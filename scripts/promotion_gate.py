#!/usr/bin/env python3
"""Evaluate a pre-registered OOS promotion policy.

Passing this gate promotes a strategy only to a forward-demo candidate. It never
authorizes live trading. The policy file must be approved and its SHA-256 must
match the hash frozen into the walk-forward plan before OOS selection.
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
    raise RegistryValidationError(f"unsupported promotion operator: {operator}")


def evaluate_promotion(
    summary_path: str | Path,
    policy_path: str | Path,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    summary_path = Path(summary_path).resolve()
    policy_path = Path(policy_path).resolve()
    summary_doc = _load_json_object(summary_path)
    policy = _load_json_object(policy_path)

    if summary_doc.get("methodology") != "ROLLING_FROZEN_OOS_AGGREGATION":
        raise RegistryValidationError("unsupported OOS summary methodology")

    if policy.get("schema_version") != 1:
        raise RegistryValidationError("unsupported promotion policy schema_version")
    policy_id = policy.get("policy_id")
    if not isinstance(policy_id, str) or not policy_id.strip():
        raise RegistryValidationError("promotion policy requires policy_id")
    approved = policy.get("approved")
    if not isinstance(approved, bool):
        raise RegistryValidationError("promotion policy approved must be true/false")

    policy_sha = sha256_file(policy_path)
    if summary_doc.get("promotion_policy_sha256") != policy_sha:
        raise RegistryValidationError(
            "promotion policy hash differs from the policy frozen before OOS execution"
        )

    criteria = policy.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        raise RegistryValidationError("promotion policy requires a non-empty criteria array")

    summary = summary_doc.get("summary")
    if not isinstance(summary, dict):
        raise RegistryValidationError("OOS summary is missing summary metrics")

    checks: list[dict[str, Any]] = []
    all_passed = True
    for rule in criteria:
        if not isinstance(rule, dict):
            raise RegistryValidationError("promotion criterion must be an object")
        metric = rule.get("metric")
        operator = rule.get("operator")
        target = rule.get("value")
        if not isinstance(metric, str) or not metric:
            raise RegistryValidationError("promotion criterion metric is required")
        if operator not in SUPPORTED_OPERATORS:
            raise RegistryValidationError(f"unsupported promotion operator: {operator!r}")
        if not isinstance(target, (int, float)) or isinstance(target, bool):
            raise RegistryValidationError("promotion criterion value must be numeric")
        observed = summary.get(metric)
        if not isinstance(observed, (int, float)) or isinstance(observed, bool):
            passed = False
            observed_value: float | None = None
        else:
            observed_value = float(observed)
            if not math.isfinite(observed_value):
                raise RegistryValidationError(f"promotion metric {metric} must be finite")
            passed = _compare(observed_value, operator, float(target))
        all_passed = all_passed and passed
        checks.append(
            {
                "metric": metric,
                "operator": operator,
                "target": float(target),
                "observed": observed_value,
                "passed": passed,
            }
        )

    if not approved:
        decision = "BLOCKED_POLICY_UNAPPROVED"
        promotable = False
    elif all_passed:
        decision = "PROMOTE_TO_FORWARD_DEMO_CANDIDATE"
        promotable = True
    else:
        decision = "DO_NOT_PROMOTE"
        promotable = False

    result = {
        "schema_version": 1,
        "decision_scope": "FORWARD_DEMO_ONLY",
        "live_trading_authorized": False,
        "decision": decision,
        "promotable": promotable,
        "policy_id": policy_id.strip(),
        "policy_sha256": policy_sha,
        "oos_summary_sha256": sha256_file(summary_path),
        "criteria": checks,
        "all_criteria_passed": all_passed,
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
    parser.add_argument(
        "--require-pass",
        action="store_true",
        help="Exit non-zero unless the decision is PROMOTE_TO_FORWARD_DEMO_CANDIDATE.",
    )
    args = parser.parse_args()
    try:
        result = evaluate_promotion(args.summary, args.policy, args.output)
    except RegistryValidationError as exc:
        parser.error(str(exc))
        return
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    if args.require_pass and not result["promotable"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
