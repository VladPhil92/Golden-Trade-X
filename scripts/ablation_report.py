#!/usr/bin/env python3
"""Build a descriptive baseline-vs-ablation report from registered MT5 evidence.

This report deliberately does not label a component statistically significant.
It only computes reproducible deltas from completed, normalized experiments.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

try:
    from scripts.experiment_registry import (
        RegistryValidationError,
        connect_registry,
        get_experiment,
    )
except ModuleNotFoundError:
    from experiment_registry import RegistryValidationError, connect_registry, get_experiment

COMPARISON_METRICS = (
    "total_net_profit",
    "profit_factor",
    "expected_payoff",
    "max_drawdown_pct",
    "total_trades",
    "win_rate",
    "recovery_factor",
    "sharpe_ratio",
)

METRIC_PREFERENCE = {
    "total_net_profit": "higher",
    "profit_factor": "higher",
    "expected_payoff": "higher",
    "max_drawdown_pct": "lower",
    "total_trades": "descriptive",
    "win_rate": "descriptive",
    "recovery_factor": "higher",
    "sharpe_ratio": "higher",
}


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RegistryValidationError(f"JSON root must be an object: {path}")
    return value


def _load_normalized_result(record: dict[str, Any], artifact_root: Path) -> dict[str, Any]:
    if record.get("status") != "COMPLETED":
        raise RegistryValidationError(
            f"experiment {record.get('experiment_id')} is not COMPLETED ({record.get('status')})"
        )
    artifact = record.get("artifacts", {}).get("normalized_results")
    if not isinstance(artifact, dict) or not isinstance(artifact.get("path"), str):
        raise RegistryValidationError(
            f"experiment {record.get('experiment_id')} has no normalized_results artifact"
        )
    path = Path(artifact["path"])
    if not path.is_absolute():
        path = artifact_root / path
    if not path.is_file():
        raise RegistryValidationError(f"normalized result artifact not found: {path}")
    result = _load_json(path)
    if result.get("experiment_id") != record.get("experiment_id"):
        raise RegistryValidationError(
            f"normalized result identity mismatch for {record.get('experiment_id')}"
        )
    return result


def _numeric_summary(result: dict[str, Any], metric: str) -> float | int | None:
    value = result.get("summary", {}).get(metric)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(float(value)):
        return None
    return value


def _delta(current: float | int, baseline: float | int) -> dict[str, float]:
    absolute = float(current) - float(baseline)
    result = {"absolute": absolute}
    if float(baseline) != 0:
        result["relative_pct"] = absolute / abs(float(baseline)) * 100.0
    return result


def build_ablation_report(
    matrix_dir: str | Path,
    registry_db: str | Path,
    output_path: str | Path,
    *,
    artifact_root: str | Path = ".",
) -> dict[str, Any]:
    matrix = Path(matrix_dir)
    manifest = _load_json(matrix / "matrix_manifest.json")
    if manifest.get("methodology") != "ONE_CHANGE_AT_A_TIME":
        raise RegistryValidationError("ablation report requires ONE_CHANGE_AT_A_TIME matrix")

    connection = connect_registry(registry_db)
    try:
        baseline_id = manifest.get("baseline", {}).get("experiment_id")
        if not isinstance(baseline_id, str):
            raise RegistryValidationError("matrix baseline experiment_id is missing")
        baseline_record = get_experiment(connection, baseline_id)
        baseline_result = _load_normalized_result(baseline_record, Path(artifact_root))

        baseline_metrics = {
            metric: _numeric_summary(baseline_result, metric)
            for metric in COMPARISON_METRICS
        }
        variants: list[dict[str, Any]] = []
        for item in manifest.get("variants", []):
            experiment_id = item.get("experiment_id")
            if not isinstance(experiment_id, str):
                raise RegistryValidationError("matrix variant missing experiment_id")
            record = get_experiment(connection, experiment_id)
            normalized = _load_normalized_result(record, Path(artifact_root))
            current_metrics = {
                metric: _numeric_summary(normalized, metric)
                for metric in COMPARISON_METRICS
            }
            deltas: dict[str, dict[str, float]] = {}
            for metric in COMPARISON_METRICS:
                baseline_value = baseline_metrics[metric]
                current_value = current_metrics[metric]
                if baseline_value is not None and current_value is not None:
                    deltas[metric] = _delta(current_value, baseline_value)

            variants.append(
                {
                    "name": item.get("name"),
                    "experiment_id": experiment_id,
                    "changed_parameter": item.get("changed_parameter"),
                    "changed_from": item.get("changed_from"),
                    "changed_to": item.get("changed_to"),
                    "metrics": current_metrics,
                    "delta_vs_baseline": deltas,
                }
            )
    finally:
        connection.close()

    report = {
        "schema_version": 1,
        "methodology": "ONE_CHANGE_AT_A_TIME",
        "interpretation": (
            "DESCRIPTIVE_ONLY: deltas do not establish statistical significance or causal edge. "
            "Promotion requires repeated OOS/walk-forward evidence."
        ),
        "metric_preference": METRIC_PREFERENCE,
        "baseline": {
            "experiment_id": baseline_id,
            "metrics": baseline_metrics,
        },
        "variants": variants,
    }
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix-dir", required=True)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--artifact-root", default=".")
    args = parser.parse_args()

    try:
        result = build_ablation_report(
            args.matrix_dir,
            args.registry,
            args.output,
            artifact_root=args.artifact_root,
        )
    except RegistryValidationError as exc:
        parser.error(str(exc))
        return
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
