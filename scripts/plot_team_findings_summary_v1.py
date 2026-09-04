#!/usr/bin/env python3
"""Generate vector figures for the integrated team findings report."""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import FuncFormatter


ROOT = Path(__file__).resolve().parents[1]

NAVY = "#17324D"
TEAL = "#008C8C"
TEAL_LIGHT = "#69C4C4"
ORANGE = "#E58B2A"
RED = "#C84A3A"
SLATE = "#607284"
LIGHT = "#E8EFF4"
DARK = "#172A3A"


def norwegian_integer(value: float, _position: int | None = None) -> str:
    return f"{value:,.0f}".replace(",", " ")


def setup_style() -> None:
    mpl.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 9.5,
            "axes.titlesize": 14,
            "axes.titleweight": "bold",
            "axes.labelsize": 10,
            "axes.labelcolor": DARK,
            "axes.edgecolor": "#A7B5C2",
            "axes.linewidth": 0.8,
            "xtick.color": "#465B6B",
            "ytick.color": "#465B6B",
            "grid.color": "#D9E2E9",
            "grid.linewidth": 0.7,
            "grid.alpha": 0.8,
            "legend.frameon": False,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "savefig.facecolor": "white",
        }
    )


def finish_figure(fig: plt.Figure, output_dir: Path, name: str) -> None:
    fig.savefig(output_dir / f"{name}.pdf", bbox_inches="tight")
    fig.savefig(output_dir / f"{name}.png", dpi=220, bbox_inches="tight")
    plt.close(fig)


def add_figure_header(
    fig: plt.Figure,
    title: str,
    subtitle: str,
    *,
    left: float = 0.11,
    top: float = 0.79,
) -> None:
    fig.suptitle(
        title,
        x=left,
        y=0.97,
        ha="left",
        fontsize=14,
        fontweight="bold",
    )
    fig.text(left, 0.885, subtitle, ha="left", fontsize=8.8, color=SLATE)
    fig.subplots_adjust(top=top, left=left, right=0.98, bottom=0.17)


def area_curve_figure(curve: pd.DataFrame, output_dir: Path) -> None:
    x = curve["receiver_capacity_multiplier"].to_numpy(float)
    area = curve["required_active_area_m2"].to_numpy(float)

    fig, ax = plt.subplots(figsize=(7.15, 4.0))
    ax.plot(x, area, color=TEAL, marker="o", linewidth=2.4, markersize=5.5)
    ax.fill_between(x, 9000.0, area, color=TEAL_LIGHT, alpha=0.15)
    ax.axhline(
        9000.0,
        color=SLATE,
        linewidth=1.3,
        linestyle=(0, (4, 3)),
        label="9 000 m² – kun sammenligning",
    )
    ax.scatter([3.0], [9275.1], color=ORANGE, marker="X", s=70, zorder=4)
    ax.annotate(
        "Gammel proporsjonal\nindikator: 9 275 m²",
        xy=(3.0, 9275.1),
        xytext=(2.12, 9520),
        color="#8C541A",
        fontsize=8.5,
        arrowprops=dict(arrowstyle="->", color=ORANGE, lw=1.1),
    )
    ax.annotate(
        "12 139,9 m²",
        xy=(x[0], area[0]),
        xytext=(1.13, 12300),
        fontsize=8.5,
        color=NAVY,
        arrowprops=dict(arrowstyle="-", color=NAVY, lw=0.8),
    )
    ax.annotate(
        "10 499,7 m²",
        xy=(x[-1], area[-1]),
        xytext=(2.26, 10840),
        fontsize=8.5,
        color=NAVY,
        arrowprops=dict(arrowstyle="->", color=NAVY, lw=0.9),
    )
    add_figure_header(
        fig,
        "Ikke-lineært påkrevd O30-areal ved 1,0 V",
        "Alle åtte receiverpunkter når målet; ingen strømtetthetsgate er brukt.",
    )
    ax.set_xlabel("Receiver-kapasitetsmultiplikator, R")
    ax.set_ylabel("Påkrevd aktivt areal [m²]")
    ax.set_ylim(8800, 12550)
    ax.set_xlim(0.92, 3.12)
    ax.yaxis.set_major_formatter(FuncFormatter(norwegian_integer))
    ax.grid(axis="y")
    ax.legend(loc="lower left", fontsize=8.5)
    ax.spines[["top", "right"]].set_visible(False)
    finish_figure(fig, output_dir, "o30_required_area_curve")


