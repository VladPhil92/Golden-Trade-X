#!/usr/bin/env python3
"""Static security policy for GitHub Actions workflows."""

from __future__ import annotations

import re
from pathlib import Path

WRITE_RE = re.compile(r"^\s*([A-Za-z0-9_-]+):\s*write\s*(?:#.*)?$")
SECRET_RE = re.compile(r"\$\{\{\s*secrets\.", re.IGNORECASE)
ALLOWED_WRITES = {("security.yml", "security-events")}


def validate_workflow_security(workflow_root: str | Path = ".github/workflows") -> list[str]:
    root = Path(workflow_root)
    failures: list[str] = []
    for path in sorted(root.glob("*.y*ml")):
        lines = path.read_text(encoding="utf-8").splitlines()
        text = "\n".join(lines)
        if re.search(r"(?m)^\s*pull_request_target\s*:", text):
            failures.append(f"{path}: pull_request_target is forbidden")
        if re.search(r"(?m)^\s*permissions\s*:\s*write-all\s*$", text):
            failures.append(f"{path}: permissions write-all is forbidden")

        # Every workflow must define a top-level permission boundary before jobs.
        jobs_index = next((i for i, line in enumerate(lines) if line.startswith("jobs:")), None)
        prefix = lines[:jobs_index] if jobs_index is not None else lines
        has_permissions = any(line.startswith("permissions:") for line in prefix)
        if not has_permissions:
            failures.append(f"{path}: missing top-level permissions boundary")

        in_run_block = False
        run_indent = -1
        for line_no, raw in enumerate(lines, 1):
            stripped = raw.lstrip()
            indent = len(raw) - len(stripped)
            if in_run_block and stripped and indent <= run_indent:
                in_run_block = False
            if re.match(r"run:\s*(\||>)?\s*$", stripped):
                in_run_block = True
                run_indent = indent
            elif stripped.startswith("run:"):
                if SECRET_RE.search(stripped):
                    failures.append(f"{path}:{line_no}: secrets must be passed via env, not inline run")
            elif in_run_block and SECRET_RE.search(raw):
                failures.append(f"{path}:{line_no}: secrets must be passed via env, not run block")

            write = WRITE_RE.match(raw)
            if write:
                permission = write.group(1)
                if (path.name, permission) not in ALLOWED_WRITES:
                    failures.append(f"{path}:{line_no}: unauthorized write permission: {permission}")

        # Evidence uploads must be bounded and fail visibly when expected artifacts vanish.
        for idx, raw in enumerate(lines):
            if "actions/upload-artifact@" not in raw:
                continue
            window = "\n".join(lines[idx : min(len(lines), idx + 16)])
            if "retention-days:" not in window:
                failures.append(f"{path}:{idx + 1}: upload-artifact missing retention-days")
            if "if-no-files-found:" not in window:
                failures.append(f"{path}:{idx + 1}: upload-artifact missing if-no-files-found policy")

    return failures


def main() -> None:
    failures = validate_workflow_security()
    if failures:
        for row in failures:
            print(f"FAIL: {row}")
        raise SystemExit(1)
    print("WORKFLOW SECURITY POLICY PASS — least privilege, safe secrets, bounded artifacts")


if __name__ == "__main__":
    main()
