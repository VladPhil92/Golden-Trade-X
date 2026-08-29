import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import strategy_tester_harness as harness
from scripts.experiment_registry import RegistryValidationError, sha256_file
from scripts.forward_demo_readiness import evaluate_readiness
from scripts.promotion_gate import _compare as promotion_compare
from scripts.promotion_gate import evaluate_promotion
from scripts.robustness_gate import REQUIRED_EVIDENCE_CLASSES
from scripts.robustness_gate import _compare as robustness_compare
from scripts.robustness_gate import evaluate_robustness
from scripts.strategy_tester_results import StrategyTesterResultError


def _write_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _tester_spec() -> dict:
    return {
        "git_sha": "b" * 40,
        "preset_path": "preset.set",
        "expert": "GoldenTradeX\\GoldenTradeX.ex5",
        "expert_parameters": "GoldenTradeX.set",
        "symbol": "XAUUSD",
        "timeframe": "M15",
        "period_start": "2024-01-01T00:00:00Z",
        "period_end": "2024-12-31T23:59:59Z",
        "tester_model": 4,
        "execution_mode": 0,
        "portable_mode": True,
        "modelling": "Every tick based on real ticks",
        "deposit": 10000,
        "currency": "USD",
        "leverage": 100,
        "optimization": False,
        "forward_mode_code": 0,
    }


class _FakeConnection:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def _patch_harness_registry(monkeypatch, spec: dict):
    connection = _FakeConnection()
    statuses = []
    artifacts = []
    monkeypatch.setattr(harness, "load_spec", lambda path: dict(spec))
    monkeypatch.setattr(harness, "connect_registry", lambda path: connection)
    monkeypatch.setattr(
        harness,
        "register_experiment",
        lambda conn, loaded, base_dir, status: {"experiment_id": "exp-001", "status": status},
    )

    def fake_status(conn, experiment_id, status):
        statuses.append(status)
        return {"experiment_id": experiment_id, "status": status}

    monkeypatch.setattr(harness, "set_status", fake_status)
    monkeypatch.setattr(
        harness,
        "attach_artifact",
        lambda conn, experiment_id, kind, path: artifacts.append((kind, Path(path).name)),
    )
    return connection, statuses, artifacts


def test_execution_manifest_records_all_evidence_fields(tmp_path: Path) -> None:
    manifest = _write_json(tmp_path / "manifest.json", {"status": "PREPARED_NOT_EXECUTED"})
    report = tmp_path / "report.htm"
    normalized = tmp_path / "normalized.json"
    report.write_text("report", encoding="utf-8")
    normalized.write_text("{}", encoding="utf-8")

    harness._update_execution_manifest(
        manifest,
        status="COMPLETED",
        exit_code=0,
        report_path=report,
        normalized_path=normalized,
        error="diagnostic",
    )
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["status"] == "COMPLETED"
    assert payload["terminal_exit_code"] == 0
    assert payload["report_sha256"] == sha256_file(report)
    assert payload["normalized_results_sha256"] == sha256_file(normalized)
    assert payload["report_size"] > 0
    assert payload["normalized_results_size"] > 0
    assert payload["error"] == "diagnostic"


