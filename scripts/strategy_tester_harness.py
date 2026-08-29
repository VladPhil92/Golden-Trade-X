#!/usr/bin/env python3
"""Golden Trade X v2.90 — MetaTrader Strategy Tester harness.

This module prepares deterministic Strategy Tester configuration files and can
optionally execute MetaTrader on Windows. Preparation is not treated as an
executed backtest: completion requires an observed report artifact.
"""

from __future__ import annotations

import argparse
import configparser
import json
import os
import platform
import subprocess
from pathlib import Path
from typing import Any

try:
    from scripts.experiment_registry import (
        RegistryValidationError,
        attach_artifact,
        connect_registry,
        load_spec,
        register_experiment,
        set_status,
        sha256_file,
    )
except ModuleNotFoundError:
    from experiment_registry import (
        RegistryValidationError,
        attach_artifact,
        connect_registry,
        load_spec,
        register_experiment,
        set_status,
        sha256_file,
    )


def _required(spec: dict[str, Any], key: str) -> Any:
    value = spec.get(key)
    if value is None or value == "":
        raise RegistryValidationError(f"missing required field: {key}")
    return value


def _portable_mode(spec: dict[str, Any]) -> bool:
    value = spec.get("portable_mode", True)
    if not isinstance(value, bool):
        raise RegistryValidationError("portable_mode must be true/false")
    return value


def build_tester_config(spec: dict[str, Any], output_dir: str | Path) -> tuple[Path, Path]:
    """Write deterministic MT5 tester INI + execution manifest.

    MT5 numeric model semantics are supplied explicitly by the experiment spec
    rather than inferred here, avoiding hidden assumptions across terminal builds.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    expert = str(_required(spec, "expert"))
    expert_parameters = str(_required(spec, "expert_parameters"))
    symbol = str(_required(spec, "symbol"))
    period = str(_required(spec, "timeframe")).upper()
    from_date = str(_required(spec, "period_start"))[:10].replace("-", ".")
    to_date = str(_required(spec, "period_end"))[:10].replace("-", ".")
    tester_model = int(_required(spec, "tester_model"))
    if tester_model < 0:
        raise RegistryValidationError("tester_model must be >= 0")
    portable_mode = _portable_mode(spec)

    report_path = out / "strategy_tester_report.htm"
    ini_path = out / "strategy_tester.ini"
    manifest_path = out / "execution_manifest.json"

    config = configparser.ConfigParser(interpolation=None)
    config.optionxform = str
    config["Tester"] = {
        "Expert": expert,
        "ExpertParameters": expert_parameters,
        "Symbol": symbol,
        "Period": period,
        "Model": str(tester_model),
        "ExecutionMode": str(spec.get("execution_mode", 0)),
        "Optimization": "1" if bool(spec.get("optimization", False)) else "0",
        "FromDate": from_date,
        "ToDate": to_date,
        "ForwardMode": str(spec.get("forward_mode_code", 0)),
        "Deposit": str(spec.get("deposit", 10000)),
        "Currency": str(spec.get("currency", "USD")),
        "Leverage": f"1:{int(spec.get('leverage', 100))}",
        "Report": str(report_path),
        "ReplaceReport": "1",
        "ShutdownTerminal": "1",
        "Visual": "0",
    }

    with ini_path.open("w", encoding="utf-8", newline="\n") as handle:
        config.write(handle, space_around_delimiters=False)

    execution_manifest = {
        "schema_version": 1,
        "tester_ini": ini_path.name,
        "tester_ini_sha256": sha256_file(ini_path),
        "expected_report": report_path.name,
        "git_sha": spec.get("git_sha"),
        "preset_path": spec.get("preset_path"),
        "symbol": symbol,
        "timeframe": period,
        "period_start": spec.get("period_start"),
        "period_end": spec.get("period_end"),
        "tester_model": tester_model,
        "execution_mode": int(spec.get("execution_mode", 0)),
        "portable_mode": portable_mode,
        "modelling": spec.get("modelling"),
        "status": "PREPARED_NOT_EXECUTED",
    }
    manifest_path.write_text(
        json.dumps(execution_manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return ini_path, manifest_path


def build_terminal_command(
    terminal: str | Path,
    ini_path: str | Path,
    *,
    portable_mode: bool = True,
) -> list[str]:
    terminal_path = Path(terminal)
    ini = Path(ini_path).resolve()
    command = [str(terminal_path)]
    if portable_mode:
        command.append("/portable")
    command.append(f"/config:{ini}")
    return command


def execute_terminal(
    terminal: str | Path,
    ini_path: str | Path,
    timeout_seconds: int = 3600,
    *,
    portable_mode: bool = True,
) -> int:
    if platform.system() != "Windows":
        raise RegistryValidationError("Strategy Tester execution is supported only on Windows")
    terminal_path = Path(terminal)
    if not terminal_path.is_file():
        raise RegistryValidationError(f"terminal executable not found: {terminal_path}")
    command = build_terminal_command(terminal_path, ini_path, portable_mode=portable_mode)
    completed = subprocess.run(command, check=False, timeout=timeout_seconds)
    return int(completed.returncode)


def run_registered_experiment(
    spec_path: str | Path,
    registry_db: str | Path,
    output_dir: str | Path,
    terminal: str | Path | None = None,
    timeout_seconds: int = 3600,
) -> dict[str, Any]:
    spec_path = Path(spec_path)
    spec = load_spec(spec_path)
    portable_mode = _portable_mode(spec)
    connection = connect_registry(registry_db)
    try:
        record = register_experiment(connection, spec, base_dir=spec_path.parent, status="PLANNED")
        experiment_id = record["experiment_id"]
        run_dir = Path(output_dir) / experiment_id
        ini_path, manifest_path = build_tester_config(spec, run_dir)
        attach_artifact(connection, experiment_id, "tester_ini", ini_path)
        attach_artifact(connection, experiment_id, "execution_manifest", manifest_path)
        record = set_status(connection, experiment_id, "PREPARED")

        if terminal is None:
            return record

        set_status(connection, experiment_id, "RUNNING")
        exit_code = execute_terminal(
            terminal,
            ini_path,
            timeout_seconds=timeout_seconds,
            portable_mode=portable_mode,
        )
        report_path = run_dir / "strategy_tester_report.htm"
        if exit_code != 0 or not report_path.is_file() or report_path.stat().st_size == 0:
            set_status(connection, experiment_id, "FAILED")
            raise RegistryValidationError(
                f"Strategy Tester did not produce valid evidence (exit_code={exit_code}, report={report_path})"
            )
        attach_artifact(connection, experiment_id, "strategy_tester_report", report_path)
        return set_status(connection, experiment_id, "COMPLETED")
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--registry", default="data/research/experiments.sqlite")
    parser.add_argument("--output-dir", default="data/research/runs")
    parser.add_argument("--terminal", default=os.environ.get("GTX_MT5_TERMINAL"))
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    args = parser.parse_args()

    try:
        record = run_registered_experiment(
            args.spec,
            args.registry,
            args.output_dir,
            terminal=args.terminal,
            timeout_seconds=args.timeout_seconds,
        )
    except RegistryValidationError as exc:
        parser.error(str(exc))
        return
    print(json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
