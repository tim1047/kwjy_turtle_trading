from dataclasses import dataclass

import requests

from turtle.signals import BREAKOUT_TODAY, BREAKOUT_CLOSE, APPROACHING


@dataclass(frozen=True)
class ScreenResult:
    ticker: str
    name: str
    market: str
    close: float
    entry_trigger: float
    n: float
    stop_loss_price: float
    unit_size: float
    unit_notional: float
    status: str
    gap_pct: float
    tradable: bool
    note: str


def _fmt_won(v: float) -> str:
    return f"{v:,.0f}"


def format_report(target: str, results: list, universe_counts: dict) -> str:
    breakouts = [r for r in results if r.status in (BREAKOUT_TODAY, BREAKOUT_CLOSE)]
    approaching = [r for r in results if r.status == APPROACHING]

    lines = [f"📊 터틀 스크리닝 리포트 — {target}", ""]
    lines.append(
        f"유니버스: 주식 {universe_counts.get('stocks', 0)}개 / "
        f"ETF {universe_counts.get('etf', 0)}개"
    )
    lines.append(f"매수 신호: {len(breakouts)}종목 / 관찰: {len(approaching)}종목")
    lines.append("")

    lines.append("🔥 매수 신호 종목")
    if breakouts:
        for r in breakouts:
            flag = "" if r.tradable else f" ⚠️{r.note}"
            lines.append(
                f"• {r.name}({r.ticker}) {r.status}\n"
                f"  종가 {_fmt_won(r.close)} / 트리거 {_fmt_won(r.entry_trigger)} / "
                f"N {_fmt_won(r.n)}\n"
                f"  손절 {_fmt_won(r.stop_loss_price)} / "
                f"1유닛 {_fmt_won(r.unit_size)}주 ({_fmt_won(r.unit_notional)}원){flag}"
            )
    else:
        lines.append("• 없음")
    lines.append("")

    lines.append("👀 관찰 종목 (2% 이내 근접)")
    if approaching:
        for r in approaching:
            lines.append(
                f"• {r.name}({r.ticker}) 종가 {_fmt_won(r.close)} / "
                f"트리거 {_fmt_won(r.entry_trigger)} / 이격 {r.gap_pct:.2f}%"
            )
    else:
        lines.append("• 없음")

    return "\n".join(lines)


def format_stoploss_report(target: str, results: list) -> str:
    lines = [f"⛔ 보유종목 손절가 체크 — {target}", ""]
    if not results:
        lines.append("보유 종목 없음")
        return "\n".join(lines)
    for r in results:
        flags = []
        if r.breach_2n:
            flags.append("2N 이탈")
        if r.breach_10d:
            flags.append("10일저가 이탈")
        flag_str = f" ⚠️ {' / '.join(flags)}" if flags else ""
        lines.append(
            f"• {r.name}({r.ticker}) 종가 {_fmt_won(r.close)}\n"
            f"  2N손절 {_fmt_won(r.stop_2n)} / 10일저가 {_fmt_won(r.stop_10d)}{flag_str}"
        )
    return "\n".join(lines)


def send_telegram(text: str, bot_token: str, chat_id: str) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    # 텔레그램 4096자 제한 → 분할 전송
    chunks = [text[i:i + 3500] for i in range(0, len(text), 3500)] or [""]
    for chunk in chunks:
        resp = requests.post(url, data={"chat_id": chat_id, "text": chunk}, timeout=15)
        resp.raise_for_status()
