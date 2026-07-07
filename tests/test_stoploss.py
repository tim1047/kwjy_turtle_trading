import pandas as pd

from turtle.positions.store import Position
from turtle.stoploss import check_position


def _make_df(lows: list[float], closes: list[float]) -> pd.DataFrame:
    n = len(lows)
    idx = pd.date_range("2026-06-01", periods=n, freq="D")
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 100 for c in closes],
            "low": lows,
            "close": closes,
            "volume": [1000] * n,
        },
        index=idx,
    )


def test_check_position_no_breach():
    # rolling_low는 shift(1) 기반이라 마지막 날 이전 10일 중 최저 low가 9000.
    lows = [9500, 9400, 9300, 9200, 9100, 9050, 9000, 9600, 9700, 9800, 9900]
    closes = lows
    df = _make_df(lows, closes)
    position = Position(
        ticker="005930", name="삼성전자", market="STOCK",
        entry_price=10000.0, n=500.0, entry_date="2026-06-01",
    )
    result = check_position(position, df)
    assert result.stop_2n == 10000.0 - 2 * 500.0  # 9000.0
    assert result.stop_10d == 9000.0
    assert result.close == 9900.0
    assert result.breach_2n is False
    assert result.breach_10d is False


def test_check_position_breach_both():
    lows = [9500, 9400, 9300, 9200, 9100, 9050, 9000, 9600, 9700, 9800, 8500]
    closes = lows
    df = _make_df(lows, closes)
    position = Position(
        ticker="005930", name="삼성전자", market="STOCK",
        entry_price=10000.0, n=500.0, entry_date="2026-06-01",
    )
    result = check_position(position, df)
    assert result.close == 8500.0
    assert result.breach_2n is True  # 8500 <= 9000
    assert result.breach_10d is True  # 8500 <= 9000 (10일 저가)
