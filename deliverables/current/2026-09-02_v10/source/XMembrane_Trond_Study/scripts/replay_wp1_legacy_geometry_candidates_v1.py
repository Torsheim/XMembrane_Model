#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

import pandas as pd

from heiq.wp1.studies import (
    build_repository_context,
    solve_case,
)


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class LegacyGeometryCandidate:
    candidate_id: str
    target: str
    geometry_case_index: int
    terminal_voltage_v: float
    receiver_capacity_multiplier: float
    process_gap_m: float
    receiver_gap_m: float
    process_velocity_m_s: float
    active_sides: float
    receiver_geometry_mode: str
    fixed_receiver_velocity_m_s: float | None
    water_drag: float
    water_diffusivity_m2_s: float
    conductivity_s_m: float
    dry_thickness_um: float
    water_capacity_mol_m3_activity: float
    diffusivity_activity_exponent: float
    conductivity_activity_exponent: float
    capacity_activity_exponent: float
    legacy_required_active_area_m2: float
    legacy_maximum_local_current_density_a_m2: float
    legacy_eo_grid_power_kw: float
    legacy_process_channel_fan_power_kw: float
    legacy_receiver_channel_fan_power_kw: float
    legacy_core_plus_header_power_kw: float


COMMON_MATERIAL = {
    "water_drag": 100.06078708377692,
    "water_diffusivity_m2_s": 1.597880133581376e-14,
    "conductivity_s_m": 23.171886845550485,
    "dry_thickness_um": 36.91369958200169,
    "water_capacity_mol_m3_activity": 10000.0,
    "diffusivity_activity_exponent": 2.0,
    "conductivity_activity_exponent": 4.0,
    "capacity_activity_exponent": 0.0,
}


CANDIDATES = (
    LegacyGeometryCandidate(
        candidate_id="legacy_O30_case_94",
        target="O30",
        geometry_case_index=94,
        terminal_voltage_v=1.2635555556,
        receiver_capacity_multiplier=1.01,
        process_gap_m=0.002,
        receiver_gap_m=0.004,
        process_velocity_m_s=1.0,
        active_sides=2.0,
        receiver_geometry_mode="aligned_equal_total_width",
        fixed_receiver_velocity_m_s=None,
        **COMMON_MATERIAL,
        legacy_required_active_area_m2=8670.577696948978,
        legacy_maximum_local_current_density_a_m2=17.763302365886346,
        legacy_eo_grid_power_kw=91.14011300215746,
        legacy_process_channel_fan_power_kw=0.7485010408578956,
        legacy_receiver_channel_fan_power_kw=0.2897983568212181,
        legacy_core_plus_header_power_kw=92.17841239983656,
    ),
    LegacyGeometryCandidate(
        candidate_id="legacy_O50_case_310",
        target="O50",
        geometry_case_index=310,
        terminal_voltage_v=0.343,
        receiver_capacity_multiplier=1.01,
        process_gap_m=0.004,
        receiver_gap_m=0.004,
        process_velocity_m_s=1.0,
        active_sides=2.0,
        receiver_geometry_mode="aligned_equal_total_width",
        fixed_receiver_velocity_m_s=None,
        **COMMON_MATERIAL,
        legacy_required_active_area_m2=7757.248963824429,
        legacy_maximum_local_current_density_a_m2=6.7684412476937865,
        legacy_eo_grid_power_kw=14.986573023770475,
        legacy_process_channel_fan_power_kw=0.3348282621156577,
        legacy_receiver_channel_fan_power_kw=0.3805668341163483,
        legacy_core_plus_header_power_kw=15.70196812000248,
    ),
)


