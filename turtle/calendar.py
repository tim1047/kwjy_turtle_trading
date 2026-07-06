from datetime import date, datetime, timedelta

from pykrx import stock

from turtle.data.base import with_retry

# 거래일 목록 산출용 기준 종목.
#
# 스파이크 결과 (pykrx 1.2.8, 2026-07-06 실행):
#   stock.get_previous_business_days(fromdate="20240601", todate="20240630")
#   -> [] (빈 리스트). 원인: 이 함수는 내부적으로
#      pykrx.website.krx.market.wrap.get_market_ohlcv_by_date() 를 직접 호출하는데,
#      이는 data.krx.co.kr의 원본 API(dbms/MDC/STAT/standard/MDCSTAT01701)를
#      세션 쿠키 없이 그대로 POST 하여 "400 LOGOUT" 응답을 받는다
#      (raw requests.post로 재현 확인). year/month 형태 호출도 동일 경로라 마찬가지로
#      깨져 있음 (RangeIndex.month AttributeError).
#   반면 stock.get_market_ohlcv(start, end, ticker)는 (adjusted=True 기본값일 때)
#      naver.get_market_ohlcv_by_date()를 경유하며, 이는 안정적으로 응답한다
#      (turtle/data/krx.py의 KrxFetcher가 이미 이 경로를 사용 중).
# 따라서 브리프가 허용한 대안인 "OHLCV index 기반"으로 구현한다: 삼성전자(005930)는
# KRX 최유동성 종목으로 거래정지 리스크가 사실상 없어, 실제 거래일이면 항상 시세가
# 존재한다 -> 그 인덱스가 곧 거래일 목록이다.
_REFERENCE_TICKER = "005930"


def resolve_target_date(requested: date | None, business_days: list[date]) -> date:
    """요청일이 거래일이면 그대로, 아니면 그 이하 최근 거래일을 반환한다.

    requested가 None이면 가장 최근 거래일을 반환한다.
    순수 함수 (I/O 없음).
    """
    days = sorted(business_days)
    if not days:
        raise ValueError("business_days가 비어 있음")
    if requested is None:
        return days[-1]
    eligible = [d for d in days if d <= requested]
    if not eligible:
        raise ValueError(f"{requested} 이전에 거래일이 없음")
    return eligible[-1]


def lookback_start(target: str, days: int = 320) -> str:
    """target("YYYYMMDD") 기준 달력일로 days만큼 이전 날짜를 "YYYYMMDD"로 반환한다.

    여유분을 포함한 조회 시작일을 만드는 용도 (예: 320일 지표 계산용 룩백).
    순수 함수 (I/O 없음).
    """
    d = datetime.strptime(target, "%Y%m%d").date()
    return (d - timedelta(days=days)).strftime("%Y%m%d")


def get_business_days(start: str, end: str) -> list[date]:
    """start~end("YYYYMMDD") 사이의 실제 거래일 목록을 조회한다 (I/O).

    기준 종목(_REFERENCE_TICKER)의 OHLCV 인덱스를 거래일 목록으로 사용한다.
    """

    def _call():
        return stock.get_market_ohlcv(start, end, _REFERENCE_TICKER)

    raw = with_retry(_call, retries=3, base_delay=1.0)
    return [ts.date() for ts in raw.index]
