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
        "E": make_state(
            case, "E", "Entering air", e_t, e_w, pressure_pa
        ),
        "ADP": make_state(
            case, "ADP", "Effective saturated coil surface", adp_t, adp_w, pressure_pa
        ),
        "C": make_state(
            case, "C", "Coil leaving air", c_t, c_w, pressure_pa
        ),
        "S": make_state(
            case, "S", "Final supply after reheat", s_t, s_w, pressure_pa
        ),
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
    cases: list[str],
    target_rh_pct: float,
    airflow_cfm: float,
    pressure_pa: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = source[source["case"].astype(str).isin(cases)].copy()

    if "target_rh_pct" in df.columns:
        target = pd.to_numeric(df["target_rh_pct"], errors="coerce")
        df = df[np.isclose(target, target_rh_pct)].copy()

    if df.empty:
        raise RuntimeError("No rows matched the requested cases and target RH.")

    case_order = pd.CategoricalDtype(cases, ordered=True)
    df["_order"] = df["case"].astype(str).astype(case_order)
    df = df.sort_values("_order")

    volume_flow_m3_s = airflow_cfm * CFM_TO_M3_S

    state_rows: list[dict[str, float | str]] = []
    summary_rows: list[dict[str, float | str]] = []

    for _, row in df.iterrows():
        case = str(row["case"])
        states = extract_states(row, pressure_pa)

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
            pressure_pa,
        )
        m_da = volume_flow_m3_s / v_e

        summary_rows.append(
            {
                "case": case,
                "airflow_cfm": airflow_cfm,
                "dry_air_mass_flow_kg_s": m_da,
                "cooling_removed_kj_kg_da": q_cooling,
                "active_reheat_added_kj_kg_da": q_active_reheat,
                "fan_heat_added_kj_kg_da": fan_heat,
                "total_postcoil_enthalpy_gain_kj_kg_da": q_total_postcoil,
                "net_enthalpy_removed_e_to_s_kj_kg_da": q_net,
                "gross_active_thermal_handling_kj_kg_da": (
                    q_cooling + q_active_reheat
                ),
                "cooling_removed_kw": m_da * q_cooling,
                "active_reheat_added_kw": m_da * q_active_reheat,
                "fan_heat_added_kw": m_da * fan_heat,
                "total_postcoil_enthalpy_gain_kw": m_da * q_total_postcoil,
                "net_enthalpy_removed_e_to_s_kw": m_da * q_net,
                "gross_active_thermal_handling_kw": (
                    m_da * (q_cooling + q_active_reheat)
                ),
                "source_total_cooling_kj_kg_da": optional_value(
                    row,
                    ["total_cooling_kj_kg_da"],
                    float("nan"),
                ),
                "source_active_reheat_kj_kg_da": optional_value(
                    row,
                    ["reheat_kj_kg_da"],
                    float("nan"),
                ),
            }
        )

    states_df = pd.DataFrame(state_rows)
    summary_df = pd.DataFrame(summary_rows)

    states_df["case"] = pd.Categorical(
        states_df["case"],
        categories=cases,
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
        categories=cases,
        ordered=True,
    )
    summary_df = summary_df.sort_values("case").reset_index(drop=True)

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
            temperatures,
            rh,
            pressure_pa,
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
        temperatures,
        pressure_pa,
    )
    mask_sat = w_sat <= 1.03 * w_max

    ax.plot(
        temperatures[mask_sat],
        w_sat[mask_sat],
        linewidth=2.0,
        label="100% RH / condensation line",
    )


