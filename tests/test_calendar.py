from datetime import date

import pandas as pd
import pytest

from turtle.calendar import resolve_target_date, lookback_start


def test_resolve_returns_same_when_business_day():
    bdays = [date(2026, 7, 2), date(2026, 7, 3), date(2026, 7, 6)]
    assert resolve_target_date(date(2026, 7, 3), bdays) == date(2026, 7, 3)


def test_resolve_falls_back_to_prior_business_day():
    # 7/4(토),7/5(일) 휴장 -> 7/4 요청 시 7/3 반환
    bdays = [date(2026, 7, 2), date(2026, 7, 3), date(2026, 7, 6)]
    assert resolve_target_date(date(2026, 7, 4), bdays) == date(2026, 7, 3)


def test_resolve_none_returns_latest():
    bdays = [date(2026, 7, 2), date(2026, 7, 3), date(2026, 7, 6)]
    assert resolve_target_date(None, bdays) == date(2026, 7, 6)


def test_resolve_unsorted_input_still_works():
    # business_days may arrive unsorted; function must sort internally.
    bdays = [date(2026, 7, 6), date(2026, 7, 2), date(2026, 7, 3)]
    assert resolve_target_date(None, bdays) == date(2026, 7, 6)
    assert resolve_target_date(date(2026, 7, 4), bdays) == date(2026, 7, 3)


def test_resolve_raises_when_requested_before_all_business_days():
    bdays = [date(2026, 7, 2), date(2026, 7, 3), date(2026, 7, 6)]
    with pytest.raises(ValueError):
        resolve_target_date(date(2026, 6, 30), bdays)


def test_resolve_raises_on_empty_business_days():
    with pytest.raises(ValueError):
        resolve_target_date(date(2026, 7, 3), [])
    with pytest.raises(ValueError):
        resolve_target_date(None, [])


def test_lookback_start_moves_back():
    # 넉넉히 과거로 이동 (정확한 값보다 '이전인지'만 확인)
    assert lookback_start("20260706", days=320) < "20260706"


def test_lookback_start_default_days_is_320():
    assert lookback_start("20260706") == lookback_start("20260706", days=320)


def test_get_business_days_converts_ohlcv_index_to_date_list(monkeypatch):
    import turtle.calendar as cal

    idx = pd.to_datetime(["2026-06-01", "2026-06-02", "2026-06-03"])
    raw = pd.DataFrame(
        {"시가": [1, 2, 3], "고가": [1, 2, 3], "저가": [1, 2, 3],
         "종가": [1, 2, 3], "거래량": [1, 2, 3]},
        index=idx,
    )
    calls = []

    def fake_get_market_ohlcv(start, end, ticker):
        calls.append((start, end, ticker))
        return raw

    monkeypatch.setattr(cal.stock, "get_market_ohlcv", fake_get_market_ohlcv)

    out = cal.get_business_days("20260601", "20260603")

    assert calls == [("20260601", "20260603", cal._REFERENCE_TICKER)]
    assert out == [date(2026, 6, 1), date(2026, 6, 2), date(2026, 6, 3)]
    assert all(isinstance(d, date) for d in out)
