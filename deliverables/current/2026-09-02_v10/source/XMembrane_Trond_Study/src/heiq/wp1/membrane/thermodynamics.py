"""Thermodynamic audits for coupled electro-osmotic water transport.

The transport convention used throughout WP1 is positive water flux and
positive current from the process/source surface to the receiver surface.
For that convention the water chemical-potential rise is

    delta_mu_w = R T ln(a_receiver / a_source).

An active EO state is allowed to have ``delta_mu_w > 0``.  That is pumping
uphill and is not, by itself, a thermodynamic violation.  For the
constant-drag power-law constitutive model, the useful identities are

    j V_water = N_EO delta_mu_w

and

    j (V_ohmic + V_water) - N_net delta_mu_w
      = j V_ohmic + (-N_diff) delta_mu_w >= 0.

The second expression is the membrane dissipation per active area.  It is the
appropriate sign/entropy diagnostic for active transport; the raw difference
``a_source - a_receiver`` is retained only as a regime indicator.
"""

from __future__ import annotations

import math
from typing import Any, Mapping


FARADAY_C_MOL = 96485.33212
R_UNIVERSAL_J_MOL_K = 8.314462618
ACTIVITY_EPS = 1.0e-12


def water_chemical_potential_difference_j_mol(
    source_surface_activity: float,
    receiver_surface_activity: float,
    temperature_c: float,
) -> float:
    """Return ``mu_receiver - mu_source`` for water.

    Positive values mean that positive source-to-receiver water transport is
    uphill in chemical potential.
    """

    source = float(source_surface_activity)
    receiver = float(receiver_surface_activity)
    temperature_k = float(temperature_c) + 273.15
    if not (
        math.isfinite(source)
        and math.isfinite(receiver)
        and math.isfinite(temperature_k)
        and source > ACTIVITY_EPS
        and receiver > ACTIVITY_EPS
        and temperature_k > 0.0
    ):
        return math.nan
    return R_UNIVERSAL_J_MOL_K * temperature_k * math.log(receiver / source)


def _relative_error(residual: float, *terms: float) -> float:
    scale = max(*(abs(float(value)) for value in terms), ACTIVITY_EPS)
    return float(residual) / scale


