from __future__ import annotations

from types import ModuleType
from typing import Any, Mapping

from heiq.wp1.airside.channels import (
    process_channel_fan,
)

from .channels import (
    channel_pressure_drop_and_fan,
)
from .stack import stack_topology


def add_geometry_and_stack(
    *,
    row: dict[str, Any],
    axial: ModuleType,
    process_basis: Any,
    base_config: Mapping[str, Any],
    v12_config: Mapping[str, Any],
) -> dict[str, Any]:
    """Add process/receiver channel and illustrative stack engineering.

    ``axial`` is retained temporarily for V12 call compatibility.
    The native implementation does not depend on it.
    """

    _ = axial

    area = float(
        row.get(
            "required_active_area_m2",
            0.0,
        )
    )

    if area <= 0.0:
        return {
            **row,
            "process_channel_fan_power_kw": 0.0,
            "receiver_channel_fan_power_kw": 0.0,
            "stack_feasible": False,
            "stack_infeasibility_reason":
                "no positive active area",
        }

    process_geometry = process_channel_fan(
        active_area_m2=area,
        config=dict(base_config),
        basis=process_basis,
    )

    channel = base_config["channel"]

    receiver_geometry = (
        channel_pressure_drop_and_fan(
            axial=None,
            active_area_m2=area,
            total_channel_width_m=float(
                row[
                    "receiver_total_channel_width_m"
                ]
            ),
            active_sides=float(
                channel[
                    "active_sides_per_process_channel"
                ]
            ),
            gap_m=float(
                channel["receiver_gap_m"]
            ),
            velocity_m_s=float(
                row["receiver_velocity_m_s"]
            ),
            volume_flow_m3_s=float(
                row[
                    "selected_actual_volume_flow_m3_s"
                ]
            ),
            temperature_c=float(
                row["temperature_c"]
            ),
            pressure_pa=float(
                row["pressure_pa"]
            ),
            humidity_ratio_kg_kg_da=float(
                row[
                    "inlet_humidity_ratio_kg_kg_da"
                ]
            ),
            fan_efficiency=float(
                v12_config["channel"][
                    "receiver_fan_efficiency"
                ]
            ),
        )
    )

    topology = stack_topology(
        required_area_m2=area,
        integrated_current_a=float(
            row.get(
                "integrated_current_a",
                0.0,
            )
        ),
        maximum_current_density_a_m2=float(
            row.get(
                "maximum_local_current_density_a_m2",
                0.0,
            )
        ),
        cell_terminal_voltage_v=float(
            row["terminal_voltage_v"]
        ),
        stack_config=v12_config["stack"],
    )

    return {
        **row,
        **process_geometry,

        "process_channel_fan_power_kw": float(
            process_geometry[
                "process_fan_power_kw"
            ]
        ),

        "receiver_channel_length_m":
            receiver_geometry[
                "channel_length_m"
            ],

        "receiver_channel_reynolds_number":
            receiver_geometry[
                "channel_reynolds_number"
            ],

        "receiver_channel_pressure_drop_pa":
            receiver_geometry[
                "channel_pressure_drop_pa"
            ],

        "receiver_channel_fan_power_kw":
            receiver_geometry[
                "channel_fan_power_kw"
            ],

        **topology,
    }


__all__ = [
    "add_geometry_and_stack",
]
