#!/usr/bin/env python3
"""Audit the full v3.0-rc1 evidence lineage before manual release review.

This gate proves lineage and pre-registration consistency. Even a PASS only
permits a manual release review; it never authorizes live trading or real money.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from scripts.campaign_contract import candidate_universe_sha256
    from scripts.experiment_registry import RegistryValidationError, sha256_file
except ModuleNotFoundError:
    from campaign_contract import candidate_universe_sha256
    from experiment_registry import RegistryValidationError, sha256_file


def _load(path: str | Path) -> dict[str, Any]:
    target = Path(path).resolve()
    with target.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise RegistryValidationError(f"JSON root must be an object: {target}")
    return value


def _resolve(base: Path, raw: Any, field: str) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise RegistryValidationError(f"{field} is required")
    value = Path(raw)
    if not value.is_absolute():
        value = base / value
    value = value.resolve()
    if not value.is_file():
        raise RegistryValidationError(f"{field} not found: {value}")
    return value


def _expected_changed_to(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def _verify_robustness_template(plan: dict[str, Any], lock: dict[str, Any]) -> None:
    frozen = lock.get("robustness", {}).get("template")
    if not isinstance(frozen, dict):
        raise RegistryValidationError("campaign lock lacks frozen robustness template")
    domains = plan.get("domains")
    if not isinstance(domains, dict):
        raise RegistryValidationError("robustness plan lacks domains")

    parameter_domain = domains.get("parameter_stability")
    if not isinstance(parameter_domain, dict):
        raise RegistryValidationError("robustness plan lacks parameter_stability domain")
    actual_rows = parameter_domain.get("scenarios")
    if not isinstance(actual_rows, list):
        raise RegistryValidationError("robustness plan parameter scenarios missing")
    actual_parameters = sorted(
        [
            {
                "name": row.get("name"),
                "parameter": row.get("parameter"),
                "changed_to": row.get("changed_to"),
            }
            for row in actual_rows
            if isinstance(row, dict)
        ],
        key=lambda row: str(row.get("name")),
    )
    expected_parameters = sorted(
        [
            {
                "name": row.get("name"),
                "parameter": row.get("parameter"),
                "changed_to": _expected_changed_to(row.get("value")),
            }
            for row in frozen.get("parameter_scenarios", [])
            if isinstance(row, dict)
        ],
        key=lambda row: str(row.get("name")),
    )
    if actual_parameters != expected_parameters:
        raise RegistryValidationError("robustness parameter scenarios drifted after campaign freeze")

    broker_domain = domains.get("broker_replication")
    expected_broker = frozen.get("broker_requirements")
    if not isinstance(broker_domain, dict) or not isinstance(expected_broker, dict):
        raise RegistryValidationError("robustness broker contract missing")
    if sorted(broker_domain.get("required_labels", [])) != sorted(expected_broker.get("required_labels", [])):
        raise RegistryValidationError("robustness broker labels drifted after campaign freeze")
    if broker_domain.get("minimum_distinct_brokers") != expected_broker.get("minimum_distinct_brokers"):
        raise RegistryValidationError("robustness minimum broker count drifted after campaign freeze")

    cost_domain = domains.get("cost_sensitivity")
    if not isinstance(cost_domain, dict):
        raise RegistryValidationError("robustness cost_sensitivity domain missing")
    actual_costs = sorted(
        [
            {
                "name": row.get("name"),
                "cost_per_trade_currency": float(row.get("cost_per_trade_currency")),
            }
            for row in cost_domain.get("scenarios", [])
            if isinstance(row, dict) and isinstance(row.get("cost_per_trade_currency"), (int, float))
        ],
        key=lambda row: str(row.get("name")),
    )
    expected_costs = sorted(
        [
            {
                "name": row.get("name"),
                "cost_per_trade_currency": float(row.get("cost_per_trade_currency")),
            }
            for row in frozen.get("modeled_cost_scenarios", [])
            if isinstance(row, dict) and isinstance(row.get("cost_per_trade_currency"), (int, float))
        ],
        key=lambda row: str(row.get("name")),
    )
    if actual_costs != expected_costs:
        raise RegistryValidationError("robustness modeled-cost scenarios drifted after campaign freeze")


def evaluate_rc1_release_review(
    bundle_path: str | Path,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    bundle_path = Path(bundle_path).resolve()
    bundle = _load(bundle_path)
    base = bundle_path.parent

    paths = {
        name: _resolve(base, bundle.get(name), name)
        for name in (
            "campaign_lock_path",
            "selection_manifest_path",
            "oos_summary_path",
            "promotion_decision_path",
            "robustness_plan_path",
            "robustness_summary_path",
            "robustness_decision_path",
            "readiness_path",
            "forward_plan_path",
            "forward_evaluation_path",
            "forward_gate_path",
        )
    }
    docs = {name: _load(path) for name, path in paths.items()}

    lock = docs["campaign_lock_path"]
    selection = docs["selection_manifest_path"]
    oos = docs["oos_summary_path"]
    promotion = docs["promotion_decision_path"]
    robust_plan = docs["robustness_plan_path"]
    robust_summary = docs["robustness_summary_path"]
    robust_decision = docs["robustness_decision_path"]
    readiness = docs["readiness_path"]
    forward_plan = docs["forward_plan_path"]
    forward_eval = docs["forward_evaluation_path"]
    forward_gate = docs["forward_gate_path"]

    if lock.get("methodology") != "OFFICIAL_VALIDATION_CAMPAIGN_FREEZE_V1":
        raise RegistryValidationError("unsupported campaign lock methodology")
    if lock.get("status") != "OFFICIAL_CAMPAIGN_FROZEN":
        raise RegistryValidationError("rc1 release review requires an OFFICIAL_CAMPAIGN_FROZEN lock")
    if lock.get("live_trading_authorized") is not False:
        raise RegistryValidationError("campaign lock must explicitly deny live trading")

    walk = lock.get("walk_forward")
    robustness_lock = lock.get("robustness")
    forward_lock = lock.get("forward_demo")
    universe = lock.get("candidate_universe")
    if not all(isinstance(value, dict) for value in (walk, robustness_lock, forward_lock, universe)):
        raise RegistryValidationError("campaign lock is incomplete")

    plan_sha = walk.get("plan_sha256")
    promotion_policy_sha = walk.get("promotion_policy", {}).get("sha256")
    robustness_policy_sha = robustness_lock.get("policy", {}).get("sha256")
    forward_policy_sha = forward_lock.get("policy", {}).get("sha256")
    universe_sha = universe.get("sha256")

    if selection.get("methodology") != "IS_SELECTION_THEN_FROZEN_OOS":
        raise RegistryValidationError("unsupported selection manifest methodology")
    if selection.get("evidence_status") != "OFFICIAL_FROZEN_OOS":
        raise RegistryValidationError("selection manifest is not official frozen OOS evidence")
    if selection.get("plan_sha256") != plan_sha:
        raise RegistryValidationError("selection manifest does not descend from the frozen walk-forward plan")
    if selection.get("promotion_policy_sha256") != promotion_policy_sha:
        raise RegistryValidationError("selection manifest promotion policy differs from campaign lock")
    if candidate_universe_sha256(selection.get("candidates")) != universe_sha:
        raise RegistryValidationError("selection candidate universe differs from campaign lock")

    selected = selection.get("selected")
    selected_oos = selection.get("oos")
    if not isinstance(selected, dict) or not isinstance(selected_oos, dict):
        raise RegistryValidationError("selection manifest lacks selected/OOS identity")
    candidate_preset_sha = selected.get("frozen_preset_sha256")
    candidate_id = selected_oos.get("experiment_id")
    fold_id = selection.get("fold_id")

    if oos.get("methodology") != "ROLLING_FROZEN_OOS_AGGREGATION":
        raise RegistryValidationError("unsupported OOS summary methodology")
    if oos.get("plan_sha256") != plan_sha:
        raise RegistryValidationError("OOS summary does not use the frozen walk-forward plan")
    if oos.get("promotion_policy_sha256") != promotion_policy_sha:
        raise RegistryValidationError("OOS summary promotion policy differs from campaign lock")
    if oos.get("candidate_universe_sha256") != universe_sha:
        raise RegistryValidationError("OOS aggregate candidate universe differs from campaign lock")
    fold_matches = [
        row for row in oos.get("folds", [])
        if isinstance(row, dict)
        and row.get("fold_id") == fold_id
        and row.get("oos_experiment_id") == candidate_id
    ]
    if len(fold_matches) != 1:
        raise RegistryValidationError("selected robustness candidate is not present in frozen OOS aggregate")
    if fold_matches[0].get("selection_manifest_sha256") != sha256_file(paths["selection_manifest_path"]):
        raise RegistryValidationError("OOS aggregate hashes a different selection manifest")

    if promotion.get("oos_summary_sha256") != sha256_file(paths["oos_summary_path"]):
        raise RegistryValidationError("promotion decision hashes a different OOS summary")
    if promotion.get("policy_sha256") != promotion_policy_sha:
        raise RegistryValidationError("promotion decision policy differs from campaign lock")
    if promotion.get("live_trading_authorized") is not False:
        raise RegistryValidationError("promotion decision must explicitly deny live trading")

    if robust_plan.get("methodology") != "ROBUSTNESS_V1":
        raise RegistryValidationError("unsupported robustness plan methodology")
    if robust_plan.get("robustness_policy", {}).get("sha256") != robustness_policy_sha:
        raise RegistryValidationError("robustness plan policy differs from campaign lock")
    base_identity = robust_plan.get("base")
    if not isinstance(base_identity, dict):
        raise RegistryValidationError("robustness plan baseline identity missing")
    if base_identity.get("experiment_id") != candidate_id:
        raise RegistryValidationError("robustness baseline is not the selected frozen OOS candidate")
    if base_identity.get("preset_sha256") != candidate_preset_sha:
        raise RegistryValidationError("robustness baseline preset differs from selected OOS preset")
    if str(base_identity.get("git_sha", "")).lower() != str(lock.get("build_id", "")).lower():
        raise RegistryValidationError("robustness baseline build differs from campaign lock")
    _verify_robustness_template(robust_plan, lock)

    if robust_summary.get("methodology") != "ROBUSTNESS_AGGREGATION_V1":
        raise RegistryValidationError("unsupported robustness summary methodology")
    if robust_summary.get("plan_sha256") != sha256_file(paths["robustness_plan_path"]):
        raise RegistryValidationError("robustness summary hashes a different plan")
    if robust_summary.get("robustness_policy_sha256") != robustness_policy_sha:
        raise RegistryValidationError("robustness summary policy differs from campaign lock")
    if robust_summary.get("baseline", {}).get("experiment_id") != candidate_id:
        raise RegistryValidationError("robustness summary baseline candidate mismatch")
    if robust_summary.get("baseline", {}).get("preset_sha256") != candidate_preset_sha:
        raise RegistryValidationError("robustness summary baseline preset mismatch")

    if robust_decision.get("robustness_summary_sha256") != sha256_file(paths["robustness_summary_path"]):
        raise RegistryValidationError("robustness decision hashes a different summary")
    if robust_decision.get("policy_sha256") != robustness_policy_sha:
        raise RegistryValidationError("robustness decision policy differs from campaign lock")
    if robust_decision.get("live_trading_authorized") is not False:
        raise RegistryValidationError("robustness decision must explicitly deny live trading")

    if readiness.get("methodology") != "FORWARD_DEMO_READINESS_V1":
        raise RegistryValidationError("unsupported readiness methodology")
    evidence = readiness.get("evidence")
    if not isinstance(evidence, dict):
        raise RegistryValidationError("readiness evidence hashes missing")
    expected_evidence_hashes = {
        "oos_summary_sha256": sha256_file(paths["oos_summary_path"]),
        "promotion_decision_sha256": sha256_file(paths["promotion_decision_path"]),
        "selection_manifest_sha256": sha256_file(paths["selection_manifest_path"]),
        "robustness_summary_sha256": sha256_file(paths["robustness_summary_path"]),
        "robustness_decision_sha256": sha256_file(paths["robustness_decision_path"]),
    }
    if any(evidence.get(key) != value for key, value in expected_evidence_hashes.items()):
        raise RegistryValidationError("readiness does not hash the supplied official evidence chain")
    if readiness.get("candidate", {}).get("experiment_id") != candidate_id:
        raise RegistryValidationError("readiness candidate mismatch")
    if readiness.get("candidate", {}).get("preset_sha256") != candidate_preset_sha:
        raise RegistryValidationError("readiness preset mismatch")
    if readiness.get("live_trading_authorized") is not False:
        raise RegistryValidationError("readiness must explicitly deny live trading")

    if forward_plan.get("methodology") != "FORWARD_DEMO_FIXED_WINDOW_V1":
        raise RegistryValidationError("unsupported forward-demo plan methodology")
    if forward_plan.get("candidate", {}).get("experiment_id") != candidate_id:
        raise RegistryValidationError("forward-demo plan candidate mismatch")
    if forward_plan.get("candidate", {}).get("preset_sha256") != candidate_preset_sha:
        raise RegistryValidationError("forward-demo plan preset mismatch")
    if forward_plan.get("candidate", {}).get("readiness_sha256") != sha256_file(paths["readiness_path"]):
        raise RegistryValidationError("forward-demo plan hashes a different readiness decision")
    if forward_plan.get("forward_policy", {}).get("sha256") != forward_policy_sha:
        raise RegistryValidationError("forward-demo policy differs from campaign lock")
    if str(forward_plan.get("runtime_contract", {}).get("build_id", "")).lower() != str(lock.get("build_id", "")).lower():
        raise RegistryValidationError("forward-demo runtime build differs from campaign lock")
    if forward_plan.get("live_trading_authorized") is not False:
        raise RegistryValidationError("forward-demo plan must explicitly deny live trading")

    if forward_eval.get("methodology") != "FORWARD_DEMO_EVIDENCE_V1":
        raise RegistryValidationError("unsupported forward-demo evidence methodology")
    if forward_eval.get("plan_sha256") != sha256_file(paths["forward_plan_path"]):
        raise RegistryValidationError("forward evidence hashes a different forward plan")
    if forward_eval.get("live_trading_authorized") is not False:
        raise RegistryValidationError("forward evidence must explicitly deny live trading")

    if forward_gate.get("methodology") != "FORWARD_DEMO_GATE_V1":
        raise RegistryValidationError("unsupported forward-demo gate methodology")
    if forward_gate.get("plan_sha256") != sha256_file(paths["forward_plan_path"]):
        raise RegistryValidationError("forward gate hashes a different plan")
    if forward_gate.get("evaluation_sha256") != sha256_file(paths["forward_evaluation_path"]):
        raise RegistryValidationError("forward gate hashes different evaluation evidence")
    if forward_gate.get("policy_sha256") != forward_policy_sha:
        raise RegistryValidationError("forward gate policy differs from campaign lock")
    if forward_gate.get("live_trading_authorized") is not False:
        raise RegistryValidationError("forward gate must explicitly deny live trading")

    reasons: list[str] = []
    if promotion.get("decision") != "PROMOTE_TO_FORWARD_DEMO_CANDIDATE" or promotion.get("promotable") is not True:
        reasons.append("OOS_PROMOTION_NOT_PASSED")
    if robust_decision.get("decision") != "ROBUSTNESS_PASS_FOR_FORWARD_DEMO_REVIEW" or robust_decision.get("robust") is not True:
        reasons.append("ROBUSTNESS_NOT_PASSED")
    if readiness.get("decision") != "READY_FOR_FORWARD_DEMO" or readiness.get("ready") is not True:
        reasons.append("FORWARD_READINESS_NOT_PASSED")
    if forward_eval.get("status") != "VALID_FORWARD_DEMO_EVIDENCE" or forward_eval.get("valid") is not True:
        reasons.append("FORWARD_EVIDENCE_INVALID")
    if forward_gate.get("decision") != "FORWARD_DEMO_PASS_FOR_RELEASE_REVIEW" or forward_gate.get("passed") is not True:
        reasons.append("FORWARD_GATE_NOT_PASSED")

    passed = not reasons
    result = {
        "schema_version": 1,
        "methodology": "RC1_RELEASE_REVIEW_GATE_V1",
        "campaign_id": lock.get("campaign_id"),
        "campaign_fingerprint": lock.get("campaign_fingerprint"),
        "decision": (
            "RC1_PASS_FOR_MANUAL_RELEASE_REVIEW"
            if passed
            else "RC1_EVIDENCE_NOT_PROMOTABLE"
        ),
        "passed": passed,
        "decision_scope": "MANUAL_RELEASE_REVIEW_ONLY",
        "live_trading_authorized": False,
        "real_capital_authorized": False,
        "reasons": reasons,
        "candidate": {
            "experiment_id": candidate_id,
            "preset_sha256": candidate_preset_sha,
            "source_fold_id": fold_id,
            "build_id": lock.get("build_id"),
        },
        "evidence": {name: sha256_file(path) for name, path in paths.items()},
    }

    if output_path is not None:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--output")
    parser.add_argument("--require-pass", action="store_true")
    args = parser.parse_args()
    try:
        result = evaluate_rc1_release_review(args.bundle, args.output)
    except RegistryValidationError as exc:
        parser.error(str(exc))
        return
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    if args.require_pass and not result["passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
