from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.campaign_contract import robustness_template_sha256
from scripts.experiment_registry import RegistryValidationError
from scripts.materialize_robustness_template import materialize_robustness_template


def _write(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _environment(label: str, company: str, server: str, *, approved: bool = True) -> dict:
    return {
        "schema_version": 1,
        "environment_id": f"GTX-{label}-DEMO",
        "approved": approved,
        "live_trading_authorized": False,
        "require_trade_mode": "DEMO",
        "broker_label": label,
        "account_company": company,
        "account_server": server,
        "symbol": "XAUUSD",
        "timeframe": "M15",
        "mt5_build": "5555",
        "modelling": "Every tick based on real ticks",
        "tester_model": 4,
        "expert": "GoldenTradeX\\\\GoldenTradeX.ex5",
        "execution_mode": 0,
        "portable_mode": True,
        "deposit": 10000,
        "currency": "USD",
        "leverage": 100,
        "spread_mode": "tester/broker observed",
        "commission": None,
        "swap_mode": "tester/broker observed",
        "slippage_points": 0,
        "optimization": False,
        "forward_mode": "disabled",
        "forward_mode_code": 0,
        "symbol_contract": {
            "digits": 2,
            "point": 0.01,
            "trade_contract_size": 100.0,
            "trade_tick_size": 0.01,
            "trade_tick_value": 1.0,
            "currency_profit": "USD",
        },
    }


def _base_template(tmp_path: Path) -> Path:
    return _write(
        tmp_path / "base.json",
        {
            "schema_version": 1,
            "template_id": "BASE-DRAFT",
            "parameter_scenarios": [
                {"name": "ema_minus", "parameter": "InpEmaFast", "value": 18},
                {"name": "ema_plus", "parameter": "InpEmaFast", "value": 24},
            ],
            "broker_requirements": {
                "required_labels": ["PLACEHOLDER-A", "PLACEHOLDER-B"],
                "minimum_distinct_brokers": 2,
            },
            "modeled_cost_scenarios": [
                {"name": "cost_1", "cost_per_trade_currency": 1.0},
                {"name": "cost_2", "cost_per_trade_currency": 2.0},
            ],
            "executed_metadata_stress": [],
        },
    )


def test_materializes_brokers_from_approved_demo_environments(tmp_path: Path) -> None:
    first = _write(
        tmp_path / "broker_a.json",
        _environment("BROKER-A", "Broker A Ltd", "BrokerA-Demo"),
    )
    second = _write(
        tmp_path / "broker_b.json",
        _environment("BROKER-B", "Broker B Ltd", "BrokerB-Demo"),
    )
    output = tmp_path / "robustness_template.v1.json"
    audit_output = tmp_path / "audit.json"

    template, audit = materialize_robustness_template(
        base_template_path=_base_template(tmp_path),
        environment_paths=[first, second],
        output_path=output,
        audit_output_path=audit_output,
    )

    assert template["template_id"] == "GTX-ROBUSTNESS-TEMPLATE-V1"
    assert template["broker_requirements"]["required_labels"] == ["BROKER-A", "BROKER-B"]
    assert template["broker_requirements"]["minimum_distinct_brokers"] == 2
    assert audit["template_sha256"] == robustness_template_sha256(template)
    assert len(audit["source_environments"]) == 2
    assert audit["live_trading_authorized"] is False
    assert audit["real_capital_authorized"] is False
    assert output.is_file()
    assert audit_output.is_file()


def test_rejects_unapproved_environment(tmp_path: Path) -> None:
    first = _write(
        tmp_path / "broker_a.json",
        _environment("BROKER-A", "Broker A Ltd", "BrokerA-Demo", approved=False),
    )
    second = _write(
        tmp_path / "broker_b.json",
        _environment("BROKER-B", "Broker B Ltd", "BrokerB-Demo"),
    )

    with pytest.raises(RegistryValidationError, match="not approved"):
        materialize_robustness_template(
            base_template_path=_base_template(tmp_path),
            environment_paths=[first, second],
        )


def test_rejects_duplicate_broker_identity(tmp_path: Path) -> None:
    first = _write(
        tmp_path / "broker_a.json",
        _environment("BROKER-A", "Broker A Ltd", "BrokerA-Demo"),
    )
    second = _write(
        tmp_path / "broker_b.json",
        _environment("BROKER-B", "Broker A Ltd", "BrokerA-Demo"),
    )

    with pytest.raises(RegistryValidationError, match="distinct company/server identities"):
        materialize_robustness_template(
            base_template_path=_base_template(tmp_path),
            environment_paths=[first, second],
        )


def test_rejects_environment_without_symbol_contract(tmp_path: Path) -> None:
    first_payload = _environment("BROKER-A", "Broker A Ltd", "BrokerA-Demo")
    first_payload.pop("symbol_contract")
    first = _write(tmp_path / "broker_a.json", first_payload)
    second = _write(
        tmp_path / "broker_b.json",
        _environment("BROKER-B", "Broker B Ltd", "BrokerB-Demo"),
    )

    with pytest.raises(RegistryValidationError, match="lacks frozen symbol_contract"):
        materialize_robustness_template(
            base_template_path=_base_template(tmp_path),
            environment_paths=[first, second],
        )


def test_requires_at_least_two_environments(tmp_path: Path) -> None:
    first = _write(
        tmp_path / "broker_a.json",
        _environment("BROKER-A", "Broker A Ltd", "BrokerA-Demo"),
    )

    with pytest.raises(RegistryValidationError, match="at least two"):
        materialize_robustness_template(
            base_template_path=_base_template(tmp_path),
            environment_paths=[first],
        )


def test_materializes_single_target_broker_from_one_approved_demo_environment(tmp_path: Path) -> None:
    first = _write(
        tmp_path / "xm.json",
        _environment("XM Global Limited", "XM Global Limited", "XMGlobal-MT5 2"),
    )
    base = json.loads(_base_template(tmp_path).read_text(encoding="utf-8"))
    base["validation_scope"] = "TARGET_BROKER_SINGLE"
    base["broker_requirements"] = {
        "required_labels": ["PLACEHOLDER-XM"],
        "minimum_distinct_brokers": 1,
    }
    base_path = _write(tmp_path / "single_base.json", base)

    template, audit = materialize_robustness_template(
        base_template_path=base_path,
        environment_paths=[first],
    )

    assert template["validation_scope"] == "TARGET_BROKER_SINGLE"
    assert template["broker_requirements"]["required_labels"] == ["XM Global Limited"]
    assert template["broker_requirements"]["minimum_distinct_brokers"] == 1
    assert audit["validation_scope"] == "TARGET_BROKER_SINGLE"
    assert len(audit["source_environments"]) == 1
