#!/usr/bin/env python3
"""Calculate the Trond 13-FOM register and the headline water/energy FOM.

The source documents define the headline figure of merit as water removed per
electrical energy and list thirteen device/AC/system metrics.  This runner
uses names and formulas from those documents; it deliberately does not reuse
the incompatible numbering of the older 18-FOM project register.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from heiq.wp1.studies.direct_eo_erv import (  # noqa: E402
    AirState,
    build_passive_baseline,
    solve_coil,
    state_from_t_w,
    states_from_config,
)


SCRIPT_VERSION = "fom-assessment-v1.1-2026-08-30"
DEFAULT_CONFIG = ROOT / "config" / "fom_assessment_v1.json"
DEFAULT_OUTPUT = ROOT / "outputs" / "fom_assessment_v1"


class FOMAssessmentError(RuntimeError):
    """Raised when a source, identity or calculation boundary is inconsistent."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def resolve_path(value: str | Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def finite(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise FOMAssessmentError(f"{label} is not numeric: {value!r}") from exc
    if not math.isfinite(result):
        raise FOMAssessmentError(f"{label} is not finite: {value!r}")
    return result


def close(actual: float, expected: float, label: str, atol: float = 1.0e-7) -> None:
    if not math.isclose(actual, expected, rel_tol=1.0e-9, abs_tol=atol):
        raise FOMAssessmentError(
            f"{label} mismatch: calculated {actual:.12g}, source {expected:.12g}"
        )


