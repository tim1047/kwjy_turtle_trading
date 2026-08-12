import pandas as pd
import pytest

from swing.universe import is_excluded_name, top_by_market_cap


def _cap_df(pairs):
    return pd.DataFrame(
        {"종가": [1000] * len(pairs), "시가총액": [c for _, c in pairs]},
        index=pd.Index([t for t, _ in pairs], name="티커"),
    )


def test_preferred_stock_excluded():
    assert is_excluded_name("삼성전자우") is True
    assert is_excluded_name("현대차2우B") is True


def test_spac_and_reit_excluded():
    assert is_excluded_name("교보14호스팩") is True
    assert is_excluded_name("신한알파리츠") is True


def test_normal_name_kept():
    assert is_excluded_name("삼성전자") is False
    assert is_excluded_name("우리금융지주") is False  # '우'로 시작할 뿐 우선주가 아니다


def test_top_by_market_cap_keeps_upper_half_in_order():
    df = _cap_df([("A", 100), ("B", 400), ("C", 200), ("D", 300)])
    assert top_by_market_cap(df, 50) == ["B", "D"]


def test_top_by_market_cap_rounds_up_on_odd_count():
    df = _cap_df([("A", 100), ("B", 300), ("C", 200)])
    assert top_by_market_cap(df, 50) == ["B", "C"]


def test_top_by_market_cap_empty_raises():
    with pytest.raises(ValueError):
        top_by_market_cap(_cap_df([]), 50)
