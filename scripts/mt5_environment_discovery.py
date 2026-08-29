#!/usr/bin/env python3
"""Discover a real MT5 DEMO environment and emit an unapproved review contract.

This tool is intentionally separate from runtime attestation. Discovery is allowed
before an execution-environment contract is approved, but it is fail-closed on
non-DEMO accounts and never writes credentials or account login identifiers to
its outputs. The generated contract is always approved=false and therefore cannot
unlock official campaign execution by itself.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
from pathlib import Path
from typing import Any

try:
    from scripts.execution_environment import (
        canonical_environment_sha256,
        validate_execution_environment,
    )
    from scripts.experiment_registry import RegistryValidationError
except ModuleNotFoundError:
    from execution_environment import canonical_environment_sha256, validate_execution_environment
    from experiment_registry import RegistryValidationError

METHODOLOGY = "MT5_EXECUTION_ENVIRONMENT_DISCOVERY_V1"


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


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RegistryValidationError(f"{field} is required")
    return value.strip()


def _positive_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RegistryValidationError(f"{field} must be a number > 0")
    parsed = float(value)
    if parsed <= 0:
        raise RegistryValidationError(f"{field} must be a number > 0")
    return parsed


def build_discovered_environment(
    observed: dict[str, Any],
    *,
    timeframe: str = "M15",
    deposit: float = 10000.0,
    portable_mode: bool = True,
    modelling: str = "Every tick based on real ticks",
    tester_model: int = 4,
    expert: str = "GoldenTradeX\\GoldenTradeX.ex5",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build a deterministic unapproved contract from sanitized observed metadata."""

    trade_mode = _text(observed.get("trade_mode"), "trade_mode").upper()
    if trade_mode != "DEMO":
        raise RegistryValidationError(
            f"environment discovery requires DEMO trade mode, observed {trade_mode!r}"
        )
    if observed.get("terminal_connected") is not True:
        raise RegistryValidationError("environment discovery requires terminal_connected=true")
    if observed.get("symbol_synchronized") is not True:
        raise RegistryValidationError("environment discovery requires symbol_synchronized=true")

    company = _text(observed.get("account_company"), "account_company")
    server = _text(observed.get("account_server"), "account_server")
    currency = _text(observed.get("account_currency"), "account_currency").upper()
    symbol = _text(observed.get("symbol"), "symbol")
    build = _text(str(observed.get("mt5_build", "")), "mt5_build")
    tf = _text(timeframe, "timeframe").upper()
    leverage = _positive_number(observed.get("leverage"), "leverage")
    if not leverage.is_integer():
        raise RegistryValidationError("observed leverage must be an integer ratio denominator")
    initial_deposit = _positive_number(deposit, "deposit")

    identity = "|".join((company, server, symbol, tf, build)).encode("utf-8")
    digest = hashlib.sha256(identity).hexdigest()[:12].upper()
    environment_id = f"GTX-{symbol.upper()}-{tf}-DEMO-{digest}"

    candidate = {
        "schema_version": 1,
        "environment_id": environment_id,
        "approved": False,
        "status_note": (
            "Observed from a real connected MT5 DEMO account. Review and explicitly approve "
            "this immutable contract before official evidence generation."
        ),
        "live_trading_authorized": False,
        "require_trade_mode": "DEMO",
        "broker_label": company,
        "account_company": company,
        "account_server": server,
        "symbol": symbol,
        "timeframe": tf,
        "mt5_build": build,
        "modelling": _text(modelling, "modelling"),
        "tester_model": int(tester_model),
        "expert": _text(expert, "expert"),
        "execution_mode": 0,
        "portable_mode": bool(portable_mode),
        "deposit": initial_deposit,
        "currency": currency,
        "leverage": int(leverage),
        "spread_mode": "tester/broker observed",
        "commission": None,
        "swap_mode": "tester/broker observed",
        "slippage_points": 0.0,
        "optimization": False,
        "forward_mode": "disabled",
        "forward_mode_code": 0,
    }

    # Validate against the same schema used later by campaign readiness.
    normalized = validate_execution_environment(candidate)
    if normalized["approved"] is not False:
        raise RegistryValidationError("discovery candidate must remain approved=false")

    safe_observed = {
        "trade_mode": trade_mode,
        "account_company": company,
        "account_server": server,
        "account_currency": currency,
        "leverage": int(leverage),
        "symbol": symbol,
        "mt5_build": build,
        "terminal_connected": True,
        "symbol_synchronized": True,
        "symbol_digits": int(observed.get("symbol_digits", 0)),
        "symbol_point": float(observed.get("symbol_point", 0.0)),
        "trade_contract_size": float(observed.get("trade_contract_size", 0.0)),
        "trade_tick_size": float(observed.get("trade_tick_size", 0.0)),
        "trade_tick_value": float(observed.get("trade_tick_value", 0.0)),
        "currency_profit": str(observed.get("currency_profit", "")),
    }
    audit = {
        "schema_version": 1,
        "methodology": METHODOLOGY,
        "status": "CANDIDATE_DISCOVERED",
        "approved": False,
        "live_trading_authorized": False,
        "real_capital_authorized": False,
        "environment_id": environment_id,
        "candidate_canonical_sha256": canonical_environment_sha256(candidate),
        "observed": safe_observed,
    }
    return candidate, audit


