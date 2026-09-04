from __future__ import annotations

from types import ModuleType

from heiq.wp1.airside.properties import (
    HUMIDITY_RATIO_CONSTANT,
    R_DRY_AIR_J_KG_K,
    dynamic_viscosity_air_pa_s,
)


def channel_pressure_drop_and_fan(
    *,
    axial: ModuleType,
    active_area_m2: float,
    total_channel_width_m: float,
    active_sides: float,
    gap_m: float,
    velocity_m_s: float,
    volume_flow_m3_s: float,
    temperature_c: float,
    pressure_pa: float,
    humidity_ratio_kg_kg_da: float,
    fan_efficiency: float,
) -> dict[str, float]:
    """Receiver/channel pressure-drop and fan-power calculation.

    ``axial`` is retained temporarily for V12 call compatibility.
    The native implementation does not depend on it.
    """

    _ = axial

    if any(
        value <= 0.0
        for value in (
            total_channel_width_m,
            active_sides,
            gap_m,
            velocity_m_s,
            volume_flow_m3_s,
            fan_efficiency,
        )
    ):
        raise ValueError(
            "Channel geometry, flow and fan efficiency must be positive"
        )

    length = (
        active_area_m2
        / (
            active_sides
            * total_channel_width_m
        )
    )

    temperature_k = temperature_c + 273.15

    if humidity_ratio_kg_kg_da < 0.0:
        raise ValueError(
            "Humidity ratio cannot be negative"
        )

    dry_air_partial_pressure = (
        pressure_pa
        / (
            1.0
            + humidity_ratio_kg_kg_da
            / HUMIDITY_RATIO_CONSTANT
        )
    )

    density = (
        dry_air_partial_pressure
        / (
            R_DRY_AIR_J_KG_K
            * temperature_k
        )
        * (
            1.0
            + humidity_ratio_kg_kg_da
        )
    )

    viscosity = float(
        dynamic_viscosity_air_pa_s(
            temperature_c
        )
    )

    hydraulic_diameter = 2.0 * gap_m

    reynolds = (
        density
        * velocity_m_s
        * hydraulic_diameter
        / viscosity
    )

    if reynolds <= 2300.0:
        pressure_drop = (
            12.0
            * viscosity
            * length
            * velocity_m_s
            / gap_m**2
        )
    else:
        friction_factor = (
            0.3164
            * reynolds ** -0.25
        )

        pressure_drop = (
            friction_factor
            * length
            / hydraulic_diameter
            * density
            * velocity_m_s**2
            / 2.0
        )

    fan_power_kw = (
        pressure_drop
        * volume_flow_m3_s
        / fan_efficiency
        / 1000.0
    )

    return {
        "channel_length_m":
            length,

        "channel_reynolds_number":
            reynolds,

        "channel_pressure_drop_pa":
            pressure_drop,

        "channel_fan_power_kw":
            fan_power_kw,
    }


__all__ = [
    "channel_pressure_drop_and_fan",
]
