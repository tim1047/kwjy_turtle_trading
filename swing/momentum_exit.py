from dataclasses import dataclass
from datetime import date

import pandas as pd

from swing.momentum_params import MomentumScreenerParams


@dataclass(frozen=True)
class ExitDecision:
    """보유 포지션에 대한 청산 판정 결과."""

    action: str  # "HOLD" | "STOP" | "TIME"
    price: float  # action이 STOP/TIME이면 청산가, HOLD면 현재 종가(참고용)
    days_held: int  # 진입일 기준 경과 거래일 수
    as_of: date  # price가 관측/확정된 날짜


def check_exit(
    entry_price: float,
    stop_price: float,
    entry_date: str,
    df: pd.DataFrame,
    p: MomentumScreenerParams,
) -> ExitDecision:
    """docs/momentum_screener_spec.md §3.3의 청산 규칙 5개를 그대로 판정한다 (순수 함수).

    df는 entry_date를 포함하는 표준 OHLCV(DatetimeIndex 오름차순)여야 한다.

    규칙:
      1. 손절선은 호출측이 진입 시점에 확정해 넘긴 stop_price를 그대로 쓴다
         (여기서 갱신하지 않는다).
      2. 갭 하락 시 시가 체결 — 당일 시가가 이미 stop_price 이하면 시가로 청산.
      3. 손절이 시간 청산보다 우선 — 만기일에 손절선을 건드리면 손절로 처리.
      4. 거래정지봉(open<=0 또는 volume<=0)은 건너뛴다. 만기일이 거래정지면
         직전 거래일 종가로 청산.
      5. (파이프라인 책임) 보유 중 재신호는 여기서 다루지 않는다 — 쿨다운이
         새 진입 자체를 막는다.
    """
    idx = df.index
    entry_ts = pd.Timestamp(entry_date)
    if entry_ts not in idx:
        raise ValueError(f"entry_date {entry_date} not found in df index")
    i = idx.get_loc(entry_ts)

    o = df["open"].to_numpy()
    h = df["high"].to_numpy()
    l = df["low"].to_numpy()
    c = df["close"].to_numpy()
    v = df["volume"].to_numpy()
    halted = (o <= 0) | (v <= 0)
    n = len(df)

    target = i + p.hold_days
    last_bar = min(n - 1, target)

    for k in range(i + 1, last_bar + 1):
        if halted[k]:
            continue
        if o[k] <= stop_price:
            return ExitDecision("STOP", float(o[k]), k - i, idx[k].date())
        if l[k] <= stop_price:
            return ExitDecision("STOP", float(stop_price), k - i, idx[k].date())

    if n - 1 < target:
        return ExitDecision("HOLD", float(c[-1]), n - 1 - i, idx[-1].date())

    j = target
    while j > i and halted[j]:
        j -= 1
    return ExitDecision("TIME", float(c[j]), j - i, idx[j].date())
