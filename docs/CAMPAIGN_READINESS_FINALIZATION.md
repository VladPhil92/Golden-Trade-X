# Golden Trade X — Phase 7A Campaign Readiness Finalization

## Objective

Close the last software-side blockers before the first official rolling IS → frozen OOS campaign.

Phase 7A does **not** authorize live trading or real capital. Its purpose is to make the
validation environment auditable, reproducible and fail-closed.

## 1. DEMO execution-environment hardening

A reviewed DEMO environment now binds the following account fields to the discovery evidence:

- account company;
- account server;
- account currency;
- leverage;
- symbol;
- exact MT5 build.

The approval freeze also requires a frozen symbol contract:

- digits;
- point;
- trade contract size;
- trade tick size;
- trade tick value;
- profit currency.

A mismatch between discovery evidence and the reviewed candidate blocks approval.

The runtime attestation repeats the same account/symbol checks before official execution.

## 2. Symbol-contract boundary

Legacy draft contracts may still be parsed, but an official campaign readiness decision requires
a non-empty `symbol_contract`. This prevents a reviewed XAUUSD environment from being silently
reused against materially different broker contract specifications.

## 3. Robustness broker-universe materialization

`scripts/materialize_robustness_template.py` derives the broker universe from approved DEMO
execution-environment contracts. It does not accept free-form broker labels as official evidence.

The materializer requires:

- at least two approved DEMO environments;
- distinct broker labels;
- distinct account company/server identities;
- frozen symbol-contract metadata in every source environment;
- `live_trading_authorized=false`.

It preserves the reviewed parameter-perturbation and modeled-cost geometry from the base robustness
template and emits:

- `robustness_template.v1.json`;
- `robustness_template.materialization.json`.

The audit binds the output to the exact source environment file hashes and canonical environment hashes.

## 4. Operator sequence

### Environment A

1. Configure repository secrets:
   - `GTX_MT5_LOGIN`
   - `GTX_MT5_PASSWORD`
   - `GTX_MT5_SERVER`
2. Run **Materialize DEMO Execution Environment**.
3. Review the candidate and discovery audit.
4. Commit the reviewed artifacts under `data/research/environment-review/`.
5. Run **Freeze DEMO Execution Environment Approval**.
6. Install the approved result into a reviewed canonical config file.

### Environment B

Repeat the same process with a genuinely distinct broker/company-server environment.

### Robustness template

Run **Materialize Robustness Template** with the two canonical approved environment files.
Review the generated artifact, then install the exact reviewed template as
`config/robustness_template.v1.json`.

### Campaign wiring

Only after the canonical DEMO environment and robustness template exist:

1. update `config/official_validation_campaign.json` to reference them;
2. run `scripts/pre_campaign_readiness.py`;
3. require `READY_TO_FREEZE`;
4. freeze the official campaign with the exact checked-out Git SHA;
5. generate a fresh runtime MT5 attestation;
6. begin rolling IS → frozen OOS.

## 5. Phase exit criteria

Phase 7A is complete only when:

- one canonical execution environment is approved and installed for the primary official campaign;
- the approved environment includes account currency, leverage and symbol contract metadata;
- at least two approved DEMO broker environments exist for robustness replication;
- `config/robustness_template.v1.json` contains real broker labels derived from those contracts;
- `official_validation_campaign.json` no longer references either `.example.json` blocker;
- pre-campaign readiness returns `READY_TO_FREEZE`;
- all CI, Security, MQL5 and Reproducibility gates pass.

The next phase is **L4 — Official rolling IS → frozen OOS campaign**.
