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


def test_check_position_chandelier_ratchets_from_none():
    # 22일 고가 확보를 위해 22거래일 이상 데이터 필요. 마지막 날 이전 22일 중
    # 최고가가 나오도록 설계: 앞쪽에 스파이크를 하나 심어둔다.
    n = 25
    lows = [9000 + i * 10 for i in range(n)]
    closes = lows
    highs = list(closes)
    highs[2] = 9500  # 22일 윈도우 안에서 최고가 스파이크
    idx = pd.date_range("2026-06-01", periods=n, freq="D")
    df = pd.DataFrame(
        {"open": closes, "high": highs, "low": lows, "close": closes, "volume": [1000] * n},
        index=idx,
    )
    position = Position(
        ticker="005930", name="삼성전자", market="STOCK",
        entry_price=9000.0, n=50.0, entry_date="2026-06-01",
        chandelier_stop=None,
    )
    result = check_position(position, df)
    assert result.stop_chandelier > 0
    assert result.stop_chandelier == result.stop_chandelier  # NaN 아님


def test_check_position_chandelier_ratchet_keeps_higher_prior_value():
    lows = [9000 + i * 10 for i in range(25)]
    closes = lows
    highs = list(closes)
    idx = pd.date_range("2026-06-01", periods=25, freq="D")
    df = pd.DataFrame(
        {"open": closes, "high": highs, "low": lows, "close": closes, "volume": [1000] * 25},
        index=idx,
    )
    position = Position(
        ticker="005930", name="삼성전자", market="STOCK",
        entry_price=9000.0, n=50.0, entry_date="2026-06-01",
        chandelier_stop=999999.0,  # 신규 계산값보다 훨씬 높은 기존값
    )
    result = check_position(position, df)
    assert result.stop_chandelier == 999999.0
    assert result.breach_chandelier is True  # close(마지막날 9000+24*10=9240) <= 999999
