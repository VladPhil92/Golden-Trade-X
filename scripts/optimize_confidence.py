#!/usr/bin/env python3
"""Golden Trade X — legacy CSV confidence sensitivity explorer.

This utility is retained for backwards-compatible inspection of historical
TradeLogger CSVs. It performs a post-hoc *in-sample sensitivity table* only.
It does NOT optimize or validate ``InpMinConfidence`` and must not be used to
promote a parameter change.

Why: filtering already-observed trades cannot reproduce the counterfactual EA
path that would result from rejecting trades at runtime. Skipped trades can
change equity, drawdown, sizing, loss streaks and future state. Full-sample
threshold selection also introduces selection bias.

For v2.80 research use ``scripts/confidence_research.py`` with a v2.70 SQLite
telemetry database and provenance manifest. That tool freezes a threshold on a
chronological training partition and evaluates it once on a later holdout, while
still requiring Strategy Tester confirmation before any parameter change.
"""

from __future__ import annotations

import argparse
import csv
import glob
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Trade:
    close_date: str
    close_time: str
    symbol: str
    side: str
    pnl: float
    commission: float
    r_multiple: float
    comment: str = ""

    @property
    def net(self) -> float:
        return self.pnl + self.commission

    @property
    def confidence(self) -> int | None:
        for part in self.comment.split("|"):
            if part.startswith("Conf="):
                try:
                    value = int(part.split("=", 1)[1])
                except ValueError:
                    return None
                return value if 0 <= value <= 100 else None
        return None


def load_csv(path: str | Path) -> list[Trade]:
    trades: list[Trade] = []
    with Path(path).open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            try:
                trades.append(
                    Trade(
                        close_date=row["CloseDate"],
                        close_time=row["CloseTime"],
                        symbol=row["Symbol"],
                        side=row["Type"],
                        pnl=float(row["ProfitLoss"]),
                        commission=float(row["Commission"]),
                        r_multiple=float(row["RMultiple"]),
                        comment=row.get("Comment", ""),
                    )
                )
            except (KeyError, ValueError):
                continue
    return trades


def _r_profit_factor(values: list[float]) -> float | None:
    gross_positive = sum(value for value in values if value > 0)
    gross_negative = abs(sum(value for value in values if value < 0))
    return gross_positive / gross_negative if gross_negative > 0 else None


def evaluate(trades: list[Trade], threshold: int, min_trades: int = 10) -> dict[str, Any] | None:
    """Describe observed trades with confidence >= threshold; no counterfactual claim."""
    subset = [
        trade
        for trade in trades
        if trade.confidence is not None and trade.confidence >= threshold
    ]
    if len(subset) < min_trades:
        return None

    realized_r = [trade.r_multiple for trade in subset]
    positive = sum(value > 0 for value in realized_r)
    return {
        "threshold": threshold,
        "observations": len(subset),
        "kept_pct": len(subset) / len(trades) * 100.0 if trades else 0.0,
        "positive_rate": positive / len(subset),
        "avg_realized_r": statistics.fmean(realized_r),
        "median_realized_r": statistics.median(realized_r),
        "net_realized_r": sum(realized_r),
        "r_profit_factor": _r_profit_factor(realized_r),
    }


def sensitivity_table(trades: list[Trade], step: int, min_trades: int = 10) -> list[dict[str, Any]]:
    if step < 1 or step > 100:
        raise ValueError("step must be between 1 and 100")
    rows: list[dict[str, Any]] = []
    for threshold in range(0, 101, step):
        row = evaluate(trades, threshold, min_trades=min_trades)
        if row is not None:
            rows.append(row)
    return rows


def _print_table(rows: list[dict[str, Any]]) -> None:
    print("\nLEGACY IN-SAMPLE SENSITIVITY — NOT PARAMETER VALIDATION")
    print("Threshold     N   Kept%   PosRate    AvgR   MedianR      NetR     R-PF")
    for row in rows:
        pf = row["r_profit_factor"]
        pf_text = f"{pf:.3f}" if pf is not None else "N/A"
        print(
            f"{row['threshold']:>9} {row['observations']:>5} "
            f"{row['kept_pct']:>7.1f} {row['positive_rate']:>9.3f} "
            f"{row['avg_realized_r']:>7.3f} {row['median_realized_r']:>9.3f} "
            f"{row['net_realized_r']:>9.3f} {pf_text:>8}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Legacy post-hoc confidence sensitivity table (not optimization/validation)"
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="TradeLogger CSV files; otherwise auto-discover GoldenTradeX_*.csv",
    )
    parser.add_argument("--step", type=int, default=5)
    parser.add_argument("--min-trades", type=int, default=10)
    parser.add_argument("--output", default="", help="optional CSV output path")
    # Kept only so old command lines fail safely rather than silently changing meaning.
    parser.add_argument(
        "--metric",
        default="",
        help="deprecated; ignored because this utility no longer selects an in-sample 'best' threshold",
    )
    args = parser.parse_args()

    paths = list(args.files)
    if not paths:
        paths = sorted(
            set(
                glob.glob("GoldenTradeX_*.csv")
                + glob.glob("**/GoldenTradeX_*.csv", recursive=True)
            )
        )
    if not paths:
        print("No CSV files found. This legacy tool has no data to describe.")
        raise SystemExit(1)

    trades: list[Trade] = []
    for path in paths:
        loaded = load_csv(path)
        print(f"Loaded {len(loaded):>4} trades <- {path}")
        trades.extend(loaded)

    trades.sort(key=lambda trade: (trade.close_date, trade.close_time))
    confidence_count = sum(trade.confidence is not None for trade in trades)
    if confidence_count < args.min_trades:
        print(
            "INSUFFICIENT_EVIDENCE: fewer confidence-tagged observed trades than --min-trades."
        )
        raise SystemExit(3)

    if args.metric:
        print(
            "NOTE: --metric is deprecated and ignored. Full-sample metric maximization is not validation."
        )

    rows = sensitivity_table(trades, args.step, min_trades=args.min_trades)
    _print_table(rows)
    print(
        "\nNo threshold recommendation is emitted. Use confidence_research.py for chronological "
        "train/holdout discrimination research and controlled Strategy Tester reruns before changing "
        "InpMinConfidence."
    )

    if args.output and rows:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        print(f"Sensitivity table saved -> {output}")


if __name__ == "__main__":
    main()
