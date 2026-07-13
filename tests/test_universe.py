import pandas as pd

from turtle.config import StockFilterConfig
from turtle.universe.filters import StockMetrics, passes_stock_filters


def _cfg():
    return StockFilterConfig(
        min_listing_days=300,
        min_avg_turnover_20=10_000_000_000,
        min_avg_volume_20=100_000,
        min_price=1000,
        min_market_cap=300_000_000_000,
        kospi_top_n=200,
        kosdaq_top_n=100,
        etf_top_n=100,
        exclude_preferred=True,
        exclude_spac=True,
        exclude_recent_split=True,
    )


def _good_metrics(**over):
    base = dict(
        ticker="005930", name="삼성전자", market="KOSPI",
        listing_days=5000, avg_turnover_20=50_000_000_000, avg_volume_20=1_000_000,
        price=70_000, market_cap=400_000_000_000_000,
        is_flagged=False, is_preferred=False, is_spac=False, had_recent_split=False,
    )
    base.update(over)
    return StockMetrics(**base)


def test_good_stock_passes():
    assert passes_stock_filters(_good_metrics(), _cfg()) is True


def test_short_listing_fails():
    assert passes_stock_filters(_good_metrics(listing_days=100), _cfg()) is False


def test_low_turnover_fails():
    assert passes_stock_filters(_good_metrics(avg_turnover_20=1_000_000_000), _cfg()) is False


def test_penny_price_fails():
    assert passes_stock_filters(_good_metrics(price=500), _cfg()) is False


def test_small_cap_fails():
    assert passes_stock_filters(_good_metrics(market_cap=100_000_000_000), _cfg()) is False


def test_flagged_fails():
    assert passes_stock_filters(_good_metrics(is_flagged=True), _cfg()) is False


def test_preferred_excluded_when_enabled():
    assert passes_stock_filters(_good_metrics(is_preferred=True), _cfg()) is False


def test_preferred_allowed_when_option_off():
    cfg = _cfg()
    cfg = StockFilterConfig(**{**cfg.__dict__, "exclude_preferred": False})
    assert passes_stock_filters(_good_metrics(is_preferred=True), cfg) is True


def test_low_volume_fails():
    assert passes_stock_filters(_good_metrics(avg_volume_20=1_000), _cfg()) is False


def test_spac_excluded_when_enabled():
    assert passes_stock_filters(_good_metrics(is_spac=True), _cfg()) is False


def test_spac_allowed_when_option_off():
    cfg = _cfg()
    cfg = StockFilterConfig(**{**cfg.__dict__, "exclude_spac": False})
    assert passes_stock_filters(_good_metrics(is_spac=True), cfg) is True


def test_recent_split_excluded_when_enabled():
    assert passes_stock_filters(_good_metrics(had_recent_split=True), _cfg()) is False


def test_recent_split_allowed_when_option_off():
    cfg = _cfg()
    cfg = StockFilterConfig(**{**cfg.__dict__, "exclude_recent_split": False})
    assert passes_stock_filters(_good_metrics(had_recent_split=True), cfg) is True


def test_boundary_values_pass_at_exact_thresholds():
    cfg = _cfg()
    m = _good_metrics(
        listing_days=cfg.min_listing_days,
        avg_turnover_20=cfg.min_avg_turnover_20,
        avg_volume_20=cfg.min_avg_volume_20,
        price=cfg.min_price,
        market_cap=cfg.min_market_cap,
    )
    assert passes_stock_filters(m, cfg) is True


# --- I/O wiring tests: turtle.universe.krx_stocks ---------------------------
# These monkeypatch the network/pykrx boundary (as tests/test_data.py and
# tests/test_calendar.py already do) so no real HTTP/pykrx calls happen here.


def _ohlcv_df(n: int, close: float = 70_000, volume: float = 1_000_000):
    idx = pd.date_range("2020-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {
            "open": [close] * n,
            "high": [close] * n,
            "low": [close] * n,
            "close": [close] * n,
            "volume": [volume] * n,
        },
        index=idx,
    )


class _FakeFetcher:
    def __init__(self, frames: dict):
        self.frames = frames
        self.calls = []

    def get_ohlcv(self, ticker, start, end):
        self.calls.append((ticker, start, end))
        if ticker not in self.frames:
            raise ValueError(f"no data for {ticker}")
        return self.frames[ticker]


