#!/usr/bin/env python3
"""Shared canonical contracts for the Golden Trade X official validation campaign."""

from __future__ import annotations

import hashlib
import json
from typing import Any

try:
    from scripts.experiment_registry import RegistryValidationError
except ModuleNotFoundError:
    from experiment_registry import RegistryValidationError


def _canonical_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def candidate_universe_snapshot(entries: Any) -> list[dict[str, str]]:
    """Normalize candidate name/preset hashes and reject aliases or duplicates."""
    if not isinstance(entries, list) or not entries:
        raise RegistryValidationError("candidate universe must be a non-empty array")

    names: set[str] = set()
    hashes: set[str] = set()
    normalized: list[dict[str, str]] = []
    for raw in entries:
        if not isinstance(raw, dict):
            raise RegistryValidationError("candidate universe entry must be an object")
        name = raw.get("name")
        preset_sha = raw.get("preset_sha256")
        if not isinstance(name, str) or not name.strip():
            raise RegistryValidationError("candidate universe entry requires name")
        if not isinstance(preset_sha, str) or len(preset_sha) != 64:
            raise RegistryValidationError("candidate universe entry requires a SHA-256 preset hash")
        name = name.strip()
        preset_sha = preset_sha.lower()
        if name in names:
            raise RegistryValidationError(f"duplicate candidate name: {name}")
        if preset_sha in hashes:
            raise RegistryValidationError(
                f"duplicate candidate preset hash under multiple names: {preset_sha}"
            )
        names.add(name)
        hashes.add(preset_sha)
        normalized.append({"name": name, "preset_sha256": preset_sha})

    return sorted(normalized, key=lambda item: item["name"])


def candidate_universe_sha256(entries: Any) -> str:
    return _canonical_hash(
        {
            "schema_version": 1,
            "methodology": "FROZEN_CANDIDATE_UNIVERSE_V1",
            "candidates": candidate_universe_snapshot(entries),
        }
    )


def robustness_template_snapshot(document: Any) -> dict[str, Any]:
    """Normalize pre-registered robustness rules independent of the later OOS base."""
    if not isinstance(document, dict):
        raise RegistryValidationError("robustness template must be an object")

    template_id = document.get("template_id")
    if not isinstance(template_id, str) or not template_id.strip():
        raise RegistryValidationError("robustness template requires template_id")

    parameter_scenarios = document.get("parameter_scenarios")
    if not isinstance(parameter_scenarios, list) or not parameter_scenarios:
        raise RegistryValidationError("robustness template parameter_scenarios must be non-empty")
    parameter_rows: list[dict[str, Any]] = []
    names: set[str] = set()
    for raw in parameter_scenarios:
        if not isinstance(raw, dict):
            raise RegistryValidationError("robustness parameter scenario must be an object")
        name = raw.get("name")
        parameter = raw.get("parameter")
        if not isinstance(name, str) or not name.strip():
            raise RegistryValidationError("robustness parameter scenario requires name")
        if not isinstance(parameter, str) or not parameter.strip():
            raise RegistryValidationError(f"{name}: parameter is required")
        if "value" not in raw:
            raise RegistryValidationError(f"{name}: value is required")
        name = name.strip()
        if name in names:
            raise RegistryValidationError(f"duplicate robustness parameter scenario: {name}")
        names.add(name)
        parameter_rows.append(
            {"name": name, "parameter": parameter.strip(), "value": raw["value"]}
        )

    broker = document.get("broker_requirements")
    if not isinstance(broker, dict):
        raise RegistryValidationError("robustness template broker_requirements must be an object")
    labels = broker.get("required_labels")
    if not isinstance(labels, list) or not labels:
        raise RegistryValidationError("robustness template requires broker labels")
    clean_labels: list[str] = []
    for value in labels:
        if not isinstance(value, str) or not value.strip():
            raise RegistryValidationError("broker labels must be non-empty strings")
        clean_labels.append(value.strip())
    if len(clean_labels) != len(set(clean_labels)):
        raise RegistryValidationError("broker labels must be unique")
    minimum = broker.get("minimum_distinct_brokers", len(clean_labels))
    if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 1:
        raise RegistryValidationError("minimum_distinct_brokers must be an integer >= 1")
    if minimum > len(clean_labels):
        raise RegistryValidationError("minimum_distinct_brokers exceeds required broker labels")

    costs = document.get("modeled_cost_scenarios")
    if not isinstance(costs, list) or not costs:
        raise RegistryValidationError("robustness template modeled_cost_scenarios must be non-empty")
    cost_rows: list[dict[str, Any]] = []
    cost_names: set[str] = set()
    for raw in costs:
        if not isinstance(raw, dict):
            raise RegistryValidationError("modeled cost scenario must be an object")
        name = raw.get("name")
        cost = raw.get("cost_per_trade_currency")
        if not isinstance(name, str) or not name.strip():
            raise RegistryValidationError("modeled cost scenario requires name")
        if not isinstance(cost, (int, float)) or isinstance(cost, bool) or float(cost) < 0:
            raise RegistryValidationError(f"{name}: cost_per_trade_currency must be >= 0")
        name = name.strip()
        if name in cost_names:
            raise RegistryValidationError(f"duplicate modeled cost scenario: {name}")
        cost_names.add(name)
        cost_rows.append({"name": name, "cost_per_trade_currency": float(cost)})

    metadata_stress = document.get("executed_metadata_stress", [])
    if metadata_stress != []:
        raise RegistryValidationError(
            "official robustness template forbids metadata-only executed stress claims"
        )

    return {
        "template_id": template_id.strip(),
        "parameter_scenarios": sorted(parameter_rows, key=lambda item: item["name"]),
        "broker_requirements": {
            "required_labels": sorted(clean_labels),
            "minimum_distinct_brokers": minimum,
        },
        "modeled_cost_scenarios": sorted(cost_rows, key=lambda item: item["name"]),
        "executed_metadata_stress": [],
    }


def robustness_template_sha256(document: Any) -> str:
    return _canonical_hash(
        {
            "schema_version": 1,
            "methodology": "ROBUSTNESS_TEMPLATE_V1",
            **robustness_template_snapshot(document),
        }
    )
