#!/usr/bin/env python3
"""Generate the cross-study figures for the complete result atlas."""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import ListedColormap
from matplotlib.ticker import FuncFormatter


ROOT = Path(__file__).resolve().parents[1]
HEIQ = ROOT.parent
V2 = HEIQ / "HeiQ_V2"

NAVY = "#17324D"
TEAL = "#008C8C"
TEAL2 = "#69C4C4"
ORANGE = "#E58B2A"
RED = "#B94A3D"
GREEN = "#2E7D5B"
SLATE = "#607284"
LIGHT = "#E8EFF4"
PALE = "#F5F8FA"
INK = "#172A3A"
PURPLE = "#765A9A"


def style() -> None:
    mpl.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 9.2,
            "axes.titlesize": 14,
            "axes.titleweight": "bold",
            "axes.labelsize": 10,
            "axes.edgecolor": "#A7B5C2",
            "axes.labelcolor": INK,
            "xtick.color": "#465B6B",
            "ytick.color": "#465B6B",
            "grid.color": "#D9E2E9",
            "grid.linewidth": 0.7,
            "legend.frameon": False,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "figure.facecolor": "white",
            "savefig.facecolor": "white",
        }
    )


def finish(fig: plt.Figure, out: Path, name: str) -> None:
    fig.savefig(out / f"{name}.pdf", bbox_inches="tight")
    fig.savefig(out / f"{name}.png", dpi=220, bbox_inches="tight")
    plt.close(fig)


def title(fig: plt.Figure, heading: str, subtitle: str, *, y: float = 0.965) -> None:
    fig.suptitle(heading, x=0.08, y=y, ha="left", fontsize=15, fontweight="bold", color=NAVY)
    fig.text(0.08, y - 0.055, subtitle, ha="left", va="top", fontsize=8.8, color=SLATE)


def norwegian(value: float, _pos: int | None = None) -> str:
    return f"{value:,.0f}".replace(",", " ")


def chronology(out: Path) -> None:
    lanes = ["Termo/HVAC", "Materiale", "Aksialmodell", "Receiver", "ERV/system"]
    lane_y = {name: len(lanes) - index - 1 for index, name in enumerate(lanes)}
    events = [
        (0, "Termo/HVAC", "SEC-ramme\n100–150 Wh/kg", "retained"),
        (4, "Termo/HVAC", "150k cfm\n469/775 kW gross", "conditional"),
        (5, "Materiale", "H-Nafion\n1.83–1.95 kWh/kg", "negative"),
        (7, "Materiale", "V2–V7\nproperty oracle", "historical"),
        (8, "Aksialmodell", "V3\n28/432, kun O50", "negative"),
        (10, "Aksialmodell", "V8\n32 256 rader", "retained"),
        (11, "Materiale", "V11\nspenningsvindu", "retained"),
        (12, "Receiver", "V12/V13\nkobling + regen", "negative"),
        (13, "Receiver", "V14\n80 positive, 0 fysisk", "negative"),
        (14, "Receiver", "O50/O30 closure\n0 robust/full", "negative"),
        (15, "Receiver", "V35–V44\n0 robust materiale", "negative"),
        (16, "ERV/system", "Modern ERV\ndirekte EO negativ", "negative"),
        (17, "Receiver", "Væske/totrinn\nikke lukket", "negative"),
        (18, "ERV/system", "Aktiv EO-ERV\n90→41→9→1→0", "negative"),
        (19, "Receiver", "Strømstyrt\n336→195; 0 kryss", "retained"),
        (20, "ERV/system", "Post-ERV +10%\n+53.07 kW betinget", "conditional"),
        (21, "Materiale", "D-følsomhet\n+6.1–9.8%", "conditional"),
        (22, "Receiver", "Eksakt O30 1 V\n10.5–12.1k m²", "retained"),
        (23, "ERV/system", "Systemledger\n118.39 kW + mangler", "negative"),
    ]
    colors = {"retained": TEAL, "conditional": ORANGE, "negative": RED, "historical": PURPLE}
    fig, ax = plt.subplots(figsize=(11.2, 5.8))
    for lane in lanes:
        y = lane_y[lane]
        ax.hlines(y, -0.3, 23.5, color="#CAD6DE", lw=1.0)
    for x, lane, label, status in events:
        y = lane_y[lane]
        ax.scatter(x, y, s=85, color=colors[status], edgecolor="white", linewidth=1.2, zorder=3)
        dy = 0.18 if (x + y) % 2 == 0 else -0.18
        va = "bottom" if dy > 0 else "top"
        ax.text(x, y + dy, label, ha="center", va=va, fontsize=7.5, color=INK, linespacing=1.1)
    ax.set_yticks([lane_y[name] for name in lanes], lanes)
    ax.set_xlim(-0.8, 24)
    ax.set_ylim(-0.65, 4.65)
    ax.set_xticks([0, 4, 8, 12, 16, 20, 23], ["2. jul", "9. jul", "29. jul", "4. aug", "7. aug", "24. aug", "26. aug"])
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.grid(False)
    handles = [plt.Line2D([0], [0], marker="o", color="none", markerfacecolor=c, markersize=8, label=l) for l, c in [("Beholdt læring", TEAL), ("Betinget mulighet", ORANGE), ("Negativ/ikke lukket", RED), ("Historisk oracle", PURPLE)]]
    ax.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.5, -0.18), ncols=4)
    title(fig, "Resultatlinjen 2. juli–26. august", "Historien er et progressivt skifte fra energipotensial og fantasy-materialer til receiver-, domene- og systemlukking.")
    fig.subplots_adjust(top=0.80, bottom=0.18, left=0.12, right=0.99)
    finish(fig, out, "01_chronology_swimlane")


