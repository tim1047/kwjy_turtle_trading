from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class IndicatorResult:
    close: float
    high_55: float
    low_20: float
    high_20: float
    low_10: float
    tr: float
    atr_20: float
    adx_14: float
    avg_volume_20: float
    avg_turnover_20: float


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    hl = df["high"] - df["low"]
    hc = (df["high"] - prev_close).abs()
    lc = (df["low"] - prev_close).abs()
    return pd.concat([hl, hc, lc], axis=1).max(axis=1)


def atr_wilder(tr: pd.Series, period: int = 20) -> pd.Series:
    tr = tr.reset_index(drop=True)
    atr = pd.Series(np.nan, index=tr.index, dtype=float)
    if len(tr) < period:
        return atr
    seed = tr.iloc[:period].mean()
    atr.iloc[period - 1] = seed
    prev = seed
    for i in range(period, len(tr)):
        prev = (prev * (period - 1) + tr.iloc[i]) / period
        atr.iloc[i] = prev
    return atr


def rolling_high(high: pd.Series, window: int) -> pd.Series:
    return high.shift(1).rolling(window).max()


def rolling_low(low: pd.Series, window: int) -> pd.Series:
    return low.shift(1).rolling(window).min()


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr = true_range(df)
    atr = tr.ewm(alpha=1 / period, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / period, adjust=False).mean()


def compute_indicators(df: pd.DataFrame) -> IndicatorResult:
    df = df.sort_index()
    tr = true_range(df)
    atr = atr_wilder(tr, period=20)
    turnover = df["close"] * df["volume"]
    return IndicatorResult(
        close=float(df["close"].iloc[-1]),
        high_55=float(rolling_high(df["high"], 55).iloc[-1]),
        low_20=float(rolling_low(df["low"], 20).iloc[-1]),
        high_20=float(rolling_high(df["high"], 20).iloc[-1]),
        low_10=float(rolling_low(df["low"], 10).iloc[-1]),
        tr=float(tr.iloc[-1]),
        atr_20=float(atr.iloc[-1]),
        adx_14=float(adx(df, 14).iloc[-1]),
        avg_volume_20=float(df["volume"].iloc[-20:].mean()),
        avg_turnover_20=float(turnover.iloc[-20:].mean()),
    )
