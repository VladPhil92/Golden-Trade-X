import json
from pathlib import Path

import pytest

from scripts.campaign_contract import (
    candidate_universe_sha256,
    candidate_universe_snapshot,
    robustness_template_sha256,
    robustness_template_snapshot,
)
from scripts.execution_environment import (
    canonical_environment_sha256,
    load_and_validate_attestation,
    load_execution_environment_contract,
    validate_environment_attestation,
    validate_execution_environment,
)
from scripts.experiment_registry import RegistryValidationError, sha256_file
from scripts.forward_demo_gate import _compare as forward_compare
from scripts.forward_demo_gate import evaluate_forward_demo_gate


def _write_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def test_candidate_universe_canonicalizes_order_case_and_hash() -> None:
    entries = [
        {"name": "zeta", "preset_sha256": "A" * 64},
        {"name": "alpha", "preset_sha256": "b" * 64},
    ]
    snapshot = candidate_universe_snapshot(entries)
    assert [row["name"] for row in snapshot] == ["alpha", "zeta"]
    assert snapshot[1]["preset_sha256"] == "a" * 64
    assert candidate_universe_sha256(entries) == candidate_universe_sha256(list(reversed(entries)))


@pytest.mark.parametrize(
    ("entries", "message"),
    [
        (None, "non-empty array"),
        ([], "non-empty array"),
        (["bad"], "entry must be an object"),
        ([{"name": "", "preset_sha256": "a" * 64}], "requires name"),
        ([{"name": "x", "preset_sha256": "short"}], "SHA-256"),
        ([{"name": "x", "preset_sha256": "a" * 64}, {"name": "x", "preset_sha256": "b" * 64}], "duplicate candidate name"),
        ([{"name": "x", "preset_sha256": "a" * 64}, {"name": "y", "preset_sha256": "A" * 64}], "duplicate candidate preset hash"),
    ],
)
def test_candidate_universe_fails_closed(entries, message: str) -> None:
    with pytest.raises(RegistryValidationError, match=message):
        candidate_universe_snapshot(entries)


def _robustness_template() -> dict:
    return {
        "template_id": "ROBUST-V1",
        "parameter_scenarios": [
            {"name": "z", "parameter": "InpA", "value": 2},
            {"name": "a", "parameter": "InpB", "value": False},
        ],
        "broker_requirements": {
            "required_labels": ["BROKER-B", "BROKER-A"],
            "minimum_distinct_brokers": 2,
        },
        "modeled_cost_scenarios": [
            {"name": "wide", "cost_per_trade_currency": 2},
            {"name": "base", "cost_per_trade_currency": 0.5},
        ],
        "executed_metadata_stress": [],
    }


def test_robustness_template_canonicalizes_and_hashes() -> None:
    snapshot = robustness_template_snapshot(_robustness_template())
    assert snapshot["template_id"] == "ROBUST-V1"
    assert [row["name"] for row in snapshot["parameter_scenarios"]] == ["a", "z"]
    assert snapshot["broker_requirements"]["required_labels"] == ["BROKER-A", "BROKER-B"]
    assert [row["name"] for row in snapshot["modeled_cost_scenarios"]] == ["base", "wide"]
    assert len(robustness_template_sha256(_robustness_template())) == 64


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda d: None, "robustness template must be an object"),
        (lambda d: d.update(template_id=""), "template_id"),
        (lambda d: d.update(parameter_scenarios=[]), "parameter_scenarios"),
        (lambda d: d.update(parameter_scenarios=["bad"]), "scenario must be an object"),
        (lambda d: d.update(parameter_scenarios=[{"name": "", "parameter": "x", "value": 1}]), "requires name"),
        (lambda d: d.update(parameter_scenarios=[{"name": "x", "parameter": "", "value": 1}]), "parameter is required"),
        (lambda d: d.update(parameter_scenarios=[{"name": "x", "parameter": "p"}]), "value is required"),
        (lambda d: d.update(parameter_scenarios=[{"name": "x", "parameter": "p", "value": 1}, {"name": "x", "parameter": "q", "value": 2}]), "duplicate robustness parameter scenario"),
        (lambda d: d.update(broker_requirements=None), "broker_requirements"),
        (lambda d: d.update(broker_requirements={"required_labels": []}), "requires broker labels"),
        (lambda d: d.update(broker_requirements={"required_labels": [""]}), "broker labels must be non-empty"),
        (lambda d: d.update(broker_requirements={"required_labels": ["A", "A"]}), "broker labels must be unique"),
        (lambda d: d.update(broker_requirements={"required_labels": ["A"], "minimum_distinct_brokers": True}), "minimum_distinct_brokers"),
        (lambda d: d.update(broker_requirements={"required_labels": ["A"], "minimum_distinct_brokers": 2}), "exceeds required broker labels"),
        (lambda d: d.update(modeled_cost_scenarios=[]), "modeled_cost_scenarios"),
        (lambda d: d.update(modeled_cost_scenarios=["bad"]), "modeled cost scenario must be an object"),
        (lambda d: d.update(modeled_cost_scenarios=[{"name": "", "cost_per_trade_currency": 1}]), "requires name"),
        (lambda d: d.update(modeled_cost_scenarios=[{"name": "x", "cost_per_trade_currency": -1}]), "cost_per_trade_currency must be >= 0"),
        (lambda d: d.update(modeled_cost_scenarios=[{"name": "x", "cost_per_trade_currency": 1}, {"name": "x", "cost_per_trade_currency": 2}]), "duplicate modeled cost scenario"),
        (lambda d: d.update(executed_metadata_stress=[{"fake": True}]), "forbids metadata-only"),
    ],
)
def test_robustness_template_fails_closed(mutator, message: str) -> None:
    if mutator(_robustness_template()) is None and message == "robustness template must be an object":
        with pytest.raises(RegistryValidationError, match=message):
            robustness_template_snapshot(None)
        return
    doc = _robustness_template()
    mutator(doc)
    with pytest.raises(RegistryValidationError, match=message):
        robustness_template_snapshot(doc)


