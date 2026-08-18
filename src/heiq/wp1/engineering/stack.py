from __future__ import annotations

import math
from typing import Any, Mapping


def stack_topology(
    *,
    required_area_m2: float,
    integrated_current_a: float,
    maximum_current_density_a_m2: float,
    cell_terminal_voltage_v: float,
    stack_config: Mapping[str, Any],
) -> dict[str, Any]:
    """Search an integer Ns x Np topology under declared illustrative limits."""
    if required_area_m2 <= 0.0 or integrated_current_a <= 0.0:
        return {
            "stack_feasible": False,
            "stack_infeasibility_reason": "nonpositive area or integrated current",
        }
    max_cell_area = float(stack_config["maximum_cell_active_area_m2"])
    max_cell_current = float(stack_config["maximum_cell_current_a"])
    minimum_converter_voltage = float(
        stack_config["minimum_converter_input_voltage_v"]
    )
    max_bus_voltage = float(stack_config["maximum_dc_bus_voltage_v"])
    max_bus_current = float(stack_config["maximum_converter_current_a"])
    max_converter_power_kw = float(stack_config["maximum_converter_power_kw"])
    max_series = int(stack_config["maximum_series_cells"])
    if any(
        value <= 0
        for value in (
            max_cell_area,
            max_cell_current,
            minimum_converter_voltage,
            max_bus_voltage,
            max_bus_current,
            max_converter_power_kw,
            max_series,
        )
    ):
        raise ValueError("Stack constraints must be positive")
    minimum_cells_area = math.ceil(required_area_m2 / max_cell_area)
    # Terminal current is the area integral of j divided among repeat cells.
    # The local maximum j is retained as a separate collector/material screen;
    # multiplying j_max by every cell's full area would overstate cell current.
    minimum_cells_terminal_current = math.ceil(
        integrated_current_a / max_cell_current
    )
    minimum_cells = max(1, minimum_cells_area, minimum_cells_terminal_current)
    reference_power_kw = cell_terminal_voltage_v * integrated_current_a / 1000.0
    if reference_power_kw > max_converter_power_kw + 1.0e-12:
        return {
            "stack_feasible": False,
            "stack_infeasibility_reason": "converter power limit exceeded",
            "stack_reference_cell_power_kw": reference_power_kw,
            "stack_maximum_local_current_density_a_m2": maximum_current_density_a_m2,
        }
    maximum_ns_voltage = math.floor(max_bus_voltage / cell_terminal_voltage_v)
    maximum_ns = min(max_series, maximum_ns_voltage)
    minimum_ns_current = max(1, math.ceil(integrated_current_a / max_bus_current))
    minimum_ns_voltage = max(
        1, math.ceil(minimum_converter_voltage / cell_terminal_voltage_v)
    )
    minimum_ns = max(minimum_ns_current, minimum_ns_voltage)
    if maximum_ns < minimum_ns:
        return {
            "stack_feasible": False,
            "stack_infeasibility_reason": (
                "no series count meets converter voltage/current limits"
            ),
            "minimum_series_cells_from_current": minimum_ns_current,
            "minimum_series_cells_from_voltage": minimum_ns_voltage,
            "maximum_series_cells_from_voltage": maximum_ns,
        }
    candidates: list[tuple[int, int, int]] = []
    for series_cells in range(minimum_ns, maximum_ns + 1):
        parallel_strings = math.ceil(minimum_cells / series_cells)
        total_cells = series_cells * parallel_strings
        candidates.append((total_cells, -series_cells, parallel_strings))
    total_cells, negative_series, parallel_strings = min(candidates)
    series_cells = -negative_series
    cell_area = required_area_m2 / total_cells
    cell_terminal_current = integrated_current_a / total_cells
    string_voltage = series_cells * cell_terminal_voltage_v
    dc_bus_current = integrated_current_a / series_cells
    topology_power_kw = string_voltage * dc_bus_current / 1000.0
    identity_error = topology_power_kw - reference_power_kw
    feasible = (
        cell_area <= max_cell_area + 1.0e-12
        and cell_terminal_current <= max_cell_current + 1.0e-9
        and string_voltage >= minimum_converter_voltage - 1.0e-12
        and string_voltage <= max_bus_voltage + 1.0e-12
        and dc_bus_current <= max_bus_current + 1.0e-9
        and topology_power_kw <= max_converter_power_kw + 1.0e-12
        and total_cells == series_cells * parallel_strings
        and abs(identity_error) <= 1.0e-9 * max(reference_power_kw, 1.0)
    )
    return {
        "stack_feasible": bool(feasible),
        "stack_infeasibility_reason": "" if feasible else "integer topology identity failure",
        "stack_series_cells": series_cells,
        "stack_parallel_strings": parallel_strings,
        "stack_total_cells": total_cells,
        "stack_cell_active_area_m2": cell_area,
        "stack_cell_terminal_current_a": cell_terminal_current,
        "stack_maximum_local_current_density_a_m2": maximum_current_density_a_m2,
        "stack_local_current_density_limit_interpretation": (
            "reported separately; no finite current-collector segment model"
        ),
        "stack_string_voltage_v": string_voltage,
        "stack_dc_bus_current_a": dc_bus_current,
        "stack_topology_power_kw": topology_power_kw,
        "stack_reference_cell_power_kw": reference_power_kw,
        "stack_power_identity_error_kw": identity_error,
        "stack_state_matching_assumption": (
            "series groups contain hydraulically parallel, state-matched repeat cells; "
            "axially dissimilar cells are not silently placed in one series string"
        ),
    }

__all__ = [
    "stack_topology",
]
