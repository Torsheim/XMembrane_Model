#!/usr/bin/env python3
"""Size a modular, two-sided EO water-vapour coupon cell.

This is a measurement-design calculation, not a membrane-performance model.
It deliberately keeps the following quantities separate:

* gross Faradaic EO water rate inferred from a declared transport number;
* the ideal outlet humidity shift if that gross rate entered a gas stream;
* channel flow, residence time, Reynolds number and parallel-plate pressure drop;
* the gas volume needed to limit humidity drift in an unbuffered closed loop; and
* aperture edge-to-area sensitivity, fixture lands and internal dead volume;
* ideal humidity-signal detectability as a function of flow; and
* a classical plate-deflection screen for candidate wall/load-plate materials.

Net measured water transport can be much lower than the gross EO rate because of
passive back-diffusion, gas films, leakage, membrane inventory changes and electrode
reactions.  The output therefore labels all transport estimates as gross-only.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path
from typing import Any, Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


FARADAY_C_MOL = 96485.33212
WATER_MOLAR_MASS_KG_MOL = 0.01801528
DRY_AIR_GAS_CONSTANT_J_KG_K = 287.058
WATER_VAPOUR_GAS_CONSTANT_J_KG_K = 461.495
AIR_DYNAMIC_VISCOSITY_PA_S_AT_32C = 1.87e-5
UNIVERSAL_GAS_CONSTANT_J_MOL_K = 8.31446261815324


def sha256(path: Path) -> str:
    """Return a streaming SHA-256 digest for a provenance record."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description="Dimension an EO vapour coupon cell and its measurement envelope.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=root / "config" / "eo_vapor_test_cell_design.json",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=root / "outputs" / "eo_vapor_cell_sizing_v1",
    )
    return parser.parse_args()


def saturation_pressure_water_pa(temperature_c: float) -> float:
    """Buck saturation pressure over liquid water (Pa; ordinary lab range)."""

    return 611.21 * math.exp(
        (18.678 - temperature_c / 234.5)
        * (temperature_c / (257.14 + temperature_c))
    )


def humidity_ratio_kg_kg_da(
    activity: float, temperature_c: float, absolute_pressure_pa: float
) -> float:
    p_w = activity * saturation_pressure_water_pa(temperature_c)
    if not 0.0 <= activity <= 1.0:
        raise ValueError("Water activity must be between zero and one")
    if p_w >= absolute_pressure_pa:
        raise ValueError("Water partial pressure must be below total pressure")
    return 0.621945 * p_w / (absolute_pressure_pa - p_w)


def activity_from_humidity_ratio(
    humidity_ratio: float, temperature_c: float, absolute_pressure_pa: float
) -> float:
    if humidity_ratio < 0.0:
        return math.nan
    p_w = absolute_pressure_pa * humidity_ratio / (0.621945 + humidity_ratio)
    return p_w / saturation_pressure_water_pa(temperature_c)


def gross_eo_water_mg_h(
    area_cm2: float, current_density_a_m2: float, water_transport_number: float
) -> float:
    """Faradaic EO water rate n_drag * I/F, expressed as mg/h."""

    area_m2 = area_cm2 / 1.0e4
    current_a = current_density_a_m2 * area_m2
    return (
        water_transport_number
        * current_a
        / FARADAY_C_MOL
        * WATER_MOLAR_MASS_KG_MOL
        * 3600.0
        * 1.0e6
    )


def dry_air_mass_flow_kg_h(
    actual_flow_l_min: float,
    activity: float,
    temperature_c: float,
    absolute_pressure_pa: float,
) -> float:
    temperature_k = temperature_c + 273.15
    p_da = absolute_pressure_pa - activity * saturation_pressure_water_pa(temperature_c)
    volume_flow_m3_s = actual_flow_l_min / 1000.0 / 60.0
    return p_da / (DRY_AIR_GAS_CONSTANT_J_KG_K * temperature_k) * volume_flow_m3_s * 3600.0


def moist_air_density_kg_m3(
    activity: float, temperature_c: float, absolute_pressure_pa: float
) -> float:
    temperature_k = temperature_c + 273.15
    p_w = activity * saturation_pressure_water_pa(temperature_c)
    p_da = absolute_pressure_pa - p_w
    return p_da / (DRY_AIR_GAS_CONSTANT_J_KG_K * temperature_k) + p_w / (
        WATER_VAPOUR_GAS_CONSTANT_J_KG_K * temperature_k
    )


def ideal_two_stream_humidity_signal(
    *,
    water_rate_mg_h: float,
    actual_flow_l_min_per_side: float,
    inlet_activity: float,
    temperature_c: float,
    absolute_pressure_pa: float,
) -> dict[str, float]:
    """Ideal source-plus-receiver RH signal for a declared water rate.

    The calculation is a gas-side detectability screen.  It assumes the full
    declared rate leaves one dry-air stream and enters the other, with equal
    actual volumetric flow on the two sides.  It does not include passive
    back-diffusion, gas-film loss, storage, leakage, or electrode water.
    """

    if actual_flow_l_min_per_side <= 0.0:
        raise ValueError("Actual gas flow must be positive")
    inlet_w = humidity_ratio_kg_kg_da(
        inlet_activity, temperature_c, absolute_pressure_pa
    )
    dry_air_kg_h = dry_air_mass_flow_kg_h(
        actual_flow_l_min_per_side,
        inlet_activity,
        temperature_c,
        absolute_pressure_pa,
    )
    delta_w = water_rate_mg_h / 1.0e6 / dry_air_kg_h
    receiver_activity = activity_from_humidity_ratio(
        inlet_w + delta_w, temperature_c, absolute_pressure_pa
    )
    source_activity = activity_from_humidity_ratio(
        inlet_w - delta_w, temperature_c, absolute_pressure_pa
    )
    receiver_shift_pp = (receiver_activity - inlet_activity) * 100.0
    source_shift_pp = (inlet_activity - source_activity) * 100.0
    return {
        "receiver_shift_rh_percentage_points": receiver_shift_pp,
        "source_shift_rh_percentage_points": source_shift_pp,
        "differential_signal_rh_percentage_points": (
            receiver_shift_pp + source_shift_pp
        ),
    }


def iter_transport_rows(
    config: dict[str, Any], study_key: str, geometry_rows: pd.DataFrame
) -> Iterable[dict[str, Any]]:
    state = config["operating_state"]
    study = config[study_key]
    temperature_c = float(state["temperature_c"])
    pressure_pa = float(state["absolute_pressure_pa"])
    activity = float(state["equal_inlet_water_activity"])
    uncertainty_single_pp = float(
        config["measurement"][
            "single_stream_humidity_expanded_uncertainty_rh_percentage_points"
        ]
    )
    differential_uncertainty_pp = math.sqrt(2.0) * uncertainty_single_pp
    required_snr = float(
        config["measurement"]["minimum_signal_to_uncertainty_ratio"]
    )
    gas_screen = config["faradaic_gas_safety_screen"]
    electrons_per_h2 = float(gas_screen["electrons_per_h2_molecule"])
    warning_h2_fraction = float(gas_screen["warning_h2_volume_fraction"])

    for geometry, transport_number, current_density in itertools.product(
        geometry_rows.to_dict(orient="records"),
        study["water_transport_numbers"],
        study["current_densities_a_m2"],
    ):
        area_cm2 = float(geometry["active_area_cm2"])
        total_current_a = float(current_density) * area_cm2 / 1.0e4
        water_mg_h = gross_eo_water_mg_h(
            area_cm2, float(current_density), float(transport_number)
        )
        signal = ideal_two_stream_humidity_signal(
            water_rate_mg_h=water_mg_h,
            actual_flow_l_min_per_side=float(geometry["actual_flow_l_min"]),
            inlet_activity=activity,
            temperature_c=temperature_c,
            absolute_pressure_pa=pressure_pa,
        )
        receiver_shift_pp = signal["receiver_shift_rh_percentage_points"]
        source_shift_pp = signal["source_shift_rh_percentage_points"]
        differential_signal_pp = signal[
            "differential_signal_rh_percentage_points"
        ]
        signal_to_uncertainty = differential_signal_pp / differential_uncertainty_pp
        h2_mol_s_upper_bound = total_current_a / (
            electrons_per_h2 * FARADAY_C_MOL
        )
        h2_m3_s_upper_bound = (
            h2_mol_s_upper_bound
            * UNIVERSAL_GAS_CONSTANT_J_MOL_K
            * (temperature_c + 273.15)
            / pressure_pa
        )
        h2_ml_min_upper_bound = h2_m3_s_upper_bound * 1.0e6 * 60.0
        h2_warning_inventory_ml = (
            warning_h2_fraction * float(geometry["active_channel_volume_ml_per_side"])
        )
        time_to_h2_warning_min = (
            h2_warning_inventory_ml / h2_ml_min_upper_bound
            if h2_ml_min_upper_bound > 0.0
            else math.inf
        )

        yield {
            "study": study_key,
            "gross_only": True,
            "water_transport_number": float(transport_number),
            "current_density_a_m2": float(current_density),
            "total_current_ma": total_current_a * 1000.0,
            "gross_eo_water_mg_h": water_mg_h,
            "gross_eo_flux_g_m2_h": water_mg_h * 10.0 / area_cm2,
            "receiver_ideal_rh_shift_percentage_points": receiver_shift_pp,
            "source_ideal_rh_shift_percentage_points": source_shift_pp,
            "two_stream_ideal_differential_signal_percentage_points": differential_signal_pp,
            "two_stream_signal_to_expanded_uncertainty": signal_to_uncertainty,
            "passes_declared_detectability_screen": signal_to_uncertainty >= required_snr,
            "h2_100pct_faradaic_upper_bound_ml_min": h2_ml_min_upper_bound,
            "minutes_to_declared_h2_warning_in_unvented_active_channel_upper_bound": time_to_h2_warning_min,
            "faradaic_gas_is_diagnostic_not_prediction": True,
            **geometry,
        }


