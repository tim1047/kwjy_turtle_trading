import time
from datetime import datetime

import pandas as pd
import requests

from turtle.data.base import DataFetcher, with_retry

_CANDLES_URL = "https://api.upbit.com/v1/candles/days"
_MAX_COUNT = 200


def normalize_upbit_ohlcv(
    rows: list[dict], start: datetime, end: datetime
) -> pd.DataFrame:
    """Upbit candles 응답(JSON dict 리스트, 최신순)을 표준 스키마로 변환한다.

    표준 스키마: DatetimeIndex, ['open','high','low','close','volume'] float,
    오름차순, [start, end] 구간으로 필터링."""
    cols = ["open", "high", "low", "close", "volume"]
    if not rows:
        return pd.DataFrame(columns=cols).astype(float)
    df = pd.DataFrame(rows)
    df["날짜"] = pd.to_datetime(df["candle_date_time_utc"].str[:10])
    df = df.rename(
        columns={
            "opening_price": "open",
            "high_price": "high",
            "low_price": "low",
            "trade_price": "close",
            "candle_acc_trade_volume": "volume",
        }
    )
    df = df.set_index("날짜")[cols].astype(float).sort_index()
    return df.loc[(df.index >= start) & (df.index <= end)]


class UpbitFetcher(DataFetcher):
    """DataFetcher implementation backed by Upbit's public candles API."""

    def __init__(self, throttle: float = 0.15):
        self.throttle = throttle

    def get_ohlcv(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        start_dt = datetime.strptime(start, "%Y%m%d")
        end_dt = datetime.strptime(end, "%Y%m%d")

        rows: list[dict] = []
        to_param = None
        while True:
            params = {"market": ticker, "count": _MAX_COUNT}
            if to_param is not None:
                params["to"] = to_param

            def _call(p=params):
                resp = requests.get(_CANDLES_URL, params=p, timeout=10)
                resp.raise_for_status()
                return resp.json()

            batch = with_retry(_call, retries=3, base_delay=1.0)
            time.sleep(self.throttle)
            if not batch:
                break
            rows.extend(batch)
            oldest_utc = batch[-1]["candle_date_time_utc"]
            oldest_dt = datetime.strptime(oldest_utc, "%Y-%m-%dT%H:%M:%S")
            if oldest_dt <= start_dt or len(batch) < _MAX_COUNT:
                break
            to_param = oldest_utc.replace("T", " ")

        return normalize_upbit_ohlcv(rows, start_dt, end_dt)
