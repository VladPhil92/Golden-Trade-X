#!/usr/bin/env python3
"""Daily trading-activity metrics for Golden Trade X v3.1 research.

This module measures participation; it never promotes a strategy and never infers edge.
The denominator is an explicit set of eligible trading dates. By default that is Monday
through Friday in the requested half-open interval [start_date, end_date). A caller may
provide a newline-delimited trading-day file to use an exact broker/session calendar.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Sequence


class ActivityMetricsError(ValueError):
    """Raised when activity evidence is incomplete or inconsistent."""


@dataclass(frozen=True)
class TradeActivity:
    entry_utc: datetime
    symbol: str
    setup: str


def _parse_utc(raw: str) -> datetime:
    value = raw.strip()
    if not value:
        raise ActivityMetricsError("entry timestamp is empty")
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ActivityMetricsError(f"invalid ISO entry timestamp: {raw!r}") from exc
    if parsed.tzinfo is None:
        raise ActivityMetricsError("entry timestamp must include UTC offset")
    return parsed.astimezone(timezone.utc)


def load_trades_csv(
    path: str | Path,
    *,
    entry_column: str = "entry_utc",
    symbol_column: str = "symbol",
    setup_column: str = "setup",
) -> list[TradeActivity]:
    source = Path(path)
    if not source.is_file():
        raise ActivityMetricsError(f"trade file not found: {source}")
    with source.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or entry_column not in reader.fieldnames:
            raise ActivityMetricsError(f"missing required column: {entry_column}")
        trades: list[TradeActivity] = []
        for row_no, row in enumerate(reader, start=2):
            try:
                entry = _parse_utc(row.get(entry_column, ""))
            except ActivityMetricsError as exc:
                raise ActivityMetricsError(f"row {row_no}: {exc}") from exc
            symbol = (row.get(symbol_column, "") or "UNKNOWN").strip() or "UNKNOWN"
            setup = (row.get(setup_column, "") or "UNCLASSIFIED").strip() or "UNCLASSIFIED"
            trades.append(TradeActivity(entry, symbol, setup))
    return trades


def weekday_trading_days(start: date, end_exclusive: date) -> list[date]:
    if end_exclusive <= start:
        raise ActivityMetricsError("end_date must be after start_date")
    out: list[date] = []
    current = start
    while current < end_exclusive:
        if current.weekday() < 5:
            out.append(current)
        current += timedelta(days=1)
    return out


def load_trading_days(path: str | Path) -> list[date]:
    source = Path(path)
    if not source.is_file():
        raise ActivityMetricsError(f"trading-day file not found: {source}")
    values: list[date] = []
    for line_no, raw in enumerate(source.read_text(encoding="utf-8-sig").splitlines(), start=1):
        text = raw.strip()
        if not text or text.startswith("#"):
            continue
        try:
            values.append(date.fromisoformat(text))
        except ValueError as exc:
            raise ActivityMetricsError(f"invalid trading date on line {line_no}: {text!r}") from exc
    if len(values) != len(set(values)):
        raise ActivityMetricsError("trading-day file contains duplicate dates")
    return sorted(values)


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def compute_activity_metrics(
    trades: Sequence[TradeActivity],
    trading_days: Iterable[date],
) -> dict:
    days = sorted(set(trading_days))
    if not days:
        raise ActivityMetricsError("eligible trading-day set is empty")
    day_set = set(days)

    counts: Counter[date] = Counter()
    by_symbol: Counter[str] = Counter()
    by_setup: Counter[str] = Counter()
    for trade in trades:
        trade_day = trade.entry_utc.date()
        if trade_day not in day_set:
            raise ActivityMetricsError(
                f"trade at {trade.entry_utc.isoformat()} falls outside eligible trading days"
            )
        counts[trade_day] += 1
        by_symbol[trade.symbol] += 1
        by_setup[trade.setup] += 1

    daily = [counts.get(day, 0) for day in days]
    active_days = sum(1 for value in daily if value > 0)
    zero_days = len(days) - active_days
    total = sum(daily)
    distribution = {
        "0": sum(1 for value in daily if value == 0),
        "1": sum(1 for value in daily if value == 1),
        "2": sum(1 for value in daily if value == 2),
        "3_plus": sum(1 for value in daily if value >= 3),
    }

    return {
        "schema_version": 1,
        "methodology": "DAILY_OPPORTUNITY_ACTIVITY_V1",
        "trading_days": len(days),
        "active_trading_days": active_days,
        "zero_trade_days": zero_days,
        "active_trading_day_ratio": _ratio(active_days, len(days)),
        "zero_trade_day_ratio": _ratio(zero_days, len(days)),
        "total_trades": total,
        "trades_per_day_mean": total / len(days),
        "trades_per_day_median": float(statistics.median(daily)),
        "max_trades_single_day": max(daily),
        "daily_distribution": distribution,
        "trades_by_symbol": dict(sorted(by_symbol.items())),
        "trades_by_setup": dict(sorted(by_setup.items())),
        "daily_counts": {day.isoformat(): counts.get(day, 0) for day in days},
        "evidence_scope": "ACTIVITY_ONLY_NOT_EDGE_VALIDATION",
        "live_trading_authorized": False,
        "real_capital_authorized": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trades", required=True)
    parser.add_argument("--start-date", required=True, help="YYYY-MM-DD inclusive")
    parser.add_argument("--end-date", required=True, help="YYYY-MM-DD exclusive")
    parser.add_argument("--trading-days-file")
    parser.add_argument("--entry-column", default="entry_utc")
    parser.add_argument("--symbol-column", default="symbol")
    parser.add_argument("--setup-column", default="setup")
    parser.add_argument("--output")
    args = parser.parse_args()

    try:
        start = date.fromisoformat(args.start_date)
        end_exclusive = date.fromisoformat(args.end_date)
        trades = load_trades_csv(
            args.trades,
            entry_column=args.entry_column,
            symbol_column=args.symbol_column,
            setup_column=args.setup_column,
        )
        if args.trading_days_file:
            days = load_trading_days(args.trading_days_file)
            if not days or days[0] < start or days[-1] >= end_exclusive:
                raise ActivityMetricsError("trading-day file must be contained in requested interval")
        else:
            days = weekday_trading_days(start, end_exclusive)
        result = compute_activity_metrics(trades, days)
    except (ActivityMetricsError, ValueError) as exc:
        parser.error(str(exc))
        return

    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
