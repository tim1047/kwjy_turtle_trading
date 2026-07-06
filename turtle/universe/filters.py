from dataclasses import dataclass

from turtle.config import StockFilterConfig


@dataclass(frozen=True)
class StockMetrics:
    ticker: str
    name: str
    market: str
    listing_days: int
    avg_turnover_20: float
    avg_volume_20: float
    price: float
    market_cap: float
    is_flagged: bool
    is_preferred: bool
    is_spac: bool
    had_recent_split: bool


def passes_stock_filters(m: StockMetrics, cfg: StockFilterConfig) -> bool:
    """모든 조건을 AND로 만족해야 유니버스에 포함된다 (순수 함수, I/O 없음)."""
    if m.listing_days < cfg.min_listing_days:
        return False
    if m.avg_turnover_20 < cfg.min_avg_turnover_20:
        return False
    if m.avg_volume_20 < cfg.min_avg_volume_20:
        return False
    if m.price < cfg.min_price:
        return False
    if m.market_cap < cfg.min_market_cap:
        return False
    if m.is_flagged:
        return False
    if cfg.exclude_preferred and m.is_preferred:
        return False
    if cfg.exclude_spac and m.is_spac:
        return False
    if cfg.exclude_recent_split and m.had_recent_split:
        return False
    return True
