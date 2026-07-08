from dataclasses import dataclass
from html import escape as _esc
from turtle.signals import APPROACHING, BREAKOUT_CLOSE, BREAKOUT_TODAY

import requests


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
    adx: float


def _fmt_won(v: float) -> str:
    return f"{v:,.0f}"


def _fmt_qty(v: float, market: str) -> str:
    if market == "CRYPTO":
        s = f"{v:.8f}".rstrip("0").rstrip(".")
        return s if s else "0"
    return f"{v:,.0f}"


def _fmt_adx(v: float) -> str:
    return "-" if v != v else f"{v:.1f}"


_STATUS_LABEL = {BREAKOUT_TODAY: "당일돌파", BREAKOUT_CLOSE: "종가돌파"}


def _breakout_card(r) -> str:
    header = (
        f"🔹 <b>{_esc(r.name)}</b> <code>{_esc(r.ticker)}</code> · "
        f"{_STATUS_LABEL.get(r.status, _esc(r.status))}"
    )
    unit_label = "개" if r.market == "CRYPTO" else "주"
    body = (
        f"   종가 {_fmt_won(r.close)} → 트리거 {_fmt_won(r.entry_trigger)} "
        f"(N {_fmt_won(r.n)} · ADX {_fmt_adx(r.adx)})\n"
        f"   손절 {_fmt_won(r.stop_loss_price)} · "
        f"1유닛 {_fmt_qty(r.unit_size, r.market)}{unit_label} ({_fmt_won(r.unit_notional)}원)"
    )
    card = f"{header}\n{body}"
    if not r.tradable:
        card += f"\n   ⚠️ <i>{_esc(r.note)}</i>"
    return card


def _approaching_card(r) -> str:
    return (
        f"🔸 <b>{_esc(r.name)}</b> <code>{_esc(r.ticker)}</code>\n"
        f"   종가 {_fmt_won(r.close)} → 트리거 {_fmt_won(r.entry_trigger)} · "
        f"이격 {r.gap_pct:.2f}% · ADX {_fmt_adx(r.adx)}"
    )


def format_report(target: str, results: list, universe_counts: dict) -> str:
    breakouts = [r for r in results if r.status in (BREAKOUT_TODAY, BREAKOUT_CLOSE)]
    approaching = [r for r in results if r.status == APPROACHING]

    lines = [f"📊 <b>터틀 스크리닝 리포트</b> — {_esc(target)}", ""]
    lines.append(
        f"유니버스: 주식 {universe_counts.get('stocks', 0)}개 / "
        f"ETF {universe_counts.get('etf', 0)}개 / "
        f"코인 {universe_counts.get('crypto', 0)}개"
    )
    lines.append(f"매수 신호: {len(breakouts)}종목 / 관찰: {len(approaching)}종목")
    lines.append("")

    lines.append("🔥 <b>매수 신호 종목</b>")
    if breakouts:
        for r in breakouts:
            lines.append(_breakout_card(r))
            lines.append("")
    else:
        lines.append("• 없음")
        lines.append("")

    lines.append("👀 <b>관찰 종목</b> (2% 이내 근접)")
    if approaching:
        for r in approaching:
            lines.append(_approaching_card(r))
    else:
        lines.append("• 없음")

    return "\n".join(lines)


def format_stoploss_report(target: str, results: list) -> str:
    lines = [f"⛔ <b>보유종목 손절가 체크</b> — {_esc(target)}", ""]
    if not results:
        lines.append("보유 종목 없음")
        return "\n".join(lines)

    for r in results:
        flags = []
        if r.breach_2n:
            flags.append("2N 이탈")
        if r.breach_10d:
            flags.append("10일저가 이탈")
        card = (
            f"🔹 <b>{_esc(r.name)}</b> <code>{_esc(r.ticker)}</code>\n"
            f"   진입가 {_fmt_won(r.entry_price)} · 종가 {_fmt_won(r.close)} · 2N손절 {_fmt_won(r.stop_2n)} · "
            f"10일저가 {_fmt_won(r.stop_10d)}"
        )
        if flags:
            card += f"\n   ⚠️ <b>{' / '.join(flags)}</b>"
        lines.append(card)
        lines.append("")
    return "\n".join(lines).rstrip()


def send_telegram(text: str, bot_token: str, chat_id: str) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    # 텔레그램 4096자 제한 → 분할 전송
    chunks = [text[i : i + 3500] for i in range(0, len(text), 3500)] or [""]
    for chunk in chunks:
        resp = requests.post(
            url,
            data={"chat_id": chat_id, "text": chunk, "parse_mode": "HTML"},
            timeout=15,
        )
        resp.raise_for_status()
