#!/usr/bin/env python3
"""Golden Trade X v2.80 — quantitative research baseline gate.

Consumes the v2.70 SQLite telemetry database in read-only mode and produces a
reproducible descriptive baseline. The gate separates three states:

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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

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
    return sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)


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

    for field in REQUIRED_MANIFEST_FIELDS - {"symbols"}:
        if field not in manifest:
            continue
        value = manifest[field]
        if value is None or (isinstance(value, str) and not value.strip()):
            errors.append(f"manifest field {field} must not be null/empty")

    source_type = manifest.get("source_type")
    if source_type is not None and source_type not in ALLOWED_SOURCE_TYPES:
        errors.append(
            "manifest source_type must be one of: " + ", ".join(sorted(ALLOWED_SOURCE_TYPES))
        )

    git_sha = manifest.get("git_sha")
    if git_sha is not None and str(git_sha).strip() and not _is_hex(str(git_sha), 7, 40):
        errors.append("manifest git_sha must be a 7-40 character hexadecimal Git commit id")

    preset_sha = manifest.get("preset_sha256")
    if preset_sha is not None and str(preset_sha).strip() and not _is_hex(str(preset_sha), 64, 64):
        errors.append("manifest preset_sha256 must be a 64 character SHA-256 hex digest")

    symbols = manifest.get("symbols")
    if not isinstance(symbols, list) or not symbols or not all(
        isinstance(symbol, str) and symbol.strip() for symbol in symbols
    ):
        errors.append("manifest symbols must be a non-empty array of non-empty strings")

    parsed_periods: dict[str, datetime] = {}
    for field in ("period_start", "period_end"):
        value = manifest.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        try:
            parsed_periods[field] = _parse_datetime(str(value))
        except ValueError:
            errors.append(f"manifest {field} is not a recognized ISO/MT5 datetime")

    if "period_start" in parsed_periods and "period_end" in parsed_periods:
        start, end, awareness_error = _normalize_datetime_pair(
            parsed_periods["period_start"], parsed_periods["period_end"]
        )
        if awareness_error:
            errors.append(
                "manifest period_start and period_end must either both include timezone offsets or both omit them"
            )
        elif end <= start:
            errors.append("manifest period_end must be later than period_start")

    return manifest, list(dict.fromkeys(errors))


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


def _normalize_datetime_pair(first: datetime, second: datetime) -> tuple[datetime, datetime, bool]:
    first_aware = first.tzinfo is not None and first.utcoffset() is not None
    second_aware = second.tzinfo is not None and second.utcoffset() is not None
    if first_aware != second_aware:
        return first, second, True
    if first_aware:
        return first.astimezone(timezone.utc), second.astimezone(timezone.utc), False
    return first, second, False


def _finite(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _positive_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed > 0 else None


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


def _dataset_fingerprint(rows: Iterable[Mapping[str, Any]], manifest: dict[str, Any] | None) -> str:
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


def _outcome_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    cursor = conn.execute(
        """
        SELECT row_hash, event_id, close_time, symbol, position_id, direction,
               entry_time, initial_risk_money, confidence, regime, mfe_r, mae_r,
               net_pnl, realized_r
        FROM position_outcomes
        ORDER BY COALESCE(close_time, ''), COALESCE(position_id, 0), row_hash
        """
    )
    names = [column[0] for column in cursor.description or ()]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


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

    normalized_position_ids = [_positive_int(row["position_id"]) for row in rows]
    null_position_ids = sum(position_id is None for position_id in normalized_position_ids)
    valid_position_ids = [position_id for position_id in normalized_position_ids if position_id is not None]
    duplicate_position_ids = len(valid_position_ids) - len(set(valid_position_ids))
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
        symbol = str(row["symbol"] or "").strip()
        if symbol:
            observed_symbols.add(symbol)

        risk = row["initial_risk_money"]
        if not _finite(risk) or float(risk) <= 0:
            invalid_risk += 1

        if not _finite(row["realized_r"]):
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
            try:
                parsed_confidence = int(confidence)
            except (TypeError, ValueError, OverflowError):
                invalid_confidence += 1
            else:
                if parsed_confidence == -1:
                    pass
                elif 0 <= parsed_confidence <= 100:
                    confidence_known += 1
                else:
                    invalid_confidence += 1

        direction = str(row["direction"] or "").upper()
        if direction not in {"BUY", "SELL"}:
            invalid_direction += 1

        if row["entry_time"] and row["close_time"]:
            try:
                entry_time = _parse_datetime(str(row["entry_time"]))
                close_time = _parse_datetime(str(row["close_time"]))
                entry_time, close_time, awareness_error = _normalize_datetime_pair(
                    entry_time, close_time
                )
                if awareness_error:
                    integrity_errors.append(
                        f"position_id={row['position_id']} mixes timezone-aware and naive timestamps"
                    )
                elif close_time < entry_time:
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

    manifest_symbols: set[str] = set()
    if manifest:
        raw_symbols = manifest.get("symbols")
        if isinstance(raw_symbols, list):
            manifest_symbols = {
                symbol.strip() for symbol in raw_symbols if isinstance(symbol, str) and symbol.strip()
            }
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
        "unique_position_ids": len(set(valid_position_ids)),
        "confidence_coverage": confidence_coverage,
        "excursion_coverage": excursion_coverage,
        "time_coverage": time_coverage,
        "integrity_errors": list(dict.fromkeys(integrity_errors)),
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


def _segment(rows: Sequence[Mapping[str, Any]], thresholds: EvidenceThresholds) -> dict[str, Any]:
    realized = [float(row["realized_r"]) for row in rows if _finite(row["realized_r"])]
    positive = sum(value > 0 for value in realized)
    negative = sum(value < 0 for value in realized)
    gross_positive = sum(value for value in realized if value > 0)
    gross_negative = abs(sum(value for value in realized if value < 0))
    return {
        "status": (
            DESCRIPTIVE_SEGMENT
            if len(realized) >= thresholds.min_segment_outcomes
            else INSUFFICIENT_SEGMENT
        ),
        "observations": len(realized),
        "positive": positive,
        "negative": negative,
        "zero": len(realized) - positive - negative,
        "positive_rate": _ratio(positive, len(realized)) if realized else None,
        "avg_realized_r": statistics.fmean(realized) if realized else None,
        "median_realized_r": statistics.median(realized) if realized else None,
        "r_profit_factor": gross_positive / gross_negative if gross_negative > 0 else None,
    }


def _confidence_bucket(confidence: Any) -> str:
    try:
        parsed = int(confidence)
    except (TypeError, ValueError, OverflowError):
        return "UNKNOWN"
    if parsed < 0:
        return "UNKNOWN"
    if parsed < 50:
        return "00-49"
    if parsed < 60:
        return "50-59"
    if parsed < 70:
        return "60-69"
    if parsed < 80:
        return "70-79"
    if parsed < 90:
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

    confidence_groups: dict[str, list[Mapping[str, Any]]] = {}
    regime_groups: dict[str, list[Mapping[str, Any]]] = {}
    for row in valid_rows:
        confidence_groups.setdefault(_confidence_bucket(row["confidence"]), []).append(row)
        regime = row["regime"] if row["regime"] is not None else "UNKNOWN"
        regime_groups.setdefault(str(regime), []).append(row)

    close_times: list[datetime] = []
    for row in valid_rows:
        if row["close_time"]:
            try:
                close_times.append(_parse_datetime(str(row["close_time"])))
            except ValueError:
                pass
    comparable_close_times = _normalize_datetime_collection(close_times)

    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
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
                "first_close": min(comparable_close_times).isoformat() if comparable_close_times else None,
                "last_close": max(comparable_close_times).isoformat() if comparable_close_times else None,
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


def _normalize_datetime_collection(values: Sequence[datetime]) -> list[datetime]:
    if not values:
        return []
    aware = [value.tzinfo is not None and value.utcoffset() is not None for value in values]
    if any(aware) and not all(aware):
        return []
    if all(aware):
        return [value.astimezone(timezone.utc) for value in values]
    return list(values)


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
