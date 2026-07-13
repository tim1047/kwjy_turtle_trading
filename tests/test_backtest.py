import pandas as pd
import pytest

from turtle.backtest import Unit, OpenPosition, Trade, close_position, enter_position, add_pyramid_unit
from turtle.config import AccountConfig
from turtle.indicators import IndicatorResult
from turtle.trading_params import compute_trading_params


def test_close_position_single_unit():
    position = OpenPosition(
        units=[Unit(entry_price=100.0, size=10.0, entry_date="2026-01-01")],
        n=5.0,
        stop_price=90.0,
        chandelier_stop=-1e18,
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
        chandelier_stop=-1e18,
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
        close=104.0, high_55=100.0, low_20=80.0, high_20=100.0, high_22=100.0,
        low_10=90.0, tr=2.0, atr_20=2.0, adx_14=25.0, avg_volume_20=1000.0,
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


def test_enter_position_initializes_chandelier_stop():
    ind = _ind(high_22=100.0, atr_20=2.0)
    row = _row(high=105.0, low=99.0, close=104.0)
    day = pd.Timestamp("2026-01-01")
    position = enter_position(row, ind, day, _acct(), min_unit=1.0, approaching_pct=0.98)
    assert position.chandelier_stop == pytest.approx(100.0 - 3 * 2.0)  # 94.0


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


def test_add_pyramid_unit_when_price_reaches_level():
    position = OpenPosition(
        units=[Unit(entry_price=100.0, size=10000.0, entry_date="2026-01-01")],
        n=2.0,
        stop_price=96.0,
        chandelier_stop=-1e18,
    )
    # pyramid_1_price = 100 + 0.5*2 = 101
    row = pd.Series({"open": 101.0, "high": 102.0, "low": 100.5, "close": 101.0})
    day = pd.Timestamp("2026-01-02")
    add_pyramid_unit(position, row, day, _acct(), min_unit=1.0)
    assert len(position.units) == 2
    assert position.units[1].entry_price == 101.0
    assert position.units[1].entry_date == "2026-01-02"
    assert position.stop_price == 101.0 - 2 * 2.0  # 97.0


def test_no_pyramid_when_price_below_level():
    position = OpenPosition(
        units=[Unit(entry_price=100.0, size=10000.0, entry_date="2026-01-01")],
        n=2.0,
        stop_price=96.0,
        chandelier_stop=-1e18,
    )
    row = pd.Series({"open": 100.5, "high": 100.8, "low": 100.0, "close": 100.5})  # < 101
    day = pd.Timestamp("2026-01-02")
    add_pyramid_unit(position, row, day, _acct(), min_unit=1.0)
    assert len(position.units) == 1
    assert position.stop_price == 96.0


def test_no_pyramid_when_max_units_reached():
    position = OpenPosition(
        units=[
            Unit(entry_price=100.0, size=1.0, entry_date="2026-01-01"),
            Unit(entry_price=101.0, size=1.0, entry_date="2026-01-02"),
        ],
        n=2.0,
        stop_price=97.0,
        chandelier_stop=-1e18,
    )
    row = pd.Series({"open": 110.0, "high": 111.0, "low": 109.0, "close": 110.0})
    day = pd.Timestamp("2026-01-03")
    add_pyramid_unit(position, row, day, _acct(max_units=2), min_unit=1.0)
    assert len(position.units) == 2  # max_units_per_asset=2라 추가 안 됨
    assert position.stop_price == 97.0


def test_no_pyramid_when_all_three_levels_used():
    position = OpenPosition(
        units=[
            Unit(entry_price=100.0, size=1.0, entry_date="2026-01-01"),
            Unit(entry_price=101.0, size=1.0, entry_date="2026-01-02"),
            Unit(entry_price=102.0, size=1.0, entry_date="2026-01-03"),
            Unit(entry_price=103.0, size=1.0, entry_date="2026-01-04"),
        ],
        n=2.0,
        stop_price=99.0,
        chandelier_stop=-1e18,
    )
    row = pd.Series({"open": 200.0, "high": 201.0, "low": 199.0, "close": 200.0})
    day = pd.Timestamp("2026-01-05")
    add_pyramid_unit(position, row, day, _acct(max_units=4), min_unit=1.0)
    assert len(position.units) == 4  # 이미 4유닛(max) -> 더 추가 안 됨


def test_check_exit_no_breach():
    from turtle.backtest import check_exit

    position = OpenPosition(units=[Unit(100.0, 10.0, "2026-01-01")], n=2.0, stop_price=96.0, chandelier_stop=-1e18)
    row = pd.Series({"close": 99.0})
    trade = check_exit(position, row, _ind(low_10=95.0), pd.Timestamp("2026-01-05"))
    assert trade is None


def test_check_exit_breach_2n_only():
    from turtle.backtest import check_exit

    position = OpenPosition(units=[Unit(100.0, 10.0, "2026-01-01")], n=2.0, stop_price=96.0, chandelier_stop=-1e18)
    row = pd.Series({"close": 95.0})  # <= stop_price(96), > low_10(90)
    trade = check_exit(position, row, _ind(low_10=90.0), pd.Timestamp("2026-01-05"))
    assert trade is not None
    assert trade.exit_reason == "2N"
    assert trade.exit_price == 95.0
    assert trade.exit_date == "2026-01-05"


def test_check_exit_breach_10d_only():
    from turtle.backtest import check_exit

    position = OpenPosition(units=[Unit(100.0, 10.0, "2026-01-01")], n=2.0, stop_price=80.0, chandelier_stop=-1e18)
    row = pd.Series({"close": 85.0})  # > stop_price(80), <= low_10(90)
    trade = check_exit(position, row, _ind(low_10=90.0), pd.Timestamp("2026-01-05"))
    assert trade is not None
    assert trade.exit_reason == "10D"


def test_check_exit_breach_both():
    from turtle.backtest import check_exit

    position = OpenPosition(units=[Unit(100.0, 10.0, "2026-01-01")], n=2.0, stop_price=96.0, chandelier_stop=-1e18)
    row = pd.Series({"close": 80.0})  # <= both
    trade = check_exit(position, row, _ind(low_10=90.0), pd.Timestamp("2026-01-05"))
    assert trade is not None
    assert trade.exit_reason == "2N+10D"


def test_check_exit_breach_chandelier_only():
    from turtle.backtest import check_exit

    position = OpenPosition(
        units=[Unit(100.0, 10.0, "2026-01-01")], n=2.0, stop_price=50.0,
        chandelier_stop=90.0,
    )
    row = pd.Series({"close": 85.0})  # <= chandelier(90), > stop_price(50), > low_10
    trade = check_exit(position, row, _ind(low_10=80.0), pd.Timestamp("2026-01-05"))
    assert trade is not None
    assert trade.exit_reason == "CHANDELIER"


def test_check_exit_breach_all_three():
    from turtle.backtest import check_exit

    position = OpenPosition(
        units=[Unit(100.0, 10.0, "2026-01-01")], n=2.0, stop_price=96.0,
        chandelier_stop=97.0,
    )
    row = pd.Series({"close": 80.0})  # <= all three
    trade = check_exit(position, row, _ind(low_10=90.0), pd.Timestamp("2026-01-05"))
    assert trade is not None
    assert trade.exit_reason == "2N+10D+CHANDELIER"


from turtle.backtest import run_backtest
from turtle.indicators import compute_indicators


def _flat_then_breakout_df(breakout_idx: int, n: int, post_breakout_closes: dict):
    """기본 흐름은 high=101/low=99/close=100 평평한 흐름. breakout_idx일에 high를
    트리거(101) 위로 살짝 올리고, post_breakout_closes={offset: close}로 이후
    일자의 종가를 덮어쓴다 (high=close+1, low=close-1 패턴 유지).

    row 200(테스트의 start_idx)부터 breakout_idx 직전까지는 high를 100.9로 살짝
    눌러둔다 — 그렇지 않으면 트레일링 high_55도 101.0이라 오늘 high(101.0)가
    `>=` 비교로 그 값과 정확히 같아져, 평가되는 첫날(row200)부터 스퓨리어스
    돌파가 발생한다. row 200 이전(0~199) 구간은 101.0을 유지해 트레일링
    55일 윈도우 안에서 저항선(high_55=101.0) 역할을 하도록 남겨둔다."""
    idx = pd.bdate_range("2020-01-01", periods=n)
    highs = [101.0] * n
    lows = [99.0] * n
    closes = [100.0] * n
    for i in range(200, breakout_idx):
        highs[i] = 100.9
    highs[breakout_idx] = 101.5
    for offset, close in post_breakout_closes.items():
        i = breakout_idx + offset
        closes[i] = close
        highs[i] = close + 1.0
        lows[i] = close - 1.0
    return pd.DataFrame(
        {"open": closes, "high": highs, "low": lows, "close": closes, "volume": [1_000_000.0] * n},
        index=idx,
    )


def test_run_backtest_entry_pyramid_and_exit():
    n = 230
    breakout_idx = 205  # sma_200 워밍업(200일) 이후, 여유 있게
    df = _flat_then_breakout_df(
        breakout_idx, n,
        post_breakout_closes={1: 103.0, 2: 80.0},  # 1일 후 피라미드 추가, 2일 후 급락 청산
    )
    start = df.index[200].strftime("%Y%m%d")
    end = df.index[breakout_idx + 3].strftime("%Y%m%d")

    trades = run_backtest(df, start, end, _acct(), min_unit=1.0, approaching_pct=0.98)

    assert len(trades) == 1
    trade = trades[0]

    # 오라클: 이미 단위 테스트로 검증된 compute_indicators/compute_trading_params를
    # 그대로 호출해 기대값을 계산 (run_backtest도 내부적으로 동일 함수를 호출함)
    entry_ind = compute_indicators(df.iloc[: breakout_idx + 1])
    entry_params = compute_trading_params(entry_ind.high_55, entry_ind.atr_20, _acct(), 1.0)
    expected_pyramid_1 = entry_params.pyramid_1_price
    assert expected_pyramid_1 < 103.0  # offset=1의 종가(103.0)가 피라미드 레벨을 넘긴다는 전제 검증

    assert trade.entry_date == df.index[breakout_idx].strftime("%Y-%m-%d")
    assert trade.exit_date == df.index[breakout_idx + 2].strftime("%Y-%m-%d")
    assert trade.units == 2
    # 이 시나리오에서는 급락(80.0) 시점에 실제 chandelier_stop도 함께 breach된다
    # (day+1 상승으로 ratchet된 chandelier_stop ~95.19 > close 80.0).
    assert trade.exit_reason == "2N+10D+CHANDELIER"
    assert trade.exit_price == 80.0

    expected_avg = (entry_ind.high_55 + expected_pyramid_1) / 2
    expected_size = 2 * entry_params.unit_size
    assert trade.entry_price == pytest.approx(expected_avg)
    assert trade.size == pytest.approx(expected_size)
    assert trade.pnl == pytest.approx((80.0 - expected_avg) * expected_size)


def test_run_backtest_raises_when_warmup_insufficient():
    n = 50  # 200일 미달
    idx = pd.bdate_range("2020-01-01", periods=n)
    df = pd.DataFrame(
        {"open": [100.0] * n, "high": [101.0] * n, "low": [99.0] * n,
         "close": [100.0] * n, "volume": [1000.0] * n},
        index=idx,
    )
    with pytest.raises(ValueError, match="워밍업"):
        run_backtest(df, df.index[40].strftime("%Y%m%d"), df.index[45].strftime("%Y%m%d"), _acct())


def test_run_backtest_chandelier_stop_ratchets_up_and_does_not_fall():
    n = 230
    breakout_idx = 205
    # breakout 직후 며칠간 상승(고점 갱신) 후 하락하지만 chandelier 아래까지는 안 감,
    # 대신 10D 저가를 깨서 청산 -> 청산 시점에 chandelier_stop이 초기값보다 높아야 함
    df = _flat_then_breakout_df(
        breakout_idx, n,
        post_breakout_closes={1: 110.0, 2: 108.0, 3: 106.0, 4: 104.0, 5: 90.0},
    )
    start = df.index[200].strftime("%Y%m%d")
    end = df.index[breakout_idx + 6].strftime("%Y%m%d")

    trades = run_backtest(df, start, end, _acct(), min_unit=1.0, approaching_pct=0.98)

    assert len(trades) == 1
    entry_ind = compute_indicators(df.iloc[: breakout_idx + 1])
    initial_chandelier = entry_ind.high_22 - 3 * entry_ind.atr_20
    # 상승 구간에서 high_22가 갱신됐으므로 청산 시점 chandelier_stop은 진입 시점보다 높아야 함
    peak_ind = compute_indicators(df.iloc[: breakout_idx + 4 + 1])  # offset=4(종가104) 시점까지
    peak_chandelier = peak_ind.high_22 - 3 * peak_ind.atr_20
    assert peak_chandelier > initial_chandelier