def truth(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {
        "true",
        "1",
        "yes",
    }


def finite(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return math.nan
    return result if math.isfinite(result) else math.nan


def selective_context_copy(
    context: Mapping[str, Any],
) -> dict[str, Any]:
    """Copy mutable configuration while preserving solver modules."""

    copied = dict(context)
    copied["base"] = copy.deepcopy(context["base"])
    copied["cfg12"] = copy.deepcopy(context["cfg12"])

    if "args" in context:
        copied["args"] = copy.copy(context["args"])

    return copied


def material_from_candidate(
    candidate: LegacyGeometryCandidate,
) -> dict[str, Any]:
    return {
        "name": candidate.candidate_id + "_material",
        "model": "powerlaw",
        "water_drag": candidate.water_drag,
        "water_diffusivity_m2_s": (
            candidate.water_diffusivity_m2_s
        ),
        "conductivity_s_m": candidate.conductivity_s_m,
        "dry_thickness_um": candidate.dry_thickness_um,
        "water_capacity_mol_m3_activity": (
            candidate.water_capacity_mol_m3_activity
        ),
        "diffusivity_activity_exponent": (
            candidate.diffusivity_activity_exponent
        ),
        "conductivity_activity_exponent": (
            candidate.conductivity_activity_exponent
        ),
        "capacity_activity_exponent": (
            candidate.capacity_activity_exponent
        ),
        "interpretation": (
            "Legacy V11 hypothetical material vector replayed "
            "on the canonical native core; not material validation"
        ),
    }


def apply_candidate_geometry(
    context: dict[str, Any],
    candidate: LegacyGeometryCandidate,
) -> None:
    channel = context["base"]["channel"]

    channel.update(
        {
            "process_gap_m": candidate.process_gap_m,
            "receiver_gap_m": candidate.receiver_gap_m,
            "process_velocity_m_s": (
                candidate.process_velocity_m_s
            ),
            "active_sides_per_process_channel": (
                candidate.active_sides
            ),
            "receiver_geometry_mode": (
                candidate.receiver_geometry_mode
            ),
        }
    )

    cfg_channel = context["cfg12"]["channel"]
    cfg_channel["active_sides_per_process_channel"] = (
        candidate.active_sides
    )
    cfg_channel["receiver_geometry_mode"] = (
        candidate.receiver_geometry_mode
    )

    if candidate.fixed_receiver_velocity_m_s is not None:
        value = float(candidate.fixed_receiver_velocity_m_s)
        channel["fixed_receiver_velocity_m_s"] = value
        cfg_channel["fixed_receiver_velocity_m_s"] = value


def evaluate_declared_gates(
    row: Mapping[str, Any],
    *,
    candidate: LegacyGeometryCandidate,
    context: Mapping[str, Any],
    workflow_voltage_max_v: float,
) -> dict[str, Any]:
    current_cap = float(
        context["cfg12"]["operating"][
            "current_density_cap_a_m2"
        ]
    )
    area_cap = float(context["args"].area_max_m2)
    cell_voltage_cap = float(
        context["cfg12"]["voltage_grid"][
            "maximum_cell_terminal_voltage_v"
        ]
    )

    current = finite(
        row.get("maximum_local_current_density_a_m2")
    )
    area = finite(row.get("required_active_area_m2"))
    voltage = float(candidate.terminal_voltage_v)

    gates = {
        "native_analysis_pass": truth(
            row.get("analysis_pass")
        ),
        "stack_gate_pass": truth(
            row.get("stack_feasible")
        ),
        "current_gate_pass": (
            math.isfinite(current)
            and 0.0 < current <= current_cap + 1.0e-9
        ),
        "area_gate_pass": (
            math.isfinite(area)
            and 0.0 < area <= area_cap + 1.0e-9
        ),
        "workflow_voltage_gate_pass": (
            0.0 < voltage <= workflow_voltage_max_v + 1.0e-12
        ),
        "declared_cell_voltage_gate_pass": (
            0.0 < voltage <= cell_voltage_cap + 1.0e-12
        ),
        "current_cap_a_m2": current_cap,
        "area_cap_m2": area_cap,
        "workflow_voltage_max_v": workflow_voltage_max_v,
        "declared_cell_voltage_cap_v": cell_voltage_cap,
    }

    gates["all_declared_gates_pass"] = all(
        bool(gates[key])
        for key in (
            "native_analysis_pass",
            "stack_gate_pass",
            "current_gate_pass",
            "area_gate_pass",
            "workflow_voltage_gate_pass",
            "declared_cell_voltage_gate_pass",
        )
    )

    return gates


def relative_error(actual: Any, reference: float) -> float:
    actual_value = finite(actual)
    reference_value = float(reference)
    if not math.isfinite(actual_value):
        return math.nan
    scale = max(abs(reference_value), 1.0e-12)
    return abs(actual_value - reference_value) / scale


def add_legacy_comparison(
    row: dict[str, Any],
    candidate: LegacyGeometryCandidate,
) -> None:
    pairs = {
        "required_active_area_m2": (
            candidate.legacy_required_active_area_m2
        ),
        "maximum_local_current_density_a_m2": (
            candidate
            .legacy_maximum_local_current_density_a_m2
        ),
        "eo_grid_power_kw": candidate.legacy_eo_grid_power_kw,
        "process_channel_fan_power_kw": (
            candidate.legacy_process_channel_fan_power_kw
        ),
        "receiver_channel_fan_power_kw": (
            candidate.legacy_receiver_channel_fan_power_kw
        ),
        "analysis_core_power_kw": (
            candidate.legacy_core_plus_header_power_kw
        ),
    }

    errors: list[float] = []

    for column, reference in pairs.items():
        label = column.removeprefix("analysis_")
        row[f"legacy_reference_{label}"] = reference
        error = relative_error(row.get(column), reference)
        row[f"relative_error_vs_legacy_{label}"] = error
        errors.append(error)

    finite_errors = [
        value for value in errors if math.isfinite(value)
    ]
    maximum_error = (
        max(finite_errors) if finite_errors else math.nan
    )
    row["maximum_relative_error_vs_legacy"] = maximum_error
    row["native_legacy_equivalence_within_1e_6"] = bool(
        math.isfinite(maximum_error)
        and maximum_error <= 1.0e-6
    )


def run_variant(
    base_context: Mapping[str, Any],
    candidate: LegacyGeometryCandidate,
    *,
    variant: str,
    workflow_voltage_max_v: float,
    record_profile: bool,
) -> tuple[dict[str, Any], pd.DataFrame]:
    context = selective_context_copy(base_context)

    if variant == "candidate_geometry":
        apply_candidate_geometry(context, candidate)
    elif variant != "canonical_default_geometry":
        raise ValueError(f"Unknown variant {variant}")

    row, profile, _receiver = solve_case(
        context,
        target=candidate.target,
        material=material_from_candidate(candidate),
        voltage_v=candidate.terminal_voltage_v,
        receiver_multiplier=(
            candidate.receiver_capacity_multiplier
        ),
        record_profile=record_profile,
    )

    result = dict(row)
    result.update(
        {
            "replay_candidate_id": candidate.candidate_id,
            "replay_variant": variant,
            "legacy_geometry_case_index": (
                candidate.geometry_case_index
            ),
            "replay_material_evidence": (
                "hypothetical legacy V11 vector"
            ),
        }
    )
    result.update(
        evaluate_declared_gates(
            result,
            candidate=candidate,
            context=context,
            workflow_voltage_max_v=workflow_voltage_max_v,
        )
    )

    if variant == "candidate_geometry":
        add_legacy_comparison(result, candidate)

    return result, profile


def build_context(args: argparse.Namespace) -> dict[str, Any]:
    setup_args = SimpleNamespace(
        receiver_band="bridge_40_to_60",
        receiver_temperature_c=None,
        area_max_m2=float(args.area_max_m2),
        voltage_max_v=float(args.workflow_voltage_max_v),
        current_cap_a_m2=float(args.current_cap_a_m2),
        lhs_samples=8,
        seed=20260812,
        smoke=False,
    )
    return build_repository_context(setup_args, root=ROOT)


def build_comparison(results: pd.DataFrame) -> pd.DataFrame:
    metrics = [
        "required_active_area_m2",
        "maximum_local_current_density_a_m2",
        "eo_grid_power_kw",
        "process_channel_fan_power_kw",
        "receiver_channel_fan_power_kw",
        "analysis_core_power_kw",
        "process_channel_length_m",
        "process_total_channel_width_m",
        "receiver_channel_length_m",
        "receiver_total_channel_width_m",
    ]

    rows: list[dict[str, Any]] = []

    for candidate_id, group in results.groupby(
        "replay_candidate_id",
        sort=False,
    ):
        indexed = group.set_index("replay_variant")
        default = indexed.loc["canonical_default_geometry"]
        replay = indexed.loc["candidate_geometry"]

        item: dict[str, Any] = {
            "replay_candidate_id": candidate_id,
            "target": replay["target"],
            "candidate_all_declared_gates_pass": bool(
                replay["all_declared_gates_pass"]
            ),
        }

        for metric in metrics:
            default_value = finite(default.get(metric))
            replay_value = finite(replay.get(metric))
            item[f"default_{metric}"] = default_value
            item[f"candidate_{metric}"] = replay_value
            item[f"candidate_minus_default_{metric}"] = (
                replay_value - default_value
                if (
                    math.isfinite(replay_value)
                    and math.isfinite(default_value)
                )
                else math.nan
            )

        rows.append(item)

    return pd.DataFrame(rows)


def write_interpretation(
    output_dir: Path,
    results: pd.DataFrame,
    comparison: pd.DataFrame,
) -> None:
    candidate_rows = results[
        results["replay_variant"].eq("candidate_geometry")
    ]

    lines = [
        "# Canonical replay of legacy geometry candidates",
        "",
        "This directory is a native-core replay, not a new material "
        "or product validation.",
        "",
        "## Gate result",
        "",
    ]

    for _, row in candidate_rows.iterrows():
        lines.append(
            "- "
            f"{row['replay_candidate_id']}: "
            f"native analysis pass={row['native_analysis_pass']}, "
            f"stack pass={row['stack_gate_pass']}, "
            "declared 1.0 V cell cap pass="
            f"{row['declared_cell_voltage_gate_pass']}, "
            "all declared gates pass="
            f"{row['all_declared_gates_pass']}."
        )

    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "The candidate geometry changes local gas-film transfer, "
            "receiver sizing, channel length and fan power and is "
            "therefore re-solved through the canonical coupled core.",
            "",
            "The cumulative channel width is not a physical module "
            "width. It represents extensive hydraulic parallelisation. "
            "A separate module/manifold design is required.",
            "",
            "Header losses, maldistribution, finite manifold geometry, "
            "wet-electrode behaviour, construction tolerances and "
            "experimental material validation remain unresolved.",
            "",
            "The configuration declares 1.0 V as a hard per-cell cap. "
            "A candidate above that value must not be called feasible "
            "without an explicit reviewed contract change.",
            "",
            "## Files",
            "",
            "- `all_replay_cases.csv`: all native replay rows",
            "- `candidate_vs_default_geometry.csv`: controlled geometry "
            "comparison at identical material, voltage and receiver state",
            "- `profiles/`: axial profiles from each native solve",
            "- `run_metadata.json`: model boundary and candidate inputs",
            "",
        ]
    )

    (output_dir / "INTERPRETATION.md").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )


