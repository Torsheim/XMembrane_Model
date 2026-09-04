#!/usr/bin/env python3
"""Equal-service opportunity plots and calculated break-even SEC values."""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/heiq-opportunity-mpl")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/equal_service_opportunity_plots_v1"
DIRECT = Path("/home/torsheim/HeiQ/HeiQ_V2/outputs/actual_o50_o30_energy_plots/actual_o50_o30_energy_savings.csv")
DIRECT_DUTY = Path("/home/torsheim/HeiQ/HeiQ_V2/outputs/pre_receiver_axial_v3/humidity_ratio_targets.csv")
SYSTEM_FOM = ROOT / "outputs/fom_assessment_v1/system_fom.csv"
DEVICE_FOM = ROOT / "outputs/fom_assessment_v1/device_fom.csv"
POST_SELECTED = ROOT / "outputs/post_erv_eo_percentage_sweep_v1/selected_transport_cases.csv"
POST_BREAK_EVEN = ROOT / "outputs/post_erv_full_eo_study_v1/break_even_by_target.csv"

AC_KW = 1166.4
ERV_KW = 34.359224


def one(frame: pd.DataFrame, **selectors: object) -> pd.Series:
    mask = np.ones(len(frame), dtype=bool)
    for col, value in selectors.items():
        mask &= frame[col].eq(value)
    rows = frame[mask]
    if len(rows) != 1:
        raise RuntimeError(f"Expected one row for {selectors}, found {len(rows)}")
    return rows.iloc[0]


