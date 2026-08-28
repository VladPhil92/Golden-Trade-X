import hashlib
import json
from pathlib import Path

import pytest

from quant_research import (
    INVALID_DATA,
    INSUFFICIENT_EVIDENCE,
    READY_FOR_EXPLORATORY_RESEARCH,
    EvidenceThresholds,
    build_baseline,
    evaluate_data_quality,
    load_manifest,
)
from telemetry_db import connect


def _manifest() -> dict:
    return {
        "dataset_id": "gtx-baseline-test-001",
        "source_type": "strategy_tester",
        "git_sha": "6c9d078d3f642ffb0196a3f62fbd95bf62246bf6",
        "preset_sha256": hashlib.sha256(b"test-preset").hexdigest(),
        "broker": "TEST-BROKER",
        "symbols": ["XAUUSD"],
        "timeframe": "M15",
        "period_start": "2026-01-01T00:00:00Z",
        "period_end": "2026-06-01T00:00:00Z",
    }


def _seed_outcomes(conn, count: int = 100, *, unknown_confidence: bool = False) -> None:
    for index in range(count):
        realized = 1.0 if index % 2 == 0 else -0.5
        confidence = -1 if unknown_confidence else 60 + index % 31
        conn.execute(
            """
            INSERT INTO position_outcomes (
                row_hash, event_id, close_time, account, magic, symbol,
                position_id, direction, entry_time, entry_price, initial_sl,
                initial_tp, initial_risk_price, initial_risk_money,
                initial_volume, confidence, regime, mfe_r, mfe_price,
                mfe_time, mae_r, mae_price, mae_time, net_pnl, realized_r,
                close_price, source_file, raw_json
            ) VALUES (
                ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
            )
            """,
            (
                f"hash-{index}",
                f"event-{index}",
                f"2026.04.{(index % 28) + 1:02d} 16:00:00",
                12345,
                920260,
                "XAUUSD",
                100000 + index,
                "BUY" if index % 2 == 0 else "SELL",
                f"2026.04.{(index % 28) + 1:02d} 10:00:00",
                3000.0,
                2990.0,
                3020.0,
                10.0,
                100.0,
                0.1,
                confidence,
                index % 3,
                1.5 + (index % 5) * 0.1,
                3015.0,
                f"2026.04.{(index % 28) + 1:02d} 12:00:00",
                0.4 + (index % 4) * 0.1,
                2996.0,
                f"2026.04.{(index % 28) + 1:02d} 11:00:00",
                realized * 100.0,
                realized,
                3010.0,
                "outcomes.csv",
                "{}",
            ),
        )
    conn.commit()


def test_empty_database_is_insufficient_not_success(tmp_path: Path) -> None:
    db = tmp_path / "research.sqlite"
    with connect(db) as conn:
        report = build_baseline(
            conn,
            manifest=None,
            manifest_errors=["research manifest was not supplied"],
            generated_at="fixed",
        )

    assert report["research_status"] == INSUFFICIENT_EVIDENCE
    assert report["data_quality"]["outcomes"] == 0
    assert report["baseline"]["realized_r"]["mean"] is None
    assert report["baseline"]["r_profit_factor"] is None
    assert "not evidence of profitability" in report["evidence_scope"]


def test_valid_dataset_meets_internal_exploratory_floor_and_is_reproducible(tmp_path: Path) -> None:
    db = tmp_path / "research.sqlite"
    manifest = _manifest()
    thresholds = EvidenceThresholds(min_segment_outcomes=10)
    with connect(db) as conn:
        _seed_outcomes(conn, 100)
        first = build_baseline(conn, manifest, [], thresholds, generated_at="first")
        second = build_baseline(conn, manifest, [], thresholds, generated_at="second")

    assert first["research_status"] == READY_FOR_EXPLORATORY_RESEARCH
    assert first["dataset"]["fingerprint_sha256"] == second["dataset"]["fingerprint_sha256"]
    assert first["baseline"]["observations_used"] == 100
    assert first["baseline"]["positive"] == 50
    assert first["baseline"]["negative"] == 50
    assert first["baseline"]["positive_rate"] == pytest.approx(0.5)
    assert first["baseline"]["realized_r"]["mean"] == pytest.approx(0.25)
    assert first["baseline"]["r_profit_factor"] == pytest.approx(2.0)
    assert first["ablation_status"]["status"] == "REQUIRES_COUNTERFACTUAL_STRATEGY_TESTER_RUNS"


def test_unknown_confidence_keeps_dataset_below_evidence_floor(tmp_path: Path) -> None:
    db = tmp_path / "research.sqlite"
    with connect(db) as conn:
        _seed_outcomes(conn, 100, unknown_confidence=True)
        quality = evaluate_data_quality(conn, _manifest(), [], EvidenceThresholds())

    assert quality["status"] == INSUFFICIENT_EVIDENCE
    assert quality["confidence_coverage"] == 0.0
    assert any("confidence coverage" in gap for gap in quality["evidence_gaps"])


def test_duplicate_position_outcome_is_invalid_data(tmp_path: Path) -> None:
    db = tmp_path / "research.sqlite"
    with connect(db) as conn:
        _seed_outcomes(conn, 100)
        source = conn.execute("SELECT * FROM position_outcomes LIMIT 1").fetchone()
        values = dict(source)
        values["row_hash"] = "duplicate-hash"
        values["event_id"] = "duplicate-event"
        columns = list(values)
        placeholders = ",".join("?" for _ in columns)
        conn.execute(
            f"INSERT INTO position_outcomes ({','.join(columns)}) VALUES ({placeholders})",
            [values[column] for column in columns],
        )
        conn.commit()
        quality = evaluate_data_quality(conn, _manifest(), [], EvidenceThresholds())

    assert quality["status"] == INVALID_DATA
    assert any("duplicate final outcome" in error for error in quality["integrity_errors"])


def test_manifest_symbol_scope_mismatch_is_invalid_data(tmp_path: Path) -> None:
    db = tmp_path / "research.sqlite"
    manifest = _manifest()
    manifest["symbols"] = ["XAGUSD"]
    with connect(db) as conn:
        _seed_outcomes(conn, 100)
        quality = evaluate_data_quality(conn, manifest, [], EvidenceThresholds())

    assert quality["status"] == INVALID_DATA
    assert any("outside manifest scope" in error for error in quality["integrity_errors"])


def test_manifest_loader_rejects_bad_hashes_and_missing_fields(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "dataset_id": "bad",
                "source_type": "strategy_tester",
                "git_sha": "not-a-sha",
                "preset_sha256": "short",
                "broker": "TEST",
                "symbols": ["XAUUSD"],
                "timeframe": "M15",
                "period_start": "2026-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    manifest, errors = load_manifest(path)
    assert manifest is not None
    assert any("period_end" in error for error in errors)
    assert any("git_sha" in error for error in errors)
    assert any("preset_sha256" in error for error in errors)


def test_threshold_validation_rejects_impossible_coverage() -> None:
    with pytest.raises(ValueError, match="between 0 and 1"):
        EvidenceThresholds(min_confidence_coverage=1.1).validate()