def _environment() -> dict:
    return {
        "schema_version": 1,
        "environment_id": "DEMO-ENV-V1",
        "approved": True,
        "live_trading_authorized": False,
        "require_trade_mode": "DEMO",
        "broker_label": "Broker-A",
        "account_company": "Broker A Ltd",
        "account_server": "BrokerA-Demo",
        "symbol": "XAUUSD",
        "timeframe": "m15",
        "mt5_build": "5555",
        "modelling": "Every tick based on real ticks",
        "tester_model": 4,
        "expert": "GoldenTradeX\\GoldenTradeX.ex5",
        "execution_mode": 0,
        "portable_mode": True,
        "deposit": 10000,
        "currency": "usd",
        "leverage": 100,
        "spread_mode": "observed",
        "commission": None,
        "swap_mode": "observed",
        "slippage_points": 0,
        "optimization": False,
        "forward_mode": "disabled",
        "forward_mode_code": 0,
    }


def test_environment_normalization_loading_and_hash(tmp_path: Path) -> None:
    env = _environment()
    normalized = validate_execution_environment(env)
    assert normalized["timeframe"] == "M15"
    assert normalized["currency"] == "USD"
    assert normalized["deposit"] == 10000.0
    assert normalized["leverage"] == 100
    path = _write_json(tmp_path / "environment.json", env)
    loaded, file_sha = load_execution_environment_contract(path)
    assert loaded == normalized
    assert file_sha == sha256_file(path)
    assert canonical_environment_sha256(env) == canonical_environment_sha256(normalized)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("schema_version", 2, "schema_version"),
        ("environment_id", "", "environment_id is required"),
        ("approved", "yes", "approved must be true/false"),
        ("require_trade_mode", "REAL", "must require DEMO"),
        ("live_trading_authorized", True, "live_trading_authorized=false"),
        ("portable_mode", "true", "portable_mode must be true/false"),
        ("optimization", True, "optimization=false"),
        ("tester_model", True, "tester_model must be an integer"),
        ("tester_model", -1, "tester_model must be an integer"),
        ("tester_model", "04", "tester_model must be an integer"),
        ("execution_mode", -1, "execution_mode must be an integer"),
        ("forward_mode", "enabled", "disable MT5 forward mode"),
        ("forward_mode_code", 1, "disable MT5 forward mode"),
        ("deposit", 0, "deposit must be a finite number > 0"),
        ("deposit", float("inf"), "deposit must be a finite number > 0"),
        ("leverage", 100.5, "leverage must be an integer ratio"),
        ("slippage_points", -1, "slippage_points must be a finite number >= 0"),
        ("commission", True, "commission must be null"),
        ("commission", -0.1, "commission must be null"),
        ("broker_label", "TBD-BROKER", "placeholder values"),
        ("mt5_build", "UNKNOWN", "placeholder values"),
    ],
)
def test_environment_contract_fails_closed(field: str, value, message: str) -> None:
    env = _environment()
    env[field] = value
    with pytest.raises(RegistryValidationError, match=message):
        validate_execution_environment(env)


