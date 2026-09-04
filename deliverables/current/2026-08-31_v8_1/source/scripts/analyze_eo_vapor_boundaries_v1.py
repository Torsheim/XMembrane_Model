#!/usr/bin/env python3
"""Boundary-condition sensitivity study for the EO vapour coupon cell.

The study has two deliberately separate layers:

1. A power-law membrane + finite gas-film calculation at imposed current.
   Short-channel bulk depletion is represented by an iterated inlet/outlet mean
   state.  The local constitutive equation is cross-checked against the canonical
   repository solver.
2. A measurement-nuisance layer for convective bypass leakage, perimeter
   conductance, humidity-difference bias and between-polarity drift.

The combined Latin-hypercube calculation is a space-filling stress envelope.
Its ranges are declared engineering scenarios, not calibrated probability
distributions.  Quantiles therefore must not be interpreted as confidence
intervals for hardware that has not yet been measured.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import qmc, spearmanr


FARADAY_C_MOL = 96485.33212
WATER_MOLAR_MASS_KG_MOL = 0.01801528
R_UNIVERSAL_J_MOL_K = 8.31446261815324
R_DRY_AIR_J_KG_K = 287.058
ACTIVITY_EPS = 1.0e-8
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

SCENARIO_PLOT_LABELS = {
    "low_drag_slow_diffusion": "low drag, slow diffusion",
    "order_unity_slow_diffusion": "order unity, slow diffusion",
    "order_unity_fast_diffusion": "order unity, fast diffusion",
    "inverse_design_anchor": "inverse-design anchor",
}
SENSITIVITY_PLOT_LABELS = {
    "humidity_drift_between_polarities_rh_percentage_points": "ABBA RH residual",
    "film_multiplier": "film multiplier",
    "active_area_error_fraction": "active-area error",
    "wall_and_sensor_rate_drift_between_polarities_mg_h": "ABBA rate residual",
    "current_error_fraction": "current error",
    "velocity_error_fraction": "velocity error",
    "temperature_mismatch_k": "temperature mismatch",
    "gap_error_fraction": "gap error",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description="Analyze EO coupon-cell boundary-condition sensitivity.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=root / "config" / "eo_vapor_boundary_analysis_v1.json",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=root / "outputs" / "eo_vapor_boundary_analysis_v1",
    )
    return parser.parse_args()


def saturation_pressure_water_pa(temperature_c: np.ndarray | float) -> np.ndarray:
    temperature_c = np.asarray(temperature_c, dtype=float)
    return 611.21 * np.exp(
        (18.678 - temperature_c / 234.5)
        * (temperature_c / (257.14 + temperature_c))
    )


def dynamic_viscosity_air_pa_s(temperature_c: np.ndarray | float) -> np.ndarray:
    temperature_k = np.asarray(temperature_c, dtype=float) + 273.15
    return (
        1.716e-5
        * (temperature_k / 273.15) ** 1.5
        * (273.15 + 111.0)
        / (temperature_k + 111.0)
    )


def water_vapour_diffusivity_air_m2_s(
    temperature_c: np.ndarray | float, pressure_pa: np.ndarray | float
) -> np.ndarray:
    temperature_k = np.asarray(temperature_c, dtype=float) + 273.15
    return (
        2.60e-5
        * (temperature_k / 298.15) ** 1.81
        * (101325.0 / np.asarray(pressure_pa, dtype=float))
    )


def film_state(
    *,
    temperature_c: np.ndarray,
    pressure_pa: np.ndarray,
    velocity_m_s: np.ndarray,
    gap_m: np.ndarray,
    multiplier: np.ndarray,
    laminar_sherwood: float,
) -> dict[str, np.ndarray]:
    temperature_k = temperature_c + 273.15
    hydraulic_diameter = 2.0 * gap_m
    density = pressure_pa / (R_DRY_AIR_J_KG_K * temperature_k)
    viscosity = dynamic_viscosity_air_pa_s(temperature_c)
    diffusivity = water_vapour_diffusivity_air_m2_s(temperature_c, pressure_pa)
    reynolds = density * velocity_m_s * hydraulic_diameter / viscosity
    schmidt = viscosity / (density * diffusivity)
    turbulent = np.maximum(
        0.023 * np.maximum(reynolds, 1.0) ** 0.83 * np.maximum(schmidt, 1e-8) ** 0.44,
        laminar_sherwood,
    )
    transition = np.clip((reynolds - 2300.0) / 1700.0, 0.0, 1.0)
    sherwood = (1.0 - transition) * laminar_sherwood + transition * turbulent
    k_gas_m_s = sherwood * diffusivity / hydraulic_diameter
    saturated_molar_concentration = saturation_pressure_water_pa(temperature_c) / (
        R_UNIVERSAL_J_MOL_K * temperature_k
    )
    return {
        "reynolds_number": reynolds,
        "schmidt_number": schmidt,
        "sherwood_number": sherwood,
        "gas_mass_transfer_coefficient_m_s": k_gas_m_s,
        "activity_film_coefficient_mol_m2_s_activity": (
            multiplier * k_gas_m_s * saturated_molar_concentration
        ),
    }


def _power_integral(
    lower: np.ndarray,
    upper: np.ndarray,
    exponent: float,
    reference_activity: float,
) -> np.ndarray:
    lower = np.clip(np.asarray(lower, dtype=float), ACTIVITY_EPS, 1.0)
    upper = np.clip(np.asarray(upper, dtype=float), ACTIVITY_EPS, 1.0)
    shifted = exponent + 1.0
    if abs(shifted) <= 1.0e-10:
        return reference_activity * np.log(upper / lower)
    return (
        upper**shifted - lower**shifted
    ) / (shifted * reference_activity**exponent)


def local_powerlaw_flux(
    *,
    source_bulk_activity: np.ndarray,
    receiver_bulk_activity: np.ndarray,
    signed_current_density_a_m2: np.ndarray,
    source_film_coefficient: np.ndarray,
    receiver_film_coefficient: np.ndarray,
    material: Mapping[str, Any],
    reference_activity: float,
    newton_iterations: int = 16,
) -> dict[str, np.ndarray]:
    """Vectorized exact constant-drag power-law flux equation.

    This reproduces the water-flux part of
    ``heiq_pre_receiver_model.py::solve_powerlaw_at_current`` while allowing
    sample-specific films and signed current for polarity reversal.
    """

    a_s = np.asarray(source_bulk_activity, dtype=float)
    a_r = np.asarray(receiver_bulk_activity, dtype=float)
    current = np.asarray(signed_current_density_a_m2, dtype=float)
    k_s = np.asarray(source_film_coefficient, dtype=float)
    k_r = np.asarray(receiver_film_coefficient, dtype=float)
    drag = float(material["water_drag"])
    diffusivity = float(material["water_diffusivity_m2_s"])
    capacity = float(material["water_capacity_mol_m3_activity"])
    thickness_m = float(material["dry_thickness_um"]) * 1.0e-6
    p_b = float(material["diffusivity_activity_exponent"]) + float(
        material["capacity_activity_exponent"]
    )
    b_ref = diffusivity * capacity
    eo_flux = drag * current / FARADAY_C_MOL

    lower_flux = np.maximum(
        k_s * (a_s - (1.0 - ACTIVITY_EPS)),
        -k_r * (a_r - ACTIVITY_EPS),
    )
    upper_flux = np.minimum(
        k_s * (a_s - ACTIVITY_EPS),
        k_r * ((1.0 - ACTIVITY_EPS) - a_r),
    )
    span = upper_flux - lower_flux
    interval_valid = span > 0.0
    mean_bulk = np.clip(0.5 * (a_s + a_r), ACTIVITY_EPS, 1.0)
    b_mean = b_ref * (mean_bulk / reference_activity) ** p_b
    conductance = b_mean / thickness_m
    flux = (
        eo_flux + conductance * (a_s - a_r)
    ) / (1.0 + conductance * (1.0 / k_s + 1.0 / k_r))
    padding = np.maximum(1.0e-14, 1.0e-10 * np.maximum(span, 0.0))
    flux = np.minimum(np.maximum(flux, lower_flux + padding), upper_flux - padding)

    for _ in range(newton_iterations):
        source_surface = a_s - flux / k_s
        receiver_surface = a_r + flux / k_r
        integral = _power_integral(
            source_surface, receiver_surface, p_b, reference_activity
        )
        residual = flux - eo_flux + b_ref * integral / thickness_m
        b_source = b_ref * (
            np.clip(source_surface, ACTIVITY_EPS, 1.0) / reference_activity
        ) ** p_b
        b_receiver = b_ref * (
            np.clip(receiver_surface, ACTIVITY_EPS, 1.0) / reference_activity
        ) ** p_b
        derivative = 1.0 + (
            b_source / k_s + b_receiver / k_r
        ) / thickness_m
        candidate = flux - residual / derivative
        flux = np.minimum(
            np.maximum(candidate, lower_flux + padding), upper_flux - padding
        )

    source_surface = a_s - flux / k_s
    receiver_surface = a_r + flux / k_r
    residual = flux - eo_flux + b_ref * _power_integral(
        source_surface, receiver_surface, p_b, reference_activity
    ) / thickness_m
    scale = np.maximum.reduce(
        [np.abs(flux), np.abs(eo_flux), np.full_like(flux, 1.0e-10)]
    )
    success = (
        interval_valid
        & (source_surface > ACTIVITY_EPS)
        & (source_surface < 1.0 - ACTIVITY_EPS)
        & (receiver_surface > ACTIVITY_EPS)
        & (receiver_surface < 1.0 - ACTIVITY_EPS)
        & (np.abs(residual) / scale < 1.0e-7)
    )
    return {
        "net_flux_mol_m2_s": np.where(success, flux, np.nan),
        "eo_flux_mol_m2_s": eo_flux,
        "diffusion_flux_mol_m2_s": np.where(success, flux - eo_flux, np.nan),
        "source_surface_activity": source_surface,
        "receiver_surface_activity": receiver_surface,
        "solver_success": success,
        "residual_relative": np.abs(residual) / scale,
    }


def molar_ratio_from_activity(
    activity: np.ndarray,
    temperature_c: np.ndarray,
    pressure_pa: np.ndarray,
) -> np.ndarray:
    p_w = np.clip(activity, 0.0, 0.999999) * saturation_pressure_water_pa(
        temperature_c
    )
    return p_w / (pressure_pa - p_w)


def activity_from_molar_ratio(
    ratio: np.ndarray,
    temperature_c: np.ndarray,
    pressure_pa: np.ndarray,
) -> np.ndarray:
    ratio = np.maximum(ratio, 0.0)
    p_w = pressure_pa * ratio / (1.0 + ratio)
    return p_w / saturation_pressure_water_pa(temperature_c)


def make_boundary_arrays(
    config: Mapping[str, Any], values: Mapping[str, np.ndarray | float]
) -> dict[str, np.ndarray]:
    cell = config["cell"]
    arrays = [np.atleast_1d(np.asarray(value, dtype=float)) for value in values.values()]
    n = max((array.size for array in arrays), default=1)

    def value(name: str, default: float) -> np.ndarray:
        raw = np.atleast_1d(np.asarray(values.get(name, default), dtype=float))
        return np.broadcast_to(raw, (n,)).astype(float, copy=True)

    return {
        "inlet_activity_mismatch_rh_percentage_points": value(
            "inlet_activity_mismatch_rh_percentage_points", 0.0
        ),
        "temperature_mismatch_k": value("temperature_mismatch_k", 0.0),
        "pressure_difference_pa": value("pressure_difference_pa", 0.0),
        "gap_m": value(
            "gap_m", float(cell["nominal_gap_mm_each_side"]) / 1000.0
        ),
        "velocity_m_s": value(
            "velocity_m_s", float(cell["nominal_velocity_m_s_each_side"])
        ),
        "film_multiplier": value(
            "film_multiplier", float(config["film_model"]["nominal_multiplier"])
        ),
        "actual_convective_leak_sccm_at_50_pa": value(
            "actual_convective_leak_sccm_at_50_pa", 0.0
        ),
        "humidity_static_difference_bias_rh_percentage_points": value(
            "humidity_static_difference_bias_rh_percentage_points", 0.0
        ),
        "humidity_drift_between_polarities_rh_percentage_points": value(
            "humidity_drift_between_polarities_rh_percentage_points", 0.0
        ),
        "wall_and_sensor_rate_drift_between_polarities_mg_h": value(
            "wall_and_sensor_rate_drift_between_polarities_mg_h", 0.0
        ),
        "edge_conductance_fraction_of_membrane": value(
            "edge_conductance_fraction_of_membrane", 0.0
        ),
        "active_area_error_fraction": value("active_area_error_fraction", 0.0),
        "current_error_fraction": value("current_error_fraction", 0.0),
    }


def simulate_signed_current(
    *,
    config: Mapping[str, Any],
    material: Mapping[str, Any],
    boundaries: Mapping[str, np.ndarray],
    polarity: float,
) -> dict[str, np.ndarray]:
    cell = config["cell"]
    t0 = float(cell["temperature_c"])
    p0 = float(cell["absolute_pressure_pa"])
    a0 = float(cell["common_inlet_water_activity"])
    reference_activity = float(cell["material_reference_water_activity"])
    iterations = int(cell["axial_mean_state_iterations"])
    width_m = float(cell["square_width_mm"]) / 1000.0
    nominal_area_m2 = float(cell["active_area_cm2"]) / 1.0e4

    d_t = boundaries["temperature_mismatch_k"]
    d_p = boundaries["pressure_difference_pa"]
    t_s = np.full_like(d_t, t0) + 0.5 * d_t
    t_r = np.full_like(d_t, t0) - 0.5 * d_t
    p_s = np.full_like(d_p, p0) + 0.5 * d_p
    p_r = np.full_like(d_p, p0) - 0.5 * d_p

    common_water_mole_fraction = a0 * float(saturation_pressure_water_pa(t0)) / p0
    p_w_s = common_water_mole_fraction * p_s
    p_w_r = common_water_mole_fraction * p_r
    mismatch_activity = (
        boundaries["inlet_activity_mismatch_rh_percentage_points"] / 100.0
    )
    a_s_in = p_w_s / saturation_pressure_water_pa(t_s) + 0.5 * mismatch_activity
    a_r_in = p_w_r / saturation_pressure_water_pa(t_r) - 0.5 * mismatch_activity
    a_s_in = np.clip(a_s_in, ACTIVITY_EPS, 1.0 - ACTIVITY_EPS)
    a_r_in = np.clip(a_r_in, ACTIVITY_EPS, 1.0 - ACTIVITY_EPS)

    gap_m = boundaries["gap_m"]
    velocity = boundaries["velocity_m_s"]
    multiplier = boundaries["film_multiplier"]
    source_film = film_state(
        temperature_c=t_s,
        pressure_pa=p_s,
        velocity_m_s=velocity,
        gap_m=gap_m,
        multiplier=multiplier,
        laminar_sherwood=float(config["film_model"]["laminar_parallel_plate_sherwood"]),
    )
    receiver_film = film_state(
        temperature_c=t_r,
        pressure_pa=p_r,
        velocity_m_s=velocity,
        gap_m=gap_m,
        multiplier=multiplier,
        laminar_sherwood=float(config["film_model"]["laminar_parallel_plate_sherwood"]),
    )
    k_s = source_film["activity_film_coefficient_mol_m2_s_activity"]
    k_r = receiver_film["activity_film_coefficient_mol_m2_s_activity"]

    volume_flow_m3_s = velocity * width_m * gap_m
    p_da_s = p_s - a_s_in * saturation_pressure_water_pa(t_s)
    p_da_r = p_r - a_r_in * saturation_pressure_water_pa(t_r)
    n_da_s = p_da_s * volume_flow_m3_s / (R_UNIVERSAL_J_MOL_K * (t_s + 273.15))
    n_da_r = p_da_r * volume_flow_m3_s / (R_UNIVERSAL_J_MOL_K * (t_r + 273.15))
    ratio_s_in = molar_ratio_from_activity(a_s_in, t_s, p_s)
    ratio_r_in = molar_ratio_from_activity(a_r_in, t_r, p_r)

    area_m2 = nominal_area_m2 * (1.0 + boundaries["active_area_error_fraction"])
    signed_current = (
        polarity
        * float(material["current_density_a_m2"])
        * (1.0 + boundaries["current_error_fraction"])
    )
    bulk_s = a_s_in.copy()
    bulk_r = a_r_in.copy()
    state: dict[str, np.ndarray] = {}
    a_s_out = a_s_in.copy()
    a_r_out = a_r_in.copy()
    for _ in range(iterations):
        state = local_powerlaw_flux(
            source_bulk_activity=bulk_s,
            receiver_bulk_activity=bulk_r,
            signed_current_density_a_m2=signed_current,
            source_film_coefficient=k_s,
            receiver_film_coefficient=k_r,
            material=material,
            reference_activity=reference_activity,
        )
        molar_rate = state["net_flux_mol_m2_s"] * area_m2
        ratio_s_out = np.maximum(ratio_s_in - molar_rate / n_da_s, 0.0)
        ratio_r_out = np.maximum(ratio_r_in + molar_rate / n_da_r, 0.0)
        a_s_out = np.clip(
            activity_from_molar_ratio(ratio_s_out, t_s, p_s),
            ACTIVITY_EPS,
            1.0 - ACTIVITY_EPS,
        )
        a_r_out = np.clip(
            activity_from_molar_ratio(ratio_r_out, t_r, p_r),
            ACTIVITY_EPS,
            1.0 - ACTIVITY_EPS,
        )
        target_bulk_s = 0.5 * (a_s_in + a_s_out)
        target_bulk_r = 0.5 * (a_r_in + a_r_out)
        bulk_s = 0.5 * bulk_s + 0.5 * target_bulk_s
        bulk_r = 0.5 * bulk_r + 0.5 * target_bulk_r

    state = local_powerlaw_flux(
        source_bulk_activity=bulk_s,
        receiver_bulk_activity=bulk_r,
        signed_current_density_a_m2=signed_current,
        source_film_coefficient=k_s,
        receiver_film_coefficient=k_r,
        material=material,
        reference_activity=reference_activity,
    )
    molar_rate = state["net_flux_mol_m2_s"] * area_m2
    mg_h = molar_rate * WATER_MOLAR_MASS_KG_MOL * 3600.0 * 1.0e6
    return {
        **state,
        "net_water_rate_mg_h": mg_h,
        "source_inlet_activity": a_s_in,
        "receiver_inlet_activity": a_r_in,
        "source_outlet_activity": a_s_out,
        "receiver_outlet_activity": a_r_out,
        "source_mean_bulk_activity": bulk_s,
        "receiver_mean_bulk_activity": bulk_r,
        "source_temperature_c": t_s,
        "receiver_temperature_c": t_r,
        "source_pressure_pa": p_s,
        "receiver_pressure_pa": p_r,
        "source_dry_air_molar_flow_mol_s": n_da_s,
        "receiver_dry_air_molar_flow_mol_s": n_da_r,
        "source_film_coefficient": k_s,
        "receiver_film_coefficient": k_r,
        "source_reynolds_number": source_film["reynolds_number"],
        "receiver_reynolds_number": receiver_film["reynolds_number"],
        "actual_flow_l_min_per_side": volume_flow_m3_s * 60000.0,
        "actual_area_m2": area_m2,
        "signed_current_density_a_m2": signed_current,
    }


def humidity_bias_rate_mg_h(
    *,
    difference_bias_pp: np.ndarray,
    outlet_activity: np.ndarray,
    temperature_c: np.ndarray,
    pressure_pa: np.ndarray,
    dry_air_molar_flow_mol_s: np.ndarray,
) -> np.ndarray:
    biased_activity = np.clip(
        outlet_activity + difference_bias_pp / 100.0,
        ACTIVITY_EPS,
        1.0 - ACTIVITY_EPS,
    )
    true_ratio = molar_ratio_from_activity(outlet_activity, temperature_c, pressure_pa)
    biased_ratio = molar_ratio_from_activity(
        biased_activity, temperature_c, pressure_pa
    )
    return (
        dry_air_molar_flow_mol_s
        * (biased_ratio - true_ratio)
        * WATER_MOLAR_MASS_KG_MOL
        * 3600.0
        * 1.0e6
    )


def evaluate_boundaries(
    *,
    config: Mapping[str, Any],
    material: Mapping[str, Any],
    boundaries: Mapping[str, np.ndarray],
    nominal_odd_rate_mg_h: float,
) -> dict[str, np.ndarray]:
    plus = simulate_signed_current(
        config=config, material=material, boundaries=boundaries, polarity=1.0
    )
    minus = simulate_signed_current(
        config=config, material=material, boundaries=boundaries, polarity=-1.0
    )
    plus_rate = plus["net_water_rate_mg_h"]
    minus_rate = minus["net_water_rate_mg_h"]
    true_odd = 0.5 * (plus_rate - minus_rate)
    true_even = 0.5 * (plus_rate + minus_rate)

    thickness_m = float(material["dry_thickness_um"]) * 1.0e-6
    p_b = float(material["diffusivity_activity_exponent"]) + float(
        material["capacity_activity_exponent"]
    )
    mean_activity = np.clip(
        0.5 * (plus["source_mean_bulk_activity"] + plus["receiver_mean_bulk_activity"]),
        ACTIVITY_EPS,
        1.0,
    )
    membrane_conductance_total = (
        float(material["water_diffusivity_m2_s"])
        * float(material["water_capacity_mol_m3_activity"])
        / thickness_m
        * (mean_activity / float(config["cell"]["material_reference_water_activity"]))
        ** p_b
        * plus["actual_area_m2"]
    )
    edge_rate_mol_s = (
        boundaries["edge_conductance_fraction_of_membrane"]
        * membrane_conductance_total
        * (plus["source_inlet_activity"] - plus["receiver_inlet_activity"])
    )
    edge_rate_mg_h = (
        edge_rate_mol_s
        * WATER_MOLAR_MASS_KG_MOL
        * 3600.0
        * 1.0e6
    )

    leak_sccm = (
        boundaries["actual_convective_leak_sccm_at_50_pa"]
        * boundaries["pressure_difference_pa"]
        / 50.0
    )
    source_water_concentration = (
        plus["source_inlet_activity"]
        * saturation_pressure_water_pa(plus["source_temperature_c"])
        / (R_UNIVERSAL_J_MOL_K * (plus["source_temperature_c"] + 273.15))
    )
    receiver_water_concentration = (
        plus["receiver_inlet_activity"]
        * saturation_pressure_water_pa(plus["receiver_temperature_c"])
        / (R_UNIVERSAL_J_MOL_K * (plus["receiver_temperature_c"] + 273.15))
    )
    upstream_concentration = np.where(
        leak_sccm >= 0.0, source_water_concentration, receiver_water_concentration
    )
    leak_rate_mol_s = leak_sccm * 1.0e-6 / 60.0 * upstream_concentration
    leak_rate_mg_h = (
        leak_rate_mol_s
        * WATER_MOLAR_MASS_KG_MOL
        * 3600.0
        * 1.0e6
    )

    static_bias = boundaries[
        "humidity_static_difference_bias_rh_percentage_points"
    ]
    drift_bias = boundaries[
        "humidity_drift_between_polarities_rh_percentage_points"
    ]
    plus_sensor_bias_rate = humidity_bias_rate_mg_h(
        difference_bias_pp=static_bias + 0.5 * drift_bias,
        outlet_activity=plus["receiver_outlet_activity"],
        temperature_c=plus["receiver_temperature_c"],
        pressure_pa=plus["receiver_pressure_pa"],
        dry_air_molar_flow_mol_s=plus["receiver_dry_air_molar_flow_mol_s"],
    )
    minus_sensor_bias_rate = humidity_bias_rate_mg_h(
        difference_bias_pp=static_bias - 0.5 * drift_bias,
        outlet_activity=minus["receiver_outlet_activity"],
        temperature_c=minus["receiver_temperature_c"],
        pressure_pa=minus["receiver_pressure_pa"],
        dry_air_molar_flow_mol_s=minus["receiver_dry_air_molar_flow_mol_s"],
    )
    rate_drift = boundaries[
        "wall_and_sensor_rate_drift_between_polarities_mg_h"
    ]
    plus_apparent = (
        plus_rate
        + edge_rate_mg_h
        + leak_rate_mg_h
        + plus_sensor_bias_rate
        + 0.5 * rate_drift
    )
    minus_apparent = (
        minus_rate
        + edge_rate_mg_h
        + leak_rate_mg_h
        + minus_sensor_bias_rate
        - 0.5 * rate_drift
    )
    measured_odd = 0.5 * (plus_apparent - minus_apparent)
    measured_even = 0.5 * (plus_apparent + minus_apparent)
    scale = float(nominal_odd_rate_mg_h)
    return {
        "plus_true_membrane_rate_mg_h": plus_rate,
        "minus_true_membrane_rate_mg_h": minus_rate,
        "true_odd_rate_mg_h": true_odd,
        "true_even_rate_mg_h": true_even,
        "edge_apparent_rate_mg_h": edge_rate_mg_h,
        "convective_leak_apparent_rate_mg_h": leak_rate_mg_h,
        "plus_sensor_bias_rate_mg_h": plus_sensor_bias_rate,
        "minus_sensor_bias_rate_mg_h": minus_sensor_bias_rate,
        "plus_apparent_rate_mg_h": plus_apparent,
        "minus_apparent_rate_mg_h": minus_apparent,
        "measured_odd_rate_mg_h": measured_odd,
        "measured_even_rate_mg_h": measured_even,
        "true_boundary_shift_odd_percent": 100.0 * (true_odd - scale) / scale,
        "measurement_odd_error_percent_of_nominal": 100.0
        * (measured_odd - true_odd)
        / scale,
        "total_odd_error_percent": 100.0 * (measured_odd - scale) / scale,
        "single_direction_apparent_error_percent": 100.0
        * (plus_apparent - scale)
        / scale,
        "true_even_fraction_of_nominal_percent": 100.0 * true_even / scale,
        "measured_even_fraction_of_nominal_percent": 100.0 * measured_even / scale,
        "total_inlet_activity_difference_rh_percentage_points": 100.0
        * (plus["source_inlet_activity"] - plus["receiver_inlet_activity"]),
        "actual_operating_convective_leak_sccm": leak_sccm,
        "source_film_coefficient": plus["source_film_coefficient"],
        "receiver_film_coefficient": plus["receiver_film_coefficient"],
        "source_reynolds_number": plus["source_reynolds_number"],
        "actual_flow_l_min_per_side": plus["actual_flow_l_min_per_side"],
        "source_surface_activity_plus": plus["source_surface_activity"],
        "receiver_surface_activity_plus": plus["receiver_surface_activity"],
        "source_outlet_activity_plus": plus["source_outlet_activity"],
        "receiver_outlet_activity_plus": plus["receiver_outlet_activity"],
        "solver_success": plus["solver_success"] & minus["solver_success"],
    }


def nominal_boundaries(config: Mapping[str, Any]) -> dict[str, np.ndarray]:
    return make_boundary_arrays(config, {})


def nominal_results(
    config: Mapping[str, Any], material: Mapping[str, Any]
) -> dict[str, float]:
    boundaries = nominal_boundaries(config)
    plus = simulate_signed_current(
        config=config, material=material, boundaries=boundaries, polarity=1.0
    )
    minus = simulate_signed_current(
        config=config, material=material, boundaries=boundaries, polarity=-1.0
    )
    odd = 0.5 * (plus["net_water_rate_mg_h"] - minus["net_water_rate_mg_h"])
    even = 0.5 * (plus["net_water_rate_mg_h"] + minus["net_water_rate_mg_h"])
    area_m2 = float(config["cell"]["active_area_cm2"]) / 1.0e4
    gross = (
        float(material["water_drag"])
        * float(material["current_density_a_m2"])
        * area_m2
        / FARADAY_C_MOL
        * WATER_MOLAR_MASS_KG_MOL
        * 3600.0
        * 1.0e6
    )
    return {
        "nominal_odd_rate_mg_h": float(odd[0]),
        "nominal_even_rate_mg_h": float(even[0]),
        "gross_faradaic_rate_mg_h": gross,
        "nominal_odd_fraction_of_gross": float(odd[0]) / gross,
        "nominal_source_film_coefficient": float(plus["source_film_coefficient"][0]),
        "nominal_reynolds_number": float(plus["source_reynolds_number"][0]),
        "nominal_flow_l_min_per_side": float(plus["actual_flow_l_min_per_side"][0]),
        "nominal_source_outlet_activity": float(plus["source_outlet_activity"][0]),
        "nominal_receiver_outlet_activity": float(plus["receiver_outlet_activity"][0]),
    }


def one_factor_frame(
    config: Mapping[str, Any],
    materials: Iterable[Mapping[str, Any]],
    nominal_by_id: Mapping[str, Mapping[str, float]],
) -> pd.DataFrame:
    mapping = {
        "inlet_activity_mismatch_rh_percentage_points": (
            "inlet_activity_mismatch_rh_percentage_points",
            lambda x: x,
        ),
        "temperature_mismatch_k": ("temperature_mismatch_k", lambda x: x),
        "pressure_difference_pa": ("pressure_difference_pa", lambda x: x),
        "gap_mm": ("gap_m", lambda x: x / 1000.0),
        "velocity_m_s": ("velocity_m_s", lambda x: x),
        "film_multiplier": ("film_multiplier", lambda x: x),
        "actual_convective_leak_sccm_at_50_pa": (
            "actual_convective_leak_sccm_at_50_pa",
            lambda x: x,
        ),
        "humidity_difference_bias_rh_percentage_points": (
            "humidity_static_difference_bias_rh_percentage_points",
            lambda x: x,
        ),
        "polarity_drift_mg_h": (
            "wall_and_sensor_rate_drift_between_polarities_mg_h",
            lambda x: x,
        ),
        "edge_conductance_fraction_of_membrane": (
            "edge_conductance_fraction_of_membrane",
            lambda x: x,
        ),
    }
    frames: list[pd.DataFrame] = []
    for material in materials:
        scenario_id = str(material["scenario_id"])
        nominal = nominal_by_id[scenario_id]
        for factor, values in config["one_factor_sweeps"].items():
            model_name, transform = mapping[factor]
            values_array = np.asarray(values, dtype=float)
            boundary_values: dict[str, np.ndarray | float] = {
                model_name: transform(values_array)
            }
            # Leakage and perimeter conductance require a driving force.  Their
            # OAT screens therefore use declared small challenge conditions
            # instead of the zero-driving-force nominal state.
            if factor == "actual_convective_leak_sccm_at_50_pa":
                boundary_values["pressure_difference_pa"] = 5.0
            if factor == "edge_conductance_fraction_of_membrane":
                boundary_values[
                    "inlet_activity_mismatch_rh_percentage_points"
                ] = 0.1
            boundaries = make_boundary_arrays(config, boundary_values)
            result = evaluate_boundaries(
                config=config,
                material=material,
                boundaries=boundaries,
                nominal_odd_rate_mg_h=float(nominal["nominal_odd_rate_mg_h"]),
            )
            frame = pd.DataFrame(result)
            frame.insert(0, "factor_value", values_array)
            frame.insert(0, "factor", factor)
            frame.insert(0, "scenario_id", scenario_id)
            frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def latin_hypercube_inputs(config: Mapping[str, Any]) -> pd.DataFrame:
    spec = config["combined_scenario_space"]
    keys = [
        key
        for key, value in spec.items()
        if isinstance(value, dict) and "min" in value and "max" in value
    ]
    sampler = qmc.LatinHypercube(d=len(keys), seed=int(spec["seed"]), scramble=True)
    unit = sampler.random(n=int(spec["samples"]))
    data: dict[str, np.ndarray] = {}
    for index, key in enumerate(keys):
        item = spec[key]
        low = float(item["min"])
        high = float(item["max"])
        if item.get("scale") == "log":
            data[key] = np.exp(np.log(low) + unit[:, index] * (np.log(high) - np.log(low)))
        else:
            data[key] = low + unit[:, index] * (high - low)
    return pd.DataFrame(data)


def combined_frame(
    config: Mapping[str, Any],
    materials: Iterable[Mapping[str, Any]],
    nominal_by_id: Mapping[str, Mapping[str, float]],
) -> pd.DataFrame:
    base_inputs = latin_hypercube_inputs(config)
    frames = []
    nominal_gap_m = float(config["cell"]["nominal_gap_mm_each_side"]) / 1000.0
    nominal_velocity = float(config["cell"]["nominal_velocity_m_s_each_side"])
    for material in materials:
        inputs = base_inputs.copy()
        boundary_values = {
            "inlet_activity_mismatch_rh_percentage_points": inputs[
                "inlet_activity_mismatch_rh_percentage_points"
            ].to_numpy(),
            "temperature_mismatch_k": inputs["temperature_mismatch_k"].to_numpy(),
            "pressure_difference_pa": inputs["pressure_difference_pa"].to_numpy(),
            "gap_m": nominal_gap_m * (1.0 + inputs["gap_error_fraction"].to_numpy()),
            "velocity_m_s": nominal_velocity
            * (1.0 + inputs["velocity_error_fraction"].to_numpy()),
            "film_multiplier": inputs["film_multiplier"].to_numpy(),
            "actual_convective_leak_sccm_at_50_pa": inputs[
                "actual_convective_leak_sccm_at_50_pa"
            ].to_numpy(),
            "humidity_static_difference_bias_rh_percentage_points": inputs[
                "humidity_static_difference_bias_rh_percentage_points"
            ].to_numpy(),
            "humidity_drift_between_polarities_rh_percentage_points": inputs[
                "humidity_drift_between_polarities_rh_percentage_points"
            ].to_numpy(),
            "wall_and_sensor_rate_drift_between_polarities_mg_h": inputs[
                "wall_and_sensor_rate_drift_between_polarities_mg_h"
            ].to_numpy(),
            "edge_conductance_fraction_of_membrane": inputs[
                "edge_conductance_fraction_of_membrane"
            ].to_numpy(),
            "active_area_error_fraction": inputs["active_area_error_fraction"].to_numpy(),
            "current_error_fraction": inputs["current_error_fraction"].to_numpy(),
        }
        boundaries = make_boundary_arrays(config, boundary_values)
        result = evaluate_boundaries(
            config=config,
            material=material,
            boundaries=boundaries,
            nominal_odd_rate_mg_h=float(
                nominal_by_id[str(material["scenario_id"])]["nominal_odd_rate_mg_h"]
            ),
        )
        for name, values in result.items():
            inputs[name] = values
        inputs["gap_m"] = boundary_values["gap_m"]
        inputs["velocity_m_s"] = boundary_values["velocity_m_s"]
        inputs.insert(0, "sample_id", np.arange(len(inputs), dtype=int))
        inputs.insert(0, "scenario_id", str(material["scenario_id"]))
        frames.append(inputs)
    return pd.concat(frames, ignore_index=True)


def sensitivity_frame(combined: pd.DataFrame) -> pd.DataFrame:
    independent_inputs = [
        "inlet_activity_mismatch_rh_percentage_points",
        "temperature_mismatch_k",
        "pressure_difference_pa",
        "gap_error_fraction",
        "velocity_error_fraction",
        "film_multiplier",
        "actual_convective_leak_sccm_at_50_pa",
        "humidity_static_difference_bias_rh_percentage_points",
        "humidity_drift_between_polarities_rh_percentage_points",
        "wall_and_sensor_rate_drift_between_polarities_mg_h",
        "edge_conductance_fraction_of_membrane",
        "active_area_error_fraction",
        "current_error_fraction",
    ]
    derived_inputs = [
        "total_inlet_activity_difference_rh_percentage_points",
        "actual_operating_convective_leak_sccm",
    ]
    outputs = [
        "single_direction_apparent_error_percent",
        "true_boundary_shift_odd_percent",
        "measurement_odd_error_percent_of_nominal",
        "total_odd_error_percent",
    ]
    rows = []
    for scenario_id, group in combined.groupby("scenario_id", sort=False):
        x_base = group[independent_inputs].to_numpy(float)
        x_std = (x_base - x_base.mean(axis=0)) / x_base.std(axis=0, ddof=0)
        design = np.column_stack([np.ones(len(group)), x_std])
        for output in outputs:
            y = group[output].to_numpy(float)
            y_std_value = y.std(ddof=0)
            y_std = (y - y.mean()) / y_std_value if y_std_value > 0.0 else np.zeros_like(y)
            coefficients = np.linalg.lstsq(design, y_std, rcond=None)[0][1:]
            fitted = design @ np.concatenate([[0.0], coefficients])
            r2 = 1.0 - np.sum((y_std - fitted) ** 2) / max(
                np.sum((y_std - y_std.mean()) ** 2), 1.0e-30
            )
            for index, input_name in enumerate(independent_inputs):
                statistic = spearmanr(group[input_name], group[output]).statistic
                rows.append(
                    {
                        "scenario_id": scenario_id,
                        "output": output,
                        "input": input_name,
                        "spearman_rank_correlation": float(statistic),
                        "absolute_spearman_rank_correlation": abs(float(statistic)),
                        "standardized_linear_coefficient": float(coefficients[index]),
                        "absolute_standardized_linear_coefficient": abs(
                            float(coefficients[index])
                        ),
                        "linear_model_r_squared": float(r2),
                    }
                )
            for input_name in derived_inputs:
                statistic = spearmanr(group[input_name], group[output]).statistic
                rows.append(
                    {
                        "scenario_id": scenario_id,
                        "output": output,
                        "input": input_name,
                        "spearman_rank_correlation": float(statistic),
                        "absolute_spearman_rank_correlation": abs(float(statistic)),
                        "standardized_linear_coefficient": math.nan,
                        "absolute_standardized_linear_coefficient": math.nan,
                        "linear_model_r_squared": float(r2),
                    }
                )
    frame = pd.DataFrame(rows)
    frame["spearman_importance_rank"] = frame.groupby(
        ["scenario_id", "output"]
    )["absolute_spearman_rank_correlation"].rank(method="dense", ascending=False)
    return frame


def summary_frame(
    config: Mapping[str, Any],
    materials: Iterable[Mapping[str, Any]],
    nominal_by_id: Mapping[str, Mapping[str, float]],
    combined: pd.DataFrame,
) -> pd.DataFrame:
    max_error = float(
        config["acceptance_screens"]["maximum_absolute_odd_estimator_error_percent"]
    )
    rows = []
    by_material = {str(item["scenario_id"]): item for item in materials}
    for scenario_id, group in combined.groupby("scenario_id", sort=False):
        error = group["total_odd_error_percent"].to_numpy(float)
        single = group["single_direction_apparent_error_percent"].to_numpy(float)
        nominal = nominal_by_id[scenario_id]
        rows.append(
            {
                "scenario_id": scenario_id,
                "scenario_interpretation": by_material[scenario_id]["interpretation"],
                **nominal,
                "combined_samples": len(group),
                "odd_error_p05_percent": float(np.quantile(error, 0.05)),
                "odd_error_median_percent": float(np.quantile(error, 0.5)),
                "odd_error_p95_percent": float(np.quantile(error, 0.95)),
                "odd_absolute_error_p95_percent": float(
                    np.quantile(np.abs(error), 0.95)
                ),
                "odd_absolute_error_max_percent": float(np.max(np.abs(error))),
                "odd_screen_pass_fraction": float(np.mean(np.abs(error) <= max_error)),
                "single_absolute_error_p95_percent": float(
                    np.quantile(np.abs(single), 0.95)
                ),
                "single_absolute_error_max_percent": float(np.max(np.abs(single))),
                "solver_success_fraction": float(group["solver_success"].mean()),
                "quantiles_are_conditional_scenario_not_confidence_intervals": True,
            }
        )
    return pd.DataFrame(rows)


def closed_loop_frame(
    config: Mapping[str, Any],
    materials: Iterable[Mapping[str, Any]],
    nominal_by_id: Mapping[str, Mapping[str, float]],
) -> pd.DataFrame:
    """Linearized symmetric rigid-chamber screen.

    ``delta`` is receiver minus source activity, so a one-side RH change of
    one percentage point corresponds to ``delta=0.02`` when both sides move
    symmetrically.  Wall/membrane capacity is expressed as a multiple of the
    gas capacity because it is not yet measured.
    """

    cell = config["cell"]
    screen = config["closed_loop_screen"]
    t_c = float(cell["temperature_c"])
    t_k = t_c + 273.15
    p_abs = float(cell["absolute_pressure_pa"])
    a0 = float(cell["common_inlet_water_activity"])
    a_ref = float(cell["material_reference_water_activity"])
    area_m2 = float(cell["active_area_cm2"]) / 1.0e4
    p_sat = float(saturation_pressure_water_pa(t_c))
    c_sat = p_sat / (R_UNIVERSAL_J_MOL_K * t_k)
    target_delta = 2.0 * float(
        screen["target_one_side_rh_change_percentage_points"]
    ) / 100.0
    maximum_delta = 2.0 * min(a0, 1.0 - a0)

    rows = []
    for material in materials:
        scenario_id = str(material["scenario_id"])
        nominal = nominal_by_id[scenario_id]
        p_b = float(material["diffusivity_activity_exponent"]) + float(
            material["capacity_activity_exponent"]
        )
        membrane_conductance = (
            float(material["water_diffusivity_m2_s"])
            * float(material["water_capacity_mol_m3_activity"])
            / (float(material["dry_thickness_um"]) * 1.0e-6)
            * (a0 / a_ref) ** p_b
        )
        k_film = float(nominal["nominal_source_film_coefficient"])
        film_factor = 1.0 / (
            1.0 + membrane_conductance * (2.0 / k_film)
        )
        eo_flux = (
            float(material["water_drag"])
            * float(material["current_density_a_m2"])
            / FARADAY_C_MOL
        )
        unconstrained_equilibrium_delta = eo_flux / membrane_conductance
        reachable_equilibrium_delta = min(
            unconstrained_equilibrium_delta, maximum_delta
        )

        for volume_l in screen["gas_volume_l_per_side"]:
            for capacity_multiple in screen[
                "effective_wall_plus_membrane_capacity_multiple_of_gas"
            ]:
                gas_capacity_mol_per_activity = float(volume_l) / 1000.0 * c_sat
                effective_capacity = gas_capacity_mol_per_activity * (
                    1.0 + float(capacity_multiple)
                )
                tau_s = effective_capacity / (
                    2.0 * area_m2 * film_factor * membrane_conductance
                )

                def time_to_delta(delta: float) -> float:
                    if delta <= 0.0:
                        return 0.0
                    if delta >= reachable_equilibrium_delta:
                        return math.inf
                    return -tau_s * math.log(
                        1.0 - delta / unconstrained_equilibrium_delta
                    )

                time_target_s = time_to_delta(target_delta)
                for temperature_mismatch_k in screen[
                    "temperature_mismatch_k_for_pressure_screen"
                ]:
                    thermal_pressure_difference = (
                        p_abs * abs(float(temperature_mismatch_k)) / t_k
                    )
                    water_pressure_at_target = target_delta * p_sat
                    remaining_water_pressure_to_5pa = max(
                        5.0 - thermal_pressure_difference, 0.0
                    )
                    delta_for_5pa = remaining_water_pressure_to_5pa / p_sat
                    time_to_5pa_s = (
                        0.0
                        if thermal_pressure_difference >= 5.0
                        else time_to_delta(delta_for_5pa)
                    )
                    rows.append(
                        {
                            "scenario_id": scenario_id,
                            "gas_volume_l_per_side": float(volume_l),
                            "effective_wall_plus_membrane_capacity_multiple_of_gas": float(
                                capacity_multiple
                            ),
                            "temperature_mismatch_k": float(temperature_mismatch_k),
                            "gas_capacity_mol_per_activity_per_side": gas_capacity_mol_per_activity,
                            "effective_capacity_mol_per_activity_per_side": effective_capacity,
                            "membrane_conductance_mol_m2_s_activity": membrane_conductance,
                            "film_attenuation_factor": film_factor,
                            "unconstrained_equilibrium_activity_difference": unconstrained_equilibrium_delta,
                            "reachable_equilibrium_activity_difference": reachable_equilibrium_delta,
                            "reachable_equilibrium_rh_difference_percentage_points": 100.0
                            * reachable_equilibrium_delta,
                            "linear_time_constant_s": tau_s,
                            "target_one_side_rh_change_percentage_points": float(
                                screen["target_one_side_rh_change_percentage_points"]
                            ),
                            "time_to_target_one_side_rh_change_s": time_target_s,
                            "water_pressure_difference_at_target_pa": water_pressure_at_target,
                            "thermal_pressure_difference_pa": thermal_pressure_difference,
                            "combined_pressure_difference_at_target_pa": water_pressure_at_target
                            + thermal_pressure_difference,
                            "time_to_5pa_pressure_difference_s": time_to_5pa_s,
                            "target_rh_change_is_reachable_before_passive_equilibrium": bool(
                                target_delta < reachable_equilibrium_delta
                            ),
                            "interpretation": screen["interpretation"],
                        }
                    )
    return pd.DataFrame(rows)


def aperture_design_identifiability_frame() -> pd.DataFrame:
    """Screen whether blank, area and perimeter terms can be separated.

    The fitted response is assumed to be ``blank + beta_A*A + beta_P*P``.
    This is a design-matrix check only; it does not assign a physical value to
    either coefficient.  Scaling the columns before calculating the condition
    number prevents the units of area and perimeter from dominating that
    diagnostic.
    """

    designs = {
        "current_4_9_25_square": [
            ("2x2 cm", 4.0, 8.0),
            ("3x3 cm", 9.0, 12.0),
            ("5x5 cm", 25.0, 20.0),
        ],
        "add_16_square": [
            ("2x2 cm", 4.0, 8.0),
            ("3x3 cm", 9.0, 12.0),
            ("4x4 cm", 16.0, 16.0),
            ("5x5 cm", 25.0, 20.0),
        ],
        "recommended_with_equal_area_rectangle": [
            ("2x2 cm", 4.0, 8.0),
            ("0.8x5 cm", 4.0, 11.6),
            ("3x3 cm", 9.0, 12.0),
            ("4x4 cm", 16.0, 16.0),
            ("5x5 cm", 25.0, 20.0),
        ],
    }
    rows = []
    for design_id, specimens in designs.items():
        area = np.asarray([item[1] for item in specimens], dtype=float)
        perimeter = np.asarray([item[2] for item in specimens], dtype=float)
        matrix = np.column_stack([np.ones(len(specimens)), area, perimeter])
        rank = int(np.linalg.matrix_rank(matrix))
        scaled = matrix / np.linalg.norm(matrix, axis=0)
        correlation = float(np.corrcoef(area, perimeter)[0, 1])
        vif = 1.0 / max(1.0 - correlation**2, np.finfo(float).eps)
        rows.append(
            {
                "design_id": design_id,
                "specimen_count": len(specimens),
                "parameters_blank_area_perimeter": 3,
                "design_matrix_rank": rank,
                "residual_degrees_of_freedom": len(specimens) - rank,
                "area_perimeter_correlation": correlation,
                "area_perimeter_variance_inflation_factor": vif,
                "scaled_design_condition_number": float(np.linalg.cond(scaled)),
                "specimens": "; ".join(item[0] for item in specimens),
                "both_flow_orientations_required": design_id
                == "recommended_with_equal_area_rectangle",
            }
        )
    return pd.DataFrame(rows)


def canonical_solver_crosscheck(
    config: Mapping[str, Any], materials: Iterable[Mapping[str, Any]]
) -> pd.DataFrame:
    from heiq.wp1.membrane.local_transport import legacy_v2_module

    v2 = legacy_v2_module()
    cell = config["cell"]
    t = float(cell["temperature_c"])
    p = float(cell["absolute_pressure_pa"])
    gap = np.array([float(cell["nominal_gap_mm_each_side"]) / 1000.0])
    velocity = np.array([float(cell["nominal_velocity_m_s_each_side"])])
    film = film_state(
        temperature_c=np.array([t]),
        pressure_pa=np.array([p]),
        velocity_m_s=velocity,
        gap_m=gap,
        multiplier=np.array([1.0]),
        laminar_sherwood=float(config["film_model"]["laminar_parallel_plate_sherwood"]),
    )
    k = float(film["activity_film_coefficient_mol_m2_s_activity"][0])
    rows = []
    for material in materials:
        parameters = pd.DataFrame(
            {
                "water_drag": [float(material["water_drag"])],
                "water_diffusivity_m2_s": [float(material["water_diffusivity_m2_s"])],
                "conductivity_s_m": [23.171886845550485],
                "dry_thickness_um": [float(material["dry_thickness_um"])],
                "water_capacity_mol_m3_activity": [
                    float(material["water_capacity_mol_m3_activity"])
                ],
                "diffusivity_activity_exponent": [
                    float(material["diffusivity_activity_exponent"])
                ],
                "conductivity_activity_exponent": [4.0],
                "capacity_activity_exponent": [
                    float(material["capacity_activity_exponent"])
                ],
            }
        )
        local_config = {
            "model": {
                "temperature_c": t,
                "reference_water_activity": float(cell["material_reference_water_activity"]),
                "source_film_coefficient_mol_m2_s_activity": k,
                "receiver_film_coefficient_mol_m2_s_activity": k,
                "series_area_resistance_ohm_m2": 0.0,
                "other_voltage_lower_bound_v": 0.0,
                "profile_flux_newton_iterations": 16,
                "profile_flux_relative_tolerance": 1.0e-7,
            },
            "activity_cases": {
                "crosscheck": {
                    "source_bulk_water_activity": float(cell["common_inlet_water_activity"]),
                    "receiver_bulk_water_activity": float(cell["common_inlet_water_activity"]),
                }
            },
        }
        canonical = v2.solve_powerlaw_at_current(
            parameters,
            float(material["current_density_a_m2"]),
            local_config,
            "crosscheck",
        )
        surrogate = local_powerlaw_flux(
            source_bulk_activity=np.array([float(cell["common_inlet_water_activity"])]),
            receiver_bulk_activity=np.array([float(cell["common_inlet_water_activity"])]),
            signed_current_density_a_m2=np.array(
                [float(material["current_density_a_m2"])]
            ),
            source_film_coefficient=np.array([k]),
            receiver_film_coefficient=np.array([k]),
            material=material,
            reference_activity=float(cell["material_reference_water_activity"]),
        )
        canonical_flux = float(canonical["net_flux_mol_m2_s"][0])
        surrogate_flux = float(surrogate["net_flux_mol_m2_s"][0])
        rows.append(
            {
                "scenario_id": material["scenario_id"],
                "canonical_local_flux_mol_m2_s": canonical_flux,
                "study_local_flux_mol_m2_s": surrogate_flux,
                "relative_difference": (surrogate_flux - canonical_flux)
                / canonical_flux,
                "canonical_solver_success": bool(canonical["solver_success"][0]),
                "study_solver_success": bool(surrogate["solver_success"][0]),
            }
        )
    return pd.DataFrame(rows)


def make_activity_temperature_heatmap(
    config: Mapping[str, Any],
    material: Mapping[str, Any],
    nominal: Mapping[str, float],
    output_dir: Path,
) -> pd.DataFrame:
    mismatch = np.linspace(-0.25, 0.25, 51)
    temperature = np.linspace(-0.25, 0.25, 51)
    grid_mismatch, grid_temperature = np.meshgrid(mismatch, temperature)
    boundaries = make_boundary_arrays(
        config,
        {
            "inlet_activity_mismatch_rh_percentage_points": grid_mismatch.ravel(),
            "temperature_mismatch_k": grid_temperature.ravel(),
        },
    )
    result = evaluate_boundaries(
        config=config,
        material=material,
        boundaries=boundaries,
        nominal_odd_rate_mg_h=float(nominal["nominal_odd_rate_mg_h"]),
    )
    frame = pd.DataFrame(
        {
            "inlet_activity_mismatch_rh_percentage_points": grid_mismatch.ravel(),
            "temperature_mismatch_k": grid_temperature.ravel(),
            **result,
        }
    )
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.6), sharex=True, sharey=True)
    for ax, column, title in (
        (
            axes[0],
            "single_direction_apparent_error_percent",
            "Single direction: apparent error",
        ),
        (axes[1], "total_odd_error_percent", "Polarity-odd estimator: error"),
    ):
        values = frame[column].to_numpy().reshape(grid_mismatch.shape)
        limit = max(float(np.nanmax(np.abs(values))), 1.0e-6)
        image = ax.pcolormesh(
            mismatch,
            temperature,
            values,
            shading="auto",
            cmap="coolwarm",
            vmin=-limit,
            vmax=limit,
        )
        fig.colorbar(image, ax=ax, label="Error versus nominal odd signal (%)")
        ax.set_title(title)
        ax.set_xlabel("Controlled inlet activity mismatch (RH percentage points)")
        ax.grid(False)
    axes[0].set_ylabel("Membrane-side temperature mismatch (K)")
    fig.suptitle(
        "Boundary mismatch: "
        + SCENARIO_PLOT_LABELS.get(
            str(material["scenario_id"]), str(material["scenario_id"])
        )
    )
    fig.tight_layout()
    fig.savefig(output_dir / "activity_temperature_interaction.png", dpi=190)
    plt.close(fig)
    return frame


def make_plots(
    output_dir: Path,
    one_factor: pd.DataFrame,
    combined: pd.DataFrame,
    sensitivity: pd.DataFrame,
) -> None:
    scenario = "order_unity_fast_diffusion"
    subset = one_factor[one_factor["scenario_id"] == scenario]
    fig, axes = plt.subplots(2, 2, figsize=(11.0, 8.0))
    panels = [
        ("inlet_activity_mismatch_rh_percentage_points", "Activity mismatch (RH pp)"),
        ("temperature_mismatch_k", "Temperature mismatch (K)"),
        ("gap_mm", "Gap per side (mm)"),
        ("film_multiplier", "Film-coefficient multiplier"),
    ]
    for ax, (factor, label) in zip(axes.ravel(), panels):
        group = subset[subset["factor"] == factor]
        ax.plot(
            group["factor_value"],
            group["single_direction_apparent_error_percent"],
            marker="o",
            label="single direction",
        )
        ax.plot(
            group["factor_value"],
            group["total_odd_error_percent"],
            marker="s",
            label="polarity odd",
        )
        ax.axhline(0.0, color="black", lw=0.8)
        ax.set_xlabel(label)
        ax.set_ylabel("Error versus nominal odd signal (%)")
        ax.grid(True, alpha=0.3)
    axes[0, 0].legend()
    fig.suptitle("One-factor boundary sensitivity: order-unity fast-diffusion case")
    fig.tight_layout()
    fig.savefig(output_dir / "one_factor_boundary_sensitivity.png", dpi=190)
    plt.close(fig)

    scenarios = list(combined["scenario_id"].drop_duplicates())
    fig, axes = plt.subplots(1, 2, figsize=(12.0, 4.8), sharey=True)
    positions = np.arange(len(scenarios))
    single_data = [
        combined.loc[
            combined["scenario_id"] == name,
            "single_direction_apparent_error_percent",
        ].to_numpy()
        for name in scenarios
    ]
    odd_data = [
        combined.loc[
            combined["scenario_id"] == name, "total_odd_error_percent"
        ].to_numpy()
        for name in scenarios
    ]
    axes[0].boxplot(single_data, positions=positions, showfliers=False)
    axes[1].boxplot(odd_data, positions=positions, showfliers=False)
    for ax, title in zip(axes, ["Single-direction apparent error", "Polarity-odd error"]):
        ax.axhline(0.0, color="black", lw=0.8)
        ax.set_xticks(positions)
        ax.set_xticklabels(
            [SCENARIO_PLOT_LABELS.get(name, name) for name in scenarios],
            rotation=25,
            ha="right",
        )
        ax.set_title(title)
        ax.grid(True, axis="y", alpha=0.3)
    axes[0].set_ylabel("Error versus nominal odd signal (%)")
    fig.suptitle("Combined declared boundary-condition stress space")
    fig.tight_layout()
    fig.savefig(output_dir / "combined_error_distributions.png", dpi=190)
    plt.close(fig)

    rank = sensitivity[
        sensitivity["output"] == "total_odd_error_percent"
    ].copy()
    rank = rank[~rank["input"].isin(
        [
            "total_inlet_activity_difference_rh_percentage_points",
            "actual_operating_convective_leak_sccm",
        ]
    )]
    top_names = (
        rank.groupby("input")["absolute_spearman_rank_correlation"]
        .max()
        .sort_values(ascending=False)
        .head(8)
        .index
    )
    rank = rank[rank["input"].isin(top_names)]
    pivot = rank.pivot(
        index="input",
        columns="scenario_id",
        values="absolute_spearman_rank_correlation",
    ).fillna(0.0)
    pivot = pivot.loc[
        pivot.max(axis=1).sort_values(ascending=True).index
    ]
    pivot = pivot.rename(
        index=SENSITIVITY_PLOT_LABELS,
        columns=SCENARIO_PLOT_LABELS,
    )
    fig, ax = plt.subplots(figsize=(9.2, 5.8))
    pivot.plot.barh(ax=ax)
    ax.set_xlabel("Absolute Spearman rank correlation")
    ax.set_ylabel("")
    ax.set_title("Rank associations for polarity-odd total error")
    ax.grid(True, axis="x", alpha=0.3)
    fig.tight_layout()
    fig.savefig(output_dir / "combined_sensitivity_rank.png", dpi=190)
    plt.close(fig)


def make_closed_loop_plot(output_dir: Path, closed_loop: pd.DataFrame) -> None:
    subset = closed_loop[
        (closed_loop["temperature_mismatch_k"] == 0.0)
        & (
            closed_loop[
                "effective_wall_plus_membrane_capacity_multiple_of_gas"
            ]
            == 0.0
        )
    ]
    fig, ax = plt.subplots(figsize=(7.6, 4.8))
    for scenario_id, group in subset.groupby("scenario_id", sort=False):
        group = group.sort_values("gas_volume_l_per_side")
        ax.plot(
            group["gas_volume_l_per_side"],
            group["time_to_5pa_pressure_difference_s"],
            marker="o",
            label=SCENARIO_PLOT_LABELS.get(scenario_id, scenario_id),
        )
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Rigid closed gas volume per side (L)")
    ax.set_ylabel("Gas-only time to 5 Pa differential pressure (s)")
    ax.set_title("Closed-loop boundary evolves far faster than steady-state criteria")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(fontsize=7.5)
    fig.tight_layout()
    fig.savefig(output_dir / "closed_loop_time_to_5pa.png", dpi=190)
    plt.close(fig)


def write_summary_markdown(
    path: Path,
    config: Mapping[str, Any],
    summary: pd.DataFrame,
    one_factor: pd.DataFrame,
    sensitivity: pd.DataFrame,
    crosscheck: pd.DataFrame,
    closed_loop: pd.DataFrame,
    aperture_design: pd.DataFrame,
) -> None:
    fast = summary.set_index("scenario_id").loc["order_unity_fast_diffusion"]
    slow = summary.set_index("scenario_id").loc["order_unity_slow_diffusion"]
    anchor = summary.set_index("scenario_id").loc["inverse_design_anchor"]

    def oat(scenario: str, factor: str, value: float, column: str) -> float:
        rows = one_factor[
            (one_factor["scenario_id"] == scenario)
            & (one_factor["factor"] == factor)
        ]
        index = (rows["factor_value"] - value).abs().idxmin()
        return float(rows.loc[index, column])

    fast_activity_single = oat(
        "order_unity_fast_diffusion",
        "inlet_activity_mismatch_rh_percentage_points",
        0.1,
        "single_direction_apparent_error_percent",
    )
    fast_activity_odd = oat(
        "order_unity_fast_diffusion",
        "inlet_activity_mismatch_rh_percentage_points",
        0.1,
        "total_odd_error_percent",
    )
    fast_temp_single = oat(
        "order_unity_fast_diffusion",
        "temperature_mismatch_k",
        0.1,
        "single_direction_apparent_error_percent",
    )
    fast_temp_odd = oat(
        "order_unity_fast_diffusion",
        "temperature_mismatch_k",
        0.1,
        "total_odd_error_percent",
    )
    fast_gap_1 = oat(
        "order_unity_fast_diffusion",
        "gap_mm",
        1.0,
        "total_odd_error_percent",
    )
    fast_gap_4 = oat(
        "order_unity_fast_diffusion",
        "gap_mm",
        4.0,
        "total_odd_error_percent",
    )

    top_rows = sensitivity[
        sensitivity["output"] == "total_odd_error_percent"
    ].copy()
    top_text = []
    for scenario_id in summary["scenario_id"]:
        group = top_rows[
            (top_rows["scenario_id"] == scenario_id)
            & (~top_rows["input"].isin(
                [
                    "total_inlet_activity_difference_rh_percentage_points",
                    "actual_operating_convective_leak_sccm",
                ]
            ))
        ].nlargest(3, "absolute_spearman_rank_correlation")
        names = ", ".join(
            f"{row.input} (|rho|={row.absolute_spearman_rank_correlation:.2f})"
            for row in group.itertuples()
        )
        top_text.append(f"- `{scenario_id}`: {names}")

    max_crosscheck = float(crosscheck["relative_difference"].abs().max())
    closed_low = closed_loop[
        (closed_loop["scenario_id"] == "low_drag_slow_diffusion")
        & (closed_loop["gas_volume_l_per_side"] == 5.0)
        & (
            closed_loop[
                "effective_wall_plus_membrane_capacity_multiple_of_gas"
            ]
            == 0.0
        )
        & (closed_loop["temperature_mismatch_k"] == 0.0)
    ].iloc[0]
    closed_active = closed_loop[
        (closed_loop["scenario_id"] == "low_drag_slow_diffusion")
        & (closed_loop["gas_volume_l_per_side"] == 0.005)
        & (
            closed_loop[
                "effective_wall_plus_membrane_capacity_multiple_of_gas"
            ]
            == 0.0
        )
        & (closed_loop["temperature_mismatch_k"] == 0.0)
    ].iloc[0]
    thermal_01 = closed_loop[
        (closed_loop["scenario_id"] == "low_drag_slow_diffusion")
        & (closed_loop["gas_volume_l_per_side"] == 5.0)
        & (
            closed_loop[
                "effective_wall_plus_membrane_capacity_multiple_of_gas"
            ]
            == 0.0
        )
        & (closed_loop["temperature_mismatch_k"] == 0.1)
    ].iloc[0]
    current_apertures = aperture_design.set_index("design_id").loc[
        "current_4_9_25_square"
    ]
    recommended_apertures = aperture_design.set_index("design_id").loc[
        "recommended_with_equal_area_rectangle"
    ]
    text = f"""# EO vapour-cell boundary analysis v1

