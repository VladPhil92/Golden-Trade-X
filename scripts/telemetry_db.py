#!/usr/bin/env python3
"""Golden Trade X v2.70 — idempotent research telemetry importer.

Ingests append-only CSV ledgers emitted by ``ResearchTelemetry.mqh`` into a
local SQLite research database. The importer is deliberately offline and does
not place, modify, or close trades.

Usage::

    python scripts/telemetry_db.py --db data/gtx_research.sqlite --root /path/to/Common/Files

The command can be run repeatedly: rows are deduplicated by a stable hash of
ledger family + canonical row contents. No trading statistics are fabricated;
missing fields remain NULL/empty and malformed source files fail fast.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

LEDGER_PATTERNS = {
    "signals": "GoldenTradeX_signals_*.csv",
    "executions": "GoldenTradeX_executions_*.csv",
    "outcomes": "GoldenTradeX_outcomes_*.csv",
}

REQUIRED_HEADERS = {
    "signals": {"EventID", "EventTime", "BarTime", "Symbol", "Stage", "Decision", "Direction"},
    "executions": {"EventID", "EventTime", "Symbol", "Action", "Status", "DealTicket", "PositionID"},
    "outcomes": {"EventID", "CloseTime", "Symbol", "PositionID", "InitialRiskMoney", "MFE_R", "MAE_R", "RealizedR"},
}

SCHEMA = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS signal_events (
    row_hash TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    event_time TEXT,
    bar_time TEXT,
    account INTEGER,
    magic INTEGER,
    symbol TEXT,
    timeframe TEXT,
    stage TEXT,
    decision TEXT,
    reason TEXT,
    direction TEXT,
    confidence INTEGER,
    regime INTEGER,
    base_score INTEGER,
    regime_score INTEGER,
    smc_score INTEGER,
    htf_score INTEGER,
    fib_score INTEGER,
    spread_points REAL,
    atr REAL,
    requested_price REAL,
    sl REAL,
    tp REAL,
    initial_rr REAL,
    lots REAL,
    position_id INTEGER,
    order_ticket INTEGER,
    deal_ticket INTEGER,
    source_file TEXT NOT NULL,
    raw_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS execution_events (
    row_hash TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    event_time TEXT,
    account INTEGER,
    magic INTEGER,
    symbol TEXT,
    action TEXT,
    status TEXT,
    direction TEXT,
    requested_price REAL,
    requested_sl REAL,
    requested_tp REAL,
    requested_volume REAL,
    server_retcode INTEGER,
    result_class INTEGER,
    executed_price REAL,
    executed_volume REAL,
    slippage_points REAL,
    order_ticket INTEGER,
    deal_ticket INTEGER,
    position_id INTEGER,
    position_ticket INTEGER,
    deal_entry INTEGER,
    deal_reason INTEGER,
    profit REAL,
    commission REAL,
    swap REAL,
    fee REAL,
    comment TEXT,
    source_file TEXT NOT NULL,
    raw_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS position_outcomes (
    row_hash TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    close_time TEXT,
    account INTEGER,
    magic INTEGER,
    symbol TEXT,
    position_id INTEGER,
    direction TEXT,
    entry_time TEXT,
    entry_price REAL,
    initial_sl REAL,
    initial_tp REAL,
    initial_risk_price REAL,
    initial_risk_money REAL,
    initial_volume REAL,
    confidence INTEGER,
    regime INTEGER,
    mfe_r REAL,
    mfe_price REAL,
    mfe_time TEXT,
    mae_r REAL,
    mae_price REAL,
    mae_time TEXT,
    net_pnl REAL,
    realized_r REAL,
    close_price REAL,
    source_file TEXT NOT NULL,
    raw_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_signal_symbol_time ON signal_events(symbol, event_time);
CREATE INDEX IF NOT EXISTS idx_signal_stage_decision ON signal_events(stage, decision);
CREATE INDEX IF NOT EXISTS idx_execution_position ON execution_events(position_id, event_time);
CREATE INDEX IF NOT EXISTS idx_execution_deal ON execution_events(deal_ticket);
CREATE INDEX IF NOT EXISTS idx_outcome_symbol_time ON position_outcomes(symbol, close_time);
CREATE INDEX IF NOT EXISTS idx_outcome_position ON position_outcomes(position_id);

CREATE VIEW IF NOT EXISTS research_trade_summary AS
SELECT
    position_id,
    symbol,
    direction,
    entry_time,
    close_time,
    initial_risk_money,
    confidence,
    regime,
    mfe_r,
    mae_r,
    net_pnl,
    realized_r
FROM position_outcomes;
"""