def hvac_opportunity(out: Path) -> None:
    path = V2 / "outputs/wp1_free_predrying_explicit_cop/free_predrying_energy_cop_summary.csv"
    frame = pd.read_csv(path).set_index("case").loc[["O80", "O50", "O30"]]
    labels = ["O80\n32°C / 80%", "O50\n32°C / 50%", "O30\n32°C / 30%"]
    fig, axes = plt.subplots(1, 3, figsize=(10.6, 3.9))
    values = [
        ("Kjølelast", frame["cooling_removed_kw"].to_numpy(), "kW termisk", TEAL),
        ("Kompressoreffekt", frame["compressor_electric_kw"].to_numpy(), "kW elektrisk", NAVY),
        ("Aircon-COP", frame["cop_cooling"].to_numpy(), "–", ORANGE),
    ]
    for ax, (heading, data, ylabel, color) in zip(axes, values):
        bars = ax.bar(labels, data, color=[SLATE, color, color], alpha=0.95)
        for bar, val in zip(bars, data):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() * 1.02, f"{val:,.1f}".replace(",", " "), ha="center", va="bottom", fontsize=8.4, color=INK)
        ax.set_title(heading, fontsize=11, color=NAVY)
        ax.set_ylabel(ylabel)
        ax.set_ylim(0, max(data) * 1.18)
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="y")
    title(fig, "Den tidlige HVAC-muligheten var reell – men brutto", "50 000 cfm, eksplisitt COP. Tallene er kompressor-/coil-resultater før komplett EO-receiver, varmeavvisning og modul.")
    fig.subplots_adjust(top=0.73, bottom=0.17, left=0.07, right=0.99, wspace=0.38)
    finish(fig, out, "02_hvac_opportunity")


