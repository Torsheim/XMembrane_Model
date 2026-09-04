#!/usr/bin/env python3
"""Build the like-for-like weather chart for EO integrated in the ERV core.

O80, O50 and O30 are outdoor inlet states at 32 degC.  The installed membrane
area is sized once from the audited O80 full-duty point (0.25 V, eight axial
segments).  O50 and O30 are inverse control replays that vary terminal voltage
until the same installed area reaches the common 20 degC / 50 %RH humidity
target.  This fixes membrane area, but it is not a manufactured fixed-stack
off-design model; the integer stack screen is therefore retained explicitly.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
from pathlib import Path
import sys
from typing import Any, Mapping

os.environ.setdefault("MPLCONFIGDIR", "/tmp/heiq-direct-eo-erv-weather-mpl")

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SCRIPTS = ROOT / "scripts"
for location in (SRC, SCRIPTS):
    if str(location) not in sys.path:
        sys.path.insert(0, str(location))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import run_direct_eo_erv_study_v1 as direct_runner
from heiq.wp1.studies.direct_eo_erv import (
    BaselineSystem,
    build_passive_baseline,
    run_erv,
    solve_coil,
    states_from_config,
)


SCRIPT_VERSION = "integrated-active-erv-weather-v1.0-2026-08-31"
DEFAULT_CONFIG = ROOT / "config" / "direct_eo_erv_study_v1.json"
DEFAULT_OUTPUT = ROOT / "outputs" / "integrated_active_erv_weather_v1"
WEATHER_STATES = (("O80", 0.80), ("O50", 0.50), ("O30", 0.30))
DESIGN_VOLTAGE_V = 0.25
SEGMENT_COUNT = 8


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def load_config(path: Path) -> dict[str, Any]:
    return direct_runner.load_config(path)


def passive_baseline_with_frozen_cop(
    config: Mapping[str, Any],
    states: Mapping[str, Any],
    rated_cop: float,
) -> BaselineSystem:
    boundary = config["boundary"]
    erv_config = config["passive_baseline_erv"]
    m_process = float(boundary["process_outdoor_dry_air_kg_s"])
    m_exhaust = m_process * float(boundary["available_exhaust_to_process_ratio"])
    erv = run_erv(
        oa_in=states["outdoor"],
        exhaust_in=states["exhaust"],
        m_oa=m_process,
        m_exhaust=m_exhaust,
        sensible_effectiveness=float(erv_config["sensible_effectiveness"]),
        latent_effectiveness=float(erv_config["latent_effectiveness"]),
        pressure_drop_each_side_pa=float(erv_config["pressure_drop_each_side_pa"]),
        fan_efficiency=float(erv_config["fan_efficiency"]),
        motor_power_kw=float(erv_config["motor_power_kw"]),
    )
    coil = solve_coil(
        inlet=erv.oa_out,
        supply_target=states["supply"],
        m_da=m_process,
        rated_cop=rated_cop,
        ac_config=config["ac_model"],
    )
    common_kw = float(
        config["common_components"]["common_electric_power_kw_each_system"]
    )
    return BaselineSystem(
        passive_erv=erv,
        remaining_ac=coil,
        rated_cop=rated_cop,
        total_power_kw=erv.total_power_kw + coil.total_ac_power_kw + common_kw,
    )


def case_spec(
    config: Mapping[str, Any],
    voltage_v: float,
    index: int,
    sensible_effectiveness: float,
) -> dict[str, Any]:
    supply_w = states_from_config(config)["supply"].w
    return {
        "case_index": index,
        "material_id": "terminal1_anchor",
        "process_outlet_w_g_kg_da": 1000.0 * supply_w,
        "terminal_voltage_v": float(voltage_v),
        "segment_count": SEGMENT_COUNT,
        "sensible_effectiveness": float(sensible_effectiveness),
        "film_scale_factor": 1.0,
        "electric_heat_scenario_id": "external_rejection",
    }


def solve_case(
    *,
    config: Mapping[str, Any],
    states: Mapping[str, Any],
    baseline: BaselineSystem,
    voltage_v: float,
    index: int,
    v2: Any,
    v2_config: Mapping[str, Any],
    sensible_effectiveness: float = 0.75,
) -> dict[str, Any]:
    row, _ = direct_runner.run_case(
        spec=case_spec(config, voltage_v, index, sensible_effectiveness),
        config=config,
        states=states,
        baseline=baseline,
        v2=v2,
        v2_config=dict(v2_config),
    )
    if not bool(row.get("conditional_decision_ready", False)):
        raise RuntimeError(
            f"Active-ERV replay did not close at {voltage_v:.8g} V: "
            f"{row.get('status')}"
        )
    return row


def voltage_for_fixed_area(
    *,
    installed_area_m2: float,
    config: Mapping[str, Any],
    states: Mapping[str, Any],
    baseline: BaselineSystem,
    v2: Any,
    v2_config: Mapping[str, Any],
    lower_v: float = 0.005,
    upper_v: float = 0.5,
    iterations: int = 18,
    sensible_effectiveness: float = 0.75,
) -> dict[str, Any]:
    low = float(lower_v)
    high = float(upper_v)
    low_row = solve_case(
        config=config,
        states=states,
        baseline=baseline,
        voltage_v=low,
        index=1,
        v2=v2,
        v2_config=v2_config,
        sensible_effectiveness=sensible_effectiveness,
    )
    high_row = solve_case(
        config=config,
        states=states,
        baseline=baseline,
        voltage_v=high,
        index=2,
        v2=v2,
        v2_config=v2_config,
        sensible_effectiveness=sensible_effectiveness,
    )
    if not (
        float(low_row["required_active_area_m2"]) > installed_area_m2
        and float(high_row["required_active_area_m2"]) < installed_area_m2
    ):
        raise RuntimeError("Fixed-area voltage root is not bracketed")
    row = high_row
    for iteration in range(iterations):
        voltage = 0.5 * (low + high)
        row = solve_case(
            config=config,
            states=states,
            baseline=baseline,
            voltage_v=voltage,
            index=iteration + 3,
            v2=v2,
            v2_config=v2_config,
            sensible_effectiveness=sensible_effectiveness,
        )
        if float(row["required_active_area_m2"]) > installed_area_m2:
            low = voltage
        else:
            high = voltage
    voltage = 0.5 * (low + high)
    return solve_case(
        config=config,
        states=states,
        baseline=baseline,
        voltage_v=voltage,
        index=iterations + 3,
        v2=v2,
        v2_config=v2_config,
        sensible_effectiveness=sensible_effectiveness,
    )


def calculate(config_path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    base_config = load_config(config_path)
    o80_states = states_from_config(base_config)
    o80_passive = build_passive_baseline(
        base_config,
        o80_states,
        float(base_config["passive_baseline_erv"]["sensible_effectiveness"]),
    )
    rated_cop = float(o80_passive.rated_cop)
    v2 = direct_runner.legacy_v2_module()
    v2_config = v2.load_config(direct_runner.V2_CONFIG)

    design_row = solve_case(
        config=base_config,
        states=o80_states,
        baseline=o80_passive,
        voltage_v=DESIGN_VOLTAGE_V,
        index=1,
        v2=v2,
        v2_config=v2_config,
    )
    installed_area = float(design_row["required_active_area_m2"])

    records: list[dict[str, Any]] = []
    for weather, rh in WEATHER_STATES:
        config = copy.deepcopy(base_config)
        config["study_id"] = f"integrated-active-erv-weather-{weather.lower()}"
        config["boundary"]["outdoor_rh"] = rh
        states = states_from_config(config)
        passive = passive_baseline_with_frozen_cop(config, states, rated_cop)
        if weather == "O80":
            row = design_row
        else:
            row = voltage_for_fixed_area(
                installed_area_m2=installed_area,
                config=config,
                states=states,
                baseline=passive,
                v2=v2,
                v2_config=v2_config,
            )
        total = float(row["conditional_active_total_power_kw"])
        comparator = float(passive.total_power_kw)
        saving = comparator - total
        records.append(
            {
                "weather_state": weather,
                "outdoor_temperature_c": states["outdoor"].t_c,
                "outdoor_rh_fraction": rh,
                "outdoor_w_g_kg_da": 1000.0 * states["outdoor"].w,
                "supply_target_temperature_c": states["supply"].t_c,
                "supply_target_rh_fraction": states["supply"].rh,
                "supply_target_w_g_kg_da": 1000.0 * states["supply"].w,
                "water_transfer_target_kg_h": float(
                    row["water_transfer_target_kg_h"]
                ),
                "installed_membrane_area_m2": installed_area,
                "inverse_required_area_m2": float(row["required_active_area_m2"]),
                "terminal_voltage_v": float(row["terminal_voltage_v"]),
                "eo_grid_power_kw": float(row["eo_grid_power_kw"]),
                "active_core_fan_power_kw": float(
                    row["selected_active_core_fan_power_kw"]
                ),
                "remaining_ac_power_kw": float(row["remaining_ac_power_kw"]),
                "remaining_ac_water_removed_kg_h": float(
                    row["remaining_ac_water_removed_kg_h"]
                ),
                "active_erv_plus_ac_total_power_kw": total,
                "passive_erv_plus_ac_comparator_kw": comparator,
                "conditional_reduction_vs_passive_kw": saving,
                "conditional_reduction_vs_passive_pct": 100.0 * saving / comparator,
                "transport_closed": bool(row["target_transport_closed"]),
                "stack_feasible": bool(row["stack_feasible"]),
                "engineering_screen_pass": bool(row["engineering_screen_pass"]),
                "full_system_claim_allowed": bool(row["full_system_claim_allowed"]),
                "status": str(row["status"]),
                "stack_infeasibility_reason": str(
                    row.get("stack_infeasibility_reason", "")
                ),
            }
        )
    frame = pd.DataFrame(records)

    if frame["weather_state"].tolist() != ["O80", "O50", "O30"]:
        raise AssertionError("Weather-state order changed")
    if not np.allclose(frame["installed_membrane_area_m2"], installed_area):
        raise AssertionError("Installed membrane area is not fixed")
    relative_area_error = (
        (frame["inverse_required_area_m2"] - installed_area).abs() / installed_area
    )
    if float(relative_area_error.max()) > 2.0e-5:
        raise AssertionError("Fixed-area control root did not converge")
    if not frame["transport_closed"].all():
        raise AssertionError("One or more weather replays did not close transport")
    if not np.allclose(
        frame["remaining_ac_water_removed_kg_h"], 0.0, atol=1.0e-8
    ):
        raise AssertionError("Remaining AC is condensing water in the active-ERV chart")
    if bool(frame.loc[frame["weather_state"].eq("O30"), "stack_feasible"].iloc[0]):
        raise AssertionError("O30 unexpectedly passed the declared stack screen")
    if math.isclose(
        float(frame.iloc[0]["active_erv_plus_ac_total_power_kw"]),
        float(frame.iloc[1]["active_erv_plus_ac_total_power_kw"]),
        abs_tol=1.0e-6,
    ):
        raise AssertionError("O80 and O50 cannot collapse to the old mixed-axis result")

    manifest = {
        "script_version": SCRIPT_VERSION,
        "source_config": str(config_path.resolve()),
        "architecture": (
            "outdoor air -> active EO/sensible ERV membrane core -> remaining "
            "sensible AC -> common supply target; balanced return air is the "
            "water receiver in the same core"
        ),
        "weather_axis": [name for name, _ in WEATHER_STATES],
        "rated_cop_calibration": "calibrated once at O80 and frozen",
        "rated_cop": rated_cop,
        "installed_area_basis": "O80 full-duty, 0.25 V, eight segments",
        "installed_membrane_area_m2": installed_area,
        "control_replay": (
            "weather-specific inverse voltage root at fixed membrane area; not a "
            "fully fixed manufactured stack or converter replay"
        ),
        "claim_boundary": (
            "conditional reduced-order result using the hypothetical Terminal-1 "
            "material and external rejection of EO electrical heat"
        ),
        "omitted_or_unclosed": [
            "measured membrane properties",
            "fixed off-design integer stack and converter control",
            "electrical heat-rejection power and coupled heat transfer",
            "electrodes, current collectors, manifolds and leakage",
            "condensation, liquid films, fouling, ageing and lifetime",
        ],
    }
    return frame, manifest


def calculate_no_coil(config_path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Calculate an ideal sensible-closure case with no downstream coil."""

    base_config = load_config(config_path)
    o80_states = states_from_config(base_config)
    o80_passive = build_passive_baseline(
        base_config,
        o80_states,
        float(base_config["passive_baseline_erv"]["sensible_effectiveness"]),
    )
    rated_cop = float(o80_passive.rated_cop)
    v2 = direct_runner.legacy_v2_module()
    v2_config = v2.load_config(direct_runner.V2_CONFIG)
    ideal_sensible_effectiveness = 1.0

    design_row = solve_case(
        config=base_config,
        states=o80_states,
        baseline=o80_passive,
        voltage_v=DESIGN_VOLTAGE_V,
        index=1,
        v2=v2,
        v2_config=v2_config,
        sensible_effectiveness=ideal_sensible_effectiveness,
    )
    installed_area = float(design_row["required_active_area_m2"])
    records: list[dict[str, Any]] = []
    for weather, rh in WEATHER_STATES:
        config = copy.deepcopy(base_config)
        config["study_id"] = f"integrated-active-erv-no-coil-{weather.lower()}"
        config["boundary"]["outdoor_rh"] = rh
        states = states_from_config(config)
        passive = passive_baseline_with_frozen_cop(config, states, rated_cop)
        if weather == "O80":
            row = design_row
        else:
            row = voltage_for_fixed_area(
                installed_area_m2=installed_area,
                config=config,
                states=states,
                baseline=passive,
                v2=v2,
                v2_config=v2_config,
                sensible_effectiveness=ideal_sensible_effectiveness,
            )
        remaining_ac = float(row["remaining_ac_power_kw"])
        if abs(remaining_ac) > 1.0e-8:
            raise AssertionError("The no-coil endpoint retained downstream AC power")
        total = float(row["conditional_active_total_power_kw"])
        comparator = float(passive.total_power_kw)
        saving = comparator - total
        records.append(
            {
                "weather_state": weather,
                "outdoor_temperature_c": states["outdoor"].t_c,
                "outdoor_rh_fraction": rh,
                "outdoor_w_g_kg_da": 1000.0 * states["outdoor"].w,
                "core_outlet_temperature_c": float(
                    row["process_outlet_temperature_c"]
                ),
                "core_outlet_w_g_kg_da": float(row["process_outlet_w_g_kg_da"]),
                "water_transfer_target_kg_h": float(
                    row["water_transfer_target_kg_h"]
                ),
                "sensible_effectiveness": ideal_sensible_effectiveness,
                "installed_membrane_area_m2": installed_area,
                "inverse_required_area_m2": float(row["required_active_area_m2"]),
                "terminal_voltage_v": float(row["terminal_voltage_v"]),
                "eo_grid_power_kw": float(row["eo_grid_power_kw"]),
                "active_core_fan_power_kw": float(
                    row["selected_active_core_fan_power_kw"]
                ),
                "remaining_ac_power_kw": remaining_ac,
                "erv_eo_only_total_power_kw": total,
                "passive_erv_plus_ac_comparator_kw": comparator,
                "conditional_reduction_vs_passive_kw": saving,
                "conditional_reduction_vs_passive_pct": 100.0 * saving / comparator,
                "transport_closed": bool(row["target_transport_closed"]),
                "stack_feasible": bool(row["stack_feasible"]),
                "engineering_screen_pass": bool(row["engineering_screen_pass"]),
                "full_system_claim_allowed": bool(row["full_system_claim_allowed"]),
                "status": str(row["status"]),
                "stack_infeasibility_reason": str(
                    row.get("stack_infeasibility_reason", "")
                ),
            }
        )
    frame = pd.DataFrame(records)
    relative_area_error = (
        (frame["inverse_required_area_m2"] - installed_area).abs() / installed_area
    )
    if float(relative_area_error.max()) > 2.0e-5:
        raise AssertionError("No-coil fixed-area voltage root did not converge")
    if not frame["transport_closed"].all():
        raise AssertionError("One or more no-coil weather replays did not close")
    if not np.allclose(frame["remaining_ac_power_kw"], 0.0, atol=1.0e-8):
        raise AssertionError("No-coil result contains downstream coil power")

    manifest = {
        "script_version": SCRIPT_VERSION,
        "source_config": str(config_path.resolve()),
        "architecture": (
            "outdoor air -> active EO/sensible ERV membrane core -> supply; "
            "no downstream cooling coil"
        ),
        "endpoint": "core outlet fixed at 20 degC and 50 %RH",
        "sensible_effectiveness": ideal_sensible_effectiveness,
        "interpretation": (
            "ideal sensible-recovery upper bound; epsilon_s=1.0 is imposed so "
            "the ERV core reaches the final temperature without a coil"
        ),
        "rated_cop_calibration": (
            "O80-frozen AC model retained only for the passive comparator; no "
            "AC power appears in the ERV+EO-only bars"
        ),
        "installed_area_basis": "O80 no-coil full-duty, 0.25 V, eight segments",
        "installed_membrane_area_m2": installed_area,
        "claim_boundary": (
            "conditional theoretical upper bound using the hypothetical "
            "Terminal-1 material and external rejection of EO electrical heat"
        ),
    }
    return frame, manifest