def _attestation(env: dict, file_sha: str) -> dict:
    return {
        "schema_version": 1,
        "methodology": "MT5_EXECUTION_ENVIRONMENT_ATTESTATION_V1",
        "status": "VERIFIED",
        "live_trading_authorized": False,
        "contract_file_sha256": file_sha,
        "environment_id": env["environment_id"],
        "observed": {
            "trade_mode": "DEMO",
            "account_company": env["account_company"],
            "account_server": env["account_server"],
            "symbol": env["symbol"],
            "mt5_build": env["mt5_build"],
            "terminal_connected": True,
            "symbol_synchronized": True,
        },
        "python_api_version": "5.test",
    }


def test_attestation_happy_path_and_loader(tmp_path: Path) -> None:
    env = _environment()
    contract = _write_json(tmp_path / "env.json", env)
    file_sha = sha256_file(contract)
    att = _attestation(env, file_sha)
    validated = validate_environment_attestation(att, env, file_sha)
    assert validated["status"] == "VERIFIED"
    assert validated["live_trading_authorized"] is False
    att_path = _write_json(tmp_path / "attestation.json", att)
    loaded, att_sha = load_and_validate_attestation(att_path, env, file_sha)
    assert loaded == validated
    assert att_sha == sha256_file(att_path)


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda a: a.update(schema_version=2), "schema_version"),
        (lambda a: a.update(methodology="WRONG"), "unsupported environment attestation methodology"),
        (lambda a: a.update(status="FAILED"), "not VERIFIED"),
        (lambda a: a.update(live_trading_authorized=True), "deny live trading"),
        (lambda a: a.update(contract_file_sha256="0" * 64), "contract SHA-256 mismatch"),
        (lambda a: a.update(environment_id="other"), "environment_id mismatch"),
        (lambda a: a.update(observed=None), "observed payload is missing"),
        (lambda a: a["observed"].update(trade_mode="REAL"), "trade_mode mismatch"),
        (lambda a: a["observed"].update(account_company="Other"), "account_company mismatch"),
        (lambda a: a["observed"].update(account_server="Other"), "account_server mismatch"),
        (lambda a: a["observed"].update(symbol="EURUSD"), "symbol mismatch"),
        (lambda a: a["observed"].update(mt5_build="9999"), "mt5_build mismatch"),
        (lambda a: a["observed"].update(terminal_connected=False), "terminal_connected=true"),
        (lambda a: a["observed"].update(symbol_synchronized=False), "symbol_synchronized=true"),
    ],
)
def test_attestation_fails_closed(mutator, message: str) -> None:
    env = _environment()
    file_sha = "a" * 64
    att = _attestation(env, file_sha)
    mutator(att)
    with pytest.raises(RegistryValidationError, match=message):
        validate_environment_attestation(att, env, file_sha)


@pytest.mark.parametrize(
    ("operator", "observed", "target", "expected"),
    [(">", 2, 1, True), (">=", 2, 2, True), ("<", 1, 2, True), ("<=", 2, 2, True), ("==", 2, 2, True)],
)
def test_forward_gate_comparator(operator, observed, target, expected) -> None:
    assert forward_compare(observed, operator, target) is expected


def test_forward_gate_comparator_rejects_unknown() -> None:
    with pytest.raises(RegistryValidationError, match="unsupported forward-demo operator"):
        forward_compare(1, "!=", 1)


def _forward_files(tmp_path: Path, *, approved=True, status="READY_FOR_FORWARD_DEMO_OBSERVATION", valid=True):
    policy = _write_json(
        tmp_path / "policy.json",
        {
            "policy_id": "FORWARD-V1",
            "approved": approved,
            "criteria": [
                {"metric": "expectancy_r", "operator": ">", "value": 0},
                {"metric": "max_dd_r", "operator": "<=", "value": 2},
            ],
        },
    )
    plan = _write_json(
        tmp_path / "plan.json",
        {
            "methodology": "FORWARD_DEMO_FIXED_WINDOW_V1",
            "status": status,
            "campaign_id": "campaign",
            "live_trading_authorized": False,
            "candidate": {"experiment_id": "exp"},
            "forward_policy": {"policy_id": "FORWARD-V1", "approved": approved, "sha256": sha256_file(policy)},
        },
    )
    evaluation = _write_json(
        tmp_path / "evaluation.json",
        {
            "methodology": "FORWARD_DEMO_EVIDENCE_V1",
            "status": "VALID_FORWARD_DEMO_EVIDENCE" if valid else "INVALID_FORWARD_DEMO_EVIDENCE",
            "valid": valid,
            "live_trading_authorized": False,
            "plan_sha256": sha256_file(plan),
            "summary": {"expectancy_r": 0.5, "max_dd_r": 1.0},
        },
    )
    return plan, evaluation, policy


