from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import sys

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "direct_eo_erv_study_v1.json"
RUNNER = ROOT / "scripts" / "run_direct_eo_erv_study_v1.py"


def load_runner():
    spec = importlib.util.spec_from_file_location(
        "_direct_eo_erv_runner_test", RUNNER
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def config() -> dict[str, object]:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def test_config_declares_shared_core_low_voltage_and_no_current_gate():
    runner = load_runner()
    cfg = runner.load_config(CONFIG)
    assert cfg["architecture"]["id"] == "shared_core_same_stream"
    assert cfg["architecture"]["same_exhaust_stream_used_once"] is True
    assert cfg["architecture"]["separate_receiver_loop"] is False
    assert cfg["electrical"]["maximum_terminal_voltage_v"] == 2.0
    assert cfg["electrical"]["preferred_terminal_voltage_v"] == 1.8
    assert cfg["electrical"]["engineering_current_density_limit_a_m2"] is None
    assert cfg["solver"]["area_is_acceptance_gate"] is False
    assert cfg["claim_boundary"]["full_system_claim_allowed"] is False
    assert runner.expected_case_count(cfg, "smoke") == 18
    assert runner.expected_case_count(cfg, "nafion_sensitivity") == 1260
    specs = runner.make_case_specs(cfg, "smoke")
    assert max(row["terminal_voltage_v"] for row in specs) <= 2.0
    nafion_specs = runner.make_case_specs(cfg, "nafion_sensitivity")
    assert min(row["terminal_voltage_v"] for row in nafion_specs) == 0.0005
    assert max(row["terminal_voltage_v"] for row in nafion_specs) == 0.06


def test_config_rejects_voltage_above_two_and_any_current_acceptance_gate(
    tmp_path: Path,
):
    runner = load_runner()
    cfg = config()
    cfg["modes"]["smoke"]["terminal_voltages_v"] = [2.01]
    path = tmp_path / "bad-voltage.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    with pytest.raises(ValueError, match="exceeds the terminal-voltage cap"):
        runner.load_config(path)

    cfg = config()
    cfg["electrical"]["engineering_current_density_limit_a_m2"] = 21.0
    path = tmp_path / "bad-current.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    with pytest.raises(ValueError, match="Current-density acceptance"):
        runner.load_config(path)

    cfg = config()
    cfg["solver"]["area_is_acceptance_gate"] = True
    path = tmp_path / "bad-area-gate.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    with pytest.raises(ValueError, match="area must remain a diagnostic"):
        runner.load_config(path)


@pytest.mark.parametrize(
    ("section", "field", "value", "message"),
    [
        ("architecture", "id", "two_loop", "Architecture id"),
        (
            "architecture",
            "receiver_regeneration_required",
            True,
            "Receiver regeneration",
        ),
        (
            "architecture",
            "external_receiver_mass_flow_kg_s",
            1.0,
            "External receiver flow",
        ),
        (
            "boundary",
            "available_exhaust_to_process_ratio",
            0.9,
            "balanced process and exhaust",
        ),
    ],
)
def test_config_rejects_architecture_contradictions(
    tmp_path: Path,
    section: str,
    field: str,
    value: object,
    message: str,
):
    runner = load_runner()
    cfg = config()
    cfg[section][field] = value
    path = tmp_path / f"bad-{field}.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        runner.load_config(path)


def test_two_case_materialized_smoke_audits_and_fails_decisions_closed(
    tmp_path: Path,
):
    runner = load_runner()
    cfg = config()
    cfg["modes"]["smoke"] = {
        "material_ids": ["terminal1_anchor"],
        "process_outlet_w_g_kg_da": [10.0, 7.26028059345441],
        "terminal_voltages_v": [0.01],
        "segment_counts": [4],
        "sensible_effectiveness_values": [0.75],
        "film_scale_factors": [1.0],
        "electric_heat_scenario_ids": ["external_rejection"],
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(cfg), encoding="utf-8")
    output = tmp_path / "study"
    audit = runner.run(config_path, output, "smoke", overwrite=False)
    assert audit["status"] == "PASS"
    assert all(check["passed"] for check in audit["checks"])
    cases = pd.read_csv(output / "smoke" / "case_register.csv")
    assert len(cases) == 2
    assert not cases["current_density_gate_applied"].astype(bool).any()
    assert not cases["area_acceptance_gate_applied"].astype(bool).any()
    assert cases["engineering_current_density_limit_a_m2"].isna().all()
    assert cases["same_exhaust_stream_used_once"].astype(bool).all()
    assert cases["shared_stream_water_identity_error_kg_s"].abs().max() < 1.0e-12
    assert (cases["effective_fixed_loss_voltage_v"] == 0.0).all()
    assert (cases["effective_series_asr_ohm_m2"] == 1.0e-5).all()
    contract = json.loads(
        (output / "smoke" / "run_contract.json").read_text(encoding="utf-8")
    )
    assert contract["audit_scope"] == (
        "integrity_and_reproducibility_not_design_acceptance"
    )
    assert cases["target_transport_closed"].astype(bool).all()
    assert (~cases["within_area_observation_cap"].astype(bool)).any()
    assert cases["conditional_active_total_power_kw"].notna().all()
    assert not cases["full_coupled_gate_pass"].astype(bool).any()
    assert (output / "smoke" / "figures" / "01_axial_gradient_anchor.png").is_file()


def test_surface_gate_includes_segment_boundaries(tmp_path: Path):
    """A midpoint-only check falsely promoted this near-threshold Nafion case."""

    runner = load_runner()
    cfg = config()
    cfg["modes"]["smoke"] = {
        "material_ids": ["nafion_nr211_nominal_reference"],
        "process_outlet_w_g_kg_da": [13.214990502676377],
        "terminal_voltages_v": [0.01],
        "segment_counts": [8],
        "sensible_effectiveness_values": [0.75],
        "film_scale_factors": [1.0],
        "electric_heat_scenario_ids": ["external_rejection"],
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(cfg), encoding="utf-8")
    output = tmp_path / "boundary-gate"
    audit = runner.run(config_path, output, "smoke", overwrite=False)
    assert audit["status"] == "PASS"
    row = pd.read_csv(output / "smoke" / "case_register.csv").iloc[0]
    assert bool(row["surface_diagnostic_complete"])
    assert row["minimum_midpoint_surface_activity_margin"] > 0.02
    assert row["minimum_surface_activity_margin"] == pytest.approx(
        0.01965123, abs=2.0e-8
    )
    assert row["maximum_local_current_density_a_m2"] > 21.0
    assert not bool(row["current_density_gate_applied"])
    assert bool(row["terminal_voltage_solution_pass"])
    assert row["maximum_absolute_terminal_voltage_error_v"] <= 2.0e-6
    assert not bool(row["robust_surface_direction"])
    assert bool(row["thermodynamic_consistency_pass"])
    assert bool(row["robust_physics_pass"])
    assert bool(row["passive_gradient_assistance_pass"])
    assert not bool(row["robust_passive_gradient_assistance_pass"])


def test_area_observation_cap_does_not_close_transport_gate(tmp_path: Path):
    runner = load_runner()
    cfg = config()
    cfg["solver"]["area_observation_cap_m2"] = 1.0
    cfg["modes"]["smoke"] = {
        "material_ids": ["terminal1_anchor"],
        "process_outlet_w_g_kg_da": [10.0],
        "terminal_voltages_v": [0.01],
        "segment_counts": [4],
        "sensible_effectiveness_values": [0.75],
        "film_scale_factors": [1.0],
        "electric_heat_scenario_ids": ["external_rejection"],
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(cfg), encoding="utf-8")
    output = tmp_path / "area-diagnostic"
    audit = runner.run(config_path, output, "smoke", overwrite=False)
    assert audit["status"] == "PASS"
    row = pd.read_csv(output / "smoke" / "case_register.csv").iloc[0]
    assert row["required_active_area_m2"] > 1.0
    assert not bool(row["within_area_observation_cap"])
    assert not bool(row["area_acceptance_gate_applied"])
    assert bool(row["target_transport_closed"])


def test_engineering_gate_fails_closed_when_segment_decision_does_not_converge():
    runner = load_runner()
    cases = pd.DataFrame(
        {
            "case_id": ["coarse", "refined"],
            "engineering_screen_pass": [True, True],
            "status": ["engineering_screen_pass_not_full_coupled"] * 2,
        }
    )
    convergence = pd.DataFrame(
        {
            "coarse_case_id": ["coarse"],
            "refined_case_id": ["refined"],
            "transport_convergence_pass": [True],
            "decision_convergence_pass": [False],
        }
    )
    gated = runner.attach_segment_convergence(cases, convergence)
    assert gated["segment_convergence_evaluated"].astype(bool).all()
    assert not gated["segment_convergence_gate_pass"].astype(bool).any()
    assert not gated["engineering_screen_pass"].astype(bool).any()
    assert gated["status"].eq(
        "engineering_screen_failed_segment_convergence"
    ).all()


def test_engineering_gate_fails_closed_when_convergence_is_not_evaluated():
    runner = load_runner()
    cases = pd.DataFrame(
        {
            "case_id": ["single-grid"],
            "engineering_screen_pass": [True],
            "status": ["engineering_screen_pass_not_full_coupled"],
        }
    )
    gated = runner.attach_segment_convergence(cases, pd.DataFrame())
    assert not bool(gated.iloc[0]["segment_convergence_evaluated"])
    assert not bool(gated.iloc[0]["segment_convergence_gate_pass"])
    assert not bool(gated.iloc[0]["engineering_screen_pass"])
    assert gated.iloc[0]["status"] == (
        "engineering_screen_not_evaluated_without_segment_convergence"
    )


def test_selected_diagnostic_prefers_refined_member_of_converged_pair():
    runner = load_runner()
    common = {
        "process_outlet_w_g_kg_da": 9.5,
        "engineering_screen_pass": False,
        "robust_physics_pass": True,
        "physics_screen_pass": True,
        "segment_convergence_gate_pass": True,
        "segment_convergence_evaluated": True,
        "target_transport_closed": True,
        "minimum_surface_activity_margin": 0.021,
        "required_active_area_m2": 10_000.0,
    }
    frame = pd.DataFrame(
        [
            {
                **common,
                "case_id": "coarse",
                "segment_count": 4,
                "conditional_saving_kw_vs_passive_erv": 100.01,
            },
            {
                **common,
                "case_id": "refined",
                "segment_count": 8,
                "conditional_saving_kw_vs_passive_erv": 100.00,
            },
        ]
    )
    selected = runner.select_cases(frame)
    assert selected.iloc[0]["case_id"] == "refined"
