#!/usr/bin/env python3
"""Validate the integrity boundary of a completed official L4 IS→OOS campaign.

This checker does not judge trading performance. It only verifies that the completed
campaign evidence is internally consistent with the frozen campaign, the DEMO runtime
attestation and the final OOS promotion decision.

Both a valid OOS promotion pass and a valid OOS rejection are successful methodological
outcomes. Neither outcome authorizes live trading or real capital.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from scripts.experiment_registry import RegistryValidationError, sha256_file
except ModuleNotFoundError:
    from experiment_registry import RegistryValidationError, sha256_file


SUPPORTED_CAMPAIGN_LOCK = "OFFICIAL_VALIDATION_CAMPAIGN_FREEZE_V1"
SUPPORTED_ATTESTATION = "MT5_EXECUTION_ENVIRONMENT_ATTESTATION_V1"
SUPPORTED_READINESS = "PRE_CAMPAIGN_READINESS_V2"
SUPPORTED_EXECUTION = "OFFICIAL_WALK_FORWARD_EXECUTION_V1"
SUPPORTED_OOS_SET = "OFFICIAL_OOS_EVIDENCE_SET_V1"

PASS_STATUS = "OOS_PROMOTION_PASS_READY_FOR_ROBUSTNESS"
REJECT_STATUS = "OOS_PROMOTION_REJECTED"
VALID_TERMINAL_STATUSES = {PASS_STATUS, REJECT_STATUS}


def _load(path: str | Path) -> dict[str, Any]:
    target = Path(path).resolve()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RegistryValidationError(f"invalid JSON evidence: {target}") from exc
    if not isinstance(payload, dict):
        raise RegistryValidationError(f"JSON evidence root must be an object: {target}")
    return payload


def _require_false(payload: dict[str, Any], field: str, label: str) -> None:
    if payload.get(field) is not False:
        raise RegistryValidationError(f"{label} must set {field}=false")


def validate_l4_evidence(
    *,
    readiness_path: str | Path,
    campaign_lock_path: str | Path,
    attestation_path: str | Path,
    execution_manifest_path: str | Path,
    oos_evidence_path: str | Path,
    oos_summary_path: str | Path,
    promotion_decision_path: str | Path,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    readiness = _load(readiness_path)
    lock = _load(campaign_lock_path)
    attestation = _load(attestation_path)
    manifest = _load(execution_manifest_path)
    oos_evidence = _load(oos_evidence_path)
    oos_summary = _load(oos_summary_path)
    decision = _load(promotion_decision_path)

    if readiness.get("methodology") != SUPPORTED_READINESS:
        raise RegistryValidationError("unsupported pre-campaign readiness methodology")
    if readiness.get("decision") != "READY_TO_FREEZE" or readiness.get("ready") is not True:
        raise RegistryValidationError("pre-campaign readiness is not READY_TO_FREEZE")
    _require_false(readiness, "live_trading_authorized", "pre-campaign readiness")
    _require_false(readiness, "real_capital_authorized", "pre-campaign readiness")

    if lock.get("methodology") != SUPPORTED_CAMPAIGN_LOCK:
        raise RegistryValidationError("unsupported campaign lock methodology")
    if lock.get("status") != "OFFICIAL_CAMPAIGN_FROZEN":
        raise RegistryValidationError("campaign lock is not OFFICIAL_CAMPAIGN_FROZEN")
    _require_false(lock, "live_trading_authorized", "campaign lock")
    _require_false(lock, "real_capital_authorized", "campaign lock")

    if attestation.get("methodology") != SUPPORTED_ATTESTATION:
        raise RegistryValidationError("unsupported MT5 environment attestation methodology")
    if attestation.get("status") != "VERIFIED":
        raise RegistryValidationError("MT5 environment attestation is not VERIFIED")
    _require_false(attestation, "live_trading_authorized", "MT5 environment attestation")
    observed = attestation.get("observed")
    if not isinstance(observed, dict):
        raise RegistryValidationError("MT5 environment attestation lacks observed payload")
    if observed.get("trade_mode") != "DEMO":
        raise RegistryValidationError("official L4 evidence requires DEMO trade_mode")

    if manifest.get("methodology") != SUPPORTED_EXECUTION:
        raise RegistryValidationError("unsupported campaign execution methodology")
    status = manifest.get("status")
    if status not in VALID_TERMINAL_STATUSES:
        raise RegistryValidationError(
            "campaign execution must end in OOS promotion pass or rejection"
        )
    _require_false(manifest, "live_trading_authorized", "campaign execution")
    _require_false(manifest, "real_capital_authorized", "campaign execution")

    campaign_id = lock.get("campaign_id")
    fingerprint = lock.get("campaign_fingerprint")
    build_id = lock.get("build_id")
    if not isinstance(campaign_id, str) or not campaign_id:
        raise RegistryValidationError("campaign lock lacks campaign_id")
    if manifest.get("campaign_id") != campaign_id:
        raise RegistryValidationError("execution manifest campaign_id differs from campaign lock")
    if manifest.get("campaign_fingerprint") != fingerprint:
        raise RegistryValidationError(
            "execution manifest campaign_fingerprint differs from campaign lock"
        )
    if manifest.get("build_id") != build_id:
        raise RegistryValidationError("execution manifest build_id differs from campaign lock")

    lock_path = Path(campaign_lock_path).resolve()
    if manifest.get("campaign_lock_sha256") != sha256_file(lock_path):
        raise RegistryValidationError("execution manifest campaign_lock_sha256 mismatch")

    oos_evidence_file = Path(oos_evidence_path).resolve()
    oos_summary_file = Path(oos_summary_path).resolve()
    decision_file = Path(promotion_decision_path).resolve()
    if manifest.get("oos_evidence_manifest_sha256") != sha256_file(oos_evidence_file):
        raise RegistryValidationError("execution manifest OOS evidence hash mismatch")
    if manifest.get("oos_summary_sha256") != sha256_file(oos_summary_file):
        raise RegistryValidationError("execution manifest OOS summary hash mismatch")
    if manifest.get("promotion_decision_sha256") != sha256_file(decision_file):
        raise RegistryValidationError("execution manifest promotion decision hash mismatch")

    if oos_evidence.get("methodology") != SUPPORTED_OOS_SET:
        raise RegistryValidationError("unsupported official OOS evidence methodology")
    if oos_evidence.get("campaign_id") != campaign_id:
        raise RegistryValidationError("OOS evidence campaign_id differs from campaign lock")
    if oos_evidence.get("campaign_fingerprint") != fingerprint:
        raise RegistryValidationError(
            "OOS evidence campaign_fingerprint differs from campaign lock"
        )

    universe = lock.get("candidate_universe")
    if not isinstance(universe, dict):
        raise RegistryValidationError("campaign lock lacks candidate universe")
    universe_sha = universe.get("sha256")
    if oos_evidence.get("candidate_universe_sha256") != universe_sha:
        raise RegistryValidationError("OOS evidence candidate universe differs from campaign lock")
    if oos_summary.get("candidate_universe_sha256") != universe_sha:
        raise RegistryValidationError("OOS summary candidate universe differs from campaign lock")

    manifest_folds = manifest.get("folds")
    evidence_folds = oos_evidence.get("folds")
    if not isinstance(manifest_folds, list) or not manifest_folds:
        raise RegistryValidationError("execution manifest has no folds")
    if not isinstance(evidence_folds, list) or not evidence_folds:
        raise RegistryValidationError("OOS evidence has no folds")

    completed_ids: list[str] = []
    for row in manifest_folds:
        if not isinstance(row, dict):
            raise RegistryValidationError("execution manifest fold must be an object")
        fold_id = row.get("fold_id")
        if not isinstance(fold_id, str) or not fold_id:
            raise RegistryValidationError("execution manifest fold_id is required")
        if row.get("status") != "OOS_COMPLETED":
            raise RegistryValidationError(f"{fold_id}: OOS execution is not complete")
        if not isinstance(row.get("oos_experiment_id"), str) or not row["oos_experiment_id"]:
            raise RegistryValidationError(f"{fold_id}: OOS experiment id is missing")
        completed_ids.append(fold_id)

    evidence_ids: list[str] = []
    for row in evidence_folds:
        if not isinstance(row, dict):
            raise RegistryValidationError("OOS evidence fold must be an object")
        fold_id = row.get("fold_id")
        if not isinstance(fold_id, str) or not fold_id:
            raise RegistryValidationError("OOS evidence fold_id is required")
        evidence_ids.append(fold_id)

    if len(completed_ids) != len(set(completed_ids)):
        raise RegistryValidationError("execution manifest contains duplicate fold ids")
    if len(evidence_ids) != len(set(evidence_ids)):
        raise RegistryValidationError("OOS evidence contains duplicate fold ids")
    if set(completed_ids) != set(evidence_ids):
        raise RegistryValidationError("execution and OOS evidence fold sets differ")

    promotable = decision.get("promotable")
    if not isinstance(promotable, bool):
        raise RegistryValidationError("promotion decision promotable must be true/false")
    _require_false(decision, "live_trading_authorized", "promotion decision")

    manifest_promotable = manifest.get("promotable_to_robustness")
    if manifest_promotable is not promotable:
        raise RegistryValidationError(
            "campaign manifest promotable_to_robustness differs from promotion decision"
        )
    expected_status = PASS_STATUS if promotable else REJECT_STATUS
    if status != expected_status:
        raise RegistryValidationError(
            "campaign terminal status is inconsistent with promotion decision"
        )

    result = {
        "schema_version": 1,
        "methodology": "L4_OFFICIAL_OOS_EVIDENCE_INTEGRITY_V1",
        "status": "L4_OFFICIAL_OOS_EVIDENCE_VALIDATED",
        "campaign_id": campaign_id,
        "campaign_fingerprint": fingerprint,
        "build_id": build_id,
        "fold_count": len(completed_ids),
        "oos_terminal_status": status,
        "promotable_to_robustness": promotable,
        "next_stage": "ROBUSTNESS_VALIDATION" if promotable else "STOP_REVIEW_REJECTED_OOS",
        "live_trading_authorized": False,
        "real_capital_authorized": False,
        "evidence": {
            "readiness_sha256": sha256_file(Path(readiness_path)),
            "campaign_lock_sha256": sha256_file(lock_path),
            "attestation_sha256": sha256_file(Path(attestation_path)),
            "execution_manifest_sha256": sha256_file(Path(execution_manifest_path)),
            "oos_evidence_sha256": sha256_file(oos_evidence_file),
            "oos_summary_sha256": sha256_file(oos_summary_file),
            "promotion_decision_sha256": sha256_file(decision_file),
        },
    }

    if output_path is not None:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--readiness", required=True)
    parser.add_argument("--campaign-lock", required=True)
    parser.add_argument("--attestation", required=True)
    parser.add_argument("--execution-manifest", required=True)
    parser.add_argument("--oos-evidence", required=True)
    parser.add_argument("--oos-summary", required=True)
    parser.add_argument("--promotion-decision", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()

    try:
        result = validate_l4_evidence(
            readiness_path=args.readiness,
            campaign_lock_path=args.campaign_lock,
            attestation_path=args.attestation,
            execution_manifest_path=args.execution_manifest,
            oos_evidence_path=args.oos_evidence,
            oos_summary_path=args.oos_summary,
            promotion_decision_path=args.promotion_decision,
            output_path=args.output,
        )
    except RegistryValidationError as exc:
        parser.error(str(exc))
        return

    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
