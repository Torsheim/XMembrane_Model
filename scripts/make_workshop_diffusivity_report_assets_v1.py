#!/usr/bin/env python3
"""Build the auditable data tables and figures for the 2026-08-28 workshop note.

The primary membrane calculation is the registered post-passive-ERV,
counter-current, finite-gas-film sweep.  All membrane properties are frozen at
the hypothetical Terminal-1 inverse-design coordinate except water
diffusivity.  Current density is a sampled operating coordinate, not an
acceptance gate.  The selection rule is target reached, balanced receiver,
maximum local terminal voltage <= 2 V, then maximum conditional electrical
saving before unmodelled receiver/sink terms.

The script also packages three explicitly different energy comparisons:

* AC-only at O80/O50/O30 outdoor states;
* passive ERV + AC at the same three outdoor states; and
* fixed O80 outdoor air with passive ERV followed by EO to the O50/O30
  absolute-humidity coordinates.

The distinctions are deliberate: mixing these boundaries is the main way to
produce an apparently spectacular but invalid saving comparison.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import shutil
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable, Mapping

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
WATER_MOLAR_MASS_KG_MOL = 0.01801528

NAVY = "#17324D"
TEAL = "#008C8C"
TEAL_LIGHT = "#69C4C4"
ORANGE = "#E58B2A"
RED = "#B94A3D"
SLATE = "#607284"
LIGHT = "#E8EFF4"
DARK = "#172A3A"

PHYSICAL_D_VALUES = np.array([1.0e-14, 1.0e-13, 1.0e-12, 1.0e-11, 1.0e-10, 1.0e-9])
TARGET_ORDER = ["post_erv_10pct", "o30", "full_remaining_latent"]
TARGET_LABELS = {
    "post_erv_10pct": "Historical post-ERV point",
    "o30": "O30 post-ERV target",
    "full_remaining_latent": "Full remaining duty",
}


class AssetError(RuntimeError):
    """Raised when a frozen workshop invariant is not satisfied."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description="Generate workshop report tables and figures.",
    )
    parser.add_argument(
        "--transport-dir",
        type=Path,
        default=ROOT / "outputs" / "workshop_diffusivity_energy_v1",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=ROOT / "reports" / "workshop_diffusivity_energy_v1",
    )
    parser.add_argument(
        "--v2-root", type=Path, default=Path("/home/torsheim/HeiQ/HeiQ_V2")
    )
    return parser.parse_args()


def setup_style() -> None:
    mpl.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 9.5,
            "axes.titlesize": 13.5,
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


def add_header(
    fig: plt.Figure,
    title: str,
    subtitle: str,
    *,
    left: float = 0.10,
    top: float = 0.79,
) -> None:
    fig.suptitle(title, x=left, y=0.975, ha="left", fontsize=14, fontweight="bold")
    fig.text(left, 0.905, subtitle, ha="left", va="top", fontsize=8.6, color=SLATE)
    fig.subplots_adjust(top=top, left=left, right=0.98, bottom=0.18)


def finish(fig: plt.Figure, directory: Path, name: str) -> None:
    fig.savefig(directory / f"{name}.pdf", bbox_inches="tight")
    fig.savefig(directory / f"{name}.png", dpi=220, bbox_inches="tight")
    plt.close(fig)


