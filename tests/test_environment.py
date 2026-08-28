"""Build-integrity smoke tests for the supported Python environment."""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "module_name",
    ["requests", "xgboost", "sklearn", "yfinance", "dotenv"],
)
def test_runtime_dependency_imports(module_name: str) -> None:
    """Cross-platform runtime dependencies must import after a clean install."""
    assert importlib.import_module(module_name) is not None


@pytest.mark.parametrize(
    "script",
    [
        "scripts/backtest_analysis.py",
        "scripts/ml_pipeline.py",
        "scripts/performance_report.py",
    ],
)
def test_core_cli_help(script: str) -> None:
    """Core analysis CLIs must at least parse and render their help output."""
    proc = subprocess.run(
        [sys.executable, str(ROOT / script), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "usage" in proc.stdout.lower()
