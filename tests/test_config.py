from turtle.config import load_config, Config

def test_load_config_reads_yaml_and_env(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "account:\n"
        "  total_value: 100000000\n"
        "  risk_pct: 0.01\n"
        "  max_units_per_asset: 4\n"
        "  max_units_correlated: 6\n"
        "  max_units_total: 12\n"
        "filters_stocks:\n"
        "  min_listing_days: 300\n"
        "  min_avg_turnover_20: 10000000000\n"
        "  min_avg_volume_20: 100000\n"
        "  min_price: 1000\n"
        "  min_market_cap: 300000000000\n"
        "  kospi_top_n: 200\n"
        "  kosdaq_top_n: 100\n"
        "  etf_top_n: 100\n"
        "  exclude_preferred: true\n"
        "  exclude_spac: true\n"
        "  exclude_recent_split: true\n"
        "approaching_pct: 0.98\n"
        "assets:\n"
        "  stocks: true\n"
        "  etf: true\n"
        "  crypto: false\n"
        'telegram_chat_id: "123"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok-abc")
    cfg = load_config(str(cfg_file))
    assert isinstance(cfg, Config)
    assert cfg.account.total_value == 100000000
    assert cfg.account.risk_pct == 0.01
    assert cfg.filters_stocks.min_listing_days == 300
    assert cfg.approaching_pct == 0.98
    assert cfg.assets["crypto"] is False
    assert cfg.telegram_chat_id == "123"
    assert cfg.telegram_bot_token == "tok-abc"

def test_load_config_reads_database_url(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "account:\n"
        "  total_value: 100000000\n"
        "  risk_pct: 0.01\n"
        "  max_units_per_asset: 4\n"
        "  max_units_correlated: 6\n"
        "  max_units_total: 12\n"
        "filters_stocks:\n"
        "  min_listing_days: 300\n"
        "  min_avg_turnover_20: 10000000000\n"
        "  min_avg_volume_20: 100000\n"
        "  min_price: 1000\n"
        "  min_market_cap: 300000000000\n"
        "  kospi_top_n: 200\n"
        "  kosdaq_top_n: 100\n"
        "  etf_top_n: 100\n"
        "  exclude_preferred: true\n"
        "  exclude_spac: true\n"
        "  exclude_recent_split: true\n"
        "approaching_pct: 0.98\n"
        "assets:\n"
        "  stocks: true\n"
        "  etf: true\n"
        "  crypto: false\n"
        'telegram_chat_id: "123"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok-abc")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@localhost:5432/turtle")
    cfg = load_config(str(cfg_file))
    assert cfg.database_url == "postgresql://user:pw@localhost:5432/turtle"

def test_load_config_reads_crypto_filters(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "account:\n"
        "  total_value: 100000000\n"
        "  risk_pct: 0.01\n"
        "  max_units_per_asset: 4\n"
        "  max_units_correlated: 6\n"
        "  max_units_total: 12\n"
        "filters_stocks:\n"
        "  min_listing_days: 300\n"
        "  min_avg_turnover_20: 10000000000\n"
        "  min_avg_volume_20: 100000\n"
        "  min_price: 1000\n"
        "  min_market_cap: 300000000000\n"
        "  kospi_top_n: 200\n"
        "  kosdaq_top_n: 100\n"
        "  etf_top_n: 100\n"
        "  exclude_preferred: true\n"
        "  exclude_spac: true\n"
        "  exclude_recent_split: true\n"
        "filters_crypto:\n"
        "  tickers: [\"KRW-BTC\", \"KRW-ETH\"]\n"
        "  min_unit: 0.0001\n"
        "approaching_pct: 0.98\n"
        "assets:\n"
        "  stocks: true\n"
        "  etf: true\n"
        "  crypto: true\n"
        'telegram_chat_id: "123"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok-abc")
    cfg = load_config(str(cfg_file))
    assert cfg.filters_crypto.tickers == ["KRW-BTC", "KRW-ETH"]
    assert cfg.filters_crypto.min_unit == 0.0001


def test_load_config_defaults_crypto_filters_when_absent(tmp_path, monkeypatch):
    # filters_crypto 키가 없는 기존 yaml(다른 테스트들과 동일 포맷)도 깨지면 안 된다.
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "account:\n"
        "  total_value: 100000000\n"
        "  risk_pct: 0.01\n"
        "  max_units_per_asset: 4\n"
        "  max_units_correlated: 6\n"
        "  max_units_total: 12\n"
        "filters_stocks:\n"
        "  min_listing_days: 300\n"
        "  min_avg_turnover_20: 10000000000\n"
        "  min_avg_volume_20: 100000\n"
        "  min_price: 1000\n"
        "  min_market_cap: 300000000000\n"
        "  kospi_top_n: 200\n"
        "  kosdaq_top_n: 100\n"
        "  etf_top_n: 100\n"
        "  exclude_preferred: true\n"
        "  exclude_spac: true\n"
        "  exclude_recent_split: true\n"
        "approaching_pct: 0.98\n"
        "assets:\n"
        "  stocks: true\n"
        "  etf: true\n"
        "  crypto: false\n"
        'telegram_chat_id: "123"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok-abc")
    cfg = load_config(str(cfg_file))
    assert cfg.filters_crypto.tickers == []
    assert cfg.filters_crypto.min_unit == 1.0
