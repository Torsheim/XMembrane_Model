from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "design_eo_vapor_test_cell.py"
CONFIG_PATH = ROOT / "config" / "eo_vapor_test_cell_design.json"
SPEC = importlib.util.spec_from_file_location("design_eo_vapor_test_cell", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
CONFIG = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

REQUIRED_FABRICATION_GATES = {
    "gross_empty_cavity_volume_and_depth",
    "installed_component_displacement",
    "end_wall_and_central_divider_structural_sizing",
    "fluidic_and_electrical_port_interfaces",
    "internal_fan_selection_and_mounting",
    "baffle_geometry_and_mounting",
    "differential_pressure_management",
    "fixture_mounting_fastener_pattern_and_preload",
    "seal_geometry_and_compression",
    "drawing_datums_and_dimensional_tolerances",
    "loaded_flatness_and_gap_uniformity",
    "internal_mixing_time",
    "net_volume_calibration",
}

UNRESOLVED_PHYSICAL_DIMENSIONS = {
    "gross_cavity_depth_mm_per_side",
    "end_wall_thickness_mm",
    "central_divider_thickness_mm",
    "fluidic_port_thread_and_seal_specification",
    "electrical_feedthrough_specification",
    "internal_fan_part_envelope_mount_and_heat_load",
    "baffle_geometry_and_mounting",
    "external_fixture_mounting_interface",
    "drawing_datum_and_tolerance_scheme",
}


def test_selected_physical_system_is_symmetric_and_valid() -> None:
    MODULE.validate_config(CONFIG)
    volumes = CONFIG["integrated_sealed_cell"]["chamber_net_free_gas_volumes_ml"]
    assert volumes == {"A": 500.0, "B": 500.0}
    region = CONFIG["integrated_sealed_cell"]["membrane_region"]
    assert (region["width_mm"], region["height_mm"]) == (50.0, 50.0)
    assert region["local_gap_options_mm"] == [1.0, 2.0, 4.0]


def test_validation_rejects_asymmetric_chambers() -> None:
    changed = copy.deepcopy(CONFIG)
    changed["integrated_sealed_cell"]["chamber_net_free_gas_volumes_ml"]["B"] = 499.0
    try:
        MODULE.validate_config(changed)
    except ValueError as error:
        assert "equal calibrated net volumes" in str(error)
    else:
        raise AssertionError("Asymmetric chambers must fail validation")


def test_target_rate_and_required_volume_follow_declared_basis() -> None:
    rate = MODULE.integrated_target_water_rate_mg_s(CONFIG)
    assert math.isclose(rate, 13.0 / 90.0, rel_tol=1e-12)
    assert math.isclose(rate * 3600.0, 520.0, rel_tol=1e-12)

    density = MODULE.saturated_water_vapour_density_kg_m3(32.0)
    expected_ml = (rate * 5.0 / 1e6) / (density * 0.05) * 1e6
    observed_ml = MODULE.required_net_volume_ml_per_side(CONFIG)
    assert math.isclose(observed_ml, expected_ml, rel_tol=1e-12)
    assert 425.0 < observed_ml < 430.0


def test_local_bulk_net_and_gross_volumes_are_distinct() -> None:
    rows = MODULE.build_integrated_volume_basis_frame(CONFIG)
    assert rows["local_gap_mm"].tolist() == [1.0, 2.0, 4.0]
    assert rows["local_membrane_region_volume_ml_per_side"].tolist() == [2.5, 5.0, 10.0]
    assert rows["bulk_free_gas_volume_ml_per_side"].tolist() == [497.5, 495.0, 490.0]
    assert (rows["calibrated_net_free_gas_volume_ml_per_side"] == 500.0).all()
    assert rows["gross_empty_cavity_volume_ml_per_side"].isna().all()
    assert rows["gross_cavity_depth_mm_per_side"].isna().all()
    assert (
        rows["local_membrane_region_volume_ml_per_side"]
        + rows["bulk_free_gas_volume_ml_per_side"]
        == rows["calibrated_net_free_gas_volume_ml_per_side"]
    ).all()


def test_selected_volume_meets_half_cycle_drift_criterion() -> None:
    row = MODULE.build_integrated_volume_basis_frame(CONFIG).iloc[0]
    assert math.isclose(
        row["water_transferred_per_half_cycle_mg"], 13.0 / 18.0, rel_tol=1e-12
    )
    assert row["selected_to_required_volume_ratio"] > 1.16
    assert math.isclose(
        row["predicted_single_chamber_rh_change_percentage_points"],
        5.0 / row["selected_to_required_volume_ratio"],
        rel_tol=1e-12,
    )
    assert row["predicted_single_chamber_rh_change_percentage_points"] < 5.0


def test_interconnect_budget_is_named_and_bounded_separately() -> None:
    row = MODULE.build_interconnect_volume_budget_frame(CONFIG).iloc[0]
    assert math.isclose(row["triangular_header_volume_ml_per_side"], 0.75)
    assert math.isclose(row["port_bore_volume_ml_per_side"], 0.4523893421169302)
    assert math.isclose(
        row["interconnect_header_port_volume_ml_per_side"], 1.2223893421169302
    )
    assert row["maximum_interconnect_header_port_volume_ml_per_side"] == 1.3
    assert row["calibrated_net_free_gas_volume_ml_per_side"] == 500.0
    assert row["interconnect_volume_target_pass"]


def test_transient_conserves_inventory_and_is_symmetric() -> None:
    frame = MODULE.build_integrated_transient_frame(CONFIG)
    initial = frame.iloc[0]
    delta_a = frame["water_inventory_A_mg"] - initial["water_inventory_A_mg"]
    delta_b = frame["water_inventory_B_mg"] - initial["water_inventory_B_mg"]
    assert (
        frame["total_water_inventory_mg"] - initial["total_water_inventory_mg"]
    ).abs().max() < 1e-12
    assert (delta_a + delta_b).abs().max() < 1e-12
    assert len(frame) == 201


def test_abba_endpoints_and_pressure_diagnostic() -> None:
    frame = MODULE.build_integrated_transient_frame(CONFIG)
    endpoints = frame[frame["time_s"].isin([0.0, 5.0, 10.0, 15.0, 20.0])]
    expected = [0.0, 13.0 / 18.0, 0.0, -13.0 / 18.0, 0.0]
    assert all(
        math.isclose(observed, target, abs_tol=1e-12)
        for observed, target in zip(
            endpoints["signed_water_transferred_A_to_B_mg"], expected
        )
    )
    peak = endpoints[endpoints["time_s"] == 5.0].iloc[0]
    assert 45.0 < peak["relative_humidity_A_percent"] < 46.0
    assert 54.0 < peak["relative_humidity_B_percent"] < 55.0
    assert 400.0 < peak["gas_only_differential_pressure_B_minus_A_pa"] < 410.0
    assert math.isclose(endpoints.iloc[-1]["relative_humidity_A_percent"], 50.0, abs_tol=1e-12)
    assert math.isclose(endpoints.iloc[-1]["relative_humidity_B_percent"], 50.0, abs_tol=1e-12)


def test_time_response_scales_with_selected_chamber_inventory() -> None:
    baseline = MODULE.build_integrated_transient_frame(CONFIG)
    doubled = copy.deepcopy(CONFIG)
    doubled["integrated_sealed_cell"]["chamber_net_free_gas_volumes_ml"] = {
        "A": 1000.0,
        "B": 1000.0,
    }
    doubled["integrated_sealed_cell"]["volume_sizing_basis"][
        "selected_net_free_gas_volume_ml_per_side"
    ] = 1000.0
    doubled_frame = MODULE.build_integrated_transient_frame(doubled)

    baseline_step = abs(
        float(baseline.loc[baseline["time_s"].eq(5.0), "relative_humidity_A_percent"].iloc[0])
        - 50.0
    )
    doubled_step = abs(
        float(
            doubled_frame.loc[
                doubled_frame["time_s"].eq(5.0), "relative_humidity_A_percent"
            ].iloc[0]
        )
        - 50.0
    )
    assert math.isclose(doubled_step, baseline_step / 2.0, rel_tol=1e-12)


def test_engineering_register_explicitly_gates_every_physical_tbd() -> None:
    cell = CONFIG["integrated_sealed_cell"]
    release = cell["fabrication_release"]
    register = MODULE.build_integrated_engineering_register_frame(CONFIG)
    register_by_item = register.set_index("item")

    assert release["ready"] is False
    assert set(release["required_register_items"]) == REQUIRED_FABRICATION_GATES
    assert REQUIRED_FABRICATION_GATES.issubset(set(register_by_item.index))
    assert (
        register_by_item.loc[sorted(REQUIRED_FABRICATION_GATES), "status"] == "open"
    ).all()
    assert (
        register_by_item.loc[sorted(REQUIRED_FABRICATION_GATES), "closure_evidence"]
        .str.strip()
        .ne("")
        .all()
    )
    assert set(release["unresolved_dimensions"]) == UNRESOLVED_PHYSICAL_DIMENSIONS
    assert all(value is None for value in release["unresolved_dimensions"].values())
    assert register_by_item.loc["net_free_gas_volume_target", "status"] == "defined"
    assert register_by_item.loc["net_volume_calibration", "status"] == "open"


def test_validation_rejects_premature_fabrication_release() -> None:
    changed = copy.deepcopy(CONFIG)
    changed["integrated_sealed_cell"]["fabrication_release"]["ready"] = True
    try:
        MODULE.validate_config(changed)
    except ValueError as error:
        assert "cannot be ready" in str(error)
    else:
        raise AssertionError("An open engineering register must block fabrication release")


def test_cli_writes_passing_portable_hash_bound_package(tmp_path: Path) -> None:
    output = tmp_path / "integrated-cell"
    subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--config",
            str(CONFIG_PATH),
            "--output-dir",
            str(output),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    audit = json.loads((output / "audit.json").read_text(encoding="utf-8"))
    manifest = json.loads((output / "source_manifest.json").read_text(encoding="utf-8"))
    assert audit["all_pass"]
    assert all(audit["checks"].values())
    assert manifest["verification"]["audit_all_pass"]
    assert len(manifest["sources"]) == 2
    assert len(manifest["generated_outputs"]) == 8
    expected_names = {
        "integrated_sealed_cell_volume_basis.csv",
        "integrated_sealed_cell_transient.csv",
        "integrated_sealed_cell_engineering_register.csv",
        "interconnect_header_port_volume_budget.csv",
        "config_used.json",
        "SUMMARY.md",
        "integrated_sealed_cell_transient.png",
        "audit.json",
    }
    assert {Path(record["path"]).name for record in manifest["generated_outputs"]} == expected_names
    for record in manifest["generated_outputs"]:
        path = output / Path(record["path"]).name
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]
