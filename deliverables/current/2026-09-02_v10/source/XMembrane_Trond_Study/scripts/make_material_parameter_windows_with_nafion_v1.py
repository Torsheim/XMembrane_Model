#!/usr/bin/env python3
"""Build audited membrane-parameter window plots with a Nafion reference.

The study deliberately keeps three evidence planes separate:

* direct EO under the canonical 2 V / preferred 1.8 V voltage screen;
* post-ERV conditional screening before receiver and surface closure;
* a declared literature-function Nafion reference envelope.

Only joint rows in the source grids are treated as joint results.  Fixed axes
and marginal ranges are labelled as screening coordinates, not as a material
recipe or a validated full-system saving claim.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config/material_parameter_windows_with_nafion_v1.json"
DEFAULT_OUTPUT = ROOT / "outputs/material_parameter_windows_with_nafion_v1"

NAVY = "#17324d"
BLUE = "#2878a8"
TEAL = "#008c8c"
GREEN = "#158466"
ORANGE = "#e88924"
RED = "#c44e3b"
GREY = "#dfe5e8"
DARK_GREY = "#667782"
GRID = "#d8e0e5"


@dataclass(frozen=True)
class NafionReference:
    drag_min: float
    drag_max: float
    thickness_min_um: float
    thickness_max_um: float
    diffusivity_min_m2_s: float
    diffusivity_max_m2_s: float
    conductivity_min_s_m: float
    conductivity_max_s_m: float
    capacity_slope_min: float
    capacity_slope_max: float
    lambda_min: float
    lambda_max: float
    adapter_reference_activity: float
    adapter_diffusivity_ref_m2_s: float
    adapter_diffusivity_exponent: float
    adapter_diffusivity_max_abs_relative_error: float
    adapter_conductivity_ref_s_m: float
    adapter_conductivity_exponent: float
    adapter_conductivity_max_abs_relative_error: float
    conductivity_at_lambda_ref_s_m: float
    diffusivity_at_lambda_ref_m2_s: float
    direct_d_scale_min: float
    direct_d_scale_max: float
    direct_d_scale_at_lambda_ref: float
    asr_min_ohm_m2: float
    asr_max_ohm_m2: float
    grade_ids: tuple[str, ...]
    thicknesses_um: tuple[float, ...]
    asr_values_ohm_m2: tuple[float, ...]
    drag_scenarios: tuple[float, ...]
    grade_count: int
    case_count: int


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _file_record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "sha256": _sha256(path),
        "size_bytes": path.stat().st_size,
    }


def _resolve_path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def _as_bool(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        if series.isna().any():
            raise ValueError(f"Boolean column {series.name!r} contains missing values")
        return series.astype(bool)
    if pd.api.types.is_numeric_dtype(series):
        numeric = pd.to_numeric(series, errors="raise")
        if numeric.isna().any() or not numeric.isin([0, 1]).all():
            bad = sorted(set(map(str, numeric.loc[numeric.isna() | ~numeric.isin([0, 1])].tolist())))
            raise ValueError(f"Boolean column {series.name!r} contains invalid numeric tokens: {bad[:5]}")
        return numeric.eq(1)
    normalized = series.astype("string").str.strip().str.lower()
    mapping = {"true": True, "1": True, "yes": True, "false": False, "0": False, "no": False}
    invalid = normalized.isna() | ~normalized.isin(mapping)
    if invalid.any():
        bad = sorted(set(map(str, normalized.loc[invalid].tolist())))
        raise ValueError(f"Boolean column {series.name!r} contains invalid tokens: {bad[:5]}")
    return normalized.map(mapping).astype(bool)


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _log_edges(values: Iterable[float]) -> np.ndarray:
    values = np.asarray(sorted(set(float(v) for v in values)), dtype=float)
    if len(values) < 2 or np.any(values <= 0):
        raise ValueError("Log-grid axes need at least two distinct positive values")
    mids = np.sqrt(values[:-1] * values[1:])
    first = values[0] ** 2 / mids[0]
    last = values[-1] ** 2 / mids[-1]
    return np.concatenate(([first], mids, [last]))


def _linear_edges(values: Iterable[float]) -> np.ndarray:
    values = np.asarray(sorted(set(float(v) for v in values)), dtype=float)
    if len(values) < 2:
        raise ValueError("Linear-grid axes need at least two distinct values")
    mids = (values[:-1] + values[1:]) / 2.0
    return np.concatenate(([values[0] - (mids[0] - values[0])], mids, [values[-1] + (values[-1] - mids[-1])]))


def _linear_cell_span(values: Iterable[float], selected: Iterable[float]) -> tuple[float, float]:
    axis = np.asarray(sorted(set(float(value) for value in values)), dtype=float)
    chosen = np.asarray(sorted(set(float(value) for value in selected)), dtype=float)
    indices = [int(np.flatnonzero(np.isclose(axis, value, rtol=0.0, atol=1e-12))[0]) for value in chosen]
    edges = _linear_edges(axis)
    return float(edges[min(indices)]), float(edges[max(indices) + 1])


def _pivot(
    data: pd.DataFrame,
    x: str,
    y: str,
    value: str,
    x_values: Iterable[float] | None = None,
    y_values: Iterable[float] | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    xv = np.asarray(sorted(set(data[x] if x_values is None else x_values)), dtype=float)
    yv = np.asarray(sorted(set(data[y] if y_values is None else y_values)), dtype=float)
    table = data.pivot(index=y, columns=x, values=value).reindex(index=yv, columns=xv)
    return xv, yv, table.to_numpy(dtype=float)


def _save_figure(fig: plt.Figure, output_dir: Path, stem: str, dpi: int) -> list[Path]:
    paths = [output_dir / f"{stem}.png", output_dir / f"{stem}.pdf"]
    fig.savefig(paths[0], dpi=dpi, bbox_inches="tight", facecolor="white")
    fig.savefig(paths[1], bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return paths


def _apply_axis_style(axis: plt.Axes) -> None:
    axis.grid(True, which="major", color=GRID, linewidth=0.65, alpha=0.8)
    axis.grid(True, which="minor", color=GRID, linewidth=0.35, alpha=0.35)
    axis.set_axisbelow(True)
    for spine in axis.spines.values():
        spine.set_color("#9aa9b3")
        spine.set_linewidth(0.7)


def _mark_nafion_direct(axis: plt.Axes, ref: NafionReference) -> None:
    axis.plot(
        [ref.drag_min, ref.drag_max],
        [ref.direct_d_scale_at_lambda_ref, ref.direct_d_scale_at_lambda_ref],
        color=ORANGE,
        linewidth=3.2,
        solid_capstyle="round",
        zorder=8,
    )
    axis.scatter(
        [ref.drag_min, 1.0, ref.drag_max],
        [ref.direct_d_scale_at_lambda_ref] * 3,
        s=42,
        facecolor="white",
        edgecolor=ORANGE,
        linewidth=1.25,
        zorder=9,
    )
    axis.plot(
        [1.0, 1.0],
        [ref.direct_d_scale_min, ref.direct_d_scale_max],
        color=ORANGE,
        linewidth=1.5,
        zorder=8,
    )
    axis.scatter(
        [1.0, 1.0],
        [ref.direct_d_scale_min, ref.direct_d_scale_max],
        marker="_",
        s=80,
        color=ORANGE,
        linewidth=1.5,
        zorder=9,
    )
    axis.text(
        0.34,
        2.45,
        (
            "Nafion, separate referanseakser\n"
            f"$t_w$={ref.drag_min:.1f}–{ref.drag_max:.1f}; "
            f"D/V5 (lik $\\lambda$)={ref.direct_d_scale_min:.2f}–{ref.direct_d_scale_max:.2f}"
        ).replace(".", ","),
        color="#9a550e",
        fontsize=8.1,
        ha="left",
        va="top",
        fontweight="bold",
        zorder=10,
    )


def _log_cell_span(values: Iterable[float], selected: Iterable[float]) -> tuple[float, float]:
    axis = np.asarray(sorted(set(float(value) for value in values)), dtype=float)
    chosen = np.asarray(sorted(set(float(value) for value in selected)), dtype=float)
    indices = [int(np.flatnonzero(np.isclose(axis, value, rtol=0.0, atol=1e-12))[0]) for value in chosen]
    edges = _log_edges(axis)
    return float(edges[min(indices)]), float(edges[max(indices) + 1])


def _load_inputs(config_path: Path) -> tuple[dict[str, Any], dict[str, Path], dict[str, Any]]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    paths = {name: _resolve_path(value) for name, value in config["sources"].items()}
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing declared sources: {missing}")
    expected_hashes = config.get("expected_source_sha256", {})
    if set(expected_hashes) != set(paths):
        raise AssertionError("Expected-source SHA-256 keys do not exactly match declared sources")
    actual_hashes = {name: _sha256(path) for name, path in paths.items()}
    hash_mismatches = {
        name: {"expected": expected_hashes[name], "actual": actual_hashes[name]}
        for name in paths
        if actual_hashes[name] != expected_hashes[name]
    }
    if hash_mismatches:
        raise AssertionError(f"Declared source SHA-256 mismatch: {hash_mismatches}")

    direct_audit = json.loads(paths["direct_analysis_audit"].read_text(encoding="utf-8"))
    broad_audit = json.loads(paths["direct_broad_analysis_audit"].read_text(encoding="utf-8"))
    region_audit = json.loads(paths["operating_region_study_audit"].read_text(encoding="utf-8"))
    post_audit = json.loads(paths["post_erv_audit"].read_text(encoding="utf-8"))
    if direct_audit.get("status") != "PASS":
        raise AssertionError("Canonical direct-EO low-voltage audit is not PASS")
    direct_outputs = direct_audit.get("outputs", {})
    direct_bindings = {
        "low_voltage_cap_register.csv": "direct_low_voltage_cap_register",
        "fixed_loss_sensitivity.csv": "direct_fixed_loss_sensitivity",
    }
    for output_name, source_name in direct_bindings.items():
        if direct_outputs.get(output_name, {}).get("sha256") != actual_hashes[source_name]:
            raise AssertionError(f"Direct-EO source {source_name} does not match its upstream output audit")
    if post_audit.get("pass") is not True:
        raise AssertionError("Post-ERV operating-region audit is not PASS")
    if post_audit.get("full_system_claim_allowed") is not False:
        raise AssertionError("Post-ERV full-system claim boundary changed")
    if broad_audit.get("status") != "PASS" or region_audit.get("pass") is not True:
        raise AssertionError("Broad direct-EO upstream audit chain is not PASS")
    required_outputs = {row["relative_path"]: row for row in broad_audit.get("required_outputs", [])}
    broad_output = required_outputs.get("per_cap_robust_register.csv")
    if broad_output is None or broad_output.get("sha256") != actual_hashes["direct_broad_material_register"]:
        raise AssertionError("Broad direct-EO register does not match its upstream output audit")
    if region_audit.get("sha256", {}).get("direct_analysis_audit") != actual_hashes["direct_broad_analysis_audit"]:
        raise AssertionError("Combined operating-region audit does not bind the broad direct audit")
    if region_audit.get("sha256", {}).get("post_erv_audit") != actual_hashes["post_erv_audit"]:
        raise AssertionError("Combined operating-region audit does not bind the current post-ERV audit")

    module_path = paths["nafion_reference_module"]
    spec = importlib.util.spec_from_file_location("heiq_nafion_reference_for_windows", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load Nafion reference module: {module_path}")
    nafion_module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = nafion_module
    spec.loader.exec_module(nafion_module)

    tables: dict[str, Any] = {
        "direct_cap": pd.read_csv(paths["direct_low_voltage_cap_register"]),
        "direct_fixed_loss": pd.read_csv(paths["direct_fixed_loss_sensitivity"]),
        "direct_broad": pd.read_csv(paths["direct_broad_material_register"], low_memory=False),
        "post_erv": pd.read_csv(paths["post_erv_dense_register"]),
        "nafion_module": nafion_module,
        "direct_audit": direct_audit,
        "direct_broad_audit": broad_audit,
        "region_audit": region_audit,
        "post_audit": post_audit,
    }
    return config, paths, tables


def _build_nafion_reference(config: dict[str, Any], tables: dict[str, Any]) -> NafionReference:
    module = tables["nafion_module"]
    activity_min = float(config["nafion_reference"]["activity_min"])
    activity_max = float(config["nafion_reference"]["activity_max"])
    temperature_c = float(config["nafion_reference"]["temperature_c"])
    temperature_k = temperature_c + 273.15
    adapter_reference_activity = float(config["nafion_reference"]["adapter_reference_activity"])
    activities = np.linspace(activity_min, activity_max, 501)
    lambdas = np.asarray(module.nafion_lambda_vapour(activities), dtype=float)
    diffusivities = np.asarray(module.nafion_water_diffusivity_m2_s(activities, temperature_k=temperature_k), dtype=float)
    conductivities = np.asarray(module.nafion_conductivity_s_m(activities, temperature_k=temperature_k), dtype=float)
    capacities = np.asarray(module.nafion_dcdactivity_mol_m3_activity(activities), dtype=float)
    fitted_v14, fit_audit, _ = module.fit_nafion_to_v14_powerlaw(
        activity_min=activity_min,
        activity_max=activity_max,
        reference_activity=adapter_reference_activity,
        temperature_c=temperature_c,
        points=501,
    )
    fit_by_property = fit_audit.set_index("property_name")
    grade_ids = tuple(str(grade.grade_id) for grade in module.NAFION_GRADES)
    thicknesses = np.asarray([grade.dry_thickness_um for grade in module.NAFION_GRADES], dtype=float)
    drags = np.asarray([row["water_drag"] for row in module.DEFAULT_DRAG_SCENARIOS], dtype=float)

    lambda_ref = float(config["nafion_reference"]["lambda_reference"])
    lambda_low = float(config["nafion_reference"]["lambda_scale_interval_min"])
    lambda_high = float(config["nafion_reference"]["lambda_scale_interval_max"])
    lambda_axis = np.linspace(lambda_low, lambda_high, 501)

    def internal_v5_diffusivity(lam: np.ndarray | float) -> np.ndarray:
        values = np.asarray(lam, dtype=float)
        return 1.0e-10 * (0.12 + (np.maximum(values, 0.05) / 14.0) ** 2.6)

    def nafion_diffusivity_from_lambda(lam: np.ndarray | float) -> np.ndarray:
        values = np.maximum(np.asarray(lam, dtype=float), 1e-12)
        low = 3.1e-3 * values * (np.exp(0.28 * values) - 1.0) * np.exp(-2436.0 / temperature_k)
        high = 4.17e-4 * values * (161.0 * np.exp(-values) + 1.0) * np.exp(-2436.0 / temperature_k)
        return np.where(values < 3.0, low, high) * 1e-4

    d_scales = nafion_diffusivity_from_lambda(lambda_axis) / internal_v5_diffusivity(lambda_axis)
    d_ref = float(nafion_diffusivity_from_lambda(lambda_ref))
    conductivity_ref = float(
        max(
            (0.005139 * lambda_ref - 0.00326)
            * math.exp(1268.0 * (1.0 / 303.0 - 1.0 / temperature_k))
            * 100.0,
            1e-9,
        )
    )
    asr_values = thicknesses * 1e-6 / conductivity_ref
    return NafionReference(
        drag_min=float(drags.min()),
        drag_max=float(drags.max()),
        thickness_min_um=float(thicknesses.min()),
        thickness_max_um=float(thicknesses.max()),
        diffusivity_min_m2_s=float(diffusivities.min()),
        diffusivity_max_m2_s=float(diffusivities.max()),
        conductivity_min_s_m=float(conductivities.min()),
        conductivity_max_s_m=float(conductivities.max()),
        capacity_slope_min=float(capacities.min()),
        capacity_slope_max=float(capacities.max()),
        lambda_min=float(lambdas.min()),
        lambda_max=float(lambdas.max()),
        adapter_reference_activity=float(fitted_v14["powerlaw_reference_activity"]),
        adapter_diffusivity_ref_m2_s=float(fitted_v14["water_diffusivity_m2_s"]),
        adapter_diffusivity_exponent=float(fitted_v14["diffusivity_activity_exponent"]),
        adapter_diffusivity_max_abs_relative_error=float(
            fit_by_property.loc["water_diffusivity_m2_s", "maximum_absolute_relative_error"]
        ),
        adapter_conductivity_ref_s_m=float(fitted_v14["conductivity_s_m"]),
        adapter_conductivity_exponent=float(fitted_v14["conductivity_activity_exponent"]),
        adapter_conductivity_max_abs_relative_error=float(
            fit_by_property.loc["conductivity_s_m", "maximum_absolute_relative_error"]
        ),
        conductivity_at_lambda_ref_s_m=conductivity_ref,
        diffusivity_at_lambda_ref_m2_s=d_ref,
        direct_d_scale_min=float(d_scales.min()),
        direct_d_scale_max=float(d_scales.max()),
        direct_d_scale_at_lambda_ref=float(d_ref / internal_v5_diffusivity(lambda_ref)),
        asr_min_ohm_m2=float(asr_values.min()),
        asr_max_ohm_m2=float(asr_values.max()),
        grade_ids=grade_ids,
        thicknesses_um=tuple(map(float, thicknesses)),
        asr_values_ohm_m2=tuple(map(float, asr_values)),
        drag_scenarios=tuple(map(float, drags)),
        grade_count=int(len(module.NAFION_GRADES)),
        case_count=int(len(module.NAFION_GRADES) * len(module.DEFAULT_DRAG_SCENARIOS)),
    )


def _build_nafion_reference_tables(
    config: dict[str, Any], tables: dict[str, Any], ref: NafionReference
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    module = tables["nafion_module"]
    activity = np.linspace(
        float(config["nafion_reference"]["activity_min"]),
        float(config["nafion_reference"]["activity_max"]),
        501,
    )
    temperature_k = float(config["nafion_reference"]["temperature_c"]) + 273.15
    fitted_v14, fit_audit, fitted_curve = module.fit_nafion_to_v14_powerlaw(
        activity_min=float(config["nafion_reference"]["activity_min"]),
        activity_max=float(config["nafion_reference"]["activity_max"]),
        reference_activity=float(config["nafion_reference"]["adapter_reference_activity"]),
        temperature_c=float(config["nafion_reference"]["temperature_c"]),
        points=501,
    )
    lam = np.asarray(module.nafion_lambda_vapour(activity), dtype=float)
    diffusivity = np.asarray(module.nafion_water_diffusivity_m2_s(activity, temperature_k=temperature_k), dtype=float)
    internal_equal_lambda_d = 1.0e-10 * (0.12 + (np.maximum(lam, 0.05) / 14.0) ** 2.6)
    curve = pd.DataFrame(
        {
            "water_activity": activity,
            "nafion_lambda": lam,
            "nafion_conductivity_s_m": module.nafion_conductivity_s_m(activity, temperature_k=temperature_k),
            "nafion_water_diffusivity_m2_s": diffusivity,
            "nafion_capacity_slope_mol_m3_activity": module.nafion_dcdactivity_mol_m3_activity(activity),
            "nafion_conductivity_s_m_v14_fit": fitted_curve["nafion_conductivity_s_m_v14_fit"],
            "nafion_water_diffusivity_m2_s_v14_fit": fitted_curve["nafion_water_diffusivity_m2_s_v14_fit"],
            "nafion_capacity_slope_mol_m3_activity_v14_fit": fitted_curve[
                "nafion_dcdactivity_mol_m3_activity_v14_fit"
            ],
            "internal_v5_diffusivity_at_equal_lambda_m2_s": internal_equal_lambda_d,
            "nafion_d_over_internal_v5_at_equal_lambda": diffusivity / internal_equal_lambda_d,
            "inside_declared_v5_lambda_mapping_interval": (
                (lam >= float(config["nafion_reference"]["lambda_scale_interval_min"]))
                & (lam <= float(config["nafion_reference"]["lambda_scale_interval_max"]))
            ),
        }
    )

    rows: list[dict[str, Any]] = []
    grade_lookup = {grade.grade_id: grade for grade in module.NAFION_GRADES}
    for grade_id, thickness_um, asr in zip(ref.grade_ids, ref.thicknesses_um, ref.asr_values_ohm_m2):
        grade = grade_lookup[grade_id]
        for drag_case in module.DEFAULT_DRAG_SCENARIOS:
            rows.append(
                {
                    "material_case_id": f"nafion_{grade_id}_{drag_case['id']}",
                    "grade_id": grade_id,
                    "manufacturing_family": grade.manufacturing_family,
                    "dry_thickness_um": thickness_um,
                    "water_drag_reference": float(drag_case["water_drag"]),
                    "drag_scenario_id": str(drag_case["id"]),
                    "conductivity_at_lambda_8_s_m": ref.conductivity_at_lambda_ref_s_m,
                    "water_diffusivity_at_lambda_8_m2_s": ref.diffusivity_at_lambda_ref_m2_s,
                    "d_over_internal_v5_at_equal_lambda_8": ref.direct_d_scale_at_lambda_ref,
                    "v14_adapter_reference_activity": ref.adapter_reference_activity,
                    "v14_adapter_diffusivity_ref_m2_s": ref.adapter_diffusivity_ref_m2_s,
                    "v14_adapter_diffusivity_exponent": ref.adapter_diffusivity_exponent,
                    "v14_adapter_conductivity_ref_s_m": ref.adapter_conductivity_ref_s_m,
                    "v14_adapter_conductivity_exponent": ref.adapter_conductivity_exponent,
                    "area_resistance_l_over_sigma_at_lambda_8_ohm_m2": asr,
                    "validated_for_heiq_device": False,
                    "interpretation": str(drag_case["interpretation"]),
                }
            )
    fit_audit = fit_audit.copy()
    fit_audit["adapter_reference_activity"] = float(fitted_v14["powerlaw_reference_activity"])
    return curve, pd.DataFrame(rows), fit_audit


def _direct_joint_register(config: dict[str, Any], direct_cap: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    cap = float(config["direct_eo"]["primary_voltage_cap_v"])
    primary = direct_cap.loc[np.isclose(direct_cap["cell_voltage_cap_tested_v"], cap)].copy()
    key = ["transport_number_reference_t_w", "water_diffusivity_scale_vs_pfsa", "current_density_a_m2"]
    if primary.duplicated(key).any():
        raise AssertionError("Direct primary-cap register is not unique on the physical grid")
    for column in ["membrane_operating_pass_at_cap", "preferred_membrane_operating_pass"]:
        primary[column] = _as_bool(primary[column])
    grouped = (
        primary.groupby(key[:2], as_index=False)
        .agg(
            evaluated_current_count=("current_density_a_m2", "nunique"),
            pass_2v_current_count=("membrane_operating_pass_at_cap", "sum"),
            pass_1p8v_current_count=("preferred_membrane_operating_pass", "sum"),
        )
        .sort_values(key[:2])
    )
    return primary, grouped


def _verify_declared_direct_cores(config: dict[str, Any], primary: pd.DataFrame) -> dict[str, dict[str, Any]]:
    d_values = sorted(map(float, primary["water_diffusivity_scale_vs_pfsa"].unique()))
    verified: dict[str, dict[str, Any]] = {}
    for cap_label, gate_column in [("2.0", "membrane_operating_pass_at_cap"), ("1.8", "preferred_membrane_operating_pass")]:
        declaration = config["direct_eo"]["observed_full_discrete_cores"][cap_label]
        tw_values = list(map(float, declaration["transport_number_reference_t_w"]))
        j_values = list(map(float, declaration["current_density_a_m2"]))
        if declaration["diffusivity_axis"] != "all_tested":
            raise AssertionError(f"Unsupported diffusivity-axis declaration for {cap_label} V")
        selected = primary.loc[
            primary["transport_number_reference_t_w"].isin(tw_values)
            & primary["current_density_a_m2"].isin(j_values)
            & primary["water_diffusivity_scale_vs_pfsa"].isin(d_values)
        ].copy()
        expected_rows = int(declaration["expected_rows"])
        if len(selected) != expected_rows or not _as_bool(selected[gate_column]).all():
            raise AssertionError(f"Declared {cap_label} V full discrete core is not {expected_rows}/{expected_rows} pass")
        verified[cap_label] = {
            "tw_values": tw_values,
            "j_values": j_values,
            "d_values": d_values,
            "row_count": int(len(selected)),
        }
    return verified


def _direct_energy_register(config: dict[str, Any], fixed_loss: pd.DataFrame) -> pd.DataFrame:
    losses = [
        float(config["direct_eo"]["baseline_combined_fixed_loss_v"]),
        float(config["direct_eo"]["aspirational_combined_fixed_loss_v"]),
    ]
    subset = fixed_loss.loc[
        np.isclose(fixed_loss["combined_fixed_loss_scenario_v"], losses[0])
        | np.isclose(fixed_loss["combined_fixed_loss_scenario_v"], losses[1])
    ].copy()
    subset["scenario_membrane_operating_pass_2v"] = _as_bool(subset["scenario_membrane_operating_pass_2v"])
    subset["scenario_modern_positive_before_receiver_pass"] = _as_bool(
        subset["scenario_modern_positive_before_receiver_pass"]
    )
    rows: list[dict[str, Any]] = []
    group_cols = ["combined_fixed_loss_scenario_v", "transport_number_reference_t_w", "water_diffusivity_scale_vs_pfsa"]
    for keys, group in subset.groupby(group_cols, sort=True):
        passed = group.loc[group["scenario_membrane_operating_pass_2v"]]
        positive = group.loc[
            group["scenario_membrane_operating_pass_2v"]
            & group["scenario_modern_positive_before_receiver_pass"]
        ]
        if passed.empty:
            best_margin = math.nan
            best_current = math.nan
        else:
            best_index = passed["scenario_modern_comparator_margin_before_receiver_kw"].idxmax()
            best_margin = float(passed.loc[best_index, "scenario_modern_comparator_margin_before_receiver_kw"])
            best_current = float(passed.loc[best_index, "current_density_a_m2"])
        rows.append(
            {
                "combined_fixed_loss_scenario_v": float(keys[0]),
                "transport_number_reference_t_w": float(keys[1]),
                "water_diffusivity_scale_vs_pfsa": float(keys[2]),
                "membrane_pass_current_count": int(len(passed)),
                "modern_positive_current_count": int(len(positive)),
                "best_modern_margin_before_receiver_kw": best_margin,
                "best_margin_current_density_a_m2": best_current,
            }
        )
    return pd.DataFrame(rows)


def _broad_direct_register(data: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    axes = [
        "transport_number_reference_t_w",
        "current_density_a_m2",
        "water_diffusivity_scale_vs_pfsa",
        "ionic_area_resistance_ohm_m2_at_lambda_ref",
        "dry_thickness_um",
        "retention_factor_vs_pfsa_sorption",
    ]
    result = data.loc[
        data["source_study"].eq("global_v53")
        & np.isclose(data["cell_voltage_cap_tested_v"], 2.0)
    ].copy()
    if result.duplicated(axes).any():
        raise AssertionError("Broad global-v53 material register is not unique on its six material/control axes")
    for column in [
        "strict_physical_and_architecture_pass",
        "hard_area_cap_pass",
        "process_activity_robust_pass",
    ]:
        result[column] = _as_bool(result[column])
    base = (
        result["strict_physical_and_architecture_pass"]
        & result["hard_area_cap_pass"]
        & result["process_activity_robust_pass"]
    )
    result["membrane_replay_pass_2v"] = base & (result["cell_voltage_required_max_v"] <= 2.0 + 1e-12)
    result["membrane_replay_pass_1p8v"] = base & (result["cell_voltage_required_max_v"] <= 1.8 + 1e-12)

    core_mask = (
        np.isclose(result["transport_number_reference_t_w"], 20.0)
        & result["current_density_a_m2"].isin([100.0, 150.0])
        & result["retention_factor_vs_pfsa_sorption"].isin([1.25, 1.5])
    )
    core = result.loc[core_mask]
    if len(core) != 384 or not core["membrane_replay_pass_1p8v"].all():
        raise AssertionError("Declared broad 1.8 V material core is not 384/384 pass")
    metadata = {
        "axes": axes,
        "core_rows": int(len(core)),
        "core_tw": [20.0],
        "core_j": [100.0, 150.0],
        "core_d": sorted(map(float, result["water_diffusivity_scale_vs_pfsa"].unique())),
        "core_asr": sorted(map(float, result["ionic_area_resistance_ohm_m2_at_lambda_ref"].unique())),
        "core_thickness": sorted(map(float, result["dry_thickness_um"].unique())),
        "core_retention": [1.25, 1.5],
    }
    return result, metadata


def _post_register(post_erv: pd.DataFrame) -> pd.DataFrame:
    key = ["water_diffusivity_m2_s", "uniform_current_density_a_m2"]
    if post_erv.duplicated(key).any():
        raise AssertionError("Post-ERV dense grid is not unique on D-j")
    result = post_erv.copy()
    for column in [
        "target_reached",
        "conditional_energy_pass",
        "positive_surface_direction_everywhere",
        "area_is_right_censored",
        "full_system_claim_allowed",
    ]:
        result[column] = _as_bool(result[column])
    result["plot_margin_kw"] = np.where(
        result["target_reached"], result["target_reached_screening_saving_kw"], np.nan
    )
    result["plot_status"] = "solver_or_transport_unresolved"
    result.loc[result["area_is_right_censored"], "plot_status"] = "right_censored"
    result.loc[result["target_reached"], "plot_status"] = "target_reached_negative"
    result.loc[result["conditional_energy_pass"], "plot_status"] = "conditional_positive"
    return result


def _make_direct_joint_plot(
    grouped: pd.DataFrame,
    ref: NafionReference,
    cores: dict[str, dict[str, Any]],
    output_dir: Path,
    dpi: int,
) -> list[Path]:
    x, y, z2 = _pivot(
        grouped,
        "transport_number_reference_t_w",
        "water_diffusivity_scale_vs_pfsa",
        "pass_2v_current_count",
    )
    _, _, z18 = _pivot(
        grouped,
        "transport_number_reference_t_w",
        "water_diffusivity_scale_vs_pfsa",
        "pass_1p8v_current_count",
        x,
        y,
    )
    fig, axes = plt.subplots(1, 2, figsize=(13.4, 5.7), sharex=True, sharey=True)
    cmap = mcolors.LinearSegmentedColormap.from_list("pass_count", ["#f0f3f5", "#b7d9ea", "#4d9fc6", "#155d82"])
    meshes = []
    for axis, matrix, title, subtitle, core_label in [
        (axes[0], z2, "Hard grense: 2,0 V", "178 koordinater; pass ved j=40–100 A/m²", "2.0"),
        (axes[1], z18, "Foretrukket grense: 1,8 V", "108 koordinater; pass ved j=50–100 A/m²", "1.8"),
    ]:
        mesh = axis.pcolormesh(
            _log_edges(x),
            _log_edges(y),
            matrix,
            cmap=cmap,
            vmin=0,
            vmax=11,
            shading="flat",
            edgecolors="white",
            linewidth=0.25,
        )
        meshes.append(mesh)
        core = cores[core_label]
        core_x0, core_x1 = _log_cell_span(x, core["tw_values"])
        core_y0, core_y1 = _log_cell_span(y, core["d_values"])
        axis.add_patch(
            Rectangle(
                (core_x0, core_y0),
                core_x1 - core_x0,
                core_y1 - core_y0,
                fill=False,
                edgecolor=GREEN,
                linewidth=2.0,
                linestyle="--",
                zorder=7,
            )
        )
        _mark_nafion_direct(axis, ref)
        axis.set_xscale("log")
        axis.set_yscale("log")
        axis.set_xlim(0.24, 250)
        axis.set_ylim(7e-4, 22.0)
        axis.set_title(title, color=NAVY, fontsize=13, fontweight="bold", pad=12)
        axis.text(0.5, 1.015, subtitle, transform=axis.transAxes, ha="center", va="bottom", fontsize=9, color=DARK_GREY)
        axis.set_xlabel("Effektivt vanntransporttall $t_w$  [–]")
        axis.set_xticks([0.3, 1, 2.5, 10, 20, 45, 100, 200])
        axis.set_xticklabels(["0,3", "1", "2,5", "10", "20", "45", "100", "200"])
        axis.set_yticks([0.001, 0.01, 0.1, 0.6, 1.0, 3.4, 10.0])
        axis.set_yticklabels(["0,001", "0,01", "0,1", "0,6", "1", "3,4", "10"])
        axis.text(
            0.80,
            0.035,
            (
                "Fullt observert diskret kjerne\n"
                f"$t_w$={','.join(f'{value:g}' for value in core['tw_values'])}; "
                f"j={','.join(f'{value:g}' for value in core['j_values'])}\n"
                f"{core['row_count']}/{core['row_count']} pass; alle 12 D-nivåer"
            ),
            transform=axis.transAxes,
            ha="right",
            va="bottom",
            fontsize=8.1,
            color="#0d654e",
            bbox={"facecolor": "white", "edgecolor": GREEN, "alpha": 0.92, "boxstyle": "round,pad=0.3"},
            zorder=12,
        )
        _apply_axis_style(axis)
    axes[0].set_ylabel("D-skala / intern V5-PFSA-lov  [–]")
    cbar = fig.colorbar(meshes[-1], ax=axes, fraction=0.026, pad=0.025)
    cbar.set_label("Antall av 11 undersøkte strømtettheter som består", fontsize=10)
    fig.suptitle("Direkte EO: det samtidige lavspenningsvinduet ligger langt fra Nafion", color=NAVY, fontsize=16, fontweight="bold", y=1.035)
    fig.text(
        0.5,
        -0.015,
        "Farge viser joint pass i den kanoniske 2 508-punktsstudien. Grønn ramme er et 100 % observert diskret delnett; Nafion-markørene er separate referanseakser, ikke joint pass.",
        ha="center",
        fontsize=9.2,
        color=DARK_GREY,
    )
    fig.subplots_adjust(top=0.82, bottom=0.16, left=0.08, right=0.91, wspace=0.10)
    return _save_figure(fig, output_dir, "01_direct_eo_joint_window_with_nafion", dpi)


def _make_direct_energy_plot(
    energy: pd.DataFrame,
    ref: NafionReference,
    config: dict[str, Any],
    output_dir: Path,
    dpi: int,
) -> list[Path]:
    baseline = float(config["direct_eo"]["baseline_combined_fixed_loss_v"])
    aspirational = float(config["direct_eo"]["aspirational_combined_fixed_loss_v"])
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 5.8), sharex=True, sharey=True)
    x_values = sorted(energy["transport_number_reference_t_w"].unique())
    y_values = sorted(energy["water_diffusivity_scale_vs_pfsa"].unique())
    panel_data = []
    for loss in [baseline, aspirational]:
        subset = energy.loc[np.isclose(energy["combined_fixed_loss_scenario_v"], loss)]
        _, _, matrix = _pivot(
            subset,
            "transport_number_reference_t_w",
            "water_diffusivity_scale_vs_pfsa",
            "best_modern_margin_before_receiver_kw",
            x_values,
            y_values,
        )
        panel_data.append((subset, matrix))

    norms = [
        mcolors.Normalize(vmin=-435, vmax=-115),
        mcolors.TwoSlopeNorm(vmin=-80, vcenter=0, vmax=15),
    ]
    cmaps = [plt.get_cmap("YlOrRd_r"), plt.get_cmap("RdYlGn")]
    titles = [
        ("Baseline: 0,85 V fast tap", "0 moderne-positive før receiver; best −119,846 kW"),
        ("Ambisiøst scenario: 0,20 V fast tap", "15 moderne-positive; best +14,971 kW før receiver"),
    ]
    for index, (axis, (subset, matrix), norm, cmap, title) in enumerate(zip(axes, panel_data, norms, cmaps, titles)):
        axis.set_facecolor("#eef1f3")
        mesh = axis.pcolormesh(
            _log_edges(x_values),
            _log_edges(y_values),
            np.ma.masked_invalid(matrix),
            cmap=cmap,
            norm=norm,
            shading="flat",
            edgecolors="white",
            linewidth=0.25,
        )
        positive = subset.loc[subset["modern_positive_current_count"] > 0]
        axis.scatter(
            positive["transport_number_reference_t_w"],
            positive["water_diffusivity_scale_vs_pfsa"],
            s=66,
            facecolors="none",
            edgecolors=NAVY,
            linewidths=1.5,
            zorder=8,
            label="Minst én energi-positiv strøm",
        )
        _mark_nafion_direct(axis, ref)
        axis.set_xscale("log")
        axis.set_yscale("log")
        axis.set_xlim(0.24, 250)
        axis.set_ylim(7e-4, 22.0)
        axis.set_title(title[0], color=NAVY, fontsize=13, fontweight="bold", pad=12)
        axis.text(0.5, 1.015, title[1], transform=axis.transAxes, ha="center", fontsize=9, color=DARK_GREY)
        axis.set_xlabel("Effektivt vanntransporttall $t_w$  [–]")
        axis.set_xticks([0.3, 1, 2.5, 10, 20, 45, 100, 200])
        axis.set_xticklabels(["0,3", "1", "2,5", "10", "20", "45", "100", "200"])
        axis.set_yticks([0.001, 0.01, 0.1, 0.6, 1.0, 3.4, 10.0])
        axis.set_yticklabels(["0,001", "0,01", "0,1", "0,6", "1", "3,4", "10"])
        _apply_axis_style(axis)
        cbar = fig.colorbar(mesh, ax=axis, fraction=0.046, pad=0.025)
        cbar.set_label("Beste margin mot moderne AC+ERV  [kW]", fontsize=9)
    axes[0].set_ylabel("D-skala / intern V5-PFSA-lov  [–]")
    fig.suptitle("Direkte EO: energivinduet åpner bare ved svært lave faste tap", color=NAVY, fontsize=16, fontweight="bold", y=1.035)
    fig.text(
        0.5,
        -0.012,
        "Kun celler som består 2-V-membranporten er farget. Receiver/BOP er fortsatt satt til 0 kW; blå ringer er derfor ikke fullsystempass.",
        ha="center",
        fontsize=9.2,
        color=DARK_GREY,
    )
    fig.subplots_adjust(top=0.82, bottom=0.16, left=0.08, right=0.96, wspace=0.22)
    return _save_figure(fig, output_dir, "02_direct_eo_energy_window_fixed_loss", dpi)


def _make_post_erv_plot(
    post: pd.DataFrame,
    ref: NafionReference,
    output_dir: Path,
    dpi: int,
) -> list[Path]:
    x, y, matrix = _pivot(
        post,
        "water_diffusivity_m2_s",
        "uniform_current_density_a_m2",
        "plot_margin_kw",
    )
    fig, axis = plt.subplots(figsize=(11.7, 6.8))
    axis.set_facecolor("#e8ecef")
    norm = mcolors.TwoSlopeNorm(vmin=-55, vcenter=0, vmax=55)
    mesh = axis.pcolormesh(
        _log_edges(x),
        _linear_edges(y),
        np.ma.masked_invalid(matrix),
        cmap="RdYlGn",
        norm=norm,
        shading="flat",
        edgecolors="white",
        linewidth=0.18,
    )
    censored = post.loc[post["area_is_right_censored"]]
    axis.scatter(
        censored["water_diffusivity_m2_s"],
        censored["uniform_current_density_a_m2"],
        marker="x",
        color=NAVY,
        s=22,
        linewidths=0.8,
        zorder=7,
        label="Høyresensurert ved arealtak",
    )
    d_ref_label = f"{ref.adapter_diffusivity_ref_m2_s:.2e}".replace(".", ",")
    d_exponent_label = f"{ref.adapter_diffusivity_exponent:.2f}".replace(".", ",")
    sigma_ref_label = f"{ref.adapter_conductivity_ref_s_m:.2f}".replace(".", ",")
    axis.axvline(ref.adapter_diffusivity_ref_m2_s, color=ORANGE, linewidth=2.1, zorder=6)
    axis.text(
        ref.adapter_diffusivity_ref_m2_s,
        34.1,
        (
            "Nafion V14-adapter\n"
            f"$D_{{ref}}$={d_ref_label}; $\\alpha_D$={d_exponent_label}"
        ),
        color="#9a550e",
        fontsize=9,
        fontweight="bold",
        ha="center",
        va="top",
        zorder=9,
    )
    axis.set_xscale("log")
    axis.set_xlim(_log_edges(x)[0], _log_edges(x)[-1])
    axis.set_ylim(1.5, 35.5)
    axis.set_xlabel("Diffusivitetskoeffisient $D_{ref}$ ved $a_{ref}=0{,}8$  [m²/s]")
    axis.set_ylabel("Uniform strømtetthet j  [A/m²]")
    axis.set_title("EO etter ERV: Nafion-adapterens $D_{ref}$ overlapper, men eksponenten og materialvektoren gjør ikke", color=NAVY, fontsize=14.2, fontweight="bold", pad=16)
    axis.text(
        0.5,
        1.008,
        "Farget: target nådd og screeningmargin beregnet. Grått: solver/transport uløst. Alle 1 122 rader har ulukket overflateretning.",
        transform=axis.transAxes,
        ha="center",
        va="bottom",
        fontsize=9.3,
        color=DARK_GREY,
    )
    _apply_axis_style(axis)
    cbar = fig.colorbar(mesh, ax=axis, fraction=0.035, pad=0.025)
    cbar.set_label("Betinget screeningmargin før receiver/surface closure  [kW]", fontsize=9.5)
    legend_items = [
        Line2D([0], [0], color=ORANGE, linewidth=2.1, label="Nafion V14-adapter: $D_{ref}$ ved $a_{ref}=0{,}8$"),
        Line2D([0], [0], marker="x", linestyle="none", color=NAVY, label="Høyresensurert areal"),
        Patch(facecolor="#e8ecef", edgecolor="#9aa9b3", label="Uløst solver/transport"),
    ]
    axis.legend(handles=legend_items, loc="lower left", frameon=True, framealpha=0.95, fontsize=8.8)
    fig.text(
        0.5,
        0.01,
        (
            "Koeffisientoverlapp alene er ikke materialpass: nettet holder $t_w$=100,06, "
            "$\\sigma_{ref}$=23,17 S/m, $\\alpha_D$=2 og L=36,9 µm fast; Nafion-adapteren har "
            f"$t_w$=0,3–2,5, $\\sigma_{{ref}}$={sigma_ref_label} S/m og "
            f"$\\alpha_D$={d_exponent_label}. Adapterens maksimale D-tilpasningsfeil i aktivitetsbåndet er "
            f"{100.0 * ref.adapter_diffusivity_max_abs_relative_error:.0f} %."
        ),
        ha="center",
        fontsize=9.2,
        color=DARK_GREY,
    )
    fig.subplots_adjust(top=0.85, bottom=0.17, left=0.10, right=0.91)
    return _save_figure(fig, output_dir, "03_post_erv_dj_window_with_nafion", dpi)


def _range_mark(axis: plt.Axes, y: float, low: float, high: float, color: str, label: str) -> None:
    if not (math.isfinite(low) and math.isfinite(high) and low > 0 and high > 0):
        return
    if math.isclose(low, high, rel_tol=1e-12, abs_tol=0.0):
        axis.scatter([low], [y], marker="D", s=46, color=color, edgecolor="white", linewidth=0.7, zorder=5)
    else:
        axis.plot([low, high], [y, y], color=color, linewidth=6, solid_capstyle="round", zorder=4)
        axis.scatter([low, high], [y, y], s=28, color=color, edgecolor="white", linewidth=0.6, zorder=5)
    axis.annotate(label, (math.sqrt(low * high), y), xytext=(0, 7), textcoords="offset points", ha="center", va="bottom", fontsize=7.6, color=color)


def _point_marks(axis: plt.Axes, y: float, values: Iterable[float], color: str, labels: Iterable[str]) -> None:
    values_list = list(map(float, values))
    labels_list = list(map(str, labels))
    axis.scatter(values_list, [y] * len(values_list), marker="D", s=42, color=color, edgecolor="white", linewidth=0.7, zorder=5)
    for index, (value, label) in enumerate(zip(values_list, labels_list)):
        axis.annotate(
            label,
            (value, y),
            xytext=(0, 7 + 7 * (index % 2)),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=6.8,
            color=color,
        )


def _make_property_gap_plot(
    primary: pd.DataFrame,
    post: pd.DataFrame,
    ref: NafionReference,
    output_dir: Path,
    dpi: int,
) -> list[Path]:
    direct_pass = primary.loc[_as_bool(primary["membrane_operating_pass_at_cap"])]
    post_pass = post.loc[post["conditional_energy_pass"]]
    direct_asr = float(primary["ionic_area_resistance_ohm_m2_at_lambda_ref"].iloc[0])
    specifications = [
        {
            "title": "Effektivt drag / $t_w$ [–]",
            "direct": (float(direct_pass["transport_number_reference_t_w"].min()), float(direct_pass["transport_number_reference_t_w"].max())),
            "post": (float(post["water_drag"].iloc[0]), float(post["water_drag"].iloc[0])),
            "nafion": (ref.drag_min, ref.drag_max),
            "xlim": (0.2, 160),
        },
        {
            "title": "Direkte EO: D / intern V5-lov (lik $\\lambda$) [–]",
            "direct": (float(direct_pass["water_diffusivity_scale_vs_pfsa"].min()), float(direct_pass["water_diffusivity_scale_vs_pfsa"].max())),
            "post": None,
            "nafion": (ref.direct_d_scale_min, ref.direct_d_scale_max),
            "xlim": (5e-4, 25.0),
        },
        {
            "title": "EO+ERV: $D_{ref}$ ved $a_{ref}$=0,8 [m²/s]",
            "direct": None,
            "post": (float(post_pass["water_diffusivity_m2_s"].min()), float(post_pass["water_diffusivity_m2_s"].max())),
            "nafion": (ref.adapter_diffusivity_ref_m2_s, ref.adapter_diffusivity_ref_m2_s),
            "xlim": (5e-16, 5e-9),
        },
        {
            "title": "EO+ERV: $\\sigma_{ref}$ ved $a_{ref}$=0,8 [S/m]",
            "direct": None,
            "post": (float(post["conductivity_s_m"].iloc[0]), float(post["conductivity_s_m"].iloc[0])),
            "nafion": (ref.adapter_conductivity_ref_s_m, ref.adapter_conductivity_ref_s_m),
            "xlim": (0.7, 40),
        },
        {
            "title": "Tørr tykkelse L [µm]",
            "direct": (float(primary["dry_thickness_um"].iloc[0]), float(primary["dry_thickness_um"].iloc[0])),
            "post": (float(post["dry_thickness_um"].iloc[0]), float(post["dry_thickness_um"].iloc[0])),
            "nafion": None,
            "nafion_points": ref.thicknesses_um,
            "nafion_point_labels": ref.grade_ids,
            "xlim": (10, 260),
        },
        {
            "title": "Direkte EO: membran-ASR ved $\\lambda$=8 [Ω m²]",
            "direct": (direct_asr, direct_asr),
            "post": None,
            "nafion": None,
            "nafion_points": ref.asr_values_ohm_m2,
            "nafion_point_labels": ref.grade_ids,
            "xlim": (3e-6, 3e-4),
        },
    ]
    fig, axes = plt.subplots(2, 3, figsize=(13.6, 7.2))
    y_positions = {"direct": 2.0, "post": 1.0, "nafion": 0.0}
    for axis, spec in zip(axes.flat, specifications):
        axis.set_xscale("log")
        axis.set_xlim(*spec["xlim"])
        axis.set_ylim(-0.65, 2.65)
        axis.set_yticks([0, 1, 2])
        axis.set_yticklabels(["Nafion-ref.", "EO etter ERV", "Direkte EO"])
        axis.set_title(spec["title"], color=NAVY, fontsize=11.2, fontweight="bold", pad=9)
        if spec["direct"]:
            _range_mark(axis, y_positions["direct"], *spec["direct"], BLUE, f"{spec['direct'][0]:.3g}" if math.isclose(*spec["direct"]) else f"{spec['direct'][0]:.3g}–{spec['direct'][1]:.3g}")
        if spec["post"]:
            _range_mark(axis, y_positions["post"], *spec["post"], TEAL, f"{spec['post'][0]:.3g}" if math.isclose(*spec["post"]) else f"{spec['post'][0]:.3g}–{spec['post'][1]:.3g}")
        if spec["nafion"]:
            _range_mark(axis, y_positions["nafion"], *spec["nafion"], ORANGE, f"{spec['nafion'][0]:.3g}" if math.isclose(*spec["nafion"]) else f"{spec['nafion'][0]:.3g}–{spec['nafion'][1]:.3g}")
        else:
            _point_marks(axis, y_positions["nafion"], spec["nafion_points"], ORANGE, spec["nafion_point_labels"])
        _apply_axis_style(axis)
        axis.tick_params(axis="both", labelsize=8.5)
    fig.suptitle("Parameter-for-parameter-gap mot Nafion: $D_{ref}$ overlapper, drag og $\\sigma_{ref}$ gjør ikke", color=NAVY, fontsize=15.5, fontweight="bold", y=0.995)
    legend = [
        Line2D([0], [0], color=BLUE, linewidth=6, label="Direkte EO: 2-V joint pass eller fast screenkoordinat"),
        Line2D([0], [0], color=TEAL, linewidth=6, label="EO etter ERV: betinget D-j-pass eller fast screenkoordinat"),
        Line2D(
            [0],
            [0],
            color=ORANGE,
            linewidth=6,
            label="Nafion: V14-adapterpunkt eller diskret grad/litteraturreferanse",
        ),
    ]
    fig.legend(handles=legend, loc="lower center", ncol=3, frameon=False, fontsize=8.7, bbox_to_anchor=(0.5, 0.035))
    fig.text(
        0.5,
        0.005,
        (
            "Post-ERV har $\\alpha_D$=2 og $\\alpha_\\sigma$=4; Nafion-adapteren har "
            f"$\\alpha_D$={ref.adapter_diffusivity_exponent:.2f} og "
            f"$\\alpha_\\sigma$={ref.adapter_conductivity_exponent:.2f}. "
            f"Maks. adapterfeil: D {100.0 * ref.adapter_diffusivity_max_abs_relative_error:.0f} %, "
            f"$\\sigma$ {100.0 * ref.adapter_conductivity_max_abs_relative_error:.0f} %. "
            "Punkter og intervaller er ikke toleransegrenser eller en materialoppskrift."
        ),
        ha="center",
        fontsize=9.2,
        color=DARK_GREY,
    )
    fig.subplots_adjust(top=0.88, bottom=0.16, left=0.10, right=0.98, hspace=0.42, wspace=0.34)
    return _save_figure(fig, output_dir, "04_simultaneous_property_gap_vs_nafion", dpi)


def _make_nafion_law_comparison_plot(
    config: dict[str, Any],
    tables: dict[str, Any],
    ref: NafionReference,
    output_dir: Path,
    dpi: int,
) -> list[Path]:
    module = tables["nafion_module"]
    temperature_k = float(config["nafion_reference"]["temperature_c"]) + 273.15
    activity = np.linspace(0.0, 1.0, 501)
    lam = np.asarray(module.nafion_lambda_vapour(activity), dtype=float)
    lambda_low = float(config["nafion_reference"]["lambda_scale_interval_min"])
    lambda_high = float(config["nafion_reference"]["lambda_scale_interval_max"])
    lambda_ref = float(config["nafion_reference"]["lambda_reference"])
    lambda_axis = np.linspace(lambda_low, lambda_high, 501)

    internal_d = 1.0e-10 * (0.12 + (np.maximum(lambda_axis, 0.05) / 14.0) ** 2.6)
    low = 3.1e-3 * lambda_axis * (np.exp(0.28 * lambda_axis) - 1.0) * np.exp(-2436.0 / temperature_k)
    high = 4.17e-4 * lambda_axis * (161.0 * np.exp(-lambda_axis) + 1.0) * np.exp(-2436.0 / temperature_k)
    nafion_d = np.where(lambda_axis < 3.0, low, high) * 1e-4
    d_scale = nafion_d / internal_d

    fig, axes = plt.subplots(1, 2, figsize=(13.2, 5.3))
    axes[0].plot(activity, lam, color=ORANGE, linewidth=2.6, label="Nafion/PFSA-litteratur: 1,00× sorpsjon")
    axes[0].plot(activity, 1.25 * lam, color=BLUE, linewidth=2.6, label="Direkte-EO-screen: 1,25× sorpsjon")
    axes[0].axhline(4.0, color=DARK_GREY, linestyle="--", linewidth=1.1, label="Deklarert λ=4 domenegrense")
    for a in [0.3, 0.5, 0.8]:
        value = float(module.nafion_lambda_vapour(a))
        axes[0].scatter([a], [value], color=ORANGE, s=30, zorder=5)
        axes[0].annotate(f"λ={value:.2f}", (a, value), xytext=(4, 6), textcoords="offset points", fontsize=8, color="#9a550e")
    axes[0].set_xlabel("Vannaktivitet $a_w$  [–]")
    axes[0].set_ylabel("Vanninnhold λ  [mol H₂O/mol SO₃H]")
    axes[0].set_xlim(0, 1)
    axes[0].set_ylim(0, max(18.2, float((1.25 * lam).max()) * 1.03))
    axes[0].set_title("Sorpsjon: V5 bruker en hypotetisk 1,25×-kurve", color=NAVY, fontsize=12.4, fontweight="bold")
    axes[0].legend(loc="upper left", fontsize=8.4, frameon=True)
    _apply_axis_style(axes[0])

    axes[1].fill_between(lambda_axis, 0.001, 0.6, color=BLUE, alpha=0.17, label="V5 undersøkt D-skala: 0,001–0,6")
    axes[1].plot(lambda_axis, d_scale, color=ORANGE, linewidth=2.8, label="Nafion D / intern V5-basis")
    axes[1].scatter([lambda_ref], [ref.direct_d_scale_at_lambda_ref], color=ORANGE, edgecolor="white", linewidth=0.8, s=62, zorder=6)
    axes[1].annotate(
        f"λ=8: {ref.direct_d_scale_at_lambda_ref:.3f}×",
        (lambda_ref, ref.direct_d_scale_at_lambda_ref),
        xytext=(9, -3),
        textcoords="offset points",
        fontsize=9,
        color="#9a550e",
        fontweight="bold",
    )
    axes[1].set_yscale("log")
    axes[1].set_xlim(lambda_low, lambda_high)
    axes[1].set_ylim(7e-4, 22)
    axes[1].set_xlabel("Lokalt vanninnhold λ  [–]")
    axes[1].set_ylabel("Diffusivitetsforhold  [–]")
    axes[1].set_title("Diffusjon ved lik λ: Nafion-korrelasjonen ligger over V5-nettet", color=NAVY, fontsize=12.4, fontweight="bold")
    axes[1].legend(loc="lower right", fontsize=8.4, frameon=True)
    _apply_axis_style(axes[1])
    fig.suptitle("Hvor Nafion-referansen faktisk ligger mot den interne V5-normaliseringen", color=NAVY, fontsize=15.4, fontweight="bold", y=1.01)
    fig.text(
        0.5,
        -0.015,
        "Nafion er en litteraturkorrelasjon ved 32 °C, ikke batchmåling. D-forholdet er en lik-λ kryssmodell-diagnose, ikke en simulert Nafion-koordinat.",
        ha="center",
        fontsize=9.2,
        color=DARK_GREY,
    )
    fig.subplots_adjust(top=0.84, bottom=0.16, left=0.08, right=0.98, wspace=0.25)
    return _save_figure(fig, output_dir, "05_nafion_reference_vs_v5_internal_laws", dpi)


def _make_broad_6axis_plot(
    broad: pd.DataFrame,
    core: dict[str, Any],
    ref: NafionReference,
    output_dir: Path,
    dpi: int,
) -> list[Path]:
    cmap = mcolors.LinearSegmentedColormap.from_list(
        "pass_fraction", ["#eef1f3", "#c5deea", "#69acc8", "#17658b"]
    )
    fig, axes = plt.subplots(1, 3, figsize=(14.8, 5.8))

    panels = [
        {
            "axis": axes[0],
            "x": "transport_number_reference_t_w",
            "y": "current_density_a_m2",
            "title": "Transporttall mot strømtetthet",
            "xlabel": "Effektivt vanntransporttall $t_w$  [–]",
            "ylabel": "Strømtetthet j  [A/m²]",
            "x_edges": _log_edges,
            "y_edges": _linear_edges,
            "xscale": "log",
        },
        {
            "axis": axes[1],
            "x": "dry_thickness_um",
            "y": "ionic_area_resistance_ohm_m2_at_lambda_ref",
            "title": "Tykkelse mot arealmotstand",
            "xlabel": "Tørr tykkelse L  [µm]",
            "ylabel": "ASR ved $\\lambda_{ref}$  [Ω m²]",
            "x_edges": _linear_edges,
            "y_edges": _log_edges,
            "yscale": "log",
        },
        {
            "axis": axes[2],
            "x": "water_diffusivity_scale_vs_pfsa",
            "y": "retention_factor_vs_pfsa_sorption",
            "title": "Diffusjonsskala mot sorpsjonsretensjon",
            "xlabel": "D / intern V5-lov  [–]",
            "ylabel": "Sorpsjonsretensjon / PFSA  [–]",
            "x_edges": _log_edges,
            "y_edges": _linear_edges,
            "xscale": "log",
        },
    ]
    meshes: list[Any] = []
    for panel in panels:
        grouped = (
            broad.groupby([panel["x"], panel["y"]], as_index=False)
            .agg(pass_fraction_1p8v=("membrane_replay_pass_1p8v", "mean"))
        )
        x, y, matrix = _pivot(grouped, panel["x"], panel["y"], "pass_fraction_1p8v")
        axis = panel["axis"]
        mesh = axis.pcolormesh(
            panel["x_edges"](x),
            panel["y_edges"](y),
            matrix,
            cmap=cmap,
            vmin=0.0,
            vmax=1.0,
            shading="flat",
            edgecolors="white",
            linewidth=0.45,
        )
        meshes.append(mesh)
        for y_index, y_value in enumerate(y):
            for x_index, x_value in enumerate(x):
                value = matrix[y_index, x_index]
                if math.isfinite(value):
                    axis.text(
                        x_value,
                        y_value,
                        f"{100 * value:.0f}",
                        ha="center",
                        va="center",
                        fontsize=6.6,
                        color="white" if value >= 0.55 else NAVY,
                        zorder=5,
                    )
        if panel.get("xscale"):
            axis.set_xscale(panel["xscale"])
        if panel.get("yscale"):
            axis.set_yscale(panel["yscale"])
        axis.set_title(panel["title"], color=NAVY, fontsize=11.5, fontweight="bold", pad=10)
        axis.set_xlabel(panel["xlabel"])
        axis.set_ylabel(panel["ylabel"])
        _apply_axis_style(axis)

    # Panel 1: the Nafion drag envelope is independent of current density.
    axes[0].axvspan(ref.drag_min, ref.drag_max, color=ORANGE, alpha=0.18, zorder=3)
    axes[0].axvline(ref.drag_min, color=ORANGE, linewidth=1.1, zorder=4)
    axes[0].axvline(ref.drag_max, color=ORANGE, linewidth=1.1, zorder=4)
    axes[0].set_xlim(0.24, 190)
    axes[0].set_ylim(25, 275)
    axes[0].text(0.38, 260, "Nafion $t_w$\n0,3–2,5", color="#9a550e", fontsize=8.4, fontweight="bold")
    tw0, tw1 = _log_cell_span(broad["transport_number_reference_t_w"].unique(), core["core_tw"])
    j0, j1 = _linear_cell_span(broad["current_density_a_m2"].unique(), core["core_j"])
    axes[0].add_patch(Rectangle((tw0, j0), tw1 - tw0, j1 - j0, fill=False, edgecolor=GREEN, linewidth=2.2, linestyle="--", zorder=7))

    # Panel 2: commercial grade points use L/sigma at lambda=8.
    for index, (grade, thickness, asr) in enumerate(zip(ref.grade_ids, ref.thicknesses_um, ref.asr_values_ohm_m2)):
        axes[1].scatter([thickness], [asr], marker="D", s=48, color=ORANGE, edgecolor="white", linewidth=0.7, zorder=8)
        axes[1].annotate(grade, (thickness, asr), xytext=(0, 7 + 6 * (index % 2)), textcoords="offset points", ha="center", fontsize=7.0, color="#9a550e", zorder=9)
    axes[1].set_xlim(10, 200)
    axes[1].set_ylim(3e-6, 2e-4)
    l0, l1 = _linear_cell_span(broad["dry_thickness_um"].unique(), core["core_thickness"])
    a0, a1 = _log_cell_span(broad["ionic_area_resistance_ohm_m2_at_lambda_ref"].unique(), core["core_asr"])
    axes[1].add_patch(Rectangle((l0, a0), l1 - l0, a1 - a0, fill=False, edgecolor=GREEN, linewidth=2.2, linestyle="--", zorder=7))

    # Panel 3: cross-schema Nafion D mapping and sorption factor are reference axes only.
    axes[2].plot([ref.direct_d_scale_min, ref.direct_d_scale_max], [1.0, 1.0], color=ORANGE, linewidth=3.0, solid_capstyle="round", zorder=8)
    axes[2].scatter([ref.direct_d_scale_at_lambda_ref], [1.0], color=ORANGE, edgecolor="white", linewidth=0.7, s=52, zorder=9)
    axes[2].annotate("Nafion D/V5 (lik $\\lambda$)", (ref.direct_d_scale_at_lambda_ref, 1.0), xytext=(-5, -17), textcoords="offset points", ha="right", fontsize=7.4, color="#9a550e")
    axes[2].set_xlim(0.0015, 22)
    axes[2].set_ylim(0.88, 1.62)
    d0, d1 = _log_cell_span(broad["water_diffusivity_scale_vs_pfsa"].unique(), core["core_d"])
    r0, r1 = _linear_cell_span(broad["retention_factor_vs_pfsa_sorption"].unique(), core["core_retention"])
    axes[2].add_patch(Rectangle((d0, r0), d1 - d0, r1 - r0, fill=False, edgecolor=GREEN, linewidth=2.2, linestyle="--", zorder=7))

    cbar_axis = fig.add_axes([0.915, 0.205, 0.013, 0.625])
    cbar = fig.colorbar(meshes[-1], cax=cbar_axis)
    cbar.set_label("Marginal passandel ved 1,8 V  [–]", fontsize=9.5)
    legend = [
        Patch(facecolor="none", edgecolor=GREEN, linewidth=2.0, linestyle="--", label="Projeksjon av verifisert 384/384 joint kjerne"),
        Patch(facecolor=ORANGE, edgecolor=ORANGE, alpha=0.25, label="Nafion off-axis referanse"),
    ]
    fig.legend(handles=legend, loc="lower center", ncol=2, frameon=False, fontsize=8.8, bbox_to_anchor=(0.5, 0.055))
    fig.suptitle("Bredere 6-akse-replay: et fullt observert 1,8-V-delnett finnes, men krever høyt $t_w$", color=NAVY, fontsize=15.5, fontweight="bold", y=1.015)
    fig.text(
        0.5,
        0.012,
        "Tall i cellene er passandel i prosent, ikke sannsynlighet eller kontinuerlig toleranse. Grønn kjerne: $t_w$=20; j=100/150; alle 6 D-, 4 ASR- og 4 L-nivåer; retensjon=1,25/1,50.",
        ha="center",
        fontsize=9.0,
        color=DARK_GREY,
    )
    fig.subplots_adjust(top=0.83, bottom=0.19, left=0.065, right=0.885, wspace=0.31)
    return _save_figure(fig, output_dir, "06_broad_6axis_direct_eo_window_with_nafion", dpi)


def _build_parameter_register(
    primary: pd.DataFrame,
    fixed_loss: pd.DataFrame,
    broad: pd.DataFrame,
    broad_core: dict[str, Any],
    post: pd.DataFrame,
    ref: NafionReference,
) -> pd.DataFrame:
    direct_pass = primary.loc[_as_bool(primary["membrane_operating_pass_at_cap"])]
    direct_preferred = primary.loc[_as_bool(primary["preferred_membrane_operating_pass"])]
    post_pass = post.loc[post["conditional_energy_pass"]]
    broad_pass = broad.loc[broad["membrane_replay_pass_1p8v"]]
    rows = [
        ("direct_eo_2v_joint", "effective_water_transport_number", direct_pass["transport_number_reference_t_w"].min(), direct_pass["transport_number_reference_t_w"].max(), "-", "marginal extrema among joint pass rows; not a filled box"),
        ("direct_eo_2v_joint", "water_diffusivity_scale_vs_pfsa", direct_pass["water_diffusivity_scale_vs_pfsa"].min(), direct_pass["water_diffusivity_scale_vs_pfsa"].max(), "-", "marginal extrema among joint pass rows; correlated with t_w and j; not a box"),
        ("direct_eo_2v_joint", "current_density", direct_pass["current_density_a_m2"].min(), direct_pass["current_density_a_m2"].max(), "A/m2", "marginal sampling-axis extrema among joint pass rows; not a box"),
        ("direct_eo_1p8v_joint", "effective_water_transport_number", direct_preferred["transport_number_reference_t_w"].min(), direct_preferred["transport_number_reference_t_w"].max(), "-", "marginal extrema among preferred-voltage joint pass rows; not a box"),
        ("direct_eo_1p8v_joint", "current_density", direct_preferred["current_density_a_m2"].min(), direct_preferred["current_density_a_m2"].max(), "A/m2", "marginal sampling-axis extrema among preferred-voltage pass rows; not a box"),
        ("direct_eo_fixed_screen", "dry_thickness", primary["dry_thickness_um"].iloc[0], primary["dry_thickness_um"].iloc[0], "um", "fixed screen coordinate, not a tolerance"),
        ("direct_eo_fixed_screen", "ionic_area_resistance", primary["ionic_area_resistance_ohm_m2_at_lambda_ref"].iloc[0], primary["ionic_area_resistance_ohm_m2_at_lambda_ref"].iloc[0], "ohm m2", "fixed screen coordinate, not a tolerance"),
        ("direct_eo_fixed_screen", "retention_factor_vs_pfsa", primary["retention_factor_vs_pfsa_sorption"].iloc[0], primary["retention_factor_vs_pfsa_sorption"].iloc[0], "-", "fixed screen coordinate, not a tolerance"),
        ("direct_eo_broad_1p8v_marginal", "effective_water_transport_number", broad_pass["transport_number_reference_t_w"].min(), broad_pass["transport_number_reference_t_w"].max(), "-", "marginal pass support in global-v53 replay; not a joint box"),
        ("direct_eo_broad_1p8v_marginal", "current_density", broad_pass["current_density_a_m2"].min(), broad_pass["current_density_a_m2"].max(), "A/m2", "sampling/control axis in marginal pass support"),
        ("direct_eo_broad_1p8v_marginal", "water_diffusivity_scale_vs_pfsa", broad_pass["water_diffusivity_scale_vs_pfsa"].min(), broad_pass["water_diffusivity_scale_vs_pfsa"].max(), "-", "marginal pass support; not a joint box"),
        ("direct_eo_broad_1p8v_marginal", "ionic_area_resistance", broad_pass["ionic_area_resistance_ohm_m2_at_lambda_ref"].min(), broad_pass["ionic_area_resistance_ohm_m2_at_lambda_ref"].max(), "ohm m2", "marginal pass support; not a joint box"),
        ("direct_eo_broad_1p8v_marginal", "dry_thickness", broad_pass["dry_thickness_um"].min(), broad_pass["dry_thickness_um"].max(), "um", "marginal pass support; not a joint box"),
        ("direct_eo_broad_1p8v_marginal", "retention_factor_vs_pfsa", broad_pass["retention_factor_vs_pfsa_sorption"].min(), broad_pass["retention_factor_vs_pfsa_sorption"].max(), "-", "marginal pass support; retention 1.0 has no replay pass"),
        ("direct_eo_broad_1p8v_full_discrete_core", "effective_water_transport_number", broad_core["core_tw"][0], broad_core["core_tw"][0], "-", "joint 384/384 discrete core"),
        ("direct_eo_broad_1p8v_full_discrete_core", "current_density", min(broad_core["core_j"]), max(broad_core["core_j"]), "A/m2", "two sampled values in joint 384/384 core"),
        ("direct_eo_broad_1p8v_full_discrete_core", "retention_factor_vs_pfsa", min(broad_core["core_retention"]), max(broad_core["core_retention"]), "-", "two sampled values in joint 384/384 core"),
        ("post_erv_conditional_dj", "water_diffusivity_ref_at_activity_0p8", post_pass["water_diffusivity_m2_s"].min(), post_pass["water_diffusivity_m2_s"].max(), "m2/s", "conditional D-j screening pass; coefficient at a_ref=0.8 with alpha_D=2; full-system unknown"),
        ("post_erv_conditional_dj", "current_density", post_pass["uniform_current_density_a_m2"].min(), post_pass["uniform_current_density_a_m2"].max(), "A/m2", "sampling/control axis; no 21 A/m2 gate"),
        ("post_erv_fixed_screen", "effective_water_transport_number", post["water_drag"].iloc[0], post["water_drag"].iloc[0], "-", "fixed inverse-design coordinate"),
        ("post_erv_fixed_screen", "conductivity_ref_at_activity_0p8", post["conductivity_s_m"].iloc[0], post["conductivity_s_m"].iloc[0], "S/m", "fixed inverse-design coefficient at a_ref=0.8 with alpha_sigma=4"),
        ("post_erv_fixed_screen", "dry_thickness", post["dry_thickness_um"].iloc[0], post["dry_thickness_um"].iloc[0], "um", "fixed inverse-design coordinate"),
        ("post_erv_fixed_screen", "total_reference_area_resistance_at_activity_0p8", post["total_reference_area_resistance_ohm_m2"].iloc[0], post["total_reference_area_resistance_ohm_m2"].iloc[0], "ohm m2", "fixed L/sigma_ref plus 1e-5 ohm m2 series ASR at a_ref=0.8; not a lambda=8 membrane ASR"),
        ("nafion_reference", "effective_water_transport_number", ref.drag_min, ref.drag_max, "-", "declared low/nominal/high drag envelope"),
        ("nafion_reference", "water_diffusivity_scale_vs_internal_v5_law", ref.direct_d_scale_min, ref.direct_d_scale_max, "-", "equal-lambda cross-schema diagnostic; not a simulated joint coordinate"),
        ("nafion_reference", "water_diffusivity", ref.diffusivity_min_m2_s, ref.diffusivity_max_m2_s, "m2/s", "literature function over declared activity interval"),
        ("nafion_reference", "conductivity", ref.conductivity_min_s_m, ref.conductivity_max_s_m, "S/m", "literature function over declared activity interval"),
        ("nafion_v14_adapter", "water_diffusivity_ref_at_activity_0p8", ref.adapter_diffusivity_ref_m2_s, ref.adapter_diffusivity_ref_m2_s, "m2/s", f"power-law fit coefficient at a_ref=0.8; alpha_D={ref.adapter_diffusivity_exponent:.6g}; max relative fit error={ref.adapter_diffusivity_max_abs_relative_error:.6g}; not raw D(a)"),
        ("nafion_v14_adapter", "conductivity_ref_at_activity_0p8", ref.adapter_conductivity_ref_s_m, ref.adapter_conductivity_ref_s_m, "S/m", f"power-law fit coefficient at a_ref=0.8; alpha_sigma={ref.adapter_conductivity_exponent:.6g}; max relative fit error={ref.adapter_conductivity_max_abs_relative_error:.6g}; not raw sigma(a)"),
        ("nafion_reference", "dry_thickness", ref.thickness_min_um, ref.thickness_max_um, "um", "NR211/NR212/N115/N117 nominal grade envelope"),
        ("nafion_reference", "area_resistance_L_over_sigma_at_lambda_8", ref.asr_min_ohm_m2, ref.asr_max_ohm_m2, "ohm m2", "four discrete grade values derived at fixed lambda=8; not an activity envelope"),
    ]
    return pd.DataFrame(rows, columns=["evidence_plane", "parameter", "lower", "upper", "unit", "interpretation"])


def _summary_text(metrics: dict[str, Any]) -> str:
    return f"""# Material parameter windows with Nafion reference v1

