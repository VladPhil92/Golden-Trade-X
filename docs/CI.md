# Golden Trade X — CI Quality Gates

This document defines what automated checks prove — and what they do **not** prove.

## Linux CI

The primary workflow contains ten blocking jobs:

1. **Dependency integrity** — clean Python 3.12 install from `requirements.txt`, `pip check`, bytecode compilation and environment smoke tests.
2. **Tracked secret scan** — scans files tracked by Git for `.env`, private keys and high-risk GitHub/AWS/Telegram credential patterns; includes scanner regression tests.
3. **Python lint (Ruff)** — pinned high-signal static checks.
4. **MQL5 static analysis** — project-specific guards for known API/safety mistakes.
5. **Config validation** — required inputs, numeric/boolean ranges, relational invariants, Confluence weights and unique magic numbers.
6. **Repository structure** — mandatory code, test, config, governance and documentation assets.
7. **Version consistency** — EA `#property version` must equal the newest CHANGELOG version.
8. **Python tests + coverage** — regression/unit tests with >=80% coverage on the currently gated statistical modules.
9. **ML compatibility** — real XGBoost/scikit-learn train → predict → save → load → predict smoke test.
10. **Dashboard validation** — static dashboard dependency guard.

All workflows use explicit least-privilege permissions. A green Linux workflow proves only those contracts.

## Windows MetaTrader / MetaEditor verification

`.github/workflows/mql5-windows.yml` runs on `windows-latest` and performs two distinct gates.

### EA compilation

1. downloads the official MetaTrader 5 installer;
2. initializes the MetaQuotes MQL5 data tree;
3. stages Golden Trade X source/includes beside the standard MQL5 library;
4. invokes MetaEditor command-line compilation;
5. requires an explicit `0 errors` result;
6. requires a generated `.ex5`;
7. computes SHA-256;
8. uploads `.ex5` and compile log as evidence.

### Automated MQL5 verification

`.github/scripts/verify-mql5-tests.ps1` then:

1. stages every `MQL5/Scripts/Tests/Test*.mq5` script into the initialized terminal tree;
2. compiles **every test script** with MetaEditor and requires explicit `0 errors` plus an EX5 artifact;
3. launches each compiled script through MetaTrader's `[StartUp] Script=...` configuration interface;
4. disables live trading and DLL imports in the test configuration;
5. waits for a machine-readable `PASS/FAIL` summary in terminal/MQL5 journals;
6. fails closed on compile error, timeout, missing summary, zero tests or any failed assertion;
7. preserves compile logs, runtime journals and EX5 files as workflow artifacts.

A passing Windows workflow therefore proves both MQL5 compilation and execution of the deterministic MQL5 test harness. It does **not** constitute a Strategy Tester/backtest result.

## Security workflow

`.github/workflows/security.yml` adds:

- **CodeQL (Python)** as a blocking static security-analysis gate;
- **Dependency Review capability detection**. When GitHub Dependency Graph is enabled, dependency review becomes blocking at severity `moderate` or higher. When Dependency Graph is disabled/unavailable, the workflow records `DEPENDENCY_REVIEW=BLOCKED_EXTERNAL` explicitly rather than pretending the review ran.

Repository governance additionally includes `.github/CODEOWNERS`, `CONTRIBUTING.md` and `SECURITY.md`.

## Platform boundary

The `MetaTrader5` Python wheel remains Windows-specific. Linux dependency CI skips it through the platform marker in `requirements.txt` while still resolving the portable research/analytics environment.

## Verification hierarchy

Do not conflate these levels:

```text
L0 Static analysis
L1 Compilation
L2 Deterministic unit/module tests
L3 Terminal/runtime integration tests
L4 Strategy Tester historical test
L5 OOS / true walk-forward validation
L6 Forward demo validation
```

v2.63 targets L0–L3. Strategy Tester automation, OOS robustness and forward evidence remain separate later gates and must be reported `NOT VALIDATED` until real evidence exists.

## Governance / branch protection

The intended `main` policy is:

- pull request required;
- CODEOWNERS review required when applicable;
- required status checks include Linux CI, Windows MQL5 verification and Security;
- branch must be up to date before merge;
- force pushes and branch deletion disabled.

Repository-side files are present, but GitHub branch protection/ruleset state must be verified through repository settings/API. Do not describe branch protection as active unless GitHub reports it active.

## Merge policy

A PR is not integration-eligible when a required available gate is red. Never suppress a failing test solely to obtain green status. If an external GitHub capability is disabled, record it as an external blocker and preserve the strongest locally enforceable gate.

## What CI never proves

Even when every workflow is green, CI does **not** prove:

- profitable edge;
- adequate sample size;
- OOS robustness;
- broker robustness;
- realistic execution quality;
- future profitability.

Those require experiment manifests, Strategy Tester evidence, walk-forward, stress testing and forward validation.
