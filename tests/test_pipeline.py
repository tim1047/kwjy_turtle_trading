from datetime import date
from unittest.mock import patch

import numpy as np
import pandas as pd

from turtle.config import AccountConfig, StockFilterConfig, Config
from turtle.pipeline import run_stoploss_check, screen_ticker
from turtle.positions.store import Position
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
    # ADX가 indicators.adx()로부터 채워져야 한다
    assert res.adx == res.adx  # NaN 아님 (70일치 데이터로 충분)
    assert res.adx > 0


def test_screen_ticker_neutral_when_no_breakout():
    res = screen_ticker("000660", "SK하이닉스", "KOSPI", _flat_df(), _cfg())
    assert res.status == NEUTRAL
    assert res.gap_pct >= 0


class _FakeStopFetcher:
    def __init__(self, df: pd.DataFrame):
        self._df = df

    def get_ohlcv(self, ticker, start, end):
        return self._df


def _stop_check_df() -> pd.DataFrame:
    lows = [9500, 9400, 9300, 9200, 9100, 9050, 9000, 9600, 9700, 9800, 9900]
    idx = pd.date_range("2026-06-01", periods=len(lows), freq="D")
    return pd.DataFrame(
        {
            "open": lows, "high": [x + 100 for x in lows],
            "low": lows, "close": lows, "volume": [1000] * len(lows),
        },
        index=idx,
    )


def test_run_stoploss_check_reports_open_positions():
    cfg = _cfg()
    fetcher = _FakeStopFetcher(_stop_check_df())
    position = Position(
        ticker="005930", name="삼성전자", market="STOCK",
        entry_price=10000.0, n=500.0, entry_date="2026-06-01",
    )
    with patch("turtle.pipeline.get_open_positions", return_value=[position]), \
         patch("turtle.pipeline.get_business_days", return_value=[date(2026, 7, 7)]):
        text = run_stoploss_check(None, cfg, fetcher, send=False)

    assert "삼성전자" in text
    assert "9,000" in text


def test_run_stoploss_check_survives_db_failure():
    """get_open_positions()가 DB 오류로 예외를 던져도 run_stoploss_check는
    예외를 전파하지 않고 '보유 종목 없음' 리포트를 반환해야 한다.

    이 함수는 main.py에서 매수 신호 스캔(run())보다 먼저 호출되므로,
    여기서 예외가 전파되면 DB 문제 하나로 전체 스캔이 죽는다.
    """
    cfg = _cfg()
    fetcher = _FakeStopFetcher(_stop_check_df())
    with patch("turtle.pipeline.get_open_positions", side_effect=Exception("DB down")), \
         patch("turtle.pipeline.get_business_days", return_value=[date(2026, 7, 7)]):
        text = run_stoploss_check(None, cfg, fetcher, send=False)

    assert "보유" in text
