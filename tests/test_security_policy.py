from pathlib import Path

from scripts.dependency_lock_check import validate_dependency_lock
from scripts.workflow_security_policy_check import validate_workflow_security


def test_repository_dependency_lock_is_exact_and_complete() -> None:
    assert validate_dependency_lock() == []


def test_dependency_lock_rejects_ranges_urls_missing_and_marker_drift(tmp_path: Path) -> None:
    requirements = tmp_path / "requirements.txt"
    lock = tmp_path / "lock.txt"
    requirements.write_text(
        'requests~=2.34\nMetaTrader5~=5.0; platform_system == "Windows"\n',
        encoding="utf-8",
    )
    lock.write_text(
        'requests~=2.34\nhttps://example.invalid/pkg.whl\nMetaTrader5==5.0.6147; python_version > "3"\nextra==1.0\n',
        encoding="utf-8",
    )
    failures = validate_dependency_lock(requirements, lock)
    joined = "\n".join(failures)
    assert "requires exact == pin" in joined
    assert "forbids directives/URLs" in joined
    assert "unsupported campaign lock marker" in joined
    assert "campaign lock contains undeclared dependencies" in joined
    assert "environment marker drift" in joined


def test_dependency_lock_rejects_missing_files(tmp_path: Path) -> None:
    assert "requirements file missing" in validate_dependency_lock(tmp_path / "missing", tmp_path / "lock")[0]
    req = tmp_path / "requirements.txt"
    req.write_text("requests~=2.34\n", encoding="utf-8")
    assert "campaign dependency lock missing" in validate_dependency_lock(req, tmp_path / "missing-lock")[0]


def test_repository_workflows_satisfy_security_policy() -> None:
    assert validate_workflow_security() == []


def test_workflow_policy_rejects_unsafe_triggers_permissions_secrets_and_uploads(tmp_path: Path) -> None:
    root = tmp_path / "workflows"
    root.mkdir()
    (root / "unsafe.yml").write_text(
        """name: unsafe
on:
  pull_request_target:
permissions: write-all
jobs:
  bad:
    permissions:
      contents: write
    steps:
      - run: echo ${{ secrets.PASSWORD }}
      - uses: actions/upload-artifact@0123456789012345678901234567890123456789
        with:
          path: out.txt
""",
        encoding="utf-8",
    )
    failures = "\n".join(validate_workflow_security(root))
    assert "pull_request_target is forbidden" in failures
    assert "permissions write-all is forbidden" in failures
    assert "unauthorized write permission: contents" in failures
    assert "secrets must be passed via env" in failures
    assert "upload-artifact missing retention-days" in failures
    assert "upload-artifact missing if-no-files-found policy" in failures


def test_workflow_policy_requires_top_level_permissions(tmp_path: Path) -> None:
    root = tmp_path / "workflows"
    root.mkdir()
    (root / "missing.yml").write_text("name: x\non: push\njobs:\n  x:\n    runs-on: ubuntu-latest\n", encoding="utf-8")
    failures = validate_workflow_security(root)
    assert any("missing top-level permissions boundary" in item for item in failures)
