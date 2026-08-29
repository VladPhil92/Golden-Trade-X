import json
from pathlib import Path

import pytest

from scripts.campaign_contract import candidate_universe_sha256
from scripts.experiment_registry import RegistryValidationError, sha256_file
from scripts.official_campaign_freeze import freeze_official_campaign
from scripts.rc1_release_review_gate import evaluate_rc1_release_review


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _policy(path: Path, policy_id: str, *, approved: bool = True) -> Path:
    return _write_json(
        path,
        {
            "schema_version": 1,
            "policy_id": policy_id,
            "approved": approved,
            "criteria": [{"metric": "placeholder", "operator": ">", "value": 0}],
        },
    )


def _campaign_inputs(tmp_path: Path, *, promotion_approved: bool = True) -> tuple[Path, Path]:
    preset = tmp_path / "candidate.set"
    preset.write_text(Path("config/GoldenTradeX.set").read_text(encoding="utf-8"), encoding="utf-8")

    promotion = _policy(tmp_path / "promotion.json", "TEST-PROMOTION", approved=promotion_approved)
    robustness = _policy(tmp_path / "robustness.json", "TEST-ROBUSTNESS")
    forward = _policy(tmp_path / "forward.json", "TEST-FORWARD")

    walk = _write_json(
        tmp_path / "walk.json",
        {
            "schema_version": 1,
            "plan_id": "TEST-WF-OFFICIAL",
            "start_date": "2022-01-01",
            "end_date": "2023-01-01",
            "in_sample_months": 6,
            "oos_months": 3,
            "step_months": 3,
            "embargo_days": 0,
            "minimum_folds": 2,
            "selection_policy": {
                "policy_id": "TEST-IS-SELECTION",
                "objective": {"metric": "profit_factor", "direction": "maximize"},
                "constraints": [{"metric": "total_trades", "operator": ">=", "value": 20}],
                "tie_breakers": [{"metric": "expected_payoff", "direction": "maximize"}],
            },
            "promotion_policy_path": promotion.name,
        },
    )

    template = _write_json(
        tmp_path / "robustness_template.json",
        {
            "schema_version": 1,
            "template_id": "TEST-ROBUSTNESS-TEMPLATE",
            "parameter_scenarios": [
                {"name": "ema_minus", "parameter": "InpEmaFast", "value": 18},
                {"name": "ema_plus", "parameter": "InpEmaFast", "value": 24},
            ],
            "broker_requirements": {
                "required_labels": ["BROKER-A", "BROKER-B"],
                "minimum_distinct_brokers": 2,
            },
            "modeled_cost_scenarios": [
                {"name": "cost_1", "cost_per_trade_currency": 1.0}
            ],
            "executed_metadata_stress": [],
        },
    )

    config = _write_json(
        tmp_path / "campaign.json",
        {
            "schema_version": 1,
            "campaign_id": "TEST-RC1-CAMPAIGN",
            "build_id": "a" * 40,
            "candidate_universe": [
                {"name": "baseline", "preset_path": preset.name}
            ],
            "walk_forward_config_path": walk.name,
            "robustness_template_path": template.name,
            "robustness_policy_path": robustness.name,
            "forward_policy_path": forward.name,
        },
    )
    return config, preset


def test_official_freeze_requires_all_policies_approved(tmp_path: Path) -> None:
    config, _ = _campaign_inputs(tmp_path, promotion_approved=False)
    with pytest.raises(RegistryValidationError, match="requires approved"):
        freeze_official_campaign(config, tmp_path / "out")

    draft = freeze_official_campaign(config, tmp_path / "draft", allow_draft=True)
    assert draft["status"] == "ENGINEERING_DRAFT_NOT_OFFICIAL"
    assert draft["live_trading_authorized"] is False


def test_official_freeze_hashes_candidate_universe_and_walk_plan(tmp_path: Path) -> None:
    config, preset = _campaign_inputs(tmp_path)
    result = freeze_official_campaign(config, tmp_path / "out")

    assert result["status"] == "OFFICIAL_CAMPAIGN_FROZEN"
    assert result["candidate_universe"]["count"] == 1
    assert result["candidate_universe"]["candidates"][0]["preset_sha256"] == sha256_file(preset)
    assert result["candidate_universe"]["sha256"] == candidate_universe_sha256(
        result["candidate_universe"]["candidates"]
    )
    assert (tmp_path / "out" / "walk_forward_plan.json").is_file()
    assert result["walk_forward"]["plan_sha256"] == sha256_file(
        tmp_path / "out" / "walk_forward_plan.json"
    )
    assert result["live_trading_authorized"] is False