def json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(json_safe(payload), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def prepare_output(path: Path, overwrite: bool) -> None:
    known = (
        "device_fom.csv",
        "system_fom.csv",
        "thirteen_fom_register.csv",
        "economic_sensitivity.csv",
        "operating_point.csv",
        "workshop_ac_erv_eo_bar.csv",
        "source_manifest.json",
        "audit.json",
        "summary.json",
        "figures/device_fom.pdf",
        "figures/device_fom.png",
        "figures/system_comparison.pdf",
        "figures/system_comparison.png",
        "figures/receiver_sensitivity.pdf",
        "figures/receiver_sensitivity.png",
        "figures/workshop_ac_erv_eo_energy.pdf",
        "figures/workshop_ac_erv_eo_energy.png",
    )
    existing = [path / name for name in known if (path / name).exists()]
    if existing and not overwrite:
        raise FileExistsError("Output exists; use --overwrite")
    if overwrite:
        for item in existing:
            item.unlink()
    (path / "figures").mkdir(parents=True, exist_ok=True)


def select_one(frame: pd.DataFrame, mask: pd.Series, label: str) -> pd.Series:
    selected = frame.loc[mask]
    if len(selected) != 1:
        raise FOMAssessmentError(f"Expected one {label} row, found {len(selected)}")
    return selected.iloc[0]


def water_l_day(water_kg_h: float, density_kg_l: float) -> float:
    return water_kg_h * 24.0 / density_kg_l


def device_row(
    *,
    architecture_id: str,
    label: str,
    duty: str,
    water_kg_h: float,
    delta_w_g_kg_da: float,
    active_area_m2: float,
    cell_power_kw: float,
    eo_grid_power_kw: float,
    fan_power_kw: float,
    known_core_power_kw: float,
    terminal_voltage_v: float,
    minimum_current_density_a_m2: float,
    maximum_current_density_a_m2: float,
    break_even_core_sec_kwh_kg: float,
    density_kg_l: float,
    comparator: str,
    evidence_class: str,
) -> dict[str, Any]:
    if water_kg_h <= 0.0 or known_core_power_kw <= 0.0 or active_area_m2 <= 0.0:
        raise FOMAssessmentError(f"Nonpositive device quantity for {architecture_id}")
    sec = known_core_power_kw / water_kg_h
    fom = water_kg_h / known_core_power_kw
    grid_sec = eo_grid_power_kw / water_kg_h
    grid_fom = water_kg_h / eo_grid_power_kw
    flux = water_kg_h / active_area_m2
    area_fom = fom / active_area_m2
    return {
        "architecture_id": architecture_id,
        "label": label,
        "duty": duty,
        "water_removed_kg_h": water_kg_h,
        "water_removed_l_day": water_l_day(water_kg_h, density_kg_l),
        "humidity_reduction_g_kg_da": delta_w_g_kg_da,
        "active_area_m2": active_area_m2,
        "water_flux_kg_m2_h": flux,
        "cell_power_kw": cell_power_kw,
        "eo_grid_power_kw": eo_grid_power_kw,
        "fan_power_kw": fan_power_kw,
        "known_core_power_kw": known_core_power_kw,
        "grid_only_sec_kwh_kg": grid_sec,
        "grid_only_fom_kg_kwh": grid_fom,
        "known_core_sec_kwh_kg": sec,
        "known_core_fom_kg_kwh": fom,
        "area_normalized_fom_kg_m2_kwh": area_fom,
        "break_even_core_sec_kwh_kg": break_even_core_sec_kwh_kg,
        "minimum_break_even_fom_kg_kwh": 1.0 / break_even_core_sec_kwh_kg,
        "unallocated_sec_budget_kwh_kg": break_even_core_sec_kwh_kg - sec,
        "terminal_voltage_v": terminal_voltage_v,
        "minimum_current_density_a_m2": minimum_current_density_a_m2,
        "maximum_current_density_a_m2": maximum_current_density_a_m2,
        "comparator": comparator,
        "evidence_class": evidence_class,
    }


def system_row(
    *,
    system_id: str,
    label: str,
    ac_power_kw: float,
    predryer_power_kw: float,
    total_power_kw: float,
    ac_water_removed_kg_h: float,
    predryer_water_removed_kg_h: float,
    ac_cop: float,
    evaporating_temperature_c: float,
    baseline_water_kg_h: float,
    baseline_ac_power_kw: float,
    passive_erv_power_kw: float,
    useful_service_kw: float,
    evidence_class: str,
) -> dict[str, Any]:
    total_water = ac_water_removed_kg_h + predryer_water_removed_kg_h
    close(total_water, baseline_water_kg_h, f"{system_id} water identity", 1.0e-5)
    combined_cop = useful_service_kw / total_power_kw
    baseline_cop = useful_service_kw / baseline_ac_power_kw
    return {
        "system_id": system_id,
        "label": label,
        "ac_power_kw": ac_power_kw,
        "predryer_power_kw": predryer_power_kw,
        "total_power_kw": total_power_kw,
        "ac_water_removed_kg_h": ac_water_removed_kg_h,
        "predryer_water_removed_kg_h": predryer_water_removed_kg_h,
        "total_outdoor_to_supply_water_kg_h": total_water,
        "water_normalized_system_sec_kwh_kg": total_power_kw / total_water,
        "water_normalized_system_fom_kg_kwh": total_water / total_power_kw,
        "ac_cop": ac_cop,
        "ac_cop_improvement_pct_vs_ac_only": 100.0 * (ac_cop / baseline_cop - 1.0),
        "evaporating_temperature_c": evaporating_temperature_c,
        "ac_peak_power_reduction_kw_vs_ac_only": baseline_ac_power_kw - ac_power_kw,
        "latent_load_reduction_pct_vs_ac_only": 100.0
        * (1.0 - ac_water_removed_kg_h / baseline_water_kg_h),
        "equal_service_combined_cop": combined_cop,
        "equal_service_combined_cop_improvement_pct_vs_ac_only": 100.0
        * (combined_cop / baseline_cop - 1.0),
        "site_peak_reduction_kw_vs_ac_only": baseline_ac_power_kw - total_power_kw,
        "site_peak_reduction_pct_vs_ac_only": 100.0
        * (1.0 - total_power_kw / baseline_ac_power_kw),
        "site_peak_reduction_kw_vs_passive_erv_ac": passive_erv_power_kw
        - total_power_kw,
        "evidence_class": evidence_class,
    }


def add_thirteen_fom_rows(
    rows: list[dict[str, Any]],
    *,
    architecture_id: str,
    device: pd.Series,
    system: pd.Series,
    baseline_evap_c: float,
    annual_saving_chf: float,
    economic_note: str,
) -> None:
    values = {
        1: (
            "Water-removal capacity",
            "m_dot_w = m_dot_da (w_in - w_out)",
            float(device["water_removed_kg_h"]),
            "kg/h",
            "conditional_known_core",
            f"{float(device['water_removed_l_day']):.2f} L/day at the declared water density",
        ),
        2: (
            "Humidity reduction",
            "Delta w = w_in - w_out",
            float(device["humidity_reduction_g_kg_da"]),
            "g/kg dry air",
            "conditional_known_core",
            "Increment across the active device boundary",
        ),
        3: (
            "Pre-dryer SEC",
            "SEC_PD = P_PD / m_dot_w",
            float(device["known_core_sec_kwh_kg"]),
            "kWh/kg water",
            "conditional_known_core",
            "Known EO/core power only; receiver/sink and omitted hardware remain open",
        ),
        4: (
            "AC COP improvement",
            "100 (COP_AC,new - COP_AC,base) / COP_AC,base",
            float(system["ac_cop_improvement_pct_vs_ac_only"]),
            "%",
            "conditional_reduced_order_coil_model",
            "Relative to AC-only at the fixed O80 duty",
        ),
        5: (
            "AC COP",
            "COP_AC = Q_cooling / P_AC",
            float(system["ac_cop"]),
            "-",
            "conditional_reduced_order_coil_model",
            "Remaining-coil COP",
        ),
        6: (
            "Latent-load reduction",
            "100 (Q_lat,base - Q_lat,new) / Q_lat,base",
            float(system["latent_load_reduction_pct_vs_ac_only"]),
            "%",
            "conditional_water_load_proxy",
            "Calculated from remaining AC water removal at common h_fg",
        ),
        7: (
            "Evaporating-temperature increase",
            "T_evap,new - T_evap,base",
            float(system["evaporating_temperature_c"]) - baseline_evap_c,
            "degC",
            "conditional_reduced_order_coil_model",
            "Frozen 5 K evaporator-approach model",
        ),
        8: (
            "AC peak-power reduction",
            "P_AC,base - P_AC,new",
            float(system["ac_peak_power_reduction_kw_vs_ac_only"]),
            "kW",
            "conditional_reduced_order_coil_model",
            "AC compressor branch only; pre-dryer power excluded",
        ),
        9: (
            "Combined-system COP",
            "Q_useful,fixed / (P_AC + P_PD)",
            float(system["equal_service_combined_cop"]),
            "-",
            "conditional_equal_service_index",
            "Fixed AC-only useful cooling numerator for like-for-like comparison",
        ),
        10: (
            "Combined-system COP improvement",
            "100 (COP_sys - COP_AC,base) / COP_AC,base",
            float(system["equal_service_combined_cop_improvement_pct_vs_ac_only"]),
            "%",
            "conditional_equal_service_index",
            "Not a refrigerant-cycle COP",
        ),
        11: (
            "Combined-system peak-power reduction",
            "P_AC,base - (P_AC,new + P_PD)",
            float(system["site_peak_reduction_kw_vs_ac_only"]),
            "kW",
            "conditional_incomplete_system_ledger",
            f"{float(system['site_peak_reduction_kw_vs_passive_erv_ac']):.3f} kW versus passive ERV+AC",
        ),
        12: (
            "Annual energy-cost saving",
            "Delta P_sys * h_year * electricity_price",
            annual_saving_chf,
            "CHF/year",
            "illustrative_parameterized",
            economic_note,
        ),
        13: (
            "Payback period",
            "CAPEX_PD / annual net saving",
            math.nan,
            "years",
            "not_available",
            "CAPEX and incremental annual maintenance are not supplied",
        ),
    }
    for fom_id, (name, formula, value, unit, status, note) in values.items():
        rows.append(
            {
                "architecture_id": architecture_id,
                "fom_id": f"FOM-{fom_id:02d}",
                "name": name,
                "formula": formula,
                "numeric_value": value,
                "unit": unit,
                "status": status,
                "boundary_note": note,
            }
        )


def style_axis(ax: plt.Axes) -> None:
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color="#D8E1E8", linewidth=0.8)
    ax.set_axisbelow(True)


