#!/usr/bin/env python3
"""
Golden Trade X v2.00 — Correlation Engine.

Downloads XAUUSD and macro proxies (DXY, VIX, US10Y, SP500) via yfinance,
calculates rolling correlations, and generates actionable trading insights.

Insights:
  - DXY inverse correlation to XAUUSD (dollar strength = gold weakness)
  - VIX positive correlation (fear = gold demand)
  - US10Y inverse correlation (real yields = gold opportunity cost)
  - SP500 correlation regime (risk-on vs risk-off)

Usage:
    python scripts/correlation_engine.py
    python scripts/correlation_engine.py --period 2y --window 30
    python scripts/correlation_engine.py --output corr_report.csv
    python scripts/correlation_engine.py --no-download  # use cached data

Requires:
    pip install yfinance
"""

import argparse
import csv
import math
import sys
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

try:
    import yfinance as yf
    _YF_OK = True
except ImportError:
    _YF_OK = False

TICKERS = {
    "XAUUSD": "GC=F",      # Gold Futures (CME)
    "DXY":    "DX-Y.NYB",  # US Dollar Index
    "VIX":    "^VIX",      # CBOE Volatility Index
    "US10Y":  "^TNX",      # 10-Year Treasury Yield
    "SP500":  "^GSPC",    # S&P 500
}

CACHE_FILE = "corr_cache.csv"


# ── Data loading ────────────────────────────────────────────────────────────────

def download_data(period: str = "2y") -> Dict[str, List[Tuple[str, float]]]:
    """Returns {name: [(date_str, close), ...]} sorted ascending."""
    if not _YF_OK:
        print("ERROR: yfinance not installed. Run: pip install yfinance")
        sys.exit(1)

    data: Dict[str, List[Tuple[str, float]]] = {}
    for name, ticker in TICKERS.items():
        print(f"  Downloading {name} ({ticker}) ...")
        try:
            df = yf.download(ticker, period=period, auto_adjust=True, progress=False)
            if df.empty:
                print(f"  WARNING: no data for {ticker}")
                data[name] = []
                continue
            series = []
            for dt, row in df.iterrows():
                close = float(row["Close"])
                if not math.isnan(close):
                    series.append((str(dt.date()), close))
            data[name] = sorted(series)
        except Exception as e:
            print(f"  WARNING: failed to download {ticker}: {e}")
            data[name] = []

    # Cache to CSV for offline use
    _write_cache(data)
    return data


def _write_cache(data: Dict[str, List[Tuple[str, float]]]) -> None:
    all_dates = sorted(set(d for series in data.values() for d, _ in series))
    with open(CACHE_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["date"] + list(TICKERS.keys()))
        writer.writeheader()
        lookup = {name: dict(series) for name, series in data.items()}
        for dt in all_dates:
            row = {"date": dt}
            for name in TICKERS:
                row[name] = lookup[name].get(dt, "")
            writer.writerow(row)


