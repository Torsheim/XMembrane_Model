#!/usr/bin/env python3
"""Analyse a 20 mm bulk chamber depth for the EO vapour test cell."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from heiq.wp1.airside.properties import calculate_film_state, sherwood_parallel_plate


AIR_GAS_CONSTANT_J_KG_K = 287.05
UNIVERSAL_GAS_CONSTANT_J_MOL_K = 8.31446261815324
WATER_MOLAR_MASS_KG_MOL = 0.01801528
AIR_HEAT_CAPACITY_J_KG_K = 1005.0

GATE_NAMES_NO = {
    "gross_empty_cavity_volume_and_depth": "Bruttovolum og kammerdybde",
    "installed_component_displacement": "Fortrengning fra installerte komponenter",
    "end_wall_and_central_divider_structural_sizing": "Dimensjonering av endevegg og midtskille",
    "fluidic_and_electrical_port_interfaces": "Fluidiske og elektriske gjennomføringer",
    "internal_fan_selection_and_mounting": "Innvendig vifte og innfesting",
    "baffle_geometry_and_mounting": "Baffelgeometri og innfesting",
    "differential_pressure_management": "Differansetrykkhåndtering",
    "fixture_mounting_fastener_pattern_and_preload": "Boltmønster og forspenning",
    "seal_geometry_and_compression": "Tetningsgeometri og kompresjon",
    "drawing_datums_and_dimensional_tolerances": "Datumer og måltoleranser",
    "loaded_flatness_and_gap_uniformity": "Planhet og gap under last",
    "internal_mixing_time": "Intern blandetid",
    "net_volume_calibration": "Kalibrering av nettovolum",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Screen a 20 mm bulk chamber depth and fabrication choices."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "config" / "eo_vapor_test_cell_20mm_channel_study.json",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "reports" / "test_cell_20mm_channel_study_2026-09-04",
    )
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_release_checksums(release_dir: Path) -> dict[str, Any]:
    """Verify every entry in a release-local SHA256SUMS file."""
    checksum_path = release_dir / "SHA256SUMS"
    failures: list[str] = []
    checked = 0
    try:
        display_path = release_dir.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        display_path = release_dir.resolve().as_posix()
    if not checksum_path.is_file():
        return {
            "path": display_path,
            "checksum_file": "SHA256SUMS",
            "entries_checked": 0,
            "all_pass": False,
            "failures": ["missing SHA256SUMS"],
        }

    release_root = release_dir.resolve()
    for line_number, raw_line in enumerate(
        checksum_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not raw_line.strip():
            continue
        parts = raw_line.split(maxsplit=1)
        if len(parts) != 2 or len(parts[0]) != 64:
            failures.append(f"line {line_number}: malformed checksum entry")
            continue
        expected, relative_text = parts
        relative_text = relative_text.lstrip("*")
        candidate = (release_dir / relative_text).resolve()
        if candidate != release_root and release_root not in candidate.parents:
            failures.append(f"line {line_number}: path escapes release directory")
            continue
        checked += 1
        if not candidate.is_file():
            failures.append(f"{relative_text}: missing")
        elif sha256(candidate) != expected.lower():
            failures.append(f"{relative_text}: checksum mismatch")

    return {
        "path": display_path,
        "checksum_file": "SHA256SUMS",
        "entries_checked": checked,
        "all_pass": checked > 0 and not failures,
        "failures": failures,
    }


def load_base_model(path: Path):
    spec = importlib.util.spec_from_file_location("eo_test_cell_base_model", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load base model: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rectangular_volume_ml(width_mm: float, height_mm: float, depth_mm: float) -> float:
    if min(width_mm, height_mm, depth_mm) <= 0.0:
        raise ValueError("Cavity dimensions must be positive")
    return width_mm * height_mm * depth_mm / 1000.0


def square_side_mm_for_volume(
    volume_ml: float, depth_mm: float, displacement_ml: float = 0.0
) -> float:
    if volume_ml <= 0.0 or depth_mm <= 0.0 or displacement_ml < 0.0:
        raise ValueError("Volume and depth must be positive and displacement non-negative")
    return math.sqrt((volume_ml + displacement_ml) * 1000.0 / depth_mm)


def simply_supported_square_stress_coefficient(
    poisson_ratio: float, maximum_odd_index: int
) -> float:
    """Return the Navier-series centre surface-stress coefficient."""
    if not -1.0 < poisson_ratio < 0.5:
        raise ValueError("Poisson ratio is outside the isotropic elastic range")
    if maximum_odd_index < 1 or maximum_odd_index % 2 == 0:
        raise ValueError("Navier-series maximum index must be a positive odd integer")
    series_sum = 0.0
    for m in range(1, maximum_odd_index + 1, 2):
        for n in range(1, maximum_odd_index + 1, 2):
            sign = math.sin(m * math.pi / 2.0) * math.sin(n * math.pi / 2.0)
            series_sum += (
                sign
                * (m**2 + poisson_ratio * n**2)
                / (m * n * (m**2 + n**2) ** 2)
            )
    return 96.0 * series_sum / math.pi**4


def component_displacement_bound_ml(study: dict[str, Any]) -> float:
    items = study["geometry"]["component_displacement_upper_bound_ml_per_side"]
    values = [float(value) for value in items.values()]
    if any(value < 0.0 for value in values):
        raise ValueError("Component displacement bounds must be non-negative")
    return sum(values)


def validate_study_config(study: dict[str, Any], base: dict[str, Any]) -> None:
    if int(study["schema_version"]) != 1:
        raise ValueError("Only 20 mm study schema version 1 is supported")
    interpretation = study["interpretation"]
    membrane = study["membrane_constraint"]
    if not math.isclose(
        float(interpretation["requested_channel_depth_mm"]), 20.0, abs_tol=1e-12
    ):
        raise ValueError("This study is specifically bound to a 20 mm bulk depth")
    nominal_gap = float(
        base["integrated_sealed_cell"]["membrane_region"]["nominal_gap_mm"]
    )
    if not math.isclose(
        float(membrane["local_gap_remains_mm"]),
        nominal_gap,
        abs_tol=1e-12,
    ):
        raise ValueError("The bulk-depth study must preserve the base local membrane gap")
    region = base["integrated_sealed_cell"]["membrane_region"]
    base_width_mm = float(region["width_mm"])
    base_height_mm = float(region["height_mm"])
    declared_width_mm = float(membrane["active_width_mm"])
    declared_height_mm = float(membrane["active_height_mm"])
    declared_area_cm2 = float(membrane["active_area_cm2"])
    base_coupon_mm = [
        float(value)
        for value in base["integrated_sealed_cell"]["mechanical_starting_values"][
            "membrane_coupon_mm"
        ]
    ]
    declared_coupon_mm = [float(value) for value in membrane["coupon_dimensions_mm"]]
    if not (
        math.isclose(declared_width_mm, base_width_mm, abs_tol=1e-12)
        and math.isclose(declared_height_mm, base_height_mm, abs_tol=1e-12)
        and math.isclose(
            declared_area_cm2,
            base_width_mm * base_height_mm / 100.0,
            abs_tol=1e-12,
        )
        and math.isclose(declared_area_cm2, 25.0, abs_tol=1e-12)
        and declared_coupon_mm == base_coupon_mm
    ):
        raise ValueError(
            "The study must preserve the 50 x 50 mm (25 cm2) active window "
            "and 80 x 80 mm coupon"
        )
    target = float(study["geometry"]["target_net_free_gas_volume_ml_per_side"])
    base_target = float(
        base["integrated_sealed_cell"]["volume_sizing_basis"][
            "selected_net_free_gas_volume_ml_per_side"
        ]
    )
    if not math.isclose(target, base_target, abs_tol=1e-12):
        raise ValueError("The 20 mm study must preserve the governing 500 mL target")
    if len(study["sources"]) < 5:
        raise ValueError("Engineering choices require traceable primary sources")
    if any(not str(row.get("url", "")).startswith("https://") for row in study["sources"]):
        raise ValueError("Every engineering source requires an HTTPS URL")
    fan = study["flow_and_instrumentation_screen"]["fan"]
    if float(fan["typical_power_w"]) <= 0.0 or float(fan["maximum_power_w"]) < float(
        fan["typical_power_w"]
    ):
        raise ValueError("Fan maximum power must be positive and at least typical power")
    if float(fan["maximum_static_pressure_pa"]) <= 0.0:
        raise ValueError("Fan maximum static pressure must be positive")


def base_quantities(base: dict[str, Any], model: Any) -> dict[str, float]:
    model.validate_config(base)
    cell = base["integrated_sealed_cell"]
    state = base["operating_state"]
    basis = cell["volume_sizing_basis"]
    region = cell["membrane_region"]
    membrane_width_mm = float(region["width_mm"])
    membrane_height_mm = float(region["height_mm"])
    membrane_area_m2 = float(model.membrane_area_m2(base))
    target_volume_ml = float(basis["selected_net_free_gas_volume_ml_per_side"])
    rate_mg_s = float(model.integrated_target_water_rate_mg_s(base))
    segment_s = float(basis["half_cycle_duration_s"])
    transferred_mg = rate_mg_s * segment_s
    temperature_k = float(state["temperature_c"]) + 273.15
    transferred_moles = transferred_mg / 1.0e6 / WATER_MOLAR_MASS_KG_MOL
    return {
        "temperature_c": float(state["temperature_c"]),
        "temperature_k": temperature_k,
        "absolute_pressure_pa": float(state["absolute_pressure_pa"]),
        "initial_rh_percent": float(state["initial_relative_humidity_percent"]),
        "target_volume_ml": target_volume_ml,
        "required_volume_ml": float(model.required_net_volume_ml_per_side(base)),
        "target_flux_g_m2_h": float(basis["target_net_water_flux_g_m2_h"]),
        "active_membrane_width_mm": membrane_width_mm,
        "active_membrane_height_mm": membrane_height_mm,
        "active_membrane_area_m2": membrane_area_m2,
        "active_membrane_area_cm2": membrane_area_m2 * 1.0e4,
        "allowed_rh_change_pp": float(
            basis["maximum_single_chamber_rh_change_percentage_points"]
        ),
        "segment_duration_s": segment_s,
        "rate_mg_s": rate_mg_s,
        "transferred_mg": transferred_mg,
        "transferred_moles": transferred_moles,
        "saturated_density_kg_m3": float(
            model.saturated_water_vapour_density_kg_m3(
                float(state["temperature_c"])
            )
        ),
    }


def response_at_volume(volume_ml: float, quantities: dict[str, float]) -> dict[str, float]:
    if volume_ml <= 0.0:
        raise ValueError("Net gas volume must be positive")
    volume_m3 = volume_ml / 1.0e6
    drift_pp = (
        quantities["transferred_mg"]
        / 1.0e6
        / (quantities["saturated_density_kg_m3"] * volume_m3)
        * 100.0
    )
    pressure_pa = (
        2.0
        * quantities["transferred_moles"]
        * UNIVERSAL_GAS_CONSTANT_J_MOL_K
        * quantities["temperature_k"]
        / volume_m3
    )
    maximum_segment_s = (
        quantities["segment_duration_s"]
        * quantities["allowed_rh_change_pp"]
        / drift_pp
    )
    return {
        "single_chamber_rh_change_pp": drift_pp,
        "chamber_A_rh_after_segment_percent": quantities["initial_rh_percent"]
        - drift_pp,
        "chamber_B_rh_after_segment_percent": quantities["initial_rh_percent"]
        + drift_pp,
        "chamber_differential_rh_pp": 2.0 * drift_pp,
        "rigid_chamber_differential_pressure_pa": pressure_pa,
        "maximum_segment_duration_for_rh_limit_s": maximum_segment_s,
        "minimum_switching_frequency_for_rh_limit_hz": 0.5 / maximum_segment_s,
        "maximum_flux_for_rh_limit_g_m2_h": quantities["target_flux_g_m2_h"]
        * quantities["allowed_rh_change_pp"]
        / drift_pp,
    }


def scenario_row(
    scenario_id: str,
    width_mm: float,
    height_mm: float,
    depth_mm: float,
    displacement_ml: float,
    trim_insert_ml: float,
    quantities: dict[str, float],
    note: str,
) -> dict[str, Any]:
    gross_ml = rectangular_volume_ml(width_mm, height_mm, depth_mm)
    net_ml = gross_ml - displacement_ml - trim_insert_ml
    response = response_at_volume(net_ml, quantities)
    return {
        "scenario_id": scenario_id,
        "bulk_cavity_width_mm": width_mm,
        "bulk_cavity_height_mm": height_mm,
        "active_membrane_area_cm2": quantities["active_membrane_area_cm2"],
        "integrated_water_rate_mg_s": quantities["rate_mg_s"],
        "bulk_depth_mm": depth_mm,
        "gross_empty_cavity_volume_ml_per_side": gross_ml,
        "assumed_component_displacement_ml_per_side": displacement_ml,
        "nominal_trim_insert_ml_per_side": trim_insert_ml,
        "resulting_net_gas_volume_ml_per_side": net_ml,
        "required_minimum_net_volume_ml_per_side": quantities["required_volume_ml"],
        "target_net_volume_ml_per_side": quantities["target_volume_ml"],
        "meets_rh_volume_minimum": net_ml >= quantities["required_volume_ml"],
        "within_500ml_calibration_band": abs(net_ml - quantities["target_volume_ml"])
        <= 5.0,
        **response,
        "note": note,
    }


def build_scenario_frame(
    study: dict[str, Any], quantities: dict[str, float]
) -> pd.DataFrame:
    geometry = study["geometry"]
    depth_mm = float(study["interpretation"]["requested_channel_depth_mm"])
    existing_w, existing_h = [
        float(value) for value in geometry["existing_bulk_cavity_footprint_mm"]
    ]
    recommended_w, recommended_h = [
        float(value)
        for value in geometry["recommended_bulk_cavity_footprint_mm"]
    ]
    displacement_ml = component_displacement_bound_ml(study)
    recommended_gross_ml = rectangular_volume_ml(
        recommended_w, recommended_h, depth_mm
    )
    recommended_pretrim_ml = recommended_gross_ml - displacement_ml
    trim_ml = recommended_pretrim_ml - quantities["target_volume_ml"]
    return pd.DataFrame(
        [
            scenario_row(
                "100x100x20_geometry_only",
                existing_w,
                existing_h,
                depth_mm,
                0.0,
                0.0,
                quantities,
                "Literal geometry; optimistic upper bound before any hardware is installed.",
            ),
            scenario_row(
                "100x100x20_with_conservative_component_bound",
                existing_w,
                existing_h,
                depth_mm,
                displacement_ml,
                0.0,
                quantities,
                "Uses full bounding volumes as a conservative displacement screen.",
            ),
            scenario_row(
                "165x165x20_before_calibration_trim",
                recommended_w,
                recommended_h,
                depth_mm,
                displacement_ml,
                0.0,
                quantities,
                "Recommended shallow cavity before removable calibration inserts.",
            ),
            scenario_row(
                "165x165x20_calibrated_to_500ml",
                recommended_w,
                recommended_h,
                depth_mm,
                displacement_ml,
                trim_ml,
                quantities,
                "Recommended geometry with nominal trim; final value still requires measurement.",
            ),
        ]
    )


def build_geometry_sweep_frame(
    study: dict[str, Any], quantities: dict[str, float]
) -> pd.DataFrame:
    depth_mm = float(study["interpretation"]["requested_channel_depth_mm"])
    displacement_ml = component_displacement_bound_ml(study)
    rows: list[dict[str, Any]] = []
    for side_mm in range(90, 181):
        gross_ml = rectangular_volume_ml(float(side_mm), float(side_mm), depth_mm)
        net_ml = gross_ml - displacement_ml
        if net_ml <= 0.0:
            continue
        response = response_at_volume(net_ml, quantities)
        rows.append(
            {
                "square_bulk_cavity_footprint_side_mm": float(side_mm),
                "active_membrane_area_cm2": quantities["active_membrane_area_cm2"],
                "bulk_depth_mm": depth_mm,
                "gross_volume_ml_per_side": gross_ml,
                "component_displacement_bound_ml_per_side": displacement_ml,
                "net_volume_before_trim_ml_per_side": net_ml,
                "single_chamber_rh_change_pp": response[
                    "single_chamber_rh_change_pp"
                ],
                "meets_rh_volume_minimum": net_ml >= quantities["required_volume_ml"],
                "meets_500ml_target_before_trim": net_ml >= quantities["target_volume_ml"],
            }
        )
    return pd.DataFrame(rows)


def build_local_gap_interpretation_frame(
    study: dict[str, Any], base: dict[str, Any]
) -> pd.DataFrame:
    cell = base["integrated_sealed_cell"]
    state = base["operating_state"]
    region = cell["membrane_region"]
    mechanical = cell["mechanical_starting_values"]
    header = cell["interconnect_header_port_budget"]
    proposed_port = study["flow_and_instrumentation_screen"]["ports"]
    width_mm = float(region["width_mm"])
    height_mm = float(region["height_mm"])
    target_ml = float(
        cell["volume_sizing_basis"]["selected_net_free_gas_volume_ml_per_side"]
    )
    maximum_budget_ml = float(header["maximum_volume_ml_per_side"])
    rows: list[dict[str, Any]] = []
    for gap_mm in (float(region["nominal_gap_mm"]), 20.0):
        local_ml = width_mm * height_mm * gap_mm / 1000.0
        header_ml = (
            float(header["triangular_header_count_per_side"])
            * 0.5
            * width_mm
            * float(header["triangular_header_length_mm"])
            * gap_mm
            / 1000.0
        )
        current_radius_mm = 0.5 * float(mechanical["port_bore_inner_diameter_mm"])
        proposed_radius_mm = 0.5 * float(proposed_port["bore_inner_diameter_mm"])
        count = float(proposed_port["count_per_side"])
        length_mm = float(proposed_port["screened_wall_bore_length_mm"])
        current_port_ml = count * math.pi * current_radius_mm**2 * length_mm / 1000.0
        proposed_port_ml = count * math.pi * proposed_radius_mm**2 * length_mm / 1000.0
        tap_ml = float(header["pressure_tap_volume_ml_per_side"])
        film = calculate_film_state(
            side="both",
            temperature_c=float(state["temperature_c"]),
            velocity_m_s=1.0,
            gap_m=gap_mm / 1000.0,
            pressure_pa=float(state["absolute_pressure_pa"]),
            scale_factor=1.0,
        )
        gap_m = gap_mm / 1000.0
        width_m = width_mm / 1000.0
        rectangular_hydraulic_diameter_m = (
            2.0 * width_m * gap_m / (width_m + gap_m)
        )
        rectangular_reynolds = (
            film.reynolds_number
            * rectangular_hydraulic_diameter_m
            / film.hydraulic_diameter_m
        )
        rectangular_sherwood, rectangular_regime = sherwood_parallel_plate(
            rectangular_reynolds, film.schmidt_number
        )
        rectangular_film_coefficient = (
            rectangular_sherwood
            * film.vapour_diffusivity_air_m2_s
            / rectangular_hydraulic_diameter_m
        )
        rows.append(
            {
                "interpretation": "selected_local_gap" if gap_mm == float(region["nominal_gap_mm"]) else "alternate_20mm_local_gap",
                "local_gap_mm": gap_mm,
                "local_membrane_region_volume_ml_per_side": local_ml,
                "remaining_bulk_volume_at_500ml_ml_per_side": target_ml - local_ml,
                "channel_flow_at_1m_s_l_min": width_mm
                / 1000.0
                * gap_mm
                / 1000.0
                * 1.0
                * 60_000.0,
                "channel_aspect_ratio_width_to_gap": width_mm / gap_mm,
                "rectangular_hydraulic_diameter_m": rectangular_hydraulic_diameter_m,
                "reynolds_number": rectangular_reynolds,
                "sherwood_number": rectangular_sherwood,
                "gas_film_mass_transfer_coefficient_m_s": rectangular_film_coefficient,
                "correlation_regime": rectangular_regime,
                "correlation_boundary": "Hydraulic-diameter screen using the legacy fully developed parallel-plate Sherwood relation; the one-active-wall boundary condition and low aspect ratio require separate validation.",
                "legacy_parallel_plate_hydraulic_diameter_m": film.hydraulic_diameter_m,
                "legacy_parallel_plate_reynolds_number": film.reynolds_number,
                "legacy_parallel_plate_film_coefficient_m_s": film.gas_mass_transfer_coefficient_m_s,
                "header_volume_ml_per_side": header_ml,
                "header_plus_current_6mm_ports_ml_per_side": header_ml
                + current_port_ml
                + tap_ml,
                "header_plus_proposed_4mm_wall_bore_screen_ml_per_side": header_ml
                + proposed_port_ml
                + tap_ml,
                "maximum_interconnect_budget_ml_per_side": maximum_budget_ml,
                "proposed_4mm_wall_bore_screen_budget_pass": header_ml
                + proposed_port_ml
                + tap_ml
                <= maximum_budget_ml,
            }
        )
    return pd.DataFrame(rows)


def build_plate_pressure_screen_frame(study: dict[str, Any]) -> pd.DataFrame:
    screen = study["mechanical_screen"]
    side_mm = float(
        study["geometry"]["recommended_bulk_cavity_footprint_mm"][0]
    )
    side_m = side_mm / 1000.0
    pressure_pa = float(screen["proof_differential_pressure_pa"])
    model = screen["plate_model"]
    maximum_odd_index = int(model["stress_series_max_odd_index"])
    rows: list[dict[str, Any]] = []
    for key in ("aluminium_load_plate", "peek_insulating_plate"):
        item = screen[key]
        thickness_m = float(item["thickness_mm"]) / 1000.0
        elastic_modulus_pa = float(item["elastic_modulus_gpa"]) * 1.0e9
        poisson = float(item["poisson_ratio"])
        rigidity_nm = elastic_modulus_pa * thickness_m**3 / (
            12.0 * (1.0 - poisson**2)
        )
        stress_coefficient = simply_supported_square_stress_coefficient(
            poisson, maximum_odd_index
        )
        deflection_m = (
            float(model["deflection_coefficient"])
            * pressure_pa
            * side_m**4
            / rigidity_nm
        )
        stress_pa = (
            stress_coefficient
            * pressure_pa
            * side_m**2
            / thickness_m**2
        )
        rows.append(
            {
                "component": key,
                "material": item["material"],
                "bulk_cavity_clear_span_mm": side_mm,
                "thickness_mm": float(item["thickness_mm"]),
                "proof_differential_pressure_pa": pressure_pa,
                "flexural_rigidity_nm": rigidity_nm,
                "pressure_only_maximum_deflection_um": deflection_m * 1.0e6,
                "pressure_only_maximum_bending_stress_mpa": stress_pa / 1.0e6,
                "navier_centre_stress_coefficient": stress_coefficient,
                "navier_maximum_odd_index": maximum_odd_index,
                "model_boundary": model["boundary_condition"],
                "release_use": "Screen only; seal preload, fastener loads and creep remain unmodelled.",
            }
        )
    return pd.DataFrame(rows)


def build_decision_summary(
    study: dict[str, Any], quantities: dict[str, float], scenarios: pd.DataFrame
) -> dict[str, Any]:
    geometry = study["geometry"]
    screen = study["mechanical_screen"]
    flow = study["flow_and_instrumentation_screen"]
    depth_mm = float(study["interpretation"]["requested_channel_depth_mm"])
    displacement_ml = component_displacement_bound_ml(study)
    target_ml = quantities["target_volume_ml"]
    required_ml = quantities["required_volume_ml"]
    recommended = scenarios.set_index("scenario_id").loc[
        "165x165x20_before_calibration_trim"
    ]
    literal = scenarios.set_index("scenario_id").loc["100x100x20_geometry_only"]
    compact_bounded = scenarios.set_index("scenario_id").loc[
        "100x100x20_with_conservative_component_bound"
    ]
    minimum_side_target_no_hardware = square_side_mm_for_volume(target_ml, depth_mm)
    minimum_side_target_with_bound = square_side_mm_for_volume(
        target_ml, depth_mm, displacement_ml
    )
    minimum_side_rh_with_bound = square_side_mm_for_volume(
        required_ml, depth_mm, displacement_ml
    )
    required_depth_existing_with_bound = (
        (target_ml + displacement_ml)
        * 1000.0
        / (
            float(geometry["existing_bulk_cavity_footprint_mm"][0])
            * float(geometry["existing_bulk_cavity_footprint_mm"][1])
        )
    )

    target_volume_m3 = target_ml / 1.0e6
    transferred_moles = quantities["transferred_moles"]
    p0 = quantities["absolute_pressure_pa"]
    target_dp = float(study["pressure_management"]["target_differential_pressure_pa"])
    half_target_dp = 0.5 * target_dp
    nrt = (
        transferred_moles
        * UNIVERSAL_GAS_CONSTANT_J_MOL_K
        * quantities["temperature_k"]
    )
    high_volume_m3 = (p0 * target_volume_m3 + nrt) / (p0 + half_target_dp)
    low_volume_m3 = (p0 * target_volume_m3 - nrt) / (p0 - half_target_dp)
    diaphragm_travel_ul = max(
        abs(high_volume_m3 - target_volume_m3),
        abs(low_volume_m3 - target_volume_m3),
    ) * 1.0e9
    diaphragm_full_stroke_ul = (high_volume_m3 - low_volume_m3) * 1.0e9
    rigid_single_side_pressure_pa = nrt / target_volume_m3
    external_reference_compliance_nl_pa = (
        diaphragm_travel_ul * 1000.0 / half_target_dp
    )
    double_acting_compliance_nl_pa = diaphragm_travel_ul * 1000.0 / target_dp

    proof_pressure_pa = float(screen["proof_differential_pressure_pa"])
    recommended_side_m = (
        float(geometry["recommended_bulk_cavity_footprint_mm"][0]) / 1000.0
    )
    pressure_separation_force_n = proof_pressure_pa * recommended_side_m**2
    fasteners = screen["fasteners"]
    nominal_preload_n_each = float(fasteners["nominal_torque_nm_each"]) / (
        float(fasteners["nut_factor"])
        * float(fasteners["nominal_diameter_mm"])
        / 1000.0
    )
    fastener_count = int(fasteners["count"])

    seal = screen["seal"]
    seal_cross_section_mm = float(seal["o_ring_cross_section_mm"])
    seal_groove_depth_mm = seal_cross_section_mm * (
        1.0 - float(seal["target_squeeze_fraction"])
    )
    seal_area_mm2 = math.pi * (0.5 * seal_cross_section_mm) ** 2
    minimum_groove_width_mm = seal_area_mm2 / (
        float(seal["maximum_gland_fill_fraction"]) * seal_groove_depth_mm
    )
    actual_gland_fill = seal_area_mm2 / (
        float(seal["recommended_groove_width_mm"]) * seal_groove_depth_mm
    )
    minimum_effective_gland_depth_mm = float(
        seal["screened_minimum_effective_gland_depth_mm"]
    )
    depth_only_worst_gland_fill = seal_area_mm2 / (
        float(seal["recommended_groove_width_mm"])
        * minimum_effective_gland_depth_mm
    )
    maximum_screened_squeeze_fraction = (
        1.0 - minimum_effective_gland_depth_mm / seal_cross_section_mm
    )

    ports = flow["ports"]
    port_volume_ml = (
        float(ports["count_per_side"])
        * math.pi
        * (0.5 * float(ports["bore_inner_diameter_mm"])) ** 2
        * float(ports["screened_wall_bore_length_mm"])
        / 1000.0
    )
    base_cell = read_json(ROOT / study["base_config"])["integrated_sealed_cell"]
    header = base_cell["interconnect_header_port_budget"]
    region = base_cell["membrane_region"]
    header_volume_ml = (
        float(header["triangular_header_count_per_side"])
        * 0.5
        * float(region["width_mm"])
        * float(header["triangular_header_length_mm"])
        * float(region["nominal_gap_mm"])
        / 1000.0
    )
    interconnect_volume_ml = (
        header_volume_ml
        + port_volume_ml
        + float(header["pressure_tap_volume_ml_per_side"])
    )
    interconnect_budget_ml = float(header["maximum_volume_ml_per_side"])

    fan = flow["fan"]
    airflow_l_s = float(fan["maximum_airflow_m3_h"]) * 1000.0 / 3600.0
    ideal_turnover_s = target_ml / 1000.0 / airflow_l_s
    conservative_turnover_s = ideal_turnover_s / float(
        fan["minimum_effective_flow_fraction_for_screen"]
    )
    air_density_kg_m3 = p0 / (
        AIR_GAS_CONSTANT_J_KG_K * quantities["temperature_k"]
    )
    typical_adiabatic_fan_rise_k = (
        float(fan["typical_power_w"])
        * quantities["segment_duration_s"]
        / (air_density_kg_m3 * target_volume_m3 * AIR_HEAT_CAPACITY_J_KG_K)
    )
    maximum_adiabatic_fan_rise_k = (
        float(fan["maximum_power_w"])
        * quantities["segment_duration_s"]
        / (air_density_kg_m3 * target_volume_m3 * AIR_HEAT_CAPACITY_J_KG_K)
    )

    pretrim_net_ml = float(recommended["resulting_net_gas_volume_ml_per_side"])
    gross_recommended_ml = rectangular_volume_ml(
        float(geometry["recommended_bulk_cavity_footprint_mm"][0]),
        float(geometry["recommended_bulk_cavity_footprint_mm"][1]),
        depth_mm,
    )
    recommended_footprint_area_cm2 = (
        float(geometry["recommended_bulk_cavity_footprint_mm"][0])
        * float(geometry["recommended_bulk_cavity_footprint_mm"][1])
        / 100.0
    )
    footprint_to_membrane_area_ratio = (
        recommended_footprint_area_cm2 / quantities["active_membrane_area_cm2"]
    )
    return {
        "study_id": study["study_id"],
        "selected_interpretation": study["interpretation"]["meaning"],
        "membrane_area_invariant": {
            "active_window_mm": [
                quantities["active_membrane_width_mm"],
                quantities["active_membrane_height_mm"],
            ],
            "active_area_cm2": quantities["active_membrane_area_cm2"],
            "coupon_dimensions_mm": study["membrane_constraint"][
                "coupon_dimensions_mm"
            ],
            "target_flux_g_m2_h": quantities["target_flux_g_m2_h"],
            "integrated_water_rate_mg_s": quantities["rate_mg_s"],
            "water_transferred_per_5s_segment_mg": quantities["transferred_mg"],
            "recommended_bulk_footprint_area_cm2_not_active": recommended_footprint_area_cm2,
            "bulk_footprint_to_active_membrane_area_ratio": footprint_to_membrane_area_ratio,
            "bulk_footprint_used_as_transport_area": False,
            "if_bulk_footprint_were_incorrectly_used_as_active": {
                "active_area_cm2": recommended_footprint_area_cm2,
                "integrated_water_rate_mg_s": quantities["rate_mg_s"]
                * footprint_to_membrane_area_ratio,
                "water_transferred_per_5s_segment_mg": quantities["transferred_mg"]
                * footprint_to_membrane_area_ratio,
                "required_volume_for_5pp_ml": quantities["required_volume_ml"]
                * footprint_to_membrane_area_ratio,
                "rigid_pressure_difference_at_500ml_pa": response_at_volume(
                    target_ml, quantities
                )["rigid_chamber_differential_pressure_pa"]
                * footprint_to_membrane_area_ratio,
                "status": "FORBIDDEN MISINTERPRETATION",
            },
        },
        "literal_100mm_case": {
            "gross_volume_ml_per_side": float(
                literal["gross_empty_cavity_volume_ml_per_side"]
            ),
            "rh_change_pp_per_chamber": float(literal["single_chamber_rh_change_pp"]),
            "pressure_difference_pa": float(
                literal["rigid_chamber_differential_pressure_pa"]
            ),
            "maximum_segment_duration_s": float(
                literal["maximum_segment_duration_for_rh_limit_s"]
            ),
            "minimum_switching_frequency_hz": float(
                literal["minimum_switching_frequency_for_rh_limit_hz"]
            ),
            "maximum_flux_g_m2_h": float(
                literal["maximum_flux_for_rh_limit_g_m2_h"]
            ),
            "passes_original_5s_rh_criterion": bool(
                literal["meets_rh_volume_minimum"]
            ),
        },
        "recommended_geometry": {
            "bulk_cavity_footprint_mm": geometry[
                "recommended_bulk_cavity_footprint_mm"
            ],
            "active_membrane_window_mm": [
                quantities["active_membrane_width_mm"],
                quantities["active_membrane_height_mm"],
            ],
            "active_membrane_area_cm2": quantities["active_membrane_area_cm2"],
            "membrane_coupon_mm": study["membrane_constraint"][
                "coupon_dimensions_mm"
            ],
            "integrated_water_rate_mg_s_at_target_flux": quantities["rate_mg_s"],
            "water_transferred_per_5s_segment_mg": quantities["transferred_mg"],
            "bulk_depth_mm": depth_mm,
            "outer_plate_face_mm": geometry["recommended_outer_plate_face_mm"],
            "gross_volume_ml_per_side": gross_recommended_ml,
            "component_displacement_upper_bound_ml_per_side": displacement_ml,
            "pretrim_net_volume_ml_per_side": pretrim_net_ml,
            "nominal_removable_trim_insert_ml_per_side": pretrim_net_ml - target_ml,
            "required_trim_range_for_zero_to_bounded_component_displacement_ml_per_side": [
                pretrim_net_ml - target_ml,
                gross_recommended_ml - target_ml,
            ],
            "minimum_available_trim_capacity_ml_per_side": gross_recommended_ml
            - target_ml,
            "final_acceptance_requires_measured_net_volume_ml": target_ml,
            "final_acceptance_tolerance_ml": 5.0,
        },
        "geometry_thresholds": {
            "minimum_square_side_for_500ml_without_hardware_mm": minimum_side_target_no_hardware,
            "minimum_square_side_for_500ml_with_displacement_bound_mm": minimum_side_target_with_bound,
            "minimum_square_side_for_rh_limit_with_displacement_bound_mm": minimum_side_rh_with_bound,
            "required_depth_at_100mm_bulk_footprint_with_displacement_bound_mm": required_depth_existing_with_bound,
        },
        "design_alternatives": {
            "external_plenum_at_100mm_bulk_footprint": {
                "minimum_external_volume_ml_per_side": target_ml
                + displacement_ml
                - float(literal["gross_empty_cavity_volume_ml_per_side"]),
                "strength": "Preserves the compact 100 x 100 mm bulk-cavity footprint.",
                "weakness": "Adds tubing/plenum dead volume, surface adsorption and a mixing delay to a five-second test.",
            },
            "compact_cell_with_revised_protocol": {
                "conservative_installed_net_volume_ml_per_side": float(
                    compact_bounded["resulting_net_gas_volume_ml_per_side"]
                ),
                "maximum_segment_duration_s": float(
                    compact_bounded["maximum_segment_duration_for_rh_limit_s"]
                ),
                "minimum_switching_frequency_hz": float(
                    compact_bounded["minimum_switching_frequency_for_rh_limit_hz"]
                ),
                "maximum_flux_g_m2_h": float(
                    compact_bounded["maximum_flux_for_rh_limit_g_m2_h"]
                ),
                "strength": "Keeps the original compact cavity without external volume.",
                "weakness": "Changes the experimental basis and becomes faster than the screened humidity sensor response.",
            },
        },
        "pressure_management": {
            "rigid_single_side_pressure_change_pa": rigid_single_side_pressure_pa,
            "rigid_chamber_to_chamber_difference_pa": 2.0
            * rigid_single_side_pressure_pa,
            "target_chamber_to_chamber_difference_pa": target_dp,
            "minimum_travel_from_nominal_ul_per_side": diaphragm_travel_ul,
            "minimum_full_stroke_ul_per_side": diaphragm_full_stroke_ul,
            "two_external_reference_diaphragms_minimum_compliance_nl_per_pa_each": external_reference_compliance_nl_pa,
            "one_double_acting_diaphragm_minimum_compliance_nl_per_pa": double_acting_compliance_nl_pa,
        },
        "fastener_screen": {
            "proof_pressure_separation_force_n": pressure_separation_force_n,
            "nominal_preload_n_each": nominal_preload_n_each,
            "fastener_count": fastener_count,
            "nominal_total_preload_n": nominal_preload_n_each * fastener_count,
            "preload_to_proof_pressure_force_ratio": nominal_preload_n_each
            * fastener_count
            / pressure_separation_force_n,
        },
        "seal_screen": {
            "cross_section_mm": seal_cross_section_mm,
            "groove_depth_mm_for_25_percent_squeeze": seal_groove_depth_mm,
            "minimum_groove_width_mm_at_85_percent_fill": minimum_groove_width_mm,
            "recommended_groove_width_mm": float(
                seal["recommended_groove_width_mm"]
            ),
            "resulting_gland_fill_fraction": actual_gland_fill,
            "screened_minimum_effective_gland_depth_mm": minimum_effective_gland_depth_mm,
            "depth_only_worst_gland_fill_fraction": depth_only_worst_gland_fill,
            "maximum_screened_squeeze_fraction": maximum_screened_squeeze_fraction,
            "gas_seal_surface_roughness_rq_um": float(
                seal["recommended_gas_seal_surface_roughness_rq_um"]
            ),
        },
        "interconnect_screen": {
            "header_volume_ml_per_side": header_volume_ml,
            "idealized_4mm_wall_bore_volume_ml_per_side": port_volume_ml,
            "idealized_header_tap_and_wall_bore_volume_ml_per_side": interconnect_volume_ml,
            "unallocated_idealized_margin_ml_per_side": interconnect_budget_ml
            - interconnect_volume_ml,
            "maximum_budget_ml_per_side": interconnect_budget_ml,
            "idealized_bore_screen_passes_budget": interconnect_volume_ml
            <= interconnect_budget_ml,
            "actual_fitting_tube_and_valve_volume_included": False,
            "physical_budget_status": "UNRESOLVED pending CAD or measured fitting-to-isolation-valve volume",
        },
        "fan_screen": {
            "nominal_ideal_turnover_time_s": ideal_turnover_s,
            "turnover_time_at_20_percent_effective_flow_s": conservative_turnover_s,
            "five_second_adiabatic_temperature_rise_at_typical_power_k": typical_adiabatic_fan_rise_k,
            "five_second_adiabatic_temperature_rise_upper_bound_k": maximum_adiabatic_fan_rise_k,
            "maximum_static_pressure_pa": float(fan["maximum_static_pressure_pa"]),
            "sensor_tau63_s": float(flow["humidity_sensor"]["response_time_tau63_s"]),
        },
    }


def build_gate_assessment_frame(
    study: dict[str, Any], summary: dict[str, Any], plates: pd.DataFrame
) -> pd.DataFrame:
    recommended = summary["recommended_geometry"]
    pressure = summary["pressure_management"]
    fastener = summary["fastener_screen"]
    seal = summary["seal_screen"]
    interconnect = summary["interconnect_screen"]
    fan = summary["fan_screen"]
    al = plates.set_index("component").loc["aluminium_load_plate"]
    rows = [
        {
            "gate": "gross_empty_cavity_volume_and_depth",
            "desktop_assessment": "calculated_design_selected",
            "recommendation": "Bruk 165 x 165 x 20 mm bulk-kammerfotavtrykk per side rundt et uendret 50 x 50 mm aktivt membranvindu (25 cm²); 544,5 mL brutto.",
            "strength": "Beholder både 25 cm² membranareal og ønsket dybde på 20 mm, samtidig som det gir kalibreringsmargin.",
            "weakness": "Gir et bredt, grunt plenum og krever en kontrollert overgang via 80 x 80 mm kupong til 50 x 50 mm aktivt vindu; 165 x 165 mm kan ikke være membranaperturen.",
            "remaining_evidence": "Frigi CAD som viser separat bulkplenum, 80 x 80 mm kupong og 50 x 50 mm aktiv apertur; kontroller deretter kavitetsmålene.",
        },
        {
            "gate": "installed_component_displacement",
            "desktop_assessment": "conservative_upper_bound",
            "recommendation": f"Reserver {recommended['component_displacement_upper_bound_ml_per_side']:.1f} mL per side ved å bruke komponentenes fulle avgrensningsvolumer.",
            "strength": "Konservativt tidlig volumbudsjett; faktisk fast fortrengning bør bli mindre.",
            "weakness": "Viftevolumet inneholder luft og er derfor ikke en kalibrert fortrengningsverdi.",
            "remaining_evidence": "Mål hver installert del med CAD/nedsenking og kalibrer det monterte kammeret.",
        },
        {
            "gate": "end_wall_and_central_divider_structural_sizing",
            "desktop_assessment": "uniform_pressure_component_screened",
            "recommendation": f"Behold 12 mm lastplater i 6082-T6 aluminium og minst 16 mm ufylt PEEK-isolasjon; beregnet trykkdeformasjon i aluminium er {al['pressure_only_maximum_deflection_um']:.2f} µm ved 5 kPa.",
            "strength": "Den jevne gasstrykk-komponenten gir liten beregnet deformasjon og spenning.",
            "weakness": "Beregningen utelater punktlaster fra bolter, tetningskraft, hull, PEEK-kryp og temperaturgradienter.",
            "remaining_evidence": "Kontroller endelig CAD/FEA og mål deformasjon under last.",
        },
        {
            "gate": "fluidic_and_electrical_port_interfaces",
            "desktop_assessment": "idealized_wall_bore_screen_only",
            "recommendation": f"Prøv to 316-rustfrie 6 mm OD-bulkheadkoblinger med 4 mm strømningsvei per side og en avtakbar hermetisk seks-pins gjennomføring. Header, trykktapp og to ideelle 4 x 8 mm veggboringer summerer til {interconnect['idealized_header_tap_and_wall_bore_volume_ml_per_side']:.3f} mL og etterlater bare {interconnect['unallocated_idealized_margin_ml_per_side']:.3f} mL av 1,3 mL-budsjettet.",
            "strength": "Standardiserte, gjenbrukbare komponentkandidater og en liten idealisert veggboregeometri.",
            "weakness": "Screeningen utelater faktisk indre volum i koblinger, rør og isolasjonsventiler; den dokumenterer derfor ikke at 1,3 mL-grensen består.",
            "remaining_evidence": "Mål eller hent CAD-volum helt frem til stengte ventiler, frigi grensesnitttegninger og utfør trykkfall- og krysslekkasjetest.",
        },
        {
            "gate": "internal_fan_selection_and_mounting",
            "desktop_assessment": "catalogue_screen_only",
            "recommendation": f"Prøv én NF-A4x10 5V PWM-vifte per side, innfelt eller kantmontert. Ideell volumomsetning er {fan['nominal_ideal_turnover_time_s']:.2f} s og 20%-skjermen gir {fan['turnover_time_at_20_percent_effective_flow_s']:.2f} s.",
            "strength": "Passer innen 20 mm dybde, har PWM-styring og god katalogluftmengde.",
            "weakness": f"V/Q er ikke blandetid. Maksimal statisk viftetrykk er {fan['maximum_static_pressure_pa']:.1f} Pa mot 5 Pa-målet, og maksimal katalogeffekt gir en gas-only øvre temperaturgrense på {fan['five_second_adiabatic_temperature_rise_upper_bound_k']:.1f} K.",
            "remaining_evidence": "Mål temperaturbias, faktisk fortrengning, strømning og vibrasjon i begge kamre.",
        },
        {
            "gate": "baffle_geometry_and_mounting",
            "desktop_assessment": "starting_geometry_proposed",
            "recommendation": "Bruk avtakbare 1 mm PEEK-vende-/fordelerskovler som fordeler strømmen symmetrisk mellom 165 x 165 mm bulkplenum og 50 x 50 mm aktivt membranvindu, minst 60% åpne og maksimalt 2 mL fastvolum per side.",
            "strength": "Bevarer 25 cm² aktivt areal, gir lite volumtap og kan itereres mot dødsoner.",
            "weakness": "Den store arealkontraksjonen kan gi fuktgradienter og lokalt trykkfall; åpningsgrad alene beviser ikke jevn blanding.",
            "remaining_evidence": "Frigi overgangs-/baffel-CAD etter flerposisjons sporstoff- eller rask fuktkartlegging over 50 x 50 mm-vinduet.",
        },
        {
            "gate": "differential_pressure_management",
            "desktop_assessment": "required_compliance_calculated",
            "recommendation": f"Bruk enten to eksternrefererte gasstette diafragmaer med minst +/-{pressure['minimum_travel_from_nominal_ul_per_side']:.0f} µL vandring, {pressure['minimum_full_stroke_ul_per_side'] / 1000.0:.2f} mL fullt slag og {pressure['two_external_reference_diaphragms_minimum_compliance_nl_per_pa_each'] / 1.0e6:.3f} mL/Pa hver, eller én dobbeltvirkende med samme slag og {pressure['one_double_acting_diaphragm_minimum_compliance_nl_per_pa'] / 1.0e6:.3f} mL/Pa mot differansetrykket.",
            "strength": "Utjevner trykk uten direkte blanding av de fuktige gassinventarene.",
            "weakness": "Friksjon, fjærstivhet, hysterese og permeasjon kan dominere ved bare 5 Pa.",
            "remaining_evidence": "Kjør hele ABBA-sekvensen med kalibrert differansetrykksensor.",
        },
        {
            "gate": "fixture_mounting_fastener_pattern_and_preload",
            "desktop_assessment": "pressure_separation_only_screen",
            "recommendation": f"Bruk {fastener['fastener_count']} x M5 A4-skruer med omtrent 45-50 mm perifer avstand, harde kompresjonsstopp og skivefjærer; 1,0 Nm gir omtrent {fastener['nominal_preload_n_each']:.0f} N nominelt per skrue ved K=0,2.",
            "strength": f"Nominell samlet forspenning er omtrent {fastener['preload_to_proof_pressure_force_ratio']:.0f} ganger den rene separasjonskraften fra 5 kPa.",
            "weakness": "Spredning mellom moment og forspenning samt PEEK-kryp gjør moment alene uegnet som gapkontroll.",
            "remaining_evidence": "Definer boltmønster, kryssvis tiltrekking og kontroller last/gap etter holdetid.",
        },
        {
            "gate": "seal_geometry_and_compression",
            "desktop_assessment": "gland_starting_dimensions_calculated",
            "recommendation": f"Prøv to kontinuerlige 2 mm EPDM 70-plantetninger ved 25% nominell klem: 1,50 mm spordybde og 2,90 mm bredde ({100.0 * seal['resulting_gland_fill_fraction']:.1f}% nominell fylling), adskilt av guardsporet. Spesifiser gasstetningsflaten som Rq/RMS <= {seal['gas_seal_surface_roughness_rq_um']:.1f} µm, ikke Ra.",
            "strength": f"Dobbel tetning gir målbar guard-lekkasje; bredere spor har {100.0 * seal['depth_only_worst_gland_fill_fraction']:.1f}% fylling selv ved screenet 1,40 mm effektiv dybde.",
            "weakness": "Diameter-/sportoleranse, hjørnevolum, svelling, kompresjonssett og permeasjon er fortsatt ikke fullstendig toleransestablet.",
            "remaining_evidence": "Bekreft leverandørens toleranser og kompatibilitet, gjør full gland-stack og utfør lekkasje-/blanktest med harde stopp.",
        },
        {
            "gate": "drawing_datums_and_dimensional_tolerances",
            "desktop_assessment": "starting_scheme_defined",
            "recommendation": "Datum A på membran-/tetningsplanet, B/C på ortogonale senterplan; 20,00 +/- 0,05 mm dybde, 0,05 mm planhet/parallellitet og +/-0,05 mm lokale gap.",
            "strength": "Gir en inspiserbar og symmetrisk stakkdefinisjon.",
            "weakness": "Toleransene øker maskineringskostnaden og er ikke avstemt mot valgt leverandørprosess.",
            "remaining_evidence": "Frigi tegningen og gjennomfør CMM-/planhetskontroll.",
        },
        {
            "gate": "loaded_flatness_and_gap_uniformity",
            "desktop_assessment": "pressure_component_screened",
            "recommendation": f"Bruk harde gapstopp og kartlegg lastede 1/2/4 mm-innsatser; trykkdeformasjonen i aluminium ved 5 kPa er {al['pressure_only_maximum_deflection_um']:.2f} µm mot foreslått 50 µm planhetsgrense.",
            "strength": "Jevnt trykk alene er neglisjerbart sammenlignet med den foreslåtte toleransen.",
            "weakness": "Tetning og diskrete boltlaster, ikke gasstrykket, vil trolig styre virkelig deformasjon.",
            "remaining_evidence": "Kartlegg montert gap under driftsforspenning og etter krypholdetid.",
        },
        {
            "gate": "internal_mixing_time",
            "desktop_assessment": "flow_capacity_screen_only",
            "recommendation": "Bruk symmetrisk kontinuerlig PWM-blanding og verifiser romlig trinnrespons med en raskere referanse enn SHT45.",
            "strength": f"Katalogluftmengden tilsvarer {fan['turnover_time_at_20_percent_effective_flow_s']:.2f} s per kammervolum selv ved 20% effektivitet.",
            "weakness": f"SHT45 har tau63 på {fan['sensor_tau63_s']:.1f} s, nesten hele 5 s-segmentet, og kan ikke alene bevise den modellerte 0,1 s-transienten.",
            "remaining_evidence": "Mål blandetid på flere posisjoner med rask dampanalysator eller validert sporstoffmetode.",
        },
        {
            "gate": "net_volume_calibration",
            "desktop_assessment": "trim_range_designed_not_measured",
            "recommendation": f"Maskiner 544,5 mL brutto og bruk modulære PEEK-innsatser som dekker {recommended['required_trim_range_for_zero_to_bounded_component_displacement_ml_per_side'][0]:.1f}-{recommended['required_trim_range_for_zero_to_bounded_component_displacement_ml_per_side'][1]:.1f} mL per side; {recommended['nominal_removable_trim_insert_ml_per_side']:.1f} mL er startverdien ved konservativ komponentgrense.",
            "strength": "Avtakbar trim gjør 500,0 +/- 5,0 mL oppnåelig til tross for komponentusikkerhet.",
            "weakness": "Nominell startinnsats følger en konservativ komponentgrense; mindre faktisk fastvolum krever opptil 44,5 mL innsats.",
            "remaining_evidence": "Kalibrer hver forseglet montert side sporbar i driftskonfigurasjon.",
        },
    ]
    frame = pd.DataFrame(rows)
    frame.insert(1, "gate_name_no", frame["gate"].map(GATE_NAMES_NO))
    frame["physical_gate_status"] = "open_pending_physical_evidence"
    return frame


def markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    def cell(value: Any) -> str:
        return str(value).replace("|", "\\|").replace("\n", " ")

    lines = [
        "| " + " | ".join(cell(value) for value in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend(
        "| " + " | ".join(cell(value) for value in row) + " |" for row in rows
    )
    return "\n".join(lines)


def write_report(
    path: Path,
    study: dict[str, Any],
    quantities: dict[str, float],
    scenarios: pd.DataFrame,
    local_gap: pd.DataFrame,
    plates: pd.DataFrame,
    summary: dict[str, Any],
    gates: pd.DataFrame,
) -> None:
    scenario_rows = []
    for row in scenarios.itertuples():
        scenario_rows.append(
            [
                row.scenario_id,
                f"{row.bulk_cavity_width_mm:.0f} x {row.bulk_cavity_height_mm:.0f}",
                f"{row.active_membrane_area_cm2:.0f}",
                f"{row.gross_empty_cavity_volume_ml_per_side:.1f}",
                f"{row.resulting_net_gas_volume_ml_per_side:.1f}",
                f"{row.single_chamber_rh_change_pp:.3f}",
                f"{row.rigid_chamber_differential_pressure_pa:.1f}",
                "PASS" if row.meets_rh_volume_minimum else "FAIL",
            ]
        )
    gate_rows = []
    for row in gates.itertuples():
        gate_rows.append(
            [
                row.gate_name_no,
                row.desktop_assessment.replace("_", " "),
                row.recommendation,
                row.strength,
                row.weakness,
                row.remaining_evidence,
            ]
        )
    source_lines = "\n".join(
        f"- [{row['title']}]({row['url']}): {row['used_for']}."
        for row in study["sources"]
    )
    compact = summary["literal_100mm_case"]
    geometry = summary["recommended_geometry"]
    membrane = summary["membrane_area_invariant"]
    thresholds = summary["geometry_thresholds"]
    alternatives = summary["design_alternatives"]
    pressure = summary["pressure_management"]
    fan = summary["fan_screen"]
    seal = summary["seal_screen"]
    local_2 = local_gap.loc[local_gap["local_gap_mm"].eq(2.0)].iloc[0]
    local_20 = local_gap.loc[local_gap["local_gap_mm"].eq(20.0)].iloc[0]
    plate_rows = [
        [
            row.material,
            f"{row.thickness_mm:.0f}",
            f"{row.pressure_only_maximum_deflection_um:.3f}",
            f"{row.pressure_only_maximum_bending_stress_mpa:.3f}",
        ]
        for row in plates.itertuples()
    ]
    report = f"""# Test av 20 mm kanaldybde for EO-dampcellen

