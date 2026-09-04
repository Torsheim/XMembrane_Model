from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_system_energy_closure_study.py"


def module():
    spec = importlib.util.spec_from_file_location("_system_energy_closure_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    import sys
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_break_even_180_wh_l_arithmetic():
    mod = module()
    frame = mod.break_even_register(
        baseline_compressor_kw=1167.33,
        o30_compressor_kw=382.44,
        water_load_kg_h=4365.92,
        core_power_kw=115.08,
    )
    gross = frame.iloc[0]
    assert math.isclose(
        float(gross["break_even_sec_kwh_kg"]),
        784.89 / 4365.92,
        rel_tol=1e-12,
    )
    assert 179.0 < float(gross["break_even_wh_l_approx"]) < 181.0


def test_active_default_engineering_gates_do_not_include_current(monkeypatch):
    mod = module()
    monkeypatch.setattr(sys, "argv", [str(SCRIPT)])
    args = mod.parse_args()
    assert args.voltage_cap_v == 1.0
    assert args.current_cap_a_m2 is None
    assert args.area_cap_m2 == 9000.0


def test_golden_o30_reference_is_not_rejected_on_current_density():
    mod = module()
    row = mod.select_reference_row(
        ROOT / "data" / "golden" / "o30" / "overall_best.csv",
        target="O30",
        current_cap_a_m2=None,
        area_cap_m2=9000.0,
        voltage_cap_v=1.0,
    )
    assert row["reference_selection_status"] == "selected_all_gates_reference"
    assert bool(row["reference_gate_pass"])
    assert bool(row["reference_current_gate_pass"])
    assert not bool(row["reference_current_gate_applied"])
    assert bool(row["reference_current_density_diagnostic_available"])
    assert bool(row["reference_area_gate_pass"])
    assert bool(row["reference_voltage_gate_pass"])
    assert int(row["reference_gate_failure_count"]) == 0
    assert str(row["reference_gate_violations"]) == ""


def test_explicit_current_sensitivity_gate_can_still_be_requested():
    mod = module()
    row = mod.select_reference_row(
        ROOT / "data" / "golden" / "o30" / "overall_best.csv",
        target="O30",
        current_cap_a_m2=21.0,
        area_cap_m2=9000.0,
        voltage_cap_v=1.0,
    )
    assert not bool(row["reference_gate_pass"])
    assert bool(row["reference_current_gate_applied"])
    assert not bool(row["reference_current_gate_pass"])
    assert "21.223" in str(row["reference_gate_violations"])


def test_reference_selection_prefers_valid_row_over_cheaper_invalid_row(tmp_path):
    mod = module()
    frame = pd.DataFrame(
        [
            {
                "target": "O30",
                "analysis_pass": True,
                "target_reached": True,
                "water_balance_pass": True,
                "stack_feasible": True,
                "maximum_local_current_density_a_m2": 21.1,
                "required_active_area_m2": 8000.0,
                "terminal_voltage_v": 0.9,
                "analysis_core_power_kw": 10.0,
            },
            {
                "target": "O30",
                "analysis_pass": True,
                "target_reached": True,
                "water_balance_pass": True,
                "stack_feasible": True,
                "maximum_local_current_density_a_m2": 20.0,
                "required_active_area_m2": 8500.0,
                "terminal_voltage_v": 1.0,
                "analysis_core_power_kw": 12.0,
            },
        ]
    )
    path = tmp_path / "candidates.csv"
    frame.to_csv(path, index=False)
    selected = mod.select_reference_row(
        path,
        target="O30",
        current_cap_a_m2=21.0,
        area_cap_m2=9000.0,
        voltage_cap_v=1.0,
    )
    assert bool(selected["reference_gate_pass"])
    assert selected["reference_selection_status"] == "selected_all_gates_reference"
    assert float(selected["analysis_core_power_kw"]) == 12.0


def test_invalid_reference_does_not_fall_back_to_historical_power_values():
    mod = module()
    gas_row = mod.select_reference_row(
        ROOT / "data" / "golden" / "o30" / "overall_best.csv",
        target="O30",
        current_cap_a_m2=21.0,
        area_cap_m2=9000.0,
        voltage_cap_v=1.0,
    )
    sec = mod.eo_sec_options(
        gas_row=gas_row,
        liquid_table=None,
        water_load_kg_h=4365.92,
    )
    assert sec["sec_kwh_kg"].isna().all()
    assert set(sec["calculation_status"]) == {
        "not_available_no_all_gates_reference"
    }

    class Args:
        o30_water_load_kg_h = 4365.92
        controls_power_kw = 1.0
        grid_to_device_efficiency = 0.98

    ledger = mod.power_ledger(
        gas_row=gas_row,
        break_even=pd.DataFrame(),
        liquid_upper=pd.DataFrame(),
        args=Args(),
    )
    gas = ledger.iloc[0]
    assert not bool(gas["system_claim_available"])
    assert math.isnan(float(gas["eo_grid_kw"]))
    assert math.isnan(float(gas["site_total_kw"]))
    assert math.isnan(float(gas["sec_kwh_kg"]))


def test_valid_reference_with_missing_power_has_distinct_audit_status():
    mod = module()

    class Args:
        target = "O30"
        o30_water_load_kg_h = 100.0
        controls_power_kw = 1.0
        grid_to_device_efficiency = 0.98

    gas_row = {
        "target": "O30",
        "reference_gate_pass": True,
        "reference_gate_violations": "",
        "eo_grid_power_kw": 5.0,
        "process_channel_fan_power_kw": 1.0,
    }
    ledger = mod.power_ledger(
        gas_row=gas_row,
        break_even=pd.DataFrame(),
        liquid_upper=pd.DataFrame(),
        args=Args(),
    )
    gas = ledger.iloc[0]
    assert bool(gas["reference_gate_pass"])
    assert not bool(gas["system_claim_available"])
    assert gas["calculation_status"] == "not_available_missing_power_components"
    assert "receiver_fan_kw" in str(gas["unresolved_power_terms"])
    assert gas["reference_gate_violations"] == ""


def test_missing_direct_liquid_source_writes_schema_valid_status_row(tmp_path):
    mod = module()
    frame = mod.direct_liquid_output_summary(None)
    path = tmp_path / "liquid_summary.csv"
    frame.to_csv(path, index=False)
    reloaded = pd.read_csv(path)
    assert len(reloaded) == 1
    assert reloaded.loc[0, "status"] == "not_available_no_source_table"


def test_direct_liquid_summary_fails_closed_without_gate_column(tmp_path):
    mod = module()
    path = tmp_path / "ungated_liquid.csv"
    pd.DataFrame(
        [
            {
                "target": "O30",
                "liquid_activity": 0.6,
                "predryer_core_power_kw": 5.0,
            }
        ]
    ).to_csv(path, index=False)
    summary = mod.direct_liquid_output_summary(path)
    assert not bool(summary.loc[0, "any_passing_case"])
    assert summary.loc[0, "status"] == "not_available_no_passing_case"


def test_complete_system_ledger_excludes_water_infeasible_incremental_rows():
    mod = module()

    class Args:
        baseline_compressor_kw = 100.0
        o30_compressor_kw = 50.0
        grid_to_device_efficiency = 1.0

    erv = pd.DataFrame(
        [
            {
                "technology": "energy_wheel",
                "rating_point": "mid",
                "site_power_kw": 60.0,
                "compressor_power_kw": 55.0,
                "erv_fan_power_kw": 5.0,
                "grid_conversion_loss_kw": 0.0,
            }
        ]
    )
    incremental = pd.DataFrame(
        [
            {
                "technology": "energy_wheel",
                "erv_rating_point": "mid",
                "eo_boundary": "feasible_core",
                "reduction_definition": "10pct_post_erv",
                "required_additional_water_transport_kg_h": 5.0,
                "feasible_by_available_water": True,
                "gross_compressor_site_reduction_kw": 8.0,
                "additional_eo_site_power_kw": 2.0,
            },
            {
                "technology": "energy_wheel",
                "erv_rating_point": "mid",
                "eo_boundary": "infeasible_core",
                "reduction_definition": "10pct_post_erv",
                "required_additional_water_transport_kg_h": 50.0,
                "feasible_by_available_water": False,
                "gross_compressor_site_reduction_kw": 80.0,
                "additional_eo_site_power_kw": 20.0,
            },
        ]
    )
    ledger = mod.complete_system_power_ledger(
        erv=erv,
        incremental=incremental,
        predryer_ledger=pd.DataFrame(),
        args=Args(),
    )
    hybrid = ledger[ledger["system"].eq("ERV_plus_incremental_EO")]
    assert len(hybrid) == 1
    assert "feasible_core" in str(hybrid.iloc[0]["rating_point"])
    assert "infeasible_core" not in " ".join(hybrid["rating_point"].astype(str))


def test_smoke_workflow_does_not_apply_current_density_gate(
    tmp_path,
    monkeypatch,
):
    mod = module()
    output = tmp_path / "closure"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT),
            "--source-root",
            str(ROOT),
            "--output-dir",
            str(output),
            "--smoke",
        ],
    )
    assert mod.main() == 0

    selected = pd.read_csv(output / "selected_reference_case.csv").iloc[0]
    assert bool(selected["reference_gate_pass"])
    assert bool(selected["reference_current_gate_pass"])
    assert not bool(selected["reference_current_gate_applied"])

    incremental = pd.read_csv(output / "erv_plus_eo_10pct.csv")
    assert not incremental.empty
    assert "required_additional_water_transport_kg_h" in incremental

    core_ledger = pd.read_csv(output / "power_ledger.csv")
    core = core_ledger[
        core_ledger["scenario"].eq("gas_receiver_o30_core")
    ].iloc[0]
    assert bool(core["core_result_available"])
    assert not bool(core["system_power_ledger_complete"])

    complete = pd.read_csv(output / "complete_system_power_ledger.csv")
    gas = complete[
        complete["technology"].eq("gas_receiver_o30_core")
    ].iloc[0]
    assert not bool(gas["system_claim_available"])
    assert math.isnan(float(gas["total_site_kw"]))
    assert math.isnan(float(gas["saving_vs_no_erv_pct"]))

    available_systems = complete[complete["system_claim_available"]]
    for _, row in available_systems.iterrows():
        component_sum = sum(
            float(row[name])
            for name in (
                "compressor_site_kw",
                "erv_fan_site_kw",
                "eo_predryer_site_kw",
                "other_site_kw",
            )
        )
        assert math.isclose(component_sum, float(row["total_site_kw"]), rel_tol=1e-12)

    foms = pd.read_csv(output / "all_requested_foms.csv")
    saving = foms[foms["fom_id"].eq("FOM-14")].iloc[0]
    assert saving["status"] == "not_available"
    assert math.isnan(float(saving["numeric_value"]))

    liquid_summary = pd.read_csv(
        output / "liquid_existing_output_summary.csv"
    )
    assert liquid_summary.loc[0, "status"] == "not_available_no_source_table"


