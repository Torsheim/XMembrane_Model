from __future__ import annotations

from dataclasses import dataclass
import math
from types import ModuleType
from typing import Any, Mapping

from heiq.wp1.airside.properties import (
    CFM_TO_M3_S,
    R_DRY_AIR_J_KG_K,
    humidity_ratio_from_t_rh,
    vapour_pressure_from_humidity_ratio,
)


@dataclass(frozen=True)
class ReceiverBasis:
    """One receiver-loop dry-air basis for a target and humidity band."""

    band_id: str
    receiver_sizing_target: str
    flow_arrangement: str
    temperature_c: float
    pressure_pa: float
    inlet_activity: float
    maximum_outlet_activity: float
    inlet_humidity_ratio_kg_kg_da: float
    maximum_outlet_humidity_ratio_kg_kg_da: float
    target_outlet_humidity_ratio_kg_kg_da: float
    minimum_dry_air_mass_flow_kg_s: float
    selected_dry_air_mass_flow_kg_s: float
    selected_actual_volume_flow_m3_s: float
    selected_actual_airflow_cfm: float
    capacity_multiplier: float
    receiver_geometry_mode: str
    receiver_total_channel_width_m: float
    receiver_velocity_m_s: float
    receiver_to_process_dry_air_ratio: float
    target_capacity_sufficient: bool


def finite_float(value: Any, label: str) -> float:
    result = float(value)

    if not math.isfinite(result):
        raise ValueError(
            f"{label} must be finite, got {value!r}"
        )

    return result


def humidity_ratio_from_activity(
    temperature_c: float,
    activity: float,
    pressure_pa: float,
) -> float:
    return float(
        humidity_ratio_from_t_rh(
            temperature_c,
            activity,
            pressure_pa,
        )
    )


def actual_volume_flow_from_dry_air(
    dry_air_mass_flow_kg_s: float,
    temperature_c: float,
    humidity_ratio_kg_kg_da: float,
    pressure_pa: float,
) -> float:
    vapour_pressure = float(
        vapour_pressure_from_humidity_ratio(
            humidity_ratio_kg_kg_da,
            pressure_pa,
        )
    )

    dry_air_pressure = (
        pressure_pa - vapour_pressure
    )

    if dry_air_pressure <= 0.0:
        raise ValueError(
            "Receiver dry-air partial pressure must be positive"
        )

    return (
        dry_air_mass_flow_kg_s
        * R_DRY_AIR_J_KG_K
        * (temperature_c + 273.15)
        / dry_air_pressure
    )


def water_load_kg_h(
    target_row: Mapping[str, Any],
) -> float:
    return finite_float(
        target_row["computed_water_load_kg_h"],
        "water load",
    )


