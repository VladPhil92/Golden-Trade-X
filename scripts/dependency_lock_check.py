#!/usr/bin/env python3
"""Fail closed when the official campaign dependency lock becomes non-exact or drifts."""

from __future__ import annotations

import re
from pathlib import Path

REQ_RE = re.compile(r"^([A-Za-z0-9_.-]+)(~=|==)([^;\s]+)(?:;\s*(.+))?$")
ALLOWED_MARKER = 'platform_system == "Windows"'


def _lines(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def validate_dependency_lock(
    requirements_path: str | Path = "requirements.txt",
    lock_path: str | Path = "config/campaign_requirements.lock",
) -> list[str]:
    failures: list[str] = []
    requirements = Path(requirements_path)
    lock = Path(lock_path)
    if not requirements.is_file():
        return [f"requirements file missing: {requirements}"]
    if not lock.is_file():
        return [f"campaign dependency lock missing: {lock}"]

    declared: dict[str, tuple[str, str | None]] = {}
    for raw in _lines(requirements):
        if raw.startswith(("-", "http://", "https://", "git+")):
            failures.append(f"unsupported requirements directive/source: {raw}")
            continue
        match = REQ_RE.fullmatch(raw)
        if not match:
            failures.append(f"unsupported requirement syntax: {raw}")
            continue
        name, _operator, version, marker = match.groups()
        key = name.lower().replace("_", "-")
        if key in declared:
            failures.append(f"duplicate declared dependency: {name}")
        if marker and marker.strip() != ALLOWED_MARKER:
            failures.append(f"unsupported environment marker for {name}: {marker}")
        declared[key] = (version, marker.strip() if marker else None)

    locked: dict[str, tuple[str, str | None]] = {}
    for raw in _lines(lock):
        if raw.startswith(("-", "http://", "https://", "git+")):
            failures.append(f"campaign lock forbids directives/URLs: {raw}")
            continue
        match = REQ_RE.fullmatch(raw)
        if not match:
            failures.append(f"unsupported campaign lock syntax: {raw}")
            continue
        name, operator, version, marker = match.groups()
        key = name.lower().replace("_", "-")
        if operator != "==":
            failures.append(f"campaign lock requires exact == pin: {raw}")
        if key in locked:
            failures.append(f"duplicate locked dependency: {name}")
        if marker and marker.strip() != ALLOWED_MARKER:
            failures.append(f"unsupported campaign lock marker for {name}: {marker}")
        locked[key] = (version, marker.strip() if marker else None)

    missing = sorted(set(declared) - set(locked))
    extra = sorted(set(locked) - set(declared))
    if missing:
        failures.append("dependencies missing from campaign lock: " + ", ".join(missing))
    if extra:
        failures.append("campaign lock contains undeclared dependencies: " + ", ".join(extra))

    for key in sorted(set(declared) & set(locked)):
        declared_marker = declared[key][1]
        locked_marker = locked[key][1]
        if declared_marker != locked_marker:
            failures.append(f"environment marker drift for {key}")

    return failures


def main() -> None:
    failures = validate_dependency_lock()
    if failures:
        for row in failures:
            print(f"FAIL: {row}")
        raise SystemExit(1)
    print("DEPENDENCY LOCK PASS — campaign dependencies are exact, complete, and source-safe")


if __name__ == "__main__":
    main()
