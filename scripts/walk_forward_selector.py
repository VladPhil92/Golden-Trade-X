#!/usr/bin/env python3
"""Select an IS candidate deterministically and freeze its preset for OOS.

Official selection is permitted only when the walk-forward plan was created with
an already-approved promotion policy. The selector verifies candidate execution
identity, common provenance, exact IS boundaries and normalized evidence before
materializing an executable OOS spec.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
from pathlib import Path
from typing import Any

try:
    from scripts.experiment_registry import (
        IDENTITY_FIELDS,
        RegistryValidationError,
        identity_for,
        load_spec,
        normalize_spec,
        sha256_file,
    )
except ModuleNotFoundError:
    from experiment_registry import (
        IDENTITY_FIELDS,
        RegistryValidationError,
        identity_for,
        load_spec,
        normalize_spec,
        sha256_file,
    )

COMPARABILITY_EXCLUSIONS = {
    "preset_sha256",
    "expert_parameters",
}
SUPPORTED_OPERATORS = {">=", "<=", ">", "<", "=="}


def _load_json_object(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    with target.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise RegistryValidationError(f"JSON root must be an object: {target}")
    return value


def _numeric_summary(result: dict[str, Any], metric: str) -> float:
    summary = result.get("summary")
    if not isinstance(summary, dict) or metric not in summary:
        raise RegistryValidationError(f"normalized result missing summary metric: {metric}")
    value = summary[metric]
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise RegistryValidationError(f"summary metric {metric} must be numeric")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise RegistryValidationError(f"summary metric {metric} must be finite")
    return parsed


def _constraint_pass(value: float, operator: str, target: float) -> bool:
    if operator == ">=":
        return value >= target
    if operator == "<=":
        return value <= target
    if operator == ">":
        return value > target
    if operator == "<":
        return value < target
    if operator == "==":
        return value == target
    raise RegistryValidationError(f"unsupported operator: {operator}")


def _resolve(base: Path, raw: Any, field: str) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise RegistryValidationError(f"{field} is required")
    path = Path(raw)
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def _fold(plan: dict[str, Any], fold_id: str) -> dict[str, Any]:
    folds = plan.get("folds")
    if not isinstance(folds, list):
        raise RegistryValidationError("plan folds must be an array")
    matches = [fold for fold in folds if isinstance(fold, dict) and fold.get("fold_id") == fold_id]
    if len(matches) != 1:
        raise RegistryValidationError(f"expected exactly one fold {fold_id}, found {len(matches)}")
    return matches[0]


def _candidate_comparability(normalized: dict[str, Any]) -> dict[str, Any]:
    return {
        key: normalized.get(key)
        for key in IDENTITY_FIELDS
        if key not in COMPARABILITY_EXCLUSIONS
    }


def select_and_freeze(
    plan_path: str | Path,
    evidence_manifest_path: str | Path,
    output_dir: str | Path,
    *,
    allow_draft: bool = False,
) -> dict[str, Any]:
    plan_path = Path(plan_path).resolve()
    evidence_manifest_path = Path(evidence_manifest_path).resolve()
    plan = _load_json_object(plan_path)
    evidence = _load_json_object(evidence_manifest_path)

    if plan.get("methodology") != "ROLLING_IS_FROZEN_OOS":
        raise RegistryValidationError("unsupported walk-forward plan methodology")
    if plan.get("status") != "READY_FOR_REGISTERED_EXECUTION" and not allow_draft:
        raise RegistryValidationError(
            "official OOS freeze requires a plan created with an approved promotion policy"
        )

    fold_id = evidence.get("fold_id")
    if not isinstance(fold_id, str) or not fold_id:
        raise RegistryValidationError("evidence manifest fold_id is required")
    fold = _fold(plan, fold_id)
    is_window = fold.get("in_sample")
    oos_window = fold.get("out_of_sample")
    if not isinstance(is_window, dict) or not isinstance(oos_window, dict):
        raise RegistryValidationError("fold must contain in_sample and out_of_sample windows")

    policy = plan.get("selection_policy")
    if not isinstance(policy, dict):
        raise RegistryValidationError("plan selection_policy is missing")
    objective = policy.get("objective")
    constraints = policy.get("constraints", [])
    tie_breakers = policy.get("tie_breakers", [])
    if not isinstance(objective, dict) or not isinstance(constraints, list) or not isinstance(tie_breakers, list):
        raise RegistryValidationError("invalid selection policy")

    candidates = evidence.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise RegistryValidationError("candidate evidence manifest requires a non-empty candidates array")

    base = evidence_manifest_path.parent
    names: set[str] = set()
    records: list[dict[str, Any]] = []
    common_signature: dict[str, Any] | None = None

    needed_metrics = {str(objective.get("metric"))}
    needed_metrics.update(str(item.get("metric")) for item in constraints if isinstance(item, dict))
    needed_metrics.update(str(item.get("metric")) for item in tie_breakers if isinstance(item, dict))

    for raw in candidates:
        if not isinstance(raw, dict):
            raise RegistryValidationError("candidate entry must be an object")
        name = raw.get("name")
        if not isinstance(name, str) or not name.strip():
            raise RegistryValidationError("candidate name is required")
        name = name.strip()
        if name in names:
            raise RegistryValidationError(f"duplicate candidate name: {name}")
        names.add(name)

        spec_path = _resolve(base, raw.get("spec"), f"{name}.spec")
        results_path = _resolve(base, raw.get("normalized_results"), f"{name}.normalized_results")
        spec = load_spec(spec_path)
        normalized, _ = normalize_spec(spec, base_dir=spec_path.parent)
        identity = identity_for(normalized)

        if normalized.get("source_type") != "strategy_tester":
            raise RegistryValidationError(f"{name}: source_type must be strategy_tester")
        if normalized.get("period_start") != is_window.get("period_start"):
            raise RegistryValidationError(f"{name}: IS period_start does not match plan")
        if normalized.get("period_end") != is_window.get("period_end"):
            raise RegistryValidationError(f"{name}: IS period_end does not match plan")

        result = _load_json_object(results_path)
        if result.get("experiment_id") != identity.experiment_id:
            raise RegistryValidationError(
                f"{name}: normalized evidence experiment_id does not match spec identity"
            )

        signature = _candidate_comparability(normalized)
        if common_signature is None:
            common_signature = signature
        elif signature != common_signature:
            raise RegistryValidationError(
                f"{name}: candidate execution provenance is not comparable with the candidate set"
            )

        metrics = {metric: _numeric_summary(result, metric) for metric in sorted(needed_metrics)}
        checks: list[dict[str, Any]] = []
        eligible = True
        for rule in constraints:
            if not isinstance(rule, dict):
                raise RegistryValidationError("selection constraint must be an object")
            metric = str(rule.get("metric"))
            operator = str(rule.get("operator"))
            if operator not in SUPPORTED_OPERATORS:
                raise RegistryValidationError(f"unsupported selection operator: {operator}")
            target = rule.get("value")
            if not isinstance(target, (int, float)) or isinstance(target, bool):
                raise RegistryValidationError("selection constraint target must be numeric")
            passed = _constraint_pass(metrics[metric], operator, float(target))
            eligible = eligible and passed
            checks.append(
                {
                    "metric": metric,
                    "operator": operator,
                    "target": float(target),
                    "observed": metrics[metric],
                    "passed": passed,
                }
            )

        preset_path = Path(str(spec.get("preset_path", "")))
        if not preset_path.is_absolute():
            preset_path = spec_path.parent / preset_path
        if not preset_path.is_file():
            raise RegistryValidationError(f"{name}: preset not found: {preset_path}")

        records.append(
            {
                "name": name,
                "spec_path": spec_path,
                "spec": spec,
                "normalized": normalized,
                "identity": identity,
                "results_path": results_path,
                "metrics": metrics,
                "constraint_checks": checks,
                "eligible": eligible,
                "preset_path": preset_path.resolve(),
            }
        )

    eligible = [record for record in records if record["eligible"]]
    if not eligible:
        raise RegistryValidationError(f"{fold_id}: no IS candidate satisfies the predeclared constraints")

    ranking_rules = [objective, *tie_breakers]

    def rank_key(record: dict[str, Any]) -> tuple[Any, ...]:
        key: list[Any] = []
        for rule in ranking_rules:
            metric = str(rule.get("metric"))
            direction = rule.get("direction")
            value = record["metrics"][metric]
            if direction == "maximize":
                key.append(-value)
            elif direction == "minimize":
                key.append(value)
            else:
                raise RegistryValidationError(f"unsupported selection direction: {direction}")
        key.append(record["name"])
        return tuple(key)

    selected = sorted(eligible, key=rank_key)[0]
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)

    frozen_preset = output / "frozen_preset.set"
    shutil.copyfile(selected["preset_path"], frozen_preset)

    oos_spec = dict(selected["spec"])
    oos_spec["preset_path"] = "frozen_preset.set"
    oos_spec["expert_parameters"] = frozen_preset.name
    oos_spec["period_start"] = oos_window.get("period_start")
    oos_spec["period_end"] = oos_window.get("period_end")
    oos_spec["parent_experiment_id"] = selected["identity"].experiment_id
    oos_spec["changed_parameter"] = None
    oos_spec["changed_from"] = None
    oos_spec["changed_to"] = None
    oos_spec["notes"] = (
        f"Frozen OOS candidate for {fold_id}; selected strictly from IS evidence under "
        f"{policy.get('policy_id')}."
    )

    oos_spec_path = output / "oos_spec.json"
    oos_spec_path.write_text(
        json.dumps(oos_spec, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    normalized_oos, _ = normalize_spec(oos_spec, base_dir=output)
    oos_identity = identity_for(normalized_oos)

    selection_manifest = {
        "schema_version": 1,
        "methodology": "IS_SELECTION_THEN_FROZEN_OOS",
        "fold_id": fold_id,
        "plan_sha256": sha256_file(plan_path),
        "evidence_manifest_sha256": sha256_file(evidence_manifest_path),
        "selection_policy": policy,
        "promotion_policy_sha256": plan.get("promotion_policy", {}).get("sha256"),
        "evidence_status": ("OFFICIAL_FROZEN_OOS" if plan.get("status") == "READY_FOR_REGISTERED_EXECUTION" else "ENGINEERING_DRAFT_NOT_OFFICIAL"),
        "candidate_count": len(records),
        "eligible_candidate_count": len(eligible),
        "candidates": [
            {
                "name": record["name"],
                "experiment_id": record["identity"].experiment_id,
                "preset_sha256": record["identity"].preset_sha256,
                "eligible": record["eligible"],
                "metrics": record["metrics"],
                "constraint_checks": record["constraint_checks"],
            }
            for record in records
        ],
        "selected": {
            "name": selected["name"],
            "is_experiment_id": selected["identity"].experiment_id,
            "is_fingerprint": selected["identity"].fingerprint,
            "is_results_sha256": sha256_file(selected["results_path"]),
            "frozen_preset_sha256": sha256_file(frozen_preset),
        },
        "oos": {
            "experiment_id": oos_identity.experiment_id,
            "fingerprint": oos_identity.fingerprint,
            "period_start": normalized_oos["period_start"],
            "period_end": normalized_oos["period_end"],
            "spec": oos_spec_path.name,
            "preset": frozen_preset.name,
        },
    }
    selection_path = output / "selection_manifest.json"
    selection_path.write_text(
        json.dumps(selection_manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return selection_manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--allow-draft",
        action="store_true",
        help="Engineering-only escape hatch; generated output is not official OOS evidence.",
    )
    args = parser.parse_args()
    try:
        manifest = select_and_freeze(
            args.plan,
            args.evidence,
            args.output_dir,
            allow_draft=args.allow_draft,
        )
    except RegistryValidationError as exc:
        parser.error(str(exc))
        return
    print(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
