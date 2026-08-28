"""I/O and aggregation coverage for backtest_analysis core logic."""

from __future__ import annotations

from pathlib import Path

from scripts.backtest_analysis import (
    Trade,
    annualized_return_pct,
    equity_curve,
    load_csv,
    sharpe_ratio,
    walk_forward_table,
)


def _trade(date: str, pnl: float, r: float = 1.0, position_id: str = "1") -> Trade:
    return Trade(
        close_date=date,
        close_time="12:00:00",
        position_id=position_id,
        symbol="XAUUSD",
        side="BUY",
        lots=0.1,
        open_price=2000.0,
        sl=1990.0,
        tp=2020.0,
        close_price=2010.0,
        pnl=pnl,
        commission=-1.0,
        r_multiple=r,
    )


def test_load_csv_parses_valid_rows_and_skips_invalid(tmp_path: Path) -> None:
    csv_path = tmp_path / "trades.csv"
    csv_path.write_text(
        "CloseDate,CloseTime,PositionID,Symbol,Type,Lots,OpenPrice,InitialSL,InitialTP,ClosePrice,ProfitLoss,Commission,RMultiple\n"
        "2026-01-01,12:00:00,1,XAUUSD,BUY,0.10,2000,1990,2020,2010,12,-1,1.2\n"
        "2026-01-02,12:00:00,2,XAUUSD,BUY,not-a-number,2000,1990,2020,2010,12,-1,1.2\n",
        encoding="utf-8",
    )

    trades = load_csv(str(csv_path))

    assert len(trades) == 1
    assert trades[0].position_id == "1"
    assert trades[0].net == 11.0


def test_sharpe_ratio_guards_and_positive_case() -> None:
    assert sharpe_ratio([]) == 0.0
    assert sharpe_ratio([1.0]) == 0.0
    assert sharpe_ratio([1.0, 1.0, 1.0]) == 0.0
    assert sharpe_ratio([1.0, 2.0, 3.0]) > 0.0


def test_walk_forward_table_groups_quarters_and_metrics() -> None:
    trades = [
        _trade("2026-01-10", 10.0, 1.0, "1"),
        _trade("2026-03-10", -5.0, -0.5, "2"),
        _trade("2026-04-10", 8.0, 0.8, "3"),
    ]

    rows = walk_forward_table(trades)

    assert [row["window"] for row in rows] == ["2026-Q1", "2026-Q2"]
    assert rows[0]["trades"] == 2
    assert rows[0]["net_pnl"] == 3.0  # commissions included
    assert rows[1]["trades"] == 1


def test_walk_forward_table_handles_unknown_date_bucket() -> None:
    rows = walk_forward_table([_trade("invalid", 5.0)])
    assert rows[0]["window"] == "Unknown"


def test_annualized_return_handles_invalid_dates_and_growth() -> None:
    invalid = [_trade("bad", 1.0, position_id="1"), _trade("also-bad", 1.0, position_id="2")]
    assert annualized_return_pct(invalid, equity_curve([1.0, 1.0])) == 0.0

    trades = [_trade("2025-01-01", 100.0, position_id="1"), _trade("2026-01-01", 100.0, position_id="2")]
    cagr = annualized_return_pct(trades, [10_000.0, 10_100.0, 10_200.0])
    assert cagr > 0.0
