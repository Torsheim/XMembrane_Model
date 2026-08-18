from __future__ import annotations

from dataclasses import asdict
import copy
import math
from types import ModuleType
from typing import Any, Mapping

import pandas as pd

from heiq.wp1.airside.properties import (
    ACTIVITY_EPS,
    MOLAR_MASS_WATER_KG_MOL,
    activity_from_t_w,
)
from heiq.wp1.axial.local_state import (
    solve_local_state,
)

from .basis import ReceiverBasis


MATERIAL_COLUMNS = ['water_drag', 'water_diffusivity_m2_s', 'conductivity_s_m', 'dry_thickness_um', 'water_capacity_mol_m3_activity', 'diffusivity_activity_exponent', 'conductivity_activity_exponent', 'capacity_activity_exponent']


def coupled_local_gate(local: Mapping[str, Any], current_cap_a_m2: float) -> str:
    if not bool(local.get("solution_ok", False)):
        return str(local.get("solution_status", "unknown_local_failure"))
    flux = float(local["net_flux_mol_m2_s"])
    current = float(local["current_density_a_m2"])
    if not math.isfinite(flux) or flux <= 0.0:
        return "nonpositive_net_water_flux"
    if not math.isfinite(current) or current <= 0.0:
        return "nonpositive_current_density"
    if current > current_cap_a_m2:
        return "operating_current_density_limit"
    return "local_gates_pass"

