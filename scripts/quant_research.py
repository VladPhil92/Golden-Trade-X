#!/usr/bin/env python3
"""Golden Trade X v2.80 — quantitative research baseline gate.

This module consumes the v2.70 SQLite telemetry database in read-only mode and
produces a reproducible *descriptive* baseline. It deliberately separates three
states:

- INVALID_DATA: structural/semantic integrity violations were observed;
- INSUFFICIENT_EVIDENCE: data are internally consistent but do not meet the
  configured internal research floor or provenance requirements;
- READY_FOR_EXPLORATORY_RESEARCH: the configured floor is met.

None of these states constitutes profitability, statistical significance, OOS,
walk-forward, broker-robustness or forward-demo validation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sqlite3
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

REQUIRED_TABLES = {"signal_events", "execution_events", "position_outcomes"}
REQUIRED_MANIFEST_FIELDS = {
    "dataset_id",
    "source_type",
    "git_sha",
    "preset_sha256",
    "broker",
    "symbols",
    "timeframe",
    "period_start",
    "period_end",
}
ALLOWED_SOURCE_TYPES = {"strategy_tester", "demo", "forward_demo", "live", "other"}
REPORT_SCHEMA_VERSION = 1

INVALID_DATA = "INVALID_DATA"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
READY_FOR_EXPLORATORY_RESEARCH = "READY_FOR_EXPLORATORY_RESEARCH"
INSUFFICIENT_SEGMENT = "INSUFFICIENT_SEGMENT"
DESCRIPTIVE_SEGMENT = "DESCRIPTIVE_SEGMENT"


@dataclass(frozen=True)
class EvidenceThresholds:
    """Internal floors for exploratory research, not universal statistical rules."""

    min_outcomes: int = 100
    min_confidence_coverage: float = 0.95
    min_excursion_coverage: float = 0.99
    min_time_coverage: float = 0.95
    min_segment_outcomes: int = 30

    def validate(self) -> None:
        if self.min_outcomes < 1 or self.min_segment_outcomes < 1:
            raise ValueError("outcome thresholds must be positive")
        for name in ("min_confidence_coverage", "min_excursion_coverage", "min_time_coverage"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")


def open_readonly(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def validate_schema(conn: sqlite3.Connection) -> None:
    existing = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    missing = REQUIRED_TABLES - existing
    if missing:
        raise ValueError(f"telemetry database missing table(s): {', '.join(sorted(missing))}")


def load_manifest(path: Path | None) -> tuple[dict[str, Any] | None, list[str]]:
    if path is None:
        return None, ["research manifest was not supplied"]
    if not path.is_file():
        return None, [f"research manifest does not exist: {path}"]
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid research manifest JSON: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ValueError("research manifest must be a JSON object")

    errors: list[str] = []
    missing = sorted(REQUIRED_MANIFEST_FIELDS - set(manifest))
    if missing:
        errors.append(f"manifest missing field(s): {', '.join(missing)}")

    source_type = manifest.get("source_type")
    if source_type is not None and source_type not in ALLOWED_SOURCE_TYPES:
        errors.append(
            "manifest source_type must be one of: " + ", ".join(sorted(ALLOWED_SOURCE_TYPES))
        )

    git_sha = str(manifest.get("git_sha", ""))
    if git_sha and not _is_hex(git_sha, 7, 40):
        errors.append("manifest git_sha must be a 7-40 character hexadecimal Git commit id")

    preset_sha = str(manifest.get("preset_sha256", ""))
    if preset_sha and not _is_hex(preset_sha, 64, 64):
        errors.append("manifest preset_sha256 must be a 64 character SHA-256 hex digest")

    symbols = manifest.get("symbols")
    if symbols is not None:
        if not isinstance(symbols, list) or not symbols or not all(
            isinstance(symbol, str) and symbol.strip() for symbol in symbols
        ):
            errors.append("manifest symbols must be a non-empty array of non-empty strings")

    for field in REQUIRED_MANIFEST_FIELDS - {"symbols"}:
        if field in manifest and not str(manifest[field]).strip():
            errors.append(f"manifest field {field} must not be empty")

    for field in ("period_start", "period_end"):
        value = manifest.get(field)
        if value:
            try:
                _parse_datetime(str(value))
            except ValueError:
                errors.append(f"manifest {field} is not a recognized ISO/MT5 datetime")

    if manifest.get("period_start") and manifest.get("period_end"):
        try:
            if _parse_datetime(str(manifest["period_end"])) <= _parse_datetime(
                str(manifest["period_start"])
            ):
                errors.append("manifest period_end must be later than period_start")
        except ValueError:
            pass

    return manifest, errors


def _is_hex(value: str, minimum: int, maximum: int) -> bool:
    if not minimum <= len(value) <= maximum:
        return False
    return all(char in "0123456789abcdefABCDEF" for char in value)


def _parse_datetime(value: str) -> datetime:
    text = value.strip()
    if not text:
        raise ValueError("empty datetime")
    candidates = [text, text.replace(".", "-", 2)]
    formats = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d",
    )
    for candidate in candidates:
        try:
            return datetime.fromisoformat(candidate.replace("Z", "+00:00"))
        except ValueError:
            pass
        for fmt in formats:
            try:
                return datetime.strptime(candidate, fmt)
            except ValueError:
                continue
    raise ValueError(value)


def _finite(value: Any) -> bool:
    return value is not None and isinstance(value, (int, float)) and math.isfinite(float(value))


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _quantile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = (len(ordered) - 1) * q
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    weight = index - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _dataset_fingerprint(rows: Iterable[sqlite3.Row], manifest: dict[str, Any] | None) -> str:
    digest = hashlib.sha256()
    digest.update(b"GoldenTradeX-v2.80-baseline-v1\n")
    if manifest is not None:
        digest.update(
            json.dumps(manifest, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
        )
        digest.update(b"\n")
    for row in rows:
        digest.update(str(row["row_hash"]).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _outcome_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT row_hash, event_id, close_time, symbol, position_id, direction,
               entry_time, initial_risk_money, confidence, regime, mfe_r, mae_r,
               net_pnl, realized_r
        FROM position_outcomes
        ORDER BY COALESCE(close_time, ''), COALESCE(position_id, 0), row_hash
        """
    ).fetchall()


