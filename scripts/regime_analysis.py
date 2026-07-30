#!/usr/bin/env python3
"""
Golden Trade X v2.00 — Análisis estadístico por régimen de mercado.

Clasifica cada trade del CSV de TradeLogger según el régimen de mercado
inferido del comentario de la operación (Conf=N|Reg=REGIME) y genera
un informe por régimen + stress testing por condición de mercado.

Uso:
    python scripts/regime_analysis.py                    # auto-descubre CSVs
    python scripts/regime_analysis.py trades.csv
    python scripts/regime_analysis.py --output report.csv
"""

import argparse
import csv
import glob
import math
import sys
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple  # noqa: F401

KNOWN_REGIMES = [
    "TRENDING_BULL", "TRENDING_BEAR", "RANGING",
    "VOLATILE", "ACCUMULATION", "DISTRIBUTION", "UNKNOWN",
]


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
    comment:     str = ""

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

    @property
    def regime(self) -> str:
        for part in self.comment.split("|"):
            if part.startswith("Reg="):
                r = part.split("=")[1].strip()
                return r if r in KNOWN_REGIMES else "UNKNOWN"
        return "UNKNOWN"


def load_csv(path: str) -> List[Trade]:
    trades: List[Trade] = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                trades.append(Trade(
                    close_date=row["CloseDate"],
                    close_time=row["CloseTime"],
                    position_id=row["PositionID"],
                    symbol=row["Symbol"],
                    side=row["Type"],
                    lots=float(row["Lots"]),
                    open_price=float(row["OpenPrice"]),
                    sl=float(row["InitialSL"]),
                    tp=float(row["InitialTP"]),
                    close_price=float(row["ClosePrice"]),
                    pnl=float(row["ProfitLoss"]),
                    commission=float(row["Commission"]),
                    r_multiple=float(row["RMultiple"]),
                    comment=row.get("Comment", ""),
                ))
            except (KeyError, ValueError):
                continue
    return trades


def profit_factor(returns: List[float]) -> float:
    gross_profit = sum(r for r in returns if r > 0)
    gross_loss   = abs(sum(r for r in returns if r < 0))
    return gross_profit / gross_loss if gross_loss > 0 else float("inf")


def sharpe_ratio(returns: List[float], periods: int = 252) -> float:
    n = len(returns)
    if n < 2:
        return 0.0
    mean = sum(returns) / n
    std  = math.sqrt(sum((r - mean) ** 2 for r in returns) / (n - 1))
    return (mean / std) * math.sqrt(periods) if std else 0.0


def max_drawdown_pct(returns: List[float], start: float = 10_000.0) -> float:
    eq = start
    peak = start
    max_dd = 0.0
    for r in returns:
        eq += r
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    return max_dd * 100.0


def sep(title: str = "") -> None:
    print(f"\n{'─' * 62}")
    if title:
        print(f"  {title}")
        print(f"{'─' * 62}")


def regime_table(trades: List[Trade]) -> List[Dict]:
    buckets: Dict[str, List[Trade]] = defaultdict(list)
    for t in trades:
        buckets[t.regime].append(t)

    rows = []
    for regime in KNOWN_REGIMES:
        ts = buckets.get(regime, [])
        if not ts:
            continue
        rets = [t.net for t in ts]
        wins = sum(1 for t in ts if t.is_win)
        pf   = profit_factor(rets)
        rows.append({
            "regime":        regime,
            "trades":        len(ts),
            "win_rate":      wins / len(ts) * 100,
            "profit_factor": pf,
            "net_pnl":       sum(rets),
            "avg_r":         sum(t.r_multiple for t in ts) / len(ts),
            "sharpe":        sharpe_ratio(rets),
            "max_dd_pct":    max_drawdown_pct(rets),
        })
    return sorted(rows, key=lambda r: r["net_pnl"], reverse=True)


def confidence_buckets(trades: List[Trade]) -> List[Dict]:
    """Agrupa trades por rango de confidence score (0-39, 40-54, 55-69, 70-84, 85-100)."""
    bands = [(0, 39), (40, 54), (55, 69), (70, 84), (85, 100)]
    rows = []
    for lo, hi in bands:
        ts = [t for t in trades
              if t.confidence is not None and lo <= t.confidence <= hi]
        if not ts:
            continue
        rets = [t.net for t in ts]
        wins = sum(1 for t in ts if t.is_win)
        rows.append({
            "band":          f"{lo}-{hi}",
            "trades":        len(ts),
            "win_rate":      wins / len(ts) * 100,
            "profit_factor": profit_factor(rets),
            "net_pnl":       sum(rets),
            "avg_r":         sum(t.r_multiple for t in ts) / len(ts),
        })
    return rows