def sec_ladder(out: Path) -> None:
    rows = [
        ("H-Nafion, 1 V\nnegativ kontroll", 1.83, 1.95, RED, "korrelert referanse"),
        ("H-Nafion, optimistisk drag", 0.58, 0.62, RED, "fortsatt over budsjett"),
        ("V13 wall-admissible regen", 0.2277, 0.2277, RED, "receiverpakke"),
        ("V39 kjølt receiver", 0.18049, 0.18049, RED, "lukket stresstest"),
        ("Post-ERV break-even", 0.157, 0.157, TEAL, "total EO-subsystem"),
        ("Tidlig 10% konservativ ramme", 0.100, 0.150, TEAL, "termodynamisk"),
        ("V14 full pre-dryer O30", 0.1075, 0.1075, ORANGE, "betinget"),
        ("V14 full pre-dryer O50", 0.0894, 0.0894, ORANGE, "betinget"),
        ("Post-ERV D=1e-9", 0.06807, 0.06807, ORANGE, "enparameter"),
        ("V12 valgt core", 0.02634, 0.02634, PURPLE, "ufullstendig core"),
        ("Post-ERV best screen", 0.01517, 0.01517, ORANGE, "ufullstendig add-on"),
    ]
    fig, ax = plt.subplots(figsize=(9.4, 5.4))
    y = np.arange(len(rows))[::-1]
    for yi, (label, lo, hi, color, note) in zip(y, rows):
        if hi > lo:
            ax.hlines(yi, lo, hi, color=color, lw=7, alpha=0.85)
            ax.scatter([lo, hi], [yi, yi], color=color, s=35, zorder=3)
        else:
            ax.scatter(lo, yi, color=color, s=68, zorder=3)
        ax.text(hi * 1.08, yi, note, va="center", fontsize=7.8, color=SLATE)
    ax.set_yticks(y, [r[0] for r in rows])
    ax.set_xscale("log")
    ax.set_xlim(0.01, 2.8)
    ax.set_xlabel("Spesifikk elektrisitet [kWh/kg fjernet vann] – log-skala")
    ax.grid(axis="x", which="both")
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.tick_params(axis="y", length=0)
    title(fig, "SEC-resultatene svarer på forskjellige spørsmål", "Lav core-SEC er ikke et systemresultat. Høyre side viser hvorfor receiver-/materiallukking kan spise energivinduet.")
    fig.subplots_adjust(top=0.80, bottom=0.12, left=0.30, right=0.93)
    finish(fig, out, "03_sec_evidence_ladder")


def v8_v11_tradeoff(out: Path) -> None:
    points = [
        ("V8 O50 lav effekt", 5871.6, 13.57, "O50", "V8"),
        ("V8 O50 min areal+", 1056.5, 289.19, "O50", "V8"),
        ("V8 O30 lav effekt", 5530.1, 128.26, "O30", "V8"),
        ("V8 O30 min areal+", 2169.5, 476.03, "O30", "V8"),
        ("V11 O50 lav effekt", 5872, 13.57, "O50", "V11"),
        ("V11 O50 min areal", 1039, 296.12, "O50", "V11"),
        ("V11 O30 lav effekt", 5922, 123.51, "O30", "V11"),
        ("V11 O30 min areal", 2131, 487.26, "O30", "V11"),
        ("V12 O30 valgt", 8922, 115.02, "O30", "V12"),
    ]
    fig, ax = plt.subplots(figsize=(8.8, 5.1))
    colors = {"O50": TEAL, "O30": ORANGE}
    markers = {"V8": "o", "V11": "s", "V12": "D"}
    for label, area, power, target_name, version in points:
        ax.scatter(area, power, s=90, color=colors[target_name], marker=markers[version], edgecolor="white", linewidth=1.1, zorder=3)
        ax.annotate(label, (area, power), xytext=(5, 5), textcoords="offset points", fontsize=7.3, color=INK)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Aktivt membranareal [m²] – log-skala")
    ax.set_ylabel("Rapportert hjelpe-/core-effekt [kW] – log-skala")
    ax.grid(which="both")
    ax.spines[["top", "right"]].set_visible(False)
    handles = []
    for target_name, color in colors.items():
        handles.append(plt.Line2D([0], [0], marker="o", color="none", markerfacecolor=color, markersize=8, label=target_name))
    for version, marker in markers.items():
        handles.append(plt.Line2D([0], [0], marker=marker, color=SLATE, linestyle="none", markersize=7, label=version))
    ax.legend(handles=handles, ncols=5, loc="lower left")
    title(fig, "V8–V12: mindre areal ble kjøpt med mye høyere effekt", "Historiske receiver- og effektgrenser varierer. Figuren viser utvikling/trade-off, ikke en felles systemranking.")
    fig.subplots_adjust(top=0.78, bottom=0.13, left=0.11, right=0.98)
    finish(fig, out, "04_v8_v11_area_power_tradeoff")


