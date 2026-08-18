#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from CoolProp.CoolProp import PropsSI


P_ATM_PA = 101325.0
R_DA = 287.055
CFM_TO_M3_S = 0.00047194745


def saturation_pressure_pa(t_c: float | np.ndarray) -> float | np.ndarray:
    t = np.asarray(t_c, dtype=float)
    p = 611.21 * np.exp((18.678 - t / 234.5) * (t / (257.14 + t)))
    return float(p) if np.ndim(t_c) == 0 else p


def humidity_ratio_from_t_rh(
    t_c: float | np.ndarray,
    rh_pct: float | np.ndarray,
    pressure_pa: float = P_ATM_PA,
) -> float | np.ndarray:
    t = np.asarray(t_c, dtype=float)
    rh = np.asarray(rh_pct, dtype=float) / 100.0
    p_v = np.clip(rh, 0.0, 1.0) * saturation_pressure_pa(t)

    if np.any(p_v >= pressure_pa):
        raise ValueError("Water-vapour partial pressure must be below total pressure.")

    w = 0.621945 * p_v / (pressure_pa - p_v)
    if np.ndim(t_c) == 0 and np.ndim(rh_pct) == 0:
        return float(w)
    return w


def saturation_humidity_ratio(
    t_c: float | np.ndarray,
    pressure_pa: float = P_ATM_PA,
) -> float | np.ndarray:
    return humidity_ratio_from_t_rh(t_c, 100.0, pressure_pa)


def relative_humidity_pct(
    t_c: float,
    w_kg_kg: float,
    pressure_pa: float = P_ATM_PA,
) -> float:
    p_v = pressure_pa * w_kg_kg / (0.621945 + w_kg_kg)
    return 100.0 * p_v / saturation_pressure_pa(t_c)


def enthalpy_kj_kg_da(
    t_c: float | np.ndarray,
    w_kg_kg: float | np.ndarray,
) -> float | np.ndarray:
    t = np.asarray(t_c, dtype=float)
    w = np.asarray(w_kg_kg, dtype=float)
    return 1.006 * t + w * (2501.0 + 1.86 * t)


def specific_volume_m3_kg_da(
    t_c: float,
    w_kg_kg: float,
    pressure_pa: float = P_ATM_PA,
) -> float:
    return (
        R_DA
        * (t_c + 273.15)
        * (1.0 + 1.607858 * w_kg_kg)
        / pressure_pa
    )


def first_value(row: pd.Series, names: list[str]) -> float:
    for name in names:
        if name in row.index and pd.notna(row[name]):
            return float(row[name])
    raise KeyError(f"Missing required columns. Tried: {names}")


def optional_value(
    row: pd.Series,
    names: list[str],
    default: float = 0.0,
) -> float:
    for name in names:
        if name in row.index and pd.notna(row[name]):
            return float(row[name])
    return default


def explicit_vapour_compression_cycle(
    t_evap_c: float,
    t_cond_c: float,
    refrigerant: str,
    superheat_k: float,
    subcooling_k: float,
    isentropic_efficiency: float,
    motor_efficiency: float,
    drive_efficiency: float,
) -> dict[str, float]:
    if t_cond_c <= t_evap_c:
        raise ValueError("Condensing temperature must be above evaporating temperature.")

    t_evap_k = t_evap_c + 273.15
    t_cond_k = t_cond_c + 273.15

    p_evap = PropsSI("P", "T", t_evap_k, "Q", 1, refrigerant)
    p_cond = PropsSI("P", "T", t_cond_k, "Q", 0, refrigerant)

    t_1 = t_evap_k + superheat_k
    h_1 = PropsSI("H", "P", p_evap, "T", t_1, refrigerant)
    s_1 = PropsSI("S", "P", p_evap, "T", t_1, refrigerant)

    h_2s = PropsSI("H", "P", p_cond, "S", s_1, refrigerant)
    h_2 = h_1 + (h_2s - h_1) / isentropic_efficiency

    t_3 = t_cond_k - subcooling_k
    h_3 = PropsSI("H", "P", p_cond, "T", t_3, refrigerant)
    h_4 = h_3

    q_evap = h_1 - h_4
    w_shaft = h_2 - h_1
    w_electric = w_shaft / (motor_efficiency * drive_efficiency)

    if q_evap <= 0 or w_electric <= 0:
        raise RuntimeError("Invalid refrigeration cycle state.")

    return {
        "p_evap_bar": p_evap / 1e5,
        "p_cond_bar": p_cond / 1e5,
        "pressure_ratio": p_cond / p_evap,
        "q_evap_kj_kg_refrigerant": q_evap / 1000.0,
        "w_electric_kj_kg_refrigerant": w_electric / 1000.0,
        "cop_cooling": q_evap / w_electric,
    }


