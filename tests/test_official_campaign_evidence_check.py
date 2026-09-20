from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.experiment_registry import RegistryValidationError, sha256_file
from scripts.official_campaign_evidence_check import validate_l4_evidence


def _write(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _bundle(tmp_path: Path, *, promotable: bool = True) -> dict[str, Path]:
    campaign_id = "GTX-L4-TEST"
    fingerprint = "f" * 64
    build_id = "a" * 40
    universe_sha = "b" * 64

    readiness = _write(
        tmp_path / "readiness.json",
        {
            "methodology": "PRE_CAMPAIGN_READINESS_V2",
            "decision": "READY_TO_FREEZE",
            "ready": True,
            "campaign_id": campaign_id,
            "live_trading_authorized": False,
            "real_capital_authorized": False,
        },
    )
    lock = _write(
        tmp_path / "campaign_lock.json",
        {
            "methodology": "OFFICIAL_VALIDATION_CAMPAIGN_FREEZE_V1",
            "status": "OFFICIAL_CAMPAIGN_FROZEN",
            "campaign_id": campaign_id,
            "campaign_fingerprint": fingerprint,
            "build_id": build_id,
            "candidate_universe": {"sha256": universe_sha},
            "live_trading_authorized": False,
            "real_capital_authorized": False,
        },
    )
    attestation = _write(
        tmp_path / "attestation.json",
        {
            "methodology": "MT5_EXECUTION_ENVIRONMENT_ATTESTATION_V1",
            "status": "VERIFIED",
            "live_trading_authorized": False,
            "observed": {"trade_mode": "DEMO"},
        },
    )
    oos_evidence = _write(
        tmp_path / "oos_evidence.json",
        {
            "methodology": "OFFICIAL_OOS_EVIDENCE_SET_V1",
            "campaign_id": campaign_id,
            "campaign_fingerprint": fingerprint,
            "candidate_universe_sha256": universe_sha,
            "folds": [
                {"fold_id": "WF001"},
                {"fold_id": "WF002"},
            ],
        },
    )
    oos_summary = _write(
        tmp_path / "oos_summary.json",
        {
            "methodology": "ROLLING_FROZEN_OOS_AGGREGATION",
            "candidate_universe_sha256": universe_sha,
            "summary": {"fold_count": 2},
        },
    )
    decision = _write(
        tmp_path / "promotion_decision.json",
        {
            "decision": (
                "PROMOTE_TO_FORWARD_DEMO_CANDIDATE"
                if promotable
                else "DO_NOT_PROMOTE"
            ),
            "promotable": promotable,
            "live_trading_authorized": False,
        },
    )
    status = (
        "OOS_PROMOTION_PASS_READY_FOR_ROBUSTNESS"
        if promotable
        else "OOS_PROMOTION_REJECTED"
    )
    manifest = _write(
        tmp_path / "manifest.json",
        {
            "methodology": "OFFICIAL_WALK_FORWARD_EXECUTION_V1",
            "campaign_id": campaign_id,
            "campaign_fingerprint": fingerprint,
            "build_id": build_id,
            "status": status,
            "live_trading_authorized": False,
            "real_capital_authorized": False,
            "campaign_lock_sha256": sha256_file(lock),
            "oos_evidence_manifest_sha256": sha256_file(oos_evidence),
            "oos_summary_sha256": sha256_file(oos_summary),
            "promotion_decision_sha256": sha256_file(decision),
            "promotable_to_robustness": promotable,
            "folds": [
                {
                    "fold_id": "WF001",
                    "status": "OOS_COMPLETED",
                    "oos_experiment_id": "oos-1",
                },
                {
                    "fold_id": "WF002",
                    "status": "OOS_COMPLETED",
                    "oos_experiment_id": "oos-2",
                },
            ],
        },
    )
    return {
        "readiness": readiness,
        "lock": lock,
        "attestation": attestation,
        "manifest": manifest,
        "oos_evidence": oos_evidence,
        "oos_summary": oos_summary,
        "decision": decision,
    }


def _validate(paths: dict[str, Path], output: Path | None = None) -> dict:
    return validate_l4_evidence(
        readiness_path=paths["readiness"],
        campaign_lock_path=paths["lock"],
        attestation_path=paths["attestation"],
        execution_manifest_path=paths["manifest"],
        oos_evidence_path=paths["oos_evidence"],
        oos_summary_path=paths["oos_summary"],
        promotion_decision_path=paths["decision"],
        output_path=output,
    )


@pytest.mark.parametrize(
    ("promotable", "expected_status", "next_stage"),
    [
        (
            True,
            "OOS_PROMOTION_PASS_READY_FOR_ROBUSTNESS",
            "ROBUSTNESS_VALIDATION",
        ),
        (
            False,
            "OOS_PROMOTION_REJECTED",
            "STOP_REVIEW_REJECTED_OOS",
        ),
    ],
)
def test_valid_l4_terminal_outcomes(
    tmp_path: Path,
    promotable: bool,
    expected_status: str,
    next_stage: str,
) -> None:
    paths = _bundle(tmp_path, promotable=promotable)
    output = tmp_path / "l4_completion.json"
    result = _validate(paths, output)

    assert result["status"] == "L4_OFFICIAL_OOS_EVIDENCE_VALIDATED"
    assert result["oos_terminal_status"] == expected_status
    assert result["promotable_to_robustness"] is promotable
    assert result["next_stage"] == next_stage
    assert result["fold_count"] == 2
    assert result["live_trading_authorized"] is False
    assert result["real_capital_authorized"] is False
    assert output.is_file()


def test_rejects_non_demo_attestation(tmp_path: Path) -> None:
    paths = _bundle(tmp_path)
    payload = json.loads(paths["attestation"].read_text(encoding="utf-8"))
    payload["observed"]["trade_mode"] = "REAL"
    _write(paths["attestation"], payload)

    with pytest.raises(RegistryValidationError, match="requires DEMO trade_mode"):
        _validate(paths)


def test_rejects_tampered_oos_evidence_hash(tmp_path: Path) -> None:
    paths = _bundle(tmp_path)
    payload = json.loads(paths["oos_evidence"].read_text(encoding="utf-8"))
    payload["folds"].append({"fold_id": "WF003"})
    _write(paths["oos_evidence"], payload)

    with pytest.raises(RegistryValidationError, match="OOS evidence hash mismatch"):
        _validate(paths)


def test_rejects_incomplete_fold(tmp_path: Path) -> None:
    paths = _bundle(tmp_path)
    payload = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    payload["folds"][0]["status"] = "PREPARED_NOT_EXECUTED"
    _write(paths["manifest"], payload)

    with pytest.raises(RegistryValidationError, match="OOS execution is not complete"):
        _validate(paths)


def test_rejects_promotion_status_inconsistency(tmp_path: Path) -> None:
    paths = _bundle(tmp_path, promotable=True)
    payload = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    payload["status"] = "OOS_PROMOTION_REJECTED"
    _write(paths["manifest"], payload)

    with pytest.raises(RegistryValidationError, match="terminal status is inconsistent"):
        _validate(paths)


def test_rejects_live_trading_authorization(tmp_path: Path) -> None:
    paths = _bundle(tmp_path)
    payload = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    payload["live_trading_authorized"] = True
    _write(paths["manifest"], payload)

    with pytest.raises(RegistryValidationError, match="live_trading_authorized=false"):
        _validate(paths)
