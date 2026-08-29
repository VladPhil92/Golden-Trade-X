import json
from pathlib import Path

import pytest

from scripts.experiment_registry import RegistryValidationError, identity_for, normalize_spec, sha256_file
from scripts.robustness_aggregate import aggregate_robustness
from scripts.robustness_gate import evaluate_robustness
from scripts.robustness_planner import generate_robustness_plan


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _policy(path: Path, *, approved: bool = True) -> Path:
    return _write_json(
        path,
        {
            "schema_version": 1,
            "policy_id": "TEST-ROBUSTNESS-V1",
            "approved": approved,
            "criteria": [
                {"metric": "baseline_total_net_profit", "operator": ">", "value": 0},
                {"metric": "parameter_positive_net_ratio", "operator": ">=", "value": 0.5},
                {"metric": "parameter_min_profit_factor", "operator": ">=", "value": 1.0},
                {"metric": "broker_count", "operator": ">=", "value": 2},
                {"metric": "broker_positive_net_ratio", "operator": ">=", "value": 0.5},
                {"metric": "modeled_cost_min_adjusted_net_profit", "operator": ">", "value": 0},
            ],
        },
    )


def _base_spec(root: Path, *, broker: str = "BROKER-A", preset_name: str = "base.set") -> Path:
    preset = root / preset_name
    preset.write_text(
        "InpEmaFast=21\nInpMinConfidence=55\nInpAtrSlMultiplier=2.0\n",
        encoding="utf-8",
    )
    return _write_json(
        root / f"{broker.replace('-', '_')}_spec.json",
        {
            "git_sha": "c" * 40,
            "preset_path": preset.name,
            "broker": broker,
            "symbol": "XAUUSD",
            "timeframe": "M15",
            "period_start": "2024-01-01T00:00:00Z",
            "period_end": "2024-12-31T23:59:59Z",
            "source_type": "strategy_tester",
            "mt5_build": f"build-{broker}",
            "modelling": "Every tick based on real ticks",
            "tester_model": 4,
            "expert": "GoldenTradeX\\GoldenTradeX.ex5",
            "expert_parameters": preset.name,
            "execution_mode": 0,
            "portable_mode": True,
            "deposit": 10000,
            "currency": "USD",
            "leverage": 100,
            "spread_mode": "observed",
            "commission": None,
            "swap_mode": "observed",
            "slippage_points": 0.0,
            "optimization": False,
            "forward_mode": "disabled",
            "forward_mode_code": 0,
            "parent_experiment_id": None,
            "changed_parameter": None,
            "changed_from": None,
            "changed_to": None,
        },
    )


def _result(path: Path, spec_path: Path, *, net: float, pf: float, payoff: float, dd: float, trades: int) -> Path:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    normalized, _ = normalize_spec(spec, base_dir=spec_path.parent)
    identity = identity_for(normalized)
    return _write_json(
        path,
        {
            "schema_version": 1,
            "parser_version": "test",
            "experiment_id": identity.experiment_id,
            "summary": {
                "total_net_profit": net,
                "profit_factor": pf,
                "expected_payoff": payoff,
                "max_drawdown_pct": dd,
                "total_trades": trades,
            },
            "metrics": {},
            "warnings": [],
        },
    )


def _config(root: Path, base_spec: Path, *, approved: bool = True) -> tuple[Path, Path]:
    policy = _policy(root / "policy.json", approved=approved)
    config = {
        "schema_version": 1,
        "campaign_id": "TEST-ROBUSTNESS",
        "base_spec_path": base_spec.name,
        "robustness_policy_path": policy.name,
        "parameter_scenarios": [
            {"name": "ema_minus", "parameter": "InpEmaFast", "value": 18},
            {"name": "ema_plus", "parameter": "InpEmaFast", "value": 24},
        ],
        "broker_requirements": {
            "required_labels": ["BROKER-A", "BROKER-B"],
            "minimum_distinct_brokers": 2,
        },
        "modeled_cost_scenarios": [
            {"name": "cost_low", "cost_per_trade_currency": 1.0},
            {"name": "cost_high", "cost_per_trade_currency": 2.0},
        ],
        "executed_metadata_stress": [],
    }
    return _write_json(root / "robustness_config.json", config), policy


def _broker_spec(root: Path, baseline_spec: Path, broker: str) -> Path:
    source = json.loads(baseline_spec.read_text(encoding="utf-8"))
    baseline_preset = baseline_spec.parent / source["preset_path"]
    target_preset = root / f"{broker}.set"
    target_preset.write_bytes(baseline_preset.read_bytes())
    source["preset_path"] = target_preset.name
    source["expert_parameters"] = target_preset.name
    source["broker"] = broker
    source["mt5_build"] = f"build-{broker}"
    return _write_json(root / f"{broker}.json", source)


