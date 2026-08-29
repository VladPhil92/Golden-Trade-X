# Golden Trade X v2.90 — Reproducible Validation

## Objective

v2.90 converts Strategy Tester work into registered, reproducible experiments. A backtest is evidence only when the exact code, preset, tester provenance, period and produced artifacts can be identified later.

The workflow is:

```text
experiment JSON
    ↓
provenance validation
    ↓
preset SHA-256 + canonical experiment fingerprint
    ↓
Experiment Registry
    ↓
deterministic Strategy Tester INI
    ↓
MetaTrader 5 Strategy Tester
    ↓
observed report artifact
    ↓
artifact SHA-256
    ↓
COMPLETED experiment
```

A green CI run is not a profitable trading result. A `COMPLETED` experiment means only that the configured run produced registered evidence; statistical promotion remains a separate gate.

## Experiment identity

`scripts/experiment_registry.py` requires:

- full Git commit SHA;
- exact preset path and computed SHA-256;
- broker/tester source;
- symbol;
- timeframe;
- UTC period start/end;
- source type;
- MetaTrader build;
- modelling mode;
- deposit and leverage.

The normalized metadata and preset hash are serialized canonically and hashed. The resulting fingerprint creates an idempotent experiment id:

```text
gtx-<first 16 chars of SHA-256 fingerprint>
```

Registering the same configuration twice returns the same experiment instead of fabricating a second independent observation. Changing the preset contents changes the preset hash and therefore the experiment identity.

## Status model

```text
PLANNED
  ↓
PREPARED
  ↓
RUNNING
  ├──→ FAILED
  └──→ COMPLETED
```

`PREPARED` explicitly means that configuration artifacts exist but no completed Strategy Tester evidence has been observed.

The harness marks a run `COMPLETED` only when MetaTrader returns successfully and a non-empty Strategy Tester report exists. Preparation alone never becomes completion.

## Example

Start from `config/experiment.example.json`. It is a template, not evidence. Replace placeholders with observed provenance.

Register without running:

```bash
python scripts/experiment_registry.py \
  --db data/research/experiments.sqlite \
  register --spec config/experiment.json
```

Prepare a deterministic Strategy Tester configuration:

```bash
python scripts/strategy_tester_harness.py \
  --spec config/experiment.json \
  --registry data/research/experiments.sqlite \
  --output-dir data/research/runs
```

On Windows, execution can be enabled by supplying the terminal path:

```powershell
python scripts/strategy_tester_harness.py `
  --spec config/experiment.json `
  --registry data/research/experiments.sqlite `
  --output-dir data/research/runs `
  --terminal "C:\Program Files\MetaTrader 5\terminal64.exe"
```

The exact tester numeric model is supplied by the experiment spec (`tester_model`) and its semantic description is separately recorded (`modelling`). The harness deliberately does not guess numeric model semantics across MT5 builds.

## Ablation contract

Ablations must be one-change-at-a-time. Variant experiments therefore record:

```json
{
  "parent_experiment_id": "gtx-...",
  "changed_parameter": "InpUseSmcFilter",
  "changed_from": true,
  "changed_to": false
}
```

When any change metadata is present, all three change fields are required and the before/after values must differ.

Ablation comparison is valid only when all non-target conditions are frozen, including code SHA, period, broker/tester source, modelling, deposit, leverage and every other preset parameter.

## Evidence boundary

The registry does not claim that a completed backtest proves edge. Promotion requires subsequent v2.90 gates:

1. baseline and one-change-at-a-time ablation matrix;
2. true IS optimization → frozen parameters → independent OOS run;
3. rolling walk-forward aggregation;
4. spread/commission/slippage stress;
5. parameter stability;
6. broker robustness;
7. OOS promotion criteria;
8. forward demo before any controlled production candidate.

## Next implementation increment

The next increment after this registry/harness foundation is an experiment matrix runner that generates controlled baseline/ablation specs and a Windows Strategy Tester workflow that executes the matrix and uploads immutable evidence artifacts.
