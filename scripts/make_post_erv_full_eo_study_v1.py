#!/usr/bin/env python3
"""Explore ERV followed by EO for the complete remaining latent duty.

The study keeps two questions separate:

1. How much all-in EO energy is available before ERV + EO + sensible cooling
   loses its advantage over the equal-service passive ERV + AC reference?
2. Can the current finite-film membrane model actually reach the requested
   post-ERV humidity target, and what area/core-power/receiver budget follows?

The first question is an architecture-agnostic energy window.  The second
reuses the audited post-ERV counter-current transport integrator.  Receiver
and sink SEC remain parameterized, so no row is promoted to a full-system
saving claim.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
from types import ModuleType
from typing import Any, Iterable, Mapping, Sequence

os.environ.setdefault("MPLCONFIGDIR", "/tmp/heiq-post-erv-full-eo-mpl")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


SCRIPT_VERSION = "post-erv-full-remaining-eo-v1.0-2026-08-27"
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "post_erv_full_eo_study_v1.json"
DEFAULT_OUTPUT = ROOT / "outputs" / "post_erv_full_eo_study_v1"
DEFAULT_V2_ROOT = ROOT.parent / "HeiQ_V2"


class StudyError(RuntimeError):
    """Raised when the declared study contract or audit is violated."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--v2-root", type=Path, default=DEFAULT_V2_ROOT)
    parser.add_argument("--jobs", type=int, default=min(8, os.cpu_count() or 1))
    parser.add_argument(
        "--energy-only",
        action="store_true",
        help="Generate the fast energy window without running membrane transport.",
    )
    parser.add_argument(
        "--postprocess-existing",
        action="store_true",
        help="Rebuild summaries, selections, scenarios and plots without rerunning the full sweep; selected step-halving checks are rerun.",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Run one diffusivity and three current-density points per target.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow this script to replace its own named artifacts in a non-empty output directory.",
    )
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
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
    if isinstance(value, Path):
        return str(value)
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