def evaluate_data_quality(
    conn: sqlite3.Connection,
    manifest: dict[str, Any] | None,
    manifest_errors: Sequence[str],
    thresholds: EvidenceThresholds,
) -> dict[str, Any]:
    thresholds.validate()
    validate_schema(conn)
    rows = _outcome_rows(conn)
    count = len(rows)

    integrity_errors: list[str] = []
    evidence_gaps: list[str] = list(manifest_errors)

    position_ids = [row["position_id"] for row in rows]
    null_position_ids = sum(position_id is None or int(position_id) <= 0 for position_id in position_ids)
    duplicate_position_ids = len([p for p in position_ids if p is not None]) - len(
        {int(p) for p in position_ids if p is not None}
    )
    if null_position_ids:
        integrity_errors.append(f"{null_position_ids} outcome row(s) have missing/invalid position_id")
    if duplicate_position_ids:
        integrity_errors.append(
            f"{duplicate_position_ids} duplicate final outcome row(s) by position_id"
        )

    invalid_risk = 0
    invalid_realized = 0
    invalid_net_pnl = 0
    invalid_excursion = 0
    invalid_confidence = 0
    invalid_direction = 0
    confidence_known = 0
    excursion_complete = 0
    time_complete = 0
    observed_symbols: set[str] = set()

    for row in rows:
        symbol = (row["symbol"] or "").strip()
        if symbol:
            observed_symbols.add(symbol)

        risk = row["initial_risk_money"]
        if not _finite(risk) or float(risk) <= 0:
            invalid_risk += 1

        realized = row["realized_r"]
        if not _finite(realized):
            invalid_realized += 1

        if not _finite(row["net_pnl"]):
            invalid_net_pnl += 1

        mfe = row["mfe_r"]
        mae = row["mae_r"]
        if _finite(mfe) and _finite(mae):
            if float(mfe) < 0 or float(mae) < 0:
                invalid_excursion += 1
            else:
                excursion_complete += 1

        confidence = row["confidence"]
        if confidence is not None:
            confidence = int(confidence)
            if confidence == -1:
                pass
            elif 0 <= confidence <= 100:
                confidence_known += 1
            else:
                invalid_confidence += 1

        direction = (row["direction"] or "").upper()
        if direction not in {"BUY", "SELL"}:
            invalid_direction += 1

        if row["entry_time"] and row["close_time"]:
            try:
                entry_time = _parse_datetime(str(row["entry_time"]))
                close_time = _parse_datetime(str(row["close_time"]))
                if close_time < entry_time:
                    integrity_errors.append(
                        f"position_id={row['position_id']} closes before its entry time"
                    )
                else:
                    time_complete += 1
            except ValueError:
                integrity_errors.append(
                    f"position_id={row['position_id']} has an unparseable entry/close timestamp"
                )

    for label, value in (
        ("initial_risk_money", invalid_risk),
        ("realized_r", invalid_realized),
        ("net_pnl", invalid_net_pnl),
        ("MFE/MAE", invalid_excursion),
        ("confidence", invalid_confidence),
        ("direction", invalid_direction),
    ):
        if value:
            integrity_errors.append(f"{value} outcome row(s) have invalid {label}")

    manifest_symbols = set(manifest.get("symbols", [])) if manifest else set()
    if manifest and observed_symbols and observed_symbols - manifest_symbols:
        integrity_errors.append(
            "database contains symbol(s) outside manifest scope: "
            + ", ".join(sorted(observed_symbols - manifest_symbols))
        )

    confidence_coverage = _ratio(confidence_known, count)
    excursion_coverage = _ratio(excursion_complete, count)
    time_coverage = _ratio(time_complete, count)

    if manifest is None:
        evidence_gaps.append("dataset provenance is unavailable")
    if count < thresholds.min_outcomes:
        evidence_gaps.append(
            f"outcomes={count} is below internal exploratory floor={thresholds.min_outcomes}"
        )
    if confidence_coverage < thresholds.min_confidence_coverage:
        evidence_gaps.append(
            "confidence coverage "
            f"{confidence_coverage:.3f} is below floor {thresholds.min_confidence_coverage:.3f}"
        )
    if excursion_coverage < thresholds.min_excursion_coverage:
        evidence_gaps.append(
            "MFE/MAE coverage "
            f"{excursion_coverage:.3f} is below floor {thresholds.min_excursion_coverage:.3f}"
        )
    if time_coverage < thresholds.min_time_coverage:
        evidence_gaps.append(
            f"time coverage {time_coverage:.3f} is below floor {thresholds.min_time_coverage:.3f}"
        )

    if integrity_errors:
        status = INVALID_DATA
    elif evidence_gaps:
        status = INSUFFICIENT_EVIDENCE
    else:
        status = READY_FOR_EXPLORATORY_RESEARCH

    return {
        "status": status,
        "outcomes": count,
        "observed_symbols": sorted(observed_symbols),
        "unique_position_ids": len({int(p) for p in position_ids if p is not None and int(p) > 0}),
        "confidence_coverage": confidence_coverage,
        "excursion_coverage": excursion_coverage,
        "time_coverage": time_coverage,
        "integrity_errors": integrity_errors,
        "evidence_gaps": list(dict.fromkeys(evidence_gaps)),
        "thresholds": asdict(thresholds),
    }


