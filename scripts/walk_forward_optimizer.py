#!/usr/bin/env python3
"""
Golden Trade X — Sliding-window walk-forward optimizer for InpMinConfidence.

Reads GoldenTradeX_*.csv and searches for the optimal InpMinConfidence
threshold using a sliding walk-forward framework:
  - IS  (in-sample)  window: fit/train on first `is_months` months
  - OOS (out-of-sample) window: evaluate on following `oos_months` months
  - Advance by `step_months` months and repeat

Metrics reported per window: PF, Sharpe, Net P/L, Win%, OOS/IS efficiency.
Recommends the threshold that is most stable across OOS windows.

Usage:
    python scripts/walk_forward_optimizer.py                   # auto-discover
    python scripts/walk_forward_optimizer.py trades.csv
    python scripts/walk_forward_optimizer.py trades.csv --is-months 6 --oos-months 2
    python scripts/walk_forward_optimizer.py trades.csv --metric pf --output wf_opt.csv
    python scripts/walk_forward_optimizer.py trades.csv --threshold-step 10
"""

import argparse
import csv
import glob
import math
import sys
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

THRESHOLD_MIN  = 0
THRESHOLD_MAX  = 90
DEFAULT_STEP   = 5
DEFAULT_IS_MO  = 3
DEFAULT_OOS_MO = 1
DEFAULT_METRIC = "pf"


# ── Data model ─────────────────────────────────────────────────────────────────

@dataclass
class Trade:
    close_date:  str
    symbol:      str
    side:        str
    net:         float
    r_multiple:  float
    confidence:  int    # extracted from trade comment if available, else 100

    @property
    def is_win(self) -> bool:
        return self.net > 0

    @property
    def year_month(self) -> Tuple[int, int]:
        parts = self.close_date.split("-")
        if len(parts) >= 2:
            try:
                return int(parts[0]), int(parts[1])
            except ValueError:
                pass
        return 0, 0


def load_csv(path: str) -> List[Trade]:
    trades: List[Trade] = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                pnl    = float(row["ProfitLoss"])
                comm   = float(row["Commission"])
                r_mult = float(row["RMultiple"])
                # Extract confidence from comment field (format: "GTX|Conf=72|...")
                comment = row.get("Comment", "")
                conf = 100
                if "Conf=" in comment:
                    try:
                        conf = int(comment.split("Conf=")[1].split("|")[0])
                    except (ValueError, IndexError):
                        conf = 100
                trades.append(Trade(
                    close_date=row["CloseDate"],
                    symbol=row["Symbol"],
                    side=row["Type"],
                    net=pnl + comm,
                    r_multiple=r_mult,
                    confidence=conf,
                ))
            except (KeyError, ValueError):
                continue
    return trades


# ── Statistics ─────────────────────────────────────────────────────────────────

def profit_factor(nets: List[float]) -> float:
    gp = sum(n for n in nets if n > 0)
    gl = abs(sum(n for n in nets if n < 0))
    return gp / gl if gl > 0 else float("inf")


def sharpe(nets: List[float]) -> float:
    n = len(nets)
    if n < 2:
        return 0.0
    mean = sum(nets) / n
    std  = math.sqrt(sum((r - mean) ** 2 for r in nets) / (n - 1))
    return (mean / std) * math.sqrt(252) if std else 0.0


def metric_value(nets: List[float], metric: str) -> float:
    if not nets:
        return 0.0
    if metric == "pf":
        v = profit_factor(nets)
        return v if v != float("inf") else 9999.0
    if metric == "sharpe":
        return sharpe(nets)
    if metric == "net_pnl":
        return sum(nets)
    if metric == "win_rate":
        return sum(1 for n in nets if n > 0) / len(nets) * 100
    return 0.0


# ── Walk-forward engine ────────────────────────────────────────────────────────

def ym_to_index(y: int, m: int) -> int:
    return y * 12 + m


def index_to_ym(idx: int) -> Tuple[int, int]:
    return idx // 12, idx % 12 or 12


