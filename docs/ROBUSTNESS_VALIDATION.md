# Golden Trade X v2.90.3 — Robustness Validation

## Objective

v2.90.3 adds an auditable robustness layer after reproducible OOS infrastructure and before forward-demo readiness. Its central rule is that a metadata change is **not** an executed counterfactual unless that change materially reaches MetaTrader or the EA runtime.

The framework separates three evidence classes:

| Domain | Evidence class | Meaning |
|---|---|---|
| Parameter stability | `EXECUTED_COUNTERFACTUAL` | A generated `.set` changes exactly one EA input and must be rerun in Strategy Tester. |
| Broker robustness | `EXTERNAL_BROKER_REPLICATION` | The exact strategy/preset is rerun in an explicitly declared broker/tester environment. |
| Cost sensitivity | `MODELED_COST_SENSITIVITY` | A deterministic accounting deduction from observed results; not a new MT5 execution. |

These classes must not be collapsed into a single claim of equivalent evidence.

## Why slippage/commission metadata is not enough

The current Strategy Tester harness writes these execution controls into the MT5 tester INI:

- Expert and ExpertParameters;
- symbol and timeframe;
- tester model and execution mode;
- date range;
- optimization/forward mode;
- deposit, currency and leverage;
- report path and shutdown behavior.

The experiment registry also records fields such as `slippage_points`, `commission`, `spread_mode` and `swap_mode`, but the current harness does not materialize those fields into MT5 execution. Therefore changing only those registry values would create a different experiment fingerprint without creating the claimed execution counterfactual.

`scripts/robustness_planner.py` rejects such metadata-only execution claims. Until a verified execution binding exists, transaction-cost stress remains explicitly modeled sensitivity.

## 1. Robustness plan

Start from `config/robustness_plan.example.json`. The example is deliberately draft and points to an unapproved policy.

The planner:

```bash
python scripts/robustness_planner.py \
  --config config/robustness_plan.example.json \
  --output-dir data/research/robustness
```

produces `robustness_plan.json`, executable parameter scenario specs and exact variant presets.

The plan freezes:

- base experiment ID and fingerprint;
- exact base preset SHA-256;
- Git SHA and test geometry;
- exact robustness-policy SHA-256;
- every executable parameter perturbation and its future experiment ID;
- required broker labels;
- explicitly modeled cost scenarios.

If the policy is not approved, status is `DRAFT_POLICY_UNAPPROVED`.

## 2. Parameter stability

Each parameter scenario is a one-change-at-a-time executable counterfactual. The generator modifies exactly one `parameter=value` line in the frozen baseline preset and records:

- parameter;
- old value;
- new value;
- generated preset SHA-256;
- generated experiment ID and fingerprint;
- `parent_experiment_id` linking back to the baseline.

A result counts only when the executed spec recomputes to the predeclared experiment ID and exact preset hash.

The example perturbation magnitudes are illustrative research geometry, not validated optimal neighborhoods.

## 3. Broker replication

Broker evidence is not synthesized by changing the `broker` string. Each declared broker must supply a real Strategy Tester spec and normalized result from that environment.

For a run to count as a broker replication, the following remain invariant relative to baseline:

- Git SHA;
- preset SHA-256;
- symbol and timeframe;
- period start/end;
- source type;
- tester model;
- EA path;
- execution mode;
- deposit/currency/leverage;
- optimization and forward mode.

Broker label and MT5 build may differ. Environment-specific spread, commission, swap metadata and portable topology may also differ and remain provenance rather than evidence of a changed strategy.

Duplicate broker labels do not increase the broker count.

## 4. Modeled cost sensitivity

Because the current harness cannot honestly execute arbitrary slippage/commission/spread stress, v2.90.3 provides a deliberately weaker sensitivity model:

```text
adjusted net profit
  = observed baseline net profit
    - cost_per_trade_currency × observed total trades
```

and:

```text
adjusted expected payoff = adjusted net profit / total trades
```

The output always carries:

```json
{
  "evidence_class": "MODELED_COST_SENSITIVITY",
  "executed_in_mt5": false
}
```

This may be useful for economic sensitivity but cannot substitute for a real counterfactual tester run.

## 5. Robustness aggregation

`scripts/robustness_aggregate.py` requires complete parameter and broker evidence before producing a summary.

Example evidence manifest:

```json
{
  "baseline": {
    "spec": "baseline/spec.json",
    "normalized_results": "baseline/normalized_results.json"
  },
  "parameter_scenarios": [
    {
      "name": "ema_fast_minus",
      "normalized_results": "parameter/ema_fast_minus.json"
    }
  ],
  "broker_runs": [
    {
      "broker": "BROKER-A",
      "spec": "brokers/a/spec.json",
      "normalized_results": "brokers/a/normalized_results.json"
    }
  ]
}
```

Aggregation exposes, among other metrics:

- baseline profit, PF, expectancy, DD and trades;
- parameter positive-profit/expectancy ratios;
- parameter minimum/median PF;
- parameter worst DD;
- parameter minimum net-profit retention;
- distinct broker count;
- broker positive-profit/expectancy ratios;
- broker minimum/median PF;
- broker worst DD;
- broker minimum net-profit retention;
- worst modeled cost-adjusted profit/expectancy/retention.

## 6. Pre-registered robustness gate

`config/robustness_policy.example.json` is intentionally `approved=false`. Its numbers are examples only.

An official campaign must create and review an immutable approved policy **before** generating the official robustness plan. The plan stores the policy SHA-256, and `scripts/robustness_gate.py` refuses a changed policy later.

Possible decisions:

```text
BLOCKED_POLICY_UNAPPROVED
ROBUSTNESS_FAIL
ROBUSTNESS_PASS_FOR_FORWARD_DEMO_REVIEW
```

Even the positive decision contains:

```json
"live_trading_authorized": false
```

The robustness gate is a prerequisite for forward-demo review, not a production release gate.

## 7. Evidence boundary

v2.90.3 improves falsifiability: it tests whether a result survives nearby parameter changes, different broker environments and declared economic cost assumptions. It does not turn modeled costs into executed evidence, it does not manufacture missing broker runs, and it does not establish live-trading readiness.

The next layer after valid OOS plus robustness evidence is a combined forward-demo readiness contract and then a time-based forward-demo observation period.
