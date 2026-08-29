# Golden Trade X v3.1 — Daily Opportunity Architecture

## Objective

Increase the probability that the system finds at least one valid intraday opportunity on an eligible trading day **without making daily activity a mandatory entry condition**.

The v3.1 research question is:

> Can Golden Trade X increase active-trading-day participation without degrading OOS expectancy, drawdown, robustness or forward-demo behavior?

A zero-trade day remains a valid outcome. No module may lower a threshold merely because no trade has occurred yet.

## Safety boundary

v3.1 is research-first and does not replace the v3.0-rc1 baseline by default. The current production/research preset remains the control candidate until v3.1 variants pass the same OOS, robustness and forward-demo gates.

`config/daily_opportunity_policy.example.json` is deliberately `approved=false` and `research_only=true`.

## Architecture

### 1. Multi-Setup Engine

Target setup families:

- **A — High Conviction**: existing high-confluence trend architecture.
- **B — Standard Intraday**: independent, separately validated intraday setup family.
- **C — Tactical**: lower-risk setup family intended to add valid opportunity diversity, not forced trades.

Each family must have its own research identity, risk ceiling and ablation evidence. A setup is not promoted merely because it increases trade count.

### 2. Multi-Symbol Scanner

The future execution scanner will evaluate an approved symbol universe and emit candidates into a common contract. Symbols are not automatically approved. Every symbol/preset combination must have independent Strategy Tester evidence and must be included in the frozen candidate universe before OOS.

### 3. Opportunity Ranker

`MQL5/Include/GoldenTradeX/OpportunityRanker.mqh` implements deterministic ranking of already-valid candidates. It does **not** create signals and does not know how many trades occurred that day.

Eligibility requires:

- valid source/setup;
- BUY/SELL direction;
- non-empty symbol;
- minimum confidence;
- minimum pre-registered quality score;
- candidate risk inside the configured ceiling.

Ranking order is deterministic:

1. quality score;
2. confidence;
3. lower proposed risk;
4. setup class;
5. symbol lexical order.

If nothing is eligible, the result is `NO_ELIGIBLE_OPPORTUNITY`.

### 4. Portfolio / Correlation Risk Governor

`PortfolioCorrelationGovernor.mqh` protects aggregate exposure. It provides:

- aggregate open-risk cap checks;
- Pearson correlation calculation for aligned samples;
- directional exposure transformation;
- blocking of strongly aligned correlated exposure.

Correlation is not assumed from symbol names. Runtime integration must use measured, sufficiently sampled price-return correlation or a separately frozen evidence source.

## Daily activity evidence

`scripts/daily_opportunity_metrics.py` reports participation independently of profitability:

- `active_trading_day_ratio`;
- `zero_trade_day_ratio`;
- mean and median trades/day;
- maximum trades in one day;
- 0 / 1 / 2 / 3+ daily distribution;
- trades by symbol;
- trades by setup;
- exact per-day counts.

The denominator is explicit. An exact broker trading-day file is preferred for official research; weekday inference is only a fallback for exploratory analysis.

Activity metrics are **not edge metrics**. A candidate can improve participation and still be rejected for negative expectancy or excessive drawdown.

## Anti-overtrading invariants

The following behaviors are forbidden:

- `minimum_trades_per_day` forcing an entry;
- lowering confidence after a zero-trade day;
- disabling news/session/risk guards to meet an activity target;
- changing setup thresholds after seeing OOS activity/performance;
- adding a symbol after partial OOS observation;
- treating correlated symbols as independent portfolio risk.

## Research progression

```text
v3.0 baseline
   ↓
A/B/C setup candidates + symbol candidates
   ↓
activity report + economic metrics
   ↓
IS-only selection
   ↓
frozen OOS
   ↓
compare participation AND expectancy/DD
   ↓
robustness
   ↓
forward DEMO
   ↓
commercial preset review
```

The commercial objective may be an 80%+ active-day ratio and roughly 1–3 trades/day, but those values are research targets, not promises and not promotion criteria by themselves.

## Current phase boundary

This first v3.1 increment provides the candidate contract, deterministic ranker, correlation/risk governor, activity metrics and automated tests. It does not yet route live EA execution through multiple symbols or setup families. Runtime scanning is the next v3.1 increment after these contracts compile and pass MetaTrader tests.

No v3.1 artifact authorizes live trading or real capital.
