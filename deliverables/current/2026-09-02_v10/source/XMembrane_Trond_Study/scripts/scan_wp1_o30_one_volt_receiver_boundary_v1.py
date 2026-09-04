#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable, Mapping

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]


FIXED_MATERIAL = {
    "name": "legacy_O30_case_94_material",
    "model": "powerlaw",
    "water_drag": 100.06078708377692,
    "water_diffusivity_m2_s": 1.597880133581376e-14,
    "conductivity_s_m": 23.171886845550485,
    "dry_thickness_um": 36.91369958200169,
    "water_capacity_mol_m3_activity": 10000.0,
    "diffusivity_activity_exponent": 2.0,
    "conductivity_activity_exponent": 4.0,
    "capacity_activity_exponent": 0.0,
    "interpretation": (
        "Hypothetical legacy V11 material vector from O30 case 94; "
        "not experimental material validation"
    ),
}


FIXED_GEOMETRY = {
    "process_gap_m": 0.002,
    "receiver_gap_m": 0.004,
    "process_velocity_m_s": 1.0,
    "active_sides_per_process_channel": 2.0,
    "receiver_geometry_mode": "aligned_equal_total_width",
}


DEFAULT_VOLTAGES_V = (0.80, 0.90, 1.00)
DEFAULT_RECEIVER_MULTIPLIERS = (
    1.01,
    1.02,
    1.05,
    1.10,
    1.20,
    1.50,
    2.00,
    3.00,
)


@dataclass(frozen=True)
class SearchPoint:
    terminal_voltage_v: float
    receiver_capacity_multiplier: float

    @property
    def search_point_id(self) -> str:
        voltage = (
            f"{self.terminal_voltage_v:.6f}"
            .rstrip("0")
            .rstrip(".")
        )
        multiplier = (
            f"{self.receiver_capacity_multiplier:.6f}"
            .rstrip("0")
            .rstrip(".")
        )
        return f"O30_V{voltage}_R{multiplier}"


def truth(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"true", "1", "yes"}


