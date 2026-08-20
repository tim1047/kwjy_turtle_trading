import pandas as pd
import pytest

import swing.momentum_screener as ms
from swing.momentum_params import MomentumScreenerParams
from swing.momentum_screener import (
    compute_screener_features,
    has_fresh_signal,
    latest_accepted_signal,
    market_momentum,
    screen,
    stop_price,
)


def _uptrend_df(n=150, growth=0.001, price0=10000.0, volume=100_000.0):
    """MA5>MA20>MA60>MA120이 안정적으로 성립하는 완만한 상승 시계열 (실측 확인됨)."""
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    close = [price0 * (1 + growth) ** i for i in range(n)]
    rows = []
    for c in close:
        o = c / (1 + growth)  # 전일 종가 근사
        rows.append((o, c * 1.005, o * 0.995, c, volume))
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"], index=idx)


def _set_bar(df, i, *, open_, high, low, close, volume):
    df = df.copy()
    df.iloc[i] = [open_, high, low, close, volume]
    return df


# ---------------------------------------------------------------------------
# spike 판정 (§2.1)
# ---------------------------------------------------------------------------

def _spike_frame():
    """직전 20봉 평온 + 마지막 봉이 급등(거래량 4배·+9%·종가위치 0.9)."""
    idx = pd.date_range("2024-01-01", periods=21, freq="B")
    rows = [(10000, 10100, 9900, 10000, 100_000)] * 20
    rows.append((10000, 11000, 10000, 10900, 400_000))  # vol 4x, +9%, close_pos 0.9
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"], index=idx).astype(float)


def test_spike_detected_when_all_conditions_met():
    p = MomentumScreenerParams()
    f = compute_screener_features(_spike_frame(), p)
    assert bool(f["spike"].iloc[-1]) is True


def test_spike_false_when_volume_below_threshold():
    df = _spike_frame()
    df = _set_bar(df, -1, open_=10000, high=11000, low=10000, close=10900, volume=150_000)  # 1.5x
    p = MomentumScreenerParams()
    f = compute_screener_features(df, p)
    assert bool(f["spike"].iloc[-1]) is False


def test_spike_false_when_change_below_threshold():
    df = _spike_frame()
    df = _set_bar(df, -1, open_=10000, high=10300, low=10000, close=10200, volume=400_000)  # +2%
    p = MomentumScreenerParams()
    f = compute_screener_features(df, p)
    assert bool(f["spike"].iloc[-1]) is False


def test_spike_false_when_long_upper_wick():
    df = _spike_frame()
    # 고가 12000까지 갔다가 10900으로 밀림 -> close_pos = (10900-10000)/(12000-10000)=0.45
    df = _set_bar(df, -1, open_=10000, high=12000, low=10000, close=10900, volume=400_000)
    p = MomentumScreenerParams()
    f = compute_screener_features(df, p)
    assert bool(f["spike"].iloc[-1]) is False


def test_zero_range_bar_does_not_crash_and_is_not_spike():
    """상한가 점상 등 high==low인 봉 (§2.1 body_range=0 -> close_pos NaN)."""
    df = _spike_frame()
    df = _set_bar(df, -1, open_=10000, high=10000, low=10000, close=10000, volume=400_000)
    p = MomentumScreenerParams()
    f = compute_screener_features(df, p)  # 예외 없이 완주해야 함
    assert bool(f["spike"].iloc[-1]) is False


# ---------------------------------------------------------------------------
# 정배열 (§2.3) — 엄격 비교
# ---------------------------------------------------------------------------

def test_aligned_true_in_steady_uptrend():
    p = MomentumScreenerParams()
    f = compute_screener_features(_uptrend_df(), p)
    assert bool(f["aligned"].iloc[-1]) is True


def test_aligned_false_when_ma60_equals_ma120():
    """MA60 == MA120이면 엄격 비교(>)라 False여야 한다."""
    df = _uptrend_df(n=150, growth=0.0)  # 완전 평탄 -> 모든 MA가 동일
    p = MomentumScreenerParams()
    f = compute_screener_features(df, p)
    assert bool(f["aligned"].iloc[-1]) is False


def test_aligned_false_in_downtrend():
    p = MomentumScreenerParams()
    f = compute_screener_features(_uptrend_df(growth=-0.001), p)
    assert bool(f["aligned"].iloc[-1]) is False


# ---------------------------------------------------------------------------
# 거래대금 상한/하한 (§3.1)
# ---------------------------------------------------------------------------

def test_turnover_max_none_disables_upper_bound():
    df = _uptrend_df(n=150, price0=100_000, volume=1_000_000)  # 거래대금 매우 큼(>80억 상한)
    prev_close = df.iloc[-2]["close"]
    new_close = prev_close * 1.09
    df = _set_bar(
        df, -1,
        open_=prev_close, high=new_close * 1.001, low=prev_close,
        close=new_close, volume=6_000_000,  # vol_ratio ~4.8x
    )

    p_capped = MomentumScreenerParams()
    f_capped = compute_screener_features(df, p_capped)
    assert bool(f_capped["watch"].iloc[-1]) is False  # 상한 초과로 탈락

    p_uncapped = MomentumScreenerParams(turnover_max=None)
    f_uncapped = compute_screener_features(df, p_uncapped)
    assert bool(f_uncapped["watch"].iloc[-1]) is True


# ---------------------------------------------------------------------------
# 거래정지 봉 (§1)
# ---------------------------------------------------------------------------

