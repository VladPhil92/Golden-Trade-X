# Golden Trade X — CI Quality Gates

This document describes the automated checks that must remain green before code is eligible for integration.

## Linux CI gates

1. **Dependency integrity** — clean Python 3.12 install from `requirements.txt`, `pip check`, bytecode compilation and environment smoke tests.
2. **Python lint (ruff)** — pinned Ruff version with high-signal error rules.
3. **MQL5 static analysis** — conservative detection of known MQL4/API mistakes, unsafe literal zero-SL entry calls and unnamespaced terminal GlobalVariables.
4. **Config validation** — required inputs, types/ranges, relational invariants, Confluence Score weight total and unique magic numbers across XAUUSD/XAGUSD presets.
5. **Repository structure** — required source, config, test and documentation files exist.
6. **Version consistency** — EA `#property version` matches the latest CHANGELOG entry.
7. **Python tests + coverage** — unit/regression tests plus an initial 80% coverage gate on the core statistical analysis modules.
8. **ML compatibility** — real XGBoost/scikit-learn train → predict → save → load → predict smoke test using chronological synthetic trades.
9. **Dashboard validation** — static dashboard dependency check.

## Platform boundary

The `MetaTrader5` Python package and MetaEditor are Windows-specific operational dependencies. Linux CI intentionally skips the `MetaTrader5` wheel through a platform marker; this is not a substitute for terminal validation.

The next engineering gate is a Windows runner that invokes MetaEditor and treats any MQL5 compile error as a blocking CI failure. Until that runner exists and executes successfully, **MQL5 compilation remains an explicit production-readiness gap**.

## Policy

A green Linux workflow means the portable Python environment resolves, the tested analytics/ML APIs work, presets satisfy repository invariants, and the MQL5 source passes conservative static guards. It must never be described as proof that the EA compiles or that the trading strategy is profitable.
