from __future__ import annotations

from pathlib import Path

from scripts.local_official_campaign import _read_compile_log


def test_read_compile_log_accepts_utf16(tmp_path: Path) -> None:
    path = tmp_path / "compile.log"
    path.write_text("Result: 0 errors, 0 warnings\n", encoding="utf-16")
    assert "0 errors" in _read_compile_log(path)


def test_read_compile_log_accepts_utf8(tmp_path: Path) -> None:
    path = tmp_path / "compile.log"
    path.write_text("Result: 0 errors, 0 warnings\n", encoding="utf-8")
    assert "0 errors" in _read_compile_log(path)