def test_o50_smoke_uses_o50_reference_table(tmp_path, monkeypatch):
    mod = module()
    output = tmp_path / "closure_o50"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT),
            "--source-root",
            str(ROOT),
            "--output-dir",
            str(output),
            "--target",
            "O50",
            "--smoke",
        ],
    )
    assert mod.main() == 0
    selected = pd.read_csv(output / "selected_reference_case.csv").iloc[0]
    assert selected["target"] == "O50"
    assert str(selected["reference_source_path"]).endswith(
        "data/golden/o50/best_by_drag.csv"
    )
    assert int(selected["reference_gate_failure_count"]) == 1
    assert "stack_feasible" in str(selected["reference_gate_violations"])


def test_empty_screens_overwrite_stale_liquid_and_geometry_plots(tmp_path):
    mod = module()
    figures = tmp_path / "figures"
    figures.mkdir()
    liquid_path = figures / "liquid_receiver_bottlenecks.png"
    geometry_path = figures / "geometry_pareto.png"
    liquid_path.write_bytes(b"stale")
    geometry_path.write_bytes(b"stale")

    mod.make_plots(
        out=tmp_path,
        erv=pd.DataFrame(
            [
                {
                    "technology": "test",
                    "latent_effectiveness": 0.5,
                    "saving_pct_of_baseline": 10.0,
                }
            ]
        ),
        incremental=pd.DataFrame(),
        diffusivity=pd.DataFrame(
            [
                {
                    "water_diffusivity_m2_s": 1.0e-10,
                    "absolute_diffusion_to_eo_ratio": 1.0,
                }
            ]
        ),
        liquid_upper=pd.DataFrame(),
        geometry=pd.DataFrame(),
    )
    assert liquid_path.read_bytes().startswith(b"\x89PNG")
    assert geometry_path.read_bytes().startswith(b"\x89PNG")


