#!/usr/bin/env python3
"""Freeze an approved MT5 DEMO execution environment from reviewed discovery evidence.

Discovery and approval are intentionally separate transitions. This command accepts
an unapproved execution-environment candidate plus its credential-free discovery
audit, revalidates their identity and observed broker metadata, and only then emits
an approved validation contract and immutable approval record. Approval never
authorizes live trading or real capital.
"""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.execution_environment import (
        canonical_environment_sha256,
        validate_execution_environment,
    )
    from scripts.experiment_registry import RegistryValidationError, sha256_file
    from scripts.mt5_environment_discovery import METHODOLOGY as DISCOVERY_METHODOLOGY
except ModuleNotFoundError:
    from execution_environment import canonical_environment_sha256, validate_execution_environment
    from experiment_registry import RegistryValidationError, sha256_file
    from mt5_environment_discovery import METHODOLOGY as DISCOVERY_METHODOLOGY

METHODOLOGY = "MT5_EXECUTION_ENVIRONMENT_APPROVAL_FREEZE_V1"
CONFIRMATION = "APPROVE_DEMO_EXECUTION_ENVIRONMENT"


class EnvironmentApprovalError(ValueError):
    pass


def _load_json(path: str | Path) -> dict[str, Any]:
    target = Path(path).resolve()
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EnvironmentApprovalError(f"invalid JSON input: {target}") from exc
    if not isinstance(value, dict):
        raise EnvironmentApprovalError(f"JSON input root must be an object: {target}")
    return value


def _parse_approval_time(raw: str) -> str:
    if not isinstance(raw, str) or not raw.endswith("Z"):
        raise EnvironmentApprovalError(
            "approved_at_utc must be an ISO-8601 UTC timestamp ending in Z"
        )
    try:
        parsed = datetime.fromisoformat(raw[:-1] + "+00:00")
    except ValueError as exc:
        raise EnvironmentApprovalError("approved_at_utc is invalid") from exc
    if parsed.tzinfo != timezone.utc:
        raise EnvironmentApprovalError("approved_at_utc must be UTC")
    return parsed.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _validate_discovery_audit(
    audit: dict[str, Any], candidate: dict[str, Any]
) -> dict[str, Any]:
    if audit.get("schema_version") != 1:
        raise EnvironmentApprovalError("discovery audit schema_version must be 1")
    if audit.get("methodology") != DISCOVERY_METHODOLOGY:
        raise EnvironmentApprovalError("unsupported discovery audit methodology")
    if audit.get("status") != "CANDIDATE_DISCOVERED":
        raise EnvironmentApprovalError("discovery audit status must be CANDIDATE_DISCOVERED")
    if audit.get("approved") is not False:
        raise EnvironmentApprovalError("discovery audit must remain approved=false")
    if audit.get("live_trading_authorized") is not False:
        raise EnvironmentApprovalError("discovery audit must deny live trading")
    if audit.get("real_capital_authorized") is not False:
        raise EnvironmentApprovalError("discovery audit must deny real capital")

    expected_canonical = canonical_environment_sha256(candidate)
    if audit.get("candidate_canonical_sha256") != expected_canonical:
        raise EnvironmentApprovalError("discovery audit candidate canonical SHA-256 mismatch")
    if audit.get("environment_id") != candidate["environment_id"]:
        raise EnvironmentApprovalError("discovery audit environment_id mismatch")

    observed = audit.get("observed")
    if not isinstance(observed, dict):
        raise EnvironmentApprovalError("discovery audit observed payload is required")
    expected_observed = {
        "trade_mode": "DEMO",
        "account_company": candidate["account_company"],
        "account_server": candidate["account_server"],
        "symbol": candidate["symbol"],
        "mt5_build": candidate["mt5_build"],
    }
    for field, expected in expected_observed.items():
        actual = observed.get(field)
        if str(actual).strip() != str(expected).strip():
            raise EnvironmentApprovalError(
                f"discovery audit {field} mismatch: expected {expected!r}, got {actual!r}"
            )
    if observed.get("terminal_connected") is not True:
        raise EnvironmentApprovalError("discovery audit requires terminal_connected=true")
    if observed.get("symbol_synchronized") is not True:
        raise EnvironmentApprovalError("discovery audit requires symbol_synchronized=true")
    return observed


