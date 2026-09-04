from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def test_o30_terminal1_golden_point():
    df = pd.read_csv(ROOT / "data/golden/o30/overall_best.csv")
    assert len(df) == 1
    r = df.iloc[0]
    assert str(r["target"]) == "O30"
    assert np.isclose(float(r["water_drag"]), 100.060787, rtol=1e-6)
    assert np.isclose(float(r["water_diffusivity_m2_s"]), 1.597880e-14, rtol=1e-5)
    assert np.isclose(float(r["conductivity_s_m"]), 23.171887, rtol=1e-6)
    assert np.isclose(float(r["dry_thickness_um"]), 36.913700, rtol=1e-6)
    assert np.isclose(float(r["terminal_voltage_v"]), 0.98, atol=1e-8)
    assert np.isclose(float(r["required_active_area_m2"]), 8922.21294, rtol=1e-6)
    assert np.isclose(
        float(
            r[
                "maximum_local_current_density_a_m2"
            ]
        ),
        21.224,
        rtol=2e-4,
    )
    assert (
        float(
            r[
                "maximum_local_current_density_a_m2"
            ]
        )
        > 21.0
    )
    assert np.isclose(float(r["analysis_core_power_kw"]), 115.017720, rtol=1e-6)
    assert np.isclose(float(r["analysis_core_sec_kwh_kg"]), 0.026344, rtol=2e-5)


def test_o50_low_voltage_golden_point():
    df = pd.read_csv(ROOT / "data/golden/o50/best_by_drag.csv")
    power = pd.to_numeric(df["analysis_core_power_kw"], errors="raise")
    r = df.loc[power.idxmin()]
    assert str(r["target"]) == "O50"
    assert np.isclose(float(r["required_active_area_m2"]), 5308.144516, rtol=1e-5)
    assert np.isclose(float(r["analysis_core_power_kw"]), 16.430131, rtol=1e-5)
    assert np.isclose(float(r["analysis_core_sec_kwh_kg"]), 0.006212, rtol=1e-4)
    assert float(r["terminal_voltage_v"]) <= 1.1e-5


def test_o30_voltage_budget_is_chemical_potential_dominated():
    p = ROOT / "data/golden/thermodynamic_audit/axial_voltage_flux_budget.csv"
    df = pd.read_csv(p)
    weights = pd.to_numeric(df["step_area_m2"], errors="raise").to_numpy()
    water = pd.to_numeric(df["water_polarisation_voltage_v"], errors="raise").to_numpy()
    ohmic = pd.to_numeric(df["ohmic_voltage_v"], errors="raise").to_numpy()
    series = pd.to_numeric(df["series_loss_voltage_v"], errors="raise").to_numpy()
    terminal = pd.to_numeric(df["reconstructed_terminal_voltage_v"], errors="raise").to_numpy()
    water_mean = np.average(water, weights=weights)
    ohmic_mean = np.average(ohmic, weights=weights)
    series_mean = np.average(series, weights=weights)
    terminal_mean = np.average(terminal, weights=weights)
    assert np.isclose(terminal_mean, 0.98, atol=5e-4)
    assert water_mean / terminal_mean > 0.999
    assert ohmic_mean < 2e-4
    assert series_mean < 2e-4


def test_o30_backdiffusion_is_negligible_at_selected_point():
    p = ROOT / "data/golden/thermodynamic_audit/axial_voltage_flux_budget.csv"
    df = pd.read_csv(p)
    eo = pd.to_numeric(df["eo_flux_mol_m2_s"], errors="raise").to_numpy()
    diff = pd.to_numeric(df["diffusion_flux_mol_m2_s"], errors="raise").to_numpy()
    mask = eo > 0
    fraction = np.max(np.abs(diff[mask]) / eo[mask])
    assert fraction < 1e-4


def test_existing_liquid_activity_scan_has_no_crossing_above_0p7():
    p = ROOT / "data/golden/direct_liquid/crossover_summary.csv"
    if not p.exists():
        return
    df = pd.read_csv(p)
    assert len(df) > 0
    assert df["estimated_break_even_liquid_activity"].isna().all()
    assert df["status"].astype(str).eq("NO_CROSSOVER_IN_TESTED_RANGE__TEST_LOWER_ACTIVITY").all()
