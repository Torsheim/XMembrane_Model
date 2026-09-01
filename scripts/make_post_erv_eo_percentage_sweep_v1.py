#!/usr/bin/env python3
"""Sweep EO share of the remaining dehumidification duty after a passive ERV.

Two percentage coordinates are kept side by side:

* historical relative reduction = (w_ERV - w_target) / w_ERV;
* remaining-duty completion = (w_ERV - w_target) / (w_ERV - w_supply).

The earlier "10 percent" result used the first definition.  The physical sweep
uses the second definition so that 100 percent means the complete remaining
latent duty.  The script reuses the audited energy and finite-film transport
functions from ``make_post_erv_full_eo_study_v1.py`` and adds a percentage-
specific, hash-bound output contract.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
from types import ModuleType
from typing import Any, Mapping

os.environ.setdefault("MPLCONFIGDIR", "/tmp/heiq-post-erv-eo-percentage-mpl")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


SCRIPT_VERSION = "post-erv-eo-percentage-sweep-v1.1-2026-08-27"
ROOT = Path(__file__).resolve().parents[1]
BASE_SCRIPT = ROOT / "scripts" / "make_post_erv_full_eo_study_v1.py"
DEFAULT_CONFIG = ROOT / "config" / "post_erv_eo_percentage_sweep_v1.json"
DEFAULT_OUTPUT = ROOT / "outputs" / "post_erv_eo_percentage_sweep_v1"
DEFAULT_V2_ROOT = ROOT.parent / "HeiQ_V2"


class StudyError(RuntimeError):
    """Raised when the percentage-study contract is violated."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--v2-root", type=Path, default=DEFAULT_V2_ROOT)
    parser.add_argument("--jobs", type=int, default=min(8, os.cpu_count() or 1))
    parser.add_argument(
        "--energy-only",
        action="store_true",
        help="Generate the dense percentage energy curve without transport.",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Use the declared smoke percentages and reduced material/current grid.",
    )
    parser.add_argument(
        "--postprocess-existing",
        action="store_true",
        help="Reuse a contract-matched transport CSV; selected step-halving cases are rerun.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow replacement of this study's named artifacts in a non-empty output directory.",
    )
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise StudyError(f"Could not load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def resolve_path(value: str | Path, *, root: Path = ROOT) -> Path:
    path = Path(value).expanduser()
    return (path if path.is_absolute() else root / path).resolve()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def percentage_token(value: float) -> str:
    text = f"{value:.9f}".rstrip("0").rstrip(".")
    return text.replace("-", "m").replace(".", "p")


def effective_config(
    percentage_config: Mapping[str, Any], base_config: Mapping[str, Any]
) -> dict[str, Any]:
    config = copy.deepcopy(dict(base_config))
    config["study_id"] = str(percentage_config["study_id"])
    sweep = config["transport_sweep"]
    for key, value in percentage_config["transport_overrides"].items():
        if key != "convergence_selection":
            sweep[key] = copy.deepcopy(value)
    config["claim_policy"]["full_system_claim_allowed"] = False
    scenario_sec = [
        float(value)
        for value in percentage_config["energy_percentage_grid"][
            "all_in_sec_scenarios_kwh_per_kg"
        ]
    ]
    if not scenario_sec or not all(math.isfinite(value) and value >= 0.0 for value in scenario_sec):
        raise StudyError("Energy SEC scenarios must be finite and nonnegative")
    config["energy_window"]["all_in_eo_sec_kwh_per_kg"] = sorted(
        set(
            float(value)
            for value in config["energy_window"]["all_in_eo_sec_kwh_per_kg"]
        ).union(scenario_sec)
    )
    config["targets"] = []
    return config


def completion_grid(section: Mapping[str, Any]) -> list[float]:
    start = float(section["start_remaining_duty_completion_pct"])
    stop = float(section["stop_remaining_duty_completion_pct"])
    step = float(section["step_remaining_duty_completion_pct"])
    if step <= 0.0 or start < 0.0 or stop >= 100.0 or start > stop:
        raise StudyError("Invalid remaining-duty energy grid")
    count = int(round((stop - start) / step))
    values = [start + index * step for index in range(count + 1)]
    if not math.isclose(values[-1], stop, rel_tol=0.0, abs_tol=1.0e-9):
        raise StudyError("Energy percentage grid does not land on its stop value")
    values.extend(float(value) for value in section["near_endpoint_completion_pct"])
    values.append(100.0)
    return values


def make_percentage_targets(
    base: ModuleType,
    runtime: Mapping[str, Any],
    percentage_config: Mapping[str, Any],
    config: dict[str, Any],
    *,
    smoke: bool,
) -> tuple[dict[str, Any], pd.DataFrame]:
    inlet_w = float(runtime["process_in"].w)
    supply_w = float(runtime["baseline"].remaining_ac.supply.w)
    remaining_delta = inlet_w - supply_w
    if remaining_delta <= 0.0:
        raise StudyError("Supply humidity must be below the passive-ERV outlet")
    full_historical_pct = 100.0 * remaining_delta / inlet_w
    legacy_relative_pct = float(
        percentage_config["percentage_definition"]["legacy_relative_reduction_pct"]
    )
    legacy_completion_pct = 100.0 * legacy_relative_pct / full_historical_pct
    transport_key = (
        "smoke_remaining_duty_completion_pct"
        if smoke
        else "transport_remaining_duty_completion_pct"
    )
    transport_values = [float(value) for value in percentage_config[transport_key]]
    all_values = completion_grid(percentage_config["energy_percentage_grid"])
    all_values.extend(transport_values)

    special_by_id: dict[str, dict[str, Any]] = {}
    for special in percentage_config["special_targets"]:
        row = dict(special)
        if row.get("use_supply_humidity_ratio"):
            target_w = supply_w
        else:
            target_w = float(row["humidity_ratio_kg_kg_da"])
        completion = 100.0 * (inlet_w - target_w) / remaining_delta
        listed_for_transport = any(
            math.isclose(completion, value, rel_tol=0.0, abs_tol=1.0e-8)
            for value in transport_values
        )
        if not isinstance(row.get("run_transport"), bool):
            raise StudyError(
                f"special_targets[{row.get('target_id', '?')}].run_transport must be boolean"
            )
        if bool(row["run_transport"]) != listed_for_transport:
            raise StudyError(
                f"special target {row.get('target_id', '?')} has run_transport="
                f"{row['run_transport']}, but its completion coordinate is "
                f"{'present' if listed_for_transport else 'absent'} in {transport_key}"
            )
        row["target_w"] = target_w
        row["completion"] = completion
        special_by_id[str(row["target_id"])] = row
        all_values.append(completion)

    all_values.append(legacy_completion_pct)
    unique_values: list[float] = []
    for value in sorted(all_values):
        if value < -1.0e-10 or value > 100.0 + 1.0e-10:
            raise StudyError(f"Completion percentage outside [0, 100]: {value}")
        value = float(np.clip(value, 0.0, 100.0))
        if not unique_values or not math.isclose(
            value, unique_values[-1], rel_tol=0.0, abs_tol=1.0e-9
        ):
            unique_values.append(value)

    def requested_for_transport(completion: float) -> bool:
        return any(
            math.isclose(completion, value, rel_tol=0.0, abs_tol=1.0e-8)
            for value in transport_values
        )

    targets: list[dict[str, Any]] = []
    coordinate_rows: list[dict[str, Any]] = []
    for completion in unique_values:
        special = next(
            (
                row
                for row in special_by_id.values()
                if math.isclose(
                    completion, float(row["completion"]), rel_tol=0.0, abs_tol=1.0e-8
                )
            ),
            None,
        )
        if special is not None:
            target_id = str(special["target_id"])
            label = str(special["label"])
            target_w = float(special["target_w"])
            interpretation = str(special["interpretation"])
        elif math.isclose(
            completion, legacy_completion_pct, rel_tol=0.0, abs_tol=1.0e-8
        ):
            target_id = "post_erv_10pct"
            label = "Historical 10 percent post-ERV humidity-ratio reduction"
            target_w = inlet_w * (1.0 - legacy_relative_pct / 100.0)
            interpretation = (
                "Regression bridge to the earlier 10 percent relative humidity-ratio reduction."
            )
        else:
            target_id = f"completion_{percentage_token(completion)}pct"
            label = f"{completion:g} percent of remaining duty"
            target_w = inlet_w - completion / 100.0 * remaining_delta
            interpretation = (
                f"EO completes {completion:g} percent of the finite remaining latent duty after ERV."
            )
        run_transport = bool(completion > 0.0 and requested_for_transport(completion))
        target = {
            "target_id": target_id,
            "label": label,
            "humidity_ratio_kg_kg_da": target_w,
            "run_transport": run_transport,
            "interpretation": interpretation,
        }
        targets.append(target)
        historical_pct = 100.0 * (inlet_w - target_w) / inlet_w
        water_kg_h = (
            float(runtime["dry_air_mass_flow_kg_s"])
            * (inlet_w - target_w)
            * 3600.0
        )
        coordinate_rows.append(
            {
                "target_id": target_id,
                "remaining_duty_completion_pct": completion,
                "historical_relative_reduction_pct": historical_pct,
                "target_w_kg_kg_da": target_w,
                "target_w_g_kg_da": 1000.0 * target_w,
                "eo_water_removal_kg_h": water_kg_h,
                "run_transport": run_transport,
                "is_historical_10pct_bridge": target_id == "post_erv_10pct",
                "is_o30_bridge": target_id == "o30",
                "is_exact_full_endpoint": target_id == "full_remaining_latent",
            }
        )
    config = copy.deepcopy(config)
    config["targets"] = targets
    target_frame = base.target_table(config, inlet_w)
    coordinates = target_frame.merge(
        pd.DataFrame(coordinate_rows),
        on=["target_id", "target_w_kg_kg_da", "target_w_g_kg_da", "run_transport"],
        how="left",
        validate="one_to_one",
    ).sort_values("remaining_duty_completion_pct", ignore_index=True)
    return config, coordinates


PERCENTAGE_COLUMNS = (
    "remaining_duty_completion_pct",
    "historical_relative_reduction_pct",
    "is_historical_10pct_bridge",
    "is_o30_bridge",
    "is_exact_full_endpoint",
)


def add_percentage_columns(frame: pd.DataFrame, coordinates: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    output = frame.drop(
        columns=[column for column in PERCENTAGE_COLUMNS if column in frame.columns]
    )
    lookup = coordinates.loc[:, ("target_id",) + PERCENTAGE_COLUMNS]
    return output.merge(lookup, on="target_id", how="left", validate="many_to_one")


def build_energy_tables(
    base: ModuleType,
    runtime: Mapping[str, Any],
    coordinates: pd.DataFrame,
    config: Mapping[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    energy, break_even = base.build_energy_window(runtime, coordinates, config)
    zero_target = coordinates.loc[
        np.isclose(coordinates["remaining_duty_completion_pct"], 0.0)
    ].iloc[0].to_dict()
    zero_rows: list[dict[str, Any]] = []
    zero_break_rows: list[dict[str, Any]] = []
    for heat_fraction in config["energy_window"]["process_heat_leak_fractions"]:
        zero_break_rows.append(
            {
                "target_id": zero_target["target_id"],
                "label": zero_target["label"],
                "target_w_g_kg_da": zero_target["target_w_g_kg_da"],
                "process_heat_leak_fraction": float(heat_fraction),
                "eo_water_removal_kg_h": 0.0,
                "remaining_ac_power_kw_at_zero_eo_sec": float(
                    runtime["baseline"].remaining_ac.total_ac_power_kw
                ),
                "maximum_avoided_ac_power_kw_at_zero_eo_sec": 0.0,
                "break_even_all_in_eo_sec_kwh_per_kg": math.nan,
                "full_system_claim_allowed": False,
            }
        )
        for sec in config["energy_window"]["all_in_eo_sec_kwh_per_kg"]:
            row = base.evaluate_energy_case(
                runtime,
                target=zero_target,
                sec_kwh_per_kg=float(sec),
                heat_fraction=float(heat_fraction),
            )
            row["break_even_all_in_eo_sec_kwh_per_kg"] = math.nan
            row["sec_margin_kwh_per_kg"] = math.nan
            row["conditional_energy_positive"] = False
            zero_rows.append(row)
    energy = pd.concat([pd.DataFrame(zero_rows), energy], ignore_index=True)
    break_even = pd.concat(
        [pd.DataFrame(zero_break_rows), break_even], ignore_index=True
    )
    energy = add_percentage_columns(energy, coordinates)
    break_even = add_percentage_columns(break_even, coordinates)

    endpoint = base.build_endpoint_control_audit(runtime, config)
    near_offset = endpoint.loc[
        endpoint["humidity_offset_above_supply_g_kg_da"] > 0.0
    ].sort_values("humidity_offset_above_supply_g_kg_da").iloc[0]
    full_mask = energy["target_id"].eq("full_remaining_latent")
    energy["control_conservative_net_saving_kw_vs_erv_ac"] = energy[
        "net_saving_kw_vs_erv_ac"
    ]
    energy["control_conservative_remaining_ac_power_kw"] = energy[
        "remaining_ac_power_kw"
    ]
    for index in energy.index[full_mask]:
        row = energy.loc[index]
        target = {
            "target_id": "near_endpoint_control_branch",
            "label": "Near-endpoint control branch",
            "target_w_kg_kg_da": float(runtime["baseline"].remaining_ac.supply.w)
            + float(near_offset["humidity_offset_above_supply_g_kg_da"]) / 1000.0,
            "target_w_g_kg_da": float(runtime["baseline"].remaining_ac.supply.w)
            * 1000.0
            + float(near_offset["humidity_offset_above_supply_g_kg_da"]),
            "requires_post_erv_eo": True,
        }
        conservative = base.evaluate_energy_case(
            runtime,
            target=target,
            sec_kwh_per_kg=float(row["all_in_eo_sec_kwh_per_kg"]),
            heat_fraction=float(row["process_heat_leak_fraction"]),
        )
        energy.loc[index, "control_conservative_net_saving_kw_vs_erv_ac"] = float(
            conservative["net_saving_kw_vs_erv_ac"]
        )
        energy.loc[index, "control_conservative_remaining_ac_power_kw"] = float(
            conservative["remaining_ac_power_kw"]
        )
    break_even["control_conservative_break_even_sec_kwh_per_kg"] = break_even[
        "break_even_all_in_eo_sec_kwh_per_kg"
    ]
    for index in break_even.index[
        break_even["target_id"].eq("full_remaining_latent")
    ]:
        heat_fraction = float(break_even.loc[index, "process_heat_leak_fraction"])
        target = {
            "target_id": "near_endpoint_control_branch",
            "label": "Near-endpoint control branch",
            "target_w_kg_kg_da": float(runtime["baseline"].remaining_ac.supply.w)
            + float(near_offset["humidity_offset_above_supply_g_kg_da"]) / 1000.0,
            "target_w_g_kg_da": float(runtime["baseline"].remaining_ac.supply.w)
            * 1000.0
            + float(near_offset["humidity_offset_above_supply_g_kg_da"]),
            "requires_post_erv_eo": True,
        }
        conservative_break = base.find_break_even_sec(
            runtime,
            target=target,
            heat_fraction=heat_fraction,
            search_max=float(config["energy_window"]["break_even_search_max_kwh_per_kg"]),
        )
        break_even.loc[
            index, "control_conservative_break_even_sec_kwh_per_kg"
        ] = conservative_break
    return energy, break_even, endpoint


def validate_percentage_transport(
    base: ModuleType,
    transport: pd.DataFrame,
    design: pd.DataFrame,
    coordinates: pd.DataFrame,
) -> None:
    base.validate_transport_frame_design(transport, design)
    if transport.empty:
        return
    lookup = coordinates.set_index("target_id")
    for target_id, group in transport.groupby("target_id", sort=False):
        if target_id not in lookup.index:
            raise StudyError(f"Unknown percentage target in transport: {target_id}")
        expected = lookup.loc[target_id]
        for column in PERCENTAGE_COLUMNS[:2]:
            values = pd.to_numeric(group[column], errors="coerce").to_numpy()
            if not np.isfinite(values).all() or not np.allclose(
                values, float(expected[column]), rtol=0.0, atol=1.0e-9
            ):
                raise StudyError(f"Transport percentage column mismatch: {column}")


def build_fixed_design_trajectory(
    transport: pd.DataFrame,
    runtime: Mapping[str, Any],
    percentage_config: Mapping[str, Any],
) -> pd.DataFrame:
    if transport.empty:
        return pd.DataFrame()
    section = percentage_config["fixed_design_trajectory"]
    if not bool(section["use_terminal1_anchor_diffusivity"]):
        raise StudyError("Only the declared Terminal-1 anchor trajectory is supported")
    diffusivity = float(runtime["anchor"]["water_diffusivity_m2_s"])
    current = float(section["uniform_current_density_a_m2"])
    receiver_ratio = float(section["receiver_to_process_dry_air_ratio"])
    mask = (
        np.isclose(
            pd.to_numeric(transport["water_diffusivity_m2_s"], errors="coerce"),
            diffusivity,
            rtol=1.0e-12,
            atol=0.0,
        )
        & np.isclose(
            pd.to_numeric(
                transport["uniform_current_density_a_m2"], errors="coerce"
            ),
            current,
            rtol=0.0,
            atol=1.0e-12,
        )
        & np.isclose(
            pd.to_numeric(
                transport["receiver_to_process_dry_air_ratio"], errors="coerce"
            ),
            receiver_ratio,
            rtol=0.0,
            atol=1.0e-12,
        )
    )
    trajectory = transport.loc[mask].copy().sort_values(
        "remaining_duty_completion_pct", ignore_index=True
    )
    expected_targets = set(transport["target_id"].astype(str))
    if set(trajectory["target_id"].astype(str)) != expected_targets:
        raise StudyError("Fixed-design trajectory does not cover every transport target")
    if trajectory["target_id"].duplicated().any():
        raise StudyError("Fixed-design trajectory has duplicate target rows")
    trajectory["trajectory_id"] = "terminal1_anchor__j3__R1"
    trajectory["trajectory_interpretation"] = str(section["interpretation"])
    trajectory["area_resized_for_each_target"] = True
    trajectory["fixed_installed_module_response"] = False
    return trajectory


def select_percentage_cases(base: ModuleType, transport: pd.DataFrame) -> pd.DataFrame:
    """Select only balanced, declared-gate rows; never fall back to failed cases."""

    if transport.empty:
        return pd.DataFrame()
    reached = transport.loc[base.bool_series(transport["target_reached"])].copy()
    rows: list[dict[str, Any]] = []
    for target_id, group in reached.groupby("target_id", sort=False):
        candidates = group.loc[
            base.bool_series(group["declared_transport_screen_pass"])
            & base.bool_series(group["receiver_resource_feasible_without_external_source"])
            & np.isclose(
                pd.to_numeric(
                    group["receiver_to_process_dry_air_ratio"], errors="coerce"
                ),
                1.0,
                rtol=0.0,
                atol=1.0e-12,
            )
        ].copy()
        if candidates.empty:
            continue
        best = candidates.sort_values(
            ["incremental_saving_kw_vs_passive_erv", "required_active_area_m2"],
            ascending=[False, True],
        ).iloc[0]
        minimum = candidates.sort_values(
            ["required_active_area_m2", "incremental_saving_kw_vs_passive_erv"],
            ascending=[True, False],
        ).iloc[0]
        for selection, row in (
            ("best_conditional_saving", best),
            ("minimum_area", minimum),
        ):
            record = row.to_dict()
            record["selection"] = selection
            record["selection_population"] = (
                "declared_transport_screen_pass_and_balanced_receiver_only"
            )
            record["percentage_selection_has_no_failed_case_fallback"] = True
            rows.append(record)
    return pd.DataFrame(rows)


def build_selection_status(
    base: ModuleType,
    transport: pd.DataFrame,
    selections: pd.DataFrame,
    coordinates: pd.DataFrame,
) -> pd.DataFrame:
    if transport.empty:
        return pd.DataFrame()
    selected_targets = (
        set(
            selections.loc[
                selections["selection"].eq("best_conditional_saving"), "target_id"
            ].astype(str)
        )
        if not selections.empty
        else set()
    )
    coordinate_lookup = coordinates.set_index("target_id")
    rows: list[dict[str, Any]] = []
    for target_id, group in transport.groupby("target_id", sort=False):
        reached = base.bool_series(group["target_reached"])
        balanced = np.isclose(
            pd.to_numeric(
                group["receiver_to_process_dry_air_ratio"], errors="coerce"
            ),
            1.0,
            rtol=0.0,
            atol=1.0e-12,
        )
        gate = base.bool_series(group["declared_transport_screen_pass"]) & balanced
        direction = (
            base.bool_series(group["positive_surface_direction_screen_pass"])
            & balanced
        )
        available = str(target_id) in selected_targets
        if available:
            reason = "selected_balanced_declared_gate_case"
        elif not reached.any():
            reason = "no_target_reaching_case"
        elif not gate.any():
            reason = "no_balanced_declared_gate_case"
        else:
            reason = "selection_missing_despite_available_case"
        coordinate = coordinate_lookup.loc[str(target_id)]
        rows.append(
            {
                "target_id": str(target_id),
                "remaining_duty_completion_pct": float(
                    coordinate["remaining_duty_completion_pct"]
                ),
                "historical_relative_reduction_pct": float(
                    coordinate["historical_relative_reduction_pct"]
                ),
                "case_count": len(group),
                "target_reached_count": int(reached.sum()),
                "balanced_declared_gate_pass_count": int(gate.sum()),
                "balanced_positive_surface_direction_count": int(direction.sum()),
                "balanced_selection_available": available,
                "selection_status": reason,
                "full_system_claim_allowed": False,
            }
        )
    return pd.DataFrame(rows).sort_values(
        "remaining_duty_completion_pct", ignore_index=True
    )


def build_convergence_population(
    base: ModuleType,
    selections: pd.DataFrame,
    fixed_trajectory: pd.DataFrame,
    convergence_selection: str,
) -> pd.DataFrame:
    """Return the deduplicated union of the primary envelope and fixed sizing path."""

    populations: list[pd.DataFrame] = []
    if not selections.empty:
        primary = selections.loc[
            selections["selection"].eq(convergence_selection)
        ].copy()
        if not primary.empty:
            primary["convergence_population"] = "selected_primary_envelope"
            populations.append(primary)
    if not fixed_trajectory.empty:
        fixed_area = pd.to_numeric(
            fixed_trajectory["required_active_area_m2"], errors="coerce"
        )
        fixed = fixed_trajectory.loc[
            base.bool_series(fixed_trajectory["target_reached"])
            & np.isfinite(fixed_area)
        ].copy()
        if not fixed.empty:
            fixed["convergence_population"] = "fixed_coordinate_sizing_trajectory"
            populations.append(fixed)
    if not populations:
        return pd.DataFrame()
    combined = pd.concat(populations, ignore_index=True, sort=False)
    membership = (
        combined.groupby("case_id", sort=False)["convergence_population"]
        .agg(lambda values: "+".join(sorted(set(map(str, values)))))
        .to_dict()
    )
    unique = combined.drop_duplicates("case_id", keep="first").copy()
    unique["convergence_population"] = unique["case_id"].map(membership)
    return unique.reset_index(drop=True)


def build_source_snapshot(
    runtime: Mapping[str, Any],
    *,
    percentage_config_path: Path,
    base_config_path: Path,
    source_config_path: Path,
    analyzer_path: Path,
) -> dict[str, Any]:
    """Hash every executable/configured input before a long transport run."""

    runtime_inputs: dict[str, dict[str, str]] = {}
    runtime_paths = runtime.get("paths")
    if runtime_paths is not None:
        for name, value in vars(runtime_paths).items():
            if name == "v2_root":
                continue
            path = Path(value).expanduser().resolve()
            if not path.is_file():
                raise StudyError(f"Runtime input disappeared before hashing: {path}")
            runtime_inputs[str(name)] = {
                "path": str(path),
                "sha256": sha256_file(path),
            }
    return {
        "percentage_generator_sha256": sha256_file(Path(__file__).resolve()),
        "base_generator_sha256": sha256_file(BASE_SCRIPT),
        "percentage_config_sha256": sha256_file(percentage_config_path),
        "base_config_sha256": sha256_file(base_config_path),
        "source_operating_region_config_sha256": sha256_file(source_config_path),
        "transport_analyzer_sha256": sha256_file(analyzer_path),
        "transport_source_hashes": dict(runtime["source_hashes"]),
        "runtime_inputs": runtime_inputs,
    }


def build_transport_contract(
    base: ModuleType,
    runtime: Mapping[str, Any],
    percentage_config: Mapping[str, Any],
    config: Mapping[str, Any],
    design: pd.DataFrame,
    transport_path: Path,
    *,
    percentage_config_path: Path,
    base_config_path: Path,
    source_config_path: Path,
    analyzer_path: Path,
    mode: str,
    source_snapshot: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    snapshot = dict(
        source_snapshot
        if source_snapshot is not None
        else build_source_snapshot(
            runtime,
            percentage_config_path=percentage_config_path,
            base_config_path=base_config_path,
            source_config_path=source_config_path,
            analyzer_path=analyzer_path,
        )
    )
    return {
        "schema_version": 1,
        "study_id": str(percentage_config["study_id"]),
        "mode": mode,
        "percentage_generator_version": SCRIPT_VERSION,
        "percentage_generator_sha256": snapshot["percentage_generator_sha256"],
        "base_generator_sha256": snapshot["base_generator_sha256"],
        "percentage_config_sha256": snapshot["percentage_config_sha256"],
        "base_config_sha256": snapshot["base_config_sha256"],
        "effective_config_sha256": base.sha256_json(config),
        "source_operating_region_config_sha256": snapshot[
            "source_operating_region_config_sha256"
        ],
        "transport_analyzer_sha256": snapshot["transport_analyzer_sha256"],
        "transport_source_hashes": snapshot["transport_source_hashes"],
        "source_snapshot": snapshot,
        "case_design_count": len(design),
        "case_design_sha256": base.transport_design_digest(design),
        "transport_csv": {
            "path": str(transport_path.resolve()),
            "sha256": sha256_file(transport_path),
        },
        "full_system_claim_allowed": False,
    }


def validate_transport_contract(
    base: ModuleType,
    contract_path: Path,
    runtime: Mapping[str, Any],
    percentage_config: Mapping[str, Any],
    config: Mapping[str, Any],
    design: pd.DataFrame,
    transport_path: Path,
    *,
    percentage_config_path: Path,
    base_config_path: Path,
    source_config_path: Path,
    analyzer_path: Path,
    mode: str,
) -> dict[str, Any]:
    if not contract_path.is_file() or not transport_path.is_file():
        raise StudyError("Postprocessing requires transport_contract.json and transport_cases.csv")
    contract = read_json(contract_path)
    expected = build_transport_contract(
        base,
        runtime,
        percentage_config,
        config,
        design,
        transport_path,
        percentage_config_path=percentage_config_path,
        base_config_path=base_config_path,
        source_config_path=source_config_path,
        analyzer_path=analyzer_path,
        mode=mode,
    )
    ignored = {"transport_csv"}
    mismatches = [
        key
        for key, value in expected.items()
        if key not in ignored and contract.get(key) != value
    ]
    if contract.get("transport_csv", {}).get("sha256") != expected[
        "transport_csv"
    ]["sha256"]:
        mismatches.append("transport_csv.sha256")
    if mismatches:
        raise StudyError(
            "Existing percentage transport output does not match the current contract: "
            + ", ".join(mismatches)
        )
    return contract


def build_percentage_summary(
    coordinates: pd.DataFrame,
    energy: pd.DataFrame,
    break_even: pd.DataFrame,
    selections: pd.DataFrame,
    selection_status: pd.DataFrame,
    fixed_trajectory: pd.DataFrame,
    percentage_config: Mapping[str, Any],
) -> pd.DataFrame:
    summary = coordinates.loc[
        :,
        [
            "target_id",
            "remaining_duty_completion_pct",
            "historical_relative_reduction_pct",
            "target_w_g_kg_da",
            "eo_water_removal_kg_h",
            "run_transport",
            "is_historical_10pct_bridge",
            "is_o30_bridge",
            "is_exact_full_endpoint",
        ],
    ].copy()
    zero_sec = energy.loc[
        np.isclose(energy["all_in_eo_sec_kwh_per_kg"], 0.0)
        & np.isclose(energy["process_heat_leak_fraction"], 0.0)
    ].set_index("target_id")
    summary["remaining_ac_power_kw_at_zero_eo_sec"] = summary["target_id"].map(
        zero_sec["remaining_ac_power_kw"]
    )
    summary["avoided_ac_power_kw_at_zero_eo_sec"] = summary["target_id"].map(
        zero_sec["reference_erv_plus_ac_power_kw"]
        - zero_sec["passive_erv_power_kw"]
        - zero_sec["remaining_ac_power_kw"]
    )
    zero_heat_break = break_even.loc[
        np.isclose(break_even["process_heat_leak_fraction"], 0.0)
    ].set_index("target_id")
    summary["native_break_even_sec_kwh_per_kg"] = summary["target_id"].map(
        zero_heat_break["break_even_all_in_eo_sec_kwh_per_kg"]
    )
    summary["control_conservative_break_even_sec_kwh_per_kg"] = summary[
        "target_id"
    ].map(zero_heat_break["control_conservative_break_even_sec_kwh_per_kg"])
    for sec in percentage_config["energy_percentage_grid"][
        "all_in_sec_scenarios_kwh_per_kg"
    ]:
        value = float(sec)
        subset = energy.loc[
            np.isclose(energy["all_in_eo_sec_kwh_per_kg"], value)
            & np.isclose(energy["process_heat_leak_fraction"], 0.0)
        ].set_index("target_id")
        token = percentage_token(1000.0 * value)
        summary[f"native_saving_zero_process_heat_at_{token}_wh_per_kg_kw"] = summary[
            "target_id"
        ].map(subset["net_saving_kw_vs_erv_ac"])
        summary[
            f"control_conservative_saving_zero_process_heat_at_{token}_wh_per_kg_kw"
        ] = summary["target_id"].map(
            subset["control_conservative_net_saving_kw_vs_erv_ac"]
        )

    if not selection_status.empty:
        status = selection_status.set_index("target_id")
        for column in (
            "case_count",
            "target_reached_count",
            "balanced_declared_gate_pass_count",
            "balanced_positive_surface_direction_count",
            "balanced_selection_available",
            "selection_status",
        ):
            summary[column] = summary["target_id"].map(status[column])

    if not selections.empty:
        best = selections.loc[
            selections["selection"].eq("best_conditional_saving")
        ].set_index("target_id")
        best_columns = {
            "water_diffusivity_m2_s": "best_water_diffusivity_m2_s",
            "uniform_current_density_a_m2": "best_current_density_a_m2",
            "required_active_area_m2": "best_required_active_area_m2",
            "maximum_required_terminal_voltage_signed_v": "best_maximum_terminal_voltage_v",
            "eo_grid_import_kw_no_export_credit": "best_eo_grid_import_kw",
            "incremental_module_fan_power_kw": "best_module_fan_power_kw",
            "known_eo_core_and_module_fan_sec_kwh_per_kg": "best_known_core_and_fan_sec_kwh_per_kg",
            "incremental_saving_kw_vs_passive_erv": "best_native_saving_before_receiver_sink_kw",
            "control_regime_conservative_saving_kw_before_receiver_sink": "best_control_conservative_saving_before_receiver_sink_kw",
            "control_regime_conservative_receiver_sink_sec_budget_kwh_per_kg": "best_control_conservative_receiver_sink_sec_budget_kwh_per_kg",
            "receiver_out_rh": "best_receiver_out_rh",
            "maximum_receiver_surface_activity": "best_maximum_receiver_surface_activity",
            "minimum_surface_activity_margin": "best_minimum_surface_activity_margin",
            "declared_transport_screen_pass": "best_declared_transport_screen_pass",
            "positive_surface_direction_screen_pass": "best_positive_surface_direction_screen_pass",
        }
        for source, destination in best_columns.items():
            summary[destination] = summary["target_id"].map(best[source])
        minimum = selections.loc[selections["selection"].eq("minimum_area")].set_index(
            "target_id"
        )
        for source, destination in {
            "required_active_area_m2": "minimum_area_m2",
            "uniform_current_density_a_m2": "minimum_area_current_density_a_m2",
            "maximum_required_terminal_voltage_signed_v": "minimum_area_maximum_terminal_voltage_v",
            "incremental_saving_kw_vs_passive_erv": "minimum_area_native_saving_kw",
        }.items():
            summary[destination] = summary["target_id"].map(minimum[source])
    if not fixed_trajectory.empty:
        fixed = fixed_trajectory.set_index("target_id")
        for source, destination in {
            "target_reached": "fixed_target_reached",
            "declared_transport_screen_pass": "fixed_declared_transport_screen_pass",
            "positive_surface_direction_screen_pass": "fixed_positive_surface_direction_screen_pass",
            "receiver_resource_feasible_without_external_source": "fixed_receiver_resource_feasible_without_external_source",
            "required_active_area_m2": "fixed_required_active_area_m2",
            "maximum_required_terminal_voltage_signed_v": "fixed_maximum_terminal_voltage_v",
            "known_eo_core_and_module_fan_sec_kwh_per_kg": "fixed_known_core_and_fan_sec_kwh_per_kg",
            "control_regime_conservative_saving_kw_before_receiver_sink": "fixed_control_conservative_saving_before_receiver_sink_kw",
            "control_regime_conservative_receiver_sink_sec_budget_kwh_per_kg": "fixed_control_conservative_receiver_sink_sec_budget_kwh_per_kg",
            "receiver_out_rh": "fixed_receiver_out_rh",
            "maximum_receiver_surface_activity": "fixed_maximum_receiver_surface_activity",
            "minimum_surface_activity_margin": "fixed_minimum_surface_activity_margin",
        }.items():
            summary[destination] = summary["target_id"].map(fixed[source])
    summary["full_system_claim_allowed"] = False
    return summary.sort_values("remaining_duty_completion_pct", ignore_index=True)


def plot_percentage_energy(
    summary: pd.DataFrame,
    percentage_config: Mapping[str, Any],
    output: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(9.4, 5.8))
    for sec in percentage_config["energy_percentage_grid"][
        "all_in_sec_scenarios_kwh_per_kg"
    ]:
        value = float(sec)
        token = percentage_token(1000.0 * value)
        column = (
            f"control_conservative_saving_zero_process_heat_at_"
            f"{token}_wh_per_kg_kw"
        )
        line = ax.plot(
            summary["remaining_duty_completion_pct"],
            summary[column],
            label=f"all-in EO SEC {value:.3f} kWh/kg",
        )[0]
        full = summary.loc[summary["target_id"].eq("full_remaining_latent")]
        native_column = f"native_saving_zero_process_heat_at_{token}_wh_per_kg_kw"
        if not full.empty:
            ax.scatter(
                [100.0],
                [float(full.iloc[0][native_column])],
                marker="*",
                s=90,
                color=line.get_color(),
                label=f"exact 100% endpoint, SEC {value:.3f}",
                zorder=4,
            )
    ax.axhline(0.0, color="black", linewidth=1.0)
    for target_id, label in (
        ("post_erv_10pct", "historical 10%"),
        ("o30", "O30"),
        ("full_remaining_latent", "full duty"),
    ):
        row = summary.loc[summary["target_id"].eq(target_id)]
        if not row.empty:
            x = float(row.iloc[0]["remaining_duty_completion_pct"])
            ax.axvline(x, color="0.45", linewidth=0.8, linestyle=":")
            ax.text(x, ax.get_ylim()[1] * 0.96, label, rotation=90, va="top", ha="right")
    ax.set_xlabel("EO completion of the remaining post-ERV latent duty [%]")
    ax.set_ylabel("Conservative conditional saving vs ERV + AC [kW]")
    ax.set_title("Energy consequence of increasing the EO share after ERV")
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output, dpi=180)
    plt.close(fig)


def plot_percentage_sec_budget(summary: pd.DataFrame, output: Path) -> None:
    rows = summary.loc[summary["run_transport"]].copy()
    fig, ax = plt.subplots(figsize=(9.4, 5.8))
    for prefix, label, linestyle, marker in (
        ("best", "best-energy envelope", "-", "o"),
        ("fixed", "fixed Terminal-1 D / 3 A m⁻² sizing path", "--", "x"),
    ):
        known = f"{prefix}_known_core_and_fan_sec_kwh_per_kg"
        budget = f"{prefix}_control_conservative_receiver_sink_sec_budget_kwh_per_kg"
        if known not in rows or budget not in rows:
            continue
        x = rows["remaining_duty_completion_pct"]
        line = ax.plot(
            x,
            rows[known],
            linestyle=linestyle,
            marker=marker,
            label=f"known core + module fan SEC — {label}",
        )[0]
        ax.plot(
            x,
            rows[budget],
            linestyle=linestyle,
            marker=marker,
            color=line.get_color(),
            alpha=0.62,
            label=f"remaining receiver/sink SEC budget — {label}",
        )
    ax.axhline(0.0, color="black", linewidth=1.0)
    ax.set_xlabel("EO completion of remaining post-ERV latent duty [%]")
    ax.set_ylabel("Specific energy [kWh/kg water]")
    ax.set_title("Known membrane demand and unclosed receiver/sink budget")
    ax.grid(alpha=0.25)
    if ax.lines:
        ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(output, dpi=180)
    plt.close(fig)


def plot_percentage_transport(summary: pd.DataFrame, output: Path) -> None:
    best = (
        summary.loc[summary["run_transport"]].copy()
        if "best_required_active_area_m2" in summary.columns
        else pd.DataFrame()
    )
    fixed = (
        summary.loc[summary["run_transport"]].copy()
        if "fixed_required_active_area_m2" in summary.columns
        else pd.DataFrame()
    )
    fig, axes = plt.subplots(2, 2, figsize=(11.0, 8.0), sharex=True)
    if not best.empty:
        x = best["remaining_duty_completion_pct"]
        axes[0, 0].plot(
            x,
            best["best_required_active_area_m2"],
            marker="o",
            label="best-energy envelope",
        )
        axes[0, 1].plot(
            x,
            best["best_maximum_terminal_voltage_v"],
            marker="o",
            color="tab:orange",
        )
        axes[1, 0].plot(
            x,
            best["best_maximum_receiver_surface_activity"],
            marker="o",
            color="tab:green",
        )
        axes[1, 1].plot(
            x,
            best["best_minimum_surface_activity_margin"],
            marker="o",
            color="tab:red",
        )
    if not fixed.empty:
        fixed_x = fixed["remaining_duty_completion_pct"]
        axes[0, 0].plot(
            fixed_x,
            fixed["fixed_required_active_area_m2"],
            linestyle="--",
            marker="x",
            label="fixed Terminal-1, 3 A/m²",
        )
        axes[0, 1].plot(
            fixed_x,
            fixed["fixed_maximum_terminal_voltage_v"],
            linestyle="--",
            marker="x",
            color="tab:orange",
        )
        axes[1, 0].plot(
            fixed_x,
            fixed["fixed_maximum_receiver_surface_activity"],
            linestyle="--",
            marker="x",
            color="tab:green",
        )
        axes[1, 1].plot(
            fixed_x,
            fixed["fixed_minimum_surface_activity_margin"],
            linestyle="--",
            marker="x",
            color="tab:red",
        )
    axes[0, 0].set_ylabel("Active area [m²]")
    axes[0, 0].set_title("Membrane area")
    if axes[0, 0].lines:
        axes[0, 0].legend()
    axes[0, 1].axhline(1.0, color="0.45", linewidth=0.8, linestyle=":")
    axes[0, 1].axhline(2.0, color="0.45", linewidth=0.8, linestyle="--")
    axes[0, 1].set_ylabel("Maximum terminal voltage [V]")
    axes[0, 1].set_title("Voltage sensitivity")
    axes[1, 0].axhline(0.99, color="0.45", linewidth=0.8, linestyle="--")
    axes[1, 0].set_ylabel("Maximum receiver surface activity [-]")
    axes[1, 0].set_title("Receiver loading")
    axes[1, 1].axhline(0.0, color="black", linewidth=1.0)
    axes[1, 1].set_ylabel("Minimum source−receiver activity [-]")
    axes[1, 1].set_title("Diffusive driving-direction margin")
    for ax in axes.flat:
        ax.set_xlabel("Remaining-duty completion [%]")
        ax.grid(alpha=0.25)
    fig.suptitle("Finite-film membrane and balanced receiver as EO share increases")
    fig.tight_layout()
    fig.savefig(output, dpi=180)
    plt.close(fig)


def value_at(summary: pd.DataFrame, target_id: str, column: str) -> float:
    row = summary.loc[summary["target_id"].eq(target_id)]
    return float(row.iloc[0][column]) if not row.empty else math.nan


def build_summary_markdown(
    base: ModuleType,
    runtime: Mapping[str, Any],
    summary: pd.DataFrame,
    transport: pd.DataFrame,
    selections: pd.DataFrame,
    convergence: pd.DataFrame,
    percentage_config: Mapping[str, Any],
    *,
    mode: str,
) -> str:
    legacy_completion = value_at(
        summary, "post_erv_10pct", "remaining_duty_completion_pct"
    )
    o30_completion = value_at(summary, "o30", "remaining_duty_completion_pct")
    full_historical = value_at(
        summary, "full_remaining_latent", "historical_relative_reduction_pct"
    )
    lines = [
        "# EO percentage sweep after passive ERV",
        "",
        f"Mode: `{mode}`.",
        "",
        "## Percentage semantics",
        "",
        f"- The historical 10% case closes {legacy_completion:.4f}% of the finite post-ERV-to-supply moisture gap.",
        f"- O30 closes {o30_completion:.4f}% of that gap.",
        f"- Full remaining dehumidification is only a {full_historical:.4f}% relative reduction from the ERV outlet humidity ratio, but 100% of the finite remaining duty.",
        "- Both coordinates are retained; no previous 10% result is silently relabelled.",
        "",
        "## Energy trend",
        "",
        "For every point below the exact 100% endpoint, the screening HVAC model stays on its saturated-coil branch. At zero EO process-heat leakage, the conservative saving therefore grows approximately linearly with treated water when all-in EO SEC is below 0.1567 kWh/kg, is neutral near 0.1567, and becomes an increasing loss above it.",
        "",
        "The exact 100% coordinate is a separate control regime: it switches to sensible-only cooling and must not be connected continuously to the one-sided near-endpoint curve.",
    ]
    for sec in percentage_config["energy_percentage_grid"][
        "all_in_sec_scenarios_kwh_per_kg"
    ]:
        token = percentage_token(1000.0 * float(sec))
        column = (
            f"control_conservative_saving_zero_process_heat_at_"
            f"{token}_wh_per_kg_kw"
        )
        legacy = value_at(summary, "post_erv_10pct", column)
        o30 = value_at(summary, "o30", column)
        full = value_at(summary, "full_remaining_latent", column)
        lines.append(
            f"- At all-in SEC {float(sec):.3f} kWh/kg and zero process-heat leakage: conservative saving is {legacy:.2f} kW at the historical 10% point, {o30:.2f} kW at O30 and {full:.2f} kW at full duty."
        )
    lines.extend(["", "## Membrane and receiver trend", ""])
    if transport.empty:
        lines.append("Transport was not run (`--energy-only`).")
    elif selections.empty:
        lines.append(
            "Transport ran, but no balanced receiver case passed the declared selection gates."
        )
    else:
        reached = base.bool_series(transport["target_reached"])
        gate = base.bool_series(transport["declared_transport_screen_pass"])
        direction = base.bool_series(
            transport["positive_surface_direction_screen_pass"]
        )
        lines.append(
            f"- {int(reached.sum())}/{len(transport)} cases reached target; {int(gate.sum())} passed the declared transport/receiver gate and {int(direction.sum())} also retained positive surface direction everywhere."
        )
        lines.append(
            "- The fixed Terminal-1 D/j/R curve re-sizes active area at every target; it is a fixed-coordinate sizing trajectory, not one fixed installed module."
        )
        for target_id, name in (
            ("post_erv_10pct", "historical 10%"),
            ("o30", "O30"),
            ("full_remaining_latent", "full duty"),
        ):
            anchor = summary.loc[summary["target_id"].eq(target_id)]
            available = bool(
                not anchor.empty
                and "balanced_selection_available" in anchor.columns
                and anchor.iloc[0]["balanced_selection_available"] is not pd.NA
                and bool(anchor.iloc[0]["balanced_selection_available"])
            )
            if not available:
                status = (
                    str(anchor.iloc[0].get("selection_status", "status_unavailable"))
                    if not anchor.empty
                    else "coordinate_missing"
                )
                lines.append(f"- {name}: no selected balanced case (`{status}`).")
                continue
            area = value_at(summary, target_id, "best_required_active_area_m2")
            voltage = value_at(summary, target_id, "best_maximum_terminal_voltage_v")
            activity = value_at(
                summary, target_id, "best_maximum_receiver_surface_activity"
            )
            budget = value_at(
                summary,
                target_id,
                "best_control_conservative_receiver_sink_sec_budget_kwh_per_kg",
            )
            lines.append(
                f"- {name}: {area:.1f} m², maximum {voltage:.3f} V, receiver-surface activity {activity:.4f}, and {budget:.4f} kWh/kg conservative receiver/sink budget."
            )
        if not convergence.empty:
            lines.append(
                f"- Step-halving: {int(convergence['step_halving_convergence_pass'].sum())}/{len(convergence)} unique best-envelope/fixed-trajectory cases passed."
            )
    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "The curves are conditional. Receiver regeneration/disposal, heat rejection, conjugate thermal feedback and rankable manifold pressure drop remain missing or parameterized. No percentage is a validated full-system optimum.",
            "",
            "## Reproduction",
            "",
            "```bash",
            "python3 -B scripts/make_post_erv_eo_percentage_sweep_v1.py --energy-only --output-dir outputs/post_erv_eo_percentage_sweep_v1_energy_only --overwrite",
            "python3 -B scripts/make_post_erv_eo_percentage_sweep_v1.py --smoke --jobs 4 --output-dir outputs/post_erv_eo_percentage_sweep_v1_smoke --overwrite",
            "python3 -B scripts/make_post_erv_eo_percentage_sweep_v1.py --jobs 8 --output-dir outputs/post_erv_eo_percentage_sweep_v1 --overwrite",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def build_audit(
    base: ModuleType,
    runtime: Mapping[str, Any],
    percentage_config: Mapping[str, Any],
    config: Mapping[str, Any],
    coordinates: pd.DataFrame,
    energy: pd.DataFrame,
    break_even: pd.DataFrame,
    transport: pd.DataFrame,
    selections: pd.DataFrame,
    endpoint: pd.DataFrame,
    convergence: pd.DataFrame,
    summary: pd.DataFrame,
    selection_status: pd.DataFrame,
    fixed_trajectory: pd.DataFrame,
    transport_contract_validated: bool,
    source_snapshot_unchanged: bool,
    *,
    percentage_config_path: Path,
    base_config_path: Path,
    source_config_path: Path,
    analyzer_path: Path,
    mode: str,
) -> dict[str, Any]:
    base_audit = base.build_audit(
        runtime,
        config,
        coordinates,
        energy,
        break_even,
        transport,
        endpoint,
        convergence,
        transport_contract_validated,
        config_path=percentage_config_path,
        source_config_path=source_config_path,
        analyzer_path=analyzer_path,
        mode=mode,
    )
    ordered = coordinates.sort_values("remaining_duty_completion_pct")
    tolerance = float(percentage_config["audit_tolerances"]["percentage_absolute"])
    identity_tolerance = float(
        percentage_config["audit_tolerances"]["identity_absolute_kw"]
    )
    monotonic_tolerance = float(
        percentage_config["audit_tolerances"]["monotonic_absolute"]
    )
    legacy = ordered.loc[ordered["target_id"].eq("post_erv_10pct")].iloc[0]
    o30 = ordered.loc[ordered["target_id"].eq("o30")].iloc[0]
    full = ordered.loc[ordered["target_id"].eq("full_remaining_latent")].iloc[0]
    full_water = float(full["eo_water_removal_kg_h"])
    convergence_selection = str(
        percentage_config["transport_overrides"]["convergence_selection"]
    )
    expected_convergence = build_convergence_population(
        base, selections, fixed_trajectory, convergence_selection
    )
    expected_convergence_ids = (
        set(expected_convergence["case_id"].astype(str))
        if not expected_convergence.empty
        else set()
    )
    actual_convergence_ids = (
        set(convergence["source_case_id"].astype(str))
        if not convergence.empty
        else set()
    )
    zero_heat_zero_sec = energy.loc[
        np.isclose(energy["all_in_eo_sec_kwh_per_kg"], 0.0)
        & np.isclose(energy["process_heat_leak_fraction"], 0.0)
    ]
    sensible = zero_heat_zero_sec.loc[
        (zero_heat_zero_sec["remaining_duty_completion_pct"] > 0.0)
        & base.bool_series(zero_heat_zero_sec["remaining_ac_is_sensible_only"])
    ]
    full_energy = zero_heat_zero_sec.loc[
        zero_heat_zero_sec["target_id"].eq("full_remaining_latent")
    ]
    full_energy_all_sec = energy.loc[
        energy["target_id"].eq("full_remaining_latent")
        & np.isclose(energy["process_heat_leak_fraction"], 0.0)
    ]
    exact_endpoint = endpoint.loc[
        endpoint["humidity_offset_above_supply_g_kg_da"].eq(0.0)
    ]
    near_endpoint = endpoint.loc[
        endpoint["humidity_offset_above_supply_g_kg_da"] > 0.0
    ].sort_values("humidity_offset_above_supply_g_kg_da")
    full_break = break_even.loc[
        break_even["target_id"].eq("full_remaining_latent")
        & np.isclose(break_even["process_heat_leak_fraction"], 0.0)
    ]
    endpoint_linkage = False
    endpoint_all_sec_linkage = False
    endpoint_jump_kw = math.nan
    if (
        len(full_energy) == 1
        and len(exact_endpoint) == 1
        and not near_endpoint.empty
        and len(full_break) == 1
    ):
        full_energy_row = full_energy.iloc[0]
        exact_endpoint_row = exact_endpoint.iloc[0]
        near_endpoint_row = near_endpoint.iloc[0]
        full_break_row = full_break.iloc[0]
        endpoint_jump_kw = float(full_energy_row["net_saving_kw_vs_erv_ac"]) - float(
            full_energy_row["control_conservative_net_saving_kw_vs_erv_ac"]
        )
        expected_jump_kw = float(
            full_energy_row["control_conservative_remaining_ac_power_kw"]
        ) - float(full_energy_row["remaining_ac_power_kw"])
        exact_ac_kw = float(
            exact_endpoint_row["remaining_ac_power_kw_at_zero_eo_sec"]
        )
        near_ac_kw = float(
            near_endpoint_row["remaining_ac_power_kw_at_zero_eo_sec"]
        )
        exact_water_kg_h = float(exact_endpoint_row["eo_water_removal_kg_h"])
        near_water_kg_h = float(near_endpoint_row["eo_water_removal_kg_h"])
        baseline_ac_kw = float(runtime["baseline"].remaining_ac.total_ac_power_kw)
        endpoint_all_sec_linkage = True
        for _, row in full_energy_all_sec.iterrows():
            sec = float(row["all_in_eo_sec_kwh_per_kg"])
            native_expected = baseline_ac_kw - exact_ac_kw - exact_water_kg_h * sec
            conservative_expected = (
                baseline_ac_kw - near_ac_kw - near_water_kg_h * sec
            )
            actual_jump = float(row["net_saving_kw_vs_erv_ac"]) - float(
                row["control_conservative_net_saving_kw_vs_erv_ac"]
            )
            expected_sec_jump = (
                near_ac_kw
                - exact_ac_kw
                + (near_water_kg_h - exact_water_kg_h) * sec
            )
            endpoint_all_sec_linkage = bool(
                endpoint_all_sec_linkage
                and math.isclose(
                    float(row["remaining_ac_power_kw"]),
                    exact_ac_kw,
                    rel_tol=0.0,
                    abs_tol=identity_tolerance,
                )
                and math.isclose(
                    float(row["control_conservative_remaining_ac_power_kw"]),
                    near_ac_kw,
                    rel_tol=0.0,
                    abs_tol=identity_tolerance,
                )
                and math.isclose(
                    float(row["net_saving_kw_vs_erv_ac"]),
                    native_expected,
                    rel_tol=0.0,
                    abs_tol=identity_tolerance,
                )
                and math.isclose(
                    float(row["control_conservative_net_saving_kw_vs_erv_ac"]),
                    conservative_expected,
                    rel_tol=0.0,
                    abs_tol=identity_tolerance,
                )
                and math.isclose(
                    actual_jump,
                    expected_sec_jump,
                    rel_tol=0.0,
                    abs_tol=identity_tolerance,
                )
            )
        endpoint_linkage = bool(
            math.isclose(
                float(full_energy_row["remaining_ac_power_kw"]),
                float(exact_endpoint_row["remaining_ac_power_kw_at_zero_eo_sec"]),
                rel_tol=0.0,
                abs_tol=identity_tolerance,
            )
            and math.isclose(
                float(full_energy_row["control_conservative_remaining_ac_power_kw"]),
                float(near_endpoint_row["remaining_ac_power_kw_at_zero_eo_sec"]),
                rel_tol=0.0,
                abs_tol=identity_tolerance,
            )
            and math.isclose(
                float(full_break_row["break_even_all_in_eo_sec_kwh_per_kg"]),
                float(exact_endpoint_row["break_even_all_in_eo_sec_kwh_per_kg"]),
                rel_tol=0.0,
                abs_tol=identity_tolerance,
            )
            and math.isclose(
                float(
                    full_break_row[
                        "control_conservative_break_even_sec_kwh_per_kg"
                    ]
                ),
                float(near_endpoint_row["break_even_all_in_eo_sec_kwh_per_kg"]),
                rel_tol=0.0,
                abs_tol=identity_tolerance,
            )
            and endpoint_jump_kw > identity_tolerance
            and math.isclose(
                endpoint_jump_kw,
                expected_jump_kw,
                rel_tol=0.0,
                abs_tol=identity_tolerance,
            )
            and math.isclose(
                float(full["target_w_g_kg_da"]),
                float(exact_endpoint_row["target_w_g_kg_da"]),
                rel_tol=0.0,
                abs_tol=tolerance,
            )
            and math.isclose(
                full_water,
                exact_water_kg_h,
                rel_tol=1.0e-10,
                abs_tol=monotonic_tolerance,
            )
            and bool(exact_endpoint_row["remaining_ac_is_sensible_only"])
            and not bool(near_endpoint_row["remaining_ac_is_sensible_only"])
            and endpoint_all_sec_linkage
        )

    scenario_complete = True
    summary_scenarios_finite = True
    heat_values = [
        float(value)
        for value in config["energy_window"]["process_heat_leak_fractions"]
    ]
    expected_scenario_keys = {
        (str(target_id), heat)
        for target_id in coordinates["target_id"]
        for heat in heat_values
    }
    for sec in percentage_config["energy_percentage_grid"][
        "all_in_sec_scenarios_kwh_per_kg"
    ]:
        scenario = energy.loc[
            np.isclose(energy["all_in_eo_sec_kwh_per_kg"], float(sec))
        ]
        required = (
            "eo_water_removal_kg_h",
            "eo_power_kw",
            "remaining_ac_power_kw",
            "net_saving_kw_vs_erv_ac",
            "energy_identity_error_kw",
            "control_conservative_remaining_ac_power_kw",
            "control_conservative_net_saving_kw_vs_erv_ac",
        )
        actual_scenario_keys = set(
            zip(
                scenario["target_id"].astype(str),
                scenario["process_heat_leak_fraction"].astype(float),
            )
        )
        scenario_complete = bool(
            scenario_complete
            and len(scenario) == len(expected_scenario_keys)
            and actual_scenario_keys == expected_scenario_keys
            and all(
                np.isfinite(pd.to_numeric(scenario[column], errors="coerce")).all()
                for column in required
            )
        )
        token = percentage_token(1000.0 * float(sec))
        summary_columns = (
            f"native_saving_zero_process_heat_at_{token}_wh_per_kg_kw",
            f"control_conservative_saving_zero_process_heat_at_{token}_wh_per_kg_kw",
        )
        summary_scenarios_finite = bool(
            summary_scenarios_finite
            and all(column in summary.columns for column in summary_columns)
            and all(
                np.isfinite(pd.to_numeric(summary[column], errors="coerce")).all()
                for column in summary_columns
            )
        )

    transport_target_ids = set(
        coordinates.loc[coordinates["run_transport"], "target_id"].astype(str)
    )
    status_target_ids = (
        set(selection_status["target_id"].astype(str))
        if not selection_status.empty
        else set()
    )
    selection_status_complete = bool(
        (transport.empty and selection_status.empty)
        or (
            status_target_ids == transport_target_ids
            and not selection_status["target_id"].duplicated().any()
        )
    )
    no_internal_selection_gap = bool(
        selection_status.empty
        or not selection_status["selection_status"]
        .astype(str)
        .eq("selection_missing_despite_available_case")
        .any()
    )
    special_transport_consistent = True
    coordinate_by_id = coordinates.set_index("target_id")
    transport_grid_key = (
        "smoke_remaining_duty_completion_pct"
        if mode == "smoke"
        else "transport_remaining_duty_completion_pct"
    )
    configured_transport_completion = [
        float(value) for value in percentage_config[transport_grid_key]
    ]
    for special in percentage_config["special_targets"]:
        target_id = str(special["target_id"])
        coordinate_exists_once = int(coordinates["target_id"].eq(target_id).sum()) == 1
        completion = (
            float(coordinate_by_id.loc[target_id, "remaining_duty_completion_pct"])
            if coordinate_exists_once
            else math.nan
        )
        listed = any(
            math.isclose(completion, value, rel_tol=0.0, abs_tol=1.0e-8)
            for value in configured_transport_completion
        )
        actual = bool(coordinate_by_id.loc[target_id, "run_transport"]) if coordinate_exists_once else False
        declared = bool(special["run_transport"])
        special_transport_consistent = bool(
            special_transport_consistent
            and coordinate_exists_once
            and declared == listed
            and actual == (completion > 0.0 and listed)
            and actual == declared
        )
    configured_ratios = [
        float(value)
        for value in config["transport_sweep"]["receiver_to_process_dry_air_ratio"]
    ]
    configured_smoke_ratios = [
        float(value)
        for value in config["transport_sweep"][
            "smoke_receiver_to_process_dry_air_ratio"
        ]
    ]

    def ratios_are_exactly_one(frame: pd.DataFrame) -> bool:
        if frame.empty:
            return True
        values = pd.to_numeric(
            frame["receiver_to_process_dry_air_ratio"], errors="coerce"
        ).to_numpy(float)
        return bool(
            np.isfinite(values).all()
            and np.isclose(values, 1.0, rtol=0.0, atol=1.0e-12).all()
        )

    fixed_structure_valid = bool(transport.empty and fixed_trajectory.empty)
    if not transport.empty and not fixed_trajectory.empty:
        fixed_section = percentage_config["fixed_design_trajectory"]
        fixed_d = pd.to_numeric(
            fixed_trajectory["water_diffusivity_m2_s"], errors="coerce"
        ).to_numpy(float)
        fixed_j = pd.to_numeric(
            fixed_trajectory["uniform_current_density_a_m2"], errors="coerce"
        ).to_numpy(float)
        fixed_structure_valid = bool(
            len(fixed_trajectory) == len(transport_target_ids)
            and set(fixed_trajectory["target_id"].astype(str))
            == transport_target_ids
            and not fixed_trajectory["target_id"].duplicated().any()
            and not fixed_trajectory["case_id"].duplicated().any()
            and set(fixed_trajectory["case_id"].astype(str)).issubset(
                set(transport["case_id"].astype(str))
            )
            and fixed_trajectory["trajectory_id"]
            .astype(str)
            .eq("terminal1_anchor__j3__R1")
            .all()
            and base.bool_series(
                fixed_trajectory["area_resized_for_each_target"]
            ).all()
            and not base.bool_series(
                fixed_trajectory["fixed_installed_module_response"]
            ).any()
            and np.isfinite(fixed_d).all()
            and np.isclose(
                fixed_d,
                float(runtime["anchor"]["water_diffusivity_m2_s"]),
                rtol=1.0e-12,
                atol=0.0,
            ).all()
            and np.isfinite(fixed_j).all()
            and np.isclose(
                fixed_j,
                float(fixed_section["uniform_current_density_a_m2"]),
                rtol=0.0,
                atol=1.0e-12,
            ).all()
            and ratios_are_exactly_one(fixed_trajectory)
        )

    percentage_checks = {
        "coordinate_ids_unique": not ordered["target_id"].duplicated().any(),
        "completion_starts_at_zero": math.isclose(
            float(ordered.iloc[0]["remaining_duty_completion_pct"]),
            0.0,
            rel_tol=0.0,
            abs_tol=tolerance,
        ),
        "completion_ends_at_exact_100": math.isclose(
            float(full["remaining_duty_completion_pct"]),
            100.0,
            rel_tol=0.0,
            abs_tol=tolerance,
        ),
        "historical_10pct_maps_to_expected_completion": math.isclose(
            float(legacy["remaining_duty_completion_pct"]),
            22.192500901195075,
            rel_tol=0.0,
            abs_tol=tolerance,
        ),
        "o30_maps_to_expected_completion": math.isclose(
            float(o30["remaining_duty_completion_pct"]),
            72.70030721103439,
            rel_tol=0.0,
            abs_tol=tolerance,
        ),
        "full_historical_reduction_is_expected": math.isclose(
            float(full["historical_relative_reduction_pct"]),
            45.06026627878382,
            rel_tol=0.0,
            abs_tol=tolerance,
        ),
        "humidity_target_monotone_nonincreasing": bool(
            np.all(
                np.diff(ordered["target_w_kg_kg_da"].to_numpy(float))
                <= monotonic_tolerance
            )
        ),
        "water_duty_monotone_nondecreasing": bool(
            np.all(
                np.diff(ordered["eo_water_removal_kg_h"].to_numpy(float))
                >= -monotonic_tolerance
            )
        ),
        "water_duty_is_completion_fraction_identity": bool(
            np.allclose(
                ordered["eo_water_removal_kg_h"].to_numpy(float),
                ordered["remaining_duty_completion_pct"].to_numpy(float)
                / 100.0
                * full_water,
                rtol=1.0e-10,
                atol=monotonic_tolerance,
            )
        ),
        "only_exact_full_endpoint_is_sensible_only": bool(
            len(sensible) == 1
            and str(sensible.iloc[0]["target_id"]) == "full_remaining_latent"
            and bool(sensible.iloc[0]["is_exact_full_endpoint"])
            and math.isclose(
                float(sensible.iloc[0]["remaining_duty_completion_pct"]),
                100.0,
                rel_tol=0.0,
                abs_tol=tolerance,
            )
        ),
        "full_exact_and_conservative_endpoint_linkage": endpoint_linkage,
        "configured_zero_heat_sec_scenarios_complete_and_finite": scenario_complete,
        "summary_zero_heat_sec_scenarios_are_finite": summary_scenarios_finite,
        "energy_identity_within_configured_tolerance": bool(
            base_audit["energy_identity_max_abs_kw"] is not None
            and float(base_audit["energy_identity_max_abs_kw"])
            <= identity_tolerance
        ),
        "special_target_transport_flags_match_grid": special_transport_consistent,
        "summary_has_every_coordinate": len(summary) == len(coordinates),
        "selection_status_covers_every_transport_target": selection_status_complete,
        "selection_status_has_no_internal_gap": no_internal_selection_gap,
        "fixed_coordinate_sizing_trajectory_structure_valid": fixed_structure_valid,
        "selection_has_no_failed_case_fallback": bool(
            selections.empty
            or (
                base.bool_series(selections["declared_transport_screen_pass"]).all()
                and base.bool_series(
                    selections["receiver_resource_feasible_without_external_source"]
                ).all()
                and base.bool_series(
                    selections[
                        "percentage_selection_has_no_failed_case_fallback"
                    ]
                ).all()
            )
        ),
        "balanced_receiver_design_is_exactly_ratio_one": bool(
            len(configured_ratios) == 1
            and math.isclose(
                configured_ratios[0], 1.0, rel_tol=0.0, abs_tol=1.0e-12
            )
            and len(configured_smoke_ratios) == 1
            and math.isclose(
                configured_smoke_ratios[0], 1.0, rel_tol=0.0, abs_tol=1.0e-12
            )
            and ratios_are_exactly_one(transport)
            and ratios_are_exactly_one(selections)
            and ratios_are_exactly_one(fixed_trajectory)
        ),
        "receiver_capacity_sweep_is_disabled": bool(
            config["transport_sweep"]["receiver_capacity_sweep_target_ids"] == []
            and percentage_config["transport_overrides"][
                "receiver_capacity_sweep_target_ids"
            ]
            == []
        ),
        "convergence_exactly_covers_primary_and_fixed_cases": bool(
            expected_convergence_ids == actual_convergence_ids
        ),
        "source_snapshot_unchanged_during_run": bool(source_snapshot_unchanged),
        "full_system_claim_disabled": bool(
            not energy["full_system_claim_allowed"].any()
            and not summary["full_system_claim_allowed"].any()
        ),
    }
    audit = dict(base_audit)
    audit.update(
        {
            "script_version": SCRIPT_VERSION,
            "study_id": str(percentage_config["study_id"]),
            "percentage_coordinate_count": len(coordinates),
            "transport_percentage_count": int(coordinates["run_transport"].sum()),
            "exact_endpoint_saving_jump_kw": endpoint_jump_kw,
            "fixed_trajectory_status": {
                "case_count": len(fixed_trajectory),
                "target_reached_count": (
                    int(base.bool_series(fixed_trajectory["target_reached"]).sum())
                    if not fixed_trajectory.empty
                    else 0
                ),
                "target_reached_all": bool(
                    fixed_trajectory.empty
                    or base.bool_series(fixed_trajectory["target_reached"]).all()
                ),
                "declared_gate_pass_count": (
                    int(
                        base.bool_series(
                            fixed_trajectory["declared_transport_screen_pass"]
                        ).sum()
                    )
                    if not fixed_trajectory.empty
                    else 0
                ),
                "declared_gate_pass_all": bool(
                    fixed_trajectory.empty
                    or base.bool_series(
                        fixed_trajectory["declared_transport_screen_pass"]
                    ).all()
                ),
                "positive_surface_direction_pass_count": (
                    int(
                        base.bool_series(
                            fixed_trajectory[
                                "positive_surface_direction_screen_pass"
                            ]
                        ).sum()
                    )
                    if not fixed_trajectory.empty
                    else 0
                ),
                "receiver_resource_feasible_count": (
                    int(
                        base.bool_series(
                            fixed_trajectory[
                                "receiver_resource_feasible_without_external_source"
                            ]
                        ).sum()
                    )
                    if not fixed_trajectory.empty
                    else 0
                ),
                "failed_target_ids": (
                    fixed_trajectory.loc[
                        ~base.bool_series(fixed_trajectory["target_reached"]),
                        "target_id",
                    ]
                    .astype(str)
                    .tolist()
                    if not fixed_trajectory.empty
                    else []
                ),
                "failed_declared_gate_target_ids": (
                    fixed_trajectory.loc[
                        ~base.bool_series(
                            fixed_trajectory["declared_transport_screen_pass"]
                        ),
                        "target_id",
                    ]
                    .astype(str)
                    .tolist()
                    if not fixed_trajectory.empty
                    else []
                ),
            },
            "percentage_checks": percentage_checks,
        }
    )
    audit["provenance"] = dict(base_audit["provenance"])
    audit["provenance"].update(
        {
            "percentage_study_script": {
                "path": str(Path(__file__).resolve()),
                "sha256": sha256_file(Path(__file__).resolve()),
            },
            "base_percentage_engine": {
                "path": str(BASE_SCRIPT.resolve()),
                "sha256": sha256_file(BASE_SCRIPT),
            },
            "percentage_config": {
                "path": str(percentage_config_path.resolve()),
                "sha256": sha256_file(percentage_config_path),
            },
            "base_study_config": {
                "path": str(base_config_path.resolve()),
                "sha256": sha256_file(base_config_path),
            },
            "effective_config_sha256": base.sha256_json(config),
        }
    )
    audit["pass"] = bool(base_audit["pass"] and all(percentage_checks.values()))
    return audit


def main() -> None:
    args = parse_args()
    if args.energy_only and args.postprocess_existing:
        raise StudyError("--energy-only and --postprocess-existing are mutually exclusive")
    if args.energy_only and args.smoke:
        raise StudyError("--energy-only and --smoke are mutually exclusive")
    percentage_config_path = args.config.expanduser().resolve()
    percentage_config = read_json(percentage_config_path)
    base_config_path = resolve_path(percentage_config["base_study_config"])
    base_config = read_json(base_config_path)
    base = load_module(BASE_SCRIPT, "post_erv_eo_percentage_base")
    config = effective_config(percentage_config, base_config)
    default_suffix = "_smoke" if args.smoke else ("_energy_only" if args.energy_only else "")
    output = (
        args.output_dir.expanduser().resolve()
        if args.output_dir is not None
        else DEFAULT_OUTPUT.parent / (DEFAULT_OUTPUT.name + default_suffix)
    )
    base.validate_output_mode(output, energy_only=bool(args.energy_only))
    base.validate_output_directory(output, bool(args.overwrite))
    analyzer, runtime, _, source_config_path, analyzer_path = base.load_runtime(
        config,
        v2_root=args.v2_root.expanduser().resolve(),
        area_step_m2=float(config["transport_sweep"]["area_step_m2"]),
    )
    config, coordinates = make_percentage_targets(
        base,
        runtime,
        percentage_config,
        config,
        smoke=bool(args.smoke),
    )
    energy, break_even, endpoint = build_energy_tables(
        base, runtime, coordinates, config
    )
    mode = "energy_only" if args.energy_only else ("smoke" if args.smoke else "study")
    design = (
        pd.DataFrame()
        if args.energy_only
        else base.build_transport_case_design(coordinates, config, smoke=bool(args.smoke))
    )
    initial_source_snapshot = build_source_snapshot(
        runtime,
        percentage_config_path=percentage_config_path,
        base_config_path=base_config_path,
        source_config_path=source_config_path,
        analyzer_path=analyzer_path,
    )
    transport = pd.DataFrame()
    contract_validated = False
    transport_path = output / "transport_cases.csv"
    contract_path = output / "transport_contract.json"
    if args.postprocess_existing:
        validate_transport_contract(
            base,
            contract_path,
            runtime,
            percentage_config,
            config,
            design,
            transport_path,
            percentage_config_path=percentage_config_path,
            base_config_path=base_config_path,
            source_config_path=source_config_path,
            analyzer_path=analyzer_path,
            mode=mode,
        )
        transport = pd.read_csv(transport_path, low_memory=False)
        validate_percentage_transport(base, transport, design, coordinates)
        contract_validated = True
    elif not args.energy_only:
        transport = base.transport_cases(
            analyzer,
            runtime,
            coordinates,
            config,
            jobs=max(1, int(args.jobs)),
            smoke=bool(args.smoke),
        )
        transport = add_percentage_columns(transport, coordinates)
        validate_percentage_transport(base, transport, design, coordinates)

    scenarios = add_percentage_columns(
        base.build_receiver_scenarios(transport, config), coordinates
    )
    voltage_scenarios = add_percentage_columns(
        base.build_voltage_cap_scenarios(transport, config), coordinates
    )
    selections = select_percentage_cases(base, transport)
    selection_status = build_selection_status(
        base, transport, selections, coordinates
    )
    fixed_trajectory = build_fixed_design_trajectory(
        transport, runtime, percentage_config
    )
    convergence_selection = str(
        percentage_config["transport_overrides"]["convergence_selection"]
    )
    allowed_convergence_selections = {"best_conditional_saving", "minimum_area"}
    if convergence_selection not in allowed_convergence_selections:
        raise StudyError(
            "transport_overrides.convergence_selection must be one of "
            + ", ".join(sorted(allowed_convergence_selections))
        )
    convergence_input = build_convergence_population(
        base, selections, fixed_trajectory, convergence_selection
    )
    convergence = base.build_step_halving_convergence(
        analyzer, runtime, coordinates, convergence_input, config
    )
    convergence = add_percentage_columns(convergence, coordinates)
    if not convergence.empty:
        convergence_membership = convergence_input.set_index("case_id")[
            "convergence_population"
        ]
        convergence["convergence_population"] = convergence[
            "source_case_id"
        ].map(convergence_membership)
    power_ledger = base.build_selected_power_ledger(runtime, selections, endpoint)
    power_ledger = add_percentage_columns(power_ledger, coordinates)
    percentage_summary = build_percentage_summary(
        coordinates,
        energy,
        break_even,
        selections,
        selection_status,
        fixed_trajectory,
        percentage_config,
    )

    final_source_snapshot = build_source_snapshot(
        runtime,
        percentage_config_path=percentage_config_path,
        base_config_path=base_config_path,
        source_config_path=source_config_path,
        analyzer_path=analyzer_path,
    )
    source_snapshot_unchanged = initial_source_snapshot == final_source_snapshot
    if not source_snapshot_unchanged:
        raise StudyError(
            "A hashed source/configuration input changed during the percentage run; "
            "discarding results before publication"
        )

    coordinates.to_csv(output / "percentage_coordinates.csv", index=False)
    energy.to_csv(output / "percentage_energy_window.csv", index=False)
    break_even.to_csv(output / "percentage_break_even.csv", index=False)
    endpoint.to_csv(output / "endpoint_control_regime_audit.csv", index=False)
    percentage_summary.to_csv(output / "percentage_summary.csv", index=False)
    base.write_json(output / "percentage_config_used.json", percentage_config)
    base.write_json(output / "effective_config_used.json", config)
    if not transport.empty:
        if not args.postprocess_existing:
            transport.to_csv(transport_path, index=False)
            contract_source_snapshot = build_source_snapshot(
                runtime,
                percentage_config_path=percentage_config_path,
                base_config_path=base_config_path,
                source_config_path=source_config_path,
                analyzer_path=analyzer_path,
            )
            if contract_source_snapshot != initial_source_snapshot:
                raise StudyError(
                    "A hashed source/configuration input changed before contract write"
                )
            contract = build_transport_contract(
                base,
                runtime,
                percentage_config,
                config,
                design,
                transport_path,
                percentage_config_path=percentage_config_path,
                base_config_path=base_config_path,
                source_config_path=source_config_path,
                analyzer_path=analyzer_path,
                mode=mode,
                source_snapshot=initial_source_snapshot,
            )
            base.write_json(contract_path, contract)
            validate_transport_contract(
                base,
                contract_path,
                runtime,
                percentage_config,
                config,
                design,
                transport_path,
                percentage_config_path=percentage_config_path,
                base_config_path=base_config_path,
                source_config_path=source_config_path,
                analyzer_path=analyzer_path,
                mode=mode,
            )
            contract_validated = True
        scenarios.to_csv(output / "receiver_and_sink_sec_scenarios.csv", index=False)
        voltage_scenarios.to_csv(output / "terminal_voltage_cap_scenarios.csv", index=False)
        selections.to_csv(output / "selected_transport_cases.csv", index=False)
        selection_status.to_csv(output / "selection_status.csv", index=False)
        convergence.to_csv(output / "step_halving_convergence.csv", index=False)
        power_ledger.to_csv(output / "selected_power_ledger.csv", index=False)
        fixed_trajectory.to_csv(
            output / "fixed_coordinate_sizing_trajectory.csv", index=False
        )
    plot_percentage_energy(
        percentage_summary, percentage_config, output / "percentage_energy_saving.png"
    )
    if not transport.empty:
        plot_percentage_transport(
            percentage_summary, output / "percentage_membrane_receiver.png"
        )
        plot_percentage_sec_budget(
            percentage_summary, output / "percentage_sec_budget.png"
        )
    summary_text = build_summary_markdown(
        base,
        runtime,
        percentage_summary,
        transport,
        selections,
        convergence,
        percentage_config,
        mode=mode,
    )
    (output / "SUMMARY.md").write_text(summary_text, encoding="utf-8")
    audit = build_audit(
        base,
        runtime,
        percentage_config,
        config,
        coordinates,
        energy,
        break_even,
        transport,
        selections,
        endpoint,
        convergence,
        percentage_summary,
        selection_status,
        fixed_trajectory,
        contract_validated,
        source_snapshot_unchanged,
        percentage_config_path=percentage_config_path,
        base_config_path=base_config_path,
        source_config_path=source_config_path,
        analyzer_path=analyzer_path,
        mode=mode,
    )
    base.write_json(output / "audit.json", audit)
    if not audit["pass"]:
        raise StudyError(f"Percentage study audit failed; inspect {output / 'audit.json'}")
    print(f"Wrote percentage {mode} study to {output}")
    print(
        "Historical 10% closes",
        f"{value_at(percentage_summary, 'post_erv_10pct', 'remaining_duty_completion_pct'):.6f}%",
        "of the remaining duty.",
    )


if __name__ == "__main__":
    main()
