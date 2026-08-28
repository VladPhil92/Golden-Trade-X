"""Tests para scripts/performance_report.py — evaluación continua de desempeño."""

import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from backtest_analysis import Trade  # noqa: E402
from performance_report import (  # noqa: E402
    block_stats,
    current_drawdown_pct,
    evaluate,
    parse_confidence,
    parse_regime,
)


def mk_trade(net: float, close_date: str = "2026-01-05", r: float = 0.0) -> Trade:
    return Trade(
        close_date=close_date, close_time="10:00:00", position_id="1",
        symbol="XAUUSD", side="BUY", lots=0.1,
        open_price=2000.0, sl=1990.0, tp=2020.0, close_price=2000.0 + net,
        pnl=net, commission=0.0, r_multiple=r,
    )


def mk_row(net: float, comment: str = "", close_date: str = "2026-01-05") -> dict:
    return {
        "trade": mk_trade(net, close_date),
        "comment": comment,
        "open_date": close_date,
        "open_time": "09:00:00",
    }


def default_args() -> types.SimpleNamespace:
    return types.SimpleNamespace(
        wr_drop=15.0, pf_alert=1.0, dd_alert=10.0, consec_alert=4)


# ── Parsing del Comment (schema TradeLogger v2.50) ────────────────────────────

def test_parse_confidence_ok():
    assert parse_confidence("GoldenTradeX|Conf=72|Reg=TRENDING_BULL") == 72


def test_parse_confidence_missing():
    assert parse_confidence("GoldenTradeX") is None
    assert parse_confidence("") is None


def test_parse_regime_ok():
    assert parse_regime("GTX|Conf=60|Reg=RANGING") == "RANGING"


def test_parse_regime_missing():
    assert parse_regime("GTX|Conf=60") == "N/D"


# ── Métricas de bloque ────────────────────────────────────────────────────────

def test_block_stats_empty():
    assert block_stats([])["n"] == 0


def test_block_stats_basic():
    s = block_stats([mk_trade(10), mk_trade(-5), mk_trade(10)])
    assert s["n"] == 3
    assert abs(s["win_rate"] - 66.666) < 0.1
    assert abs(s["pf"] - 4.0) < 1e-9
    assert abs(s["net"] - 15.0) < 1e-9


def test_block_stats_open_streak():
    s = block_stats([mk_trade(10), mk_trade(-1), mk_trade(-1), mk_trade(-1)])
    assert s["consec_losses_end"] == 3
    assert s["max_consec_losses"] == 3


def test_current_drawdown_from_peak():
    # sube a +100 y devuelve 50 → DD actual = 50/10100
    trades = [mk_trade(100), mk_trade(-50)]
    dd = current_drawdown_pct(trades, start=10_000)
    assert abs(dd - 50 / 10_100 * 100) < 1e-6


# ── Detección de degradación ──────────────────────────────────────────────────

def test_no_alerts_when_healthy():
    rows = [mk_row(10.0) for _ in range(60)]
    res = evaluate(rows, window=20, args=default_args())
    assert res["alerts"] == []


def test_degradation_alert_on_wr_drop():
    # baseline: 40 ganadores; ventana reciente: 20 perdedores
    rows = [mk_row(10.0) for _ in range(40)] + [mk_row(-10.0) for _ in range(20)]
    res = evaluate(rows, window=20, args=default_args())
    assert any("DEGRADACION" in a for a in res["alerts"])


def test_consec_loss_alert():
    rows = [mk_row(10.0) for _ in range(40)] + [mk_row(-1.0) for _ in range(5)]
    res = evaluate(rows, window=20, args=default_args())
    assert any("RACHA" in a for a in res["alerts"])


def test_breakdown_by_regime_and_confidence():
    rows = [
        mk_row(10.0, "GTX|Conf=72|Reg=TRENDING_BULL"),
        mk_row(-5.0, "GTX|Conf=58|Reg=RANGING"),
        mk_row(8.0,  "GTX|Conf=75|Reg=TRENDING_BULL"),
    ]
    res = evaluate(rows, window=20, args=default_args())
    assert res["by_regime"]["TRENDING_BULL"]["n"] == 2
    assert res["by_regime"]["RANGING"]["n"] == 1
    assert res["by_confidence"]["70-79"]["n"] == 2
    assert res["by_confidence"]["50-59"]["n"] == 1


def test_breakdown_by_open_hour():
    rows = [mk_row(10.0), mk_row(-5.0)]
    res = evaluate(rows, window=20, args=default_args())
    assert res["by_hour"][9]["n"] == 2  # open_time fija 09:00 en mk_row
