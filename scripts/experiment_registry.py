#!/usr/bin/env python3
"""Golden Trade X v2.90 — reproducible experiment registry.

The registry is intentionally fail-closed: an experiment cannot be accepted as
research evidence unless its provenance is complete and internally consistent.
Configuration identity is derived only from execution-relevant metadata plus the
exact preset SHA-256. Human notes and research annotations never create a fake
new execution identity.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
STATUS_VALUES = {"PLANNED", "PREPARED", "RUNNING", "COMPLETED", "FAILED", "INVALID"}
SOURCE_TYPES = {"strategy_tester", "demo", "forward_demo", "live", "other"}
SHA40_RE = re.compile(r"^[0-9a-f]{40}$")

# Only fields capable of changing the actual execution or its market/tester
# provenance belong to the experiment fingerprint. Notes and ablation labels do
# not, otherwise relabelling the same run could manufacture a new observation.
IDENTITY_FIELDS = (
    "schema_version",
    "git_sha",
    "preset_sha256",
    "broker",
    "symbol",
    "timeframe",
    "period_start",
    "period_end",
    "source_type",
    "mt5_build",
    "modelling",
    "tester_model",
    "expert",
    "expert_parameters",
    "execution_mode",
    "portable_mode",
    "deposit",
    "currency",
    "leverage",
    "spread_mode",
    "commission",
    "swap_mode",
    "slippage_points",
    "optimization",
    "forward_mode",
    "forward_mode_code",
)


class RegistryValidationError(ValueError):
    """Raised when experiment provenance is incomplete or contradictory."""


@dataclass(frozen=True)
class ExperimentIdentity:
    experiment_id: str
    fingerprint: str
    preset_sha256: str


def sha256_file(path: str | Path) -> str:
    target = Path(path)
    if not target.is_file():
        raise RegistryValidationError(f"file not found: {target}")
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _parse_iso_date(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RegistryValidationError(f"{field} must be ISO-8601: {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _positive_number(spec: dict[str, Any], key: str) -> float:
    value = spec.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
        raise RegistryValidationError(f"{key} must be a finite number")
    if float(value) <= 0:
        raise RegistryValidationError(f"{key} must be > 0")
    return float(value)


def _nonnegative_int(spec: dict[str, Any], key: str, *, required: bool = True, default: int = 0) -> int:
    if key not in spec:
        if required:
            raise RegistryValidationError(f"missing required field: {key}")
        return default
    value = spec[key]
    if isinstance(value, bool):
        raise RegistryValidationError(f"{key} must be an integer >= 0")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise RegistryValidationError(f"{key} must be an integer >= 0") from exc
    if str(value).strip() not in {str(parsed), f"+{parsed}"} and not isinstance(value, int):
        raise RegistryValidationError(f"{key} must be an integer >= 0")
    if parsed < 0:
        raise RegistryValidationError(f"{key} must be an integer >= 0")
    return parsed


def normalize_spec(spec: dict[str, Any], base_dir: str | Path | None = None) -> tuple[dict[str, Any], str]:
    base = Path(base_dir or ".").resolve()
    required_text = (
        "git_sha",
        "preset_path",
        "broker",
        "symbol",
        "timeframe",
        "period_start",
        "period_end",
        "source_type",
        "mt5_build",
        "modelling",
    )
    for key in required_text:
        value = spec.get(key)
        if not isinstance(value, str) or not value.strip():
            raise RegistryValidationError(f"missing required field: {key}")

    git_sha = spec["git_sha"].strip().lower()
    if not SHA40_RE.fullmatch(git_sha):
        raise RegistryValidationError("git_sha must be a full 40-character hexadecimal SHA")

    source_type = spec["source_type"].strip().lower()
    if source_type not in SOURCE_TYPES:
        raise RegistryValidationError(f"unsupported source_type: {source_type}")

    start = _parse_iso_date(spec["period_start"], "period_start")
    end = _parse_iso_date(spec["period_end"], "period_end")
    if end <= start:
        raise RegistryValidationError("period_end must be strictly after period_start")

    preset_path = Path(spec["preset_path"])
    if not preset_path.is_absolute():
        preset_path = base / preset_path
    preset_sha256 = sha256_file(preset_path)

    deposit = _positive_number(spec, "deposit")
    leverage = _positive_number(spec, "leverage")
    if not float(leverage).is_integer():
        raise RegistryValidationError("leverage must be an integer ratio denominator")

    tester_model: int | None = None
    expert: str | None = None
    expert_parameters: str | None = None
    execution_mode: int | None = None
    forward_mode_code: int | None = None
    portable_mode: bool | None = None
    if source_type == "strategy_tester":
        for key in ("expert", "expert_parameters"):
            value = spec.get(key)
            if not isinstance(value, str) or not value.strip():
                raise RegistryValidationError(f"missing required field: {key}")
        tester_model = _nonnegative_int(spec, "tester_model")
        execution_mode = _nonnegative_int(spec, "execution_mode", required=False, default=0)
        forward_mode_code = _nonnegative_int(spec, "forward_mode_code", required=False, default=0)
        expert = spec["expert"].strip()
        expert_parameters = spec["expert_parameters"].strip()
        portable_value = spec.get("portable_mode", True)
        if not isinstance(portable_value, bool):
            raise RegistryValidationError("portable_mode must be true/false")
        portable_mode = portable_value

    changed_parameter = spec.get("changed_parameter")
    changed_from = spec.get("changed_from")
    changed_to = spec.get("changed_to")
    if any(value is not None for value in (changed_parameter, changed_from, changed_to)):
        if not isinstance(changed_parameter, str) or not changed_parameter.strip():
            raise RegistryValidationError("changed_parameter is required for an ablation/variant experiment")
        if changed_from is None or changed_to is None:
            raise RegistryValidationError("changed_from and changed_to are required with changed_parameter")
        if changed_from == changed_to:
            raise RegistryValidationError("changed_from and changed_to must differ")

    normalized = {
        "schema_version": SCHEMA_VERSION,
        "git_sha": git_sha,
        "preset_path": Path(spec["preset_path"]).as_posix(),
        "preset_sha256": preset_sha256,
        "broker": spec["broker"].strip(),
        "symbol": spec["symbol"].strip(),
        "timeframe": spec["timeframe"].strip().upper(),
        "period_start": start.isoformat().replace("+00:00", "Z"),
        "period_end": end.isoformat().replace("+00:00", "Z"),
        "source_type": source_type,
        "mt5_build": spec["mt5_build"].strip(),
        "modelling": spec["modelling"].strip(),
        "tester_model": tester_model,
        "expert": expert,
        "expert_parameters": expert_parameters,
        "execution_mode": execution_mode,
        "portable_mode": portable_mode,
        "deposit": deposit,
        "currency": str(spec.get("currency", "USD")).strip().upper(),
        "leverage": int(leverage),
        "spread_mode": str(spec.get("spread_mode", "current")).strip(),
        "commission": spec.get("commission"),
        "swap_mode": spec.get("swap_mode"),
        "slippage_points": float(spec.get("slippage_points", 0.0)),
        "optimization": bool(spec.get("optimization", False)),
        "forward_mode": str(spec.get("forward_mode", "disabled")).strip(),
        "forward_mode_code": forward_mode_code,
        "parent_experiment_id": spec.get("parent_experiment_id"),
        "changed_parameter": changed_parameter.strip() if isinstance(changed_parameter, str) else None,
        "changed_from": changed_from,
        "changed_to": changed_to,
        "notes": str(spec.get("notes", "")).strip(),
    }
    if normalized["slippage_points"] < 0 or not math.isfinite(normalized["slippage_points"]):
        raise RegistryValidationError("slippage_points must be finite and >= 0")
    if not normalized["currency"]:
        raise RegistryValidationError("currency cannot be empty")

    return normalized, preset_sha256


def identity_for(normalized: dict[str, Any]) -> ExperimentIdentity:
    missing = [key for key in IDENTITY_FIELDS if key not in normalized]
    if missing:
        raise RegistryValidationError(f"normalized spec missing identity fields: {', '.join(missing)}")
    identity_payload = {key: normalized[key] for key in IDENTITY_FIELDS}
    fingerprint = hashlib.sha256(_canonical_json(identity_payload).encode("utf-8")).hexdigest()
    return ExperimentIdentity(
        experiment_id=f"gtx-{fingerprint[:16]}",
        fingerprint=fingerprint,
        preset_sha256=normalized["preset_sha256"],
    )


def connect_registry(path: str | Path) -> sqlite3.Connection:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(target)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS experiments (
            experiment_id TEXT PRIMARY KEY,
            fingerprint TEXT NOT NULL UNIQUE,
            schema_version INTEGER NOT NULL,
            status TEXT NOT NULL,
            registered_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            spec_json TEXT NOT NULL,
            artifacts_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    return connection


def register_experiment(
    connection: sqlite3.Connection,
    spec: dict[str, Any],
    base_dir: str | Path | None = None,
    status: str = "PLANNED",
) -> dict[str, Any]:
    status = status.upper()
    if status not in STATUS_VALUES:
        raise RegistryValidationError(f"invalid status: {status}")
    normalized, _ = normalize_spec(spec, base_dir=base_dir)
    identity = identity_for(normalized)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    spec_json = _canonical_json(normalized)

    existing = connection.execute(
        "SELECT * FROM experiments WHERE fingerprint = ?", (identity.fingerprint,)
    ).fetchone()
    if existing is None:
        connection.execute(
            """
            INSERT INTO experiments(
                experiment_id, fingerprint, schema_version, status,
                registered_at, updated_at, spec_json, artifacts_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, '{}')
            """,
            (
                identity.experiment_id,
                identity.fingerprint,
                SCHEMA_VERSION,
                status,
                now,
                now,
                spec_json,
            ),
        )
        connection.commit()
    return get_experiment(connection, identity.experiment_id)


def get_experiment(connection: sqlite3.Connection, experiment_id: str) -> dict[str, Any]:
    row = connection.execute(
        "SELECT * FROM experiments WHERE experiment_id = ?", (experiment_id,)
    ).fetchone()
    if row is None:
        raise RegistryValidationError(f"unknown experiment_id: {experiment_id}")
    return {
        "experiment_id": row["experiment_id"],
        "fingerprint": row["fingerprint"],
        "schema_version": row["schema_version"],
        "status": row["status"],
        "registered_at": row["registered_at"],
        "updated_at": row["updated_at"],
        "spec": json.loads(row["spec_json"]),
        "artifacts": json.loads(row["artifacts_json"]),
    }


def set_status(connection: sqlite3.Connection, experiment_id: str, status: str) -> dict[str, Any]:
    status = status.upper()
    if status not in STATUS_VALUES:
        raise RegistryValidationError(f"invalid status: {status}")
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    cursor = connection.execute(
        "UPDATE experiments SET status = ?, updated_at = ? WHERE experiment_id = ?",
        (status, now, experiment_id),
    )
    if cursor.rowcount != 1:
        raise RegistryValidationError(f"unknown experiment_id: {experiment_id}")
    connection.commit()
    return get_experiment(connection, experiment_id)


def attach_artifact(
    connection: sqlite3.Connection,
    experiment_id: str,
    name: str,
    path: str | Path,
) -> dict[str, Any]:
    if not name.strip():
        raise RegistryValidationError("artifact name cannot be empty")
    record = get_experiment(connection, experiment_id)
    artifact_path = Path(path)
    artifact = {
        "path": artifact_path.as_posix(),
        "sha256": sha256_file(artifact_path),
        "size": artifact_path.stat().st_size,
    }
    artifacts = dict(record["artifacts"])
    artifacts[name.strip()] = artifact
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    connection.execute(
        "UPDATE experiments SET artifacts_json = ?, updated_at = ? WHERE experiment_id = ?",
        (_canonical_json(artifacts), now, experiment_id),
    )
    connection.commit()
    return get_experiment(connection, experiment_id)


def load_spec(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise RegistryValidationError("experiment spec root must be a JSON object")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="data/research/experiments.sqlite")
    sub = parser.add_subparsers(dest="command", required=True)

    register_cmd = sub.add_parser("register")
    register_cmd.add_argument("--spec", required=True)
    register_cmd.add_argument("--status", default="PLANNED")

    show_cmd = sub.add_parser("show")
    show_cmd.add_argument("experiment_id")

    status_cmd = sub.add_parser("status")
    status_cmd.add_argument("experiment_id")
    status_cmd.add_argument("status")

    artifact_cmd = sub.add_parser("artifact")
    artifact_cmd.add_argument("experiment_id")
    artifact_cmd.add_argument("name")
    artifact_cmd.add_argument("path")

    args = parser.parse_args()
    connection = connect_registry(args.db)
    try:
        if args.command == "register":
            spec_path = Path(args.spec)
            result = register_experiment(
                connection,
                load_spec(spec_path),
                base_dir=spec_path.parent,
                status=args.status,
            )
        elif args.command == "show":
            result = get_experiment(connection, args.experiment_id)
        elif args.command == "status":
            result = set_status(connection, args.experiment_id, args.status)
        else:
            result = attach_artifact(connection, args.experiment_id, args.name, args.path)
    except RegistryValidationError as exc:
        parser.error(str(exc))
        return
    finally:
        connection.close()
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
