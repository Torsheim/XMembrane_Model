from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "analyze_direct_eo_operating_region_v1.py"
GLOBAL_REGISTER = (
    ROOT.parent
    / "HeiQ_V2"
    / "outputs"
    / "EO_symmetric_wet_receiver_sink_v53"
    / "joint_material_operating_gate_register.csv"
)
DENSE_REGISTER = (
    ROOT
    / "outputs"
    / "membrane_operating_region_study_v1"
    / "direct_eo_dense"
    / "joint_material_operating_gate_register.csv"
)


def module():
    spec = importlib.util.spec_from_file_location("_direct_eo_region_v1_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def base_row(cap: float, tw: float = 50.0, diffusivity: float = 0.3) -> dict[str, object]:
    return {
        "source_study": "synthetic",
        "cell_voltage_cap_tested_v": cap,
        "cell_voltage_required_max_v": 1.80,
        "conditional_known_electric_saving_kw": 450.0,
        "process_surface_activity_min": 0.18,
        "strict_physical_and_architecture_pass": True,
        "hard_area_cap_pass": True,
        "current_density_a_m2": 50.0,
        "dry_thickness_um": 20.0,
        "channel_length_m": 0.1,
        "channel_height_mm": 4.0,
        "channel_width_m": 1.0,
        "receiver_control_activity": 0.8,
        "transport_number_reference_t_w": tw,
        "eo_drag_scale_vs_pfsa": 2.0 * tw,
        "water_diffusivity_scale_vs_pfsa": diffusivity,
        "ionic_area_resistance_ohm_m2_at_lambda_ref": 5.0e-6,
        "retention_factor_vs_pfsa_sorption": 1.25,
        "active_area_m2": 2200.0,
        "receiver_sink_net_kg_h": 4500.0,
        "receiver_sink_energy_kw_assumed": 0.0,
    }


def test_cap_deduplication_and_selected_cap_headroom_are_separate():
    mod = module()
    frame = pd.DataFrame([base_row(2.0), base_row(3.0)])
    flagged = mod.add_cap_specific_robust_flags(frame, 0.17, 425.0, 0.25)

    # 1.80 V has only 0.20 V headroom under a 2 V design, but 1.20 V under 3 V.
    assert not bool(flagged.loc[flagged["cell_voltage_cap_tested_v"].eq(2.0), "per_cap_robust_pass"].iloc[0])
    assert bool(flagged.loc[flagged["cell_voltage_cap_tested_v"].eq(3.0), "per_cap_robust_pass"].iloc[0])

    physical = mod.deduplicate_cap_copies(flagged)
    assert len(physical) == 1
    assert physical.iloc[0]["cap_copy_count"] == 2
    assert physical.iloc[0]["available_voltage_caps_v"] == "2;3"


def test_receiver_sec_budget_and_scenario_identity():
    mod = module()
    physical = mod.add_receiver_sec_budget(pd.DataFrame([base_row(5.0)]))
    assert math.isclose(physical.iloc[0]["receiver_sec_budget_kwh_kg"], 0.1)

    scenarios = mod.receiver_sec_scenarios(physical, [0.0, 0.05, 0.10, 0.15])
    values = scenarios.set_index("receiver_sec_assumed_kwh_kg")
    assert math.isclose(values.loc[0.05, "conditional_saving_after_receiver_sec_kw"], 225.0)
    assert math.isclose(values.loc[0.10, "conditional_saving_after_receiver_sec_kw"], 0.0)
    assert not bool(values.loc[0.15, "positive_after_receiver_sec"])


def test_complete_three_by_three_neighbourhood_is_detected():
    mod = module()
    rows: list[dict[str, object]] = []
    for tw in [40.0, 50.0, 60.0]:
        for diffusivity in [0.1, 0.3, 0.6]:
            rows.append(
                {
                    "source_study": "synthetic",
                    "cell_voltage_cap_tested_v": 5.0,
                    "current_density_a_m2": 50.0,
                    "transport_number_reference_t_w": tw,
                    "water_diffusivity_scale_vs_pfsa": diffusivity,
                    "evaluated_coordinates": 1,
                    "robust_passing_coordinates": 1,
                    "any_robust_pass": True,
                }
            )
    neighbourhood = mod.build_3x3_neighborhood(pd.DataFrame(rows))
    centre = neighbourhood.loc[
        np.isclose(neighbourhood["transport_number_reference_t_w"], 50.0)
        & np.isclose(neighbourhood["water_diffusivity_scale_vs_pfsa"], 0.3)
    ].iloc[0]
    corner = neighbourhood.loc[
        np.isclose(neighbourhood["transport_number_reference_t_w"], 40.0)
        & np.isclose(neighbourhood["water_diffusivity_scale_vs_pfsa"], 0.1)
    ].iloc[0]
    assert bool(centre["full_3x3_available"])
    assert bool(centre["all_3x3_cells_have_robust_pass"])
    assert centre["neighbour_cell_count"] == 9
    assert not bool(corner["full_3x3_available"])
    assert corner["neighbour_cell_count"] == 4


@pytest.mark.skipif(
    not GLOBAL_REGISTER.is_file() or not DENSE_REGISTER.is_file(),
    reason="Audited global and dense direct-EO registers are not present",
)
def test_real_registers_reproduce_cap_specific_counts_and_v55_status():
    mod = module()
    global_frame = mod.load_register(GLOBAL_REGISTER, "global_v53")
    dense_frame = mod.load_register(DENSE_REGISTER, "dense_local")
    manifest = mod.load_manifest(ROOT / "config" / "membrane_operating_region_study_v1.json")
    mod.validate_manifest_dense_axes(dense_frame, manifest)

    assert len(dense_frame) == 1320
    assert len(mod.deduplicate_cap_copies(dense_frame)) == 660
    assert 21.0 not in set(dense_frame["current_density_a_m2"])

    combined = pd.concat([global_frame, dense_frame], ignore_index=True, sort=False)
    flagged = mod.add_cap_specific_robust_flags(combined, 0.17, 425.0, 0.25)
    counts = flagged.groupby(["source_study", "cell_voltage_cap_tested_v"])[
        "per_cap_robust_pass"
    ].sum()
    assert counts.loc[("global_v53", 2.0)] == 92
    assert counts.loc[("global_v53", 5.0)] == 380
    assert counts.loc[("dense_local", 3.0)] == 187
    assert counts.loc[("dense_local", 5.0)] == 237

    v55 = flagged.loc[
        flagged["source_study"].eq("dense_local")
        & np.isclose(flagged["current_density_a_m2"], 50.0)
        & np.isclose(flagged["transport_number_reference_t_w"], 75.0)
        & np.isclose(flagged["water_diffusivity_scale_vs_pfsa"], 0.60)
    ].sort_values("cell_voltage_cap_tested_v")
    assert list(v55["per_cap_robust_pass"].astype(bool)) == [False, True]
    budget = mod.add_receiver_sec_budget(v55)
    assert math.isclose(
        budget.iloc[-1]["receiver_sec_budget_kwh_kg"], 0.113268806, rel_tol=1.0e-7
    )


def test_reuse_verifier_requires_explicit_live_hashes_and_detects_tampering(tmp_path):
    mod = module()
    provenance_names = [
        "script",
        "manifest",
        "v53_generator",
        "global_register",
        "dense_register",
        "global_assumptions_v53",
        "dense_assumptions_v53",
    ]
    paths: dict[str, Path] = {}
    provenance: dict[str, dict[str, object]] = {}
    for name in provenance_names:
        path = tmp_path / f"{name}.txt"
        path.write_text(f"stable {name}\n", encoding="utf-8")
        paths[name] = path
        provenance[name] = {
            "path": str(path.resolve()),
            "sha256": mod.sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
    output = tmp_path / "required.csv"
    output.write_text("value\n1\n", encoding="utf-8")
    parameters = {
        "process_activity_min": 0.17,
        "conditional_saving_min_kw": 425.0,
        "selected_cap_voltage_headroom_v": 0.25,
        "primary_cap_v": 5.0,
        "primary_current_density_a_m2": 50.0,
        "receiver_sec_values_kwh_kg": [0.0, 0.1],
    }
    audit = {
        "status": "PASS",
        "provenance": provenance,
        "effective_parameters": parameters,
        "policies": {
            "engineering_current_density_limit_a_m2": None,
            "system_energy_status": "UNKNOWN",
            "full_system_claim_allowed": False,
        },
        "required_outputs": [
            {
                "relative_path": output.name,
                "sha256": mod.sha256_file(output),
                "size_bytes": output.stat().st_size,
            }
        ],
    }
    audit_path = tmp_path / "audit.json"
    audit_path.write_text(json.dumps(audit), encoding="utf-8")

    kwargs = {
        "script_path": paths["script"],
        "manifest_path": paths["manifest"],
        "v53_generator_path": paths["v53_generator"],
        "global_register_path": paths["global_register"],
        "dense_register_path": paths["dense_register"],
        "global_assumptions_v53_path": paths["global_assumptions_v53"],
        "dense_assumptions_v53_path": paths["dense_assumptions_v53"],
        "process_activity_min": 0.17,
        "conditional_saving_min_kw": 425.0,
        "selected_cap_voltage_headroom_v": 0.25,
        "primary_cap_v": 5.0,
        "primary_current_density_a_m2": 50.0,
        "receiver_sec_values_kwh_kg": [0.0, 0.1],
        "required_output_names": [output.name],
    }
    assert mod.verify_audit_for_reuse(audit_path, **kwargs)["status"] == "PASS"

    output.write_text("value\n2\n", encoding="utf-8")
    verification = mod.verify_audit_for_reuse(audit_path, **kwargs)
    assert verification["status"] == "FAIL"
    assert any("required output hash mismatch" in issue for issue in verification["issues"])

    output.write_text("value\n1\n", encoding="utf-8")
    paths["global_register"].write_text("changed register\n", encoding="utf-8")
    verification = mod.verify_audit_for_reuse(audit_path, **kwargs)
    assert verification["status"] == "FAIL"
    assert any(
        "provenance hash mismatch: global_register" in issue
        for issue in verification["issues"]
    )

    paths["global_register"].write_text("stable global_register\n", encoding="utf-8")
    changed_thresholds = {**kwargs, "process_activity_min": 0.18}
    verification = mod.verify_audit_for_reuse(audit_path, **changed_thresholds)
    assert verification["status"] == "FAIL"
    assert "effective analysis parameters do not match" in verification["issues"]
