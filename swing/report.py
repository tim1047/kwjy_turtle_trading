from dataclasses import dataclass
from datetime import date
from html import escape as _esc


@dataclass(frozen=True)
class SwingCandidate:
    """최종 후보 1종목. net_buy는 부가정보이며 None이면 N/A로 표시한다."""

    ticker: str
    name: str
    market: str
    close: float
    pole_date: date
    elapsed: int
    retrace_pct: float
    avg_turnover_20: float
    net_buy: float | None = None  # 외국인+기관 누적 순매수 거래대금(원)


def _fmt_net_buy(v: float | None) -> str:
    return "N/A" if v is None else f"{v / 1e8:+,.1f}억"


def _card(idx: int, c: SwingCandidate) -> str:
    return (
        f"{idx}. <b>{_esc(c.name)}</b> <code>{_esc(c.ticker)}</code> · "
        f"{_esc(c.market)} · {c.close:,.0f}원\n"
        f"   장대양봉 {c.pole_date.strftime('%m-%d')} · 경과 {c.elapsed}일 · "
        f"되돌림 {c.retrace_pct:.1f}%\n"
        f"   외국인+기관 {_fmt_net_buy(c.net_buy)}"
    )


def format_swing_report(target: str, candidates: list, scanned: int) -> str:
    """텔레그램 발송용 HTML 메시지를 만든다 (순수 함수).

    candidates는 호출측이 정한 순서(거래대금 내림차순)를 그대로 유지한다.
    """
    lines = [
        f"📈 <b>눌림목 후보</b> — {_esc(target)}",
        f"스캔 {scanned:,}종목 / 후보 {len(candidates)}종목",
        "",
    ]
    if not candidates:
        lines.append("• 후보 없음")
        return "\n".join(lines)
    for i, c in enumerate(candidates, start=1):
        lines.append(_card(i, c))
        lines.append("")
    return "\n".join(lines).rstrip()
