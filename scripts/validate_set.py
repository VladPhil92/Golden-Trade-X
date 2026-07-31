#!/usr/bin/env python3
"""Validates that GoldenTradeX.set contains all required EA input parameters."""

import sys
import re

REQUIRED = {
    # Identity
    "InpMagicNumber", "InpTradeComment",
    # Signals
    "InpEmaFast", "InpEmaSlow", "InpRsiPeriod", "InpRsiUpper", "InpRsiLower",
    "InpRsiLongMin", "InpRsiShortMax", "InpTimeframe",
    "InpAtrPeriod", "InpAtrMinRatio", "InpAtrMaxRatio", "InpAdxMinLevel",
    # HTF filter
    "InpUseHtfFilter", "InpHtfEmaPeriod",
    # Risk
    "InpRiskPercent", "InpMaxDailyDD", "InpMaxWeeklyDD",
    "InpMaxConsecLosses", "InpMaxPositions",
    "InpAtrSlMultiplier", "InpAtrTpMultiplier", "InpMaxSpreadPoints",
    # Trailing / break-even
    "InpUseTrailing", "InpTrailAtrMult", "InpUseBreakEven", "InpBreakEvenR",
    # Sessions
    "InpUseSessionFilter", "InpStartHour", "InpEndHour",
    "InpCloseOnFriday", "InpFridayCloseHour",
    # News
    "InpUseNewsFilter", "InpNewsBufferBefore", "InpNewsBufferAfter", "InpPauseForNews",
    # Logging
    "InpEnableTradeLog",
    # v2.00 — Ensemble & Smart Money
    "InpUseRegimeFilter", "InpUseSmcFilter", "InpMinConfidence",
    # v2.00 — Advanced Risk
    "InpMaxMonthlyDD", "InpCpThresholdPct",
    # v2.40 — Kelly Criterion
    "InpUseKelly", "InpKellyFraction", "InpKellyMinTrades",
    # v2.30 — Order Manager
    "InpOrderMaxRetries", "InpOrderRetryDelay", "InpMinMarginLevel",
    # v2.60 — Portfolio Risk Cap
    "InpUsePortfolioCap", "InpMaxPortfolioRiskPct",
    # v2.60 — Confluence Score weights (heurístico, configurable)
    "InpConfWeightBase", "InpConfWeightRegime", "InpConfWeightSmc",
    "InpConfWeightHtf", "InpConfWeightFib",
    # v2.20 — Partial Take Profit
    "InpUsePartialTP", "InpPartialTPR", "InpPartialTPPct",
    # v2.20 — Equity Curve Filter
    "InpUseEqCurveFilter", "InpEqCurvePeriod",
    # v2.20 — Signal quality
    "InpMinTickVolume",
}

RANGE_CHECKS = {
    "InpRiskPercent":       (0, 10, False, True),
    "InpMaxDailyDD":        (0, 100, False, True),
    "InpMaxWeeklyDD":       (0, 100, False, True),
    "InpAtrMinRatio":       (0, 10, False, True),
    "InpAtrMaxRatio":       (0, 20, False, True),
    "InpAtrSlMultiplier":   (0, 20, False, True),
    "InpAtrTpMultiplier":   (0, 20, False, True),
    "InpBreakEvenR":        (0, 10, False, True),
    "InpMinConfidence":     (0, 100, True, True),
    "InpMaxMonthlyDD":      (0, 100, False, True),
    "InpCpThresholdPct":    (0, 50, False, True),
    "InpKellyFraction":     (0.01, 1.0, False, True),
    "InpKellyMinTrades":    (10, 500, True, True),
    "InpOrderMaxRetries":   (0, 10, True, True),
    "InpOrderRetryDelay":   (0, 10000, True, True),
    "InpMinMarginLevel":    (0, 10000, False, True),
    "InpMaxPortfolioRiskPct": (0.01, 20, False, True),
    "InpConfWeightBase":    (0, 100, True, True),
    "InpConfWeightRegime":  (0, 100, True, True),
    "InpConfWeightSmc":     (0, 100, True, True),
    "InpConfWeightHtf":     (0, 100, True, True),
    "InpConfWeightFib":     (0, 100, True, True),
    "InpPartialTPR":        (0, 10, False, True),
    "InpPartialTPPct":      (1, 99, False, True),
    "InpEqCurvePeriod":     (2, 200, True, True),
    "InpMinTickVolume":     (0, 10000, True, True),
    "InpStartHour":         (0, 23, True,  True),
    "InpEndHour":           (0, 23, True,  True),
    "InpFridayCloseHour":   (0, 23, True,  True),
    "InpNewsBufferBefore":  (0, 240, True,  True),
    "InpNewsBufferAfter":   (0, 480, True,  True),
}


def parse_set(path):
    params = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith(";"):
                continue
            m = re.match(r"^(\w+)=(.+)$", line)
            if m:
                params[m.group(1)] = m.group(2).strip()
    return params


def main():
    if len(sys.argv) < 2:
        print("Usage: validate_set.py <path/to/GoldenTradeX.set>")
        sys.exit(1)

    path = sys.argv[1]
    try:
        params = parse_set(path)
    except FileNotFoundError:
        print(f"ERROR: file not found: {path}")
        sys.exit(1)

    errors = []

    # Presence check
    missing = REQUIRED - set(params.keys())
    for key in sorted(missing):
        errors.append(f"MISSING parameter: {key}")

    # Range checks
    for key, (lo, hi, is_int, inclusive) in RANGE_CHECKS.items():
        if key not in params:
            continue
        raw = params[key]
        try:
            val = int(raw) if is_int else float(raw)
        except ValueError:
            errors.append(f"BAD VALUE for {key}: '{raw}' is not numeric")
            continue
        ok = (lo <= val <= hi) if inclusive else (lo < val < hi)
        if not ok:
            errors.append(f"OUT OF RANGE {key}={val} (expected {lo}..{hi})")

    if errors:
        for e in errors:
            print(e)
        sys.exit(1)

    print(f"OK — {len(params)} parameters validated in {path}")


if __name__ == "__main__":
    main()
