# Golden Trade X — Pre-Campaign Hardening

## Purpose

This document defines the boundary between repository engineering readiness and the first official quantitative validation campaign. It is intentionally fail-closed: incomplete external inputs do not become evidence merely because the software stack is green.

## Repository-controlled gates

The following must be green before an official campaign is frozen:

1. `CI required gate`
2. `Security required gate`
3. `MQL5 required gate`
4. `Reproducibility required gate`
5. `scripts/pre_campaign_readiness.py` returns `READY_TO_FREEZE`

The pre-campaign gate requires:

- a non-DRAFT campaign id;
- an approved economic-calendar contract;
- calendar coverage spanning the complete walk-forward period;
- exact BLS provenance for NFP/CPI and Federal Reserve provenance for FOMC;
- a generated `EconomicCalendarData.mqh` that matches the canonical calendar hash;
- an exact campaign dependency lock.

## External inputs that cannot be manufactured in the repository

These remain manual/runtime blockers until real values exist:

- DEMO broker account and server;
- `GTX_MT5_LOGIN`, `GTX_MT5_PASSWORD`, `GTX_MT5_SERVER` stored as GitHub Secrets;
- exact broker/account-company identity;
- exact MT5 terminal build;
- synchronized symbol/history availability;
- approved OOS/robustness/forward policies;
- approved historical economic-calendar dataset;
- actual Strategy Tester results;
- actual forward DEMO observation.

No placeholder value is acceptable for official evidence.

## Economic-calendar lifecycle

```text
BLS/Federal Reserve primary records
        ↓
reviewed JSON contract
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

`config/economic_calendar.example.json` is deliberately `approved=false`. Exploratory/demo runs may retain the documented legacy NFP/CPI proxy fallback while this contract is draft. The official workflow cannot pass the preflight with the draft artifact.

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

Engineering hardening is complete when all required workflow families pass on the same immutable SHA and `pre_campaign_readiness.py` is capable of returning `READY_TO_FREEZE` for real, approved campaign inputs. That status means **ready to generate evidence**, not profitable and not authorized for real capital.
