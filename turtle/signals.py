BREAKOUT_TODAY = "BREAKOUT_TODAY"
BREAKOUT_CLOSE = "BREAKOUT_CLOSE"
APPROACHING = "APPROACHING"
NEUTRAL = "NEUTRAL"
BREAKDOWN = "BREAKDOWN"


def classify(
    today_high: float,
    today_low: float,
    today_close: float,
    high_55: float,
    low_20: float,
    approaching_pct: float,
) -> str:
    if today_high >= high_55:
        return BREAKOUT_TODAY
    if today_close >= high_55:
        return BREAKOUT_CLOSE
    if today_close >= high_55 * approaching_pct:
        return APPROACHING
    if today_low <= low_20:
        return BREAKDOWN
    return NEUTRAL
