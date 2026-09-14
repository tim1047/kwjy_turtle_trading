import logging

import pandas as pd
from pykrx import stock

from turtle.config import StockFilterConfig
from turtle.data.base import with_retry
from turtle.universe.filters import StockMetrics, passes_stock_filters
from turtle.universe.krx_etf import etf_ticker_set

log = logging.getLogger(__name__)

_PREFERRED_SUFFIXES = ("우", "우B")

# --- 시가총액 상위 종목 조회 -------------------------------------------------
#
# 원래는 네이버 금융 시가총액 순위 페이지(finance.naver.com/sise/sise_market_sum.naver)의
# HTML 표를 스크래핑했다. 2026-09-14 확인 시 이 주소는 sosok·page와 무관하게
# stock.naver.com의 JS 렌더링 페이지로 리다이렉트되어 (HTTP 200, <table> 0개)
# pd.read_html이 "No tables found"로 실패한다. 상태 코드가 200이라 재시도로도
# 복구되지 않는다.
#
# 대신 KRX 원본 단면(pykrx get_market_cap_by_ticker)을 쓴다. 2026-07-06 스파이크에서는
# 세션 쿠키 없는 POST가 "400 LOGOUT"으로 빈 결과를 냈지만, 이후 .env의 KRX_ID/KRX_PW로
# pykrx가 로그인하면서 정상 응답한다 (2026-09-11: KOSPI 943 / KOSDAQ 1822종목, 1위 005930).
# 시가총액 단위는 원이고, 날짜별 단면이라 유니버스를 target 시점 기준으로 잡을 수 있다.
#
# 주의: 휴장일을 target으로 넘기면 예외 없이 무의미한 단면이 온다
# (2026-08-01 토요일 KOSPI 1위가 095570). 호출측은 반드시 거래일로 확정한 날짜를 넘긴다.


def _is_preferred(name: str) -> bool:
    return name.endswith(_PREFERRED_SUFFIXES)


def _is_spac(name: str) -> bool:
    return "스팩" in name


def fetch_market_cap(target: str, market: str) -> pd.DataFrame:
    """날짜별 전종목 시가총액 단면 조회 (I/O).

    pykrx의 KRX 계열 함수는 KRX_ID/KRX_PW 미설정·세션 만료 시 예외 없이 빈
    결과를 반환한다. 그대로 진행하면 "후보 0개"로 위장된 장애가 발송되므로
    빈 결과는 예외로 승격시켜 배치를 중단한다.
    """

    def _call():
        return stock.get_market_cap_by_ticker(target, market=market)

    df = with_retry(_call, retries=3, base_delay=1.0)
    if df is None or df.empty:
        raise RuntimeError(
            f"{market} 시가총액 단면이 비어 있음 "
            f"(target={target}) — KRX_ID/KRX_PW 미설정 또는 세션 만료 의심"
        )
    return df


def _top_by_cap(target: str, market: str, top_n: int) -> pd.DataFrame:
    """target 거래일 기준 시가총액 상위 top_n 종목 (index=ticker, 컬럼 '시가총액'=원 단위)."""
    cap_df = fetch_market_cap(target, market)
    out = cap_df[["시가총액"]].astype(float).sort_values("시가총액", ascending=False)
    out.index = out.index.astype(str)
    return out.head(top_n)


def _build_metrics(
    ticker: str,
    target: str,
    lookback_start: str,
    market: str,
    market_cap: float,
    fetcher,
) -> StockMetrics:
    df = fetcher.get_ohlcv(ticker, lookback_start, target)
    turnover = (df["close"] * df["volume"]).iloc[-20:].mean()
    name = stock.get_market_ticker_name(ticker)
    flagged = ticker in _flagged_tickers(target, market)
    return StockMetrics(
        ticker=ticker,
        name=name,
        market=market,
        listing_days=len(df),
        avg_turnover_20=float(turnover),
        avg_volume_20=float(df["volume"].iloc[-20:].mean()),
        price=float(df["close"].iloc[-1]),
        market_cap=float(market_cap),
        is_flagged=flagged,
        is_preferred=_is_preferred(name),
        is_spac=_is_spac(name),
        had_recent_split=False,  # MVP: pykrx 미제공 → 보수적으로 False, 로깅으로 대체
    )


def _flagged_tickers(target: str, market: str) -> set:
    """관리종목/투자경고. pykrx가 표준 API로 제공하지 않는 환경에서는 빈 집합 반환.

    (Task 브리프의 알려진 MVP 한계 — 관리종목 크롤러 구축은 이 태스크의 범위 밖.)
    """
    try:
        return set()
    except Exception as exc:  # noqa: BLE001
        log.warning("flagged ticker 조회 실패: %s", exc)
        return set()


def build_stock_universe(
    target: str, cfg: StockFilterConfig, fetcher, lookback: str
) -> list[tuple[str, str]]:
    """KOSPI/KOSDAQ 시가총액 상위 N 종목에 필터를 적용해 유니버스를 만든다 (I/O).

    반환: (ticker, market) 튜플 리스트. market은 "KOSPI"/"KOSDAQ" — 리포트에서
    종목이 어느 시장 소속인지 표시하는 데 쓰인다.
    종목 단위 실패는 전체 배치를 막지 않도록 개별적으로 격리한다.
    """
    try:
        etf_tickers = etf_ticker_set()
    except Exception as exc:  # noqa: BLE001 - 조회 실패 시 필터링 없이 진행
        log.warning("ETF 티커 목록 조회 실패, 교차 제외 없이 진행: %s", exc)
        etf_tickers = set()

    result = []
    plan = [("KOSPI", cfg.kospi_top_n), ("KOSDAQ", cfg.kosdaq_top_n)]
    for market, top_n in plan:
        try:
            cap_df = _top_by_cap(target, market, top_n)
        except Exception as exc:  # noqa: BLE001 - 시장 단위 조회 실패도 전체를 막지 않는다
            log.warning("%s 시가총액 조회 실패: %s", market, exc)
            continue
        for ticker, row in cap_df.iterrows():
            if ticker in etf_tickers:
                log.info("universe OUT %s (ETF, 시총 순위에 혼입)", ticker)
                continue
            try:
                m = _build_metrics(
                    ticker, target, lookback, market, float(row["시가총액"]), fetcher
                )
                if passes_stock_filters(m, cfg):
                    result.append((m.ticker, market))
                    log.info("universe IN  %s %s", m.ticker, m.name)
                else:
                    log.info("universe OUT %s %s", m.ticker, m.name)
            except Exception as exc:  # noqa: BLE001 - 종목별 격리
                log.warning("종목 %s 처리 실패: %s", ticker, exc)
    return result
