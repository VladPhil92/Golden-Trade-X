#!/usr/bin/env python3
"""Freeze all pre-observation inputs for a Golden Trade X v3.0-rc1 campaign.

An official lock is created only when the execution environment and the OOS
promotion, robustness and forward policies were approved before evidence
generation. Draft locks are allowed only through an explicit engineering flag
and can never be promoted by the rc1 gate.

The build SHA can be injected at freeze time (for example from GITHUB_SHA). This
avoids the impossible requirement for a tracked JSON file to contain the SHA of
the same commit that contains that file. The injected SHA is frozen before any
evidence is generated and becomes part of the campaign fingerprint.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

try:
    from scripts.campaign_contract import (
        candidate_universe_sha256,
        candidate_universe_snapshot,
        robustness_template_sha256,
        robustness_template_snapshot,
    )
    from scripts.execution_environment import (
        canonical_environment_sha256,
        load_execution_environment_contract,
    )
    from scripts.experiment_registry import RegistryValidationError, sha256_file
    from scripts.walk_forward_planner import generate_walk_forward_plan
except ModuleNotFoundError:
    from campaign_contract import (
        candidate_universe_sha256,
        candidate_universe_snapshot,
        robustness_template_sha256,
        robustness_template_snapshot,
    )
    from execution_environment import (
        canonical_environment_sha256,
        load_execution_environment_contract,
    )
    from experiment_registry import RegistryValidationError, sha256_file
    from walk_forward_planner import generate_walk_forward_plan

_BUILD_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_CANDIDATE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_ZERO_SHA = "0" * 40


def _load(path: str | Path) -> dict[str, Any]:
    target = Path(path).resolve()
    with target.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise RegistryValidationError(f"JSON root must be an object: {target}")
    return value


def _resolve(base: Path, raw: Any, field: str) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise RegistryValidationError(f"{field} is required")
    value = Path(raw)
    if not value.is_absolute():
        value = base / value
    value = value.resolve()
    if not value.is_file():
        raise RegistryValidationError(f"{field} not found: {value}")
    return value


def _policy_snapshot(path: Path, role: str) -> dict[str, Any]:
    policy = _load(path)
    if policy.get("schema_version") != 1:
        raise RegistryValidationError(f"{role} policy schema_version must be 1")
    policy_id = policy.get("policy_id")
    approved = policy.get("approved")
    if not isinstance(policy_id, str) or not policy_id.strip():
        raise RegistryValidationError(f"{role} policy requires policy_id")
    if not isinstance(approved, bool):
        raise RegistryValidationError(f"{role} policy approved must be true/false")
    return {
        "policy_id": policy_id.strip(),
        "approved": approved,
        "sha256": sha256_file(path),
    }


def _preset_allows_real_trading(path: Path) -> bool:
    values: list[str] = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line.startswith("InpAllowRealTrading="):
            values.append(line.split("=", 1)[1].strip().lower())
    if len(values) != 1:
        raise RegistryValidationError(
            "candidate preset must contain exactly one InpAllowRealTrading=false entry: "
            f"{path}"
        )
    if values[0] in {"false", "0"}:
        return False
    if values[0] in {"true", "1"}:
        return True
    raise RegistryValidationError(
        f"candidate preset has invalid InpAllowRealTrading value {values[0]!r}: {path}"
    )


def _candidate_universe(config_path: Path, raw: Any) -> tuple[list[dict[str, Any]], str]:
    if not isinstance(raw, list) or not raw:
        raise RegistryValidationError("candidate_universe must be a non-empty array")
    records: list[dict[str, Any]] = []
    names: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise RegistryValidationError("candidate_universe entry must be an object")
        name = item.get("name")
        if not isinstance(name, str) or not _CANDIDATE_RE.fullmatch(name):
            raise RegistryValidationError(f"invalid candidate name: {name!r}")
        if name in names:
            raise RegistryValidationError(f"duplicate candidate name: {name}")
        names.add(name)
        path = _resolve(config_path.parent, item.get("preset_path"), f"candidate {name}.preset_path")
        if _preset_allows_real_trading(path):
            raise RegistryValidationError(
                f"candidate {name} enables real trading; official validation presets must fail closed"
            )
        records.append(
            {
                "name": name,
                "preset_path": Path(str(item.get("preset_path"))).as_posix(),
                "preset_sha256": sha256_file(path),
            }
        )

    normalized = candidate_universe_snapshot(records)
    by_name = {item["name"]: item for item in records}
    ordered = [by_name[item["name"]] for item in normalized]
    return ordered, candidate_universe_sha256(normalized)


def _resolve_build_id(config: dict[str, Any], build_id_override: str | None) -> str:
    configured = config.get("build_id")
    if build_id_override is None:
        if not isinstance(configured, str) or not _BUILD_RE.fullmatch(configured):
            raise RegistryValidationError("build_id must be an exact 40-character Git SHA")
        return configured.lower()

    override = build_id_override.strip().lower()
    if not _BUILD_RE.fullmatch(override):
        raise RegistryValidationError("build_id override must be an exact 40-character Git SHA")

    if configured is not None:
        if not isinstance(configured, str) or not _BUILD_RE.fullmatch(configured):
            raise RegistryValidationError(
                "configured build_id must be a full Git SHA or be omitted when using a build override"
            )
        configured = configured.lower()
        if configured not in {_ZERO_SHA, override}:
            raise RegistryValidationError(
                "configured build_id differs from the build SHA supplied at campaign freeze"
            )
    return override


def _campaign_fingerprint(core: dict[str, Any]) -> str:
    payload = json.dumps(
        core,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def freeze_official_campaign(
    config_path: str | Path,
    output_dir: str | Path,
    *,
    allow_draft: bool = False,
    build_id_override: str | None = None,
) -> dict[str, Any]:
    config_path = Path(config_path).resolve()
    config = _load(config_path)
    base = config_path.parent

    campaign_id = config.get("campaign_id")
    if not isinstance(campaign_id, str) or not campaign_id.strip():
        raise RegistryValidationError("campaign_id is required")
    build_id = _resolve_build_id(config, build_id_override)

    candidates, universe_sha = _candidate_universe(config_path, config.get("candidate_universe"))

    environment_path = _resolve(
        base,
        config.get("execution_environment_path"),
        "execution_environment_path",
    )
    execution_environment, environment_file_sha = load_execution_environment_contract(
        environment_path
    )
    environment_canonical_sha = canonical_environment_sha256(execution_environment)

    walk_config = _resolve(base, config.get("walk_forward_config_path"), "walk_forward_config_path")
    robustness_template_path = _resolve(
        base, config.get("robustness_template_path"), "robustness_template_path"
    )
    robustness_policy_path = _resolve(
        base, config.get("robustness_policy_path"), "robustness_policy_path"
    )
    forward_policy_path = _resolve(base, config.get("forward_policy_path"), "forward_policy_path")

    robustness_template = _load(robustness_template_path)
    robustness_template_normalized = robustness_template_snapshot(robustness_template)
    robustness_policy = _policy_snapshot(robustness_policy_path, "robustness")
    forward_policy = _policy_snapshot(forward_policy_path, "forward-demo")

    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    walk_plan_path = output / "walk_forward_plan.json"
    walk_plan = generate_walk_forward_plan(walk_config, walk_plan_path)
    promotion_policy = walk_plan.get("promotion_policy")
    if not isinstance(promotion_policy, dict):
        raise RegistryValidationError("generated walk-forward plan lacks promotion policy snapshot")

    all_inputs_approved = (
        execution_environment["approved"] is True
        and walk_plan.get("status") == "READY_FOR_REGISTERED_EXECUTION"
        and promotion_policy.get("approved") is True
        and robustness_policy["approved"] is True
        and forward_policy["approved"] is True
    )
    if not all_inputs_approved and not allow_draft:
        raise RegistryValidationError(
            "official campaign freeze requires an approved execution environment and approved "
            "OOS promotion, robustness and forward-demo policies"
        )

    core = {
        "campaign_id": campaign_id.strip(),
        "build_id": build_id,
        "candidate_universe_sha256": universe_sha,
        "execution_environment_file_sha256": environment_file_sha,
        "execution_environment_sha256": environment_canonical_sha,
        "walk_forward_plan_sha256": sha256_file(walk_plan_path),
        "promotion_policy_sha256": promotion_policy.get("sha256"),
        "robustness_template_sha256": robustness_template_sha256(robustness_template),
        "robustness_policy_sha256": robustness_policy["sha256"],
        "forward_policy_sha256": forward_policy["sha256"],
    }

    manifest = {
        "schema_version": 1,
        "methodology": "OFFICIAL_VALIDATION_CAMPAIGN_FREEZE_V1",
        "campaign_id": campaign_id.strip(),
        "status": (
            "OFFICIAL_CAMPAIGN_FROZEN"
            if all_inputs_approved
            else "ENGINEERING_DRAFT_NOT_OFFICIAL"
        ),
        "decision_scope": "EVIDENCE_GENERATION_ONLY",
        "live_trading_authorized": False,
        "build_id": build_id,
        "candidate_universe": {
            "sha256": universe_sha,
            "count": len(candidates),
            "candidates": candidates,
        },
        "execution_environment": {
            "path": Path(str(config.get("execution_environment_path"))).as_posix(),
            "file_sha256": environment_file_sha,
            "canonical_sha256": environment_canonical_sha,
            "contract": execution_environment,
        },
        "walk_forward": {
            "config_path": Path(str(config.get("walk_forward_config_path"))).as_posix(),
            "config_sha256": sha256_file(walk_config),
            "plan_path": walk_plan_path.name,
            "plan_sha256": sha256_file(walk_plan_path),
            "plan_id": walk_plan.get("plan_id"),
            "promotion_policy": promotion_policy,
        },
        "robustness": {
            "template_path": Path(str(config.get("robustness_template_path"))).as_posix(),
            "template_file_sha256": sha256_file(robustness_template_path),
            "template_sha256": robustness_template_sha256(robustness_template),
            "template": robustness_template_normalized,
            "policy_path": Path(str(config.get("robustness_policy_path"))).as_posix(),
            "policy": robustness_policy,
        },
        "forward_demo": {
            "policy_path": Path(str(config.get("forward_policy_path"))).as_posix(),
            "policy": forward_policy,
        },
        "required_sequence": [
            "MT5_EXECUTION_ENVIRONMENT_ATTESTATION_V1",
            "ROLLING_IS_FROZEN_OOS",
            "OOS_PROMOTION_GATE",
            "ROBUSTNESS_V1",
            "FORWARD_DEMO_READINESS_V1",
            "FORWARD_DEMO_FIXED_WINDOW_V1",
            "FORWARD_DEMO_GATE_V1",
            "RC1_MANUAL_RELEASE_REVIEW",
        ],
        "campaign_fingerprint": _campaign_fingerprint(core),
    }

    lock_path = output / "campaign_lock.json"
    lock_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output-dir", default="data/research/official_campaign")
    parser.add_argument(
        "--allow-draft",
        action="store_true",
        help="Generate an engineering-only lock when inputs are still unapproved.",
    )
    parser.add_argument(
        "--build-id",
        help="Exact checked-out Git SHA to freeze before evidence generation.",
    )
    args = parser.parse_args()
    try:
        result = freeze_official_campaign(
            args.config,
            args.output_dir,
            allow_draft=args.allow_draft,
            build_id_override=args.build_id,
        )
    except RegistryValidationError as exc:
        parser.error(str(exc))
        return
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