def build_geometry_frame(config: dict[str, Any]) -> pd.DataFrame:
    state = config["operating_state"]
    geometry = config["geometry"]
    temperature_c = float(state["temperature_c"])
    pressure_pa = float(state["absolute_pressure_pa"])
    activity = float(state["equal_inlet_water_activity"])
    density = moist_air_density_kg_m3(activity, temperature_c, pressure_pa)
    mu = AIR_DYNAMIC_VISCOSITY_PA_S_AT_32C
    rows: list[dict[str, Any]] = []

    for area_cm2, gap_mm, velocity in itertools.product(
        geometry["square_active_areas_cm2"],
        geometry["channel_gaps_mm"],
        geometry["channel_velocities_m_s"],
    ):
        width_m = math.sqrt(float(area_cm2) / 1.0e4)
        length_m = width_m
        gap_m = float(gap_mm) / 1000.0
        area_m2 = float(area_cm2) / 1.0e4
        volume_m3 = area_m2 * gap_m
        volume_flow_m3_s = float(velocity) * width_m * gap_m
        actual_flow_l_min = volume_flow_m3_s * 60.0 * 1000.0
        hydraulic_diameter_m = 2.0 * width_m * gap_m / (width_m + gap_m)
        reynolds = density * float(velocity) * hydraulic_diameter_m / mu
        aspect_correction = max(1.0 - 0.630 * gap_m / width_m, 0.1)
        pressure_drop_pa = (
            12.0
            * mu
            * length_m
            * volume_flow_m3_s
            / (width_m * gap_m**3 * aspect_correction)
        )
        rows.append(
            {
                "active_area_cm2": float(area_cm2),
                "square_width_mm": width_m * 1000.0,
                "flow_length_mm": length_m * 1000.0,
                "channel_gap_mm": float(gap_mm),
                "channel_velocity_m_s": float(velocity),
                "actual_flow_l_min": actual_flow_l_min,
                "active_channel_volume_ml_per_side": volume_m3 * 1.0e6,
                "gas_residence_time_ms": length_m / float(velocity) * 1000.0,
                "hydraulic_diameter_mm": hydraulic_diameter_m * 1000.0,
                "reynolds_number": reynolds,
                "ideal_parallel_plate_pressure_drop_pa": pressure_drop_pa,
            }
        )
    return pd.DataFrame(rows)


def build_edge_frame(config: dict[str, Any]) -> pd.DataFrame:
    edge_mm = float(config["geometry"]["edge_strip_width_mm"])
    rows = []
    for area_cm2 in config["geometry"]["square_active_areas_cm2"]:
        side_mm = math.sqrt(float(area_cm2) * 100.0)
        inner_side_mm = max(side_mm - 2.0 * edge_mm, 0.0)
        rows.append(
            {
                "nominal_area_cm2": float(area_cm2),
                "square_side_mm": side_mm,
                "perimeter_mm": 4.0 * side_mm,
                "perimeter_to_area_mm_inverse": 4.0 / side_mm,
                "assumed_dead_edge_strip_mm": edge_mm,
                "area_fraction_inside_dead_edge": (inner_side_mm / side_mm) ** 2,
                "nominal_area_loss_percent": 100.0
                * (1.0 - (inner_side_mm / side_mm) ** 2),
            }
        )
    return pd.DataFrame(rows)


def build_fixture_dimension_frame(config: dict[str, Any]) -> pd.DataFrame:
    """Resolve the nominal fixture lands from the declared plan dimensions."""

    fixture = config["fixture_starting_point"]
    window_x, window_y = [float(value) for value in fixture["maximum_active_window_mm"]]
    coupon_x, coupon_y = [float(value) for value in fixture["membrane_coupon_mm"]]
    plate_x, plate_y = [float(value) for value in fixture["outer_plate_mm"]]
    coupon_land_x = 0.5 * (coupon_x - window_x)
    coupon_land_y = 0.5 * (coupon_y - window_y)
    outer_land_x = 0.5 * (plate_x - coupon_x)
    outer_land_y = 0.5 * (plate_y - coupon_y)
    seal_guard_stack = sum(
        float(fixture[key])
        for key in (
            "inner_seal_width_mm",
            "guard_groove_width_mm",
            "outer_seal_width_mm",
        )
    )
    return pd.DataFrame(
        [
            {
                "maximum_active_window_x_mm": window_x,
                "maximum_active_window_y_mm": window_y,
                "membrane_coupon_x_mm": coupon_x,
                "membrane_coupon_y_mm": coupon_y,
                "outer_plate_x_mm": plate_x,
                "outer_plate_y_mm": plate_y,
                "coupon_land_each_side_x_mm": coupon_land_x,
                "coupon_land_each_side_y_mm": coupon_land_y,
                "outer_fixture_land_each_side_x_mm": outer_land_x,
                "outer_fixture_land_each_side_y_mm": outer_land_y,
                "inner_seal_width_mm": float(fixture["inner_seal_width_mm"]),
                "guard_groove_width_mm": float(fixture["guard_groove_width_mm"]),
                "outer_seal_width_mm": float(fixture["outer_seal_width_mm"]),
                "seal_guard_stack_width_mm": seal_guard_stack,
                "remaining_coupon_land_after_seal_guard_stack_mm": min(
                    coupon_land_x, coupon_land_y
                )
                - seal_guard_stack,
                "nominal_channel_gap_mm": float(fixture["nominal_channel_gap_mm"]),
                "nominal_channel_velocity_m_s": float(
                    fixture["nominal_channel_velocity_m_s"]
                ),
                "mask_inserts_leave_50x50_mm_flow_field_fixed": bool(
                    fixture["mask_inserts_leave_50x50_mm_flow_field_fixed"]
                ),
                "maximum_internal_dead_volume_ml_per_side": float(
                    fixture["maximum_internal_dead_volume_ml_per_side"]
                ),
                "metal_load_plate_recommended_thickness_mm": float(
                    fixture["metal_load_plate_recommended_thickness_mm"]
                ),
                "all_polymer_load_plate_recommended_thickness_mm": float(
                    fixture["all_polymer_load_plate_recommended_thickness_mm"]
                ),
                "interpretation": (
                    "Plan-view arithmetic only. Port, bolt, seal and electrode-stack "
                    "details require a final drawing and loaded-flatness check."
                ),
            }
        ]
    )


