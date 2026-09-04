#!/usr/bin/env python3
"""Select and plot matched integrated ERV+EO cases below 9,000 m²."""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/heiq-under-9000-mpl")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/integrated_erv_eo_under_9000_v1"
CASES = ROOT / "outputs/direct_active_eo_erv_study_v1/study/case_register.csv"
SYSTEM_FOM = ROOT / "outputs/fom_assessment_v1/system_fom.csv"

AREA_GATE_M2 = 9000.0
AC_ONLY_KW = 1166.4
FULL_WATER_DUTY_KG_H = 4827.147005
O30_W_G_KG = 8.8858981051461


def style(ax: plt.Axes) -> None:
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color="#D9E1E5", alpha=.8)
    ax.set_axisbelow(True)


def build() -> pd.DataFrame:
    cases = pd.read_csv(CASES, low_memory=False)
    systems = pd.read_csv(SYSTEM_FOM).set_index("system_id")
    passive_kw = float(systems.loc["passive_erv_ac", "total_power_kw"])

    eligible = cases[
        cases.transport_solution_complete.eq(True)
        & cases.conditional_energy_pass.eq(True)
        & cases.engineering_screen_pass.eq(True)
        & cases.segment_count.eq(8)
        & (cases.required_active_area_m2 <= AREA_GATE_M2)
    ].copy()
    # For each achieved humidity ratio, retain the lowest known-power case.
    selected = (
        eligible.sort_values("conditional_active_total_power_kw")
        .groupby("process_outlet_w_g_kg_da", as_index=False)
        .first()
        .sort_values("process_outlet_w_g_kg_da", ascending=False)
        .reset_index(drop=True)
    )
    selected["target_label"] = selected.process_outlet_w_g_kg_da.map(
        lambda value: "O30 (8.886)" if np.isclose(value, O30_W_G_KG, atol=1e-8) else f"{value:.3f} g/kg"
    )
    selected["saving_kw_vs_passive_erv"] = passive_kw - selected.conditional_active_total_power_kw
    selected["saving_pct_vs_passive_erv"] = 100 * selected.saving_kw_vs_passive_erv / passive_kw
    selected["saving_kw_vs_ac"] = AC_ONLY_KW - selected.conditional_active_total_power_kw
    selected["saving_pct_vs_ac"] = 100 * selected.saving_kw_vs_ac / AC_ONLY_KW
    selected["known_core_sec_wh_kg"] = 1000 * selected.active_core_power_kw / selected.integrated_net_water_transfer_kg_h
    selected["break_even_core_sec_wh_kg"] = 1000 * (passive_kw - selected.remaining_ac_power_kw) / selected.integrated_net_water_transfer_kg_h
    selected["sec_headroom_wh_kg"] = selected.break_even_core_sec_wh_kg - selected.known_core_sec_wh_kg
    selected["omitted_load_headroom_kw"] = selected.saving_kw_vs_passive_erv
    selected["fraction_full_humidity_duty_pct"] = 100 * selected.integrated_net_water_transfer_kg_h / FULL_WATER_DUTY_KG_H
    selected["under_9000_gate"] = True

    columns = [
        "target_label", "process_outlet_w_g_kg_da", "process_outlet_rh",
        "terminal_voltage_v", "required_active_area_m2",
        "integrated_net_water_transfer_kg_h", "fraction_full_humidity_duty_pct",
        "remaining_ac_power_kw", "active_core_power_kw", "conditional_active_total_power_kw",
        "saving_kw_vs_passive_erv", "saving_pct_vs_passive_erv",
        "saving_kw_vs_ac", "saving_pct_vs_ac",
        "known_core_sec_wh_kg", "break_even_core_sec_wh_kg", "sec_headroom_wh_kg",
        "omitted_load_headroom_kw", "minimum_surface_activity_margin",
        "thermodynamic_consistency_pass", "robust_physics_pass",
        "engineering_screen_pass", "full_coupled_gate_pass", "case_id",
    ]
    return selected[columns]