def search_funnels(out: Path) -> None:
    studies = [
        ("Aksial V3", [432, 28, 0], ["samplet", "mål", "O30"]),
        ("V8 O30", [16128, 864, 608], ["samplet", "mål", "energi+"]),
        ("V14", [50688, 80, 0], ["arkitektur", "aritmetikk+", "fysisk"]),
        ("V38 Nafion/krav", [18, 8, 0], ["materialer", "arealrot", "full gate"]),
        ("V44 robust", [432, 0, 0], ["samplet", "robust", "system"]),
        ("Aktiv EO-ERV", [90, 9, 0], ["fullført", "engineering", "fullkoblet"]),
    ]
    fig, axes = plt.subplots(2, 3, figsize=(10.8, 6.2))
    for ax, (name, vals, labels) in zip(axes.flat, studies):
        x = np.arange(3)
        bars = ax.bar(x, vals, color=[SLATE, ORANGE, RED])
        ax.set_yscale("symlog", linthresh=1)
        ax.set_xticks(x, labels, rotation=15, ha="right")
        ax.set_title(name, fontsize=10.5, color=NAVY)
        for bar, value in zip(bars, vals):
            ax.text(bar.get_x() + bar.get_width() / 2, max(value, 0.7) * 1.12, f"{value:,}".replace(",", " "), ha="center", fontsize=8, color=INK)
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="y")
    title(fig, "Mer fysikk ga færre – ikke flere – gyldige resultater", "Funnene er ikke ett sekvensielt felles funnel; hvert panel viser sin egen studie og sin egen siste port.")
    fig.subplots_adjust(top=0.82, bottom=0.11, left=0.07, right=0.99, wspace=0.32, hspace=0.55)
    finish(fig, out, "05_search_and_gate_funnels")


def receiver_sensitivity(out: Path) -> None:
    labels = ["V12\nreceiver 0.4–0.6", "2× begge\ngassfilmer", "10× begge\ngassfilmer", "Receiver\n0.1–0.3"]
    powers = [115.02, 90.69, 65.10, 23.61]
    colors = [NAVY, TEAL, TEAL2, ORANGE]
    fig, ax = plt.subplots(figsize=(8.5, 4.2))
    bars = ax.bar(labels, powers, color=colors)
    for bar, val in zip(bars, powers):
        ax.text(bar.get_x() + bar.get_width() / 2, val + 3, f"{val:.1f} kW", ha="center", fontsize=9, fontweight="bold", color=INK)
    ax.set_ylim(0, 132)
    ax.set_ylabel("Historisk O30 core-effekt [kW]")
    ax.grid(axis="y")
    ax.spines[["top", "right"]].set_visible(False)
    title(fig, "Receiveraktivitet slo materialfinjustering", "V12/Terminal 2: filmforbedring og tørrere receiver reduserer core-effekten, men er ikke gratis designvariabler.")
    fig.subplots_adjust(top=0.75, bottom=0.16, left=0.10, right=0.98)
    finish(fig, out, "06_receiver_sensitivity_v12")


def fixed_voltage_receiver(out: Path) -> None:
    best_path = V2 / "outputs/terminal1_receiver_mechanism_map_v1_smoke/best_by_boundary_target.csv"
    ceiling_path = V2 / "outputs/terminal1_receiver_mechanism_map_v1_smoke/process_film_ceiling.csv"
    best = pd.read_csv(best_path)
    ceiling = pd.read_csv(ceiling_path)
    boundaries = ["Real film\na=0.50", "Ideal film\na=0.50", "Tørr sink\na=0.05", "Rent vann\na≈1", "Prosessfilm-\ntak"]
    ids = ["controlled_a0p50_real_film", "controlled_a0p50_ideal_film", "dry_sink_a0p05", "pure_water_liquid"]
    fig, axes = plt.subplots(1, 2, figsize=(10.4, 4.5), sharey=False)
    for ax, target_name in zip(axes, ["O50", "O30"]):
        sub = best.loc[best["target"].eq(target_name)].set_index("boundary_id")
        vals = []
        for bid in ids:
            vals.append(sub.loc[bid, "required_active_area_m2"] if bid in sub.index else np.nan)
        vals.append(ceiling.loc[ceiling["target"].eq(target_name), "required_active_area_m2"].iloc[0])
        x = np.arange(len(vals))
        bars = ax.bar(x, np.nan_to_num(vals), color=[NAVY, TEAL, ORANGE, PURPLE, SLATE])
        for bar, val in zip(bars, vals):
            if np.isfinite(val):
                ax.text(bar.get_x() + bar.get_width() / 2, val * 1.02, f"{val:,.0f}".replace(",", " "), ha="center", va="bottom", fontsize=7.8)
            else:
                ax.text(bar.get_x() + bar.get_width() / 2, 200, "mål ikke nådd", ha="center", va="bottom", fontsize=7.2, color=RED, rotation=90)
        ax.set_xticks(x, boundaries, fontsize=7.5)
        ax.set_title(target_name, color=NAVY)
        ax.set_ylabel("Påkrevd areal ved 1.96 V [m²]")
        ax.yaxis.set_major_formatter(FuncFormatter(norwegian))
        ax.grid(axis="y")
        ax.spines[["top", "right"]].set_visible(False)
    title(fig, "Fast spenning: receiverfilm gir ~44 % arealstraff", "Rent vann er en våt, ikke tørr, sink. Tørr-sink og prosessfilm er øvre grenser med null vedlikeholdsenergi.")
    fig.subplots_adjust(top=0.75, bottom=0.22, left=0.08, right=0.99, wspace=0.28)
    finish(fig, out, "07_fixed_voltage_receiver_boundaries")


