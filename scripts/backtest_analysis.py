#!/usr/bin/env python3
"""
Golden Trade X — Statistical analysis of TradeLogger CSV exports.

Reads GoldenTradeX_*.csv (produced by TradeLogger.mqh) and computes:
  - Core metrics: win rate, profit factor, Sharpe, max drawdown, R-stats
  - Monte Carlo (default 1 000 runs): max-DD distribution, ruin probability
  - Walk-forward table: rolling quarterly metrics
  - Institutional targets check (PF>=1.8, Sharpe>=1.5, etc.)

Usage:
    python scripts/backtest_analysis.py                        # auto-discover CSVs
    python scripts/backtest_analysis.py trades.csv            # specific file
    python scripts/backtest_analysis.py *.csv --mc-runs 2000  # multiple files
    python scripts/backtest_analysis.py --output report.csv   # save WF table
"""

import argparse
import csv
import glob
import math
import random
import sys
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Tuple

RUIN_THRESHOLD = 0.40   # 40 % drawdown counts as ruin in Monte Carlo


# ── Data model ─────────────────────────────────────────────────────────────────

@dataclass
class Trade:
    close_date:  str
    close_time:  str
    position_id: str
    symbol:      str
    side:        str
    lots:        float
    open_price:  float
    sl:          float
    tp:          float
    close_price: float
    pnl:         float
    commission:  float
    r_multiple:  float

    @property
    def net(self) -> float:
        return self.pnl + self.commission

    @property
    def is_win(self) -> bool:
        return self.net > 0


def load_csv(path: str) -> List[Trade]:
    trades: List[Trade] = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                trades.append(Trade(
                    close_date=row["CloseDate"], close_time=row["CloseTime"],
                    position_id=row["PositionID"], symbol=row["Symbol"],
                    side=row["Type"],
                    lots=float(row["Lots"]),
                    open_price=float(row["OpenPrice"]),
                    sl=float(row["InitialSL"]), tp=float(row["InitialTP"]),
                    close_price=float(row["ClosePrice"]),
                    pnl=float(row["ProfitLoss"]),
                    commission=float(row["Commission"]),
                    r_multiple=float(row["RMultiple"]),
                ))
            except (KeyError, ValueError):
                continue
    return trades


# ── Statistical helpers ────────────────────────────────────────────────────────

def equity_curve(returns: List[float], start: float = 10_000.0) -> List[float]:
    eq = [start]
    for r in returns:
        eq.append(eq[-1] + r)
    return eq


def max_drawdown(curve: List[float]) -> Tuple[float, float]:
    """Returns (absolute_dd, pct_dd)."""
    peak, max_abs, max_pct = curve[0], 0.0, 0.0
    for v in curve:
        if v > peak:
            peak = v
        dd_abs = peak - v
        dd_pct = dd_abs / peak if peak > 0 else 0.0
        if dd_abs > max_abs:
            max_abs, max_pct = dd_abs, dd_pct
    return max_abs, max_pct


def sharpe_ratio(returns: List[float], periods_per_year: int = 252) -> float:
    n = len(returns)
    if n < 2:
        return 0.0
    mean = sum(returns) / n
    std = math.sqrt(sum((r - mean) ** 2 for r in returns) / (n - 1))
    return (mean / std) * math.sqrt(periods_per_year) if std else 0.0


def profit_factor(returns: List[float]) -> float:
    gross_profit = sum(r for r in returns if r > 0)
    gross_loss   = abs(sum(r for r in returns if r < 0))
    return gross_profit / gross_loss if gross_loss > 0 else float("inf")


def max_consec_losses(trades: List[Trade]) -> int:
    best = cur = 0
    for t in trades:
        cur = cur + 1 if not t.is_win else 0
        best = max(best, cur)
    return best


# ── Monte Carlo ────────────────────────────────────────────────────────────────

