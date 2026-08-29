from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.execution_environment import canonical_environment_sha256
from scripts.freeze_approved_execution_environment import (
    CONFIRMATION,
    EnvironmentApprovalError,
    freeze_approved_environment,
)
from scripts.mt5_environment_discovery import build_discovered_environment


def _observed() -> dict[str, object]:
    return {
        "trade_mode": "DEMO",
        "account_company": "Verified Broker Ltd",
        "account_server": "VerifiedBroker-Demo",
        "account_currency": "USD",
        "leverage": 100,
        "symbol": "XAUUSD",
        "mt5_build": "5320",
        "terminal_connected": True,
        "symbol_synchronized": True,
        "symbol_digits": 2,
        "symbol_point": 0.01,
        "trade_contract_size": 100.0,
        "trade_tick_size": 0.01,
        "trade_tick_value": 1.0,
        "currency_profit": "USD",
    }


def _write_bundle(tmp_path: Path) -> tuple[Path, Path, dict, dict]:
    candidate, audit = build_discovered_environment(_observed())
    candidate_path = tmp_path / "execution_environment.candidate.json"
    audit_path = tmp_path / "execution_environment.discovery.json"
    candidate_path.write_text(json.dumps(candidate, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    audit_path.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return candidate_path, audit_path, candidate, audit


def _freeze(candidate_path: Path, audit_path: Path):
    return freeze_approved_environment(
        candidate_path=candidate_path,
        discovery_audit_path=audit_path,
        approved_by="VladPhil92",
        approval_note="Reviewed broker identity and DEMO execution metadata.",
        approved_at_utc="2026-08-29T22:50:00Z",
        confirmation=CONFIRMATION,
    )


def test_freeze_approves_only_validated_demo_candidate(tmp_path: Path) -> None:
    candidate_path, audit_path, candidate, _ = _write_bundle(tmp_path)
    approved, record = _freeze(candidate_path, audit_path)

    assert approved["approved"] is True
    assert approved["live_trading_authorized"] is False
    assert approved["require_trade_mode"] == "DEMO"
    assert approved["environment_id"] == candidate["environment_id"]
    assert approved["account_server"] == candidate["account_server"]
    assert record["decision"] == "APPROVED_FOR_OFFICIAL_VALIDATION"
    assert record["live_trading_authorized"] is False
    assert record["real_capital_authorized"] is False
    assert record["approved_environment_canonical_sha256"] == canonical_environment_sha256(approved)


def test_freeze_rejects_missing_explicit_confirmation(tmp_path: Path) -> None:
    candidate_path, audit_path, _, _ = _write_bundle(tmp_path)

    with pytest.raises(EnvironmentApprovalError, match="explicit confirmation"):
        freeze_approved_environment(
            candidate_path=candidate_path,
            discovery_audit_path=audit_path,
            approved_by="VladPhil92",
            approval_note="Reviewed broker metadata.",
            approved_at_utc="2026-08-29T22:50:00Z",
            confirmation="YES",
        )


def test_freeze_rejects_candidate_hash_drift(tmp_path: Path) -> None:
    candidate_path, audit_path, candidate, _ = _write_bundle(tmp_path)
    candidate["deposit"] = 20000.0
    candidate_path.write_text(json.dumps(candidate, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(EnvironmentApprovalError, match="canonical SHA-256 mismatch"):
        _freeze(candidate_path, audit_path)


def test_freeze_rejects_observed_broker_mismatch(tmp_path: Path) -> None:
    candidate_path, audit_path, _, audit = _write_bundle(tmp_path)
    audit = copy.deepcopy(audit)
    audit["observed"]["account_server"] = "Different-Demo"
    audit_path.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(EnvironmentApprovalError, match="account_server mismatch"):
        _freeze(candidate_path, audit_path)


def test_freeze_rejects_disconnected_discovery_evidence(tmp_path: Path) -> None:
    candidate_path, audit_path, _, audit = _write_bundle(tmp_path)
    audit = copy.deepcopy(audit)
    audit["observed"]["terminal_connected"] = False
    audit_path.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(EnvironmentApprovalError, match="terminal_connected"):
        _freeze(candidate_path, audit_path)


def test_freeze_rejects_placeholder_environment_on_approval(tmp_path: Path) -> None:
    candidate_path, audit_path, candidate, audit = _write_bundle(tmp_path)
    candidate["broker_label"] = "REPLACE_WITH_BROKER"
    candidate["account_company"] = "REPLACE_WITH_BROKER"
    candidate["environment_id"] = "GTX-PLACEHOLDER-DEMO"
    audit["environment_id"] = candidate["environment_id"]
    audit["observed"]["account_company"] = candidate["account_company"]
    audit["candidate_canonical_sha256"] = canonical_environment_sha256(candidate)
    candidate_path.write_text(json.dumps(candidate, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    audit_path.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(EnvironmentApprovalError, match="placeholder"):
        _freeze(candidate_path, audit_path)


def test_freeze_rejects_already_approved_candidate(tmp_path: Path) -> None:
    candidate_path, audit_path, candidate, audit = _write_bundle(tmp_path)
    candidate["approved"] = True
    audit["candidate_canonical_sha256"] = canonical_environment_sha256(candidate)
    candidate_path.write_text(json.dumps(candidate, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    audit_path.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(EnvironmentApprovalError, match="approved=false"):
        _freeze(candidate_path, audit_path)