def test_build_stock_universe_filters_and_isolates_ticker_failure(monkeypatch):
    import turtle.universe.krx_stocks as krx_stocks

    cap_df = pd.DataFrame(
        {"시가총액": [400_000_000_000_000.0, 400_000_000_000_000.0, 400_000_000_000_000.0]},
        index=["AAAAAA", "BBBBBB", "CCCCCC"],
    )

    def fake_top_by_cap(market, top_n):
        return cap_df if market == "KOSPI" else cap_df.iloc[0:0]

    monkeypatch.setattr(krx_stocks, "_top_by_cap", fake_top_by_cap)
    monkeypatch.setattr(krx_stocks, "etf_ticker_set", lambda: set())
    monkeypatch.setattr(
        krx_stocks.stock, "get_market_ticker_name", lambda t: f"name-{t}"
    )

    frames = {
        "AAAAAA": _ohlcv_df(400, close=70_000, volume=1_000_000),  # passes
        "BBBBBB": _ohlcv_df(400, close=500, volume=1_000_000),  # fails price filter
        # "CCCCCC" intentionally missing -> fetcher raises -> must be isolated
    }
    fetcher = _FakeFetcher(frames)
    cfg = _cfg()

    result = krx_stocks.build_stock_universe("20260703", cfg, fetcher, "20250601")

    assert result == [("AAAAAA", "KOSPI")]


def test_build_stock_universe_excludes_etf_tickers_mixed_into_cap_ranking(monkeypatch):
    """네이버 KOSPI 시총 순위에는 ETF도 섞여 나온다 (예: 069500 KODEX 200).
    get_market_ticker_name이 ETF 티커를 지원하지 않아 크래시하므로, ETF는
    시총 순위에서 조회조차 하지 않고 사전에 제외해야 한다."""
    import turtle.universe.krx_stocks as krx_stocks

    cap_df = pd.DataFrame(
        {"시가총액": [400_000_000_000_000.0, 400_000_000_000_000.0]},
        index=["069500", "AAAAAA"],
    )

    def fake_top_by_cap(market, top_n):
        return cap_df if market == "KOSPI" else cap_df.iloc[0:0]

    monkeypatch.setattr(krx_stocks, "_top_by_cap", fake_top_by_cap)
    monkeypatch.setattr(krx_stocks, "etf_ticker_set", lambda: {"069500"})
    monkeypatch.setattr(
        krx_stocks.stock, "get_market_ticker_name", lambda t: f"name-{t}"
    )

    fetcher = _FakeFetcher({"AAAAAA": _ohlcv_df(400, close=70_000, volume=1_000_000)})
    cfg = _cfg()

    result = krx_stocks.build_stock_universe("20260703", cfg, fetcher, "20250601")

    assert result == [("AAAAAA", "KOSPI")]
    assert ("069500", "20250601", "20260703") not in fetcher.calls


def test_build_stock_universe_isolates_market_level_failure(monkeypatch):
    import turtle.universe.krx_stocks as krx_stocks

    def fake_top_by_cap(market, top_n):
        if market == "KOSPI":
            raise ConnectionError("naver unreachable")
        return pd.DataFrame({"시가총액": [400_000_000_000_000.0]}, index=["DDDDDD"])

    monkeypatch.setattr(krx_stocks, "_top_by_cap", fake_top_by_cap)
    monkeypatch.setattr(krx_stocks, "etf_ticker_set", lambda: set())
    monkeypatch.setattr(
        krx_stocks.stock, "get_market_ticker_name", lambda t: f"name-{t}"
    )

    fetcher = _FakeFetcher({"DDDDDD": _ohlcv_df(400)})
    cfg = _cfg()

    result = krx_stocks.build_stock_universe("20260703", cfg, fetcher, "20250601")

    assert result == [("DDDDDD", "KOSDAQ")]


# --- I/O wiring tests: turtle.universe.krx_etf ------------------------------


def test_build_etf_universe_applies_liquidity_filters_and_isolates_failures(
    monkeypatch,
):
    import turtle.universe.krx_etf as krx_etf

    monkeypatch.setattr(
        krx_etf, "_etf_ticker_list", lambda top_n: ["069500", "PENNY01", "BROKEN1"]
    )

    frames = {
        "069500": _ohlcv_df(400, close=30_000, volume=1_000_000),  # passes
        "PENNY01": _ohlcv_df(400, close=500, volume=1_000_000),  # fails price filter
        # "BROKEN1" missing -> fetcher raises -> must be isolated
    }
    fetcher = _FakeFetcher(frames)
    cfg = _cfg()

    result = krx_etf.build_etf_universe("20260703", cfg, fetcher, "20250601")

    assert result == ["069500"]


def test_build_etf_universe_ticker_list_failure_returns_empty(monkeypatch):
    import turtle.universe.krx_etf as krx_etf

    def raise_error(top_n):
        raise ConnectionError("naver etf list unreachable")

    monkeypatch.setattr(krx_etf, "_etf_ticker_list", raise_error)

    fetcher = _FakeFetcher({})
    cfg = _cfg()

    result = krx_etf.build_etf_universe("20260703", cfg, fetcher, "20250601")

    assert result == []
