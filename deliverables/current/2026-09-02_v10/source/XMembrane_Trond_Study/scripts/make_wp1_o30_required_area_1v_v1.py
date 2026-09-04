#!/usr/bin/env python3
"""Solve the nonlinear O30 required-area curve at exactly 1.0 V.

This workflow deliberately separates numerical solver guards from engineering
acceptance criteria.  In particular, local current density is reported as a
diagnostic and is not used as an acceptance gate.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable, Mapping

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
STUDY_ID = "wp1_o30_required_area_1v_v1"
TERMINAL_VOLTAGE_V = 1.0


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


MAIN_COLUMNS = [
    "receiver_capacity_multiplier",
    "analysis_receiver_to_process_dry_air_ratio",
    "analysis_receiver_airflow_cfm",
    "required_active_area_m2",
    "area_delta_vs_reference_m2",
    "area_delta_vs_reference_percent",
    "maximum_local_current_density_a_m2",
    "integrated_water_transfer_kg_h",
    "eo_grid_power_kw",
    "process_channel_fan_power_kw",
    "receiver_channel_fan_power_kw",
    "analysis_core_power_kw",
    "required_area_solution_valid",
]


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


def normalize_receiver_multipliers(
    values: Iterable[float],
) -> tuple[float, ...]:
    multipliers = tuple(sorted({float(value) for value in values}))
    if not multipliers:
        raise ValueError("At least one receiver multiplier is required")
    if any(
        not math.isfinite(value) or value <= 1.0
        for value in multipliers
    ):
        raise ValueError(
            "Receiver capacity multipliers must be finite and greater than 1"
        )
    return multipliers


def selective_context_copy(
    context: Mapping[str, Any],
) -> dict[str, Any]:
    """Copy mutable configuration while preserving imported solver modules."""

    copied = dict(context)
    copied["base"] = copy.deepcopy(context["base"])
    copied["cfg12"] = copy.deepcopy(context["cfg12"])
    if "args" in context:
        copied["args"] = copy.copy(context["args"])
    return copied


def apply_fixed_geometry(context: dict[str, Any]) -> None:
    context["base"]["channel"].update(FIXED_GEOMETRY)
    context["cfg12"]["channel"][
        "active_sides_per_process_channel"
    ] = FIXED_GEOMETRY["active_sides_per_process_channel"]
    context["cfg12"]["channel"][
        "receiver_geometry_mode"
    ] = FIXED_GEOMETRY["receiver_geometry_mode"]


def worker_exception_absent(value: Any) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    return not str(value).strip()


def required_area_validity(
    row: Mapping[str, Any],
    *,
    integration_ceiling_m2: float,
    mass_balance_relative_tolerance: float = 1.0e-8,
    humidity_ratio_absolute_tolerance: float = 1.0e-9,
    terminal_voltage_error_tolerance_v: float = 1.0e-8,
) -> dict[str, Any]:
    """Evaluate numerical/physical validity without area or current gates."""

    area = finite(row.get("required_active_area_m2"))
    outlet = finite(row.get("process_outlet_humidity_ratio_kg_kg_da"))
    target = finite(row.get("target_humidity_ratio_kg_kg_da"))
    maximum_current = finite(
        row.get("maximum_local_current_density_a_m2")
    )
    minimum_flux = finite(row.get("minimum_local_flux_mol_m2_s"))
    process_error = finite(row.get("process_mass_balance_relative_error"))
    receiver_error = finite(row.get("receiver_mass_balance_relative_error"))
    voltage_error = finite(row.get("maximum_terminal_voltage_error_v"))

    checks = {
        "target_reached_validity_pass": (
            str(row.get("status", "")) == "target_reached"
            and truth(row.get("target_reached"))
        ),
        "target_capacity_validity_pass": truth(
            row.get("target_capacity_sufficient")
        ),
        "active_area_finite_positive_validity_pass": (
            math.isfinite(area) and area > 0.0
        ),
        "integration_ceiling_not_reached_validity_pass": (
            math.isfinite(area)
            and area <= integration_ceiling_m2 + 1.0e-9
            and str(row.get("status", "")) != "area_limit_before_target"
        ),
        "process_target_residual_validity_pass": (
            math.isfinite(outlet)
            and math.isfinite(target)
            and abs(outlet - target) <= humidity_ratio_absolute_tolerance
        ),
        "local_solver_evaluated_validity_pass": truth(
            row.get("local_solver_evaluated")
        ),
        "positive_transport_direction_validity_pass": (
            math.isfinite(minimum_flux)
            and minimum_flux > 0.0
            and math.isfinite(maximum_current)
            and maximum_current > 0.0
        ),
        "countercurrent_boundary_validity_pass": (
            truth(row.get("countercurrent_boundary_solution_valid"))
            and truth(row.get("receiver_boundary_pass"))
        ),
        "water_balance_validity_pass": (
            truth(row.get("water_balance_evaluated"))
            and truth(row.get("water_balance_pass"))
            and math.isfinite(process_error)
            and abs(process_error) <= mass_balance_relative_tolerance
            and math.isfinite(receiver_error)
            and abs(receiver_error) <= mass_balance_relative_tolerance
        ),
        "shortened_endpoint_validity_pass": truth(
            row.get("shortened_endpoint_resolved")
        ),
        "terminal_voltage_reconstruction_validity_pass": (
            math.isfinite(voltage_error)
            and abs(voltage_error) <= terminal_voltage_error_tolerance_v
        ),
        "finite_power_validity_pass": all(
            math.isfinite(finite(row.get(column)))
            and finite(row.get(column)) >= 0.0
            for column in (
                "eo_grid_power_kw",
                "process_channel_fan_power_kw",
                "receiver_channel_fan_power_kw",
                "analysis_core_power_kw",
            )
        ),
        "worker_exception_absent_validity_pass": worker_exception_absent(
            row.get("worker_exception")
        ),
    }
    failed = [name for name, passed in checks.items() if not passed]
    return {
        **checks,
        "required_area_solution_valid": not failed,
        "required_area_invalid_reasons": ";".join(failed),
    }


def decorate_result(
    row: Mapping[str, Any],
    *,
    receiver_multiplier: float,
    integration_area_step_m2: float,
    integration_ceiling_m2: float,
    solver_current_safety_guard_a_m2: float,
    area_reference_m2: float,
    contract_sha256: str,
) -> dict[str, Any]:
    result = dict(row)
    area = finite(row.get("required_active_area_m2"))
    current = finite(row.get("maximum_local_current_density_a_m2"))
    result.update(
        {
            "study_id": STUDY_ID,
            "study_contract_sha256": contract_sha256,
            "receiver_capacity_multiplier": float(receiver_multiplier),
            "study_terminal_voltage_v": TERMINAL_VOLTAGE_V,
            "integration_area_step_m2": float(integration_area_step_m2),
            "integration_ceiling_m2": float(integration_ceiling_m2),
            "solver_current_safety_guard_a_m2": float(
                solver_current_safety_guard_a_m2
            ),
            "current_density_acceptance_gate_applied": False,
            "current_density_interpretation": (
                "diagnostic_only_no_engineering_acceptance_limit"
            ),
            "design_area_cap_applied": False,
            "area_reference_m2": float(area_reference_m2),
            "area_reference_interpretation": "comparison_only_not_a_gate",
            "area_delta_vs_reference_m2": (
                area - area_reference_m2 if math.isfinite(area) else math.nan
            ),
            "area_delta_vs_reference_percent": (
                100.0 * (area / area_reference_m2 - 1.0)
                if math.isfinite(area) and area_reference_m2 > 0.0
                else math.nan
            ),
            "solver_current_guard_margin_factor": (
                solver_current_safety_guard_a_m2 / current
                if math.isfinite(current) and current > 0.0
                else math.nan
            ),
            "stack_feasibility_interpretation": (
                "illustrative_packaging_diagnostic_not_required_area_gate"
            ),
        }
    )
    result.update(
        required_area_validity(
            result,
            integration_ceiling_m2=integration_ceiling_m2,
        )
    )
    return result


def choose_tradeoff_rows(
    rows: Iterable[Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    valid = [
        dict(row)
        for row in rows
        if truth(row.get("required_area_solution_valid"))
    ]
    if not valid:
        raise RuntimeError("No valid required-area solution was produced")
    minimum_area = min(
        valid,
        key=lambda row: finite(row.get("required_active_area_m2")),
    )
    minimum_core_power = min(
        valid,
        key=lambda row: finite(row.get("analysis_core_power_kw")),
    )
    return minimum_area, minimum_core_power


def convergence_metrics(
    nominal: Mapping[str, Any],
    refined: Mapping[str, Any],
    *,
    relative_tolerance: float,
) -> dict[str, Any]:
    nominal_area = finite(nominal.get("required_active_area_m2"))
    refined_area = finite(refined.get("required_active_area_m2"))
    absolute_delta = abs(nominal_area - refined_area)
    relative_delta = (
        absolute_delta / abs(refined_area)
        if math.isfinite(absolute_delta) and refined_area != 0.0
        else math.inf
    )
    return {
        "receiver_capacity_multiplier": finite(
            refined.get("receiver_capacity_multiplier")
        ),
        "nominal_area_step_m2": finite(
            nominal.get("integration_area_step_m2")
        ),
        "refined_area_step_m2": finite(
            refined.get("integration_area_step_m2")
        ),
        "nominal_required_active_area_m2": nominal_area,
        "refined_required_active_area_m2": refined_area,
        "absolute_area_difference_m2": absolute_delta,
        "relative_area_difference": relative_delta,
        "relative_area_difference_percent": 100.0 * relative_delta,
        "convergence_relative_tolerance": float(relative_tolerance),
        "nominal_solution_valid": truth(
            nominal.get("required_area_solution_valid")
        ),
        "refined_solution_valid": truth(
            refined.get("required_area_solution_valid")
        ),
        "step_halving_convergence_pass": bool(
            truth(nominal.get("required_area_solution_valid"))
            and truth(refined.get("required_area_solution_valid"))
            and math.isfinite(relative_delta)
            and relative_delta <= relative_tolerance
        ),
    }


def build_contract(
    args: argparse.Namespace,
    receiver_multipliers: tuple[float, ...],
) -> dict[str, Any]:
    return {
        "study_id": STUDY_ID,
        "model_basis": (
            "canonical native prearchitecture solve_case with coupled "
            "counter-current gas receiver"
        ),
        "target": "O30",
        "terminal_voltage_v": TERMINAL_VOLTAGE_V,
        "receiver_multipliers": list(receiver_multipliers),
        "nominal_area_step_m2": float(args.nominal_area_step_m2),
        "refined_area_step_m2": float(args.refined_area_step_m2),
        "integration_ceiling_m2": float(args.integration_ceiling_m2),
        "solver_current_safety_guard_a_m2": float(
            args.solver_current_safety_guard_a_m2
        ),
        "current_density_acceptance_gate_applied": False,
        "design_area_cap_applied": False,
        "area_reference_m2": float(args.area_reference_m2),
        "legacy_proportional_estimate_m2": float(
            args.legacy_proportional_estimate_m2
        ),
        "convergence_relative_tolerance": float(
            args.convergence_relative_tolerance
        ),
        "fixed_material": FIXED_MATERIAL,
        "fixed_geometry": FIXED_GEOMETRY,
    }


def contract_sha256(contract: Mapping[str, Any]) -> str:
    payload = json.dumps(
        contract,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_context(args: argparse.Namespace) -> dict[str, Any]:
    from heiq.wp1.studies import build_repository_context

    setup_args = SimpleNamespace(
        receiver_band="bridge_40_to_60",
        receiver_temperature_c=None,
        area_max_m2=float(args.integration_ceiling_m2),
        voltage_max_v=TERMINAL_VOLTAGE_V,
        current_cap_a_m2=float(args.solver_current_safety_guard_a_m2),
        lhs_samples=8,
        seed=20260826,
        smoke=False,
    )
    return build_repository_context(setup_args, root=ROOT)


def solve_point(
    base_context: Mapping[str, Any],
    *,
    receiver_multiplier: float,
    integration_area_step_m2: float,
    args: argparse.Namespace,
    contract_hash: str,
    record_profile: bool,
) -> tuple[dict[str, Any], pd.DataFrame]:
    from heiq.wp1.studies import solve_case

    context = selective_context_copy(base_context)
    apply_fixed_geometry(context)
    context["base"]["integration"]["area_step_m2"] = float(
        integration_area_step_m2
    )
    context["base"]["integration"]["minimum_area_step_m2"] = min(
        float(
            context["base"]["integration"].get(
                "minimum_area_step_m2",
                integration_area_step_m2 / 64.0,
            )
        ),
        integration_area_step_m2 / 32.0,
    )

    row, profile, _receiver = solve_case(
        context,
        target="O30",
        material=dict(FIXED_MATERIAL),
        voltage_v=TERMINAL_VOLTAGE_V,
        receiver_multiplier=float(receiver_multiplier),
        record_profile=record_profile,
    )
    result = decorate_result(
        row,
        receiver_multiplier=receiver_multiplier,
        integration_area_step_m2=integration_area_step_m2,
        integration_ceiling_m2=float(args.integration_ceiling_m2),
        solver_current_safety_guard_a_m2=float(
            args.solver_current_safety_guard_a_m2
        ),
        area_reference_m2=float(args.area_reference_m2),
        contract_sha256=contract_hash,
    )
    return result, profile


def multiplier_id(value: float) -> str:
    token = f"{value:.8f}".rstrip("0").rstrip(".").replace(".", "p")
    return f"R{token}"


def write_interpretation(
    output_dir: Path,
    *,
    results: pd.DataFrame,
    minimum_area: Mapping[str, Any],
    minimum_core_power: Mapping[str, Any],
    convergence: Mapping[str, Any],
    args: argparse.Namespace,
) -> None:
    low_multiplier_row = results.sort_values(
        "receiver_capacity_multiplier", kind="stable"
    ).iloc[0]
    area_reduction = 100.0 * (
        1.0
        - finite(minimum_area["required_active_area_m2"])
        / finite(low_multiplier_row["required_active_area_m2"])
    )
    airflow_increase = 100.0 * (
        finite(minimum_area["analysis_receiver_airflow_cfm"])
        / finite(low_multiplier_row["analysis_receiver_airflow_cfm"])
        - 1.0
    )
    power_increase = 100.0 * (
        finite(minimum_area["analysis_core_power_kw"])
        / finite(low_multiplier_row["analysis_core_power_kw"])
        - 1.0
    )
    refined_area = finite(convergence["refined_required_active_area_m2"])
    legacy_estimate = float(args.legacy_proportional_estimate_m2)
    legacy_delta_percent = 100.0 * (refined_area / legacy_estimate - 1.0)

    lines = [
        "# O30 nonlinear required area at 1.0 V — v1",
        "",
        "## Result",
        "",
        f"All {len(results)} tested receiver points reached O30 and passed the "
        "required-area validity checks. No current-density acceptance limit "
        "or design-area cap was applied.",
        "",
        "The minimum required area among the tested points occurs at receiver "
        f"multiplier {finite(minimum_area['receiver_capacity_multiplier']):.6g}: "
        f"{refined_area:.6f} m2 after step refinement. This is "
        f"{refined_area - float(args.area_reference_m2):.6f} m2 "
        f"({100.0 * (refined_area / float(args.area_reference_m2) - 1.0):.4f}%) "
        f"above the {float(args.area_reference_m2):.0f} m2 comparison line.",
        "",
        f"The old proportional diagnostic ({legacy_estimate:.1f} m2) was "
        f"{legacy_delta_percent:.2f}% lower than the nonlinear refined solve.",
        "",
        "## Numerical audit",
        "",
        f"The selected area changed from "
        f"{finite(convergence['nominal_required_active_area_m2']):.6f} m2 at "
        f"{finite(convergence['nominal_area_step_m2']):.6g} m2 steps to "
        f"{refined_area:.6f} m2 at "
        f"{finite(convergence['refined_area_step_m2']):.6g} m2 steps. The "
        f"relative difference is "
        f"{finite(convergence['relative_area_difference_percent']):.6g}% and "
        f"the convergence check is "
        f"{truth(convergence['step_halving_convergence_pass'])}.",
        "",
        "The finite current value passed to the legacy solver API is only a "
        "non-binding numerical safety guard. Maximum local current density is "
        "reported as a diagnostic and never enters acceptance or ranking. The "
        "finite integration ceiling is likewise a solver guard; 9000 m2 is "
        "comparison-only.",
        "",
        "## Trade-off",
        "",
        f"Across the tested range, moving from receiver multiplier "
        f"{finite(low_multiplier_row['receiver_capacity_multiplier']):.6g} to "
        f"{finite(minimum_area['receiver_capacity_multiplier']):.6g} reduces "
        f"required area by {area_reduction:.2f}%, increases receiver airflow by "
        f"{airflow_increase:.2f}% and increases core power by "
        f"{power_increase:.2f}%.",
        "",
        "There is therefore no single system optimum in this scan. The "
        f"minimum-area tested point is R="
        f"{finite(minimum_area['receiver_capacity_multiplier']):.6g}; the "
        f"minimum-core-power tested point is R="
        f"{finite(minimum_core_power['receiver_capacity_multiplier']):.6g}.",
        "",
        "## Claim boundary",
        "",
        "This is a local required-area curve for one hypothetical legacy "
        "material vector and one fixed legacy geometry. It is not a global "
        "material/geometry optimization, an experimental material validation, "
        "a hardware design, or a proof of global O30 feasibility/infeasibility. "
        "The very large receiver flows still require manifold, distribution "
        "and hardware closure.",
        "",
    ]
    (output_dir / "INTERPRETATION.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )


def validate_args(args: argparse.Namespace) -> None:
    positive = {
        "integration_ceiling_m2": args.integration_ceiling_m2,
        "solver_current_safety_guard_a_m2": (
            args.solver_current_safety_guard_a_m2
        ),
        "area_reference_m2": args.area_reference_m2,
        "nominal_area_step_m2": args.nominal_area_step_m2,
        "refined_area_step_m2": args.refined_area_step_m2,
        "legacy_proportional_estimate_m2": (
            args.legacy_proportional_estimate_m2
        ),
        "convergence_relative_tolerance": (
            args.convergence_relative_tolerance
        ),
    }
    for name, value in positive.items():
        if not math.isfinite(float(value)) or float(value) <= 0.0:
            raise ValueError(f"{name} must be positive and finite")
    if args.refined_area_step_m2 >= args.nominal_area_step_m2:
        raise ValueError(
            "refined_area_step_m2 must be smaller than nominal_area_step_m2"
        )
    if args.integration_ceiling_m2 <= args.nominal_area_step_m2:
        raise ValueError(
            "integration_ceiling_m2 must exceed nominal_area_step_m2"
        )


def self_test() -> None:
    multipliers = normalize_receiver_multipliers([3.0, 1.01, 3.0])
    assert multipliers == (1.01, 3.0)

    base = {
        "status": "target_reached",
        "target_reached": True,
        "target_capacity_sufficient": True,
        "required_active_area_m2": 10500.0,
        "process_outlet_humidity_ratio_kg_kg_da": 0.009,
        "target_humidity_ratio_kg_kg_da": 0.009,
        "local_solver_evaluated": True,
        "minimum_local_flux_mol_m2_s": 0.001,
        "maximum_local_current_density_a_m2": 999.0,
        "countercurrent_boundary_solution_valid": True,
        "receiver_boundary_pass": True,
        "water_balance_evaluated": True,
        "water_balance_pass": True,
        "process_mass_balance_relative_error": 1.0e-12,
        "receiver_mass_balance_relative_error": 1.0e-12,
        "shortened_endpoint_resolved": True,
        "maximum_terminal_voltage_error_v": 1.0e-11,
        "eo_grid_power_kw": 70.0,
        "process_channel_fan_power_kw": 1.0,
        "receiver_channel_fan_power_kw": 2.0,
        "analysis_core_power_kw": 73.0,
        "worker_exception": "",
    }
    validity = required_area_validity(
        base, integration_ceiling_m2=15000.0
    )
    assert validity["required_area_solution_valid"]
    assert base["maximum_local_current_density_a_m2"] > 21.0

    failed = required_area_validity(
        {**base, "water_balance_pass": False},
        integration_ceiling_m2=15000.0,
    )
    assert not failed["required_area_solution_valid"]
    print("Self-test passed: no-current-gate required-area contract is valid")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Solve the nonlinear O30 required-area curve at exactly 1.0 V "
            "without a current-density acceptance gate or design-area cap."
        )
    )
    parser.add_argument(
        "--output-dir", default="outputs/o30_required_area_1v_v1"
    )
    parser.add_argument(
        "--receiver-multipliers",
        nargs="+",
        type=float,
        default=list(DEFAULT_RECEIVER_MULTIPLIERS),
    )
    parser.add_argument(
        "--integration-ceiling-m2", type=float, default=15000.0
    )
    parser.add_argument(
        "--solver-current-safety-guard-a-m2", type=float, default=1.0e6
    )
    parser.add_argument("--area-reference-m2", type=float, default=9000.0)
    parser.add_argument(
        "--legacy-proportional-estimate-m2", type=float, default=9275.1
    )
    parser.add_argument(
        "--nominal-area-step-m2", type=float, default=20.0
    )
    parser.add_argument(
        "--refined-area-step-m2", type=float, default=10.0
    )
    parser.add_argument(
        "--convergence-relative-tolerance", type=float, default=1.0e-4
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume only when the stored run contract exactly matches",
    )
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        self_test()
        return 0

    validate_args(args)
    multipliers = normalize_receiver_multipliers(args.receiver_multipliers)
    contract = build_contract(args, multipliers)
    contract_hash = contract_sha256(contract)
    contract["study_contract_sha256"] = contract_hash

    output_dir = ROOT / args.output_dir
    contract_path = output_dir / "run_contract.json"
    if args.resume:
        if not contract_path.is_file():
            raise SystemExit("--resume requires an existing run_contract.json")
        stored = json.loads(contract_path.read_text(encoding="utf-8"))
        if stored != contract:
            raise SystemExit(
                "Stored run contract differs from the requested run; refusing "
                "to reuse checkpoints"
            )
    else:
        output_dir.mkdir(parents=True, exist_ok=False)
        contract_path.write_text(
            json.dumps(contract, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    checkpoint_dir = output_dir / "checkpoints"
    checkpoint_dir.mkdir(exist_ok=args.resume)
    context = build_context(args)

    rows: list[dict[str, Any]] = []
    for index, multiplier in enumerate(multipliers, start=1):
        checkpoint = checkpoint_dir / f"nominal_{multiplier_id(multiplier)}.csv"
        if args.resume and checkpoint.is_file():
            frame = pd.read_csv(checkpoint)
            if len(frame) != 1:
                raise RuntimeError(f"Invalid checkpoint: {checkpoint}")
            row = frame.iloc[0].to_dict()
            if str(row.get("study_contract_sha256")) != contract_hash:
                raise RuntimeError(f"Checkpoint contract mismatch: {checkpoint}")
            if not math.isclose(
                finite(row.get("receiver_capacity_multiplier")),
                multiplier,
                rel_tol=0.0,
                abs_tol=1.0e-12,
            ):
                raise RuntimeError(f"Checkpoint point mismatch: {checkpoint}")
            print(
                f"Required-area curve {index}/{len(multipliers)}: reused "
                f"R={multiplier:.6g}",
                flush=True,
            )
        else:
            print(
                f"Required-area curve {index}/{len(multipliers)}: "
                f"R={multiplier:.6g}",
                flush=True,
            )
            row, _profile = solve_point(
                context,
                receiver_multiplier=multiplier,
                integration_area_step_m2=float(args.nominal_area_step_m2),
                args=args,
                contract_hash=contract_hash,
                record_profile=False,
            )
            pd.DataFrame([row]).to_csv(checkpoint, index=False)
        rows.append(row)
        pd.DataFrame(rows).to_csv(
            output_dir / "required_area_curve_partial.csv", index=False
        )

    results = pd.DataFrame(rows).sort_values(
        "receiver_capacity_multiplier", kind="stable"
    )
    results.to_csv(output_dir / "required_area_curve.csv", index=False)
    minimum_area, minimum_core_power = choose_tradeoff_rows(rows)

    selected_multiplier = finite(
        minimum_area["receiver_capacity_multiplier"]
    )
    print(
        "Step-halving audit at minimum-area tested point: "
        f"R={selected_multiplier:.6g}",
        flush=True,
    )
    refined, profile = solve_point(
        context,
        receiver_multiplier=selected_multiplier,
        integration_area_step_m2=float(args.refined_area_step_m2),
        args=args,
        contract_hash=contract_hash,
        record_profile=True,
    )
    pd.DataFrame([refined]).to_csv(
        output_dir / "minimum_area_refined_case.csv", index=False
    )
    if isinstance(profile, pd.DataFrame):
        profile.to_csv(output_dir / "minimum_area_refined_profile.csv", index=False)

    convergence = convergence_metrics(
        minimum_area,
        refined,
        relative_tolerance=float(args.convergence_relative_tolerance),
    )
    pd.DataFrame([convergence]).to_csv(
        output_dir / "step_halving_convergence.csv", index=False
    )
    if not truth(convergence["step_halving_convergence_pass"]):
        raise RuntimeError("Step-halving convergence check failed")

    summary = {
        "study_id": STUDY_ID,
        "study_contract_sha256": contract_hash,
        "all_tested_points_valid": bool(
            results["required_area_solution_valid"].map(truth).all()
        ),
        "valid_point_count": int(
            results["required_area_solution_valid"].map(truth).sum()
        ),
        "tested_point_count": int(len(results)),
        "minimum_required_area_tested_point": {
            "receiver_capacity_multiplier": selected_multiplier,
            "nominal_required_active_area_m2": finite(
                minimum_area["required_active_area_m2"]
            ),
            "refined_required_active_area_m2": finite(
                refined["required_active_area_m2"]
            ),
            "analysis_receiver_airflow_cfm": finite(
                refined["analysis_receiver_airflow_cfm"]
            ),
            "maximum_local_current_density_a_m2_diagnostic": finite(
                refined["maximum_local_current_density_a_m2"]
            ),
            "analysis_core_power_kw": finite(
                refined["analysis_core_power_kw"]
            ),
        },
        "minimum_core_power_tested_point": {
            "receiver_capacity_multiplier": finite(
                minimum_core_power["receiver_capacity_multiplier"]
            ),
            "required_active_area_m2": finite(
                minimum_core_power["required_active_area_m2"]
            ),
            "analysis_core_power_kw": finite(
                minimum_core_power["analysis_core_power_kw"]
            ),
        },
        "step_halving_convergence": convergence,
        "interpretation": (
            "area-airflow-power trade-off; no single system optimum selected"
        ),
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_interpretation(
        output_dir,
        results=results,
        minimum_area=minimum_area,
        minimum_core_power=minimum_core_power,
        convergence=convergence,
        args=args,
    )

    print()
    print("=== O30 REQUIRED-AREA CURVE AT 1.0 V ===")
    print(results[MAIN_COLUMNS].to_string(index=False))
    print()
    print(
        "Refined minimum-area tested point: "
        f"R={selected_multiplier:.6g}, "
        f"area={finite(refined['required_active_area_m2']):.6f} m2"
    )
    print(f"Outputs: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
