import dataclasses
import logging
from datetime import date, timedelta

from swing.params import SwingParams
from swing.report import SwingCandidate, format_swing_report
from swing.screener import avg_turnover_20, screen
from swing.universe import build_swing_universe
from turtle.calendar import get_business_days, lookback_start, resolve_target_date
from turtle.data.base import CachingFetcher
from turtle.data.krx import get_investor_net_buy_value
from turtle.report.telegram import send_telegram

log = logging.getLogger(__name__)

# 101거래일(SwingParams.required_bars)을 확보하기 위한 달력일 룩백.
# 250달력일이면 연휴를 최대로 잡아도 여유가 있다.
_LOOKBACK_DAYS = 250


def _resolve_target(target: date | None) -> date:
    """요청일(또는 None)을 실제 거래일로 확정한다 (I/O)."""
    anchor = (target or date.today()).strftime("%Y%m%d")
    bdays = get_business_days(lookback_start(anchor, days=30), anchor)
    return resolve_target_date(target, bdays)


def run(
    target: date | None,
    p: SwingParams,
    fetcher,
    bot_token: str,
    chat_id: str,
    send: bool = True,
) -> str:
    """스윙 눌림목 스크리닝 파이프라인 (I/O).

    무상태: 캐시·DB에 아무것도 쓰지 않고 매 실행마다 원천에서 다시 계산한다.
    """
    resolved = _resolve_target(target)
    target_str = resolved.strftime("%Y%m%d")
    lookback = lookback_start(target_str, days=_LOOKBACK_DAYS)

    universe = build_swing_universe(target_str, p)
    log.info("유니버스 %d종목", len(universe))

    cached = CachingFetcher(fetcher)
    candidates: list[SwingCandidate] = []
    for ticker, name, market in universe:
        try:
            df = cached.get_ohlcv(ticker, lookback, target_str)
            if len(df) < p.required_bars:  # 신규상장 등 히스토리 부족
                continue
            turnover = avg_turnover_20(df)
            if turnover < p.liquidity_min_value:
                continue
            sig = screen(df, p)
            if sig is None:
                continue
            candidates.append(
                SwingCandidate(
                    ticker=ticker,
                    name=name,
                    market=market,
                    close=sig.close,
                    pole_date=sig.pole_date,
                    elapsed=sig.elapsed,
                    retrace_pct=sig.retrace_pct,
                    avg_turnover_20=turnover,
                )
            )
        except Exception as exc:  # noqa: BLE001 - 종목별 실패가 배치를 막지 않도록
            log.warning("스크리닝 실패 %s: %s", ticker, exc)

    candidates.sort(key=lambda c: c.avg_turnover_20, reverse=True)
    log.info("후보 %d종목", len(candidates))

    # 부가정보: 장대양봉 다음 거래일 ~ 오늘의 외국인+기관 누적 순매수.
    # 실패는 후보 탈락 사유가 아니다 (net_buy=None -> N/A 표시).
    for i, c in enumerate(candidates):
        start = (c.pole_date + timedelta(days=1)).strftime("%Y%m%d")
        try:
            value = get_investor_net_buy_value(c.ticker, start, target_str)
            candidates[i] = dataclasses.replace(c, net_buy=value)
        except Exception as exc:  # noqa: BLE001
            log.warning("순매수 조회 실패 %s: %s", c.ticker, exc)

    text = format_swing_report(
        resolved.strftime("%Y-%m-%d"), candidates, scanned=len(universe)
    )
    if send and (candidates or p.notify_empty):
        try:
            send_telegram(text, bot_token, chat_id)
        except Exception as exc:  # noqa: BLE001
            log.error("텔레그램 전송 실패: %s", exc)
    return text