## Scope

This is an experiment-design screen for the 25 cm2, 2 mm, 32 degC cell. It combines an imposed-current power-law membrane model, finite gas films, a short-channel mean-state water balance and declared measurement nuisances. The combined ranges are stress scenarios, not calibrated probability distributions.

The local flux surrogate reproduces the canonical repository finite-film solver to a maximum relative difference of {max_crosscheck:.3e} in the registered cross-check cases.

## Nominal physical response

| Scenario | Gross Faradaic (mg/h) | Polarity-odd net (mg/h) | Net/gross | Conditional 95th percentile absolute odd error |
|---|---:|---:|---:|---:|
| order-unity slow diffusion | {slow['gross_faradaic_rate_mg_h']:.3f} | {slow['nominal_odd_rate_mg_h']:.3f} | {100*slow['nominal_odd_fraction_of_gross']:.2f}% | {slow['odd_absolute_error_p95_percent']:.2f}% |
| order-unity fast diffusion | {fast['gross_faradaic_rate_mg_h']:.3f} | {fast['nominal_odd_rate_mg_h']:.3f} | {100*fast['nominal_odd_fraction_of_gross']:.2f}% | {fast['odd_absolute_error_p95_percent']:.2f}% |
| inverse-design anchor | {anchor['gross_faradaic_rate_mg_h']:.3f} | {anchor['nominal_odd_rate_mg_h']:.3f} | {100*anchor['nominal_odd_fraction_of_gross']:.2f}% | {anchor['odd_absolute_error_p95_percent']:.2f}% |