def build_aperture_insert_frame(config: dict[str, Any]) -> pd.DataFrame:
    """Quantify area, perimeter, flow and internal inventory for each insert."""

    fixture = config["fixture_starting_point"]
    gap_mm = float(fixture["nominal_channel_gap_mm"])
    gap_cm = gap_mm / 10.0
    gap_m = gap_mm / 1000.0
    velocity = float(fixture["nominal_channel_velocity_m_s"])
    dead_edge_mm = float(config["geometry"]["edge_strip_width_mm"])
    flow_field_width_mm, flow_field_length_mm = [
        float(value) for value in fixture["maximum_active_window_mm"]
    ]
    fixed_flow_area_cm2 = flow_field_width_mm * flow_field_length_mm / 100.0
    fixed_flow_perimeter_cm = 2.0 * (
        flow_field_width_mm + flow_field_length_mm
    ) / 10.0
    fixed_flow_volume_ml = fixed_flow_area_cm2 * gap_cm
    fixed_flow_l_min = (
        velocity * flow_field_width_mm / 1000.0 * gap_m * 60.0 * 1000.0
    )
    fixed_flow_sidewall_area_cm2 = fixed_flow_perimeter_cm * gap_cm
    rows: list[dict[str, Any]] = []
    for insert in fixture["aperture_inserts_mm"]:
        width_mm = float(insert["width_mm"])
        length_mm = float(insert["flow_length_mm"])
        area_cm2 = width_mm * length_mm / 100.0
        perimeter_cm = 2.0 * (width_mm + length_mm) / 10.0
        active_volume_ml = area_cm2 * gap_cm
        actual_flow_l_min = (
            velocity * width_mm / 1000.0 * gap_m * 60.0 * 1000.0
        )
        inner_width_mm = max(width_mm - 2.0 * dead_edge_mm, 0.0)
        inner_length_mm = max(length_mm - 2.0 * dead_edge_mm, 0.0)
        live_area_fraction = inner_width_mm * inner_length_mm / (
            width_mm * length_mm
        )
        sidewall_area_cm2 = perimeter_cm * gap_cm
        nonmembrane_wetted_area_cm2 = area_cm2 + sidewall_area_cm2
        rows.append(
            {
                "aperture_id": str(insert["aperture_id"]),
                "channel_width_mm": width_mm,
                "flow_length_mm": length_mm,
                "active_area_cm2": area_cm2,
                "perimeter_cm": perimeter_cm,
                "perimeter_to_area_cm_inverse": perimeter_cm / area_cm2,
                "relative_gross_signal_vs_25_cm2": area_cm2 / 25.0,
                "nominal_gap_mm": gap_mm,
                "nominal_velocity_m_s": velocity,
                "aperture_following_channel_volume_ml_per_side": active_volume_ml,
                "aperture_following_actual_flow_l_min_per_side": actual_flow_l_min,
                "aperture_following_gas_residence_time_ms": length_mm / velocity,
                "sidewall_area_cm2_per_side": sidewall_area_cm2,
                "nonmembrane_wetted_area_cm2_per_side": nonmembrane_wetted_area_cm2,
                "nonmembrane_wetted_area_to_membrane_area": (
                    nonmembrane_wetted_area_cm2 / area_cm2
                ),
                "recommended_mask_only_fixed_flow_field": bool(
                    fixture["mask_inserts_leave_50x50_mm_flow_field_fixed"]
                ),
                "recommended_fixed_flow_field_width_mm": flow_field_width_mm,
                "recommended_fixed_flow_field_length_mm": flow_field_length_mm,
                "recommended_fixed_flow_field_volume_ml_per_side": (
                    fixed_flow_volume_ml
                ),
                "recommended_fixed_flow_field_actual_flow_l_min_per_side": (
                    fixed_flow_l_min
                ),
                "recommended_fixed_flow_field_residence_time_ms": (
                    flow_field_length_mm / velocity
                ),
                "recommended_mask_only_nonmembrane_wetted_area_cm2_per_side": (
                    fixed_flow_area_cm2
                    + fixed_flow_sidewall_area_cm2
                    + (fixed_flow_area_cm2 - area_cm2)
                ),
                "maximum_internal_dead_volume_ml_per_side": float(
                    fixture["maximum_internal_dead_volume_ml_per_side"]
                ),
                "assumed_dead_edge_strip_mm": dead_edge_mm,
                "nominal_area_loss_percent_for_dead_edge": 100.0
                * (1.0 - live_area_fraction),
                "interpretation": (
                    "Ideal rectangular active channel. Manifolds, support media, "
                    "ports and tubing are excluded and must be measured."
                ),
            }
        )
    return pd.DataFrame(rows)


def build_internal_volume_budget_frame(config: dict[str, Any]) -> pd.DataFrame:
    """Calculate a proposed swept cell-volume budget for the nominal flow field."""

    fixture = config["fixture_starting_point"]
    proposed = fixture["proposed_internal_volume_geometry"]
    width_mm, length_mm = [
        float(value) for value in fixture["maximum_active_window_mm"]
    ]
    gap_mm = float(fixture["nominal_channel_gap_mm"])
    active_volume_ml = width_mm * length_mm * gap_mm / 1000.0
    header_volume_ml = (
        float(proposed["triangular_header_count"])
        * 0.5
        * width_mm
        * float(proposed["triangular_header_length_mm"])
        * gap_mm
        / 1000.0
    )
    radius_mm = 0.5 * float(proposed["port_bore_inner_diameter_mm"])
    port_volume_ml = (
        float(proposed["port_bore_count"])
        * math.pi
        * radius_mm**2
        * float(proposed["port_bore_length_mm"])
        / 1000.0
    )
    pressure_tap_volume_ml = float(proposed["pressure_tap_volume_ml_total"])
    proposed_dead_volume_ml = (
        header_volume_ml + port_volume_ml + pressure_tap_volume_ml
    )
    total_volume_ml = active_volume_ml + proposed_dead_volume_ml
    nominal_flow_ml_s = (
        float(fixture["nominal_channel_velocity_m_s"])
        * width_mm
        / 1000.0
        * gap_mm
        / 1000.0
        * 1.0e6
    )
    return pd.DataFrame(
        [
            {
                "active_parallel_plate_volume_ml_per_side": active_volume_ml,
                "triangular_header_volume_ml_per_side": header_volume_ml,
                "port_bore_volume_ml_per_side": port_volume_ml,
                "pressure_tap_volume_ml_per_side": pressure_tap_volume_ml,
                "proposed_internal_dead_volume_ml_per_side": proposed_dead_volume_ml,
                "maximum_internal_dead_volume_ml_per_side": float(
                    fixture["maximum_internal_dead_volume_ml_per_side"]
                ),
                "proposed_total_swept_internal_volume_ml_per_side": total_volume_ml,
                "dead_volume_fraction_of_active_volume": proposed_dead_volume_ml
                / active_volume_ml,
                "nominal_total_internal_residence_time_ms": total_volume_ml
                / nominal_flow_ml_s
                * 1000.0,
                "dead_volume_target_pass": proposed_dead_volume_ml
                <= float(fixture["maximum_internal_dead_volume_ml_per_side"]),
                "interpretation": (
                    "Proposed arithmetic geometry, not an as-built volume. Fittings, "
                    "external tubing and sensor volumes are excluded and must be "
                    "reported separately."
                ),
            }
        ]
    )


def build_detectability_flow_frame(config: dict[str, Any]) -> pd.DataFrame:
    """Screen the ideal differential humidity signal over candidate gas flows."""

    state = config["operating_state"]
    screen = config["detectability_flow_screen"]
    measurement = config["measurement"]
    area_cm2 = float(screen["reference_area_cm2"])
    gap_m = float(screen["reference_gap_mm"]) / 1000.0
    width_m = math.sqrt(area_cm2 / 1.0e4)
    differential_uncertainty_pp = math.sqrt(2.0) * float(
        measurement[
            "single_stream_humidity_expanded_uncertainty_rh_percentage_points"
        ]
    )
    required_snr = float(measurement["minimum_signal_to_uncertainty_ratio"])
    rows: list[dict[str, Any]] = []
    for case, flow_l_min in itertools.product(
        screen["reference_cases"], screen["candidate_actual_flows_l_min"]
    ):
        gross_rate = gross_eo_water_mg_h(
            area_cm2,
            float(case["current_density_a_m2"]),
            float(case["water_transport_number"]),
        )
        signal = ideal_two_stream_humidity_signal(
            water_rate_mg_h=gross_rate,
            actual_flow_l_min_per_side=float(flow_l_min),
            inlet_activity=float(state["equal_inlet_water_activity"]),
            temperature_c=float(state["temperature_c"]),
            absolute_pressure_pa=float(state["absolute_pressure_pa"]),
        )
        differential_signal_pp = signal[
            "differential_signal_rh_percentage_points"
        ]
        channel_velocity = (
            float(flow_l_min) / 1000.0 / 60.0 / (width_m * gap_m)
        )
        rows.append(
            {
                "case_id": str(case["case_id"]),
                "reference_area_cm2": area_cm2,
                "reference_gap_mm": float(screen["reference_gap_mm"]),
                "water_transport_number": float(case["water_transport_number"]),
                "current_density_a_m2": float(case["current_density_a_m2"]),
                "gross_eo_water_mg_h": gross_rate,
                "actual_flow_l_min_per_side": float(flow_l_min),
                "channel_velocity_m_s": channel_velocity,
                **signal,
                "single_stream_expanded_uncertainty_rh_percentage_points": (
                    differential_uncertainty_pp / math.sqrt(2.0)
                ),
                "differential_expanded_uncertainty_rh_percentage_points": (
                    differential_uncertainty_pp
                ),
                "signal_to_expanded_uncertainty": differential_signal_pp
                / differential_uncertainty_pp,
                "passes_declared_detectability_screen": (
                    differential_signal_pp
                    >= required_snr * differential_uncertainty_pp
                ),
                "maximum_single_stream_expanded_uncertainty_for_declared_snr_rh_percentage_points": (
                    differential_signal_pp / (math.sqrt(2.0) * required_snr)
                ),
                "interpretation": str(case["interpretation"]),
            }
        )
    return pd.DataFrame(rows)


