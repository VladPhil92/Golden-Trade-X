#!/usr/bin/env python3
"""Validate and materialize the immutable economic-calendar contract used by Golden Trade X.

The repository may retain heuristic NFP/CPI fallbacks for exploratory/demo work, but an
OFFICIAL validation campaign must reference an approved calendar contract and a generated
MQL5 include derived from exactly the same canonical event set.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EVENT_TYPES = {"NFP", "CPI", "FOMC"}
SCHEMA_VERSION = 1


class EconomicCalendarValidationError(ValueError):
    pass


def _load(path: str | Path) -> dict[str, Any]:
    target = Path(path).resolve()
    with target.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise EconomicCalendarValidationError("economic calendar root must be an object")
    return value


def _parse_utc(raw: Any) -> datetime:
    if not isinstance(raw, str) or not raw.endswith("Z"):
        raise EconomicCalendarValidationError(f"release_utc must be an ISO-8601 UTC timestamp: {raw!r}")
    try:
        parsed = datetime.fromisoformat(raw[:-1] + "+00:00")
    except ValueError as exc:
        raise EconomicCalendarValidationError(f"invalid release_utc: {raw!r}") from exc
    if parsed.tzinfo != timezone.utc:
        raise EconomicCalendarValidationError(f"release_utc is not UTC: {raw!r}")
    return parsed


def canonical_calendar_snapshot(document: dict[str, Any]) -> dict[str, Any]:
    if document.get("schema_version") != SCHEMA_VERSION:
        raise EconomicCalendarValidationError("economic calendar schema_version must be 1")
    calendar_id = document.get("calendar_id")
    approved = document.get("approved")
    if not isinstance(calendar_id, str) or not calendar_id.strip():
        raise EconomicCalendarValidationError("calendar_id is required")
    if not isinstance(approved, bool):
        raise EconomicCalendarValidationError("approved must be true/false")

    raw_events = document.get("events")
    if not isinstance(raw_events, list):
        raise EconomicCalendarValidationError("events must be an array")

    normalized: list[dict[str, str]] = []
    identities: set[tuple[str, str]] = set()
    for index, row in enumerate(raw_events):
        if not isinstance(row, dict):
            raise EconomicCalendarValidationError(f"events[{index}] must be an object")
        event = row.get("event")
        release_utc = row.get("release_utc")
        authority = row.get("source_authority")
        source_url = row.get("source_url")
        if event not in EVENT_TYPES:
            raise EconomicCalendarValidationError(f"events[{index}].event must be one of {sorted(EVENT_TYPES)}")
        parsed = _parse_utc(release_utc)
        if not isinstance(authority, str) or authority not in {"BLS", "FEDERAL_RESERVE"}:
            raise EconomicCalendarValidationError(f"events[{index}].source_authority is invalid")
        if not isinstance(source_url, str) or not source_url.startswith("https://"):
            raise EconomicCalendarValidationError(f"events[{index}].source_url must be https")
        if event in {"NFP", "CPI"} and authority != "BLS":
            raise EconomicCalendarValidationError(f"{event} events must use BLS provenance")
        if event == "FOMC" and authority != "FEDERAL_RESERVE":
            raise EconomicCalendarValidationError("FOMC events must use Federal Reserve provenance")
        canonical_ts = parsed.strftime("%Y-%m-%dT%H:%M:%SZ")
        identity = (event, canonical_ts)
        if identity in identities:
            raise EconomicCalendarValidationError(f"duplicate economic event: {identity}")
        identities.add(identity)
        normalized.append(
            {
                "event": event,
                "release_utc": canonical_ts,
                "source_authority": authority,
                "source_url": source_url,
            }
        )

    normalized.sort(key=lambda item: (item["release_utc"], item["event"]))
    coverage = document.get("coverage")
    if not isinstance(coverage, dict):
        raise EconomicCalendarValidationError("coverage object is required")
    start_raw = coverage.get("start_utc")
    end_raw = coverage.get("end_utc")
    start = _parse_utc(start_raw)
    end = _parse_utc(end_raw)
    if start >= end:
        raise EconomicCalendarValidationError("coverage.start_utc must precede coverage.end_utc")
    for row in normalized:
        stamp = _parse_utc(row["release_utc"])
        if stamp < start or stamp > end:
            raise EconomicCalendarValidationError("event lies outside declared calendar coverage")

    if approved:
        present = {row["event"] for row in normalized}
        if present != EVENT_TYPES:
            raise EconomicCalendarValidationError(
                "approved calendar must contain NFP, CPI and FOMC events"
            )
        if not normalized:
            raise EconomicCalendarValidationError("approved calendar cannot be empty")

    return {
        "schema_version": SCHEMA_VERSION,
        "calendar_id": calendar_id.strip(),
        "approved": approved,
        "coverage": {
            "start_utc": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end_utc": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "events": normalized,
    }


def canonical_calendar_sha256(document: dict[str, Any]) -> str:
    payload = json.dumps(
        canonical_calendar_snapshot(document),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_calendar_contract(path: str | Path) -> tuple[dict[str, Any], str, str]:
    target = Path(path).resolve()
    document = _load(target)
    canonical = canonical_calendar_snapshot(document)
    file_sha = hashlib.sha256(target.read_bytes()).hexdigest()
    canonical_sha = canonical_calendar_sha256(document)
    return canonical, file_sha, canonical_sha


def _mql5_date_conditions(events: list[dict[str, str]], event_type: str) -> list[str]:
    rows: list[str] = []
    for row in events:
        if row["event"] != event_type:
            continue
        stamp = _parse_utc(row["release_utc"])
        rows.append(f"(year=={stamp.year} && mon=={stamp.month} && day=={stamp.day})")
    return rows


def _render_bool_function(name: str, conditions: list[str]) -> list[str]:
    lines = [f"bool {name}(int year, int mon, int day)", "  {"]
    if not conditions:
        lines.append("   return false;")
    else:
        chunks = " ||\n          ".join(conditions)
        lines.append(f"   return({chunks});")
    lines.append("  }")
    return lines


def generate_mql5_include(document: dict[str, Any], output_path: str | Path) -> Path:
    canonical = canonical_calendar_snapshot(document)
    canonical_sha = canonical_calendar_sha256(document)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    approved = "true" if canonical["approved"] else "false"
    events = canonical["events"]
    lines = [
        "// AUTO-GENERATED by scripts/economic_calendar_contract.py. DO NOT EDIT BY HAND.",
        "#property strict",
        "",
        f"const bool GTX_ECONOMIC_CALENDAR_APPROVED = {approved};",
        f'const string GTX_ECONOMIC_CALENDAR_ID = "{canonical["calendar_id"]}";',
        f'const string GTX_ECONOMIC_CALENDAR_SHA256 = "{canonical_sha}";',
        f'const string GTX_ECONOMIC_CALENDAR_START_UTC = "{canonical["coverage"]["start_utc"]}";',
        f'const string GTX_ECONOMIC_CALENDAR_END_UTC = "{canonical["coverage"]["end_utc"]}";',
        "",
    ]
    lines += _render_bool_function("GTX_IsExactNfpReleaseDate", _mql5_date_conditions(events, "NFP"))
    lines.append("")
    lines += _render_bool_function("GTX_IsExactCpiReleaseDate", _mql5_date_conditions(events, "CPI"))
    lines.append("")
    lines += _render_bool_function("GTX_IsExactFomcDecisionDate", _mql5_date_conditions(events, "FOMC"))
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


def verify_generated_include(contract_path: str | Path, include_path: str | Path) -> None:
    document = _load(contract_path)
    target = Path(include_path).resolve()
    expected = generate_mql5_include(document, target.parent / (target.name + ".expected"))
    expected_bytes = expected.read_bytes()
    try:
        actual_bytes = target.read_bytes()
    except FileNotFoundError as exc:
        expected.unlink(missing_ok=True)
        raise EconomicCalendarValidationError(f"generated include not found: {target}") from exc
    expected.unlink(missing_ok=True)
    if actual_bytes != expected_bytes:
        raise EconomicCalendarValidationError(
            "EconomicCalendarData.mqh does not match the canonical economic-calendar contract"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--generate-mql5")
    parser.add_argument("--verify-mql5")
    parser.add_argument("--require-approved", action="store_true")
    args = parser.parse_args()
    try:
        canonical, file_sha, canonical_sha = load_calendar_contract(args.contract)
        if args.require_approved and canonical["approved"] is not True:
            raise EconomicCalendarValidationError("economic calendar is not approved")
        if args.generate_mql5:
            generate_mql5_include(_load(args.contract), args.generate_mql5)
        if args.verify_mql5:
            verify_generated_include(args.contract, args.verify_mql5)
    except EconomicCalendarValidationError as exc:
        parser.error(str(exc))
        return
    print(json.dumps({
        "calendar_id": canonical["calendar_id"],
        "approved": canonical["approved"],
        "event_count": len(canonical["events"]),
        "file_sha256": file_sha,
        "canonical_sha256": canonical_sha,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