def build() -> tuple[pd.DataFrame, pd.DataFrame]:
    direct = pd.read_csv(DIRECT)
    duties = pd.read_csv(DIRECT_DUTY).set_index("target")
    systems = pd.read_csv(SYSTEM_FOM).set_index("system_id")
    devices = pd.read_csv(DEVICE_FOM).set_index("architecture_id")
    post = pd.read_csv(POST_SELECTED)
    be = pd.read_csv(POST_BREAK_EVEN)

    direct_primary = direct[np.isclose(direct.receiver_flow_ratio_multiplier, 1.0)].set_index("target")
    passive = systems.loc["passive_erv_ac"]
    post_o30_system = systems.loc["post_erv_o30_common_voltage"]
    post_o30_device = devices.loc["post_erv_o30_common_voltage"]
    full = one(post, target_id="full_remaining_latent", selection="best_conditional_saving")
    full_be = one(be, target_id="full_remaining_latent", process_heat_leak_fraction=0.0)
    conservative_be = one(be, target_id="o30", process_heat_leak_fraction=0.0)

    records: list[dict[str, object]] = [{
        "scenario": "AC only",
        "family": "baseline",
        "coil_kw": AC_KW,
        "erv_kw": 0.0,
        "eo_and_active_fans_kw": 0.0,
        "known_total_kw": AC_KW,
        "eo_water_kg_h": 0.0,
        "active_area_m2": 0.0,
        "status": "calibrated baseline",
    }]
    for target in ("O50", "O30"):
        d = direct_primary.loc[target]
        records.append({
            "scenario": f"ERV+EO to {target} + AC",
            "family": "direct preconditioning",
            "coil_kw": AC_KW - float(d.gross_hvac_opportunity_kw),
            "erv_kw": 0.0,
            "eo_and_active_fans_kw": float(d.predryer_power_kw),
            "known_total_kw": float(d.combined_system_power_kw),
            "eo_water_kg_h": float(duties.loc[target, "computed_water_load_kg_h"]),
            "active_area_m2": float(d.total_active_area_m2),
            "status": "target reached; robust surface closure open",
        })
    records.extend([
        {
            "scenario": "Passive ERV + AC",
            "family": "passive ERV",
            "coil_kw": float(passive.ac_power_kw),
            "erv_kw": float(passive.predryer_power_kw),
            "eo_and_active_fans_kw": 0.0,
            "known_total_kw": float(passive.total_power_kw),
            "eo_water_kg_h": 0.0,
            "active_area_m2": 0.0,
            "status": "modelled passive reference",
        },
        {
            "scenario": "ERV + EO to O30 + AC",
            "family": "post-ERV EO",
            "coil_kw": float(post_o30_system.ac_power_kw),
            "erv_kw": ERV_KW,
            "eo_and_active_fans_kw": float(post_o30_device.known_core_power_kw),
            "known_total_kw": float(post_o30_system.total_power_kw),
            "eo_water_kg_h": float(post_o30_device.water_removed_kg_h),
            "active_area_m2": float(post_o30_device.active_area_m2),
            "status": "common-voltage mechanism; incomplete ledger",
        },
        {
            "scenario": "ERV + EO to supply + sensible AC",
            "family": "post-ERV EO",
            "coil_kw": float(full.remaining_ac_power_kw),
            "erv_kw": ERV_KW,
            "eo_and_active_fans_kw": float(full.eo_grid_import_kw_no_export_credit + full.incremental_module_fan_power_kw),
            "known_total_kw": float(full.conservative_erv_plus_eo_plus_ac_power_kw),
            "eo_water_kg_h": float(full.net_water_transport_kg_h),
            "active_area_m2": float(full.required_active_area_m2),
            "status": "exact uniform-current endpoint; common-bus unresolved",
        },
    ])
    scenarios = pd.DataFrame(records)
    scenarios["reduction_kw_vs_ac"] = AC_KW - scenarios.known_total_kw
    scenarios["reduction_pct_vs_ac"] = 100 * scenarios.reduction_kw_vs_ac / AC_KW
    scenarios["reduction_kw_vs_passive_erv"] = float(passive.total_power_kw) - scenarios.known_total_kw

    breaks: list[dict[str, object]] = []
    for target in ("O50", "O30"):
        d = direct_primary.loc[target]
        water = float(duties.loc[target, "computed_water_load_kg_h"])
        actual_be = float(d.gross_hvac_opportunity_kw) / water
        known_sec = float(d.predryer_power_kw) / water
        breaks.append({
            "scenario": f"ERV+EO to {target} + AC vs AC",
            "water_removed_kg_h": water,
            "avoided_comparator_power_kw": float(d.gross_hvac_opportunity_kw),
            "calculated_break_even_kwh_kg": actual_be,
            "known_eo_sec_kwh_kg": known_sec,
            "unallocated_sec_headroom_kwh_kg": actual_be - known_sec,
            "branch": "direct fixed-O80 preconditioning",
        })
    breaks.append({
        "scenario": "Post-ERV EO to O30 vs passive ERV+AC",
        "water_removed_kg_h": float(post_o30_device.water_removed_kg_h),
        "avoided_comparator_power_kw": float(conservative_be.maximum_avoided_ac_power_kw_at_zero_eo_sec),
        "calculated_break_even_kwh_kg": float(conservative_be.break_even_all_in_eo_sec_kwh_per_kg),
        "known_eo_sec_kwh_kg": float(post_o30_device.known_core_sec_kwh_kg),
        "unallocated_sec_headroom_kwh_kg": float(post_o30_device.unallocated_sec_budget_kwh_kg),
        "branch": "post-ERV conservative",
    })
    full_known_sec = float(full.eo_grid_import_kw_no_export_credit + full.incremental_module_fan_power_kw) / float(full.net_water_transport_kg_h)
    breaks.append({
        "scenario": "Post-ERV full EO exact endpoint vs passive ERV+AC",
        "water_removed_kg_h": float(full.net_water_transport_kg_h),
        "avoided_comparator_power_kw": float(full_be.maximum_avoided_ac_power_kw_at_zero_eo_sec),
        "calculated_break_even_kwh_kg": float(full_be.break_even_all_in_eo_sec_kwh_per_kg),
        "known_eo_sec_kwh_kg": full_known_sec,
        "unallocated_sec_headroom_kwh_kg": float(full_be.break_even_all_in_eo_sec_kwh_per_kg) - full_known_sec,
        "branch": "exact sensible-only endpoint; diagnostic discontinuity",
    })
    break_even = pd.DataFrame(breaks)
    return scenarios, break_even