def monte_carlo(
    returns: List[float],
    runs: int = 1_000,
    start: float = 10_000.0,
    seed: int = 42,
) -> Dict:
    rng = random.Random(seed)
    dd_pcts: List[float] = []
    ruins = 0

    for _ in range(runs):
        shuffled = returns[:]
        rng.shuffle(shuffled)
        _, dd_pct = max_drawdown(equity_curve(shuffled, start))
        dd_pcts.append(dd_pct * 100)
        if dd_pct >= RUIN_THRESHOLD:
            ruins += 1

    dd_pcts.sort()
    n = len(dd_pcts)

    def p(pct: float) -> float:
        return dd_pcts[min(int(pct / 100 * n), n - 1)]

    return {
        "runs": runs,
        "dd_p5": p(5), "dd_p25": p(25), "dd_p50": p(50),
        "dd_p75": p(75), "dd_p95": p(95),
        "ruin_pct": ruins / runs * 100,
    }


# ── Walk-forward ───────────────────────────────────────────────────────────────

def walk_forward_table(trades: List[Trade]) -> List[Dict]:
    def quarter(date_str: str) -> str:
        parts = date_str.split("-")
        if len(parts) < 2:
            return "Unknown"
        year, mon = int(parts[0]), int(parts[1])
        return f"{year}-Q{(mon - 1) // 3 + 1}"

    buckets: Dict[str, List[Trade]] = defaultdict(list)
    for t in trades:
        buckets[quarter(t.close_date)].append(t)

    rows = []
    for window in sorted(buckets):
        ts = buckets[window]
        rets = [t.net for t in ts]
        wins = sum(1 for t in ts if t.is_win)
        rows.append({
            "window": window,
            "trades": len(ts),
            "win_rate": wins / len(ts) * 100,
            "profit_factor": profit_factor(rets),
            "net_pnl": sum(rets),
            "avg_r": sum(t.r_multiple for t in ts) / len(ts),
            "sharpe": sharpe_ratio(rets),
        })
    return rows


# ── Reporting ──────────────────────────────────────────────────────────────────