def filter_by_threshold(trades: List[Trade], threshold: int) -> List[Trade]:
    return [t for t in trades if t.confidence >= threshold]


def build_windows(
    trades: List[Trade],
    is_months: int,
    oos_months: int,
    step_months: int,
) -> List[Dict]:
    if not trades:
        return []

    months_all = sorted({ym_to_index(*t.year_month) for t in trades if t.year_month[0] > 0})
    if len(months_all) < is_months + oos_months:
        return []

    start = months_all[0]
    end   = months_all[-1]

    windows = []
    cursor = start
    while cursor + is_months + oos_months - 1 <= end:
        is_start  = cursor
        is_end    = cursor + is_months - 1
        oos_start = cursor + is_months
        oos_end   = cursor + is_months + oos_months - 1

        is_trades  = [t for t in trades
                      if is_start  <= ym_to_index(*t.year_month) <= is_end]
        oos_trades = [t for t in trades
                      if oos_start <= ym_to_index(*t.year_month) <= oos_end]

        if is_trades:
            windows.append({
                "is_label":  f"{index_to_ym(is_start)[0]}-{index_to_ym(is_start)[1]:02d}"
                             f"→{index_to_ym(is_end)[0]}-{index_to_ym(is_end)[1]:02d}",
                "oos_label": f"{index_to_ym(oos_start)[0]}-{index_to_ym(oos_start)[1]:02d}"
                             f"→{index_to_ym(oos_end)[0]}-{index_to_ym(oos_end)[1]:02d}",
                "is_trades":  is_trades,
                "oos_trades": oos_trades,
            })
        cursor += step_months

    return windows


def optimize_window(
    window: Dict,
    thresholds: List[int],
    metric: str,
) -> Tuple[int, float]:
    best_thresh = thresholds[0]
    best_val    = -1e18

    for thresh in thresholds:
        filtered = filter_by_threshold(window["is_trades"], thresh)
        if len(filtered) < 3:
            continue
        val = metric_value([t.net for t in filtered], metric)
        if val > best_val:
            best_val   = val
            best_thresh = thresh

    return best_thresh, best_val


def oos_efficiency(is_val: float, oos_val: float) -> Optional[float]:
    if is_val <= 0:
        return None
    return oos_val / is_val * 100.0


# ── Entry point ────────────────────────────────────────────────────────────────

