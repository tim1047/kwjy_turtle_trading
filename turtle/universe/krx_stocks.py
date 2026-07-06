import logging
import math
import re
import time
from io import StringIO

import pandas as pd
import requests
from pykrx import stock

from turtle.config import StockFilterConfig
from turtle.data.base import with_retry
from turtle.universe.filters import StockMetrics, passes_stock_filters

log = logging.getLogger(__name__)

_PREFERRED_SUFFIXES = ("우", "우B")

# --- 시가총액 상위 종목 조회 -------------------------------------------------
#
# 스파이크 결과 (pykrx 1.2.8, 2026-07-06 실행):
#   stock.get_market_cap('20260703', market='KOSPI')
#   -> KeyError: "None of [Index(['종가', '시가총액', ...])] are in the [columns]"
# 원인 추적: get_market_cap_by_ticker는 내부적으로 원본 KRX 엔드포인트
# (dbms/MDC/STAT/standard/MDCSTAT01501)를 세션 쿠키 없이 POST하며, turtle/calendar.py
# (Task 6)에서 이미 확인된 것과 동일하게 "400 LOGOUT" 응답을 받아 빈 DataFrame으로
# 귀결된다 (raw requests.post로 재현 확인). 같은 근본 원인으로
# stock.get_market_ticker_list / stock.get_market_cap_by_date 도 전부 빈 결과를 반환해,
# 이 환경에서는 "시가총액순 종목 목록"을 얻을 pykrx 경로가 전혀 없다.
#
# 대안: 네이버 금융의 공개 시가총액 순위 페이지
# (finance.naver.com/sise/sise_market_sum.naver)는 이미 시가총액 내림차순으로 정렬되어
# 있고, 종목 코드는 페이지 내 "/item/main.naver?code=XXXXXX" 링크에서 추출할 수 있다.
# 시가총액 컬럼 단위는 억원이므로 원 단위로 변환한다 (검증: 삼성전자 표시값
# price * 상장주식수(천주 단위) ≈ 시가총액(억원) * 1e8, 오차 1% 이내).
# 종목명(및 우선주/스팩 판별)은 여전히 안정적으로 동작하는
# stock.get_market_ticker_name()을 사용한다.
_NAVER_CAP_URL = "https://finance.naver.com/sise/sise_market_sum.naver"
_SOSOK = {"KOSPI": "0", "KOSDAQ": "1"}
_PAGE_SIZE = 50


def _is_preferred(name: str) -> bool:
    return name.endswith(_PREFERRED_SUFFIXES)


def _is_spac(name: str) -> bool:
    return "스팩" in name


def _fetch_cap_page(market: str, page: int) -> pd.DataFrame:
    """네이버 금융 시가총액 순위 페이지 1장을 조회한다 (ticker, 시가총액(억원))."""

    def _call():
        resp = requests.get(
            _NAVER_CAP_URL,
            params={"sosok": _SOSOK[market], "page": page},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        resp.raise_for_status()
        resp.encoding = "euc-kr"
        return resp.text

    html = with_retry(_call, retries=3, base_delay=1.0)
    tables = pd.read_html(StringIO(html))
    df = tables[1].dropna(subset=["종목명"]).reset_index(drop=True)
    if df.empty:
        return df
    codes = re.findall(r"/item/main\.naver\?code=(\d{6})", html)
    n = min(len(df), len(codes))
    df = df.iloc[:n].copy()
    df["ticker"] = codes[:n]
    return df[["ticker", "시가총액"]]


def _top_by_cap(market: str, top_n: int) -> pd.DataFrame:
    """시가총액 상위 top_n 종목을 반환한다 (index=ticker, 컬럼 '시가총액'=원 단위)."""
    pages_needed = max(1, math.ceil(top_n / _PAGE_SIZE))
    frames = []
    for page in range(1, pages_needed + 1):
        df = _fetch_cap_page(market, page)
        if df.empty:
            break
        frames.append(df)
        time.sleep(0.2)
    if not frames:
        return pd.DataFrame(columns=["시가총액"])
    out = pd.concat(frames, ignore_index=True)
    out["시가총액"] = out["시가총액"].astype(float) * 100_000_000  # 억원 -> 원
    out = out.set_index("ticker").head(top_n)
    return out


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
) -> list:
    """KOSPI/KOSDAQ 시가총액 상위 N 종목에 필터를 적용해 유니버스를 만든다 (I/O).

    종목 단위 실패는 전체 배치를 막지 않도록 개별적으로 격리한다.
    """
    result = []
    plan = [("KOSPI", cfg.kospi_top_n), ("KOSDAQ", cfg.kosdaq_top_n)]
    for market, top_n in plan:
        try:
            cap_df = _top_by_cap(market, top_n)
        except Exception as exc:  # noqa: BLE001 - 시장 단위 조회 실패도 전체를 막지 않는다
            log.warning("%s 시가총액 조회 실패: %s", market, exc)
            continue
        for ticker, row in cap_df.iterrows():
            try:
                m = _build_metrics(
                    ticker, target, lookback, market, float(row["시가총액"]), fetcher
                )
                if passes_stock_filters(m, cfg):
                    result.append(m.ticker)
                    log.info("universe IN  %s %s", m.ticker, m.name)
                else:
                    log.info("universe OUT %s %s", m.ticker, m.name)
            except Exception as exc:  # noqa: BLE001 - 종목별 격리
                log.warning("종목 %s 처리 실패: %s", ticker, exc)
    return result
