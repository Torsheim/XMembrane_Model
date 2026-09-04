#!/usr/bin/env python3
"""Analyse the direct-EO operating region from v53 gate registers.

The v53 register repeats each physical simulation for every tested voltage
cap.  This module keeps those copies for the cap-specific engineering result,
but removes them before calculating physical parameter sensitivity.  It also
corrects a subtle v54 presentation issue: voltage headroom is evaluated
against the *selected* cap, not against the lowest passing discrete cap.

The primary robust flag is intentionally explicit::

    all v53 physical/architecture gates
    AND the declared v53 hard-area screen
    AND a_process,min >= 0.17
    AND conditional known-electric saving >= 425 kW
    AND V_max <= selected cap - 0.25 V

Current density is an ordinary sampled operating coordinate.  There is no
21 A/m2 acceptance limit in this analysis.

All energy results remain conditional: the inherited ideal-wet receiver sets
water-removal/regeneration power to zero.  The module therefore reports the
receiver SEC budget at break-even and explicit non-zero SEC scenarios rather
than relabelling the result as a closed plant energy balance.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Iterable, Sequence

os.environ.setdefault("MPLCONFIGDIR", "/tmp/heiq-direct-eo-region-mpl")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.patches import Patch, Rectangle
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
HEIQ_ROOT = ROOT.parent

DEFAULT_GLOBAL_REGISTER = (
    HEIQ_ROOT
    / "HeiQ_V2"
    / "outputs"
    / "EO_symmetric_wet_receiver_sink_v53"
    / "joint_material_operating_gate_register.csv"
)
DEFAULT_DENSE_REGISTER = (
    ROOT
    / "outputs"
    / "membrane_operating_region_study_v1"
    / "direct_eo_dense"
    / "joint_material_operating_gate_register.csv"
)
DEFAULT_OUTPUT = (
    ROOT
    / "outputs"
    / "membrane_operating_region_study_v1"
    / "direct_eo_analysis"
)
DEFAULT_MANIFEST = ROOT / "config" / "membrane_operating_region_study_v1.json"
DEFAULT_V53_GENERATOR = (
    HEIQ_ROOT / "HeiQ_V2" / "scripts" / "make_wp1_symmetric_wet_receiver_sink_v53.py"
)
DEFAULT_GLOBAL_ASSUMPTIONS = DEFAULT_GLOBAL_REGISTER.parent / "assumptions_v53.csv"
DEFAULT_DENSE_ASSUMPTIONS = DEFAULT_DENSE_REGISTER.parent / "assumptions_v53.csv"

REQUIRED_ANALYSIS_OUTPUTS = [
    "per_cap_robust_register.csv",
    "physical_sensitivity_register.csv",
    "parameter_level_pass_share.csv",
    "tw_diffusivity_cell_register.csv",
    "tw_diffusivity_3x3_neighborhood.csv",
    "receiver_sec_scenarios.csv",
    "receiver_sec_cap_summary.csv",
    "gate_failure_summary.csv",
    "analysis_assumptions.json",
    "summary_direct_eo_operating_region_v1.md",
    "01_dense_tw_diffusivity_region_by_cap.png",
    "01_dense_tw_diffusivity_region_by_cap.pdf",
    "02_dense_tw_diffusivity_region_by_current.png",
    "02_dense_tw_diffusivity_region_by_current.pdf",
    "03_global_tw_diffusivity_region_by_current.png",
    "03_global_tw_diffusivity_region_by_current.pdf",
    "04_parameter_level_robust_pass_share.png",
    "04_parameter_level_robust_pass_share.pdf",
    "05_dense_receiver_sec_break_even_budget.png",
    "05_dense_receiver_sec_break_even_budget.pdf",
]

EPS = 1.0e-9

NAVY = "#17324D"
TEAL = "#008C8C"
TEAL_DARK = "#005F63"
TEAL_PALE = "#D9F0EF"
ORANGE = "#E58B2A"
RED = "#B94A3D"
GREY = "#D8E0E6"
GREY_DARK = "#8999A6"
SLATE = "#607284"
INK = "#172A3A"
WHITE = "#FFFFFF"

PASS_CMAP = LinearSegmentedColormap.from_list(
    "direct_eo_pass_share", ["#EEF4F4", "#9BD4D1", "#2AA7A2", "#005F63"]
)
SEC_CMAP = LinearSegmentedColormap.from_list(
    "receiver_sec_budget", ["#FFF1DD", "#F2BD73", "#49A9A4", "#005F63"]
)


PHYSICAL_KEY_CANDIDATES = [
    "current_density_a_m2",
    "dry_thickness_um",
    "channel_length_m",
    "channel_height_mm",
    "channel_width_m",
    "receiver_control_activity",
    "transport_number_reference_t_w",
    "eo_drag_scale_vs_pfsa",
    "water_diffusivity_scale_vs_pfsa",
    "ionic_area_resistance_ohm_m2_at_lambda_ref",
    "retention_factor_vs_pfsa_sorption",
]

PARAMETERS: list[tuple[str, str]] = [
    ("transport_number_reference_t_w", "Reference transport number $t_w$"),
    ("water_diffusivity_scale_vs_pfsa", "Water diffusivity / PFSA reference"),
    ("current_density_a_m2", "Current density [A/m²]"),
    ("dry_thickness_um", "Dry thickness [µm]"),
    ("retention_factor_vs_pfsa_sorption", "Water-retention factor / PFSA"),
    ("ionic_area_resistance_ohm_m2_at_lambda_ref", "Ionic ASR at $\\lambda=8$ [Ω m²]"),
]

REQUIRED_COLUMNS = {
    "active_area_m2",
    "cell_voltage_cap_tested_v",
    "cell_voltage_required_max_v",
    "conditional_known_electric_saving_kw",
    "current_density_a_m2",
    "dry_thickness_um",
    "hard_area_cap_pass",
    "process_surface_activity_min",
    "receiver_sink_energy_kw_assumed",
    "receiver_sink_net_kg_h",
    "strict_physical_and_architecture_pass",
    "transport_number_reference_t_w",
    "water_diffusivity_scale_vs_pfsa",
}

BOOLEAN_COLUMNS = {
    "strict_physical_and_architecture_pass",
    "hard_area_cap_pass",
    "hard_area_cap_enabled",
    "selected_voltage_cap_pass",
    "conditional_positive_saving_pass",
    "target_reached_pass",
    "water_retention_pass",
    "pressure_drop_pass",
    "packaging_pass",
    "gas_surface_activity_pass",
    "receiver_surface_activity_pass",
    "process_surface_full_module_pass",
    "v50_architecture_pass_at_screening_cap",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--global-register", type=Path, default=DEFAULT_GLOBAL_REGISTER)
    parser.add_argument("--dense-register", type=Path, default=DEFAULT_DENSE_REGISTER)
    parser.add_argument("--v53-generator", type=Path, default=DEFAULT_V53_GENERATOR)
    parser.add_argument(
        "--global-assumptions-v53", type=Path, default=DEFAULT_GLOBAL_ASSUMPTIONS
    )
    parser.add_argument(
        "--dense-assumptions-v53", type=Path, default=DEFAULT_DENSE_ASSUMPTIONS
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--require-empty-out-dir",
        action="store_true",
        help="Fail rather than mix a fresh candidate analysis with pre-existing files.",
    )
    parser.add_argument("--process-activity-min", type=float, default=0.17)
    parser.add_argument("--conditional-saving-min-kw", type=float, default=425.0)
    parser.add_argument("--voltage-headroom-v", type=float, default=0.25)
    parser.add_argument("--primary-cap-v", type=float, default=5.0)
    parser.add_argument("--primary-current-density-a-m2", type=float, default=50.0)
    parser.add_argument(
        "--receiver-sec-values-kwh-kg",
        type=float,
        nargs="+",
        default=[0.0, 0.05, 0.10, 0.15, 0.20],
    )
    return parser.parse_args()


def load_manifest(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise FileNotFoundError(f"Could not find central study manifest: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "direct_eo" not in payload or "current_density_policy" not in payload:
        raise ValueError(f"{path} is not a membrane-operating-region v1 manifest")
    return payload


def validate_manifest_dense_axes(frame: pd.DataFrame, manifest: dict[str, object]) -> None:
    """Ensure the local register is the exact grid declared by the shared study manifest."""
    direct = manifest["direct_eo"]
    if not isinstance(direct, dict) or not isinstance(direct.get("dense_axes"), dict):
        raise ValueError("Manifest lacks direct_eo.dense_axes")
    axes = direct["dense_axes"]
    for column, expected_values in axes.items():
        if column not in frame.columns:
            raise ValueError(f"Dense register lacks manifest axis {column}")
        expected = np.asarray(sorted(map(float, expected_values)), dtype=float)
        actual = np.asarray(sorted(frame[column].dropna().unique()), dtype=float)
        if expected.shape != actual.shape or not np.allclose(expected, actual, rtol=0.0, atol=EPS):
            raise ValueError(
                f"Dense register axis {column} differs from the central manifest: "
                f"expected {expected.tolist()}, found {actual.tolist()}"
            )
    policy = manifest["current_density_policy"]
    if not isinstance(policy, dict) or policy.get("engineering_current_density_limit_a_m2") is not None:
        raise ValueError("Central manifest unexpectedly defines a current-density acceptance limit")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def provenance_record(path: Path) -> dict[str, object]:
    resolved = path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"Required provenance file is missing: {resolved}")
    return {
        "path": str(resolved),
        "sha256": sha256_file(resolved),
        "size_bytes": resolved.stat().st_size,
    }


def source_count_audit(
    source: str,
    source_frame: pd.DataFrame,
    source_physical: pd.DataFrame,
    input_path: Path,
    manifest: dict[str, object],
) -> dict[str, object]:
    raw_input_rows = len(pd.read_csv(input_path, usecols=["cell_voltage_cap_tested_v"]))
    caps = sorted(source_frame["cell_voltage_cap_tested_v"].unique())
    keys = physical_key_columns(source_frame)
    copy_counts = source_frame.groupby(keys, dropna=False).size()
    complete_cap_copies = bool(
        len(caps) > 0
        and copy_counts.eq(len(caps)).all()
        and raw_input_rows % len(caps) == 0
    )
    structural_expected_physical = raw_input_rows // len(caps) if complete_cap_copies else None

    manifest_expected_physical: int | None = None
    manifest_expected_rows: int | None = None
    if source == "dense_local":
        direct = manifest["direct_eo"]
        axes = direct["dense_axes"]
        cap_values = axes["cell_voltage_cap_tested_v"]
        physical_lengths = [len(values) for name, values in axes.items() if name != "cell_voltage_cap_tested_v"]
        manifest_expected_physical = int(np.prod(physical_lengths, dtype=np.int64))
        manifest_expected_rows = manifest_expected_physical * len(cap_values)

    expected_physical = (
        manifest_expected_physical
        if manifest_expected_physical is not None
        else structural_expected_physical
    )
    expected_rows = manifest_expected_rows if manifest_expected_rows is not None else raw_input_rows
    return {
        "input_csv_rows": raw_input_rows,
        "expected_loaded_rows": expected_rows,
        "observed_loaded_rows": len(source_frame),
        "voltage_caps": list(map(float, caps)),
        "cap_copy_count_per_physical_coordinate": len(caps),
        "complete_cap_copy_cartesian": complete_cap_copies,
        "structural_expected_physical_coordinates": structural_expected_physical,
        "manifest_expected_physical_coordinates": manifest_expected_physical,
        "expected_physical_coordinates": expected_physical,
        "observed_physical_coordinates": len(source_physical),
        "row_count_match": bool(expected_rows == len(source_frame) == raw_input_rows),
        "physical_count_match": bool(
            expected_physical is not None and expected_physical == len(source_physical)
        ),
    }


def build_audit(
    args: argparse.Namespace,
    manifest: dict[str, object],
    cap_register: pd.DataFrame,
    physical: pd.DataFrame,
    output_row_counts: dict[str, int],
) -> dict[str, object]:
    script_path = Path(__file__).resolve()
    provenance_paths = {
        "script": script_path,
        "manifest": args.manifest,
        "v53_generator": args.v53_generator,
        "global_register": args.global_register,
        "dense_register": args.dense_register,
        "global_assumptions_v53": args.global_assumptions_v53,
        "dense_assumptions_v53": args.dense_assumptions_v53,
    }
    provenance = {name: provenance_record(path) for name, path in provenance_paths.items()}

    counts: dict[str, object] = {}
    for source, input_path in (
        ("global_v53", args.global_register),
        ("dense_local", args.dense_register),
    ):
        source_frame = cap_register.loc[cap_register["source_study"].eq(source)]
        source_physical = physical.loc[physical["source_study"].eq(source)]
        counts[source] = source_count_audit(
            source, source_frame, source_physical, input_path, manifest
        )
    counts["combined"] = {
        "expected_loaded_rows": sum(
            int(counts[source]["expected_loaded_rows"])
            for source in ("global_v53", "dense_local")
        ),
        "observed_loaded_rows": len(cap_register),
        "expected_physical_coordinates": sum(
            int(counts[source]["expected_physical_coordinates"])
            for source in ("global_v53", "dense_local")
        ),
        "observed_physical_coordinates": len(physical),
    }
    counts["combined"]["row_count_match"] = bool(
        counts["combined"]["expected_loaded_rows"] == counts["combined"]["observed_loaded_rows"]
    )
    counts["combined"]["physical_count_match"] = bool(
        counts["combined"]["expected_physical_coordinates"]
        == counts["combined"]["observed_physical_coordinates"]
    )

    direct_policy = manifest["direct_eo"]
    current_policy = manifest["current_density_policy"]
    closure_policy = manifest["system_closure_policy"]
    effective_parameters = {
        "process_activity_min": float(args.process_activity_min),
        "conditional_saving_min_kw": float(args.conditional_saving_min_kw),
        "selected_cap_voltage_headroom_v": float(args.voltage_headroom_v),
        "primary_cap_v": float(args.primary_cap_v),
        "primary_current_density_a_m2": float(args.primary_current_density_a_m2),
        "receiver_sec_values_kwh_kg": list(map(float, args.receiver_sec_values_kwh_kg)),
    }
    threshold_matches_manifest = bool(
        math.isclose(
            effective_parameters["process_activity_min"],
            float(direct_policy["robust_process_surface_activity_min"]),
            abs_tol=EPS,
        )
        and math.isclose(
            effective_parameters["conditional_saving_min_kw"],
            float(direct_policy["robust_minimum_conditional_saving_kw"]),
            abs_tol=EPS,
        )
        and math.isclose(
            effective_parameters["selected_cap_voltage_headroom_v"],
            float(direct_policy["robust_voltage_headroom_v"]),
            abs_tol=EPS,
        )
    )
    no_current_limit = bool(
        current_policy.get("engineering_current_density_limit_a_m2") is None
        and current_policy.get("current_density_is_sampling_or_control_axis") is True
    )
    system_unknown = bool(
        closure_policy.get("missing_receiver_energy_status") == "UNKNOWN"
        and closure_policy.get("full_system_claim_allowed") is False
        and closure_policy.get("conditional_saving_is_not_system_saving") is True
    )
    receiver_zero = bool(
        np.allclose(
            cap_register["receiver_sink_energy_kw_assumed"].to_numpy(dtype=float),
            0.0,
            rtol=0.0,
            atol=EPS,
        )
    )

    output_records: list[dict[str, object]] = []
    missing_outputs: list[str] = []
    for relative in REQUIRED_ANALYSIS_OUTPUTS:
        path = args.out_dir / relative
        if not path.is_file():
            missing_outputs.append(relative)
            continue
        record: dict[str, object] = {
            "relative_path": relative,
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
        if relative in output_row_counts:
            record["row_count"] = int(output_row_counts[relative])
        output_records.append(record)

    checks = [
        {
            "check": "thresholds_match_manifest",
            "status": "PASS" if threshold_matches_manifest else "FAIL",
        },
        {
            "check": "no_current_density_acceptance_limit",
            "status": "PASS" if no_current_limit else "FAIL",
        },
        {
            "check": "system_energy_status_unknown",
            "status": "PASS" if system_unknown else "FAIL",
        },
        {
            "check": "receiver_energy_is_explicit_zero_boundary",
            "status": "PASS" if receiver_zero else "FAIL",
        },
        {
            "check": "all_source_row_counts_match",
            "status": "PASS"
            if all(bool(counts[source]["row_count_match"]) for source in counts)
            else "FAIL",
        },
        {
            "check": "all_source_physical_counts_match",
            "status": "PASS"
            if all(bool(counts[source]["physical_count_match"]) for source in counts)
            else "FAIL",
        },
        {
            "check": "all_required_outputs_hashed",
            "status": "PASS" if not missing_outputs else "FAIL",
            "missing": missing_outputs,
        },
    ]
    status = "PASS" if all(item["status"] == "PASS" for item in checks) else "FAIL"
    audit = {
        "schema_version": 1,
        "status": status,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "study_id": manifest.get("study_id"),
        "provenance": provenance,
        "effective_parameters": effective_parameters,
        "expected_and_observed_counts": counts,
        "policies": {
            "engineering_current_density_limit_a_m2": None,
            "current_density_is_sampling_or_control_axis": True,
            "system_energy_status": "UNKNOWN",
            "full_system_claim_allowed": False,
            "receiver_sink_energy_modelled": False,
        },
        "checks": checks,
        "required_outputs": output_records,
    }
    (args.out_dir / "audit.json").write_text(
        json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if status != "PASS":
        raise RuntimeError(f"Direct-EO audit failed; inspect {args.out_dir / 'audit.json'}")
    return audit


def verify_audit_for_reuse(
    audit_path: Path,
    *,
    script_path: Path,
    manifest_path: Path,
    v53_generator_path: Path,
    global_register_path: Path,
    dense_register_path: Path,
    global_assumptions_v53_path: Path,
    dense_assumptions_v53_path: Path,
    process_activity_min: float,
    conditional_saving_min_kw: float,
    selected_cap_voltage_headroom_v: float,
    primary_cap_v: float,
    primary_current_density_a_m2: float,
    receiver_sec_values_kwh_kg: Sequence[float],
    required_output_names: Sequence[str],
) -> dict[str, object]:
    """Verify a reusable result without consulting module defaults."""
    issues: list[str] = []
    if not audit_path.is_file():
        return {"status": "FAIL", "issues": [f"missing audit: {audit_path}"]}
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    if audit.get("status") != "PASS":
        issues.append("stored audit status is not PASS")

    expected_paths = {
        "script": script_path,
        "manifest": manifest_path,
        "v53_generator": v53_generator_path,
        "global_register": global_register_path,
        "dense_register": dense_register_path,
        "global_assumptions_v53": global_assumptions_v53_path,
        "dense_assumptions_v53": dense_assumptions_v53_path,
    }
    stored_provenance = audit.get("provenance", {})
    for name, path in expected_paths.items():
        resolved = path.resolve()
        stored = stored_provenance.get(name, {})
        if not resolved.is_file():
            issues.append(f"live provenance file missing: {name}")
            continue
        if stored.get("path") != str(resolved):
            issues.append(f"provenance path mismatch: {name}")
        if stored.get("sha256") != sha256_file(resolved):
            issues.append(f"provenance hash mismatch: {name}")

    expected_parameters = {
        "process_activity_min": float(process_activity_min),
        "conditional_saving_min_kw": float(conditional_saving_min_kw),
        "selected_cap_voltage_headroom_v": float(selected_cap_voltage_headroom_v),
        "primary_cap_v": float(primary_cap_v),
        "primary_current_density_a_m2": float(primary_current_density_a_m2),
        "receiver_sec_values_kwh_kg": list(map(float, receiver_sec_values_kwh_kg)),
    }
    if audit.get("effective_parameters") != expected_parameters:
        issues.append("effective analysis parameters do not match")

    policies = audit.get("policies", {})
    if policies.get("engineering_current_density_limit_a_m2") is not None:
        issues.append("audit contains a current-density acceptance limit")
    if policies.get("system_energy_status") != "UNKNOWN":
        issues.append("audit does not retain UNKNOWN system-energy status")
    if policies.get("full_system_claim_allowed") is not False:
        issues.append("audit permits a full-system claim")

    output_dir = audit_path.resolve().parent
    stored_outputs = {
        item.get("relative_path"): item for item in audit.get("required_outputs", [])
    }
    if set(stored_outputs) != set(required_output_names):
        issues.append("stored required-output set differs from caller's explicit set")
    for relative in required_output_names:
        live = output_dir / relative
        stored = stored_outputs.get(relative, {})
        if not live.is_file():
            issues.append(f"required output missing: {relative}")
        elif stored.get("sha256") != sha256_file(live):
            issues.append(f"required output hash mismatch: {relative}")

    return {"status": "PASS" if not issues else "FAIL", "issues": issues}


def style() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 9.0,
            "axes.titlesize": 10.8,
            "axes.titleweight": "bold",
            "axes.labelsize": 9.2,
            "axes.edgecolor": "#A7B5C2",
            "axes.labelcolor": INK,
            "xtick.color": "#465B6B",
            "ytick.color": "#465B6B",
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "figure.facecolor": WHITE,
            "savefig.facecolor": WHITE,
        }
    )


def as_bool(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series.fillna(False)
    if pd.api.types.is_numeric_dtype(series):
        return series.fillna(0).astype(float).ne(0.0)
    return series.astype(str).str.strip().str.lower().isin({"true", "1", "yes", "y"})


def require_columns(frame: pd.DataFrame, source: Path) -> None:
    missing = sorted(REQUIRED_COLUMNS - set(frame.columns))
    if missing:
        raise ValueError(f"{source} lacks required columns: {', '.join(missing)}")


def load_register(path: Path, source_study: str) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(f"Could not find v53 register: {path}")
    frame = pd.read_csv(path, low_memory=False)
    require_columns(frame, path)
    frame["source_study"] = source_study
    for column in BOOLEAN_COLUMNS & set(frame.columns):
        frame[column] = as_bool(frame[column])
    numeric = {
        column
        for column in (
            set(PHYSICAL_KEY_CANDIDATES)
            | REQUIRED_COLUMNS
            | {
                "baseline_hvac_kw",
                "downstream_hvac_kw",
                "eo_grid_power_kw",
                "fan_process_kw",
                "fan_receiver_kw",
                "module_fan_kw",
                "known_electric_total_kw",
                "water_transferred_kg_h",
            }
        )
        if column in frame.columns and column not in BOOLEAN_COLUMNS
    }
    for column in numeric:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    essential = [
        "cell_voltage_cap_tested_v",
        "cell_voltage_required_max_v",
        "conditional_known_electric_saving_kw",
        "process_surface_activity_min",
        "receiver_sink_net_kg_h",
        "transport_number_reference_t_w",
        "water_diffusivity_scale_vs_pfsa",
        "current_density_a_m2",
    ]
    frame = frame.dropna(subset=essential).copy()
    if frame.empty:
        raise ValueError(f"No numerically valid rows remain in {path}")
    return frame


def physical_key_columns(frame: pd.DataFrame) -> list[str]:
    keys = [column for column in PHYSICAL_KEY_CANDIDATES if column in frame.columns]
    if not keys:
        raise ValueError("No physical coordinate columns found")
    return keys


def deduplicate_cap_copies(frame: pd.DataFrame) -> pd.DataFrame:
    """Return one row per physical model coordinate, independent of cap copies."""
    keys = ["source_study", *physical_key_columns(frame)]
    ordered = frame.sort_values([*keys, "cell_voltage_cap_tested_v"], kind="mergesort")

    # These outputs must not change when only the post-screen voltage cap changes.
    invariant = [
        column
        for column in (
            "active_area_m2",
            "cell_voltage_required_max_v",
            "conditional_known_electric_saving_kw",
            "process_surface_activity_min",
            "receiver_sink_net_kg_h",
            "strict_physical_and_architecture_pass",
        )
        if column in ordered.columns
    ]
    for column in invariant:
        spread = ordered.groupby(keys, dropna=False)[column].nunique(dropna=False)
        if int(spread.max()) > 1:
            raise ValueError(
                f"Cap copies disagree on cap-invariant column {column}; "
                "the register cannot be safely deduplicated."
            )

    physical = ordered.drop_duplicates(keys, keep="first").copy()
    cap_summary = (
        ordered.groupby(keys, dropna=False)["cell_voltage_cap_tested_v"]
        .agg(
            cap_copy_count="size",
            available_voltage_caps_v=lambda values: ";".join(
                f"{float(value):g}" for value in sorted(set(values))
            ),
        )
        .reset_index()
    )
    physical = physical.drop(
        columns=[
            column
            for column in (
                "cell_voltage_cap_tested_v",
                "cell_voltage_headroom_v",
                "selected_voltage_cap_pass",
                "v52_cap_and_area_only_pass",
                "strict_v53_pass",
                "v53_failed_hard_gates",
            )
            if column in physical.columns
        ]
    )
    return physical.merge(cap_summary, on=keys, how="left", validate="one_to_one")


def robust_failure_reason(row: pd.Series) -> str:
    failures: list[str] = []
    if not bool(row["strict_physical_and_architecture_pass"]):
        failures.append("physical/architecture gate")
    if not bool(row["hard_area_cap_pass"]):
        failures.append("declared hard-area screen")
    if not bool(row["process_activity_robust_pass"]):
        failures.append("process activity")
    if not bool(row["conditional_saving_robust_pass"]):
        failures.append("conditional saving")
    if not bool(row["selected_cap_headroom_robust_pass"]):
        failures.append("selected-cap voltage headroom")
    return "; ".join(failures) if failures else "passes per-cap robust screen"


def add_cap_specific_robust_flags(
    frame: pd.DataFrame,
    process_activity_min: float,
    conditional_saving_min_kw: float,
    voltage_headroom_v: float,
) -> pd.DataFrame:
    result = frame.copy()
    result["selected_cap_voltage_headroom_v"] = (
        result["cell_voltage_cap_tested_v"] - result["cell_voltage_required_max_v"]
    )
    result["process_activity_robust_pass"] = (
        result["process_surface_activity_min"] >= process_activity_min - EPS
    )
    result["conditional_saving_robust_pass"] = (
        result["conditional_known_electric_saving_kw"] >= conditional_saving_min_kw - EPS
    )
    result["selected_cap_headroom_robust_pass"] = (
        result["selected_cap_voltage_headroom_v"] >= voltage_headroom_v - EPS
    )
    result["per_cap_robust_pass_without_area_screen"] = (
        result["strict_physical_and_architecture_pass"]
        & result["process_activity_robust_pass"]
        & result["conditional_saving_robust_pass"]
        & result["selected_cap_headroom_robust_pass"]
    )
    result["per_cap_robust_pass"] = (
        result["per_cap_robust_pass_without_area_screen"] & result["hard_area_cap_pass"]
    )
    result["per_cap_robust_failure_reason"] = result.apply(robust_failure_reason, axis=1)
    return result


def add_receiver_sec_budget(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    water = result["receiver_sink_net_kg_h"].to_numpy(dtype=float)
    saving = result["conditional_known_electric_saving_kw"].to_numpy(dtype=float)
    valid = water > EPS
    signed = np.full(len(result), np.nan)
    signed[valid] = saving[valid] / water[valid]
    result["receiver_sec_break_even_signed_kwh_kg"] = signed
    result["receiver_sec_budget_kwh_kg"] = np.where(valid, np.maximum(saving, 0.0) / water, np.nan)
    return result


def receiver_sec_scenarios(frame: pd.DataFrame, sec_values: Sequence[float]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    identity = [
        column
        for column in (
            "source_study",
            "current_density_a_m2",
            "transport_number_reference_t_w",
            "water_diffusivity_scale_vs_pfsa",
            "dry_thickness_um",
            "retention_factor_vs_pfsa_sorption",
            "ionic_area_resistance_ohm_m2_at_lambda_ref",
            "active_area_m2",
            "conditional_known_electric_saving_kw",
            "receiver_sink_net_kg_h",
            "receiver_sec_break_even_signed_kwh_kg",
            "receiver_sec_budget_kwh_kg",
        )
        if column in frame.columns
    ]
    for sec in sorted(set(float(value) for value in sec_values)):
        scenario = frame[identity].copy()
        scenario["receiver_sec_assumed_kwh_kg"] = sec
        scenario["receiver_power_at_sec_kw"] = sec * scenario["receiver_sink_net_kg_h"]
        scenario["conditional_saving_after_receiver_sec_kw"] = (
            scenario["conditional_known_electric_saving_kw"] - scenario["receiver_power_at_sec_kw"]
        )
        scenario["positive_after_receiver_sec"] = (
            scenario["conditional_saving_after_receiver_sec_kw"] >= -EPS
        )
        frames.append(scenario)
    return pd.concat(frames, ignore_index=True)


def receiver_sec_cap_summary(
    cap_register: pd.DataFrame, sec_values: Sequence[float]
) -> pd.DataFrame:
    """Summarise how non-zero receiver SEC erodes each cap's robust set."""
    rows: list[dict[str, object]] = []
    for (source, cap), group in cap_register.groupby(
        ["source_study", "cell_voltage_cap_tested_v"], sort=True
    ):
        robust = group.loc[group["per_cap_robust_pass"]].copy()
        for sec in sorted(set(float(value) for value in sec_values)):
            residual = (
                robust["conditional_known_electric_saving_kw"]
                - sec * robust["receiver_sink_net_kg_h"]
            )
            positive = residual >= -EPS
            rows.append(
                {
                    "source_study": source,
                    "cell_voltage_cap_tested_v": float(cap),
                    "receiver_sec_assumed_kwh_kg": sec,
                    "robust_coordinates_before_receiver_energy": len(robust),
                    "positive_coordinates_after_receiver_energy": int(positive.sum()),
                    "positive_share_of_robust_coordinates": (
                        float(positive.mean()) if len(robust) else math.nan
                    ),
                    "minimum_residual_saving_kw": float(residual.min()) if len(robust) else math.nan,
                    "median_residual_saving_kw": float(residual.median()) if len(robust) else math.nan,
                    "maximum_residual_saving_kw": float(residual.max()) if len(robust) else math.nan,
                }
            )
    return pd.DataFrame(rows)