## Decision reading

- **Direct EO, 2 V:** {metrics['direct_2v_passes']} of {metrics['direct_coordinates']} physical coordinates pass the membrane operating gate. The marginal joint-pass span is t_w={metrics['direct_2v_tw_min']:.0f}–{metrics['direct_2v_tw_max']:.0f}, D/V5={metrics['direct_2v_d_min']:.3g}–{metrics['direct_2v_d_max']:.3g} and j={metrics['direct_2v_j_min']:.0f}–{metrics['direct_2v_j_max']:.0f} A/m2; it is not a fully passing box. The verified all-D discrete core is t_w={metrics['direct_2v_core_tw']}, j={metrics['direct_2v_core_j']} A/m2 ({metrics['direct_2v_core_rows']}/{metrics['direct_2v_core_rows']} rows).
- **Direct EO, preferred 1.8 V:** {metrics['direct_1p8v_passes']} rows pass; the marginal span is t_w={metrics['direct_1p8v_tw_min']:.0f}–{metrics['direct_1p8v_tw_max']:.0f} and j={metrics['direct_1p8v_j_min']:.0f}–{metrics['direct_1p8v_j_max']:.0f} A/m2. The verified all-D discrete core is t_w={metrics['direct_1p8v_core_tw']}, j={metrics['direct_1p8v_core_j']} A/m2 ({metrics['direct_1p8v_core_rows']}/{metrics['direct_1p8v_core_rows']} rows).
- **Broader six-axis replay:** {metrics['direct_broad_1p8v_passes']} of {metrics['direct_broad_rows']} global-v53 rows pass the replayed 1.8 V membrane gate. A verified {metrics['direct_broad_core_rows']}/{metrics['direct_broad_core_rows']} discrete core has t_w=20, j=100/150 A/m2, every tested D scale, ASR and thickness, and retention=1.25/1.50. This is discrete support, not a continuous tolerance; retention=1.0 has zero pass rows.
- **Nafion reference:** declared drag envelope t_w={metrics['nafion_drag_min']:.1f}–{metrics['nafion_drag_max']:.1f}, grade thickness {metrics['nafion_thickness_min_um']:.0f}–{metrics['nafion_thickness_max_um']:.0f} um and literature D={metrics['nafion_d_min']:.3e}–{metrics['nafion_d_max']:.3e} m2/s over the declared activity interval. The equal-lambda mapping to the internal V5 D-law is {metrics['nafion_direct_d_scale_min']:.2f}–{metrics['nafion_direct_d_scale_max']:.2f}; this is a cross-schema diagnostic, not a joint Nafion simulation. Nafion does not overlap the direct-EO drag requirement.
- **Direct-EO energy:** baseline 0.85 V combined fixed loss has {metrics['direct_baseline_positive']} modern-comparator-positive rows before receiver. The 0.20 V deterministic scenario has {metrics['direct_0p2_positive']} positive rows, but this is still before receiver/BOP.
- **EO after ERV:** {metrics['post_conditional_passes']} of {metrics['post_rows']} dense D-j rows are conditionally energy-positive. On the same V14 coefficient basis, Nafion's fitted D_ref={metrics['nafion_adapter_d_ref']:.3e} m2/s at a_ref={metrics['nafion_adapter_reference_activity']:.1f} lies on the sampled D axis. This is not a material-vector match: post-ERV fixes t_w={metrics['post_drag']:.2f}, sigma_ref={metrics['post_conductivity']:.2f} S/m, alpha_D=2, alpha_sigma=4 and L={metrics['post_thickness_um']:.1f} um, whereas the Nafion adapter has sigma_ref={metrics['nafion_adapter_conductivity_ref']:.2f} S/m, alpha_D={metrics['nafion_adapter_d_exponent']:.2f} and alpha_sigma={metrics['nafion_adapter_conductivity_exponent']:.2f}. Maximum relative adapter-fit errors over the declared activity interval are {100.0 * metrics['nafion_adapter_d_max_relative_error']:.0f}% for D and {100.0 * metrics['nafion_adapter_conductivity_max_relative_error']:.0f}% for conductivity.

