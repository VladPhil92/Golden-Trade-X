#!/usr/bin/env python3
"""Capture immutable BLS/Federal Reserve HTML snapshots for calendar materialization.

This command is intended for a network environment that can access BLS directly (for
example a maintainer workstation). GitHub-hosted runners are known to receive HTTP 403
from BLS schedule endpoints. The command validates all downloaded pages before writing
anything, then emits raw official HTML files plus a SHA-256 source manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

try:
    from scripts.materialize_official_calendar import (
        BLS_YEAR_URL,
        DEFAULT_END_YEAR,
        DEFAULT_START_YEAR,
        FED_CALENDAR_URL,
        FED_SNAPSHOT_NAME,
        USER_AGENT,
        CalendarMaterializationError,
        _audit_counts,
        _validate_counts,
        parse_bls_year,
        parse_fomc_statement_links,
    )
except ModuleNotFoundError:
    from materialize_official_calendar import (
        BLS_YEAR_URL,
        DEFAULT_END_YEAR,
        DEFAULT_START_YEAR,
        FED_CALENDAR_URL,
        FED_SNAPSHOT_NAME,
        USER_AGENT,
        CalendarMaterializationError,
        _audit_counts,
        _validate_counts,
        parse_bls_year,
        parse_fomc_statement_links,
    )


class SourceCaptureError(ValueError):
    pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fetch(
    session: requests.Session,
    url: str,
    *,
    timeout: int,
) -> bytes:
    response = session.get(
        url,
        timeout=timeout,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    response.raise_for_status()
    raw = response.content
    if not raw:
        raise SourceCaptureError(f"official source returned an empty response: {url}")
    try:
        raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SourceCaptureError(f"official source is not UTF-8 decodable: {url}") from exc
    return raw


def capture_sources(
    start_year: int,
    end_year: int,
    output_dir: str | Path,
    *,
    timeout: int = 30,
    session: requests.Session | None = None,
    captured_at_utc: str | None = None,
) -> dict[str, Any]:
    if start_year < 2000 or end_year < start_year:
        raise SourceCaptureError("invalid capture year range")

    client = session or requests.Session()
    staged: dict[str, bytes] = {}
    events = []
    source_rows: list[dict[str, Any]] = []

    for year in range(start_year, end_year + 1):
        url = BLS_YEAR_URL.format(year=year)
        raw = _fetch(client, url, timeout=timeout)
        text = raw.decode("utf-8-sig")
        parsed = parse_bls_year(text, year, url)
        events.extend(parsed)
        name = f"bls-{year}.html"
        staged[name] = raw
        source_rows.append(
            {
                "authority": "BLS",
                "year": year,
                "url": url,
                "snapshot_name": name,
                "sha256": _sha256(raw),
                "size_bytes": len(raw),
                "parsed_event_count": len(parsed),
            }
        )

    fed_raw = _fetch(client, FED_CALENDAR_URL, timeout=timeout)
    fed_text = fed_raw.decode("utf-8-sig")
    fed_events = parse_fomc_statement_links(fed_text, start_year=start_year, end_year=end_year)
    events.extend(fed_events)
    staged[FED_SNAPSHOT_NAME] = fed_raw
    source_rows.append(
        {
            "authority": "FEDERAL_RESERVE",
            "url": FED_CALENDAR_URL,
            "snapshot_name": FED_SNAPSHOT_NAME,
            "sha256": _sha256(fed_raw),
            "size_bytes": len(fed_raw),
            "parsed_event_count": len(fed_events),
        }
    )

    counts = _audit_counts(events, start_year, end_year)
    _validate_counts(counts)

    target = Path(output_dir).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    stage_dir = target.parent / f".{target.name}.capture-tmp"
    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    stage_dir.mkdir(parents=True)

    try:
        for name, raw in staged.items():
            (stage_dir / name).write_bytes(raw)
        manifest = {
            "schema_version": 1,
            "methodology": "OFFICIAL_CALENDAR_SOURCE_SNAPSHOT_V1",
            "source_authorities": ["BLS", "FEDERAL_RESERVE"],
            "start_year": start_year,
            "end_year": end_year,
            "captured_at_utc": captured_at_utc
            or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "counts_by_year": counts,
            "sources": source_rows,
            "approved": False,
            "live_trading_authorized": False,
            "real_capital_authorized": False,
        }
        (stage_dir / "source_manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if target.exists():
            shutil.rmtree(target)
        stage_dir.replace(target)
    except Exception:
        if stage_dir.exists():
            shutil.rmtree(stage_dir)
        raise

    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-year", type=int, default=DEFAULT_START_YEAR)
    parser.add_argument("--end-year", type=int, default=DEFAULT_END_YEAR)
    parser.add_argument(
        "--output-dir",
        default="data/research/calendar-sources/v1",
    )
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()
    try:
        manifest = capture_sources(
            args.start_year,
            args.end_year,
            args.output_dir,
            timeout=args.timeout,
        )
    except (SourceCaptureError, CalendarMaterializationError, requests.RequestException) as exc:
        parser.error(str(exc))
        return
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
