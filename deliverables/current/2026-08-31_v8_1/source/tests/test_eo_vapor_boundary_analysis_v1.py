from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "analyze_eo_vapor_boundaries_v1.py"
SPEC = importlib.util.spec_from_file_location(
    "analyze_eo_vapor_boundaries_v1", SCRIPT
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
CONFIG = json.loads(
    (ROOT / "config" / "eo_vapor_boundary_analysis_v1.json").read_text(
        encoding="utf-8"
    )
)


def material(scenario_id: str):
    return next(
        item
        for item in CONFIG["material_scenarios"]
        if item["scenario_id"] == scenario_id
    )


def test_constant_property_odd_even_identity() -> None:
    item = dict(material("order_unity_fast_diffusion"))
    item["diffusivity_activity_exponent"] = 0.0
    source = np.array([0.501])
    receiver = np.array([0.499])
    k = np.array([0.1])
    j = np.array([10.0])
    plus = MODULE.local_powerlaw_flux(
        source_bulk_activity=source,
        receiver_bulk_activity=receiver,
        signed_current_density_a_m2=j,
        source_film_coefficient=k,
        receiver_film_coefficient=k,
        material=item,
        reference_activity=0.8,
    )["net_flux_mol_m2_s"][0]
    minus = MODULE.local_powerlaw_flux(
        source_bulk_activity=source,
        receiver_bulk_activity=receiver,
        signed_current_density_a_m2=-j,
        source_film_coefficient=k,
        receiver_film_coefficient=k,
        material=item,
        reference_activity=0.8,
    )["net_flux_mol_m2_s"][0]
    membrane_conductance = (
        item["water_diffusivity_m2_s"]
        * item["water_capacity_mol_m3_activity"]
        / (item["dry_thickness_um"] * 1e-6)
    )
    attenuation = 1.0 / (1.0 + membrane_conductance * 2.0 / k[0])
    expected_odd = attenuation * item["water_drag"] * j[0] / MODULE.FARADAY_C_MOL
    expected_even = attenuation * membrane_conductance * (source[0] - receiver[0])
    assert math.isclose(0.5 * (plus - minus), expected_odd, rel_tol=1e-11)
    assert math.isclose(0.5 * (plus + minus), expected_even, rel_tol=1e-11)


def test_project_laminar_film_is_velocity_independent() -> None:
    state = MODULE.film_state(
        temperature_c=np.array([32.0, 32.0]),
        pressure_pa=np.array([101325.0, 101325.0]),
        velocity_m_s=np.array([0.5, 2.0]),
        gap_m=np.array([0.002, 0.002]),
        multiplier=np.array([1.0, 1.0]),
        laminar_sherwood=7.54,
    )
    assert np.all(state["reynolds_number"] < 2300.0)
    assert math.isclose(
        state["activity_film_coefficient_mol_m2_s_activity"][0],
        state["activity_film_coefficient_mol_m2_s_activity"][1],
        rel_tol=1e-14,
    )


def test_static_mismatch_is_rejected_by_polarity_odd_estimator() -> None:
    item = material("order_unity_fast_diffusion")
    nominal = MODULE.nominal_results(CONFIG, item)
    boundaries = MODULE.make_boundary_arrays(
        CONFIG, {"inlet_activity_mismatch_rh_percentage_points": 0.1}
    )
    result = MODULE.evaluate_boundaries(
        config=CONFIG,
        material=item,
        boundaries=boundaries,
        nominal_odd_rate_mg_h=nominal["nominal_odd_rate_mg_h"],
    )
    assert abs(result["single_direction_apparent_error_percent"][0]) > 5.0
    assert abs(result["total_odd_error_percent"][0]) < 0.1


def test_closed_loop_gas_only_time_scales_with_volume() -> None:
    materials = CONFIG["material_scenarios"]
    nominal = {
        item["scenario_id"]: MODULE.nominal_results(CONFIG, item)
        for item in materials
    }
    frame = MODULE.closed_loop_frame(CONFIG, materials, nominal)
    rows = frame[
        (frame["scenario_id"] == "low_drag_slow_diffusion")
        & (
            frame["effective_wall_plus_membrane_capacity_multiple_of_gas"]
            == 0.0
        )
        & (frame["temperature_mismatch_k"] == 0.0)
    ].set_index("gas_volume_l_per_side")
    assert math.isclose(
        rows.loc[5.0, "time_to_5pa_pressure_difference_s"]
        / rows.loc[1.0, "time_to_5pa_pressure_difference_s"],
        5.0,
        rel_tol=1e-12,
    )
    assert rows.loc[0.005, "time_to_5pa_pressure_difference_s"] < 0.1


def test_latin_hypercube_is_seed_deterministic() -> None:
    first = MODULE.latin_hypercube_inputs(CONFIG)
    second = MODULE.latin_hypercube_inputs(CONFIG)
    assert first.equals(second)


def test_equal_area_rectangle_improves_area_perimeter_identifiability() -> None:
    designs = MODULE.aperture_design_identifiability_frame().set_index("design_id")
    current = designs.loc["current_4_9_25_square"]
    recommended = designs.loc["recommended_with_equal_area_rectangle"]
    assert current["design_matrix_rank"] == 3
    assert current["residual_degrees_of_freedom"] == 0
    assert recommended["residual_degrees_of_freedom"] == 2
    assert abs(recommended["area_perimeter_correlation"]) < abs(
        current["area_perimeter_correlation"]
    )
    assert recommended["scaled_design_condition_number"] < current[
        "scaled_design_condition_number"
    ]
