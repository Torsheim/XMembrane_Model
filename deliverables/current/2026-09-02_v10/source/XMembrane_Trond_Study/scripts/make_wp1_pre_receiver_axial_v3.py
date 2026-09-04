#!/usr/bin/env python3
"""Axial pre-receiver model built on the coupled V2 membrane solver.

This script fixes five limitations in the local V2 screening calculation:

1. O50 and O30 are fixed *humidity-ratio* targets at a declared reference
   temperature.  A temperature rise can therefore not create false drying.
2. The 150,000-cfm basis is explicit: actual inlet cfm or standard dry-air
   cfm.  Pressure, reference temperature and the resulting dry-air mass flow
   are written to the outputs.
3. The process stream is marched along active membrane area.  The coupled V2
   local membrane problem is solved at every area step, and both water removal
   and electrical power are integrated.
4. Terminal voltage is split into membrane, series-resistance and fixed-loss
   contributions.  Grid power includes power-electronics efficiency.
5. Numerical/physical solution statuses are retained separately from the
   operating gates.  An internal current-search ceiling is not reported as an
   operating-current failure or a generic profile error.

Gas-film coefficients are calculated from channel velocity, gap, gas
properties and a Sherwood correlation:

    K_a = Sh D_va / D_h * p_sat(T) / (R T)

where K_a has units mol m-2 s-1 per unit water activity.  This replaces the
unqualified K=15 default used in the first screening sweep.

The receiver remains a controlled boundary condition.  Receiver regeneration,
water removal, receiver-side fan power, electrodes and complete module design
remain outside scope.  Results are therefore conditional pre-receiver results.

Run from the HeiQ_V2 repository root:

    python -B scripts/make_wp1_pre_receiver_axial_v3.py

Fast verification:

    python -B scripts/make_wp1_pre_receiver_axial_v3.py --quick

The existing V2 package is expected at:

    heiq_pre_receiver_material_analyses/heiq_pre_receiver_model.py
"""

from __future__ import annotations

import argparse
import copy
from dataclasses import dataclass
import importlib.util
import json
import math
import os
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

os.environ.setdefault("MPLCONFIGDIR", "/tmp/heiq-pre-receiver-axial-v3-mpl")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


R_UNIVERSAL_J_MOL_K = 8.314462618
R_DRY_AIR_J_KG_K = 287.055
MOLAR_MASS_DRY_AIR_KG_MOL = R_UNIVERSAL_J_MOL_K / R_DRY_AIR_J_KG_K
MOLAR_MASS_WATER_KG_MOL = 0.01801528
CFM_TO_M3_S = 0.00047194745
HUMIDITY_RATIO_CONSTANT = 0.621945
ACTIVITY_EPS = 1.0e-7

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = Path(__file__).with_name("pre_receiver_axial_v3_config.json")
DEFAULT_V2_ROOT = REPO_ROOT / "heiq_pre_receiver_material_analyses"
DEFAULT_OUTPUT = REPO_ROOT / "outputs" / "pre_receiver_axial_v3"


@dataclass(frozen=True)
class AirflowBasis:
    basis: str
    input_cfm: float
    volume_flow_m3_s: float
    dry_air_mass_flow_kg_s: float
    inlet_water_vapour_pressure_pa: float
    inlet_humidity_ratio_kg_kg_da: float
    inlet_temperature_c: float
    inlet_relative_humidity: float
    absolute_pressure_pa: float
    standard_temperature_c: float | None
    standard_pressure_pa: float | None


@dataclass(frozen=True)
class FilmState:
    side: str
    temperature_c: float
    velocity_m_s: float
    gap_m: float
    hydraulic_diameter_m: float
    reynolds_number: float
    schmidt_number: float
    sherwood_number: float
    vapour_diffusivity_air_m2_s: float
    gas_mass_transfer_coefficient_m_s: float
    activity_film_coefficient_mol_m2_s_activity: float
    correlation_regime: str


def saturation_vapour_pressure_pa(temperature_c: float) -> float:
    """Buck saturation-pressure equation over liquid water."""
    return 611.21 * math.exp(
        (18.678 - temperature_c / 234.5)
        * (temperature_c / (257.14 + temperature_c))
    )


def humidity_ratio_from_t_rh(
    temperature_c: float,
    relative_humidity: float,
    pressure_pa: float,
) -> float:
    if not 0.0 < relative_humidity <= 1.0:
        raise ValueError("relative_humidity must lie in (0, 1]")
    p_water = relative_humidity * saturation_vapour_pressure_pa(temperature_c)
    if p_water >= pressure_pa:
        raise ValueError("Water-vapour pressure must be lower than total pressure")
    return HUMIDITY_RATIO_CONSTANT * p_water / (pressure_pa - p_water)


def vapour_pressure_from_humidity_ratio(
    humidity_ratio_kg_kg_da: float,
    pressure_pa: float,
) -> float:
    if humidity_ratio_kg_kg_da < 0.0:
        raise ValueError("Humidity ratio cannot be negative")
    return (
        pressure_pa
        * humidity_ratio_kg_kg_da
        / (HUMIDITY_RATIO_CONSTANT + humidity_ratio_kg_kg_da)
    )


def activity_from_t_w(
    temperature_c: float,
    humidity_ratio_kg_kg_da: float,
    pressure_pa: float,
) -> float:
    return vapour_pressure_from_humidity_ratio(
        humidity_ratio_kg_kg_da, pressure_pa
    ) / saturation_vapour_pressure_pa(temperature_c)


def relative_humidity_from_t_w(
    temperature_c: float,
    humidity_ratio_kg_kg_da: float,
    pressure_pa: float,
) -> float:
    return activity_from_t_w(
        temperature_c, humidity_ratio_kg_kg_da, pressure_pa
    )