## Main boundary findings

- In the fast-diffusion stress case, a static +0.1 RH-percentage-point inlet mismatch changes a naive single-direction result by {fast_activity_single:+.1f}%, but the polarity-odd result by only {fast_activity_odd:+.2f}% in this model.
- A +0.1 K side-to-side temperature mismatch changes the same single-direction result by {fast_temp_single:+.1f}% and the odd result by {fast_temp_odd:+.2f}%. Static mismatch is therefore highly damaging to one-way flux inference but largely rejected by a stable polarity reversal.
- Gas-film/geometry effects do not cancel. Changing the gap from the nominal 2 mm to 1 mm shifts the fast-diffusion odd signal by {fast_gap_1:+.1f}%; 4 mm shifts it by {fast_gap_4:+.1f}%.
- The project Sherwood correlation uses Sh=7.54 throughout this laminar envelope, so its local film coefficient is velocity-independent. Flow still changes axial bulk depletion. Experimental flow dependence must therefore be measured and an explicit film multiplier retained.
- Static leakage, edge flux and sensor offset mainly enter the polarity-even/single-direction channel. Residual polarity-correlated humidity or wall-inventory drift can mimic EO and survives the odd estimator. Ideal ABBA ordering rejects static and linear time drift; the sampled drift term must therefore be interpreted as the non-cancelling residual from curvature, hysteresis or polarity-linked settling.

