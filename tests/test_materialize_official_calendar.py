import hashlib
from datetime import datetime

import pytest

from scripts.materialize_official_calendar import (
    DEFAULT_END_YEAR,
    DEFAULT_START_YEAR,
    CalendarMaterializationError,
    _audit_counts,
    _validate_counts,
    materialize_calendar,
    parse_bls_year,
    parse_fomc_statement_links,
)


BLS_HTML = """
<table>
  <tr><th>Date</th><th>Time</th><th>Release</th></tr>
  <tr><td>Friday, January 8, 2021</td><td>08:30 AM</td><td>Employment Situation for December 2020</td></tr>
  <tr><td>Wednesday, January 13, 2021</td><td>08:30 AM</td><td>Consumer Price Index for December 2020</td></tr>
  <tr><td>Thursday, January 14, 2021</td><td>08:30 AM</td><td>Producer Price Index for December 2020</td></tr>
  <tr><td>Friday, July 2, 2021</td><td>08:30 AM</td><td>Employment Situation for June 2021</td></tr>
  <tr><td>Tuesday, July 13, 2021</td><td>08:30 AM</td><td>Consumer Price Index for June 2021</td></tr>
</table>
"""

FED_HTML = """
<html><body>
<a href="/newsevents/pressreleases/monetary20210127a.htm">not a statement-pattern link</a>
<a href="/monetarypolicy/fomcstatement20210127a.htm">January statement</a>
<a href="/monetarypolicy/fomcstatement20210317a.htm">March statement</a>
<a href="/monetarypolicy/fomcstatement20210428a.htm">April statement</a>
<a href="/monetarypolicy/fomcstatement20210616a.htm">June statement</a>
<a href="/monetarypolicy/fomcstatement20210728a.htm">July statement</a>
<a href="/monetarypolicy/fomcstatement20210922a.htm">September statement</a>
<a href="/monetarypolicy/fomcstatement20211103a.htm">November statement</a>
<a href="/monetarypolicy/fomcstatement20211215a.htm">December statement</a>
<a href="/monetarypolicy/fomcstatement20210127a.htm">duplicate statement link</a>
</body></html>
"""


def _complete_bls_html(year: int) -> str:
    rows = ["<table><tr><th>Date</th><th>Time</th><th>Release</th></tr>"]
    for month in range(1, 13):
        nfp = datetime(year, month, 1)
        cpi = datetime(year, month, 2)
        rows.append(
            "<tr><td>"
            + nfp.strftime("%A, %B %d, %Y")
            + "</td><td>08:30 AM</td><td>Employment Situation for prior month</td></tr>"
        )
        rows.append(
            "<tr><td>"
            + cpi.strftime("%A, %B %d, %Y")
            + "</td><td>08:30 AM</td><td>Consumer Price Index for prior month</td></tr>"
        )
    rows.append("</table>")
    return "\n".join(rows)


class _NoNetworkSession:
    def get(self, *args, **kwargs):  # pragma: no cover - must never execute
        raise AssertionError("snapshot mode attempted network access")


def test_v1_defaults_use_only_completed_historical_release_years() -> None:
    assert DEFAULT_START_YEAR == 2021
    assert DEFAULT_END_YEAR == 2025


def test_bls_parser_selects_only_nfp_and_cpi_and_applies_dst() -> None:
    events = parse_bls_year(BLS_HTML, 2021, "https://www.bls.gov/schedule/2021/")
    assert [(event.event, event.release_utc) for event in events] == [
        ("NFP", "2021-01-08T13:30:00Z"),
        ("CPI", "2021-01-13T13:30:00Z"),
        ("NFP", "2021-07-02T12:30:00Z"),
        ("CPI", "2021-07-13T12:30:00Z"),
    ]
    assert all(event.source_authority == "BLS" for event in events)


def test_bls_parser_rejects_unexpected_release_clock() -> None:
    bad = BLS_HTML.replace("Friday, January 8, 2021</td><td>08:30 AM", "Friday, January 8, 2021</td><td>09:30 AM")
    with pytest.raises(CalendarMaterializationError, match="unexpected NFP release time"):
        parse_bls_year(bad, 2021, "https://www.bls.gov/schedule/2021/")


def test_fomc_parser_uses_statement_dates_and_deduplicates_links() -> None:
    events = parse_fomc_statement_links(FED_HTML, start_year=2021, end_year=2021)
    assert len(events) == 8
    assert events[0].release_utc == "2021-01-27T19:00:00Z"
    assert events[3].release_utc == "2021-06-16T18:00:00Z"
    assert events[-1].release_utc == "2021-12-15T19:00:00Z"
    assert all(event.source_authority == "FEDERAL_RESERVE" for event in events)
    assert all("fomcstatement" in event.source_url for event in events)


def test_count_audit_fails_closed_on_incomplete_source_parse() -> None:
    events = parse_bls_year(BLS_HTML, 2021, "https://www.bls.gov/schedule/2021/")
    events += parse_fomc_statement_links(FED_HTML, start_year=2021, end_year=2021)
    counts = _audit_counts(events, 2021, 2021)
    assert counts["2021"] == {"NFP": 2, "CPI": 2, "FOMC": 8}
    with pytest.raises(CalendarMaterializationError, match="only 2 NFP releases"):
        _validate_counts(counts)


def test_count_audit_rejects_partial_future_fomc_year() -> None:
    counts = {"2026": {"NFP": 12, "CPI": 12, "FOMC": 5}}
    with pytest.raises(CalendarMaterializationError, match="expected exactly 8 regular FOMC"):
        _validate_counts(counts)


def test_snapshot_mode_is_offline_and_hashes_every_source(tmp_path) -> None:
    bls = _complete_bls_html(2021).encode("utf-8")
    fed = FED_HTML.encode("utf-8")
    (tmp_path / "bls-2021.html").write_bytes(bls)
    (tmp_path / "fomccalendars.html").write_bytes(fed)

    document, audit = materialize_calendar(
        2021,
        2021,
        source_dir=tmp_path,
        session=_NoNetworkSession(),
    )

    assert document["approved"] is False
    assert audit["schema_version"] == 2
    assert audit["source_mode"] == "IMMUTABLE_OFFICIAL_SNAPSHOTS"
    assert audit["counts_by_year"]["2021"] == {"NFP": 12, "CPI": 12, "FOMC": 8}
    assert audit["event_count"] == 32
    assert audit["sources"]["bls"][0]["snapshot_sha256"] == hashlib.sha256(bls).hexdigest()
    assert audit["sources"]["federal_reserve"]["snapshot_sha256"] == hashlib.sha256(fed).hexdigest()
    assert audit["live_trading_authorized"] is False
    assert audit["real_capital_authorized"] is False


def test_snapshot_mode_never_falls_back_to_network_when_source_is_missing(tmp_path) -> None:
    (tmp_path / "bls-2021.html").write_text(_complete_bls_html(2021), encoding="utf-8")
    with pytest.raises(CalendarMaterializationError, match="required source snapshot not found"):
        materialize_calendar(
            2021,
            2021,
            source_dir=tmp_path,
            session=_NoNetworkSession(),
        )