def test_execute_terminal_windows_contract(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(harness.platform, "system", lambda: "Windows")
    missing = tmp_path / "missing.exe"
    with pytest.raises(RegistryValidationError, match="terminal executable not found"):
        harness.execute_terminal(missing, tmp_path / "tester.ini")

    terminal = tmp_path / "terminal64.exe"
    terminal.write_bytes(b"stub")
    captured = {}

    def fake_run(command, check, timeout):
        captured.update(command=command, check=check, timeout=timeout)
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr(harness.subprocess, "run", fake_run)
    assert harness.execute_terminal(terminal, tmp_path / "tester.ini", timeout_seconds=13, portable_mode=False) == 7
    assert captured["check"] is False
    assert captured["timeout"] == 13
    assert "/portable" not in captured["command"]


def test_registered_experiment_prepare_only_closes_registry(monkeypatch, tmp_path: Path) -> None:
    connection, statuses, artifacts = _patch_harness_registry(monkeypatch, _tester_spec())
    spec_path = _write_json(tmp_path / "spec.json", _tester_spec())
    record = harness.run_registered_experiment(spec_path, tmp_path / "registry.sqlite", tmp_path / "runs")
    assert record["status"] == "PREPARED"
    assert statuses == ["PREPARED"]
    assert {kind for kind, _ in artifacts} == {"tester_ini", "execution_manifest"}
    assert connection.closed is True


def test_registered_experiment_fails_when_terminal_produces_no_report(monkeypatch, tmp_path: Path) -> None:
    connection, statuses, artifacts = _patch_harness_registry(monkeypatch, _tester_spec())
    spec_path = _write_json(tmp_path / "spec.json", _tester_spec())
    monkeypatch.setattr(harness, "execute_terminal", lambda *args, **kwargs: 0)

    with pytest.raises(RegistryValidationError, match="did not produce valid evidence"):
        harness.run_registered_experiment(
            spec_path, tmp_path / "registry.sqlite", tmp_path / "runs", terminal="terminal.exe"
        )
    assert statuses[-1] == "FAILED"
    assert ("execution_manifest", "execution_manifest.json") in artifacts
    assert connection.closed is True


def test_registered_experiment_fails_on_report_normalization(monkeypatch, tmp_path: Path) -> None:
    connection, statuses, _ = _patch_harness_registry(monkeypatch, _tester_spec())
    spec_path = _write_json(tmp_path / "spec.json", _tester_spec())

    def fake_execute(terminal, ini_path, **kwargs):
        Path(ini_path).parent.joinpath("strategy_tester_report.htm").write_text("report", encoding="utf-8")
        return 0

    def fail_normalization(*args, **kwargs):
        raise StrategyTesterResultError("malformed report")

    monkeypatch.setattr(harness, "execute_terminal", fake_execute)
    monkeypatch.setattr(harness, "write_normalized_results", fail_normalization)
    with pytest.raises(RegistryValidationError, match="failed normalization"):
        harness.run_registered_experiment(
            spec_path, tmp_path / "registry.sqlite", tmp_path / "runs", terminal="terminal.exe"
        )
    assert statuses[-1] == "FAILED"
    assert connection.closed is True


def test_registered_experiment_completes_only_with_normalized_results(monkeypatch, tmp_path: Path) -> None:
    connection, statuses, artifacts = _patch_harness_registry(monkeypatch, _tester_spec())
    spec_path = _write_json(tmp_path / "spec.json", _tester_spec())

    def fake_execute(terminal, ini_path, **kwargs):
        Path(ini_path).parent.joinpath("strategy_tester_report.htm").write_text("report", encoding="utf-8")
        return 0

    def fake_normalize(report_path, normalized_path, experiment_id):
        _write_json(Path(normalized_path), {"experiment_id": experiment_id, "summary": {"total_trades": 1}})

    monkeypatch.setattr(harness, "execute_terminal", fake_execute)
    monkeypatch.setattr(harness, "write_normalized_results", fake_normalize)
    record = harness.run_registered_experiment(
        spec_path, tmp_path / "registry.sqlite", tmp_path / "runs", terminal="terminal.exe"
    )
    assert record["status"] == "COMPLETED"
    assert statuses == ["PREPARED", "RUNNING", "COMPLETED"]
    assert ("strategy_tester_report", "strategy_tester_report.htm") in artifacts
    assert ("normalized_results", "normalized_results.json") in artifacts
    manifest = json.loads((tmp_path / "runs" / "exp-001" / "execution_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "COMPLETED"
    assert manifest["terminal_exit_code"] == 0
    assert connection.closed is True


@pytest.mark.parametrize(
    ("operator", "observed", "target", "expected"),
    [
        (">=", 2.0, 2.0, True),
        ("<=", 2.0, 2.0, True),
        (">", 2.0, 1.0, True),
        ("<", 1.0, 2.0, True),
        ("==", 2.0, 2.0, True),
        (">", 1.0, 2.0, False),
    ],
)
def test_gate_comparators_cover_supported_operators(operator, observed, target, expected) -> None:
    assert promotion_compare(observed, operator, target) is expected
    assert robustness_compare(observed, operator, target) is expected


def test_gate_comparators_reject_unknown_operator() -> None:
    with pytest.raises(RegistryValidationError, match="unsupported promotion operator"):
        promotion_compare(1.0, "!=", 1.0)
    with pytest.raises(RegistryValidationError, match="unsupported robustness operator"):
        robustness_compare(1.0, "!=", 1.0)


def _promotion_files(tmp_path: Path, *, approved=True, observed=2.0, operator=">=", target=1.0):
    policy = _write_json(
        tmp_path / "promotion.json",
        {
            "schema_version": 1,
            "policy_id": "PROMO-V1",
            "approved": approved,
            "criteria": [{"metric": "score", "operator": operator, "value": target}],
        },
    )
    summary = _write_json(
        tmp_path / "oos.json",
        {
            "methodology": "ROLLING_FROZEN_OOS_AGGREGATION",
            "promotion_policy_sha256": sha256_file(policy),
            "summary": {"score": observed},
        },
    )
    return summary, policy


def test_promotion_gate_pass_fail_unapproved_and_missing_metric(tmp_path: Path) -> None:
    summary, policy = _promotion_files(tmp_path / "pass")
    assert evaluate_promotion(summary, policy, tmp_path / "pass" / "decision.json")["promotable"] is True

    summary, policy = _promotion_files(tmp_path / "fail", observed=0.0)
    decision = evaluate_promotion(summary, policy)
    assert decision["decision"] == "DO_NOT_PROMOTE"
    assert decision["promotable"] is False

    summary, policy = _promotion_files(tmp_path / "unapproved", approved=False)
    assert evaluate_promotion(summary, policy)["decision"] == "BLOCKED_POLICY_UNAPPROVED"

    summary, policy = _promotion_files(tmp_path / "missing")
    payload = json.loads(summary.read_text(encoding="utf-8"))
    payload["summary"] = {}
    _write_json(summary, payload)
    missing = evaluate_promotion(summary, policy)
    assert missing["criteria"][0]["observed"] is None
    assert missing["promotable"] is False


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda s, p: s.update(methodology="wrong"), "unsupported OOS summary methodology"),
        (lambda s, p: p.update(schema_version=2), "schema_version"),
        (lambda s, p: p.update(policy_id=""), "policy_id"),
        (lambda s, p: p.update(approved="yes"), "approved"),
        (lambda s, p: p.update(criteria=[]), "criteria"),
        (lambda s, p: p.update(criteria=["bad"]), "criterion must be an object"),
        (lambda s, p: p.update(criteria=[{"metric": "", "operator": ">", "value": 1}]), "metric is required"),
        (lambda s, p: p.update(criteria=[{"metric": "score", "operator": "!=", "value": 1}]), "unsupported promotion operator"),
        (lambda s, p: p.update(criteria=[{"metric": "score", "operator": ">", "value": True}]), "value must be numeric"),
    ],
)
def test_promotion_gate_validation_fails_closed(tmp_path: Path, mutation, message: str) -> None:
    summary, policy = _promotion_files(tmp_path)
    s = json.loads(summary.read_text(encoding="utf-8"))
    p = json.loads(policy.read_text(encoding="utf-8"))
    mutation(s, p)
    _write_json(policy, p)
    if s.get("methodology") == "ROLLING_FROZEN_OOS_AGGREGATION":
        s["promotion_policy_sha256"] = sha256_file(policy)
    _write_json(summary, s)
    with pytest.raises(RegistryValidationError, match=message):
        evaluate_promotion(summary, policy)


