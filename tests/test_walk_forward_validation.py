import json
from pathlib import Path

import pytest

from scripts.experiment_registry import (
    RegistryValidationError,
    identity_for,
    normalize_spec,
    sha256_file,
)
from scripts.promotion_gate import evaluate_promotion
from scripts.walk_forward_aggregate import aggregate_oos_evidence
from scripts.walk_forward_planner import generate_walk_forward_plan
from scripts.walk_forward_selector import select_and_freeze


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _promotion_policy(path: Path, *, approved: bool = True) -> Path:
    return _write_json(
        path,
        {
            "schema_version": 1,
            "policy_id": "TEST-PROMOTION-V1",
            "approved": approved,
            "criteria": [
                {"metric": "fold_count", "operator": ">=", "value": 2},
                {"metric": "total_net_profit", "operator": ">", "value": 0},
                {"metric": "median_profit_factor", "operator": ">=", "value": 1.1},
                {"metric": "max_drawdown_pct", "operator": "<=", "value": 10.0},
            ],
        },
    )


def _plan_config(path: Path, *, approved: bool = True, minimum_folds: int = 2) -> tuple[Path, Path]:
    policy = _promotion_policy(path.parent / "promotion.json", approved=approved)
    config = {
        "schema_version": 1,
        "plan_id": "TEST-WF",
        "start_date": "2022-01-01",
        "end_date": "2023-01-01",
        "in_sample_months": 6,
        "oos_months": 3,
        "step_months": 3,
        "embargo_days": 0,
        "minimum_folds": minimum_folds,
        "selection_policy": {
            "policy_id": "TEST-IS-SELECT",
            "objective": {"metric": "profit_factor", "direction": "maximize"},
            "constraints": [
                {"metric": "total_trades", "operator": ">=", "value": 20},
                {"metric": "max_drawdown_pct", "operator": "<=", "value": 15},
            ],
            "tie_breakers": [
                {"metric": "expected_payoff", "direction": "maximize"},
                {"metric": "total_net_profit", "direction": "maximize"},
            ],
        },
        "promotion_policy_path": policy.name,
    }
    return _write_json(path, config), policy


def _spec(preset_name: str, period_start: str, period_end: str) -> dict:
    return {
        "git_sha": "a" * 40,
        "preset_path": preset_name,
        "broker": "TEST-BROKER",
        "symbol": "XAUUSD",
        "timeframe": "M15",
        "period_start": period_start,
        "period_end": period_end,
        "source_type": "strategy_tester",
        "mt5_build": "test-build",
        "modelling": "Every tick based on real ticks",
        "tester_model": 4,
        "expert": "GoldenTradeX\\GoldenTradeX.ex5",
        "expert_parameters": preset_name,
        "execution_mode": 0,
        "portable_mode": True,
        "deposit": 10000,
        "currency": "USD",
        "leverage": 100,
        "spread_mode": "current",
        "commission": None,
        "swap_mode": None,
        "slippage_points": 0,
        "optimization": False,
        "forward_mode": "disabled",
        "forward_mode_code": 0,
    }


def _normalized_result(path: Path, spec_path: Path, summary: dict) -> Path:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    normalized, _ = normalize_spec(spec, base_dir=spec_path.parent)
    identity = identity_for(normalized)
    payload = {
        "schema_version": 1,
        "parser_version": "test",
        "experiment_id": identity.experiment_id,
        "source_report": {"sha256": "f" * 64},
        "summary": summary,
        "metrics": {},
        "warnings": [],
    }
    return _write_json(path, payload)