def finite(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return math.nan
    return result if math.isfinite(result) else math.nan


def selective_context_copy(
    context: Mapping[str, Any],
) -> dict[str, Any]:
    """Copy mutable configuration but preserve imported solver modules."""

    copied = dict(context)
    copied["base"] = copy.deepcopy(context["base"])
    copied["cfg12"] = copy.deepcopy(context["cfg12"])

    if "args" in context:
        copied["args"] = copy.copy(context["args"])

    return copied


def apply_fixed_geometry(context: dict[str, Any]) -> None:
    channel = context["base"]["channel"]
    channel.update(FIXED_GEOMETRY)

    cfg_channel = context["cfg12"]["channel"]
    cfg_channel["active_sides_per_process_channel"] = (
        FIXED_GEOMETRY["active_sides_per_process_channel"]
    )
    cfg_channel["receiver_geometry_mode"] = (
        FIXED_GEOMETRY["receiver_geometry_mode"]
    )


def build_points(
    voltages_v: Iterable[float],
    receiver_multipliers: Iterable[float],
    *,
    voltage_cap_v: float,
) -> tuple[SearchPoint, ...]:
    voltages = tuple(sorted({float(value) for value in voltages_v}))
    multipliers = tuple(
        sorted({float(value) for value in receiver_multipliers})
    )

    if not voltages:
        raise ValueError("At least one voltage is required")
    if not multipliers:
        raise ValueError("At least one receiver multiplier is required")
    if not math.isfinite(voltage_cap_v) or voltage_cap_v <= 0.0:
        raise ValueError("voltage_cap_v must be positive and finite")

    for voltage in voltages:
        if not math.isfinite(voltage) or voltage <= 0.0:
            raise ValueError("Voltages must be positive and finite")
        if voltage > voltage_cap_v + 1.0e-12:
            raise ValueError(
                f"Voltage {voltage} V exceeds cap {voltage_cap_v} V"
            )

    for multiplier in multipliers:
        if not math.isfinite(multiplier) or multiplier <= 1.0:
            raise ValueError(
                "Receiver capacity multipliers must be finite and > 1"
            )

    return tuple(
        SearchPoint(voltage, multiplier)
        for multiplier in multipliers
        for voltage in voltages
    )


def evaluate_gates(
    row: Mapping[str, Any],
    *,
    point: SearchPoint,
    current_cap_a_m2: float,
    area_cap_m2: float,
    declared_cell_voltage_cap_v: float,
) -> dict[str, Any]:
    current = finite(
        row.get("maximum_local_current_density_a_m2")
    )
    area = finite(row.get("required_active_area_m2"))
    process_inlet = finite(
        row.get("process_inlet_humidity_ratio_kg_kg_da")
    )
    process_outlet = finite(
        row.get("process_outlet_humidity_ratio_kg_kg_da")
    )
    process_target = finite(
        row.get("target_humidity_ratio_kg_kg_da")
    )

    required_humidity_reduction = process_inlet - process_target
    if (
        math.isfinite(required_humidity_reduction)
        and required_humidity_reduction > 0.0
        and math.isfinite(process_outlet)
    ):
        normalized_target_shortfall = max(
            (process_outlet - process_target)
            / required_humidity_reduction,
            0.0,
        )
    else:
        normalized_target_shortfall = math.inf

    gates = {
        "native_analysis_pass": truth(row.get("analysis_pass")),
        "stack_gate_pass": truth(row.get("stack_feasible")),
        "current_gate_pass": (
            math.isfinite(current)
            and 0.0 < current <= current_cap_a_m2 + 1.0e-9
        ),
        "area_gate_pass": (
            math.isfinite(area)
            and 0.0 < area <= area_cap_m2 + 1.0e-9
        ),
        "declared_cell_voltage_gate_pass": (
            0.0
            < point.terminal_voltage_v
            <= declared_cell_voltage_cap_v + 1.0e-12
        ),
        "current_cap_a_m2": float(current_cap_a_m2),
        "area_cap_m2": float(area_cap_m2),
        "declared_cell_voltage_cap_v": float(
            declared_cell_voltage_cap_v
        ),
    }
    gates["all_declared_gates_pass"] = all(
        bool(gates[name])
        for name in (
            "native_analysis_pass",
            "stack_gate_pass",
            "current_gate_pass",
            "area_gate_pass",
            "declared_cell_voltage_gate_pass",
        )
    )

    area_excess = (
        max(area / area_cap_m2 - 1.0, 0.0)
        if math.isfinite(area) and area > 0.0
        else math.inf
    )
    current_excess = (
        max(current / current_cap_a_m2 - 1.0, 0.0)
        if math.isfinite(current) and current > 0.0
        else math.inf
    )

    gates["normalized_area_cap_excess"] = area_excess
    gates["normalized_current_cap_excess"] = current_excess
    gates["normalized_constraint_excess"] = (
        area_excess + current_excess
        if math.isfinite(area_excess)
        and math.isfinite(current_excess)
        else math.inf
    )
    gates["normalized_target_shortfall"] = (
        normalized_target_shortfall
    )
    gates["target_removal_fraction"] = (
        max(0.0, min(1.0, 1.0 - normalized_target_shortfall))
        if math.isfinite(normalized_target_shortfall)
        else math.nan
    )
    return gates


def selection_key(row: Mapping[str, Any]) -> tuple[float, ...]:
    """Rank feasible rows by power and failed rows by gate proximity."""

    feasible = truth(row.get("all_declared_gates_pass"))
    native = truth(row.get("native_analysis_pass"))
    stack = truth(row.get("stack_gate_pass"))
    target_shortfall = finite(
        row.get("normalized_target_shortfall")
    )
    excess = finite(row.get("normalized_constraint_excess"))
    core = finite(row.get("analysis_core_power_kw"))
    receiver_ratio = finite(
        row.get("analysis_receiver_to_process_dry_air_ratio")
    )

    if not math.isfinite(target_shortfall):
        target_shortfall = 1.0e12
    if not math.isfinite(excess):
        excess = 1.0e12
    if not math.isfinite(core):
        core = 1.0e12
    if not math.isfinite(receiver_ratio):
        receiver_ratio = 1.0e12

    if feasible:
        return (0.0, core, receiver_ratio)

    return (
        1.0,
        0.0 if native else 1.0,
        0.0 if stack else 1.0,
        target_shortfall,
        excess,
        core,
        receiver_ratio,
    )


def select_best_row(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    materialized = [dict(row) for row in rows]
    if not materialized:
        raise ValueError("Cannot select from an empty result set")
    return min(materialized, key=selection_key)


def build_context(args: argparse.Namespace) -> dict[str, Any]:
    from heiq.wp1.studies import build_repository_context

    setup_args = SimpleNamespace(
        receiver_band="bridge_40_to_60",
        receiver_temperature_c=None,
        area_max_m2=float(args.area_max_m2),
        voltage_max_v=float(args.voltage_cap_v),
        current_cap_a_m2=float(args.current_cap_a_m2),
        lhs_samples=8,
        seed=20260812,
        smoke=False,
    )
    return build_repository_context(setup_args, root=ROOT)


def solve_point(
    base_context: Mapping[str, Any],
    point: SearchPoint,
    *,
    current_cap_a_m2: float,
    area_cap_m2: float,
    declared_cell_voltage_cap_v: float,
    record_profile: bool,
) -> tuple[dict[str, Any], pd.DataFrame]:
    from heiq.wp1.studies import solve_case

    context = selective_context_copy(base_context)
    apply_fixed_geometry(context)

    row, profile, _receiver = solve_case(
        context,
        target="O30",
        material=dict(FIXED_MATERIAL),
        voltage_v=point.terminal_voltage_v,
        receiver_multiplier=point.receiver_capacity_multiplier,
        record_profile=record_profile,
    )

    result = dict(row)
    result.update(
        {
            "search_point_id": point.search_point_id,
            "search_target": "O30",
            "search_terminal_voltage_v": point.terminal_voltage_v,
            "search_receiver_capacity_multiplier": (
                point.receiver_capacity_multiplier
            ),
            "search_scope": (
                "fixed case-94 material and geometry; receiver-capacity "
                "and sub-1.0-V boundary scan"
            ),
        }
    )
    result.update(
        evaluate_gates(
            result,
            point=point,
            current_cap_a_m2=current_cap_a_m2,
            area_cap_m2=area_cap_m2,
            declared_cell_voltage_cap_v=(
                declared_cell_voltage_cap_v
            ),
        )
    )
    return result, profile


def write_interpretation(
    output_dir: Path,
    results: pd.DataFrame,
    selected: Mapping[str, Any],
) -> None:
    feasible_count = int(
        results["all_declared_gates_pass"].astype(bool).sum()
    )
    total_count = len(results)
    is_feasible = truth(selected["all_declared_gates_pass"])

    status = (
        "At least one point passed all declared gates."
        if feasible_count
        else (
            "No point in this local scan passed all declared gates. "
            "This does not establish global O30 infeasibility."
        )
    )
    selection_label = (
        "best feasible point" if is_feasible else "nearest ranked point"
    )

    lines = [
        "# O30 one-volt receiver-capacity boundary scan",
        "",
        "## Result",
        "",
        f"{status} Feasible points: {feasible_count}/{total_count}.",
        "",
        f"The {selection_label} is "
        f"`{selected['search_point_id']}` with:",
        "",
        f"- voltage: {finite(selected.get('search_terminal_voltage_v')):.6g} V",
        "- receiver capacity multiplier: "
        f"{finite(selected.get('search_receiver_capacity_multiplier')):.6g}",
        "- active area: "
        f"{finite(selected.get('required_active_area_m2')):.6g} m2",
        "- maximum current density: "
        f"{finite(selected.get('maximum_local_current_density_a_m2')):.6g} A/m2",
        "- analysis core power: "
        f"{finite(selected.get('analysis_core_power_kw')):.6g} kW",
        "- receiver/process dry-air ratio: "
        f"{finite(selected.get('analysis_receiver_to_process_dry_air_ratio')):.6g}",
        "- all declared gates pass: "
        f"{truth(selected.get('all_declared_gates_pass'))}.",
        "",
        "## What this scan establishes",
        "",
        "The scan isolates receiver-capacity leverage at fixed material and "
        "fixed legacy case-94 geometry while enforcing the declared 1.0 V, "
        "21 A/m2 and 9000 m2 limits independently.",
        "",
        "## What this scan does not establish",
        "",
        "It is not a global material or geometry optimisation. A failed scan "
        "does not prove that O30 is impossible. A passing point is still a "
        "model-feasible hypothesis, not a hardware-validated design. Large "
        "receiver-air ratios, cumulative channel widths, manifolds, "
        "maldistribution and material validation remain separate gates.",
        "",
        "Liquid receiver operation is excluded from this gas-receiver scan.",
        "",
    ]
    (output_dir / "INTERPRETATION.md").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )


def self_test() -> None:
    points = build_points(
        (0.8, 1.0),
        (1.01, 1.2),
        voltage_cap_v=1.0,
    )
    assert len(points) == 4
    assert max(point.terminal_voltage_v for point in points) == 1.0

    marker = math
    context = {
        "base": {"channel": {}},
        "cfg12": {"channel": {}},
        "args": SimpleNamespace(area_max_m2=9000.0),
        "v2": marker,
    }
    copied = selective_context_copy(context)
    apply_fixed_geometry(copied)
    assert copied["v2"] is marker
    assert "process_gap_m" not in context["base"]["channel"]
    assert copied["base"]["channel"]["process_gap_m"] == 0.002

    gates = evaluate_gates(
        {
            "analysis_pass": True,
            "stack_feasible": True,
            "required_active_area_m2": 8999.0,
            "maximum_local_current_density_a_m2": 20.0,
        },
        point=SearchPoint(1.0, 1.05),
        current_cap_a_m2=21.0,
        area_cap_m2=9000.0,
        declared_cell_voltage_cap_v=1.0,
    )
    assert gates["all_declared_gates_pass"]

    failed = dict(gates)
    failed.update(
        {
            "search_point_id": "failed",
            "all_declared_gates_pass": False,
            "normalized_constraint_excess": 0.1,
            "analysis_core_power_kw": 1.0,
        }
    )
    passed = dict(gates)
    passed.update(
        {
            "search_point_id": "passed",
            "analysis_core_power_kw": 10.0,
        }
    )
    assert select_best_row((failed, passed))["search_point_id"] == "passed"

    print(
        "Self-test passed: grid construction, selective context copying, "
        "geometry override, independent gates and selection are consistent."
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Scan whether receiver capacity can recover O30 below the "
            "declared 1.0 V cell cap at fixed case-94 material and geometry."
        )
    )
    parser.add_argument("--output-dir")
    parser.add_argument(
        "--voltages-v",
        type=float,
        nargs="+",
        default=list(DEFAULT_VOLTAGES_V),
    )
    parser.add_argument(
        "--receiver-multipliers",
        type=float,
        nargs="+",
        default=list(DEFAULT_RECEIVER_MULTIPLIERS),
    )
    parser.add_argument("--voltage-cap-v", type=float, default=1.0)
    parser.add_argument("--current-cap-a-m2", type=float, default=21.0)
    parser.add_argument("--area-max-m2", type=float, default=9000.0)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reuse completed per-point checkpoints in an existing output dir",
    )
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.self_test:
        self_test()
        return 0

    if not args.output_dir:
        raise SystemExit("--output-dir is required")

    points = build_points(
        args.voltages_v,
        args.receiver_multipliers,
        voltage_cap_v=float(args.voltage_cap_v),
    )
    context = build_context(args)
    declared_cap = float(
        context["cfg12"]["voltage_grid"][
            "maximum_cell_terminal_voltage_v"
        ]
    )
    if float(args.voltage_cap_v) > declared_cap + 1.0e-12:
        raise SystemExit(
            f"Requested voltage cap {args.voltage_cap_v} V exceeds "
            f"the repository contract {declared_cap} V"
        )

    output_dir = ROOT / args.output_dir
    if args.resume:
        if not output_dir.is_dir():
            raise SystemExit(
                "--resume requires an existing output directory"
            )
    else:
        output_dir.mkdir(parents=True, exist_ok=False)

    checkpoint_dir = output_dir / "checkpoints"
    checkpoint_dir.mkdir(exist_ok=args.resume)

    rows: list[dict[str, Any]] = []
    for index, point in enumerate(points, start=1):
        checkpoint_path = (
            checkpoint_dir / f"{point.search_point_id}.csv"
        )

        if args.resume and checkpoint_path.is_file():
            checkpoint = pd.read_csv(checkpoint_path)
            if len(checkpoint) != 1:
                raise RuntimeError(
                    f"Invalid checkpoint {checkpoint_path}: "
                    f"expected one row, found {len(checkpoint)}"
                )
            row = checkpoint.iloc[0].to_dict()
            if row.get("search_point_id") != point.search_point_id:
                raise RuntimeError(
                    f"Checkpoint identity mismatch in {checkpoint_path}"
                )
            row.update(
                evaluate_gates(
                    row,
                    point=point,
                    current_cap_a_m2=float(args.current_cap_a_m2),
                    area_cap_m2=float(args.area_max_m2),
                    declared_cell_voltage_cap_v=declared_cap,
                )
            )
            pd.DataFrame([row]).to_csv(checkpoint_path, index=False)
            rows.append(row)
            print(
                f"O30 one-volt scan {index}/{len(points)}: "
                f"reused {point.search_point_id}",
                flush=True,
            )
            continue

        print(
            f"O30 one-volt scan {index}/{len(points)}: "
            f"V={point.terminal_voltage_v:.6g}, "
            f"receiver multiplier={point.receiver_capacity_multiplier:.6g}",
            flush=True,
        )
        row, _profile = solve_point(
            context,
            point,
            current_cap_a_m2=float(args.current_cap_a_m2),
            area_cap_m2=float(args.area_max_m2),
            declared_cell_voltage_cap_v=declared_cap,
            record_profile=False,
        )
        rows.append(row)
        pd.DataFrame([row]).to_csv(checkpoint_path, index=False)
        pd.DataFrame(rows).to_csv(
            output_dir / "all_cases_partial.csv",
            index=False,
        )

    results = pd.DataFrame(rows)
    results.to_csv(output_dir / "all_cases.csv", index=False)
    results.to_csv(
        output_dir / "all_cases_partial.csv",
        index=False,
    )

    selected = select_best_row(rows)
    selected_frame = pd.DataFrame([selected])
    selected_frame.to_csv(output_dir / "selected_case.csv", index=False)

    feasible = results[
        results["all_declared_gates_pass"].astype(bool)
    ].copy()
    if not feasible.empty:
        feasible = feasible.sort_values(
            [
                "analysis_core_power_kw",
                "analysis_receiver_to_process_dry_air_ratio",
            ],
            kind="stable",
        )
    feasible.to_csv(output_dir / "feasible_cases.csv", index=False)

    selected_point = SearchPoint(
        terminal_voltage_v=float(
            selected["search_terminal_voltage_v"]
        ),
        receiver_capacity_multiplier=float(
            selected["search_receiver_capacity_multiplier"]
        ),
    )
    repeated, profile = solve_point(
        context,
        selected_point,
        current_cap_a_m2=float(args.current_cap_a_m2),
        area_cap_m2=float(args.area_max_m2),
        declared_cell_voltage_cap_v=declared_cap,
        record_profile=True,
    )
    if repeated["search_point_id"] != selected["search_point_id"]:
        raise RuntimeError("Selected-point profile replay changed identity")
    if isinstance(profile, pd.DataFrame):
        profile.to_csv(output_dir / "selected_profile.csv", index=False)

    metadata = {
        "model_basis": (
            "canonical native prearchitecture solve_case with coupled "
            "gas receiver"
        ),
        "scientific_scope": (
            "local receiver-capacity boundary scan at fixed legacy O30 "
            "case-94 material and geometry"
        ),
        "target": "O30",
        "voltage_cap_v": float(args.voltage_cap_v),
        "declared_cell_voltage_cap_v": declared_cap,
        "current_cap_a_m2": float(args.current_cap_a_m2),
        "area_max_m2": float(args.area_max_m2),
        "voltages_v": sorted({float(v) for v in args.voltages_v}),
        "receiver_multipliers": sorted(
            {float(v) for v in args.receiver_multipliers}
        ),
        "fixed_material": FIXED_MATERIAL,
        "fixed_geometry": FIXED_GEOMETRY,
        "selected_point": {
            key: value
            for key, value in selected.items()
            if isinstance(value, (str, int, float, bool))
        },
        "limitations": [
            "not a global material search",
            "not a global geometry search",
            "hypothetical legacy material vector",
            "gas receiver only; liquid receiver excluded",
            "no finite manifold or maldistribution model",
            "no experimental material or hardware validation",
        ],
    }
    (output_dir / "run_metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True, allow_nan=True) + "\n",
        encoding="utf-8",
    )
    write_interpretation(output_dir, results, selected)

    show = [
        "search_point_id",
        "search_terminal_voltage_v",
        "search_receiver_capacity_multiplier",
        "required_active_area_m2",
        "maximum_local_current_density_a_m2",
        "analysis_receiver_to_process_dry_air_ratio",
        "eo_grid_power_kw",
        "process_channel_fan_power_kw",
        "receiver_channel_fan_power_kw",
        "analysis_core_power_kw",
        "native_analysis_pass",
        "stack_gate_pass",
        "current_gate_pass",
        "area_gate_pass",
        "declared_cell_voltage_gate_pass",
        "all_declared_gates_pass",
        "target_removal_fraction",
        "normalized_target_shortfall",
    ]
    print()
    print("=== SELECTED O30 ONE-VOLT POINT ===")
    print(selected_frame[show].to_string(index=False))
    print()
    print(
        "Feasible points: "
        f"{int(results['all_declared_gates_pass'].astype(bool).sum())}/"
        f"{len(results)}"
    )
    print(f"Outputs: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
