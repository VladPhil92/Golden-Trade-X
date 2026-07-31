#!/usr/bin/env python3
"""
Golden Trade X — Statistical analysis of TradeLogger CSV exports.

Reads GoldenTradeX_*.csv (produced by TradeLogger.mqh) and computes:
  - Core metrics: win rate, profit factor, Sharpe, max drawdown, R-stats
  - Risk-adjusted metrics on % returns: Sharpe, Sortino, Calmar, Ulcer Index,
    Expected Shortfall, Probabilistic/Deflated Sharpe Ratio (v2.60)
  - Monte Carlo (default 1 000 runs): max-DD distribution, ruin probability.
    Supports block bootstrap (--block-size) to account for serial
    correlation/streaks that single-trade IID resampling misses.
  - Walk-forward table: rolling quarterly performance breakdown (NOT a
    train/test walk-forward optimization — see scripts/walk_forward_optimizer.py
    for that).
  - Internal quality targets check (PF>=1.8, Sharpe>=1.5, etc.) — these are
    this project's own thresholds, not an external institutional standard.

Usage:
    python scripts/backtest_analysis.py                        # auto-discover CSVs
    python scripts/backtest_analysis.py trades.csv            # specific file
    python scripts/backtest_analysis.py *.csv --mc-runs 2000  # multiple files
    python scripts/backtest_analysis.py --output report.csv   # save WF table
    python scripts/backtest_analysis.py --block-size 5        # block bootstrap
    python scripts/backtest_analysis.py --trials 20           # Deflated Sharpe
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
    """Legacy per-trade Sharpe — use daily_sharpe() for annualised accuracy."""
    n = len(returns)
    if n < 2:
        return 0.0
    mean = sum(returns) / n
    std = math.sqrt(sum((r - mean) ** 2 for r in returns) / (n - 1))
    return (mean / std) * math.sqrt(periods_per_year) if std else 0.0


def daily_sharpe(trades: List["Trade"], periods_per_year: int = 252) -> float:
    """Proper Sharpe: annualised on daily P&L buckets (sqrt-252 annualisation)."""
    daily: Dict[str, float] = defaultdict(float)
    for t in trades:
        daily[t.close_date] += t.net
    rets = list(daily.values())
    n = len(rets)
    if n < 2:
        return 0.0
    mean = sum(rets) / n
    std = math.sqrt(sum((r - mean) ** 2 for r in rets) / (n - 1))
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
    block_size: int = 1,
) -> Dict:
    """Bootstrap Monte Carlo over trade returns.

    block_size=1 (default) resamples individual trades — assumes
    independence between trades, which trend-following systems typically
    violate (streaks, regime clustering). block_size>1 uses a moving-block
    bootstrap: resamples contiguous blocks of `block_size` trades, which
    preserves short-range serial correlation and tends to widen the
    estimated drawdown distribution for systems with real streakiness.
    """
    rng = random.Random(seed)
    n = len(returns)
    block_size = max(1, min(block_size, n)) if n else 1
    dd_pcts: List[float] = []
    ruins = 0

    for _ in range(runs):
        if block_size <= 1:
            # v2.20: bootstrap (sampling with replacement) — not shuffle-only
            shuffled = [rng.choice(returns) for _ in range(n)]
        else:
            # v2.60: moving-block bootstrap — preserves local autocorrelation
            shuffled = []
            while len(shuffled) < n:
                start_idx = rng.randrange(0, n - block_size + 1)
                shuffled.extend(returns[start_idx:start_idx + block_size])
            shuffled = shuffled[:n]
        _, dd_pct = max_drawdown(equity_curve(shuffled, start))
        dd_pcts.append(dd_pct * 100)
        if dd_pct >= RUIN_THRESHOLD:
            ruins += 1

    dd_pcts.sort()
    n_dd = len(dd_pcts)

    def p(pct: float) -> float:
        return dd_pcts[min(int(pct / 100 * n_dd), n_dd - 1)]

    return {
        "runs": runs,
        "block_size": block_size,
        "dd_p5": p(5), "dd_p25": p(25), "dd_p50": p(50),
        "dd_p75": p(75), "dd_p95": p(95),
        "ruin_pct": ruins / runs * 100,
    }


# ── Risk-adjusted metrics on % returns (v2.60) ─────────────────────────────────
# The functions above (daily_sharpe, sharpe_ratio) operate on absolute P&L in
# account currency. That distorts comparisons when equity/lot size changes
# over the test (e.g. Kelly or the Equity Curve Filter resizing positions).
# These operate on PERIOD RETURNS (fractional, e.g. 0.01 = 1%) instead.

def daily_pct_returns(trades: List[Trade], start: float = 10_000.0) -> List[float]:
    """Daily P&L bucketed and expressed as a fraction of equity at day-start."""
    daily: Dict[str, float] = defaultdict(float)
    for t in trades:
        daily[t.close_date] += t.net
    equity = start
    rets: List[float] = []
    for day in sorted(daily.keys()):
        pnl = daily[day]
        if equity > 0:
            rets.append(pnl / equity)
        equity += pnl
    return rets


def sharpe_from_returns(returns: List[float], periods_per_year: int = 252) -> float:
    n = len(returns)
    if n < 2:
        return 0.0
    mean = sum(returns) / n
    std = math.sqrt(sum((r - mean) ** 2 for r in returns) / (n - 1))
    return (mean / std) * math.sqrt(periods_per_year) if std else 0.0


def sortino_ratio(returns: List[float], periods_per_year: int = 252,
                  mar: float = 0.0) -> float:
    """Like Sharpe, but penalizes only downside deviation below `mar`."""
    n = len(returns)
    if n < 2:
        return 0.0
    mean = sum(returns) / n
    downside_sq = sum(min(0.0, r - mar) ** 2 for r in returns)
    downside_dev = math.sqrt(downside_sq / n)
    return (mean / downside_dev) * math.sqrt(periods_per_year) if downside_dev else 0.0


def ulcer_index(curve: List[float]) -> float:
    """RMS of drawdown-%-from-peak over the whole curve — penalizes both
    depth and duration of drawdowns, unlike max_drawdown which only
    captures the single worst point."""
    if not curve:
        return 0.0
    peak = curve[0]
    sq_sum = 0.0
    for v in curve:
        peak = max(peak, v)
        dd_pct = (peak - v) / peak * 100 if peak > 0 else 0.0
        sq_sum += dd_pct ** 2
    return math.sqrt(sq_sum / len(curve))


def expected_shortfall(returns: List[float], alpha: float = 0.95) -> float:
    """Average return in the worst (1-alpha) tail — CVaR. More informative
    than a single max-DD point about how bad the bad days actually are."""
    if not returns:
        return 0.0
    sorted_r = sorted(returns)
    cutoff = max(1, int(len(sorted_r) * (1 - alpha)))
    worst = sorted_r[:cutoff]
    return sum(worst) / len(worst)


def annualized_return_pct(trades: List[Trade], curve: List[float]) -> float:
    """CAGR from first to last trade close date."""
    if len(trades) < 2 or len(curve) < 2 or curve[0] <= 0:
        return 0.0
    from datetime import date

    def parse(d: str):
        y, m, dd = map(int, d.split("-"))
        return date(y, m, dd)

    try:
        days = max((parse(trades[-1].close_date) - parse(trades[0].close_date)).days, 1)
    except (ValueError, IndexError):
        return 0.0
    years = days / 365.25
    growth = curve[-1] / curve[0]
    if growth <= 0 or years <= 0:
        return -100.0
    return (growth ** (1 / years) - 1) * 100


def calmar_ratio(annual_return_pct_: float, max_dd_pct: float) -> float:
    return annual_return_pct_ / max_dd_pct if max_dd_pct > 0 else float("inf")


def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def probabilistic_sharpe_ratio(returns: List[float], benchmark_sr: float = 0.0) -> float:
    """PSR (Bailey & López de Prado, 2012): probability that the TRUE Sharpe
    ratio exceeds `benchmark_sr`, correcting for skew/kurtosis and sample
    size. Operates on per-period (non-annualized) returns — the annualization
    factor cancels out of the PSR formula. PSR >= 0.95 is a common bar for
    "statistically significant edge at the 95% confidence level"."""
    n = len(returns)
    if n < 3:
        return 0.0
    mean = sum(returns) / n
    std = math.sqrt(sum((r - mean) ** 2 for r in returns) / (n - 1))
    if std == 0:
        return 0.0
    sr_hat = mean / std
    skew = sum(((r - mean) / std) ** 3 for r in returns) / n
    kurt = sum(((r - mean) / std) ** 4 for r in returns) / n
    denom_sq = 1 - skew * sr_hat + (kurt - 1) / 4 * sr_hat ** 2
    denom = math.sqrt(max(1e-12, denom_sq))
    z = (sr_hat - benchmark_sr) * math.sqrt(n - 1) / denom
    return _norm_cdf(z)


def deflated_sharpe_ratio(returns: List[float], num_trials: int = 1) -> float:
    """DSR: PSR against the expected maximum Sharpe achievable by chance
    across `num_trials` independent (skill-less) parameter combinations —
    corrects for selection bias from trying many configurations.

    NOTE: this uses a simplified approximation of the expected-max-of-N
    benchmark (sigma_SR * sqrt(2*ln(N)), dropping the smaller
    Euler-Mascheroni correction terms from the full closed form). For the
    exact estimator see Bailey & López de Prado (2014), "The Deflated
    Sharpe Ratio". num_trials=1 (default) reduces to plain PSR (benchmark=0)
    — pass the real number of parameter combinations you tried in
    optimization to get an honest, bias-corrected figure.
    """
    n = len(returns)
    if n < 3 or num_trials < 1:
        return probabilistic_sharpe_ratio(returns)
    mean = sum(returns) / n
    std = math.sqrt(sum((r - mean) ** 2 for r in returns) / (n - 1))
    if std == 0:
        return 0.0
    sr_hat = mean / std
    skew = sum(((r - mean) / std) ** 3 for r in returns) / n
    kurt = sum(((r - mean) / std) ** 4 for r in returns) / n
    se_sr_sq = max(1e-12, 1 - skew * sr_hat + (kurt - 1) / 4 * sr_hat ** 2) / (n - 1)
    se_sr = math.sqrt(se_sr_sq)
    sr_benchmark = 0.0 if num_trials <= 1 else se_sr * math.sqrt(2 * math.log(num_trials))
    return probabilistic_sharpe_ratio(returns, benchmark_sr=sr_benchmark)


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
    parser.add_argument(
        "--html-output", type=str, default="",
        help="Optional HTML path to save a self-contained analysis report",
    )
    parser.add_argument(
        "--block-size", type=int, default=1,
        help="Monte Carlo block bootstrap size in trades (default 1 = IID "
             "single-trade resampling; >1 preserves serial correlation/streaks)",
    )
    parser.add_argument(
        "--trials", type=int, default=1,
        help="Number of parameter combinations tried during optimization, "
             "for the Deflated Sharpe Ratio's multiple-testing correction "
             "(default 1 = no correction, equals plain PSR)",
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
    sharpe   = daily_sharpe(trades)    # v2.20: daily-bucket Sharpe with sqrt(252)
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

    # ── Risk-adjusted metrics on % returns (v2.60) ──────────────────────
    # Sharpe/Sortino/Calmar computed on daily % returns instead of absolute
    # P&L — avoids distortion when equity or lot size changes over the test
    # (Kelly, Equity Curve Filter). PSR/DSR add statistical confidence
    # bounds instead of a single point estimate.
    _sep("MÉTRICAS AJUSTADAS POR RIESGO (retornos %)")
    pct_rets   = daily_pct_returns(trades, args.start_equity)
    sharpe_pct = sharpe_from_returns(pct_rets)
    sortino    = sortino_ratio(pct_rets)
    cagr       = annualized_return_pct(trades, curve)
    calmar     = calmar_ratio(cagr, dd_pct * 100)
    ulcer      = ulcer_index(curve)
    es95       = expected_shortfall(returns) if returns else 0.0
    psr        = probabilistic_sharpe_ratio(pct_rets)
    dsr        = deflated_sharpe_ratio(pct_rets, num_trials=args.trials)
    calmar_str = f"{calmar:.3f}" if calmar != float("inf") else "Inf"
    for label, val in [
        ("Sharpe (retornos % diarios)", f"{sharpe_pct:.3f}"),
        ("Sortino (retornos %)",        f"{sortino:.3f}"),
        ("CAGR (retorno anualizado)",   f"{cagr:+.1f} %"),
        ("Calmar ratio",                calmar_str),
        ("Ulcer Index",                 f"{ulcer:.2f}"),
        ("Expected Shortfall (peor 5%)",f"{es95:+.2f}"),
        ("PSR (P[Sharpe real > 0])",    f"{psr*100:.1f} %"),
        (f"DSR (ajustado, trials={args.trials})", f"{dsr*100:.1f} %"),
    ]:
        print(f"  {label:<32} {val}")

    # ── Monte Carlo ────────────────────────────────────────────────────
    _sep(f"MONTE CARLO  ({args.mc_runs:,} simulaciones · bloque={args.block_size} · seed=42)")
    mc = monte_carlo(returns, runs=args.mc_runs, start=args.start_equity,
                     block_size=args.block_size)
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
    # v2.60: renamed from "objetivos institucionales" — these are this
    # project's own internal quality bars, not an external certification
    # or industry-wide institutional standard.
    _sep("OBJETIVOS INTERNOS DE CALIDAD (no es una certificación institucional)")
    checks = [
        ("Profit Factor ≥ 1.8",   pf >= 1.8,              f"{pf:.3f}"),
        ("Sharpe (%) ≥ 1.5",      sharpe_pct >= 1.5,      f"{sharpe_pct:.3f}"),
        ("Win rate ≥ 45 %",       wr >= 45,               f"{wr:.1f} %"),
        ("Max DD ≤ 15 %",         dd_pct <= 0.15,         f"{dd_pct*100:.1f} %"),
        ("MC DD P95 ≤ 25 %",      mc["dd_p95"] <= 25,     f"{mc['dd_p95']:.1f} %"),
        ("MC ruina < 5 %",        mc["ruin_pct"] < 5,     f"{mc['ruin_pct']:.1f} %"),
        ("Recovery factor ≥ 3",   rec_fac >= 3,           f"{rec_fac:.2f}"),
        ("Pérd. consec. ≤ 5",     max_cl <= 5,            f"{max_cl}"),
        ("PSR ≥ 95 % (confianza estadística)", psr >= 0.95, f"{psr*100:.1f} %"),
    ]
    all_pass = True
    for label, passed, val in checks:
        icon = "✓" if passed else "✗"
        all_pass = all_pass and passed
        print(f"  [{icon}] {label:<32} {val}")

    print()
    if all_pass:
        print("  >>> TODOS LOS OBJETIVOS INTERNOS SUPERADOS — listo para prueba en demo real <<<")
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

    # ── Optional HTML report ───────────────────────────────────────────
    if args.html_output:
        risk_adj = {
            "sharpe_pct": sharpe_pct, "sortino": sortino, "calmar": calmar,
            "ulcer": ulcer, "es95": es95, "psr": psr, "dsr": dsr,
        }
        html = _build_html_report(
            trades, returns, curve, wf_rows, mc, checks,
            pf, wr, sharpe, dd_pct, net_pnl, avg_r, max_cl, rec_fac,
            risk_adj,
        )
        with open(args.html_output, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"\n  HTML report saved → {args.html_output}")


# ── HTML report builder ────────────────────────────────────────────────────────

def _build_html_report(
    trades: List[Trade],
    returns: List[float],
    curve: List[float],
    wf_rows: List[Dict],
    mc: Dict,
    checks: list,
    pf: float, wr: float, sharpe: float, dd_pct: float,
    net_pnl: float, avg_r: float, max_cl: int, rec_fac: float,
    risk_adj: Dict = None,
) -> str:
    risk_adj = risk_adj or {}
    import datetime
    n = len(trades)
    today = datetime.date.today()

    # Equity curve SVG (pure SVG, no CDN)
    if len(curve) > 1:
        start_eq = curve[0]
        final_eq  = curve[-1]
        line_color = "#00c853" if final_eq >= start_eq else "#f44336"
        svg_w, svg_h, pad = 700, 160, 18
        min_y = min(curve)
        max_y = max(curve)
        ry = max_y - min_y or 1
        pts = " ".join(
            f"{pad + i / (len(curve) - 1) * (svg_w - 2*pad):.1f},"
            f"{svg_h - pad - (v - min_y) / ry * (svg_h - 2*pad):.1f}"
            for i, v in enumerate(curve)
        )
        svg_eq = (
            f'<svg viewBox="0 0 {svg_w} {svg_h}" style="width:100%;height:auto">'
            f'<polyline points="{pts}" fill="none" stroke="{line_color}" stroke-width="2"/>'
            f'</svg>'
        )
    else:
        svg_eq = "<p>No equity data</p>"

    # Walk-forward bar chart SVG
    def wf_svg() -> str:
        if not wf_rows:
            return "<p>Insufficient quarters for walk-forward</p>"
        n_bars = len(wf_rows)
        bar_w = max(18, 560 // n_bars)
        total_w = bar_w * n_bars + 40
        h = 110
        nets = [r["net_pnl"] for r in wf_rows]
        max_abs = max(abs(v) for v in nets) or 1
        mid = h // 2
        parts = []
        for i, r in enumerate(wf_rows):
            x = 20 + i * bar_w
            bar_h_val = abs(r["net_pnl"]) / max_abs * (mid - 12)
            color = "#00c853" if r["net_pnl"] >= 0 else "#f44336"
            y = mid - bar_h_val if r["net_pnl"] >= 0 else mid
            parts.append(f'<rect x="{x}" y="{y:.0f}" width="{bar_w-2}" '
                         f'height="{max(bar_h_val, 1):.0f}" fill="{color}" opacity="0.85"/>')
            parts.append(f'<text x="{x + bar_w//2}" y="{h-2}" text-anchor="middle" '
                         f'font-size="8" fill="#777">{r["window"][-4:]}</text>')
        parts.append(f'<line x1="20" y1="{mid}" x2="{total_w-20}" y2="{mid}" '
                     f'stroke="#444" stroke-width="1"/>')
        return (f'<svg viewBox="0 0 {total_w} {h}" style="width:100%;height:auto">'
                + "".join(parts) + "</svg>")

    checks_html = "".join(
        f'<tr><td style="color:{"#00c853" if ok else "#f44336"}">{"✓" if ok else "✗"}</td>'
        f'<td>{lbl}</td><td>{val}</td></tr>'
        for lbl, ok, val in checks
    )

    wf_rows_html = "".join(
        f"<tr><td>{r['window']}</td><td>{r['trades']}</td>"
        f"<td>{r['win_rate']:.1f}%</td><td>{r['profit_factor']:.3f}</td>"
        f"<td>{r['net_pnl']:+.2f}</td><td>{r['avg_r']:+.3f}R</td>"
        f"<td>{r['sharpe']:.3f}</td></tr>"
        for r in wf_rows
    )

    all_pass = all(ok for _, ok, _ in checks)
    verdict_color = "#00c853" if all_pass else "#f44336"
    verdict_text  = ("ALL TARGETS MET — Ready for live demo"
                     if all_pass else "Targets pending — optimize before live trading")
    pf_str = f"{pf:.3f}" if pf != float("inf") else "Inf"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>GTX Backtest Report {today}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#0f1117;color:#e0e0e0;font-family:monospace;font-size:13px;padding:20px;max-width:900px}}
h1{{color:#ffd700;font-size:17px;margin-bottom:3px}}
h2{{color:#90caf9;font-size:12px;margin:18px 0 6px;border-bottom:1px solid #2a2d34;padding-bottom:3px}}
.meta{{color:#666;font-size:11px;margin-bottom:16px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(155px,1fr));gap:8px;margin-bottom:14px}}
.kpi{{background:#161921;border:1px solid #252830;border-radius:5px;padding:9px}}
.kpi .lbl{{color:#666;font-size:10px}}
.kpi .val{{color:#ffd700;font-size:15px;font-weight:bold;margin-top:2px}}
table{{width:100%;border-collapse:collapse;font-size:12px;margin-bottom:10px}}
th{{background:#161921;color:#90caf9;padding:5px 7px;text-align:left}}
td{{padding:4px 7px;border-bottom:1px solid #1e2030}}
.mc{{display:grid;grid-template-columns:repeat(3,1fr);gap:7px;margin-bottom:12px}}
.mc-c{{background:#161921;border:1px solid #252830;border-radius:4px;padding:8px;text-align:center}}
.mc-c .lbl{{color:#666;font-size:10px}}
.mc-c .val{{font-size:13px;margin-top:2px}}
.verdict{{border:2px solid {verdict_color};border-radius:5px;padding:11px;
          margin-top:14px;color:{verdict_color};font-weight:bold;text-align:center}}
</style>
</head>
<body>
<h1>Golden Trade X — Backtest Analysis Report</h1>
<div class="meta">Generated: {today} | {n} trades | stdlib-only report (no CDN)</div>

<h2>KEY METRICS</h2>
<div class="grid">
  <div class="kpi"><div class="lbl">Net P/L</div><div class="val">{net_pnl:+.2f}</div></div>
  <div class="kpi"><div class="lbl">Win Rate</div><div class="val">{wr:.1f}%</div></div>
  <div class="kpi"><div class="lbl">Profit Factor</div><div class="val">{pf_str}</div></div>
  <div class="kpi"><div class="lbl">Sharpe Ratio</div><div class="val">{sharpe:.3f}</div></div>
  <div class="kpi"><div class="lbl">Max Drawdown</div><div class="val">{dd_pct*100:.1f}%</div></div>
  <div class="kpi"><div class="lbl">Avg R-Multiple</div><div class="val">{avg_r:+.3f}R</div></div>
  <div class="kpi"><div class="lbl">Recovery Factor</div><div class="val">{rec_fac:.2f}</div></div>
  <div class="kpi"><div class="lbl">Max Consec. Loss</div><div class="val">{max_cl}</div></div>
</div>

<h2>EQUITY CURVE</h2>
{svg_eq}

<h2>MONTE CARLO ({mc["runs"]:,} simulations · 40% ruin threshold)</h2>
<div class="mc">
  <div class="mc-c"><div class="lbl">P5 best case</div><div class="val">{mc["dd_p5"]:.1f}%</div></div>
  <div class="mc-c"><div class="lbl">P25</div><div class="val">{mc["dd_p25"]:.1f}%</div></div>
  <div class="mc-c"><div class="lbl">P50 median</div><div class="val">{mc["dd_p50"]:.1f}%</div></div>
  <div class="mc-c"><div class="lbl">P75</div><div class="val">{mc["dd_p75"]:.1f}%</div></div>
  <div class="mc-c"><div class="lbl">P95 worst case</div><div class="val">{mc["dd_p95"]:.1f}%</div></div>
  <div class="mc-c"><div class="lbl">Ruin probability</div><div class="val">{mc["ruin_pct"]:.1f}%</div></div>
</div>

<h2>WALK-FORWARD BY QUARTER</h2>
{wf_svg()}
<table>
<tr><th>Quarter</th><th>N</th><th>WR%</th><th>PF</th><th>Net P/L</th><th>Avg R</th><th>Sharpe</th></tr>
{wf_rows_html if wf_rows_html else '<tr><td colspan="7">Insufficient data</td></tr>'}
</table>

<h2>RISK-ADJUSTED METRICS (% returns)</h2>
<div class="mc">
  <div class="mc-c"><div class="lbl">Sharpe (%)</div><div class="val">{risk_adj.get("sharpe_pct", 0):.3f}</div></div>
  <div class="mc-c"><div class="lbl">Sortino</div><div class="val">{risk_adj.get("sortino", 0):.3f}</div></div>
  <div class="mc-c"><div class="lbl">Calmar</div><div class="val">{risk_adj.get("calmar", 0):.3f}</div></div>
  <div class="mc-c"><div class="lbl">Ulcer Index</div><div class="val">{risk_adj.get("ulcer", 0):.2f}</div></div>
  <div class="mc-c"><div class="lbl">PSR</div><div class="val">{risk_adj.get("psr", 0)*100:.1f}%</div></div>
  <div class="mc-c"><div class="lbl">DSR</div><div class="val">{risk_adj.get("dsr", 0)*100:.1f}%</div></div>
</div>

<h2>INTERNAL QUALITY TARGETS (not an institutional certification)</h2>
<table>
<tr><th></th><th>Target</th><th>Value</th></tr>
{checks_html}
</table>

<div class="verdict">{verdict_text}</div>
</body>
</html>"""


if __name__ == "__main__":
    main()
