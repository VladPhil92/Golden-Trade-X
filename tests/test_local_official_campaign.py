from __future__ import annotations

import json
from pathlib import Path
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


def test_compile_accepts_fresh_ex5_when_metaeditor_omits_log(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, data_path, terminal = _compile_fixture(tmp_path)
    evidence_log = tmp_path / "evidence" / "compile.log"

    def fake_run(command: list[str], check: bool = False):  # noqa: ARG001
        source_arg = next(item for item in command if item.startswith("/compile:"))
        source = Path(source_arg.split(":", 1)[1])
        source.with_suffix(".ex5").write_bytes(b"fresh-ex5")
        return SimpleNamespace(returncode=0)

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


def test_compile_rejects_reported_errors_even_when_ex5_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, data_path, terminal = _compile_fixture(tmp_path)
    evidence_log = tmp_path / "evidence" / "compile.log"

    def fake_run(command: list[str], check: bool = False):  # noqa: ARG001
        source_arg = next(item for item in command if item.startswith("/compile:"))
        source = Path(source_arg.split(":", 1)[1])
        source.with_suffix(".ex5").write_bytes(b"fresh-ex5")
        source.with_suffix(".log").write_text(
            "Result: 1 errors, 0 warnings\n",
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0)

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
