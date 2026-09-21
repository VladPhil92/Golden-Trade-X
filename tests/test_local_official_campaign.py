from __future__ import annotations

import json
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace

import pytest

from scripts.experiment_registry import RegistryValidationError
from scripts import local_official_campaign as local_campaign
from scripts.local_official_campaign import _read_compile_log


def test_read_compile_log_accepts_utf16(tmp_path: Path) -> None:
    path = tmp_path / "compile.log"
    path.write_text("Result: 0 errors, 0 warnings\n", encoding="utf-16")
    assert "0 errors" in _read_compile_log(path)


def test_read_compile_log_accepts_utf8(tmp_path: Path) -> None:
    path = tmp_path / "compile.log"
    path.write_text("Result: 0 errors, 0 warnings\n", encoding="utf-8")
    assert "0 errors" in _read_compile_log(path)


def _compile_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    repo = tmp_path / "repo"
    (repo / "MQL5" / "Include" / "GoldenTradeX").mkdir(parents=True)
    (repo / "MQL5" / "Experts" / "GoldenTradeX").mkdir(parents=True)
    (repo / "MQL5" / "Include" / "GoldenTradeX" / "Dummy.mqh").write_text(
        "// include\n",
        encoding="utf-8",
    )
    (repo / "MQL5" / "Experts" / "GoldenTradeX" / "GoldenTradeX.mq5").write_text(
        "#property strict\nvoid OnTick(){}\n",
        encoding="utf-8",
    )

    data_path = tmp_path / "terminal-data"
    (data_path / "MQL5" / "Include" / "Trade").mkdir(parents=True)
    (data_path / "MQL5" / "Include" / "Trade" / "Trade.mqh").write_text(
        "// standard\n",
        encoding="utf-8",
    )

    install = tmp_path / "install"
    install.mkdir()
    terminal = install / "terminal64.exe"
    terminal.write_bytes(b"terminal")
    (install / "metaeditor64.exe").write_bytes(b"metaeditor")
    return repo, data_path, terminal


def _source_from_command_line(command: str) -> Path:
    prefix = '/compile:"'
    assert prefix in command
    return Path(command.split(prefix, 1)[1].split('"', 1)[0])


def test_metaeditor_command_line_quotes_paths_with_spaces() -> None:
    command = local_campaign._metaeditor_command_line(
        metaeditor=PureWindowsPath(r"C:\Program Files\XM MT5\metaeditor64.exe"),
        source=PureWindowsPath(
            r"C:\Users\JUAN PABLO\AppData\Roaming\MetaQuotes\Terminal\ABC\MQL5\Experts\GoldenTradeX\GoldenTradeX.mq5"
        ),
        mql5_root=PureWindowsPath(
            r"C:\Users\JUAN PABLO\AppData\Roaming\MetaQuotes\Terminal\ABC\MQL5"
        ),
        portable_mode=False,
    )

    assert command.startswith('"C:\\Program Files\\XM MT5\\metaeditor64.exe" ')
    assert '/compile:"C:\\Users\\JUAN PABLO\\' in command
    assert '/include:"C:\\Users\\JUAN PABLO\\' in command
    assert command.endswith(" /log")


def test_target_metaeditor_detection_fails_closed_without_killing_processes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install = tmp_path / "XM MT5"
    install.mkdir()
    metaeditor = install / "metaeditor64.exe"
    metaeditor.write_bytes(b"metaeditor")

    monkeypatch.setattr(local_campaign.platform, "system", lambda: "Windows")

    captured: dict[str, object] = {}

    def fake_run(command, check=False, text=False, capture_output=False):
        captured["command"] = command
        return SimpleNamespace(returncode=0, stdout="12345\n", stderr="")

    monkeypatch.setattr(local_campaign.subprocess, "run", fake_run)

    with pytest.raises(
        RegistryValidationError,
        match="TARGET_METAEDITOR_ALREADY_RUNNING",
    ):
        local_campaign._ensure_target_metaeditor_not_running(metaeditor)

    command = captured["command"]
    assert isinstance(command, list)
    assert command[0] == "powershell.exe"
    assert "taskkill" not in " ".join(command).lower()