def _sep(title: str = "") -> None:
    print(f"\n{'─' * 58}")
    if title:
        print(f"  {title}")
        print(f"{'─' * 58}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Golden Trade X — backtest statistical analysis"
    )
    parser.add_argument(
        "files", nargs="*",
        help="CSV files from TradeLogger. Auto-discovers GoldenTradeX_*.csv if omitted.",
    )
    parser.add_argument(
        "--mc-runs", type=int, default=1_000,
        help="Number of Monte Carlo simulations (default 1000)",
    )
    parser.add_argument(
        "--start-equity", type=float, default=10_000.0,
        help="Starting equity for MC equity curves (default 10000)",
    )
    parser.add_argument(
        "--output", type=str, default="",
        help="Optional CSV path to save the walk-forward table",
    )
    args = parser.parse_args()

    # ── File discovery ─────────────────────────────────────────────────
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
        print("No valid trades in provided files.")
        sys.exit(1)

    trades.sort(key=lambda t: (t.close_date, t.close_time))
    returns = [t.net for t in trades]
    n       = len(trades)
    wins    = sum(1 for t in trades if t.is_win)
    losses  = n - wins

    # ── Core metrics ───────────────────────────────────────────────────
    _sep("MÉTRICAS GENERALES")
    net_pnl  = sum(returns)
    pf       = profit_factor(returns)
    wr       = wins / n * 100
    avg_r    = sum(t.r_multiple for t in trades) / n
    avg_win  = sum(t.net for t in trades if t.is_win) / wins if wins else 0.0
    avg_loss = sum(t.net for t in trades if not t.is_win) / losses if losses else 0.0
    rr       = abs(avg_win / avg_loss) if avg_loss else float("inf")
    sharpe   = sharpe_ratio(returns)
    curve    = equity_curve(returns, args.start_equity)
    dd_abs, dd_pct = max_drawdown(curve)
    rec_fac  = net_pnl / dd_abs if dd_abs > 0 else float("inf")
    exp_val  = net_pnl / n
    max_cl   = max_consec_losses(trades)

    for label, val in [
        ("Operaciones totales",    f"{n}"),
        ("Ganadoras / Perdedoras", f"{wins} / {losses}"),
        ("Win rate",               f"{wr:.1f} %"),
        ("Profit factor",          f"{pf:.3f}"),
        ("Net P/L",                f"{net_pnl:+.2f}"),
        ("Valor esperado / trade", f"{exp_val:+.2f}"),
        ("R-múltiplo promedio",    f"{avg_r:+.3f} R"),
        ("Ganancia media",         f"{avg_win:+.2f}"),
        ("Pérdida media",          f"{avg_loss:+.2f}"),
        ("Ratio R:R realizado",    f"1 : {rr:.2f}"),
        ("Sharpe ratio (anual.)",  f"{sharpe:.3f}"),
        ("Max drawdown",           f"{dd_abs:.2f}  ({dd_pct * 100:.1f} %)"),
        ("Recovery factor",        f"{rec_fac:.2f}"),
        ("Pérd. consec. máximas",  f"{max_cl}"),
    ]:
        print(f"  {label:<32} {val}")

    # ── Monte Carlo ────────────────────────────────────────────────────
    _sep(f"MONTE CARLO  ({args.mc_runs:,} simulaciones · seed=42)")
    mc = monte_carlo(returns, runs=args.mc_runs, start=args.start_equity)
    for label, key in [
        ("Max DD P5  (escenario favorable)", "dd_p5"),
        ("Max DD P25",                       "dd_p25"),
        ("Max DD P50 (mediana)",             "dd_p50"),
        ("Max DD P75",                       "dd_p75"),
        ("Max DD P95 (escenario adverso)",   "dd_p95"),
        (f"Prob. ruina (DD ≥ {RUIN_THRESHOLD*100:.0f} %)",  "ruin_pct"),
    ]:
        print(f"  {label:<40} {mc[key]:.1f} %")

    # ── Walk-forward table ─────────────────────────────────────────────
    wf_rows = walk_forward_table(trades)
    if len(wf_rows) > 1:
        _sep("WALK-FORWARD POR TRIMESTRE")
        print(f"  {'Ventana':<10} {'N':>5} {'WR%':>7} {'PF':>7} {'NetP/L':>10} "
              f"{'AvgR':>7} {'Sharpe':>7}")
        for r in wf_rows:
            print(
                f"  {r['window']:<10} {r['trades']:>5} {r['win_rate']:>6.1f}%"
                f" {r['profit_factor']:>7.3f} {r['net_pnl']:>+10.2f}"
                f" {r['avg_r']:>+6.3f}R {r['sharpe']:>7.3f}"
            )

    # ── Targets check ──────────────────────────────────────────────────
    _sep("OBJETIVOS INSTITUCIONALES")
    checks = [
        ("Profit Factor ≥ 1.8",   pf >= 1.8,              f"{pf:.3f}"),
        ("Sharpe ≥ 1.5",          sharpe >= 1.5,          f"{sharpe:.3f}"),
        ("Win rate ≥ 45 %",       wr >= 45,               f"{wr:.1f} %"),
        ("Max DD ≤ 15 %",         dd_pct <= 0.15,         f"{dd_pct*100:.1f} %"),
        ("MC DD P95 ≤ 25 %",      mc["dd_p95"] <= 25,     f"{mc['dd_p95']:.1f} %"),
        ("MC ruina < 5 %",        mc["ruin_pct"] < 5,     f"{mc['ruin_pct']:.1f} %"),
        ("Recovery factor ≥ 3",   rec_fac >= 3,           f"{rec_fac:.2f}"),
        ("Pérd. consec. ≤ 5",     max_cl <= 5,            f"{max_cl}"),
    ]
    all_pass = True
    for label, passed, val in checks:
        icon = "✓" if passed else "✗"
        all_pass = all_pass and passed
        print(f"  [{icon}] {label:<32} {val}")

    print()
    if all_pass:
        print("  >>> TODOS LOS OBJETIVOS SUPERADOS — listo para prueba en demo real <<<")
    else:
        failed = sum(1 for _, p, _ in checks if not p)
        print(f"  >>> {failed} objetivo(s) pendiente(s) — optimizar antes de capital real <<<")

    # ── Optional CSV output ────────────────────────────────────────────
    if args.output and wf_rows:
        with open(args.output, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=wf_rows[0].keys())
            writer.writeheader()
            writer.writerows(wf_rows)
        print(f"\n  Walk-forward table saved → {args.output}")


if __name__ == "__main__":
    main()
