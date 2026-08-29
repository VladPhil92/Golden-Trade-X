import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.experiment_registry import RegistryValidationError, sha256_file
from scripts.forward_demo_evaluator import evaluate_forward_demo
from scripts.forward_demo_gate import evaluate_forward_demo_gate
from scripts.forward_demo_planner import generate_forward_demo_plan
from scripts.forward_demo_readiness import evaluate_readiness
from scripts.telemetry_db import connect


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _approved_policy(path: Path, *, approved: bool = True) -> Path:
    return _write_json(
        path,
        {
            "schema_version": 1,
            "policy_id": "TEST-FORWARD-DEMO-V1",
            "approved": approved,
            "observation": {
                "minimum_calendar_days": 2,
                "minimum_closed_trades": 2,
                "maximum_heartbeat_gap_seconds": 3700,
                "require_trade_mode": "DEMO",
                "require_stable_terminal_build": True,
            },
            "criteria": [
                {"metric": "total_realized_r", "operator": ">", "value": 0},
                {"metric": "expectancy_r", "operator": ">", "value": 0},
                {"metric": "closed_trade_max_drawdown_r", "operator": "<=", "value": 2.0},
            ],
        },
    )


def _readiness(path: Path, preset: Path) -> Path:
    return _write_json(
        path,
        {
            "schema_version": 1,
            "methodology": "FORWARD_DEMO_READINESS_V1",
            "decision": "READY_FOR_FORWARD_DEMO",
            "ready": True,
            "live_trading_authorized": False,
            "candidate": {
                "experiment_id": "candidate-exp-001",
                "preset_sha256": sha256_file(preset),
                "source_fold_id": "WF-001",
            },
        },
    )


def _plan(tmp_path: Path, *, approved: bool = True) -> tuple[Path, Path, dict]:
    preset = tmp_path / "frozen_preset.set"
    preset.write_text(Path("config/GoldenTradeX.set").read_text(encoding="utf-8"), encoding="utf-8")
    readiness = _readiness(tmp_path / "readiness.json", preset)
    policy = _approved_policy(tmp_path / "policy.json", approved=approved)
    config = _write_json(
        tmp_path / "plan_config.json",
        {
            "schema_version": 1,
            "campaign_id": "TEST-FWD-001",
            "readiness_path": readiness.name,
            "forward_policy_path": policy.name,
            "frozen_preset_path": preset.name,
            "build_id": "a" * 40,
            "observation_start_utc": "2026-09-01T00:00:00Z",
            "observation_end_utc": "2026-09-03T00:00:00Z",
            "demo_environment": {
                "account": 123456,
                "broker": "TEST-BROKER-DEMO",
                "symbol": "XAUUSD",
                "timeframe": "PERIOD_M15",
            },
        },
    )
    plan_path = tmp_path / "forward_plan.json"
    plan = generate_forward_demo_plan(config, plan_path)
    return plan_path, policy, plan


def _mql(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).strftime("%Y.%m.%d %H:%M:%S")


def _db(tmp_path: Path, plan: dict, *, realized: tuple[float, float] = (1.0, 0.5)) -> Path:
    db = tmp_path / "forward.sqlite"
    runtime = plan["runtime_contract"]
    config_sha = plan["frozen_preset"]["expected_runtime_config_sha256"]
    config_snapshot = plan["frozen_preset"]["expected_runtime_config_snapshot"]
    start = datetime(2026, 9, 1, tzinfo=timezone.utc)

    with connect(db) as conn:
        for hour in range(49):
            ts = start + timedelta(hours=hour)
            kind = "START" if hour == 0 else "END" if hour == 48 else "HEARTBEAT"
            conn.execute(
                """
                INSERT INTO research_sessions (
                    row_hash,event_id,server_time,utc_time,account,magic,symbol,timeframe,kind,
                    candidate_id,build_id,broker,terminal_build,trade_mode,server_utc_offset_seconds,
                    config_snapshot,config_sha256,source_file,raw_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    f"session-{hour}", f"ses-{hour}", _mql(ts), _mql(ts), runtime["account"],
                    runtime["magic"], runtime["symbol"], runtime["timeframe"], kind,
                    runtime["candidate_id"], runtime["build_id"], runtime["broker"], 5100,
                    "DEMO", 0, config_snapshot, config_sha, "sessions.csv", "{}",
                ),
            )

        for index, r_value in enumerate(realized, start=1):
            close = start + timedelta(hours=12 * index)
            conn.execute(
                """
                INSERT INTO position_outcomes (
                    row_hash,event_id,close_time,account,magic,symbol,position_id,
                    net_pnl,realized_r,source_file,raw_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    f"outcome-{index}", f"out-{index}", _mql(close), runtime["account"],
                    runtime["magic"], runtime["symbol"], 1000 + index,
                    r_value * 100.0, r_value, "outcomes.csv", "{}",
                ),
            )
        conn.commit()
    return db


