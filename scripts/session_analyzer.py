#!/usr/bin/env python3
"""
Golden Trade X — Per-session and per-hour performance analyzer.

Reads GoldenTradeX_*.csv (produced by TradeLogger.mqh) and breaks down
performance by trading session (Asian/London/NY/London-NY Overlap) and
by hour of day. Outputs a text heatmap and per-session summary table.

Usage:
    python scripts/session_analyzer.py                        # auto-discover
    python scripts/session_analyzer.py trades.csv            # specific file
    python scripts/session_analyzer.py *.csv --utc-offset 3  # broker UTC+3
    python scripts/session_analyzer.py trades.csv --output sessions.csv
"""

import argparse
import csv
import glob
import sys
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional

# ── Session windows (UTC hours) ────────────────────────────────────────────────
# Adjust with --utc-offset to match your broker's server time
SESSIONS = {
    "Asian":          (0,  8),   # 00:00 – 08:00 UTC
    "London":         (7,  16),  # 07:00 – 16:00 UTC
    "London-NY":      (12, 17),  # 12:00 – 17:00 UTC (overlap)
    "New York":       (12, 21),  # 12:00 – 21:00 UTC
}

HEATMAP_CHARS = " ░▒▓█"


# ── Data model ─────────────────────────────────────────────────────────────────

@dataclass
class Trade:
    close_date: str
    close_time: str
    symbol:     str
    side:       str
    pnl:        float
    commission: float
    r_multiple: float

    @property
    def net(self) -> float:
        return self.pnl + self.commission

    @property
    def is_win(self) -> bool:
        return self.net > 0

    @property
    def hour(self) -> Optional[int]:
        parts = self.close_time.split(":")
        if parts:
            try:
                return int(parts[0])
            except ValueError:
                return None
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
                ))
            except (KeyError, ValueError):
                continue
    return trades


# ── Helpers ────────────────────────────────────────────────────────────────────

def profit_factor(nets: List[float]) -> float:
    gross_profit = sum(n for n in nets if n > 0)
    gross_loss   = abs(sum(n for n in nets if n < 0))
    return gross_profit / gross_loss if gross_loss > 0 else float("inf")


def _heatmap_char(value: float, min_v: float, max_v: float) -> str:
    if max_v <= min_v:
        return HEATMAP_CHARS[0]
    idx = int((value - min_v) / (max_v - min_v) * (len(HEATMAP_CHARS) - 1))
    return HEATMAP_CHARS[max(0, min(idx, len(HEATMAP_CHARS) - 1))]


def session_label(broker_hour: int, utc_offset: int) -> str:
    utc = (broker_hour - utc_offset) % 24
    labels = []
    for name, (start, end) in SESSIONS.items():
        if start <= utc < end:
            labels.append(name)
    return "/".join(labels) if labels else "Off-Hours"


def _sep(title: str = "") -> None:
    print(f"\n{'─' * 62}")
    if title:
        print(f"  {title}")
        print(f"{'─' * 62}")


# ── Core analysis ──────────────────────────────────────────────────────────────

def analyze(trades: List[Trade], utc_offset: int) -> Dict:
    by_hour:    Dict[int, List[Trade]] = defaultdict(list)
    by_session: Dict[str, List[Trade]] = defaultdict(list)

    for t in trades:
        h = t.hour
        if h is None:
            continue
        by_hour[h].append(t)
        sess = session_label(h, utc_offset)
        for part in sess.split("/"):
            by_session[part.strip()].append(t)

    return {"by_hour": by_hour, "by_session": by_session}