def _candidate_evidence(
    root: Path,
    fold: dict,
    *,
    pf_a: float = 1.2,
    pf_b: float = 1.4,
) -> Path:
    candidates = []
    for name, pf, payoff, net, dd in (
        ("candidate_a", pf_a, 1.1, 100.0, 8.0),
        ("candidate_b", pf_b, 1.3, 140.0, 7.0),
    ):
        candidate_dir = root / name
        candidate_dir.mkdir(parents=True, exist_ok=True)
        preset = candidate_dir / f"{name}.set"
        preset.write_text(f"InpCandidate={1 if name.endswith('a') else 2}\n", encoding="utf-8")
        spec = _spec(
            preset.name,
            fold["in_sample"]["period_start"],
            fold["in_sample"]["period_end"],
        )
        spec_path = _write_json(candidate_dir / "spec.json", spec)
        result_path = _normalized_result(
            candidate_dir / "normalized_results.json",
            spec_path,
            {
                "total_net_profit": net,
                "profit_factor": pf,
                "expected_payoff": payoff,
                "max_drawdown_pct": dd,
                "total_trades": 40,
            },
        )
        candidates.append(
            {
                "name": name,
                "spec": str(spec_path.relative_to(root)),
                "normalized_results": str(result_path.relative_to(root)),
            }
        )
    return _write_json(root / "is_evidence.json", {"fold_id": fold["fold_id"], "candidates": candidates})


def test_planner_generates_non_overlapping_oos_and_locks_policy_hash(tmp_path: Path) -> None:
    config, policy = _plan_config(tmp_path / "plan.json")
    output = tmp_path / "manifest.json"
    manifest = generate_walk_forward_plan(config, output)

    assert manifest["status"] == "READY_FOR_REGISTERED_EXECUTION"
    assert manifest["promotion_policy"]["sha256"] == sha256_file(policy)
    assert len(manifest["folds"]) == 2
    first, second = manifest["folds"]
    assert first["out_of_sample"]["end_date_exclusive"] == second["out_of_sample"]["start_date"]
    assert first["in_sample"]["period_end"] < first["out_of_sample"]["period_start"]


def test_planner_rejects_overlapping_official_oos_windows(tmp_path: Path) -> None:
    config, _ = _plan_config(tmp_path / "plan.json")
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["step_months"] = 1
    _write_json(config, payload)
    with pytest.raises(RegistryValidationError, match="never overlap"):
        generate_walk_forward_plan(config, tmp_path / "manifest.json")


def test_unapproved_policy_produces_draft_plan_and_blocks_official_freeze(tmp_path: Path) -> None:
    config, _ = _plan_config(tmp_path / "plan.json", approved=False)
    plan_path = tmp_path / "manifest.json"
    plan = generate_walk_forward_plan(config, plan_path)
    assert plan["status"] == "DRAFT_POLICY_UNAPPROVED"

    evidence = _candidate_evidence(tmp_path / "wf1", plan["folds"][0])
    with pytest.raises(RegistryValidationError, match="approved promotion policy"):
        select_and_freeze(plan_path, evidence, tmp_path / "frozen")


def test_selector_chooses_predeclared_is_winner_and_freezes_exact_preset(tmp_path: Path) -> None:
    config, _ = _plan_config(tmp_path / "plan.json")
    plan_path = tmp_path / "manifest.json"
    plan = generate_walk_forward_plan(config, plan_path)
    fold = plan["folds"][0]
    evidence = _candidate_evidence(tmp_path / "wf1", fold)

    selection = select_and_freeze(plan_path, evidence, tmp_path / "frozen")

    assert selection["evidence_status"] == "OFFICIAL_FROZEN_OOS"
    assert selection["selected"]["name"] == "candidate_b"
    assert selection["eligible_candidate_count"] == 2
    frozen = tmp_path / "frozen" / "frozen_preset.set"
    assert sha256_file(frozen) == selection["selected"]["frozen_preset_sha256"]

    oos_spec = json.loads((tmp_path / "frozen" / "oos_spec.json").read_text(encoding="utf-8"))
    assert oos_spec["period_start"] == fold["out_of_sample"]["period_start"]
    assert oos_spec["period_end"] == fold["out_of_sample"]["period_end"]
    assert oos_spec["parent_experiment_id"] == selection["selected"]["is_experiment_id"]