def _robustness_files(tmp_path: Path, *, approved=True, observed=2.0):
    policy = _write_json(
        tmp_path / "robustness_policy.json",
        {
            "schema_version": 1,
            "policy_id": "ROBUST-V1",
            "approved": approved,
            "criteria": [{"metric": "score", "operator": ">=", "value": 1.0}],
        },
    )
    summary = _write_json(
        tmp_path / "robustness_summary.json",
        {
            "methodology": "ROBUSTNESS_AGGREGATION_V1",
            "evidence_classes": dict(REQUIRED_EVIDENCE_CLASSES),
            "robustness_policy_sha256": sha256_file(policy),
            "campaign_id": "campaign",
            "baseline": {"experiment_id": "exp", "preset_sha256": "a" * 64},
            "summary": {"score": observed},
        },
    )
    return summary, policy


def test_robustness_gate_pass_fail_unapproved_and_missing_metric(tmp_path: Path) -> None:
    summary, policy = _robustness_files(tmp_path / "pass")
    result = evaluate_robustness(summary, policy, tmp_path / "pass" / "decision.json")
    assert result["robust"] is True
    assert result["live_trading_authorized"] is False

    summary, policy = _robustness_files(tmp_path / "fail", observed=0.0)
    assert evaluate_robustness(summary, policy)["decision"] == "ROBUSTNESS_FAIL"

    summary, policy = _robustness_files(tmp_path / "unapproved", approved=False)
    assert evaluate_robustness(summary, policy)["decision"] == "BLOCKED_POLICY_UNAPPROVED"

    summary, policy = _robustness_files(tmp_path / "missing")
    payload = json.loads(summary.read_text(encoding="utf-8"))
    payload["summary"] = {}
    _write_json(summary, payload)
    missing = evaluate_robustness(summary, policy)
    assert missing["criteria"][0]["observed"] is None
    assert missing["robust"] is False


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda s, p: s.update(methodology="wrong"), "unsupported robustness summary methodology"),
        (lambda s, p: s.update(evidence_classes={}), "evidence classes"),
        (lambda s, p: p.update(schema_version=2), "schema_version"),
        (lambda s, p: p.update(policy_id=""), "policy_id"),
        (lambda s, p: p.update(approved="yes"), "approved"),
        (lambda s, p: p.update(criteria=[]), "criteria"),
        (lambda s, p: p.update(criteria=["bad"]), "criterion must be an object"),
        (lambda s, p: p.update(criteria=[{"metric": "", "operator": ">", "value": 1}]), "metric is required"),
        (lambda s, p: p.update(criteria=[{"metric": "score", "operator": "!=", "value": 1}]), "unsupported robustness operator"),
        (lambda s, p: p.update(criteria=[{"metric": "score", "operator": ">", "value": True}]), "target must be numeric"),
    ],
)
def test_robustness_gate_validation_fails_closed(tmp_path: Path, mutation, message: str) -> None:
    summary, policy = _robustness_files(tmp_path)
    s = json.loads(summary.read_text(encoding="utf-8"))
    p = json.loads(policy.read_text(encoding="utf-8"))
    mutation(s, p)
    _write_json(policy, p)
    if s.get("methodology") == "ROBUSTNESS_AGGREGATION_V1" and s.get("evidence_classes") == REQUIRED_EVIDENCE_CLASSES:
        s["robustness_policy_sha256"] = sha256_file(policy)
    _write_json(summary, s)
    with pytest.raises(RegistryValidationError, match=message):
        evaluate_robustness(summary, policy)


