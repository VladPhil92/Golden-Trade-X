"""Regression tests for conservative MQL5 static guards."""

from pathlib import Path

from scripts.mql5_lint import lint_file


def _lint(tmp_path: Path, source: str):
    path = tmp_path / "Sample.mq5"
    path.write_text(source, encoding="utf-8")
    return lint_file(path)


def test_flags_mql4_style_indicator_call(tmp_path: Path) -> None:
    findings = _lint(tmp_path, "int h = iATR(_Symbol, PERIOD_M15, 14, 0);\n")
    assert any("iATR()" in message for _, message in findings)


def test_flags_literal_zero_stop_loss(tmp_path: Path) -> None:
    source = 'trade.PositionOpen(_Symbol, ORDER_TYPE_BUY, 0.10, ask, 0, ask+10, "GTX");\n'
    findings = _lint(tmp_path, source)
    assert any("SL literal 0" in message for _, message in findings)


def test_flags_global_variable_outside_namespace(tmp_path: Path) -> None:
    findings = _lint(tmp_path, 'GlobalVariableSet("OTHER_STATE", 1.0);\n')
    assert any("fuera del namespace GTX_" in message for _, message in findings)


def test_accepts_supported_patterns(tmp_path: Path) -> None:
    source = """
int atr = iATR(_Symbol, PERIOD_M15, 14);
double sl = ask - 10.0;
double tp = ask + 15.0;
trade.PositionOpen(_Symbol, ORDER_TYPE_BUY, 0.10, ask, sl, tp, "GTX");
GlobalVariableSet("GTX_TEST_STATE", 1.0);
"""
    assert _lint(tmp_path, source) == []
