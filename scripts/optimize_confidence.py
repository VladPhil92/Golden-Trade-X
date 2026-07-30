#!/usr/bin/env python3
"""
Golden Trade X v2.00 — Confidence Threshold Optimizer.

Grid-searches InpMinConfidence (0-90, step 5) using historical CSV trades
and reports which threshold maximizes Profit Factor, Sharpe, and Net P/L.

Avoids look-ahead bias by evaluating each threshold on the FULL dataset
(the threshold is a filter, not a predictor — no data leakage).

Usage:
    python scripts/optimize_confidence.py                    # auto-discover CSVs
    python scripts/optimize_confidence.py trades.csv
    python scripts/optimize_confidence.py --step 1 --metric sharpe
    python scripts/optimize_confidence.py --output opt_results.csv
"""

import argparse
import csv
import glob
import math
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass
class Trade:
    close_date: str
    close_time: str
    symbol:     str
    side:       str
    pnl:        float
    commission: float
    r_multiple: float
    comment:    str = ""

    @property
    def net(self) -> float:
        return self.pnl + self.commission

    @property
    def is_win(self) -> bool:
        return self.net > 0

    @property
    def confidence(self) -> Optional[int]:
        for part in self.comment.split("|"):
            if part.startswith("Conf="):
                try:
                    return int(part.split("=")[1])
                except ValueError:
                    pass
        return None


def load_csv(path: str) -> List[Trade]:
    trades: List[Trade] = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                trades.append(Trade(
                    close_date=row["CloseDate"],
                    close_time=row["CloseTime"],
                    symbol=row["Symbol"],
                    side=row["Type"],
                    pnl=float(row["ProfitLoss"]),
                    commission=float(row["Commission"]),
                    r_multiple=float(row["RMultiple"]),
                    comment=row.get("Comment", ""),
                ))
            except (KeyError, ValueError):
                continue
    return trades


# ── Statistics ──────────────────────────────────────────────────────────────────

def profit_factor(rets: List[float]) -> float:
    gp = sum(r for r in rets if r > 0)
    gl = abs(sum(r for r in rets if r < 0))
    return gp / gl if gl > 0 else float("inf")


def sharpe_ratio(rets: List[float], periods: int = 252) -> float:
    n = len(rets)
    if n < 2:
        return 0.0
    mean = sum(rets) / n
    std  = math.sqrt(sum((r - mean) ** 2 for r in rets) / (n - 1))
    return (mean / std) * math.sqrt(periods) if std else 0.0


def max_dd_pct(rets: List[float], start: float = 10_000.0) -> float:
    eq, peak, max_dd = start, start, 0.0
    for r in rets:
        eq += r
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    return max_dd * 100.0


def max_consec_losses(ts: List[Trade]) -> int:
    best = cur = 0
    for t in ts:
        cur = cur + 1 if not t.is_win else 0
        best = max(best, cur)
    return best


# ── Grid search ─────────────────────────────────────────────────────────────────

def evaluate(trades: List[Trade], threshold: int) -> Optional[Dict]:
    """Evaluate all metrics for trades with confidence >= threshold."""
    subset = [t for t in trades if t.confidence is not None and t.confidence >= threshold]
    n = len(subset)
    if n < 10:
        return None

    rets = [t.net for t in subset]
    wins = sum(1 for t in subset if t.is_win)

    pf     = profit_factor(rets)
    wr     = wins / n * 100
    net    = sum(rets)
    avg_r  = sum(t.r_multiple for t in subset) / n
    sharpe = sharpe_ratio(rets)
    dd     = max_dd_pct(rets)
    mcl    = max_consec_losses(subset)

    return {
        "threshold": threshold,
        "n_trades":  n,
        "kept_pct":  n / len(trades) * 100,
        "win_rate":  wr,
        "pf":        pf,
        "net_pnl":   net,
        "avg_r":     avg_r,
        "sharpe":    sharpe,
        "max_dd":    dd,
        "max_cl":    mcl,
    }


def grid_search(trades: List[Trade], step: int) -> List[Dict]:
    results = []
    for thresh in range(0, 95, step):
        row = evaluate(trades, thresh)
        if row is not None:
            results.append(row)
    return results


# ── Scoring ─────────────────────────────────────────────────────────────────────

METRIC_KEYS = {
    "pf":      ("Profit Factor",  False),
    "sharpe":  ("Sharpe Ratio",   False),
    "net_pnl": ("Net P/L",        False),
    "max_dd":  ("Max DD %",       True),   # lower is better
}


def best_threshold(results: List[Dict], metric: str) -> Tuple[int, Dict]:
    lower_better = METRIC_KEYS.get(metric, ("", False))[1]
    valid = [r for r in results if r[metric] != float("inf")]
    if not valid:
        return -1, {}
    if lower_better:
        best = min(valid, key=lambda r: r[metric])
    else:
        best = max(valid, key=lambda r: r[metric])
    return best["threshold"], best


