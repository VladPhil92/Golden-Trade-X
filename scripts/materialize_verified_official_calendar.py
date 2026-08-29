#!/usr/bin/env python3
"""Materialize the official economic calendar only from verified source snapshots."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from scripts.materialize_official_calendar import (
        DEFAULT_END_YEAR,
        DEFAULT_START_YEAR,
        CalendarMaterializationError,
    )
    from scripts.official_calendar_snapshot import materialize_verified_snapshot
except ModuleNotFoundError:
    from materialize_official_calendar import (
        DEFAULT_END_YEAR,
        DEFAULT_START_YEAR,
        CalendarMaterializationError,
    )
    from official_calendar_snapshot import materialize_verified_snapshot


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-year", type=int, default=DEFAULT_START_YEAR)
    parser.add_argument("--end-year", type=int, default=DEFAULT_END_YEAR)
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--audit-output", required=True)
    args = parser.parse_args()
    try:
        document, audit = materialize_verified_snapshot(
            args.start_year,
            args.end_year,
            args.source_dir,
        )
    except CalendarMaterializationError as exc:
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
