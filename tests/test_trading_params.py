import math

from turtle.config import AccountConfig
from turtle.trading_params import compute_trading_params


def _acct():
    return AccountConfig(
        total_value=100_000_000,
        risk_pct=0.01,
        max_units_per_asset=4,
        max_units_correlated=6,
        max_units_total=12,
    )


def test_unit_size_is_floored():
    # risk budget = 1,000,000 ; N=1000 -> 1000주 (floor)
    p = compute_trading_params(entry_trigger=50_000, n=1000, account=_acct())
    assert p.unit_size == 1000
    assert p.tradable is True


def test_stop_and_pyramids():
    p = compute_trading_params(entry_trigger=50_000, n=1000, account=_acct())
    assert p.entry_price_assumed == 50_000
    assert p.stop_loss_price == 50_000 - 2 * 1000        # 48000
    assert p.pyramid_1_price == 50_000 + 0.5 * 1000      # 50500
    assert p.pyramid_2_price == 50_000 + 1.0 * 1000      # 51000
    assert p.pyramid_3_price == 50_000 + 1.5 * 1000      # 51500
    assert p.unit_notional == 1000 * 50_000
    assert p.max_loss_per_unit == 1000 * 2 * 1000


def test_unit_size_below_one_is_not_tradable():
    # N 매우 큼 -> floor(1_000_000 / 2_000_000) = 0
    p = compute_trading_params(entry_trigger=50_000, n=2_000_000, account=_acct())
    assert p.unit_size == 0
    assert p.tradable is False
    assert "매매 불가" in p.note


def test_floor_not_round():
    # risk budget 1,000,000 ; N=3 -> 333333.33 -> floor 333333
    p = compute_trading_params(entry_trigger=10, n=3, account=_acct())
    assert p.unit_size == math.floor(1_000_000 / 3)


def test_floor_vs_round_discriminator():
    # Discriminates floor from round: risk_budget=1_000_000; N=1500
    # -> 1_000_000 / 1500 = 666.666...
    # floor(666.666) = 666, round(666.666) = 667
    # This test FAILS if someone swaps math.floor() for round()
    risk_budget = 1_000_000
    n = 1500
    p = compute_trading_params(entry_trigger=10_000, n=n, account=_acct())
    assert p.unit_size == math.floor(risk_budget / n), \
        f"unit_size should be {math.floor(risk_budget / n)}, got {p.unit_size}"
    assert p.unit_size != round(risk_budget / n), \
        f"unit_size must NOT be round(risk_budget/n)={round(risk_budget / n)}; got {p.unit_size}"
    # Explicitly verify the values we're testing with
    assert p.unit_size == 666, f"Expected 666, got {p.unit_size}"
    assert round(risk_budget / n) == 667, "round(1_000_000/1500) should be 667"
