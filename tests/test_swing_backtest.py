import pandas as pd

from swing.backtest import (
    chandelier_series,
    extract_trades,
    simulate_exit,
    summarize,
)
from swing.params import SwingParams

# 합성 프레임 규약은 test_swing_screener와 동일: bar = (open, high, low, close, volume)
QUIET_LONG = (10_000, 10_100, 9_900, 10_000, 200_000)
QUIET_BASE = (10_000, 10_100, 9_900, 10_000, 100_000)
POLE = (10_000, 10_750, 9_990, 10_700, 300_000)
HOLD = (10_720, 10_800, 10_710, 10_750, 60_000)


def _frame(bars):
    idx = pd.date_range("2026-01-01", periods=len(bars), freq="B")
    return pd.DataFrame(
        list(bars), columns=["open", "high", "low", "close", "volume"], index=idx
    ).astype(float)


# 장대양봉 저가 = 9,990 (POLE). A안 진입 10,700 / B안 진입 10,750(HOLD 종가).
# B안 진입이 더 높으므로 손절폭도 더 크다 -> 이 합성 데이터에서는 A안이 유리하다.
# 실데이터에서는 눌림 진입가가 장대양봉 종가보다 낮아 부호가 뒤집힌다.
PAD = (QUIET_LONG,) * 70
BASE = (QUIET_BASE,) * 30
RALLY = (10_800, 11_500, 10_780, 11_400, 80_000)   # 눌림 이후 상승
CRASH = (10_700, 10_720, 9_000, 9_100, 500_000)    # 손절선 하향 이탈


def _p(**over):
    return SwingParams(**over)


def test_pole_produces_paired_a_and_b_trades():
    df = _frame(list(PAD) + list(BASE) + [POLE] + [HOLD] * 3 + [RALLY] * 20)
    trades = extract_trades("TEST", df, _p(), max_hold=20)

    arms = {t.arm: t for t in trades}
    assert set(arms) == {"A", "B"}
    # 같은 장대양봉을 공유하고 손절선도 같다 -> R 비교가 성립한다
    assert arms["A"].pole_date == arms["B"].pole_date
    assert arms["A"].stop == arms["B"].stop == 9_990.0
    assert arms["A"].entry == 10_700.0 and arms["A"].elapsed == 0
    # 눌림 조건은 k=1에서 이미 성립한다. 실운용 screen()은 마지막 봉 기준이라
    # 같은 프레임에서 elapsed=3을 보고하지만, 백테스트는 첫 성립일에 진입한다.
    assert arms["B"].entry == 10_750.0 and arms["B"].elapsed == 1


def test_gap_down_fills_at_open_not_stop():
    # 손절선(9,990) 아래로 갭하락하면 시가(10,700이 아닌 CRASH 저가 경로) 대신
    # 실제 시가에서 체결되어야 한다. 여기선 시가 10,700 > 손절선이므로 손절가 체결.
    df = _frame(list(PAD) + list(BASE) + [POLE] + [CRASH] * 5)
    idx = len(df) - 6  # POLE 위치
    j, px, reason = simulate_exit(df, idx, stop=9_990.0, max_hold=20)
    assert reason == "STOP"
    assert j == idx + 1 and px == 9_990.0

    gap = (9_500, 9_600, 9_000, 9_100, 500_000)  # 시가부터 손절선 아래
    df2 = _frame(list(PAD) + list(BASE) + [POLE] + [gap] * 5)
    _, px2, _ = simulate_exit(df2, idx, stop=9_990.0, max_hold=20)
    assert px2 == 9_500.0  # 갭 손실이 사라지지 않는다


def test_timeout_exits_at_last_close():
    df = _frame(list(PAD) + list(BASE) + [POLE] + [HOLD] * 3 + [RALLY] * 20)
    a = next(t for t in extract_trades("TEST", df, _p(), max_hold=5) if t.arm == "A")
    assert a.reason == "TIMEOUT" and a.bars_held == 5