Status: post-V10 engineering sensitivity. Den publiserte V10-utgivelsen og handoff-v1 er uendret.

## Tolkning og hovedresultat

20 mm er her tolket som bulk kammerdybde på hver side av membranen. **Det aktive membranvinduet er uendret 50 x 50 mm = {quantities['active_membrane_area_cm2']:.0f} cm²** innenfor den eksisterende 80 x 80 mm kupongen, og det lokale membrangapet forblir 2 mm. Alle fukt- og trykkresultater bruker derfor fortsatt 208 g/m²/h over 25 cm², som gir {quantities['rate_mg_s']:.6f} mg/s og {quantities['transferred_mg']:.6f} mg vann per 5 s-segment.

Dimensjonene 100 x 100 mm og 165 x 165 mm nedenfor er bare **bulk-kammerets fotavtrykk**, ikke membranarealet. Med dagens 100 x 100 mm bulkfotavtrykk blir bruttovolumet **200.0 mL per side**. Selv uten installerte komponenter er dette under det beregnede minimumet på **{quantities['required_volume_ml']:.2f} mL** og langt under målet 500.0 +/- 5.0 mL.

Som misforståelsessperre: 165 x 165 mm tilsvarer {membrane['recommended_bulk_footprint_area_cm2_not_active']:.2f} cm², altså {membrane['bulk_footprint_to_active_membrane_area_ratio']:.2f} ganger det aktive arealet. Denne flaten brukes **ikke** i transportberegningen; bare 25 cm²-membranen brukes. Hvis 165 x 165 mm feilaktig ble brukt som aktiv membran, ville nødvendig 5-prosentpoengsvolum øke til omtrent {membrane['if_bulk_footprint_were_incorrectly_used_as_active']['required_volume_for_5pp_ml'] / 1000.0:.2f} L. Det er eksplisitt forbudt i auditen.

