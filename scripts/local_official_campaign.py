#!/usr/bin/env python3
"""Run the official XM validation campaign locally on Windows.

This is the canonical local orchestrator. PowerShell is intentionally kept as a
thin launcher so Windows PowerShell 5.1 parsing/scoping cannot affect campaign
state or evidence generation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.experiment_registry import RegistryValidationError
    from scripts.local_mt5_runtime_context import inspect_local_mt5
    from scripts.mt5_environment_probe import create_mt5_environment_attestation
    from scripts.official_campaign_evidence_check import validate_l4_evidence
    from scripts.official_campaign_freeze import freeze_official_campaign
    from scripts.official_campaign_runner import execute_official_campaign
    from scripts.pre_campaign_readiness import evaluate_campaign_readiness
except ModuleNotFoundError:
    from experiment_registry import RegistryValidationError
    from local_mt5_runtime_context import inspect_local_mt5
    from mt5_environment_probe import create_mt5_environment_attestation
    from official_campaign_evidence_check import validate_l4_evidence
    from official_campaign_freeze import freeze_official_campaign
    from official_campaign_runner import execute_official_campaign
    from pre_campaign_readiness import evaluate_campaign_readiness


_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_ERROR_RE = re.compile(r"(?im)(^|\s)([1-9][0-9]*)\s+errors?\b")
_ZERO_ERRORS_RE = re.compile(r"(?im)\b0\s+errors?\b")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(
    args: list[str],
    *,
    cwd: Path,
    label: str,
    check: bool = True,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    print(f"\n== {label} ==", flush=True)
    result = subprocess.run(
        args,
        cwd=cwd,
        check=False,
        text=True,
        capture_output=capture,
    )
    if capture:
        if result.stdout:
            print(result.stdout.rstrip())
        if result.stderr:
            print(result.stderr.rstrip(), file=sys.stderr)
    if check and result.returncode != 0:
        raise RegistryValidationError(
            f"{label} failed with exit code {result.returncode}"
        )
    return result


def _git_sha(repo: Path) -> str:
    for args, label in (
        (["git", "diff", "--quiet"], "tracked worktree cleanliness"),
        (["git", "diff", "--cached", "--quiet"], "Git index cleanliness"),
    ):
        result = subprocess.run(args, cwd=repo, check=False)
        if result.returncode != 0:
            raise RegistryValidationError(
                f"{label} check failed; commit/stash/revert tracked changes before official execution"
            )

    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=False,
        text=True,
        capture_output=True,
    )
    sha = result.stdout.strip().lower()
    if result.returncode != 0 or not _SHA_RE.fullmatch(sha):
        raise RegistryValidationError("could not resolve a full Git commit SHA")
    return sha


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RegistryValidationError(f"invalid JSON file: {path}") from exc
    if not isinstance(payload, dict):
        raise RegistryValidationError(f"JSON root must be an object: {path}")
    return payload


def _read_compile_log(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-16", "utf-8-sig", "utf-8", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise RegistryValidationError(f"unable to decode MetaEditor compile log: {path}")


def _find_metaeditor(terminal: Path) -> Path:
    for name in ("metaeditor64.exe", "MetaEditor64.exe", "metaeditor.exe", "MetaEditor.exe"):
        candidate = terminal.parent / name
        if candidate.is_file():
            return candidate
    raise RegistryValidationError(
        f"MetaEditor was not found beside the running MT5 terminal: {terminal.parent}"
    )


def _quote_metaeditor_value(value: Path) -> str:
    """Quote a MetaEditor switch value using the CLI syntax documented by MetaQuotes."""

    return f'"{value}"'


def _metaeditor_command_line(
    *,
    metaeditor: Path,
    source: Path,
    mql5_root: Path,
    portable_mode: bool,
) -> str:
    executable = f'"{metaeditor}"'
    command = (
        f"{executable} "
        f"/compile:{_quote_metaeditor_value(source)} "
        f"/include:{_quote_metaeditor_value(mql5_root)} "
        "/log"
    )
    if portable_mode:
        command += " /portable"
    return command


def _ensure_target_metaeditor_not_running(metaeditor: Path) -> None:
    """Refuse to compile through a pre-existing target MetaEditor instance.

    MetaEditor is single-instance. Reusing an already-open editor can turn a CLI
    compile request into a silent no-op, but force-killing editors risks losing
    unsaved work. Detect only the editor executable that belongs to this MT5
    installation and fail with an actionable instruction instead.
    """

    if platform.system() != "Windows":
        return

    target = str(metaeditor.resolve()).replace("'", "''")
    ps_command = (
        f"$target='{target}'; "
        "$p=@(Get-Process metaeditor64,metaeditor -ErrorAction SilentlyContinue | "
        "Where-Object { $_.Path -and $_.Path -ieq $target }); "
        "$p | Select-Object -ExpandProperty Id"
    )
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            ps_command,
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RegistryValidationError(
            "could not safely determine whether the target MetaEditor is already running"
        )

    pids = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if pids:
        raise RegistryValidationError(
            "TARGET_METAEDITOR_ALREADY_RUNNING: close the MetaEditor window that "
            f"belongs to {metaeditor.parent} and rerun. Keep the XM MT5 terminal open."
        )


def _compile_log_excerpt(text: str, *, max_lines: int = 20) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    error_lines = [line for line in lines if re.search(r"(?i)\berror\b", line)]
    selected = error_lines if error_lines else lines[-max_lines:]
    return "\n".join(selected[:max_lines])


def _write_compile_diagnostic(
    path: Path,
    *,
    status: str,
    message: str,
    metaeditor: Path,
    command_line: str,
    source: Path,
    source_log: Path,
    ex5: Path,
    exit_code: int,
    started_at: datetime,
    process_stdout: str = "",
    process_stderr: str = "",
    compiler_log_excerpt: str = "",
) -> None:
    payload = {
        "schema_version": 1,
        "methodology": "LOCAL_METAEDITOR_CLI_DIAGNOSTIC_V1",
        "status": status,
        "message": message,
        "metaeditor_path": str(metaeditor),
        "command_line": command_line,
        "metaeditor_exit_code": exit_code,
        "process_stdout": process_stdout,
        "process_stderr": process_stderr,
        "compiler_log_excerpt": compiler_log_excerpt,
        "source_path": str(source),
        "source_log_path": str(source_log),
        "source_log_present": source_log.is_file(),
        "ex5_path": str(ex5),
        "ex5_present": ex5.is_file(),
        "started_at_utc": started_at.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "live_trading_authorized": False,
        "real_capital_authorized": False,
    }
    _write_json(path, payload)


def _compile_exact_build(
    *,
    repo: Path,
    terminal: Path,
    data_path: Path,
    portable_mode: bool,
    compile_log: Path,
    build_id: str,
) -> tuple[Path, Path]:
    mql5_root = data_path / "MQL5"
    standard_trade = mql5_root / "Include" / "Trade" / "Trade.mqh"
    if not standard_trade.is_file():
        raise RegistryValidationError(
            f"MT5 standard library not found under local data path: {standard_trade}"
        )

    custom_include_dst = mql5_root / "Include" / "GoldenTradeX"
    expert_dst = mql5_root / "Experts" / "GoldenTradeX"
    custom_include_dst.mkdir(parents=True, exist_ok=True)
    expert_dst.mkdir(parents=True, exist_ok=True)

    source_include = repo / "MQL5" / "Include" / "GoldenTradeX"
    source_expert = repo / "MQL5" / "Experts" / "GoldenTradeX"
    shutil.copytree(source_include, custom_include_dst, dirs_exist_ok=True)
    shutil.copytree(source_expert, expert_dst, dirs_exist_ok=True)

    source = expert_dst / "GoldenTradeX.mq5"
    ex5 = source.with_suffix(".ex5")
    source_log = source.with_suffix(".log")
    metaeditor = _find_metaeditor(terminal)
    compile_log.parent.mkdir(parents=True, exist_ok=True)

    # MetaEditor documents /log as a flag and /compile:"<path>" /
    # include:"<path>" with quoted switch values. Use the exact CLI form
    # because the local Windows profile path can contain spaces.
    for stale in (ex5, source_log, compile_log):
        try:
            stale.unlink()
        except FileNotFoundError:
            pass

    diagnostic_path = compile_log.with_suffix(".diagnostic.json")
    try:
        diagnostic_path.unlink()
    except FileNotFoundError:
        pass

    command_line = _metaeditor_command_line(
        metaeditor=metaeditor,
        source=source,
        mql5_root=mql5_root,
        portable_mode=portable_mode,
    )

    print("\n== Compile exact local Git build in XM MT5 data tree ==", flush=True)
    print("Checking target MetaEditor single-instance state; XM MT5 remains running.", flush=True)
    _ensure_target_metaeditor_not_running(metaeditor)

    started_at = datetime.now(timezone.utc)
    completed = subprocess.run(
        command_line,
        check=False,
        text=True,
        capture_output=True,
    )
    process_stdout = completed.stdout or ""
    process_stderr = completed.stderr or ""
    print(f"MetaEditor exit code: {completed.returncode}", flush=True)

    # A non-zero MetaEditor process code is not enough diagnostic evidence by
    # itself. MetaEditor may still flush <source>.log after the process exits.
    # Always give that log a bounded capture window before classifying the failure.
    process_failed = completed.returncode != 0
    deadline = time.monotonic() + (15.0 if process_failed else 60.0)
    ex5_seen_at: float | None = None
    while time.monotonic() < deadline:
        if source_log.is_file():
            try:
                candidate_text = _read_compile_log(source_log)
            except (OSError, RegistryValidationError):
                candidate_text = ""
            if candidate_text and (
                _ERROR_RE.search(candidate_text)
                or _ZERO_ERRORS_RE.search(candidate_text)
                or process_failed
            ):
                break

        if ex5.is_file() and ex5_seen_at is None:
            ex5_seen_at = time.monotonic()

        if not process_failed and ex5.is_file() and (
            source_log.is_file()
            or (
                ex5_seen_at is not None
                and time.monotonic() - ex5_seen_at >= 3.0
            )
        ):
            break
        time.sleep(0.5)

    compile_text = ""
    compile_excerpt = ""
    if source_log.is_file():
        shutil.copy2(source_log, compile_log)
        compile_text = _read_compile_log(compile_log)
        compile_excerpt = _compile_log_excerpt(compile_text)

    # Compiler evidence has precedence over the process exit code. This is the
    # path needed on XM installations where MetaEditor returns 1 and writes the
    # actual MQL5 error only to the source log.
    if compile_text and _ERROR_RE.search(compile_text):
        if compile_excerpt:
            print("---- MetaEditor compiler error excerpt ----", flush=True)
            print(compile_excerpt, flush=True)
            print("------------------------------------------", flush=True)
        message = f"MQL5 compilation reported errors. See {compile_log}"
        _write_compile_diagnostic(
            diagnostic_path,
            status="MQL5_COMPILE_ERRORS",
            message=message,
            metaeditor=metaeditor,
            command_line=command_line,
            source=source,
            source_log=source_log,
            ex5=ex5,
            exit_code=completed.returncode,
            started_at=started_at,
            process_stdout=process_stdout,
            process_stderr=process_stderr,
            compiler_log_excerpt=compile_excerpt,
        )
        raise RegistryValidationError(
            f"{message}. Diagnostic: {diagnostic_path}"
        )

    if process_failed:
        if compile_text:
            status = "METAEDITOR_PROCESS_FAILED_WITH_LOG"
            message = (
                f"MetaEditor exited with code {completed.returncode}. "
                f"Compiler log captured at {compile_log}"
            )
            if compile_excerpt:
                print("---- MetaEditor compiler log excerpt ----", flush=True)
                print(compile_excerpt, flush=True)
                print("----------------------------------------", flush=True)
        else:
            status = "METAEDITOR_PROCESS_FAILED_NO_LOG"
            message = (
                f"MetaEditor exited with code {completed.returncode} and did not "
                "produce a source compilation log"
            )
        _write_compile_diagnostic(
            diagnostic_path,
            status=status,
            message=message,
            metaeditor=metaeditor,
            command_line=command_line,
            source=source,
            source_log=source_log,
            ex5=ex5,
            exit_code=completed.returncode,
            started_at=started_at,
            process_stdout=process_stdout,
            process_stderr=process_stderr,
            compiler_log_excerpt=compile_excerpt,
        )
        raise RegistryValidationError(
            f"{message}. Diagnostic: {diagnostic_path}"
        )

    log_status = "UNAVAILABLE_FRESH_EX5_FALLBACK"
    if compile_text:
        if not _ZERO_ERRORS_RE.search(compile_text):
            message = "compile log exists but lacks explicit 0 errors result"
            _write_compile_diagnostic(
                diagnostic_path,
                status="MQL5_COMPILE_LOG_INDETERMINATE",
                message=message,
                metaeditor=metaeditor,
                command_line=command_line,
                source=source,
                source_log=source_log,
                ex5=ex5,
                exit_code=completed.returncode,
                started_at=started_at,
                process_stdout=process_stdout,
                process_stderr=process_stderr,
                compiler_log_excerpt=compile_excerpt,
            )
            raise RegistryValidationError(
                f"{message}. See {compile_log}. Diagnostic: {diagnostic_path}"
            )
        log_status = "VERIFIED_0_ERRORS"

    if not ex5.is_file():
        if source_log.is_file():
            message = (
                "MetaEditor reported 0 errors but did not create the compiled EX5 artifact"
            )
            status = "METAEDITOR_NO_EX5_AFTER_ZERO_ERRORS"
        else:
            message = (
                "METAEDITOR_CLI_NOOP: MetaEditor exited with code 0 but produced "
                "neither a compilation log nor an EX5 artifact"
            )
            status = "METAEDITOR_CLI_NOOP"
        _write_compile_diagnostic(
            diagnostic_path,
            status=status,
            message=message,
            metaeditor=metaeditor,
            command_line=command_line,
            source=source,
            source_log=source_log,
            ex5=ex5,
            exit_code=completed.returncode,
            started_at=started_at,
        )
        raise RegistryValidationError(
            f"{message}. Diagnostic: {diagnostic_path}"
        )

    attestation_path = compile_log.with_suffix(".attestation.json")
    attestation = {
        "schema_version": 1,
        "methodology": "LOCAL_METAEDITOR_COMPILE_ATTESTATION_V2",
        "build_id": build_id,
        "metaeditor_path": str(metaeditor),
        "metaeditor_exit_code": completed.returncode,
        "portable_mode": portable_mode,
        "source_path": str(source),
        "source_sha256": _sha256_file(source),
        "ex5_path": str(ex5),
        "ex5_sha256": _sha256_file(ex5),
        "ex5_size_bytes": ex5.stat().st_size,
        "source_log_path": str(source_log),
        "source_log_present": source_log.is_file(),
        "log_status": log_status,
        "started_at_utc": started_at.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "live_trading_authorized": False,
        "real_capital_authorized": False,
    }
    _write_json(attestation_path, attestation)

    if log_status == "VERIFIED_0_ERRORS":
        print("MQL5 LOCAL COMPILE PASS — log verified, 0 errors", flush=True)
    else:
        print(
            "MQL5 LOCAL COMPILE PASS — fresh EX5 verified; MetaEditor log unavailable",
            flush=True,
        )
    print(f"EX5 SHA256: {attestation['ex5_sha256']}", flush=True)
    return ex5, mql5_root


def _install_runtime(runtime_lock: Path, repo: Path) -> None:
    _run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "-r",
            str(runtime_lock),
        ],
        cwd=repo,
        label="Install frozen Python runtime",
    )


def _zip_tree(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for item in source.rglob("*"):
            if item.is_file():
                archive.write(item, item.relative_to(source))


def run_local_campaign(
    *,
    repo: Path,
    campaign_config: Path,
    terminal: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    if platform.system() != "Windows":
        raise RegistryValidationError("local official MT5 campaign is supported only on Windows")
    if timeout_seconds < 60 or timeout_seconds > 7200:
        raise RegistryValidationError("timeout_seconds must be in [60, 7200]")
    if not terminal.is_file():
        raise RegistryValidationError(f"MetaTrader terminal not found: {terminal}")
    if not campaign_config.is_file():
        raise RegistryValidationError(f"campaign config not found: {campaign_config}")

    git_sha = _git_sha(repo)
    campaign = _load_json(campaign_config)
    config_root = campaign_config.parent

    campaign_id = campaign.get("campaign_id")
    if not isinstance(campaign_id, str) or not campaign_id.strip():
        raise RegistryValidationError("campaign_id is required")

    env_raw = campaign.get("execution_environment_path")
    runtime_raw = campaign.get("python_runtime_lock_path")
    if not isinstance(env_raw, str) or not isinstance(runtime_raw, str):
        raise RegistryValidationError("campaign execution/runtime paths are required")
    environment_path = (config_root / env_raw).resolve()
    runtime_lock = (config_root / runtime_raw).resolve()
    if not environment_path.is_file():
        raise RegistryValidationError(
            f"execution environment contract not found: {environment_path}"
        )
    if not runtime_lock.is_file():
        raise RegistryValidationError(f"campaign runtime lock not found: {runtime_lock}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_root = (
        repo
        / "data"
        / "research"
        / "official_campaign-local"
        / f"{campaign_id}-{stamp}"
    )
    freeze_dir = run_root / "freeze"
    execution_dir = run_root / "execution"
    runs_dir = run_root / "runs"
    registry = run_root / "experiments.sqlite"
    readiness_path = run_root / "pre_campaign_readiness.json"
    runtime_context_path = run_root / "runtime_context.json"
    attestation_path = run_root / "environment_attestation.json"
    completion_path = run_root / "l4_completion.json"
    compile_log = run_root / "GoldenTradeX-local-compile.log"
    run_root.mkdir(parents=True, exist_ok=True)

    print("Golden Trade X — LOCAL OFFICIAL XM CAMPAIGN")
    print(f"Campaign: {campaign_id}")
    print(f"Git SHA:  {git_sha}")
    print(f"Terminal: {terminal}")
    print(f"Output:   {run_root}")
    print()
    print("This runner reuses the DEMO account already logged into MT5.")
    print("It does not request or write your MT5 password or account login.")

    print("\n== Pre-campaign readiness ==", flush=True)
    readiness = evaluate_campaign_readiness(
        campaign_config,
        repo / "MQL5" / "Include" / "GoldenTradeX" / "EconomicCalendarData.mqh",
    )
    _write_json(readiness_path, readiness)
    if readiness.get("decision") != "READY_TO_FREEZE" or readiness.get("ready") is not True:
        raise RegistryValidationError(
            "pre-campaign readiness did not return READY_TO_FREEZE"
        )
    print("PRE-CAMPAIGN READINESS PASS — READY_TO_FREEZE", flush=True)

    print("\n== Freeze official campaign ==", flush=True)
    lock = freeze_official_campaign(
        campaign_config,
        freeze_dir,
        build_id_override=git_sha,
    )
    if lock.get("status") != "OFFICIAL_CAMPAIGN_FROZEN":
        raise RegistryValidationError(
            "campaign freeze did not produce OFFICIAL_CAMPAIGN_FROZEN"
        )
    campaign_lock = freeze_dir / "campaign_lock.json"
    print("OFFICIAL CAMPAIGN FREEZE PASS", flush=True)

    _install_runtime(runtime_lock, repo)

    print("\n== Inspect existing local MT5 DEMO session ==", flush=True)
    runtime_context = inspect_local_mt5(terminal, runtime_context_path)
    if (
        runtime_context.get("trade_mode") != "DEMO"
        or runtime_context.get("terminal_connected") is not True
    ):
        raise RegistryValidationError(
            "local MT5 runtime is not a connected DEMO session"
        )
    print("LOCAL MT5 DEMO SESSION PASS", flush=True)

    data_path = Path(str(runtime_context["data_path"])).resolve()
    portable_mode = bool(runtime_context["portable_mode"])
    _, mql5_root = _compile_exact_build(
        repo=repo,
        terminal=terminal,
        data_path=data_path,
        portable_mode=portable_mode,
        compile_log=compile_log,
        build_id=git_sha,
    )
    tester_profiles = mql5_root / "Profiles" / "Tester"
    tester_profiles.mkdir(parents=True, exist_ok=True)

    print("\n== Attest exact XM DEMO environment from existing session ==", flush=True)
    attestation = create_mt5_environment_attestation(
        environment_path,
        terminal,
        attestation_path,
        runtime_portable_mode=portable_mode,
        reuse_existing_session=True,
    )
    if attestation.get("status") != "VERIFIED":
        raise RegistryValidationError("environment attestation did not return VERIFIED")
    print("XM DEMO ENVIRONMENT ATTESTATION PASS", flush=True)

    print("\n== Execute rolling IS to frozen OOS ==", flush=True)
    execution = execute_official_campaign(
        campaign_lock,
        attestation_path,
        config_root,
        execution_dir,
        actual_git_sha=git_sha,
        terminal=terminal,
        tester_profiles_dir=tester_profiles,
        registry_db=registry,
        runs_dir=runs_dir,
        timeout_seconds=timeout_seconds,
        runtime_portable_mode=portable_mode,
    )
    terminal_status = execution.get("status")
    if terminal_status not in {
        "OOS_PROMOTION_PASS_READY_FOR_ROBUSTNESS",
        "OOS_PROMOTION_REJECTED",
    }:
        raise RegistryValidationError(
            f"official campaign ended in unexpected status: {terminal_status}"
        )

    print("\n== Validate completed L4 OOS evidence ==", flush=True)
    completion = validate_l4_evidence(
        readiness_path=readiness_path,
        campaign_lock_path=campaign_lock,
        attestation_path=attestation_path,
        execution_manifest_path=execution_dir / "campaign_execution_manifest.json",
        oos_evidence_path=execution_dir / "oos_evidence_manifest.json",
        oos_summary_path=execution_dir / "oos_summary.json",
        promotion_decision_path=execution_dir / "oos_promotion_decision.json",
        output_path=completion_path,
    )

    zip_path = run_root.with_suffix(".zip")
    _zip_tree(run_root, zip_path)

    print("\nLOCAL OFFICIAL CAMPAIGN COMPLETE")
    print(f"Integrity:  {completion['status']}")
    print(f"OOS result: {completion['oos_terminal_status']}")
    print(f"Next stage: {completion['next_stage']}")
    print(f"Evidence ZIP: {zip_path}")
    print()
    print("Live trading authorized: false")
    print("Real capital authorized: false")
    return completion


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--campaign-config",
        default="config/official_validation_campaign.xm_gold.json",
    )
    parser.add_argument("--terminal", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    args = parser.parse_args()

    repo = Path.cwd().resolve()
    if not (repo / ".git").exists():
        parser.error("run this command from the Golden-Trade-X repository root")
    campaign = (repo / args.campaign_config).resolve()
    terminal = Path(args.terminal).resolve()

    try:
        run_local_campaign(
            repo=repo,
            campaign_config=campaign,
            terminal=terminal,
            timeout_seconds=args.timeout_seconds,
        )
    except (RegistryValidationError, OSError, subprocess.SubprocessError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
