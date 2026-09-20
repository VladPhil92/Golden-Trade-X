# Golden Trade X v3.4 — XM Single-Broker Robustness

## Scope

This phase allows official validation to proceed using **XM Global only** while preserving the original multi-broker methodology for future portability studies.

The XM path is explicit:

```text
validation_scope = TARGET_BROKER_SINGLE
```

It validates whether Golden Trade X remains stable under adverse conditions **inside the approved XM Global DEMO environment**. It does not claim that the strategy is portable to other brokers.

## What remains unchanged

- DEMO-only execution;
- live trading remains unauthorized;
- real capital remains unauthorized;
- Strategy Tester evidence remains required;
- rolling IS → frozen OOS remains required;
- robustness remains a prerequisite for forward DEMO;
- forward DEMO remains a prerequisite for manual release review.

## XM canonical environments

Approved contracts:

- `execution_environment.xm_gold.v1.json`
- `execution_environment.xm_btcusd.v1.json`

Both are tied to:

```text
broker: XM Global Limited
server: XMGlobal-MT5 2
trade mode: DEMO
```

## Robustness scope

The XM-specific template uses:

```text
minimum_distinct_brokers = 1
required_labels = ["XM Global Limited"]
```

This exception is valid only when:

1. the campaign declares `TARGET_BROKER_SINGLE`;
2. the robustness template declares the same scope;
3. the single broker label matches the approved execution environment;
4. the XM-specific frozen robustness policy is used.

The default `MULTI_BROKER` path still requires at least two distinct brokers.

## XM robustness policy

The XM-only policy increases emphasis on within-broker stability:

- positive baseline net profit;
- at least 75% of parameter perturbations with positive net profit;
- at least 75% with positive expectancy;
- minimum perturbed profit factor >= 1.0;
- minimum net-profit retention >= 50%;
- the single XM broker run must remain positive;
- worst modeled cost scenario must remain profitable.

## Evidence classification

The standard multi-broker domain remains:

```text
EXTERNAL_BROKER_REPLICATION
```

The XM-only domain is explicitly classified as:

```text
TARGET_BROKER_STABILITY
```

This prevents XM-only evidence from being mislabeled as cross-broker validation.

## Campaigns

Two campaign definitions are provided:

- `official_validation_campaign.xm_gold.json`
- `official_validation_campaign.xm_btcusd.json`

GOLD compares legacy and adaptive candidates.

BTCUSD currently validates the adaptive research candidate independently.

## Safety boundary

Every XM-only campaign still retains:

```text
live_trading_authorized=false
real_capital_authorized=false
```

A robustness pass authorizes only forward-DEMO review.
