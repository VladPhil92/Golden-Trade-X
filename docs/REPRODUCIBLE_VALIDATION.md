# Golden Trade X v2.90 — Reproducible Validation

## Objective

v2.90 converts Strategy Tester work into registered, reproducible experiments. A backtest is evidence only when the exact code, preset, tester provenance, execution mode, period and produced artifacts can be identified later.

Since v2.90.1, a non-empty MetaTrader report is no longer sufficient to mark an experiment complete. The report must also satisfy the normalized result contract.

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
raw HTML report
    ↓
normalized result parser
    ↓
raw + normalized SHA-256 evidence
    ↓
COMPLETED experiment
```

A green CI run is not a profitable trading result. A `COMPLETED` experiment means only that the configured run produced parseable, registered evidence; statistical promotion remains a separate gate.

## Experiment identity

`scripts/experiment_registry.py` fails closed unless required provenance is complete. Strategy Tester experiments identify, among other fields:

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

The fingerprint intentionally excludes human notes and ablation labels. Relabelling the same execution must not manufacture a second independent observation. Conversely, changing an execution-critical field creates a different identity.

## Status and evidence model

```text
PLANNED
  ↓
PREPARED
  ↓
RUNNING
  ├──→ FAILED
  └──→ raw report
          ↓
      normalize
      ├──→ FAILED
      └──→ COMPLETED
```

`PREPARED` means configuration artifacts exist but no completed Strategy Tester evidence has been observed. `COMPLETED` requires all of the following:

1. terminal execution returned successfully;
2. a non-empty Strategy Tester report exists;
3. the report can be decoded and parsed;
4. all minimum research metrics are present;
5. `normalized_results.json` is produced and hashed;
6. the execution manifest is finalized with raw and normalized evidence hashes.

## Normalized Strategy Tester results

`scripts/strategy_tester_results.py` parses MT5 HTML reports without adding a third-party HTML dependency. UTF-8 and UTF-16 reports are supported, together with canonical English labels and the principal Spanish equivalents.

The minimum fail-closed metric contract is:

- `total_net_profit`;
- `profit_factor`;
- `expected_payoff`;
- `max_drawdown_pct`;
- `total_trades`.

When available, the parser also normalizes win rate, recovery factor, Sharpe ratio, gross profit/loss, trade averages, history quality, ticks and related report fields.

Every metric retains:

```json
{
  "value": 1.42,
  "unit": "ratio",
  "source_label": "Sharpe Ratio",
  "raw_value": "1.42"
}
```

Derived metrics also record their source. For example, `max_drawdown_pct` prefers `Equity Drawdown Relative`; if that field is absent, `Balance Drawdown Relative` is used explicitly as a documented fallback.

A parser warning never fabricates a value. If one of the minimum metrics cannot be established, the experiment fails normalization.

## Single experiment

Start from `config/experiment.example.json`. It is a template, not evidence. Replace placeholders with observed provenance.

```bash
python scripts/strategy_tester_harness.py \
  --spec config/experiment.json \
  --registry data/research/experiments.sqlite \
  --output-dir data/research/runs
```

On Windows, execution is enabled by supplying the terminal path. `portable_mode` is recorded explicitly; the harness only adds `/portable` when the registered experiment declares that topology.

## Ablation matrix

Ablations are one-change-at-a-time. `scripts/experiment_matrix.py` produces a frozen baseline plus variant presets/specs.

The first official component-removal design is `config/ablation_matrix.v1.json` (`GTX-ABLATION-V1`) and contains:

1. SMC filter off;
2. market regime filter off;
3. HTF filter off;
4. equity curve filter off;
5. session filter off;
6. news filter off;
7. trailing stop off;
8. break-even off;
9. partial take profit off.

Fibonacci is intentionally not included in this matrix because the current implementation has no isolated boolean switch. Changing its confidence weight would alter score normalization semantics and would therefore not be a clean one-variable component-removal experiment.

The matrix generator records baseline identity and, for every variant, `parent_experiment_id`, `changed_parameter`, `changed_from`, `changed_to`, preset hash and experiment fingerprint.

## Matrix execution

`scripts/strategy_tester_matrix.py` executes the generated matrix sequentially:

```text
baseline
  ↓
variant 1
  ↓
variant 2
  ↓
...
  ↓
variant N
```

The runner verifies that the experiment identity produced at execution matches the identity frozen in the matrix manifest. `--continue-on-failure` allows all variants to be attempted while still returning an overall failure if any experiment fails. This is useful for preserving diagnostic evidence without declaring an incomplete matrix promotable.

A dry run with no terminal only prepares and registers every experiment. It does not create completed evidence.

## Descriptive ablation report

`scripts/ablation_report.py` compares completed normalized variants against the completed baseline and reports absolute/relative deltas for metrics such as:

- total net profit;
- profit factor;
- expected payoff;
- maximum drawdown percentage;
- trade count;
- win rate;
- recovery factor;
- Sharpe ratio.

The output is explicitly marked `DESCRIPTIVE_ONLY`. A single baseline/variant comparison does **not** establish causal or statistically significant contribution. Component promotion/removal decisions require repeated OOS/walk-forward evidence.

## GitHub Actions research workflows

`.github/workflows/strategy-tester-research.yml` runs one registered Strategy Tester experiment.

`.github/workflows/strategy-tester-ablation.yml` runs the full `GTX-ABLATION-V1` research chain on a Windows runner:

1. installs official MetaTrader 5;
2. compiles the exact checked-out GoldenTradeX EA;
3. records runtime Git/MT5/tester provenance;
4. generates frozen baseline and nine one-change-at-a-time presets;
5. stages them in the actual Tester profile directory;
6. executes baseline and all variants;
7. normalizes every raw report;
8. builds the descriptive ablation report if the full matrix completes;
9. uploads the registry, manifests, raw reports, normalized JSON, generated presets, EX5 and compile logs;
10. fails the workflow if any registered experiment fails.

A GitHub-hosted runner is not automatically equivalent to a production broker. If the requested symbol/history/tester environment is unavailable, the workflow must fail instead of substituting a different source. Broker robustness should ultimately use explicitly provisioned or self-hosted environments.

## Evidence boundary

The current tooling can now answer **what a completed Strategy Tester run reported** and can compare controlled component-removal variants. It still cannot claim stable edge.

Promotion still requires:

1. execute the first official baseline + `GTX-ABLATION-V1` matrix on valid XAUUSD M15 data;
2. inspect component deltas without selecting parameters on OOS data;
3. true IS optimization → freeze parameters → independent OOS run;
4. rolling walk-forward aggregation;
5. spread/commission/slippage stress;
6. parameter stability;
7. broker robustness;
8. OOS promotion criteria;
9. prolonged forward demo before controlled production.

## Next implementation increment

After the first valid ablation evidence set exists, the next software increment is the **rolling IS → frozen OOS experiment planner and promotion gate**. Until then, no component should be declared useful or useless solely from one historical matrix.
