from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "direct_eo_low_voltage_study_v1.json"
ANALYZER = ROOT / "scripts" / "analyze_direct_eo_low_voltage_study_v1.py"
RUNNER = ROOT / "scripts" / "run_direct_eo_low_voltage_study_v1.py"
CANONICAL_OUTPUT = ROOT / "outputs" / "direct_eo_low_voltage_study_v1"
CANDIDATE_OUTPUT = (
    ROOT / "outputs" / "direct_eo_low_voltage_study_v1_candidate_20260826"
)


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def config() -> dict[str, object]:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def base_physical_row(cap: float = 2.0) -> dict[str, object]:
    return {
        "current_density_a_m2": 30.0,
        "transport_number_reference_t_w": 35.0,
        "water_diffusivity_scale_vs_pfsa": 0.1,
        "dry_thickness_um": 20.0,
        "ionic_area_resistance_ohm_m2_at_lambda_ref": 5e-6,
        "retention_factor_vs_pfsa_sorption": 1.25,
        "receiver_control_activity": 0.8,
        "cell_voltage_cap_tested_v": cap,
        "active_area_m2": 3000.0,
        "baseline_hvac_kw": 1166.0,
        "cell_voltage_required_max_v": 1.70,
        "cell_voltage_required_mean_v": 1.50,
        "conditional_known_electric_saving_kw": 500.0,
        "eo_grid_power_kw": 200.0,
        "hard_area_cap_pass": True,
        "known_electric_total_kw": 666.0,
        "process_surface_activity_min": 0.18,
        "receiver_sink_energy_kw_assumed": 0.0,
        "receiver_sink_net_kg_h": 4473.6,
        "selected_voltage_cap_pass": cap >= 1.70,
        "strict_physical_and_architecture_pass": True,
        "voltage_electrode_overpotential_v": 0.4,
        "voltage_interface_v": 0.45,
        "voltage_membrane_ohmic_max_v": 0.02,
        "voltage_series_ohmic_v": 0.0015,
        "voltage_water_activity_reversible_max_v": 0.4285,
    }


def test_config_is_exact_expanded_low_voltage_grid_without_current_gate():
    cfg = config()
    analyzer = load_module(ANALYZER, "_low_voltage_analyzer_config_test")
    analyzer.validate_config(cfg)
    physical, cap_rows = analyzer.expected_grid_counts(cfg)
    assert physical == 19 * 11 * 12
    assert cap_rows == physical * 5
    assert max(cfg["grid"]["cell_voltage_caps_v"]) == 2.0
    assert min(cfg["grid"]["current_density_a_m2"]) == 5.0
    assert max(cfg["grid"]["transport_number_reference_t_w"]) == 200.0
    assert 120.0 in cfg["grid"]["transport_number_reference_t_w"]
    assert cfg["gates"]["engineering_current_density_limit_a_m2"] is None
    assert cfg["claim_boundary"]["full_system_claim_allowed"] is False


def test_generator_command_uses_internal_ceiling_but_only_low_acceptance_caps(tmp_path):
    cfg = config()
    runner = load_module(RUNNER, "_low_voltage_runner_command_test")
    command = runner.generator_command(cfg, tmp_path / "physics", smoke=False)
    ceiling = command[command.index("--screening-voltage-cap-v") + 1]
    assert float(ceiling) == 12.0
    start = command.index("--cell-voltage-caps-v") + 1
    end = command.index("--operating-current-densities-a-m2")
    caps = list(map(float, command[start:end]))
    assert caps == [1.0, 1.25, 1.5, 1.75, 2.0]
    assert max(caps) <= 2.0
    assert "--maximum-current-density-a-m2" not in command


