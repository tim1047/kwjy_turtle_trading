from turtle.report.telegram import format_report, ScreenResult
from turtle.signals import BREAKOUT_TODAY, APPROACHING


def _r(**over):
    base = dict(
        ticker="005930", name="삼성전자", market="KOSPI", close=71000,
        entry_trigger=70000, n=1500, stop_loss_price=67000,
        unit_size=666, unit_notional=46620000, status=BREAKOUT_TODAY,
        gap_pct=0.0, tradable=True, note="",
    )
    base.update(over)
    return ScreenResult(**base)


def test_report_lists_breakout_section():
    text = format_report(
        "2026-07-06",
        [_r()],
        {"stocks": 120, "etf": 30},
    )
    assert "2026-07-06" in text
    assert "삼성전자" in text
    assert "매수 신호" in text


def test_report_separates_approaching():
    text = format_report(
        "2026-07-06",
        [_r(status=APPROACHING, name="근접주", gap_pct=1.2)],
        {"stocks": 120, "etf": 30},
    )
    assert "관찰" in text
    assert "근접주" in text


def test_report_handles_empty_signals():
    text = format_report("2026-07-06", [], {"stocks": 0, "etf": 0})
    assert "2026-07-06" in text