def bool_series(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series.fillna(False)
    if pd.api.types.is_numeric_dtype(series):
        return series.fillna(0).astype(float).ne(0.0)
    return series.astype(str).str.strip().str.lower().isin({"true", "1", "yes", "y"})


def load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssetError(f"Could not load module: {path}")
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


def select_diffusivity_optima(cases: pd.DataFrame) -> pd.DataFrame:
    frame = cases.copy()
    reached = bool_series(frame["target_reached"])
    censored = bool_series(frame["area_is_right_censored"])
    frame = frame.loc[
        reached
        & ~censored
        & np.isclose(frame["receiver_to_process_dry_air_ratio"], 1.0)
        & frame["maximum_required_terminal_voltage_signed_v"].le(2.0 + 1.0e-10)
    ].copy()

    rows: list[dict[str, Any]] = []
    for target in TARGET_ORDER:
        for diffusivity in PHYSICAL_D_VALUES:
            candidate = frame.loc[
                frame["target_id"].eq(target)
                & np.isclose(
                    frame["water_diffusivity_m2_s"], diffusivity, rtol=1.0e-10, atol=0.0
                )
            ].copy()
            if candidate.empty:
                rows.append(
                    {
                        "target_id": target,
                        "target_label": TARGET_LABELS[target],
                        "water_diffusivity_m2_s": diffusivity,
                        "feasible_under_2v_sampled_grid": False,
                        "selection_status": "no target-reaching sampled row at or below 2 V",
                    }
                )
                continue
            ranking = (
                "control_regime_conservative_saving_kw_before_receiver_sink"
                if target == "full_remaining_latent"
                else "incremental_saving_kw_vs_passive_erv"
            )
            selected = candidate.sort_values(
                [ranking, "required_active_area_m2", "uniform_current_density_a_m2"],
                ascending=[False, True, True],
            ).iloc[0]
            row = selected.to_dict()
            row.update(
                {
                    "target_label": TARGET_LABELS[target],
                    "feasible_under_2v_sampled_grid": True,
                    "selection_status": "selected conditional uniform-current row",
                    "reported_saving_kw": float(selected[ranking]),
                    "reported_saving_pct_vs_passive_erv": 100.0
                    * float(selected[ranking])
                    / float(selected["passive_erv_plus_ac_reference_kw"]),
                    "reported_total_kw": float(selected["passive_erv_plus_ac_reference_kw"])
                    - float(selected[ranking]),
                    "reported_saving_branch": (
                        "near-endpoint conservative coil-control branch"
                        if target == "full_remaining_latent"
                        else "native matched coil branch"
                    ),
                }
            )
            rows.append(row)
    result = pd.DataFrame(rows)
    expected = len(TARGET_ORDER) * len(PHYSICAL_D_VALUES)
    if len(result) != expected:
        raise AssetError(f"Expected {expected} selected coordinates, found {len(result)}")
    return result


def selected_row(
    optima: pd.DataFrame, target: str, diffusivity: float
) -> pd.Series:
    rows = optima.loc[
        optima["target_id"].eq(target)
        & np.isclose(
            optima["water_diffusivity_m2_s"], diffusivity, rtol=1.0e-10, atol=0.0
        )
        & bool_series(optima["feasible_under_2v_sampled_grid"])
    ]
    if len(rows) != 1:
        raise AssetError(f"Expected one selected row for {target}, D={diffusivity:g}")
    return rows.iloc[0]


def make_system_energy_data() -> tuple[pd.DataFrame, Any, Mapping[str, Any], Mapping[str, Any]]:
    active = load_module(
        ROOT / "src" / "heiq" / "wp1" / "studies" / "direct_eo_erv.py",
        "workshop_active_erv",
    )
    config = json.loads(
        (ROOT / "config" / "direct_eo_erv_study_v1.json").read_text(
            encoding="utf-8"
        )
    )
    states = active.states_from_config(config)
    baseline = active.build_passive_baseline(
        config,
        states,
        float(config["passive_baseline_erv"]["sensible_effectiveness"]),
    )
    pressure = float(config["boundary"]["pressure_pa"])
    m_da = float(config["boundary"]["process_outdoor_dry_air_kg_s"])
    rows: list[dict[str, Any]] = []
    for label, rh in (("O80", 0.80), ("O50", 0.50), ("O30", 0.30)):
        outdoor = active.state_from_t_rh(32.0, rh, pressure, f"{label} at 32 C")
        coil = active.solve_coil(
            inlet=outdoor,
            supply_target=states["supply"],
            m_da=m_da,
            rated_cop=baseline.rated_cop,
            ac_config=config["ac_model"],
        )
        rows.append(
            {
                "diagram_id": "ac_only_weather",
                "state_id": label,
                "state_definition": f"32 C/{100 * rh:.0f}% RH outdoor inlet",
                "humidity_ratio_g_kg_da": 1000.0 * outdoor.w,
                "ac_power_kw": coil.total_ac_power_kw,
                "erv_power_kw": 0.0,
                "eo_and_module_power_kw": 0.0,
                "total_power_kw": coil.total_ac_power_kw,
                "comparison_boundary": "weather-state comparison; no pre-dryer energy",
            }
        )
        erv = active.run_erv(
            oa_in=outdoor,
            exhaust_in=states["exhaust"],
            m_oa=m_da,
            m_exhaust=m_da,
            sensible_effectiveness=float(
                config["passive_baseline_erv"]["sensible_effectiveness"]
            ),
            latent_effectiveness=float(
                config["passive_baseline_erv"]["latent_effectiveness"]
            ),
            pressure_drop_each_side_pa=float(
                config["passive_baseline_erv"]["pressure_drop_each_side_pa"]
            ),
            fan_efficiency=float(config["passive_baseline_erv"]["fan_efficiency"]),
            motor_power_kw=float(config["passive_baseline_erv"]["motor_power_kw"]),
        )
        erv_coil = active.solve_coil(
            inlet=erv.oa_out,
            supply_target=states["supply"],
            m_da=m_da,
            rated_cop=baseline.rated_cop,
            ac_config=config["ac_model"],
        )
        rows.append(
            {
                "diagram_id": "ac_erv_weather",
                "state_id": label,
                "state_definition": f"32 C/{100 * rh:.0f}% RH outdoor inlet",
                "humidity_ratio_g_kg_da": 1000.0 * outdoor.w,
                "post_erv_humidity_ratio_g_kg_da": 1000.0 * erv.oa_out.w,
                "ac_power_kw": erv_coil.total_ac_power_kw,
                "erv_power_kw": erv.total_power_kw,
                "eo_and_module_power_kw": 0.0,
                "total_power_kw": erv.total_power_kw + erv_coil.total_ac_power_kw,
                "comparison_boundary": "weather-state comparison through passive ERV",
            }
        )
    result = pd.DataFrame(rows)
    if not math.isclose(
        float(
            result.loc[
                result["diagram_id"].eq("ac_only_weather")
                & result["state_id"].eq("O80"),
                "total_power_kw",
            ].iloc[0]
        ),
        1166.4,
        abs_tol=1.0e-8,
    ):
        raise AssetError("Legacy AC anchor changed")
    if not math.isclose(baseline.total_power_kw, 543.7405641877893, abs_tol=5.0e-7):
        raise AssetError("Passive ERV + AC anchor changed")
    return result, active, config, {**states, "baseline": baseline}


def append_post_erv_eo_bars(
    energy: pd.DataFrame,
    optima: pd.DataFrame,
    state_bundle: Mapping[str, Any],
) -> pd.DataFrame:
    baseline = state_bundle["baseline"]
    reference = float(baseline.total_power_kw)
    o30 = selected_row(optima, "o30", 1.0e-14)
    extra = pd.DataFrame(
        [
            {
                "diagram_id": "ac_erv_eo_posterv",
                "state_id": "O80 / no EO",
                "state_definition": "fixed 32 C/80% RH outdoor; passive ERV + AC",
                "humidity_ratio_g_kg_da": 1000.0 * state_bundle["outdoor"].w,
                "ac_power_kw": baseline.remaining_ac.total_ac_power_kw,
                "erv_power_kw": baseline.passive_erv.total_power_kw,
                "eo_and_module_power_kw": 0.0,
                "total_power_kw": reference,
                "comparison_boundary": "fixed O80 outdoor; post-ERV EO target comparison",
            },
            {
                "diagram_id": "ac_erv_eo_posterv",
                "state_id": "O50 target",
                "state_definition": "post-ERV O50 absolute-humidity coordinate",
                "humidity_ratio_g_kg_da": 14.9522480769927,
                "ac_power_kw": baseline.remaining_ac.total_ac_power_kw,
                "erv_power_kw": baseline.passive_erv.total_power_kw,
                "eo_and_module_power_kw": 0.0,
                "total_power_kw": reference,
                "comparison_boundary": "no EO duty: passive ERV outlet is already drier than O50",
            },
            {
                "diagram_id": "ac_erv_eo_posterv",
                "state_id": "O30 target",
                "state_definition": "post-ERV EO to the O30 absolute-humidity coordinate",
                "humidity_ratio_g_kg_da": 8.8858981051461,
                "ac_power_kw": float(o30["remaining_ac_power_kw"]),
                "erv_power_kw": baseline.passive_erv.total_power_kw,
                "eo_and_module_power_kw": float(o30["incremental_eo_and_fan_power_kw"]),
                "total_power_kw": float(o30["reported_total_kw"]),
                "comparison_boundary": (
                    "conditional D=1e-14 uniform-current subtotal; receiver/sink omitted"
                ),
            },
        ]
    )
    return pd.concat([energy, extra], ignore_index=True, sort=False)


def energy_bar_figure(
    data: pd.DataFrame,
    diagram_id: str,
    title: str,
    subtitle: str,
    output_dir: Path,
    name: str,
) -> None:
    rows = data.loc[data["diagram_id"].eq(diagram_id)].copy()
    baseline = float(rows.iloc[0]["total_power_kw"])
    rows["saving_kw"] = baseline - rows["total_power_kw"]
    x = np.arange(len(rows))
    fig, ax = plt.subplots(figsize=(7.15, 4.15))
    bars = ax.bar(x, rows["total_power_kw"], color=TEAL, width=0.64, label="Electricity used")
    ax.bar(
        x,
        rows["saving_kw"],
        bottom=rows["total_power_kw"],
        color=LIGHT,
        width=0.64,
        label="Reduction from first bar",
    )
    for bar, used, saving in zip(bars, rows["total_power_kw"], rows["saving_kw"]):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            used * 0.5,
            f"{used:,.1f} kW",
            ha="center",
            va="center",
            color="white",
            fontweight="bold",
            fontsize=9,
        )
        if saving > 0.1:
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                used + saving * 0.5,
                f"save {saving:,.1f}\n({100 * saving / baseline:.1f}%)",
                ha="center",
                va="center",
                color=NAVY,
                fontsize=8.4,
            )
        elif saving <= 0.1 and bar.get_x() > -0.5:
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                used + 0.025 * baseline,
                "no change",
                ha="center",
                va="bottom",
                color=SLATE,
                fontsize=8.2,
            )
    add_header(fig, title, subtitle, left=0.105, top=0.79)
    ax.set_xticks(x, rows["state_id"])
    ax.set_ylabel("Electrical power at the duty point [kW]")
    ax.set_ylim(0.0, baseline * 1.16)
    ax.grid(axis="y")
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(loc="upper right", ncols=2, fontsize=8.2)
    finish(fig, output_dir, name)


