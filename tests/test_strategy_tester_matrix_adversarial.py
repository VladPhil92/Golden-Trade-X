import json
from pathlib import Path

import pytest

from scripts import strategy_tester_matrix as matrix
from scripts.experiment_registry import RegistryValidationError


def _write_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _matrix_dir(tmp_path: Path) -> Path:
    root = tmp_path / "matrix"
    _write_json(root / "base.json", {"name": "base"})
    _write_json(root / "variant.json", {"name": "variant"})
    _write_json(root / "matrix_manifest.json", {
        "methodology": "ONE_CHANGE_AT_A_TIME",
        "baseline": {"spec": "base.json", "experiment_id": "base-id"},
        "variants": [{"name": "no-x", "spec": "variant.json", "experiment_id": "variant-id"}],
    })
    return root


def test_manifest_validation_and_entry_path_guards(tmp_path: Path) -> None:
    root = tmp_path / "missing"
    root.mkdir()
    with pytest.raises(RegistryValidationError, match="manifest not found"):
        matrix._load_manifest(root)

    cases = [
        ({"methodology": "WRONG", "baseline": {}, "variants": [{}]}, "methodology"),
        ({"methodology": "ONE_CHANGE_AT_A_TIME", "baseline": None, "variants": [{}]}, "baseline"),
        ({"methodology": "ONE_CHANGE_AT_A_TIME", "baseline": {}, "variants": []}, "variants"),
    ]
    for payload, message in cases:
        _write_json(root / "matrix_manifest.json", payload)
        with pytest.raises(RegistryValidationError, match=message):
            matrix._load_manifest(root)

    (root / "matrix_manifest.json").write_text("[]\n", encoding="utf-8")
    with pytest.raises(RegistryValidationError, match="root must be an object"):
        matrix._load_manifest(root)

    root = _matrix_dir(tmp_path)
    with pytest.raises(RegistryValidationError, match="missing spec path"):
        matrix._entry_spec(root, {})
    with pytest.raises(RegistryValidationError, match="escapes matrix directory"):
        matrix._entry_spec(root, {"spec": "../outside.json"})
    with pytest.raises(RegistryValidationError, match="spec not found"):
        matrix._entry_spec(root, {"spec": "missing.json"})
    assert matrix._entry_spec(root, {"spec": "base.json"}) == (root / "base.json").resolve()


def test_matrix_prepared_and_terminal_completed(monkeypatch, tmp_path: Path) -> None:
    root = _matrix_dir(tmp_path)

    def fake_run(spec_path, registry_db, output_dir, terminal=None, timeout_seconds=0):
        experiment_id = "base-id" if Path(spec_path).stem == "base" else "variant-id"
        return {
            "experiment_id": experiment_id,
            "status": "COMPLETED" if terminal else "PREPARED",
            "artifacts": {"evidence": "ok"},
        }

    monkeypatch.setattr(matrix, "run_registered_experiment", fake_run)
    prepared = matrix.run_matrix(root, tmp_path / "registry.sqlite", tmp_path / "runs")
    assert prepared["status"] == "PREPARED"
    assert prepared["failures"] == []
    assert len(prepared["results"]) == 2

    completed = matrix.run_matrix(
        root,
        tmp_path / "registry.sqlite",
        tmp_path / "runs",
        terminal=tmp_path / "terminal.exe",
        timeout_seconds=10,
    )
    assert completed["status"] == "COMPLETED"
    assert completed["terminal_execution_requested"] is True


def test_matrix_identity_drift_stops_or_continues_by_policy(monkeypatch, tmp_path: Path) -> None:
    root = _matrix_dir(tmp_path)
    calls = []

    def drift(spec_path, *args, **kwargs):
        calls.append(Path(spec_path).name)
        return {"experiment_id": "wrong", "status": "COMPLETED"}

    monkeypatch.setattr(matrix, "run_registered_experiment", drift)
    with pytest.raises(RegistryValidationError, match="baseline"):
        matrix.run_matrix(root, tmp_path / "registry.sqlite", tmp_path / "runs")
    assert calls == ["base.json"]
    failed = json.loads((root / "matrix_execution.json").read_text(encoding="utf-8"))
    assert failed["status"] == "FAILED"
    assert "identity drift" in failed["results"][0]["error"]

    calls.clear()
    with pytest.raises(RegistryValidationError, match="baseline, no-x"):
        matrix.run_matrix(
            root,
            tmp_path / "registry.sqlite",
            tmp_path / "runs",
            continue_on_failure=True,
        )
    assert calls == ["base.json", "variant.json"]