def freeze_approved_environment(
    *,
    candidate_path: str | Path,
    discovery_audit_path: str | Path,
    approved_by: str,
    approval_note: str,
    approved_at_utc: str,
    confirmation: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if confirmation != CONFIRMATION:
        raise EnvironmentApprovalError(
            f"explicit confirmation must equal {CONFIRMATION!r}"
        )
    reviewer = approved_by.strip() if isinstance(approved_by, str) else ""
    note = approval_note.strip() if isinstance(approval_note, str) else ""
    if not reviewer:
        raise EnvironmentApprovalError("approved_by is required")
    if len(note) < 8:
        raise EnvironmentApprovalError("approval_note must contain at least 8 characters")
    approved_at = _parse_approval_time(approved_at_utc)

    raw_candidate = _load_json(candidate_path)
    try:
        candidate = validate_execution_environment(raw_candidate)
    except RegistryValidationError as exc:
        raise EnvironmentApprovalError(str(exc)) from exc
    if candidate["approved"] is not False:
        raise EnvironmentApprovalError("candidate must be approved=false before approval freeze")
    if candidate["require_trade_mode"] != "DEMO":
        raise EnvironmentApprovalError("candidate must require DEMO trade mode")
    if candidate["live_trading_authorized"] is not False:
        raise EnvironmentApprovalError("candidate must deny live trading")

    discovery_audit = _load_json(discovery_audit_path)
    observed = _validate_discovery_audit(discovery_audit, candidate)

    approval_input = deepcopy(candidate)
    approval_input["approved"] = True
    try:
        approved_document = validate_execution_environment(approval_input)
    except RegistryValidationError as exc:
        raise EnvironmentApprovalError(str(exc)) from exc
    if approved_document["approved"] is not True:
        raise EnvironmentApprovalError("execution environment approval transition failed")
    if approved_document["live_trading_authorized"] is not False:
        raise EnvironmentApprovalError("approved environment must deny live trading")

    approval_record = {
        "schema_version": 1,
        "methodology": METHODOLOGY,
        "decision": "APPROVED_FOR_OFFICIAL_VALIDATION",
        "approved_by": reviewer,
        "approval_note": note,
        "approved_at_utc": approved_at,
        "environment_id": approved_document["environment_id"],
        "candidate_file_sha256": sha256_file(Path(candidate_path).resolve()),
        "candidate_canonical_sha256": canonical_environment_sha256(candidate),
        "discovery_audit_file_sha256": sha256_file(Path(discovery_audit_path).resolve()),
        "approved_environment_canonical_sha256": canonical_environment_sha256(approved_document),
        "observed": {
            "trade_mode": observed["trade_mode"],
            "account_company": observed["account_company"],
            "account_server": observed["account_server"],
            "symbol": observed["symbol"],
            "mt5_build": str(observed["mt5_build"]),
            "terminal_connected": True,
            "symbol_synchronized": True,
        },
        "live_trading_authorized": False,
        "real_capital_authorized": False,
    }
    return approved_document, approval_record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--discovery-audit", required=True)
    parser.add_argument("--approved-by", required=True)
    parser.add_argument("--approval-note", required=True)
    parser.add_argument("--approved-at-utc", required=True)
    parser.add_argument("--confirmation", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--approval-record", required=True)
    args = parser.parse_args()

    try:
        document, record = freeze_approved_environment(
            candidate_path=args.candidate,
            discovery_audit_path=args.discovery_audit,
            approved_by=args.approved_by,
            approval_note=args.approval_note,
            approved_at_utc=args.approved_at_utc,
            confirmation=args.confirmation,
        )
    except EnvironmentApprovalError as exc:
        parser.error(str(exc))
        return

    output = Path(args.output)
    record_output = Path(args.approval_record)
    output.parent.mkdir(parents=True, exist_ok=True)
    record_output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    record_output.write_text(
        json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(json.dumps({
        "status": record["decision"],
        "environment_id": document["environment_id"],
        "approved": document["approved"],
        "approved_environment_canonical_sha256": record["approved_environment_canonical_sha256"],
        "live_trading_authorized": False,
        "real_capital_authorized": False,
    }, indent=2, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