def make_figure(frame: pd.DataFrame, output: Path) -> None:
    figure_dir = output / "figures"
    figure_dir.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 9.5,
            "axes.titlesize": 13.5,
            "axes.titleweight": "bold",
            "axes.labelsize": 10,
            "axes.labelcolor": "#172A3A",
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
    x = np.arange(len(frame))
    total = frame["active_erv_plus_ac_total_power_kw"].to_numpy(float)
    baseline = float(total[0])
    reduction = baseline - total

    fig, ax = plt.subplots(figsize=(7.15, 4.15))
    bars = ax.bar(
        x,
        total,
        color="#008C8C",
        width=0.64,
        label="Electricity used",
    )
    ax.bar(
        x,
        reduction,
        bottom=total,
        color="#E8EFF4",
        width=0.64,
        label="Reduction from first bar",
    )
    for bar, used, saving in zip(bars, total, reduction):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            used * 0.5,
            f"{used:,.1f} kW",
            ha="center",
            va="center",
            color="white",
            fontsize=9,
            fontweight="bold",
        )
        if saving > 0.1:
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                used + saving * 0.5,
                f"save {saving:,.1f}\n({100.0 * saving / baseline:.1f}%)",
                ha="center",
                va="center",
                color="#17324D",
                fontsize=8.4,
            )
        else:
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                used + 0.025 * baseline,
                "no change",
                ha="center",
                va="bottom",
                color="#607284",
                fontsize=8.2,
            )
    ax.set_xticks(x, frame["weather_state"])
    ax.set_ylabel("Electrical power at the duty point [kW]")
    ax.set_ylim(0.0, baseline * 1.16)
    ax.grid(axis="y")
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(loc="upper right", ncols=2, fontsize=8.2)
    fig.suptitle(
        "Diagram 3 — Active EO-assisted ERV + sensible-only AC",
        x=0.105,
        y=0.975,
        ha="left",
        fontsize=14,
        fontweight="bold",
    )
    fig.text(
        0.105,
        0.905,
        "EO handles all moisture; the coil is sensible-only (0 kg/h condensate). O30 fails the current stack-voltage gate.",
        ha="left",
        va="top",
        color="#607284",
        fontsize=8.6,
    )
    fig.subplots_adjust(top=0.79, left=0.105, right=0.98, bottom=0.18)
    for suffix in ("pdf", "png"):
        kwargs = {"dpi": 220} if suffix == "png" else {}
        fig.savefig(
            figure_dir / f"active_erv_weather_energy.{suffix}",
            bbox_inches="tight",
            facecolor="white",
            **kwargs,
        )
    plt.close(fig)