def make_receiver_basis(
    *,
    axial: ModuleType,
    process_basis: Any,
    target_row: Mapping[str, Any],
    receiver_sizing_target_row: Mapping[str, Any],
    band_id: str,
    band: Mapping[str, Any],
    capacity_multiplier: float,
    flow_arrangement: str,
    base_config: Mapping[str, Any],
) -> ReceiverBasis:
    """Construct the receiver dry-air basis.

    ``axial`` is retained temporarily for compatibility with the V12
    call signature.  The native implementation does not depend on it.
    """

    _ = axial

    pressure = float(
        base_config["air"]["absolute_pressure_pa"]
    )

    temperature = float(
        base_config["channel"][
            "receiver_temperature_c"
        ]
    )

    inlet_activity = float(
        band["inlet_activity"]
    )

    maximum_activity = float(
        band["maximum_outlet_activity"]
    )

    inlet_w = humidity_ratio_from_activity(
        temperature,
        inlet_activity,
        pressure,
    )

    maximum_w = humidity_ratio_from_activity(
        temperature,
        maximum_activity,
        pressure,
    )

    delta_w = maximum_w - inlet_w

    if delta_w <= 0.0:
        raise ValueError(
            "Receiver humidity band has no water capacity"
        )

    design_load_kg_s = (
        water_load_kg_h(
            receiver_sizing_target_row
        )
        / 3600.0
    )

    minimum_flow = (
        design_load_kg_s / delta_w
    )

    selected_flow = (
        minimum_flow
        * float(capacity_multiplier)
    )

    if selected_flow <= 0.0:
        raise ValueError(
            "Receiver dry-air flow must be positive"
        )

    actual_target_load_kg_s = (
        water_load_kg_h(target_row)
        / 3600.0
    )

    target_outlet_w = (
        inlet_w
        + actual_target_load_kg_s
        / selected_flow
    )

    capacity_sufficient = (
        target_outlet_w
        <= maximum_w + 1.0e-12
    )

    volume_flow = (
        actual_volume_flow_from_dry_air(
            selected_flow,
            temperature,
            inlet_w,
            pressure,
        )
    )

    channel = base_config["channel"]

    process_open_area = (
        process_basis.volume_flow_m3_s
        / float(
            channel["process_velocity_m_s"]
        )
    )

    total_process_width = (
        process_open_area
        / float(
            channel["process_gap_m"]
        )
    )

    active_sides = float(
        channel[
            "active_sides_per_process_channel"
        ]
    )

    receiver_gap = float(
        channel["receiver_gap_m"]
    )

    geometry_mode = str(
        channel["receiver_geometry_mode"]
    )

    if geometry_mode == "aligned_equal_total_width":
        receiver_total_width = (
            total_process_width
        )

        receiver_open_area = (
            receiver_total_width
            * receiver_gap
            * active_sides
        )

        receiver_velocity = (
            volume_flow
            / receiver_open_area
        )

    elif (
        geometry_mode
        == "fixed_receiver_velocity_resize_width"
    ):
        receiver_velocity = float(
            channel[
                "fixed_receiver_velocity_m_s"
            ]
        )

        receiver_open_area = (
            volume_flow
            / receiver_velocity
        )

        receiver_total_width = (
            receiver_open_area
            / (
                receiver_gap
                * active_sides
            )
        )

    else:
        raise ValueError(
            f"Unknown receiver geometry mode {geometry_mode}"
        )

    if receiver_open_area <= 0.0:
        raise ValueError(
            "Receiver open flow area must be positive"
        )

    return ReceiverBasis(
        band_id=band_id,
        receiver_sizing_target=str(
            receiver_sizing_target_row["target"]
        ),
        flow_arrangement=flow_arrangement,
        temperature_c=temperature,
        pressure_pa=pressure,
        inlet_activity=inlet_activity,
        maximum_outlet_activity=maximum_activity,
        inlet_humidity_ratio_kg_kg_da=inlet_w,
        maximum_outlet_humidity_ratio_kg_kg_da=maximum_w,
        target_outlet_humidity_ratio_kg_kg_da=target_outlet_w,
        minimum_dry_air_mass_flow_kg_s=minimum_flow,
        selected_dry_air_mass_flow_kg_s=selected_flow,
        selected_actual_volume_flow_m3_s=volume_flow,
        selected_actual_airflow_cfm=(
            volume_flow / CFM_TO_M3_S
        ),
        capacity_multiplier=float(
            capacity_multiplier
        ),
        receiver_geometry_mode=geometry_mode,
        receiver_total_channel_width_m=(
            receiver_total_width
        ),
        receiver_velocity_m_s=(
            receiver_velocity
        ),
        receiver_to_process_dry_air_ratio=(
            selected_flow
            / process_basis.dry_air_mass_flow_kg_s
        ),
        target_capacity_sufficient=(
            capacity_sufficient
        ),
    )


__all__ = [
    "ReceiverBasis",
    "finite_float",
    "humidity_ratio_from_activity",
    "actual_volume_flow_from_dry_air",
    "water_load_kg_h",
    "make_receiver_basis",
]
