from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class Unit:
    entry_price: float
    size: float
    entry_date: str


@dataclass
class OpenPosition:
    units: list[Unit]
    n: float
    stop_price: float


@dataclass(frozen=True)
class Trade:
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    units: int
    size: float
    pnl: float
    pnl_pct: float
    exit_reason: str


def close_position(
    position: OpenPosition, exit_date: pd.Timestamp, exit_price: float, reason: str
) -> Trade:
    total_size = sum(u.size for u in position.units)
    avg_price = sum(u.entry_price * u.size for u in position.units) / total_size
    pnl = (exit_price - avg_price) * total_size
    pnl_pct = (exit_price - avg_price) / avg_price * 100
    return Trade(
        entry_date=position.units[0].entry_date,
        exit_date=exit_date.strftime("%Y-%m-%d"),
        entry_price=avg_price,
        exit_price=exit_price,
        units=len(position.units),
        size=total_size,
        pnl=pnl,
        pnl_pct=pnl_pct,
        exit_reason=reason,
    )
