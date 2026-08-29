#!/usr/bin/env python3
"""Validate Golden Trade X Strategy Tester presets and cross-preset invariants."""

import re
import sys
from pathlib import Path

REQUIRED = {
    # Identity / safety
    "InpMagicNumber", "InpTradeComment", "InpAllowRealTrading",
    # Signals
    "InpEmaFast", "InpEmaSlow", "InpRsiPeriod", "InpRsiUpper", "InpRsiLower",
    "InpRsiLongMin", "InpRsiShortMax", "InpTimeframe",
    "InpAtrPeriod", "InpAtrMinRatio", "InpAtrMaxRatio",
    "InpAdxPeriod", "InpAdxMinLevel",
    # HTF filter
    "InpUseHtfFilter", "InpHtfEmaPeriod",
    # Risk
    "InpRiskPercent", "InpMaxDailyDD", "InpMaxWeeklyDD",
    "InpMaxConsecLosses", "InpMaxPositions",
    "InpAtrSlMultiplier", "InpAtrTpMultiplier", "InpMaxSpreadPoints",
    "InpMinInitialRR",
    # Trailing / break-even
    "InpUseTrailing", "InpTrailAtrMult", "InpUseBreakEven", "InpBreakEvenR",
    # Sessions
    "InpUseSessionFilter", "InpStartHour", "InpEndHour",
    "InpCloseOnFriday", "InpFridayCloseHour",
    # News
    "InpUseNewsFilter", "InpNewsBufferBefore", "InpNewsBufferAfter",
    "InpNewsCalendarPolicy", "InpPauseForNews",
    # Logging
    "InpEnableTradeLog",
    # Confluence & Smart Money
    "InpUseRegimeFilter", "InpUseSmcFilter", "InpMinConfidence",
    # Advanced Risk
    "InpMaxMonthlyDD", "InpCpThresholdPct",
    # Kelly Criterion
    "InpUseKelly", "InpKellyFraction", "InpKellyMinTrades",
    # Order Manager
    "InpOrderMaxRetries", "InpOrderRetryDelay", "InpMinMarginLevel",
    # Portfolio Risk Cap
    "InpUsePortfolioCap", "InpMaxPortfolioRiskPct",
    # Confluence Score weights
    "InpConfWeightBase", "InpConfWeightRegime", "InpConfWeightSmc",
    "InpConfWeightHtf", "InpConfWeightFib",
    # Partial Take Profit
    "InpUsePartialTP", "InpPartialTPR", "InpPartialTPPct",
    # Equity Curve Filter
    "InpUseEqCurveFilter", "InpEqCurvePeriod",
    # Signal quality
    "InpMinTickVolume",
}

BOOLEAN_KEYS = {
    "InpAllowRealTrading",
    "InpUseHtfFilter", "InpUseTrailing", "InpUseBreakEven", "InpUseSessionFilter",
    "InpCloseOnFriday", "InpUseNewsFilter", "InpPauseForNews", "InpEnableTradeLog",
    "InpUseRegimeFilter", "InpUseSmcFilter", "InpUseKelly", "InpUsePortfolioCap",
    "InpUsePartialTP", "InpUseEqCurveFilter",
}