Ved 200 mL gir den samme 208 g/m2/h-fluksen og det samme 5 s-segmentet:

- RH-endring per kammer: **{compact['rh_change_pp_per_chamber']:.3f} prosentpoeng**;
- RH etter 5 s: **39.311% i A og 60.689% i B**;
- stivt kammer, differansetrykkdiagnostikk: **{compact['pressure_difference_pa']:.1f} Pa**;
- for å holde 5 prosentpoeng: segmentet må ned til **{compact['maximum_segment_duration_s']:.3f} s**, frekvensen opp til minst **{compact['minimum_switching_frequency_hz']:.4f} Hz**, eller fluksen ned til **{compact['maximum_flux_g_m2_h']:.2f} g/m2/h**.

Den anbefalte 20 mm-løsningen er derfor et **165 x 165 x 20 mm bulk-kammerfotavtrykk** per side rundt det uendrede 50 x 50 mm membranvinduet. Dette gir 544.5 mL brutto uten å øke den aktive membranen. Etter et konservativt komponentbudsjett på {geometry['component_displacement_upper_bound_ml_per_side']:.1f} mL gjenstår {geometry['pretrim_net_volume_ml_per_side']:.1f} mL. Bruk modulære kalibreringsinnsatser med kapasitet fra {geometry['required_trim_range_for_zero_to_bounded_component_displacement_ml_per_side'][0]:.1f} til {geometry['required_trim_range_for_zero_to_bounded_component_displacement_ml_per_side'][1]:.1f} mL per side; {geometry['nominal_removable_trim_insert_ml_per_side']:.1f} mL er startverdien ved konservativ komponentgrense. Trim hver ferdigmonterte side til 500.0 +/- 5.0 mL ved måling.

