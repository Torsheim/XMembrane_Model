#!/usr/bin/env python3
"""Dense inverse-design study for the 10 % post-passive-ERV EO polisher.

The study deliberately separates four questions:

1. Does the numerical current-controlled membrane calculation reach the duty?
2. Is the required area observed, or only right-censored at 24 000 m2?
3. Is the *screening-boundary* incremental energy balance positive?
4. Is the full system closed?  It is not; that status is always ``UNKNOWN``.

The current-density coordinate is an operating/sampling axis.  No 21 A/m2
acceptance limit, or any other hidden current-density limit, is imposed.

The local membrane calculation is delegated to the hash-checked repository
``heiq_pre_receiver_model.py::solve_powerlaw_at_current``.  This file contains
the counter-current finite-film area integration and all study orchestration so
that the generated result set does not depend on an unpacked Downloads bundle.
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
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable, Mapping, Sequence

os.environ.setdefault("MPLCONFIGDIR", "/tmp/heiq-post-erv-inverse-design-mpl")

import matplotlib

matplotlib.use("Agg")
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


SCRIPT_VERSION = "post-erv-inverse-design-v1.2-2026-08-26"
KNOWN_SOLVER_SCRIPT_VERSIONS = {
    "post-erv-inverse-design-v1.0-2026-08-26",
    "post-erv-inverse-design-v1.1-2026-08-26",
    SCRIPT_VERSION,
}
WATER_MOLAR_MASS_KG_MOL = 0.01801528
FARADAY_C_MOL = 96485.33212
ACTIVITY_EPS = 1.0e-7

EXPECTED_ACTIVE_VERSION = "active-eo-erv-terminal1-v2.2.2-2026-08-23"
EXPECTED_ACTIVE_ROWS = 90
EXPECTED_ARCHIVE_ROWS = 12
EXPECTED_ARCHIVE_SHA256 = (
    "32597974e9001fef89a4d02e9d4b2494120ed5a98d854575771da1da4f0bfc5d"
)


class StudyError(RuntimeError):
    """Raised when provenance, model, or study invariants are violated."""


@dataclass(frozen=True)
class RuntimePaths:
    v2_root: Path
    central_manifest: Path
    v2_model: Path
    v2_config: Path
    v3_axial: Path
    active_config: Path
    active_core: Path
    system_core: Path
    active_manifest: Path
    active_status: Path
    baseline_audit: Path
    archive_cases: Path
    detailed_cases: Path


_WORKER_RUNTIME: dict[str, Any] | None = None


def parse_args() -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description="Dense post-ERV membrane/operating inverse-design study.",
    )
    parser.add_argument("--repo-root", type=Path, default=repo_root)
    parser.add_argument("--v2-root", type=Path, default=Path("/home/torsheim/HeiQ/HeiQ_V2"))
    parser.add_argument(
        "--config",
        type=Path,
        default=repo_root / "config" / "membrane_operating_region_study_v1.json",
    )
    parser.add_argument(
        "--detailed-cases",
        type=Path,
        default=None,
        help=(
            "Explicit detailed-HVAC comparison CSV; when omitted, use the legacy "
            "HeiQ_V2 closure-study path"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=repo_root / "outputs" / "membrane_operating_region_study_v1" / "post_erv",
    )
    parser.add_argument("--jobs", type=int, default=min(8, os.cpu_count() or 1))
    parser.add_argument("--area-step-m2", type=float, default=5.0)
    parser.add_argument("--regression-only", action="store_true")
    parser.add_argument(
        "--postprocess-existing",
        action="store_true",
        help=(
            "Rebuild derived CSV summaries, plots and audit from existing dense/global "
            "case CSVs without rerunning the transport solver"
        ),
    )
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
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
    if isinstance(value, (np.bool_,)):
        return bool(value)
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(json_safe(dict(payload)), indent=2, sort_keys=True) + "\n",
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


def scalar(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        if value.size != 1:
            raise StudyError(f"Expected scalar array, got {value.shape}")
        value = value.reshape(-1)[0]
    if isinstance(value, np.generic):
        return value.item()
    return value


def finite(value: Any, default: float = math.nan) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def truth(value: Any) -> bool:
    value = scalar(value)
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def bool_series(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series.fillna(False)
    return (
        series.astype(str)
        .str.strip()
        .str.lower()
        .map({"true": True, "false": False})
        .fillna(False)
        .astype(bool)
    )


def normalize_area_observations(frame: pd.DataFrame) -> pd.DataFrame:
    """Keep solver progress separate from observed/censored required area.

    A transport or numerical failure can occur before any membrane area has
    been integrated.  That raw progress belongs in ``solver_observed_area_m2``
    but is not an area estimate and must not enter plots, Pareto ranking, or
    PRCC as zero.  The analysis coordinate is defined only for target-reached
    rows and rows right-censored at the registered area cap.
    """

    result = frame.copy()
    required = {
        "target_reached",
        "area_is_right_censored",
        "solver_observed_area_m2",
    }
    missing = sorted(required.difference(result.columns))
    if missing:
        raise StudyError(f"Cannot normalize area observations; missing columns: {missing}")
    if "solver_script_version" in result.columns:
        solver_versions = result["solver_script_version"].astype(str)
    elif "script_version" in result.columns:
        solver_versions = result["script_version"].astype(str)
        result["solver_script_version"] = solver_versions
    else:
        raise StudyError("Cannot preserve solver provenance; no solver/script version column")
    observed_versions = set(solver_versions.dropna().unique())
    if not observed_versions or not observed_versions.issubset(
        KNOWN_SOLVER_SCRIPT_VERSIONS
    ):
        raise StudyError(
            f"Unsupported solver script version(s): {sorted(observed_versions)}"
        )
    target = bool_series(result["target_reached"])
    censored = bool_series(result["area_is_right_censored"])
    if bool((target & censored).any()):
        raise StudyError("A row cannot be both target-reached and area-right-censored")
    raw_area = pd.to_numeric(result["solver_observed_area_m2"], errors="coerce")
    result["required_active_area_m2"] = raw_area.where(target)
    result["required_active_area_censored_m2"] = raw_area.where(target | censored)
    for raw_name, target_name in (
        (
            "incremental_saving_kw_vs_passive_erv",
            "target_reached_screening_saving_kw",
        ),
        (
            "incremental_saving_pct_vs_passive_erv",
            "target_reached_screening_saving_pct",
        ),
    ):
        if raw_name in result.columns:
            result[target_name] = pd.to_numeric(
                result[raw_name], errors="coerce"
            ).where(target)
    result["script_version"] = SCRIPT_VERSION
    result["analysis_script_version"] = SCRIPT_VERSION
    result["area_observation_status"] = np.select(
        [censored.to_numpy(), target.to_numpy()],
        ["RIGHT_CENSORED_AT_CAP", "OBSERVED"],
        default="NOT_OBSERVED",
    )
    return result


def resolve_paths(
    v2_root: Path,
    central_manifest: Path,
    detailed_cases_override: Path | None = None,
) -> RuntimePaths:
    root = v2_root.expanduser().resolve()
    active_tool = root / "tools" / "HeiQ_active_eo_erv_terminal1_v2"
    active_output = root / "outputs" / "active_eo_erv_terminal1_v2_study"
    archive = (
        root
        / "outputs"
        / "archive_terminal1_post_erv_diffusivity_sensitivity_v1_20260825T084804Z"
    )
    detailed = root / "outputs" / "terminal1_post_erv_physics_closure_v1_smoke"
    return RuntimePaths(
        v2_root=root,
        central_manifest=central_manifest.expanduser().resolve(),
        v2_model=root / "heiq_pre_receiver_material_analyses" / "heiq_pre_receiver_model.py",
        v2_config=root / "heiq_pre_receiver_material_analyses" / "config" / "default.json",
        v3_axial=root / "scripts" / "make_wp1_pre_receiver_axial_v3.py",
        active_config=active_tool / "configs" / "active_eo_erv_study.json",
        active_core=active_tool / "active_core.py",
        system_core=active_tool / "system_core.py",
        active_manifest=active_output / "active_eo_erv_manifest.json",
        active_status=active_output / "active_eo_erv_status.json",
        baseline_audit=active_output / "baseline_reproduction_audit.json",
        archive_cases=archive / "post_erv_diffusivity_cases.csv",
        detailed_cases=(
            detailed_cases_override.expanduser().resolve()
            if detailed_cases_override is not None
            else detailed / "detailed_hvac_base_cases_with_pareto_flag.csv"
        ),
    )


def require_runtime_files(paths: RuntimePaths) -> None:
    required = [
        paths.central_manifest,
        paths.v2_model,
        paths.v2_config,
        paths.v3_axial,
        paths.active_config,
        paths.active_core,
        paths.system_core,
        paths.active_manifest,
        paths.active_status,
        paths.baseline_audit,
        paths.archive_cases,
        paths.detailed_cases,
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise StudyError("Missing required input files:\n  " + "\n  ".join(missing))


def anchor_material_from_config(config: Mapping[str, Any]) -> dict[str, Any]:
    anchor = dict(config["post_erv"]["terminal1_anchor"])
    return {
        "water_drag": float(anchor["water_drag"]),
        "water_diffusivity_m2_s": float(anchor["water_diffusivity_m2_s"]),
        "conductivity_s_m": float(anchor["conductivity_s_m"]),
        "dry_thickness_um": float(anchor["dry_thickness_um"]),
        "water_capacity_mol_m3_activity": float(
            anchor["water_capacity_mol_m3_activity"]
        ),
        "diffusivity_activity_exponent": float(
            anchor["diffusivity_activity_exponent"]
        ),
        "conductivity_activity_exponent": float(
            anchor["conductivity_activity_exponent"]
        ),
        "capacity_activity_exponent": float(anchor["capacity_activity_exponent"]),
        "series_asr_ohm_m2": float(anchor["series_area_resistance_ohm_m2"]),
        "fixed_loss_voltage_v": 0.0,
    }


def load_runtime(paths: RuntimePaths, config: Mapping[str, Any], area_step_m2: float) -> dict[str, Any]:
    require_runtime_files(paths)
    active_manifest = read_json(paths.active_manifest)
    active_status = read_json(paths.active_status)
    active_cfg = read_json(paths.active_config)
    baseline_audit = read_json(paths.baseline_audit)
    archive_hash = sha256_file(paths.archive_cases)

    if active_manifest.get("script_version") != EXPECTED_ACTIVE_VERSION:
        raise StudyError("Unexpected active-ERV manifest version")
    if active_status.get("script_version") != EXPECTED_ACTIVE_VERSION:
        raise StudyError("Unexpected active-ERV status version")
    if int(active_status.get("completed_case_count", -1)) != EXPECTED_ACTIVE_ROWS:
        raise StudyError("Validated active-ERV study is not the expected 90-row run")
    if int(active_status.get("full_coupled_gate_case_count", -1)) != 0:
        raise StudyError("Validated active-ERV full-coupled count has changed")
    if not bool(baseline_audit.get("pass")):
        raise StudyError("Passive ERV baseline audit is not passing")
    if archive_hash != EXPECTED_ARCHIVE_SHA256:
        raise StudyError(
            f"12-case archive hash mismatch: {archive_hash} != {EXPECTED_ARCHIVE_SHA256}"
        )

    source_hashes = {
        "v2_model": sha256_file(paths.v2_model),
        "v2_default_config": sha256_file(paths.v2_config),
        "v3_axial_script": sha256_file(paths.v3_axial),
        "active_config": sha256_file(paths.active_config),
        "active_core": sha256_file(paths.active_core),
        "system_core": sha256_file(paths.system_core),
    }
    manifest_hashes = active_manifest["file_sha256"]
    manifest_key = {
        "v2_model": "v2_model",
        "v2_default_config": "v2_default_config",
        "v3_axial_script": "v3_axial_script",
        "active_config": "config",
        "active_core": "active_core",
        "system_core": "system_core",
    }
    for local_key, active_key in manifest_key.items():
        if source_hashes[local_key] != manifest_hashes[active_key]:
            raise StudyError(
                f"Hash mismatch for {local_key}: {source_hashes[local_key]} "
                f"!= {manifest_hashes[active_key]}"
            )

    system_core = load_module(paths.system_core, "system_core")
    active_core = load_module(paths.active_core, "posterv_inverse_active_core")
    v2 = load_module(paths.v2_model, "posterv_inverse_v2")
    v3 = load_module(paths.v3_axial, "posterv_inverse_v3")
    v2_config = v2.load_config(paths.v2_config)

    states = active_core.states_from_config(active_cfg)
    baseline = active_core.build_passive_baseline(
        active_cfg,
        states,
        float(active_cfg["reference_case"]["sensible_effectiveness"]),
    )
    process_in = baseline.passive_erv.oa_out
    receiver_in = baseline.passive_erv.exhaust_out
    post_cfg = config["post_erv"]
    expected_state = {
        "process_t": float(post_cfg["process_inlet_temperature_c"]),
        "process_w": float(post_cfg["process_inlet_humidity_ratio_kg_kg_da"]),
        "receiver_t": float(post_cfg["receiver_inlet_temperature_c"]),
        "receiver_w": float(post_cfg["receiver_inlet_humidity_ratio_kg_kg_da"]),
        "reference_kw": float(post_cfg["passive_erv_plus_ac_reference_kw"]),
    }
    actual_state = {
        "process_t": float(process_in.t_c),
        "process_w": float(process_in.w),
        "receiver_t": float(receiver_in.t_c),
        "receiver_w": float(receiver_in.w),
        "reference_kw": float(baseline.total_power_kw),
    }
    for key, expected in expected_state.items():
        if not math.isclose(actual_state[key], expected, rel_tol=1e-10, abs_tol=1e-12):
            raise StudyError(f"Central manifest mismatch for {key}: {actual_state[key]} != {expected}")

    anchor = anchor_material_from_config(config)
    inverse_cfg = post_cfg["global_inverse_design"]
    expected_parameterization = (
        "water_drag, D*C/L, total_L_over_sigma_plus_series_ASR, current_density"
    )
    if inverse_cfg.get("sampled_coordinate_parameterization") != expected_parameterization:
        raise StudyError("Global sampled-coordinate parameterization is not explicit")
    if inverse_cfg.get("dry_thickness_independently_sampled") is not False:
        raise StudyError("Dry thickness must be declared not independently sampled")
    if "dry_thickness_um_range" in inverse_cfg:
        raise StudyError("Unused dry-thickness sampling range must not be present")
    if not math.isclose(
        float(inverse_cfg.get("mapping_dry_thickness_um", math.nan)),
        float(anchor["dry_thickness_um"]),
        rel_tol=1.0e-12,
        abs_tol=1.0e-12,
    ):
        raise StudyError("Composite-to-raw mapping thickness differs from the anchor")
    if not str(inverse_cfg.get("identifiability_note", "")).strip():
        raise StudyError("Global inverse-design identifiability note is missing")
    active_anchor = active_manifest["terminal1_material_override"]
    comparisons = {
        "water_drag": active_anchor["water_drag"],
        "water_diffusivity_m2_s": active_anchor["water_diffusivity_m2_s"],
        "conductivity_s_m": active_anchor["conductivity_s_m"],
        "dry_thickness_um": active_anchor["dry_thickness_um"],
        "water_capacity_mol_m3_activity": active_anchor[
            "water_capacity_mol_m3_activity"
        ],
        "diffusivity_activity_exponent": active_anchor[
            "diffusivity_activity_exponent"
        ],
        "conductivity_activity_exponent": active_anchor[
            "conductivity_activity_exponent"
        ],
        "capacity_activity_exponent": active_anchor["capacity_activity_exponent"],
    }
    for key, expected in comparisons.items():
        if not math.isclose(float(anchor[key]), float(expected), rel_tol=1e-12, abs_tol=1e-30):
            raise StudyError(f"Terminal-1 anchor mismatch for {key}")

    process_film = v3.calculate_film_state(
        side="process",
        temperature_c=float(process_in.t_c),
        velocity_m_s=2.0,
        gap_m=0.002,
        pressure_pa=float(post_cfg["pressure_pa"]),
        scale_factor=1.0,
    )
    receiver_film = v3.calculate_film_state(
        side="receiver",
        temperature_c=float(receiver_in.t_c),
        velocity_m_s=2.0,
        gap_m=0.002,
        pressure_pa=float(post_cfg["pressure_pa"]),
        scale_factor=1.0,
    )
    k_source = float(process_film.activity_film_coefficient_mol_m2_s_activity)
    k_receiver = float(receiver_film.activity_film_coefficient_mol_m2_s_activity)
    if not math.isclose(
        k_source,
        float(post_cfg["source_film_coefficient_mol_m2_s_activity"]),
        rel_tol=1e-12,
    ):
        raise StudyError("Process-film coefficient does not reproduce central manifest")
    if not math.isclose(
        k_receiver,
        float(post_cfg["receiver_film_coefficient_mol_m2_s_activity"]),
        rel_tol=1e-12,
    ):
        raise StudyError("Receiver-film coefficient does not reproduce central manifest")

    return {
        "paths": paths,
        "config": config,
        "active_manifest": active_manifest,
        "active_status": active_status,
        "active_cfg": active_cfg,
        "baseline_audit": baseline_audit,
        "source_hashes": source_hashes,
        "archive_sha256": archive_hash,
        "v2": v2,
        "v3": v3,
        "system_core": system_core,
        "v2_config": v2_config,
        "baseline": baseline,
        "process_in": process_in,
        "receiver_in": receiver_in,
        "anchor": anchor,
        "source_film_coefficient": k_source,
        "receiver_film_coefficient": k_receiver,
        "target_w": float(post_cfg["target_process_humidity_ratio_kg_kg_da"]),
        "area_limit_m2": float(post_cfg["area_solver_observation_cap_m2"]),
        "area_step_m2": float(area_step_m2),
        "power_electronics_efficiency": float(post_cfg["power_electronics_efficiency"]),
        "fan_power_kw_per_m2": float(
            post_cfg["process_and_receiver_fan_power_kw_per_m2"]
        ),
        "pressure_pa": float(post_cfg["pressure_pa"]),
        "dry_air_mass_flow_kg_s": float(post_cfg["process_dry_air_mass_flow_kg_s"]),
    }


def local_state(runtime: Mapping[str, Any], material: Mapping[str, float], process_w: float, receiver_w: float, current: float) -> dict[str, Any]:
    v2 = runtime["v2"]
    v3 = runtime["v3"]
    process_t = float(runtime["process_in"].t_c)
    receiver_t = float(runtime["receiver_in"].t_c)
    pressure = float(runtime["pressure_pa"])
    source_activity = v3.activity_from_t_w(process_t, process_w, pressure)
    receiver_activity = v3.activity_from_t_w(receiver_t, receiver_w, pressure)
    if not ACTIVITY_EPS < source_activity < 1.0 - ACTIVITY_EPS:
        return {
            "solution_ok": False,
            "solution_status": "source_bulk_activity_out_of_bounds",
        }
    if not ACTIVITY_EPS < receiver_activity < 1.0 - ACTIVITY_EPS:
        return {
            "solution_ok": False,
            "solution_status": "receiver_bulk_activity_out_of_bounds",
        }

    model = dict(runtime["v2_config"]["model"])
    model["temperature_c"] = process_t
    model["source_film_coefficient_mol_m2_s_activity"] = float(
        runtime["source_film_coefficient"]
    )
    model["receiver_film_coefficient_mol_m2_s_activity"] = float(
        runtime["receiver_film_coefficient"]
    )
    model["series_area_resistance_ohm_m2"] = float(material["series_asr_ohm_m2"])
    model["other_voltage_lower_bound_v"] = float(material["fixed_loss_voltage_v"])
    local_config = {
        "model": model,
        "activity_cases": {
            "axial_local": {
                "source_bulk_water_activity": source_activity,
                "receiver_bulk_water_activity": receiver_activity,
                "interpretation": "post-ERV counter-current local state",
            }
        },
    }
    parameters = pd.DataFrame(
        {
            "water_drag": [float(material["water_drag"])],
            "water_diffusivity_m2_s": [float(material["water_diffusivity_m2_s"])],
            "conductivity_s_m": [float(material["conductivity_s_m"])],
            "dry_thickness_um": [float(material["dry_thickness_um"])],
            "water_capacity_mol_m3_activity": [
                float(material["water_capacity_mol_m3_activity"])
            ],
            "diffusivity_activity_exponent": [
                float(material["diffusivity_activity_exponent"])
            ],
            "conductivity_activity_exponent": [
                float(material["conductivity_activity_exponent"])
            ],
            "capacity_activity_exponent": [
                float(material["capacity_activity_exponent"])
            ],
        }
    )
    raw = v2.solve_powerlaw_at_current(parameters, float(current), local_config, "axial_local")
    record = {key: scalar(value) for key, value in raw.items()}
    signed_voltage = finite(record.get("cell_voltage_signed_v"))
    imposed_current = finite(record.get("current_density_a_m2"))
    return {
        **record,
        "solution_ok": truth(record.get("solver_success")),
        "solution_status": str(record.get("solver_status", "unknown")),
        "source_bulk_activity": source_activity,
        "receiver_bulk_activity": receiver_activity,
        "required_terminal_voltage_signed_v": signed_voltage,
        "series_loss_voltage_v": imposed_current
        * float(material["series_asr_ohm_m2"]),
        "fixed_loss_voltage_v": float(material["fixed_loss_voltage_v"]),
    }


def local_gate(state: Mapping[str, Any]) -> str:
    if not truth(state.get("solution_ok")):
        return f"local_solver:{state.get('solution_status', 'unknown')}"
    flux = finite(state.get("net_flux_mol_m2_s"))
    a_source = finite(state.get("source_surface_activity"))
    a_receiver = finite(state.get("receiver_surface_activity"))
    voltage = finite(state.get("required_terminal_voltage_signed_v"))
    if not math.isfinite(flux) or flux <= 0.0:
        return "nonpositive_net_flux"
    if not (
        ACTIVITY_EPS < a_source < 1.0 - ACTIVITY_EPS
        and ACTIVITY_EPS < a_receiver < 1.0 - ACTIVITY_EPS
    ):
        return "surface_activity_out_of_bounds"
    if not math.isfinite(voltage):
        return "nonfinite_required_voltage"
    return "pass"


def integrate_case(runtime: Mapping[str, Any], case: Mapping[str, Any]) -> dict[str, Any]:
    """Integrate one uniform-current case over active membrane area.

    The algorithm is the validated predictor/corrector counter-current water
    balance used by the archived post-ERV study.  Profiles are reduced online;
    this keeps a 1600+ case study practical without changing the equations.
    """

    material = {
        key: float(case[key])
        for key in (
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
    }
    current = float(case["uniform_current_density_a_m2"])
    process_in = runtime["process_in"]
    receiver_in = runtime["receiver_in"]
    baseline = runtime["baseline"]
    system_core = runtime["system_core"]
    active_cfg = runtime["active_cfg"]
    pressure = float(runtime["pressure_pa"])
    m_da = float(runtime["dry_air_mass_flow_kg_s"])
    receiver_to_process_ratio = float(
        case.get(
            "receiver_to_process_dry_air_ratio",
            runtime.get("receiver_to_process_dry_air_ratio", 1.0),
        )
    )
    if not math.isfinite(receiver_to_process_ratio) or receiver_to_process_ratio <= 0.0:
        raise StudyError("Receiver-to-process dry-air ratio must be finite and positive")
    receiver_m_da = m_da * receiver_to_process_ratio
    process_t = float(process_in.t_c)
    receiver_t = float(receiver_in.t_c)
    w_in = float(process_in.w)
    receiver_in_w = float(receiver_in.w)
    target_w = float(runtime["target_w"])
    total_dw = w_in - target_w
    area_limit = float(runtime["area_limit_m2"])
    nominal_step = float(runtime["area_step_m2"])
    minimum_step = min(nominal_step / 64.0, 0.05)
    efficiency = float(runtime["power_electronics_efficiency"])
    if total_dw <= 0.0:
        raise StudyError("Post-ERV target must be below inlet humidity ratio")

    area = 0.0
    w = w_in
    status = "area_limit_before_target"
    net_mol_s = 0.0
    eo_mol_s = 0.0
    diff_mol_s = 0.0
    p_mu_w = 0.0
    p_ohm_w = 0.0
    p_asr_w = 0.0
    p_fixed_w = 0.0
    grid_import_w = 0.0
    grid_export_upper_w = 0.0
    integrated_current_a = 0.0
    minimum_flux = math.inf
    minimum_surface_margin = math.inf
    minimum_legacy_average_surface_margin = math.inf
    maximum_film_utilisation = -math.inf
    minimum_crossover_current = math.inf
    minimum_voltage = math.inf
    maximum_voltage = -math.inf
    weighted_voltage_area = 0.0
    negative_voltage_area = 0.0
    maximum_receiver_bulk_rh = -math.inf
    maximum_receiver_surface_activity = -math.inf
    integration_steps = 0

    def receiver_w_from_process(process_w: float) -> float:
        return receiver_in_w + (m_da / receiver_m_da) * (process_w - target_w)

    def solve_local(process_w: float) -> dict[str, Any]:
        return local_state(
            runtime,
            material,
            process_w,
            receiver_w_from_process(process_w),
            current,
        )

    while area < area_limit - 1.0e-12:
        if w <= target_w + 1.0e-10:
            status = "target_reached"
            break
        step = min(nominal_step, area_limit - area)
        start = solve_local(w)
        gate = local_gate(start)
        if gate != "pass":
            status = gate
            break
        d_w_start = (
            -WATER_MOLAR_MASS_KG_MOL
            * float(start["net_flux_mol_m2_s"])
            / m_da
        )
        while True:
            predicted = w + d_w_start * step
            if predicted <= 0.0:
                end: dict[str, Any] = {}
                end_gate = "predictor_negative_humidity"
            else:
                end = solve_local(predicted)
                end_gate = local_gate(end)
            if end_gate == "pass":
                break
            if step <= minimum_step + 1.0e-12:
                status = f"corrector_failure:{end_gate}"
                break
            step = max(0.5 * step, minimum_step)
        if status.startswith("corrector_failure"):
            break

        d_w_end = (
            -WATER_MOLAR_MASS_KG_MOL
            * float(end["net_flux_mol_m2_s"])
            / m_da
        )
        corrected = w + 0.5 * (d_w_start + d_w_end) * step
        fraction = 1.0
        if corrected < target_w:
            denominator = w - corrected
            fraction = (w - target_w) / denominator if denominator > 0.0 else 0.0
            fraction = float(np.clip(fraction, 0.0, 1.0))
        d_area = step * fraction
        next_w = w + fraction * (corrected - w)

        def average(name: str) -> float:
            return 0.5 * (float(start[name]) + float(end[name]))

        net_flux = average("net_flux_mol_m2_s")
        eo_flux = average("eo_flux_mol_m2_s")
        diffusion_flux = average("diffusion_flux_mol_m2_s")
        source_bulk_activity = 0.5 * (
            float(start["source_bulk_activity"])
            + float(end["source_bulk_activity"])
        )
        source_surface_activity = average("source_surface_activity")
        receiver_surface_activity = average("receiver_surface_activity")
        start_surface_margin = (
            float(start["source_surface_activity"])
            - float(start["receiver_surface_activity"])
        )
        end_surface_margin = (
            float(end["source_surface_activity"])
            - float(end["receiver_surface_activity"])
        )
        receiver_bulk_w = 0.5 * (
            receiver_w_from_process(w) + receiver_w_from_process(next_w)
        )
        film_ceiling = max(
            0.0,
            float(runtime["source_film_coefficient"])
            * (source_bulk_activity - ACTIVITY_EPS),
        )
        film_utilisation = net_flux / film_ceiling if film_ceiling > 0.0 else math.nan
        crossover_current = (
            FARADAY_C_MOL * film_ceiling / float(material["water_drag"])
        )
        voltage = average("required_terminal_voltage_signed_v")
        water_voltage = average("water_polarisation_voltage_v")
        ohmic_voltage = average("ohmic_voltage_v")
        series_voltage = current * float(material["series_asr_ohm_m2"])
        fixed_voltage = float(material["fixed_loss_voltage_v"])
        power_density = current * voltage

        net_mol_s += net_flux * d_area
        eo_mol_s += eo_flux * d_area
        diff_mol_s += diffusion_flux * d_area
        p_mu_w += current * water_voltage * d_area
        p_ohm_w += current * ohmic_voltage * d_area
        p_asr_w += current * series_voltage * d_area
        p_fixed_w += current * fixed_voltage * d_area
        integrated_current_a += current * d_area
        if power_density >= 0.0:
            grid_import_w += power_density * d_area / efficiency
        else:
            grid_export_upper_w += (-power_density) * d_area * efficiency

        minimum_flux = min(
            minimum_flux,
            float(start["net_flux_mol_m2_s"]),
            float(end["net_flux_mol_m2_s"]),
        )
        minimum_surface_margin = min(
            minimum_surface_margin,
            start_surface_margin,
            end_surface_margin,
        )
        minimum_legacy_average_surface_margin = min(
            minimum_legacy_average_surface_margin,
            source_surface_activity - receiver_surface_activity,
        )
        if math.isfinite(film_utilisation):
            maximum_film_utilisation = max(
                maximum_film_utilisation, film_utilisation
            )
        minimum_crossover_current = min(minimum_crossover_current, crossover_current)
        minimum_voltage = min(
            minimum_voltage,
            float(start["required_terminal_voltage_signed_v"]),
            float(end["required_terminal_voltage_signed_v"]),
        )
        maximum_voltage = max(
            maximum_voltage,
            float(start["required_terminal_voltage_signed_v"]),
            float(end["required_terminal_voltage_signed_v"]),
        )
        weighted_voltage_area += voltage * d_area
        if voltage < 0.0:
            negative_voltage_area += d_area
        receiver_rh = system_core.relative_humidity_from_t_w(
            receiver_t, receiver_bulk_w, pressure
        )
        maximum_receiver_bulk_rh = max(maximum_receiver_bulk_rh, receiver_rh)
        maximum_receiver_surface_activity = max(
            maximum_receiver_surface_activity,
            float(start["receiver_surface_activity"]),
            float(end["receiver_surface_activity"]),
        )

        area += d_area
        w = next_w
        integration_steps += 1
        if fraction < 1.0:
            status = "target_reached"
            break

    # Reaching the target exactly on the registered area cap is an observed
    # target, not a right-censored failure.  The same tolerance is used at the
    # top of the integration loop.
    if status == "area_limit_before_target" and w <= target_w + 1.0e-10:
        status = "target_reached"

    net_kg_h = net_mol_s * WATER_MOLAR_MASS_KG_MOL * 3600.0
    eo_kg_h = eo_mol_s * WATER_MOLAR_MASS_KG_MOL * 3600.0
    diff_kg_h = diff_mol_s * WATER_MOLAR_MASS_KG_MOL * 3600.0
    air_balance_kg_h = m_da * (w_in - w) * 3600.0
    target_water_kg_h = m_da * (w_in - target_w) * 3600.0
    water_error = (net_kg_h - air_balance_kg_h) / max(
        abs(net_kg_h), abs(air_balance_kg_h), 1.0e-12
    )
    target_reached = status == "target_reached"
    receiver_out_w = receiver_in_w + (m_da / receiver_m_da) * (w_in - w)
    receiver_out = system_core.state_from_t_w(
        receiver_t, receiver_out_w, pressure, "post-EO receiver outlet"
    )
    process_out = system_core.state_from_t_w(
        process_t, w, pressure, "post-EO process outlet"
    )
    receiver_gain_kg_h = (
        receiver_m_da * (receiver_out_w - receiver_in_w) * 3600.0
    )
    receiver_error = (receiver_gain_kg_h - air_balance_kg_h) / max(
        abs(receiver_gain_kg_h), abs(air_balance_kg_h), 1.0e-12
    )

    fan_power_kw = area * float(runtime["fan_power_kw_per_m2"])
    # The validated model splits this almost equally; only the sum participates
    # in the energy boundary and is the registered quantity in the central manifest.
    process_fan_kw = fan_power_kw / 2.0
    receiver_fan_kw = fan_power_kw - process_fan_kw
    remaining_ac = system_core.solve_coil(
        inlet=process_out,
        supply_target=baseline.remaining_ac.supply,
        m_da=m_da,
        rated_cop=baseline.rated_cop,
        ac_config=active_cfg["ac_model"],
    )
    eo_grid_import_kw = grid_import_w / 1000.0
    export_upper_kw = grid_export_upper_w / 1000.0
    erv_power_kw = float(baseline.passive_erv.total_power_kw)
    common_kw = float(active_cfg["common_components"]["common_electric_power_kw_each_system"])
    conservative_total_kw = (
        erv_power_kw
        + float(remaining_ac.total_ac_power_kw)
        + fan_power_kw
        + eo_grid_import_kw
        + common_kw
    )
    ideal_bidirectional_total_kw = conservative_total_kw - export_upper_kw
    saving_kw = float(baseline.total_power_kw) - conservative_total_kw
    saving_pct = 100.0 * saving_kw / float(baseline.total_power_kw)
    baseline_remaining_ac_kw = float(baseline.remaining_ac.total_ac_power_kw)
    ac_reduction_kw = baseline_remaining_ac_kw - float(remaining_ac.total_ac_power_kw)
    addon_kw = eo_grid_import_kw + fan_power_kw
    power_identity_error_kw = saving_kw - (ac_reduction_kw - addon_kw)

    transport_gate = bool(
        target_reached
        and abs(water_error) <= 5.0e-3
        and abs(receiver_error) <= 5.0e-3
        and minimum_flux > 0.0
        and maximum_film_utilisation < 1.0 + 1.0e-6
        and receiver_out.rh <= 0.98 + 1.0e-9
    )
    mechanism_energy_gate = bool(
        transport_gate and remaining_ac.physical and math.isfinite(conservative_total_kw)
    )
    conditional_energy_pass = bool(mechanism_energy_gate and saving_kw > 0.0)
    right_censored = bool(status == "area_limit_before_target")
    positive_surface_direction = bool(
        minimum_surface_margin > 0.0
        if minimum_surface_margin < math.inf
        else False
    )
    permeability = (
        float(material["water_diffusivity_m2_s"])
        * float(material["water_capacity_mol_m3_activity"])
        / (float(material["dry_thickness_um"]) * 1.0e-6)
    )
    membrane_asr = (
        float(material["dry_thickness_um"]) * 1.0e-6
        / float(material["conductivity_s_m"])
    )
    total_reference_asr = membrane_asr + float(material["series_asr_ohm_m2"])

    return {
        **dict(case),
        "script_version": SCRIPT_VERSION,
        "solver_script_version": SCRIPT_VERSION,
        "analysis_script_version": SCRIPT_VERSION,
        "model_boundary": "passive ERV outlet -> finite-film isothermal EO polishing -> remaining screening AC",
        "target_definition": "10 percent relative reduction in humidity ratio, not RH",
        "engineering_current_density_limit_a_m2": None,
        "current_density_is_sampling_or_control_axis": True,
        "status": status,
        "numerical_status": "TARGET_REACHED" if target_reached else "NOT_TARGET_REACHED",
        "transport_gate_status": "PASS" if transport_gate else "FAIL",
        "screening_energy_status": (
            "CONDITIONAL_POSITIVE"
            if conditional_energy_pass
            else "NONPOSITIVE_OR_TRANSPORT_FAIL"
        ),
        "surface_direction_status": "PASS" if positive_surface_direction else "FAIL",
        "area_observation_status": (
            "RIGHT_CENSORED_AT_CAP"
            if right_censored
            else ("OBSERVED" if target_reached else "NOT_OBSERVED")
        ),
        "full_system_status": "UNKNOWN",
        "full_system_claim_allowed": False,
        "missing_receiver_energy_status": "UNKNOWN",
        "screening_hvac_used_for_full_grid": True,
        "target_reached": target_reached,
        "transport_gate_pass": transport_gate,
        "mechanism_energy_gate_pass": mechanism_energy_gate,
        "conditional_energy_pass": conditional_energy_pass,
        "positive_surface_direction_everywhere": positive_surface_direction,
        "area_is_right_censored": right_censored,
        "area_observation_cap_m2": area_limit,
        "solver_observed_area_m2": area,
        "required_active_area_m2": area if target_reached else math.nan,
        "required_active_area_censored_m2": (
            area if (target_reached or right_censored) else math.nan
        ),
        "integration_step_count": integration_steps,
        "outlet_w_g_kg_da": 1000.0 * w,
        "target_w_g_kg_da": 1000.0 * target_w,
        "incremental_water_removal_target_kg_h": target_water_kg_h,
        "receiver_to_process_dry_air_ratio": receiver_to_process_ratio,
        "receiver_dry_air_mass_flow_kg_s": receiver_m_da,
        "net_water_transport_kg_h": net_kg_h,
        "eo_water_transport_kg_h": eo_kg_h,
        "signed_diffusion_water_transport_kg_h": diff_kg_h,
        "signed_diffusion_fraction_of_eo": (
            diff_kg_h / eo_kg_h if abs(eo_kg_h) > 1.0e-12 else math.nan
        ),
        "absolute_diffusion_fraction_of_eo": (
            abs(diff_kg_h) / abs(eo_kg_h) if abs(eo_kg_h) > 1.0e-12 else math.nan
        ),
        "water_balance_relative_error": water_error,
        "receiver_water_balance_relative_error": receiver_error,
        "integrated_current_a": integrated_current_a,
        "maximum_local_current_density_a_m2": current,
        "minimum_process_film_crossover_current_density_a_m2": (
            minimum_crossover_current
            if minimum_crossover_current < math.inf
            else math.nan
        ),
        "maximum_process_film_utilisation": (
            maximum_film_utilisation
            if maximum_film_utilisation > -math.inf
            else math.nan
        ),
        "minimum_surface_activity_margin": (
            minimum_surface_margin
            if minimum_surface_margin < math.inf
            else math.nan
        ),
        "legacy_step_average_minimum_surface_activity_margin": (
            minimum_legacy_average_surface_margin
            if minimum_legacy_average_surface_margin < math.inf
            else math.nan
        ),
        "minimum_required_terminal_voltage_signed_v": (
            minimum_voltage if minimum_voltage < math.inf else math.nan
        ),
        "maximum_required_terminal_voltage_signed_v": (
            maximum_voltage if maximum_voltage > -math.inf else math.nan
        ),
        "area_weighted_required_terminal_voltage_signed_v": (
            weighted_voltage_area / area if area > 0.0 else math.nan
        ),
        "negative_required_voltage_area_fraction": (
            negative_voltage_area / area if area > 0.0 else math.nan
        ),
        "water_chemical_potential_power_kw": p_mu_w / 1000.0,
        "membrane_ohmic_power_kw": p_ohm_w / 1000.0,
        "series_asr_power_kw": p_asr_w / 1000.0,
        "fixed_loss_power_kw": p_fixed_w / 1000.0,
        "eo_grid_import_kw_no_export_credit": eo_grid_import_kw,
        "eo_grid_export_upper_bound_kw": export_upper_kw,
        "process_channel_fan_power_kw": process_fan_kw,
        "receiver_channel_fan_power_kw": receiver_fan_kw,
        "incremental_module_fan_power_kw": fan_power_kw,
        "receiver_out_rh": receiver_out.rh,
        "maximum_receiver_bulk_rh": (
            maximum_receiver_bulk_rh
            if maximum_receiver_bulk_rh > -math.inf
            else math.nan
        ),
        "maximum_receiver_surface_activity": (
            maximum_receiver_surface_activity
            if maximum_receiver_surface_activity > -math.inf
            else math.nan
        ),
        "passive_reference_remaining_ac_power_kw": baseline_remaining_ac_kw,
        "remaining_ac_power_kw": remaining_ac.total_ac_power_kw,
        "incremental_ac_power_reduction_kw": ac_reduction_kw,
        "incremental_eo_and_fan_power_kw": addon_kw,
        "incremental_power_identity_error_kw": power_identity_error_kw,
        "passive_erv_plus_ac_reference_kw": baseline.total_power_kw,
        "conservative_erv_plus_eo_plus_ac_power_kw": conservative_total_kw,
        "ideal_bidirectional_upper_bound_system_power_kw": ideal_bidirectional_total_kw,
        "incremental_saving_kw_vs_passive_erv": saving_kw,
        "incremental_saving_pct_vs_passive_erv": saving_pct,
        "diffusive_permeability_d_c_over_l_mol_m2_s_activity": permeability,
        "membrane_area_resistance_l_over_sigma_ohm_m2": membrane_asr,
        "total_reference_area_resistance_ohm_m2": total_reference_asr,
        "independent_ion_concentration_potential_modelled": False,
        "ion_concentration_potential_result": "NOT MODELLED",
        "electrical_topology_evaluated": False,
        "module_rankability_evaluated": False,
    }


def worker_case(case: Mapping[str, Any]) -> dict[str, Any]:
    if _WORKER_RUNTIME is None:
        raise StudyError("Worker runtime was not initialized")
    try:
        return integrate_case(_WORKER_RUNTIME, case)
    except Exception as exc:  # pragma: no cover - retained as explicit study row
        return {
            **dict(case),
            "script_version": SCRIPT_VERSION,
            "solver_script_version": SCRIPT_VERSION,
            "analysis_script_version": SCRIPT_VERSION,
            "status": f"exception:{type(exc).__name__}:{exc}",
            "numerical_status": "EXCEPTION",
            "transport_gate_status": "FAIL",
            "screening_energy_status": "UNRESOLVED",
            "surface_direction_status": "UNKNOWN",
            "area_observation_status": "UNKNOWN",
            "full_system_status": "UNKNOWN",
            "full_system_claim_allowed": False,
            "target_reached": False,
            "transport_gate_pass": False,
            "mechanism_energy_gate_pass": False,
            "conditional_energy_pass": False,
            "area_is_right_censored": False,
            "solver_observed_area_m2": math.nan,
            "required_active_area_m2": math.nan,
            "required_active_area_censored_m2": math.nan,
        }


def anchored_grid(
    minimum: float,
    maximum: float,
    count: int,
    anchors: Sequence[float],
    *,
    logarithmic: bool,
) -> np.ndarray:
    if count < len(anchors) + 2:
        raise StudyError("Grid is too small for requested anchors")
    values = (
        np.geomspace(minimum, maximum, count)
        if logarithmic
        else np.linspace(minimum, maximum, count)
    )
    used: set[int] = set()
    transformed = np.log(values) if logarithmic else values
    for anchor in anchors:
        target = math.log(anchor) if logarithmic else anchor
        order = np.argsort(np.abs(transformed - target))
        index = next(int(idx) for idx in order if int(idx) not in used)
        values[index] = float(anchor)
        used.add(index)
        transformed = np.log(values) if logarithmic else values
    values.sort()
    if len(np.unique(values)) != count:
        raise StudyError("Anchored grid contains duplicate values")
    return values


def base_case_material(anchor: Mapping[str, float]) -> dict[str, float]:
    return {key: float(value) for key, value in anchor.items()}


def build_regression_cases(runtime: Mapping[str, Any]) -> list[dict[str, Any]]:
    anchor = base_case_material(runtime["anchor"])
    diffusivities = [
        1.597880133581376e-14,
        1.0e-12,
        1.0e-10,
        1.0e-9,
    ]
    currents = [5.0, 10.0, 15.0]
    cases: list[dict[str, Any]] = []
    for diffusivity in diffusivities:
        for current in currents:
            cases.append(
                {
                    **anchor,
                    "study_family": "archive_regression",
                    "case_id": f"reg__D{diffusivity:.12e}__j{current:g}",
                    "water_diffusivity_m2_s": diffusivity,
                    "uniform_current_density_a_m2": current,
                }
            )
    return cases


def build_dense_cases(runtime: Mapping[str, Any]) -> tuple[list[dict[str, Any]], np.ndarray, np.ndarray]:
    config = runtime["config"]["post_erv"]["dense_map"]
    anchor = base_case_material(runtime["anchor"])
    d_values = anchored_grid(
        float(config["water_diffusivity_min_m2_s"]),
        float(config["water_diffusivity_max_m2_s"]),
        int(config["water_diffusivity_points"]),
        [
            float(anchor["water_diffusivity_m2_s"]),
            1.0e-12,
            1.0e-10,
            1.0e-9,
        ],
        logarithmic=True,
    )
    j_values = anchored_grid(
        float(config["current_density_min_a_m2"]),
        float(config["current_density_max_a_m2"]),
        int(config["current_density_points"]),
        [5.0, 10.0, 15.0, 25.0],
        logarithmic=False,
    )
    cases: list[dict[str, Any]] = []
    for d_index, diffusivity in enumerate(d_values):
        for j_index, current in enumerate(j_values):
            cases.append(
                {
                    **anchor,
                    "study_family": "dense_dj",
                    "case_id": f"dense__d{d_index:02d}__j{j_index:02d}",
                    "dense_d_index": d_index,
                    "dense_j_index": j_index,
                    "water_diffusivity_m2_s": float(diffusivity),
                    "uniform_current_density_a_m2": float(current),
                }
            )
    return cases, d_values, j_values


def latin_hypercube(
    ranges: Mapping[str, tuple[float, float, str]],
    sample_count: int,
    seed: int,
) -> pd.DataFrame:
    if sample_count < 8:
        raise StudyError("LHS sample count is too small")
    rng = np.random.default_rng(int(seed))
    columns: dict[str, np.ndarray] = {}
    for name, (minimum, maximum, distribution) in ranges.items():
        strata = (np.arange(sample_count, dtype=float) + rng.random(sample_count)) / sample_count
        rng.shuffle(strata)
        if distribution == "uniform":
            values = minimum + strata * (maximum - minimum)
        elif distribution == "loguniform":
            values = np.exp(
                math.log(minimum) + strata * (math.log(maximum) - math.log(minimum))
            )
        else:
            raise StudyError(f"Unsupported LHS distribution: {distribution}")
        columns[name] = values
    return pd.DataFrame(columns)


def build_global_cases(runtime: Mapping[str, Any]) -> tuple[list[dict[str, Any]], pd.DataFrame]:
    cfg = runtime["config"]["post_erv"]["global_inverse_design"]
    anchor = base_case_material(runtime["anchor"])
    mapping_thickness_um = float(cfg["mapping_dry_thickness_um"])
    base_l_m = mapping_thickness_um * 1.0e-6
    base_capacity = float(anchor["water_capacity_mol_m3_activity"])
    base_membrane_asr = base_l_m / float(anchor["conductivity_s_m"])
    base_series_asr = float(anchor["series_asr_ohm_m2"])
    base_total_asr = base_membrane_asr + base_series_asr
    membrane_fraction = base_membrane_asr / base_total_asr
    series_fraction = base_series_asr / base_total_asr

    d_min, d_max = [float(value) for value in cfg["water_diffusivity_m2_s_range"]]
    sigma_min, sigma_max = [float(value) for value in cfg["conductivity_s_m_range"]]
    series_min, series_max = [
        float(value) for value in cfg["series_area_resistance_ohm_m2_range"]
    ]
    permeability_min = d_min * base_capacity / base_l_m
    permeability_max = d_max * base_capacity / base_l_m
    scale_min = max(
        float(anchor["conductivity_s_m"]) / sigma_max,
        series_min / base_series_asr,
    )
    scale_max = min(
        float(anchor["conductivity_s_m"]) / sigma_min,
        series_max / base_series_asr,
    )
    total_asr_min = base_total_asr * scale_min
    total_asr_max = base_total_asr * scale_max
    drag_min, drag_max = [float(value) for value in cfg["water_drag_range"]]
    j_min, j_max = [float(value) for value in cfg["current_density_a_m2_range"]]
    ranges = {
        "lhs_water_drag": (drag_min, drag_max, "loguniform"),
        "lhs_diffusive_permeability_d_c_over_l": (
            permeability_min,
            permeability_max,
            "loguniform",
        ),
        "lhs_total_reference_area_resistance_ohm_m2": (
            total_asr_min,
            total_asr_max,
            "loguniform",
        ),
        "lhs_uniform_current_density_a_m2": (j_min, j_max, "uniform"),
    }
    design = latin_hypercube(
        ranges,
        int(cfg["base_sample_size"]),
        int(cfg["seed"]),
    )
    cases: list[dict[str, Any]] = []
    for index, row in design.iterrows():
        permeability = float(row["lhs_diffusive_permeability_d_c_over_l"])
        total_asr = float(row["lhs_total_reference_area_resistance_ohm_m2"])
        derived_d = permeability * base_l_m / base_capacity
        derived_membrane_asr = total_asr * membrane_fraction
        derived_series_asr = total_asr * series_fraction
        derived_sigma = base_l_m / derived_membrane_asr
        case = {
            **anchor,
            "study_family": "global_lhs_prcc",
            "case_id": f"lhs__{int(index):04d}",
            "lhs_sample_index": int(index),
            "water_drag": float(row["lhs_water_drag"]),
            "water_diffusivity_m2_s": derived_d,
            "conductivity_s_m": derived_sigma,
            "series_asr_ohm_m2": derived_series_asr,
            "uniform_current_density_a_m2": float(
                row["lhs_uniform_current_density_a_m2"]
            ),
            "lhs_diffusive_permeability_d_c_over_l": permeability,
            "lhs_total_reference_area_resistance_ohm_m2": total_asr,
            "lhs_mapping_dry_thickness_um": mapping_thickness_um,
            "lhs_mapping_membrane_asr_fraction": membrane_fraction,
            "lhs_mapping_series_asr_fraction": series_fraction,
        }
        cases.append(case)
    bounds = pd.DataFrame(
        [
            {
                "parameter": name,
                "minimum": spec[0],
                "maximum": spec[1],
                "distribution": spec[2],
                "interpretation": "independent inverse-design coordinate; not a material probability distribution",
            }
            for name, spec in ranges.items()
        ]
    )
    return cases, bounds


def evaluate_cases(
    runtime: dict[str, Any],
    cases: Sequence[Mapping[str, Any]],
    *,
    jobs: int,
    label: str,
    checkpoint: Path | None = None,
) -> pd.DataFrame:
    global _WORKER_RUNTIME
    _WORKER_RUNTIME = runtime
    started = time.perf_counter()
    rows: list[dict[str, Any]] = []
    total = len(cases)
    if jobs <= 1:
        iterator: Iterable[dict[str, Any]] = (worker_case(case) for case in cases)
        pool = None
    else:
        context = mp.get_context("fork")
        pool = context.Pool(processes=jobs)
        iterator = pool.imap_unordered(worker_case, cases, chunksize=1)
    try:
        for index, result in enumerate(iterator, start=1):
            rows.append(result)
            if index == 1 or index % 50 == 0 or index == total:
                elapsed = time.perf_counter() - started
                rate = index / max(elapsed, 1.0e-9)
                remaining = (total - index) / max(rate, 1.0e-9)
                print(
                    f"[{label}] {index}/{total} cases; {rate:.2f} case/s; "
                    f"ETA {remaining / 60.0:.1f} min",
                    flush=True,
                )
            if checkpoint is not None and index % 100 == 0:
                pd.DataFrame(rows).to_csv(checkpoint, index=False)
    finally:
        if pool is not None:
            pool.close()
            pool.join()
    frame = pd.DataFrame(rows)
    if "case_id" in frame:
        frame = frame.sort_values("case_id").reset_index(drop=True)
    if checkpoint is not None:
        frame.to_csv(checkpoint, index=False)
    return frame


def archive_regression(
    calculated: pd.DataFrame,
    archive_path: Path,
) -> tuple[pd.DataFrame, bool]:
    archived = pd.read_csv(archive_path)
    if len(archived) != EXPECTED_ARCHIVE_ROWS or len(calculated) != EXPECTED_ARCHIVE_ROWS:
        raise StudyError("Archive regression does not contain exactly 12 rows")
    rows: list[dict[str, Any]] = []
    fields = [
        "solver_observed_area_m2",
        "outlet_w_g_kg_da",
        "net_water_transport_kg_h",
        "eo_water_transport_kg_h",
        "signed_diffusion_water_transport_kg_h",
        "water_balance_relative_error",
        "receiver_water_balance_relative_error",
        "integrated_current_a",
        "maximum_process_film_utilisation",
        "legacy_step_average_minimum_surface_activity_margin",
        "minimum_required_terminal_voltage_signed_v",
        "maximum_required_terminal_voltage_signed_v",
        "area_weighted_required_terminal_voltage_signed_v",
        "eo_grid_import_kw_no_export_credit",
        "incremental_module_fan_power_kw",
        "remaining_ac_power_kw",
        "incremental_saving_kw_vs_passive_erv",
        "incremental_saving_pct_vs_passive_erv",
    ]
    archive_field = {
        "solver_observed_area_m2": "required_active_area_m2",
        "legacy_step_average_minimum_surface_activity_margin": (
            "minimum_surface_activity_margin"
        ),
    }
    for _, expected in archived.iterrows():
        d_value = float(expected["water_diffusivity_m2_s"])
        j_value = float(expected["uniform_current_density_a_m2"])
        match = calculated[
            np.isclose(
                pd.to_numeric(calculated["water_diffusivity_m2_s"]),
                d_value,
                rtol=1.0e-12,
                atol=1.0e-30,
            )
            & np.isclose(
                pd.to_numeric(calculated["uniform_current_density_a_m2"]),
                j_value,
                rtol=1.0e-12,
                atol=1.0e-12,
            )
        ]
        if len(match) != 1:
            raise StudyError(f"Archive regression match count != 1 for D={d_value}, j={j_value}")
        actual = match.iloc[0]
        status_pass = str(actual["status"]) == str(expected["status"])
        bool_pass = all(
            truth(actual[key]) == truth(expected[key])
            for key in (
                "target_reached",
                "transport_gate_pass",
                "mechanism_energy_gate_pass",
            )
        )
        corrected_margin = finite(actual.get("minimum_surface_activity_margin"))
        legacy_margin = finite(
            actual.get("legacy_step_average_minimum_surface_activity_margin")
        )
        endpoint_margin_pass = bool(
            math.isfinite(corrected_margin)
            and math.isfinite(legacy_margin)
            and corrected_margin <= legacy_margin + 1.0e-12
        )
        case_pass = bool(status_pass and bool_pass and endpoint_margin_pass)
        for field in fields:
            expected_field = archive_field.get(field, field)
            actual_value = finite(actual.get(field))
            expected_value = finite(expected.get(expected_field))
            absolute_error = abs(actual_value - expected_value)
            scale = max(abs(expected_value), 1.0)
            tolerance = 2.0e-9 * scale + 1.0e-10
            field_pass = bool(
                math.isfinite(actual_value)
                and math.isfinite(expected_value)
                and absolute_error <= tolerance
            )
            case_pass = case_pass and field_pass
            rows.append(
                {
                    "water_diffusivity_m2_s": d_value,
                    "uniform_current_density_a_m2": j_value,
                    "field": field,
                    "archive_field": expected_field,
                    "actual": actual_value,
                    "expected": expected_value,
                    "absolute_error": absolute_error,
                    "tolerance": tolerance,
                    "field_pass": field_pass,
                    "status_pass": status_pass,
                    "boolean_gates_pass": bool_pass,
                    "endpoint_margin_more_conservative_pass": endpoint_margin_pass,
                    "released_endpoint_minimum_surface_margin": corrected_margin,
                    "legacy_step_average_minimum_surface_margin": legacy_margin,
                }
            )
        if not case_pass:
            print(f"Regression case failed: D={d_value:.6e}, j={j_value:g}")
    frame = pd.DataFrame(rows)
    passed = (
        bool(frame["field_pass"].all())
        and bool(frame["status_pass"].all())
        and bool(frame["boolean_gates_pass"].all())
        and bool(frame["endpoint_margin_more_conservative_pass"].all())
    )
    return frame, passed


def residualize(target: np.ndarray, predictors: np.ndarray) -> np.ndarray:
    target = np.asarray(target, dtype=float)
    predictors = np.asarray(predictors, dtype=float)
    if predictors.ndim == 1:
        predictors = predictors[:, None]
    design = np.column_stack([np.ones(len(target)), predictors])
    coefficients = np.linalg.lstsq(design, target, rcond=None)[0]
    return target - design @ coefficients


def prcc_coefficients(
    frame: pd.DataFrame,
    inputs: Sequence[str],
    output: str,
) -> dict[str, float]:
    clean = frame[list(inputs) + [output]].apply(pd.to_numeric, errors="coerce").dropna()
    if len(clean) <= len(inputs) + 3:
        return {name: math.nan for name in inputs}
    ranked_inputs = np.column_stack(
        [clean[name].rank(method="average").to_numpy(float) for name in inputs]
    )
    ranked_output = clean[output].rank(method="average").to_numpy(float)
    result: dict[str, float] = {}
    for index, name in enumerate(inputs):
        others = [column for column in range(len(inputs)) if column != index]
        if others:
            x_residual = residualize(ranked_inputs[:, index], ranked_inputs[:, others])
            y_residual = residualize(ranked_output, ranked_inputs[:, others])
        else:
            x_residual = ranked_inputs[:, index]
            y_residual = ranked_output
        coefficient = (
            float(np.corrcoef(x_residual, y_residual)[0, 1])
            if np.std(x_residual) > 0.0 and np.std(y_residual) > 0.0
            else math.nan
        )
        result[name] = coefficient
    return result


def build_prcc(frame: pd.DataFrame, seed: int) -> pd.DataFrame:
    data = frame.copy()
    target_reached = bool_series(data["target_reached"])
    right_censored = bool_series(data["area_is_right_censored"])
    data["transport_gate_numeric"] = bool_series(data["transport_gate_pass"]).astype(int)
    data["area_censoring_numeric"] = right_censored.astype(int)
    inputs = [
        "water_drag",
        "diffusive_permeability_d_c_over_l_mol_m2_s_activity",
        "total_reference_area_resistance_ohm_m2",
        "uniform_current_density_a_m2",
    ]
    outputs = [
        "required_active_area_m2",
        "required_active_area_censored_m2",
        "incremental_saving_kw_vs_passive_erv",
        "maximum_required_terminal_voltage_signed_v",
        "absolute_diffusion_fraction_of_eo",
        "area_censoring_numeric",
        "transport_gate_numeric",
    ]
    rng = np.random.default_rng(seed + 1)
    rows: list[dict[str, Any]] = []
    bootstrap_count = 200
    for output in outputs:
        population = (
            data.loc[target_reached]
            if output
            in {
                "incremental_saving_kw_vs_passive_erv",
                "required_active_area_m2",
            }
            else (
                data.loc[target_reached | right_censored]
                if output == "area_censoring_numeric"
                else data
            )
        )
        clean = (
            population[inputs + [output]]
            .apply(pd.to_numeric, errors="coerce")
            .dropna()
        )
        if output == "incremental_saving_kw_vs_passive_erv":
            interpretation = (
                "target-reached rows only; deterministic inverse-design rank "
                "sensitivity; not a probability model"
            )
            population_label = "TARGET_REACHED_ONLY"
        elif output == "required_active_area_m2":
            interpretation = (
                "observed target-reached area only; no censored coordinate; "
                "deterministic inverse-design rank sensitivity"
            )
            population_label = "TARGET_REACHED_OBSERVED_AREA_ONLY"
        elif output == "required_active_area_censored_m2":
            interpretation = (
                "target-reached plus 24 000 m2 right-censored capped coordinate; "
                "solver failures omitted; deterministic inverse-design rank sensitivity"
            )
            population_label = "TARGET_REACHED_OR_RIGHT_CENSORED_CAPPED_COORDINATE"
        elif output == "area_censoring_numeric":
            interpretation = (
                "censoring indicator among target-reached or right-censored rows; "
                "rank association, not a continuous-response probability model"
            )
            population_label = "REACHED_OR_CENSORED_CENSOR_ASSOCIATION"
        elif output == "transport_gate_numeric":
            interpretation = (
                "all-case feasibility indicator; deterministic inverse-design rank "
                "association; not a continuous-response probability model"
            )
            population_label = "ALL_CASE_FEASIBILITY"
        else:
            interpretation = (
                "deterministic inverse-design rank sensitivity; not a probability model"
            )
            population_label = "FINITE_OUTPUT_ROWS"
        point = prcc_coefficients(clean, inputs, output)
        samples: dict[str, list[float]] = {name: [] for name in inputs}
        if len(clean) > len(inputs) + 3:
            for _ in range(bootstrap_count):
                indices = rng.integers(0, len(clean), len(clean))
                sampled = clean.iloc[indices]
                coefficients = prcc_coefficients(sampled, inputs, output)
                for name, value in coefficients.items():
                    if math.isfinite(value):
                        samples[name].append(value)
        for name in inputs:
            distribution = np.asarray(samples[name], dtype=float)
            rows.append(
                {
                    "parameter": name,
                    "output": output,
                    "prcc": point[name],
                    "absolute_prcc": abs(point[name]) if math.isfinite(point[name]) else math.nan,
                    "bootstrap_count": bootstrap_count,
                    "prcc_ci025": (
                        float(np.quantile(distribution, 0.025))
                        if len(distribution)
                        else math.nan
                    ),
                    "prcc_ci975": (
                        float(np.quantile(distribution, 0.975))
                        if len(distribution)
                        else math.nan
                    ),
                    "complete_case_count": len(clean),
                    "analysis_population": population_label,
                    "interpretation": interpretation,
                }
            )
    return pd.DataFrame(rows)


def input_rank_correlation(frame: pd.DataFrame) -> pd.DataFrame:
    inputs = [
        "water_drag",
        "diffusive_permeability_d_c_over_l_mol_m2_s_activity",
        "total_reference_area_resistance_ohm_m2",
        "uniform_current_density_a_m2",
    ]
    correlation = frame[inputs].rank(method="average").corr()
    return correlation.rename_axis("parameter").reset_index()


def pareto_mask(frame: pd.DataFrame) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype=bool, index=frame.index)
    # Minimize observed area, add-on power and maximum voltage; maximize saving.
    values = frame[
        [
            "required_active_area_censored_m2",
            "incremental_eo_and_fan_power_kw",
            "maximum_required_terminal_voltage_signed_v",
            "incremental_saving_kw_vs_passive_erv",
        ]
    ].to_numpy(float)
    keep = np.ones(len(frame), dtype=bool)
    for index in range(len(frame)):
        for challenger in range(len(frame)):
            if challenger == index:
                continue
            no_worse = bool(
                np.all(values[challenger, :3] <= values[index, :3] + 1.0e-12)
                and values[challenger, 3] >= values[index, 3] - 1.0e-12
            )
            strictly_better = bool(
                np.any(values[challenger, :3] < values[index, :3] - 1.0e-12)
                or values[challenger, 3] > values[index, 3] + 1.0e-12
            )
            if no_worse and strictly_better:
                keep[index] = False
                break
    return pd.Series(keep, index=frame.index)


def build_pareto(frame: pd.DataFrame) -> pd.DataFrame:
    valid = frame[bool_series(frame["conditional_energy_pass"])].copy()
    valid = valid[~bool_series(valid["area_is_right_censored"])].copy()
    required = [
        "required_active_area_censored_m2",
        "incremental_eo_and_fan_power_kw",
        "maximum_required_terminal_voltage_signed_v",
        "incremental_saving_kw_vs_passive_erv",
    ]
    valid = valid.dropna(subset=required)
    valid["pareto_nondominated"] = pareto_mask(valid)
    return valid[valid["pareto_nondominated"]].sort_values(
        ["incremental_saving_kw_vs_passive_erv", "required_active_area_censored_m2"],
        ascending=[False, True],
    )


def dense_summaries(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    best_rows: list[dict[str, Any]] = []
    for diffusivity, group in frame.groupby("water_diffusivity_m2_s", sort=True):
        passing = group[bool_series(group["conditional_energy_pass"])].copy()
        observed = passing[~bool_series(passing["area_is_right_censored"])].copy()
        if observed.empty:
            best_rows.append(
                {
                    "water_diffusivity_m2_s": diffusivity,
                    "conditional_positive_current_exists": False,
                    "best_current_density_a_m2": math.nan,
                    "best_screening_saving_kw": math.nan,
                    "best_required_area_m2": math.nan,
                }
            )
            continue
        best = observed.sort_values(
            ["incremental_saving_kw_vs_passive_erv", "required_active_area_censored_m2"],
            ascending=[False, True],
        ).iloc[0]
        best_rows.append(
            {
                "water_diffusivity_m2_s": diffusivity,
                "conditional_positive_current_exists": True,
                "best_current_density_a_m2": best["uniform_current_density_a_m2"],
                "best_screening_saving_kw": best["incremental_saving_kw_vs_passive_erv"],
                "best_screening_saving_pct": best["incremental_saving_pct_vs_passive_erv"],
                "best_required_area_m2": best["required_active_area_censored_m2"],
                "best_maximum_voltage_v": best["maximum_required_terminal_voltage_signed_v"],
                "best_absolute_diffusion_fraction_of_eo": best[
                    "absolute_diffusion_fraction_of_eo"
                ],
                "full_system_status": "UNKNOWN",
            }
        )
    threshold_rows: list[dict[str, Any]] = []
    for current, group in frame.groupby("uniform_current_density_a_m2", sort=True):
        passing = group[bool_series(group["conditional_energy_pass"])].copy()
        censored = group[bool_series(group["area_is_right_censored"])].copy()
        threshold_rows.append(
            {
                "uniform_current_density_a_m2": current,
                "highest_tested_diffusivity_conditional_positive_m2_s": (
                    passing["water_diffusivity_m2_s"].max()
                    if not passing.empty
                    else math.nan
                ),
                "lowest_tested_diffusivity_area_censored_m2_s": (
                    censored["water_diffusivity_m2_s"].min()
                    if not censored.empty
                    else math.nan
                ),
                "conditional_positive_count": len(passing),
                "area_censored_count": len(censored),
                "current_density_is_sampling_or_control_axis": True,
                "engineering_current_density_limit_a_m2": None,
            }
        )
    return pd.DataFrame(best_rows), pd.DataFrame(threshold_rows)


def detailed_hvac_validation(
    dense: pd.DataFrame,
    detailed_path: Path,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if not detailed_path.is_file():
        return pd.DataFrame(), {
            "availability": "NOT_AVAILABLE",
            "selected_point_count": 0,
            "validation_pass": None,
        }
    detailed = pd.read_csv(detailed_path)
    if "scenario_id" in detailed:
        detailed = detailed[detailed["scenario_id"].eq("isothermal_counterfactual")]
    rows: list[dict[str, Any]] = []
    for _, reference in detailed.iterrows():
        diffusivity = float(reference["water_diffusivity_m2_s"])
        current = float(reference["uniform_current_density_a_m2"])
        match = dense[
            np.isclose(
                dense["water_diffusivity_m2_s"].astype(float),
                diffusivity,
                rtol=1.0e-12,
                atol=1.0e-30,
            )
            & np.isclose(
                dense["uniform_current_density_a_m2"].astype(float),
                current,
                rtol=1.0e-12,
                atol=1.0e-12,
            )
        ]
        if len(match) != 1:
            continue
        actual = match.iloc[0]
        area_error = abs(
            finite(actual["solver_observed_area_m2"])
            - finite(reference["required_active_area_m2"])
        )
        screening_error = abs(
            finite(actual["incremental_saving_kw_vs_passive_erv"])
            - finite(reference["screening_incremental_saving_kw"])
        )
        addon_error = abs(
            finite(actual["incremental_eo_and_fan_power_kw"])
            - finite(reference["addon_electric_power_kw"])
        )
        validation_pass = bool(
            area_error <= 1.0e-5
            and screening_error <= 1.0e-6
            and addon_error <= 1.0e-6
        )
        rows.append(
            {
                "water_diffusivity_m2_s": diffusivity,
                "uniform_current_density_a_m2": current,
                "screening_saving_kw_this_study": actual[
                    "incremental_saving_kw_vs_passive_erv"
                ],
                "screening_saving_kw_detailed_source": reference[
                    "screening_incremental_saving_kw"
                ],
                "detailed_isothermal_saving_kw": reference[
                    "detailed_incremental_saving_kw"
                ],
                "detailed_isothermal_saving_pct": reference[
                    "detailed_incremental_saving_pct"
                ],
                "screening_to_detailed_delta_kw": (
                    finite(reference["detailed_incremental_saving_kw"])
                    - finite(actual["incremental_saving_kw_vs_passive_erv"])
                ),
                "area_absolute_error_m2": area_error,
                "screening_saving_absolute_error_kw": screening_error,
                "addon_power_absolute_error_kw": addon_error,
                "validation_pass": validation_pass,
                "detailed_hvac_boundary": "60-segment coil and explicit R1234ze(E) cycle",
                "full_system_status": "UNKNOWN",
            }
        )
    output = pd.DataFrame(rows)
    status = {
        "availability": "AVAILABLE" if len(output) else "AVAILABLE_NO_GRID_MATCH",
        "selected_point_count": len(output),
        "validation_pass": bool(output["validation_pass"].all()) if len(output) else None,
        "source_path": str(detailed_path),
        "source_sha256": sha256_file(detailed_path),
    }
    return output, status


def centers_to_edges(values: Sequence[float], logarithmic: bool = False) -> np.ndarray:
    centers = np.asarray(values, dtype=float)
    transformed = np.log10(centers) if logarithmic else centers
    midpoints = 0.5 * (transformed[:-1] + transformed[1:])
    edges = np.empty(len(centers) + 1, dtype=float)
    edges[1:-1] = midpoints
    edges[0] = transformed[0] - (midpoints[0] - transformed[0])
    edges[-1] = transformed[-1] + (transformed[-1] - midpoints[-1])
    return np.power(10.0, edges) if logarithmic else edges


def pivot_dense(frame: pd.DataFrame, field: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    pivot = frame.pivot(
        index="water_diffusivity_m2_s",
        columns="uniform_current_density_a_m2",
        values=field,
    ).sort_index().sort_index(axis=1)
    return (
        pivot.columns.to_numpy(float),
        pivot.index.to_numpy(float),
        pivot.to_numpy(float),
    )


def save_figure(fig: plt.Figure, directory: Path, stem: str) -> None:
    fig.savefig(directory / f"{stem}.png", dpi=220, bbox_inches="tight")
    fig.savefig(directory / f"{stem}.pdf", bbox_inches="tight")
    plt.close(fig)


def plot_dense_regions(frame: pd.DataFrame, figures: Path) -> None:
    figures.mkdir(parents=True, exist_ok=True)
    x, y, saving = pivot_dense(frame, "target_reached_screening_saving_pct")
    _, _, target_values = pivot_dense(
        frame.assign(_target=bool_series(frame["target_reached"]).astype(int)),
        "_target",
    )
    saving = np.where(target_values > 0.5, saving, np.nan)
    _, _, pass_values = pivot_dense(
        frame.assign(_pass=bool_series(frame["conditional_energy_pass"]).astype(int)),
        "_pass",
    )
    _, _, censored = pivot_dense(
        frame.assign(_censored=bool_series(frame["area_is_right_censored"]).astype(int)),
        "_censored",
    )
    x_edges = centers_to_edges(x)
    y_edges = centers_to_edges(y, logarithmic=True)
    x_mesh, y_mesh = np.meshgrid(x, y)

    finite_saving = saving[np.isfinite(saving)]
    if not len(finite_saving):
        raise StudyError("Dense saving plot has no TARGET_REACHED response cells")
    limit = max(10.0, float(np.nanpercentile(np.abs(finite_saving), 98)))
    norm = mcolors.TwoSlopeNorm(vmin=-limit, vcenter=0.0, vmax=limit)
    saving_cmap = plt.get_cmap("RdYlGn").copy()
    saving_cmap.set_bad("#e5e7eb")
    fig, ax = plt.subplots(figsize=(10.8, 7.2))
    image = ax.pcolormesh(
        x_edges,
        y_edges,
        saving,
        cmap=saving_cmap,
        norm=norm,
        shading="flat",
    )
    if np.nanmin(pass_values) < 0.5 < np.nanmax(pass_values):
        ax.contour(x_mesh, y_mesh, pass_values, levels=[0.5], colors="black", linewidths=1.8)
    censored_y, censored_x = np.where(censored > 0.5)
    if len(censored_x):
        ax.scatter(
            x[censored_x],
            y[censored_y],
            marker="x",
            s=20,
            linewidths=0.7,
            color="#4b5563",
            label="Area right-censored at 24 000 m²",
        )
    ax.set_yscale("log")
    ax.set_xlabel("Uniform current density [A/m²] (sampling/control axis; no 21 A/m² limit)")
    ax.set_ylabel("Water diffusivity prefactor D [m²/s]")
    ax.set_title("Post-ERV 10% EO polishing: screening saving where target is reached")
    colorbar = fig.colorbar(image, ax=ax)
    colorbar.set_label("Incremental saving vs passive ERV + AC | target reached [%]")
    ax.text(
        0.01,
        0.01,
        "Black contour: target + transport + positive screening-energy gate.\n"
        "Grey cells did not reach target; crosses are right-censored.\n"
        "Full-system status is UNKNOWN; receiver/sink and module closure are absent.",
        transform=ax.transAxes,
        va="bottom",
        ha="left",
        fontsize=8,
        bbox={"facecolor": "white", "alpha": 0.82, "edgecolor": "0.7"},
    )
    if len(censored_x):
        ax.legend(loc="upper right", fontsize=8)
    ax.grid(True, which="both", alpha=0.18)
    save_figure(fig, figures, "01_dense_dj_conditional_saving")

    x, y, observed_area = pivot_dense(frame, "required_active_area_censored_m2")
    fig, ax = plt.subplots(figsize=(10.8, 7.2))
    image = ax.pcolormesh(
        x_edges,
        y_edges,
        np.log10(np.maximum(observed_area, 1.0)),
        cmap="viridis",
        shading="flat",
    )
    if np.nanmin(pass_values) < 0.5 < np.nanmax(pass_values):
        ax.contour(x_mesh, y_mesh, pass_values, levels=[0.5], colors="white", linewidths=1.5)
    if len(censored_x):
        ax.scatter(
            x[censored_x],
            y[censored_y],
            marker="x",
            s=20,
            linewidths=0.7,
            color="white",
        )
    ax.set_yscale("log")
    ax.set_xlabel("Uniform current density [A/m²]")
    ax.set_ylabel("Water diffusivity prefactor D [m²/s]")
    ax.set_title("Observed membrane area; crosses are right-censored, not 24 000 m² estimates")
    ticks = [2, 2.5, 3, 3.5, 4, math.log10(24000.0)]
    colorbar = fig.colorbar(image, ax=ax, ticks=ticks)
    colorbar.ax.set_yticklabels([f"{10**tick:,.0f}" for tick in ticks])
    colorbar.set_label("Observed / censored active area [m²]")
    ax.grid(True, which="both", alpha=0.18)
    save_figure(fig, figures, "02_dense_dj_area_censoring")

    status = np.zeros_like(pass_values)
    status[censored > 0.5] = 1.0
    status[pass_values > 0.5] = 2.0
    cmap = mcolors.ListedColormap(["#dc2626", "#9ca3af", "#059669"])
    norm_status = mcolors.BoundaryNorm([-0.5, 0.5, 1.5, 2.5], cmap.N)
    fig, ax = plt.subplots(figsize=(10.8, 7.2))
    image = ax.pcolormesh(
        x_edges,
        y_edges,
        status,
        cmap=cmap,
        norm=norm_status,
        shading="flat",
    )
    ax.set_yscale("log")
    ax.set_xlabel("Uniform current density [A/m²]")
    ax.set_ylabel("Water diffusivity prefactor D [m²/s]")
    ax.set_title("Separate calculation status: fail, right-censored, conditional positive")
    colorbar = fig.colorbar(image, ax=ax, ticks=[0, 1, 2])
    colorbar.ax.set_yticklabels(
        ["Transport/energy fail", "Area censored", "Conditional positive"]
    )
    ax.text(
        0.01,
        0.01,
        "No cell is a full-system pass. Full-system status = UNKNOWN.",
        transform=ax.transAxes,
        fontsize=9,
        bbox={"facecolor": "white", "alpha": 0.85, "edgecolor": "0.7"},
    )
    save_figure(fig, figures, "03_dense_dj_status")

    x, y, voltage = pivot_dense(frame, "maximum_required_terminal_voltage_signed_v")
    _, _, backdiffusion = pivot_dense(frame, "absolute_diffusion_fraction_of_eo")
    fig, axes = plt.subplots(1, 2, figsize=(13.2, 5.6), sharey=True)
    voltage_image = axes[0].pcolormesh(
        x_edges,
        y_edges,
        voltage,
        cmap="magma",
        shading="flat",
    )
    axes[0].set_yscale("log")
    axes[0].set_xlabel("Current density [A/m²]")
    axes[0].set_ylabel("Water diffusivity D [m²/s]")
    axes[0].set_title("Maximum signed terminal voltage [V]")
    fig.colorbar(voltage_image, ax=axes[0])
    diffusion_image = axes[1].pcolormesh(
        x_edges,
        y_edges,
        backdiffusion,
        cmap="cividis",
        vmin=0.0,
        vmax=min(1.0, float(np.nanpercentile(backdiffusion, 99))),
        shading="flat",
    )
    axes[1].set_yscale("log")
    axes[1].set_xlabel("Current density [A/m²]")
    axes[1].set_title("Opposing |diffusion| / |EO| [-]")
    fig.colorbar(diffusion_image, ax=axes[1])
    for axis in axes:
        axis.grid(True, which="both", alpha=0.15)
    fig.suptitle("Why the D–j region changes")
    save_figure(fig, figures, "04_dense_dj_voltage_and_backdiffusion")


def plot_global_results(
    frame: pd.DataFrame,
    prcc: pd.DataFrame,
    figures: Path,
) -> None:
    labels = {
        "water_drag": "Water drag",
        "diffusive_permeability_d_c_over_l_mol_m2_s_activity": "D·C/L",
        "total_reference_area_resistance_ohm_m2": "L/σ + series ASR",
        "uniform_current_density_a_m2": "Current density",
    }
    outputs = [
        (
            "incremental_saving_kw_vs_passive_erv",
            "Screening saving | target reached [kW]",
        ),
        (
            "required_active_area_m2",
            "Observed area | target reached [m²]",
        ),
        (
            "required_active_area_censored_m2",
            "Capped area coordinate | reached + censored [m²]",
        ),
        ("area_censoring_numeric", "Censor association | reached or censored"),
        ("transport_gate_numeric", "Feasibility association | all cases"),
    ]
    fig, axes_grid = plt.subplots(2, 3, figsize=(15.2, 9.0), sharey=True)
    axes = list(axes_grid.flat)
    for axis, (output, title) in zip(axes, outputs):
        group = prcc[prcc["output"].eq(output)].copy()
        group["label"] = group["parameter"].map(labels)
        group = group.sort_values("prcc")
        errors = np.vstack(
            [
                group["prcc"] - group["prcc_ci025"],
                group["prcc_ci975"] - group["prcc"],
            ]
        )
        axis.barh(group["label"], group["prcc"], xerr=errors, color="#2563eb", alpha=0.86)
        axis.axvline(0.0, color="black", linewidth=0.8)
        axis.set_xlim(-1.0, 1.0)
        axis.set_title(title)
        axis.grid(True, axis="x", alpha=0.25)
    axes[0].set_ylabel("Independent inverse-design coordinate")
    axes[3].set_ylabel("Independent inverse-design coordinate")
    axes[-1].axis("off")
    axes[-1].text(
        0.02,
        0.92,
        "Populations are intentionally separate:\n"
        "• saving/observed area: target reached\n"
        "• capped coordinate/censor: reached or censored\n"
        "• feasibility: all 512 cases",
        transform=axes[-1].transAxes,
        va="top",
        fontsize=10,
    )
    fig.suptitle(
        "Deterministic LHS/PRCC by stated analysis population "
        "(95% bootstrap interval)"
    )
    save_figure(fig, figures, "05_global_prcc")

    target = bool_series(frame["target_reached"])
    passing = bool_series(frame["conditional_energy_pass"])
    censored = bool_series(frame["area_is_right_censored"])
    target_frame = frame.loc[target]
    target_saving = pd.to_numeric(
        target_frame["incremental_saving_kw_vs_passive_erv"], errors="coerce"
    )
    fig, axes = plt.subplots(1, 2, figsize=(13.0, 5.8))
    axes[0].scatter(
        frame.loc[~target, "diffusive_permeability_d_c_over_l_mol_m2_s_activity"],
        frame.loc[~target, "water_drag"],
        marker="x",
        color="#9ca3af",
        s=15,
        linewidths=0.7,
        label="Not target reached",
    )
    scatter = axes[0].scatter(
        target_frame["diffusive_permeability_d_c_over_l_mol_m2_s_activity"],
        target_frame["water_drag"],
        c=target_saving,
        cmap="RdYlGn",
        norm=mcolors.TwoSlopeNorm(
            vmin=min(-1.0, float(target_saving.min())),
            vcenter=0.0,
            vmax=max(1.0, float(target_saving.max())),
        ),
        s=np.where(passing.loc[target], 30.0, 16.0),
        alpha=0.78,
        linewidths=0.0,
    )
    axes[0].scatter(
        frame.loc[censored, "diffusive_permeability_d_c_over_l_mol_m2_s_activity"],
        frame.loc[censored, "water_drag"],
        marker="x",
        color="#374151",
        s=24,
        linewidths=0.9,
        label="24 000 m² right-censored",
    )
    axes[0].set_xscale("log")
    axes[0].set_yscale("log")
    axes[0].set_xlabel("Diffusive permeability D·C/L [mol m⁻² s⁻¹ activity⁻¹]")
    axes[0].set_ylabel("Water drag [-]")
    axes[0].set_title("Transport coordinates")
    axes[0].legend(loc="best", fontsize=7)
    fig.colorbar(scatter, ax=axes[0], label="Screening saving | target reached [kW]")

    axes[1].scatter(
        frame.loc[~target, "total_reference_area_resistance_ohm_m2"],
        frame.loc[~target, "uniform_current_density_a_m2"],
        marker="x",
        color="#9ca3af",
        s=15,
        linewidths=0.7,
    )
    scatter2 = axes[1].scatter(
        target_frame["total_reference_area_resistance_ohm_m2"],
        target_frame["uniform_current_density_a_m2"],
        c=target_frame["maximum_required_terminal_voltage_signed_v"],
        cmap="magma",
        s=np.where(passing.loc[target], 30.0, 16.0),
        alpha=0.78,
        linewidths=0.0,
    )
    axes[1].set_xscale("log")
    axes[1].set_xlabel("Total reference area resistance L/σ + ASR [Ω m²]")
    axes[1].set_ylabel("Current density [A/m²]")
    axes[1].set_title("Electrical coordinates")
    fig.colorbar(scatter2, ax=axes[1], label="Maximum signed voltage [V]")
    for axis in axes:
        axis.grid(True, which="both", alpha=0.2)
    fig.suptitle(
        "Post-ERV inverse-design sample; failed rows are not plotted as energy responses"
    )
    save_figure(fig, figures, "06_global_inverse_design_coordinates")


def study_summary(
    dense: pd.DataFrame,
    global_frame: pd.DataFrame,
    prcc: pd.DataFrame,
    pareto: pd.DataFrame,
    detailed_status: Mapping[str, Any],
) -> tuple[str, dict[str, Any]]:
    dense_area_defined = pd.to_numeric(
        dense["required_active_area_censored_m2"], errors="coerce"
    ).notna()
    global_area_defined = pd.to_numeric(
        global_frame["required_active_area_censored_m2"], errors="coerce"
    ).notna()
    global_target_count = int(bool_series(global_frame["target_reached"]).sum())
    dense_pass = dense[bool_series(dense["conditional_energy_pass"])].copy()
    dense_observed = dense_pass[~bool_series(dense_pass["area_is_right_censored"])].copy()
    global_pass = global_frame[bool_series(global_frame["conditional_energy_pass"])].copy()
    global_observed = global_pass[
        ~bool_series(global_pass["area_is_right_censored"])
    ].copy()
    best_dense = (
        dense_observed.sort_values(
            ["incremental_saving_kw_vs_passive_erv", "required_active_area_censored_m2"],
            ascending=[False, True],
        ).iloc[0]
        if not dense_observed.empty
        else None
    )
    best_global = (
        global_observed.sort_values(
            ["incremental_saving_kw_vs_passive_erv", "required_active_area_censored_m2"],
            ascending=[False, True],
        ).iloc[0]
        if not global_observed.empty
        else None
    )
    top_saving_prcc = prcc[prcc["output"].eq("incremental_saving_kw_vs_passive_erv")].copy()
    top_saving_prcc = top_saving_prcc.sort_values("absolute_prcc", ascending=False)
    top_observed_area_prcc = prcc[
        prcc["output"].eq("required_active_area_m2")
    ].copy()
    top_observed_area_prcc = top_observed_area_prcc.sort_values(
        "absolute_prcc", ascending=False
    )
    top_capped_area_prcc = prcc[
        prcc["output"].eq("required_active_area_censored_m2")
    ].copy()
    top_capped_area_prcc = top_capped_area_prcc.sort_values(
        "absolute_prcc", ascending=False
    )
    sensitivity_labels = {
        "water_drag": "Water drag",
        "diffusive_permeability_d_c_over_l_mol_m2_s_activity": "D·C/L",
        "total_reference_area_resistance_ohm_m2": "L/σ + series ASR",
        "uniform_current_density_a_m2": "Current density",
    }

    def sensitivity_lines(output: str) -> list[str]:
        subset = prcc[prcc["output"].eq(output)].sort_values(
            "absolute_prcc", ascending=False
        )
        return [
            (
                f"- {sensitivity_labels.get(str(row['parameter']), str(row['parameter']))}: "
                f"PRCC `{float(row['prcc']):+.3f}` "
                f"(95 % bootstrap `{float(row['prcc_ci025']):+.3f}` to "
                f"`{float(row['prcc_ci975']):+.3f}`, n = "
                f"{int(row['complete_case_count'])})."
            )
            for _, row in subset.iterrows()
        ]

    payload = {
        "script_version": SCRIPT_VERSION,
        "dense_case_count": len(dense),
        "dense_conditional_positive_count": len(dense_pass),
        "dense_area_right_censored_count": int(
            bool_series(dense["area_is_right_censored"]).sum()
        ),
        "dense_area_coordinate_defined_count": int(dense_area_defined.sum()),
        "dense_unobserved_area_omitted_count": int((~dense_area_defined).sum()),
        "dense_positive_surface_direction_count": int(
            bool_series(dense["positive_surface_direction_everywhere"]).sum()
        ),
        "global_case_count": len(global_frame),
        "global_target_reached_count": global_target_count,
        "global_conditional_positive_count": len(global_pass),
        "global_area_right_censored_count": int(
            bool_series(global_frame["area_is_right_censored"]).sum()
        ),
        "global_area_coordinate_defined_count": int(global_area_defined.sum()),
        "global_unobserved_area_omitted_count": int((~global_area_defined).sum()),
        "global_positive_surface_direction_count": int(
            bool_series(global_frame["positive_surface_direction_everywhere"]).sum()
        ),
        "global_pareto_count": len(pareto),
        "best_dense": json_safe(best_dense.to_dict()) if best_dense is not None else None,
        "best_global": json_safe(best_global.to_dict()) if best_global is not None else None,
        "strongest_saving_prcc": (
            json_safe(top_saving_prcc.iloc[0].to_dict())
            if not top_saving_prcc.empty
            else None
        ),
        "strongest_observed_area_prcc": (
            json_safe(top_observed_area_prcc.iloc[0].to_dict())
            if not top_observed_area_prcc.empty
            else None
        ),
        "strongest_capped_area_coordinate_prcc": (
            json_safe(top_capped_area_prcc.iloc[0].to_dict())
            if not top_capped_area_prcc.empty
            else None
        ),
        "detailed_hvac_validation": dict(detailed_status),
        "full_system_status": "UNKNOWN",
        "full_system_claim_allowed": False,
        "current_density_limit_a_m2": None,
    }

    lines = [
        "# Post-ERV membrane and operating inverse-design study v1",
        "",
        "## What was calculated",
        "",
        f"- Dense D–j map: **{len(dense)}** cases.",
        f"- Deterministic global LHS: **{len(global_frame)}** cases.",
        "- Main boundary: passive ERV outlet → finite-film, isothermal EO polishing → remaining screening AC.",
        "- Current density is a sampling/control coordinate; **no 21 A/m² limit** is applied.",
        "- Area values at 24 000 m² are right-censored lower bounds, not required-area estimates.",
        "- Negative signed voltage receives no recovered-grid-power credit.",
        "",
        "## Main calculation counts",
        "",
        f"- Dense conditional-positive rows: **{len(dense_pass)}/{len(dense)}**.",
        f"- Dense right-censored rows: **{int(bool_series(dense['area_is_right_censored']).sum())}**.",
        f"- Dense failed/unobserved rows omitted from area statistics: **{int((~dense_area_defined).sum())}**.",
        f"- Global conditional-positive rows: **{len(global_pass)}/{len(global_frame)}**.",
        f"- Global failed/unobserved rows omitted from area statistics: **{int((~global_area_defined).sum())}**.",
        f"- Saving PRCC population (TARGET_REACHED only): **{global_target_count}**.",
        f"- Observed-area PRCC population (TARGET_REACHED only): **{global_target_count}**.",
        f"- Capped-area/censor association population (target reached + right-censored): **{int(global_area_defined.sum())}**.",
        f"- Feasibility rank-association population (all cases): **{len(global_frame)}**.",
        f"- Global non-dominated conditional rows: **{len(pareto)}**.",
        f"- Positive surface-direction rows in dense map: **{int(bool_series(dense['positive_surface_direction_everywhere']).sum())}**.",
        "",
        "## Global PRCC sensitivity",
        "",
        "Saving among TARGET_REACHED rows (negative means that increasing the coordinate reduces conditional screening saving):",
        "",
        *sensitivity_lines("incremental_saving_kw_vs_passive_erv"),
        "",
        "Observed area among TARGET_REACHED rows (positive means larger observed area):",
        "",
        *sensitivity_lines("required_active_area_m2"),
        "",
        "Capped area coordinate among target-reached plus 24 000 m² right-censored rows (positive means larger capped coordinate):",
        "",
        *sensitivity_lines("required_active_area_censored_m2"),
        "",
        "These are deterministic inverse-design rank sensitivities over the registered ranges, not uncertainty probabilities or independent raw-material effects.",
        "",
        "## Best conditional points",
        "",
    ]
    if best_dense is not None:
        lines.extend(
            [
                "Dense D–j slice at the Terminal-1 anchor:",
                "",
                f"- D = `{float(best_dense['water_diffusivity_m2_s']):.6e} m²/s`.",
                f"- j = `{float(best_dense['uniform_current_density_a_m2']):.3f} A/m²`.",
                f"- Screening saving = `{float(best_dense['incremental_saving_kw_vs_passive_erv']):.3f} kW` / `{float(best_dense['incremental_saving_pct_vs_passive_erv']):.3f} %`.",
                f"- Observed required area = `{float(best_dense['required_active_area_censored_m2']):.3f} m²`.",
                "",
            ]
        )
    if best_global is not None:
        lines.extend(
            [
                "Global inverse-design sample:",
                "",
                f"- Drag = `{float(best_global['water_drag']):.3f}`.",
                f"- D·C/L = `{float(best_global['diffusive_permeability_d_c_over_l_mol_m2_s_activity']):.6e}`.",
                f"- Total L/σ + ASR = `{float(best_global['total_reference_area_resistance_ohm_m2']):.6e} Ω m²`.",
                f"- j = `{float(best_global['uniform_current_density_a_m2']):.3f} A/m²`.",
                f"- Screening saving = `{float(best_global['incremental_saving_kw_vs_passive_erv']):.3f} kW`.",
                f"- Observed required area = `{float(best_global['required_active_area_censored_m2']):.3f} m²`.",
                "",
            ]
        )
    lines.extend(
        [
            "## Interpretation boundary",
            "",
            "The global coordinates are independently sampled inverse-design requirements, not a probability distribution of purchasable materials. Under the power-law model, diffusion is primarily identified through D·C/L and electrical resistance through L/σ plus series ASR. Raw D, capacity and thickness should therefore not be interpreted as independently identified effects when those composites are unchanged.",
            "",
            "Solver failures retain their raw integration progress only in `solver_observed_area_m2`; they are NaN—not zero—in the required-area coordinates. Saving and observed-area PRCC use TARGET_REACHED rows only. The capped-area and censor panels use target-reached plus right-censored rows, while the separate feasibility panel uses all cases.",
            "",
            "The dense grid uses the screening HVAC model because it is computationally suitable for the full map. Selected matching points are checked against the available 60-segment/R1234ze(E) detailed-HVAC output. This validation does not supply missing receiver/sink energy, conjugate thermal coupling, packaging, electrodes, lifetime or manufacturing evidence.",
            "",
            "**Full-system status is UNKNOWN for every row. Conditional saving is not a system-saving claim.**",
            "",
        ]
    )
    return "\n".join(lines), payload


def run_self_test() -> None:
    values = anchored_grid(1.0e-15, 3.0e-9, 33, [1.0e-12, 1.0e-10, 1.0e-9], logarithmic=True)
    assert len(values) == 33
    for anchor in (1.0e-12, 1.0e-10, 1.0e-9):
        assert np.any(np.isclose(values, anchor, rtol=1.0e-12, atol=1.0e-30))
    ranges = {
        "a": (1.0, 10.0, "loguniform"),
        "b": (2.0, 5.0, "uniform"),
        "c": (1.0e-6, 1.0e-2, "loguniform"),
        "d": (3.0, 30.0, "uniform"),
    }
    first = latin_hypercube(ranges, 32, 123)
    second = latin_hypercube(ranges, 32, 123)
    assert first.equals(second)
    assert first.nunique().eq(32).all()
    dummy = pd.DataFrame(
        {
            "required_active_area_censored_m2": [10.0, 12.0, 8.0],
            "incremental_eo_and_fan_power_kw": [2.0, 3.0, 4.0],
            "maximum_required_terminal_voltage_signed_v": [1.0, 1.2, 1.4],
            "incremental_saving_kw_vs_passive_erv": [20.0, 18.0, 22.0],
        }
    )
    assert pareto_mask(dummy).tolist() == [True, False, True]
    area_dummy = pd.DataFrame(
        {
            "target_reached": [True, False, False],
            "area_is_right_censored": [False, True, False],
            "solver_observed_area_m2": [120.0, 24000.0, 0.0],
            "solver_script_version": [SCRIPT_VERSION] * 3,
        }
    )
    normalized = normalize_area_observations(area_dummy)
    assert normalized["required_active_area_censored_m2"].iloc[:2].tolist() == [
        120.0,
        24000.0,
    ]
    assert math.isnan(normalized["required_active_area_censored_m2"].iloc[2])
    assert normalized["area_observation_status"].iloc[2] == "NOT_OBSERVED"
    print("Self-test passed: anchored grids, deterministic LHS and Pareto logic are consistent.")


def canonical_json_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_existing_result_set(
    output: Path,
    runtime: Mapping[str, Any],
    config: Mapping[str, Any],
    regression: pd.DataFrame,
    dense: pd.DataFrame,
    global_frame: pd.DataFrame,
) -> dict[str, Any]:
    """Validate a complete released result set before any postprocess mutation."""

    audit_path = output / "audit.json"
    config_used_path = output / "config_used.json"
    if not audit_path.is_file() or not config_used_path.is_file():
        raise StudyError("Postprocess requires existing audit.json and config_used.json")
    prior = read_json(audit_path)
    config_used = read_json(config_used_path)
    if prior.get("pass") is not True:
        raise StudyError("Refusing to migrate a result set whose prior audit did not pass")
    if prior.get("study_id") != config.get("study_id"):
        raise StudyError("Existing result study_id does not match the selected manifest")
    if config_used != dict(config):
        raise StudyError("Existing config_used.json does not equal the selected manifest")
    central_hash = sha256_file(Path(runtime["paths"].central_manifest))
    if prior.get("central_manifest_sha256") != central_hash:
        raise StudyError("Existing result was not generated from the selected manifest hash")
    config_used_hash = sha256_file(config_used_path)
    recorded_config_used_hash = prior.get("config_used_sha256")
    if recorded_config_used_hash is not None and recorded_config_used_hash != config_used_hash:
        raise StudyError("Existing config_used.json hash does not match its prior audit")
    if prior.get("archive_sha256") != runtime["archive_sha256"]:
        raise StudyError("Existing archive source hash does not match the selected runtime")
    prior_source_hashes = prior.get("source_sha256")
    if prior_source_hashes != runtime["source_hashes"]:
        raise StudyError("Existing model-source hashes do not match the selected runtime")
    detailed = prior.get("detailed_hvac_validation", {})
    selected_detailed_hash = sha256_file(Path(runtime["paths"].detailed_cases))
    if (
        detailed.get("source_path") != str(Path(runtime["paths"].detailed_cases))
        or detailed.get("source_sha256") != selected_detailed_hash
    ):
        raise StudyError("Existing detailed-HVAC source path/hash does not match selection")

    def solver_versions(frame: pd.DataFrame, label: str) -> set[str]:
        column = (
            "solver_script_version"
            if "solver_script_version" in frame.columns
            else "script_version"
        )
        if column not in frame.columns:
            raise StudyError(f"{label} rows have no solver/script version")
        versions = set(frame[column].dropna().astype(str).unique())
        if not versions or not versions.issubset(KNOWN_SOLVER_SCRIPT_VERSIONS):
            raise StudyError(f"Unsupported {label} solver version(s): {sorted(versions)}")
        return versions

    versions = {
        "regression": sorted(solver_versions(regression, "regression")),
        "dense": sorted(solver_versions(dense, "dense")),
        "global": sorted(solver_versions(global_frame, "global")),
    }
    expected_regression = pd.DataFrame(build_regression_cases(runtime))
    expected_dense_cases, expected_d, expected_j = build_dense_cases(runtime)
    expected_dense = pd.DataFrame(expected_dense_cases)
    expected_global_cases, expected_bounds = build_global_cases(runtime)
    expected_global = pd.DataFrame(expected_global_cases)

    def require_case_ids(
        actual: pd.DataFrame, expected: pd.DataFrame, label: str
    ) -> None:
        if "case_id" not in actual.columns or actual["case_id"].duplicated().any():
            raise StudyError(f"{label} case IDs are missing or non-unique")
        if set(actual["case_id"]) != set(expected["case_id"]):
            raise StudyError(f"{label} case IDs do not match the deterministic design")

    require_case_ids(regression, expected_regression, "regression")
    require_case_ids(dense, expected_dense, "dense")
    require_case_ids(global_frame, expected_global, "global")

    dense_axes_match = bool(
        np.allclose(
            np.sort(pd.to_numeric(dense["water_diffusivity_m2_s"]).unique()),
            expected_d,
            rtol=1.0e-14,
            atol=0.0,
        )
        and np.allclose(
            np.sort(
                pd.to_numeric(dense["uniform_current_density_a_m2"]).unique()
            ),
            expected_j,
            rtol=1.0e-14,
            atol=0.0,
        )
    )
    if not dense_axes_match:
        raise StudyError("Existing dense axes do not match the selected manifest")
    global_coordinates = [
        "water_drag",
        "lhs_diffusive_permeability_d_c_over_l",
        "lhs_total_reference_area_resistance_ohm_m2",
        "uniform_current_density_a_m2",
    ]
    merged = expected_global[["case_id", *global_coordinates]].merge(
        global_frame[["case_id", *global_coordinates]],
        on="case_id",
        suffixes=("_expected", "_actual"),
        validate="one_to_one",
    )
    global_design_match = all(
        np.allclose(
            pd.to_numeric(merged[f"{name}_actual"]),
            pd.to_numeric(merged[f"{name}_expected"]),
            rtol=2.0e-12,
            atol=0.0,
        )
        for name in global_coordinates
    )
    if not global_design_match:
        raise StudyError("Existing global LHS coordinates do not match deterministic design")
    _, regression_pass = archive_regression(regression, runtime["paths"].archive_cases)
    if not regression_pass:
        raise StudyError("Existing 12-row archive regression no longer passes")
    if len(expected_bounds) != 4:
        raise StudyError("Selected inverse-design parameterization is not four-dimensional")
    return {
        "pass": True,
        "prior_audit_sha256": sha256_file(audit_path),
        "config_used_sha256": config_used_hash,
        "config_canonical_sha256": canonical_json_sha256(config_used),
        "central_manifest_sha256": central_hash,
        "archive_sha256": runtime["archive_sha256"],
        "detailed_cases_sha256": selected_detailed_hash,
        "dense_axes_match": dense_axes_match,
        "global_design_match": global_design_match,
        "case_id_counts": {
            "regression": len(regression),
            "dense": len(dense),
            "global": len(global_frame),
        },
        "solver_script_versions": versions,
        "legacy_prior_audit_had_config_used_sha256": recorded_config_used_hash is not None,
    }


def main() -> int:
    args = parse_args()
    run_self_test()
    if args.self_test:
        return 0
    if args.jobs < 1:
        raise StudyError("--jobs must be at least 1")
    if args.regression_only and args.postprocess_existing:
        raise StudyError("--regression-only and --postprocess-existing are mutually exclusive")
    if not math.isclose(float(args.area_step_m2), 5.0, rel_tol=0.0, abs_tol=1.0e-12):
        raise StudyError(
            "The released study requires --area-step-m2 5 to preserve the archived regression"
        )

    output = args.output_dir.expanduser().resolve()
    output_has_files = output.exists() and any(output.iterdir())
    if args.postprocess_existing:
        if not output_has_files:
            raise StudyError(f"No existing result set to postprocess: {output}")
    elif output_has_files:
        raise StudyError(f"Output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    figures = output / "figures"
    started_wall = datetime.now(timezone.utc)
    started = time.perf_counter()
    prior_audit: dict[str, Any] = {}
    audit_started_at_utc = started_wall.isoformat()
    transport_runtime_seconds: float | None = None
    postprocess_input_validation: dict[str, Any] | None = None
    raw_dense_existing: pd.DataFrame | None = None
    raw_global_existing: pd.DataFrame | None = None

    paths = resolve_paths(args.v2_root, args.config, args.detailed_cases)
    config = read_json(paths.central_manifest)
    runtime = load_runtime(paths, config, float(args.area_step_m2))
    command_text = (
        " ".join([sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]]) + "\n"
    )
    if args.postprocess_existing:
        required_existing = [
            output / "post_erv_archive_regression_cases.csv",
            output / "post_erv_dense_dj_cases.csv",
            output / "post_erv_global_inverse_design_cases.csv",
        ]
        missing_existing = [str(path) for path in required_existing if not path.is_file()]
        if missing_existing:
            raise StudyError(f"Missing existing result files: {missing_existing}")
        if not (output / "audit.json").is_file():
            raise StudyError("Postprocess requires an existing audit.json")
        prior_audit = read_json(output / "audit.json")
        audit_started_at_utc = str(
            prior_audit.get("started_at_utc", audit_started_at_utc)
        )
        transport_runtime_seconds = finite(
            prior_audit.get("runtime_seconds"), default=math.nan
        )
        if not math.isfinite(transport_runtime_seconds):
            transport_runtime_seconds = None
        regression_results = pd.read_csv(required_existing[0])
        raw_dense_existing = pd.read_csv(required_existing[1])
        raw_global_existing = pd.read_csv(required_existing[2])
        postprocess_input_validation = validate_existing_result_set(
            output,
            runtime,
            config,
            regression_results,
            raw_dense_existing,
            raw_global_existing,
        )
        (output / "postprocess_command.txt").write_text(
            command_text, encoding="utf-8"
        )
    else:
        write_json(output / "config_used.json", config)
        (output / "run_command.txt").write_text(command_text, encoding="utf-8")
        regression_cases = build_regression_cases(runtime)
        regression_results = evaluate_cases(
            runtime,
            regression_cases,
            jobs=min(args.jobs, 3),
            label="archive regression",
        )
        regression_results.to_csv(
            output / "post_erv_archive_regression_cases.csv", index=False
        )

    figures.mkdir(exist_ok=True)

    if "solver_script_version" not in regression_results.columns:
        if "script_version" not in regression_results.columns:
            raise StudyError("Regression rows lack solver provenance")
        regression_results["solver_script_version"] = regression_results[
            "script_version"
        ]
    regression_solver_versions = set(
        regression_results["solver_script_version"].astype(str).unique()
    )
    if not regression_solver_versions.issubset(KNOWN_SOLVER_SCRIPT_VERSIONS):
        raise StudyError(
            "Unsupported regression solver version(s): "
            f"{sorted(regression_solver_versions)}"
        )
    regression_results["script_version"] = SCRIPT_VERSION
    regression_results["analysis_script_version"] = SCRIPT_VERSION
    regression_results.to_csv(
        output / "post_erv_archive_regression_cases.csv", index=False
    )
    regression_audit, regression_pass = archive_regression(
        regression_results, paths.archive_cases
    )
    regression_audit.to_csv(
        output / "post_erv_archive_regression_audit.csv", index=False
    )
    if not regression_pass:
        failure_audit = {
            "script_version": SCRIPT_VERSION,
            "pass": False,
            "failure": "12-point archived numerical regression failed",
            "archive_sha256": runtime["archive_sha256"],
            "full_system_status": "UNKNOWN",
        }
        write_json(output / "audit.json", failure_audit)
        raise StudyError("12-point archive regression failed; full grid was not started")
    print("12-point archived numerical regression: PASS", flush=True)

    if args.regression_only:
        write_json(
            output / "audit.json",
            {
                "script_version": SCRIPT_VERSION,
                "pass": True,
                "mode": "regression_only",
                "archive_regression_pass": True,
                "archive_regression_case_count": len(regression_results),
                "full_system_status": "UNKNOWN",
                "full_system_claim_allowed": False,
            },
        )
        return 0

    if args.postprocess_existing:
        if raw_dense_existing is None or raw_global_existing is None:
            raise StudyError("Internal error: validated postprocess rows are unavailable")
        dense = normalize_area_observations(raw_dense_existing)
        global_frame = normalize_area_observations(raw_global_existing)
        d_values = np.sort(
            pd.to_numeric(dense["water_diffusivity_m2_s"], errors="raise").unique()
        )
        j_values = np.sort(
            pd.to_numeric(
                dense["uniform_current_density_a_m2"], errors="raise"
            ).unique()
        )
        print(
            f"Postprocessing existing rows: dense={len(dense)}, global={len(global_frame)}",
            flush=True,
        )
    else:
        dense_cases, d_values, j_values = build_dense_cases(runtime)
        dense = normalize_area_observations(
            evaluate_cases(
                runtime,
                dense_cases,
                jobs=args.jobs,
                label="dense D-j",
                checkpoint=output / "post_erv_dense_dj_cases.checkpoint.csv",
            )
        )
        global_cases, global_bounds = build_global_cases(runtime)
        global_bounds.to_csv(
            output / "post_erv_global_parameter_bounds.csv", index=False
        )
        global_frame = normalize_area_observations(
            evaluate_cases(
                runtime,
                global_cases,
                jobs=args.jobs,
                label="global LHS",
                checkpoint=output / "post_erv_global_inverse_design_cases.checkpoint.csv",
            )
        )

    dense.to_csv(output / "post_erv_dense_dj_cases.csv", index=False)
    global_frame.to_csv(
        output / "post_erv_global_inverse_design_cases.csv", index=False
    )
    # Checkpoints are complete case tables after a successful run, so keep them
    # semantically aligned with the released CSVs during postprocessing.
    dense.to_csv(output / "post_erv_dense_dj_cases.checkpoint.csv", index=False)
    global_frame.to_csv(
        output / "post_erv_global_inverse_design_cases.checkpoint.csv", index=False
    )

    prcc = build_prcc(
        global_frame,
        int(config["post_erv"]["global_inverse_design"]["seed"]),
    )
    prcc.to_csv(output / "post_erv_global_prcc.csv", index=False)
    correlations = input_rank_correlation(global_frame)
    correlations.to_csv(output / "post_erv_global_input_rank_correlation.csv", index=False)
    pareto = build_pareto(global_frame)
    pareto.to_csv(output / "post_erv_global_pareto.csv", index=False)

    best_by_d, thresholds = dense_summaries(dense)
    best_by_d.to_csv(output / "post_erv_dense_best_current_by_diffusivity.csv", index=False)
    thresholds.to_csv(output / "post_erv_dense_thresholds_by_current.csv", index=False)
    detailed_validation, detailed_status = detailed_hvac_validation(
        dense, paths.detailed_cases
    )
    detailed_validation.to_csv(
        output / "post_erv_detailed_hvac_validation.csv", index=False
    )
    write_json(output / "post_erv_detailed_hvac_validation_status.json", detailed_status)

    plot_dense_regions(dense, figures)
    plot_global_results(global_frame, prcc, figures)
    summary_text, summary_payload = study_summary(
        dense, global_frame, prcc, pareto, detailed_status
    )
    (output / "SUMMARY.md").write_text(summary_text, encoding="utf-8")
    write_json(output / "DECISION_SUMMARY.json", summary_payload)

    dense_target = bool_series(dense["target_reached"])
    dense_censored = bool_series(dense["area_is_right_censored"])
    global_target = bool_series(global_frame["target_reached"])
    global_censored = bool_series(global_frame["area_is_right_censored"])
    dense_target_rows = dense.loc[dense_target]
    global_target_rows = global_frame.loc[global_target]
    dense_finite_water = pd.to_numeric(
        dense_target_rows["water_balance_relative_error"], errors="coerce"
    ).dropna()
    dense_finite_receiver = pd.to_numeric(
        dense_target_rows["receiver_water_balance_relative_error"], errors="coerce"
    ).dropna()
    global_finite_water = pd.to_numeric(
        global_target_rows["water_balance_relative_error"], errors="coerce"
    ).dropna()
    global_finite_receiver = pd.to_numeric(
        global_target_rows["receiver_water_balance_relative_error"], errors="coerce"
    ).dropna()
    finite_power = pd.to_numeric(
        dense["incremental_power_identity_error_kw"], errors="coerce"
    ).dropna()
    exception_count = int(dense["numerical_status"].eq("EXCEPTION").sum()) + int(
        global_frame["numerical_status"].eq("EXCEPTION").sum()
    )
    full_unknown = bool(
        dense["full_system_status"].eq("UNKNOWN").all()
        and global_frame["full_system_status"].eq("UNKNOWN").all()
    )
    dense_area_coordinate = pd.to_numeric(
        dense["required_active_area_censored_m2"], errors="coerce"
    )
    global_area_coordinate = pd.to_numeric(
        global_frame["required_active_area_censored_m2"], errors="coerce"
    )
    dense_unobserved = ~(dense_target | dense_censored)
    global_unobserved = ~(global_target | global_censored)
    area_observation_semantics_pass = bool(
        dense_area_coordinate[dense_target | dense_censored].notna().all()
        and dense_area_coordinate[dense_unobserved].isna().all()
        and global_area_coordinate[global_target | global_censored].notna().all()
        and global_area_coordinate[global_unobserved].isna().all()
        and dense.loc[dense_unobserved, "area_observation_status"]
        .eq("NOT_OBSERVED")
        .all()
        and global_frame.loc[global_unobserved, "area_observation_status"]
        .eq("NOT_OBSERVED")
        .all()
    )
    surface_margin_endpoint_definition_pass = True
    surface_margin_finite_count = 0
    for surface_frame in (dense, global_frame):
        endpoint_margin = pd.to_numeric(
            surface_frame["minimum_surface_activity_margin"], errors="coerce"
        )
        legacy_margin = pd.to_numeric(
            surface_frame["legacy_step_average_minimum_surface_activity_margin"],
            errors="coerce",
        )
        comparable = endpoint_margin.notna() & legacy_margin.notna()
        surface_margin_finite_count += int(comparable.sum())
        declared_positive = bool_series(
            surface_frame["positive_surface_direction_everywhere"]
        )
        surface_margin_endpoint_definition_pass = bool(
            surface_margin_endpoint_definition_pass
            and (endpoint_margin[comparable] <= legacy_margin[comparable] + 1.0e-12).all()
            and declared_positive[comparable]
            .eq(endpoint_margin[comparable] > 0.0)
            .all()
        )
    target_saving_mask_pass = bool(
        pd.to_numeric(
            dense.loc[dense_target, "target_reached_screening_saving_pct"],
            errors="coerce",
        )
        .notna()
        .all()
        and pd.to_numeric(
            dense.loc[~dense_target, "target_reached_screening_saving_pct"],
            errors="coerce",
        )
        .isna()
        .all()
    )
    target_tolerance_g_kg_da = 1000.0 * 1.0e-10
    target_w_g_kg_da = 1000.0 * float(runtime["target_w"])
    dense_censored_strictly_above_target = bool(
        pd.to_numeric(
            dense.loc[dense_censored, "outlet_w_g_kg_da"], errors="coerce"
        )
        .gt(target_w_g_kg_da + target_tolerance_g_kg_da)
        .all()
        and dense.loc[dense_censored, "status"].eq("area_limit_before_target").all()
    )
    global_censored_strictly_above_target = bool(
        pd.to_numeric(
            global_frame.loc[global_censored, "outlet_w_g_kg_da"], errors="coerce"
        )
        .gt(target_w_g_kg_da + target_tolerance_g_kg_da)
        .all()
        and global_frame.loc[global_censored, "status"]
        .eq("area_limit_before_target")
        .all()
    )
    capped_area_prcc_counts = prcc.loc[
        prcc["output"].eq("required_active_area_censored_m2"),
        "complete_case_count",
    ].unique()
    capped_area_prcc_excludes_unobserved = bool(
        len(capped_area_prcc_counts) == 1
        and int(capped_area_prcc_counts[0]) == int((~global_unobserved).sum())
        and prcc.loc[
            prcc["output"].eq("required_active_area_censored_m2"),
            "analysis_population",
        ]
        .eq("TARGET_REACHED_OR_RIGHT_CENSORED_CAPPED_COORDINATE")
        .all()
    )
    observed_area_prcc_counts = prcc.loc[
        prcc["output"].eq("required_active_area_m2"), "complete_case_count"
    ].unique()
    observed_area_prcc_target_reached_only = bool(
        len(observed_area_prcc_counts) == 1
        and int(observed_area_prcc_counts[0]) == int(global_target.sum())
        and prcc.loc[
            prcc["output"].eq("required_active_area_m2"),
            "analysis_population",
        ]
        .eq("TARGET_REACHED_OBSERVED_AREA_ONLY")
        .all()
    )
    saving_prcc_counts = prcc.loc[
        prcc["output"].eq("incremental_saving_kw_vs_passive_erv"),
        "complete_case_count",
    ].unique()
    saving_prcc_target_reached_only = bool(
        len(saving_prcc_counts) == 1
        and int(saving_prcc_counts[0]) == int(global_target.sum())
        and prcc.loc[
            prcc["output"].eq("incremental_saving_kw_vs_passive_erv"),
            "analysis_population",
        ]
        .eq("TARGET_REACHED_ONLY")
        .all()
    )
    feasibility_prcc_counts = prcc.loc[
        prcc["output"].eq("transport_gate_numeric"), "complete_case_count"
    ].unique()
    feasibility_prcc_uses_all_cases = bool(
        len(feasibility_prcc_counts) == 1
        and int(feasibility_prcc_counts[0]) == len(global_frame)
    )
    censor_prcc_counts = prcc.loc[
        prcc["output"].eq("area_censoring_numeric"), "complete_case_count"
    ].unique()
    censor_prcc_uses_reached_or_censored = bool(
        len(censor_prcc_counts) == 1
        and int(censor_prcc_counts[0]) == int((global_target | global_censored).sum())
        and prcc.loc[
            prcc["output"].eq("area_censoring_numeric"),
            "analysis_population",
        ]
        .eq("REACHED_OR_CENSORED_CENSOR_ASSOCIATION")
        .all()
    )
    bounds_path = output / "post_erv_global_parameter_bounds.csv"
    bounds_frame = pd.read_csv(bounds_path) if bounds_path.is_file() else pd.DataFrame()
    global_parameter_bounds_count = len(bounds_frame)
    expected_regression_ids = {
        str(case["case_id"]) for case in build_regression_cases(runtime)
    }
    expected_dense_cases_audit, expected_d_values, expected_j_values = (
        build_dense_cases(runtime)
    )
    expected_global_cases_audit, _ = build_global_cases(runtime)
    deterministic_case_ids_pass = bool(
        not regression_results["case_id"].duplicated().any()
        and not dense["case_id"].duplicated().any()
        and not global_frame["case_id"].duplicated().any()
        and set(regression_results["case_id"]) == expected_regression_ids
        and set(dense["case_id"])
        == {str(case["case_id"]) for case in expected_dense_cases_audit}
        and set(global_frame["case_id"])
        == {str(case["case_id"]) for case in expected_global_cases_audit}
        and np.allclose(d_values, expected_d_values, rtol=1.0e-14, atol=0.0)
        and np.allclose(j_values, expected_j_values, rtol=1.0e-14, atol=0.0)
    )
    inverse_cfg = config["post_erv"]["global_inverse_design"]
    sampled_coordinate_parameterization_explicit = bool(
        inverse_cfg.get("sampled_coordinate_parameterization")
        == "water_drag, D*C/L, total_L_over_sigma_plus_series_ASR, current_density"
        and inverse_cfg.get("dry_thickness_independently_sampled") is False
        and "dry_thickness_um_range" not in inverse_cfg
        and math.isclose(
            float(inverse_cfg.get("mapping_dry_thickness_um", math.nan)),
            float(runtime["anchor"]["dry_thickness_um"]),
            rel_tol=1.0e-12,
            abs_tol=1.0e-12,
        )
        and bool(str(inverse_cfg.get("identifiability_note", "")).strip())
        and set(bounds_frame.get("parameter", pd.Series(dtype=str)))
        == {
            "lhs_water_drag",
            "lhs_diffusive_permeability_d_c_over_l",
            "lhs_total_reference_area_resistance_ohm_m2",
            "lhs_uniform_current_density_a_m2",
        }
    )
    current_policy = config["current_density_policy"]
    detailed_ok = bool(
        detailed_status.get("availability") == "AVAILABLE"
        and detailed_status.get("validation_pass") is True
        and int(detailed_status.get("selected_point_count", 0)) > 0
    )
    dense_target_count = int(dense_target.sum())
    global_target_count = int(global_target.sum())
    dense_conditional_count = int(bool_series(dense["conditional_energy_pass"]).sum())
    global_conditional_count = int(
        bool_series(global_frame["conditional_energy_pass"]).sum()
    )
    finite_balance_counts_match_targets = bool(
        len(dense_finite_water) == dense_target_count
        and len(dense_finite_receiver) == dense_target_count
        and len(global_finite_water) == global_target_count
        and len(global_finite_receiver) == global_target_count
    )
    audit_pass = bool(
        regression_pass
        and len(d_values) >= 30
        and len(j_values) >= 30
        and len(dense) == len(d_values) * len(j_values)
        and len(global_frame)
        == int(config["post_erv"]["global_inverse_design"]["base_sample_size"])
        and exception_count == 0
        and dense_target_count > 0
        and global_target_count > 0
        and dense_conditional_count > 0
        and global_conditional_count > 0
        and finite_balance_counts_match_targets
        and dense_finite_water.abs().max() <= 1.0e-10
        and dense_finite_receiver.abs().max() <= 1.0e-10
        and global_finite_water.abs().max() <= 1.0e-10
        and global_finite_receiver.abs().max() <= 1.0e-10
        and (finite_power.empty or finite_power.abs().max() <= 1.0e-8)
        and area_observation_semantics_pass
        and surface_margin_endpoint_definition_pass
        and target_saving_mask_pass
        and dense_censored_strictly_above_target
        and global_censored_strictly_above_target
        and capped_area_prcc_excludes_unobserved
        and observed_area_prcc_target_reached_only
        and saving_prcc_target_reached_only
        and censor_prcc_uses_reached_or_censored
        and feasibility_prcc_uses_all_cases
        and global_parameter_bounds_count == 4
        and deterministic_case_ids_pass
        and sampled_coordinate_parameterization_explicit
        and full_unknown
        and current_policy["engineering_current_density_limit_a_m2"] is None
        and detailed_ok
    )
    completed = datetime.now(timezone.utc)
    audit = {
        "script_version": SCRIPT_VERSION,
        "study_id": config["study_id"],
        "pass": audit_pass,
        "generated_at_utc": completed.isoformat(),
        "started_at_utc": audit_started_at_utc,
        "runtime_seconds": (
            transport_runtime_seconds
            if transport_runtime_seconds is not None
            else time.perf_counter() - started
        ),
        "postprocessing_runtime_seconds": (
            time.perf_counter() - started if args.postprocess_existing else None
        ),
        "postprocessed_from_existing_solver_rows": bool(args.postprocess_existing),
        "jobs": args.jobs,
        "area_step_m2": args.area_step_m2,
        "area_observation_cap_m2": runtime["area_limit_m2"],
        "archive_regression_pass": regression_pass,
        "archive_regression_case_count": len(regression_results),
        "archive_sha256": runtime["archive_sha256"],
        "dense_d_points": len(d_values),
        "dense_j_points": len(j_values),
        "dense_case_count": len(dense),
        "global_lhs_case_count": len(global_frame),
        "global_lhs_seed": config["post_erv"]["global_inverse_design"]["seed"],
        "exception_count": exception_count,
        "dense_target_reached_count": dense_target_count,
        "global_target_reached_count": global_target_count,
        "dense_conditional_positive_count": dense_conditional_count,
        "global_conditional_positive_count": global_conditional_count,
        "finite_balance_counts_match_target_counts": finite_balance_counts_match_targets,
        "area_observation_semantics_pass": area_observation_semantics_pass,
        "surface_margin_endpoint_definition_pass": surface_margin_endpoint_definition_pass,
        "surface_margin_endpoint_comparison_finite_count": surface_margin_finite_count,
        "surface_margin_definition": (
            "minimum of start/end local source_surface_activity minus "
            "receiver_surface_activity over every accepted integration step"
        ),
        "archive_regression_surface_margin_projection": (
            "legacy step-average margin retained only to regress against the archived "
            "12-case output; released gate uses endpoint minimum"
        ),
        "target_reached_saving_mask_pass": target_saving_mask_pass,
        "dense_censored_strictly_above_target": dense_censored_strictly_above_target,
        "global_censored_strictly_above_target": global_censored_strictly_above_target,
        "capped_area_prcc_excludes_unobserved_rows": capped_area_prcc_excludes_unobserved,
        "observed_area_prcc_target_reached_only": observed_area_prcc_target_reached_only,
        "saving_prcc_target_reached_only": saving_prcc_target_reached_only,
        "censor_prcc_uses_reached_or_censored": censor_prcc_uses_reached_or_censored,
        "feasibility_prcc_uses_all_cases": feasibility_prcc_uses_all_cases,
        "global_parameter_bounds_count": global_parameter_bounds_count,
        "deterministic_case_ids_and_axes_pass": deterministic_case_ids_pass,
        "sampled_coordinate_parameterization_explicit": sampled_coordinate_parameterization_explicit,
        "sampled_coordinate_parameterization": inverse_cfg.get(
            "sampled_coordinate_parameterization"
        ),
        "dry_thickness_independently_sampled": inverse_cfg.get(
            "dry_thickness_independently_sampled"
        ),
        "mapping_dry_thickness_um": inverse_cfg.get("mapping_dry_thickness_um"),
        "identifiability_note": inverse_cfg.get("identifiability_note"),
        "dense_area_coordinate_defined_count": int((~dense_unobserved).sum()),
        "dense_unobserved_area_omitted_count": int(dense_unobserved.sum()),
        "global_area_coordinate_defined_count": int((~global_unobserved).sum()),
        "global_unobserved_area_omitted_count": int(global_unobserved.sum()),
        "global_observed_area_prcc_complete_case_count": (
            int(observed_area_prcc_counts[0])
            if len(observed_area_prcc_counts) == 1
            else None
        ),
        "global_capped_area_prcc_complete_case_count": (
            int(capped_area_prcc_counts[0])
            if len(capped_area_prcc_counts) == 1
            else None
        ),
        "global_saving_prcc_complete_case_count": (
            int(saving_prcc_counts[0]) if len(saving_prcc_counts) == 1 else None
        ),
        "global_feasibility_prcc_complete_case_count": (
            int(feasibility_prcc_counts[0])
            if len(feasibility_prcc_counts) == 1
            else None
        ),
        "global_censor_prcc_complete_case_count": (
            int(censor_prcc_counts[0]) if len(censor_prcc_counts) == 1 else None
        ),
        "dense_target_reached_water_balance_finite_count": len(dense_finite_water),
        "dense_target_reached_receiver_balance_finite_count": len(
            dense_finite_receiver
        ),
        "global_target_reached_water_balance_finite_count": len(global_finite_water),
        "global_target_reached_receiver_balance_finite_count": len(
            global_finite_receiver
        ),
        "dense_target_reached_water_balance_max_abs": (
            float(dense_finite_water.abs().max())
            if not dense_finite_water.empty
            else None
        ),
        "dense_target_reached_receiver_balance_max_abs": (
            float(dense_finite_receiver.abs().max())
            if not dense_finite_receiver.empty
            else None
        ),
        "global_target_reached_water_balance_max_abs": (
            float(global_finite_water.abs().max())
            if not global_finite_water.empty
            else None
        ),
        "global_target_reached_receiver_balance_max_abs": (
            float(global_finite_receiver.abs().max())
            if not global_finite_receiver.empty
            else None
        ),
        "power_identity_max_abs_kw": (
            float(finite_power.abs().max()) if not finite_power.empty else None
        ),
        "dense_area_right_censored_count": int(
            bool_series(dense["area_is_right_censored"]).sum()
        ),
        "global_area_right_censored_count": int(
            bool_series(global_frame["area_is_right_censored"]).sum()
        ),
        "engineering_current_density_limit_a_m2": None,
        "current_density_is_sampling_or_control_axis": True,
        "no_21_a_m2_gate_applied": True,
        "screening_hvac_used_for_full_grid": True,
        "detailed_hvac_validation": detailed_status,
        "detailed_cases_path": str(paths.detailed_cases),
        "detailed_cases_sha256": sha256_file(paths.detailed_cases),
        "solver_script_versions": {
            "regression": sorted(
                set(regression_results["solver_script_version"].astype(str))
            ),
            "dense": sorted(set(dense["solver_script_version"].astype(str))),
            "global": sorted(set(global_frame["solver_script_version"].astype(str))),
        },
        "area_censoring_interpretation": (
            "24 000 m2 values are right-censored lower bounds, not required-area estimates"
        ),
        "full_system_status": "UNKNOWN",
        "full_system_status_unknown_everywhere": full_unknown,
        "full_system_claim_allowed": False,
        "missing_receiver_energy_status": "UNKNOWN",
        "independent_ion_concentration_potential_modelled": False,
        "global_inverse_design_is_probability_distribution": False,
        "source_paths": {
            key: str(value)
            for key, value in paths.__dict__.items()
        },
        "source_sha256": runtime["source_hashes"],
        "central_manifest_sha256": sha256_file(paths.central_manifest),
        "config_used_sha256": sha256_file(output / "config_used.json"),
        "config_used_canonical_sha256": canonical_json_sha256(config),
        "postprocess_input_validation": postprocess_input_validation,
        "script_sha256": sha256_file(Path(__file__).resolve()),
    }
    write_json(output / "audit.json", audit)
    if not audit_pass:
        raise StudyError("Final computational audit failed; inspect audit.json")

    print("=== POST-ERV INVERSE-DESIGN STUDY COMPLETE ===")
    print(f"Archive regression:       PASS ({len(regression_results)} cases)")
    print(f"Dense D-j grid:           {len(d_values)} x {len(j_values)} = {len(dense)}")
    print(f"Global deterministic LHS: {len(global_frame)}")
    print(f"Area-censored dense rows: {audit['dense_area_right_censored_count']}")
    print(f"Full-system status:       UNKNOWN")
    print(f"Outputs:                  {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
