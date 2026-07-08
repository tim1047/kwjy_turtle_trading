import math
from dataclasses import dataclass

from turtle.config import AccountConfig


@dataclass(frozen=True)
class TradingParams:
    entry_trigger: float
    entry_price_assumed: float
    stop_loss_price: float
    pyramid_1_price: float
    pyramid_2_price: float
    pyramid_3_price: float
    unit_size: float
    unit_notional: float
    max_position_notional: float
    max_loss_per_unit: float
    tradable: bool
    note: str


def compute_trading_params(
    entry_trigger: float,
    n: float,
    account: AccountConfig,
    min_unit: float = 1.0,
) -> TradingParams:
    entry = entry_trigger
    if n <= 0:
        return TradingParams(
            entry, entry, 0, 0, 0, 0, 0, 0, 0, 0,
            tradable=False, note="매매 불가 (N=0)",
        )
    risk_budget = account.total_value * account.risk_pct
    unit_size = math.floor(risk_budget / n / min_unit) * min_unit
    tradable = unit_size >= min_unit
    note = "" if tradable else "매매 불가 (유닛 수량 < 최소 단위)"
    return TradingParams(
        entry_trigger=entry,
        entry_price_assumed=entry,
        stop_loss_price=entry - 2 * n,
        pyramid_1_price=entry + 0.5 * n,
        pyramid_2_price=entry + 1.0 * n,
        pyramid_3_price=entry + 1.5 * n,
        unit_size=unit_size,
        unit_notional=unit_size * entry,
        max_position_notional=unit_size * entry * account.max_units_per_asset,
        max_loss_per_unit=unit_size * 2 * n,
        tradable=tradable,
        note=note,
    )
