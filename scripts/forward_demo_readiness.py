#!/usr/bin/env python3
"""Combine OOS and robustness evidence into a forward-demo readiness decision.

The script is a governance join, not a trading-performance calculator. A
candidate is ready to *start* forward-demo planning only when the positive OOS
promotion decision and positive robustness decision refer to the exact same
frozen Strategy Tester experiment and preset bytes.
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


def _load(path: str | Path) -> dict[str, Any]:
    target = Path(path).resolve()
    with target.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise RegistryValidationError(f"JSON root must be an object: {target}")
    return value


def evaluate_readiness(
    oos_summary_path: str | Path,
    promotion_decision_path: str | Path,
    selection_manifest_path: str | Path,
    robustness_summary_path: str | Path,
    robustness_decision_path: str | Path,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    oos_summary_path = Path(oos_summary_path).resolve()
    promotion_decision_path = Path(promotion_decision_path).resolve()
    selection_manifest_path = Path(selection_manifest_path).resolve()
    robustness_summary_path = Path(robustness_summary_path).resolve()
    robustness_decision_path = Path(robustness_decision_path).resolve()

    oos = _load(oos_summary_path)
    promotion = _load(promotion_decision_path)
    selection = _load(selection_manifest_path)
    robustness = _load(robustness_summary_path)
    robustness_decision = _load(robustness_decision_path)

    if oos.get("methodology") != "ROLLING_FROZEN_OOS_AGGREGATION":
        raise RegistryValidationError("unsupported OOS summary methodology")
    if robustness.get("methodology") != "ROBUSTNESS_AGGREGATION_V1":
        raise RegistryValidationError("unsupported robustness summary methodology")
    if selection.get("methodology") != "IS_SELECTION_THEN_FROZEN_OOS":
        raise RegistryValidationError("unsupported selection manifest methodology")

    if promotion.get("oos_summary_sha256") != sha256_file(oos_summary_path):
        raise RegistryValidationError("promotion decision does not hash the supplied OOS summary")
    if robustness_decision.get("robustness_summary_sha256") != sha256_file(robustness_summary_path):
        raise RegistryValidationError("robustness decision does not hash the supplied robustness summary")

    if promotion.get("live_trading_authorized") is not False:
        raise RegistryValidationError("OOS promotion decision must explicitly deny live trading")
    if robustness_decision.get("live_trading_authorized") is not False:
        raise RegistryValidationError("robustness decision must explicitly deny live trading")

    selection_oos = selection.get("oos")
    selection_selected = selection.get("selected")
    robustness_base = robustness.get("baseline")
    if not isinstance(selection_oos, dict) or not isinstance(selection_selected, dict):
        raise RegistryValidationError("selection manifest lacks selected/OOS identity")
    if not isinstance(robustness_base, dict):
        raise RegistryValidationError("robustness summary lacks baseline identity")

    candidate_id = selection_oos.get("experiment_id")
    preset_sha = selection_selected.get("frozen_preset_sha256")
    fold_id = selection.get("fold_id")
    if not isinstance(candidate_id, str) or not candidate_id:
        raise RegistryValidationError("selection OOS experiment_id is required")
    if not isinstance(preset_sha, str) or not preset_sha:
        raise RegistryValidationError("selection frozen preset SHA-256 is required")
    if not isinstance(fold_id, str) or not fold_id:
        raise RegistryValidationError("selection fold_id is required")

    if selection.get("plan_sha256") != oos.get("plan_sha256"):
        raise RegistryValidationError("selection and OOS aggregate come from different walk-forward plans")
    if selection.get("promotion_policy_sha256") != oos.get("promotion_policy_sha256"):
        raise RegistryValidationError("selection and OOS aggregate use different promotion policies")
    if promotion.get("policy_sha256") != oos.get("promotion_policy_sha256"):
        raise RegistryValidationError("promotion decision policy does not match OOS aggregate")

    folds = oos.get("folds")
    if not isinstance(folds, list):
        raise RegistryValidationError("OOS aggregate folds are missing")
    fold_matches = [
        row for row in folds
        if isinstance(row, dict)
        and row.get("fold_id") == fold_id
        and row.get("oos_experiment_id") == candidate_id
    ]
    if len(fold_matches) != 1:
        raise RegistryValidationError(
            "selected candidate must appear exactly once as the same fold OOS experiment in the aggregate"
        )

    if robustness_base.get("experiment_id") != candidate_id:
        raise RegistryValidationError(
            "robustness campaign baseline is not the exact selected OOS candidate"
        )
    if robustness_base.get("preset_sha256") != preset_sha:
        raise RegistryValidationError(
            "robustness campaign preset is not the exact frozen OOS preset"
        )
    if robustness_decision.get("baseline_experiment_id") != candidate_id:
        raise RegistryValidationError("robustness decision baseline experiment mismatch")
    if robustness_decision.get("baseline_preset_sha256") != preset_sha:
        raise RegistryValidationError("robustness decision baseline preset mismatch")
    if robustness_decision.get("policy_sha256") != robustness.get("robustness_policy_sha256"):
        raise RegistryValidationError("robustness decision policy does not match robustness aggregate")

    reasons: list[str] = []
    if promotion.get("decision") != "PROMOTE_TO_FORWARD_DEMO_CANDIDATE" or promotion.get("promotable") is not True:
        reasons.append("OOS_PROMOTION_NOT_PASSED")
    if robustness_decision.get("decision") != "ROBUSTNESS_PASS_FOR_FORWARD_DEMO_REVIEW" or robustness_decision.get("robust") is not True:
        reasons.append("ROBUSTNESS_NOT_PASSED")

    ready = not reasons
    result = {
        "schema_version": 1,
        "methodology": "FORWARD_DEMO_READINESS_V1",
        "decision": "READY_FOR_FORWARD_DEMO" if ready else "NOT_READY_FOR_FORWARD_DEMO",
        "ready": ready,
        "decision_scope": "FORWARD_DEMO_PLANNING_ONLY",
        "live_trading_authorized": False,
        "reasons": reasons,
        "candidate": {
            "experiment_id": candidate_id,
            "preset_sha256": preset_sha,
            "source_fold_id": fold_id,
            "walk_forward_plan_sha256": oos.get("plan_sha256"),
        },
        "evidence": {
            "oos_summary_sha256": sha256_file(oos_summary_path),
            "promotion_decision_sha256": sha256_file(promotion_decision_path),
            "selection_manifest_sha256": sha256_file(selection_manifest_path),
            "robustness_summary_sha256": sha256_file(robustness_summary_path),
            "robustness_decision_sha256": sha256_file(robustness_decision_path),
        },
    }

    if output_path is not None:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oos-summary", required=True)
    parser.add_argument("--promotion-decision", required=True)
    parser.add_argument("--selection-manifest", required=True)
    parser.add_argument("--robustness-summary", required=True)
    parser.add_argument("--robustness-decision", required=True)
    parser.add_argument("--output")
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args()
    try:
        result = evaluate_readiness(
            args.oos_summary,
            args.promotion_decision,
            args.selection_manifest,
            args.robustness_summary,
            args.robustness_decision,
            args.output,
        )
    except RegistryValidationError as exc:
        parser.error(str(exc))
        return
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    if args.require_ready and not result["ready"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