def current_control_matrix(out: Path) -> None:
    path = V2 / "outputs/terminal1_current_controlled_receiver_v2_study/current_control_cases.csv"
    frame = pd.read_csv(path)
    valid = frame.loc[frame["target_reached"] & frame["mechanism_case_valid"]].copy()
    fig, axes = plt.subplots(1, 2, figsize=(9.4, 4.4))
    for ax, target_name in zip(axes, ["O50", "O30"]):
        sub = valid.loc[valid["target"].eq(target_name)]
        neg = sub["negative_required_voltage_area_fraction"].gt(0)
        pos = sub["passive_surface_direction_positive_everywhere"]
        matrix = np.array(
            [
                [int((~neg & ~pos).sum()), int((~neg & pos).sum())],
                [int((neg & ~pos).sum()), int((neg & pos).sum())],
            ]
        )
        ax.imshow(matrix, cmap=ListedColormap([PALE, "#F8D8D3", "#F4C57D", "#D5ECEC"]), vmin=0, vmax=max(matrix.max(), 1))
        for (i, j), value in np.ndenumerate(matrix):
            ax.text(j, i, str(value), ha="center", va="center", fontsize=18, fontweight="bold", color=NAVY)
        ax.set_xticks([0, 1], ["Passiv retning\nikke positiv", "Passiv retning\npositiv"])
        ax.set_yticks([0, 1], ["Ingen negativt\nspenningsområde", "Negativt\nspenningsområde"])
        ax.set_title(f"{target_name}: {len(sub)} gyldige målpass", color=NAVY)
    title(fig, "0 av 195 lukker begge receiverdiagnostikkene samtidig", "Positiv passiv overflateretning og fravær av negativt lokalt spenningsområde er kryssdiagnostikk – ikke formelle hardware-gates.")
    fig.subplots_adjust(top=0.73, bottom=0.17, left=0.15, right=0.98, wspace=0.42)
    finish(fig, out, "08_current_control_receiver_crossmatrix")


def liquid_receiver(out: Path) -> None:
    labels = ["O50 gas\nV12 core", "O50 væske\na=0.7", "O50 rent vann", "O30 gas\nV12 core", "O30 væske\na=0.7", "O30 rent vann"]
    powers = [16.43, 43.85, 85.07, 115.02, 168.26, 237.11]
    phase = [0, 1781.81, 1781.81, 0, 2941.39, 2941.39]
    target_colors = [TEAL, TEAL2, PURPLE, ORANGE, "#F0B15B", RED]
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.5))
    x = np.arange(len(labels))
    axes[0].bar(x, powers, color=target_colors)
    axes[0].set_xticks(x, labels, rotation=22, ha="right", fontsize=7.5)
    axes[0].set_ylabel("Rapportert core [kW]")
    axes[0].set_title("Elektrisk core", color=NAVY)
    axes[1].bar(x, phase, color=target_colors)
    axes[1].set_xticks(x, labels, rotation=22, ha="right", fontsize=7.5)
    axes[1].set_ylabel("Fasevarme-proxy [kW termisk]")
    axes[1].set_title("Varme som må håndteres", color=NAVY)
    for ax in axes:
        ax.grid(axis="y")
        ax.spines[["top", "right"]].set_visible(False)
    title(fig, "Direkte væske var ikke en gratis receiver", "Aktivitet 0.7–1 var 27–69 kW verre for O50 og 53–122 kW verre for O30 enn de historiske gassreferansene.")
    fig.subplots_adjust(top=0.74, bottom=0.28, left=0.08, right=0.99, wspace=0.30)
    finish(fig, out, "09_liquid_receiver_penalty")