def make_state(
    case: str,
    point: str,
    role: str,
    t_c: float,
    w_g_kg: float,
    pressure_pa: float,
) -> dict[str, float | str]:
    w = w_g_kg / 1000.0
    return {
        "case": case,
        "point": point,
        "role": role,
        "temperature_c": t_c,
        "rh_pct": relative_humidity_pct(t_c, w, pressure_pa),
        "humidity_ratio_g_kg_da": w_g_kg,
        "enthalpy_kj_kg_da": float(enthalpy_kj_kg_da(t_c, w)),
    }


def extract_states(
    row: pd.Series,
    pressure_pa: float,
) -> dict[str, dict[str, float | str]]:
    case = str(row["case"])

    e_t = first_value(row, ["entering_t_c", "inlet_t_c", "outdoor_t_c"])
    e_w = first_value(
        row,
        ["entering_w_g_kg", "inlet_w_g_kg", "outdoor_w_g_kg"],
    )

    adp_t = first_value(
        row,
        [
            "required_surface_or_adp_t_c",
            "required_adp_t_c",
            "adp_t_c",
            "surface_t_c",
        ],
    )
    adp_w = 1000.0 * float(saturation_humidity_ratio(adp_t, pressure_pa))

    c_t = first_value(
        row,
        ["coil_leave_t_c", "coil_leaving_t_c", "off_coil_t_c"],
    )
    c_w = first_value(
        row,
        ["coil_leave_w_g_kg", "coil_leaving_w_g_kg", "off_coil_w_g_kg"],
    )

    s_t = first_value(row, ["supply_t_c", "target_t_c"])
    s_w = first_value(row, ["supply_w_g_kg", "target_w_g_kg"])

    return {
        "E": make_state(case, "E", "Entering air", e_t, e_w, pressure_pa),
        "ADP": make_state(
            case, "ADP", "Effective saturated coil surface", adp_t, adp_w, pressure_pa
        ),
        "C": make_state(case, "C", "Coil leaving air", c_t, c_w, pressure_pa),
        "S": make_state(case, "S", "Final supply after reheat", s_t, s_w, pressure_pa),
    }


def saturation_constrained_path(
    t_start_c: float,
    w_start_g_kg: float,
    t_end_c: float,
    w_end_g_kg: float,
    pressure_pa: float,
    n_points: int,
) -> pd.DataFrame:
    f = np.linspace(0.0, 1.0, n_points)
    t = t_start_c + f * (t_end_c - t_start_c)
    w_line = w_start_g_kg + f * (w_end_g_kg - w_start_g_kg)
    w_sat = 1000.0 * saturation_humidity_ratio(t, pressure_pa)
    w_plot = np.minimum(w_line, w_sat)

    return pd.DataFrame(
        {
            "fraction": f,
            "temperature_c": t,
            "w_line_g_kg": w_line,
            "w_sat_g_kg": w_sat,
            "w_plot_g_kg": w_plot,
            "on_saturation_curve": w_line > w_sat + 1e-9,
        }
    )


