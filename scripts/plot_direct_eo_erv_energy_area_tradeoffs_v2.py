#!/usr/bin/env python3
"""Matched comparisons with EO located only inside the ERV membrane/core."""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/heiq-integrated-erv-eo-mpl")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/integrated_erv_eo_opportunity_plots_v2"
CASES = ROOT / "outputs/direct_active_eo_erv_study_v1/study/case_register.csv"
SELECTED = ROOT / "outputs/direct_active_eo_erv_study_v1/study/selected_cases.csv"
TARGETS = Path("/home/torsheim/HeiQ/HeiQ_V2/outputs/pre_receiver_axial_v3/humidity_ratio_targets.csv")
SYSTEM_FOM = ROOT / "outputs/fom_assessment_v1/system_fom.csv"

AC_ONLY_KW = 1166.4
AREA_GATE_M2 = 9000.0
SUPPLY_W_G_KG = 7.26028059345441


def style(ax: plt.Axes) -> None:
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color="#D9E1E5", alpha=.8)
    ax.set_axisbelow(True)


def choose_cases() -> tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.Series]:
    cases = pd.read_csv(CASES, low_memory=False)
    selected = pd.read_csv(SELECTED)
    targets = pd.read_csv(TARGETS).set_index("target")
    systems = pd.read_csv(SYSTEM_FOM).set_index("system_id")
    passive = systems.loc["passive_erv_ac"]

    valid = cases[
        cases.transport_solution_complete.eq(True)
        & cases.conditional_energy_pass.eq(True)
        & cases.engineering_screen_pass.eq(True)
        & cases.segment_count.eq(8)
    ].copy()
    o30_w = float(targets.loc["O30", "target_humidity_ratio_g_kg_da"])
    o30 = valid[np.isclose(valid.process_outlet_w_g_kg_da, o30_w, atol=1e-8)]
    o30_under_gate = o30[o30.required_active_area_m2 <= AREA_GATE_M2].sort_values(
        "conditional_saving_kw_vs_passive_erv", ascending=False
    ).iloc[0]
    o30_low_voltage = o30.sort_values("conditional_saving_kw_vs_passive_erv", ascending=False).iloc[0]
    full = selected[np.isclose(selected.process_outlet_w_g_kg_da, SUPPLY_W_G_KG, atol=1e-8)].iloc[0]
    return passive, targets.loc["O50"], targets.loc["O30"], o30_under_gate, o30_low_voltage, full


