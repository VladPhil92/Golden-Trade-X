import hashlib
import json
from datetime import datetime
from pathlib import Path

import pytest

from scripts.freeze_approved_economic_calendar import (
    CONFIRMATION,
    CalendarApprovalError,
    freeze_approved_calendar,
)
from scripts.materialize_official_calendar import BLS_YEAR_URL, FED_CALENDAR_URL, FED_SNAPSHOT_NAME
from scripts.official_calendar_snapshot import materialize_verified_snapshot


FED_HTML = """<html><body>
<a href="/monetarypolicy/fomcstatement20210127a.htm">1</a>
<a href="/monetarypolicy/fomcstatement20210317a.htm">2</a>
<a href="/monetarypolicy/fomcstatement20210428a.htm">3</a>
<a href="/monetarypolicy/fomcstatement20210616a.htm">4</a>
<a href="/monetarypolicy/fomcstatement20210728a.htm">5</a>
<a href="/monetarypolicy/fomcstatement20210922a.htm">6</a>
<a href="/monetarypolicy/fomcstatement20211103a.htm">7</a>
<a href="/monetarypolicy/fomcstatement20211215a.htm">8</a>
</body></html>"""


def _bls_html(year: int) -> str:
    rows = ["<table>"]
    for month in range(1, 13):
        for day, release in ((1, "Employment Situation for prior month"), (2, "Consumer Price Index for prior month")):
            stamp = datetime(year, month, day)
            rows.append(
                f"<tr><td>{stamp.strftime('%A, %B %d, %Y')}</td><td>08:30 AM</td><td>{release}</td></tr>"
            )
    rows.append("</table>")
    return "\n".join(rows)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "sources"
    root.mkdir()
    bls = _bls_html(2021).encode()
    fed = FED_HTML.encode()
    (root / "bls-2021.html").write_bytes(bls)
    (root / FED_SNAPSHOT_NAME).write_bytes(fed)
    manifest = {
        "schema_version": 1,
        "methodology": "OFFICIAL_CALENDAR_SOURCE_SNAPSHOT_V1",
        "source_authorities": ["BLS", "FEDERAL_RESERVE"],
        "start_year": 2021,
        "end_year": 2021,
        "captured_at_utc": "2026-08-29T00:00:00Z",
        "counts_by_year": {"2021": {"NFP": 12, "CPI": 12, "FOMC": 8}},
        "sources": [
            {"authority": "BLS", "year": 2021, "url": BLS_YEAR_URL.format(year=2021), "snapshot_name": "bls-2021.html", "sha256": _sha(bls), "size_bytes": len(bls), "parsed_event_count": 24},
            {"authority": "FEDERAL_RESERVE", "url": FED_CALENDAR_URL, "snapshot_name": FED_SNAPSHOT_NAME, "sha256": _sha(fed), "size_bytes": len(fed), "parsed_event_count": 8},
        ],
        "approved": False,
        "live_trading_authorized": False,
        "real_capital_authorized": False,
    }
    (root / "source_manifest.json").write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    document, audit = materialize_verified_snapshot(2021, 2021, root)
    review = tmp_path / "review.json"
    review_audit = tmp_path / "audit.json"
    review.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    review_audit.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return root, review, review_audit


def _approve(root: Path, review: Path, audit: Path, **overrides):
    args = dict(
        start_year=2021,
        end_year=2021,
        source_dir=root,
        review_calendar_path=review,
        review_audit_path=audit,
        approved_by="reviewer@example",
        approval_note="Reviewed source bundle and annual counts.",
        approved_at_utc="2026-08-29T19:00:00Z",
        confirmation=CONFIRMATION,
    )
    args.update(overrides)
    return freeze_approved_calendar(**args)


def test_approval_freeze_emits_validation_only_approved_contract(tmp_path: Path) -> None:
    root, review, audit = _fixture(tmp_path)
    document, record = _approve(root, review, audit)
    assert document["approved"] is True
    assert record["decision"] == "APPROVED_FOR_OFFICIAL_VALIDATION"
    assert record["event_count"] == 32
    assert len(record["source_manifest_sha256"]) == 64
    assert record["live_trading_authorized"] is False
    assert record["real_capital_authorized"] is False


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"confirmation": "YES"}, "explicit confirmation"),
        ({"approved_by": ""}, "approved_by"),
        ({"approval_note": "short"}, "at least 8"),
        ({"approved_at_utc": "not-a-time"}, "approved_at_utc"),
    ],
)
def test_approval_requires_explicit_human_decision_fields(tmp_path: Path, overrides, message: str) -> None:
    root, review, audit = _fixture(tmp_path)
    with pytest.raises(CalendarApprovalError, match=message):
        _approve(root, review, audit, **overrides)


def test_approval_rejects_tampered_review_calendar(tmp_path: Path) -> None:
    root, review, audit = _fixture(tmp_path)
    doc = json.loads(review.read_text())
    doc["events"].pop()
    review.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(CalendarApprovalError, match="review calendar differs"):
        _approve(root, review, audit)


def test_approval_rejects_tampered_review_audit(tmp_path: Path) -> None:
    root, review, audit = _fixture(tmp_path)
    doc = json.loads(audit.read_text())
    doc["event_count"] = 999
    audit.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(CalendarApprovalError, match="review audit differs"):
        _approve(root, review, audit)


def test_approval_rejects_preapproved_review_input(tmp_path: Path) -> None:
    root, review, audit = _fixture(tmp_path)
    doc = json.loads(review.read_text())
    doc["approved"] = True
    review.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(CalendarApprovalError, match="approved=false"):
        _approve(root, review, audit)


def test_approval_rejects_source_bundle_drift_after_review(tmp_path: Path) -> None:
    root, review, audit = _fixture(tmp_path)
    (root / "bls-2021.html").write_text("tampered", encoding="utf-8")
    with pytest.raises(CalendarApprovalError, match="mismatch"):
        _approve(root, review, audit)
