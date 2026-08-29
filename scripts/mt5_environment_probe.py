#!/usr/bin/env python3
"""Produce a fail-closed runtime attestation for an approved MT5 research environment."""

from __future__ import annotations

import argparse
import json
import os
import platform
from pathlib import Path
from typing import Any

try:
    from scripts.execution_environment import (
        load_execution_environment_contract,
        validate_environment_attestation,
    )
    from scripts.experiment_registry import RegistryValidationError
except ModuleNotFoundError:
    from execution_environment import (
        load_execution_environment_contract,
        validate_environment_attestation,
    )
    from experiment_registry import RegistryValidationError


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value or not value.strip():
        raise RegistryValidationError(f"missing required environment variable: {name}")
    return value.strip()


def _trade_mode_label(mt5: Any, value: int) -> str:
    mapping = {
        int(mt5.ACCOUNT_TRADE_MODE_DEMO): "DEMO",
        int(mt5.ACCOUNT_TRADE_MODE_CONTEST): "CONTEST",
        int(mt5.ACCOUNT_TRADE_MODE_REAL): "REAL",
    }
    return mapping.get(int(value), f"UNKNOWN_{value}")


def create_mt5_environment_attestation(
    contract_path: str | Path,
    terminal_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    if platform.system() != "Windows":
        raise RegistryValidationError("MT5 environment attestation is supported only on Windows")

    terminal = Path(terminal_path).resolve()
    if not terminal.is_file():
        raise RegistryValidationError(f"MetaTrader terminal not found: {terminal}")

    contract, contract_sha = load_execution_environment_contract(contract_path)
    if contract["approved"] is not True:
        raise RegistryValidationError(
            "runtime attestation requires an approved execution environment contract"
        )

    login_text = _required_env("GTX_MT5_LOGIN")
    password = _required_env("GTX_MT5_PASSWORD")
    server = _required_env("GTX_MT5_SERVER")
    try:
        login = int(login_text)
    except ValueError as exc:
        raise RegistryValidationError("GTX_MT5_LOGIN must be an integer account login") from exc
    if server != contract["account_server"]:
        raise RegistryValidationError(
            "GTX_MT5_SERVER differs from the frozen execution environment account_server"
        )

    try:
        import MetaTrader5 as mt5
    except ImportError as exc:
        raise RegistryValidationError(
            "MetaTrader5 Python package is required for runtime attestation"
        ) from exc

    initialized = mt5.initialize(
        str(terminal),
        login=login,
        password=password,
        server=server,
        portable=bool(contract["portable_mode"]),
    )
    if not initialized:
        code, message = mt5.last_error()
        raise RegistryValidationError(
            f"MetaTrader5 initialize failed: code={code}, message={message}"
        )

    try:
        terminal_info = mt5.terminal_info()
        account_info = mt5.account_info()
        if terminal_info is None:
            raise RegistryValidationError("MetaTrader5 terminal_info() returned no data")
        if account_info is None:
            raise RegistryValidationError("MetaTrader5 account_info() returned no data")

        symbol = contract["symbol"]
        if not mt5.symbol_select(symbol, True):
            code, message = mt5.last_error()
            raise RegistryValidationError(
                f"cannot select frozen symbol {symbol}: code={code}, message={message}"
            )
        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            raise RegistryValidationError(f"MetaTrader5 symbol_info({symbol!r}) returned no data")

        synchronized = True
        if hasattr(mt5, "symbol_info_tick"):
            synchronized = mt5.symbol_info_tick(symbol) is not None

        observed = {
            "trade_mode": _trade_mode_label(mt5, int(account_info.trade_mode)),
            "account_company": str(account_info.company),
            "account_server": str(account_info.server),
            "account_currency": str(account_info.currency),
            "symbol": str(symbol_info.name),
            "mt5_build": str(terminal_info.build),
            "terminal_connected": bool(terminal_info.connected),
            "symbol_synchronized": bool(synchronized),
            "symbol_digits": int(symbol_info.digits),
            "symbol_point": float(symbol_info.point),
            "trade_contract_size": float(symbol_info.trade_contract_size),
            "trade_tick_size": float(symbol_info.trade_tick_size),
            "trade_tick_value": float(symbol_info.trade_tick_value),
            "currency_profit": str(symbol_info.currency_profit),
        }
        payload = {
            "schema_version": 1,
            "methodology": "MT5_EXECUTION_ENVIRONMENT_ATTESTATION_V1",
            "status": "VERIFIED",
            "live_trading_authorized": False,
            "environment_id": contract["environment_id"],
            "contract_file_sha256": contract_sha,
            "python_api_version": getattr(mt5, "__version__", None),
            "observed": observed,
        }
        validated = validate_environment_attestation(payload, contract, contract_sha)
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(validated, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return validated
    finally:
        mt5.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--terminal", required=True)
    parser.add_argument(
        "--output",
        default="data/research/official_campaign/environment_attestation.json",
    )
    args = parser.parse_args()
    try:
        result = create_mt5_environment_attestation(
            args.contract,
            args.terminal,
            args.output,
        )
    except RegistryValidationError as exc:
        parser.error(str(exc))
        return
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