def integrate_coupled_receiver_case(
    *,
    axial: ModuleType,
    v2: ModuleType,
    v2_config: Mapping[str, Any],
    config: Mapping[str, Any],
    process_basis: Any,
    target_row: Mapping[str, Any],
    material: Mapping[str, Any],
    receiver: ReceiverBasis,
    terminal_voltage_v: float,
    electrode_pair_loss_voltage_v: float,
    legacy_series_asr_ohm_m2: float,
    added_contact_asr_ohm_m2: float,
    power_electronics_efficiency: float,
    current_cap_a_m2: float,
    film_scale_factor: float,
    record_profile: bool,
) -> tuple[dict[str, Any], pd.DataFrame]:
    """Integrate a co- or counter-current two-stream membrane case.

    The same mean flux updates both streams, so each numerical segment closes
    water mass by construction.  Counter-current starts at the process inlet
    paired with the receiver outlet, whose humidity is fixed by the requested
    target and the global receiver balance.
    """
    integration = config["integration"]
    area_limit = float(integration["area_limit_m2"])
    nominal_step = float(integration["area_step_m2"])
    minimum_step = float(integration["minimum_area_step_m2"])
    humidity_tolerance = float(integration["humidity_ratio_absolute_tolerance"])
    balance_tolerance = float(integration["mass_balance_relative_tolerance"])
    target_w = float(target_row["target_humidity_ratio_kg_kg_da"])
    process_inlet_w = float(process_basis.inlet_humidity_ratio_kg_kg_da)
    process_w = process_inlet_w
    process_temperature_c = float(process_basis.inlet_temperature_c)
    receiver_inlet_w = receiver.inlet_humidity_ratio_kg_kg_da
    if receiver.flow_arrangement == "co_current":
        receiver_w = receiver_inlet_w
        receiver_derivative_sign = 1.0
    elif receiver.flow_arrangement == "counter_current":
        receiver_w = receiver.target_outlet_humidity_ratio_kg_kg_da
        receiver_derivative_sign = -1.0
    else:
        raise ValueError(f"Unknown flow arrangement {receiver.flow_arrangement}")

    identity = {
        "target": str(target_row["target"]),
        "material_id": str(material["name"]),
        **{name: float(material[name]) for name in MATERIAL_COLUMNS},
        "terminal_voltage_v": float(terminal_voltage_v),
        "is_exact_1v_solver_point": float(terminal_voltage_v) == 1.0,
        "electrode_pair_loss_voltage_v": float(electrode_pair_loss_voltage_v),
        "legacy_series_asr_ohm_m2": float(legacy_series_asr_ohm_m2),
        "added_contact_asr_ohm_m2": float(added_contact_asr_ohm_m2),
        **asdict(receiver),
    }
    if not receiver.target_capacity_sufficient:
        return (
            {
                **identity,
                "status": "receiver_capacity_insufficient_for_target_band",
                "target_reached": False,
                "required_active_area_m2": 0.0,
                "process_outlet_humidity_ratio_kg_kg_da": process_inlet_w,
                "receiver_outlet_humidity_ratio_kg_kg_da": math.nan,
                "receiver_outlet_activity": math.nan,
                "integrated_water_transfer_kg_h": 0.0,
                "process_air_balance_water_removal_kg_h": 0.0,
                "receiver_air_balance_water_gain_kg_h": 0.0,
                "process_mass_balance_relative_error": 0.0,
                "receiver_mass_balance_relative_error": 0.0,
                "maximum_local_current_density_a_m2": math.nan,
                "minimum_local_flux_mol_m2_s": math.nan,
                "integrated_current_a": 0.0,
                "cell_power_kw": 0.0,
                "membrane_power_kw": 0.0,
                "legacy_series_loss_power_kw": 0.0,
                "added_contact_loss_power_kw": 0.0,
                "electrode_loss_power_kw": 0.0,
                "power_electronics_loss_kw": 0.0,
                "eo_grid_power_kw": 0.0,
                "maximum_terminal_voltage_error_v": math.nan,
                "receiver_boundary_pass": False,
                "water_balance_evaluated": False,
                "water_balance_pass": False,
                "local_solver_evaluated": False,
                "worker_exception": "",
            },
            pd.DataFrame(),
        )

    local_config = copy.deepcopy(dict(config))
    local_config["channel"] = copy.deepcopy(dict(config["channel"]))
    local_config["channel"]["receiver_velocity_m_s"] = receiver.receiver_velocity_m_s
    total_series_asr = legacy_series_asr_ohm_m2 + added_contact_asr_ohm_m2
    process_mass_flow = float(process_basis.dry_air_mass_flow_kg_s)
    receiver_mass_flow = receiver.selected_dry_air_mass_flow_kg_s
    maximum_receiver_w = receiver.maximum_outlet_humidity_ratio_kg_kg_da

    cumulative_area = 0.0
    cell_power_w = 0.0
    membrane_power_w = 0.0
    legacy_series_power_w = 0.0
    contact_power_w = 0.0
    electrode_power_w = 0.0
    integrated_current_a = 0.0
    integrated_transfer_mol_s = 0.0
    maximum_current = -math.inf
    minimum_flux = math.inf
    maximum_voltage_error = 0.0
    profile_rows: list[dict[str, Any]] = []
    status = "area_limit_before_target"
    last_local: Mapping[str, Any] | None = None
    shortened_endpoint_resolved = False

    def receiver_activity(water_ratio: float) -> float:
        return float(
            activity_from_t_w(
                receiver.temperature_c,
                water_ratio,
                receiver.pressure_pa,
            )
        )

    def solve_at(process_ratio: float, receiver_ratio: float) -> dict[str, Any]:
        activity = receiver_activity(receiver_ratio)
        if not ACTIVITY_EPS < activity < 1.0 - ACTIVITY_EPS:
            return {
                "solution_ok": False,
                "solution_status": "receiver_bulk_activity_out_of_bounds",
                "raw_solution_status": "receiver_bulk_activity_out_of_bounds",
                "receiver_bulk_activity": activity,
            }
        return solve_local_state(
            v2=v2,
            v2_config=v2_config,
            material=dict(material),
            source_temperature_c=process_temperature_c,
            source_humidity_ratio=process_ratio,
            receiver_activity=activity,
            terminal_voltage_v=terminal_voltage_v,
            fixed_loss_voltage_v=electrode_pair_loss_voltage_v,
            series_asr_ohm_m2=total_series_asr,
            film_scale_factor=film_scale_factor,
            config=local_config,
        )

    while cumulative_area < area_limit - 1.0e-12:
        if process_w <= target_w + humidity_tolerance:
            status = "target_reached"
            break
        step = min(nominal_step, area_limit - cumulative_area)
        local_start = solve_at(process_w, receiver_w)
        start_gate = coupled_local_gate(local_start, current_cap_a_m2)
        if start_gate != "local_gates_pass":
            status = start_gate
            last_local = local_start
            break
        start_flux = float(local_start["net_flux_mol_m2_s"])

        while True:
            transfer_start_kg_s = start_flux * MOLAR_MASS_WATER_KG_MOL * step
            predicted_process_w = process_w - transfer_start_kg_s / process_mass_flow
            predicted_receiver_w = (
                receiver_w
                + receiver_derivative_sign * transfer_start_kg_s / receiver_mass_flow
            )
            if predicted_process_w <= 0.0:
                end_gate = "predictor_negative_process_humidity_ratio"
                local_end = {"solution_ok": False}
            elif predicted_receiver_w <= 0.0:
                end_gate = "predictor_negative_receiver_humidity_ratio"
                local_end = {"solution_ok": False}
            elif (
                receiver.flow_arrangement == "co_current"
                and predicted_receiver_w > maximum_receiver_w + humidity_tolerance
            ):
                end_gate = "predictor_receiver_activity_limit"
                local_end = {"solution_ok": False}
            else:
                local_end = solve_at(predicted_process_w, predicted_receiver_w)
                end_gate = coupled_local_gate(local_end, current_cap_a_m2)
            if end_gate == "local_gates_pass":
                break
            if step <= minimum_step + 1.0e-12:
                status = f"corrector_failure:{end_gate}"
                last_local = local_end
                break
            step = max(0.5 * step, minimum_step)
        if status.startswith("corrector_failure:"):
            break

        end_flux = float(local_end["net_flux_mol_m2_s"])
        mean_flux = 0.5 * (start_flux + end_flux)
        full_transfer_kg_s = mean_flux * MOLAR_MASS_WATER_KG_MOL * step
        if full_transfer_kg_s <= 0.0 or not math.isfinite(full_transfer_kg_s):
            status = "nonpositive_corrected_water_transfer"
            last_local = local_end
            break

        process_needed_kg_s = process_mass_flow * max(process_w - target_w, 0.0)
        fractions = [(1.0, "continue")]
        fractions.append((process_needed_kg_s / full_transfer_kg_s, "target_reached"))
        if receiver.flow_arrangement == "co_current":
            receiver_capacity_kg_s = receiver_mass_flow * max(
                maximum_receiver_w - receiver_w, 0.0
            )
            fractions.append(
                (
                    receiver_capacity_kg_s / full_transfer_kg_s,
                    "receiver_activity_limit_before_target",
                )
            )
        nonnegative = [(max(0.0, value), label) for value, label in fractions]
        step_fraction, limiting_status = min(nonnegative, key=lambda item: item[0])
        step_fraction = min(step_fraction, 1.0)
        if step_fraction < 1.0:
            # The old implementation scaled a full-step trapezoid even though
            # its end state lay beyond the target/band boundary.  Resolve the
            # physical event state, re-run the local solver there, and derive
            # the shortened area from the event's exact transferred water.
            if limiting_status == "target_reached":
                transferred_kg_s = process_needed_kg_s
                next_process_w = target_w
                next_receiver_w = receiver_w + (
                    receiver_derivative_sign
                    * transferred_kg_s
                    / receiver_mass_flow
                )
            elif limiting_status == "receiver_activity_limit_before_target":
                transferred_kg_s = receiver_capacity_kg_s
                next_receiver_w = maximum_receiver_w
                next_process_w = process_w - transferred_kg_s / process_mass_flow
            else:
                raise RuntimeError(f"Unexpected shortened-step status {limiting_status}")
            event_end = solve_at(next_process_w, next_receiver_w)
            event_gate = coupled_local_gate(event_end, current_cap_a_m2)
            if event_gate != "local_gates_pass":
                status = f"shortened_endpoint_failure:{event_gate}"
                last_local = event_end
                break
            local_end = event_end
            end_flux = float(local_end["net_flux_mol_m2_s"])
            mean_flux = 0.5 * (start_flux + end_flux)
            effective_step = transferred_kg_s / (
                mean_flux * MOLAR_MASS_WATER_KG_MOL
            )
            if (
                not math.isfinite(effective_step)
                or effective_step < 0.0
                or effective_step > step * (1.0 + 1.0e-8)
            ):
                status = "shortened_endpoint_area_inconsistent"
                last_local = local_end
                break
            step_fraction = effective_step / step
            shortened_endpoint_resolved = True
        else:
            effective_step = step
            transferred_kg_s = full_transfer_kg_s
            next_process_w = process_w - transferred_kg_s / process_mass_flow
            next_receiver_w = receiver_w + (
                receiver_derivative_sign
                * transferred_kg_s
                / receiver_mass_flow
            )

        def mean(name: str) -> float:
            return 0.5 * (float(local_start[name]) + float(local_end[name]))

        mean_current = mean("current_density_a_m2")
        mean_membrane_power = mean("membrane_power_density_w_m2")
        start_current = float(local_start["current_density_a_m2"])
        end_current = float(local_end["current_density_a_m2"])
        mean_current_squared = 0.5 * (start_current**2 + end_current**2)
        mean_legacy_series_power = (
            mean_current_squared * legacy_series_asr_ohm_m2
        )
        mean_contact_power = mean_current_squared * added_contact_asr_ohm_m2
        mean_electrode_power = mean_current * electrode_pair_loss_voltage_v
        mean_cell_power = terminal_voltage_v * mean_current
        component_sum = (
            mean_membrane_power
            + mean_legacy_series_power
            + mean_contact_power
            + mean_electrode_power
        )
        component_tolerance = 1.0e-6 + 1.0e-7 * max(abs(mean_cell_power), 1.0)
        if abs(component_sum - mean_cell_power) > component_tolerance:
            status = "electrical_component_identity_failure"
            last_local = local_end
            break

        cell_power_w += mean_cell_power * effective_step
        membrane_power_w += mean_membrane_power * effective_step
        legacy_series_power_w += mean_legacy_series_power * effective_step
        contact_power_w += mean_contact_power * effective_step
        electrode_power_w += mean_electrode_power * effective_step
        integrated_current_a += mean_current * effective_step
        integrated_transfer_mol_s += mean_flux * effective_step
        maximum_current = max(
            maximum_current,
            float(local_start["current_density_a_m2"]),
            float(local_end["current_density_a_m2"]),
        )
        minimum_flux = min(minimum_flux, start_flux, end_flux)
        maximum_voltage_error = max(
            maximum_voltage_error,
            abs(float(local_start["terminal_voltage_error_v"])),
            abs(float(local_end["terminal_voltage_error_v"])),
        )

        cumulative_area += effective_step
        process_w = next_process_w
        receiver_w = next_receiver_w
        last_local = local_end
        if record_profile:
            profile_rows.append(
                {
                    **identity,
                    "cumulative_area_m2": cumulative_area,
                    "step_area_m2": effective_step,
                    "process_humidity_ratio_kg_kg_da": process_w,
                    "process_activity": float(
                        activity_from_t_w(
                            process_temperature_c,
                            process_w,
                            process_basis.absolute_pressure_pa,
                        )
                    ),
                    "receiver_humidity_ratio_kg_kg_da": receiver_w,
                    "receiver_activity": receiver_activity(receiver_w),
                    "net_flux_mol_m2_s": mean_flux,
                    "current_density_a_m2": mean_current,
                    "cell_power_density_w_m2": mean_cell_power,
                    "cumulative_cell_power_kw": cell_power_w / 1000.0,
                }
            )
        if step_fraction < 1.0:
            status = limiting_status
            break

    countercurrent_boundary_solution_valid = bool(
        receiver.flow_arrangement == "counter_current" and status == "target_reached"
    )
    if receiver.flow_arrangement == "co_current":
        receiver_outlet_w = receiver_w
        receiver_boundary_residual_w = math.nan
        receiver_calculated_far_end_w = receiver_outlet_w
    elif countercurrent_boundary_solution_valid:
        receiver_outlet_w = receiver.target_outlet_humidity_ratio_kg_kg_da
        receiver_boundary_residual_w = receiver_w - receiver_inlet_w
        receiver_calculated_far_end_w = receiver_w
    else:
        # The counter-current IVP was conditioned on the requested outlet.  If
        # it did not reach the target, that assumed outlet is not a solved
        # physical boundary and must not be published as one.
        receiver_outlet_w = math.nan
        receiver_boundary_residual_w = math.nan
        receiver_calculated_far_end_w = math.nan

    integrated_water_kg_h = (
        integrated_transfer_mol_s * MOLAR_MASS_WATER_KG_MOL * 3600.0
    )
    process_balance_kg_h = (
        process_mass_flow * (process_inlet_w - process_w) * 3600.0
    )
    receiver_balance_kg_h = (
        receiver_mass_flow * (receiver_outlet_w - receiver_inlet_w) * 3600.0
        if receiver.flow_arrangement == "co_current"
        else receiver_mass_flow
        * (receiver_outlet_w - receiver_calculated_far_end_w)
        * 3600.0
    )

    def relative_error(left: float, right: float) -> float:
        scale = max(abs(left), abs(right), 1.0e-12)
        return (left - right) / scale

    process_error = relative_error(integrated_water_kg_h, process_balance_kg_h)
    receiver_error = (
        relative_error(integrated_water_kg_h, receiver_balance_kg_h)
        if math.isfinite(receiver_balance_kg_h)
        else math.nan
    )
    receiver_boundary_pass = (
        True
        if receiver.flow_arrangement == "co_current"
        else countercurrent_boundary_solution_valid
        and abs(receiver_boundary_residual_w) <= max(humidity_tolerance, 1.0e-10)
    )
    balance_pass = (
        abs(process_error) <= balance_tolerance
        and math.isfinite(receiver_error)
        and abs(receiver_error) <= balance_tolerance
        and receiver_boundary_pass
    )
    if status == "target_reached" and not balance_pass:
        status = "coupled_water_balance_failure"

    grid_power_kw = cell_power_w / power_electronics_efficiency / 1000.0
    power_electronics_loss_kw = grid_power_kw - cell_power_w / 1000.0
    return (
        {
            **identity,
            "status": status,
            "target_reached": status == "target_reached",
            "required_active_area_m2": cumulative_area,
            "process_inlet_humidity_ratio_kg_kg_da": process_inlet_w,
            "process_outlet_humidity_ratio_kg_kg_da": process_w,
            "target_humidity_ratio_kg_kg_da": target_w,
            "receiver_inlet_humidity_ratio_kg_kg_da": receiver_inlet_w,
            "receiver_outlet_humidity_ratio_kg_kg_da": receiver_outlet_w,
            "receiver_calculated_far_end_humidity_ratio_kg_kg_da": (
                receiver_calculated_far_end_w
            ),
            "receiver_outlet_activity": (
                receiver_activity(receiver_outlet_w)
                if math.isfinite(receiver_outlet_w)
                else math.nan
            ),
            "receiver_boundary_residual_humidity_ratio": receiver_boundary_residual_w,
            "countercurrent_boundary_solution_valid": (
                countercurrent_boundary_solution_valid
            ),
            "integrated_water_transfer_kg_h": integrated_water_kg_h,
            "process_air_balance_water_removal_kg_h": process_balance_kg_h,
            "receiver_air_balance_water_gain_kg_h": receiver_balance_kg_h,
            "process_mass_balance_relative_error": process_error,
            "receiver_mass_balance_relative_error": receiver_error,
            "receiver_boundary_pass": receiver_boundary_pass,
            "water_balance_evaluated": True,
            "water_balance_pass": balance_pass,
            "local_solver_evaluated": True,
            "shortened_endpoint_resolved": shortened_endpoint_resolved,
            "maximum_local_current_density_a_m2": (
                maximum_current if maximum_current > -math.inf else math.nan
            ),
            "minimum_local_flux_mol_m2_s": (
                minimum_flux if minimum_flux < math.inf else math.nan
            ),
            "integrated_current_a": integrated_current_a,
            "cell_power_kw": cell_power_w / 1000.0,
            "membrane_power_kw": membrane_power_w / 1000.0,
            "legacy_series_loss_power_kw": legacy_series_power_w / 1000.0,
            "added_contact_loss_power_kw": contact_power_w / 1000.0,
            "electrode_loss_power_kw": electrode_power_w / 1000.0,
            "power_electronics_loss_kw": power_electronics_loss_kw,
            "eo_grid_power_kw": grid_power_kw,
            "maximum_terminal_voltage_error_v": maximum_voltage_error,
            "worker_exception": "",
            "material_evidence": (
                "hypothetical independent V11 property combination; not material validation"
            ),
        },
        pd.DataFrame(profile_rows),
    )

__all__ = [
    "MATERIAL_COLUMNS",
    "coupled_local_gate",
    "integrate_coupled_receiver_case",
]
