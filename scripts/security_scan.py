#!/usr/bin/env python3
"""Fail-closed scan for high-risk credential material in tracked repository files."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")),
    ("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("Telegram bot token", re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b")),
)

ALLOWED_BASENAMES = {".env.example"}
SKIP_SUFFIXES = {".ex5", ".zip", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf"}


def tracked_files(root: Path = ROOT) -> list[Path]:
    proc = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        capture_output=True,
        check=True,
    )
    return [root / item.decode("utf-8") for item in proc.stdout.split(b"\0") if item]


def scan_text(text: str) -> list[str]:
    findings: list[str] = []
    for label, pattern in PATTERNS:
        if pattern.search(text):
            findings.append(label)
    return findings


def scan_path(path: Path, root: Path = ROOT) -> list[str]:
    relative = path.relative_to(root).as_posix()
    findings: list[str] = []

    if path.name == ".env":
        findings.append(f"{relative}: tracked .env file")
        return findings

    if path.name in ALLOWED_BASENAMES or path.suffix.lower() in SKIP_SUFFIXES:
        return findings

    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return findings

    for label in scan_text(text):
        findings.append(f"{relative}: suspected {label}")
    return findings


def scan_repository(root: Path = ROOT) -> list[str]:
    findings: list[str] = []
    for path in tracked_files(root):
        if path.is_file():
            findings.extend(scan_path(path, root))
    return findings


def main() -> int:
    findings = scan_repository()
    if findings:
        print("SECURITY SCAN FAILED")
        for finding in findings:
            print(f"- {finding}")
        print("Rotate any exposed credential and remove it from repository history as needed.")
        return 1

    print("SECURITY SCAN PASS — no tracked high-risk credential patterns detected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
