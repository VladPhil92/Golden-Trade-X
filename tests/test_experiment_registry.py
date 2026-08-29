import json
from pathlib import Path

import pytest

from scripts.experiment_registry import (
    RegistryValidationError,
    attach_artifact,
    connect_registry,
    register_experiment,
)


def _spec(preset_name: str = "preset.set") -> dict:
    return {
        "git_sha": "a" * 40,
        "preset_path": preset_name,
        "broker": "Test Broker",
        "symbol": "XAUUSD",
        "timeframe": "M15",
        "period_start": "2024-01-01T00:00:00Z",
        "period_end": "2024-12-31T23:59:59Z",
        "source_type": "strategy_tester",
        "mt5_build": "6000",
        "modelling": "Every tick based on real ticks",
        "deposit": 10000,
        "currency": "USD",
        "leverage": 100,
    }


def test_registration_is_idempotent_for_same_provenance(tmp_path: Path) -> None:
    preset = tmp_path / "preset.set"
    preset.write_text("InpRiskPercent=1.0\n", encoding="utf-8")
    connection = connect_registry(tmp_path / "registry.sqlite")
    try:
        first = register_experiment(connection, _spec(), base_dir=tmp_path)
        second = register_experiment(connection, _spec(), base_dir=tmp_path)
        assert first["experiment_id"] == second["experiment_id"]
        assert first["fingerprint"] == second["fingerprint"]
        count = connection.execute("SELECT COUNT(*) FROM experiments").fetchone()[0]
        assert count == 1
    finally:
        connection.close()


def test_preset_content_change_changes_experiment_identity(tmp_path: Path) -> None:
    preset = tmp_path / "preset.set"
    preset.write_text("InpRiskPercent=1.0\n", encoding="utf-8")
    connection = connect_registry(tmp_path / "registry.sqlite")
    try:
        first = register_experiment(connection, _spec(), base_dir=tmp_path)
        preset.write_text("InpRiskPercent=0.5\n", encoding="utf-8")
        second = register_experiment(connection, _spec(), base_dir=tmp_path)
        assert first["experiment_id"] != second["experiment_id"]
        assert first["spec"]["preset_sha256"] != second["spec"]["preset_sha256"]
    finally:
        connection.close()


def test_invalid_or_missing_provenance_fails_closed(tmp_path: Path) -> None:
    preset = tmp_path / "preset.set"
    preset.write_text("x=1\n", encoding="utf-8")
    spec = _spec()
    spec["git_sha"] = "short"
    connection = connect_registry(tmp_path / "registry.sqlite")
    try:
        with pytest.raises(RegistryValidationError, match="git_sha"):
            register_experiment(connection, spec, base_dir=tmp_path)
    finally:
        connection.close()


def test_ablation_requires_complete_one_change_metadata(tmp_path: Path) -> None:
    preset = tmp_path / "preset.set"
    preset.write_text("x=1\n", encoding="utf-8")
    spec = _spec()
    spec["changed_parameter"] = "InpUseSmcFilter"
    spec["changed_from"] = True
    connection = connect_registry(tmp_path / "registry.sqlite")
    try:
        with pytest.raises(RegistryValidationError, match="changed_from and changed_to"):
            register_experiment(connection, spec, base_dir=tmp_path)
    finally:
        connection.close()


def test_artifacts_are_hashed_and_attached(tmp_path: Path) -> None:
    preset = tmp_path / "preset.set"
    preset.write_text("x=1\n", encoding="utf-8")
    artifact = tmp_path / "report.json"
    artifact.write_text(json.dumps({"profit_factor": 1.3}), encoding="utf-8")
    connection = connect_registry(tmp_path / "registry.sqlite")
    try:
        record = register_experiment(connection, _spec(), base_dir=tmp_path)
        updated = attach_artifact(connection, record["experiment_id"], "report", artifact)
        assert updated["artifacts"]["report"]["size"] == artifact.stat().st_size
        assert len(updated["artifacts"]["report"]["sha256"]) == 64
    finally:
        connection.close()
