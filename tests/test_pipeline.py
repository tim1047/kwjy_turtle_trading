import numpy as np
import pandas as pd

from turtle.config import AccountConfig, StockFilterConfig, Config
from turtle.pipeline import screen_ticker
from turtle.signals import BREAKOUT_TODAY, NEUTRAL


def _cfg():
    return Config(
        account=AccountConfig(100_000_000, 0.01, 4, 6, 12),
        filters_stocks=StockFilterConfig(300, 1e10, 1e5, 1000, 3e11, 200, 100, 100,
                                         True, True, True),
        approaching_pct=0.98,
        assets={"stocks": True, "etf": True, "crypto": False},
        telegram_chat_id="1",
        telegram_bot_token="t",
        database_url="postgresql://fake",
    )


def _breakout_df():
    n = 70
    idx = pd.date_range("2026-01-01", periods=n, freq="D")
    highs = list(np.linspace(100, 150, n - 1)) + [300]   # 오늘 고가 급등 → 돌파
    lows = [h - 5 for h in highs]
    closes = [h - 1 for h in highs]
    return pd.DataFrame(
        {"open": closes, "high": highs, "low": lows, "close": closes,
         "volume": [1_000_000] * n},
        index=idx,
    )


def _flat_df():
    """오늘 고가/종가가 55일 고점(및 근접 기준)에 못 미치고, 20일 저점도
    깨지 않는 흐름 -> NEUTRAL이어야 한다."""
    n = 70
    idx = pd.date_range("2026-01-01", periods=n, freq="D")
    highs = [100.0] * (n - 1) + [90.0]
    lows = [95.0] * (n - 1) + [96.0]
    closes = [98.0] * (n - 1) + [91.0]
    return pd.DataFrame(
        {"open": closes, "high": highs, "low": lows, "close": closes,
         "volume": [1_000_000] * n},
        index=idx,
    )


def test_screen_ticker_detects_breakout():
    res = screen_ticker("005930", "삼성전자", "KOSPI", _breakout_df(), _cfg())
    assert res.status == BREAKOUT_TODAY
    assert res.entry_trigger > 0
    assert res.n > 0
    assert res.ticker == "005930"
    assert res.name == "삼성전자"
    assert res.market == "KOSPI"
    # 트레이딩 파라미터가 결합되어 있어야 한다
    assert res.stop_loss_price < res.entry_trigger
    assert res.unit_size >= 0


def test_screen_ticker_neutral_when_no_breakout():
    res = screen_ticker("000660", "SK하이닉스", "KOSPI", _flat_df(), _cfg())
    assert res.status == NEUTRAL
    assert res.gap_pct >= 0