def build_tables(
    source: pd.DataFrame,
    args: argparse.Namespace,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = source[source["case"].astype(str).isin(args.cases)].copy()

    if "target_rh_pct" in df.columns:
        target = pd.to_numeric(df["target_rh_pct"], errors="coerce")
        df = df[np.isclose(target, args.target_rh_pct)].copy()

    if df.empty:
        raise RuntimeError("No rows matched the requested cases and target RH.")

    case_order = pd.CategoricalDtype(args.cases, ordered=True)
    df["_order"] = df["case"].astype(str).astype(case_order)
    df = df.sort_values("_order")

    volume_flow_m3_s = args.airflow_cfm * CFM_TO_M3_S

    state_rows: list[dict[str, float | str]] = []
    summary_rows: list[dict[str, float | str]] = []

    for _, row in df.iterrows():
        case = str(row["case"])
        states = extract_states(row, args.pressure_pa)

        for point in ["E", "ADP", "C", "S"]:
            state_rows.append(states[point])

        h_e = float(states["E"]["enthalpy_kj_kg_da"])
        h_c = float(states["C"]["enthalpy_kj_kg_da"])
        h_s = float(states["S"]["enthalpy_kj_kg_da"])

        q_cooling = h_e - h_c
        q_total_postcoil = h_s - h_c

        fan_heat = optional_value(row, ["fan_heat_kj_kg_da"], 0.0)
        q_active_reheat = q_total_postcoil - fan_heat
        q_net = h_e - h_s

        w_e = float(states["E"]["humidity_ratio_g_kg_da"]) / 1000.0
        v_e = specific_volume_m3_kg_da(
            float(states["E"]["temperature_c"]),
            w_e,
            args.pressure_pa,
        )
        m_da = volume_flow_m3_s / v_e

        cooling_kw = m_da * q_cooling
        active_reheat_kw = m_da * q_active_reheat
        fan_heat_kw = m_da * fan_heat
        net_kw = m_da * q_net

        adp_c = float(states["ADP"]["temperature_c"])
        t_evap_c = adp_c - args.evaporator_approach_k
        t_cond_c = (
            args.outdoor_wetbulb_c
            + args.cooling_tower_approach_k
            + args.condenser_water_range_k
            + args.condenser_approach_k
        )

        cycle = explicit_vapour_compression_cycle(
            t_evap_c=t_evap_c,
            t_cond_c=t_cond_c,
            refrigerant=args.refrigerant,
            superheat_k=args.superheat_k,
            subcooling_k=args.subcooling_k,
            isentropic_efficiency=args.isentropic_efficiency,
            motor_efficiency=args.motor_efficiency,
            drive_efficiency=args.drive_efficiency,
        )

        compressor_kw = cooling_kw / cycle["cop_cooling"]

        if args.reheat_mode == "excluded":
            reheat_electric_kw = 0.0
        elif args.reheat_mode == "resistance":
            reheat_electric_kw = active_reheat_kw
        elif args.reheat_mode == "heat_pump":
            reheat_electric_kw = active_reheat_kw / args.reheat_cop
        else:
            raise ValueError(f"Unknown reheat mode: {args.reheat_mode}")

        process_electric_kw = compressor_kw + reheat_electric_kw

        summary_rows.append(
            {
                "case": case,
                "airflow_cfm": args.airflow_cfm,
                "dry_air_mass_flow_kg_s": m_da,
                "cooling_removed_kj_kg_da": q_cooling,
                "active_reheat_added_kj_kg_da": q_active_reheat,
                "fan_heat_added_kj_kg_da": fan_heat,
                "net_enthalpy_removed_e_to_s_kj_kg_da": q_net,
                "gross_active_thermal_handling_kj_kg_da": (
                    q_cooling + q_active_reheat
                ),
                "cooling_removed_kw": cooling_kw,
                "active_reheat_added_kw": active_reheat_kw,
                "fan_heat_added_kw": fan_heat_kw,
                "net_enthalpy_removed_e_to_s_kw": net_kw,
                "gross_active_thermal_handling_kw": (
                    cooling_kw + active_reheat_kw
                ),
                "adp_c": adp_c,
                "t_evap_c": t_evap_c,
                "t_cond_c": t_cond_c,
                "refrigerant": args.refrigerant,
                "p_evap_bar": cycle["p_evap_bar"],
                "p_cond_bar": cycle["p_cond_bar"],
                "pressure_ratio": cycle["pressure_ratio"],
                "cop_cooling": cycle["cop_cooling"],
                "compressor_electric_kw": compressor_kw,
                "reheat_mode": args.reheat_mode,
                "reheat_electric_kw": reheat_electric_kw,
                "process_electric_kw": process_electric_kw,
                "source_total_cooling_kj_kg_da": optional_value(
                    row, ["total_cooling_kj_kg_da"], float("nan")
                ),
                "source_active_reheat_kj_kg_da": optional_value(
                    row, ["reheat_kj_kg_da"], float("nan")
                ),
            }
        )

    states_df = pd.DataFrame(state_rows)
    summary_df = pd.DataFrame(summary_rows)

    states_df["case"] = pd.Categorical(
        states_df["case"],
        categories=args.cases,
        ordered=True,
    )
    states_df["point"] = pd.Categorical(
        states_df["point"],
        categories=["E", "ADP", "C", "S"],
        ordered=True,
    )
    states_df = states_df.sort_values(["case", "point"]).reset_index(drop=True)

    summary_df["case"] = pd.Categorical(
        summary_df["case"],
        categories=args.cases,
        ordered=True,
    )
    summary_df = summary_df.sort_values("case").reset_index(drop=True)

    baseline = summary_df[
        summary_df["case"].astype(str) == args.design_case
    ].iloc[0]

    summary_df["cop_improvement_vs_o80_pct"] = (
        100.0
        * (
            summary_df["cop_cooling"]
            / float(baseline["cop_cooling"])
            - 1.0
        )
    )
    summary_df["cooling_energy_saved_kw"] = (
        float(baseline["cooling_removed_kw"])
        - summary_df["cooling_removed_kw"]
    )
    summary_df["cooling_energy_saved_pct"] = (
        100.0
        * summary_df["cooling_energy_saved_kw"]
        / float(baseline["cooling_removed_kw"])
    )
    summary_df["reheat_energy_saved_kw"] = (
        float(baseline["active_reheat_added_kw"])
        - summary_df["active_reheat_added_kw"]
    )
    summary_df["gross_thermal_handling_saved_kw"] = (
        float(baseline["gross_active_thermal_handling_kw"])
        - summary_df["gross_active_thermal_handling_kw"]
    )
    summary_df["gross_thermal_handling_saved_pct"] = (
        100.0
        * summary_df["gross_thermal_handling_saved_kw"]
        / float(baseline["gross_active_thermal_handling_kw"])
    )
    summary_df["compressor_electric_saved_kw"] = (
        float(baseline["compressor_electric_kw"])
        - summary_df["compressor_electric_kw"]
    )
    summary_df["compressor_electric_saved_pct"] = (
        100.0
        * summary_df["compressor_electric_saved_kw"]
        / float(baseline["compressor_electric_kw"])
    )
    summary_df["process_electric_saved_kw"] = (
        float(baseline["process_electric_kw"])
        - summary_df["process_electric_kw"]
    )
    summary_df["process_electric_saved_pct"] = (
        100.0
        * summary_df["process_electric_saved_kw"]
        / float(baseline["process_electric_kw"])
    )

    summary_df["cooling_crosscheck_error_kj_kg_da"] = (
        summary_df["cooling_removed_kj_kg_da"]
        - summary_df["source_total_cooling_kj_kg_da"]
    )
    summary_df["reheat_crosscheck_error_kj_kg_da"] = (
        summary_df["active_reheat_added_kj_kg_da"]
        - summary_df["source_active_reheat_kj_kg_da"]
    )

    return states_df, summary_df


def add_background(
    ax: plt.Axes,
    pressure_pa: float,
    t_min: float,
    t_max: float,
    w_max: float,
) -> None:
    temperatures = np.linspace(t_min, t_max, 600)

    for rh in [20, 40, 60, 80]:
        w = 1000.0 * humidity_ratio_from_t_rh(
            temperatures, rh, pressure_pa
        )
        mask = w <= 1.03 * w_max
        ax.plot(
            temperatures[mask],
            w[mask],
            linestyle=":",
            linewidth=0.8,
            alpha=0.35,
        )

    w_sat = 1000.0 * saturation_humidity_ratio(
        temperatures, pressure_pa
    )
    mask_sat = w_sat <= 1.03 * w_max

    ax.plot(
        temperatures[mask_sat],
        w_sat[mask_sat],
        linewidth=2.0,
        label="100% RH / condensation line",
    )


def make_psychrometric_chart(
    states_df: pd.DataFrame,
    args: argparse.Namespace,
    out_dir: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(12.5, 8.2))

    t_min = min(0.0, float(states_df["temperature_c"].min()) - 2.0)
    t_max = max(35.0, float(states_df["temperature_c"].max()) + 3.0)
    w_max = max(
        28.0,
        float(states_df["humidity_ratio_g_kg_da"].max()) * 1.12,
    )

    add_background(ax, args.pressure_pa, t_min, t_max, w_max)

    colours = plt.rcParams["axes.prop_cycle"].by_key()["color"]
    case_colour = {
        case: colours[i % len(colours)]
        for i, case in enumerate(args.cases)
    }

    label_offsets = {
        ("O80", "E"): (8, 8),
        ("O50", "E"): (8, 8),
        ("O30", "E"): (8, 8),
        ("O80", "ADP"): (-52, -22),
        ("O50", "ADP"): (-52, 2),
        ("O30", "ADP"): (-52, 26),
        ("O80", "C"): (8, -25),
        ("O50", "C"): (8, 0),
        ("O30", "C"): (8, 23),
    }

    supply_done = False

    for case in args.cases:
        cdf = states_df[
            states_df["case"].astype(str) == case
        ].set_index("point")

        if cdf.empty:
            continue

        colour = case_colour[case]
        e = cdf.loc["E"]
        adp = cdf.loc["ADP"]
        c = cdf.loc["C"]
        s = cdf.loc["S"]

        cooling_path = saturation_constrained_path(
            float(e["temperature_c"]),
            float(e["humidity_ratio_g_kg_da"]),
            float(c["temperature_c"]),
            float(c["humidity_ratio_g_kg_da"]),
            args.pressure_pa,
            args.path_points,
        )

        ax.plot(
            cooling_path["temperature_c"],
            cooling_path["w_plot_g_kg"],
            linewidth=2.5,
            color=colour,
            label=f"{case}: cooling E→C",
        )

        adp_path = saturation_constrained_path(
            float(c["temperature_c"]),
            float(c["humidity_ratio_g_kg_da"]),
            float(adp["temperature_c"]),
            float(adp["humidity_ratio_g_kg_da"]),
            args.pressure_pa,
            max(100, args.path_points // 3),
        )

        ax.plot(
            adp_path["temperature_c"],
            adp_path["w_plot_g_kg"],
            linewidth=1.2,
            linestyle=":",
            color=colour,
            label=f"{case}: extension to ADP",
        )

        ax.plot(
            [c["temperature_c"], s["temperature_c"]],
            [c["humidity_ratio_g_kg_da"], s["humidity_ratio_g_kg_da"]],
            linewidth=2.0,
            linestyle="--",
            color=colour,
            label=f"{case}: reheat C→S",
        )

        for point_name, marker in [
            ("E", "o"),
            ("ADP", "X"),
            ("C", "s"),
        ]:
            point = cdf.loc[point_name]

            ax.scatter(
                point["temperature_c"],
                point["humidity_ratio_g_kg_da"],
                marker=marker,
                s=75,
                color=colour,
                zorder=6,
            )
            ax.annotate(
                f"{case} {point_name}",
                (
                    point["temperature_c"],
                    point["humidity_ratio_g_kg_da"],
                ),
                xytext=label_offsets.get((case, point_name), (7, 7)),
                textcoords="offset points",
                fontsize=8.5,
                fontweight="bold",
                color=colour,
                bbox={
                    "boxstyle": "round,pad=0.13",
                    "facecolor": "white",
                    "edgecolor": colour,
                    "alpha": 0.86,
                },
                zorder=7,
            )

        if not supply_done:
            ax.scatter(
                s["temperature_c"],
                s["humidity_ratio_g_kg_da"],
                marker="*",
                s=190,
                zorder=7,
            )
            ax.annotate(
                "Common supply S",
                (
                    s["temperature_c"],
                    s["humidity_ratio_g_kg_da"],
                ),
                xytext=(12, 14),
                textcoords="offset points",
                fontsize=9,
                fontweight="bold",
                bbox={
                    "boxstyle": "round,pad=0.15",
                    "facecolor": "white",
                    "edgecolor": "black",
                    "alpha": 0.88,
                },
                zorder=8,
            )
            supply_done = True

    ax.set_xlim(t_min, t_max)
    ax.set_ylim(0.0, w_max)
    ax.set_xlabel("Dry-bulb temperature [°C]")
    ax.set_ylabel("Humidity ratio [g water/kg dry air]")
    ax.set_title(
        "Free pre-dehumidification: direct enthalpy and explicit COP\n"
        "Cooling paths remain on the 100% RH boundary after condensation begins"
    )
    ax.grid(alpha=0.18)
    ax.legend(
        fontsize=7.4,
        ncol=2,
        loc="upper left",
        framealpha=0.92,
    )

    fig.tight_layout()
    fig.savefig(
        out_dir / "psychrometric_free_predrying_explicit_cop.png",
        dpi=250,
        bbox_inches="tight",
    )
    fig.savefig(
        out_dir / "psychrometric_free_predrying_explicit_cop.pdf",
        bbox_inches="tight",
    )
    plt.close(fig)


def make_energy_and_savings_charts(
    summary_df: pd.DataFrame,
    out_dir: Path,
) -> None:
    labels = summary_df["case"].astype(str).tolist()
    x = np.arange(len(labels))

    fig, ax = plt.subplots(figsize=(10.0, 6.0))
    width = 0.23

    for index, (label, column) in enumerate(
        [
            ("Cooling thermal duty", "cooling_removed_kw"),
            ("Active reheat thermal duty", "active_reheat_added_kw"),
            ("Compressor electricity", "compressor_electric_kw"),
            ("Total process electricity", "process_electric_kw"),
        ]
    ):
        positions = x + (index - 1.5) * width
        values = summary_df[column].to_numpy(float)
        ax.bar(positions, values, width=width, label=label)

    ax.set_xticks(x, labels)
    ax.set_ylabel("Power [kW]")
    ax.set_title(
        "Thermal duties and electrical input\n"
        "Pre-dehumidification energy is set to zero"
    )
    ax.grid(axis="y", alpha=0.18)
    ax.legend()

    fig.tight_layout()
    fig.savefig(out_dir / "free_predrying_energy_components.png", dpi=250)
    fig.savefig(out_dir / "free_predrying_energy_components.pdf")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10.0, 6.0))
    width = 0.22

    metrics = [
        ("Cooling duty saved", "cooling_energy_saved_pct"),
        ("Gross thermal handling saved", "gross_thermal_handling_saved_pct"),
        ("Compressor electricity saved", "compressor_electric_saved_pct"),
        ("Total process electricity saved", "process_electric_saved_pct"),
    ]

    for index, (label, column) in enumerate(metrics):
        positions = x + (index - 1.5) * width
        values = summary_df[column].to_numpy(float)
        bars = ax.bar(positions, values, width=width, label=label)

        for bar, value in zip(bars, values):
            ax.annotate(
                f"{value:.1f}%",
                (
                    bar.get_x() + bar.get_width() / 2.0,
                    bar.get_height(),
                ),
                xytext=(0, 3),
                textcoords="offset points",
                ha="center",
                fontsize=7.5,
            )

    ax.set_xticks(x, labels)
    ax.set_ylabel("Saving versus O80 [%]")
    ax.set_title("Energy savings with free pre-dehumidification")
    ax.grid(axis="y", alpha=0.18)
    ax.legend(fontsize=8)

    fig.tight_layout()
    fig.savefig(out_dir / "free_predrying_energy_savings.png", dpi=250)
    fig.savefig(out_dir / "free_predrying_energy_savings.pdf")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8.5, 5.5))
    ax.plot(
        x,
        summary_df["cop_cooling"].to_numpy(float),
        marker="o",
        linewidth=2.0,
    )

    for xi, cop, improvement in zip(
        x,
        summary_df["cop_cooling"],
        summary_df["cop_improvement_vs_o80_pct"],
    ):
        ax.annotate(
            f"COP={cop:.2f}\n{improvement:.1f}%",
            (xi, cop),
            xytext=(0, 8),
            textcoords="offset points",
            ha="center",
            fontsize=8,
        )

    ax.set_xticks(x, labels)
    ax.set_ylabel("Explicit cooling COP [-]")
    ax.set_title("Explicit COP and improvement versus O80")
    ax.grid(alpha=0.18)

    fig.tight_layout()
    fig.savefig(out_dir / "free_predrying_explicit_cop.png", dpi=250)
    fig.savefig(out_dir / "free_predrying_explicit_cop.pdf")
    plt.close(fig)


