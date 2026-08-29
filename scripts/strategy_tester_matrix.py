#!/usr/bin/env python3
"""Execute a generated Golden Trade X baseline/ablation matrix sequentially."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from scripts.experiment_registry import RegistryValidationError
    from scripts.strategy_tester_harness import run_registered_experiment
except ModuleNotFoundError:
    from experiment_registry import RegistryValidationError
    from strategy_tester_harness import run_registered_experiment


def _load_manifest(matrix_dir: Path) -> dict[str, Any]:
    manifest_path = matrix_dir / "matrix_manifest.json"
    if not manifest_path.is_file():
        raise RegistryValidationError(f"matrix manifest not found: {manifest_path}")
    value = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RegistryValidationError("matrix manifest root must be an object")
    if value.get("methodology") != "ONE_CHANGE_AT_A_TIME":
        raise RegistryValidationError("matrix methodology must be ONE_CHANGE_AT_A_TIME")
    if not isinstance(value.get("baseline"), dict):
        raise RegistryValidationError("matrix manifest baseline is missing")
    if not isinstance(value.get("variants"), list) or not value["variants"]:
        raise RegistryValidationError("matrix manifest variants are missing")
    return value


def _entry_spec(matrix_dir: Path, entry: dict[str, Any]) -> Path:
    spec = entry.get("spec")
    if not isinstance(spec, str) or not spec.strip():
        raise RegistryValidationError("matrix entry missing spec path")
    path = (matrix_dir / spec).resolve()
    root = matrix_dir.resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise RegistryValidationError(f"matrix spec escapes matrix directory: {spec}") from exc
    if not path.is_file():
        raise RegistryValidationError(f"matrix spec not found: {path}")
    return path


def run_matrix(
    matrix_dir: str | Path,
    registry_db: str | Path,
    output_dir: str | Path,
    *,
    terminal: str | Path | None = None,
    timeout_seconds: int = 3600,
    continue_on_failure: bool = False,
) -> dict[str, Any]:
    matrix = Path(matrix_dir)
    manifest = _load_manifest(matrix)
    entries: list[tuple[str, dict[str, Any]]] = [("baseline", manifest["baseline"])]
    entries.extend((str(item.get("name", "variant")), item) for item in manifest["variants"])

    results: list[dict[str, Any]] = []
    failures: list[str] = []
    for name, entry in entries:
        spec_path = _entry_spec(matrix, entry)
        try:
            record = run_registered_experiment(
                spec_path,
                registry_db,
                output_dir,
                terminal=terminal,
                timeout_seconds=timeout_seconds,
            )
            expected_id = entry.get("experiment_id")
            if expected_id and record["experiment_id"] != expected_id:
                raise RegistryValidationError(
                    f"matrix identity drift for {name}: expected {expected_id}, got {record['experiment_id']}"
                )
            results.append(
                {
                    "name": name,
                    "experiment_id": record["experiment_id"],
                    "status": record["status"],
                    "spec": spec_path.as_posix(),
                    "artifacts": record.get("artifacts", {}),
                }
            )
        except Exception as exc:  # noqa: BLE001 - evidence runner must record every failure class.
            failures.append(name)
            results.append(
                {
                    "name": name,
                    "experiment_id": entry.get("experiment_id"),
                    "status": "FAILED",
                    "spec": spec_path.as_posix(),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            if not continue_on_failure:
                break

    summary = {
        "schema_version": 1,
        "methodology": "ONE_CHANGE_AT_A_TIME",
        "matrix_dir": matrix.as_posix(),
        "registry": Path(registry_db).as_posix(),
        "terminal_execution_requested": terminal is not None,
        "results": results,
        "failures": failures,
        "status": "FAILED" if failures else "COMPLETED" if terminal is not None else "PREPARED",
    }
    output = matrix / "matrix_execution.json"
    output.write_text(
        json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    if failures:
        raise RegistryValidationError(
            "matrix execution failed for: " + ", ".join(failures)
        )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix-dir", required=True)
    parser.add_argument("--registry", default="data/research/experiments.sqlite")
    parser.add_argument("--output-dir", default="data/research/runs")
    parser.add_argument("--terminal")
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    parser.add_argument("--continue-on-failure", action="store_true")
    args = parser.parse_args()

    try:
        result = run_matrix(
            args.matrix_dir,
            args.registry,
            args.output_dir,
            terminal=args.terminal,
            timeout_seconds=args.timeout_seconds,
            continue_on_failure=args.continue_on_failure,
        )
    except RegistryValidationError as exc:
        parser.error(str(exc))
        return
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
