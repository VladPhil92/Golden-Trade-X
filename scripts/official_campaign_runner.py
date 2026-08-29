#!/usr/bin/env python3
"""Prepare and execute the frozen Golden Trade X official IS→OOS campaign.

The runner is deliberately limited to the OOS promotion boundary. It can prepare
all deterministic IS specs without MetaTrader, or execute every IS candidate,
freeze each fold's winner using IS evidence only, execute the corresponding OOS
run, aggregate the folds and apply the pre-registered OOS promotion policy.

A positive decision authorizes only the next robustness phase. Live trading and
real capital remain explicitly unauthorized.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

try:
    from scripts.campaign_contract import candidate_universe_sha256
    from scripts.execution_environment import (
        load_and_validate_attestation,
        load_execution_environment_contract,
        validate_execution_environment,
    )
    from scripts.experiment_registry import (
        RegistryValidationError,
        identity_for,
        load_spec,
        normalize_spec,
        sha256_file,
    )
    from scripts.promotion_gate import evaluate_promotion
    from scripts.strategy_tester_harness import run_registered_experiment
    from scripts.walk_forward_aggregate import aggregate_oos_evidence
    from scripts.walk_forward_selector import select_and_freeze
except ModuleNotFoundError:
    from campaign_contract import candidate_universe_sha256
    from execution_environment import (
        load_and_validate_attestation,
        load_execution_environment_contract,
        validate_execution_environment,
    )
    from experiment_registry import (
        RegistryValidationError,
        identity_for,
        load_spec,
        normalize_spec,
        sha256_file,
    )
    from promotion_gate import evaluate_promotion
    from strategy_tester_harness import run_registered_experiment
    from walk_forward_aggregate import aggregate_oos_evidence
    from walk_forward_selector import select_and_freeze

_BUILD_RE = re.compile(r"^[0-9a-f]{40}$")
SUPPORTED_LOCK_METHOD = "OFFICIAL_VALIDATION_CAMPAIGN_FREEZE_V1"


def _load_json(path: str | Path) -> dict[str, Any]:
    target = Path(path).resolve()
    with target.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise RegistryValidationError(f"JSON root must be an object: {target}")
    return value


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _resolve_within(root: Path, raw: Any, field: str) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise RegistryValidationError(f"{field} is required")
    root = root.resolve()
    target = (root / raw).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise RegistryValidationError(f"{field} escapes frozen config root: {raw}") from exc
    if not target.is_file():
        raise RegistryValidationError(f"{field} not found: {target}")
    return target


def _relpath(target: Path, start: Path) -> str:
    return Path(os.path.relpath(target.resolve(), start.resolve())).as_posix()


def _validate_lock(lock: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if lock.get("methodology") != SUPPORTED_LOCK_METHOD:
        raise RegistryValidationError("unsupported official campaign lock methodology")
    if lock.get("status") != "OFFICIAL_CAMPAIGN_FROZEN":
        raise RegistryValidationError(
            "official campaign execution requires OFFICIAL_CAMPAIGN_FROZEN"
        )
    if lock.get("live_trading_authorized") is not False:
        raise RegistryValidationError("campaign lock must explicitly deny live trading")

    build_id = lock.get("build_id")
    if not isinstance(build_id, str) or not _BUILD_RE.fullmatch(build_id):
        raise RegistryValidationError("campaign lock build_id must be a full lowercase Git SHA")

    environment = lock.get("execution_environment")
    if not isinstance(environment, dict):
        raise RegistryValidationError("campaign lock lacks frozen execution_environment")
    contract = environment.get("contract")
    if not isinstance(contract, dict):
        raise RegistryValidationError("campaign lock lacks execution environment contract")
    normalized_contract = validate_execution_environment(contract)
    if normalized_contract["approved"] is not True:
        raise RegistryValidationError("frozen execution environment is not approved")

    walk = lock.get("walk_forward")
    if not isinstance(walk, dict):
        raise RegistryValidationError("campaign lock lacks walk_forward contract")
    return normalized_contract, walk


def _verify_source_contract(
    lock: dict[str, Any],
    config_root: Path,
) -> tuple[dict[str, Any], str]:
    environment = lock["execution_environment"]
    path = _resolve_within(
        config_root,
        environment.get("path"),
        "execution_environment.path",
    )
    contract, file_sha = load_execution_environment_contract(path)
    if file_sha != environment.get("file_sha256"):
        raise RegistryValidationError(
            "execution environment file changed after campaign freeze"
        )
    if contract != environment.get("contract"):
        raise RegistryValidationError(
            "execution environment semantic snapshot changed after campaign freeze"
        )
    return contract, file_sha


def _verify_candidate_sources(
    lock: dict[str, Any],
    config_root: Path,
) -> list[dict[str, Any]]:
    universe = lock.get("candidate_universe")
    if not isinstance(universe, dict):
        raise RegistryValidationError("campaign lock lacks candidate_universe")
    candidates = universe.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise RegistryValidationError("campaign lock candidate universe is empty")
    if candidate_universe_sha256(candidates) != universe.get("sha256"):
        raise RegistryValidationError("campaign lock candidate universe fingerprint is invalid")

    verified: list[dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, dict):
            raise RegistryValidationError("campaign candidate entry must be an object")
        name = item.get("name")
        path = _resolve_within(
            config_root,
            item.get("preset_path"),
            f"candidate {name}.preset_path",
        )
        actual_sha = sha256_file(path)
        if actual_sha != item.get("preset_sha256"):
            raise RegistryValidationError(
                f"candidate {name} preset changed after campaign freeze"
            )
        text = path.read_text(encoding="utf-8-sig")
        real_guard = [
            line.split("=", 1)[1].strip().lower()
            for line in text.splitlines()
            if line.strip().startswith("InpAllowRealTrading=")
        ]
        if real_guard != ["false"]:
            raise RegistryValidationError(
                f"candidate {name} must retain exactly one InpAllowRealTrading=false"
            )
        verified.append({**item, "source_path": path})
    return verified


def _walk_plan(lock_path: Path, walk: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    raw = walk.get("plan_path")
    if not isinstance(raw, str) or not raw.strip():
        raise RegistryValidationError("campaign lock walk_forward.plan_path is required")
    path = (lock_path.parent / raw).resolve()
    try:
        path.relative_to(lock_path.parent.resolve())
    except ValueError as exc:
        raise RegistryValidationError("walk-forward plan escapes campaign lock directory") from exc
    if not path.is_file():
        raise RegistryValidationError(f"frozen walk-forward plan not found: {path}")
    if sha256_file(path) != walk.get("plan_sha256"):
        raise RegistryValidationError("frozen walk-forward plan SHA-256 mismatch")
    plan = _load_json(path)
    if plan.get("methodology") != "ROLLING_IS_FROZEN_OOS":
        raise RegistryValidationError("unsupported frozen walk-forward methodology")
    if plan.get("status") != "READY_FOR_REGISTERED_EXECUTION":
        raise RegistryValidationError("frozen walk-forward plan is not execution-ready")
    return path, plan


def _experiment_spec(
    environment: dict[str, Any],
    build_id: str,
    preset_path: str,
    expert_parameters: str,
    period_start: str,
    period_end: str,
    *,
    notes: str,
) -> dict[str, Any]:
    return {
        "git_sha": build_id,
        "preset_path": preset_path,
        "broker": environment["broker_label"],
        "symbol": environment["symbol"],
        "timeframe": environment["timeframe"],
        "period_start": period_start,
        "period_end": period_end,
        "source_type": "strategy_tester",
        "mt5_build": environment["mt5_build"],
        "modelling": environment["modelling"],
        "tester_model": environment["tester_model"],
        "expert": environment["expert"],
        "expert_parameters": expert_parameters,
        "execution_mode": environment["execution_mode"],
        "portable_mode": environment["portable_mode"],
        "deposit": environment["deposit"],
        "currency": environment["currency"],
        "leverage": environment["leverage"],
        "spread_mode": environment["spread_mode"],
        "commission": environment["commission"],
        "swap_mode": environment["swap_mode"],
        "slippage_points": environment["slippage_points"],
        "optimization": False,
        "forward_mode": "disabled",
        "forward_mode_code": 0,
        "parent_experiment_id": None,
        "changed_parameter": None,
        "changed_from": None,
        "changed_to": None,
        "notes": notes,
    }


def prepare_official_campaign(
    campaign_lock_path: str | Path,
    attestation_path: str | Path,
    config_root: str | Path,
    output_dir: str | Path,
    *,
    actual_git_sha: str | None = None,
) -> dict[str, Any]:
    lock_path = Path(campaign_lock_path).resolve()
    lock = _load_json(lock_path)
    environment, walk = _validate_lock(lock)
    config_root = Path(config_root).resolve()

    if actual_git_sha is not None:
        normalized_sha = actual_git_sha.strip().lower()
        if not _BUILD_RE.fullmatch(normalized_sha):
            raise RegistryValidationError("actual_git_sha must be a full lowercase Git SHA")
        if normalized_sha != lock["build_id"]:
            raise RegistryValidationError(
                "runtime Git SHA differs from the build frozen into campaign lock"
            )

    source_contract, contract_file_sha = _verify_source_contract(lock, config_root)
    attestation, attestation_sha = load_and_validate_attestation(
        attestation_path,
        source_contract,
        contract_file_sha,
    )
    candidates = _verify_candidate_sources(lock, config_root)
    plan_path, plan = _walk_plan(lock_path, walk)

    output = Path(output_dir).resolve()
    manifest_path = output / "campaign_execution_manifest.json"
    if manifest_path.exists():
        raise RegistryValidationError(
            f"campaign execution output already contains a manifest: {manifest_path}"
        )
    output.mkdir(parents=True, exist_ok=True)

    fold_rows: list[dict[str, Any]] = []
    folds = plan.get("folds")
    if not isinstance(folds, list) or not folds:
        raise RegistryValidationError("frozen walk-forward plan has no folds")

    for fold in folds:
        if not isinstance(fold, dict):
            raise RegistryValidationError("walk-forward fold must be an object")
        fold_id = fold.get("fold_id")
        window = fold.get("in_sample")
        if not isinstance(fold_id, str) or not fold_id:
            raise RegistryValidationError("walk-forward fold_id is required")
        if not isinstance(window, dict):
            raise RegistryValidationError(f"{fold_id}: in_sample window missing")

        fold_dir = output / "folds" / fold_id
        specs_dir = fold_dir / "is" / "specs"
        presets_dir = fold_dir / "is" / "presets"
        specs_dir.mkdir(parents=True, exist_ok=True)
        presets_dir.mkdir(parents=True, exist_ok=True)

        candidate_rows: list[dict[str, Any]] = []
        for candidate in candidates:
            name = str(candidate["name"])
            source = Path(candidate["source_path"])
            preset_target = presets_dir / f"{name}.set"
            shutil.copyfile(source, preset_target)
            if sha256_file(preset_target) != candidate["preset_sha256"]:
                raise RegistryValidationError(
                    f"{fold_id}/{name}: frozen execution copy hash mismatch"
                )

            spec = _experiment_spec(
                environment,
                lock["build_id"],
                f"../presets/{preset_target.name}",
                preset_target.name,
                str(window.get("period_start")),
                str(window.get("period_end")),
                notes=(
                    f"Official campaign {lock['campaign_id']} {fold_id} IS candidate "
                    f"{name}; campaign_fingerprint={lock.get('campaign_fingerprint')}."
                ),
            )
            spec_path = specs_dir / f"{name}.json"
            _write_json(spec_path, spec)
            normalized, _ = normalize_spec(spec, base_dir=specs_dir)
            identity = identity_for(normalized)
            if identity.preset_sha256 != candidate["preset_sha256"]:
                raise RegistryValidationError(
                    f"{fold_id}/{name}: experiment identity preset differs from campaign lock"
                )
            candidate_rows.append(
                {
                    "name": name,
                    "experiment_id": identity.experiment_id,
                    "fingerprint": identity.fingerprint,
                    "preset_sha256": identity.preset_sha256,
                    "spec": _relpath(spec_path, output),
                    "preset": _relpath(preset_target, output),
                }
            )

        fold_manifest = {
            "schema_version": 1,
            "methodology": "OFFICIAL_IS_EXECUTION_SET_V1",
            "campaign_id": lock["campaign_id"],
            "campaign_fingerprint": lock.get("campaign_fingerprint"),
            "fold_id": fold_id,
            "candidate_universe_sha256": lock["candidate_universe"]["sha256"],
            "period_start": window.get("period_start"),
            "period_end": window.get("period_end"),
            "candidates": candidate_rows,
            "status": "PREPARED_NOT_EXECUTED",
            "live_trading_authorized": False,
        }
        fold_manifest_path = fold_dir / "is_execution_set.json"
        _write_json(fold_manifest_path, fold_manifest)
        fold_rows.append(
            {
                "fold_id": fold_id,
                "is_execution_set": _relpath(fold_manifest_path, output),
                "candidate_count": len(candidate_rows),
                "status": "PREPARED_NOT_EXECUTED",
            }
        )

    manifest = {
        "schema_version": 1,
        "methodology": "OFFICIAL_WALK_FORWARD_EXECUTION_V1",
        "campaign_id": lock["campaign_id"],
        "campaign_fingerprint": lock.get("campaign_fingerprint"),
        "status": "PREPARED_NOT_EXECUTED",
        "decision_scope": "OOS_PROMOTION_ONLY",
        "live_trading_authorized": False,
        "real_capital_authorized": False,
        "build_id": lock["build_id"],
        "campaign_lock_sha256": sha256_file(lock_path),
        "walk_forward_plan_sha256": sha256_file(plan_path),
        "candidate_universe_sha256": lock["candidate_universe"]["sha256"],
        "execution_environment": {
            "environment_id": environment["environment_id"],
            "contract_file_sha256": contract_file_sha,
            "attestation_sha256": attestation_sha,
            "attested_mt5_build": attestation["observed"]["mt5_build"],
            "attested_broker": environment["broker_label"],
            "trade_mode": "DEMO",
        },
        "folds": fold_rows,
    }
    _write_json(manifest_path, manifest)
    return manifest


def _stage_preset(spec_path: Path, tester_profiles_dir: Path) -> None:
    spec = load_spec(spec_path)
    raw_preset = spec.get("preset_path")
    expert_parameters = spec.get("expert_parameters")
    if not isinstance(raw_preset, str) or not raw_preset:
        raise RegistryValidationError(f"spec preset_path missing: {spec_path}")
    if not isinstance(expert_parameters, str) or not expert_parameters:
        raise RegistryValidationError(f"spec expert_parameters missing: {spec_path}")
    if Path(expert_parameters).name != expert_parameters:
        raise RegistryValidationError("expert_parameters must be a filename for official execution")

    source = (spec_path.parent / raw_preset).resolve()
    if not source.is_file():
        raise RegistryValidationError(f"preset referenced by spec not found: {source}")
    tester_profiles_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, tester_profiles_dir / expert_parameters)


def _run_spec(
    spec_path: Path,
    *,
    tester_profiles_dir: Path,
    terminal: Path,
    registry_db: Path,
    runs_dir: Path,
    timeout_seconds: int,
) -> tuple[dict[str, Any], Path]:
    _stage_preset(spec_path, tester_profiles_dir)
    record = run_registered_experiment(
        spec_path,
        registry_db,
        runs_dir,
        terminal=terminal,
        timeout_seconds=timeout_seconds,
    )
    if record.get("status") != "COMPLETED":
        raise RegistryValidationError(
            f"registered experiment did not complete: {record.get('experiment_id')}"
        )
    normalized = runs_dir / str(record["experiment_id"]) / "normalized_results.json"
    if not normalized.is_file():
        raise RegistryValidationError(
            f"normalized Strategy Tester evidence missing: {normalized}"
        )
    return record, normalized


def execute_official_campaign(
    campaign_lock_path: str | Path,
    attestation_path: str | Path,
    config_root: str | Path,
    output_dir: str | Path,
    *,
    actual_git_sha: str,
    terminal: str | Path,
    tester_profiles_dir: str | Path,
    registry_db: str | Path,
    runs_dir: str | Path,
    timeout_seconds: int = 3600,
) -> dict[str, Any]:
    output = Path(output_dir).resolve()
    manifest = prepare_official_campaign(
        campaign_lock_path,
        attestation_path,
        config_root,
        output,
        actual_git_sha=actual_git_sha,
    )
    manifest_path = output / "campaign_execution_manifest.json"
    lock_path = Path(campaign_lock_path).resolve()
    lock = _load_json(lock_path)
    _, walk = _validate_lock(lock)
    plan_path, _ = _walk_plan(lock_path, walk)

    terminal = Path(terminal).resolve()
    if not terminal.is_file():
        raise RegistryValidationError(f"MetaTrader terminal not found: {terminal}")
    tester_profiles = Path(tester_profiles_dir).resolve()
    registry = Path(registry_db).resolve()
    runs = Path(runs_dir).resolve()
    runs.mkdir(parents=True, exist_ok=True)

    oos_entries: list[dict[str, Any]] = []
    try:
        for fold_row in manifest["folds"]:
            fold_id = str(fold_row["fold_id"])
            fold_dir = output / "folds" / fold_id
            execution_set_path = output / str(fold_row["is_execution_set"])
            execution_set = _load_json(execution_set_path)

            candidate_evidence: list[dict[str, Any]] = []
            for candidate in execution_set["candidates"]:
                spec_path = output / str(candidate["spec"])
                record, normalized_path = _run_spec(
                    spec_path,
                    tester_profiles_dir=tester_profiles,
                    terminal=terminal,
                    registry_db=registry,
                    runs_dir=runs,
                    timeout_seconds=timeout_seconds,
                )
                if record["experiment_id"] != candidate["experiment_id"]:
                    raise RegistryValidationError(
                        f"{fold_id}/{candidate['name']}: experiment identity drift"
                    )
                candidate_evidence.append(
                    {
                        "name": candidate["name"],
                        "spec": _relpath(spec_path, fold_dir),
                        "normalized_results": _relpath(normalized_path, fold_dir),
                    }
                )

            is_evidence_path = fold_dir / "is_evidence_manifest.json"
            _write_json(
                is_evidence_path,
                {
                    "schema_version": 1,
                    "methodology": "OFFICIAL_IS_EVIDENCE_V1",
                    "campaign_fingerprint": lock.get("campaign_fingerprint"),
                    "fold_id": fold_id,
                    "candidate_universe_sha256": lock["candidate_universe"]["sha256"],
                    "candidates": candidate_evidence,
                },
            )

            selection_dir = fold_dir / "selection"
            selection = select_and_freeze(
                plan_path,
                is_evidence_path,
                selection_dir,
            )
            selection_path = selection_dir / "selection_manifest.json"
            oos_spec_path = selection_dir / "oos_spec.json"
            oos_record, oos_normalized = _run_spec(
                oos_spec_path,
                tester_profiles_dir=tester_profiles,
                terminal=terminal,
                registry_db=registry,
                runs_dir=runs,
                timeout_seconds=timeout_seconds,
            )
            expected_oos_id = selection.get("oos", {}).get("experiment_id")
            if oos_record["experiment_id"] != expected_oos_id:
                raise RegistryValidationError(f"{fold_id}: frozen OOS identity drift")

            oos_entries.append(
                {
                    "fold_id": fold_id,
                    "selection_manifest": _relpath(selection_path, output),
                    "oos_spec": _relpath(oos_spec_path, output),
                    "normalized_results": _relpath(oos_normalized, output),
                }
            )
            fold_row["status"] = "OOS_COMPLETED"
            fold_row["selected_candidate"] = selection.get("selected", {}).get("name")
            fold_row["oos_experiment_id"] = oos_record["experiment_id"]
            _write_json(manifest_path, manifest)

        oos_evidence_path = output / "oos_evidence_manifest.json"
        _write_json(
            oos_evidence_path,
            {
                "schema_version": 1,
                "methodology": "OFFICIAL_OOS_EVIDENCE_SET_V1",
                "campaign_id": lock["campaign_id"],
                "campaign_fingerprint": lock.get("campaign_fingerprint"),
                "candidate_universe_sha256": lock["candidate_universe"]["sha256"],
                "folds": oos_entries,
            },
        )

        oos_summary_path = output / "oos_summary.json"
        oos_summary = aggregate_oos_evidence(
            plan_path,
            oos_evidence_path,
            oos_summary_path,
        )
        if (
            oos_summary.get("candidate_universe_sha256")
            != lock["candidate_universe"]["sha256"]
        ):
            raise RegistryValidationError(
                "OOS aggregate candidate universe differs from campaign lock"
            )

        config_root_path = Path(config_root).resolve()
        promotion = walk.get("promotion_policy")
        if not isinstance(promotion, dict):
            raise RegistryValidationError("campaign lock lacks promotion policy snapshot")
        walk_config_path = _resolve_within(
            config_root_path,
            walk.get("config_path"),
            "walk_forward.config_path",
        )
        walk_config = _load_json(walk_config_path)
        policy_path = _resolve_within(
            walk_config_path.parent,
            walk_config.get("promotion_policy_path"),
            "promotion_policy_path",
        )
        if sha256_file(policy_path) != promotion.get("sha256"):
            raise RegistryValidationError(
                "promotion policy file changed after campaign freeze"
            )

        decision_path = output / "oos_promotion_decision.json"
        decision = evaluate_promotion(
            oos_summary_path,
            policy_path,
            decision_path,
        )

        manifest["oos_evidence_manifest_sha256"] = sha256_file(oos_evidence_path)
        manifest["oos_summary_sha256"] = sha256_file(oos_summary_path)
        manifest["promotion_decision_sha256"] = sha256_file(decision_path)
        manifest["promotable_to_robustness"] = bool(decision["promotable"])
        manifest["status"] = (
            "OOS_PROMOTION_PASS_READY_FOR_ROBUSTNESS"
            if decision["promotable"]
            else "OOS_PROMOTION_REJECTED"
        )
        _write_json(manifest_path, manifest)
        return manifest
    except Exception as exc:  # noqa: BLE001 - persist the exact failed stage.
        manifest["status"] = "FAILED"
        manifest["failure"] = f"{type(exc).__name__}: {exc}"
        _write_json(manifest_path, manifest)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-lock", required=True)
    parser.add_argument("--attestation", required=True)
    parser.add_argument("--config-root", default="config")
    parser.add_argument(
        "--output-dir",
        default="data/research/official_campaign/execution",
    )
    parser.add_argument("--actual-git-sha")
    parser.add_argument("--terminal")
    parser.add_argument("--tester-profiles-dir")
    parser.add_argument(
        "--registry",
        default="data/research/official_campaign/experiments.sqlite",
    )
    parser.add_argument(
        "--runs-dir",
        default="data/research/official_campaign/runs",
    )
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    args = parser.parse_args()

    try:
        if args.terminal:
            if not args.actual_git_sha:
                raise RegistryValidationError(
                    "--actual-git-sha is required for official execution"
                )
            if not args.tester_profiles_dir:
                raise RegistryValidationError(
                    "--tester-profiles-dir is required for official execution"
                )
            result = execute_official_campaign(
                args.campaign_lock,
                args.attestation,
                args.config_root,
                args.output_dir,
                actual_git_sha=args.actual_git_sha,
                terminal=args.terminal,
                tester_profiles_dir=args.tester_profiles_dir,
                registry_db=args.registry,
                runs_dir=args.runs_dir,
                timeout_seconds=args.timeout_seconds,
            )
        else:
            result = prepare_official_campaign(
                args.campaign_lock,
                args.attestation,
                args.config_root,
                args.output_dir,
                actual_git_sha=args.actual_git_sha,
            )
    except RegistryValidationError as exc:
        parser.error(str(exc))
        return

    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
