#!/usr/bin/env python3
"""Aggregate registered OOS fold evidence without stitching an artificial equity curve."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path
from typing import Any

try:
    from scripts.experiment_registry import (
        RegistryValidationError,
        identity_for,
        load_spec,
        normalize_spec,
        sha256_file,
    )
except ModuleNotFoundError:
    from experiment_registry import (
        RegistryValidationError,
        identity_for,
        load_spec,
        normalize_spec,
        sha256_file,
    )

REQUIRED_METRICS = (
    "total_net_profit",
    "profit_factor",
    "expected_payoff",
    "max_drawdown_pct",
    "total_trades",
)


def _load_json_object(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    with target.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise RegistryValidationError(f"JSON root must be an object: {target}")
    return value


def _resolve(base: Path, raw: Any, field: str) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise RegistryValidationError(f"{field} is required")
    path = Path(raw)
    if not path.is_absolute():
        path = base / path
    return path.resolve()


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


def _fold_map(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    folds = plan.get("folds")
    if not isinstance(folds, list) or not folds:
        raise RegistryValidationError("plan folds must be a non-empty array")
    result: dict[str, dict[str, Any]] = {}
    for fold in folds:
        if not isinstance(fold, dict):
            raise RegistryValidationError("plan fold must be an object")
        fold_id = fold.get("fold_id")
        if not isinstance(fold_id, str) or not fold_id:
            raise RegistryValidationError("plan fold_id is required")
        if fold_id in result:
            raise RegistryValidationError(f"duplicate plan fold_id: {fold_id}")
        result[fold_id] = fold
    return result


def aggregate_oos_evidence(
    plan_path: str | Path,
    evidence_manifest_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    plan_path = Path(plan_path).resolve()
    evidence_manifest_path = Path(evidence_manifest_path).resolve()
    plan = _load_json_object(plan_path)
    evidence = _load_json_object(evidence_manifest_path)

    if plan.get("methodology") != "ROLLING_IS_FROZEN_OOS":
        raise RegistryValidationError("unsupported walk-forward plan methodology")
    folds = _fold_map(plan)

    entries = evidence.get("folds")
    if not isinstance(entries, list):
        raise RegistryValidationError("OOS evidence manifest folds must be an array")
    by_id: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise RegistryValidationError("OOS evidence fold entry must be an object")
        fold_id = entry.get("fold_id")
        if not isinstance(fold_id, str) or not fold_id:
            raise RegistryValidationError("OOS evidence fold_id is required")
        if fold_id in by_id:
            raise RegistryValidationError(f"duplicate OOS evidence fold_id: {fold_id}")
        by_id[fold_id] = entry

    missing = sorted(set(folds) - set(by_id))
    extra = sorted(set(by_id) - set(folds))
    if missing or extra:
        raise RegistryValidationError(
            f"OOS evidence must cover every planned fold exactly once; missing={missing}, extra={extra}"
        )

    base = evidence_manifest_path.parent
    fold_results: list[dict[str, Any]] = []

    for fold_id in sorted(folds):
        fold = folds[fold_id]
        entry = by_id[fold_id]
        selection_path = _resolve(base, entry.get("selection_manifest"), f"{fold_id}.selection_manifest")
        oos_spec_path = _resolve(base, entry.get("oos_spec"), f"{fold_id}.oos_spec")
        results_path = _resolve(base, entry.get("normalized_results"), f"{fold_id}.normalized_results")

        selection = _load_json_object(selection_path)
        if selection.get("fold_id") != fold_id:
            raise RegistryValidationError(f"{fold_id}: selection manifest fold mismatch")
        if selection.get("plan_sha256") != sha256_file(plan_path):
            raise RegistryValidationError(f"{fold_id}: selection manifest was produced from a different plan")
        if selection.get("promotion_policy_sha256") != plan.get("promotion_policy", {}).get("sha256"):
            raise RegistryValidationError(f"{fold_id}: promotion policy hash mismatch")

        oos_spec = load_spec(oos_spec_path)
        normalized_oos, _ = normalize_spec(oos_spec, base_dir=oos_spec_path.parent)
        oos_identity = identity_for(normalized_oos)

        planned_oos = fold.get("out_of_sample")
        if not isinstance(planned_oos, dict):
            raise RegistryValidationError(f"{fold_id}: plan missing out_of_sample window")
        if normalized_oos.get("period_start") != planned_oos.get("period_start"):
            raise RegistryValidationError(f"{fold_id}: OOS period_start does not match plan")
        if normalized_oos.get("period_end") != planned_oos.get("period_end"):
            raise RegistryValidationError(f"{fold_id}: OOS period_end does not match plan")

        selected = selection.get("selected")
        oos_meta = selection.get("oos")
        if not isinstance(selected, dict) or not isinstance(oos_meta, dict):
            raise RegistryValidationError(f"{fold_id}: incomplete selection manifest")
        if oos_meta.get("experiment_id") != oos_identity.experiment_id:
            raise RegistryValidationError(f"{fold_id}: OOS spec identity differs from frozen selection")
        if selected.get("frozen_preset_sha256") != normalized_oos.get("preset_sha256"):
            raise RegistryValidationError(f"{fold_id}: OOS preset hash differs from frozen IS selection")

        result = _load_json_object(results_path)
        if result.get("experiment_id") != oos_identity.experiment_id:
            raise RegistryValidationError(f"{fold_id}: OOS normalized evidence experiment_id mismatch")

        metrics = {metric: _numeric_summary(result, metric) for metric in REQUIRED_METRICS}
        optional: dict[str, float] = {}
        for metric in ("win_rate", "recovery_factor", "sharpe_ratio"):
            summary = result.get("summary")
            if isinstance(summary, dict) and metric in summary:
                optional[metric] = _numeric_summary(result, metric)

        fold_results.append(
            {
                "fold_id": fold_id,
                "is_experiment_id": selected.get("is_experiment_id"),
                "oos_experiment_id": oos_identity.experiment_id,
                "oos_results_sha256": sha256_file(results_path),
                "metrics": {**metrics, **optional},
            }
        )

    total_trades = int(round(sum(item["metrics"]["total_trades"] for item in fold_results)))
    total_net_profit = sum(item["metrics"]["total_net_profit"] for item in fold_results)
    profitable = sum(1 for item in fold_results if item["metrics"]["total_net_profit"] > 0)
    positive_expectancy = sum(1 for item in fold_results if item["metrics"]["expected_payoff"] > 0)
    profit_factors = [item["metrics"]["profit_factor"] for item in fold_results]
    expected_payoffs = [item["metrics"]["expected_payoff"] for item in fold_results]
    drawdowns = [item["metrics"]["max_drawdown_pct"] for item in fold_results]

    summary: dict[str, Any] = {
        "fold_count": len(fold_results),
        "total_trades": total_trades,
        "total_net_profit": total_net_profit,
        "aggregate_expected_payoff": (total_net_profit / total_trades) if total_trades > 0 else None,
        "median_profit_factor": statistics.median(profit_factors),
        "min_profit_factor": min(profit_factors),
        "median_expected_payoff": statistics.median(expected_payoffs),
        "max_drawdown_pct": max(drawdowns),
        "profitable_fold_ratio": profitable / len(fold_results),
        "positive_expectancy_fold_ratio": positive_expectancy / len(fold_results),
    }

    if all("recovery_factor" in item["metrics"] for item in fold_results):
        summary["median_recovery_factor"] = statistics.median(
            item["metrics"]["recovery_factor"] for item in fold_results
        )
    if all("sharpe_ratio" in item["metrics"] for item in fold_results):
        summary["median_sharpe_ratio"] = statistics.median(
            item["metrics"]["sharpe_ratio"] for item in fold_results
        )
    if all("win_rate" in item["metrics"] for item in fold_results):
        summary["median_win_rate"] = statistics.median(
            item["metrics"]["win_rate"] for item in fold_results
        )

    output = {
        "schema_version": 1,
        "methodology": "ROLLING_FROZEN_OOS_AGGREGATION",
        "equity_curve_semantics": (
            "Fold reports are aggregated descriptively; no synthetic stitched equity curve is constructed. "
            "max_drawdown_pct is the worst observed fold drawdown, not continuous portfolio drawdown."
        ),
        "plan_id": plan.get("plan_id"),
        "plan_sha256": sha256_file(plan_path),
        "promotion_policy_sha256": plan.get("promotion_policy", {}).get("sha256"),
        "summary": summary,
        "folds": fold_results,
    }

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(output, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--output", default="data/research/walk_forward/oos_summary.json")
    args = parser.parse_args()
    try:
        result = aggregate_oos_evidence(args.plan, args.evidence, args.output)
    except RegistryValidationError as exc:
        parser.error(str(exc))
        return
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
