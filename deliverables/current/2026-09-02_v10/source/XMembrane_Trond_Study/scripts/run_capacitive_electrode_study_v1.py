#!/usr/bin/env python3
"""Run the reduced-order capacitive-electrode transient study.

This study answers a narrow question: what changes when the steady electrode
assumption is replaced by two blocking capacitive electrodes?  It is a local
coupon/constitutive screen with fixed bulk activities, not a coupled transient
ERV-core or building-energy prediction.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sys
from typing import Any, Callable, Mapping, Sequence

os.environ.setdefault("MPLCONFIGDIR", "/tmp/heiq-capacitive-electrode-study-mpl")

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from heiq.wp1.airside.properties import calculate_film_state
from heiq.wp1.electrodes.capacitive import (
    FARADAY_C_MOL,
    WATER_MOLAR_MASS_KG_MOL,
    effective_series_capacitance_f_m2,
    simulate_current_controlled_cell,
    signed_powerlaw_state,
)


SCRIPT_VERSION = "capacitive-electrode-transient-study-v1.1-2026-09-02"
DEFAULT_CONFIG = ROOT / "config" / "capacitive_electrode_study_v1.json"
DEFAULT_OUTPUT = ROOT / "outputs" / "capacitive_electrode_study_v1"
PRIMARY_REPLAY_VOLTAGE_BASIS = "original_stored_terminal_voltage"
UPPER_BOUND_REPLAY_VOLTAGE_BASIS = "common_1p8v_current_commanded_ceiling"


class CapacitiveStudyError(RuntimeError):
    """Raised when a study input or result invariant fails."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    return {
        "path": str(resolved),
        "sha256": sha256(resolved),
        "size_bytes": resolved.stat().st_size,
    }


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, (np.integer, np.bool_)):
        return value.item()
    if isinstance(value, np.floating):
        value = float(value)
    if isinstance(value, float):
        if math.isnan(value):
            return None
        if math.isinf(value):
            return "Infinity" if value > 0.0 else "-Infinity"
    return value


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(json_safe(dict(payload)), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def resolve_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def validated_replay_voltage_modes(
    config: Mapping[str, Any],
    *,
    original_terminal_voltage_v: float | None = None,
) -> list[dict[str, Any]]:
    """Validate and optionally resolve the two controlled ERV replay modes."""

    replay = config["frozen_erv_replay"]
    definitions = replay.get("voltage_limit_modes")
    if not isinstance(definitions, list) or len(definitions) != 2:
        raise ValueError("Frozen ERV replay requires exactly two voltage-limit modes")
    by_basis: dict[str, Mapping[str, Any]] = {}
    for definition in definitions:
        if not isinstance(definition, Mapping):
            raise ValueError("Each frozen ERV voltage-limit mode must be an object")
        basis = str(definition.get("voltage_limit_basis", ""))
        if not basis or basis in by_basis:
            raise ValueError("Frozen ERV voltage-limit bases must be nonempty and unique")
        by_basis[basis] = definition
    expected = {
        PRIMARY_REPLAY_VOLTAGE_BASIS,
        UPPER_BOUND_REPLAY_VOLTAGE_BASIS,
    }
    if set(by_basis) != expected:
        raise ValueError(
            "Frozen ERV replay must contain the original-voltage primary mode "
            "and common-1.8-V optimistic upper-bound mode"
        )

    primary = by_basis[PRIMARY_REPLAY_VOLTAGE_BASIS]
    upper = by_basis[UPPER_BOUND_REPLAY_VOLTAGE_BASIS]
    if not (
        primary.get("diagnostic_role")
        == "primary_same_boundary_duration_diagnostic"
        and primary.get("uses_original_stored_terminal_voltage") is True
        and primary.get("optimistic_upper_bound_sensitivity") is False
    ):
        raise ValueError("Original-voltage replay mode is not fail-closed")
    common_voltage = float(upper.get("maximum_absolute_terminal_voltage_v", math.nan))
    configured_common_voltage = float(
        config["electrical"]["maximum_absolute_terminal_voltage_v"]
    )
    if not (
        upper.get("diagnostic_role") == "optimistic_upper_bound_sensitivity"
        and upper.get("uses_original_stored_terminal_voltage") is False
        and upper.get("optimistic_upper_bound_sensitivity") is True
        and math.isclose(
            common_voltage,
            configured_common_voltage,
            rel_tol=0.0,
            abs_tol=1.0e-12,
        )
        and math.isclose(common_voltage, 1.8, rel_tol=0.0, abs_tol=1.0e-12)
    ):
        raise ValueError("Common-voltage replay mode is not the declared 1.8 V upper bound")

    if original_terminal_voltage_v is None:
        return [dict(primary), dict(upper)]
    original_voltage = abs(float(original_terminal_voltage_v))
    if not math.isfinite(original_voltage) or original_voltage <= 0.0:
        raise ValueError("Stored terminal voltage must be finite and nonzero")
    hard_limit = float(config["electrical"]["hard_project_voltage_limit_v"])
    if original_voltage > hard_limit or common_voltage > hard_limit:
        raise ValueError("A frozen replay voltage limit exceeds the project limit")
    return [
        {
            **dict(primary),
            "applied_absolute_terminal_voltage_limit_v": original_voltage,
        },
        {
            **dict(upper),
            "applied_absolute_terminal_voltage_limit_v": common_voltage,
        },
    ]


def load_config(path: Path) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    if config.get("schema_version") != 1:
        raise ValueError("Unsupported capacitive-electrode study schema")
    cell = config["cell"]
    electrical = config["electrical"]
    if not math.isclose(float(cell["active_area_m2"]), 0.0025, rel_tol=0.0, abs_tol=1e-15):
        raise ValueError("The v1 study must retain the declared 25 cm2 coupon area")
    maximum_voltage = float(electrical["maximum_absolute_terminal_voltage_v"])
    hard_voltage = float(electrical["hard_project_voltage_limit_v"])
    if maximum_voltage <= 0.0 or maximum_voltage > hard_voltage or hard_voltage > 2.0:
        raise ValueError("The voltage window must remain positive and at or below 2 V")
    hardware_limit = float(electrical["current_density_hardware_limit_a_m2"])
    commands = [float(value) for value in config["dc_study"]["current_density_commands_a_m2"]]
    if hardware_limit <= 0.0 or max(abs(value) for value in commands) > hardware_limit:
        raise ValueError("DC commands exceed the declared controller current limit")
    claim = config["claim_boundary"]
    required_true = (
        "transient_electrical_capacitance_modelled",
        "dual_frozen_erv_voltage_boundary_replay_modelled",
        "original_stored_voltage_replay_is_primary",
        "common_1p8v_replay_is_optimistic_upper_bound",
    )
    if any(claim.get(key) is not True for key in required_true):
        raise ValueError("The transient and dual-replay claim boundary must remain enabled")
    required_false = (
        "measured_electrode_capacitance_used",
        "measured_faradaic_kinetics_used",
        "constant_phase_element_or_frequency_dispersion_modelled",
        "transient_membrane_water_inventory_modelled",
        "dynamic_gas_stream_humidity_modelled",
        "individual_electrode_potential_constraints_modelled",
        "electrode_pair_electrochemical_window_constraint_modelled",
        "axial_erv_core_modelled",
        "validated_electrode_prediction",
        "full_system_claim_allowed",
        "area_is_acceptance_gate",
    )
    if any(claim.get(key) is not False for key in required_false):
        raise ValueError("The v1 claim boundary must remain fail-closed")
    if not config.get("boundary_cases"):
        raise ValueError("At least one fixed boundary case is required")
    validated_replay_voltage_modes(config)
    return config


def build_membrane_kwargs(
    config: Mapping[str, Any], boundary: Mapping[str, Any]
) -> dict[str, Any]:
    cell = config["cell"]
    film = calculate_film_state(
        side="both",
        temperature_c=float(cell["temperature_c"]),
        velocity_m_s=float(cell["channel_velocity_m_s"]),
        gap_m=float(cell["channel_gap_m"]),
        pressure_pa=float(cell["absolute_pressure_pa"]),
        scale_factor=float(cell["film_scale_factor"]),
    )
    return {
        "source_bulk_activity": float(boundary["source_bulk_activity"]),
        "receiver_bulk_activity": float(boundary["receiver_bulk_activity"]),
        "source_film_coefficient_mol_m2_s_activity": (
            film.activity_film_coefficient_mol_m2_s_activity
        ),
        "receiver_film_coefficient_mol_m2_s_activity": (
            film.activity_film_coefficient_mol_m2_s_activity
        ),
        "temperature_c": float(cell["temperature_c"]),
        "material": dict(config["material"]),
        "reference_activity": float(cell["reference_water_activity"]),
        "transport_series_asr_ohm_m2": float(
            config["electrical"]["transport_series_asr_ohm_m2"]
        ),
    }


def make_dc_time_grid(
    *,
    duration_s: float,
    nominal_charge_time_s: float,
    horizons_s: Sequence[float],
    minimum_charge_steps: int,
    logarithmic_points: int,
) -> np.ndarray:
    duration = float(duration_s)
    charge_time = max(float(nominal_charge_time_s), 1.0e-6)
    early_end = min(duration, 1.5 * charge_time)
    early = np.linspace(0.0, early_end, max(int(minimum_charge_steps), 20) + 1)
    smallest = max(min(charge_time / max(minimum_charge_steps, 20), duration), 1.0e-6)
    if duration > smallest:
        logarithmic = np.geomspace(smallest, duration, max(int(logarithmic_points), 50))
    else:
        logarithmic = np.asarray([duration])
    combined = np.concatenate(
        [early, logarithmic, np.asarray(horizons_s, dtype=float), np.asarray([duration])]
    )
    combined = combined[(combined >= 0.0) & (combined <= duration)]
    return np.unique(np.round(combined, decimals=10))


def square_current_command(amplitude_a_m2: float, frequency_hz: float) -> Callable[[float], float]:
    amplitude = float(amplitude_a_m2)
    frequency = float(frequency_hz)
    if amplitude <= 0.0 or frequency <= 0.0:
        raise ValueError("Square-wave amplitude and frequency must be positive")

    def command(time_s: float) -> float:
        phase = (float(time_s) * frequency) % 1.0
        return amplitude if phase < 0.5 else -amplitude

    return command


def constant_current_command(current_density_a_m2: float) -> Callable[[float], float]:
    current = float(current_density_a_m2)
    return lambda _time_s: current


def simulate(
    *,
    config: Mapping[str, Any],
    boundary: Mapping[str, Any],
    time_s: Sequence[float],
    command: Callable[[float], float],
    individual_capacitance_f_m2: float,
    interface_esr_ohm_m2: float,
    leakage_resistance_ohm_m2: float | None,
    recovery_efficiency: float,
) -> pd.DataFrame:
    electrical = config["electrical"]
    return simulate_current_controlled_cell(
        time_s=time_s,
        current_command=command,
        active_area_m2=float(config["cell"]["active_area_m2"]),
        source_electrode_capacitance_f_m2=float(individual_capacitance_f_m2),
        receiver_electrode_capacitance_f_m2=float(individual_capacitance_f_m2),
        maximum_absolute_terminal_voltage_v=float(
            electrical["maximum_absolute_terminal_voltage_v"]
        ),
        current_density_hardware_limit_a_m2=float(
            electrical["current_density_hardware_limit_a_m2"]
        ),
        interface_esr_ohm_m2=float(interface_esr_ohm_m2),
        interface_leakage_resistance_ohm_m2=leakage_resistance_ohm_m2,
        energy_recovery_efficiency=float(recovery_efficiency),
        membrane_kwargs=build_membrane_kwargs(config, boundary),
    )


def row_at_time(frame: pd.DataFrame, time_s: float) -> pd.Series:
    matches = np.flatnonzero(np.isclose(frame["time_s"].to_numpy(float), float(time_s), atol=1e-7))
    if matches.size != 1:
        raise CapacitiveStudyError(f"Expected exactly one row at t={time_s:g} s")
    return frame.iloc[int(matches[0])]


def continuous_reference(
    *,
    config: Mapping[str, Any],
    boundary: Mapping[str, Any],
    current_density_a_m2: float,
) -> dict[str, Any]:
    state = signed_powerlaw_state(
        current_density_a_m2=float(current_density_a_m2),
        **build_membrane_kwargs(config, boundary),
    )
    if not state.get("solver_success"):
        raise CapacitiveStudyError("Continuous reference state failed")
    return state


def build_dc_study(config: Mapping[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    electrical = config["electrical"]
    study = config["dc_study"]
    area = float(config["cell"]["active_area_m2"])
    maximum_voltage = float(electrical["maximum_absolute_terminal_voltage_v"])
    duration_s = float(study["duration_h"]) * 3600.0
    horizons_s = [float(value) * 3600.0 for value in study["reporting_horizons_h"]]
    reference_capacitance = float(
        electrical["reference_individual_electrode_areal_capacitance_f_m2"]
    )
    reference_timeseries: pd.DataFrame | None = None
    rows: list[dict[str, Any]] = []
    for boundary_id, boundary in config["boundary_cases"].items():
        for individual_capacitance in electrical[
            "individual_electrode_areal_capacitance_sweep_f_m2"
        ]:
            pair_capacitance = effective_series_capacitance_f_m2(
                float(individual_capacitance), float(individual_capacitance)
            )
            for command_current in study["current_density_commands_a_m2"]:
                nominal_charge_time = (
                    pair_capacitance * maximum_voltage / float(command_current)
                )
                time_grid = make_dc_time_grid(
                    duration_s=duration_s,
                    nominal_charge_time_s=nominal_charge_time,
                    horizons_s=horizons_s,
                    minimum_charge_steps=int(study["minimum_steps_during_nominal_charge"]),
                    logarithmic_points=int(study["logarithmic_reporting_points"]),
                )
                frame = simulate(
                    config=config,
                    boundary=boundary,
                    time_s=time_grid,
                    command=constant_current_command(float(command_current)),
                    individual_capacitance_f_m2=float(individual_capacitance),
                    interface_esr_ohm_m2=float(electrical["reference_interface_esr_ohm_m2"]),
                    leakage_resistance_ohm_m2=electrical[
                        "reference_interface_leakage_resistance_ohm_m2"
                    ],
                    recovery_efficiency=float(electrical["reference_energy_recovery_efficiency"]),
                )
                if (
                    boundary_id == "equal_activity_coupon"
                    and math.isclose(float(individual_capacitance), reference_capacitance)
                    and math.isclose(float(command_current), 1.0)
                ):
                    reference_timeseries = frame.assign(
                        boundary_id=boundary_id,
                        individual_electrode_areal_capacitance_f_m2=float(individual_capacitance),
                    )
                reference = continuous_reference(
                    config=config,
                    boundary=boundary,
                    current_density_a_m2=float(command_current),
                )
                for horizon_s in horizons_s:
                    row = row_at_time(frame, horizon_s)
                    continuous_eo_mg = (
                        float(reference["eo_flux_mol_m2_s"])
                        * area
                        * horizon_s
                        * WATER_MOLAR_MASS_KG_MOL
                        * 1.0e6
                    )
                    continuous_net_mg = (
                        float(reference["net_flux_mol_m2_s"])
                        * area
                        * horizon_s
                        * WATER_MOLAR_MASS_KG_MOL
                        * 1.0e6
                    )
                    actual_eo_mg = float(row["cumulative_eo_water_mg"])
                    actual_net_mg = float(row["cumulative_net_water_mg"])
                    charge_identity = (
                        float(row["cumulative_membrane_charge_c"])
                        - float(row["cumulative_faradaic_charge_c"])
                        - float(row["charge_density_c_m2"]) * area
                    )
                    rows.append(
                        {
                            "boundary_id": boundary_id,
                            "source_bulk_activity": float(boundary["source_bulk_activity"]),
                            "receiver_bulk_activity": float(boundary["receiver_bulk_activity"]),
                            "individual_electrode_areal_capacitance_f_m2": float(individual_capacitance),
                            "effective_pair_areal_capacitance_f_m2": pair_capacitance,
                            "total_cell_capacitance_f": pair_capacitance * area,
                            "commanded_current_density_a_m2": float(command_current),
                            "horizon_h": horizon_s / 3600.0,
                            "nominal_capacitive_charge_time_h": nominal_charge_time / 3600.0,
                            "end_current_density_a_m2": float(row["current_density_a_m2"]),
                            "end_terminal_voltage_v": float(row["terminal_voltage_v"]),
                            "end_electrode_pair_voltage_v": float(row["electrode_pair_voltage_v"]),
                            "continuous_reference_eo_water_mg": continuous_eo_mg,
                            "capacitive_eo_water_mg": actual_eo_mg,
                            "eo_retention_fraction_vs_continuous_reference": actual_eo_mg / continuous_eo_mg,
                            "continuous_reference_net_water_mg": continuous_net_mg,
                            "capacitive_net_water_mg": actual_net_mg,
                            "net_retention_fraction_vs_continuous_reference": (
                                actual_net_mg / continuous_net_mg
                                if abs(continuous_net_mg) > 1e-20
                                else math.nan
                            ),
                            "grid_energy_wh": float(row["cumulative_grid_energy_j"]) / 3600.0,
                            "stored_capacitor_energy_wh": float(row["stored_capacitor_energy_j"]) / 3600.0,
                            "charge_identity_residual_c": charge_identity,
                            "energy_balance_residual_j": float(row["energy_balance_residual_j"]),
                            "maximum_absolute_terminal_voltage_v": float(frame.loc[frame["time_s"] <= horizon_s, "terminal_voltage_v"].abs().max()),
                            "voltage_clamped_fraction_of_samples": float(frame.loc[frame["time_s"] <= horizon_s, "voltage_clamped"].astype(float).mean()),
                            "blocking_electrodes": True,
                        }
                    )
    if reference_timeseries is None:
        raise CapacitiveStudyError("Reference DC timeseries was not generated")
    return pd.DataFrame(rows), reference_timeseries


def integrate_interval(frame: pd.DataFrame, column: str, start_s: float) -> float:
    selected = frame.loc[frame["time_s"] >= float(start_s) - 1e-9]
    times = selected["time_s"].to_numpy(float)
    values = selected[column].to_numpy(float)
    if len(selected) < 2:
        raise CapacitiveStudyError("Cycle interval has too few rows")
    return float(np.sum(np.diff(times) * values[1:]))


def build_ac_study(config: Mapping[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    electrical = config["electrical"]
    study = config["ac_study"]
    area = float(config["cell"]["active_area_m2"])
    material = config["material"]
    amplitude = float(study["current_density_amplitude_a_m2"])
    cycles = int(study["cycles"])
    steps_per_cycle = int(study["steps_per_cycle"])
    membrane_time_scale_s = (
        float(material["dry_thickness_um"]) * 1.0e-6
    ) ** 2 / float(material["water_diffusivity_m2_s"])
    rows: list[dict[str, Any]] = []
    reference_cycle: pd.DataFrame | None = None
    reference_capacitance = float(
        electrical["reference_individual_electrode_areal_capacitance_f_m2"]
    )
    for boundary_id, boundary in config["boundary_cases"].items():
        passive = continuous_reference(
            config=config,
            boundary=boundary,
            current_density_a_m2=0.0,
        )
        for individual_capacitance in electrical[
            "individual_electrode_areal_capacitance_sweep_f_m2"
        ]:
            pair_capacitance = effective_series_capacitance_f_m2(
                float(individual_capacitance), float(individual_capacitance)
            )
            for frequency in study["frequencies_hz"]:
                frequency = float(frequency)
                period = 1.0 / frequency
                time_grid = np.linspace(
                    0.0,
                    cycles * period,
                    cycles * steps_per_cycle + 1,
                )
                frame = simulate(
                    config=config,
                    boundary=boundary,
                    time_s=time_grid,
                    command=square_current_command(amplitude, frequency),
                    individual_capacitance_f_m2=float(individual_capacitance),
                    interface_esr_ohm_m2=float(electrical["reference_interface_esr_ohm_m2"]),
                    leakage_resistance_ohm_m2=None,
                    recovery_efficiency=float(electrical["reference_energy_recovery_efficiency"]),
                )
                cycle_start = (cycles - 1) * period
                cycle = frame.loc[frame["time_s"] >= cycle_start - 1e-9].copy()
                cycle["cycle_time_s"] = cycle["time_s"] - cycle_start
                if (
                    boundary_id == "equal_activity_coupon"
                    and math.isclose(float(individual_capacitance), reference_capacitance)
                    and math.isclose(frequency, 0.001)
                ):
                    reference_cycle = cycle.assign(
                        boundary_id=boundary_id,
                        frequency_hz=frequency,
                        individual_electrode_areal_capacitance_f_m2=float(individual_capacitance),
                    )
                eo_moles = integrate_interval(frame, "eo_flux_mol_m2_s", cycle_start) * area
                diffusion_moles = integrate_interval(frame, "diffusion_flux_mol_m2_s", cycle_start) * area
                net_moles = integrate_interval(frame, "net_flux_mol_m2_s", cycle_start) * area
                absolute_eo_moles = integrate_interval(
                    frame.assign(absolute_eo_flux=frame["eo_flux_mol_m2_s"].abs()),
                    "absolute_eo_flux",
                    cycle_start,
                ) * area
                current_charge_c_m2 = integrate_interval(frame, "current_density_a_m2", cycle_start)
                faradaic_charge_c_m2 = integrate_interval(
                    frame, "faradaic_leakage_current_density_a_m2", cycle_start
                )
                start = cycle.iloc[0]
                end = cycle.iloc[-1]
                import_j = float(end["cumulative_import_energy_j"] - start["cumulative_import_energy_j"])
                export_j = float(end["cumulative_export_energy_j"] - start["cumulative_export_energy_j"])
                passive_moles = float(passive["net_flux_mol_m2_s"]) * area * period
                for recovery in electrical["energy_recovery_efficiency_sweep"]:
                    grid_j = import_j - float(recovery) * export_j
                    rows.append(
                        {
                            "boundary_id": boundary_id,
                            "individual_electrode_areal_capacitance_f_m2": float(individual_capacitance),
                            "effective_pair_areal_capacitance_f_m2": pair_capacitance,
                            "frequency_hz": frequency,
                            "period_s": period,
                            "current_density_amplitude_a_m2": amplitude,
                            "energy_recovery_efficiency": float(recovery),
                            "cycle_charge_density_c_m2": current_charge_c_m2,
                            "cycle_faradaic_charge_density_c_m2": faradaic_charge_c_m2,
                            "cycle_eo_water_mg": eo_moles * WATER_MOLAR_MASS_KG_MOL * 1.0e6,
                            "cycle_absolute_shuttled_eo_water_mg": absolute_eo_moles * WATER_MOLAR_MASS_KG_MOL * 1.0e6,
                            "cycle_diffusion_water_mg": diffusion_moles * WATER_MOLAR_MASS_KG_MOL * 1.0e6,
                            "cycle_net_water_mg": net_moles * WATER_MOLAR_MASS_KG_MOL * 1.0e6,
                            "passive_reference_cycle_water_mg": passive_moles * WATER_MOLAR_MASS_KG_MOL * 1.0e6,
                            "incremental_cycle_water_above_passive_mg": (net_moles - passive_moles) * WATER_MOLAR_MASS_KG_MOL * 1.0e6,
                            "cycle_import_energy_j": import_j,
                            "cycle_export_energy_j": export_j,
                            "cycle_grid_energy_j": grid_j,
                            "cycle_charge_closure_c_m2": float(end["charge_density_c_m2"] - start["charge_density_c_m2"]),
                            "maximum_absolute_terminal_voltage_v": float(cycle["terminal_voltage_v"].abs().max()),
                            "voltage_clamped_fraction_of_samples": float(cycle["voltage_clamped"].astype(float).mean()),
                            "period_over_membrane_l2_over_d": period / membrane_time_scale_s,
                            "quasisteady_membrane_frequency_validated": False,
                        }
                    )
    if reference_cycle is None:
        raise CapacitiveStudyError("Reference AC cycle was not generated")
    return pd.DataFrame(rows), reference_cycle


def build_leakage_study(config: Mapping[str, Any]) -> pd.DataFrame:
    electrical = config["electrical"]
    capacitance = float(electrical["reference_individual_electrode_areal_capacitance_f_m2"])
    command_current = 1.0
    duration_s = 24.0 * 3600.0
    time_grid = make_dc_time_grid(
        duration_s=duration_s,
        nominal_charge_time_s=effective_series_capacitance_f_m2(capacitance, capacitance)
        * float(electrical["maximum_absolute_terminal_voltage_v"])
        / command_current,
        horizons_s=[duration_s],
        minimum_charge_steps=300,
        logarithmic_points=600,
    )
    rows: list[dict[str, Any]] = []
    for boundary_id, boundary in config["boundary_cases"].items():
        for leakage in electrical["interface_leakage_resistance_sweep_ohm_m2"]:
            frame = simulate(
                config=config,
                boundary=boundary,
                time_s=time_grid,
                command=constant_current_command(command_current),
                individual_capacitance_f_m2=capacitance,
                interface_esr_ohm_m2=float(electrical["reference_interface_esr_ohm_m2"]),
                leakage_resistance_ohm_m2=leakage,
                recovery_efficiency=float(electrical["reference_energy_recovery_efficiency"]),
            )
            end = frame.iloc[-1]
            rows.append(
                {
                    "boundary_id": boundary_id,
                    "interface_leakage_resistance_ohm_m2": math.inf if leakage is None else float(leakage),
                    "end_current_density_a_m2": float(end["current_density_a_m2"]),
                    "end_faradaic_current_density_a_m2": float(end["faradaic_leakage_current_density_a_m2"]),
                    "end_capacitive_current_density_a_m2": float(end["capacitive_current_density_a_m2"]),
                    "end_terminal_voltage_v": float(end["terminal_voltage_v"]),
                    "cumulative_eo_water_mg": float(end["cumulative_eo_water_mg"]),
                    "cumulative_net_water_mg": float(end["cumulative_net_water_mg"]),
                    "grid_energy_wh": float(end["cumulative_grid_energy_j"]) / 3600.0,
                    "continuous_current_is_faradaic_not_blocking_capacitive": leakage is not None,
                }
            )
    return pd.DataFrame(rows)


def build_esr_study(config: Mapping[str, Any]) -> pd.DataFrame:
    electrical = config["electrical"]
    boundary = config["boundary_cases"]["equal_activity_coupon"]
    capacitance = float(electrical["reference_individual_electrode_areal_capacitance_f_m2"])
    duration_s = 4.0 * 3600.0
    time_grid = make_dc_time_grid(
        duration_s=duration_s,
        nominal_charge_time_s=effective_series_capacitance_f_m2(capacitance, capacitance)
        * float(electrical["maximum_absolute_terminal_voltage_v"]),
        horizons_s=[duration_s],
        minimum_charge_steps=240,
        logarithmic_points=500,
    )
    rows: list[dict[str, Any]] = []
    for esr in electrical["interface_esr_sweep_ohm_m2"]:
        frame = simulate(
            config=config,
            boundary=boundary,
            time_s=time_grid,
            command=constant_current_command(1.0),
            individual_capacitance_f_m2=capacitance,
            interface_esr_ohm_m2=float(esr),
            leakage_resistance_ohm_m2=None,
            recovery_efficiency=float(electrical["reference_energy_recovery_efficiency"]),
        )
        end = frame.iloc[-1]
        rows.append(
            {
                "interface_esr_ohm_m2": float(esr),
                "end_current_density_a_m2": float(end["current_density_a_m2"]),
                "end_terminal_voltage_v": float(end["terminal_voltage_v"]),
                "cumulative_eo_water_mg": float(end["cumulative_eo_water_mg"]),
                "grid_energy_wh": float(end["cumulative_grid_energy_j"]) / 3600.0,
            }
        )
    return pd.DataFrame(rows)


def build_frozen_erv_replay(config: Mapping[str, Any]) -> tuple[pd.DataFrame, list[Path]]:
    """Replay blocking-electrode duration at stored direct-ERV segment states.

    Each case is replayed twice: first at its original stored terminal-voltage
    limit, which is the primary same-boundary diagnostic, and then with the
    stored current command allowed to continue up to the common 1.8 V terminal
    ceiling, which is an explicitly optimistic upper-bound sensitivity.  The
    stored bulk states and installed steady-state area are held fixed in both
    modes.  Neither mode feeds falling EO duty back into either air stream.
    """

    replay = config.get("frozen_erv_replay", {})
    if not replay.get("enabled", False):
        return pd.DataFrame(), []
    case_path = resolve_path(replay["case_register_csv"])
    segment_path = resolve_path(replay["segment_register_csv"])
    if not case_path.is_file() or not segment_path.is_file():
        raise FileNotFoundError(
            "Frozen ERV replay inputs are missing: "
            f"{case_path}, {segment_path}"
        )
    cases = pd.read_csv(case_path)
    segments = pd.read_csv(segment_path)
    electrical = config["electrical"]
    material = dict(config["material"])
    reference_activity = float(config["cell"]["reference_water_activity"])
    capacitance = float(
        electrical["reference_individual_electrode_areal_capacitance_f_m2"]
    )
    pair_capacitance = effective_series_capacitance_f_m2(
        capacitance, capacitance
    )
    horizons_s = [float(value) * 3600.0 for value in replay["reporting_horizons_h"]]
    duration_s = max(horizons_s)
    rows: list[dict[str, Any]] = []
    for selected_case in replay["cases"]:
        case_id = str(selected_case["case_id"])
        case_label = str(selected_case["case_label"])
        case_rows = cases.loc[cases["case_id"].eq(case_id)]
        profile = segments.loc[segments["case_id"].eq(case_id)].sort_values(
            "segment_index"
        )
        if len(case_rows) != 1 or profile.empty:
            raise CapacitiveStudyError(
                f"Frozen ERV replay expected one case and nonempty profile for {case_id}"
            )
        case_row = case_rows.iloc[0]
        target_kg_h = float(case_row["water_transfer_target_kg_h"])
        original_voltage = abs(float(case_row["terminal_voltage_v"]))
        for replay_mode in validated_replay_voltage_modes(
            config,
            original_terminal_voltage_v=original_voltage,
        ):
            voltage_limit = float(
                replay_mode["applied_absolute_terminal_voltage_limit_v"]
            )
            segment_results: list[
                tuple[Mapping[str, Any], pd.DataFrame, float, float]
            ] = []
            for segment in profile.to_dict("records"):
                command_current = float(segment["current_density_a_m2"])
                membrane_kwargs = {
                    "source_bulk_activity": float(segment["source_bulk_activity"]),
                    "receiver_bulk_activity": float(segment["receiver_bulk_activity"]),
                    "source_film_coefficient_mol_m2_s_activity": float(
                        segment["source_film_coefficient_mol_m2_s_activity"]
                    ),
                    "receiver_film_coefficient_mol_m2_s_activity": float(
                        segment["receiver_film_coefficient_mol_m2_s_activity"]
                    ),
                    "temperature_c": float(segment["membrane_temperature_c"]),
                    "material": material,
                    "reference_activity": reference_activity,
                    "transport_series_asr_ohm_m2": float(
                        segment["series_asr_ohm_m2"]
                    ),
                }
                zero_current = signed_powerlaw_state(
                    current_density_a_m2=0.0,
                    **membrane_kwargs,
                )
                if not zero_current.get("solver_success"):
                    raise CapacitiveStudyError(
                        f"Frozen replay zero-current state failed for {case_id}"
                    )
                equilibrium_pair_voltage = (
                    voltage_limit
                    - float(zero_current["membrane_transport_voltage_v"])
                )
                nominal_pair_voltage_swing = max(
                    abs(equilibrium_pair_voltage),
                    voltage_limit,
                    1.0e-9,
                )
                nominal_charge_time = (
                    pair_capacitance
                    * nominal_pair_voltage_swing
                    / max(abs(command_current), 1.0e-12)
                )
                time_grid = make_dc_time_grid(
                    duration_s=duration_s,
                    nominal_charge_time_s=nominal_charge_time,
                    horizons_s=horizons_s,
                    minimum_charge_steps=int(
                        config["dc_study"]["minimum_steps_during_nominal_charge"]
                    ),
                    logarithmic_points=int(
                        config["dc_study"]["logarithmic_reporting_points"]
                    ),
                )
                frame = simulate_current_controlled_cell(
                    time_s=time_grid,
                    current_command=constant_current_command(command_current),
                    active_area_m2=float(segment["required_active_area_m2"]),
                    source_electrode_capacitance_f_m2=capacitance,
                    receiver_electrode_capacitance_f_m2=capacitance,
                    maximum_absolute_terminal_voltage_v=voltage_limit,
                    current_density_hardware_limit_a_m2=float(
                        electrical["current_density_hardware_limit_a_m2"]
                    ),
                    interface_esr_ohm_m2=float(
                        electrical["reference_interface_esr_ohm_m2"]
                    ),
                    interface_leakage_resistance_ohm_m2=None,
                    energy_recovery_efficiency=float(
                        electrical["reference_energy_recovery_efficiency"]
                    ),
                    membrane_kwargs=membrane_kwargs,
                )
                initial = frame.iloc[0]
                initial_voltage_error = float(initial["terminal_voltage_v"]) - float(
                    segment["calculated_terminal_voltage_v"]
                )
                stored_flux = float(segment["net_flux_mol_m2_s"])
                initial_flux_relative_error = (
                    float(initial["net_flux_mol_m2_s"]) - stored_flux
                ) / max(abs(stored_flux), 1.0e-20)
                segment_results.append(
                    (
                        segment,
                        frame,
                        initial_voltage_error,
                        initial_flux_relative_error,
                    )
                )
            maximum_initial_voltage_error = max(
                abs(record[2]) for record in segment_results
            )
            maximum_initial_flux_relative_error = max(
                abs(record[3]) for record in segment_results
            )
            for horizon_s in horizons_s:
                continuous_eo_kg = 0.0
                continuous_net_kg = 0.0
                capacitive_eo_kg = 0.0
                capacitive_net_kg = 0.0
                grid_energy_kwh = 0.0
                end_total_current_a = 0.0
                maximum_terminal_voltage = 0.0
                maximum_pair_voltage = 0.0
                maximum_charge_residual_c = 0.0
                for segment, frame, _voltage_error, _flux_error in segment_results:
                    endpoint = row_at_time(frame, horizon_s)
                    area = float(segment["required_active_area_m2"])
                    continuous_eo_kg += (
                        float(segment["eo_flux_mol_m2_s"])
                        * area
                        * horizon_s
                        * WATER_MOLAR_MASS_KG_MOL
                    )
                    continuous_net_kg += (
                        float(segment["net_flux_mol_m2_s"])
                        * area
                        * horizon_s
                        * WATER_MOLAR_MASS_KG_MOL
                    )
                    capacitive_eo_kg += (
                        float(endpoint["cumulative_eo_water_mg"]) / 1.0e6
                    )
                    capacitive_net_kg += (
                        float(endpoint["cumulative_net_water_mg"]) / 1.0e6
                    )
                    grid_energy_kwh += (
                        float(endpoint["cumulative_grid_energy_j"]) / 3.6e6
                    )
                    end_total_current_a += (
                        float(endpoint["current_density_a_m2"]) * area
                    )
                    interval = frame.loc[frame["time_s"] <= horizon_s]
                    maximum_terminal_voltage = max(
                        maximum_terminal_voltage,
                        float(interval["terminal_voltage_v"].abs().max()),
                    )
                    maximum_pair_voltage = max(
                        maximum_pair_voltage,
                        float(interval["electrode_pair_voltage_v"].abs().max()),
                    )
                    charge_residual = (
                        float(endpoint["cumulative_membrane_charge_c"])
                        - float(endpoint["cumulative_faradaic_charge_c"])
                        - float(endpoint["charge_density_c_m2"]) * area
                    )
                    maximum_charge_residual_c = max(
                        maximum_charge_residual_c, abs(charge_residual)
                    )
                is_primary = (
                    replay_mode["voltage_limit_basis"]
                    == PRIMARY_REPLAY_VOLTAGE_BASIS
                )
                is_upper = (
                    replay_mode["voltage_limit_basis"]
                    == UPPER_BOUND_REPLAY_VOLTAGE_BASIS
                )
                rows.append(
                    {
                        "case_label": case_label,
                        "case_id": case_id,
                        "voltage_limit_basis": replay_mode["voltage_limit_basis"],
                        "diagnostic_role": replay_mode["diagnostic_role"],
                        "applied_absolute_terminal_voltage_limit_v": voltage_limit,
                        "original_steady_terminal_voltage_v": original_voltage,
                        "applied_to_original_voltage_limit_ratio": (
                            voltage_limit / original_voltage
                        ),
                        "voltage_limit_matches_original_steady_case": is_primary,
                        "primary_same_boundary_duration_diagnostic": is_primary,
                        "optimistic_upper_bound_sensitivity": is_upper,
                        "terminal_controller_basis": (
                            "stored_current_density_command_with_absolute_voltage_clamp"
                        ),
                        "original_steady_active_area_m2": float(
                            case_row["required_active_area_m2"]
                        ),
                        "original_water_transfer_target_kg_h": target_kg_h,
                        "horizon_h": horizon_s / 3600.0,
                        "continuous_reference_eo_water_kg": continuous_eo_kg,
                        "capacitive_eo_water_kg": capacitive_eo_kg,
                        "eo_retention_fraction_vs_continuous_reference": (
                            capacitive_eo_kg / continuous_eo_kg
                        ),
                        "continuous_reference_net_water_kg": continuous_net_kg,
                        "capacitive_net_water_kg": capacitive_net_kg,
                        "net_retention_fraction_vs_continuous_reference": (
                            capacitive_net_kg / continuous_net_kg
                        ),
                        "capacitive_water_equivalent_hours_at_original_target": (
                            capacitive_net_kg / target_kg_h
                        ),
                        "end_total_current_a": end_total_current_a,
                        "grid_energy_kwh": grid_energy_kwh,
                        "maximum_absolute_terminal_voltage_v": (
                            maximum_terminal_voltage
                        ),
                        "maximum_absolute_electrode_pair_voltage_v": (
                            maximum_pair_voltage
                        ),
                        "terminal_voltage_limit_is_electrode_window_limit": False,
                        "individual_electrode_potentials_resolved": False,
                        "individual_electrode_potential_constraints_modelled": False,
                        "electrode_pair_electrochemical_window_constraint_modelled": False,
                        "maximum_segment_charge_identity_residual_c": (
                            maximum_charge_residual_c
                        ),
                        "maximum_initial_terminal_replay_error_v": (
                            maximum_initial_voltage_error
                        ),
                        "maximum_initial_net_flux_relative_error": (
                            maximum_initial_flux_relative_error
                        ),
                        "frozen_bulk_states_and_installed_area": True,
                        "dynamic_erv_response_modelled": False,
                    }
                )
    return pd.DataFrame(rows), [case_path, segment_path]


def save_figure(fig: plt.Figure, directory: Path, stem: str) -> list[Path]:
    png = directory / f"{stem}.png"
    pdf = directory / f"{stem}.pdf"
    fig.savefig(png, dpi=220, bbox_inches="tight", facecolor="white")
    fig.savefig(pdf, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return [png, pdf]


def make_figures(
    *,
    dc: pd.DataFrame,
    reference_dc: pd.DataFrame,
    ac: pd.DataFrame,
    reference_ac: pd.DataFrame,
    leakage: pd.DataFrame,
    erv_replay: pd.DataFrame,
    output: Path,
    config: Mapping[str, Any],
) -> list[Path]:
    figures = output / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update(
        {
            "font.size": 10,
            "axes.grid": True,
            "grid.alpha": 0.25,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )
    outputs: list[Path] = []

    fig, axes = plt.subplots(3, 1, figsize=(8.4, 8.2), sharex=True)
    hours = reference_dc["time_s"] / 3600.0
    axes[0].plot(hours, reference_dc["current_density_a_m2"], color="#087E8B", linewidth=2.0)
    axes[0].axhline(1.0, color="#777777", linestyle="--", linewidth=1.0, label="command")
    axes[0].set_ylabel("Current density\n[A m$^{-2}$]")
    axes[0].legend(frameon=False)
    axes[1].plot(hours, reference_dc["electrode_pair_voltage_v"], color="#E07A3F", linewidth=2.0, label="electrode pair")
    axes[1].plot(hours, reference_dc["terminal_voltage_v"], color="#394867", linewidth=1.5, label="terminal")
    axes[1].axhline(float(config["electrical"]["maximum_absolute_terminal_voltage_v"]), color="#222222", linestyle="--", linewidth=1.0)
    axes[1].set_ylabel("Voltage [V]")
    axes[1].legend(frameon=False)
    axes[2].plot(hours, reference_dc["cumulative_eo_water_mg"], color="#6A994E", linewidth=2.0)
    axes[2].set_xlabel("Elapsed time [h]")
    axes[2].set_ylabel("Cumulative EO water [mg]")
    axes[0].set_title("Blocking electrodes give a finite startup displacement, not steady DC")
    outputs.extend(save_figure(fig, figures, "01_blocking_dc_transient"))

    selected = dc.loc[
        dc["boundary_id"].eq("equal_activity_coupon")
        & dc["horizon_h"].isin([1.0, 24.0])
    ]
    fig, axes = plt.subplots(1, 2, figsize=(10.0, 4.5), sharey=True)
    colors = {0.5: "#087E8B", 1.0: "#E07A3F", 5.0: "#6A994E"}
    for axis, horizon in zip(axes, [1.0, 24.0]):
        group_h = selected.loc[np.isclose(selected["horizon_h"], horizon)]
        for current, group in group_h.groupby("commanded_current_density_a_m2"):
            ordered = group.sort_values("individual_electrode_areal_capacitance_f_m2")
            axis.plot(
                ordered["individual_electrode_areal_capacitance_f_m2"],
                100.0 * ordered["eo_retention_fraction_vs_continuous_reference"],
                marker="o",
                linewidth=2.0,
                color=colors.get(float(current), "#555555"),
                label=f"{current:g} A/m²",
            )
        axis.set_xscale("log")
        axis.set_ylim(-2.0, 105.0)
        axis.set_xlabel("Assumed capacitance of each electrode [F m$^{-2}$]")
        axis.set_title(f"{horizon:g} h operating horizon")
    axes[0].set_ylabel("Retained EO displacement vs continuous reference [%]")
    axes[1].legend(frameon=False)
    outputs.extend(save_figure(fig, figures, "02_dc_retention_vs_capacitance"))

    ac_selected = ac.loc[
        ac["boundary_id"].eq("equal_activity_coupon")
        & np.isclose(ac["energy_recovery_efficiency"], 0.9)
    ]
    fig, axes = plt.subplots(1, 2, figsize=(10.0, 4.5))
    for capacitance, group in ac_selected.groupby("individual_electrode_areal_capacitance_f_m2"):
        ordered = group.sort_values("frequency_hz")
        displayed_net = np.where(
            ordered["cycle_eo_water_mg"].abs().to_numpy(float) < 1.0e-6,
            0.0,
            ordered["cycle_eo_water_mg"].to_numpy(float),
        )
        axes[0].plot(
            ordered["frequency_hz"],
            displayed_net,
            marker="o",
            linewidth=1.8,
            label=f"{capacitance:g} F/m² each",
        )
        axes[1].plot(
            ordered["frequency_hz"],
            ordered["cycle_absolute_shuttled_eo_water_mg"],
            marker="o",
            linewidth=1.8,
        )
    axes[0].axhline(0.0, color="#222222", linewidth=1.0)
    axes[0].set_ylim(-1.0e-5, 1.0e-5)
    axes[0].set_xscale("log")
    axes[0].set_xlabel("Square-current frequency [Hz]")
    axes[0].set_ylabel("Net EO water per closed cycle [mg]")
    axes[0].set_title("Charge-balanced EO increment closes to zero")
    axes[0].legend(frameon=False, fontsize=8)
    axes[1].set_xscale("log")
    axes[1].set_yscale("log")
    axes[1].set_xlabel("Square-current frequency [Hz]")
    axes[1].set_ylabel("Absolute water shuttled per cycle [mg]")
    axes[1].set_title("Water still moves back and forth")
    outputs.extend(save_figure(fig, figures, "03_symmetric_ac_cycle"))

    leak_equal = leakage.loc[leakage["boundary_id"].eq("equal_activity_coupon")].copy()
    leak_equal["label"] = leak_equal["interface_leakage_resistance_ohm_m2"].map(
        lambda value: "blocking" if math.isinf(float(value)) else f"{float(value):g} Ω m²"
    )
    fig, axes = plt.subplots(1, 2, figsize=(9.4, 4.4))
    x = np.arange(len(leak_equal))
    axes[0].bar(x, leak_equal["end_current_density_a_m2"], color="#087E8B")
    axes[0].set_xticks(x, leak_equal["label"], rotation=15)
    axes[0].set_ylabel("Current density after 24 h [A m$^{-2}$]")
    axes[0].set_title("Only leakage sustains DC current")
    axes[1].bar(x, leak_equal["cumulative_eo_water_mg"], color="#E07A3F")
    axes[1].set_xticks(x, leak_equal["label"], rotation=15)
    axes[1].set_ylabel("Cumulative EO water after 24 h [mg]")
    axes[1].set_title("Sustained result is then Faradaic, not purely capacitive")
    outputs.extend(save_figure(fig, figures, "04_leakage_sensitivity"))

    fig, axes = plt.subplots(3, 1, figsize=(8.4, 7.8), sharex=True)
    cycle_time = reference_ac["cycle_time_s"]
    axes[0].step(cycle_time, reference_ac["commanded_current_density_a_m2"], where="post", color="#777777", label="command")
    axes[0].plot(cycle_time, reference_ac["current_density_a_m2"], color="#087E8B", linewidth=1.6, label="actual")
    axes[0].set_ylabel("j [A m$^{-2}$]")
    axes[0].legend(frameon=False)
    axes[1].plot(cycle_time, reference_ac["electrode_pair_voltage_v"], color="#E07A3F", linewidth=1.8)
    axes[1].set_ylabel("Electrode pair [V]")
    axes[2].plot(cycle_time, reference_ac["eo_flux_mol_m2_s"], color="#6A994E", linewidth=1.8)
    axes[2].axhline(0.0, color="#222222", linewidth=1.0)
    axes[2].set_ylabel("EO flux [mol m$^{-2}$ s$^{-1}$]")
    axes[2].set_xlabel("Time within final cycle [s]")
    axes[0].set_title("Reference 1 mHz cycle: forward transport is reversed on discharge")
    outputs.extend(save_figure(fig, figures, "05_reference_ac_waveform"))

    if not erv_replay.empty:
        fig, axes = plt.subplots(1, 2, figsize=(10.0, 4.6))
        labels = {
            "direct_erv_o30": "Direct ERV to O30",
            "direct_erv_full_duty": "Direct ERV full duty",
        }
        colors = {
            "direct_erv_o30": "#087E8B",
            "direct_erv_full_duty": "#E07A3F",
        }
        line_styles = {
            PRIMARY_REPLAY_VOLTAGE_BASIS: "-",
            UPPER_BOUND_REPLAY_VOLTAGE_BASIS: "--",
        }
        mode_labels = {
            PRIMARY_REPLAY_VOLTAGE_BASIS: "original voltage (primary)",
            UPPER_BOUND_REPLAY_VOLTAGE_BASIS: "1.8 V ceiling (upper bound)",
        }
        for (case_label, voltage_basis), group in erv_replay.groupby(
            ["case_label", "voltage_limit_basis"], sort=False
        ):
            ordered = group.sort_values("horizon_h")
            label = (
                f"{labels.get(case_label, case_label)} — "
                f"{mode_labels.get(voltage_basis, voltage_basis)}"
            )
            axes[0].plot(
                ordered["horizon_h"],
                100.0
                * ordered["eo_retention_fraction_vs_continuous_reference"],
                marker="o",
                linewidth=2.0,
                color=colors.get(case_label, "#555555"),
                linestyle=line_styles.get(voltage_basis, "-"),
                label=label,
            )
            axes[1].plot(
                ordered["horizon_h"],
                ordered["capacitive_water_equivalent_hours_at_original_target"],
                marker="o",
                linewidth=2.0,
                color=colors.get(case_label, "#555555"),
                linestyle=line_styles.get(voltage_basis, "-"),
            )
        axes[0].set_xlabel("Operating horizon [h]")
        axes[0].set_ylabel("Retained EO displacement vs steady reference [%]")
        axes[0].set_title("Original-voltage result and optimistic 1.8 V bound")
        axes[0].legend(frameon=False, fontsize=8)
        axes[1].set_xlabel("Operating horizon [h]")
        axes[1].set_ylabel("Cumulative water / original target rate [h]")
        axes[1].set_title("Both electrical boundaries give finite inventory")
        axes[1].axhline(1.0, color="#777777", linestyle="--", linewidth=1.0)
        outputs.extend(save_figure(fig, figures, "06_frozen_erv_capacity_duration"))
    return outputs


def write_summary(
    path: Path,
    *,
    config: Mapping[str, Any],
    dc: pd.DataFrame,
    ac: pd.DataFrame,
    leakage: pd.DataFrame,
    erv_replay: pd.DataFrame,
) -> None:
    ref_cap = float(config["electrical"]["reference_individual_electrode_areal_capacitance_f_m2"])
    ref_dc = dc.loc[
        dc["boundary_id"].eq("equal_activity_coupon")
        & np.isclose(dc["individual_electrode_areal_capacitance_f_m2"], ref_cap)
    ]

    def dc_row(current: float, horizon: float) -> pd.Series:
        selected = ref_dc.loc[
            np.isclose(ref_dc["commanded_current_density_a_m2"], current)
            & np.isclose(ref_dc["horizon_h"], horizon)
        ]
        if len(selected) != 1:
            raise CapacitiveStudyError("Reference DC summary row is not unique")
        return selected.iloc[0]

    one_h_05 = dc_row(0.5, 1.0)
    day_05 = dc_row(0.5, 24.0)
    one_h_1 = dc_row(1.0, 1.0)
    day_1 = dc_row(1.0, 24.0)
    one_h_5 = dc_row(5.0, 1.0)
    day_5 = dc_row(5.0, 24.0)
    ac_ref = ac.loc[
        ac["boundary_id"].eq("equal_activity_coupon")
        & np.isclose(ac["individual_electrode_areal_capacitance_f_m2"], ref_cap)
        & np.isclose(ac["energy_recovery_efficiency"], 0.9)
    ]
    max_cycle_eo = float(ac_ref["cycle_eo_water_mg"].abs().max())
    max_cycle_charge = float(ac_ref["cycle_charge_closure_c_m2"].abs().max())
    blocking = leakage.loc[
        leakage["boundary_id"].eq("equal_activity_coupon")
        & np.isinf(leakage["interface_leakage_resistance_ohm_m2"])
    ].iloc[0]
    membrane_time_h = (
        (float(config["material"]["dry_thickness_um"]) * 1.0e-6) ** 2
        / float(config["material"]["water_diffusivity_m2_s"])
        / 3600.0
    )
    lines = [
        "# Capacitive-electrode transient study v1",
        "",
        "## Main finding",
        "",
        (
            "A purely blocking capacitive electrode pair does not support the "
            "continuous DC current assumed by the earlier steady model. It gives a "
            "finite startup displacement while the electrodes charge; after the "
            "1.8 V limit is reached, current and incremental EO transport decay toward zero."
        ),
        "",
        "For the 25 cm² cell and the unmeasured reference assumption of "
        f"{ref_cap:,.0f} F/m² for each identical electrode "
        f"({ref_cap / 2:,.0f} F/m² effective pair capacitance):",
        "",
        (
            f"- At 0.5 A/m², the capacitive model retains {100 * one_h_05['eo_retention_fraction_vs_continuous_reference']:.1f}% "
            f"of the counterfactual continuous-electrode EO displacement after 1 h, but only {100 * day_05['eo_retention_fraction_vs_continuous_reference']:.1f}% when averaged over 24 h."
        ),
        (
            f"- At 1 A/m², the corresponding values are {100 * one_h_1['eo_retention_fraction_vs_continuous_reference']:.1f}% and "
            f"{100 * day_1['eo_retention_fraction_vs_continuous_reference']:.1f}%."
        ),
        (
            f"- At 5 A/m², they fall to {100 * one_h_5['eo_retention_fraction_vs_continuous_reference']:.1f}% after 1 h and "
            f"{100 * day_5['eo_retention_fraction_vs_continuous_reference']:.1f}% over 24 h."
        ),
        (
            f"- The ideal blocking case ends at {blocking['end_current_density_a_m2']:.4g} A/m² after 24 h."
        ),
        "",
        "## Symmetric cycling",
        "",
        (
            "The full-cycle EO increment is zero to numerical precision for the "
            f"reference sweep (maximum |cycle EO| {max_cycle_eo:.3g} mg and maximum "
            f"charge-closure residual {max_cycle_charge:.3g} C/m²). Water is moved "
            "forward during one half-cycle and returned during the other. The assisting "
            "ERV gradient retains its passive diffusion contribution, but it does not "
            "make constant-drag, charge-balanced EO transport sustainable by itself."
        ),
        "",
        "## Interpretation",
        "",
        "A nonzero sustained result in the leakage sweep comes from the diagnostic Faradaic leakage branch. It must therefore be treated as an electrode-reaction architecture, with reaction products, lifetime and overpotential measured explicitly—not as purely capacitive EO.",
    ]
    if not erv_replay.empty:
        replay_index = erv_replay.set_index(
            ["case_label", "voltage_limit_basis", "horizon_h"]
        )

        def replay_row(case_label: str, basis: str, horizon_h: float) -> pd.Series:
            row = replay_index.loc[(case_label, basis, horizon_h)]
            if isinstance(row, pd.DataFrame):
                raise CapacitiveStudyError("Frozen replay summary row is not unique")
            return row

        o30_primary_1 = replay_row(
            "direct_erv_o30", PRIMARY_REPLAY_VOLTAGE_BASIS, 1.0
        )
        o30_primary_24 = replay_row(
            "direct_erv_o30", PRIMARY_REPLAY_VOLTAGE_BASIS, 24.0
        )
        full_primary_1 = replay_row(
            "direct_erv_full_duty", PRIMARY_REPLAY_VOLTAGE_BASIS, 1.0
        )
        full_primary_24 = replay_row(
            "direct_erv_full_duty", PRIMARY_REPLAY_VOLTAGE_BASIS, 24.0
        )
        o30_upper_1 = replay_row(
            "direct_erv_o30", UPPER_BOUND_REPLAY_VOLTAGE_BASIS, 1.0
        )
        o30_upper_24 = replay_row(
            "direct_erv_o30", UPPER_BOUND_REPLAY_VOLTAGE_BASIS, 24.0
        )
        full_upper_1 = replay_row(
            "direct_erv_full_duty", UPPER_BOUND_REPLAY_VOLTAGE_BASIS, 1.0
        )
        full_upper_24 = replay_row(
            "direct_erv_full_duty", UPPER_BOUND_REPLAY_VOLTAGE_BASIS, 24.0
        )
        lines.extend(
            [
                "",
                "## Dual frozen replay of the stored direct-ERV cases",
                "",
                (
                    "The primary same-boundary replay retains the original stored "
                    f"terminal-voltage limits ({o30_primary_24['original_steady_terminal_voltage_v']:.3g} V "
                    "for O30 and "
                    f"{full_primary_24['original_steady_terminal_voltage_v']:.3g} V for full duty). "
                    "At O30 it retains "
                    f"{100 * o30_primary_1['eo_retention_fraction_vs_continuous_reference']:.1f}% "
                    "of the former steady EO displacement over the first hour and "
                    f"{100 * o30_primary_24['eo_retention_fraction_vs_continuous_reference']:.2f}% "
                    "when averaged over 24 h."
                ),
                (
                    "For the full-duty case, the primary values are "
                    f"{100 * full_primary_1['eo_retention_fraction_vs_continuous_reference']:.1f}% "
                    f"and {100 * full_primary_24['eo_retention_fraction_vs_continuous_reference']:.2f}%. "
                    "The corresponding finite inventories are "
                    f"{o30_primary_24['capacitive_water_equivalent_hours_at_original_target']:.2f} h "
                    "and "
                    f"{full_primary_24['capacitive_water_equivalent_hours_at_original_target']:.2f} h "
                    "at the original target rates."
                ),
                (
                    "The separate optimistic sensitivity keeps commanding the stored "
                    "current densities and permits terminal voltage to rise to 1.8 V. "
                    "It gives O30 retentions of "
                    f"{100 * o30_upper_1['eo_retention_fraction_vs_continuous_reference']:.1f}% "
                    f"and {100 * o30_upper_24['eo_retention_fraction_vs_continuous_reference']:.1f}%, "
                    "and full-duty retentions of "
                    f"{100 * full_upper_1['eo_retention_fraction_vs_continuous_reference']:.1f}% "
                    f"and {100 * full_upper_24['eo_retention_fraction_vs_continuous_reference']:.1f}%, "
                    "at 1 h and 24 h. These are upper-bound sensitivities, not "
                    "same-voltage replays."
                ),
                "",
                (
                    "Both modes freeze the original bulk states, films and installed "
                    "area while current collapses. They diagnose duration only; neither "
                    "is a mass-balanced transient ERV or a revised HVAC-saving calculation."
                ),
                (
                    "The model reports an effective pair-capacitor voltage but does not "
                    "resolve or constrain individual electrode potentials or impose an "
                    "electrode-pair electrochemical stability window. In the 1.8 V O30 "
                    "upper-bound replay the maximum pair-capacitor voltage is "
                    f"{o30_upper_24['maximum_absolute_electrode_pair_voltage_v']:.2f} V; "
                    "the 1.8 V terminal ceiling must not be read as an electrode-window limit."
                ),
            ]
        )
    lines.extend(
        [
            "",
            "## Claim boundary",
            "",
            (
                f"The electrical RC state is transient, but the membrane profile is still "
                f"quasi-steady. The anchor membrane has L²/D ≈ {membrane_time_h:.2f} h, "
                "so the tested AC periods are faster than internal water equilibration and "
                "are not frequency-validated predictions. Capacitance, leakage, ESR and "
                "energy recovery are sensitivity coordinates, not measurements. Gas-stream "
                "humidity response, dynamic axial ERV evolution, CPE dispersion, individual "
                "electrode potentials, electrode stability windows and full-system energy are not closed."
            ),
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_audit(
    *,
    config: Mapping[str, Any],
    dc: pd.DataFrame,
    reference_dc: pd.DataFrame,
    ac: pd.DataFrame,
    reference_ac: pd.DataFrame,
    erv_replay: pd.DataFrame,
) -> dict[str, Any]:
    maximum_allowed = float(config["electrical"]["maximum_absolute_terminal_voltage_v"])
    charge_scale = max(float(reference_dc["cumulative_membrane_charge_c"].abs().max()), 1.0)
    dc_charge_residual = float(dc["charge_identity_residual_c"].abs().max())
    ac_blocking = ac.loc[np.isclose(ac["energy_recovery_efficiency"], 0.9)]
    ac_charge_closure = float(ac_blocking["cycle_charge_closure_c_m2"].abs().max())
    ac_eo_closure = float(ac_blocking["cycle_eo_water_mg"].abs().max())
    max_voltage = max(
        float(dc["maximum_absolute_terminal_voltage_v"].max()),
        float(ac["maximum_absolute_terminal_voltage_v"].max()),
        float(reference_dc["terminal_voltage_v"].abs().max()),
        float(reference_ac["terminal_voltage_v"].abs().max()),
        (
            float(erv_replay["maximum_absolute_terminal_voltage_v"].max())
            if not erv_replay.empty
            else 0.0
        ),
    )
    replay_enabled = bool(config.get("frozen_erv_replay", {}).get("enabled", False))
    if erv_replay.empty:
        dual_replay_complete = not replay_enabled
        replay_labels_fail_closed = not replay_enabled
        replay_voltage_limits_respected = not replay_enabled
        replay_electrode_window_limits_declared = not replay_enabled
        optimistic_replay_dominates_primary = not replay_enabled
        maximum_pair_voltage = 0.0
        maximum_primary_pair_voltage = 0.0
        maximum_upper_pair_voltage = 0.0
    else:
        expected_keys = {
            (
                str(case["case_label"]),
                basis,
                float(horizon),
            )
            for case in config["frozen_erv_replay"]["cases"]
            for basis in (
                PRIMARY_REPLAY_VOLTAGE_BASIS,
                UPPER_BOUND_REPLAY_VOLTAGE_BASIS,
            )
            for horizon in config["frozen_erv_replay"]["reporting_horizons_h"]
        }
        actual_keys = {
            (
                str(row.case_label),
                str(row.voltage_limit_basis),
                float(row.horizon_h),
            )
            for row in erv_replay.itertuples(index=False)
        }
        dual_replay_complete = bool(
            replay_enabled
            and len(erv_replay) == len(expected_keys)
            and actual_keys == expected_keys
        )
        primary = erv_replay.loc[
            erv_replay["voltage_limit_basis"].eq(PRIMARY_REPLAY_VOLTAGE_BASIS)
        ].copy()
        upper = erv_replay.loc[
            erv_replay["voltage_limit_basis"].eq(
                UPPER_BOUND_REPLAY_VOLTAGE_BASIS
            )
        ].copy()
        replay_labels_fail_closed = bool(
            not primary.empty
            and not upper.empty
            and primary["diagnostic_role"]
            .eq("primary_same_boundary_duration_diagnostic")
            .all()
            and primary["primary_same_boundary_duration_diagnostic"]
            .astype(bool)
            .all()
            and not primary["optimistic_upper_bound_sensitivity"]
            .astype(bool)
            .any()
            and upper["diagnostic_role"]
            .eq("optimistic_upper_bound_sensitivity")
            .all()
            and upper["optimistic_upper_bound_sensitivity"].astype(bool).all()
            and not upper["primary_same_boundary_duration_diagnostic"]
            .astype(bool)
            .any()
            and np.allclose(
                primary["applied_absolute_terminal_voltage_limit_v"],
                primary["original_steady_terminal_voltage_v"],
                rtol=0.0,
                atol=1.0e-12,
            )
            and np.allclose(
                upper["applied_absolute_terminal_voltage_limit_v"],
                1.8,
                rtol=0.0,
                atol=1.0e-12,
            )
        )
        replay_voltage_limits_respected = bool(
            np.all(
                erv_replay["maximum_absolute_terminal_voltage_v"].to_numpy(float)
                <= erv_replay[
                    "applied_absolute_terminal_voltage_limit_v"
                ].to_numpy(float)
                + 2.0e-6
            )
        )
        maximum_pair_voltage = float(
            erv_replay["maximum_absolute_electrode_pair_voltage_v"].max()
        )
        maximum_primary_pair_voltage = float(
            primary["maximum_absolute_electrode_pair_voltage_v"].max()
        )
        maximum_upper_pair_voltage = float(
            upper["maximum_absolute_electrode_pair_voltage_v"].max()
        )
        replay_electrode_window_limits_declared = bool(
            np.isfinite(
                erv_replay[
                    "maximum_absolute_electrode_pair_voltage_v"
                ].to_numpy(float)
            ).all()
            and not erv_replay[
                "terminal_voltage_limit_is_electrode_window_limit"
            ]
            .astype(bool)
            .any()
            and not erv_replay["individual_electrode_potentials_resolved"]
            .astype(bool)
            .any()
            and not erv_replay[
                "individual_electrode_potential_constraints_modelled"
            ]
            .astype(bool)
            .any()
            and not erv_replay[
                "electrode_pair_electrochemical_window_constraint_modelled"
            ]
            .astype(bool)
            .any()
        )
        comparison = primary.merge(
            upper,
            on=["case_label", "case_id", "horizon_h"],
            suffixes=("_primary", "_upper"),
            validate="one_to_one",
        )
        optimistic_replay_dominates_primary = bool(
            np.all(
                comparison[
                    "capacitive_eo_water_kg_upper"
                ].to_numpy(float)
                + 1.0e-9
                >= comparison[
                    "capacitive_eo_water_kg_primary"
                ].to_numpy(float)
            )
        )
    checks = {
        "declared_25_cm2_area_retained": math.isclose(float(config["cell"]["active_area_m2"]), 0.0025),
        "terminal_voltage_within_1p8v": max_voltage <= maximum_allowed + 2.0e-6,
        "dc_charge_balance": dc_charge_residual <= 2.0e-7 * charge_scale,
        "blocking_ac_cycle_charge_closure": ac_charge_closure <= 2.0e-5,
        "blocking_ac_cycle_eo_closure": ac_eo_closure <= 1.0e-5,
        "blocking_dc_current_decays": bool(
            np.all(
                dc.loc[np.isclose(dc["horizon_h"], 24.0), "end_current_density_a_m2"].abs().to_numpy(float)
                < 2.0e-3
            )
        ),
        "no_full_system_claim": config["claim_boundary"]["full_system_claim_allowed"] is False,
        "unmeasured_capacitance_declared": config["claim_boundary"]["measured_electrode_capacitance_used"] is False,
        "membrane_inventory_limit_declared": config["claim_boundary"]["transient_membrane_water_inventory_modelled"] is False,
        "frozen_erv_dual_voltage_modes_complete": dual_replay_complete,
        "frozen_erv_voltage_mode_labels_fail_closed": replay_labels_fail_closed,
        "frozen_erv_mode_specific_terminal_limits_respected": (
            replay_voltage_limits_respected
        ),
        "frozen_erv_optimistic_upper_bound_not_below_primary": (
            optimistic_replay_dominates_primary
        ),
        "electrode_window_constraints_explicitly_not_modelled": (
            replay_electrode_window_limits_declared
            and config["claim_boundary"][
                "individual_electrode_potential_constraints_modelled"
            ]
            is False
            and config["claim_boundary"][
                "electrode_pair_electrochemical_window_constraint_modelled"
            ]
            is False
        ),
        "frozen_erv_replay_is_fail_closed": bool(
            erv_replay.empty
            or not erv_replay["dynamic_erv_response_modelled"].astype(bool).any()
        ),
        "frozen_erv_initial_state_reproduced": bool(
            erv_replay.empty
            or (
                float(
                    erv_replay["maximum_initial_terminal_replay_error_v"]
                    .abs()
                    .max()
                )
                < 1.0e-4
                and float(
                    erv_replay["maximum_initial_net_flux_relative_error"]
                    .abs()
                    .max()
                )
                < 5.0e-4
            )
        ),
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "all_pass": all(checks.values()),
        "checks": checks,
        "metrics": {
            "maximum_absolute_terminal_voltage_v": max_voltage,
            "maximum_dc_charge_identity_residual_c": dc_charge_residual,
            "maximum_ac_cycle_charge_closure_c_m2": ac_charge_closure,
            "maximum_ac_cycle_eo_water_closure_mg": ac_eo_closure,
            "maximum_frozen_erv_electrode_pair_voltage_v": maximum_pair_voltage,
            "maximum_primary_frozen_erv_electrode_pair_voltage_v": (
                maximum_primary_pair_voltage
            ),
            "maximum_optimistic_frozen_erv_electrode_pair_voltage_v": (
                maximum_upper_pair_voltage
            ),
            "maximum_frozen_erv_initial_terminal_replay_error_v": (
                float(
                    erv_replay["maximum_initial_terminal_replay_error_v"]
                    .abs()
                    .max()
                )
                if not erv_replay.empty
                else 0.0
            ),
            "maximum_frozen_erv_initial_net_flux_relative_error": (
                float(
                    erv_replay["maximum_initial_net_flux_relative_error"]
                    .abs()
                    .max()
                )
                if not erv_replay.empty
                else 0.0
            ),
        },
        "claim_boundary": dict(config["claim_boundary"]),
    }


def run(config_path: Path, output: Path, overwrite: bool = False) -> dict[str, Any]:
    config_path = config_path.resolve()
    output = output.resolve()
    known_outputs = (
        "config_used.json",
        "dc_horizon_summary.csv",
        "reference_dc_timeseries.csv",
        "ac_cycle_summary.csv",
        "reference_ac_cycle.csv",
        "leakage_sensitivity.csv",
        "interface_esr_sensitivity.csv",
        "frozen_erv_replay_summary.csv",
        "SUMMARY.md",
        "audit.json",
        "source_manifest.json",
        "figures",
    )
    existing = [output / name for name in known_outputs if (output / name).exists()]
    if existing and not overwrite:
        raise FileExistsError(
            "Refusing to overwrite existing capacitive study outputs: "
            + ", ".join(str(path) for path in existing)
        )
    if overwrite:
        for path in existing:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
    output.mkdir(parents=True, exist_ok=True)
    config = load_config(config_path)
    write_json(output / "config_used.json", config)

    dc, reference_dc = build_dc_study(config)
    ac, reference_ac = build_ac_study(config)
    leakage = build_leakage_study(config)
    esr = build_esr_study(config)
    erv_replay, erv_source_paths = build_frozen_erv_replay(config)
    dc.to_csv(output / "dc_horizon_summary.csv", index=False)
    reference_dc.to_csv(output / "reference_dc_timeseries.csv", index=False)
    ac.to_csv(output / "ac_cycle_summary.csv", index=False)
    reference_ac.to_csv(output / "reference_ac_cycle.csv", index=False)
    leakage.to_csv(output / "leakage_sensitivity.csv", index=False)
    esr.to_csv(output / "interface_esr_sensitivity.csv", index=False)
    if not erv_replay.empty:
        erv_replay.to_csv(output / "frozen_erv_replay_summary.csv", index=False)
    figures = make_figures(
        dc=dc,
        reference_dc=reference_dc,
        ac=ac,
        reference_ac=reference_ac,
        leakage=leakage,
        erv_replay=erv_replay,
        output=output,
        config=config,
    )
    write_summary(
        output / "SUMMARY.md",
        config=config,
        dc=dc,
        ac=ac,
        leakage=leakage,
        erv_replay=erv_replay,
    )
    audit = build_audit(
        config=config,
        dc=dc,
        reference_dc=reference_dc,
        ac=ac,
        reference_ac=reference_ac,
        erv_replay=erv_replay,
    )
    write_json(output / "audit.json", audit)

    source_paths = [
        config_path,
        Path(__file__).resolve(),
        ROOT / "src" / "heiq" / "wp1" / "electrodes" / "capacitive.py",
        *erv_source_paths,
    ]
    generated = [
        output / "config_used.json",
        output / "dc_horizon_summary.csv",
        output / "reference_dc_timeseries.csv",
        output / "ac_cycle_summary.csv",
        output / "reference_ac_cycle.csv",
        output / "leakage_sensitivity.csv",
        output / "interface_esr_sensitivity.csv",
        *(
            [output / "frozen_erv_replay_summary.csv"]
            if not erv_replay.empty
            else []
        ),
        output / "SUMMARY.md",
        output / "audit.json",
        *figures,
    ]
    manifest = {
        "study_id": config["study_id"],
        "script_version": SCRIPT_VERSION,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "sources": [file_record(path) for path in source_paths],
        "generated_outputs": [file_record(path) for path in generated],
        "verification": {"audit_all_pass": bool(audit["all_pass"])},
    }
    write_json(output / "source_manifest.json", manifest)
    if not audit["all_pass"]:
        raise CapacitiveStudyError("Capacitive study audit failed")
    return audit


def main() -> None:
    args = parse_args()
    audit = run(args.config, args.output_dir, overwrite=args.overwrite)
    print(json.dumps(json_safe(audit), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
