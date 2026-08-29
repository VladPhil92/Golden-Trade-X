# Golden Trade X v2.90 — Reproducible Validation

## Objective

v2.90 converts Strategy Tester work into registered, reproducible experiments. A backtest is evidence only when the exact code, preset, tester provenance, execution mode, period and produced artifacts can be identified later.

The workflow is:

```text
experiment JSON
    ↓
provenance validation
    ↓
preset SHA-256 + execution fingerprint
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

`scripts/experiment_registry.py` fails closed unless the required provenance is complete. Strategy Tester experiments identify, among other fields:

- full Git commit SHA;
- exact preset SHA-256;
- broker/tester source;
- symbol and timeframe;
- UTC period start/end;
- MetaTrader build;
- human-readable modelling semantics and exact numeric `tester_model`;
- EA path and runtime preset name;
- execution mode and portable/non-portable data mode;
- deposit, currency and leverage;
- spread/commission/swap/slippage assumptions;
- optimization/forward settings.

The fingerprint intentionally excludes human notes and ablation labels. Relabelling the same execution must not manufacture a second independent observation. Conversely, changing an execution-critical field such as the preset contents or tester model creates a different identity.

The resulting id is:

```text
gtx-<first 16 chars of SHA-256 fingerprint>
```

Registering the same execution configuration twice returns the same experiment.

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

`PREPARED` explicitly means that configuration artifacts exist but no completed Strategy Tester evidence has been observed. The harness marks a run `COMPLETED` only when MetaTrader returns successfully and a non-empty Strategy Tester report exists. Preparation alone never becomes completion.

## Single experiment

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

`portable_mode` is recorded explicitly. The harness only adds `/portable` when the registered experiment says the terminal is using that data topology.

## Ablation matrix

Ablations must be one-change-at-a-time. `scripts/experiment_matrix.py` generates a frozen baseline plus variant presets/specs from `config/ablation_matrix.example.json`.

```bash
python scripts/experiment_matrix.py \
  --base-spec config/experiment.json \
  --matrix config/ablation_matrix.example.json \
  --output-dir data/research/ablation
```

The matrix manifest records the baseline experiment id plus each variant's exact preset hash and change metadata. The generator refuses missing parameters, duplicate variant names, duplicate parameter definitions and variants that do not actually change the baseline value.

A generated variant records:

```json
{
  "parent_experiment_id": "gtx-...",
  "changed_parameter": "InpUseSmcFilter",
  "changed_from": "true",
  "changed_to": "false"
}
```

These labels document the controlled relationship; execution identity itself is still determined by actual executable inputs.

## GitHub Actions research execution

`.github/workflows/strategy-tester-research.yml` is a manual `workflow_dispatch` research workflow. It:

1. installs official MetaTrader 5 using the same project compile path;
2. compiles the exact checked-out GoldenTradeX EA;
3. stages the selected preset in the actual Tester profile directory;
4. records the current Git SHA, MT5 file/build version and actual portable/non-portable data mode;
5. executes the registered Strategy Tester experiment;
6. fails if no non-empty report is produced;
7. uploads the experiment registry, report/run evidence, runtime spec, compile log and EX5 artifact.

A hosted GitHub runner is not automatically equivalent to a specific production broker. If the requested symbol/history/broker environment is unavailable, the run must fail rather than silently substitute another source. Broker-robustness work should therefore use explicitly provisioned environments or self-hosted runners where appropriate.

## Evidence boundary

The registry does not claim that a completed backtest proves edge. Promotion requires subsequent v2.90 gates:

1. execute baseline and one-change-at-a-time ablation matrix;
2. normalize Strategy Tester reports into a comparison dataset;
3. true IS optimization → freeze parameters → independent OOS run;
4. rolling walk-forward aggregation;
5. spread/commission/slippage stress;
6. parameter stability;
7. broker robustness;
8. OOS promotion criteria;
9. forward demo before any controlled production candidate.

## Next implementation increment

The next increment is the normalized Strategy Tester result parser plus the rolling IS→frozen OOS experiment planner. No parameter should be promoted from the current research tooling without counterfactual Strategy Tester confirmation.