## Closed-loop boundary screen

- In the 5 mL active chamber, the low-drag 5.04 mg/h case reaches 5 Pa differential pressure in only {closed_active['time_to_5pa_pressure_difference_s']:.3g} s in the gas-only rigid-chamber limit.
- With 5 L per side, the same gas-only time is {closed_low['time_to_5pa_pressure_difference_s']:.1f} s. Unknown wall and membrane capacity lengthen the transient in direct proportion and must be identified by RH-step blanks.
- Symmetric one-side changes of 1 RH percentage point create about {closed_low['water_pressure_difference_at_target_pa']:.1f} Pa water-vapour pressure difference. A 0.1 K rigid-chamber temperature mismatch alone contributes about {thermal_01['thermal_pressure_difference_pa']:.1f} Pa, already above the +/-5 Pa steady-cell target.
- The high-diffusivity scenario can reach passive equilibrium before a one-side 1 RH-point change; the closed test must fit EO and passive back-diffusion together.

## Rank associations in the declared combined stress space

{chr(10).join(top_text)}

The reported 5th/95th percentiles and pass fractions are conditional on `config/eo_vapor_boundary_analysis_v1.json`; they are not confidence limits. Replace each nuisance range with measured calibration, blank and repeatability results before producing a formal uncertainty budget.

