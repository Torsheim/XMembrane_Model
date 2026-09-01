from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "make_post_erv_full_eo_study_v1.py"
CONFIG = ROOT / "config" / "post_erv_full_eo_study_v1.json"
V2_ROOT = ROOT.parent / "HeiQ_V2"
RUNTIME_AVAILABLE = (
    V2_ROOT
    / "outputs"
    / "active_eo_erv_terminal1_v2_study"
    / "active_eo_erv_manifest.json"
).is_file()


def load_script():
    name = "_post_erv_full_eo_study_test"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_manifest_declares_full_remaining_target_and_fail_closed_claim_policy():
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    targets = {row["target_id"]: row for row in config["targets"]}

    assert targets["o50_reference"]["run_transport"] is False
    assert targets["full_remaining_latent"]["run_transport"] is True
    assert targets["full_remaining_latent"]["humidity_ratio_kg_kg_da"] == pytest.approx(
        0.00726028059345441
    )
    assert config["claim_policy"]["full_system_claim_allowed"] is False
    assert "sampling coordinate" in config["transport_sweep"]["current_density_policy"]
    assert "not rankable" in config["transport_sweep"][
        "receiver_capacity_axis_interpretation"
    ]
    assert min(config["transport_sweep"]["uniform_current_density_a_m2"]) <= 1.0
    assert config["transport_sweep"]["maximum_receiver_surface_activity"] == 0.99
    assert config["transport_sweep"]["terminal_voltage_cap_sensitivity_v"] == [
        1.0,
        2.0,
        3.0,
        5.0,
    ]
    assert config["transport_sweep"]["receiver_capacity_sweep_target_ids"] == [
        "full_remaining_latent"
    ]
    assert config["transport_sweep"]["available_post_erv_exhaust_to_process_ratio"] == 1.0


def test_output_directory_requires_explicit_overwrite(tmp_path):
    module = load_script()
    output = tmp_path / "existing"
    output.mkdir()
    (output / "owned.txt").write_text("preserve", encoding="utf-8")

    with pytest.raises(module.StudyError, match="--overwrite"):
        module.validate_output_directory(output, overwrite=False)

    module.validate_output_directory(output, overwrite=True)
    assert (output / "owned.txt").read_text(encoding="utf-8") == "preserve"


def test_energy_only_run_rejects_stale_transport_artifacts(tmp_path):
    module = load_script()
    output = tmp_path / "mixed-mode-output"
    output.mkdir()
    (output / "transport_cases.csv").write_text("case_id\nold\n", encoding="utf-8")

    with pytest.raises(module.StudyError, match="separate --output-dir"):
        module.validate_output_mode(output, energy_only=True)
    module.validate_output_mode(output, energy_only=False)


@pytest.fixture(scope="module")
def loaded_runtime():
    if not RUNTIME_AVAILABLE:
        pytest.skip("Audited HeiQ_V2 post-ERV runtime is not present")
    module = load_script()
    config = module.read_json(CONFIG)
    analyzer, runtime, _, source_config_path, analyzer_path = module.load_runtime(
        config,
        v2_root=V2_ROOT,
        area_step_m2=5.0,
    )
    return module, analyzer, runtime, config, source_config_path, analyzer_path


def test_energy_window_distinguishes_exact_and_near_endpoint_control_regimes(
    loaded_runtime,
):
    module, _, runtime, config, _, _ = loaded_runtime
    targets = module.target_table(config, float(runtime["process_in"].w))
    energy, break_even = module.build_energy_window(runtime, targets, config)
    endpoint = module.build_endpoint_control_audit(runtime, config)

    full = break_even[
        break_even["target_id"].eq("full_remaining_latent")
        & (break_even["process_heat_leak_fraction"] == 0.0)
    ].iloc[0]
    assert full["eo_water_removal_kg_h"] == pytest.approx(1689.5014518920134)
    assert full["break_even_all_in_eo_sec_kwh_per_kg"] == pytest.approx(
        0.2751956966376383, rel=1.0e-9
    )

    exact = endpoint.iloc[0]
    near = endpoint.iloc[1]
    assert exact["remaining_ac_is_sensible_only"]
    assert exact["remaining_ac_water_removal_kg_h"] == pytest.approx(0.0, abs=1.0e-12)
    assert not near["remaining_ac_is_sensible_only"]
    assert near["break_even_all_in_eo_sec_kwh_per_kg"] == pytest.approx(
        0.15670080744075676, rel=1.0e-9
    )
    assert energy["energy_identity_error_kw"].abs().max() <= 1.0e-8
    assert not energy["full_system_claim_allowed"].any()


def test_transport_design_is_exact_and_rejects_target_tampering(loaded_runtime):
    module, _, _, config, _, _ = loaded_runtime
    targets = module.target_table(config, 0.013214990502676377)
    design = module.build_transport_case_design(targets, config, smoke=False)

    assert len(design) == 480
    assert design["case_id"].nunique() == 480
    assert set(design["target_id"]) == {
        "post_erv_10pct",
        "o30",
        "full_remaining_latent",
    }
    module.validate_transport_frame_design(design.copy(), design)

    tampered = design.copy()
    tampered.loc[tampered.index[0], "target_w_g_kg_da"] += 1.0
    with pytest.raises(module.StudyError, match="target_w_g_kg_da"):
        module.validate_transport_frame_design(tampered, design)


