#!/usr/bin/env python3
"""Create like-for-like AC, passive-ERV and active-ERV comparisons."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/heiq-architecture-comparison-mpl")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WEATHER_DATA = (
    ROOT / "reports" / "workshop_diffusivity_energy_v1" / "data" / "system_bar_data.csv"
)
DEFAULT_ACTIVE_DATA = (
    ROOT
    / "outputs"
    / "integrated_active_erv_weather_v1"
    / "active_erv_weather_energy.csv"
)
DEFAULT_OUTPUT = ROOT / "outputs" / "integrated_active_erv_weather_v1"
WEATHER_ORDER = ["O80", "O50", "O30"]

NAVY = "#17324D"
TEAL = "#008C8C"
SLATE = "#607284"
LIGHT = "#E8EFF4"
DARK = "#172A3A"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weather-data", type=Path, default=DEFAULT_WEATHER_DATA)
    parser.add_argument("--active-data", type=Path, default=DEFAULT_ACTIVE_DATA)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def setup_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 9.5,
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


def load_energy_data(weather_path: Path, active_path: Path) -> pd.DataFrame:
    weather = pd.read_csv(weather_path)
    active = pd.read_csv(active_path)
    records: list[dict[str, float | str]] = []
    for state in WEATHER_ORDER:
        ac = weather.loc[
            weather["diagram_id"].eq("ac_only_weather")
            & weather["state_id"].eq(state),
            "total_power_kw",
        ]
        passive = weather.loc[
            weather["diagram_id"].eq("ac_erv_weather")
            & weather["state_id"].eq(state),
            "total_power_kw",
        ]
        active_row = active.loc[active["weather_state"].eq(state)]
        if len(ac) != 1 or len(passive) != 1 or len(active_row) != 1:
            raise ValueError(f"Expected one AC, passive and active row for {state}")
        if float(active_row.iloc[0]["remaining_ac_water_removed_kg_h"]) != 0.0:
            raise ValueError(f"Active-ERV coil condenses water at {state}")
        records.append(
            {
                "weather_state": state,
                "ac_only_kw": float(ac.iloc[0]),
                "passive_erv_plus_ac_kw": float(passive.iloc[0]),
                "active_erv_plus_sensible_ac_kw": float(
                    active_row.iloc[0]["active_erv_plus_ac_total_power_kw"]
                ),
            }
        )
    return pd.DataFrame(records)


def comparison_table(energy: pd.DataFrame) -> pd.DataFrame:
    definitions = [
        (
            "passive_erv_vs_ac",
            "Passive ERV + AC vs AC only",
            "ac_only_kw",
            "passive_erv_plus_ac_kw",
            "AC only",
            "Passive ERV + AC",
        ),
        (
            "active_erv_vs_passive",
            "Active EO-ERV + sensible AC vs passive ERV + AC",
            "passive_erv_plus_ac_kw",
            "active_erv_plus_sensible_ac_kw",
            "Passive ERV + AC",
            "Active EO-ERV + sensible AC",
        ),
        (
            "active_erv_vs_ac",
            "Active EO-ERV + sensible AC vs AC only",
            "ac_only_kw",
            "active_erv_plus_sensible_ac_kw",
            "AC only",
            "Active EO-ERV + sensible AC",
        ),
    ]
    rows: list[dict[str, float | str]] = []
    for comparison_id, label, baseline_col, candidate_col, baseline_label, candidate_label in definitions:
        for record in energy.to_dict("records"):
            baseline = float(record[baseline_col])
            candidate = float(record[candidate_col])
            reduction = baseline - candidate
            rows.append(
                {
                    "comparison_id": comparison_id,
                    "comparison_label": label,
                    "weather_state": record["weather_state"],
                    "baseline_label": baseline_label,
                    "candidate_label": candidate_label,
                    "baseline_power_kw": baseline,
                    "candidate_power_kw": candidate,
                    "reduction_kw": reduction,
                    "reduction_pct": 100.0 * reduction / baseline,
                }
            )
    frame = pd.DataFrame(rows)
    if not frame["reduction_kw"].gt(0.0).all():
        raise AssertionError("At least one architecture comparison is not a reduction")
    return frame


def save(fig: plt.Figure, figure_dir: Path, stem: str) -> None:
    fig.savefig(figure_dir / f"{stem}.pdf", bbox_inches="tight")
    fig.savefig(figure_dir / f"{stem}.png", dpi=220, bbox_inches="tight")
    plt.close(fig)


def paired_plot(group: pd.DataFrame, figure_dir: Path, stem: str) -> None:
    group = group.set_index("weather_state").loc[WEATHER_ORDER].reset_index()
    x = np.arange(len(group))
    width = 0.34
    baseline = group["baseline_power_kw"].to_numpy(float)
    candidate = group["candidate_power_kw"].to_numpy(float)

    fig, ax = plt.subplots(figsize=(7.15, 4.15))
    left = ax.bar(
        x - width / 2,
        baseline,
        width,
        color=SLATE,
        label=str(group.iloc[0]["baseline_label"]),
    )
    right = ax.bar(
        x + width / 2,
        candidate,
        width,
        color=TEAL,
        label=str(group.iloc[0]["candidate_label"]),
    )
    y_max = float(max(baseline)) * 1.24
    for index, row in group.iterrows():
        ax.text(
            left[index].get_x() + left[index].get_width() / 2,
            baseline[index] * 0.5,
            f"{baseline[index]:,.1f}",
            ha="center",
            va="center",
            color="white",
            fontsize=8.3,
            fontweight="bold",
        )
        ax.text(
            right[index].get_x() + right[index].get_width() / 2,
            candidate[index] * 0.5,
            f"{candidate[index]:,.1f}",
            ha="center",
            va="center",
            color="white",
            fontsize=8.3,
            fontweight="bold",
        )
        ax.text(
            x[index],
            max(baseline[index], candidate[index]) + 0.035 * y_max,
            f"save {row.reduction_kw:,.1f} kW\n({row.reduction_pct:.1f}%)",
            ha="center",
            va="bottom",
            color=NAVY,
            fontsize=8.4,
        )
    fig.suptitle(
        str(group.iloc[0]["comparison_label"]),
        x=0.105,
        y=0.975,
        ha="left",
        fontsize=14,
        fontweight="bold",
    )
    fig.text(
        0.105,
        0.905,
        "Like-for-like electricity at the same outdoor weather state and the same 20°C/50% RH supply service.",
        ha="left",
        va="top",
        color=SLATE,
        fontsize=8.6,
    )
    ax.set_xticks(x, group["weather_state"])
    ax.set_ylabel("Electrical power at the duty point [kW]")
    ax.set_ylim(0.0, y_max)
    ax.grid(axis="y")
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(loc="upper right", ncols=2, fontsize=8.0)
    fig.subplots_adjust(top=0.79, left=0.105, right=0.98, bottom=0.18)
    save(fig, figure_dir, stem)


def overview_plot(comparisons: pd.DataFrame, figure_dir: Path) -> None:
    row_order = [
        "passive_erv_vs_ac",
        "active_erv_vs_passive",
        "active_erv_vs_ac",
    ]
    row_labels = [
        "Passive ERV + AC\nvs AC only",
        "Active EO-ERV + sensible AC\nvs passive ERV + AC",
        "Active EO-ERV + sensible AC\nvs AC only",
    ]
    pct = np.zeros((3, 3))
    kw = np.zeros((3, 3))
    for row_index, comparison_id in enumerate(row_order):
        group = comparisons.loc[comparisons["comparison_id"].eq(comparison_id)]
        group = group.set_index("weather_state").loc[WEATHER_ORDER]
        pct[row_index, :] = group["reduction_pct"].to_numpy(float)
        kw[row_index, :] = group["reduction_kw"].to_numpy(float)

    cmap = LinearSegmentedColormap.from_list("heiq_teal", [LIGHT, "#69C4C4", TEAL])
    fig, ax = plt.subplots(figsize=(7.15, 4.25))
    image = ax.imshow(pct, cmap=cmap, vmin=0.0, vmax=100.0, aspect="auto")
    for row in range(3):
        for column in range(3):
            colour = "white" if pct[row, column] >= 65.0 else NAVY
            ax.text(
                column,
                row,
                f"{pct[row, column]:.1f}%\n{kw[row, column]:,.1f} kW",
                ha="center",
                va="center",
                color=colour,
                fontsize=9.2,
                fontweight="bold",
            )
    ax.set_xticks(np.arange(3), WEATHER_ORDER)
    ax.set_yticks(np.arange(3), row_labels)
    ax.tick_params(axis="y", length=0, labelsize=8.5)
    ax.tick_params(axis="x", length=0)
    for edge in np.arange(-0.5, 3.5, 1.0):
        ax.axhline(edge, color="white", lw=2.0)
        ax.axvline(edge, color="white", lw=2.0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    colourbar = fig.colorbar(image, ax=ax, fraction=0.025, pad=0.025)
    colourbar.set_label("Electrical reduction [%]")
    fig.suptitle(
        "Like-for-like architecture reductions across O80, O50 and O30",
        x=0.19,
        y=0.98,
        ha="left",
        fontsize=14,
        fontweight="bold",
    )
    fig.text(
        0.19,
        0.915,
        "Each cell shows reduction relative to the named baseline at the same weather state: percent, then kW.",
        ha="left",
        va="top",
        color=SLATE,
        fontsize=8.6,
    )
    fig.subplots_adjust(top=0.79, left=0.33, right=0.91, bottom=0.13)
    save(fig, figure_dir, "architecture_comparison_overview")


def run(weather_path: Path, active_path: Path, output: Path) -> pd.DataFrame:
    setup_style()
    output.mkdir(parents=True, exist_ok=True)
    figure_dir = output / "figures"
    figure_dir.mkdir(parents=True, exist_ok=True)
    energy = load_energy_data(weather_path, active_path)
    comparisons = comparison_table(energy)
    comparisons.to_csv(output / "architecture_comparison_data.csv", index=False)
    stems = {
        "passive_erv_vs_ac": "comparison_passive_erv_vs_ac",
        "active_erv_vs_passive": "comparison_active_erv_vs_passive_erv",
        "active_erv_vs_ac": "comparison_active_erv_vs_ac",
    }
    for comparison_id, stem in stems.items():
        paired_plot(
            comparisons.loc[comparisons["comparison_id"].eq(comparison_id)].copy(),
            figure_dir,
            stem,
        )
    overview_plot(comparisons, figure_dir)
    manifest = {
        "weather_source": str(weather_path.resolve()),
        "active_source": str(active_path.resolve()),
        "comparison_rule": "baseline minus candidate at the same weather state",
        "service_boundary": "32 degC outdoor state to 20 degC / 50 %RH supply",
        "active_architecture_note": (
            "EO in the ERV membrane removes all water; remaining AC removes "
            "zero water and supplies sensible cooling only"
        ),
        "claim_boundary": (
            "active EO-ERV results are conditional reduced-order screens; O30 "
            "fails the current stack-voltage gate"
        ),
    }
    (output / "architecture_comparison_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return comparisons


def main() -> None:
    args = parse_args()
    frame = run(
        args.weather_data.resolve(),
        args.active_data.resolve(),
        args.output_dir.resolve(),
    )
    print(
        frame[
            [
                "comparison_id",
                "weather_state",
                "reduction_kw",
                "reduction_pct",
            ]
        ].to_string(index=False)
    )


if __name__ == "__main__":
    main()
