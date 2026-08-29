from pathlib import Path

from scripts.validate_set import parse_set, validate_params


def test_ea_declares_and_enforces_real_money_interlock() -> None:
    source = Path("MQL5/Experts/GoldenTradeX/GoldenTradeX.mq5").read_text(encoding="utf-8")
    assert "input bool    InpAllowRealTrading = false;" in source
    assert "mode == ACCOUNT_TRADE_MODE_REAL && !InpAllowRealTrading" in source
    assert "return INIT_FAILED;" in source
    assert '"|InpAllowRealTrading=" + B(InpAllowRealTrading)' in source


def test_repository_presets_remain_fail_closed() -> None:
    for path in (Path("config/GoldenTradeX.set"), Path("config/GoldenTradeX_XAGUSD.set")):
        params = parse_set(path)
        assert params["InpAllowRealTrading"].lower() == "false"
        assert validate_params(params, str(path)) == []


def test_validator_rejects_real_money_override() -> None:
    params = parse_set("config/GoldenTradeX.set")
    params["InpAllowRealTrading"] = "true"
    errors = validate_params(params, "synthetic")
    assert any("must remain false" in error for error in errors)
