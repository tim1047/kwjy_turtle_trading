from datetime import date

from swing.report import SwingCandidate, format_swing_report


def _c(**over):
    base = dict(
        ticker="005930", name="삼성전자", market="KOSPI", close=71_200.0,
        pole_date=date(2026, 8, 5), elapsed=4, retrace_pct=32.1,
        avg_turnover_20=5e10, net_buy=1.24e9,
    )
    base.update(over)
    return SwingCandidate(**base)


def test_report_includes_all_fields():
    text = format_swing_report("2026-08-12", [_c()], scanned=1380)
    assert "2026-08-12" in text
    assert "삼성전자" in text
    assert "005930" in text
    assert "KOSPI" in text
    assert "71,200" in text
    assert "08-05" in text
    assert "경과 4일" in text
    assert "되돌림 32.1%" in text
    assert "+12.4억" in text
    assert "1,380" in text


def test_empty_candidates():
    text = format_swing_report("2026-08-12", [], scanned=1380)
    assert "후보 없음" in text


def test_missing_net_buy_shows_na():
    text = format_swing_report("2026-08-12", [_c(net_buy=None)], scanned=10)
    assert "N/A" in text


def test_negative_net_buy_keeps_sign():
    text = format_swing_report("2026-08-12", [_c(net_buy=-3.5e8)], scanned=10)
    assert "-3.5억" in text


def test_html_is_escaped():
    text = format_swing_report("2026-08-12", [_c(name="A<b>&B")], scanned=1)
    assert "A&lt;b&gt;&amp;B" in text


def test_candidates_are_numbered_in_given_order():
    text = format_swing_report(
        "2026-08-12", [_c(ticker="000001"), _c(ticker="000002")], scanned=2
    )
    assert text.index("000001") < text.index("000002")
    assert "1." in text and "2." in text