En kvadratisk 20 mm-kavitet trenger minst {thresholds['minimum_square_side_for_500ml_without_hardware_mm']:.2f} mm side uten maskinvare, {thresholds['minimum_square_side_for_500ml_with_displacement_bound_mm']:.2f} mm med det konservative komponentbudsjettet, og {thresholds['minimum_square_side_for_rh_limit_with_displacement_bound_mm']:.2f} mm for bare å møte RH-grensen. Ved 100 x 100 mm bulkfotavtrykk måtte dybden vært minst {thresholds['required_depth_at_100mm_bulk_footprint_with_displacement_bound_mm']:.1f} mm for 500 mL med samme budsjett.

## Scenarioresultater

{markdown_table(['Scenario', 'Bulkfotavtrykk mm', 'Aktiv membran cm²', 'Brutto mL', 'Netto mL', 'RH-endring pp', 'Delta p Pa', '5 pp-krav'], scenario_rows)}

![Sammenligning av 20 mm-geometri](channel_depth_tradeoff.png)

## Alternative måter å beholde 100 mm bulkfotavtrykk

Det finnes to reelle alternativer til det anbefalte 165 mm-bulkfotavtrykket; membranen er 25 cm² i alle alternativene:

1. Legg til minst **{alternatives['external_plenum_at_100mm_bulk_footprint']['minimum_external_volume_ml_per_side']:.1f} mL eksternt volum per side**. Styrken er at selve cellen forblir kompakt. Svakheten er ekstra slange-/plenumvolum, fuktopptak på flere flater og blandeforsinkelse i en test som bare varer fem sekunder per segment.
2. Bruk den konservative installerte øvre grensen på **{alternatives['compact_cell_with_revised_protocol']['conservative_installed_net_volume_ml_per_side']:.1f} mL** og endre protokollen til høyst **{alternatives['compact_cell_with_revised_protocol']['maximum_segment_duration_s']:.3f} s** per halvsyklus, minst **{alternatives['compact_cell_with_revised_protocol']['minimum_switching_frequency_hz']:.4f} Hz**, eller høyst **{alternatives['compact_cell_with_revised_protocol']['maximum_flux_g_m2_h']:.2f} g/m2/h**. Styrken er enkel mekanikk. Svakheten er at forsøket ikke lenger tester den opprinnelige 5 s / 208 g/m2/h-basen, og sensoren blir for treg i forhold til dynamikken.

