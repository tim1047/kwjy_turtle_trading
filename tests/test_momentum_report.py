from swing.momentum_exit import ExitDecision
from swing.momentum_positions import MomentumPosition
from swing.momentum_report import MomentumCandidate, format_momentum_report


def test_empty_report_shows_no_candidates_or_exits():
    text = format_momentum_report("2026-08-19", [], [], scanned=400, market_momentum_pct=None)
    assert "신규 후보 0종목" in text
    assert "청산 알림 0건" in text
    assert "N/A" in text
    assert "• 없음" in text


def test_candidate_card_shows_key_fields():
    c = MomentumCandidate(
        ticker="005930", name="삼성전자", market="KOSPI",
        close=75000.0, stop_price=56250.0, turnover_med=5_000_000_000,
    )
    text = format_momentum_report("2026-08-19", [c], [], scanned=400, market_momentum_pct=3.2)
    assert "삼성전자" in text
    assert "005930" in text
    assert "75,000원" in text
    assert "56,250원" in text
    assert "-25.0%" in text
    assert "+3.2% (상승)" in text


def test_exit_card_shows_action_label():
    pos = MomentumPosition(
        ticker="005930", name="삼성전자", market="KOSPI",
        entry_price=10000.0, stop_price=7500.0, hold_days=10, entry_date="2026-08-01",
    )
    stop_decision = ExitDecision("STOP", 7500.0, 3, __import__("datetime").date(2026, 8, 5))
    text = format_momentum_report(
        "2026-08-19", [], [(pos, stop_decision)], scanned=400, market_momentum_pct=-1.5
    )
    assert "⛔ 손절" in text
    assert "-1.5% (하락)" in text
    assert "청산 알림 1건" in text


def test_time_exit_label():
    pos = MomentumPosition(
        ticker="005930", name="삼성전자", market="KOSPI",
        entry_price=10000.0, stop_price=7500.0, hold_days=10, entry_date="2026-08-01",
    )
    time_decision = ExitDecision("TIME", 10500.0, 10, __import__("datetime").date(2026, 8, 15))
    text = format_momentum_report(
        "2026-08-19", [], [(pos, time_decision)], scanned=400, market_momentum_pct=1.0
    )
    assert "⏰ 보유기간 만료" in text
    assert "+5.0%" in text  # (10500/10000-1)*100
