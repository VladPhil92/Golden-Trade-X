import json
from pathlib import Path

import pytest

from telemetry_db import connect
from telemetry_report import build_report, open_readonly, validate_schema, write_report


def _seed(conn) -> None:
    conn.execute(
        """
        INSERT INTO signal_events (
            row_hash, event_id, event_time, stage, decision, reason, direction,
            confidence, regime, source_file, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("s1", "sig-1", "2026.08.28 12:00:00", "GUARD", "REJECTED", "NEWS_WINDOW", "NONE",
         -1, 1, "signals.csv", "{}"),
    )
    conn.execute(
        """
        INSERT INTO signal_events (
            row_hash, event_id, event_time, stage, decision, reason, direction,
            confidence, regime, source_file, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("s2", "sig-2", "2026.08.28 12:15:00", "EXECUTION", "ORDER_REQUESTED", "", "BUY",
         72, 1, "signals.csv", "{}"),
    )
    conn.execute(
        """
        INSERT INTO execution_events (
            row_hash, event_id, event_time, action, status, direction,
            slippage_points, position_id, source_file, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("e1", "exe-1", "2026.08.28 12:15:01", "OPEN", "SERVER_CONFIRMED", "BUY",
         1.5, 4001, "executions.csv", "{}"),
    )
    conn.execute(
        """
        INSERT INTO position_outcomes (
            row_hash, event_id, close_time, symbol, position_id, direction,
            initial_risk_money, confidence, regime, mfe_r, mae_r, net_pnl,
            realized_r, source_file, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("o1", "out-1", "2026.08.28 14:00:00", "XAUUSD", 4001, "BUY",
         25.0, 72, 1, 1.8, 0.4, 20.0, 0.8, "outcomes.csv", "{}"),
    )
    conn.commit()


def test_build_report_uses_only_observed_rows(tmp_path: Path) -> None:
    db = tmp_path / "research.sqlite"
    with connect(db) as conn:
        _seed(conn)
        report = build_report(conn, generated_at="2026-08-28T22:00:00+00:00")

    assert report["counts"] == {"signals": 2, "executions": 1, "outcomes": 1}
    assert report["signal_funnel"]["rejection_reasons"] == [
        {"reason": "NEWS_WINDOW", "count": 1}
    ]
    assert report["execution"]["confirmed_open_slippage"] == {
        "observations": 1,
        "avg_points": 1.5,
        "min_points": 1.5,
        "max_points": 1.5,
    }
    assert report["outcomes"]["observations"] == 1
    assert report["outcomes"]["net_pnl_sum"] == 20.0
    assert report["outcomes"]["avg_realized_r"] == 0.8
    assert report["outcomes"]["positive_r"] == 1
    assert "not evidence of profitability" in report["evidence_scope"]


def test_empty_database_reports_zero_without_fabricating_metrics(tmp_path: Path) -> None:
    db = tmp_path / "empty.sqlite"
    with connect(db) as conn:
        report = build_report(conn, generated_at="fixed")

    assert report["counts"] == {"signals": 0, "executions": 0, "outcomes": 0}
    assert report["outcomes"]["observations"] == 0
    assert report["outcomes"]["net_pnl_sum"] is None
    assert report["outcomes"]["avg_realized_r"] is None
    assert report["signal_funnel"]["stage_decisions"] == []
    assert report["execution"]["statuses"] == []


def test_report_can_be_written_and_read_from_readonly_db(tmp_path: Path) -> None:
    db = tmp_path / "research.sqlite"
    with connect(db) as conn:
        _seed(conn)

    with open_readonly(db) as conn:
        report = build_report(conn, generated_at="fixed")

    output = tmp_path / "report.json"
    write_report(report, output)
    loaded = json.loads(output.read_text(encoding="utf-8"))
    assert loaded["schema_version"] == 1
    assert loaded["counts"]["outcomes"] == 1


def test_schema_validation_fails_closed_for_unrelated_database(tmp_path: Path) -> None:
    import sqlite3

    db = tmp_path / "bad.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE unrelated (id INTEGER)")
        with pytest.raises(ValueError, match="missing table"):
            validate_schema(conn)