def build_detectability_limit_frame(config: dict[str, Any]) -> pd.DataFrame:
    """Solve the maximum flow that just reaches the declared ideal S/U gate."""

    state = config["operating_state"]
    screen = config["detectability_flow_screen"]
    measurement = config["measurement"]
    area_cm2 = float(screen["reference_area_cm2"])
    gap_m = float(screen["reference_gap_mm"]) / 1000.0
    width_m = math.sqrt(area_cm2 / 1.0e4)
    target_signal_pp = (
        math.sqrt(2.0)
        * float(
            measurement[
                "single_stream_humidity_expanded_uncertainty_rh_percentage_points"
            ]
        )
        * float(measurement["minimum_signal_to_uncertainty_ratio"])
    )
    rows = []
    for case in screen["reference_cases"]:
        gross_rate = gross_eo_water_mg_h(
            area_cm2,
            float(case["current_density_a_m2"]),
            float(case["water_transport_number"]),
        )
        low_flow = 1.0e-6
        high_flow = 1.0e4
        for _ in range(100):
            trial_flow = 0.5 * (low_flow + high_flow)
            trial = ideal_two_stream_humidity_signal(
                water_rate_mg_h=gross_rate,
                actual_flow_l_min_per_side=trial_flow,
                inlet_activity=float(state["equal_inlet_water_activity"]),
                temperature_c=float(state["temperature_c"]),
                absolute_pressure_pa=float(state["absolute_pressure_pa"]),
            )["differential_signal_rh_percentage_points"]
            if math.isnan(trial) or trial > target_signal_pp:
                low_flow = trial_flow
            else:
                high_flow = trial_flow
        limiting_flow = 0.5 * (low_flow + high_flow)
        rows.append(
            {
                "case_id": str(case["case_id"]),
                "reference_area_cm2": area_cm2,
                "reference_gap_mm": float(screen["reference_gap_mm"]),
                "water_transport_number": float(case["water_transport_number"]),
                "current_density_a_m2": float(case["current_density_a_m2"]),
                "gross_eo_water_mg_h": gross_rate,
                "declared_required_differential_signal_rh_percentage_points": target_signal_pp,
                "maximum_actual_flow_l_min_per_side_for_declared_detectability": limiting_flow,
                "corresponding_channel_velocity_m_s": (
                    limiting_flow / 1000.0 / 60.0 / (width_m * gap_m)
                ),
                "interpretation": (
                    "Ideal gross-signal limit only. A lower flow changes films and "
                    "does not by itself validate an intrinsic membrane rate."
                ),
            }
        )
    return pd.DataFrame(rows)


def build_minimum_detectable_area_frame(config: dict[str, Any]) -> pd.DataFrame:
    """Solve the ideal minimum active area at each declared measurement flow.

    Flow is held fixed while active membrane area is varied.  This matches the
    recommended mask-only experiment, where every insert retains the same
    50 x 50 mm gas-flow field.  The result is therefore a measurement signal
    floor, not a minimum material sample or a guarantee of net-flux detection.
    """

    state = config["operating_state"]
    screen = config["detectability_flow_screen"]
    measurement = config["measurement"]
    target_signal_pp = (
        math.sqrt(2.0)
        * float(
            measurement[
                "single_stream_humidity_expanded_uncertainty_rh_percentage_points"
            ]
        )
        * float(measurement["minimum_signal_to_uncertainty_ratio"])
    )
    available_areas = sorted(
        {
            float(row["width_mm"]) * float(row["flow_length_mm"]) / 100.0
            for row in config["fixture_starting_point"]["aperture_inserts_mm"]
        }
    )
    maximum_fixture_area_cm2 = max(available_areas)
    rows: list[dict[str, Any]] = []
    for case, flow_l_min in itertools.product(
        screen["reference_cases"], screen["candidate_actual_flows_l_min"]
    ):
        low_area_cm2 = 0.0
        high_area_cm2 = 1.0
        while high_area_cm2 < 1.0e6:
            rate = gross_eo_water_mg_h(
                high_area_cm2,
                float(case["current_density_a_m2"]),
                float(case["water_transport_number"]),
            )
            signal = ideal_two_stream_humidity_signal(
                water_rate_mg_h=rate,
                actual_flow_l_min_per_side=float(flow_l_min),
                inlet_activity=float(state["equal_inlet_water_activity"]),
                temperature_c=float(state["temperature_c"]),
                absolute_pressure_pa=float(state["absolute_pressure_pa"]),
            )["differential_signal_rh_percentage_points"]
            if math.isnan(signal) or signal >= target_signal_pp:
                break
            high_area_cm2 *= 2.0
        for _ in range(120):
            trial_area_cm2 = 0.5 * (low_area_cm2 + high_area_cm2)
            rate = gross_eo_water_mg_h(
                trial_area_cm2,
                float(case["current_density_a_m2"]),
                float(case["water_transport_number"]),
            )
            signal = ideal_two_stream_humidity_signal(
                water_rate_mg_h=rate,
                actual_flow_l_min_per_side=float(flow_l_min),
                inlet_activity=float(state["equal_inlet_water_activity"]),
                temperature_c=float(state["temperature_c"]),
                absolute_pressure_pa=float(state["absolute_pressure_pa"]),
            )["differential_signal_rh_percentage_points"]
            if math.isnan(signal) or signal >= target_signal_pp:
                high_area_cm2 = trial_area_cm2
            else:
                low_area_cm2 = trial_area_cm2
        minimum_area_cm2 = 0.5 * (low_area_cm2 + high_area_cm2)
        fitting_inserts = [area for area in available_areas if area >= minimum_area_cm2]
        rows.append(
            {
                "case_id": str(case["case_id"]),
                "water_transport_number": float(case["water_transport_number"]),
                "current_density_a_m2": float(case["current_density_a_m2"]),
                "fixed_actual_flow_l_min_per_side": float(flow_l_min),
                "declared_required_differential_signal_rh_percentage_points": target_signal_pp,
                "minimum_ideal_active_area_cm2": minimum_area_cm2,
                "equivalent_square_side_mm": math.sqrt(minimum_area_cm2 * 100.0),
                "smallest_existing_insert_that_passes_cm2": (
                    min(fitting_inserts) if fitting_inserts else math.nan
                ),
                "fits_25_cm2_fixture": minimum_area_cm2 <= maximum_fixture_area_cm2,
                "interpretation": (
                    "Ideal gross Faradaic EO signal at fixed total gas flow. "
                    "Passive diffusion, films, leakage, storage, electrode water "
                    "and blank uncertainty are excluded."
                ),
            }
        )
    return pd.DataFrame(rows)


def build_plate_deflection_frame(config: dict[str, Any]) -> pd.DataFrame:
    """Classical square-plate deflection screen for candidate load plates."""

    screen = config["structural_screen"]
    span_m = float(screen["unsupported_square_span_mm"]) / 1000.0
    allowable_bow_m = (
        float(screen["smallest_channel_gap_mm"])
        / 1000.0
        * float(screen["maximum_bow_fraction_of_smallest_gap"])
    )
    alpha = float(screen["plate_coefficient_alpha_q_a4_over_D"])
    rows = []
    for material, load in itertools.product(
        screen["materials"], screen["effective_uniform_load_cases_pa"]
    ):
        youngs_modulus_pa = float(material["youngs_modulus_gpa"]) * 1.0e9
        poisson = float(material["poisson_ratio"])
        pressure_pa = float(load["pressure_pa"])
        reference_thickness_m = float(material["reference_thickness_mm"]) / 1000.0
        flexural_rigidity = youngs_modulus_pa * reference_thickness_m**3 / (
            12.0 * (1.0 - poisson**2)
        )
        reference_deflection_m = (
            alpha * pressure_pa * span_m**4 / flexural_rigidity
        )
        required_thickness_m = (
            alpha
            * pressure_pa
            * span_m**4
            * 12.0
            * (1.0 - poisson**2)
            / (youngs_modulus_pa * allowable_bow_m)
        ) ** (1.0 / 3.0)
        rows.append(
            {
                "material_id": str(material["material_id"]),
                "youngs_modulus_gpa": float(material["youngs_modulus_gpa"]),
                "poisson_ratio": poisson,
                "unsupported_square_span_mm": span_m * 1000.0,
                "load_case": str(load["load_case"]),
                "effective_uniform_pressure_pa": pressure_pa,
                "effective_uniform_pressure_kpa": pressure_pa / 1000.0,
                "allowable_bow_um": allowable_bow_m * 1.0e6,
                "required_plate_thickness_mm_for_allowable_bow": (
                    required_thickness_m * 1000.0
                ),
                "reference_plate_thickness_mm": reference_thickness_m * 1000.0,
                "predicted_bow_um_at_reference_thickness": (
                    reference_deflection_m * 1.0e6
                ),
                "reference_thickness_passes_screen": (
                    reference_deflection_m <= allowable_bow_m
                ),
                "plate_boundary_condition": str(
                    screen["plate_boundary_condition"]
                ),
                "interpretation": str(screen["interpretation"]),
            }
        )
    return pd.DataFrame(rows)


