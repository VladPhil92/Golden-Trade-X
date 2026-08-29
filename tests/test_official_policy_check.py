import json
from pathlib import Path

import pytest

from scripts.official_policy_check import (
    OfficialPolicyValidationError,
    validate_official_policy_bundle,
)


FILES = (
    "promotion_policy.v1.json",
    "robustness_policy.v1.json",
    "forward_demo_policy.v1.json",
    "walk_forward_plan.v1.json",
)


def _copy_bundle(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    source = Path("config")
    for name in FILES:
        (tmp_path / name).write_text((source / name).read_text(encoding="utf-8"), encoding="utf-8")
    return tmp_path


def _mutate(path: Path, callback) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    callback(payload)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_official_policy_bundle_is_frozen_and_never_authorizes_live_capital() -> None:
    result = validate_official_policy_bundle("config")
    assert result["decision"] == "POLICY_BUNDLE_FROZEN"
    assert result["promotion"]["approved"] is True
    assert result["robustness"]["approved"] is True
    assert result["forward_demo"]["approved"] is True
    assert result["walk_forward"]["plan_id"] == "GTX-WF-V1"
    assert result["live_trading_authorized"] is False
    assert result["real_capital_authorized"] is False
    assert len(result["bundle_sha256"]) == 64


def test_rejects_draft_or_unapproved_official_policy(tmp_path: Path) -> None:
    root = _copy_bundle(tmp_path)
    _mutate(root / "promotion_policy.v1.json", lambda p: p.update({"approved": False}))
    with pytest.raises(OfficialPolicyValidationError, match="approved=true"):
        validate_official_policy_bundle(root)


def test_rejects_unsupported_or_duplicate_metric(tmp_path: Path) -> None:
    root = _copy_bundle(tmp_path)

    def bad_metric(payload: dict) -> None:
        payload["criteria"][0]["metric"] = "made_up_metric"

    _mutate(root / "robustness_policy.v1.json", bad_metric)
    with pytest.raises(OfficialPolicyValidationError, match="unsupported metric"):
        validate_official_policy_bundle(root)

    root = _copy_bundle(tmp_path / "second")

    def duplicate(payload: dict) -> None:
        payload["criteria"][1]["metric"] = payload["criteria"][0]["metric"]

    _mutate(root / "promotion_policy.v1.json", duplicate)
    with pytest.raises(OfficialPolicyValidationError, match="duplicate criterion"):
        validate_official_policy_bundle(root)


def test_forward_policy_must_remain_demo_and_stable_build(tmp_path: Path) -> None:
    root = _copy_bundle(tmp_path)

    def real_mode(payload: dict) -> None:
        payload["observation"]["require_trade_mode"] = "REAL"

    _mutate(root / "forward_demo_policy.v1.json", real_mode)
    with pytest.raises(OfficialPolicyValidationError, match="must be DEMO"):
        validate_official_policy_bundle(root)

    root = _copy_bundle(tmp_path / "second")

    def unstable(payload: dict) -> None:
        payload["observation"]["require_stable_terminal_build"] = False

    _mutate(root / "forward_demo_policy.v1.json", unstable)
    with pytest.raises(OfficialPolicyValidationError, match="stable terminal build"):
        validate_official_policy_bundle(root)


def test_walk_forward_must_reference_frozen_promotion_policy(tmp_path: Path) -> None:
    root = _copy_bundle(tmp_path)

    def wrong_reference(payload: dict) -> None:
        payload["promotion_policy_path"] = "promotion_policy.example.json"

    _mutate(root / "walk_forward_plan.v1.json", wrong_reference)
    with pytest.raises(OfficialPolicyValidationError, match="promotion_policy_path"):
        validate_official_policy_bundle(root)