def test_selector_uses_candidate_name_as_final_deterministic_tie_breaker(tmp_path: Path) -> None:
    config, _ = _plan_config(tmp_path / "plan.json")
    plan_path = tmp_path / "manifest.json"
    plan = generate_walk_forward_plan(config, plan_path)
    evidence = _candidate_evidence(tmp_path / "wf1", plan["folds"][0], pf_a=1.4, pf_b=1.4)

    payload = json.loads(evidence.read_text(encoding="utf-8"))
    for candidate in payload["candidates"]:
        result_path = evidence.parent / candidate["normalized_results"]
        result = json.loads(result_path.read_text(encoding="utf-8"))
        result["summary"]["expected_payoff"] = 1.3
        result["summary"]["total_net_profit"] = 140.0
        _write_json(result_path, result)

    selection = select_and_freeze(plan_path, evidence, tmp_path / "frozen")
    assert selection["selected"]["name"] == "candidate_a"


def test_aggregate_and_promotion_gate_validate_complete_frozen_oos_chain(tmp_path: Path) -> None:
    config, policy = _plan_config(tmp_path / "plan.json")
    plan_path = tmp_path / "manifest.json"
    plan = generate_walk_forward_plan(config, plan_path)

    evidence_entries = []
    for index, fold in enumerate(plan["folds"], start=1):
        fold_root = tmp_path / f"fold_{index}"
        evidence = _candidate_evidence(fold_root / "is", fold)
        frozen_dir = fold_root / "frozen"
        selection = select_and_freeze(plan_path, evidence, frozen_dir)

        oos_spec_path = frozen_dir / "oos_spec.json"
        net = 120.0 if index == 1 else 80.0
        pf = 1.35 if index == 1 else 1.2
        dd = 7.0 if index == 1 else 9.0
        result_path = _normalized_result(
            fold_root / "oos_results.json",
            oos_spec_path,
            {
                "total_net_profit": net,
                "profit_factor": pf,
                "expected_payoff": net / 50,
                "max_drawdown_pct": dd,
                "total_trades": 50,
                "win_rate": 55.0,
                "recovery_factor": 1.5,
                "sharpe_ratio": 0.8,
            },
        )
        assert selection["oos"]["experiment_id"] == json.loads(
            result_path.read_text(encoding="utf-8")
        )["experiment_id"]
        evidence_entries.append(
            {
                "fold_id": fold["fold_id"],
                "selection_manifest": str((frozen_dir / "selection_manifest.json").relative_to(tmp_path)),
                "oos_spec": str(oos_spec_path.relative_to(tmp_path)),
                "normalized_results": str(result_path.relative_to(tmp_path)),
            }
        )

    oos_manifest = _write_json(tmp_path / "oos_evidence.json", {"folds": evidence_entries})
    summary_path = tmp_path / "oos_summary.json"
    aggregate = aggregate_oos_evidence(plan_path, oos_manifest, summary_path)

    assert aggregate["summary"]["fold_count"] == 2
    assert aggregate["summary"]["total_trades"] == 100
    assert aggregate["summary"]["total_net_profit"] == 200.0
    assert aggregate["summary"]["profitable_fold_ratio"] == 1.0
    assert aggregate["summary"]["max_drawdown_pct"] == 9.0

    decision = evaluate_promotion(summary_path, policy, tmp_path / "decision.json")
    assert decision["decision"] == "PROMOTE_TO_FORWARD_DEMO_CANDIDATE"
    assert decision["promotable"] is True
    assert decision["live_trading_authorized"] is False


def test_promotion_gate_rejects_policy_changed_after_oos(tmp_path: Path) -> None:
    config, policy = _plan_config(tmp_path / "plan.json")
    plan_path = tmp_path / "manifest.json"
    plan = generate_walk_forward_plan(config, plan_path)
    summary_path = _write_json(
        tmp_path / "summary.json",
        {
            "methodology": "ROLLING_FROZEN_OOS_AGGREGATION",
            "promotion_policy_sha256": plan["promotion_policy"]["sha256"],
            "summary": {
                "fold_count": 2,
                "total_net_profit": 100,
                "median_profit_factor": 1.2,
                "max_drawdown_pct": 5,
            },
        },
    )

    changed = json.loads(policy.read_text(encoding="utf-8"))
    changed["criteria"][1]["value"] = -999
    _write_json(policy, changed)

    with pytest.raises(RegistryValidationError, match="hash differs"):
        evaluate_promotion(summary_path, policy)
