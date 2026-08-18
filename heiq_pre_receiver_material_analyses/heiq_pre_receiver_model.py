#!/usr/bin/env python3
"""Shared 1-D water-activity/voltage model for the HeiQ analyses.

Positive water flux and positive current point from the process/source side
(``x=0``) to the receiver side (``x=L``).  The local constitutive equations are

    N_w = n_d(a_w) j/F - D_w(a_w) S_w(a_w) da_w/dx

and

    dV/dx = j/sigma(a_w)
            + n_d(a_w) RT/F d(ln a_w)/dx.

The source and receiver gas films close the boundary-value problem:

    N_w = K_s(a_s,bulk-a_s,surface)
    N_w = K_r(a_r,surface-a_r,bulk).

Analyses 01 and 02 use an exact analytical reduction for a material-neutral
power-law response model with activity-independent effective drag.  Analysis
03 solves the complete H-Nafion boundary-value problem, including local
``D_w(a_w)``, ``S_w(a_w)``, ``sigma(a_w)`` and ``n_d(a_w)``.

The applied voltage is an operating input.  Current density is solved from the
coupled transport/voltage equations; the voltage cap is not used as a fixed
power-accounting voltage.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, Iterable

os.environ.setdefault("MPLCONFIGDIR", "/tmp/heiq-pre-receiver-mpl-v2")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.integrate import solve_bvp


FARADAY_C_MOL = 96485.33212
GAS_CONSTANT_J_MOL_K = 8.314462618
WATER_MOLAR_MASS_KG_MOL = 0.01801528
ACTIVITY_EPS = 1.0e-7

# Reference-property names retained from v1 so old result-processing notebooks
# need only small changes.  ``applied_voltage_v`` replaces imposed current.
PARAMETER_COLUMNS = [
    "water_drag",
    "water_diffusivity_m2_s",
    "conductivity_s_m",
    "dry_thickness_um",
    "applied_voltage_v",
    "water_capacity_mol_m3_activity",
    "diffusivity_activity_exponent",
    "conductivity_activity_exponent",
    "capacity_activity_exponent",
]


def load_config(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    validate_config(config)
    return config


def validate_config(config: dict[str, Any]) -> None:
    required = {
        "scenarios",
        "activity_cases",
        "model",
        "free_sweep",
        "monte_carlo",
        "nafion",
    }
    missing = required.difference(config)
    if missing:
        raise ValueError(f"Configuration is missing: {sorted(missing)}")
    model = config["model"]
    for name in (
        "reference_water_activity",
        "source_film_coefficient_mol_m2_s_activity",
        "receiver_film_coefficient_mol_m2_s_activity",
        "area_limit_m2",
        "maximum_cell_voltage_v",
        "current_density_cap_a_m2",
        "current_solver_upper_bound_a_m2",
        "power_electronics_efficiency",
        "profile_nodes",
    ):
        if float(model[name]) <= 0.0:
            raise ValueError(f"model.{name} must be positive")
    caps = np.asarray(model["cell_voltage_caps_v"], dtype=float)
    if caps.size == 0 or np.any(caps <= 0.0):
        raise ValueError("model.cell_voltage_caps_v must contain positive values")
    if float(np.max(caps)) > float(model["maximum_cell_voltage_v"]) + 1.0e-12:
        raise ValueError("A reported voltage cap exceeds maximum_cell_voltage_v")
    if not 0.0 < float(model["reference_water_activity"]) < 1.0:
        raise ValueError("reference_water_activity must lie in (0, 1)")
    for label, case in config["activity_cases"].items():
        for name in ("source_bulk_water_activity", "receiver_bulk_water_activity"):
            value = float(case[name])
            if not 0.0 < value < 1.0:
                raise ValueError(f"activity_cases.{label}.{name} must lie in (0, 1)")
    for label, scenario in config["scenarios"].items():
        if (
            float(scenario["water_load_kg_h"]) <= 0.0
            or float(scenario["gross_hvac_electric_opportunity_kw"]) <= 0.0
        ):
            raise ValueError(f"Scenario {label} has non-positive load or budget")


def values_from_spec(spec: dict[str, Any], quick: bool = False) -> np.ndarray:
    if "values" in spec:
        values = np.asarray(spec["values"], dtype=float)
        if quick and values.size > 3:
            values = values[[0, values.size // 2, -1]]
        return values
    points = int(spec["points"])
    if quick:
        points = min(points, 4)
    low = float(spec["min"])
    high = float(spec["max"])
    if spec.get("scale", "linear") == "log":
        return np.geomspace(low, high, points)
    return np.linspace(low, high, points)


def configure_plots() -> None:
    plt.rcParams.update(
        {
            "font.size": 10.0,
            "axes.titlesize": 10.0,
            "axes.labelsize": 10.0,
            "xtick.labelsize": 9.0,
            "ytick.labelsize": 9.0,
            "legend.fontsize": 8.2,
            "figure.dpi": 150,
            "savefig.dpi": 240,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )


def save_figure(fig: plt.Figure, output_dir: Path, stem: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for suffix, file_format in (("png", "png"), ("pdf", "pdf")):
        final_path = output_dir / f"{stem}.{suffix}"
        temporary_path = output_dir / f".{stem}.tmp.{suffix}"
        temporary_path.unlink(missing_ok=True)
        fig.savefig(
            temporary_path,
            format=file_format,
            bbox_inches="tight",
        )
        if temporary_path.stat().st_size == 0:
            raise RuntimeError(f"Matplotlib wrote an empty figure: {final_path}")
        temporary_path.replace(final_path)
        temporary_path.unlink(missing_ok=True)
    plt.close(fig)


def make_parameter_frame(**axes: Iterable[float]) -> pd.DataFrame:
    missing = set(PARAMETER_COLUMNS).difference(axes)
    if missing:
        raise ValueError(f"Parameter axes are missing: {sorted(missing)}")
    arrays = np.meshgrid(
        *[np.asarray(list(axes[name]), dtype=float) for name in PARAMETER_COLUMNS],
        indexing="ij",
    )
    return pd.DataFrame(
        {name: array.ravel() for name, array in zip(PARAMETER_COLUMNS, arrays)}
    )


def _power_integral(
    lower: np.ndarray,
    upper: np.ndarray,
    exponent: np.ndarray,
    reference_activity: float,
) -> np.ndarray:
    """Return integral_lower^upper (a/a_ref)^exponent da."""
    lower = np.clip(np.asarray(lower, dtype=float), ACTIVITY_EPS, 1.0)
    upper = np.clip(np.asarray(upper, dtype=float), ACTIVITY_EPS, 1.0)
    exponent = np.asarray(exponent, dtype=float)
    shifted = exponent + 1.0
    regular = np.abs(shifted) > 1.0e-10
    result = np.empty(np.broadcast(lower, upper, exponent).shape, dtype=float)
    result[regular] = (
        upper[regular] ** shifted[regular]
        - lower[regular] ** shifted[regular]
    ) / (shifted[regular] * reference_activity ** exponent[regular])
    result[~regular] = reference_activity * np.log(
        upper[~regular] / lower[~regular]
    )
    return result


def _power_property(
    reference_value: np.ndarray,
    activity: np.ndarray,
    exponent: np.ndarray,
    reference_activity: float,
) -> np.ndarray:
    return reference_value * (
        np.clip(activity, ACTIVITY_EPS, 1.0) / reference_activity
    ) ** exponent


def solve_powerlaw_at_current(
    parameters: pd.DataFrame,
    current_density_a_m2: np.ndarray | float,
    config: dict[str, Any],
    activity_case: str,
) -> dict[str, np.ndarray]:
    """Solve the exact power-law 1-D profile at imposed current density.

    Effective drag is activity-independent in this material-neutral model.
    ``D``, ``S`` and ``sigma`` vary locally as power laws about the declared
    reference activity.  Because drag is constant, the nonlinear BVP reduces
    exactly to one monotone scalar flux equation.
    """
    model = config["model"]
    case = config["activity_cases"][activity_case]
    n = len(parameters)

    def col(name: str) -> np.ndarray:
        return parameters[name].to_numpy(float)

    drag = col("water_drag")
    diffusivity_ref = col("water_diffusivity_m2_s")
    conductivity_ref = col("conductivity_s_m")
    capacity_ref = col("water_capacity_mol_m3_activity")
    p_d = col("diffusivity_activity_exponent")
    p_sigma = col("conductivity_activity_exponent")
    p_capacity = col("capacity_activity_exponent")
    p_b = p_d + p_capacity
    thickness_m = col("dry_thickness_um") * 1.0e-6
    current = np.broadcast_to(
        np.asarray(current_density_a_m2, dtype=float), (n,)
    ).astype(float, copy=False)
    source_bulk = np.full(
        n, float(case["source_bulk_water_activity"]), dtype=float
    )
    receiver_bulk = np.full(
        n, float(case["receiver_bulk_water_activity"]), dtype=float
    )
    temperature_k = float(model["temperature_c"]) + 273.15
    k_source = float(model["source_film_coefficient_mol_m2_s_activity"])
    k_receiver = float(model["receiver_film_coefficient_mol_m2_s_activity"])
    a_ref = float(model["reference_water_activity"])
    series_asr = float(model["series_area_resistance_ohm_m2"])
    other_voltage = float(model["other_voltage_lower_bound_v"])
    b_ref = diffusivity_ref * capacity_ref
    eo_flux = drag * current / FARADAY_C_MOL

    positive_inputs = (
        (drag > 0.0)
        & (diffusivity_ref > 0.0)
        & (conductivity_ref > 0.0)
        & (capacity_ref > 0.0)
        & (thickness_m > 0.0)
        & (current >= 0.0)
    )
    lower_flux = np.maximum(
        k_source * (source_bulk - (1.0 - ACTIVITY_EPS)),
        -k_receiver * (receiver_bulk - ACTIVITY_EPS),
    )
    upper_flux = np.minimum(
        k_source * (source_bulk - ACTIVITY_EPS),
        k_receiver * ((1.0 - ACTIVITY_EPS) - receiver_bulk),
    )
    interval_valid = upper_flux > lower_flux
    mean_bulk = 0.5 * (source_bulk + receiver_bulk)
    b_mean = _power_property(b_ref, mean_bulk, p_b, a_ref)
    conductance = b_mean / thickness_m
    flux = (
        eo_flux - conductance * (receiver_bulk - source_bulk)
    ) / (1.0 + conductance * (1.0 / k_source + 1.0 / k_receiver))
    padding = np.maximum(1.0e-12, 1.0e-9 * (upper_flux - lower_flux))
    flux = np.clip(flux, lower_flux + padding, upper_flux - padding)

    iterations = int(model["profile_flux_newton_iterations"])
    for _ in range(iterations):
        source_surface = source_bulk - flux / k_source
        receiver_surface = receiver_bulk + flux / k_receiver
        integral_shape = _power_integral(
            source_surface, receiver_surface, p_b, a_ref
        )
        residual = flux - eo_flux + b_ref * integral_shape / thickness_m
        b_source = _power_property(b_ref, source_surface, p_b, a_ref)
        b_receiver = _power_property(b_ref, receiver_surface, p_b, a_ref)
        derivative = 1.0 + (
            b_source / k_source + b_receiver / k_receiver
        ) / thickness_m
        candidate = flux - residual / derivative
        flux = np.clip(candidate, lower_flux + padding, upper_flux - padding)

    source_surface = source_bulk - flux / k_source
    receiver_surface = receiver_bulk + flux / k_receiver
    integral_b_shape = _power_integral(
        source_surface, receiver_surface, p_b, a_ref
    )
    residual = flux - eo_flux + b_ref * integral_b_shape / thickness_m
    residual_scale = np.maximum.reduce(
        [
            np.abs(flux),
            np.abs(eo_flux),
            np.abs(b_ref / thickness_m),
            np.full(n, 1.0e-10),
        ]
    )
    residual_relative = np.abs(residual) / residual_scale
    surface_valid = (
        interval_valid
        & (source_surface > ACTIVITY_EPS)
        & (source_surface < 1.0 - ACTIVITY_EPS)
        & (receiver_surface > ACTIVITY_EPS)
        & (receiver_surface < 1.0 - ACTIVITY_EPS)
    )

    integral_resistance_shape = _power_integral(
        source_surface, receiver_surface, p_b - p_sigma, a_ref
    )
    same_activity = np.abs(integral_b_shape) < 1.0e-12
    conductivity_mean = _power_property(
        conductivity_ref,
        0.5 * (source_surface + receiver_surface),
        p_sigma,
        a_ref,
    )
    with np.errstate(divide="ignore", invalid="ignore"):
        asr_ratio = integral_resistance_shape / integral_b_shape
    membrane_asr = np.where(
        same_activity,
        thickness_m / conductivity_mean,
        thickness_m * asr_ratio / conductivity_ref,
    )
    water_polarisation_voltage = (
        drag
        * GAS_CONSTANT_J_MOL_K
        * temperature_k
        / FARADAY_C_MOL
        * np.log(receiver_surface / source_surface)
    )
    ohmic_voltage = current * membrane_asr
    signed_voltage = (
        ohmic_voltage
        + water_polarisation_voltage
        + current * series_asr
        + other_voltage
    )
    lower_bound_voltage = np.maximum(0.0, signed_voltage)
    successful = (
        positive_inputs
        & surface_valid
        & np.isfinite(membrane_asr)
        & (membrane_asr > 0.0)
        & np.isfinite(signed_voltage)
        & (residual_relative <= float(model["profile_flux_relative_tolerance"]))
    )

    endpoint_activity = np.stack([source_surface, receiver_surface], axis=0)
    d_end = _power_property(
        diffusivity_ref[None, :],
        endpoint_activity,
        p_d[None, :],
        a_ref,
    )
    s_end = _power_property(
        capacity_ref[None, :],
        endpoint_activity,
        p_capacity[None, :],
        a_ref,
    )
    sigma_end = _power_property(
        conductivity_ref[None, :],
        endpoint_activity,
        p_sigma[None, :],
        a_ref,
    )
    return {
        "solver_success": successful,
        "solver_status": np.where(successful, "steady_state", "profile_solve_failed"),
        "current_density_a_m2": current,
        "source_bulk_activity": source_bulk,
        "receiver_bulk_activity": receiver_bulk,
        "source_surface_activity": source_surface,
        "receiver_surface_activity": receiver_surface,
        "eo_flux_mol_m2_s": eo_flux,
        "net_flux_mol_m2_s": flux,
        "diffusion_flux_mol_m2_s": flux - eo_flux,
        "profile_flux_residual_relative": residual_relative,
        "membrane_asr_ohm_m2": membrane_asr,
        "ohmic_voltage_v": ohmic_voltage,
        "water_polarisation_voltage_v": water_polarisation_voltage,
        "cell_voltage_signed_v": signed_voltage,
        "cell_voltage_lower_bound_v": lower_bound_voltage,
        "minimum_diffusivity_m2_s": np.min(d_end, axis=0),
        "maximum_diffusivity_m2_s": np.max(d_end, axis=0),
        "minimum_capacity_mol_m3_activity": np.min(s_end, axis=0),
        "maximum_capacity_mol_m3_activity": np.max(s_end, axis=0),
        "minimum_conductivity_s_m": np.min(sigma_end, axis=0),
        "maximum_conductivity_s_m": np.max(sigma_end, axis=0),
        "minimum_water_drag": drag,
        "maximum_water_drag": drag,
        "diffusive_permeability_mol_m_s_activity": b_ref,
    }


def solve_powerlaw_voltage_control(
    parameters: pd.DataFrame,
    config: dict[str, Any],
    activity_case: str,
) -> pd.DataFrame:
    """Solve current density so calculated required voltage equals applied V."""
    model = config["model"]
    target = parameters["applied_voltage_v"].to_numpy(float)
    n = len(parameters)
    current_low = np.zeros(n, dtype=float)
    # The finite gas films impose a stricter row-specific maximum current when
    # either membrane surface approaches a_w=0 or 1.  Derive that endpoint from
    # the exact flux equation instead of evaluating an arbitrarily huge current
    # that has no bounded steady profile.
    case = config["activity_cases"][activity_case]
    source_bulk = np.full(
        n, float(case["source_bulk_water_activity"]), dtype=float
    )
    receiver_bulk = np.full(
        n, float(case["receiver_bulk_water_activity"]), dtype=float
    )
    k_source = float(model["source_film_coefficient_mol_m2_s_activity"])
    k_receiver = float(model["receiver_film_coefficient_mol_m2_s_activity"])
    upper_flux = np.minimum(
        k_source * (source_bulk - ACTIVITY_EPS),
        k_receiver * ((1.0 - ACTIVITY_EPS) - receiver_bulk),
    )
    lower_flux = np.maximum(
        k_source * (source_bulk - (1.0 - ACTIVITY_EPS)),
        -k_receiver * (receiver_bulk - ACTIVITY_EPS),
    )
    padding = np.maximum(1.0e-10, 2.0e-7 * (upper_flux - lower_flux))
    endpoint_flux = upper_flux - padding
    endpoint_source = source_bulk - endpoint_flux / k_source
    endpoint_receiver = receiver_bulk + endpoint_flux / k_receiver
    p_b = (
        parameters["diffusivity_activity_exponent"].to_numpy(float)
        + parameters["capacity_activity_exponent"].to_numpy(float)
    )
    b_ref = (
        parameters["water_diffusivity_m2_s"].to_numpy(float)
        * parameters["water_capacity_mol_m3_activity"].to_numpy(float)
    )
    thickness_m = parameters["dry_thickness_um"].to_numpy(float) * 1.0e-6
    a_ref = float(model["reference_water_activity"])
    endpoint_integral = _power_integral(
        endpoint_source, endpoint_receiver, p_b, a_ref
    )
    endpoint_eo_flux = endpoint_flux + b_ref * endpoint_integral / thickness_m
    drag = parameters["water_drag"].to_numpy(float)
    physical_current_limit = endpoint_eo_flux * FARADAY_C_MOL / drag
    current_high = np.minimum(
        np.maximum(physical_current_limit, 1.0e-8),
        float(model["current_solver_upper_bound_a_m2"]),
    )
    low_state = solve_powerlaw_at_current(
        parameters, current_low, config, activity_case
    )
    high_state = solve_powerlaw_at_current(
        parameters, current_high, config, activity_case
    )
    low_voltage = low_state["cell_voltage_signed_v"]
    high_voltage = high_state["cell_voltage_signed_v"]
    bracket = (
        low_state["solver_success"]
        & high_state["solver_success"]
        & np.isfinite(low_voltage)
        & np.isfinite(high_voltage)
        & (target >= low_voltage - 1.0e-10)
        & (target <= high_voltage + 1.0e-10)
        & (high_voltage > low_voltage)
    )

    iterations = int(model["voltage_bisection_iterations"])
    for _ in range(iterations):
        current_mid = 0.5 * (current_low + current_high)
        mid_state = solve_powerlaw_at_current(
            parameters, current_mid, config, activity_case
        )
        go_higher = mid_state["cell_voltage_signed_v"] < target
        current_low = np.where(bracket & go_higher, current_mid, current_low)
        current_high = np.where(bracket & ~go_higher, current_mid, current_high)

    solved_current = 0.5 * (current_low + current_high)
    state = solve_powerlaw_at_current(
        parameters, solved_current, config, activity_case
    )
    voltage_error = state["cell_voltage_signed_v"] - target
    tolerance = float(model["voltage_absolute_tolerance_v"]) + float(
        model["voltage_relative_tolerance"]
    ) * np.maximum(target, 1.0e-3)
    voltage_match = bracket & state["solver_success"] & (
        np.abs(voltage_error) <= tolerance
    )
    status = np.full(n, "voltage_matched", dtype=object)
    status[target < low_voltage - 1.0e-10] = "below_reversible_voltage"
    status[target > high_voltage + 1.0e-10] = "above_current_solver_ceiling"
    status[~low_state["solver_success"] | ~high_state["solver_success"]] = (
        "profile_bracket_failed"
    )
    status[bracket & ~voltage_match] = "voltage_root_not_converged"

    result = parameters.copy()
    result.insert(0, "activity_case", activity_case)
    for name, values in state.items():
        result[name] = values
    result["voltage_solution_status"] = status
    result["voltage_match_error_v"] = voltage_error
    result["voltage_current_solution_ok"] = voltage_match
    result["accounting_voltage_v"] = target
    result["net_flux_kg_m2_h"] = (
        result["net_flux_mol_m2_s"]
        * WATER_MOLAR_MASS_KG_MOL
        * 3600.0
    )
    return result


def _cap_column(cap: float) -> str:
    text = f"{cap:.3f}".rstrip("0").rstrip(".").replace(".", "p")
    return f"feasible_at_{text}v_cap"


def apply_scenario_gates(
    transport: pd.DataFrame,
    config: dict[str, Any],
    scenario_label: str,
) -> pd.DataFrame:
    model = config["model"]
    scenario = config["scenarios"][scenario_label]
    result = transport.copy()
    result.insert(0, "scenario", scenario_label)
    flux_kg = result["net_flux_kg_m2_h"].to_numpy(float)
    positive_flux = (
        result["voltage_current_solution_ok"].to_numpy(bool)
        & np.isfinite(flux_kg)
        & (flux_kg > 0.0)
    )
    water_load = float(scenario["water_load_kg_h"])
    with np.errstate(divide="ignore", invalid="ignore"):
        area = np.where(positive_flux, water_load / flux_kg, np.inf)
    current = result["current_density_a_m2"].to_numpy(float)
    applied_voltage = result["applied_voltage_v"].to_numpy(float)
    grid_power = (
        applied_voltage
        * current
        * area
        / 1000.0
        / float(model["power_electronics_efficiency"])
    )
    grid_power = np.where(positive_flux, grid_power, np.inf)
    fan_kw = float(scenario["added_process_fan_kw"])
    gross_budget = float(scenario["gross_hvac_electric_opportunity_kw"])
    residual = gross_budget - fan_kw - grid_power
    area_ok = positive_flux & (area <= float(model["area_limit_m2"]))
    voltage_ok = (
        result["voltage_current_solution_ok"].to_numpy(bool)
        & (applied_voltage <= float(model["maximum_cell_voltage_v"]) + 1.0e-12)
    )
    current_ok = (
        result["voltage_current_solution_ok"].to_numpy(bool)
        & (current <= float(model["current_density_cap_a_m2"]) + 1.0e-12)
    )
    energy_ok = positive_flux & (residual >= 0.0)
    feasible = positive_flux & area_ok & voltage_ok & current_ok & energy_ok

    status = np.full(len(result), "feasible", dtype=object)
    status[~energy_ok] = "energy"
    status[~current_ok] = "current"
    status[~voltage_ok] = "voltage"
    status[~area_ok] = "area"
    status[~positive_flux] = "nonpositive_flux"
    status[~result["voltage_current_solution_ok"].to_numpy(bool)] = (
        "voltage_or_profile_solution"
    )

    result["required_active_area_m2"] = area
    result["eo_grid_power_kw"] = grid_power
    result["eo_grid_sec_kwh_kg"] = grid_power / water_load
    result["pre_receiver_residual_budget_kw"] = residual
    result["positive_net_flux"] = positive_flux
    result["area_gate_ok"] = area_ok
    result["voltage_gate_ok"] = voltage_ok
    result["current_gate_ok"] = current_ok
    result["energy_gate_ok"] = energy_ok
    result["all_gates_feasible"] = feasible
    result["primary_status"] = status
    for cap in model["cell_voltage_caps_v"]:
        result[_cap_column(float(cap))] = feasible & (
            applied_voltage <= float(cap) + 1.0e-12
        )
    return result


def evaluate_powerlaw_all_cases(
    parameters: pd.DataFrame,
    config: dict[str, Any],
    *,
    activity_cases: Iterable[str] | None = None,
    chunk_size: int | None = None,
) -> pd.DataFrame:
    missing = set(PARAMETER_COLUMNS).difference(parameters.columns)
    if missing:
        raise ValueError(f"Parameter frame is missing columns: {sorted(missing)}")
    selected_cases = list(activity_cases or config["activity_cases"].keys())
    size = int(chunk_size or config["model"]["vector_chunk_size"])
    outputs: list[pd.DataFrame] = []
    for activity_case in selected_cases:
        transport_parts = []
        for start in range(0, len(parameters), size):
            block = parameters.iloc[start : start + size].reset_index(drop=True)
            transport_parts.append(
                solve_powerlaw_voltage_control(block, config, activity_case)
            )
        transport = pd.concat(transport_parts, ignore_index=True)
        for scenario in config["scenarios"]:
            outputs.append(apply_scenario_gates(transport, config, scenario))
    return pd.concat(outputs, ignore_index=True)


def reconstruct_powerlaw_profile(
    row: pd.Series | dict[str, Any],
    config: dict[str, Any],
    nodes: int | None = None,
) -> pd.DataFrame:
    """Reconstruct the exact activity/property profile for one solved row."""
    values = dict(row)
    count = int(nodes or config["model"]["profile_nodes"])
    fraction = np.linspace(0.0, 1.0, count)
    a0 = float(values["source_surface_activity"])
    a1 = float(values["receiver_surface_activity"])
    p_d = float(values["diffusivity_activity_exponent"])
    p_s = float(values["capacity_activity_exponent"])
    p_sigma = float(values["conductivity_activity_exponent"])
    p_b = p_d + p_s
    a_ref = float(config["model"]["reference_water_activity"])
    if abs(p_b + 1.0) < 1.0e-10:
        activity = a0 * np.exp(fraction * np.log(a1 / a0))
    else:
        activity = (
            a0 ** (p_b + 1.0)
            + fraction * (a1 ** (p_b + 1.0) - a0 ** (p_b + 1.0))
        ) ** (1.0 / (p_b + 1.0))
    thickness_m = float(values["dry_thickness_um"]) * 1.0e-6
    diffusivity = float(values["water_diffusivity_m2_s"]) * (
        activity / a_ref
    ) ** p_d
    capacity = float(values["water_capacity_mol_m3_activity"]) * (
        activity / a_ref
    ) ** p_s
    conductivity = float(values["conductivity_s_m"]) * (
        activity / a_ref
    ) ** p_sigma
    drag = np.full(count, float(values["water_drag"]))
    current = float(values["current_density_a_m2"])
    flux = float(values["net_flux_mol_m2_s"])
    gradient = (
        drag * current / FARADAY_C_MOL - flux
    ) / (diffusivity * capacity)
    return pd.DataFrame(
        {
            "x_fraction": fraction,
            "x_um": fraction * thickness_m * 1.0e6,
            "water_activity": activity,
            "water_drag": drag,
            "water_diffusivity_m2_s": diffusivity,
            "water_capacity_mol_m3_activity": capacity,
            "diffusive_permeability_mol_m_s_activity": diffusivity * capacity,
            "conductivity_s_m": conductivity,
            "dactivity_dx_per_m": gradient,
        }
    )


# H-Nafion property correlations used by Analysis 03.
def nafion_lambda(activity: np.ndarray | float) -> np.ndarray:
    a = np.asarray(activity, dtype=float)
    return 0.043 + 17.81 * a - 39.85 * a**2 + 36.0 * a**3


def nafion_dlambda_da(activity: np.ndarray | float) -> np.ndarray:
    a = np.asarray(activity, dtype=float)
    return 17.81 - 79.7 * a + 108.0 * a**2


def nafion_conductivity_s_m(
    hydration_lambda: np.ndarray | float, temperature_k: np.ndarray | float
) -> np.ndarray:
    lam = np.asarray(hydration_lambda, dtype=float)
    temp = np.asarray(temperature_k, dtype=float)
    return np.maximum(0.5139 * lam - 0.326, 1.0e-5) * np.exp(
        1268.0 * (1.0 / 303.15 - 1.0 / temp)
    )


def nafion_diffusivity_m2_s(
    hydration_lambda: np.ndarray | float, temperature_k: np.ndarray | float
) -> np.ndarray:
    lam = np.asarray(hydration_lambda, dtype=float)
    temp = np.asarray(temperature_k, dtype=float)
    polynomial = 2.563 - 0.33 * lam + 0.0264 * lam**2 - 0.000671 * lam**3
    return 1.0e-10 * np.maximum(polynomial, 0.05) * np.exp(
        2416.0 * (1.0 / 303.15 - 1.0 / temp)
    )


def nafion_drag_prior(hydration_lambda: np.ndarray | float) -> np.ndarray:
    lam = np.asarray(hydration_lambda, dtype=float)
    return np.clip(2.5 * lam / 22.0, 0.0, 2.5)


def _nafion_local_properties(
    activity: np.ndarray,
    temperature_k: float,
    config: dict[str, Any],
    drag_scale: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    spec = config["nafion"]
    a = np.clip(np.asarray(activity, dtype=float), ACTIVITY_EPS, 1.0 - ACTIVITY_EPS)
    hydration = nafion_lambda(a)
    capacity = (
        float(spec["dry_polymer_density_kg_m3"])
        / float(spec["equivalent_weight_kg_mol"])
        * nafion_dlambda_da(a)
    )
    diffusivity = nafion_diffusivity_m2_s(hydration, temperature_k)
    conductivity = nafion_conductivity_s_m(hydration, temperature_k)
    drag = drag_scale * nafion_drag_prior(hydration)
    return hydration, capacity, diffusivity, conductivity, drag, diffusivity * capacity


def solve_nafion_voltage_state(
    *,
    source_bulk_activity: float,
    receiver_bulk_activity: float,
    temperature_c: float,
    dry_thickness_um: float,
    applied_voltage_v: float,
    drag_scale_factor: float,
    config: dict[str, Any],
    return_profile: bool = False,
) -> tuple[dict[str, Any], pd.DataFrame | None]:
    """Solve local H-Nafion properties, flux and current as one nonlinear BVP."""
    model = config["model"]
    spec = config["nafion"]
    temperature_k = temperature_c + 273.15
    length_m = dry_thickness_um * 1.0e-6
    k_source = float(model["source_film_coefficient_mol_m2_s_activity"])
    k_receiver = float(model["receiver_film_coefficient_mol_m2_s_activity"])
    series_asr = float(model["series_area_resistance_ohm_m2"])
    other_voltage = float(model["other_voltage_lower_bound_v"])
    profile_nodes = int(model["profile_nodes"])

    mean_a = 0.5 * (source_bulk_activity + receiver_bulk_activity)
    _, capacity0, diffusivity0, conductivity0, drag0, permeability0 = (
        _nafion_local_properties(
            np.asarray([mean_a]),
            temperature_k,
            config,
            drag_scale_factor,
        )
    )
    reversible_guess = (
        float(drag0[0])
        * GAS_CONSTANT_J_MOL_K
        * temperature_k
        / FARADAY_C_MOL
        * math.log(receiver_bulk_activity / source_bulk_activity)
    )
    resistance_guess = length_m / float(conductivity0[0]) + series_asr
    current_guess = max(
        1.0,
        (applied_voltage_v - other_voltage - reversible_guess)
        / max(resistance_guess, 1.0e-12),
    )
    current_guess = min(
        current_guess, 0.8 * float(model["current_solver_upper_bound_a_m2"])
    )
    eo_guess = float(drag0[0]) * current_guess / FARADAY_C_MOL
    conductance_guess = float(permeability0[0]) / length_m
    flux_guess = (
        eo_guess
        - conductance_guess
        * (receiver_bulk_activity - source_bulk_activity)
    ) / (
        1.0
        + conductance_guess * (1.0 / k_source + 1.0 / k_receiver)
    )
    lower_flux = max(
        k_source * (source_bulk_activity - (1.0 - ACTIVITY_EPS)),
        -k_receiver * (receiver_bulk_activity - ACTIVITY_EPS),
    )
    upper_flux = min(
        k_source * (source_bulk_activity - ACTIVITY_EPS),
        k_receiver * ((1.0 - ACTIVITY_EPS) - receiver_bulk_activity),
    )
    flux_guess = float(np.clip(flux_guess, lower_flux + 1.0e-9, upper_flux - 1.0e-9))
    source_surface_guess = source_bulk_activity - flux_guess / k_source
    receiver_surface_guess = receiver_bulk_activity + flux_guess / k_receiver
    xi = np.linspace(0.0, 1.0, min(profile_nodes, 31))
    activity_guess = np.linspace(
        source_surface_guess, receiver_surface_guess, xi.size
    )
    membrane_voltage_guess = (
        applied_voltage_v - other_voltage - current_guess * series_asr
    )
    voltage_guess = np.linspace(0.0, membrane_voltage_guess, xi.size)
    y_guess = np.vstack([activity_guess, voltage_guess])

    def ode(
        _xi: np.ndarray, y: np.ndarray, parameters: np.ndarray
    ) -> np.ndarray:
        flux, current = parameters
        activity = np.clip(y[0], ACTIVITY_EPS, 1.0 - ACTIVITY_EPS)
        _, capacity, diffusivity, conductivity, drag, permeability = (
            _nafion_local_properties(
                activity, temperature_k, config, drag_scale_factor
            )
        )
        dactivity_dxi = length_m * (
            drag * current / FARADAY_C_MOL - flux
        ) / permeability
        dvoltage_dxi = (
            length_m * current / conductivity
            + drag
            * GAS_CONSTANT_J_MOL_K
            * temperature_k
            / FARADAY_C_MOL
            * dactivity_dxi
            / activity
        )
        return np.vstack([dactivity_dxi, dvoltage_dxi])

    def boundary(
        left: np.ndarray, right: np.ndarray, parameters: np.ndarray
    ) -> np.ndarray:
        flux, current = parameters
        return np.asarray(
            [
                left[0] - (source_bulk_activity - flux / k_source),
                right[0] - (receiver_bulk_activity + flux / k_receiver),
                left[1],
                right[1]
                - (
                    applied_voltage_v
                    - other_voltage
                    - current * series_asr
                ),
            ],
            dtype=float,
        )

    solution = solve_bvp(
        ode,
        boundary,
        xi,
        y_guess,
        p=np.asarray([flux_guess, current_guess], dtype=float),
        tol=float(model["nafion_bvp_tolerance"]),
        max_nodes=int(model["nafion_bvp_max_nodes"]),
        verbose=0,
    )
    eval_xi = np.linspace(0.0, 1.0, profile_nodes)
    evaluated = solution.sol(eval_xi) if solution.sol is not None else np.full((2, profile_nodes), np.nan)
    activity = evaluated[0]
    voltage_profile = evaluated[1]
    flux = float(solution.p[0]) if solution.p is not None else math.nan
    current = float(solution.p[1]) if solution.p is not None else math.nan
    (
        hydration,
        capacity,
        diffusivity,
        conductivity,
        drag,
        permeability,
    ) = _nafion_local_properties(
        activity, temperature_k, config, drag_scale_factor
    )
    x_m = eval_xi * length_m
    membrane_asr = float(np.trapezoid(1.0 / conductivity, x_m))
    ohmic_voltage = current * membrane_asr
    water_voltage = float(
        np.trapezoid(
            drag
            * GAS_CONSTANT_J_MOL_K
            * temperature_k
            / FARADAY_C_MOL
            / np.clip(activity, ACTIVITY_EPS, 1.0),
            activity,
        )
    )
    calculated_voltage = (
        ohmic_voltage
        + water_voltage
        + current * series_asr
        + other_voltage
    )
    voltage_error = calculated_voltage - applied_voltage_v
    source_surface = float(activity[0])
    receiver_surface = float(activity[-1])
    boundary_error = max(
        abs(source_surface - (source_bulk_activity - flux / k_source)),
        abs(receiver_surface - (receiver_bulk_activity + flux / k_receiver)),
    )
    correlation_valid = bool(
        np.all(hydration >= float(spec["minimum_correlation_lambda"]))
    )
    physical_profile = bool(
        np.all(np.isfinite(activity))
        and np.all(activity > ACTIVITY_EPS)
        and np.all(activity < 1.0 - ACTIVITY_EPS)
        and np.all(diffusivity > 0.0)
        and np.all(capacity > 0.0)
        and np.all(conductivity > 0.0)
    )
    voltage_tolerance = float(model["voltage_absolute_tolerance_v"]) + float(
        model["voltage_relative_tolerance"]
    ) * max(applied_voltage_v, 1.0e-3)
    solver_success = bool(
        solution.success
        and physical_profile
        and math.isfinite(current)
        and current > 0.0
        and current <= float(model["current_solver_upper_bound_a_m2"])
        and math.isfinite(flux)
        and boundary_error <= 2.0e-5
        and abs(voltage_error) <= max(5.0 * voltage_tolerance, 2.0e-4)
    )
    if solver_success:
        status = "steady_state"
    elif solution.success and current <= 0.0:
        status = "no_positive_current_at_applied_voltage"
    elif solution.success and not physical_profile:
        status = "activity_profile_out_of_bounds"
    elif solution.success and current > float(model["current_solver_upper_bound_a_m2"]):
        status = "above_current_solver_ceiling"
    else:
        status = f"bvp_failed_{solution.status}"

    record: dict[str, Any] = {
        "solver_success": solver_success,
        "solver_status": status,
        "voltage_current_solution_ok": solver_success,
        "voltage_solution_status": status,
        "temperature_c": temperature_c,
        "source_bulk_activity": source_bulk_activity,
        "receiver_bulk_activity": receiver_bulk_activity,
        "source_surface_activity": source_surface,
        "receiver_surface_activity": receiver_surface,
        "dry_thickness_um": dry_thickness_um,
        "applied_voltage_v": applied_voltage_v,
        "accounting_voltage_v": applied_voltage_v,
        "current_density_a_m2": current,
        "net_flux_mol_m2_s": flux,
        "eo_flux_mol_m2_s": float(np.trapezoid(drag, x_m) / length_m)
        * current
        / FARADAY_C_MOL,
        "diffusion_flux_mol_m2_s": flux
        - float(np.trapezoid(drag, x_m) / length_m)
        * current
        / FARADAY_C_MOL,
        "net_flux_kg_m2_h": flux
        * WATER_MOLAR_MASS_KG_MOL
        * 3600.0,
        "membrane_asr_ohm_m2": membrane_asr,
        "ohmic_voltage_v": ohmic_voltage,
        "water_polarisation_voltage_v": water_voltage,
        "cell_voltage_signed_v": calculated_voltage,
        "cell_voltage_lower_bound_v": max(0.0, calculated_voltage),
        "voltage_match_error_v": voltage_error,
        "profile_boundary_error": boundary_error,
        "profile_flux_residual_relative": float(solution.rms_residuals.max())
        if solution.rms_residuals.size
        else math.nan,
        "hydration_lambda_min": float(np.min(hydration)),
        "hydration_lambda_max": float(np.max(hydration)),
        "water_drag": float(np.trapezoid(drag, x_m) / length_m),
        "minimum_water_drag": float(np.min(drag)),
        "maximum_water_drag": float(np.max(drag)),
        "water_diffusivity_m2_s": float(np.trapezoid(diffusivity, x_m) / length_m),
        "minimum_diffusivity_m2_s": float(np.min(diffusivity)),
        "maximum_diffusivity_m2_s": float(np.max(diffusivity)),
        "conductivity_s_m": length_m / membrane_asr,
        "minimum_conductivity_s_m": float(np.min(conductivity)),
        "maximum_conductivity_s_m": float(np.max(conductivity)),
        "water_capacity_mol_m3_activity": float(
            np.trapezoid(capacity, x_m) / length_m
        ),
        "minimum_capacity_mol_m3_activity": float(np.min(capacity)),
        "maximum_capacity_mol_m3_activity": float(np.max(capacity)),
        "diffusive_permeability_mol_m_s_activity": float(
            np.trapezoid(permeability, x_m) / length_m
        ),
        "drag_scale_factor": drag_scale_factor,
        "nafion_correlation_validity_gate": correlation_valid,
        "bvp_mesh_nodes": int(solution.x.size),
        "bvp_message": str(solution.message),
    }
    profile = None
    if return_profile:
        profile = pd.DataFrame(
            {
                "x_fraction": eval_xi,
                "x_um": x_m * 1.0e6,
                "water_activity": activity,
                "hydration_lambda": hydration,
                "water_drag": drag,
                "water_diffusivity_m2_s": diffusivity,
                "water_capacity_mol_m3_activity": capacity,
                "diffusive_permeability_mol_m_s_activity": permeability,
                "conductivity_s_m": conductivity,
                "voltage_profile_v": voltage_profile,
            }
        )
    return record, profile


def evaluate_nafion_states(
    states: pd.DataFrame,
    config: dict[str, Any],
) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    total = len(states)
    for index, row in states.iterrows():
        record, _ = solve_nafion_voltage_state(
            source_bulk_activity=float(row["source_bulk_activity_input"]),
            receiver_bulk_activity=float(row["receiver_bulk_activity_input"]),
            temperature_c=float(row["temperature_c_nafion_path"]),
            dry_thickness_um=float(row["dry_thickness_um"]),
            applied_voltage_v=float(row["applied_voltage_v"]),
            drag_scale_factor=float(row["drag_scale_factor"]),
            config=config,
        )
        records.append({**row.to_dict(), **record})
        if total >= 100 and (index + 1) % max(100, total // 10) == 0:
            print(f"  solved {index + 1:,}/{total:,} Nafion states", flush=True)
    return pd.DataFrame(records)


def pareto_front(
    frame: pd.DataFrame,
    x: str = "required_active_area_m2",
    y: str = "eo_grid_power_kw",
) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    ordered = frame.sort_values([x, y], kind="mergesort").copy()
    y_values = ordered[y].to_numpy(float)
    keep = np.zeros(len(ordered), dtype=bool)
    best = math.inf
    for idx, value in enumerate(y_values):
        if np.isfinite(value) and value < best - 1.0e-12:
            keep[idx] = True
            best = value
    return ordered.loc[keep].reset_index(drop=True)


def select_pareto_knee(front: pd.DataFrame) -> pd.DataFrame:
    if front.empty:
        return front.copy()
    x = front["required_active_area_m2"].to_numpy(float)
    y = front["eo_grid_power_kw"].to_numpy(float)
    x_span = max(float(np.max(x) - np.min(x)), 1.0e-12)
    y_span = max(float(np.max(y) - np.min(y)), 1.0e-12)
    distance = np.sqrt(
        ((x - np.min(x)) / x_span) ** 2
        + ((y - np.min(y)) / y_span) ** 2
    )
    selected = front.iloc[[int(np.argmin(distance))]].copy()
    selected["selection"] = "normalised_pareto_knee"
    return selected


def compact_json_dump(data: Any, path: Path) -> None:
    path.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
