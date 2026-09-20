# Golden Trade X v3.3 — Adaptive Multi-Asset Analysis

## Purpose

This phase improves the analytical layer for **GOLD/XAU** and **BTCUSD** without
silently changing the existing baseline. All new decision logic is opt-in and
research-only until it survives registered IS → frozen OOS, robustness and
forward-DEMO validation.

## Why a new layer

Absolute price scales differ radically between metals and crypto. A condition
that is meaningful in raw points for GOLD can be meaningless for BTCUSD.

The adaptive engine therefore prioritizes normalized features:

- EMA separation / ATR;
- directional EMA slope / ATR;
- RSI directional momentum;
- ADX trend strength;
- candle body efficiency;
- ATR / price in basis points;
- spread / mid-price in basis points;
- tick-volume ratio versus recent history;
- closed-bar location inside a 20-bar range;
- H4 price + EMA-slope alignment.

All market-state features are read from **closed bars**. Current spread is used
only as an execution-quality observation.

## Profiles

GTX_ANALYSIS_AUTO resolves by symbol name:

- GOLD or XAU* → GOLD profile;
- symbols containing BTC → BTC profile;
- otherwise → generic profile.

Profiles do not claim asset-specific alpha. They provide portable defaults such
as a spread-quality reference while preserving the same normalized scoring
framework.

## Quality decomposition

The current heuristic quality score is 0–100:

- trend: 20;
- directional momentum: 15;
- ADX strength: 15;
- H4 alignment: 15;
- 20-bar structure location: 15;
- candle efficiency: 10;
- liquidity/spread + volume ratio: 10.

A setup must also be directionally coherent across slope, H4 and range
location. A high arithmetic score cannot override contradictory direction.

This score is **not a calibrated probability**. It must be evaluated by score
bucket against realized R and OOS outcomes before any threshold is treated as
stable.

## Closed-bar signal candidate

InpSignalClosedBarOnly=true removes the legacy requirement that EMA fast/slow
remain crossed on bar [0].

Legacy:

    [2] -> [1] crossover
    AND
    bar [0] still confirms

Experimental:

    [2] -> [1] crossover
    closed bars only

The default remains false, so existing presets retain their historical
behavior. The GOLD and BTC adaptive research presets enable the closed-bar
candidate to test whether it reduces first-tick sensitivity.

## GOLD candidate

config/research/GoldenTradeX_GOLD_M15_adaptive.experimental.set

Key research boundaries:

- real trading disabled;
- 0.5% risk;
- closed-bar crossover candidate;
- GOLD adaptive profile;
- minimum adaptive quality 60;
- 6 bps candidate spread ceiling;
- portfolio risk cap 1%;
- research telemetry enabled.

The 7–20 session window remains broker-server-time dependent and must be
validated against XM server time/DST before forward evidence.

## BTCUSD candidate

config/research/GoldenTradeX_BTCUSD_M15.experimental.set

Key research boundaries:

- real trading disabled;
- 0.5% risk;
- closed-bar crossover candidate;
- BTC adaptive profile;
- minimum adaptive quality 58;
- 10 bps candidate spread ceiling;
- no weekday session filter;
- no forced Friday close;
- portfolio risk cap 1%;
- research telemetry enabled.

Broker availability still controls actual crypto trading hours.

## Telemetry

When adaptive analysis is enabled, the EA writes an additional append-only
analysis stream containing profile, direction, decision, total quality,
component scores, ATR bps, spread bps and volume ratio.

This supports later calibration such as E[R | quality bucket], win rate and
profit factor by quality bucket, spread-cost sensitivity and IS/OOS stability.

## Validation order

For each asset independently:

    broker/symbol contract discovery
            ↓
    registered Strategy Tester matrix
            ↓
    IS-only candidate selection
            ↓
    frozen OOS
            ↓
    feature ablation
            ↓
    score calibration
            ↓
    robustness / cost stress
            ↓
    fixed forward DEMO
            ↓
    manual production review

Passing GOLD does not validate BTCUSD, and vice versa.

## Safety boundary

This phase does not authorize live trading.

    InpAllowRealTrading=false
    live_trading_authorized=false
    real_capital_authorized=false

The current forward-DEMO evidence path also remains blocked until the approved
economic-calendar contract covers the intended 2026 observation window.
