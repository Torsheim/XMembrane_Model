#!/usr/bin/env python3
"""
HeiQ WP1 — pre-architecture bottleneck diagnostics v1.1

Purpose
-------
Quantify what limits the O30/O50 coupled axial EO core before any receiver-side
ERV, HRV, regeneration, condensation or other architecture is introduced.

The script uses the reviewed V12.1 coupled two-stream core through the helper
`make_wp1_prearchitecture_continuation_v2.py`:

- process and receiver humidity both march axially;
- the unchanged V2/V3 local voltage-controlled membrane BVP is re-solved;
- process- and receiver-side gas films are retained;
- target landing, water balance, current, area, voltage and generic channel
  fan power are recalculated for every full coupled case.

Studies
-------
film
    Process-only, receiver-only and balanced gas-film coefficient sensitivity.
    A factor of 1e4 is the finite numerical proxy for K -> infinity.

receiver
    Receiver inlet activity and receiver dry-air capacity multiplier sweep.

corners
    Four-corner decomposition:
        real films / baseline receiver
        near-ideal films / baseline receiver
        real films / dry receiver
        near-ideal films / dry receiver

area
    Area-energy Pareto sweep with voltage re-optimisation.

diffusion
    Diffusivity-factor mechanism sweep. D=0 is represented by 1e-20 m2/s and
    is explicitly labelled a near-zero-diffusion numerical proxy.

budget
    Reconstruct local ohmic, water-polarisation and series-ASR voltage terms,
    EO/diffusive/net flux and surface activities along the selected profile.

zoned
    First-order 3-zone and 5-zone voltage-schedule replay on the converged
    uniform-voltage bulk profile. This is diagnostic only; it is NOT a full
    coupled zoned-voltage re-integration.

all
    Run every study above.

Important
---------
A negative membrane-surface activity margin is diagnostic, not an automatic
failure in this active-EO pre-architecture model. The hard local transport gate
is positive net water flux with physical local states and current below cap.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import importlib.util
import json
import math
import sys
from dataclasses import asdict
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, Iterable, Mapping, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from heiq.wp1.axial import solve_local_state
from heiq.wp1.engineering import add_geometry_and_stack
from heiq.wp1.receiver import (
    MATERIAL_COLUMNS,
    integrate_coupled_receiver_case,
    make_receiver_basis,
)

ROOT = Path(__file__).resolve().parents[1]
CONTINUATION_SCRIPT = ROOT / "scripts" / "make_wp1_prearchitecture_continuation_v2.py"

WATER_MOLAR_MASS_KG_MOL = 0.01801528
NEAR_IDEAL_FILM_FACTOR = 1.0e4

FILM_FACTORS = [0.5, 1.0, 2.0, 5.0, 10.0, NEAR_IDEAL_FILM_FACTOR]
RECEIVER_INLET_ACTIVITIES = [0.10, 0.20, 0.30, 0.40, 0.50]
RECEIVER_CAPACITY_MULTIPLIERS = [1.01, 1.05, 1.10, 1.25, 1.50, 2.00]
AREA_LIMITS_M2 = [3000.0, 4500.0, 6000.0, 7500.0, 9000.0, 12000.0]
DIFFUSIVITY_FACTORS = [0.0, 0.1, 0.5, 1.0, 2.0, 10.0]

DEFAULT_BASELINE_PATHS = [
    "outputs/prearchitecture_continuation_v2/material_global/overall_best.csv",
    "outputs/prearchitecture_continuation_v2/o30_receiver/overall_best.csv",
    "outputs/prearchitecture_material_screen_9000m2_v1/overall_best_by_target.csv",
    "outputs/prearchitecture_material_screen_9000m2_v1/best_by_drag.csv",
]

NUMERIC_EPS = 1.0e-12


def load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def finite(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return math.nan
    return result if math.isfinite(result) else math.nan


def truth(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    return str(value).strip().lower() in {"true", "1", "yes"}


def first_finite(mapping: Mapping[str, Any], names: Sequence[str], default: float = math.nan) -> float:
    for name in names:
        if name in mapping:
            value = finite(mapping[name])
            if math.isfinite(value):
                return value
    return default


def first_value(mapping: Mapping[str, Any], names: Sequence[str], default: Any = None) -> Any:
    for name in names:
        if name in mapping and pd.notna(mapping[name]):
            return mapping[name]
    return default


def unique_sorted(values: Iterable[float], lo: float = 0.0, hi: float = math.inf) -> list[float]:
    return sorted(
        {
            round(float(value), 10)
            for value in values
            if math.isfinite(float(value)) and lo <= float(value) <= hi
        }
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stage",
        choices=["film", "receiver", "corners", "area", "diffusion", "budget", "zoned", "all"],
        default="all",
    )
    parser.add_argument("--target", choices=["O50", "O30"], default="O30")
    parser.add_argument(
        "--output-dir",
        default="outputs/prearchitecture_bottleneck_diagnostics_v1",
    )
    parser.add_argument("--baseline-csv", type=Path)
    parser.add_argument("--area-max-m2", type=float, default=9000.0)
    parser.add_argument("--voltage-max-v", type=float, default=2.0)
    parser.add_argument("--receiver-band", default="bridge_40_to_60")
    parser.add_argument("--receiver-temperature-c", type=float, default=None)
    parser.add_argument("--receiver-band-span", type=float, default=0.20)
    parser.add_argument("--dry-receiver-inlet-activity", type=float, default=0.10)
    parser.add_argument("--dry-receiver-maximum-activity", type=float, default=0.30)
    parser.add_argument("--fallback-water-drag", type=float, default=150.0)
    parser.add_argument("--fallback-voltage-v", type=float, default=1.59375)
    parser.add_argument("--fallback-receiver-multiplier", type=float, default=1.25)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def setup_context(args: argparse.Namespace) -> tuple[ModuleType, dict[str, Any]]:
    if not CONTINUATION_SCRIPT.is_file():
        raise FileNotFoundError(
            f"Missing {CONTINUATION_SCRIPT}. Copy "
            "make_wp1_prearchitecture_continuation_v2.py into scripts/ first."
        )
    continuation = load_module(CONTINUATION_SCRIPT, "heiq_prearchitecture_continuation_for_diagnostics")
    setup_args = SimpleNamespace(
        receiver_band=str(args.receiver_band),
        receiver_temperature_c=args.receiver_temperature_c,
        area_max_m2=float(args.area_max_m2),
        voltage_max_v=float(args.voltage_max_v),
        lhs_samples=8,
        seed=20260812,
        smoke=False,
    )
    context = continuation.setup(setup_args)
    return continuation, context


def select_baseline_row(args: argparse.Namespace) -> tuple[pd.Series, str]:
    paths: list[Path] = []
    if args.baseline_csv is not None:
        paths.append(args.baseline_csv)
    paths.extend(ROOT / path for path in DEFAULT_BASELINE_PATHS)

    for path in paths:
        if not path.is_file():
            continue

        # Some upstream stages deliberately write a zero-column CSV when no
        # candidate passes.  pandas raises EmptyDataError for those files.
        # Such a file means "no usable baseline here", so skip it and try the
        # next candidate path instead of aborting the diagnostics run.
        try:
            frame = pd.read_csv(path)
        except pd.errors.EmptyDataError:
            continue
        except (pd.errors.ParserError, OSError):
            continue

        if frame.empty or len(frame.columns) == 0:
            continue

        if "target" in frame.columns:
            target_rows = frame[frame["target"].astype(str).eq(args.target)]
            # Do not silently use (for example) an O50 row as the O30
            # baseline merely because the file exists.
            if target_rows.empty:
                continue
            frame = target_rows

        pass_columns = [
            "analysis_pass",
            "screen_target_pass",
            "material_screen_pass",
            "target_reached",
        ]
        for column in pass_columns:
            if column in frame.columns:
                passed = frame[frame[column].map(truth)]
                if not passed.empty:
                    frame = passed
                    break

        power_columns = ["analysis_core_power_kw", "screen_core_power_kw"]
        power_column = next((name for name in power_columns if name in frame.columns), None)
        if power_column is not None:
            frame = frame.assign(
                _rank_power=pd.to_numeric(frame[power_column], errors="coerce")
            ).sort_values("_rank_power", kind="mergesort")

        return frame.iloc[0].copy(), str(path)

    fallback = pd.Series(
        {
            "target": args.target,
            "water_drag": float(args.fallback_water_drag),
            "water_diffusivity_m2_s": 1.0e-12,
            "conductivity_s_m": 50.0,
            "dry_thickness_um": 100.0,
            "terminal_voltage_v": float(args.fallback_voltage_v),
            "analysis_receiver_capacity_multiplier": float(args.fallback_receiver_multiplier),
            "baseline_source": "declared_fallback",
        }
    )
    return fallback, "declared_fallback"


def material_from_baseline(
    continuation: ModuleType,
    context: dict[str, Any],
    baseline: Mapping[str, Any],
) -> dict[str, Any]:
    _ = continuation
    base = context["m11675"]

    properties: dict[str, float] = {}

    for name in MATERIAL_COLUMNS:
        value = finite(
            baseline.get(name, math.nan)
        )

        properties[name] = (
            value
            if math.isfinite(value)
            else float(base[name])
        )

    return {
        "name": (
            f"diagnostic_tw{properties['water_drag']:.6g}_"
            f"D{properties['water_diffusivity_m2_s']:.3e}_"
            f"sig{properties['conductivity_s_m']:.6g}_"
            f"L{properties['dry_thickness_um']:.6g}"
        ),
        "model": "powerlaw",
        **properties,
        "interpretation":
            "Selected pre-architecture baseline property vector",
    }



def baseline_voltage(baseline: Mapping[str, Any], args: argparse.Namespace) -> float:
    value = first_finite(
        baseline,
        ["terminal_voltage_v", "screen_terminal_voltage_v"],
        float(args.fallback_voltage_v),
    )
    return float(np.clip(value, 1.0e-5, args.voltage_max_v))


def baseline_receiver_multiplier(baseline: Mapping[str, Any], args: argparse.Namespace) -> float:
    return first_finite(
        baseline,
        [
            "analysis_receiver_capacity_multiplier",
            "capacity_multiplier",
            "receiver_capacity_multiplier",
        ],
        float(args.fallback_receiver_multiplier),
    )


def default_band(context: dict[str, Any], args: argparse.Namespace) -> dict[str, float]:
    band = context["cfg12"]["receiver_bands"][str(args.receiver_band)]
    return {
        "inlet_activity": float(band["inlet_activity"]),
        "maximum_outlet_activity": float(band["maximum_outlet_activity"]),
    }


def make_receiver(
    context: dict[str, Any],
    *,
    target: str,
    capacity_multiplier: float,
    band: Mapping[str, float],
    band_id: str,
) -> Any:
    return make_receiver_basis(
        axial=None,
        process_basis=context["process_basis"],
        target_row=context["targets"][target],
        receiver_sizing_target_row=context["targets"][target],
        band_id=band_id,
        band=band,
        capacity_multiplier=float(capacity_multiplier),
        flow_arrangement="counter_current",
        base_config=context["base"],
    )





@contextlib.contextmanager
def temporary_area_limit(context: dict[str, Any], area_limit_m2: float):
    original = float(context["base"]["integration"]["area_limit_m2"])
    context["base"]["integration"]["area_limit_m2"] = float(area_limit_m2)
    try:
        yield
    finally:
        context["base"]["integration"]["area_limit_m2"] = original


def solve_full_case(
    context: dict[str, Any],
    *,
    target: str,
    material: Mapping[str, Any],
    terminal_voltage_v: float,
    receiver_multiplier: float,
    receiver_band: Mapping[str, float],
    receiver_band_id: str,
    process_film_factor: float = 1.0,
    receiver_film_factor: float = 1.0,
    area_limit_m2: float | None = None,
    record_profile: bool = False,
) -> tuple[dict[str, Any], pd.DataFrame, Any]:
    base = context["base"]
    cfg12 = context["cfg12"]

    if (
        process_film_factor <= 0.0
        or receiver_film_factor <= 0.0
    ):
        raise ValueError(
            "Film factors must be positive"
        )

    receiver = make_receiver(
        context,
        target=target,
        capacity_multiplier=receiver_multiplier,
        band=receiver_band,
        band_id=receiver_band_id,
    )

    selected_area_limit = (
        float(area_limit_m2)
        if area_limit_m2 is not None
        else float(
            base["integration"]["area_limit_m2"]
        )
    )

    base_film_scale = float(
        cfg12["operating"]["film_scale_factor"]
    )

    with temporary_area_limit(
        context,
        selected_area_limit,
    ):
        row, profile = (
            integrate_coupled_receiver_case(
                axial=None,
                v2=context["v2"],
                v2_config=context["v2_config"],
                config=base,
                process_basis=context["process_basis"],
                target_row=context["targets"][target],
                material=dict(material),
                receiver=receiver,
                terminal_voltage_v=float(
                    terminal_voltage_v
                ),
                electrode_pair_loss_voltage_v=0.0,
                legacy_series_asr_ohm_m2=float(
                    cfg12["operating"][
                        "legacy_series_asr_ohm_m2"
                    ]
                ),
                added_contact_asr_ohm_m2=0.0,
                power_electronics_efficiency=float(
                    cfg12["operating"][
                        "power_electronics_efficiency"
                    ]
                ),
                current_cap_a_m2=float(
                    cfg12["operating"][
                        "current_density_cap_a_m2"
                    ]
                ),
                film_scale_factor=base_film_scale,
                process_film_scale_factor=(
                    base_film_scale
                    * float(process_film_factor)
                ),
                receiver_film_scale_factor=(
                    base_film_scale
                    * float(receiver_film_factor)
                ),
                record_profile=record_profile,
            )
        )

    row = add_geometry_and_stack(
        row=row,
        axial=None,
        process_basis=context["process_basis"],
        base_config=base,
        v12_config=cfg12,
    )

    eo = finite(
        row.get("eo_grid_power_kw")
    )

    process_fan = finite(
        row.get(
            "process_channel_fan_power_kw"
        )
    )

    receiver_fan = finite(
        row.get(
            "receiver_channel_fan_power_kw"
        )
    )

    core_power = (
        eo + process_fan + receiver_fan
        if all(
            math.isfinite(value)
            for value in (
                eo,
                process_fan,
                receiver_fan,
            )
        )
        else math.nan
    )

    water = finite(
        row.get(
            "integrated_water_transfer_kg_h"
        )
    )

    area = finite(
        row.get(
            "required_active_area_m2"
        )
    )

    max_current = finite(
        row.get(
            "maximum_local_current_density_a_m2"
        )
    )

    min_flux = finite(
        row.get(
            "minimum_local_flux_mol_m2_s"
        )
    )

    current_cap = float(
        cfg12["operating"][
            "current_density_cap_a_m2"
        ]
    )

    analysis_pass = bool(
        truth(
            row.get("target_reached")
        )
        and truth(
            row.get("water_balance_pass")
        )
        and truth(
            row.get(
                "target_capacity_sufficient"
            )
        )
        and math.isfinite(area)
        and area
        <= selected_area_limit + 1.0e-9
        and math.isfinite(max_current)
        and 0.0
        < max_current
        <= current_cap + 1.0e-9
        and math.isfinite(min_flux)
        and min_flux > 0.0
        and math.isfinite(core_power)
    )

    row.update(
        {
            "diagnostic_target":
                target,

            "diagnostic_terminal_voltage_v":
                float(terminal_voltage_v),

            "diagnostic_process_film_factor":
                float(process_film_factor),

            "diagnostic_receiver_film_factor":
                float(receiver_film_factor),

            "diagnostic_area_limit_m2":
                selected_area_limit,

            "diagnostic_receiver_band_id":
                receiver_band_id,

            "diagnostic_receiver_inlet_activity":
                float(
                    receiver_band[
                        "inlet_activity"
                    ]
                ),

            "diagnostic_receiver_maximum_activity":
                float(
                    receiver_band[
                        "maximum_outlet_activity"
                    ]
                ),

            "diagnostic_receiver_capacity_multiplier":
                float(receiver_multiplier),

            "diagnostic_receiver_to_process_flow_ratio":
                float(
                    receiver
                    .receiver_to_process_dry_air_ratio
                ),

            "diagnostic_core_power_kw":
                core_power,

            "diagnostic_core_sec_kwh_kg":
                (
                    core_power / water
                    if (
                        math.isfinite(core_power)
                        and water > 0.0
                    )
                    else math.nan
                ),

            "diagnostic_analysis_pass":
                analysis_pass,
        }
    )

    return row, profile, receiver



def voltage_grid(center_v: float, max_v: float, smoke: bool = False) -> list[float]:
    if smoke:
        scales = [0.85, 1.0, 1.15]
        absolutes = [0.25, 0.75, 1.25, max_v]
    else:
        scales = [0.60, 0.72, 0.82, 0.90, 0.96, 1.0, 1.04, 1.10, 1.20, 1.35, 1.50]
        absolutes = [0.03, 0.05, 0.10, 0.25, 0.50, 0.75, 1.00, 1.25, 1.50, 1.75, max_v]
    values = [center_v * scale for scale in scales] + absolutes + [center_v]
    return unique_sorted(values, lo=1.0e-5, hi=max_v)


def optimise_voltage(
    context: dict[str, Any],
    *,
    target: str,
    material: Mapping[str, Any],
    center_voltage_v: float,
    voltage_max_v: float,
    receiver_multiplier: float,
    receiver_band: Mapping[str, float],
    receiver_band_id: str,
    process_film_factor: float = 1.0,
    receiver_film_factor: float = 1.0,
    area_limit_m2: float | None = None,
    smoke: bool = False,
) -> tuple[pd.DataFrame, pd.Series | None]:
    rows: list[dict[str, Any]] = []
    for voltage in voltage_grid(center_voltage_v, voltage_max_v, smoke=smoke):
        row, _, _ = solve_full_case(
            context,
            target=target,
            material=material,
            terminal_voltage_v=voltage,
            receiver_multiplier=receiver_multiplier,
            receiver_band=receiver_band,
            receiver_band_id=receiver_band_id,
            process_film_factor=process_film_factor,
            receiver_film_factor=receiver_film_factor,
            area_limit_m2=area_limit_m2,
            record_profile=False,
        )
        rows.append(row)

    frame = pd.DataFrame(rows)
    passing = frame[frame["diagnostic_analysis_pass"].map(truth)].copy()
    if passing.empty:
        return frame, None

    best = (
        passing.sort_values(
            [
                "diagnostic_core_power_kw",
                "required_active_area_m2",
                "diagnostic_terminal_voltage_v",
            ],
            kind="mergesort",
        )
        .iloc[0]
        .copy()
    )
    return frame, best


def save_plot(
    path: Path,
    x: Sequence[float],
    ys: Mapping[str, Sequence[float]],
    *,
    xlabel: str,
    ylabel: str,
    title: str,
    xscale: str | None = None,
    horizontal_lines: Sequence[tuple[float, str]] = (),
):
    fig, ax = plt.subplots(figsize=(7.5, 4.8))
    for label, values in ys.items():
        ax.plot(x, values, marker="o", label=label)
    for value, label in horizontal_lines:
        ax.axhline(value, linestyle="--", label=label)
    if xscale is not None:
        ax.set_xscale(xscale)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(alpha=0.25)
    if len(ys) + len(horizontal_lines) > 1:
        ax.legend()
    fig.tight_layout()
    fig.savefig(path.with_suffix(".png"), dpi=220)
    fig.savefig(path.with_suffix(".pdf"))
    plt.close(fig)


def run_film_study(
    context: dict[str, Any],
    material: Mapping[str, Any],
    baseline_v: float,
    receiver_mult: float,
    args: argparse.Namespace,
    out: Path,
):
    stage = out / "film"
    stage.mkdir(parents=True, exist_ok=True)
    factors = [1.0, 5.0, NEAR_IDEAL_FILM_FACTOR] if args.smoke else FILM_FACTORS

    all_rows: list[pd.DataFrame] = []
    best_rows: list[dict[str, Any]] = []
    band = default_band(context, args)

    modes = {
        "balanced_both": lambda factor: (factor, factor),
        "process_only": lambda factor: (factor, 1.0),
        "receiver_only": lambda factor: (1.0, factor),
    }

    for mode, mapping in modes.items():
        for factor in factors:
            process_factor, receiver_factor = mapping(factor)
            frame, best = optimise_voltage(
                context,
                target=args.target,
                material=material,
                center_voltage_v=baseline_v,
                voltage_max_v=args.voltage_max_v,
                receiver_multiplier=receiver_mult,
                receiver_band=band,
                receiver_band_id=f"{args.receiver_band}_{mode}_{factor:g}",
                process_film_factor=process_factor,
                receiver_film_factor=receiver_factor,
                area_limit_m2=args.area_max_m2,
                smoke=args.smoke,
            )
            frame["film_mode"] = mode
            frame["film_factor_tested"] = factor
            all_rows.append(frame)
            if best is not None:
                record = best.to_dict()
                record.update({"film_mode": mode, "film_factor_tested": factor})
                best_rows.append(record)

    all_cases = pd.concat(all_rows, ignore_index=True)
    best = pd.DataFrame(best_rows)
    all_cases.to_csv(stage / "all_cases.csv.gz", index=False, compression="gzip")
    best.to_csv(stage / "best_by_film_mode_factor.csv", index=False)

    if not best.empty:
        for mode, group in best.groupby("film_mode", sort=True):
            ordered = group.sort_values("film_factor_tested")
            save_plot(
                stage / f"core_power_{mode}",
                ordered["film_factor_tested"],
                {"Core power": ordered["diagnostic_core_power_kw"]},
                xlabel="Gas-film coefficient multiplier [-]",
                ylabel="EO + process fan + receiver fan [kW]",
                title=f"{args.target}: {mode.replace('_', ' ')} film sensitivity",
                xscale="log",
            )
            save_plot(
                stage / f"area_{mode}",
                ordered["film_factor_tested"],
                {"Required area": ordered["required_active_area_m2"]},
                xlabel="Gas-film coefficient multiplier [-]",
                ylabel="Required active area [m²]",
                title=f"{args.target}: {mode.replace('_', ' ')} area response",
                xscale="log",
                horizontal_lines=[(args.area_max_m2, "Area gate")],
            )


def receiver_activity_grid(args: argparse.Namespace) -> list[float]:
    if args.smoke:
        return [0.20, 0.40]
    return RECEIVER_INLET_ACTIVITIES


def receiver_multiplier_grid(args: argparse.Namespace) -> list[float]:
    if args.smoke:
        return [1.05, 1.25]
    return RECEIVER_CAPACITY_MULTIPLIERS


def run_receiver_study(
    context: dict[str, Any],
    material: Mapping[str, Any],
    baseline_v: float,
    args: argparse.Namespace,
    out: Path,
):
    stage = out / "receiver"
    stage.mkdir(parents=True, exist_ok=True)

    all_frames: list[pd.DataFrame] = []
    best_rows: list[dict[str, Any]] = []

    for inlet_activity in receiver_activity_grid(args):
        maximum_activity = min(0.95, inlet_activity + args.receiver_band_span)
        if maximum_activity <= inlet_activity:
            continue
        band = {
            "inlet_activity": inlet_activity,
            "maximum_outlet_activity": maximum_activity,
        }
        for multiplier in receiver_multiplier_grid(args):
            frame, best = optimise_voltage(
                context,
                target=args.target,
                material=material,
                center_voltage_v=baseline_v,
                voltage_max_v=args.voltage_max_v,
                receiver_multiplier=multiplier,
                receiver_band=band,
                receiver_band_id=f"custom_{inlet_activity:.3f}_to_{maximum_activity:.3f}",
                area_limit_m2=args.area_max_m2,
                smoke=args.smoke,
            )
            frame["receiver_inlet_activity_tested"] = inlet_activity
            frame["receiver_maximum_activity_tested"] = maximum_activity
            frame["receiver_capacity_multiplier_tested"] = multiplier
            all_frames.append(frame)
            if best is not None:
                record = best.to_dict()
                record.update(
                    {
                        "receiver_inlet_activity_tested": inlet_activity,
                        "receiver_maximum_activity_tested": maximum_activity,
                        "receiver_capacity_multiplier_tested": multiplier,
                    }
                )
                best_rows.append(record)

    all_cases = pd.concat(all_frames, ignore_index=True)
    best = pd.DataFrame(best_rows)
    all_cases.to_csv(stage / "all_cases.csv.gz", index=False, compression="gzip")
    best.to_csv(stage / "best_by_receiver_condition.csv", index=False)

    if not best.empty:
        overall = (
            best.sort_values(
                ["diagnostic_core_power_kw", "required_active_area_m2"],
                kind="mergesort",
            )
            .head(1)
            .copy()
        )
        overall.to_csv(stage / "overall_best.csv", index=False)

        for activity, group in best.groupby("receiver_inlet_activity_tested", sort=True):
            ordered = group.sort_values("receiver_capacity_multiplier_tested")
            save_plot(
                stage / f"core_power_inlet_activity_{activity:.3f}",
                ordered["receiver_capacity_multiplier_tested"],
                {"Core power": ordered["diagnostic_core_power_kw"]},
                xlabel="Receiver capacity multiplier [-]",
                ylabel="EO + process fan + receiver fan [kW]",
                title=f"{args.target}: receiver inlet activity {activity:.2f}",
            )

        pivot = best.pivot_table(
            index="receiver_inlet_activity_tested",
            columns="receiver_capacity_multiplier_tested",
            values="diagnostic_core_power_kw",
            aggfunc="min",
        )
        pivot.to_csv(stage / "core_power_pivot.csv")


def run_corner_study(
    context: dict[str, Any],
    material: Mapping[str, Any],
    baseline_v: float,
    receiver_mult: float,
    args: argparse.Namespace,
    out: Path,
):
    stage = out / "corners"
    stage.mkdir(parents=True, exist_ok=True)

    real_band = default_band(context, args)
    dry_band = {
        "inlet_activity": float(args.dry_receiver_inlet_activity),
        "maximum_outlet_activity": float(args.dry_receiver_maximum_activity),
    }
    cases = [
        ("real_films_real_receiver", 1.0, 1.0, real_band),
        ("near_ideal_films_real_receiver", NEAR_IDEAL_FILM_FACTOR, NEAR_IDEAL_FILM_FACTOR, real_band),
        ("real_films_dry_receiver", 1.0, 1.0, dry_band),
        ("near_ideal_films_dry_receiver", NEAR_IDEAL_FILM_FACTOR, NEAR_IDEAL_FILM_FACTOR, dry_band),
    ]

    all_frames: list[pd.DataFrame] = []
    best_rows: list[dict[str, Any]] = []
    for case_id, process_factor, receiver_factor, band in cases:
        frame, best = optimise_voltage(
            context,
            target=args.target,
            material=material,
            center_voltage_v=baseline_v,
            voltage_max_v=args.voltage_max_v,
            receiver_multiplier=receiver_mult,
            receiver_band=band,
            receiver_band_id=case_id,
            process_film_factor=process_factor,
            receiver_film_factor=receiver_factor,
            area_limit_m2=args.area_max_m2,
            smoke=args.smoke,
        )
        frame["corner_case_id"] = case_id
        all_frames.append(frame)
        if best is not None:
            record = best.to_dict()
            record["corner_case_id"] = case_id
            best_rows.append(record)

    all_cases = pd.concat(all_frames, ignore_index=True)
    best = pd.DataFrame(best_rows)
    all_cases.to_csv(stage / "all_cases.csv.gz", index=False, compression="gzip")
    best.to_csv(stage / "corner_comparison.csv", index=False)

    if not best.empty:
        fig, ax = plt.subplots(figsize=(8.0, 4.8))
        ax.bar(best["corner_case_id"], best["diagnostic_core_power_kw"])
        ax.set_ylabel("EO + process fan + receiver fan [kW]")
        ax.set_title(f"{args.target}: film versus receiver bottleneck decomposition")
        ax.grid(axis="y", alpha=0.25)
        ax.tick_params(axis="x", rotation=20)
        fig.tight_layout()
        fig.savefig(stage / "corner_core_power.png", dpi=220)
        fig.savefig(stage / "corner_core_power.pdf")
        plt.close(fig)


def run_area_study(
    context: dict[str, Any],
    material: Mapping[str, Any],
    baseline_v: float,
    receiver_mult: float,
    args: argparse.Namespace,
    out: Path,
):
    stage = out / "area"
    stage.mkdir(parents=True, exist_ok=True)
    limits = [6000.0, 9000.0] if args.smoke else AREA_LIMITS_M2
    band = default_band(context, args)

    all_frames: list[pd.DataFrame] = []
    best_rows: list[dict[str, Any]] = []
    for limit in limits:
        frame, best = optimise_voltage(
            context,
            target=args.target,
            material=material,
            center_voltage_v=baseline_v,
            voltage_max_v=args.voltage_max_v,
            receiver_multiplier=receiver_mult,
            receiver_band=band,
            receiver_band_id=f"{args.receiver_band}_area_{limit:g}",
            area_limit_m2=limit,
            smoke=args.smoke,
        )
        frame["area_limit_tested_m2"] = limit
        all_frames.append(frame)
        if best is not None:
            record = best.to_dict()
            record["area_limit_tested_m2"] = limit
            best_rows.append(record)

    all_cases = pd.concat(all_frames, ignore_index=True)
    best = pd.DataFrame(best_rows)
    all_cases.to_csv(stage / "all_cases.csv.gz", index=False, compression="gzip")
    best.to_csv(stage / "area_energy_pareto.csv", index=False)

    if not best.empty:
        ordered = best.sort_values("area_limit_tested_m2")
        save_plot(
            stage / "core_power_vs_area_limit",
            ordered["area_limit_tested_m2"],
            {"Core power": ordered["diagnostic_core_power_kw"]},
            xlabel="Allowed active area [m²]",
            ylabel="EO + process fan + receiver fan [kW]",
            title=f"{args.target}: area-energy Pareto",
        )
        save_plot(
            stage / "optimal_voltage_vs_area_limit",
            ordered["area_limit_tested_m2"],
            {"Optimal tested voltage": ordered["diagnostic_terminal_voltage_v"]},
            xlabel="Allowed active area [m²]",
            ylabel="Terminal voltage [V]",
            title=f"{args.target}: voltage re-optimisation by area gate",
        )


def run_diffusion_study(
    continuation: ModuleType,
    context: dict[str, Any],
    material: Mapping[str, Any],
    baseline_v: float,
    receiver_mult: float,
    args: argparse.Namespace,
    out: Path,
):
    stage = out / "diffusion"
    stage.mkdir(parents=True, exist_ok=True)
    factors = [0.0, 1.0, 10.0] if args.smoke else DIFFUSIVITY_FACTORS
    band = default_band(context, args)
    base_diffusivity = float(material["water_diffusivity_m2_s"])

    all_frames: list[pd.DataFrame] = []
    best_rows: list[dict[str, Any]] = []
    for factor in factors:
        tested_diffusivity = 1.0e-20 if factor == 0.0 else base_diffusivity * factor
        changed = dict(material)
        changed["water_diffusivity_m2_s"] = tested_diffusivity
        changed["name"] = f"{material['name']}_Dfactor_{factor:g}"

        frame, best = optimise_voltage(
            context,
            target=args.target,
            material=changed,
            center_voltage_v=baseline_v,
            voltage_max_v=args.voltage_max_v,
            receiver_multiplier=receiver_mult,
            receiver_band=band,
            receiver_band_id=f"{args.receiver_band}_Dfactor_{factor:g}",
            area_limit_m2=args.area_max_m2,
            smoke=args.smoke,
        )
        frame["diffusivity_factor_tested"] = factor
        frame["near_zero_diffusivity_proxy"] = factor == 0.0
        all_frames.append(frame)
        if best is not None:
            record = best.to_dict()
            record.update(
                {
                    "diffusivity_factor_tested": factor,
                    "near_zero_diffusivity_proxy": factor == 0.0,
                }
            )
            best_rows.append(record)

    all_cases = pd.concat(all_frames, ignore_index=True)
    best = pd.DataFrame(best_rows)
    all_cases.to_csv(stage / "all_cases.csv.gz", index=False, compression="gzip")
    best.to_csv(stage / "best_by_diffusivity_factor.csv", index=False)

    if not best.empty:
        ordered = best.sort_values("diffusivity_factor_tested")
        x = ordered["diffusivity_factor_tested"].replace({0.0: 0.01})
        save_plot(
            stage / "core_power_vs_diffusivity",
            x,
            {"Core power": ordered["diagnostic_core_power_kw"]},
            xlabel="Diffusivity factor (0 plotted at 0.01) [-]",
            ylabel="EO + process fan + receiver fan [kW]",
            title=f"{args.target}: diffusion mechanism sensitivity",
            xscale="log",
        )
        save_plot(
            stage / "area_vs_diffusivity",
            x,
            {"Required area": ordered["required_active_area_m2"]},
            xlabel="Diffusivity factor (0 plotted at 0.01) [-]",
            ylabel="Required active area [m²]",
            title=f"{args.target}: area response to water diffusivity",
            xscale="log",
            horizontal_lines=[(args.area_max_m2, "Area gate")],
        )


def local_field(local: Mapping[str, Any], names: Sequence[str]) -> float:
    return first_finite(local, names)


def reconstruct_local_profile(
    context: dict[str, Any],
    *,
    material: Mapping[str, Any],
    terminal_voltage_v: float,
    profile: pd.DataFrame,
    receiver: Any,
    process_film_factor: float = 1.0,
    receiver_film_factor: float = 1.0,
) -> pd.DataFrame:
    cfg12 = context["cfg12"]

    local_config = copy.deepcopy(
        context["base"]
    )

    local_config["channel"] = copy.deepcopy(
        context["base"]["channel"]
    )

    local_config["channel"][
        "receiver_velocity_m_s"
    ] = receiver.receiver_velocity_m_s

    rows: list[dict[str, Any]] = []

    total_area = max(
        float(
            profile[
                "cumulative_area_m2"
            ].max()
        ),
        NUMERIC_EPS,
    )

    base_film_scale = float(
        cfg12["operating"][
            "film_scale_factor"
        ]
    )

    for _, point in profile.iterrows():
        process_w = first_finite(
            point,
            [
                "process_humidity_ratio_kg_kg_da",
                "humidity_ratio_kg_kg_da",
            ],
        )

        receiver_activity = first_finite(
            point,
            [
                "receiver_activity",
                "receiver_bulk_activity",
            ],
        )

        if not (
            math.isfinite(process_w)
            and math.isfinite(
                receiver_activity
            )
        ):
            continue

        local = solve_local_state(
            v2=context["v2"],
            v2_config=context[
                "v2_config"
            ],
            material=dict(material),
            source_temperature_c=float(
                context[
                    "process_basis"
                ].inlet_temperature_c
            ),
            source_humidity_ratio=process_w,
            receiver_activity=receiver_activity,
            terminal_voltage_v=float(
                terminal_voltage_v
            ),
            fixed_loss_voltage_v=0.0,
            series_asr_ohm_m2=float(
                cfg12["operating"][
                    "legacy_series_asr_ohm_m2"
                ]
            ),
            film_scale_factor=(
                base_film_scale
            ),
            process_film_scale_factor=(
                base_film_scale
                * float(
                    process_film_factor
                )
            ),
            receiver_film_scale_factor=(
                base_film_scale
                * float(
                    receiver_film_factor
                )
            ),
            config=local_config,
        )

        if not bool(
            local.get(
                "solution_ok",
                False,
            )
        ):
            continue

        current = finite(
            local.get(
                "current_density_a_m2"
            )
        )

        ohmic = finite(
            local.get(
                "ohmic_voltage_v"
            )
        )

        water_voltage = finite(
            local.get(
                "water_polarisation_voltage_v"
            )
        )

        series_voltage = finite(
            local.get(
                "series_loss_voltage_v"
            )
        )

        fixed_voltage = finite(
            local.get(
                "fixed_loss_voltage_v"
            )
        )

        cumulative_area = float(
            point["cumulative_area_m2"]
        )

        rows.append(
            {
                "cumulative_area_m2":
                    cumulative_area,

                "x_over_L":
                    cumulative_area
                    / total_area,

                "step_area_m2":
                    finite(
                        point.get(
                            "step_area_m2"
                        )
                    ),

                "process_bulk_activity":
                    first_finite(
                        point,
                        [
                            "process_activity",
                            "source_bulk_activity",
                        ],
                    ),

                "receiver_bulk_activity":
                    receiver_activity,

                "process_surface_activity":
                    local_field(
                        local,
                        [
                            "source_surface_activity",
                            "source_membrane_surface_activity",
                        ],
                    ),

                "receiver_surface_activity":
                    local_field(
                        local,
                        [
                            "receiver_surface_activity",
                            "receiver_membrane_surface_activity",
                        ],
                    ),

                "current_density_a_m2":
                    current,

                "ohmic_voltage_v":
                    ohmic,

                "water_polarisation_voltage_v":
                    water_voltage,

                "series_loss_voltage_v":
                    series_voltage,

                "fixed_loss_voltage_v":
                    fixed_voltage,

                "reconstructed_terminal_voltage_v":
                    (
                        ohmic
                        + water_voltage
                        + series_voltage
                        + fixed_voltage
                    ),

                "eo_flux_mol_m2_s":
                    local_field(
                        local,
                        [
                            "eo_flux_mol_m2_s"
                        ],
                    ),

                "diffusion_flux_mol_m2_s":
                    local_field(
                        local,
                        [
                            "diffusion_flux_mol_m2_s"
                        ],
                    ),

                "net_flux_mol_m2_s":
                    finite(
                        local.get(
                            "net_flux_mol_m2_s"
                        )
                    ),

                "source_film_coefficient":
                    finite(
                        local.get(
                            "source_film_coefficient_mol_m2_s_activity"
                        )
                    ),

                "receiver_film_coefficient":
                    finite(
                        local.get(
                            "receiver_film_coefficient_mol_m2_s_activity"
                        )
                    ),
            }
        )

    frame = pd.DataFrame(rows)

    if not frame.empty:
        frame[
            "surface_activity_margin"
        ] = (
            frame[
                "process_surface_activity"
            ]
            - frame[
                "receiver_surface_activity"
            ]
        )

    return frame



def run_budget_study(
    context: dict[str, Any],
    material: Mapping[str, Any],
    baseline_v: float,
    receiver_mult: float,
    args: argparse.Namespace,
    out: Path,
):
    stage = out / "budget"
    stage.mkdir(parents=True, exist_ok=True)
    band = default_band(context, args)

    summary, profile, receiver = solve_full_case(
        context,
        target=args.target,
        material=material,
        terminal_voltage_v=baseline_v,
        receiver_multiplier=receiver_mult,
        receiver_band=band,
        receiver_band_id=args.receiver_band,
        area_limit_m2=args.area_max_m2,
        record_profile=True,
    )
    pd.DataFrame([summary]).to_csv(stage / "uniform_baseline_summary.csv", index=False)
    profile.to_csv(stage / "uniform_baseline_profile.csv.gz", index=False, compression="gzip")

    if profile.empty:
        return

    reconstructed = reconstruct_local_profile(
        context,
        material=material,
        terminal_voltage_v=baseline_v,
        profile=profile,
        receiver=receiver,
    )
    reconstructed.to_csv(stage / "axial_voltage_flux_budget.csv", index=False)

    if reconstructed.empty:
        return

    save_plot(
        stage / "voltage_components",
        reconstructed["x_over_L"],
        {
            "Ohmic": reconstructed["ohmic_voltage_v"],
            "Water activity": reconstructed["water_polarisation_voltage_v"],
            "Series ASR": reconstructed["series_loss_voltage_v"],
        },
        xlabel="Axial position x/L",
        ylabel="Local voltage contribution [V]",
        title=f"{args.target}: local voltage-budget decomposition",
    )
    save_plot(
        stage / "flux_components",
        reconstructed["x_over_L"],
        {
            "EO": reconstructed["eo_flux_mol_m2_s"],
            "Diffusion": reconstructed["diffusion_flux_mol_m2_s"],
            "Net": reconstructed["net_flux_mol_m2_s"],
        },
        xlabel="Axial position x/L",
        ylabel="Water flux [mol m⁻² s⁻¹]",
        title=f"{args.target}: EO, diffusion and net water flux",
    )
    save_plot(
        stage / "activities",
        reconstructed["x_over_L"],
        {
            "Process bulk": reconstructed["process_bulk_activity"],
            "Process surface": reconstructed["process_surface_activity"],
            "Receiver surface": reconstructed["receiver_surface_activity"],
            "Receiver bulk": reconstructed["receiver_bulk_activity"],
        },
        xlabel="Axial position x/L",
        ylabel="Water activity [-]",
        title=f"{args.target}: bulk and membrane-surface activities",
    )


def voltage_schedule_multipliers(kind: str, x: np.ndarray) -> np.ndarray:
    if kind == "uniform":
        return np.ones_like(x)
    if kind == "three_zone":
        indices = np.minimum((3.0 * x).astype(int), 2)
        return np.asarray([0.90, 1.00, 1.10])[indices]
    if kind == "five_zone":
        indices = np.minimum((5.0 * x).astype(int), 4)
        return np.asarray([0.80, 0.90, 1.00, 1.10, 1.20])[indices]
    raise ValueError(kind)


def replay_schedule(
    context: dict[str, Any],
    *,
    material: Mapping[str, Any],
    profile: pd.DataFrame,
    receiver: Any,
    schedule_kind: str,
    voltage_scale_v: float,
    voltage_max_v: float,
) -> dict[str, Any]:
    cfg12 = context["cfg12"]

    local_config = copy.deepcopy(
        context["base"]
    )

    local_config["channel"] = copy.deepcopy(
        context["base"]["channel"]
    )

    local_config["channel"][
        "receiver_velocity_m_s"
    ] = receiver.receiver_velocity_m_s

    efficiency = float(
        cfg12["operating"][
            "power_electronics_efficiency"
        ]
    )

    base_film_scale = float(
        cfg12["operating"][
            "film_scale_factor"
        ]
    )

    total_area = max(
        float(
            profile[
                "cumulative_area_m2"
            ].max()
        ),
        NUMERIC_EPS,
    )

    x = (
        profile[
            "cumulative_area_m2"
        ].to_numpy(float)
        / total_area
    )

    multipliers = (
        voltage_schedule_multipliers(
            schedule_kind,
            x,
        )
    )

    local_voltages = (
        voltage_scale_v
        * multipliers
    )

    if (
        np.max(local_voltages)
        > voltage_max_v + 1.0e-12
    ):
        return {
            "schedule_solution_ok":
                False
        }

    transfer_mol_s = 0.0
    grid_power_w = 0.0

    local_rows: list[
        dict[str, Any]
    ] = []

    for (
        (_, point),
        x_value,
        multiplier,
        local_voltage,
    ) in zip(
        profile.iterrows(),
        x,
        multipliers,
        local_voltages,
    ):
        process_w = first_finite(
            point,
            [
                "process_humidity_ratio_kg_kg_da",
                "humidity_ratio_kg_kg_da",
            ],
        )

        receiver_activity = first_finite(
            point,
            [
                "receiver_activity",
                "receiver_bulk_activity",
            ],
        )

        step_area = finite(
            point.get(
                "step_area_m2"
            )
        )

        if not all(
            math.isfinite(value)
            for value in (
                process_w,
                receiver_activity,
                step_area,
            )
        ):
            return {
                "schedule_solution_ok":
                    False
            }

        local = solve_local_state(
            v2=context["v2"],
            v2_config=context[
                "v2_config"
            ],
            material=dict(material),
            source_temperature_c=float(
                context[
                    "process_basis"
                ].inlet_temperature_c
            ),
            source_humidity_ratio=process_w,
            receiver_activity=receiver_activity,
            terminal_voltage_v=float(
                local_voltage
            ),
            fixed_loss_voltage_v=0.0,
            series_asr_ohm_m2=float(
                cfg12["operating"][
                    "legacy_series_asr_ohm_m2"
                ]
            ),
            film_scale_factor=(
                base_film_scale
            ),
            config=local_config,
        )

        if not bool(
            local.get(
                "solution_ok",
                False,
            )
        ):
            return {
                "schedule_solution_ok":
                    False
            }

        flux = finite(
            local.get(
                "net_flux_mol_m2_s"
            )
        )

        current = finite(
            local.get(
                "current_density_a_m2"
            )
        )

        if not (
            math.isfinite(flux)
            and math.isfinite(current)
            and flux > 0.0
            and current > 0.0
        ):
            return {
                "schedule_solution_ok":
                    False
            }

        transfer_mol_s += (
            flux
            * step_area
        )

        grid_power_w += (
            local_voltage
            * current
            * step_area
            / efficiency
        )

        local_rows.append(
            {
                "x_over_L":
                    x_value,

                "voltage_multiplier":
                    multiplier,

                "local_voltage_v":
                    local_voltage,

                "net_flux_mol_m2_s":
                    flux,

                "current_density_a_m2":
                    current,
            }
        )

    return {
        "schedule_solution_ok":
            True,

        "schedule_kind":
            schedule_kind,

        "voltage_scale_v":
            voltage_scale_v,

        "maximum_local_voltage_v":
            float(
                np.max(
                    local_voltages
                )
            ),

        "replayed_water_transfer_kg_h":
            (
                transfer_mol_s
                * WATER_MOLAR_MASS_KG_MOL
                * 3600.0
            ),

        "replayed_eo_grid_power_kw":
            grid_power_w
            / 1000.0,

        "profile_rows":
            local_rows,
    }



def run_zoned_study(
    context: dict[str, Any],
    material: Mapping[str, Any],
    baseline_v: float,
    receiver_mult: float,
    args: argparse.Namespace,
    out: Path,
):
    stage = out / "zoned"
    stage.mkdir(parents=True, exist_ok=True)
    band = default_band(context, args)

    baseline, profile, receiver = solve_full_case(
        context,
        target=args.target,
        material=material,
        terminal_voltage_v=baseline_v,
        receiver_multiplier=receiver_mult,
        receiver_band=band,
        receiver_band_id=args.receiver_band,
        area_limit_m2=args.area_max_m2,
        record_profile=True,
    )
    if profile.empty:
        return

    target_water = finite(baseline.get("integrated_water_transfer_kg_h"))
    process_fan = finite(baseline.get("process_channel_fan_power_kw"))
    receiver_fan = finite(baseline.get("receiver_channel_fan_power_kw"))

    schedule_kinds = ["uniform", "three_zone", "five_zone"]
    summary_rows: list[dict[str, Any]] = []
    detailed_rows: list[dict[str, Any]] = []

    for kind in schedule_kinds:
        max_multiplier = {
            "uniform": 1.0,
            "three_zone": 1.10,
            "five_zone": 1.20,
        }[kind]
        upper_scale = args.voltage_max_v / max_multiplier
        scales = np.linspace(max(1.0e-4, 0.40 * baseline_v), upper_scale, 35)
        candidates: list[dict[str, Any]] = []
        for scale in scales:
            result = replay_schedule(
                context,
                material=material,
                profile=profile,
                receiver=receiver,
                schedule_kind=kind,
                voltage_scale_v=float(scale),
                voltage_max_v=args.voltage_max_v,
            )
            if not result.get("schedule_solution_ok", False):
                continue
            result["relative_water_duty_error"] = (
                result["replayed_water_transfer_kg_h"] - target_water
            ) / max(abs(target_water), NUMERIC_EPS)
            candidates.append(result)

        if not candidates:
            continue

        best = min(candidates, key=lambda item: abs(item["relative_water_duty_error"]))
        total_core = (
            best["replayed_eo_grid_power_kw"] + process_fan + receiver_fan
        )
        summary_rows.append(
            {
                "schedule_kind": kind,
                "profile_replay_only": True,
                "baseline_area_m2": finite(baseline.get("required_active_area_m2")),
                "target_water_transfer_kg_h": target_water,
                "replayed_water_transfer_kg_h": best["replayed_water_transfer_kg_h"],
                "relative_water_duty_error": best["relative_water_duty_error"],
                "voltage_scale_v": best["voltage_scale_v"],
                "maximum_local_voltage_v": best["maximum_local_voltage_v"],
                "replayed_eo_grid_power_kw": best["replayed_eo_grid_power_kw"],
                "baseline_process_fan_kw": process_fan,
                "baseline_receiver_fan_kw": receiver_fan,
                "replayed_core_power_kw": total_core,
            }
        )
        for row in best["profile_rows"]:
            detailed_rows.append({"schedule_kind": kind, **row})

    summary = pd.DataFrame(summary_rows)
    detail = pd.DataFrame(detailed_rows)
    summary.to_csv(stage / "schedule_replay_summary.csv", index=False)
    detail.to_csv(stage / "schedule_replay_profiles.csv", index=False)

    if not summary.empty:
        fig, ax = plt.subplots(figsize=(7.5, 4.8))
        ax.bar(summary["schedule_kind"], summary["replayed_core_power_kw"])
        ax.set_ylabel("Profile-replay core power [kW]")
        ax.set_title(
            f"{args.target}: uniform versus zoned voltage\n"
            "Diagnostic fixed-bulk-profile replay only"
        )
        ax.grid(axis="y", alpha=0.25)
        fig.tight_layout()
        fig.savefig(stage / "schedule_core_power.png", dpi=220)
        fig.savefig(stage / "schedule_core_power.pdf")
        plt.close(fig)

    if not detail.empty:
        for kind, group in detail.groupby("schedule_kind", sort=True):
            ordered = group.sort_values("x_over_L")
            save_plot(
                stage / f"voltage_schedule_{kind}",
                ordered["x_over_L"],
                {"Local voltage": ordered["local_voltage_v"]},
                xlabel="Axial position x/L",
                ylabel="Local terminal voltage [V]",
                title=f"{args.target}: {kind.replace('_', ' ')} schedule",
            )


def write_summary(
    out: Path,
    *,
    args: argparse.Namespace,
    baseline_source: str,
    baseline: Mapping[str, Any],
    material: Mapping[str, Any],
    baseline_v: float,
    receiver_mult: float,
):
    lines = [
        "# HeiQ pre-architecture bottleneck diagnostics v1",
        "",
        "## Model boundary",
        "",
        "- V12.1 coupled two-stream core.",
        "- Process and receiver humidity both march axially.",
        "- Local V2/V3 membrane BVP and both gas films are retained.",
        "- Receiver ERV/HRV/regeneration/condensation architecture is excluded.",
        "",
        "## Selected baseline",
        "",
        f"- Source: `{baseline_source}`",
        f"- Target: `{args.target}`",
        f"- Water drag: {material['water_drag']:.8g}",
        f"- Diffusivity: {material['water_diffusivity_m2_s']:.6g} m2/s",
        f"- Conductivity: {material['conductivity_s_m']:.6g} S/m",
        f"- Dry thickness: {material['dry_thickness_um']:.6g} um",
        f"- Uniform terminal voltage: {baseline_v:.8g} V",
        f"- Receiver capacity multiplier: {receiver_mult:.6g}",
        f"- Area gate: {args.area_max_m2:.6g} m2",
        "",
        "## Interpretation limits",
        "",
        "- The 1e4 film factor is a finite near-ideal-film proxy, not mathematical infinity.",
        "- The D=0 point uses D=1e-20 m2/s and is a near-zero-diffusion proxy.",
        "- Zoned-voltage results are fixed-bulk-profile replays, not full coupled re-integrations.",
        "- A negative surface activity margin indicates EO pumping against back-diffusion; it is diagnostic, not an automatic failure when net flux remains positive.",
        "",
    ]
    (out / "README_RESULTS.md").write_text("\n".join(lines), encoding="utf-8")


def self_test():
    assert truth(True)
    assert truth("yes")
    assert not truth("false")
    assert unique_sorted([1.0, 1.0, 2.0], lo=0.0, hi=2.0) == [1.0, 2.0]
    x = np.asarray([0.0, 0.2, 0.4, 0.8, 1.0])
    assert np.allclose(
        voltage_schedule_multipliers("three_zone", x),
        [0.9, 0.9, 1.0, 1.1, 1.1],
    )
    assert np.allclose(
        voltage_schedule_multipliers("five_zone", x),
        [0.8, 0.9, 1.0, 1.2, 1.2],
    )
    print("Self-test passed: utilities, truth parsing and zoned schedule maps are consistent.")


def main() -> int:
    args = parse_args()
    if args.self_test:
        self_test()
        return 0

    continuation, context = setup_context(args)
    baseline, baseline_source = select_baseline_row(args)
    material = material_from_baseline(continuation, context, baseline)
    voltage = baseline_voltage(baseline, args)
    receiver_mult = baseline_receiver_multiplier(baseline, args)

    out = ROOT / args.output_dir
    out.mkdir(parents=True, exist_ok=True)

    metadata = {
        "script": "make_wp1_prearchitecture_bottleneck_diagnostics_v1.py",
        "model": "V12.1 coupled two-stream pre-architecture core",
        "target": args.target,
        "baseline_source": baseline_source,
        "baseline_material": {
            name: material[name] for name in MATERIAL_COLUMNS
        },
        "baseline_terminal_voltage_v": voltage,
        "baseline_receiver_capacity_multiplier": receiver_mult,
        "area_gate_m2": args.area_max_m2,
        "voltage_cap_v": args.voltage_max_v,
        "receiver_architecture_included": False,
        "zoned_voltage_is_profile_replay_only": True,
    }
    (out / "run_metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n",
        encoding="utf-8",
    )
    write_summary(
        out,
        args=args,
        baseline_source=baseline_source,
        baseline=baseline,
        material=material,
        baseline_v=voltage,
        receiver_mult=receiver_mult,
    )

    stages = (
        ["film", "receiver", "corners", "area", "diffusion", "budget", "zoned"]
        if args.stage == "all"
        else [args.stage]
    )

    for stage in stages:
        print(f"\n=== RUNNING {stage.upper()} ===", flush=True)
        if stage == "film":
            run_film_study(context, material, voltage, receiver_mult, args, out)
        elif stage == "receiver":
            run_receiver_study(context, material, voltage, args, out)
        elif stage == "corners":
            run_corner_study(context, material, voltage, receiver_mult, args, out)
        elif stage == "area":
            run_area_study(context, material, voltage, receiver_mult, args, out)
        elif stage == "diffusion":
            run_diffusion_study(
                continuation, context, material, voltage, receiver_mult, args, out
            )
        elif stage == "budget":
            run_budget_study(context, material, voltage, receiver_mult, args, out)
        elif stage == "zoned":
            run_zoned_study(context, material, voltage, receiver_mult, args, out)
        else:
            raise RuntimeError(stage)

    print(f"\nDone. Outputs: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