def test_readiness_requires_same_candidate_for_oos_and_robustness(tmp_path: Path) -> None:
    oos = _write_json(
        tmp_path / "oos.json",
        {
            "methodology": "ROLLING_FROZEN_OOS_AGGREGATION",
            "plan_sha256": "plan-sha",
            "promotion_policy_sha256": "promotion-policy-sha",
            "folds": [{"fold_id": "WF-001", "oos_experiment_id": "candidate-exp-001"}],
        },
    )
    promotion = _write_json(
        tmp_path / "promotion.json",
        {
            "oos_summary_sha256": sha256_file(oos),
            "policy_sha256": "promotion-policy-sha",
            "decision": "PROMOTE_TO_FORWARD_DEMO_CANDIDATE",
            "promotable": True,
            "live_trading_authorized": False,
        },
    )
    selection = _write_json(
        tmp_path / "selection.json",
        {
            "methodology": "IS_SELECTION_THEN_FROZEN_OOS",
            "fold_id": "WF-001",
            "plan_sha256": "plan-sha",
            "promotion_policy_sha256": "promotion-policy-sha",
            "selected": {"frozen_preset_sha256": "preset-sha"},
            "oos": {"experiment_id": "candidate-exp-001"},
        },
    )
    robustness = _write_json(
        tmp_path / "robustness.json",
        {
            "methodology": "ROBUSTNESS_AGGREGATION_V1",
            "robustness_policy_sha256": "robust-policy-sha",
            "baseline": {"experiment_id": "candidate-exp-001", "preset_sha256": "preset-sha"},
        },
    )
    robustness_decision = _write_json(
        tmp_path / "robustness_decision.json",
        {
            "robustness_summary_sha256": sha256_file(robustness),
            "baseline_experiment_id": "candidate-exp-001",
            "baseline_preset_sha256": "preset-sha",
            "policy_sha256": "robust-policy-sha",
            "decision": "ROBUSTNESS_PASS_FOR_FORWARD_DEMO_REVIEW",
            "robust": True,
            "live_trading_authorized": False,
        },
    )

    result = evaluate_readiness(oos, promotion, selection, robustness, robustness_decision)
    assert result["ready"] is True
    assert result["live_trading_authorized"] is False

    payload = json.loads(robustness.read_text(encoding="utf-8"))
    payload["baseline"]["experiment_id"] = "different-candidate"
    _write_json(robustness, payload)
    robustness_payload = json.loads(robustness_decision.read_text(encoding="utf-8"))
    robustness_payload["robustness_summary_sha256"] = sha256_file(robustness)
    _write_json(robustness_decision, robustness_payload)
    with pytest.raises(RegistryValidationError, match="exact selected OOS candidate"):
        evaluate_readiness(oos, promotion, selection, robustness, robustness_decision)


def test_planner_freezes_preset_runtime_fingerprint_and_fixed_window(tmp_path: Path) -> None:
    _, _, plan = _plan(tmp_path)
    assert plan["status"] == "READY_FOR_FORWARD_DEMO_OBSERVATION"
    assert plan["runtime_contract"]["magic"] == 920260
    assert plan["runtime_contract"]["timeframe"] == "PERIOD_M15"
    assert plan["frozen_preset"]["expected_runtime_config_sha256"]
    assert plan["observation_window"]["planned_calendar_days"] == 2.0
    assert plan["live_trading_authorized"] is False


def test_planner_rejects_preset_bytes_different_from_readiness(tmp_path: Path) -> None:
    plan_path, _, _ = _plan(tmp_path)
    config_path = tmp_path / "plan_config.json"
    preset = tmp_path / "frozen_preset.set"
    preset.write_text(preset.read_text(encoding="utf-8") + "\n; drift\n", encoding="utf-8")
    with pytest.raises(RegistryValidationError, match="preset bytes"):
        generate_forward_demo_plan(config_path, plan_path)