def plot_power_and_saving(d: pd.DataFrame, passive_kw: float) -> None:
    x = np.arange(len(d))
    labels = d.target_label.tolist()
    fig, axes = plt.subplots(1, 2, figsize=(14.0, 6.2))

    ax = axes[0]
    bars = ax.bar(x, d.conditional_active_total_power_kw, color="#F28E2B", width=.68)
    ax.axhline(passive_kw, color="#2A9D8F", linestyle="--", linewidth=1.7, label=f"Passive ERV+AC: {passive_kw:.1f} kW")
    for bar, value in zip(bars, d.conditional_active_total_power_kw):
        ax.text(bar.get_x()+bar.get_width()/2, value+7, f"{value:.1f}", ha="center", fontweight="bold", fontsize=8.5)
    ax.set_xticks(x, labels, rotation=18, ha="right")
    ax.set_ylabel("Known total power [kW]")
    ax.set_title("Best integrated ERV+EO point under 9,000 m²")
    ax.legend(frameon=False)
    ax.set_ylim(0, passive_kw * 1.18)
    style(ax)

    ax = axes[1]
    bars = ax.bar(x, d.saving_kw_vs_passive_erv, color="#6A4C93", width=.68)
    for bar, (_, row) in zip(bars, d.iterrows()):
        ax.text(bar.get_x()+bar.get_width()/2, row.saving_kw_vs_passive_erv+3,
                f"{row.saving_kw_vs_passive_erv:.1f} kW\n{row.saving_pct_vs_passive_erv:.1f}%",
                ha="center", fontweight="bold", fontsize=8.5)
    ax.set_xticks(x, labels, rotation=18, ha="right")
    ax.set_ylabel("Conditional saving vs passive ERV+AC [kW]")
    ax.set_title("Incremental benefit of EO inside the ERV")
    ax.set_ylim(0, max(d.saving_kw_vs_passive_erv) * 1.25)
    style(ax)

    fig.suptitle("Area-constrained integrated ERV+EO screening", fontsize=15, y=1.02)
    fig.tight_layout(rect=(0, .08, 1, .95))
    fig.savefig(OUT / "under_9000_power_and_saving.pdf", bbox_inches="tight")
    fig.savefig(OUT / "under_9000_power_and_saving.png", dpi=220, bbox_inches="tight")
    plt.close(fig)


def plot_area_and_break_even(d: pd.DataFrame) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(14.0, 6.2))

    ax = axes[0]
    scatter = ax.scatter(d.required_active_area_m2, d.saving_kw_vs_passive_erv,
                         c=d.process_outlet_w_g_kg_da, cmap="viridis", s=130,
                         edgecolor="#263238", linewidth=1.0)
    for _, row in d.iterrows():
        ax.annotate(row.target_label, (row.required_active_area_m2, row.saving_kw_vs_passive_erv),
                    xytext=(7, 6), textcoords="offset points", fontsize=8.5)
    ax.axvline(AREA_GATE_M2, color="#C62828", linestyle="--", linewidth=1.5, label="9,000 m² gate")
    ax.set_xlabel("Active membrane area [m²]")
    ax.set_ylabel("Conditional saving vs passive ERV+AC [kW]")
    ax.set_title("Saving within the project area gate")
    ax.legend(frameon=False)
    style(ax)
    fig.colorbar(scatter, ax=ax, label="Core outlet humidity ratio [g/kg]")

    ax = axes[1]
    x = np.arange(len(d))
    known = d.known_core_sec_wh_kg.to_numpy(float)
    headroom = d.sec_headroom_wh_kg.to_numpy(float)
    total = d.break_even_core_sec_wh_kg.to_numpy(float)
    ax.bar(x, known, color="#F28E2B", width=.68, label="Known integrated-core SEC")
    ax.bar(x, headroom, bottom=known, color="#D7E6EA", edgecolor="#607D8B", hatch="///", width=.68, label="Remaining headroom")
    for i, value in enumerate(total):
        ax.text(i, value+1.0, f"{value:.1f}", ha="center", fontweight="bold", fontsize=8.5)
    ax.set_xticks(x, d.target_label, rotation=18, ha="right")
    ax.set_ylabel("Active-core energy [Wh/kg water removed]")
    ax.set_title("Calculated break-even against the same ERV with EO off")
    ax.legend(frameon=False, fontsize=8.5)
    ax.set_ylim(0, max(total) * 1.25)
    style(ax)

    fig.suptitle("Energy margin for integrated ERV+EO cases below 9,000 m²", fontsize=15, y=1.02)
    fig.tight_layout(rect=(0, .10, 1, .95))
    fig.savefig(OUT / "under_9000_area_and_break_even.pdf", bbox_inches="tight")
    fig.savefig(OUT / "under_9000_area_and_break_even.png", dpi=220, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    systems = pd.read_csv(SYSTEM_FOM).set_index("system_id")
    passive_kw = float(systems.loc["passive_erv_ac", "total_power_kw"])
    selected = build()
    selected.to_csv(OUT / "best_integrated_cases_under_9000.csv", index=False)
    plot_power_and_saving(selected, passive_kw)
    plot_area_and_break_even(selected)
    manifest = {
        "architecture": "EO integrated only in ERV membrane/core",
        "area_gate_m2": AREA_GATE_M2,
        "comparator": "same passive ERV+AC with EO off",
        "passive_erv_ac_kw": passive_kw,
        "fixed_180_wh_kg_assumption_used": False,
        "selection": "lowest known total power per achieved core-outlet humidity ratio among converged 8-segment engineering-screen cases",
        "claim_boundary": "known-power conditional saving; receiver, heat rejection and full hardware closure remain open",
    }
    (OUT / "run_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(selected.to_string(index=False))


if __name__ == "__main__":
    main()
