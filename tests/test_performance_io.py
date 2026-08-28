"""I/O and orchestration tests for performance_report."""

from __future__ import annotations

import sys
import types
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from performance_report import (  # noqa: E402
    discover_csvs,
    evaluate,
    load_trades,
    open_hour,
    open_weekday,
    run_once,
)


def _args(json_path: str = "") -> types.SimpleNamespace:
    return types.SimpleNamespace(
        window=5,
        wr_drop=15.0,
        pf_alert=1.0,
        dd_alert=0.01,
        consec_alert=3,
        json=json_path,
    )


def _csv(path: Path, rows: list[str]) -> None:
    header = (
        "CloseDate,CloseTime,PositionID,Symbol,Type,Lots,OpenPrice,InitialSL,InitialTP,"
        "ClosePrice,ProfitLoss,Commission,RMultiple,Comment,OpenDate,OpenTime\n"
    )
    path.write_text(header + "".join(rows), encoding="utf-8")


def test_load_trades_preserves_signal_metadata_and_skips_bad_rows(tmp_path: Path) -> None:
    path = tmp_path / "GoldenTradeX_test.csv"
    _csv(
        path,
        [
            "2026-01-01,12:00:00,1,XAUUSD,BUY,0.1,2000,1990,2020,2010,10,-1,1.0,GTX|Conf=70|Reg=TRENDING_BULL,2026-01-01,09:15:00\n",
            "2026-01-02,12:00:00,2,XAUUSD,BUY,bad,2000,1990,2020,2010,10,-1,1.0,GTX,2026-01-02,09:15:00\n",
        ],
    )

    rows = load_trades(str(path))

    assert len(rows) == 1
    assert rows[0]["comment"].startswith("GTX|Conf=70")
    assert rows[0]["open_time"] == "09:15:00"


def test_open_time_and_weekday_use_fallbacks_and_invalid_values(tmp_path: Path) -> None:
    path = tmp_path / "GoldenTradeX_test.csv"
    _csv(
        path,
        [
            "2026-01-05,12:00:00,1,XAUUSD,BUY,0.1,2000,1990,2020,2010,10,-1,1.0,GTX,,,\n",
        ],
    )
    row = load_trades(str(path))[0]
    assert open_hour(row) == 12
    assert open_weekday(row) == 0

    row["open_time"] = "bad"
    row["open_date"] = "bad"
    assert open_hour(row) is None
    assert open_weekday(row) is None


def test_discover_csvs_finds_nested_trade_logs(tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    first = tmp_path / "GoldenTradeX_A.csv"
    second = nested / "GoldenTradeX_B.csv"
    first.write_text("", encoding="utf-8")
    second.write_text("", encoding="utf-8")

    found = discover_csvs(str(tmp_path))

    assert str(first) in found
    assert str(second) in found


def test_run_once_writes_json_and_returns_alert_exit_code(tmp_path: Path) -> None:
    path = tmp_path / "GoldenTradeX_test.csv"
    json_path = tmp_path / "report.json"
    rows = []
    for i in range(6):
        pnl = -20 if i >= 3 else 10
        rows.append(
            f"2026-01-{i+1:02d},12:00:00,{i},XAUUSD,BUY,0.1,2000,1990,2020,2010,{pnl},0,{-1 if pnl < 0 else 1},GTX|Conf=60|Reg=RANGING,2026-01-{i+1:02d},09:00:00\n"
        )
    _csv(path, rows)

    code = run_once([str(path)], _args(str(json_path)))

    assert code == 1
    assert json_path.is_file()
    assert '"alerts"' in json_path.read_text(encoding="utf-8")


def test_run_once_with_no_valid_trades_is_nonfatal(tmp_path: Path) -> None:
    path = tmp_path / "GoldenTradeX_empty.csv"
    _csv(path, ["bad,row\n"])
    assert run_once([str(path)], _args()) == 0


def test_evaluate_emits_pf_drawdown_and_loss_streak_alerts(tmp_path: Path) -> None:
    path = tmp_path / "GoldenTradeX_test.csv"
    rows = []
    for i, pnl in enumerate([100, -150, -150, -150, -150, -150]):
        rows.append(
            f"2026-02-{i+1:02d},12:00:00,{i},XAUUSD,BUY,0.1,2000,1990,2020,2010,{pnl},0,{-1 if pnl < 0 else 1},GTX|Conf=55|Reg=RANGING,2026-02-{i+1:02d},09:00:00\n"
        )
    _csv(path, rows)
    loaded = load_trades(str(path))
    res = evaluate(loaded, 5, _args())

    assert any("PF reciente" in alert for alert in res["alerts"])
    assert any("DRAWDOWN" in alert for alert in res["alerts"])
    assert any("RACHA ABIERTA" in alert for alert in res["alerts"])
