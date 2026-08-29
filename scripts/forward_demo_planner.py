#!/usr/bin/env python3
"""Plan a fixed-window Golden Trade X forward-demo observation campaign.

The planner consumes a positive v2.90.4 readiness decision, the exact frozen
preset that passed OOS/robustness, an immutable observation policy and an
explicit demo environment. It derives the runtime configuration fingerprint
expected from the preset before any forward evidence is observed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.experiment_registry import RegistryValidationError, sha256_file
except ModuleNotFoundError:
    from experiment_registry import RegistryValidationError, sha256_file

PLAN_SCHEMA_VERSION = 1
_BUILD_RE = re.compile(r"^[0-9a-fA-F]{40}$")

SNAPSHOT_FIELDS: tuple[tuple[str, str], ...] = (
    ("InpMagicNumber", "int"),
    ("InpEmaFast", "int"),
    ("InpEmaSlow", "int"),
    ("InpRsiPeriod", "int"),
    ("InpRsiUpper", "float"),
    ("InpRsiLower", "float"),
    ("InpRsiLongMin", "float"),
    ("InpRsiShortMax", "float"),
    ("InpTimeframe", "int"),
    ("InpAtrPeriod", "int"),
    ("InpAtrMinRatio", "float"),
    ("InpAtrMaxRatio", "float"),
    ("InpAdxPeriod", "int"),
    ("InpAdxMinLevel", "float"),
    ("InpMinTickVolume", "int"),
    ("InpUseHtfFilter", "bool"),
    ("InpHtfEmaPeriod", "int"),
    ("InpUseRegimeFilter", "bool"),
    ("InpUseSmcFilter", "bool"),
    ("InpMinConfidence", "int"),
    ("InpConfWeightBase", "int"),
    ("InpConfWeightRegime", "int"),
    ("InpConfWeightSmc", "int"),
    ("InpConfWeightHtf", "int"),
    ("InpConfWeightFib", "int"),
    ("InpRiskPercent", "float"),
    ("InpMaxDailyDD", "float"),
    ("InpMaxWeeklyDD", "float"),
    ("InpMaxMonthlyDD", "float"),
    ("InpMaxConsecLosses", "int"),
    ("InpMaxPositions", "int"),
    ("InpAtrSlMultiplier", "float"),
    ("InpAtrTpMultiplier", "float"),
    ("InpMaxSpreadPoints", "float"),
    ("InpCpThresholdPct", "float"),
    ("InpMinInitialRR", "float"),
    ("InpUseTrailing", "bool"),
    ("InpTrailAtrMult", "float"),
    ("InpUseBreakEven", "bool"),
    ("InpBreakEvenR", "float"),
    ("InpUsePartialTP", "bool"),
    ("InpPartialTPR", "float"),
    ("InpPartialTPPct", "float"),
    ("InpUseEqCurveFilter", "bool"),
    ("InpEqCurvePeriod", "int"),
    ("InpUseKelly", "bool"),
    ("InpKellyFraction", "float"),
    ("InpKellyMinTrades", "int"),
    ("InpUsePortfolioCap", "bool"),
    ("InpMaxPortfolioRiskPct", "float"),
    ("InpOrderMaxRetries", "int"),
    ("InpOrderRetryDelay", "int"),
    ("InpMinMarginLevel", "float"),
    ("InpUseSessionFilter", "bool"),
    ("InpStartHour", "int"),
    ("InpEndHour", "int"),
    ("InpCloseOnFriday", "bool"),
    ("InpFridayCloseHour", "int"),
    ("InpUseNewsFilter", "bool"),
    ("InpNewsBufferBefore", "int"),
    ("InpNewsBufferAfter", "int"),
    ("InpNewsCalendarPolicy", "int"),
    ("InpPauseForNews", "bool"),
)

_TIMEFRAME_LABELS = {
    1: "PERIOD_M1",
    2: "PERIOD_M2",
    3: "PERIOD_M3",
    4: "PERIOD_M4",
    5: "PERIOD_M5",
    6: "PERIOD_M6",
    10: "PERIOD_M10",
    12: "PERIOD_M12",
    15: "PERIOD_M15",
    20: "PERIOD_M20",
    30: "PERIOD_M30",
    60: "PERIOD_H1",
    120: "PERIOD_H2",
    180: "PERIOD_H3",
    240: "PERIOD_H4",
    360: "PERIOD_H6",
    480: "PERIOD_H8",
    720: "PERIOD_H12",
    1440: "PERIOD_D1",
    10080: "PERIOD_W1",
    43200: "PERIOD_MN1",
}


def _load(path: str | Path) -> dict[str, Any]:
    target = Path(path).resolve()
    with target.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise RegistryValidationError(f"JSON root must be an object: {target}")
    return value


def _resolve(base: Path, raw: Any, field: str) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise RegistryValidationError(f"{field} is required")
    path = Path(raw)
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def _utc(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise RegistryValidationError(f"{field} is required")
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise RegistryValidationError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise RegistryValidationError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _parse_set(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_no, raw_line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith(";") or line.startswith("#"):
            continue
        if "=" not in line:
            raise RegistryValidationError(f"{path}:{line_no}: invalid preset line")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or key in values:
            raise RegistryValidationError(f"{path}:{line_no}: duplicate/empty preset key {key!r}")
        values[key] = value
    return values


def _canonical_value(key: str, kind: str, raw: str) -> str:
    try:
        if kind == "int":
            value = float(raw)
            if not value.is_integer():
                raise ValueError
            return str(int(value))
        if kind == "float":
            return f"{float(raw):.8f}"
        if kind == "bool":
            normalized = raw.strip().lower()
            if normalized in {"true", "1"}:
                return "1"
            if normalized in {"false", "0"}:
                return "0"
    except ValueError as exc:
        raise RegistryValidationError(f"invalid {kind} value for {key}: {raw!r}") from exc
    raise RegistryValidationError(f"unsupported snapshot field type: {kind}")


def canonical_runtime_snapshot(preset_path: str | Path) -> tuple[str, dict[str, str]]:
    path = Path(preset_path).resolve()
    values = _parse_set(path)
    missing = [key for key, _ in SNAPSHOT_FIELDS if key not in values]
    if missing:
        raise RegistryValidationError(
            "frozen preset is missing runtime-affecting input(s): " + ", ".join(missing)
        )
    canonical: dict[str, str] = {}
    for key, kind in SNAPSHOT_FIELDS:
        canonical[key] = _canonical_value(key, kind, values[key])
    snapshot = "|".join(f"{key}={canonical[key]}" for key, _ in SNAPSHOT_FIELDS)
    return snapshot, canonical


def _validate_policy(policy: dict[str, Any]) -> dict[str, Any]:
    policy_id = policy.get("policy_id")
    approved = policy.get("approved")
    observation = policy.get("observation")
    criteria = policy.get("criteria")
    if not isinstance(policy_id, str) or not policy_id.strip():
        raise RegistryValidationError("forward-demo policy requires policy_id")
    if not isinstance(approved, bool):
        raise RegistryValidationError("forward-demo policy approved must be true/false")
    if not isinstance(observation, dict):
        raise RegistryValidationError("forward-demo policy observation must be an object")
    if not isinstance(criteria, list) or not criteria:
        raise RegistryValidationError("forward-demo policy criteria must be non-empty")

    min_days = observation.get("minimum_calendar_days")
    min_trades = observation.get("minimum_closed_trades")
    max_gap = observation.get("maximum_heartbeat_gap_seconds")
    require_mode = observation.get("require_trade_mode")
    stable_build = observation.get("require_stable_terminal_build")
    if not isinstance(min_days, (int, float)) or isinstance(min_days, bool) or float(min_days) <= 0:
        raise RegistryValidationError("minimum_calendar_days must be > 0")
    if isinstance(min_trades, bool) or not isinstance(min_trades, int) or min_trades < 1:
        raise RegistryValidationError("minimum_closed_trades must be an integer >= 1")
    if isinstance(max_gap, bool) or not isinstance(max_gap, int) or max_gap < 3600:
        raise RegistryValidationError("maximum_heartbeat_gap_seconds must be >= 3600")
    if require_mode != "DEMO":
        raise RegistryValidationError("forward-demo policy must require DEMO trade mode")
    if not isinstance(stable_build, bool):
        raise RegistryValidationError("require_stable_terminal_build must be true/false")

    for rule in criteria:
        if not isinstance(rule, dict):
            raise RegistryValidationError("forward-demo criterion must be an object")
        if not isinstance(rule.get("metric"), str) or not rule["metric"].strip():
            raise RegistryValidationError("forward-demo criterion requires metric")
        if rule.get("operator") not in {">", ">=", "<", "<=", "=="}:
            raise RegistryValidationError("unsupported forward-demo criterion operator")
        value = rule.get("value")
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise RegistryValidationError("forward-demo criterion value must be numeric")

    return {
        "policy_id": policy_id.strip(),
        "approved": approved,
        "observation": {
            "minimum_calendar_days": float(min_days),
            "minimum_closed_trades": min_trades,
            "maximum_heartbeat_gap_seconds": max_gap,
            "require_trade_mode": "DEMO",
            "require_stable_terminal_build": stable_build,
        },
        "criteria": criteria,
    }


def generate_forward_demo_plan(config_path: str | Path, output_path: str | Path) -> dict[str, Any]:
    config_path = Path(config_path).resolve()
    config = _load(config_path)
    base = config_path.parent

    campaign_id = config.get("campaign_id")
    if not isinstance(campaign_id, str) or not campaign_id.strip():
        raise RegistryValidationError("campaign_id is required")

    readiness_path = _resolve(base, config.get("readiness_path"), "readiness_path")
    policy_path = _resolve(base, config.get("forward_policy_path"), "forward_policy_path")
    preset_path = _resolve(base, config.get("frozen_preset_path"), "frozen_preset_path")
    readiness = _load(readiness_path)
    policy = _load(policy_path)
    validated_policy = _validate_policy(policy)

    if readiness.get("methodology") != "FORWARD_DEMO_READINESS_V1":
        raise RegistryValidationError("unsupported readiness methodology")
    if readiness.get("decision") != "READY_FOR_FORWARD_DEMO" or readiness.get("ready") is not True:
        raise RegistryValidationError("candidate is not READY_FOR_FORWARD_DEMO")
    if readiness.get("live_trading_authorized") is not False:
        raise RegistryValidationError("readiness must explicitly deny live trading")
    candidate = readiness.get("candidate")
    if not isinstance(candidate, dict):
        raise RegistryValidationError("readiness candidate identity is missing")
    candidate_id = candidate.get("experiment_id")
    preset_sha = candidate.get("preset_sha256")
    if not isinstance(candidate_id, str) or not candidate_id:
        raise RegistryValidationError("readiness candidate experiment_id is required")
    if not isinstance(preset_sha, str) or not preset_sha:
        raise RegistryValidationError("readiness candidate preset_sha256 is required")
    if sha256_file(preset_path) != preset_sha:
        raise RegistryValidationError("frozen preset bytes do not match readiness candidate")

    build_id = config.get("build_id")
    if not isinstance(build_id, str) or not _BUILD_RE.fullmatch(build_id):
        raise RegistryValidationError("build_id must be an exact 40-character Git SHA")

    environment = config.get("demo_environment")
    if not isinstance(environment, dict):
        raise RegistryValidationError("demo_environment must be an object")
    account = environment.get("account")
    broker = environment.get("broker")
    symbol = environment.get("symbol")
    timeframe = environment.get("timeframe")
    if isinstance(account, bool) or not isinstance(account, int) or account <= 0:
        raise RegistryValidationError("demo_environment.account must be a positive integer")
    if not isinstance(broker, str) or not broker.strip():
        raise RegistryValidationError("demo_environment.broker is required")
    if not isinstance(symbol, str) or not symbol.strip():
        raise RegistryValidationError("demo_environment.symbol is required")
    if not isinstance(timeframe, str) or not timeframe.strip():
        raise RegistryValidationError("demo_environment.timeframe is required")

    start = _utc(config.get("observation_start_utc"), "observation_start_utc")
    end = _utc(config.get("observation_end_utc"), "observation_end_utc")
    if end <= start:
        raise RegistryValidationError("observation_end_utc must be after observation_start_utc")
    planned_days = (end - start).total_seconds() / 86400.0
    if planned_days < validated_policy["observation"]["minimum_calendar_days"]:
        raise RegistryValidationError("planned observation window is shorter than policy minimum_calendar_days")

    snapshot, canonical = canonical_runtime_snapshot(preset_path)
    expected_config_sha = hashlib.sha256(snapshot.encode("utf-8")).hexdigest()
    magic = int(canonical["InpMagicNumber"])
    expected_tf = _TIMEFRAME_LABELS.get(int(canonical["InpTimeframe"]))
    if expected_tf is None:
        raise RegistryValidationError("preset timeframe cannot be mapped to an MQL5 runtime label")
    if timeframe.strip() != expected_tf:
        raise RegistryValidationError(
            f"demo_environment.timeframe {timeframe!r} differs from frozen preset {expected_tf!r}"
        )

    result = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "methodology": "FORWARD_DEMO_FIXED_WINDOW_V1",
        "campaign_id": campaign_id.strip(),
        "status": (
            "READY_FOR_FORWARD_DEMO_OBSERVATION"
            if validated_policy["approved"]
            else "DRAFT_POLICY_UNAPPROVED"
        ),
        "decision_scope": "DEMO_OBSERVATION_ONLY",
        "live_trading_authorized": False,
        "candidate": {
            "experiment_id": candidate_id,
            "preset_sha256": preset_sha,
            "source_fold_id": candidate.get("source_fold_id"),
            "readiness_sha256": sha256_file(readiness_path),
        },
        "forward_policy": {
            "path": Path(str(config.get("forward_policy_path"))).as_posix(),
            "sha256": sha256_file(policy_path),
            **validated_policy,
        },
        "frozen_preset": {
            "path": Path(str(config.get("frozen_preset_path"))).as_posix(),
            "sha256": preset_sha,
            "expected_runtime_config_sha256": expected_config_sha,
            "expected_runtime_config_snapshot": snapshot,
        },
        "runtime_contract": {
            "candidate_id": candidate_id,
            "build_id": build_id.lower(),
            "account": account,
            "magic": magic,
            "broker": broker.strip(),
            "symbol": symbol.strip(),
            "timeframe": timeframe.strip(),
            "trade_mode": "DEMO",
        },
        "observation_window": {
            "start_utc": start.isoformat().replace("+00:00", "Z"),
            "end_utc": end.isoformat().replace("+00:00", "Z"),
            "planned_calendar_days": planned_days,
        },
    }

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        result = generate_forward_demo_plan(args.config, args.output)
    except RegistryValidationError as exc:
        parser.error(str(exc))
        return
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