def make_device_figure(frame: pd.DataFrame, output: Path) -> None:
    labels = ["Post-ERV EO\nO30", "Direct EO in ERV\nO30", "Direct EO in ERV\nfull"]
    x = np.arange(len(frame))
    fig, ax = plt.subplots(figsize=(9.2, 4.9))
    bars = ax.bar(
        x - 0.17,
        frame["known_core_fom_kg_kwh"],
        width=0.34,
        color="#008F8C",
        label="Known core FOM",
    )
    floor = ax.bar(
        x + 0.17,
        frame["minimum_break_even_fom_kg_kwh"],
        width=0.34,
        color="#F08A24",
        label="Minimum break-even FOM",
    )
    for group in (bars, floor):
        ax.bar_label(group, fmt="%.1f", padding=3, fontsize=9)
    ax.set_xticks(x, labels)
    ax.set_ylabel("Water-energy FOM [kg/kWh]")
    fig.suptitle("The FOM is duty- and boundary-specific", y=0.98, fontsize=15)
    fig.text(
        0.5,
        0.925,
        "Higher is better. Known-core values exclude receiver/sink and unmodelled hardware.",
        ha="center",
        color="#5B7083",
        fontsize=9,
    )
    style_axis(ax)
    ax.legend(frameon=False, ncol=2, loc="upper right")
    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.88))
    fig.savefig(output / "figures" / "device_fom.pdf", bbox_inches="tight")
    fig.savefig(output / "figures" / "device_fom.png", dpi=220, bbox_inches="tight")
    plt.close(fig)


def make_system_figure(frame: pd.DataFrame, output: Path) -> None:
    labels = ["AC only", "Passive ERV + AC", "Post-ERV EO O30", "Direct EO in ERV full"]
    colors = ["#173753", "#5B7083", "#008F8C", "#26A69A"]
    fig, axes = plt.subplots(1, 2, figsize=(11.0, 4.8))
    x = np.arange(len(frame))
    power = axes[0].bar(x, frame["total_power_kw"], color=colors)
    axes[0].bar_label(power, fmt="%.1f", padding=3, fontsize=8)
    axes[0].set_xticks(x, labels, rotation=17, ha="right")
    axes[0].set_ylabel("Known/conditional site power [kW]")
    axes[0].set_title("Fixed O80 duty")
    style_axis(axes[0])
    cop = axes[1].bar(x, frame["equal_service_combined_cop"], color=colors)
    axes[1].bar_label(cop, fmt="%.1f", padding=3, fontsize=8)
    axes[1].set_xticks(x, labels, rotation=17, ha="right")
    axes[1].set_ylabel("Equal-service combined COP index [-]")
    axes[1].set_title("Same 5.26-MW useful-service numerator")
    style_axis(axes[1])
    fig.suptitle("System comparison: the direct-ERV point has the largest conditional upside")
    fig.tight_layout()
    fig.savefig(output / "figures" / "system_comparison.pdf", bbox_inches="tight")
    fig.savefig(output / "figures" / "system_comparison.png", dpi=220, bbox_inches="tight")
    plt.close(fig)


