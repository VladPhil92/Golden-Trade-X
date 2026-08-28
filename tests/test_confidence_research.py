import hashlib
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from confidence_research import (
    COUNTERFACTUAL_REQUIRED,
    HOLDOUT_EVALUATED,
    ConfidenceOutcome,
    ConfidenceThresholds,
    build_confidence_report,
    chronological_split,
    purge_holdout_overlaps,
    select_threshold,
    threshold_metrics,
    training_grid,
)
from telemetry_db import connect


def _manifest() -> dict:
    return {
        "dataset_id": "gtx-confidence-test-001",
        "source_type": "strategy_tester",
        "git_sha": "c574ed758d1498a2d614a69e04e1f1af2c8dd20a",
        "preset_sha256": hashlib.sha256(b"confidence-test-preset").hexdigest(),
        "broker": "TEST-BROKER",
        "symbols": ["XAUUSD"],
        "timeframe": "M15",
        "period_start": "2026-01-01T00:00:00Z",
        "period_end": "2026-06-01T00:00:00Z",
    }


def _outcome(
    position_id: int,
    hour: int,
    confidence: int,
    realized_r: float,
    *,
    entry_time: datetime | None = None,
) -> ConfidenceOutcome:
    close_time = datetime(2026, 1, 1) + timedelta(hours=hour)
    return ConfidenceOutcome(
        position_id=position_id,
        entry_time=entry_time or close_time - timedelta(minutes=30),
        close_time=close_time,
        confidence=confidence,
        realized_r=realized_r,
    )