def build() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    passive, o50_target, o30_target, o30, o30_low_v, full = choose_cases()
    passive_outlet_w = float(full.exhaust_inlet_w_g_kg_da)  # return-air humidity, not process outlet
    # The passive process outlet is stored as the zero-current active-core target.
    passive_process_outlet_w = 13.214990538824374
    o50_w = float(o50_target.target_humidity_ratio_g_kg_da)

    rows = [
        {
            "scenario": "AC only",
            "downstream_ac_kw": AC_ONLY_KW,
            "passive_erv_core_kw": 0.0,
            "integrated_erv_eo_core_kw": 0.0,
            "known_total_kw": AC_ONLY_KW,
            "active_area_m2": 0.0,
            "eo_water_kg_h": 0.0,
            "status": "calibrated AC baseline",
        },
        {
            "scenario": "AC + ERV",
            "downstream_ac_kw": float(passive.ac_power_kw),
            "passive_erv_core_kw": float(passive.predryer_power_kw),
            "integrated_erv_eo_core_kw": 0.0,
            "known_total_kw": float(passive.total_power_kw),
            "active_area_m2": 0.0,
            "eo_water_kg_h": 0.0,
            "status": "matched passive ERV reference",
        },
        {
            "scenario": "AC + ERV+EO to O50",
            "downstream_ac_kw": float(passive.ac_power_kw),
            "passive_erv_core_kw": float(passive.predryer_power_kw),
            "integrated_erv_eo_core_kw": 0.0,
            "known_total_kw": float(passive.total_power_kw),
            "active_area_m2": 0.0,
            "eo_water_kg_h": 0.0,
            "status": f"EO off: passive ERV outlet {passive_process_outlet_w:.3f} g/kg is below O50 {o50_w:.3f} g/kg",
        },
        {
            "scenario": "AC + ERV+EO to O30",
            "downstream_ac_kw": float(o30.remaining_ac_power_kw),
            "passive_erv_core_kw": 0.0,
            "integrated_erv_eo_core_kw": float(o30.active_core_power_kw),
            "known_total_kw": float(o30.conditional_active_total_power_kw),
            "active_area_m2": float(o30.required_active_area_m2),
            "eo_water_kg_h": float(o30.integrated_net_water_transfer_kg_h),
            "status": "EO integrated in ERV core; selected under 9,000 m²",
        },
        {
            "scenario": "AC + ERV+EO to supply humidity",
            "downstream_ac_kw": float(full.remaining_ac_power_kw),
            "passive_erv_core_kw": 0.0,
            "integrated_erv_eo_core_kw": float(full.active_core_power_kw),
            "known_total_kw": float(full.conditional_active_total_power_kw),
            "active_area_m2": float(full.required_active_area_m2),
            "eo_water_kg_h": float(full.integrated_net_water_transfer_kg_h),
            "status": "EO integrated in ERV core; unconstrained mechanism point above 9,000 m²",
        },
    ]
    scenarios = pd.DataFrame(rows)
    scenarios["reduction_kw_vs_ac"] = AC_ONLY_KW - scenarios.known_total_kw
    scenarios["reduction_pct_vs_ac"] = 100 * scenarios.reduction_kw_vs_ac / AC_ONLY_KW
    scenarios["reduction_kw_vs_passive_erv"] = float(passive.total_power_kw) - scenarios.known_total_kw
    scenarios["reduction_pct_vs_passive_erv"] = 100 * scenarios.reduction_kw_vs_passive_erv / float(passive.total_power_kw)

    pairs = pd.DataFrame([
        {"comparison": "AC+ERV vs AC", "saving_kw": AC_ONLY_KW - float(passive.total_power_kw), "baseline_kw": AC_ONLY_KW},
        {"comparison": "Integrated O50 vs AC+ERV", "saving_kw": 0.0, "baseline_kw": float(passive.total_power_kw)},
        {"comparison": "Integrated O30 vs AC+ERV", "saving_kw": float(o30.conditional_saving_kw_vs_passive_erv), "baseline_kw": float(passive.total_power_kw)},
        {"comparison": "Integrated O30 vs AC", "saving_kw": AC_ONLY_KW - float(o30.conditional_active_total_power_kw), "baseline_kw": AC_ONLY_KW},
        {"comparison": "Integrated full vs AC+ERV", "saving_kw": float(full.conditional_saving_kw_vs_passive_erv), "baseline_kw": float(passive.total_power_kw)},
        {"comparison": "Integrated full vs AC", "saving_kw": AC_ONLY_KW - float(full.conditional_active_total_power_kw), "baseline_kw": AC_ONLY_KW},
    ])
    pairs["saving_pct"] = 100 * pairs.saving_kw / pairs.baseline_kw

    breaks = []
    for name, row, area_status in [
        ("Integrated ERV+EO to O30", o30, "under 9,000 m²"),
        ("Integrated ERV+EO full humidity duty", full, "unconstrained; above 9,000 m²"),
    ]:
        water = float(row.integrated_net_water_transfer_kg_h)
        known_sec = float(row.active_core_power_kw) / water
        break_even = (float(passive.total_power_kw) - float(row.remaining_ac_power_kw)) / water
        breaks.append({
            "scenario": name,
            "comparator": "same passive ERV+AC with EO off",
            "water_removed_kg_h": water,
            "remaining_ac_power_kw": float(row.remaining_ac_power_kw),
            "known_integrated_core_power_kw": float(row.active_core_power_kw),
            "calculated_break_even_kwh_kg": break_even,
            "known_integrated_core_sec_kwh_kg": known_sec,
            "unallocated_sec_headroom_kwh_kg": break_even - known_sec,
            "active_area_m2": float(row.required_active_area_m2),
            "area_status": area_status,
        })
    break_even = pd.DataFrame(breaks)

    area_points = pd.DataFrame([
        {"scenario": "O30, ≤9,000 m² selection", "active_area_m2": float(o30.required_active_area_m2), "known_total_kw": float(o30.conditional_active_total_power_kw)},
        {"scenario": "O30, low-voltage opportunity", "active_area_m2": float(o30_low_v.required_active_area_m2), "known_total_kw": float(o30_low_v.conditional_active_total_power_kw)},
        {"scenario": "Full humidity duty", "active_area_m2": float(full.required_active_area_m2), "known_total_kw": float(full.conditional_active_total_power_kw)},
    ])
    return scenarios, pairs, break_even, area_points