def write_report(
    states_df: pd.DataFrame,
    summary_df: pd.DataFrame,
    args: argparse.Namespace,
    out_dir: Path,
) -> None:
    lines = [
        "# Free pre-dehumidification with direct enthalpy and explicit COP",
        "",
        "O50 and O30 are prescribed inlet states. The energy required to create "
        "those inlet states is set to zero.",
        "",
        "## Thermal balances",
        "",
        "`Q_cooling = m_da*(h_E - h_C)`",
        "",
        "`Q_active_reheat = m_da*(h_S - h_C - q_fan)`",
        "",
        "`Q_gross = Q_cooling + Q_active_reheat`",
        "",
        "## Electrical balances",
        "",
        "`P_compressor = Q_cooling / COP_cooling`",
        "",
        "`P_process = P_compressor + P_reheat`",
        "",
        "The cooling COP is calculated from an explicit single-stage "
        "vapour-compression cycle using CoolProp.",
        "",
        "## Assumptions",
        "",
        f"- refrigerant: {args.refrigerant}",
        f"- evaporator approach below ADP: {args.evaporator_approach_k:.3f} K",
        f"- outdoor wet-bulb: {args.outdoor_wetbulb_c:.3f} °C",
        f"- cooling-tower approach: {args.cooling_tower_approach_k:.3f} K",
        f"- condenser-water range: {args.condenser_water_range_k:.3f} K",
        f"- condenser approach: {args.condenser_approach_k:.3f} K",
        f"- isentropic efficiency: {args.isentropic_efficiency:.3f}",
        f"- motor efficiency: {args.motor_efficiency:.3f}",
        f"- drive efficiency: {args.drive_efficiency:.3f}",
        f"- reheat mode: {args.reheat_mode}",
        "",
        "## States",
        "",
        states_df.to_markdown(index=False, floatfmt=".5f"),
        "",
        "## Results",
        "",
        summary_df.to_markdown(index=False, floatfmt=".5f"),
        "",
    ]

    (out_dir / "free_predrying_explicit_cop_report.md").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--input-csv",
        default=(
            "outputs/wp1_ac_gross_only_meeting/"
            "generic_commercial_states_per_kg_da.csv"
        ),
    )
    parser.add_argument(
        "--out-dir",
        default="outputs/wp1_free_predrying_explicit_cop",
    )
    parser.add_argument("--target-rh-pct", type=float, default=50.0)
    parser.add_argument("--cases", nargs="+", default=["O80", "O50", "O30"])
    parser.add_argument("--design-case", default="O80")
    parser.add_argument("--airflow-cfm", type=float, default=50000.0)
    parser.add_argument("--pressure-pa", type=float, default=P_ATM_PA)
    parser.add_argument("--path-points", type=int, default=800)

    parser.add_argument("--refrigerant", default="R1234ze(E)")
    parser.add_argument("--evaporator-approach-k", type=float, default=3.0)
    parser.add_argument("--outdoor-wetbulb-c", type=float, default=29.0)
    parser.add_argument("--cooling-tower-approach-k", type=float, default=3.0)
    parser.add_argument("--condenser-water-range-k", type=float, default=5.5)
    parser.add_argument("--condenser-approach-k", type=float, default=2.5)
    parser.add_argument("--superheat-k", type=float, default=2.0)
    parser.add_argument("--subcooling-k", type=float, default=3.0)
    parser.add_argument("--isentropic-efficiency", type=float, default=0.78)
    parser.add_argument("--motor-efficiency", type=float, default=0.97)
    parser.add_argument("--drive-efficiency", type=float, default=0.98)

    parser.add_argument(
        "--reheat-mode",
        choices=["excluded", "resistance", "heat_pump"],
        default="excluded",
    )
    parser.add_argument("--reheat-cop", type=float, default=3.0)

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    input_csv = Path(args.input_csv)
    if not input_csv.exists():
        raise FileNotFoundError(input_csv)

    source = pd.read_csv(input_csv)

    states_df, summary_df = build_tables(source, args)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    states_df.to_csv(
        out_dir / "free_predrying_state_coordinates.csv",
        index=False,
    )
    summary_df.to_csv(
        out_dir / "free_predrying_energy_cop_summary.csv",
        index=False,
    )

    make_psychrometric_chart(states_df, args, out_dir)
    make_energy_and_savings_charts(summary_df, out_dir)
    write_report(states_df, summary_df, args, out_dir)

    print("\nFree pre-dehumidification results\n")
    print(
        summary_df[
            [
                "case",
                "cooling_removed_kw",
                "active_reheat_added_kw",
                "gross_active_thermal_handling_kw",
                "cop_cooling",
                "cop_improvement_vs_o80_pct",
                "compressor_electric_kw",
                "process_electric_kw",
                "cooling_energy_saved_pct",
                "gross_thermal_handling_saved_pct",
                "compressor_electric_saved_pct",
                "process_electric_saved_pct",
            ]
        ]
        .round(4)
        .to_string(index=False)
    )

    print(f"\nResults written to: {out_dir}")


if __name__ == "__main__":
    main()
