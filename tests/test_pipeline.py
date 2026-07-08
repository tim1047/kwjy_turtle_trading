from datetime import date
from unittest.mock import patch

import numpy as np
import pandas as pd

from turtle.config import AccountConfig, StockFilterConfig, CryptoFilterConfig, Config
from turtle.pipeline import run, run_stoploss_check, screen_ticker
from turtle.positions.store import Position
from turtle.signals import BREAKOUT_TODAY, NEUTRAL


def _cfg():
    return Config(
        account=AccountConfig(100_000_000, 0.01, 4, 6, 12),
        filters_stocks=StockFilterConfig(300, 1e10, 1e5, 1000, 3e11, 200, 100, 100,
                                         True, True, True),
        filters_crypto=CryptoFilterConfig(tickers=["KRW-BTC"], min_unit=0.0001),
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


def _crypto_stop_check_df() -> pd.DataFrame:
    lows = [x * 10000 for x in [9500, 9400, 9300, 9200, 9100, 9050, 9000, 9600, 9700, 9800, 9900]]
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
    fetchers = {"STOCK": _FakeStopFetcher(_stop_check_df()), "CRYPTO": _FakeStopFetcher(_stop_check_df())}
    position = Position(
        ticker="005930", name="삼성전자", market="STOCK",
        entry_price=10000.0, n=500.0, entry_date="2026-06-01",
    )
    with patch("turtle.pipeline.get_open_positions", return_value=[position]), \
         patch("turtle.pipeline.get_business_days", return_value=[date(2026, 7, 7)]):
        text = run_stoploss_check(None, cfg, fetchers, send=False)

    assert "삼성전자" in text
    assert "9,000" in text


def test_run_stoploss_check_survives_db_failure():
    """get_open_positions()가 DB 오류로 예외를 던져도 run_stoploss_check는
    예외를 전파하지 않고 '보유 종목 없음' 리포트를 반환해야 한다.

    이 함수는 main.py에서 매수 신호 스캔(run())보다 먼저 호출되므로,
    여기서 예외가 전파되면 DB 문제 하나로 전체 스캔이 죽는다.
    """
    cfg = _cfg()
    fetchers = {"STOCK": _FakeStopFetcher(_stop_check_df())}
    with patch("turtle.pipeline.get_open_positions", side_effect=Exception("DB down")), \
         patch("turtle.pipeline.get_business_days", return_value=[date(2026, 7, 7)]):
        text = run_stoploss_check(None, cfg, fetchers, send=False)

    assert "보유" in text


def test_run_stoploss_check_skips_position_with_unrecognized_market():
    """p.market이 STOCK/ETF/CRYPTO 중 하나가 아니면(예: UNKNOWN),
    KeyError가 나도 배치 크래시 없이 그 포지션은 스킵되고 다른 정상 포지션은 처리된다.
    """
    cfg = _cfg()
    stock_fetcher = _FakeStopFetcher(_stop_check_df())
    fetchers = {"STOCK": stock_fetcher}
    good_position = Position(
        ticker="005930", name="삼성전자", market="STOCK",
        entry_price=10000.0, n=500.0, entry_date="2026-06-01",
    )
    bad_position = Position(
        ticker="999999", name="알수없는종목", market="UNKNOWN",
        entry_price=1000.0, n=100.0, entry_date="2026-06-01",
    )
    with patch("turtle.pipeline.get_open_positions", return_value=[good_position, bad_position]), \
         patch("turtle.pipeline.get_business_days", return_value=[date(2026, 7, 7)]):
        text = run_stoploss_check(None, cfg, fetchers, send=False)

    # UNKNOWN market인 포지션은 조용히 스킵되고(크래시 없음), 나머지 정상 포지션은 그대로 리포트된다.
    assert "삼성전자" in text
    assert "알수없는종목" not in text


def test_run_stoploss_check_routes_crypto_position_to_crypto_fetcher():
    cfg = _cfg()
    stock_fetcher = _FakeStopFetcher(_stop_check_df())          # 마지막 종가 9,900
    crypto_fetcher = _FakeStopFetcher(_crypto_stop_check_df())  # 마지막 종가 99,000,000
    fetchers = {"STOCK": stock_fetcher, "CRYPTO": crypto_fetcher}
    position = Position(
        ticker="KRW-BTC", name="KRW-BTC", market="CRYPTO",
        entry_price=100_000_000.0, n=2_000_000.0, entry_date="2026-06-01",
    )
    with patch("turtle.pipeline.get_open_positions", return_value=[position]), \
         patch("turtle.pipeline.get_business_days", return_value=[date(2026, 7, 7)]):
        text = run_stoploss_check(None, cfg, fetchers, send=False)

    assert "KRW-BTC" in text
    # crypto_fetcher 고유값(99,000,000)이 나와야 실제로 fetchers["CRYPTO"]가 쓰였다는 증거가 된다.
    # stock_fetcher를 잘못 썼다면 9,900이 나왔을 것이므로 그 값의 부재도 함께 확인한다.
    assert "99,000,000" in text
    assert "9,900" not in text


def test_run_includes_crypto_when_enabled(monkeypatch):
    cfg = Config(
        account=AccountConfig(100_000_000, 0.01, 4, 6, 12),
        filters_stocks=StockFilterConfig(300, 1e10, 1e5, 1000, 3e11, 200, 100, 100,
                                         True, True, True),
        filters_crypto=CryptoFilterConfig(tickers=["KRW-BTC"], min_unit=0.0001),
        approaching_pct=0.98,
        assets={"stocks": False, "etf": False, "crypto": True},
        telegram_chat_id="1",
        telegram_bot_token="t",
        database_url="postgresql://fake",
    )
    crypto_fetcher = _FakeStopFetcher(_breakout_df())
    fetchers = {"CRYPTO": crypto_fetcher}

    from turtle import pipeline as pipeline_mod
    monkeypatch.setattr(pipeline_mod, "get_business_days", lambda *a, **k: [date(2026, 7, 7)])

    text = run(date(2026, 7, 7), cfg, fetchers, send=False)
    assert "KRW-BTC" in text


def test_screen_ticker_crypto_uses_fractional_min_unit():
    res = screen_ticker("KRW-BTC", "KRW-BTC", "CRYPTO", _breakout_df(), _cfg())
    assert res.market == "CRYPTO"
    assert res.unit_size >= 0
    # 주식 기본값(min_unit=1.0)이었다면 unit_size는 항상 정수(math.floor 결과)다.
    # 이 assertion은 market=="CRYPTO" 라우팅이 실제로 cfg.filters_crypto.min_unit(0.0001)을
    # 적용했는지 구분한다 -- 라우팅이 빠지면(min_unit=1.0으로 폴백) unit_size가 정수가 되어 실패한다.
    assert abs(res.unit_size - round(res.unit_size)) > 1e-6, (
        f"unit_size={res.unit_size} is integer-valued; crypto min_unit routing may not be applied"
    )


class _RecordingFetcher:
    def __init__(self, df):
        self._df = df
        self.calls = []

    def get_ohlcv(self, ticker, start, end):
        self.calls.append((ticker, start, end))
        return self._df


def test_run_stoploss_check_crypto_uses_today_not_resolved_target():
    cfg = _cfg()
    stock_fetcher = _RecordingFetcher(_stop_check_df())
    crypto_fetcher = _RecordingFetcher(_crypto_stop_check_df())
    fetchers = {"STOCK": stock_fetcher, "CRYPTO": crypto_fetcher}
    stock_position = Position(
        ticker="005930", name="삼성전자", market="STOCK",
        entry_price=10000.0, n=500.0, entry_date="2026-06-01",
    )
    crypto_position = Position(
        ticker="KRW-BTC", name="KRW-BTC", market="CRYPTO",
        entry_price=100_000_000.0, n=2_000_000.0, entry_date="2026-06-01",
    )
    with patch("turtle.pipeline.get_open_positions", return_value=[stock_position, crypto_position]), \
         patch("turtle.pipeline.get_business_days", return_value=[date(2026, 7, 7)]):
        run_stoploss_check(None, cfg, fetchers, send=False)

    assert len(stock_fetcher.calls) == 1
    assert len(crypto_fetcher.calls) == 1
    _, _, stock_end = stock_fetcher.calls[0]
    _, _, crypto_end = crypto_fetcher.calls[0]

    # STOCK 경로는 get_business_days가 patch된 2026-07-07 기준으로 resolve된다.
    assert stock_end == "20260707"
    # CRYPTO 경로는 get_business_days patch와 무관하게 테스트 실행 시점의 실제 오늘 날짜를 써야 한다.
    assert crypto_end == date.today().strftime("%Y%m%d")
