"""기간(--start/--end) 스캔 모드 테스트."""

from datetime import date, timedelta
from unittest.mock import patch

import pandas as pd
import pytest

from swing.momentum_params import MomentumScreenerParams
from swing.momentum_pipeline import run_range

_BDAYS = [date(2026, 8, 17), date(2026, 8, 18), date(2026, 8, 19)]


def _df(n=400, close=10000.0, volume=1_000_000.0):
    idx = pd.date_range(end="2026-08-19", periods=n, freq="B")
    return pd.DataFrame(
        {"open": close, "high": close, "low": close, "close": close, "volume": volume},
        index=idx,
    )


class _CountingFetcher:
    """호출 인자를 기록하는 스텁. start/end와 무관하게 전체 프레임을 준다."""

    def __init__(self, frames):
        self.frames = frames
        self.calls: list[tuple[str, str, str]] = []

    def get_ohlcv(self, ticker, start, end):
        self.calls.append((ticker, start, end))
        return self.frames[ticker]


def _run_range(fetcher, universe, bdays=None, **patches):
    seen = patches.pop("seen", None)

    def _signal(df, p):
        if seen is not None:
            seen.append(df)
        return True

    with patch("swing.momentum_pipeline.get_business_days", return_value=bdays if bdays is not None else _BDAYS), \
         patch("swing.momentum_pipeline.build_momentum_universe", return_value=universe), \
         patch("swing.momentum_pipeline.market_momentum", return_value=1.5), \
         patch("swing.momentum_pipeline.has_fresh_signal", side_effect=_signal), \
         patch("swing.momentum_pipeline._ticker_name", return_value="테스트종목"):
        return run_range(
            date(2026, 8, 17),
            date(2026, 8, 19),
            MomentumScreenerParams(min_bars=1),
            fetcher,
        )


def test_range_reports_every_business_day():
    f = _CountingFetcher({"000001": _df()})
    text = _run_range(f, [("000001", "KOSPI")])
    for d in ("2026-08-17", "2026-08-18", "2026-08-19"):
        assert d in text


def test_range_fetches_each_ticker_once():
    """기간 전체를 한 번에 받아 날짜별로 잘라 쓴다 — 하루당 재조회하지 않는다."""
    f = _CountingFetcher({"000001": _df(), "000002": _df()})
    _run_range(f, [("000001", "KOSPI"), ("000002", "KOSDAQ")])
    assert [c[0] for c in f.calls].count("000001") == 1
    assert [c[0] for c in f.calls].count("000002") == 1


def test_range_slices_history_to_each_as_of_date():
    """날짜별 판정에 그 날 이후 데이터가 새지 않는다 (룩어헤드 방지)."""
    seen: list[pd.DataFrame] = []
    f = _CountingFetcher({"000001": _df()})
    _run_range(f, [("000001", "KOSPI")], seen=seen)
    assert [df.index[-1].date() for df in seen] == _BDAYS


def test_range_honors_requested_lookback_start():
    """단일 날짜 실행과 같은 룩백 창을 쓴다 — 앞쪽 이력이 더 붙지 않는다."""
    seen: list[pd.DataFrame] = []
    f = _CountingFetcher({"000001": _df()})
    _run_range(f, [("000001", "KOSPI")], seen=seen)
    first = seen[0]
    assert first.index[0].date() >= date(2026, 8, 17) - timedelta(days=380)


def test_range_skips_exit_checks():
    """보유 포지션은 현재 시점 기준이라 과거 날짜 판정에 쓰지 않는다."""
    f = _CountingFetcher({"000001": _df()})
    with patch("swing.momentum_pipeline.get_open_positions") as pos_mock:
        _run_range(f, [("000001", "KOSPI")])
    pos_mock.assert_not_called()


def test_range_never_sends_telegram():
    f = _CountingFetcher({"000001": _df()})
    with patch("swing.momentum_pipeline.send_telegram") as send_mock:
        _run_range(f, [("000001", "KOSPI")])
    send_mock.assert_not_called()


def test_range_without_business_days_raises():
    f = _CountingFetcher({"000001": _df()})
    with pytest.raises(ValueError):
        _run_range(f, [("000001", "KOSPI")], bdays=[])


def test_range_builds_universe_per_business_day():
    """유니버스는 날짜별 시총 단면이다 — 같은 날짜면 단일 실행과 같은 유니버스를 쓴다."""
    f = _CountingFetcher({"000001": _df()})
    calls: list[str] = []

    def _universe(target):
        calls.append(target)
        return [("000001", "KOSPI")]

    with patch("swing.momentum_pipeline.get_business_days", return_value=_BDAYS), \
         patch("swing.momentum_pipeline.build_momentum_universe", side_effect=_universe), \
         patch("swing.momentum_pipeline.market_momentum", return_value=1.5), \
         patch("swing.momentum_pipeline.has_fresh_signal", return_value=True), \
         patch("swing.momentum_pipeline._ticker_name", return_value="테스트종목"):
        run_range(date(2026, 8, 17), date(2026, 8, 19), MomentumScreenerParams(min_bars=1), f)

    assert calls == ["20260817", "20260818", "20260819"]