def _summary(values: Sequence[float]) -> dict[str, Any]:
    if not values:
        return {
            "n": 0,
            "mean": None,
            "median": None,
            "stddev_sample": None,
            "p10": None,
            "p25": None,
            "p75": None,
            "p90": None,
            "min": None,
            "max": None,
        }
    return {
        "n": len(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "stddev_sample": statistics.stdev(values) if len(values) > 1 else None,
        "p10": _quantile(values, 0.10),
        "p25": _quantile(values, 0.25),
        "p75": _quantile(values, 0.75),
        "p90": _quantile(values, 0.90),
        "min": min(values),
        "max": max(values),
    }


def _segment(rows: Sequence[sqlite3.Row], thresholds: EvidenceThresholds) -> dict[str, Any]:
    realized = [float(row["realized_r"]) for row in rows if _finite(row["realized_r"])]
    positive = sum(value > 0 for value in realized)
    negative = sum(value < 0 for value in realized)
    gross_positive = sum(value for value in realized if value > 0)
    gross_negative = abs(sum(value for value in realized if value < 0))
    return {
        "status": DESCRIPTIVE_SEGMENT if len(realized) >= thresholds.min_segment_outcomes else INSUFFICIENT_SEGMENT,
        "observations": len(realized),
        "positive": positive,
        "negative": negative,
        "zero": len(realized) - positive - negative,
        "positive_rate": _ratio(positive, len(realized)) if realized else None,
        "avg_realized_r": statistics.fmean(realized) if realized else None,
        "median_realized_r": statistics.median(realized) if realized else None,
        "r_profit_factor": gross_positive / gross_negative if gross_negative > 0 else None,
    }


def _confidence_bucket(confidence: int | None) -> str:
    if confidence is None or confidence < 0:
        return "UNKNOWN"
    if confidence < 50:
        return "00-49"
    if confidence < 60:
        return "50-59"
    if confidence < 70:
        return "60-69"
    if confidence < 80:
        return "70-79"
    if confidence < 90:
        return "80-89"
    return "90-100"


def build_baseline(
    conn: sqlite3.Connection,
    manifest: dict[str, Any] | None,
    manifest_errors: Sequence[str],
    thresholds: EvidenceThresholds | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    thresholds = thresholds or EvidenceThresholds()
    quality = evaluate_data_quality(conn, manifest, manifest_errors, thresholds)
    rows = _outcome_rows(conn)

    valid_rows = [
        row
        for row in rows
        if _finite(row["realized_r"])
        and _finite(row["mfe_r"])
        and _finite(row["mae_r"])
        and _finite(row["initial_risk_money"])
        and float(row["initial_risk_money"]) > 0
    ]
    realized = [float(row["realized_r"]) for row in valid_rows]
    mfe = [float(row["mfe_r"]) for row in valid_rows]
    mae = [float(row["mae_r"]) for row in valid_rows]

    positive = sum(value > 0 for value in realized)
    negative = sum(value < 0 for value in realized)
    gross_positive = sum(value for value in realized if value > 0)
    gross_negative = abs(sum(value for value in realized if value < 0))

    confidence_groups: dict[str, list[sqlite3.Row]] = {}
    regime_groups: dict[str, list[sqlite3.Row]] = {}
    for row in valid_rows:
        confidence_groups.setdefault(_confidence_bucket(row["confidence"]), []).append(row)
        regime_groups.setdefault(str(row["regime"] if row["regime"] is not None else "UNKNOWN"), []).append(row)

    close_times: list[datetime] = []
    for row in valid_rows:
        if row["close_time"]:
            try:
                close_times.append(_parse_datetime(str(row["close_time"])))
            except ValueError:
                pass

    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": generated_at or datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "research_status": quality["status"],
        "evidence_scope": (
            "Descriptive in-sample telemetry baseline only. READY_FOR_EXPLORATORY_RESEARCH means the "
            "configured internal data-quality floor is met; it is not evidence of profitability, "
            "statistical significance, OOS validity, walk-forward robustness or forward performance."
        ),
        "dataset": {
            "fingerprint_sha256": _dataset_fingerprint(rows, manifest),
            "manifest": manifest,
            "observed_period": {
                "first_close": min(close_times).isoformat() if close_times else None,
                "last_close": max(close_times).isoformat() if close_times else None,
            },
        },
        "data_quality": quality,
        "baseline": {
            "observations_used": len(valid_rows),
            "realized_r": _summary(realized),
            "mfe_r": _summary(mfe),
            "mae_r": _summary(mae),
            "positive": positive,
            "negative": negative,
            "zero": len(realized) - positive - negative,
            "positive_rate": _ratio(positive, len(realized)) if realized else None,
            "gross_positive_r": gross_positive if realized else None,
            "gross_negative_r_abs": gross_negative if realized else None,
            "r_profit_factor": gross_positive / gross_negative if gross_negative > 0 else None,
            "net_realized_r": sum(realized) if realized else None,
            "avg_mfe_minus_realized_r": (
                statistics.fmean([m - r for m, r in zip(mfe, realized, strict=True)])
                if realized
                else None
            ),
        },
        "confidence_bins": {
            key: _segment(group, thresholds) for key, group in sorted(confidence_groups.items())
        },
        "regime_segments": {
            key: _segment(group, thresholds) for key, group in sorted(regime_groups.items())
        },
        "ablation_status": {
            "status": "REQUIRES_COUNTERFACTUAL_STRATEGY_TESTER_RUNS",
            "reason": (
                "Telemetry can describe component scores on trades that actually occurred, but cannot "
                "supply outcomes for trades rejected by a counterfactual component configuration. True "
                "ablation therefore requires rerunning the EA with one controlled component change at a time."
            ),
        },
    }


def write_report(report: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Golden Trade X v2.80 baseline/data-quality research gate")
    parser.add_argument("--db", type=Path, required=True, help="v2.70 SQLite telemetry database")
    parser.add_argument("--manifest", type=Path, help="research provenance manifest JSON")
    parser.add_argument("--output", type=Path, required=True, help="versioned JSON baseline report")
    parser.add_argument("--min-outcomes", type=int, default=100)
    parser.add_argument("--min-confidence-coverage", type=float, default=0.95)
    parser.add_argument("--min-excursion-coverage", type=float, default=0.99)
    parser.add_argument("--min-time-coverage", type=float, default=0.95)
    parser.add_argument("--min-segment-outcomes", type=int, default=30)
    parser.add_argument(
        "--enforce",
        action="store_true",
        help="exit non-zero unless status is READY_FOR_EXPLORATORY_RESEARCH",
    )
    args = parser.parse_args()

    thresholds = EvidenceThresholds(
        min_outcomes=args.min_outcomes,
        min_confidence_coverage=args.min_confidence_coverage,
        min_excursion_coverage=args.min_excursion_coverage,
        min_time_coverage=args.min_time_coverage,
        min_segment_outcomes=args.min_segment_outcomes,
    )

    try:
        manifest, manifest_errors = load_manifest(args.manifest)
        with open_readonly(args.db) as conn:
            report = build_baseline(conn, manifest, manifest_errors, thresholds)
    except (FileNotFoundError, sqlite3.Error, ValueError) as exc:
        parser.error(str(exc))

    write_report(report, args.output)
    print(
        f"v2.80 baseline | status={report['research_status']} "
        f"outcomes={report['data_quality']['outcomes']} "
        f"fingerprint={report['dataset']['fingerprint_sha256']} | {args.output}"
    )

    if report["research_status"] == INVALID_DATA:
        raise SystemExit(2)
    if args.enforce and report["research_status"] != READY_FOR_EXPLORATORY_RESEARCH:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
