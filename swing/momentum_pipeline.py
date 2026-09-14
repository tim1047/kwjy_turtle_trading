import dataclasses
import logging
from datetime import date

import pandas as pd
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


def _scan_day(
    cached, universe: list[tuple[str, str]], resolved: date, p: MomentumScreenerParams
) -> tuple[list[MomentumCandidate], int, float | None]:
    """하루치 신규 편입 스캔 (I/O). (후보, 스캔종목수, 시장국면)을 돌려준다.

    단일 날짜 실행(run)과 기간 스캔(run_range)이 공유하는 코어다 — 두 경로가
    같은 날짜에 대해 반드시 같은 결과를 내도록 한 곳에 모아 둔다.
    """
    target_str = resolved.strftime("%Y%m%d")
    lookback = lookback_start(target_str, days=_LOOKBACK_DAYS)

    regime = market_momentum(cached, target_str, p)
    candidates, scanned = _scan_candidates(cached, universe, lookback, target_str, p)
    log.info("%s 신규 편입 후보 %d종목", resolved, len(candidates))
    return candidates, scanned, regime


class _AsOfSlice:
    """기간 스캔 전용 페처 래퍼 — 캐시된 광역 프레임을 as_of까지 잘라 준다.

    기간 스캔은 날짜마다 target이 달라지므로, 그대로 두면 CachingFetcher의 키
    (ticker, start, end)가 매일 어긋나 유니버스 전체를 하루당 다시 조회한다
    (400종목 x 거래일수). 그래서 조회 자체는 구간 전체(fetch_start~fetch_end)로
    한 번만 하고, 날짜별 판정에는 그 프레임의 슬라이스를 넘긴다.

    슬라이스 구간은 호출측이 요청한 start부터 as_of까지다 — 뒤를 자르는 것은
    룩어헤드 방지이고, 앞을 요청대로 맞추는 것은 단일 날짜 실행과 룩백 창을
    동일하게 유지하기 위해서다 (쿨다운 판정이 이력 길이에 의존한다).
    """

    def __init__(self, inner, fetch_start: str, fetch_end: str, as_of: date):
        self._inner = inner
        self._fetch_start = fetch_start
        self._fetch_end = fetch_end
        self._as_of = pd.Timestamp(as_of)

    def get_ohlcv(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        df = self._inner.get_ohlcv(ticker, self._fetch_start, self._fetch_end)
        return df.loc[pd.Timestamp(start) : self._as_of]


def run_range(
    start: date,
    end: date,
    p: MomentumScreenerParams,
    fetcher,
) -> str:
    """구간 내 모든 거래일을 하루씩 스캔해 리포트를 이어 붙인다 (I/O).

    과거 시그널을 훑어보는 조사용 모드다. 일일 운영 경로(run)와 두 가지가 다르다:

      1. 청산 알림을 내지 않는다 — momentum_position의 보유 포지션은 "현재" 상태라
         과거 날짜에 대입하면 의미가 없다.
      2. 텔레그램으로 보내지 않는다 — 거래일 수만큼 메시지가 나가기 때문이다.

    유니버스는 날짜마다 그 거래일의 KRX 시총 단면으로 다시 잡는다 — 같은 날짜면
    run과 같은 유니버스를 쓰므로 두 경로의 결과가 일치한다. 거래일당 KRX 단면
    조회가 2회(KOSPI/KOSDAQ) 늘지만, 종목별 OHLCV는 CachingFetcher가 구간 전체로
    한 번만 받는다 (날짜별로 새로 편입된 종목도 처음 등장할 때 한 번).
    """
    bdays = get_business_days(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
    if not bdays:
        raise ValueError(f"{start}~{end} 구간에 거래일이 없음")

    fetch_start = lookback_start(bdays[0].strftime("%Y%m%d"), days=_LOOKBACK_DAYS)
    fetch_end = bdays[-1].strftime("%Y%m%d")

    cached = CachingFetcher(fetcher)
    log.info("거래일 %d일 스캔", len(bdays))

    reports = []
    for day in bdays:
        universe = build_momentum_universe(day.strftime("%Y%m%d"))
        log.info("%s 유니버스 %d종목", day, len(universe))
        as_of = _AsOfSlice(cached, fetch_start, fetch_end, day)
        candidates, scanned, regime = _scan_day(as_of, universe, day, p)
        reports.append(
            format_momentum_report(
                day.strftime("%Y-%m-%d"), candidates, [], scanned, regime
            )
        )
    return "\n\n".join(reports)


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

    universe = build_momentum_universe(target_str)
    log.info("유니버스 %d종목", len(universe))

    candidates, scanned, regime = _scan_day(cached, universe, resolved, p)

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