def make_receiver_figure(frame: pd.DataFrame, output: Path) -> None:
    fig, ax = plt.subplots(figsize=(9.2, 4.9))
    colors = ["#008F8C", "#4C78A8", "#173753"]
    for (_, row), color in zip(frame.iterrows(), colors):
        core_sec = float(row["known_core_sec_kwh_kg"])
        budget = max(float(row["unallocated_sec_budget_kwh_kg"]), 0.0)
        added = np.linspace(0.0, max(0.22, budget * 1.25), 250)
        fom = 1.0 / (core_sec + added)
        ax.plot(1000.0 * added, fom, linewidth=2.2, color=color, label=row["label"])
        ax.scatter(
            [1000.0 * budget],
            [float(row["minimum_break_even_fom_kg_kwh"])],
            color=color,
            s=36,
            zorder=4,
        )
    ax.set_xlabel("Additional receiver/sink/hardware SEC [Wh/kg]")
    ax.set_ylabel("All-in pre-dryer FOM [kg/kWh]")
    fig.suptitle(
        "Unmodelled downstream energy rapidly reduces the headline FOM",
        y=0.98,
        fontsize=15,
    )
    fig.text(
        0.5,
        0.925,
        "Dots mark the conditional break-even allowance against each declared comparator.",
        ha="center",
        color="#5B7083",
        fontsize=9,
    )
    style_axis(ax)
    ax.legend(frameon=False)
    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.88))
    fig.savefig(output / "figures" / "receiver_sensitivity.pdf", bbox_inches="tight")
    fig.savefig(output / "figures" / "receiver_sensitivity.png", dpi=220, bbox_inches="tight")
    plt.close(fig)


def make_workshop_post_erv_bar(frame: pd.DataFrame, output: Path) -> pd.DataFrame:
    """Build the requested fixed-O80 AC+ERV+EO bar chart from current rows.

    O50 has no EO duty because the passive-ERV outlet is already below the O50
    absolute-humidity coordinate.  O30 uses the current common-voltage result,
    not the older uniform-current sensitivity point.
    """
    passive = select_one(
        frame,
        frame["system_id"].eq("passive_erv_ac"),
        "passive workshop bar",
    )
    post = select_one(
        frame,
        frame["system_id"].eq("post_erv_o30_common_voltage"),
        "post-ERV workshop bar",
    )
    baseline = float(passive["total_power_kw"])
    rows = pd.DataFrame(
        [
            {
                "state_id": "O80 / no EO",
                "total_power_kw": baseline,
                "saving_vs_no_eo_kw": 0.0,
                "saving_vs_no_eo_pct": 0.0,
                "comparison_boundary": "fixed O80 inlet; passive ERV + AC",
            },
            {
                "state_id": "O50 target",
                "total_power_kw": baseline,
                "saving_vs_no_eo_kw": 0.0,
                "saving_vs_no_eo_pct": 0.0,
                "comparison_boundary": "no EO duty; passive ERV outlet is already drier than O50",
            },
            {
                "state_id": "O30 target",
                "total_power_kw": float(post["total_power_kw"]),
                "saving_vs_no_eo_kw": baseline - float(post["total_power_kw"]),
                "saving_vs_no_eo_pct": 100.0
                * (baseline - float(post["total_power_kw"]))
                / baseline,
                "comparison_boundary": "current 1.00-V common-voltage known subtotal; receiver/sink omitted",
            },
        ]
    )
    rows.to_csv(output / "workshop_ac_erv_eo_bar.csv", index=False)

    x = np.arange(len(rows))
    fig, ax = plt.subplots(figsize=(9.2, 4.9))
    used = ax.bar(
        x,
        rows["total_power_kw"],
        color="#008F8C",
        width=0.64,
        label="Electricity used",
    )
    ax.bar(
        x,
        rows["saving_vs_no_eo_kw"],
        bottom=rows["total_power_kw"],
        color="#E6EEF3",
        width=0.64,
        label="Reduction from no-EO bar",
    )
    for index, (bar, row) in enumerate(zip(used, rows.itertuples(index=False))):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            row.total_power_kw * 0.50,
            f"{row.total_power_kw:,.1f} kW",
            ha="center",
            va="center",
            color="white",
            fontweight="bold",
            fontsize=9,
        )
        if row.saving_vs_no_eo_kw > 0.1:
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                row.total_power_kw + row.saving_vs_no_eo_kw * 0.50,
                f"save {row.saving_vs_no_eo_kw:,.1f}\n({row.saving_vs_no_eo_pct:.1f}%)",
                ha="center",
                va="center",
                color="#173753",
                fontsize=8.5,
            )
        else:
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                baseline * (1.015 + 0.025 * index),
                "no change",
                ha="center",
                va="bottom",
                color="#5B7083",
                fontsize=8.2,
            )
    ax.set_xticks(x, rows["state_id"])
    ax.set_ylabel("Electrical power at the duty point [kW]")
    ax.set_ylim(0.0, baseline * 1.17)
    style_axis(ax)
    ax.legend(frameon=False, ncol=2, loc="upper right")
    fig.suptitle(
        "Diagram 3 — Passive ERV + post-ERV EO + AC at fixed O80 outdoor air",
        y=0.98,
        fontsize=14,
        fontweight="bold",
    )
    fig.text(
        0.5,
        0.925,
        "O50 needs no EO. O30 uses the current 1.00-V common-voltage point; open receiver and hardware losses are excluded.",
        ha="center",
        color="#5B7083",
        fontsize=8.5,
    )
    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.88))
    fig.savefig(output / "figures" / "workshop_ac_erv_eo_energy.pdf", bbox_inches="tight")
    fig.savefig(
        output / "figures" / "workshop_ac_erv_eo_energy.png",
        dpi=220,
        bbox_inches="tight",
    )
    plt.close(fig)
    return rows