def discover_mt5_environment(
    terminal_path: str | Path,
    output_contract: str | Path,
    output_audit: str | Path,
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M15",
    deposit: float = 10000.0,
    portable_mode: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if platform.system() != "Windows":
        raise RegistryValidationError("MT5 environment discovery is supported only on Windows")

    terminal = Path(terminal_path).resolve()
    if not terminal.is_file():
        raise RegistryValidationError(f"MetaTrader terminal not found: {terminal}")

    login_text = _required_env("GTX_MT5_LOGIN")
    password = _required_env("GTX_MT5_PASSWORD")
    requested_server = _required_env("GTX_MT5_SERVER")
    try:
        login = int(login_text)
    except ValueError as exc:
        raise RegistryValidationError("GTX_MT5_LOGIN must be an integer account login") from exc

    try:
        import MetaTrader5 as mt5
    except ImportError as exc:
        raise RegistryValidationError(
            "MetaTrader5 Python package is required for environment discovery"
        ) from exc

    initialized = mt5.initialize(
        str(terminal),
        login=login,
        password=password,
        server=requested_server,
        portable=bool(portable_mode),
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

        trade_mode = _trade_mode_label(mt5, int(account_info.trade_mode))
        if trade_mode != "DEMO":
            raise RegistryValidationError(
                f"environment discovery refuses non-DEMO account: observed {trade_mode}"
            )
        if str(account_info.server).strip() != requested_server:
            raise RegistryValidationError(
                "observed account server differs from GTX_MT5_SERVER"
            )
        if not bool(terminal_info.connected):
            raise RegistryValidationError("MetaTrader terminal is not connected")

        requested_symbol = _text(symbol, "symbol")
        if not mt5.symbol_select(requested_symbol, True):
            code, message = mt5.last_error()
            raise RegistryValidationError(
                f"cannot select symbol {requested_symbol}: code={code}, message={message}"
            )
        symbol_info = mt5.symbol_info(requested_symbol)
        if symbol_info is None:
            raise RegistryValidationError(
                f"MetaTrader5 symbol_info({requested_symbol!r}) returned no data"
            )
        synchronized = mt5.symbol_info_tick(requested_symbol) is not None

        observed = {
            "trade_mode": trade_mode,
            "account_company": str(account_info.company),
            "account_server": str(account_info.server),
            "account_currency": str(account_info.currency),
            "leverage": int(account_info.leverage),
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
        candidate, audit = build_discovered_environment(
            observed,
            timeframe=timeframe,
            deposit=deposit,
            portable_mode=portable_mode,
        )

        contract_target = Path(output_contract)
        audit_target = Path(output_audit)
        contract_target.parent.mkdir(parents=True, exist_ok=True)
        audit_target.parent.mkdir(parents=True, exist_ok=True)
        contract_target.write_text(
            json.dumps(candidate, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        audit_target.write_text(
            json.dumps(audit, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return candidate, audit
    finally:
        mt5.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--terminal", required=True)
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M15")
    parser.add_argument("--deposit", type=float, default=10000.0)
    parser.add_argument("--portable-mode", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument(
        "--output-contract",
        default="data/research/environment-discovery/execution_environment.candidate.json",
    )
    parser.add_argument(
        "--output-audit",
        default="data/research/environment-discovery/execution_environment.discovery.json",
    )
    args = parser.parse_args()
    try:
        candidate, audit = discover_mt5_environment(
            args.terminal,
            args.output_contract,
            args.output_audit,
            symbol=args.symbol,
            timeframe=args.timeframe,
            deposit=args.deposit,
            portable_mode=args.portable_mode,
        )
    except RegistryValidationError as exc:
        parser.error(str(exc))
        return
    print(json.dumps({
        "status": audit["status"],
        "environment_id": candidate["environment_id"],
        "broker_label": candidate["broker_label"],
        "account_server": candidate["account_server"],
        "mt5_build": candidate["mt5_build"],
        "approved": False,
        "live_trading_authorized": False,
        "real_capital_authorized": False,
    }, indent=2, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