def _complete_evidence(root: Path, plan_path: Path, baseline_spec: Path) -> tuple[Path, Path]:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    baseline_result = _result(
        root / "baseline_results.json",
        baseline_spec,
        net=200.0,
        pf=1.4,
        payoff=2.0,
        dd=6.0,
        trades=100,
    )

    parameter_entries = []
    for index, scenario in enumerate(plan["domains"]["parameter_stability"]["scenarios"]):
        spec_path = plan_path.parent / scenario["spec"]
        result_path = _result(
            root / f"{scenario['name']}_results.json",
            spec_path,
            net=150.0 - index * 10,
            pf=1.25 - index * 0.05,
            payoff=1.5 - index * 0.1,
            dd=7.0 + index,
            trades=100,
        )
        parameter_entries.append(
            {
                "name": scenario["name"],
                "normalized_results": result_path.name,
            }
        )

    broker_entries = []
    for broker, net, pf in (("BROKER-A", 200.0, 1.4), ("BROKER-B", 120.0, 1.15)):
        broker_spec = _broker_spec(root, baseline_spec, broker)
        result_path = _result(
            root / f"{broker}_results.json",
            broker_spec,
            net=net,
            pf=pf,
            payoff=net / 100,
            dd=8.0,
            trades=100,
        )
        broker_entries.append(
            {
                "broker": broker,
                "spec": broker_spec.name,
                "normalized_results": result_path.name,
            }
        )

    evidence = _write_json(
        root / "evidence.json",
        {
            "baseline": {
                "spec": baseline_spec.name,
                "normalized_results": baseline_result.name,
            },
            "parameter_scenarios": parameter_entries,
            "broker_runs": broker_entries,
        },
    )
    return evidence, baseline_result


def test_planner_creates_one_change_executable_scenarios_and_freezes_policy(tmp_path: Path) -> None:
    base_spec = _base_spec(tmp_path)
    config, policy = _config(tmp_path, base_spec)
    output_dir = tmp_path / "plan"
    plan = generate_robustness_plan(config, output_dir)

    assert plan["status"] == "READY_FOR_REGISTERED_EXECUTION"
    assert plan["robustness_policy"]["sha256"] == sha256_file(policy)
    scenarios = plan["domains"]["parameter_stability"]["scenarios"]
    assert len(scenarios) == 2
    assert all(item["evidence_class"] == "EXECUTED_COUNTERFACTUAL" for item in scenarios)
    assert all(item["binding"] == "preset_parameter" for item in scenarios)
    assert plan["domains"]["cost_sensitivity"]["evidence_class"] == "MODELED_COST_SENSITIVITY"

    original = (tmp_path / "base.set").read_text(encoding="utf-8").splitlines()
    variant = (output_dir / scenarios[0]["preset"]).read_text(encoding="utf-8").splitlines()
    assert sum(a != b for a, b in zip(original, variant)) == 1


def test_planner_rejects_metadata_only_slippage_as_executed_stress(tmp_path: Path) -> None:
    base_spec = _base_spec(tmp_path)
    config, _ = _config(tmp_path, base_spec)
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["executed_metadata_stress"] = [{"field": "slippage_points", "value": 5}]
    _write_json(config, payload)

    with pytest.raises(RegistryValidationError, match="cannot be claimed as executed"):
        generate_robustness_plan(config, tmp_path / "plan")


def test_aggregate_requires_all_planned_parameter_and_broker_evidence(tmp_path: Path) -> None:
    base_spec = _base_spec(tmp_path)
    config, _ = _config(tmp_path, base_spec)
    plan_dir = tmp_path / "plan"
    generate_robustness_plan(config, plan_dir)
    plan_path = plan_dir / "robustness_plan.json"
    evidence, _ = _complete_evidence(tmp_path, plan_path, base_spec)

    payload = json.loads(evidence.read_text(encoding="utf-8"))
    payload["parameter_scenarios"].pop()
    _write_json(evidence, payload)
    with pytest.raises(RegistryValidationError, match="every planned scenario"):
        aggregate_robustness(plan_path, evidence, tmp_path / "summary.json")


