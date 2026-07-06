import pandas as pd
import pytest

from turtle.data.base import CachingFetcher, DataFetcher, normalize_pykrx_ohlcv, with_retry
from turtle.data.krx import KrxFetcher


def test_normalize_maps_korean_columns():
    idx = pd.to_datetime(["2026-01-02", "2026-01-03"])
    raw = pd.DataFrame(
        {"시가": [1, 2], "고가": [3, 4], "저가": [0, 1], "종가": [2, 3], "거래량": [10, 20]},
        index=idx,
    )
    out = normalize_pykrx_ohlcv(raw)
    assert list(out.columns) == ["open", "high", "low", "close", "volume"]
    assert out["high"].iloc[1] == 4
    assert str(out.index.dtype).startswith("datetime64")


def test_normalize_ignores_extra_columns_and_casts_float():
    # pykrx also returns a 등락률 (change rate) column we don't use;
    # normalize must drop it and coerce numeric columns to float.
    idx = pd.to_datetime(["2026-01-02", "2026-01-03"])
    raw = pd.DataFrame(
        {
            "시가": [1, 2],
            "고가": [3, 4],
            "저가": [0, 1],
            "종가": [2, 3],
            "거래량": [10, 20],
            "등락률": [1.5, -2.1],
        },
        index=idx,
    )
    out = normalize_pykrx_ohlcv(raw)
    assert list(out.columns) == ["open", "high", "low", "close", "volume"]
    assert out["open"].dtype == float
    assert out["volume"].dtype == float


def test_normalize_sorts_ascending_by_date():
    idx = pd.to_datetime(["2026-01-03", "2026-01-02"])
    raw = pd.DataFrame(
        {"시가": [2, 1], "고가": [4, 3], "저가": [1, 0], "종가": [3, 2], "거래량": [20, 10]},
        index=idx,
    )
    out = normalize_pykrx_ohlcv(raw)
    assert list(out.index) == sorted(out.index)
    assert out["close"].iloc[0] == 2  # the 2026-01-02 row, sorted first


def test_with_retry_succeeds_after_failures():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ValueError("boom")
        return "ok"

    assert with_retry(flaky, retries=3, base_delay=0) == "ok"
    assert calls["n"] == 3


def test_with_retry_raises_after_exhausting():
    def always_fail():
        raise ValueError("nope")

    with pytest.raises(ValueError):
        with_retry(always_fail, retries=3, base_delay=0)


def test_with_retry_does_not_call_more_than_retries_times():
    calls = {"n": 0}

    def always_fail():
        calls["n"] += 1
        raise ValueError("nope")

    with pytest.raises(ValueError):
        with_retry(always_fail, retries=3, base_delay=0)
    assert calls["n"] == 3


def test_with_retry_backoff_sleeps_with_exponential_delay(monkeypatch):
    import turtle.data.base as base

    sleeps = []
    monkeypatch.setattr(base.time, "sleep", lambda s: sleeps.append(s))

    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ValueError("boom")
        return "ok"

    assert with_retry(flaky, retries=3, base_delay=1.0) == "ok"
    assert sleeps == [1.0, 2.0]


def test_krx_fetcher_calls_pykrx_and_normalizes(monkeypatch):
    import turtle.data.krx as krx

    idx = pd.to_datetime(["2026-01-02", "2026-01-03"])
    raw = pd.DataFrame(
        {"시가": [1, 2], "고가": [3, 4], "저가": [0, 1], "종가": [2, 3], "거래량": [10, 20]},
        index=idx,
    )
    calls = []

    def fake_get_market_ohlcv(start, end, ticker):
        calls.append((start, end, ticker))
        return raw

    monkeypatch.setattr(krx.stock, "get_market_ohlcv", fake_get_market_ohlcv)
    monkeypatch.setattr(krx.time, "sleep", lambda s: None)  # skip real throttle wait

    fetcher = KrxFetcher(throttle=0.2)
    out = fetcher.get_ohlcv("005930", "20260102", "20260103")

    assert calls == [("20260102", "20260103", "005930")]
    assert list(out.columns) == ["open", "high", "low", "close", "volume"]
    assert out["close"].iloc[0] == 2


def test_krx_fetcher_retries_then_succeeds(monkeypatch):
    import turtle.data.krx as krx

    idx = pd.to_datetime(["2026-01-02"])
    raw = pd.DataFrame(
        {"시가": [1], "고가": [3], "저가": [0], "종가": [2], "거래량": [10]}, index=idx
    )
    calls = {"n": 0}

    def flaky_get_market_ohlcv(start, end, ticker):
        calls["n"] += 1
        if calls["n"] < 2:
            raise ConnectionError("network blip")
        return raw

    monkeypatch.setattr(krx.stock, "get_market_ohlcv", flaky_get_market_ohlcv)
    monkeypatch.setattr(krx.time, "sleep", lambda s: None)

    fetcher = KrxFetcher()
    out = fetcher.get_ohlcv("005930", "20260102", "20260102")

    assert calls["n"] == 2
    assert out["open"].iloc[0] == 1


class _CountingFetcher(DataFetcher):
    """(ticker, start, end)별 고유 DataFrame을 반환하며 호출 횟수를 기록하는 페이크."""

    def __init__(self):
        self.calls = []

    def get_ohlcv(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        self.calls.append((ticker, start, end))
        return pd.DataFrame({"close": [len(self.calls)]})


def test_caching_fetcher_hits_cache_on_identical_args():
    inner = _CountingFetcher()
    fetcher = CachingFetcher(inner)

    first = fetcher.get_ohlcv("005930", "20260101", "20260201")
    second = fetcher.get_ohlcv("005930", "20260101", "20260201")

    assert inner.calls == [("005930", "20260101", "20260201")]
    assert first["close"].iloc[0] == second["close"].iloc[0]
    pd.testing.assert_frame_equal(first, second)


def test_caching_fetcher_different_ticker_triggers_new_call():
    inner = _CountingFetcher()
    fetcher = CachingFetcher(inner)

    fetcher.get_ohlcv("005930", "20260101", "20260201")
    fetcher.get_ohlcv("000660", "20260101", "20260201")

    assert len(inner.calls) == 2
    assert inner.calls == [
        ("005930", "20260101", "20260201"),
        ("000660", "20260101", "20260201"),
    ]


def test_caching_fetcher_different_date_range_triggers_new_call():
    inner = _CountingFetcher()
    fetcher = CachingFetcher(inner)

    fetcher.get_ohlcv("005930", "20260101", "20260201")
    fetcher.get_ohlcv("005930", "20260102", "20260201")

    assert len(inner.calls) == 2
