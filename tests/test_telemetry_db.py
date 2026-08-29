import csv
import hashlib
from pathlib import Path

import pytest

from telemetry_db import connect, counts, discover, ingest_files, ingest_root


SESSION_HEADERS = [
    "EventID", "ServerTime", "UtcTime", "Account", "Magic", "Symbol", "Timeframe", "Kind",
    "CandidateID", "BuildID", "Broker", "TerminalBuild", "TradeMode", "ServerUtcOffsetSeconds",
    "ConfigSnapshot",
]
SIGNAL_HEADERS = [
    "EventID", "EventTime", "BarTime", "Account", "Magic", "Symbol", "Timeframe", "Stage",
    "Decision", "Reason", "Direction", "Confidence", "Regime", "BaseScore", "RegimeScore",
    "SmcScore", "HtfScore", "FibScore", "Bid", "Ask", "SpreadPoints", "ATR", "RequestedPrice",
    "SL", "TP", "InitialRR", "Lots", "PositionID", "OrderTicket", "DealTicket",
]
EXECUTION_HEADERS = [
    "EventID", "EventTime", "Account", "Magic", "Symbol", "Action", "Status", "Direction",
    "RequestedPrice", "RequestedSL", "RequestedTP", "RequestedVolume", "ServerRetcode", "ResultClass",
    "ExecutedPrice", "ExecutedVolume", "SlippagePoints", "OrderTicket", "DealTicket", "PositionID",
    "PositionTicket", "DealEntry", "DealReason", "Profit", "Commission", "Swap", "Fee", "Comment",
]
OUTCOME_HEADERS = [
    "EventID", "CloseTime", "Account", "Magic", "Symbol", "PositionID", "Direction", "EntryTime",
    "EntryPrice", "InitialSL", "InitialTP", "InitialRiskPrice", "InitialRiskMoney", "InitialVolume",
    "Confidence", "Regime", "MFE_R", "MFE_Price", "MFE_Time", "MAE_R", "MAE_Price", "MAE_Time",
    "NetPnL", "RealizedR", "ClosePrice",
]


