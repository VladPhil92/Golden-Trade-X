from __future__ import annotations

from pathlib import Path

from scripts.security_scan import scan_path, scan_text


def test_detects_high_risk_credential_patterns() -> None:
    assert "private key" in scan_text("-----BEGIN PRIVATE KEY-----\nabc")
    assert "GitHub token" in scan_text("token=ghp_abcdefghijklmnopqrstuvwxyz123456")
    assert "AWS access key" in scan_text("AKIA1234567890ABCDEF")
    assert "Telegram bot token" in scan_text("123456789:abcdefghijklmnopqrstuvwxyzABCDEFGHI")


def test_does_not_flag_normal_placeholders() -> None:
    text = "GTX_TELEGRAM_TOKEN=replace-me\nGITHUB_TOKEN=${{ secrets.GITHUB_TOKEN }}"
    assert scan_text(text) == []


def test_tracked_env_is_always_rejected(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("SAFE=value\n", encoding="utf-8")
    assert scan_path(env, tmp_path) == [".env: tracked .env file"]


def test_env_example_is_allowed_even_with_variable_names(tmp_path: Path) -> None:
    example = tmp_path / ".env.example"
    example.write_text("GTX_TELEGRAM_TOKEN=replace-me\n", encoding="utf-8")
    assert scan_path(example, tmp_path) == []
