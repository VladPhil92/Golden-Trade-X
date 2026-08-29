import json
from pathlib import Path

import pytest

from scripts.experiment_matrix import generate_matrix
from scripts.experiment_registry import RegistryValidationError


def _base_spec() -> dict:
    return {
        "git_sha": "c" * 40,
        "preset_path": "GoldenTradeX.set",
        "broker": "Test Broker",
        "symbol": "XAUUSD",
        "timeframe": "M15",
        "period_start": "2024-01-01T00:00:00Z",
        "period_end": "2024-12-31T23:59:59Z",
        "source_type": "strategy_tester",
        "mt5_build": "6000",
        "modelling": "Every tick based on real ticks",
        "tester_model": 4,
        "expert": "GoldenTradeX\\GoldenTradeX.ex5",
        "expert_parameters": "GoldenTradeX.set",
        "deposit": 10000,
        "currency": "USD",
        "leverage": 100,
    }


def _write_inputs(tmp_path: Path, variants: list[dict]) -> tuple[Path, Path]:
    preset = tmp_path / "GoldenTradeX.set"
    preset.write_text(
        "InpUseSmcFilter=true\nInpUseRegimeFilter=true\nInpRiskPercent=1.0\n",
        encoding="utf-8",
    )
    base = tmp_path / "experiment.json"
    base.write_text(json.dumps(_base_spec()), encoding="utf-8")
    matrix = tmp_path / "matrix.json"
    matrix.write_text(json.dumps({"variants": variants}), encoding="utf-8")
    return base, matrix


def test_matrix_generates_baseline_and_one_change_variants(tmp_path: Path) -> None:
    base, matrix = _write_inputs(
        tmp_path,
        [
            {"name": "no_smc", "parameter": "InpUseSmcFilter", "value": False},
            {"name": "no_regime", "parameter": "InpUseRegimeFilter", "value": False},
        ],
    )
    output = tmp_path / "matrix-out"
    manifest = generate_matrix(base, matrix, output)

    assert manifest["methodology"] == "ONE_CHANGE_AT_A_TIME"
    assert len(manifest["variants"]) == 2
    assert manifest["variants"][0]["experiment_id"] != manifest["baseline"]["experiment_id"]

    baseline_lines = (output / "presets/baseline.set").read_text(encoding="utf-8").splitlines()
    no_smc_lines = (output / "presets/no_smc.set").read_text(encoding="utf-8").splitlines()
    differences = [(a, b) for a, b in zip(baseline_lines, no_smc_lines) if a != b]
    assert differences == [("InpUseSmcFilter=true", "InpUseSmcFilter=false")]

    variant_spec = json.loads((output / "specs/no_smc.json").read_text(encoding="utf-8"))
    assert variant_spec["parent_experiment_id"] == manifest["baseline"]["experiment_id"]
    assert variant_spec["changed_parameter"] == "InpUseSmcFilter"
    assert variant_spec["changed_from"] == "true"
    assert variant_spec["changed_to"] == "false"


def test_matrix_rejects_missing_parameter(tmp_path: Path) -> None:
    base, matrix = _write_inputs(
        tmp_path,
        [{"name": "bad", "parameter": "InpDoesNotExist", "value": False}],
    )
    with pytest.raises(RegistryValidationError, match="expected exactly one"):
        generate_matrix(base, matrix, tmp_path / "out")


def test_matrix_rejects_duplicate_variant_names(tmp_path: Path) -> None:
    base, matrix = _write_inputs(
        tmp_path,
        [
            {"name": "duplicate", "parameter": "InpUseSmcFilter", "value": False},
            {"name": "duplicate", "parameter": "InpUseRegimeFilter", "value": False},
        ],
    )
    with pytest.raises(RegistryValidationError, match="duplicate variant name"):
        generate_matrix(base, matrix, tmp_path / "out")