def test_broker_replication_rejects_strategy_drift(tmp_path: Path) -> None:
    base_spec = _base_spec(tmp_path)
    config, _ = _config(tmp_path, base_spec)
    plan_dir = tmp_path / "plan"
    generate_robustness_plan(config, plan_dir)
    plan_path = plan_dir / "robustness_plan.json"
    evidence, _ = _complete_evidence(tmp_path, plan_path, base_spec)

    payload = json.loads(evidence.read_text(encoding="utf-8"))
    broker_b = next(item for item in payload["broker_runs"] if item["broker"] == "BROKER-B")
    broker_spec_path = tmp_path / broker_b["spec"]
    spec = json.loads(broker_spec_path.read_text(encoding="utf-8"))
    preset_path = broker_spec_path.parent / spec["preset_path"]
    preset_path.write_text("InpEmaFast=99\nInpMinConfidence=55\nInpAtrSlMultiplier=2.0\n", encoding="utf-8")
    _write_json(broker_spec_path, spec)
    broker_b["normalized_results"] = _result(
        tmp_path / "BROKER-B_drift_results.json",
        broker_spec_path,
        net=120,
        pf=1.15,
        payoff=1.2,
        dd=8,
        trades=100,
    ).name
    _write_json(evidence, payload)

    with pytest.raises(RegistryValidationError, match="strategy/test geometry differs"):
        aggregate_robustness(plan_path, evidence, tmp_path / "summary.json")


def test_aggregate_preserves_modeled_cost_class_and_gate_never_authorizes_live(tmp_path: Path) -> None:
    base_spec = _base_spec(tmp_path)
    config, policy = _config(tmp_path, base_spec)
    plan_dir = tmp_path / "plan"
    generate_robustness_plan(config, plan_dir)
    plan_path = plan_dir / "robustness_plan.json"
    evidence, _ = _complete_evidence(tmp_path, plan_path, base_spec)
    summary_path = tmp_path / "summary.json"
    summary = aggregate_robustness(plan_path, evidence, summary_path)

    assert summary["evidence_classes"]["cost_sensitivity"] == "MODELED_COST_SENSITIVITY"
    assert all(item["executed_in_mt5"] is False for item in summary["modeled_cost_scenarios"])
    assert summary["summary"]["modeled_cost_min_adjusted_net_profit"] == 0.0

    # Policy requires > 0 for worst modeled cost, therefore this evidence must not pass.
    decision = evaluate_robustness(summary_path, policy)
    assert decision["decision"] == "ROBUSTNESS_FAIL"
    assert decision["robust"] is False
    assert decision["live_trading_authorized"] is False


def test_robustness_gate_passes_only_approved_frozen_policy(tmp_path: Path) -> None:
    base_spec = _base_spec(tmp_path)
    config, policy = _config(tmp_path, base_spec)
    policy_payload = json.loads(policy.read_text(encoding="utf-8"))
    policy_payload["criteria"][-1]["value"] = -1
    _write_json(policy, policy_payload)
    # Regenerate plan after the deliberate policy change so the hash is frozen pre-evidence.
    plan_dir = tmp_path / "plan"
    generate_robustness_plan(config, plan_dir)
    plan_path = plan_dir / "robustness_plan.json"
    evidence, _ = _complete_evidence(tmp_path, plan_path, base_spec)
    summary_path = tmp_path / "summary.json"
    aggregate_robustness(plan_path, evidence, summary_path)

    decision = evaluate_robustness(summary_path, policy)
    assert decision["decision"] == "ROBUSTNESS_PASS_FOR_FORWARD_DEMO_REVIEW"
    assert decision["robust"] is True
    assert decision["live_trading_authorized"] is False

    mutated = json.loads(policy.read_text(encoding="utf-8"))
    mutated["criteria"][0]["value"] = -999
    _write_json(policy, mutated)
    with pytest.raises(RegistryValidationError, match="hash differs"):
        evaluate_robustness(summary_path, policy)


def test_unapproved_robustness_policy_cannot_pass_gate(tmp_path: Path) -> None:
    base_spec = _base_spec(tmp_path)
    config, policy = _config(tmp_path, base_spec, approved=False)
    plan_dir = tmp_path / "plan"
    plan = generate_robustness_plan(config, plan_dir)
    assert plan["status"] == "DRAFT_POLICY_UNAPPROVED"
    plan_path = plan_dir / "robustness_plan.json"
    evidence, _ = _complete_evidence(tmp_path, plan_path, base_spec)
    summary_path = tmp_path / "summary.json"
    aggregate_robustness(plan_path, evidence, summary_path)
    decision = evaluate_robustness(summary_path, policy)
    assert decision["decision"] == "BLOCKED_POLICY_UNAPPROVED"
    assert decision["robust"] is False
