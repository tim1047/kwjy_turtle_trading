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


def get_investor_net_buy_days(
    ticker: str, start: str, end: str, window: int = 10, throttle: float = 0.2
) -> tuple[int, int]:
    """최근 window 거래일 중 외국인/기관 순매수(+)였던 날 수를 센다 (I/O).

    start~end는 window보다 넉넉한 달력일 구간이어야 한다 (호출측이 lookback_start로
    구성). 반환: (foreign_buy_days, inst_buy_days). 상장 초기 등으로 거래 이력이
    window보다 짧으면 있는 만큼만 센다.
    """

    def _call():
        return stock.get_market_trading_value_by_date(start, end, ticker, on="순매수")

    raw = with_retry(_call, retries=3, base_delay=1.0)
    time.sleep(throttle)
    recent = raw.tail(window)
    foreign_days = int((recent["외국인합계"] > 0).sum())
    inst_days = int((recent["기관합계"] > 0).sum())
    return foreign_days, inst_days
