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


def test_normalize_upbit_maps_and_sorts():
    from turtle.data.upbit import normalize_upbit_ohlcv
    from datetime import datetime

    rows = [
        {
            "candle_date_time_utc": "2026-07-08T00:00:00",
            "opening_price": 2.0, "high_price": 4.0, "low_price": 1.0,
            "trade_price": 3.0, "candle_acc_trade_volume": 20.0,
        },
        {
            "candle_date_time_utc": "2026-07-07T00:00:00",
            "opening_price": 1.0, "high_price": 3.0, "low_price": 0.0,
            "trade_price": 2.0, "candle_acc_trade_volume": 10.0,
        },
    ]
    out = normalize_upbit_ohlcv(
        rows, datetime(2026, 7, 7), datetime(2026, 7, 8)
    )
    assert list(out.columns) == ["open", "high", "low", "close", "volume"]
    assert list(out.index) == sorted(out.index)
    assert out["close"].iloc[0] == 2.0  # 2026-07-07 먼저
    assert out["close"].iloc[1] == 3.0  # 2026-07-08


def test_normalize_upbit_filters_by_start_end():
    from turtle.data.upbit import normalize_upbit_ohlcv
    from datetime import datetime

    rows = [
        {
            "candle_date_time_utc": "2026-07-06T00:00:00",  # start 이전 -> 제외
            "opening_price": 1.0, "high_price": 1.0, "low_price": 1.0,
            "trade_price": 1.0, "candle_acc_trade_volume": 1.0,
        },
        {
            "candle_date_time_utc": "2026-07-07T00:00:00",
            "opening_price": 2.0, "high_price": 2.0, "low_price": 2.0,
            "trade_price": 2.0, "candle_acc_trade_volume": 2.0,
        },
    ]
    out = normalize_upbit_ohlcv(
        rows, datetime(2026, 7, 7), datetime(2026, 7, 8)
    )
    assert len(out) == 1
    assert out["close"].iloc[0] == 2.0


def test_upbit_fetcher_single_page(monkeypatch):
    import turtle.data.upbit as upbit_mod

    calls = []

    class _FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return [
                {
                    "candle_date_time_utc": "2026-07-08T00:00:00",
                    "opening_price": 2.0, "high_price": 4.0, "low_price": 1.0,
                    "trade_price": 3.0, "candle_acc_trade_volume": 20.0,
                },
                {
                    "candle_date_time_utc": "2026-07-07T00:00:00",
                    "opening_price": 1.0, "high_price": 3.0, "low_price": 0.0,
                    "trade_price": 2.0, "candle_acc_trade_volume": 10.0,
                },
            ]

    def fake_get(url, params=None, timeout=None):
        calls.append(params)
        return _FakeResp()

    monkeypatch.setattr(upbit_mod.requests, "get", fake_get)
    monkeypatch.setattr(upbit_mod.time, "sleep", lambda s: None)

    fetcher = upbit_mod.UpbitFetcher()
    out = fetcher.get_ohlcv("KRW-BTC", "20260707", "20260708")

    assert len(calls) == 1  # 2건 < 200 -> 페이지네이션 없음
    assert calls[0]["market"] == "KRW-BTC"
    assert list(out.columns) == ["open", "high", "low", "close", "volume"]
    assert len(out) == 2


def test_upbit_fetcher_paginates_when_full_page(monkeypatch):
    import turtle.data.upbit as upbit_mod

    calls = []

    def _page(to_param):
        # to_param이 없으면(첫 페이지) 2026-07-08부터 200일치, 있으면 그 이전 1일치
        if to_param is None:
            base = pd.Timestamp("2026-07-08")
            return [
                {
                    "candle_date_time_utc": (base - pd.Timedelta(days=i)).strftime("%Y-%m-%dT00:00:00"),
                    "opening_price": 1.0, "high_price": 1.0, "low_price": 1.0,
                    "trade_price": 1.0, "candle_acc_trade_volume": 1.0,
                }
                for i in range(200)  # 가득 찬 페이지 -> 다음 페이지 요청 유발
            ]
        return [
            {
                "candle_date_time_utc": "2026-01-01T00:00:00",
                "opening_price": 1.0, "high_price": 1.0, "low_price": 1.0,
                "trade_price": 1.0, "candle_acc_trade_volume": 1.0,
            }
        ]

    class _FakeResp:
        def __init__(self, data):
            self._data = data

        def raise_for_status(self):
            pass

        def json(self):
            return self._data

    def fake_get(url, params=None, timeout=None):
        calls.append(params)
        return _FakeResp(_page(params.get("to") if len(calls) > 1 else None))

    monkeypatch.setattr(upbit_mod.requests, "get", fake_get)
    monkeypatch.setattr(upbit_mod.time, "sleep", lambda s: None)

    fetcher = upbit_mod.UpbitFetcher()
    fetcher.get_ohlcv("KRW-BTC", "20250101", "20260708")

    assert len(calls) == 2  # 첫 페이지 200개(가득 참) -> 두번째 페이지 요청됨
