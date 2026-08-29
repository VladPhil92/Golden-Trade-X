# Golden Trade X v2.90.2 — Rolling IS → Frozen OOS

## Objective

v2.90.2 introduces a fail-closed walk-forward contract for Golden Trade X. The purpose is to prevent temporal leakage, post-hoc threshold changes and accidental reuse of in-sample decisions as if they were out-of-sample evidence.

The sequence is:

```text
pre-approved promotion policy
        ↓ SHA-256 locked before OOS
walk-forward plan
        ↓
rolling IS candidate executions
        ↓
deterministic IS selection policy
        ↓
selected preset copied byte-for-byte
        ↓ frozen SHA-256
independent OOS Strategy Tester execution
        ↓
normalized OOS evidence
        ↓
repeat for every fold
        ↓
OOS aggregation
        ↓
pre-registered promotion gate
        ↓
FORWARD DEMO CANDIDATE only
```

A passing promotion gate never authorizes live trading.

## 1. Temporal plan

`scripts/walk_forward_planner.py` creates deterministic fixed-length rolling windows.

The planner uses half-open date geometry internally:

- `start_date` is inclusive;
- `end_date` in the plan config is exclusive;
- each IS and OOS `end_date_exclusive` is exclusive;
- the generated experiment-registry `period_end` is one second before that exclusive boundary.

Official OOS windows may not overlap. Therefore `step_months` must be greater than or equal to `oos_months`.

An optional `embargo_days` gap may be inserted between the end of IS and the beginning of OOS. The default example uses zero because separate Strategy Tester executions already reset position state; a non-zero embargo should be declared when the research design requires it.

## 2. Policy must exist before OOS

The plan stores the exact SHA-256 of the promotion policy. This prevents changing the criteria after observing OOS results.

`config/promotion_policy.example.json` is intentionally:

```json
"approved": false
```

Its thresholds are examples, not validated Golden Trade X promotion criteria. Before an official walk-forward campaign, create a reviewed immutable policy and set `approved=true` before generating the official plan.

If the policy is not approved, the planner marks the output:

```text
DRAFT_POLICY_UNAPPROVED
```

and the selector refuses an official OOS freeze.

## 3. IS candidate selection

For each fold, provide an IS evidence manifest:

```json
{
  "fold_id": "WF001",
  "candidates": [
    {
      "name": "candidate_a",
      "spec": "candidate_a/spec.json",
      "normalized_results": "candidate_a/normalized_results.json"
    },
    {
      "name": "candidate_b",
      "spec": "candidate_b/spec.json",
      "normalized_results": "candidate_b/normalized_results.json"
    }
  ]
}
```

`scripts/walk_forward_selector.py` verifies that:

1. every candidate is a real `strategy_tester` experiment;
2. every candidate uses the exact planned IS dates;
3. normalized evidence `experiment_id` equals the identity recomputed from the spec and preset hash;
4. candidates share execution provenance such as Git SHA, broker, symbol, timeframe, MT5 build, tester model, costs and execution mode;
5. only preset content / runtime preset filename may distinguish candidate execution identity for ranking;
6. all predeclared constraints pass before a candidate is eligible;
7. objective and tie-breakers are applied deterministically;
8. candidate name ascending is the final deterministic tie-breaker.

No OOS metric participates in this choice.

## 4. Frozen OOS spec

The selected IS preset is copied byte-for-byte to:

```text
frozen_preset.set
```

The selector records its SHA-256 and creates an `oos_spec.json` whose dates are replaced by the planned OOS window. The OOS experiment gets a new registry identity because its temporal boundaries differ, while its executable preset remains frozen.

The selection manifest records:

- IS experiment ID and fingerprint;
- IS normalized-result hash;
- frozen preset SHA-256;
- complete candidate ranking inputs;
- selection policy;
- promotion-policy hash;
- resulting OOS experiment ID and fingerprint.

## 5. OOS aggregation

`scripts/walk_forward_aggregate.py` refuses partial evidence. Every planned fold must appear exactly once.

For every fold it revalidates:

- the plan hash;
- promotion-policy hash;
- selection manifest;
- frozen preset hash;
- OOS experiment identity;
- OOS dates;
- normalized results `experiment_id`.

The aggregate contains:

- total trades;
- total net profit;
- aggregate expected payoff (`total net profit / total trades`);
- median and minimum fold Profit Factor;
- median expected payoff;
- worst observed fold drawdown;
- profitable-fold ratio;
- positive-expectancy-fold ratio;
- optional medians for recovery factor, Sharpe and win rate when every fold provides them.

The system **does not construct a synthetic stitched equity curve**. Consequently `max_drawdown_pct` in the aggregate is the worst fold drawdown and must not be presented as continuous portfolio drawdown.

## 6. Promotion gate

`scripts/promotion_gate.py` verifies that the supplied policy hash is exactly the hash locked into the walk-forward plan before OOS.

Possible decisions are:

```text
BLOCKED_POLICY_UNAPPROVED
DO_NOT_PROMOTE
PROMOTE_TO_FORWARD_DEMO_CANDIDATE
```

Even the positive decision emits:

```json
"live_trading_authorized": false
```

Forward demo remains a separate validation phase.

## 7. Example commands

Generate a draft plan:

```bash
python scripts/walk_forward_planner.py \
  --config config/walk_forward_plan.example.json \
  --output data/research/walk_forward/plan_manifest.json
```

The example remains draft because its promotion policy is not approved.

After running the registered IS candidate set for a fold:

```bash
python scripts/walk_forward_selector.py \
  --plan data/research/walk_forward/plan_manifest.json \
  --evidence data/research/walk_forward/WF001/is_evidence.json \
  --output-dir data/research/walk_forward/WF001/frozen
```

After every frozen OOS run is complete:

```bash
python scripts/walk_forward_aggregate.py \
  --plan data/research/walk_forward/plan_manifest.json \
  --evidence data/research/walk_forward/oos_evidence.json \
  --output data/research/walk_forward/oos_summary.json
```

Then evaluate the exact pre-registered policy:

```bash
python scripts/promotion_gate.py \
  --summary data/research/walk_forward/oos_summary.json \
  --policy config/promotion_policy.approved.json \
  --output data/research/walk_forward/promotion_decision.json
```

## Evidence boundary

v2.90.2 supplies the temporal and governance machinery for real walk-forward evidence. It does not itself prove profitability. Golden Trade X remains experimental until registered Strategy Tester OOS evidence passes a policy that was frozen before OOS and is subsequently confirmed in forward demo.
