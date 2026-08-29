#!/usr/bin/env python3
"""Evaluate a pre-registered Golden Trade X robustness policy.

A positive result is only a robustness prerequisite for forward-demo review.
It never authorizes live trading and it preserves evidence-class distinctions.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

try:
    from scripts.experiment_registry import RegistryValidationError, sha256_file
except ModuleNotFoundError:
    from experiment_registry import RegistryValidationError, sha256_file

SUPPORTED_OPERATORS = {">=", "<=", ">", "<", "=="}
REQUIRED_EVIDENCE_CLASSES = {
    "parameter_stability": "EXECUTED_COUNTERFACTUAL",
    "broker_replication": "EXTERNAL_BROKER_REPLICATION",
    "cost_sensitivity": "MODELED_COST_SENSITIVITY",
}


def _load_json_object(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    with target.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise RegistryValidationError(f"JSON root must be an object: {target}")
    return value


def _compare(observed: float, operator: str, target: float) -> bool:
    if operator == ">=":
        return observed >= target
    if operator == "<=":
        return observed <= target
    if operator == ">":
        return observed > target
    if operator == "<":
        return observed < target
    if operator == "==":
        return observed == target
    raise RegistryValidationError(f"unsupported robustness operator: {operator}")


def evaluate_robustness(
    summary_path: str | Path,
    policy_path: str | Path,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    summary_path = Path(summary_path).resolve()
    policy_path = Path(policy_path).resolve()
    summary_doc = _load_json_object(summary_path)
    policy = _load_json_object(policy_path)

    if summary_doc.get("methodology") != "ROBUSTNESS_AGGREGATION_V1":
        raise RegistryValidationError("unsupported robustness summary methodology")
    evidence_classes = summary_doc.get("evidence_classes")
    if evidence_classes != REQUIRED_EVIDENCE_CLASSES:
        raise RegistryValidationError("robustness evidence classes are missing or misclassified")

    if policy.get("schema_version") != 1:
        raise RegistryValidationError("unsupported robustness policy schema_version")
    policy_id = policy.get("policy_id")
    if not isinstance(policy_id, str) or not policy_id.strip():
        raise RegistryValidationError("robustness policy requires policy_id")
    approved = policy.get("approved")
    if not isinstance(approved, bool):
        raise RegistryValidationError("robustness policy approved must be true/false")

    policy_sha = sha256_file(policy_path)
    if summary_doc.get("robustness_policy_sha256") != policy_sha:
        raise RegistryValidationError(
            "robustness policy hash differs from the policy frozen before robustness execution"
        )

    criteria = policy.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        raise RegistryValidationError("robustness policy requires a non-empty criteria array")
    summary = summary_doc.get("summary")
    if not isinstance(summary, dict):
        raise RegistryValidationError("robustness summary metrics missing")

    checks: list[dict[str, Any]] = []
    all_passed = True
    for rule in criteria:
        if not isinstance(rule, dict):
            raise RegistryValidationError("robustness criterion must be an object")
        metric = rule.get("metric")
        operator = rule.get("operator")
        target = rule.get("value")
        if not isinstance(metric, str) or not metric:
            raise RegistryValidationError("robustness criterion metric is required")
        if operator not in SUPPORTED_OPERATORS:
            raise RegistryValidationError(f"unsupported robustness operator: {operator!r}")
        if not isinstance(target, (int, float)) or isinstance(target, bool):
            raise RegistryValidationError("robustness criterion target must be numeric")
        raw_observed = summary.get(metric)
        if not isinstance(raw_observed, (int, float)) or isinstance(raw_observed, bool):
            observed: float | None = None
            passed = False
        else:
            observed = float(raw_observed)
            if not math.isfinite(observed):
                raise RegistryValidationError(f"robustness metric {metric} must be finite")
            passed = _compare(observed, operator, float(target))
        all_passed = all_passed and passed
        checks.append(
            {
                "metric": metric,
                "operator": operator,
                "target": float(target),
                "observed": observed,
                "passed": passed,
            }
        )

    if not approved:
        decision = "BLOCKED_POLICY_UNAPPROVED"
        robust = False
    elif all_passed:
        decision = "ROBUSTNESS_PASS_FOR_FORWARD_DEMO_REVIEW"
        robust = True
    else:
        decision = "ROBUSTNESS_FAIL"
        robust = False

    result = {
        "schema_version": 1,
        "decision_scope": "FORWARD_DEMO_REVIEW_PREREQUISITE",
        "live_trading_authorized": False,
        "decision": decision,
        "robust": robust,
        "policy_id": policy_id.strip(),
        "policy_sha256": policy_sha,
        "robustness_summary_sha256": sha256_file(summary_path),
        "campaign_id": summary_doc.get("campaign_id"),
        "baseline_experiment_id": summary_doc.get("baseline", {}).get("experiment_id"),
        "baseline_preset_sha256": summary_doc.get("baseline", {}).get("preset_sha256"),
        "criteria": checks,
        "all_criteria_passed": all_passed,
        "evidence_classes": REQUIRED_EVIDENCE_CLASSES,
    }

    if output_path is not None:
        target_path = Path(output_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(
            json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--output")
    parser.add_argument("--require-pass", action="store_true")
    args = parser.parse_args()
    try:
        result = evaluate_robustness(args.summary, args.policy, args.output)
    except RegistryValidationError as exc:
        parser.error(str(exc))
        return
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    if args.require_pass and not result["robust"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