## Experimental implications

1. Use a split common inlet and ABBA polarity reversal as the primary EO estimator.
2. Treat gap, support and unresolved film multiplier as physical calibration variables, not measurement noise.
3. Cross-switch the humidity reference; measure the residual over a complete ABBA block, not only absolute RH accuracy. Randomize or mirror block order to expose nonlinear drift and hysteresis.
4. Measure the foil blank and pressure-driven bypass before and after each block.
5. Report single-direction, polarity-even and polarity-odd rates separately.
6. Do not fit blank, area and perimeter from only the 4/9/25 cm2 square masks: that design has {int(current_apertures['residual_degrees_of_freedom'])} residual degrees of freedom and area/perimeter correlation {current_apertures['area_perimeter_correlation']:.3f}. Add a 16 cm2 square and an equal-area/different-perimeter insert (20x20 mm versus 8x50 mm, both 4 cm2), and run the rectangular insert in both flow orientations. The recommended five-insert design has {int(recommended_apertures['residual_degrees_of_freedom'])} residual degrees of freedom and area/perimeter correlation {recommended_apertures['area_perimeter_correlation']:.3f}.
"""
    path.write_text(text, encoding="utf-8")


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, np.generic):
        return value.item()
    return value


def main() -> None:
    args = parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    materials = list(config["material_scenarios"])

    nominal_by_id = {
        str(material["scenario_id"]): nominal_results(config, material)
        for material in materials
    }
    nominal_frame = pd.DataFrame(
        [
            {"scenario_id": scenario_id, **values}
            for scenario_id, values in nominal_by_id.items()
        ]
    )
    crosscheck = canonical_solver_crosscheck(config, materials)
    if not bool(crosscheck["canonical_solver_success"].all()):
        raise RuntimeError("Canonical solver cross-check failed")
    if float(crosscheck["relative_difference"].abs().max()) > 1.0e-8:
        raise RuntimeError("Local study solver differs from canonical finite-film solver")

    one_factor = one_factor_frame(config, materials, nominal_by_id)
    combined = combined_frame(config, materials, nominal_by_id)
    if not bool(combined["solver_success"].all()):
        raise RuntimeError("At least one combined boundary scenario failed to solve")
    sensitivity = sensitivity_frame(combined)
    summary = summary_frame(config, materials, nominal_by_id, combined)
    closed_loop = closed_loop_frame(config, materials, nominal_by_id)
    aperture_design = aperture_design_identifiability_frame()

    primary_material = next(
        item for item in materials if item["scenario_id"] == "order_unity_fast_diffusion"
    )
    interaction = make_activity_temperature_heatmap(
        config,
        primary_material,
        nominal_by_id["order_unity_fast_diffusion"],
        output_dir,
    )
    make_plots(output_dir, one_factor, combined, sensitivity)
    make_closed_loop_plot(output_dir, closed_loop)

    nominal_frame.to_csv(output_dir / "nominal_cases.csv", index=False)
    crosscheck.to_csv(output_dir / "canonical_solver_crosscheck.csv", index=False)
    one_factor.to_csv(output_dir / "one_factor_boundary_sweeps.csv", index=False)
    combined.to_csv(output_dir / "combined_boundary_scenarios.csv", index=False)
    sensitivity.to_csv(output_dir / "combined_sensitivity_rank.csv", index=False)
    summary.to_csv(output_dir / "scenario_summary.csv", index=False)
    closed_loop.to_csv(output_dir / "closed_loop_boundary_screen.csv", index=False)
    aperture_design.to_csv(
        output_dir / "aperture_design_identifiability.csv", index=False
    )
    interaction.to_csv(output_dir / "activity_temperature_interaction.csv", index=False)
    (output_dir / "config_used.json").write_text(
        json.dumps(json_safe(config), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    audit = {
        "study_id": config["study_id"],
        "claim_boundary": config["claim_boundary"],
        "canonical_crosscheck_max_abs_relative_difference": float(
            crosscheck["relative_difference"].abs().max()
        ),
        "canonical_crosscheck_pass": True,
        "combined_sample_rows": len(combined),
        "combined_solver_success_fraction": float(combined["solver_success"].mean()),
        "combined_ranges_are_calibrated_probabilities": False,
        "outputs_are_confidence_intervals": False,
    }
    (output_dir / "audit.json").write_text(
        json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    write_summary_markdown(
        output_dir / "SUMMARY.md",
        config,
        summary,
        one_factor,
        sensitivity,
        crosscheck,
        closed_loop,
        aperture_design,
    )
    local_transport_source = (
        REPOSITORY_ROOT / "src" / "heiq" / "wp1" / "membrane" / "local_transport.py"
    )
    canonical_solver_source = (
        REPOSITORY_ROOT
        / "heiq_pre_receiver_material_analyses"
        / "heiq_pre_receiver_model.py"
    )
    source_paths = [
        args.config.resolve(),
        Path(__file__).resolve(),
        local_transport_source.resolve(),
        canonical_solver_source.resolve(),
    ]
    missing_sources = [str(path) for path in source_paths if not path.is_file()]
    if missing_sources:
        raise RuntimeError(f"Missing provenance sources: {missing_sources}")
    output_names = (
        "nominal_cases.csv",
        "canonical_solver_crosscheck.csv",
        "one_factor_boundary_sweeps.csv",
        "combined_boundary_scenarios.csv",
        "combined_sensitivity_rank.csv",
        "scenario_summary.csv",
        "closed_loop_boundary_screen.csv",
        "aperture_design_identifiability.csv",
        "activity_temperature_interaction.csv",
        "config_used.json",
        "audit.json",
        "SUMMARY.md",
        "activity_temperature_interaction.png",
        "closed_loop_time_to_5pa.png",
        "combined_error_distributions.png",
        "combined_sensitivity_rank.png",
        "one_factor_boundary_sensitivity.png",
    )
    output_paths = [output_dir / name for name in output_names]
    missing_outputs = [str(path) for path in output_paths if not path.is_file()]
    if missing_outputs:
        raise RuntimeError(f"Missing declared boundary-analysis outputs: {missing_outputs}")
    manifest = {
        "schema_version": 1,
        "study_id": config["study_id"],
        "sources": [
            {"path": str(path), "sha256": sha256(path)} for path in source_paths
        ],
        "generated_outputs": [
            {
                "path": str(path.resolve()),
                "sha256": sha256(path),
                "size_bytes": path.stat().st_size,
            }
            for path in output_paths
        ],
        "verification": {
            "canonical_solver_crosscheck_pass": True,
            "all_combined_cases_solved": True,
            "manifest_self_excluded_to_avoid_recursive_hash": True,
        },
    }
    (output_dir / "source_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Wrote EO boundary-condition study to {output_dir}")


if __name__ == "__main__":
    main()