def _readiness_files(tmp_path: Path):
    oos = _write_json(
        tmp_path / "oos.json",
        {
            "methodology": "ROLLING_FROZEN_OOS_AGGREGATION",
            "plan_sha256": "plan",
            "promotion_policy_sha256": "promotion-policy",
            "folds": [{"fold_id": "WF001", "oos_experiment_id": "candidate"}],
        },
    )
    promotion = _write_json(
        tmp_path / "promotion.json",
        {
            "oos_summary_sha256": sha256_file(oos),
            "policy_sha256": "promotion-policy",
            "decision": "PROMOTE_TO_FORWARD_DEMO_CANDIDATE",
            "promotable": True,
            "live_trading_authorized": False,
        },
    )
    selection = _write_json(
        tmp_path / "selection.json",
        {
            "methodology": "IS_SELECTION_THEN_FROZEN_OOS",
            "fold_id": "WF001",
            "plan_sha256": "plan",
            "promotion_policy_sha256": "promotion-policy",
            "selected": {"frozen_preset_sha256": "preset"},
            "oos": {"experiment_id": "candidate"},
        },
    )
    robustness = _write_json(
        tmp_path / "robustness.json",
        {
            "methodology": "ROBUSTNESS_AGGREGATION_V1",
            "robustness_policy_sha256": "robust-policy",
            "baseline": {"experiment_id": "candidate", "preset_sha256": "preset"},
        },
    )
    robust_decision = _write_json(
        tmp_path / "robust_decision.json",
        {
            "robustness_summary_sha256": sha256_file(robustness),
            "baseline_experiment_id": "candidate",
            "baseline_preset_sha256": "preset",
            "policy_sha256": "robust-policy",
            "decision": "ROBUSTNESS_PASS_FOR_FORWARD_DEMO_REVIEW",
            "robust": True,
            "live_trading_authorized": False,
        },
    )
    return oos, promotion, selection, robustness, robust_decision


