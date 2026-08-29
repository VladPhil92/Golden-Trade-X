#!/usr/bin/env python3
"""Fail-closed preflight for an official Golden Trade X validation campaign.

Repository-controlled inputs must be complete before Strategy Tester evidence is generated.
This gate validates the frozen policy bundle, approved DEMO execution environment, approved
source-backed economic calendar, generated MQL5 calendar include, exact runtime dependency
lock and non-placeholder robustness broker requirements. Runtime credentials/attestation
remain separate and are checked later on the Windows runner.
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
    from scripts.execution_environment import load_execution_environment_contract
    from scripts.experiment_registry import RegistryValidationError
    from scripts.official_policy_check import (
        OfficialPolicyValidationError,
        validate_official_policy_bundle,
    )
except ModuleNotFoundError:
    from economic_calendar_contract import (
        EconomicCalendarValidationError,
        load_calendar_contract,
        verify_generated_include,
    )
    from execution_environment import load_execution_environment_contract
    from experiment_registry import RegistryValidationError
    from official_policy_check import OfficialPolicyValidationError, validate_official_policy_bundle


class CampaignReadinessError(ValueError):
    pass


_PLACEHOLDER_MARKERS = ("REPLACE_WITH", "PLACEHOLDER", "TBD", "UNKNOWN")
_OFFICIAL_REFERENCES = {
    "walk_forward_config_path": "walk_forward_plan.v1.json",
    "robustness_policy_path": "robustness_policy.v1.json",
    "forward_policy_path": "forward_demo_policy.v1.json",
}


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


def _contains_placeholder(value: Any) -> bool:
    if isinstance(value, str):
        upper = value.upper()
        return any(marker in upper for marker in _PLACEHOLDER_MARKERS)
    if isinstance(value, list):
        return any(_contains_placeholder(item) for item in value)
    if isinstance(value, dict):
        return any(_contains_placeholder(item) for item in value.values())
    return False


def _validate_runtime_lock(path: Path) -> int:
    lock_lines = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not lock_lines:
        raise CampaignReadinessError("python runtime lock is empty")
    seen: set[str] = set()
    for line in lock_lines:
        marker = line.split(";", 1)[0].strip()
        if "==" not in marker or "~=" in marker or ">=" in marker or "<=" in marker:
            raise CampaignReadinessError(
                f"python runtime lock must use exact direct pins only: {line!r}"
            )
        package = marker.split("==", 1)[0].strip().lower()
        if not package or package in seen:
            raise CampaignReadinessError(f"python runtime lock has duplicate/invalid package: {line!r}")
        seen.add(package)
    if "metatrader5" not in seen:
        raise CampaignReadinessError("python runtime lock must pin MetaTrader5 exactly")
    return len(lock_lines)


def evaluate_campaign_readiness(
    campaign_config_path: str | Path,
    generated_calendar_include: str | Path,
) -> dict[str, Any]:
    campaign_path = Path(campaign_config_path).resolve()
    campaign = _load(campaign_path)
    base = campaign_path.parent

    campaign_id = campaign.get("campaign_id")
    if not isinstance(campaign_id, str) or not campaign_id.strip():
        raise CampaignReadinessError("campaign_id is required")
    if "DRAFT" in campaign_id.upper():
        raise CampaignReadinessError("official campaign_id must not contain DRAFT")

    for field, expected in _OFFICIAL_REFERENCES.items():
        if campaign.get(field) != expected:
            raise CampaignReadinessError(f"{field} must reference frozen {expected}")

    try:
        policy_bundle = validate_official_policy_bundle(base)
    except OfficialPolicyValidationError as exc:
        raise CampaignReadinessError(str(exc)) from exc

    environment_path = _resolve(
        base, campaign.get("execution_environment_path"), "execution_environment_path"
    )
    try:
        environment, environment_file_sha = load_execution_environment_contract(environment_path)
    except RegistryValidationError as exc:
        raise CampaignReadinessError(str(exc)) from exc
    if environment["approved"] is not True:
        raise CampaignReadinessError("execution environment is not approved")
    if environment["require_trade_mode"] != "DEMO" or environment["live_trading_authorized"] is not False:
        raise CampaignReadinessError("official execution environment must remain DEMO-only")

    robustness_template_path = _resolve(
        base, campaign.get("robustness_template_path"), "robustness_template_path"
    )
    robustness_template = _load(robustness_template_path)
    broker_requirements = robustness_template.get("broker_requirements")
    if not isinstance(broker_requirements, dict):
        raise CampaignReadinessError("robustness template requires broker_requirements")
    labels = broker_requirements.get("required_labels")
    minimum = broker_requirements.get("minimum_distinct_brokers")
    if not isinstance(labels, list) or not labels or not isinstance(minimum, int) or minimum < 2:
        raise CampaignReadinessError("robustness template requires at least two broker labels")
    if len(set(labels)) != len(labels) or len(labels) < minimum:
        raise CampaignReadinessError("robustness broker labels must be distinct and satisfy the minimum")
    if _contains_placeholder(labels):
        raise CampaignReadinessError("robustness broker labels still contain placeholders")

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

    runtime_pin_count = _validate_runtime_lock(lock_path)

    return {
        "schema_version": 2,
        "methodology": "PRE_CAMPAIGN_READINESS_V2",
        "decision": "READY_TO_FREEZE",
        "ready": True,
        "campaign_id": campaign_id.strip(),
        "policy_bundle_sha256": policy_bundle["bundle_sha256"],
        "execution_environment": {
            "environment_id": environment["environment_id"],
            "file_sha256": environment_file_sha,
            "broker_label": environment["broker_label"],
            "account_server": environment["account_server"],
            "mt5_build": environment["mt5_build"],
            "trade_mode": "DEMO",
        },
        "economic_calendar": {
            "calendar_id": calendar["calendar_id"],
            "file_sha256": calendar_file_sha,
            "canonical_sha256": calendar_canonical_sha,
            "event_count": len(calendar["events"]),
            "coverage": calendar["coverage"],
        },
        "robustness_brokers": sorted(labels),
        "python_runtime_lock": lock_path.name,
        "python_runtime_pin_count": runtime_pin_count,
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
