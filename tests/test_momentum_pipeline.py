from datetime import date
from unittest.mock import patch

import pandas as pd

from swing.momentum_exit import ExitDecision
from swing.momentum_params import MomentumScreenerParams
from swing.momentum_pipeline import run
from swing.momentum_positions import MomentumPosition


def _df(n=200, close=10000.0, volume=1_000_000.0):
    idx = pd.date_range(end="2026-08-19", periods=n, freq="B")
    return pd.DataFrame(
        {"open": close, "high": close, "low": close, "close": close, "volume": volume},
        index=idx,
    )


class _Fetcher:
    def __init__(self, frames):
        self.frames = frames

    def get_ohlcv(self, ticker, start, end):
        return self.frames[ticker]


def _run(fetcher, universe, positions=None, exits_map=None, send=False, regime=1.5):
    with patch("swing.momentum_pipeline._resolve_target", return_value=date(2026, 8, 19)), \
         patch("swing.momentum_pipeline.build_momentum_universe", return_value=universe), \
         patch("swing.momentum_pipeline.market_momentum", return_value=regime), \
         patch("swing.momentum_pipeline.has_fresh_signal", return_value=True), \
         patch("swing.momentum_pipeline._ticker_name", return_value="테스트종목"), \
         patch("swing.momentum_pipeline.get_open_positions", return_value=positions or []), \
         patch(
             "swing.momentum_pipeline.check_exit",
             side_effect=lambda entry, stop, entry_date, df, p: (exits_map or {}).get(
                 entry_date, ExitDecision("HOLD", 0.0, 0, date(2026, 8, 19))
             ),
         ):
        return run(None, MomentumScreenerParams(min_bars=1), fetcher, "db", "token", "chat", send=send)


def test_candidate_appears_in_report():
    f = _Fetcher({"000001": _df()})
    text = _run(f, [("000001", "KOSPI")])
    assert "테스트종목" in text
    assert "신규 후보 1종목" in text


def test_no_signal_yields_empty_candidates():
    f = _Fetcher({"000001": _df()})
    with patch("swing.momentum_pipeline._resolve_target", return_value=date(2026, 8, 19)), \
         patch("swing.momentum_pipeline.build_momentum_universe", return_value=[("000001", "KOSPI")]), \
         patch("swing.momentum_pipeline.market_momentum", return_value=None), \
         patch("swing.momentum_pipeline.has_fresh_signal", return_value=False), \
         patch("swing.momentum_pipeline.get_open_positions", return_value=[]):
        text = run(None, MomentumScreenerParams(min_bars=1), f, "db", "token", "chat", send=False)
    assert "신규 후보 0종목" in text
    assert "N/A" in text


def test_ticker_failure_does_not_stop_batch():
    class _Boom(_Fetcher):
        def get_ohlcv(self, ticker, start, end):
            if ticker == "000001":
                raise RuntimeError("조회 실패")
            return self.frames[ticker]

    f = _Boom({"000002": _df()})
    text = _run(f, [("000001", "KOSPI"), ("000002", "KOSDAQ")])
    assert "신규 후보 1종목" in text


def test_name_lookup_failure_drops_candidate():
    f = _Fetcher({"000001": _df()})
    with patch("swing.momentum_pipeline._resolve_target", return_value=date(2026, 8, 19)), \
         patch("swing.momentum_pipeline.build_momentum_universe", return_value=[("000001", "KOSPI")]), \
         patch("swing.momentum_pipeline.market_momentum", return_value=1.0), \
         patch("swing.momentum_pipeline.has_fresh_signal", return_value=True), \
         patch("swing.momentum_pipeline._ticker_name", return_value=None), \
         patch("swing.momentum_pipeline.get_open_positions", return_value=[]):
        text = run(None, MomentumScreenerParams(min_bars=1), f, "db", "token", "chat", send=False)
    assert "신규 후보 0종목" in text


def test_position_check_failure_is_isolated():
    """포지션 조회 실패해도 신규 후보 스캔은 계속된다."""
    f = _Fetcher({"000001": _df()})
    with patch("swing.momentum_pipeline._resolve_target", return_value=date(2026, 8, 19)), \
         patch("swing.momentum_pipeline.build_momentum_universe", return_value=[("000001", "KOSPI")]), \
         patch("swing.momentum_pipeline.market_momentum", return_value=1.0), \
         patch("swing.momentum_pipeline.has_fresh_signal", return_value=True), \
         patch("swing.momentum_pipeline._ticker_name", return_value="테스트종목"), \
         patch("swing.momentum_pipeline.get_open_positions", side_effect=RuntimeError("DB 실패")):
        text = run(None, MomentumScreenerParams(min_bars=1), f, "db", "token", "chat", send=False)
    assert "신규 후보 1종목" in text
    assert "청산 알림 0건" in text


def test_exit_alert_included_for_stop_and_time_only():
    pos_stop = MomentumPosition("000003", "손절종목", "KOSPI", 10000.0, 7500.0, 10, "2026-08-01")
    pos_hold = MomentumPosition("000004", "보유종목", "KOSPI", 10000.0, 7500.0, 10, "2026-08-15")
    f = _Fetcher({"000003": _df(), "000004": _df()})
    exits_map = {
        "2026-08-01": ExitDecision("STOP", 7500.0, 5, date(2026, 8, 19)),
        "2026-08-15": ExitDecision("HOLD", 10100.0, 2, date(2026, 8, 19)),
    }
    with patch("swing.momentum_pipeline._resolve_target", return_value=date(2026, 8, 19)), \
         patch("swing.momentum_pipeline.build_momentum_universe", return_value=[]), \
         patch("swing.momentum_pipeline.market_momentum", return_value=1.0), \
         patch("swing.momentum_pipeline.get_open_positions", return_value=[pos_stop, pos_hold]), \
         patch(
             "swing.momentum_pipeline.check_exit",
             side_effect=lambda entry, stop, entry_date, df, p: exits_map[entry_date],
         ):
        text = run(None, MomentumScreenerParams(min_bars=1), f, "db", "token", "chat", send=False)
    assert "청산 알림 1건" in text
    assert "손절종목" in text
    assert "보유종목" not in text  # HOLD는 알림 대상 아님


def test_report_sent_when_send_true():
    f = _Fetcher({"000001": _df()})
    with patch("swing.momentum_pipeline._resolve_target", return_value=date(2026, 8, 19)), \
         patch("swing.momentum_pipeline.build_momentum_universe", return_value=[("000001", "KOSPI")]), \
         patch("swing.momentum_pipeline.market_momentum", return_value=1.0), \
         patch("swing.momentum_pipeline.has_fresh_signal", return_value=True), \
         patch("swing.momentum_pipeline._ticker_name", return_value="테스트종목"), \
         patch("swing.momentum_pipeline.get_open_positions", return_value=[]), \
         patch("swing.momentum_pipeline.send_telegram") as send_mock:
        run(None, MomentumScreenerParams(min_bars=1), f, "db", "token", "chat", send=True)
    send_mock.assert_called_once()
