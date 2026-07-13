import pytest

from turtle.backtest import Trade
from turtle.backtest_report import compute_metrics, format_backtest_report


def _trade(entry_date, exit_date, pnl):
    return Trade(
        entry_date=entry_date, exit_date=exit_date, entry_price=100.0,
        exit_price=100.0 + pnl / 10.0, units=1, size=10.0, pnl=pnl,
        pnl_pct=pnl / 1000.0 * 100, exit_reason="2N",
    )


def test_compute_metrics_all_wins():
    trades = [_trade("2020-01-01", "2020-02-01", 100_000.0), _trade("2020-02-01", "2020-03-01", 50_000.0)]
    metrics = compute_metrics(trades, initial_capital=1_000_000.0, start="20200101", end="20201231")
    assert metrics.total_trades == 2
    assert metrics.win_rate == pytest.approx(100.0)
    assert metrics.profit_factor == float("inf")
    assert metrics.mdd == pytest.approx(0.0)  # 계속 상승만 했으므로 낙폭 없음


def test_compute_metrics_mixed():
    trades = [
        _trade("2020-01-01", "2020-02-01", 200_000.0),   # 1,000,000 -> 1,200,000
        _trade("2020-02-01", "2020-03-01", -300_000.0),  # -> 900,000 (peak 1,200,000 대비 -25%)
        _trade("2020-03-01", "2020-04-01", 100_000.0),   # -> 1,000,000
    ]
    metrics = compute_metrics(trades, initial_capital=1_000_000.0, start="20200101", end="20201231")
    assert metrics.total_trades == 3
    assert metrics.win_rate == pytest.approx(200 / 3, rel=1e-3)  # 2/3 승
    assert metrics.profit_factor == pytest.approx(1.0)  # gross_profit 300,000 / gross_loss 300,000
    assert metrics.mdd == pytest.approx(25.0)  # (1,200,000-900,000)/1,200,000*100


def test_compute_metrics_no_trades():
    metrics = compute_metrics([], initial_capital=1_000_000.0, start="20200101", end="20201231")
    assert metrics.total_trades == 0
    assert metrics.win_rate == 0.0
    assert metrics.profit_factor == 0.0
    assert metrics.cagr == 0.0
    assert metrics.mdd == 0.0


def test_compute_metrics_cagr_simple():
    trades = [_trade("2020-01-01", "2021-01-01", 1_000_000.0)]  # 1,000,000 -> 2,000,000 (100% 수익)
    metrics = compute_metrics(trades, initial_capital=1_000_000.0, start="20200101", end="20210101")
    # 약 1년(366일, 2020년 윤년) 기간의 100% 수익 -> CAGR ≈ 100%
    assert metrics.cagr == pytest.approx(100.0, rel=0.01)


def test_format_backtest_report_includes_summary_and_trades():
    trades = [_trade("2020-01-01", "2020-02-01", 100_000.0)]
    metrics = compute_metrics(trades, initial_capital=1_000_000.0, start="20200101", end="20201231")
    text = format_backtest_report("005930", "20200101", "20201231", trades, metrics)
    assert "005930" in text
    assert "2020-01-01" in text
    assert "2020-02-01" in text
    assert "1" in text  # total_trades


def test_format_backtest_report_no_trades():
    metrics = compute_metrics([], initial_capital=1_000_000.0, start="20200101", end="20201231")
    text = format_backtest_report("005930", "20200101", "20201231", [], metrics)
    assert "거래 없음" in text
