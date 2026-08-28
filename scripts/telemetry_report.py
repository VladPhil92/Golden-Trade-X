#!/usr/bin/env python3
"""Golden Trade X v2.70 — reproducible descriptive telemetry summary.

Reads the v2.70 SQLite research database in read-only mode and emits JSON for
``dashboard/research.html``. Metrics are descriptive observations only. The
report does not infer profitability, significance, OOS validity or forward
performance.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REQUIRED_TABLES = {"signal_events", "execution_events", "position_outcomes"}
REPORT_SCHEMA_VERSION = 1


def open_readonly(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(path)
    return sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)


def validate_schema(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    existing = {row[0] for row in rows}
    missing = REQUIRED_TABLES - existing
    if missing:
        raise ValueError(f"telemetry database missing table(s): {', '.join(sorted(missing))}")


def _scalar(conn: sqlite3.Connection, sql: str) -> Any:
    row = conn.execute(sql).fetchone()
    return None if row is None else row[0]


def _named_rows(conn: sqlite3.Connection, sql: str, names: tuple[str, ...]) -> list[dict[str, Any]]:
    return [dict(zip(names, row, strict=True)) for row in conn.execute(sql).fetchall()]


def build_report(conn: sqlite3.Connection, generated_at: str | None = None) -> dict[str, Any]:
    validate_schema(conn)
    generated = generated_at or datetime.now(timezone.utc).isoformat()

    counts = {
        "signals": int(_scalar(conn, "SELECT COUNT(*) FROM signal_events") or 0),
        "executions": int(_scalar(conn, "SELECT COUNT(*) FROM execution_events") or 0),
        "outcomes": int(_scalar(conn, "SELECT COUNT(*) FROM position_outcomes") or 0),
    }

    signal_stages = _named_rows(
        conn,
        """
        SELECT COALESCE(stage, ''), COALESCE(decision, ''), COUNT(*)
        FROM signal_events
        GROUP BY stage, decision
        ORDER BY COUNT(*) DESC, stage, decision
        """,
        ("stage", "decision", "count"),
    )
    rejection_reasons = _named_rows(
        conn,
        """
        SELECT COALESCE(reason, ''), COUNT(*)
        FROM signal_events
        WHERE decision = 'REJECTED'
        GROUP BY reason
        ORDER BY COUNT(*) DESC, reason
        """,
        ("reason", "count"),
    )
    execution_statuses = _named_rows(
        conn,
        """
        SELECT COALESCE(action, ''), COALESCE(status, ''), COUNT(*)
        FROM execution_events
        GROUP BY action, status
        ORDER BY action, status
        """,
        ("action", "status", "count"),
    )

    slippage_row = conn.execute(
        """
        SELECT COUNT(slippage_points), AVG(slippage_points),
               MIN(slippage_points), MAX(slippage_points)
        FROM execution_events
        WHERE action = 'OPEN'
          AND status = 'SERVER_CONFIRMED'
          AND slippage_points IS NOT NULL
        """
    ).fetchone()
    confirmed_open_slippage = {
        "observations": int(slippage_row[0] or 0),
        "avg_points": slippage_row[1],
        "min_points": slippage_row[2],
        "max_points": slippage_row[3],
    }

    outcome_row = conn.execute(
        """
        SELECT COUNT(*),
               SUM(net_pnl),
               AVG(realized_r),
               AVG(mfe_r),
               AVG(mae_r),
               SUM(CASE WHEN realized_r > 0 THEN 1 ELSE 0 END),
               SUM(CASE WHEN realized_r < 0 THEN 1 ELSE 0 END),
               SUM(CASE WHEN realized_r = 0 THEN 1 ELSE 0 END)
        FROM position_outcomes
        """
    ).fetchone()
    outcomes = {
        "observations": int(outcome_row[0] or 0),
        "net_pnl_sum": outcome_row[1],
        "avg_realized_r": outcome_row[2],
        "avg_mfe_r": outcome_row[3],
        "avg_mae_r": outcome_row[4],
        "positive_r": int(outcome_row[5] or 0),
        "negative_r": int(outcome_row[6] or 0),
        "zero_r": int(outcome_row[7] or 0),
    }
    outcomes_by_regime = _named_rows(
        conn,
        """
        SELECT regime, COUNT(*), AVG(realized_r), AVG(mfe_r), AVG(mae_r)
        FROM position_outcomes
        GROUP BY regime
        ORDER BY regime
        """,
        ("regime", "count", "avg_realized_r", "avg_mfe_r", "avg_mae_r"),
    )

    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at_utc": generated,
        "evidence_scope": (
            "Descriptive observations from the v2.70 telemetry database only; "
            "not evidence of profitability, statistical significance, OOS validity or forward performance."
        ),
        "counts": counts,
        "signal_funnel": {
            "stage_decisions": signal_stages,
            "rejection_reasons": rejection_reasons,
        },
        "execution": {
            "statuses": execution_statuses,
            "confirmed_open_slippage": confirmed_open_slippage,
        },
        "outcomes": outcomes,
        "outcomes_by_regime": outcomes_by_regime,
    }


def write_report(report: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Golden Trade X SQLite telemetry → descriptive JSON")
    parser.add_argument("--db", type=Path, required=True, help="v2.70 SQLite research database")
    parser.add_argument("--output", type=Path, required=True, help="JSON output consumed by research dashboard")
    args = parser.parse_args()

    try:
        with open_readonly(args.db) as conn:
            report = build_report(conn)
    except (FileNotFoundError, sqlite3.Error, ValueError) as exc:
        parser.error(str(exc))

    write_report(report, args.output)
    print(
        "research summary written | "
        f"signals={report['counts']['signals']} "
        f"executions={report['counts']['executions']} "
        f"outcomes={report['counts']['outcomes']} | {args.output}"
    )


if __name__ == "__main__":
    main()
