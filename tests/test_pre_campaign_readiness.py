import json
from pathlib import Path

import pytest

from scripts.economic_calendar_contract import generate_mql5_include
from scripts.pre_campaign_readiness import CampaignReadinessError, evaluate_campaign_readiness


def _write(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _calendar(approved: bool = True) -> dict:
    return {
        "schema_version": 1,
        "calendar_id": "TEST-CALENDAR",
        "approved": approved,
        "coverage": {
            "start_utc": "2022-01-01T00:00:00Z",
            "end_utc": "2024-01-01T23:59:59Z",
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


def _fixture(tmp_path: Path, *, approved: bool = True, campaign_id: str = "TEST-OFFICIAL") -> tuple[Path, Path]:
    calendar = _write(tmp_path / "calendar.json", _calendar(approved))
    include = generate_mql5_include(_calendar(approved), tmp_path / "EconomicCalendarData.mqh")
    _write(
        tmp_path / "walk.json",
        {
            "start_date": "2022-01-01",
            "end_date": "2023-12-31",
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
            "economic_calendar_path": calendar.name,
            "walk_forward_config_path": "walk.json",
            "python_runtime_lock_path": "campaign.lock",
        },
    )
    return campaign, include


def test_ready_to_freeze_requires_approved_calendar_and_exact_lock(tmp_path: Path) -> None:
    campaign, include = _fixture(tmp_path)
    result = evaluate_campaign_readiness(campaign, include)
    assert result["decision"] == "READY_TO_FREEZE"
    assert result["ready"] is True
    assert result["live_trading_authorized"] is False
    assert result["real_capital_authorized"] is False


def test_draft_calendar_blocks_official_readiness(tmp_path: Path) -> None:
    campaign, include = _fixture(tmp_path, approved=False)
    with pytest.raises(CampaignReadinessError, match="calendar is not approved"):
        evaluate_campaign_readiness(campaign, include)


def test_calendar_must_cover_complete_walk_forward_period(tmp_path: Path) -> None:
    campaign, include = _fixture(tmp_path)
    walk = tmp_path / "walk.json"
    _write(walk, {"start_date": "2021-01-01", "end_date": "2023-12-31"})
    with pytest.raises(CampaignReadinessError, match="does not cover"):
        evaluate_campaign_readiness(campaign, include)


def test_generated_include_drift_blocks_readiness(tmp_path: Path) -> None:
    campaign, include = _fixture(tmp_path)
    include.write_text(include.read_text(encoding="utf-8") + "// drift\n", encoding="utf-8")
    with pytest.raises(CampaignReadinessError, match="does not match"):
        evaluate_campaign_readiness(campaign, include)


def test_dependency_lock_must_use_exact_pins(tmp_path: Path) -> None:
    campaign, include = _fixture(tmp_path)
    (tmp_path / "campaign.lock").write_text("pytest~=9.1\n", encoding="utf-8")
    with pytest.raises(CampaignReadinessError, match="exact direct pins"):
        evaluate_campaign_readiness(campaign, include)


def test_draft_campaign_id_blocks_readiness(tmp_path: Path) -> None:
    campaign, include = _fixture(tmp_path, campaign_id="TEST-DRAFT")
    with pytest.raises(CampaignReadinessError, match="must not contain DRAFT"):
        evaluate_campaign_readiness(campaign, include)