def tradeoff_index_figure(curve: pd.DataFrame, output_dir: Path) -> None:
    x = curve["receiver_capacity_multiplier"].to_numpy(float)
    base = curve.iloc[0]
    area_index = 100.0 * curve["required_active_area_m2"] / base[
        "required_active_area_m2"
    ]
    airflow_index = 100.0 * curve["analysis_receiver_airflow_cfm"] / base[
        "analysis_receiver_airflow_cfm"
    ]
    core_index = 100.0 * curve["analysis_core_power_kw"] / base[
        "analysis_core_power_kw"
    ]

    fig, ax = plt.subplots(figsize=(7.15, 4.0))
    ax.plot(x, area_index, color=TEAL, marker="o", lw=2.2, label="Aktivt areal")
    ax.plot(
        x,
        airflow_index,
        color=ORANGE,
        marker="o",
        lw=2.2,
        label="Receiverluft",
    )
    ax.plot(
        x,
        core_index,
        color=NAVY,
        marker="o",
        lw=2.2,
        label="Kjerneeffekt",
    )
    ax.axhline(100.0, color="#9CAAB6", lw=0.9, linestyle=(0, (3, 3)))
    ax.annotate(
        "−13,51 %",
        xy=(3.0, area_index.iloc[-1]),
        xytext=(2.45, 70),
        color=TEAL,
        weight="bold",
        arrowprops=dict(arrowstyle="->", color=TEAL),
    )
    ax.annotate(
        "+197 %",
        xy=(3.0, airflow_index.iloc[-1]),
        xytext=(2.34, 267),
        color="#9A5718",
        weight="bold",
        arrowprops=dict(arrowstyle="->", color=ORANGE),
    )
    ax.annotate(
        "+3,46 %",
        xy=(3.0, core_index.iloc[-1]),
        xytext=(2.38, 125),
        color=NAVY,
        weight="bold",
        arrowprops=dict(arrowstyle="->", color=NAVY),
    )
    add_figure_header(
        fig,
        "Mer receiverluft kjøper areal – men med raskt avtagende nytte",
        "Indeks: R=1,01 er satt til 100 for hver størrelse.",
    )
    ax.set_xlabel("Receiver-kapasitetsmultiplikator, R")
    ax.set_ylabel("Relativ verdi [indeks]")
    ax.set_ylim(55, 320)
    ax.set_xlim(0.92, 3.12)
    ax.grid(axis="y")
    ax.legend(loc="upper left", ncols=3, fontsize=8.3)
    ax.spines[["top", "right"]].set_visible(False)
    finish_figure(fig, output_dir, "receiver_tradeoff_index")


def geometry_replay_figure(replay_path: Path, output_dir: Path) -> None:
    comparison = pd.read_csv(replay_path)
    row = comparison.loc[
        comparison["replay_candidate_id"].eq("legacy_O50_case_310")
    ].iloc[0]
    default_fans = (
        row["default_process_channel_fan_power_kw"]
        + row["default_receiver_channel_fan_power_kw"]
    )
    candidate_fans = (
        row["candidate_process_channel_fan_power_kw"]
        + row["candidate_receiver_channel_fan_power_kw"]
    )
    ratios = np.array(
        [
            100.0
            * row["candidate_required_active_area_m2"]
            / row["default_required_active_area_m2"],
            100.0
            * row["candidate_maximum_local_current_density_a_m2"]
            / row["default_maximum_local_current_density_a_m2"],
            100.0 * candidate_fans / default_fans,
            100.0
            * row["candidate_analysis_core_power_kw"]
            / row["default_analysis_core_power_kw"],
            100.0
            * row["candidate_eo_grid_power_kw"]
            / row["default_eo_grid_power_kw"],
        ]
    )
    labels = [
        "Aktivt areal",
        "Maks. lokal strøm",
        "Kanalvifter",
        "Kjerneeffekt",
        "EO-effekt fra nettet",
    ]
    y = np.arange(len(labels))

    fig, ax = plt.subplots(figsize=(7.15, 3.75))
    ax.barh(y + 0.18, np.full(len(labels), 100.0), height=0.32, color=LIGHT, label="Standardgeometri")
    bars = ax.barh(y - 0.18, ratios, height=0.32, color=TEAL, label="Legacy case 310-geometri")
    for bar, value in zip(bars, ratios):
        ax.text(
            value + 3.0,
            bar.get_y() + bar.get_height() / 2,
            f"{value:.0f}",
            va="center",
            fontsize=8.5,
            color=DARK,
        )
    ax.axvline(100.0, color="#8EA0AF", lw=0.9)
    ax.set_yticks(y, labels)
    ax.invert_yaxis()
    ax.set_xlim(0, 220)
    ax.set_xlabel("Indeks [standardgeometri = 100]")
    add_figure_header(
        fig,
        "Kontrollert O50-replay: geometri flytter systembalansen",
        "Samme materiale, spenning og receiverpunkt – kun geometrien endres.",
        left=0.22,
    )
    ax.grid(axis="x")
    ax.legend(loc="lower right", fontsize=8.4)
    ax.spines[["top", "right", "left"]].set_visible(False)
    finish_figure(fig, output_dir, "o50_geometry_replay")


