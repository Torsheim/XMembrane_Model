from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

R_UNIVERSAL_J_MOL_K = 8.314462618
R_DRY_AIR_J_KG_K = 287.055
MOLAR_MASS_DRY_AIR_KG_MOL = R_UNIVERSAL_J_MOL_K / R_DRY_AIR_J_KG_K
MOLAR_MASS_WATER_KG_MOL = 0.01801528
CFM_TO_M3_S = 0.00047194745
HUMIDITY_RATIO_CONSTANT = 0.621945
ACTIVITY_EPS = 1.0e-7

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


__all__ = [
    "AirflowBasis",
    "FilmState",
    "R_UNIVERSAL_J_MOL_K",
    "R_DRY_AIR_J_KG_K",
    "MOLAR_MASS_DRY_AIR_KG_MOL",
    "MOLAR_MASS_WATER_KG_MOL",
    "CFM_TO_M3_S",
    "HUMIDITY_RATIO_CONSTANT",
    "ACTIVITY_EPS",
    "saturation_vapour_pressure_pa",
    "humidity_ratio_from_t_rh",
    "vapour_pressure_from_humidity_ratio",
    "activity_from_t_w",
    "relative_humidity_from_t_w",
    "moist_air_enthalpy_kj_kg_da",
    "dry_air_mass_flow",
    "dynamic_viscosity_air_pa_s",
    "water_vapour_diffusivity_air_m2_s",
    "sherwood_parallel_plate",
    "calculate_film_state",
]
