#!/usr/bin/env python3
"""
Golden Trade X — Evaluación CONTINUA de desempeño (v2.51).

A diferencia de backtest_analysis.py (análisis puntual y profundo de un
backtest), este script está pensado para correr de forma recurrente sobre
los CSV que el EA genera en vivo/demo, y responder una pregunta:
¿el bot sigue funcionando como se espera, o se está degradando?

Qué evalúa:
  1. KPIs globales (win rate, profit factor, expectancy, DD, racha).
  2. VENTANA RECIENTE vs HISTÓRICO — los últimos N trades comparados con
     la línea base: detecta degradación antes de que duela.
  3. Breakdown por régimen de mercado y banda de confianza (columna
     Comment del TradeLogger >= v2.50) — qué filtros están aportando.
  4. Breakdown por hora y día de APERTURA (OpenDate/OpenTime).
  5. Alertas accionables con umbrales configurables. Exit code 1 si hay
     alertas → integrable en cron / Task Scheduler / CI.

Uso:
    python scripts/performance_report.py                    # auto-descubre CSVs
    python scripts/performance_report.py trades.csv
    python scripts/performance_report.py --window 20        # ventana reciente
    python scripts/performance_report.py --watch 300        # re-evalúa cada 5 min
    python scripts/performance_report.py --json out.json    # export para dashboard

Rutina recomendada:
    - En el VPS junto al EA:  --watch 300  (evaluación constante)
    - Semanal (manual):       revisar breakdown por régimen/confianza
    - Mensual:                backtest_analysis.py + walk_forward_optimizer.py
"""

import argparse
import glob
import json
import os
import sys
import time
from collections import defaultdict
from typing import Dict, List, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from backtest_analysis import (  # noqa: E402
    Trade,
    equity_curve,
    profit_factor,
)

# ── Umbrales de alerta (ajustables por CLI) ───────────────────────────────────
DEFAULT_WINDOW          = 20
MIN_TRADES_FOR_BASELINE = 30
WR_DEGRADATION_PTS      = 15.0
PF_ALERT                = 1.0
DD_ALERT_PCT            = 10.0
CONSEC_LOSS_ALERT       = 4


# ── Carga (schema v2.50: OpenDate/OpenTime/Comment opcionales) ────────────────

def load_trades(path: str) -> List[dict]:
    """Carga filas como dicts crudos + objeto Trade — conserva Comment/Open*."""
    import csv
    rows: List[dict] = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                t = Trade(
                    close_date=row["CloseDate"], close_time=row["CloseTime"],
                    position_id=row["PositionID"], symbol=row["Symbol"],
                    side=row["Type"], lots=float(row["Lots"]),
                    open_price=float(row["OpenPrice"]),
                    sl=float(row["InitialSL"]), tp=float(row["InitialTP"]),
                    close_price=float(row["ClosePrice"]),
                    pnl=float(row["ProfitLoss"]),
                    commission=float(row["Commission"]),
                    r_multiple=float(row["RMultiple"]),
                )
            except (KeyError, TypeError, ValueError):
                continue
            rows.append({
                "trade":     t,
                "comment":   row.get("Comment", ""),
                "open_date": row.get("OpenDate", ""),
                "open_time": row.get("OpenTime", ""),
            })
    return rows


def parse_confidence(comment: str) -> Optional[int]:
    for part in comment.split("|"):
        if part.startswith("Conf="):
            try:
                return int(part.split("=")[1])
            except ValueError:
                return None
    return None


def parse_regime(comment: str) -> str:
    for part in comment.split("|"):
        if part.startswith("Reg="):
            return part.split("=")[1].strip()
    return "N/D"


def open_hour(row: dict) -> Optional[int]:
    src = row["open_time"] or row["trade"].close_time
    try:
        return int(src.split(":")[0])
    except (ValueError, IndexError):
        return None


def open_weekday(row: dict) -> Optional[int]:
    from datetime import date
    src = row["open_date"] or row["trade"].close_date
    try:
        y, m, d = map(int, src.split("-"))
        return date(y, m, d).weekday()
    except Exception:
        return None


# ── Métricas de bloque ────────────────────────────────────────────────────────

def block_stats(trades: List[Trade]) -> Dict:
    if not trades:
        return {"n": 0}
    rets = [t.net for t in trades]
    wins = sum(1 for t in trades if t.is_win)
    consec = best_consec = 0
    for t in trades:
        consec = consec + 1 if not t.is_win else 0
        best_consec = max(best_consec, consec)
    return {
        "n":          len(trades),
        "win_rate":   wins / len(trades) * 100,
        "pf":         profit_factor(rets),
        "net":        sum(rets),
        "expectancy": sum(rets) / len(trades),
        "avg_r":      sum(t.r_multiple for t in trades) / len(trades),
        "consec_losses_end": consec,
        "max_consec_losses": best_consec,
    }


