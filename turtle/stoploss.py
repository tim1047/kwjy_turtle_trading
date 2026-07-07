from dataclasses import dataclass

import pandas as pd

from turtle.indicators import rolling_low
from turtle.positions.store import Position


@dataclass(frozen=True)
class StopCheckResult:
    ticker: str
    name: str
    market: str
    close: float
    stop_2n: float
    stop_10d: float
    breach_2n: bool
    breach_10d: bool


def check_position(position: Position, df: pd.DataFrame) -> StopCheckResult:
    """진입 시 고정된 entry_price/n으로 2N 손절가를, df(최소 11거래일 이상)로
    10일 저가 손절가를 계산한다. 순수 함수 (네트워크 호출 없음)."""
    df = df.sort_index()
    close = float(df["close"].iloc[-1])
    stop_10d = float(rolling_low(df["low"], 10).iloc[-1])
    stop_2n = position.entry_price - 2 * position.n
    return StopCheckResult(
        ticker=position.ticker,
        name=position.name,
        market=position.market,
        close=close,
        stop_2n=stop_2n,
        stop_10d=stop_10d,
        breach_2n=close <= stop_2n,
        breach_10d=close <= stop_10d,
    )