def energy_boundaries(out: Path) -> None:
    panels = [
        ("Historisk no-ERV", [("V12 O30", 669.87), ("V14 O50", 225.9), ("V14 O30", 286.8)]),
        ("Direkte mot modern ERV", [("O50", -362.51), ("O30", -218.55)]),
        ("Aktiv EO-ERV", [("robust rad", -86.10), ("engineering rad", 58.60)]),
        ("Post-ERV / lukking", [("post-ERV screen", 53.07), ("detaljert smoke", 47.97), ("koblet thermal", -32.78), ("v39 regenerering", -91.58)]),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(10.4, 6.5))
    for ax, (heading, values) in zip(axes.flat, panels):
        labels = [v[0] for v in values]
        nums = [v[1] for v in values]
        colors = [TEAL if v >= 0 else RED for v in nums]
        y = np.arange(len(nums))
        ax.barh(y, nums, color=colors)
        ax.axvline(0, color=SLATE, lw=1)
        ax.set_yticks(y, labels)
        ax.set_title(heading, color=NAVY, fontsize=11)
        for yi, val in zip(y, nums):
            ax.text(val + (8 if val >= 0 else -8), yi, f"{val:+.1f}", ha="left" if val >= 0 else "right", va="center", fontsize=8.2, fontweight="bold")
        ax.grid(axis="x")
        ax.spines[["top", "right", "left"]].set_visible(False)
        ax.tick_params(axis="y", length=0)
    title(fig, "Fortegnet avhenger av systemgrensen", "Panelene har ulike komparatorer og skal aldri summeres eller rangeres som én felles besparelsesliste.")
    fig.text(0.5, 0.03, "Betinget effektmargin [kW] – positivt til høyre", ha="center", color=INK)
    fig.subplots_adjust(top=0.82, bottom=0.10, left=0.17, right=0.98, wspace=0.35, hspace=0.42)
    finish(fig, out, "10_energy_boundaries_separate_panels")


def post_erv_diffusivity(out: Path) -> None:
    path = V2 / "outputs/archive_terminal1_post_erv_diffusivity_sensitivity_v1_20260825T084804Z/best_case_by_diffusivity.csv"
    frame = pd.read_csv(path)
    x = frame["water_diffusivity_m2_s"].to_numpy()
    fig, axes = plt.subplots(1, 3, figsize=(10.6, 3.9))
    series = [
        ("Påkrevd areal", frame["best_required_active_area_m2"], "m²", TEAL),
        ("Betinget margin", frame["best_incremental_saving_kw_vs_passive_erv"], "kW", ORANGE),
        ("Motdiffusjon / EO", 100 * frame["best_absolute_diffusion_fraction_of_eo"], "%", RED),
    ]
    for ax, (heading, y, ylabel, color) in zip(axes, series):
        ax.plot(x, y, marker="o", lw=2.2, color=color)
        ax.set_xscale("log")
        ax.set_title(heading, color=NAVY, fontsize=10.5)
        ax.set_xlabel("D [m²/s]")
        ax.set_ylabel(ylabel)
        ax.grid(which="both")
        ax.spines[["top", "right"]].set_visible(False)
    title(fig, "Høyere diffusivitet spiser areal og transportmargin", "Post-ERV-enparameterstudie: marginen er fortsatt positiv ved 10⁻⁹ m²/s, men området er ikke materialbevis.")
    fig.subplots_adjust(top=0.72, bottom=0.18, left=0.07, right=0.99, wspace=0.36)
    finish(fig, out, "11_post_erv_diffusivity")


