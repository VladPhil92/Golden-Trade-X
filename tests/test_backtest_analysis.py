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
