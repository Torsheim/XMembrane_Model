from __future__ import annotations

import math
from types import ModuleType
from typing import Any

import numpy as np
import pandas as pd

from heiq.wp1.airside.properties import (
    MOLAR_MASS_WATER_KG_MOL,
    AirflowBasis,
    activity_from_t_w,
    relative_humidity_from_t_w,
)

from .local_state import (
    local_derivatives,
    local_gate_status,
    solve_local_state,
)

def integrate_axial_case(
    *,
    v2: ModuleType,
    v2_config: dict[str, Any],
    config: dict[str, Any],
    basis: AirflowBasis,
    target_row: pd.Series,
    material: dict[str, Any],
    receiver_label: str,
    receiver_activity: float,
    terminal_voltage_v: float,
    fixed_loss_voltage_v: float,
    series_asr_ohm_m2: float,
    power_electronics_efficiency: float,
    current_cap_a_m2: float,
    film_scale_factor: float,
    thermal_mode: str,
    record_profile: bool,
) -> tuple[dict[str, Any], pd.DataFrame]:
    integration = config["integration"]
    thermal_config = config["thermal"]
    area_limit = float(integration["area_limit_m2"])
    nominal_step = float(integration["area_step_m2"])
    minimum_step = float(integration["minimum_area_step_m2"])
    target_w = float(target_row["target_humidity_ratio_kg_kg_da"])
    inlet_w = basis.inlet_humidity_ratio_kg_kg_da
    humidity_ratio = inlet_w
    temperature_c = basis.inlet_temperature_c
    cumulative_area = 0.0
    cell_power_w = 0.0
    membrane_power_w = 0.0
    series_loss_power_w = 0.0
    fixed_loss_power_w = 0.0
    current_integral_a = 0.0
    molar_transfer_integral_mol_s = 0.0
    profile_rows: list[dict[str, Any]] = []
    maximum_current = -math.inf
    minimum_flux = math.inf
    maximum_temperature = temperature_c
    status = "area_limit_before_target"
    last_local: dict[str, Any] | None = None

    def solve_at(water_ratio: float, temp_c: float) -> dict[str, Any]:
        return solve_local_state(
            v2=v2,
            v2_config=v2_config,
            material=material,
            source_temperature_c=temp_c,
            source_humidity_ratio=water_ratio,
            receiver_activity=receiver_activity,
            terminal_voltage_v=terminal_voltage_v,
            fixed_loss_voltage_v=fixed_loss_voltage_v,
            series_asr_ohm_m2=series_asr_ohm_m2,
            film_scale_factor=film_scale_factor,
            config=config,
        )

    while cumulative_area < area_limit - 1.0e-12:
        if humidity_ratio <= target_w + float(
            integration["humidity_ratio_absolute_tolerance"]
        ):
            status = "target_reached"
            break
        step = min(nominal_step, area_limit - cumulative_area)
        local_start = solve_at(humidity_ratio, temperature_c)
        gate = local_gate_status(
            local_start, current_cap_a_m2=current_cap_a_m2
        )
        if gate != "local_gates_pass":
            status = gate
            last_local = local_start
            break
        derivative_start = local_derivatives(
            local_start,
            dry_air_mass_flow_kg_s=basis.dry_air_mass_flow_kg_s,
            humidity_ratio=humidity_ratio,
            temperature_c=temperature_c,
            thermal_mode=thermal_mode,
            thermal_config=thermal_config,
        )

        while True:
            predicted_w = humidity_ratio + derivative_start[0] * step
            predicted_t = temperature_c + derivative_start[1] * step
            if predicted_w <= 0.0:
                local_end = {"solution_ok": False}
                end_gate = "predictor_negative_humidity_ratio"
            else:
                local_end = solve_at(predicted_w, predicted_t)
                end_gate = local_gate_status(
                    local_end, current_cap_a_m2=current_cap_a_m2
                )
            if end_gate == "local_gates_pass":
                break
            if step <= minimum_step + 1.0e-12:
                status = f"corrector_failure:{end_gate}"
                last_local = local_end
                break
            step = max(0.5 * step, minimum_step)
        if status.startswith("corrector_failure:"):
            break

        derivative_end = local_derivatives(
            local_end,
            dry_air_mass_flow_kg_s=basis.dry_air_mass_flow_kg_s,
            humidity_ratio=predicted_w,
            temperature_c=predicted_t,
            thermal_mode=thermal_mode,
            thermal_config=thermal_config,
        )
        corrected_w = humidity_ratio + 0.5 * (
            derivative_start[0] + derivative_end[0]
        ) * step
        corrected_t = temperature_c + 0.5 * (
            derivative_start[1] + derivative_end[1]
        ) * step
        step_fraction = 1.0
        if corrected_w < target_w:
            denominator = humidity_ratio - corrected_w
            step_fraction = (
                (humidity_ratio - target_w) / denominator
                if denominator > 0.0
                else 0.0
            )
            step_fraction = float(np.clip(step_fraction, 0.0, 1.0))
        effective_step = step * step_fraction
        next_w = humidity_ratio + step_fraction * (
            corrected_w - humidity_ratio
        )
        next_t = temperature_c + step_fraction * (
            corrected_t - temperature_c
        )

        def average(name: str) -> float:
            return 0.5 * (
                float(local_start[name]) + float(local_end[name])
            )

        mean_current = average("current_density_a_m2")
        mean_flux = average("net_flux_mol_m2_s")
        mean_cell_power_density = terminal_voltage_v * mean_current
        mean_membrane_power_density = average(
            "membrane_power_density_w_m2"
        )
        mean_series_power_density = average(
            "series_loss_power_density_w_m2"
        )
        mean_fixed_power_density = average(
            "fixed_loss_power_density_w_m2"
        )
        cell_power_w += mean_cell_power_density * effective_step
        membrane_power_w += mean_membrane_power_density * effective_step
        series_loss_power_w += mean_series_power_density * effective_step
        fixed_loss_power_w += mean_fixed_power_density * effective_step
        current_integral_a += mean_current * effective_step
        molar_transfer_integral_mol_s += mean_flux * effective_step
        maximum_current = max(
            maximum_current,
            float(local_start["current_density_a_m2"]),
            float(local_end["current_density_a_m2"]),
        )
        minimum_flux = min(
            minimum_flux,
            float(local_start["net_flux_mol_m2_s"]),
            float(local_end["net_flux_mol_m2_s"]),
        )
        maximum_temperature = max(maximum_temperature, next_t)

        if record_profile:
            profile_rows.append(
                {
                    "target": target_row["target"],
                    "material": material["name"],
                    "receiver_boundary": receiver_label,
                    "thermal_mode": thermal_mode,
                    "terminal_voltage_v": terminal_voltage_v,
                    "fixed_loss_voltage_v": fixed_loss_voltage_v,
                    "series_asr_ohm_m2": series_asr_ohm_m2,
                    "power_electronics_efficiency": (
                        power_electronics_efficiency
                    ),
                    "current_cap_a_m2": current_cap_a_m2,
                    "film_scale_factor": film_scale_factor,
                    "step_area_m2": effective_step,
                    "cumulative_area_m2": cumulative_area + effective_step,
                    "humidity_ratio_kg_kg_da": next_w,
                    "humidity_ratio_g_kg_da": 1000.0 * next_w,
                    "temperature_c": next_t,
                    "relative_humidity": relative_humidity_from_t_w(
                        next_t, next_w, basis.absolute_pressure_pa
                    ),
                    "source_bulk_activity": activity_from_t_w(
                        next_t, next_w, basis.absolute_pressure_pa
                    ),
                    "receiver_bulk_activity": receiver_activity,
                    "net_flux_mol_m2_s": mean_flux,
                    "net_flux_kg_m2_h": (
                        mean_flux * MOLAR_MASS_WATER_KG_MOL * 3600.0
                    ),
                    "current_density_a_m2": mean_current,
                    "membrane_voltage_v": average("membrane_voltage_v"),
                    "series_loss_voltage_v": average(
                        "series_loss_voltage_v"
                    ),
                    "source_surface_activity": average(
                        "source_surface_activity"
                    ),
                    "receiver_surface_activity": average(
                        "receiver_surface_activity"
                    ),
                    "source_film_coefficient_mol_m2_s_activity": average(
                        "source_film_coefficient_mol_m2_s_activity"
                    ),
                    "receiver_film_coefficient_mol_m2_s_activity": average(
                        "receiver_film_coefficient_mol_m2_s_activity"
                    ),
                    "cell_power_density_w_m2": mean_cell_power_density,
                    "cumulative_cell_power_kw": cell_power_w / 1000.0,
                }
            )

        cumulative_area += effective_step
        humidity_ratio = next_w
        temperature_c = next_t
        last_local = local_end
        if step_fraction < 1.0:
            status = "target_reached"
            break

    grid_power_kw = (
        cell_power_w / power_electronics_efficiency / 1000.0
        if math.isfinite(cell_power_w)
        else math.inf
    )
    power_electronics_loss_kw = (
        grid_power_kw - cell_power_w / 1000.0
        if math.isfinite(grid_power_kw)
        else math.inf
    )
    integrated_water_kg_h = (
        molar_transfer_integral_mol_s
        * MOLAR_MASS_WATER_KG_MOL
        * 3600.0
    )
    air_balance_water_kg_h = (
        basis.dry_air_mass_flow_kg_s
        * (inlet_w - humidity_ratio)
        * 3600.0
    )
    balance_scale = max(
        abs(integrated_water_kg_h), abs(air_balance_water_kg_h), 1.0e-12
    )
    mass_balance_relative_error = (
        integrated_water_kg_h - air_balance_water_kg_h
    ) / balance_scale
    profile = pd.DataFrame(profile_rows)
    raw_status = (
        str(last_local.get("raw_solution_status", "not_applicable"))
        if last_local is not None
        else "not_applicable"
    )
    return (
        {
            "target": target_row["target"],
            "material": material["name"],
            "material_model": material["model"],
            "receiver_boundary": receiver_label,
            "receiver_bulk_activity": receiver_activity,
            "thermal_mode": thermal_mode,
            "terminal_voltage_v": terminal_voltage_v,
            "fixed_loss_voltage_v": fixed_loss_voltage_v,
            "series_asr_ohm_m2": series_asr_ohm_m2,
            "power_electronics_efficiency": power_electronics_efficiency,
            "current_cap_a_m2": current_cap_a_m2,
            "internal_current_search_ceiling_a_m2": float(
                v2_config["model"]["current_solver_upper_bound_a_m2"]
            ),
            "film_scale_factor": film_scale_factor,
            "status": status,
            "last_raw_local_solution_status": raw_status,
            "target_reached": status == "target_reached",
            "required_active_area_m2": cumulative_area,
            "outlet_humidity_ratio_kg_kg_da": humidity_ratio,
            "target_humidity_ratio_kg_kg_da": target_w,
            "outlet_temperature_c": temperature_c,
            "maximum_process_temperature_c": maximum_temperature,
            "outlet_relative_humidity": relative_humidity_from_t_w(
                temperature_c, humidity_ratio, basis.absolute_pressure_pa
            ),
            "outlet_water_activity": activity_from_t_w(
                temperature_c, humidity_ratio, basis.absolute_pressure_pa
            ),
            "integrated_water_removal_kg_h": integrated_water_kg_h,
            "air_balance_water_removal_kg_h": air_balance_water_kg_h,
            "water_mass_balance_relative_error": mass_balance_relative_error,
            "maximum_local_current_density_a_m2": (
                maximum_current if maximum_current > -math.inf else math.nan
            ),
            "minimum_local_flux_mol_m2_s": (
                minimum_flux if minimum_flux < math.inf else math.nan
            ),
            "integrated_current_a": current_integral_a,
            "cell_power_kw": cell_power_w / 1000.0,
            "membrane_power_kw": membrane_power_w / 1000.0,
            "series_loss_power_kw": series_loss_power_w / 1000.0,
            "fixed_loss_power_kw": fixed_loss_power_w / 1000.0,
            "power_electronics_loss_kw": power_electronics_loss_kw,
            "eo_grid_power_kw": grid_power_kw,
            "eo_grid_sec_kwh_kg": (
                grid_power_kw / integrated_water_kg_h
                if integrated_water_kg_h > 0.0
                else math.inf
            ),
        },
        profile,
    )

__all__ = [
    "integrate_axial_case",
]