def plot_power_ladder(d: pd.DataFrame) -> None:
    x = np.arange(len(d))
    labels = ["AC only", "AC + ERV", "AC + ERV+EO\nto O50", "AC + ERV+EO\nto O30", "AC + ERV+EO\nto supply humidity"]
    fig, ax = plt.subplots(figsize=(12.6, 7.0))
    bottom = np.zeros(len(d))
    for label, col, color in [
        ("Downstream AC", "downstream_ac_kw", "#455A64"),
        ("Passive ERV core", "passive_erv_core_kw", "#2A9D8F"),
        ("Integrated ERV+EO core", "integrated_erv_eo_core_kw", "#F28E2B"),
    ]:
        values = d[col].to_numpy(float)
        ax.bar(x, values, bottom=bottom, width=.68, color=color, label=label)
        bottom += values
    for i, row in d.iterrows():
        ax.text(i, row.known_total_kw + 22, f"{row.known_total_kw:,.1f} kW", ha="center", fontweight="bold", fontsize=9)
        if row.scenario.endswith("O50"):
            ax.text(i, row.known_total_kw - 65, "EO OFF\nO50 already passed", ha="center", color="white", fontweight="bold", fontsize=7.5)
        if row.active_area_m2 > 0:
            gate = "≤9,000 m²" if row.active_area_m2 <= AREA_GATE_M2 else ">9,000 m²"
            ax.text(i, row.known_total_kw - 52, f"A={row.active_area_m2:,.0f} m²\n{gate}", ha="center", color="white", fontweight="bold", fontsize=7.5)
    ax.set_xticks(x, labels)
    ax.set_ylabel("Known electrical power [kW]")
    ax.set_title("Matched architectures: EO is integrated only in the ERV membrane/core", pad=30)
    ax.text(.5, 1.01, "One O80 inlet, one supply endpoint; the downstream coil removes only the remaining load", transform=ax.transAxes, ha="center", color="#455A64", fontsize=9)
    ax.legend(frameon=False, ncol=3)
    ax.set_ylim(0, AC_ONLY_KW * 1.18)
    style(ax)
    fig.tight_layout()
    fig.savefig(OUT / "integrated_power_ladder.pdf")
    fig.savefig(OUT / "integrated_power_ladder.png", dpi=220)
    plt.close(fig)


def plot_pairwise(d: pd.DataFrame) -> None:
    labels = ["AC+ERV\nvs AC", "O50\nvs AC+ERV", "O30\nvs AC+ERV", "O30\nvs AC", "Full\nvs AC+ERV", "Full\nvs AC"]
    colors = ["#2A9D8F", "#90A4AE", "#F6A03A", "#E76F51", "#9C6ADE", "#6A4C93"]
    fig, ax = plt.subplots(figsize=(12.0, 6.4))
    bars = ax.bar(np.arange(len(d)), d.saving_kw, color=colors, width=.7)
    for bar, (_, row) in zip(bars, d.iterrows()):
        y = max(float(row.saving_kw), 0.0)
        ax.text(bar.get_x()+bar.get_width()/2, y+18, f"{row.saving_kw:,.1f} kW\n{row.saving_pct:.1f}%", ha="center", fontweight="bold", fontsize=9)
    ax.set_xticks(np.arange(len(d)), labels)
    ax.set_ylabel("Conditional known-power reduction [kW]")
    ax.set_title("Pairwise savings with the comparator named explicitly", pad=30)
    ax.text(.5, 1.01, "EO rows are integrated ERV+EO; no post-ERV EO module is included", transform=ax.transAxes, ha="center", color="#455A64", fontsize=9)
    ax.set_ylim(0, max(d.saving_kw) * 1.18)
    style(ax)
    fig.tight_layout()
    fig.savefig(OUT / "integrated_pairwise_reductions.pdf")
    fig.savefig(OUT / "integrated_pairwise_reductions.png", dpi=220)
    plt.close(fig)