RANGE_CHECKS = {
    "InpMagicNumber":          (1, 2**63 - 1, True, True),
    "InpEmaFast":             (1, 1000, True, True),
    "InpEmaSlow":             (2, 2000, True, True),
    "InpRsiPeriod":           (2, 200, True, True),
    "InpRsiUpper":            (0, 100, False, True),
    "InpRsiLower":            (0, 100, False, True),
    "InpRsiLongMin":          (0, 100, False, True),
    "InpRsiShortMax":         (0, 100, False, True),
    "InpTimeframe":           (1, 43200, True, True),
    "InpAtrPeriod":           (2, 200, True, True),
    "InpRiskPercent":         (0, 10, False, False),
    "InpMaxDailyDD":          (0, 100, False, False),
    "InpMaxWeeklyDD":         (0, 100, False, False),
    "InpAtrMinRatio":         (0, 10, False, False),
    "InpAtrMaxRatio":         (0, 20, False, False),
    "InpAdxPeriod":           (2, 100, True, True),
    "InpAdxMinLevel":         (0, 100, False, True),
    "InpHtfEmaPeriod":        (2, 2000, True, True),
    "InpMaxConsecLosses":     (1, 100, True, True),
    "InpMaxPositions":        (1, 100, True, True),
    "InpAtrSlMultiplier":     (0, 20, False, False),
    "InpAtrTpMultiplier":     (0, 20, False, False),
    "InpMaxSpreadPoints":     (0, 100000, False, False),
    "InpMinInitialRR":        (0, 10, False, True),
    "InpTrailAtrMult":        (0, 20, False, False),
    "InpBreakEvenR":          (0, 10, False, False),
    "InpMinConfidence":       (0, 100, True, True),
    "InpMaxMonthlyDD":        (0, 100, False, False),
    "InpCpThresholdPct":      (0, 50, False, False),
    "InpKellyFraction":       (0.01, 1.0, False, True),
    "InpKellyMinTrades":      (10, 5000, True, True),
    "InpOrderMaxRetries":     (0, 10, True, True),
    "InpOrderRetryDelay":     (0, 10000, True, True),
    "InpMinMarginLevel":      (0, 10000, False, False),
    "InpMaxPortfolioRiskPct": (0.01, 20, False, True),
    "InpConfWeightBase":      (0, 100, True, True),
    "InpConfWeightRegime":    (0, 100, True, True),
    "InpConfWeightSmc":       (0, 100, True, True),
    "InpConfWeightHtf":       (0, 100, True, True),
    "InpConfWeightFib":       (0, 100, True, True),
    "InpPartialTPR":          (0, 10, False, False),
    "InpPartialTPPct":        (1, 99, False, True),
    "InpEqCurvePeriod":       (2, 200, True, True),
    "InpMinTickVolume":       (0, 10000, True, True),
    "InpStartHour":           (0, 23, True, True),
    "InpEndHour":             (0, 23, True, True),
    "InpFridayCloseHour":     (0, 23, True, True),
    "InpNewsBufferBefore":    (0, 240, True, True),
    "InpNewsBufferAfter":     (0, 480, True, True),
    "InpNewsCalendarPolicy":  (0, 2, True, True),
}

WEIGHT_KEYS = (
    "InpConfWeightBase", "InpConfWeightRegime", "InpConfWeightSmc",
    "InpConfWeightHtf", "InpConfWeightFib",
)


def parse_set(path: str | Path) -> dict[str, str]:
    params: dict[str, str] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith(";"):
                continue
            match = re.match(r"^(\w+)=(.+)$", line)
            if match:
                params[match.group(1)] = match.group(2).strip()
    return params


def _number(params: dict[str, str], key: str) -> float | None:
    try:
        return float(params[key])
    except (KeyError, ValueError):
        return None


