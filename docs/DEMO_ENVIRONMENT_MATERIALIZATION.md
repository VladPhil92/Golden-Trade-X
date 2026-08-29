# DEMO Execution Environment Materialization

The official validation campaign must not infer broker/server/build metadata from templates.
A real connected MetaTrader 5 **DEMO** account is observed first, then a review candidate is
materialized, reviewed, and only later promoted into an immutable approved execution-environment
contract.

## Boundary

`Materialize DEMO Execution Environment` is a manual Windows workflow. It:

1. installs/compiles the current MT5 build using the repository compile gate;
2. installs the exact pinned `MetaTrader5==5.0.6147` Python client;
3. connects using `GTX_MT5_LOGIN`, `GTX_MT5_PASSWORD`, and `GTX_MT5_SERVER` GitHub secrets;
4. refuses REAL/CONTEST/unknown trade modes;
5. observes broker company/server, terminal build, account currency/leverage, and XAUUSD contract metadata;
6. emits `execution_environment.candidate.json` with `approved=false`;
7. emits a credential-free discovery audit; and
8. uploads both files for review without changing repository configuration.

The discovery artifact never contains the account login or password. Discovery does not authorize
live trading or real capital.

## Required GitHub secrets

- `GTX_MT5_LOGIN`
- `GTX_MT5_PASSWORD`
- `GTX_MT5_SERVER`

The account represented by these secrets must be a MetaTrader 5 DEMO account. The workflow fails
closed if the observed account is not DEMO or the observed server differs from `GTX_MT5_SERVER`.

## Review output

The candidate records the observed broker company/server, symbol, timeframe, exact terminal build,
currency, leverage and deterministic environment identity. Reviewers must verify these values before
creating a frozen approved environment contract.

The review candidate and its matching discovery audit should be placed on a review branch under
`data/research/environment-review/`. They remain `approved=false` while under review.

## Explicit approval freeze

After the candidate has been reviewed, `Freeze DEMO Execution Environment Approval` performs the
second transition. It requires the literal confirmation
`APPROVE_DEMO_EXECUTION_ENVIRONMENT` plus a human approval note. The freeze command verifies:

- the candidate still validates as an unapproved DEMO-only execution environment;
- the discovery audit carries `MT5_EXECUTION_ENVIRONMENT_DISCOVERY_V1` and remains unapproved;
- the audit's candidate canonical SHA-256 matches the reviewed candidate;
- broker company, server, symbol and terminal build match the observed values;
- the terminal was connected and the symbol synchronized during discovery; and
- the would-be approved contract contains no placeholder broker/build identity.

Only after those checks does the workflow emit:

- `execution_environment.approved.json`; and
- `execution_environment.approval.json`.

The workflow has `contents: read`; it uploads the freeze as an immutable review artifact and does not
edit repository configuration automatically. A separate reviewed PR must install the exact approved
artifact into canonical `config/` and update `official_validation_campaign.json`.

Even an approved execution environment remains research-only: `live_trading_authorized=false` and
`real_capital_authorized=false` are mandatory throughout the official validation pipeline.
