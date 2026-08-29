from pathlib import Path


SCRIPT = Path("scripts/capture-official-calendar.ps1")


def _text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_capture_bootstrap_uses_verified_snapshot_materialization_only() -> None:
    text = _text()
    assert "capture_official_calendar_sources.py" in text
    assert "materialize_verified_official_calendar.py" in text
    assert "economic_calendar_contract.py" in text
    assert "materialize_official_calendar.py" not in text


def test_capture_bootstrap_cannot_approve_calendar() -> None:
    text = _text().lower()
    assert "freeze_approved_economic_calendar.py" not in text
    assert "--approved" not in text
    assert "approve_official_economic_calendar" not in text
    assert "approved=false" in text


def test_capture_bootstrap_requires_verified_manifest_and_live_denial() -> None:
    text = _text()
    assert "source_manifest.json" in text
    assert "source_manifest_verified" in text
    assert "live_trading_authorized" in text
    assert "real_capital_authorized" in text


def test_capture_bootstrap_installs_exact_windows_calendar_dependencies() -> None:
    text = _text()
    assert 'requests==2.34.2' in text
    assert 'tzdata==2026.3' in text
    assert "America/New_York" in text
    assert "-m pip install" in text
