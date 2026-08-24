import logging

from turtle.universe.krx_etf import etf_ticker_set
from turtle.universe.krx_stocks import _top_by_cap

log = logging.getLogger(__name__)


def build_momentum_universe(
    top_n_kospi: int = 200, top_n_kosdaq: int = 200
) -> list[tuple[str, str]]:
    """KOSPI/KOSDAQ 시가총액 상위 종목의 (ticker, market) 목록 (I/O).

    **상위 200을 넘기지 말 것.** 400으로 넓히면 소형 구간이 들어와 거래당 성능이
    무너진다 (2022-01~2026-08 재측정, 같은 BASE 청산 규칙):

        top200x2  종목 221 / 신호  923 / 평균 +4.30% / CAGR +32.0% / MDD -10.3%
        top400x2  종목 476 / 신호 1990 / 평균 +2.57% / CAGR +15.9% / MDD -22.2%

    거래대금 상한(§3.1)을 올렸을 때와 같은 열화 패턴이다. 청산 규칙을 어떻게
    조정해도 이 차이를 메우지 못한다.

    docs/momentum_screener_spec.md §8 검증 절차와 동일한 유니버스 정의다 — 우선주·
    스팩 등을 별도로 걸러내지 않는다. §6 실측이 이 정의 그대로 돌린 결과이므로,
    필터를 추가하면 검증된 성과와 실운영 결과가 달라진다. 유동성·정배열 조건은
    검색기 쪽(swing.momentum_screener)이 이미 걸러낸다.

    ETF는 시총 랭킹에 섞여 나오므로 등록된 ETF 티커 목록과 교차 제외한다.
    """
    try:
        etfs = etf_ticker_set()
    except Exception as exc:  # noqa: BLE001 - 조회 실패 시 교차 제외 없이 진행
        log.warning("ETF 티커 목록 조회 실패, 교차 제외 없이 진행: %s", exc)
        etfs = set()

    out: list[tuple[str, str]] = []
    for market, top_n in (("KOSPI", top_n_kospi), ("KOSDAQ", top_n_kosdaq)):
        cap_df = _top_by_cap(market, top_n)
        added = 0
        for ticker in cap_df.index:
            if ticker in etfs:
                continue
            out.append((str(ticker), market))
            added += 1
        log.info("%s 시총상위 %d종목 -> 유니버스 누적 %d종목", market, added, len(out))
    return out
