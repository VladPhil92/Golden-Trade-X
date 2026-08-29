import json
from pathlib import Path

import pytest

from scripts.economic_calendar_contract import (
    EconomicCalendarValidationError,
    canonical_calendar_sha256,
    canonical_calendar_snapshot,
    generate_mql5_include,
    verify_generated_include,
)


def _calendar(*, approved: bool = True) -> dict:
    return {
        "schema_version": 1,
        "calendar_id": "TEST-ECON-CALENDAR",
        "approved": approved,
        "coverage": {
            "start_utc": "2026-01-01T00:00:00Z",
            "end_utc": "2026-12-31T23:59:59Z",
        },
        "events": [
            {
                "event": "NFP",
                "release_utc": "2026-02-11T13:30:00Z",
                "source_authority": "BLS",
                "source_url": "https://www.bls.gov/schedule/2026/",
            },
            {
                "event": "CPI",
                "release_utc": "2026-02-13T13:30:00Z",
                "source_authority": "BLS",
                "source_url": "https://www.bls.gov/schedule/2026/",
            },
            {
                "event": "FOMC",
                "release_utc": "2026-03-18T18:00:00Z",
                "source_authority": "FEDERAL_RESERVE",
                "source_url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
            },
        ],
    }


def test_approved_calendar_normalizes_and_hashes_deterministically() -> None:
    document = _calendar()
    snapshot = canonical_calendar_snapshot(document)
    assert snapshot["approved"] is True
    assert [row["event"] for row in snapshot["events"]] == ["NFP", "CPI", "FOMC"]
    assert canonical_calendar_sha256(document) == canonical_calendar_sha256(document)


def test_approved_calendar_requires_all_three_event_families() -> None:
    document = _calendar()
    document["events"] = [document["events"][0]]
    with pytest.raises(EconomicCalendarValidationError, match="must contain NFP, CPI and FOMC"):
        canonical_calendar_snapshot(document)


def test_calendar_rejects_wrong_authority_and_duplicates() -> None:
    document = _calendar()
    document["events"][0]["source_authority"] = "FEDERAL_RESERVE"
    with pytest.raises(EconomicCalendarValidationError, match="NFP events must use BLS"):
        canonical_calendar_snapshot(document)

    document = _calendar()
    document["events"].append(dict(document["events"][0]))
    with pytest.raises(EconomicCalendarValidationError, match="duplicate economic event"):
        canonical_calendar_snapshot(document)


def test_generated_include_is_content_addressed_and_verifiable(tmp_path: Path) -> None:
    document = _calendar()
    contract = tmp_path / "calendar.json"
    contract.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    include = generate_mql5_include(document, tmp_path / "EconomicCalendarData.mqh")
    text = include.read_text(encoding="utf-8")
    assert "GTX_ECONOMIC_CALENDAR_APPROVED = true" in text
    assert canonical_calendar_sha256(document) in text
    assert "year==2026 && mon==2 && day==11" in text
    assert "year==2026 && mon==2 && day==13" in text
    verify_generated_include(contract, include)

    include.write_text(text + "// drift\n", encoding="utf-8")
    with pytest.raises(EconomicCalendarValidationError, match="does not match"):
        verify_generated_include(contract, include)


def test_draft_calendar_may_be_empty_but_is_not_approved() -> None:
    document = _calendar(approved=False)
    document["events"] = []
    snapshot = canonical_calendar_snapshot(document)
    assert snapshot["approved"] is False
    assert snapshot["events"] == []
