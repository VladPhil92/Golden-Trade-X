from __future__ import annotations

import copy

import pytest

from scripts.execution_environment import validate_execution_environment
from scripts.experiment_registry import RegistryValidationError
from scripts.mt5_environment_discovery import build_discovered_environment


def _observed() -> dict[str, object]:
    return {
        "trade_mode": "DEMO",
        "account_company": "Example Broker Ltd",
        "account_server": "ExampleBroker-Demo",
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


def test_build_discovered_environment_is_unapproved_and_demo_only() -> None:
    candidate, audit = build_discovered_environment(_observed())
    normalized = validate_execution_environment(candidate)

    assert normalized["approved"] is False
    assert normalized["live_trading_authorized"] is False
    assert normalized["require_trade_mode"] == "DEMO"
    assert normalized["broker_label"] == "Example Broker Ltd"
    assert normalized["account_server"] == "ExampleBroker-Demo"
    assert normalized["mt5_build"] == "5320"
    assert audit["status"] == "CANDIDATE_DISCOVERED"
    assert audit["approved"] is False
    assert audit["live_trading_authorized"] is False
    assert audit["real_capital_authorized"] is False


def test_discovery_outputs_do_not_include_credentials() -> None:
    candidate, audit = build_discovered_environment(_observed())
    payload = repr(candidate).lower() + repr(audit).lower()

    assert "password" not in payload
    assert "login" not in payload


def test_environment_identity_is_deterministic() -> None:
    first, first_audit = build_discovered_environment(_observed())
    second, second_audit = build_discovered_environment(_observed())

    assert first["environment_id"] == second["environment_id"]
    assert first_audit["candidate_canonical_sha256"] == second_audit["candidate_canonical_sha256"]


def test_environment_identity_changes_with_server() -> None:
    observed = _observed()
    first, _ = build_discovered_environment(observed)
    changed = copy.deepcopy(observed)
    changed["account_server"] = "ExampleBroker-Demo2"
    second, _ = build_discovered_environment(changed)

    assert first["environment_id"] != second["environment_id"]


@pytest.mark.parametrize("mode", ["REAL", "CONTEST", "UNKNOWN_999"])
def test_discovery_rejects_non_demo_modes(mode: str) -> None:
    observed = _observed()
    observed["trade_mode"] = mode

    with pytest.raises(RegistryValidationError, match="requires DEMO"):
        build_discovered_environment(observed)


def test_discovery_rejects_disconnected_terminal() -> None:
    observed = _observed()
    observed["terminal_connected"] = False

    with pytest.raises(RegistryValidationError, match="terminal_connected"):
        build_discovered_environment(observed)


def test_discovery_rejects_unsynchronized_symbol() -> None:
    observed = _observed()
    observed["symbol_synchronized"] = False

    with pytest.raises(RegistryValidationError, match="symbol_synchronized"):
        build_discovered_environment(observed)