def build_closed_cell_dimension_frame(config: dict[str, Any]) -> pd.DataFrame:
    """Gas-inventory-only pressure/RH time scales for proposed reservoirs."""

    state = config["operating_state"]
    screen = config["detectability_flow_screen"]
    volumes_l = config["geometry"]["external_closed_loop_volumes_l"]
    temperature_k = float(state["temperature_c"]) + 273.15
    saturated_molar_concentration = saturation_pressure_water_pa(
        float(state["temperature_c"])
    ) / (UNIVERSAL_GAS_CONSTANT_J_MOL_K * temperature_k)
    pressure_limit_pa = float(
        config["measurement"]["maximum_membrane_differential_pressure_pa"]
    )
    rows = []
    for case, volume_l in itertools.product(screen["reference_cases"], volumes_l):
        rate_mg_h = gross_eo_water_mg_h(
            float(screen["reference_area_cm2"]),
            float(case["current_density_a_m2"]),
            float(case["water_transport_number"]),
        )
        molar_rate_mol_s = (
            rate_mg_h
            / 1.0e6
            / WATER_MOLAR_MASS_KG_MOL
            / 3600.0
        )
        volume_m3 = float(volume_l) / 1000.0
        time_to_pressure_s = (
            pressure_limit_pa
            * volume_m3
            / (2.0 * UNIVERSAL_GAS_CONSTANT_J_MOL_K * temperature_k * molar_rate_mol_s)
        )
        time_to_one_rh_point_s = (
            volume_m3 * saturated_molar_concentration * 0.01 / molar_rate_mol_s
        )
        rows.append(
            {
                "case_id": str(case["case_id"]),
                "gross_eo_water_mg_h": rate_mg_h,
                "gas_volume_l_per_side": float(volume_l),
                "equivalent_cube_side_cm": (float(volume_l) * 1000.0)
                ** (1.0 / 3.0),
                "differential_pressure_limit_pa": pressure_limit_pa,
                "gas_only_time_to_pressure_limit_s": time_to_pressure_s,
                "gas_only_time_to_one_rh_percentage_point_per_side_min": (
                    time_to_one_rh_point_s / 60.0
                ),
                "gas_only_differential_rh_rate_percentage_points_per_min": (
                    2.0
                    * molar_rate_mol_s
                    / (volume_m3 * saturated_molar_concentration)
                    * 100.0
                    * 60.0
                ),
                "interpretation": (
                    "Rigid, isothermal, leak-free gas inventory only. Passive "
                    "back-diffusion, wall/membrane sorption, compliance and electrode "
                    "gas are omitted."
                ),
            }
        )
    return pd.DataFrame(rows)


def build_closed_loop_frame(
    config: dict[str, Any], transport: pd.DataFrame
) -> pd.DataFrame:
    state = config["operating_state"]
    measurement = config["measurement"]
    temperature_c = float(state["temperature_c"])
    drift_fraction = float(
        measurement["closed_loop_allowed_boundary_drift_rh_percentage_points"]
    ) / 100.0
    run_h = float(measurement["closed_loop_run_time_minutes"]) / 60.0
    saturated_water_density_kg_m3 = saturation_pressure_water_pa(temperature_c) / (
        WATER_VAPOUR_GAS_CONSTANT_J_KG_K * (temperature_c + 273.15)
    )
    kg_per_m3_for_drift = saturated_water_density_kg_m3 * drift_fraction

    unique = transport[
        [
            "study",
            "active_area_cm2",
            "water_transport_number",
            "current_density_a_m2",
            "total_current_ma",
            "gross_eo_water_mg_h",
        ]
    ].drop_duplicates()
    rows = []
    for row in unique.to_dict(orient="records"):
        transferred_kg = float(row["gross_eo_water_mg_h"]) * run_h / 1.0e6
        required_m3 = transferred_kg / kg_per_m3_for_drift
        rows.append(
            {
                **row,
                "allowed_rh_drift_percentage_points": drift_fraction * 100.0,
                "run_time_minutes": run_h * 60.0,
                "unbuffered_gas_volume_required_l_per_side": required_m3 * 1000.0,
                "interpretation": "Ideal gas inventory only; wall and membrane sorption make a real transient more complex.",
            }
        )
    return pd.DataFrame(rows)


def build_closed_loop_drift_time_frame(
    config: dict[str, Any], transport: pd.DataFrame
) -> pd.DataFrame:
    state = config["operating_state"]
    geometry_config = config["geometry"]
    measurement = config["measurement"]
    temperature_c = float(state["temperature_c"])
    drift_fraction = float(
        measurement["closed_loop_allowed_boundary_drift_rh_percentage_points"]
    ) / 100.0
    saturated_water_density_kg_m3 = saturation_pressure_water_pa(temperature_c) / (
        WATER_VAPOUR_GAS_CONSTANT_J_KG_K * (temperature_c + 273.15)
    )
    unique = transport[
        [
            "study",
            "active_area_cm2",
            "water_transport_number",
            "current_density_a_m2",
            "gross_eo_water_mg_h",
        ]
    ].drop_duplicates()
    rows = []
    for row, reservoir_l in itertools.product(
        unique.to_dict(orient="records"),
        geometry_config["external_closed_loop_volumes_l"],
    ):
        water_capacity_kg = (
            float(reservoir_l) / 1000.0
            * saturated_water_density_kg_m3
            * drift_fraction
        )
        rate_kg_h = float(row["gross_eo_water_mg_h"]) / 1.0e6
        rows.append(
            {
                **row,
                "closed_loop_gas_volume_l_per_side": float(reservoir_l),
                "rh_drift_percentage_points": drift_fraction * 100.0,
                "ideal_time_to_rh_drift_minutes": water_capacity_kg
                / rate_kg_h
                * 60.0,
                "interpretation": "Ideal gas inventory only; passive back-diffusion and sorption are omitted.",
            }
        )
    return pd.DataFrame(rows)


def build_membrane_time_scale_frame(config: dict[str, Any]) -> pd.DataFrame:
    screen = config["membrane_time_scale_screen"]
    thickness_m = float(screen["thickness_um"]) * 1.0e-6
    multiple = float(screen["preconditioning_multiple_of_l2_over_d"])
    rows = []
    for diffusivity in screen["water_diffusivities_m2_s"]:
        tau_s = thickness_m**2 / float(diffusivity)
        rows.append(
            {
                "membrane_thickness_um": thickness_m * 1.0e6,
                "water_diffusivity_m2_s": float(diffusivity),
                "l2_over_d_seconds": tau_s,
                "l2_over_d_hours": tau_s / 3600.0,
                "declared_preconditioning_multiple": multiple,
                "multiple_l2_over_d_hours": multiple * tau_s / 3600.0,
                "interpretation": screen["interpretation"],
            }
        )
    return pd.DataFrame(rows)


def build_boundary_mismatch_frame(config: dict[str, Any]) -> pd.DataFrame:
    screen = config["boundary_activity_mismatch_screen"]
    capacity = float(screen["water_capacity_mol_m3_activity"])
    thickness_m = float(screen["membrane_thickness_um"]) * 1.0e-6
    area_cm2 = float(screen["reference_area_cm2"])
    area_m2 = area_cm2 / 1.0e4
    transport_number = float(screen["reference_water_transport_number"])
    rows = []
    for diffusivity, mismatch_pp, current_density in itertools.product(
        screen["water_diffusivities_m2_s"],
        screen["activity_mismatch_rh_percentage_points"],
        screen["reference_current_densities_a_m2"],
    ):
        delta_activity = float(mismatch_pp) / 100.0
        molar_rate_mol_s = (
            float(diffusivity)
            * capacity
            / thickness_m
            * delta_activity
            * area_m2
        )
        passive_mg_h = (
            molar_rate_mol_s
            * WATER_MOLAR_MASS_KG_MOL
            * 3600.0
            * 1.0e6
        )
        reference_eo_mg_h = gross_eo_water_mg_h(
            area_cm2, float(current_density), transport_number
        )
        rows.append(
            {
                "water_diffusivity_m2_s": float(diffusivity),
                "water_capacity_mol_m3_activity": capacity,
                "membrane_thickness_um": thickness_m * 1.0e6,
                "activity_mismatch_rh_percentage_points": float(mismatch_pp),
                "reference_area_cm2": area_cm2,
                "linear_passive_water_rate_mg_h": passive_mg_h,
                "reference_water_transport_number": transport_number,
                "reference_current_density_a_m2": float(current_density),
                "reference_gross_eo_water_rate_mg_h": reference_eo_mg_h,
                "passive_mismatch_fraction_of_reference_gross_eo": passive_mg_h
                / reference_eo_mg_h,
                "interpretation": screen["interpretation"],
            }
        )
    return pd.DataFrame(rows)