def test_summarize_r_and_pnl_math():
    df = _frame(list(PAD) + list(BASE) + [POLE] + [HOLD] * 3 + [RALLY] * 20)
    a = next(t for t in extract_trades("TEST", df, _p(), max_hold=20) if t.arm == "A")
    # R = (11400 - 10700) / (10700 - 9990),  수익률 = (11400 - 10700) / 10700
    assert round(a.r, 4) == round(700 / 710, 4)
    assert round(a.pnl_pct, 4) == round(700 / 10_700 * 100, 4)
    # 손절폭(6.64%)이 수익률(6.54%)보다 커서 R < 1 인데 수익률은 양수다.
    # 두 지표가 다른 것을 재고 있음을 고정한다.
    assert a.r < 1.0 and a.pnl_pct > 0

    s = summarize([a])
    assert s["n"] == 1 and s["win_rate"] == 100.0
    assert round(s["avg_r"], 4) == round(a.r, 4)
    assert round(s["avg_pnl_pct"], 4) == round(a.pnl_pct, 4)
    assert s["best_pnl_pct"] == s["worst_pnl_pct"] == a.pnl_pct
    assert s["avg_loss_pnl_pct"] == 0.0  # 손실 표본 없음


def test_empty_trades_summary():
    assert summarize([]) == {"n": 0}


def test_no_pole_no_trades():
    flat = _frame(list(PAD) + list(BASE) + [QUIET_BASE] * 10)
    assert extract_trades("TEST", flat, _p(), max_hold=20) == []


def test_trail_exits_before_timeout_on_giveback():
    # 20봉 급등 후 급락. 트레일링이 있으면 되돌림 도중 끊고, 없으면 20일째까지
    # 들고 가 이익을 다 뱉는다.
    up = [(10_800 + 400 * i, 11_000 + 400 * i, 10_750 + 400 * i, 10_950 + 400 * i, 70_000)
          for i in range(12)]
    down = [(15_300 - 700 * i, 15_400 - 700 * i, 14_800 - 700 * i, 14_900 - 700 * i, 90_000)
            for i in range(10)]
    df = _frame(list(PAD) + list(BASE) + [POLE] + [HOLD] + up + down)
    entry = len(PAD) + len(BASE)  # POLE 위치

    j_h, px_h, why_h = simulate_exit(df, entry, stop=9_990.0, max_hold=20)
    j_t, px_t, why_t = simulate_exit(
        df, entry, stop=9_990.0, max_hold=20, trail=chandelier_series(df)
    )
    assert why_h == "TIMEOUT"
    assert why_t == "TRAIL"
    assert j_t < j_h          # 더 일찍 끊고
    assert px_t > px_h        # 더 비싸게 나온다


def test_trail_never_triggers_before_entry_warmup():
    # 지표 워밍업이 모자라 샹들리에가 NaN이어도 조용히 청산되지 않아야 한다
    # (max(prior, candidate) 인자 순서가 NaN을 흡수한다).
    df = _frame(list(PAD) + list(BASE) + [POLE] + [HOLD] * 3)
    trail = chandelier_series(df).copy()
    trail.iloc[:] = float("nan")
    j, _px, why = simulate_exit(df, len(df) - 4, stop=9_990.0, max_hold=20, trail=trail)
    assert why == "TIMEOUT" and j == len(df) - 1


def test_trail_uses_no_future_bars():
    # j시점 값은 j 이후 봉에 의존하지 않아야 한다: j에서 자른 프레임으로 계산해도
    # 같은 값이 나온다. (당일 봉 자체는 쓴다 — ATR에 당일 TR이 들어간다. 청산
    # 판정이 종가에 이뤄지므로 그 시점에 이미 알 수 있는 정보다.)
    bars = list(PAD) + list(BASE) + [POLE] + [HOLD] * 3
    full = chandelier_series(_frame(bars))
    j = len(bars) - 3
    assert chandelier_series(_frame(bars[: j + 1])).iloc[-1] == full.iloc[j]


def test_exit_mode_hold_disables_trailing():
    df = _frame(list(PAD) + list(BASE) + [POLE] + [HOLD] * 3 + [RALLY] * 20)
    held = extract_trades("TEST", df, _p(), max_hold=20, exit_mode="hold")
    assert all(t.reason in ("STOP", "TIMEOUT") for t in held)


def test_dataframe_index_is_datetime():
    df = _frame(list(PAD) + list(BASE) + [POLE] + [HOLD] * 3 + [RALLY] * 20)
    assert isinstance(df.index, pd.DatetimeIndex)
