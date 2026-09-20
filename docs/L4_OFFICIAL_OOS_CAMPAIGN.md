# Golden Trade X — L4 Official Rolling IS → Frozen OOS Campaign

## Objective

L4 is the first stage that generates official economic validation evidence from the frozen
Golden Trade X campaign.

It executes the pre-registered sequence:

```text
Approved DEMO environment
        +
Frozen candidate universe
        +
Frozen policies
        +
Frozen walk-forward geometry
        ↓
READY_TO_FREEZE
        ↓
OFFICIAL_CAMPAIGN_FROZEN
        ↓
Runtime MT5 DEMO attestation
        ↓
Rolling IS candidate execution
        ↓
IS-only selection
        ↓
Frozen OOS execution
        ↓
OOS aggregation
        ↓
Frozen promotion policy
        ↓
PASS_TO_ROBUSTNESS or REJECTED
```

L4 never authorizes live trading or real capital.

## Launch protection

The workflow is manual and requires the literal confirmation:

```text
RUN_L4_DEMO_OOS
```

Only one official L4 campaign may run at a time. GitHub Actions concurrency prevents two
official campaigns from generating evidence concurrently.

The workflow also fails before evidence generation if any of these secrets are missing:

```text
GTX_MT5_LOGIN
GTX_MT5_PASSWORD
GTX_MT5_SERVER
```

They must identify the approved DEMO environment. Never use REAL-account credentials in L4.

## Frozen Python runtime

The campaign config names `config/campaign_requirements.lock`.

L4 now installs that exact lock before runtime attestation and Strategy Tester orchestration.
The repository therefore validates and executes against the same pinned direct dependency set.

## Required repository inputs

Before L4 can run, `config/official_validation_campaign.json` must reference:

- an approved canonical DEMO execution environment, not `execution_environment.example.json`;
- `economic_calendar.v1.json`;
- `campaign_requirements.lock`;
- `walk_forward_plan.v1.json`;
- an official robustness template derived from at least two approved DEMO broker environments,
  not `robustness_template.example.json`;
- approved promotion, robustness and forward-demo policies.

`scripts/pre_campaign_readiness.py` must return:

```text
READY_TO_FREEZE
```

before any official Strategy Tester evidence is generated.

## L4 evidence integrity gate

After the IS→OOS runner completes, `scripts/official_campaign_evidence_check.py` validates:

- the pre-campaign readiness artifact;
- the immutable campaign lock;
- the exact MT5 DEMO attestation;
- the official execution manifest;
- the OOS evidence manifest;
- the aggregated OOS summary;
- the frozen promotion decision;
- all evidence hashes;
- campaign ID, fingerprint and build identity;
- candidate-universe identity;
- completion of every OOS fold;
- consistency between promotion decision and terminal campaign status.

The terminal methodological outcomes are:

```text
OOS_PROMOTION_PASS_READY_FOR_ROBUSTNESS
OOS_PROMOTION_REJECTED
```

Both are valid completed L4 outcomes. A rejection is not converted into a software failure.

The integrity artifact is:

```text
data/research/official_campaign/l4_completion.json
```

with methodology:

```text
L4_OFFICIAL_OOS_EVIDENCE_INTEGRITY_V1
```

and status:

```text
L4_OFFICIAL_OOS_EVIDENCE_VALIDATED
```

## Interpretation boundary

If the result is:

```text
OOS_PROMOTION_PASS_READY_FOR_ROBUSTNESS
```

the only authorized next stage is **Robustness Validation**.

If the result is:

```text
OOS_PROMOTION_REJECTED
```

the campaign stops for review. The failed candidate must not be promoted merely because the
software pipeline itself passed.

Neither outcome constitutes a claim of future profitability.

## Operator sequence

1. Materialize the primary MT5 DEMO environment.
2. Review and freeze its approval.
3. Repeat with a genuinely distinct DEMO broker environment.
4. Materialize the official robustness template from both approved environments.
5. Install the canonical environment and robustness files into `config/`.
6. Update `config/official_validation_campaign.json` to reference those canonical files.
7. Confirm pre-campaign readiness reaches `READY_TO_FREEZE`.
8. Open GitHub Actions → **Official Validation Campaign**.
9. Keep the default campaign config unless intentionally using another reviewed config.
10. Enter `RUN_L4_DEMO_OOS`.
11. Run the workflow.
12. Preserve the generated official campaign artifact.

## Safety boundary

Every L4 artifact must retain:

```text
live_trading_authorized=false
real_capital_authorized=false
```

L4 does not place discretionary live orders and does not enable real-money execution.
