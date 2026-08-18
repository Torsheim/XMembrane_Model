from __future__ import annotations

import copy
import math
from types import ModuleType
from typing import Any

import pandas as pd

from heiq.wp1.airside.properties import (
    ACTIVITY_EPS,
    MOLAR_MASS_WATER_KG_MOL,
    FilmState,
    activity_from_t_w,
    calculate_film_state,
)

def status_category(raw_status: str, solution_ok: bool) -> str:
    """Map V2's detailed status without collapsing distinct failure modes."""
    if solution_ok:
        return "local_solution_valid"
    mapping = {
        "below_reversible_voltage": "below_reversible_voltage",
        "above_current_solver_ceiling": "above_internal_current_search_ceiling",
        "profile_bracket_failed": "profile_bracket_failure",
        "voltage_root_not_converged": "voltage_root_nonconvergence",
        "no_positive_current_at_applied_voltage": "below_reversible_voltage",
        "activity_profile_out_of_bounds": "activity_profile_out_of_bounds",
    }
    if raw_status in mapping:
        return mapping[raw_status]
    if raw_status.startswith("bvp_failed_"):
        return "bvp_numerical_failure"
    return f"unclassified_local_failure:{raw_status}"

def make_local_config(
    base_config: dict[str, Any],
    *,
    temperature_c: float,
    source_activity: float,
    receiver_activity: float,
    source_film: FilmState,
    receiver_film: FilmState,
    fixed_loss_voltage_v: float,
    series_asr_ohm_m2: float,
) -> dict[str, Any]:
    local = copy.deepcopy(base_config)
    local["model"]["temperature_c"] = temperature_c
    local["model"][
        "source_film_coefficient_mol_m2_s_activity"
    ] = source_film.activity_film_coefficient_mol_m2_s_activity
    local["model"][
        "receiver_film_coefficient_mol_m2_s_activity"
    ] = receiver_film.activity_film_coefficient_mol_m2_s_activity
    local["model"]["series_area_resistance_ohm_m2"] = series_asr_ohm_m2
    local["model"]["other_voltage_lower_bound_v"] = fixed_loss_voltage_v
    local["activity_cases"] = {
        "axial_local": {
            "source_bulk_water_activity": source_activity,
            "receiver_bulk_water_activity": receiver_activity,
            "interpretation": "Local axial state with controlled receiver boundary",
        }
    }
    return local