def moist_air_enthalpy_kj_kg_da(
    temperature_c: float,
    humidity_ratio_kg_kg_da: float,
) -> float:
    return (
        1.006 * temperature_c
        + humidity_ratio_kg_kg_da * (2501.0 + 1.86 * temperature_c)
    )


def dry_air_mass_flow(config: dict[str, Any]) -> AirflowBasis:
    air = config["air"]
    input_cfm = float(air["airflow_cfm"])
    volume_flow = input_cfm * CFM_TO_M3_S
    inlet_temperature_c = float(air["inlet_temperature_c"])
    inlet_rh = float(air["inlet_relative_humidity"])
    pressure_pa = float(air["absolute_pressure_pa"])
    inlet_p_water = (
        inlet_rh * saturation_vapour_pressure_pa(inlet_temperature_c)
    )
    inlet_w = humidity_ratio_from_t_rh(
        inlet_temperature_c, inlet_rh, pressure_pa
    )
    basis = str(air["cfm_basis"])

    if basis == "actual_inlet":
        dry_air_molar_flow = (
            (pressure_pa - inlet_p_water)
            * volume_flow
            / (R_UNIVERSAL_J_MOL_K * (inlet_temperature_c + 273.15))
        )
        mass_flow = dry_air_molar_flow * MOLAR_MASS_DRY_AIR_KG_MOL
        standard_temperature = None
        standard_pressure = None
    elif basis == "standard_dry_air":
        standard_temperature = float(air["standard_temperature_c"])
        standard_pressure = float(air["standard_pressure_pa"])
        mass_flow = (
            standard_pressure
            * volume_flow
            / (R_DRY_AIR_J_KG_K * (standard_temperature + 273.15))
        )
    else:
        raise ValueError(
            "air.cfm_basis must be 'actual_inlet' or 'standard_dry_air'"
        )

    return AirflowBasis(
        basis=basis,
        input_cfm=input_cfm,
        volume_flow_m3_s=volume_flow,
        dry_air_mass_flow_kg_s=mass_flow,
        inlet_water_vapour_pressure_pa=inlet_p_water,
        inlet_humidity_ratio_kg_kg_da=inlet_w,
        inlet_temperature_c=inlet_temperature_c,
        inlet_relative_humidity=inlet_rh,
        absolute_pressure_pa=pressure_pa,
        standard_temperature_c=standard_temperature,
        standard_pressure_pa=standard_pressure,
    )


def dynamic_viscosity_air_pa_s(temperature_c: float) -> float:
    """Sutherland equation for air."""
    temperature_k = temperature_c + 273.15
    reference_temperature_k = 273.15
    reference_viscosity = 1.716e-5
    sutherland_temperature_k = 111.0
    return (
        reference_viscosity
        * (temperature_k / reference_temperature_k) ** 1.5
        * (reference_temperature_k + sutherland_temperature_k)
        / (temperature_k + sutherland_temperature_k)
    )


def water_vapour_diffusivity_air_m2_s(
    temperature_c: float,
    pressure_pa: float,
) -> float:
    """HVAC-scale temperature/pressure correction around 25 °C."""
    return (
        2.60e-5
        * ((temperature_c + 273.15) / 298.15) ** 1.81
        * (101_325.0 / pressure_pa)
    )


def sherwood_parallel_plate(
    reynolds_number: float,
    schmidt_number: float,
) -> tuple[float, str]:
    """Fully developed laminar value with a smooth turbulent transition."""
    laminar = 7.54
    turbulent = max(
        0.023
        * max(reynolds_number, 1.0) ** 0.83
        * max(schmidt_number, 1.0e-8) ** 0.44,
        laminar,
    )
    if reynolds_number <= 2300.0:
        return laminar, "laminar_fully_developed_parallel_plate"
    if reynolds_number >= 4000.0:
        return turbulent, "turbulent_chilton_colburn_screen"
    fraction = (reynolds_number - 2300.0) / (4000.0 - 2300.0)
    return (
        (1.0 - fraction) * laminar + fraction * turbulent,
        "transitional_interpolation",
    )


def calculate_film_state(
    *,
    side: str,
    temperature_c: float,
    velocity_m_s: float,
    gap_m: float,
    pressure_pa: float,
    scale_factor: float,
) -> FilmState:
    if velocity_m_s <= 0.0 or gap_m <= 0.0 or scale_factor <= 0.0:
        raise ValueError("Film geometry and scale factor must be positive")
    temperature_k = temperature_c + 273.15
    hydraulic_diameter = 2.0 * gap_m
    density = pressure_pa / (R_DRY_AIR_J_KG_K * temperature_k)
    viscosity = dynamic_viscosity_air_pa_s(temperature_c)
    diffusivity = water_vapour_diffusivity_air_m2_s(
        temperature_c, pressure_pa
    )
    reynolds = density * velocity_m_s * hydraulic_diameter / viscosity
    schmidt = viscosity / (density * diffusivity)
    sherwood, regime = sherwood_parallel_plate(reynolds, schmidt)
    k_gas = sherwood * diffusivity / hydraulic_diameter
    c_sat = saturation_vapour_pressure_pa(temperature_c) / (
        R_UNIVERSAL_J_MOL_K * temperature_k
    )
    k_activity = scale_factor * k_gas * c_sat
    return FilmState(
        side=side,
        temperature_c=temperature_c,
        velocity_m_s=velocity_m_s,
        gap_m=gap_m,
        hydraulic_diameter_m=hydraulic_diameter,
        reynolds_number=reynolds,
        schmidt_number=schmidt,
        sherwood_number=sherwood,
        vapour_diffusivity_air_m2_s=diffusivity,
        gas_mass_transfer_coefficient_m_s=k_gas,
        activity_film_coefficient_mol_m2_s_activity=k_activity,
        correlation_regime=regime,
    )


