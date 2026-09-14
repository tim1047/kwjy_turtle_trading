import logging
import math

import pandas as pd
from pykrx import stock

from swing.params import SwingParams
from turtle.universe.krx_etf import etf_ticker_set
from turtle.universe.krx_stocks import fetch_market_cap

log = logging.getLogger(__name__)

_PREFERRED_SUFFIXES = ("우", "우B")
_EXCLUDE_KEYWORDS = ("스팩", "리츠")


def is_excluded_name(name: str) -> bool:
    """우선주·스팩·리츠 종목명 패턴 판정 (순수 함수)."""
    if name.endswith(_PREFERRED_SUFFIXES):
        return True
    return any(kw in name for kw in _EXCLUDE_KEYWORDS)


def top_by_market_cap(cap_df: pd.DataFrame, cut_percentile: float) -> list[str]:
    """시총 단면에서 상위 (100 - cut_percentile)% 티커를 시총 내림차순으로 반환 (순수 함수)."""
    if cap_df.empty:
        raise ValueError("시가총액 단면이 비어 있음")
    ordered = cap_df.sort_values("시가총액", ascending=False)
    keep = math.ceil(len(ordered) * (100.0 - cut_percentile) / 100.0)
    return [str(t) for t in ordered.index[:keep]]


def _ticker_name(ticker: str) -> str | None:
    """종목명 조회 (I/O). 실패 시 None을 반환한다.

    이름이 없으면 우선주/스팩/리츠 배제 규칙을 적용할 수 없으므로, 호출부에서
    해당 티커를 유니버스에서 제외한다(티커 숫자열을 이름으로 대신 쓰지 않는다).
    첫 호출에서 전체 종목 테이블을 받아 캐시하므로 두 번째부터는 네트워크
    호출이 없다 (2026-08-12 실측: 1회차 ~7초, 이후 0초).
    """
    try:
        return stock.get_market_ticker_name(ticker)
    except Exception as exc:  # noqa: BLE001
        log.warning("종목명 조회 실패 %s: %s", ticker, exc)
        return None


def build_swing_universe(target: str, p: SwingParams) -> list[tuple[str, str, str]]:
    """KOSPI/KOSDAQ 시총 상위 (100-cut)%에서 제외 규칙을 적용한 유니버스 (I/O).

    반환: (ticker, name, market) 리스트. 시총 단면 조회 실패는 예외를 전파해
    배치를 중단시킨다 (조용한 빈 결과 금지).
    """
    try:
        etfs = etf_ticker_set()
    except Exception as exc:  # noqa: BLE001 - 조회 실패 시 교차 제외 없이 진행
        log.warning("ETF 티커 목록 조회 실패, 교차 제외 없이 진행: %s", exc)
        etfs = set()

    out: list[tuple[str, str, str]] = []
    for market in ("KOSPI", "KOSDAQ"):
        cap_df = fetch_market_cap(target, market)
        tickers = top_by_market_cap(cap_df, p.mcap_percentile_cut)
        for ticker in tickers:
            if ticker in etfs:
                continue
            if float(cap_df.at[ticker, "종가"]) < p.min_price:
                continue
            name = _ticker_name(ticker)
            if name is None:
                continue
            if is_excluded_name(name):
                continue
            out.append((ticker, name, market))
        log.info("%s 시총컷 %d종목 -> 유니버스 누적 %d종목", market, len(tickers), len(out))
    return out
