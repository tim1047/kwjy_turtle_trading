import os
from dataclasses import dataclass

import yaml
from dotenv import load_dotenv


@dataclass(frozen=True)
class AccountConfig:
    total_value: float
    risk_pct: float
    max_units_per_asset: int
    max_units_correlated: int
    max_units_total: int


@dataclass(frozen=True)
class StockFilterConfig:
    min_listing_days: int
    min_avg_turnover_20: float
    min_avg_volume_20: float
    min_price: float
    min_market_cap: float
    kospi_top_n: int
    kosdaq_top_n: int
    etf_top_n: int
    exclude_preferred: bool
    exclude_spac: bool
    exclude_recent_split: bool


@dataclass(frozen=True)
class CryptoFilterConfig:
    tickers: list[str]
    min_unit: float


@dataclass(frozen=True)
class Config:
    account: AccountConfig
    filters_stocks: StockFilterConfig
    filters_crypto: CryptoFilterConfig
    approaching_pct: float
    assets: dict
    telegram_chat_id: str
    telegram_bot_token: str
    database_url: str


def load_config(path: str = "config.yaml") -> Config:
    load_dotenv()
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    raw_crypto = raw.get("filters_crypto", {})
    return Config(
        account=AccountConfig(**raw["account"]),
        filters_stocks=StockFilterConfig(**raw["filters_stocks"]),
        filters_crypto=CryptoFilterConfig(
            tickers=list(raw_crypto.get("tickers", [])),
            min_unit=float(raw_crypto.get("min_unit", 1.0)),
        ),
        approaching_pct=raw["approaching_pct"],
        assets=raw["assets"],
        telegram_chat_id=str(raw["telegram_chat_id"]),
        telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        database_url=os.environ.get("DATABASE_URL", ""),
    )