def test_halted_bar_not_spike_and_not_watch():
    df = _spike_frame()
    df = _set_bar(df, -1, open_=0, high=0, low=0, close=10000, volume=0)
    p = MomentumScreenerParams()
    f = compute_screener_features(df, p)
    assert bool(f["halted"].iloc[-1]) is True
    assert bool(f["spike"].iloc[-1]) is False
    assert bool(f["watch"].iloc[-1]) is False


# ---------------------------------------------------------------------------
# screen() — 신규 편입 판정, min_bars
# ---------------------------------------------------------------------------

def test_screen_false_when_history_too_short():
    p = MomentumScreenerParams(min_bars=180)
    df = _uptrend_df(n=50)
    assert screen(df, p) is False


def test_screen_true_only_on_transition_day(monkeypatch):
    """watch가 이미 True로 유지 중이면(연속) screen()은 False, 전환일에만 True."""
    p = MomentumScreenerParams(min_bars=1)
    idx = pd.date_range("2024-01-01", periods=6, freq="B")
    df = pd.DataFrame(
        {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0}, index=idx
    )
    watch = pd.Series([False, False, False, True, True, True], index=idx)
    monkeypatch.setattr(
        ms, "compute_screener_features",
        lambda d, pp: pd.DataFrame({"watch": watch.loc[d.index]}, index=d.index),
    )
    assert screen(df.iloc[:4], p) is True  # 3번째->4번째(index 3) 전환일
    assert screen(df.iloc[:5], p) is False  # 계속 True, 전환 아님
    assert screen(df.iloc[:6], p) is False


# ---------------------------------------------------------------------------
# 쿨다운 (§3.2) — compute_screener_features를 모킹해 watch 시퀀스를 직접 제어
# ---------------------------------------------------------------------------

def _dummy_df(n):
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0}, index=idx
    )


def _patch_watch(monkeypatch, true_at: set[int], n: int):
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    watch = pd.Series([i in true_at for i in range(n)], index=idx)
    monkeypatch.setattr(
        ms, "compute_screener_features",
        lambda d, pp: pd.DataFrame({"watch": watch.loc[d.index]}, index=d.index),
    )
    return idx


def test_cooldown_suppresses_second_transition_within_window(monkeypatch):
    """블록A(20~22, 신규@20) -> 블록B(24~25, 신규@24, 20과의 간격 4<쿨다운5 -> 무시)
    -> 블록C(40~41, 신규@40, 마지막 채택(20)과의 간격 20>=5 -> 채택)."""
    n = 45
    true_at = {20, 21, 22, 24, 25, 40, 41}
    idx = _patch_watch(monkeypatch, true_at, n)
    p = MomentumScreenerParams(min_bars=1, cooldown=5)

    assert latest_accepted_signal(_dummy_df(n), p) == idx[40]

    # 마지막 봉이 24(쿨다운으로 무시된 신호)인 경우: fresh 아님
    assert has_fresh_signal(_dummy_df(n).iloc[:25], p) is False
    # 마지막 봉이 20(최초 채택)인 경우: fresh
    assert has_fresh_signal(_dummy_df(n).iloc[:21], p) is True
    # 마지막 봉이 40(쿨다운 충족 후 채택)인 경우: fresh
    assert has_fresh_signal(_dummy_df(n).iloc[:41], p) is True
    # 마지막 봉이 41(연속 True, 전환일 아님)인 경우: fresh 아님
    assert has_fresh_signal(_dummy_df(n).iloc[:42], p) is False


def test_no_signal_returns_none(monkeypatch):
    n = 30
    idx = _patch_watch(monkeypatch, set(), n)
    p = MomentumScreenerParams(min_bars=1)
    assert latest_accepted_signal(_dummy_df(n), p) is None
    assert has_fresh_signal(_dummy_df(n), p) is False


def test_has_fresh_signal_false_when_history_too_short(monkeypatch):
    n = 10
    _patch_watch(monkeypatch, {9}, n)
    p = MomentumScreenerParams(min_bars=180)
    assert has_fresh_signal(_dummy_df(n), p) is False


# ---------------------------------------------------------------------------
# stop_price
# ---------------------------------------------------------------------------

def test_stop_price_applies_fixed_pct():
    p = MomentumScreenerParams(stop_pct=25.0)
    assert stop_price(10000.0, p) == 7500.0


# ---------------------------------------------------------------------------
# market_momentum — 정보성 지표, 실패해도 예외 없이 None
# ---------------------------------------------------------------------------

class _FakeFetcher:
    def __init__(self, closes: dict):
        self.closes = closes

    def get_ohlcv(self, ticker, start, end):
        s = self.closes[ticker]
        idx = pd.date_range(end=end, periods=len(s), freq="B")
        return pd.DataFrame({"close": s}, index=idx)


def test_market_momentum_averages_two_proxies():
    p = MomentumScreenerParams(market_momentum_window=2)
    # 종가 시퀀스: 마지막 값 / (window+1번째 이전 값) - 1
    closes_a = [100, 100, 110]  # 2일 수익률 10%
    closes_b = [100, 100, 120]  # 2일 수익률 20%
    f = _FakeFetcher({"069500": closes_a, "229200": closes_b})
    v = market_momentum(f, "20260819", p)
    assert v == pytest.approx(15.0, abs=0.01)


def test_market_momentum_none_on_fetch_failure():
    class _Boom:
        def get_ohlcv(self, *a, **k):
            raise RuntimeError("네트워크 실패")

    p = MomentumScreenerParams()
    assert market_momentum(_Boom(), "20260819", p) is None


def test_market_momentum_none_when_history_too_short():
    p = MomentumScreenerParams(market_momentum_window=20)
    f = _FakeFetcher({"069500": [100] * 5, "229200": [100] * 5})
    assert market_momentum(f, "20260819", p) is None
