import logging
from datetime import date

import requests
from pykrx import stock as pykrx_stock

from turtle.calendar import get_business_days, lookback_start, resolve_target_date
from turtle.config import Config
from turtle.data.base import CachingFetcher, with_retry
from turtle.indicators import compute_indicators
from turtle.positions.store import get_open_positions
from turtle.report.telegram import ScreenResult, format_report, format_stoploss_report, send_telegram
from turtle.signals import APPROACHING, BREAKOUT_CLOSE, BREAKOUT_TODAY, classify
from turtle.stoploss import check_position
from turtle.trading_params import compute_trading_params
from turtle.universe.krx_etf import build_etf_universe
from turtle.universe.krx_stocks import build_stock_universe

log = logging.getLogger(__name__)

# ETF 종목명 조회용. krx_etf.py의 _etf_ticker_list()가 사용하는 것과 동일한
# 네이버 금융 ETF 목록 JSON(이미 Task 7에서 검증된 안정 경로)이지만, 그 함수는
# itemcode만 반환하고 itemname은 버린다. build_etf_universe()의 반환 타입(리스트)을
# 바꾸지 않기 위해, 리포트용 이름 매핑은 이 모듈에서 별도로 조회한다.
_ETF_LIST_URL = "https://finance.naver.com/api/sise/etfItemList.naver"


def screen_ticker(ticker: str, name: str, market: str, df, cfg: Config) -> ScreenResult:
    """지표 계산 -> 신호 분류 -> 매매 파라미터 계산을 하나로 묶는 순수 함수.

    df는 표준 OHLCV 스키마(DatetimeIndex, open/high/low/close/volume)를
    따라야 하며, 네트워크 호출은 전혀 하지 않는다.
    """
    ind = compute_indicators(df)
    today_high = float(df["high"].iloc[-1])
    today_low = float(df["low"].iloc[-1])

    status = classify(
        today_high=today_high,
        today_low=today_low,
        today_close=ind.close,
        high_55=ind.high_55,
        low_20=ind.low_20,
        approaching_pct=cfg.approaching_pct,
        sma_200=ind.sma_200,
    )
    min_unit = cfg.filters_crypto.min_unit if market == "CRYPTO" else 1.0
    params = compute_trading_params(ind.high_55, ind.atr_20, cfg.account, min_unit=min_unit)
    gap_pct = (
        (ind.high_55 - ind.close) / ind.high_55 * 100 if ind.high_55 else 0.0
    )
    return ScreenResult(
        ticker=ticker,
        name=name,
        market=market,
        close=ind.close,
        entry_trigger=ind.high_55,
        n=ind.atr_20,
        stop_loss_price=params.stop_loss_price,
        unit_size=params.unit_size,
        unit_notional=params.unit_notional,
        status=status,
        gap_pct=gap_pct,
        tradable=params.tradable,
        note=params.note,
        adx=ind.adx_14,
    )


def _stock_name(ticker: str) -> str:
    """종목명 조회 (I/O). 실패 시 티커를 그대로 이름으로 사용한다.

    pykrx.stock.get_market_ticker_name은 Task 7 스파이크에서 여전히
    정상 동작함이 확인된 경로다 (krx_stocks.py의 _build_metrics에서도 사용 중).
    """
    try:
        return pykrx_stock.get_market_ticker_name(ticker)
    except Exception as exc:  # noqa: BLE001
        log.warning("종목명 조회 실패 %s: %s", ticker, exc)
        return ticker


def _etf_name_map() -> dict:
    """ETF 티커 -> 이름 매핑 (I/O). 실패 시 빈 dict를 반환한다 (호출측이 티커로 대체)."""

    def _call():
        resp = requests.get(
            _ETF_LIST_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=10
        )
        resp.raise_for_status()
        return resp.json()

    try:
        data = with_retry(_call, retries=3, base_delay=1.0)
        items = data.get("result", {}).get("etfItemList", [])
        return {item["itemcode"]: item["itemname"] for item in items}
    except Exception as exc:  # noqa: BLE001
        log.warning("ETF 이름 목록 조회 실패: %s", exc)
        return {}


def _resolve_target(target: date | None) -> date:
    """요청일(또는 None)을 실제 거래일로 확정한다 (I/O).

    30 달력일 룩백이면 한국 증시에서 가장 긴 연휴(설/추석)를 포함해도
    거래일을 하나는 반드시 포함하기에 충분하다.
    """
    anchor = target or date.today()
    anchor_str = anchor.strftime("%Y%m%d")
    probe_start = lookback_start(anchor_str, days=30)
    bdays = get_business_days(probe_start, anchor_str)
    return resolve_target_date(target, bdays)


