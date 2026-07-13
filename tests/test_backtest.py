import pandas as pd
import pytest

from turtle.backtest import Unit, OpenPosition, Trade, close_position, enter_position
from turtle.config import AccountConfig
from turtle.indicators import IndicatorResult


def test_close_position_single_unit():
    position = OpenPosition(
        units=[Unit(entry_price=100.0, size=10.0, entry_date="2026-01-01")],
        n=5.0,
        stop_price=90.0,
    )
    trade = close_position(position, pd.Timestamp("2026-01-10"), 120.0, "2N")
    assert trade.entry_date == "2026-01-01"
    assert trade.exit_date == "2026-01-10"
    assert trade.entry_price == 100.0
    assert trade.exit_price == 120.0
    assert trade.units == 1
    assert trade.size == 10.0
    assert trade.pnl == pytest.approx(200.0)  # (120-100)*10
    assert trade.pnl_pct == pytest.approx(20.0)  # (120-100)/100*100
    assert trade.exit_reason == "2N"


def test_close_position_weighted_avg_multi_unit():
    position = OpenPosition(
        units=[
            Unit(entry_price=100.0, size=10.0, entry_date="2026-01-01"),
            Unit(entry_price=110.0, size=10.0, entry_date="2026-01-05"),
        ],
        n=5.0,
        stop_price=100.0,
    )
    trade = close_position(position, pd.Timestamp("2026-01-10"), 130.0, "10D")
    # 평단가 = (100*10 + 110*10) / 20 = 105
    assert trade.entry_price == pytest.approx(105.0)
    assert trade.entry_date == "2026-01-01"  # 최초 진입일 유지
    assert trade.units == 2
    assert trade.size == 20.0
    assert trade.pnl == pytest.approx((130.0 - 105.0) * 20.0)
    assert trade.pnl_pct == pytest.approx((130.0 - 105.0) / 105.0 * 100)


def _acct(max_units=4):
    return AccountConfig(
        total_value=100_000_000, risk_pct=0.01, max_units_per_asset=max_units,
        max_units_correlated=6, max_units_total=12,
    )


def _ind(**overrides):
    base = dict(
        close=104.0, high_55=100.0, low_20=80.0, high_20=100.0, low_10=90.0,
        tr=2.0, atr_20=2.0, adx_14=25.0, avg_volume_20=1000.0,
        avg_turnover_20=100000.0, sma_200=90.0,
    )
    base.update(overrides)
    return IndicatorResult(**base)


def _row(high, low, close):
    return pd.Series({"open": close, "high": high, "low": low, "close": close, "volume": 1000.0})


def test_enter_position_on_breakout():
    ind = _ind()
    row = _row(high=105.0, low=99.0, close=104.0)  # high(105) >= high_55(100)
    day = pd.Timestamp("2026-01-01")
    position = enter_position(row, ind, day, _acct(), min_unit=1.0, approaching_pct=0.98)
    assert position is not None
    assert len(position.units) == 1
    assert position.units[0].entry_price == 100.0  # 트리거가(high_55) 체결, 당일 고가 아님
    assert position.units[0].entry_date == "2026-01-01"
    assert position.n == 2.0
    assert position.stop_price == 100.0 - 2 * 2.0  # 96.0


def test_no_entry_when_no_breakout():
    ind = _ind()
    row = _row(high=95.0, low=90.0, close=93.0)  # 트리거 미달
    day = pd.Timestamp("2026-01-01")
    position = enter_position(row, ind, day, _acct(), min_unit=1.0, approaching_pct=0.98)
    assert position is None


def test_no_entry_when_not_tradable():
    # N이 매우 커서 유닛 사이즈가 0으로 내림됨 -> 매매 불가
    ind = _ind(atr_20=50_000_000.0)
    row = _row(high=105.0, low=99.0, close=104.0)
    day = pd.Timestamp("2026-01-01")
    position = enter_position(row, ind, day, _acct(), min_unit=1.0, approaching_pct=0.98)
    assert position is None
