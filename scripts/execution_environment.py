#!/usr/bin/env python3
"""Validate and attest the frozen MetaTrader execution environment for official research."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

try:
    from scripts.experiment_registry import RegistryValidationError, sha256_file
except ModuleNotFoundError:
    from experiment_registry import RegistryValidationError, sha256_file

PLACEHOLDER_MARKERS = ("REPLACE_WITH", "PLACEHOLDER", "TBD", "UNKNOWN")
SUPPORTED_TRADE_MODE = "DEMO"


def _load(path: str | Path) -> dict[str, Any]:
    target = Path(path).resolve()
    with target.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise RegistryValidationError(f"JSON root must be an object: {target}")
    return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RegistryValidationError(f"{field} is required")
    return value.strip()


def _nonnegative_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise RegistryValidationError(f"{field} must be an integer >= 0")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise RegistryValidationError(f"{field} must be an integer >= 0") from exc
    if parsed < 0 or (not isinstance(value, int) and str(value).strip() != str(parsed)):
        raise RegistryValidationError(f"{field} must be an integer >= 0")
    return parsed


def _positive_number(value: Any, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise RegistryValidationError(f"{field} must be a finite number > 0")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise RegistryValidationError(f"{field} must be a finite number > 0")
    return parsed


def _nonnegative_number(value: Any, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise RegistryValidationError(f"{field} must be a finite number >= 0")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise RegistryValidationError(f"{field} must be a finite number >= 0")
    return parsed


def _contains_placeholder(value: str) -> bool:
    upper = value.upper()
    return any(marker in upper for marker in PLACEHOLDER_MARKERS)


def validate_execution_environment(contract: dict[str, Any]) -> dict[str, Any]:
    if contract.get("schema_version") != 1:
        raise RegistryValidationError("execution environment schema_version must be 1")

    environment_id = _text(contract.get("environment_id"), "environment_id")
    approved = contract.get("approved")
    if not isinstance(approved, bool):
        raise RegistryValidationError("execution environment approved must be true/false")

    required_text = {
        field: _text(contract.get(field), field)
        for field in (
            "broker_label",
            "account_company",
            "account_server",
            "symbol",
            "timeframe",
            "mt5_build",
            "modelling",
            "expert",
            "currency",
            "spread_mode",
            "swap_mode",
            "forward_mode",
        )
    }

    require_trade_mode = _text(contract.get("require_trade_mode"), "require_trade_mode").upper()
    if require_trade_mode != SUPPORTED_TRADE_MODE:
        raise RegistryValidationError("official execution environment must require DEMO trade mode")

    live_trading_authorized = contract.get("live_trading_authorized")
    if live_trading_authorized is not False:
        raise RegistryValidationError(
            "execution environment must explicitly set live_trading_authorized=false"
        )

    portable_mode = contract.get("portable_mode")
    if not isinstance(portable_mode, bool):
        raise RegistryValidationError("portable_mode must be true/false")

    optimization = contract.get("optimization")
    if optimization is not False:
        raise RegistryValidationError(
            "official candidate-universe execution requires optimization=false"
        )

    tester_model = _nonnegative_int(contract.get("tester_model"), "tester_model")
    execution_mode = _nonnegative_int(contract.get("execution_mode", 0), "execution_mode")
    forward_mode_code = _nonnegative_int(
        contract.get("forward_mode_code", 0), "forward_mode_code"
    )
    if required_text["forward_mode"].lower() != "disabled" or forward_mode_code != 0:
        raise RegistryValidationError("official execution environment must disable MT5 forward mode")

    deposit = _positive_number(contract.get("deposit"), "deposit")
    leverage = _positive_number(contract.get("leverage"), "leverage")
    if not leverage.is_integer():
        raise RegistryValidationError("leverage must be an integer ratio denominator")

    slippage_points = _nonnegative_number(
        contract.get("slippage_points", 0.0), "slippage_points"
    )
    commission = contract.get("commission")
    if commission is not None:
        if not isinstance(commission, (int, float)) or isinstance(commission, bool):
            raise RegistryValidationError("commission must be null or a finite number >= 0")
        commission = float(commission)
        if not math.isfinite(commission) or commission < 0:
            raise RegistryValidationError("commission must be null or a finite number >= 0")

    normalized = {
        "schema_version": 1,
        "environment_id": environment_id,
        "approved": approved,
        "live_trading_authorized": False,
        "require_trade_mode": SUPPORTED_TRADE_MODE,
        "broker_label": required_text["broker_label"],
        "account_company": required_text["account_company"],
        "account_server": required_text["account_server"],
        "symbol": required_text["symbol"],
        "timeframe": required_text["timeframe"].upper(),
        "mt5_build": required_text["mt5_build"],
        "modelling": required_text["modelling"],
        "tester_model": tester_model,
        "expert": required_text["expert"],
        "execution_mode": execution_mode,
        "portable_mode": portable_mode,
        "deposit": deposit,
        "currency": required_text["currency"].upper(),
        "leverage": int(leverage),
        "spread_mode": required_text["spread_mode"],
        "commission": commission,
        "swap_mode": required_text["swap_mode"],
        "slippage_points": slippage_points,
        "optimization": False,
        "forward_mode": "disabled",
        "forward_mode_code": 0,
    }

    if approved:
        placeholder_fields = [
            field
            for field in (
                "environment_id",
                "broker_label",
                "account_company",
                "account_server",
                "mt5_build",
            )
            if _contains_placeholder(str(normalized[field]))
        ]
        if placeholder_fields:
            raise RegistryValidationError(
                "approved execution environment contains placeholder values: "
                + ", ".join(placeholder_fields)
            )
    return normalized


def load_execution_environment_contract(
    path: str | Path,
) -> tuple[dict[str, Any], str]:
    target = Path(path).resolve()
    normalized = validate_execution_environment(_load(target))
    return normalized, sha256_file(target)


def canonical_environment_sha256(environment: dict[str, Any]) -> str:
    normalized = validate_execution_environment(environment)
    payload = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_environment_attestation(
    attestation: dict[str, Any],
    contract: dict[str, Any],
    contract_file_sha256: str,
) -> dict[str, Any]:
    normalized_contract = validate_execution_environment(contract)

    if attestation.get("schema_version") != 1:
        raise RegistryValidationError("environment attestation schema_version must be 1")
    if attestation.get("methodology") != "MT5_EXECUTION_ENVIRONMENT_ATTESTATION_V1":
        raise RegistryValidationError("unsupported environment attestation methodology")
    if attestation.get("status") != "VERIFIED":
        raise RegistryValidationError("execution environment attestation is not VERIFIED")
    if attestation.get("live_trading_authorized") is not False:
        raise RegistryValidationError("environment attestation must deny live trading")
    if attestation.get("contract_file_sha256") != contract_file_sha256:
        raise RegistryValidationError("environment attestation contract SHA-256 mismatch")
    if attestation.get("environment_id") != normalized_contract["environment_id"]:
        raise RegistryValidationError("environment attestation environment_id mismatch")

    observed = attestation.get("observed")
    if not isinstance(observed, dict):
        raise RegistryValidationError("environment attestation observed payload is missing")

    expected = {
        "trade_mode": normalized_contract["require_trade_mode"],
        "account_company": normalized_contract["account_company"],
        "account_server": normalized_contract["account_server"],
        "symbol": normalized_contract["symbol"],
        "mt5_build": normalized_contract["mt5_build"],
    }
    for field, expected_value in expected.items():
        actual = observed.get(field)
        if str(actual).strip() != str(expected_value).strip():
            raise RegistryValidationError(
                f"environment attestation {field} mismatch: "
                f"expected {expected_value!r}, got {actual!r}"
            )

    if observed.get("terminal_connected") is not True:
        raise RegistryValidationError("environment attestation requires terminal_connected=true")
    if observed.get("symbol_synchronized") is not True:
        raise RegistryValidationError("environment attestation requires symbol_synchronized=true")

    return {
        "schema_version": 1,
        "methodology": "MT5_EXECUTION_ENVIRONMENT_ATTESTATION_V1",
        "status": "VERIFIED",
        "live_trading_authorized": False,
        "environment_id": normalized_contract["environment_id"],
        "contract_file_sha256": contract_file_sha256,
        "observed": observed,
        "python_api_version": attestation.get("python_api_version"),
    }


def load_and_validate_attestation(
    path: str | Path,
    contract: dict[str, Any],
    contract_file_sha256: str,
) -> tuple[dict[str, Any], str]:
    target = Path(path).resolve()
    result = validate_environment_attestation(
        _load(target), contract, contract_file_sha256
    )
    return result, sha256_file(target)
