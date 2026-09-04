from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

from heiq.wp1.airside.properties import calculate_film_state
from heiq.wp1.electrodes.capacitive import (
    FARADAY_C_MOL,
    effective_series_capacitance_f_m2,
    simulate_current_controlled_cell,
    signed_powerlaw_state,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "capacitive_electrode_study_v1.json"
RUNNER_PATH = ROOT / "scripts" / "run_capacitive_electrode_study_v1.py"
CONFIG = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def load_runner():
    spec = importlib.util.spec_from_file_location(
        "_capacitive_electrode_study_test", RUNNER_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def membrane_kwargs(source: float = 0.5, receiver: float = 0.5):
    cell = CONFIG["cell"]
    film = calculate_film_state(
        side="both",
        temperature_c=cell["temperature_c"],
        velocity_m_s=cell["channel_velocity_m_s"],
        gap_m=cell["channel_gap_m"],
        pressure_pa=cell["absolute_pressure_pa"],
        scale_factor=cell["film_scale_factor"],
    )
    return {
        "source_bulk_activity": source,
        "receiver_bulk_activity": receiver,
        "source_film_coefficient_mol_m2_s_activity": (
            film.activity_film_coefficient_mol_m2_s_activity
        ),
        "receiver_film_coefficient_mol_m2_s_activity": (
            film.activity_film_coefficient_mol_m2_s_activity
        ),
        "temperature_c": cell["temperature_c"],
        "material": CONFIG["material"],
        "reference_activity": cell["reference_water_activity"],
        "transport_series_asr_ohm_m2": CONFIG["electrical"][
            "transport_series_asr_ohm_m2"
        ],
    }


def simulate(time_s, command, *, leakage=None, capacitance=10000.0, voltage=1.8):
    return simulate_current_controlled_cell(
        time_s=time_s,
        current_command=command,
        active_area_m2=0.0025,
        source_electrode_capacitance_f_m2=capacitance,
        receiver_electrode_capacitance_f_m2=capacitance,
        maximum_absolute_terminal_voltage_v=voltage,
        current_density_hardware_limit_a_m2=5.0,
        interface_esr_ohm_m2=0.0,
        interface_leakage_resistance_ohm_m2=leakage,
        energy_recovery_efficiency=0.9,
        membrane_kwargs=membrane_kwargs(),
    )


def test_two_equal_electrodes_have_half_the_single_electrode_capacitance():
    assert effective_series_capacitance_f_m2(10000.0, 10000.0) == pytest.approx(
        5000.0
    )


def test_signed_membrane_state_obeys_polarity_reversal_symmetry():
    plus = signed_powerlaw_state(current_density_a_m2=1.0, **membrane_kwargs())
    minus = signed_powerlaw_state(current_density_a_m2=-1.0, **membrane_kwargs())
    assert plus["solver_success"] and minus["solver_success"]
    assert minus["net_flux_mol_m2_s"] == pytest.approx(
        -plus["net_flux_mol_m2_s"], rel=1e-11, abs=1e-15
    )
    assert minus["membrane_transport_voltage_v"] == pytest.approx(
        -plus["membrane_transport_voltage_v"], rel=1e-11, abs=1e-15
    )


def test_blocking_dc_has_finite_charge_and_water_then_current_decays():
    frame = simulate(
        np.linspace(0.0, 8.0 * 3600.0, 801),
        lambda _time: 1.0,
    )
    end = frame.iloc[-1]
    area = 0.0025
    expected_eo_moles = (
        CONFIG["material"]["water_drag"]
        * float(end["cumulative_membrane_charge_c"])
        / FARADAY_C_MOL
    )
    observed_eo_moles = (
        float(end["cumulative_eo_water_mg"]) / 1.0e6 / 0.01801528
    )
    assert abs(float(end["current_density_a_m2"])) < 1.0e-7
    assert float(end["terminal_voltage_v"]) == pytest.approx(1.8, abs=2e-8)
    assert observed_eo_moles == pytest.approx(expected_eo_moles, rel=1e-10)
    charge_identity = (
        float(end["cumulative_membrane_charge_c"])
        - float(end["cumulative_faradaic_charge_c"])
        - float(end["charge_density_c_m2"]) * area
    )
    assert abs(charge_identity) < 1.0e-8


def test_symmetric_blocking_cycle_has_zero_net_eo_but_nonzero_shuttling():
    frequency = 0.001
    period = 1.0 / frequency
    cycles = 4
    steps_per_cycle = 120
    frame = simulate(
        np.linspace(0.0, cycles * period, cycles * steps_per_cycle + 1),
        lambda time: 1.0 if (time * frequency) % 1.0 < 0.5 else -1.0,
    )
    cycle = frame.loc[frame["time_s"] >= (cycles - 1) * period - 1e-9]
    start = cycle.iloc[0]
    end = cycle.iloc[-1]
    cycle_eo_mg = float(
        end["cumulative_eo_water_mg"] - start["cumulative_eo_water_mg"]
    )
    assert abs(float(end["charge_density_c_m2"] - start["charge_density_c_m2"])) < 1e-7
    assert abs(cycle_eo_mg) < 1e-8
    times = cycle["time_s"].to_numpy(float)
    absolute_flux = cycle["eo_flux_mol_m2_s"].abs().to_numpy(float)
    shuttled = float(np.sum(np.diff(times) * absolute_flux[1:]))
    assert shuttled > 0.0


def test_linear_leakage_sustains_faradaic_not_capacitive_current():
    blocking = simulate(
        np.linspace(0.0, 24.0 * 3600.0, 601),
        lambda _time: 1.0,
        leakage=None,
    ).iloc[-1]
    leaky = simulate(
        np.linspace(0.0, 24.0 * 3600.0, 601),
        lambda _time: 1.0,
        leakage=1.0,
    ).iloc[-1]
    assert abs(float(blocking["current_density_a_m2"])) < 1e-6
    assert float(leaky["current_density_a_m2"]) == pytest.approx(1.0, rel=2e-5)
    assert float(leaky["faradaic_leakage_current_density_a_m2"]) == pytest.approx(
        1.0, rel=2e-5
    )
    assert abs(float(leaky["capacitive_current_density_a_m2"])) < 2e-5


def test_config_stays_under_two_volts_and_fail_closed():
    runner = load_runner()
    config = runner.load_config(CONFIG_PATH)
    assert config["electrical"]["maximum_absolute_terminal_voltage_v"] == 1.8
    assert config["electrical"]["hard_project_voltage_limit_v"] == 2.0
    assert config["claim_boundary"]["full_system_claim_allowed"] is False
    assert config["claim_boundary"]["measured_electrode_capacitance_used"] is False
    assert config["claim_boundary"]["transient_membrane_water_inventory_modelled"] is False
    assert (
        config["claim_boundary"][
            "individual_electrode_potential_constraints_modelled"
        ]
        is False
    )
    assert (
        config["claim_boundary"][
            "electrode_pair_electrochemical_window_constraint_modelled"
        ]
        is False
    )
    modes = runner.validated_replay_voltage_modes(
        config, original_terminal_voltage_v=0.025
    )
    assert [mode["voltage_limit_basis"] for mode in modes] == [
        runner.PRIMARY_REPLAY_VOLTAGE_BASIS,
        runner.UPPER_BOUND_REPLAY_VOLTAGE_BASIS,
    ]
    assert modes[0]["applied_absolute_terminal_voltage_limit_v"] == pytest.approx(
        0.025
    )
    assert modes[1]["applied_absolute_terminal_voltage_limit_v"] == pytest.approx(
        1.8
    )


def test_config_rejects_missing_or_mislabelled_replay_mode(tmp_path: Path):
    runner = load_runner()
    broken = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    broken["frozen_erv_replay"]["voltage_limit_modes"] = broken[
        "frozen_erv_replay"
    ]["voltage_limit_modes"][:1]
    broken_path = tmp_path / "missing_mode.json"
    broken_path.write_text(json.dumps(broken), encoding="utf-8")
    with pytest.raises(ValueError, match="exactly two"):
        runner.load_config(broken_path)

    broken = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    broken["frozen_erv_replay"]["voltage_limit_modes"][1][
        "optimistic_upper_bound_sensitivity"
    ] = False
    broken_path = tmp_path / "mislabelled_mode.json"
    broken_path.write_text(json.dumps(broken), encoding="utf-8")
    with pytest.raises(ValueError, match="not the declared 1.8 V upper bound"):
        runner.load_config(broken_path)


def test_frozen_replay_contains_primary_and_optimistic_voltage_modes(
    tmp_path: Path,
):
    runner = load_runner()
    config = runner.load_config(CONFIG_PATH)
    selected = config["frozen_erv_replay"]["cases"][0]
    cases = pd.read_csv(
        ROOT / config["frozen_erv_replay"]["case_register_csv"]
    )
    segments = pd.read_csv(
        ROOT / config["frozen_erv_replay"]["segment_register_csv"]
    )
    case = cases.loc[cases["case_id"].eq(selected["case_id"])]
    segment = (
        segments.loc[segments["case_id"].eq(selected["case_id"])]
        .sort_values("segment_index")
        .head(1)
    )
    assert len(case) == 1 and len(segment) == 1
    case_path = tmp_path / "case_register.csv"
    segment_path = tmp_path / "segment_register.csv"
    case.to_csv(case_path, index=False)
    segment.to_csv(segment_path, index=False)
    config["frozen_erv_replay"]["case_register_csv"] = str(case_path)
    config["frozen_erv_replay"]["segment_register_csv"] = str(segment_path)
    config["frozen_erv_replay"]["cases"] = [selected]
    config["frozen_erv_replay"]["reporting_horizons_h"] = [24.0]
    config["dc_study"]["minimum_steps_during_nominal_charge"] = 40
    config["dc_study"]["logarithmic_reporting_points"] = 80

    replay, sources = runner.build_frozen_erv_replay(config)
    assert sources == [case_path, segment_path]
    assert set(replay["voltage_limit_basis"]) == {
        runner.PRIMARY_REPLAY_VOLTAGE_BASIS,
        runner.UPPER_BOUND_REPLAY_VOLTAGE_BASIS,
    }
    assert len(replay) == 2
    primary = replay.loc[
        replay["voltage_limit_basis"].eq(runner.PRIMARY_REPLAY_VOLTAGE_BASIS)
    ].iloc[0]
    upper = replay.loc[
        replay["voltage_limit_basis"].eq(
            runner.UPPER_BOUND_REPLAY_VOLTAGE_BASIS
        )
    ].iloc[0]
    assert primary["applied_absolute_terminal_voltage_limit_v"] == pytest.approx(
        float(case.iloc[0]["terminal_voltage_v"])
    )
    assert upper["applied_absolute_terminal_voltage_limit_v"] == pytest.approx(1.8)
    assert bool(primary["primary_same_boundary_duration_diagnostic"])
    assert not bool(primary["optimistic_upper_bound_sensitivity"])
    assert bool(upper["optimistic_upper_bound_sensitivity"])
    assert not bool(upper["primary_same_boundary_duration_diagnostic"])
    assert upper["capacitive_eo_water_kg"] > primary["capacitive_eo_water_kg"]
    assert (
        upper["maximum_absolute_electrode_pair_voltage_v"]
        > upper["applied_absolute_terminal_voltage_limit_v"]
    )
    assert not bool(upper["individual_electrode_potentials_resolved"])
    assert not bool(
        upper["electrode_pair_electrochemical_window_constraint_modelled"]
    )


def test_quick_cli_contract_and_overwrite_refusal(tmp_path: Path):
    runner = load_runner()
    quick = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    quick["boundary_cases"] = {
        "equal_activity_coupon": quick["boundary_cases"]["equal_activity_coupon"]
    }
    quick["electrical"]["individual_electrode_areal_capacitance_sweep_f_m2"] = [
        10000.0
    ]
    quick["electrical"]["interface_esr_sweep_ohm_m2"] = [0.0]
    quick["electrical"]["interface_leakage_resistance_sweep_ohm_m2"] = [None]
    quick["electrical"]["energy_recovery_efficiency_sweep"] = [0.9]
    quick["dc_study"]["reporting_horizons_h"] = [1.0, 24.0]
    quick["dc_study"]["minimum_steps_during_nominal_charge"] = 30
    quick["dc_study"]["logarithmic_reporting_points"] = 50
    quick["ac_study"]["frequencies_hz"] = [0.001]
    quick["ac_study"]["cycles"] = 2
    quick["ac_study"]["steps_per_cycle"] = 40
    quick["frozen_erv_replay"]["enabled"] = False
    config_path = tmp_path / "quick_config.json"
    config_path.write_text(json.dumps(quick), encoding="utf-8")
    output = tmp_path / "study"
    audit = runner.run(config_path, output, overwrite=False)
    assert audit["all_pass"]
    manifest = json.loads(
        (output / "source_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["verification"]["audit_all_pass"]
    assert (output / "figures" / "01_blocking_dc_transient.pdf").is_file()
    for record in [*manifest["sources"], *manifest["generated_outputs"]]:
        path = Path(record["path"])
        assert path.is_file()
        assert hashlib_sha256(path) == record["sha256"]
    with pytest.raises(FileExistsError):
        runner.run(config_path, output, overwrite=False)


def hashlib_sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()