def test_compile_accepts_fresh_ex5_when_metaeditor_omits_log(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, data_path, terminal = _compile_fixture(tmp_path)
    evidence_log = tmp_path / "evidence" / "compile.log"

    def fake_run(
        command: str,
        check: bool = False,
        text: bool = False,
        capture_output: bool = False,
    ):  # noqa: ARG001
        source = _source_from_command_line(command)
        source.with_suffix(".ex5").write_bytes(b"fresh-ex5")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(local_campaign.subprocess, "run", fake_run)

    ex5, _ = local_campaign._compile_exact_build(
        repo=repo,
        terminal=terminal,
        data_path=data_path,
        portable_mode=False,
        compile_log=evidence_log,
        build_id="a" * 40,
    )

    assert ex5.is_file()
    attestation_path = evidence_log.with_suffix(".attestation.json")
    payload = json.loads(attestation_path.read_text(encoding="utf-8"))
    assert payload["log_status"] == "UNAVAILABLE_FRESH_EX5_FALLBACK"
    assert payload["source_log_present"] is False
    assert payload["metaeditor_exit_code"] == 0
    assert payload["build_id"] == "a" * 40
    assert len(payload["ex5_sha256"]) == 64


def test_compile_surfaces_reported_errors_even_when_ex5_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, data_path, terminal = _compile_fixture(tmp_path)
    evidence_log = tmp_path / "evidence" / "compile.log"

    def fake_run(
        command: str,
        check: bool = False,
        text: bool = False,
        capture_output: bool = False,
    ):  # noqa: ARG001
        source = _source_from_command_line(command)
        source.with_suffix(".log").write_text(
            "Result: 1 errors, 0 warnings\n",
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(local_campaign.subprocess, "run", fake_run)

    with pytest.raises(RegistryValidationError, match="reported errors"):
        local_campaign._compile_exact_build(
            repo=repo,
            terminal=terminal,
            data_path=data_path,
            portable_mode=False,
            compile_log=evidence_log,
            build_id="b" * 40,
        )


def test_compile_exit_one_surfaces_compiler_log_before_process_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, data_path, terminal = _compile_fixture(tmp_path)
    evidence_log = tmp_path / "evidence" / "compile.log"

    def fake_run(
        command: str,
        check: bool = False,
        text: bool = False,
        capture_output: bool = False,
    ):  # noqa: ARG001
        source = _source_from_command_line(command)
        source.with_suffix(".log").write_text(
            "GoldenTradeX.mq5(42,7) : error 256: undeclared identifier\n"
            "Result: 1 errors, 0 warnings\n",
            encoding="utf-8",
        )
        return SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="MetaEditor failed",
        )

    monkeypatch.setattr(local_campaign.subprocess, "run", fake_run)

    with pytest.raises(RegistryValidationError, match="reported errors"):
        local_campaign._compile_exact_build(
            repo=repo,
            terminal=terminal,
            data_path=data_path,
            portable_mode=False,
            compile_log=evidence_log,
            build_id="d" * 40,
        )

    assert evidence_log.is_file()
    diagnostic_path = evidence_log.with_suffix(".diagnostic.json")
    payload = json.loads(diagnostic_path.read_text(encoding="utf-8"))
    assert payload["status"] == "MQL5_COMPILE_ERRORS"
    assert payload["metaeditor_exit_code"] == 1
    assert "undeclared identifier" in payload["compiler_log_excerpt"]
    assert payload["process_stderr"] == "MetaEditor failed"


def test_compile_exit_one_without_log_is_classified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, data_path, terminal = _compile_fixture(tmp_path)
    evidence_log = tmp_path / "evidence" / "compile.log"

    monkeypatch.setattr(
        local_campaign.subprocess,
        "run",
        lambda command, check=False, text=False, capture_output=False: SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="",
        ),
    )
    clock = iter((0.0, 16.0))
    monkeypatch.setattr(local_campaign.time, "monotonic", lambda: next(clock))

    with pytest.raises(RegistryValidationError, match="did not produce a source compilation log"):
        local_campaign._compile_exact_build(
            repo=repo,
            terminal=terminal,
            data_path=data_path,
            portable_mode=False,
            compile_log=evidence_log,
            build_id="e" * 40,
        )

    diagnostic_path = evidence_log.with_suffix(".diagnostic.json")
    payload = json.loads(diagnostic_path.read_text(encoding="utf-8"))
    assert payload["status"] == "METAEDITOR_PROCESS_FAILED_NO_LOG"
    assert payload["metaeditor_exit_code"] == 1


def test_compile_classifies_exit_zero_without_artifacts_as_cli_noop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, data_path, terminal = _compile_fixture(tmp_path)
    evidence_log = tmp_path / "evidence" / "compile.log"

    monkeypatch.setattr(
        local_campaign.subprocess,
        "run",
        lambda command, check=False: SimpleNamespace(returncode=0),
    )
    clock = iter((0.0, 61.0))
    monkeypatch.setattr(local_campaign.time, "monotonic", lambda: next(clock))

    with pytest.raises(RegistryValidationError, match="METAEDITOR_CLI_NOOP"):
        local_campaign._compile_exact_build(
            repo=repo,
            terminal=terminal,
            data_path=data_path,
            portable_mode=False,
            compile_log=evidence_log,
            build_id="c" * 40,
        )

    diagnostic_path = evidence_log.with_suffix(".diagnostic.json")
    payload = json.loads(diagnostic_path.read_text(encoding="utf-8"))
    assert payload["status"] == "METAEDITOR_CLI_NOOP"
    assert payload["metaeditor_exit_code"] == 0
    assert payload["source_log_present"] is False
    assert payload["ex5_present"] is False
