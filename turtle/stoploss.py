from dataclasses import dataclass
from turtle.indicators import compute_indicators, rolling_low
from turtle.positions.store import Position

import pandas as pd


@dataclass(frozen=True)
class StopCheckResult:
    ticker: str
    name: str
    market: str
    entry_price: float
    close: float
    stop_2n: float
    stop_10d: float
    stop_chandelier: float
    breach_2n: bool
    breach_10d: bool
    breach_chandelier: bool


def check_position(position: Position, df: pd.DataFrame) -> StopCheckResult:
    """진입 시 고정된 entry_price/n으로 2N 손절가를, df(최소 11거래일 이상)로
    10일 저가 손절가를, ind.high_22/atr_20으로 ratchet된 Chandelier 손절가를
    계산한다. 순수 함수 (네트워크 호출 없음)."""
    df = df.sort_index()
    close = float(df["close"].iloc[-1])
    stop_10d = float(rolling_low(df["low"], 10).iloc[-1])
    stop_2n = position.entry_price - 2 * position.n
    ind = compute_indicators(df)
    candidate_chandelier = ind.high_22 - 3 * ind.atr_20
    if position.chandelier_stop is None:
        stop_chandelier = candidate_chandelier
    else:
        # 인자 순서 주의: max(a, b)는 b가 a보다 "엄격히 클" 때만 b를 반환하고,
        # 그 외(NaN 비교 포함, 항상 False)에는 a를 그대로 유지한다. 따라서
        # candidate가 NaN(데이터 부족)일 때 prior를 살리려면 prior를 첫 인자로
        # 둬야 한다: max(candidate, prior)로 쓰면 candidate=NaN일 때 결과가
        # NaN이 되어버려 유효했던 prior를 잃는다 (실측: max(nan, 5.0) == nan,
        # max(5.0, nan) == 5.0). prior가 유효한 두 값 사이에서는 인자 순서가
        # 결과에 영향을 주지 않으므로 이 순서는 정상 ratchet 동작을 그대로
        # 보존한다.
        stop_chandelier = max(position.chandelier_stop, candidate_chandelier)
    return StopCheckResult(
        ticker=position.ticker,
        name=position.name,
        market=position.market,
        entry_price=position.entry_price,
        close=close,
        stop_2n=stop_2n,
        stop_10d=stop_10d,
        stop_chandelier=stop_chandelier,
        breach_2n=close <= stop_2n,
        breach_10d=close <= stop_10d,
        breach_chandelier=close <= stop_chandelier,
    )
