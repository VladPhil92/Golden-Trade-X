#!/usr/bin/env python3
"""Plan auditable Golden Trade X robustness campaigns.

Robustness evidence is separated into three classes:

* EXECUTED_COUNTERFACTUAL: one preset parameter is materially changed and the
  resulting spec must be executed in MetaTrader Strategy Tester.
* EXTERNAL_BROKER_REPLICATION: the exact frozen preset is rerun in explicitly
  named broker/tester environments.
* MODELED_COST_SENSITIVITY: deterministic accounting sensitivity applied to an
  observed result. This is never represented as an executed MT5 counterfactual.

The planner intentionally rejects metadata-only execution stress claims.
"""

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

PLAN_SCHEMA_VERSION = 1
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
FORBIDDEN_METADATA_ONLY_FIELDS = {
    "slippage_points",
    "commission",
    "spread_mode",
    "swap_mode",
    "broker",
}


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


def _find_parameter(lines: list[str], parameter: str) -> tuple[int, str]:
    pattern = re.compile(rf"^\s*{re.escape(parameter)}\s*=\s*(.*?)\s*$")
    matches: list[tuple[int, str]] = []
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
    bare = [line.rstrip("\r\n") for line in lines]
    index, old_value = _find_parameter(bare, parameter)
    new_value = str(value).lower() if isinstance(value, bool) else str(value)
    if old_value == new_value:
        raise RegistryValidationError(
            f"{parameter} robustness scenario does not change baseline value ({old_value})"
        )
    ending = "\r\n" if lines[index].endswith("\r\n") else "\n" if lines[index].endswith("\n") else ""
    lines[index] = f"{parameter}={new_value}{ending}"
    destination.write_text("".join(lines), encoding="utf-8", newline="")
    return old_value, new_value


def _validate_policy_snapshot(config_path: Path, config: dict[str, Any]) -> dict[str, Any]:
    raw = config.get("robustness_policy_path")
    policy_path = _resolve(config_path.parent, raw, "robustness_policy_path")
    policy = _load_json_object(policy_path)
    policy_id = policy.get("policy_id")
    if not isinstance(policy_id, str) or not policy_id.strip():
        raise RegistryValidationError("robustness policy requires policy_id")
    approved = policy.get("approved")
    if not isinstance(approved, bool):
        raise RegistryValidationError("robustness policy approved must be true/false")
    return {
        "path": Path(str(raw)).as_posix(),
        "sha256": sha256_file(policy_path),
        "policy_id": policy_id.strip(),
        "approved": approved,
    }


