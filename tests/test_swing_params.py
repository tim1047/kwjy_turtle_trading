import pytest

from swing.params import SwingParams, load_swing_params


def test_defaults_match_spec():
    p = SwingParams()
    assert p.base_window == 30
    assert p.base_long_window == 60
    assert p.price_contraction == 0.20
    assert p.base_vol_ratio == 0.8
    assert p.body_min == 0.06
    assert p.close_pos == 0.7
    assert p.vol_spike == 2.5
    assert p.spike_ref_window == 20
    assert p.pullback_min == 1
    assert p.pullback_max == 10
    assert p.retrace_max == 0.5
    assert p.pullback_vol_ratio == 0.3
    assert p.dist_vol == 2.0
    assert p.mcap_percentile_cut == 50.0
    assert p.liquidity_min_value == 1_000_000_000
    assert p.min_price == 1000.0
    assert p.notify_empty is True


def test_required_bars_covers_long_window_and_pullback():
    # 조건1 장기창(90봉) + 최대 경과 10봉 + 당일 1봉
    assert SwingParams().required_bars == 101
    assert SwingParams(base_window=20, base_long_window=40, pullback_max=5).required_bars == 66


def test_load_from_yaml_overrides(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("swing:\n  body_min: 0.09\n  pullback_max: 7\n", encoding="utf-8")
    p = load_swing_params(str(cfg))
    assert p.body_min == 0.09
    assert p.pullback_max == 7
    assert p.base_window == 30  # 미지정 항목은 기본값


def test_load_without_swing_section_uses_defaults(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("account:\n  total_value: 1\n", encoding="utf-8")
    assert load_swing_params(str(cfg)) == SwingParams()


def test_unknown_key_raises(tmp_path):
    # 오타 방어: 모르는 키는 조용히 무시하지 않고 즉시 실패해야 한다
    cfg = tmp_path / "config.yaml"
    cfg.write_text("swing:\n  bodymin: 0.09\n", encoding="utf-8")
    with pytest.raises(TypeError):
        load_swing_params(str(cfg))