def make_combined_chart(
    states_df: pd.DataFrame,
    cases: list[str],
    pressure_pa: float,
    path_points: int,
    out_dir: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(12.5, 8.2))

    t_min = min(0.0, float(states_df["temperature_c"].min()) - 2.0)
    t_max = max(35.0, float(states_df["temperature_c"].max()) + 3.0)
    w_max = max(
        28.0,
        float(states_df["humidity_ratio_g_kg_da"].max()) * 1.12,
    )

    add_background(ax, pressure_pa, t_min, t_max, w_max)

    colours = plt.rcParams["axes.prop_cycle"].by_key()["color"]
    case_colour = {
        case: colours[i % len(colours)]
        for i, case in enumerate(cases)
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

    for case in cases:
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
            pressure_pa,
            path_points,
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
            pressure_pa,
            max(100, path_points // 3),
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
        "Direct air-side enthalpy calculation\n"
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
        out_dir / "psychrometric_direct_enthalpy_combined.png",
        dpi=250,
        bbox_inches="tight",
    )
    fig.savefig(
        out_dir / "psychrometric_direct_enthalpy_combined.pdf",
        bbox_inches="tight",
    )
    plt.close(fig)


def make_case_charts(
    states_df: pd.DataFrame,
    summary_df: pd.DataFrame,
    cases: list[str],
    pressure_pa: float,
    path_points: int,
    out_dir: Path,
) -> None:
    for case in cases:
        cdf = states_df[
            states_df["case"].astype(str) == case
        ].set_index("point")

        sdf = summary_df[
            summary_df["case"].astype(str) == case
        ]

        if cdf.empty or sdf.empty:
            continue

        summary = sdf.iloc[0]

        e = cdf.loc["E"]
        adp = cdf.loc["ADP"]
        c = cdf.loc["C"]
        s = cdf.loc["S"]

        fig, ax = plt.subplots(figsize=(9.5, 6.8))

        t_min = min(0.0, float(adp["temperature_c"]) - 2.0)
        t_max = max(
            float(e["temperature_c"]) + 2.0,
            float(s["temperature_c"]) + 2.0,
        )
        w_max = max(
            12.0,
            float(e["humidity_ratio_g_kg_da"]) + 2.0,
        )

        add_background(ax, pressure_pa, t_min, t_max, w_max)

        path = saturation_constrained_path(
            float(e["temperature_c"]),
            float(e["humidity_ratio_g_kg_da"]),
            float(c["temperature_c"]),
            float(c["humidity_ratio_g_kg_da"]),
            pressure_pa,
            path_points,
        )

        ax.plot(
            path["temperature_c"],
            path["w_plot_g_kg"],
            linewidth=2.6,
            label="Cooling E→C",
        )
        ax.plot(
            [c["temperature_c"], s["temperature_c"]],
            [c["humidity_ratio_g_kg_da"], s["humidity_ratio_g_kg_da"]],
            linewidth=2.0,
            linestyle="--",
            label="Reheat C→S",
        )

        offsets = {
            "E": (10, 10),
            "C": (10, -58),
            "S": (12, 14),
            "ADP": (-110, -35),
        }

        for point_name, marker in [
            ("E", "o"),
            ("C", "s"),
            ("S", "*"),
            ("ADP", "X"),
        ]:
            point = cdf.loc[point_name]

            ax.scatter(
                point["temperature_c"],
                point["humidity_ratio_g_kg_da"],
                marker=marker,
                s=125 if point_name == "S" else 70,
                zorder=6,
            )

            ax.annotate(
                (
                    f"{point_name}\n"
                    f"T={point['temperature_c']:.2f}°C\n"
                    f"RH={point['rh_pct']:.2f}%\n"
                    f"w={point['humidity_ratio_g_kg_da']:.3f} g/kg\n"
                    f"h={point['enthalpy_kj_kg_da']:.3f} kJ/kg"
                ),
                (
                    point["temperature_c"],
                    point["humidity_ratio_g_kg_da"],
                ),
                xytext=offsets[point_name],
                textcoords="offset points",
                fontsize=8.2,
                bbox={
                    "boxstyle": "round,pad=0.18",
                    "facecolor": "white",
                    "edgecolor": "black",
                    "alpha": 0.88,
                },
            )

        ax.text(
            0.985,
            0.03,
            (
                f"Cooling: {summary['cooling_removed_kj_kg_da']:.3f} kJ/kg_da\n"
                f"Active reheat: {summary['active_reheat_added_kj_kg_da']:.3f} kJ/kg_da\n"
                f"Fan heat: {summary['fan_heat_added_kj_kg_da']:.3f} kJ/kg_da\n"
                f"Net E→S: {summary['net_enthalpy_removed_e_to_s_kj_kg_da']:.3f} kJ/kg_da"
            ),
            transform=ax.transAxes,
            ha="right",
            va="bottom",
            fontsize=8.5,
            bbox={
                "boxstyle": "round,pad=0.25",
                "facecolor": "white",
                "edgecolor": "black",
                "alpha": 0.9,
            },
        )

        ax.set_xlim(t_min, t_max)
        ax.set_ylim(0.0, w_max)
        ax.set_xlabel("Dry-bulb temperature [°C]")
        ax.set_ylabel("Humidity ratio [g water/kg dry air]")
        ax.set_title(f"{case}: direct enthalpy path")
        ax.grid(alpha=0.18)
        ax.legend(fontsize=8, loc="upper left")

        fig.tight_layout()
        fig.savefig(
            out_dir / f"psychrometric_direct_enthalpy_{case}.png",
            dpi=250,
            bbox_inches="tight",
        )
        fig.savefig(
            out_dir / f"psychrometric_direct_enthalpy_{case}.pdf",
            bbox_inches="tight",
        )
        plt.close(fig)


def make_energy_chart(
    summary_df: pd.DataFrame,
    out_dir: Path,
) -> None:
    labels = summary_df["case"].astype(str).tolist()
    x = np.arange(len(labels))
    width = 0.24

    fig, ax = plt.subplots(figsize=(10.0, 6.0))

    metrics = [
        ("Cooling removed", "cooling_removed_kw"),
        ("Active reheat added", "active_reheat_added_kw"),
        ("Net enthalpy removed E→S", "net_enthalpy_removed_e_to_s_kw"),
    ]

    for index, (label, column) in enumerate(metrics):
        positions = x + (index - 1) * width
        values = summary_df[column].to_numpy(float)

        bars = ax.bar(
            positions,
            values,
            width=width,
            label=label,
        )

        for bar, value in zip(bars, values):
            ax.annotate(
                f"{value:.0f}",
                (
                    bar.get_x() + bar.get_width() / 2.0,
                    bar.get_height(),
                ),
                xytext=(0, 3),
                textcoords="offset points",
                ha="center",
                fontsize=8,
            )

    airflow = float(summary_df["airflow_cfm"].iloc[0])

    ax.set_xticks(x, labels)
    ax.set_ylabel("Thermal duty [kW]")
    ax.set_title(
        f"Direct air-side enthalpy duties at {airflow:,.0f} cfm\n"
        "No COP, compressor model or EO penalty"
    )
    ax.grid(axis="y", alpha=0.18)
    ax.legend()

    fig.tight_layout()
    fig.savefig(
        out_dir / "direct_enthalpy_energy_balance.png",
        dpi=250,
        bbox_inches="tight",
    )
    fig.savefig(
        out_dir / "direct_enthalpy_energy_balance.pdf",
        bbox_inches="tight",
    )
    plt.close(fig)


def make_table_plot(
    dataframe: pd.DataFrame,
    columns: list[str],
    headers: list[str],
    title: str,
    filename_stem: str,
    out_dir: Path,
    figsize: tuple[float, float],
) -> None:
    display = dataframe[columns].copy()

    for column in display.columns:
        if pd.api.types.is_numeric_dtype(display[column]):
            display[column] = display[column].map(lambda value: f"{value:.3f}")
        else:
            display[column] = display[column].astype(str)

    fig, ax = plt.subplots(figsize=figsize)
    ax.axis("off")

    table = ax.table(
        cellText=display.values,
        colLabels=headers,
        cellLoc="center",
        colLoc="center",
        loc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(8.3)
    table.scale(1.0, 1.45)

    ax.set_title(
        title,
        fontsize=12,
        fontweight="bold",
        pad=10,
    )

    fig.tight_layout()
    fig.savefig(
        out_dir / f"{filename_stem}.png",
        dpi=250,
        bbox_inches="tight",
    )
    fig.savefig(
        out_dir / f"{filename_stem}.pdf",
        bbox_inches="tight",
    )
    plt.close(fig)


def write_report(
    states_df: pd.DataFrame,
    summary_df: pd.DataFrame,
    input_csv: Path,
    out_dir: Path,
) -> None:
    text = [
        "# Direct air-side enthalpy calculation",
        "",
        f"Input file: `{input_csv}`",
        "",
        "This calculation reports thermal energy transferred directly to or "
        "from the air. It does not divide by COP and is therefore not "
        "compressor electricity.",
        "",
        "## Equations",
        "",
        "`h = 1.006*T + w*(2501 + 1.86*T)`",
        "",
        "`Q_cooling = m_da*(h_E - h_C)`",
        "",
        "`Q_postcoil,total = m_da*(h_S - h_C)`",
        "",
        "`Q_active,reheat = Q_postcoil,total - Q_fan,heat`",
        "",
        "`Q_net = m_da*(h_E - h_S)`",
        "",
        "Cooling paths are clipped to the 100% RH curve wherever a straight "
        "path would enter the supersaturated region.",
        "",
        "## States",
        "",
        states_df.to_markdown(index=False, floatfmt=".5f"),
        "",
        "## Summary",
        "",
        summary_df.to_markdown(index=False, floatfmt=".5f"),
        "",
    ]

    (out_dir / "direct_enthalpy_report.md").write_text(
        "\n".join(text),
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
        default="outputs/wp1_direct_enthalpy_hospital",
    )
    parser.add_argument(
        "--target-rh-pct",
        type=float,
        default=50.0,
    )
    parser.add_argument(
        "--cases",
        nargs="+",
        default=["O80", "O50", "O30"],
    )
    parser.add_argument(
        "--airflow-cfm",
        type=float,
        default=50000.0,
    )
    parser.add_argument(
        "--pressure-pa",
        type=float,
        default=P_ATM_PA,
    )
    parser.add_argument(
        "--path-points",
        type=int,
        default=800,
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    input_csv = Path(args.input_csv)
    if not input_csv.exists():
        raise FileNotFoundError(input_csv)

    source = pd.read_csv(input_csv)

    states_df, summary_df = build_tables(
        source=source,
        cases=args.cases,
        target_rh_pct=args.target_rh_pct,
        airflow_cfm=args.airflow_cfm,
        pressure_pa=args.pressure_pa,
    )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    states_df.to_csv(
        out_dir / "direct_enthalpy_state_coordinates.csv",
        index=False,
    )
    summary_df.to_csv(
        out_dir / "direct_enthalpy_summary.csv",
        index=False,
    )

    make_combined_chart(
        states_df=states_df,
        cases=args.cases,
        pressure_pa=args.pressure_pa,
        path_points=args.path_points,
        out_dir=out_dir,
    )
    make_case_charts(
        states_df=states_df,
        summary_df=summary_df,
        cases=args.cases,
        pressure_pa=args.pressure_pa,
        path_points=args.path_points,
        out_dir=out_dir,
    )
    make_energy_chart(summary_df, out_dir)

    make_table_plot(
        dataframe=states_df,
        columns=[
            "case",
            "point",
            "temperature_c",
            "rh_pct",
            "humidity_ratio_g_kg_da",
            "enthalpy_kj_kg_da",
        ],
        headers=[
            "Case",
            "Point",
            "T [°C]",
            "RH [%]",
            "w [g/kg_da]",
            "h [kJ/kg_da]",
        ],
        title="Psychrometric state coordinates",
        filename_stem="direct_enthalpy_state_coordinates",
        out_dir=out_dir,
        figsize=(10.5, 5.8),
    )

    make_table_plot(
        dataframe=summary_df,
        columns=[
            "case",
            "dry_air_mass_flow_kg_s",
            "cooling_removed_kw",
            "active_reheat_added_kw",
            "fan_heat_added_kw",
            "net_enthalpy_removed_e_to_s_kw",
            "gross_active_thermal_handling_kw",
        ],
        headers=[
            "Case",
            "m_da [kg/s]",
            "Cooling [kW]",
            "Active reheat [kW]",
            "Fan heat [kW]",
            "Net E→S [kW]",
            "Gross active [kW]",
        ],
        title="Direct air-side enthalpy duties",
        filename_stem="direct_enthalpy_energy_table",
        out_dir=out_dir,
        figsize=(12.5, 3.8),
    )

    write_report(
        states_df=states_df,
        summary_df=summary_df,
        input_csv=input_csv,
        out_dir=out_dir,
    )

    print("\nDirect enthalpy results\n")
    print(
        summary_df[
            [
                "case",
                "dry_air_mass_flow_kg_s",
                "cooling_removed_kj_kg_da",
                "active_reheat_added_kj_kg_da",
                "fan_heat_added_kj_kg_da",
                "net_enthalpy_removed_e_to_s_kj_kg_da",
                "cooling_removed_kw",
                "active_reheat_added_kw",
                "fan_heat_added_kw",
                "net_enthalpy_removed_e_to_s_kw",
                "gross_active_thermal_handling_kw",
                "cooling_crosscheck_error_kj_kg_da",
                "reheat_crosscheck_error_kj_kg_da",
            ]
        ]
        .round(5)
        .to_string(index=False)
    )

    print(f"\nResults written to: {out_dir}")


if __name__ == "__main__":
    main()
