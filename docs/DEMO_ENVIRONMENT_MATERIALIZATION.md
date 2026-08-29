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

The discovery artifact never contains the account login or password. Approval remains a separate,
explicit transition. Discovery does not authorize live trading or real capital.

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

Even an approved execution environment remains research-only: `live_trading_authorized=false` is
mandatory throughout the official validation pipeline.