def write_summary(
    path: Path,
    config: dict[str, Any],
    geometry: pd.DataFrame,
    transport: pd.DataFrame,
    closed_loop: pd.DataFrame,
    membrane_time_scale: pd.DataFrame,
    boundary_mismatch: pd.DataFrame,
    fixture_dimensions: pd.DataFrame,
    apertures: pd.DataFrame,
    internal_volume_budget: pd.DataFrame,
    detectability_limits: pd.DataFrame,
    minimum_detectable_area: pd.DataFrame,
    plate_deflection: pd.DataFrame,
    closed_cell_dimensions: pd.DataFrame,
) -> None:
    fixture = config["fixture_starting_point"]
    nominal = geometry[
        (geometry["active_area_cm2"] == 25.0)
        & (geometry["channel_gap_mm"] == fixture["nominal_channel_gap_mm"])
        & (geometry["channel_velocity_m_s"] == 1.0)
    ].iloc[0]
    material = transport[
        (transport["study"] == "material_coupon_screen")
        & (transport["active_area_cm2"] == 25.0)
        & (transport["channel_gap_mm"] == fixture["nominal_channel_gap_mm"])
        & (transport["channel_velocity_m_s"] == 1.0)
    ]
    low = material.loc[material["gross_eo_water_mg_h"].idxmin()]
    high = material.loc[material["gross_eo_water_mg_h"].idxmax()]
    anchor = transport[
        (transport["study"] == "inverse_design_anchor_screen")
        & (transport["active_area_cm2"] == 25.0)
        & (transport["channel_gap_mm"] == fixture["nominal_channel_gap_mm"])
        & (transport["channel_velocity_m_s"] == 1.0)
    ]
    anchor_low = anchor.loc[anchor["gross_eo_water_mg_h"].idxmin()]
    anchor_high = anchor.loc[anchor["gross_eo_water_mg_h"].idxmax()]
    closed_material = closed_loop[
        (closed_loop["study"] == "material_coupon_screen")
        & (closed_loop["active_area_cm2"] == 25.0)
    ]
    slow_tau = membrane_time_scale.loc[
        membrane_time_scale["l2_over_d_hours"].idxmax()
    ]
    mismatch_case = boundary_mismatch[
        (boundary_mismatch["water_diffusivity_m2_s"] == 1.0e-10)
        & (
            boundary_mismatch["activity_mismatch_rh_percentage_points"]
            == 0.1
        )
        & (boundary_mismatch["reference_current_density_a_m2"] == 3.0)
    ].iloc[0]
    fixture_row = fixture_dimensions.iloc[0]
    main_aperture = apertures[apertures["aperture_id"] == "square_50"].iloc[0]
    volume_row = internal_volume_budget.iloc[0]
    low_drag_limit = detectability_limits[
        detectability_limits["case_id"] == "low_drag_signal_floor"
    ].iloc[0]
    order_unity_limit = detectability_limits[
        detectability_limits["case_id"] == "order_unity_reference"
    ].iloc[0]
    minimum_area_6_l_min = minimum_detectable_area[
        minimum_detectable_area["fixed_actual_flow_l_min_per_side"] == 6.0
    ].set_index("case_id")
    high_load = plate_deflection[
        plate_deflection["load_case"] == "high_fixture_load_surrogate"
    ].set_index("material_id")
    low_drag_closed = closed_cell_dimensions[
        closed_cell_dimensions["case_id"] == "low_drag_signal_floor"
    ].set_index("gas_volume_l_per_side")
    five_ml = low_drag_closed.loc[0.005]
    five_l = low_drag_closed.loc[5.0]

    text = f"""# EO vapour coupon-cell sizing v1

## Recommended starting fixture

- Maximum active aperture: **50 x 50 mm (25 cm2)**, with masks for 30 x 30 mm and 20 x 20 mm.
- Membrane coupon: approximately **80 x 80 mm**.
- Outer fixture: approximately **110 x 110 mm**.
- Interchangeable symmetric gaps: **1, 2 and 4 mm**; use **2 mm** as the first nominal case.
- Starting structural stack: **8-10 mm insulating flow frames** plus **12 mm metal backing/load plates**. If the load-bearing plate itself is PEEK, start at **16 mm**. Accept either only after measuring loaded gap and flatness under the real gasket/bolt load.
- Use continuous, controlled gas flow for steady transport measurements. Treat a closed loop as a separate transient experiment.

The 80 mm coupon leaves {fixture_row['coupon_land_each_side_x_mm']:.0f} mm per side outside the 50 mm aperture. A 3 mm inner seal, 2 mm guarded groove and 3 mm outer seal use {fixture_row['seal_guard_stack_width_mm']:.0f} mm, leaving {fixture_row['remaining_coupon_land_after_seal_guard_stack_mm']:.0f} mm of unallocated land before the coupon edge. The outer 110 mm plate leaves a further {fixture_row['outer_fixture_land_each_side_x_mm']:.0f} mm per side for bolts and ports.

At 25 cm2, 2 mm gap and 1 m/s, each side needs {nominal['actual_flow_l_min']:.2f} actual L/min, contains {nominal['active_channel_volume_ml_per_side']:.2f} mL in the active channel, has Re about {nominal['reynolds_number']:.0f}, and the ideal straight-channel pressure drop is only {nominal['ideal_parallel_plate_pressure_drop_pa']:.1f} Pa. The exposed non-membrane surface in the ideal rectangular chamber is {main_aperture['nonmembrane_wetted_area_cm2_per_side']:.1f} cm2 per side ({main_aperture['nonmembrane_wetted_area_to_membrane_area']:.2f} times the membrane area). The proposed two tapered headers, two port bores and pressure taps add {volume_row['proposed_internal_dead_volume_ml_per_side']:.2f} mL, giving {volume_row['proposed_total_swept_internal_volume_ml_per_side']:.2f} mL total swept internal volume and {volume_row['nominal_total_internal_residence_time_ms']:.0f} ms residence at 6 L/min. The acceptance target is no more than {volume_row['maximum_internal_dead_volume_ml_per_side']:.1f} mL internal dead volume per side; measure the actual assembled volume.

The plate screen limits bow to 20 micrometres, or 2% of the 1 mm gap, across a 50 mm unsupported square. Gas pressure at 50 Pa alone requires less than 0.6 mm even for PEEK and is not the governing load. Under the deliberately conservative 1 MPa equivalent-uniform fixture-load surrogate, the calculated minimum thicknesses are {high_load.loc['PEEK', 'required_plate_thickness_mm_for_allowable_bow']:.1f} mm PEEK, {high_load.loc['Al_6061_T6', 'required_plate_thickness_mm_for_allowable_bow']:.1f} mm aluminium and {high_load.loc['316L_stainless', 'required_plate_thickness_mm_for_allowable_bow']:.1f} mm 316L. The surrogate is not a gasket-contact model; the assembled cell still needs a torque/flatness map.

## Signal envelope (gross EO only)

For order-unity transport-number scenarios, the 25 cm2 screen spans {low['gross_eo_water_mg_h']:.2f}-{high['gross_eo_water_mg_h']:.1f} mg/h over the declared current grid. The hypothetical inverse-design anchor spans {anchor_low['gross_eo_water_mg_h']:.1f}-{anchor_high['gross_eo_water_mg_h']:.1f} mg/h over its lower-current grid. These are not net-flux predictions.

With 0.1 RH-percentage-point expanded uncertainty for each humidity channel and a declared signal/uncertainty gate of five, the ideal gross-signal calculation limits flow to {low_drag_limit['maximum_actual_flow_l_min_per_side_for_declared_detectability']:.2f} L/min per side for the 5.04 mg/h low-drag floor and {order_unity_limit['maximum_actual_flow_l_min_per_side_for_declared_detectability']:.2f} L/min per side for the 16.80 mg/h order-unity reference. Both are below the 6 L/min film-characterisation baseline. Low-flow signal acquisition and high-flow film testing must therefore be separate modes unless a more sensitive or integrating water measurement is used.

At the fixed 6 L/min film-characterisation flow, the corresponding ideal minimum active areas are {minimum_area_6_l_min.loc['inverse_design_anchor', 'minimum_ideal_active_area_cm2']:.2f} cm2 for the inverse-design anchor at 1 A/m2, {minimum_area_6_l_min.loc['order_unity_reference', 'minimum_ideal_active_area_cm2']:.1f} cm2 for the order-unity reference at 10 A/m2, and {minimum_area_6_l_min.loc['low_drag_signal_floor', 'minimum_ideal_active_area_cm2']:.0f} cm2 for the low-drag reference at 10 A/m2. Thus the existing 25 cm2 fixture is comfortably large enough for the hypothetical anchor but cannot resolve the order-unity reference at 6 L/min using the declared humidity sensors alone. These are ideal gross-signal areas, not practical net-flux guarantees.

To keep an unbuffered closed-loop boundary within 1 RH percentage point for one hour, the order-unity 25 cm2 cases would require approximately {closed_material['unbuffered_gas_volume_required_l_per_side'].min():.1f}-{closed_material['unbuffered_gas_volume_required_l_per_side'].max():.0f} L of ideal gas inventory per side. This is why a shallow sealed chamber cannot represent fixed-RH steady state.

For the 5.04 mg/h gas-only reference, the 5 mL active chamber reaches 5 Pa in {five_ml['gas_only_time_to_pressure_limit_s']:.3f} s. A 5 L reservoir per side (equivalent cube side {five_l['equivalent_cube_side_cm']:.1f} cm) extends this only to {five_l['gas_only_time_to_pressure_limit_s']:.1f} s and takes {five_l['gas_only_time_to_one_rh_percentage_point_per_side_min']:.1f} min for a one-RH-percentage-point change per side. Closed operation therefore requires pressure-balancing compliance or active volume control and a transient inventory fit.

Gas residence time is not a membrane steady-state criterion. At the slowest hypothetical diffusivity in the configured screen, L2/D is {slow_tau['l2_over_d_hours']:.1f} h and the declared preconditioning screen is {slow_tau['multiple_l2_over_d_hours']:.1f} h. Use measured drift and mass-balance stability for acceptance.

Equal-RH work needs a common inlet, not merely two nominally equal sensor readings. In the configured high-diffusivity screen, a 0.1 RH-percentage-point mismatch produces {mismatch_case['linear_passive_water_rate_mg_h']:.2f} mg/h on 25 cm2, or {100.0*mismatch_case['passive_mismatch_fraction_of_reference_gross_eo']:.0f}% of the gross n=1, j=3 EO reference signal.

## Interpretation gates

1. An impermeable-foil blank must be below the allocated blank fraction before subtraction.
2. Source water loss and receiver water gain must close within the combined uncertainty.
3. Repeat at 0.5x, 1x and 2x flow and at multiple gaps; flow-dependent flux is a gas-film result, not yet an intrinsic membrane result.
4. Fit total measured rate versus aperture area and perimeter using at least three masks.
5. Hold membrane differential pressure within the declared limit and challenge it deliberately in a separate test.
6. Separate polarity-odd transport from polarity-even drift/electrode effects.

See the CSV files for the full, editable design envelope.
"""
    path.write_text(text, encoding="utf-8")


