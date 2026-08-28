# Golden Trade X — CI Quality Gates

This document defines what automated checks prove — and what they do **not** prove.

## Linux CI

The primary workflow currently contains nine jobs:

1. **Dependency integrity** — clean Python 3.12 install from `requirements.txt`, `pip check`, bytecode compilation and environment smoke tests.
2. **Python lint (Ruff)** — pinned high-signal static checks.
3. **MQL5 static analysis** — project-specific guards for known API/safety mistakes.
4. **Config validation** — required inputs, numeric/boolean ranges, relational invariants, Confluence weights and unique magic numbers.
5. **Repository structure** — mandatory code, test, config and documentation assets.
6. **Version consistency** — EA `#property version` must equal the newest CHANGELOG version.
7. **Python tests + coverage** — regression/unit tests with >=80% coverage on the currently gated statistical modules.
8. **ML compatibility** — real XGBoost/scikit-learn train → predict → save → load → predict smoke test.
9. **Dashboard validation** — static dashboard dependency guard.

A green Linux workflow proves only those contracts.

## Windows MetaEditor build gate

`.github/workflows/mql5-windows.yml` runs on `windows-latest` and:

1. downloads the official MetaTrader 5 installer;
2. initializes the MetaQuotes MQL5 data tree;
3. stages Golden Trade X source/includes beside the standard MQL5 library;
4. invokes MetaEditor command-line compilation;
5. requires an explicit `0 errors` result in the compile log;
6. requires a generated `.ex5`;
7. computes SHA-256;
8. uploads `.ex5` and compile log as workflow evidence.

This gate replaced the former documentation statement that CI could not compile MQL5.

## Platform boundary

The `MetaTrader5` Python wheel remains Windows-specific. Linux dependency CI skips it through the platform marker in `requirements.txt` while still resolving the portable research/analytics environment.

## Verification hierarchy

Do not conflate these levels:

```text
L0 Static analysis
L1 Compilation
L2 Unit tests
L3 Integration tests
L4 Strategy Tester historical test
L5 OOS / walk-forward validation
L6 Forward demo validation
```

Current state after v2.62 work:

- L0: automated;
- L1 EA compilation: automated;
- Python L2: automated;
- MQL5 test **source files exist but runtime execution is not yet fully automated**;
- Strategy Tester automation: pending;
- OOS/forward evidence: NOT VALIDATED.

## Next gate — v2.63

The next milestone must extend Windows verification to:

- compile every MQL5 test script;
- preserve each compile log;
- fail if any script has errors;
- create an execution harness for deterministic MQL5 unit/integration tests;
- keep Strategy Tester smoke testing as a separate gate from unit tests.

Target test domains:

- RiskManager;
- OrderManager retcodes/retries;
- PositionState restart/identity;
- Partial TP Initial R;
- News DST/midnight/coverage;
- Session boundaries;
- Market Regime/Fibonacci existing contracts.

## Merge policy

A PR is not integration-eligible when a required gate is red. Never suppress a failing test solely to obtain green status. If a new test reveals a real defect, fix the defect or document a justified scope limitation.

## What CI never proves

Even when every workflow is green, CI does **not** prove:

- profitable edge;
- adequate sample size;
- OOS robustness;
- broker robustness;
- realistic execution quality;
- future profitability.

Those require experiment manifests, Strategy Tester evidence, walk-forward, stress testing and forward validation.