def diffusivity_figures(optima: pd.DataFrame, output_dir: Path) -> None:
    fig, ax = plt.subplots(figsize=(7.15, 4.15))
    styles = {
        "post_erv_10pct": (TEAL, "o"),
        "o30": (NAVY, "s"),
        "full_remaining_latent": (ORANGE, "^"),
    }
    for target in TARGET_ORDER:
        group = optima.loc[optima["target_id"].eq(target)].sort_values(
            "water_diffusivity_m2_s"
        )
        ok = bool_series(group["feasible_under_2v_sampled_grid"])
        colour, marker = styles[target]
        ax.plot(
            group.loc[ok, "water_diffusivity_m2_s"],
            group.loc[ok, "reported_saving_kw"],
            color=colour,
            marker=marker,
            lw=2.0,
            ms=5.2,
            label=TARGET_LABELS[target],
        )
        if bool((~ok).any()):
            ax.scatter(
                group.loc[~ok, "water_diffusivity_m2_s"],
                np.zeros((~ok).sum()),
                marker="x",
                color=RED,
                s=55,
                zorder=5,
            )
    ax.axhline(0.0, color=RED, lw=1.1)
    ax.axvline(1.597880133581376e-14, color=SLATE, lw=1.0, linestyle=(0, (4, 3)))
    ax.text(
        1.80e-14,
        ax.get_ylim()[1] * 0.88,
        "inverse-design D anchor",
        color=SLATE,
        fontsize=8.0,
    )
    add_header(
        fig,
        "Back-diffusion erodes the conditional post-ERV energy window",
        "All other hypothetical membrane properties frozen; selected sampled row must reach the target at <=2 V. Full duty uses the conservative near-endpoint branch.",
    )
    ax.set_xscale("log")
    ax.set_xlabel(r"Water diffusivity, $D$ [m$^2$/s]")
    ax.set_ylabel("Conditional electricity reduction [kW]")
    ax.grid(which="both")
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(loc="upper right", fontsize=8.2)
    finish(fig, output_dir, "04_diffusivity_energy_saving")

    o30 = optima.loc[optima["target_id"].eq("o30")].sort_values(
        "water_diffusivity_m2_s"
    )
    fig, axes = plt.subplots(2, 2, figsize=(7.15, 6.0), sharex=True)
    panels = [
        ("uniform_current_density_a_m2", "Selected current density [A/m²]", TEAL),
        ("required_active_area_m2", "Required active area [m²]", NAVY),
        ("maximum_required_terminal_voltage_signed_v", "Maximum terminal voltage [V]", ORANGE),
        ("absolute_diffusion_fraction_of_eo", "|Back-diffusion| / EO flux [%]", RED),
    ]
    for ax, (column, ylabel, colour) in zip(axes.flat, panels):
        values = o30[column].to_numpy(float)
        if column == "absolute_diffusion_fraction_of_eo":
            values = 100.0 * values
        ax.plot(o30["water_diffusivity_m2_s"], values, color=colour, marker="o", lw=2.0)
        ax.set_xscale("log")
        ax.set_ylabel(ylabel)
        ax.grid(which="both")
        ax.spines[["top", "right"]].set_visible(False)
    axes[1, 0].set_xlabel(r"Water diffusivity, $D$ [m$^2$/s]")
    axes[1, 1].set_xlabel(r"Water diffusivity, $D$ [m$^2$/s]")
    fig.suptitle(
        "O30 operating coordinate moves sharply above D = 10⁻¹¹ m²/s",
        x=0.10,
        y=0.985,
        ha="left",
        fontsize=14,
        fontweight="bold",
    )
    fig.text(
        0.10,
        0.945,
        "Uniform-current screen, no current-density acceptance limit; area is an observed sizing result, not a design cap.",
        ha="left",
        fontsize=8.6,
        color=SLATE,
    )
    fig.tight_layout(rect=(0.02, 0.02, 1.0, 0.91))
    finish(fig, output_dir, "05_o30_operating_parameters")


