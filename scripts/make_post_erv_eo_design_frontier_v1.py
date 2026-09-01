#!/usr/bin/env python3
"""Explore the post-ERV EO voltage, energy and receiver design frontiers.

This follow-on study is deliberately separate from the audited percentage
sweep.  It extends the current-density grid below 1 A/m2, brackets the largest
remaining-duty completion that can stay below a declared terminal-voltage cap,
and runs an explicitly unrankable receiver-intervention factorial.

The primary population uses only the balanced post-ERV exhaust (R=1).  Changed
receiver humidity, extra receiver air and changed film coefficients are
diagnostics: their conditioning, pressure-drop, disposal and heat-rejection
terms are not modelled and therefore cannot support a full-system optimum.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import math
import multiprocessing as mp
import os
from pathlib import Path
import sys
import time
from types import ModuleType
from typing import Any, Iterable, Mapping, Sequence

os.environ.setdefault("MPLCONFIGDIR", "/tmp/heiq-post-erv-eo-frontier-mpl")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


SCRIPT_VERSION = "post-erv-eo-design-frontier-v1.0-2026-08-27"
ROOT = Path(__file__).resolve().parents[1]
BASE_SCRIPT = ROOT / "scripts" / "make_post_erv_full_eo_study_v1.py"
PERCENTAGE_SCRIPT = ROOT / "scripts" / "make_post_erv_eo_percentage_sweep_v1.py"
ANALYZER_SCRIPT = ROOT / "scripts" / "analyze_post_erv_inverse_design_v1.py"
DEFAULT_CONFIG = ROOT / "config" / "post_erv_eo_design_frontier_v1.json"
DEFAULT_OUTPUT = ROOT / "outputs" / "post_erv_eo_design_frontier_v1"
DEFAULT_V2_ROOT = ROOT.parent / "HeiQ_V2"

MATERIAL_KEYS = (
    "water_drag",
    "water_diffusivity_m2_s",
    "conductivity_s_m",
    "dry_thickness_um",
    "water_capacity_mol_m3_activity",
    "diffusivity_activity_exponent",
    "conductivity_activity_exponent",
    "capacity_activity_exponent",
    "series_asr_ohm_m2",
    "fixed_loss_voltage_v",
)

_RECEIVER_ANALYZER: ModuleType | None = None
_RECEIVER_RUNTIME: dict[str, Any] | None = None
_RECEIVER_AREA_CAP_M2: float = math.nan
_RECEIVER_AREA_STEP_M2: float = math.nan


class StudyError(RuntimeError):
    """Raised when a fail-closed study or provenance check is violated."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--v2-root", type=Path, default=DEFAULT_V2_ROOT)
    parser.add_argument("--jobs", type=int, default=min(8, os.cpu_count() or 1))
    parser.add_argument(
        "--smoke", action="store_true", help="Run the reduced declared smoke grid."
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow replacement of named artifacts in a non-empty output directory.",
    )
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise StudyError(f"Could not load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def resolve_path(value: str | Path, *, root: Path = ROOT) -> Path:
    path = Path(value).expanduser()
    return (path if path.is_absolute() else root / path).resolve()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def token(value: float, digits: int = 9) -> str:
    text = f"{float(value):.{digits}f}".rstrip("0").rstrip(".")
    return text.replace("-", "m").replace(".", "p")


def finite_max_abs(series: pd.Series) -> float | None:
    values = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    return float(values.abs().max()) if not values.empty else None


def bools(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series.fillna(False)
    if pd.api.types.is_numeric_dtype(series):
        return series.fillna(0).astype(float).ne(0.0)
    return series.astype(str).str.strip().str.lower().isin({"true", "1", "yes", "y"})


def effective_config(frontier: Mapping[str, Any], base_config: Mapping[str, Any]) -> dict[str, Any]:
    config = copy.deepcopy(dict(base_config))
    config["study_id"] = str(frontier["study_id"])
    primary = frontier["primary_transport"]
    sweep = config["transport_sweep"]
    sweep["water_diffusivity_m2_s"] = [float(x) for x in primary["water_diffusivity_m2_s"]]
    sweep["uniform_current_density_a_m2"] = [
        float(x) for x in primary["uniform_current_density_a_m2"]
    ]
    sweep["receiver_to_process_dry_air_ratio"] = [
        float(primary["receiver_to_process_dry_air_ratio"])
    ]
    sweep["area_observation_cap_m2"] = float(primary["area_observation_cap_m2"])
    sweep["area_step_m2"] = float(primary["area_step_m2"])
    sweep["maximum_receiver_surface_activity"] = float(
        primary["maximum_receiver_surface_activity"]
    )
    sweep["step_halving_relative_area_tolerance"] = float(
        frontier["convergence"]["area_step_halving_relative_tolerance"]
    )
    sweep["receiver_and_sink_sec_kwh_per_kg"] = [
        float(x) for x in frontier["receiver_and_sink_sec_scenarios_kwh_per_kg"]
    ]
    sweep["terminal_voltage_cap_sensitivity_v"] = [
        float(x) for x in frontier["terminal_voltage_scenarios_v"]
    ]
    sweep["receiver_capacity_sweep_target_ids"] = []
    config["targets"] = []
    config["claim_policy"]["full_system_claim_allowed"] = False
    return config


def validate_parent(frontier: Mapping[str, Any]) -> dict[str, Any]:
    parent_output = resolve_path(frontier["parent_percentage_output"])
    parent_config_path = resolve_path(frontier["parent_percentage_config"])
    base_config_path = resolve_path(frontier["base_study_config"])
    required = {
        "audit": parent_output / "audit.json",
        "contract": parent_output / "transport_contract.json",
        "transport": parent_output / "transport_cases.csv",
        "summary": parent_output / "percentage_summary.csv",
    }
    missing = [str(path) for path in required.values() if not path.is_file()]
    if missing:
        raise StudyError("Parent percentage study is incomplete: " + ", ".join(missing))
    audit = read_json(required["audit"])
    contract = read_json(required["contract"])
    checks = {
        "parent_audit_pass": audit.get("pass") is True,
        "parent_study_id_matches": audit.get("study_id")
        == read_json(parent_config_path).get("study_id"),
        "parent_config_hash_matches": contract.get("percentage_config_sha256")
        == sha256_file(parent_config_path),
        "parent_generator_hash_matches": contract.get("percentage_generator_sha256")
        == sha256_file(PERCENTAGE_SCRIPT),
        "base_config_hash_matches": contract.get("base_config_sha256")
        == sha256_file(base_config_path),
        "base_generator_hash_matches": contract.get("base_generator_sha256")
        == sha256_file(BASE_SCRIPT),
        "analyzer_hash_matches": contract.get("transport_analyzer_sha256")
        == sha256_file(ANALYZER_SCRIPT),
        "parent_transport_hash_matches": contract.get("transport_csv", {}).get("sha256")
        == sha256_file(required["transport"]),
        "parent_full_system_claim_disabled": contract.get("full_system_claim_allowed") is False,
    }
    if not all(checks.values()):
        failed = [name for name, passed in checks.items() if not passed]
        raise StudyError("Parent percentage provenance check failed: " + ", ".join(failed))
    return {
        "checks": checks,
        "files": {
            name: {"path": str(path), "sha256": sha256_file(path)}
            for name, path in required.items()
        },
        "parent_study_id": str(audit["study_id"]),
    }


def build_source_snapshot(
    runtime: Mapping[str, Any],
    frontier_config_path: Path,
    base_config_path: Path,
    percentage_config_path: Path,
    source_config_path: Path,
    parent: Mapping[str, Any],
) -> dict[str, Any]:
    runtime_inputs: dict[str, dict[str, str]] = {}
    paths = runtime.get("paths")
    if paths is not None:
        for name, value in vars(paths).items():
            if name == "v2_root":
                continue
            path = Path(value).expanduser().resolve()
            if not path.is_file():
                raise StudyError(f"Runtime input disappeared: {path}")
            runtime_inputs[str(name)] = {"path": str(path), "sha256": sha256_file(path)}
    return {
        "frontier_generator_sha256": sha256_file(Path(__file__).resolve()),
        "frontier_config_sha256": sha256_file(frontier_config_path),
        "percentage_generator_sha256": sha256_file(PERCENTAGE_SCRIPT),
        "percentage_config_sha256": sha256_file(percentage_config_path),
        "base_generator_sha256": sha256_file(BASE_SCRIPT),
        "base_config_sha256": sha256_file(base_config_path),
        "transport_analyzer_sha256": sha256_file(ANALYZER_SCRIPT),
        "source_operating_region_config_sha256": sha256_file(source_config_path),
        "transport_source_hashes": dict(runtime["source_hashes"]),
        "runtime_inputs": runtime_inputs,
        "parent_percentage": copy.deepcopy(dict(parent)),
    }


def unique_sorted(values: Iterable[float], *, tolerance: float = 1.0e-9) -> list[float]:
    result: list[float] = []
    for value in sorted(float(x) for x in values):
        if not math.isfinite(value):
            raise StudyError("Completion coordinates must be finite")
        if not result or not math.isclose(value, result[-1], rel_tol=0.0, abs_tol=tolerance):
            result.append(value)
    return result


def target_from_completion(
    completion: float,
    runtime: Mapping[str, Any],
    frontier: Mapping[str, Any],
    *,
    population: str,
) -> dict[str, Any]:
    inlet_w = float(runtime["process_in"].w)
    supply_w = float(runtime["baseline"].remaining_ac.supply.w)
    if not 0.0 < completion < 100.0:
        raise StudyError(f"Focus completion must lie strictly inside (0,100): {completion}")
    target_w = inlet_w - completion / 100.0 * (inlet_w - supply_w)
    target_id = f"completion_{token(completion)}pct"
    label = f"{completion:g}% of remaining post-ERV duty"
    for special in frontier["special_completion_coordinates"]:
        if math.isclose(
            completion,
            float(special["remaining_duty_completion_pct"]),
            rel_tol=0.0,
            abs_tol=1.0e-9,
        ):
            target_id = str(special["target_id"])
            label = str(special["label"])
            configured_w = float(special["humidity_ratio_kg_kg_da"])
            if not math.isclose(target_w, configured_w, rel_tol=0.0, abs_tol=1.0e-12):
                raise StudyError(f"Special target humidity identity failed for {target_id}")
            target_w = configured_w
            break
    water = float(runtime["dry_air_mass_flow_kg_s"]) * (inlet_w - target_w) * 3600.0
    historical = 100.0 * (inlet_w - target_w) / inlet_w
    return {
        "target_id": target_id,
        "target_label": label,
        "target_definition": "EO completion of finite post-ERV-to-supply humidity-ratio duty",
        "target_w_kg_kg_da": target_w,
        "target_w_g_kg_da": 1000.0 * target_w,
        "remaining_duty_completion_pct": completion,
        "historical_relative_reduction_pct": historical,
        "eo_water_removal_kg_h": water,
        "target_population": population,
        "is_o30_bridge": target_id == "o30",
        "requires_post_erv_eo": True,
        "full_system_claim_allowed": False,
    }


def make_targets(
    runtime: Mapping[str, Any], frontier: Mapping[str, Any], *, smoke: bool
) -> pd.DataFrame:
    key = "coarse_remaining_duty_completion_pct"
    values = frontier["smoke"][key] if smoke else frontier[key]
    rows = [
        target_from_completion(float(value), runtime, frontier, population="coarse")
        for value in unique_sorted(values)
    ]
    frame = pd.DataFrame(rows).sort_values("remaining_duty_completion_pct", ignore_index=True)
    if frame["target_id"].duplicated().any():
        raise StudyError("Target IDs are not unique")
    return frame


def primary_axes(frontier: Mapping[str, Any], *, smoke: bool) -> tuple[list[float], list[float]]:
    if smoke:
        return (
            [float(x) for x in frontier["smoke"]["water_diffusivity_m2_s"]],
            [float(x) for x in frontier["smoke"]["uniform_current_density_a_m2"]],
        )
    primary = frontier["primary_transport"]
    return (
        [float(x) for x in primary["water_diffusivity_m2_s"]],
        [float(x) for x in primary["uniform_current_density_a_m2"]],
    )


def build_primary_design(
    targets: pd.DataFrame, frontier: Mapping[str, Any], *, smoke: bool
) -> pd.DataFrame:
    diffusivities, currents = primary_axes(frontier, smoke=smoke)
    receiver_ratio = float(frontier["primary_transport"]["receiver_to_process_dry_air_ratio"])
    rows: list[dict[str, Any]] = []
    for target in targets.to_dict("records"):
        for diffusivity in diffusivities:
            for current in currents:
                rows.append(
                    {
                        "case_id": (
                            f"primary__{target['target_id']}__D{diffusivity:.6e}"
                            f"__j{current:g}__R{receiver_ratio:g}"
                        ),
                        "target_id": str(target["target_id"]),
                        "target_w_g_kg_da": float(target["target_w_g_kg_da"]),
                        "remaining_duty_completion_pct": float(
                            target["remaining_duty_completion_pct"]
                        ),
                        "water_diffusivity_m2_s": diffusivity,
                        "uniform_current_density_a_m2": current,
                        "receiver_to_process_dry_air_ratio": receiver_ratio,
                        "design_population": (
                            "balanced_primary_adaptive"
                            if str(target["target_population"]) == "adaptive"
                            else "balanced_primary_coarse"
                        ),
                    }
                )
    frame = pd.DataFrame(rows)
    if not frame.empty and frame["case_id"].duplicated().any():
        raise StudyError("Primary design contains duplicate case IDs")
    return frame


def enrich_transport(
    frame: pd.DataFrame,
    target: Mapping[str, Any],
    frontier: Mapping[str, Any],
    *,
    intervention: bool,
) -> pd.DataFrame:
    output = frame.copy()
    for key in (
        "target_id",
        "target_label",
        "target_definition",
        "target_w_kg_kg_da",
        "target_w_g_kg_da",
        "remaining_duty_completion_pct",
        "historical_relative_reduction_pct",
        "is_o30_bridge",
    ):
        output[key] = target[key]
    water = pd.to_numeric(output["incremental_water_removal_target_kg_h"], errors="coerce")
    addon = pd.to_numeric(output["incremental_eo_and_fan_power_kw"], errors="coerce")
    saving = pd.to_numeric(output["incremental_saving_kw_vs_passive_erv"], errors="coerce")
    output["known_eo_core_and_module_fan_sec_kwh_per_kg"] = addon / water
    output["control_regime_conservative_saving_kw_before_receiver_sink"] = saving
    output["control_regime_conservative_receiver_sink_sec_budget_kwh_per_kg"] = (
        saving / water
    )
    maximum_activity = float(frontier["primary_transport"]["maximum_receiver_surface_activity"])
    output["receiver_surface_activity_gate_pass"] = pd.to_numeric(
        output["maximum_receiver_surface_activity"], errors="coerce"
    ).le(maximum_activity)
    output["declared_transport_screen_pass"] = bools(output["transport_gate_pass"]) & bools(
        output["receiver_surface_activity_gate_pass"]
    )
    output["positive_surface_direction_screen_pass"] = bools(
        output["declared_transport_screen_pass"]
    ) & bools(output["positive_surface_direction_everywhere"])
    ratio = pd.to_numeric(output["receiver_to_process_dry_air_ratio"], errors="coerce")
    output["available_post_erv_exhaust_to_process_ratio"] = 1.0
    output["external_receiver_source_required_to_process_ratio"] = (ratio - 1.0).clip(lower=0.0)
    output["receiver_resource_feasible_without_external_source"] = ratio.le(1.0 + 1.0e-12)
    output["external_receiver_source_energy_modelled"] = False
    output["receiver_capacity_related_fan_and_manifold_energy_modelled"] = False
    output["receiver_capacity_axis_is_energy_rankable"] = not intervention
    output["receiver_intervention_energy_rankable"] = False if intervention else True
    output["full_system_claim_allowed"] = False
    output["model_boundary"] = (
        "passive ERV outlet -> finite-film EO -> remaining AC; receiver conditioning/sink open"
    )
    voltage_min = pd.to_numeric(
        output["minimum_required_terminal_voltage_signed_v"], errors="coerce"
    )
    voltage_max = pd.to_numeric(
        output["maximum_required_terminal_voltage_signed_v"], errors="coerce"
    )
    voltage_resolved = pd.Series(
        np.isfinite(voltage_min.to_numpy(float))
        & np.isfinite(voltage_max.to_numpy(float)),
        index=output.index,
    ) & voltage_min.le(voltage_max)
    output["electrical_regime"] = np.select(
        [
            ~voltage_resolved,
            voltage_max.lt(0.0),
            voltage_min.lt(0.0) & voltage_max.ge(0.0),
        ],
        [
            "unresolved_voltage",
            "negative_voltage_everywhere",
            "mixed_voltage_sign",
        ],
        default="nonnegative_voltage_everywhere",
    )
    output["ordinary_nonnegative_import_voltage_everywhere"] = (
        voltage_resolved & voltage_min.ge(0.0)
    )
    return output


def evaluate_primary_targets(
    analyzer: ModuleType,
    runtime: Mapping[str, Any],
    targets: pd.DataFrame,
    frontier: Mapping[str, Any],
    *,
    jobs: int,
    smoke: bool,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    design = build_primary_design(targets, frontier, smoke=smoke)
    if design.empty:
        return design, pd.DataFrame()
    frames: list[pd.DataFrame] = []
    target_lookup = targets.set_index("target_id")
    primary = frontier["primary_transport"]
    for target_id, group in design.groupby("target_id", sort=False):
        target = target_lookup.loc[str(target_id)].to_dict()
        target["target_id"] = str(target_id)
        local_runtime = dict(runtime)
        local_runtime["target_w"] = float(target["target_w_kg_kg_da"])
        local_runtime["area_limit_m2"] = float(primary["area_observation_cap_m2"])
        local_runtime["area_step_m2"] = float(primary["area_step_m2"])
        cases: list[dict[str, Any]] = []
        for row in group.to_dict("records"):
            case = analyzer.base_case_material(runtime["anchor"])
            case.update(
                {
                    "study_family": "post_erv_eo_design_frontier_primary",
                    "case_id": str(row["case_id"]),
                    "water_diffusivity_m2_s": float(row["water_diffusivity_m2_s"]),
                    "uniform_current_density_a_m2": float(row["uniform_current_density_a_m2"]),
                    "receiver_to_process_dry_air_ratio": float(
                        row["receiver_to_process_dry_air_ratio"]
                    ),
                    "design_population": str(row["design_population"]),
                }
            )
            cases.append(case)
        calculated = analyzer.evaluate_cases(
            local_runtime,
            cases,
            jobs=max(1, jobs),
            label=f"frontier-{target_id}",
        )
        frames.append(enrich_transport(calculated, target, frontier, intervention=False))
    transport = pd.concat(frames, ignore_index=True)
    transport = transport.sort_values("case_id", ignore_index=True)
    return design.sort_values("case_id", ignore_index=True), transport


def primary_candidates(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    finite_area = np.isfinite(pd.to_numeric(frame["required_active_area_m2"], errors="coerce"))
    balanced = np.isclose(
        pd.to_numeric(frame["receiver_to_process_dry_air_ratio"], errors="coerce"),
        1.0,
        rtol=0.0,
        atol=1.0e-12,
    )
    return frame.loc[
        bools(frame["target_reached"])
        & bools(frame["declared_transport_screen_pass"])
        & bools(frame["receiver_resource_feasible_without_external_source"])
        & ~bools(frame["area_is_right_censored"])
        & finite_area
        & balanced
    ].copy()


def select_primary_cases(transport: pd.DataFrame, voltage_limit: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    status_rows: list[dict[str, Any]] = []
    for target_id, group in transport.groupby("target_id", sort=False):
        candidates = primary_candidates(group)
        under = candidates.loc[
            pd.to_numeric(candidates["maximum_required_terminal_voltage_signed_v"], errors="coerce")
            <= voltage_limit + 1.0e-12
        ].copy()
        status_rows.append(
            {
                "target_id": str(target_id),
                "remaining_duty_completion_pct": float(
                    group.iloc[0]["remaining_duty_completion_pct"]
                ),
                "case_count": len(group),
                "target_reached_count": int(bools(group["target_reached"]).sum()),
                "declared_balanced_candidate_count": len(candidates),
                "one_volt_candidate_count": len(under),
                "one_volt_feasible": not under.empty,
                "positive_surface_direction_count": int(
                    bools(group["positive_surface_direction_screen_pass"]).sum()
                ),
                "full_system_claim_allowed": False,
            }
        )
        choices: list[tuple[str, pd.Series]] = []
        if not candidates.empty:
            choices.extend(
                [
                    (
                        "best_conditional_saving",
                        candidates.sort_values(
                            ["incremental_saving_kw_vs_passive_erv", "required_active_area_m2"],
                            ascending=[False, True],
                        ).iloc[0],
                    ),
                    (
                        "minimum_voltage",
                        candidates.sort_values(
                            ["maximum_required_terminal_voltage_signed_v", "incremental_saving_kw_vs_passive_erv"],
                            ascending=[True, False],
                        ).iloc[0],
                    ),
                ]
            )
        if not under.empty:
            choices.append(
                (
                    "best_under_1v",
                    under.sort_values(
                        ["incremental_saving_kw_vs_passive_erv", "required_active_area_m2"],
                        ascending=[False, True],
                    ).iloc[0],
                )
            )
        for selection, chosen in choices:
            record = chosen.to_dict()
            record["selection"] = selection
            record["selection_population"] = "balanced_declared_gate_target_reached_only"
            record["selection_has_no_failed_case_fallback"] = True
            rows.append(record)
    selected = pd.DataFrame(rows)
    status = pd.DataFrame(status_rows).sort_values(
        "remaining_duty_completion_pct", ignore_index=True
    )
    return selected, status


def find_one_volt_bracket(status: pd.DataFrame) -> tuple[str, float, float]:
    ordered = status.sort_values("remaining_duty_completion_pct")
    feasible = ordered.loc[bools(ordered["one_volt_feasible"])]
    if feasible.empty:
        return "already_failed_at_lower_bound", math.nan, float(ordered.iloc[0]["remaining_duty_completion_pct"])
    lower = float(feasible.iloc[-1]["remaining_duty_completion_pct"])
    upper_rows = ordered.loc[
        (ordered["remaining_duty_completion_pct"] > lower)
        & ~bools(ordered["one_volt_feasible"])
    ]
    if upper_rows.empty:
        return "not_reached_by_upper_bound", lower, math.nan
    return "bracketed_crossing", lower, float(upper_rows.iloc[0]["remaining_duty_completion_pct"])


def adaptive_frontier(
    analyzer: ModuleType,
    runtime: Mapping[str, Any],
    frontier: Mapping[str, Any],
    targets: pd.DataFrame,
    design: pd.DataFrame,
    transport: pd.DataFrame,
    *,
    jobs: int,
    smoke: bool,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    limit = float(frontier["primary_transport"]["terminal_voltage_limit_v"])
    _, status = select_primary_cases(transport, limit)
    bracket_status, lower, upper = find_one_volt_bracket(status)
    max_iterations = int(
        frontier["smoke"]["adaptive_maximum_iterations"]
        if smoke
        else frontier["adaptive_one_volt_frontier"]["maximum_iterations"]
    )
    tolerance = float(
        frontier["adaptive_one_volt_frontier"]["completion_tolerance_percentage_point"]
    )
    trace: list[dict[str, Any]] = []
    if bracket_status != "bracketed_crossing":
        trace.append(
            {
                "iteration": 0,
                "status": bracket_status,
                "lower_feasible_completion_pct": lower,
                "upper_infeasible_completion_pct": upper,
                "bracket_width_percentage_point": (
                    upper - lower if math.isfinite(lower) and math.isfinite(upper) else math.nan
                ),
                "midpoint_completion_pct": math.nan,
                "midpoint_one_volt_feasible": False,
            }
        )
        return targets, design, transport, pd.DataFrame(trace)
    for iteration in range(1, max_iterations + 1):
        width = upper - lower
        if width <= tolerance:
            break
        midpoint = 0.5 * (lower + upper)
        target = target_from_completion(midpoint, runtime, frontier, population="adaptive")
        midpoint_rows = targets.loc[
            np.isclose(
                targets["remaining_duty_completion_pct"], midpoint, rtol=0.0, atol=1.0e-10
            )
        ]
        if midpoint_rows.empty:
            new_targets = pd.DataFrame([target])
            new_design, new_transport = evaluate_primary_targets(
                analyzer,
                runtime,
                new_targets,
                frontier,
                jobs=jobs,
                smoke=smoke,
            )
            targets = pd.concat([targets, new_targets], ignore_index=True).sort_values(
                "remaining_duty_completion_pct", ignore_index=True
            )
            design = pd.concat([design, new_design], ignore_index=True).sort_values(
                "case_id", ignore_index=True
            )
            transport = pd.concat([transport, new_transport], ignore_index=True).sort_values(
                "case_id", ignore_index=True
            )
            midpoint_group = new_transport
        else:
            midpoint_id = str(midpoint_rows.iloc[0]["target_id"])
            midpoint_group = transport.loc[transport["target_id"].eq(midpoint_id)]
        feasible = not primary_candidates(midpoint_group).loc[
            pd.to_numeric(
                primary_candidates(midpoint_group)["maximum_required_terminal_voltage_signed_v"],
                errors="coerce",
            )
            <= limit + 1.0e-12
        ].empty
        if feasible:
            lower = midpoint
        else:
            upper = midpoint
        trace.append(
            {
                "iteration": iteration,
                "status": "refined" if upper - lower > tolerance else "tolerance_reached",
                "lower_feasible_completion_pct": lower,
                "upper_infeasible_completion_pct": upper,
                "bracket_width_percentage_point": upper - lower,
                "midpoint_completion_pct": midpoint,
                "midpoint_one_volt_feasible": feasible,
            }
        )
    if not trace or trace[-1]["lower_feasible_completion_pct"] != lower or trace[-1]["upper_infeasible_completion_pct"] != upper:
        trace.append(
            {
                "iteration": len(trace),
                "status": "tolerance_reached" if upper - lower <= tolerance else "maximum_iterations_reached",
                "lower_feasible_completion_pct": lower,
                "upper_infeasible_completion_pct": upper,
                "bracket_width_percentage_point": upper - lower,
                "midpoint_completion_pct": math.nan,
                "midpoint_one_volt_feasible": False,
            }
        )
    elif trace:
        trace[-1]["status"] = (
            "tolerance_reached" if upper - lower <= tolerance else "maximum_iterations_reached"
        )
    return targets, design, transport, pd.DataFrame(trace)


def receiver_axes(
    runtime: Mapping[str, Any], frontier: Mapping[str, Any], *, smoke: bool
) -> tuple[list[float], list[float], list[float], list[float]]:
    section = frontier["receiver_intervention"]
    baseline_rh = float(runtime["receiver_in"].rh)
    if smoke:
        smoke_cfg = frontier["smoke"]
        completions = [float(x) for x in smoke_cfg["receiver_target_completion_pct"]]
        ratios = [float(x) for x in smoke_cfg["receiver_to_process_dry_air_ratio"]]
        rh_values = [float(x) for x in smoke_cfg["receiver_inlet_rh"]]
        include_baseline = bool(smoke_cfg["include_baseline_receiver_inlet_rh"])
        films = [float(x) for x in smoke_cfg["receiver_film_multiplier"]]
    else:
        completions = [float(x) for x in section["target_completion_pct"]]
        ratios = [float(x) for x in section["receiver_to_process_dry_air_ratio"]]
        rh_values = [float(x) for x in section["receiver_inlet_rh"]]
        include_baseline = bool(section["include_baseline_receiver_inlet_rh"])
        films = [float(x) for x in section["receiver_film_multiplier"]]
    if include_baseline:
        rh_values.append(baseline_rh)
    return (
        unique_sorted(completions),
        unique_sorted(ratios),
        unique_sorted(rh_values),
        unique_sorted(films),
    )


def build_receiver_design(
    runtime: Mapping[str, Any], frontier: Mapping[str, Any], *, smoke: bool
) -> pd.DataFrame:
    completions, ratios, rh_values, films = receiver_axes(runtime, frontier, smoke=smoke)
    section = frontier["receiver_intervention"]
    diffusivity = float(section["water_diffusivity_m2_s"])
    current = float(section["uniform_current_density_a_m2"])
    baseline_rh = float(runtime["receiver_in"].rh)
    rows: list[dict[str, Any]] = []
    for completion in completions:
        target = target_from_completion(completion, runtime, frontier, population="receiver_intervention")
        for ratio in ratios:
            for rh in rh_values:
                for film in films:
                    rows.append(
                        {
                            "case_id": (
                                f"receiver__{target['target_id']}__D{diffusivity:.6e}__j{current:g}"
                                f"__R{ratio:g}__rh{token(rh, 12)}__k{film:g}"
                            ),
                            "target_id": target["target_id"],
                            "target_w_kg_kg_da": target["target_w_kg_kg_da"],
                            "target_w_g_kg_da": target["target_w_g_kg_da"],
                            "remaining_duty_completion_pct": completion,
                            "water_diffusivity_m2_s": diffusivity,
                            "uniform_current_density_a_m2": current,
                            "receiver_to_process_dry_air_ratio": ratio,
                            "receiver_inlet_rh": rh,
                            "receiver_inlet_is_erv_baseline": math.isclose(
                                rh, baseline_rh, rel_tol=0.0, abs_tol=1.0e-12
                            ),
                            "receiver_film_multiplier": film,
                            "design_population": "receiver_intervention_unrankable",
                        }
                    )
    design = pd.DataFrame(rows).sort_values("case_id", ignore_index=True)
    if design["case_id"].duplicated().any():
        raise StudyError("Receiver design contains duplicate case IDs")
    return design


def _receiver_worker(payload: Mapping[str, Any]) -> dict[str, Any]:
    if _RECEIVER_ANALYZER is None or _RECEIVER_RUNTIME is None:
        raise StudyError("Receiver worker was not initialized")
    row = dict(payload)
    runtime = dict(_RECEIVER_RUNTIME)
    runtime["target_w"] = float(row["target_w_kg_kg_da"])
    runtime["area_limit_m2"] = _RECEIVER_AREA_CAP_M2
    runtime["area_step_m2"] = _RECEIVER_AREA_STEP_M2
    baseline_receiver = _RECEIVER_RUNTIME["receiver_in"]
    runtime["receiver_in"] = runtime["system_core"].state_from_t_rh(
        float(baseline_receiver.t_c),
        float(row["receiver_inlet_rh"]),
        float(runtime["pressure_pa"]),
        "receiver intervention inlet",
    )
    runtime["receiver_film_coefficient"] = float(
        _RECEIVER_RUNTIME["receiver_film_coefficient"]
    ) * float(row["receiver_film_multiplier"])
    case = _RECEIVER_ANALYZER.base_case_material(runtime["anchor"])
    case.update(
        {
            "study_family": "post_erv_eo_receiver_intervention_unrankable",
            "case_id": str(row["case_id"]),
            "target_id": str(row["target_id"]),
            "water_diffusivity_m2_s": float(row["water_diffusivity_m2_s"]),
            "uniform_current_density_a_m2": float(row["uniform_current_density_a_m2"]),
            "receiver_to_process_dry_air_ratio": float(
                row["receiver_to_process_dry_air_ratio"]
            ),
            "receiver_inlet_rh": float(row["receiver_inlet_rh"]),
            "receiver_inlet_is_erv_baseline": bool(row["receiver_inlet_is_erv_baseline"]),
            "receiver_film_multiplier": float(row["receiver_film_multiplier"]),
            "design_population": str(row["design_population"]),
        }
    )
    return _RECEIVER_ANALYZER.integrate_case(runtime, case)


def evaluate_receiver_design(
    analyzer: ModuleType,
    runtime: Mapping[str, Any],
    frontier: Mapping[str, Any],
    design: pd.DataFrame,
    *,
    jobs: int,
) -> pd.DataFrame:
    global _RECEIVER_ANALYZER, _RECEIVER_RUNTIME, _RECEIVER_AREA_CAP_M2, _RECEIVER_AREA_STEP_M2
    _RECEIVER_ANALYZER = analyzer
    _RECEIVER_RUNTIME = dict(runtime)
    _RECEIVER_AREA_CAP_M2 = float(frontier["primary_transport"]["area_observation_cap_m2"])
    _RECEIVER_AREA_STEP_M2 = float(frontier["primary_transport"]["area_step_m2"])
    started = time.perf_counter()
    rows: list[dict[str, Any]] = []
    payloads = design.to_dict("records")
    if jobs <= 1:
        iterator: Iterable[dict[str, Any]] = (_receiver_worker(row) for row in payloads)
        pool = None
    else:
        pool = mp.get_context("fork").Pool(processes=jobs)
        iterator = pool.imap_unordered(_receiver_worker, payloads, chunksize=1)
    try:
        for index, result in enumerate(iterator, start=1):
            rows.append(result)
            if index == 1 or index % 50 == 0 or index == len(payloads):
                elapsed = time.perf_counter() - started
                rate = index / max(elapsed, 1.0e-9)
                print(
                    f"[receiver-intervention] {index}/{len(payloads)}; {rate:.2f} case/s; "
                    f"ETA {(len(payloads) - index) / max(rate, 1.0e-9) / 60.0:.1f} min",
                    flush=True,
                )
    finally:
        if pool is not None:
            pool.close()
            pool.join()
    calculated = pd.DataFrame(rows).sort_values("case_id", ignore_index=True)
    target_lookup = {
        row["target_id"]: row
        for row in (
            target_from_completion(float(p), runtime, frontier, population="receiver_intervention")
            for p in unique_sorted(design["remaining_duty_completion_pct"])
        )
    }
    frames: list[pd.DataFrame] = []
    for target_id, group in calculated.groupby("target_id", sort=False):
        # integrate_case does not know the target id; recover it from the design case id.
        matching = design.loc[design["case_id"].isin(group["case_id"])]
        actual_target_id = str(matching.iloc[0]["target_id"])
        enriched = enrich_transport(group, target_lookup[actual_target_id], frontier, intervention=True)
        frames.append(enriched)
    # Scenario coordinates were carried through ``case`` by integrate_case;
    # retaining those columns also audits worker metadata round-tripping.
    output = pd.concat(frames, ignore_index=True).sort_values("case_id", ignore_index=True)
    baseline_rh = float(runtime["receiver_in"].rh)
    output["receiver_inlet_conditioning_required"] = ~np.isclose(
        pd.to_numeric(output["receiver_inlet_rh"], errors="coerce"),
        baseline_rh,
        rtol=0.0,
        atol=1.0e-12,
    )
    output["receiver_inlet_conditioning_energy_modelled"] = False
    output["receiver_film_change_energy_modelled"] = False
    output["receiver_intervention_energy_rankable"] = False
    output["receiver_capacity_axis_is_energy_rankable"] = False
    output["full_system_claim_allowed"] = False
    return output


def classify_threshold(
    x: Sequence[float], y: Sequence[float], *, threshold: float = 0.0
) -> dict[str, Any]:
    pairs = sorted(
        (float(a), float(b))
        for a, b in zip(x, y)
        if math.isfinite(float(a)) and math.isfinite(float(b))
    )
    if len(pairs) < 2:
        return {"status": "invalid_or_missing_data", "threshold_x": math.nan, "lower_x": math.nan, "upper_x": math.nan}
    for x_value, y_value in pairs:
        if math.isclose(y_value, threshold, rel_tol=0.0, abs_tol=1.0e-12):
            return {"status": "exact_grid_crossing", "threshold_x": x_value, "lower_x": x_value, "upper_x": x_value}
    for (x0, y0), (x1, y1) in zip(pairs[:-1], pairs[1:]):
        if (y0 - threshold) * (y1 - threshold) < 0.0:
            crossing = x0 + (threshold - y0) * (x1 - x0) / (y1 - y0)
            return {"status": "bracketed_crossing", "threshold_x": crossing, "lower_x": x0, "upper_x": x1}
    if pairs[0][1] < threshold:
        status = "already_failed_at_lower_bound"
    else:
        status = "not_reached_by_upper_bound"
    return {"status": status, "threshold_x": math.nan, "lower_x": pairs[0][0], "upper_x": pairs[-1][0]}


def receiver_strategy_tables(
    receiver: pd.DataFrame, runtime: Mapping[str, Any]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if receiver.empty:
        return pd.DataFrame(), pd.DataFrame()
    baseline_rh = float(runtime["receiver_in"].rh)
    ratio = pd.to_numeric(receiver["receiver_to_process_dry_air_ratio"], errors="coerce")
    rh = pd.to_numeric(receiver["receiver_inlet_rh"], errors="coerce")
    film = pd.to_numeric(receiver["receiver_film_multiplier"], errors="coerce")
    base_r = np.isclose(ratio, 1.0, rtol=0.0, atol=1.0e-12)
    base_rh = np.isclose(rh, baseline_rh, rtol=0.0, atol=1.0e-12)
    base_film = np.isclose(film, 1.0, rtol=0.0, atol=1.0e-12)
    receiver = receiver.copy()
    receiver["receiver_strategy_family"] = np.select(
        [
            base_r & base_rh & base_film,
            ~base_r & base_rh & base_film,
            base_r & ~base_rh & base_film,
            base_r & base_rh & ~base_film,
        ],
        ["baseline", "airflow_only", "drying_only", "film_only"],
        default="combined_factorial",
    )
    rows: list[dict[str, Any]] = []
    for (target_id, family), group in receiver.groupby(
        ["target_id", "receiver_strategy_family"], sort=False
    ):
        margin = pd.to_numeric(group["minimum_surface_activity_margin"], errors="coerce")
        rows.append(
            {
                "target_id": str(target_id),
                "remaining_duty_completion_pct": float(group.iloc[0]["remaining_duty_completion_pct"]),
                "receiver_strategy_family": str(family),
                "case_count": len(group),
                "target_reached_count": int(bools(group["target_reached"]).sum()),
                "declared_gate_pass_count": int(bools(group["declared_transport_screen_pass"]).sum()),
                "positive_surface_direction_count": int(
                    bools(group["positive_surface_direction_screen_pass"]).sum()
                ),
                "maximum_minimum_surface_activity_margin": (
                    float(margin.max()) if np.isfinite(margin).any() else math.nan
                ),
                "any_positive_surface_direction": bool(
                    bools(group["positive_surface_direction_screen_pass"]).any()
                ),
                "energy_rankable": False,
                "full_system_claim_allowed": False,
            }
        )
    thresholds: list[dict[str, Any]] = []
    for (target_id, ratio_value, film_value), group in receiver.groupby(
        ["target_id", "receiver_to_process_dry_air_ratio", "receiver_film_multiplier"],
        sort=False,
    ):
        reached = group.loc[bools(group["target_reached"])].sort_values("receiver_inlet_rh")
        result = classify_threshold(
            reached["receiver_inlet_rh"].to_numpy(float),
            reached["minimum_surface_activity_margin"].to_numpy(float),
        )
        thresholds.append(
            {
                "target_id": str(target_id),
                "remaining_duty_completion_pct": float(group.iloc[0]["remaining_duty_completion_pct"]),
                "receiver_to_process_dry_air_ratio": float(ratio_value),
                "receiver_film_multiplier": float(film_value),
                "threshold_status": result["status"],
                "receiver_inlet_rh_at_zero_surface_margin": result["threshold_x"],
                "bracket_lower_receiver_inlet_rh": result["lower_x"],
                "bracket_upper_receiver_inlet_rh": result["upper_x"],
                "threshold_is_diagnostic_not_energy_rankable": True,
                "full_system_claim_allowed": False,
            }
        )
    return (
        pd.DataFrame(rows).sort_values(
            ["remaining_duty_completion_pct", "receiver_strategy_family"], ignore_index=True
        ),
        pd.DataFrame(thresholds).sort_values(
            ["remaining_duty_completion_pct", "receiver_to_process_dry_air_ratio", "receiver_film_multiplier"],
            ignore_index=True,
        ),
    )


def build_energy_scenarios(
    selected: pd.DataFrame, frontier: Mapping[str, Any]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    if not selected.empty:
        ranked = selected.loc[
            selected["selection"].isin(["best_conditional_saving", "best_under_1v"])
        ]
        for case in ranked.to_dict("records"):
            water = float(case["incremental_water_removal_target_kg_h"])
            before = float(case["control_regime_conservative_saving_kw_before_receiver_sink"])
            for sec in frontier["receiver_and_sink_sec_scenarios_kwh_per_kg"]:
                receiver_sec = float(sec)
                power = water * receiver_sec
                saving = before - power
                rows.append(
                    {
                        "case_id": case["case_id"],
                        "target_id": case["target_id"],
                        "selection": case["selection"],
                        "remaining_duty_completion_pct": case[
                            "remaining_duty_completion_pct"
                        ],
                        "receiver_and_sink_sec_kwh_per_kg": receiver_sec,
                        "receiver_and_sink_power_kw": power,
                        "saving_before_receiver_and_sink_kw": before,
                        "scenario_saving_kw_vs_erv_ac": saving,
                        "scenario_energy_positive": saving > 0.0,
                        "scenario_is_parameterized_not_validated": True,
                        "full_system_claim_allowed": False,
                    }
                )
    scenarios = pd.DataFrame(rows)
    optimum_rows: list[dict[str, Any]] = []
    if not scenarios.empty:
        for (selection, sec), group in scenarios.groupby(
            ["selection", "receiver_and_sink_sec_kwh_per_kg"], sort=False
        ):
            best = group.sort_values(
                ["scenario_saving_kw_vs_erv_ac", "remaining_duty_completion_pct"],
                ascending=[False, True],
            ).iloc[0]
            record = best.to_dict()
            record["screened_window_optimum_only"] = True
            record["validated_full_system_optimum"] = False
            optimum_rows.append(record)
    return scenarios, pd.DataFrame(optimum_rows)


def build_voltage_envelope(
    transport: pd.DataFrame, frontier: Mapping[str, Any]
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for target_id, group in transport.groupby("target_id", sort=False):
        candidates = primary_candidates(group)
        for cap in frontier["terminal_voltage_scenarios_v"]:
            cap_value = float(cap)
            feasible = candidates.loc[
                pd.to_numeric(
                    candidates["maximum_required_terminal_voltage_signed_v"], errors="coerce"
                )
                <= cap_value + 1.0e-12
            ]
            row: dict[str, Any] = {
                "target_id": str(target_id),
                "remaining_duty_completion_pct": float(
                    group.iloc[0]["remaining_duty_completion_pct"]
                ),
                "terminal_voltage_cap_v": cap_value,
                "feasible_case_count": len(feasible),
                "voltage_cap_feasible": not feasible.empty,
                "voltage_is_sensitivity_not_transport_acceptance_gate": True,
                "full_system_claim_allowed": False,
            }
            if not feasible.empty:
                best = feasible.sort_values(
                    ["incremental_saving_kw_vs_passive_erv", "required_active_area_m2"],
                    ascending=[False, True],
                ).iloc[0]
                for column in (
                    "case_id",
                    "water_diffusivity_m2_s",
                    "uniform_current_density_a_m2",
                    "required_active_area_m2",
                    "maximum_required_terminal_voltage_signed_v",
                    "incremental_saving_kw_vs_passive_erv",
                    "control_regime_conservative_receiver_sink_sec_budget_kwh_per_kg",
                    "minimum_surface_activity_margin",
                ):
                    row[f"selected_{column}"] = best[column]
            rows.append(row)
    return pd.DataFrame(rows).sort_values(
        ["terminal_voltage_cap_v", "remaining_duty_completion_pct"], ignore_index=True
    )


def build_convergence_input(
    selected: pd.DataFrame,
    targets: pd.DataFrame,
    trace: pd.DataFrame,
    frontier: Mapping[str, Any],
) -> pd.DataFrame:
    if selected.empty:
        return pd.DataFrame()
    rows: list[pd.DataFrame] = []
    representative = [float(x) for x in frontier["convergence"]["representative_completion_pct"]]
    for completion in representative:
        target_row = targets.iloc[
            int(np.argmin(np.abs(targets["remaining_duty_completion_pct"].to_numpy(float) - completion)))
        ]
        subset = selected.loc[
            selected["target_id"].eq(str(target_row["target_id"]))
            & selected["selection"].eq("best_conditional_saving")
        ]
        if not subset.empty:
            rows.append(subset)
    if not trace.empty and trace.iloc[-1]["status"] in {
        "tolerance_reached",
        "maximum_iterations_reached",
    }:
        final = trace.iloc[-1]
        for completion, selection in (
            (float(final["lower_feasible_completion_pct"]), "best_under_1v"),
            (float(final["upper_infeasible_completion_pct"]), "minimum_voltage"),
        ):
            target_row = targets.iloc[
                int(np.argmin(np.abs(targets["remaining_duty_completion_pct"].to_numpy(float) - completion)))
            ]
            subset = selected.loc[
                selected["target_id"].eq(str(target_row["target_id"]))
                & selected["selection"].eq(selection)
            ]
            if not subset.empty:
                rows.append(subset)
    if not rows:
        return pd.DataFrame()
    combined = pd.concat(rows, ignore_index=True).drop_duplicates("case_id").copy()
    combined["convergence_population"] = "declared_representative_and_frontier_boundary"
    return combined


def receiver_baseline_reproduction(
    primary: pd.DataFrame,
    receiver: pd.DataFrame,
    runtime: Mapping[str, Any],
    frontier: Mapping[str, Any],
) -> pd.DataFrame:
    section = frontier["receiver_intervention"]
    baseline_rh = float(runtime["receiver_in"].rh)
    receiver_base = receiver.loc[
        np.isclose(receiver["receiver_inlet_rh"], baseline_rh, rtol=0.0, atol=1.0e-12)
        & np.isclose(receiver["receiver_film_multiplier"], 1.0, rtol=0.0, atol=1.0e-12)
        & np.isclose(
            receiver["receiver_to_process_dry_air_ratio"], 1.0, rtol=0.0, atol=1.0e-12
        )
    ]
    primary_base = primary.loc[
        np.isclose(
            primary["water_diffusivity_m2_s"],
            float(section["water_diffusivity_m2_s"]),
            rtol=1.0e-12,
            atol=0.0,
        )
        & np.isclose(
            primary["uniform_current_density_a_m2"],
            float(section["uniform_current_density_a_m2"]),
            rtol=0.0,
            atol=1.0e-12,
        )
    ]
    fields = (
        "required_active_area_m2",
        "maximum_required_terminal_voltage_signed_v",
        "minimum_surface_activity_margin",
        "maximum_receiver_surface_activity",
        "incremental_saving_kw_vs_passive_erv",
    )
    rows: list[dict[str, Any]] = []
    for target_id, diagnostic in receiver_base.groupby("target_id", sort=False):
        reference = primary_base.loc[primary_base["target_id"].eq(str(target_id))]
        if len(diagnostic) != 1 or len(reference) != 1:
            rows.append(
                {
                    "target_id": str(target_id),
                    "comparison_available": False,
                    "maximum_relative_difference": math.inf,
                    "baseline_reproduction_pass": False,
                }
            )
            continue
        left = diagnostic.iloc[0]
        right = reference.iloc[0]
        differences: list[float] = []
        record: dict[str, Any] = {
            "target_id": str(target_id),
            "remaining_duty_completion_pct": float(left["remaining_duty_completion_pct"]),
            "comparison_available": True,
        }
        for field in fields:
            a = float(left[field])
            b = float(right[field])
            relative = abs(a - b) / max(abs(a), abs(b), 1.0e-12)
            record[f"{field}_relative_difference"] = relative
            differences.append(relative)
        record["maximum_relative_difference"] = max(differences)
        record["baseline_reproduction_pass"] = max(differences) <= float(
            frontier["audit_tolerances"]["receiver_baseline_reproduction_relative"]
        )
        rows.append(record)
    return pd.DataFrame(rows)


def canonical_design_digest(base: ModuleType, primary: pd.DataFrame, receiver: pd.DataFrame) -> str:
    columns = (
        "case_id",
        "target_id",
        "target_w_g_kg_da",
        "remaining_duty_completion_pct",
        "water_diffusivity_m2_s",
        "uniform_current_density_a_m2",
        "receiver_to_process_dry_air_ratio",
        "receiver_inlet_rh",
        "receiver_film_multiplier",
        "design_population",
    )
    combined = pd.concat(
        [primary.assign(receiver_inlet_rh=np.nan, receiver_film_multiplier=np.nan), receiver],
        ignore_index=True,
        sort=False,
    )
    records: list[dict[str, Any]] = []
    for row in combined.loc[:, columns].sort_values("case_id").to_dict("records"):
        records.append(
            {
                key: (None if isinstance(value, float) and math.isnan(value) else value)
                for key, value in row.items()
            }
        )
    return base.sha256_json(records)


def build_contract(
    base: ModuleType,
    frontier: Mapping[str, Any],
    mode: str,
    snapshot: Mapping[str, Any],
    effective: Mapping[str, Any],
    primary_design: pd.DataFrame,
    receiver_design: pd.DataFrame,
    output: Path,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "study_id": str(frontier["study_id"]),
        "mode": mode,
        "frontier_generator_version": SCRIPT_VERSION,
        "source_snapshot": copy.deepcopy(dict(snapshot)),
        "effective_config_sha256": base.sha256_json(effective),
        "primary_case_design_count": len(primary_design),
        "receiver_case_design_count": len(receiver_design),
        "combined_case_design_sha256": canonical_design_digest(
            base, primary_design, receiver_design
        ),
        "transport_files": {
            "primary_transport_cases.csv": sha256_file(output / "primary_transport_cases.csv"),
            "receiver_intervention_cases.csv": sha256_file(
                output / "receiver_intervention_cases.csv"
            ),
        },
        "full_system_claim_allowed": False,
    }


def validate_contract(
    base: ModuleType,
    contract: Mapping[str, Any],
    frontier: Mapping[str, Any],
    mode: str,
    snapshot: Mapping[str, Any],
    effective: Mapping[str, Any],
    primary_design: pd.DataFrame,
    receiver_design: pd.DataFrame,
    output: Path,
) -> bool:
    expected = build_contract(
        base,
        frontier,
        mode,
        snapshot,
        effective,
        primary_design,
        receiver_design,
        output,
    )
    return dict(contract) == expected


def build_audit(
    base: ModuleType,
    frontier: Mapping[str, Any],
    mode: str,
    parent: Mapping[str, Any],
    source_unchanged: bool,
    contract_valid: bool,
    targets: pd.DataFrame,
    primary_design: pd.DataFrame,
    primary: pd.DataFrame,
    selected: pd.DataFrame,
    status: pd.DataFrame,
    trace: pd.DataFrame,
    receiver_design: pd.DataFrame,
    receiver: pd.DataFrame,
    reproduction: pd.DataFrame,
    energy: pd.DataFrame,
    convergence_input: pd.DataFrame,
    convergence: pd.DataFrame,
) -> dict[str, Any]:
    balance_tolerance = float(frontier["audit_tolerances"]["balance_relative"])
    identity_tolerance = float(frontier["audit_tolerances"]["identity_absolute_kw"])
    voltage_limit = float(frontier["primary_transport"]["terminal_voltage_limit_v"])
    primary_ids = set(primary_design["case_id"].astype(str))
    actual_primary_ids = set(primary["case_id"].astype(str))
    receiver_ids = set(receiver_design["case_id"].astype(str))
    actual_receiver_ids = set(receiver["case_id"].astype(str))
    reached_primary = primary.loc[bools(primary["target_reached"])]
    reached_receiver = receiver.loc[bools(receiver["target_reached"])]
    selected_candidates = primary_candidates(primary)
    selected_ids = set(selected["case_id"].astype(str)) if not selected.empty else set()
    expected_selection_pairs: set[tuple[str, str]] = set()
    for target_id, group in selected_candidates.groupby("target_id", sort=False):
        expected_selection_pairs.update(
            {
                (str(target_id), "best_conditional_saving"),
                (str(target_id), "minimum_voltage"),
            }
        )
        if (
            pd.to_numeric(
                group["maximum_required_terminal_voltage_signed_v"], errors="coerce"
            )
            <= voltage_limit + 1.0e-12
        ).any():
            expected_selection_pairs.add((str(target_id), "best_under_1v"))
    actual_selection_pairs = (
        set(zip(selected["target_id"].astype(str), selected["selection"].astype(str)))
        if not selected.empty
        else set()
    )
    under_selected = selected.loc[selected["selection"].eq("best_under_1v")]
    energy_error = (
        energy["scenario_saving_kw_vs_erv_ac"]
        - (
            energy["saving_before_receiver_and_sink_kw"]
            - energy["receiver_and_sink_power_kw"]
        )
        if not energy.empty
        else pd.Series(dtype=float)
    )
    final_trace = trace.iloc[-1] if not trace.empty else None
    ordered_status = status.sort_values("remaining_duty_completion_pct")
    feasibility_values = bools(ordered_status["one_volt_feasible"]).to_numpy(bool)
    feasibility_is_monotone = bool(
        not feasibility_values.any()
        or not feasibility_values[np.argmax(~feasibility_values) :].any()
        if (~feasibility_values).any()
        else True
    )
    bracket_endpoints_verified = False
    if final_trace is not None:
        lower_rows = ordered_status.loc[
            np.isclose(
                ordered_status["remaining_duty_completion_pct"],
                float(final_trace["lower_feasible_completion_pct"]),
                rtol=0.0,
                atol=1.0e-8,
            )
        ]
        upper_rows = ordered_status.loc[
            np.isclose(
                ordered_status["remaining_duty_completion_pct"],
                float(final_trace["upper_infeasible_completion_pct"]),
                rtol=0.0,
                atol=1.0e-8,
            )
        ]
        bracket_endpoints_verified = bool(
            len(lower_rows) == 1
            and len(upper_rows) == 1
            and bool(lower_rows.iloc[0]["one_volt_feasible"])
            and not bool(upper_rows.iloc[0]["one_volt_feasible"])
        )
    bracket_ok = bool(
        final_trace is not None
        and (
            (
                final_trace["status"] == "tolerance_reached"
                and float(final_trace["bracket_width_percentage_point"])
                <= float(
                    frontier["adaptive_one_volt_frontier"][
                        "completion_tolerance_percentage_point"
                    ]
                )
                + 1.0e-12
            )
            or (mode == "smoke" and final_trace["status"] == "maximum_iterations_reached")
        )
    )
    no_better_omitted = True
    for row in selected.to_dict("records"):
        group = selected_candidates.loc[selected_candidates["target_id"].eq(row["target_id"])]
        if row["selection"] == "best_under_1v":
            group = group.loc[
                group["maximum_required_terminal_voltage_signed_v"] <= voltage_limit + 1.0e-12
            ]
        if row["selection"] in {"best_under_1v", "best_conditional_saving"} and not group.empty:
            no_better_omitted = bool(
                no_better_omitted
                and float(row["incremental_saving_kw_vs_passive_erv"])
                >= float(group["incremental_saving_kw_vs_passive_erv"].max()) - 1.0e-10
            )
        if row["selection"] == "minimum_voltage" and not group.empty:
            no_better_omitted = bool(
                no_better_omitted
                and float(row["maximum_required_terminal_voltage_signed_v"])
                <= float(group["maximum_required_terminal_voltage_signed_v"].min()) + 1.0e-10
            )
    checks = {
        "parent_percentage_contract_is_valid": all(parent["checks"].values()),
        "source_snapshot_unchanged_during_run": source_unchanged,
        "transport_contract_validated": contract_valid,
        "target_ids_unique": not targets["target_id"].duplicated().any(),
        "target_completion_strictly_inside_endpoint": bool(
            targets["remaining_duty_completion_pct"].between(0.0, 100.0, inclusive="neither").all()
        ),
        "primary_design_exactly_covered": primary_ids == actual_primary_ids
        and not primary["case_id"].duplicated().any(),
        "receiver_design_exactly_covered": receiver_ids == actual_receiver_ids
        and not receiver["case_id"].duplicated().any(),
        "primary_and_receiver_ids_disjoint": primary_ids.isdisjoint(receiver_ids),
        "no_transport_exceptions": not primary["status"].astype(str).str.startswith("exception:").any()
        and not receiver["status"].astype(str).str.startswith("exception:").any(),
        "primary_water_balance_within_tolerance": bool(
            reached_primary.empty
            or finite_max_abs(reached_primary["water_balance_relative_error"]) <= balance_tolerance
        ),
        "primary_receiver_balance_within_tolerance": bool(
            reached_primary.empty
            or finite_max_abs(reached_primary["receiver_water_balance_relative_error"])
            <= balance_tolerance
        ),
        "receiver_intervention_balances_within_tolerance": bool(
            reached_receiver.empty
            or (
                finite_max_abs(reached_receiver["water_balance_relative_error"]) <= balance_tolerance
                and finite_max_abs(reached_receiver["receiver_water_balance_relative_error"])
                <= balance_tolerance
            )
        ),
        "primary_selection_is_fail_closed": selected_ids.issubset(
            set(selected_candidates["case_id"].astype(str))
        )
        and bool(selected.get("selection_has_no_failed_case_fallback", pd.Series(dtype=bool)).all())
        and actual_selection_pairs == expected_selection_pairs
        and not selected.loc[:, ["target_id", "selection"]].duplicated().any(),
        "no_better_primary_candidate_omitted": no_better_omitted,
        "selected_one_volt_cases_obey_cap": bool(
            under_selected.empty
            or (
                under_selected["maximum_required_terminal_voltage_signed_v"]
                <= voltage_limit + 1.0e-12
            ).all()
        ),
        "adaptive_one_volt_bracket_reaches_tolerance": bracket_ok,
        "adaptive_bracket_endpoints_are_verified": bracket_endpoints_verified,
        "one_volt_feasibility_is_monotone_with_completion": feasibility_is_monotone,
        "status_covers_every_target": set(status["target_id"].astype(str))
        == set(targets["target_id"].astype(str)),
        "receiver_interventions_are_unrankable": bool(
            (~bools(receiver["receiver_intervention_energy_rankable"])).all()
            and (~bools(receiver["receiver_capacity_axis_is_energy_rankable"])).all()
            and (~bools(receiver["full_system_claim_allowed"])).all()
        ),
        "receiver_baseline_reproduces_primary": bool(
            not reproduction.empty
            and set(reproduction["target_id"].astype(str))
            == set(receiver_design["target_id"].astype(str))
            and not reproduction["target_id"].duplicated().any()
            and bools(reproduction["baseline_reproduction_pass"]).all()
        ),
        "energy_scenario_identity": bool(
            energy.empty or finite_max_abs(energy_error) <= identity_tolerance
        ),
        "energy_sign_flags_match": bool(
            energy.empty
            or bools(energy["scenario_energy_positive"]).equals(
                energy["scenario_saving_kw_vs_erv_ac"].gt(0.0)
            )
        ),
        "convergence_population_passes": bool(
            set(convergence.get("source_case_id", pd.Series(dtype=str)).astype(str))
            == set(convergence_input.get("case_id", pd.Series(dtype=str)).astype(str))
            and (convergence_input.empty or not convergence.empty)
            and (convergence.empty or bools(convergence["step_halving_convergence_pass"]).all())
        ),
        "full_system_claim_disabled_everywhere": bool(
            (~bools(primary["full_system_claim_allowed"])).all()
            and (~bools(receiver["full_system_claim_allowed"])).all()
            and frontier["claim_policy"]["full_system_claim_allowed"] is False
        ),
    }
    return {
        "script_version": SCRIPT_VERSION,
        "study_id": str(frontier["study_id"]),
        "mode": mode,
        "pass": all(checks.values()),
        "checks": checks,
        "target_count": len(targets),
        "primary_case_count": len(primary),
        "primary_target_reached_count": int(bools(primary["target_reached"]).sum()),
        "primary_declared_gate_pass_count": int(bools(primary["declared_transport_screen_pass"]).sum()),
        "primary_positive_surface_direction_count": int(
            bools(primary["positive_surface_direction_screen_pass"]).sum()
        ),
        "receiver_intervention_case_count": len(receiver),
        "receiver_intervention_target_reached_count": int(bools(receiver["target_reached"]).sum()),
        "receiver_intervention_positive_surface_direction_count": int(
            bools(receiver["positive_surface_direction_screen_pass"]).sum()
        ),
        "selected_case_count": len(selected),
        "step_halving_case_count": len(convergence),
        "one_volt_frontier": (
            {
                "status": str(final_trace["status"]),
                "lower_feasible_completion_pct": (
                    float(final_trace["lower_feasible_completion_pct"])
                    if math.isfinite(float(final_trace["lower_feasible_completion_pct"]))
                    else None
                ),
                "upper_infeasible_completion_pct": (
                    float(final_trace["upper_infeasible_completion_pct"])
                    if math.isfinite(float(final_trace["upper_infeasible_completion_pct"]))
                    else None
                ),
                "bracket_width_percentage_point": (
                    float(final_trace["bracket_width_percentage_point"])
                    if math.isfinite(float(final_trace["bracket_width_percentage_point"]))
                    else None
                ),
            }
            if final_trace is not None
            else None
        ),
        "physical_status": {
            "primary_positive_surface_direction_feasible": bool(
                bools(primary["positive_surface_direction_screen_pass"]).any()
            ),
            "receiver_intervention_positive_surface_direction_feasible": bool(
                bools(receiver["positive_surface_direction_screen_pass"]).any()
            ),
            "receiver_interventions_energy_rankable": False,
            "validated_full_system_optimum": False,
            "full_system_claim_allowed": False,
        },
    }


def plot_voltage_frontier(selected: pd.DataFrame, trace: pd.DataFrame, output: Path) -> None:
    fig, left = plt.subplots(figsize=(9.4, 5.8))
    right = left.twinx()
    for selection, label, marker in (
        ("best_conditional_saving", "best conditional energy", "o"),
        ("best_under_1v", "best at or below 1 V", "s"),
        ("minimum_voltage", "minimum sampled voltage", "x"),
    ):
        group = selected.loc[selected["selection"].eq(selection)].sort_values(
            "remaining_duty_completion_pct"
        )
        if group.empty:
            continue
        left.plot(
            group["remaining_duty_completion_pct"],
            group["maximum_required_terminal_voltage_signed_v"],
            marker=marker,
            label=label,
        )
    under = selected.loc[selected["selection"].eq("best_under_1v")].sort_values(
        "remaining_duty_completion_pct"
    )
    if not under.empty:
        right.plot(
            under["remaining_duty_completion_pct"],
            under["required_active_area_m2"],
            color="tab:gray",
            linestyle="--",
            alpha=0.7,
            label="area for best <=1 V",
        )
    left.axhline(1.0, color="black", linewidth=1.0, linestyle=":")
    if (
        not trace.empty
        and math.isfinite(float(trace.iloc[-1]["lower_feasible_completion_pct"]))
        and math.isfinite(float(trace.iloc[-1]["upper_infeasible_completion_pct"]))
    ):
        left.axvspan(
            float(trace.iloc[-1]["lower_feasible_completion_pct"]),
            float(trace.iloc[-1]["upper_infeasible_completion_pct"]),
            color="tab:red",
            alpha=0.12,
            label="final 1 V bracket",
        )
    left.set_xlabel("EO completion of remaining post-ERV latent duty [%]")
    left.set_ylabel("Maximum required terminal voltage [V]")
    right.set_ylabel("Active membrane area [m2]")
    left.set_title("Voltage-constrained post-ERV EO design frontier")
    left.grid(alpha=0.25)
    handles1, labels1 = left.get_legend_handles_labels()
    handles2, labels2 = right.get_legend_handles_labels()
    left.legend(handles1 + handles2, labels1 + labels2, fontsize=8)
    fig.tight_layout()
    fig.savefig(output, dpi=180)
    plt.close(fig)


def plot_energy_scenarios(energy: pd.DataFrame, output: Path) -> None:
    fig, ax = plt.subplots(figsize=(9.4, 5.8))
    subset = energy.loc[energy["selection"].eq("best_under_1v")]
    for sec, group in subset.groupby("receiver_and_sink_sec_kwh_per_kg", sort=True):
        group = group.sort_values("remaining_duty_completion_pct")
        ax.plot(
            group["remaining_duty_completion_pct"],
            group["scenario_saving_kw_vs_erv_ac"],
            marker="o",
            label=f"receiver + sink SEC {float(sec):.3f}",
        )
    ax.axhline(0.0, color="black", linewidth=1.0)
    ax.set_xlabel("EO completion of remaining post-ERV latent duty [%]")
    ax.set_ylabel("Conditional saving vs ERV + AC [kW]")
    ax.set_title("Energy consequence within the 1 V-feasible sampled envelope")
    ax.grid(alpha=0.25)
    if ax.lines:
        ax.legend(fontsize=8, ncol=2)
    fig.tight_layout()
    fig.savefig(output, dpi=180)
    plt.close(fig)


def plot_receiver_strategies(strategy: pd.DataFrame, output: Path) -> None:
    fig, ax = plt.subplots(figsize=(9.4, 5.8))
    for family, group in strategy.groupby("receiver_strategy_family", sort=False):
        group = group.sort_values("remaining_duty_completion_pct")
        ax.plot(
            group["remaining_duty_completion_pct"],
            group["maximum_minimum_surface_activity_margin"],
            marker="o",
            label=str(family).replace("_", " "),
        )
    ax.axhline(0.0, color="black", linewidth=1.0)
    ax.set_xlabel("EO completion of remaining post-ERV latent duty [%]")
    ax.set_ylabel("Best diagnostic minimum source-receiver activity margin [-]")
    ax.set_title("Which receiver intervention can restore local surface direction?")
    ax.grid(alpha=0.25)
    if ax.lines:
        ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(output, dpi=180)
    plt.close(fig)


def build_summary(
    runtime: Mapping[str, Any],
    audit: Mapping[str, Any],
    selected: pd.DataFrame,
    energy_optimum: pd.DataFrame,
    strategy: pd.DataFrame,
    thresholds: pd.DataFrame,
    *,
    mode: str,
) -> str:
    frontier = audit["one_volt_frontier"]
    lines = [
        "# Post-ERV EO design frontier",
        "",
        f"Mode: `{mode}`.",
        "",
        "## 1 V frontier",
        "",
    ]
    if (
        frontier
        and frontier["lower_feasible_completion_pct"] is not None
        and frontier["upper_infeasible_completion_pct"] is not None
        and frontier["bracket_width_percentage_point"] is not None
    ):
        lines.append(
            f"- The sampled balanced design brackets the 1 V completion frontier between "
            f"{frontier['lower_feasible_completion_pct']:.4f}% and "
            f"{frontier['upper_infeasible_completion_pct']:.4f}% of the remaining duty "
            f"(width {frontier['bracket_width_percentage_point']:.4f} percentage point)."
        )
    elif frontier:
        lines.append(
            f"- No closed 1 V crossing was observed in the configured window "
            f"(`{frontier['status']}`); no threshold is extrapolated."
        )
    lines.extend(
        [
            "- The frontier is conditional on the sampled material/current grid and the 60,000 m2 observation cap.",
            "- A lower voltage by itself is not an energy optimum: low current reduces voltage but increases active area and module-fan power.",
            "",
            "## Energy sensitivity",
            "",
        ]
    )
    if not energy_optimum.empty:
        one_volt = energy_optimum.loc[energy_optimum["selection"].eq("best_under_1v")]
        for row in one_volt.sort_values("receiver_and_sink_sec_kwh_per_kg").to_dict("records"):
            lines.append(
                f"- Receiver/sink SEC {float(row['receiver_and_sink_sec_kwh_per_kg']):.3f} kWh/kg: "
                f"best point in the screened 1 V window is {float(row['remaining_duty_completion_pct']):.3f}% "
                f"with {float(row['scenario_saving_kw_vs_erv_ac']):.2f} kW conditional saving."
            )
    lines.extend(["", "## Receiver and membrane direction", ""])
    if not strategy.empty:
        positive = strategy.loc[strategy["any_positive_surface_direction"]]
        lines.append(
            f"- Primary balanced receiver cases with positive local surface direction: "
            f"{audit['primary_positive_surface_direction_count']}/{audit['primary_case_count']}."
        )
        lines.append(
            f"- Receiver diagnostic cases with positive local surface direction: "
            f"{audit['receiver_intervention_positive_surface_direction_count']}/"
            f"{audit['receiver_intervention_case_count']}."
        )
        if not positive.empty:
            lines.append(
                "- Dry receiver-inlet scenarios can restore the local activity direction, but many enter negative- or mixed-voltage regimes; they are passive-gradient/topology diagnostics, not closed EO-import designs."
            )
    baseline_thresholds = thresholds.loc[
        np.isclose(thresholds["receiver_to_process_dry_air_ratio"], 1.0)
        & np.isclose(thresholds["receiver_film_multiplier"], 1.0)
        & thresholds["threshold_status"].isin(["bracketed_crossing", "exact_grid_crossing"])
    ]
    for row in baseline_thresholds.to_dict("records"):
        lines.append(
            f"- `{row['target_id']}`: zero surface-margin receiver-inlet RH is approximately "
            f"{float(row['receiver_inlet_rh_at_zero_surface_margin']):.3f} at fixed temperature, R=1 and baseline film."
        )
    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "Receiver conditioning, extra airflow, film/channel changes, regeneration or disposal, heat rejection, manifold pressure drop and electrical export/topology are not closed. Receiver-intervention rows are deliberately excluded from energy ranking.",
            "",
            "**No row is a validated full-system saving or optimum.**",
            "",
            "## Reproduction",
            "",
            "```bash",
            "python3 -B scripts/make_post_erv_eo_design_frontier_v1.py --smoke --jobs 4 --output-dir outputs/post_erv_eo_design_frontier_v1_smoke --overwrite",
            "python3 -B scripts/make_post_erv_eo_design_frontier_v1.py --jobs 8 --output-dir outputs/post_erv_eo_design_frontier_v1 --overwrite",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def output_manifest(output: Path) -> dict[str, Any]:
    files: dict[str, Any] = {}
    for path in sorted(output.iterdir()):
        if not path.is_file() or path.name == "output_manifest.json":
            continue
        record: dict[str, Any] = {
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
        if path.suffix == ".csv":
            frame = pd.read_csv(path, low_memory=False)
            record["row_count"] = len(frame)
            record["columns"] = list(frame.columns)
        files[path.name] = record
    return {
        "schema_version": 1,
        "study_id": "post-erv-eo-design-frontier-v1-2026-08-27",
        "files": files,
    }


def main() -> None:
    args = parse_args()
    frontier_path = args.config.expanduser().resolve()
    frontier = read_json(frontier_path)
    base_config_path = resolve_path(frontier["base_study_config"])
    percentage_config_path = resolve_path(frontier["parent_percentage_config"])
    base_config = read_json(base_config_path)
    base = load_module(BASE_SCRIPT, "post_erv_eo_frontier_base")
    effective = effective_config(frontier, base_config)
    output = (
        args.output_dir.expanduser().resolve()
        if args.output_dir is not None
        else DEFAULT_OUTPUT.parent / (DEFAULT_OUTPUT.name + ("_smoke" if args.smoke else ""))
    )
    base.validate_output_directory(output, bool(args.overwrite))
    parent = validate_parent(frontier)
    analyzer, runtime, _, source_config_path, analyzer_path = base.load_runtime(
        effective,
        v2_root=args.v2_root.expanduser().resolve(),
        area_step_m2=float(frontier["primary_transport"]["area_step_m2"]),
    )
    if analyzer_path.resolve() != ANALYZER_SCRIPT.resolve():
        raise StudyError("Unexpected transport analyzer path")
    initial_snapshot = build_source_snapshot(
        runtime,
        frontier_path,
        base_config_path,
        percentage_config_path,
        source_config_path,
        parent,
    )
    mode = "smoke" if args.smoke else "study"
    targets = make_targets(runtime, frontier, smoke=bool(args.smoke))
    primary_design, primary = evaluate_primary_targets(
        analyzer,
        runtime,
        targets,
        frontier,
        jobs=max(1, int(args.jobs)),
        smoke=bool(args.smoke),
    )
    targets, primary_design, primary, trace = adaptive_frontier(
        analyzer,
        runtime,
        frontier,
        targets,
        primary_design,
        primary,
        jobs=max(1, int(args.jobs)),
        smoke=bool(args.smoke),
    )
    selected, status = select_primary_cases(
        primary, float(frontier["primary_transport"]["terminal_voltage_limit_v"])
    )
    receiver_design = build_receiver_design(runtime, frontier, smoke=bool(args.smoke))
    receiver = evaluate_receiver_design(
        analyzer,
        runtime,
        frontier,
        receiver_design,
        jobs=max(1, int(args.jobs)),
    )
    strategy, thresholds = receiver_strategy_tables(receiver, runtime)
    energy, energy_optimum = build_energy_scenarios(selected, frontier)
    voltage = build_voltage_envelope(primary, frontier)
    reproduction = receiver_baseline_reproduction(
        primary, receiver, runtime, frontier
    )
    convergence_input = build_convergence_input(selected, targets, trace, frontier)
    convergence = base.build_step_halving_convergence(
        analyzer, runtime, targets, convergence_input, effective
    )
    if not convergence.empty:
        convergence = convergence.merge(
            targets.loc[:, ["target_id", "remaining_duty_completion_pct"]],
            on="target_id",
            how="left",
            validate="many_to_one",
        )
        convergence["convergence_population"] = "declared_representative_and_frontier_boundary"
    final_snapshot = build_source_snapshot(
        runtime,
        frontier_path,
        base_config_path,
        percentage_config_path,
        source_config_path,
        parent,
    )
    source_unchanged = initial_snapshot == final_snapshot
    if not source_unchanged:
        raise StudyError("A hashed input changed during the run; results were not published")

    targets.to_csv(output / "completion_targets.csv", index=False)
    primary_design.to_csv(output / "primary_case_design.csv", index=False)
    primary.to_csv(output / "primary_transport_cases.csv", index=False)
    selected.to_csv(output / "selected_primary_cases.csv", index=False)
    status.to_csv(output / "primary_target_status.csv", index=False)
    trace.to_csv(output / "one_volt_frontier_trace.csv", index=False)
    voltage.to_csv(output / "voltage_constrained_envelope.csv", index=False)
    receiver_design.to_csv(output / "receiver_intervention_design.csv", index=False)
    receiver.to_csv(output / "receiver_intervention_cases.csv", index=False)
    strategy.to_csv(output / "receiver_strategy_summary.csv", index=False)
    thresholds.to_csv(output / "receiver_surface_direction_thresholds.csv", index=False)
    reproduction.to_csv(output / "receiver_baseline_reproduction.csv", index=False)
    energy.to_csv(output / "receiver_sink_energy_scenarios.csv", index=False)
    energy_optimum.to_csv(output / "screened_optimum_by_receiver_sec.csv", index=False)
    convergence.to_csv(output / "step_halving_convergence.csv", index=False)
    write_json(output / "frontier_config_used.json", frontier)
    write_json(output / "effective_config_used.json", effective)
    contract = build_contract(
        base,
        frontier,
        mode,
        initial_snapshot,
        effective,
        primary_design,
        receiver_design,
        output,
    )
    write_json(output / "transport_contract.json", contract)
    contract_valid = validate_contract(
        base,
        read_json(output / "transport_contract.json"),
        frontier,
        mode,
        initial_snapshot,
        effective,
        primary_design,
        receiver_design,
        output,
    )
    audit = build_audit(
        base,
        frontier,
        mode,
        parent,
        source_unchanged,
        contract_valid,
        targets,
        primary_design,
        primary,
        selected,
        status,
        trace,
        receiver_design,
        receiver,
        reproduction,
        energy,
        convergence_input,
        convergence,
    )
    write_json(output / "audit.json", audit)
    plot_voltage_frontier(selected, trace, output / "voltage_frontier.png")
    plot_energy_scenarios(energy, output / "receiver_sec_energy.png")
    plot_receiver_strategies(strategy, output / "receiver_strategy_margin.png")
    summary = build_summary(
        runtime,
        audit,
        selected,
        energy_optimum,
        strategy,
        thresholds,
        mode=mode,
    )
    (output / "SUMMARY.md").write_text(summary, encoding="utf-8")
    write_json(output / "output_manifest.json", output_manifest(output))
    if not audit["pass"]:
        failed = [name for name, passed in audit["checks"].items() if not passed]
        raise StudyError(
            f"Design-frontier audit failed ({', '.join(failed)}); inspect {output / 'audit.json'}"
        )
    print(f"Wrote {mode} design-frontier study to {output}")
    print(json.dumps(audit["one_volt_frontier"], indent=2))


if __name__ == "__main__":
    main()