def style(ax: plt.Axes) -> None:
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color="#D9E1E5", alpha=.8)
    ax.set_axisbelow(True)


def plot_equal_service(d: pd.DataFrame) -> None:
    x = np.arange(len(d))
    labels = ["AC only", "ERV+EO\nto O50 + AC", "ERV+EO\nto O30 + AC", "Passive ERV\n+ AC", "ERV then EO\nto O30 + AC", "ERV then full EO\n+ sensible AC"]
    fig, ax = plt.subplots(figsize=(13.5, 7.0))
    bottom = np.zeros(len(d))
    for label, col, color in [
        ("Downstream AC", "coil_kw", "#455A64"),
        ("Passive ERV", "erv_kw", "#2A9D8F"),
        ("EO + active fans", "eo_and_active_fans_kw", "#F28E2B"),
    ]:
        vals = d[col].to_numpy(float)
        ax.bar(x, vals, bottom=bottom, width=.7, label=label, color=color)
        bottom += vals
    for i, row in d.iterrows():
        ax.text(i, row.known_total_kw + 22, f"{row.known_total_kw:,.1f} kW", ha="center", fontweight="bold", fontsize=9)
        if row.active_area_m2 > 0:
            ax.text(i, row.known_total_kw - 50, f"A={row.active_area_m2:,.0f} m²", ha="center", color="white", fontweight="bold", fontsize=8)
    ax.set_xticks(x, labels)
    ax.set_ylabel("Known electrical power [kW]")
    ax.set_title("Equal-service opportunity ladder: one O80 inlet, one supply endpoint", pad=28)
    ax.text(.5, 1.005, "O50/O30 are preconditioner outlet coordinates; open receiver, thermal and hardware loads are excluded", transform=ax.transAxes, ha="center", color="#455A64", fontsize=9)
    ax.legend(frameon=False, ncol=3)
    ax.set_ylim(0, AC_KW * 1.17)
    style(ax)
    fig.tight_layout()
    fig.savefig(OUT / "equal_service_power_ladder.pdf")
    fig.savefig(OUT / "equal_service_power_ladder.png", dpi=220)
    plt.close(fig)


def plot_reductions(d: pd.DataFrame) -> None:
    c = d.iloc[1:].copy()
    labels = ["ERV+EO→O50\nvs AC", "ERV+EO→O30\nvs AC", "Passive ERV+AC\nvs AC", "ERV then EO→O30\nvs AC", "Full post-ERV EO\nvs AC"]
    fig, ax = plt.subplots(figsize=(11.5, 6.2))
    bars = ax.bar(np.arange(len(c)), c.reduction_kw_vs_ac, color=["#5AB4AC", "#F6A03A", "#2A9D8F", "#E76F51", "#9C6ADE"])
    for bar, (_, row) in zip(bars, c.iterrows()):
        ax.text(bar.get_x()+bar.get_width()/2, bar.get_height()+18, f"{row.reduction_kw_vs_ac:,.1f} kW\n{row.reduction_pct_vs_ac:.1f}%", ha="center", fontweight="bold", fontsize=9)
    ax.set_xticks(np.arange(len(c)), labels)
    ax.set_ylabel("Conditional known-power reduction vs AC only [kW]")
    ax.set_title("Opportunity comparison with one named baseline", pad=28)
    ax.text(.5, 1.005, "These are incomplete-ledger windows, not validated net savings", transform=ax.transAxes, ha="center", color="#455A64", fontsize=9)
    ax.set_ylim(0, max(c.reduction_kw_vs_ac)*1.18)
    style(ax)
    fig.tight_layout()
    fig.savefig(OUT / "conditional_reductions_vs_ac.pdf")
    fig.savefig(OUT / "conditional_reductions_vs_ac.png", dpi=220)
    plt.close(fig)


