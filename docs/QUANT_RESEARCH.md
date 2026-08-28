# Golden Trade X v2.80 — Quant Research Methodology

## Scope

v2.80 starts quantitative research on top of the v2.70 telemetry database. The first gate is intentionally conservative: it verifies data integrity, provenance and minimum internal coverage before descriptive baseline metrics are treated as usable research material.

A green software CI run is **not** a green trading result. Likewise, `READY_FOR_EXPLORATORY_RESEARCH` means only that the configured internal data-quality floor was met. It does not mean that the strategy is profitable, statistically significant, OOS validated, walk-forward robust, broker robust or forward validated.

## Reproducible input contract

The baseline consumes two inputs:

1. the v2.70 SQLite telemetry database;
2. a provenance manifest describing the dataset/experiment source.

Start from `config/research_manifest.example.json`, but replace every `<REQUIRED_...>` value with observed provenance. The template itself is intentionally invalid as evidence.

Required provenance:

- unique dataset id;
- source type (`strategy_tester`, `demo`, `forward_demo`, `live` or `other`);
- exact Git commit SHA;
- SHA-256 of the preset used;
- broker/tester source;
- symbol scope;
- timeframe;
- period start/end.

The report hashes the canonical manifest plus the ordered v2.70 outcome row hashes to produce a dataset fingerprint. Re-running the same database + manifest therefore produces the same fingerprint even when report generation time changes.

## Baseline command

```bash
python scripts/quant_research.py \
  --db data/gtx_research.sqlite \
  --manifest config/research_manifest.json \
  --output data/research/baseline.json
```

To make automation fail when the exploratory floor is not met:

```bash
python scripts/quant_research.py \
  --db data/gtx_research.sqlite \
  --manifest config/research_manifest.json \
  --output data/research/baseline.json \
  --enforce
```

Exit behavior:

- `0`: report generated; with `--enforce`, evidence floor passed;
- `2`: invalid data integrity;
- `3`: `--enforce` requested but evidence is insufficient.

## Status semantics

### `INVALID_DATA`

Used when the database contradicts the telemetry contract, for example:

- duplicate final outcome for the same `POSITION_IDENTIFIER`;
- missing/invalid position identity;
- non-positive Initial Risk money;
- invalid/non-finite Realized R or net P/L;
- negative MFE/MAE despite the v2.62 definition as non-negative excursion magnitudes;
- invalid confidence values;
- invalid direction;
- close timestamp before entry;
- symbol observed outside the manifest scope.

No parameter recommendation should be produced from a dataset in this state.

### `INSUFFICIENT_EVIDENCE`

The rows may be internally consistent, but one or more internal exploratory floors are not met. Defaults are:

| Gate | Default |
|---|---:|
| Final outcomes | 100 |
| Confidence coverage | 95% |
| MFE/MAE coverage | 99% |
| Entry/close time coverage | 95% |
| Per-segment descriptive floor | 30 outcomes |

These numbers are project-internal research floors, **not universal statistical sufficiency thresholds** and not promotion criteria for real capital.

Missing provenance also produces `INSUFFICIENT_EVIDENCE` rather than allowing anonymous data to become an official baseline.

### `READY_FOR_EXPLORATORY_RESEARCH`

The configured quality/provenance floors passed. Descriptive baseline, confidence-bin and regime summaries may be used to formulate hypotheses for controlled experiments. This status still does not establish edge.

## Baseline outputs

The report records only observed data:

- dataset fingerprint and provenance manifest;
- data-quality diagnostics and coverage ratios;
- Realized R distribution;
- MFE and MAE distributions;
- observed positive/negative/zero outcomes;
- R-space profit factor (descriptive, not forward estimate);
- net observed R;
- average MFE-minus-realized-R gap;
- confidence-bin descriptive summaries;
- regime descriptive summaries.

Empty or missing observations remain `null`/empty. The script does not manufacture zeros, trades or missing excursion values.

## Ablation boundary

v2.70 telemetry preserves component scores and rejected decisions, but telemetry alone cannot provide the outcome of a trade that was **not taken** under a counterfactual configuration. Therefore a true ablation such as “disable SMC” or “remove Fibonacci weight” cannot be inferred by deleting/filtering rows after the fact.

The baseline report explicitly returns:

```text
REQUIRES_COUNTERFACTUAL_STRATEGY_TESTER_RUNS
```

for ablation status.

True v2.80 ablation must use controlled Strategy Tester reruns where exactly one component/configuration changes and every other relevant input is frozen. Those runs will be compared only after provenance and data-quality gates pass.

## Confidence-research warning

The legacy `scripts/optimize_confidence.py` searches thresholds on the same dataset it scores. That is useful for exploratory sensitivity analysis, but selecting the best threshold on the full dataset creates selection bias and is not OOS validation. v2.80 will replace “optimal threshold” language with train/holdout or controlled Strategy Tester experiment semantics before any confidence recommendation is promoted.

## Exit-research boundary

MFE/MAE and Realized R support descriptive exit diagnostics, including how much favorable excursion was captured. They do **not** establish that a different stop, take-profit, partial, break-even or trailing rule would have produced the same path-dependent trade sequence. Counterfactual exit recommendations also require controlled reruns.

## v2.80 exit gate

v2.80 is complete only when:

- [x] data-quality/provenance gate exists;
- [x] reproducible descriptive baseline exists;
- [ ] legacy confidence optimizer no longer presents in-sample selection as validated optimization;
- [ ] confidence research uses explicit holdout/counterfactual semantics;
- [ ] ablation experiment matrix is reproducible and one-change-at-a-time;
- [ ] exit research distinguishes descriptive MFE/MAE diagnostics from counterfactual reruns;
- [ ] controlled experiment outputs are registered without fabricating missing evidence;
- [ ] CI/Security/MQL5 required gates pass for all integrated v2.80 changes.