def audit_local_transport(
    *,
    source_surface_activity: float,
    receiver_surface_activity: float,
    temperature_c: float,
    current_density_a_m2: float,
    net_flux_mol_m2_s: float,
    eo_flux_mol_m2_s: float,
    diffusion_flux_mol_m2_s: float,
    ohmic_voltage_v: float,
    water_polarisation_voltage_v: float,
    series_loss_voltage_v: float = 0.0,
    fixed_loss_voltage_v: float = 0.0,
    coupling_identity_required: bool = True,
    identity_relative_tolerance: float = 2.0e-7,
    nonnegative_power_tolerance_w_m2: float = 1.0e-10,
) -> dict[str, Any]:
    """Audit one local membrane state without imposing a passive-gradient gate."""

    values = {
        "source": float(source_surface_activity),
        "receiver": float(receiver_surface_activity),
        "temperature_c": float(temperature_c),
        "current": float(current_density_a_m2),
        "net_flux": float(net_flux_mol_m2_s),
        "eo_flux": float(eo_flux_mol_m2_s),
        "diffusion_flux": float(diffusion_flux_mol_m2_s),
        "ohmic_voltage": float(ohmic_voltage_v),
        "water_voltage": float(water_polarisation_voltage_v),
        "series_voltage": float(series_loss_voltage_v),
        "fixed_voltage": float(fixed_loss_voltage_v),
    }
    finite_inputs = all(math.isfinite(value) for value in values.values())
    activities_valid = bool(
        finite_inputs
        and ACTIVITY_EPS < values["source"] < 1.0
        and ACTIVITY_EPS < values["receiver"] < 1.0
        and values["temperature_c"] > -273.15
    )
    delta_mu = water_chemical_potential_difference_j_mol(
        values["source"], values["receiver"], values["temperature_c"]
    )

    flux_identity_residual = (
        values["net_flux"] - values["eo_flux"] - values["diffusion_flux"]
    )
    flux_identity_relative_error = _relative_error(
        flux_identity_residual,
        values["net_flux"],
        values["eo_flux"],
        values["diffusion_flux"],
    )

    water_polarisation_power = values["current"] * values["water_voltage"]
    net_chemical_work = values["net_flux"] * delta_mu
    eo_chemical_work = values["eo_flux"] * delta_mu
    diffusive_dissipation = -values["diffusion_flux"] * delta_mu
    ohmic_dissipation = values["current"] * values["ohmic_voltage"]
    membrane_electrical_power = values["current"] * (
        values["ohmic_voltage"] + values["water_voltage"]
    )
    membrane_dissipation = membrane_electrical_power - net_chemical_work
    decomposed_membrane_dissipation = ohmic_dissipation + diffusive_dissipation
    series_dissipation = values["current"] * values["series_voltage"]
    fixed_loss_dissipation = values["current"] * values["fixed_voltage"]
    total_cell_dissipation = (
        membrane_dissipation + series_dissipation + fixed_loss_dissipation
    )

    coupling_residual = water_polarisation_power - eo_chemical_work
    coupling_relative_error = _relative_error(
        coupling_residual, water_polarisation_power, eo_chemical_work
    )
    dissipation_identity_residual = (
        membrane_dissipation - decomposed_membrane_dissipation
    )
    dissipation_identity_relative_error = _relative_error(
        dissipation_identity_residual,
        membrane_dissipation,
        decomposed_membrane_dissipation,
    )

    downhill_diffusion_pass = bool(
        math.isfinite(diffusive_dissipation)
        and diffusive_dissipation >= -nonnegative_power_tolerance_w_m2
    )
    nonnegative_dissipation_pass = bool(
        math.isfinite(membrane_dissipation)
        and math.isfinite(ohmic_dissipation)
        and membrane_dissipation >= -nonnegative_power_tolerance_w_m2
        and ohmic_dissipation >= -nonnegative_power_tolerance_w_m2
    )
    flux_identity_pass = bool(
        abs(flux_identity_relative_error) <= identity_relative_tolerance
    )
    coupling_identity_pass = bool(
        abs(coupling_relative_error) <= identity_relative_tolerance
    )
    dissipation_decomposition_pass = bool(
        abs(dissipation_identity_relative_error)
        <= identity_relative_tolerance
    )
    identity_pass = bool(
        flux_identity_pass
        and (
            not coupling_identity_required
            or (coupling_identity_pass and dissipation_decomposition_pass)
        )
    )
    thermodynamic_consistency_pass = bool(
        activities_valid
        and identity_pass
        and (downhill_diffusion_pass or not coupling_identity_required)
        and nonnegative_dissipation_pass
    )

    surface_margin = values["source"] - values["receiver"]
    uphill_active = bool(
        values["net_flux"] > 0.0
        and math.isfinite(delta_mu)
        and delta_mu > 0.0
    )
    if uphill_active:
        transport_regime = "uphill_active"
    elif values["net_flux"] * delta_mu < 0.0:
        transport_regime = "downhill"
    elif abs(values["net_flux"] * delta_mu) <= nonnegative_power_tolerance_w_m2:
        transport_regime = "chemical_equilibrium_or_zero_flux"
    else:
        transport_regime = "uphill_nonpositive_or_reverse_flux"

    return {
        "surface_activity_margin": surface_margin,
        "passive_surface_direction": bool(surface_margin > 0.0),
        "transport_regime": transport_regime,
        "uphill_active_transport": uphill_active,
        "delta_mu_water_j_mol": delta_mu,
        "flux_identity_residual_mol_m2_s": flux_identity_residual,
        "flux_identity_relative_error": flux_identity_relative_error,
        "water_polarisation_power_density_w_m2": water_polarisation_power,
        "net_chemical_work_density_w_m2": net_chemical_work,
        "eo_chemical_work_density_w_m2": eo_chemical_work,
        "diffusive_dissipation_density_w_m2": diffusive_dissipation,
        "ohmic_dissipation_density_w_m2": ohmic_dissipation,
        "membrane_electrical_power_density_w_m2": membrane_electrical_power,
        "membrane_dissipation_density_w_m2": membrane_dissipation,
        "decomposed_membrane_dissipation_density_w_m2": (
            decomposed_membrane_dissipation
        ),
        "series_dissipation_density_w_m2": series_dissipation,
        "fixed_loss_dissipation_density_w_m2": fixed_loss_dissipation,
        "total_cell_dissipation_density_w_m2": total_cell_dissipation,
        "coupling_identity_residual_w_m2": coupling_residual,
        "coupling_identity_relative_error": coupling_relative_error,
        "dissipation_identity_residual_w_m2": dissipation_identity_residual,
        "dissipation_identity_relative_error": dissipation_identity_relative_error,
        "coupling_identity_applicable": bool(coupling_identity_required),
        "thermodynamic_audit_level": (
            "full_constant_drag_constitutive_identity"
            if coupling_identity_required
            else "variable_drag_boundary_energy_balance"
        ),
        "flux_identity_pass": flux_identity_pass,
        "coupling_identity_pass": coupling_identity_pass,
        "dissipation_decomposition_pass": dissipation_decomposition_pass,
        "downhill_diffusion_pass": downhill_diffusion_pass,
        "nonnegative_dissipation_pass": nonnegative_dissipation_pass,
        "thermodynamic_identity_pass": identity_pass,
        "thermodynamic_consistency_pass": thermodynamic_consistency_pass,
    }


def audit_local_record(
    record: Mapping[str, Any],
    *,
    temperature_c: float,
    identity_relative_tolerance: float = 2.0e-7,
    nonnegative_power_tolerance_w_m2: float = 1.0e-10,
    coupling_identity_required: bool = True,
) -> dict[str, Any]:
    """Audit a canonical V2/local-state record."""

    return audit_local_transport(
        source_surface_activity=float(record["source_surface_activity"]),
        receiver_surface_activity=float(record["receiver_surface_activity"]),
        temperature_c=float(temperature_c),
        current_density_a_m2=float(record["current_density_a_m2"]),
        net_flux_mol_m2_s=float(record["net_flux_mol_m2_s"]),
        eo_flux_mol_m2_s=float(record["eo_flux_mol_m2_s"]),
        diffusion_flux_mol_m2_s=float(record["diffusion_flux_mol_m2_s"]),
        ohmic_voltage_v=float(record["ohmic_voltage_v"]),
        water_polarisation_voltage_v=float(
            record["water_polarisation_voltage_v"]
        ),
        series_loss_voltage_v=float(record.get("series_loss_voltage_v", 0.0)),
        fixed_loss_voltage_v=float(record.get("fixed_loss_voltage_v", 0.0)),
        coupling_identity_required=coupling_identity_required,
        identity_relative_tolerance=identity_relative_tolerance,
        nonnegative_power_tolerance_w_m2=nonnegative_power_tolerance_w_m2,
    )


__all__ = [
    "FARADAY_C_MOL",
    "R_UNIVERSAL_J_MOL_K",
    "water_chemical_potential_difference_j_mol",
    "audit_local_transport",
    "audit_local_record",
]
