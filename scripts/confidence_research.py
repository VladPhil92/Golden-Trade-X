#!/usr/bin/env python3
"""Golden Trade X v2.80 — confidence discrimination research.

Selects a confidence threshold using only the chronological training partition,
then evaluates that frozen threshold once on a later holdout partition.

This is a post-hoc discrimination study over trades that actually occurred. It
is NOT a counterfactual simulation of changing InpMinConfidence: skipping trades
can alter equity, drawdown, sizing, loss streaks and subsequent EA state. Any
parameter change therefore still requires a controlled Strategy Tester rerun.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from quant_research import (
    INVALID_DATA,
    READY_FOR_EXPLORATORY_RESEARCH,
    EvidenceThresholds,
    evaluate_data_quality,
    load_manifest,
    open_readonly,
)

REPORT_SCHEMA_VERSION = 1
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
HOLDOUT_EVALUATED = "HOLDOUT_EVALUATED"
HOLDOUT_INSUFFICIENT = "HOLDOUT_INSUFFICIENT"
COUNTERFACTUAL_REQUIRED = "REQUIRES_COUNTERFACTUAL_STRATEGY_TESTER_CONFIRMATION"

SELECTION_METRICS = {
    "avg_realized_r": True,
    "net_realized_r": True,
    "positive_rate": True,
    "r_profit_factor": True,
}


@dataclass(frozen=True)
class ConfidenceOutcome:
    position_id: int
    close_time: datetime
    confidence: int
    realized_r: float


@dataclass(frozen=True)
class ConfidenceThresholds:
    min_train_outcomes: int = 70
    min_holdout_outcomes: int = 30
    min_candidate_train: int = 20
    min_candidate_holdout: int = 10

    def validate(self) -> None:
        values = asdict(self)
        if any(value < 1 for value in values.values()):
            raise ValueError("confidence research minimum counts must be positive")


def _finite(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _parse_datetime(value: str) -> datetime:
    text = value.strip()
    if not text:
        raise ValueError("empty datetime")
    candidates = [text, text.replace(".", "-", 2)]
    for candidate in candidates:
        try:
            return datetime.fromisoformat(candidate.replace("Z", "+00:00"))
        except ValueError:
            pass
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(candidate, fmt)
            except ValueError:
                continue
    raise ValueError(value)


def _normalize_datetimes(values: Sequence[datetime]) -> list[datetime]:
    if not values:
        return []
    aware = [value.tzinfo is not None and value.utcoffset() is not None for value in values]
    if any(aware) and not all(aware):
        raise ValueError("confidence outcomes mix timezone-aware and naive close times")
    if all(aware):
        return [value.astimezone(timezone.utc) for value in values]
    return list(values)


def load_outcomes(conn: sqlite3.Connection) -> tuple[list[ConfidenceOutcome], list[str]]:
    cursor = conn.execute(
        """
        SELECT position_id, close_time, confidence, realized_r
        FROM position_outcomes
        ORDER BY COALESCE(close_time, ''), COALESCE(position_id, 0), row_hash
        """
    )
    errors: list[str] = []
    raw: list[tuple[int, datetime, int, float]] = []
    for position_id, close_time, confidence, realized_r in cursor.fetchall():
        try:
            parsed_position = int(position_id)
            parsed_confidence = int(confidence)
            parsed_time = _parse_datetime(str(close_time))
        except (TypeError, ValueError, OverflowError):
            errors.append(f"invalid identity/time/confidence for position_id={position_id}")
            continue
        if parsed_position <= 0:
            errors.append(f"invalid position_id={position_id}")
            continue
        if not 0 <= parsed_confidence <= 100:
            continue  # unknown confidence is a coverage issue handled by the baseline quality gate
        if not _finite(realized_r):
            errors.append(f"non-finite RealizedR for position_id={parsed_position}")
            continue
        raw.append((parsed_position, parsed_time, parsed_confidence, float(realized_r)))

    try:
        normalized_times = _normalize_datetimes([row[1] for row in raw])
    except ValueError as exc:
        errors.append(str(exc))
        return [], errors

    outcomes = [
        ConfidenceOutcome(position_id, normalized_time, confidence, realized_r)
        for (position_id, _, confidence, realized_r), normalized_time in zip(
            raw, normalized_times, strict=True
        )
    ]
    outcomes.sort(key=lambda row: (row.close_time, row.position_id))
    return outcomes, list(dict.fromkeys(errors))


def chronological_split(
    outcomes: Sequence[ConfidenceOutcome], train_fraction: float
) -> tuple[list[ConfidenceOutcome], list[ConfidenceOutcome]]:
    if not 0.5 <= train_fraction < 1.0:
        raise ValueError("train_fraction must be >= 0.5 and < 1.0")
    if len(outcomes) < 2:
        return list(outcomes), []

    split = max(1, min(len(outcomes) - 1, int(len(outcomes) * train_fraction)))
    boundary_time = outcomes[split - 1].close_time
    while split < len(outcomes) and outcomes[split].close_time == boundary_time:
        split += 1
    if split >= len(outcomes):
        return list(outcomes), []
    return list(outcomes[:split]), list(outcomes[split:])


def threshold_metrics(
    outcomes: Sequence[ConfidenceOutcome], threshold: int
) -> dict[str, Any]:
    selected = [row for row in outcomes if row.confidence >= threshold]
    realized = [row.realized_r for row in selected]
    if not realized:
        return {
            "threshold": threshold,
            "observations": 0,
            "kept_fraction": 0.0,
            "avg_realized_r": None,
            "median_realized_r": None,
            "net_realized_r": None,
            "positive_rate": None,
            "r_profit_factor": None,
        }

    positive = [value for value in realized if value > 0]
    negative = [value for value in realized if value < 0]
    gross_positive = sum(positive)
    gross_negative = abs(sum(negative))
    return {
        "threshold": threshold,
        "observations": len(realized),
        "kept_fraction": len(realized) / len(outcomes) if outcomes else 0.0,
        "avg_realized_r": statistics.fmean(realized),
        "median_realized_r": statistics.median(realized),
        "net_realized_r": sum(realized),
        "positive_rate": len(positive) / len(realized),
        "r_profit_factor": gross_positive / gross_negative if gross_negative > 0 else None,
    }


def training_grid(
    train: Sequence[ConfidenceOutcome], step: int, min_candidate_train: int
) -> list[dict[str, Any]]:
    if step < 1 or step > 100:
        raise ValueError("threshold step must be between 1 and 100")
    rows: list[dict[str, Any]] = []
    for threshold in range(0, 101, step):
        metrics = threshold_metrics(train, threshold)
        metrics["eligible_for_selection"] = metrics["observations"] >= min_candidate_train
        rows.append(metrics)
    return rows


def select_threshold(
    grid: Sequence[dict[str, Any]], metric: str
) -> dict[str, Any] | None:
    if metric not in SELECTION_METRICS:
        raise ValueError(f"unsupported selection metric: {metric}")
    candidates = [
        row
        for row in grid
        if row.get("eligible_for_selection") and row.get(metric) is not None
    ]
    if not candidates:
        return None
    # Threshold selection is based on TRAIN ONLY. Lower threshold wins ties to
    # preserve more observations rather than preferring a more selective filter.
    return max(candidates, key=lambda row: (float(row[metric]), -int(row["threshold"])))


def build_confidence_report(
    conn: sqlite3.Connection,
    manifest: dict[str, Any] | None,
    manifest_errors: Sequence[str],
    *,
    train_fraction: float = 0.70,
    step: int = 5,
    selection_metric: str = "avg_realized_r",
    quality_thresholds: EvidenceThresholds | None = None,
    research_thresholds: ConfidenceThresholds | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    quality_thresholds = quality_thresholds or EvidenceThresholds()
    research_thresholds = research_thresholds or ConfidenceThresholds()
    research_thresholds.validate()

    quality = evaluate_data_quality(conn, manifest, manifest_errors, quality_thresholds)
    outcomes, load_errors = load_outcomes(conn)

    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "research_status": INSUFFICIENT_EVIDENCE,
        "selection_metric": selection_metric,
        "train_fraction_requested": train_fraction,
        "quality_status": quality["status"],
        "load_errors": load_errors,
        "counts": {"eligible_confidence_outcomes": len(outcomes), "train": 0, "holdout": 0},
        "training_grid": [],
        "selected_threshold": None,
        "train_selected": None,
        "holdout_selected": None,
        "holdout_all_observed": None,
        "parameter_change_status": COUNTERFACTUAL_REQUIRED,
        "methodology_note": (
            "The threshold is selected only on the earlier training partition and evaluated once on "
            "the later holdout partition. This tests confidence discrimination among observed trades; "
            "it does not reproduce the counterfactual EA path created by changing InpMinConfidence."
        ),
        "research_thresholds": asdict(research_thresholds),
    }

    if quality["status"] == INVALID_DATA or load_errors:
        report["research_status"] = INVALID_DATA
        return report
    if quality["status"] != READY_FOR_EXPLORATORY_RESEARCH:
        return report

    train, holdout = chronological_split(outcomes, train_fraction)
    report["counts"] = {
        "eligible_confidence_outcomes": len(outcomes),
        "train": len(train),
        "holdout": len(holdout),
    }
    if (
        len(train) < research_thresholds.min_train_outcomes
        or len(holdout) < research_thresholds.min_holdout_outcomes
    ):
        return report

    grid = training_grid(train, step, research_thresholds.min_candidate_train)
    report["training_grid"] = grid
    selected = select_threshold(grid, selection_metric)
    if selected is None:
        return report

    threshold = int(selected["threshold"])
    holdout_selected = threshold_metrics(holdout, threshold)
    report["selected_threshold"] = threshold
    report["train_selected"] = selected
    report["holdout_selected"] = holdout_selected
    report["holdout_all_observed"] = threshold_metrics(holdout, 0)

    if holdout_selected["observations"] < research_thresholds.min_candidate_holdout:
        report["research_status"] = HOLDOUT_INSUFFICIENT
    else:
        report["research_status"] = HOLDOUT_EVALUATED
    return report


def write_report(report: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Golden Trade X v2.80 chronological confidence discrimination study"
    )
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--train-fraction", type=float, default=0.70)
    parser.add_argument("--step", type=int, default=5)
    parser.add_argument(
        "--metric",
        choices=sorted(SELECTION_METRICS),
        default="avg_realized_r",
        help="metric used to select threshold on TRAIN only",
    )
    parser.add_argument("--min-train", type=int, default=70)
    parser.add_argument("--min-holdout", type=int, default=30)
    parser.add_argument("--min-candidate-train", type=int, default=20)
    parser.add_argument("--min-candidate-holdout", type=int, default=10)
    args = parser.parse_args()

    try:
        manifest, manifest_errors = load_manifest(args.manifest)
        research_thresholds = ConfidenceThresholds(
            min_train_outcomes=args.min_train,
            min_holdout_outcomes=args.min_holdout,
            min_candidate_train=args.min_candidate_train,
            min_candidate_holdout=args.min_candidate_holdout,
        )
        with open_readonly(args.db) as conn:
            report = build_confidence_report(
                conn,
                manifest,
                manifest_errors,
                train_fraction=args.train_fraction,
                step=args.step,
                selection_metric=args.metric,
                research_thresholds=research_thresholds,
            )
    except (FileNotFoundError, sqlite3.Error, ValueError) as exc:
        parser.error(str(exc))

    write_report(report, args.output)
    print(
        "v2.80 confidence research | "
        f"status={report['research_status']} "
        f"selected_threshold={report['selected_threshold']} "
        f"parameter_change={report['parameter_change_status']} | {args.output}"
    )

    if report["research_status"] == INVALID_DATA:
        raise SystemExit(2)
    if report["research_status"] != HOLDOUT_EVALUATED:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