## Designporter som kan beregnes eller avgrenses

Ingen fysisk designport er markert lukket fra en skrivebordsberegning. Tabellen skiller en beregnet startverdi fra målingen eller inspeksjonen som fortsatt kreves.

{markdown_table(['Designport', 'Skrivebordsstatus', 'Anbefalt valg', 'Styrke', 'Svakhet', 'Gjenstår'], gate_rows)}

## Mekanisk skjermberegning

Plateskjermen bruker 5 kPa prøvedifferanse over hele det 165 mm brede bulk-kammerspennet, omtrent 12 ganger den stive 500 mL-diagnostikken. Dette er en lineær, enkelt opplagt kvadratplateskjerm og ikke en sluttanalyse/FEA. Det aktive membranspennet er fortsatt bare 50 x 50 mm.

{markdown_table(['Material', 'Thickness mm', 'Pressure deflection um', 'Bending stress MPa'], plate_rows)}

Den beregnede trykkseparasjonskraften ved 5 kPa er {summary['fastener_screen']['proof_pressure_separation_force_n']:.1f} N. {summary['fastener_screen']['fastener_count']} M5-skruer ved 1.0 Nm gir omtrent {summary['fastener_screen']['nominal_preload_n_each']:.0f} N nominell forspenning per skrue med mutterfaktor 0.2. Dette er et styrkesjekkpunkt, ikke en presis forspenningsgaranti; hardstopp og kontroll av lastet gap skal styre tetningskompresjonen.

