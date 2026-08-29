#!/usr/bin/env python3
"""Freeze an approved economic-calendar contract from verified immutable snapshots.

Approval is intentionally a second, explicit transition after unapproved review
materialization. The command re-materializes the source bundle, verifies the exact
review document and audit, and only then emits an approved validation contract plus
an immutable approval record. Approval never authorizes live or real-capital trading.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.economic_calendar_contract import (
        canonical_calendar_sha256,
        canonical_calendar_snapshot,
        load_calendar_contract,
    )
    from scripts.materialize_official_calendar import CalendarMaterializationError
    from scripts.official_calendar_snapshot import materialize_verified_snapshot
except ModuleNotFoundError:
    from economic_calendar_contract import (
        canonical_calendar_sha256,
        canonical_calendar_snapshot,
        load_calendar_contract,
    )
    from materialize_official_calendar import CalendarMaterializationError
    from official_calendar_snapshot import materialize_verified_snapshot

METHODOLOGY = "OFFICIAL_ECONOMIC_CALENDAR_APPROVAL_FREEZE_V1"
CONFIRMATION = "APPROVE_OFFICIAL_ECONOMIC_CALENDAR"


class CalendarApprovalError(ValueError):
    pass


def _load_json(path: str | Path) -> dict[str, Any]:
    target = Path(path).resolve()
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CalendarApprovalError(f"invalid JSON input: {target}") from exc
    if not isinstance(value, dict):
        raise CalendarApprovalError(f"JSON input root must be an object: {target}")
    return value


def _file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).resolve().read_bytes()).hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _parse_approval_time(raw: str) -> str:
    if not isinstance(raw, str) or not raw.endswith("Z"):
        raise CalendarApprovalError("approved_at_utc must be an ISO-8601 UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(raw[:-1] + "+00:00")
    except ValueError as exc:
        raise CalendarApprovalError("approved_at_utc is invalid") from exc
    if parsed.tzinfo != timezone.utc:
        raise CalendarApprovalError("approved_at_utc must be UTC")
    return parsed.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def freeze_approved_calendar(
    *,
    start_year: int,
    end_year: int,
    source_dir: str | Path,
    review_calendar_path: str | Path,
    review_audit_path: str | Path,
    approved_by: str,
    approval_note: str,
    approved_at_utc: str,
    confirmation: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if confirmation != CONFIRMATION:
        raise CalendarApprovalError(
            f"explicit confirmation must equal {CONFIRMATION!r}"
        )
    reviewer = approved_by.strip() if isinstance(approved_by, str) else ""
    note = approval_note.strip() if isinstance(approval_note, str) else ""
    if not reviewer:
        raise CalendarApprovalError("approved_by is required")
    if len(note) < 8:
        raise CalendarApprovalError("approval_note must contain at least 8 characters")
    approved_at = _parse_approval_time(approved_at_utc)

    review_document = _load_json(review_calendar_path)
    review_audit = _load_json(review_audit_path)
    review_canonical = canonical_calendar_snapshot(review_document)
    if review_canonical["approved"] is not False:
        raise CalendarApprovalError("review calendar must be approved=false before approval freeze")
    if review_audit.get("source_manifest_verified") is not True:
        raise CalendarApprovalError("review audit must contain source_manifest_verified=true")
    if review_audit.get("approved") is not False:
        raise CalendarApprovalError("review audit must remain approved=false")
    if review_audit.get("live_trading_authorized") is not False:
        raise CalendarApprovalError("review audit must deny live trading")
    if review_audit.get("real_capital_authorized") is not False:
        raise CalendarApprovalError("review audit must deny real capital")

    try:
        expected_document, expected_audit = materialize_verified_snapshot(
            start_year,
            end_year,
            source_dir,
        )
    except CalendarMaterializationError as exc:
        raise CalendarApprovalError(str(exc)) from exc

    if _canonical_json(review_document) != _canonical_json(expected_document):
        raise CalendarApprovalError(
            "review calendar differs from deterministic materialization of verified snapshots"
        )
    if _canonical_json(review_audit) != _canonical_json(expected_audit):
        raise CalendarApprovalError(
            "review audit differs from deterministic materialization of verified snapshots"
        )

    approved_document = deepcopy(review_document)
    approved_document["approved"] = True
    approved_canonical = canonical_calendar_snapshot(approved_document)
    if approved_canonical["approved"] is not True:
        raise CalendarApprovalError("approved calendar transition failed")

    source_manifest = review_audit.get("source_manifest")
    if not isinstance(source_manifest, dict) or not source_manifest.get("sha256"):
        raise CalendarApprovalError("verified source manifest SHA-256 is required")

    approval_record = {
        "schema_version": 1,
        "methodology": METHODOLOGY,
        "decision": "APPROVED_FOR_OFFICIAL_VALIDATION",
        "approved_by": reviewer,
        "approval_note": note,
        "approved_at_utc": approved_at,
        "calendar_id": approved_canonical["calendar_id"],
        "coverage": approved_canonical["coverage"],
        "event_count": len(approved_canonical["events"]),
        "source_manifest_sha256": source_manifest["sha256"],
        "review_calendar_file_sha256": _file_sha256(review_calendar_path),
        "review_calendar_canonical_sha256": canonical_calendar_sha256(review_document),
        "review_audit_file_sha256": _file_sha256(review_audit_path),
        "approved_calendar_canonical_sha256": canonical_calendar_sha256(approved_document),
        "live_trading_authorized": False,
        "real_capital_authorized": False,
    }
    return approved_document, approval_record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-year", type=int, required=True)
    parser.add_argument("--end-year", type=int, required=True)
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--review-calendar", required=True)
    parser.add_argument("--review-audit", required=True)
    parser.add_argument("--approved-by", required=True)
    parser.add_argument("--approval-note", required=True)
    parser.add_argument("--approved-at-utc", required=True)
    parser.add_argument("--confirmation", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--approval-record", required=True)
    args = parser.parse_args()

    try:
        document, record = freeze_approved_calendar(
            start_year=args.start_year,
            end_year=args.end_year,
            source_dir=args.source_dir,
            review_calendar_path=args.review_calendar,
            review_audit_path=args.review_audit,
            approved_by=args.approved_by,
            approval_note=args.approval_note,
            approved_at_utc=args.approved_at_utc,
            confirmation=args.confirmation,
        )
    except CalendarApprovalError as exc:
        parser.error(str(exc))
        return

    output = Path(args.output)
    record_output = Path(args.approval_record)
    output.parent.mkdir(parents=True, exist_ok=True)
    record_output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    record_output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    canonical, file_sha, canonical_sha = load_calendar_contract(output)
    print(json.dumps({
        "status": record["decision"],
        "calendar_id": canonical["calendar_id"],
        "approved": canonical["approved"],
        "event_count": len(canonical["events"]),
        "approved_calendar_file_sha256": file_sha,
        "approved_calendar_canonical_sha256": canonical_sha,
        "live_trading_authorized": False,
        "real_capital_authorized": False,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
