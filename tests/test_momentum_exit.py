import pandas as pd
import pytest

from swing.momentum_exit import check_exit
from swing.momentum_params import MomentumScreenerParams


def _df(bars, start="2024-01-02"):
    """bars: (open, high, low, close, volume) 튜플 리스트."""
    idx = pd.date_range(start=start, periods=len(bars), freq="B")
    return pd.DataFrame(
        list(bars), columns=["open", "high", "low", "close", "volume"], index=idx
    ).astype(float)


ENTRY = (10000, 10000, 9900, 10000, 100_000)
FLAT = (10000, 10100, 9900, 10000, 100_000)
UP = (10050, 10200, 10000, 10150, 100_000)


def test_hold_days_reached_exits_at_close():
    p = MomentumScreenerParams(hold_days=3, stop_pct=25.0)
    bars = [ENTRY, FLAT, FLAT, UP]  # entry(0) + 3거래일
    df = _df(bars)
    d = check_exit(10000.0, 7500.0, "2024-01-02", df, p)
    assert d.action == "TIME"
    assert d.price == 10150.0
    assert d.days_held == 3
    assert d.as_of == df.index[3].date()


def test_before_hold_days_reached_returns_hold():
    p = MomentumScreenerParams(hold_days=5, stop_pct=25.0)
    bars = [ENTRY, FLAT, FLAT]  # 진입 후 2거래일만 경과
    df = _df(bars)
    d = check_exit(10000.0, 7500.0, "2024-01-02", df, p)
    assert d.action == "HOLD"
    assert d.days_held == 2
    assert d.price == 10000.0


def test_low_touch_triggers_stop_at_stop_price():
    p = MomentumScreenerParams(hold_days=10, stop_pct=25.0)
    stop = 7500.0
    breach = (7600, 7700, 7400, 7550, 100_000)  # 저가 7400 <= 7500
    df = _df([ENTRY, FLAT, breach])
    d = check_exit(10000.0, stop, "2024-01-02", df, p)
    assert d.action == "STOP"
    assert d.price == stop
    assert d.days_held == 2


def test_gap_down_open_fills_at_open_not_stop_price():
    p = MomentumScreenerParams(hold_days=10, stop_pct=25.0)
    stop = 7500.0
    gap = (7000, 7100, 6900, 7000, 100_000)  # 시가부터 손절가 아래
    df = _df([ENTRY, gap])
    d = check_exit(10000.0, stop, "2024-01-02", df, p)
    assert d.action == "STOP"
    assert d.price == 7000.0  # 시가 체결, 손절가(7500)가 아님
    assert d.days_held == 1


def test_stop_takes_priority_over_time_on_expiry_day():
    p = MomentumScreenerParams(hold_days=1, stop_pct=25.0)
    stop = 7500.0
    breach = (7600, 7700, 7400, 7550, 100_000)
    df = _df([ENTRY, breach])  # 만기일(1일차)에 손절선도 터치
    d = check_exit(10000.0, stop, "2024-01-02", df, p)
    assert d.action == "STOP"


def test_halted_bar_is_skipped_for_stop_check():
    p = MomentumScreenerParams(hold_days=10, stop_pct=25.0)
    stop = 7500.0
    halted = (0, 0, 0, 10000, 0)  # 거래정지: 저가 0이지만 손절 아님
    df = _df([ENTRY, halted, FLAT])
    d = check_exit(10000.0, stop, "2024-01-02", df, p)
    assert d.action == "HOLD"  # 정지봉은 건너뛰고, 만기 전이므로 HOLD


def test_expiry_day_halted_walks_back_to_prior_close():
    p = MomentumScreenerParams(hold_days=2, stop_pct=25.0)
    stop = 7500.0
    halted = (0, 0, 0, 10000, 0)
    df = _df([ENTRY, FLAT, halted])  # 만기일(2일차)이 거래정지
    d = check_exit(10000.0, stop, "2024-01-02", df, p)
    assert d.action == "TIME"
    assert d.price == 10000.0  # 직전 거래일(1일차) 종가로 청산
    assert d.days_held == 1
    assert d.as_of == df.index[1].date()


def test_entry_date_not_in_index_raises():
    p = MomentumScreenerParams(hold_days=10, stop_pct=25.0)
    df = _df([ENTRY, FLAT])
    with pytest.raises(ValueError):
        check_exit(10000.0, 7500.0, "2099-01-01", df, p)
