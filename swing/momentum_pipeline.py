import dataclasses
import logging
from datetime import date

from pykrx import stock

from swing.momentum_exit import check_exit
from swing.momentum_params import MomentumScreenerParams
from swing.momentum_positions import get_open_positions
from swing.momentum_report import MomentumCandidate, format_momentum_report
from swing.momentum_screener import (
    compute_screener_features,
    has_fresh_signal,
    market_momentum,
)
from swing.momentum_universe import build_momentum_universe
from turtle.calendar import get_business_days, lookback_start, resolve_target_date
from turtle.data.base import CachingFetcher
from turtle.report.telegram import send_telegram

log = logging.getLogger(__name__)

# min_bars(180거래일) + watch_lookback(60일) 롤링 계산과 보유 포지션의 entry_date
# 조회를 모두 커버하는 달력일 룩백. 기존 swing 파이프라인(250일)보다 이력 요구치가
# 커서 여유를 더 뒀다.
_LOOKBACK_DAYS = 380


def _resolve_target(target: date | None) -> date:
    """요청일(또는 None)을 실제 거래일로 확정한다 (I/O)."""
    anchor = (target or date.today()).strftime("%Y%m%d")
    bdays = get_business_days(lookback_start(anchor, days=30), anchor)
    return resolve_target_date(target, bdays)


def _ticker_name(ticker: str) -> str | None:
    """종목명 조회 (I/O). 실패 시 None — 호출부가 해당 티커를 건너뛴다."""
    try:
        return stock.get_market_ticker_name(ticker)
    except Exception as exc:  # noqa: BLE001
        log.warning("종목명 조회 실패 %s: %s", ticker, exc)
        return None


def _scan_candidates(
    cached, universe: list[tuple[str, str]], lookback: str, target_str: str, p: MomentumScreenerParams
) -> tuple[list[MomentumCandidate], int]:
    """유니버스를 스캔해 신규 편입 후보를 뽑는다 (I/O). 종목별 실패는 격리한다."""
    candidates: list[MomentumCandidate] = []
    scanned = 0
    for ticker, market in universe:
        try:
            df = cached.get_ohlcv(ticker, lookback, target_str)
            scanned += 1
            if len(df) < p.min_bars:
                continue
            if not has_fresh_signal(df, p):
                continue
            name = _ticker_name(ticker)
            if name is None:
                continue
            close = float(df["close"].iloc[-1])
            f = compute_screener_features(df, p)
            turnover = float(f["turnover_med"].iloc[-1])
            candidates.append(
                MomentumCandidate(
                    ticker=ticker,
                    name=name,
                    market=market,
                    close=close,
                    stop_price=close * (1 - p.stop_pct / 100),
                    turnover_med=turnover,
                )
            )
        except Exception as exc:  # noqa: BLE001 - 종목별 실패가 배치를 막지 않도록
            log.warning("스크리닝 실패 %s: %s", ticker, exc)
    candidates.sort(key=lambda c: c.turnover_med, reverse=True)
    return candidates, scanned


def _check_exits(cached, database_url: str, lookback: str, target_str: str, p: MomentumScreenerParams):
    """보유 포지션의 청산 여부를 판정한다 (I/O). HOLD는 알림 대상에서 뺀다.

    포지션 조회 자체가 실패하면(DB 미설정 등) 빈 리스트로 진행한다 — 청산 알림은
    부가 기능이고, 신규 후보 스캔을 막을 이유가 아니다.
    """
    try:
        positions = get_open_positions(database_url)
    except Exception as exc:  # noqa: BLE001
        log.warning("포지션 조회 실패, 청산 알림 생략: %s", exc)
        return []

    exits = []
    for pos in positions:
        try:
            df = cached.get_ohlcv(pos.ticker, lookback, target_str)
            pos_params = dataclasses.replace(p, hold_days=pos.hold_days)
            decision = check_exit(pos.entry_price, pos.stop_price, pos.entry_date, df, pos_params)
        except Exception as exc:  # noqa: BLE001
            log.warning("청산 판정 실패 %s: %s", pos.ticker, exc)
            continue
        if decision.action in ("STOP", "TIME"):
            exits.append((pos, decision))
    return exits


def run(
    target: date | None,
    p: MomentumScreenerParams,
    fetcher,
    database_url: str,
    bot_token: str,
    chat_id: str,
    send: bool = True,
) -> str:
    """모멘텀 검색기 일일 파이프라인 (I/O).

    두 가지를 함께 리포트한다:
      1. 신규 편입 후보 — 유니버스 스캔 (무상태, 매 실행마다 원천에서 재계산.
         쿨다운도 momentum_screener.has_fresh_signal이 이력에서 다시 복원한다).
      2. 청산 알림 — momentum_position 테이블의 보유 포지션에 대해 손절/보유기간
         만료 여부를 판정한다. 포지션은 사용자가 매수 후 수동으로 등록하고,
         매도 후 수동으로 삭제한다 (db/momentum_positions.sql, turtle.positions와
         동일한 설계 — 이 파이프라인은 매매를 자동 실행하지 않는다).
    """
    resolved = _resolve_target(target)
    target_str = resolved.strftime("%Y%m%d")
    lookback = lookback_start(target_str, days=_LOOKBACK_DAYS)

    cached = CachingFetcher(fetcher)

    regime = market_momentum(cached, target_str, p)

    universe = build_momentum_universe()
    log.info("유니버스 %d종목", len(universe))

    candidates, scanned = _scan_candidates(cached, universe, lookback, target_str, p)
    log.info("신규 편입 후보 %d종목", len(candidates))

    exits = _check_exits(cached, database_url, lookback, target_str, p)
    log.info("청산 알림 %d건", len(exits))

    text = format_momentum_report(
        resolved.strftime("%Y-%m-%d"), candidates, exits, scanned, regime
    )
    if send:
        try:
            send_telegram(text, bot_token, chat_id)
        except Exception as exc:  # noqa: BLE001
            log.error("텔레그램 전송 실패: %s", exc)
    return text
