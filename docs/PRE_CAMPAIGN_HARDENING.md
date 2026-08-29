# Golden Trade X — Pre-Campaign Hardening

## Purpose

This document defines the boundary between repository engineering readiness and the first official quantitative validation campaign. It is intentionally fail-closed: incomplete external inputs do not become evidence merely because the software stack is green.

## Repository-controlled gates

The following must be green before an official campaign is frozen:

1. `CI required gate`
2. `Security required gate`
3. `MQL5 required gate`
4. `Reproducibility required gate`
5. `scripts/official_policy_check.py` returns `POLICY_BUNDLE_FROZEN`
6. `scripts/pre_campaign_readiness.py` returns `READY_TO_FREEZE`

The pre-campaign gate requires:

- a non-DRAFT campaign id;
- the frozen `GTX-WF-V1` walk-forward geometry and policy references;
- approved OOS, robustness and forward-demo V1 policies;
- an approved DEMO execution-environment contract;
- at least two distinct, non-placeholder broker labels in the robustness template;
- an approved economic-calendar contract;
- calendar coverage spanning the complete half-open walk-forward period `[start_date, end_date)`;
- exact BLS provenance for NFP/CPI and Federal Reserve provenance for FOMC;
- a generated `EconomicCalendarData.mqh` that matches the canonical calendar hash;
- an exact campaign dependency lock including `MetaTrader5`.

## Ex-ante quantitative policy freeze

The first official policy generation is now versioned before any official OOS evidence exists:

- `config/promotion_policy.v1.json` — `GTX-OOS-PROMOTION-V1`;
- `config/robustness_policy.v1.json` — `GTX-ROBUSTNESS-V1`;
- `config/forward_demo_policy.v1.json` — `GTX-FORWARD-DEMO-V1`;
- `config/walk_forward_plan.v1.json` — `GTX-WF-V1`.

These files are `approved=true` because approval here means **pre-registered for evaluation**, not that the strategy passed. Their values must not be changed after official evidence begins. A changed threshold, criterion or observation rule requires a new policy id and a new campaign identity.

The resulting progression remains:

```text
OOS policy PASS
    -> robustness evaluation only
robustness policy PASS
    -> forward DEMO readiness only
forward DEMO policy PASS
    -> manual release review only
```

No policy grants live trading or real-capital authorization.

## Canonical campaign definition

`config/official_validation_campaign.json` is the canonical non-DRAFT V1 campaign definition. Its quantitative policies and walk-forward geometry are fixed, but it deliberately remains operationally blocked while it references unapproved/example external inputs such as the DEMO execution environment, economic calendar and robustness broker template.

The exact Git build SHA is injected at campaign freeze; the tracked zero SHA is a pre-freeze sentinel rather than evidence identity.

## Economic-calendar lifecycle

The official calendar must be sourced rather than transcribed heuristically:

```text
BLS annual schedules + Federal Reserve FOMC statement links
        ↓
scripts/materialize_official_calendar.py
        ↓
unapproved review JSON + audit counts
        ↓
human/source review
        ↓
approved immutable JSON contract
        ↓
canonical SHA-256
        ↓
EconomicCalendarData.mqh generator
        ↓
CI byte-for-byte verification
        ↓
pre-campaign coverage check
        ↓
official campaign freeze
```

`GTX-WF-V1` freezes `start_date=2021-01-01` and `end_date=2026-01-01`. The end date is an **exclusive boundary**, so the exact historical evidence interval is `[2021-01-01, 2026-01-01)`. Consequently, the completed release years required by this campaign are 2021 through 2025 inclusive; no 2026 economic event is part of the frozen historical window. The pre-campaign coverage check therefore accepts a calendar ending at `2025-12-31T23:59:59Z` and rejects any earlier endpoint.

`.github/workflows/materialize-economic-calendar.yml` creates the review artifact from primary-source pages and deliberately leaves `approved=false`. Its dispatch range is bound to the frozen walk-forward window, so a request inconsistent with the current V1 plan fails before source materialization. It uses `America/New_York` timezone rules to convert BLS 08:30 ET and FOMC 14:00 ET release clocks to UTC, so DST is not represented by a fixed offset.

The materializer fails closed if a year produces fewer than ten NFP/CPI releases or does not contain exactly eight regular FOMC statement dates. Exceptional completed schedules therefore remain reviewable rather than silently synthesized. Future meeting dates are not treated as completed statement evidence and are never manufactured to satisfy annual counts.

`config/economic_calendar.example.json` remains deliberately `approved=false`. Exploratory/demo runs may retain the documented legacy NFP/CPI proxy fallback while this contract is draft. The official workflow cannot pass the preflight with the draft artifact.

## External inputs that cannot be manufactured in the repository

These remain manual/runtime blockers until real values exist:

- approved DEMO broker account, company and server;
- `GTX_MT5_LOGIN`, `GTX_MT5_PASSWORD`, `GTX_MT5_SERVER` stored as GitHub Secrets;
- exact MT5 terminal build;
- synchronized symbol/history availability;
- at least two real broker labels/environments for robustness replication;
- reviewed and approved historical BLS/Fed calendar artifact;
- actual Strategy Tester IS/OOS results;
- actual robustness evidence;
- actual forward DEMO observation.

No placeholder value is acceptable for official evidence.

## Dependency lifecycle

`requirements.txt` remains the compatible development environment. `config/campaign_requirements.lock` contains exact direct versions used as part of campaign readiness. Changing the lock after campaign freeze requires a new campaign identity.

## Supply-chain policy

All external GitHub Actions in `.github/workflows/` must be pinned to full 40-character commit SHAs. `scripts/workflow_supply_chain_check.py` enforces this and the Security required gate depends on that check.

## Governance target

`.github/scripts/configure-governance.ps1` is the declarative branch-protection contract. The desired `main` state is:

- PR required;
- strict/up-to-date branch before merge;
- conversation resolution required;
- force pushes blocked;
- deletion blocked;
- `CI required gate` required;
- `Security required gate` required;
- `MQL5 required gate` required;
- `Reproducibility required gate` required;
- zero approval count permitted for a single-maintainer repository without turning automated gates off.

The script cannot substitute for verifying GitHub's live repository settings.

## Remaining manual repository hygiene

Merged historical branches should be pruned only after confirming their commits are reachable from `main`. Branch deletion is an administrative cleanup task and must never be inferred from a merged PR alone.

## Exit criterion

Engineering hardening is complete when all required workflow families pass on the same immutable SHA and `pre_campaign_readiness.py` returns `READY_TO_FREEZE` for real, approved external inputs. That status means **ready to generate evidence**, not profitable and not authorized for real capital.