For to 2 mm EPDM-tetninger ved 25% nominell klem blir startverdien {seal['groove_depth_mm_for_25_percent_squeeze']:.2f} mm spordybde og 2.90 mm bredde, tilsvarende {100.0 * seal['resulting_gland_fill_fraction']:.1f}% nominell gland fill. Ved den screenede minimumsdybden {seal['screened_minimum_effective_gland_depth_mm']:.2f} mm blir dybdebidraget alene {100.0 * seal['depth_only_worst_gland_fill_fraction']:.1f}% fylling og {100.0 * seal['maximum_screened_squeeze_fraction']:.0f}% klem. Diameter-/sportoleranse, hjørnevolum og svelling må fortsatt legges til. Parkers gasstetningsverdi føres som Rq/RMS <= {seal['gas_seal_surface_roughness_rq_um']:.1f} µm, ikke som Ra.

## Trykk, blanding og måling

Den stive 500 mL-modellen gir {pressure['rigid_chamber_to_chamber_difference_pa']:.1f} Pa mellom kamrene etter 5 s. For å holde differansen nær 5 Pa trengs omtrent **+/-{pressure['minimum_travel_from_nominal_ul_per_side'] / 1000.0:.3f} mL** vandring per side og minst **{pressure['minimum_full_stroke_ul_per_side'] / 1000.0:.3f} mL fullt slag**. To separate diafragmaer mot samme eksterne referanse trenger hver omtrent **{pressure['two_external_reference_diaphragms_minimum_compliance_nl_per_pa_each'] / 1.0e6:.3f} mL/Pa** over +/-2,5 Pa. Ett dobbeltvirkende diafragma trenger omtrent **{pressure['one_double_acting_diaphragm_minimum_compliance_nl_per_pa'] / 1.0e6:.3f} mL/Pa** definert mot hele 5 Pa-differansen. Begge er bedre enn en gassforbindelse mellom kamrene; en direkte forbindelse vil blande fukt og ødelegge inventarbalansen.

