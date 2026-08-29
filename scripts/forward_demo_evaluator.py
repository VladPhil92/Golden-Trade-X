#!/usr/bin/env python3
"""Evaluate Golden Trade X forward-demo evidence from v2.90.4 telemetry.

The evaluator validates provenance and observation sufficiency only. It computes
closed-trade performance metrics but does not decide promotion; that decision is
left to ``forward_demo_gate.py`` under the immutable pre-registered policy.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.experiment_registry import RegistryValidationError, sha256_file
except ModuleNotFoundError:
    from experiment_registry import RegistryValidationError, sha256_file


def _load(path: str | Path) -> dict[str, Any]:
    target = Path(path).resolve()
    with target.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise RegistryValidationError(f"JSON root must be an object: {target}")
    return value


def _iso_utc(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise RegistryValidationError(f"{field} is required")
    raw = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise RegistryValidationError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise RegistryValidationError(f"{field} must include timezone")
    return parsed.astimezone(timezone.utc)


def _mql_utc(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise RegistryValidationError(f"{field} is missing")
    raw = value.strip()
    for fmt in ("%Y.%m.%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise RegistryValidationError(f"{field} has unsupported timestamp: {raw!r}")


def _readonly(db_path: Path) -> sqlite3.Connection:
    if not db_path.is_file():
        raise RegistryValidationError(f"telemetry database not found: {db_path}")
    conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _validate_schema(conn: sqlite3.Connection) -> None:
    names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    required = {"research_sessions", "execution_events", "position_outcomes"}
    missing = required - names
    if missing:
        raise RegistryValidationError("telemetry database missing table(s): " + ", ".join(sorted(missing)))


def _finite(value: Any, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise RegistryValidationError(f"{field} must be numeric")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise RegistryValidationError(f"{field} must be finite")
    return parsed


def _max_closed_trade_drawdown(realized_r: list[float]) -> float:
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for value in realized_r:
        cumulative += value
        peak = max(peak, cumulative)
        max_dd = max(max_dd, peak - cumulative)
    return max_dd


def evaluate_forward_demo(
    plan_path: str | Path,
    db_path: str | Path,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    plan_path = Path(plan_path).resolve()
    db_path = Path(db_path).resolve()
    plan = _load(plan_path)

    if plan.get("methodology") != "FORWARD_DEMO_FIXED_WINDOW_V1":
        raise RegistryValidationError("unsupported forward-demo plan methodology")
    if plan.get("live_trading_authorized") is not False:
        raise RegistryValidationError("forward-demo plan must explicitly deny live trading")

    runtime = plan.get("runtime_contract")
    frozen = plan.get("frozen_preset")
    policy = plan.get("forward_policy")
    window = plan.get("observation_window")
    if not all(isinstance(value, dict) for value in (runtime, frozen, policy, window)):
        raise RegistryValidationError("forward-demo plan is missing runtime/preset/policy/window contract")

    approved = policy.get("approved") is True
    start = _iso_utc(window.get("start_utc"), "observation_window.start_utc")
    end = _iso_utc(window.get("end_utc"), "observation_window.end_utc")
    if end <= start:
        raise RegistryValidationError("observation window is invalid")

    account = runtime.get("account")
    magic = runtime.get("magic")
    symbol = runtime.get("symbol")
    if isinstance(account, bool) or not isinstance(account, int):
        raise RegistryValidationError("runtime account must be integer")
    if isinstance(magic, bool) or not isinstance(magic, int):
        raise RegistryValidationError("runtime magic must be integer")
    if not isinstance(symbol, str) or not symbol:
        raise RegistryValidationError("runtime symbol is required")

    observation = policy.get("observation")
    if not isinstance(observation, dict):
        raise RegistryValidationError("forward policy observation contract missing")
    max_gap = observation.get("maximum_heartbeat_gap_seconds")
    min_trades = observation.get("minimum_closed_trades")
    stable_terminal = observation.get("require_stable_terminal_build")
    if isinstance(max_gap, bool) or not isinstance(max_gap, int) or max_gap < 3600:
        raise RegistryValidationError("invalid maximum_heartbeat_gap_seconds")
    if isinstance(min_trades, bool) or not isinstance(min_trades, int) or min_trades < 1:
        raise RegistryValidationError("invalid minimum_closed_trades")
    if not isinstance(stable_terminal, bool):
        raise RegistryValidationError("invalid require_stable_terminal_build")

    reasons: list[str] = []
    if not approved or plan.get("status") != "READY_FOR_FORWARD_DEMO_OBSERVATION":
        reasons.append("POLICY_NOT_APPROVED")

    with _readonly(db_path) as conn:
        _validate_schema(conn)
        raw_sessions = conn.execute(
            """
            SELECT event_id, utc_time, account, magic, symbol, timeframe, kind,
                   candidate_id, build_id, broker, terminal_build, trade_mode,
                   server_utc_offset_seconds, config_sha256
            FROM research_sessions
            WHERE account=? AND magic=? AND symbol=?
            ORDER BY utc_time, event_id
            """,
            (account, magic, symbol),
        ).fetchall()

        sessions: list[tuple[sqlite3.Row, datetime]] = []
        for row in raw_sessions:
            ts = _mql_utc(row["utc_time"], f"session {row['event_id']} utc_time")
            if start <= ts <= end:
                sessions.append((row, ts))

        if not sessions:
            reasons.append("NO_SESSION_EVIDENCE_IN_WINDOW")
            first_ts = last_ts = None
            max_observed_gap = None
            terminal_builds: list[int] = []
        else:
            first_ts = sessions[0][1]
            last_ts = sessions[-1][1]
            gaps = [max(0.0, (first_ts - start).total_seconds())]
            gaps.extend(
                max(0.0, (sessions[index][1] - sessions[index - 1][1]).total_seconds())
                for index in range(1, len(sessions))
            )
            gaps.append(max(0.0, (end - last_ts).total_seconds()))
            max_observed_gap = max(gaps)
            if max_observed_gap > max_gap:
                reasons.append("HEARTBEAT_COVERAGE_GAP")
            if sessions[0][0]["kind"] != "START":
                reasons.append("WINDOW_DOES_NOT_BEGIN_WITH_SESSION_START")
            if not any(row["kind"] == "START" for row, _ in sessions):
                reasons.append("SESSION_START_MISSING")
            invalid_kinds = sorted({row["kind"] for row, _ in sessions if row["kind"] not in {"START", "HEARTBEAT", "END"}})
            if invalid_kinds:
                reasons.append("UNKNOWN_SESSION_EVENT_KIND")

            expected = {
                "candidate_id": runtime.get("candidate_id"),
                "build_id": runtime.get("build_id"),
                "broker": runtime.get("broker"),
                "timeframe": runtime.get("timeframe"),
                "trade_mode": runtime.get("trade_mode"),
                "config_sha256": frozen.get("expected_runtime_config_sha256"),
            }
            for field, expected_value in expected.items():
                observed = {row[field] for row, _ in sessions}
                if observed != {expected_value}:
                    reasons.append(f"SESSION_{field.upper()}_DRIFT")

            terminal_builds = sorted({int(row["terminal_build"]) for row, _ in sessions if row["terminal_build"] is not None})
            if stable_terminal and len(terminal_builds) != 1:
                reasons.append("TERMINAL_BUILD_DRIFT")

        raw_outcomes = conn.execute(
            """
            SELECT close_time, position_id, net_pnl, realized_r
            FROM position_outcomes
            WHERE account=? AND magic=? AND symbol=?
            ORDER BY close_time, position_id
            """,
            (account, magic, symbol),
        ).fetchall()
        outcomes: list[sqlite3.Row] = []
        for row in raw_outcomes:
            ts = _mql_utc(row["close_time"], f"outcome {row['position_id']} close_time")
            if start <= ts <= end:
                outcomes.append(row)

        realized_r = [_finite(row["realized_r"], "realized_r") for row in outcomes]
        net_pnl = [_finite(row["net_pnl"], "net_pnl") for row in outcomes]
        trades = len(outcomes)
        if trades < min_trades:
            reasons.append("INSUFFICIENT_CLOSED_TRADES")

        total_r = sum(realized_r)
        expectancy_r = total_r / trades if trades else None
        gross_win_r = sum(value for value in realized_r if value > 0)
        gross_loss_r = -sum(value for value in realized_r if value < 0)
        profit_factor_r = gross_win_r / gross_loss_r if gross_loss_r > 0 else None
        wins = sum(1 for value in realized_r if value > 0)
        losses = sum(1 for value in realized_r if value < 0)
        zeros = trades - wins - losses
        closed_trade_dd_r = _max_closed_trade_drawdown(realized_r)

        raw_slippage = conn.execute(
            """
            SELECT event_time, slippage_points
            FROM execution_events
            WHERE account=? AND magic=? AND symbol=?
              AND action='OPEN' AND status='SERVER_CONFIRMED'
              AND slippage_points IS NOT NULL
            ORDER BY event_time
            """,
            (account, magic, symbol),
        ).fetchall()
        slippage: list[float] = []
        for row in raw_slippage:
            ts = _mql_utc(row["event_time"], "execution event_time")
            if start <= ts <= end:
                slippage.append(abs(_finite(row["slippage_points"], "slippage_points")))

    valid = not reasons
    result = {
        "schema_version": 1,
        "methodology": "FORWARD_DEMO_EVIDENCE_V1",
        "campaign_id": plan.get("campaign_id"),
        "status": "VALID_FORWARD_DEMO_EVIDENCE" if valid else "INVALID_FORWARD_DEMO_EVIDENCE",
        "valid": valid,
        "decision_scope": "FORWARD_DEMO_EVIDENCE_ONLY",
        "live_trading_authorized": False,
        "reasons": reasons,
        "plan_sha256": sha256_file(plan_path),
        "telemetry_db_sha256": sha256_file(db_path),
        "candidate": plan.get("candidate"),
        "runtime_contract": runtime,
        "provenance": {
            "session_event_count": len(sessions) if 'sessions' in locals() else 0,
            "first_session_utc": first_ts.isoformat().replace("+00:00", "Z") if first_ts else None,
            "last_session_utc": last_ts.isoformat().replace("+00:00", "Z") if last_ts else None,
            "maximum_observed_coverage_gap_seconds": max_observed_gap,
            "terminal_builds": terminal_builds,
            "expected_runtime_config_sha256": frozen.get("expected_runtime_config_sha256"),
        },
        "summary": {
            "closed_trades": trades,
            "net_pnl": sum(net_pnl),
            "total_realized_r": total_r,
            "expectancy_r": expectancy_r,
            "profit_factor_r": profit_factor_r,
            "win_rate": (wins / trades) if trades else None,
            "wins": wins,
            "losses": losses,
            "zeros": zeros,
            "closed_trade_max_drawdown_r": closed_trade_dd_r,
            "confirmed_open_slippage_observations": len(slippage),
            "avg_abs_open_slippage_points": (sum(slippage) / len(slippage)) if slippage else None,
            "max_abs_open_slippage_points": max(slippage) if slippage else None,
        },
    }

    if output_path is not None:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--db", required=True)
    parser.add_argument("--output")
    parser.add_argument("--require-valid", action="store_true")
    args = parser.parse_args()
    try:
        result = evaluate_forward_demo(args.plan, args.db, args.output)
    except (RegistryValidationError, sqlite3.Error) as exc:
        parser.error(str(exc))
        return
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    if args.require_valid and not result["valid"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
