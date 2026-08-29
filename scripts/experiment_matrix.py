#!/usr/bin/env python3
"""Generate reproducible Golden Trade X baseline/ablation experiment matrices."""

from __future__ import annotations

import argparse
import json
import re
import shutil
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

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _load_json_object(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise RegistryValidationError(f"JSON root must be an object: {path}")
    return value


def _find_parameter(lines: list[str], parameter: str) -> tuple[int, str]:
    matches: list[tuple[int, str]] = []
    pattern = re.compile(rf"^\s*{re.escape(parameter)}\s*=\s*(.*?)\s*$")
    for index, line in enumerate(lines):
        match = pattern.match(line)
        if match:
            matches.append((index, match.group(1)))
    if len(matches) != 1:
        raise RegistryValidationError(
            f"expected exactly one {parameter}=... entry in preset, found {len(matches)}"
        )
    return matches[0]


def _replace_parameter(source: Path, destination: Path, parameter: str, value: Any) -> tuple[str, str]:
    text = source.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    index, old_value = _find_parameter([line.rstrip("\r\n") for line in lines], parameter)
    new_value = str(value).lower() if isinstance(value, bool) else str(value)
    if old_value == new_value:
        raise RegistryValidationError(f"{parameter} variant does not change the baseline value ({old_value})")
    ending = "\r\n" if lines[index].endswith("\r\n") else "\n" if lines[index].endswith("\n") else ""
    lines[index] = f"{parameter}={new_value}{ending}"
    destination.write_text("".join(lines), encoding="utf-8", newline="")
    return old_value, new_value


def _validate_variants(matrix: dict[str, Any]) -> list[dict[str, Any]]:
    variants = matrix.get("variants")
    if not isinstance(variants, list) or not variants:
        raise RegistryValidationError("matrix must contain a non-empty variants array")
    names: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for raw in variants:
        if not isinstance(raw, dict):
            raise RegistryValidationError("every matrix variant must be an object")
        name = raw.get("name")
        parameter = raw.get("parameter")
        if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
            raise RegistryValidationError(f"invalid variant name: {name!r}")
        if name in names:
            raise RegistryValidationError(f"duplicate variant name: {name}")
        names.add(name)
        if not isinstance(parameter, str) or not parameter.strip():
            raise RegistryValidationError(f"variant {name}: parameter is required")
        if "value" not in raw:
            raise RegistryValidationError(f"variant {name}: value is required")
        normalized.append({"name": name, "parameter": parameter.strip(), "value": raw["value"]})
    return normalized


def generate_matrix(
    base_spec_path: str | Path,
    matrix_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    base_spec_path = Path(base_spec_path).resolve()
    matrix_path = Path(matrix_path).resolve()
    output = Path(output_dir).resolve()
    specs_dir = output / "specs"
    presets_dir = output / "presets"
    specs_dir.mkdir(parents=True, exist_ok=True)
    presets_dir.mkdir(parents=True, exist_ok=True)

    base_spec = load_spec(base_spec_path)
    matrix = _load_json_object(matrix_path)
    variants = _validate_variants(matrix)

    source_preset = Path(str(base_spec.get("preset_path", "")))
    if not source_preset.is_absolute():
        source_preset = base_spec_path.parent / source_preset
    if not source_preset.is_file():
        raise RegistryValidationError(f"baseline preset not found: {source_preset}")

    baseline_preset = presets_dir / "baseline.set"
    shutil.copyfile(source_preset, baseline_preset)
    baseline_spec = dict(base_spec)
    baseline_spec["preset_path"] = "../presets/baseline.set"
    baseline_spec["expert_parameters"] = baseline_preset.name
    baseline_spec["parent_experiment_id"] = None
    baseline_spec["changed_parameter"] = None
    baseline_spec["changed_from"] = None
    baseline_spec["changed_to"] = None
    baseline_spec_path = specs_dir / "baseline.json"
    baseline_spec_path.write_text(
        json.dumps(baseline_spec, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    normalized_baseline, _ = normalize_spec(baseline_spec, base_dir=specs_dir)
    baseline_identity = identity_for(normalized_baseline)

    manifest_variants: list[dict[str, Any]] = []
    for variant in variants:
        name = variant["name"]
        variant_preset = presets_dir / f"{name}.set"
        changed_from, changed_to = _replace_parameter(
            baseline_preset, variant_preset, variant["parameter"], variant["value"]
        )
        variant_spec = dict(base_spec)
        variant_spec["preset_path"] = f"../presets/{variant_preset.name}"
        variant_spec["expert_parameters"] = variant_preset.name
        variant_spec["parent_experiment_id"] = baseline_identity.experiment_id
        variant_spec["changed_parameter"] = variant["parameter"]
        variant_spec["changed_from"] = changed_from
        variant_spec["changed_to"] = changed_to
        variant_spec_path = specs_dir / f"{name}.json"
        variant_spec_path.write_text(
            json.dumps(variant_spec, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        normalized_variant, _ = normalize_spec(variant_spec, base_dir=specs_dir)
        variant_identity = identity_for(normalized_variant)
        manifest_variants.append(
            {
                "name": name,
                "experiment_id": variant_identity.experiment_id,
                "fingerprint": variant_identity.fingerprint,
                "preset_sha256": sha256_file(variant_preset),
                "spec": f"specs/{name}.json",
                "preset": f"presets/{name}.set",
                "changed_parameter": variant["parameter"],
                "changed_from": changed_from,
                "changed_to": changed_to,
            }
        )

    manifest = {
        "schema_version": 1,
        "methodology": "ONE_CHANGE_AT_A_TIME",
        "baseline": {
            "experiment_id": baseline_identity.experiment_id,
            "fingerprint": baseline_identity.fingerprint,
            "preset_sha256": sha256_file(baseline_preset),
            "spec": "specs/baseline.json",
            "preset": "presets/baseline.set",
        },
        "variants": manifest_variants,
    }
    manifest_path = output / "matrix_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-spec", required=True)
    parser.add_argument("--matrix", required=True)
    parser.add_argument("--output-dir", default="data/research/matrix")
    args = parser.parse_args()
    try:
        result = generate_matrix(args.base_spec, args.matrix, args.output_dir)
    except RegistryValidationError as exc:
        parser.error(str(exc))
        return
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
