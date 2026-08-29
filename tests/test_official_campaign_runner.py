import json
from pathlib import Path

import pytest

from scripts.execution_environment import (
    canonical_environment_sha256,
    validate_execution_environment,
)
from scripts.experiment_registry import RegistryValidationError, sha256_file
from scripts.official_campaign_freeze import freeze_official_campaign
from scripts.official_campaign_runner import prepare_official_campaign


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _policy(path: Path, policy_id: str, *, approved: bool = True) -> Path:
    return _write_json(
        path,
        {
            "schema_version": 1,
            "policy_id": policy_id,
            "approved": approved,
            "criteria": [{"metric": "placeholder", "operator": ">", "value": 0}],
        },
    )


def _environment(*, approved: bool = True) -> dict:
    return {
        "schema_version": 1,
        "environment_id": "TEST-XAUUSD-DEMO-ENV",
        "approved": approved,
        "live_trading_authorized": False,
        "require_trade_mode": "DEMO",
        "broker_label": "TEST-BROKER-CANONICAL",
        "account_company": "Test Broker Ltd",
        "account_server": "TestBroker-Demo",
        "symbol": "XAUUSD",
        "timeframe": "M15",
        "mt5_build": "5555",
        "modelling": "Every tick based on real ticks",
        "tester_model": 4,
        "expert": "GoldenTradeX\\GoldenTradeX.ex5",
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
    }


def _campaign_inputs(tmp_path: Path, *, environment_approved: bool = True) -> tuple[Path, Path, Path]:
    source = Path("config/GoldenTradeX.set").read_text(encoding="utf-8")
    baseline = tmp_path / "baseline.set"
    baseline.write_text(source, encoding="utf-8")
    alternative = tmp_path / "alternative.set"
    alternative.write_text(
        source.replace("InpMinConfidence=55", "InpMinConfidence=54"),
        encoding="utf-8",
    )

    promotion = _policy(tmp_path / "promotion.json", "TEST-PROMOTION")
    robustness = _policy(tmp_path / "robustness.json", "TEST-ROBUSTNESS")
    forward = _policy(tmp_path / "forward.json", "TEST-FORWARD")
    environment_path = _write_json(
        tmp_path / "environment.json",
        _environment(approved=environment_approved),
    )

    walk = _write_json(
        tmp_path / "walk.json",
        {
            "schema_version": 1,
            "plan_id": "TEST-WF-OFFICIAL",
            "start_date": "2022-01-01",
            "end_date": "2023-01-01",
            "in_sample_months": 6,
            "oos_months": 3,
            "step_months": 3,
            "embargo_days": 0,
            "minimum_folds": 2,
            "selection_policy": {
                "policy_id": "TEST-IS-SELECTION",
                "objective": {"metric": "profit_factor", "direction": "maximize"},
                "constraints": [
                    {"metric": "total_trades", "operator": ">=", "value": 20}
                ],
                "tie_breakers": [
                    {"metric": "expected_payoff", "direction": "maximize"}
                ],
            },
            "promotion_policy_path": promotion.name,
        },
    )

    template = _write_json(
        tmp_path / "robustness_template.json",
        {
            "schema_version": 1,
            "template_id": "TEST-ROBUSTNESS-TEMPLATE",
            "parameter_scenarios": [
                {"name": "ema_minus", "parameter": "InpEmaFast", "value": 18},
                {"name": "ema_plus", "parameter": "InpEmaFast", "value": 24},
            ],
            "broker_requirements": {
                "required_labels": ["BROKER-A", "BROKER-B"],
                "minimum_distinct_brokers": 2,
            },
            "modeled_cost_scenarios": [
                {"name": "cost_1", "cost_per_trade_currency": 1.0}
            ],
            "executed_metadata_stress": [],
        },
    )

    config = _write_json(
        tmp_path / "campaign.json",
        {
            "schema_version": 1,
            "campaign_id": "TEST-OFFICIAL-RUNNER",
            "build_id": "a" * 40,
            "candidate_universe": [
                {"name": "baseline", "preset_path": baseline.name},
                {"name": "alternative", "preset_path": alternative.name},
            ],
            "execution_environment_path": environment_path.name,
            "walk_forward_config_path": walk.name,
            "robustness_template_path": template.name,
            "robustness_policy_path": robustness.name,
            "forward_policy_path": forward.name,
        },
    )
    return config, baseline, environment_path


def _attestation(tmp_path: Path, environment_path: Path, *, company: str = "Test Broker Ltd") -> Path:
    environment = json.loads(environment_path.read_text(encoding="utf-8"))
    return _write_json(
        tmp_path / "attestation.json",
        {
            "schema_version": 1,
            "methodology": "MT5_EXECUTION_ENVIRONMENT_ATTESTATION_V1",
            "status": "VERIFIED",
            "live_trading_authorized": False,
            "environment_id": environment["environment_id"],
            "contract_file_sha256": sha256_file(environment_path),
            "python_api_version": "5.0.test",
            "observed": {
                "trade_mode": "DEMO",
                "account_company": company,
                "account_server": environment["account_server"],
                "symbol": environment["symbol"],
                "mt5_build": environment["mt5_build"],
                "terminal_connected": True,
                "symbol_synchronized": True,
            },
        },
    )


