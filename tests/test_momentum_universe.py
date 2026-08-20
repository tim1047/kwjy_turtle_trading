import pandas as pd

import swing.momentum_universe as mu


def _cap_df(tickers):
    return pd.DataFrame({"시가총액": [1.0] * len(tickers)}, index=pd.Index(tickers))


def test_cross_excludes_etf_and_tags_market(monkeypatch):
    def _fake_top(market, top_n):
        if market == "KOSPI":
            return _cap_df(["005930", "069500"])  # 069500은 ETF
        return _cap_df(["229200", "111111"])  # 229200도 ETF

    monkeypatch.setattr(mu, "_top_by_cap", _fake_top)
    monkeypatch.setattr(mu, "etf_ticker_set", lambda: {"069500", "229200"})

    result = mu.build_momentum_universe(top_n_kospi=2, top_n_kosdaq=2)

    assert result == [("005930", "KOSPI"), ("111111", "KOSDAQ")]


def test_etf_lookup_failure_keeps_all_tickers(monkeypatch):
    monkeypatch.setattr(mu, "_top_by_cap", lambda market, top_n: _cap_df(["005930"]))
    monkeypatch.setattr(
        mu, "etf_ticker_set", lambda: (_ for _ in ()).throw(RuntimeError("실패"))
    )

    result = mu.build_momentum_universe(top_n_kospi=1, top_n_kosdaq=1)

    assert ("005930", "KOSPI") in result
    assert ("005930", "KOSDAQ") in result
