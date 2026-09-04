from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
import csv

import pytest


@pytest.fixture(scope="module")
def delivery_module():
    path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "run_final_delivery_check_v1.py"
    )
    spec = importlib.util.spec_from_file_location(
        "test_final_delivery_check_script", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    assert rows
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def common_voltage_claim_fixture(tmp_path):
    cases_path = tmp_path / "cases.csv"
    envelope_path = tmp_path / "envelope.csv"
    probe_path = tmp_path / "probe.csv"
    decision_columns = [
        "known_eo_grid_and_module_fan_power_kw",
        "conditional_conservative_total_power_kw",
        "conditional_conservative_saving_kw_vs_erv_ac",
    ]
    cases: list[dict[str, object]] = []
    envelope: list[dict[str, object]] = []
    for index, diffusivity in enumerate((1.0e-14, 1.0e-12), start=1):
        case_id = f"o30-D{index}-V1-n16"
        selected_values = {
            "required_active_area_m2": 7000.0 + index,
            "integrated_current_a": 1000.0 + index,
            "cell_power_kw": 18.0 + index,
            "known_eo_grid_and_module_fan_power_kw": 30.0 + index,
            "conditional_conservative_total_power_kw": 380.0 + index,
            "conditional_conservative_saving_kw_vs_erv_ac": 163.0 - index,
        }
        cases.append(
            {
                "case_id": case_id,
                "target_id": "o30",
                "water_diffusivity_m2_s": diffusivity,
                "common_terminal_voltage_v": 1.0,
                "segment_count": 16,
                "status": "COMMON_VOLTAGE_FEASIBLE",
                "resolution_class": "CONVERGED_TARGET",
                "common_voltage_feasible": True,
                "transport_solution_complete": True,
                "terminal_voltage_solution_pass": True,
                "thermodynamic_consistency_pass": True,
                **selected_values,
            }
        )
        cases.append(
            {
                "case_id": f"o30-D{index}-V2-n16",
                "target_id": "o30",
                "water_diffusivity_m2_s": diffusivity,
                "common_terminal_voltage_v": 2.0,
                "segment_count": 16,
                "status": "above_internal_current_search_ceiling",
                "resolution_class": "NUMERICAL_OR_LOCAL_SOLUTION_FAILURE",
                "common_voltage_feasible": False,
                "transport_solution_complete": False,
                "terminal_voltage_solution_pass": False,
                "thermodynamic_consistency_pass": True,
                **{column: "" for column in decision_columns},
            }
        )
        cases.append(
            {
                "case_id": f"full-D{index}-V0p5-n16",
                "target_id": "full_remaining_latent",
                "water_diffusivity_m2_s": diffusivity,
                "common_terminal_voltage_v": 0.5,
                "segment_count": 16,
                "status": "below_reversible_voltage",
                "resolution_class": (
                    "PHYSICAL_NO_COMMON_VOLTAGE_AT_THIS_COORDINATE"
                ),
                "common_voltage_feasible": False,
                "transport_solution_complete": False,
                "terminal_voltage_solution_pass": False,
                "thermodynamic_consistency_pass": True,
                **{column: "" for column in decision_columns},
            }
        )
        cases.append(
            {
                "case_id": f"full-D{index}-V2-n16",
                "target_id": "full_remaining_latent",
                "water_diffusivity_m2_s": diffusivity,
                "common_terminal_voltage_v": 2.0,
                "segment_count": 16,
                "status": "above_internal_current_search_ceiling",
                "resolution_class": "NUMERICAL_OR_LOCAL_SOLUTION_FAILURE",
                "common_voltage_feasible": False,
                "transport_solution_complete": False,
                "terminal_voltage_solution_pass": False,
                "thermodynamic_consistency_pass": True,
                **{column: "" for column in decision_columns},
            }
        )
        envelope.append(
            {
                "target_id": "o30",
                "water_diffusivity_m2_s": diffusivity,
                "sampled_voltage_count": 2,
                "refined_feasible_voltage_count": 1,
                "numerically_confirmed_voltage_count": 1,
                "refined_physical_no_solution_voltage_count": 0,
                "refined_numerical_or_local_unresolved_voltage_count": 1,
                "selection_status": "NUMERICALLY_CONFIRMED_FEASIBLE_VOLTAGE",
                "full_system_claim_allowed": False,
                "selected_case_id": case_id,
                "selected_common_terminal_voltage_v": 1.0,
                "selected_required_active_area_m2": selected_values[
                    "required_active_area_m2"
                ],
                "selected_known_eo_grid_and_module_fan_power_kw": selected_values[
                    "known_eo_grid_and_module_fan_power_kw"
                ],
                "selected_conditional_conservative_total_power_kw": selected_values[
                    "conditional_conservative_total_power_kw"
                ],
                "selected_conditional_conservative_saving_kw_vs_erv_ac": selected_values[
                    "conditional_conservative_saving_kw_vs_erv_ac"
                ],
            }
        )
        envelope.append(
            {
                "target_id": "full_remaining_latent",
                "water_diffusivity_m2_s": diffusivity,
                "sampled_voltage_count": 2,
                "refined_feasible_voltage_count": 0,
                "numerically_confirmed_voltage_count": 0,
                "refined_physical_no_solution_voltage_count": 1,
                "refined_numerical_or_local_unresolved_voltage_count": 1,
                "selection_status": (
                    "NO_FEASIBLE_SAMPLED_VOLTAGE_WITH_UNRESOLVED_POINTS"
                ),
                "full_system_claim_allowed": False,
                "selected_case_id": "",
                "selected_common_terminal_voltage_v": "",
                "selected_required_active_area_m2": "",
                "selected_known_eo_grid_and_module_fan_power_kw": "",
                "selected_conditional_conservative_total_power_kw": "",
                "selected_conditional_conservative_saving_kw_vs_erv_ac": "",
            }
        )
    for row in cases:
        retry_applied = row["status"] == "above_internal_current_search_ceiling"
        row["numeric_ceiling_retry_applied"] = retry_applied
        row["numeric_ceiling_retry_recovered"] = False
        row["initial_status_before_numeric_ceiling_retry"] = (
            row["status"] if retry_applied else ""
        )
        row["initial_resolution_class_before_numeric_ceiling_retry"] = (
            row["resolution_class"] if retry_applied else ""
        )
    probes = []
    for row in cases:
        if not row["numeric_ceiling_retry_applied"]:
            continue
        probes.append(
            {
                "source_case_id": row["case_id"],
                "target_id": row["target_id"],
                "water_diffusivity_m2_s": row["water_diffusivity_m2_s"],
                "common_terminal_voltage_v": row["common_terminal_voltage_v"],
                "segment_count": row["segment_count"],
                "source_numeric_current_ceiling_a_m2": 50_000.0,
                "elevated_numeric_current_ceiling_a_m2": 5_000_000.0,
                "numeric_ceiling_multiplier": 100.0,
                "source_status": row["status"],
                "elevated_status": row["status"],
                "source_high_bracket_encountered": True,
                "elevated_high_bracket_encountered": True,
                "source_resolution_class": row["resolution_class"],
                "elevated_resolution_class": (
                    "NUMERICAL_OR_LOCAL_SOLUTION_FAILURE"
                ),
                "source_common_voltage_feasible": False,
                "elevated_common_voltage_feasible": False,
                "retry_recovered": False,
                "source_current_density_gate_applied": False,
                "elevated_current_density_gate_applied": False,
                "source_area_is_acceptance_gate": False,
                "elevated_area_is_acceptance_gate": False,
                "source_surface_direction_is_acceptance_gate": False,
                "elevated_surface_direction_is_acceptance_gate": False,
                "elevated_transport_solution_complete": False,
                "elevated_transport_water_balance_pass": False,
                "elevated_terminal_voltage_solution_pass": False,
                "elevated_thermodynamic_consistency_pass": True,
            }
        )
    contract = {
        "selected_target_id": "o30",
        "full_duty_target_id": "full_remaining_latent",
        "selected_segment_count": 16,
        "expected_selected_target_envelope_rows": 2,
        "expected_full_duty_envelope_rows": 2,
        "local_probe_coverage": "all_flagged_cases_at_or_below_2v",
        "maximum_local_probe_voltage_v": 2.0,
        "minimum_local_probe_ceiling_multiplier": 100.0,
        "confirmed_selection_status": "NUMERICALLY_CONFIRMED_FEASIBLE_VOLTAGE",
        "full_duty_open_selection_status": (
            "NO_FEASIBLE_SAMPLED_VOLTAGE_WITH_UNRESOLVED_POINTS"
        ),
        "converged_resolution_class": "CONVERGED_TARGET",
        "unresolved_resolution_class": "NUMERICAL_OR_LOCAL_SOLUTION_FAILURE",
        "physical_no_solution_resolution_class": (
            "PHYSICAL_NO_COMMON_VOLTAGE_AT_THIS_COORDINATE"
        ),
        "legacy_high_bracket_status": "above_internal_current_search_ceiling",
        "feasible_case_status": "COMMON_VOLTAGE_FEASIBLE",
        "unresolved_case_decision_value_columns": decision_columns,
        "selected_numeric_field_mapping": {
            "selected_common_terminal_voltage_v": "common_terminal_voltage_v",
            "selected_required_active_area_m2": "required_active_area_m2",
            "selected_known_eo_grid_and_module_fan_power_kw": (
                "known_eo_grid_and_module_fan_power_kw"
            ),
            "selected_conditional_conservative_total_power_kw": (
                "conditional_conservative_total_power_kw"
            ),
            "selected_conditional_conservative_saving_kw_vs_erv_ac": (
                "conditional_conservative_saving_kw_vs_erv_ac"
            ),
        },
        "numeric_match_relative_tolerance": 1.0e-9,
        "numeric_match_absolute_tolerance": 1.0e-9,
    }

    def write() -> None:
        _write_csv(cases_path, cases)
        _write_csv(envelope_path, envelope)
        _write_csv(probe_path, probes)

    write()
    return {
        "cases_path": cases_path,
        "envelope_path": envelope_path,
        "probe_path": probe_path,
        "cases": cases,
        "envelope": envelope,
        "probes": probes,
        "contract": contract,
        "write": write,
    }


@pytest.fixture
def complete_delivery(tmp_path):
    report_dir = tmp_path / "report"
    report_dir.mkdir()
    tex_path = report_dir / "final_report.tex"
    pdf_path = report_dir / "final_report.pdf"
    tex_path.write_text(
        "\\documentclass{article}\\begin{document}Final\\end{document}\n",
        encoding="utf-8",
    )
    # The delivery checker only needs to establish that the already compiled
    # report artifact exists and is non-empty.  PDF structure is validated by
    # the report build itself, not by these unit tests.
    pdf_path.write_bytes(b"%PDF-1.4\n% final delivery fixture\n%%EOF\n")

    manifest_path = report_dir / "source_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "hash_algorithm": "sha256",
                "files": {
                    tex_path.name: _sha256(tex_path),
                    pdf_path.name: _sha256(pdf_path),
                },
            }
        ),
        encoding="utf-8",
    )

    closure_status = {
        "broad_modelling_can_stop": True,
        "material_data_collection_ready": True,
        # These are deliberately open.  They belong to the material/subsystem
        # phase and must not prevent delivery of the completed model phase.
        "material_candidate_ranking_ready": False,
        "full_system_claim_allowed": False,
        "technology_validated": False,
        "full_duty_sampled_common_voltage_point_feasible": False,
        "full_duty_single_bus_claim_status": (
            "OPEN_UNCONVERGED_SAMPLED_DIAGNOSTIC"
        ),
        "recommended_phase_label": (
            "MODEL STUDY COMPLETE - MATERIAL AND SUBSYSTEM FEASIBILITY STARTS"
        ),
    }
    scientific_audits = [
        {
            "study_id": "direct-active-erv",
            "status": "PASS",
            "checks": [
                {"check": "thermodynamic_consistency", "passed": True},
                {"check": "no_area_acceptance_gate", "passed": True},
            ],
        },
        {
            "study_id": "gradient-closure",
            "status": "PASS",
            "checks": [
                {"check": "surface_film_identity", "passed": True},
                {"check": "signed_triplet_solved", "passed": True},
            ],
        },
    ]
    return {
        "closure_status": closure_status,
        "scientific_audits": scientific_audits,
        "manifest_path": manifest_path,
        "tex_path": tex_path,
        "pdf_path": pdf_path,
    }