def load_v2_module(v2_root: Path) -> ModuleType:
    model_path = v2_root / "heiq_pre_receiver_model.py"
    if not model_path.is_file():
        raise FileNotFoundError(
            f"V2 model not found at {model_path}. "
            "Unpack HeiQ_pre_receiver_material_analyses_v2.zip at the "
            "HeiQ_V2 repository root or pass --v2-root."
        )
    spec = importlib.util.spec_from_file_location(
        "heiq_pre_receiver_model_v2", model_path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not import V2 model from {model_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, data: Any) -> None:
    path.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def validate_config(config: dict[str, Any]) -> None:
    for name in (
        "air",
        "targets",
        "receiver_boundaries",
        "channel",
        "electrical",
        "thermal",
        "integration",
        "materials",
    ):
        if name not in config:
            raise ValueError(f"Configuration is missing top-level key: {name}")
    if not config["materials"]:
        raise ValueError("At least one material design is required")
    if not 0.0 < float(config["air"]["inlet_relative_humidity"]) <= 1.0:
        raise ValueError("Inlet relative humidity must lie in (0, 1]")
    for target, values in config["targets"].items():
        rh = float(values["reference_relative_humidity"])
        if not 0.0 < rh < float(config["air"]["inlet_relative_humidity"]):
            raise ValueError(f"Target {target} has an invalid reference RH")
    for label, values in config["receiver_boundaries"].items():
        activity = float(values["water_activity"])
        if not 0.0 < activity < 1.0:
            raise ValueError(f"Receiver activity {label} must lie in (0, 1)")
    for efficiency in config["electrical"]["power_electronics_efficiencies"]:
        if not 0.0 < float(efficiency) <= 1.0:
            raise ValueError("Power-electronics efficiency must lie in (0, 1]")


def build_targets(
    config: dict[str, Any],
    basis: AirflowBasis,
    v2_config: dict[str, Any],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    inlet_w = basis.inlet_humidity_ratio_kg_kg_da
    for label, target in config["targets"].items():
        reference_temperature = float(target["reference_temperature_c"])
        reference_rh = float(target["reference_relative_humidity"])
        target_w = humidity_ratio_from_t_rh(
            reference_temperature,
            reference_rh,
            basis.absolute_pressure_pa,
        )
        water_load = (
            basis.dry_air_mass_flow_kg_s * (inlet_w - target_w) * 3600.0
        )
        legacy = v2_config.get("scenarios", {}).get(label, {})
        legacy_load = float(legacy.get("water_load_kg_h", math.nan))
        legacy_gross = float(
            legacy.get("gross_hvac_electric_opportunity_kw", math.nan)
        )
        if math.isfinite(legacy_load) and legacy_load > 0.0:
            gross_hvac = legacy_gross * water_load / legacy_load
        else:
            gross_hvac = math.nan
        rows.append(
            {
                "target": label,
                "target_definition": "fixed_humidity_ratio_at_reference_state",
                "reference_temperature_c": reference_temperature,
                "reference_relative_humidity": reference_rh,
                "target_humidity_ratio_kg_kg_da": target_w,
                "target_humidity_ratio_g_kg_da": 1000.0 * target_w,
                "computed_water_load_kg_h": water_load,
                "legacy_v2_water_load_kg_h": legacy_load,
                "water_load_difference_percent": (
                    100.0 * (water_load / legacy_load - 1.0)
                    if math.isfinite(legacy_load) and legacy_load > 0.0
                    else math.nan
                ),
                "scaled_gross_hvac_opportunity_kw": gross_hvac,
            }
        )
    return pd.DataFrame(rows)


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
) -> dict[str, Any]:
    air = config["air"]
    channel = config["channel"]
    pressure_pa = float(air["absolute_pressure_pa"])
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
        scale_factor=film_scale_factor,
    )
    receiver_temperature_c = float(channel["receiver_temperature_c"])
    receiver_film = calculate_film_state(
        side="receiver",
        temperature_c=receiver_temperature_c,
        velocity_m_s=float(channel["receiver_velocity_m_s"]),
        gap_m=float(channel["receiver_gap_m"]),
        pressure_pa=pressure_pa,
        scale_factor=film_scale_factor,
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


def integrate_axial_case(
    *,
    v2: ModuleType,
    v2_config: dict[str, Any],
    config: dict[str, Any],
    basis: AirflowBasis,
    target_row: pd.Series,
    material: dict[str, Any],
    receiver_label: str,
    receiver_activity: float,
    terminal_voltage_v: float,
    fixed_loss_voltage_v: float,
    series_asr_ohm_m2: float,
    power_electronics_efficiency: float,
    current_cap_a_m2: float,
    film_scale_factor: float,
    thermal_mode: str,
    record_profile: bool,
) -> tuple[dict[str, Any], pd.DataFrame]:
    integration = config["integration"]
    thermal_config = config["thermal"]
    area_limit = float(integration["area_limit_m2"])
    nominal_step = float(integration["area_step_m2"])
    minimum_step = float(integration["minimum_area_step_m2"])
    target_w = float(target_row["target_humidity_ratio_kg_kg_da"])
    inlet_w = basis.inlet_humidity_ratio_kg_kg_da
    humidity_ratio = inlet_w
    temperature_c = basis.inlet_temperature_c
    cumulative_area = 0.0
    cell_power_w = 0.0
    membrane_power_w = 0.0
    series_loss_power_w = 0.0
    fixed_loss_power_w = 0.0
    current_integral_a = 0.0
    molar_transfer_integral_mol_s = 0.0
    profile_rows: list[dict[str, Any]] = []
    maximum_current = -math.inf
    minimum_flux = math.inf
    maximum_temperature = temperature_c
    status = "area_limit_before_target"
    last_local: dict[str, Any] | None = None

    def solve_at(water_ratio: float, temp_c: float) -> dict[str, Any]:
        return solve_local_state(
            v2=v2,
            v2_config=v2_config,
            material=material,
            source_temperature_c=temp_c,
            source_humidity_ratio=water_ratio,
            receiver_activity=receiver_activity,
            terminal_voltage_v=terminal_voltage_v,
            fixed_loss_voltage_v=fixed_loss_voltage_v,
            series_asr_ohm_m2=series_asr_ohm_m2,
            film_scale_factor=film_scale_factor,
            config=config,
        )

    while cumulative_area < area_limit - 1.0e-12:
        if humidity_ratio <= target_w + float(
            integration["humidity_ratio_absolute_tolerance"]
        ):
            status = "target_reached"
            break
        step = min(nominal_step, area_limit - cumulative_area)
        local_start = solve_at(humidity_ratio, temperature_c)
        gate = local_gate_status(
            local_start, current_cap_a_m2=current_cap_a_m2
        )
        if gate != "local_gates_pass":
            status = gate
            last_local = local_start
            break
        derivative_start = local_derivatives(
            local_start,
            dry_air_mass_flow_kg_s=basis.dry_air_mass_flow_kg_s,
            humidity_ratio=humidity_ratio,
            temperature_c=temperature_c,
            thermal_mode=thermal_mode,
            thermal_config=thermal_config,
        )

        while True:
            predicted_w = humidity_ratio + derivative_start[0] * step
            predicted_t = temperature_c + derivative_start[1] * step
            if predicted_w <= 0.0:
                local_end = {"solution_ok": False}
                end_gate = "predictor_negative_humidity_ratio"
            else:
                local_end = solve_at(predicted_w, predicted_t)
                end_gate = local_gate_status(
                    local_end, current_cap_a_m2=current_cap_a_m2
                )
            if end_gate == "local_gates_pass":
                break
            if step <= minimum_step + 1.0e-12:
                status = f"corrector_failure:{end_gate}"
                last_local = local_end
                break
            step = max(0.5 * step, minimum_step)
        if status.startswith("corrector_failure:"):
            break

        derivative_end = local_derivatives(
            local_end,
            dry_air_mass_flow_kg_s=basis.dry_air_mass_flow_kg_s,
            humidity_ratio=predicted_w,
            temperature_c=predicted_t,
            thermal_mode=thermal_mode,
            thermal_config=thermal_config,
        )
        corrected_w = humidity_ratio + 0.5 * (
            derivative_start[0] + derivative_end[0]
        ) * step
        corrected_t = temperature_c + 0.5 * (
            derivative_start[1] + derivative_end[1]
        ) * step
        step_fraction = 1.0
        if corrected_w < target_w:
            denominator = humidity_ratio - corrected_w
            step_fraction = (
                (humidity_ratio - target_w) / denominator
                if denominator > 0.0
                else 0.0
            )
            step_fraction = float(np.clip(step_fraction, 0.0, 1.0))
        effective_step = step * step_fraction
        next_w = humidity_ratio + step_fraction * (
            corrected_w - humidity_ratio
        )
        next_t = temperature_c + step_fraction * (
            corrected_t - temperature_c
        )

        def average(name: str) -> float:
            return 0.5 * (
                float(local_start[name]) + float(local_end[name])
            )

        mean_current = average("current_density_a_m2")
        mean_flux = average("net_flux_mol_m2_s")
        mean_cell_power_density = terminal_voltage_v * mean_current
        mean_membrane_power_density = average(
            "membrane_power_density_w_m2"
        )
        mean_series_power_density = average(
            "series_loss_power_density_w_m2"
        )
        mean_fixed_power_density = average(
            "fixed_loss_power_density_w_m2"
        )
        cell_power_w += mean_cell_power_density * effective_step
        membrane_power_w += mean_membrane_power_density * effective_step
        series_loss_power_w += mean_series_power_density * effective_step
        fixed_loss_power_w += mean_fixed_power_density * effective_step
        current_integral_a += mean_current * effective_step
        molar_transfer_integral_mol_s += mean_flux * effective_step
        maximum_current = max(
            maximum_current,
            float(local_start["current_density_a_m2"]),
            float(local_end["current_density_a_m2"]),
        )
        minimum_flux = min(
            minimum_flux,
            float(local_start["net_flux_mol_m2_s"]),
            float(local_end["net_flux_mol_m2_s"]),
        )
        maximum_temperature = max(maximum_temperature, next_t)

        if record_profile:
            profile_rows.append(
                {
                    "target": target_row["target"],
                    "material": material["name"],
                    "receiver_boundary": receiver_label,
                    "thermal_mode": thermal_mode,
                    "terminal_voltage_v": terminal_voltage_v,
                    "fixed_loss_voltage_v": fixed_loss_voltage_v,
                    "series_asr_ohm_m2": series_asr_ohm_m2,
                    "power_electronics_efficiency": (
                        power_electronics_efficiency
                    ),
                    "current_cap_a_m2": current_cap_a_m2,
                    "film_scale_factor": film_scale_factor,
                    "step_area_m2": effective_step,
                    "cumulative_area_m2": cumulative_area + effective_step,
                    "humidity_ratio_kg_kg_da": next_w,
                    "humidity_ratio_g_kg_da": 1000.0 * next_w,
                    "temperature_c": next_t,
                    "relative_humidity": relative_humidity_from_t_w(
                        next_t, next_w, basis.absolute_pressure_pa
                    ),
                    "source_bulk_activity": activity_from_t_w(
                        next_t, next_w, basis.absolute_pressure_pa
                    ),
                    "receiver_bulk_activity": receiver_activity,
                    "net_flux_mol_m2_s": mean_flux,
                    "net_flux_kg_m2_h": (
                        mean_flux * MOLAR_MASS_WATER_KG_MOL * 3600.0
                    ),
                    "current_density_a_m2": mean_current,
                    "membrane_voltage_v": average("membrane_voltage_v"),
                    "series_loss_voltage_v": average(
                        "series_loss_voltage_v"
                    ),
                    "source_surface_activity": average(
                        "source_surface_activity"
                    ),
                    "receiver_surface_activity": average(
                        "receiver_surface_activity"
                    ),
                    "source_film_coefficient_mol_m2_s_activity": average(
                        "source_film_coefficient_mol_m2_s_activity"
                    ),
                    "receiver_film_coefficient_mol_m2_s_activity": average(
                        "receiver_film_coefficient_mol_m2_s_activity"
                    ),
                    "cell_power_density_w_m2": mean_cell_power_density,
                    "cumulative_cell_power_kw": cell_power_w / 1000.0,
                }
            )

        cumulative_area += effective_step
        humidity_ratio = next_w
        temperature_c = next_t
        last_local = local_end
        if step_fraction < 1.0:
            status = "target_reached"
            break

    grid_power_kw = (
        cell_power_w / power_electronics_efficiency / 1000.0
        if math.isfinite(cell_power_w)
        else math.inf
    )
    power_electronics_loss_kw = (
        grid_power_kw - cell_power_w / 1000.0
        if math.isfinite(grid_power_kw)
        else math.inf
    )
    integrated_water_kg_h = (
        molar_transfer_integral_mol_s
        * MOLAR_MASS_WATER_KG_MOL
        * 3600.0
    )
    air_balance_water_kg_h = (
        basis.dry_air_mass_flow_kg_s
        * (inlet_w - humidity_ratio)
        * 3600.0
    )
    balance_scale = max(
        abs(integrated_water_kg_h), abs(air_balance_water_kg_h), 1.0e-12
    )
    mass_balance_relative_error = (
        integrated_water_kg_h - air_balance_water_kg_h
    ) / balance_scale
    profile = pd.DataFrame(profile_rows)
    raw_status = (
        str(last_local.get("raw_solution_status", "not_applicable"))
        if last_local is not None
        else "not_applicable"
    )
    return (
        {
            "target": target_row["target"],
            "material": material["name"],
            "material_model": material["model"],
            "receiver_boundary": receiver_label,
            "receiver_bulk_activity": receiver_activity,
            "thermal_mode": thermal_mode,
            "terminal_voltage_v": terminal_voltage_v,
            "fixed_loss_voltage_v": fixed_loss_voltage_v,
            "series_asr_ohm_m2": series_asr_ohm_m2,
            "power_electronics_efficiency": power_electronics_efficiency,
            "current_cap_a_m2": current_cap_a_m2,
            "internal_current_search_ceiling_a_m2": float(
                v2_config["model"]["current_solver_upper_bound_a_m2"]
            ),
            "film_scale_factor": film_scale_factor,
            "status": status,
            "last_raw_local_solution_status": raw_status,
            "target_reached": status == "target_reached",
            "required_active_area_m2": cumulative_area,
            "outlet_humidity_ratio_kg_kg_da": humidity_ratio,
            "target_humidity_ratio_kg_kg_da": target_w,
            "outlet_temperature_c": temperature_c,
            "maximum_process_temperature_c": maximum_temperature,
            "outlet_relative_humidity": relative_humidity_from_t_w(
                temperature_c, humidity_ratio, basis.absolute_pressure_pa
            ),
            "outlet_water_activity": activity_from_t_w(
                temperature_c, humidity_ratio, basis.absolute_pressure_pa
            ),
            "integrated_water_removal_kg_h": integrated_water_kg_h,
            "air_balance_water_removal_kg_h": air_balance_water_kg_h,
            "water_mass_balance_relative_error": mass_balance_relative_error,
            "maximum_local_current_density_a_m2": (
                maximum_current if maximum_current > -math.inf else math.nan
            ),
            "minimum_local_flux_mol_m2_s": (
                minimum_flux if minimum_flux < math.inf else math.nan
            ),
            "integrated_current_a": current_integral_a,
            "cell_power_kw": cell_power_w / 1000.0,
            "membrane_power_kw": membrane_power_w / 1000.0,
            "series_loss_power_kw": series_loss_power_w / 1000.0,
            "fixed_loss_power_kw": fixed_loss_power_w / 1000.0,
            "power_electronics_loss_kw": power_electronics_loss_kw,
            "eo_grid_power_kw": grid_power_kw,
            "eo_grid_sec_kwh_kg": (
                grid_power_kw / integrated_water_kg_h
                if integrated_water_kg_h > 0.0
                else math.inf
            ),
        },
        profile,
    )


def process_channel_fan(
    *,
    active_area_m2: float,
    config: dict[str, Any],
    basis: AirflowBasis,
) -> dict[str, float]:
    """Close one transparent process-channel geometry after area is known."""
    channel = config["channel"]
    gap = float(channel["process_gap_m"])
    velocity = float(channel["process_velocity_m_s"])
    active_sides = float(channel["active_sides_per_process_channel"])
    fan_efficiency = float(channel["process_fan_efficiency"])
    open_flow_area = basis.volume_flow_m3_s / velocity
    total_channel_width = open_flow_area / gap
    channel_length = (
        active_area_m2 / (active_sides * total_channel_width)
        if active_area_m2 > 0.0
        else 0.0
    )
    inlet_temperature_k = basis.inlet_temperature_c + 273.15
    density = basis.absolute_pressure_pa / (
        R_DRY_AIR_J_KG_K * inlet_temperature_k
    )
    viscosity = dynamic_viscosity_air_pa_s(basis.inlet_temperature_c)
    hydraulic_diameter = 2.0 * gap
    reynolds = density * velocity * hydraulic_diameter / viscosity
    if reynolds <= 2300.0:
        pressure_drop = (
            12.0 * viscosity * channel_length * velocity / gap**2
        )
    else:
        friction_factor = 0.3164 * reynolds ** -0.25
        pressure_drop = (
            friction_factor
            * channel_length
            / hydraulic_diameter
            * density
            * velocity**2
            / 2.0
        )
    fan_power_kw = (
        pressure_drop
        * basis.volume_flow_m3_s
        / fan_efficiency
        / 1000.0
    )
    return {
        "process_channel_length_m": channel_length,
        "process_total_channel_width_m": total_channel_width,
        "process_open_flow_area_m2": open_flow_area,
        "process_channel_reynolds_number": reynolds,
        "process_pressure_drop_pa": pressure_drop,
        "process_fan_power_kw": fan_power_kw,
    }


def add_system_accounting(
    summary: pd.DataFrame,
    targets: pd.DataFrame,
    config: dict[str, Any],
    basis: AirflowBasis,
) -> pd.DataFrame:
    target_budget = targets.set_index("target")[
        "scaled_gross_hvac_opportunity_kw"
    ].to_dict()
    rows: list[dict[str, Any]] = []
    for _, row in summary.iterrows():
        geometry = process_channel_fan(
            active_area_m2=float(row["required_active_area_m2"]),
            config=config,
            basis=basis,
        )
        gross = float(target_budget[row["target"]])
        grid = float(row["eo_grid_power_kw"])
        fan = geometry["process_fan_power_kw"]
        target_reached = bool(row["target_reached"])
        residual = gross - grid - fan if target_reached else math.nan
        rows.append(
            {
                **row.to_dict(),
                **geometry,
                "gross_hvac_electric_opportunity_kw": gross,
                "conditional_net_electric_saving_kw": residual,
                "conditional_net_saving_percent": (
                    100.0 * residual / gross
                    if target_reached and gross > 0.0
                    else math.nan
                ),
                "energy_gate_ok": bool(
                    target_reached and residual >= 0.0
                ),
                "scope": (
                    "conditional_pre_receiver; receiver regeneration, "
                    "receiver fan, electrodes and water removal excluded"
                ),
            }
        )
    return pd.DataFrame(rows)


def configure_plots() -> None:
    plt.rcParams.update(
        {
            "font.size": 9.5,
            "axes.titlesize": 10.5,
            "axes.labelsize": 9.5,
            "xtick.labelsize": 8.5,
            "ytick.labelsize": 8.5,
            "legend.fontsize": 7.7,
            "figure.dpi": 150,
            "savefig.dpi": 220,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )


def save_figure(fig: plt.Figure, output_dir: Path, stem: str) -> None:
    for suffix in ("png", "pdf"):
        path = output_dir / f"{stem}.{suffix}"
        fig.savefig(path, format=suffix, bbox_inches="tight")
    plt.close(fig)


def plot_summary(
    summary: pd.DataFrame,
    output_dir: Path,
) -> None:
    completed = summary[
        summary["target_reached"]
        & (summary["thermal_mode"] == "isothermal")
    ].copy()
    if completed.empty:
        return
    minimum_loss = float(completed["fixed_loss_voltage_v"].min())
    completed = completed[
        np.isclose(completed["fixed_loss_voltage_v"], minimum_loss)
    ]
    fig, axes = plt.subplots(2, 2, figsize=(10.0, 7.0), sharex="col")
    colours = {
        label: colour
        for label, colour in zip(
            sorted(completed["receiver_boundary"].unique()),
            ("#2878B5", "#F28E2B", "#C73E1D", "#59A14F"),
        )
    }
    for row_index, target in enumerate(("O50", "O30")):
        subset = completed[completed["target"] == target]
        for receiver, group in subset.groupby("receiver_boundary"):
            ordered = group.sort_values("terminal_voltage_v")
            axes[row_index, 0].plot(
                ordered["terminal_voltage_v"],
                ordered["required_active_area_m2"],
                marker="o",
                label=receiver,
                color=colours[receiver],
            )
            axes[row_index, 1].plot(
                ordered["terminal_voltage_v"],
                ordered["eo_grid_power_kw"],
                marker="o",
                label=receiver,
                color=colours[receiver],
            )
        axes[row_index, 0].set_ylabel(f"{target}: active area [m²]")
        axes[row_index, 1].set_ylabel(f"{target}: grid power [kW]")
        axes[row_index, 0].grid(alpha=0.25)
        axes[row_index, 1].grid(alpha=0.25)
    axes[1, 0].set_xlabel("Terminal cell voltage [V]")
    axes[1, 1].set_xlabel("Terminal cell voltage [V]")
    axes[0, 0].set_title(
        f"Axially integrated area; fixed loss={minimum_loss:g} V"
    )
    axes[0, 1].set_title(
        "Grid power including power-electronics efficiency"
    )
    handles, labels = axes[0, 0].get_legend_handles_labels()
    if handles:
        fig.legend(handles, labels, loc="lower center", ncol=len(handles))
        fig.subplots_adjust(bottom=0.12)
    save_figure(fig, output_dir, "01_axial_area_and_grid_power")


def plot_profiles(profiles: pd.DataFrame, output_dir: Path) -> None:
    if profiles.empty:
        return
    preferred = profiles[
        (profiles["thermal_mode"] == "isothermal")
        & (profiles["receiver_boundary"] == "symmetric_80_80")
    ].copy()
    if preferred.empty:
        preferred = profiles.copy()
    selected_keys: list[tuple[Any, ...]] = []
    key_columns = [
        "target",
        "material",
        "receiver_boundary",
        "thermal_mode",
        "terminal_voltage_v",
        "fixed_loss_voltage_v",
        "series_asr_ohm_m2",
        "power_electronics_efficiency",
        "current_cap_a_m2",
        "film_scale_factor",
    ]
    for target in sorted(preferred["target"].unique()):
        target_profiles = preferred[preferred["target"] == target]
        cases = target_profiles[key_columns].drop_duplicates()
        cases["distance"] = (
            cases["terminal_voltage_v"].sub(1.0).abs()
            + cases["fixed_loss_voltage_v"].abs()
        )
        selected = cases.sort_values("distance").iloc[0]
        selected_keys.append(tuple(selected[column] for column in key_columns))
    fig, axes = plt.subplots(1, 3, figsize=(12.0, 3.8))
    for key in selected_keys:
        mask = np.ones(len(preferred), dtype=bool)
        for column, value in zip(key_columns, key):
            mask &= preferred[column].to_numpy() == value
        group = preferred.loc[mask].sort_values("cumulative_area_m2")
        if group.empty:
            continue
        label = f"{key[0]}, {key[4]:g} V"
        axes[0].plot(
            group["cumulative_area_m2"],
            group["humidity_ratio_g_kg_da"],
            label=label,
        )
        axes[1].plot(
            group["cumulative_area_m2"],
            100.0 * group["relative_humidity"],
            label=label,
        )
        axes[2].plot(
            group["cumulative_area_m2"],
            group["net_flux_kg_m2_h"],
            label=label,
        )
    axes[0].set_ylabel("Humidity ratio [g/kg dry air]")
    axes[1].set_ylabel("Relative humidity [%]")
    axes[2].set_ylabel("Local net flux [kg m⁻² h⁻¹]")
    for axis in axes:
        axis.set_xlabel("Cumulative active area [m²]")
        axis.grid(alpha=0.25)
    axes[0].legend()
    fig.suptitle(
        "Fixed humidity-ratio targets; RH is a reported state, not the stop criterion"
    )
    save_figure(fig, output_dir, "02_selected_axial_profiles")


def make_summary_markdown(
    *,
    basis: AirflowBasis,
    targets: pd.DataFrame,
    film_rows: pd.DataFrame,
    summary: pd.DataFrame,
) -> str:
    counts = summary["status"].value_counts(dropna=False)
    lines = [
        "# Axial pre-receiver calculation — v3",
        "",
        "## Basis",
        "",
        f"- Airflow: {basis.input_cfm:,.0f} cfm, basis `{basis.basis}`.",
        (
            f"- Dry-air mass flow: "
            f"{basis.dry_air_mass_flow_kg_s:.4f} kg dry air/s."
        ),
        (
            f"- Inlet: {basis.inlet_temperature_c:.2f} °C, "
            f"{100.0 * basis.inlet_relative_humidity:.1f} % RH, "
            f"{1000.0 * basis.inlet_humidity_ratio_kg_kg_da:.4f} "
            "g/kg dry air."
        ),
        "- O50/O30 are fixed humidity-ratio targets at their declared reference state.",
        "",
        "## Recalculated water loads",
        "",
    ]
    for _, row in targets.iterrows():
        lines.append(
            f"- {row['target']}: {row['computed_water_load_kg_h']:.2f} kg/h "
            f"(V2 reference {row['legacy_v2_water_load_kg_h']:.2f} kg/h; "
            f"difference {row['water_load_difference_percent']:+.2f} %)."
        )
    lines.extend(
        [
            "",
            "## Gas-film calculation",
            "",
        ]
    )
    for _, row in film_rows.iterrows():
        lines.append(
            f"- {row['side']}: K={row['activity_film_coefficient_mol_m2_s_activity']:.5g} "
            "mol m⁻² s⁻¹ activity⁻¹, "
            f"Re={row['reynolds_number']:.0f}, "
            f"Sh={row['sherwood_number']:.3g}, "
            f"`{row['correlation_regime']}`."
        )
    lines.extend(["", "## Run status", ""])
    for status, count in counts.items():
        lines.append(f"- `{status}`: {int(count)} cases.")
    lines.extend(
        [
            "",
            "## Scope",
            "",
            (
                "The receiver is still a controlled boundary condition. "
                "Receiver regeneration, water removal, receiver-side fan power, "
                "electrodes, degradation and complete module design are excluded. "
                "The energy result is therefore a conditional pre-receiver result."
            ),
            "",
            (
                "The adiabatic case is an upper thermal bound that deposits the "
                "configured fraction of cell electrical power into the process air. "
                "It is not a prediction of the actual heat split."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def reduced_quick_config(config: dict[str, Any]) -> dict[str, Any]:
    quick = copy.deepcopy(config)
    quick["receiver_boundaries"] = {
        "dry_receiver_80_50": quick["receiver_boundaries"][
            "dry_receiver_80_50"
        ]
    }
    quick["electrical"]["terminal_voltages_v"] = [
        quick["electrical"]["terminal_voltages_v"][-1]
    ]
    quick["electrical"]["fixed_loss_voltages_v"] = [
        quick["electrical"]["fixed_loss_voltages_v"][0]
    ]
    quick["thermal"]["modes"] = ["isothermal"]
    quick["materials"] = [quick["materials"][0]]
    quick["integration"]["area_step_m2"] = max(
        50.0, float(quick["integration"]["area_step_m2"])
    )
    return quick


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--v2-root", type=Path, default=DEFAULT_V2_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()

    config = load_json(args.config)
    validate_config(config)
    if args.quick:
        config = reduced_quick_config(config)
    v2 = load_v2_module(args.v2_root.resolve())
    v2_config_path = (
        args.v2_root.resolve() / "config" / "default.json"
    )
    v2_config = v2.load_config(v2_config_path)
    basis = dry_air_mass_flow(config)
    targets = build_targets(config, basis, v2_config)
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    inlet_process_film = calculate_film_state(
        side="process",
        temperature_c=basis.inlet_temperature_c,
        velocity_m_s=float(config["channel"]["process_velocity_m_s"]),
        gap_m=float(config["channel"]["process_gap_m"]),
        pressure_pa=basis.absolute_pressure_pa,
        scale_factor=1.0,
    )
    receiver_film = calculate_film_state(
        side="receiver",
        temperature_c=float(config["channel"]["receiver_temperature_c"]),
        velocity_m_s=float(config["channel"]["receiver_velocity_m_s"]),
        gap_m=float(config["channel"]["receiver_gap_m"]),
        pressure_pa=basis.absolute_pressure_pa,
        scale_factor=1.0,
    )
    film_rows = pd.DataFrame(
        [inlet_process_film.__dict__, receiver_film.__dict__]
    )

    summary_rows: list[dict[str, Any]] = []
    profiles: list[pd.DataFrame] = []
    combinations = (
        len(config["targets"])
        * len(config["materials"])
        * len(config["receiver_boundaries"])
        * len(config["electrical"]["terminal_voltages_v"])
        * len(config["electrical"]["fixed_loss_voltages_v"])
        * len(config["electrical"]["series_area_resistances_ohm_m2"])
        * len(config["electrical"]["power_electronics_efficiencies"])
        * len(config["electrical"]["current_density_caps_a_m2"])
        * len(config["channel"]["film_coefficient_scale_factors"])
        * len(config["thermal"]["modes"])
    )
    completed = 0
    for _, target_row in targets.iterrows():
        for material in config["materials"]:
            for receiver_label, receiver in config[
                "receiver_boundaries"
            ].items():
                for terminal_voltage in config["electrical"][
                    "terminal_voltages_v"
                ]:
                    for fixed_loss in config["electrical"][
                        "fixed_loss_voltages_v"
                    ]:
                        for series_asr in config["electrical"][
                            "series_area_resistances_ohm_m2"
                        ]:
                            for efficiency in config["electrical"][
                                "power_electronics_efficiencies"
                            ]:
                                for current_cap in config["electrical"][
                                    "current_density_caps_a_m2"
                                ]:
                                    for film_scale in config["channel"][
                                        "film_coefficient_scale_factors"
                                    ]:
                                        for thermal_mode in config["thermal"][
                                            "modes"
                                        ]:
                                            summary, profile = integrate_axial_case(
                                                v2=v2,
                                                v2_config=v2_config,
                                                config=config,
                                                basis=basis,
                                                target_row=target_row,
                                                material=material,
                                                receiver_label=receiver_label,
                                                receiver_activity=float(
                                                    receiver["water_activity"]
                                                ),
                                                terminal_voltage_v=float(
                                                    terminal_voltage
                                                ),
                                                fixed_loss_voltage_v=float(
                                                    fixed_loss
                                                ),
                                                series_asr_ohm_m2=float(
                                                    series_asr
                                                ),
                                                power_electronics_efficiency=float(
                                                    efficiency
                                                ),
                                                current_cap_a_m2=float(
                                                    current_cap
                                                ),
                                                film_scale_factor=float(
                                                    film_scale
                                                ),
                                                thermal_mode=str(thermal_mode),
                                                record_profile=True,
                                            )
                                            summary_rows.append(summary)
                                            if not profile.empty:
                                                profiles.append(profile)
                                            completed += 1
                                            if (
                                                combinations >= 20
                                                and completed
                                                % max(1, combinations // 10)
                                                == 0
                                            ):
                                                print(
                                                    f"Completed {completed:,}/"
                                                    f"{combinations:,} cases",
                                                    flush=True,
                                                )

    summary = pd.DataFrame(summary_rows)
    summary = add_system_accounting(
        summary, targets, config, basis
    )
    profile_frame = (
        pd.concat(profiles, ignore_index=True)
        if profiles
        else pd.DataFrame()
    )
    status_counts = (
        summary.groupby(
            [
                "target",
                "receiver_boundary",
                "thermal_mode",
                "status",
            ],
            dropna=False,
        )
        .size()
        .rename("case_count")
        .reset_index()
    )
    basis_frame = pd.DataFrame(
        [
            {
                **basis.__dict__,
                "inlet_humidity_ratio_g_kg_da": (
                    1000.0 * basis.inlet_humidity_ratio_kg_kg_da
                ),
                "inlet_enthalpy_kj_kg_da": moist_air_enthalpy_kj_kg_da(
                    basis.inlet_temperature_c,
                    basis.inlet_humidity_ratio_kg_kg_da,
                ),
            }
        ]
    )

    basis_frame.to_csv(output_dir / "airflow_basis.csv", index=False)
    targets.to_csv(output_dir / "humidity_ratio_targets.csv", index=False)
    film_rows.to_csv(
        output_dir / "gas_film_coefficients.csv", index=False
    )
    summary.to_csv(output_dir / "axial_case_summary.csv", index=False)
    status_counts.to_csv(output_dir / "status_counts.csv", index=False)
    if not profile_frame.empty:
        profile_frame.to_csv(
            output_dir / "axial_profiles.csv.gz",
            index=False,
            compression="gzip",
        )
    write_json(output_dir / "config_used.json", config)
    write_json(
        output_dir / "method_metadata.json",
        {
            "model_version": 3,
            "v2_model_path": str(
                args.v2_root.resolve() / "heiq_pre_receiver_model.py"
            ),
            "target_stop_criterion": (
                "humidity_ratio <= target humidity ratio defined at "
                "target reference temperature/RH"
            ),
            "power_integral": (
                "P_grid = integral(V_terminal(A)*j(A) dA) / eta_PE"
            ),
            "receiver_scope": "controlled boundary condition only",
            "quick_mode": bool(args.quick),
        },
    )
    configure_plots()
    plot_summary(summary, output_dir)
    plot_profiles(profile_frame, output_dir)
    (output_dir / "summary.md").write_text(
        make_summary_markdown(
            basis=basis,
            targets=targets,
            film_rows=film_rows,
            summary=summary,
        ),
        encoding="utf-8",
    )

    print(f"Wrote results to {output_dir}")
    print(summary["status"].value_counts(dropna=False).to_string())


if __name__ == "__main__":
    main()