def plot_feasibility(d: pd.DataFrame) -> None:
    c = d[d.active_area_m2 > 0].copy()
    fig, ax = plt.subplots(figsize=(9.5, 6.2))
    colors = ["#5AB4AC", "#F6A03A", "#E76F51", "#9C6ADE"]
    offsets = [(8, -34), (8, 7), (8, 7), (8, 7)]
    for ((_, row), color, offset) in zip(c.iterrows(), colors, offsets):
        ax.scatter(row.active_area_m2, row.known_total_kw, s=140, color=color, edgecolor="#263238", linewidth=1.0)
        ax.annotate(row.scenario.replace(" + ", "\n+ "), (row.active_area_m2, row.known_total_kw), xytext=offset, textcoords="offset points", fontsize=9)
    ax.set_xlabel("Active membrane area [m²]")
    ax.set_ylabel("Known electrical power [kW]")
    ax.set_title("Energy opportunity versus active membrane area", pad=30)
    ax.text(.5, 1.015, "Position indicates opportunity; labels retain the physical-closure caveats in the data register", transform=ax.transAxes, ha="center", color="#455A64", fontsize=9)
    style(ax)
    fig.tight_layout()
    fig.savefig(OUT / "power_vs_active_area.pdf")
    fig.savefig(OUT / "power_vs_active_area.png", dpi=220)
    plt.close(fig)


def plot_break_even(d: pd.DataFrame) -> None:
    labels = ["Direct to O50\nvs AC", "Direct to O30\nvs AC", "Post-ERV O30\nvs ERV+AC", "Post-ERV full\nexact endpoint"]
    x = np.arange(len(d))
    known = 1000*d.known_eo_sec_kwh_kg.to_numpy(float)
    headroom = 1000*d.unallocated_sec_headroom_kwh_kg.to_numpy(float)
    total = 1000*d.calculated_break_even_kwh_kg.to_numpy(float)
    fig, ax = plt.subplots(figsize=(11.2, 6.4))
    ax.bar(x, known, color="#F28E2B", width=.67, label="Known EO/core SEC")
    ax.bar(x, headroom, bottom=known, color="#D7E6EA", edgecolor="#607D8B", hatch="///", width=.67, label="Remaining headroom to calculated break-even")
    for i, value in enumerate(total):
        ax.text(i, value+5, f"{value:.1f} Wh/kg", ha="center", fontweight="bold")
    ax.set_xticks(x, labels)
    ax.set_ylabel("EO subsystem energy [Wh/kg water removed]")
    ax.set_title("Calculated break-even SEC from each comparator balance", pad=28)
    ax.text(.5, 1.005, "Break-even = avoided comparator power / EO water duty; no fixed 180 Wh/kg assumption", transform=ax.transAxes, ha="center", color="#455A64", fontsize=9)
    ax.legend(frameon=False)
    ax.set_ylim(0, max(total)*1.20)
    style(ax)
    fig.tight_layout()
    fig.savefig(OUT / "calculated_break_even_sec.pdf")
    fig.savefig(OUT / "calculated_break_even_sec.png", dpi=220)
    plt.close(fig)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    scenarios, break_even = build()
    scenarios.to_csv(OUT / "opportunity_register.csv", index=False)
    break_even.to_csv(OUT / "calculated_break_even_register.csv", index=False)
    plot_equal_service(scenarios)
    plot_reductions(scenarios)
    plot_feasibility(scenarios)
    plot_break_even(break_even)
    manifest = {
        "fixed_inlet": "O80, 32 C / 80% RH",
        "fixed_endpoint": "common supply state",
        "break_even_definition": "avoided comparator power divided by EO water duty",
        "fixed_180_assumption_used": False,
        "area_gate_applied": False,
        "claim_boundary": "conditional incomplete ledgers; exact full endpoint is a diagnostic coil-control discontinuity",
    }
    (OUT / "run_manifest.json").write_text(json.dumps(manifest, indent=2)+"\n")
    print(scenarios[["scenario", "known_total_kw", "active_area_m2", "status"]].to_string(index=False))
    print("\nBreak-even SEC:")
    print(break_even[["scenario", "calculated_break_even_kwh_kg", "known_eo_sec_kwh_kg", "unallocated_sec_headroom_kwh_kg"]].to_string(index=False))


if __name__ == "__main__":
    main()
