#!/usr/bin/env python3
"""Validate the frozen ex-ante quantitative policy bundle for Golden Trade X.

This is a repository-only gate. It validates policy syntax, supported aggregate metrics,
walk-forward geometry, approval state and cross-file references before any official OOS
evidence is generated. Passing this gate is not trading evidence and never authorizes
live capital.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import date
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
SUPPORTED_OPERATORS = {">=", "<=", ">", "<", "=="}

OOS_METRICS = {
    "fold_count",
    "total_trades",
    "total_net_profit",
    "aggregate_expected_payoff",
    "median_profit_factor",
    "min_profit_factor",
    "median_expected_payoff",
    "max_drawdown_pct",
    "profitable_fold_ratio",
    "positive_expectancy_fold_ratio",
    "median_recovery_factor",
    "median_sharpe_ratio",
    "median_win_rate",
}

ROBUSTNESS_METRICS = {
    "baseline_total_net_profit",
    "baseline_profit_factor",
    "baseline_expected_payoff",
    "baseline_max_drawdown_pct",
    "baseline_total_trades",
    "parameter_scenario_count",
    "parameter_positive_net_ratio",
    "parameter_positive_expectancy_ratio",
    "parameter_min_profit_factor",
    "parameter_median_profit_factor",
    "parameter_max_drawdown_pct",
    "parameter_min_net_profit_retention",
    "broker_count",
    "broker_positive_net_ratio",
    "broker_positive_expectancy_ratio",
    "broker_min_profit_factor",
    "broker_median_profit_factor",
    "broker_max_drawdown_pct",
    "broker_min_net_profit_retention",
    "modeled_cost_scenario_count",
    "modeled_cost_min_adjusted_net_profit",
    "modeled_cost_min_adjusted_expected_payoff",
    "modeled_cost_min_net_profit_retention",
}

FORWARD_METRICS = {
    "total_realized_r",
    "expectancy_r",
    "closed_trade_max_drawdown_r",
}


class OfficialPolicyValidationError(ValueError):
    pass


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise OfficialPolicyValidationError(f"required policy file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise OfficialPolicyValidationError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise OfficialPolicyValidationError(f"JSON root must be an object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _validate_policy(path: Path, *, role: str, allowed_metrics: set[str]) -> dict[str, Any]:
    policy = _load(path)
    if policy.get("schema_version") != SCHEMA_VERSION:
        raise OfficialPolicyValidationError(f"{role}: schema_version must be 1")
    policy_id = policy.get("policy_id")
    if not isinstance(policy_id, str) or not policy_id.strip():
        raise OfficialPolicyValidationError(f"{role}: policy_id is required")
    if "DRAFT" in policy_id.upper():
        raise OfficialPolicyValidationError(f"{role}: official policy_id must not contain DRAFT")
    if policy.get("approved") is not True:
        raise OfficialPolicyValidationError(f"{role}: official policy must be approved=true")

    criteria = policy.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        raise OfficialPolicyValidationError(f"{role}: criteria must be a non-empty array")

    seen_metrics: set[str] = set()
    for index, rule in enumerate(criteria):
        if not isinstance(rule, dict):
            raise OfficialPolicyValidationError(f"{role}: criteria[{index}] must be an object")
        metric = rule.get("metric")
        operator = rule.get("operator")
        target = rule.get("value")
        if metric not in allowed_metrics:
            raise OfficialPolicyValidationError(f"{role}: unsupported metric {metric!r}")
        if metric in seen_metrics:
            raise OfficialPolicyValidationError(f"{role}: duplicate criterion for {metric}")
        seen_metrics.add(metric)
        if operator not in SUPPORTED_OPERATORS:
            raise OfficialPolicyValidationError(f"{role}: unsupported operator {operator!r}")
        if not isinstance(target, (int, float)) or isinstance(target, bool):
            raise OfficialPolicyValidationError(f"{role}: criterion {metric} value must be numeric")
        if not math.isfinite(float(target)):
            raise OfficialPolicyValidationError(f"{role}: criterion {metric} value must be finite")

    return {
        "policy_id": policy_id.strip(),
        "approved": True,
        "file_sha256": _sha256(path),
        "criteria_count": len(criteria),
    }


def _validate_forward_observation(path: Path) -> None:
    policy = _load(path)
    observation = policy.get("observation")
    if not isinstance(observation, dict):
        raise OfficialPolicyValidationError("forward-demo: observation contract is required")
    for field in ("minimum_calendar_days", "minimum_closed_trades", "maximum_heartbeat_gap_seconds"):
        value = observation.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise OfficialPolicyValidationError(f"forward-demo: {field} must be a positive integer")
    if observation.get("require_trade_mode") != "DEMO":
        raise OfficialPolicyValidationError("forward-demo: require_trade_mode must be DEMO")
    if observation.get("require_stable_terminal_build") is not True:
        raise OfficialPolicyValidationError("forward-demo: stable terminal build must be required")


def _parse_date(raw: Any, field: str) -> date:
    if not isinstance(raw, str):
        raise OfficialPolicyValidationError(f"walk-forward: {field} must be YYYY-MM-DD")
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise OfficialPolicyValidationError(f"walk-forward: invalid {field}: {raw!r}") from exc


def _validate_walk_forward(path: Path, promotion_path: Path) -> dict[str, Any]:
    plan = _load(path)
    if plan.get("schema_version") != SCHEMA_VERSION:
        raise OfficialPolicyValidationError("walk-forward: schema_version must be 1")
    plan_id = plan.get("plan_id")
    if not isinstance(plan_id, str) or not plan_id.strip() or "DRAFT" in plan_id.upper():
        raise OfficialPolicyValidationError("walk-forward: official plan_id is required and must not contain DRAFT")
    start = _parse_date(plan.get("start_date"), "start_date")
    end = _parse_date(plan.get("end_date"), "end_date")
    if start >= end:
        raise OfficialPolicyValidationError("walk-forward: start_date must precede end_date")
    for field in ("in_sample_months", "oos_months", "step_months", "minimum_folds"):
        value = plan.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise OfficialPolicyValidationError(f"walk-forward: {field} must be a positive integer")
    embargo = plan.get("embargo_days")
    if not isinstance(embargo, int) or isinstance(embargo, bool) or embargo < 0:
        raise OfficialPolicyValidationError("walk-forward: embargo_days must be a non-negative integer")

    expected_reference = promotion_path.name
    if plan.get("promotion_policy_path") != expected_reference:
        raise OfficialPolicyValidationError(
            f"walk-forward: promotion_policy_path must reference {expected_reference}"
        )

    selection = plan.get("selection_policy")
    if not isinstance(selection, dict):
        raise OfficialPolicyValidationError("walk-forward: selection_policy is required")
    selection_id = selection.get("policy_id")
    if not isinstance(selection_id, str) or not selection_id.strip() or "DRAFT" in selection_id.upper():
        raise OfficialPolicyValidationError("walk-forward: official selection policy_id is required")
    objective = selection.get("objective")
    if not isinstance(objective, dict) or objective.get("metric") != "profit_factor" or objective.get("direction") != "maximize":
        raise OfficialPolicyValidationError("walk-forward: selection objective must maximize profit_factor")
    constraints = selection.get("constraints")
    if not isinstance(constraints, list) or not constraints:
        raise OfficialPolicyValidationError("walk-forward: selection constraints are required")

    return {
        "plan_id": plan_id.strip(),
        "selection_policy_id": selection_id.strip(),
        "file_sha256": _sha256(path),
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
    }


def validate_official_policy_bundle(config_root: str | Path = "config") -> dict[str, Any]:
    root = Path(config_root).resolve()
    promotion_path = root / "promotion_policy.v1.json"
    robustness_path = root / "robustness_policy.v1.json"
    forward_path = root / "forward_demo_policy.v1.json"
    walk_path = root / "walk_forward_plan.v1.json"

    promotion = _validate_policy(promotion_path, role="oos-promotion", allowed_metrics=OOS_METRICS)
    robustness = _validate_policy(robustness_path, role="robustness", allowed_metrics=ROBUSTNESS_METRICS)
    forward = _validate_policy(forward_path, role="forward-demo", allowed_metrics=FORWARD_METRICS)
    _validate_forward_observation(forward_path)
    walk = _validate_walk_forward(walk_path, promotion_path)

    snapshot = {
        "schema_version": 1,
        "methodology": "OFFICIAL_POLICY_BUNDLE_V1",
        "decision": "POLICY_BUNDLE_FROZEN",
        "live_trading_authorized": False,
        "real_capital_authorized": False,
        "promotion": promotion,
        "robustness": robustness,
        "forward_demo": forward,
        "walk_forward": walk,
    }
    snapshot["bundle_sha256"] = _canonical_sha(snapshot)
    return snapshot


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-root", default="config")
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        result = validate_official_policy_bundle(args.config_root)
    except OfficialPolicyValidationError as exc:
        parser.error(str(exc))
        return
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
