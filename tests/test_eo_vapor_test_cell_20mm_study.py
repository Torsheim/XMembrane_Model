from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "analyze_eo_vapor_test_cell_20mm.py"
CONFIG_PATH = ROOT / "config" / "eo_vapor_test_cell_20mm_channel_study.json"
BASE_CONFIG_PATH = ROOT / "config" / "eo_vapor_test_cell_design.json"
SPEC = importlib.util.spec_from_file_location("eo_test_cell_20mm_study", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
STUDY = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
BASE = json.loads(BASE_CONFIG_PATH.read_text(encoding="utf-8"))
BASE_MODEL = MODULE.load_base_model(ROOT / "scripts" / "design_eo_vapor_test_cell.py")
QUANTITIES = MODULE.base_quantities(BASE, BASE_MODEL)


def test_study_interprets_20mm_as_bulk_depth_and_preserves_local_gap() -> None:
    MODULE.validate_study_config(STUDY, BASE)
    assert STUDY["interpretation"]["requested_channel_depth_mm"] == 20.0
    assert STUDY["interpretation"]["local_membrane_gap_remains_mm"] == 2.0
    assert BASE["integrated_sealed_cell"]["membrane_region"]["nominal_gap_mm"] == 2.0


def test_release_checksum_verifier_detects_payload_drift(tmp_path: Path) -> None:
    release = tmp_path / "release"
    release.mkdir()
    payload = release / "payload.txt"
    payload.write_text("bound payload\n", encoding="utf-8")
    digest = hashlib.sha256(payload.read_bytes()).hexdigest()
    (release / "SHA256SUMS").write_text(
        f"{digest}  payload.txt\n", encoding="utf-8"
    )

    clean = MODULE.verify_release_checksums(release)
    assert clean["all_pass"]
    assert clean["entries_checked"] == 1
    payload.write_text("changed payload\n", encoding="utf-8")
    changed = MODULE.verify_release_checksums(release)
    assert not changed["all_pass"]
    assert changed["failures"] == ["payload.txt: checksum mismatch"]


def test_literal_100x100x20_geometry_fails_original_volume_basis() -> None:
    frame = MODULE.build_scenario_frame(STUDY, QUANTITIES).set_index("scenario_id")
    literal = frame.loc["100x100x20_geometry_only"]
    bounded = frame.loc["100x100x20_with_conservative_component_bound"]

    assert math.isclose(literal["gross_empty_cavity_volume_ml_per_side"], 200.0)
    assert math.isclose(literal["resulting_net_gas_volume_ml_per_side"], 200.0)
    assert math.isclose(bounded["resulting_net_gas_volume_ml_per_side"], 177.4)
    assert not bool(literal["meets_rh_volume_minimum"])
    assert not bool(bounded["meets_rh_volume_minimum"])
    assert math.isclose(
        literal["single_chamber_rh_change_pp"], 10.689010317885824, rel_tol=1e-10
    )
    assert math.isclose(
        literal["rigid_chamber_differential_pressure_pa"],
        1017.1321691328133,
        rel_tol=1e-12,
    )
    assert math.isclose(
        literal["maximum_segment_duration_for_rh_limit_s"],
        2.3388507688282165,
        rel_tol=1e-10,
    )


def test_recommended_165mm_cavity_has_trim_margin_for_500ml() -> None:
    frame = MODULE.build_scenario_frame(STUDY, QUANTITIES).set_index("scenario_id")
    pretrim = frame.loc["165x165x20_before_calibration_trim"]
    calibrated = frame.loc["165x165x20_calibrated_to_500ml"]

    assert math.isclose(pretrim["gross_empty_cavity_volume_ml_per_side"], 544.5)
    assert math.isclose(pretrim["assumed_component_displacement_ml_per_side"], 22.6)
    assert math.isclose(pretrim["resulting_net_gas_volume_ml_per_side"], 521.9)
    assert bool(pretrim["meets_rh_volume_minimum"])
    assert math.isclose(calibrated["nominal_trim_insert_ml_per_side"], 21.9)
    assert math.isclose(calibrated["resulting_net_gas_volume_ml_per_side"], 500.0)
    assert bool(calibrated["within_500ml_calibration_band"])


def test_geometry_thresholds_follow_volume_identity() -> None:
    scenarios = MODULE.build_scenario_frame(STUDY, QUANTITIES)
    summary = MODULE.build_decision_summary(STUDY, QUANTITIES, scenarios)
    thresholds = summary["geometry_thresholds"]

    assert math.isclose(
        thresholds["minimum_square_side_for_500ml_without_hardware_mm"],
        math.sqrt(25_000.0),
    )
    assert math.isclose(
        thresholds["minimum_square_side_for_500ml_with_displacement_bound_mm"],
        math.sqrt(26_130.0),
    )
    assert math.isclose(
        thresholds["required_depth_at_100mm_face_with_displacement_bound_mm"],
        52.26,
    )
    assert MODULE.rectangular_volume_ml(140.0, 140.0, 20.0) == 392.0
    assert 392.0 < QUANTITIES["required_volume_ml"]


def test_compact_protocol_alternative_uses_installed_volume_bound() -> None:
    scenarios = MODULE.build_scenario_frame(STUDY, QUANTITIES)
    summary = MODULE.build_decision_summary(STUDY, QUANTITIES, scenarios)
    alternative = summary["design_alternatives"][
        "compact_cell_with_revised_protocol"
    ]

    assert math.isclose(
        alternative["conservative_installed_net_volume_ml_per_side"], 177.4
    )
    assert math.isclose(
        alternative["maximum_segment_duration_s"], 2.074560631950628
    )
    assert math.isclose(
        alternative["minimum_switching_frequency_hz"], 0.2410148887911122
    )
    assert math.isclose(alternative["maximum_flux_g_m2_h"], 86.30172228914611)


def test_alternate_local_20mm_gap_is_separate_and_fails_header_budget() -> None:
    frame = MODULE.build_local_gap_interpretation_frame(STUDY, BASE).set_index(
        "local_gap_mm"
    )
    selected = frame.loc[2.0]
    alternate = frame.loc[20.0]

    assert selected["interpretation"] == "selected_local_gap"
    assert alternate["interpretation"] == "alternate_20mm_local_gap"
    assert selected["local_membrane_region_volume_ml_per_side"] == 5.0
    assert alternate["local_membrane_region_volume_ml_per_side"] == 50.0
    assert alternate["remaining_bulk_volume_at_500ml_ml_per_side"] == 450.0
    assert selected["channel_flow_at_1m_s_l_min"] == 6.0
    assert alternate["channel_flow_at_1m_s_l_min"] == 60.0
    assert math.isclose(alternate["rectangular_hydraulic_diameter_m"], 0.02857142857)
    assert 1760.0 < alternate["reynolds_number"] < 1770.0
    assert alternate["correlation_regime"] == "laminar_fully_developed_parallel_plate"
    assert alternate["gas_film_mass_transfer_coefficient_m_s"] < (
        selected["gas_film_mass_transfer_coefficient_m_s"] / 7.0
    )
    assert bool(selected["proposed_4mm_wall_bore_screen_budget_pass"])
    assert not bool(alternate["proposed_4mm_wall_bore_screen_budget_pass"])
    assert alternate["header_volume_ml_per_side"] > (
        alternate["maximum_interconnect_budget_ml_per_side"]
    )


def test_structural_seal_fastener_and_pressure_screens_are_bounded() -> None:
    scenarios = MODULE.build_scenario_frame(STUDY, QUANTITIES)
    plates = MODULE.build_plate_pressure_screen_frame(STUDY).set_index("component")
    summary = MODULE.build_decision_summary(STUDY, QUANTITIES, scenarios)

    aluminium = plates.loc["aluminium_load_plate"]
    peek = plates.loc["peek_insulating_plate"]
    assert aluminium["pressure_only_maximum_deflection_um"] < 2.0
    assert peek["pressure_only_maximum_deflection_um"] < 12.0
    assert aluminium["pressure_only_maximum_bending_stress_mpa"] < 1.0
    assert math.isclose(
        aluminium["navier_centre_stress_coefficient"], 0.293949, rel_tol=1.0e-5
    )
    assert math.isclose(
        peek["navier_centre_stress_coefficient"], 0.309420, rel_tol=1.0e-5
    )
    assert summary["fastener_screen"]["fastener_count"] == 16
    assert summary["fastener_screen"]["nominal_preload_n_each"] == 1000.0
    assert summary["fastener_screen"]["preload_to_proof_pressure_force_ratio"] > 100.0
    assert math.isclose(
        summary["seal_screen"]["groove_depth_mm_for_25_percent_squeeze"], 1.5
    )
    assert 0.70 < summary["seal_screen"]["resulting_gland_fill_fraction"] < 0.75
    assert 0.75 < summary["seal_screen"][
        "depth_only_worst_gland_fill_fraction"
    ] < 0.80
    assert math.isclose(
        summary["seal_screen"]["gas_seal_surface_roughness_rq_um"], 0.4
    )
    assert (
        980.0
        < summary["pressure_management"]["minimum_travel_from_nominal_ul_per_side"]
        < 1000.0
    )
    assert (
        1960.0
        < summary["pressure_management"]["minimum_full_stroke_ul_per_side"]
        < 2000.0
    )
    assert 390_000.0 < summary["pressure_management"][
        "two_external_reference_diaphragms_minimum_compliance_nl_per_pa_each"
    ] < 410_000.0
    assert 195_000.0 < summary["pressure_management"][
        "one_double_acting_diaphragm_minimum_compliance_nl_per_pa"
    ] < 205_000.0
    assert 3.0 < summary["fan_screen"][
        "five_second_adiabatic_temperature_rise_upper_bound_k"
    ] < 3.1
    assert summary["fan_screen"]["maximum_static_pressure_pa"] > 5.0
    trim_range = summary["recommended_geometry"][
        "required_trim_range_for_zero_to_bounded_component_displacement_ml_per_side"
    ]
    assert math.isclose(trim_range[0], 21.9)
    assert math.isclose(trim_range[1], 44.5)
    assert summary["interconnect_screen"]["idealized_bore_screen_passes_budget"]
    assert not summary["interconnect_screen"][
        "actual_fitting_tube_and_valve_volume_included"
    ]


def test_all_thirteen_gates_have_choices_strengths_weaknesses_and_residual_tests() -> None:
    scenarios = MODULE.build_scenario_frame(STUDY, QUANTITIES)
    plates = MODULE.build_plate_pressure_screen_frame(STUDY)
    summary = MODULE.build_decision_summary(STUDY, QUANTITIES, scenarios)
    gates = MODULE.build_gate_assessment_frame(STUDY, summary, plates)

    required = set(
        BASE["integrated_sealed_cell"]["fabrication_release"][
            "required_register_items"
        ]
    )
    assert set(gates["gate"]) == required
    assert len(gates) == 13
    assert gates["gate_name_no"].str.strip().ne("").all()
    for column in (
        "recommendation",
        "strength",
        "weakness",
        "remaining_evidence",
    ):
        assert gates[column].str.strip().ne("").all()
    assert gates["physical_gate_status"].eq(
        "open_pending_physical_evidence"
    ).all()


def test_cli_writes_hash_bound_passing_study(tmp_path: Path) -> None:
    output = tmp_path / "twenty-mm-study"
    completed = subprocess.run(
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
    result = json.loads(completed.stdout)
    assert result["status"] == "PASS"
    assert result["literal_100mm_status"] == "REJECT"
    assert result["assessed_gates"] == 13

    audit = json.loads((output / "audit.json").read_text(encoding="utf-8"))
    manifest = json.loads(
        (output / "source_manifest.json").read_text(encoding="utf-8")
    )
    assert audit["all_pass"]
    assert all(audit["checks"].values())
    assert len(manifest["sources"]) == 6
    assert len(manifest["generated_outputs"]) == 9
    assert manifest["verification"]["frozen_v10_and_handoff_v1_unchanged"]
    release_checks = manifest["verification"]["release_checksum_verification"]
    assert release_checks["v10"]["all_pass"]
    assert release_checks["v10"]["entries_checked"] == 430
    assert release_checks["handoff_v1"]["all_pass"]
    assert release_checks["handoff_v1"]["entries_checked"] == 38
    assert (output / "channel_depth_tradeoff.png").stat().st_size > 10_000
    report = (output / "REPORT.md").read_text(encoding="utf-8")
    assert "Styrke" in report
    assert "Svakhet" in report
    for record in manifest["generated_outputs"]:
        path = output / record["path"]
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]