def test_forward_gate_pass_block_and_invalid_evidence(tmp_path: Path) -> None:
    plan, evaluation, policy = _forward_files(tmp_path / "pass")
    passed = evaluate_forward_demo_gate(plan, evaluation, policy, tmp_path / "pass" / "gate.json")
    assert passed["passed"] is True
    assert passed["decision"] == "FORWARD_DEMO_PASS_FOR_RELEASE_REVIEW"

    plan, evaluation, policy = _forward_files(tmp_path / "unapproved", approved=False)
    blocked = evaluate_forward_demo_gate(plan, evaluation, policy)
    assert blocked["passed"] is False
    assert blocked["decision"] == "BLOCKED_POLICY_UNAPPROVED"

    plan, evaluation, policy = _forward_files(tmp_path / "invalid", valid=False)
    invalid = evaluate_forward_demo_gate(plan, evaluation, policy)
    assert invalid["passed"] is False
    assert "EVIDENCE_INVALID" in invalid["reasons"]


def test_forward_gate_nonfinite_and_nonnumeric_metrics_fail_criterion(tmp_path: Path) -> None:
    for value in (float("nan"), "bad"):
        case = tmp_path / str(value).replace("/", "_")
        plan, evaluation, policy = _forward_files(case)
        payload = json.loads(evaluation.read_text(encoding="utf-8"))
        payload["summary"]["expectancy_r"] = value
        _write_json(evaluation, payload)
        result = evaluate_forward_demo_gate(plan, evaluation, policy)
        assert result["passed"] is False
        assert "CRITERION_FAILED:expectancy_r" in result["reasons"]


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda p, e, pol: p.update(methodology="WRONG"), "unsupported forward-demo plan methodology"),
        (lambda p, e, pol: e.update(methodology="WRONG"), "unsupported forward-demo evidence methodology"),
        (lambda p, e, pol: p.update(live_trading_authorized=True), "deny live trading"),
        (lambda p, e, pol: e.update(plan_sha256="0" * 64), "does not hash"),
        (lambda p, e, pol: p.update(forward_policy=None), "policy snapshot missing"),
        (lambda p, e, pol: pol.update(policy_id="OTHER"), "policy changed after plan freeze"),
        (lambda p, e, pol: e.update(summary=None), "evaluation summary missing"),
        (lambda p, e, pol: pol.update(criteria=[]), "policy criteria missing"),
        (lambda p, e, pol: pol.update(criteria=["bad"]), "criterion must be an object"),
        (lambda p, e, pol: pol.update(criteria=[{"metric": "", "operator": ">", "value": 0}]), "criterion metric missing"),
        (lambda p, e, pol: pol.update(criteria=[{"metric": "missing", "operator": ">", "value": 0}]), "summary missing policy metric"),
        (lambda p, e, pol: pol.update(criteria=[{"metric": "expectancy_r", "operator": ">", "value": True}]), "target for expectancy_r must be numeric"),
    ],
)
def test_forward_gate_validation_fails_closed(tmp_path: Path, mutator, message: str) -> None:
    plan, evaluation, policy = _forward_files(tmp_path)
    p = json.loads(plan.read_text(encoding="utf-8"))
    e = json.loads(evaluation.read_text(encoding="utf-8"))
    pol = json.loads(policy.read_text(encoding="utf-8"))
    mutator(p, e, pol)
    _write_json(policy, pol)
    if isinstance(p.get("forward_policy"), dict) and pol.get("policy_id") == p["forward_policy"].get("policy_id"):
        p["forward_policy"]["sha256"] = sha256_file(policy)
    _write_json(plan, p)
    if e.get("plan_sha256") != "0" * 64:
        e["plan_sha256"] = sha256_file(plan)
    _write_json(evaluation, e)
    with pytest.raises(RegistryValidationError, match=message):
        evaluate_forward_demo_gate(plan, evaluation, policy)