@dataclass(frozen=True)
class IngestResult:
    family: str
    files: int
    rows_seen: int
    rows_inserted: int


def _int(value: str | None) -> int | None:
    if value is None or value.strip() == "":
        return None
    return int(float(value))


def _float(value: str | None) -> float | None:
    if value is None or value.strip() == "":
        return None
    return float(value)


def _text(row: Mapping[str, str], key: str) -> str | None:
    value = row.get(key, "").strip()
    return value or None


def _canonical_hash(family: str, row: Mapping[str, str]) -> str:
    payload = json.dumps(dict(sorted(row.items())), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(f"{family}\n{payload}".encode("utf-8")).hexdigest()


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    return conn


def discover(root: Path, family: str) -> list[Path]:
    if family not in LEDGER_PATTERNS:
        raise ValueError(f"unknown telemetry family: {family}")
    return sorted(p for p in root.glob(LEDGER_PATTERNS[family]) if p.is_file())


def _read_rows(path: Path, family: str) -> Iterable[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = set(reader.fieldnames or [])
        missing = REQUIRED_HEADERS[family] - headers
        if missing:
            raise ValueError(f"{path}: missing required header(s): {', '.join(sorted(missing))}")
        for line_no, row in enumerate(reader, start=2):
            if None in row:
                raise ValueError(f"{path}:{line_no}: row has more fields than header")
            if not any((value or "").strip() for value in row.values()):
                continue
            yield {key: (value or "").strip() for key, value in row.items()}


def _signal_values(row: Mapping[str, str], source: str) -> tuple:
    return (
        _canonical_hash("signals", row), row["EventID"], _text(row, "EventTime"), _text(row, "BarTime"),
        _int(row.get("Account")), _int(row.get("Magic")), _text(row, "Symbol"), _text(row, "Timeframe"),
        _text(row, "Stage"), _text(row, "Decision"), _text(row, "Reason"), _text(row, "Direction"),
        _int(row.get("Confidence")), _int(row.get("Regime")), _int(row.get("BaseScore")),
        _int(row.get("RegimeScore")), _int(row.get("SmcScore")), _int(row.get("HtfScore")),
        _int(row.get("FibScore")), _float(row.get("SpreadPoints")), _float(row.get("ATR")),
        _float(row.get("RequestedPrice")), _float(row.get("SL")), _float(row.get("TP")),
        _float(row.get("InitialRR")), _float(row.get("Lots")), _int(row.get("PositionID")),
        _int(row.get("OrderTicket")), _int(row.get("DealTicket")), source,
        json.dumps(row, ensure_ascii=False, sort_keys=True),
    )


def _execution_values(row: Mapping[str, str], source: str) -> tuple:
    return (
        _canonical_hash("executions", row), row["EventID"], _text(row, "EventTime"),
        _int(row.get("Account")), _int(row.get("Magic")), _text(row, "Symbol"), _text(row, "Action"),
        _text(row, "Status"), _text(row, "Direction"), _float(row.get("RequestedPrice")),
        _float(row.get("RequestedSL")), _float(row.get("RequestedTP")), _float(row.get("RequestedVolume")),
        _int(row.get("ServerRetcode")), _int(row.get("ResultClass")), _float(row.get("ExecutedPrice")),
        _float(row.get("ExecutedVolume")), _float(row.get("SlippagePoints")), _int(row.get("OrderTicket")),
        _int(row.get("DealTicket")), _int(row.get("PositionID")), _int(row.get("PositionTicket")),
        _int(row.get("DealEntry")), _int(row.get("DealReason")), _float(row.get("Profit")),
        _float(row.get("Commission")), _float(row.get("Swap")), _float(row.get("Fee")), _text(row, "Comment"),
        source, json.dumps(row, ensure_ascii=False, sort_keys=True),
    )


def _outcome_values(row: Mapping[str, str], source: str) -> tuple:
    return (
        _canonical_hash("outcomes", row), row["EventID"], _text(row, "CloseTime"),
        _int(row.get("Account")), _int(row.get("Magic")), _text(row, "Symbol"), _int(row.get("PositionID")),
        _text(row, "Direction"), _text(row, "EntryTime"), _float(row.get("EntryPrice")),
        _float(row.get("InitialSL")), _float(row.get("InitialTP")), _float(row.get("InitialRiskPrice")),
        _float(row.get("InitialRiskMoney")), _float(row.get("InitialVolume")), _int(row.get("Confidence")),
        _int(row.get("Regime")), _float(row.get("MFE_R")), _float(row.get("MFE_Price")),
        _text(row, "MFE_Time"), _float(row.get("MAE_R")), _float(row.get("MAE_Price")),
        _text(row, "MAE_Time"), _float(row.get("NetPnL")), _float(row.get("RealizedR")),
        _float(row.get("ClosePrice")), source, json.dumps(row, ensure_ascii=False, sort_keys=True),
    )


INSERTS = {
    "signals": (
        "signal_events",
        """INSERT OR IGNORE INTO signal_events VALUES (
            ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
        )""",
        _signal_values,
    ),
    "executions": (
        "execution_events",
        """INSERT OR IGNORE INTO execution_events VALUES (
            ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
        )""",
        _execution_values,
    ),
    "outcomes": (
        "position_outcomes",
        """INSERT OR IGNORE INTO position_outcomes VALUES (
            ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
        )""",
        _outcome_values,
    ),
}


def ingest_files(conn: sqlite3.Connection, family: str, paths: Sequence[Path]) -> IngestResult:
    if family not in INSERTS:
        raise ValueError(f"unknown telemetry family: {family}")
    _, sql, converter = INSERTS[family]
    seen = 0
    inserted = 0
    with conn:
        for path in paths:
            for row in _read_rows(path, family):
                seen += 1
                before = conn.total_changes
                conn.execute(sql, converter(row, path.name))
                inserted += conn.total_changes - before
    return IngestResult(family=family, files=len(paths), rows_seen=seen, rows_inserted=inserted)


def ingest_root(conn: sqlite3.Connection, root: Path) -> list[IngestResult]:
    return [ingest_files(conn, family, discover(root, family)) for family in LEDGER_PATTERNS]


def counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        "signals": conn.execute("SELECT COUNT(*) FROM signal_events").fetchone()[0],
        "executions": conn.execute("SELECT COUNT(*) FROM execution_events").fetchone()[0],
        "outcomes": conn.execute("SELECT COUNT(*) FROM position_outcomes").fetchone()[0],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Golden Trade X research telemetry → SQLite")
    parser.add_argument("--db", type=Path, default=Path("data/gtx_research.sqlite"))
    parser.add_argument("--root", type=Path, required=True, help="MT5 Common/Files directory containing GTX ledgers")
    args = parser.parse_args()

    if not args.root.exists() or not args.root.is_dir():
        parser.error(f"--root is not a directory: {args.root}")

    with connect(args.db) as conn:
        results = ingest_root(conn, args.root)
        for result in results:
            print(
                f"{result.family}: files={result.files} rows={result.rows_seen} "
                f"inserted={result.rows_inserted}"
            )
        print("database counts:", json.dumps(counts(conn), sort_keys=True))


if __name__ == "__main__":
    main()
