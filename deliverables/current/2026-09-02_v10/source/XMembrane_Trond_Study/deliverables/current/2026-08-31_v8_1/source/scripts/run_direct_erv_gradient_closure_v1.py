#!/usr/bin/env python3
"""Close the direct-ERV gradient and quasi-static symmetric-current questions.

The study replays the selected hypothetical power-law membrane at the stored
direct-ERV axial states.  It separates bulk driving, gas-film polarisation and
surface driving, then evaluates matched +J/0/-J states.  The signed replay is a
quasi-static constitutive test; it is not a frequency-domain AC prediction.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
from types import ModuleType
from typing import Any, Mapping, Sequence

os.environ.setdefault("MPLCONFIGDIR", "/tmp/heiq-direct-erv-gradient-closure-mpl")

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from heiq.wp1.membrane.thermodynamics import (
    FARADAY_C_MOL,
    R_UNIVERSAL_J_MOL_K,
    audit_local_transport,
)


SCRIPT_VERSION = "direct-erv-gradient-closure-v1.0-2026-08-31"
DEFAULT_CONFIG = ROOT / "config" / "direct_erv_gradient_closure_v1.json"
DEFAULT_OUTPUT = ROOT / "outputs" / "direct_erv_gradient_closure_v1"
WATER_MOLAR_MASS_KG_MOL = 0.01801528
ACTIVITY_EPS = 1.0e-9


class GradientClosureError(RuntimeError):
    """Raised when a closure input or invariant fails."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def resolve_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def load_config(path: Path) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    if config.get("schema_version") != 1:
        raise ValueError("Unsupported direct-ERV gradient closure schema")
    if not config.get("cases"):
        raise ValueError("At least one selected direct-ERV case is required")
    claim = config["claim_boundary"]
    required_false = (
        "transient_ac_predicted",
        "material_gradient_modelled",
        "area_is_acceptance_gate",
        "full_system_claim_allowed",
    )
    if any(claim.get(key) is not False for key in required_false):
        raise ValueError("The closure claim boundary must remain fail-closed")
    if claim.get("quasistatic_only") is not True:
        raise ValueError("This study is explicitly quasi-static")
    return config