def self_test() -> None:
    module_marker = math
    context = {
        "base": {
            "channel": {
                "process_gap_m": 0.001,
                "receiver_gap_m": 0.001,
                "process_velocity_m_s": 2.0,
                "active_sides_per_process_channel": 1.0,
                "receiver_geometry_mode": (
                    "aligned_equal_total_width"
                ),
            }
        },
        "cfg12": {
            "channel": {
                "active_sides_per_process_channel": 1.0,
                "receiver_geometry_mode": (
                    "aligned_equal_total_width"
                ),
            },
            "operating": {
                "current_density_cap_a_m2": 21.0,
            },
            "voltage_grid": {
                "maximum_cell_terminal_voltage_v": 1.0,
            },
        },
        "args": SimpleNamespace(area_max_m2=9000.0),
        "v2": module_marker,
    }

    copied = selective_context_copy(context)
    apply_candidate_geometry(copied, CANDIDATES[0])

    assert context["base"]["channel"]["process_gap_m"] == 0.001
    assert copied["base"]["channel"]["process_gap_m"] == 0.002
    assert copied["v2"] is module_marker

    gates = evaluate_declared_gates(
        {
            "analysis_pass": True,
            "stack_feasible": True,
            "maximum_local_current_density_a_m2": 17.0,
            "required_active_area_m2": 8000.0,
        },
        candidate=CANDIDATES[0],
        context=context,
        workflow_voltage_max_v=24.0,
    )
    assert gates["native_analysis_pass"]
    assert not gates["declared_cell_voltage_gate_pass"]
    assert not gates["all_declared_gates_pass"]

    print(
        "Self-test passed: selective context copying, geometry "
        "override and independent voltage gating are consistent."
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Replay selected legacy geometry hypotheses on the "
            "canonical native coupled core."
        )
    )
    parser.add_argument("--output-dir")
    parser.add_argument(
        "--current-cap-a-m2",
        type=float,
        default=21.0,
    )
    parser.add_argument(
        "--area-max-m2",
        type=float,
        default=9000.0,
    )
    parser.add_argument(
        "--workflow-voltage-max-v",
        type=float,
        default=24.0,
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.self_test:
        self_test()
        return 0

    if not args.output_dir:
        raise SystemExit("--output-dir is required")

    output_dir = ROOT / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=False)
    profile_dir = output_dir / "profiles"
    profile_dir.mkdir()

    context = build_context(args)
    result_rows: list[dict[str, Any]] = []

    for candidate in CANDIDATES:
        for variant in (
            "canonical_default_geometry",
            "candidate_geometry",
        ):
            print(
                f"Replaying {candidate.candidate_id}: {variant}",
                flush=True,
            )
            row, profile = run_variant(
                context,
                candidate,
                variant=variant,
                workflow_voltage_max_v=float(
                    args.workflow_voltage_max_v
                ),
                record_profile=True,
            )
            result_rows.append(row)

            if isinstance(profile, pd.DataFrame):
                profile.to_csv(
                    profile_dir
                    / f"{candidate.candidate_id}_{variant}.csv",
                    index=False,
                )

    results = pd.DataFrame(result_rows)
    results.to_csv(
        output_dir / "all_replay_cases.csv",
        index=False,
    )

    comparison = build_comparison(results)
    comparison.to_csv(
        output_dir / "candidate_vs_default_geometry.csv",
        index=False,
    )

    metadata = {
        "model_basis": (
            "canonical native prearchitecture solve_case with full "
            "coupled process/receiver re-solve"
        ),
        "current_cap_a_m2": float(args.current_cap_a_m2),
        "area_max_m2": float(args.area_max_m2),
        "workflow_voltage_max_v": float(
            args.workflow_voltage_max_v
        ),
        "declared_cell_voltage_cap_v": float(
            context["cfg12"]["voltage_grid"][
                "maximum_cell_terminal_voltage_v"
            ]
        ),
        "candidate_inputs": [
            asdict(candidate) for candidate in CANDIDATES
        ],
        "limitations": [
            "hypothetical legacy material vector",
            "no finite manifold or maldistribution model",
            "cumulative channel width is not module width",
            "no experimental material or hardware validation",
            "gas receiver only; liquid receiver excluded",
        ],
    }
    (output_dir / "run_metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    write_interpretation(output_dir, results, comparison)

    show_columns = [
        "replay_candidate_id",
        "replay_variant",
        "terminal_voltage_v",
        "required_active_area_m2",
        "maximum_local_current_density_a_m2",
        "eo_grid_power_kw",
        "process_channel_fan_power_kw",
        "receiver_channel_fan_power_kw",
        "analysis_core_power_kw",
        "process_channel_length_m",
        "process_total_channel_width_m",
        "stack_feasible",
        "native_analysis_pass",
        "declared_cell_voltage_gate_pass",
        "all_declared_gates_pass",
    ]
    print()
    print("=== CANONICAL REPLAY RESULTS ===")
    print(results[show_columns].to_string(index=False))
    print()
    print(f"Outputs: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