def _write(path: Path, headers: list[str], row: dict[str, object]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerow({key: row.get(key, "") for key in headers})


def _fixtures(root: Path) -> None:
    snapshot = "InpMagicNumber=920260|InpEmaFast=21|InpRiskPercent=1.00000000"
    _write(
        root / "GoldenTradeX_sessions_100_920260_XAUUSD_2026.csv",
        SESSION_HEADERS,
        {
            "EventID": "ses-1", "ServerTime": "2026.08.28 12:00:00", "UtcTime": "2026.08.28 10:00:00",
            "Account": 100, "Magic": 920260, "Symbol": "XAUUSD", "Timeframe": "PERIOD_M15",
            "Kind": "START", "CandidateID": "gtx-candidate-1", "BuildID": "a" * 40,
            "Broker": "TEST-BROKER", "TerminalBuild": 5100, "TradeMode": "DEMO",
            "ServerUtcOffsetSeconds": 7200, "ConfigSnapshot": snapshot,
        },
    )
    _write(
        root / "GoldenTradeX_signals_100_920260_XAUUSD_2026.csv",
        SIGNAL_HEADERS,
        {
            "EventID": "sig-1", "EventTime": "2026.08.28 12:00:00", "BarTime": "2026.08.28 12:00:00",
            "Account": 100, "Magic": 920260, "Symbol": "XAUUSD", "Timeframe": "PERIOD_M15",
            "Stage": "RR", "Decision": "ORDER_REQUESTED", "Reason": "", "Direction": "BUY",
            "Confidence": 72, "Regime": 1, "BaseScore": 25, "RegimeScore": 20, "SmcScore": 15,
            "HtfScore": 10, "FibScore": 2, "SpreadPoints": 32.5, "ATR": 4.2,
            "RequestedPrice": 2520.1, "SL": 2512.1, "TP": 2532.1, "InitialRR": 1.5,
            "Lots": 0.03, "PositionID": 0, "OrderTicket": 0, "DealTicket": 0,
        },
    )
    _write(
        root / "GoldenTradeX_executions_100_920260_XAUUSD_2026.csv",
        EXECUTION_HEADERS,
        {
            "EventID": "exe-1", "EventTime": "2026.08.28 12:00:01", "Account": 100, "Magic": 920260,
            "Symbol": "XAUUSD", "Action": "OPEN", "Status": "SERVER_CONFIRMED", "Direction": "BUY",
            "RequestedPrice": 2520.1, "RequestedSL": 2512.1, "RequestedTP": 2532.1,
            "RequestedVolume": 0.03, "ServerRetcode": 10009, "ResultClass": 0,
            "ExecutedPrice": 2520.2, "ExecutedVolume": 0.03, "SlippagePoints": 1.0,
            "OrderTicket": 2001, "DealTicket": 3001, "PositionID": 4001, "PositionTicket": 5001,
            "DealEntry": "", "DealReason": "", "Profit": "", "Commission": "", "Swap": "", "Fee": "",
            "Comment": "GoldenTradeX|Conf=72",
        },
    )
    _write(
        root / "GoldenTradeX_outcomes_100_920260_XAUUSD_2026.csv",
        OUTCOME_HEADERS,
        {
            "EventID": "out-1", "CloseTime": "2026.08.28 14:00:00", "Account": 100, "Magic": 920260,
            "Symbol": "XAUUSD", "PositionID": 4001, "Direction": "BUY",
            "EntryTime": "2026.08.28 12:00:01", "EntryPrice": 2520.2, "InitialSL": 2512.1,
            "InitialTP": 2532.1, "InitialRiskPrice": 8.1, "InitialRiskMoney": 24.3,
            "InitialVolume": 0.03, "Confidence": 72, "Regime": 1, "MFE_R": 1.8,
            "MFE_Price": 2534.78, "MFE_Time": "2026.08.28 13:10:00", "MAE_R": 0.35,
            "MAE_Price": 2517.365, "MAE_Time": "2026.08.28 12:15:00", "NetPnL": 19.44,
            "RealizedR": 0.8, "ClosePrice": 2526.68,
        },
    )


def test_ingest_root_is_idempotent_and_typed(tmp_path: Path) -> None:
    root = tmp_path / "files"
    root.mkdir()
    _fixtures(root)

    with connect(tmp_path / "research.sqlite") as conn:
        first = ingest_root(conn, root)
        second = ingest_root(conn, root)

        assert [r.rows_inserted for r in first] == [1, 1, 1, 1]
        assert [r.rows_inserted for r in second] == [0, 0, 0, 0]
        assert counts(conn) == {"sessions": 1, "signals": 1, "executions": 1, "outcomes": 1}

        session = conn.execute(
            "SELECT candidate_id, build_id, trade_mode, config_snapshot, config_sha256 "
            "FROM research_sessions WHERE event_id='ses-1'"
        ).fetchone()
        expected_snapshot = "InpMagicNumber=920260|InpEmaFast=21|InpRiskPercent=1.00000000"
        assert session == (
            "gtx-candidate-1",
            "a" * 40,
            "DEMO",
            expected_snapshot,
            hashlib.sha256(expected_snapshot.encode("utf-8")).hexdigest(),
        )

        signal = conn.execute(
            "SELECT confidence, initial_rr, lots FROM signal_events WHERE event_id='sig-1'"
        ).fetchone()
        assert signal == (72, 1.5, 0.03)

        execution = conn.execute(
            "SELECT server_retcode, slippage_points, position_id FROM execution_events WHERE event_id='exe-1'"
        ).fetchone()
        assert execution == (10009, 1.0, 4001)

        outcome = conn.execute(
            "SELECT mfe_r, mae_r, realized_r, initial_risk_money FROM research_trade_summary WHERE position_id=4001"
        ).fetchone()
        assert outcome == (1.8, 0.35, 0.8, 24.3)


def test_discover_only_matches_requested_family(tmp_path: Path) -> None:
    _fixtures(tmp_path)
    assert len(discover(tmp_path, "sessions")) == 1
    assert len(discover(tmp_path, "signals")) == 1
    assert len(discover(tmp_path, "executions")) == 1
    assert len(discover(tmp_path, "outcomes")) == 1


def test_missing_required_headers_fails_closed(tmp_path: Path) -> None:
    bad = tmp_path / "GoldenTradeX_sessions_bad.csv"
    _write(bad, ["EventID", "ServerTime"], {"EventID": "bad", "ServerTime": "now"})

    with connect(tmp_path / "research.sqlite") as conn:
        with pytest.raises(ValueError, match="missing required header"):
            ingest_files(conn, "sessions", [bad])
