from datetime import date
from unittest.mock import patch

import pandas as pd

from swing.params import SwingParams
from swing.pipeline import run

QUIET_LONG = (10_000, 10_100, 9_900, 10_000, 200_000)
QUIET_BASE = (10_000, 10_100, 9_900, 10_000, 100_000)
POLE = (10_000, 10_750, 9_990, 10_700, 300_000)
HOLD = (10_720, 10_800, 10_710, 10_750, 60_000)


def _frame(bars, end="2026-08-11"):
    idx = pd.date_range(end=end, periods=len(bars), freq="B")
    return pd.DataFrame(
        list(bars), columns=["open", "high", "low", "close", "volume"], index=idx
    ).astype(float)



# required_bars(=30+60+10+1=101) 확보용 여유 이력. 브리프 원안(장기창60+바닥30+장대양봉1
# +눌림3)은 94봉뿐이라 게이트에 걸려 즉시 None이 나온다 — tests/test_swing_screener.py의
# PAD와 동일한 이유로 여기서도 보정한다 (임계값이 아니라 픽스처 길이 결함).
_PAD = (QUIET_LONG,) * 10


def _hit_df(scale=1.0):
    """조건을 만족하는 프레임. scale로 거래대금 크기를 바꿔 정렬을 검증한다."""
    bars = list(_PAD) + [QUIET_LONG] * 60 + [QUIET_BASE] * 30 + [POLE] + [HOLD] * 3
    scaled = [(o, h, lo, c, v * scale) for (o, h, lo, c, v) in bars]
    return _frame(scaled)


def _miss_df():
    return _frame([QUIET_BASE] * 101)


class _Fetcher:
    def __init__(self, frames):
        self.frames = frames
        self.calls = []

    def get_ohlcv(self, ticker, start, end):
        self.calls.append(ticker)
        return self.frames[ticker]


def _run(fetcher, universe, net_buy=1.0e9, send=False):
    with patch("swing.pipeline.build_swing_universe", return_value=universe), \
         patch("swing.pipeline._resolve_target", return_value=date(2026, 8, 11)), \
         patch("swing.pipeline.get_investor_net_buy_value", return_value=net_buy):
        return run(None, SwingParams(), fetcher, "token", "chat", send=send)


def test_candidate_appears_in_report():
    f = _Fetcher({"000001": _hit_df()})
    text = _run(f, [("000001", "히트", "KOSPI")])
    assert "히트" in text
    assert "후보 1종목" in text


def test_non_matching_ticker_filtered_out():
    f = _Fetcher({"000002": _miss_df()})
    text = _run(f, [("000002", "미스", "KOSDAQ")])
    assert "후보 없음" in text


def test_candidates_sorted_by_turnover_desc():
    f = _Fetcher({"000001": _hit_df(scale=1.0), "000002": _hit_df(scale=5.0)})
    text = _run(f, [("000001", "작은거래", "KOSPI"), ("000002", "큰거래", "KOSPI")])
    assert text.index("큰거래") < text.index("작은거래")


def test_liquidity_floor_drops_thin_names():
    f = _Fetcher({"000001": _hit_df(scale=0.0001)})
    text = _run(f, [("000001", "얇은종목", "KOSDAQ")])
    assert "후보 없음" in text


def test_ticker_failure_does_not_stop_batch():
    class _Boom(_Fetcher):
        def get_ohlcv(self, ticker, start, end):
            if ticker == "000001":
                raise RuntimeError("조회 실패")
            return self.frames[ticker]

    f = _Boom({"000002": _hit_df()})
    text = _run(f, [("000001", "터짐", "KOSPI"), ("000002", "정상", "KOSPI")])
    assert "정상" in text
    assert "후보 1종목" in text


def test_net_buy_failure_keeps_candidate_as_na():
    f = _Fetcher({"000001": _hit_df()})
    with patch("swing.pipeline.build_swing_universe", return_value=[("000001", "히트", "KOSPI")]), \
         patch("swing.pipeline._resolve_target", return_value=date(2026, 8, 11)), \
         patch("swing.pipeline.get_investor_net_buy_value", side_effect=RuntimeError("없음")):
        text = run(None, SwingParams(), f, "token", "chat", send=False)
    assert "히트" in text
    assert "N/A" in text


def test_empty_report_not_sent_when_notify_empty_false():
    f = _Fetcher({"000002": _miss_df()})
    with patch("swing.pipeline.build_swing_universe", return_value=[("000002", "미스", "KOSPI")]), \
         patch("swing.pipeline._resolve_target", return_value=date(2026, 8, 11)), \
         patch("swing.pipeline.send_telegram") as send_mock:
        run(None, SwingParams(notify_empty=False), f, "token", "chat", send=True)
    send_mock.assert_not_called()


def test_report_is_sent_when_candidates_exist():
    f = _Fetcher({"000001": _hit_df()})
    with patch("swing.pipeline.build_swing_universe", return_value=[("000001", "히트", "KOSPI")]), \
         patch("swing.pipeline._resolve_target", return_value=date(2026, 8, 11)), \
         patch("swing.pipeline.get_investor_net_buy_value", return_value=1.0e9), \
         patch("swing.pipeline.send_telegram") as send_mock:
        run(None, SwingParams(), f, "token", "chat", send=True)
    send_mock.assert_called_once()