def current_drawdown_pct(trades: List[Trade], start: float = 10_000.0) -> float:
    """DD actual (desde el pico hasta HOY), no el máximo histórico."""
    curve = equity_curve([t.net for t in trades], start)
    peak = max(curve)
    return (peak - curve[-1]) / peak * 100 if peak > 0 else 0.0


# ── Evaluación ────────────────────────────────────────────────────────────────

def evaluate(rows: List[dict], window: int, args) -> Dict:
    trades = [r["trade"] for r in rows]
    result: Dict = {"total": block_stats(trades), "alerts": []}

    recent = trades[-window:]
    baseline = trades[:-window]
    result["recent"] = block_stats(recent)
    result["recent"]["window"] = min(window, len(trades))

    if len(baseline) >= MIN_TRADES_FOR_BASELINE and len(recent) >= window:
        base = block_stats(baseline)
        result["baseline"] = base
        wr_drop = base["win_rate"] - result["recent"]["win_rate"]
        if wr_drop >= args.wr_drop:
            result["alerts"].append(
                f"DEGRADACION: win rate reciente {result['recent']['win_rate']:.0f}% "
                f"vs baseline {base['win_rate']:.0f}% (caida {wr_drop:.0f} pts)")
        if result["recent"]["expectancy"] < 0 <= base["expectancy"]:
            result["alerts"].append(
                f"DEGRADACION: expectancy reciente negativa "
                f"({result['recent']['expectancy']:+.2f}/trade vs "
                f"{base['expectancy']:+.2f} historico)")

    if result["recent"]["n"] >= 5 and result["recent"]["pf"] < args.pf_alert:
        result["alerts"].append(
            f"PF reciente {result['recent']['pf']:.2f} < {args.pf_alert} "
            f"(ultimos {result['recent']['n']} trades)")

    dd_now = current_drawdown_pct(trades)
    result["dd_now_pct"] = dd_now
    if dd_now >= args.dd_alert:
        result["alerts"].append(
            f"DRAWDOWN actual {dd_now:.1f}% >= {args.dd_alert}% desde el pico")

    if result["recent"]["consec_losses_end"] >= args.consec_alert:
        result["alerts"].append(
            f"RACHA ABIERTA de {result['recent']['consec_losses_end']} perdidas "
            f"consecutivas")

    by_regime: Dict[str, List[Trade]] = defaultdict(list)
    for r in rows:
        by_regime[parse_regime(r["comment"])].append(r["trade"])
    result["by_regime"] = {k: block_stats(v) for k, v in by_regime.items()}

    by_conf: Dict[str, List[Trade]] = defaultdict(list)
    for r in rows:
        c = parse_confidence(r["comment"])
        band = "N/D" if c is None else f"{(c // 10) * 10}-{(c // 10) * 10 + 9}"
        by_conf[band].append(r["trade"])
    result["by_confidence"] = {k: block_stats(v) for k, v in by_conf.items()}

    by_hour: Dict[int, List[Trade]] = defaultdict(list)
    by_day: Dict[int, List[Trade]] = defaultdict(list)
    for r in rows:
        h = open_hour(r)
        d = open_weekday(r)
        if h is not None:
            by_hour[h].append(r["trade"])
        if d is not None:
            by_day[d].append(r["trade"])
    result["by_hour"] = {k: block_stats(v) for k, v in sorted(by_hour.items())}
    result["by_day"] = {k: block_stats(v) for k, v in sorted(by_day.items())}

    return result


# ── Presentación ──────────────────────────────────────────────────────────────

DAY_NAMES = ["Lun", "Mar", "Mie", "Jue", "Vie", "Sab", "Dom"]


def _fmt_block(label: str, s: Dict) -> str:
    if s.get("n", 0) == 0:
        return f"  {label:<18} sin trades"
    pf = s["pf"]
    pf_str = f"{pf:.2f}" if pf != float("inf") else "inf"
    return (f"  {label:<18} n={s['n']:<4} WR={s['win_rate']:5.1f}%  PF={pf_str:<6} "
            f"net={s['net']:+9.2f}  E[x]={s['expectancy']:+7.2f}  "
            f"avgR={s['avg_r']:+.2f}")


