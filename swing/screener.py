from dataclasses import dataclass
from datetime import date

import pandas as pd

from swing.params import SwingParams


@dataclass(frozen=True)
class SwingSignal:
    """장대양봉 후 눌림 구간 판정 결과."""

    pole_date: date      # 장대양봉 발생일
    elapsed: int         # 장대양봉 이후 경과 거래일 수
    retrace_pct: float   # 몸통 되돌림율(%). 0 이하 = 장대양봉 종가 위 지지
    close: float         # 현재가(마지막 봉 종가)


def avg_turnover_20(df: pd.DataFrame) -> float:
    """최근 20거래일 평균 거래대금(원). 유동성 필터·정렬 기준용 (순수 함수)."""
    return float((df["close"] * df["volume"]).iloc[-20:].mean())


def _spike_ref_mean(df: pd.DataFrame, d: int, p: SwingParams) -> float:
    """장대양봉 직전 spike_ref_window 거래일 평균 거래량 (당일 제외).

    조건2의 급증 판정과 조건3의 대량 음봉 판정이 같은 기준을 쓴다 — 장대양봉
    이후 시점의 평균을 쓰면 급증분이 섞여 기준이 떠버리기 때문이다 (스펙 §5.4).
    """
    return float(df["volume"].iloc[d - p.spike_ref_window : d].mean())


def _base_ok(df: pd.DataFrame, d: int, p: SwingParams) -> bool:
    """조건1 — 장대양봉 직전 저거래량 횡보 (바닥 다지기)."""
    base = df.iloc[d - p.base_window : d]
    lo = float(base["low"].min())
    hi = float(base["high"].max())
    if lo <= 0:
        return False
    if (hi - lo) / lo > p.price_contraction:
        return False
    if bool((base["volume"] <= 0).any()):  # 거래정지일이 섞이면 "거래량 마름"으로 오판정
        return False
    long_start = d - p.base_window - p.base_long_window
    long_mean = float(df["volume"].iloc[long_start : d - p.base_window].mean())
    if long_mean <= 0:
        return False
    return float(base["volume"].mean()) <= p.base_vol_ratio * long_mean


def _pole_ok(df: pd.DataFrame, d: int, p: SwingParams) -> bool:
    """조건2 — 대량 거래를 동반한 장대양봉(박스 상단 돌파)."""
    o = float(df["open"].iloc[d])
    h = float(df["high"].iloc[d])
    lo = float(df["low"].iloc[d])
    c = float(df["close"].iloc[d])
    v = float(df["volume"].iloc[d])
    if o <= 0:
        return False
    if (c - o) / o < p.body_min:
        return False
    if c < lo + p.close_pos * (h - lo):
        return False
    ref = _spike_ref_mean(df, d, p)
    if ref <= 0 or v < p.vol_spike * ref:
        return False
    return h > float(df["high"].iloc[d - p.base_window : d].max())


def _pullback_ok(df: pd.DataFrame, d: int, p: SwingParams) -> bool:
    """조건3 — 거래량 마른 눌림 지지 (현재 상태)."""
    pull = df.iloc[d + 1 :]
    if pull.empty:
        return False
    o_d = float(df["open"].iloc[d])
    c_d = float(df["close"].iloc[d])
    v_d = float(df["volume"].iloc[d])
    min_low = float(pull["low"].min())
    close_t = float(df["close"].iloc[-1])

    on_top = min_low >= c_d                                        # (a) 양봉 위 지지형
    inside = min_low >= o_d and close_t >= c_d - p.retrace_max * (c_d - o_d)  # (b) 양봉 내 지지형
    if not (on_top or inside):
        return False
    if float(pull["volume"].mean()) > p.pullback_vol_ratio * v_d:
        return False
    ref = _spike_ref_mean(df, d, p)
    heavy_down = (pull["close"] < pull["open"]) & (pull["volume"] >= p.dist_vol * ref)
    return not bool(heavy_down.any())


def screen(df: pd.DataFrame, p: SwingParams) -> SwingSignal | None:
    """장대양봉 후 눌림 구간에 들어와 있으면 SwingSignal, 아니면 None (순수 함수).

    df는 표준 OHLCV 스키마(DatetimeIndex 오름차순, open/high/low/close/volume).
    최근 봉부터 과거로 훑어 조건1·2·3을 모두 만족하는 첫 장대양봉을 채택한다
    (복수 히트 시 가장 최근 봉 — 스펙 §5.1).
    """
    n = len(df)
    if n < p.required_bars:
        return None
    for k in range(p.pullback_min, p.pullback_max + 1):
        d = n - 1 - k
        if d - p.base_window - p.base_long_window < 0:
            break  # k가 커질수록 d는 작아지므로 이후 후보도 전부 데이터 부족
        if _pole_ok(df, d, p) and _base_ok(df, d, p) and _pullback_ok(df, d, p):
            o_d = float(df["open"].iloc[d])
            c_d = float(df["close"].iloc[d])
            close_t = float(df["close"].iloc[-1])
            return SwingSignal(
                pole_date=df.index[d].date(),
                elapsed=k,
                retrace_pct=(c_d - close_t) / (c_d - o_d) * 100.0,
                close=close_t,
            )
    return None