def test_valid_forward_demo_evidence_passes_release_review_gate(tmp_path: Path) -> None:
    plan_path, policy, plan = _plan(tmp_path)
    db = _db(tmp_path, plan)
    evaluation_path = tmp_path / "evaluation.json"
    evaluation = evaluate_forward_demo(plan_path, db, evaluation_path)
    assert evaluation["valid"] is True
    assert evaluation["summary"]["closed_trades"] == 2
    assert evaluation["summary"]["total_realized_r"] == 1.5
    assert evaluation["provenance"]["maximum_observed_coverage_gap_seconds"] <= 3700

    gate = evaluate_forward_demo_gate(plan_path, evaluation_path, policy)
    assert gate["decision"] == "FORWARD_DEMO_PASS_FOR_RELEASE_REVIEW"
    assert gate["passed"] is True
    assert gate["live_trading_authorized"] is False


def test_config_build_and_real_mode_drift_fail_closed(tmp_path: Path) -> None:
    for column, value, expected_reason in (
        ("config_sha256", "0" * 64, "SESSION_CONFIG_SHA256_DRIFT"),
        ("build_id", "b" * 40, "SESSION_BUILD_ID_DRIFT"),
        ("trade_mode", "REAL", "SESSION_TRADE_MODE_DRIFT"),
    ):
        case = tmp_path / column
        case.mkdir()
        plan_path, _, plan = _plan(case)
        db = _db(case, plan)
        with sqlite3_connect(db) as conn:
            conn.execute(f"UPDATE research_sessions SET {column}=? WHERE event_id='ses-24'", (value,))
            conn.commit()
        evaluation = evaluate_forward_demo(plan_path, db)
        assert evaluation["valid"] is False
        assert expected_reason in evaluation["reasons"]


def sqlite3_connect(path: Path):
    import sqlite3

    return sqlite3.connect(path)


def test_heartbeat_gap_and_insufficient_trades_are_invalid_evidence(tmp_path: Path) -> None:
    plan_path, _, plan = _plan(tmp_path)
    db = _db(tmp_path, plan)
    with sqlite3_connect(db) as conn:
        conn.execute("DELETE FROM research_sessions WHERE event_id IN ('ses-24','ses-25')")
        conn.execute("DELETE FROM position_outcomes WHERE event_id='out-2'")
        conn.commit()
    evaluation = evaluate_forward_demo(plan_path, db)
    assert evaluation["valid"] is False
    assert "HEARTBEAT_COVERAGE_GAP" in evaluation["reasons"]
    assert "INSUFFICIENT_CLOSED_TRADES" in evaluation["reasons"]


def test_negative_forward_performance_is_valid_evidence_but_fails_gate(tmp_path: Path) -> None:
    plan_path, policy, plan = _plan(tmp_path)
    db = _db(tmp_path, plan, realized=(-1.0, 0.25))
    evaluation_path = tmp_path / "evaluation.json"
    evaluation = evaluate_forward_demo(plan_path, db, evaluation_path)
    assert evaluation["valid"] is True
    gate = evaluate_forward_demo_gate(plan_path, evaluation_path, policy)
    assert gate["passed"] is False
    assert gate["decision"] == "FORWARD_DEMO_FAIL"
    assert "CRITERION_FAILED:total_realized_r" in gate["reasons"]


def test_policy_mutation_after_plan_freeze_is_rejected(tmp_path: Path) -> None:
    plan_path, policy, plan = _plan(tmp_path)
    db = _db(tmp_path, plan)
    evaluation_path = tmp_path / "evaluation.json"
    evaluate_forward_demo(plan_path, db, evaluation_path)

    payload = json.loads(policy.read_text(encoding="utf-8"))
    payload["criteria"][0]["value"] = -100
    _write_json(policy, payload)
    with pytest.raises(RegistryValidationError, match="policy changed after plan freeze"):
        evaluate_forward_demo_gate(plan_path, evaluation_path, policy)


def test_unapproved_policy_never_creates_official_forward_evidence(tmp_path: Path) -> None:
    plan_path, _, plan = _plan(tmp_path, approved=False)
    assert plan["status"] == "DRAFT_POLICY_UNAPPROVED"
    db = _db(tmp_path, plan)
    evaluation = evaluate_forward_demo(plan_path, db)
    assert evaluation["valid"] is False
    assert "POLICY_NOT_APPROVED" in evaluation["reasons"]
