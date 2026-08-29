#!/usr/bin/env python3
"""Plan deterministic rolling in-sample/out-of-sample validation windows.

The planner does not execute MetaTrader and does not select parameters. It locks
the temporal geometry, the in-sample selection policy, and the exact promotion
policy hash before any official OOS run may be frozen.
"""

from __future__ import annotations

import argparse
import json
from calendar import monthrange
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.experiment_registry import RegistryValidationError, sha256_file
except ModuleNotFoundError:
    from experiment_registry import RegistryValidationError, sha256_file

PLAN_SCHEMA_VERSION = 1
SUPPORTED_METRICS = {
    "total_net_profit",
    "profit_factor",
    "expected_payoff",
    "max_drawdown_pct",
    "total_trades",
    "win_rate",
    "recovery_factor",
    "sharpe_ratio",
}
SUPPORTED_OPERATORS = {">=", "<=", ">", "<", "=="}
SUPPORTED_DIRECTIONS = {"maximize", "minimize"}


def _load_json_object(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    with target.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise RegistryValidationError(f"JSON root must be an object: {target}")
    return value


def _parse_date(value: Any, field: str) -> date:
    if not isinstance(value, str):
        raise RegistryValidationError(f"{field} must be YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise RegistryValidationError(f"{field} must be YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise RegistryValidationError(f"{field} must be canonical YYYY-MM-DD")
    return parsed


def _positive_int(value: Any, field: str, *, allow_zero: bool = False) -> int:
    if isinstance(value, bool):
        raise RegistryValidationError(f"{field} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise RegistryValidationError(f"{field} must be an integer") from exc
    if str(value).strip() != str(parsed) and not isinstance(value, int):
        raise RegistryValidationError(f"{field} must be an integer")
    minimum = 0 if allow_zero else 1
    if parsed < minimum:
        comparator = ">= 0" if allow_zero else "> 0"
        raise RegistryValidationError(f"{field} must be {comparator}")
    return parsed


def _add_months(value: date, months: int) -> date:
    index = value.year * 12 + value.month - 1 + months
    year, month_index = divmod(index, 12)
    month = month_index + 1
    day = min(value.day, monthrange(year, month)[1])
    return date(year, month, day)


def _period_bounds(start: date, end_exclusive: date) -> tuple[str, str]:
    if end_exclusive <= start:
        raise RegistryValidationError("period end must be after period start")
    start_dt = datetime.combine(start, time.min, tzinfo=timezone.utc)
    end_dt = datetime.combine(end_exclusive, time.min, tzinfo=timezone.utc) - timedelta(seconds=1)
    return (
        start_dt.isoformat().replace("+00:00", "Z"),
        end_dt.isoformat().replace("+00:00", "Z"),
    )


def _validate_metric_rule(rule: Any, *, selection: bool = False) -> dict[str, Any]:
    if not isinstance(rule, dict):
        raise RegistryValidationError("metric rule must be an object")
    metric = rule.get("metric")
    if not isinstance(metric, str) or metric not in SUPPORTED_METRICS:
        raise RegistryValidationError(f"unsupported metric: {metric!r}")
    if selection:
        direction = rule.get("direction")
        if direction not in SUPPORTED_DIRECTIONS:
            raise RegistryValidationError(f"unsupported direction: {direction!r}")
        return {"metric": metric, "direction": direction}

    operator = rule.get("operator")
    if operator not in SUPPORTED_OPERATORS:
        raise RegistryValidationError(f"unsupported operator: {operator!r}")
    value = rule.get("value")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise RegistryValidationError("constraint value must be numeric")
    return {"metric": metric, "operator": operator, "value": float(value)}


def validate_selection_policy(policy: Any) -> dict[str, Any]:
    if not isinstance(policy, dict):
        raise RegistryValidationError("selection_policy must be an object")
    policy_id = policy.get("policy_id")
    if not isinstance(policy_id, str) or not policy_id.strip():
        raise RegistryValidationError("selection_policy.policy_id is required")
    objective = _validate_metric_rule(policy.get("objective"), selection=True)
    constraints_raw = policy.get("constraints", [])
    if not isinstance(constraints_raw, list):
        raise RegistryValidationError("selection_policy.constraints must be an array")
    tie_raw = policy.get("tie_breakers", [])
    if not isinstance(tie_raw, list):
        raise RegistryValidationError("selection_policy.tie_breakers must be an array")
    constraints = [_validate_metric_rule(item) for item in constraints_raw]
    tie_breakers = [_validate_metric_rule(item, selection=True) for item in tie_raw]
    seen = {objective["metric"]}
    for item in tie_breakers:
        if item["metric"] in seen:
            raise RegistryValidationError("selection objective/tie-breaker metrics must be unique")
        seen.add(item["metric"])
    return {
        "policy_id": policy_id.strip(),
        "objective": objective,
        "constraints": constraints,
        "tie_breakers": tie_breakers,
        "final_tie_breaker": "candidate_name_ascending",
    }


def _promotion_policy_snapshot(config_path: Path, config: dict[str, Any]) -> dict[str, Any]:
    raw_path = config.get("promotion_policy_path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise RegistryValidationError("promotion_policy_path is required")
    policy_path = Path(raw_path)
    if not policy_path.is_absolute():
        policy_path = config_path.parent / policy_path
    policy = _load_json_object(policy_path)
    policy_id = policy.get("policy_id")
    if not isinstance(policy_id, str) or not policy_id.strip():
        raise RegistryValidationError("promotion policy requires policy_id")
    approved = policy.get("approved")
    if not isinstance(approved, bool):
        raise RegistryValidationError("promotion policy approved must be true/false")
    return {
        "path": Path(raw_path).as_posix(),
        "sha256": sha256_file(policy_path),
        "policy_id": policy_id.strip(),
        "approved": approved,
    }


def generate_walk_forward_plan(config_path: str | Path, output_path: str | Path) -> dict[str, Any]:
    config_path = Path(config_path).resolve()
    config = _load_json_object(config_path)

    plan_id = config.get("plan_id")
    if not isinstance(plan_id, str) or not plan_id.strip():
        raise RegistryValidationError("plan_id is required")

    start = _parse_date(config.get("start_date"), "start_date")
    end_exclusive = _parse_date(config.get("end_date"), "end_date")
    if end_exclusive <= start:
        raise RegistryValidationError("end_date must be after start_date (end is exclusive)")

    is_months = _positive_int(config.get("in_sample_months"), "in_sample_months")
    oos_months = _positive_int(config.get("oos_months"), "oos_months")
    step_months = _positive_int(config.get("step_months"), "step_months")
    embargo_days = _positive_int(config.get("embargo_days", 0), "embargo_days", allow_zero=True)
    minimum_folds = _positive_int(config.get("minimum_folds", 1), "minimum_folds")

    if step_months < oos_months:
        raise RegistryValidationError(
            "step_months must be >= oos_months so official OOS windows never overlap"
        )

    selection_policy = validate_selection_policy(config.get("selection_policy"))
    promotion_policy = _promotion_policy_snapshot(config_path, config)

    folds: list[dict[str, Any]] = []
    cursor = start
    index = 1
    while True:
        is_start = cursor
        is_end_exclusive = _add_months(is_start, is_months)
        oos_start = is_end_exclusive + timedelta(days=embargo_days)
        oos_end_exclusive = _add_months(oos_start, oos_months)
        if oos_end_exclusive > end_exclusive:
            break

        is_period_start, is_period_end = _period_bounds(is_start, is_end_exclusive)
        oos_period_start, oos_period_end = _period_bounds(oos_start, oos_end_exclusive)
        folds.append(
            {
                "fold_id": f"WF{index:03d}",
                "in_sample": {
                    "start_date": is_start.isoformat(),
                    "end_date_exclusive": is_end_exclusive.isoformat(),
                    "period_start": is_period_start,
                    "period_end": is_period_end,
                },
                "embargo_days": embargo_days,
                "out_of_sample": {
                    "start_date": oos_start.isoformat(),
                    "end_date_exclusive": oos_end_exclusive.isoformat(),
                    "period_start": oos_period_start,
                    "period_end": oos_period_end,
                },
            }
        )
        cursor = _add_months(cursor, step_months)
        index += 1

    if len(folds) < minimum_folds:
        raise RegistryValidationError(
            f"plan produced {len(folds)} folds, below minimum_folds={minimum_folds}"
        )

    manifest = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "methodology": "ROLLING_IS_FROZEN_OOS",
        "plan_id": plan_id.strip(),
        "status": (
            "READY_FOR_REGISTERED_EXECUTION"
            if promotion_policy["approved"]
            else "DRAFT_POLICY_UNAPPROVED"
        ),
        "date_semantics": "start inclusive; end_date_exclusive exclusive; registry period_end is one second before exclusive boundary",
        "geometry": {
            "start_date": start.isoformat(),
            "end_date_exclusive": end_exclusive.isoformat(),
            "in_sample_months": is_months,
            "oos_months": oos_months,
            "step_months": step_months,
            "embargo_days": embargo_days,
            "minimum_folds": minimum_folds,
        },
        "selection_policy": selection_policy,
        "promotion_policy": promotion_policy,
        "folds": folds,
    }

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", default="data/research/walk_forward/plan_manifest.json")
    args = parser.parse_args()
    try:
        manifest = generate_walk_forward_plan(args.config, args.output)
    except RegistryValidationError as exc:
        parser.error(str(exc))
        return
    print(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
