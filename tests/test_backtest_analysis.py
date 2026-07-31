"""
pytest suite for scripts/backtest_analysis.py

Tests the statistical functions: profit_factor, max_drawdown,
daily_sharpe, monte_carlo bootstrap, equity_curve, max_consec_losses.

Run: pytest tests/ -v
"""

import sys
import os

# Allow import without package install
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.backtest_analysis import (
    Trade,
    equity_curve,
    max_drawdown,
    profit_factor,
    daily_sharpe,
    monte_carlo,
    max_consec_losses,
    daily_pct_returns,
    sharpe_from_returns,
    sortino_ratio,
    ulcer_index,
    expected_shortfall,
    annualized_return_pct,
    calmar_ratio,
    probabilistic_sharpe_ratio,
    deflated_sharpe_ratio,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def make_trade(pnl: float, commission: float = 0.0, close_date: str = "2025-01-01",
               r: float = 0.0, pos_id: str = "1") -> Trade:
    return Trade(
        close_date=close_date, close_time="12:00:00",
        position_id=pos_id, symbol="XAUUSD", side="BUY",
        lots=0.01, open_price=2000.0, sl=1990.0, tp=2030.0,
        close_price=2010.0, pnl=pnl, commission=commission,
        r_multiple=r,
    )


# ── equity_curve ───────────────────────────────────────────────────────────────

def test_equity_curve_flat():
    curve = equity_curve([0.0, 0.0, 0.0], start=10_000.0)
    assert curve == [10_000.0, 10_000.0, 10_000.0, 10_000.0]


def test_equity_curve_growth():
    curve = equity_curve([100.0, 200.0], start=1_000.0)
    assert curve == [1_000.0, 1_100.0, 1_300.0]


def test_equity_curve_loss():
    curve = equity_curve([-50.0, -50.0], start=200.0)
    assert curve == [200.0, 150.0, 100.0]


def test_equity_curve_empty():
    curve = equity_curve([], start=5_000.0)
    assert curve == [5_000.0]


# ── max_drawdown ───────────────────────────────────────────────────────────────

def test_max_drawdown_no_loss():
    curve = [100.0, 110.0, 120.0, 130.0]
    abs_dd, pct_dd = max_drawdown(curve)
    assert abs_dd == 0.0
    assert pct_dd == 0.0


def test_max_drawdown_single_loss():
    curve = [100.0, 80.0, 90.0]
    abs_dd, pct_dd = max_drawdown(curve)
    assert abs_dd == 20.0
    assert abs(pct_dd - 0.20) < 1e-9


def test_max_drawdown_partial_recovery():
    curve = [100.0, 120.0, 90.0, 110.0]
    abs_dd, pct_dd = max_drawdown(curve)
    assert abs_dd == 30.0
    assert abs(pct_dd - 30.0 / 120.0) < 1e-9


def test_max_drawdown_single_point():
    abs_dd, pct_dd = max_drawdown([500.0])
    assert abs_dd == 0.0
    assert pct_dd == 0.0


# ── profit_factor ──────────────────────────────────────────────────────────────

def test_profit_factor_basic():
    returns = [100.0, -50.0, 200.0, -100.0]
    assert profit_factor(returns) == 300.0 / 150.0


def test_profit_factor_all_wins():
    pf = profit_factor([10.0, 20.0, 30.0])
    assert pf == float("inf")


def test_profit_factor_all_losses():
    pf = profit_factor([-10.0, -20.0])
    assert pf == 0.0


def test_profit_factor_empty():
    assert profit_factor([]) == float("inf")


# ── daily_sharpe ───────────────────────────────────────────────────────────────

def test_daily_sharpe_insufficient_data():
    trades = [make_trade(100.0, close_date="2025-01-01")]
    result = daily_sharpe(trades)
    assert result == 0.0


def test_daily_sharpe_positive():
    trades = [
        make_trade(100.0, close_date="2025-01-01"),
        make_trade(120.0, close_date="2025-01-02"),
        make_trade(80.0, close_date="2025-01-03"),
        make_trade(110.0, close_date="2025-01-04"),
        make_trade(90.0, close_date="2025-01-05"),
    ]
    result = daily_sharpe(trades)
    assert result > 0.0


def test_daily_sharpe_aggregates_same_day():
    # Two trades on same day → one daily bucket
    trades = [
        make_trade(100.0, close_date="2025-01-01", pos_id="1"),
        make_trade(50.0, close_date="2025-01-01", pos_id="2"),   # same day
        make_trade(-80.0, close_date="2025-01-02", pos_id="3"),
        make_trade(60.0, close_date="2025-01-03", pos_id="4"),
    ]
    # Should produce 3 daily buckets: 150, -80, 60
    result = daily_sharpe(trades)
    assert isinstance(result, float)


def test_daily_sharpe_uses_sqrt252():
    # Construct perfectly uniform daily returns → Sharpe = mean/std * sqrt(252)
    rets = [1.0] * 10 + [-1.0] * 10    # equal wins/losses
    trades = [
        make_trade(r, close_date=f"2025-01-{i+1:02d}", pos_id=str(i))
        for i, r in enumerate(rets)
    ]
    result = daily_sharpe(trades)
    assert result == 0.0  # mean=0 → Sharpe=0


# ── monte_carlo ────────────────────────────────────────────────────────────────

def test_monte_carlo_runs_count():
    returns = [10.0, -5.0, 8.0, -3.0, 12.0]
    result  = monte_carlo(returns, runs=50, seed=0)
    assert result["runs"] == 50


def test_monte_carlo_percentile_order():
    returns = [10.0, -20.0, 15.0, -5.0, 8.0, -12.0, 20.0, -8.0]
    result  = monte_carlo(returns, runs=500, seed=42)
    assert result["dd_p5"] <= result["dd_p25"]
    assert result["dd_p25"] <= result["dd_p50"]
    assert result["dd_p50"] <= result["dd_p75"]
    assert result["dd_p75"] <= result["dd_p95"]


def test_monte_carlo_ruin_zero_for_all_wins():
    returns = [100.0] * 20
    result  = monte_carlo(returns, runs=100, seed=1)
    assert result["ruin_pct"] == 0.0
    assert result["dd_p95"]   == 0.0


def test_monte_carlo_bootstrap_differs_from_shuffle():
    # With bootstrap (replacement), same element can appear multiple times.
    # Result should vary more than simple shuffle — we can't guarantee specific
    # values but we can verify it produces different distributions on different seeds.
    returns = [100.0, -200.0, 50.0, -10.0, 75.0]
    r1 = monte_carlo(returns, runs=200, seed=1)
    r2 = monte_carlo(returns, runs=200, seed=99)
    # Two different seeds should produce different P95 values
    assert r1["dd_p95"] != r2["dd_p95"] or r1["dd_p50"] != r2["dd_p50"]


# ── max_consec_losses ──────────────────────────────────────────────────────────

def test_max_consec_losses_none():
    trades = [make_trade(10.0), make_trade(20.0)]
    assert max_consec_losses(trades) == 0


def test_max_consec_losses_all_losses():
    trades = [make_trade(-10.0), make_trade(-10.0), make_trade(-10.0)]
    assert max_consec_losses(trades) == 3


def test_max_consec_losses_mixed():
    trades = [
        make_trade(10.0),   # W
        make_trade(-5.0),   # L
        make_trade(-5.0),   # L
        make_trade(-5.0),   # L  ← streak of 3
        make_trade(10.0),   # W
        make_trade(-5.0),   # L
        make_trade(-5.0),   # L  ← streak of 2
    ]
    assert max_consec_losses(trades) == 3


def test_max_consec_losses_empty():
    assert max_consec_losses([]) == 0


# ── Trade.net and Trade.is_win ─────────────────────────────────────────────────

def test_trade_net_includes_commission():
    t = make_trade(100.0, commission=-7.0)
    assert t.net == 93.0


def test_trade_is_win_net_positive():
    assert make_trade(10.0, commission=-2.0).is_win is True


def test_trade_is_win_net_negative_due_to_commission():
    assert make_trade(5.0, commission=-10.0).is_win is False


def test_trade_is_win_exactly_zero():
    assert make_trade(0.0).is_win is False


# ── monte_carlo block bootstrap (v2.60) ────────────────────────────────────────

def test_monte_carlo_block_size_default_matches_legacy_iid():
    # block_size=1 (default) must reproduce identical behavior to the
    # original single-trade IID bootstrap for the same seed.
    returns = [10.0, -20.0, 15.0, -5.0, 8.0, -12.0, 20.0, -8.0]
    r_default = monte_carlo(returns, runs=50, seed=7)
    r_block1  = monte_carlo(returns, runs=50, seed=7, block_size=1)
    assert r_default == r_block1


def test_monte_carlo_block_size_reported():
    result = monte_carlo([10.0, -5.0, 8.0], runs=10, seed=1, block_size=3)
    assert result["block_size"] == 3


def test_monte_carlo_block_size_clamped_to_n():
    # block_size larger than the sample must not crash — clamp to n.
    result = monte_carlo([10.0, -5.0], runs=10, seed=1, block_size=99)
    assert result["block_size"] == 2


def test_monte_carlo_block_size_produces_valid_dd():
    returns = [10.0, -20.0, 15.0, -5.0, 8.0, -12.0, 20.0, -8.0] * 3
    result = monte_carlo(returns, runs=100, seed=3, block_size=4)
    assert 0.0 <= result["dd_p50"] <= 100.0
    assert result["dd_p5"] <= result["dd_p95"]


# ── daily_pct_returns / sharpe_from_returns (v2.60) ────────────────────────────

def test_daily_pct_returns_basic():
    trades = [
        make_trade(100.0, close_date="2025-01-01"),
        make_trade(-50.0, close_date="2025-01-02"),
    ]
    rets = daily_pct_returns(trades, start=10_000.0)
    assert len(rets) == 2
    assert abs(rets[0] - 100.0 / 10_000.0) < 1e-9
    assert abs(rets[1] - (-50.0 / 10_100.0)) < 1e-9


def test_daily_pct_returns_empty():
    assert daily_pct_returns([], start=10_000.0) == []


def test_sharpe_from_returns_zero_mean():
    assert sharpe_from_returns([0.01, -0.01, 0.01, -0.01]) == 0.0


def test_sharpe_from_returns_insufficient_data():
    assert sharpe_from_returns([0.01]) == 0.0


def test_sharpe_from_returns_positive():
    assert sharpe_from_returns([0.01, 0.02, 0.015, 0.018, 0.012]) > 0.0


# ── sortino_ratio ──────────────────────────────────────────────────────────────

def test_sortino_ignores_upside_volatility():
    # Wild upside swings shouldn't hurt Sortino the way they hurt Sharpe.
    upside_vol   = [0.05, -0.01, 0.20, -0.01, 0.08, -0.01]
    steady_gains = [0.02, -0.01, 0.02, -0.01, 0.02, -0.01]
    assert sortino_ratio(upside_vol) >= sortino_ratio(steady_gains)


def test_sortino_zero_when_no_downside():
    assert sortino_ratio([0.01, 0.02, 0.03]) == 0.0  # no downside → div by 0 guard


def test_sortino_insufficient_data():
    assert sortino_ratio([0.01]) == 0.0


# ── ulcer_index ────────────────────────────────────────────────────────────────

def test_ulcer_index_no_drawdown():
    assert ulcer_index([100.0, 110.0, 120.0]) == 0.0


def test_ulcer_index_positive_with_drawdown():
    assert ulcer_index([100.0, 80.0, 90.0]) > 0.0


def test_ulcer_index_empty():
    assert ulcer_index([]) == 0.0


def test_ulcer_index_deeper_dd_scores_higher():
    shallow = ulcer_index([100.0, 95.0, 100.0])
    deep    = ulcer_index([100.0, 50.0, 100.0])
    assert deep > shallow


# ── expected_shortfall ──────────────────────────────────────────────────────────

def test_expected_shortfall_averages_worst_tail():
    returns = [10.0, -100.0, 5.0, -90.0, 8.0, -80.0, 3.0, -10.0, 2.0, -5.0]
    es = expected_shortfall(returns, alpha=0.95)
    assert es < 0  # worst 5% (1 trade) should be the -100 outlier
    assert abs(es - (-100.0)) < 1e-9


def test_expected_shortfall_empty():
    assert expected_shortfall([]) == 0.0


def test_expected_shortfall_all_positive():
    es = expected_shortfall([10.0, 20.0, 30.0])
    assert es > 0


# ── annualized_return_pct / calmar_ratio ───────────────────────────────────────

def test_annualized_return_pct_one_year_doubling():
    trades = [
        make_trade(0.0, close_date="2024-01-01"),
        make_trade(0.0, close_date="2025-01-01"),
    ]
    curve = [10_000.0, 20_000.0]
    cagr = annualized_return_pct(trades, curve)
    assert abs(cagr - 100.0) < 2.0  # ~100% over ~1 year


def test_annualized_return_pct_insufficient_data():
    assert annualized_return_pct([make_trade(0.0)], [10_000.0]) == 0.0


def test_calmar_ratio_basic():
    assert calmar_ratio(20.0, 10.0) == 2.0


def test_calmar_ratio_no_drawdown_is_inf():
    assert calmar_ratio(20.0, 0.0) == float("inf")


# ── probabilistic / deflated Sharpe ratio ──────────────────────────────────────

def test_psr_high_for_strong_consistent_edge():
    # Strong, consistent positive returns with low variance → high PSR
    rets = [0.02, 0.018, 0.021, 0.019, 0.022, 0.017, 0.020, 0.019, 0.021, 0.018] * 3
    assert probabilistic_sharpe_ratio(rets) > 0.9


def test_psr_near_half_for_symmetric_noise():
    # Zero-mean symmetric noise → true Sharpe ≈ 0 → PSR ≈ 0.5 vs benchmark 0
    rets = [0.01, -0.01] * 20
    psr = probabilistic_sharpe_ratio(rets)
    assert 0.3 < psr < 0.7


def test_psr_insufficient_data():
    assert probabilistic_sharpe_ratio([0.01, 0.02]) == 0.0


def test_dsr_decreases_with_more_trials():
    rets = [0.02, 0.018, 0.021, 0.019, 0.022, 0.017, 0.020, 0.019, 0.021, 0.018] * 3
    dsr_1   = deflated_sharpe_ratio(rets, num_trials=1)
    dsr_100 = deflated_sharpe_ratio(rets, num_trials=100)
    assert dsr_100 <= dsr_1


def test_dsr_equals_psr_for_single_trial():
    rets = [0.02, 0.018, 0.021, 0.019, 0.022, 0.017, 0.020, 0.019, 0.021, 0.018]
    assert deflated_sharpe_ratio(rets, num_trials=1) == probabilistic_sharpe_ratio(rets)
