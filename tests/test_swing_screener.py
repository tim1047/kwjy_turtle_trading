import pandas as pd

from swing.params import SwingParams
from swing.screener import avg_turnover_20, screen

# 합성 프레임 규약: bar = (open, high, low, close, volume)
QUIET_LONG = (10_000, 10_100, 9_900, 10_000, 200_000)   # 장기창(60봉): 거래량 많음
QUIET_BASE = (10_000, 10_100, 9_900, 10_000, 100_000)   # 직전 30봉: 거래량 위축
POLE = (10_000, 10_750, 9_990, 10_700, 300_000)         # 몸통 7%, 종가 상단, 3배 급증, 박스 돌파
HOLD = (10_720, 10_800, 10_710, 10_750, 60_000)         # 양봉 위 지지 + 거래량 감소


def _frame(bars):
    idx = pd.date_range("2026-01-01", periods=len(bars), freq="B")
    return pd.DataFrame(
        list(bars), columns=["open", "high", "low", "close", "volume"], index=idx
    ).astype(float)


# required_bars(=30+60+10+1=101) 확보용 여유 이력. 브리프 원안(장기창60+바닥30+장대양봉1
# +눌림n)은 최소 pullback(1~3봉)일 때 92~94봉뿐이라 게이트에 걸려 즉시 None이 나온다 —
# 임계값이 아니라 데이터 길이가 짧은 픽스처 결함이므로 여기서 보정한다.
PAD = (QUIET_LONG,) * 10


def _scenario(pole=POLE, pullback=(HOLD,) * 3, base=None, long_=None):
    """여유이력 10봉 + 장기창 60봉 + 바닥 30봉 + 장대양봉 1봉 + 눌림 n봉."""
    return _frame(
        list(PAD)
        + list(long_ or (QUIET_LONG,) * 60)
        + list(base or (QUIET_BASE,) * 30)
        + [pole]
        + list(pullback)
    )


def _p(**over):
    return SwingParams(**over)


def test_happy_path_detects_pullback():
    sig = screen(_scenario(), _p())
    assert sig is not None
    assert sig.elapsed == 3
    assert sig.pole_date == _scenario().index[100].date()  # PAD(10) + 장기창(60) + 바닥(30)
    assert sig.close == 10_750.0
    # (10700 - 10750) / (10700 - 10000) * 100
    assert round(sig.retrace_pct, 2) == -7.14


def test_short_history_returns_none():
    df = _scenario()
    assert screen(df.iloc[-50:], _p()) is None


def test_small_body_rejected():
    weak = (10_000, 10_300, 9_990, 10_200, 300_000)  # 몸통 2%
    assert screen(_scenario(pole=weak), _p()) is None


def test_upper_wick_rejected():
    wick = (10_000, 12_000, 9_990, 10_700, 300_000)  # 종가가 고가 대비 하단
    assert screen(_scenario(pole=wick), _p()) is None


def test_weak_volume_spike_rejected():
    thin = (10_000, 10_750, 9_990, 10_700, 120_000)  # 20일 평균의 1.2배
    assert screen(_scenario(pole=thin), _p()) is None


def test_no_box_breakout_rejected():
    inside = (10_000, 10_050, 9_990, 10_700, 300_000)  # 고가가 박스 상단 이하
    assert screen(_scenario(pole=inside), _p()) is None


def test_wide_base_range_rejected():
    wide = [QUIET_BASE] * 29 + [(10_000, 15_000, 9_900, 10_000, 100_000)]
    assert screen(_scenario(base=wide), _p()) is None


def test_base_volume_not_contracted_rejected():
    # 장기창과 바닥 구간의 거래량이 동일 -> 비율 1.0 > 0.8
    assert screen(_scenario(long_=(QUIET_BASE,) * 60), _p()) is None


def test_halted_day_in_base_rejected():
    halted = [QUIET_BASE] * 29 + [(10_000, 10_100, 9_900, 10_000, 0)]
    assert screen(_scenario(base=halted), _p()) is None


def test_break_below_pole_open_rejected():
    deep = (10_100, 10_200, 9_500, 9_900, 60_000)  # 장대양봉 시가 아래로 이탈
    assert screen(_scenario(pullback=(deep,)), _p()) is None


def test_retrace_beyond_half_body_rejected():
    # 저가는 시가 위지만 현재가가 몸통 절반(10,350) 아래
    shallow = (10_300, 10_350, 10_050, 10_100, 60_000)
    assert screen(_scenario(pullback=(shallow,)), _p()) is None


def test_inside_body_support_accepted():
    # 저가가 장대양봉 시가 위 + 현재가가 몸통 절반 위 -> (b) 유형 통과
    inside = (10_600, 10_650, 10_400, 10_500, 60_000)
    sig = screen(_scenario(pullback=(inside,)), _p())
    assert sig is not None
    assert sig.elapsed == 1


def test_high_pullback_volume_rejected():
    heavy = (10_720, 10_800, 10_710, 10_750, 200_000)  # 장대양봉 거래량의 0.67배
    assert screen(_scenario(pullback=(heavy,)), _p()) is None


def test_heavy_bearish_bar_in_pullback_rejected():
    down = (10_750, 10_760, 10_705, 10_710, 250_000)  # 음봉 + 20일 평균의 2.5배
    assert screen(_scenario(pullback=(HOLD, down, HOLD)), _p()) is None


def test_pole_older_than_pullback_max_rejected():
    assert screen(_scenario(pullback=(HOLD,) * 11), _p()) is None


def test_picks_most_recent_qualifying_pole():
    """조건을 만족하는 장대양봉이 둘이면 더 최근 것을 채택한다."""
    pole2 = (10_800, 11_650, 10_790, 11_600, 400_000)
    hold2 = (11_610, 11_700, 11_605, 11_650, 80_000)
    df = _frame(
        list(PAD)
        + [QUIET_LONG] * 60
        + [QUIET_BASE] * 30
        + [POLE]
        + [HOLD] * 4
        + [pole2]
        + [hold2] * 2
    )
    sig = screen(df, _p())
    assert sig is not None
    assert sig.elapsed == 2  # 최근 장대양봉 기준 경과일 (과거 것이면 7)


def test_avg_turnover_20_uses_last_20_bars():
    df = _frame([(10.0, 10.0, 10.0, 10.0, 100.0)] * 30)
    assert avg_turnover_20(df) == 1000.0