def make_plot(path: Path, transport: pd.DataFrame) -> None:
    subset = transport[
        (transport["study"] == "material_coupon_screen")
        & (transport["active_area_cm2"] == 25.0)
        & (transport["channel_gap_mm"] == 2.0)
        & (transport["channel_velocity_m_s"] == 1.0)
    ]
    fig, ax = plt.subplots(figsize=(7.0, 4.6))
    for transport_number, group in subset.groupby("water_transport_number"):
        group = group.sort_values("current_density_a_m2")
        ax.plot(
            group["current_density_a_m2"],
            group["gross_eo_water_mg_h"],
            marker="o",
            label=f"transport number = {transport_number:g}",
        )
    ax.set_xlabel("Current density (A/m2)")
    ax.set_ylabel("Gross Faradaic EO water rate (mg/h)")
    ax.set_title("25 cm2 coupon: gross signal-sizing envelope")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def make_dimension_tradeoff_plot(
    path: Path,
    detectability: pd.DataFrame,
    plate_deflection: pd.DataFrame,
    config: dict[str, Any],
) -> None:
    """Plot the two sizing decisions that cannot be read from dimensions alone."""

    required_snr = float(
        config["measurement"]["minimum_signal_to_uncertainty_ratio"]
    )
    differential_uncertainty = math.sqrt(2.0) * float(
        config["measurement"][
            "single_stream_humidity_expanded_uncertainty_rh_percentage_points"
        ]
    )
    signal_threshold = required_snr * differential_uncertainty
    labels = {
        "low_drag_signal_floor": "5.04 mg/h low-drag floor",
        "order_unity_reference": "16.80 mg/h order-unity reference",
        "inverse_design_anchor": "168.15 mg/h inverse-design anchor",
    }
    colours = {
        "low_drag_signal_floor": "#B94A3D",
        "order_unity_reference": "#008C8C",
        "inverse_design_anchor": "#17324D",
    }

    fig, axes = plt.subplots(1, 2, figsize=(11.2, 4.5))
    ax_signal, ax_plate = axes
    for case_id, group in detectability.groupby("case_id"):
        group = group.sort_values("actual_flow_l_min_per_side")
        ax_signal.plot(
            group["actual_flow_l_min_per_side"],
            group["differential_signal_rh_percentage_points"],
            marker="o",
            linewidth=2.0,
            label=labels.get(str(case_id), str(case_id)),
            color=colours.get(str(case_id)),
        )
    ax_signal.axhline(
        signal_threshold,
        color="#E58B2A",
        linestyle="--",
        linewidth=1.8,
        label=f"declared S/U = {required_snr:g} threshold",
    )
    ax_signal.axvline(6.0, color="#607284", linestyle=":", linewidth=1.5)
    ax_signal.text(
        6.15,
        ax_signal.get_ylim()[1] * 0.72,
        "6 L/min\nfilm baseline",
        color="#607284",
        fontsize=8,
    )
    ax_signal.set_xscale("log")
    ax_signal.set_yscale("log")
    ax_signal.set_xlabel("Actual flow per side (L/min)")
    ax_signal.set_ylabel("Ideal differential RH signal (percentage points)")
    ax_signal.set_title("Signal detectability versus gas flow")
    ax_signal.grid(True, which="both", alpha=0.25)
    ax_signal.legend(fontsize=7.5, loc="best")

    plate_colours = {
        "PEEK": "#B94A3D",
        "Al_6061_T6": "#008C8C",
        "316L_stainless": "#17324D",
    }
    plate_labels = {
        "PEEK": "PEEK",
        "Al_6061_T6": "Al 6061-T6",
        "316L_stainless": "316L stainless",
    }
    for material_id, group in plate_deflection.groupby("material_id"):
        group = group.sort_values("effective_uniform_pressure_kpa")
        ax_plate.plot(
            group["effective_uniform_pressure_kpa"],
            group["required_plate_thickness_mm_for_allowable_bow"],
            marker="s",
            linewidth=2.0,
            label=plate_labels.get(str(material_id), str(material_id)),
            color=plate_colours.get(str(material_id)),
        )
    ax_plate.set_xscale("log")
    ax_plate.set_yscale("log")
    ax_plate.set_xlabel("Equivalent uniform load (kPa)")
    ax_plate.set_ylabel("Required thickness for 20 µm bow (mm)")
    ax_plate.set_title("50 mm square plate-deflection screen")
    ax_plate.grid(True, which="both", alpha=0.25)
    ax_plate.legend(fontsize=8, loc="best")

    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def write_audit_and_manifest(
    *,
    output_dir: Path,
    config_path: Path,
    config: dict[str, Any],
    geometry: pd.DataFrame,
    fixture_dimensions: pd.DataFrame,
    apertures: pd.DataFrame,
    internal_volume_budget: pd.DataFrame,
    detectability_limits: pd.DataFrame,
    plate_deflection: pd.DataFrame,
    generated_paths: list[Path],
) -> None:
    """Fail closed on the fixture arithmetic and bind the generated evidence.

    The audit deliberately checks only identities and declared design gates.  It
    does not promote the screening fixture to a validated membrane test method.
    """

    fixture = fixture_dimensions.iloc[0]
    nominal_rows = geometry.loc[
        geometry["active_area_cm2"].eq(25.0)
        & geometry["channel_gap_mm"].eq(2.0)
        & geometry["channel_velocity_m_s"].eq(1.0)
    ]
    main_rows = apertures.loc[apertures["aperture_id"].eq("square_50")]
    volume = internal_volume_budget.iloc[0]
    flow_limits = detectability_limits.set_index("case_id")
    high_load = plate_deflection.loc[
        plate_deflection["load_case"].eq("high_fixture_load_surrogate")
    ]

    checks = {
        "all_declared_output_files_exist_and_nonempty": all(
            path.is_file() and path.stat().st_size > 0 for path in generated_paths
        ),
        "single_nominal_25cm2_2mm_1ms_geometry": len(nominal_rows) == 1,
        "nominal_flow_is_6_l_min_per_side": len(nominal_rows) == 1
        and math.isclose(
            float(nominal_rows.iloc[0]["actual_flow_l_min"]),
            6.0,
            rel_tol=0.0,
            abs_tol=1.0e-12,
        ),
        "fixture_seal_and_guard_stack_fits_coupon_land": float(
            fixture["remaining_coupon_land_after_seal_guard_stack_mm"]
        )
        > 0.0,
        "single_50x50mm_25cm2_primary_aperture": len(main_rows) == 1
        and math.isclose(
            float(main_rows.iloc[0]["active_area_cm2"]),
            25.0,
            rel_tol=0.0,
            abs_tol=1.0e-12,
        ),
        "proposed_internal_dead_volume_meets_declared_limit": bool(
            volume["dead_volume_target_pass"]
        ),
        "low_drag_detectability_requires_flow_below_film_baseline": float(
            flow_limits.loc[
                "low_drag_signal_floor",
                "maximum_actual_flow_l_min_per_side_for_declared_detectability",
            ]
        )
        < 6.0,
        "order_unity_detectability_requires_flow_below_film_baseline": float(
            flow_limits.loc[
                "order_unity_reference",
                "maximum_actual_flow_l_min_per_side_for_declared_detectability",
            ]
        )
        < 6.0,
        "declared_reference_plates_pass_high_load_screen": len(high_load) == len(
            config["structural_screen"]["materials"]
        )
        and bool(high_load["reference_thickness_passes_screen"].all()),
        "screen_remains_nonvalidated_and_conditional": True,
    }
    all_pass = all(checks.values())
    audit = {
        "schema_version": 1,
        "study_id": config["study_id"],
        "all_pass": all_pass,
        "checks": checks,
        "recommended_starting_fixture": {
            "maximum_active_area_cm2": 25.0,
            "maximum_active_window_mm": [50.0, 50.0],
            "membrane_coupon_mm": [80.0, 80.0],
            "outer_plate_mm": [110.0, 110.0],
            "nominal_channel_gap_mm": 2.0,
            "interchangeable_channel_gaps_mm": [1.0, 2.0, 4.0],
            "nominal_flow_l_min_per_side": 6.0,
            "insulating_flow_frame_thickness_mm": [8.0, 10.0],
            "metal_load_plate_starting_thickness_mm": 12.0,
            "all_polymer_load_plate_starting_thickness_mm": 16.0,
            "maximum_internal_dead_volume_ml_per_side": 1.3,
        },
        "claim_boundary": {
            "fixture_dimensions_are_starting_values": True,
            "gross_faradaic_transport_is_not_net_measured_transport": True,
            "plate_loads_are_sensitivity_coordinates_not_gasket_predictions": True,
            "final_acceptance_requires_blank_mass_balance_flatness_and_pressure_tests": True,
        },
    }
    write_json(output_dir / "audit.json", audit)
    if not all_pass:
        failed = [name for name, passed in checks.items() if not passed]
        raise RuntimeError(f"EO vapour-cell sizing audit failed: {failed}")

    bound_outputs = [*generated_paths, output_dir / "audit.json"]
    manifest = {
        "schema_version": 1,
        "study_id": config["study_id"],
        "sources": [
            {"path": str(config_path.resolve()), "sha256": sha256(config_path)},
            {"path": str(Path(__file__).resolve()), "sha256": sha256(Path(__file__))},
        ],
        "generated_outputs": [
            {
                "path": str(path.resolve()),
                "sha256": sha256(path),
                "size_bytes": path.stat().st_size,
            }
            for path in bound_outputs
        ],
        "verification": {
            "audit_all_pass": True,
            "manifest_self_excluded_to_avoid_recursive_hash": True,
        },
    }
    write_json(output_dir / "source_manifest.json", manifest)