def test_erv_envelopes_are_ordered():
    mod = module()
    for envelope in mod.ERV_ENVELOPES.values():
        assert envelope["sensible_effectiveness"][0] <= envelope["sensible_effectiveness"][1]
        assert envelope["latent_effectiveness"][0] <= envelope["latent_effectiveness"][1]
        assert envelope["pressure_drop_pa_per_stream"][0] <= envelope["pressure_drop_pa_per_stream"][1]


def test_terminology_is_unique():
    mod = module()
    frame = mod.terminology_table()
    assert frame["term"].is_unique
    assert "SEC" in set(frame["term"])


def test_industry_benchmark_includes_airjoule_with_boundary_caveat():
    mod = module()
    break_even = mod.break_even_register(
        baseline_compressor_kw=1167.33,
        o30_compressor_kw=382.44,
        water_load_kg_h=4365.92,
        core_power_kw=115.08,
    )
    ledger = pd.DataFrame(
        [
            {
                "scenario": "gas_receiver_o30_core",
                "sec_kwh_kg": 0.026344,
            }
        ]
    )
    frame = mod.industry_benchmarks(
        break_even=break_even,
        ledger=ledger,
    )
    airjoule = frame[frame["benchmark"].str.contains("AirJoule")]
    assert len(airjoule) == 1
    assert float(airjoule.iloc[0]["upper_value"]) == 160.0
    assert "not the same boundary" in str(airjoule.iloc[0]["caveat"])