def make_no_coil_figure(frame: pd.DataFrame, output: Path) -> None:
    figure_dir = output / "figures"
    figure_dir.mkdir(parents=True, exist_ok=True)
    x = np.arange(len(frame))
    width = 0.62
    fan = frame["active_core_fan_power_kw"].to_numpy()
    eo = frame["eo_grid_power_kw"].to_numpy()
    total = frame["erv_eo_only_total_power_kw"].to_numpy()
    passive = frame["passive_erv_plus_ac_comparator_kw"].to_numpy()

    fig, ax = plt.subplots(figsize=(9.3, 5.4))
    ax.bar(x, fan, width, color="#008F8C", label="Active-core fans")
    ax.bar(x, eo, width, bottom=fan, color="#E58B2A", label="EO grid power")
    for xpos, row, top, reference in zip(x, frame.itertuples(index=False), total, passive):
        ax.hlines(reference, xpos - width / 2, xpos + width / 2, color="#607284", lw=2.0)
        ax.vlines(xpos, top, reference, color="#AAB8C2", lw=1.0, linestyles="dashed")
        ax.text(
            xpos,
            top + 8.0,
            f"{top:.1f} kW\n{row.conditional_reduction_vs_passive_pct:.1f}% below passive",
            ha="center",
            va="bottom",
            color="#173753",
            fontsize=9,
            fontweight="bold",
        )
        ax.text(
            xpos,
            reference + 8.0,
            f"passive {reference:.1f}",
            ha="center",
            va="bottom",
            color="#607284",
            fontsize=8.2,
        )
    ax.set_xticks(x, frame["weather_state"])
    ax.set_ylabel("Electrical power at the duty point [kW]")
    ax.set_ylim(0.0, max(passive) * 1.16)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, ncol=2, loc="upper right")
    fig.suptitle(
        "Diagram 4 — ERV + EO only (no downstream coil)",
        y=0.985,
        fontsize=14,
        fontweight="bold",
    )
    fig.text(
        0.5,
        0.925,
        "The active ERV reaches 20 °C / 50% RH directly; all latent removal is through the membrane.",
        ha="center",
        color="#607284",
        fontsize=8.6,
    )
    fig.text(
        0.5,
        0.018,
        "Theoretical upper bound: sensible effectiveness is imposed at 1.0 and EO electrical heat is rejected externally.",
        ha="center",
        color="#B94A3D",
        fontsize=8.3,
    )
    fig.tight_layout(rect=(0.0, 0.055, 1.0, 0.89))
    for suffix in ("pdf", "png"):
        kwargs = {"dpi": 220} if suffix == "png" else {}
        fig.savefig(
            figure_dir / f"active_erv_no_coil_energy.{suffix}",
            bbox_inches="tight",
            facecolor="white",
            **kwargs,
        )
    plt.close(fig)


def run(config_path: Path, output: Path) -> pd.DataFrame:
    output.mkdir(parents=True, exist_ok=True)
    frame, manifest = calculate(config_path)
    frame.to_csv(output / "active_erv_weather_energy.csv", index=False)
    (output / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    make_figure(frame, output)
    return frame


def main() -> None:
    args = parse_args()
    frame = run(args.config.resolve(), args.output_dir.resolve())
    print(
        frame[
            [
                "weather_state",
                "terminal_voltage_v",
                "active_erv_plus_ac_total_power_kw",
                "stack_feasible",
            ]
        ].to_string(index=False)
    )


if __name__ == "__main__":
    main()
