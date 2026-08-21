from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "make_wp1_trond_system_closure_v1.py"


def module():
    spec = importlib.util.spec_from_file_location("_trond_closure_test", SCRIPT)
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
