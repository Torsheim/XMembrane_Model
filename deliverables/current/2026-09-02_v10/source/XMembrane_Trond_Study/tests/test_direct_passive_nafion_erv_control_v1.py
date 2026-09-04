from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_direct_passive_nafion_erv_control_v1.py"
CONFIG = ROOT / "config" / "direct_eo_erv_study_v1.json"
V2_CONFIG = (
    ROOT / "heiq_pre_receiver_material_analyses" / "config" / "default.json"
)


def load_control():
    spec = importlib.util.spec_from_file_location(
        "_direct_passive_nafion_control_test", SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_local_control_is_exactly_zero_current_and_pure_diffusion():
    control = load_control()
    v2 = control.legacy_v2_module()
    v2_config = v2.load_config(V2_CONFIG)
    state = control.solve_zero_current_nafion_state(
        v2=v2,
        v2_config=v2_config,
        source_bulk_activity=0.80,
        receiver_bulk_activity=0.60,
        membrane_temperature_c=25.0,
        dry_thickness_um=25.0,
        drag_scale_factor=1.0,
        source_film_coefficient_mol_m2_s_activity=0.12,
        receiver_film_coefficient_mol_m2_s_activity=0.10,
    )
    assert state["solution_ok"]
    assert state["electrical_boundary_condition"] == "open_circuit_zero_current"
    assert state["terminal_voltage_imposed"] is False
    assert state["current_density_a_m2"] == 0.0
    assert state["integrated_current_a"] == 0.0
    assert state["eo_flux_mol_m2_s"] == 0.0
    assert state["diffusion_flux_mol_m2_s"] == pytest.approx(
        state["net_flux_mol_m2_s"], rel=0.0, abs=1.0e-15
    )
    assert (
        state["receiver_bulk_activity"]
        < state["receiver_surface_activity"]
        < state["source_surface_activity"]
        < state["source_bulk_activity"]
    )
    assert state["maximum_absolute_flux_residual_mol_m2_s"] < 1.0e-12
    # The passive control is open circuit.  It is not obtained by imposing
    # zero terminal voltage, and its water-activity gradient creates a signed
    # membrane diffusion potential.
    assert state["open_circuit_membrane_voltage_v"] < 0.0


def test_zero_current_flux_is_drag_independent_but_open_circuit_voltage_is_not():
    control = load_control()
    v2 = control.legacy_v2_module()
    v2_config = v2.load_config(V2_CONFIG)
    common = {
        "v2": v2,
        "v2_config": v2_config,
        "source_bulk_activity": 0.80,
        "receiver_bulk_activity": 0.60,
        "membrane_temperature_c": 25.0,
        "dry_thickness_um": 25.0,
        "source_film_coefficient_mol_m2_s_activity": 0.12,
        "receiver_film_coefficient_mol_m2_s_activity": 0.10,
    }
    low_drag = control.solve_zero_current_nafion_state(
        **common, drag_scale_factor=0.5
    )
    high_drag = control.solve_zero_current_nafion_state(
        **common, drag_scale_factor=2.0
    )
    assert high_drag["net_flux_mol_m2_s"] == pytest.approx(
        low_drag["net_flux_mol_m2_s"], rel=0.0, abs=1.0e-14
    )
    assert high_drag["open_circuit_membrane_voltage_v"] == pytest.approx(
        4.0 * low_drag["open_circuit_membrane_voltage_v"],
        rel=1.0e-11,
    )


def test_nonpositive_bulk_gradient_fails_without_inventing_reverse_control():
    control = load_control()
    v2 = control.legacy_v2_module()
    v2_config = v2.load_config(V2_CONFIG)
    state = control.solve_zero_current_nafion_state(
        v2=v2,
        v2_config=v2_config,
        source_bulk_activity=0.60,
        receiver_bulk_activity=0.60,
        membrane_temperature_c=25.0,
        dry_thickness_um=25.0,
        drag_scale_factor=1.0,
        source_film_coefficient_mol_m2_s_activity=0.12,
        receiver_film_coefficient_mol_m2_s_activity=0.10,
    )
    assert not state["solution_ok"]
    assert state["solution_status"] == "nonpositive_bulk_activity_gradient"
    assert np.isnan(state["net_flux_mol_m2_s"])
    assert state["current_density_a_m2"] == 0.0
    assert state["eo_flux_mol_m2_s"] == 0.0


def test_case_00936_matched_control_regression():
    control = load_control()
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    v2 = control.legacy_v2_module()
    v2_config = v2.load_config(V2_CONFIG)
    coordinates = control.ControlCoordinates(
        material_id="nafion_nr211_nominal_reference",
        process_outlet_w_g_kg_da=9.5,
        segment_count=8,
        sensible_effectiveness=0.85,
        film_scale_factor=2.0,
        electric_heat_scenario_id="symmetric_split",
        matched_active_case_id=control.DEFAULT_ACTIVE_CASE_ID,
    )
    summary, segments = control.run_control_case(
        coordinates=coordinates,
        config=config,
        v2=v2,
        v2_config=v2_config,
    )
    assert summary["transport_solution_complete"]
    assert summary["thermal_fixed_point_converged"]
    assert summary["transport_water_balance_pass"]
    assert summary["positive_surface_direction"]
    assert summary["robust_surface_direction"]
    # The numerical control uses the same literature correlation as the
    # active row, but its driest local state lies below that correlation's
    # declared lambda range.  This remains a reference calculation, not a
    # validated Nafion claim.
    assert not summary["nafion_correlation_validity_complete"]
    assert summary["current_density_a_m2"] == 0.0
    assert summary["eo_grid_power_kw"] == 0.0
    assert summary["required_passive_membrane_area_m2"] == pytest.approx(
        13770.4318065, rel=2.0e-8
    )
    assert summary["effective_net_flux_mol_m2_s"] == pytest.approx(
        0.00469350475, rel=2.0e-8
    )
    assert summary["minimum_net_flux_mol_m2_s"] == pytest.approx(
        0.00409757293, rel=2.0e-8
    )
    assert summary["maximum_net_flux_mol_m2_s"] == pytest.approx(
        0.00491190892, rel=2.0e-8
    )
    assert summary["minimum_surface_activity_margin"] == pytest.approx(
        0.0216354421, rel=2.0e-8
    )
    assert len(segments) == 8
    assert (segments["current_density_a_m2"] == 0.0).all()
    assert (segments["eo_flux_mol_m2_s"] == 0.0).all()
    assert np.allclose(
        segments["diffusion_flux_mol_m2_s"],
        segments["net_flux_mol_m2_s"],
        rtol=0.0,
        atol=1.0e-14,
    )

    active = {
        "case_id": control.DEFAULT_ACTIVE_CASE_ID,
        "terminal_voltage_v": 0.0005,
        "required_active_area_m2": 13414.500803157433,
        "diffusion_fraction_of_net_water": 0.9163357995563118,
        "eo_grid_power_kw": 0.44350562154229023,
        "conditional_active_total_power_kw": 355.85036079437015,
    }
    comparison = control.compare_to_active_case(summary, active)
    assert comparison["passive_area_increase_pct_vs_active"] == pytest.approx(
        2.65333022, rel=2.0e-8
    )
    assert comparison["passive_minus_active_total_power_kw"] == pytest.approx(
        -0.49268277, rel=2.0e-8
    )


def test_coordinates_reject_non_nafion_active_case():
    control = load_control()
    with pytest.raises(ValueError, match="requires Nafion"):
        control.coordinates_from_active_row(
            {
                "material_id": "terminal1_anchor",
                "process_outlet_w_g_kg_da": 10.0,
                "segment_count": 8,
                "sensible_effectiveness": 0.85,
                "film_scale_factor": 2.0,
                "electric_heat_scenario_id": "symmetric_split",
                "case_id": "not-nafion",
            }
        )


def test_config_rejects_receiver_regeneration():
    control = load_control()
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    config["architecture"]["receiver_regeneration_required"] = True
    with pytest.raises(ValueError, match="Receiver regeneration"):
        control.validate_control_config(config)


def test_materialized_control_has_summary_source_and_output_hashes(tmp_path: Path):
    control = load_control()
    active_case = pd.DataFrame(
        [
            {
                "case_id": control.DEFAULT_ACTIVE_CASE_ID,
                "material_id": "nafion_nr211_nominal_reference",
                "process_outlet_w_g_kg_da": 9.5,
                "terminal_voltage_v": 0.0005,
                "segment_count": 8,
                "sensible_effectiveness": 0.85,
                "film_scale_factor": 2.0,
                "electric_heat_scenario_id": "symmetric_split",
                "required_active_area_m2": 13414.500803157433,
                "diffusion_fraction_of_net_water": 0.9163357995563118,
                "eo_grid_power_kw": 0.44350562154229023,
                "conditional_active_total_power_kw": 355.85036079437015,
            }
        ]
    )
    active_path = tmp_path / "active-case.csv"
    active_case.to_csv(active_path, index=False)
    output = tmp_path / "control"
    audit = control.run(
        config_path=CONFIG,
        v2_config_path=V2_CONFIG,
        active_case_register=active_path,
        active_case_id=control.DEFAULT_ACTIVE_CASE_ID,
        output_dir=output,
        overwrite=False,
    )
    assert audit["status"] == "PASS"
    assert set(audit["sources"]) == {
        "control_script",
        "active_erv_module",
        "canonical_v2_model",
    }
    assert set(audit["outputs_excluding_self_referential_audit"]) == {
        "control_summary.json",
        "segment_register.csv",
        "matched_comparison.json",
        "SUMMARY.md",
    }
    for section in ("sources", "inputs", "outputs_excluding_self_referential_audit"):
        for record in audit[section].values():
            path = Path(record["path"])
            assert path.is_file()
            assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]
            assert path.stat().st_size == record["size_bytes"]
    summary = (output / "SUMMARY.md").read_text(encoding="utf-8")
    assert "Nafion correlation validity" in summary
    assert "**False**" in summary
    assert "13,770.43 m²" in summary
    assert "355.358 kW" in summary
    assert "355.850 kW" in summary