def calculate(
    config: Mapping[str, Any],
    output: Path,
    config_source: Path = DEFAULT_CONFIG,
) -> dict[str, Any]:
    active_config_path = resolve_path(config["active_erv_config"])
    active_config = read_json(active_config_path)
    states = states_from_config(active_config)
    baseline = build_passive_baseline(
        active_config,
        states,
        float(active_config["passive_baseline_erv"]["sensible_effectiveness"]),
    )
    m_da = float(active_config["boundary"]["process_outdoor_dry_air_kg_s"])
    ac_only = solve_coil(
        inlet=states["outdoor"],
        supply_target=states["supply"],
        m_da=m_da,
        rated_cop=baseline.rated_cop,
        ac_config=active_config["ac_model"],
    )
    close(ac_only.total_ac_power_kw, 1166.4, "AC-only anchor")
    close(baseline.total_power_kw, 543.7405641877893, "passive ERV+AC anchor")

    density = float(config["liquid_water_density_kg_l"])
    total_water = (states["outdoor"].w - states["supply"].w) * m_da * 3600.0
    close(total_water, ac_only.water_removed_kg_h, "AC-only water removal")
    passive_water = (
        states["outdoor"].w - baseline.passive_erv.oa_out.w
    ) * m_da * 3600.0

    envelope_path = resolve_path(config["common_voltage_envelope"])
    common_cases_path = resolve_path(config["common_voltage_cases"])
    envelope = pd.read_csv(envelope_path)
    optimal_d = float(config["post_erv"]["water_diffusivity_m2_s"])
    envelope_row = select_one(
        envelope,
        envelope["target_id"].eq(str(config["post_erv"]["target_id"]))
        & np.isclose(
            pd.to_numeric(envelope["water_diffusivity_m2_s"]),
            optimal_d,
            rtol=1.0e-12,
            atol=0.0,
        ),
        "post-ERV common-voltage envelope",
    )
    if envelope_row["selection_status"] != "NUMERICALLY_CONFIRMED_FEASIBLE_VOLTAGE":
        raise FOMAssessmentError("Selected post-ERV voltage is not numerically confirmed")
    common_cases = pd.read_csv(common_cases_path)
    post = select_one(
        common_cases,
        common_cases["case_id"].eq(str(envelope_row["selected_case_id"])),
        "post-ERV common-voltage case",
    )
    post_state: AirState = state_from_t_w(
        baseline.passive_erv.oa_out.t_c,
        finite(post["target_humidity_ratio_kg_kg_da"], "post target w"),
        states["outdoor"].pressure_pa,
        "post-ERV EO O30 outlet",
    )
    post_coil = solve_coil(
        inlet=post_state,
        supply_target=states["supply"],
        m_da=m_da,
        rated_cop=baseline.rated_cop,
        ac_config=active_config["ac_model"],
    )
    close(
        post_coil.total_ac_power_kw,
        finite(post["exact_endpoint_remaining_ac_power_kw"], "post AC power"),
        "post-ERV remaining AC",
    )

    direct_path = resolve_path(config["direct_active_selected_cases"])
    direct_cases = pd.read_csv(direct_path)
    direct_rows: dict[str, pd.Series] = {}
    for duty, case_id in config["direct_active_case_ids"].items():
        direct_rows[str(duty)] = select_one(
            direct_cases,
            direct_cases["case_id"].eq(str(case_id)),
            f"direct active {duty}",
        )

    device_rows: list[dict[str, Any]] = []
    post_water = finite(post["integrated_net_water_transfer_kg_h"], "post water")
    post_known = finite(
        post["known_eo_grid_and_module_fan_power_kw"], "post known power"
    )
    post_gross_ac_reduction = (
        baseline.remaining_ac.total_ac_power_kw - post_coil.total_ac_power_kw
    )
    post_break_even_sec = post_gross_ac_reduction / post_water
    device_rows.append(
        device_row(
            architecture_id="post_erv_o30_common_voltage",
            label="Post-ERV EO to O30",
            duty="O30 after passive ERV",
            water_kg_h=post_water,
            delta_w_g_kg_da=1000.0
            * (baseline.passive_erv.oa_out.w - post_state.w),
            active_area_m2=finite(post["required_active_area_m2"], "post area"),
            cell_power_kw=finite(post["cell_power_kw"], "post cell power"),
            eo_grid_power_kw=finite(post["eo_grid_power_kw"], "post grid power"),
            fan_power_kw=finite(post["module_fan_power_kw"], "post module fan"),
            known_core_power_kw=post_known,
            terminal_voltage_v=finite(
                post["common_terminal_voltage_v"], "post voltage"
            ),
            minimum_current_density_a_m2=finite(
                post["minimum_local_current_density_a_m2"], "post minimum j"
            ),
            maximum_current_density_a_m2=finite(
                post["maximum_local_current_density_a_m2"], "post maximum j"
            ),
            break_even_core_sec_kwh_kg=post_break_even_sec,
            density_kg_l=density,
            comparator="passive ERV+AC",
            evidence_class="conditional_common_voltage_known_core",
        )
    )

    for duty in ("o30", "full"):
        direct = direct_rows[duty]
        water = finite(direct["integrated_net_water_transfer_kg_h"], f"direct {duty} water")
        target_w = finite(direct["process_outlet_w_g_kg_da"], f"direct {duty} w") / 1000.0
        device_rows.append(
            device_row(
                architecture_id=f"direct_eo_erv_{duty}",
                label=f"Direct EO in ERV — {'O30' if duty == 'o30' else 'full duty'}",
                duty="O30 outlet" if duty == "o30" else "20 C/50% RH humidity ratio",
                water_kg_h=water,
                delta_w_g_kg_da=1000.0 * (states["outdoor"].w - target_w),
                active_area_m2=finite(direct["required_active_area_m2"], f"direct {duty} area"),
                cell_power_kw=finite(direct["cell_power_kw"], f"direct {duty} cell power"),
                eo_grid_power_kw=finite(direct["eo_grid_power_kw"], f"direct {duty} grid power"),
                fan_power_kw=finite(
                    direct["selected_active_core_fan_power_kw"], f"direct {duty} fan"
                ),
                known_core_power_kw=finite(
                    direct["active_core_power_kw"], f"direct {duty} core power"
                ),
                terminal_voltage_v=finite(direct["terminal_voltage_v"], f"direct {duty} voltage"),
                minimum_current_density_a_m2=finite(
                    direct["minimum_local_current_density_a_m2"], f"direct {duty} minimum j"
                ),
                maximum_current_density_a_m2=finite(
                    direct["maximum_local_current_density_a_m2"], f"direct {duty} maximum j"
                ),
                break_even_core_sec_kwh_kg=finite(
                    direct["break_even_active_core_sec_kwh_kg"],
                    f"direct {duty} break-even SEC",
                ),
                density_kg_l=density,
                comparator="passive ERV+AC",
                evidence_class="conditional_reclassified_active_core",
            )
        )
    device = pd.DataFrame(device_rows)
    for row in device.itertuples(index=False):
        close(
            row.known_core_fom_kg_kwh * row.known_core_sec_kwh_kg,
            1.0,
            f"{row.architecture_id} FOM reciprocal",
            1.0e-10,
        )
        if row.unallocated_sec_budget_kwh_kg <= 0.0:
            raise FOMAssessmentError(f"No positive open SEC budget for {row.architecture_id}")

    direct_full = direct_rows["full"]
    direct_full_state = state_from_t_w(
        finite(direct_full["process_outlet_temperature_c"], "direct full temperature"),
        finite(direct_full["process_outlet_w_g_kg_da"], "direct full w") / 1000.0,
        states["outdoor"].pressure_pa,
        "direct EO-in-ERV full-duty outlet",
    )
    direct_full_coil = solve_coil(
        inlet=direct_full_state,
        supply_target=states["supply"],
        m_da=m_da,
        rated_cop=baseline.rated_cop,
        ac_config=active_config["ac_model"],
    )
    close(
        direct_full_coil.total_ac_power_kw,
        finite(direct_full["remaining_ac_power_kw"], "direct full remaining AC"),
        "direct full remaining AC",
    )

    system_rows = [
        system_row(
            system_id="ac_only",
            label="AC only",
            ac_power_kw=ac_only.total_ac_power_kw,
            predryer_power_kw=0.0,
            total_power_kw=ac_only.total_ac_power_kw,
            ac_water_removed_kg_h=ac_only.water_removed_kg_h,
            predryer_water_removed_kg_h=0.0,
            ac_cop=ac_only.cop,
            evaporating_temperature_c=ac_only.evap_temperature_c,
            baseline_water_kg_h=total_water,
            baseline_ac_power_kw=ac_only.total_ac_power_kw,
            passive_erv_power_kw=baseline.total_power_kw,
            useful_service_kw=ac_only.cooling_load_kw,
            evidence_class="calibrated_baseline",
        ),
        system_row(
            system_id="passive_erv_ac",
            label="Passive ERV + AC",
            ac_power_kw=baseline.remaining_ac.total_ac_power_kw,
            predryer_power_kw=baseline.passive_erv.total_power_kw,
            total_power_kw=baseline.total_power_kw,
            ac_water_removed_kg_h=baseline.remaining_ac.water_removed_kg_h,
            predryer_water_removed_kg_h=passive_water,
            ac_cop=baseline.remaining_ac.cop,
            evaporating_temperature_c=baseline.remaining_ac.evap_temperature_c,
            baseline_water_kg_h=total_water,
            baseline_ac_power_kw=ac_only.total_ac_power_kw,
            passive_erv_power_kw=baseline.total_power_kw,
            useful_service_kw=ac_only.cooling_load_kw,
            evidence_class="modelled_passive_reference",
        ),
        system_row(
            system_id="post_erv_o30_common_voltage",
            label="Passive ERV + post-ERV EO O30 + AC",
            ac_power_kw=post_coil.total_ac_power_kw,
            predryer_power_kw=baseline.passive_erv.total_power_kw + post_known,
            total_power_kw=finite(
                post["conditional_exact_endpoint_total_power_kw"], "post total power"
            ),
            ac_water_removed_kg_h=post_coil.water_removed_kg_h,
            predryer_water_removed_kg_h=passive_water + post_water,
            ac_cop=post_coil.cop,
            evaporating_temperature_c=post_coil.evap_temperature_c,
            baseline_water_kg_h=total_water,
            baseline_ac_power_kw=ac_only.total_ac_power_kw,
            passive_erv_power_kw=baseline.total_power_kw,
            useful_service_kw=ac_only.cooling_load_kw,
            evidence_class="conditional_common_voltage_incomplete_ledger",
        ),
        system_row(
            system_id="direct_eo_erv_full",
            label="Direct EO in ERV, full humidity duty + AC",
            ac_power_kw=direct_full_coil.total_ac_power_kw,
            predryer_power_kw=finite(
                direct_full["active_core_power_kw"], "direct full core power"
            ),
            total_power_kw=finite(
                direct_full["conditional_active_total_power_kw"], "direct full total"
            ),
            ac_water_removed_kg_h=direct_full_coil.water_removed_kg_h,
            predryer_water_removed_kg_h=finite(
                direct_full["integrated_net_water_transfer_kg_h"], "direct full water"
            ),
            ac_cop=direct_full_coil.cop,
            evaporating_temperature_c=direct_full_coil.evap_temperature_c,
            baseline_water_kg_h=total_water,
            baseline_ac_power_kw=ac_only.total_ac_power_kw,
            passive_erv_power_kw=baseline.total_power_kw,
            useful_service_kw=ac_only.cooling_load_kw,
            evidence_class="conditional_reclassified_incomplete_ledger",
        ),
    ]
    system = pd.DataFrame(system_rows)

    economics = config["economic_sensitivity"]
    economic_rows: list[dict[str, Any]] = []
    for system_row_record in system.loc[
        system["system_id"].isin(
            ["post_erv_o30_common_voltage", "direct_eo_erv_full"]
        )
    ].to_dict("records"):
        for comparator_id, saving_key in (
            ("ac_only", "site_peak_reduction_kw_vs_ac_only"),
            ("passive_erv_ac", "site_peak_reduction_kw_vs_passive_erv_ac"),
        ):
            saving_kw = float(system_row_record[saving_key])
            for hours in economics["equivalent_full_load_hours_per_year"]:
                for price in economics["electricity_price_chf_per_kwh"]:
                    annual_kwh = saving_kw * float(hours)
                    economic_rows.append(
                        {
                            "system_id": system_row_record["system_id"],
                            "comparator_id": comparator_id,
                            "saving_kw": saving_kw,
                            "equivalent_full_load_hours_per_year": float(hours),
                            "electricity_price_chf_per_kwh": float(price),
                            "annual_energy_saving_kwh": annual_kwh,
                            "annual_energy_cost_saving_chf": annual_kwh * float(price),
                            "status": "illustrative_parameterized",
                        }
                    )
    economic = pd.DataFrame(economic_rows)

    illustrative_hours = float(economics["illustrative_hours_per_year"])
    illustrative_price = float(
        economics["illustrative_electricity_price_chf_per_kwh"]
    )
    economic_note = (
        f"Illustrative only: {illustrative_hours:g} equivalent full-load h/year "
        f"and {illustrative_price:g} CHF/kWh; maintenance excluded"
    )
    thirteen_rows: list[dict[str, Any]] = []
    for architecture_id in (
        "post_erv_o30_common_voltage",
        "direct_eo_erv_full",
    ):
        drow = select_one(
            device,
            device["architecture_id"].eq(architecture_id),
            f"device {architecture_id}",
        )
        srow = select_one(
            system,
            system["system_id"].eq(architecture_id),
            f"system {architecture_id}",
        )
        annual_chf = (
            float(srow["site_peak_reduction_kw_vs_ac_only"])
            * illustrative_hours
            * illustrative_price
        )
        add_thirteen_fom_rows(
            thirteen_rows,
            architecture_id=architecture_id,
            device=drow,
            system=srow,
            baseline_evap_c=ac_only.evap_temperature_c,
            annual_saving_chf=annual_chf,
            economic_note=economic_note,
        )
    thirteen = pd.DataFrame(thirteen_rows)

    operating_point = pd.DataFrame(
        [
            {"parameter": "Outdoor/process inlet", "value": 32.0, "unit": "degC"},
            {"parameter": "Outdoor relative humidity", "value": 80.0, "unit": "%"},
            {"parameter": "Supply/return temperature", "value": 20.0, "unit": "degC"},
            {"parameter": "Supply/return relative humidity", "value": 50.0, "unit": "%"},
            {"parameter": "Dry-air mass flow", "value": m_da, "unit": "kg/s"},
            {"parameter": "Outdoor actual volume flow", "value": finite(direct_full["process_actual_volume_flow_m3_s"], "actual volume flow"), "unit": "m3/s"},
            {"parameter": "Nominal airflow", "value": 150000.0, "unit": "cfm"},
            {"parameter": "Pressure", "value": states["outdoor"].pressure_pa, "unit": "Pa"},
            {"parameter": "Passive/core sensible effectiveness", "value": float(active_config["passive_baseline_erv"]["sensible_effectiveness"]), "unit": "-"},
            {"parameter": "Passive ERV latent effectiveness", "value": float(active_config["passive_baseline_erv"]["latent_effectiveness"]), "unit": "-"},
            {"parameter": "Optimal-vector water diffusivity", "value": optimal_d, "unit": "m2/s"},
            {"parameter": "Optimal-vector water drag number", "value": float(active_config["materials"]["terminal1_anchor"]["water_drag"]), "unit": "mol H2O/mol charge"},
            {"parameter": "Optimal-vector wet conductivity", "value": float(active_config["materials"]["terminal1_anchor"]["conductivity_s_m"]), "unit": "S/m"},
            {"parameter": "Optimal-vector dry thickness", "value": float(active_config["materials"]["terminal1_anchor"]["dry_thickness_um"]), "unit": "um"},
        ]
    )

    device.to_csv(output / "device_fom.csv", index=False)
    system.to_csv(output / "system_fom.csv", index=False)
    thirteen.to_csv(output / "thirteen_fom_register.csv", index=False)
    economic.to_csv(output / "economic_sensitivity.csv", index=False)
    operating_point.to_csv(output / "operating_point.csv", index=False)

    make_device_figure(device, output)
    make_system_figure(system, output)
    make_receiver_figure(device, output)
    make_workshop_post_erv_bar(system, output)

    source_paths = [
        *[resolve_path(path) for path in config["fom_source_documents"]],
        resolve_path(config_source),
        active_config_path,
        envelope_path,
        common_cases_path,
        direct_path,
        resolve_path(config["thermodynamic_reclassification"]),
        ROOT / "src" / "heiq" / "wp1" / "studies" / "direct_eo_erv.py",
        Path(__file__).resolve(),
    ]
    missing = [str(path) for path in source_paths if not path.is_file()]
    if missing:
        raise FOMAssessmentError(f"Missing provenance sources: {missing}")
    manifest = {
        "study_id": config["study_id"],
        "script_version": SCRIPT_VERSION,
        "sources": [
            {"path": str(path), "sha256": sha256(path)} for path in source_paths
        ],
    }
    write_json(output / "source_manifest.json", manifest)

    checks = {
        "ac_only_power_anchor": math.isclose(ac_only.total_ac_power_kw, 1166.4, abs_tol=1.0e-7),
        "passive_erv_power_anchor": math.isclose(baseline.total_power_kw, 543.7405641877893, abs_tol=1.0e-7),
        "all_system_water_identities": bool(
            np.allclose(
                system["total_outdoor_to_supply_water_kg_h"],
                total_water,
                rtol=0.0,
                atol=1.0e-5,
            )
        ),
        "all_device_fom_sec_reciprocals": bool(
            np.allclose(
                device["known_core_fom_kg_kwh"]
                * device["known_core_sec_kwh_kg"],
                1.0,
                rtol=0.0,
                atol=1.0e-10,
            )
        ),
        "positive_open_sec_budgets": bool(
            (device["unallocated_sec_budget_kwh_kg"] > 0.0).all()
        ),
        "thirteen_foms_per_architecture": bool(
            thirteen.groupby("architecture_id")["fom_id"].nunique().eq(13).all()
        ),
        "payback_fail_closed": bool(
            thirteen.loc[thirteen["fom_id"].eq("FOM-13"), "numeric_value"]
            .isna()
            .all()
        ),
        "claim_boundary_remains_conditional": not bool(
            config["claim_boundary"]["full_system_claim_allowed"]
        ),
    }
    if not all(checks.values()):
        raise FOMAssessmentError(f"Audit failed: {checks}")
    write_json(output / "audit.json", {"all_pass": True, "checks": checks})

    post_device = select_one(
        device,
        device["architecture_id"].eq("post_erv_o30_common_voltage"),
        "post device summary",
    )
    direct_device = select_one(
        device,
        device["architecture_id"].eq("direct_eo_erv_full"),
        "direct device summary",
    )
    post_system = select_one(
        system,
        system["system_id"].eq("post_erv_o30_common_voltage"),
        "post system summary",
    )
    direct_system = select_one(
        system,
        system["system_id"].eq("direct_eo_erv_full"),
        "direct system summary",
    )
    summary = {
        "study_id": config["study_id"],
        "headline_definition": "FOM = water removed [kg/h] / electrical power [kW] = kg/kWh = 1/SEC",
        "post_erv_o30": post_device.to_dict(),
        "direct_eo_erv_full": direct_device.to_dict(),
        "post_erv_o30_system": post_system.to_dict(),
        "direct_eo_erv_full_system": direct_system.to_dict(),
        "illustrative_economics": {
            "hours_per_year": illustrative_hours,
            "electricity_price_chf_per_kwh": illustrative_price,
            "capex_available": economics.get("capex_chf") is not None,
            "maintenance_available": economics.get("annual_incremental_maintenance_chf") is not None,
        },
        "claim_boundary": config["claim_boundary"],
    }
    write_json(output / "summary.json", summary)
    return summary


def main() -> None:
    args = parse_args()
    config_path = resolve_path(args.config)
    config = read_json(config_path)
    if int(config.get("schema_version", -1)) != 1:
        raise FOMAssessmentError("Unsupported config schema")
    output = resolve_path(args.output_dir)
    prepare_output(output, args.overwrite)
    summary = calculate(config, output, config_source=config_path)
    print(json.dumps(json_safe(summary), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
