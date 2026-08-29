#!/usr/bin/env python3
"""Materialize Golden Trade X economic-calendar evidence from official sources.

Sources:
- BLS annual release calendars for Employment Situation (NFP proxy event class) and CPI.
- Federal Reserve FOMC statement links for regular policy-decision dates.

The materializer converts published Eastern Time release clocks to UTC using the IANA
America/New_York timezone, preserves per-event source URLs and emits the same schema
consumed by economic_calendar_contract.py. It does not approve data by default; approval
must be an explicit pre-observation action after reviewing the generated audit summary.

The CLI defaults match the frozen GTX-WF-V1 historical window [2021-01-01, 2026-01-01):
release years 2021 through 2025 inclusive. Future-year statement links are never invented.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime, time
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests

BLS_YEAR_URL = "https://www.bls.gov/schedule/{year}/"
FED_CALENDAR_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
USER_AGENT = "GoldenTradeX-OfficialCalendar/1.0 (+reproducible-validation)"
EASTERN = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")
DEFAULT_START_YEAR = 2021
DEFAULT_END_YEAR = 2025

_BLS_DATE_FORMATS = ("%A, %B %d, %Y", "%A, %B %e, %Y")
_FOMC_HREF_RE = re.compile(r"fomcstatement(?P<date>20\d{6})a?\.htm(?:$|[?#])", re.IGNORECASE)


class CalendarMaterializationError(ValueError):
    pass


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_row = False
        self._in_cell = False
        self._cell_parts: list[str] = []
        self._row: list[str] = []
        self.rows: list[list[str]] = []
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag == "tr":
            self._in_row = True
            self._row = []
        elif self._in_row and tag in {"td", "th"}:
            self._in_cell = True
            self._cell_parts = []
        elif tag == "a":
            href = dict(attrs).get("href")
            if isinstance(href, str):
                self.links.append(href)

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._in_cell and tag in {"td", "th"}:
            text = " ".join("".join(self._cell_parts).split())
            self._row.append(text)
            self._in_cell = False
            self._cell_parts = []
        elif self._in_row and tag == "tr":
            if self._row:
                self.rows.append(self._row)
            self._in_row = False
            self._row = []


@dataclass(frozen=True)
class Event:
    event: str
    release_utc: str
    source_authority: str
    source_url: str

    def as_dict(self) -> dict[str, str]:
        return {
            "event": self.event,
            "release_utc": self.release_utc,
            "source_authority": self.source_authority,
            "source_url": self.source_url,
        }


def _request(url: str, *, timeout: int = 30, session: requests.Session | None = None) -> str:
    client = session or requests.Session()
    response = client.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    return response.text


def _parse_bls_date(raw: str) -> datetime:
    normalized = " ".join(raw.split())
    # %e is not portable on Windows, so normalize one-digit day manually first.
    normalized = re.sub(r"(, [A-Za-z]+)\s+0?(\d{1,2})(, \d{4})$", r"\1 \2\3", normalized)
    for fmt in _BLS_DATE_FORMATS:
        try:
            return datetime.strptime(normalized, fmt)
        except (ValueError, TypeError):
            continue
    raise CalendarMaterializationError(f"unrecognized BLS release date: {raw!r}")


def _parse_release_clock(raw: str) -> time:
    try:
        return datetime.strptime(" ".join(raw.split()), "%I:%M %p").time()
    except ValueError as exc:
        raise CalendarMaterializationError(f"unrecognized BLS release time: {raw!r}") from exc


def _to_utc(date_value: datetime, clock: time) -> str:
    local = datetime.combine(date_value.date(), clock, tzinfo=EASTERN)
    return local.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_bls_year(html: str, year: int, source_url: str) -> list[Event]:
    parser = _TableParser()
    parser.feed(html)
    events: list[Event] = []
    for row in parser.rows:
        if len(row) < 3:
            continue
        date_text, time_text = row[0], row[1]
        release_text = " ".join(row[2:])
        if release_text.startswith("Employment Situation for"):
            event_type = "NFP"
        elif release_text.startswith("Consumer Price Index for"):
            event_type = "CPI"
        else:
            continue
        release_date = _parse_bls_date(date_text)
        if release_date.year != year:
            raise CalendarMaterializationError(
                f"BLS {year} page contains selected event outside year: {date_text}"
            )
        release_clock = _parse_release_clock(time_text)
        if release_clock != time(8, 30):
            raise CalendarMaterializationError(
                f"unexpected {event_type} release time on {date_text}: {time_text}"
            )
        events.append(
            Event(
                event=event_type,
                release_utc=_to_utc(release_date, release_clock),
                source_authority="BLS",
                source_url=source_url,
            )
        )
    return events


def parse_fomc_statement_links(html: str, *, start_year: int, end_year: int) -> list[Event]:
    parser = _TableParser()
    parser.feed(html)
    by_date: dict[str, str] = {}
    for href in parser.links:
        match = _FOMC_HREF_RE.search(href)
        if not match:
            continue
        raw_date = match.group("date")
        stamp = datetime.strptime(raw_date, "%Y%m%d")
        if not (start_year <= stamp.year <= end_year):
            continue
        source_url = urljoin(FED_CALENDAR_URL, href)
        by_date[raw_date] = source_url

    events: list[Event] = []
    for raw_date in sorted(by_date):
        stamp = datetime.strptime(raw_date, "%Y%m%d")
        events.append(
            Event(
                event="FOMC",
                release_utc=_to_utc(stamp, time(14, 0)),
                source_authority="FEDERAL_RESERVE",
                source_url=by_date[raw_date],
            )
        )
    return events


def _audit_counts(events: Iterable[Event], start_year: int, end_year: int) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for year in range(start_year, end_year + 1):
        counts[str(year)] = {"NFP": 0, "CPI": 0, "FOMC": 0}
    for event in events:
        year = event.release_utc[:4]
        if year in counts:
            counts[year][event.event] += 1
    return counts


def _validate_counts(counts: dict[str, dict[str, int]]) -> None:
    for year, row in counts.items():
        # BLS schedules can contain government-shutdown delays/cancellations, so do not
        # hard-code 12. Requiring at least 10 catches parser/source failures while keeping
        # exceptional official schedules reviewable. FOMC regular meetings are eight/year.
        if row["NFP"] < 10:
            raise CalendarMaterializationError(f"{year}: only {row['NFP']} NFP releases parsed")
        if row["CPI"] < 10:
            raise CalendarMaterializationError(f"{year}: only {row['CPI']} CPI releases parsed")
        if row["FOMC"] != 8:
            raise CalendarMaterializationError(
                f"{year}: expected exactly 8 regular FOMC statement dates, parsed {row['FOMC']}"
            )


def materialize_calendar(
    start_year: int,
    end_year: int,
    *,
    approved: bool = False,
    timeout: int = 30,
    session: requests.Session | None = None,
) -> tuple[dict, dict]:
    if start_year < 2000 or end_year < start_year:
        raise CalendarMaterializationError("invalid materialization year range")

    events: list[Event] = []
    for year in range(start_year, end_year + 1):
        url = BLS_YEAR_URL.format(year=year)
        events.extend(parse_bls_year(_request(url, timeout=timeout, session=session), year, url))

    fed_html = _request(FED_CALENDAR_URL, timeout=timeout, session=session)
    events.extend(parse_fomc_statement_links(fed_html, start_year=start_year, end_year=end_year))

    identities: set[tuple[str, str]] = set()
    for event in events:
        identity = (event.event, event.release_utc)
        if identity in identities:
            raise CalendarMaterializationError(f"duplicate materialized event: {identity}")
        identities.add(identity)

    events.sort(key=lambda item: (item.release_utc, item.event))
    counts = _audit_counts(events, start_year, end_year)
    _validate_counts(counts)

    document = {
        "schema_version": 1,
        "calendar_id": f"GTX-ECONOMIC-CALENDAR-{start_year}-{end_year}-V1",
        "approved": bool(approved),
        "status_note": (
            "Materialized exclusively from BLS annual release calendars and Federal Reserve "
            "FOMC statement links. Approval is explicit and must occur before official evidence."
        ),
        "coverage": {
            "start_utc": f"{start_year}-01-01T00:00:00Z",
            "end_utc": f"{end_year}-12-31T23:59:59Z",
        },
        "events": [event.as_dict() for event in events],
    }
    audit = {
        "schema_version": 1,
        "methodology": "OFFICIAL_ECONOMIC_CALENDAR_MATERIALIZATION_V1",
        "approved": bool(approved),
        "start_year": start_year,
        "end_year": end_year,
        "event_count": len(events),
        "counts_by_year": counts,
        "sources": {
            "bls": [BLS_YEAR_URL.format(year=year) for year in range(start_year, end_year + 1)],
            "federal_reserve": FED_CALENDAR_URL,
        },
        "live_trading_authorized": False,
        "real_capital_authorized": False,
    }
    return document, audit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-year", type=int, default=DEFAULT_START_YEAR)
    parser.add_argument("--end-year", type=int, default=DEFAULT_END_YEAR)
    parser.add_argument("--output", required=True)
    parser.add_argument("--audit-output", required=True)
    parser.add_argument("--approved", action="store_true")
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()
    try:
        document, audit = materialize_calendar(
            args.start_year,
            args.end_year,
            approved=args.approved,
            timeout=args.timeout,
        )
    except (CalendarMaterializationError, requests.RequestException) as exc:
        parser.error(str(exc))
        return

    output = Path(args.output)
    audit_output = Path(args.audit_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    audit_output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    audit_output.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(audit, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
