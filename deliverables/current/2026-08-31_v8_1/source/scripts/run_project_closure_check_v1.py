#!/usr/bin/env python3
"""Run the bounded final modelling audit before material scouting.

This workflow does four things and deliberately does not launch a new broad
material sweep:

1. Re-audits stored active-ERV segments with the electrochemical dissipation
   inequality instead of treating a passive activity gradient as mandatory.
2. Replays frozen post-ERV targets on one common terminal-voltage bus, with
   local current sharing, and samples the bounded 0.5--2.0 V topology range.
3. Re-runs selected uniform-current anchors at smaller area steps and checks
   the voltage roots independently with Brent's method.
4. Emits machine-readable project gates for model closure, material-data
   collection, candidate ranking, receiver closure and release hygiene.

The result is still a screening model.  It does not validate a material,
receiver, electrode, module, durability or complete HVAC system.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import math
import os
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

os.environ.setdefault("MPLCONFIGDIR", "/tmp/heiq-project-closure-check-v1-mpl")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.optimize import brentq

from heiq.wp1.membrane.thermodynamics import audit_local_record
from heiq.wp1.studies.active_erv import (
    ActiveEndpoints,
    solve_segmented_transport,
    state_from_t_w,
)


SCRIPT_VERSION = "project-closure-check-v1.1-2026-08-28"
MOLAR_MASS_WATER_KG_MOL = 0.01801528


class ClosureCheckError(RuntimeError):
    """Raised when an input contract or audit invariant is broken."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description="Bounded project-closure audit before material scouting.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "config" / "project_closure_check_v1.json",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "outputs" / "project_closure_check_v1",
    )
    parser.add_argument(
        "--v2-root", type=Path, default=Path("/home/torsheim/HeiQ/HeiQ_V2")
    )
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--skip-uniform-current-replay",
        action="store_true",
        help="Skip the slower 20/10/5 m2 legacy-current convergence replay.",
    )
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        if np.isnan(value):
            return None
        if np.isposinf(value):
            return "Infinity"
        if np.isneginf(value):
            return "-Infinity"
        return float(value)
    if isinstance(value, Path):
        return str(value)
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(json_safe(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ClosureCheckError(f"Cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def scalar(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        if value.size != 1:
            raise ClosureCheckError(f"Expected scalar array, got {value.shape}")
        return value.reshape(-1)[0].item()
    if isinstance(value, np.generic):
        return value.item()
    return value


def truth(value: Any) -> bool:
    value = scalar(value)
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def bool_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        return pd.Series(False, index=frame.index, dtype=bool)
    series = frame[column]
    if series.dtype == bool:
        return series.fillna(False)
    return series.astype(str).str.strip().str.lower().isin(
        {"true", "1", "yes", "y"}
    )


def prepare_output(path: Path, overwrite: bool) -> None:
    path.mkdir(parents=True, exist_ok=True)
    existing = [item for item in path.iterdir() if item.name != ".gitkeep"]
    if existing and not overwrite:
        raise ClosureCheckError(
            f"Output directory is not empty: {path}; use --overwrite to replace "
            "the known generated artifacts."
        )
    if overwrite:
        known = {
            "active_erv_reclassification.csv",
            "active_erv_thermodynamic_audit.csv.gz",
            "common_voltage_cases.csv",
            "common_voltage_profiles.csv.gz",
            "common_voltage_convergence.csv",
            "common_voltage_window_scan.csv",
            "common_voltage_window_summary.csv",
            "independent_voltage_root_replay.csv",
            "uniform_current_convergence.csv",
            "decision_gate_register.csv",
            "closure_status.json",
            "source_manifest.json",
            "SUMMARY.md",
        }
        for name in known:
            (path / name).unlink(missing_ok=True)
        figures = path / "figures"
        if figures.is_dir():
            for name in (
                "closure_common_voltage.png",
                "closure_common_voltage.pdf",
            ):
                (figures / name).unlink(missing_ok=True)


def load_runtime(
    config: Mapping[str, Any], v2_root: Path
) -> tuple[ModuleType, dict[str, Any], dict[str, Any], Path]:
    source_config_path = resolve_path(config["source_operating_region_config"])
    source_config = read_json(source_config_path)
    analyzer_path = ROOT / "scripts" / "analyze_post_erv_inverse_design_v1.py"
    analyzer = load_module(analyzer_path, "project_closure_post_erv_source")
    paths = analyzer.resolve_paths(v2_root, source_config_path)
    runtime = analyzer.load_runtime(paths, source_config, area_step_m2=10.0)
    return analyzer, runtime, source_config, analyzer_path


def anchor_material(runtime: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "name": "terminal1_post_erv_anchor",
        "model": "powerlaw",
        **{
            key: float(runtime["anchor"][key])
            for key in (
                "water_drag",
                "water_diffusivity_m2_s",
                "conductivity_s_m",
                "dry_thickness_um",
                "water_capacity_mol_m3_activity",
                "diffusivity_activity_exponent",
                "conductivity_activity_exponent",
                "capacity_activity_exponent",
            )
        },
    }


def completion_target_w(runtime: Mapping[str, Any], completion_pct: float) -> float:
    inlet = float(runtime["process_in"].w)
    supply = float(runtime["baseline"].remaining_ac.supply.w)
    fraction = float(completion_pct) / 100.0
    if not 0.0 < fraction <= 1.0:
        raise ClosureCheckError(f"Completion must lie in (0, 100], got {completion_pct}")
    return inlet - fraction * (inlet - supply)


def post_erv_endpoints(
    runtime: Mapping[str, Any], completion_pct: float
) -> ActiveEndpoints:
    pressure = float(runtime["pressure_pa"])
    process_in = state_from_t_w(
        float(runtime["process_in"].t_c),
        float(runtime["process_in"].w),
        pressure,
        "post-ERV process inlet",
    )
    exhaust_in = state_from_t_w(
        float(runtime["receiver_in"].t_c),
        float(runtime["receiver_in"].w),
        pressure,
        "post-ERV balanced exhaust inlet",
    )
    target_w = completion_target_w(runtime, completion_pct)
    m_process = float(runtime["dry_air_mass_flow_kg_s"])
    m_exhaust = m_process
    water_kg_s = m_process * (process_in.w - target_w)
    exhaust_out_w = exhaust_in.w + water_kg_s / m_exhaust
    process_out = state_from_t_w(
        process_in.t_c, target_w, pressure, "post-EO process outlet"
    )
    exhaust_out = state_from_t_w(
        exhaust_in.t_c,
        exhaust_out_w,
        pressure,
        "post-EO balanced receiver outlet",
    )
    water_residual = (
        m_process * (process_in.w - process_out.w)
        - m_exhaust * (exhaust_out.w - exhaust_in.w)
    )
    return ActiveEndpoints(
        process_in=process_in,
        exhaust_in=exhaust_in,
        process_out=process_out,
        exhaust_out=exhaust_out,
        process_dry_air_kg_s=m_process,
        exhaust_dry_air_kg_s=m_exhaust,
        sensible_effectiveness=0.0,
        active_latent_effectiveness=math.nan,
        water_transfer_kg_h=water_kg_s * 3600.0,
        water_balance_residual_kg_s=water_residual,
        base_enthalpy_balance_residual_kw=math.nan,
        process_heat_kw=0.0,
        exhaust_heat_kw=0.0,
        externally_rejected_heat_kw=0.0,
        condensation_required=bool(
            process_out.rh > 1.0 + 1.0e-9 or exhaust_out.rh > 1.0 + 1.0e-9
        ),
        valid=bool(
            process_out.rh <= 1.0 + 1.0e-9
            and exhaust_out.rh <= 1.0 + 1.0e-9
            and abs(water_residual) <= 1.0e-10
        ),
    )


def effective_common_voltage_config(
    config: Mapping[str, Any], active_config: Mapping[str, Any]
) -> dict[str, Any]:
    effective = copy.deepcopy(dict(active_config))
    replay = config["common_voltage_replay"]
    effective["solver"]["activity_temperature_basis"] = "stream_bulk_rh"
    effective["solver"]["membrane_temperature_mode"] = "process_mean"
    effective["solver"]["area_observation_cap_m2"] = float(
        replay["area_observation_cap_m2"]
    )
    effective["electrical"]["maximum_terminal_voltage_v"] = float(
        config["frozen_claim_contract"]["hard_terminal_voltage_v"]
    )
    effective["electrical"]["preferred_terminal_voltage_v"] = float(
        config["frozen_claim_contract"]["preferred_terminal_voltage_v"]
    )
    effective["electrical"]["engineering_current_density_limit_a_m2"] = None
    effective["electrical"]["current_density_is_diagnostic_only"] = True
    return effective


def thermodynamic_profile_audit(
    profile: pd.DataFrame, tolerances: Mapping[str, Any]
) -> pd.DataFrame:
    if profile.empty:
        return profile.copy()
    rows: list[dict[str, Any]] = []
    for row in profile.to_dict("records"):
        audit = audit_local_record(
            row,
            temperature_c=float(row["membrane_temperature_c"]),
            identity_relative_tolerance=float(
                tolerances["thermodynamic_identity_relative"]
            ),
            nonnegative_power_tolerance_w_m2=float(
                tolerances["nonnegative_power_w_m2"]
            ),
        )
        rows.append({**row, **audit})
    return pd.DataFrame(rows)


def integrated_profile_value(profile: pd.DataFrame, column: str) -> float:
    if profile.empty or column not in profile:
        return math.nan
    density = pd.to_numeric(profile[column], errors="coerce")
    area = pd.to_numeric(profile["required_active_area_m2"], errors="coerce")
    if not (np.isfinite(density).all() and np.isfinite(area).all()):
        return math.nan
    return float((density * area).sum() / 1000.0)


def ac_reduction_at_completion(
    percentage_summary: pd.DataFrame, completion_pct: float
) -> float:
    completion = pd.to_numeric(
        percentage_summary["remaining_duty_completion_pct"], errors="coerce"
    )
    water = pd.to_numeric(
        percentage_summary["eo_water_removal_kg_h"], errors="coerce"
    )
    sec = pd.to_numeric(
        percentage_summary["control_conservative_break_even_sec_kwh_per_kg"],
        errors="coerce",
    )
    power = water * sec
    valid = np.isfinite(completion) & np.isfinite(power)
    if not valid.any():
        return math.nan
    order = np.argsort(completion[valid].to_numpy(float))
    x = completion[valid].to_numpy(float)[order]
    y = power[valid].to_numpy(float)[order]
    return float(np.interp(float(completion_pct), x, y))


def classify_replay_resolution(
    *, replay_pass: bool, transport_complete: bool, failure_reason: str
) -> str:
    if replay_pass:
        return "CONVERGED_TARGET"
    if failure_reason in {
        "below_reversible_voltage",
        "nonpositive_net_water_flux",
    }:
        return "PHYSICAL_NO_COMMON_VOLTAGE_AT_THIS_COORDINATE"
    if not transport_complete:
        return "NUMERICAL_OR_LOCAL_SOLUTION_FAILURE"
    return "DECLARED_GATE_FAILURE"


def decorate_common_result(
    result: Mapping[str, Any],
    profile: pd.DataFrame,
    *,
    case: Mapping[str, Any],
    endpoints: ActiveEndpoints,
    source_config: Mapping[str, Any],
    percentage_summary: pd.DataFrame,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    complete = truth(result.get("transport_solution_complete"))
    water_pass = truth(result.get("transport_water_balance_pass"))
    terminal_pass = truth(result.get("terminal_voltage_solution_pass"))
    area_pass = truth(result.get("area_cap_pass"))
    thermo_pass = bool(
        not profile.empty
        and bool_series(profile, "thermodynamic_consistency_pass").all()
    )
    uphill_fraction = (
        float(bool_series(profile, "uphill_active_transport").mean())
        if not profile.empty
        else math.nan
    )
    area = float(result.get("required_active_area_m2", math.nan))
    fan_kw_per_m2 = float(
        source_config["post_erv"]["process_and_receiver_fan_power_kw_per_m2"]
    )
    fan_kw = area * fan_kw_per_m2 if math.isfinite(area) else math.nan
    grid_kw = float(result.get("eo_grid_power_kw", math.nan))
    known_kw = grid_kw + fan_kw if complete and math.isfinite(fan_kw) else math.nan
    ac_reduction_kw = ac_reduction_at_completion(
        percentage_summary, float(case["remaining_duty_completion_pct"])
    )
    saving_kw = (
        ac_reduction_kw - known_kw
        if math.isfinite(ac_reduction_kw) and math.isfinite(known_kw)
        else math.nan
    )
    water_kg_h = float(endpoints.water_transfer_kg_h)
    receiver_budget = (
        saving_kw / water_kg_h
        if math.isfinite(saving_kw) and water_kg_h > 0.0
        else math.nan
    )
    hard_voltage = float(config["frozen_claim_contract"]["hard_terminal_voltage_v"])
    replay_pass = bool(
        endpoints.valid
        and complete
        and water_pass
        and terminal_pass
        and thermo_pass
        and float(case["terminal_voltage_v"]) <= hard_voltage + 1.0e-12
    )
    failure = str(result.get("transport_failure_reason", ""))
    resolution = classify_replay_resolution(
        replay_pass=replay_pass,
        transport_complete=complete,
        failure_reason=failure,
    )

    return {
        **dict(result),
        "case_id": str(case["case_id"]),
        "case_role": str(case["role"]),
        "remaining_duty_completion_pct": float(
            case["remaining_duty_completion_pct"]
        ),
        "target_w_kg_kg_da": float(endpoints.process_out.w),
        "target_water_transfer_kg_h": water_kg_h,
        "common_terminal_voltage_v": float(case["terminal_voltage_v"]),
        "electrical_topology": "single_common_voltage_parallel_current_sharing",
        "uniform_current_density_imposed": False,
        "current_density_gate_applied": False,
        "thermodynamic_consistency_pass": thermo_pass,
        "uphill_active_segment_fraction": uphill_fraction,
        "passive_surface_direction_everywhere": bool(
            truth(result.get("positive_surface_direction"))
        ),
        "surface_direction_interpretation": (
            "uphill_active_regime_indicator_not_hard_thermodynamic_gate"
            if uphill_fraction > 0.0
            else "downhill_or_neutral"
        ),
        "minimum_membrane_dissipation_density_w_m2": (
            float(
                pd.to_numeric(
                    profile["membrane_dissipation_density_w_m2"], errors="coerce"
                ).min()
            )
            if not profile.empty
            else math.nan
        ),
        "maximum_thermodynamic_identity_relative_error": (
            float(
                pd.to_numeric(
                    profile["dissipation_identity_relative_error"],
                    errors="coerce",
                ).abs().max()
            )
            if not profile.empty
            else math.nan
        ),
        "integrated_net_chemical_work_kw": integrated_profile_value(
            profile, "net_chemical_work_density_w_m2"
        ),
        "integrated_membrane_dissipation_kw": integrated_profile_value(
            profile, "membrane_dissipation_density_w_m2"
        ),
        "incremental_module_fan_power_kw": fan_kw,
        "known_grid_and_module_fan_power_kw": known_kw,
        "control_conservative_ac_reduction_kw": ac_reduction_kw,
        "conditional_saving_before_receiver_sink_kw": saving_kw,
        "conditional_receiver_sink_sec_budget_kwh_per_kg": receiver_budget,
        "conditional_energy_positive_before_receiver_sink": bool(
            math.isfinite(saving_kw) and saving_kw > 0.0
        ),
        "within_area_observation_cap": area_pass,
        "common_voltage_replay_pass": replay_pass,
        "resolution_status": resolution,
        "full_system_claim_allowed": False,
    }


def run_common_voltage_replays(
    config: Mapping[str, Any],
    runtime: Mapping[str, Any],
    source_config: Mapping[str, Any],
    percentage_summary: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    active_config = read_json(resolve_path(config["source_active_erv_config"]))
    effective = effective_common_voltage_config(config, active_config)
    material = anchor_material(runtime)
    replay = config["common_voltage_replay"]
    rows: list[dict[str, Any]] = []
    profiles: list[pd.DataFrame] = []
    for case in replay["cases"]:
        endpoints = post_erv_endpoints(
            runtime, float(case["remaining_duty_completion_pct"])
        )
        for segment_count in replay["segment_counts"]:
            result, profile = solve_segmented_transport(
                v2=runtime["v2"],
                v2_config=runtime["v2_config"],
                study_config=effective,
                endpoints=endpoints,
                material=material,
                terminal_voltage_v=float(case["terminal_voltage_v"]),
                fixed_loss_voltage_v=float(replay["fixed_loss_voltage_v"]),
                series_asr_ohm_m2=float(replay["series_asr_ohm_m2"]),
                film_scale_factor=float(replay["film_scale_factor"]),
                segment_count=int(segment_count),
            )
            audited = thermodynamic_profile_audit(
                profile, config["audit_tolerances"]
            )
            if not audited.empty:
                audited.insert(0, "case_id", str(case["case_id"]))
                audited.insert(1, "case_role", str(case["role"]))
                audited.insert(
                    2,
                    "remaining_duty_completion_pct",
                    float(case["remaining_duty_completion_pct"]),
                )
                profiles.append(audited)
            rows.append(
                decorate_common_result(
                    result,
                    audited,
                    case=case,
                    endpoints=endpoints,
                    source_config=source_config,
                    percentage_summary=percentage_summary,
                    config=config,
                )
            )
    return pd.DataFrame(rows), (
        pd.concat(profiles, ignore_index=True) if profiles else pd.DataFrame()
    )


def build_segment_convergence(
    cases: pd.DataFrame, config: Mapping[str, Any]
) -> pd.DataFrame:
    selected_count = int(
        config["common_voltage_replay"]["selected_segment_count"]
    )
    previous_counts = sorted(
        int(value)
        for value in config["common_voltage_replay"]["segment_counts"]
        if int(value) < selected_count
    )
    if not previous_counts:
        raise ClosureCheckError("At least two segment counts are required")
    previous_count = previous_counts[-1]
    tolerance = float(config["audit_tolerances"]["segment_area_relative_change"])
    rows: list[dict[str, Any]] = []
    for case_id, group in cases.groupby("case_id", sort=False):
        coarse = group.loc[group["segment_count"].eq(previous_count)]
        fine = group.loc[group["segment_count"].eq(selected_count)]
        if len(coarse) != 1 or len(fine) != 1:
            raise ClosureCheckError(f"Incomplete segment pair for {case_id}")
        left, right = coarse.iloc[0], fine.iloc[0]
        left_area = float(left.get("required_active_area_m2", math.nan))
        right_area = float(right.get("required_active_area_m2", math.nan))
        both_complete = truth(left["transport_solution_complete"]) and truth(
            right["transport_solution_complete"]
        )
        relative = (
            abs(right_area - left_area) / max(abs(right_area), 1.0e-12)
            if both_complete and math.isfinite(left_area) and math.isfinite(right_area)
            else math.nan
        )
        same_resolution = str(left["resolution_status"]) == str(
            right["resolution_status"]
        )
        numerical_failure_present = bool(
            str(left["resolution_status"])
            == "NUMERICAL_OR_LOCAL_SOLUTION_FAILURE"
            or str(right["resolution_status"])
            == "NUMERICAL_OR_LOCAL_SOLUTION_FAILURE"
        )
        repeated_physical_no_solution = bool(
            same_resolution
            and str(right["resolution_status"])
            == "PHYSICAL_NO_COMMON_VOLTAGE_AT_THIS_COORDINATE"
        )
        passed = bool(
            same_resolution
            and not numerical_failure_present
            and (
                relative <= tolerance
                if math.isfinite(relative)
                else repeated_physical_no_solution
            )
        )
        case_role = str(right["case_role"])
        model_closure_relevant = case_role not in {
            "negative_control",
            "hard_voltage_stress_point",
        }
        rows.append(
            {
                "case_id": case_id,
                "case_role": case_role,
                "model_closure_relevant": model_closure_relevant,
                "coarse_segment_count": previous_count,
                "refined_segment_count": selected_count,
                "coarse_resolution_status": left["resolution_status"],
                "refined_resolution_status": right["resolution_status"],
                "coarse_area_m2": left_area,
                "refined_area_m2": right_area,
                "area_relative_change": relative,
                "resolution_stable": same_resolution,
                "numerical_failure_present": numerical_failure_present,
                "convergence_pass": passed,
            }
        )
    return pd.DataFrame(rows)


def voltage_scan_values(section: Mapping[str, Any]) -> list[float]:
    low = float(section["minimum_terminal_voltage_v"])
    high = float(section["maximum_terminal_voltage_v"])
    step = float(section["terminal_voltage_step_v"])
    count = int(round((high - low) / step))
    values = [low + index * step for index in range(count + 1)]
    if not math.isclose(values[-1], high, rel_tol=0.0, abs_tol=1.0e-10):
        values.append(high)
    return [round(value, 12) for value in values]


def run_common_voltage_window_scan(
    config: Mapping[str, Any], runtime: Mapping[str, Any]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    active_config = read_json(resolve_path(config["source_active_erv_config"]))
    effective = effective_common_voltage_config(config, active_config)
    material = anchor_material(runtime)
    section = config["common_voltage_window_scan"]
    replay = config["common_voltage_replay"]
    rows: list[dict[str, Any]] = []
    for completion in section["remaining_duty_completion_pct"]:
        endpoints = post_erv_endpoints(runtime, float(completion))
        for voltage in voltage_scan_values(section):
            result, profile = solve_segmented_transport(
                v2=runtime["v2"],
                v2_config=runtime["v2_config"],
                study_config=effective,
                endpoints=endpoints,
                material=material,
                terminal_voltage_v=voltage,
                fixed_loss_voltage_v=float(replay["fixed_loss_voltage_v"]),
                series_asr_ohm_m2=float(replay["series_asr_ohm_m2"]),
                film_scale_factor=float(replay["film_scale_factor"]),
                segment_count=int(section["segment_count"]),
            )
            audited = thermodynamic_profile_audit(
                profile, config["audit_tolerances"]
            )
            thermo = bool(
                not audited.empty
                and bool_series(audited, "thermodynamic_consistency_pass").all()
            )
            feasible = bool(
                truth(result.get("transport_solution_complete"))
                and truth(result.get("transport_water_balance_pass"))
                and truth(result.get("terminal_voltage_solution_pass"))
                and thermo
            )
            rows.append(
                {
                    "remaining_duty_completion_pct": float(completion),
                    "terminal_voltage_v": voltage,
                    "segment_count": int(section["segment_count"]),
                    "transport_solution_complete": truth(
                        result.get("transport_solution_complete")
                    ),
                    "transport_failure_reason": str(
                        result.get("transport_failure_reason", "")
                    ),
                    "required_active_area_m2": float(
                        result.get("required_active_area_m2", math.nan)
                    ),
                    "minimum_local_current_density_a_m2": float(
                        result.get("minimum_local_current_density_a_m2", math.nan)
                    ),
                    "maximum_local_current_density_a_m2": float(
                        result.get("maximum_local_current_density_a_m2", math.nan)
                    ),
                    "thermodynamic_consistency_pass": thermo,
                    "within_area_observation_cap": truth(
                        result.get("area_cap_pass")
                    ),
                    "common_voltage_feasible": feasible,
                }
            )
    scan = pd.DataFrame(rows)
    summaries: list[dict[str, Any]] = []
    for completion, group in scan.groupby(
        "remaining_duty_completion_pct", sort=True
    ):
        feasible = group.loc[bool_series(group, "common_voltage_feasible")]
        summaries.append(
            {
                "remaining_duty_completion_pct": float(completion),
                "sampled_common_voltage_feasible_point_exists": not feasible.empty,
                "minimum_feasible_terminal_voltage_v": (
                    float(feasible["terminal_voltage_v"].min())
                    if not feasible.empty
                    else math.nan
                ),
                "maximum_feasible_terminal_voltage_v": (
                    float(feasible["terminal_voltage_v"].max())
                    if not feasible.empty
                    else math.nan
                ),
                "feasible_voltage_count": len(feasible),
                "tested_voltage_count": len(group),
                "sampled_terminal_voltage_step_v": float(
                    section["terminal_voltage_step_v"]
                ),
                "minimum_feasible_area_m2": (
                    float(feasible["required_active_area_m2"].min())
                    if not feasible.empty
                    else math.nan
                ),
                "topology_interpretation": (
                    "sampled_single_common_voltage_point_supported"
                    if not feasible.empty
                    else "no_feasible_sampled_common_voltage_point_at_frozen_anchor"
                ),
            }
        )
    return scan, pd.DataFrame(summaries)


def _current_state_for_profile(
    runtime: Mapping[str, Any],
    material: Mapping[str, Any],
    profile_row: Mapping[str, Any],
    current: float,
) -> dict[str, Any]:
    v2_config = copy.deepcopy(runtime["v2_config"])
    model = v2_config["model"]
    model["temperature_c"] = float(profile_row["membrane_temperature_c"])
    model["source_film_coefficient_mol_m2_s_activity"] = float(
        profile_row["source_film_coefficient_mol_m2_s_activity"]
    )
    model["receiver_film_coefficient_mol_m2_s_activity"] = float(
        profile_row["receiver_film_coefficient_mol_m2_s_activity"]
    )
    model["series_area_resistance_ohm_m2"] = float(
        profile_row["series_asr_ohm_m2"]
    )
    model["other_voltage_lower_bound_v"] = float(
        profile_row["fixed_loss_voltage_v"]
    )
    v2_config["activity_cases"] = {
        "closure_root": {
            "source_bulk_water_activity": float(
                profile_row["source_bulk_activity"]
            ),
            "receiver_bulk_water_activity": float(
                profile_row["receiver_bulk_activity"]
            ),
            "interpretation": "independent Brent replay",
        }
    }
    parameters = pd.DataFrame(
        {
            key: [float(material[key])]
            for key in (
                "water_drag",
                "water_diffusivity_m2_s",
                "conductivity_s_m",
                "dry_thickness_um",
                "water_capacity_mol_m3_activity",
                "diffusivity_activity_exponent",
                "conductivity_activity_exponent",
                "capacity_activity_exponent",
            )
        }
    )
    raw = runtime["v2"].solve_powerlaw_at_current(
        parameters, float(current), v2_config, "closure_root"
    )
    return {key: scalar(value) for key, value in raw.items()}


def independent_root_replay(
    config: Mapping[str, Any],
    runtime: Mapping[str, Any],
    profiles: pd.DataFrame,
) -> pd.DataFrame:
    if profiles.empty:
        return pd.DataFrame()
    selected_count = int(
        config["common_voltage_replay"]["selected_segment_count"]
    )
    selected_ids = {
        "screen_60pct_1v",
        "o30_1v",
    }
    material = anchor_material(runtime)
    rows: list[dict[str, Any]] = []
    subset = profiles.loc[
        profiles["case_id"].isin(selected_ids)
        & profiles["segment_count"].eq(selected_count)
    ]
    for case_id, group in subset.groupby("case_id", sort=False):
        group = group.sort_values("segment_index", ignore_index=True)
        indices = sorted({0, len(group) // 2, len(group) - 1})
        for index in indices:
            row = group.iloc[index].to_dict()
            reference_current = float(row["current_density_a_m2"])
            target_voltage = float(row["terminal_voltage_v"])

            def residual(current: float) -> float:
                state = _current_state_for_profile(
                    runtime, material, row, current
                )
                if not truth(state.get("solver_success")):
                    raise ValueError("invalid current state inside root bracket")
                return float(state["cell_voltage_signed_v"]) - target_voltage

            factors = [0.0, 0.1, 0.25, 0.5, 0.8, 0.95, 1.05, 1.2, 1.5, 2.0]
            sampled: list[tuple[float, float]] = []
            for factor in factors:
                current = reference_current * factor
                try:
                    sampled.append((current, residual(current)))
                except (ValueError, FloatingPointError):
                    continue
            bracket: tuple[float, float] | None = None
            for left, right in zip(sampled[:-1], sampled[1:]):
                if left[1] == 0.0:
                    bracket = (left[0], left[0])
                    break
                if left[1] * right[1] <= 0.0:
                    bracket = (left[0], right[0])
                    break
            if bracket is None:
                rows.append(
                    {
                        "case_id": case_id,
                        "segment_index": int(row["segment_index"]),
                        "status": "NO_ROOT_BRACKETED",
                        "reference_current_density_a_m2": reference_current,
                        "brent_current_density_a_m2": math.nan,
                        "current_relative_difference": math.nan,
                        "voltage_residual_v": math.nan,
                        "root_replay_pass": False,
                    }
                )
                continue
            try:
                if bracket[0] == bracket[1]:
                    root = bracket[0]
                else:
                    root = float(
                        brentq(
                            residual,
                            bracket[0],
                            bracket[1],
                            xtol=1.0e-12,
                            rtol=1.0e-12,
                            maxiter=100,
                        )
                    )
                voltage_residual = residual(root)
            except (ValueError, RuntimeError, FloatingPointError):
                rows.append(
                    {
                        "case_id": case_id,
                        "segment_index": int(row["segment_index"]),
                        "status": "ROOT_SOLVER_ERROR",
                        "reference_current_density_a_m2": reference_current,
                        "brent_current_density_a_m2": math.nan,
                        "current_relative_difference": math.nan,
                        "voltage_residual_v": math.nan,
                        "root_replay_pass": False,
                    }
                )
                continue
            relative = abs(root - reference_current) / max(
                abs(reference_current), 1.0e-12
            )
            passed = bool(
                relative
                <= float(
                    config["audit_tolerances"][
                        "independent_current_root_relative"
                    ]
                )
                and abs(voltage_residual)
                <= float(
                    config["audit_tolerances"][
                        "common_voltage_reconstruction_absolute_v"
                    ]
                )
            )
            rows.append(
                {
                    "case_id": case_id,
                    "segment_index": int(row["segment_index"]),
                    "status": "CONVERGED" if passed else "ROOT_MISMATCH",
                    "reference_current_density_a_m2": reference_current,
                    "brent_current_density_a_m2": root,
                    "current_relative_difference": relative,
                    "voltage_residual_v": voltage_residual,
                    "root_replay_pass": passed,
                }
            )
    return pd.DataFrame(rows)


def select_source_anchor(
    config: Mapping[str, Any], anchor: Mapping[str, Any]
) -> pd.Series:
    if anchor["source"] == "percentage":
        path = resolve_path(config["source_percentage_output"]) / (
            "selected_transport_cases.csv"
        )
    elif anchor["source"] == "frontier":
        path = resolve_path(config["source_frontier_output"]) / (
            "selected_primary_cases.csv"
        )
    else:
        raise ClosureCheckError(f"Unknown anchor source: {anchor['source']}")
    frame = pd.read_csv(path)
    selected = frame.loc[
        frame["target_id"].astype(str).eq(str(anchor["target_id"]))
        & frame["selection"].astype(str).eq(str(anchor["selection"]))
    ]
    if len(selected) != 1:
        raise ClosureCheckError(
            f"Expected one source row for {anchor['anchor_id']}, got {len(selected)}"
        )
    return selected.iloc[0]


def uniform_current_convergence(
    config: Mapping[str, Any],
    analyzer: ModuleType,
    runtime: Mapping[str, Any],
) -> pd.DataFrame:
    section = config["uniform_current_convergence"]
    rows: list[dict[str, Any]] = []
    for anchor in section["anchors"]:
        source = select_source_anchor(config, anchor)
        case = analyzer.base_case_material(runtime["anchor"])
        case.update(
            {
                "study_family": "project_closure_uniform_current_replay",
                "case_id": str(anchor["anchor_id"]),
                "water_diffusivity_m2_s": float(
                    source["water_diffusivity_m2_s"]
                ),
                "uniform_current_density_a_m2": float(
                    source["uniform_current_density_a_m2"]
                ),
                "receiver_to_process_dry_air_ratio": float(
                    source["receiver_to_process_dry_air_ratio"]
                ),
            }
        )
        target_w = float(source["target_w_g_kg_da"]) / 1000.0
        for step in section["area_steps_m2"]:
            local_runtime = dict(runtime)
            local_runtime["target_w"] = target_w
            local_runtime["area_step_m2"] = float(step)
            local_runtime["area_limit_m2"] = float(
                section["area_observation_cap_m2"]
            )
            result = analyzer.integrate_case(local_runtime, case)
            rows.append(
                {
                    "anchor_id": str(anchor["anchor_id"]),
                    "source_target_id": str(anchor["target_id"]),
                    "source_selection": str(anchor["selection"]),
                    "area_step_m2": float(step),
                    "status": str(result.get("status", "")),
                    "target_reached": truth(result.get("target_reached")),
                    "required_active_area_m2": float(
                        result.get("required_active_area_m2", math.nan)
                    ),
                    "maximum_required_terminal_voltage_signed_v": float(
                        result.get(
                            "maximum_required_terminal_voltage_signed_v", math.nan
                        )
                    ),
                    "minimum_surface_activity_margin": float(
                        result.get("minimum_surface_activity_margin", math.nan)
                    ),
                    "water_balance_relative_error": float(
                        result.get("water_balance_relative_error", math.nan)
                    ),
                    "conditional_saving_kw_vs_passive_erv": float(
                        result.get(
                            "incremental_saving_kw_vs_passive_erv", math.nan
                        )
                    ),
                }
            )
    frame = pd.DataFrame(rows)
    selected_step = float(section["selected_area_step_m2"])
    tolerance = float(
        config["audit_tolerances"]["uniform_current_area_relative_change"]
    )
    frame["area_relative_difference_from_selected"] = math.nan
    frame["area_convergence_pass"] = False
    for _, group in frame.groupby("anchor_id", sort=False):
        selected = group.loc[np.isclose(group["area_step_m2"], selected_step)]
        if len(selected) != 1:
            raise ClosureCheckError("Uniform-current selected step missing")
        reference = float(selected.iloc[0]["required_active_area_m2"])
        for index in group.index:
            area = float(frame.at[index, "required_active_area_m2"])
            relative = abs(area - reference) / max(abs(reference), 1.0e-12)
            frame.at[index, "area_relative_difference_from_selected"] = relative
            frame.at[index, "area_convergence_pass"] = bool(
                truth(frame.at[index, "target_reached"]) and relative <= tolerance
            )
    return frame


def audit_existing_active_erv(
    config: Mapping[str, Any]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    root = ROOT / "outputs" / "direct_active_eo_erv_study_v1"
    all_segments: list[pd.DataFrame] = []
    summaries: list[dict[str, Any]] = []
    for population in ("study", "sensitivity", "nafion_sensitivity"):
        segment_path = root / population / "segment_register.csv.gz"
        case_path = root / population / "case_register.csv"
        segments = pd.read_csv(segment_path)
        valid = segments.loc[bool_series(segments, "solution_ok")].copy()
        audited_rows: list[dict[str, Any]] = []
        for row in valid.to_dict("records"):
            audited_rows.append(
                {
                    **row,
                    **audit_local_record(
                        row,
                        temperature_c=float(row["membrane_temperature_c"]),
                        coupling_identity_required=(
                            "nafion" not in str(row["material_id"]).lower()
                        ),
                        identity_relative_tolerance=float(
                            config["audit_tolerances"][
                                "thermodynamic_identity_relative"
                            ]
                        ),
                        nonnegative_power_tolerance_w_m2=float(
                            config["audit_tolerances"][
                                "nonnegative_power_w_m2"
                            ]
                        ),
                    ),
                    "population": population,
                }
            )
        audited = pd.DataFrame(audited_rows)
        all_segments.append(audited)
        case_thermo = (
            audited.groupby("case_id")["thermodynamic_consistency_pass"]
            .all()
            .rename("thermodynamic_consistency_pass")
        )
        cases = pd.read_csv(case_path).drop(
            columns=["thermodynamic_consistency_pass"], errors="ignore"
        ).merge(
            case_thermo, how="left", left_on="case_id", right_index=True
        )
        alternative = bool_series(cases, "target_transport_closed")
        for column in (
            "thermal_fixed_point_converged",
            "exhaust_rh_gate_pass",
            "conditional_energy_pass",
            "hydraulic_pressure_gate_pass",
            "stack_feasible",
            "segment_convergence_gate_pass",
            "thermodynamic_consistency_pass",
        ):
            alternative &= bool_series(cases, column)
        original = bool_series(cases, "engineering_screen_pass")
        summaries.append(
            {
                "population": population,
                "valid_segment_count": len(audited),
                "thermodynamic_pass_segment_count": int(
                    bool_series(audited, "thermodynamic_consistency_pass").sum()
                ),
                "full_constant_drag_identity_segment_count": int(
                    bool_series(audited, "coupling_identity_applicable").sum()
                ),
                "variable_drag_boundary_energy_segment_count": int(
                    (~bool_series(audited, "coupling_identity_applicable")).sum()
                ),
                "negative_dissipation_segment_count": int(
                    (
                        pd.to_numeric(
                            audited["membrane_dissipation_density_w_m2"],
                            errors="coerce",
                        )
                        < -float(
                            config["audit_tolerances"][
                                "nonnegative_power_w_m2"
                            ]
                        )
                    ).sum()
                ),
                "minimum_membrane_dissipation_density_w_m2": float(
                    pd.to_numeric(
                        audited["membrane_dissipation_density_w_m2"],
                        errors="coerce",
                    ).min()
                ),
                "original_engineering_screen_pass_count": int(original.sum()),
                "engineering_pass_without_passive_surface_gate_count": int(
                    alternative.sum()
                ),
                "newly_reclassified_conditional_case_count": int(
                    (alternative & ~original).sum()
                ),
                "source_engineering_false_positive_count": int(
                    (original & ~alternative).sum()
                ),
                "reclassification_interpretation": (
                    "conditional_hypothetical_only_not_full_system_validation"
                ),
            }
        )
    return pd.concat(all_segments, ignore_index=True), pd.DataFrame(summaries)


def version_tuple(text: str) -> tuple[int, ...]:
    values = [int(value) for value in re.findall(r"\d+", str(text))[:3]]
    return tuple(values + [0] * (3 - len(values)))


def git_snapshot() -> dict[str, Any]:
    def command(*args: str) -> str:
        completed = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip()

    try:
        revision = command("rev-parse", "HEAD")
        status = command("status", "--porcelain")
        return {
            "git_available": True,
            "revision": revision,
            "worktree_clean": status == "",
            "porcelain_line_count": len(status.splitlines()) if status else 0,
        }
    except (OSError, subprocess.CalledProcessError) as exc:
        return {
            "git_available": False,
            "revision": None,
            "worktree_clean": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


def add_gate(
    rows: list[dict[str, Any]],
    gate_id: str,
    status: str,
    *,
    blocks: str,
    evidence: str,
    interpretation: str,
) -> None:
    rows.append(
        {
            "gate_id": gate_id,
            "status": status,
            "blocks": blocks,
            "evidence": evidence,
            "interpretation": interpretation,
        }
    )


def material_requirement_schema_valid(frame: pd.DataFrame) -> bool:
    required_ids = {f"MAT-{index:02d}" for index in range(1, 10)}
    return bool(
        "requirement_id" in frame
        and len(frame) == len(required_ids)
        and frame["requirement_id"].astype(str).is_unique
        and set(frame["requirement_id"].astype(str)) == required_ids
    )


def material_candidate_data_complete(
    frame: pd.DataFrame, *, same_sample_required: bool
) -> bool:
    if not material_requirement_schema_valid(frame):
        return False
    required_columns = {"candidate_value_or_source", "data_status"}
    if not required_columns.issubset(frame.columns):
        return False
    sources = frame["candidate_value_or_source"].astype(str).str.strip()
    status = frame["data_status"].astype(str).str.strip().str.lower()
    complete = bool(
        sources.ne("").all()
        and ~sources.str.lower().isin({"nan", "none"}).any()
        and status.isin({"complete", "verified"}).all()
    )
    if not same_sample_required:
        return complete
    if "candidate_sample_id" not in frame:
        return False
    sample_ids = frame["candidate_sample_id"].astype(str).str.strip()
    return bool(
        complete
        and sample_ids.ne("").all()
        and ~sample_ids.str.lower().isin({"nan", "none"}).any()
        and sample_ids.nunique() == 1
    )


def receiver_contract_valid(receiver: Mapping[str, Any]) -> bool:
    try:
        temperature = float(receiver["inlet_temperature_c"])
        relative_humidity = float(receiver["inlet_relative_humidity"])
        flow_ratio = float(receiver["flow_ratio"])
        sec = float(receiver["measured_sec_kwh_per_kg"])
    except (KeyError, TypeError, ValueError):
        return False
    return bool(
        str(receiver.get("architecture_id", "")).strip()
        and str(receiver.get("regeneration_or_disposal_route", "")).strip()
        and math.isfinite(temperature)
        and -80.0 <= temperature <= 100.0
        and math.isfinite(relative_humidity)
        and 0.0 <= relative_humidity <= 1.0
        and math.isfinite(flow_ratio)
        and flow_ratio > 0.0
        and math.isfinite(sec)
        and sec >= 0.0
    )


def practical_limits_valid(practical: Mapping[str, Any]) -> bool:
    try:
        values = [
            float(practical[key])
            for key in (
                "maximum_active_area_m2",
                "maximum_channel_pressure_drop_pa_each_side",
                "maximum_module_footprint_m3",
                "maximum_installed_cost",
            )
        ]
    except (KeyError, TypeError, ValueError):
        return False
    return bool(
        all(math.isfinite(value) and value > 0.0 for value in values)
        and str(practical.get("currency", "")).strip()
    )


def uniform_current_replay_converged(
    uniform: pd.DataFrame, config: Mapping[str, Any]
) -> bool:
    if uniform.empty:
        return False
    uniform_steps = sorted(
        float(value)
        for value in config["uniform_current_convergence"]["area_steps_m2"]
    )
    selected_step = float(
        config["uniform_current_convergence"]["selected_area_step_m2"]
    )
    coarser_steps = [value for value in uniform_steps if value > selected_step]
    if not coarser_steps:
        return False
    comparison = uniform.loc[
        np.isclose(uniform["area_step_m2"], min(coarser_steps))
    ]
    return bool(
        len(comparison)
        == len(config["uniform_current_convergence"]["anchors"])
        and bool_series(comparison, "area_convergence_pass").all()
    )


def build_decision_gates(
    config: Mapping[str, Any],
    runtime: Mapping[str, Any],
    common: pd.DataFrame,
    convergence: pd.DataFrame,
    window: pd.DataFrame,
    roots: pd.DataFrame,
    uniform: pd.DataFrame,
    active_summary: pd.DataFrame,
    material_requirements: pd.DataFrame,
    percentage_summary: pd.DataFrame,
    git: Mapping[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    selected_count = int(
        config["common_voltage_replay"]["selected_segment_count"]
    )
    selected = common.loc[common["segment_count"].eq(selected_count)]
    primary = selected.loc[selected["case_role"].eq("primary_screen")]
    primary_resolved = bool(
        len(primary) == 3
        and ~primary["resolution_status"].eq(
            "NUMERICAL_OR_LOCAL_SOLUTION_FAILURE"
        ).any()
    )
    primary_survives = bool(
        len(primary) == 3
        and bool_series(primary, "common_voltage_replay_pass").all()
    )
    active_thermo = bool(
        not active_summary.empty
        and (
            active_summary["valid_segment_count"]
            == active_summary["thermodynamic_pass_segment_count"]
        ).all()
    )
    reclassified = int(
        active_summary["newly_reclassified_conditional_case_count"].sum()
    )
    source_false_positives = int(
        active_summary["source_engineering_false_positive_count"].sum()
    )
    surface_gate_correction_pass = bool(
        active_thermo and source_false_positives == 0
    )
    if reclassified > 0:
        surface_gate_evidence = (
            f"{reclassified} legacy false-negative active-ERV cases are "
            "reclassified by the thermodynamic/non-surface engineering screen"
        )
    else:
        surface_gate_evidence = (
            "0 cases require reclassification because the stored source "
            "outputs already use the corrected thermodynamic/non-surface screen"
        )
    relevant_convergence = convergence.loc[
        bool_series(convergence, "model_closure_relevant")
    ]
    segment_converged = bool(
        not relevant_convergence.empty
        and bool_series(relevant_convergence, "convergence_pass").all()
    )
    expected_root_cases = {"screen_60pct_1v", "o30_1v"}
    root_pass = bool(
        len(roots) == 3 * len(expected_root_cases)
        and set(roots["case_id"].astype(str)) == expected_root_cases
        and bool_series(roots, "root_replay_pass").all()
    )
    # An explicitly skipped or missing replay is unresolved, not a pass.  This
    # keeps the machine-readable closure conclusion fail-closed.
    uniform_pass = uniform_current_replay_converged(uniform, config)
    full_window = window.loc[
        np.isclose(window["remaining_duty_completion_pct"], 100.0)
    ]
    full_single_bus_exists = bool(
        not full_window.empty
        and truth(
            full_window.iloc[0][
                "sampled_common_voltage_feasible_point_exists"
            ]
        )
    )
    material_schema_pass = material_requirement_schema_valid(
        material_requirements
    )
    candidate_data_complete = material_candidate_data_complete(
        material_requirements,
        same_sample_required=bool(
            config["material_screening_boundary"][
                "same_sample_correlated_properties_required"
            ]
        ),
    )
    numpy_environment_pass = version_tuple(np.__version__) >= version_tuple(
        config["environment_contract"]["minimum_numpy_version"]
    )
    python_environment_pass = version_tuple(
        platform.python_version()
    ) >= version_tuple(config["environment_contract"]["minimum_python_version"])
    runtime_environment_pass = bool(
        numpy_environment_pass and python_environment_pass
    )
    reference_pass = math.isclose(
        float(runtime["baseline"].total_power_kw),
        float(
            config["frozen_claim_contract"][
                "modern_passive_erv_plus_ac_reference_kw"
            ]
        ),
        rel_tol=2.0e-6,
        abs_tol=5.0e-4,
    )
    full_energy = percentage_summary.loc[
        np.isclose(
            pd.to_numeric(
                percentage_summary["remaining_duty_completion_pct"],
                errors="coerce",
            ),
            100.0,
        )
    ]
    energy_contract_pass = False
    full_break_even = math.nan
    full_sink_budget = math.nan
    if len(full_energy) == 1:
        full_break_even = float(
            full_energy.iloc[0][
                "control_conservative_break_even_sec_kwh_per_kg"
            ]
        )
        full_sink_budget = float(
            full_energy.iloc[0][
                "best_control_conservative_receiver_sink_sec_budget_kwh_per_kg"
            ]
        )
        energy_contract_pass = bool(
            reference_pass
            and math.isclose(
                full_break_even,
                float(
                    config["frozen_claim_contract"][
                        "conservative_all_in_break_even_kwh_per_kg"
                    ]
                ),
                rel_tol=2.0e-9,
                abs_tol=2.0e-10,
            )
            and math.isclose(
                full_sink_budget,
                float(
                    config["frozen_claim_contract"][
                        "full_duty_receiver_sink_budget_kwh_per_kg"
                    ]
                ),
                rel_tol=2.0e-9,
                abs_tol=2.0e-10,
            )
        )
    no_current_density_gate = bool(
        config["frozen_claim_contract"].get(
            "engineering_current_density_limit_a_m2"
        )
        is None
        and not common.empty
        and not bool_series(common, "current_density_gate_applied").any()
        and pd.to_numeric(
            common["engineering_current_density_limit_a_m2"], errors="coerce"
        ).isna().all()
    )
    receiver = config["receiver_contract"]
    receiver_frozen = receiver_contract_valid(receiver)
    practical = config["practical_limits"]
    practical_frozen = practical_limits_valid(practical)
    rows: list[dict[str, Any]] = []
    add_gate(
        rows,
        "G01_THERMODYNAMIC_SIGN",
        "PASS" if active_thermo else "FAIL",
        blocks="model_closure",
        evidence=(
            f"{int(active_summary['thermodynamic_pass_segment_count'].sum())}/"
            f"{int(active_summary['valid_segment_count'].sum())} stored valid segments pass; "
            f"{int(active_summary['full_constant_drag_identity_segment_count'].sum())} "
            "full constant-drag identities + "
            f"{int(active_summary['variable_drag_boundary_energy_segment_count'].sum())} "
            "variable-drag boundary-energy audits"
        ),
        interpretation="Surface activity sign is a regime indicator; the applicable dissipation or boundary-energy balance is the hard physics check.",
    )
    add_gate(
        rows,
        "G02_SURFACE_GATE_RECLASSIFICATION",
        "PASS" if surface_gate_correction_pass else "FAIL",
        blocks="claim_correction",
        evidence=surface_gate_evidence,
        interpretation=(
            "A zero count is expected after corrected outputs are regenerated. "
            "Any reclassified cases remain hypothetical and conditional, not "
            "full-system validations."
        ),
    )
    add_gate(
        rows,
        "G03_COMMON_VOLTAGE_PRIMARY",
        "PASS" if primary_resolved and primary_survives else "FAIL",
        blocks="material_search_path",
        evidence=f"{int(bool_series(primary, 'common_voltage_replay_pass').sum())}/{len(primary)} primary 1-V cases pass",
        interpretation="Tests one common bus with local current sharing at 50, 60 and 67.5 percent completion.",
    )
    add_gate(
        rows,
        "G03B_NO_CURRENT_DENSITY_GATE",
        "PASS" if no_current_density_gate else "FAIL",
        blocks="model_closure",
        evidence="In this closure run, current density is solved/sampled and no A/m2 acceptance ceiling is configured or applied",
        interpretation="Voltage, transport, energy and practical consequences remain explicit; historical 21-A/m2 sensitivity replays are not current acceptance gates.",
    )
    add_gate(
        rows,
        "G04_FULL_DUTY_SINGLE_BUS",
        "PASS" if full_single_bus_exists else "OPEN",
        blocks="full_duty_single_bus_claim_only",
        evidence=(
            "At least one feasible sampled common-voltage point exists"
            if full_single_bus_exists
            else "No feasible point was found on the 0.05-V grid from 0.5 to 2.0 V at the frozen anchor"
        ),
        interpretation="This 32-segment discrete diagnostic is not a converged proof that every continuous sub-interval is empty and does not imply a general membrane no-go.",
    )
    add_gate(
        rows,
        "G05_SEGMENT_CONVERGENCE",
        "PASS" if segment_converged else "FAIL",
        blocks="model_closure",
        evidence=(
            f"{int(bool_series(relevant_convergence, 'convergence_pass').sum())}/"
            f"{len(relevant_convergence)} closure-relevant replay outcomes stable from "
            f"{int(relevant_convergence['coarse_segment_count'].iloc[0])} to "
            f"{int(relevant_convergence['refined_segment_count'].iloc[0])} segments"
        ),
        interpretation="No new broad sweep is required if this gate passes.",
    )
    add_gate(
        rows,
        "G06_INDEPENDENT_CURRENT_ROOTS",
        "PASS" if root_pass else "FAIL",
        blocks="model_closure",
        evidence=f"{int(bool_series(roots, 'root_replay_pass').sum())}/{len(roots)} local roots reproduced with Brent",
        interpretation="Independent algorithmic check of the built-in voltage bisection.",
    )
    add_gate(
        rows,
        "G07_UNIFORM_CURRENT_STEP_REPLAY",
        "PASS" if uniform_pass else ("OPEN" if uniform.empty else "FAIL"),
        blocks="model_closure",
        evidence=(
            "Skipped by explicit CLI option"
            if uniform.empty
            else f"{uniform['anchor_id'].nunique()} selected anchors replayed at 20/10/5 m2"
        ),
        interpretation="Targeted numerical hygiene only; it does not promote uniform current to a physical topology.",
    )
    add_gate(
        rows,
        "G08_FROZEN_ENERGY_CONTRACT",
        "PASS" if energy_contract_pass else "FAIL",
        blocks="model_closure",
        evidence=(
            f"baseline={float(runtime['baseline'].total_power_kw):.6f} kW; "
            f"break-even={full_break_even:.12f} kWh/kg; "
            f"full-duty sink budget={full_sink_budget:.12f} kWh/kg"
        ),
        interpretation="Validates all three frozen energy coordinates against the source percentage study.",
    )
    add_gate(
        rows,
        "G09_MATERIAL_DATA_SCHEMA",
        "PASS" if material_schema_pass else "FAIL",
        blocks="supplier_data_collection",
        evidence=f"{len(material_requirements)} requirement rows found",
        interpretation="Candidate values are expected to be empty before material scouting.",
    )
    complete_material_rows = int(
        material_requirements.get(
            "data_status", pd.Series(index=material_requirements.index, dtype=str)
        )
        .astype(str)
        .str.strip()
        .str.lower()
        .isin({"complete", "verified"})
        .sum()
    )
    add_gate(
        rows,
        "G09B_CANDIDATE_DATA_COMPLETENESS",
        "PASS" if candidate_data_complete else "OPEN",
        blocks="candidate_ranking",
        evidence=(
            f"{complete_material_rows}/{len(material_requirements)} requirement rows complete; "
            "one same-sample candidate ID is required"
        ),
        interpretation="A requirements checklist enables data collection but is not candidate evidence.",
    )
    add_gate(
        rows,
        "G10_RECEIVER_CONTRACT",
        "PASS" if receiver_frozen else "OPEN",
        blocks="candidate_ranking_and_system_claim",
        evidence=str(receiver.get("status")),
        interpretation="Receiver architecture, boundary and measured SEC belong to the next subsystem phase.",
    )
    add_gate(
        rows,
        "G11_PRACTICAL_LIMITS",
        "PASS" if practical_frozen else "OPEN",
        blocks="candidate_ranking",
        evidence=str(practical.get("status")),
        interpretation="Team must set area, pressure-drop, footprint and cost ceilings.",
    )
    add_gate(
        rows,
        "G12_RUNTIME_ENVIRONMENT",
        "PASS" if runtime_environment_pass else "OPEN",
        blocks="release_freeze",
        evidence=f"Python {platform.python_version()}, NumPy {np.__version__}",
        interpretation=(
            "Checks the closure contract's declared Python and NumPy minima; "
            "the final-delivery checker validates the complete project runtime."
        ),
    )
    add_gate(
        rows,
        "G13_RELEASE_SNAPSHOT",
        "PASS" if truth(git.get("worktree_clean")) else "OPEN",
        blocks="release_freeze",
        evidence=f"revision={git.get('revision')}; clean={git.get('worktree_clean')}",
        interpretation="A hash manifest is written, but the working tree must be frozen separately.",
    )

    broad_modelling_can_stop = bool(
        active_thermo
        and primary_resolved
        and primary_survives
        and no_current_density_gate
        and segment_converged
        and root_pass
        and uniform_pass
        and energy_contract_pass
    )
    material_data_collection_ready = bool(
        broad_modelling_can_stop and material_schema_pass
    )
    candidate_ranking_ready = bool(
        material_data_collection_ready
        and candidate_data_complete
        and receiver_frozen
        and practical_frozen
    )
    status = {
        "script_version": SCRIPT_VERSION,
        "study_id": config["study_id"],
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "broad_modelling_can_stop": broad_modelling_can_stop,
        "material_data_collection_ready": material_data_collection_ready,
        "material_candidate_ranking_ready": candidate_ranking_ready,
        "technology_validated": False,
        "full_system_claim_allowed": False,
        "full_duty_sampled_common_voltage_point_feasible": full_single_bus_exists,
        "full_duty_single_bus_claim_status": (
            "SUPPORTED_AT_SAMPLED_POINT"
            if full_single_bus_exists
            else "OPEN_UNCONVERGED_SAMPLED_DIAGNOSTIC"
        ),
        "newly_reclassified_conditional_active_erv_cases": reclassified,
        "recommended_phase_label": (
            "MODEL STUDY COMPLETE - MATERIAL AND SUBSYSTEM FEASIBILITY STARTS"
            if broad_modelling_can_stop
            else "TARGETED CLOSURE ACTIONS STILL REQUIRED"
        ),
    }
    return pd.DataFrame(rows), status


def consumed_input_paths(
    config_path: Path,
    analyzer_path: Path,
    config: Mapping[str, Any],
    runtime: Mapping[str, Any],
) -> list[Path]:
    active_root = ROOT / "outputs" / "direct_active_eo_erv_study_v1"
    percentage_root = resolve_path(config["source_percentage_output"])
    frontier_root = resolve_path(config["source_frontier_output"])
    paths = [
        config_path,
        analyzer_path,
        ROOT / "scripts" / "run_project_closure_check_v1.py",
        ROOT / "scripts" / "make_post_erv_eo_design_frontier_v1.py",
        ROOT / "src" / "heiq" / "wp1" / "membrane" / "thermodynamics.py",
        ROOT / "src" / "heiq" / "wp1" / "studies" / "active_erv.py",
        resolve_path(config["source_operating_region_config"]),
        resolve_path(config["source_active_erv_config"]),
        resolve_path(config["material_requirements"]),
        percentage_root / "percentage_summary.csv",
        percentage_root / "percentage_break_even.csv",
        percentage_root / "selected_transport_cases.csv",
        frontier_root / "selected_primary_cases.csv",
    ]
    for population in ("study", "sensitivity", "nafion_sensitivity"):
        paths.extend(
            [
                active_root / population / "case_register.csv",
                active_root / population / "segment_register.csv.gz",
            ]
        )
    runtime_paths = runtime.get("paths")
    if runtime_paths is not None:
        paths.extend(
            value
            for value in vars(runtime_paths).values()
            if isinstance(value, Path) and value.is_file()
        )
    unique = {Path(path).expanduser().resolve() for path in paths}
    return sorted(unique, key=str)


def snapshot_inputs(paths: Iterable[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in paths:
        if not path.is_file():
            raise ClosureCheckError(f"Required closure input is missing: {path}")
        records.append(
            {
                "path": str(path),
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
        )
    return records


def assert_inputs_unchanged(records: Iterable[Mapping[str, Any]]) -> None:
    changed: list[str] = []
    for record in records:
        path = Path(str(record["path"]))
        if (
            not path.is_file()
            or path.stat().st_size != int(record["size_bytes"])
            or sha256_file(path) != str(record["sha256"])
        ):
            changed.append(str(path))
    if changed:
        raise ClosureCheckError(
            "Closure inputs changed during the run:\n  " + "\n  ".join(changed)
        )


def source_manifest(
    input_records: Iterable[Mapping[str, Any]],
    runtime_source_hashes: Mapping[str, Any],
    output: Path,
    git: Mapping[str, Any],
) -> dict[str, Any]:
    output_records = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name != "source_manifest.json":
            output_records.append(
                {
                    "path": str(path),
                    "sha256": sha256_file(path),
                    "size_bytes": path.stat().st_size,
                }
            )
    return {
        "script_version": SCRIPT_VERSION,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "git": dict(git),
        "inputs": [dict(record) for record in input_records],
        "runtime_source_sha256": dict(runtime_source_hashes),
        "outputs": output_records,
    }


def make_plot(
    common: pd.DataFrame,
    window: pd.DataFrame,
    output: Path,
    selected_count: int,
) -> None:
    figures = output / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    selected = common.loc[common["segment_count"].eq(selected_count)].copy()
    fig, axes = plt.subplots(1, 2, figsize=(11.0, 4.6))
    successful = selected.loc[bool_series(selected, "common_voltage_replay_pass")]
    failed = selected.loc[~bool_series(selected, "common_voltage_replay_pass")]
    axes[0].scatter(
        successful["remaining_duty_completion_pct"],
        successful["required_active_area_m2"],
        c=successful["common_terminal_voltage_v"],
        cmap="viridis",
        s=55,
        label="common-V pass",
    )
    if not failed.empty:
        axes[0].scatter(
            failed["remaining_duty_completion_pct"],
            np.zeros(len(failed)),
            marker="x",
            color="#b22222",
            s=70,
            label="no common-V solution / gate fail",
        )
    axes[0].set_xlabel("Remaining post-ERV duty completed (%)")
    axes[0].set_ylabel("Required active area (m²)")
    axes[0].set_title("Frozen-anchor common-voltage replay")
    axes[0].grid(alpha=0.25)
    axes[0].legend(fontsize=8)

    for completion, group in window.groupby(
        "remaining_duty_completion_pct", sort=True
    ):
        axes[1].plot(
            group["terminal_voltage_v"],
            group["common_voltage_feasible"].astype(int),
            marker="o",
            markersize=2.5,
            linewidth=1.0,
            label=f"{completion:g}%",
        )
    axes[1].set_xlabel("Common terminal voltage (V)")
    axes[1].set_ylabel("All segments feasible at sampled V")
    axes[1].set_yticks([0, 1], ["No", "Yes"])
    axes[1].set_title("Sampled single-bus voltage feasibility")
    axes[1].grid(alpha=0.25)
    axes[1].legend(fontsize=7, ncol=2)
    fig.tight_layout()
    for suffix in ("png", "pdf"):
        fig.savefig(
            figures / f"closure_common_voltage.{suffix}",
            dpi=220,
            bbox_inches="tight",
        )
    plt.close(fig)


def write_summary(
    path: Path,
    status: Mapping[str, Any],
    gates: pd.DataFrame,
    common: pd.DataFrame,
    window: pd.DataFrame,
    active: pd.DataFrame,
    selected_count: int,
) -> None:
    selected = common.loc[common["segment_count"].eq(selected_count)]
    lines = [
        "# Project closure check v1",
        "",
        f"**Phase result:** {status['recommended_phase_label']}",
        "",
        "This is a bounded modelling audit, not a material or technology validation.",
        "",
        "## Key findings",
        "",
        f"- Stored active-ERV segments passing the thermodynamic audit: "
        f"{int(active['thermodynamic_pass_segment_count'].sum())}/"
        f"{int(active['valid_segment_count'].sum())}.",
        f"- Conditional active-ERV cases reclassified when passive surface direction "
        f"is replaced by the dissipation gate: "
        f"{int(active['newly_reclassified_conditional_case_count'].sum())}.",
        "- A negative source-minus-receiver surface-activity margin is classified as "
        "uphill active transport when the applicable audit closes: full coupling and "
        "dissipation identities for the constant-drag power-law model, or the boundary "
        "energy balance for the variable-drag Nafion summary.",
        f"- Broad modelling can stop: {status['broad_modelling_can_stop']}.",
        f"- Material data collection ready: {status['material_data_collection_ready']}.",
        f"- Candidate ranking ready: {status['material_candidate_ranking_ready']}.",
        "",
        "## Common-voltage selected replays",
        "",
        "| Case | Completion | Voltage | Result | Area (m2) | Current range (A/m2) | Conditional receiver/sink room (kWh/kg) |",
        "|---|---:|---:|---|---:|---:|---:|",
    ]
    for row in selected.itertuples(index=False):
        area = getattr(row, "required_active_area_m2")
        current_range = (
            f"{getattr(row, 'minimum_local_current_density_a_m2'):.3f}--"
            f"{getattr(row, 'maximum_local_current_density_a_m2'):.3f}"
            if math.isfinite(float(getattr(row, "minimum_local_current_density_a_m2")))
            else "n/a"
        )
        budget = getattr(row, "conditional_receiver_sink_sec_budget_kwh_per_kg")
        lines.append(
            f"| {row.case_id} | {row.remaining_duty_completion_pct:.3f}% | "
            f"{row.common_terminal_voltage_v:.3f} | {row.resolution_status} | "
            f"{area:.2f} | {current_range} | {budget:.5f} |"
        )
    lines.extend(
        [
            "",
            "## Sampled common-voltage scan",
            "",
            "| Completion | Feasible sampled point | Feasible sampled span (V) | Minimum area (m2) |",
            "|---:|---|---:|---:|",
        ]
    )
    for row in window.itertuples(index=False):
        interval = (
            f"{row.minimum_feasible_terminal_voltage_v:.2f}--"
            f"{row.maximum_feasible_terminal_voltage_v:.2f}"
            if truth(row.sampled_common_voltage_feasible_point_exists)
            else "none"
        )
        area = (
            f"{row.minimum_feasible_area_m2:.2f}"
            if math.isfinite(float(row.minimum_feasible_area_m2))
            else "n/a"
        )
        lines.append(
            f"| {row.remaining_duty_completion_pct:.3f}% | "
            f"{row.sampled_common_voltage_feasible_point_exists} | {interval} | {area} |"
        )
    lines.extend(
        [
            "",
            "## Decision gates",
            "",
            "| Gate | Status | Blocks | Evidence |",
            "|---|---|---|---|",
        ]
    )
    for row in gates.itertuples(index=False):
        lines.append(
            f"| {row.gate_id} | {row.status} | {row.blocks} | {row.evidence} |"
        )
    lines.extend(
        [
            "",
            "The correct milestone is **model study complete -- material and subsystem "
            "feasibility starts**, not technology validated.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    config_path = args.config.expanduser().resolve()
    config_hash_before_read = sha256_file(config_path)
    config = read_json(config_path)
    if sha256_file(config_path) != config_hash_before_read:
        raise ClosureCheckError("Closure config changed while it was being read")
    output = args.output_dir.expanduser().resolve()
    prepare_output(output, args.overwrite)

    analyzer, runtime, source_config, analyzer_path = load_runtime(
        config, args.v2_root.expanduser().resolve()
    )
    input_records = snapshot_inputs(
        consumed_input_paths(
            config_path, analyzer_path, config, runtime
        )
    )
    percentage_summary = pd.read_csv(
        resolve_path(config["source_percentage_output"]) / "percentage_summary.csv"
    )
    material_requirements = pd.read_csv(
        resolve_path(config["material_requirements"])
    )

    active_segments, active_summary = audit_existing_active_erv(config)
    common, profiles = run_common_voltage_replays(
        config, runtime, source_config, percentage_summary
    )
    convergence = build_segment_convergence(common, config)
    voltage_scan, voltage_windows = run_common_voltage_window_scan(config, runtime)
    roots = independent_root_replay(config, runtime, profiles)
    uniform = (
        pd.DataFrame()
        if args.skip_uniform_current_replay
        else uniform_current_convergence(config, analyzer, runtime)
    )
    git = git_snapshot()
    gates, status = build_decision_gates(
        config,
        runtime,
        common,
        convergence,
        voltage_windows,
        roots,
        uniform,
        active_summary,
        material_requirements,
        percentage_summary,
        git,
    )

    assert_inputs_unchanged(input_records)

    active_segments.to_csv(
        output / "active_erv_thermodynamic_audit.csv.gz",
        index=False,
        compression="gzip",
    )
    active_summary.to_csv(output / "active_erv_reclassification.csv", index=False)
    common.to_csv(output / "common_voltage_cases.csv", index=False)
    profiles.to_csv(
        output / "common_voltage_profiles.csv.gz", index=False, compression="gzip"
    )
    convergence.to_csv(output / "common_voltage_convergence.csv", index=False)
    voltage_scan.to_csv(output / "common_voltage_window_scan.csv", index=False)
    voltage_windows.to_csv(
        output / "common_voltage_window_summary.csv", index=False
    )
    roots.to_csv(output / "independent_voltage_root_replay.csv", index=False)
    uniform.to_csv(output / "uniform_current_convergence.csv", index=False)
    gates.to_csv(output / "decision_gate_register.csv", index=False)
    write_json(output / "closure_status.json", status)
    make_plot(
        common,
        voltage_scan,
        output,
        int(config["common_voltage_replay"]["selected_segment_count"]),
    )
    write_summary(
        output / "SUMMARY.md",
        status,
        gates,
        common,
        voltage_windows,
        active_summary,
        int(config["common_voltage_replay"]["selected_segment_count"]),
    )
    assert_inputs_unchanged(input_records)
    write_json(
        output / "source_manifest.json",
        source_manifest(
            input_records,
            runtime.get("source_hashes", {}),
            output,
            git,
        ),
    )

    print(json.dumps(json_safe(status), indent=2, sort_keys=True))
    print(f"Wrote closure audit to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