def test_official_freeze_rejects_candidate_that_enables_real_trading(tmp_path: Path) -> None:
    config, preset = _campaign_inputs(tmp_path)
    text = preset.read_text(encoding="utf-8")
    assert "InpAllowRealTrading=false" in text
    preset.write_text(text.replace("InpAllowRealTrading=false", "InpAllowRealTrading=true"), encoding="utf-8")

    with pytest.raises(RegistryValidationError, match="enables real trading"):
        freeze_official_campaign(config, tmp_path / "out")


def _build_release_bundle(tmp_path: Path) -> tuple[Path, dict]:
    config, _ = _campaign_inputs(tmp_path)
    out = tmp_path / "freeze"
    lock = freeze_official_campaign(config, out)
    lock_path = out / "campaign_lock.json"

    candidate = lock["candidate_universe"]["candidates"][0]
    preset_sha = candidate["preset_sha256"]
    candidate_id = "official-oos-candidate-001"
    fold_id = "WF001"

    selection = _write_json(
        tmp_path / "selection.json",
        {
            "schema_version": 1,
            "methodology": "IS_SELECTION_THEN_FROZEN_OOS",
            "fold_id": fold_id,
            "plan_sha256": lock["walk_forward"]["plan_sha256"],
            "promotion_policy_sha256": lock["walk_forward"]["promotion_policy"]["sha256"],
            "evidence_status": "OFFICIAL_FROZEN_OOS",
            "candidates": [
                {
                    "name": candidate["name"],
                    "preset_sha256": preset_sha,
                    "experiment_id": "is-candidate-001",
                    "eligible": True,
                    "metrics": {},
                    "constraint_checks": [],
                }
            ],
            "selected": {
                "name": candidate["name"],
                "is_experiment_id": "is-candidate-001",
                "frozen_preset_sha256": preset_sha,
            },
            "oos": {"experiment_id": candidate_id},
        },
    )

    oos = _write_json(
        tmp_path / "oos.json",
        {
            "schema_version": 1,
            "methodology": "ROLLING_FROZEN_OOS_AGGREGATION",
            "plan_sha256": lock["walk_forward"]["plan_sha256"],
            "promotion_policy_sha256": lock["walk_forward"]["promotion_policy"]["sha256"],
            "candidate_universe_sha256": lock["candidate_universe"]["sha256"],
            "folds": [
                {
                    "fold_id": fold_id,
                    "oos_experiment_id": candidate_id,
                    "selection_manifest_sha256": sha256_file(selection),
                }
            ],
            "summary": {},
        },
    )
    promotion = _write_json(
        tmp_path / "promotion_decision.json",
        {
            "decision": "PROMOTE_TO_FORWARD_DEMO_CANDIDATE",
            "promotable": True,
            "live_trading_authorized": False,
            "policy_sha256": lock["walk_forward"]["promotion_policy"]["sha256"],
            "oos_summary_sha256": sha256_file(oos),
        },
    )

    template = lock["robustness"]["template"]
    parameter_rows = [
        {
            "name": row["name"],
            "parameter": row["parameter"],
            "changed_to": str(row["value"]).lower() if isinstance(row["value"], bool) else str(row["value"]),
        }
        for row in template["parameter_scenarios"]
    ]
    robust_plan = _write_json(
        tmp_path / "robustness_plan.json",
        {
            "methodology": "ROBUSTNESS_V1",
            "campaign_id": lock["campaign_id"],
            "base": {
                "experiment_id": candidate_id,
                "preset_sha256": preset_sha,
                "git_sha": lock["build_id"],
            },
            "robustness_policy": lock["robustness"]["policy"],
            "domains": {
                "parameter_stability": {"scenarios": parameter_rows},
                "broker_replication": template["broker_requirements"],
                "cost_sensitivity": {"scenarios": template["modeled_cost_scenarios"]},
            },
        },
    )
    robust_summary = _write_json(
        tmp_path / "robustness_summary.json",
        {
            "methodology": "ROBUSTNESS_AGGREGATION_V1",
            "plan_sha256": sha256_file(robust_plan),
            "robustness_policy_sha256": lock["robustness"]["policy"]["sha256"],
            "baseline": {"experiment_id": candidate_id, "preset_sha256": preset_sha},
        },
    )
    robust_decision = _write_json(
        tmp_path / "robustness_decision.json",
        {
            "decision": "ROBUSTNESS_PASS_FOR_FORWARD_DEMO_REVIEW",
            "robust": True,
            "live_trading_authorized": False,
            "policy_sha256": lock["robustness"]["policy"]["sha256"],
            "robustness_summary_sha256": sha256_file(robust_summary),
        },
    )
    readiness = _write_json(
        tmp_path / "readiness.json",
        {
            "methodology": "FORWARD_DEMO_READINESS_V1",
            "decision": "READY_FOR_FORWARD_DEMO",
            "ready": True,
            "live_trading_authorized": False,
            "candidate": {
                "experiment_id": candidate_id,
                "preset_sha256": preset_sha,
                "source_fold_id": fold_id,
            },
            "evidence": {
                "oos_summary_sha256": sha256_file(oos),
                "promotion_decision_sha256": sha256_file(promotion),
                "selection_manifest_sha256": sha256_file(selection),
                "robustness_summary_sha256": sha256_file(robust_summary),
                "robustness_decision_sha256": sha256_file(robust_decision),
            },
        },
    )
    forward_plan = _write_json(
        tmp_path / "forward_plan.json",
        {
            "methodology": "FORWARD_DEMO_FIXED_WINDOW_V1",
            "status": "READY_FOR_FORWARD_DEMO_OBSERVATION",
            "live_trading_authorized": False,
            "candidate": {
                "experiment_id": candidate_id,
                "preset_sha256": preset_sha,
                "readiness_sha256": sha256_file(readiness),
            },
            "forward_policy": lock["forward_demo"]["policy"],
            "runtime_contract": {"build_id": lock["build_id"]},
        },
    )
    forward_eval = _write_json(
        tmp_path / "forward_eval.json",
        {
            "methodology": "FORWARD_DEMO_EVIDENCE_V1",
            "status": "VALID_FORWARD_DEMO_EVIDENCE",
            "valid": True,
            "live_trading_authorized": False,
            "plan_sha256": sha256_file(forward_plan),
        },
    )
    forward_gate = _write_json(
        tmp_path / "forward_gate.json",
        {
            "methodology": "FORWARD_DEMO_GATE_V1",
            "decision": "FORWARD_DEMO_PASS_FOR_RELEASE_REVIEW",
            "passed": True,
            "live_trading_authorized": False,
            "plan_sha256": sha256_file(forward_plan),
            "evaluation_sha256": sha256_file(forward_eval),
            "policy_sha256": lock["forward_demo"]["policy"]["sha256"],
        },
    )

    bundle_payload = {
        "campaign_lock_path": str(lock_path.relative_to(tmp_path)),
        "selection_manifest_path": selection.name,
        "oos_summary_path": oos.name,
        "promotion_decision_path": promotion.name,
        "robustness_plan_path": robust_plan.name,
        "robustness_summary_path": robust_summary.name,
        "robustness_decision_path": robust_decision.name,
        "readiness_path": readiness.name,
        "forward_plan_path": forward_plan.name,
        "forward_evaluation_path": forward_eval.name,
        "forward_gate_path": forward_gate.name,
    }
    return _write_json(tmp_path / "bundle.json", bundle_payload), lock


def test_rc1_gate_passes_only_for_one_frozen_lineage(tmp_path: Path) -> None:
    bundle, lock = _build_release_bundle(tmp_path)
    result = evaluate_rc1_release_review(bundle, tmp_path / "rc1_decision.json")

    assert result["decision"] == "RC1_PASS_FOR_MANUAL_RELEASE_REVIEW"
    assert result["passed"] is True
    assert result["campaign_fingerprint"] == lock["campaign_fingerprint"]
    assert result["live_trading_authorized"] is False
    assert result["real_capital_authorized"] is False


def test_rc1_gate_rejects_candidate_universe_mutation(tmp_path: Path) -> None:
    bundle, _ = _build_release_bundle(tmp_path)
    bundle_doc = json.loads(bundle.read_text(encoding="utf-8"))
    selection = tmp_path / bundle_doc["selection_manifest_path"]
    payload = json.loads(selection.read_text(encoding="utf-8"))
    payload["candidates"][0]["preset_sha256"] = "f" * 64
    _write_json(selection, payload)

    with pytest.raises(RegistryValidationError, match="candidate universe differs"):
        evaluate_rc1_release_review(bundle)
