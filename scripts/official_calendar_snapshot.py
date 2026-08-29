#!/usr/bin/env python3
"""Verify immutable official calendar source snapshots before materialization.

This is the official snapshot boundary. It binds every BLS/Federal Reserve source
file to the capture manifest by exact URL, authority, year, filename, byte size,
and SHA-256 before parsing. It then cross-checks parsed event counts and annual
coverage against the capture manifest. No network fallback is permitted here.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

try:
    from scripts.materialize_official_calendar import (
        BLS_YEAR_URL,
        FED_CALENDAR_URL,
        FED_SNAPSHOT_NAME,
        CalendarMaterializationError,
        materialize_calendar,
    )
except ModuleNotFoundError:
    from materialize_official_calendar import (
        BLS_YEAR_URL,
        FED_CALENDAR_URL,
        FED_SNAPSHOT_NAME,
        CalendarMaterializationError,
        materialize_calendar,
    )

MANIFEST_NAME = "source_manifest.json"
MANIFEST_METHOD = "OFFICIAL_CALENDAR_SOURCE_SNAPSHOT_V1"


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _expected_sources(start_year: int, end_year: int) -> dict[str, dict[str, Any]]:
    expected: dict[str, dict[str, Any]] = {}
    for year in range(start_year, end_year + 1):
        name = f"bls-{year}.html"
        expected[name] = {
            "authority": "BLS",
            "year": year,
            "url": BLS_YEAR_URL.format(year=year),
        }
    expected[FED_SNAPSHOT_NAME] = {
        "authority": "FEDERAL_RESERVE",
        "year": None,
        "url": FED_CALENDAR_URL,
    }
    return expected


def load_and_verify_source_manifest(
    source_dir: str | Path,
    start_year: int,
    end_year: int,
) -> tuple[dict[str, Any], str]:
    root = Path(source_dir).resolve()
    if not root.is_dir():
        raise CalendarMaterializationError(f"source snapshot directory not found: {root}")
    manifest_path = (root / MANIFEST_NAME).resolve()
    try:
        manifest_path.relative_to(root)
    except ValueError as exc:  # pragma: no cover - defensive
        raise CalendarMaterializationError("source manifest escapes source directory") from exc
    if not manifest_path.is_file():
        raise CalendarMaterializationError(f"required source manifest not found: {manifest_path}")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CalendarMaterializationError(f"invalid source manifest: {manifest_path}") from exc
    if not isinstance(manifest, dict):
        raise CalendarMaterializationError("source manifest root must be an object")
    if manifest.get("schema_version") != 1:
        raise CalendarMaterializationError("source manifest schema_version must be 1")
    if manifest.get("methodology") != MANIFEST_METHOD:
        raise CalendarMaterializationError("unsupported source manifest methodology")
    if manifest.get("start_year") != start_year or manifest.get("end_year") != end_year:
        raise CalendarMaterializationError(
            f"source manifest range mismatch: expected {start_year}-{end_year}"
        )
    if manifest.get("approved") is not False:
        raise CalendarMaterializationError("source capture manifest must remain approved=false")
    if manifest.get("live_trading_authorized") is not False:
        raise CalendarMaterializationError("source manifest must deny live trading")
    if manifest.get("real_capital_authorized") is not False:
        raise CalendarMaterializationError("source manifest must deny real capital")
    authorities = manifest.get("source_authorities")
    if authorities != ["BLS", "FEDERAL_RESERVE"]:
        raise CalendarMaterializationError(
            "source manifest authorities must be exactly BLS,FEDERAL_RESERVE"
        )

    rows = manifest.get("sources")
    if not isinstance(rows, list):
        raise CalendarMaterializationError("source manifest sources must be an array")
    expected = _expected_sources(start_year, end_year)
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise CalendarMaterializationError("source manifest source row must be an object")
        name = row.get("snapshot_name")
        if not isinstance(name, str) or not name:
            raise CalendarMaterializationError("source manifest snapshot_name is required")
        if name in seen:
            raise CalendarMaterializationError(f"duplicate source manifest snapshot: {name}")
        seen.add(name)
        if name not in expected:
            raise CalendarMaterializationError(f"unexpected source manifest snapshot: {name}")
        contract = expected[name]
        if row.get("authority") != contract["authority"]:
            raise CalendarMaterializationError(f"source authority mismatch for {name}")
        if row.get("url") != contract["url"]:
            raise CalendarMaterializationError(f"source URL mismatch for {name}")
        if contract["year"] is not None and row.get("year") != contract["year"]:
            raise CalendarMaterializationError(f"source year mismatch for {name}")
        if contract["year"] is None and "year" in row and row.get("year") is not None:
            raise CalendarMaterializationError(f"Federal Reserve source must not carry a year: {name}")

        path = (root / name).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise CalendarMaterializationError(f"source snapshot escapes source directory: {name}") from exc
        if not path.is_file():
            raise CalendarMaterializationError(f"required source snapshot not found: {path}")
        raw = path.read_bytes()
        if not raw:
            raise CalendarMaterializationError(f"source snapshot is empty: {path}")
        expected_size = row.get("size_bytes")
        if isinstance(expected_size, bool) or not isinstance(expected_size, int) or expected_size <= 0:
            raise CalendarMaterializationError(f"invalid manifest size_bytes for {name}")
        if len(raw) != expected_size:
            raise CalendarMaterializationError(f"source snapshot size mismatch for {name}")
        expected_sha = row.get("sha256")
        if not isinstance(expected_sha, str) or len(expected_sha) != 64:
            raise CalendarMaterializationError(f"invalid manifest SHA-256 for {name}")
        if _sha256_bytes(raw) != expected_sha.lower():
            raise CalendarMaterializationError(f"source snapshot SHA-256 mismatch for {name}")
        parsed_count = row.get("parsed_event_count")
        if isinstance(parsed_count, bool) or not isinstance(parsed_count, int) or parsed_count <= 0:
            raise CalendarMaterializationError(f"invalid parsed_event_count for {name}")

    missing = sorted(set(expected) - seen)
    if missing:
        raise CalendarMaterializationError(
            "source manifest missing required snapshots: " + ", ".join(missing)
        )
    if len(rows) != len(expected):
        raise CalendarMaterializationError("source manifest contains duplicate/unexpected source rows")

    counts = manifest.get("counts_by_year")
    if not isinstance(counts, dict):
        raise CalendarMaterializationError("source manifest counts_by_year must be an object")
    if set(counts) != {str(year) for year in range(start_year, end_year + 1)}:
        raise CalendarMaterializationError("source manifest counts_by_year range mismatch")
    return manifest, _sha256_file(manifest_path)


def materialize_verified_snapshot(
    start_year: int,
    end_year: int,
    source_dir: str | Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest, manifest_sha = load_and_verify_source_manifest(source_dir, start_year, end_year)
    document, audit = materialize_calendar(
        start_year,
        end_year,
        approved=False,
        source_dir=source_dir,
    )

    if audit.get("counts_by_year") != manifest.get("counts_by_year"):
        raise CalendarMaterializationError("parsed annual counts differ from source manifest")

    source_rows = manifest["sources"]
    actual_counts: dict[str, int] = {}
    for row in audit["sources"]["bls"]:
        actual_counts[row["snapshot_name"]] = 24  # annual NFP+CPI count validated below
    # Derive exact parsed counts from annual audit rather than trusting source metadata.
    for year in range(start_year, end_year + 1):
        name = f"bls-{year}.html"
        counts = audit["counts_by_year"][str(year)]
        actual_counts[name] = int(counts["NFP"]) + int(counts["CPI"])
    actual_counts[FED_SNAPSHOT_NAME] = sum(
        int(audit["counts_by_year"][str(year)]["FOMC"])
        for year in range(start_year, end_year + 1)
    )
    for row in source_rows:
        name = row["snapshot_name"]
        if row["parsed_event_count"] != actual_counts[name]:
            raise CalendarMaterializationError(f"parsed_event_count mismatch for {name}")

    audit = dict(audit)
    audit["source_manifest"] = {
        "path": MANIFEST_NAME,
        "methodology": MANIFEST_METHOD,
        "sha256": manifest_sha,
    }
    audit["source_manifest_verified"] = True
    audit["approved"] = False
    audit["live_trading_authorized"] = False
    audit["real_capital_authorized"] = False
    return document, audit