def print_report(res: Dict, args) -> None:
    line = "─" * 74
    print(f"\n{line}")
    print(f"  GOLDEN TRADE X — EVALUACIÓN DE DESEMPEÑO   "
          f"{time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(line)

    print("\n  GLOBAL")
    print(_fmt_block("todos", res["total"]))
    print(f"  {'drawdown actual':<18} {res['dd_now_pct']:.1f}% desde el pico")

    print(f"\n  VENTANA RECIENTE (últimos {res['recent'].get('window', 0)} trades)")
    print(_fmt_block("reciente", res["recent"]))
    if "baseline" in res:
        print(_fmt_block("baseline", res["baseline"]))
    else:
        print(f"  (baseline no disponible: se requieren "
              f">= {MIN_TRADES_FOR_BASELINE} trades históricos)")

    def _print_breakdown(title: str, d: Dict, key_fmt=str) -> None:
        rows = {k: v for k, v in d.items() if v.get("n", 0) > 0}
        if not rows:
            return
        print(f"\n  {title}")
        for k, v in rows.items():
            print(_fmt_block(key_fmt(k), v))

    _print_breakdown("POR RÉGIMEN DE MERCADO", res["by_regime"])
    _print_breakdown("POR BANDA DE CONFIANZA", res["by_confidence"])
    _print_breakdown("POR HORA DE APERTURA (servidor)", res["by_hour"],
                     key_fmt=lambda h: f"{h:02d}:00")
    _print_breakdown("POR DÍA DE APERTURA", res["by_day"],
                     key_fmt=lambda d: DAY_NAMES[d] if 0 <= d < 7 else str(d))

    print(f"\n{line}")
    if res["alerts"]:
        print(f"  ⚠ {len(res['alerts'])} ALERTA(S):")
        for a in res["alerts"]:
            print(f"    • {a}")
    else:
        print("  ✓ Sin alertas — desempeño dentro de parámetros.")
    print(line)


# ── Entry point ───────────────────────────────────────────────────────────────

def discover_csvs(directory: str) -> List[str]:
    return sorted(
        glob.glob(os.path.join(directory, "GoldenTradeX_*.csv"))
        + glob.glob(os.path.join(directory, "**", "GoldenTradeX_*.csv"), recursive=True)
    )


def run_once(paths: List[str], args) -> int:
    rows: List[dict] = []
    for p in paths:
        loaded = load_trades(p)
        print(f"  {len(loaded):>4} trades ← {p}")
        rows.extend(loaded)
    if not rows:
        print("  Sin trades válidos todavía.")
        return 0

    rows.sort(key=lambda r: (r["trade"].close_date, r["trade"].close_time))
    res = evaluate(rows, args.window, args)
    print_report(res, args)

    if args.json:
        serializable = {k: v for k, v in res.items()}
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(serializable, f, indent=2, ensure_ascii=False, default=str)
        print(f"  JSON → {args.json}")

    return 1 if res["alerts"] else 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Golden Trade X — evaluación continua de desempeño")
    parser.add_argument("files", nargs="*",
                        help="CSVs de TradeLogger (auto-descubre si se omite)")
    parser.add_argument("--dir", default=".",
                        help="Directorio a escanear (Common\\Files del terminal)")
    parser.add_argument("--window", type=int, default=DEFAULT_WINDOW,
                        help=f"Trades de la ventana reciente (default {DEFAULT_WINDOW})")
    parser.add_argument("--watch", type=int, default=0, metavar="SEG",
                        help="Re-evaluar cada SEG segundos (0 = una sola vez)")
    parser.add_argument("--json", default="",
                        help="Ruta para exportar el resultado como JSON")
    parser.add_argument("--wr-drop", type=float, default=WR_DEGRADATION_PTS,
                        help="Alerta si el WR reciente cae N pts vs baseline")
    parser.add_argument("--pf-alert", type=float, default=PF_ALERT,
                        help="Alerta si el PF reciente es menor a este valor")
    parser.add_argument("--dd-alert", type=float, default=DD_ALERT_PCT,
                        help="Alerta si el DD actual supera este %%")
    parser.add_argument("--consec-alert", type=int, default=CONSEC_LOSS_ALERT,
                        help="Alerta con esta racha de pérdidas abierta")
    args = parser.parse_args()

    paths = list(args.files) or discover_csvs(args.dir)
    if not paths:
        print("No se encontraron CSVs GoldenTradeX_*.csv. "
              "Ejecuta el EA (o pasa una ruta) para generar datos.")
        sys.exit(1)

    if args.watch > 0:
        print(f"Modo watch: re-evaluando cada {args.watch}s (Ctrl+C para salir)")
        try:
            while True:
                run_once(list(args.files) or discover_csvs(args.dir), args)
                time.sleep(args.watch)
        except KeyboardInterrupt:
            print("\nMonitor detenido.")
            sys.exit(0)
    else:
        sys.exit(run_once(paths, args))


if __name__ == "__main__":
    main()