Den foreslåtte 40 x 40 x 11 mm PWM-viften har 8.9 m3/h katalogstrøm. Fri-blås V/Q tilsvarer {fan['nominal_ideal_turnover_time_s']:.3f} s, og en antatt 20%-faktor gir {fan['turnover_time_at_20_percent_effective_flow_s']:.3f} s. Dette er bare kapasitetshypoteser, ikke beregnet blandetid. Maksimalt statisk trykk er {fan['maximum_static_pressure_pa']:.1f} Pa, større enn 5 Pa-målet, så vifte/baffel og trykktapp må prøves sammen. Varme er også en svakhet: 0.30 W typisk effekt gir {fan['five_second_adiabatic_temperature_rise_at_typical_power_k']:.2f} K, mens 0.35 W maksimal katalogeffekt gir en gas-only, adiabatisk femsekunders øvre grense på {fan['five_second_adiabatic_temperature_rise_upper_bound_k']:.2f} K. Bruk like vifter kontinuerlig på begge sider etter termisk stabilisering, og mål temperaturbias.

SHT45 kan screene en cirka 4.3 prosentpoeng endepunktsendring, men den typiske +/-1 prosentpoeng-nøyaktigheten er omtrent 23% av signalet per avlesning og oppgitt tau63 er 4 s. Den kan derfor ikke alene gi en presis transient eller dokumentere 0.1 s-sampling og sub-segment blanding. Bruk den til endepunkt/quasi-statisk kontroll og en raskere referanse for blandingstesten.

## Dersom 20 mm egentlig betyr lokalt membrangap

Dette er ikke det valgte tilfellet, men følsomheten er beregnet. Lokalt volum øker fra {local_2['local_membrane_region_volume_ml_per_side']:.1f} til {local_20['local_membrane_region_volume_ml_per_side']:.1f} mL per side, mens resterende bulkvolum ved 500 mL faller til {local_20['remaining_bulk_volume_at_500ml_ml_per_side']:.1f} mL. Ved 1 m/s øker kanalstrømmen fra {local_2['channel_flow_at_1m_s_l_min']:.1f} til {local_20['channel_flow_at_1m_s_l_min']:.1f} L/min. En hydraulisk-diameter-screen gir Dh={1000.0 * local_20['rectangular_hydraulic_diameter_m']:.2f} mm, Re={local_20['reynolds_number']:.0f} og k={local_20['gas_film_mass_transfer_coefficient_m_s']:.5f} m/s ved 20 mm, mot k={local_2['gas_film_mass_transfer_coefficient_m_s']:.5f} m/s ved 2 mm. Fordi 20 mm-kanalens bredde/gap bare er {local_20['channel_aspect_ratio_width_to_gap']:.1f}, og én vegg er aktiv mens den andre ikke er det, er Sherwood-randbetingelsen ikke validert; koeffisienten er kun en screeningverdi. Selve headeren blir {local_20['header_volume_ml_per_side']:.1f} mL og overskrider alene 1.3 mL-budsjettet, så feilen er uavhengig av ukjent fittingvolum. Et lokalt 20 mm-gap trenger derfor en egen transport- og headerdesign.

## Begrensninger

- Komponentbudsjettet bruker hele fanens bounding box og er konservativt; faktisk solidvolum må måles.
- Plateskjermen inkluderer ikke bolthull, punktlaster, tetningskraft, kryp, termiske gradienter eller den endelige randbetingelsen.
- Katalogluftmengde er ikke lik blandingstid i den grunne cellen.
- Sensorrespons, diafragmastivhet, lekkasje, overflateadsorpsjon og montert volum kan bare lukkes eksperimentelt.
- Overgangen fra 165 mm bulk-kammerfotavtrykk til 50 x 50 mm aktivt membranvindu kan gi laterale fuktgradienter; baffel og sensorer må derfor valideres ved flere posisjoner.

## Primærkilder for foreslåtte valg

{source_lines}

## Reproduksjon

Kjør:

    python3 scripts/analyze_eo_vapor_test_cell_20mm.py
    python3 -m pytest -q tests/test_eo_vapor_test_cell_20mm_study.py

