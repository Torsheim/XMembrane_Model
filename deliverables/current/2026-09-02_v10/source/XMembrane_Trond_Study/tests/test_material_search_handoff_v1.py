from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_material_search_handoff_v1.py"
FULL_WORKSPACE_EVIDENCE = (
    ROOT
    / "reports"
    / "team_result_atlas_v8"
    / "HeiQ_XMembrane_Current_Result_and_Decision_Report_2026-08-31_v8.pdf"
)


def load_module():
    spec = importlib.util.spec_from_file_location("material_search_handoff_v1", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(
    not FULL_WORKSPACE_EVIDENCE.is_file(),
    reason="The full multi-repository material-search evidence tree is not present",
)
def test_canonical_local_evidence_contract_passes() -> None:
    module = load_module()
    result = module.validate_local_evidence()
    assert result == {"pass": True, "failure_count": 0, "failures": []}


def test_named_materials_are_not_promoted_to_complete_candidates() -> None:
    module = load_module()
    rows = module.named_material_rows()
    assert len(rows) == 10
    assert not any(row["same_sample_complete"] for row in rows)
    selemion = next(row for row in rows if row["candidate_id"] == "SELEMION_CMVN")
    assert selemion["priority"] == "P0_EVIDENCE_ANCHOR_TEST"
    assert "9.2+/-0.8" in selemion["quantitative_local_evidence"]


def test_synthetic_targets_remain_separate_from_named_materials() -> None:
    module = load_module()
    named_ids = {row["candidate_id"] for row in module.NAMED_MATERIALS}
    synthetic_ids = {row["target_id"] for row in module.SYNTHETIC_TARGETS}
    assert named_ids.isdisjoint(synthetic_ids)
    assert {"TERMINAL1_ANCHOR", "V4_HIGH_TRANSPORT_NUMBER_AXIS", "M00653"} <= synthetic_ids
    terminal = next(row for row in module.SYNTHETIC_TARGETS if row["target_id"] == "TERMINAL1_ANCHOR")
    assert "Not a material" in terminal["forbidden_interpretation"]


@pytest.mark.skipif(
    not FULL_WORKSPACE_EVIDENCE.is_file(),
    reason="The full multi-repository material-search evidence tree is not present",
)
def test_historical_work_and_downloads_are_in_scope() -> None:
    module = load_module()
    source_ids = {row["source_id"] for row in module.SOURCE_RECORDS}
    assert {"HIST-17", "HIST-18", "HIST-22", "HIST-24", "HIST-25", "ARCH-04"} <= source_ids
    assert {"CUR-00", "CUR-16", "CUR-18", "CUR-22", "CUR-25", "CUR-28", "CUR-29", "CUR-31", "CUR-32", "CUR-33", "CUR-34", "CUR-35", "CUR-36", "CUR-37"} <= source_ids
    assert len(source_ids) == 75
    assert module.downloaded_document_summary() == {
        "manifest_rows": 45,
        "unique_documents": 31,
        "duplicate_rows": 14,
    }
    availability = {row["search_id"]: row for row in module.AVAILABILITY_SHEET}
    assert len(availability) == 9
    assert availability["SEARCH_SELEMION_CMVN"]["priority"] == "P0"
    assert availability["SEARCH_NAFION_NR211_NR212"]["proposed_role"] == "Method and thickness controls"
    assert {row["required_physical_coupon_mm"] for row in availability.values()} == {"80 x 80"}
    assert all("usable_80x80_coupon_count" in row for row in availability.values())


def test_known_model_conflicts_are_explicit() -> None:
    module = load_module()
    conflicts = {row["conflict_id"]: row for row in module.MODEL_CONFLICTS}
    assert conflicts["NAFION_IMPLEMENTATIONS"]["status"] == "intentional_model_divergence"
    assert conflicts["M14424_M14425"]["status"].startswith("unresolved")
    assert conflicts["D_VS_CHEMICAL_PERMEANCE"]["status"] == "superseded_interpretation"
    assert conflicts["MAT_ID_SCHEMA_COLLISION"]["status"] == "versioned_schema_collision"
    assert conflicts["RELOCATED_REPORT_MANIFEST_PATHS"]["status"] == "open_portable_release_traceability_defect"
    aliases = {(row["canonical_id"], row["alias"]) for row in module.ALIAS_REGISTER}
    assert ("TERMINAL1_ANCHOR", "terminal1_anchor") in aliases
    assert ("UNRESOLVED_O30_FINAL", "O30_final_material") in aliases


@pytest.mark.skipif(
    not FULL_WORKSPACE_EVIDENCE.is_file(),
    reason="The full controlled-release hierarchy is not present",
)
def test_release_hierarchy_is_hash_verified() -> None:
    module = load_module()
    release = module.current_release_status()
    assert release["v8_1_state"] == "controlled_release"
    assert release["v8_checksum_verification"]["pass"] is True
    assert release["v8_1_checksum_verification"]["pass"] is True
    assert release["v8_1_scientific_delta_from_parent"] is False
    assert release["v8_1_live_tests_pass"] is True
    assert release["v8_1_live_test_passed_count"] == 300
    assert release["v8_1_immutable_repository_archival_release"] is False
    assert release["v8_1_parent_manifest_sha256"] == release["v8_manifest_sha256"]
    assert "team_result_atlas_v8" in release["governing_scientific_report"]
    assert "post-ERV O30" in release["first_system_relevant_coupon_target"]


def test_post_erv_and_direct_erv_boundaries_remain_separate() -> None:
    module = load_module()
    routes = {row["route_id"]: row for row in module.DEVELOPMENT_ROUTES}
    assert routes["ROUTE_POST_ERV_O30"]["priority"] == "P0_FIRST_SYSTEM_EXPERIMENT"
    assert "1228.27 kg/h" in routes["ROUTE_POST_ERV_O30"]["quantitative_anchor"]
    assert routes["ROUTE_DIRECT_ACTIVE_ERV"]["priority"] == "P1_SECONDARY_TARGET"
    assert "0/320" in routes["ROUTE_DIRECT_ACTIVE_ERV"]["quantitative_anchor"]
    gaps = {row["comparison_id"]: row for row in module.gap_rows()}
    assert "4365.918 kg/h" in gaps["DIRECT_ERV_O30_FILM_SURFACE"]["candidate_value"]
    assert "1228.27 kg/h" in gaps["POST_ERV_O30_D_SENSITIVITY"]["current_target"]
    assert "O30 fails stack/engineering" in gaps["DIRECT_ERV_FIXED_AREA_WEATHER_EXTENSION"]["interpretation"]


def test_nafion_is_a_negative_control_not_a_candidate() -> None:
    module = load_module()
    nr211 = next(row for row in module.named_material_rows() if row["candidate_id"] == "NAFION_NR211")
    assert nr211["priority"] == "CONTROL"
    assert "91.63%" in nr211["quantitative_local_evidence"]
    assert "negative/mechanism control" in nr211["active_erv_reading"]
