#!/usr/bin/env python3
"""Inspect the already-running local MT5 session without requesting credentials."""

from __future__ import annotations

import argparse
import json
import platform
from pathlib import Path

try:
    from scripts.experiment_registry import RegistryValidationError
    from scripts.mt5_connection import connect_existing_mt5_session
except ModuleNotFoundError:
    from experiment_registry import RegistryValidationError
    from mt5_connection import connect_existing_mt5_session


def _trade_mode_label(mt5, value: int) -> str:
    mapping = {
        int(mt5.ACCOUNT_TRADE_MODE_DEMO): "DEMO",
        int(mt5.ACCOUNT_TRADE_MODE_CONTEST): "CONTEST",
        int(mt5.ACCOUNT_TRADE_MODE_REAL): "REAL",
    }
    return mapping.get(int(value), f"UNKNOWN_{value}")


def inspect_local_mt5(terminal_path: str | Path, output_path: str | Path) -> dict:
    if platform.system() != "Windows":
        raise RegistryValidationError("local MT5 runtime inspection is supported only on Windows")

    terminal = Path(terminal_path).resolve()
    if not terminal.is_file():
        raise RegistryValidationError(f"MetaTrader terminal not found: {terminal}")

    try:
        import MetaTrader5 as mt5
    except ImportError as exc:
        raise RegistryValidationError("MetaTrader5 Python package is required") from exc

    connect_existing_mt5_session(mt5, terminal_path=terminal, portable=False)
    try:
        terminal_info = mt5.terminal_info()
        account_info = mt5.account_info()
        if terminal_info is None:
            raise RegistryValidationError("terminal_info() returned no data")
        if account_info is None:
            raise RegistryValidationError("account_info() returned no data")

        trade_mode = _trade_mode_label(mt5, int(account_info.trade_mode))
        if trade_mode != "DEMO":
            raise RegistryValidationError(
                f"local official campaign requires DEMO trade mode, got {trade_mode}"
            )

        data_path = Path(str(terminal_info.data_path)).resolve()
        terminal_dir = terminal.parent.resolve()
        portable_mode = str(data_path).lower() == str(terminal_dir).lower()

        payload = {
            "schema_version": 1,
            "methodology": "LOCAL_MT5_RUNTIME_CONTEXT_V1",
            "trade_mode": trade_mode,
            "account_company": str(account_info.company),
            "account_server": str(account_info.server),
            "account_currency": str(account_info.currency),
            "leverage": int(account_info.leverage),
            "mt5_build": str(terminal_info.build),
            "terminal_connected": bool(terminal_info.connected),
            "terminal_path": str(terminal),
            "terminal_install_dir": str(terminal_dir),
            "data_path": str(data_path),
            "portable_mode": portable_mode,
            "live_trading_authorized": False,
            "real_capital_authorized": False,
        }
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return payload
    finally:
        mt5.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--terminal", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        result = inspect_local_mt5(args.terminal, args.output)
    except RegistryValidationError as exc:
        parser.error(str(exc))
        return
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