def plot_area(d: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(10.5, 6.2))
    colors = ["#F6A03A", "#E76F51", "#9C6ADE"]
    offsets = [(8, 8), (8, 8), (-140, 8)]
    for ((_, row), color, offset) in zip(d.iterrows(), colors, offsets):
        ax.scatter(row.active_area_m2, row.known_total_kw, s=155, color=color, edgecolor="#263238", linewidth=1.0)
        ax.annotate(row.scenario, (row.active_area_m2, row.known_total_kw), xytext=offset, textcoords="offset points", fontsize=9)
    ax.axvline(AREA_GATE_M2, color="#C62828", linestyle="--", linewidth=1.6, label="9,000 m² project gate")
    ax.set_xlabel("Active membrane area [m²]")
    ax.set_ylabel("Known electrical power [kW]")
    ax.set_title("Integrated ERV+EO energy--area trade-off", pad=30)
    ax.text(.5, 1.01, "The low-power full-duty point is not area-feasible under the current project gate", transform=ax.transAxes, ha="center", color="#455A64", fontsize=9)
    ax.legend(frameon=False)
    style(ax)
    fig.tight_layout()
    fig.savefig(OUT / "integrated_area_gate.pdf")
    fig.savefig(OUT / "integrated_area_gate.png", dpi=220)
    plt.close(fig)


def plot_break_even(d: pd.DataFrame) -> None:
    labels = ["Integrated O30\n≤9,000 m²", "Integrated full duty\n>9,000 m²"]
    known = 1000 * d.known_integrated_core_sec_kwh_kg.to_numpy(float)
    headroom = 1000 * d.unallocated_sec_headroom_kwh_kg.to_numpy(float)
    total = 1000 * d.calculated_break_even_kwh_kg.to_numpy(float)
    x = np.arange(len(d))
    fig, ax = plt.subplots(figsize=(9.4, 6.3))
    ax.bar(x, known, width=.62, color="#F28E2B", label="Known integrated ERV+EO core SEC")
    ax.bar(x, headroom, bottom=known, width=.62, color="#D7E6EA", edgecolor="#607D8B", hatch="///", label="Remaining headroom")
    for i, value in enumerate(total):
        ax.text(i, value+3, f"{value:.1f} Wh/kg", ha="center", fontweight="bold")
    ax.set_xticks(x, labels)
    ax.set_ylabel("Integrated active-core energy [Wh/kg water removed]")
    ax.set_title("Calculated EO break-even against the same ERV with EO off", pad=30)
    ax.text(.5, 1.01, "Break-even = (passive ERV+AC power − remaining coil power) / integrated EO water duty", transform=ax.transAxes, ha="center", color="#455A64", fontsize=9)
    ax.legend(frameon=False)
    ax.set_ylim(0, max(total) * 1.25)
    style(ax)
    fig.tight_layout()
    fig.savefig(OUT / "integrated_break_even_sec.pdf")
    fig.savefig(OUT / "integrated_break_even_sec.png", dpi=220)
    plt.close(fig)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    scenarios, pairs, break_even, area_points = build()
    scenarios.to_csv(OUT / "integrated_scenario_register.csv", index=False)
    pairs.to_csv(OUT / "integrated_pairwise_savings.csv", index=False)
    break_even.to_csv(OUT / "integrated_break_even_register.csv", index=False)
    area_points.to_csv(OUT / "integrated_area_register.csv", index=False)
    plot_power_ladder(scenarios)
    plot_pairwise(pairs)
    plot_area(area_points)
    plot_break_even(break_even)
    manifest = {
        "architecture_rule": "EO exists only inside the shared ERV membrane/core",
        "eo_after_erv_included": False,
        "fixed_inlet": "O80 at 32 C / 80% RH",
        "fixed_endpoint": "20 C / 50% RH supply",
        "eo_break_even_comparator": "same passive ERV+AC architecture with EO off",
        "fixed_180_wh_kg_assumption_used": False,
        "project_area_gate_m2": AREA_GATE_M2,
        "claim_boundary": "conditional known-power ledger; open receiver, heat rejection and hardware closure",
    }
    (OUT / "run_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(scenarios[["scenario", "known_total_kw", "active_area_m2", "status"]].to_string(index=False))
    print("\nCalculated integrated-core break-even:")
    print(break_even[["scenario", "calculated_break_even_kwh_kg", "known_integrated_core_sec_kwh_kg", "active_area_m2"]].to_string(index=False))


if __name__ == "__main__":
    main()