def test_approved_execution_environment_rejects_placeholders() -> None:
    environment = _environment()
    environment["broker_label"] = "REPLACE_WITH_BROKER"
    with pytest.raises(RegistryValidationError, match="placeholder"):
        validate_execution_environment(environment)


def test_official_freeze_requires_approved_execution_environment(tmp_path: Path) -> None:
    config, _, _ = _campaign_inputs(tmp_path, environment_approved=False)
    with pytest.raises(RegistryValidationError, match="approved execution environment"):
        freeze_official_campaign(config, tmp_path / "freeze")

    draft = freeze_official_campaign(config, tmp_path / "draft", allow_draft=True)
    assert draft["status"] == "ENGINEERING_DRAFT_NOT_OFFICIAL"


def test_freeze_can_bind_checked_out_sha_without_self_reference(tmp_path: Path) -> None:
    config, _, environment_path = _campaign_inputs(tmp_path)
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["build_id"] = "0" * 40
    _write_json(config, payload)

    result = freeze_official_campaign(
        config,
        tmp_path / "freeze",
        build_id_override="b" * 40,
    )
    environment = json.loads(environment_path.read_text(encoding="utf-8"))

    assert result["build_id"] == "b" * 40
    assert result["execution_environment"]["file_sha256"] == sha256_file(environment_path)
    assert result["execution_environment"]["canonical_sha256"] == canonical_environment_sha256(
        environment
    )


def test_prepare_builds_every_fold_candidate_from_frozen_environment(tmp_path: Path) -> None:
    config, _, environment_path = _campaign_inputs(tmp_path)
    freeze_dir = tmp_path / "freeze"
    lock = freeze_official_campaign(config, freeze_dir)
    attestation = _attestation(tmp_path, environment_path)

    execution = prepare_official_campaign(
        freeze_dir / "campaign_lock.json",
        attestation,
        tmp_path,
        tmp_path / "execution",
        actual_git_sha="a" * 40,
    )

    assert execution["status"] == "PREPARED_NOT_EXECUTED"
    assert execution["live_trading_authorized"] is False
    assert execution["real_capital_authorized"] is False
    assert execution["candidate_universe_sha256"] == lock["candidate_universe"]["sha256"]
    assert len(execution["folds"]) == 2

    for fold in execution["folds"]:
        execution_set = json.loads(
            (tmp_path / "execution" / fold["is_execution_set"]).read_text(encoding="utf-8")
        )
        assert execution_set["candidate_universe_sha256"] == lock["candidate_universe"]["sha256"]
        assert len(execution_set["candidates"]) == 2
        for candidate in execution_set["candidates"]:
            spec_path = tmp_path / "execution" / candidate["spec"]
            spec = json.loads(spec_path.read_text(encoding="utf-8"))
            assert spec["git_sha"] == "a" * 40
            assert spec["broker"] == "TEST-BROKER-CANONICAL"
            assert spec["mt5_build"] == "5555"
            assert spec["symbol"] == "XAUUSD"
            assert spec["optimization"] is False


def test_prepare_rejects_runtime_build_drift(tmp_path: Path) -> None:
    config, _, environment_path = _campaign_inputs(tmp_path)
    freeze_dir = tmp_path / "freeze"
    freeze_official_campaign(config, freeze_dir)
    attestation = _attestation(tmp_path, environment_path)

    with pytest.raises(RegistryValidationError, match="runtime Git SHA differs"):
        prepare_official_campaign(
            freeze_dir / "campaign_lock.json",
            attestation,
            tmp_path,
            tmp_path / "execution",
            actual_git_sha="b" * 40,
        )


def test_prepare_rejects_attested_broker_drift(tmp_path: Path) -> None:
    config, _, environment_path = _campaign_inputs(tmp_path)
    freeze_dir = tmp_path / "freeze"
    freeze_official_campaign(config, freeze_dir)
    attestation = _attestation(tmp_path, environment_path, company="Other Broker Ltd")

    with pytest.raises(RegistryValidationError, match="account_company mismatch"):
        prepare_official_campaign(
            freeze_dir / "campaign_lock.json",
            attestation,
            tmp_path,
            tmp_path / "execution",
            actual_git_sha="a" * 40,
        )


def test_prepare_rejects_candidate_mutation_after_freeze(tmp_path: Path) -> None:
    config, baseline, environment_path = _campaign_inputs(tmp_path)
    freeze_dir = tmp_path / "freeze"
    freeze_official_campaign(config, freeze_dir)
    attestation = _attestation(tmp_path, environment_path)

    baseline.write_text(
        baseline.read_text(encoding="utf-8").replace(
            "InpMinConfidence=55", "InpMinConfidence=56"
        ),
        encoding="utf-8",
    )

    with pytest.raises(RegistryValidationError, match="changed after campaign freeze"):
        prepare_official_campaign(
            freeze_dir / "campaign_lock.json",
            attestation,
            tmp_path,
            tmp_path / "execution",
            actual_git_sha="a" * 40,
        )
