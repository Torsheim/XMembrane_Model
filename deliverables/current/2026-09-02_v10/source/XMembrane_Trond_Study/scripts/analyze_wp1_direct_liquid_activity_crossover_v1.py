#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


ALIASES = {
    "target": ["target"],
    "basis": ["material_basis_id", "material_basis", "basis_id"],
    "activity": [
        "liquid_activity",
        "liquid_activity_proxy",
        "receiver_liquid_activity",
        "liquid_sink_activity",
    ],
    "voltage": ["terminal_voltage_v", "voltage_v"],
    "tw": ["water_drag", "water_transport_number", "tw"],
    "area": ["required_active_area_m2", "active_area_m2"],
    "jmax": [
        "maximum_local_current_density_a_m2",
        "max_local_current_density_a_m2",
    ],
    "eo_power": ["eo_grid_power_kw", "eo_power_kw"],
    "process_fan": [
        "process_channel_fan_power_kw",
        "process_fan_power_kw",
    ],
    "pump": [
        "condensate_pump_power_kw",
        "pump_power_kw",
    ],
    "core": [
        "predryer_core_power_kw",
        "core_power_kw",
    ],
    "sec": [
        "predryer_core_sec_kwh_kg",
        "core_sec_kwh_kg",
    ],
    "water": [
        "integrated_water_transfer_kg_h",
        "water_removed_kg_h",
    ],
    "heat": [
        "condensation_or_phase_change_heat_proxy_kw",
        "condensation_heat_kw",
        "phase_change_heat_kw",
    ],
    "target_reached": ["target_reached"],
    "analysis_pass": ["analysis_pass"],
    "status": ["status"],
}


def find_col(df, key, required=False):
    for name in ALIASES[key]:
        if name in df.columns:
            return name

    if required:
        raise KeyError(
            f"Missing column for {key}. Tried: {ALIASES[key]}"
        )

    return None


def to_bool(series):
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)

    if pd.api.types.is_numeric_dtype(series):
        return (
            pd.to_numeric(series, errors="coerce")
            .fillna(0)
            .ne(0)
        )

    return (
        series.astype(str)
        .str.strip()
        .str.lower()
        .isin(
            {
                "true",
                "1",
                "yes",
                "pass",
                "passed",
            }
        )
    )


def numeric(df, key, default=np.nan):
    name = find_col(df, key)

    if name is None:
        return pd.Series(
            default,
            index=df.index,
            dtype=float,
        )

    return pd.to_numeric(
        df[name],
        errors="coerce",
    )


def load_direct_liquid_table(root):
    candidates = []

    files = (
        sorted(root.rglob("*.csv"))
        +
        sorted(root.rglob("*.csv.gz"))
    )

    for path in files:
        try:
            df = pd.read_csv(path)
        except Exception:
            continue

        if df.empty:
            continue

        required = [
            "target",
            "basis",
            "activity",
            "voltage",
            "eo_power",
        ]

        if not all(
            find_col(df, key)
            for key in required
        ):
            continue

        score = len(df)

        name = path.name.lower()

        if "all" in name:
            score *= 5
        elif "best" in name:
            score *= 2

        candidates.append(
            (
                score,
                len(df),
                path,
                df,
            )
        )

    if not candidates:
        raise RuntimeError(
            "Fant ingen direct-liquid CSV med de nødvendige kolonnene."
        )

    candidates.sort(
        key=lambda x: (x[0], x[1]),
        reverse=True,
    )

    _, _, path, df = candidates[0]

    return path, df.copy()


