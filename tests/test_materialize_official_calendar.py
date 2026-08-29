import pytest

from scripts.materialize_official_calendar import (
    CalendarMaterializationError,
    _audit_counts,
    _validate_counts,
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
