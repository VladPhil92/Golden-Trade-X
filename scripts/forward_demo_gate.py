#!/usr/bin/env python3
"""Apply the pre-registered forward-demo policy to validated telemetry evidence."""

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


def _load(path: str | Path) -> dict[str, Any]:
    target = Path(path).resolve()
    with target.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise RegistryValidationError(f"JSON root must be an object: {target}")
    return value


def _compare(observed: float, operator: str, target: float) -> bool:
    if operator == ">":
        return observed > target
    if operator == ">=":
        return observed >= target
    if operator == "<":
        return observed < target
    if operator == "<=":
        return observed <= target
    if operator == "==":
        return observed == target
    raise RegistryValidationError(f"unsupported forward-demo operator: {operator}")


def evaluate_forward_demo_gate(
    plan_path: str | Path,
    evaluation_path: str | Path,
    policy_path: str | Path,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    plan_path = Path(plan_path).resolve()
    evaluation_path = Path(evaluation_path).resolve()
    policy_path = Path(policy_path).resolve()
    plan = _load(plan_path)
    evaluation = _load(evaluation_path)
    policy = _load(policy_path)

    if plan.get("methodology") != "FORWARD_DEMO_FIXED_WINDOW_V1":
        raise RegistryValidationError("unsupported forward-demo plan methodology")
    if evaluation.get("methodology") != "FORWARD_DEMO_EVIDENCE_V1":
        raise RegistryValidationError("unsupported forward-demo evidence methodology")
    if plan.get("live_trading_authorized") is not False or evaluation.get("live_trading_authorized") is not False:
        raise RegistryValidationError("all forward-demo artifacts must explicitly deny live trading")
    if evaluation.get("plan_sha256") != sha256_file(plan_path):
        raise RegistryValidationError("evaluation does not hash the supplied forward-demo plan")

    plan_policy = plan.get("forward_policy")
    if not isinstance(plan_policy, dict):
        raise RegistryValidationError("forward-demo plan policy snapshot missing")
    expected_policy_sha = plan_policy.get("sha256")
    actual_policy_sha = sha256_file(policy_path)
    if expected_policy_sha != actual_policy_sha:
        raise RegistryValidationError("forward-demo policy changed after plan freeze")
    if policy.get("policy_id") != plan_policy.get("policy_id"):
        raise RegistryValidationError("forward-demo policy_id differs from frozen plan")

    reasons: list[str] = []
    checks: list[dict[str, Any]] = []
    if policy.get("approved") is not True or plan_policy.get("approved") is not True:
        reasons.append("POLICY_NOT_APPROVED")
    if plan.get("status") != "READY_FOR_FORWARD_DEMO_OBSERVATION":
        reasons.append("PLAN_NOT_READY")
    if evaluation.get("status") != "VALID_FORWARD_DEMO_EVIDENCE" or evaluation.get("valid") is not True:
        reasons.append("EVIDENCE_INVALID")

    summary = evaluation.get("summary")
    criteria = policy.get("criteria")
    if not isinstance(summary, dict):
        raise RegistryValidationError("forward-demo evaluation summary missing")
    if not isinstance(criteria, list) or not criteria:
        raise RegistryValidationError("forward-demo policy criteria missing")

    for rule in criteria:
        if not isinstance(rule, dict):
            raise RegistryValidationError("forward-demo criterion must be an object")
        metric = rule.get("metric")
        operator = rule.get("operator")
        target = rule.get("value")
        if not isinstance(metric, str) or not metric:
            raise RegistryValidationError("forward-demo criterion metric missing")
        if metric not in summary:
            raise RegistryValidationError(f"forward-demo summary missing policy metric: {metric}")
        observed = summary[metric]
        if not isinstance(observed, (int, float)) or isinstance(observed, bool):
            passed = False
        else:
            observed_float = float(observed)
            if not math.isfinite(observed_float):
                passed = False
            elif not isinstance(target, (int, float)) or isinstance(target, bool):
                raise RegistryValidationError(f"criterion target for {metric} must be numeric")
            else:
                passed = _compare(observed_float, str(operator), float(target))
        checks.append(
            {
                "metric": metric,
                "operator": operator,
                "target": target,
                "observed": observed,
                "passed": passed,
            }
        )
        if not passed:
            reasons.append(f"CRITERION_FAILED:{metric}")

    passed = not reasons
    result = {
        "schema_version": 1,
        "methodology": "FORWARD_DEMO_GATE_V1",
        "campaign_id": plan.get("campaign_id"),
        "decision": (
            "FORWARD_DEMO_PASS_FOR_RELEASE_REVIEW"
            if passed
            else ("BLOCKED_POLICY_UNAPPROVED" if "POLICY_NOT_APPROVED" in reasons else "FORWARD_DEMO_FAIL")
        ),
        "passed": passed,
        "decision_scope": "RELEASE_REVIEW_ONLY",
        "live_trading_authorized": False,
        "reasons": reasons,
        "checks": checks,
        "candidate": plan.get("candidate"),
        "plan_sha256": sha256_file(plan_path),
        "evaluation_sha256": sha256_file(evaluation_path),
        "policy_sha256": actual_policy_sha,
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
    parser.add_argument("--plan", required=True)
    parser.add_argument("--evaluation", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--output")
    parser.add_argument("--require-pass", action="store_true")
    args = parser.parse_args()
    try:
        result = evaluate_forward_demo_gate(args.plan, args.evaluation, args.policy, args.output)
    except RegistryValidationError as exc:
        parser.error(str(exc))
        return
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    if args.require_pass and not result["passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
