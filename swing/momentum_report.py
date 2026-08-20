from dataclasses import dataclass
from html import escape as _esc

from swing.momentum_exit import ExitDecision
from swing.momentum_positions import MomentumPosition


@dataclass(frozen=True)
class MomentumCandidate:
    """신규 편입 후보 1종목."""

    ticker: str
    name: str
    market: str
    close: float  # 진입가(신호일 종가)
    stop_price: float
    turnover_med: float  # 20일 거래대금 중앙값(원)


def _fmt_won(v: float) -> str:
    return f"{v:,.0f}"


def _fmt_pct(v: float) -> str:
    return f"{v:+.1f}%"


_ACTION_LABEL = {"STOP": "⛔ 손절", "TIME": "⏰ 보유기간 만료"}


def _candidate_card(idx: int, c: MomentumCandidate) -> str:
    stop_pct = (c.stop_price / c.close - 1) * 100 if c.close else 0.0
    return (
        f"{idx}. <b>{_esc(c.name)}</b> <code>{_esc(c.ticker)}</code> · "
        f"{_esc(c.market)} · {_fmt_won(c.close)}원\n"
        f"   손절 {_fmt_won(c.stop_price)}원 ({_fmt_pct(stop_pct)}) · "
        f"거래대금중앙 {c.turnover_med / 1e8:,.0f}억"
    )


def _exit_card(pos: MomentumPosition, d: ExitDecision) -> str:
    label = _ACTION_LABEL.get(d.action, d.action)
    ret_pct = (d.price / pos.entry_price - 1) * 100 if pos.entry_price else 0.0
    return (
        f"{label} <b>{_esc(pos.name)}</b> <code>{_esc(pos.ticker)}</code>\n"
        f"   진입 {_fmt_won(pos.entry_price)}원 ({_esc(pos.entry_date)}) · "
        f"청산가 {_fmt_won(d.price)}원 ({_fmt_pct(ret_pct)}) · 보유 {d.days_held}거래일"
    )


def _fmt_regime(market_momentum_pct: float | None) -> str:
    if market_momentum_pct is None:
        return "N/A"
    label = "상승" if market_momentum_pct > 0 else "하락"
    return f"{market_momentum_pct:+.1f}% ({label})"


def format_momentum_report(
    target: str,
    candidates: list[MomentumCandidate],
    exits: list[tuple[MomentumPosition, ExitDecision]],
    scanned: int,
    market_momentum_pct: float | None,
) -> str:
    """텔레그램 발송용 HTML 메시지를 만든다 (순수 함수).

    market_momentum_pct는 정보성 표시일 뿐 후보 필터링에 쓰이지 않는다
    (docs/momentum_screener_spec.md §3.4). exits는 action이 STOP/TIME인 것만
    호출측이 걸러서 넘겨야 한다 — HOLD는 알림 대상이 아니다.
    """
    lines = [
        f"🚀 <b>모멘텀 검색기</b> — {_esc(target)}",
        f"시장 국면: {_fmt_regime(market_momentum_pct)} "
        f"— 최근 20거래일 KODEX200/코스닥150 평균",
        f"스캔 {scanned:,}종목 / 신규 후보 {len(candidates)}종목 / 청산 알림 {len(exits)}건",
        "",
        "🆕 <b>신규 편입 후보</b>",
    ]
    if candidates:
        for i, c in enumerate(candidates, start=1):
            lines.append(_candidate_card(i, c))
            lines.append("")
    else:
        lines.append("• 없음")
        lines.append("")

    lines.append("📤 <b>청산 알림</b> (보유 종목)")
    if exits:
        for pos, d in exits:
            lines.append(_exit_card(pos, d))
            lines.append("")
    else:
        lines.append("• 없음")

    return "\n".join(lines).rstrip()