def solve_local_state(
    *,
    v2: ModuleType,
    v2_config: dict[str, Any],
    material: dict[str, Any],
    source_temperature_c: float,
    source_humidity_ratio: float,
    receiver_activity: float,
    terminal_voltage_v: float,
    fixed_loss_voltage_v: float,
    series_asr_ohm_m2: float,
    film_scale_factor: float,
    config: dict[str, Any],
    process_film_scale_factor: float | None = None,
    receiver_film_scale_factor: float | None = None,
) -> dict[str, Any]:
    air = config["air"]
    channel = config["channel"]
    pressure_pa = float(air["absolute_pressure_pa"])

    process_scale_factor = (
        film_scale_factor
        if process_film_scale_factor is None
        else process_film_scale_factor
    )

    receiver_scale_factor = (
        film_scale_factor
        if receiver_film_scale_factor is None
        else receiver_film_scale_factor
    )

    source_activity = activity_from_t_w(
        source_temperature_c, source_humidity_ratio, pressure_pa
    )
    if not ACTIVITY_EPS < source_activity < 1.0 - ACTIVITY_EPS:
        return {
            "solution_ok": False,
            "raw_solution_status": "source_bulk_activity_out_of_bounds",
            "solution_status": "source_bulk_activity_out_of_bounds",
            "source_bulk_activity": source_activity,
        }
    source_film = calculate_film_state(
        side="process",
        temperature_c=source_temperature_c,
        velocity_m_s=float(channel["process_velocity_m_s"]),
        gap_m=float(channel["process_gap_m"]),
        pressure_pa=pressure_pa,
        scale_factor=process_scale_factor,
    )
    receiver_temperature_c = float(channel["receiver_temperature_c"])
    receiver_film = calculate_film_state(
        side="receiver",
        temperature_c=receiver_temperature_c,
        velocity_m_s=float(channel["receiver_velocity_m_s"]),
        gap_m=float(channel["receiver_gap_m"]),
        pressure_pa=pressure_pa,
        scale_factor=receiver_scale_factor,
    )
    local_config = make_local_config(
        v2_config,
        temperature_c=source_temperature_c,
        source_activity=source_activity,
        receiver_activity=receiver_activity,
        source_film=source_film,
        receiver_film=receiver_film,
        fixed_loss_voltage_v=fixed_loss_voltage_v,
        series_asr_ohm_m2=series_asr_ohm_m2,
    )

    if material["model"] == "powerlaw":
        parameters = pd.DataFrame(
            {
                "water_drag": [float(material["water_drag"])],
                "water_diffusivity_m2_s": [
                    float(material["water_diffusivity_m2_s"])
                ],
                "conductivity_s_m": [float(material["conductivity_s_m"])],
                "dry_thickness_um": [float(material["dry_thickness_um"])],
                "applied_voltage_v": [terminal_voltage_v],
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
        solved = v2.solve_powerlaw_voltage_control(
            parameters, local_config, "axial_local"
        )
        record = solved.iloc[0].to_dict()
    elif material["model"] == "nafion":
        record, _ = v2.solve_nafion_voltage_state(
            source_bulk_activity=source_activity,
            receiver_bulk_activity=receiver_activity,
            temperature_c=source_temperature_c,
            dry_thickness_um=float(material["dry_thickness_um"]),
            applied_voltage_v=terminal_voltage_v,
            drag_scale_factor=float(material.get("drag_scale_factor", 1.0)),
            config=local_config,
            return_profile=False,
        )
    else:
        raise ValueError(f"Unknown material model: {material['model']}")

    solution_ok = bool(record["voltage_current_solution_ok"])
    raw_status = str(record["voltage_solution_status"])
    current = float(record.get("current_density_a_m2", math.nan))
    flux = float(record.get("net_flux_mol_m2_s", math.nan))
    ohmic_voltage = float(record.get("ohmic_voltage_v", math.nan))
    water_voltage = float(
        record.get("water_polarisation_voltage_v", math.nan)
    )
    membrane_voltage = ohmic_voltage + water_voltage
    series_loss_voltage = current * series_asr_ohm_m2
    calculated_cell_voltage = (
        membrane_voltage + series_loss_voltage + fixed_loss_voltage_v
    )
    return {
        **record,
        "solution_ok": solution_ok,
        "raw_solution_status": raw_status,
        "solution_status": status_category(raw_status, solution_ok),
        "source_bulk_activity": source_activity,
        "source_film_coefficient_mol_m2_s_activity": (
            source_film.activity_film_coefficient_mol_m2_s_activity
        ),
        "receiver_film_coefficient_mol_m2_s_activity": (
            receiver_film.activity_film_coefficient_mol_m2_s_activity
        ),
        "source_reynolds_number": source_film.reynolds_number,
        "receiver_reynolds_number": receiver_film.reynolds_number,
        "source_sherwood_number": source_film.sherwood_number,
        "receiver_sherwood_number": receiver_film.sherwood_number,
        "membrane_voltage_v": membrane_voltage,
        "series_loss_voltage_v": series_loss_voltage,
        "fixed_loss_voltage_v": fixed_loss_voltage_v,
        "calculated_terminal_voltage_v": calculated_cell_voltage,
        "terminal_voltage_error_v": calculated_cell_voltage - terminal_voltage_v,
        "cell_power_density_w_m2": terminal_voltage_v * current,
        "membrane_power_density_w_m2": membrane_voltage * current,
        "series_loss_power_density_w_m2": series_loss_voltage * current,
        "fixed_loss_power_density_w_m2": fixed_loss_voltage_v * current,
        "net_flux_mol_m2_s": flux,
    }

def local_derivatives(
    local: dict[str, Any],
    *,
    dry_air_mass_flow_kg_s: float,
    humidity_ratio: float,
    temperature_c: float,
    thermal_mode: str,
    thermal_config: dict[str, Any],
) -> tuple[float, float]:
    flux = float(local["net_flux_mol_m2_s"])
    d_w_d_area = (
        -MOLAR_MASS_WATER_KG_MOL * flux / dry_air_mass_flow_kg_s
    )
    if thermal_mode == "isothermal":
        return d_w_d_area, 0.0
    if thermal_mode != "adiabatic_upper_bound":
        raise ValueError(f"Unknown thermal mode: {thermal_mode}")
    heat_fraction = float(
        thermal_config["cell_power_to_process_air_fraction"]
    )
    heat_to_air_w_m2 = heat_fraction * float(
        local["cell_power_density_w_m2"]
    )
    cp_moist_air_j_kg_da_k = 1006.0 + 1860.0 * humidity_ratio
    d_t_d_area = heat_to_air_w_m2 / (
        dry_air_mass_flow_kg_s * cp_moist_air_j_kg_da_k
    )
    return d_w_d_area, d_t_d_area

def local_gate_status(
    local: dict[str, Any],
    *,
    current_cap_a_m2: float,
) -> str:
    if not bool(local.get("solution_ok", False)):
        return str(local.get("solution_status", "unknown_local_failure"))
    flux = float(local["net_flux_mol_m2_s"])
    current = float(local["current_density_a_m2"])
    if not math.isfinite(flux) or flux <= 0.0:
        return "nonpositive_net_water_flux"
    if not math.isfinite(current) or current <= 0.0:
        return "nonpositive_current_density"
    if current > current_cap_a_m2:
        return "operating_current_density_limit"
    return "local_gates_pass"

__all__ = [
    "status_category",
    "make_local_config",
    "solve_local_state",
    "local_derivatives",
    "local_gate_status",
]
