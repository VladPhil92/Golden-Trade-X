import json
from pathlib import Path

import pytest

from scripts.ablation_report import build_ablation_report
from scripts.experiment_matrix import generate_matrix
from scripts.experiment_registry import (
    attach_artifact,
    connect_registry,
    load_spec,
    register_experiment,
    set_status,
)
from scripts.strategy_tester_matrix import run_matrix


def _base_spec() -> dict:
    return {
        "git_sha": "c" * 40,
        "preset_path": "baseline_source.set",
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
        "expert_parameters": "baseline_source.set",
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
    }


def _prepare_matrix(tmp_path: Path) -> Path:
    preset = tmp_path / "baseline_source.set"
    preset.write_text(
        "InpUseSmcFilter=true\nInpUseRegimeFilter=true\n",
        encoding="utf-8",
    )
    base_spec = tmp_path / "base.json"
    base_spec.write_text(json.dumps(_base_spec()), encoding="utf-8")
    matrix_config = tmp_path / "matrix.json"
    matrix_config.write_text(
        json.dumps(
            {
                "variants": [
                    {"name": "no_smc", "parameter": "InpUseSmcFilter", "value": False},
                    {"name": "no_regime", "parameter": "InpUseRegimeFilter", "value": False},
                ]
            }
        ),
        encoding="utf-8",
    )
    matrix_dir = tmp_path / "matrix"
    generate_matrix(base_spec, matrix_config, matrix_dir)
    return matrix_dir


def test_matrix_dry_run_prepares_baseline_and_variants(tmp_path: Path) -> None:
    matrix_dir = _prepare_matrix(tmp_path)
    registry = tmp_path / "registry.sqlite"
    runs = tmp_path / "runs"

    summary = run_matrix(matrix_dir, registry, runs, terminal=None)

    assert summary["status"] == "PREPARED"
    assert summary["failures"] == []
    assert [item["name"] for item in summary["results"]] == ["baseline", "no_smc", "no_regime"]
    assert all(item["status"] == "PREPARED" for item in summary["results"])
    assert (matrix_dir / "matrix_execution.json").is_file()


def _normalized(experiment_id: str, *, profit: float, pf: float, dd: float) -> dict:
    return {
        "schema_version": 1,
        "parser_version": "test",
        "experiment_id": experiment_id,
        "summary": {
            "total_net_profit": profit,
            "profit_factor": pf,
            "expected_payoff": profit / 100.0,
            "max_drawdown_pct": dd,
            "total_trades": 100,
            "win_rate": 55.0,
            "recovery_factor": 2.0,
            "sharpe_ratio": 1.1,
        },
        "metrics": {},
        "warnings": [],
    }


def test_ablation_report_uses_only_completed_normalized_evidence(tmp_path: Path) -> None:
    matrix_dir = _prepare_matrix(tmp_path)
    manifest = json.loads((matrix_dir / "matrix_manifest.json").read_text(encoding="utf-8"))
    registry_path = tmp_path / "registry.sqlite"
    connection = connect_registry(registry_path)
    try:
        entries = [manifest["baseline"], *manifest["variants"]]
        values = [(1000.0, 1.50, 6.0), (700.0, 1.20, 8.0), (1100.0, 1.55, 5.5)]
        for entry, (profit, pf, dd) in zip(entries, values, strict=True):
            spec_path = matrix_dir / entry["spec"]
            record = register_experiment(
                connection,
                load_spec(spec_path),
                base_dir=spec_path.parent,
            )
            normalized_path = tmp_path / f"{record['experiment_id']}.json"
            normalized_path.write_text(
                json.dumps(_normalized(record["experiment_id"], profit=profit, pf=pf, dd=dd)),
                encoding="utf-8",
            )
            attach_artifact(connection, record["experiment_id"], "normalized_results", normalized_path)
            set_status(connection, record["experiment_id"], "COMPLETED")
    finally:
        connection.close()

    output = tmp_path / "ablation_report.json"
    report = build_ablation_report(matrix_dir, registry_path, output)

    assert report["baseline"]["metrics"]["profit_factor"] == pytest.approx(1.50)
    assert report["variants"][0]["delta_vs_baseline"]["total_net_profit"]["absolute"] == pytest.approx(-300.0)
    assert report["variants"][1]["delta_vs_baseline"]["max_drawdown_pct"]["absolute"] == pytest.approx(-0.5)
    assert report["interpretation"].startswith("DESCRIPTIVE_ONLY")
    assert output.is_file()