def print_hourly_heatmap(by_hour: Dict[int, List[Trade]]) -> None:
    _sep("HEATMAP HORARIO (hora de cierre del broker)")
    nets_per_hour = {h: sum(t.net for t in ts) for h, ts in by_hour.items()}

    if not nets_per_hour:
        print("  Sin datos.")
        return

    min_net = min(nets_per_hour.values())
    max_net = max(nets_per_hour.values())

    print(f"  {'H':>3}  {'N':>4}  {'NetP/L':>9}  {'WR%':>6}  Mapa")
    for h in range(24):
        ts = by_hour.get(h, [])
        if not ts:
            print(f"  {h:02d}:  {'—':>4}  {'—':>9}  {'—':>6}  ·")
            continue
        net = nets_per_hour[h]
        wr  = sum(1 for t in ts if t.is_win) / len(ts) * 100
        bar = _heatmap_char(net, min_net, max_net) * max(1, int(abs(net) / max(abs(max_net), abs(min_net), 1) * 20))
        color = "+" if net >= 0 else "-"
        print(f"  {h:02d}:  {len(ts):>4}  {net:>+9.2f}  {wr:>5.1f}%  {color}{bar}")


def print_session_table(by_session: Dict[str, List[Trade]]) -> None:
    _sep("RENDIMIENTO POR SESIÓN")
    headers = ["Sesión", "N", "Win%", "PF", "Net P/L", "Avg R", "Mejor", "Peor"]
    print(f"  {headers[0]:<15} {headers[1]:>5} {headers[2]:>7} {headers[3]:>6} "
          f"{headers[4]:>10} {headers[5]:>7} {headers[6]:>9} {headers[7]:>9}")

    session_order = ["Asian", "London", "London-NY", "New York", "Off-Hours"]
    shown = set()
    for name in session_order + sorted(by_session.keys()):
        if name in shown or name not in by_session:
            continue
        shown.add(name)
        ts   = by_session[name]
        nets = [t.net for t in ts]
        wins = sum(1 for t in ts if t.is_win)
        pf   = profit_factor(nets)
        pf_s = f"{pf:.3f}" if pf != float("inf") else "Inf"
        avg_r = sum(t.r_multiple for t in ts) / len(ts)
        print(
            f"  {name:<15} {len(ts):>5} {wins/len(ts)*100:>6.1f}% {pf_s:>6} "
            f"{sum(nets):>+10.2f} {avg_r:>+6.3f}R {max(nets):>+9.2f} {min(nets):>+9.2f}"
        )


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Golden Trade X — per-session and per-hour performance analyzer"
    )
    parser.add_argument(
        "files", nargs="*",
        help="CSV files from TradeLogger. Auto-discovers GoldenTradeX_*.csv if omitted.",
    )
    parser.add_argument(
        "--utc-offset", type=int, default=3,
        help="Broker server UTC offset in hours (default +3, EET winter / XM default)",
    )
    parser.add_argument(
        "--output", type=str, default="",
        help="Optional CSV path to save per-session summary",
    )
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

    trades.sort(key=lambda t: (t.close_date, t.close_time))
    print(f"\n  UTC offset: +{args.utc_offset}h  |  "
          f"Trades analizados: {len(trades)}  |  "
          f"Rango: {trades[0].close_date} → {trades[-1].close_date}")

    result = analyze(trades, args.utc_offset)
    print_hourly_heatmap(result["by_hour"])
    print_session_table(result["by_session"])

    if args.output and result["by_session"]:
        with open(args.output, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["session", "trades", "win_pct", "profit_factor",
                             "net_pnl", "avg_r", "best_trade", "worst_trade"])
            for name, ts in sorted(result["by_session"].items()):
                nets = [t.net for t in ts]
                wins = sum(1 for t in ts if t.is_win)
                pf   = profit_factor(nets)
                avg_r = sum(t.r_multiple for t in ts) / len(ts)
                writer.writerow([
                    name, len(ts),
                    round(wins / len(ts) * 100, 2),
                    round(pf, 4) if pf != float("inf") else "inf",
                    round(sum(nets), 4),
                    round(avg_r, 4),
                    round(max(nets), 4),
                    round(min(nets), 4),
                ])
        print(f"\n  Session summary saved → {args.output}")


if __name__ == "__main__":
    main()