def sha256_json(payload: Any) -> str:
    encoded = json.dumps(
        json_safe(payload), sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise StudyError(f"Could not load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def resolve_config_path(repo_root: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = repo_root / path
    return path.resolve()


def bool_series(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series.fillna(False)
    if pd.api.types.is_numeric_dtype(series):
        return series.fillna(0).astype(float).ne(0.0)
    return series.astype(str).str.strip().str.lower().isin({"true", "1", "yes", "y"})


def validate_output_directory(path: Path, overwrite: bool) -> None:
    if path.exists() and any(path.iterdir()) and not overwrite:
        raise StudyError(
            f"Output directory is not empty: {path}. Use --overwrite or choose another directory."
        )
    path.mkdir(parents=True, exist_ok=True)


def validate_output_mode(path: Path, *, energy_only: bool) -> None:
    """Prevent a fast run from leaving stale transport artifacts beside its audit."""

    if energy_only and (path / "transport_cases.csv").is_file():
        raise StudyError(
            "Energy-only output cannot reuse a directory containing transport_cases.csv; "
            "choose a separate --output-dir."
        )


def load_runtime(
    config: Mapping[str, Any],
    *,
    v2_root: Path,
    area_step_m2: float,
) -> tuple[ModuleType, dict[str, Any], dict[str, Any], Path, Path]:
    source_config_path = resolve_config_path(
        ROOT, str(config["source_operating_region_config"])
    )
    source_config = read_json(source_config_path)
    analyzer_path = ROOT / "scripts" / "analyze_post_erv_inverse_design_v1.py"
    analyzer = load_module(analyzer_path, "post_erv_full_eo_transport_source")
    paths = analyzer.resolve_paths(v2_root, source_config_path)
    runtime = analyzer.load_runtime(paths, source_config, area_step_m2)
    return analyzer, runtime, source_config, source_config_path, analyzer_path


def target_table(config: Mapping[str, Any], inlet_w: float) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for target in config["targets"]:
        target_id = str(target["target_id"])
        if not target_id or target_id in seen:
            raise StudyError(f"Target IDs must be non-empty and unique: {target_id!r}")
        seen.add(target_id)
        target_w = float(target["humidity_ratio_kg_kg_da"])
        if target_w <= 0.0:
            raise StudyError(f"Target humidity ratio must be positive: {target_id}")
        requires_eo = target_w < inlet_w - 1.0e-12
        if bool(target["run_transport"]) and not requires_eo:
            raise StudyError(f"Transport target {target_id} is not below the ERV outlet")
        rows.append(
            {
                "target_id": target_id,
                "label": str(target["label"]),
                "target_w_kg_kg_da": target_w,
                "target_w_g_kg_da": 1000.0 * target_w,
                "requires_post_erv_eo": requires_eo,
                "run_transport": bool(target["run_transport"]),
                "interpretation": str(target["interpretation"]),
            }
        )
    return pd.DataFrame(rows)


def state_after_eo(
    runtime: Mapping[str, Any],
    *,
    target_w: float,
    eo_power_kw: float,
    process_heat_leak_fraction: float,
) -> Any:
    system_core = runtime["system_core"]
    inlet = runtime["process_in"]
    m_da = float(runtime["dry_air_mass_flow_kg_s"])
    isothermal = system_core.state_from_t_w(
        float(inlet.t_c), target_w, float(runtime["pressure_pa"]), "post-EO isothermal"
    )
    outlet_h = float(isothermal.h) + eo_power_kw * process_heat_leak_fraction / m_da
    return system_core.state_from_h_w(
        outlet_h, target_w, float(runtime["pressure_pa"]), "post-EO with process heat"
    )


def evaluate_energy_case(
    runtime: Mapping[str, Any],
    *,
    target: Mapping[str, Any],
    sec_kwh_per_kg: float,
    heat_fraction: float,
) -> dict[str, Any]:
    if sec_kwh_per_kg < 0.0:
        raise StudyError("EO SEC cannot be negative")
    if not 0.0 <= heat_fraction <= 1.0:
        raise StudyError("Process heat-leak fraction must lie in [0, 1]")
    inlet_w = float(runtime["process_in"].w)
    target_w = float(target["target_w_kg_kg_da"])
    m_da = float(runtime["dry_air_mass_flow_kg_s"])
    water_kg_h = m_da * max(inlet_w - target_w, 0.0) * 3600.0
    eo_power_kw = water_kg_h * sec_kwh_per_kg
    outlet = state_after_eo(
        runtime,
        target_w=min(target_w, inlet_w),
        eo_power_kw=eo_power_kw,
        process_heat_leak_fraction=heat_fraction,
    )
    baseline = runtime["baseline"]
    active_cfg = runtime["active_cfg"]
    remaining_ac = runtime["system_core"].solve_coil(
        inlet=outlet,
        supply_target=baseline.remaining_ac.supply,
        m_da=m_da,
        rated_cop=baseline.rated_cop,
        ac_config=active_cfg["ac_model"],
    )
    erv_kw = float(baseline.passive_erv.total_power_kw)
    common_kw = float(
        active_cfg.get("common_components", {}).get(
            "common_electric_power_kw_each_system", 0.0
        )
    )
    total_kw = erv_kw + float(remaining_ac.total_ac_power_kw) + eo_power_kw + common_kw
    saving_kw = float(baseline.total_power_kw) - total_kw
    return {
        "target_id": str(target["target_id"]),
        "label": str(target["label"]),
        "target_w_g_kg_da": 1000.0 * target_w,
        "all_in_eo_sec_kwh_per_kg": sec_kwh_per_kg,
        "process_heat_leak_fraction": heat_fraction,
        "eo_water_removal_kg_h": water_kg_h,
        "eo_power_kw": eo_power_kw,
        "eo_heat_to_process_kw": eo_power_kw * heat_fraction,
        "remaining_ac_water_removal_kg_h": float(remaining_ac.water_removed_kg_h),
        "remaining_ac_power_kw": float(remaining_ac.total_ac_power_kw),
        "remaining_ac_is_sensible_only": bool(
            float(remaining_ac.water_removed_kg_h) <= 1.0e-8
        ),
        "remaining_ac_physical": bool(remaining_ac.physical),
        "passive_erv_power_kw": erv_kw,
        "reference_erv_plus_ac_power_kw": float(baseline.total_power_kw),
        "erv_plus_eo_plus_remaining_ac_power_kw": total_kw,
        "net_saving_kw_vs_erv_ac": saving_kw,
        "net_saving_pct_vs_erv_ac": 100.0 * saving_kw / float(baseline.total_power_kw),
        "energy_identity_error_kw": saving_kw
        - (float(baseline.remaining_ac.total_ac_power_kw)
           - float(remaining_ac.total_ac_power_kw)
           - eo_power_kw),
        "full_system_claim_allowed": False,
    }


def find_break_even_sec(
    runtime: Mapping[str, Any],
    *,
    target: Mapping[str, Any],
    heat_fraction: float,
    search_max: float,
) -> float:
    if not bool(target["requires_post_erv_eo"]):
        return math.nan

    def saving(sec: float) -> float:
        return float(
            evaluate_energy_case(
                runtime,
                target=target,
                sec_kwh_per_kg=sec,
                heat_fraction=heat_fraction,
            )["net_saving_kw_vs_erv_ac"]
        )

    lo = 0.0
    if saving(lo) <= 0.0:
        return 0.0
    hi = float(search_max)
    while saving(hi) > 0.0 and hi < 10.0:
        hi *= 2.0
    if saving(hi) > 0.0:
        return math.inf
    for _ in range(120):
        mid = 0.5 * (lo + hi)
        value = saving(mid)
        if abs(value) <= 1.0e-10:
            return mid
        if value > 0.0:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def build_energy_window(
    runtime: Mapping[str, Any],
    targets: pd.DataFrame,
    config: Mapping[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    section = config["energy_window"]
    sec_values = [float(value) for value in section["all_in_eo_sec_kwh_per_kg"]]
    heat_values = [float(value) for value in section["process_heat_leak_fractions"]]
    search_max = float(section["break_even_search_max_kwh_per_kg"])
    rows: list[dict[str, Any]] = []
    break_even_rows: list[dict[str, Any]] = []
    for target in targets.to_dict("records"):
        if not bool(target["requires_post_erv_eo"]):
            continue
        for heat_fraction in heat_values:
            break_even = find_break_even_sec(
                runtime,
                target=target,
                heat_fraction=heat_fraction,
                search_max=search_max,
            )
            zero = evaluate_energy_case(
                runtime,
                target=target,
                sec_kwh_per_kg=0.0,
                heat_fraction=heat_fraction,
            )
            break_even_rows.append(
                {
                    "target_id": target["target_id"],
                    "label": target["label"],
                    "target_w_g_kg_da": target["target_w_g_kg_da"],
                    "process_heat_leak_fraction": heat_fraction,
                    "eo_water_removal_kg_h": zero["eo_water_removal_kg_h"],
                    "remaining_ac_power_kw_at_zero_eo_sec": zero[
                        "remaining_ac_power_kw"
                    ],
                    "maximum_avoided_ac_power_kw_at_zero_eo_sec": float(
                        runtime["baseline"].remaining_ac.total_ac_power_kw
                    )
                    - float(zero["remaining_ac_power_kw"]),
                    "break_even_all_in_eo_sec_kwh_per_kg": break_even,
                    "full_system_claim_allowed": False,
                }
            )
            for sec in sec_values:
                row = evaluate_energy_case(
                    runtime,
                    target=target,
                    sec_kwh_per_kg=sec,
                    heat_fraction=heat_fraction,
                )
                row["break_even_all_in_eo_sec_kwh_per_kg"] = break_even
                row["sec_margin_kwh_per_kg"] = break_even - sec
                row["conditional_energy_positive"] = bool(
                    row["net_saving_kw_vs_erv_ac"] > 0.0
                )
                rows.append(row)
    return pd.DataFrame(rows), pd.DataFrame(break_even_rows)


def build_endpoint_control_audit(
    runtime: Mapping[str, Any], config: Mapping[str, Any]
) -> pd.DataFrame:
    """Expose the exact-supply control-regime discontinuity explicitly."""

    section = config["endpoint_control_audit"]
    supply_w = float(runtime["baseline"].remaining_ac.supply.w)
    heat_fraction = float(section["process_heat_leak_fraction"])
    search_max = float(config["energy_window"]["break_even_search_max_kwh_per_kg"])
    rows: list[dict[str, Any]] = []
    for offset_g_kg in section["humidity_offsets_above_supply_g_kg_da"]:
        offset = float(offset_g_kg)
        target_w = supply_w + offset / 1000.0
        target = {
            "target_id": "endpoint_control_audit",
            "label": "Supply-endpoint control audit",
            "target_w_kg_kg_da": target_w,
            "target_w_g_kg_da": 1000.0 * target_w,
            "requires_post_erv_eo": True,
        }
        zero = evaluate_energy_case(
            runtime,
            target=target,
            sec_kwh_per_kg=0.0,
            heat_fraction=heat_fraction,
        )
        break_even = find_break_even_sec(
            runtime,
            target=target,
            heat_fraction=heat_fraction,
            search_max=search_max,
        )
        rows.append(
            {
                "humidity_offset_above_supply_g_kg_da": offset,
                "target_w_g_kg_da": 1000.0 * target_w,
                "eo_water_removal_kg_h": zero["eo_water_removal_kg_h"],
                "remaining_ac_water_removal_kg_h": zero[
                    "remaining_ac_water_removal_kg_h"
                ],
                "remaining_ac_power_kw_at_zero_eo_sec": zero["remaining_ac_power_kw"],
                "remaining_ac_is_sensible_only": zero[
                    "remaining_ac_is_sensible_only"
                ],
                "break_even_all_in_eo_sec_kwh_per_kg": break_even,
                "control_regime": (
                    "SENSIBLE_ONLY_EXACT_ENDPOINT"
                    if zero["remaining_ac_is_sensible_only"]
                    else "SATURATED_COIL_WITH_REMAINING_LATENT_DUTY"
                ),
                "interpretation": section["interpretation"],
                "full_system_claim_allowed": False,
            }
        )
    return pd.DataFrame(rows)


def build_transport_case_design(
    targets: pd.DataFrame,
    config: Mapping[str, Any],
    *,
    smoke: bool,
) -> pd.DataFrame:
    sweep = config["transport_sweep"]
    currents = [float(value) for value in sweep["uniform_current_density_a_m2"]]
    diffusivities = [float(value) for value in sweep["water_diffusivity_m2_s"]]
    receiver_ratios = [
        float(value) for value in sweep["receiver_to_process_dry_air_ratio"]
    ]
    if smoke:
        currents = [
            float(value) for value in sweep["smoke_uniform_current_density_a_m2"]
        ]
        diffusivities = [diffusivities[0]]
        receiver_ratios = [
            float(value)
            for value in sweep["smoke_receiver_to_process_dry_air_ratio"]
        ]
    ratio_sweep_targets = {
        str(value) for value in sweep["receiver_capacity_sweep_target_ids"]
    }
    rows: list[dict[str, Any]] = []
    for target in targets.loc[bool_series(targets["run_transport"])].to_dict(
        "records"
    ):
        target_receiver_ratios = (
            receiver_ratios
            if str(target["target_id"]) in ratio_sweep_targets
            else [1.0]
        )
        for diffusivity in diffusivities:
            for current in currents:
                for receiver_ratio in target_receiver_ratios:
                    rows.append(
                        {
                            "case_id": (
                                f"{target['target_id']}__D{diffusivity:.6e}__j{current:g}"
                                f"__R{receiver_ratio:g}"
                            ),
                            "target_id": str(target["target_id"]),
                            "target_label": str(target["label"]),
                            "target_definition": str(target["interpretation"]),
                            "target_w_kg_kg_da": float(target["target_w_kg_kg_da"]),
                            "target_w_g_kg_da": float(target["target_w_g_kg_da"]),
                            "water_diffusivity_m2_s": diffusivity,
                            "uniform_current_density_a_m2": current,
                            "receiver_to_process_dry_air_ratio": receiver_ratio,
                        }
                    )
    design = pd.DataFrame(rows)
    if not design.empty and design["case_id"].duplicated().any():
        raise StudyError("Transport case design contains duplicate case IDs")
    return design


def transport_cases(
    analyzer: ModuleType,
    base_runtime: Mapping[str, Any],
    targets: pd.DataFrame,
    config: Mapping[str, Any],
    *,
    jobs: int,
    smoke: bool,
) -> pd.DataFrame:
    sweep = config["transport_sweep"]
    design = build_transport_case_design(targets, config, smoke=smoke)
    endpoint_audit = build_endpoint_control_audit(base_runtime, config)
    near_endpoint = endpoint_audit.loc[
        endpoint_audit["humidity_offset_above_supply_g_kg_da"] > 0.0
    ].sort_values("humidity_offset_above_supply_g_kg_da").iloc[0]
    near_endpoint_ac_reduction_kw = float(
        base_runtime["baseline"].remaining_ac.total_ac_power_kw
    ) - float(near_endpoint["remaining_ac_power_kw_at_zero_eo_sec"])
    all_frames: list[pd.DataFrame] = []
    for _, target_design in design.groupby("target_id", sort=False):
        target = target_design.iloc[0]
        runtime = dict(base_runtime)
        runtime["target_w"] = float(target["target_w_kg_kg_da"])
        runtime["area_limit_m2"] = float(sweep["area_observation_cap_m2"])
        cases: list[dict[str, Any]] = []
        for design_row in target_design.to_dict("records"):
            case = analyzer.base_case_material(runtime["anchor"])
            case.update(
                {
                    "study_family": "post_erv_full_remaining_target_sweep",
                    "case_id": str(design_row["case_id"]),
                    "water_diffusivity_m2_s": float(
                        design_row["water_diffusivity_m2_s"]
                    ),
                    "uniform_current_density_a_m2": float(
                        design_row["uniform_current_density_a_m2"]
                    ),
                    "receiver_to_process_dry_air_ratio": float(
                        design_row["receiver_to_process_dry_air_ratio"]
                    ),
                }
            )
            cases.append(case)
        frame = analyzer.evaluate_cases(
            runtime,
            cases,
            jobs=jobs,
            label=str(target["target_id"]),
        )
        frame["target_id"] = str(target["target_id"])
        frame["target_label"] = str(target["target_label"])
        frame["target_definition"] = str(target["target_definition"])
        frame["model_boundary"] = (
            "passive ERV outlet -> finite-film counter-current EO -> remaining AC"
        )
        water = pd.to_numeric(
            frame["incremental_water_removal_target_kg_h"], errors="coerce"
        )
        addon = pd.to_numeric(frame["incremental_eo_and_fan_power_kw"], errors="coerce")
        saving = pd.to_numeric(
            frame["incremental_saving_kw_vs_passive_erv"], errors="coerce"
        )
        frame["known_eo_core_and_module_fan_sec_kwh_per_kg"] = addon / water
        frame["conditional_receiver_and_sink_sec_budget_kwh_per_kg"] = saving / water
        is_full_endpoint = str(target["target_id"]) == "full_remaining_latent"
        control_regime_ac_reduction = (
            near_endpoint_ac_reduction_kw
            if is_full_endpoint
            else pd.to_numeric(frame["incremental_ac_power_reduction_kw"], errors="coerce")
        )
        frame["control_regime_conservative_ac_reduction_kw"] = (
            control_regime_ac_reduction
        )
        frame["control_regime_conservative_saving_kw_before_receiver_sink"] = (
            control_regime_ac_reduction - addon
        )
        frame[
            "control_regime_conservative_receiver_sink_sec_budget_kwh_per_kg"
        ] = (
            frame["control_regime_conservative_saving_kw_before_receiver_sink"]
            / water
        )
        receiver_surface = pd.to_numeric(
            frame["maximum_receiver_surface_activity"], errors="coerce"
        )
        frame["receiver_surface_activity_gate_pass"] = receiver_surface.le(
            float(sweep["maximum_receiver_surface_activity"])
        )
        frame["declared_transport_screen_pass"] = (
            bool_series(frame["transport_gate_pass"])
            & bool_series(frame["receiver_surface_activity_gate_pass"])
        )
        frame["positive_surface_direction_screen_pass"] = (
            bool_series(frame["declared_transport_screen_pass"])
            & bool_series(frame["positive_surface_direction_everywhere"])
        )
        frame["full_system_claim_allowed"] = False
        frame["receiver_capacity_axis_is_energy_rankable"] = False
        frame["receiver_capacity_related_fan_and_manifold_energy_modelled"] = False
        available_ratio = float(sweep["available_post_erv_exhaust_to_process_ratio"])
        receiver_ratio_values = pd.to_numeric(
            frame["receiver_to_process_dry_air_ratio"], errors="coerce"
        )
        frame["available_post_erv_exhaust_to_process_ratio"] = available_ratio
        frame["external_receiver_source_required_to_process_ratio"] = (
            receiver_ratio_values - available_ratio
        ).clip(lower=0.0)
        frame["receiver_resource_feasible_without_external_source"] = (
            receiver_ratio_values.le(available_ratio + 1.0e-12)
        )
        frame["external_receiver_source_energy_modelled"] = False
        frame["external_receiver_source_interpretation"] = str(
            sweep["external_receiver_source_interpretation"]
        )
        frame["receiver_capacity_axis_interpretation"] = str(
            sweep["receiver_capacity_axis_interpretation"]
        )
        all_frames.append(frame)
    return pd.concat(all_frames, ignore_index=True) if all_frames else pd.DataFrame()


TRANSPORT_DESIGN_COLUMNS = (
    "case_id",
    "target_id",
    "target_w_g_kg_da",
    "water_diffusivity_m2_s",
    "uniform_current_density_a_m2",
    "receiver_to_process_dry_air_ratio",
)


def transport_design_digest(design: pd.DataFrame) -> str:
    records = (
        design.loc[:, TRANSPORT_DESIGN_COLUMNS]
        .sort_values("case_id")
        .to_dict("records")
    )
    return sha256_json(records)


def validate_transport_frame_design(
    transport: pd.DataFrame,
    expected_design: pd.DataFrame,
) -> None:
    missing = [column for column in TRANSPORT_DESIGN_COLUMNS if column not in transport]
    if missing:
        raise StudyError(f"Transport table is missing design columns: {missing}")
    if transport["case_id"].astype(str).duplicated().any():
        raise StudyError("Transport table contains duplicate case IDs")
    actual_ids = set(transport["case_id"].astype(str))
    expected_ids = set(expected_design["case_id"].astype(str))
    if actual_ids != expected_ids:
        missing_ids = sorted(expected_ids - actual_ids)[:5]
        extra_ids = sorted(actual_ids - expected_ids)[:5]
        raise StudyError(
            "Transport case design does not match the selected config; "
            f"missing={missing_ids}, extra={extra_ids}, "
            f"expected_count={len(expected_ids)}, actual_count={len(actual_ids)}"
        )
    actual = transport.set_index(transport["case_id"].astype(str), drop=False)
    expected = expected_design.set_index(
        expected_design["case_id"].astype(str), drop=False
    )
    actual = actual.loc[expected.index]
    if not actual["target_id"].astype(str).eq(expected["target_id"].astype(str)).all():
        raise StudyError("Transport target IDs do not match the selected config")
    numeric_tolerances = {
        "target_w_g_kg_da": (1.0e-12, 1.0e-12),
        "water_diffusivity_m2_s": (1.0e-12, 0.0),
        "uniform_current_density_a_m2": (1.0e-12, 1.0e-12),
        "receiver_to_process_dry_air_ratio": (1.0e-12, 1.0e-12),
    }
    for column, (rtol, atol) in numeric_tolerances.items():
        actual_values = pd.to_numeric(actual[column], errors="coerce").to_numpy()
        expected_values = pd.to_numeric(expected[column], errors="coerce").to_numpy()
        if not np.isfinite(actual_values).all() or not np.allclose(
            actual_values, expected_values, rtol=rtol, atol=atol
        ):
            raise StudyError(
                f"Transport design column {column!r} does not match the selected config"
            )


def build_transport_contract(
    runtime: Mapping[str, Any],
    config: Mapping[str, Any],
    design: pd.DataFrame,
    transport_path: Path,
    *,
    config_path: Path,
    source_config_path: Path,
    analyzer_path: Path,
    mode: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "study_id": str(config["study_id"]),
        "transport_generator_version": SCRIPT_VERSION,
        "transport_generator_sha256": sha256_file(Path(__file__).resolve()),
        "mode": mode,
        "case_design_count": len(design),
        "case_design_sha256": transport_design_digest(design),
        "study_config_sha256": sha256_file(config_path),
        "source_operating_region_config_sha256": sha256_file(source_config_path),
        "transport_analyzer_sha256": sha256_file(analyzer_path),
        "transport_source_hashes": dict(runtime["source_hashes"]),
        "transport_csv": {
            "path": str(transport_path.resolve()),
            "sha256": sha256_file(transport_path),
        },
        "full_system_claim_allowed": False,
    }


def validate_transport_contract(
    contract_path: Path,
    runtime: Mapping[str, Any],
    config: Mapping[str, Any],
    design: pd.DataFrame,
    transport_path: Path,
    *,
    config_path: Path,
    source_config_path: Path,
    analyzer_path: Path,
    mode: str,
) -> dict[str, Any]:
    if not contract_path.is_file():
        raise StudyError(
            f"Postprocessing requires the transport provenance contract: {contract_path}"
        )
    if not transport_path.is_file():
        raise StudyError(f"Postprocessing requires {transport_path}")
    contract = read_json(contract_path)
    expected = {
        "schema_version": 1,
        "study_id": str(config["study_id"]),
        "transport_generator_version": SCRIPT_VERSION,
        "transport_generator_sha256": sha256_file(Path(__file__).resolve()),
        "mode": mode,
        "case_design_count": len(design),
        "case_design_sha256": transport_design_digest(design),
        "study_config_sha256": sha256_file(config_path),
        "source_operating_region_config_sha256": sha256_file(source_config_path),
        "transport_analyzer_sha256": sha256_file(analyzer_path),
        "transport_source_hashes": dict(runtime["source_hashes"]),
        "full_system_claim_allowed": False,
    }
    mismatches = [
        key for key, value in expected.items() if contract.get(key) != value
    ]
    transport_record = contract.get("transport_csv", {})
    if transport_record.get("sha256") != sha256_file(transport_path):
        mismatches.append("transport_csv.sha256")
    if mismatches:
        raise StudyError(
            "Existing transport output does not match the current study contract: "
            + ", ".join(mismatches)
        )
    return contract


def build_receiver_scenarios(
    transport: pd.DataFrame, config: Mapping[str, Any]
) -> pd.DataFrame:
    if transport.empty:
        return pd.DataFrame()
    sec_values = [
        float(value)
        for value in config["transport_sweep"]["receiver_and_sink_sec_kwh_per_kg"]
    ]
    rows: list[dict[str, Any]] = []
    reached = transport.loc[bool_series(transport["target_reached"])].copy()
    for case in reached.to_dict("records"):
        water = float(case["incremental_water_removal_target_kg_h"])
        conditional_total = float(case["conservative_erv_plus_eo_plus_ac_power_kw"])
        reference = float(case["passive_erv_plus_ac_reference_kw"])
        conservative_saving_before_receiver = float(
            case["control_regime_conservative_saving_kw_before_receiver_sink"]
        )
        for receiver_sec in sec_values:
            receiver_power = receiver_sec * water
            scenario_total = conditional_total + receiver_power
            saving = reference - scenario_total
            rows.append(
                {
                    "case_id": case["case_id"],
                    "target_id": case["target_id"],
                    "water_diffusivity_m2_s": case["water_diffusivity_m2_s"],
                    "uniform_current_density_a_m2": case[
                        "uniform_current_density_a_m2"
                    ],
                    "receiver_to_process_dry_air_ratio": case[
                        "receiver_to_process_dry_air_ratio"
                    ],
                    "required_active_area_m2": case["required_active_area_m2"],
                    "transport_gate_pass": bool(case["transport_gate_pass"]),
                    "positive_surface_direction_everywhere": bool(
                        case["positive_surface_direction_everywhere"]
                    ),
                    "receiver_and_sink_sec_kwh_per_kg": receiver_sec,
                    "receiver_and_sink_power_kw": receiver_power,
                    "scenario_total_power_kw": scenario_total,
                    "scenario_saving_kw_vs_erv_ac": saving,
                    "scenario_saving_pct_vs_erv_ac": 100.0 * saving / reference,
                    "scenario_energy_positive": bool(saving > 0.0),
                    "control_regime_conservative_scenario_saving_kw_vs_erv_ac": (
                        conservative_saving_before_receiver - receiver_power
                    ),
                    "control_regime_conservative_scenario_saving_pct_vs_erv_ac": (
                        100.0
                        * (conservative_saving_before_receiver - receiver_power)
                        / reference
                    ),
                    "control_regime_conservative_scenario_energy_positive": bool(
                        conservative_saving_before_receiver - receiver_power > 0.0
                    ),
                    "scenario_is_parameterized_not_validated": True,
                    "full_system_claim_allowed": False,
                }
            )
    return pd.DataFrame(rows)


def build_voltage_cap_scenarios(
    transport: pd.DataFrame, config: Mapping[str, Any]
) -> pd.DataFrame:
    if transport.empty:
        return pd.DataFrame()
    caps = [
        float(value)
        for value in config["transport_sweep"]["terminal_voltage_cap_sensitivity_v"]
    ]
    rows: list[dict[str, Any]] = []
    for case in transport.to_dict("records"):
        required = float(case["maximum_required_terminal_voltage_signed_v"])
        finite_required = math.isfinite(required)
        for cap in caps:
            rows.append(
                {
                    "case_id": case["case_id"],
                    "target_id": case["target_id"],
                    "water_diffusivity_m2_s": case["water_diffusivity_m2_s"],
                    "uniform_current_density_a_m2": case[
                        "uniform_current_density_a_m2"
                    ],
                    "receiver_to_process_dry_air_ratio": case[
                        "receiver_to_process_dry_air_ratio"
                    ],
                    "target_reached": bool(case["target_reached"]),
                    "declared_transport_screen_pass": bool(
                        case["declared_transport_screen_pass"]
                    ),
                    "required_maximum_terminal_voltage_v": (
                        required if finite_required else math.nan
                    ),
                    "terminal_voltage_cap_v": cap,
                    "terminal_voltage_cap_pass": bool(
                        finite_required and required <= cap + 1.0e-12
                    ),
                    "transport_and_voltage_cap_pass": bool(
                        case["declared_transport_screen_pass"]
                        and finite_required
                        and required <= cap + 1.0e-12
                    ),
                    "voltage_is_sensitivity_not_hidden_acceptance_gate": True,
                    "full_system_claim_allowed": False,
                }
            )
    return pd.DataFrame(rows)


def select_cases(transport: pd.DataFrame) -> pd.DataFrame:
    if transport.empty:
        return pd.DataFrame()
    reached = transport.loc[bool_series(transport["target_reached"])].copy()
    if reached.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for target_id, group in reached.groupby("target_id", sort=False):
        declared = group.loc[
            bool_series(group["declared_transport_screen_pass"])
        ].copy()
        candidates = declared.loc[
            bool_series(declared["receiver_resource_feasible_without_external_source"])
        ].copy()
        population = "declared_transport_screen_pass_and_declared_receiver_resource"
        if candidates.empty and not declared.empty:
            candidates = declared
            population = "declared_transport_screen_pass_external_resource_required"
        elif candidates.empty:
            candidates = group
            population = "target_reached_only"
        best_saving = candidates.sort_values(
            ["incremental_saving_kw_vs_passive_erv", "required_active_area_m2"],
            ascending=[False, True],
        ).iloc[0]
        minimum_area = candidates.sort_values(
            ["required_active_area_m2", "incremental_saving_kw_vs_passive_erv"],
            ascending=[True, False],
        ).iloc[0]
        for selection, row in (("best_conditional_saving", best_saving), ("minimum_area", minimum_area)):
            record = row.to_dict()
            record["selection"] = selection
            record["selection_population"] = population
            rows.append(record)
        if not declared.empty:
            capacity_best = declared.sort_values(
                ["incremental_saving_kw_vs_passive_erv", "required_active_area_m2"],
                ascending=[False, True],
            ).iloc[0]
            if str(capacity_best["case_id"]) != str(best_saving["case_id"]):
                record = capacity_best.to_dict()
                record["selection"] = "capacity_only_best_unrankable"
                record["selection_population"] = (
                    "declared_transport_screen_pass_including_unmodelled_external_receiver_resource"
                )
                rows.append(record)
    return pd.DataFrame(rows)


def build_step_halving_convergence(
    analyzer: ModuleType,
    base_runtime: Mapping[str, Any],
    targets: pd.DataFrame,
    selections: pd.DataFrame,
    config: Mapping[str, Any],
) -> pd.DataFrame:
    if selections.empty:
        return pd.DataFrame()
    target_w_by_id = targets.set_index("target_id")["target_w_kg_kg_da"].to_dict()
    sweep = config["transport_sweep"]
    nominal_step = float(sweep["area_step_m2"])
    refined_step = nominal_step / 2.0
    tolerance = float(sweep["step_halving_relative_area_tolerance"])
    material_keys = (
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
    rows: list[dict[str, Any]] = []
    unique = selections.drop_duplicates("case_id")
    for nominal in unique.to_dict("records"):
        target_id = str(nominal["target_id"])
        runtime = dict(base_runtime)
        runtime["target_w"] = float(target_w_by_id[target_id])
        runtime["area_limit_m2"] = float(sweep["area_observation_cap_m2"])
        runtime["area_step_m2"] = refined_step
        case = {key: float(nominal[key]) for key in material_keys}
        case.update(
            {
                "study_family": "step_halving_convergence",
                "case_id": f"{nominal['case_id']}__step_halved",
                "uniform_current_density_a_m2": float(
                    nominal["uniform_current_density_a_m2"]
                ),
                "receiver_to_process_dry_air_ratio": float(
                    nominal["receiver_to_process_dry_air_ratio"]
                ),
            }
        )
        refined = analyzer.integrate_case(runtime, case)
        nominal_area = float(nominal["required_active_area_m2"])
        refined_area = float(refined["required_active_area_m2"])
        absolute_difference = abs(refined_area - nominal_area)
        relative_difference = absolute_difference / max(abs(refined_area), 1.0e-12)
        rows.append(
            {
                "source_case_id": nominal["case_id"],
                "target_id": target_id,
                "nominal_area_step_m2": nominal_step,
                "refined_area_step_m2": refined_step,
                "nominal_required_active_area_m2": nominal_area,
                "refined_required_active_area_m2": refined_area,
                "absolute_area_difference_m2": absolute_difference,
                "relative_area_difference": relative_difference,
                "relative_area_tolerance": tolerance,
                "nominal_saving_kw": float(
                    nominal["incremental_saving_kw_vs_passive_erv"]
                ),
                "refined_saving_kw": float(
                    refined["incremental_saving_kw_vs_passive_erv"]
                ),
                "refined_target_reached": bool(refined["target_reached"]),
                "refined_water_balance_relative_error": float(
                    refined["water_balance_relative_error"]
                ),
                "refined_receiver_balance_relative_error": float(
                    refined["receiver_water_balance_relative_error"]
                ),
                "step_halving_convergence_pass": bool(
                    refined["target_reached"]
                    and relative_difference <= tolerance
                    and abs(float(refined["water_balance_relative_error"])) <= 1.0e-8
                    and abs(float(refined["receiver_water_balance_relative_error"]))
                    <= 1.0e-8
                ),
            }
        )
    return pd.DataFrame(rows)


def build_selected_power_ledger(
    runtime: Mapping[str, Any],
    selections: pd.DataFrame,
    endpoint_audit: pd.DataFrame,
) -> pd.DataFrame:
    if selections.empty:
        return pd.DataFrame()
    baseline = runtime["baseline"]
    near_endpoint = endpoint_audit.loc[
        endpoint_audit["humidity_offset_above_supply_g_kg_da"] > 0.0
    ].sort_values("humidity_offset_above_supply_g_kg_da").iloc[0]
    missing = (
        "receiver_regeneration_or_disposal;receiver_heat_rejection;"
        "external_receiver_resource_if_required;conjugate_thermal_feedback;"
        "rankable_manifold_and_controls"
    )
    rows: list[dict[str, Any]] = []
    for selected in selections.to_dict("records"):
        branches = [
            (
                "native_or_exact_endpoint_screen",
                float(selected["remaining_ac_power_kw"]),
            )
        ]
        if str(selected["target_id"]) == "full_remaining_latent":
            branches.append(
                (
                    "conservative_near_endpoint_control",
                    float(near_endpoint["remaining_ac_power_kw_at_zero_eo_sec"]),
                )
            )
        for branch, remaining_ac_kw in branches:
            erv_kw = float(baseline.passive_erv.total_power_kw)
            eo_kw = float(selected["eo_grid_import_kw_no_export_credit"])
            process_fan_kw = float(selected["process_channel_fan_power_kw"])
            receiver_fan_kw = float(selected["receiver_channel_fan_power_kw"])
            known_total = erv_kw + remaining_ac_kw + eo_kw + process_fan_kw + receiver_fan_kw
            reference = float(baseline.total_power_kw)
            rows.append(
                {
                    "case_id": selected["case_id"],
                    "target_id": selected["target_id"],
                    "selection": selected["selection"],
                    "comparison_branch": branch,
                    "reference_erv_plus_ac_power_kw": reference,
                    "passive_erv_power_kw": erv_kw,
                    "remaining_ac_power_kw": remaining_ac_kw,
                    "eo_grid_import_kw": eo_kw,
                    "process_channel_fan_power_kw": process_fan_kw,
                    "receiver_channel_fan_power_kw": receiver_fan_kw,
                    "known_subtotal_power_kw": known_total,
                    "conditional_saving_before_missing_power_kw": reference - known_total,
                    "receiver_regeneration_or_disposal_power_kw": math.nan,
                    "receiver_heat_rejection_power_kw": math.nan,
                    "external_receiver_resource_power_kw": math.nan,
                    "other_missing_components": missing,
                    "power_ledger_complete": False,
                    "full_system_claim_allowed": False,
                }
            )
    return pd.DataFrame(rows)


def plot_energy_window(frame: pd.DataFrame, output: Path) -> None:
    subset = frame.loc[np.isclose(frame["process_heat_leak_fraction"], 0.0)].copy()
    fig, ax = plt.subplots(figsize=(9.0, 5.8))
    for target_id, group in subset.groupby("target_id", sort=False):
        group = group.sort_values("all_in_eo_sec_kwh_per_kg")
        ax.plot(
            group["all_in_eo_sec_kwh_per_kg"],
            group["net_saving_kw_vs_erv_ac"],
            marker="o",
            label=str(target_id),
        )
    ax.axhline(0.0, color="black", linewidth=1.0)
    ax.set_xlabel("All-in EO SEC [kWh/kg water]")
    ax.set_ylabel("Conditional saving vs passive ERV + AC [kW]")
    ax.set_title("ERV first, EO carries the selected remaining latent duty")
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output, dpi=180)
    plt.close(fig)


def plot_transport_area(frame: pd.DataFrame, anchor_d: float, output: Path) -> None:
    resource_feasible = (
        bool_series(frame["receiver_resource_feasible_without_external_source"])
        if "receiver_resource_feasible_without_external_source" in frame.columns
        else pd.Series(True, index=frame.index)
    )
    reached = frame.loc[
        bool_series(frame["target_reached"])
        & resource_feasible
        & np.isclose(
            pd.to_numeric(frame["water_diffusivity_m2_s"], errors="coerce"),
            anchor_d,
            rtol=1.0e-10,
            atol=0.0,
        )
    ].copy()
    fig, ax = plt.subplots(figsize=(9.0, 5.8))
    for target_id, group in reached.groupby("target_id", sort=False):
        group = group.sort_values("uniform_current_density_a_m2")
        ax.plot(
            group["uniform_current_density_a_m2"],
            group["required_active_area_m2"],
            marker="o",
            label=str(target_id),
        )
    ax.set_xlabel("Uniform current-density sampling coordinate [A/m²]")
    ax.set_ylabel("Observed target-reaching active area [m²]")
    ax.set_title(
        "Terminal-1 anchor: area with the available balanced ERV receiver flow"
    )
    ax.grid(alpha=0.25)
    if not reached.empty:
        ax.legend()
    fig.tight_layout()
    fig.savefig(output, dpi=180)
    plt.close(fig)


def plot_receiver_budget(
    scenarios: pd.DataFrame, selections: pd.DataFrame, output: Path
) -> None:
    fig, ax = plt.subplots(figsize=(9.0, 5.8))
    if not scenarios.empty and not selections.empty:
        selected_ids = set(
            selections.loc[
                selections["selection"].eq("best_conditional_saving"), "case_id"
            ].astype(str)
        )
        subset = scenarios.loc[scenarios["case_id"].astype(str).isin(selected_ids)]
        for target_id, group in subset.groupby("target_id", sort=False):
            group = group.sort_values("receiver_and_sink_sec_kwh_per_kg")
            ax.plot(
                group["receiver_and_sink_sec_kwh_per_kg"],
                group["control_regime_conservative_scenario_saving_kw_vs_erv_ac"],
                marker="o",
                label=str(target_id),
            )
    ax.axhline(0.0, color="black", linewidth=1.0)
    ax.set_xlabel("Added receiver + sink SEC [kWh/kg water]")
    ax.set_ylabel("Conservative near-endpoint saving vs passive ERV + AC [kW]")
    ax.set_title("Receiver/sink budget using the conservative HVAC control branch")
    ax.grid(alpha=0.25)
    if ax.lines:
        ax.legend()
    fig.tight_layout()
    fig.savefig(output, dpi=180)
    plt.close(fig)


def finite_max_abs(series: pd.Series) -> float | None:
    values = pd.to_numeric(series, errors="coerce").dropna()
    return float(values.abs().max()) if not values.empty else None


def build_summary(
    runtime: Mapping[str, Any],
    targets: pd.DataFrame,
    break_even: pd.DataFrame,
    transport: pd.DataFrame,
    selections: pd.DataFrame,
    endpoint_audit: pd.DataFrame,
    convergence: pd.DataFrame,
    *,
    mode: str,
) -> str:
    baseline = runtime["baseline"]
    lines = [
        "# ERV first, EO for the full remaining dehumidification duty",
        "",
        f"Mode: `{mode}`.",
        "",
        "## Reference boundary",
        "",
        f"- Passive ERV outlet: {float(runtime['process_in'].t_c):.2f} °C and {1000.0 * float(runtime['process_in'].w):.3f} g/kg dry air.",
        f"- Equal-service passive ERV + AC reference: {float(baseline.total_power_kw):.3f} kW.",
        f"- Remaining AC after ERV: {float(baseline.remaining_ac.total_ac_power_kw):.3f} kW.",
        "- O50 already has no post-ERV EO duty on an absolute-humidity basis.",
        "",
        "## Energy-window result",
        "",
    ]
    zero_heat = break_even.loc[np.isclose(break_even["process_heat_leak_fraction"], 0.0)]
    for row in zero_heat.to_dict("records"):
        lines.append(
            f"- `{row['target_id']}`: {float(row['eo_water_removal_kg_h']):.2f} kg/h EO duty; "
            f"break-even all-in EO SEC {float(row['break_even_all_in_eo_sec_kwh_per_kg']):.4f} kWh/kg."
        )
    full_break = break_even.loc[break_even["target_id"].eq("full_remaining_latent")]
    if not full_break.empty:
        lines.extend(["", "Full remaining latent-duty sensitivity:"])
        for row in full_break.sort_values("process_heat_leak_fraction").to_dict("records"):
            lines.append(
                f"- Process heat fraction {100.0 * float(row['process_heat_leak_fraction']):.0f}%: "
                f"break-even {float(row['break_even_all_in_eo_sec_kwh_per_kg']):.4f} kWh/kg."
            )
    exact_endpoint = endpoint_audit.loc[
        np.isclose(endpoint_audit["humidity_offset_above_supply_g_kg_da"], 0.0)
    ].iloc[0]
    near_endpoint = endpoint_audit.loc[
        endpoint_audit["humidity_offset_above_supply_g_kg_da"] > 0.0
    ].sort_values("humidity_offset_above_supply_g_kg_da").iloc[0]
    lines.extend(
        [
            "",
            "### Endpoint/control-regime warning",
            "",
            f"- Exact supply-humidity endpoint: {float(exact_endpoint['break_even_all_in_eo_sec_kwh_per_kg']):.4f} kWh/kg and a sensible-only remaining coil.",
            f"- Infinitesimally above that endpoint: {float(near_endpoint['break_even_all_in_eo_sec_kwh_per_kg']):.4f} kWh/kg because the screening coil returns to its saturated-coil latent-control branch.",
            "- Use the lower near-endpoint budget for conservative decisions until a real coil/control sequence validates the ideal endpoint transition.",
        ]
    )
    lines.extend(["", "## Finite-film membrane sweep", ""])
    if transport.empty:
        lines.append("Transport was not run (`--energy-only`).")
    else:
        reached = bool_series(transport["target_reached"])
        passed = bool_series(transport["declared_transport_screen_pass"])
        positive_surface = bool_series(
            transport["positive_surface_direction_screen_pass"]
        )
        lines.append(
            f"- {int(reached.sum())}/{len(transport)} cases reached their numerical target; "
            f"{int(passed.sum())} passed the transport and receiver-surface gates, and "
            f"{int(positive_surface.sum())} also retained positive surface direction everywhere."
        )
        primary_selections = selections.loc[
            selections["selection"].eq("best_conditional_saving")
        ].set_index("target_id")
        for target_id, group in transport.groupby("target_id", sort=False):
            group_reached = group.loc[bool_series(group["target_reached"])]
            if group_reached.empty:
                lines.append(f"- `{target_id}`: no tested case reached target within the area cap.")
                continue
            best = primary_selections.loc[target_id]
            prefix = (
                f"- `{target_id}`: best target-reaching conditional row uses "
                f"{float(best['required_active_area_m2']):.1f} m² at "
                f"{float(best['uniform_current_density_a_m2']):.1f} A/m² and receiver/process "
                f"dry-air ratio {float(best['receiver_to_process_dry_air_ratio']):.2f}."
            )
            voltage_text = (
                f" Required maximum terminal voltage is {float(best['maximum_required_terminal_voltage_signed_v']):.3f} V "
                f"(1 V sensitivity: {'pass' if float(best['maximum_required_terminal_voltage_signed_v']) <= 1.0 else 'fail'}; "
                f"2 V sensitivity: {'pass' if float(best['maximum_required_terminal_voltage_signed_v']) <= 2.0 else 'fail'})."
            )
            if target_id == "full_remaining_latent":
                lines.append(
                    prefix
                    + f" Saving before receiver/sink energy is {float(best['incremental_saving_kw_vs_passive_erv']):.2f} kW "
                    + f"on the ideal exact-endpoint branch and {float(best['control_regime_conservative_saving_kw_before_receiver_sink']):.2f} kW "
                    + "on the conservative near-endpoint branch."
                    + voltage_text
                )
            else:
                lines.append(
                    prefix
                    + f" Conditional saving before receiver/sink energy is {float(best['incremental_saving_kw_vs_passive_erv']):.2f} kW."
                    + voltage_text
                )
            capacity_only = selections.loc[
                selections["target_id"].eq(target_id)
                & selections["selection"].eq("capacity_only_best_unrankable")
            ]
            if not capacity_only.empty:
                row = capacity_only.iloc[0]
                lines.append(
                    f"  Capacity-only diagnostic reaches {float(row['incremental_saving_kw_vs_passive_erv']):.2f} kW at receiver ratio "
                    f"{float(row['receiver_to_process_dry_air_ratio']):.2f}, but requires unmodelled external receiver air and is not the primary selection."
                )
        if not convergence.empty:
            lines.append(
                f"- Step-halving audit: {int(convergence['step_halving_convergence_pass'].sum())}/{len(convergence)} selected unique cases passed."
            )
    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "The all-in SEC window is the decision budget; the finite-film sweep estimates only known EO core and idealized module-fan terms. Receiver regeneration/disposal, heat rejection, conjugate thermal feedback, rankable manifolds, electrodes and durability remain unresolved or parameterized.",
            "",
            "Receiver/process dry-air ratio is varied only as a capacity sensitivity. Film coefficients and the released fan law are frozen, so extra receiver-flow fan/manifold energy is not included and cases must not be ranked across that axis as complete designs.",
            "",
            "Ratios above 1.0 require external receiver air in addition to the balanced ERV exhaust. That resource and its conditioning/disposal energy are not included.",
            "",
            "**No row is a validated full-system saving claim. Current density is a sampling coordinate, not an acceptance limit.**",
            "",
            "## Reproduction",
            "",
            "```bash",
            "python3 -B scripts/make_post_erv_full_eo_study_v1.py --energy-only --output-dir outputs/post_erv_full_eo_energy_only_v1 --overwrite",
            "python3 -B scripts/make_post_erv_full_eo_study_v1.py --smoke --jobs 4 --output-dir outputs/post_erv_full_eo_smoke_v1 --overwrite",
            "python3 -B scripts/make_post_erv_full_eo_study_v1.py --jobs 8 --output-dir outputs/post_erv_full_eo_study_v1 --overwrite",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def build_audit(
    runtime: Mapping[str, Any],
    config: Mapping[str, Any],
    targets: pd.DataFrame,
    energy: pd.DataFrame,
    break_even: pd.DataFrame,
    transport: pd.DataFrame,
    endpoint_audit: pd.DataFrame,
    convergence: pd.DataFrame,
    transport_contract_validated: bool,
    *,
    config_path: Path,
    source_config_path: Path,
    analyzer_path: Path,
    mode: str,
) -> dict[str, Any]:
    expected = config["reference_audit"]
    rel_tol = float(expected["relative_tolerance"])
    baseline = runtime["baseline"]
    supply_w = float(baseline.remaining_ac.supply.w)
    full_target = targets.loc[targets["target_id"].eq("full_remaining_latent")]
    full_break = break_even.loc[
        break_even["target_id"].eq("full_remaining_latent")
        & np.isclose(break_even["process_heat_leak_fraction"], 0.0)
    ]
    full_water = (
        float(full_break.iloc[0]["eo_water_removal_kg_h"])
        if len(full_break) == 1
        else math.nan
    )
    full_break_even = (
        float(full_break.iloc[0]["break_even_all_in_eo_sec_kwh_per_kg"])
        if len(full_break) == 1
        else math.nan
    )
    near_endpoint = endpoint_audit.loc[
        endpoint_audit["humidity_offset_above_supply_g_kg_da"] > 0.0
    ].sort_values("humidity_offset_above_supply_g_kg_da")
    near_endpoint_break_even = (
        float(near_endpoint.iloc[0]["break_even_all_in_eo_sec_kwh_per_kg"])
        if not near_endpoint.empty
        else math.nan
    )
    reference_checks = {
        "post_erv_temperature": math.isclose(
            float(runtime["process_in"].t_c),
            float(expected["expected_post_erv_temperature_c"]),
            rel_tol=rel_tol,
            abs_tol=1.0e-10,
        ),
        "post_erv_humidity": math.isclose(
            float(runtime["process_in"].w),
            float(expected["expected_post_erv_humidity_ratio_kg_kg_da"]),
            rel_tol=rel_tol,
            abs_tol=1.0e-12,
        ),
        "supply_humidity": math.isclose(
            supply_w,
            float(expected["expected_supply_humidity_ratio_kg_kg_da"]),
            rel_tol=rel_tol,
            abs_tol=1.0e-12,
        ),
        "process_mass_flow": math.isclose(
            float(runtime["dry_air_mass_flow_kg_s"]),
            float(expected["expected_process_dry_air_mass_flow_kg_s"]),
            rel_tol=rel_tol,
        ),
        "passive_erv_power": math.isclose(
            float(baseline.passive_erv.total_power_kw),
            float(expected["expected_passive_erv_power_kw"]),
            rel_tol=rel_tol,
        ),
        "remaining_ac_power": math.isclose(
            float(baseline.remaining_ac.total_ac_power_kw),
            float(expected["expected_remaining_ac_power_kw"]),
            rel_tol=rel_tol,
        ),
        "reference_total_power": math.isclose(
            float(baseline.total_power_kw),
            float(expected["expected_passive_erv_plus_ac_power_kw"]),
            rel_tol=rel_tol,
        ),
        "full_remaining_water_duty": math.isclose(
            full_water,
            float(expected["expected_full_remaining_water_duty_kg_h"]),
            rel_tol=rel_tol,
        ),
        "full_remaining_break_even": math.isclose(
            full_break_even,
            float(expected["expected_full_remaining_zero_heat_break_even_sec_kwh_per_kg"]),
            rel_tol=rel_tol,
        ),
        "full_target_equals_supply_humidity": bool(
            len(full_target) == 1
            and math.isclose(
                float(full_target.iloc[0]["target_w_kg_kg_da"]),
                supply_w,
                rel_tol=rel_tol,
                abs_tol=1.0e-12,
            )
        ),
        "near_endpoint_conservative_break_even": math.isclose(
            near_endpoint_break_even,
            float(expected["expected_near_endpoint_break_even_sec_kwh_per_kg"]),
            rel_tol=rel_tol,
        ),
        "endpoint_control_regime_switch_exposed": bool(
            endpoint_audit["remaining_ac_is_sensible_only"].sum() == 1
            and endpoint_audit.iloc[0]["remaining_ac_is_sensible_only"]
            and (~endpoint_audit.iloc[1:]["remaining_ac_is_sensible_only"]).all()
        ),
    }
    energy_identity_max = finite_max_abs(energy["energy_identity_error_kw"])
    transport_exception_count = 0
    transport_water_balance_max: float | None = None
    transport_receiver_balance_max: float | None = None
    transport_full_unknown = True
    if not transport.empty:
        transport_exception_count = int(
            transport["status"].astype(str).str.startswith("exception:").sum()
        )
        reached = bool_series(transport["target_reached"])
        transport_water_balance_max = finite_max_abs(
            transport.loc[reached, "water_balance_relative_error"]
        )
        transport_receiver_balance_max = finite_max_abs(
            transport.loc[reached, "receiver_water_balance_relative_error"]
        )
        transport_full_unknown = bool(
            transport["full_system_status"].eq("UNKNOWN").all()
            and (~bool_series(transport["full_system_claim_allowed"])).all()
        )
    convergence_pass = bool(
        convergence.empty or bool_series(convergence["step_halving_convergence_pass"]).all()
    )
    audit_pass = bool(
        all(reference_checks.values())
        and energy_identity_max is not None
        and energy_identity_max <= 1.0e-8
        and transport_exception_count == 0
        and (transport_water_balance_max is None or transport_water_balance_max <= 1.0e-8)
        and (transport_receiver_balance_max is None or transport_receiver_balance_max <= 1.0e-8)
        and transport_full_unknown
        and convergence_pass
        and (transport.empty or transport_contract_validated)
        and config["claim_policy"]["full_system_claim_allowed"] is False
    )
    return {
        "script_version": SCRIPT_VERSION,
        "study_id": config["study_id"],
        "mode": mode,
        "pass": audit_pass,
        "reference_checks": reference_checks,
        "energy_case_count": len(energy),
        "break_even_case_count": len(break_even),
        "endpoint_control_audit_case_count": len(endpoint_audit),
        "step_halving_case_count": len(convergence),
        "step_halving_convergence_pass": convergence_pass,
        "energy_identity_max_abs_kw": energy_identity_max,
        "transport_case_count": len(transport),
        "transport_contract_required": not transport.empty,
        "transport_contract_validated": bool(
            not transport.empty and transport_contract_validated
        ),
        "transport_exception_count": transport_exception_count,
        "transport_target_reached_count": (
            int(bool_series(transport["target_reached"]).sum())
            if not transport.empty
            else 0
        ),
        "transport_gate_pass_count": (
            int(bool_series(transport["declared_transport_screen_pass"]).sum())
            if not transport.empty
            else 0
        ),
        "positive_surface_direction_screen_pass_count": (
            int(bool_series(transport["positive_surface_direction_screen_pass"]).sum())
            if not transport.empty
            else 0
        ),
        "one_volt_transport_screen_pass_count": (
            int(
                (
                    bool_series(transport["declared_transport_screen_pass"])
                    & pd.to_numeric(
                        transport["maximum_required_terminal_voltage_signed_v"],
                        errors="coerce",
                    ).le(1.0 + 1.0e-12)
                ).sum()
            )
            if not transport.empty
            else 0
        ),
        "two_volt_transport_screen_pass_count": (
            int(
                (
                    bool_series(transport["declared_transport_screen_pass"])
                    & pd.to_numeric(
                        transport["maximum_required_terminal_voltage_signed_v"],
                        errors="coerce",
                    ).le(2.0 + 1.0e-12)
                ).sum()
            )
            if not transport.empty
            else 0
        ),
        "transport_water_balance_max_abs": transport_water_balance_max,
        "transport_receiver_balance_max_abs": transport_receiver_balance_max,
        "full_system_status_unknown_everywhere": transport_full_unknown,
        "full_system_claim_allowed": False,
        "engineering_current_density_limit_a_m2": None,
        "current_density_is_sampling_coordinate": True,
        "provenance": {
            "study_script": {
                "path": str(Path(__file__).resolve()),
                "sha256": sha256_file(Path(__file__).resolve()),
            },
            "study_config": {
                "path": str(config_path.resolve()),
                "sha256": sha256_file(config_path),
            },
            "source_operating_region_config": {
                "path": str(source_config_path),
                "sha256": sha256_file(source_config_path),
            },
            "transport_analyzer": {
                "path": str(analyzer_path),
                "sha256": sha256_file(analyzer_path),
            },
            "transport_source_hashes": runtime["source_hashes"],
        },
    }


def main() -> None:
    args = parse_args()
    if args.energy_only and args.postprocess_existing:
        raise StudyError("--energy-only and --postprocess-existing are mutually exclusive")
    config_path = args.config.expanduser().resolve()
    config = read_json(config_path)
    default_suffix = "_smoke" if args.smoke else ("_energy_only" if args.energy_only else "")
    output = (
        args.output_dir.expanduser().resolve()
        if args.output_dir is not None
        else (DEFAULT_OUTPUT.parent / (DEFAULT_OUTPUT.name + default_suffix))
    )
    validate_output_mode(output, energy_only=bool(args.energy_only))
    validate_output_directory(output, args.overwrite)
    area_step = float(config["transport_sweep"]["area_step_m2"])
    analyzer, runtime, source_config, source_config_path, analyzer_path = load_runtime(
        config,
        v2_root=args.v2_root.expanduser().resolve(),
        area_step_m2=area_step,
    )
    targets = target_table(config, float(runtime["process_in"].w))
    mode = "energy_only" if args.energy_only else ("smoke" if args.smoke else "study")
    design = (
        pd.DataFrame()
        if args.energy_only
        else build_transport_case_design(targets, config, smoke=bool(args.smoke))
    )
    energy, break_even = build_energy_window(runtime, targets, config)
    endpoint_audit = build_endpoint_control_audit(runtime, config)
    transport = pd.DataFrame()
    transport_contract_validated = False
    transport_path = output / "transport_cases.csv"
    contract_path = output / "transport_contract.json"
    if args.postprocess_existing:
        validate_transport_contract(
            contract_path,
            runtime,
            config,
            design,
            transport_path,
            config_path=config_path,
            source_config_path=source_config_path,
            analyzer_path=analyzer_path,
            mode=mode,
        )
        transport = pd.read_csv(transport_path, low_memory=False)
        validate_transport_frame_design(transport, design)
        transport_contract_validated = True
    elif not args.energy_only:
        transport = transport_cases(
            analyzer,
            runtime,
            targets,
            config,
            jobs=max(1, int(args.jobs)),
            smoke=bool(args.smoke),
        )
        validate_transport_frame_design(transport, design)
    scenarios = build_receiver_scenarios(transport, config)
    voltage_scenarios = build_voltage_cap_scenarios(transport, config)
    selections = select_cases(transport)
    convergence = build_step_halving_convergence(
        analyzer, runtime, targets, selections, config
    )
    power_ledger = build_selected_power_ledger(runtime, selections, endpoint_audit)

    targets.to_csv(output / "target_coordinates.csv", index=False)
    energy.to_csv(output / "energy_window.csv", index=False)
    break_even.to_csv(output / "break_even_by_target.csv", index=False)
    endpoint_audit.to_csv(output / "endpoint_control_regime_audit.csv", index=False)
    if not transport.empty:
        if not args.postprocess_existing:
            transport.to_csv(transport_path, index=False)
            contract = build_transport_contract(
                runtime,
                config,
                design,
                transport_path,
                config_path=config_path,
                source_config_path=source_config_path,
                analyzer_path=analyzer_path,
                mode=mode,
            )
            write_json(contract_path, contract)
            validate_transport_contract(
                contract_path,
                runtime,
                config,
                design,
                transport_path,
                config_path=config_path,
                source_config_path=source_config_path,
                analyzer_path=analyzer_path,
                mode=mode,
            )
            transport_contract_validated = True
        scenarios.to_csv(output / "receiver_and_sink_sec_scenarios.csv", index=False)
        voltage_scenarios.to_csv(output / "terminal_voltage_cap_scenarios.csv", index=False)
        selections.to_csv(output / "selected_transport_cases.csv", index=False)
        convergence.to_csv(output / "step_halving_convergence.csv", index=False)
        power_ledger.to_csv(output / "selected_power_ledger.csv", index=False)
    write_json(output / "config_used.json", config)
    plot_energy_window(energy, output / "energy_window.png")
    if not transport.empty:
        plot_transport_area(
            transport,
            float(config["transport_sweep"]["water_diffusivity_m2_s"][0]),
            output / "transport_area_vs_current.png",
        )
        plot_receiver_budget(
            scenarios, selections, output / "receiver_and_sink_budget.png"
        )
    summary = build_summary(
        runtime,
        targets,
        break_even,
        transport,
        selections,
        endpoint_audit,
        convergence,
        mode=mode,
    )
    (output / "SUMMARY.md").write_text(summary, encoding="utf-8")
    audit = build_audit(
        runtime,
        config,
        targets,
        energy,
        break_even,
        transport,
        endpoint_audit,
        convergence,
        transport_contract_validated,
        config_path=config_path,
        source_config_path=source_config_path,
        analyzer_path=analyzer_path,
        mode=mode,
    )
    write_json(output / "audit.json", audit)
    if not audit["pass"]:
        raise StudyError(f"Study audit failed; inspect {output / 'audit.json'}")
    print(f"Wrote {mode} study to {output}")
    print(
        "Full-remaining zero-heat break-even SEC:",
        f"{float(break_even.loc[(break_even['target_id'] == 'full_remaining_latent') & np.isclose(break_even['process_heat_leak_fraction'], 0.0), 'break_even_all_in_eo_sec_kwh_per_kg'].iloc[0]):.6f} kWh/kg",
    )


if __name__ == "__main__":
    main()
