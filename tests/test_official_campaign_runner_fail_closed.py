"""Adversarial coverage for official campaign runner fail-closed paths."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.campaign_contract import candidate_universe_sha256
from scripts.experiment_registry import RegistryValidationError, sha256_file
from scripts import official_campaign_runner as runner


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _environment() -> dict:
    return {
        "schema_version": 1,
        "environment_id": "TEST-XAUUSD-DEMO-ENV",
        "approved": True,
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


def _valid_lock() -> dict:
    return {
        "methodology": runner.SUPPORTED_LOCK_METHOD,
        "status": "OFFICIAL_CAMPAIGN_FROZEN",
        "live_trading_authorized": False,
        "build_id": "a" * 40,
        "execution_environment": {"contract": _environment()},
        "walk_forward": {},
    }


def test_load_json_and_resolve_within_fail_closed(tmp_path: Path) -> None:
    bad_root = _write_json(tmp_path / "bad.json", [])
    with pytest.raises(RegistryValidationError, match="root must be an object"):
        runner._load_json(bad_root)

    root = tmp_path / "config"
    root.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("{}\n", encoding="utf-8")
    with pytest.raises(RegistryValidationError, match="escapes frozen config root"):
        runner._resolve_within(root, "../outside.json", "test.path")
    with pytest.raises(RegistryValidationError, match="is required"):
        runner._resolve_within(root, "", "test.path")
    with pytest.raises(RegistryValidationError, match="not found"):
        runner._resolve_within(root, "missing.json", "test.path")


def test_campaign_lock_validation_rejects_each_identity_boundary() -> None:
    cases = [
        ("methodology", "WRONG", "unsupported official campaign lock methodology"),
        ("status", "DRAFT", "requires OFFICIAL_CAMPAIGN_FROZEN"),
        ("live_trading_authorized", True, "deny live trading"),
        ("build_id", "ABC", "full lowercase Git SHA"),
    ]
    for field, value, message in cases:
        lock = _valid_lock()
        lock[field] = value
        with pytest.raises(RegistryValidationError, match=message):
            runner._validate_lock(lock)

    lock = _valid_lock()
    lock["execution_environment"] = None
    with pytest.raises(RegistryValidationError, match="lacks frozen execution_environment"):
        runner._validate_lock(lock)

    lock = _valid_lock()
    lock["execution_environment"] = {"contract": None}
    with pytest.raises(RegistryValidationError, match="lacks execution environment contract"):
        runner._validate_lock(lock)

    lock = _valid_lock()
    lock["walk_forward"] = None
    with pytest.raises(RegistryValidationError, match="lacks walk_forward contract"):
        runner._validate_lock(lock)


def test_candidate_source_verification_rejects_fingerprint_bytes_and_real_guard(tmp_path: Path) -> None:
    preset = tmp_path / "baseline.set"
    preset.write_text("InpAllowRealTrading=false\n", encoding="utf-8")
    candidates = [
        {
            "name": "baseline",
            "preset_path": preset.name,
            "preset_sha256": sha256_file(preset),
        }
    ]
    lock = {
        "candidate_universe": {
            "candidates": candidates,
            "sha256": candidate_universe_sha256(candidates),
        }
    }
    verified = runner._verify_candidate_sources(lock, tmp_path)
    assert verified[0]["source_path"] == preset.resolve()

    tampered_lock = json.loads(json.dumps(lock))
    tampered_lock["candidate_universe"]["sha256"] = "0" * 64
    with pytest.raises(RegistryValidationError, match="fingerprint is invalid"):
        runner._verify_candidate_sources(tampered_lock, tmp_path)

    preset.write_text("InpAllowRealTrading=true\n", encoding="utf-8")
    with pytest.raises(RegistryValidationError, match="preset changed after campaign freeze"):
        runner._verify_candidate_sources(lock, tmp_path)

    candidates[0]["preset_sha256"] = sha256_file(preset)
    lock["candidate_universe"]["sha256"] = candidate_universe_sha256(candidates)
    with pytest.raises(RegistryValidationError, match="must retain exactly one InpAllowRealTrading=false"):
        runner._verify_candidate_sources(lock, tmp_path)


def test_stage_preset_validates_filename_and_source(tmp_path: Path) -> None:
    spec = _write_json(tmp_path / "spec.json", {"preset_path": "preset.set"})
    with pytest.raises(RegistryValidationError, match="expert_parameters missing"):
        runner._stage_preset(spec, tmp_path / "profiles")

    _write_json(
        spec,
        {"preset_path": "preset.set", "expert_parameters": "../preset.set"},
    )
    with pytest.raises(RegistryValidationError, match="must be a filename"):
        runner._stage_preset(spec, tmp_path / "profiles")

    _write_json(
        spec,
        {"preset_path": "missing.set", "expert_parameters": "missing.set"},
    )
    with pytest.raises(RegistryValidationError, match="not found"):
        runner._stage_preset(spec, tmp_path / "profiles")

    (tmp_path / "preset.set").write_text("InpAllowRealTrading=false\n", encoding="utf-8")
    _write_json(spec, {"preset_path": "preset.set", "expert_parameters": "preset.set"})
    profiles = tmp_path / "profiles"
    runner._stage_preset(spec, profiles)
    assert (profiles / "preset.set").read_text(encoding="utf-8") == "InpAllowRealTrading=false\n"


def test_run_spec_requires_completed_record_and_normalized_artifact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    preset = tmp_path / "preset.set"
    preset.write_text("InpAllowRealTrading=false\n", encoding="utf-8")
    spec = _write_json(
        tmp_path / "spec.json",
        {"preset_path": "preset.set", "expert_parameters": "preset.set"},
    )
    terminal = tmp_path / "terminal64.exe"
    terminal.write_bytes(b"test")
    profiles = tmp_path / "profiles"
    runs = tmp_path / "runs"
    registry = tmp_path / "experiments.sqlite"

    monkeypatch.setattr(
        runner,
        "run_registered_experiment",
        lambda *args, **kwargs: {"status": "FAILED", "experiment_id": "gtx-failed"},
    )
    with pytest.raises(RegistryValidationError, match="did not complete"):
        runner._run_spec(
            spec,
            tester_profiles_dir=profiles,
            terminal=terminal,
            registry_db=registry,
            runs_dir=runs,
            timeout_seconds=60,
        )

    monkeypatch.setattr(
        runner,
        "run_registered_experiment",
        lambda *args, **kwargs: {"status": "COMPLETED", "experiment_id": "gtx-complete"},
    )
    with pytest.raises(RegistryValidationError, match="normalized Strategy Tester evidence missing"):
        runner._run_spec(
            spec,
            tester_profiles_dir=profiles,
            terminal=terminal,
            registry_db=registry,
            runs_dir=runs,
            timeout_seconds=60,
        )

    normalized = runs / "gtx-complete" / "normalized_results.json"
    normalized.parent.mkdir(parents=True)
    normalized.write_text("{}\n", encoding="utf-8")
    record, actual = runner._run_spec(
        spec,
        tester_profiles_dir=profiles,
        terminal=terminal,
        registry_db=registry,
        runs_dir=runs,
        timeout_seconds=60,
    )
    assert record["status"] == "COMPLETED"
    assert actual == normalized
