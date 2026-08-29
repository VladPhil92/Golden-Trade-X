# Golden Trade X v3.1 — A-Only Multi-Symbol Shadow Observation

## Purpose

This phase measures whether symbol diversification can increase daily opportunity participation **before** changing the trading path.

`GoldenTradeXOpportunityShadow.mq5` is a research-only Expert Advisor. It contains no `CTrade`, `OrderSend`, `OpenPosition` or other order-execution path. It evaluates the existing Setup A logic across a small explicit symbol universe and records the best eligible candidate per timeframe bucket.

The production/baseline `GoldenTradeX.mq5` remains unchanged.

## Default research universe

The tracked research preset uses:

- XAUUSD
- XAGUSD
- EURUSD
- M15
- existing Setup A parameters
- confidence threshold 55
- hypothetical candidate risk 1.0% used only as ranking metadata

These symbols are a research universe, not validated commercial instruments. They may not be promoted without the normal frozen IS/OOS process.

## Deterministic flow

```text
M15 bucket
   ↓
Setup A evaluation per symbol
   ↓
base signal + regime + SMC + Fibonacci + confidence
   ↓
source-valid candidates
   ↓
OpportunityRanker
   ↓
0 candidates -> explicit NO_OPPORTUNITY
1+ candidates -> exactly one Selected=1
   ↓
append-only Common Files opportunity ledger
```

No trade-count state enters signal generation or ranking.

## Ledger

The shadow Expert writes:

`GoldenTradeX_opportunities_<magic>_<year>.csv`

under MetaTrader Common Files. Each row includes scanned symbol, setup class, selection flag, direction, confidence, quality score, proposed risk metadata, regime/components, ATR, source-validity and reason.

All scanned alternatives are retained for audit. Activity metrics count only rows where:

- `Selected=1`
- `SourceValid=1`

A selected invalid row causes analysis to fail closed.

## Activity report

Example:

```bash
python scripts/daily_opportunity_metrics.py \
  --shadow-ledger GoldenTradeX_opportunities_931100_2026.csv \
  --start-date 2026-09-01 \
  --end-date 2026-10-01 \
  --output evidence/v31_shadow_activity.json
```

For official research, provide an exact broker trading-day denominator with `--trading-days-file` instead of relying on weekday inference.

The key comparison is:

```text
baseline active_trading_day_ratio
vs
A-only multi-symbol shadow active_trading_day_ratio
```

along with zero-trade ratio and trades/day distribution.

## Promotion boundary

An increase in shadow participation is not sufficient for promotion. The next stages require:

1. Strategy Tester evidence for each symbol candidate;
2. frozen candidate universe;
3. IS-only selection;
4. independent OOS expectancy/drawdown comparison;
5. correlation/portfolio stress;
6. robustness validation;
7. forward DEMO validation.

The research target of high daily participation is not a guarantee of daily trading. A day with no eligible candidate remains a valid outcome.

## Setup B/C boundary

This phase deliberately does **not** implement Setup B or Setup C. First we isolate the frequency benefit attributable to symbol diversification while keeping the signal architecture constant. New setup families will require separate definitions, tests, ablations and OOS evidence rather than being introduced merely to create more trades.
