import json
from pathlib import Path

import pytest

from scripts.economic_calendar_contract import generate_mql5_include
from scripts.pre_campaign_readiness import CampaignReadinessError, evaluate_campaign_readiness


def _write(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _copy(path: Path, source_name: str) -> Path:
    path.write_text((Path("config") / source_name).read_text(encoding="utf-8"), encoding="utf-8")
    return path


def _calendar(approved: bool = True) -> dict:
    return {
        "schema_version": 1,
        "calendar_id": "TEST-CALENDAR",
        "approved": approved,
        "coverage": {
            "start_utc": "2021-01-01T00:00:00Z",
            "end_utc": "2025-12-31T23:59:59Z",
        },
        "events": [
            {
                "event": "NFP",
                "release_utc": "2022-02-04T13:30:00Z",
                "source_authority": "BLS",
                "source_url": "https://www.bls.gov/schedule/2022/",
            },
            {
                "event": "CPI",
                "release_utc": "2022-02-10T13:30:00Z",
                "source_authority": "BLS",
                "source_url": "https://www.bls.gov/schedule/2022/",
            },
            {
                "event": "FOMC",
                "release_utc": "2022-03-16T18:00:00Z",
                "source_authority": "FEDERAL_RESERVE",
                "source_url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
            },
        ],
    }


def _environment(approved: bool = True) -> dict:
    return {
        "schema_version": 1,
        "environment_id": "TEST-XAUUSD-M15-DEMO",
        "approved": approved,
        "live_trading_authorized": False,
        "require_trade_mode": "DEMO",
        "broker_label": "TEST-BROKER-A",
        "account_company": "Test Broker Ltd",
        "account_server": "TestBroker-Demo",
        "symbol": "XAUUSD",
        "timeframe": "M15",
        "mt5_build": "5555",
        "modelling": "Every tick based on real ticks",
        "tester_model": 4,
        "expert": "GoldenTradeX\\GoldenTradeX.ex5",
        "execution_mode": 0,
        "portable_mode": True,
        "deposit": 10000,
        "currency": "USD",
        "leverage": 100,
        "spread_mode": "tester/broker observed",
        "commission": None,
        "swap_mode": "tester/broker observed",
        "slippage_points": 0,
        "optimization": False,
        "forward_mode": "disabled",
        "forward_mode_code": 0,
    }


def _fixture(
    tmp_path: Path,
    *,
    calendar_approved: bool = True,
    environment_approved: bool = True,
    campaign_id: str = "TEST-OFFICIAL",
    broker_labels: list[str] | None = None,
) -> tuple[Path, Path]:
    calendar_doc = _calendar(calendar_approved)
    calendar = _write(tmp_path / "calendar.json", calendar_doc)
    include = generate_mql5_include(calendar_doc, tmp_path / "EconomicCalendarData.mqh")

    for name in ("promotion_policy.v1.json", "robustness_policy.v1.json", "forward_demo_policy.v1.json"):
        _copy(tmp_path / name, name)
    _copy(tmp_path / "walk_forward_plan.v1.json", "walk_forward_plan.v1.json")

    environment = _write(tmp_path / "environment.json", _environment(environment_approved))
    labels = broker_labels or ["BROKER-A-DEMO", "BROKER-B-DEMO"]
    _write(
        tmp_path / "robustness_template.json",
        {
            "schema_version": 1,
            "template_id": "TEST-ROBUSTNESS",
            "parameter_scenarios": [],
            "broker_requirements": {
                "required_labels": labels,
                "minimum_distinct_brokers": 2,
            },
            "modeled_cost_scenarios": [],
            "executed_metadata_stress": [],
        },
    )
    (tmp_path / "campaign.lock").write_text(
        "MetaTrader5==5.0.6147; platform_system == \"Windows\"\npytest==9.1.1\n",
        encoding="utf-8",
    )
    campaign = _write(
        tmp_path / "campaign.json",
        {
            "campaign_id": campaign_id,
            "execution_environment_path": environment.name,
            "economic_calendar_path": calendar.name,
            "python_runtime_lock_path": "campaign.lock",
            "walk_forward_config_path": "walk_forward_plan.v1.json",
            "robustness_template_path": "robustness_template.json",
            "robustness_policy_path": "robustness_policy.v1.json",
            "forward_policy_path": "forward_demo_policy.v1.json",
        },
    )
    return campaign, include


def test_ready_to_freeze_requires_complete_approved_repository_inputs(tmp_path: Path) -> None:
    campaign, include = _fixture(tmp_path)
    result = evaluate_campaign_readiness(campaign, include)
    assert result["schema_version"] == 2
    assert result["decision"] == "READY_TO_FREEZE"
    assert result["ready"] is True
    assert result["execution_environment"]["trade_mode"] == "DEMO"
    assert result["economic_calendar"]["coverage"]["end_utc"] == "2025-12-31T23:59:59Z"
    assert result["robustness_brokers"] == ["BROKER-A-DEMO", "BROKER-B-DEMO"]
    assert result["python_runtime_pin_count"] == 2
    assert len(result["policy_bundle_sha256"]) == 64
    assert result["live_trading_authorized"] is False
    assert result["real_capital_authorized"] is False


def test_draft_calendar_blocks_official_readiness(tmp_path: Path) -> None:
    campaign, include = _fixture(tmp_path, calendar_approved=False)
    with pytest.raises(CampaignReadinessError, match="calendar is not approved"):
        evaluate_campaign_readiness(campaign, include)


def test_unapproved_execution_environment_blocks_readiness(tmp_path: Path) -> None:
    campaign, include = _fixture(tmp_path, environment_approved=False)
    with pytest.raises(CampaignReadinessError, match="execution environment is not approved"):
        evaluate_campaign_readiness(campaign, include)


def test_robustness_placeholder_broker_blocks_readiness(tmp_path: Path) -> None:
    campaign, include = _fixture(
        tmp_path,
        broker_labels=["REPLACE_WITH_BROKER_A", "BROKER-B-DEMO"],
    )
    with pytest.raises(CampaignReadinessError, match="still contain placeholders"):
        evaluate_campaign_readiness(campaign, include)


def test_calendar_must_cover_complete_walk_forward_period(tmp_path: Path) -> None:
    campaign, include = _fixture(tmp_path)
    walk = tmp_path / "walk_forward_plan.v1.json"
    payload = json.loads(walk.read_text(encoding="utf-8"))
    payload["start_date"] = "2020-01-01"
    _write(walk, payload)
    with pytest.raises(CampaignReadinessError, match="does not cover"):
        evaluate_campaign_readiness(campaign, include)


def test_calendar_cannot_end_before_last_instant_of_exclusive_window(tmp_path: Path) -> None:
    campaign, _ = _fixture(tmp_path)
    calendar = tmp_path / "calendar.json"
    payload = json.loads(calendar.read_text(encoding="utf-8"))
    payload["coverage"]["end_utc"] = "2025-12-31T23:59:58Z"
    _write(calendar, payload)
    include = generate_mql5_include(payload, tmp_path / "EconomicCalendarData.mqh")
    with pytest.raises(CampaignReadinessError, match="half-open walk-forward period"):
        evaluate_campaign_readiness(campaign, include)


def test_generated_include_drift_blocks_readiness(tmp_path: Path) -> None:
    campaign, include = _fixture(tmp_path)
    include.write_text(include.read_text(encoding="utf-8") + "// drift\n", encoding="utf-8")
    with pytest.raises(CampaignReadinessError, match="does not match"):
        evaluate_campaign_readiness(campaign, include)


def test_dependency_lock_must_use_exact_pins_and_metatrader(tmp_path: Path) -> None:
    campaign, include = _fixture(tmp_path)
    (tmp_path / "campaign.lock").write_text("pytest~=9.1\n", encoding="utf-8")
    with pytest.raises(CampaignReadinessError, match="exact direct pins"):
        evaluate_campaign_readiness(campaign, include)

    campaign, include = _fixture(tmp_path / "second")
    (tmp_path / "second" / "campaign.lock").write_text("pytest==9.1.1\n", encoding="utf-8")
    with pytest.raises(CampaignReadinessError, match="pin MetaTrader5"):
        evaluate_campaign_readiness(campaign, include)


def test_draft_campaign_id_blocks_readiness(tmp_path: Path) -> None:
    campaign, include = _fixture(tmp_path, campaign_id="TEST-DRAFT")
    with pytest.raises(CampaignReadinessError, match="must not contain DRAFT"):
        evaluate_campaign_readiness(campaign, include)


def test_campaign_must_reference_frozen_policy_files(tmp_path: Path) -> None:
    campaign, include = _fixture(tmp_path)
    payload = json.loads(campaign.read_text(encoding="utf-8"))
    payload["forward_policy_path"] = "forward_demo_policy.example.json"
    _write(campaign, payload)
    with pytest.raises(CampaignReadinessError, match="must reference frozen"):
        evaluate_campaign_readiness(campaign, include)