def stress_test(trades: List[Trade]) -> Dict:
    """Simula escenarios adversos eliminando los mejores trades."""
    if not trades:
        return {}
    rets    = [t.net for t in trades]
    total   = sum(rets)
    sorted_ = sorted(rets, reverse=True)

    def net_without_top(n: int) -> float:
        return sum(sorted_[n:])

    return {
        "total_net":       total,
        "without_top1":    net_without_top(1),
        "without_top3":    net_without_top(3),
        "without_top5":    net_without_top(5),
        "without_top10":   net_without_top(10) if len(rets) >= 10 else None,
        "pct_from_top3":   (sum(sorted_[:3]) / total * 100) if total != 0 else 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Golden Trade X — Análisis estadístico por régimen"
    )
    parser.add_argument("files", nargs="*",
                        help="CSV files de TradeLogger. Auto-descubre GoldenTradeX_*.csv")
    parser.add_argument("--output", default="",
                        help="Ruta CSV para guardar tabla de regímenes")
    args = parser.parse_args()

    paths = list(args.files)
    if not paths:
        paths = sorted(
            glob.glob("GoldenTradeX_*.csv")
            + glob.glob("**/GoldenTradeX_*.csv", recursive=True)
        )
    if not paths:
        print("No se encontraron CSV. Ejecute el EA primero para generar datos.")
        sys.exit(1)

    trades: List[Trade] = []
    for p in paths:
        loaded = load_csv(p)
        print(f"  Cargados {len(loaded):>4} trades  ← {p}")
        trades.extend(loaded)

    if not trades:
        print("Sin trades válidos.")
        sys.exit(1)

    trades.sort(key=lambda t: (t.close_date, t.close_time))

    # ── 1. Tabla por régimen ───────────────────────────────────────────
    sep("RENDIMIENTO POR RÉGIMEN DE MERCADO")
    reg_rows = regime_table(trades)

    if reg_rows:
        print(f"  {'Régimen':<17} {'N':>5} {'WR%':>7} {'PF':>7} "
              f"{'NetP/L':>10} {'AvgR':>7} {'Sharpe':>7} {'MaxDD%':>8}")
        for r in reg_rows:
            print(
                f"  {r['regime']:<17} {r['trades']:>5} {r['win_rate']:>6.1f}%"
                f" {r['profit_factor']:>7.3f} {r['net_pnl']:>+10.2f}"
                f" {r['avg_r']:>+6.3f}R {r['sharpe']:>7.3f}"
                f" {r['max_dd_pct']:>7.1f}%"
            )
    else:
        print("  Sin datos de régimen. Asegúrese de usar GoldenTradeX v2.00+")

    # ── 2. Tabla por confidence score ─────────────────────────────────
    sep("RENDIMIENTO POR CONFIDENCE SCORE")
    conf_rows = confidence_buckets(trades)
    if conf_rows:
        print(f"  {'Score':>7} {'N':>5} {'WR%':>7} {'PF':>7} {'NetP/L':>10} {'AvgR':>7}")
        for r in conf_rows:
            print(
                f"  {r['band']:>7} {r['trades']:>5} {r['win_rate']:>6.1f}%"
                f" {r['profit_factor']:>7.3f} {r['net_pnl']:>+10.2f}"
                f" {r['avg_r']:>+6.3f}R"
            )
        # Recomendación de umbral óptimo
        best = max(conf_rows, key=lambda r: r["profit_factor"])
        print(f"\n  → Mejor PF en band {best['band']}: PF={best['profit_factor']:.3f}")
        print(f"    Umbral recomendado: InpMinConfidence = {best['band'].split('-')[0]}")
    else:
        print("  Sin datos de confidence. Asegúrese de usar GoldenTradeX v2.00+")

    # ── 3. Stress test ────────────────────────────────────────────────
    sep("STRESS TEST (eliminando trades extremos)")
    st = stress_test(trades)
    if st:
        print(f"  P/L total:                      {st['total_net']:>+10.2f}")
        print(f"  Sin el mejor trade:             {st['without_top1']:>+10.2f}")
        print(f"  Sin los 3 mejores:              {st['without_top3']:>+10.2f}")
        print(f"  Sin los 5 mejores:              {st['without_top5']:>+10.2f}")
        if st["without_top10"] is not None:
            print(f"  Sin los 10 mejores:             {st['without_top10']:>+10.2f}")
        print(f"  % P/L explicado por top 3:      {st['pct_from_top3']:>+9.1f}%")
        if st["pct_from_top3"] > 50:
            print("  ⚠  Más del 50% del P/L concentrado en 3 trades → riesgo de outlier.")

    # ── 4. Recomendaciones ────────────────────────────────────────────
    sep("RECOMENDACIONES")
    if reg_rows:
        losing = [r for r in reg_rows if r["net_pnl"] < 0]
        if losing:
            print("  Regímenes con pérdidas netas (considere desactivar entradas):")
            for r in losing:
                print(f"    - {r['regime']}: {r['net_pnl']:+.2f}  "
                      f"(PF={r['profit_factor']:.3f}, N={r['trades']})")
        winning = [r for r in reg_rows if r["profit_factor"] >= 1.8]
        if winning:
            print("  Regímenes con PF≥1.8 (optimar parámetros para estos):")
            for r in winning:
                print(f"    + {r['regime']}: PF={r['profit_factor']:.3f}  "
                      f"Net={r['net_pnl']:+.2f}")

    # ── 5. CSV output ─────────────────────────────────────────────────
    if args.output and reg_rows:
        with open(args.output, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=reg_rows[0].keys())
            writer.writeheader()
            writer.writerows(reg_rows)
        print(f"\n  Tabla de régimen guardada → {args.output}")


if __name__ == "__main__":
    main()
