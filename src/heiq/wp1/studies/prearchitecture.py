from __future__ import annotations

import copy
import math
from typing import Any

import numpy as np
import pandas as pd

from heiq.wp1.airside import (
    activity_from_t_w,
    dry_air_mass_flow,
)
from heiq.wp1.axial import (
    build_targets,
    solve_local_state,
    validate_config,
)
from heiq.wp1.engineering import (
    add_geometry_and_stack,
)
from heiq.wp1.receiver import (
    MATERIAL_COLUMNS,
    integrate_coupled_receiver_case,
    make_receiver_basis,
)


def finite(value: Any) -> float:
    try:
        result = float(value)
    except Exception:
        return math.nan

    return (
        result
        if math.isfinite(result)
        else math.nan
    )


def truth(value: Any) -> bool:
    if isinstance(
        value,
        (bool, np.bool_),
    ):
        return bool(value)

    return (
        str(value)
        .strip()
        .lower()
        in {"true", "1", "yes"}
    )


def build_context(
    args: Any,
    *,
    cfg12: dict[str, Any],
    base_config: dict[str, Any],
    candidates: pd.DataFrame,
    v2: Any,
    v2_config: dict[str, Any],
) -> dict[str, Any]:
    """Build the reusable pre-architecture study context.

    The returned numerical context is independent of the legacy V3/V12
    script modules.  Compatibility objects may be added by old CLI
    front-ends while downstream scripts are migrated.
    """

    base = copy.deepcopy(base_config)
    cfg12 = copy.deepcopy(cfg12)

    requested_current_cap = getattr(
        args,
        "current_cap_a_m2",
        None,
    )

    if requested_current_cap is not None:
        requested_current_cap = float(
            requested_current_cap
        )

        if (
            not math.isfinite(requested_current_cap)
            or requested_current_cap <= 0.0
        ):
            raise ValueError(
                "current_cap_a_m2 must be finite "
                "and positive"
            )

        cfg12["operating"][
            "current_density_cap_a_m2"
        ] = requested_current_cap

    base["channel"][
        "active_sides_per_process_channel"
    ] = float(
        cfg12["channel"][
            "active_sides_per_process_channel"
        ]
    )

    base["channel"][
        "process_fan_efficiency"
    ] = float(
        cfg12["channel"][
            "process_fan_efficiency"
        ]
    )

    base["channel"][
        "receiver_geometry_mode"
    ] = str(
        cfg12["channel"][
            "receiver_geometry_mode"
        ]
    )

    base["channel"][
        "fixed_receiver_velocity_m_s"
    ] = float(
        cfg12["channel"][
            "fixed_receiver_velocity_m_s"
        ]
    )

    if args.receiver_temperature_c is not None:
        base["channel"][
            "receiver_temperature_c"
        ] = float(
            args.receiver_temperature_c
        )

    base["integration"][
        "area_limit_m2"
    ] = float(args.area_max_m2)

    base["integration"][
        "mass_balance_relative_tolerance"
    ] = float(
        cfg12["integration"][
            "mass_balance_relative_tolerance"
        ]
    )

    validate_config(base)

    process_basis = dry_air_mass_flow(
        base
    )

    targets_df = build_targets(
        base,
        process_basis,
        v2_config,
    )

    targets = {
        str(row["target"]): row
        for _, row in targets_df.iterrows()
    }

    m11675 = candidates[
        candidates["material_id"]
        .astype(str)
        .eq("M11675")
    ]

    if len(m11675) != 1:
        raise RuntimeError(
            "Expected exactly one M11675 row."
        )

    m11675 = m11675.iloc[0]

    if (
        args.receiver_band
        not in cfg12["receiver_bands"]
    ):
        raise KeyError(
            f"Unknown receiver band "
            f"{args.receiver_band}"
        )

    return {
        "v2": v2,
        "v2_config": v2_config,
        "cfg12": cfg12,
        "base": base,
        "process_basis": process_basis,
        "targets": targets,
        "m11675": m11675,
        "args": args,
    }


def make_material(
    ctx: dict[str, Any],
    *,
    drag=None,
    diffusivity=None,
    conductivity=None,
    thickness=None,
) -> dict[str, Any]:
    base = ctx["m11675"]

    overrides = {
        "water_drag": drag,
        "water_diffusivity_m2_s":
            diffusivity,
        "conductivity_s_m":
            conductivity,
        "dry_thickness_um":
            thickness,
    }

    props: dict[str, float] = {}

    for name in MATERIAL_COLUMNS:
        value = overrides.get(
            name,
            None,
        )

        props[name] = float(
            base[name]
            if value is None
            else value
        )

    return {
        "name": (
            f"tw{props['water_drag']:.6g}_"
            f"D{props['water_diffusivity_m2_s']:.3e}_"
            f"sig{props['conductivity_s_m']:.6g}_"
            f"L{props['dry_thickness_um']:.6g}"
        ),
        "model": "powerlaw",
        **props,
        "interpretation":
            "V12.1 pre-architecture "
            "material-screen property vector",
    }


