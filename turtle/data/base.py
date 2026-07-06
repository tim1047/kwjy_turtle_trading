import time
from abc import ABC, abstractmethod

import pandas as pd

# Confirmed via live pykrx spike (pykrx 1.2.8):
#   stock.get_market_ohlcv('20260601','20260630','005930').columns.tolist()
#   -> ['시가', '고가', '저가', '종가', '거래량', '등락률']
# index name '날짜', dtype datetime64[ns]; 시가/고가/저가/종가/거래량 are int64,
# 등락률 (change rate, unused) is float64.
_COLMAP = {"시가": "open", "고가": "high", "저가": "low", "종가": "close", "거래량": "volume"}


def normalize_pykrx_ohlcv(raw: pd.DataFrame) -> pd.DataFrame:
    """Convert a raw pykrx OHLCV DataFrame (Korean columns) into the
    project's standard schema: DatetimeIndex, columns exactly
    ['open','high','low','close','volume'] as float, sorted ascending."""
    df = raw.rename(columns=_COLMAP)
    df = df[["open", "high", "low", "close", "volume"]].astype(float)
    df.index = pd.to_datetime(df.index)
    return df.sort_index()


def with_retry(fn, retries: int = 3, base_delay: float = 1.0):
    """Call fn() with exponential backoff retry. Re-raises the last
    exception if all attempts are exhausted."""
    last = None
    for attempt in range(retries):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - 재시도 목적
            last = exc
            if attempt < retries - 1:
                time.sleep(base_delay * (2**attempt))
    raise last


class DataFetcher(ABC):
    @abstractmethod
    def get_ohlcv(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        """Fetch OHLCV data for ticker between start/end ("YYYYMMDD" strings),
        returning the standard schema DataFrame."""
        ...