def test_transport_contract_rejects_csv_tampering(tmp_path, loaded_runtime):
    module, _, runtime, config, source_config_path, analyzer_path = loaded_runtime
    targets = module.target_table(config, float(runtime["process_in"].w))
    design = module.build_transport_case_design(targets, config, smoke=False)
    transport_path = tmp_path / "transport_cases.csv"
    contract_path = tmp_path / "transport_contract.json"
    transport_path.write_text("case_id\nplaceholder\n", encoding="utf-8")
    contract = module.build_transport_contract(
        runtime,
        config,
        design,
        transport_path,
        config_path=CONFIG,
        source_config_path=source_config_path,
        analyzer_path=analyzer_path,
        mode="study",
    )
    module.write_json(contract_path, contract)
    module.validate_transport_contract(
        contract_path,
        runtime,
        config,
        design,
        transport_path,
        config_path=CONFIG,
        source_config_path=source_config_path,
        analyzer_path=analyzer_path,
        mode="study",
    )

    transport_path.write_text("case_id\ntampered\n", encoding="utf-8")
    with pytest.raises(module.StudyError, match="transport_csv.sha256"):
        module.validate_transport_contract(
            contract_path,
            runtime,
            config,
            design,
            transport_path,
            config_path=CONFIG,
            source_config_path=source_config_path,
            analyzer_path=analyzer_path,
            mode="study",
        )


def test_full_latent_transport_anchor_and_receiver_capacity_balance(loaded_runtime):
    module, analyzer, runtime, _, _, _ = loaded_runtime
    supply_w = float(runtime["baseline"].remaining_ac.supply.w)
    runtime = dict(runtime)
    runtime["target_w"] = supply_w
    runtime["area_limit_m2"] = 40000.0
    runtime["area_step_m2"] = 5.0

    case = analyzer.base_case_material(runtime["anchor"])
    case.update(
        {
            "study_family": "test",
            "case_id": "full-latent-D1e-10-j10-R1",
            "water_diffusivity_m2_s": 1.0e-10,
            "uniform_current_density_a_m2": 10.0,
            "receiver_to_process_dry_air_ratio": 1.0,
        }
    )
    result = analyzer.integrate_case(runtime, case)

    assert result["target_reached"]
    assert result["required_active_area_m2"] == pytest.approx(8254.193819, rel=2.0e-7)
    assert result["incremental_water_removal_target_kg_h"] == pytest.approx(
        1689.5014518920134
    )
    assert result["remaining_ac_power_kw"] == pytest.approx(44.43781075297754)
    assert result["water_balance_relative_error"] == pytest.approx(0.0, abs=1.0e-10)
    assert result["receiver_water_balance_relative_error"] == pytest.approx(
        0.0, abs=1.0e-10
    )
    assert result["incremental_saving_kw_vs_passive_erv"] == pytest.approx(
        result["incremental_ac_power_reduction_kw"]
        - result["incremental_eo_and_fan_power_kw"],
        abs=1.0e-8,
    )
    assert result["minimum_surface_activity_margin"] < 0.0
    assert result["full_system_status"] == "UNKNOWN"
    assert result["full_system_claim_allowed"] is False

    capacity_case = dict(case)
    capacity_case.update(
        {
            "case_id": "full-latent-anchor-j5-R3",
            "water_diffusivity_m2_s": float(runtime["anchor"]["water_diffusivity_m2_s"]),
            "uniform_current_density_a_m2": 5.0,
            "receiver_to_process_dry_air_ratio": 3.0,
        }
    )
    capacity = analyzer.integrate_case(runtime, capacity_case)
    assert capacity["target_reached"]
    assert capacity["receiver_to_process_dry_air_ratio"] == pytest.approx(3.0)
    assert capacity["receiver_water_balance_relative_error"] == pytest.approx(
        0.0, abs=1.0e-10
    )
    assert capacity["minimum_surface_activity_margin"] < 0.0


def test_audit_fails_closed_for_energy_only_runtime(loaded_runtime):
    module, _, runtime, config, source_config_path, analyzer_path = loaded_runtime
    targets = module.target_table(config, float(runtime["process_in"].w))
    energy, break_even = module.build_energy_window(runtime, targets, config)
    endpoint = module.build_endpoint_control_audit(runtime, config)
    audit = module.build_audit(
        runtime,
        config,
        targets,
        energy,
        break_even,
        module.pd.DataFrame(),
        endpoint,
        module.pd.DataFrame(),
        True,
        config_path=CONFIG,
        source_config_path=source_config_path,
        analyzer_path=analyzer_path,
        mode="energy_only",
    )
    assert audit["pass"] is True
    assert audit["reference_checks"]["endpoint_control_regime_switch_exposed"] is True
    assert audit["engineering_current_density_limit_a_m2"] is None
    assert audit["full_system_claim_allowed"] is False
    assert audit["transport_contract_required"] is False
    assert audit["transport_contract_validated"] is False
    assert audit["provenance"]["study_script"]["path"] == str(SCRIPT.resolve())
    assert audit["provenance"]["study_script"]["sha256"] == module.sha256_file(SCRIPT)
