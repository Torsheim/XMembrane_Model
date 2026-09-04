#!/usr/bin/env python3
"""Fixed-O80 comparison: precondition to O50/O30, then cool to supply.

O50 and O30 are process-air outlet coordinates after ERV or active ERV+EO.
They are not outdoor-weather cases and are not supply-air states.  This first
plot set deliberately does not apply the 9000 m2 design gate.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/heiq-fixed-o80-stage-mpl")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path("/home/torsheim/HeiQ/HeiQ_V2/outputs/actual_o50_o30_energy_plots/actual_o50_o30_energy_savings.csv")
OUT = ROOT / "outputs/fixed_o80_erv_eo_stage_plots_v1"

AC_O80_KW = 1166.4
PASSIVE_ERV_POWER_KW = 34.359224
W = {"O80": 24.2737374769, "O50": 14.9522480770, "O30": 8.8858981051, "SUPPLY": 7.2602805935}


def build() -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = pd.read_csv(SOURCE)
    primary = raw[np.isclose(raw.receiver_flow_ratio_multiplier, 1.0)].set_index("target")
    rows = [{
        "architecture": "AC only",
        "preconditioner_outlet": "O80 (none)",
        "preconditioner_power_kw": 0.0,
        "downstream_ac_power_kw": AC_O80_KW,
        "combined_known_power_kw": AC_O80_KW,
        "active_area_m2": 0.0,
        "minimum_surface_margin": np.nan,
        "interpretation": "Coil handles the complete O80-to-supply duty",
    }]
    for target in ("O50", "O30"):
        r = primary.loc[target]
        downstream_ac = AC_O80_KW - float(r.gross_hvac_opportunity_kw)
        rows.append({
            "architecture": f"ERV+EO to {target} + AC",
            "preconditioner_outlet": f"{target} process-air coordinate",
            "preconditioner_power_kw": float(r.predryer_power_kw),
            "downstream_ac_power_kw": downstream_ac,
            "combined_known_power_kw": float(r.combined_system_power_kw),
            "active_area_m2": float(r.total_active_area_m2),
            "minimum_surface_margin": float(r.minimum_surface_margin),
            "interpretation": f"Active ERV+EO reaches {target}; coil handles {target}-to-supply remainder",
        })
    frame = pd.DataFrame(rows)
    frame["reduction_kw_vs_ac"] = AC_O80_KW - frame.combined_known_power_kw
    frame["reduction_pct_vs_ac"] = 100 * frame.reduction_kw_vs_ac / AC_O80_KW
    return frame, raw


def decorate(ax: plt.Axes) -> None:
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color="#D9E1E5", alpha=.8)
    ax.set_axisbelow(True)


def path_plot(out: Path) -> None:
    x = np.arange(3)
    stages = ["O80 inlet", "After ERV / ERV+EO", "Supply after coil"]
    paths = [
        ("AC only", [W["O80"], W["O80"], W["SUPPLY"]], "#455A64"),
        ("ERV+EO to O50 + AC", [W["O80"], W["O50"], W["SUPPLY"]], "#2A9D8F"),
        ("ERV+EO to O30 + AC", [W["O80"], W["O30"], W["SUPPLY"]], "#F28E2B"),
    ]
    fig, ax = plt.subplots(figsize=(10.5, 6.2))
    for label, values, color in paths:
        ax.plot(x, values, marker="o", linewidth=3, markersize=8, label=label, color=color)
        for xi, value in zip(x, values):
            ax.annotate(f"{value:.2f}", (xi, value), xytext=(0, 8), textcoords="offset points", ha="center", fontsize=9)
    ax.set_xticks(x, stages)
    ax.set_ylabel("Humidity ratio [g/kg dry air]")
    ax.set_title("Fixed O80 inlet: O50/O30 are preconditioner outlet coordinates", pad=32)
    ax.text(.01, 1.01, "The coil always delivers the final 20 C / 50% RH supply state", transform=ax.transAxes, color="#455A64")
    ax.legend(frameon=False)
    decorate(ax)
    fig.tight_layout()
    fig.savefig(out / "fixed_o80_process_paths.pdf")
    fig.savefig(out / "fixed_o80_process_paths.png", dpi=220)
    plt.close(fig)


def power_plot(frame: pd.DataFrame, out: Path) -> None:
    x = np.arange(len(frame))
    ac = frame.downstream_ac_power_kw.to_numpy()
    pre = frame.preconditioner_power_kw.to_numpy()
    fig, ax = plt.subplots(figsize=(10, 6.2))
    ax.bar(x, ac, width=.66, color="#455A64", label="Downstream AC")
    ax.bar(x, pre, width=.66, bottom=ac, color="#F28E2B", label="ERV+EO preconditioner")
    for xi, total in zip(x, frame.combined_known_power_kw):
        ax.text(xi, total + 24, f"{total:,.1f} kW", ha="center", fontweight="bold")
    ax.set_xticks(x, ["AC only", "ERV+EO to O50\n+ AC remainder", "ERV+EO to O30\n+ AC remainder"])
    ax.set_ylabel("Known electrical power [kW]")
    ax.set_title("Same O80 inlet and same supply endpoint", pad=32)
    ax.text(.01, 1.01, "No membrane-area gate; receiver/sink and other open loads remain outside the ledger", transform=ax.transAxes, color="#455A64")
    ax.legend(frameon=False)
    ax.set_ylim(0, AC_O80_KW * 1.16)
    decorate(ax)
    fig.tight_layout()
    fig.savefig(out / "fixed_o80_architecture_power.pdf")
    fig.savefig(out / "fixed_o80_architecture_power.png", dpi=220)
    plt.close(fig)


def comparison_plot(frame: pd.DataFrame, out: Path) -> None:
    active = frame.iloc[1:]
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 5.5))
    labels = ["ERV+EO to O50 + AC", "ERV+EO to O30 + AC"]
    colors = ["#2A9D8F", "#F28E2B"]
    axes[0].bar(labels, active.reduction_kw_vs_ac, color=colors)
    axes[1].bar(labels, active.active_area_m2, color=colors)
    for ax, vals, fmt in [(axes[0], active.reduction_kw_vs_ac, "{:,.1f} kW"), (axes[1], active.active_area_m2, "{:,.0f} m²")]:
        for i, value in enumerate(vals):
            ax.text(i, value + .025 * max(vals), fmt.format(value), ha="center", fontweight="bold")
        decorate(ax)
    axes[0].set_ylabel("Conditional reduction vs AC only [kW]")
    axes[0].set_title("Energy comparison")
    axes[1].set_ylabel("Active membrane area [m²]")
    axes[1].set_title("Unconstrained model area")
    fig.suptitle("Fixed-O80 ERV+EO pre-drying targets", fontweight="bold")
    fig.tight_layout()
    fig.savefig(out / "fixed_o80_saving_and_area.pdf")
    fig.savefig(out / "fixed_o80_saving_and_area.png", dpi=220)
    plt.close(fig)


def sensitivity_plot(raw: pd.DataFrame, out: Path) -> None:
    fig, ax = plt.subplots(figsize=(9.5, 5.8))
    for target, color in [("O50", "#2A9D8F"), ("O30", "#F28E2B")]:
        d = raw[raw.target == target].sort_values("receiver_flow_ratio_multiplier")
        ax.plot(d.receiver_flow_ratio_multiplier, d.combined_system_power_kw, marker="o", linewidth=2.5, color=color, label=f"ERV+EO to {target} + AC")
    ax.axhline(AC_O80_KW, color="#455A64", linestyle="--", label="AC-only baseline")
    ax.set_xlabel("Receiver/process flow ratio [-]")
    ax.set_ylabel("Known combined electrical power [kW]")
    ax.set_title("Receiver-flow sensitivity at fixed O80 inlet")
    ax.legend(frameon=False)
    decorate(ax)
    fig.tight_layout()
    fig.savefig(out / "fixed_o80_receiver_flow_sensitivity.pdf")
    fig.savefig(out / "fixed_o80_receiver_flow_sensitivity.png", dpi=220)
    plt.close(fig)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    frame, raw = build()
    frame.to_csv(OUT / "architecture_register.csv", index=False)
    raw.to_csv(OUT / "receiver_flow_sensitivity.csv", index=False)
    path_plot(OUT)
    power_plot(frame, OUT)
    comparison_plot(frame, OUT)
    sensitivity_plot(raw, OUT)
    manifest = {
        "source": str(SOURCE),
        "fixed_inlet": "O80: 32 C / 80% RH",
        "O50_O30_semantics": "process-air outlet after ERV+EO preconditioning",
        "supply_semantics": "common final state after downstream coil",
        "area_gate_applied": False,
        "claim_boundary": "conditional incomplete electrical ledger",
    }
    (OUT / "run_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(frame.to_string(index=False))
    print(f"Wrote plots to {OUT}")


if __name__ == "__main__":
    main()