def run(target: date | None, cfg: Config, fetchers: dict, send: bool = True) -> str:
    """전체 스크리닝 파이프라인 오케스트레이션 (I/O).

    무상태: 매 호출마다 target_str로부터 전부 다시 계산하며, 디스크/DB에
    아무것도 쓰지 않는다. fetchers는 {"STOCK": ..., "ETF": ..., "CRYPTO": ...}
    형태로 자산군별 DataFetcher를 담는다.
    """
    resolved = _resolve_target(target)
    target_str = resolved.strftime("%Y%m%d")
    lookback = lookback_start(target_str, days=520)  # min_listing_days(300거래일) 확보용 여유

    results = []
    counts = {"stocks": 0, "etf": 0, "crypto": 0}

    if cfg.assets.get("stocks"):
        stock_fetcher = CachingFetcher(fetchers["STOCK"])
        tickers = build_stock_universe(target_str, cfg.filters_stocks, stock_fetcher, lookback)
        counts["stocks"] = len(tickers)
        for t in tickers:
            try:
                df = stock_fetcher.get_ohlcv(t, lookback, target_str)
                results.append(screen_ticker(t, _stock_name(t), "STOCK", df, cfg))
            except Exception as exc:  # noqa: BLE001 - 종목별 실패가 배치를 막지 않도록
                log.warning("스크리닝 실패 %s: %s", t, exc)

    if cfg.assets.get("etf"):
        etf_fetcher = CachingFetcher(fetchers["ETF"])
        etfs = build_etf_universe(target_str, cfg.filters_stocks, etf_fetcher, lookback)
        counts["etf"] = len(etfs)
        names = _etf_name_map()
        for t in etfs:
            try:
                df = etf_fetcher.get_ohlcv(t, lookback, target_str)
                results.append(screen_ticker(t, names.get(t, t), "ETF", df, cfg))
            except Exception as exc:  # noqa: BLE001 - 종목별 실패가 배치를 막지 않도록
                log.warning("ETF 스크리닝 실패 %s: %s", t, exc)

    if cfg.assets.get("crypto"):
        crypto_target = date.today().strftime("%Y%m%d")
        crypto_lookback = lookback_start(crypto_target, days=520)
        crypto_fetcher = fetchers["CRYPTO"]
        counts["crypto"] = len(cfg.filters_crypto.tickers)
        for t in cfg.filters_crypto.tickers:
            try:
                df = crypto_fetcher.get_ohlcv(t, crypto_lookback, crypto_target)
                results.append(screen_ticker(t, t, "CRYPTO", df, cfg))
            except Exception as exc:  # noqa: BLE001 - 종목별 실패가 배치를 막지 않도록
                log.warning("코인 스크리닝 실패 %s: %s", t, exc)

    # 리포트에는 신호 있는 종목만 (NEUTRAL 제외)
    signalled = [
        r for r in results
        if r.status in (BREAKOUT_TODAY, BREAKOUT_CLOSE, APPROACHING)
    ]
    text = format_report(resolved.strftime("%Y-%m-%d"), signalled, counts)
    if send:
        try:
            send_telegram(text, cfg.telegram_bot_token, cfg.telegram_chat_id)
        except Exception as exc:  # noqa: BLE001
            log.error("텔레그램 전송 실패: %s", exc)
    return text


def run_stoploss_check(
    target: date | None, cfg: Config, fetchers: dict, send: bool = True
) -> str:
    """보유종목(positions 테이블) 2N/10일저가 손절 체크 (I/O).

    positions 테이블엔 status 컬럼이 없다 — 행이 존재 = 보유중으로 취급하며,
    매도된 종목 행 삭제는 사용자가 수동으로 처리한다. fetchers는
    {"STOCK": ..., "ETF": ..., "CRYPTO": ...} 형태이며 포지션의 market으로 라우팅한다.
    """
    resolved = _resolve_target(target)
    target_str = resolved.strftime("%Y%m%d")
    lookback = lookback_start(target_str, days=30)  # 10일 저가 계산에 충분한 여유
    crypto_target = date.today().strftime("%Y%m%d")
    crypto_lookback = lookback_start(crypto_target, days=30)

    try:
        positions = get_open_positions(cfg.database_url)
    except Exception as exc:  # noqa: BLE001 - DB 조회 실패가 매수 신호 스캔을 막지 않도록
        log.warning("보유종목 조회 실패: %s", exc)
        positions = []

    results = []
    for p in positions:
        try:
            # p.market은 STOCK/ETF/CRYPTO만 유효(positions 테이블 문서화된 값역) —
            # 그 외 값은 KeyError로 아래 except에서 로그 후 스킵된다(다른 자산군으로 오탐 라우팅하는 것보다 안전).
            fetcher = fetchers[p.market]
            if p.market == "CRYPTO":
                df = fetcher.get_ohlcv(p.ticker, crypto_lookback, crypto_target)
            else:
                df = fetcher.get_ohlcv(p.ticker, lookback, target_str)
            results.append(check_position(p, df))
        except Exception as exc:  # noqa: BLE001 - 종목별 실패가 배치를 막지 않도록
            log.warning("손절가 체크 실패 %s: %s", p.ticker, exc)

    text = format_stoploss_report(resolved.strftime("%Y-%m-%d"), results)
    if send:
        try:
            send_telegram(text, cfg.telegram_bot_token, cfg.telegram_chat_id)
        except Exception as exc:  # noqa: BLE001
            log.error("텔레그램 전송 실패: %s", exc)
    return text
