from pathlib import Path

import pytest

from scripts.strategy_tester_results import (
    StrategyTesterResultError,
    parse_strategy_tester_report,
    write_normalized_results,
)


REPORT_HTML = """
<html><body><table>
<tr><td>Initial Deposit:</td><td>10 000.00</td><td>History Quality:</td><td>100%</td></tr>
<tr><td>Total Net Profit:</td><td>1 250.50</td><td>Gross Profit:</td><td>3 000.75</td></tr>
<tr><td>Gross Loss:</td><td>-1 750.25</td><td>Profit Factor:</td><td>1.71</td></tr>
<tr><td>Expected Payoff:</td><td>12.50</td><td>Recovery Factor:</td><td>2.31</td></tr>
<tr><td>Sharpe Ratio:</td><td>1.42</td><td>Equity Drawdown Relative:</td><td>542.10 (5.42%)</td></tr>
<tr><td>Total Trades:</td><td>100</td><td>Profit Trades (% of total):</td><td>57 (57.00%)</td></tr>
<tr><td>Loss Trades (% of total):</td><td>43 (43.00%)</td><td>Largest profit trade:</td><td>250.00</td></tr>
<tr><td>Largest loss trade:</td><td>-180.00</td><td>Average profit trade:</td><td>52.64</td></tr>
<tr><td>Average loss trade:</td><td>-40.70</td><td>Ticks:</td><td>1 234 567</td></tr>
</table></body></html>
"""


def test_parse_report_normalizes_required_metrics_with_provenance(tmp_path: Path) -> None:
    report = tmp_path / "report.htm"
    report.write_text(REPORT_HTML, encoding="utf-8")

    parsed = parse_strategy_tester_report(report, experiment_id="gtx-test")

    assert parsed["experiment_id"] == "gtx-test"
    assert parsed["summary"]["total_net_profit"] == pytest.approx(1250.50)
    assert parsed["summary"]["profit_factor"] == pytest.approx(1.71)
    assert parsed["summary"]["expected_payoff"] == pytest.approx(12.50)
    assert parsed["summary"]["max_drawdown_pct"] == pytest.approx(5.42)
    assert parsed["summary"]["total_trades"] == 100
    assert parsed["summary"]["win_rate"] == pytest.approx(57.0)
    assert parsed["metrics"]["max_drawdown_pct"]["derived_from"] == "equity_drawdown_relative"
    assert parsed["metrics"]["total_net_profit"]["source_label"] == "Total Net Profit"
    assert parsed["metrics"]["total_net_profit"]["raw_value"] == "1 250.50"
    assert len(parsed["source_report"]["sha256"]) == 64
    assert parsed["warnings"] == []


def test_balance_drawdown_is_fallback_when_equity_relative_missing(tmp_path: Path) -> None:
    report = tmp_path / "report.htm"
    report.write_text(
        REPORT_HTML.replace(
            "Equity Drawdown Relative:</td><td>542.10 (5.42%)",
            "Balance Drawdown Relative:</td><td>600.00 (6.00%)",
        ),
        encoding="utf-8",
    )

    parsed = parse_strategy_tester_report(report)
    assert parsed["summary"]["max_drawdown_pct"] == pytest.approx(6.0)
    assert parsed["metrics"]["max_drawdown_pct"]["derived_from"] == "balance_drawdown_relative"


def test_utf16_report_is_supported(tmp_path: Path) -> None:
    report = tmp_path / "report.htm"
    report.write_bytes(REPORT_HTML.encode("utf-16"))

    parsed = parse_strategy_tester_report(report)
    assert parsed["source_report"]["encoding"] == "utf-16"
    assert parsed["summary"]["total_trades"] == 100


def test_spanish_labels_are_normalized(tmp_path: Path) -> None:
    report = tmp_path / "report.htm"
    report.write_text(
        """
        <table>
          <tr><td>Beneficio neto total:</td><td>500,50</td></tr>
          <tr><td>Factor de beneficio:</td><td>1,25</td></tr>
          <tr><td>Beneficio esperado:</td><td>5,01</td></tr>
          <tr><td>Reducción relativa del capital:</td><td>400,00 (4,00%)</td></tr>
          <tr><td>Operaciones totales:</td><td>100</td></tr>
          <tr><td>Operaciones ganadoras (% del total):</td><td>55 (55,00%)</td></tr>
        </table>
        """,
        encoding="utf-8",
    )

    parsed = parse_strategy_tester_report(report)
    assert parsed["summary"]["total_net_profit"] == pytest.approx(500.50)
    assert parsed["summary"]["profit_factor"] == pytest.approx(1.25)
    assert parsed["summary"]["max_drawdown_pct"] == pytest.approx(4.0)
    assert parsed["summary"]["win_rate"] == pytest.approx(55.0)


def test_missing_required_metric_fails_closed(tmp_path: Path) -> None:
    report = tmp_path / "report.htm"
    report.write_text(REPORT_HTML.replace("Profit Factor:</td><td>1.71", "Unknown:</td><td>1.71"), encoding="utf-8")

    with pytest.raises(StrategyTesterResultError, match="profit_factor"):
        parse_strategy_tester_report(report)


def test_write_normalized_results_persists_exact_parser_output(tmp_path: Path) -> None:
    report = tmp_path / "report.htm"
    output = tmp_path / "normalized.json"
    report.write_text(REPORT_HTML, encoding="utf-8")

    result = write_normalized_results(report, output, experiment_id="gtx-abc")

    assert output.is_file()
    assert '"experiment_id": "gtx-abc"' in output.read_text(encoding="utf-8")
    assert result["summary"]["total_trades"] == 100