def load_cache() -> Dict[str, List[Tuple[str, float]]]:
    data: Dict[str, List[Tuple[str, float]]] = defaultdict(list)
    with open(CACHE_FILE, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            dt = row["date"]
            for name in TICKERS:
                raw = row.get(name, "")
                if raw:
                    try:
                        data[name].append((dt, float(raw)))
                    except ValueError:
                        pass
    return dict(data)


# ── Math helpers ────────────────────────────────────────────────────────────────

def returns(series: List[Tuple[str, float]]) -> List[Tuple[str, float]]:
    """Daily log-returns: (date, log_return)."""
    out = []
    for i in range(1, len(series)):
        dt, cur = series[i]
        _, prev = series[i - 1]
        if prev > 0:
            out.append((dt, math.log(cur / prev)))
    return out


def align(a: List[Tuple[str, float]], b: List[Tuple[str, float]]) -> Tuple[List[float], List[float]]:
    """Return aligned value lists for dates present in both series."""
    db = dict(b)
    xs, ys = [], []
    for dt, va in a:
        if dt in db:
            xs.append(va)
            ys.append(db[dt])
    return xs, ys


def pearson(xs: List[float], ys: List[float]) -> Optional[float]:
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx  = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy  = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


def rolling_corr(
    a: List[Tuple[str, float]],
    b: List[Tuple[str, float]],
    window: int,
) -> List[Tuple[str, float]]:
    """Rolling Pearson correlation over aligned dates."""
    da = dict(a)
    dates = sorted(set(d for d, _ in a) & set(d for d, _ in b))
    ab = [(dt, da.get(dt), dict(b).get(dt)) for dt in dates]
    out = []
    for i in range(window - 1, len(ab)):
        chunk = ab[i - window + 1: i + 1]
        xs = [v[1] for v in chunk if v[1] is not None and v[2] is not None]
        ys = [v[2] for v in chunk if v[1] is not None and v[2] is not None]
        r = pearson(xs, ys)
        if r is not None:
            out.append((ab[i][0], r))
    return out


# ── Analysis ────────────────────────────────────────────────────────────────────

def correlation_summary(data: Dict[str, List[Tuple[str, float]]], window: int) -> List[Dict]:
    """Full-period Pearson + rolling stats for each macro vs XAUUSD."""
    gold_ret = returns(data.get("XAUUSD", []))
    rows = []
    for name in ["DXY", "VIX", "US10Y", "SP500"]:
        series = data.get(name, [])
        if not series:
            continue
        other_ret = returns(series)
        xs, ys = align(gold_ret, other_ret)
        full_r = pearson(xs, ys)

        roll = rolling_corr(gold_ret, other_ret, window)
        if roll:
            roll_vals = [r for _, r in roll]
            roll_mean = sum(roll_vals) / len(roll_vals)
            roll_min  = min(roll_vals)
            roll_max  = max(roll_vals)
            roll_last = roll_vals[-1]
        else:
            roll_mean = roll_min = roll_max = roll_last = None

        rows.append({
            "pair":       f"XAUUSD/{name}",
            "n_days":     len(xs),
            "full_r":     full_r,
            "roll_mean":  roll_mean,
            "roll_min":   roll_min,
            "roll_max":   roll_max,
            "roll_last":  roll_last,
            "window":     window,
        })
    return rows


def regime_breakdown(
    data: Dict[str, List[Tuple[str, float]]],
    window: int,
) -> Dict[str, Dict]:
    """Segment rolling-corr history into 4 regimes by DXY trend."""
    gold_ret = returns(data.get("XAUUSD", []))
    dxy_ret  = returns(data.get("DXY", []))
    roll = rolling_corr(gold_ret, dxy_ret, window)
    if not roll:
        return {}

    # classify each window as DXY UP (>0) or DOWN (<0) using DXY returns
    dxy_dict = dict(dxy_ret)
    buckets: Dict[str, List[float]] = defaultdict(list)
    for dt, r in roll:
        dxy_r = dxy_dict.get(dt, 0)
        key = "DXY_UP" if dxy_r > 0 else "DXY_DOWN"
        buckets[key].append(r)

    result = {}
    for key, vals in buckets.items():
        n = len(vals)
        mean = sum(vals) / n
        result[key] = {"n": n, "mean_corr": mean,
                       "min": min(vals), "max": max(vals)}
    return result


def trading_signals(rows: List[Dict]) -> List[str]:
    """Generate actionable signals based on current rolling correlations."""
    signals = []
    lookup = {r["pair"].split("/")[1]: r for r in rows}

    dxy_last = lookup.get("DXY", {}).get("roll_last")
    vix_last = lookup.get("VIX", {}).get("roll_last")
    us10y_last = lookup.get("US10Y", {}).get("roll_last")
    sp500_last = lookup.get("SP500", {}).get("roll_last")

    if dxy_last is not None:
        if dxy_last < -0.5:
            signals.append("STRONG INVERSE DXY: strong negative corr — DXY weakness = gold tailwind")
        elif dxy_last > -0.2:
            signals.append("WEAK DXY INVERSE: correlation near zero — DXY/gold decoupled, reduce weight")

    if vix_last is not None:
        if vix_last > 0.4:
            signals.append("RISK-OFF SIGNAL: VIX positively correlated — flight-to-safety active")
        elif vix_last < 0:
            signals.append("RISK-ON: VIX inverse corr — unusual, monitor for regime shift")

    if us10y_last is not None:
        if us10y_last < -0.4:
            signals.append("REAL YIELD PRESSURE: US10Y inversely correlated — rate rises headwind for gold")
        elif us10y_last > 0.2:
            signals.append("STAGFLATION REGIME: US10Y positive corr — both rising, inflationary environment")

    if sp500_last is not None:
        if sp500_last < -0.3:
            signals.append("SAFE HAVEN: SP500 negative corr — gold acting as portfolio hedge")
        elif sp500_last > 0.4:
            signals.append("RISK-ON RALLY: SP500 positive corr — gold driven by global growth expectations")

    return signals


# ── Output ──────────────────────────────────────────────────────────────────────

def sep(title: str = "") -> None:
    print(f"\n{'─' * 64}")
    if title:
        print(f"  {title}")
        print(f"{'─' * 64}")


def _fmt(v: Optional[float], decimals: int = 3) -> str:
    if v is None:
        return "  N/A"
    return f"{v:+.{decimals}f}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Golden Trade X — Macro Correlation Engine"
    )
    parser.add_argument("--period",  default="2y",
                        help="yfinance period string (1y, 2y, 5y — default 2y)")
    parser.add_argument("--window",  type=int, default=30,
                        help="Rolling correlation window in trading days (default 30)")
    parser.add_argument("--output",  default="",
                        help="Optional CSV path to save correlation summary")
    parser.add_argument("--no-download", action="store_true",
                        help="Load from cached corr_cache.csv instead of downloading")
    args = parser.parse_args()

    sep("GOLDEN TRADE X — MACRO CORRELATION ENGINE")

    if args.no_download:
        try:
            data = load_cache()
            print(f"  Loaded from cache: {CACHE_FILE}")
        except FileNotFoundError:
            print(f"  ERROR: cache file not found ({CACHE_FILE}). Run without --no-download first.")
            sys.exit(1)
    else:
        print(f"  Fetching {len(TICKERS)} instruments for period={args.period} ...")
        data = download_data(args.period)
        print(f"  Data cached to {CACHE_FILE}")

    rows = correlation_summary(data, args.window)

    # ── Full-period correlations ────────────────────────────────────
    sep(f"PEARSON CORRELATION vs XAUUSD  (daily log-returns, rolling={args.window}d)")
    print(f"  {'Pair':<15} {'N':>6} {'Full-R':>8} {'Roll-Mean':>10} "
          f"{'Roll-Min':>9} {'Roll-Max':>9} {'Roll-Last':>10}")
    for r in rows:
        print(
            f"  {r['pair']:<15} {r['n_days']:>6} "
            f"{_fmt(r['full_r']):>8} "
            f"{_fmt(r['roll_mean']):>10} "
            f"{_fmt(r['roll_min']):>9} "
            f"{_fmt(r['roll_max']):>9} "
            f"{_fmt(r['roll_last']):>10}"
        )

    # ── DXY regime breakdown ────────────────────────────────────────
    sep("CORRELATION BREAKDOWN BY DXY DIRECTION")
    rb = regime_breakdown(data, args.window)
    if rb:
        for key, stats in sorted(rb.items()):
            print(f"  {key:<12} n={stats['n']:>4}  mean_corr={stats['mean_corr']:+.3f}"
                  f"  range=[{stats['min']:+.3f}, {stats['max']:+.3f}]")
    else:
        print("  Insufficient data for regime breakdown.")

    # ── Actionable signals ─────────────────────────────────────────
    sep("ACTIONABLE SIGNALS (based on current rolling window)")
    signals = trading_signals(rows)
    if signals:
        for s in signals:
            print(f"  ► {s}")
    else:
        print("  No strong signals — correlations near historical norms.")

    # ── Interpretation guide ───────────────────────────────────────
    sep("INTERPRETATION GUIDE")
    print("  r < -0.5  → Strong inverse: use as confirming filter")
    print("  -0.5..0   → Weak inverse: partial weight only")
    print("  0..+0.3   → Decoupled: ignore this macro factor")
    print("  > +0.3    → Positive: unusual — check for regime shift")
    print()
    print("  Suggested use in GoldenTradeX:")
    print("  - DXY roll_last < -0.4 AND VIX roll_last > 0.3 → raise InpMinConfidence by 5")
    print("  - DXY roll_last > -0.2                         → tighten session filter")
    print("  - US10Y roll_last < -0.5                       → beware of rate-driven reversal")

    # ── CSV output ─────────────────────────────────────────────────
    if args.output and rows:
        fields = ["pair", "n_days", "full_r", "roll_mean", "roll_min", "roll_max", "roll_last", "window"]
        with open(args.output, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        print(f"\n  Correlation summary saved → {args.output}")


if __name__ == "__main__":
    main()
