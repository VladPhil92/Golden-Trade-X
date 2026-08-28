# Golden Trade X v2.70 — Research Telemetry Contract

## Purpose

v2.70 introduces an append-only research telemetry plane. Its purpose is to create auditable observations for later baseline, ablation, exit, walk-forward and robustness work. It does **not** change strategy parameters, increase risk, enable ML in live trading, or claim that any strategy has passed OOS/forward validation.

## Source of truth boundaries

The trading plane remains authoritative for execution and risk. Research telemetry is observational only.

```text
MT5 / EA
  ├─ PositionStateManager  -> immutable Initial R + runtime MFE/MAE
  ├─ OrderManager          -> server-confirmed execution identity
  └─ ResearchTelemetry     -> append-only CSV event ledgers
                                |
                                v
                         telemetry_db.py
                                |
                                v
                         SQLite research DB
                                |
                                v
                       telemetry_report.py
                                |
                                v
                    dashboard/research.html
```

A telemetry write failure must never be interpreted as permission to trade or as evidence that an event occurred. Missing observations stay missing.

## Ledgers

Files are written to MetaTrader `Common\Files` and partitioned by account, magic number, symbol and year.

### Signal ledger

Pattern:

```text
GoldenTradeX_signals_<account>_<magic>_<symbol>_<year>.csv
```

The schema records strategy-funnel observations such as signal stage, decision/rejection reason, direction, confidence/regime components, spread, ATR, requested geometry, initial RR, lots and later execution identifiers where available.

The EA records one terminal decision for each new-bar path it evaluates. Guard rejections are explicit (`KILL_SWITCH`, `SESSION_BLOCKED`, `SPREAD_TOO_WIDE`, drawdown/circuit-breaker limits, news, max positions, ownership, connection and volatile-regime guards). Once a base signal exists, confluence candidates and their rejection reasons, geometry/RR/sizing decisions, order requests and final server-confirmed/open-failed outcomes are recorded separately. This preserves negative observations instead of collecting only trades that survived every filter.

### Execution ledger

Pattern:

```text
GoldenTradeX_executions_<account>_<magic>_<symbol>_<year>.csv
```

The schema supports both request/result observations and immutable broker deal observations. It carries requested vs executed prices/volume, server retcode/result class, slippage, order/deal/position identities and broker costs when available.

`OrderManager` remains the execution authority. After `OpenPosition()` returns, the EA records the server result and only marks executed price/volume/slippage as confirmed when `OrderManager` itself classified the opening as server-confirmed. Separately, `OnTradeTransaction` admits immutable broker deals: entry deals must carry the EA magic; exit deals may be manual/broker-side only after position-history ownership has been proven exclusively to Golden Trade X.

### Position outcome ledger

Pattern:

```text
GoldenTradeX_outcomes_<account>_<magic>_<symbol>_<year>.csv
```

One final row per position is intended after ownership and final-close identity have been proven. The row stores immutable Initial R inputs plus MFE/MAE and realized outcome:

```text
InitialRiskMoney
MFE_R / MFE_Price / MFE_Time
MAE_R / MAE_Price / MAE_Time
NetPnL
RealizedR
```

At final closure the EA loads the still-live `PositionState` before cleanup and exports its immutable Initial R plus its accumulated MFE/MAE. `RealizedR` is calculated from the same final net P/L and immutable `InitialRiskMoney`. If final PositionState cannot be proven, the outcome row is omitted and a diagnostic is printed; MFE, MAE or R are never synthesized.

## SQLite ingestion

The importer is offline and uses Python's standard-library `sqlite3` module:

```bash
python scripts/telemetry_db.py \
  --root "/path/to/MetaQuotes/Terminal/Common/Files" \
  --db data/gtx_research.sqlite
```

Tables:

- `signal_events`
- `execution_events`
- `position_outcomes`

View:

- `research_trade_summary`

The importer is idempotent. Each canonical source row is hashed with SHA-256 and inserted with `INSERT OR IGNORE`, so re-ingesting the same ledgers does not duplicate observations.

Malformed files fail fast when required headers are absent or a row contains more fields than its header. Empty numeric fields become SQL `NULL`; they are not replaced with zero unless the source explicitly wrote zero.

## Reproducible descriptive report

The SQLite database is read in read-only mode and converted to a versioned JSON summary:

```bash
python scripts/telemetry_report.py \
  --db data/gtx_research.sqlite \
  --output data/gtx_research_report.json
```

The report contains observed row counts, signal-stage/decision counts, rejection reasons, execution status counts, confirmed-open slippage observations and descriptive final-outcome aggregates. Empty datasets remain empty/`null`; the report generator does not create placeholder trades or substitute missing values.

Open `dashboard/research.html` locally and select the generated JSON file. The dashboard is offline and does not query brokers or external services. Its evidence banner explicitly states that displayed summaries are descriptive telemetry only and are not OOS, forward-demo, profitability or statistical-significance evidence.

## Identity rules

The same identity rules used by the trading plane apply to research joins:

```text
order_ticket != deal_ticket != POSITION_IDENTIFIER != current position_ticket
```

`POSITION_IDENTIFIER` / `DEAL_POSITION_ID` is the durable position key. Event IDs identify telemetry rows only and must not replace broker identity.

## Validation status

This telemetry plane is infrastructure for future experiments. Its existence does not establish profitability, statistical significance, parameter stability, broker robustness, OOS performance or forward-demo performance.

## v2.70 exit gate

v2.70 is complete only when all of the following are integrated and verified:

- [x] append-only signal/execution/outcome ledger writer exists;
- [x] deterministic MQL5 writer smoke test exists;
- [x] idempotent SQLite schema/importer exists;
- [x] Python ingestion tests exist;
- [x] EA emits signal-funnel observations;
- [x] EA emits request/result and broker-deal execution observations;
- [x] final position outcomes export PositionState MFE/MAE and Realized R;
- [ ] dashboard/research summary consumes the database without inventing metrics;
- [x] dashboard/research summary consumes the database without inventing metrics;
- [ ] all CI/Security/MQL5 required gates pass on the integrated PR.
