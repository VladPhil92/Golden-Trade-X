"""Tests for Strategy Tester preset validation and cross-preset invariants."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from scripts.validate_set import parse_set, validate_params


ROOT = Path(__file__).resolve().parents[1]
XAU = ROOT / "config" / "GoldenTradeX.set"
XAG = ROOT / "config" / "GoldenTradeX_XAGUSD.set"


def test_repository_presets_are_individually_valid() -> None:
    assert validate_params(parse_set(XAU), str(XAU)) == []
    assert validate_params(parse_set(XAG), str(XAG)) == []


def test_relational_invariants_are_enforced() -> None:
    params = parse_set(XAU)
    params["InpEmaFast"] = "100"
    params["InpEmaSlow"] = "50"
    params["InpConfWeightFib"] = "6"

    errors = validate_params(params, "synthetic")

    assert any("InpEmaFast must be < InpEmaSlow" in error for error in errors)
    assert any("weights must sum to 100" in error for error in errors)


def test_capital_preservation_must_precede_daily_hard_stop() -> None:
    params = parse_set(XAU)
    params["InpCpThresholdPct"] = params["InpMaxDailyDD"]
    errors = validate_params(params, "synthetic")
    assert any(
        "InpCpThresholdPct must be < InpMaxDailyDD" in error
        for error in errors
    )

    params["InpCpThresholdPct"] = "8.0"
    errors = validate_params(params, "synthetic")
    assert any(
        "Capital Preservation activates before the daily hard stop" in error
        for error in errors
    )


def test_cross_preset_magic_numbers_must_be_unique(tmp_path: Path) -> None:
    first = tmp_path / "first.set"
    second = tmp_path / "second.set"
    first.write_text(XAU.read_text(encoding="utf-8"), encoding="utf-8")
    second.write_text(
        XAG.read_text(encoding="utf-8").replace("InpMagicNumber=920261", "InpMagicNumber=920260"),
        encoding="utf-8",
    )

    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "validate_set.py"), str(first), str(second)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert proc.returncode == 1
    assert "duplicate InpMagicNumber=920260" in proc.stdout
