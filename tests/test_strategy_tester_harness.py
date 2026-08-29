import json
from pathlib import Path

import pytest

from scripts.experiment_registry import RegistryValidationError
from scripts.strategy_tester_harness import build_tester_config, execute_terminal


def _tester_spec() -> dict:
    return {
        "git_sha": "b" * 40,
        "preset_path": "preset.set",
        "expert": "GoldenTradeX\\GoldenTradeX.ex5",
        "expert_parameters": "GoldenTradeX.set",
        "symbol": "XAUUSD",
        "timeframe": "M15",
        "period_start": "2024-01-01T00:00:00Z",
        "period_end": "2024-12-31T23:59:59Z",
        "tester_model": 4,
        "modelling": "Every tick based on real ticks",
        "deposit": 10000,
        "currency": "USD",
        "leverage": 100,
        "optimization": False,
        "forward_mode_code": 0,
    }


def test_prepare_writes_deterministic_ini_and_nonexecuted_manifest(tmp_path: Path) -> None:
    spec = _tester_spec()
    ini_path, manifest_path = build_tester_config(spec, tmp_path)
    first_ini = ini_path.read_text(encoding="utf-8")
    first_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    ini_path_2, manifest_path_2 = build_tester_config(spec, tmp_path)
    assert ini_path_2.read_text(encoding="utf-8") == first_ini
    second_manifest = json.loads(manifest_path_2.read_text(encoding="utf-8"))
    assert second_manifest == first_manifest
    assert first_manifest["status"] == "PREPARED_NOT_EXECUTED"
    assert first_manifest["tester_ini_sha256"] == second_manifest["tester_ini_sha256"]
    assert "Optimization=0" in first_ini
    assert "Visual=0" in first_ini
    assert "ShutdownTerminal=1" in first_ini


def test_prepare_requires_explicit_tester_model(tmp_path: Path) -> None:
    spec = _tester_spec()
    del spec["tester_model"]
    with pytest.raises(RegistryValidationError, match="tester_model"):
        build_tester_config(spec, tmp_path)


def test_negative_model_fails_closed(tmp_path: Path) -> None:
    spec = _tester_spec()
    spec["tester_model"] = -1
    with pytest.raises(RegistryValidationError, match="tester_model"):
        build_tester_config(spec, tmp_path)


def test_terminal_execution_is_not_silently_emulated_off_windows(tmp_path: Path) -> None:
    import platform

    if platform.system() == "Windows":
        pytest.skip("non-Windows fail-closed behavior only")
    fake_terminal = tmp_path / "terminal64.exe"
    fake_terminal.write_bytes(b"not executable")
    with pytest.raises(RegistryValidationError, match="only on Windows"):
        execute_terminal(fake_terminal, tmp_path / "tester.ini")
