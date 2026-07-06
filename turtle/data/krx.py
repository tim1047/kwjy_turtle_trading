import time

import pandas as pd
from pykrx import stock

from turtle.data.base import DataFetcher, normalize_pykrx_ohlcv, with_retry


class KrxFetcher(DataFetcher):
    """DataFetcher implementation backed by pykrx's KRX market data API."""

    def __init__(self, throttle: float = 0.2):
        self.throttle = throttle

    def get_ohlcv(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        def _call():
            return stock.get_market_ohlcv(start, end, ticker)

        raw = with_retry(_call, retries=3, base_delay=1.0)
        time.sleep(self.throttle)
        return normalize_pykrx_ohlcv(raw)
