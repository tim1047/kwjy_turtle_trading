"""KRX 시가총액 단면 기반 유니버스 랭킹 테스트 (turtle.universe.krx_stocks)."""

from types import SimpleNamespace

import pandas as pd
import pytest

import turtle.universe.krx_stocks as krx_stocks


def _cross_section(caps: dict[str, float]) -> pd.DataFrame:
    return pd.DataFrame(
        {"종가": [1000.0] * len(caps), "시가총액": list(caps.values())},
        index=pd.Index(list(caps.keys()), name="티커"),
    )


def test_top_by_cap_ranks_krx_cross_section_descending(monkeypatch):
    calls = []

    def fake_fetch(target, market):
        calls.append((target, market))
        return _cross_section({"CCCCCC": 1.0, "AAAAAA": 3.0, "BBBBBB": 2.0})

    monkeypatch.setattr(krx_stocks, "fetch_market_cap", fake_fetch)

    out = krx_stocks._top_by_cap("20260911", "KOSDAQ", 2)

    assert list(out.index) == ["AAAAAA", "BBBBBB"]
    assert list(out["시가총액"]) == [3.0, 2.0]
    assert calls == [("20260911", "KOSDAQ")]


def test_fetch_market_cap_raises_on_empty_cross_section(monkeypatch):
    """KRX 세션 만료·미로그인 시 pykrx는 예외 없이 빈 결과를 준다 — 조용히 넘기지 않는다."""
    monkeypatch.setattr(
        krx_stocks.stock, "get_market_cap_by_ticker", lambda target, market: pd.DataFrame()
    )
    with pytest.raises(RuntimeError):
        krx_stocks.fetch_market_cap("20260911", "KOSPI")


def test_build_stock_universe_passes_target_to_cap_ranking(monkeypatch):
    seen = []

    def fake_top(target, market, top_n):
        seen.append((target, market))
        return pd.DataFrame(columns=["시가총액"])

    monkeypatch.setattr(krx_stocks, "_top_by_cap", fake_top)
    monkeypatch.setattr(krx_stocks, "etf_ticker_set", lambda: set())
    cfg = SimpleNamespace(kospi_top_n=1, kosdaq_top_n=1)

    krx_stocks.build_stock_universe("20260911", cfg, None, "20250601")

    assert seen == [("20260911", "KOSPI"), ("20260911", "KOSDAQ")]
