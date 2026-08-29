#!/usr/bin/env python3
"""Fail-closed preflight for an official Golden Trade X validation campaign.

This gate verifies repository-controlled inputs that must be complete before any Strategy
Tester evidence is generated. Broker credentials and runtime attestation are intentionally
checked later on the Windows runner and are never stored here.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.economic_calendar_contract import (
        EconomicCalendarValidationError,
        load_calendar_contract,
        verify_generated_include,
    )
except ModuleNotFoundError:
    from economic_calendar_contract import (
        EconomicCalendarValidationError,
        load_calendar_contract,
        verify_generated_include,
    )


class CampaignReadinessError(ValueError):
    pass


def _load(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise CampaignReadinessError(f"JSON root must be an object: {path}")
    return value


def _resolve(base: Path, raw: Any, field: str) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise CampaignReadinessError(f"{field} is required")
    target = Path(raw)
    if not target.is_absolute():
        target = base / target
    target = target.resolve()
    try:
        target.relative_to(base.resolve())
    except ValueError as exc:
        raise CampaignReadinessError(f"{field} escapes the campaign config root") from exc
    if not target.is_file():
        raise CampaignReadinessError(f"{field} not found: {target}")
    return target


def _day_start(raw: Any) -> datetime:
    if not isinstance(raw, str):
        raise CampaignReadinessError("walk-forward date must be a YYYY-MM-DD string")
    try:
        return datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise CampaignReadinessError(f"invalid walk-forward date: {raw!r}") from exc


def evaluate_campaign_readiness(
    campaign_config_path: str | Path,
    generated_calendar_include: str | Path,
) -> dict[str, Any]:
    campaign_path = Path(campaign_config_path).resolve()
    campaign = _load(campaign_path)
    base = campaign_path.parent

    calendar_path = _resolve(base, campaign.get("economic_calendar_path"), "economic_calendar_path")
    walk_path = _resolve(base, campaign.get("walk_forward_config_path"), "walk_forward_config_path")
    lock_path = _resolve(base, campaign.get("python_runtime_lock_path"), "python_runtime_lock_path")

    try:
        calendar, calendar_file_sha, calendar_canonical_sha = load_calendar_contract(calendar_path)
        verify_generated_include(calendar_path, generated_calendar_include)
    except EconomicCalendarValidationError as exc:
        raise CampaignReadinessError(str(exc)) from exc
    if calendar["approved"] is not True:
        raise CampaignReadinessError("economic calendar is not approved")

    walk = _load(walk_path)
    start = _day_start(walk.get("start_date"))
    end = _day_start(walk.get("end_date"))
    cal_start = datetime.fromisoformat(calendar["coverage"]["start_utc"].replace("Z", "+00:00"))
    cal_end = datetime.fromisoformat(calendar["coverage"]["end_utc"].replace("Z", "+00:00"))
    if cal_start > start or cal_end < end:
        raise CampaignReadinessError(
            "approved economic calendar does not cover the complete walk-forward period"
        )

    lock_lines = [
        line.strip()
        for line in lock_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not lock_lines:
        raise CampaignReadinessError("python runtime lock is empty")
    for line in lock_lines:
        marker = line.split(";", 1)[0].strip()
        if "==" not in marker or "~=" in marker or ">=" in marker or "<=" in marker:
            raise CampaignReadinessError(
                f"python runtime lock must use exact direct pins only: {line!r}"
            )

    campaign_id = campaign.get("campaign_id")
    if not isinstance(campaign_id, str) or not campaign_id.strip():
        raise CampaignReadinessError("campaign_id is required")
    if "DRAFT" in campaign_id.upper():
        raise CampaignReadinessError("official campaign_id must not contain DRAFT")

    return {
        "schema_version": 1,
        "methodology": "PRE_CAMPAIGN_READINESS_V1",
        "decision": "READY_TO_FREEZE",
        "ready": True,
        "campaign_id": campaign_id,
        "economic_calendar": {
            "calendar_id": calendar["calendar_id"],
            "file_sha256": calendar_file_sha,
            "canonical_sha256": calendar_canonical_sha,
            "event_count": len(calendar["events"]),
            "coverage": calendar["coverage"],
        },
        "python_runtime_lock": lock_path.name,
        "live_trading_authorized": False,
        "real_capital_authorized": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", required=True)
    parser.add_argument(
        "--calendar-include",
        default="MQL5/Include/GoldenTradeX/EconomicCalendarData.mqh",
    )
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        result = evaluate_campaign_readiness(args.campaign, args.calendar_include)
    except CampaignReadinessError as exc:
        parser.error(str(exc))
        return
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