def _sep(title: str = "") -> None:
    print(f"\n{'─' * 70}")
    if title:
        print(f"  {title}")
        print(f"{'─' * 70}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Golden Trade X — sliding walk-forward optimizer"
    )
    parser.add_argument(
        "files", nargs="*",
        help="CSV files from TradeLogger. Auto-discovers GoldenTradeX_*.csv if omitted.",
    )
    parser.add_argument("--is-months",  type=int, default=DEFAULT_IS_MO,
                        help=f"In-sample window length in months (default {DEFAULT_IS_MO})")
    parser.add_argument("--oos-months", type=int, default=DEFAULT_OOS_MO,
                        help=f"OOS window length in months (default {DEFAULT_OOS_MO})")
    parser.add_argument("--step-months", type=int, default=1,
                        help="Step between windows in months (default 1)")
    parser.add_argument("--threshold-step", type=int, default=DEFAULT_STEP,
                        help=f"Confidence threshold grid step (default {DEFAULT_STEP})")
    parser.add_argument("--metric", type=str, default=DEFAULT_METRIC,
                        choices=["pf", "sharpe", "net_pnl", "win_rate"],
                        help="Optimization metric (default: pf)")
    parser.add_argument("--output", type=str, default="",
                        help="Optional CSV path to save walk-forward results")
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
        print("No valid trades found.")
        sys.exit(1)

    trades.sort(key=lambda t: t.close_date)
    thresholds = list(range(THRESHOLD_MIN, THRESHOLD_MAX + 1, args.threshold_step))

    _sep(f"WALK-FORWARD OPTIMIZER  IS={args.is_months}m / OOS={args.oos_months}m  "
         f"Métrica={args.metric.upper()}")

    windows = build_windows(trades, args.is_months, args.oos_months, args.step_months)
    if not windows:
        print("  Datos insuficientes para generar ventanas de walk-forward.")
        sys.exit(1)

    print(f"  {len(windows)} ventanas generadas  |  "
          f"Umbrales evaluados: {thresholds[0]}–{thresholds[-1]} (paso {args.threshold_step})\n")

    rows = []
    optimal_counts: Dict[int, int] = defaultdict(int)

    print(f"  {'IS Window':<20} {'OOS Window':<20} {'OptThresh':>9} "
          f"{'IS Met':>8} {'OOS Met':>8} {'Eff%':>7} {'OOS PF':>7} {'OOS N':>6}")

    for w in windows:
        best_thresh, is_val = optimize_window(w, thresholds, args.metric)
        optimal_counts[best_thresh] += 1

        oos_filtered = filter_by_threshold(w["oos_trades"], best_thresh)
        oos_nets = [t.net for t in oos_filtered]
        oos_val  = metric_value(oos_nets, args.metric) if oos_nets else 0.0
        oos_pf   = profit_factor(oos_nets) if oos_nets else 0.0
        eff      = oos_efficiency(is_val, oos_val)
        eff_str  = f"{eff:.1f}%" if eff is not None else "—"
        oos_pf_s = f"{oos_pf:.3f}" if oos_pf != float("inf") else "Inf"

        print(f"  {w['is_label']:<20} {w['oos_label']:<20} {best_thresh:>9} "
              f"{is_val:>8.3f} {oos_val:>8.3f} {eff_str:>7} {oos_pf_s:>7} {len(oos_filtered):>6}")

        rows.append({
            "is_window":     w["is_label"],
            "oos_window":    w["oos_label"],
            "opt_threshold": best_thresh,
            "is_metric":     round(is_val, 4),
            "oos_metric":    round(oos_val, 4),
            "oos_efficiency": round(eff, 2) if eff is not None else "",
            "oos_pf":        round(oos_pf, 4) if oos_pf != float("inf") else "inf",
            "oos_trades":    len(oos_filtered),
        })

    # ── Recommendation ─────────────────────────────────────────────────────────
    _sep("RECOMENDACIÓN")
    if optimal_counts:
        most_common = max(optimal_counts, key=lambda k: optimal_counts[k])
        print(f"  Umbral óptimo más frecuente en IS: {most_common}"
              f"  (seleccionado en {optimal_counts[most_common]}/{len(windows)} ventanas)")
        print()
        # Validate on all OOS with recommended threshold
        all_oos = [t for w in windows for t in w["oos_trades"]]
        oos_filtered = filter_by_threshold(all_oos, most_common)
        if oos_filtered:
            oos_nets = [t.net for t in oos_filtered]
            oos_pf   = profit_factor(oos_nets)
            oos_wr   = sum(1 for n in oos_nets if n > 0) / len(oos_nets) * 100
            oos_sh   = sharpe(oos_nets)
            print(f"  OOS combinado con threshold={most_common}:")
            print(f"    Trades : {len(oos_filtered)}")
            print(f"    PF     : {oos_pf:.3f}")
            print(f"    Win%   : {oos_wr:.1f}%")
            print(f"    Sharpe : {oos_sh:.3f}")
            print(f"    Net P/L: {sum(oos_nets):+.2f}")
            print()
            if oos_pf >= 1.3 and oos_wr >= 40:
                print(f"  ► Configurar InpMinConfidence={most_common} en GoldenTradeX.set")
            else:
                print("  ► Resultado OOS débil. Considerar threshold más alto o revisar estrategia.")
        else:
            print(f"  ► Sin suficientes trades OOS con threshold={most_common}")

    # ── CSV output ─────────────────────────────────────────────────────────────
    if args.output and rows:
        with open(args.output, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        print(f"\n  Walk-forward results saved → {args.output}")


if __name__ == "__main__":
    main()
