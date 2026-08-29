import hashlib
import json
from datetime import datetime
from pathlib import Path

import pytest

from scripts.materialize_official_calendar import (
    BLS_YEAR_URL,
    FED_CALENDAR_URL,
    FED_SNAPSHOT_NAME,
    CalendarMaterializationError,
)
from scripts.official_calendar_snapshot import (
    load_and_verify_source_manifest,
    materialize_verified_snapshot,
)


FED_HTML = """
<html><body>
<a href="/monetarypolicy/fomcstatement20210127a.htm">January</a>
<a href="/monetarypolicy/fomcstatement20210317a.htm">March</a>
<a href="/monetarypolicy/fomcstatement20210428a.htm">April</a>
<a href="/monetarypolicy/fomcstatement20210616a.htm">June</a>
<a href="/monetarypolicy/fomcstatement20210728a.htm">July</a>
<a href="/monetarypolicy/fomcstatement20210922a.htm">September</a>
<a href="/monetarypolicy/fomcstatement20211103a.htm">November</a>
<a href="/monetarypolicy/fomcstatement20211215a.htm">December</a>
</body></html>
"""


def _bls_html(year: int) -> str:
    rows = ["<table><tr><th>Date</th><th>Time</th><th>Release</th></tr>"]
    for month in range(1, 13):
        nfp = datetime(year, month, 1)
        cpi = datetime(year, month, 2)
        rows.append(
            f"<tr><td>{nfp.strftime('%A, %B %d, %Y')}</td><td>08:30 AM</td>"
            "<td>Employment Situation for prior month</td></tr>"
        )
        rows.append(
            f"<tr><td>{cpi.strftime('%A, %B %d, %Y')}</td><td>08:30 AM</td>"
            "<td>Consumer Price Index for prior month</td></tr>"
        )
    rows.append("</table>")
    return "\n".join(rows)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _source_bundle(tmp_path: Path) -> Path:
    root = tmp_path / "sources"
    root.mkdir()
    bls = _bls_html(2021).encode("utf-8")
    fed = FED_HTML.encode("utf-8")
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
            {
                "authority": "BLS",
                "year": 2021,
                "url": BLS_YEAR_URL.format(year=2021),
                "snapshot_name": "bls-2021.html",
                "sha256": _sha(bls),
                "size_bytes": len(bls),
                "parsed_event_count": 24,
            },
            {
                "authority": "FEDERAL_RESERVE",
                "url": FED_CALENDAR_URL,
                "snapshot_name": FED_SNAPSHOT_NAME,
                "sha256": _sha(fed),
                "size_bytes": len(fed),
                "parsed_event_count": 8,
            },
        ],
        "approved": False,
        "live_trading_authorized": False,
        "real_capital_authorized": False,
    }
    (root / "source_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return root


def _mutate_manifest(root: Path, fn) -> None:
    path = root / "source_manifest.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    fn(doc)
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_verified_snapshot_binds_manifest_and_parsed_counts(tmp_path: Path) -> None:
    root = _source_bundle(tmp_path)
    manifest, manifest_sha = load_and_verify_source_manifest(root, 2021, 2021)
    assert manifest["methodology"] == "OFFICIAL_CALENDAR_SOURCE_SNAPSHOT_V1"
    assert len(manifest_sha) == 64

    document, audit = materialize_verified_snapshot(2021, 2021, root)
    assert document["approved"] is False
    assert len(document["events"]) == 32
    assert audit["source_manifest_verified"] is True
    assert audit["source_manifest"]["sha256"] == manifest_sha
    assert audit["source_mode"] == "IMMUTABLE_OFFICIAL_SNAPSHOTS"
    assert audit["live_trading_authorized"] is False
    assert audit["real_capital_authorized"] is False


def test_verified_snapshot_requires_manifest(tmp_path: Path) -> None:
    root = tmp_path / "sources"
    root.mkdir()
    with pytest.raises(CalendarMaterializationError, match="required source manifest not found"):
        load_and_verify_source_manifest(root, 2021, 2021)


def test_verified_snapshot_detects_file_tampering(tmp_path: Path) -> None:
    root = _source_bundle(tmp_path)
    (root / "bls-2021.html").write_text("tampered", encoding="utf-8")
    with pytest.raises(CalendarMaterializationError, match="size mismatch|SHA-256 mismatch"):
        load_and_verify_source_manifest(root, 2021, 2021)


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda d: d.update(schema_version=2), "schema_version"),
        (lambda d: d.update(methodology="WRONG"), "methodology"),
        (lambda d: d.update(start_year=2020), "range mismatch"),
        (lambda d: d.update(approved=True), "approved=false"),
        (lambda d: d.update(live_trading_authorized=True), "deny live trading"),
        (lambda d: d.update(real_capital_authorized=True), "deny real capital"),
        (lambda d: d.update(source_authorities=["BLS"]), "authorities"),
        (lambda d: d["sources"][0].update(url="https://example.invalid"), "URL mismatch"),
        (lambda d: d["sources"][0].update(authority="OTHER"), "authority mismatch"),
        (lambda d: d["sources"][0].update(year=2022), "year mismatch"),
        (lambda d: d["sources"][0].update(size_bytes=1), "size mismatch"),
        (lambda d: d["sources"][0].update(sha256="0" * 64), "SHA-256 mismatch"),
        (lambda d: d["sources"].append(dict(d["sources"][0])), "duplicate source manifest snapshot"),
        (lambda d: d["sources"].pop(), "missing required snapshots"),
        (lambda d: d.update(counts_by_year={}), "counts_by_year range mismatch"),
    ],
)
def test_source_manifest_metadata_mutations_fail_closed(tmp_path: Path, mutator, message: str) -> None:
    root = _source_bundle(tmp_path)
    _mutate_manifest(root, mutator)
    with pytest.raises(CalendarMaterializationError, match=message):
        load_and_verify_source_manifest(root, 2021, 2021)


def test_verified_snapshot_detects_parsed_event_count_drift(tmp_path: Path) -> None:
    root = _source_bundle(tmp_path)
    _mutate_manifest(root, lambda d: d["sources"][0].update(parsed_event_count=23))
    with pytest.raises(CalendarMaterializationError, match="parsed_event_count mismatch"):
        materialize_verified_snapshot(2021, 2021, root)


def test_verified_snapshot_detects_annual_count_drift(tmp_path: Path) -> None:
    root = _source_bundle(tmp_path)
    _mutate_manifest(
        root,
        lambda d: d.update(counts_by_year={"2021": {"NFP": 11, "CPI": 12, "FOMC": 8}}),
    )
    with pytest.raises(CalendarMaterializationError, match="parsed annual counts differ"):
        materialize_verified_snapshot(2021, 2021, root)
