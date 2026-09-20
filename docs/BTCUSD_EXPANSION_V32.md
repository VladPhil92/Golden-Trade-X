# Golden Trade X v3.2 — BTCUSD Expansion

## Scope

This phase adds **research/DEMO support** for BTCUSD without changing the validated behavior of the
existing GOLD/XAU baseline.

BTCUSD is a separate hypothesis. It must earn its own Strategy Tester, rolling IS → frozen OOS,
robustness and forward-DEMO evidence before any production decision.

## 1. MT5 IPC bootstrap hardening

Fresh GitHub-hosted Windows runners can return MetaTrader5 error `-10005 IPC timeout` when the
Python API attempts to initialize a newly installed terminal before its IPC channel is ready.

`scripts/mt5_connection.py` now:

1. starts the terminal explicitly;
2. waits for bootstrap;
3. initializes IPC without embedding account credentials in the initialize call;
4. performs account authentication with `mt5.login()`;
5. retries boundedly on startup/IPC failure;
6. fails closed after the configured attempts; and
7. cleans up the bootstrap process.

The helper is used by both environment discovery and official runtime attestation.

Credentials remain GitHub secrets and are never written to evidence artifacts.

## 2. BTCUSD spread normalization

The legacy GOLD preset uses an absolute spread limit in broker points. That metric is not portable
to BTCUSD because point size and nominal price differ materially.

Golden Trade X now supports:

```text
InpMaxSpreadPoints
InpMaxSpreadBps
```

`InpMaxSpreadBps=0` preserves the historical behavior.

When `InpMaxSpreadBps > 0`, the risk guard computes:

```text
spread_bps = (ask - bid) / ((ask + bid) / 2) * 10,000
```

and rejects entries above the configured threshold.

The GOLD/XAG presets explicitly keep `InpMaxSpreadBps=0.0`, so this phase does not silently alter
their execution behavior.

## 3. Experimental BTCUSD M15 preset

Research preset:

```text
config/research/GoldenTradeX_BTCUSD_M15.experimental.set
```

Important properties:

- `InpAllowRealTrading=false`;
- separate magic number;
- M15 baseline signal hypothesis;
- 0.5% research risk;
- absolute spread-points cap disabled;
- 10 bps spread candidate guard;
- weekday/session filter disabled because crypto availability is broker-specific;
- Friday forced close disabled;
- portfolio cap enabled at 1.0%;
- research telemetry enabled.

The 10 bps threshold is **not claimed to be optimal**. It is only a pre-registered candidate that
must be evaluated empirically.

## 4. XM shadow universe

Research-only preset:

```text
config/research/GoldenTradeX_v32_XM_GOLD_BTC_Shadow.set
```

Universe:

```text
GOLD,BTCUSD
```

The v3.1 shadow expert never sends orders. This preset exists to compare opportunity frequency and
signal characteristics across the two XM symbols before execution integration.

## 5. Validation sequence

BTCUSD must progress independently:

```text
XM BTCUSD environment discovery
        ↓
freeze BTCUSD broker/symbol contract
        ↓
Strategy Tester candidate matrix
        ↓
rolling IS selection
        ↓
frozen OOS
        ↓
robustness
        ↓
fixed forward DEMO
        ↓
manual production review
```

Passing GOLD evidence does not promote BTCUSD automatically.

## 6. Current forward-DEMO blocker

The repository's approved economic-calendar contract does not yet cover the current 2026 forward
period. Therefore BTCUSD forward DEMO should not be treated as official forward evidence until the
calendar is extended and frozen for the observation window.

## 7. Immediate XM procedure

After this phase merges:

1. re-run **Materialize DEMO Execution Environment** for `GOLD`;
2. confirm the IPC bootstrap issue is resolved;
3. run the same workflow again with `symbol=BTCUSD`;
4. freeze the two symbol/environment contracts separately;
5. use the BTCUSD contract for BTC-specific Strategy Tester registration.

Both discovery runs remain DEMO/research-only.
