#!/usr/bin/env python3
"""Run the native reduced-order direct active EO-assisted ERV study.

The same balanced building-return stream is both the heat-recovery stream and
the EO water receiver.  The runner uses absolute cell terminal voltages no
higher than 2 V and applies no current-density acceptance limit.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

os.environ.setdefault("MPLCONFIGDIR", "/tmp/heiq-direct-active-erv-mpl")

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from heiq.wp1.engineering.stack import stack_topology
from heiq.wp1.membrane.local_transport import legacy_v2_module
from heiq.wp1.membrane.thermodynamics import audit_local_record
from heiq.wp1.studies.active_erv import (
    ActiveEndpoints,
    active_core_hydraulics,
    build_active_endpoints,
    build_passive_baseline,
    solve_coil,
    solve_segmented_transport,
    states_from_config,
)


SCRIPT_VERSION = "direct-active-eo-erv-study-v1.2-2026-08-31"
DEFAULT_CONFIG = ROOT / "config" / "direct_active_eo_erv_study_v1.json"
DEFAULT_OUTPUT = ROOT / "outputs" / "direct_active_eo_erv_study_v1"
ACTIVE_MODULE = ROOT / "src" / "heiq" / "wp1" / "studies" / "active_erv.py"
LOCAL_STATE_MODULE = ROOT / "src" / "heiq" / "wp1" / "axial" / "local_state.py"
THERMODYNAMICS_MODULE = (
    ROOT / "src" / "heiq" / "wp1" / "membrane" / "thermodynamics.py"
)
V2_MODEL = ROOT / "heiq_pre_receiver_material_analyses" / "heiq_pre_receiver_model.py"
V2_CONFIG = ROOT / "heiq_pre_receiver_material_analyses" / "config" / "default.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--mode",
        choices=("smoke", "study", "sensitivity", "nafion_sensitivity"),
        default="smoke",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow known study outputs in an existing mode directory to be replaced.",
    )
    return parser.parse_args()


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
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


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(_json_safe(dict(payload)), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _file_record(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    return {
        "path": str(resolved),
        "sha256": _sha256(resolved),
        "size_bytes": resolved.stat().st_size,
    }


def load_config(path: Path) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    if config.get("schema_version") != 1:
        raise ValueError("Unsupported direct active-ERV study config schema")
    architecture = config["architecture"]
    if architecture.get("id") != "shared_core_same_stream":
        raise ValueError("Architecture id must be shared_core_same_stream")
    if architecture.get("same_exhaust_stream_used_once") is not True:
        raise ValueError("The shared-core exhaust identity must be explicit")
    if architecture.get("separate_receiver_loop") is not False:
        raise ValueError("A separate receiver loop is outside this study boundary")
    if architecture.get("receiver_regeneration_required") is not False:
        raise ValueError("Receiver regeneration contradicts the shared exhaust core")
    if not math.isclose(
        float(architecture.get("external_receiver_mass_flow_kg_s", math.nan)),
        0.0,
        rel_tol=0.0,
        abs_tol=1.0e-12,
    ):
        raise ValueError("External receiver flow contradicts the shared exhaust core")
    if not math.isclose(
        float(config["boundary"]["available_exhaust_to_process_ratio"]),
        1.0,
        rel_tol=0.0,
        abs_tol=1.0e-12,
    ):
        raise ValueError("This study requires balanced process and exhaust dry-air flow")
    electrical = config["electrical"]
    if float(electrical["maximum_terminal_voltage_v"]) > 2.0:
        raise ValueError("Terminal voltage acceptance above 2 V is forbidden")
    if electrical.get("engineering_current_density_limit_a_m2") is not None:
        raise ValueError("Current-density acceptance gates are forbidden")
    if config["claim_boundary"].get("full_system_claim_allowed") is not False:
        raise ValueError("This reduced-order study cannot enable a full-system claim")
    if config["solver"].get("area_is_acceptance_gate") is not False:
        raise ValueError(
            "Direct active-ERV area must remain a diagnostic, not an acceptance gate"
        )
    for mode, scenario in config["modes"].items():
        voltages = [float(value) for value in scenario["terminal_voltages_v"]]
        if not voltages or min(voltages) <= 0.0:
            raise ValueError(f"Mode {mode!r} has a nonpositive voltage")
        if max(voltages) > float(electrical["maximum_terminal_voltage_v"]):
            raise ValueError(f"Mode {mode!r} exceeds the terminal-voltage cap")
        missing = set(scenario["material_ids"]) - set(config["materials"])
        if missing:
            raise KeyError(f"Mode {mode!r} names unknown materials: {sorted(missing)}")
        missing_heat = set(scenario["electric_heat_scenario_ids"]) - set(
            config["electric_heat_scenarios"]
        )
        if missing_heat:
            raise KeyError(
                f"Mode {mode!r} names unknown heat scenarios: {sorted(missing_heat)}"
            )
    return config


def make_case_specs(config: Mapping[str, Any], mode: str) -> list[dict[str, Any]]:
    scenario = config["modes"][mode]
    specs: list[dict[str, Any]] = []
    product = itertools.product(
        scenario["material_ids"],
        scenario["process_outlet_w_g_kg_da"],
        scenario["terminal_voltages_v"],
        scenario["segment_counts"],
        scenario["sensible_effectiveness_values"],
        scenario["film_scale_factors"],
        scenario["electric_heat_scenario_ids"],
    )
    for case_index, values in enumerate(product, start=1):
        (
            material_id,
            target,
            voltage,
            segment_count,
            sensible,
            film_scale,
            heat_id,
        ) = values
        specs.append(
            {
                "case_index": case_index,
                "material_id": str(material_id),
                "process_outlet_w_g_kg_da": float(target),
                "terminal_voltage_v": float(voltage),
                "segment_count": int(segment_count),
                "sensible_effectiveness": float(sensible),
                "film_scale_factor": float(film_scale),
                "electric_heat_scenario_id": str(heat_id),
            }
        )
    return specs


def expected_case_count(config: Mapping[str, Any], mode: str) -> int:
    scenario = config["modes"][mode]
    keys = (
        "material_ids",
        "process_outlet_w_g_kg_da",
        "terminal_voltages_v",
        "segment_counts",
        "sensible_effectiveness_values",
        "film_scale_factors",
        "electric_heat_scenario_ids",
    )
    return math.prod(len(scenario[key]) for key in keys)


def _case_id(spec: Mapping[str, Any]) -> str:
    def token(value: float) -> str:
        return f"{value:.8g}".replace(".", "p").replace("-", "m")

    return (
        f"case_{int(spec['case_index']):05d}"
        f"__{spec['material_id']}"
        f"__w{token(float(spec['process_outlet_w_g_kg_da']))}"
        f"__v{token(float(spec['terminal_voltage_v']))}"
        f"__n{int(spec['segment_count'])}"
        f"__eps{token(float(spec['sensible_effectiveness']))}"
        f"__film{token(float(spec['film_scale_factor']))}"
        f"__{spec['electric_heat_scenario_id']}"
    )


def _nan_stack(reason: str) -> dict[str, Any]:
    return {
        "stack_feasible": False,
        "stack_infeasibility_reason": reason,
        "stack_series_cells": math.nan,
        "stack_parallel_strings": math.nan,
        "stack_total_cells": math.nan,
        "stack_string_voltage_v": math.nan,
        "stack_dc_bus_current_a": math.nan,
        "stack_reference_cell_power_kw": math.nan,
    }


def attach_thermodynamic_audit(
    frame: pd.DataFrame,
    *,
    material_id: str,
) -> pd.DataFrame:
    """Attach the active-transport audit without imposing a passive-gradient gate."""

    if frame.empty:
        return frame.copy()
    coupling_identity_required = "nafion" not in material_id.lower()
    rows: list[dict[str, Any]] = []
    for record in frame.to_dict("records"):
        audit = audit_local_record(
            record,
            temperature_c=float(record["membrane_temperature_c"]),
            coupling_identity_required=coupling_identity_required,
        )
        rows.append({**record, **audit})
    return pd.DataFrame(rows)


def run_case(
    *,
    spec: Mapping[str, Any],
    config: Mapping[str, Any],
    states: Mapping[str, Any],
    baseline: Any,
    v2: Any,
    v2_config: dict[str, Any],
) -> tuple[dict[str, Any], pd.DataFrame]:
    boundary = config["boundary"]
    m_process = float(boundary["process_outdoor_dry_air_kg_s"])
    m_exhaust = m_process * float(boundary["available_exhaust_to_process_ratio"])
    target_w = float(spec["process_outlet_w_g_kg_da"]) / 1000.0
    if target_w < states["supply"].w - 1.0e-12:
        raise ValueError("The active-ERV target cannot be below final supply w")
    if target_w >= states["outdoor"].w:
        raise ValueError("The active-ERV target must be below outdoor inlet w")

    material = dict(config["materials"][spec["material_id"]])
    heat = config["electric_heat_scenarios"][spec["electric_heat_scenario_id"]]
    electrical = config["electrical"]
    solver_config = config["solver"]
    core_power_for_heat_kw = 0.0
    previous_temperatures: tuple[float, float] | None = None
    previous_power_kw: float | None = None
    thermal_converged = False
    endpoints: ActiveEndpoints | None = None
    transport: dict[str, Any] = {}
    segment_frame = pd.DataFrame()
    hydraulics: dict[str, Any] = {
        "hydraulic_status": "transport_not_sized",
        "selected_active_core_fan_power_kw": math.nan,
    }
    core_power_kw = math.nan
    iteration = 0
    temperature_residual_k = math.nan
    power_residual_fraction = math.nan

    for iteration in range(
        1, int(solver_config["maximum_thermal_iterations"]) + 1
    ):
        endpoints = build_active_endpoints(
            process_in=states["outdoor"],
            exhaust_in=states["exhaust"],
            process_dry_air_kg_s=m_process,
            exhaust_dry_air_kg_s=m_exhaust,
            process_out_w=target_w,
            sensible_effectiveness=float(spec["sensible_effectiveness"]),
            active_core_electric_power_kw=core_power_for_heat_kw,
            process_heat_fraction=float(heat["process_fraction"]),
            exhaust_heat_fraction=float(heat["exhaust_fraction"]),
        )
        if not endpoints.valid:
            transport = {
                "transport_solution_complete": False,
                "transport_failure": "invalid_or_supersaturated_active_endpoints",
                "current_density_gate_applied": False,
                "engineering_current_density_limit_a_m2": None,
            }
            break
        transport, segment_frame = solve_segmented_transport(
            v2=v2,
            v2_config=v2_config,
            study_config=config,
            endpoints=endpoints,
            material=material,
            terminal_voltage_v=float(spec["terminal_voltage_v"]),
            fixed_loss_voltage_v=float(
                electrical["default_fixed_loss_voltage_v"]
            ),
            series_asr_ohm_m2=float(
                electrical["default_series_asr_ohm_m2"]
            ),
            film_scale_factor=float(spec["film_scale_factor"]),
            segment_count=int(spec["segment_count"]),
        )
        if not bool(transport["transport_solution_complete"]):
            break
        hydraulics = active_core_hydraulics(
            endpoints=endpoints,
            active_area_m2=float(transport["required_active_area_m2"]),
            config=config,
        )
        core_power_kw = (
            float(transport["eo_grid_power_kw"])
            + float(hydraulics["selected_active_core_fan_power_kw"])
            + float(config["active_core"]["motor_power_kw"])
            + float(config["active_core"]["controls_power_kw"])
        )
        temperatures = (endpoints.process_out.t_c, endpoints.exhaust_out.t_c)
        if previous_temperatures is not None and previous_power_kw is not None:
            temperature_residual_k = max(
                abs(temperatures[0] - previous_temperatures[0]),
                abs(temperatures[1] - previous_temperatures[1]),
            )
            power_residual_fraction = abs(core_power_kw - previous_power_kw) / max(
                abs(core_power_kw), 1.0e-9
            )
            if (
                temperature_residual_k
                <= float(solver_config["thermal_temperature_tolerance_k"])
                and power_residual_fraction
                <= float(solver_config["thermal_power_relative_tolerance"])
            ):
                thermal_converged = True
                break
        previous_temperatures = temperatures
        previous_power_kw = core_power_kw
        core_power_for_heat_kw = core_power_kw

    if endpoints is None:
        raise RuntimeError("No active endpoint calculation was attempted")

    case_id = _case_id(spec)
    if not segment_frame.empty:
        segment_frame = attach_thermodynamic_audit(
            segment_frame,
            material_id=str(spec["material_id"]),
        )
        segment_frame.insert(0, "case_id", case_id)
        segment_frame.insert(1, "material_id", spec["material_id"])
        segment_frame.insert(
            2,
            "process_outlet_target_w_g_kg_da",
            float(spec["process_outlet_w_g_kg_da"]),
        )

    transport_complete = bool(transport.get("transport_solution_complete", False))
    water_balance_pass = bool(transport.get("transport_water_balance_pass", False))
    area_cap_pass = bool(transport.get("area_cap_pass", False))
    thermodynamic_consistency_pass = bool(
        transport_complete
        and not segment_frame.empty
        and segment_frame["thermodynamic_consistency_pass"].astype(bool).all()
    )
    terminal_voltage_pass = bool(
        transport.get("terminal_voltage_gate_pass", False)
    )
    target_closed = bool(
        transport_complete
        and water_balance_pass
        and terminal_voltage_pass
        and endpoints.valid
    )
    remaining_ac = solve_coil(
        inlet=endpoints.process_out,
        supply_target=states["supply"],
        m_da=m_process,
        rated_cop=baseline.rated_cop,
        ac_config=config["ac_model"],
    )
    exhaust_rh_pass = endpoints.exhaust_out.rh <= float(
        config["gates"]["maximum_exhaust_outlet_rh"]
    )

    if transport_complete:
        stack = stack_topology(
            required_area_m2=float(transport["required_active_area_m2"]),
            integrated_current_a=float(transport["integrated_current_a"]),
            maximum_current_density_a_m2=float(
                transport["maximum_local_current_density_a_m2"]
            ),
            cell_terminal_voltage_v=float(spec["terminal_voltage_v"]),
            stack_config=config["stack"],
        )
    else:
        stack = _nan_stack("transport solution incomplete")

    hydraulic_pass = bool(
        transport_complete
        and float(hydraulics.get("process_channel_pressure_drop_pa", math.inf))
        <= float(config["gates"]["maximum_channel_pressure_drop_each_side_pa"])
        and float(hydraulics.get("receiver_channel_pressure_drop_pa", math.inf))
        <= float(config["gates"]["maximum_channel_pressure_drop_each_side_pa"])
    )
    positive_surface = bool(transport.get("positive_surface_direction", False))
    robust_surface = bool(transport.get("robust_surface_direction", False))

    common_kw = float(
        config["common_components"]["common_electric_power_kw_each_system"]
    )
    decision_ready = bool(
        target_closed
        and thermodynamic_consistency_pass
        and thermal_converged
        and exhaust_rh_pass
        and remaining_ac.physical
        and math.isfinite(core_power_kw)
    )
    active_total_kw = (
        core_power_kw + remaining_ac.total_ac_power_kw + common_kw
        if decision_ready
        else math.nan
    )
    saving_kw = (
        baseline.total_power_kw - active_total_kw
        if decision_ready
        else math.nan
    )
    saving_pct = (
        100.0 * saving_kw / baseline.total_power_kw
        if decision_ready
        else math.nan
    )
    water_kg_h = float(transport.get("water_transfer_target_kg_h", math.nan))
    active_core_sec = (
        core_power_kw / water_kg_h
        if decision_ready and water_kg_h > 0.0
        else math.nan
    )
    break_even_power_kw = (
        baseline.total_power_kw - remaining_ac.total_ac_power_kw - common_kw
        if decision_ready
        else math.nan
    )
    break_even_sec = (
        break_even_power_kw / water_kg_h
        if decision_ready and water_kg_h > 0.0
        else math.nan
    )
    conditional_energy_pass = bool(decision_ready and saving_kw > 0.0)
    physics_screen_pass = bool(
        target_closed
        and thermodynamic_consistency_pass
        and thermal_converged
        and exhaust_rh_pass
    )
    # Legacy output name retained for downstream compatibility.  Robust
    # passive-gradient assistance is now a separate diagnostic; an adverse
    # surface gradient is allowed for thermodynamically consistent active EO.
    robust_physics_pass = physics_screen_pass
    passive_gradient_assistance_pass = bool(
        physics_screen_pass and positive_surface
    )
    robust_passive_gradient_assistance_pass = bool(
        physics_screen_pass and robust_surface
    )
    engineering_screen_pass = bool(
        physics_screen_pass
        and conditional_energy_pass
        and hydraulic_pass
        and bool(stack.get("stack_feasible", False))
    )

    if engineering_screen_pass:
        status = "engineering_screen_pass_not_full_coupled"
    elif target_closed and not thermodynamic_consistency_pass:
        status = "transport_closed_thermodynamic_audit_failed"
    elif decision_ready:
        status = "transport_closed_engineering_gate_failed"
    elif transport_complete:
        status = "transport_sized_decision_boundary_incomplete"
    else:
        status = "transport_solution_incomplete"

    process_water_loss_kg_s = endpoints.process_dry_air_kg_s * (
        endpoints.process_in.w - endpoints.process_out.w
    )
    receiver_water_gain_kg_s = endpoints.exhaust_dry_air_kg_s * (
        endpoints.exhaust_out.w - endpoints.exhaust_in.w
    )
    shared_stream_mass_identity = bool(
        config["architecture"]["id"] == "shared_core_same_stream"
        and math.isclose(
            endpoints.process_dry_air_kg_s,
            endpoints.exhaust_dry_air_kg_s,
            rel_tol=0.0,
            abs_tol=1.0e-12,
        )
        and math.isclose(
            float(config["architecture"]["external_receiver_mass_flow_kg_s"]),
            0.0,
            rel_tol=0.0,
            abs_tol=1.0e-12,
        )
    )
    row: dict[str, Any] = {
        **dict(spec),
        "case_id": case_id,
        "script_version": SCRIPT_VERSION,
        "study_id": config["study_id"],
        "architecture_id": config["architecture"]["id"],
        "same_exhaust_stream_used_once": shared_stream_mass_identity,
        "process_dry_air_mass_flow_kg_s": endpoints.process_dry_air_kg_s,
        "receiver_dry_air_mass_flow_kg_s": endpoints.exhaust_dry_air_kg_s,
        "external_receiver_mass_flow_kg_s": float(
            config["architecture"]["external_receiver_mass_flow_kg_s"]
        ),
        "process_water_loss_kg_s": process_water_loss_kg_s,
        "receiver_water_gain_kg_s": receiver_water_gain_kg_s,
        "shared_stream_water_identity_error_kg_s": (
            receiver_water_gain_kg_s - process_water_loss_kg_s
        ),
        "model_boundary": config["model_boundary"],
        "material_model": material["model"],
        "material_validated": bool(material.get("validated_material", False)),
        "status": status,
        "thermal_iteration_count": iteration,
        "thermal_fixed_point_converged": thermal_converged,
        "thermal_temperature_residual_k": temperature_residual_k,
        "thermal_power_residual_fraction": power_residual_fraction,
        "process_inlet_w_g_kg_da": 1000.0 * endpoints.process_in.w,
        "process_outlet_w_g_kg_da": 1000.0 * endpoints.process_out.w,
        "process_outlet_temperature_c": endpoints.process_out.t_c,
        "process_outlet_rh": endpoints.process_out.rh,
        "exhaust_inlet_w_g_kg_da": 1000.0 * endpoints.exhaust_in.w,
        "exhaust_outlet_w_g_kg_da": 1000.0 * endpoints.exhaust_out.w,
        "exhaust_outlet_temperature_c": endpoints.exhaust_out.t_c,
        "exhaust_outlet_rh": endpoints.exhaust_out.rh,
        "active_latent_effectiveness": endpoints.active_latent_effectiveness,
        "endpoint_water_balance_residual_kg_s": endpoints.water_balance_residual_kg_s,
        "endpoint_enthalpy_balance_residual_kw": endpoints.base_enthalpy_balance_residual_kw,
        "endpoint_valid": endpoints.valid,
        "exhaust_rh_gate_pass": exhaust_rh_pass,
        **transport,
        **hydraulics,
        **stack,
        "effective_fixed_loss_voltage_v": float(
            electrical["default_fixed_loss_voltage_v"]
        ),
        "effective_series_asr_ohm_m2": float(
            electrical["default_series_asr_ohm_m2"]
        ),
        "target_transport_closed": target_closed,
        "conditional_decision_ready": decision_ready,
        "hydraulic_pressure_gate_pass": hydraulic_pass,
        "remaining_ac_power_kw": (
            remaining_ac.total_ac_power_kw if decision_ready else math.nan
        ),
        "remaining_ac_water_removed_kg_h": (
            remaining_ac.water_removed_kg_h if decision_ready else math.nan
        ),
        "active_core_power_kw": core_power_kw if decision_ready else math.nan,
        "conditional_active_total_power_kw": active_total_kw,
        "conditional_saving_kw_vs_passive_erv": saving_kw,
        "conditional_saving_pct_vs_passive_erv": saving_pct,
        "active_core_sec_kwh_kg": active_core_sec,
        "break_even_active_core_power_kw": break_even_power_kw,
        "break_even_active_core_sec_kwh_kg": break_even_sec,
        "conditional_power_identity_error_kw": (
            baseline.total_power_kw - active_total_kw - saving_kw
            if decision_ready
            else math.nan
        ),
        "conditional_energy_pass": conditional_energy_pass,
        "thermodynamic_consistency_pass": thermodynamic_consistency_pass,
        "physics_screen_pass": physics_screen_pass,
        "robust_physics_pass": robust_physics_pass,
        "passive_gradient_assistance_pass": passive_gradient_assistance_pass,
        "robust_passive_gradient_assistance_pass": (
            robust_passive_gradient_assistance_pass
        ),
        "engineering_screen_pass": engineering_screen_pass,
        "full_coupled_gate_pass": False,
        "full_system_claim_allowed": False,
        "claim_level": config["claim_boundary"]["claim_level"],
        "current_density_gate_applied": False,
        "engineering_current_density_limit_a_m2": None,
        "area_acceptance_gate_applied": False,
        "within_area_observation_cap": area_cap_pass,
        "passive_erv_plus_ac_reference_kw": baseline.total_power_kw,
    }
    return row, segment_frame


def _bool_sum(frame: pd.DataFrame, column: str) -> int:
    return int(frame[column].fillna(False).astype(bool).sum())


def build_target_summary(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for target, group in frame.groupby("process_outlet_w_g_kg_da", sort=True):
        decision = group.loc[group["target_transport_closed"].astype(bool)]
        rows.append(
            {
                "process_outlet_w_g_kg_da": target,
                "case_count": len(group),
                "transport_closed_count": _bool_sum(group, "target_transport_closed"),
                "positive_surface_count": _bool_sum(
                    group, "positive_surface_direction"
                ),
                "thermodynamic_consistency_count": _bool_sum(
                    group, "thermodynamic_consistency_pass"
                ),
                "robust_physics_count": _bool_sum(group, "robust_physics_pass"),
                "robust_passive_gradient_assistance_count": _bool_sum(
                    group, "robust_passive_gradient_assistance_pass"
                ),
                "conditional_energy_positive_count": _bool_sum(
                    group, "conditional_energy_pass"
                ),
                "engineering_screen_count": _bool_sum(
                    group, "engineering_screen_pass"
                ),
                "minimum_required_area_m2": (
                    float(decision["required_active_area_m2"].min())
                    if not decision.empty
                    else math.nan
                ),
                "best_conditional_saving_kw": (
                    float(decision["conditional_saving_kw_vs_passive_erv"].max())
                    if not decision.empty
                    else math.nan
                ),
                "maximum_minimum_surface_margin": (
                    float(decision["minimum_surface_activity_margin"].max())
                    if not decision.empty
                    else math.nan
                ),
            }
        )
    return pd.DataFrame(rows)


def build_gate_counts(frame: pd.DataFrame) -> pd.DataFrame:
    gates = (
        "transport_solution_complete",
        "target_transport_closed",
        "surface_diagnostic_complete",
        "positive_surface_direction",
        "robust_surface_direction",
        "thermodynamic_consistency_pass",
        "passive_gradient_assistance_pass",
        "robust_passive_gradient_assistance_pass",
        "thermal_fixed_point_converged",
        "exhaust_rh_gate_pass",
        "hydraulic_pressure_gate_pass",
        "stack_feasible",
        "segment_convergence_gate_pass",
        "conditional_energy_pass",
        "physics_screen_pass",
        "robust_physics_pass",
        "engineering_screen_pass",
        "full_coupled_gate_pass",
    )
    return pd.DataFrame(
        [
            {
                "gate": gate,
                "pass_count": _bool_sum(frame, gate),
                "fail_count": len(frame) - _bool_sum(frame, gate),
                "total_count": len(frame),
            }
            for gate in gates
        ]
    )


def build_segment_convergence(
    frame: pd.DataFrame, config: Mapping[str, Any]
) -> pd.DataFrame:
    """Compare otherwise identical coarse/refined counter-current cases."""

    convergence = config["gates"]["segment_convergence"]
    coarse_count = int(convergence["coarse_segment_count"])
    refined_count = int(convergence["refined_segment_count"])
    keys = [
        "material_id",
        "process_outlet_w_g_kg_da",
        "terminal_voltage_v",
        "sensible_effectiveness",
        "film_scale_factor",
        "electric_heat_scenario_id",
    ]
    coarse = frame.loc[frame["segment_count"].eq(coarse_count)].set_index(keys)
    refined = frame.loc[frame["segment_count"].eq(refined_count)].set_index(keys)
    common = coarse.index.intersection(refined.index)
    rows: list[dict[str, Any]] = []
    for index in common:
        left = coarse.loc[index]
        right = refined.loc[index]
        if isinstance(left, pd.DataFrame) or isinstance(right, pd.DataFrame):
            raise ValueError("Segment-convergence coordinates are not unique")
        area_coarse = float(left.get("required_active_area_m2", math.nan))
        area_refined = float(right.get("required_active_area_m2", math.nan))
        surface_coarse = float(
            left.get("minimum_surface_activity_margin", math.nan)
        )
        surface_refined = float(
            right.get("minimum_surface_activity_margin", math.nan)
        )
        saving_coarse = float(
            left.get("conditional_saving_kw_vs_passive_erv", math.nan)
        )
        saving_refined = float(
            right.get("conditional_saving_kw_vs_passive_erv", math.nan)
        )
        finite_transport_pair = bool(
            math.isfinite(area_coarse)
            and math.isfinite(area_refined)
            and math.isfinite(surface_coarse)
            and math.isfinite(surface_refined)
        )
        area_relative_change = (
            abs(area_refined - area_coarse) / max(abs(area_refined), 1.0e-12)
            if finite_transport_pair
            else math.nan
        )
        surface_absolute_change = (
            abs(surface_refined - surface_coarse)
            if finite_transport_pair
            else math.nan
        )
        saving_pair_finite = bool(
            math.isfinite(saving_coarse) and math.isfinite(saving_refined)
        )
        saving_absolute_change = (
            abs(saving_refined - saving_coarse)
            if saving_pair_finite
            else math.nan
        )
        transport_converged = bool(
            finite_transport_pair
            and area_relative_change
            <= float(convergence["maximum_area_relative_change"])
            and surface_absolute_change
            <= float(convergence["maximum_surface_margin_absolute_change"])
        )
        decision_converged = bool(
            transport_converged
            and saving_pair_finite
            and saving_absolute_change
            <= float(convergence["maximum_saving_absolute_change_kw"])
        )
        key_values = index if isinstance(index, tuple) else (index,)
        rows.append(
            {
                **dict(zip(keys, key_values)),
                "coarse_case_id": left["case_id"],
                "refined_case_id": right["case_id"],
                "coarse_segment_count": coarse_count,
                "refined_segment_count": refined_count,
                "coarse_transport_closed": bool(left["target_transport_closed"]),
                "refined_transport_closed": bool(right["target_transport_closed"]),
                "area_coarse_m2": area_coarse,
                "area_refined_m2": area_refined,
                "area_relative_change": area_relative_change,
                "surface_margin_coarse": surface_coarse,
                "surface_margin_refined": surface_refined,
                "surface_margin_absolute_change": surface_absolute_change,
                "saving_coarse_kw": saving_coarse,
                "saving_refined_kw": saving_refined,
                "saving_absolute_change_kw": saving_absolute_change,
                "transport_convergence_pass": transport_converged,
                "decision_convergence_pass": decision_converged,
            }
        )
    return pd.DataFrame(rows)


def attach_segment_convergence(
    cases: pd.DataFrame, convergence: pd.DataFrame
) -> pd.DataFrame:
    result = cases.copy()
    result["segment_convergence_evaluated"] = False
    result["segment_transport_convergence_pass"] = False
    result["segment_decision_convergence_pass"] = False
    if convergence.empty:
        # A one-discretisation smoke grid is a software check, not an
        # engineering convergence claim.  Fail the engineering label closed.
        result["segment_convergence_gate_pass"] = False
        previously_engineering = result["engineering_screen_pass"].astype(bool)
        result["engineering_screen_pass"] = False
        result.loc[
            previously_engineering,
            "status",
        ] = "engineering_screen_not_evaluated_without_segment_convergence"
        return result
    by_case: dict[str, tuple[bool, bool]] = {}
    for row in convergence.itertuples(index=False):
        pair = (
            bool(row.transport_convergence_pass),
            bool(row.decision_convergence_pass),
        )
        by_case[str(row.coarse_case_id)] = pair
        by_case[str(row.refined_case_id)] = pair
    for index, case_id in result["case_id"].items():
        if str(case_id) not in by_case:
            continue
        transport_pass, decision_pass = by_case[str(case_id)]
        result.at[index, "segment_convergence_evaluated"] = True
        result.at[index, "segment_transport_convergence_pass"] = transport_pass
        result.at[index, "segment_decision_convergence_pass"] = decision_pass
    result["segment_convergence_gate_pass"] = result[
        "segment_decision_convergence_pass"
    ].astype(bool)
    previous_engineering = result["engineering_screen_pass"].astype(bool)
    result["engineering_screen_pass"] = (
        previous_engineering
        & result["segment_convergence_gate_pass"].astype(bool)
    )
    result.loc[
        previous_engineering & ~result["engineering_screen_pass"].astype(bool),
        "status",
    ] = "engineering_screen_failed_segment_convergence"
    return result


def select_cases(frame: pd.DataFrame) -> pd.DataFrame:
    selected: list[pd.Series] = []
    for _, group in frame.groupby("process_outlet_w_g_kg_da", sort=True):
        candidates = group.loc[
            group["engineering_screen_pass"].astype(bool)
            & group["conditional_saving_kw_vs_passive_erv"].notna()
        ]
        if candidates.empty:
            candidates = group.loc[
                group["robust_physics_pass"].astype(bool)
                & group["segment_convergence_gate_pass"].astype(bool)
                & group["conditional_saving_kw_vs_passive_erv"].notna()
            ]
        if candidates.empty:
            candidates = group.loc[
                group["robust_physics_pass"].astype(bool)
                & group["conditional_saving_kw_vs_passive_erv"].notna()
            ]
        if candidates.empty:
            candidates = group.loc[
                group["physics_screen_pass"].astype(bool)
                & group["segment_convergence_gate_pass"].astype(bool)
                & group["conditional_saving_kw_vs_passive_erv"].notna()
            ]
        if candidates.empty:
            candidates = group.loc[
                group["physics_screen_pass"].astype(bool)
                & group["conditional_saving_kw_vs_passive_erv"].notna()
            ]
        if candidates.empty:
            candidates = group.loc[
                group["target_transport_closed"].astype(bool)
                & group["segment_convergence_gate_pass"].astype(bool)
            ]
        if candidates.empty:
            candidates = group.loc[group["target_transport_closed"].astype(bool)]
        if candidates.empty:
            continue
        if candidates["segment_convergence_evaluated"].fillna(False).any():
            refined_count = int(candidates["segment_count"].max())
            refined = candidates.loc[
                candidates["segment_count"].eq(refined_count)
            ]
            if not refined.empty:
                candidates = refined
        ordering = candidates.sort_values(
            [
                "conditional_saving_kw_vs_passive_erv",
                "minimum_surface_activity_margin",
                "required_active_area_m2",
            ],
            ascending=[False, False, True],
            na_position="last",
        )
        selected.append(ordering.iloc[0])
    return pd.DataFrame(selected).reset_index(drop=True)


def _save_figure(fig: plt.Figure, directory: Path, stem: str) -> list[Path]:
    png = directory / f"{stem}.png"
    pdf = directory / f"{stem}.pdf"
    fig.savefig(png, dpi=220, bbox_inches="tight", facecolor="white")
    fig.savefig(pdf, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return [png, pdf]


def make_plots(
    cases: pd.DataFrame,
    segments: pd.DataFrame,
    selected: pd.DataFrame,
    output_dir: Path,
) -> list[Path]:
    figure_dir = output_dir / "figures"
    figure_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    plt.rcParams.update(
        {
            "font.size": 10,
            "axes.grid": True,
            "grid.alpha": 0.25,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )

    anchor = cases.loc[
        cases["material_id"].eq("terminal1_anchor")
        & np.isclose(cases["process_outlet_w_g_kg_da"], 10.0)
        & cases["target_transport_closed"].astype(bool)
    ].sort_values(["terminal_voltage_v", "segment_count"])
    if not anchor.empty:
        case_id = str(anchor.iloc[0]["case_id"])
        profile = segments.loc[segments["case_id"].eq(case_id)].sort_values(
            "segment_index"
        )
        fig, axes = plt.subplots(2, 1, figsize=(8.0, 7.2), sharex=True)
        axes[0].plot(
            profile["x_mid"],
            profile["minimum_boundary_bulk_activity_margin"],
            marker="o",
            label=r"Min. $\Delta a_{bulk}$ ved segmentgrense",
        )
        axes[0].plot(
            profile["x_mid"],
            profile["minimum_boundary_surface_activity_margin"],
            marker="s",
            label=r"Min. $\Delta a_{surface}$ ved segmentgrense",
        )
        axes[0].plot(
            profile["x_mid"],
            profile["surface_activity_margin"],
            color="#777777",
            linewidth=1.0,
            linestyle=":",
            label=r"$\Delta a_{surface}$ i segmentmidtpunkt",
        )
        axes[0].axhline(0.0, color="black", linewidth=0.9)
        axes[0].axhline(0.02, color="#c25a2c", linewidth=1.0, linestyle="--")
        axes[0].set_ylabel("Aktivitetsmargin [-]")
        axes[0].set_title("Aksial gradient — Terminal-1, mål 10 g/kg")
        axes[0].legend(frameon=False)
        axes[1].plot(
            profile["x_mid"],
            profile["net_flux_mol_m2_s"],
            marker="o",
            label="Netto",
        )
        axes[1].plot(
            profile["x_mid"],
            profile["eo_flux_mol_m2_s"],
            marker="^",
            label="EO",
        )
        axes[1].plot(
            profile["x_mid"],
            profile["diffusion_flux_mol_m2_s"],
            marker="s",
            label="Diffusjon",
        )
        axes[1].axhline(0.0, color="black", linewidth=0.9)
        axes[1].set_xlabel("Normalisert posisjon i prosessretningen [-]")
        axes[1].set_ylabel(r"Vannfluks [mol m$^{-2}$ s$^{-1}$]")
        axes[1].legend(frameon=False, ncol=3)
        outputs.extend(_save_figure(fig, figure_dir, "01_axial_gradient_anchor"))

    heat = cases.loc[
        cases["material_id"].eq("terminal1_anchor")
        & cases["segment_count"].eq(cases["segment_count"].min())
        & np.isclose(cases["sensible_effectiveness"], 0.75)
        & np.isclose(cases["film_scale_factor"], 1.0)
    ].copy()
    if not heat.empty:
        pivot = heat.pivot_table(
            index="process_outlet_w_g_kg_da",
            columns="terminal_voltage_v",
            values="minimum_surface_activity_margin",
            aggfunc="max",
        ).sort_index(ascending=False)
        fig, axis = plt.subplots(figsize=(9.0, 5.6))
        image = axis.imshow(
            pivot.to_numpy(dtype=float),
            aspect="auto",
            interpolation="nearest",
            cmap="RdYlGn",
            vmin=-0.1,
            vmax=0.1,
        )
        axis.set_xticks(range(len(pivot.columns)))
        axis.set_xticklabels([f"{value:g}" for value in pivot.columns], rotation=45)
        axis.set_yticks(range(len(pivot.index)))
        axis.set_yticklabels([f"{value:.3f}" for value in pivot.index])
        axis.set_xlabel("Terminalspenning per celle [V]")
        axis.set_ylabel("Prosessutløp [g/kg tørrluft]")
        axis.set_title("Minimum overflateaktivitetsmargin — Terminal-1")
        colorbar = fig.colorbar(image, ax=axis)
        colorbar.set_label("Minimum overflatemargin [-]")
        outputs.extend(_save_figure(fig, figure_dir, "02_target_voltage_surface_map"))

    if not selected.empty:
        ordered = selected.sort_values("process_outlet_w_g_kg_da")
        fig, axis_area = plt.subplots(figsize=(8.2, 5.2))
        axis_saving = axis_area.twinx()
        area_line = axis_area.plot(
            ordered["process_outlet_w_g_kg_da"],
            ordered["required_active_area_m2"],
            marker="o",
            color="#2878a8",
            label="Membranareal",
        )
        saving_line = axis_saving.plot(
            ordered["process_outlet_w_g_kg_da"],
            ordered["conditional_saving_kw_vs_passive_erv"],
            marker="s",
            color="#e88924",
            label="Betinget margin",
        )
        axis_area.set_xlabel("Prosessutløp [g/kg tørrluft]")
        axis_area.set_ylabel("Aktivt membranareal [m²]", color="#2878a8")
        axis_saving.set_ylabel("Betinget elektrisk margin [kW]", color="#e88924")
        axis_area.set_title("Beste tilgjengelige diagnostikk per fuktmål")
        lines = area_line + saving_line
        axis_area.legend(lines, [line.get_label() for line in lines], frameon=False)
        outputs.extend(_save_figure(fig, figure_dir, "03_target_area_energy_tradeoff"))

    nafion = cases.loc[
        cases["material_id"].eq("nafion_nr211_nominal_reference")
        & cases["segment_count"].eq(cases["segment_count"].max())
    ].copy()
    nafion_has_sensitivity = bool(
        not nafion.empty
        and (
            nafion["sensible_effectiveness"].nunique() > 1
            or nafion["film_scale_factor"].nunique() > 1
            or nafion["electric_heat_scenario_id"].nunique() > 1
        )
    )
    if nafion_has_sensitivity:
        robust_threshold = 0.02
        heat_ids = sorted(nafion["electric_heat_scenario_id"].unique())
        fig, axes = plt.subplots(
            1,
            len(heat_ids),
            figsize=(7.0 * len(heat_ids), 5.4),
            squeeze=False,
            sharey=True,
        )
        image = None
        for column, heat_id in enumerate(heat_ids):
            axis = axes[0, column]
            subset = nafion.loc[
                nafion["electric_heat_scenario_id"].eq(heat_id)
            ]
            pivot = subset.pivot_table(
                index="process_outlet_w_g_kg_da",
                columns="terminal_voltage_v",
                values="minimum_surface_activity_margin",
                aggfunc="max",
            ).sort_index(ascending=False)
            image = axis.imshow(
                pivot.to_numpy(dtype=float),
                aspect="auto",
                interpolation="nearest",
                cmap="RdYlGn",
                vmin=-0.04,
                vmax=0.06,
            )
            axis.set_xticks(range(len(pivot.columns)))
            axis.set_xticklabels(
                [f"{value:g}" for value in pivot.columns], rotation=45
            )
            axis.set_yticks(range(len(pivot.index)))
            axis.set_yticklabels([f"{value:.3f}" for value in pivot.index])
            axis.set_xlabel("Terminalspenning per celle [V]")
            axis.set_title(str(heat_id).replace("_", " "))
            for row_index, target in enumerate(pivot.index):
                for voltage_index, voltage in enumerate(pivot.columns):
                    value = float(pivot.loc[target, voltage])
                    if math.isfinite(value) and value >= robust_threshold:
                        axis.text(
                            voltage_index,
                            row_index,
                            "R",
                            ha="center",
                            va="center",
                            fontsize=9,
                            fontweight="bold",
                            color="black",
                        )
        axes[0, 0].set_ylabel("Prosessutløp [g/kg tørrluft]")
        fig.suptitle(
            "Nafion-referanse: beste overflatemargin i sveipet av film og sensibel effektivitet\n"
            "R = robusthetsmargin ≥ 0.02; ikke det samme som engineering-pass"
        )
        if image is not None:
            colorbar = fig.colorbar(image, ax=axes.ravel().tolist(), shrink=0.88)
            colorbar.set_label("Minimum overflateaktivitetsmargin [-]")
        outputs.extend(
            _save_figure(fig, figure_dir, "04_nafion_surface_envelope")
        )

        minimum_voltage = float(nafion["terminal_voltage_v"].min())
        targets = sorted(
            map(float, nafion["process_outlet_w_g_kg_da"].unique()),
            reverse=True,
        )
        fig, axes = plt.subplots(
            len(targets),
            len(heat_ids),
            figsize=(5.0 * len(heat_ids), 3.4 * len(targets)),
            squeeze=False,
            sharex=True,
            sharey=True,
        )
        image = None
        for row_index, target in enumerate(targets):
            for column, heat_id in enumerate(heat_ids):
                axis = axes[row_index, column]
                subset = nafion.loc[
                    np.isclose(nafion["process_outlet_w_g_kg_da"], target)
                    & np.isclose(nafion["terminal_voltage_v"], minimum_voltage)
                    & nafion["electric_heat_scenario_id"].eq(heat_id)
                ]
                pivot = subset.pivot_table(
                    index="sensible_effectiveness",
                    columns="film_scale_factor",
                    values="minimum_surface_activity_margin",
                    aggfunc="max",
                ).sort_index(ascending=False)
                image = axis.imshow(
                    pivot.to_numpy(dtype=float),
                    aspect="auto",
                    interpolation="nearest",
                    cmap="RdYlGn",
                    vmin=-0.04,
                    vmax=0.06,
                )
                axis.set_xticks(range(len(pivot.columns)))
                axis.set_xticklabels([f"{value:g}" for value in pivot.columns])
                axis.set_yticks(range(len(pivot.index)))
                axis.set_yticklabels([f"{value:g}" for value in pivot.index])
                if row_index == 0:
                    axis.set_title(str(heat_id).replace("_", " "))
                if column == 0:
                    axis.set_ylabel(
                        f"Mål {target:.3f} g/kg\nSensibel effektivitet"
                    )
                if row_index == len(targets) - 1:
                    axis.set_xlabel("Felles filmfaktor [-]")
                for y_index, sensible in enumerate(pivot.index):
                    for x_index, film in enumerate(pivot.columns):
                        value = float(pivot.loc[sensible, film])
                        label = f"{value:+.3f}" if math.isfinite(value) else "—"
                        axis.text(
                            x_index,
                            y_index,
                            label,
                            ha="center",
                            va="center",
                            fontsize=8,
                            fontweight=(
                                "bold"
                                if math.isfinite(value)
                                and value >= robust_threshold
                                else "normal"
                            ),
                        )
        fig.suptitle(
            f"Nafion-parameterområder ved {minimum_voltage:g} V — fet skrift passerer robusthetsmargin 0.02"
        )
        if image is not None:
            colorbar = fig.colorbar(image, ax=axes.ravel().tolist(), shrink=0.92)
            colorbar.set_label("Minimum overflateaktivitetsmargin [-]")
        outputs.extend(
            _save_figure(fig, figure_dir, "05_nafion_parameter_windows")
        )
    return outputs


def build_summary(
    *,
    config: Mapping[str, Any],
    mode: str,
    baseline: Any,
    cases: pd.DataFrame,
    selected: pd.DataFrame,
) -> dict[str, Any]:
    physics_energy = (
        cases["physics_screen_pass"].fillna(False).astype(bool)
        & cases["conditional_energy_pass"].fillna(False).astype(bool)
    )
    physics_energy_converged = physics_energy & cases[
        "segment_convergence_gate_pass"
    ].fillna(False).astype(bool)
    diagnostic_pool = cases.loc[cases["engineering_screen_pass"].astype(bool)]
    diagnostic_class = "engineering_screen_pass"
    if diagnostic_pool.empty:
        diagnostic_pool = cases.loc[
            cases["robust_physics_pass"].astype(bool)
            & cases["segment_convergence_gate_pass"].astype(bool)
        ]
        diagnostic_class = "robust_physics_segment_converged"
    if diagnostic_pool.empty:
        diagnostic_pool = cases.loc[cases["robust_physics_pass"].astype(bool)]
        diagnostic_class = "robust_physics_unfiltered_convergence"
    if diagnostic_pool.empty:
        diagnostic_pool = cases.loc[
            cases["physics_screen_pass"].astype(bool)
            & cases["segment_convergence_gate_pass"].astype(bool)
        ]
        diagnostic_class = "physics_screen_segment_converged"
    if diagnostic_pool.empty:
        diagnostic_pool = cases.loc[cases["physics_screen_pass"].astype(bool)]
        diagnostic_class = "physics_screen_unfiltered_convergence"
    if diagnostic_pool.empty:
        diagnostic_pool = cases.loc[
            cases["target_transport_closed"].astype(bool)
            & cases["segment_convergence_gate_pass"].astype(bool)
        ]
        diagnostic_class = "transport_closed_segment_converged"
    if diagnostic_pool.empty:
        diagnostic_pool = cases.loc[cases["target_transport_closed"].astype(bool)]
        diagnostic_class = "transport_closed_unfiltered_convergence"
    best: dict[str, Any] | None = None
    if not diagnostic_pool.empty:
        if diagnostic_pool[
            "segment_convergence_evaluated"
        ].fillna(False).any():
            refined_count = int(
                config["gates"]["segment_convergence"][
                    "refined_segment_count"
                ]
            )
            refined_pool = diagnostic_pool.loc[
                diagnostic_pool["segment_count"].eq(refined_count)
            ]
            if not refined_pool.empty:
                diagnostic_pool = refined_pool
        ranked = diagnostic_pool.sort_values(
            ["conditional_saving_kw_vs_passive_erv", "required_active_area_m2"],
            ascending=[False, True],
            na_position="last",
        )
        row = ranked.iloc[0]
        best = {
            "selection_class": diagnostic_class,
            "case_id": row["case_id"],
            "material_id": row["material_id"],
            "target_w_g_kg_da": row["process_outlet_w_g_kg_da"],
            "terminal_voltage_v": row["terminal_voltage_v"],
            "required_active_area_m2": row.get("required_active_area_m2"),
            "minimum_surface_activity_margin": row.get(
                "minimum_surface_activity_margin"
            ),
            "conditional_saving_kw": row.get(
                "conditional_saving_kw_vs_passive_erv"
            ),
            "conditional_saving_pct": row.get(
                "conditional_saving_pct_vs_passive_erv"
            ),
            "electric_heat_scenario_id": row.get(
                "electric_heat_scenario_id"
            ),
            "effective_fixed_loss_voltage_v": row.get(
                "effective_fixed_loss_voltage_v"
            ),
            "effective_series_asr_ohm_m2": row.get(
                "effective_series_asr_ohm_m2"
            ),
            "robust_physics_pass": row.get("robust_physics_pass"),
            "stack_feasible": row.get("stack_feasible"),
            "stack_infeasibility_reason": row.get(
                "stack_infeasibility_reason"
            ),
            "maximum_local_current_density_a_m2": row.get(
                "maximum_local_current_density_a_m2"
            ),
            "segment_convergence_evaluated": row.get(
                "segment_convergence_evaluated"
            ),
            "segment_decision_convergence_pass": row.get(
                "segment_decision_convergence_pass"
            ),
            "engineering_screen_pass": row.get("engineering_screen_pass"),
            "full_coupled_gate_pass": False,
        }
    return {
        "schema_version": 1,
        "study_id": config["study_id"],
        "script_version": SCRIPT_VERSION,
        "mode": mode,
        "case_count": len(cases),
        "passive_erv_plus_ac_reference_kw": baseline.total_power_kw,
        "transport_closed_count": _bool_sum(cases, "target_transport_closed"),
        "positive_surface_direction_count": _bool_sum(
            cases, "positive_surface_direction"
        ),
        "thermodynamic_consistency_count": _bool_sum(
            cases, "thermodynamic_consistency_pass"
        ),
        "robust_physics_count": _bool_sum(cases, "robust_physics_pass"),
        "robust_passive_gradient_assistance_count": _bool_sum(
            cases, "robust_passive_gradient_assistance_pass"
        ),
        "conditional_energy_positive_count": _bool_sum(
            cases, "conditional_energy_pass"
        ),
        "engineering_screen_count": _bool_sum(cases, "engineering_screen_pass"),
        "physics_energy_overlap_count": int(physics_energy.sum()),
        "physics_energy_segment_converged_count": int(
            physics_energy_converged.sum()
        ),
        # Backward-compatible aliases.  From v1.2 onward ``robust_physics``
        # means thermodynamic active-transport consistency, not a positive
        # passive surface-gradient requirement.
        "robust_energy_overlap_count": int(physics_energy.sum()),
        "robust_energy_segment_converged_count": int(
            physics_energy_converged.sum()
        ),
        "stack_feasible_count": _bool_sum(cases, "stack_feasible"),
        "segment_convergence_evaluated_count": _bool_sum(
            cases, "segment_convergence_evaluated"
        ),
        "segment_decision_convergence_pass_count": _bool_sum(
            cases, "segment_decision_convergence_pass"
        ),
        "full_coupled_gate_count": 0,
        "legacy_numeric_current_search_ceiling_case_count": _bool_sum(
            cases, "legacy_numeric_current_search_ceiling_encountered"
        ),
        "selected_target_count": len(selected),
        "best_available_diagnostic": best,
        "claim_boundary": config["claim_boundary"],
    }


def write_markdown_summary(path: Path, summary: Mapping[str, Any]) -> None:
    best = summary.get("best_available_diagnostic")
    lines = [
        "# Direct active EO-assisted ERV study v1",
        "",
        f"- Mode: **{summary['mode']}**.",
        f"- Cases: **{summary['case_count']}**.",
        (
            "- Passive modern ERV + AC reference: "
            f"**{float(summary['passive_erv_plus_ac_reference_kw']):.3f} kW**."
        ),
        f"- Transport target closed (area is diagnostic only): **{summary['transport_closed_count']}**.",
        (
            "- Thermodynamically consistent active-transport cases: "
            f"**{summary['thermodynamic_consistency_count']}**."
        ),
        f"- Physics screen: **{summary['robust_physics_count']}**.",
        (
            "- Positive / robust passive-gradient assistance diagnostics: "
            f"**{summary['positive_surface_direction_count']} / "
            f"{summary['robust_passive_gradient_assistance_count']}**."
        ),
        (
            "- Positive conditional energy margin: "
            f"**{summary['conditional_energy_positive_count']}**."
        ),
        f"- Engineering screen: **{summary['engineering_screen_count']}**.",
        (
            "- Thermodynamic-physics + positive-energy overlap: "
            f"**{summary['physics_energy_overlap_count']}**; of these "
            f"**{summary['physics_energy_segment_converged_count']}** also pass "
            "the 4→8 decision-convergence gate."
        ),
        f"- Stack-feasible cases: **{summary['stack_feasible_count']}**.",
        (
            "- Cases touching the legacy numerical 50 kA/m² search ceiling: "
            f"**{summary['legacy_numeric_current_search_ceiling_case_count']}** "
            "(numerical status, not a current-density acceptance gate)."
        ),
        (
            "- 4→8-segment decision convergence: "
            f"**{summary['segment_decision_convergence_pass_count']} / "
            f"{summary['segment_convergence_evaluated_count']} case rows**."
        ),
        "- Full-coupled/full-system cases: **0** by model contract.",
    ]
    if best:
        lines += [
            "",
            "## Best available diagnostic",
            "",
            f"- Selection class: `{best['selection_class']}`.",
            f"- Case: `{best['case_id']}`.",
            f"- Material: `{best['material_id']}`.",
            f"- Target: `{float(best['target_w_g_kg_da']):.3f} g/kg`.",
            f"- Terminal voltage: `{float(best['terminal_voltage_v']):.4g} V`.",
            f"- Area: `{float(best['required_active_area_m2']):.1f} m²`.",
            (
                "- Minimum surface margin: "
                f"`{float(best['minimum_surface_activity_margin']):.5f}`."
            ),
            (
                "- Conditional arithmetic margin: "
                f"`{float(best['conditional_saving_kw']):.2f} kW` / "
                f"`{float(best['conditional_saving_pct']):.2f} %`."
            ),
            (
                "- Heat treatment: "
                f"`{best['electric_heat_scenario_id']}`; effective fixed loss "
                f"`{float(best['effective_fixed_loss_voltage_v']):.4g} V`; "
                f"ASR `{float(best['effective_series_asr_ohm_m2']):.4g} ohm m²`."
            ),
            (
                "- Gates: robust physics "
                f"`{bool(best['robust_physics_pass'])}`, stack feasible "
                f"`{bool(best['stack_feasible'])}`, engineering "
                f"`{bool(best['engineering_screen_pass'])}`."
            ),
            (
                "- Numerics: 4→8 decision convergence "
                f"`{bool(best['segment_decision_convergence_pass'])}`; "
                "maximum local current density "
                f"`{float(best['maximum_local_current_density_a_m2']):.2f} A/m²` "
                "(diagnostic only)."
            ),
            (
                "- Stack result: "
                f"`{best['stack_infeasibility_reason']}`."
            ),
        ]
    lines += [
        "",
        "Audit PASS means integrity/reproducibility checks passed; it is not a design pass.",
        "This prescribed-effectiveness segmented screen does not enable a full-system or commercial saving claim.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_audit(
    *,
    config_path: Path,
    config: Mapping[str, Any],
    mode: str,
    baseline: Any,
    cases: pd.DataFrame,
    convergence: pd.DataFrame,
    outputs: Sequence[Path],
) -> dict[str, Any]:
    expected = expected_case_count(config, mode)
    reference = config["reference_audit"]
    transport_closed = cases.loc[cases["target_transport_closed"].astype(bool)]
    decision = cases.loc[cases["conditional_decision_ready"].astype(bool)]
    segment_counts = set(
        map(int, config["modes"][mode]["segment_counts"])
    )
    convergence_config = config["gates"]["segment_convergence"]
    convergence_pair_expected = (
        expected // len(segment_counts)
        if {
            int(convergence_config["coarse_segment_count"]),
            int(convergence_config["refined_segment_count"]),
        }.issubset(segment_counts)
        else 0
    )
    checks = [
        {
            "check_id": "exact_case_count",
            "passed": len(cases) == expected,
            "detail": f"observed={len(cases)}, expected={expected}",
        },
        {
            "check_id": "unique_case_ids",
            "passed": cases["case_id"].is_unique,
            "detail": "deterministic case identifiers are unique",
        },
        {
            "check_id": "segment_convergence_pair_count",
            "passed": len(convergence) == convergence_pair_expected,
            "detail": (
                f"observed={len(convergence)}, "
                f"expected={convergence_pair_expected}"
            ),
        },
        {
            "check_id": "all_terminal_voltages_at_or_below_2v",
            "passed": bool((cases["terminal_voltage_v"] <= 2.0 + 1.0e-12).all()),
            "detail": f"maximum={cases['terminal_voltage_v'].max():g} V",
        },
        {
            "check_id": "closed_transport_terminal_voltage_reconstructed",
            "passed": bool(
                transport_closed.empty
                or (
                    transport_closed["terminal_voltage_solution_pass"]
                    .astype(bool)
                    .all()
                    and transport_closed[
                        "maximum_calculated_terminal_voltage_v"
                    ]
                    .le(
                        float(config["electrical"]["maximum_terminal_voltage_v"])
                        + float(
                            config["solver"][
                                "terminal_voltage_absolute_tolerance_v"
                            ]
                        )
                    )
                    .all()
                    and transport_closed[
                        "maximum_absolute_terminal_voltage_error_v"
                    ]
                    .le(
                        float(
                            config["solver"][
                                "terminal_voltage_absolute_tolerance_v"
                            ]
                        )
                    )
                    .all()
                )
            ),
            "detail": "all decision-eligible midpoint and boundary states close the requested terminal voltage",
        },
        {
            "check_id": "no_current_density_acceptance_gate",
            "passed": bool(
                (~cases["current_density_gate_applied"].astype(bool)).all()
                and cases["engineering_current_density_limit_a_m2"].isna().all()
            ),
            "detail": "current density is diagnostic only",
        },
        {
            "check_id": "no_area_acceptance_gate",
            "passed": bool(
                (~cases["area_acceptance_gate_applied"].astype(bool)).all()
                and config["solver"]["area_is_acceptance_gate"] is False
            ),
            "detail": "area and the observation cap are diagnostics only",
        },
        {
            "check_id": "shared_return_stream_mass_and_water_identity",
            "passed": bool(
                cases["same_exhaust_stream_used_once"].astype(bool).all()
                and np.isclose(
                    cases["process_dry_air_mass_flow_kg_s"],
                    cases["receiver_dry_air_mass_flow_kg_s"],
                    rtol=0.0,
                    atol=1.0e-12,
                ).all()
                and cases["external_receiver_mass_flow_kg_s"]
                .abs()
                .le(1.0e-12)
                .all()
                and cases["shared_stream_water_identity_error_kg_s"]
                .abs()
                .le(1.0e-12)
                .all()
            ),
            "detail": "the balanced building-return stream is the sole receiver and gains exactly the process-side water loss",
        },
        {
            "check_id": "effective_electrical_losses_match_config",
            "passed": bool(
                np.isclose(
                    cases["effective_fixed_loss_voltage_v"],
                    float(config["electrical"]["default_fixed_loss_voltage_v"]),
                    rtol=0.0,
                    atol=1.0e-15,
                ).all()
                and np.isclose(
                    cases["effective_series_asr_ohm_m2"],
                    float(config["electrical"]["default_series_asr_ohm_m2"]),
                    rtol=0.0,
                    atol=1.0e-15,
                ).all()
            ),
            "detail": "effective fixed loss and ASR are explicit in every case row",
        },
        {
            "check_id": "surface_threshold_applied_from_config",
            "passed": bool(
                cases["positive_surface_direction"]
                .fillna(False)
                .astype(bool)
                .eq(
                    cases["surface_diagnostic_complete"]
                    .fillna(False)
                    .astype(bool)
                    & cases["minimum_surface_activity_margin"].gt(
                        float(
                            config["gates"][
                                "minimum_positive_surface_activity_margin"
                            ]
                        )
                    )
                )
                .all()
            ),
            "detail": "positive-surface classification is retained only as a passive-gradient assistance diagnostic",
        },
        {
            "check_id": "thermodynamic_gate_replaces_passive_surface_gate",
            "passed": bool(
                cases["physics_screen_pass"]
                .fillna(False)
                .astype(bool)
                .le(
                    cases["thermodynamic_consistency_pass"]
                    .fillna(False)
                    .astype(bool)
                )
                .all()
                and cases["robust_physics_pass"]
                .fillna(False)
                .astype(bool)
                .eq(cases["physics_screen_pass"].fillna(False).astype(bool))
                .all()
            ),
            "detail": "active transport is gated by thermodynamic consistency; passive-gradient sign is not a feasibility requirement",
        },
        {
            "check_id": "passive_reference_reproduced",
            "passed": math.isclose(
                baseline.total_power_kw,
                float(reference["expected_modern_ac_erv_total_power_kw"]),
                rel_tol=0.0,
                abs_tol=float(reference["absolute_tolerance_kw"]),
            ),
            "detail": (
                f"observed={baseline.total_power_kw:.12f} kW, "
                f"expected={float(reference['expected_modern_ac_erv_total_power_kw']):.12f} kW"
            ),
        },
        {
            "check_id": "passive_erv_outlet_reproduced",
            "passed": bool(
                math.isclose(
                    baseline.passive_erv.oa_out.t_c,
                    float(reference["expected_passive_erv_oa_out_temperature_c"]),
                    rel_tol=0.0,
                    abs_tol=1.0e-12,
                )
                and math.isclose(
                    baseline.passive_erv.oa_out.w,
                    float(reference["expected_passive_erv_oa_out_w_kg_kg_da"]),
                    rel_tol=0.0,
                    abs_tol=1.0e-12,
                )
            ),
            "detail": "23 C and canonical passive-ERV humidity ratio",
        },
        {
            "check_id": "closed_transport_water_balance",
            "passed": bool(
                transport_closed.empty
                or transport_closed["transport_water_balance_relative_error"]
                .abs()
                .le(float(config["gates"]["water_balance_relative_tolerance"]))
                .all()
            ),
            "detail": f"closed rows={len(transport_closed)}",
        },
        {
            "check_id": "conditional_power_identity",
            "passed": bool(
                decision.empty
                or decision["conditional_power_identity_error_kw"]
                .abs()
                .le(1.0e-9)
                .all()
            ),
            "detail": "reference - candidate total equals conditional margin",
        },
        {
            "check_id": "nondecision_rows_decision_fields_are_nan",
            "passed": bool(
                cases.loc[
                    ~cases["conditional_decision_ready"].astype(bool),
                    [
                        "conditional_active_total_power_kw",
                        "conditional_saving_kw_vs_passive_erv",
                        "active_core_sec_kwh_kg",
                        "break_even_active_core_sec_kwh_kg",
                    ],
                ]
                .isna()
                .all()
                .all()
            ),
            "detail": "decision quantities fail closed",
        },
        {
            "check_id": "full_system_claim_disabled",
            "passed": bool(
                (~cases["full_system_claim_allowed"].astype(bool)).all()
                and (~cases["full_coupled_gate_pass"].astype(bool)).all()
            ),
            "detail": "zero full-coupled cases is a valid study result",
        },
    ]
    return {
        "schema_version": 1,
        "study_id": config["study_id"],
        "script_version": SCRIPT_VERSION,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "status": "PASS" if all(check["passed"] for check in checks) else "FAIL",
        "audit_scope": "integrity_and_reproducibility_not_design_acceptance",
        "checks": checks,
        "sources": {
            "config": _file_record(config_path),
            "runner": _file_record(Path(__file__)),
            "active_erv_module": _file_record(ACTIVE_MODULE),
            "local_state_module": _file_record(LOCAL_STATE_MODULE),
            "thermodynamics_module": _file_record(THERMODYNAMICS_MODULE),
            "canonical_v2_model": _file_record(V2_MODEL),
            "canonical_v2_config": _file_record(V2_CONFIG),
        },
        "outputs": {
            path.relative_to(path.parents[1]).as_posix(): _file_record(path)
            for path in outputs
        },
        "metrics": {
            "expected_case_count": expected,
            "observed_case_count": len(cases),
            "transport_closed_count": _bool_sum(cases, "target_transport_closed"),
            "positive_surface_count": _bool_sum(
                cases, "positive_surface_direction"
            ),
            "segment_convergence_pair_count": len(convergence),
            "segment_decision_convergence_pass_pair_count": (
                int(convergence["decision_convergence_pass"].astype(bool).sum())
                if not convergence.empty
                else 0
            ),
            "maximum_reported_current_density_a_m2": float(
                pd.to_numeric(
                    cases["maximum_local_current_density_a_m2"], errors="coerce"
                ).max()
            ),
            "full_coupled_gate_count": 0,
            "robust_physics_count": _bool_sum(cases, "robust_physics_pass"),
            "thermodynamic_consistency_count": _bool_sum(
                cases, "thermodynamic_consistency_pass"
            ),
            "robust_passive_gradient_assistance_count": _bool_sum(
                cases, "robust_passive_gradient_assistance_pass"
            ),
            "engineering_screen_count": _bool_sum(
                cases, "engineering_screen_pass"
            ),
            "physics_energy_overlap_count": int(
                (
                    cases["physics_screen_pass"].fillna(False).astype(bool)
                    & cases["conditional_energy_pass"].fillna(False).astype(bool)
                ).sum()
            ),
            "physics_energy_segment_converged_count": int(
                (
                    cases["physics_screen_pass"].fillna(False).astype(bool)
                    & cases["conditional_energy_pass"].fillna(False).astype(bool)
                    & cases["segment_convergence_gate_pass"]
                    .fillna(False)
                    .astype(bool)
                ).sum()
            ),
            "robust_energy_overlap_count": int(
                (
                    cases["robust_physics_pass"].fillna(False).astype(bool)
                    & cases["conditional_energy_pass"].fillna(False).astype(bool)
                ).sum()
            ),
            "robust_energy_segment_converged_count": int(
                (
                    cases["robust_physics_pass"].fillna(False).astype(bool)
                    & cases["conditional_energy_pass"].fillna(False).astype(bool)
                    & cases["segment_convergence_gate_pass"]
                    .fillna(False)
                    .astype(bool)
                ).sum()
            ),
            "legacy_numeric_current_search_ceiling_case_count": _bool_sum(
                cases, "legacy_numeric_current_search_ceiling_encountered"
            ),
            "case_status_counts": {
                str(key): int(value)
                for key, value in cases["status"].value_counts().items()
            },
        },
        "claim_boundary": config["claim_boundary"],
    }


def run(config_path: Path, output_root: Path, mode: str, overwrite: bool) -> dict[str, Any]:
    config_path = config_path.resolve()
    output_dir = output_root.resolve() / mode
    known_outputs = (
        "config_used.json",
        "run_contract.json",
        "case_register.csv",
        "segment_register.csv.gz",
        "selected_cases.csv",
        "target_summary.csv",
        "gate_counts.csv",
        "segment_convergence.csv",
        "DECISION_SUMMARY.json",
        "SUMMARY.md",
        "study_audit.json",
    )
    existing = [output_dir / name for name in known_outputs if (output_dir / name).exists()]
    if existing and not overwrite:
        raise FileExistsError(
            f"Known outputs already exist below {output_dir}; pass --overwrite"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    config = load_config(config_path)
    specs = make_case_specs(config, mode)
    states = states_from_config(config)
    baseline = build_passive_baseline(
        config,
        states,
        float(config["passive_baseline_erv"]["sensible_effectiveness"]),
    )
    v2 = legacy_v2_module()
    v2_config = v2.load_config(V2_CONFIG)

    rows: list[dict[str, Any]] = []
    segment_frames: list[pd.DataFrame] = []
    for spec in specs:
        row, segment_frame = run_case(
            spec=spec,
            config=config,
            states=states,
            baseline=baseline,
            v2=v2,
            v2_config=v2_config,
        )
        rows.append(row)
        if not segment_frame.empty:
            segment_frames.append(segment_frame)
    cases = pd.DataFrame(rows).sort_values("case_index").reset_index(drop=True)
    segments = (
        pd.concat(segment_frames, ignore_index=True)
        if segment_frames
        else pd.DataFrame()
    )
    convergence = build_segment_convergence(cases, config)
    cases = attach_segment_convergence(cases, convergence)
    selected = select_cases(cases)
    target_summary = build_target_summary(cases)
    gate_counts = build_gate_counts(cases)
    summary = build_summary(
        config=config,
        mode=mode,
        baseline=baseline,
        cases=cases,
        selected=selected,
    )

    config_used = output_dir / "config_used.json"
    run_contract = output_dir / "run_contract.json"
    case_path = output_dir / "case_register.csv"
    segment_path = output_dir / "segment_register.csv.gz"
    selected_path = output_dir / "selected_cases.csv"
    target_path = output_dir / "target_summary.csv"
    gates_path = output_dir / "gate_counts.csv"
    convergence_path = output_dir / "segment_convergence.csv"
    decision_path = output_dir / "DECISION_SUMMARY.json"
    summary_path = output_dir / "SUMMARY.md"
    _write_json(config_used, config)
    _write_json(
        run_contract,
        {
            "schema_version": 1,
            "study_id": config["study_id"],
            "script_version": SCRIPT_VERSION,
            "mode": mode,
            "planned_case_count": len(specs),
            "maximum_terminal_voltage_v": config["electrical"][
                "maximum_terminal_voltage_v"
            ],
            "terminal_voltage_absolute_tolerance_v": config["solver"][
                "terminal_voltage_absolute_tolerance_v"
            ],
            "effective_fixed_loss_voltage_v": config["electrical"][
                "default_fixed_loss_voltage_v"
            ],
            "effective_series_asr_ohm_m2": config["electrical"][
                "default_series_asr_ohm_m2"
            ],
            "engineering_current_density_limit_a_m2": None,
            "current_density_gate_applied": False,
            "architecture_id": config["architecture"]["id"],
            "same_exhaust_stream_used_once": config["architecture"][
                "same_exhaust_stream_used_once"
            ],
            "external_receiver_mass_flow_kg_s": config["architecture"][
                "external_receiver_mass_flow_kg_s"
            ],
            "full_system_claim_allowed": False,
            "audit_scope": "integrity_and_reproducibility_not_design_acceptance",
        },
    )
    cases.to_csv(case_path, index=False)
    segments.to_csv(segment_path, index=False, compression="gzip")
    selected.to_csv(selected_path, index=False)
    target_summary.to_csv(target_path, index=False)
    gate_counts.to_csv(gates_path, index=False)
    convergence.to_csv(convergence_path, index=False)
    _write_json(decision_path, summary)
    write_markdown_summary(summary_path, summary)
    figure_paths = make_plots(cases, segments, selected, output_dir)
    materialized = [
        config_used,
        run_contract,
        case_path,
        segment_path,
        selected_path,
        target_path,
        gates_path,
        convergence_path,
        decision_path,
        summary_path,
        *figure_paths,
    ]
    audit = build_audit(
        config_path=config_path,
        config=config,
        mode=mode,
        baseline=baseline,
        cases=cases,
        convergence=convergence,
        outputs=materialized,
    )
    audit_path = output_dir / "study_audit.json"
    _write_json(audit_path, audit)
    if audit["status"] != "PASS":
        failed = [
            check["check_id"] for check in audit["checks"] if not check["passed"]
        ]
        raise RuntimeError(f"Study audit failed: {failed}")
    return audit


def main() -> int:
    args = parse_args()
    audit = run(args.config, args.output_dir, args.mode, args.overwrite)
    print(
        f"{audit['status']}: {audit['metrics']['observed_case_count']} cases; "
        f"{audit['metrics']['transport_closed_count']} transport-closed; "
        f"{audit['metrics']['positive_surface_count']} positive-surface."
    )
    print(Path(args.output_dir).resolve() / args.mode)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
