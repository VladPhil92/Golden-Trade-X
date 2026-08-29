#!/usr/bin/env python3
"""Reject mutable third-party GitHub Action references in repository workflows."""

from __future__ import annotations

import re
from pathlib import Path

PIN_RE = re.compile(r"^\s*-?\s*uses:\s*([^\s#]+)(?:\s+#.*)?$")
SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")


def find_unpinned_actions(workflow_root: str | Path = ".github/workflows") -> list[str]:
    root = Path(workflow_root)
    failures: list[str] = []
    for path in sorted(root.glob("*.y*ml")):
        for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = PIN_RE.match(raw)
            if not match:
                continue
            target = match.group(1)
            if target.startswith("./"):
                continue
            if "@" not in target:
                failures.append(f"{path}:{line_no}: action reference has no @ pin: {target}")
                continue
            action, ref = target.rsplit("@", 1)
            if not action or not SHA_RE.fullmatch(ref):
                failures.append(f"{path}:{line_no}: mutable action ref: {target}")
    return failures


def main() -> None:
    failures = find_unpinned_actions()
    if failures:
        for row in failures:
            print(f"FAIL: {row}")
        raise SystemExit(1)
    print("WORKFLOW SUPPLY-CHAIN PASS — all third-party actions pinned to full commit SHAs")


if __name__ == "__main__":
    main()
