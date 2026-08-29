import json
from pathlib import Path

import pytest

from scripts.experiment_registry import RegistryValidationError, sha256_file
from scripts.forward_demo_readiness import evaluate_readiness


def _write(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _bundle(tmp_path: Path):
    oos = _write(tmp_path / "oos.json", {
        "methodology": "ROLLING_FROZEN_OOS_AGGREGATION",
        "plan_sha256": "plan",
        "promotion_policy_sha256": "promo-policy",
        "folds": [{"fold_id": "WF-001", "oos_experiment_id": "candidate"}],
    })
    promotion = _write(tmp_path / "promotion.json", {
        "oos_summary_sha256": sha256_file(oos),
        "policy_sha256": "promo-policy",
        "decision": "PROMOTE_TO_FORWARD_DEMO_CANDIDATE",
        "promotable": True,
        "live_trading_authorized": False,
    })
    selection = _write(tmp_path / "selection.json", {
        "methodology": "IS_SELECTION_THEN_FROZEN_OOS",
        "fold_id": "WF-001",
        "plan_sha256": "plan",
        "promotion_policy_sha256": "promo-policy",
        "selected": {"frozen_preset_sha256": "preset"},
        "oos": {"experiment_id": "candidate"},
    })
    robustness = _write(tmp_path / "robustness.json", {
        "methodology": "ROBUSTNESS_AGGREGATION_V1",
        "robustness_policy_sha256": "robust-policy",
        "baseline": {"experiment_id": "candidate", "preset_sha256": "preset"},
    })
    decision = _write(tmp_path / "robustness_decision.json", {
        "robustness_summary_sha256": sha256_file(robustness),
        "baseline_experiment_id": "candidate",
        "baseline_preset_sha256": "preset",
        "policy_sha256": "robust-policy",
        "decision": "ROBUSTNESS_PASS_FOR_FORWARD_DEMO_REVIEW",
        "robust": True,
        "live_trading_authorized": False,
    })
    return [oos, promotion, selection, robustness, decision]


def _mutate(path: Path, fn) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    fn(payload)
    _write(path, payload)


def test_readiness_happy_path_writes_evidence_hashes(tmp_path: Path) -> None:
    files = _bundle(tmp_path)
    out = tmp_path / "ready.json"
    result = evaluate_readiness(*files, output_path=out)
    assert result["ready"] is True
    assert result["decision"] == "READY_FOR_FORWARD_DEMO"
    assert result["live_trading_authorized"] is False
    assert result["evidence"]["oos_summary_sha256"] == sha256_file(files[0])
    assert out.is_file()


@pytest.mark.parametrize(
    ("index", "mutation", "message"),
    [
        (0, lambda d: d.update(methodology="WRONG"), "unsupported OOS summary methodology"),
        (3, lambda d: d.update(methodology="WRONG"), "unsupported robustness summary methodology"),
        (2, lambda d: d.update(methodology="WRONG"), "unsupported selection manifest methodology"),
        (1, lambda d: d.update(oos_summary_sha256="0" * 64), "does not hash"),
        (4, lambda d: d.update(robustness_summary_sha256="0" * 64), "does not hash"),
        (1, lambda d: d.update(live_trading_authorized=True), "deny live trading"),
        (4, lambda d: d.update(live_trading_authorized=True), "deny live trading"),
        (2, lambda d: d.update(selected=None), "lacks selected/OOS identity"),
        (3, lambda d: d.update(baseline=None), "lacks baseline identity"),
        (2, lambda d: d["oos"].update(experiment_id=""), "experiment_id is required"),
        (2, lambda d: d["selected"].update(frozen_preset_sha256=""), "preset SHA-256 is required"),
        (2, lambda d: d.update(fold_id=""), "fold_id is required"),
        (2, lambda d: d.update(plan_sha256="other"), "different walk-forward plans"),
        (2, lambda d: d.update(promotion_policy_sha256="other"), "different promotion policies"),
        (1, lambda d: d.update(policy_sha256="other"), "policy does not match OOS aggregate"),
        (0, lambda d: d.update(folds=[]), "must appear exactly once"),
        (3, lambda d: d["baseline"].update(experiment_id="other"), "exact selected OOS candidate"),
        (3, lambda d: d["baseline"].update(preset_sha256="other"), "exact frozen OOS preset"),
        (4, lambda d: d.update(baseline_experiment_id="other"), "baseline experiment mismatch"),
        (4, lambda d: d.update(baseline_preset_sha256="other"), "baseline preset mismatch"),
        (4, lambda d: d.update(policy_sha256="other"), "policy does not match robustness aggregate"),
    ],
)
def test_readiness_mutations_fail_closed(tmp_path: Path, index: int, mutation, message: str) -> None:
    files = _bundle(tmp_path)
    _mutate(files[index], mutation)
    if index == 0 and "does not hash" not in message:
        _mutate(files[1], lambda d: d.update(oos_summary_sha256=sha256_file(files[0])))
    if index == 3 and "does not hash" not in message:
        _mutate(files[4], lambda d: d.update(robustness_summary_sha256=sha256_file(files[3])))
    with pytest.raises(RegistryValidationError, match=message):
        evaluate_readiness(*files)


def test_readiness_negative_decisions_record_both_reasons(tmp_path: Path) -> None:
    files = _bundle(tmp_path)
    _mutate(files[1], lambda d: d.update(decision="DO_NOT_PROMOTE", promotable=False))
    _mutate(files[4], lambda d: d.update(decision="ROBUSTNESS_FAIL", robust=False))
    result = evaluate_readiness(*files)
    assert result["ready"] is False
    assert result["decision"] == "NOT_READY_FOR_FORWARD_DEMO"
    assert result["reasons"] == ["OOS_PROMOTION_NOT_PASSED", "ROBUSTNESS_NOT_PASSED"]