def conditional_energy_figure(output_dir: Path) -> None:
    labels = [
        "O80\nkompressor",
        "O30\nkompressor",
        "Brutto\nmulighet",
        "Historisk\nkjerne",
    ]
    values = [1167.33, 382.44, 784.89, 115.02]
    colors = [SLATE, NAVY, ORANGE, TEAL]

    fig, ax = plt.subplots(figsize=(7.15, 3.75))
    bars = ax.bar(labels, values, color=colors, width=0.62)
    for index, (bar, value) in enumerate(zip(bars, values)):
        if index == 3:
            continue
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value + 28,
            norwegian_integer(value),
            ha="center",
            va="bottom",
            weight="bold",
            fontsize=9,
        )
    ax.text(
        2,
        665,
        "≈180 Wh/L\n(betinget)",
        ha="center",
        va="center",
        color="#7A4715",
        fontsize=9.5,
        weight="bold",
    )
    ax.text(
        3,
        235,
        "≈26,3 Wh/L\n(historisk kjerne)",
        ha="center",
        va="center",
        color="#006A6A",
        fontsize=8.7,
        weight="bold",
    )
    ax.set_ylim(0, 1300)
    ax.set_ylabel("Elektrisk effekt [kW]")
    add_figure_header(
        fig,
        "Det opprinnelige energirommet er stort – men ikke en systemsparing",
        "Deklarerte kompressorankre uten ERV og historisk kjerneeffekt; ikke komplett hjelpeanlegg.",
    )
    ax.grid(axis="y")
    ax.spines[["top", "right"]].set_visible(False)
    finish_figure(fig, output_dir, "conditional_energy_window")


def post_erv_energy_figure(metrics: pd.DataFrame, output_dir: Path) -> None:
    values = metrics.set_index(["study_id", "metric_id"])["numeric_value"]
    reference = values["post_erv_10pct", "passive_erv_plus_ac_reference"]
    saving = values["post_erv_10pct", "best_real_film_saving"]
    addon = values["post_erv_10pct", "best_real_film_addon_power"]
    conditional_total = reference - saving

    labels = ["Passiv ERV\n+ AC", "EO-polering\n+ AC", "Betinget\nmargin"]
    bar_values = [reference, conditional_total, saving]
    colors = [SLATE, TEAL, ORANGE]
    fig, ax = plt.subplots(figsize=(7.15, 3.8))
    bars = ax.bar(labels, bar_values, color=colors, width=0.58)
    for bar, value in zip(bars, bar_values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value + 12,
            f"{value:.2f}".replace(".", ",") + " kW",
            ha="center",
            va="bottom",
            fontsize=9,
            weight="bold",
        )
    ax.annotate(
        f"EO + avgrenset modulvifte:\n{addon:.2f} kW".replace(".", ","),
        xy=(1, conditional_total),
        xytext=(1.45, 335),
        fontsize=8.5,
        color=NAVY,
        arrowprops=dict(arrowstyle="->", color=NAVY, lw=1.0),
    )
    ax.text(
        2,
        150,
        "9,76 %",
        ha="center",
        color="#8A5018",
        fontsize=12,
        weight="bold",
    )
    ax.set_ylim(0, 620)
    ax.set_ylabel("Elektrisk effekt [kW]")
    add_figure_header(
        fig,
        "Post-ERV-polering gir det mest interessante energirommet",
        "Samme screeningbasis; real receiverfilm, uniform 5 A/m². Ikke komplett systempåstand.",
    )
    ax.grid(axis="y")
    ax.spines[["top", "right"]].set_visible(False)
    finish_figure(fig, output_dir, "post_erv_conditional_energy")


def diffusivity_sensitivity_figure(diffusivity: pd.DataFrame, output_dir: Path) -> None:
    x = diffusivity["water_diffusivity_m2_s"].to_numpy(float)
    saving = diffusivity[
        "best_incremental_saving_pct_vs_passive_erv"
    ].to_numpy(float)
    area = diffusivity["best_required_active_area_m2"].to_numpy(float)

    fig, ax = plt.subplots(figsize=(7.15, 4.0))
    ax2 = ax.twinx()
    line1 = ax.semilogx(
        x,
        saving,
        color=TEAL,
        marker="o",
        lw=2.3,
        label="Betinget energimargin",
    )[0]
    line2 = ax2.semilogx(
        x,
        area,
        color=ORANGE,
        marker="s",
        lw=2.0,
        label="Påkrevd areal",
    )[0]
    for xv, sv, av in zip(x, saving, area):
        ax.annotate(
            f"{sv:.2f} %".replace(".", ","),
            (xv, sv),
            xytext=(0, 8),
            textcoords="offset points",
            ha="center",
            fontsize=8.0,
            color="#006F6F",
        )
        ax2.annotate(
            norwegian_integer(av) + " m²",
            (xv, av),
            xytext=(0, -15),
            textcoords="offset points",
            ha="center",
            fontsize=7.7,
            color="#945216",
        )
    ax.set_xlabel("Vann-diffusivitet, D [m²/s] (log-skala)")
    ax.set_ylabel("Betinget margin mot passiv ERV [%]", color=TEAL)
    ax2.set_ylabel("Påkrevd aktivt areal [m²]", color=ORANGE)
    ax.set_ylim(4.7, 10.8)
    ax2.set_ylim(0, 5900)
    ax.grid(axis="both")
    ax.spines["top"].set_visible(False)
    ax2.spines["top"].set_visible(False)
    ax.legend([line1, line2], [line1.get_label(), line2.get_label()], loc="lower left")
    add_figure_header(
        fig,
        "Positiv margin består – men høy diffusivitet betales i areal",
        "12 studiecaser: fire D-verdier × tre strømtettheter; beste rad per D vises.",
    )
    finish_figure(fig, output_dir, "post_erv_diffusivity_sensitivity")


