import pandas as pd
import pytest

from turtle.backtest import Unit, OpenPosition, Trade, close_position


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
