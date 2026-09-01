#!/usr/bin/env python3
"""Build clear membrane/operating-region maps for EO+ERV and direct EO.

The figures deliberately distinguish a bounded, conditional calculation from a
validated full-system claim.  Current density is an operating/sampling axis;
no 21 A/m2 acceptance limit is introduced.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.patches import Patch, Rectangle


ROOT = Path(__file__).resolve().parents[1]
HEIQ = ROOT.parent
V2 = HEIQ / "HeiQ_V2"

NAVY = "#17324D"
TEAL = "#008C8C"
TEAL_DARK = "#006C70"
TEAL_PALE = "#D9F0EF"
ORANGE = "#E58B2A"
ORANGE_PALE = "#FFF1DD"
RED = "#B94A3D"
SLATE = "#607284"
GREY = "#D8E0E6"
GREY_DARK = "#8999A6"
INK = "#172A3A"
WHITE = "#FFFFFF"

PASS_CMAP = LinearSegmentedColormap.from_list(
    "conditional_saving", ["#D7EFEE", "#73C8C4", "#008C8C", "#005B63"]
)


def style() -> None:
    mpl.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 9.0,
            "axes.titlesize": 11.0,
            "axes.titleweight": "bold",
            "axes.labelsize": 9.5,
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


def finish(fig: plt.Figure, out: Path, name: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    fig.savefig(out / f"{name}.pdf", bbox_inches="tight")
    fig.savefig(out / f"{name}.png", dpi=240, bbox_inches="tight")
    plt.close(fig)


def norwegian(value: float, decimals: int = 1) -> str:
    return f"{value:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", " ")


def draw_cell(
    ax: plt.Axes,
    x: int,
    y: int,
    *,
    passed: bool,
    value: float | None,
    norm: Normalize,
    cmap: mpl.colors.Colormap,
    text: str,
    robust: bool = False,
    selected: bool = False,
) -> None:
    face = cmap(norm(value)) if passed and value is not None and np.isfinite(value) else GREY
    edge = NAVY if robust else WHITE
    linewidth = 2.5 if robust else 1.2
    ax.add_patch(Rectangle((x - 0.5, y - 0.5), 1, 1, facecolor=face, edgecolor=edge, lw=linewidth))
    if not passed:
        if text:
            ax.plot([x + 0.27, x + 0.41], [y - 0.41, y - 0.27], color=RED, lw=1.4)
            ax.plot([x + 0.27, x + 0.41], [y - 0.27, y - 0.41], color=RED, lw=1.4)
        else:
            ax.plot([x - 0.18, x + 0.18], [y - 0.18, y + 0.18], color=GREY_DARK, lw=1.4)
            ax.plot([x - 0.18, x + 0.18], [y + 0.18, y - 0.18], color=GREY_DARK, lw=1.4)
    if text:
        rgba = mpl.colors.to_rgba(face)
        luminance = 0.2126 * rgba[0] + 0.7152 * rgba[1] + 0.0722 * rgba[2]
        color = WHITE if passed and luminance < 0.52 else INK
        ax.text(x, y, text, ha="center", va="center", fontsize=6.8, color=color, linespacing=1.12)
    if selected:
        ax.scatter(x, y, marker="*", s=145, color=ORANGE, edgecolor=WHITE, linewidth=0.9, zorder=5)


def configure_grid(ax: plt.Axes, xlabels: list[str], ylabels: list[str]) -> None:
    ax.set_xlim(-0.5, len(xlabels) - 0.5)
    ax.set_ylim(len(ylabels) - 0.5, -0.5)
    ax.set_xticks(np.arange(len(xlabels)), xlabels)
    ax.set_yticks(np.arange(len(ylabels)), ylabels)
    ax.tick_params(length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)


def eo_erv_regions(out: Path) -> None:
    diff_path = (
        V2
        / "outputs/archive_terminal1_post_erv_diffusivity_sensitivity_v1_20260825T084804Z"
        / "post_erv_diffusivity_cases.csv"
    )
    schedule_path = (
        V2
        / "outputs/terminal1_post_erv_10pct_incremental_v2_study"
        / "post_erv_10pct_cases.csv"
    )
    diff = pd.read_csv(diff_path)
    schedules = pd.read_csv(schedule_path)

    conditional = (
        diff["target_reached"].astype(bool)
        & diff["transport_gate_pass"].astype(bool)
        & diff["mechanism_energy_gate_pass"].astype(bool)
        & diff["positive_incremental_saving"].astype(bool)
    )
    assert len(diff) == 12 and int(conditional.sum()) == 11
    schedule_conditional = (
        schedules["target_reached"].astype(bool)
        & schedules["transport_gate_pass"].astype(bool)
        & schedules["mechanism_energy_gate_pass"].astype(bool)
    )
    assert len(schedules) == 34 and int(schedule_conditional.sum()) == 13
    assert not schedules["full_coupled_gate_pass"].astype(bool).any()

    fig = plt.figure(figsize=(12.0, 8.3))
    gs = fig.add_gridspec(
        2,
        3,
        height_ratios=[1.04, 0.93],
        width_ratios=[1.35, 0.92, 0.92],
        hspace=0.60,
        wspace=0.33,
    )
    ax_diff = fig.add_subplot(gs[0, :])
    ax_uniform = fig.add_subplot(gs[1, 0])
    ax_film = fig.add_subplot(gs[1, 1])
    ax_zoned = fig.add_subplot(gs[1, 2])

    fig.suptitle(
        "EO + passiv ERV: hvor 10 % polering er beregningsmessig mulig",
        x=0.065,
        y=0.985,
        ha="left",
        fontsize=16,
        fontweight="bold",
        color=NAVY,
    )
    fig.text(
        0.065,
        0.947,
        "Fargede ruter = transportmål og betinget energi består. Grå X = solver/transport/energi feiler. "
        "Ingen ruter lukker overflateretning eller fullsystem.",
        ha="left",
        fontsize=9.1,
        color=SLATE,
    )

    d_values = sorted(diff["water_diffusivity_m2_s"].unique())
    j_values = sorted(diff["uniform_current_density_a_m2"].unique())
    d_labels = ["1,60·10⁻¹⁴", "1·10⁻¹²", "1·10⁻¹⁰", "1·10⁻⁹"]
    j_labels = [f"{j:g}" for j in j_values]
    saving_norm = Normalize(vmin=0, vmax=10)
    for x, d_value in enumerate(d_values):
        for y, j_value in enumerate(j_values):
            row = diff.loc[
                diff["water_diffusivity_m2_s"].eq(d_value)
                & diff["uniform_current_density_a_m2"].eq(j_value)
            ].iloc[0]
            passed = bool(conditional.loc[row.name])
            if passed:
                label = (
                    f"{norwegian(row['incremental_saving_pct_vs_passive_erv'], 2)} %\n"
                    f"{norwegian(row['required_active_area_m2'], 0)} m²"
                )
            else:
                label = (
                    f"{norwegian(row['incremental_saving_pct_vs_passive_erv'], 2)} %\n"
                    f"{norwegian(row['required_active_area_m2'], 0)} m²-tak"
                )
            draw_cell(
                ax_diff,
                x,
                y,
                passed=passed,
                value=float(row["incremental_saving_pct_vs_passive_erv"]),
                norm=saving_norm,
                cmap=PASS_CMAP,
                text=label,
            )
    configure_grid(ax_diff, d_labels, j_labels)
    ax_diff.set_title(
        "A  Membranens vanndiffusivitet × strøm-tetthet  |  tekst: betinget margin / aktivt areal",
        loc="left",
        color=NAVY,
        pad=11,
    )
    ax_diff.set_xlabel("Vanndiffusivitet D [m²/s] (logaritmisk samplet)")
    ax_diff.set_ylabel("Strøm-tetthet [A/m²]")

    schedule_specs = [
        (
            ax_uniform,
            "uniform",
            ["uniform_5", "uniform_10", "uniform_15", "uniform_21", "uniform_30", "uniform_40", "uniform_45", "uniform_50"],
            ["5", "10", "15", "21", "30", "40", "45", "50"],
            "Uniform strøm [A/m²]",
        ),
        (
            ax_film,
            "film_fraction",
            ["film50", "film70", "film80", "film90", "film95"],
            ["50", "70", "80", "90", "95"],
            "Andel av filmgrense [%]",
        ),
        (
            ax_zoned,
            "zoned",
            ["front_loaded_45", "back_loaded_45", "front_loaded_60", "back_loaded_60"],
            ["front\n45", "bak\n45", "front\n60", "bak\n60"],
            "Soneplan [A/m²]",
        ),
    ]
    receiver_order = ["real", "ideal_counterfactual"]
    receiver_labels = ["Reell film", "Idealfilm*"]
    for ax, mode, ids, labels, xlabel in schedule_specs:
        for x, schedule_id in enumerate(ids):
            for y, receiver in enumerate(receiver_order):
                row = schedules.loc[
                    schedules["schedule_mode"].eq(mode)
                    & schedules["schedule_id"].eq(schedule_id)
                    & schedules["receiver_film_mode"].eq(receiver)
                ].iloc[0]
                passed = bool(schedule_conditional.loc[row.name])
                label = ""
                if passed:
                    label = f"{norwegian(row['incremental_saving_pct_vs_passive_erv'], 1)}%\n{norwegian(row['required_active_area_m2'], 0)}"
                draw_cell(
                    ax,
                    x,
                    y,
                    passed=passed,
                    value=float(row["incremental_saving_pct_vs_passive_erv"]),
                    norm=saving_norm,
                    cmap=PASS_CMAP,
                    text=label,
                )
        configure_grid(ax, labels, receiver_labels)
        ax.set_xlabel(xlabel)
        ax.set_title(
            {"uniform": "B1  Uniform", "film_fraction": "B2  Filmstyrt", "zoned": "B3  Soneplan"}[mode],
            loc="left",
            color=NAVY,
            pad=9,
        )
    ax_uniform.set_ylabel("Receiverfilm")
    ax_film.set_yticklabels([])
    ax_zoned.set_yticklabels([])

    legend_handles = [
        Patch(facecolor=TEAL, edgecolor=WHITE, label="Betinget pass"),
        Patch(facecolor=GREY, edgecolor=GREY_DARK, label="Feil / ikke nådd"),
        Patch(facecolor=ORANGE_PALE, edgecolor=ORANGE, label="Alle: surface/fullsystem ulukket"),
    ]
    fig.legend(
        handles=legend_handles,
        loc="lower left",
        bbox_to_anchor=(0.064, 0.005),
        ncols=3,
        frameon=False,
        fontsize=8.4,
    )
    fig.text(
        0.99,
        0.019,
        "* Idealfilm er kontrafaktisk. 21 A/m² er et samplepunkt, ikke en akseptgrense.",
        ha="right",
        va="center",
        fontsize=7.8,
        color=SLATE,
    )
    cax = fig.add_axes([0.78, 0.878, 0.18, 0.018])
    cb = mpl.colorbar.ColorbarBase(cax, cmap=PASS_CMAP, norm=saving_norm, orientation="horizontal")
    cb.set_label("Betinget margin mot passiv ERV [%]", fontsize=7.8)
    cb.ax.tick_params(labelsize=7, length=2)
    fig.subplots_adjust(top=0.84, bottom=0.10, left=0.07, right=0.985)
    finish(fig, out, "14_eo_erv_parameter_regions")


def direct_eo_regions(out: Path) -> None:
    v53_path = V2 / "outputs/EO_symmetric_wet_receiver_sink_v53/joint_material_operating_gate_register.csv"
    v54_path = V2 / "outputs/EO_symmetric_wet_receiver_sink_v54/strict_margin_candidates.csv"
    v53 = pd.read_csv(v53_path)
    v54 = pd.read_csv(v54_path)

    base_mask = (
        v53["receiver_boundary_model"].eq("ideal-wet-interface")
        & np.isclose(v53["receiver_control_activity"], 0.8)
        & np.isclose(v53["receiver_sink_energy_kw_assumed"], 0.0)
        & np.isclose(v53["process_surface_activity_min_requirement"], 0.10)
        & np.isclose(v53["cell_voltage_cap_tested_v"], 5.0)
        & np.isclose(v53["dry_thickness_um"], 20.0)
        & np.isclose(v53["ionic_area_resistance_ohm_m2_at_lambda_ref"], 5e-6)
        & np.isclose(v53["retention_factor_vs_pfsa_sorption"], 1.25)
    )
    grid = v53.loc[base_mask].copy()
    assert len(grid) == 240
    assert grid.groupby(["current_density_a_m2", "transport_number_reference_t_w", "water_diffusivity_scale_vs_pfsa"]).size().eq(1).all()

    robust_mask = (
        np.isclose(v54["process_activity_gate"], 0.15)
        & np.isclose(v54["saving_target_kw"], 400.0)
        & v54["diagnostic_robust_pass"].astype(bool)
        & np.isclose(v54["dry_thickness_um"], 20.0)
        & np.isclose(v54["ionic_area_resistance_ohm_m2_at_lambda_ref"], 5e-6)
        & np.isclose(v54["retention_factor_vs_pfsa_sorption"], 1.25)
        & np.isclose(v54["receiver_control_activity"], 0.8)
        & np.isclose(v54["receiver_sink_energy_kw_assumed"], 0.0)
    )
    robust = v54.loc[robust_mask].copy()
    assert len(robust) == 12
    robust_keys = {
        (
            float(row.current_density_a_m2),
            float(row.transport_number_reference_t_w),
            float(row.water_diffusivity_scale_vs_pfsa),
        )
        for row in robust.itertuples()
    }

    currents = [50.0, 100.0, 150.0, 250.0]
    t_values = sorted(grid["transport_number_reference_t_w"].unique())
    d_values = sorted(grid["water_diffusivity_scale_vs_pfsa"].unique())
    t_labels = [f"{value:g}" for value in t_values]
    d_labels = [f"{value:g}" for value in d_values]
    norm = Normalize(vmin=80, vmax=525)

    fig, axes = plt.subplots(2, 2, figsize=(12.0, 8.5))
    fig.suptitle(
        "Direkte EO uten ERV: material- og driftsrom under idealisert våt receiver",
        x=0.065,
        y=0.985,
        ha="left",
        fontsize=16,
        fontweight="bold",
        color=NAVY,
    )
    fig.text(
        0.065,
        0.947,
        "Betinget øvre grense: ideal-wet-interface, receiveraktivitet 0,80; sinken fjerner 4,474 t/h vann, "
        "mens sink/regenerering/varme er satt til 0 kW.",
        ha="left",
        fontsize=9.2,
        color=RED,
        fontweight="bold",
    )
    fig.text(
        0.065,
        0.918,
        "Fargede ruter = streng v53-pass. Mørk ramme = v54-diagnostisk robust ved ≥400 kW og strengere aktivitets-/spenningsmargin. "
        "Grå X = passerte ikke. Strøm-tetthet er driftsakse; ingen 21 A/m²-akseptgrense.",
        ha="left",
        fontsize=8.6,
        color=SLATE,
    )

    for ax, current in zip(axes.flat, currents):
        subset = grid.loc[np.isclose(grid["current_density_a_m2"], current)]
        strict_count = int(subset["strict_v53_pass"].astype(bool).sum())
        high_count = int(
            (
                subset["strict_v53_pass"].astype(bool)
                & subset["conditional_known_electric_saving_kw"].ge(400)
            ).sum()
        )
        for x, t_value in enumerate(t_values):
            for y, d_value in enumerate(d_values):
                row = subset.loc[
                    np.isclose(subset["transport_number_reference_t_w"], t_value)
                    & np.isclose(subset["water_diffusivity_scale_vs_pfsa"], d_value)
                ].iloc[0]
                passed = bool(row["strict_v53_pass"])
                key = (current, float(t_value), float(d_value))
                robust_pass = key in robust_keys
                selected = bool(current == 50.0 and t_value == 75.0 and np.isclose(d_value, 0.6))
                label = ""
                if passed:
                    label = f"{float(row['conditional_known_electric_saving_kw']):.0f}"
                draw_cell(
                    ax,
                    x,
                    y,
                    passed=passed,
                    value=float(row["conditional_known_electric_saving_kw"]),
                    norm=norm,
                    cmap=PASS_CMAP,
                    text=label,
                    robust=robust_pass,
                    selected=selected,
                )
        configure_grid(ax, t_labels, d_labels)
        ax.set_title(
            f"j = {current:g} A/m²  |  strict {strict_count}/60  |  ≥400 kW {high_count}/60",
            loc="left",
            color=NAVY,
            pad=8,
        )
        ax.set_xlabel("Transporttall tᵥ  (EO-drag = 2·tᵥ × PFSA i dette nettet)")
        ax.set_ylabel("Vanndiffusivitet × PFSA")

    handles = [
        Patch(facecolor=TEAL, edgecolor=WHITE, label="v53 strict, betinget"),
        Patch(facecolor=GREY, edgecolor=GREY_DARK, label="Ikke strict pass"),
        Patch(facecolor="none", edgecolor=NAVY, linewidth=2.5, label="v54 robust, ≥400 kW"),
        plt.Line2D([0], [0], marker="*", color="none", markerfacecolor=ORANGE, markeredgecolor=NAVY, markersize=11, label="Valgt v55-punkt"),
    ]
    fig.legend(
        handles=handles,
        loc="lower left",
        bbox_to_anchor=(0.064, 0.005),
        ncols=4,
        frameon=False,
        fontsize=8.4,
    )
    cax = fig.add_axes([0.945, 0.22, 0.012, 0.54])
    cb = mpl.colorbar.ColorbarBase(cax, cmap=PASS_CMAP, norm=norm, orientation="vertical")
    cb.set_label("Betinget margin [kW]", fontsize=7.8)
    cb.ax.tick_params(labelsize=7, length=2)
    fig.subplots_adjust(top=0.84, bottom=0.12, left=0.07, right=0.925, hspace=0.38, wspace=0.22)
    finish(fig, out, "15_direct_eo_parameter_regions")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "reports/trond_full_results_atlas_v2/figures",
    )
    args = parser.parse_args()
    style()
    eo_erv_regions(args.out)
    direct_eo_regions(args.out)


if __name__ == "__main__":
    main()