def build_gradient_profiles(
    optima: pd.DataFrame,
    workshop_config: Mapping[str, Any],
    v2_root: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    maker = load_module(
        ROOT / "scripts" / "make_post_erv_full_eo_study_v1.py",
        "workshop_full_study_loader",
    )
    analyzer, runtime, _, _, _ = maker.load_runtime(
        workshop_config,
        v2_root=v2_root,
        area_step_m2=25.0,
    )
    rows: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    for diffusivity in (1.0e-14, 1.0e-9):
        selection = selected_row(optima, "o30", diffusivity)
        current = float(selection["uniform_current_density_a_m2"])
        target_w = float(selection["target_w_g_kg_da"]) / 1000.0
        inlet_w = float(runtime["process_in"].w)
        receiver_in_w = float(runtime["receiver_in"].w)
        m_da = float(runtime["dry_air_mass_flow_kg_s"])
        material = dict(runtime["anchor"])
        material["water_diffusivity_m2_s"] = diffusivity
        process_grid = np.linspace(inlet_w, target_w, 321)
        states: list[dict[str, Any]] = []
        for process_w in process_grid:
            receiver_w = receiver_in_w + (process_w - target_w)
            state = analyzer.local_state(
                runtime, material, float(process_w), float(receiver_w), current
            )
            if not bool(state.get("solution_ok", False)):
                raise AssetError(
                    f"Local gradient replay failed for D={diffusivity:g}: "
                    f"{state.get('solution_status')}"
                )
            states.append(state)
        areas = [0.0]
        for i in range(len(process_grid) - 1):
            flux = 0.5 * (
                float(states[i]["net_flux_mol_m2_s"])
                + float(states[i + 1]["net_flux_mol_m2_s"])
            )
            dw = float(process_grid[i] - process_grid[i + 1])
            areas.append(areas[-1] + m_da * dw / (WATER_MOLAR_MASS_KG_MOL * flux))
        total_area = areas[-1]
        checks.append(
            {
                "water_diffusivity_m2_s": diffusivity,
                "selected_required_area_m2": float(selection["required_active_area_m2"]),
                "profile_quadrature_area_m2": total_area,
                "relative_area_difference": (
                    total_area - float(selection["required_active_area_m2"])
                )
                / float(selection["required_active_area_m2"]),
            }
        )
        for process_w, area, state in zip(process_grid, areas, states):
            receiver_w = receiver_in_w + (process_w - target_w)
            rows.append(
                {
                    "target_id": "o30",
                    "water_diffusivity_m2_s": diffusivity,
                    "uniform_current_density_a_m2": current,
                    "cumulative_area_m2": area,
                    "normalized_area": area / total_area,
                    "process_humidity_ratio_g_kg_da": 1000.0 * process_w,
                    "receiver_humidity_ratio_g_kg_da": 1000.0 * receiver_w,
                    "source_bulk_activity": float(state["source_bulk_activity"]),
                    "source_surface_activity": float(state["source_surface_activity"]),
                    "receiver_bulk_activity": float(state["receiver_bulk_activity"]),
                    "receiver_surface_activity": float(state["receiver_surface_activity"]),
                    "eo_flux_mmol_m2_s": 1000.0 * float(state["eo_flux_mol_m2_s"]),
                    "diffusion_flux_mmol_m2_s": 1000.0
                    * float(state["diffusion_flux_mol_m2_s"]),
                    "net_flux_mmol_m2_s": 1000.0 * float(state["net_flux_mol_m2_s"]),
                    "required_terminal_voltage_v": float(
                        state["required_terminal_voltage_signed_v"]
                    ),
                }
            )
    return pd.DataFrame(rows), pd.DataFrame(checks)


def gradient_figure(profiles: pd.DataFrame, output_dir: Path) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(7.15, 6.1), sharex="col")
    for column, diffusivity in enumerate((1.0e-14, 1.0e-9)):
        group = profiles.loc[
            np.isclose(
                profiles["water_diffusivity_m2_s"],
                diffusivity,
                rtol=1.0e-10,
                atol=0.0,
            )
        ]
        x = group["normalized_area"]
        axes[0, column].plot(x, group["source_bulk_activity"], color=TEAL, lw=2.0, label="Process bulk")
        axes[0, column].plot(x, group["source_surface_activity"], color=TEAL, lw=1.5, ls="--", label="Process surface")
        axes[0, column].plot(x, group["receiver_bulk_activity"], color=NAVY, lw=2.0, label="Receiver bulk")
        axes[0, column].plot(x, group["receiver_surface_activity"], color=NAVY, lw=1.5, ls="--", label="Receiver surface")
        axes[0, column].set_title(rf"$D={diffusivity:.0e}$ m²/s")
        axes[0, column].set_ylabel("Water activity [-]")
        axes[0, column].grid()
        axes[0, column].spines[["top", "right"]].set_visible(False)
        axes[1, column].plot(x, group["eo_flux_mmol_m2_s"], color=TEAL, lw=2.0, label="EO drag")
        axes[1, column].plot(x, group["diffusion_flux_mmol_m2_s"], color=RED, lw=2.0, label="Diffusion")
        axes[1, column].plot(x, group["net_flux_mmol_m2_s"], color=NAVY, lw=2.2, label="Net")
        axes[1, column].axhline(0.0, color=SLATE, lw=0.8)
        axes[1, column].set_xlabel("Cumulative active area fraction [-]")
        axes[1, column].set_ylabel("Water flux [mmol m⁻² s⁻¹]")
        axes[1, column].grid()
        axes[1, column].spines[["top", "right"]].set_visible(False)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.52, 0.91), ncols=4, fontsize=7.8)
    handles, labels = axes[1, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", bbox_to_anchor=(0.52, 0.005), ncols=3, fontsize=8.0)
    fig.suptitle(
        "O30 gradients: the high-D case spends current cancelling back-diffusion",
        x=0.08,
        y=0.985,
        ha="left",
        fontsize=14,
        fontweight="bold",
    )
    fig.text(
        0.08,
        0.945,
        "Balanced counter-current gas receiver. Negative diffusion flux is transport back toward the process stream; EO still produces positive net transport.",
        ha="left",
        fontsize=8.4,
        color=SLATE,
    )
    fig.tight_layout(rect=(0.02, 0.05, 1.0, 0.88))
    finish(fig, output_dir, "06_o30_activity_and_flux_gradients")


def make_break_even_table(optima: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for target in TARGET_ORDER:
        selected = selected_row(optima, target, 1.0e-14)
        water = float(selected["incremental_water_removal_target_kg_h"])
        if target == "full_remaining_latent":
            break_even = float(
                selected["control_regime_conservative_receiver_sink_sec_budget_kwh_per_kg"]
                + selected["known_eo_core_and_module_fan_sec_kwh_per_kg"]
            )
            ac_reduction = 0.15670080744075676 * water
            branch = "near-endpoint conservative"
        else:
            break_even = float(selected["incremental_ac_power_reduction_kw"]) / water
            ac_reduction = float(selected["incremental_ac_power_reduction_kw"])
            branch = "native matched coil"
        power_180 = 0.180 * water
        rows.append(
            {
                "case_id": target,
                "case_label": TARGET_LABELS[target],
                "water_removed_kg_h": water,
                "gross_ac_reduction_kw": ac_reduction,
                "break_even_all_in_sec_kwh_kg": break_even,
                "power_at_180_wh_kg_kw": power_180,
                "saving_at_180_wh_kg_kw": ac_reduction - power_180,
                "control_branch": branch,
                "physical_decision_use": True,
            }
        )
    full = selected_row(optima, "full_remaining_latent", 1.0e-14)
    full_water = float(full["incremental_water_removal_target_kg_h"])
    exact_be = 0.2751956966376383
    rows.append(
        {
            "case_id": "full_exact_endpoint_diagnostic",
            "case_label": "Full duty, exact endpoint diagnostic",
            "water_removed_kg_h": full_water,
            "gross_ac_reduction_kw": exact_be * full_water,
            "break_even_all_in_sec_kwh_kg": exact_be,
            "power_at_180_wh_kg_kw": 0.180 * full_water,
            "saving_at_180_wh_kg_kw": (exact_be - 0.180) * full_water,
            "control_branch": "exact sensible-only endpoint discontinuity",
            "physical_decision_use": False,
        }
    )
    return pd.DataFrame(rows)


def break_even_figure(table: pd.DataFrame, output_dir: Path) -> None:
    x = np.arange(len(table))
    values = table["saving_at_180_wh_kg_kw"].to_numpy(float)
    colours = [RED if value < 0.0 else ORANGE for value in values]
    fig, ax = plt.subplots(figsize=(7.15, 4.2))
    bars = ax.bar(x, values, color=colours, width=0.62)
    bars[-1].set_hatch("///")
    for bar, value in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value + (7.0 if value >= 0.0 else -7.0),
            f"{value:+.1f} kW",
            ha="center",
            va="bottom" if value >= 0.0 else "top",
            fontsize=8.7,
            fontweight="bold",
            color=DARK,
        )
    ax.axhline(0.0, color=NAVY, lw=1.0)
    add_header(
        fig,
        "180 Wh/kg exceeds the conservative post-ERV break-even budget",
        "The hatched exact full-endpoint bar is a coil-control discontinuity and is not a decision allowance. Receiver/sink and all other EO power must fit inside the stated SEC.",
    )
    ax.set_xticks(
        x,
        ["Historical\npoint", "O30", "Full\nconservative", "Full exact\ndiagnostic"],
    )
    ax.set_ylabel("Net electricity reduction at 0.180 kWh/kg [kW]")
    ax.set_ylim(min(values) - 25.0, max(values) + 35.0)
    ax.grid(axis="y")
    ax.spines[["top", "right"]].set_visible(False)
    finish(fig, output_dir, "07_break_even_180whkg")


def cell_tables() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    geometry = pd.read_csv(ROOT / "outputs" / "eo_vapor_cell_sizing_v1" / "channel_geometry_envelope.csv")
    row = geometry.loc[
        np.isclose(geometry["active_area_cm2"], 25.0)
        & np.isclose(geometry["channel_gap_mm"], 2.0)
        & np.isclose(geometry["channel_velocity_m_s"], 1.0)
    ]
    if len(row) != 1:
        raise AssetError("Could not identify the nominal 25 cm2 test-cell geometry")
    nominal = row.copy()

    rates = pd.read_csv(ROOT / "outputs" / "eo_vapor_boundary_analysis_v1" / "nominal_cases.csv")
    scenario_meta = {
        "low_drag_slow_diffusion": (0.3, 10.0),
        "order_unity_slow_diffusion": (1.0, 10.0),
        "order_unity_fast_diffusion": (1.0, 10.0),
        "inverse_design_anchor": (100.06078708377692, 1.0),
    }
    rates["water_transport_number"] = rates["scenario_id"].map(
        lambda value: scenario_meta[value][0]
    )
    rates["current_density_a_m2"] = rates["scenario_id"].map(
        lambda value: scenario_meta[value][1]
    )
    rates["total_current_ma"] = rates["current_density_a_m2"] * 0.0025 * 1000.0

    closed = pd.read_csv(
        ROOT / "outputs" / "eo_vapor_boundary_analysis_v1" / "closed_loop_boundary_screen.csv"
    )
    closed = closed.loc[
        np.isclose(closed["gas_volume_l_per_side"], 5.0)
        & np.isclose(
            closed["effective_wall_plus_membrane_capacity_multiple_of_gas"], 0.0
        )
        & np.isclose(closed["temperature_mismatch_k"], 0.0)
    ].copy()
    if len(closed) != 4:
        raise AssetError("Expected four 5-L closed-loop scenarios")
    return nominal, rates, closed


def cell_rate_figure(rates: pd.DataFrame, output_dir: Path) -> None:
    labels = ["Low drag", "Order unity\nslow D", "Order unity\nD=10⁻¹⁰", "Inverse-design\nanchor"]
    x = np.arange(len(rates))
    fig, ax = plt.subplots(figsize=(7.15, 4.05))
    gross = ax.bar(x - 0.18, rates["gross_faradaic_rate_mg_h"], width=0.36, color=LIGHT, label="Gross Faradaic")
    net = ax.bar(x + 0.18, rates["nominal_odd_rate_mg_h"], width=0.36, color=TEAL, label="Modelled odd net")
    for bars in (gross, net):
        for bar in bars:
            value = bar.get_height()
            ax.text(bar.get_x() + bar.get_width() / 2, value + 3.0, f"{value:.1f}", ha="center", va="bottom", fontsize=7.7)
    add_header(
        fig,
        "Expected 25 cm² coupon-cell transport signal",
        "Nominal 2-mm, 6-L/min-per-side controlled-flow cell. These rates are not a true quiescent-air prediction.",
    )
    ax.set_xticks(x, labels)
    ax.set_ylabel("Water transport [mg/h]")
    ax.set_ylim(0.0, 195.0)
    ax.grid(axis="y")
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(loc="upper left", fontsize=8.2)
    finish(fig, output_dir, "08_coupon_cell_transport_rate")


def temperature_for_rh_at_w(active: ModuleType, w: float, rh: float, pressure: float) -> float:
    lo, hi = -40.0, 60.0
    for _ in range(160):
        mid = 0.5 * (lo + hi)
        trial = active.humidity_ratio_from_t_rh(mid, rh, pressure)
        if trial < w:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def parallel_path_tables(
    active: ModuleType,
    config: Mapping[str, Any],
    state_bundle: Mapping[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    pressure = float(config["boundary"]["pressure_pa"])
    m_da = float(config["boundary"]["process_outdoor_dry_air_kg_s"])
    target = state_bundle["supply"]
    rows: list[dict[str, Any]] = []
    summary: list[dict[str, Any]] = []
    starts = {
        "outdoor_direct": state_bundle["outdoor"],
        "post_passive_erv": state_bundle["baseline"].passive_erv.oa_out,
    }
    for architecture, start in starts.items():
        entry_t = temperature_for_rh_at_w(active, start.w, 0.85, pressure)
        strict_end_t = temperature_for_rh_at_w(active, target.w, 0.85, pressure)
        w_85_at_20 = active.humidity_ratio_from_t_rh(20.0, 0.85, pressure)
        total_water = m_da * (start.w - target.w) * 3600.0
        along_to_20 = m_da * max(start.w - w_85_at_20, 0.0) * 3600.0
        trim_at_20 = total_water - along_to_20
        start_h = active.moist_air_enthalpy_kj_kg_da(start.t_c, start.w)
        target_h = active.moist_air_enthalpy_kj_kg_da(target.t_c, target.w)
        strict_state = active.state_from_t_rh(strict_end_t, 0.85, pressure)
        gross_cooling_kw = m_da * (start_h - strict_state.h)
        reheat_kw = m_da * (target_h - strict_state.h)
        summary.append(
            {
                "architecture": architecture,
                "start_temperature_c": start.t_c,
                "start_rh": start.rh,
                "start_humidity_ratio_g_kg_da": 1000.0 * start.w,
                "rh85_entry_temperature_c": entry_t,
                "rh85_at_20_humidity_ratio_g_kg_da": 1000.0 * w_85_at_20,
                "strict_rh85_final_humidity_temperature_c": strict_end_t,
                "total_water_removal_kg_h": total_water,
                "water_removed_along_rh85_to_20_kg_h": along_to_20,
                "water_removed_along_rh85_to_20_pct": 100.0 * along_to_20 / total_water,
                "isothermal_trim_at_20_kg_h": trim_at_20,
                "isothermal_trim_at_20_pct": 100.0 * trim_at_20 / total_water,
                "endpoint_process_air_enthalpy_decrease_kw": m_da * (start_h - target_h),
                "strict_rh85_gross_cooling_kw": gross_cooling_kw,
                "strict_rh85_reheat_kw": reheat_kw,
                "strict_rh85_net_air_enthalpy_change_kw": gross_cooling_kw - reheat_kw,
                "claim_boundary": "psychrometric control envelope; no coupled EO/coil power ledger",
            }
        )
        # No-overcool 85%-ceiling path plus final isothermal EO trim.
        pre_t = np.linspace(float(start.t_c), entry_t, 35)
        for t_c in pre_t:
            rows.append(
                {
                    "architecture": architecture,
                    "path_id": "rh85_ceiling_no_overcool",
                    "stage": "sensible_to_rh85",
                    "temperature_c": t_c,
                    "humidity_ratio_g_kg_da": 1000.0 * start.w,
                    "relative_humidity": active.relative_humidity_from_t_w(t_c, start.w, pressure),
                    "cumulative_water_removed_kg_h": 0.0,
                }
            )
        ceiling_t = np.linspace(entry_t, 20.0, 90)
        for t_c in ceiling_t:
            w = active.humidity_ratio_from_t_rh(t_c, 0.85, pressure)
            rows.append(
                {
                    "architecture": architecture,
                    "path_id": "rh85_ceiling_no_overcool",
                    "stage": "cool_and_eo_at_rh85",
                    "temperature_c": t_c,
                    "humidity_ratio_g_kg_da": 1000.0 * w,
                    "relative_humidity": 0.85,
                    "cumulative_water_removed_kg_h": m_da * (start.w - w) * 3600.0,
                }
            )
        rows.append(
            {
                "architecture": architecture,
                "path_id": "rh85_ceiling_no_overcool",
                "stage": "isothermal_eo_trim",
                "temperature_c": 20.0,
                "humidity_ratio_g_kg_da": 1000.0 * target.w,
                "relative_humidity": target.rh,
                "cumulative_water_removed_kg_h": total_water,
            }
        )
        # EO-first bound.
        rows.extend(
            [
                {
                    "architecture": architecture,
                    "path_id": "eo_first",
                    "stage": "isothermal_eo_first",
                    "temperature_c": start.t_c,
                    "humidity_ratio_g_kg_da": 1000.0 * value,
                    "relative_humidity": active.relative_humidity_from_t_w(start.t_c, value, pressure),
                    "cumulative_water_removed_kg_h": m_da * (start.w - value) * 3600.0,
                }
                for value in np.linspace(start.w, target.w, 55)
            ]
        )
        rows.extend(
            [
                {
                    "architecture": architecture,
                    "path_id": "eo_first",
                    "stage": "sensible_after_eo",
                    "temperature_c": t_c,
                    "humidity_ratio_g_kg_da": 1000.0 * target.w,
                    "relative_humidity": active.relative_humidity_from_t_w(t_c, target.w, pressure),
                    "cumulative_water_removed_kg_h": total_water,
                }
                for t_c in np.linspace(start.t_c, target.t_c, 55)
            ]
        )
    return pd.DataFrame(rows), pd.DataFrame(summary)


def parallel_path_figure(paths: pd.DataFrame, output_dir: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(7.15, 3.9), sharey=True)
    titles = {"outdoor_direct": "Whole outdoor-air duty", "post_passive_erv": "After passive ERV"}
    for ax, architecture in zip(axes, ("outdoor_direct", "post_passive_erv")):
        group = paths.loc[paths["architecture"].eq(architecture)]
        for path_id, colour, label in (
            ("eo_first", NAVY, "EO first"),
            ("rh85_ceiling_no_overcool", TEAL, "EO + cooling, RH <=85%"),
        ):
            part = group.loc[group["path_id"].eq(path_id)]
            ax.plot(part["temperature_c"], part["humidity_ratio_g_kg_da"], color=colour, lw=2.2, label=label)
        ax.scatter([20.0], [7.26028059345441], color=ORANGE, marker="X", s=55, zorder=5)
        ax.set_title(titles[architecture])
        ax.set_xlabel("Process-air temperature [°C]")
        ax.grid()
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].set_ylabel("Humidity ratio [g/kg dry air]")
    axes[0].legend(loc="upper left", fontsize=7.8)
    fig.suptitle(
        "PRI2 control paths change the activity gradient, not the endpoint load",
        x=0.08,
        y=0.99,
        ha="left",
        fontsize=14,
        fontweight="bold",
    )
    fig.text(
        0.08,
        0.925,
        "The 85% line is a psychrometric control envelope only. A temperature-resolved EO/coil model is still required before assigning electrical power.",
        ha="left",
        fontsize=8.3,
        color=SLATE,
    )
    fig.tight_layout(rect=(0.02, 0.03, 1.0, 0.86))
    finish(fig, output_dir, "09_pri2_eo_first_vs_parallel")


def pri2_limit_table(optima: pd.DataFrame) -> pd.DataFrame:
    o30_zero = selected_row(optima, "o30", 1.0e-14)
    proxy_cases = pd.read_csv(
        ROOT / "outputs" / "workshop_diffusivity_energy_v1" / "transport_cases.csv"
    )
    numerical_zero = proxy_cases.loc[
        proxy_cases["target_id"].eq("o30")
        & np.isclose(
            proxy_cases["water_diffusivity_m2_s"], 1.0e-20, rtol=1.0e-10, atol=0.0
        )
        & np.isclose(proxy_cases["uniform_current_density_a_m2"], 3.0)
        & bool_series(proxy_cases["target_reached"])
    ].iloc[0]
    no_mu_incremental = (
        (
            float(o30_zero["membrane_ohmic_power_kw"])
            + float(o30_zero["series_asr_power_kw"])
            + float(o30_zero["fixed_loss_power_kw"])
        )
        / 0.9
        + float(o30_zero["incremental_module_fan_power_kw"])
    )
    liquid = pd.read_csv(
        ROOT
        / "outputs"
        / "trond_system_closure_v2_no_current_gate"
        / "liquid_local_upper_bound.csv"
    )
    pure = liquid.loc[
        liquid["target"].eq("O30")
        & np.isclose(liquid["liquid_activity"], 0.999999)
        & liquid["solution_ok"].eq(True)
        & liquid["terminal_voltage_v"].le(2.0)
    ].sort_values("gravity_free_heat_sink_total_kw").iloc[0]
    return pd.DataFrame(
        [
            {
                "case_id": "finite_D_gas_receiver",
                "case_label": "Finite-D gas receiver, D=1e-14",
                "boundary": "post-ERV O30",
                "known_incremental_power_kw": float(o30_zero["incremental_eo_and_fan_power_kw"]),
                "conditional_saving_kw": float(o30_zero["reported_saving_kw"]),
                "area_m2": float(o30_zero["required_active_area_m2"]),
                "maximum_voltage_v": float(o30_zero["maximum_required_terminal_voltage_signed_v"]),
                "physical_claim_eligible": True,
                "interpretation": "physical conditional finite-film screen; receiver/sink still open",
            },
            {
                "case_id": "numerical_zero_D",
                "case_label": "Numerical no-back-diffusion limit, D=1e-20",
                "boundary": "post-ERV O30",
                "known_incremental_power_kw": float(numerical_zero["incremental_eo_and_fan_power_kw"]),
                "conditional_saving_kw": float(numerical_zero["incremental_saving_kw_vs_passive_erv"]),
                "area_m2": float(numerical_zero["required_active_area_m2"]),
                "maximum_voltage_v": float(numerical_zero["maximum_required_terminal_voltage_signed_v"]),
                "physical_claim_eligible": False,
                "interpretation": "asymptotic convergence control; canonical kernel does not accept exact D=0",
            },
            {
                "case_id": "zero_water_chemical_potential",
                "case_label": "Force water chemical-potential voltage to zero",
                "boundary": "post-ERV O30 algebraic ablation",
                "known_incremental_power_kw": no_mu_incremental,
                "conditional_saving_kw": float(o30_zero["incremental_ac_power_reduction_kw"]) - no_mu_incremental,
                "area_m2": float(o30_zero["required_active_area_m2"]),
                "maximum_voltage_v": math.nan,
                "physical_claim_eligible": False,
                "interpretation": "non-thermodynamic lower bound; required uphill chemical work is deleted",
            },
            {
                "case_id": "pure_liquid_receiver_local_upper_bound",
                "case_label": "Pure-liquid receiver proxy",
                "boundary": "direct O80-to-O30 local uniform-inlet upper bound",
                "known_incremental_power_kw": float(pure["gravity_free_heat_sink_total_kw"]),
                "conditional_saving_kw": math.nan,
                "area_m2": float(pure["required_uniform_flux_area_m2"]),
                "maximum_voltage_v": float(pure["terminal_voltage_v"]),
                "physical_claim_eligible": False,
                "with_heat_rejection_power_kw": float(pure["gravity_with_heat_rejection_total_kw"]),
                "interpretation": "different duty/boundary; no axial liquid film, drainage, flooding or thermal model",
            },
            {
                "case_id": "source_film_coordinate",
                "case_label": "Finite source-film diagnostic at numerical zero D",
                "boundary": "post-ERV O30",
                "known_incremental_power_kw": float(numerical_zero["incremental_eo_and_fan_power_kw"]),
                "conditional_saving_kw": float(numerical_zero["incremental_saving_kw_vs_passive_erv"]),
                "area_m2": float(numerical_zero["required_active_area_m2"]),
                "maximum_voltage_v": float(numerical_zero["maximum_required_terminal_voltage_signed_v"]),
                "process_film_crossover_current_density_a_m2": float(
                    numerical_zero["minimum_process_film_crossover_current_density_a_m2"]
                ),
                "maximum_process_film_utilisation": float(
                    numerical_zero["maximum_process_film_utilisation"]
                ),
                "physical_claim_eligible": True,
                "interpretation": "at selected j=3 A/m2 the finite process film is not yet limiting",
            },
        ]
    )


def parameter_register(workshop_config: Mapping[str, Any], optima: pd.DataFrame) -> pd.DataFrame:
    anchor = selected_row(optima, "o30", 1.0e-14)
    parameters = [
        ("Water drag number", anchor["water_drag"], "mol H2O/mol charge", "frozen hypothetical inverse-design value"),
        ("Water diffusivity", "1e-14 to 1e-9", "m2/s", "only swept membrane property"),
        ("Ionic conductivity", anchor["conductivity_s_m"], "S/m", "frozen"),
        ("Dry thickness", anchor["dry_thickness_um"], "um", "frozen"),
        ("Water capacity coefficient", anchor["water_capacity_mol_m3_activity"], "mol/m3/activity", "frozen"),
        ("Diffusivity activity exponent", anchor["diffusivity_activity_exponent"], "-", "frozen"),
        ("Conductivity activity exponent", anchor["conductivity_activity_exponent"], "-", "frozen"),
        ("Capacity activity exponent", anchor["capacity_activity_exponent"], "-", "frozen"),
        ("Series area resistance", anchor["series_asr_ohm_m2"], "ohm m2", "frozen"),
        ("Fixed voltage loss", anchor["fixed_loss_voltage_v"], "V", "frozen at zero"),
        ("Maximum terminal voltage", 2.0, "V", "selection gate"),
        ("Current density", "0.5 to 150 sampled", "A/m2", "sampling coordinate; no acceptance cap"),
        ("Receiver/process dry-air ratio", 1.0, "-", "balanced; no external receiver air"),
        ("Area observation cap", workshop_config["transport_sweep"]["area_observation_cap_m2"], "m2", "numerical observation/censoring only"),
        ("Power-electronics efficiency", 0.9, "-", "frozen"),
    ]
    return pd.DataFrame(parameters, columns=["parameter", "value", "unit", "role"])


def write_summary(
    path: Path,
    optima: pd.DataFrame,
    energy: pd.DataFrame,
    break_even: pd.DataFrame,
    parallel_summary: pd.DataFrame,
) -> None:
    o30_low = selected_row(optima, "o30", 1.0e-14)
    o30_high = selected_row(optima, "o30", 1.0e-9)
    full_high = optima.loc[
        optima["target_id"].eq("full_remaining_latent")
        & np.isclose(
            optima["water_diffusivity_m2_s"], 1.0e-9, rtol=1.0e-10, atol=0.0
        )
    ].iloc[0]
    lines = [
        "# Workshop diffusivity and energy study v1",
        "",
        "## Primary result",
        "",
        (
            f"For the O30 post-ERV duty, the selected conditional saving falls from "
            f"{float(o30_low['reported_saving_kw']):.3f} kW at D=1e-14 m2/s to "
            f"{float(o30_high['reported_saving_kw']):.3f} kW at D=1e-9 m2/s. "
            f"Back-diffusion grows from {100*float(o30_low['absolute_diffusion_fraction_of_eo']):.3f}% "
            f"to {100*float(o30_high['absolute_diffusion_fraction_of_eo']):.3f}% of EO flux."
        ),
        (
            "The sampled full remaining duty has no target-reaching row at or below 2 V "
            "for D=1e-9 m2/s."
            if not bool(full_high["feasible_under_2v_sampled_grid"])
            else "A sampled full-duty row exists at D=1e-9 m2/s."
        ),
        "",
        "All savings are conditional subtotals before receiver/sink, heat rejection, manufactured manifold, electrodes and durability. The hypothetical membrane is not a measured material.",
        "",
        "## Energy chart boundaries",
        "",
        "- Diagram 1 compares AC-only electricity at O80/O50/O30 outdoor weather states at 32 C.",
        "- Diagram 2 passes the same three weather states through the passive ERV before AC.",
        "- Diagram 3 holds outdoor air at O80 and compares post-ERV EO targets. O50 has zero duty because the passive ERV outlet is already drier than O50 on an absolute-humidity basis.",
        "",
        "## 180 Wh/kg check",
        "",
    ]
    for row in break_even.itertuples(index=False):
        lines.append(
            f"- {row.case_label}: break-even {1000*row.break_even_all_in_sec_kwh_kg:.1f} Wh/kg; "
            f"net at 180 Wh/kg = {row.saving_at_180_wh_kg_kw:+.2f} kW ({row.control_branch})."
        )
    lines.extend(
        [
            "",
            "The historical 180 figure is 179.7765 Wh/kg on a mass basis, approximately 179.24 Wh/L liquid-water-equivalent at 0.997 kg/L. It is not Wh per litre of air.",
            "",
            "## PRI2 status",
            "",
            "The EO-first and RH<=85% parallel paths have the same process-air endpoint enthalpy difference. Parallel control changes where water is removed and can reduce the activity-gradient burden, but no coupled temperature-resolved EO/coil power ledger exists yet.",
            "",
            "Liquid-out is only a local upper-bound study; exact D=0 is represented by an analytical interpretation plus a D=1e-20 convergence proxy; forcing concentration-potential voltage to zero is explicitly non-thermodynamic; the finite source film is not limiting at the selected D~0 O30 coordinate.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    report_dir = args.report_dir.resolve()
    figure_dir = report_dir / "figures"
    data_dir = report_dir / "data"
    code_dir = report_dir / "code"
    for directory in (report_dir, figure_dir, data_dir, code_dir):
        directory.mkdir(parents=True, exist_ok=True)
    setup_style()

    workshop_config_path = ROOT / "config" / "workshop_diffusivity_energy_v1.json"
    workshop_config = json.loads(workshop_config_path.read_text(encoding="utf-8"))
    cases_path = args.transport_dir.resolve() / "transport_cases.csv"
    cases = pd.read_csv(cases_path)
    optima = select_diffusivity_optima(cases)
    optima.to_csv(data_dir / "diffusivity_optima_under_2v.csv", index=False)

    energy, active, active_config, state_bundle = make_system_energy_data()
    energy = append_post_erv_eo_bars(energy, optima, state_bundle)
    for diagram_id, group in energy.groupby("diagram_id", sort=False):
        base = float(group.iloc[0]["total_power_kw"])
        energy.loc[group.index, "saving_vs_first_bar_kw"] = base - group["total_power_kw"]
        energy.loc[group.index, "saving_vs_first_bar_pct"] = (
            100.0 * (base - group["total_power_kw"]) / base
        )
    energy.to_csv(data_dir / "system_bar_data.csv", index=False)

    energy_bar_figure(
        energy,
        "ac_only_weather",
        "Diagram 1 — AC-only electricity across O80, O50 and O30 weather states",
        "All states are at 32°C and are cooled to 20°C/50% RH. Reduction is gross weather-state opportunity; no pre-drying device is included.",
        figure_dir,
        "01_ac_only_energy",
    )
    energy_bar_figure(
        energy,
        "ac_erv_weather",
        "Diagram 2 — Passive ERV + AC across the same weather states",
        "O80/O50/O30 are outdoor inlet states at 32°C. ERV fans and motor are included; no EO is present.",
        figure_dir,
        "02_ac_erv_energy",
    )
    energy_bar_figure(
        energy,
        "ac_erv_eo_posterv",
        "Diagram 3 — Passive ERV + post-ERV EO + AC at fixed O80 outdoor air",
        "O50 requires no EO. O30 uses the D=1e-14 hypothetical membrane subtotal; receiver/sink and hardware losses remain outside the ledger.",
        figure_dir,
        "03_ac_erv_eo_energy",
    )
    diffusivity_figures(optima, figure_dir)

    profiles, profile_checks = build_gradient_profiles(optima, workshop_config, args.v2_root)
    profiles.to_csv(data_dir / "selected_gradient_profiles.csv", index=False)
    profile_checks.to_csv(data_dir / "gradient_profile_quadrature_check.csv", index=False)
    if profile_checks["relative_area_difference"].abs().max() > 0.02:
        raise AssetError("Gradient-profile quadrature differs by more than 2% from selected area")
    gradient_figure(profiles, figure_dir)

    break_even = make_break_even_table(optima)
    break_even.to_csv(data_dir / "break_even_180whkg.csv", index=False)
    break_even_figure(break_even, figure_dir)

    geometry, rates, closed = cell_tables()
    geometry.to_csv(data_dir / "test_cell_nominal_geometry.csv", index=False)
    rates.to_csv(data_dir / "test_cell_transport_rates.csv", index=False)
    closed.to_csv(data_dir / "test_cell_5l_closed_transients.csv", index=False)
    inventory = pd.read_csv(
        ROOT
        / "outputs"
        / "eo_vapor_cell_sizing_v1"
        / "closed_loop_gas_inventory_requirement.csv"
    )
    inventory = inventory.loc[
        inventory["study"].eq("inverse_design_anchor_screen")
        & np.isclose(inventory["active_area_cm2"], 25.0)
    ].copy()
    inventory.to_csv(
        data_dir / "test_cell_inverse_anchor_inventory_requirement.csv", index=False
    )
    cell_rate_figure(rates, figure_dir)

    paths, path_summary = parallel_path_tables(active, active_config, state_bundle)
    paths.to_csv(data_dir / "pri2_eo_first_parallel_paths.csv", index=False)
    path_summary.to_csv(data_dir / "pri2_eo_first_parallel_summary.csv", index=False)
    parallel_path_figure(paths, figure_dir)

    limits = pri2_limit_table(optima)
    limits.to_csv(data_dir / "pri2_limiting_cases.csv", index=False)
    parameters = parameter_register(workshop_config, optima)
    parameters.to_csv(data_dir / "parameter_register.csv", index=False)

    # Compact decade table used directly by the LaTeX report.
    columns = [
        "target_id",
        "target_label",
        "water_diffusivity_m2_s",
        "feasible_under_2v_sampled_grid",
        "uniform_current_density_a_m2",
        "required_active_area_m2",
        "maximum_required_terminal_voltage_signed_v",
        "absolute_diffusion_fraction_of_eo",
        "incremental_eo_and_fan_power_kw",
        "reported_total_kw",
        "reported_saving_kw",
        "reported_saving_pct_vs_passive_erv",
        "reported_saving_branch",
        "selection_status",
    ]
    optima.loc[:, columns].to_csv(data_dir / "diffusivity_workshop_table.csv", index=False)

    write_summary(report_dir / "SUMMARY.md", optima, energy, break_even, path_summary)
    shutil.copy2(Path(__file__).resolve(), code_dir / Path(__file__).name)
    shutil.copy2(workshop_config_path, data_dir / workshop_config_path.name)
    active_config_path = ROOT / "config" / "direct_eo_erv_study_v1.json"
    shutil.copy2(active_config_path, data_dir / active_config_path.name)
    source_files = [
        cases_path,
        workshop_config_path,
        active_config_path,
        ROOT / "outputs" / "eo_vapor_cell_sizing_v1" / "channel_geometry_envelope.csv",
        ROOT / "outputs" / "eo_vapor_boundary_analysis_v1" / "nominal_cases.csv",
        ROOT / "outputs" / "eo_vapor_boundary_analysis_v1" / "closed_loop_boundary_screen.csv",
        ROOT
        / "outputs"
        / "eo_vapor_cell_sizing_v1"
        / "closed_loop_gas_inventory_requirement.csv",
        ROOT
        / "outputs"
        / "trond_system_closure_v2_no_current_gate"
        / "liquid_local_upper_bound.csv",
    ]
    generated_files = sorted(
        [path for path in figure_dir.iterdir() if path.is_file()]
        + [path for path in data_dir.iterdir() if path.is_file()]
        + [report_dir / "SUMMARY.md"]
    )
    manifest = {
        "study_id": "workshop-diffusivity-energy-report-assets-v1-2026-08-28",
        "script": str(Path(__file__).resolve()),
        "selection_contract": {
            "voltage_cap_v": 2.0,
            "current_density_acceptance_gate": None,
            "receiver_to_process_dry_air_ratio": 1.0,
            "area_is_observation_not_gate": True,
            "full_duty_saving_branch": "near-endpoint conservative",
        },
        "source_files": [
            {"path": str(path.resolve()), "sha256": sha256(path.resolve())}
            for path in source_files
        ],
        "generated_files": [
            {"path": str(path.resolve()), "sha256": sha256(path.resolve())}
            for path in generated_files
        ],
    }
    (report_dir / "asset_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Wrote workshop report assets to {report_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