def test_modern_and_native_ledgers_are_separate_and_receiver_identity_is_exact():
    cfg = config()
    analyzer = load_module(ANALYZER, "_low_voltage_analyzer_ledger_test")
    frame = pd.DataFrame([base_physical_row()])
    augmented = analyzer.augment_cap_register(
        frame, cfg, cfg["energy_ledgers"]["modern_ac_erv_reference_kw"]
    )
    row = augmented.iloc[0]
    assert row["native_historical_no_erv_margin_kw"] == 500.0
    assert math.isclose(
        row["modern_comparator_margin_before_receiver_kw"],
        543.7405641877893 - 666.0,
    )
    assert bool(row["membrane_operating_pass_at_cap"])
    assert bool(row["native_historical_425_diagnostic_pass"])
    assert not bool(row["modern_comparator_positive_before_receiver_pass"])

    receiver, counts = analyzer.receiver_scenarios(augmented, [0.0, 0.1])
    sec = receiver[np.isclose(receiver["receiver_sec_kwh_kg"], 0.1)].iloc[0]
    assert math.isclose(sec["receiver_power_kw"], 447.36)
    assert math.isclose(
        sec["modern_comparator_margin_after_receiver_kw"],
        sec["modern_comparator_margin_before_receiver_kw"] - 447.36,
    )
    assert counts["modern_positive_after_receiver_coordinates"].sum() == 0


def test_fixed_loss_scenario_reproduces_baseline_and_does_not_change_transport():
    cfg = config()
    analyzer = load_module(ANALYZER, "_low_voltage_analyzer_fixed_test")
    cap = analyzer.augment_cap_register(
        pd.DataFrame([base_physical_row()]),
        cfg,
        cfg["energy_ledgers"]["modern_ac_erv_reference_kw"],
    )
    physical = analyzer.deduplicate_physical(cap)
    scenarios, counts = analyzer.fixed_loss_scenarios(
        physical, cfg, cfg["energy_ledgers"]["modern_ac_erv_reference_kw"]
    )
    baseline = scenarios[np.isclose(scenarios["combined_fixed_loss_scenario_v"], 0.85)].iloc[0]
    low_loss = scenarios[np.isclose(scenarios["combined_fixed_loss_scenario_v"], 0.2)].iloc[0]
    assert math.isclose(baseline["scenario_required_max_voltage_v"], 1.70)
    assert math.isclose(low_loss["scenario_required_max_voltage_v"], 1.05)
    for column in (
        "active_area_m2",
        "process_surface_activity_min",
        "receiver_sink_net_kg_h",
        "water_diffusivity_scale_vs_pfsa",
    ):
        assert scenarios[column].nunique() == 1
    assert set(counts["combined_fixed_loss_scenario_v"]) == {0.2, 0.4, 0.6, 0.85, 1.0}


@pytest.mark.parametrize(
    "output",
    [CANONICAL_OUTPUT, CANDIDATE_OUTPUT],
    ids=["canonical", "candidate"],
)
def test_full_materialized_outputs_audit_hashes_and_semantics(output: Path):
    if not (output / "study_audit.json").is_file():
        pytest.skip(f"Full low-voltage output has not been materialized: {output}")
    study = json.loads((output / "study_audit.json").read_text(encoding="utf-8"))
    analysis = json.loads(
        (output / "analysis" / "analysis_audit.json").read_text(encoding="utf-8")
    )
    assert study["status"] == "PASS"
    assert analysis["status"] == "PASS"
    assert analysis["grid_audit"]["observed_physical_coordinates"] == 2508
    assert analysis["grid_audit"]["observed_cap_rows"] == 12540
    assert all(check["passed"] for check in analysis["checks"])
    assert analysis["claim_boundary"]["full_system_claim_allowed"] is False
    assert analysis["claim_boundary"]["native_historical_margin_is_system_saving"] is False

    frame = pd.read_csv(output / "analysis" / "low_voltage_cap_register.csv")
    assert frame["cell_voltage_cap_tested_v"].max() == 2.0
    assert frame["current_density_a_m2"].min() == 5.0
    assert frame["transport_number_reference_t_w"].max() == 200.0
    assert not frame.loc[
        frame["transport_number_reference_t_w"] > 100,
        "membrane_operating_pass_at_cap",
    ].astype(bool).any()
