import argparse
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from turtle.calendar import lookback_start
from turtle.config import AccountConfig, load_config
from turtle.data.krx import KrxFetcher
from turtle.data.upbit import UpbitFetcher
from turtle.indicators import IndicatorResult, compute_indicators
from turtle.signals import BREAKOUT_CLOSE, BREAKOUT_TODAY, classify
from turtle.trading_params import compute_trading_params


@dataclass(frozen=True)
class Unit:
    entry_price: float
    size: float
    entry_date: str


@dataclass
class OpenPosition:
    units: list[Unit]
    n: float
    stop_price: float
    chandelier_stop: float


@dataclass(frozen=True)
class Trade:
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    units: int
    size: float
    pnl: float
    pnl_pct: float
    exit_reason: str


def close_position(
    position: OpenPosition, exit_date: pd.Timestamp, exit_price: float, reason: str
) -> Trade:
    total_size = sum(u.size for u in position.units)
    avg_price = sum(u.entry_price * u.size for u in position.units) / total_size
    pnl = (exit_price - avg_price) * total_size
    pnl_pct = (exit_price - avg_price) / avg_price * 100
    return Trade(
        entry_date=position.units[0].entry_date,
        exit_date=exit_date.strftime("%Y-%m-%d"),
        entry_price=avg_price,
        exit_price=exit_price,
        units=len(position.units),
        size=total_size,
        pnl=pnl,
        pnl_pct=pnl_pct,
        exit_reason=reason,
    )


def enter_position(
    row: pd.Series,
    ind: IndicatorResult,
    day: pd.Timestamp,
    account: AccountConfig,
    min_unit: float,
    approaching_pct: float,
) -> OpenPosition | None:
    status = classify(
        today_high=float(row["high"]),
        today_low=float(row["low"]),
        today_close=float(row["close"]),
        high_55=ind.high_55,
        low_20=ind.low_20,
        approaching_pct=approaching_pct,
        sma_200=ind.sma_200,
    )
    if status not in (BREAKOUT_TODAY, BREAKOUT_CLOSE):
        return None
    params = compute_trading_params(ind.high_55, ind.atr_20, account, min_unit)
    if not params.tradable:
        return None
    unit = Unit(entry_price=ind.high_55, size=params.unit_size, entry_date=day.strftime("%Y-%m-%d"))
    return OpenPosition(
        units=[unit], n=ind.atr_20, stop_price=params.stop_loss_price,
        chandelier_stop=ind.high_22 - 3 * ind.atr_20,
    )


def add_pyramid_unit(
    position: OpenPosition,
    row: pd.Series,
    day: pd.Timestamp,
    account: AccountConfig,
    min_unit: float,
) -> None:
    if len(position.units) >= account.max_units_per_asset:
        return
    first_entry = position.units[0].entry_price
    params = compute_trading_params(first_entry, position.n, account, min_unit)
    levels = [params.pyramid_1_price, params.pyramid_2_price, params.pyramid_3_price]
    idx = len(position.units) - 1
    if idx >= len(levels):
        return
    level = levels[idx]
    if float(row["close"]) >= level:
        position.units.append(
            Unit(entry_price=level, size=params.unit_size, entry_date=day.strftime("%Y-%m-%d"))
        )
        position.stop_price = level - 2 * position.n


def check_exit(
    position: OpenPosition, row: pd.Series, ind: IndicatorResult, day: pd.Timestamp
) -> Trade | None:
    close = float(row["close"])
    breach_2n = close <= position.stop_price
    breach_10d = close <= ind.low_10
    if not (breach_2n or breach_10d):
        return None
    if breach_2n and breach_10d:
        reason = "2N+10D"
    elif breach_2n:
        reason = "2N"
    else:
        reason = "10D"
    return close_position(position, day, close, reason)


def run_backtest(
    df: pd.DataFrame,
    start: str,
    end: str,
    account: AccountConfig,
    min_unit: float = 1.0,
    approaching_pct: float = 0.98,
) -> list[Trade]:
    df = df.sort_index()
    start_dt = pd.Timestamp(datetime.strptime(start, "%Y%m%d"))
    end_dt = pd.Timestamp(datetime.strptime(end, "%Y%m%d"))
    start_idx = int(df.index.searchsorted(start_dt, side="left"))
    if start_idx >= len(df) or df.index[start_idx] > end_dt:
        raise ValueError(f"{start}~{end} 구간에 데이터가 없음")

    warmup_ind = compute_indicators(df.iloc[: start_idx + 1])
    if warmup_ind.sma_200 != warmup_ind.sma_200:  # NaN
        raise ValueError("워밍업 데이터 부족 (SMA200 계산에 최소 200거래일 필요)")

    trades: list[Trade] = []
    position: OpenPosition | None = None

    for i in range(start_idx, len(df)):
        day = df.index[i]
        if day > end_dt:
            break
        row = df.iloc[i]
        ind = compute_indicators(df.iloc[: i + 1])

        if position is not None:
            trade = check_exit(position, row, ind, day)
            if trade is not None:
                trades.append(trade)
                position = None

        if position is None:
            position = enter_position(row, ind, day, account, min_unit, approaching_pct)
        else:
            add_pyramid_unit(position, row, day, account, min_unit)

    return trades


def main() -> None:
    # backtest_report가 turtle.backtest.Trade를 임포트하므로 (모듈 최상단에서
    # 서로를 임포트하면 순환 임포트가 발생), main() 내부에서 지연 임포트한다.
    from turtle.backtest_report import compute_metrics, format_backtest_report

    parser = argparse.ArgumentParser(description="터틀 트레이딩 단일 종목 백테스트")
    parser.add_argument("--ticker", required=True, help="종목/코인 코드 (예: 005930, KRW-BTC)")
    parser.add_argument("--market", required=True, choices=["STOCK", "ETF", "CRYPTO"])
    parser.add_argument("--start", required=True, help="YYYYMMDD")
    parser.add_argument("--end", required=True, help="YYYYMMDD")
    args = parser.parse_args()

    cfg = load_config()
    fetcher = UpbitFetcher() if args.market == "CRYPTO" else KrxFetcher()
    lookback = lookback_start(args.start, days=520)
    df = fetcher.get_ohlcv(args.ticker, lookback, args.end)
    min_unit = cfg.filters_crypto.min_unit if args.market == "CRYPTO" else 1.0

    trades = run_backtest(df, args.start, args.end, cfg.account, min_unit, cfg.approaching_pct)
    metrics = compute_metrics(trades, cfg.account.total_value, args.start, args.end)
    print(format_backtest_report(args.ticker, args.start, args.end, trades, metrics))


if __name__ == "__main__":
    main()
