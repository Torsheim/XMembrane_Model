#!/usr/bin/env python3
"""Run the isolated workshop common-voltage diffusivity cross-check.

The calculation reuses the reviewed post-ERV endpoints, common-terminal-voltage
segment solver and local thermodynamic audit.  Only the Terminal-1 water
diffusivity is varied.  Active area and current density are reported, but are
not acceptance gates.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
from types import ModuleType
from typing import Any, Mapping

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from heiq.wp1.studies.direct_eo_erv import solve_segmented_transport


SCRIPT_VERSION = "workshop-common-voltage-diffusivity-v1.2-2026-08-31"
DEFAULT_CONFIG = ROOT / "config" / "workshop_common_voltage_diffusivity_v1.json"
DEFAULT_OUTPUT = ROOT / "outputs" / "workshop_common_voltage_diffusivity_v1"
KNOWN_OUTPUTS = (
    "cases.csv",
    "segment_convergence.csv",
    "diffusivity_envelope.csv",
    "local_bracket_probe.csv",
    "segment_profiles.csv.gz",
    "config_used.json",
    "audit.json",
    "source_manifest.json",
    "README.md",
    "figures/workshop_common_voltage_diffusivity.png",
    "figures/workshop_common_voltage_diffusivity.pdf",
)


class WorkshopStudyError(RuntimeError):
    """Raised when the isolated workshop contract is not satisfied."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        value = float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, float):
        if math.isnan(value):
            return None
        if math.isinf(value):
            return "Infinity" if value > 0.0 else "-Infinity"
    return value


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(json_safe(dict(payload)), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def resolve_path(value: str | Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def load_module(path: Path, name: str) -> ModuleType:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise ImportError(f"Cannot load module from {path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def prepare_output(path: Path, overwrite: bool) -> None:
    path.mkdir(parents=True, exist_ok=True)
    existing = [path / name for name in KNOWN_OUTPUTS if (path / name).exists()]
    if existing and not overwrite:
        names = ", ".join(item.name for item in existing)
        raise FileExistsError(
            f"Output directory already contains study files ({names}); use --overwrite"
        )
    if overwrite:
        for item in existing:
            item.unlink()


def _unique_floats(values: list[Any], label: str) -> list[float]:
    result = [float(value) for value in values]
    if not result or not all(math.isfinite(value) for value in result):
        raise WorkshopStudyError(f"{label} must contain finite values")
    if len(set(result)) != len(result):
        raise WorkshopStudyError(f"{label} contains duplicate values")
    return result


def validate_config(config: Mapping[str, Any]) -> None:
    if int(config.get("schema_version", -1)) != 1:
        raise WorkshopStudyError("Unsupported workshop config schema")
    diffusivities = _unique_floats(
        list(config["water_diffusivity_m2_s"]), "water_diffusivity_m2_s"
    )
    if min(diffusivities) <= 0.0:
        raise WorkshopStudyError("This log sweep requires positive diffusivity")
    if not any(math.isclose(value, 1.0e-14, rel_tol=0.0, abs_tol=1.0e-30) for value in diffusivities):
        raise WorkshopStudyError("The exact 1e-14 m2/s endpoint is missing")
    if not any(math.isclose(value, 1.0e-9, rel_tol=0.0, abs_tol=1.0e-24) for value in diffusivities):
        raise WorkshopStudyError("The exact 1e-9 m2/s endpoint is missing")

    voltages = _unique_floats(list(config["terminal_voltages_v"]), "terminal_voltages_v")
    if min(voltages) <= 0.0 or max(voltages) > 2.0 + 1.0e-12:
        raise WorkshopStudyError("Every common terminal voltage must lie in (0, 2] V")

    segment_counts = [int(value) for value in config["segment_counts"]]
    if len(segment_counts) != 2 or len(set(segment_counts)) != 2:
        raise WorkshopStudyError("Exactly two distinct segment counts are required")
    if min(segment_counts) < 2:
        raise WorkshopStudyError("Segment counts must be at least two")
    if int(config["selected_segment_count"]) != max(segment_counts):
        raise WorkshopStudyError("selected_segment_count must be the refined count")

    targets = list(config["targets"])
    if len(targets) != 2 or {str(row["target_id"]) for row in targets} != {
        "o30",
        "full_remaining_latent",
    }:
        raise WorkshopStudyError("The focused run must contain O30 and full duty")
    for target in targets:
        completion = float(target["remaining_duty_completion_pct"])
        if not 0.0 < completion <= 100.0:
            raise WorkshopStudyError("Target completion must lie in (0, 100]")

    transport = config["transport"]
    if transport.get("engineering_current_density_limit_a_m2") is not None:
        raise WorkshopStudyError("A current-density acceptance gate is forbidden")
    if transport.get("area_is_acceptance_gate") is not False:
        raise WorkshopStudyError("Area must be diagnostic, not an acceptance gate")
    if transport.get("surface_direction_is_acceptance_gate") is not False:
        raise WorkshopStudyError("Passive surface direction is not a hard physics gate")
    if float(transport["area_observation_cap_m2"]) <= 0.0:
        raise WorkshopStudyError("area_observation_cap_m2 must be positive")
    if config["energy_boundary"].get("full_system_claim_allowed") is not False:
        raise WorkshopStudyError("The workshop screen cannot enable a full-system claim")
    if config["energy_boundary"].get("receiver_and_sink_energy_modelled") is not False:
        raise WorkshopStudyError("This isolated runner expects receiver energy to be open")

    probe = config["local_bracket_probe"]
    if float(probe["numeric_ceiling_multiplier"]) <= 1.0:
        raise WorkshopStudyError("The local bracket probe multiplier must exceed one")
    if probe.get("coverage") != "all_flagged_cases_at_or_below_2v":
        raise WorkshopStudyError(
            "The local bracket probe must cover every flagged case at or below 2 V"
        )


def case_is_feasible(
    result: Mapping[str, Any], *, endpoint_valid: bool, thermodynamic_pass: bool
) -> bool:
    """Physical/numerical gate with no area, current or surface-sign criterion."""

    return bool(
        endpoint_valid
        and bool(result.get("transport_solution_complete", False))
        and bool(result.get("transport_water_balance_pass", False))
        and bool(result.get("terminal_voltage_solution_pass", False))
        and thermodynamic_pass
    )


def _finite(value: Any) -> float:
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return math.nan
    return converted if math.isfinite(converted) else math.nan


def run_case(
    *,
    target: Mapping[str, Any],
    diffusivity: float,
    voltage: float,
    segment_count: int,
    config: Mapping[str, Any],
    closure: ModuleType,
    closure_config: Mapping[str, Any],
    runtime: Mapping[str, Any],
    source_config: Mapping[str, Any],
    effective_config: Mapping[str, Any],
    percentage_summary: pd.DataFrame,
) -> tuple[dict[str, Any], pd.DataFrame]:
    completion = float(target["remaining_duty_completion_pct"])
    endpoints = closure.post_erv_endpoints(runtime, completion)
    expected_target_w = float(target["target_humidity_ratio_kg_kg_da"])
    if not math.isclose(
        float(endpoints.process_out.w), expected_target_w, rel_tol=0.0, abs_tol=2.0e-12
    ):
        raise WorkshopStudyError(
            f"Target humidity mismatch for {target['target_id']}: "
            f"{endpoints.process_out.w} versus {expected_target_w}"
        )

    material = closure.anchor_material(runtime)
    material["name"] = f"terminal1_D_{diffusivity:.12e}"
    material["water_diffusivity_m2_s"] = float(diffusivity)
    transport_config = config["transport"]
    result, profile = solve_segmented_transport(
        v2=runtime["v2"],
        v2_config=runtime["v2_config"],
        study_config=effective_config,
        endpoints=endpoints,
        material=material,
        terminal_voltage_v=float(voltage),
        fixed_loss_voltage_v=float(transport_config["fixed_loss_voltage_v"]),
        series_asr_ohm_m2=float(transport_config["series_asr_ohm_m2"]),
        film_scale_factor=float(transport_config["film_scale_factor"]),
        segment_count=int(segment_count),
    )
    audited = closure.thermodynamic_profile_audit(
        profile, closure_config["audit_tolerances"]
    )
    thermodynamic_pass = bool(
        not audited.empty
        and audited["thermodynamic_consistency_pass"].fillna(False).astype(bool).all()
    )
    feasible = case_is_feasible(
        result,
        endpoint_valid=bool(endpoints.valid),
        thermodynamic_pass=thermodynamic_pass,
    )
    case_id = (
        f"{target['target_id']}__D{diffusivity:.12e}"
        f"__V{voltage:.6g}__n{segment_count}"
    )
    if not audited.empty:
        audited.insert(0, "case_id", case_id)
        audited.insert(1, "target_id", str(target["target_id"]))
        audited.insert(2, "water_diffusivity_m2_s", float(diffusivity))
        audited.insert(3, "common_terminal_voltage_v", float(voltage))
        audited.insert(4, "study_segment_count", int(segment_count))

    area = _finite(result.get("required_active_area_m2"))
    grid_kw = _finite(result.get("eo_grid_power_kw"))
    fan_rate = float(
        source_config["post_erv"]["process_and_receiver_fan_power_kw_per_m2"]
    )
    fan_kw = area * fan_rate if feasible and math.isfinite(area) else math.nan
    known_power_kw = (
        grid_kw + fan_kw
        if feasible and math.isfinite(grid_kw) and math.isfinite(fan_kw)
        else math.nan
    )
    water_kg_h = float(endpoints.water_transfer_kg_h)
    known_sec = (
        known_power_kw / water_kg_h
        if math.isfinite(known_power_kw) and water_kg_h > 0.0
        else math.nan
    )

    baseline = runtime["baseline"]
    remaining_ac = runtime["system_core"].solve_coil(
        inlet=endpoints.process_out,
        supply_target=baseline.remaining_ac.supply,
        m_da=float(runtime["dry_air_mass_flow_kg_s"]),
        rated_cop=baseline.rated_cop,
        ac_config=runtime["active_cfg"]["ac_model"],
    )
    exact_total_kw = (
        float(baseline.passive_erv.total_power_kw)
        + float(remaining_ac.total_ac_power_kw)
        + known_power_kw
        if feasible and remaining_ac.physical and math.isfinite(known_power_kw)
        else math.nan
    )
    exact_saving_kw = (
        float(baseline.total_power_kw) - exact_total_kw
        if math.isfinite(exact_total_kw)
        else math.nan
    )
    conservative_avoided_ac_kw = closure.ac_reduction_at_completion(
        percentage_summary, completion
    )
    conservative_saving_kw = (
        conservative_avoided_ac_kw - known_power_kw
        if feasible and math.isfinite(known_power_kw)
        else math.nan
    )
    conservative_total_kw = (
        float(baseline.total_power_kw) - conservative_saving_kw
        if math.isfinite(conservative_saving_kw)
        else math.nan
    )
    receiver_budget = (
        conservative_saving_kw / water_kg_h
        if math.isfinite(conservative_saving_kw) and water_kg_h > 0.0
        else math.nan
    )
    uphill_fraction = (
        float(audited["uphill_active_transport"].fillna(False).astype(bool).mean())
        if not audited.empty
        else math.nan
    )

    failure_reason = str(result.get("transport_failure_reason", "")).strip()
    if bool(result.get("legacy_numeric_current_search_ceiling_encountered", False)):
        resolution_class = "NUMERICAL_OR_LOCAL_SOLUTION_FAILURE"
    else:
        resolution_class = closure.classify_replay_resolution(
            replay_pass=feasible,
            transport_complete=bool(result.get("transport_solution_complete", False)),
            failure_reason=failure_reason,
        )
    if feasible:
        status = "COMMON_VOLTAGE_FEASIBLE"
    elif not endpoints.valid:
        status = "INVALID_ENDPOINT"
    elif not thermodynamic_pass and bool(result.get("transport_solution_complete", False)):
        status = "THERMODYNAMIC_AUDIT_FAILED"
    elif failure_reason:
        status = failure_reason
    else:
        status = "TRANSPORT_OR_VOLTAGE_NOT_CLOSED"

    row: dict[str, Any] = {
        "case_id": case_id,
        "study_id": config["study_id"],
        "script_version": SCRIPT_VERSION,
        "target_id": str(target["target_id"]),
        "remaining_duty_completion_pct": completion,
        "target_humidity_ratio_kg_kg_da": expected_target_w,
        "target_water_transfer_kg_h": water_kg_h,
        "water_diffusivity_m2_s": float(diffusivity),
        "common_terminal_voltage_v": float(voltage),
        "segment_count": int(segment_count),
        "electrical_topology": "single_common_voltage_parallel_current_sharing",
        "status": status,
        "resolution_class": resolution_class,
        "common_voltage_feasible": feasible,
        "endpoint_valid": bool(endpoints.valid),
        "thermodynamic_consistency_pass": thermodynamic_pass,
        "thermodynamic_profile_row_count": len(audited),
        "uphill_active_segment_fraction": uphill_fraction,
        "area_is_acceptance_gate": False,
        "surface_direction_is_acceptance_gate": False,
        "current_density_gate_applied": False,
        "engineering_current_density_limit_a_m2": None,
        "internal_numeric_current_search_ceiling_a_m2": float(
            runtime["v2_config"]["model"]["current_solver_upper_bound_a_m2"]
        ),
        "full_system_claim_allowed": False,
        "receiver_and_sink_energy_modelled": False,
        "process_heat_leak_fraction": float(
            config["energy_boundary"]["process_heat_leak_fraction"]
        ),
        "anchor_water_drag": float(material["water_drag"]),
        "anchor_conductivity_s_m": float(material["conductivity_s_m"]),
        "anchor_dry_thickness_um": float(material["dry_thickness_um"]),
        "anchor_water_capacity_mol_m3_activity": float(
            material["water_capacity_mol_m3_activity"]
        ),
        **dict(result),
        "area_observation_cap_pass_diagnostic": bool(
            result.get("area_cap_pass", False)
        ),
        "module_fan_power_kw": fan_kw,
        "known_eo_grid_and_module_fan_power_kw": known_power_kw,
        "known_eo_grid_and_module_fan_sec_kwh_per_kg": known_sec,
        "control_conservative_avoided_ac_power_kw": conservative_avoided_ac_kw,
        "conditional_conservative_total_power_kw": conservative_total_kw,
        "conditional_conservative_saving_kw_vs_erv_ac": conservative_saving_kw,
        "conditional_receiver_sink_sec_budget_kwh_per_kg": receiver_budget,
        "exact_endpoint_remaining_ac_power_kw": (
            float(remaining_ac.total_ac_power_kw) if remaining_ac.physical else math.nan
        ),
        "conditional_exact_endpoint_total_power_kw": exact_total_kw,
        "conditional_exact_endpoint_saving_kw_vs_erv_ac": exact_saving_kw,
        "passive_erv_plus_ac_reference_kw": float(baseline.total_power_kw),
        "integrated_net_chemical_work_kw": closure.integrated_profile_value(
            audited, "net_chemical_work_density_w_m2"
        ),
        "integrated_membrane_dissipation_kw": closure.integrated_profile_value(
            audited, "membrane_dissipation_density_w_m2"
        ),
    }
    return row, audited


def build_segment_convergence(
    cases: pd.DataFrame, config: Mapping[str, Any]
) -> pd.DataFrame:
    coarse_count = min(int(value) for value in config["segment_counts"])
    refined_count = int(config["selected_segment_count"])
    keys = ["target_id", "water_diffusivity_m2_s", "common_terminal_voltage_v"]
    fields = [
        "case_id",
        "common_voltage_feasible",
        "status",
        "required_active_area_m2",
        "known_eo_grid_and_module_fan_power_kw",
    ]
    coarse = cases.loc[cases["segment_count"].eq(coarse_count), keys + fields].copy()
    refined = cases.loc[cases["segment_count"].eq(refined_count), keys + fields].copy()
    merged = coarse.merge(
        refined,
        on=keys,
        how="outer",
        validate="one_to_one",
        suffixes=("_coarse", "_refined"),
    )
    both_feasible = (
        merged["common_voltage_feasible_coarse"].fillna(False).astype(bool)
        & merged["common_voltage_feasible_refined"].fillna(False).astype(bool)
    )
    status_stable = merged["common_voltage_feasible_coarse"].fillna(False).astype(
        bool
    ).eq(merged["common_voltage_feasible_refined"].fillna(False).astype(bool))
    area_coarse = pd.to_numeric(merged["required_active_area_m2_coarse"], errors="coerce")
    area_refined = pd.to_numeric(merged["required_active_area_m2_refined"], errors="coerce")
    power_coarse = pd.to_numeric(
        merged["known_eo_grid_and_module_fan_power_kw_coarse"], errors="coerce"
    )
    power_refined = pd.to_numeric(
        merged["known_eo_grid_and_module_fan_power_kw_refined"], errors="coerce"
    )
    merged["area_relative_change"] = np.where(
        both_feasible,
        (area_refined - area_coarse).abs() / area_refined.abs().clip(lower=1.0e-12),
        np.nan,
    )
    merged["known_power_relative_change"] = np.where(
        both_feasible,
        (power_refined - power_coarse).abs()
        / power_refined.abs().clip(lower=1.0e-12),
        np.nan,
    )
    tolerances = config["numerical_convergence"]
    merged["sampled_feasibility_status_stable"] = status_stable
    merged["numerically_confirmed_feasible"] = (
        both_feasible
        & merged["area_relative_change"].le(
            float(tolerances["maximum_area_relative_change"])
        )
        & merged["known_power_relative_change"].le(
            float(tolerances["maximum_known_power_relative_change"])
        )
    )
    merged.insert(3, "coarse_segment_count", coarse_count)
    merged.insert(4, "refined_segment_count", refined_count)
    return merged


def build_diffusivity_envelope(
    cases: pd.DataFrame, convergence: pd.DataFrame, config: Mapping[str, Any]
) -> pd.DataFrame:
    refined_count = int(config["selected_segment_count"])
    refined = cases.loc[cases["segment_count"].eq(refined_count)].copy()
    convergence_keys = [
        "target_id",
        "water_diffusivity_m2_s",
        "common_terminal_voltage_v",
    ]
    refined = refined.merge(
        convergence[
            convergence_keys
            + ["sampled_feasibility_status_stable", "numerically_confirmed_feasible"]
        ],
        on=convergence_keys,
        how="left",
        validate="one_to_one",
    )
    rows: list[dict[str, Any]] = []
    for (target_id, diffusivity), group in refined.groupby(
        ["target_id", "water_diffusivity_m2_s"], sort=True
    ):
        feasible = group.loc[group["common_voltage_feasible"].astype(bool)].copy()
        confirmed = group.loc[group["numerically_confirmed_feasible"].fillna(False)].copy()
        physical_no_solution = group["resolution_class"].eq(
            "PHYSICAL_NO_COMMON_VOLTAGE_AT_THIS_COORDINATE"
        )
        numerically_unresolved = group["resolution_class"].eq(
            "NUMERICAL_OR_LOCAL_SOLUTION_FAILURE"
        )
        pool = confirmed if not confirmed.empty else feasible
        if not confirmed.empty:
            status = "NUMERICALLY_CONFIRMED_FEASIBLE_VOLTAGE"
        elif not feasible.empty:
            status = "REFINED_FEASIBLE_NOT_CONFIRMED_AT_COARSE_RESOLUTION"
        elif numerically_unresolved.any():
            status = "NO_FEASIBLE_SAMPLED_VOLTAGE_WITH_UNRESOLVED_POINTS"
        else:
            status = "NO_FEASIBLE_SAMPLED_COMMON_VOLTAGE"
        selected: Mapping[str, Any] | None = None
        if not pool.empty:
            ordered = pool.sort_values(
                [
                    "conditional_conservative_total_power_kw",
                    "required_active_area_m2",
                    "common_terminal_voltage_v",
                ],
                kind="mergesort",
            )
            selected = ordered.iloc[0].to_dict()
        row: dict[str, Any] = {
            "target_id": target_id,
            "water_diffusivity_m2_s": float(diffusivity),
            "sampled_voltage_count": len(group),
            "refined_feasible_voltage_count": len(feasible),
            "numerically_confirmed_voltage_count": len(confirmed),
            "refined_physical_no_solution_voltage_count": int(
                physical_no_solution.sum()
            ),
            "refined_numerical_or_local_unresolved_voltage_count": int(
                numerically_unresolved.sum()
            ),
            "minimum_refined_feasible_voltage_v": (
                float(feasible["common_terminal_voltage_v"].min())
                if not feasible.empty
                else math.nan
            ),
            "maximum_refined_feasible_voltage_v": (
                float(feasible["common_terminal_voltage_v"].max())
                if not feasible.empty
                else math.nan
            ),
            "selection_status": status,
            "full_system_claim_allowed": False,
            "area_used_as_acceptance_gate": False,
            "current_density_gate_applied": False,
        }
        selected_fields = (
            "case_id",
            "common_terminal_voltage_v",
            "required_active_area_m2",
            "minimum_local_current_density_a_m2",
            "maximum_local_current_density_a_m2",
            "eo_grid_power_kw",
            "module_fan_power_kw",
            "known_eo_grid_and_module_fan_power_kw",
            "known_eo_grid_and_module_fan_sec_kwh_per_kg",
            "conditional_conservative_total_power_kw",
            "conditional_conservative_saving_kw_vs_erv_ac",
            "conditional_receiver_sink_sec_budget_kwh_per_kg",
            "conditional_exact_endpoint_total_power_kw",
            "conditional_exact_endpoint_saving_kw_vs_erv_ac",
            "minimum_surface_activity_margin",
            "uphill_active_segment_fraction",
        )
        for field in selected_fields:
            row[f"selected_{field}"] = (
                selected.get(field, math.nan) if selected is not None else math.nan
            )
        rows.append(row)
    return pd.DataFrame(rows)


def current_bracket_retry_source_mask(cases: pd.DataFrame) -> pd.Series:
    """Select every <=2 V case that encountered the ambiguous V2 high bracket."""

    voltages = pd.to_numeric(cases["common_terminal_voltage_v"], errors="coerce")
    if "legacy_numeric_current_search_ceiling_encountered" in cases:
        encountered = (
            cases["legacy_numeric_current_search_ceiling_encountered"]
            .fillna(False)
            .astype(bool)
        )
    else:
        encountered = cases["status"].eq("above_internal_current_search_ceiling")
    return encountered & voltages.gt(0.0) & voltages.le(2.0 + 1.0e-12)


def run_local_bracket_probe(
    *,
    cases: pd.DataFrame,
    profiles: pd.DataFrame,
    config: Mapping[str, Any],
    closure: ModuleType,
    closure_config: Mapping[str, Any],
    runtime: Mapping[str, Any],
    source_config: Mapping[str, Any],
    effective_config: Mapping[str, Any],
    percentage_summary: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Retry every flagged <=2 V case at a higher numeric current bound.

    The V2 high bracket is the lower of a physical-activity limit and a
    configured numeric ceiling.  Only a retry that passes the complete existing
    feasibility contract replaces the source case and its profile.  Every
    unrecovered source remains fail-closed as numerical/local unresolved.
    """

    source_ceiling = float(
        runtime["v2_config"]["model"]["current_solver_upper_bound_a_m2"]
    )
    multiplier = float(config["local_bracket_probe"]["numeric_ceiling_multiplier"])
    elevated_runtime = dict(runtime)
    elevated_runtime["v2_config"] = copy.deepcopy(runtime["v2_config"])
    elevated_runtime["v2_config"]["model"][
        "current_solver_upper_bound_a_m2"
    ] = source_ceiling * multiplier
    targets = {str(row["target_id"]): row for row in config["targets"]}
    source_rows = cases.loc[current_bracket_retry_source_mask(cases)].sort_values(
        [
            "target_id",
            "water_diffusivity_m2_s",
            "common_terminal_voltage_v",
            "segment_count",
        ],
        kind="mergesort",
    )
    effective_by_id: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for source in cases.to_dict("records"):
        case_id = str(source["case_id"])
        if case_id in effective_by_id:
            raise WorkshopStudyError(f"Duplicate case_id before bracket retry: {case_id}")
        effective = dict(source)
        effective.update(
            {
                "numeric_ceiling_retry_applied": False,
                "numeric_ceiling_retry_recovered": False,
                "numeric_ceiling_retry_source_a_m2": math.nan,
                "numeric_ceiling_retry_elevated_a_m2": math.nan,
                "initial_status_before_numeric_ceiling_retry": None,
                "initial_resolution_class_before_numeric_ceiling_retry": None,
            }
        )
        effective_by_id[case_id] = effective
        order.append(case_id)

    rows: list[dict[str, Any]] = []
    recovered_profiles: dict[str, pd.DataFrame] = {}
    for source_row in source_rows.to_dict("records"):
        source_case_id = str(source_row["case_id"])
        target_id = str(source_row["target_id"])
        diffusivity = float(source_row["water_diffusivity_m2_s"])
        voltage = float(source_row["common_terminal_voltage_v"])
        segment_count = int(source_row["segment_count"])
        elevated_row, elevated_profile = run_case(
            target=targets[target_id],
            diffusivity=diffusivity,
            voltage=voltage,
            segment_count=segment_count,
            config=config,
            closure=closure,
            closure_config=closure_config,
            runtime=elevated_runtime,
            source_config=source_config,
            effective_config=effective_config,
            percentage_summary=percentage_summary,
        )
        if str(elevated_row.get("case_id", source_case_id)) != source_case_id:
            raise WorkshopStudyError(
                f"Bracket retry changed case_id {source_case_id!r}"
            )
        retry_recovered = bool(elevated_row.get("common_voltage_feasible", False))
        elevated_resolution = str(elevated_row.get("resolution_class", ""))
        if not retry_recovered:
            elevated_resolution = "NUMERICAL_OR_LOCAL_SOLUTION_FAILURE"

        metadata = {
            "numeric_ceiling_retry_applied": True,
            "numeric_ceiling_retry_recovered": retry_recovered,
            "numeric_ceiling_retry_source_a_m2": source_ceiling,
            "numeric_ceiling_retry_elevated_a_m2": source_ceiling * multiplier,
            "initial_status_before_numeric_ceiling_retry": str(source_row["status"]),
            "initial_resolution_class_before_numeric_ceiling_retry": str(
                source_row["resolution_class"]
            ),
        }
        if retry_recovered:
            if elevated_profile.empty:
                raise WorkshopStudyError(
                    f"Recovered bracket retry has no profile: {source_case_id}"
                )
            effective = dict(elevated_row)
            effective.update(metadata)
            effective_by_id[source_case_id] = effective
            recovered_profiles[source_case_id] = elevated_profile
        else:
            effective_by_id[source_case_id].update(metadata)
            effective_by_id[source_case_id][
                "resolution_class"
            ] = "NUMERICAL_OR_LOCAL_SOLUTION_FAILURE"

        rows.append(
            {
                "source_case_id": source_case_id,
                "target_id": target_id,
                "water_diffusivity_m2_s": diffusivity,
                "common_terminal_voltage_v": voltage,
                "segment_count": segment_count,
                "source_numeric_current_ceiling_a_m2": source_ceiling,
                "elevated_numeric_current_ceiling_a_m2": source_ceiling * multiplier,
                "numeric_ceiling_multiplier": multiplier,
                "source_status": source_row["status"],
                "elevated_status": elevated_row["status"],
                "source_high_bracket_encountered": bool(
                    source_row.get(
                        "legacy_numeric_current_search_ceiling_encountered", False
                    )
                ),
                "elevated_high_bracket_encountered": bool(
                    elevated_row.get(
                        "legacy_numeric_current_search_ceiling_encountered", False
                    )
                ),
                "source_resolution_class": source_row["resolution_class"],
                "elevated_resolution_class": elevated_resolution,
                "source_common_voltage_feasible": bool(
                    source_row["common_voltage_feasible"]
                ),
                "elevated_common_voltage_feasible": bool(
                    elevated_row["common_voltage_feasible"]
                ),
                "status_unchanged": bool(source_row["status"] == elevated_row["status"]),
                "resolution_class_unchanged": bool(
                    source_row["resolution_class"]
                    == elevated_row["resolution_class"]
                ),
                "feasibility_unchanged": bool(
                    bool(source_row["common_voltage_feasible"])
                    == bool(elevated_row["common_voltage_feasible"])
                ),
                "retry_recovered": retry_recovered,
                "source_current_density_gate_applied": bool(
                    source_row.get("current_density_gate_applied", False)
                ),
                "elevated_current_density_gate_applied": bool(
                    elevated_row.get("current_density_gate_applied", False)
                ),
                "source_area_is_acceptance_gate": bool(
                    source_row.get("area_is_acceptance_gate", False)
                ),
                "elevated_area_is_acceptance_gate": bool(
                    elevated_row.get("area_is_acceptance_gate", False)
                ),
                "source_surface_direction_is_acceptance_gate": bool(
                    source_row.get("surface_direction_is_acceptance_gate", False)
                ),
                "elevated_surface_direction_is_acceptance_gate": bool(
                    elevated_row.get("surface_direction_is_acceptance_gate", False)
                ),
                "elevated_transport_solution_complete": bool(
                    elevated_row.get("transport_solution_complete", False)
                ),
                "elevated_transport_water_balance_pass": bool(
                    elevated_row.get("transport_water_balance_pass", False)
                ),
                "elevated_terminal_voltage_solution_pass": bool(
                    elevated_row.get("terminal_voltage_solution_pass", False)
                ),
                "elevated_thermodynamic_consistency_pass": bool(
                    elevated_row.get("thermodynamic_consistency_pass", False)
                ),
                "elevated_required_active_area_m2": elevated_row.get(
                    "required_active_area_m2", math.nan
                ),
                "elevated_minimum_local_current_density_a_m2": elevated_row.get(
                    "minimum_local_current_density_a_m2", math.nan
                ),
                "elevated_maximum_local_current_density_a_m2": elevated_row.get(
                    "maximum_local_current_density_a_m2", math.nan
                ),
                "interpretation": (
                    "The V2 label can reflect either its numeric ceiling or the "
                    "physical-current high bracket. Only a fully closed retry is "
                    "promoted; every other source remains numerical/local unresolved."
                ),
            }
        )

    effective_cases = pd.DataFrame([effective_by_id[case_id] for case_id in order])
    effective_profiles = profiles.copy()
    if recovered_profiles:
        if "case_id" not in effective_profiles:
            raise WorkshopStudyError("Profiles lack case_id during bracket recovery")
        recovered_ids = set(recovered_profiles)
        retained = effective_profiles.loc[
            ~effective_profiles["case_id"].astype(str).isin(recovered_ids)
        ]
        effective_profiles = pd.concat(
            [retained, *recovered_profiles.values()], ignore_index=True
        )
        sort_columns = [
            column
            for column in (
                "target_id",
                "water_diffusivity_m2_s",
                "common_terminal_voltage_v",
                "study_segment_count",
                "segment_index",
            )
            if column in effective_profiles
        ]
        if sort_columns:
            effective_profiles = effective_profiles.sort_values(
                sort_columns, kind="mergesort"
            ).reset_index(drop=True)
    return effective_cases, effective_profiles, pd.DataFrame(rows)


def _format_number(value: Any, digits: int = 3) -> str:
    converted = _finite(value)
    return f"{converted:.{digits}f}" if math.isfinite(converted) else "--"


def plot_composite(
    output_dir: Path,
    *,
    cases: pd.DataFrame,
    envelope: pd.DataFrame,
    config: Mapping[str, Any],
    plt: Any,
) -> None:
    """Write the workshop-facing feasibility, saving and area composite."""

    from matplotlib.lines import Line2D

    figure_dir = output_dir / "figures"
    figure_dir.mkdir(parents=True, exist_ok=True)
    refined = cases.loc[
        cases["segment_count"].eq(int(config["selected_segment_count"]))
    ].copy()
    target_styles = {
        "o30": ("#1565C0", 0.94, "O30"),
        "full_remaining_latent": ("#D55E00", 1.06, "Full remaining duty"),
    }
    fig, axes = plt.subplots(1, 3, figsize=(14.2, 4.7))

    feasibility_ax = axes[0]
    for target_id, (color, offset, _) in target_styles.items():
        subset = refined.loc[refined["target_id"].eq(target_id)]
        for diffusivity, group in subset.groupby("water_diffusivity_m2_s", sort=True):
            x_value = float(diffusivity) * offset
            feasible = group["common_voltage_feasible"].fillna(False).astype(bool)
            if feasible.any():
                feasible_voltage = pd.to_numeric(
                    group.loc[feasible, "common_terminal_voltage_v"], errors="coerce"
                )
                feasibility_ax.plot(
                    [x_value, x_value],
                    [feasible_voltage.min(), feasible_voltage.max()],
                    color=color,
                    linewidth=2.0,
                    alpha=0.7,
                    zorder=1,
                )
            feasibility_ax.scatter(
                np.full(int(feasible.sum()), x_value),
                pd.to_numeric(
                    group.loc[feasible, "common_terminal_voltage_v"], errors="coerce"
                ),
                color=color,
                marker="o",
                s=28,
                zorder=3,
            )
            physical_no_solution = group["resolution_class"].eq(
                "PHYSICAL_NO_COMMON_VOLTAGE_AT_THIS_COORDINATE"
            )
            numerical_or_local_failure = group["resolution_class"].eq(
                "NUMERICAL_OR_LOCAL_SOLUTION_FAILURE"
            )
            feasibility_ax.scatter(
                np.full(int(physical_no_solution.sum()), x_value),
                pd.to_numeric(
                    group.loc[physical_no_solution, "common_terminal_voltage_v"],
                    errors="coerce",
                ),
                color=color,
                marker="x",
                s=28,
                linewidths=1.2,
                alpha=0.55,
                zorder=2,
            )
            feasibility_ax.scatter(
                np.full(int(numerical_or_local_failure.sum()), x_value),
                pd.to_numeric(
                    group.loc[
                        numerical_or_local_failure, "common_terminal_voltage_v"
                    ],
                    errors="coerce",
                ),
                facecolors="none",
                edgecolors=color,
                marker="^",
                s=34,
                linewidths=1.2,
                alpha=0.7,
                zorder=2,
            )
    feasibility_ax.set_xscale("log")
    feasibility_ax.set_ylim(0.4, 2.1)
    feasibility_ax.set_xlabel("Water diffusivity D [m²/s]")
    feasibility_ax.set_ylabel("Common terminal voltage [V]")
    feasibility_ax.set_title("Sampled common-voltage window")
    feasibility_ax.grid(True, which="both", alpha=0.22)
    feasibility_ax.legend(
        handles=[
            Line2D([0], [0], color=target_styles[target][0], marker="o", lw=2,
                   label=target_styles[target][2])
            for target in target_styles
        ]
        + [
            Line2D([0], [0], color="0.35", marker="x", lw=0,
                   label="Physical no-solution point"),
            Line2D([0], [0], color="0.35", marker="^", markerfacecolor="none",
                   lw=0, label="Numerical/local unresolved point"),
        ],
        fontsize=8,
        loc="best",
    )

    saving_ax, area_ax = axes[1], axes[2]
    for target_id, (color, _, label) in target_styles.items():
        subset = envelope.loc[envelope["target_id"].eq(target_id)].sort_values(
            "water_diffusivity_m2_s"
        )
        x_values = pd.to_numeric(subset["water_diffusivity_m2_s"], errors="coerce")
        selected = subset["selected_case_id"].notna()
        confirmed = subset["selection_status"].eq(
            "NUMERICALLY_CONFIRMED_FEASIBLE_VOLTAGE"
        )
        saving_values = pd.to_numeric(
            subset["selected_conditional_conservative_saving_kw_vs_erv_ac"],
            errors="coerce",
        )
        area_values = pd.to_numeric(
            subset["selected_required_active_area_m2"], errors="coerce"
        )
        valid_saving = selected & np.isfinite(saving_values)
        valid_area = selected & np.isfinite(area_values) & area_values.gt(0.0)
        saving_ax.plot(
            x_values[valid_saving], saving_values[valid_saving], color=color,
            linewidth=1.6, alpha=0.8, label=label,
        )
        area_ax.plot(
            x_values[valid_area], area_values[valid_area], color=color,
            linewidth=1.6, alpha=0.8, label=label,
        )
        for mask, marker, face in (
            (valid_saving & confirmed, "o", color),
            (valid_saving & ~confirmed, "o", "white"),
        ):
            saving_ax.scatter(
                x_values[mask], saving_values[mask], marker=marker, s=42,
                facecolors=face, edgecolors=color, zorder=3,
            )
        for mask, marker, face in (
            (valid_area & confirmed, "o", color),
            (valid_area & ~confirmed, "o", "white"),
        ):
            area_ax.scatter(
                x_values[mask], area_values[mask], marker=marker, s=42,
                facecolors=face, edgecolors=color, zorder=3,
            )
        if not valid_saving.any():
            saving_ax.text(
                0.97, 0.94, f"{label}: no feasible sampled value",
                color=color, transform=saving_ax.transAxes, ha="right", va="top",
                fontsize=8.5,
            )
        if not valid_area.any():
            area_ax.text(
                0.97, 0.94, f"{label}: no feasible sampled value",
                color=color, transform=area_ax.transAxes, ha="right", va="top",
                fontsize=8.5,
            )

    saving_ax.axhline(0.0, color="0.35", linewidth=0.9)
    saving_ax.set_xscale("log")
    saving_ax.set_xlabel("Water diffusivity D [m²/s]")
    saving_ax.set_ylabel("Best conditional saving [kW]")
    saving_ax.set_title("Best sampled conditional saving")
    saving_ax.grid(True, which="both", alpha=0.22)
    saving_ax.legend(fontsize=8, loc="best")

    area_ax.axhline(
        float(config["transport"]["area_observation_cap_m2"]),
        color="0.35", linestyle="--", linewidth=1.0,
        label="Observation cap (not a gate)",
    )
    area_ax.set_xscale("log")
    area_ax.set_yscale("log")
    area_ax.set_xlabel("Water diffusivity D [m²/s]")
    area_ax.set_ylabel("Selected active area [m²]")
    area_ax.set_title("Area at best sampled point")
    area_ax.grid(True, which="both", alpha=0.22)
    area_ax.legend(fontsize=8, loc="best")

    fig.suptitle(
        "Hypothetical inverse-design vector: common-voltage diffusivity cross-check",
        fontsize=13,
    )
    fig.text(
        0.5,
        0.01,
        "Filled = 8/16-segment confirmed; triangles in the left panel = unresolved local bracket. "
        "Receiver/sink and EO heat rejection excluded.",
        ha="center",
        fontsize=8.5,
    )
    fig.tight_layout(rect=(0.0, 0.055, 1.0, 0.94))
    for suffix in ("png", "pdf"):
        fig.savefig(
            figure_dir / f"workshop_common_voltage_diffusivity.{suffix}",
            dpi=220,
            bbox_inches="tight",
        )
    plt.close(fig)


def write_readme(
    path: Path,
    *,
    config: Mapping[str, Any],
    cases: pd.DataFrame,
    convergence: pd.DataFrame,
    envelope: pd.DataFrame,
    bracket_probe: pd.DataFrame,
    baseline_kw: float,
) -> None:
    selected_count = int(
        envelope["selection_status"].eq("NUMERICALLY_CONFIRMED_FEASIBLE_VOLTAGE").sum()
    )
    refined = cases.loc[
        cases["segment_count"].eq(int(config["selected_segment_count"]))
    ]
    full_refined = refined.loc[refined["target_id"].eq("full_remaining_latent")]
    full_physical_count = int(
        full_refined["resolution_class"]
        .eq("PHYSICAL_NO_COMMON_VOLTAGE_AT_THIS_COORDINATE")
        .sum()
    )
    full_unresolved_count = int(
        full_refined["resolution_class"]
        .eq("NUMERICAL_OR_LOCAL_SOLUTION_FAILURE")
        .sum()
    )
    recovered_probe_count = int(bracket_probe["retry_recovered"].astype(bool).sum())
    unresolved_probe_count = len(bracket_probe) - recovered_probe_count
    source_probe_ceiling = float(
        bracket_probe["source_numeric_current_ceiling_a_m2"].iloc[0]
    )
    elevated_probe_ceiling = float(
        bracket_probe["elevated_numeric_current_ceiling_a_m2"].iloc[0]
    )
    lines = [
        "# Workshop common-voltage diffusivity cross-check v1",
        "",
        "This is a bounded post-ERV screening calculation for the hypothetical "
        "Terminal-1 inverse-design membrane. Only water diffusivity is varied.",
        "",
        "## Frozen boundary",
        "",
        f"- Passive ERV + AC reference: **{baseline_kw:.6f} kW**.",
        "- Targets: O30 and the full remaining latent duty to the 20 C / 50% RH supply humidity ratio.",
        "- Electrical topology: one common terminal voltage with local parallel current sharing.",
        f"- Tested common voltages: {min(config['terminal_voltages_v']):g}--{max(config['terminal_voltages_v']):g} V; no point exceeds 2 V.",
        "- No current-density acceptance gate and no active-area acceptance gate are used.",
        "- Feasibility requires endpoint validity, transport/water closure, terminal-voltage closure and the local thermodynamic audit.",
        "",
        "## Refined diffusivity envelope",
        "",
        "| Target | D [m²/s] | Feasible sampled V | Confirmed count | Physical no-solution count | Numerical/local unresolved count | Selected V | Area [m²] | Known EO+fan [kW] | SEC [kWh/kg] | Conservative conditional saving [kW] |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in envelope.to_dict("records"):
        span = (
            f"{_format_number(row['minimum_refined_feasible_voltage_v'], 2)}--"
            f"{_format_number(row['maximum_refined_feasible_voltage_v'], 2)}"
            if int(row["refined_feasible_voltage_count"]) > 0
            else "none"
        )
        lines.append(
            "| {target} | {d:.6e} | {span} | {confirmed} | {physical} | "
            "{unresolved} | {voltage} | {area} | "
            "{power} | {sec} | {saving} |".format(
                target=row["target_id"],
                d=float(row["water_diffusivity_m2_s"]),
                span=span,
                confirmed=int(row["numerically_confirmed_voltage_count"]),
                physical=int(row["refined_physical_no_solution_voltage_count"]),
                unresolved=int(
                    row["refined_numerical_or_local_unresolved_voltage_count"]
                ),
                voltage=_format_number(row["selected_common_terminal_voltage_v"], 2),
                area=_format_number(row["selected_required_active_area_m2"], 1),
                power=_format_number(
                    row["selected_known_eo_grid_and_module_fan_power_kw"], 3
                ),
                sec=_format_number(
                    row["selected_known_eo_grid_and_module_fan_sec_kwh_per_kg"],
                    5,
                ),
                saving=_format_number(
                    row["selected_conditional_conservative_saving_kw_vs_erv_ac"],
                    3,
                ),
            )
        )
    lines.extend(
        [
            "",
            "## Workshop figure",
            "",
            "See `figures/workshop_common_voltage_diffusivity.png` (and the PDF equivalent). In the left panel, crosses are physical no-solution results at the sampled voltage and open triangles are unresolved numerical/local high-bracket results. The saving and area panels explicitly state when a target has no feasible sampled value.",
            "",
            "## Result status",
            "",
            f"- Evaluated cases: {len(cases)}.",
            f"- Refined feasible cases: {int(cases.loc[cases['segment_count'].eq(int(config['selected_segment_count'])), 'common_voltage_feasible'].sum())}.",
            f"- Target/diffusivity coordinates with at least one numerically confirmed sampled voltage: {selected_count}/{len(envelope)}.",
            f"- Stable sampled feasibility classifications between the two segment counts: {int(convergence['sampled_feasibility_status_stable'].sum())}/{len(convergence)}.",
            f"- Refined sampled points unresolved by the numerical/local bracket: {int(refined['resolution_class'].eq('NUMERICAL_OR_LOCAL_SOLUTION_FAILURE').sum())}.",
            f"- Full remaining duty: 0/{len(full_refined)} refined sampled voltages are feasible; {full_physical_count} are physical no-solution results and {full_unresolved_count} remain numerical/local-bracket unresolved. This is no demonstrated <=2 V solution, not a global physical no-go proof.",
            "",
            "## Local-bracket sensitivity probe",
            "",
            f"Every flagged <=2 V case at both segment counts was retried after raising only the configured numerical current bound by {float(config['local_bracket_probe']['numeric_ceiling_multiplier']):g}x ({source_probe_ceiling:,.0f} to {elevated_probe_ceiling:,.0f} A/m²). {recovered_probe_count}/{len(bracket_probe)} retries recovered full closure and replaced their source rows and profiles; {unresolved_probe_count}/{len(bracket_probe)} remain numerical/local unresolved. The V2 high bracket also contains a physical-current limit, so an unrecovered retry is not promoted to a physical no-go. See `local_bracket_probe.csv`.",
            "",
            "## Energy interpretation",
            "",
            "The primary power column uses the frozen control-conservative avoided-AC boundary and subtracts EO grid power plus the frozen area-based process/receiver module-fan term. The CSV also retains the exact-endpoint coil result as a separate diagnostic. Receiver/sink energy and EO heat rejection are not modelled; therefore the reported saving and receiver SEC room are conditional budgets, not complete-system savings.",
            "",
            "## Limitations",
            "",
            "- The Terminal-1 vector is an inverse-design coordinate, not measured material data.",
            "- Only D changes; correlated changes in sorption, conductivity, drag and thickness are excluded.",
            "- The receiver is the balanced post-ERV exhaust gas stream, not a liquid-out boundary.",
            "- The reduced-order model prescribes stream endpoints and linearly segmented bulk states; it is not a conjugate heat-and-mass-transfer solution.",
            "- The 0.25-V grid can miss a narrow feasible voltage interval. `none` means no feasible sampled point, not a mathematical no-go proof.",
            "- `above_internal_current_search_ceiling` is a legacy ambiguous status: the V2 high bracket is the lower of a physical-current limit and a configured numeric bound. Every flagged <=2 V case is retried at 100x the numeric bound; any unrecovered row remains unresolved/local-bracket-limited and is neither an engineering current-density rejection nor, by status alone, a physical no-go proof.",
            f"- Numerical refinement is only {min(config['segment_counts'])} to {max(config['segment_counts'])} segments. Unconfirmed rows require a targeted 32/64-segment replay before design use.",
            "- Area is reported even above the observation cap, but is never used to determine feasibility.",
            "",
            "## Reproduction",
            "",
            "```bash",
            "python3 -B scripts/run_workshop_common_voltage_diffusivity_v1.py --overwrite",
            "```",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    config_path = resolve_path(args.config)
    output_path = resolve_path(args.output_dir)
    config = read_json(config_path)
    validate_config(config)
    prepare_output(output_path, args.overwrite)

    closure_script = ROOT / "scripts" / "run_project_closure_check_v1.py"
    closure = load_module(closure_script, "workshop_common_voltage_closure_source")
    closure_config_path = resolve_path(config["source_project_closure_config"])
    closure_config = read_json(closure_config_path)
    v2_root = resolve_path(config["source_v2_root"])
    _, runtime, source_config, analyzer_path = closure.load_runtime(
        closure_config, v2_root
    )
    active_config_path = resolve_path(closure_config["source_active_erv_config"])
    active_config = read_json(active_config_path)
    effective_config = closure.effective_common_voltage_config(
        closure_config, active_config
    )
    effective_config["solver"]["area_observation_cap_m2"] = float(
        config["transport"]["area_observation_cap_m2"]
    )
    effective_config["electrical"]["maximum_terminal_voltage_v"] = 2.0
    effective_config["electrical"]["engineering_current_density_limit_a_m2"] = None

    percentage_path = resolve_path(config["source_percentage_summary"])
    percentage_summary = pd.read_csv(percentage_path)
    baseline_kw = float(runtime["baseline"].total_power_kw)
    expected_baseline = float(
        closure_config["frozen_claim_contract"]
        ["modern_passive_erv_plus_ac_reference_kw"]
    )
    if not math.isclose(baseline_kw, expected_baseline, rel_tol=0.0, abs_tol=5.0e-7):
        raise WorkshopStudyError(
            f"Baseline mismatch: runtime={baseline_kw:.12f}, contract={expected_baseline:.12f}"
        )

    rows: list[dict[str, Any]] = []
    profiles: list[pd.DataFrame] = []
    for target in config["targets"]:
        for diffusivity in config["water_diffusivity_m2_s"]:
            print(
                f"Running {target['target_id']} at D={float(diffusivity):.6e}",
                flush=True,
            )
            for voltage in config["terminal_voltages_v"]:
                for segment_count in config["segment_counts"]:
                    row, profile = run_case(
                        target=target,
                        diffusivity=float(diffusivity),
                        voltage=float(voltage),
                        segment_count=int(segment_count),
                        config=config,
                        closure=closure,
                        closure_config=closure_config,
                        runtime=runtime,
                        source_config=source_config,
                        effective_config=effective_config,
                        percentage_summary=percentage_summary,
                    )
                    rows.append(row)
                    if not profile.empty:
                        profiles.append(profile)

    initial_cases = pd.DataFrame(rows).sort_values(
        [
            "target_id",
            "water_diffusivity_m2_s",
            "common_terminal_voltage_v",
            "segment_count",
        ],
        kind="mergesort",
    )
    profile_frame = (
        pd.concat(profiles, ignore_index=True) if profiles else pd.DataFrame()
    )
    cases, profile_frame, bracket_probe = run_local_bracket_probe(
        cases=initial_cases,
        profiles=profile_frame,
        config=config,
        closure=closure,
        closure_config=closure_config,
        runtime=runtime,
        source_config=source_config,
        effective_config=effective_config,
        percentage_summary=percentage_summary,
    )
    cases = cases.sort_values(
        [
            "target_id",
            "water_diffusivity_m2_s",
            "common_terminal_voltage_v",
            "segment_count",
        ],
        kind="mergesort",
    )
    convergence = build_segment_convergence(cases, config)
    envelope = build_diffusivity_envelope(cases, convergence, config)

    expected_cases = (
        len(config["targets"])
        * len(config["water_diffusivity_m2_s"])
        * len(config["terminal_voltages_v"])
        * len(config["segment_counts"])
    )
    energy_identity = (
        pd.to_numeric(
            cases["conditional_conservative_total_power_kw"], errors="coerce"
        )
        + pd.to_numeric(
            cases["conditional_conservative_saving_kw_vs_erv_ac"], errors="coerce"
        )
        - baseline_kw
    )
    finite_energy_identity = energy_identity[np.isfinite(energy_identity)]
    expected_retry_ids = set(
        initial_cases.loc[
            current_bracket_retry_source_mask(initial_cases), "case_id"
        ].astype(str)
    )
    actual_retry_ids = set(bracket_probe["source_case_id"].astype(str))
    recovered_retry_ids = set(
        bracket_probe.loc[
            bracket_probe["retry_recovered"].astype(bool), "source_case_id"
        ].astype(str)
    )
    unrecovered_probe = bracket_probe.loc[
        ~bracket_probe["retry_recovered"].astype(bool)
    ]
    recovered_probe = bracket_probe.loc[
        bracket_probe["retry_recovered"].astype(bool)
    ]
    checks = {
        "expected_case_count": len(cases) == expected_cases,
        "voltage_cap_respected": bool(
            pd.to_numeric(cases["common_terminal_voltage_v"]).le(2.0 + 1.0e-12).all()
        ),
        "no_current_density_gate": bool(
            not cases["current_density_gate_applied"].fillna(False).astype(bool).any()
        ),
        "no_area_acceptance_gate": bool(
            not cases["area_is_acceptance_gate"].fillna(False).astype(bool).any()
        ),
        "all_feasible_rows_pass_thermodynamics": bool(
            cases.loc[
                cases["common_voltage_feasible"].astype(bool),
                "thermodynamic_consistency_pass",
            ].astype(bool).all()
        ),
        "energy_identity": bool(
            not finite_energy_identity.empty
            and finite_energy_identity.abs().max() <= 1.0e-9
        ),
        "convergence_pair_count": len(convergence)
        == len(config["targets"])
        * len(config["water_diffusivity_m2_s"])
        * len(config["terminal_voltages_v"]),
        "envelope_coordinate_count": len(envelope)
        == len(config["targets"]) * len(config["water_diffusivity_m2_s"]),
        "local_bracket_probe_exact_source_coverage": bool(
            len(bracket_probe) == len(expected_retry_ids)
            and not bracket_probe["source_case_id"].astype(str).duplicated().any()
            and actual_retry_ids == expected_retry_ids
            and bracket_probe["source_high_bracket_encountered"].astype(bool).all()
        ),
        "local_bracket_probe_voltage_cap_respected": bool(
            pd.to_numeric(bracket_probe["common_terminal_voltage_v"], errors="coerce")
            .le(2.0 + 1.0e-12)
            .all()
        ),
        "local_bracket_probe_elevates_only_numeric_bound": bool(
            (
                pd.to_numeric(
                    bracket_probe["elevated_numeric_current_ceiling_a_m2"],
                    errors="coerce",
                )
                > pd.to_numeric(
                    bracket_probe["source_numeric_current_ceiling_a_m2"],
                    errors="coerce",
                )
            ).all()
            and not bracket_probe[
                [
                    "source_current_density_gate_applied",
                    "elevated_current_density_gate_applied",
                    "source_area_is_acceptance_gate",
                    "elevated_area_is_acceptance_gate",
                    "source_surface_direction_is_acceptance_gate",
                    "elevated_surface_direction_is_acceptance_gate",
                ]
            ]
            .fillna(False)
            .astype(bool)
            .any()
            .any()
        ),
        "unrecovered_high_bracket_cases_remain_unresolved": bool(
            unrecovered_probe["elevated_resolution_class"]
            .eq("NUMERICAL_OR_LOCAL_SOLUTION_FAILURE")
            .all()
        ),
        "recovered_high_bracket_cases_pass_full_closure": bool(
            recovered_probe[
                [
                    "elevated_common_voltage_feasible",
                    "elevated_transport_solution_complete",
                    "elevated_transport_water_balance_pass",
                    "elevated_terminal_voltage_solution_pass",
                    "elevated_thermodynamic_consistency_pass",
                ]
            ]
            .astype(bool)
            .all()
            .all()
            and cases.loc[
                cases["case_id"].astype(str).isin(recovered_retry_ids),
                "common_voltage_feasible",
            ]
            .astype(bool)
            .all()
        ),
        "legacy_high_bracket_status_is_fail_closed": bool(
            cases.loc[
                current_bracket_retry_source_mask(cases),
                "resolution_class",
            ]
            .eq("NUMERICAL_OR_LOCAL_SOLUTION_FAILURE")
            .all()
        ),
    }
    audit = {
        "study_id": config["study_id"],
        "script_version": SCRIPT_VERSION,
        "passed": all(checks.values()),
        "checks": checks,
        "case_count": len(cases),
        "profile_row_count": len(profile_frame),
        "refined_feasible_case_count": int(
            cases.loc[
                cases["segment_count"].eq(int(config["selected_segment_count"])),
                "common_voltage_feasible",
            ].sum()
        ),
        "numerically_confirmed_envelope_coordinate_count": int(
            envelope["selection_status"]
            .eq("NUMERICALLY_CONFIRMED_FEASIBLE_VOLTAGE")
            .sum()
        ),
        "refined_numerical_or_local_unresolved_case_count": int(
            cases.loc[
                cases["segment_count"].eq(int(config["selected_segment_count"])),
                "resolution_class",
            ]
            .eq("NUMERICAL_OR_LOCAL_SOLUTION_FAILURE")
            .sum()
        ),
        "local_bracket_probe_case_count": len(bracket_probe),
        "local_bracket_probe_recovered_case_count": len(recovered_retry_ids),
        "local_bracket_probe_unrecovered_case_count": int(
            len(bracket_probe) - len(recovered_retry_ids)
        ),
        "maximum_energy_identity_error_kw": (
            float(finite_energy_identity.abs().max())
            if not finite_energy_identity.empty
            else None
        ),
        "full_system_claim_allowed": False,
    }
    if not audit["passed"]:
        failed = [name for name, passed in checks.items() if not passed]
        raise WorkshopStudyError("Study audit failed: " + ", ".join(failed))

    cases.to_csv(output_path / "cases.csv", index=False)
    convergence.to_csv(output_path / "segment_convergence.csv", index=False)
    envelope.to_csv(output_path / "diffusivity_envelope.csv", index=False)
    bracket_probe.to_csv(output_path / "local_bracket_probe.csv", index=False)
    profile_frame.to_csv(
        output_path / "segment_profiles.csv.gz", index=False, compression="gzip"
    )
    write_json(output_path / "config_used.json", config)
    write_json(output_path / "audit.json", audit)
    plot_composite(
        output_path,
        cases=cases,
        envelope=envelope,
        config=config,
        plt=closure.plt,
    )
    manifest_paths = {
        "study_config": config_path,
        "project_closure_config": closure_config_path,
        "percentage_summary": percentage_path,
        "active_erv_config": active_config_path,
        "runner": Path(__file__).resolve(),
        "closure_runner": closure_script,
        "post_erv_analyzer": Path(analyzer_path),
        "active_erv_module": ROOT / "src" / "heiq" / "wp1" / "studies" / "direct_eo_erv.py",
        "thermodynamic_module": ROOT / "src" / "heiq" / "wp1" / "membrane" / "thermodynamics.py",
        "v2_model": v2_root / "heiq_pre_receiver_material_analyses" / "heiq_pre_receiver_model.py",
    }
    write_json(
        output_path / "source_manifest.json",
        {
            "study_id": config["study_id"],
            "files": {
                name: {
                    "path": str(path.resolve()),
                    "sha256": sha256_file(path.resolve()),
                }
                for name, path in manifest_paths.items()
            },
        },
    )
    write_readme(
        output_path / "README.md",
        config=config,
        cases=cases,
        convergence=convergence,
        envelope=envelope,
        bracket_probe=bracket_probe,
        baseline_kw=baseline_kw,
    )
    print(
        f"Wrote {len(cases)} cases and {len(envelope)} diffusivity coordinates "
        f"to {output_path}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
