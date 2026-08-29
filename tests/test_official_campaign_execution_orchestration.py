import importlib.util
import json
from pathlib import Path

import pytest

from scripts import official_campaign_runner as runner
from scripts.experiment_registry import RegistryValidationError, identity_for, normalize_spec, sha256_file
from scripts.official_campaign_freeze import freeze_official_campaign


def _write_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _fixture_module():
    path = Path(__file__).with_name("test_official_campaign_runner.py")
    spec = importlib.util.spec_from_file_location("gtx_runner_fixture", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _prepared_inputs(tmp_path: Path):
    fixture = _fixture_module()
    config, _, environment_path, _ = fixture._campaign_inputs(tmp_path)
    freeze_dir = tmp_path / "freeze"
    lock = freeze_official_campaign(config, freeze_dir)
    attestation = fixture._attestation(tmp_path, environment_path)
    terminal = tmp_path / "terminal64.exe"
    terminal.write_bytes(b"stub")
    return lock, freeze_dir / "campaign_lock.json", attestation, terminal


def _fake_run_spec_factory(runs_dir: Path):
    def fake_run_spec(spec_path: Path, **kwargs):
        spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
        if Path(spec_path).name == "oos_spec.json":
            experiment_id = str(spec.get("expected_test_experiment_id", "oos-exp"))
        else:
            normalized, _ = normalize_spec(spec, base_dir=Path(spec_path).parent)
            experiment_id = identity_for(normalized).experiment_id
        normalized_path = runs_dir / experiment_id / "normalized_results.json"
        _write_json(
            normalized_path,
            {
                "schema_version": 1,
                "experiment_id": experiment_id,
                "summary": {
                    "total_trades": 50,
                    "total_net_profit": 100.0,
                    "profit_factor": 1.3,
                    "expected_payoff": 2.0,
                    "max_drawdown_pct": 6.0,
                },
            },
        )
        return {"experiment_id": experiment_id, "status": "COMPLETED"}, normalized_path
    return fake_run_spec


def _fake_selection(plan_path: Path, evidence_path: Path, selection_dir: Path):
    evidence = json.loads(Path(evidence_path).read_text(encoding="utf-8"))
    first = evidence["candidates"][0]
    selection_dir = Path(selection_dir)
    selection_dir.mkdir(parents=True, exist_ok=True)
    oos_id = f"oos-{evidence['fold_id']}"
    selection = {
        "schema_version": 1,
        "methodology": "IS_SELECTION_THEN_FROZEN_OOS",
        "fold_id": evidence["fold_id"],
        "selected": {"name": first["name"], "frozen_preset_sha256": "a" * 64},
        "oos": {"experiment_id": oos_id},
    }
    _write_json(selection_dir / "selection_manifest.json", selection)
    _write_json(
        selection_dir / "oos_spec.json",
        {
            "git_sha": "a" * 40,
            "preset_path": "unused.set",
            "expected_test_experiment_id": oos_id,
        },
    )
    return selection


def _patch_execution(monkeypatch, tmp_path: Path, lock: dict, *, promotable=True, bad_universe=False):
    runs_dir = tmp_path / "runs"
    monkeypatch.setattr(runner, "_run_spec", _fake_run_spec_factory(runs_dir))
    monkeypatch.setattr(runner, "select_and_freeze", _fake_selection)

    def fake_aggregate(plan_path, evidence_path, output_path):
        payload = {
            "methodology": "ROLLING_FROZEN_OOS_AGGREGATION",
            "candidate_universe_sha256": (
                "0" * 64 if bad_universe else lock["candidate_universe"]["sha256"]
            ),
            "summary": {"fold_count": 2, "total_net_profit": 200.0},
        }
        _write_json(Path(output_path), payload)
        return payload

    def fake_promotion(summary_path, policy_path, output_path):
        result = {
            "decision": (
                "PROMOTE_TO_FORWARD_DEMO_CANDIDATE" if promotable else "DO_NOT_PROMOTE"
            ),
            "promotable": promotable,
            "live_trading_authorized": False,
        }
        _write_json(Path(output_path), result)
        return result

    monkeypatch.setattr(runner, "aggregate_oos_evidence", fake_aggregate)
    monkeypatch.setattr(runner, "evaluate_promotion", fake_promotion)
    return runs_dir


def test_execute_official_campaign_reaches_positive_oos_promotion(monkeypatch, tmp_path: Path) -> None:
    lock, lock_path, attestation, terminal = _prepared_inputs(tmp_path)
    runs_dir = _patch_execution(monkeypatch, tmp_path, lock, promotable=True)
    output = tmp_path / "execution"

    result = runner.execute_official_campaign(
        lock_path,
        attestation,
        tmp_path,
        output,
        actual_git_sha="a" * 40,
        terminal=terminal,
        tester_profiles_dir=tmp_path / "tester_profiles",
        registry_db=tmp_path / "registry.sqlite",
        runs_dir=runs_dir,
        timeout_seconds=10,
    )

    assert result["status"] == "OOS_PROMOTION_PASS_READY_FOR_ROBUSTNESS"
    assert result["promotable_to_robustness"] is True
    assert result["live_trading_authorized"] is False
    assert result["real_capital_authorized"] is False
    assert len(result["folds"]) == 2
    assert all(row["status"] == "OOS_COMPLETED" for row in result["folds"])
    assert all(row["oos_experiment_id"].startswith("oos-") for row in result["folds"])
    assert (output / "oos_evidence_manifest.json").is_file()
    assert (output / "oos_summary.json").is_file()
    assert (output / "oos_promotion_decision.json").is_file()
    manifest = json.loads((output / "campaign_execution_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == result["status"]
    assert manifest["oos_summary_sha256"] == sha256_file(output / "oos_summary.json")


def test_execute_official_campaign_records_valid_rejection(monkeypatch, tmp_path: Path) -> None:
    lock, lock_path, attestation, terminal = _prepared_inputs(tmp_path)
    runs_dir = _patch_execution(monkeypatch, tmp_path, lock, promotable=False)
    result = runner.execute_official_campaign(
        lock_path,
        attestation,
        tmp_path,
        tmp_path / "execution",
        actual_git_sha="a" * 40,
        terminal=terminal,
        tester_profiles_dir=tmp_path / "profiles",
        registry_db=tmp_path / "registry.sqlite",
        runs_dir=runs_dir,
    )
    assert result["status"] == "OOS_PROMOTION_REJECTED"
    assert result["promotable_to_robustness"] is False


def test_execute_official_campaign_fails_before_execution_without_terminal(tmp_path: Path) -> None:
    _, lock_path, attestation, _ = _prepared_inputs(tmp_path)
    with pytest.raises(RegistryValidationError, match="MetaTrader terminal not found"):
        runner.execute_official_campaign(
            lock_path,
            attestation,
            tmp_path,
            tmp_path / "execution",
            actual_git_sha="a" * 40,
            terminal=tmp_path / "missing.exe",
            tester_profiles_dir=tmp_path / "profiles",
            registry_db=tmp_path / "registry.sqlite",
            runs_dir=tmp_path / "runs",
        )


def test_execute_official_campaign_persists_failed_stage(monkeypatch, tmp_path: Path) -> None:
    lock, lock_path, attestation, terminal = _prepared_inputs(tmp_path)
    runs_dir = _patch_execution(monkeypatch, tmp_path, lock, bad_universe=True)
    output = tmp_path / "execution"
    with pytest.raises(RegistryValidationError, match="candidate universe differs"):
        runner.execute_official_campaign(
            lock_path,
            attestation,
            tmp_path,
            output,
            actual_git_sha="a" * 40,
            terminal=terminal,
            tester_profiles_dir=tmp_path / "profiles",
            registry_db=tmp_path / "registry.sqlite",
            runs_dir=runs_dir,
        )
    manifest = json.loads((output / "campaign_execution_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "FAILED"
    assert "RegistryValidationError" in manifest["failure"]


def test_execute_official_campaign_detects_is_identity_drift(monkeypatch, tmp_path: Path) -> None:
    lock, lock_path, attestation, terminal = _prepared_inputs(tmp_path)
    monkeypatch.setattr(
        runner,
        "_run_spec",
        lambda spec_path, **kwargs: ({"experiment_id": "wrong", "status": "COMPLETED"}, tmp_path / "n.json"),
    )
    output = tmp_path / "execution"
    with pytest.raises(RegistryValidationError, match="experiment identity drift"):
        runner.execute_official_campaign(
            lock_path,
            attestation,
            tmp_path,
            output,
            actual_git_sha="a" * 40,
            terminal=terminal,
            tester_profiles_dir=tmp_path / "profiles",
            registry_db=tmp_path / "registry.sqlite",
            runs_dir=tmp_path / "runs",
        )
    manifest = json.loads((output / "campaign_execution_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "FAILED"


def test_runner_stage_preset_and_run_spec_fail_closed(monkeypatch, tmp_path: Path) -> None:
    spec = _write_json(tmp_path / "spec.json", {"preset_path": "", "expert_parameters": "x.set"})
    with pytest.raises(RegistryValidationError, match="preset_path missing"):
        runner._stage_preset(spec, tmp_path / "profiles")

    _write_json(spec, {"preset_path": "preset.set", "expert_parameters": "../x.set"})
    with pytest.raises(RegistryValidationError, match="must be a filename"):
        runner._stage_preset(spec, tmp_path / "profiles")

    preset = tmp_path / "preset.set"
    preset.write_text("x=1\n", encoding="utf-8")
    _write_json(spec, {"preset_path": preset.name, "expert_parameters": "staged.set"})
    runner._stage_preset(spec, tmp_path / "profiles")
    assert (tmp_path / "profiles" / "staged.set").read_text(encoding="utf-8") == "x=1\n"

    monkeypatch.setattr(runner, "_stage_preset", lambda *args, **kwargs: None)
    monkeypatch.setattr(runner, "run_registered_experiment", lambda *args, **kwargs: {"experiment_id": "e", "status": "PREPARED"})
    with pytest.raises(RegistryValidationError, match="did not complete"):
        runner._run_spec(
            spec,
            tester_profiles_dir=tmp_path / "profiles",
            terminal=tmp_path / "terminal",
            registry_db=tmp_path / "registry.sqlite",
            runs_dir=tmp_path / "runs",
            timeout_seconds=1,
        )

    monkeypatch.setattr(runner, "run_registered_experiment", lambda *args, **kwargs: {"experiment_id": "e", "status": "COMPLETED"})
    with pytest.raises(RegistryValidationError, match="normalized Strategy Tester evidence missing"):
        runner._run_spec(
            spec,
            tester_profiles_dir=tmp_path / "profiles",
            terminal=tmp_path / "terminal",
            registry_db=tmp_path / "registry.sqlite",
            runs_dir=tmp_path / "runs",
            timeout_seconds=1,
        )
