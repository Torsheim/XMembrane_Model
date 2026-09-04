from __future__ import annotations

import importlib.util
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "size_eo_vapor_cell_v1.py"
SPEC = importlib.util.spec_from_file_location("size_eo_vapor_cell_v1", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
CONFIG = json.loads(
    (ROOT / "config" / "eo_vapor_cell_sizing_v1.json").read_text(
        encoding="utf-8"
    )
)


def test_gross_eo_rate_identity() -> None:
    # 10 cm2 at 100 A/m2 is 0.1 A. With transport number one this is
    # 0.1/F mol/s of water.
    expected = (
        0.1
        / MODULE.FARADAY_C_MOL
        * MODULE.WATER_MOLAR_MASS_KG_MOL
        * 3600.0
        * 1.0e6
    )
    observed = MODULE.gross_eo_water_mg_h(10.0, 100.0, 1.0)
    assert math.isclose(observed, expected, rel_tol=1e-12)


def test_humidity_ratio_round_trip() -> None:
    activity = 0.5
    humidity_ratio = MODULE.humidity_ratio_kg_kg_da(activity, 32.0, 101325.0)
    recovered = MODULE.activity_from_humidity_ratio(
        humidity_ratio, 32.0, 101325.0
    )
    assert math.isclose(recovered, activity, rel_tol=1e-12)


def test_nominal_25_cm2_channel_flow() -> None:
    config = {
        "operating_state": {
            "temperature_c": 32.0,
            "absolute_pressure_pa": 101325.0,
            "equal_inlet_water_activity": 0.5,
        },
        "geometry": {
            "square_active_areas_cm2": [25.0],
            "channel_gaps_mm": [2.0],
            "channel_velocities_m_s": [1.0],
        },
    }
    row = MODULE.build_geometry_frame(config).iloc[0]
    assert math.isclose(row["actual_flow_l_min"], 6.0, rel_tol=1e-12)
    assert math.isclose(row["active_channel_volume_ml_per_side"], 5.0, rel_tol=1e-12)


def test_membrane_diffusion_time_scale_identity() -> None:
    config = {
        "membrane_time_scale_screen": {
            "thickness_um": 40.0,
            "water_diffusivities_m2_s": [2.0e-12],
            "preconditioning_multiple_of_l2_over_d": 4.0,
            "interpretation": "test",
        }
    }
    row = MODULE.build_membrane_time_scale_frame(config).iloc[0]
    expected_s = (40.0e-6) ** 2 / 2.0e-12
    assert math.isclose(row["l2_over_d_seconds"], expected_s, rel_tol=1e-12)
    assert math.isclose(
        row["multiple_l2_over_d_hours"], 4.0 * expected_s / 3600.0, rel_tol=1e-12
    )


def test_boundary_mismatch_linear_scale() -> None:
    config = {
        "boundary_activity_mismatch_screen": {
            "water_capacity_mol_m3_activity": 10000.0,
            "membrane_thickness_um": 40.0,
            "water_diffusivities_m2_s": [1.0e-10],
            "activity_mismatch_rh_percentage_points": [0.1],
            "reference_area_cm2": 25.0,
            "reference_water_transport_number": 1.0,
            "reference_current_densities_a_m2": [3.0],
            "interpretation": "test",
        }
    }
    row = MODULE.build_boundary_mismatch_frame(config).iloc[0]
    expected_mol_s = 1.0e-10 * 10000.0 / 40.0e-6 * 0.001 * 0.0025
    expected_mg_h = (
        expected_mol_s
        * MODULE.WATER_MOLAR_MASS_KG_MOL
        * 3600.0
        * 1.0e6
    )
    assert math.isclose(
        row["linear_passive_water_rate_mg_h"], expected_mg_h, rel_tol=1e-12
    )


def test_fixture_land_and_nominal_aperture_arithmetic() -> None:
    fixture = MODULE.build_fixture_dimension_frame(CONFIG).iloc[0]
    apertures = MODULE.build_aperture_insert_frame(CONFIG).set_index("aperture_id")
    main = apertures.loc["square_50"]
    assert math.isclose(fixture["coupon_land_each_side_x_mm"], 15.0)
    assert math.isclose(
        fixture["remaining_coupon_land_after_seal_guard_stack_mm"], 7.0
    )
    assert math.isclose(main["active_area_cm2"], 25.0)
    assert math.isclose(main["aperture_following_channel_volume_ml_per_side"], 5.0)
    assert math.isclose(
        main["aperture_following_actual_flow_l_min_per_side"], 6.0
    )
    assert math.isclose(
        main["recommended_fixed_flow_field_volume_ml_per_side"], 5.0
    )
    assert math.isclose(main["nonmembrane_wetted_area_cm2_per_side"], 29.0)
    assert math.isclose(main["maximum_internal_dead_volume_ml_per_side"], 1.3)


def test_rotated_slot_preserves_area_perimeter_and_volume_but_changes_flow() -> None:
    rows = MODULE.build_aperture_insert_frame(CONFIG).set_index("aperture_id")
    along = rows.loc["slot_50_along_flow"]
    across = rows.loc["slot_50_across_flow"]
    for field in (
        "active_area_cm2",
        "perimeter_cm",
        "aperture_following_channel_volume_ml_per_side",
    ):
        assert math.isclose(along[field], across[field], rel_tol=1e-12)
    assert math.isclose(
        along["aperture_following_actual_flow_l_min_per_side"], 0.96
    )
    assert math.isclose(
        across["aperture_following_actual_flow_l_min_per_side"], 6.0
    )
    assert math.isclose(along["aperture_following_gas_residence_time_ms"], 50.0)
    assert math.isclose(across["aperture_following_gas_residence_time_ms"], 8.0)
    assert math.isclose(
        along["recommended_fixed_flow_field_actual_flow_l_min_per_side"], 6.0
    )
    assert math.isclose(
        across["recommended_fixed_flow_field_actual_flow_l_min_per_side"], 6.0
    )


def test_internal_volume_budget_matches_proposed_headers_and_ports() -> None:
    row = MODULE.build_internal_volume_budget_frame(CONFIG).iloc[0]
    assert math.isclose(row["active_parallel_plate_volume_ml_per_side"], 5.0)
    assert math.isclose(row["triangular_header_volume_ml_per_side"], 0.75)
    assert math.isclose(
        row["port_bore_volume_ml_per_side"], 0.4523893421169302
    )
    assert math.isclose(
        row["proposed_internal_dead_volume_ml_per_side"], 1.2223893421169302
    )
    assert math.isclose(
        row["proposed_total_swept_internal_volume_ml_per_side"],
        6.22238934211693,
    )
    assert row["dead_volume_target_pass"]


def test_plate_deflection_screen_known_peek_high_load_case() -> None:
    rows = MODULE.build_plate_deflection_frame(CONFIG)
    row = rows[
        (rows["material_id"] == "PEEK")
        & (rows["load_case"] == "high_fixture_load_surrogate")
    ].iloc[0]
    assert math.isclose(
        row["required_plate_thickness_mm_for_allowable_bow"],
        15.352361642245084,
        rel_tol=1e-12,
    )
    assert row["reference_thickness_passes_screen"]
    assert row["predicted_bow_um_at_reference_thickness"] < 20.0


def test_closed_five_ml_pressure_time_matches_inventory_identity() -> None:
    rows = MODULE.build_closed_cell_dimension_frame(CONFIG)
    row = rows[
        (rows["case_id"] == "low_drag_signal_floor")
        & (rows["gas_volume_l_per_side"] == 0.005)
    ].iloc[0]
    assert math.isclose(row["gas_only_time_to_pressure_limit_s"], 0.06338149610110864)
    one_l = rows[
        (rows["case_id"] == "low_drag_signal_floor")
        & (rows["gas_volume_l_per_side"] == 1.0)
    ].iloc[0]
    assert math.isclose(
        one_l["gas_only_time_to_pressure_limit_s"]
        / row["gas_only_time_to_pressure_limit_s"],
        200.0,
        rel_tol=1e-12,
    )


def test_detectability_limit_is_at_declared_signal_threshold() -> None:
    limits = MODULE.build_detectability_limit_frame(CONFIG).set_index("case_id")
    row = limits.loc["low_drag_signal_floor"]
    signal = MODULE.ideal_two_stream_humidity_signal(
        water_rate_mg_h=row["gross_eo_water_mg_h"],
        actual_flow_l_min_per_side=row[
            "maximum_actual_flow_l_min_per_side_for_declared_detectability"
        ],
        inlet_activity=CONFIG["operating_state"]["equal_inlet_water_activity"],
        temperature_c=CONFIG["operating_state"]["temperature_c"],
        absolute_pressure_pa=CONFIG["operating_state"]["absolute_pressure_pa"],
    )
    assert math.isclose(
        signal["differential_signal_rh_percentage_points"],
        row["declared_required_differential_signal_rh_percentage_points"],
        rel_tol=1e-12,
    )


def test_cli_writes_passing_hash_bound_audit(tmp_path: Path) -> None:
    output = tmp_path / "sizing"
    subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--config",
            str(ROOT / "config" / "eo_vapor_cell_sizing_v1.json"),
            "--output-dir",
            str(output),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    audit = json.loads((output / "audit.json").read_text(encoding="utf-8"))
    manifest = json.loads(
        (output / "source_manifest.json").read_text(encoding="utf-8")
    )
    assert audit["all_pass"]
    assert all(audit["checks"].values())
    assert audit["recommended_starting_fixture"]["maximum_active_area_cm2"] == 25.0
    assert manifest["verification"]["audit_all_pass"]
    assert len(manifest["sources"]) == 2
    assert len(manifest["generated_outputs"]) == 19
    for record in [*manifest["sources"], *manifest["generated_outputs"]]:
        path = Path(record["path"])
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]
