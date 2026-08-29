#!/usr/bin/env python3
"""Validate and aggregate Golden Trade X robustness evidence."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path
from typing import Any

try:
    from scripts.experiment_registry import (
        RegistryValidationError,
        identity_for,
        load_spec,
        normalize_spec,
        sha256_file,
    )
except ModuleNotFoundError:
    from experiment_registry import (
        RegistryValidationError,
        identity_for,
        load_spec,
        normalize_spec,
        sha256_file,
    )

REQUIRED_METRICS = (
    "total_net_profit",
    "profit_factor",
    "expected_payoff",
    "max_drawdown_pct",
    "total_trades",
)
BROKER_INVARIANT_FIELDS = (
    "git_sha",
    "preset_sha256",
    "symbol",
    "timeframe",
    "period_start",
    "period_end",
    "source_type",
    "tester_model",
    "expert",
    "execution_mode",
    "deposit",
    "currency",
    "leverage",
    "optimization",
    "forward_mode_code",
)


def _load_json_object(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    with target.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise RegistryValidationError(f"JSON root must be an object: {target}")
    return value


def _resolve(base: Path, raw: Any, field: str) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise RegistryValidationError(f"{field} is required")
    path = Path(raw)
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def _metric(result: dict[str, Any], name: str) -> float:
    summary = result.get("summary")
    if not isinstance(summary, dict) or name not in summary:
        raise RegistryValidationError(f"normalized result missing summary metric: {name}")
    value = summary[name]
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise RegistryValidationError(f"summary metric {name} must be numeric")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise RegistryValidationError(f"summary metric {name} must be finite")
    return parsed


def _metrics(result: dict[str, Any]) -> dict[str, float]:
    return {name: _metric(result, name) for name in REQUIRED_METRICS}


def _validate_evidence_identity(spec_path: Path, result_path: Path) -> tuple[dict[str, Any], Any, dict[str, Any]]:
    spec = load_spec(spec_path)
    normalized, _ = normalize_spec(spec, base_dir=spec_path.parent)
    identity = identity_for(normalized)
    result = _load_json_object(result_path)
    if result.get("experiment_id") != identity.experiment_id:
        raise RegistryValidationError(
            f"normalized evidence experiment_id does not match spec identity: {spec_path}"
        )
    return normalized, identity, result


def _broker_signature(normalized: dict[str, Any]) -> dict[str, Any]:
    return {key: normalized.get(key) for key in BROKER_INVARIANT_FIELDS}


def _retention(value: float, baseline: float) -> float | None:
    if baseline <= 0:
        return None
    return value / baseline


def aggregate_robustness(
    plan_path: str | Path,
    evidence_manifest_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    plan_path = Path(plan_path).resolve()
    evidence_manifest_path = Path(evidence_manifest_path).resolve()
    plan = _load_json_object(plan_path)
    evidence = _load_json_object(evidence_manifest_path)

    if plan.get("methodology") != "ROBUSTNESS_V1":
        raise RegistryValidationError("unsupported robustness plan methodology")
    domains = plan.get("domains")
    if not isinstance(domains, dict):
        raise RegistryValidationError("robustness plan domains are missing")

    base = evidence_manifest_path.parent
    baseline_entry = evidence.get("baseline")
    if not isinstance(baseline_entry, dict):
        raise RegistryValidationError("evidence manifest baseline is required")
    baseline_spec_path = _resolve(base, baseline_entry.get("spec"), "baseline.spec")
    baseline_result_path = _resolve(base, baseline_entry.get("normalized_results"), "baseline.normalized_results")
    baseline_normalized, baseline_identity, baseline_result = _validate_evidence_identity(
        baseline_spec_path, baseline_result_path
    )
    plan_base = plan.get("base")
    if not isinstance(plan_base, dict):
        raise RegistryValidationError("plan base is missing")
    if baseline_identity.experiment_id != plan_base.get("experiment_id"):
        raise RegistryValidationError("baseline experiment_id differs from robustness plan")
    if baseline_identity.preset_sha256 != plan_base.get("preset_sha256"):
        raise RegistryValidationError("baseline preset hash differs from robustness plan")
    baseline_metrics = _metrics(baseline_result)
    if baseline_metrics["total_trades"] <= 0:
        raise RegistryValidationError("baseline robustness evidence requires total_trades > 0")

    # Parameter stability: every generated executable scenario must appear exactly once.
    parameter_domain = domains.get("parameter_stability")
    if not isinstance(parameter_domain, dict):
        raise RegistryValidationError("parameter_stability domain missing")
    planned_scenarios = parameter_domain.get("scenarios")
    if not isinstance(planned_scenarios, list) or not planned_scenarios:
        raise RegistryValidationError("parameter_stability scenarios missing")
    planned_by_name = {
        item["name"]: item for item in planned_scenarios if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    if len(planned_by_name) != len(planned_scenarios):
        raise RegistryValidationError("invalid or duplicate planned parameter scenario names")

    raw_parameter_evidence = evidence.get("parameter_scenarios")
    if not isinstance(raw_parameter_evidence, list):
        raise RegistryValidationError("parameter_scenarios evidence must be an array")
    evidence_by_name: dict[str, dict[str, Any]] = {}
    for item in raw_parameter_evidence:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise RegistryValidationError("parameter evidence entry requires name")
        name = item["name"]
        if name in evidence_by_name:
            raise RegistryValidationError(f"duplicate parameter evidence: {name}")
        evidence_by_name[name] = item
    if set(evidence_by_name) != set(planned_by_name):
        raise RegistryValidationError(
            "parameter evidence must cover every planned scenario exactly once"
        )

    plan_root = plan_path.parent
    parameter_rows: list[dict[str, Any]] = []
    for name in sorted(planned_by_name):
        planned = planned_by_name[name]
        entry = evidence_by_name[name]
        spec_path = _resolve(plan_root, planned.get("spec"), f"{name}.planned_spec")
        result_path = _resolve(base, entry.get("normalized_results"), f"{name}.normalized_results")
        normalized, identity, result = _validate_evidence_identity(spec_path, result_path)
        if identity.experiment_id != planned.get("experiment_id"):
            raise RegistryValidationError(f"{name}: executed identity differs from planned scenario")
        if identity.preset_sha256 != planned.get("preset_sha256"):
            raise RegistryValidationError(f"{name}: executed preset hash differs from planned scenario")
        if normalized.get("parent_experiment_id") != baseline_identity.experiment_id:
            raise RegistryValidationError(f"{name}: scenario parent is not the baseline experiment")
        if normalized.get("changed_parameter") != planned.get("parameter"):
            raise RegistryValidationError(f"{name}: changed_parameter differs from plan")
        metrics = _metrics(result)
        parameter_rows.append(
            {
                "name": name,
                "experiment_id": identity.experiment_id,
                "normalized_results_sha256": sha256_file(result_path),
                "parameter": planned.get("parameter"),
                "changed_from": planned.get("changed_from"),
                "changed_to": planned.get("changed_to"),
                "metrics": metrics,
                "net_profit_retention": _retention(
                    metrics["total_net_profit"], baseline_metrics["total_net_profit"]
                ),
            }
        )

    # Broker replication: exact strategy/preset, distinct declared environment labels.
    broker_domain = domains.get("broker_replication")
    if not isinstance(broker_domain, dict):
        raise RegistryValidationError("broker_replication domain missing")
    required_labels = broker_domain.get("required_labels")
    minimum_brokers = broker_domain.get("minimum_distinct_brokers")
    if not isinstance(required_labels, list) or not isinstance(minimum_brokers, int):
        raise RegistryValidationError("invalid broker replication requirements")

    raw_brokers = evidence.get("broker_runs")
    if not isinstance(raw_brokers, list):
        raise RegistryValidationError("broker_runs evidence must be an array")
    broker_rows: list[dict[str, Any]] = []
    broker_labels: set[str] = set()
    baseline_signature = _broker_signature(baseline_normalized)
    for entry in raw_brokers:
        if not isinstance(entry, dict):
            raise RegistryValidationError("broker run entry must be an object")
        declared = entry.get("broker")
        if not isinstance(declared, str) or not declared.strip():
            raise RegistryValidationError("broker run requires broker label")
        declared = declared.strip()
        if declared in broker_labels:
            raise RegistryValidationError(f"duplicate broker evidence label: {declared}")
        broker_labels.add(declared)
        spec_path = _resolve(base, entry.get("spec"), f"broker {declared}.spec")
        result_path = _resolve(base, entry.get("normalized_results"), f"broker {declared}.normalized_results")
        normalized, identity, result = _validate_evidence_identity(spec_path, result_path)
        if normalized.get("broker") != declared:
            raise RegistryValidationError(f"broker label {declared} does not match spec provenance")
        if _broker_signature(normalized) != baseline_signature:
            raise RegistryValidationError(
                f"broker {declared}: strategy/test geometry differs from baseline beyond broker environment"
            )
        metrics = _metrics(result)
        broker_rows.append(
            {
                "broker": declared,
                "experiment_id": identity.experiment_id,
                "mt5_build": normalized.get("mt5_build"),
                "normalized_results_sha256": sha256_file(result_path),
                "metrics": metrics,
                "net_profit_retention": _retention(
                    metrics["total_net_profit"], baseline_metrics["total_net_profit"]
                ),
            }
        )

    missing_labels = sorted(set(required_labels) - broker_labels)
    if missing_labels:
        raise RegistryValidationError(f"missing required broker evidence: {missing_labels}")
    if len(broker_labels) < minimum_brokers:
        raise RegistryValidationError(
            f"broker evidence has {len(broker_labels)} distinct labels, below minimum {minimum_brokers}"
        )

    # Cost sensitivity: modeled derivative, never an executed experiment.
    cost_domain = domains.get("cost_sensitivity")
    if not isinstance(cost_domain, dict) or cost_domain.get("evidence_class") != "MODELED_COST_SENSITIVITY":
        raise RegistryValidationError("cost_sensitivity must be explicitly MODELED_COST_SENSITIVITY")
    cost_scenarios = cost_domain.get("scenarios")
    if not isinstance(cost_scenarios, list) or not cost_scenarios:
        raise RegistryValidationError("modeled cost scenarios missing")
    trades = baseline_metrics["total_trades"]
    cost_rows: list[dict[str, Any]] = []
    for scenario in cost_scenarios:
        if not isinstance(scenario, dict):
            raise RegistryValidationError("modeled cost scenario must be an object")
        name = scenario.get("name")
        cost = scenario.get("cost_per_trade_currency")
        if not isinstance(name, str) or not isinstance(cost, (int, float)) or isinstance(cost, bool):
            raise RegistryValidationError("invalid modeled cost scenario")
        adjusted_net = baseline_metrics["total_net_profit"] - float(cost) * trades
        cost_rows.append(
            {
                "name": name,
                "evidence_class": "MODELED_COST_SENSITIVITY",
                "cost_per_trade_currency": float(cost),
                "adjusted_total_net_profit": adjusted_net,
                "adjusted_expected_payoff": adjusted_net / trades,
                "net_profit_retention": _retention(
                    adjusted_net, baseline_metrics["total_net_profit"]
                ),
                "executed_in_mt5": False,
            }
        )

    parameter_pfs = [row["metrics"]["profit_factor"] for row in parameter_rows]
    parameter_dd = [row["metrics"]["max_drawdown_pct"] for row in parameter_rows]
    parameter_retentions = [
        row["net_profit_retention"] for row in parameter_rows if row["net_profit_retention"] is not None
    ]
    broker_pfs = [row["metrics"]["profit_factor"] for row in broker_rows]
    broker_dd = [row["metrics"]["max_drawdown_pct"] for row in broker_rows]
    broker_retentions = [
        row["net_profit_retention"] for row in broker_rows if row["net_profit_retention"] is not None
    ]
    cost_retentions = [
        row["net_profit_retention"] for row in cost_rows if row["net_profit_retention"] is not None
    ]

    summary = {
        "baseline_total_net_profit": baseline_metrics["total_net_profit"],
        "baseline_profit_factor": baseline_metrics["profit_factor"],
        "baseline_expected_payoff": baseline_metrics["expected_payoff"],
        "baseline_max_drawdown_pct": baseline_metrics["max_drawdown_pct"],
        "baseline_total_trades": int(round(baseline_metrics["total_trades"])),
        "parameter_scenario_count": len(parameter_rows),
        "parameter_positive_net_ratio": sum(
            1 for row in parameter_rows if row["metrics"]["total_net_profit"] > 0
        ) / len(parameter_rows),
        "parameter_positive_expectancy_ratio": sum(
            1 for row in parameter_rows if row["metrics"]["expected_payoff"] > 0
        ) / len(parameter_rows),
        "parameter_min_profit_factor": min(parameter_pfs),
        "parameter_median_profit_factor": statistics.median(parameter_pfs),
        "parameter_max_drawdown_pct": max(parameter_dd),
        "parameter_min_net_profit_retention": min(parameter_retentions) if parameter_retentions else None,
        "broker_count": len(broker_rows),
        "broker_positive_net_ratio": sum(
            1 for row in broker_rows if row["metrics"]["total_net_profit"] > 0
        ) / len(broker_rows),
        "broker_positive_expectancy_ratio": sum(
            1 for row in broker_rows if row["metrics"]["expected_payoff"] > 0
        ) / len(broker_rows),
        "broker_min_profit_factor": min(broker_pfs),
        "broker_median_profit_factor": statistics.median(broker_pfs),
        "broker_max_drawdown_pct": max(broker_dd),
        "broker_min_net_profit_retention": min(broker_retentions) if broker_retentions else None,
        "modeled_cost_scenario_count": len(cost_rows),
        "modeled_cost_min_adjusted_net_profit": min(row["adjusted_total_net_profit"] for row in cost_rows),
        "modeled_cost_min_adjusted_expected_payoff": min(row["adjusted_expected_payoff"] for row in cost_rows),
        "modeled_cost_min_net_profit_retention": min(cost_retentions) if cost_retentions else None,
    }

    output = {
        "schema_version": 1,
        "methodology": "ROBUSTNESS_AGGREGATION_V1",
        "campaign_id": plan.get("campaign_id"),
        "plan_sha256": sha256_file(plan_path),
        "robustness_policy_sha256": plan.get("robustness_policy", {}).get("sha256"),
        "evidence_classes": {
            "parameter_stability": "EXECUTED_COUNTERFACTUAL",
            "broker_replication": "EXTERNAL_BROKER_REPLICATION",
            "cost_sensitivity": "MODELED_COST_SENSITIVITY",
        },
        "modeled_cost_warning": (
            "Cost sensitivity is an accounting model derived from observed baseline metrics. "
            "It is not a MetaTrader execution counterfactual and must not be described as one."
        ),
        "baseline": {
            "experiment_id": baseline_identity.experiment_id,
            "preset_sha256": baseline_identity.preset_sha256,
            "normalized_results_sha256": sha256_file(baseline_result_path),
            "metrics": baseline_metrics,
        },
        "summary": summary,
        "parameter_scenarios": parameter_rows,
        "broker_runs": broker_rows,
        "modeled_cost_scenarios": cost_rows,
    }

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(output, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--output", default="data/research/robustness/robustness_summary.json")
    args = parser.parse_args()
    try:
        result = aggregate_robustness(args.plan, args.evidence, args.output)
    except RegistryValidationError as exc:
        parser.error(str(exc))
        return
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
