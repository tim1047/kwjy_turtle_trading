from turtle.signals import (
    classify,
    BREAKOUT_TODAY,
    BREAKOUT_CLOSE,
    APPROACHING,
    NEUTRAL,
    BREAKDOWN,
)


def test_breakout_today_when_high_crosses_trigger():
    assert classify(today_high=105, today_low=98, today_close=101,
                    high_55=104, low_20=90, approaching_pct=0.98) == BREAKOUT_TODAY


def test_breakout_close_when_only_close_crosses():
    # 고가는 트리거 미달, 종가가 트리거 이상
    assert classify(today_high=103.5, today_low=98, today_close=104,
                    high_55=104, low_20=90, approaching_pct=0.98) == BREAKOUT_CLOSE


def test_approaching_within_2pct():
    # 종가가 트리거의 98% 이상, 트리거 미만
    assert classify(today_high=103, today_low=98, today_close=102,
                    high_55=104, low_20=90, approaching_pct=0.98) == APPROACHING


def test_breakdown_when_low_breaks_low20():
    assert classify(today_high=95, today_low=89, today_close=91,
                    high_55=120, low_20=90, approaching_pct=0.98) == BREAKDOWN


def test_neutral_when_nothing_matches():
    assert classify(today_high=95, today_low=93, today_close=94,
                    high_55=120, low_20=90, approaching_pct=0.98) == NEUTRAL


def test_breakout_today_takes_priority_over_breakdown():
    assert classify(today_high=130, today_low=89, today_close=125,
                    high_55=120, low_20=90, approaching_pct=0.98) == BREAKOUT_TODAY