def load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


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
        json.dumps(json_safe(dict(payload)), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def select_one(frame: pd.DataFrame, case_id: str, label: str) -> pd.Series:
    selected = frame.loc[frame["case_id"].eq(case_id)]
    if len(selected) != 1:
        raise GradientClosureError(
            f"Expected one {label} row for {case_id!r}; found {len(selected)}"
        )
    return selected.iloc[0]


def power_integral(
    lower: float,
    upper: float,
    exponent: float,
    reference_activity: float,
) -> float:
    lower = min(max(float(lower), ACTIVITY_EPS), 1.0 - ACTIVITY_EPS)
    upper = min(max(float(upper), ACTIVITY_EPS), 1.0 - ACTIVITY_EPS)
    shifted = exponent + 1.0
    if abs(shifted) <= 1.0e-10:
        return reference_activity * math.log(upper / lower)
    return (
        upper**shifted - lower**shifted
    ) / (shifted * reference_activity**exponent)


def signed_state(
    *,
    flux_module: ModuleType,
    row: Mapping[str, Any],
    current_density_a_m2: float,
    material: Mapping[str, Any],
    reference_activity: float,
    series_asr_ohm_m2: float,
) -> dict[str, Any]:
    result = flux_module.local_powerlaw_flux(
        source_bulk_activity=np.array([float(row["source_bulk_activity"])]),
        receiver_bulk_activity=np.array([float(row["receiver_bulk_activity"])]),
        signed_current_density_a_m2=np.array([float(current_density_a_m2)]),
        source_film_coefficient=np.array(
            [float(row["source_film_coefficient_mol_m2_s_activity"])]
        ),
        receiver_film_coefficient=np.array(
            [float(row["receiver_film_coefficient_mol_m2_s_activity"])]
        ),
        material=material,
        reference_activity=float(reference_activity),
    )
    success = bool(result["solver_success"][0])
    if not success:
        return {"solver_success": False}
    net_flux = float(result["net_flux_mol_m2_s"][0])
    eo_flux = float(result["eo_flux_mol_m2_s"][0])
    diffusion_flux = float(result["diffusion_flux_mol_m2_s"][0])
    source_surface = float(result["source_surface_activity"][0])
    receiver_surface = float(result["receiver_surface_activity"][0])

    p_b = float(material["diffusivity_activity_exponent"]) + float(
        material["capacity_activity_exponent"]
    )
    p_sigma = float(material["conductivity_activity_exponent"])
    thickness_m = float(material["dry_thickness_um"]) * 1.0e-6
    conductivity_ref = float(material["conductivity_s_m"])
    integral_b = power_integral(
        source_surface, receiver_surface, p_b, reference_activity
    )
    integral_r = power_integral(
        source_surface,
        receiver_surface,
        p_b - p_sigma,
        reference_activity,
    )
    if abs(integral_b) < 1.0e-12:
        mean_activity = 0.5 * (source_surface + receiver_surface)
        conductivity = conductivity_ref * (
            mean_activity / reference_activity
        ) ** p_sigma
        membrane_asr = thickness_m / conductivity
    else:
        membrane_asr = thickness_m * integral_r / integral_b / conductivity_ref
    current = float(current_density_a_m2)
    temperature_c = float(row["membrane_temperature_c"])
    water_voltage = (
        float(material["water_drag"])
        * R_UNIVERSAL_J_MOL_K
        * (temperature_c + 273.15)
        / FARADAY_C_MOL
        * math.log(receiver_surface / source_surface)
    )
    ohmic_voltage = current * membrane_asr
    series_voltage = current * float(series_asr_ohm_m2)
    terminal_voltage = ohmic_voltage + water_voltage + series_voltage
    audit = audit_local_transport(
        source_surface_activity=source_surface,
        receiver_surface_activity=receiver_surface,
        temperature_c=temperature_c,
        current_density_a_m2=current,
        net_flux_mol_m2_s=net_flux,
        eo_flux_mol_m2_s=eo_flux,
        diffusion_flux_mol_m2_s=diffusion_flux,
        ohmic_voltage_v=ohmic_voltage,
        water_polarisation_voltage_v=water_voltage,
        series_loss_voltage_v=series_voltage,
        fixed_loss_voltage_v=0.0,
        coupling_identity_required=True,
    )
    return {
        "solver_success": True,
        "current_density_a_m2": current,
        "net_flux_mol_m2_s": net_flux,
        "eo_flux_mol_m2_s": eo_flux,
        "diffusion_flux_mol_m2_s": diffusion_flux,
        "source_surface_activity": source_surface,
        "receiver_surface_activity": receiver_surface,
        "surface_activity_margin": source_surface - receiver_surface,
        "membrane_asr_ohm_m2": membrane_asr,
        "ohmic_voltage_v": ohmic_voltage,
        "water_polarisation_voltage_v": water_voltage,
        "series_loss_voltage_v": series_voltage,
        "terminal_voltage_v": terminal_voltage,
        "electrical_power_density_w_m2": current * terminal_voltage,
        **audit,
    }


def build_gradient_rows(
    *,
    case_label: str,
    case_row: pd.Series,
    profile: pd.DataFrame,
    robust_margin: float,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    total_area = float(case_row["required_active_area_m2"])
    for record in profile.to_dict("records"):
        flux = float(record["net_flux_mol_m2_s"])
        source_drop = flux / float(
            record["source_film_coefficient_mol_m2_s_activity"]
        )
        receiver_rise = flux / float(
            record["receiver_film_coefficient_mol_m2_s_activity"]
        )
        film_loss = source_drop + receiver_rise
        bulk_margin = float(record["bulk_activity_margin"])
        surface_margin = float(record["surface_activity_margin"])
        identity_margin = bulk_margin - film_loss
        if bulk_margin > 0.0:
            zero_multiplier = film_loss / bulk_margin
        else:
            zero_multiplier = math.inf if film_loss > 0.0 else 0.0
        if bulk_margin > robust_margin:
            robust_multiplier = film_loss / (bulk_margin - robust_margin)
        else:
            robust_multiplier = math.inf
        water_voltage = float(record["water_polarisation_voltage_v"])
        terminal_voltage = float(record["terminal_voltage_v"])
        rows.append(
            {
                "case_label": case_label,
                "case_id": case_row["case_id"],
                "segment_index": int(record["segment_index"]),
                "x_mid": float(record["x_mid"]),
                "segment_area_m2": float(record["required_active_area_m2"]),
                "total_case_area_m2": total_area,
                "net_flux_mol_m2_s": flux,
                "eo_flux_mol_m2_s": float(record["eo_flux_mol_m2_s"]),
                "diffusion_flux_mol_m2_s": float(
                    record["diffusion_flux_mol_m2_s"]
                ),
                "bulk_activity_margin": bulk_margin,
                "source_film_activity_drop": source_drop,
                "receiver_film_activity_rise": receiver_rise,
                "total_film_activity_loss": film_loss,
                "surface_activity_margin": surface_margin,
                "surface_margin_from_identity": identity_margin,
                "surface_identity_error": surface_margin - identity_margin,
                "critical_film_or_area_multiplier_for_zero_surface_margin": (
                    zero_multiplier
                ),
                "critical_film_or_area_multiplier_for_robust_margin": (
                    robust_multiplier
                ),
                "case_area_at_zero_surface_margin_m2": (
                    total_area * zero_multiplier
                    if math.isfinite(zero_multiplier)
                    else math.inf
                ),
                "case_area_at_robust_surface_margin_m2": (
                    total_area * robust_multiplier
                    if math.isfinite(robust_multiplier)
                    else math.inf
                ),
                "terminal_voltage_v": terminal_voltage,
                "water_polarisation_voltage_v": water_voltage,
                "water_polarisation_fraction_of_terminal_voltage": (
                    water_voltage / terminal_voltage
                    if abs(terminal_voltage) > 1.0e-15
                    else math.nan
                ),
            }
        )
    return pd.DataFrame(rows)


def build_multiplier_sweep(
    gradient: pd.DataFrame,
    multipliers: np.ndarray,
    robust_margin: float,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for case_label, group in gradient.groupby("case_label", sort=False):
        for multiplier in multipliers:
            margins = group["bulk_activity_margin"].to_numpy(float) - group[
                "total_film_activity_loss"
            ].to_numpy(float) / float(multiplier)
            rows.append(
                {
                    "case_label": case_label,
                    "film_or_area_multiplier": float(multiplier),
                    "minimum_surface_activity_margin": float(margins.min()),
                    "maximum_surface_activity_margin": float(margins.max()),
                    "positive_surface_direction_everywhere": bool(
                        np.all(margins >= 0.0)
                    ),
                    "robust_passive_assistance_everywhere": bool(
                        np.all(margins >= robust_margin)
                    ),
                }
            )
    return pd.DataFrame(rows)


def build_signed_triplet(
    *,
    flux_module: ModuleType,
    case_label: str,
    case_row: pd.Series,
    profile: pd.DataFrame,
    material: Mapping[str, Any],
    reference_activity: float,
) -> pd.DataFrame:
    series_asr = float(case_row["effective_series_asr_ohm_m2"])
    rows: list[dict[str, Any]] = []
    for record in profile.to_dict("records"):
        amplitude = abs(float(record["current_density_a_m2"]))
        states = {
            "plus": signed_state(
                flux_module=flux_module,
                row=record,
                current_density_a_m2=amplitude,
                material=material,
                reference_activity=reference_activity,
                series_asr_ohm_m2=series_asr,
            ),
            "zero": signed_state(
                flux_module=flux_module,
                row=record,
                current_density_a_m2=0.0,
                material=material,
                reference_activity=reference_activity,
                series_asr_ohm_m2=series_asr,
            ),
            "minus": signed_state(
                flux_module=flux_module,
                row=record,
                current_density_a_m2=-amplitude,
                material=material,
                reference_activity=reference_activity,
                series_asr_ohm_m2=series_asr,
            ),
        }
        if not all(bool(state.get("solver_success")) for state in states.values()):
            raise GradientClosureError(
                f"Signed flux failed for {case_label}, segment {record['segment_index']}"
            )
        plus, zero, minus = states["plus"], states["zero"], states["minus"]
        even_flux = 0.5 * (
            float(plus["net_flux_mol_m2_s"])
            + float(minus["net_flux_mol_m2_s"])
        )
        odd_flux = 0.5 * (
            float(plus["net_flux_mol_m2_s"])
            - float(minus["net_flux_mol_m2_s"])
        )
        passive_flux = float(zero["net_flux_mol_m2_s"])
        incremental = even_flux - passive_flux
        area = float(record["required_active_area_m2"])
        conversion = area * WATER_MOLAR_MASS_KG_MOL * 3600.0
        average_power_density = 0.5 * (
            float(plus["electrical_power_density_w_m2"])
            + float(minus["electrical_power_density_w_m2"])
        )
        rows.append(
            {
                "case_label": case_label,
                "case_id": case_row["case_id"],
                "segment_index": int(record["segment_index"]),
                "x_mid": float(record["x_mid"]),
                "segment_area_m2": area,
                "current_amplitude_a_m2": amplitude,
                "plus_current_density_a_m2": float(
                    plus["current_density_a_m2"]
                ),
                "minus_current_density_a_m2": float(
                    minus["current_density_a_m2"]
                ),
                "cycle_average_current_density_a_m2": 0.0,
                "plus_terminal_voltage_v": float(plus["terminal_voltage_v"]),
                "minus_terminal_voltage_v": float(minus["terminal_voltage_v"]),
                "voltage_center_v": 0.5
                * (
                    float(plus["terminal_voltage_v"])
                    + float(minus["terminal_voltage_v"])
                ),
                "voltage_half_span_v": 0.5
                * (
                    float(plus["terminal_voltage_v"])
                    - float(minus["terminal_voltage_v"])
                ),
                "plus_flux_mol_m2_s": float(plus["net_flux_mol_m2_s"]),
                "zero_current_passive_flux_mol_m2_s": passive_flux,
                "minus_flux_mol_m2_s": float(minus["net_flux_mol_m2_s"]),
                "cycle_even_flux_mol_m2_s": even_flux,
                "cycle_odd_flux_mol_m2_s": odd_flux,
                "incremental_rectification_flux_mol_m2_s": incremental,
                "incremental_rectification_fraction_of_plus_flux": (
                    incremental / abs(float(plus["net_flux_mol_m2_s"]))
                    if abs(float(plus["net_flux_mol_m2_s"])) > 1.0e-20
                    else 0.0
                ),
                "plus_water_rate_kg_h": float(plus["net_flux_mol_m2_s"])
                * conversion,
                "zero_current_passive_water_rate_kg_h": passive_flux
                * conversion,
                "minus_water_rate_kg_h": float(minus["net_flux_mol_m2_s"])
                * conversion,
                "cycle_even_water_rate_kg_h": even_flux * conversion,
                "incremental_rectification_water_rate_kg_h": incremental
                * conversion,
                "cycle_average_electrical_power_kw": average_power_density
                * area
                / 1000.0,
                "plus_thermodynamic_pass": bool(
                    plus["thermodynamic_consistency_pass"]
                ),
                "zero_thermodynamic_pass": bool(
                    zero["thermodynamic_consistency_pass"]
                ),
                "minus_thermodynamic_pass": bool(
                    minus["thermodynamic_consistency_pass"]
                ),
            }
        )
    return pd.DataFrame(rows)


def finite_max(series: pd.Series) -> float:
    values = pd.to_numeric(series, errors="coerce").to_numpy(float)
    finite = values[np.isfinite(values)]
    return float(finite.max()) if finite.size else math.inf


def build_case_summary(
    gradient: pd.DataFrame,
    signed: pd.DataFrame,
    selected: pd.DataFrame,
    robust_margin: float,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for case_label, group in gradient.groupby("case_label", sort=False):
        triplet = signed.loc[signed["case_label"].eq(case_label)]
        case_row = selected.loc[selected["case_label"].eq(case_label)].iloc[0]
        zero_factor = finite_max(
            group["critical_film_or_area_multiplier_for_zero_surface_margin"]
        )
        robust_factor = finite_max(
            group["critical_film_or_area_multiplier_for_robust_margin"]
        )
        rectification = float(
            triplet["incremental_rectification_water_rate_kg_h"].sum()
        )
        plus_water = float(triplet["plus_water_rate_kg_h"].sum())
        passive_water = float(
            triplet["zero_current_passive_water_rate_kg_h"].sum()
        )
        even_water = float(triplet["cycle_even_water_rate_kg_h"].sum())
        rows.append(
            {
                "case_label": case_label,
                "case_id": case_row["case_id"],
                "terminal_voltage_v": float(case_row["terminal_voltage_v"]),
                "water_target_kg_h": float(
                    case_row["water_transfer_target_kg_h"]
                ),
                "selected_dc_area_m2": float(
                    case_row["required_active_area_m2"]
                ),
                "minimum_bulk_activity_margin": float(
                    group["bulk_activity_margin"].min()
                ),
                "maximum_bulk_activity_margin": float(
                    group["bulk_activity_margin"].max()
                ),
                "minimum_surface_activity_margin": float(
                    group["surface_activity_margin"].min()
                ),
                "maximum_surface_activity_margin": float(
                    group["surface_activity_margin"].max()
                ),
                "minimum_common_film_or_area_multiplier_for_zero_surface_margin": (
                    zero_factor
                ),
                "minimum_common_film_or_area_multiplier_for_robust_margin": (
                    robust_factor
                ),
                "diagnostic_area_at_zero_surface_margin_m2": (
                    float(case_row["required_active_area_m2"]) * zero_factor
                    if math.isfinite(zero_factor)
                    else math.inf
                ),
                "diagnostic_area_at_robust_surface_margin_m2": (
                    float(case_row["required_active_area_m2"])
                    * robust_factor
                    if math.isfinite(robust_factor)
                    else math.inf
                ),
                "robust_margin_definition": robust_margin,
                "maximum_absolute_surface_identity_error": float(
                    group["surface_identity_error"].abs().max()
                ),
                "maximum_water_polarisation_fraction_of_terminal_voltage": float(
                    group["water_polarisation_fraction_of_terminal_voltage"]
                    .abs()
                    .max()
                ),
                "plus_dc_water_rate_kg_h": plus_water,
                "zero_current_passive_water_rate_kg_h": passive_water,
                "symmetric_current_cycle_water_rate_kg_h": even_water,
                "incremental_rectification_water_rate_kg_h": rectification,
                "incremental_rectification_fraction_of_plus_water": (
                    rectification / abs(plus_water)
                    if abs(plus_water) > 1.0e-20
                    else 0.0
                ),
                "symmetric_current_cycle_electrical_power_kw": float(
                    triplet["cycle_average_electrical_power_kw"].sum()
                ),
                "all_signed_states_thermodynamic_pass": bool(
                    triplet[
                        [
                            "plus_thermodynamic_pass",
                            "zero_thermodynamic_pass",
                            "minus_thermodynamic_pass",
                        ]
                    ]
                    .astype(bool)
                    .to_numpy()
                    .all()
                ),
            }
        )
    return pd.DataFrame(rows)


def save_figure(fig: plt.Figure, directory: Path, stem: str) -> list[Path]:
    png = directory / f"{stem}.png"
    pdf = directory / f"{stem}.pdf"
    fig.savefig(png, dpi=220, bbox_inches="tight", facecolor="white")
    fig.savefig(pdf, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return [png, pdf]


def make_figures(
    sweep: pd.DataFrame,
    summary: pd.DataFrame,
    output: Path,
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
    labels = {
        "direct_erv_o30": "Direct ERV to O30",
        "direct_erv_full_duty": "Direct ERV full humidity duty",
    }
    colors = {
        "direct_erv_o30": "#087E8B",
        "direct_erv_full_duty": "#E07A3F",
    }
    outputs: list[Path] = []

    fig, axis = plt.subplots(figsize=(8.2, 5.2))
    for case_label, group in sweep.groupby("case_label", sort=False):
        axis.plot(
            group["film_or_area_multiplier"],
            group["minimum_surface_activity_margin"],
            linewidth=2.1,
            color=colors.get(case_label, "#555555"),
            label=labels.get(case_label, case_label),
        )
    axis.axhline(0.0, color="#222222", linewidth=1.0)
    axis.axhline(0.02, color="#777777", linewidth=1.0, linestyle="--")
    axis.set_xlabel("Common film-capacity or active-area multiplier [-]")
    axis.set_ylabel("Minimum source-minus-receiver surface activity [-]")
    axis.set_title("Finite films consume the assisting direct-ERV bulk gradient")
    axis.legend(frameon=False)
    outputs.extend(save_figure(fig, figures, "01_film_area_gradient_envelope"))

    ordered = summary.set_index("case_label").loc[
        ["direct_erv_o30", "direct_erv_full_duty"]
    ]
    fig, axes = plt.subplots(1, 2, figsize=(9.4, 4.7))
    x = np.arange(len(ordered))
    width = 0.24
    axes[0].bar(
        x - width,
        ordered["plus_dc_water_rate_kg_h"],
        width,
        label="+J half-cycle",
        color="#087E8B",
    )
    axes[0].bar(
        x,
        ordered["zero_current_passive_water_rate_kg_h"],
        width,
        label="J = 0 passive",
        color="#8A9AA9",
    )
    axes[0].bar(
        x + width,
        ordered["symmetric_current_cycle_water_rate_kg_h"],
        width,
        label="Mean of +J and -J",
        color="#E07A3F",
    )
    axes[0].set_xticks(x, ["O30", "Full duty"])
    axes[0].set_ylabel("Integrated water rate [kg/h]")
    axes[0].set_title("Charge-balanced quasi-static cycle")
    axes[0].legend(frameon=False, fontsize=8)

    rect_ppm = (
        ordered["incremental_rectification_fraction_of_plus_water"] * 1.0e6
    )
    axes[1].bar(x, rect_ppm, color=["#087E8B", "#E07A3F"])
    axes[1].set_xticks(x, ["O30", "Full duty"])
    axes[1].set_ylabel("Increment above passive baseline [ppm of +J rate]")
    axes[1].set_title("Modelled AC rectification is effectively zero")
    outputs.extend(save_figure(fig, figures, "02_signed_triplet_ac_null"))
    return outputs


def write_summary(path: Path, summary: pd.DataFrame) -> None:
    rows = summary.set_index("case_label")
    o30 = rows.loc["direct_erv_o30"]
    full = rows.loc["direct_erv_full_duty"]
    lines = [
        "# Direct-ERV gradient closure v1",
        "",
        "**Phase decision:** the broad steady-state model study can stop; start joint-property material and coupon work.",
        "",
        "## Closed findings",
        "",
        (
            "- O30 retains a favourable bulk activity margin, but the selected local "
            f"flux reverses the membrane-surface margin to {o30['minimum_surface_activity_margin']:.5f}."
        ),
        (
            "- A common film-capacity improvement or diagnostic area increase of "
            f"{o30['minimum_common_film_or_area_multiplier_for_zero_surface_margin']:.3f}x "
            "is sufficient to restore a non-negative surface direction at fixed duty; "
            f"{o30['minimum_common_film_or_area_multiplier_for_robust_margin']:.3f}x "
            "is required for the former +0.02 robustness margin."
        ),
        (
            "- The full-duty selected coordinate has zero bulk activity margin at the "
            "counter-current pinch. No finite film/area multiplier can create a positive "
            "surface margin at finite local flux; increasing area only approaches zero."
        ),
        (
            "- The matched +J/0/-J replay gives an O30 incremental even component of "
            f"{o30['incremental_rectification_water_rate_kg_h']:.6g} kg/h "
            f"({o30['incremental_rectification_fraction_of_plus_water'] * 1e6:.3f} ppm "
            "of the +J rate)."
        ),
        (
            "- The full-duty incremental even component is "
            f"{full['incremental_rectification_water_rate_kg_h']:.6g} kg/h. "
            "Within the present constant-drag steady model, charge-balanced symmetric "
            "current therefore adds no useful mean EO transport beyond N(0)."
        ),
        "",
        "## Claim boundary",
        "",
        "The signed replay is quasi-static and current-symmetric. It does not predict frequency response, hysteresis, induced-charge EO, electrode rectification or a spatially graded membrane. A symmetric voltage waveform also does not guarantee zero mean charge when a chemical-potential offset exists.",
        "",
        "Area is a diagnostic throughout this closure study, not an acceptance gate. Positive passive surface direction is a regime diagnostic, not a thermodynamic feasibility gate for active EO.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(config_path: Path, output: Path, overwrite: bool = False) -> dict[str, Any]:
    config_path = config_path.resolve()
    output = output.resolve()
    known = (
        "config_used.json",
        "source_manifest.json",
        "segment_gradient_register.csv",
        "film_area_sweep.csv",
        "signed_triplet.csv",
        "case_summary.csv",
        "SUMMARY.md",
        "audit.json",
    )
    if output.exists() and not overwrite:
        existing = [output / name for name in known if (output / name).exists()]
        if existing:
            raise FileExistsError(
                "Closure outputs already exist; use --overwrite to replace them"
            )
    output.mkdir(parents=True, exist_ok=True)

    config = load_config(config_path)
    case_register_path = resolve_path(config["case_register_csv"])
    segments_path = resolve_path(config["segment_register_csv"])
    active_config_path = resolve_path(config["active_erv_config"])
    v2_config_path = resolve_path(config["v2_config"])
    signed_source = resolve_path(config["signed_flux_source"])
    case_source = pd.read_csv(case_register_path)
    segments_source = pd.read_csv(segments_path)
    active_config = json.loads(active_config_path.read_text(encoding="utf-8"))
    v2_config = json.loads(v2_config_path.read_text(encoding="utf-8"))
    flux_module = load_module(signed_source, "_direct_erv_signed_flux_source")
    material = active_config["materials"]["terminal1_anchor"]
    reference_activity = float(v2_config["model"]["reference_water_activity"])
    robust_margin = float(config["robust_passive_assistance_margin"])

    selected_rows: list[dict[str, Any]] = []
    gradient_frames: list[pd.DataFrame] = []
    signed_frames: list[pd.DataFrame] = []
    for case_spec in config["cases"]:
        case_label = str(case_spec["case_label"])
        case_id = str(case_spec["case_id"])
        case_row = select_one(case_source, case_id, case_label)
        profile = segments_source.loc[
            segments_source["case_id"].eq(case_id)
        ].sort_values("segment_index")
        if len(profile) != int(case_row["segment_count"]):
            raise GradientClosureError(
                f"Segment count mismatch for {case_label}: {len(profile)}"
            )
        selected_rows.append({"case_label": case_label, **case_row.to_dict()})
        gradient_frames.append(
            build_gradient_rows(
                case_label=case_label,
                case_row=case_row,
                profile=profile,
                robust_margin=robust_margin,
            )
        )
        signed_frames.append(
            build_signed_triplet(
                flux_module=flux_module,
                case_label=case_label,
                case_row=case_row,
                profile=profile,
                material=material,
                reference_activity=reference_activity,
            )
        )

    selected = pd.DataFrame(selected_rows)
    gradient = pd.concat(gradient_frames, ignore_index=True)
    signed = pd.concat(signed_frames, ignore_index=True)
    grid = config["film_or_area_multiplier_grid"]
    multipliers = np.linspace(
        float(grid["minimum"]), float(grid["maximum"]), int(grid["count"])
    )
    sweep = build_multiplier_sweep(gradient, multipliers, robust_margin)
    summary = build_case_summary(gradient, signed, selected, robust_margin)

    identity_tolerance = float(config["identity_absolute_tolerance"])
    rectification_tolerance = float(config["rectification_fraction_tolerance"])
    summary_index = summary.set_index("case_label")
    o30 = summary_index.loc["direct_erv_o30"]
    full = summary_index.loc["direct_erv_full_duty"]
    checks = [
        {
            "check": "surface_film_identity",
            "passed": bool(
                gradient["surface_identity_error"].abs().max()
                <= identity_tolerance
            ),
        },
        {
            "check": "all_signed_states_solved_and_thermodynamic",
            "passed": bool(
                summary["all_signed_states_thermodynamic_pass"].astype(bool).all()
            ),
        },
        {
            "check": "o30_finite_film_or_area_crossover",
            "passed": bool(
                1.0
                < float(
                    o30[
                        "minimum_common_film_or_area_multiplier_for_zero_surface_margin"
                    ]
                )
                < 2.0
            ),
        },
        {
            "check": "full_duty_pinched_bulk_gradient",
            "passed": bool(
                math.isclose(
                    float(full["minimum_bulk_activity_margin"]),
                    0.0,
                    abs_tol=identity_tolerance,
                )
                and math.isinf(
                    float(
                        full[
                            "minimum_common_film_or_area_multiplier_for_zero_surface_margin"
                        ]
                    )
                )
            ),
        },
        {
            "check": "quasistatic_rectification_below_closure_tolerance",
            "passed": bool(
                summary["incremental_rectification_fraction_of_plus_water"]
                .abs()
                .le(rectification_tolerance)
                .all()
            ),
        },
        {
            "check": "area_is_diagnostic_only",
            "passed": config["claim_boundary"]["area_is_acceptance_gate"]
            is False,
        },
    ]
    audit = {
        "schema_version": 1,
        "study_id": config["study_id"],
        "script_version": SCRIPT_VERSION,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if all(check["passed"] for check in checks) else "FAIL",
        "checks": checks,
        "claim_boundary": config["claim_boundary"],
        "case_count": len(summary),
        "segment_count": len(gradient),
        "maximum_surface_identity_error": float(
            gradient["surface_identity_error"].abs().max()
        ),
        "maximum_absolute_rectification_fraction": float(
            summary["incremental_rectification_fraction_of_plus_water"]
            .abs()
            .max()
        ),
    }
    if audit["status"] != "PASS":
        failed = [item["check"] for item in checks if not item["passed"]]
        raise GradientClosureError(f"Closure audit failed: {failed}")

    gradient.to_csv(output / "segment_gradient_register.csv", index=False)
    sweep.to_csv(output / "film_area_sweep.csv", index=False)
    signed.to_csv(output / "signed_triplet.csv", index=False)
    summary.to_csv(output / "case_summary.csv", index=False)
    write_summary(output / "SUMMARY.md", summary)
    figure_paths = make_figures(sweep, summary, output)
    write_json(output / "config_used.json", config)
    manifest = {
        "schema_version": 1,
        "study_id": config["study_id"],
        "sources": {
            "config": file_record(config_path),
            "case_register": file_record(case_register_path),
            "segment_register": file_record(segments_path),
            "active_erv_config": file_record(active_config_path),
            "v2_config": file_record(v2_config_path),
            "signed_flux_source": file_record(signed_source),
            "runner": file_record(Path(__file__)),
        },
        "figures": [file_record(path) for path in figure_paths],
    }
    write_json(output / "source_manifest.json", manifest)
    write_json(output / "audit.json", audit)
    return audit


def main() -> int:
    args = parse_args()
    audit = run(args.config, args.output_dir, overwrite=args.overwrite)
    print(
        f"{audit['status']}: {audit['case_count']} cases, "
        f"{audit['segment_count']} segments; "
        f"max rectification fraction={audit['maximum_absolute_rectification_fraction']:.3e}"
    )
    print(Path(args.output_dir).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
