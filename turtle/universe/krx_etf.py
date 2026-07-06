import logging

import requests

from turtle.config import StockFilterConfig
from turtle.data.base import with_retry

log = logging.getLogger(__name__)

# --- ETF 티커 목록 조회 -------------------------------------------------
#
# 브리프 가정과의 차이 (스파이크 결과, pykrx 1.2.8, 2026-07-06 실행):
#   `from pykrx import etf as etf_api` -> ImportError: cannot import name 'etf' from
#   'pykrx' (설치된 pykrx 1.2.8에는 별도의 etf 서브모듈이 없다; ETF 관련 함수는
#   모두 `pykrx.stock` 아래에 있다: stock.get_etf_ticker_list, stock.get_etf_ohlcv_by_date 등).
#
#   그마저도 stock.get_etf_ticker_list('20260703')는 turtle/calendar.py(Task 6),
#   turtle/universe/krx_stocks.py에서 이미 확인된 것과 동일한 근본 원인
#   (원본 KRX 엔드포인트 세션 인증 실패, "400 LOGOUT")으로 빈 결과를 반환한다.
#   stock.get_etf_ohlcv_by_date도 내부적으로 종목의 ISIN을 원본 KRX 엔드포인트에서
#   조회하려다 실패해 빈 DataFrame을 반환한다.
#
#   반면 stock.get_market_ohlcv(start, end, ticker)는 ETF 티커에도 그대로 동작한다
#   (Naver 백엔드 경유, Task 5/6과 동일한 안정 경로) — 실측:
#     stock.get_market_ohlcv('20260601','20260703','069500').columns.tolist()
#     -> ['시가','고가','저가','종가','거래량','등락률'] (주식과 동일한 스키마).
#   따라서 OHLCV는 기존에 검증된 fetcher(turtle.data.krx.KrxFetcher, Task 5)를 그대로
#   재사용하고, 티커 "목록" 조회만 네이버 금융의 공개 ETF 목록 JSON API로 대체한다:
#     GET https://finance.naver.com/api/sise/etfItemList.naver
#     -> {"result": {"etfItemList": [{"itemcode": "069500", "itemname": "KODEX 200", ...}, ...]}}
_ETF_LIST_URL = "https://finance.naver.com/api/sise/etfItemList.naver"


def _fetch_etf_items() -> list:
    """네이버 ETF 목록 원본(itemcode/itemname/marketSum 등)을 조회한다 (I/O)."""

    def _call():
        resp = requests.get(
            _ETF_LIST_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=10
        )
        resp.raise_for_status()
        return resp.json()

    data = with_retry(_call, retries=3, base_delay=1.0)
    return data.get("result", {}).get("etfItemList", [])


def etf_ticker_set() -> set:
    """전체 ETF 티커 집합 (KOSPI 시총 순위에도 ETF가 섞여 나오므로, 주식
    유니버스 구성 시 이 집합으로 교차 제외한다). 실패 시 예외를 전파한다.
    """
    return {item["itemcode"] for item in _fetch_etf_items()}


def _etf_ticker_list(top_n: int) -> list:
    """시가총액(marketSum) 상위 top_n ETF 티커 목록을 조회한다 (I/O).

    etfItemList.naver 응답의 marketSum(억원)으로 내림차순 정렬 후 상위 top_n만
    취한다. 실패 시 예외를 그대로 전파한다.
    """
    items = sorted(_fetch_etf_items(), key=lambda item: item.get("marketSum", 0), reverse=True)
    return [item["itemcode"] for item in items[:top_n]]


def build_etf_universe(
    target: str, cfg: StockFilterConfig, fetcher, lookback: str
) -> list:
    """시총 상위 cfg.etf_top_n개 ETF에 유동성·상장기간·가격 필터를 적용한다.

    종목 단위 실패는 전체 배치를 막지 않도록 개별적으로 격리한다.
    """
    try:
        tickers = _etf_ticker_list(cfg.etf_top_n)
    except Exception as exc:  # noqa: BLE001 - 목록 조회 실패도 전체를 막지 않는다
        log.warning("ETF 티커 목록 조회 실패: %s", exc)
        return []

    result = []
    for ticker in tickers:
        try:
            df = fetcher.get_ohlcv(ticker, lookback, target)
            if len(df) < cfg.min_listing_days:
                log.info("etf universe OUT %s (상장기간 부족)", ticker)
                continue
            turnover = (df["close"] * df["volume"]).iloc[-20:].mean()
            volume = df["volume"].iloc[-20:].mean()
            price = df["close"].iloc[-1]
            if (
                turnover >= cfg.min_avg_turnover_20
                and volume >= cfg.min_avg_volume_20
                and price >= cfg.min_price
            ):
                result.append(ticker)
                log.info("etf universe IN  %s", ticker)
            else:
                log.info("etf universe OUT %s", ticker)
        except Exception as exc:  # noqa: BLE001 - 종목별 격리
            log.warning("ETF %s 처리 실패: %s", ticker, exc)
    return result