def exact_o30(out: Path) -> None:
    path = ROOT / "data/golden/o30/required_area_1v_curve_v1.csv"
    frame = pd.read_csv(path)
    x = frame["analysis_receiver_airflow_cfm"] / 1000
    area = frame["required_active_area_m2"]
    power = frame["analysis_core_power_kw"]
    fig, ax1 = plt.subplots(figsize=(8.9, 4.7))
    ax2 = ax1.twinx()
    ax1.plot(x, area, color=TEAL, marker="o", lw=2.4, label="Påkrevd areal")
    ax2.plot(x, power, color=ORANGE, marker="s", lw=2.0, label="Core-effekt")
    ax1.set_xlabel("Receiverluft [1000 cfm]")
    ax1.set_ylabel("Aktivt areal [m²]", color=TEAL)
    ax2.set_ylabel("Core-effekt [kW]", color=ORANGE)
    ax1.yaxis.set_major_formatter(FuncFormatter(norwegian))
    ax1.grid(axis="both")
    ax1.spines["top"].set_visible(False)
    ax2.spines["top"].set_visible(False)
    ax1.annotate("+197 % receiverluft", xy=(x.iloc[-1], area.iloc[-1]), xytext=(760, 11800), arrowprops=dict(arrowstyle="->", color=SLATE), color=SLATE)
    ax1.annotate("−13.51 % areal", xy=(x.iloc[-1], area.iloc[-1]), xytext=(830, 10580), arrowprops=dict(arrowstyle="->", color=TEAL), color=TEAL, fontweight="bold")
    handles = ax1.get_lines() + ax2.get_lines()
    ax1.legend(handles, [line.get_label() for line in handles], loc="center right")
    title(fig, "Eksakt O30 ved 1.0 V: raskt avtagende nytte av receiverluft", "8/8 punkter når målet uten strømgrense eller design-arealtak; dette er en lokal gasreceiverkurve, ikke en systemoptimering.")
    fig.subplots_adjust(top=0.75, bottom=0.13, left=0.11, right=0.89)
    finish(fig, out, "12_exact_o30_receiver_tradeoff")


def architecture_matrix(out: Path) -> None:
    rows = [
        "V12 valgt gasreceiver",
        "V14 valgt O50",
        "V14 valgt O30",
        "O50 single-stage closure",
        "O30 single-stage closure",
        "Two-stage receiver",
        "V39 kjølt loop",
        "Direkte væske",
        "Aktiv EO-ERV",
        "Post-ERV +10%",
        "Dagens systemledger",
    ]
    cols = ["Vannmål", "Overflate", "Modul", "Receiverenergi", "Modern comparator", "Fullsystem"]
    # 2 pass/currently supported, 1 conditional/open, 0 fail/absent
    values = np.array(
        [
            [2, 0, 0, 0, 0, 0],
            [2, 0, 1, 1, 0, 0],
            [2, 0, 1, 1, 0, 0],
            [2, 1, 0, 1, 0, 0],
            [2, 0, 0, 1, 0, 0],
            [2, 1, 0, 1, 0, 0],
            [2, 1, 1, 2, 0, 0],
            [2, 0, 0, 0, 0, 0],
            [2, 1, 0, 1, 2, 0],
            [2, 0, 0, 0, 2, 0],
            [2, 1, 1, 0, 1, 0],
        ]
    )
    cmap = ListedColormap(["#F2B7AF", "#F4D29B", "#A9D8C4"])
    fig, ax = plt.subplots(figsize=(9.8, 6.1))
    ax.imshow(values, cmap=cmap, vmin=0, vmax=2, aspect="auto")
    symbols = {0: "×", 1: "åpen", 2: "✓"}
    for (i, j), value in np.ndenumerate(values):
        ax.text(j, i, symbols[int(value)], ha="center", va="center", fontsize=10, fontweight="bold", color=INK)
    ax.set_xticks(np.arange(len(cols)), cols, rotation=20, ha="right")
    ax.set_yticks(np.arange(len(rows)), rows)
    ax.set_xticks(np.arange(-0.5, len(cols), 1), minor=True)
    ax.set_yticks(np.arange(-0.5, len(rows), 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=2)
    ax.tick_params(which="minor", bottom=False, left=False)
    title(fig, "Receiver-/systematlas: vannmålet alene er ikke nok", "✓ betyr lukket innen studiens avgrensning; «åpen» betyr betinget/ufullstendig; × betyr feilet eller ikke modellert.")
    fig.subplots_adjust(top=0.80, bottom=0.16, left=0.30, right=0.98)
    finish(fig, out, "13_architecture_closure_matrix")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    style()
    chronology(args.output_dir)
    hvac_opportunity(args.output_dir)
    sec_ladder(args.output_dir)
    v8_v11_tradeoff(args.output_dir)
    search_funnels(args.output_dir)
    receiver_sensitivity(args.output_dir)
    fixed_voltage_receiver(args.output_dir)
    current_control_matrix(args.output_dir)
    liquid_receiver(args.output_dir)
    energy_boundaries(args.output_dir)
    post_erv_diffusivity(args.output_dir)
    exact_o30(args.output_dir)
    architecture_matrix(args.output_dir)


if __name__ == "__main__":
    main()
