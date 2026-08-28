# Contributing to Golden Trade X

Golden Trade X is safety-critical trading software. Correctness, state integrity, reproducibility and evidence take priority over feature count or apparent performance.

## Change workflow

1. Start from the latest `main` and create a focused branch.
2. Keep each pull request scoped to one coherent engineering or research objective.
3. Add or update tests for every behavior change.
4. Run the portable Python/static/config gates and the Windows MetaEditor/MQL5 verification gates.
5. Update documentation and `CHANGELOG.md` when behavior or release semantics change.
6. Do not merge while any required gate is failing or while a P0 correctness issue remains unresolved.

Direct development-to-production promotion is prohibited. Strategy changes require a documented hypothesis and reproducible IS/OOS experiment before they are eligible for demo evaluation.

## Commit prefixes

Use one of: `fix:`, `feat:`, `test:`, `ci:`, `docs:`, `refactor:`, `perf:`, `research:`.

## Pull request requirements

A code PR is complete only when implementation, tests, MQL5 compilation where applicable, CI and documentation agree. Trading/execution changes must preserve fail-closed behavior on ambiguous broker state. Do not weaken risk guards or test assertions merely to obtain a green build.

For strategy/research PRs, include:

- Hypothesis
- Mechanism
- Expected effect
- Metric
- Dataset and provenance
- IS period
- OOS period
- Decision criterion
- Result, including negative results

## Quantitative integrity

Never fabricate or extrapolate backtests, forward tests, win rate, Sharpe, Profit Factor, drawdown, Monte Carlo, PSR/DSR or ML performance. A missing dataset or unavailable broker environment must be reported as `NOT VALIDATED`.

Do not enable live ML decisions, increase production risk, or deploy real capital as part of ordinary feature development. Capital promotion is a separate gated process.

## Security

Never commit credentials, `.env` files, API tokens, private keys, broker passwords, account secrets or Telegram bot tokens. Use `.env.example` only for placeholder variable names. Follow `SECURITY.md` for vulnerability reporting.