def _evaluate(delivery_module, fixture, **overrides):
    inputs = {
        "closure_status": fixture["closure_status"],
        "scientific_audits": fixture["scientific_audits"],
        "manifest_verification": delivery_module.verify_hash_manifest(
            fixture["manifest_path"]
        ),
        "report_tex_path": fixture["tex_path"],
        "report_pdf_path": fixture["pdf_path"],
    }
    inputs.update(overrides)
    return delivery_module.evaluate_delivery(**inputs)


def test_hash_manifest_detects_tampering(delivery_module, complete_delivery):
    initial = delivery_module.verify_hash_manifest(
        complete_delivery["manifest_path"]
    )
    assert initial["passed"]

    complete_delivery["tex_path"].write_text(
        "tampered after the manifest was frozen\n", encoding="utf-8"
    )
    tampered = delivery_module.verify_hash_manifest(
        complete_delivery["manifest_path"]
    )
    assert not tampered["passed"]
    assert tampered["failed_file_count"] == 1

    result = _evaluate(
        delivery_module,
        complete_delivery,
        manifest_verification=tampered,
    )
    assert not result["delivery_ready_today"]
    assert not result["manifest_integrity_pass"]


def test_model_delivery_is_ready_with_declared_next_phase_openings(
    delivery_module, complete_delivery
):
    result = _evaluate(delivery_module, complete_delivery)
    assert result["delivery_ready_today"]
    assert result["model_phase_complete"]
    assert result["scientific_gates_pass"]
    assert result["manifest_integrity_pass"]
    assert result["report_artifacts_pass"]
    assert {
        "material_candidate_ranking_ready",
        "full_system_claim_allowed",
        "technology_validated",
    }.issubset(set(result["accepted_next_phase_open_items"]))
    assert result["blocking_items"] == []


