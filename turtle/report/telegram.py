from dataclasses import dataclass
from html import escape as _esc

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
    adx: float


def _fmt_won(v: float) -> str:
    return f"{v:,.0f}"


def _fmt_adx(v: float) -> str:
    return "-" if v != v else f"{v:.1f}"


def _trunc(s: str, w: int) -> str:
    return s if len(s) <= w else s[: w - 1] + "…"


_STATUS_LABEL = {BREAKOUT_TODAY: "당일", BREAKOUT_CLOSE: "종가"}

_NAME_W, _TICKER_W, _NUM_W, _ADX_W, _AMT_W = 8, 7, 9, 5, 11


def _breakout_table(results: list) -> str:
    header = (
        f"{'종목':<{_NAME_W}}{'티커':<{_TICKER_W}}{'구분':<5}"
        f"{'종가':>{_NUM_W}}{'트리거':>{_NUM_W}}{'N':>{_NUM_W}}"
        f"{'ADX':>{_ADX_W}}{'손절':>{_NUM_W}}{'수량':>{_NUM_W}}{'금액':>{_AMT_W}}"
    )
    rows = [header, "-" * len(header)]
    for r in results:
        rows.append(
            f"{_trunc(r.name, _NAME_W):<{_NAME_W}}{r.ticker:<{_TICKER_W}}"
            f"{_STATUS_LABEL.get(r.status, r.status):<5}"
            f"{_fmt_won(r.close):>{_NUM_W}}{_fmt_won(r.entry_trigger):>{_NUM_W}}"
            f"{_fmt_won(r.n):>{_NUM_W}}{_fmt_adx(r.adx):>{_ADX_W}}"
            f"{_fmt_won(r.stop_loss_price):>{_NUM_W}}{_fmt_won(r.unit_size):>{_NUM_W}}"
            f"{_fmt_won(r.unit_notional):>{_AMT_W}}"
        )
    return "<pre>" + _esc("\n".join(rows)) + "</pre>"


def _approaching_table(results: list) -> str:
    header = (
        f"{'종목':<{_NAME_W}}{'티커':<{_TICKER_W}}"
        f"{'종가':>{_NUM_W}}{'트리거':>{_NUM_W}}{'이격%':>7}{'ADX':>{_ADX_W}}"
    )
    rows = [header, "-" * len(header)]
    for r in results:
        rows.append(
            f"{_trunc(r.name, _NAME_W):<{_NAME_W}}{r.ticker:<{_TICKER_W}}"
            f"{_fmt_won(r.close):>{_NUM_W}}{_fmt_won(r.entry_trigger):>{_NUM_W}}"
            f"{r.gap_pct:>6.2f}%{_fmt_adx(r.adx):>{_ADX_W}}"
        )
    return "<pre>" + _esc("\n".join(rows)) + "</pre>"


def format_report(target: str, results: list, universe_counts: dict) -> str:
    breakouts = [r for r in results if r.status in (BREAKOUT_TODAY, BREAKOUT_CLOSE)]
    approaching = [r for r in results if r.status == APPROACHING]

    lines = [f"📊 <b>터틀 스크리닝 리포트</b> — {_esc(target)}", ""]
    lines.append(
        f"유니버스: 주식 {universe_counts.get('stocks', 0)}개 / "
        f"ETF {universe_counts.get('etf', 0)}개"
    )
    lines.append(f"매수 신호: {len(breakouts)}종목 / 관찰: {len(approaching)}종목")
    lines.append("")

    lines.append("🔥 <b>매수 신호 종목</b>")
    if breakouts:
        lines.append(_breakout_table(breakouts))
        for r in breakouts:
            if not r.tradable:
                lines.append(f"⚠️ <b>{_esc(r.name)}</b>: <i>{_esc(r.note)}</i>")
    else:
        lines.append("• 없음")
    lines.append("")

    lines.append("👀 <b>관찰 종목</b> (2% 이내 근접)")
    if approaching:
        lines.append(_approaching_table(approaching))
    else:
        lines.append("• 없음")

    return "\n".join(lines)


def format_stoploss_report(target: str, results: list) -> str:
    lines = [f"⛔ <b>보유종목 손절가 체크</b> — {_esc(target)}", ""]
    if not results:
        lines.append("보유 종목 없음")
        return "\n".join(lines)

    name_w, ticker_w, num_w, flag_w = 8, 7, 9, 10
    header = (
        f"{'종목':<{name_w}}{'티커':<{ticker_w}}"
        f"{'종가':>{num_w}}{'2N손절':>{num_w}}{'10일저가':>{num_w}}{'상태':>{flag_w}}"
    )
    rows = [header, "-" * len(header)]
    breached = []
    for r in results:
        flags = []
        if r.breach_2n:
            flags.append("2N")
        if r.breach_10d:
            flags.append("10D")
        flag_str = ",".join(flags) if flags else "-"
        rows.append(
            f"{_trunc(r.name, name_w):<{name_w}}{r.ticker:<{ticker_w}}"
            f"{_fmt_won(r.close):>{num_w}}{_fmt_won(r.stop_2n):>{num_w}}"
            f"{_fmt_won(r.stop_10d):>{num_w}}{flag_str:>{flag_w}}"
        )
        if flags:
            breached.append(r.name)
    lines.append("<pre>" + _esc("\n".join(rows)) + "</pre>")
    if breached:
        lines.append(f"⚠️ 이탈: {_esc(', '.join(breached))}")
    return "\n".join(lines)


def send_telegram(text: str, bot_token: str, chat_id: str) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    # 텔레그램 4096자 제한 → 분할 전송
    chunks = [text[i:i + 3500] for i in range(0, len(text), 3500)] or [""]
    for chunk in chunks:
        resp = requests.post(
            url,
            data={"chat_id": chat_id, "text": chunk, "parse_mode": "HTML"},
            timeout=15,
        )
        resp.raise_for_status()
