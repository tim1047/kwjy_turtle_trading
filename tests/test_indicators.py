import numpy as np
import pandas as pd
import pytest

from turtle.indicators import (
    true_range,
    atr_wilder,
    rolling_high,
    rolling_low,
    compute_indicators,
    chandelier_level,
    IndicatorResult,
)


def _df(highs, lows, closes, vols=None):
    n = len(closes)
    idx = pd.date_range("2026-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {
            "open": closes,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": vols if vols is not None else [1000] * n,
        },
        index=idx,
    )


def test_true_range_single_row():
    df = _df(highs=[100, 110], lows=[95, 90], closes=[100, 105])
    tr = true_range(df)
    # 둘째 행: max(110-90=20, |110-100|=10, |90-100|=10) = 20
    assert tr.iloc[1] == 20


def test_atr_wilder_constant_tr_is_constant():
    tr = pd.Series([2.0] * 25)
    atr = atr_wilder(tr, period=20)
    assert atr.iloc[-1] == pytest.approx(2.0)


def test_atr_wilder_seed_is_sma_then_wilder():
    tr = pd.Series([float(i) for i in range(1, 21)] + [21.0])  # 1..20, then 21
    atr = atr_wilder(tr, period=20)
    # seed(20번째) = mean(1..20) = 10.5
    assert atr.iloc[19] == pytest.approx(10.5)
    # 21번째 = (19*10.5 + 21)/20 = 11.025
    assert atr.iloc[20] == pytest.approx(11.025)


def test_rolling_high_excludes_today():
    high = pd.Series([1, 2, 3, 4, 5], dtype=float)
    rh = rolling_high(high, window=3)
    # 마지막 원소(5) 기준 직전 3봉 [2,3,4]의 max = 4 (오늘 5 제외)
    assert rh.iloc[-1] == 4


def test_rolling_low_excludes_today():
    low = pd.Series([5, 4, 3, 2, 1], dtype=float)
    rl = rolling_low(low, window=3)
    # 마지막 원소(1) 기준 직전 3봉 [4,3,2]의 min = 2 (오늘 1 제외)
    assert rl.iloc[-1] == 2


def test_compute_indicators_returns_latest_values():
    n = 80
    highs = list(np.linspace(100, 180, n))
    lows = [h - 5 for h in highs]
    closes = [h - 2 for h in highs]
    df = _df(highs, lows, closes)
    res = compute_indicators(df)
    assert res.close == pytest.approx(closes[-1])
    # high_55: 직전 55봉(오늘 제외) 최고가
    assert res.high_55 == pytest.approx(max(highs[-56:-1]))
    assert res.low_20 == pytest.approx(min(lows[-21:-1]))
    assert res.atr_20 > 0
    assert res.high_22 == pytest.approx(max(highs[-23:-1]))


def test_chandelier_level_formula():
    ind = IndicatorResult(
        close=100.0, high_55=110.0, low_20=90.0, high_20=105.0, high_22=108.0,
        low_10=95.0, tr=2.0, atr_20=3.0, adx_14=25.0, avg_volume_20=1000.0,
        avg_turnover_20=100000.0, sma_200=95.0,
    )
    assert chandelier_level(ind) == pytest.approx(108.0 - 3 * 3.0)