## Claim boundary

These plots are material-screening and experiment-planning figures. They do not validate Nafion for the HeiQ device, do not establish a continuous material tolerance, and do not authorize a full-system saving claim. Fixed screening coordinates and marginal ranges must not be combined into an unmeasured material vector.
"""


def run(config_path: Path, output_dir: Path) -> dict[str, Any]:
    config_path = config_path.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    config, source_paths, tables = _load_inputs(config_path)
    ref = _build_nafion_reference(config, tables)
    nafion_curve, nafion_cases, nafion_fit_audit = _build_nafion_reference_tables(config, tables, ref)
    primary, direct_joint = _direct_joint_register(config, tables["direct_cap"])
    cores = _verify_declared_direct_cores(config, primary)
    direct_energy = _direct_energy_register(config, tables["direct_fixed_loss"])
    broad, broad_core = _broad_direct_register(tables["direct_broad"])
    post = _post_register(tables["post_erv"])

    direct_2v = primary.loc[_as_bool(primary["membrane_operating_pass_at_cap"])]
    direct_18 = primary.loc[_as_bool(primary["preferred_membrane_operating_pass"])]
    baseline_loss = float(config["direct_eo"]["baseline_combined_fixed_loss_v"])
    aspirational_loss = float(config["direct_eo"]["aspirational_combined_fixed_loss_v"])
    fixed = tables["direct_fixed_loss"].copy()
    baseline_rows = fixed.loc[np.isclose(fixed["combined_fixed_loss_scenario_v"], baseline_loss)]
    aspirational_rows = fixed.loc[np.isclose(fixed["combined_fixed_loss_scenario_v"], aspirational_loss)]
    baseline_positive = int(_as_bool(baseline_rows["scenario_modern_positive_before_receiver_pass"]).sum())
    aspirational_positive = int(_as_bool(aspirational_rows["scenario_modern_positive_before_receiver_pass"]).sum())
    post_pass = post.loc[post["conditional_energy_pass"]]

    metrics = {
        "direct_coordinates": int(len(primary)),
        "direct_2v_passes": int(len(direct_2v)),
        "direct_1p8v_passes": int(len(direct_18)),
        "direct_baseline_positive": baseline_positive,
        "direct_0p2_positive": aspirational_positive,
        "direct_2v_tw_min": float(direct_2v["transport_number_reference_t_w"].min()),
        "direct_2v_tw_max": float(direct_2v["transport_number_reference_t_w"].max()),
        "direct_2v_d_min": float(direct_2v["water_diffusivity_scale_vs_pfsa"].min()),
        "direct_2v_d_max": float(direct_2v["water_diffusivity_scale_vs_pfsa"].max()),
        "direct_2v_j_min": float(direct_2v["current_density_a_m2"].min()),
        "direct_2v_j_max": float(direct_2v["current_density_a_m2"].max()),
        "direct_1p8v_tw_min": float(direct_18["transport_number_reference_t_w"].min()),
        "direct_1p8v_tw_max": float(direct_18["transport_number_reference_t_w"].max()),
        "direct_1p8v_j_min": float(direct_18["current_density_a_m2"].min()),
        "direct_1p8v_j_max": float(direct_18["current_density_a_m2"].max()),
        "direct_2v_core_tw": ",".join(f"{value:g}" for value in cores["2.0"]["tw_values"]),
        "direct_2v_core_j": ",".join(f"{value:g}" for value in cores["2.0"]["j_values"]),
        "direct_2v_core_rows": cores["2.0"]["row_count"],
        "direct_1p8v_core_tw": ",".join(f"{value:g}" for value in cores["1.8"]["tw_values"]),
        "direct_1p8v_core_j": ",".join(f"{value:g}" for value in cores["1.8"]["j_values"]),
        "direct_1p8v_core_rows": cores["1.8"]["row_count"],
        "direct_broad_rows": int(len(broad)),
        "direct_broad_2v_passes": int(broad["membrane_replay_pass_2v"].sum()),
        "direct_broad_1p8v_passes": int(broad["membrane_replay_pass_1p8v"].sum()),
        "direct_broad_core_rows": broad_core["core_rows"],
        "direct_broad_retention_1p0_passes": int(
            broad.loc[np.isclose(broad["retention_factor_vs_pfsa_sorption"], 1.0), "membrane_replay_pass_1p8v"].sum()
        ),
        "post_rows": int(len(post)),
        "post_conditional_passes": int(post["conditional_energy_pass"].sum()),
        "post_surface_direction_passes": int(post["positive_surface_direction_everywhere"].sum()),
        "post_drag": float(post["water_drag"].iloc[0]),
        "post_conductivity": float(post["conductivity_s_m"].iloc[0]),
        "post_thickness_um": float(post["dry_thickness_um"].iloc[0]),
        "nafion_drag_min": ref.drag_min,
        "nafion_drag_max": ref.drag_max,
        "nafion_d_min": ref.diffusivity_min_m2_s,
        "nafion_d_max": ref.diffusivity_max_m2_s,
        "nafion_conductivity_min": ref.conductivity_min_s_m,
        "nafion_conductivity_max": ref.conductivity_max_s_m,
        "nafion_thickness_min_um": ref.thickness_min_um,
        "nafion_thickness_max_um": ref.thickness_max_um,
        "nafion_asr_min": ref.asr_min_ohm_m2,
        "nafion_asr_max": ref.asr_max_ohm_m2,
        "nafion_direct_d_scale_min": ref.direct_d_scale_min,
        "nafion_direct_d_scale_max": ref.direct_d_scale_max,
        "nafion_direct_d_scale_at_lambda_8": ref.direct_d_scale_at_lambda_ref,
        "nafion_d_at_lambda_8_m2_s": ref.diffusivity_at_lambda_ref_m2_s,
        "nafion_conductivity_at_lambda_8_s_m": ref.conductivity_at_lambda_ref_s_m,
        "nafion_adapter_reference_activity": ref.adapter_reference_activity,
        "nafion_adapter_d_ref": ref.adapter_diffusivity_ref_m2_s,
        "nafion_adapter_d_exponent": ref.adapter_diffusivity_exponent,
        "nafion_adapter_d_max_relative_error": ref.adapter_diffusivity_max_abs_relative_error,
        "nafion_adapter_conductivity_ref": ref.adapter_conductivity_ref_s_m,
        "nafion_adapter_conductivity_exponent": ref.adapter_conductivity_exponent,
        "nafion_adapter_conductivity_max_relative_error": ref.adapter_conductivity_max_abs_relative_error,
        "nafion_activity_curve_d_scale_min": float(nafion_curve["nafion_d_over_internal_v5_at_equal_lambda"].min()),
        "nafion_activity_curve_d_scale_max": float(nafion_curve["nafion_d_over_internal_v5_at_equal_lambda"].max()),
        "nafion_case_count": ref.case_count,
        "nafion_grade_count": ref.grade_count,
        "full_system_claim_allowed": False,
    }

    expected = config["expected"]
    checks = [
        ("direct_physical_coordinates", metrics["direct_coordinates"] == expected["direct_physical_coordinates"]),
        ("direct_2v_membrane_passes", metrics["direct_2v_passes"] == expected["direct_2v_membrane_passes"]),
        ("direct_1p8v_membrane_passes", metrics["direct_1p8v_passes"] == expected["direct_1p8v_membrane_passes"]),
        ("direct_baseline_modern_positive", baseline_positive == expected["direct_baseline_modern_positive_before_receiver"]),
        ("direct_0p2v_loss_modern_positive", aspirational_positive == expected["direct_0p2v_loss_modern_positive_before_receiver"]),
        ("direct_broad_global_v53_rows", metrics["direct_broad_rows"] == expected["direct_broad_global_v53_rows"]),
        ("direct_broad_2v_membrane_passes", metrics["direct_broad_2v_passes"] == expected["direct_broad_2v_membrane_passes"]),
        ("direct_broad_1p8v_membrane_passes", metrics["direct_broad_1p8v_passes"] == expected["direct_broad_1p8v_membrane_passes"]),
        ("direct_broad_1p8v_full_core", metrics["direct_broad_core_rows"] == expected["direct_broad_1p8v_full_core_rows"]),
        ("direct_broad_retention_1p0_has_no_pass", metrics["direct_broad_retention_1p0_passes"] == 0),
        ("post_erv_dense_rows", metrics["post_rows"] == expected["post_erv_dense_rows"]),
        ("post_erv_conditional_energy_passes", metrics["post_conditional_passes"] == expected["post_erv_conditional_energy_passes"]),
        ("post_erv_surface_direction_passes", metrics["post_surface_direction_passes"] == expected["post_erv_positive_surface_direction_passes"]),
        ("nafion_reference_cases", ref.case_count == expected["nafion_reference_cases"]),
        ("nafion_grade_count", ref.grade_count == expected["nafion_grade_count"]),
        ("full_system_claim_disabled", config["claim_boundary"]["full_system_claim_allowed"] is False),
        (
            "direct_current_is_not_acceptance_gate",
            any(
                row.get("check") == "no_current_density_acceptance_limit" and row.get("passed") is True
                for row in tables["direct_audit"]["checks"]
            ),
        ),
        ("post_current_is_sampling_axis", tables["post_audit"]["current_density_is_sampling_or_control_axis"] is True),
        ("post_has_no_21_a_m2_gate", tables["post_audit"]["no_21_a_m2_gate_applied"] is True),
        ("direct_2v_declared_core_verified", cores["2.0"]["row_count"] == 72),
        ("direct_1p8v_declared_core_verified", cores["1.8"]["row_count"] == 48),
        ("nafion_drag_below_direct_joint_window", ref.drag_max < metrics["direct_2v_tw_min"]),
        ("nafion_equal_lambda_d_scale_outside_direct_joint_window", ref.direct_d_scale_min > metrics["direct_2v_d_max"]),
        (
            "nafion_v14_adapter_reference_activity",
            math.isclose(ref.adapter_reference_activity, expected["nafion_adapter_reference_activity"], abs_tol=1e-12),
        ),
        (
            "nafion_v14_adapter_diffusivity_coefficient",
            math.isclose(ref.adapter_diffusivity_ref_m2_s, expected["nafion_adapter_diffusivity_ref_m2_s"], rel_tol=1e-12),
        ),
        (
            "nafion_v14_adapter_diffusivity_exponent",
            math.isclose(ref.adapter_diffusivity_exponent, expected["nafion_adapter_diffusivity_exponent"], rel_tol=1e-12),
        ),
        (
            "nafion_v14_adapter_conductivity_coefficient",
            math.isclose(ref.adapter_conductivity_ref_s_m, expected["nafion_adapter_conductivity_ref_s_m"], rel_tol=1e-12),
        ),
        (
            "nafion_v14_adapter_conductivity_exponent",
            math.isclose(ref.adapter_conductivity_exponent, expected["nafion_adapter_conductivity_exponent"], rel_tol=1e-12),
        ),
        (
            "post_and_nafion_adapter_exponents_are_not_equivalent",
            not math.isclose(ref.adapter_diffusivity_exponent, 2.0, rel_tol=1e-6)
            and not math.isclose(ref.adapter_conductivity_exponent, 4.0, rel_tol=1e-6),
        ),
        ("nafion_is_not_validated_for_heiq", config["claim_boundary"]["nafion_is_validated_for_heiq_device"] is False),
    ]
    failed = [name for name, passed in checks if not passed]
    if failed:
        raise AssertionError(f"Material-window audit failed: {failed}")

    direct_joint.to_csv(output_dir / "direct_joint_window_register.csv", index=False)
    direct_energy.to_csv(output_dir / "direct_energy_window_register.csv", index=False)
    post[
        [
            "water_diffusivity_m2_s",
            "uniform_current_density_a_m2",
            "plot_status",
            "plot_margin_kw",
            "target_reached",
            "conditional_energy_pass",
            "positive_surface_direction_everywhere",
            "area_is_right_censored",
        ]
    ].to_csv(output_dir / "post_erv_dj_window_register.csv", index=False)
    broad[
        [
            *broad_core["axes"],
            "cell_voltage_required_max_v",
            "strict_physical_and_architecture_pass",
            "hard_area_cap_pass",
            "process_activity_robust_pass",
            "membrane_replay_pass_2v",
            "membrane_replay_pass_1p8v",
        ]
    ].to_csv(output_dir / "direct_broad_6axis_window_register.csv", index=False)
    parameter_register = _build_parameter_register(primary, fixed, broad, broad_core, post, ref)
    parameter_register.to_csv(output_dir / "parameter_window_register.csv", index=False)
    nafion_curve.to_csv(output_dir / "nafion_property_curve_register.csv", index=False)
    nafion_cases.to_csv(output_dir / "nafion_reference_case_register.csv", index=False)
    nafion_fit_audit.to_csv(output_dir / "nafion_v14_powerlaw_fit_audit.csv", index=False)
    pd.DataFrame([metrics]).to_csv(output_dir / "headline_metrics.csv", index=False)

    dpi = int(config["plot"]["dpi"])
    figure_paths: list[Path] = []
    figure_paths += _make_direct_joint_plot(direct_joint, ref, cores, output_dir, dpi)
    figure_paths += _make_direct_energy_plot(direct_energy, ref, config, output_dir, dpi)
    figure_paths += _make_post_erv_plot(post, ref, output_dir, dpi)
    figure_paths += _make_property_gap_plot(primary, post, ref, output_dir, dpi)
    figure_paths += _make_nafion_law_comparison_plot(config, tables, ref, output_dir, dpi)
    figure_paths += _make_broad_6axis_plot(broad, broad_core, ref, output_dir, dpi)

    (output_dir / "SUMMARY.md").write_text(_summary_text(metrics), encoding="utf-8")
    audit = {
        "schema_version": 1,
        "study_id": config["study_id"],
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS",
        "failed_checks": [],
        "checks": [{"check": name, "passed": bool(passed)} for name, passed in checks],
        "metrics": metrics,
        "claim_boundary": config["claim_boundary"],
        "config": _file_record(config_path),
        "generator": _file_record(Path(__file__).resolve()),
        "sources": {name: _file_record(path) for name, path in source_paths.items()},
        "outputs": {},
    }
    output_candidates = [
        output_dir / "direct_joint_window_register.csv",
        output_dir / "direct_energy_window_register.csv",
        output_dir / "post_erv_dj_window_register.csv",
        output_dir / "direct_broad_6axis_window_register.csv",
        output_dir / "parameter_window_register.csv",
        output_dir / "nafion_property_curve_register.csv",
        output_dir / "nafion_reference_case_register.csv",
        output_dir / "nafion_v14_powerlaw_fit_audit.csv",
        output_dir / "headline_metrics.csv",
        output_dir / "SUMMARY.md",
        *figure_paths,
    ]
    audit["outputs"] = {path.name: _file_record(path) for path in output_candidates}
    (output_dir / "audit.json").write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return audit


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    audit = run(args.config, args.output_dir)
    print(json.dumps({"status": audit["status"], "output_dir": str(args.output_dir.resolve()), "metrics": audit["metrics"]}, indent=2))


if __name__ == "__main__":
    main()