def boundary_sensitivity_figure(metrics: pd.DataFrame, output_dir: Path) -> None:
    values = metrics.set_index(["study_id", "metric_id"])["numeric_value"]
    post = values["post_erv_10pct", "best_real_film_saving"]
    detailed = values["post_erv_physics_closure", "best_detailed_saving"]
    lower = values["post_erv_physics_closure", "uncertainty_minimum"]
    upper = values["post_erv_physics_closure", "uncertainty_maximum"]
    coupled = values["material_condensation", "counterflow_coupled_saving"]
    historic = values["receiver_regeneration_v39", "historical_net_saving"]

    labels = [
        "Post-ERV\nscreeningstudie",
        "Detaljert HVAC\nsmoke",
        "Koblet kondensator\nsmoke",
        "Historisk receiver-\nregenerering",
    ]
    y = np.arange(len(labels))[::-1]
    points = np.array([post, detailed, coupled, historic])
    colors = [TEAL, NAVY, ORANGE, RED]
    fig, ax = plt.subplots(figsize=(7.15, 4.0))
    ax.axvline(0.0, color="#536675", lw=1.2)
    ax.errorbar(
        detailed,
        y[1],
        xerr=np.array([[detailed - lower], [upper - detailed]]),
        fmt="none",
        ecolor=LIGHT,
        elinewidth=10,
        capsize=5,
        zorder=1,
    )
    for yi, value, color in zip(y, points, colors):
        ax.scatter(value, yi, s=85, color=color, zorder=3)
        ax.text(
            value + (7 if value >= 0 else -7),
            yi,
            f"{value:+.1f} kW".replace(".", ","),
            va="center",
            ha="left" if value >= 0 else "right",
            fontsize=8.5,
            weight="bold",
            color=color,
        )
    ax.text(
        (lower + upper) / 2,
        y[1] - 0.42,
        f"Deterministisk scenarioomslag: {lower:.0f} til +{upper:.0f} kW".replace(".", ","),
        ha="center",
        fontsize=7.8,
        color=SLATE,
    )
    ax.set_yticks(y, labels)
    ax.set_xlim(-175, 175)
    ax.set_xlabel("Rapportert margin i hver studies egen systemgrense [kW]")
    ax.grid(axis="x")
    ax.spines[["top", "right", "left"]].set_visible(False)
    add_figure_header(
        fig,
        "Receiver- og termikkgrensen kan snu fortegnet",
        "Punktene har ulike modellgrenser og skal ikke rangeres direkte; smoke og historisk studie er tydelig merket.",
        left=0.25,
    )
    finish_figure(fig, output_dir, "boundary_sensitivity")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--geometry-replay-csv",
        type=Path,
        default=(
            ROOT.parent
            / "XMembrane_Model"
            / "outputs"
            / "wp1_geometry_candidate_replay_v1"
            / "candidate_vs_default_geometry.csv"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    setup_style()
    curve = pd.read_csv(
        ROOT / "data" / "golden" / "o30" / "required_area_1v_curve_v1.csv"
    )
    area_curve_figure(curve, args.output_dir)
    tradeoff_index_figure(curve, args.output_dir)
    geometry_replay_figure(args.geometry_replay_csv, args.output_dir)
    conditional_energy_figure(args.output_dir)
    evidence_root = ROOT / "outputs" / "integrated_evidence_v1"
    metrics = pd.read_csv(evidence_root / "headline_metrics.csv")
    diffusivity = pd.read_csv(evidence_root / "diffusivity_summary.csv")
    post_erv_energy_figure(metrics, args.output_dir)
    diffusivity_sensitivity_figure(diffusivity, args.output_dir)
    boundary_sensitivity_figure(metrics, args.output_dir)
    print(f"Wrote report figures to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
