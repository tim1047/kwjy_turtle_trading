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


class CachingFetcher(DataFetcher):
    """DataFetcher를 감싸 (ticker, start, end) 단위로 결과를 메모이즈하는 래퍼.

    유니버스 필터링(build_stock_universe/build_etf_universe)과 이후 스크리닝
    단계가 동일한 (ticker, lookback, target) 인자로 같은 종목의 OHLCV를 두 번
    조회하는 문제를 없애기 위한 것이다 (프로세스/실행 범위 내 인메모리 캐시,
    디스크·DB에는 아무것도 남기지 않는다 — 무상태 파이프라인 원칙 유지).

    래핑 대상 fetcher의 재시도/백오프 동작은 그대로 위임하며, 캐시는 성공한
    호출의 "반복"만 없앨 뿐 실패(캐시 미스) 시의 예외 전파는 건드리지 않는다.
    """

    def __init__(self, inner: DataFetcher):
        self._inner = inner
        self._cache: dict[tuple[str, str, str], pd.DataFrame] = {}

    def get_ohlcv(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        key = (ticker, start, end)
        if key not in self._cache:
            self._cache[key] = self._inner.get_ohlcv(ticker, start, end)
        return self._cache[key]