def _validate_parameter_scenarios(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not raw:
        raise RegistryValidationError("parameter_scenarios must be a non-empty array")
    names: set[str] = set()
    parameters_seen: set[tuple[str, str]] = set()
    result: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise RegistryValidationError("parameter scenario must be an object")
        name = item.get("name")
        parameter = item.get("parameter")
        if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
            raise RegistryValidationError(f"invalid robustness scenario name: {name!r}")
        if name in names:
            raise RegistryValidationError(f"duplicate robustness scenario name: {name}")
        names.add(name)
        if not isinstance(parameter, str) or not parameter.strip():
            raise RegistryValidationError(f"{name}: parameter is required")
        if "value" not in item:
            raise RegistryValidationError(f"{name}: value is required")
        key = (parameter.strip(), json.dumps(item["value"], sort_keys=True))
        if key in parameters_seen:
            raise RegistryValidationError(f"duplicate parameter/value scenario: {parameter}={item['value']}")
        parameters_seen.add(key)
        result.append({"name": name, "parameter": parameter.strip(), "value": item["value"]})
    return result


def _validate_broker_requirements(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise RegistryValidationError("broker_requirements must be an object")
    labels = raw.get("required_labels")
    if not isinstance(labels, list) or not labels:
        raise RegistryValidationError("broker_requirements.required_labels must be non-empty")
    cleaned: list[str] = []
    for label in labels:
        if not isinstance(label, str) or not label.strip():
            raise RegistryValidationError("broker labels must be non-empty strings")
        cleaned.append(label.strip())
    if len(set(cleaned)) != len(cleaned):
        raise RegistryValidationError("broker labels must be unique")
    minimum = raw.get("minimum_distinct_brokers", len(cleaned))
    if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 1:
        raise RegistryValidationError("minimum_distinct_brokers must be an integer >= 1")
    if minimum > len(cleaned):
        raise RegistryValidationError("minimum_distinct_brokers cannot exceed required_labels count")
    return {"required_labels": cleaned, "minimum_distinct_brokers": minimum}


def _validate_cost_scenarios(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not raw:
        raise RegistryValidationError("modeled_cost_scenarios must be a non-empty array")
    names: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise RegistryValidationError("modeled cost scenario must be an object")
        name = item.get("name")
        value = item.get("cost_per_trade_currency")
        if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
            raise RegistryValidationError(f"invalid modeled cost scenario name: {name!r}")
        if name in names:
            raise RegistryValidationError(f"duplicate modeled cost scenario name: {name}")
        names.add(name)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or float(value) < 0:
            raise RegistryValidationError(f"{name}: cost_per_trade_currency must be >= 0")
        result.append({"name": name, "cost_per_trade_currency": float(value)})
    return result


def _reject_metadata_only_execution_stress(config: dict[str, Any]) -> None:
    raw = config.get("executed_metadata_stress", [])
    if not isinstance(raw, list):
        raise RegistryValidationError("executed_metadata_stress must be an array")
    if not raw:
        return
    invalid: list[str] = []
    for item in raw:
        if not isinstance(item, dict):
            raise RegistryValidationError("executed_metadata_stress entry must be an object")
        field = item.get("field")
        if isinstance(field, str) and field in FORBIDDEN_METADATA_ONLY_FIELDS:
            invalid.append(field)
        else:
            invalid.append(str(field))
    raise RegistryValidationError(
        "metadata-only fields cannot be claimed as executed robustness stress without a material execution binding: "
        + ", ".join(invalid)
    )


def generate_robustness_plan(config_path: str | Path, output_dir: str | Path) -> dict[str, Any]:
    config_path = Path(config_path).resolve()
    config = _load_json_object(config_path)
    _reject_metadata_only_execution_stress(config)

    campaign_id = config.get("campaign_id")
    if not isinstance(campaign_id, str) or not campaign_id.strip():
        raise RegistryValidationError("campaign_id is required")

    base_spec_path = _resolve(config_path.parent, config.get("base_spec_path"), "base_spec_path")
    base_spec = load_spec(base_spec_path)
    normalized_base, _ = normalize_spec(base_spec, base_dir=base_spec_path.parent)
    base_identity = identity_for(normalized_base)
    if normalized_base.get("source_type") != "strategy_tester":
        raise RegistryValidationError("robustness base spec must be a strategy_tester experiment")

    source_preset = Path(str(base_spec.get("preset_path", "")))
    if not source_preset.is_absolute():
        source_preset = base_spec_path.parent / source_preset
    source_preset = source_preset.resolve()
    if not source_preset.is_file():
        raise RegistryValidationError(f"base preset not found: {source_preset}")

    policy = _validate_policy_snapshot(config_path, config)
    parameter_scenarios = _validate_parameter_scenarios(config.get("parameter_scenarios"))
    broker_requirements = _validate_broker_requirements(config.get("broker_requirements"))
    cost_scenarios = _validate_cost_scenarios(config.get("modeled_cost_scenarios"))

    output = Path(output_dir).resolve()
    specs_dir = output / "parameter_specs"
    presets_dir = output / "parameter_presets"
    specs_dir.mkdir(parents=True, exist_ok=True)
    presets_dir.mkdir(parents=True, exist_ok=True)

    scenarios: list[dict[str, Any]] = []
    for scenario in parameter_scenarios:
        name = scenario["name"]
        preset_path = presets_dir / f"{name}.set"
        changed_from, changed_to = _replace_parameter(
            source_preset,
            preset_path,
            scenario["parameter"],
            scenario["value"],
        )
        spec = dict(base_spec)
        spec["preset_path"] = f"../parameter_presets/{preset_path.name}"
        spec["expert_parameters"] = preset_path.name
        spec["parent_experiment_id"] = base_identity.experiment_id
        spec["changed_parameter"] = scenario["parameter"]
        spec["changed_from"] = changed_from
        spec["changed_to"] = changed_to
        spec["notes"] = (
            f"Robustness EXECUTED_COUNTERFACTUAL {name}: one preset parameter changed from "
            f"{changed_from} to {changed_to}."
        )
        spec_path = specs_dir / f"{name}.json"
        spec_path.write_text(
            json.dumps(spec, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        normalized, _ = normalize_spec(spec, base_dir=specs_dir)
        identity = identity_for(normalized)
        scenarios.append(
            {
                "name": name,
                "evidence_class": "EXECUTED_COUNTERFACTUAL",
                "binding": "preset_parameter",
                "parameter": scenario["parameter"],
                "changed_from": changed_from,
                "changed_to": changed_to,
                "experiment_id": identity.experiment_id,
                "fingerprint": identity.fingerprint,
                "preset_sha256": sha256_file(preset_path),
                "spec": f"parameter_specs/{name}.json",
                "preset": f"parameter_presets/{name}.set",
            }
        )

    manifest = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "methodology": "ROBUSTNESS_V1",
        "campaign_id": campaign_id.strip(),
        "status": "READY_FOR_REGISTERED_EXECUTION" if policy["approved"] else "DRAFT_POLICY_UNAPPROVED",
        "base": {
            "spec_path": Path(str(config.get("base_spec_path"))).as_posix(),
            "experiment_id": base_identity.experiment_id,
            "fingerprint": base_identity.fingerprint,
            "preset_sha256": base_identity.preset_sha256,
            "git_sha": normalized_base["git_sha"],
            "broker": normalized_base["broker"],
            "symbol": normalized_base["symbol"],
            "timeframe": normalized_base["timeframe"],
            "period_start": normalized_base["period_start"],
            "period_end": normalized_base["period_end"],
        },
        "robustness_policy": policy,
        "domains": {
            "parameter_stability": {
                "evidence_class": "EXECUTED_COUNTERFACTUAL",
                "scenarios": scenarios,
            },
            "broker_replication": {
                "evidence_class": "EXTERNAL_BROKER_REPLICATION",
                **broker_requirements,
                "note": "Broker labels are requirements, not generated evidence. Each run must come from the declared environment.",
            },
            "cost_sensitivity": {
                "evidence_class": "MODELED_COST_SENSITIVITY",
                "scenarios": cost_scenarios,
                "note": (
                    "Derived accounting sensitivity only. Current Strategy Tester harness does not materially bind "
                    "slippage/commission/spread fields into MT5 execution, so these scenarios cannot be labeled executed."
                ),
            },
        },
    }
    manifest_path = output / "robustness_plan.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output-dir", default="data/research/robustness")
    args = parser.parse_args()
    try:
        result = generate_robustness_plan(args.config, args.output_dir)
    except RegistryValidationError as exc:
        parser.error(str(exc))
        return
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