def main() -> None:
    args = parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    args.output_dir.mkdir(parents=True, exist_ok=True)

    geometry = build_geometry_frame(config)
    transport = pd.concat(
        [
            pd.DataFrame(iter_transport_rows(config, key, geometry))
            for key in ("material_coupon_screen", "inverse_design_anchor_screen")
        ],
        ignore_index=True,
    )
    edge = build_edge_frame(config)
    fixture_dimensions = build_fixture_dimension_frame(config)
    apertures = build_aperture_insert_frame(config)
    internal_volume_budget = build_internal_volume_budget_frame(config)
    detectability = build_detectability_flow_frame(config)
    detectability_limits = build_detectability_limit_frame(config)
    minimum_detectable_area = build_minimum_detectable_area_frame(config)
    plate_deflection = build_plate_deflection_frame(config)
    closed_cell_dimensions = build_closed_cell_dimension_frame(config)
    closed_loop = build_closed_loop_frame(config, transport)
    drift_time = build_closed_loop_drift_time_frame(config, transport)
    membrane_time_scale = build_membrane_time_scale_frame(config)
    boundary_mismatch = build_boundary_mismatch_frame(config)

    geometry.to_csv(args.output_dir / "channel_geometry_envelope.csv", index=False)
    transport.to_csv(args.output_dir / "gross_signal_and_detectability_envelope.csv", index=False)
    edge.to_csv(args.output_dir / "aperture_edge_sensitivity.csv", index=False)
    fixture_dimensions.to_csv(
        args.output_dir / "fixture_dimension_basis.csv", index=False
    )
    apertures.to_csv(args.output_dir / "aperture_insert_dimensions.csv", index=False)
    internal_volume_budget.to_csv(
        args.output_dir / "internal_volume_budget.csv", index=False
    )
    detectability.to_csv(
        args.output_dir / "detectability_vs_flow.csv", index=False
    )
    detectability_limits.to_csv(
        args.output_dir / "detectability_flow_limits.csv", index=False
    )
    minimum_detectable_area.to_csv(
        args.output_dir / "minimum_detectable_active_area.csv", index=False
    )
    plate_deflection.to_csv(
        args.output_dir / "plate_deflection_screen.csv", index=False
    )
    closed_cell_dimensions.to_csv(
        args.output_dir / "closed_cell_dimension_screen.csv", index=False
    )
    closed_loop.to_csv(args.output_dir / "closed_loop_gas_inventory_requirement.csv", index=False)
    drift_time.to_csv(args.output_dir / "closed_loop_drift_time_by_volume.csv", index=False)
    membrane_time_scale.to_csv(
        args.output_dir / "membrane_diffusion_time_scale.csv", index=False
    )
    boundary_mismatch.to_csv(
        args.output_dir / "boundary_activity_mismatch_screen.csv", index=False
    )
    (args.output_dir / "config_used.json").write_text(
        json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    write_summary(
        args.output_dir / "SUMMARY.md",
        config,
        geometry,
        transport,
        closed_loop,
        membrane_time_scale,
        boundary_mismatch,
        fixture_dimensions,
        apertures,
        internal_volume_budget,
        detectability_limits,
        minimum_detectable_area,
        plate_deflection,
        closed_cell_dimensions,
    )
    make_plot(args.output_dir / "gross_signal_envelope_25cm2.png", transport)
    make_dimension_tradeoff_plot(
        args.output_dir / "cell_dimension_tradeoffs.png",
        detectability,
        plate_deflection,
        config,
    )
    generated_paths = [
        args.output_dir / name
        for name in (
            "channel_geometry_envelope.csv",
            "gross_signal_and_detectability_envelope.csv",
            "aperture_edge_sensitivity.csv",
            "fixture_dimension_basis.csv",
            "aperture_insert_dimensions.csv",
            "internal_volume_budget.csv",
            "detectability_vs_flow.csv",
            "detectability_flow_limits.csv",
            "minimum_detectable_active_area.csv",
            "plate_deflection_screen.csv",
            "closed_cell_dimension_screen.csv",
            "closed_loop_gas_inventory_requirement.csv",
            "closed_loop_drift_time_by_volume.csv",
            "membrane_diffusion_time_scale.csv",
            "boundary_activity_mismatch_screen.csv",
            "config_used.json",
            "SUMMARY.md",
            "gross_signal_envelope_25cm2.png",
            "cell_dimension_tradeoffs.png",
        )
    ]
    write_audit_and_manifest(
        output_dir=args.output_dir,
        config_path=args.config,
        config=config,
        geometry=geometry,
        fixture_dimensions=fixture_dimensions,
        apertures=apertures,
        internal_volume_budget=internal_volume_budget,
        detectability_limits=detectability_limits,
        plate_deflection=plate_deflection,
        generated_paths=generated_paths,
    )
    print(f"Wrote EO vapour-cell sizing study to {args.output_dir}")


if __name__ == "__main__":
    main()
