from __future__ import annotations

import math

import pytest

from heiq.wp1.membrane.thermodynamics import (
    FARADAY_C_MOL,
    audit_local_transport,
    water_chemical_potential_difference_j_mol,
)


def test_uphill_active_transport_is_not_rejected_by_surface_sign():
    source = 0.40
    receiver = 0.60
    temperature_c = 25.0
    current = 2.0
    drag = 100.0
    eo_flux = drag * current / FARADAY_C_MOL
    diffusion_flux = -1.0e-4
    net_flux = eo_flux + diffusion_flux
    delta_mu = water_chemical_potential_difference_j_mol(
        source, receiver, temperature_c
    )
    water_voltage = drag * delta_mu / FARADAY_C_MOL

    audit = audit_local_transport(
        source_surface_activity=source,
        receiver_surface_activity=receiver,
        temperature_c=temperature_c,
        current_density_a_m2=current,
        net_flux_mol_m2_s=net_flux,
        eo_flux_mol_m2_s=eo_flux,
        diffusion_flux_mol_m2_s=diffusion_flux,
        ohmic_voltage_v=0.01,
        water_polarisation_voltage_v=water_voltage,
    )

    assert audit["surface_activity_margin"] < 0.0
    assert not audit["passive_surface_direction"]
    assert audit["uphill_active_transport"]
    assert audit["transport_regime"] == "uphill_active"
    assert audit["diffusive_dissipation_density_w_m2"] > 0.0
    assert audit["membrane_dissipation_density_w_m2"] > 0.0
    assert audit["thermodynamic_consistency_pass"]


def test_zero_current_diffusion_runs_downhill_and_dissipates():
    source = 0.70
    receiver = 0.30
    temperature_c = 25.0
    diffusion_flux = 1.0e-4
    audit = audit_local_transport(
        source_surface_activity=source,
        receiver_surface_activity=receiver,
        temperature_c=temperature_c,
        current_density_a_m2=0.0,
        net_flux_mol_m2_s=diffusion_flux,
        eo_flux_mol_m2_s=0.0,
        diffusion_flux_mol_m2_s=diffusion_flux,
        ohmic_voltage_v=0.0,
        water_polarisation_voltage_v=0.0,
    )

    assert audit["delta_mu_water_j_mol"] < 0.0
    assert audit["transport_regime"] == "downhill"
    assert audit["diffusive_dissipation_density_w_m2"] > 0.0
    assert audit["thermodynamic_consistency_pass"]


def test_uphill_diffusion_and_wrong_coupling_fail_closed():
    source = 0.40
    receiver = 0.60
    temperature_c = 25.0
    audit = audit_local_transport(
        source_surface_activity=source,
        receiver_surface_activity=receiver,
        temperature_c=temperature_c,
        current_density_a_m2=1.0,
        net_flux_mol_m2_s=2.0e-4,
        eo_flux_mol_m2_s=1.0e-4,
        diffusion_flux_mol_m2_s=1.0e-4,
        ohmic_voltage_v=0.01,
        water_polarisation_voltage_v=0.0,
    )

    assert audit["diffusive_dissipation_density_w_m2"] < 0.0
    assert not audit["downhill_diffusion_pass"]
    assert not audit["thermodynamic_identity_pass"]
    assert not audit["thermodynamic_consistency_pass"]


def test_invalid_activity_returns_a_failed_audit_instead_of_clipping():
    assert math.isnan(
        water_chemical_potential_difference_j_mol(0.0, 0.5, 25.0)
    )
    audit = audit_local_transport(
        source_surface_activity=0.0,
        receiver_surface_activity=0.5,
        temperature_c=25.0,
        current_density_a_m2=1.0,
        net_flux_mol_m2_s=1.0e-4,
        eo_flux_mol_m2_s=1.0e-4,
        diffusion_flux_mol_m2_s=0.0,
        ohmic_voltage_v=0.01,
        water_polarisation_voltage_v=0.1,
    )
    assert not audit["thermodynamic_consistency_pass"]


def test_flux_identity_is_checked_independently():
    delta_mu = water_chemical_potential_difference_j_mol(0.4, 0.6, 25.0)
    current = 1.0
    drag = 20.0
    eo_flux = drag * current / FARADAY_C_MOL
    audit = audit_local_transport(
        source_surface_activity=0.4,
        receiver_surface_activity=0.6,
        temperature_c=25.0,
        current_density_a_m2=current,
        net_flux_mol_m2_s=eo_flux,
        eo_flux_mol_m2_s=eo_flux,
        diffusion_flux_mol_m2_s=1.0e-5,
        ohmic_voltage_v=0.01,
        water_polarisation_voltage_v=drag * delta_mu / FARADAY_C_MOL,
    )
    assert abs(audit["flux_identity_relative_error"]) > 1.0e-3
    assert not audit["thermodynamic_identity_pass"]
    assert not audit["thermodynamic_consistency_pass"]


def test_variable_drag_uses_boundary_energy_balance_not_constant_drag_identity():
    common = dict(
        source_surface_activity=0.4,
        receiver_surface_activity=0.6,
        temperature_c=25.0,
        current_density_a_m2=1.0,
        net_flux_mol_m2_s=1.0e-4,
        eo_flux_mol_m2_s=1.0e-4,
        diffusion_flux_mol_m2_s=0.0,
        ohmic_voltage_v=0.01,
        water_polarisation_voltage_v=0.20,
    )
    constant_drag = audit_local_transport(**common)
    variable_drag = audit_local_transport(
        **common, coupling_identity_required=False
    )

    assert not constant_drag["coupling_identity_pass"]
    assert not constant_drag["thermodynamic_consistency_pass"]
    assert not variable_drag["coupling_identity_applicable"]
    assert variable_drag["membrane_dissipation_density_w_m2"] > 0.0
    assert variable_drag["thermodynamic_consistency_pass"]


def test_variable_drag_negative_boundary_dissipation_fails_closed():
    audit = audit_local_transport(
        source_surface_activity=0.4,
        receiver_surface_activity=0.6,
        temperature_c=25.0,
        current_density_a_m2=1.0,
        net_flux_mol_m2_s=1.0e-4,
        eo_flux_mol_m2_s=1.0e-4,
        diffusion_flux_mol_m2_s=0.0,
        ohmic_voltage_v=0.005,
        water_polarisation_voltage_v=0.005,
        coupling_identity_required=False,
    )

    assert audit["membrane_dissipation_density_w_m2"] < 0.0
    assert not audit["nonnegative_dissipation_pass"]
    assert not audit["thermodynamic_consistency_pass"]


@pytest.mark.parametrize("source,receiver", [(0.2, 0.8), (0.8, 0.2)])
def test_chemical_potential_reverses_with_surface_order(source, receiver):
    forward = water_chemical_potential_difference_j_mol(
        source, receiver, 25.0
    )
    reverse = water_chemical_potential_difference_j_mol(
        receiver, source, 25.0
    )
    assert forward == pytest.approx(-reverse)