def test_readiness_negative_decisions_are_valid_but_not_ready(tmp_path: Path) -> None:
    files = _readiness_files(tmp_path)
    promotion = files[1]
    payload = json.loads(promotion.read_text(encoding="utf-8"))
    payload.update(decision="DO_NOT_PROMOTE", promotable=False)
    _write_json(promotion, payload)
    result = evaluate_readiness(*files, output_path=tmp_path / "readiness.json")
    assert result["ready"] is False
    assert "OOS_PROMOTION_NOT_PASSED" in result["reasons"]
    assert result["live_trading_authorized"] is False


def test_readiness_rejects_live_authorization(tmp_path: Path) -> None:
    files = _readiness_files(tmp_path)
    promotion = files[1]
    payload = json.loads(promotion.read_text(encoding="utf-8"))
    payload["live_trading_authorized"] = True
    _write_json(promotion, payload)
    with pytest.raises(RegistryValidationError, match="deny live trading"):
        evaluate_readiness(*files)


def _load_campaign_test_module():
    path = Path(__file__).with_name("test_official_campaign.py")
    spec = importlib.util.spec_from_file_location("gtx_test_official_campaign_fixture", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("document_key", "field", "value", "message"),
    [
        ("campaign_lock_path", "methodology", "WRONG", "unsupported campaign lock methodology"),
        ("campaign_lock_path", "status", "WRONG", "OFFICIAL_CAMPAIGN_FROZEN"),
        ("campaign_lock_path", "live_trading_authorized", True, "deny live trading"),
        ("selection_manifest_path", "methodology", "WRONG", "unsupported selection manifest methodology"),
        ("selection_manifest_path", "evidence_status", "WRONG", "official frozen OOS evidence"),
        ("oos_summary_path", "methodology", "WRONG", "unsupported OOS summary methodology"),
        ("promotion_decision_path", "live_trading_authorized", True, "deny live trading"),
        ("robustness_plan_path", "methodology", "WRONG", "unsupported robustness plan methodology"),
        ("robustness_summary_path", "methodology", "WRONG", "unsupported robustness summary methodology"),
        ("robustness_decision_path", "live_trading_authorized", True, "deny live trading"),
        ("readiness_path", "methodology", "WRONG", "unsupported readiness methodology"),
        ("readiness_path", "live_trading_authorized", True, "deny live trading"),
        ("forward_plan_path", "methodology", "WRONG", "unsupported forward-demo plan methodology"),
        ("forward_plan_path", "live_trading_authorized", True, "deny live trading"),
        ("forward_evaluation_path", "methodology", "WRONG", "unsupported forward-demo evidence methodology"),
        ("forward_evaluation_path", "live_trading_authorized", True, "deny live trading"),
        ("forward_gate_path", "methodology", "WRONG", "unsupported forward-demo gate methodology"),
        ("forward_gate_path", "live_trading_authorized", True, "deny live trading"),
    ],
)
def test_rc1_lineage_rejects_unsafe_or_wrong_methodology(
    tmp_path: Path, document_key: str, field: str, value, message: str
) -> None:
    fixture = _load_campaign_test_module()
    bundle, _ = fixture._build_release_bundle(tmp_path)
    bundle_doc = json.loads(bundle.read_text(encoding="utf-8"))
    target = tmp_path / bundle_doc[document_key]
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload[field] = value
    _write_json(target, payload)

    from scripts.rc1_release_review_gate import evaluate_rc1_release_review

    with pytest.raises(RegistryValidationError, match=message):
        evaluate_rc1_release_review(bundle)