def validate_params(params: dict[str, str], label: str) -> list[str]:
    errors: list[str] = []

    for key in sorted(REQUIRED - set(params)):
        errors.append(f"{label}: MISSING parameter: {key}")

    for key, (lo, hi, is_int, inclusive) in RANGE_CHECKS.items():
        if key not in params:
            continue
        raw = params[key]
        try:
            val = int(raw) if is_int else float(raw)
        except ValueError:
            errors.append(f"{label}: BAD VALUE for {key}: '{raw}' is not numeric")
            continue
        ok = (lo <= val <= hi) if inclusive else (lo < val < hi)
        if not ok:
            bracket = "[inclusive]" if inclusive else "[exclusive]"
            errors.append(f"{label}: OUT OF RANGE {key}={val} (expected {lo}..{hi} {bracket})")

    for key in sorted(BOOLEAN_KEYS):
        if key in params and params[key].lower() not in {"true", "false"}:
            errors.append(f"{label}: BAD BOOLEAN {key}={params[key]!r} (expected true/false)")

    if params.get("InpAllowRealTrading", "").lower() == "true":
        errors.append(
            f"{label}: InpAllowRealTrading must remain false before an explicit controlled-production review"
        )

    ema_fast = _number(params, "InpEmaFast")
    ema_slow = _number(params, "InpEmaSlow")
    if ema_fast is not None and ema_slow is not None and ema_fast >= ema_slow:
        errors.append(f"{label}: InpEmaFast must be < InpEmaSlow")

    rsi_lower = _number(params, "InpRsiLower")
    rsi_upper = _number(params, "InpRsiUpper")
    rsi_long_min = _number(params, "InpRsiLongMin")
    rsi_short_max = _number(params, "InpRsiShortMax")
    if rsi_lower is not None and rsi_upper is not None and rsi_lower >= rsi_upper:
        errors.append(f"{label}: InpRsiLower must be < InpRsiUpper")
    if None not in (rsi_lower, rsi_long_min, rsi_upper) and not (rsi_lower < rsi_long_min < rsi_upper):
        errors.append(f"{label}: InpRsiLongMin must lie strictly inside RSI lower/upper bounds")
    if None not in (rsi_lower, rsi_short_max, rsi_upper) and not (rsi_lower < rsi_short_max < rsi_upper):
        errors.append(f"{label}: InpRsiShortMax must lie strictly inside RSI lower/upper bounds")

    atr_min = _number(params, "InpAtrMinRatio")
    atr_max = _number(params, "InpAtrMaxRatio")
    if atr_min is not None and atr_max is not None and atr_min >= atr_max:
        errors.append(f"{label}: InpAtrMinRatio must be < InpAtrMaxRatio")

    dd_daily = _number(params, "InpMaxDailyDD")
    dd_weekly = _number(params, "InpMaxWeeklyDD")
    dd_monthly = _number(params, "InpMaxMonthlyDD")
    if None not in (dd_daily, dd_weekly, dd_monthly) and not (dd_daily <= dd_weekly <= dd_monthly):
        errors.append(f"{label}: drawdown limits must satisfy daily <= weekly <= monthly")

    # v2.62: BreakEvenR is expressed in immutable Initial R, while
    # AtrSlMultiplier is an ATR distance. They are intentionally not compared.

    if all(key in params for key in WEIGHT_KEYS):
        try:
            weight_sum = sum(int(params[key]) for key in WEIGHT_KEYS)
        except ValueError:
            weight_sum = -1
        if weight_sum != 100:
            errors.append(f"{label}: Confluence Score weights must sum to 100 (got {weight_sum})")

    return errors


def main() -> None:
    paths = [Path(p) for p in sys.argv[1:]]
    if not paths:
        print("Usage: validate_set.py <preset.set> [other-preset.set ...]")
        sys.exit(1)

    all_errors: list[str] = []
    parsed: list[tuple[Path, dict[str, str]]] = []

    for path in paths:
        try:
            params = parse_set(path)
        except FileNotFoundError:
            all_errors.append(f"{path}: file not found")
            continue
        parsed.append((path, params))
        all_errors.extend(validate_params(params, str(path)))

    magic_to_path: dict[int, Path] = {}
    for path, params in parsed:
        try:
            magic = int(params["InpMagicNumber"])
        except (KeyError, ValueError):
            continue
        if magic in magic_to_path:
            all_errors.append(
                f"duplicate InpMagicNumber={magic}: {magic_to_path[magic]} and {path}"
            )
        else:
            magic_to_path[magic] = path

    if all_errors:
        for error in all_errors:
            print(error)
        sys.exit(1)

    total_params = sum(len(params) for _, params in parsed)
    print(f"OK — {len(parsed)} preset(s), {total_params} parameters, magic numbers unique")


if __name__ == "__main__":
    main()
