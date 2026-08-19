#!/usr/bin/env python3
"""
HeiQ WP1 continuation of the pre-architecture coupled axial EO analysis.

Model boundary
--------------
Uses the reviewed V12.1 coupled two-stream core:
- process and receiver humidity both march axially;
- the unchanged V2/V3 local voltage-controlled membrane BVP is re-solved;
- process and receiver gas films are retained;
- receiver architecture/regeneration/ERV/HRV is NOT introduced.

Stages
------
1) o50-edge:
   Map the very-low-terminal-voltage operating edge for O50.
   This is NOT called a passive/open-circuit reference because V12.1 is
   voltage-controlled and its local gate requires positive current.

2) o30-receiver:
   Re-optimise receiver dry-air capacity multiplier and terminal voltage for
   selected water-drag values at O30.

3) material:
   At the best O30 receiver-flow point, run a deterministic Latin-hypercube
   screen over water drag, diffusivity, conductivity and dry thickness, with
   voltage re-optimisation and finalist surface-activity audit.

Default active-area gate: 9000 m2.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from heiq.wp1.studies import build_repository_context as native_build_repository_context
from heiq.wp1.studies.prearchitecture import (
    audit_surfaces as native_audit_surfaces,
    build_context as native_build_context,
    make_material as native_make_material,
    receiver_basis as native_receiver_basis,
    solve_case as native_solve_case,
)

ROOT = Path(__file__).resolve().parents[1]
V11_DIR = ROOT / "outputs" / "axial_independent_material_sweep_v8" / "coarse" / "voltage_refinement_v11"
V12_SCRIPT = ROOT / "scripts" / "make_wp1_closed_receiver_system_v12.py"
AXIAL_SCRIPT = ROOT / "scripts" / "make_wp1_pre_receiver_axial_v3.py"
V12_CONFIG = ROOT / "scripts" / "closed_receiver_system_v12_config.json"
V2_ROOT = ROOT / "heiq_pre_receiver_material_analyses"

O50_EDGE_DRAGS = [36.205058, 150.0, 600.0]
O50_EDGE_VOLTAGES = [
    1.0e-5, 2.0e-5, 5.0e-5,
    1.0e-4, 2.0e-4, 5.0e-4,
    1.0e-3, 1.5e-3, 2.0e-3, 3.0e-3, 4.0e-3,
    5.0e-3, 7.5e-3, 1.0e-2, 1.5e-2, 2.0e-2,
]

O30_RECEIVER_DRAGS = [36.205058, 50.0, 75.0, 100.0, 150.0, 250.0]
O30_RECEIVER_MULTIPLIERS = [
    1.01, 1.025, 1.05, 1.075, 1.10, 1.15,
    1.20, 1.25, 1.35, 1.50, 1.75, 2.00,
]

# Previous V12.1/M11675-family O30 screen showed roughly V/tw ~ 0.0106 V.
# This is only a grid-centering heuristic; every case is re-solved.
V_PER_DRAG_HEURISTIC = 0.0106

MATERIAL_RANGES = {
    "water_drag": (10.0, 600.0, "linear"),
    "water_diffusivity_m2_s": (1.0e-14, 1.0e-10, "log"),
    "conductivity_s_m": (0.1, 100.0, "log"),
    "dry_thickness_um": (25.0, 200.0, "linear"),
}

SURFACE_AUDIT_TOP_N = 12





def finite(value) -> float:
    try:
        x = float(value)
    except Exception:
        return math.nan
    return x if math.isfinite(x) else math.nan


def truth(value) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    return str(value).strip().lower() in {"true", "1", "yes"}


def unique_sorted(values, *, lo=0.0, hi=math.inf):
    return sorted({
        round(float(v), 10)
        for v in values
        if math.isfinite(float(v)) and lo <= float(v) <= hi
    })


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument(
        "--stage",
        choices=["o50-edge", "o30-receiver", "material", "all"],
        default="all",
    )
    p.add_argument(
        "--output-dir",
        default="outputs/prearchitecture_continuation_v2",
    )
    p.add_argument("--area-max-m2", type=float, default=9000.0)
    p.add_argument("--voltage-max-v", type=float, default=2.0)
    p.add_argument("--receiver-band", default="bridge_40_to_60")
    p.add_argument("--receiver-temperature-c", type=float, default=None)
    p.add_argument("--lhs-samples", type=int, default=64)
    p.add_argument("--seed", type=int, default=20260812)
    p.add_argument("--smoke", action="store_true")
    return p.parse_args()


def setup(args):
    return native_build_repository_context(
        args,
        root=ROOT,
    )



def make_material(
    ctx,
    *,
    drag=None,
    diffusivity=None,
    conductivity=None,
    thickness=None,
):
    return native_make_material(
        ctx,
        drag=drag,
        diffusivity=diffusivity,
        conductivity=conductivity,
        thickness=thickness,
    )



def receiver_basis(
    ctx,
    target: str,
    multiplier: float,
):
    return native_receiver_basis(
        ctx,
        target,
        multiplier,
    )



def solve_case(
    ctx,
    *,
    target: str,
    material: dict,
    voltage_v: float,
    receiver_multiplier: float,
    record_profile: bool = False,
):
    return native_solve_case(
        ctx,
        target=target,
        material=material,
        voltage_v=voltage_v,
        receiver_multiplier=receiver_multiplier,
        record_profile=record_profile,
    )



def audit_surfaces(
    ctx,
    row: pd.Series,
):
    return native_audit_surfaces(
        ctx,
        row,
    )



def checkpoint_append(path: Path, rows: list[dict], *, key_cols: list[str]):
    new = pd.DataFrame(rows)
    if path.exists():
        old = pd.read_csv(path)
        new = pd.concat([old, new], ignore_index=True)
    new = new.drop_duplicates(subset=key_cols, keep="last")
    new.to_csv(path, index=False)


def existing_keys(path: Path, key_cols: list[str]):
    if not path.exists():
        return set()
    df = pd.read_csv(path)
    return {
        tuple(str(row[c]) for c in key_cols)
        for _, row in df.iterrows()
    }


def run_o50_edge(ctx, out: Path):
    stage = out / "o50_edge"
    stage.mkdir(parents=True, exist_ok=True)
    path = stage / "all_cases.csv"
    key_cols = ["water_drag", "terminal_voltage_v"]

    drags = [36.205058, 600.0] if ctx["args"].smoke else O50_EDGE_DRAGS
    voltages = [0.001, 0.005, 0.01] if ctx["args"].smoke else O50_EDGE_VOLTAGES
    known = existing_keys(path, key_cols)
    batch = []

    total = len(drags) * len(voltages)
    done = 0
    for drag in drags:
        material = make_material(ctx, drag=drag)
        for voltage in voltages:
            done += 1
            key = (str(float(drag)), str(float(voltage)))
            if key in known:
                continue
            row, _, _ = solve_case(
                ctx,
                target="O50",
                material=material,
                voltage_v=voltage,
                receiver_multiplier=1.25,
            )
            row["stage"] = "o50_low_voltage_edge"
            batch.append(row)
            if len(batch) >= 20:
                checkpoint_append(path, batch, key_cols=key_cols)
                batch = []
            print(f"O50 edge: {done}/{total}", flush=True)
    if batch:
        checkpoint_append(path, batch, key_cols=key_cols)

    df = pd.read_csv(path)
    passing = df[df["analysis_pass"].map(truth)].copy()
    if passing.empty:
        pd.DataFrame().to_csv(stage / "best_by_drag.csv", index=False)
        return

    best = (
        passing.sort_values(
            ["water_drag", "analysis_core_power_kw",
             "required_active_area_m2", "terminal_voltage_v"],
            kind="mergesort",
        )
        .drop_duplicates("water_drag", keep="first")
        .reset_index(drop=True)
    )
    best.to_csv(stage / "best_by_drag.csv", index=False)

    print("\n=== O50 LOW-VOLTAGE EDGE ===")
    show = [
        "water_drag", "terminal_voltage_v", "required_active_area_m2",
        "maximum_local_current_density_a_m2", "eo_grid_power_kw",
        "process_channel_fan_power_kw", "receiver_channel_fan_power_kw",
        "analysis_core_power_kw", "analysis_core_sec_kwh_kg",
    ]
    print(best[[c for c in show if c in best.columns]].to_string(index=False))


def receiver_voltage_grid(drag: float, vmax: float):
    center = min(vmax, max(0.03, V_PER_DRAG_HEURISTIC * drag))
    scales = [0.55, 0.70, 0.82, 0.90, 0.96, 1.00, 1.04, 1.10, 1.20, 1.35]
    values = [center * s for s in scales]
    values += [0.10, 0.25, 0.50, 0.75, 1.00, 1.25, 1.50, 1.75, vmax]
    return unique_sorted(values, lo=0.001, hi=vmax)


def run_o30_receiver(ctx, out: Path):
    stage = out / "o30_receiver"
    stage.mkdir(parents=True, exist_ok=True)
    path = stage / "all_cases.csv"
    key_cols = [
        "water_drag", "terminal_voltage_v",
        "analysis_receiver_capacity_multiplier",
    ]

    drags = (
        [36.205058, 150.0]
        if ctx["args"].smoke
        else O30_RECEIVER_DRAGS
    )
    mults = (
        [1.05, 1.25]
        if ctx["args"].smoke
        else O30_RECEIVER_MULTIPLIERS
    )
    known = existing_keys(path, key_cols)
    batch = []

    total = sum(
        len(receiver_voltage_grid(drag, ctx["args"].voltage_max_v))
        for drag in drags
    ) * len(mults)
    done = 0

    for mult in mults:
        for drag in drags:
            material = make_material(ctx, drag=drag)
            for voltage in receiver_voltage_grid(
                drag, ctx["args"].voltage_max_v
            ):
                done += 1
                key = (str(float(drag)), str(float(voltage)), str(float(mult)))
                if key in known:
                    continue
                row, _, _ = solve_case(
                    ctx,
                    target="O30",
                    material=material,
                    voltage_v=voltage,
                    receiver_multiplier=mult,
                )
                row["stage"] = "o30_receiver_flow"
                batch.append(row)
                if len(batch) >= 25:
                    checkpoint_append(path, batch, key_cols=key_cols)
                    batch = []
                if done % 25 == 0 or done == total:
                    print(f"O30 receiver: {done}/{total}", flush=True)
    if batch:
        checkpoint_append(path, batch, key_cols=key_cols)

    df = pd.read_csv(path)
    passing = df[df["analysis_pass"].map(truth)].copy()
    if passing.empty:
        pd.DataFrame().to_csv(stage / "best_by_multiplier_drag.csv", index=False)
        pd.DataFrame().to_csv(stage / "overall_best.csv", index=False)
        print("No passing O30 receiver-flow cases.")
        return

    best_md = (
        passing.sort_values(
            [
                "analysis_receiver_capacity_multiplier",
                "water_drag",
                "analysis_core_power_kw",
                "required_active_area_m2",
                "terminal_voltage_v",
            ],
            kind="mergesort",
        )
        .drop_duplicates(
            ["analysis_receiver_capacity_multiplier", "water_drag"],
            keep="first",
        )
        .reset_index(drop=True)
    )
    best_md.to_csv(stage / "best_by_multiplier_drag.csv", index=False)

    # Audit the globally lowest-power candidates. Surface direction is diagnostic.
    finalists = passing.sort_values(
        ["analysis_core_power_kw", "required_active_area_m2", "terminal_voltage_v"],
        kind="mergesort",
    ).head(SURFACE_AUDIT_TOP_N)

    audited = []
    for _, row in finalists.iterrows():
        audited.append({**row.to_dict(), **audit_surfaces(ctx, row)})
    audited = pd.DataFrame(audited)
    audited.to_csv(stage / "surface_audited_finalists.csv", index=False)

    physical = audited[
        audited["surface_state_audit_complete"].map(truth)
        & audited["surface_state_physical"].map(truth)
    ].copy()
    if physical.empty:
        overall = finalists.head(1).copy()
        overall["surface_state_audit_complete"] = False
        overall["surface_state_physical"] = False
    else:
        overall = physical.sort_values(
            ["analysis_core_power_kw", "required_active_area_m2"],
            kind="mergesort",
        ).head(1)

    overall.to_csv(stage / "overall_best.csv", index=False)

    print("\n=== BEST O30 RECEIVER-FLOW POINT ===")
    show = [
        "water_drag", "terminal_voltage_v",
        "analysis_receiver_capacity_multiplier",
        "analysis_receiver_to_process_dry_air_ratio",
        "analysis_receiver_target_outlet_activity",
        "required_active_area_m2",
        "maximum_local_current_density_a_m2",
        "eo_grid_power_kw",
        "process_channel_fan_power_kw",
        "receiver_channel_fan_power_kw",
        "analysis_core_power_kw",
        "analysis_core_sec_kwh_kg",
        "minimum_surface_activity_margin",
        "negative_surface_margin_fraction",
    ]
    print(overall[[c for c in show if c in overall.columns]].to_string(index=False))


def latin_hypercube(n: int, d: int, seed: int):
    # SciPy-free deterministic LHS.
    rng = np.random.default_rng(seed)
    x = np.empty((n, d), dtype=float)
    for j in range(d):
        perm = rng.permutation(n)
        x[:, j] = (perm + rng.random(n)) / n
    return x


def map_sample(u: float, lo: float, hi: float, mode: str):
    if mode == "linear":
        return lo + u * (hi - lo)
    if mode == "log":
        return 10.0 ** (
            math.log10(lo) + u * (math.log10(hi) - math.log10(lo))
        )
    raise ValueError(mode)


def material_voltage_grid(drag: float, vmax: float):
    center = min(vmax, max(0.03, V_PER_DRAG_HEURISTIC * drag))
    scales = [0.35, 0.50, 0.65, 0.80, 0.90, 1.00, 1.10, 1.25, 1.45]
    values = [center * s for s in scales]
    values += [0.05, 0.10, 0.25, 0.50, 0.75, 1.00, 1.50, 2.00]
    return unique_sorted(values, lo=0.001, hi=vmax)


def best_receiver_multiplier(out: Path) -> float:
    path = out / "o30_receiver" / "overall_best.csv"
    if not path.exists():
        return 1.25
    df = pd.read_csv(path)
    if df.empty:
        return 1.25
    return float(df.iloc[0]["analysis_receiver_capacity_multiplier"])


def run_material(ctx, out: Path):
    stage = out / "material_global"
    stage.mkdir(parents=True, exist_ok=True)
    path = stage / "all_cases.csv"
    key_cols = ["sample_id", "terminal_voltage_v"]

    n = 8 if ctx["args"].smoke else int(ctx["args"].lhs_samples)
    receiver_mult = best_receiver_multiplier(out)

    dims = list(MATERIAL_RANGES)
    lhs = latin_hypercube(n, len(dims), ctx["args"].seed)

    samples = []
    for i in range(n):
        vals = {}
        for j, name in enumerate(dims):
            lo, hi, mode = MATERIAL_RANGES[name]
            vals[name] = map_sample(lhs[i, j], lo, hi, mode)
        vals["sample_id"] = i
        samples.append(vals)

    samples_df = pd.DataFrame(samples)
    samples_df.to_csv(stage / "lhs_material_samples.csv", index=False)

    known = existing_keys(path, key_cols)
    batch = []
    total = sum(
        len(material_voltage_grid(s["water_drag"], ctx["args"].voltage_max_v))
        for s in samples
    )
    done = 0

    for s in samples:
        material = make_material(
            ctx,
            drag=s["water_drag"],
            diffusivity=s["water_diffusivity_m2_s"],
            conductivity=s["conductivity_s_m"],
            thickness=s["dry_thickness_um"],
        )
        for voltage in material_voltage_grid(
            s["water_drag"], ctx["args"].voltage_max_v
        ):
            done += 1
            key = (str(int(s["sample_id"])), str(float(voltage)))
            if key in known:
                continue
            row, _, _ = solve_case(
                ctx,
                target="O30",
                material=material,
                voltage_v=voltage,
                receiver_multiplier=receiver_mult,
            )
            row["sample_id"] = int(s["sample_id"])
            row["stage"] = "material_global_lhs"
            batch.append(row)
            if len(batch) >= 25:
                checkpoint_append(path, batch, key_cols=key_cols)
                batch = []
            if done % 25 == 0 or done == total:
                print(f"Material LHS: {done}/{total}", flush=True)
    if batch:
        checkpoint_append(path, batch, key_cols=key_cols)

    df = pd.read_csv(path)
    passing = df[df["analysis_pass"].map(truth)].copy()
    if passing.empty:
        pd.DataFrame().to_csv(stage / "best_by_sample.csv", index=False)
        pd.DataFrame().to_csv(stage / "overall_best.csv", index=False)
        print("No passing global material samples.")
        return

    best_sample = (
        passing.sort_values(
            ["sample_id", "analysis_core_power_kw",
             "required_active_area_m2", "terminal_voltage_v"],
            kind="mergesort",
        )
        .drop_duplicates("sample_id", keep="first")
        .reset_index(drop=True)
    )
    best_sample.to_csv(stage / "best_by_sample.csv", index=False)

    # Refine voltage for the best 12 samples.
    top_ids = (
        best_sample.sort_values("analysis_core_power_kw")
        .head(min(12, len(best_sample)))["sample_id"]
        .astype(int)
        .tolist()
    )

    refine_rows = []
    for sid in top_ids:
        row0 = best_sample[best_sample["sample_id"].astype(int).eq(sid)].iloc[0]
        vb = float(row0["terminal_voltage_v"])
        lo = max(0.001, 0.82 * vb)
        hi = min(ctx["args"].voltage_max_v, 1.18 * vb)
        voltages = unique_sorted(
            list(np.linspace(lo, hi, 19)) + [vb],
            lo=0.001,
            hi=ctx["args"].voltage_max_v,
        )
        material = make_material(
            ctx,
            drag=float(row0["water_drag"]),
            diffusivity=float(row0["water_diffusivity_m2_s"]),
            conductivity=float(row0["conductivity_s_m"]),
            thickness=float(row0["dry_thickness_um"]),
        )
        for voltage in voltages:
            row, _, _ = solve_case(
                ctx,
                target="O30",
                material=material,
                voltage_v=voltage,
                receiver_multiplier=receiver_mult,
            )
            row["sample_id"] = sid
            row["stage"] = "material_voltage_refined"
            refine_rows.append(row)

    refined = pd.DataFrame(refine_rows)
    refined.to_csv(stage / "refined_finalist_cases.csv", index=False)

    combined = pd.concat([passing, refined], ignore_index=True)
    combined = combined[combined["analysis_pass"].map(truth)].copy()
    best_refined = (
        combined.sort_values(
            ["sample_id", "analysis_core_power_kw",
             "required_active_area_m2", "terminal_voltage_v"],
            kind="mergesort",
        )
        .drop_duplicates("sample_id", keep="first")
        .sort_values("analysis_core_power_kw")
        .reset_index(drop=True)
    )
    best_refined.to_csv(stage / "best_refined_samples.csv", index=False)

    # Surface-state audit top finalists. Negative surface margin is allowed;
    # it is reported as uphill EO/back-diffusion diagnostic.
    audited = []
    for _, row in best_refined.head(SURFACE_AUDIT_TOP_N).iterrows():
        audited.append({**row.to_dict(), **audit_surfaces(ctx, row)})
    audited = pd.DataFrame(audited)
    audited.to_csv(stage / "surface_audited_finalists.csv", index=False)

    physical = audited[
        audited["surface_state_audit_complete"].map(truth)
        & audited["surface_state_physical"].map(truth)
    ].copy()

    if physical.empty:
        overall = best_refined.head(1).copy()
    else:
        overall = physical.sort_values(
            ["analysis_core_power_kw", "required_active_area_m2"],
            kind="mergesort",
        ).head(1)

    overall.to_csv(stage / "overall_best.csv", index=False)

    print("\n=== BEST GLOBAL MATERIAL POINT ===")
    show = [
        "sample_id", "water_drag", "water_diffusivity_m2_s",
        "conductivity_s_m", "dry_thickness_um", "terminal_voltage_v",
        "analysis_receiver_capacity_multiplier",
        "required_active_area_m2",
        "maximum_local_current_density_a_m2",
        "eo_grid_power_kw",
        "process_channel_fan_power_kw",
        "receiver_channel_fan_power_kw",
        "analysis_core_power_kw",
        "analysis_core_sec_kwh_kg",
        "minimum_surface_activity_margin",
        "negative_surface_margin_fraction",
    ]
    print(overall[[c for c in show if c in overall.columns]].to_string(index=False))


def write_metadata(ctx, out: Path):
    args = ctx["args"]
    data = {
        "script": "make_wp1_prearchitecture_continuation_v2.py",
        "model": "V12.1 coupled two-stream pre-architecture core",
        "area_limit_m2": args.area_max_m2,
        "voltage_max_v": args.voltage_max_v,
        "receiver_band": args.receiver_band,
        "receiver_temperature_c": float(
            ctx["base"]["channel"]["receiver_temperature_c"]
        ),
        "flow_arrangement": "counter_current",
        "surface_direction_is_hard_gate": False,
        "hard_local_transport_gate": "positive net water flux",
        "o50_zero_voltage_note": (
            "Exact passive/open-circuit is not inferred from Vterm=0. "
            "The existing V12.1 solver is voltage-controlled and requires "
            "positive current; o50-edge only maps the low-positive-voltage edge."
        ),
        "material_ranges": MATERIAL_RANGES,
        "receiver_architecture_included": False,
    }
    (out / "run_metadata.json").write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8"
    )


def main():
    args = parse_args()
    out = ROOT / args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    ctx = setup(args)
    write_metadata(ctx, out)

    if args.stage in {"o50-edge", "all"}:
        run_o50_edge(ctx, out)
    if args.stage in {"o30-receiver", "all"}:
        run_o30_receiver(ctx, out)
    if args.stage in {"material", "all"}:
        run_material(ctx, out)

    print(f"\nDone. Outputs: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
