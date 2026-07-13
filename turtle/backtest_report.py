from dataclasses import dataclass
from datetime import datetime

from turtle.backtest import Trade


@dataclass(frozen=True)
class BacktestMetrics:
    total_trades: int
    win_rate: float
    profit_factor: float
    cagr: float
    mdd: float


def compute_metrics(
    trades: list[Trade], initial_capital: float, start: str, end: str
) -> BacktestMetrics:
    if not trades:
        return BacktestMetrics(total_trades=0, win_rate=0.0, profit_factor=0.0, cagr=0.0, mdd=0.0)

    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    win_rate = len(wins) / len(trades) * 100

    gross_profit = sum(t.pnl for t in wins)
    gross_loss = abs(sum(t.pnl for t in losses))
    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    elif gross_profit > 0:
        profit_factor = float("inf")
    else:
        profit_factor = 0.0

    # 실현손익 누적 기준 자본곡선 (거래 청산 시점만 스텝) — 보유 중 미실현 손익은
    # v1에서 반영하지 않는다 (설계 문서의 단순화 결정과 동일 선상).
    equity = initial_capital
    curve = [initial_capital]
    for t in sorted(trades, key=lambda t: t.exit_date):
        equity += t.pnl
        curve.append(equity)
    peak = curve[0]
    mdd = 0.0
    for v in curve:
        peak = max(peak, v)
        if peak > 0:
            mdd = max(mdd, (peak - v) / peak * 100)

    start_dt = datetime.strptime(start, "%Y%m%d")
    end_dt = datetime.strptime(end, "%Y%m%d")
    years = max((end_dt - start_dt).days / 365.25, 1 / 365.25)
    final_capital = curve[-1]
    if initial_capital > 0 and final_capital > 0:
        cagr = ((final_capital / initial_capital) ** (1 / years) - 1) * 100
    else:
        cagr = 0.0

    return BacktestMetrics(
        total_trades=len(trades), win_rate=win_rate, profit_factor=profit_factor,
        cagr=cagr, mdd=mdd,
    )


def format_backtest_report(
    ticker: str, start: str, end: str, trades: list[Trade], metrics: BacktestMetrics
) -> str:
    lines = [f"백테스트 리포트 — {ticker} ({start}~{end})", ""]
    lines.append(
        f"거래 {metrics.total_trades}회 · 승률 {metrics.win_rate:.1f}% · "
        f"Profit Factor {metrics.profit_factor:.2f} · CAGR {metrics.cagr:.1f}% · MDD {metrics.mdd:.1f}%"
    )
    lines.append("")
    if not trades:
        lines.append("거래 없음")
        return "\n".join(lines)
    for t in trades:
        lines.append(
            f"{t.entry_date} → {t.exit_date} · {t.units}유닛 · "
            f"진입 {t.entry_price:,.0f} → 청산 {t.exit_price:,.0f} "
            f"({t.exit_reason}) · 손익 {t.pnl:,.0f} ({t.pnl_pct:+.2f}%)"
        )
    return "\n".join(lines)