def gas_core_power(path, target):
    df = pd.read_csv(path)

    if df.empty:
        raise RuntimeError(
            f"Tom gas-receiver baseline: {path}"
        )

    for name in [
        "analysis_core_power_kw",
        "predryer_core_power_kw",
        "diagnostic_core_power_kw",
    ]:
        if name in df.columns:
            vals = pd.to_numeric(
                df[name],
                errors="coerce",
            )

            vals = vals[
                np.isfinite(vals)
            ]

            if len(vals):
                return float(vals.min())

    needed = [
        "eo_grid_power_kw",
        "process_channel_fan_power_kw",
        "receiver_channel_fan_power_kw",
    ]

    if all(
        name in df.columns
        for name in needed
    ):
        power = sum(
            pd.to_numeric(
                df[name],
                errors="coerce",
            )
            for name in needed
        )

        power = power[
            np.isfinite(power)
        ]

        if len(power):
            return float(power.min())

    raise RuntimeError(
        f"Kunne ikke rekonstruere {target} gas-receiver core power."
    )


def interpolate_crossing(group):
    group = (
        group
        .sort_values("liquid_activity")
        .dropna(
            subset=["delta_vs_gas_kw"]
        )
    )

    if group.empty:
        return None

    exact = group[
        np.isclose(
            group["delta_vs_gas_kw"],
            0.0,
            atol=1e-9,
        )
    ]

    if not exact.empty:
        return float(
            exact.iloc[0]["liquid_activity"]
        )

    x = group[
        "liquid_activity"
    ].to_numpy(float)

    y = group[
        "delta_vs_gas_kw"
    ].to_numpy(float)

    for i in range(
        len(group) - 1
    ):
        if y[i] * y[i + 1] < 0:
            return float(
                x[i]
                +
                (0.0 - y[i])
                *
                (
                    x[i + 1]
                    -
                    x[i]
                )
                /
                (
                    y[i + 1]
                    -
                    y[i]
                )
            )

    return None


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path(
            "outputs/direct_liquid_contact_receiver_v1"
        ),
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "outputs/direct_liquid_activity_crossover_v1"
        ),
    )

    parser.add_argument(
        "--material-basis",
        default="Terminal1_optimum",
    )

    parser.add_argument(
        "--voltage-caps",
        nargs="+",
        type=float,
        default=[
            2,
            5,
            10,
            20,
            24,
        ],
    )

    parser.add_argument(
        "--o30-gas",
        type=Path,
        default=Path(
            "outputs/prearchitecture_continuation_v2/"
            "material_global/overall_best.csv"
        ),
    )

    parser.add_argument(
        "--o50-gas",
        type=Path,
        default=Path(
            "outputs/prearchitecture_continuation_v2/"
            "o50_edge/best_by_drag.csv"
        ),
    )

    args = parser.parse_args()

    args.output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    source_path, df = (
        load_direct_liquid_table(
            args.input_dir
        )
    )

    print(
        f"Using direct-liquid table: "
        f"{source_path} "
        f"({len(df)} rows)"
    )

    c_target = find_col(
        df,
        "target",
        True,
    )

    c_basis = find_col(
        df,
        "basis",
        True,
    )

    c_activity = find_col(
        df,
        "activity",
        True,
    )

    c_voltage = find_col(
        df,
        "voltage",
        True,
    )

    df = df[
        df[c_basis]
        .astype(str)
        .eq(args.material_basis)
    ].copy()

    df = df[
        df[c_target]
        .astype(str)
        .isin(
            [
                "O30",
                "O50",
            ]
        )
    ].copy()

    c = find_col(
        df,
        "target_reached",
    )

    if c:
        df = df[
            to_bool(df[c])
        ].copy()

    c = find_col(
        df,
        "analysis_pass",
    )

    if c:
        mask = to_bool(
            df[c]
        )

        if mask.any():
            df = df[
                mask
            ].copy()

    c = find_col(
        df,
        "status",
    )

    if c:
        status = (
            df[c]
            .astype(str)
            .str.lower()
        )

        mask = status.str.contains(
            "target_reached|pass|success|ok",
            regex=True,
        )

        if mask.any():
            df = df[
                mask
            ].copy()

    df["liquid_activity"] = (
        pd.to_numeric(
            df[c_activity],
            errors="coerce",
        )
    )

    df["terminal_voltage_v"] = (
        pd.to_numeric(
            df[c_voltage],
            errors="coerce",
        )
    )

    df["water_drag"] = numeric(
        df,
        "tw",
    )

    df["required_active_area_m2"] = (
        numeric(
            df,
            "area",
        )
    )

    df[
        "maximum_local_current_density_a_m2"
    ] = numeric(
        df,
        "jmax",
    )

    df["eo_grid_power_kw"] = numeric(
        df,
        "eo_power",
    )

    df[
        "process_channel_fan_power_kw"
    ] = (
        numeric(
            df,
            "process_fan",
            0.0,
        )
        .fillna(0.0)
    )

    df[
        "condensate_pump_power_kw"
    ] = (
        numeric(
            df,
            "pump",
            0.0,
        )
        .fillna(0.0)
    )

    df[
        "reported_core_power_kw"
    ] = numeric(
        df,
        "core",
    )

    df[
        "reported_core_sec_kwh_kg"
    ] = numeric(
        df,
        "sec",
    )

    df[
        "water_removed_kg_h"
    ] = numeric(
        df,
        "water",
    )

    df[
        "phase_change_heat_proxy_kw"
    ] = numeric(
        df,
        "heat",
    )

    # -----------------------------------------
    # GRATIS LIQUID REMOVAL UPPER BOUND
    #
    # Beholder:
    #   EO-grid electricity
    #   process-side fan
    #
    # Setter til null:
    #   receiver fan
    #   condensate pump
    #   heat rejection electricity
    #   liquid regeneration
    # -----------------------------------------

    df[
        "free_liquid_removal_power_kw"
    ] = (
        df["eo_grid_power_kw"]
        +
        df[
            "process_channel_fan_power_kw"
        ]
    )

    df = df[
        np.isfinite(
            df["liquid_activity"]
        )
        &
        np.isfinite(
            df["terminal_voltage_v"]
        )
        &
        np.isfinite(
            df[
                "free_liquid_removal_power_kw"
            ]
        )
    ].copy()

    if df.empty:
        raise RuntimeError(
            "Ingen gyldige Terminal1_optimum "
            "direct-liquid-rader igjen."
        )

    gas = {
        "O30": gas_core_power(
            args.o30_gas,
            "O30",
        ),
        "O50": gas_core_power(
            args.o50_gas,
            "O50",
        ),
    }

    print()
    print(
        "Gas receiver baselines:"
    )

    print(
        f"O30 = {gas['O30']:.6f} kW"
    )

    print(
        f"O50 = {gas['O50']:.6f} kW"
    )

    rows = []

    for target in [
        "O30",
        "O50",
    ]:
        base = gas[target]

        target_df = df[
            df[c_target]
            .astype(str)
            .eq(target)
        ].copy()

        for cap in sorted(
            set(args.voltage_caps)
        ):
            cap_df = target_df[
                target_df[
                    "terminal_voltage_v"
                ]
                <= cap + 1e-12
            ].copy()

            for activity, group in (
                cap_df.groupby(
                    "liquid_activity"
                )
            ):
                if group.empty:
                    continue

                idx = (
                    group[
                        "free_liquid_removal_power_kw"
                    ]
                    .idxmin()
                )

                r = group.loc[idx]

                power = float(
                    r[
                        "free_liquid_removal_power_kw"
                    ]
                )

                rows.append(
                    {
                        "target":
                            target,

                        "material_basis_id":
                            args.material_basis,

                        "voltage_cap_v":
                            cap,

                        "liquid_activity":
                            float(activity),

                        "water_drag":
                            float(
                                r[
                                    "water_drag"
                                ]
                            ),

                        "terminal_voltage_v":
                            float(
                                r[
                                    "terminal_voltage_v"
                                ]
                            ),

                        "required_active_area_m2":
                            float(
                                r[
                                    "required_active_area_m2"
                                ]
                            ),

                        "maximum_local_current_density_a_m2":
                            float(
                                r[
                                    "maximum_local_current_density_a_m2"
                                ]
                            ),

                        "eo_grid_power_kw":
                            float(
                                r[
                                    "eo_grid_power_kw"
                                ]
                            ),

                        "process_channel_fan_power_kw":
                            float(
                                r[
                                    "process_channel_fan_power_kw"
                                ]
                            ),

                        "condensate_pump_power_kw_ignored":
                            float(
                                r[
                                    "condensate_pump_power_kw"
                                ]
                            ),

                        "free_liquid_removal_power_kw":
                            power,

                        "gas_receiver_core_power_kw":
                            base,

                        "delta_vs_gas_kw":
                            power - base,

                        "saving_vs_gas_pct":
                            100.0
                            *
                            (
                                base
                                -
                                power
                            )
                            /
                            base,

                        "reported_core_power_kw":
                            float(
                                r[
                                    "reported_core_power_kw"
                                ]
                            ),

                        "reported_core_sec_kwh_kg":
                            float(
                                r[
                                    "reported_core_sec_kwh_kg"
                                ]
                            ),

                        "water_removed_kg_h":
                            float(
                                r[
                                    "water_removed_kg_h"
                                ]
                            ),

                        "phase_change_heat_proxy_kw":
                            float(
                                r[
                                    "phase_change_heat_proxy_kw"
                                ]
                            ),
                    }
                )

    out = pd.DataFrame(
        rows
    )

    if out.empty:
        raise RuntimeError(
            "Ingen activity/cap-løsninger valgt."
        )

    out = (
        out
        .sort_values(
            [
                "target",
                "voltage_cap_v",
                "liquid_activity",
            ]
        )
        .reset_index(
            drop=True
        )
    )

    out.to_csv(
        args.output_dir
        /
        "best_free_liquid_by_activity_and_voltage_cap.csv",
        index=False,
    )

    crossover_rows = []

    for (
        target,
        cap,
    ), group in out.groupby(
        [
            "target",
            "voltage_cap_v",
        ]
    ):
        crossing = (
            interpolate_crossing(
                group
            )
        )

        min_activity = float(
            group[
                "liquid_activity"
            ].min()
        )

        max_activity = float(
            group[
                "liquid_activity"
            ].max()
        )

        min_row = group.loc[
            group[
                "liquid_activity"
            ].idxmin()
        ]

        max_row = group.loc[
            group[
                "liquid_activity"
            ].idxmax()
        ]

        if crossing is not None:
            status = (
                "BRACKETED"
            )

        elif (
            group[
                "delta_vs_gas_kw"
            ] < 0
        ).all():
            status = (
                "LIQUID_BETTER_OVER_ALL_TESTED_ACTIVITIES"
            )

        elif (
            group[
                "delta_vs_gas_kw"
            ] > 0
        ).all():
            status = (
                "NO_CROSSOVER_IN_TESTED_RANGE__TEST_LOWER_ACTIVITY"
            )

        else:
            status = (
                "NO_LINEAR_CROSSING_FOUND"
            )

        crossover_rows.append(
            {
                "target":
                    target,

                "voltage_cap_v":
                    cap,

                "gas_receiver_core_power_kw":
                    gas[target],

                "tested_activity_min":
                    min_activity,

                "tested_activity_max":
                    max_activity,

                "delta_at_min_activity_kw":
                    float(
                        min_row[
                            "delta_vs_gas_kw"
                        ]
                    ),

                "delta_at_max_activity_kw":
                    float(
                        max_row[
                            "delta_vs_gas_kw"
                        ]
                    ),

                "estimated_break_even_liquid_activity":
                    crossing,

                "status":
                    status,
            }
        )

    crossover = pd.DataFrame(
        crossover_rows
    )

    crossover.to_csv(
        args.output_dir
        /
        "crossover_summary.csv",
        index=False,
    )

    idx = (
        out.groupby(
            [
                "target",
                "voltage_cap_v",
            ]
        )[
            "free_liquid_removal_power_kw"
        ]
        .idxmin()
    )

    best = (
        out.loc[idx]
        .sort_values(
            [
                "target",
                "voltage_cap_v",
            ]
        )
    )

    best.to_csv(
        args.output_dir
        /
        "best_free_liquid_by_voltage_cap.csv",
        index=False,
    )

    for target in [
        "O30",
        "O50",
    ]:
        fig, ax = plt.subplots(
            figsize=(8.5, 5.5)
        )

        target_df = out[
            out["target"].eq(
                target
            )
        ]

        for cap, group in (
            target_df.groupby(
                "voltage_cap_v"
            )
        ):
            ax.plot(
                group[
                    "liquid_activity"
                ],
                group[
                    "free_liquid_removal_power_kw"
                ],
                marker="o",
                label=f"V ≤ {cap:g} V",
            )

        ax.axhline(
            gas[target],
            linestyle="--",
            label=(
                f"gas receiver = "
                f"{gas[target]:.2f} kW"
            ),
        )

        ax.set_xlabel(
            "Liquid water activity"
        )

        ax.set_ylabel(
            "EO + process-fan power [kW]"
        )

        ax.set_title(
            f"{target}: free liquid-removal upper bound"
        )

        ax.grid(
            True,
            alpha=0.3,
        )

        ax.legend()

        fig.tight_layout()

        fig.savefig(
            args.output_dir
            /
            f"{target.lower()}_free_liquid_power_vs_activity.png",
            dpi=220,
        )

        plt.close(fig)

    max_cap = max(
        args.voltage_caps
    )

    for (
        metric,
        ylabel,
        filename,
    ) in [
        (
            "terminal_voltage_v",
            "Selected terminal voltage [V]",
            "selected_voltage_vs_activity.png",
        ),
        (
            "required_active_area_m2",
            "Required active area [m²]",
            "selected_area_vs_activity.png",
        ),
    ]:
        fig, ax = plt.subplots(
            figsize=(8.5, 5.5)
        )

        for target in [
            "O30",
            "O50",
        ]:
            group = out[
                out["target"].eq(target)
                &
                np.isclose(
                    out[
                        "voltage_cap_v"
                    ],
                    max_cap,
                )
            ]

            if group.empty:
                continue

            ax.plot(
                group[
                    "liquid_activity"
                ],
                group[
                    metric
                ],
                marker="o",
                label=target,
            )

        ax.set_xlabel(
            "Liquid water activity"
        )

        ax.set_ylabel(
            ylabel
        )

        ax.set_title(
            f"Best direct-liquid solution at V ≤ {max_cap:g} V"
        )

        ax.grid(
            True,
            alpha=0.3,
        )

        ax.legend()

        fig.tight_layout()

        fig.savefig(
            args.output_dir
            /
            filename,
            dpi=220,
        )

        plt.close(fig)

    print()
    print(
        "=== CROSSOVER SUMMARY ==="
    )

    print(
        crossover.to_string(
            index=False
        )
    )

    print()
    print(
        "=== BEST FREE-LIQUID POINT BY VOLTAGE CAP ==="
    )

    show = [
        "target",
        "voltage_cap_v",
        "liquid_activity",
        "water_drag",
        "terminal_voltage_v",
        "required_active_area_m2",
        "free_liquid_removal_power_kw",
        "gas_receiver_core_power_kw",
        "saving_vs_gas_pct",
        "phase_change_heat_proxy_kw",
    ]

    print(
        best[
            show
        ].to_string(
            index=False
        )
    )

    print()
    print(
        f"Outputs: "
        f"{args.output_dir}"
    )


if __name__ == "__main__":
    main()
