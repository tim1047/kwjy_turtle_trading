from turtle.report.telegram import format_report, format_stoploss_report, ScreenResult
from turtle.signals import BREAKOUT_TODAY, APPROACHING
from turtle.stoploss import StopCheckResult


def _r(**over):
    base = dict(
        ticker="005930", name="삼성전자", market="KOSPI", close=71000,
        entry_trigger=70000, n=1500, stop_loss_price=67000,
        unit_size=666, unit_notional=46620000, status=BREAKOUT_TODAY,
        gap_pct=0.0, tradable=True, note="", adx=30.0,
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


def test_format_stoploss_report_no_positions():
    text = format_stoploss_report("2026-07-07", [])
    assert "보유 종목 없음" in text


def test_format_stoploss_report_flags_breach():
    results = [
        StopCheckResult(
            ticker="005930", name="삼성전자", market="STOCK",
            close=8500.0, stop_2n=9000.0, stop_10d=9000.0,
            breach_2n=True, breach_10d=True,
        ),
        StopCheckResult(
            ticker="069500", name="KODEX 200", market="ETF",
            close=32500.0, stop_2n=31000.0, stop_10d=31500.0,
            breach_2n=False, breach_10d=False,
        ),
    ]
    text = format_stoploss_report("2026-07-07", results)
    assert "삼성전자" in text
    assert "⚠️" in text
    assert text.count("⚠️") == 1
    assert "8,500" in text
    assert "9,000" in text


def test_report_shows_adx_value():
    text = format_report(
        "2026-07-06",
        [_r(adx=32.5)],
        {"stocks": 120, "etf": 30},
    )
    assert "ADX 32.5" in text


def test_report_shows_adx_dash_when_nan():
    text = format_report(
        "2026-07-06",
        [_r(adx=float("nan"))],
        {"stocks": 120, "etf": 30},
    )
    assert "ADX -" in text
    assert "nan" not in text.lower()


def test_report_approaching_shows_adx_value():
    text = format_report(
        "2026-07-06",
        [_r(status=APPROACHING, name="근접주", gap_pct=1.2, adx=28.0)],
        {"stocks": 120, "etf": 30},
    )
    assert "ADX 28.0" in text
