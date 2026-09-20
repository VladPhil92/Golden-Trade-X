#!/usr/bin/env python3
"""Materialize a frozen robustness template from approved MT5 DEMO environments.

The official robustness broker universe must come from reviewed execution-environment
contracts, not free-form labels. This tool keeps parameter/cost scenarios from a
reviewed base template, derives broker labels from approved DEMO contracts, and emits
an audit record that binds the resulting template to the exact source environment files.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from scripts.campaign_contract import (
        robustness_template_sha256,
        robustness_template_snapshot,
    )
    from scripts.execution_environment import (
        canonical_environment_sha256,
        load_execution_environment_contract,
    )
    from scripts.experiment_registry import RegistryValidationError
except ModuleNotFoundError:
    from campaign_contract import robustness_template_sha256, robustness_template_snapshot
    from execution_environment import (
        canonical_environment_sha256,
        load_execution_environment_contract,
    )
    from experiment_registry import RegistryValidationError

METHODOLOGY = "ROBUSTNESS_TEMPLATE_MATERIALIZATION_V1"


def _load_json(path: str | Path) -> dict[str, Any]:
    target = Path(path).resolve()
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RegistryValidationError(f"invalid JSON input: {target}") from exc
    if not isinstance(value, dict):
        raise RegistryValidationError(f"JSON input root must be an object: {target}")
    return value


def materialize_robustness_template(
    *,
    base_template_path: str | Path,
    environment_paths: list[str | Path],
    output_path: str | Path | None = None,
    audit_output_path: str | Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if len(environment_paths) < 2:
        raise RegistryValidationError(
            "robustness materialization requires at least two approved DEMO environments"
        )

    base_template = _load_json(base_template_path)
    base_snapshot = robustness_template_snapshot(base_template)
    minimum = int(base_snapshot["broker_requirements"]["minimum_distinct_brokers"])
    if len(environment_paths) < minimum:
        raise RegistryValidationError(
            f"robustness materialization requires at least {minimum} environment contracts"
        )

    source_rows: list[dict[str, Any]] = []
    broker_labels: list[str] = []
    broker_identities: set[tuple[str, str]] = set()

    for raw_path in environment_paths:
        declared_path = Path(raw_path)
        path = declared_path.resolve()
        environment, file_sha = load_execution_environment_contract(path)
        if environment["approved"] is not True:
            raise RegistryValidationError(
                f"robustness source environment is not approved: {path}"
            )
        if environment["require_trade_mode"] != "DEMO":
            raise RegistryValidationError(
                f"robustness source environment is not DEMO-only: {path}"
            )
        if environment["live_trading_authorized"] is not False:
            raise RegistryValidationError(
                f"robustness source environment authorizes live trading: {path}"
            )
        if not isinstance(environment.get("symbol_contract"), dict):
            raise RegistryValidationError(
                f"robustness source environment lacks frozen symbol_contract: {path}"
            )

        label = environment["broker_label"].strip()
        identity = (
            environment["account_company"].strip(),
            environment["account_server"].strip(),
        )
        if label in broker_labels:
            raise RegistryValidationError(f"duplicate broker label: {label}")
        if identity in broker_identities:
            raise RegistryValidationError(
                "robustness source environments must have distinct company/server identities"
            )
        broker_labels.append(label)
        broker_identities.add(identity)
        source_rows.append(
            {
                "path": declared_path.as_posix(),
                "environment_id": environment["environment_id"],
                "broker_label": label,
                "account_company": environment["account_company"],
                "account_server": environment["account_server"],
                "file_sha256": file_sha,
                "canonical_sha256": canonical_environment_sha256(environment),
            }
        )

    template = {
        "schema_version": 1,
        "template_id": "GTX-ROBUSTNESS-TEMPLATE-V1",
        "status_note": (
            "Materialized before official OOS observation from approved, distinct MT5 DEMO "
            "execution environments. Broker labels are derived from frozen contracts."
        ),
        "parameter_scenarios": base_snapshot["parameter_scenarios"],
        "broker_requirements": {
            "required_labels": sorted(broker_labels),
            "minimum_distinct_brokers": minimum,
        },
        "modeled_cost_scenarios": base_snapshot["modeled_cost_scenarios"],
        "executed_metadata_stress": [],
    }
    normalized = robustness_template_snapshot(template)
    template_hash = robustness_template_sha256(template)

    audit = {
        "schema_version": 1,
        "methodology": METHODOLOGY,
        "status": "MATERIALIZED_FROM_APPROVED_DEMO_ENVIRONMENTS",
        "template_id": normalized["template_id"],
        "template_sha256": template_hash,
        "source_environments": sorted(source_rows, key=lambda row: row["broker_label"]),
        "live_trading_authorized": False,
        "real_capital_authorized": False,
    }

    if output_path is not None:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(template, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    if audit_output_path is not None:
        audit_output = Path(audit_output_path)
        audit_output.parent.mkdir(parents=True, exist_ok=True)
        audit_output.write_text(
            json.dumps(audit, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return template, audit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-template",
        default="config/robustness_template.example.json",
    )
    parser.add_argument(
        "--environment",
        action="append",
        required=True,
        help="Approved DEMO execution environment contract; pass at least twice.",
    )
    parser.add_argument(
        "--output",
        default="data/research/robustness-template/robustness_template.v1.json",
    )
    parser.add_argument(
        "--audit-output",
        default="data/research/robustness-template/robustness_template.materialization.json",
    )
    args = parser.parse_args()

    try:
        template, audit = materialize_robustness_template(
            base_template_path=args.base_template,
            environment_paths=args.environment,
            output_path=args.output,
            audit_output_path=args.audit_output,
        )
    except RegistryValidationError as exc:
        parser.error(str(exc))
        return

    print(
        json.dumps(
            {
                "status": audit["status"],
                "template_id": template["template_id"],
                "template_sha256": audit["template_sha256"],
                "brokers": template["broker_requirements"]["required_labels"],
                "live_trading_authorized": False,
                "real_capital_authorized": False,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
