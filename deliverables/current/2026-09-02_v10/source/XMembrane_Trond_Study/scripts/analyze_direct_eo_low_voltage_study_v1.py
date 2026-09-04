#!/usr/bin/env python3
"""Analyse the separate <=2 V direct-EO inverse-design study.

The upstream V50/V53 transport calculation is current-controlled.  Voltage
caps in this analysis are therefore post-screens on maximum *required* local
voltage, not fixed applied terminal voltages.  The inherited no-ERV margin is
kept under an explicitly historical name.  A second, hash-bound modern AC+ERV
comparator is calculated both before and after declared receiver-SEC
scenarios.  Receiver closure remains outside the model, so no result is a
full-system energy claim.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Iterable

os.environ.setdefault("MPLCONFIGDIR", "/tmp/heiq-direct-eo-low-voltage-mpl")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "direct_eo_low_voltage_study_v1.json"
DEFAULT_ROOT = ROOT / "outputs" / "direct_eo_low_voltage_study_v1_candidate_20260826"
EPS = 1.0e-9

NAVY = "#17324D"
TEAL = "#008C8C"
TEAL_DARK = "#005F63"
ORANGE = "#E58B2A"
RED = "#B94A3D"
GREY = "#D8E0E6"
SLATE = "#607284"
INK = "#172A3A"
WHITE = "#FFFFFF"

PASS_CMAP = LinearSegmentedColormap.from_list(
    "low_voltage_pass", ["#F1F5F6", "#A8D9D6", "#38A9A4", "#005F63"]
)
MARGIN_CMAP = LinearSegmentedColormap.from_list(
    "modern_margin", ["#B94A3D", "#F4C37D", "#F7F7F3", "#76C5C0", "#005F63"]
)

AXIS_TO_COLUMN = {
    "current_density_a_m2": "current_density_a_m2",
    "transport_number_reference_t_w": "transport_number_reference_t_w",
    "water_diffusivity_scale_vs_pfsa": "water_diffusivity_scale_vs_pfsa",
    "dry_thickness_um": "dry_thickness_um",
    "ionic_area_resistance_ohm_m2_at_lambda_ref": "ionic_area_resistance_ohm_m2_at_lambda_ref",
    "retention_factor_vs_pfsa_sorption": "retention_factor_vs_pfsa_sorption",
    "receiver_control_activity": "receiver_control_activity",
    "cell_voltage_caps_v": "cell_voltage_cap_tested_v",
}

PHYSICAL_KEYS = [
    "current_density_a_m2",
    "transport_number_reference_t_w",
    "water_diffusivity_scale_vs_pfsa",
    "dry_thickness_um",
    "ionic_area_resistance_ohm_m2_at_lambda_ref",
    "retention_factor_vs_pfsa_sorption",
    "receiver_control_activity",
]

REQUIRED_COLUMNS = {
    *PHYSICAL_KEYS,
    "active_area_m2",
    "baseline_hvac_kw",
    "cell_voltage_cap_tested_v",
    "cell_voltage_required_max_v",
    "cell_voltage_required_mean_v",
    "conditional_known_electric_saving_kw",
    "eo_grid_power_kw",
    "hard_area_cap_pass",
    "known_electric_total_kw",
    "process_surface_activity_min",
    "receiver_sink_energy_kw_assumed",
    "receiver_sink_net_kg_h",
    "selected_voltage_cap_pass",
    "strict_physical_and_architecture_pass",
    "voltage_electrode_overpotential_v",
    "voltage_interface_v",
    "voltage_membrane_ohmic_max_v",
    "voltage_series_ohmic_v",
    "voltage_water_activity_reversible_max_v",
}

BOOLEAN_COLUMNS = {
    "hard_area_cap_pass",
    "selected_voltage_cap_pass",
    "strict_physical_and_architecture_pass",
    "target_reached_pass",
    "water_retention_pass",
    "pressure_drop_pass",
    "packaging_pass",
    "gas_surface_activity_pass",
    "receiver_surface_activity_pass",
    "process_surface_full_module_pass",
    "v50_architecture_pass_at_screening_cap",
}

OUTPUT_FILES = [
    "low_voltage_cap_register.csv",
    "physical_register.csv",
    "tw_j_summary.csv",
    "tw_summary.csv",
    "gate_counts.csv",
    "receiver_sec_scenarios_primary_cap.csv",
    "receiver_sec_gate_counts.csv",
    "fixed_loss_sensitivity.csv",
    "fixed_loss_gate_counts.csv",
    "summary_direct_eo_low_voltage_study_v1.md",
    "analysis_assumptions.json",
    "figures/01_low_voltage_tw_j_feasibility.png",
    "figures/01_low_voltage_tw_j_feasibility.pdf",
    "figures/02_required_voltage_tw_j.png",
    "figures/02_required_voltage_tw_j.pdf",
    "figures/03_high_tw_negative_controls.png",
    "figures/03_high_tw_negative_controls.pdf",
    "figures/04_modern_comparator_margin.png",
    "figures/04_modern_comparator_margin.pdf",
    "figures/05_fixed_loss_voltage_sensitivity.png",
    "figures/05_fixed_loss_voltage_sensitivity.pdf",
    "figures/06_gate_waterfall.png",
    "figures/06_gate_waterfall.pdf",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--source-register",
        type=Path,
        default=DEFAULT_ROOT / "physics" / "joint_material_operating_gate_register.csv",
    )
    parser.add_argument(
        "--source-assumptions",
        type=Path,
        default=DEFAULT_ROOT / "physics" / "assumptions_v53.csv",
    )
    parser.add_argument(
        "--source-provenance",
        type=Path,
        default=DEFAULT_ROOT / "source_generator_provenance.json",
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_ROOT / "analysis")
    parser.add_argument("--require-empty-out-dir", action="store_true")
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def provenance_record(path: Path) -> dict[str, object]:
    resolved = path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"Required provenance file missing: {resolved}")
    return {
        "path": str(resolved),
        "sha256": sha256_file(resolved),
        "size_bytes": resolved.stat().st_size,
    }


def load_json(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise FileNotFoundError(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def as_bool(values: pd.Series) -> pd.Series:
    if values.dtype == bool:
        return values.fillna(False).astype(bool)
    if pd.api.types.is_numeric_dtype(values):
        return values.fillna(0).astype(float).astype(bool)
    return values.astype(str).str.strip().str.lower().isin({"true", "1", "yes"})


def expected_grid_counts(config: dict[str, object]) -> tuple[int, int]:
    grid = config["grid"]
    if not isinstance(grid, dict):
        raise ValueError("Config grid must be an object")
    physical = math.prod(len(grid[name]) for name in PHYSICAL_KEYS)
    cap_rows = physical * len(grid["cell_voltage_caps_v"])
    return int(physical), int(cap_rows)


def validate_config(config: dict[str, object]) -> None:
    if config.get("schema_version") != 1:
        raise ValueError("Unsupported low-voltage config schema")
    grid = config.get("grid")
    gates = config.get("gates")
    ledgers = config.get("energy_ledgers")
    decomp = config.get("voltage_decomposition")
    if not all(isinstance(item, dict) for item in (grid, gates, ledgers, decomp)):
        raise ValueError("Config lacks grid/gates/energy_ledgers/voltage_decomposition")
    for name in AXIS_TO_COLUMN:
        values = grid.get(name)
        if not isinstance(values, list) or not values or any(float(v) <= 0 for v in values):
            raise ValueError(f"Invalid positive grid axis: {name}")
        if len(set(map(float, values))) != len(values):
            raise ValueError(f"Duplicate values in grid axis: {name}")
    caps = list(map(float, grid["cell_voltage_caps_v"]))
    if max(caps) > 2.0 + EPS:
        raise ValueError("This study forbids acceptance caps above 2 V")
    if float(gates["primary_hard_voltage_cap_v"]) != max(caps):
        raise ValueError("Primary hard cap must equal the largest tested <=2 V cap")
    if gates.get("engineering_current_density_limit_a_m2") is not None:
        raise ValueError("No current-density acceptance limit is allowed")
    if not math.isclose(
        float(decomp["baseline_combined_fixed_loss_v"]),
        float(decomp["baseline_electrode_overpotential_v"])
        + float(decomp["baseline_interface_voltage_v"]),
        rel_tol=0.0,
        abs_tol=EPS,
    ):
        raise ValueError("Baseline fixed-loss decomposition does not sum")


def load_and_validate_reference(config: dict[str, object]) -> tuple[float, dict[str, object]]:
    ledger = config["energy_ledgers"]
    source = Path(str(ledger["modern_ac_erv_reference_source"]))
    payload = load_json(source)
    field = str(ledger["modern_ac_erv_reference_json_field"])
    if field not in payload:
        raise ValueError(f"Modern comparator source lacks JSON field {field}")
    actual = float(payload[field])
    declared = float(ledger["modern_ac_erv_reference_kw"])
    if not math.isclose(actual, declared, rel_tol=0.0, abs_tol=1.0e-9):
        raise ValueError(
            f"Modern comparator mismatch: config={declared:.12g}, source={actual:.12g}"
        )
    return actual, provenance_record(source)


def load_source(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(path)
    frame = pd.read_csv(path, low_memory=False)
    missing = REQUIRED_COLUMNS - set(frame.columns)
    if missing:
        raise ValueError("Source register lacks: " + ", ".join(sorted(missing)))
    for column in BOOLEAN_COLUMNS & set(frame.columns):
        frame[column] = as_bool(frame[column])
    numeric = (REQUIRED_COLUMNS | set(PHYSICAL_KEYS)) - BOOLEAN_COLUMNS
    for column in numeric & set(frame.columns):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    essential = [*PHYSICAL_KEYS, "cell_voltage_cap_tested_v", "cell_voltage_required_max_v"]
    if frame[essential].isna().any().any():
        raise ValueError("Source register contains missing essential coordinates/results")
    return frame


def validate_grid(frame: pd.DataFrame, config: dict[str, object]) -> dict[str, object]:
    grid = config["grid"]
    checks: list[dict[str, object]] = []
    for axis, column in AXIS_TO_COLUMN.items():
        expected = np.asarray(sorted(map(float, grid[axis])), dtype=float)
        actual = np.asarray(sorted(frame[column].unique()), dtype=float)
        passed = expected.shape == actual.shape and np.allclose(
            expected, actual, rtol=0.0, atol=EPS
        )
        checks.append(
            {
                "axis": axis,
                "passed": bool(passed),
                "expected": expected.tolist(),
                "actual": actual.tolist(),
            }
        )
        if not passed:
            raise ValueError(f"Source axis differs from config: {axis}")
    expected_physical, expected_rows = expected_grid_counts(config)
    observed_physical = frame[PHYSICAL_KEYS].drop_duplicates().shape[0]
    if len(frame) != expected_rows or observed_physical != expected_physical:
        raise ValueError(
            f"Grid count mismatch: rows {len(frame)}/{expected_rows}, "
            f"physical {observed_physical}/{expected_physical}"
        )
    copies = frame.groupby(PHYSICAL_KEYS, dropna=False).size()
    expected_copies = len(grid["cell_voltage_caps_v"])
    if not copies.eq(expected_copies).all():
        raise ValueError("Not every physical coordinate has every voltage-cap copy")
    invariant = [
        "active_area_m2",
        "cell_voltage_required_max_v",
        "cell_voltage_required_mean_v",
        "conditional_known_electric_saving_kw",
        "known_electric_total_kw",
        "process_surface_activity_min",
        "strict_physical_and_architecture_pass",
    ]
    for column in invariant:
        if frame.groupby(PHYSICAL_KEYS, dropna=False)[column].nunique(dropna=False).max() != 1:
            raise ValueError(f"Cap copies disagree on invariant {column}")
    return {
        "axis_checks": checks,
        "expected_physical_coordinates": expected_physical,
        "observed_physical_coordinates": observed_physical,
        "expected_cap_rows": expected_rows,
        "observed_cap_rows": len(frame),
        "cap_copies_per_physical_coordinate": expected_copies,
    }


def augment_cap_register(
    frame: pd.DataFrame, config: dict[str, object], modern_reference_kw: float
) -> pd.DataFrame:
    result = frame.copy()
    gates = config["gates"]
    ledgers = config["energy_ledgers"]
    hard_area = float(config["source_model"]["hard_area_screen_m2"])
    robust_activity = float(gates["robust_process_surface_activity_min"])
    preferred_voltage = float(gates["preferred_maximum_local_voltage_v"])
    native_threshold = float(gates["native_historical_margin_diagnostic_kw"])

    result["native_historical_no_erv_margin_kw"] = result[
        "conditional_known_electric_saving_kw"
    ]
    result["native_historical_reference_kw"] = float(
        ledgers["native_historical_reference_kw"]
    )
    result["modern_ac_erv_reference_kw"] = modern_reference_kw
    result["known_direct_eo_path_power_before_receiver_kw"] = result[
        "known_electric_total_kw"
    ]
    result["modern_comparator_margin_before_receiver_kw"] = (
        modern_reference_kw - result["known_direct_eo_path_power_before_receiver_kw"]
    )
    result["transport_intensity_reference_twj_a_m2"] = (
        result["transport_number_reference_t_w"] * result["current_density_a_m2"]
    )
    result["hard_voltage_cap_recomputed_pass"] = (
        result["cell_voltage_required_max_v"]
        <= result["cell_voltage_cap_tested_v"] + EPS
    )
    if not result["hard_voltage_cap_recomputed_pass"].equals(
        result["selected_voltage_cap_pass"]
    ):
        raise ValueError("Recomputed voltage-cap semantics disagree with V53")
    result["hard_area_recomputed_pass"] = result["active_area_m2"] <= hard_area + EPS
    if not result["hard_area_recomputed_pass"].equals(result["hard_area_cap_pass"]):
        raise ValueError("Recomputed hard-area semantics disagree with V53")
    result["robust_process_activity_pass"] = (
        result["process_surface_activity_min"] >= robust_activity - EPS
    )
    result["preferred_maximum_voltage_pass"] = (
        result["cell_voltage_required_max_v"] <= preferred_voltage + EPS
    )
    result["membrane_operating_pass_at_cap"] = (
        result["strict_physical_and_architecture_pass"]
        & result["hard_area_recomputed_pass"]
        & result["robust_process_activity_pass"]
        & result["hard_voltage_cap_recomputed_pass"]
    )
    result["preferred_membrane_operating_pass"] = (
        result["strict_physical_and_architecture_pass"]
        & result["hard_area_recomputed_pass"]
        & result["robust_process_activity_pass"]
        & result["preferred_maximum_voltage_pass"]
    )
    result["native_historical_425_diagnostic_pass"] = (
        result["membrane_operating_pass_at_cap"]
        & (result["native_historical_no_erv_margin_kw"] >= native_threshold - EPS)
    )
    result["modern_comparator_positive_before_receiver_pass"] = (
        result["membrane_operating_pass_at_cap"]
        & (result["modern_comparator_margin_before_receiver_kw"] > EPS)
    )
    return result


def deduplicate_physical(frame: pd.DataFrame) -> pd.DataFrame:
    physical = (
        frame.sort_values([*PHYSICAL_KEYS, "cell_voltage_cap_tested_v"], kind="mergesort")
        .drop_duplicates(PHYSICAL_KEYS, keep="first")
        .copy()
    )
    drop = [
        "cell_voltage_cap_tested_v",
        "cell_voltage_headroom_v",
        "selected_voltage_cap_pass",
        "hard_voltage_cap_recomputed_pass",
        "membrane_operating_pass_at_cap",
        "native_historical_425_diagnostic_pass",
        "modern_comparator_positive_before_receiver_pass",
        "strict_v53_pass",
        "v53_failed_hard_gates",
    ]
    return physical.drop(columns=[column for column in drop if column in physical])


def gate_counts(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    sequential = [
        ("all_coordinates", pd.Series(True, index=frame.index)),
        ("strict_physical_architecture", frame["strict_physical_and_architecture_pass"]),
        (
            "plus_area_le_5000_m2",
            frame["strict_physical_and_architecture_pass"]
            & frame["hard_area_recomputed_pass"],
        ),
        (
            "plus_process_activity_ge_0p17",
            frame["strict_physical_and_architecture_pass"]
            & frame["hard_area_recomputed_pass"]
            & frame["robust_process_activity_pass"],
        ),
        ("plus_selected_voltage_cap", frame["membrane_operating_pass_at_cap"]),
        ("native_historical_margin_ge_425", frame["native_historical_425_diagnostic_pass"]),
        (
            "modern_comparator_positive_before_receiver",
            frame["modern_comparator_positive_before_receiver_pass"],
        ),
    ]
    for cap, group in frame.groupby("cell_voltage_cap_tested_v", sort=True):
        for order, (name, mask) in enumerate(sequential):
            local = mask.loc[group.index]
            rows.append(
                {
                    "cell_voltage_cap_tested_v": float(cap),
                    "gate_order": order,
                    "gate": name,
                    "passing_coordinates": int(local.sum()),
                    "evaluated_coordinates": len(group),
                    "pass_fraction": float(local.mean()),
                }
            )
    return pd.DataFrame(rows)


def receiver_scenarios(
    primary: pd.DataFrame, sec_values: Iterable[float]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    frames: list[pd.DataFrame] = []
    for sec in map(float, sec_values):
        scenario = primary[
            PHYSICAL_KEYS
            + [
                "cell_voltage_cap_tested_v",
                "cell_voltage_required_max_v",
                "active_area_m2",
                "process_surface_activity_min",
                "receiver_sink_net_kg_h",
                "native_historical_no_erv_margin_kw",
                "modern_comparator_margin_before_receiver_kw",
                "membrane_operating_pass_at_cap",
                "preferred_membrane_operating_pass",
            ]
        ].copy()
        scenario["receiver_sec_kwh_kg"] = sec
        scenario["receiver_power_kw"] = scenario["receiver_sink_net_kg_h"] * sec
        scenario["native_historical_margin_after_receiver_kw"] = (
            scenario["native_historical_no_erv_margin_kw"] - scenario["receiver_power_kw"]
        )
        scenario["modern_comparator_margin_after_receiver_kw"] = (
            scenario["modern_comparator_margin_before_receiver_kw"]
            - scenario["receiver_power_kw"]
        )
        scenario["modern_comparator_positive_after_receiver_pass"] = (
            scenario["membrane_operating_pass_at_cap"]
            & (scenario["modern_comparator_margin_after_receiver_kw"] > EPS)
        )
        frames.append(scenario)
    expanded = pd.concat(frames, ignore_index=True)
    rows = []
    for sec, group in expanded.groupby("receiver_sec_kwh_kg", sort=True):
        operating = group["membrane_operating_pass_at_cap"]
        rows.append(
            {
                "cell_voltage_cap_tested_v": float(group["cell_voltage_cap_tested_v"].iloc[0]),
                "receiver_sec_kwh_kg": float(sec),
                "evaluated_coordinates": len(group),
                "membrane_operating_pass_coordinates": int(operating.sum()),
                "modern_positive_after_receiver_coordinates": int(
                    group["modern_comparator_positive_after_receiver_pass"].sum()
                ),
                "best_modern_margin_after_receiver_kw": float(
                    group.loc[operating, "modern_comparator_margin_after_receiver_kw"].max()
                )
                if operating.any()
                else np.nan,
            }
        )
    return expanded, pd.DataFrame(rows)


def fixed_loss_scenarios(
    physical: pd.DataFrame, config: dict[str, object], modern_reference_kw: float
) -> tuple[pd.DataFrame, pd.DataFrame]:
    decomp = config["voltage_decomposition"]
    cap = float(config["gates"]["primary_hard_voltage_cap_v"])
    preferred = float(config["gates"]["preferred_maximum_local_voltage_v"])
    robust_activity = float(config["gates"]["robust_process_surface_activity_min"])
    baseline_fixed = float(decomp["baseline_combined_fixed_loss_v"])
    frames: list[pd.DataFrame] = []
    for fixed in map(float, decomp["combined_fixed_loss_scenarios_v"]):
        scenario = physical[
            PHYSICAL_KEYS
            + [
                "active_area_m2",
                "cell_voltage_required_mean_v",
                "cell_voltage_required_max_v",
                "eo_grid_power_kw",
                "known_electric_total_kw",
                "process_surface_activity_min",
                "strict_physical_and_architecture_pass",
                "hard_area_recomputed_pass",
                "receiver_sink_net_kg_h",
                "voltage_electrode_overpotential_v",
                "voltage_interface_v",
                "voltage_series_ohmic_v",
                "voltage_membrane_ohmic_max_v",
                "voltage_water_activity_reversible_max_v",
            ]
        ].copy()
        scenario["combined_fixed_loss_scenario_v"] = fixed
        scenario["scenario_required_mean_voltage_v"] = (
            scenario["cell_voltage_required_mean_v"] - baseline_fixed + fixed
        )
        scenario["scenario_required_max_voltage_v"] = (
            scenario["cell_voltage_required_max_v"] - baseline_fixed + fixed
        )
        ratio = scenario["scenario_required_mean_voltage_v"] / scenario[
            "cell_voltage_required_mean_v"
        ]
        scenario["scenario_eo_grid_power_kw"] = scenario["eo_grid_power_kw"] * ratio
        scenario["scenario_known_direct_eo_path_power_before_receiver_kw"] = (
            scenario["known_electric_total_kw"]
            - scenario["eo_grid_power_kw"]
            + scenario["scenario_eo_grid_power_kw"]
        )
        scenario["scenario_modern_comparator_margin_before_receiver_kw"] = (
            modern_reference_kw
            - scenario["scenario_known_direct_eo_path_power_before_receiver_kw"]
        )
        base = (
            scenario["strict_physical_and_architecture_pass"]
            & scenario["hard_area_recomputed_pass"]
            & (scenario["process_surface_activity_min"] >= robust_activity - EPS)
        )
        scenario["scenario_membrane_operating_pass_2v"] = base & (
            scenario["scenario_required_max_voltage_v"] <= cap + EPS
        )
        scenario["scenario_preferred_voltage_pass_1p8v"] = base & (
            scenario["scenario_required_max_voltage_v"] <= preferred + EPS
        )
        scenario["scenario_modern_positive_before_receiver_pass"] = (
            scenario["scenario_membrane_operating_pass_2v"]
            & (scenario["scenario_modern_comparator_margin_before_receiver_kw"] > EPS)
        )
        frames.append(scenario)
    expanded = pd.concat(frames, ignore_index=True)
    summary_rows = []
    for fixed, group in expanded.groupby("combined_fixed_loss_scenario_v", sort=True):
        operating = group["scenario_membrane_operating_pass_2v"]
        summary_rows.append(
            {
                "combined_fixed_loss_scenario_v": float(fixed),
                "evaluated_coordinates": len(group),
                "membrane_operating_pass_2v_coordinates": int(operating.sum()),
                "preferred_voltage_pass_1p8v_coordinates": int(
                    group["scenario_preferred_voltage_pass_1p8v"].sum()
                ),
                "modern_positive_before_receiver_coordinates": int(
                    group["scenario_modern_positive_before_receiver_pass"].sum()
                ),
                "best_modern_margin_before_receiver_kw": float(
                    group.loc[operating, "scenario_modern_comparator_margin_before_receiver_kw"].max()
                )
                if operating.any()
                else np.nan,
            }
        )
    return expanded, pd.DataFrame(summary_rows)


def aggregate_tw_j(primary: pd.DataFrame, receiver: pd.DataFrame) -> pd.DataFrame:
    receiver_010 = receiver[np.isclose(receiver["receiver_sec_kwh_kg"], 0.10)].copy()
    rows = []
    keys = ["transport_number_reference_t_w", "current_density_a_m2"]
    for key, group in primary.groupby(keys, sort=True):
        tw, current = map(float, key)
        rgroup = receiver_010[
            np.isclose(receiver_010["transport_number_reference_t_w"], tw)
            & np.isclose(receiver_010["current_density_a_m2"], current)
        ]
        operating = group["membrane_operating_pass_at_cap"]
        rows.append(
            {
                "transport_number_reference_t_w": tw,
                "current_density_a_m2": current,
                "evaluated_diffusivity_levels": len(group),
                "membrane_operating_pass_levels": int(operating.sum()),
                "membrane_operating_pass_fraction": float(operating.mean()),
                "preferred_1p8v_pass_levels": int(
                    group["preferred_membrane_operating_pass"].sum()
                ),
                "minimum_required_max_voltage_v": float(
                    group["cell_voltage_required_max_v"].min()
                ),
                "maximum_process_surface_activity_min": float(
                    group["process_surface_activity_min"].max()
                ),
                "best_native_historical_margin_kw": float(
                    group["native_historical_no_erv_margin_kw"].max()
                ),
                "best_modern_margin_before_receiver_kw": float(
                    group.loc[operating, "modern_comparator_margin_before_receiver_kw"].max()
                )
                if operating.any()
                else np.nan,
                "best_modern_margin_after_receiver_0p10_kw": float(
                    rgroup.loc[
                        rgroup["membrane_operating_pass_at_cap"],
                        "modern_comparator_margin_after_receiver_kw",
                    ].max()
                )
                if rgroup["membrane_operating_pass_at_cap"].any()
                else np.nan,
            }
        )
    return pd.DataFrame(rows)


def aggregate_tw(primary: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for tw, group in primary.groupby("transport_number_reference_t_w", sort=True):
        operating = group["membrane_operating_pass_at_cap"]
        rows.append(
            {
                "transport_number_reference_t_w": float(tw),
                "evaluated_coordinates": len(group),
                "membrane_operating_pass_coordinates": int(operating.sum()),
                "preferred_1p8v_pass_coordinates": int(
                    group["preferred_membrane_operating_pass"].sum()
                ),
                "minimum_required_max_voltage_v": float(
                    group["cell_voltage_required_max_v"].min()
                ),
                "maximum_process_surface_activity_min": float(
                    group["process_surface_activity_min"].max()
                ),
                "best_modern_margin_before_receiver_kw": float(
                    group.loc[operating, "modern_comparator_margin_before_receiver_kw"].max()
                )
                if operating.any()
                else np.nan,
            }
        )
    return pd.DataFrame(rows)


def style() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": WHITE,
            "axes.facecolor": WHITE,
            "axes.edgecolor": SLATE,
            "axes.labelcolor": INK,
            "xtick.color": INK,
            "ytick.color": INK,
            "text.color": INK,
            "font.size": 9.5,
            "axes.titlesize": 11,
            "axes.titleweight": "bold",
            "figure.titlesize": 14,
            "figure.titleweight": "bold",
        }
    )


def save_figure(fig: plt.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path.with_suffix(".png"), dpi=220, bbox_inches="tight")
    fig.savefig(path.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)


def heatmap(
    ax: plt.Axes,
    data: pd.DataFrame,
    value: str,
    title: str,
    cmap,
    vmin: float | None = None,
    vmax: float | None = None,
    fmt: str | None = None,
) -> object:
    pivot = data.pivot(
        index="current_density_a_m2",
        columns="transport_number_reference_t_w",
        values=value,
    ).sort_index(ascending=True)
    image = ax.imshow(
        pivot.to_numpy(float),
        aspect="auto",
        origin="lower",
        cmap=cmap,
        vmin=vmin,
        vmax=vmax,
    )
    ax.set_xticks(np.arange(len(pivot.columns)))
    ax.set_xticklabels([f"{x:g}" for x in pivot.columns], rotation=55, ha="right")
    ax.set_yticks(np.arange(len(pivot.index)))
    ax.set_yticklabels([f"{x:g}" for x in pivot.index])
    ax.set_xlabel(r"Reference transport number $t_w$")
    ax.set_ylabel("Current density [A/m²]")
    ax.set_title(title)
    if fmt:
        for row in range(pivot.shape[0]):
            for col in range(pivot.shape[1]):
                val = pivot.iloc[row, col]
                if np.isfinite(val):
                    ax.text(col, row, format(val, fmt), ha="center", va="center", fontsize=6.2)
    return image


def plot_feasibility(tw_j: pd.DataFrame, path: Path) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(13.0, 8.4), constrained_layout=True)
    image = heatmap(
        axes[0], tw_j, "membrane_operating_pass_fraction",
        "2.0 V cap: share of 12 diffusivity levels passing physics + area + activity",
        PASS_CMAP, 0.0, 1.0, ".2f",
    )
    fig.colorbar(image, ax=axes[0], label="Pass fraction")
    image = heatmap(
        axes[1], tw_j, "preferred_1p8v_pass_levels",
        "Preferred <=1.8 V screen: number of passing diffusivity levels",
        PASS_CMAP, 0.0, 12.0, ".0f",
    )
    fig.colorbar(image, ax=axes[1], label="Passing levels / 12")
    fig.suptitle("Direct EO low-voltage operating region (current-controlled inverse design)")
    fig.text(
        0.5, -0.012,
        "No current-density acceptance limit. Receiver maintenance is still 0 kW in the source physics.",
        ha="center", color=RED, fontsize=9,
    )
    save_figure(fig, path)


def plot_required_voltage(tw_j: pd.DataFrame, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(13.0, 5.2), constrained_layout=True)
    clipped = tw_j.copy()
    clipped["minimum_required_max_voltage_v_plot"] = clipped[
        "minimum_required_max_voltage_v"
    ].clip(upper=8.0)
    image = heatmap(
        ax, clipped, "minimum_required_max_voltage_v_plot",
        "Minimum required local maximum voltage across diffusivity (values clipped at 8 V)",
        "magma_r", 0.85, 8.0, ".1f",
    )
    fig.colorbar(image, ax=ax, label="Minimum Vmax [V]")
    fig.suptitle("Why high transport number disappears under a 2 V ceiling")
    save_figure(fig, path)


def plot_high_tw(primary: pd.DataFrame, config: dict[str, object], path: Path) -> None:
    threshold = float(config["gates"]["high_transport_negative_control_min_t_w"])
    high = primary[primary["transport_number_reference_t_w"] >= threshold].copy()
    best = (
        high.sort_values("cell_voltage_required_max_v")
        .groupby(["transport_number_reference_t_w", "current_density_a_m2"], as_index=False)
        .first()
    )
    currents = sorted(best["current_density_a_m2"].unique())
    colours = plt.cm.viridis(np.linspace(0.05, 0.95, len(currents)))
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.6), constrained_layout=True)
    for colour, current in zip(colours, currents):
        group = best[np.isclose(best["current_density_a_m2"], current)]
        axes[0].plot(
            group["transport_number_reference_t_w"],
            group["cell_voltage_required_max_v"],
            marker="o", ms=3.5, color=colour, label=f"j={current:g}",
        )
        axes[1].plot(
            group["transport_number_reference_t_w"],
            group["process_surface_activity_min"],
            marker="o", ms=3.5, color=colour,
        )
    axes[0].axhline(2.0, color=RED, linestyle="--", label="2.0 V hard cap")
    axes[0].axhline(1.8, color=ORANGE, linestyle=":", label="1.8 V preferred")
    axes[1].axhline(0.17, color=RED, linestyle="--", label="a_process,min=0.17")
    axes[0].set(xlabel=r"Reference $t_w$", ylabel="Best-case required Vmax [V]", yscale="log")
    axes[1].set(xlabel=r"Reference $t_w$", ylabel="Best-case process surface activity")
    axes[0].legend(fontsize=7, ncol=2)
    axes[1].legend(fontsize=8)
    for ax in axes:
        ax.grid(True, alpha=0.25)
    fig.suptitle("High-tw controls remain in the grid and fail visibly")
    save_figure(fig, path)


def plot_modern_margin(tw_j: pd.DataFrame, path: Path) -> None:
    fig, axes = plt.subplots(3, 1, figsize=(13.0, 11.0), constrained_layout=True)
    panels = [
        ("best_modern_margin_before_receiver_kw", "Before receiver energy"),
        ("best_modern_margin_after_receiver_0p10_kw", "After receiver SEC = 0.10 kWh/kg"),
        ("best_native_historical_margin_kw", "Native historical no-ERV margin (regression only)"),
    ]
    ranges = [(-650.0, 150.0), (-1000.0, 100.0), (0.0, 600.0)]
    for ax, (column, title), (vmin, vmax) in zip(axes, panels, ranges):
        image = heatmap(ax, tw_j, column, title, MARGIN_CMAP, vmin, vmax, ".0f")
        fig.colorbar(image, ax=ax, label="Margin [kW]")
    fig.suptitle("Two ledgers kept separate: modern AC+ERV versus native historical reference")
    fig.text(
        0.5, -0.008,
        "Modern comparator = 543.740564 kW. Native margin is not a system-saving claim.",
        ha="center", color=RED, fontsize=9,
    )
    save_figure(fig, path)


def plot_fixed_loss(
    fixed_counts: pd.DataFrame, physical: pd.DataFrame, config: dict[str, object], path: Path
) -> None:
    decomp = config["voltage_decomposition"]
    fig, axes = plt.subplots(1, 2, figsize=(11.8, 4.4), constrained_layout=True)
    x = fixed_counts["combined_fixed_loss_scenario_v"]
    axes[0].plot(x, fixed_counts["membrane_operating_pass_2v_coordinates"], marker="o", label="<=2.0 V")
    axes[0].plot(x, fixed_counts["preferred_voltage_pass_1p8v_coordinates"], marker="s", label="<=1.8 V")
    axes[0].plot(x, fixed_counts["modern_positive_before_receiver_coordinates"], marker="^", label="modern margin >0")
    axes[0].axvline(float(decomp["baseline_combined_fixed_loss_v"]), color=RED, linestyle="--", label="baseline 0.85 V")
    axes[0].set(xlabel="Combined electrode + interface loss [V]", ylabel="Passing physical coordinates")
    axes[0].legend(fontsize=8)
    components = [
        ("Electrode", float(decomp["baseline_electrode_overpotential_v"]), ORANGE),
        ("Interface", float(decomp["baseline_interface_voltage_v"]), RED),
        ("Remaining budget to 2 V", 2.0 - float(decomp["baseline_combined_fixed_loss_v"]), TEAL),
    ]
    axes[1].bar([name for name, _, _ in components], [value for _, value, _ in components], color=[c for _, _, c in components])
    axes[1].set_ylabel("Voltage [V]")
    axes[1].set_title("Baseline fixed losses consume 42.5% of the 2 V budget")
    axes[1].tick_params(axis="x", rotation=20)
    for ax in axes:
        ax.grid(True, axis="y", alpha=0.25)
    fig.suptitle("Fixed-loss sensitivity (post-process only; transport held fixed)")
    save_figure(fig, path)


def plot_waterfall(counts: pd.DataFrame, cap: float, path: Path) -> None:
    data = counts[np.isclose(counts["cell_voltage_cap_tested_v"], cap)].sort_values("gate_order")
    labels = [
        "All", "Strict physics", "+ area", "+ activity", "+ voltage",
        "Native >=425", "Modern >0",
    ]
    values = data["passing_coordinates"].to_numpy(int)
    colours = [GREY, SLATE, TEAL, TEAL_DARK, NAVY, ORANGE, RED]
    fig, ax = plt.subplots(figsize=(10.8, 4.5), constrained_layout=True)
    bars = ax.bar(np.arange(len(values)), values, color=colours)
    ax.set_xticks(np.arange(len(values)))
    ax.set_xticklabels(labels, rotation=22, ha="right")
    ax.set_ylabel("Coordinates")
    ax.set_title(f"Sequential gate waterfall at {cap:g} V")
    for bar, value in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, value, f"{value:,}", ha="center", va="bottom", fontsize=8)
    ax.grid(True, axis="y", alpha=0.25)
    fig.suptitle("Physical membrane gate and energy comparators are deliberately separate")
    save_figure(fig, path)


def write_summary(
    path: Path,
    config: dict[str, object],
    cap_register: pd.DataFrame,
    physical: pd.DataFrame,
    counts: pd.DataFrame,
    tw_summary: pd.DataFrame,
    receiver_counts: pd.DataFrame,
    fixed_counts: pd.DataFrame,
) -> None:
    primary_cap = float(config["gates"]["primary_hard_voltage_cap_v"])
    primary = cap_register[np.isclose(cap_register["cell_voltage_cap_tested_v"], primary_cap)]
    operating = primary[primary["membrane_operating_pass_at_cap"]]
    preferred = primary[primary["preferred_membrane_operating_pass"]]
    native = primary[primary["native_historical_425_diagnostic_pass"]]
    modern = primary[primary["modern_comparator_positive_before_receiver_pass"]]
    high_min = float(config["gates"]["high_transport_negative_control_min_t_w"])
    high = primary[primary["transport_number_reference_t_w"] >= high_min]
    highest_pass_tw = (
        float(operating["transport_number_reference_t_w"].max()) if not operating.empty else np.nan
    )
    high_min_voltage = float(high["cell_voltage_required_max_v"].min())
    best_modern = (
        float(operating["modern_comparator_margin_before_receiver_kw"].max())
        if not operating.empty
        else np.nan
    )
    receiver_lines = []
    for _, row in receiver_counts.iterrows():
        receiver_lines.append(
            f"| {row['receiver_sec_kwh_kg']:.3f} | "
            f"{int(row['modern_positive_after_receiver_coordinates'])} | "
            f"{row['best_modern_margin_after_receiver_kw']:.3f} |"
        )
    fixed_lines = []
    for _, row in fixed_counts.iterrows():
        fixed_lines.append(
            f"| {row['combined_fixed_loss_scenario_v']:.2f} | "
            f"{int(row['membrane_operating_pass_2v_coordinates'])} | "
            f"{int(row['modern_positive_before_receiver_coordinates'])} | "
            f"{row['best_modern_margin_before_receiver_kw']:.3f} |"
        )
    lines = [
        "# Direct EO <=2 V study v1",
        "",
        "## Scope",
        "",
        f"- {len(physical):,} current-controlled physical coordinates; {len(cap_register):,} cap-expanded rows.",
        "- All acceptance caps are <=2 V. The internal 12 V calculation ceiling only preserves failed rows.",
        "- Current density is sampled from 5 to 100 A/m2; no current-density acceptance limit is applied.",
        "- High transport numbers through t_w=200 are retained as explicit negative controls.",
        "- The receiver removes water at zero power in the source physics; full-system status is UNKNOWN.",
        "",
        "## Primary 2 V result",
        "",
        f"- Membrane operating gate (strict physics + area <=5000 m2 + a_process,min>=0.17 + Vmax<=2 V): **{len(operating):,} / {len(primary):,}**.",
        f"- Preferred Vmax<=1.8 V membrane gate: **{len(preferred):,}**.",
        f"- Native historical >=425 kW diagnostic: **{len(native):,}**. This is not system saving.",
        f"- Positive margin versus modern AC+ERV before receiver energy: **{len(modern):,}**.",
        f"- Highest passing reference transport number: **{highest_pass_tw:g}**.",
        f"- Minimum required Vmax among t_w>={high_min:g} controls: **{high_min_voltage:.3f} V**.",
        f"- Best modern-comparator margin among membrane-gate passes before receiver: **{best_modern:.3f} kW**.",
        "",
        "## Energy ledgers",
        "",
        f"- Native historical no-ERV reference: {config['energy_ledgers']['native_historical_reference_kw']:.3f} kW. Retained for regression only.",
        f"- Modern AC+ERV comparator: {config['energy_ledgers']['modern_ac_erv_reference_kw']:.6f} kW, hash-bound to the declared baseline reproduction audit.",
        "- Modern margin = modern reference - known direct-EO path power - receiver power. It remains conditional because the receiver mechanism is unresolved.",
        "",
        "| Receiver SEC [kWh/kg] | Modern-positive coordinates | Best modern margin [kW] |",
        "|---:|---:|---:|",
        *receiver_lines,
        "",
        "## Combined electrode + interface loss sensitivity",
        "",
        "Transport, activity, current and membrane ASR are held fixed. These are deterministic voltage-loss scenarios, not probabilities.",
        "",
        "| Fixed loss [V] | 2 V membrane passes | Modern-positive | Best modern margin [kW] |",
        "|---:|---:|---:|---:|",
        *fixed_lines,
        "",
        "## Interpretation",
        "",
        "A voltage cap is a screen on calculated maximum required local voltage in the current-controlled V50/V53 model. It is not a fixed-voltage device replay. High t_w reduces charge/area demand but multiplies the reversible water-activity voltage per unit charge; the resulting voltage/surface feedback is why the high-t_w controls can fail below 2 V.",
        "",
        "Marginal inverse-design coordinates are not a real material vector. At fixed thickness, diffusivity scale maps the D/L direction; reference t_w maps to hydration-dependent local drag.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def audit_semantics(
    config: dict[str, object],
    raw: pd.DataFrame,
    cap_register: pd.DataFrame,
    physical: pd.DataFrame,
    receiver: pd.DataFrame,
    fixed: pd.DataFrame,
    grid_audit: dict[str, object],
) -> list[dict[str, object]]:
    primary_cap = float(config["gates"]["primary_hard_voltage_cap_v"])
    primary = cap_register[np.isclose(cap_register["cell_voltage_cap_tested_v"], primary_cap)]
    checks = [
        {"check": "all_acceptance_caps_at_or_below_2v", "passed": bool(cap_register["cell_voltage_cap_tested_v"].max() <= 2.0 + EPS)},
        {"check": "exact_physical_grid_count", "passed": bool(len(physical) == grid_audit["expected_physical_coordinates"])},
        {"check": "exact_cap_expanded_count", "passed": bool(len(cap_register) == grid_audit["expected_cap_rows"])},
        {"check": "no_current_density_acceptance_limit", "passed": config["gates"]["engineering_current_density_limit_a_m2"] is None},
        {"check": "low_currents_present", "passed": bool(physical["current_density_a_m2"].min() == 5.0)},
        {"check": "high_tw_controls_present", "passed": bool(physical["transport_number_reference_t_w"].max() == 200.0 and (physical["transport_number_reference_t_w"] > 100).any())},
        {"check": "source_receiver_energy_is_zero", "passed": bool(np.allclose(raw["receiver_sink_energy_kw_assumed"], 0.0, rtol=0.0, atol=EPS))},
        {"check": "native_margin_alias_exact", "passed": bool(np.allclose(cap_register["native_historical_no_erv_margin_kw"], cap_register["conditional_known_electric_saving_kw"], rtol=0.0, atol=EPS))},
        {"check": "modern_before_receiver_identity", "passed": bool(np.allclose(cap_register["modern_comparator_margin_before_receiver_kw"], cap_register["modern_ac_erv_reference_kw"] - cap_register["known_direct_eo_path_power_before_receiver_kw"], rtol=0.0, atol=EPS))},
        {"check": "receiver_after_margin_identity", "passed": bool(np.allclose(receiver["modern_comparator_margin_after_receiver_kw"], receiver["modern_comparator_margin_before_receiver_kw"] - receiver["receiver_power_kw"], rtol=0.0, atol=EPS))},
        {"check": "baseline_fixed_loss_components_are_0p85v", "passed": bool(np.allclose(physical["voltage_electrode_overpotential_v"] + physical["voltage_interface_v"], 0.85, rtol=0.0, atol=EPS))},
        {"check": "fixed_loss_baseline_reproduces_voltage", "passed": bool(np.allclose(fixed.loc[np.isclose(fixed["combined_fixed_loss_scenario_v"], 0.85), "scenario_required_max_voltage_v"], physical.sort_values(PHYSICAL_KEYS)["cell_voltage_required_max_v"].to_numpy(), rtol=0.0, atol=1e-8))},
        {"check": "full_system_claim_forbidden", "passed": config["claim_boundary"]["full_system_claim_allowed"] is False},
        {"check": "primary_cap_has_one_row_per_physical_coordinate", "passed": bool(len(primary) == len(physical))},
    ]
    return checks


def run_analysis(args: argparse.Namespace) -> dict[str, object]:
    if args.require_empty_out_dir and args.out_dir.exists() and any(args.out_dir.iterdir()):
        raise ValueError(f"Refusing non-empty output directory: {args.out_dir}")
    config = load_json(args.config)
    validate_config(config)
    modern_reference, modern_source_record = load_and_validate_reference(config)
    source_provenance = load_json(args.source_provenance)
    if source_provenance.get("status") != "PASS":
        raise ValueError("Source generator provenance is not PASS")
    raw = load_source(args.source_register)
    grid_audit = validate_grid(raw, config)
    cap_register = augment_cap_register(raw, config, modern_reference)
    physical = deduplicate_physical(cap_register)
    primary_cap = float(config["gates"]["primary_hard_voltage_cap_v"])
    primary = cap_register[np.isclose(cap_register["cell_voltage_cap_tested_v"], primary_cap)].copy()
    receiver, receiver_counts = receiver_scenarios(
        primary, config["energy_ledgers"]["receiver_sec_values_kwh_kg"]
    )
    fixed, fixed_counts = fixed_loss_scenarios(physical, config, modern_reference)
    tw_j = aggregate_tw_j(primary, receiver)
    tw = aggregate_tw(primary)
    counts = gate_counts(cap_register)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    figures = args.out_dir / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    cap_register.to_csv(args.out_dir / "low_voltage_cap_register.csv", index=False)
    physical.to_csv(args.out_dir / "physical_register.csv", index=False)
    tw_j.to_csv(args.out_dir / "tw_j_summary.csv", index=False)
    tw.to_csv(args.out_dir / "tw_summary.csv", index=False)
    counts.to_csv(args.out_dir / "gate_counts.csv", index=False)
    receiver.to_csv(args.out_dir / "receiver_sec_scenarios_primary_cap.csv", index=False)
    receiver_counts.to_csv(args.out_dir / "receiver_sec_gate_counts.csv", index=False)
    fixed.to_csv(args.out_dir / "fixed_loss_sensitivity.csv", index=False)
    fixed_counts.to_csv(args.out_dir / "fixed_loss_gate_counts.csv", index=False)

    assumptions = {
        "study_id": config["study_id"],
        "voltage_cap_semantics": config["parameter_interpretation"]["voltage_cap_note"],
        "current_density_acceptance_limit_a_m2": None,
        "native_historical_margin_is_system_saving": False,
        "modern_comparator_reference_kw": modern_reference,
        "receiver_energy_status": "UNKNOWN",
        "full_system_claim_allowed": False,
        "fixed_loss_scenarios_are_probabilities": False,
        "fixed_loss_scenarios_are_membrane_asr": False,
    }
    (args.out_dir / "analysis_assumptions.json").write_text(
        json.dumps(assumptions, indent=2) + "\n", encoding="utf-8"
    )
    write_summary(
        args.out_dir / "summary_direct_eo_low_voltage_study_v1.md",
        config, cap_register, physical, counts, tw, receiver_counts, fixed_counts,
    )

    style()
    plot_feasibility(tw_j, figures / "01_low_voltage_tw_j_feasibility")
    plot_required_voltage(tw_j, figures / "02_required_voltage_tw_j")
    plot_high_tw(primary, config, figures / "03_high_tw_negative_controls")
    plot_modern_margin(tw_j, figures / "04_modern_comparator_margin")
    plot_fixed_loss(fixed_counts, physical, config, figures / "05_fixed_loss_voltage_sensitivity")
    plot_waterfall(counts, primary_cap, figures / "06_gate_waterfall")

    checks = audit_semantics(
        config, raw, cap_register, physical, receiver, fixed, grid_audit
    )
    failed = [check["check"] for check in checks if not check["passed"]]
    output_records = {
        name: provenance_record(args.out_dir / name) for name in OUTPUT_FILES
    }
    audit = {
        "audit_schema_version": 1,
        "study_id": config["study_id"],
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if not failed else "FAIL",
        "failed_checks": failed,
        "checks": checks,
        "grid_audit": grid_audit,
        "inputs": {
            "config": provenance_record(args.config),
            "source_register": provenance_record(args.source_register),
            "source_assumptions": provenance_record(args.source_assumptions),
            "source_generator_provenance": provenance_record(args.source_provenance),
            "modern_comparator_source": modern_source_record,
            "analyzer": provenance_record(Path(__file__)),
        },
        "outputs": output_records,
        "claim_boundary": config["claim_boundary"],
    }
    (args.out_dir / "analysis_audit.json").write_text(
        json.dumps(audit, indent=2) + "\n", encoding="utf-8"
    )
    if failed:
        raise RuntimeError("Analysis audit failed: " + ", ".join(failed))
    return {
        "cap_register": cap_register,
        "physical": physical,
        "tw_j": tw_j,
        "tw": tw,
        "gate_counts": counts,
        "receiver_counts": receiver_counts,
        "fixed_counts": fixed_counts,
        "audit": audit,
    }


def main() -> int:
    args = parse_args()
    result = run_analysis(args)
    cap = float(load_json(args.config)["gates"]["primary_hard_voltage_cap_v"])
    primary = result["cap_register"][
        np.isclose(result["cap_register"]["cell_voltage_cap_tested_v"], cap)
    ]
    print(f"Low-voltage analysis complete: {args.out_dir}")
    print(
        f"{len(result['physical']):,} physical coordinates; "
        f"{int(primary['membrane_operating_pass_at_cap'].sum()):,} membrane-gate passes at {cap:g} V; "
        f"{int(primary['modern_comparator_positive_before_receiver_pass'].sum()):,} modern-comparator-positive before receiver."
    )
    print("Audit PASS. Full-system claim remains forbidden.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, RuntimeError, ValueError) as error:
        raise SystemExit(f"ERROR: {error}") from error