def receiver_basis(
    ctx: dict[str, Any],
    target: str,
    multiplier: float,
):
    cfg12 = ctx["cfg12"]
    args = ctx["args"]

    return make_receiver_basis(
        axial=None,
        process_basis=ctx[
            "process_basis"
        ],
        target_row=ctx[
            "targets"
        ][target],
        receiver_sizing_target_row=ctx[
            "targets"
        ][target],
        band_id=str(
            args.receiver_band
        ),
        band=cfg12[
            "receiver_bands"
        ][str(args.receiver_band)],
        capacity_multiplier=float(
            multiplier
        ),
        flow_arrangement=
            "counter_current",
        base_config=ctx["base"],
    )


def solve_case(
    ctx: dict[str, Any],
    *,
    target: str,
    material: dict[str, Any],
    voltage_v: float,
    receiver_multiplier: float,
    record_profile: bool = False,
):
    cfg12 = ctx["cfg12"]

    receiver = receiver_basis(
        ctx,
        target,
        receiver_multiplier,
    )

    row, profile = (
        integrate_coupled_receiver_case(
            axial=None,
            v2=ctx["v2"],
            v2_config=ctx[
                "v2_config"
            ],
            config=ctx["base"],
            process_basis=ctx[
                "process_basis"
            ],
            target_row=ctx[
                "targets"
            ][target],
            material=material,
            receiver=receiver,
            terminal_voltage_v=float(
                voltage_v
            ),
            electrode_pair_loss_voltage_v=0.0,
            legacy_series_asr_ohm_m2=float(
                cfg12["operating"][
                    "legacy_series_asr_ohm_m2"
                ]
            ),
            added_contact_asr_ohm_m2=0.0,
            power_electronics_efficiency=float(
                cfg12["operating"][
                    "power_electronics_efficiency"
                ]
            ),
            current_cap_a_m2=float(
                cfg12["operating"][
                    "current_density_cap_a_m2"
                ]
            ),
            film_scale_factor=float(
                cfg12["operating"][
                    "film_scale_factor"
                ]
            ),
            record_profile=record_profile,
        )
    )

    row = add_geometry_and_stack(
        row=row,
        axial=None,
        process_basis=ctx[
            "process_basis"
        ],
        base_config=ctx["base"],
        v12_config=cfg12,
    )

    water = finite(
        row.get(
            "integrated_water_transfer_kg_h"
        )
    )

    eo = finite(
        row.get(
            "eo_grid_power_kw"
        )
    )

    process_fan = finite(
        row.get(
            "process_channel_fan_power_kw"
        )
    )

    receiver_fan = finite(
        row.get(
            "receiver_channel_fan_power_kw"
        )
    )

    values = [
        eo,
        process_fan,
        receiver_fan,
    ]

    core = (
        sum(values)
        if all(
            math.isfinite(x)
            for x in values
        )
        else math.nan
    )

    min_flux = finite(
        row.get(
            "minimum_local_flux_mol_m2_s"
        )
    )

    max_j = finite(
        row.get(
            "maximum_local_current_density_a_m2"
        )
    )

    area = finite(
        row.get(
            "required_active_area_m2"
        )
    )

    solver_current_ceiling = float(
        cfg12["operating"][
            "current_density_cap_a_m2"
        ]
    )

    engineering_current_limit = getattr(
        ctx["args"],
        "current_cap_a_m2",
        None,
    )
    current_density_gate_applied = (
        engineering_current_limit is not None
    )
    if current_density_gate_applied:
        engineering_current_limit = float(
            engineering_current_limit
        )

    current_density_gate_pass = bool(
        not current_density_gate_applied
        or (
            math.isfinite(max_j)
            and 0.0 < max_j
            <= engineering_current_limit + 1.0e-9
        )
    )

    target_activity = (
        activity_from_t_w(
            receiver.temperature_c,
            receiver
            .target_outlet_humidity_ratio_kg_kg_da,
            receiver.pressure_pa,
        )
    )

    row.update(
        {
            "analysis_receiver_capacity_multiplier":
                float(
                    receiver_multiplier
                ),

            "analysis_receiver_to_process_dry_air_ratio":
                float(
                    receiver
                    .receiver_to_process_dry_air_ratio
                ),

            "analysis_receiver_airflow_cfm":
                float(
                    receiver
                    .selected_actual_airflow_cfm
                ),

            "analysis_receiver_velocity_m_s":
                float(
                    receiver
                    .receiver_velocity_m_s
                ),

            "analysis_receiver_inlet_activity":
                float(
                    receiver
                    .inlet_activity
                ),

            "analysis_receiver_target_outlet_activity":
                float(
                    target_activity
                ),

            "analysis_core_power_kw":
                core,

            "analysis_core_sec_kwh_kg":
                (
                    core / water
                    if (
                        math.isfinite(core)
                        and water > 0.0
                    )
                    else math.nan
                ),

            "analysis_pass":
                bool(
                    truth(
                        row.get(
                            "target_reached"
                        )
                    )
                    and truth(
                        row.get(
                            "water_balance_pass"
                        )
                    )
                    and truth(
                        row.get(
                            "target_capacity_sufficient"
                        )
                    )
                    and math.isfinite(
                        area
                    )
                    and area
                    <= float(
                        ctx["args"]
                        .area_max_m2
                    )
                    + 1.0e-9
                    and math.isfinite(
                        max_j
                    )
                    and 0.0 < max_j
                    and current_density_gate_pass
                    and math.isfinite(
                        min_flux
                    )
                    and min_flux > 0.0
                    and math.isfinite(
                        core
                    )
                ),

            "current_density_acceptance_gate_applied":
                current_density_gate_applied,

            "current_density_acceptance_gate_pass":
                current_density_gate_pass,

            "engineering_current_density_limit_a_m2":
                engineering_current_limit,

            "solver_current_density_ceiling_a_m2":
                solver_current_ceiling,
        }
    )

    return (
        row,
        profile,
        receiver,
    )