def _seed_confidence_dataset(conn, count: int = 120) -> None:
    start = datetime(2026, 1, 1)
    train_cut = int(count * 0.70)
    for index in range(count):
        in_train = index < train_cut
        high_conf = index % 2 == 0
        confidence = 80 if high_conf else 60
        # Training rewards the high-confidence subset; holdout deliberately
        # reverses that relationship. Selection must still remain train-only.
        if in_train:
            realized = 1.0 if high_conf else -0.2
        else:
            realized = -1.0 if high_conf else 1.0

        entry = start + timedelta(hours=index * 2)
        close = entry + timedelta(hours=1)
        conn.execute(
            """
            INSERT INTO position_outcomes (
                row_hash, event_id, close_time, account, magic, symbol,
                position_id, direction, entry_time, entry_price, initial_sl,
                initial_tp, initial_risk_price, initial_risk_money,
                initial_volume, confidence, regime, mfe_r, mfe_price,
                mfe_time, mae_r, mae_price, mae_time, net_pnl, realized_r,
                close_price, source_file, raw_json
            ) VALUES (
                ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
            )
            """,
            (
                f"confidence-hash-{index}",
                f"confidence-event-{index}",
                close.strftime("%Y-%m-%d %H:%M:%S"),
                12345,
                920260,
                "XAUUSD",
                200000 + index,
                "BUY" if high_conf else "SELL",
                entry.strftime("%Y-%m-%d %H:%M:%S"),
                3000.0,
                2990.0,
                3020.0,
                10.0,
                100.0,
                0.10,
                confidence,
                index % 3,
                1.5,
                3015.0,
                (entry + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S"),
                0.5,
                2995.0,
                (entry + timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S"),
                realized * 100.0,
                realized,
                3010.0,
                "outcomes.csv",
                "{}",
            ),
        )
    conn.commit()


def test_chronological_split_keeps_equal_timestamp_on_one_side() -> None:
    outcomes = [
        _outcome(1, 1, 60, 0.1),
        _outcome(2, 2, 60, 0.1),
        _outcome(3, 3, 60, 0.1),
        _outcome(4, 3, 80, 0.2),
        _outcome(5, 4, 80, 0.2),
        _outcome(6, 5, 80, 0.2),
    ]

    train, holdout = chronological_split(outcomes, 0.50)

    assert [row.position_id for row in train] == [1, 2, 3, 4]
    assert [row.position_id for row in holdout] == [5, 6]
    assert train[-1].close_time < holdout[0].close_time


def test_holdout_purges_entries_not_strictly_after_final_train_close() -> None:
    cutoff = datetime(2026, 1, 1, 10, 0, 0)
    train = [
        ConfidenceOutcome(1, cutoff - timedelta(hours=2), cutoff, 70, 0.5),
    ]
    holdout = [
        ConfidenceOutcome(2, cutoff - timedelta(hours=1), cutoff + timedelta(hours=1), 70, 0.2),
        ConfidenceOutcome(3, cutoff, cutoff + timedelta(hours=2), 75, 0.3),
        ConfidenceOutcome(4, cutoff + timedelta(minutes=1), cutoff + timedelta(hours=3), 80, 0.4),
    ]

    clean, purged, observed_cutoff = purge_holdout_overlaps(train, holdout)

    assert observed_cutoff == cutoff
    assert purged == 2
    assert [row.position_id for row in clean] == [4]
    assert all(row.entry_time > cutoff for row in clean)


def test_training_selection_uses_train_only_not_holdout() -> None:
    train = [
        *[_outcome(i, i, 60, -0.2) for i in range(1, 41)],
        *[_outcome(100 + i, 50 + i, 80, 1.0) for i in range(1, 41)],
    ]
    holdout = [
        *[_outcome(200 + i, 100 + i, 60, 1.0) for i in range(1, 21)],
        *[_outcome(300 + i, 130 + i, 80, -1.0) for i in range(1, 21)],
    ]
    train.sort(key=lambda row: (row.close_time, row.position_id))
    holdout.sort(key=lambda row: (row.close_time, row.position_id))

    selected = select_threshold(training_grid(train, step=5, min_candidate_train=20), "avg_realized_r")

    assert selected is not None
    # Thresholds 65..80 select the identical confidence=80 subset. The
    # deterministic tie-break intentionally picks the lowest equivalent threshold.
    assert selected["threshold"] == 65
    assert selected["avg_realized_r"] == pytest.approx(1.0)
    assert threshold_metrics(holdout, selected["threshold"])["avg_realized_r"] == pytest.approx(-1.0)


def test_selection_tie_prefers_lower_threshold_and_more_observations() -> None:
    train = [_outcome(i, i, 80, 0.5) for i in range(1, 41)]
    selected = select_threshold(training_grid(train, step=5, min_candidate_train=20), "avg_realized_r")

    assert selected is not None
    assert selected["threshold"] == 0
    assert selected["observations"] == 40


def test_end_to_end_report_freezes_train_choice_before_holdout(tmp_path: Path) -> None:
    db = tmp_path / "research.sqlite"
    with connect(db) as conn:
        _seed_confidence_dataset(conn, 120)
        report = build_confidence_report(
            conn,
            _manifest(),
            [],
            train_fraction=0.70,
            step=5,
            selection_metric="avg_realized_r",
            research_thresholds=ConfidenceThresholds(
                min_train_outcomes=70,
                min_holdout_outcomes=30,
                min_candidate_train=20,
                min_candidate_holdout=10,
            ),
            generated_at="fixed",
        )

    assert report["research_status"] == HOLDOUT_EVALUATED
    assert report["counts"] == {
        "eligible_confidence_outcomes": 120,
        "train": 84,
        "holdout_before_overlap_purge": 36,
        "holdout_overlap_purged": 0,
        "holdout": 36,
    }
    assert report["selected_threshold"] == 65
    assert report["train_selected"]["avg_realized_r"] == pytest.approx(1.0)
    assert report["holdout_selected"]["avg_realized_r"] == pytest.approx(-1.0)
    assert report["parameter_change_status"] == COUNTERFACTUAL_REQUIRED
    assert "does not reproduce the counterfactual EA path" in report["methodology_note"]


def test_invalid_train_fraction_fails_closed() -> None:
    with pytest.raises(ValueError, match="train_fraction"):
        chronological_split([_outcome(1, 1, 60, 0.1), _outcome(2, 2, 70, 0.2)], 1.0)
