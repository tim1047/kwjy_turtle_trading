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
    sma_200: float,
) -> str:
    # 200일 이동평균선 위에 있을 때만 매수 신호(돌파/근접)를 인정한다.
    # 이력 부족(sma_200 = NaN)이면 필터를 걸지 않고 통과시킨다.
    above_sma200 = sma_200 != sma_200 or today_close >= sma_200
    if today_high >= high_55 and above_sma200:
        return BREAKOUT_TODAY
    if today_close >= high_55 and above_sma200:
        return BREAKOUT_CLOSE
    if today_close >= high_55 * approaching_pct and above_sma200:
        return APPROACHING
    if today_low <= low_20:
        return BREAKDOWN
    return NEUTRAL