def test_unified_fom_register_reports_18_rows():
    mod = module()

    class DummyAPI:
        @staticmethod
        def humidity_ratio_from_t_rh(temperature_c, rh, pressure_pa):
            return 0.02 * rh

    class DummyBasis:
        dry_air_mass_flow_kg_s = 10.0
        inlet_humidity_ratio_kg_kg_da = 0.016

    class Args:
        grid_to_device_efficiency = 0.98
        baseline_compressor_kw = 100.0
        o30_compressor_kw = 50.0
        cooling_cop = 4.0
        supply_temperature_c = 20.0
        supply_rh = 0.5
        pressure_pa = 101325.0
        annual_hours = 1000.0
        electricity_price_chf_kwh = 0.25
        process_airflow_cfm = 1000.0
        outdoor_temperature_c = 32.0
        outdoor_rh = 0.8
        target = "O30"
        area_cap_m2 = 100.0

    ledger = pd.DataFrame(
        [
            {
                "scenario": "gas_receiver_o30_core",
                "water_load_kg_h": 100.0,
                "site_total_kw": 10.0,
                "system_claim_available": True,
            }
        ]
    )
    geometry = pd.DataFrame(
        [
            {
                "geometry_feasible": True,
                "channel_fan_power_kw": 1.0,
                "open_channel_volume_m3": 2.0,
            }
        ]
    )
    enclosure = pd.DataFrame(
        [
            {
                "humidity_control_pass": True,
                "maximum_protected_volume_m3": 500.0,
            }
        ]
    )
    frame = mod.unified_fom_register(
        gas_row={
            "reference_gate_pass": True,
            "required_active_area_m2": 50.0,
            "maximum_local_current_density_a_m2": 20.0,
            "integrated_current_a": 1000.0,
        },
        ledger=ledger,
        geometry=geometry,
        enclosure=enclosure,
        context={"api": DummyAPI(), "basis": DummyBasis()},
        args=Args(),
    )
    assert len(frame) == 18
    assert set(frame["fom_id"]) == {f"FOM-{i:02d}" for i in range(1, 19)}
    assert frame.loc[frame["fom_id"].eq("FOM-17"), "status"].iloc[0] == "not_available"

    invalid_ledger = ledger.copy()
    invalid_ledger["site_total_kw"] = math.nan
    invalid_ledger["system_claim_available"] = False
    invalid = mod.unified_fom_register(
        gas_row={
            "reference_gate_pass": False,
            "reference_gate_violations": "current gate failed",
            "required_active_area_m2": 50.0,
            "maximum_local_current_density_a_m2": 21.2,
        },
        ledger=invalid_ledger,
        geometry=geometry,
        enclosure=enclosure,
        context={"api": DummyAPI(), "basis": DummyBasis()},
        args=Args(),
    )
    gas_system_foms = invalid[
        ~invalid["fom_id"].isin(["FOM-09", "FOM-10", "FOM-17", "FOM-18"])
    ]
    assert gas_system_foms["numeric_value"].isna().all()
    assert set(gas_system_foms["status"]) == {"not_available"}
    assert set(gas_system_foms["availability_reason"]) == {"current gate failed"}