def test_scientific_gate_failure_blocks_delivery_fail_closed(
    delivery_module, complete_delivery
):
    failed_audits = [
        {
            "study_id": "gradient-closure",
            # A contradictory audit must fail closed even if its top-level
            # status was accidentally left at PASS.
            "status": "PASS",
            "checks": [
                {"check": "surface_film_identity", "passed": False},
            ],
        }
    ]
    result = _evaluate(
        delivery_module,
        complete_delivery,
        scientific_audits=failed_audits,
    )
    assert not result["delivery_ready_today"]
    assert not result["scientific_gates_pass"]
    assert result["blocking_items"]


def test_missing_pdf_blocks_delivery_even_when_other_gates_pass(
    delivery_module, complete_delivery
):
    complete_delivery["pdf_path"].unlink()
    result = _evaluate(
        delivery_module,
        complete_delivery,
        # Isolate the explicit artifact check from manifest verification.
        manifest_verification={
            "passed": True,
            "checked_file_count": 2,
            "failed_file_count": 0,
            "files": [],
        },
    )
    assert not result["delivery_ready_today"]
    assert not result["report_artifacts_pass"]
    assert result["blocking_items"]


def test_embedded_source_manifest_detects_stale_upstream_file(
    delivery_module, tmp_path
):
    source = tmp_path / "source.csv"
    source.write_text("x\n1\n", encoding="utf-8")
    manifest = tmp_path / "source_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "path": str(source),
                        "sha256": _sha256(source),
                        "size_bytes": source.stat().st_size,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    assert delivery_module.verify_embedded_source_manifest(manifest)["passed"]
    source.write_text("x\n2\n", encoding="utf-8")
    result = delivery_module.verify_embedded_source_manifest(manifest)
    assert not result["passed"]
    assert result["failed_file_count"] == 1


