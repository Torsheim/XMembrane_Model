"""Transient blocking-electrode model for electro-osmotic water transport.

The model is deliberately small and auditable.  It combines the reviewed
constant-drag power-law membrane equations with a pair of capacitive
electrodes represented by one effective series capacitance per active area.
Positive current and water flux run from the source/process side to the
receiver side.

The electrical closure per active area is

    V_terminal = V_membrane(j, a) + j r_interface + eta

    c_pair d(eta)/dt = j - j_F

where ``eta`` is the voltage stored across the electrode pair and the optional
diagnostic leakage branch is ``j_F = eta / r_leak``.  The leakage branch is a
linear sensitivity only; it is not a Butler--Volmer or measured Faradaic model.
The applied voltage clamp limits terminal voltage only.  This reduced model
does not resolve individual electrode potentials or impose an electrochemical
stability window on either electrode or on the effective pair capacitance.

For an ideal blocking pair, the charge passed through the membrane over a
closed periodic cycle is zero.  With constant water drag, the incremental EO
water transported over that cycle is consequently zero as well.  The solver
retains signed diffusion and finite gas films so that this invariant is not
confused with the passive ERV contribution.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Mapping, Sequence

import numpy as np
import pandas as pd
from scipy.optimize import brentq

from heiq.wp1.membrane.thermodynamics import (
    FARADAY_C_MOL,
    R_UNIVERSAL_J_MOL_K,
)


ACTIVITY_EPS = 1.0e-9
WATER_MOLAR_MASS_KG_MOL = 0.01801528


class CapacitiveCellError(RuntimeError):
    """Raised when a transient electrode state cannot be closed physically."""


def effective_series_capacitance_f_m2(
    source_electrode_capacitance_f_m2: float,
    receiver_electrode_capacitance_f_m2: float,
) -> float:
    """Return the effective areal capacitance of two electrodes in series."""

    source = float(source_electrode_capacitance_f_m2)
    receiver = float(receiver_electrode_capacitance_f_m2)
    if not (math.isfinite(source) and math.isfinite(receiver)):
        raise ValueError("Electrode capacitances must be finite")
    if source <= 0.0 or receiver <= 0.0:
        raise ValueError("Electrode capacitances must be positive")
    return 1.0 / (1.0 / source + 1.0 / receiver)


def _power_integral(
    lower: float,
    upper: float,
    exponent: float,
    reference_activity: float,
) -> float:
    lower = min(max(float(lower), ACTIVITY_EPS), 1.0 - ACTIVITY_EPS)
    upper = min(max(float(upper), ACTIVITY_EPS), 1.0 - ACTIVITY_EPS)
    shifted = float(exponent) + 1.0
    if abs(shifted) <= 1.0e-10:
        return float(reference_activity) * math.log(upper / lower)
    return (
        upper**shifted - lower**shifted
    ) / (shifted * float(reference_activity) ** float(exponent))


def signed_powerlaw_state(
    *,
    source_bulk_activity: float,
    receiver_bulk_activity: float,
    current_density_a_m2: float,
    source_film_coefficient_mol_m2_s_activity: float,
    receiver_film_coefficient_mol_m2_s_activity: float,
    temperature_c: float,
    material: Mapping[str, Any],
    reference_activity: float,
    transport_series_asr_ohm_m2: float = 0.0,
    newton_iterations: int = 18,
) -> dict[str, Any]:
    """Solve one signed local membrane state at fixed bulk activities.

    This is the scalar package implementation of the signed water-flux replay
    first used in ``analyze_eo_vapor_boundaries_v1.py``.  Its positive-current
    equations reproduce the reviewed V2 constant-drag power-law constitutive
    model, while allowing polarity reversal for a transient electrode cycle.
    """

    a_source = float(source_bulk_activity)
    a_receiver = float(receiver_bulk_activity)
    current = float(current_density_a_m2)
    k_source = float(source_film_coefficient_mol_m2_s_activity)
    k_receiver = float(receiver_film_coefficient_mol_m2_s_activity)
    temperature_k = float(temperature_c) + 273.15
    reference = float(reference_activity)
    series_asr = float(transport_series_asr_ohm_m2)
    if not (
        ACTIVITY_EPS < a_source < 1.0 - ACTIVITY_EPS
        and ACTIVITY_EPS < a_receiver < 1.0 - ACTIVITY_EPS
        and k_source > 0.0
        and k_receiver > 0.0
        and temperature_k > 0.0
        and ACTIVITY_EPS < reference < 1.0
        and series_asr >= 0.0
    ):
        raise ValueError("Invalid activity, film, temperature, or ASR input")

    drag = float(material["water_drag"])
    diffusivity_ref = float(material["water_diffusivity_m2_s"])
    capacity_ref = float(material["water_capacity_mol_m3_activity"])
    conductivity_ref = float(material["conductivity_s_m"])
    thickness_m = float(material["dry_thickness_um"]) * 1.0e-6
    p_diffusion_capacity = float(material["diffusivity_activity_exponent"]) + float(
        material["capacity_activity_exponent"]
    )
    p_conductivity = float(material["conductivity_activity_exponent"])
    if not (
        drag > 0.0
        and diffusivity_ref > 0.0
        and capacity_ref > 0.0
        and conductivity_ref > 0.0
        and thickness_m > 0.0
    ):
        raise ValueError("Material properties must be positive")

    permeability_ref = diffusivity_ref * capacity_ref
    eo_flux = drag * current / FARADAY_C_MOL
    lower_flux = max(
        k_source * (a_source - (1.0 - ACTIVITY_EPS)),
        -k_receiver * (a_receiver - ACTIVITY_EPS),
    )
    upper_flux = min(
        k_source * (a_source - ACTIVITY_EPS),
        k_receiver * ((1.0 - ACTIVITY_EPS) - a_receiver),
    )
    span = upper_flux - lower_flux
    if span <= 0.0:
        return {"solver_success": False, "solver_status": "empty_film_interval"}

    mean_bulk = min(max(0.5 * (a_source + a_receiver), ACTIVITY_EPS), 1.0)
    permeability_mean = permeability_ref * (
        mean_bulk / reference
    ) ** p_diffusion_capacity
    conductance = permeability_mean / thickness_m
    flux = (
        eo_flux + conductance * (a_source - a_receiver)
    ) / (1.0 + conductance * (1.0 / k_source + 1.0 / k_receiver))
    padding = max(1.0e-14, 1.0e-10 * span)
    flux = min(max(flux, lower_flux + padding), upper_flux - padding)

    for _ in range(int(newton_iterations)):
        source_surface = a_source - flux / k_source
        receiver_surface = a_receiver + flux / k_receiver
        integral = _power_integral(
            source_surface,
            receiver_surface,
            p_diffusion_capacity,
            reference,
        )
        residual = flux - eo_flux + permeability_ref * integral / thickness_m
        b_source = permeability_ref * (
            min(max(source_surface, ACTIVITY_EPS), 1.0) / reference
        ) ** p_diffusion_capacity
        b_receiver = permeability_ref * (
            min(max(receiver_surface, ACTIVITY_EPS), 1.0) / reference
        ) ** p_diffusion_capacity
        derivative = 1.0 + (b_source / k_source + b_receiver / k_receiver) / thickness_m
        candidate = flux - residual / derivative
        flux = min(max(candidate, lower_flux + padding), upper_flux - padding)

    source_surface = a_source - flux / k_source
    receiver_surface = a_receiver + flux / k_receiver
    integral_b = _power_integral(
        source_surface,
        receiver_surface,
        p_diffusion_capacity,
        reference,
    )
    residual = flux - eo_flux + permeability_ref * integral_b / thickness_m
    residual_scale = max(abs(flux), abs(eo_flux), 1.0e-10)
    success = bool(
        ACTIVITY_EPS < source_surface < 1.0 - ACTIVITY_EPS
        and ACTIVITY_EPS < receiver_surface < 1.0 - ACTIVITY_EPS
        and abs(residual) / residual_scale < 1.0e-7
    )
    if not success:
        return {
            "solver_success": False,
            "solver_status": "signed_flux_nonconvergence_or_surface_bound",
            "residual_relative": abs(residual) / residual_scale,
        }

    integral_resistance = _power_integral(
        source_surface,
        receiver_surface,
        p_diffusion_capacity - p_conductivity,
        reference,
    )
    if abs(integral_b) < 1.0e-12:
        mean_surface = 0.5 * (source_surface + receiver_surface)
        conductivity = conductivity_ref * (
            mean_surface / reference
        ) ** p_conductivity
        membrane_asr = thickness_m / conductivity
    else:
        membrane_asr = (
            thickness_m
            * integral_resistance
            / integral_b
            / conductivity_ref
        )
    water_voltage = (
        drag
        * R_UNIVERSAL_J_MOL_K
        * temperature_k
        / FARADAY_C_MOL
        * math.log(receiver_surface / source_surface)
    )
    ohmic_voltage = current * membrane_asr
    transport_series_voltage = current * series_asr
    membrane_transport_voltage = (
        water_voltage + ohmic_voltage + transport_series_voltage
    )
    diffusion_flux = flux - eo_flux
    return {
        "solver_success": True,
        "solver_status": "signed_steady_local_state",
        "current_density_a_m2": current,
        "net_flux_mol_m2_s": flux,
        "eo_flux_mol_m2_s": eo_flux,
        "diffusion_flux_mol_m2_s": diffusion_flux,
        "source_surface_activity": source_surface,
        "receiver_surface_activity": receiver_surface,
        "surface_activity_margin": source_surface - receiver_surface,
        "membrane_asr_ohm_m2": membrane_asr,
        "transport_series_asr_ohm_m2": series_asr,
        "ohmic_voltage_v": ohmic_voltage,
        "water_polarisation_voltage_v": water_voltage,
        "transport_series_voltage_v": transport_series_voltage,
        "membrane_transport_voltage_v": membrane_transport_voltage,
        "residual_relative": abs(residual) / residual_scale,
    }


def _terminal_state(
    *,
    charge_density_c_m2: float,
    current_density_a_m2: float,
    pair_capacitance_f_m2: float,
    interface_esr_ohm_m2: float,
    membrane_kwargs: Mapping[str, Any],
) -> dict[str, Any]:
    membrane = signed_powerlaw_state(
        current_density_a_m2=current_density_a_m2,
        **membrane_kwargs,
    )
    if not membrane.get("solver_success"):
        raise CapacitiveCellError(
            f"Signed membrane state failed at j={current_density_a_m2:g} A/m2"
        )
    electrode_voltage = float(charge_density_c_m2) / float(
        pair_capacitance_f_m2
    )
    interface_esr_voltage = float(current_density_a_m2) * float(
        interface_esr_ohm_m2
    )
    terminal_voltage = (
        float(membrane["membrane_transport_voltage_v"])
        + interface_esr_voltage
        + electrode_voltage
    )
    return {
        **membrane,
        "electrode_pair_voltage_v": electrode_voltage,
        "interface_esr_voltage_v": interface_esr_voltage,
        "terminal_voltage_v": terminal_voltage,
    }


def _current_at_voltage_limit(
    *,
    charge_density_c_m2: float,
    target_terminal_voltage_v: float,
    current_density_hardware_limit_a_m2: float,
    pair_capacitance_f_m2: float,
    interface_esr_ohm_m2: float,
    membrane_kwargs: Mapping[str, Any],
) -> dict[str, Any]:
    limit = float(current_density_hardware_limit_a_m2)

    def residual(current: float) -> float:
        return float(
            _terminal_state(
                charge_density_c_m2=charge_density_c_m2,
                current_density_a_m2=current,
                pair_capacitance_f_m2=pair_capacitance_f_m2,
                interface_esr_ohm_m2=interface_esr_ohm_m2,
                membrane_kwargs=membrane_kwargs,
            )["terminal_voltage_v"]
        ) - float(target_terminal_voltage_v)

    low = -limit
    high = limit
    low_residual = residual(low)
    high_residual = residual(high)
    if low_residual > 0.0:
        state = _terminal_state(
            charge_density_c_m2=charge_density_c_m2,
            current_density_a_m2=low,
            pair_capacitance_f_m2=pair_capacitance_f_m2,
            interface_esr_ohm_m2=interface_esr_ohm_m2,
            membrane_kwargs=membrane_kwargs,
        )
        return {**state, "voltage_clamp_hardware_saturated": True}
    if high_residual < 0.0:
        state = _terminal_state(
            charge_density_c_m2=charge_density_c_m2,
            current_density_a_m2=high,
            pair_capacitance_f_m2=pair_capacitance_f_m2,
            interface_esr_ohm_m2=interface_esr_ohm_m2,
            membrane_kwargs=membrane_kwargs,
        )
        return {**state, "voltage_clamp_hardware_saturated": True}
    current = float(brentq(residual, low, high, xtol=1.0e-11, rtol=1.0e-11))
    state = _terminal_state(
        charge_density_c_m2=charge_density_c_m2,
        current_density_a_m2=current,
        pair_capacitance_f_m2=pair_capacitance_f_m2,
        interface_esr_ohm_m2=interface_esr_ohm_m2,
        membrane_kwargs=membrane_kwargs,
    )
    return {**state, "voltage_clamp_hardware_saturated": False}


def _controlled_state(
    *,
    charge_density_c_m2: float,
    commanded_current_density_a_m2: float,
    maximum_absolute_terminal_voltage_v: float,
    current_density_hardware_limit_a_m2: float,
    pair_capacitance_f_m2: float,
    interface_esr_ohm_m2: float,
    membrane_kwargs: Mapping[str, Any],
) -> dict[str, Any]:
    command = float(commanded_current_density_a_m2)
    hardware_limit = float(current_density_hardware_limit_a_m2)
    if abs(command) > hardware_limit + 1.0e-12:
        raise ValueError("Commanded current exceeds the hardware current limit")
    requested = _terminal_state(
        charge_density_c_m2=charge_density_c_m2,
        current_density_a_m2=command,
        pair_capacitance_f_m2=pair_capacitance_f_m2,
        interface_esr_ohm_m2=interface_esr_ohm_m2,
        membrane_kwargs=membrane_kwargs,
    )
    maximum_voltage = float(maximum_absolute_terminal_voltage_v)
    requested_voltage = float(requested["terminal_voltage_v"])
    if abs(requested_voltage) <= maximum_voltage + 1.0e-12:
        return {
            **requested,
            "commanded_current_density_a_m2": command,
            "voltage_clamped": False,
            "voltage_clamp_hardware_saturated": False,
        }
    target_voltage = math.copysign(maximum_voltage, requested_voltage)
    clamped = _current_at_voltage_limit(
        charge_density_c_m2=charge_density_c_m2,
        target_terminal_voltage_v=target_voltage,
        current_density_hardware_limit_a_m2=hardware_limit,
        pair_capacitance_f_m2=pair_capacitance_f_m2,
        interface_esr_ohm_m2=interface_esr_ohm_m2,
        membrane_kwargs=membrane_kwargs,
    )
    return {
        **clamped,
        "commanded_current_density_a_m2": command,
        "voltage_clamped": True,
    }


def simulate_current_controlled_cell(
    *,
    time_s: Sequence[float],
    current_command: Callable[[float], float],
    active_area_m2: float,
    source_electrode_capacitance_f_m2: float,
    receiver_electrode_capacitance_f_m2: float,
    maximum_absolute_terminal_voltage_v: float,
    current_density_hardware_limit_a_m2: float,
    interface_esr_ohm_m2: float,
    interface_leakage_resistance_ohm_m2: float | None,
    energy_recovery_efficiency: float,
    membrane_kwargs: Mapping[str, Any],
    initial_electrode_pair_voltage_v: float = 0.0,
) -> pd.DataFrame:
    """Integrate a current-commanded capacitive cell on a supplied time grid.

    A backward-Euler charge balance is solved at each interval.  This remains
    stable when the electrode RC response is much faster than the reporting
    grid and makes the discrete charge identity explicit.  The
    ``maximum_absolute_terminal_voltage_v`` input is a terminal clamp, not an
    electrode or pair-capacitor electrochemical-window constraint.
    """

    times = np.asarray(time_s, dtype=float)
    if times.ndim != 1 or times.size < 2:
        raise ValueError("time_s must be a one-dimensional grid with >=2 points")
    if not np.all(np.isfinite(times)) or not np.all(np.diff(times) > 0.0):
        raise ValueError("time_s must be finite and strictly increasing")
    area = float(active_area_m2)
    maximum_voltage = float(maximum_absolute_terminal_voltage_v)
    hardware_limit = float(current_density_hardware_limit_a_m2)
    interface_esr = float(interface_esr_ohm_m2)
    recovery = float(energy_recovery_efficiency)
    if not (
        area > 0.0
        and maximum_voltage > 0.0
        and hardware_limit > 0.0
        and interface_esr >= 0.0
        and 0.0 <= recovery <= 1.0
    ):
        raise ValueError("Invalid area, voltage, current, ESR, or recovery input")
    pair_capacitance = effective_series_capacitance_f_m2(
        source_electrode_capacitance_f_m2,
        receiver_electrode_capacitance_f_m2,
    )
    if interface_leakage_resistance_ohm_m2 is None:
        leakage_resistance = math.inf
    else:
        leakage_resistance = float(interface_leakage_resistance_ohm_m2)
        if not math.isfinite(leakage_resistance) or leakage_resistance <= 0.0:
            raise ValueError("Finite leakage resistance must be positive")

    charge = pair_capacitance * float(initial_electrode_pair_voltage_v)
    if abs(float(initial_electrode_pair_voltage_v)) > maximum_voltage:
        raise ValueError("Initial electrode voltage exceeds the terminal limit")

    cumulative_membrane_charge = 0.0
    cumulative_faradaic_charge = 0.0
    cumulative_eo_moles = 0.0
    cumulative_diffusion_moles = 0.0
    cumulative_net_moles = 0.0
    cumulative_terminal_energy = 0.0
    cumulative_import_energy = 0.0
    cumulative_export_energy = 0.0
    cumulative_ohmic_energy = 0.0
    cumulative_interface_leak_energy = 0.0
    cumulative_chemical_work = 0.0
    initial_stored_energy = 0.5 * pair_capacitance * area * (
        float(initial_electrode_pair_voltage_v) ** 2
    )

    records: list[dict[str, Any]] = []

    def leakage_current_density(charge_density: float) -> float:
        if math.isinf(leakage_resistance):
            return 0.0
        return charge_density / pair_capacitance / leakage_resistance

    def append_record(
        *,
        time: float,
        command: float,
        state: Mapping[str, Any],
        faradaic_current: float,
    ) -> None:
        stored = 0.5 * pair_capacitance * area * (
            float(state["electrode_pair_voltage_v"]) ** 2
        )
        grid_energy = cumulative_import_energy - recovery * cumulative_export_energy
        balance_rhs = (
            cumulative_ohmic_energy
            + cumulative_interface_leak_energy
            + cumulative_chemical_work
            + stored
            - initial_stored_energy
        )
        records.append(
            {
                "time_s": float(time),
                "commanded_current_density_a_m2": float(command),
                "current_density_a_m2": float(state["current_density_a_m2"]),
                "faradaic_leakage_current_density_a_m2": float(faradaic_current),
                "capacitive_current_density_a_m2": float(
                    state["current_density_a_m2"] - faradaic_current
                ),
                "charge_density_c_m2": charge,
                "electrode_pair_voltage_v": float(
                    state["electrode_pair_voltage_v"]
                ),
                "membrane_transport_voltage_v": float(
                    state["membrane_transport_voltage_v"]
                ),
                "terminal_voltage_v": float(state["terminal_voltage_v"]),
                "voltage_clamped": bool(state["voltage_clamped"]),
                "voltage_clamp_hardware_saturated": bool(
                    state["voltage_clamp_hardware_saturated"]
                ),
                "net_flux_mol_m2_s": float(state["net_flux_mol_m2_s"]),
                "eo_flux_mol_m2_s": float(state["eo_flux_mol_m2_s"]),
                "diffusion_flux_mol_m2_s": float(
                    state["diffusion_flux_mol_m2_s"]
                ),
                "source_surface_activity": float(
                    state["source_surface_activity"]
                ),
                "receiver_surface_activity": float(
                    state["receiver_surface_activity"]
                ),
                "terminal_power_w": float(
                    state["terminal_voltage_v"]
                    * state["current_density_a_m2"]
                    * area
                ),
                "cumulative_membrane_charge_c": cumulative_membrane_charge,
                "cumulative_faradaic_charge_c": cumulative_faradaic_charge,
                "cumulative_eo_water_mg": cumulative_eo_moles
                * WATER_MOLAR_MASS_KG_MOL
                * 1.0e6,
                "cumulative_diffusion_water_mg": cumulative_diffusion_moles
                * WATER_MOLAR_MASS_KG_MOL
                * 1.0e6,
                "cumulative_net_water_mg": cumulative_net_moles
                * WATER_MOLAR_MASS_KG_MOL
                * 1.0e6,
                "cumulative_terminal_energy_j": cumulative_terminal_energy,
                "cumulative_import_energy_j": cumulative_import_energy,
                "cumulative_export_energy_j": cumulative_export_energy,
                "cumulative_grid_energy_j": grid_energy,
                "stored_capacitor_energy_j": stored,
                "cumulative_ohmic_energy_j": cumulative_ohmic_energy,
                "cumulative_interface_leak_energy_j": (
                    cumulative_interface_leak_energy
                ),
                "cumulative_water_chemical_work_j": cumulative_chemical_work,
                "energy_balance_residual_j": cumulative_terminal_energy
                - balance_rhs,
            }
        )

    initial_command = float(current_command(float(times[0])))
    initial_state = _controlled_state(
        charge_density_c_m2=charge,
        commanded_current_density_a_m2=initial_command,
        maximum_absolute_terminal_voltage_v=maximum_voltage,
        current_density_hardware_limit_a_m2=hardware_limit,
        pair_capacitance_f_m2=pair_capacitance,
        interface_esr_ohm_m2=interface_esr,
        membrane_kwargs=membrane_kwargs,
    )
    append_record(
        time=float(times[0]),
        command=initial_command,
        state=initial_state,
        faradaic_current=leakage_current_density(charge),
    )

    for previous_time, time in zip(times[:-1], times[1:]):
        dt = float(time - previous_time)
        midpoint_time = 0.5 * float(previous_time + time)
        command = float(current_command(midpoint_time))

        def charge_residual(new_charge: float) -> float:
            state = _controlled_state(
                charge_density_c_m2=float(new_charge),
                commanded_current_density_a_m2=command,
                maximum_absolute_terminal_voltage_v=maximum_voltage,
                current_density_hardware_limit_a_m2=hardware_limit,
                pair_capacitance_f_m2=pair_capacitance,
                interface_esr_ohm_m2=interface_esr,
                membrane_kwargs=membrane_kwargs,
            )
            return (
                float(new_charge)
                - charge
                - dt
                * (
                    float(state["current_density_a_m2"])
                    - leakage_current_density(float(new_charge))
                )
            )

        excursion = dt * hardware_limit + pair_capacitance * maximum_voltage + 1.0
        low = charge - excursion
        high = charge + excursion
        low_residual = charge_residual(low)
        high_residual = charge_residual(high)
        expansion = 0
        while low_residual * high_residual > 0.0 and expansion < 12:
            excursion *= 2.0
            low = charge - excursion
            high = charge + excursion
            low_residual = charge_residual(low)
            high_residual = charge_residual(high)
            expansion += 1
        if low_residual * high_residual > 0.0:
            raise CapacitiveCellError("Transient charge step could not be bracketed")

        new_charge = float(
            brentq(
                charge_residual,
                low,
                high,
                xtol=1.0e-10,
                rtol=1.0e-12,
            )
        )
        state = _controlled_state(
            charge_density_c_m2=new_charge,
            commanded_current_density_a_m2=command,
            maximum_absolute_terminal_voltage_v=maximum_voltage,
            current_density_hardware_limit_a_m2=hardware_limit,
            pair_capacitance_f_m2=pair_capacitance,
            interface_esr_ohm_m2=interface_esr,
            membrane_kwargs=membrane_kwargs,
        )
        current = float(state["current_density_a_m2"])
        faradaic_current = leakage_current_density(new_charge)
        terminal_voltage = float(state["terminal_voltage_v"])
        terminal_power_density = terminal_voltage * current
        ohmic_power_density = current**2 * (
            float(state["membrane_asr_ohm_m2"])
            + float(state["transport_series_asr_ohm_m2"])
            + interface_esr
        )
        leakage_power_density = (
            float(state["electrode_pair_voltage_v"]) * faradaic_current
        )
        chemical_power_density = (
            float(state["water_polarisation_voltage_v"]) * current
        )
        interval_charge_density = current * dt
        interval_faradaic_charge_density = faradaic_current * dt

        cumulative_membrane_charge += interval_charge_density * area
        cumulative_faradaic_charge += interval_faradaic_charge_density * area
        cumulative_eo_moles += (
            float(state["eo_flux_mol_m2_s"]) * area * dt
        )
        cumulative_diffusion_moles += (
            float(state["diffusion_flux_mol_m2_s"]) * area * dt
        )
        cumulative_net_moles += (
            float(state["net_flux_mol_m2_s"]) * area * dt
        )
        interval_terminal_energy = terminal_power_density * area * dt
        cumulative_terminal_energy += interval_terminal_energy
        if interval_terminal_energy >= 0.0:
            cumulative_import_energy += interval_terminal_energy
        else:
            cumulative_export_energy += -interval_terminal_energy
        cumulative_ohmic_energy += ohmic_power_density * area * dt
        cumulative_interface_leak_energy += leakage_power_density * area * dt
        cumulative_chemical_work += chemical_power_density * area * dt
        charge = new_charge
        append_record(
            time=float(time),
            command=command,
            state=state,
            faradaic_current=faradaic_current,
        )

    return pd.DataFrame.from_records(records)


__all__ = [
    "ACTIVITY_EPS",
    "WATER_MOLAR_MASS_KG_MOL",
    "CapacitiveCellError",
    "effective_series_capacitance_f_m2",
    "signed_powerlaw_state",
    "simulate_current_controlled_cell",
]
