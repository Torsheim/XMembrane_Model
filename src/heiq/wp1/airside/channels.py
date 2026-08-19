from __future__ import annotations

from typing import Any

from .properties import (
    AirflowBasis,
    R_DRY_AIR_J_KG_K,
    dynamic_viscosity_air_pa_s,
)


def process_channel_fan(
    *,
    active_area_m2: float,
    config: dict[str, Any],
    basis: AirflowBasis,
) -> dict[str, float]:
    """Close the process-channel geometry once active membrane area is known."""

    channel = config["channel"]

    gap = float(channel["process_gap_m"])
    velocity = float(channel["process_velocity_m_s"])
    active_sides = float(
        channel["active_sides_per_process_channel"]
    )
    fan_efficiency = float(
        channel["process_fan_efficiency"]
    )

    if gap <= 0.0:
        raise ValueError("process_gap_m must be positive")

    if velocity <= 0.0:
        raise ValueError("process_velocity_m_s must be positive")

    if active_sides <= 0.0:
        raise ValueError(
            "active_sides_per_process_channel must be positive"
        )

    if not 0.0 < fan_efficiency <= 1.0:
        raise ValueError(
            "process_fan_efficiency must lie in (0, 1]"
        )

    if active_area_m2 < 0.0:
        raise ValueError(
            "active_area_m2 cannot be negative"
        )

    open_flow_area = (
        basis.volume_flow_m3_s / velocity
    )

    total_channel_width = (
        open_flow_area / gap
    )

    channel_length = (
        active_area_m2
        / (
            active_sides
            * total_channel_width
        )
        if active_area_m2 > 0.0
        else 0.0
    )

    inlet_temperature_k = (
        basis.inlet_temperature_c
        + 273.15
    )

    density = (
        basis.absolute_pressure_pa
        / (
            R_DRY_AIR_J_KG_K
            * inlet_temperature_k
        )
    )

    viscosity = dynamic_viscosity_air_pa_s(
        basis.inlet_temperature_c
    )

    hydraulic_diameter = 2.0 * gap

    reynolds = (
        density
        * velocity
        * hydraulic_diameter
        / viscosity
    )

    if reynolds <= 2300.0:
        pressure_drop = (
            12.0
            * viscosity
            * channel_length
            * velocity
            / gap**2
        )
    else:
        friction_factor = (
            0.3164
            * reynolds ** -0.25
        )

        pressure_drop = (
            friction_factor
            * channel_length
            / hydraulic_diameter
            * density
            * velocity**2
            / 2.0
        )

    fan_power_kw = (
        pressure_drop
        * basis.volume_flow_m3_s
        / fan_efficiency
        / 1000.0
    )

    return {
        "process_channel_length_m":
            channel_length,

        "process_total_channel_width_m":
            total_channel_width,

        "process_open_flow_area_m2":
            open_flow_area,

        "process_channel_reynolds_number":
            reynolds,

        "process_pressure_drop_pa":
            pressure_drop,

        "process_fan_power_kw":
            fan_power_kw,
    }


__all__ = [
    "process_channel_fan",
]