def audit_surfaces(
    ctx: dict[str, Any],
    row: pd.Series,
) -> dict[str, Any]:
    material = make_material(
        ctx,
        drag=float(
            row["water_drag"]
        ),
        diffusivity=float(
            row[
                "water_diffusivity_m2_s"
            ]
        ),
        conductivity=float(
            row["conductivity_s_m"]
        ),
        thickness=float(
            row["dry_thickness_um"]
        ),
    )

    target = str(row["target"])
    voltage = float(
        row["terminal_voltage_v"]
    )

    multiplier = float(
        row[
            "analysis_receiver_capacity_multiplier"
        ]
    )

    _, profile, receiver = solve_case(
        ctx,
        target=target,
        material=material,
        voltage_v=voltage,
        receiver_multiplier=multiplier,
        record_profile=True,
    )

    if profile.empty:
        return {
            "surface_state_audit_complete":
                False,
            "surface_state_physical":
                False,
            "minimum_surface_activity_margin":
                math.nan,
            "negative_surface_margin_fraction":
                math.nan,
        }

    local_config = copy.deepcopy(
        ctx["base"]
    )

    local_config["channel"][
        "receiver_velocity_m_s"
    ] = receiver.receiver_velocity_m_s

    margins: list[float] = []
    physical = True

    for _, profile_row in (
        profile.iterrows()
    ):
        local = solve_local_state(
            v2=ctx["v2"],
            v2_config=ctx[
                "v2_config"
            ],
            material=material,
            source_temperature_c=float(
                ctx["process_basis"]
                .inlet_temperature_c
            ),
            source_humidity_ratio=float(
                profile_row[
                    "process_humidity_ratio_kg_kg_da"
                ]
            ),
            receiver_activity=float(
                profile_row[
                    "receiver_activity"
                ]
            ),
            terminal_voltage_v=voltage,
            fixed_loss_voltage_v=0.0,
            series_asr_ohm_m2=float(
                ctx["cfg12"][
                    "operating"
                ][
                    "legacy_series_asr_ohm_m2"
                ]
            ),
            film_scale_factor=float(
                ctx["cfg12"][
                    "operating"
                ][
                    "film_scale_factor"
                ]
            ),
            config=local_config,
        )

        if not bool(
            local.get(
                "solution_ok",
                False,
            )
        ):
            physical = False
            continue

        process_activity = finite(
            local.get(
                "source_surface_activity"
            )
        )

        receiver_activity = finite(
            local.get(
                "receiver_surface_activity"
            )
        )

        if not (
            math.isfinite(
                process_activity
            )
            and math.isfinite(
                receiver_activity
            )
            and 0.0
            < process_activity
            < 1.0
            and 0.0
            < receiver_activity
            < 1.0
        ):
            physical = False
            continue

        margins.append(
            process_activity
            - receiver_activity
        )

    if not margins:
        physical = False

    negative_fraction = (
        float(
            np.mean(
                np.asarray(margins)
                < 0.0
            )
        )
        if margins
        else math.nan
    )

    return {
        "surface_state_audit_complete":
            bool(margins),

        "surface_state_physical":
            bool(physical),

        "minimum_surface_activity_margin":
            (
                float(min(margins))
                if margins
                else math.nan
            ),

        "maximum_surface_activity_margin":
            (
                float(max(margins))
                if margins
                else math.nan
            ),

        "negative_surface_margin_fraction":
            negative_fraction,

        "positive_surface_direction_everywhere":
            bool(
                margins
                and min(margins) > 0.0
            ),

        "robust_surface_margin_0p02_everywhere":
            bool(
                margins
                and min(margins) >= 0.02
            ),
    }


__all__ = [
    "MATERIAL_COLUMNS",
    "finite",
    "truth",
    "build_context",
    "make_material",
    "receiver_basis",
    "solve_case",
    "audit_surfaces",
]