def parameter_level_pass_share(
    physical: pd.DataFrame, cap_register: pd.DataFrame
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for source, source_physical in physical.groupby("source_study", sort=True):
        for parameter, label in PARAMETERS:
            if parameter not in source_physical.columns:
                continue
            for value, group in source_physical.groupby(parameter, dropna=False, sort=True):
                physical_pass = group["strict_physical_and_architecture_pass"].astype(bool)
                rows.append(
                    {
                        "source_study": source,
                        "scope": "physical_deduplicated",
                        "cell_voltage_cap_tested_v": np.nan,
                        "parameter": parameter,
                        "parameter_label": label,
                        "parameter_value": value,
                        "evaluated_coordinates": len(group),
                        "passing_coordinates": int(physical_pass.sum()),
                        "pass_fraction": float(physical_pass.mean()),
                        "pass_definition": "all cap-invariant v53 physical/architecture gates",
                    }
                )

    for (source, cap), source_cap in cap_register.groupby(
        ["source_study", "cell_voltage_cap_tested_v"], sort=True
    ):
        for parameter, label in PARAMETERS:
            if parameter not in source_cap.columns:
                continue
            for value, group in source_cap.groupby(parameter, dropna=False, sort=True):
                passed = group["per_cap_robust_pass"].astype(bool)
                rows.append(
                    {
                        "source_study": source,
                        "scope": "cap_specific_robust",
                        "cell_voltage_cap_tested_v": float(cap),
                        "parameter": parameter,
                        "parameter_label": label,
                        "parameter_value": value,
                        "evaluated_coordinates": len(group),
                        "passing_coordinates": int(passed.sum()),
                        "pass_fraction": float(passed.mean()),
                        "pass_definition": (
                            "physical/architecture + declared hard-area screen + "
                            "a_process>=0.17 + saving>=425 kW + selected-cap headroom>=0.25 V"
                        ),
                    }
                )
    return pd.DataFrame(rows)


def _robust_metric(group: pd.DataFrame, column: str, operation: str) -> float:
    robust = group.loc[group["per_cap_robust_pass"]]
    if robust.empty:
        return math.nan
    values = robust[column].astype(float)
    if operation == "min":
        return float(values.min())
    if operation == "max":
        return float(values.max())
    if operation == "median":
        return float(values.median())
    raise ValueError(operation)


def tw_diffusivity_cells(cap_register: pd.DataFrame) -> pd.DataFrame:
    keys = [
        "source_study",
        "cell_voltage_cap_tested_v",
        "current_density_a_m2",
        "transport_number_reference_t_w",
        "water_diffusivity_scale_vs_pfsa",
    ]
    rows: list[dict[str, object]] = []
    for key, group in cap_register.groupby(keys, sort=True, dropna=False):
        source, cap, current, tw, diffusivity = key
        passed = group["per_cap_robust_pass"].astype(bool)
        rows.append(
            {
                "source_study": source,
                "cell_voltage_cap_tested_v": float(cap),
                "current_density_a_m2": float(current),
                "transport_number_reference_t_w": float(tw),
                "water_diffusivity_scale_vs_pfsa": float(diffusivity),
                "evaluated_coordinates": len(group),
                "robust_passing_coordinates": int(passed.sum()),
                "robust_pass_fraction": float(passed.mean()),
                "any_robust_pass": bool(passed.any()),
                "all_coordinates_robust_pass": bool(passed.all()),
                "physical_gate_pass_fraction": float(
                    group["strict_physical_and_architecture_pass"].astype(bool).mean()
                ),
                "minimum_robust_active_area_m2": _robust_metric(group, "active_area_m2", "min"),
                "best_robust_conditional_saving_kw": _robust_metric(
                    group, "conditional_known_electric_saving_kw", "max"
                ),
                "median_robust_receiver_sec_budget_kwh_kg": _robust_metric(
                    group, "receiver_sec_budget_kwh_kg", "median"
                ),
                "minimum_process_activity": float(group["process_surface_activity_min"].min()),
                "maximum_required_voltage_v": float(group["cell_voltage_required_max_v"].max()),
            }
        )
    return pd.DataFrame(rows)


def build_3x3_neighborhood(cells: pd.DataFrame) -> pd.DataFrame:
    """Calculate index-adjacent 3x3 neighbourhoods in sampled t_w x D space."""
    rows: list[dict[str, object]] = []
    group_keys = ["source_study", "cell_voltage_cap_tested_v", "current_density_a_m2"]
    for key, group in cells.groupby(group_keys, sort=True):
        source, cap, current = key
        tw_values = sorted(group["transport_number_reference_t_w"].unique())
        d_values = sorted(group["water_diffusivity_scale_vs_pfsa"].unique())
        indexed = group.set_index(
            ["transport_number_reference_t_w", "water_diffusivity_scale_vs_pfsa"]
        )
        for tw_index, tw in enumerate(tw_values):
            for d_index, diffusivity in enumerate(d_values):
                tw_neighbours = tw_values[max(0, tw_index - 1) : min(len(tw_values), tw_index + 2)]
                d_neighbours = d_values[max(0, d_index - 1) : min(len(d_values), d_index + 2)]
                coordinates = [
                    (tw_neighbor, d_neighbor)
                    for tw_neighbor in tw_neighbours
                    for d_neighbor in d_neighbours
                    if (tw_neighbor, d_neighbor) in indexed.index
                ]
                neighbourhood = indexed.loc[coordinates].reset_index()
                full = len(coordinates) == 9
                any_pass_cells = int(neighbourhood["any_robust_pass"].astype(bool).sum())
                evaluated = int(neighbourhood["evaluated_coordinates"].sum())
                passing = int(neighbourhood["robust_passing_coordinates"].sum())
                rows.append(
                    {
                        "source_study": source,
                        "cell_voltage_cap_tested_v": float(cap),
                        "current_density_a_m2": float(current),
                        "transport_number_reference_t_w": float(tw),
                        "water_diffusivity_scale_vs_pfsa": float(diffusivity),
                        "neighbour_cell_count": len(coordinates),
                        "full_3x3_available": full,
                        "neighbour_cells_with_any_robust_pass": any_pass_cells,
                        "neighbour_cell_any_pass_fraction": any_pass_cells / len(coordinates),
                        "neighbour_evaluated_coordinates": evaluated,
                        "neighbour_robust_passing_coordinates": passing,
                        "neighbour_coordinate_pass_fraction": passing / evaluated if evaluated else math.nan,
                        "all_3x3_cells_have_robust_pass": bool(full and any_pass_cells == 9),
                        "all_3x3_coordinates_robust_pass": bool(full and passing == evaluated),
                    }
                )
    return pd.DataFrame(rows)


def gate_failure_summary(cap_register: pd.DataFrame) -> pd.DataFrame:
    gate_columns = [
        ("strict_physical_and_architecture_pass", "physical/architecture"),
        ("hard_area_cap_pass", "declared hard-area screen"),
        ("process_activity_robust_pass", "process activity >= threshold"),
        ("conditional_saving_robust_pass", "conditional saving >= threshold"),
        ("selected_cap_headroom_robust_pass", "selected-cap voltage headroom"),
        ("per_cap_robust_pass", "all robust gates"),
    ]
    rows: list[dict[str, object]] = []
    for (source, cap), group in cap_register.groupby(
        ["source_study", "cell_voltage_cap_tested_v"], sort=True
    ):
        for column, label in gate_columns:
            passed = group[column].astype(bool)
            rows.append(
                {
                    "source_study": source,
                    "cell_voltage_cap_tested_v": float(cap),
                    "gate": column,
                    "gate_label": label,
                    "evaluated_coordinates": len(group),
                    "passing_coordinates": int(passed.sum()),
                    "failing_coordinates": int((~passed).sum()),
                    "pass_fraction": float(passed.mean()),
                }
            )
    return pd.DataFrame(rows)


def finish(fig: plt.Figure, output_dir: Path, stem: str) -> None:
    fig.savefig(output_dir / f"{stem}.png", dpi=240, bbox_inches="tight")
    fig.savefig(output_dir / f"{stem}.pdf", bbox_inches="tight")
    plt.close(fig)


def _axis_value_label(value: float, parameter: str) -> str:
    if parameter in {
        "water_diffusivity_scale_vs_pfsa",
        "ionic_area_resistance_ohm_m2_at_lambda_ref",
    }:
        return f"{float(value):.3g}"
    return f"{float(value):g}"


def draw_heatmap(
    axis: plt.Axes,
    data: pd.DataFrame,
    value_column: str,
    *,
    cmap: matplotlib.colors.Colormap,
    norm: Normalize,
    title: str,
    neighbourhood: pd.DataFrame | None = None,
    show_values: bool = False,
    value_format: str = ".0%",
) -> None:
    tw_values = sorted(data["transport_number_reference_t_w"].unique())
    d_values = sorted(data["water_diffusivity_scale_vs_pfsa"].unique())
    lookup = data.set_index(
        ["transport_number_reference_t_w", "water_diffusivity_scale_vs_pfsa"]
    )
    stable: set[tuple[float, float]] = set()
    if neighbourhood is not None and not neighbourhood.empty:
        stable = set(
            neighbourhood.loc[
                neighbourhood["all_3x3_cells_have_robust_pass"],
                ["transport_number_reference_t_w", "water_diffusivity_scale_vs_pfsa"],
            ].itertuples(index=False, name=None)
        )
    for y, diffusivity in enumerate(d_values):
        for x, tw in enumerate(tw_values):
            if (tw, diffusivity) not in lookup.index:
                face = GREY
                value = math.nan
            else:
                row = lookup.loc[(tw, diffusivity)]
                if isinstance(row, pd.DataFrame):
                    row = row.iloc[0]
                value = float(row[value_column])
                face = cmap(norm(value)) if math.isfinite(value) else GREY
            edge = NAVY if (tw, diffusivity) in stable else WHITE
            width = 2.1 if (tw, diffusivity) in stable else 0.8
            axis.add_patch(
                Rectangle((x - 0.5, y - 0.5), 1.0, 1.0, facecolor=face, edgecolor=edge, lw=width)
            )
            if show_values and math.isfinite(value):
                rgba = matplotlib.colors.to_rgba(face)
                luminance = 0.2126 * rgba[0] + 0.7152 * rgba[1] + 0.0722 * rgba[2]
                axis.text(
                    x,
                    y,
                    format(value, value_format),
                    ha="center",
                    va="center",
                    fontsize=6.3,
                    color=WHITE if luminance < 0.52 else INK,
                )
    axis.set_xlim(-0.5, len(tw_values) - 0.5)
    axis.set_ylim(len(d_values) - 0.5, -0.5)
    axis.set_xticks(range(len(tw_values)), [_axis_value_label(value, "tw") for value in tw_values])
    axis.set_yticks(
        range(len(d_values)),
        [_axis_value_label(value, "water_diffusivity_scale_vs_pfsa") for value in d_values],
    )
    axis.tick_params(length=0, labelsize=7.2)
    axis.set_xlabel(r"Reference transport number $t_w$")
    axis.set_ylabel("Water-diffusivity scale / PFSA")
    axis.set_title(title, loc="left", color=NAVY)
    for spine in axis.spines.values():
        spine.set_visible(False)


def plot_dense_by_cap(
    cells: pd.DataFrame,
    neighbourhood: pd.DataFrame,
    output_dir: Path,
    primary_current: float,
) -> None:
    selected = cells.loc[
        cells["source_study"].eq("dense_local")
        & np.isclose(cells["current_density_a_m2"], primary_current, atol=EPS)
    ]
    if selected.empty:
        return
    caps = sorted(selected["cell_voltage_cap_tested_v"].unique())
    fig, axes = plt.subplots(1, len(caps), figsize=(6.0 * len(caps), 5.8), squeeze=False)
    norm = Normalize(0.0, 1.0)
    for axis, cap in zip(axes[0], caps):
        subset = selected.loc[np.isclose(selected["cell_voltage_cap_tested_v"], cap, atol=EPS)]
        local_neighbourhood = neighbourhood.loc[
            neighbourhood["source_study"].eq("dense_local")
            & np.isclose(neighbourhood["current_density_a_m2"], primary_current, atol=EPS)
            & np.isclose(neighbourhood["cell_voltage_cap_tested_v"], cap, atol=EPS)
        ]
        draw_heatmap(
            axis,
            subset,
            "robust_pass_fraction",
            cmap=PASS_CMAP,
            norm=norm,
            title=f"{cap:g} V cap | j = {primary_current:g} A/m²",
            neighbourhood=local_neighbourhood,
            show_values=True,
        )
        v55 = subset.loc[
            np.isclose(subset["transport_number_reference_t_w"], 75.0, atol=EPS)
            & np.isclose(subset["water_diffusivity_scale_vs_pfsa"], 0.60, atol=EPS)
        ]
        if not v55.empty:
            tw_values = sorted(subset["transport_number_reference_t_w"].unique())
            d_values = sorted(subset["water_diffusivity_scale_vs_pfsa"].unique())
            axis.scatter(
                tw_values.index(75.0),
                d_values.index(0.60),
                marker="*",
                s=165,
                color=ORANGE,
                edgecolor=WHITE,
                linewidth=0.9,
                zorder=5,
            )
    colour = matplotlib.cm.ScalarMappable(norm=norm, cmap=PASS_CMAP)
    fig.suptitle(
        "Direct EO: cap-specific robust region in the dense local grid",
        x=0.07,
        y=1.01,
        ha="left",
        fontsize=15,
        fontweight="bold",
        color=NAVY,
    )
    fig.text(
        0.07,
        0.96,
        "Dark outline = centre of a complete adjacent 3×3 region where every sampled cell has a robust pass. "
        "Star = legacy v55 coordinate. Receiver handling remains priced at 0 kW.",
        ha="left",
        fontsize=8.8,
        color=SLATE,
    )
    fig.subplots_adjust(left=0.08, right=0.87, bottom=0.11, top=0.85, wspace=0.26)
    colour_axis = fig.add_axes([0.90, 0.19, 0.016, 0.55])
    fig.colorbar(colour, cax=colour_axis, label="Robust pass share")
    finish(fig, output_dir, "01_dense_tw_diffusivity_region_by_cap")


def plot_by_current(
    cells: pd.DataFrame,
    neighbourhood: pd.DataFrame,
    output_dir: Path,
    source: str,
    cap: float,
    stem: str,
    title: str,
) -> None:
    selected = cells.loc[
        cells["source_study"].eq(source)
        & np.isclose(cells["cell_voltage_cap_tested_v"], cap, atol=EPS)
    ]
    if selected.empty:
        return
    currents = sorted(selected["current_density_a_m2"].unique())
    # Four global-current branches read much more clearly as a 2x2 map;
    # the six-branch dense study remains a compact 2x3 map.
    columns = 2 if len(currents) == 4 else min(3, len(currents))
    rows = math.ceil(len(currents) / columns)
    fig, axes = plt.subplots(rows, columns, figsize=(5.1 * columns, 4.35 * rows), squeeze=False)
    norm = Normalize(0.0, 1.0)
    for axis, current in zip(axes.ravel(), currents):
        subset = selected.loc[np.isclose(selected["current_density_a_m2"], current, atol=EPS)]
        local_neighbourhood = neighbourhood.loc[
            neighbourhood["source_study"].eq(source)
            & np.isclose(neighbourhood["cell_voltage_cap_tested_v"], cap, atol=EPS)
            & np.isclose(neighbourhood["current_density_a_m2"], current, atol=EPS)
        ]
        draw_heatmap(
            axis,
            subset,
            "robust_pass_fraction",
            cmap=PASS_CMAP,
            norm=norm,
            title=f"j = {current:g} A/m²",
            neighbourhood=local_neighbourhood,
        )
    for axis in axes.ravel()[len(currents) :]:
        axis.axis("off")
    colour = matplotlib.cm.ScalarMappable(norm=norm, cmap=PASS_CMAP)
    fig.suptitle(title, x=0.06, y=0.995, ha="left", fontsize=15, fontweight="bold", color=NAVY)
    fig.text(
        0.06,
        0.965,
        f"{cap:g} V selected cap; a_process,min ≥ 0.17; conditional saving ≥ 425 kW; "
        "headroom ≥ 0.25 V. Current is sampled—not an acceptance limit.",
        ha="left",
        fontsize=8.7,
        color=SLATE,
    )
    fig.subplots_adjust(left=0.07, right=0.88, bottom=0.07, top=0.91, hspace=0.34, wspace=0.25)
    colour_axis = fig.add_axes([0.91, 0.20, 0.014, 0.58])
    fig.colorbar(colour, cax=colour_axis, label="Robust pass share")
    finish(fig, output_dir, stem)


def plot_parameter_shares(shares: pd.DataFrame, output_dir: Path, cap: float) -> None:
    selected = shares.loc[
        shares["scope"].eq("cap_specific_robust")
        & np.isclose(shares["cell_voltage_cap_tested_v"], cap, atol=EPS)
    ]
    if selected.empty:
        return
    fig, axes = plt.subplots(2, 3, figsize=(14.2, 8.0), squeeze=False)
    source_style = {
        "global_v53": (NAVY, "Global v53 grid"),
        "dense_local": (TEAL, "Dense local grid"),
    }
    for axis, (parameter, label) in zip(axes.ravel(), PARAMETERS):
        parameter_data = selected.loc[selected["parameter"].eq(parameter)]
        plotted = False
        for source, (colour, source_label) in source_style.items():
            line = parameter_data.loc[parameter_data["source_study"].eq(source)].sort_values(
                "parameter_value"
            )
            if line.empty:
                continue
            axis.plot(
                line["parameter_value"],
                line["pass_fraction"],
                marker="o",
                color=colour,
                lw=1.7,
                label=source_label,
            )
            plotted = True
        if not plotted:
            axis.axis("off")
            continue
        if parameter in {
            "water_diffusivity_scale_vs_pfsa",
            "ionic_area_resistance_ohm_m2_at_lambda_ref",
        } and (parameter_data["parameter_value"] > 0).all():
            axis.set_xscale("log")
        axis.set_ylim(-0.03, 1.03)
        axis.set_xlabel(label)
        axis.set_ylabel("Robust pass share")
        axis.grid(True, alpha=0.22)
        axis.spines[["top", "right"]].set_visible(False)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    if handles:
        fig.legend(handles, labels, loc="upper right", frameon=False, bbox_to_anchor=(0.96, 0.98))
    fig.suptitle(
        f"Direct EO parameter sensitivity at the {cap:g} V design cap",
        x=0.05,
        y=0.99,
        ha="left",
        fontsize=15,
        fontweight="bold",
        color=NAVY,
    )
    fig.text(
        0.05,
        0.955,
        "Shares are exact fractions of evaluated simultaneous coordinates, not a fitted surrogate or tolerance claim.",
        ha="left",
        fontsize=8.8,
        color=SLATE,
    )
    fig.tight_layout(rect=(0.04, 0.04, 0.96, 0.92))
    finish(fig, output_dir, "04_parameter_level_robust_pass_share")


def plot_receiver_sec_budget(
    cells: pd.DataFrame,
    output_dir: Path,
    cap: float,
    primary_current: float,
) -> None:
    selected = cells.loc[
        cells["source_study"].eq("dense_local")
        & np.isclose(cells["cell_voltage_cap_tested_v"], cap, atol=EPS)
        & np.isclose(cells["current_density_a_m2"], primary_current, atol=EPS)
    ].copy()
    if selected.empty:
        return
    values = selected["median_robust_receiver_sec_budget_kwh_kg"].dropna()
    if values.empty:
        return
    lower = max(0.0, float(values.quantile(0.02)))
    upper = float(values.quantile(0.98))
    if math.isclose(lower, upper):
        upper = lower + 1.0e-6
    norm = Normalize(lower, upper)
    fig, axis = plt.subplots(figsize=(9.6, 6.2))
    draw_heatmap(
        axis,
        selected,
        "median_robust_receiver_sec_budget_kwh_kg",
        cmap=SEC_CMAP,
        norm=norm,
        title=f"Break-even receiver SEC | {cap:g} V cap, j = {primary_current:g} A/m²",
        show_values=True,
        value_format=".3f",
    )
    colour = matplotlib.cm.ScalarMappable(norm=norm, cmap=SEC_CMAP)
    fig.colorbar(colour, ax=axis, label="Maximum receiver SEC at break-even [kWh/kg water]")
    fig.suptitle(
        "How much receiver/regeneration energy can the conditional saving tolerate?",
        x=0.08,
        y=0.99,
        ha="left",
        fontsize=14.5,
        fontweight="bold",
        color=NAVY,
    )
    fig.text(
        0.08,
        0.945,
        "Only robust cells are coloured. This is an energy budget, not a receiver design; the transport model still assumes 0 kW.",
        ha="left",
        fontsize=8.7,
        color=SLATE,
    )
    fig.tight_layout(rect=(0.04, 0.03, 0.98, 0.90))
    finish(fig, output_dir, "05_dense_receiver_sec_break_even_budget")


def write_summary(
    path: Path,
    cap_register: pd.DataFrame,
    physical: pd.DataFrame,
    cells: pd.DataFrame,
    neighbourhood: pd.DataFrame,
    args: argparse.Namespace,
) -> None:
    lines = [
        "# Direct EO operating-region study v1",
        "",
        "## Interpretation boundary",
        "",
        "The analysis uses evaluated v53 states only. Voltage-cap copies are removed for physical sensitivity and retained for cap-specific decisions. Current density is a sampled operating coordinate; no 21 A/m² limit is applied.",
        "",
        "The primary robust flag requires all inherited v53 physical/architecture gates, the declared hard-area screen, process-side activity ≥ "
        f"{args.process_activity_min:.3f}, conditional known-electric saving ≥ {args.conditional_saving_min_kw:.0f} kW, and maximum local voltage ≤ selected cap − {args.voltage_headroom_v:.2f} V.",
        "",
        "Receiver water removal/regeneration remains outside the modelled system boundary and is stored as 0 kW. Receiver SEC tables report the budget that would consume the conditional saving; they are not full-system closure.",
        "",
        "## Register sizes",
        "",
        "| Source | Cap-expanded rows | Unique physical states | Voltage caps |",
        "|---|---:|---:|---|",
    ]
    for source in sorted(cap_register["source_study"].unique()):
        expanded = cap_register.loc[cap_register["source_study"].eq(source)]
        unique = physical.loc[physical["source_study"].eq(source)]
        caps = ", ".join(f"{value:g} V" for value in sorted(expanded["cell_voltage_cap_tested_v"].unique()))
        lines.append(f"| {source} | {len(expanded):,} | {len(unique):,} | {caps} |")
    lines.extend(
        [
            "",
            "## Cap-specific robust counts",
            "",
            "| Source | Cap | Robust / evaluated | Share | Without hard-area screen |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for (source, cap), group in cap_register.groupby(
        ["source_study", "cell_voltage_cap_tested_v"], sort=True
    ):
        robust = int(group["per_cap_robust_pass"].sum())
        without_area = int(group["per_cap_robust_pass_without_area_screen"].sum())
        lines.append(
            f"| {source} | {cap:g} V | {robust:,} / {len(group):,} | "
            f"{robust/len(group):.1%} | {without_area:,} |"
        )
    lines.extend(
        [
            "",
            "## Local 3×3 regions",
            "",
            "A 3×3 region is index-adjacent in the actually sampled $t_w$ and diffusivity axes at fixed source, voltage cap and current density. A stable centre requires all nine cells to exist and every cell to contain at least one simultaneous robust coordinate. It is a tested-neighbourhood result, not an interpolated manufacturing tolerance.",
            "",
            "| Source | Cap | Current | Stable 3×3 centres |",
            "|---|---:|---:|---:|",
        ]
    )
    stable_summary = (
        neighbourhood.groupby(
            ["source_study", "cell_voltage_cap_tested_v", "current_density_a_m2"], sort=True
        )["all_3x3_cells_have_robust_pass"]
        .sum()
        .reset_index()
    )
    for _, row in stable_summary.iterrows():
        lines.append(
            f"| {row['source_study']} | {row['cell_voltage_cap_tested_v']:g} V | "
            f"{row['current_density_a_m2']:g} A/m² | {int(row['all_3x3_cells_have_robust_pass'])} |"
        )

    dense_primary = cap_register.loc[
        cap_register["source_study"].eq("dense_local")
        & np.isclose(cap_register["cell_voltage_cap_tested_v"], args.primary_cap_v, atol=EPS)
        & np.isclose(
            cap_register["current_density_a_m2"], args.primary_current_density_a_m2, atol=EPS
        )
        & cap_register["per_cap_robust_pass"]
    ]
    lines.extend(["", "## Primary dense-grid envelope", ""])
    if dense_primary.empty:
        lines.append("No dense-grid coordinate passes the primary cap/current robust screen.")
    else:
        lines.extend(
            [
                f"At {args.primary_cap_v:g} V and {args.primary_current_density_a_m2:g} A/m², "
                f"{len(dense_primary):,} simultaneous coordinates pass. Tested passing values span:",
                "",
                f"- $t_w$: {dense_primary['transport_number_reference_t_w'].min():g}–{dense_primary['transport_number_reference_t_w'].max():g}",
                "- diffusivity scale: "
                f"{dense_primary['water_diffusivity_scale_vs_pfsa'].min():.3g}–{dense_primary['water_diffusivity_scale_vs_pfsa'].max():.3g} × PFSA",
                f"- active area: {dense_primary['active_area_m2'].min():.0f}–{dense_primary['active_area_m2'].max():.0f} m²",
                "- receiver SEC budget: "
                f"{dense_primary['receiver_sec_budget_kwh_kg'].min():.3f}–{dense_primary['receiver_sec_budget_kwh_kg'].max():.3f} kWh/kg water.",
            ]
        )

    dense_cap_robust = cap_register.loc[
        cap_register["source_study"].eq("dense_local")
        & np.isclose(cap_register["cell_voltage_cap_tested_v"], args.primary_cap_v, atol=EPS)
        & cap_register["per_cap_robust_pass"]
    ]
    lines.extend(
        [
            "",
            "## Receiver-energy break-even sensitivity",
            "",
            f"Across all dense-grid robust coordinates at {args.primary_cap_v:g} V, the receiver SEC budget is "
            + (
                f"{dense_cap_robust['receiver_sec_budget_kwh_kg'].min():.3f}–"
                f"{dense_cap_robust['receiver_sec_budget_kwh_kg'].max():.3f} kWh/kg "
                f"(median {dense_cap_robust['receiver_sec_budget_kwh_kg'].median():.3f})."
                if not dense_cap_robust.empty
                else "not available because no coordinate passes."
            ),
            "",
            "| Assumed receiver SEC | Positive after receiver energy / robust coordinates | Share |",
            "|---:|---:|---:|",
        ]
    )
    for sec in sorted(set(float(value) for value in args.receiver_sec_values_kwh_kg)):
        residual = (
            dense_cap_robust["conditional_known_electric_saving_kw"]
            - sec * dense_cap_robust["receiver_sink_net_kg_h"]
        )
        positive = int((residual >= -EPS).sum())
        share = positive / len(dense_cap_robust) if len(dense_cap_robust) else math.nan
        lines.append(
            f"| {sec:.2f} kWh/kg | {positive:,} / {len(dense_cap_robust):,} | "
            f"{share:.1%} |"
        )

    lines.extend(
        [
            "",
            "## Files",
            "",
            "- `per_cap_robust_register.csv`: every cap copy with transparent robust component flags and failure reason.",
            "- `physical_sensitivity_register.csv`: one row per physical coordinate after cap deduplication.",
            "- `parameter_level_pass_share.csv`: exact physical and cap-specific pass shares at every sampled parameter level.",
            "- `tw_diffusivity_cell_register.csv`: exact cell-level robust fractions after nuisance-coordinate aggregation.",
            "- `tw_diffusivity_3x3_neighborhood.csv`: adjacent tested-neighbourhood diagnostics.",
            "- `receiver_sec_scenarios.csv`: non-zero receiver-energy consequences without pretending that a receiver has been designed.",
            "- `receiver_sec_cap_summary.csv`: survival of each robust cap-specific set under the declared receiver-SEC scenarios.",
            "- PNG/PDF pairs `01`–`05`: report-ready operating-region maps.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def validate_args(args: argparse.Namespace) -> None:
    if not 0.0 < args.process_activity_min < 1.0:
        raise ValueError("--process-activity-min must lie in (0, 1)")
    if args.conditional_saving_min_kw < 0.0:
        raise ValueError("--conditional-saving-min-kw must be non-negative")
    if args.voltage_headroom_v < 0.0:
        raise ValueError("--voltage-headroom-v must be non-negative")
    if args.primary_cap_v <= 0.0 or args.primary_current_density_a_m2 <= 0.0:
        raise ValueError("Primary cap and current density must be positive")
    if not args.receiver_sec_values_kwh_kg or any(
        value < 0.0 for value in args.receiver_sec_values_kwh_kg
    ):
        raise ValueError("Receiver SEC values must be non-negative")


def run_analysis(args: argparse.Namespace) -> dict[str, object]:
    validate_args(args)
    if args.require_empty_out_dir and args.out_dir.exists() and any(args.out_dir.iterdir()):
        raise ValueError(f"--require-empty-out-dir refused non-empty directory: {args.out_dir}")
    manifest = load_manifest(args.manifest)
    global_register = load_register(args.global_register, "global_v53")
    dense_register = load_register(args.dense_register, "dense_local")
    validate_manifest_dense_axes(dense_register, manifest)
    raw = pd.concat([global_register, dense_register], ignore_index=True, sort=False)

    cap_register = add_cap_specific_robust_flags(
        raw,
        process_activity_min=args.process_activity_min,
        conditional_saving_min_kw=args.conditional_saving_min_kw,
        voltage_headroom_v=args.voltage_headroom_v,
    )
    cap_register = add_receiver_sec_budget(cap_register)
    physical = deduplicate_cap_copies(cap_register)
    physical = add_receiver_sec_budget(physical)
    shares = parameter_level_pass_share(physical, cap_register)
    cells = tw_diffusivity_cells(cap_register)
    neighbourhood = build_3x3_neighborhood(cells)
    sec_scenarios = receiver_sec_scenarios(physical, args.receiver_sec_values_kwh_kg)
    sec_cap_summary = receiver_sec_cap_summary(cap_register, args.receiver_sec_values_kwh_kg)
    failures = gate_failure_summary(cap_register)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    cap_register.to_csv(args.out_dir / "per_cap_robust_register.csv", index=False)
    physical.to_csv(args.out_dir / "physical_sensitivity_register.csv", index=False)
    shares.to_csv(args.out_dir / "parameter_level_pass_share.csv", index=False)
    cells.to_csv(args.out_dir / "tw_diffusivity_cell_register.csv", index=False)
    neighbourhood.to_csv(args.out_dir / "tw_diffusivity_3x3_neighborhood.csv", index=False)
    sec_scenarios.to_csv(args.out_dir / "receiver_sec_scenarios.csv", index=False)
    sec_cap_summary.to_csv(args.out_dir / "receiver_sec_cap_summary.csv", index=False)
    failures.to_csv(args.out_dir / "gate_failure_summary.csv", index=False)

    assumptions = {
        "manifest": str(args.manifest.resolve()),
        "manifest_study_id": manifest.get("study_id"),
        "v53_generator": str(args.v53_generator.resolve()),
        "global_register": str(args.global_register.resolve()),
        "dense_register": str(args.dense_register.resolve()),
        "global_assumptions_v53": str(args.global_assumptions_v53.resolve()),
        "dense_assumptions_v53": str(args.dense_assumptions_v53.resolve()),
        "process_activity_min": args.process_activity_min,
        "conditional_saving_min_kw": args.conditional_saving_min_kw,
        "selected_cap_voltage_headroom_v": args.voltage_headroom_v,
        "primary_cap_v": args.primary_cap_v,
        "primary_current_density_a_m2": args.primary_current_density_a_m2,
        "receiver_sec_values_kwh_kg": list(map(float, args.receiver_sec_values_kwh_kg)),
        "current_density_acceptance_limit_a_m2": None,
        "current_density_policy": manifest.get("current_density_policy"),
        "receiver_energy_boundary": (
            "Inherited ideal-wet-interface simulations assign receiver water removal/regeneration 0 kW; "
            "non-zero SEC is a post-calculated break-even sensitivity only."
        ),
    }
    (args.out_dir / "analysis_assumptions.json").write_text(
        json.dumps(assumptions, indent=2) + "\n", encoding="utf-8"
    )

    style()
    plot_dense_by_cap(cells, neighbourhood, args.out_dir, args.primary_current_density_a_m2)
    plot_by_current(
        cells,
        neighbourhood,
        args.out_dir,
        source="dense_local",
        cap=args.primary_cap_v,
        stem="02_dense_tw_diffusivity_region_by_current",
        title="Direct EO dense study: operating region across current density",
    )
    plot_by_current(
        cells,
        neighbourhood,
        args.out_dir,
        source="global_v53",
        cap=args.primary_cap_v,
        stem="03_global_tw_diffusivity_region_by_current",
        title="Direct EO global v53: robust share across material combinations",
    )
    plot_parameter_shares(shares, args.out_dir, args.primary_cap_v)
    plot_receiver_sec_budget(
        cells, args.out_dir, args.primary_cap_v, args.primary_current_density_a_m2
    )
    write_summary(
        args.out_dir / "summary_direct_eo_operating_region_v1.md",
        cap_register,
        physical,
        cells,
        neighbourhood,
        args,
    )
    output_row_counts = {
        "per_cap_robust_register.csv": len(cap_register),
        "physical_sensitivity_register.csv": len(physical),
        "parameter_level_pass_share.csv": len(shares),
        "tw_diffusivity_cell_register.csv": len(cells),
        "tw_diffusivity_3x3_neighborhood.csv": len(neighbourhood),
        "receiver_sec_scenarios.csv": len(sec_scenarios),
        "receiver_sec_cap_summary.csv": len(sec_cap_summary),
        "gate_failure_summary.csv": len(failures),
    }
    audit = build_audit(args, manifest, cap_register, physical, output_row_counts)
    return {
        "cap_register": cap_register,
        "physical": physical,
        "shares": shares,
        "cells": cells,
        "neighbourhood": neighbourhood,
        "receiver_sec_scenarios": sec_scenarios,
        "receiver_sec_cap_summary": sec_cap_summary,
        "failures": failures,
        "audit": audit,
    }


def main() -> int:
    args = parse_args()
    result = run_analysis(args)
    robust = int(result["cap_register"]["per_cap_robust_pass"].sum())
    print(f"Direct-EO operating-region analysis complete: {args.out_dir}")
    print(
        f"Rows: {len(result['cap_register']):,} cap-expanded; "
        f"{len(result['physical']):,} unique physical; {robust:,} cap-specific robust passes."
    )
    print("No current-density acceptance limit was applied. Receiver energy remains conditional.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, RuntimeError, ValueError) as error:
        raise SystemExit(f"ERROR: {error}") from error
