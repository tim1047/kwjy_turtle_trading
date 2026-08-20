import pytest
import yaml

from swing.momentum_params import MomentumScreenerParams, load_momentum_params


def test_defaults_match_spec():
    p = MomentumScreenerParams()
    assert p.spike_vol_x == 3.0
    assert p.spike_chg_min == 0.08
    assert p.spike_close_pos == 0.6
    assert p.turnover_min == 1_000_000_000
    assert p.turnover_max == 8_000_000_000
    assert p.min_bars == 180
    assert p.hold_days == 10
    assert p.stop_pct == 25.0
    assert p.max_positions == 20
    assert p.market_proxy == ("069500", "229200")


def test_required_bars_matches_min_bars():
    p = MomentumScreenerParams(min_bars=250)
    assert p.required_bars == 250


def test_load_from_config_file(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        yaml.dump({"momentum_screener": {"hold_days": 15, "turnover_max": None}})
    )
    p = load_momentum_params(str(cfg))
    assert p.hold_days == 15
    assert p.turnover_max is None
    assert p.spike_vol_x == 3.0  # 나머지는 기본값 유지


def test_load_without_section_uses_defaults(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.dump({"other": {}}))
    p = load_momentum_params(str(cfg))
    assert p == MomentumScreenerParams()


def test_market_proxy_list_converted_to_tuple(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.dump({"momentum_screener": {"market_proxy": ["005930", "000660"]}}))
    p = load_momentum_params(str(cfg))
    assert p.market_proxy == ("005930", "000660")


def test_unknown_key_raises(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.dump({"momentum_screener": {"typo_field": 1}}))
    with pytest.raises(TypeError):
        load_momentum_params(str(cfg))