def test_closure_gate_register_requires_exact_status_contract(
    delivery_module, tmp_path
):
    path = tmp_path / "gates.csv"
    fieldnames = ["gate_id", "status", "blocks", "evidence"]
    rows = [
        {"gate_id": "MODEL", "status": "PASS", "blocks": "model", "evidence": "ok"},
        {"gate_id": "NEXT", "status": "OPEN", "blocks": "next", "evidence": "later"},
        {"gate_id": "RELEASE", "status": "OPEN", "blocks": "release", "evidence": "dirty"},
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    config = {
        "required_model_gate_status": {"MODEL": "PASS"},
        "accepted_next_phase_gate_status": {"NEXT": "OPEN"},
        "release_gate": {
            "gate_id": "RELEASE",
            "accepted_status_for_model_delivery": "OPEN",
        },
    }
    assert delivery_module.verify_closure_gate_register(path, config)["passed"]
    rows[0]["status"] = "FAIL"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    assert not delivery_module.verify_closure_gate_register(path, config)["passed"]


def test_runtime_check_fails_closed_on_impossible_minimum(delivery_module):
    result = delivery_module.verify_runtime(
        {"python": ">=3.10", "numpy": ">=999.0"}
    )
    assert not result["passed"]
    assert result["failed_requirement_count"] == 1


def _common_voltage_result(delivery_module, fixture):
    return delivery_module.verify_common_voltage_claim_integrity(
        fixture["cases_path"],
        fixture["envelope_path"],
        fixture["probe_path"],
        fixture["contract"],
    )


def test_common_voltage_claim_integrity_keeps_full_duty_unresolved_open(
    delivery_module, common_voltage_claim_fixture
):
    result = _common_voltage_result(delivery_module, common_voltage_claim_fixture)
    assert result["passed"]
    assert not result["delivery_blocking"]
    assert result["selected_target"]["failure_count"] == 0
    assert result["high_bracket_fail_closed"]["decision_value_violation_count"] == 0
    assert result["full_duty_claim_guard"]["confirmed_selected_case_count"] == 0
    assert result["full_duty_claim_guard"][
        "refined_numerical_or_local_unresolved_count"
    ] == 2
    assert result["full_duty_maturity_gate"] == {
        "status": "OPEN",
        "required_today": False,
        "delivery_blocking": False,
        "reason": (
            "2 refined points remain numerical/local unresolved; this limits "
            "the full-duty single-bus claim only."
        ),
    }


def test_open_full_duty_maturity_does_not_block_delivery_evaluator(
    delivery_module, complete_delivery, common_voltage_claim_fixture
):
    common = _common_voltage_result(delivery_module, common_voltage_claim_fixture)
    assert common["passed"]
    assert common["full_duty_maturity_gate"]["status"] == "OPEN"
    delivery = _evaluate(
        delivery_module,
        complete_delivery,
        common_voltage_claim_verification=common,
    )
    assert delivery["delivery_ready_today"]
    assert delivery["optional_checks_pass"]["common_voltage_claim_integrity"]


def test_selected_o30_case_must_map_to_a_converged_refined_row(
    delivery_module, common_voltage_claim_fixture
):
    selected_id = common_voltage_claim_fixture["envelope"][0]["selected_case_id"]
    selected = next(
        row
        for row in common_voltage_claim_fixture["cases"]
        if row["case_id"] == selected_id
    )
    selected["resolution_class"] = "NUMERICAL_OR_LOCAL_SOLUTION_FAILURE"
    common_voltage_claim_fixture["write"]()
    result = _common_voltage_result(delivery_module, common_voltage_claim_fixture)
    assert not result["passed"]
    assert result["delivery_blocking"]
    assert not result["hard_checks"]["selected_o30_rows_resolved_and_mapped"]


def test_unresolved_high_bracket_row_cannot_emit_decision_values(
    delivery_module, common_voltage_claim_fixture
):
    unresolved = next(
        row
        for row in common_voltage_claim_fixture["cases"]
        if row["status"] == "above_internal_current_search_ceiling"
    )
    unresolved["conditional_conservative_saving_kw_vs_erv_ac"] = 123.0
    common_voltage_claim_fixture["write"]()
    result = _common_voltage_result(delivery_module, common_voltage_claim_fixture)
    assert not result["passed"]
    assert not result["hard_checks"]["legacy_high_bracket_rows_fail_closed"]
    assert result["high_bracket_fail_closed"][
        "decision_value_violation_count"
    ] == 1


def test_full_duty_open_envelope_cannot_select_a_case(
    delivery_module, common_voltage_claim_fixture
):
    full = next(
        row
        for row in common_voltage_claim_fixture["envelope"]
        if row["target_id"] == "full_remaining_latent"
    )
    full["selected_case_id"] = "full-D1-V2-n16"
    common_voltage_claim_fixture["write"]()
    result = _common_voltage_result(delivery_module, common_voltage_claim_fixture)
    assert not result["passed"]
    assert not result["hard_checks"]["full_duty_claim_remains_fail_closed"]


def test_numeric_ceiling_retry_requires_exact_all_flagged_coverage(
    delivery_module, common_voltage_claim_fixture
):
    common_voltage_claim_fixture["probes"].pop()
    common_voltage_claim_fixture["write"]()
    result = _common_voltage_result(delivery_module, common_voltage_claim_fixture)
    assert not result["passed"]
    assert not result["local_bracket_probe"]["passed"]
    assert result["delivery_blocking"]
    assert result["local_bracket_probe"]["missing_source_case_ids"]


def test_recovered_numeric_ceiling_retry_requires_full_closure(
    delivery_module, common_voltage_claim_fixture
):
    probe = common_voltage_claim_fixture["probes"][0]
    source = next(
        row
        for row in common_voltage_claim_fixture["cases"]
        if row["case_id"] == probe["source_case_id"]
    )
    probe["retry_recovered"] = True
    probe["elevated_status"] = "COMMON_VOLTAGE_FEASIBLE"
    probe["elevated_resolution_class"] = "CONVERGED_TARGET"
    probe["elevated_common_voltage_feasible"] = True
    probe["elevated_transport_solution_complete"] = True
    probe["elevated_transport_water_balance_pass"] = True
    probe["elevated_terminal_voltage_solution_pass"] = False
    probe["elevated_thermodynamic_consistency_pass"] = True
    source["numeric_ceiling_retry_recovered"] = True
    source["common_voltage_feasible"] = True
    source["resolution_class"] = "CONVERGED_TARGET"
    common_voltage_claim_fixture["write"]()
    result = _common_voltage_result(delivery_module, common_voltage_claim_fixture)
    assert not result["passed"]
    failures = result["local_bracket_probe"]["failures"]
    assert any(
        "recovered_probe_missing_full_closure" in row["reasons"]
        for row in failures
    )