# ── Output ───────────────────────────────────────────────────────────────────────

def sep(title: str = "") -> None:
    print(f"\n{'─' * 68}")
    if title:
        print(f"  {title}")
        print(f"{'─' * 68}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Golden Trade X — Confidence Threshold Optimizer"
    )
    parser.add_argument("files",   nargs="*",
                        help="CSV files from TradeLogger. Auto-discovers GoldenTradeX_*.csv")
    parser.add_argument("--step",  type=int, default=5,
                        help="Grid search step size for threshold (default 5)")
    parser.add_argument("--metric", default="pf",
                        choices=list(METRIC_KEYS.keys()),
                        help="Primary metric to optimize (default: pf)")
    parser.add_argument("--output", default="",
                        help="Optional CSV path to save grid search results")
    args = parser.parse_args()

    paths = list(args.files)
    if not paths:
        paths = sorted(
            glob.glob("GoldenTradeX_*.csv")
            + glob.glob("**/GoldenTradeX_*.csv", recursive=True)
        )
    if not paths:
        print("No CSV files found. Pass a file path or run the EA to generate data.")
        sys.exit(1)

    trades: List[Trade] = []
    for p in paths:
        loaded = load_csv(p)
        print(f"  Loaded {len(loaded):>4} trades  ← {p}")
        trades.extend(loaded)

    if not trades:
        print("No valid trades loaded.")
        sys.exit(1)

    trades.sort(key=lambda t: (t.close_date, t.close_time))

    # Check how many trades have confidence data
    with_conf = sum(1 for t in trades if t.confidence is not None)
    pct_conf  = with_conf / len(trades) * 100 if trades else 0
    print(f"\n  Total trades: {len(trades)} | With Conf= data: {with_conf} ({pct_conf:.0f}%)")

    if with_conf < 20:
        print("  WARNING: fewer than 20 trades have Conf= data.")
        print("  Use GoldenTradeX v2.00+ to generate confidence-tagged trades.")
        sys.exit(1)

    # ── Grid search ────────────────────────────────────────────────
    sep(f"GRID SEARCH  step={args.step}  optimize={METRIC_KEYS[args.metric][0]}")
    results = grid_search(trades, args.step)

    # Header
    print(f"  {'Thresh':>7} {'N':>5} {'Kept%':>7} {'WR%':>7} {'PF':>7} "
          f"{'Sharpe':>8} {'NetP/L':>11} {'MaxDD%':>8} {'MCL':>5}")

    opt_thresh, opt_row = best_threshold(results, args.metric)

    for r in results:
        pf_s  = f"{r['pf']:.3f}" if r['pf'] != float('inf') else "  Inf"
        star  = " ◄" if r["threshold"] == opt_thresh else ""
        print(
            f"  {r['threshold']:>7} {r['n_trades']:>5} {r['kept_pct']:>6.1f}%"
            f" {r['win_rate']:>6.1f}% {pf_s:>7}"
            f" {r['sharpe']:>8.3f} {r['net_pnl']:>+11.2f}"
            f" {r['max_dd']:>7.1f}% {r['max_cl']:>5}{star}"
        )

    # ── Recommendations ─────────────────────────────────────────────
    sep("RECOMMENDATIONS")

    # Per-metric bests
    for metric, (label, lower) in METRIC_KEYS.items():
        t, row = best_threshold(results, metric)
        if t >= 0:
            val = row[metric]
            val_s = f"{val:.3f}" if isinstance(val, float) else str(val)
            direction = "(lower is better)" if lower else ""
            print(f"  Best {label:<18}: threshold={t:>3}  value={val_s}  {direction}")

    print()
    print(f"  Primary metric ({METRIC_KEYS[args.metric][0]}): optimal InpMinConfidence = {opt_thresh}")
    print()

    # Warn if optimal threshold cuts too many trades
    if opt_row and opt_row["kept_pct"] < 30:
        print(f"  WARNING: threshold={opt_thresh} keeps only {opt_row['kept_pct']:.0f}% of trades.")
        print("  Consider a lower threshold for statistical significance.")

    # Find balanced recommendation (PF >= 1.5 AND kept >= 40%)
    balanced = [r for r in results
                if r["pf"] >= 1.5 and r["kept_pct"] >= 40 and r["n_trades"] >= 30]
    if balanced:
        best_bal = max(balanced, key=lambda r: r["pf"])
        print("\n  Balanced recommendation (PF>=1.5 AND kept>=40%):")
        print(f"    InpMinConfidence = {best_bal['threshold']}")
        print(f"    PF={best_bal['pf']:.3f}  Sharpe={best_bal['sharpe']:.3f}"
              f"  WR={best_bal['win_rate']:.1f}%  N={best_bal['n_trades']}")

    # ── Optional CSV output ─────────────────────────────────────────
    if args.output and results:
        fields = list(results[0].keys())
        with open(args.output, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(results)
        print(f"\n  Grid search results saved → {args.output}")


if __name__ == "__main__":
    main()