Maskinlesbare resultater, audit og kildehasher ligger i samme mappe som denne rapporten.
"""
    path.write_text(report, encoding="utf-8")


def make_tradeoff_plot(
    path: Path,
    study: dict[str, Any],
    quantities: dict[str, float],
    sweep: pd.DataFrame,
) -> None:
    displacement_ml = component_displacement_bound_ml(study)
    depth_mm = float(study["interpretation"]["requested_channel_depth_mm"])
    faces = [100.0, 140.0, 165.0]
    labels = [
        "Bulkplenum\n100 x 100 mm",
        "Husgrense\n140 x 140 mm",
        "Anbefalt bulkplenum\n165 x 165 mm",
    ]
    gross = [rectangular_volume_ml(side, side, depth_mm) for side in faces]
    net = [value - displacement_ml for value in gross]

    fig, (ax_drift, ax_volume) = plt.subplots(1, 2, figsize=(11.2, 4.8))
    ax_drift.plot(
        sweep["square_bulk_cavity_footprint_side_mm"],
        sweep["single_chamber_rh_change_pp"],
        color="#176B87",
        linewidth=2.2,
        label=f"Etter {displacement_ml:.1f} mL komponentgrense",
    )
    ax_drift.axhline(
        quantities["allowed_rh_change_pp"],
        color="#B91C1C",
        linestyle="--",
        label="Krav: 5 prosentpoeng",
    )
    for side, color in ((100.0, "#B91C1C"), (165.0, "#15803D")):
        row = sweep.loc[
            sweep["square_bulk_cavity_footprint_side_mm"].eq(side)
        ].iloc[0]
        ax_drift.scatter(
            [side], [row["single_chamber_rh_change_pp"]], s=55, color=color, zorder=3
        )
        ax_drift.annotate(
            f"{side:.0f} mm: {row['single_chamber_rh_change_pp']:.2f} pp",
            (side, row["single_chamber_rh_change_pp"]),
            xytext=(6, 8),
            textcoords="offset points",
            fontsize=9,
        )
    ax_drift.set_xlabel("Sidekant for kvadratisk bulk-kammerfotavtrykk (mm)")
    ax_drift.set_ylabel("RH-endring i ett kammer etter 5 s (prosentpoeng)")
    ax_drift.set_title("20 mm dybde: krav til fuktendring")
    ax_drift.grid(True, alpha=0.25)
    ax_drift.legend(fontsize=8)
    ax_drift.set_ylim(bottom=0.0)

    positions = list(range(len(faces)))
    width = 0.36
    ax_volume.bar(
        [value - width / 2 for value in positions],
        gross,
        width,
        color="#94A3B8",
        label="Brutto kavitet",
    )
    ax_volume.bar(
        [value + width / 2 for value in positions],
        net,
        width,
        color="#176B87",
        label="Etter komponentgrense",
    )
    ax_volume.axhline(
        quantities["target_volume_ml"],
        color="#15803D",
        linestyle="--",
        label="Mål: 500 mL",
    )
    ax_volume.axhline(
        quantities["required_volume_ml"],
        color="#D97706",
        linestyle=":",
        label=f"RH-minimum: {quantities['required_volume_ml']:.1f} mL",
    )
    for index, values in enumerate((gross, net)):
        offset = -width / 2 if index == 0 else width / 2
        for position, value in zip(positions, values):
            ax_volume.text(
                position + offset,
                value + 8.0,
                f"{value:.0f}",
                ha="center",
                va="bottom",
                fontsize=8,
            )
    ax_volume.set_xticks(positions, labels)
    ax_volume.tick_params(axis="x", labelsize=8)
    ax_volume.set_ylabel("Volum per side (mL)")
    ax_volume.set_title("Geometrisk volumbudsjett")
    ax_volume.grid(True, axis="y", alpha=0.25)
    ax_volume.legend(fontsize=8)
    ax_volume.set_ylim(0.0, max(gross) * 1.2)

    fig.suptitle(
        "EO-dampcelle: 20 mm bulkdybde\n"
        "Aktiv membran er fast 50 x 50 mm = 25 cm²",
        fontsize=14,
    )
    fig.tight_layout()
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def write_audit_and_manifest(
    output_dir: Path,
    config_path: Path,
    study: dict[str, Any],
    base_path: Path,
    base_model_path: Path,
    quantities: dict[str, float],
    scenarios: pd.DataFrame,
    local_gap: pd.DataFrame,
    plates: pd.DataFrame,
    summary: dict[str, Any],
    gates: pd.DataFrame,
    generated_paths: list[Path],
) -> None:
    by_scenario = scenarios.set_index("scenario_id")
    literal = by_scenario.loc["100x100x20_geometry_only"]
    recommended = by_scenario.loc["165x165x20_calibrated_to_500ml"]
    pretrim = by_scenario.loc["165x165x20_before_calibration_trim"]
    alternative_gap = local_gap.loc[local_gap["local_gap_mm"].eq(20.0)].iloc[0]
    v10_integrity = verify_release_checksums(
        ROOT / "deliverables" / "current" / "2026-09-02_v10"
    )
    handoff_v1_integrity = verify_release_checksums(
        ROOT / "deliverables" / "current" / "2026-09-03_handoff_v1"
    )
    checks = {
        "declared_outputs_exist_and_are_nonempty": all(
            item.is_file() and item.stat().st_size > 0 for item in generated_paths
        ),
        "twenty_mm_is_bulk_depth_not_local_gap": math.isclose(
            float(study["interpretation"]["requested_channel_depth_mm"]), 20.0
        )
        and math.isclose(
            float(study["membrane_constraint"]["local_gap_remains_mm"]), 2.0
        ),
        "active_membrane_is_fixed_at_50x50mm_and_25cm2": math.isclose(
            quantities["active_membrane_width_mm"], 50.0
        )
        and math.isclose(quantities["active_membrane_height_mm"], 50.0)
        and math.isclose(quantities["active_membrane_area_cm2"], 25.0)
        and math.isclose(quantities["rate_mg_s"], 13.0 / 90.0)
        and summary["membrane_area_invariant"]["coupon_dimensions_mm"]
        == [80.0, 80.0],
        "bulk_footprint_is_not_used_as_transport_area": not bool(
            summary["membrane_area_invariant"][
                "bulk_footprint_used_as_transport_area"
            ]
        )
        and math.isclose(
            summary["membrane_area_invariant"][
                "recommended_bulk_footprint_area_cm2_not_active"
            ],
            272.25,
        )
        and not math.isclose(
            quantities["rate_mg_s"],
            quantities["target_flux_g_m2_h"]
            * 0.027225
            * 1000.0
            / 3600.0,
        ),
        "literal_100x100x20_volume_is_200ml": math.isclose(
            float(literal["gross_empty_cavity_volume_ml_per_side"]), 200.0
        ),
        "literal_geometry_fails_rh_volume_minimum": not bool(
            literal["meets_rh_volume_minimum"]
        ),
        "literal_geometry_exceeds_ten_rh_percentage_points": float(
            literal["single_chamber_rh_change_pp"]
        )
        > 10.0,
        "recommended_geometry_is_544p5ml_gross": math.isclose(
            float(pretrim["gross_empty_cavity_volume_ml_per_side"]), 544.5
        ),
        "recommended_geometry_has_pretrim_margin": float(
            pretrim["resulting_net_gas_volume_ml_per_side"]
        )
        > 500.0,
        "recommended_trim_returns_500ml": math.isclose(
            float(recommended["resulting_net_gas_volume_ml_per_side"]), 500.0
        ),
        "idealized_header_tap_and_wall_bores_fit_budget_at_2mm": bool(
            summary["interconnect_screen"]["idealized_bore_screen_passes_budget"]
        ),
        "actual_fitting_tube_and_valve_volume_remains_unclaimed": not bool(
            summary["interconnect_screen"][
                "actual_fitting_tube_and_valve_volume_included"
            ]
        )
        and summary["interconnect_screen"]["physical_budget_status"].startswith(
            "UNRESOLVED"
        ),
        "alternate_20mm_local_gap_fails_on_header_alone": float(
            alternative_gap["header_volume_ml_per_side"]
        )
        > float(alternative_gap["maximum_interconnect_budget_ml_per_side"]),
        "plate_screens_are_finite_and_positive": bool(
            (
                plates[
                    [
                        "pressure_only_maximum_deflection_um",
                        "pressure_only_maximum_bending_stress_mpa",
                    ]
                ]
                > 0.0
            ).all().all()
        ),
        "all_thirteen_gates_are_assessed": len(gates) == 13
        and gates["gate"].nunique() == 13,
        "no_physical_gate_is_claimed_closed": bool(
            gates["physical_gate_status"].eq(
                "open_pending_physical_evidence"
            ).all()
        ),
        "primary_sources_are_https": all(
            str(row["url"]).startswith("https://") for row in study["sources"]
        ),
        "frozen_v10_checksums_pass": bool(v10_integrity["all_pass"]),
        "handoff_v1_checksums_pass": bool(handoff_v1_integrity["all_pass"]),
    }
    audit = {
        "schema_version": 1,
        "study_id": study["study_id"],
        "calculation_status": "PASS" if all(checks.values()) else "FAIL",
        "all_pass": all(checks.values()),
        "checks": checks,
        "release_checksum_verification": {
            "v10": v10_integrity,
            "handoff_v1": handoff_v1_integrity,
        },
        "design_decision": {
            "literal_100x100x20_status": "REJECT for original 5 s / 500 mL basis",
            "membrane_area": "50 x 50 mm active window = 25 cm2; unchanged",
            "recommended_geometry": "165 x 165 x 20 mm bulk cavity footprint per side around the unchanged 50 x 50 mm membrane window, with measured trim to 500 +/- 5 mL",
            "fabrication_release": "NOT READY; physical evidence remains required",
        },
    }
    write_json(output_dir / "audit.json", audit)
    if not audit["all_pass"]:
        failed = [name for name, value in checks.items() if not value]
        raise RuntimeError(f"20 mm test-cell audit failed: {failed}")

    sources = [
        config_path,
        base_path,
        base_model_path,
        Path(__file__),
        ROOT / "deliverables" / "current" / "2026-09-02_v10" / "SHA256SUMS",
        ROOT
        / "deliverables"
        / "current"
        / "2026-09-03_handoff_v1"
        / "SHA256SUMS",
    ]

    def portable(path: Path) -> str:
        resolved = path.resolve()
        try:
            return resolved.relative_to(ROOT).as_posix()
        except ValueError:
            return resolved.name

    bound_outputs = [*generated_paths, output_dir / "audit.json"]
    manifest = {
        "schema_version": 1,
        "study_id": study["study_id"],
        "sources": [
            {"path": portable(path), "sha256": sha256(path)} for path in sources
        ],
        "generated_outputs": [
            {
                "path": path.resolve().relative_to(output_dir.resolve()).as_posix(),
                "sha256": sha256(path),
                "size_bytes": path.stat().st_size,
            }
            for path in bound_outputs
        ],
        "verification": {
            "audit_all_pass": True,
            "manifest_self_excluded_to_avoid_recursive_hash": True,
            "frozen_v10_and_handoff_v1_unchanged": bool(
                v10_integrity["all_pass"] and handoff_v1_integrity["all_pass"]
            ),
            "release_checksum_verification": {
                "v10": v10_integrity,
                "handoff_v1": handoff_v1_integrity,
            },
        },
    }
    write_json(output_dir / "source_manifest.json", manifest)


def run(config_path: Path, output_dir: Path) -> dict[str, Any]:
    study = read_json(config_path)
    base_path = ROOT / study["base_config"]
    base_model_path = ROOT / "scripts" / "design_eo_vapor_test_cell.py"
    base = read_json(base_path)
    model = load_base_model(base_model_path)
    validate_study_config(study, base)
    quantities = base_quantities(base, model)
    scenarios = build_scenario_frame(study, quantities)
    sweep = build_geometry_sweep_frame(study, quantities)
    local_gap = build_local_gap_interpretation_frame(study, base)
    plates = build_plate_pressure_screen_frame(study)
    summary = build_decision_summary(study, quantities, scenarios)
    gates = build_gate_assessment_frame(study, summary, plates)

    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "scenarios": output_dir / "scenario_comparison.csv",
        "sweep": output_dir / "geometry_sweep.csv",
        "local_gap": output_dir / "local_gap_interpretation.csv",
        "plates": output_dir / "plate_pressure_screen.csv",
        "gates": output_dir / "engineering_gate_assessment.csv",
        "summary": output_dir / "decision_summary.json",
        "report": output_dir / "REPORT.md",
        "plot": output_dir / "channel_depth_tradeoff.png",
    }
    scenarios.to_csv(paths["scenarios"], index=False)
    sweep.to_csv(paths["sweep"], index=False)
    local_gap.to_csv(paths["local_gap"], index=False)
    plates.to_csv(paths["plates"], index=False)
    gates.to_csv(paths["gates"], index=False)
    write_json(paths["summary"], summary)
    write_report(
        paths["report"], study, quantities, scenarios, local_gap, plates, summary, gates
    )
    make_tradeoff_plot(paths["plot"], study, quantities, sweep)
    generated_paths = list(paths.values())
    write_audit_and_manifest(
        output_dir,
        config_path,
        study,
        base_path,
        base_model_path,
        quantities,
        scenarios,
        local_gap,
        plates,
        summary,
        gates,
        generated_paths,
    )
    return {
        "status": "PASS",
        "study_id": study["study_id"],
        "literal_100mm_status": "REJECT",
        "active_membrane_area_cm2": quantities["active_membrane_area_cm2"],
        "recommended_bulk_cavity_footprint_mm": 165.0,
        "bulk_depth_mm": 20.0,
        "assessed_gates": len(gates),
        "output_dir": output_dir.as_posix(),
    }


def main() -> None:
    args = parse_args()
    result = run(args.config, args.output_dir)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
