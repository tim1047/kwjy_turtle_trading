from dataclasses import dataclass

import pandas as pd

from turtle.config import AccountConfig
from turtle.indicators import IndicatorResult
from turtle.signals import BREAKOUT_CLOSE, BREAKOUT_TODAY, classify
from turtle.trading_params import compute_trading_params


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


def enter_position(
    row: pd.Series,
    ind: IndicatorResult,
    day: pd.Timestamp,
    account: AccountConfig,
    min_unit: float,
    approaching_pct: float,
) -> OpenPosition | None:
    status = classify(
        today_high=float(row["high"]),
        today_low=float(row["low"]),
        today_close=float(row["close"]),
        high_55=ind.high_55,
        low_20=ind.low_20,
        approaching_pct=approaching_pct,
        sma_200=ind.sma_200,
    )
    if status not in (BREAKOUT_TODAY, BREAKOUT_CLOSE):
        return None
    params = compute_trading_params(ind.high_55, ind.atr_20, account, min_unit)
    if not params.tradable:
        return None
    unit = Unit(entry_price=ind.high_55, size=params.unit_size, entry_date=day.strftime("%Y-%m-%d"))
    return OpenPosition(units=[unit], n=ind.atr_20, stop_price=params.stop_loss_price)


def add_pyramid_unit(
    position: OpenPosition,
    row: pd.Series,
    day: pd.Timestamp,
    account: AccountConfig,
    min_unit: float,
) -> None:
    if len(position.units) >= account.max_units_per_asset:
        return
    first_entry = position.units[0].entry_price
    params = compute_trading_params(first_entry, position.n, account, min_unit)
    levels = [params.pyramid_1_price, params.pyramid_2_price, params.pyramid_3_price]
    idx = len(position.units) - 1
    if idx >= len(levels):
        return
    level = levels[idx]
    if float(row["close"]) >= level:
        position.units.append(
            Unit(entry_price=level, size=params.unit_size, entry_date=day.strftime("%Y-%m-%d"))
        )
        position.stop_price = level - 2 * position.n
