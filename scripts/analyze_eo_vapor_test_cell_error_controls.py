#!/usr/bin/env python3
"""Calculate the error-controlled mechanical and measurement design of the EO cell."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "eo_vapor_test_cell_error_control_design.json"
DEFAULT_OUTPUT_DIR = ROOT / "reports" / "test_cell_error_control_design_2026-09-04"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def plate_deflection_um(
    pressure_pa: float,
    span_mm: float,
    thickness_mm: float,
    elastic_modulus_gpa: float,
    poisson_ratio: float,
    coefficient: float,
) -> float:
    thickness_m = thickness_mm / 1000.0
    rigidity_nm = elastic_modulus_gpa * 1.0e9 * thickness_m**3 / (
        12.0 * (1.0 - poisson_ratio**2)
    )
    return coefficient * pressure_pa * (span_mm / 1000.0) ** 4 / rigidity_nm * 1.0e6


def plate_screen(config: dict[str, Any]) -> pd.DataFrame:
    mechanical = config["mechanical_design"]
    measurement = config["measurement_basis"]
    rows: list[dict[str, Any]] = []
    for key in ("outer_load_plate", "insulating_cartridge_plate"):
        material = mechanical[key]
        for thickness_mm in material["candidate_thicknesses_mm"]:
            deflection_um = plate_deflection_um(
                float(mechanical["proof_differential_pressure_pa"]),
                float(measurement["bulk_cavity_footprint_mm"][0]),
                float(thickness_mm),
                float(material["elastic_modulus_gpa"]),
                float(material["poisson_ratio"]),
                float(mechanical["plate_model"]["deflection_coefficient"]),
            )
            rows.append(
                {
                    "component": key,
                    "material": material["material"],
                    "thickness_mm": float(thickness_mm),
                    "pressure_only_deflection_um": deflection_um,
                    "deflection_as_percent_of_local_gap": 100.0
                    * deflection_um
                    / (1000.0 * float(measurement["local_gap_mm"])),
                    "passes_pressure_only_deflection_limit": deflection_um
                    <= float(mechanical["pressure_only_deflection_limit_um"]),
                    "selected": math.isclose(
                        float(thickness_mm), float(material["selected_thickness_mm"])
                    ),
                }
            )
    return pd.DataFrame(rows)


def minimum_plate_thicknesses(config: dict[str, Any]) -> dict[str, float]:
    mechanical = config["mechanical_design"]
    measurement = config["measurement_basis"]
    results: dict[str, float] = {}
    for key in ("outer_load_plate", "insulating_cartridge_plate"):
        material = mechanical[key]
        deflection_at_one_mm = plate_deflection_um(
            float(mechanical["proof_differential_pressure_pa"]),
            float(measurement["bulk_cavity_footprint_mm"][0]),
            1.0,
            float(material["elastic_modulus_gpa"]),
            float(material["poisson_ratio"]),
            float(mechanical["plate_model"]["deflection_coefficient"]),
        )
        results[key] = (
            deflection_at_one_mm
            / float(mechanical["pressure_only_deflection_limit_um"])
        ) ** (1.0 / 3.0)
    return results


def edge_screen(config: dict[str, Any]) -> pd.DataFrame:
    width_mm, height_mm = [float(value) for value in config["measurement_basis"]["active_window_mm"]]
    rows = []
    for band_mm in config["edge_control"]["edge_band_widths_to_screen_mm"]:
        band_mm = float(band_mm)
        unaffected_area_mm2 = max(width_mm - 2.0 * band_mm, 0.0) * max(
            height_mm - 2.0 * band_mm, 0.0
        )
        total_area_mm2 = width_mm * height_mm
        rows.append(
            {
                "edge_band_width_mm": band_mm,
                "edge_affected_area_mm2": total_area_mm2 - unaffected_area_mm2,
                "edge_affected_fraction_percent": 100.0
                * (total_area_mm2 - unaffected_area_mm2)
                / total_area_mm2,
                "unaffected_central_area_cm2": unaffected_area_mm2 / 100.0,
            }
        )
    return pd.DataFrame(rows)


def aperture_regression_design(config: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for side_mm in config["edge_control"]["characterisation_apertures_mm"]:
        side_mm = float(side_mm)
        rows.append(
            {
                "square_aperture_side_mm": side_mm,
                "area_cm2": side_mm**2 / 100.0,
                "perimeter_mm": 4.0 * side_mm,
                "perimeter_to_area_per_mm": 4.0 / side_mm,
                "role": "primary measurement" if side_mm == 50.0 else "edge-regression insert",
            }
        )
    return pd.DataFrame(rows)


def surface_and_signal_screen(config: dict[str, Any], base_model) -> dict[str, float]:
    basis = config["measurement_basis"]
    width_m = float(basis["bulk_cavity_footprint_mm"][0]) / 1000.0
    height_m = float(basis["bulk_cavity_footprint_mm"][1]) / 1000.0
    depth_m = float(basis["bulk_depth_mm"]) / 1000.0
    surface_area_m2 = 2.0 * width_m * height_m + 2.0 * depth_m * (width_m + height_m)
    volume_m3 = float(basis["calibrated_net_volume_ml_per_side"]) / 1.0e6
    transferred_mg = float(basis["conditional_water_rate_mg_s"]) * float(
        basis["segment_duration_s"]
    )
    blank_fraction = float(
        config["wetted_surface_control"]["blank_acceptance_fraction_of_segment_signal"]
    )
    allowed_blank_mg = blank_fraction * transferred_mg
    equivalent_film_nm = (
        allowed_blank_mg / 1.0e6 / (1000.0 * surface_area_m2) * 1.0e9
    )
    base = read_json(ROOT / config["base_config"])
    temperature_c = float(base["operating_state"]["temperature_c"])
    h = 0.001
    density = float(base_model.saturated_water_vapour_density_kg_m3(temperature_c))
    derivative = (
        float(base_model.saturated_water_vapour_density_kg_m3(temperature_c + h))
        - float(base_model.saturated_water_vapour_density_kg_m3(temperature_c - h))
    ) / (2.0 * h)
    max_delta_t = float(
        config["instrumentation_and_control"]["maximum_chamber_temperature_difference_k"]
    )
    return {
        "conservative_internal_surface_area_m2_per_side": surface_area_m2,
        "surface_to_net_volume_ratio_m2_m3": surface_area_m2 / volume_m3,
        "conditional_segment_signal_mg": transferred_mg,
        "one_nm_equivalent_water_film_mg": 1000.0
        * surface_area_m2
        * 1.0e-9
        * 1.0e6,
        "allowed_wall_storage_blank_mg": allowed_blank_mg,
        "allowed_equivalent_reversible_water_film_change_nm": equivalent_film_nm,
        "saturated_water_density_kg_m3": density,
        "fractional_saturation_density_sensitivity_per_k": derivative / density,
        "temperature_scale_error_percent_at_selected_delta_t": 100.0
        * derivative
        / density
        * max_delta_t,
    }


def measurement_screen(config: dict[str, Any], surface: dict[str, float]) -> dict[str, float]:
    basis = config["measurement_basis"]
    controls = config["instrumentation_and_control"]
    base = read_json(ROOT / config["base_config"])
    base_model = load_module(ROOT / "scripts" / "design_eo_vapor_test_cell.py", "eo_error_base_model")
    density = float(
        base_model.saturated_water_vapour_density_kg_m3(
            float(base["operating_state"]["temperature_c"])
        )
    )
    signal_mg = float(surface["conditional_segment_signal_mg"])
    volume_ml = float(basis["calibrated_net_volume_ml_per_side"])
    rh_change_pp = signal_mg / 1.0e6 / (density * volume_ml / 1.0e6) * 100.0
    differential_rh_fraction = 2.0 * rh_change_pp / 100.0
    differential_concentration_mg_l = density * differential_rh_fraction * 1000.0
    leakage_allowance_fraction = float(
        config["error_budget_percent_of_corrected_segment_signal"]["leakage_residual"]
    ) / 100.0
    allowed_cross_leak_l_min = (
        leakage_allowance_fraction
        * signal_mg
        / differential_concentration_mg_l
        / float(basis["segment_duration_s"])
        * 60.0
    )
    return {
        "ideal_rh_change_pp_per_chamber": rh_change_pp,
        "maximum_rh_difference_pp": 2.0 * rh_change_pp,
        "volume_measurement_scale_uncertainty_percent": 100.0
        * float(controls["maximum_net_volume_measurement_uncertainty_ml"])
        / volume_ml,
        "relative_calibration_fraction_of_signal_percent": 100.0
        * float(controls["pairwise_relative_calibration_target_rh_pp"])
        / rh_change_pp,
        "spatial_disagreement_fraction_of_signal_percent": 100.0
        * float(controls["maximum_spatial_rh_disagreement_pp"])
        / rh_change_pp,
        "pressure_compensation_volume_fraction_percent": 100.0
        * float(controls["pressure_compensation_travel_ml_per_side"])
        / volume_ml,
        "cross_leak_flow_screen_l_min_at_peak_rh_difference": allowed_cross_leak_l_min,
    }


def error_budget_frame(config: dict[str, Any]) -> pd.DataFrame:
    rows = [
        {"source": key, "allocation_percent": float(value)}
        for key, value in config["error_budget_percent_of_corrected_segment_signal"].items()
    ]
    return pd.DataFrame(rows)


def validate(
    config: dict[str, Any],
    plates: pd.DataFrame,
    edge: pd.DataFrame,
    surface: dict[str, float],
    measurement: dict[str, float],
    budget: pd.DataFrame,
) -> dict[str, bool]:
    selected = plates[plates["selected"]]
    checks = {
        "primary_area_is_25_cm2": math.isclose(
            math.prod(config["measurement_basis"]["active_window_mm"]) / 100.0, 25.0
        ),
        "selected_plates_pass_pressure_only_deflection_limit": bool(
            selected["passes_pressure_only_deflection_limit"].all()
        ),
        "selected_loaded_gap_tolerance_is_one_percent": math.isclose(
            float(config["mechanical_design"]["loaded_local_gap_tolerance_mm"])
            / float(config["measurement_basis"]["local_gap_mm"]),
            0.01,
        ),
        "one_mm_edge_band_is_not_negligible": bool(
            edge.loc[np.isclose(edge["edge_band_width_mm"], 1.0), "edge_affected_fraction_percent"].iloc[0]
            > 5.0
        ),
        "wall_blank_is_below_one_percent_of_signal": math.isclose(
            surface["allowed_wall_storage_blank_mg"]
            / surface["conditional_segment_signal_mg"],
            0.01,
        ),
        "individual_volume_uncertainty_is_at_most_quarter_percent": measurement[
            "volume_measurement_scale_uncertainty_percent"
        ]
        <= 0.25,
        "planning_rss_error_is_below_four_percent": float(
            np.sqrt(np.square(budget["allocation_percent"]).sum())
        )
        < 4.0,
    }
    if not all(checks.values()):
        failed = [key for key, value in checks.items() if not value]
        raise ValueError(f"Error-control design checks failed: {failed}")
    return checks


def build_summary(
    config: dict[str, Any],
    plates: pd.DataFrame,
    minimums: dict[str, float],
    edge: pd.DataFrame,
    surface: dict[str, float],
    measurement: dict[str, float],
    budget: pd.DataFrame,
) -> dict[str, Any]:
    selected_rows = plates[plates["selected"]].set_index("component")
    one_mm_edge = edge.loc[np.isclose(edge["edge_band_width_mm"], 1.0)].iloc[0]
    return {
        "study_id": config["study_id"],
        "status": "BUILD BASIS; fabrication release still requires physical validation",
        "selected_construction": {
            "outer_load_plate": {
                "material": config["mechanical_design"]["outer_load_plate"]["material"],
                "thickness_mm": config["mechanical_design"]["outer_load_plate"]["selected_thickness_mm"],
                "pressure_only_deflection_um": float(
                    selected_rows.loc["outer_load_plate", "pressure_only_deflection_um"]
                ),
                "calculated_minimum_for_5um_screen_mm": minimums["outer_load_plate"],
            },
            "insulating_cartridge_plate": {
                "material": config["mechanical_design"]["insulating_cartridge_plate"]["material"],
                "thickness_mm": config["mechanical_design"]["insulating_cartridge_plate"]["selected_thickness_mm"],
                "pressure_only_deflection_um": float(
                    selected_rows.loc["insulating_cartridge_plate", "pressure_only_deflection_um"]
                ),
                "calculated_minimum_for_5um_screen_mm": minimums[
                    "insulating_cartridge_plate"
                ],
            },
            "wetted_surface": config["wetted_surface_control"]["construction"],
            "loaded_local_gap_mm": config["measurement_basis"]["local_gap_mm"],
            "loaded_local_gap_tolerance_mm": config["mechanical_design"][
                "loaded_local_gap_tolerance_mm"
            ],
        },
        "edge_control": {
            "one_mm_band_fraction_percent": float(one_mm_edge["edge_affected_fraction_percent"]),
            "primary_window_mm": config["measurement_basis"]["active_window_mm"],
            "characterisation_apertures_mm": config["edge_control"][
                "characterisation_apertures_mm"
            ],
            "acceptance": config["edge_control"]["acceptance"],
        },
        "wall_storage": surface,
        "measurement_controls": measurement,
        "instrumentation_acceptance": {
            "humidity_temperature_sensors_per_chamber": config[
                "instrumentation_and_control"
            ]["humidity_temperature_sensors_per_chamber"],
            "pairwise_relative_calibration_target_rh_pp": config[
                "instrumentation_and_control"
            ]["pairwise_relative_calibration_target_rh_pp"],
            "maximum_spatial_rh_disagreement_pp": config[
                "instrumentation_and_control"
            ]["maximum_spatial_rh_disagreement_pp"],
            "maximum_chamber_temperature_difference_k": config[
                "instrumentation_and_control"
            ]["maximum_chamber_temperature_difference_k"],
            "maximum_net_volume_measurement_uncertainty_ml": config[
                "instrumentation_and_control"
            ]["maximum_net_volume_measurement_uncertainty_ml"],
        },
        "seal_design": config["sealing"],
        "planning_root_sum_square_error_percent": float(
            np.sqrt(np.square(budget["allocation_percent"]).sum())
        ),
        "planning_worst_case_sum_percent": float(budget["allocation_percent"].sum()),
        "mandatory_run_sequence": config["mandatory_run_sequence"],
        "claim_boundary": "The calculations screen known error mechanisms. Edge, adsorption, leakage, mixing and preload terms are accepted only through the specified physical blanks and validation tests.",
    }


def build_figure(plates: pd.DataFrame, edge: pd.DataFrame, output_path: Path) -> None:
    figure, axes = plt.subplots(1, 2, figsize=(11.6, 4.7))
    colours = {"outer_load_plate": "#17304b", "insulating_cartridge_plate": "#d97706"}
    labels = {"outer_load_plate": "Aluminium load wall", "insulating_cartridge_plate": "PEEK insulating plate"}
    for component, group in plates.groupby("component"):
        axes[0].plot(
            group["thickness_mm"], group["pressure_only_deflection_um"],
            marker="o", linewidth=2.0, color=colours[component], label=labels[component],
        )
        selected = group[group["selected"]].iloc[0]
        axes[0].scatter(
            [selected["thickness_mm"]], [selected["pressure_only_deflection_um"]],
            s=80, facecolor="white", edgecolor=colours[component], linewidth=2.0, zorder=5,
        )
    axes[0].axhline(5.0, color="#b91c1c", linestyle="--", linewidth=1.2, label="Pressure-only limit")
    axes[0].set_yscale("log")
    axes[0].set_xlabel("Plate thickness (mm)")
    axes[0].set_ylabel("Calculated deflection at proof pressure (µm)")
    axes[0].set_title("Wall stiffness screen")
    axes[0].grid(True, which="both", alpha=0.25)
    axes[0].legend(fontsize=8)

    axes[1].plot(
        edge["edge_band_width_mm"], edge["edge_affected_fraction_percent"],
        marker="o", linewidth=2.2, color="#127a9b",
    )
    axes[1].axhline(5.0, color="#b91c1c", linestyle="--", linewidth=1.2, label="Nominal five-percent level")
    axes[1].set_xlabel("Hypothetical affected band width (mm)")
    axes[1].set_ylabel("Fraction of active membrane area (%)")
    axes[1].set_title("Why edge effects require measurement")
    axes[1].grid(True, alpha=0.25)
    axes[1].legend(fontsize=8)
    figure.suptitle("EO vapour test cell — wall and edge error controls", fontsize=14, fontweight="bold", color="#17304b")
    figure.tight_layout()
    figure.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(figure)


def build_report(
    config: dict[str, Any], summary: dict[str, Any], plates: pd.DataFrame, edge: pd.DataFrame
) -> str:
    selected = summary["selected_construction"]
    wall = summary["wall_storage"]
    measurement = summary["measurement_controls"]
    al = selected["outer_load_plate"]
    peek = selected["insulating_cartridge_plate"]
    edge_rows = "\n".join(
        f"| {row.edge_band_width_mm:.1f} | {row.edge_affected_fraction_percent:.2f} | {row.unaffected_central_area_cm2:.2f} |"
        for row in edge.itertuples()
    )
    plate_rows = "\n".join(
        f"| {row.material} | {row.thickness_mm:.0f} | {row.pressure_only_deflection_um:.3f} | {row.deflection_as_percent_of_local_gap:.3f} | {'selected' if row.selected else ''} |"
        for row in plates.itertuples()
    )
    sequence = "\n".join(
        f"{index}. {item}" for index, item in enumerate(config["mandatory_run_sequence"], start=1)
    )
    return f"""# EO vapour test cell — error-controlled design basis

Status: **build basis, not fabrication release**. Known errors are calculated where possible and converted into physical acceptance tests where calculation alone is not credible.

![Wall and edge screens](wall_and_edge_error_controls.png)

## Construction selected

- Outer structural/load walls: **{al['thickness_mm']:.0f} mm EN AW-6082-T6 aluminium**. Calculated pressure-only deflection is {al['pressure_only_deflection_um']:.3f} µm at the 5 kPa proof screen; the calculated thickness needed for the 5 µm criterion is {al['calculated_minimum_for_5um_screen_mm']:.2f} mm.
- Electrically insulating cartridge plate: **{peek['thickness_mm']:.0f} mm unfilled PEEK**. Calculated pressure-only deflection is {peek['pressure_only_deflection_um']:.3f} µm; the calculated 5 µm minimum is {peek['calculated_minimum_for_5um_screen_mm']:.2f} mm.
- Local membrane gap: **2.00 ± 0.02 mm under operating preload**, controlled by hard stops and verified after assembly.
- Wetted bulk walls: structural aluminium outside the gas boundary with a removable, smooth non-porous metal liner. Exposed PEEK is confined to the necessary insulating cartridge land.
- Sealing: two continuous 2 mm EPDM 70 Shore A face seals, 25% nominal squeeze, separated by a vented and monitored guard groove.

The uniform-pressure calculation does not close the bolt/seal load case. Final CAD/FEA and a loaded gap map remain mandatory because discrete fastener loads, seal compression and PEEK creep can dominate the gas-pressure deflection.

## Plate screen

| Material | Thickness (mm) | Deflection (µm) | Gap fraction (%) | Decision |
| --- | ---: | ---: | ---: | --- |
{plate_rows}

## Edge effect control

An affected perimeter band is not negligible in a 50 x 50 mm active window:

| Band width (mm) | Affected active area (%) | Unaffected centre (cm²) |
| ---: | ---: | ---: |
{edge_rows}

Wall thickness cannot remove this error. The cell therefore uses interchangeable 30, 40 and 50 mm square apertures and fits `R = J_area A + J_edge P` at matched gap, humidity, temperature and electrical loading. The 50 mm aperture remains the primary 25 cm² measurement. The perimeter term plus regression uncertainty must be no more than 1.5% of the corrected signal.

## Wall storage and thermal control

The conservative internal area is {wall['conservative_internal_surface_area_m2_per_side']:.5f} m² per side, or {wall['surface_to_net_volume_ratio_m2_m3']:.1f} m²/m³ at 500 mL. A one-nanometre equivalent water layer on this area is {wall['one_nm_equivalent_water_film_mg']:.5f} mg, {100.0 * wall['one_nm_equivalent_water_film_mg'] / wall['conditional_segment_signal_mg']:.2f}% of the {wall['conditional_segment_signal_mg']:.6f} mg segment signal. The one-percent blank limit is only {wall['allowed_wall_storage_blank_mg']:.6f} mg, equivalent to {wall['allowed_equivalent_reversible_water_film_change_nm']:.3f} nm.

This is too small to guarantee from a bulk material datasheet. Low-sorption construction, controlled cleaning/preconditioning and an impermeable-coupon blank are therefore part of the measurement, not optional preparation. A chamber temperature mismatch of 0.05 K produces a {wall['temperature_scale_error_percent_at_selected_delta_t']:.3f}% saturation-density scale effect at the selected state; both temperature and pressure are included in each chamber inventory calculation.

## Measurement controls

- Trim each fully assembled chamber into the 500 ± 5 mL acceptance band, measure its actual volume with no more than 1 mL uncertainty ({measurement['volume_measurement_scale_uncertainty_percent']:.2f}% scale contribution), and use that measured value in the inventory calculation.
- Use two T/RH locations per chamber. Pair-calibrate the channels to 0.1 percentage point and reject segments with more than 0.15 percentage point spatial disagreement.
- Keep chamber-to-chamber temperature difference at or below 0.05 K.
- Keep differential pressure at or below 5 Pa using two isolated symmetric compensators. The ±2.4 mL travel is {measurement['pressure_compensation_volume_fraction_percent']:.2f}% of chamber volume and must be included in the inventory calculation.
- The 0.5% leakage allocation corresponds to only {1000.0 * measurement['cross_leak_flow_screen_l_min_at_peak_rh_difference']:.2f} mL/min at the peak ideal RH difference. Use the pressure-decay and guard measurements to reject, not merely correct, unstable leakage.
- Infer water from measured `(T, RH, p, V)` inventory on both sides. RH alone is not the result.

The planning root-sum-square allocation is **{summary['planning_root_sum_square_error_percent']:.2f}%** of the corrected segment signal. This is a planning budget, not demonstrated accuracy; correlated terms do not combine by root-sum-square and the physical validation sequence controls release.

## Mandatory sequence

{sequence}

## Decision

The former 12 mm aluminium / 16 mm PEEK concept is tightened to **12 mm aluminium / 20 mm PEEK**, loaded 2.00 ± 0.02 mm local gaps, low-sorption removable liners, four spatial T/RH channels, individual volume calibration, monitored double seals and aperture scaling. Fabrication release remains blocked until the loaded gap, blank, leakage, mixing and edge-regression criteria pass.
"""


def write_manifest(config_path: Path, output_dir: Path, outputs: list[Path]) -> None:
    config = read_json(config_path)
    sources = [
        config_path,
        ROOT / config["base_config"],
        ROOT / config["geometry_config"],
        ROOT / config["selected_working_point_config"],
        ROOT / "scripts" / "design_eo_vapor_test_cell.py",
        Path(__file__).resolve(),
    ]
    manifest = {
        "schema_version": 1,
        "study_id": config["study_id"],
        "sources": [
            {"path": path.relative_to(ROOT).as_posix(), "sha256": sha256(path)}
            for path in sources
        ],
        "outputs": [
            {
                "path": path.relative_to(output_dir).as_posix(),
                "sha256": sha256(path),
                "size_bytes": path.stat().st_size,
            }
            for path in outputs
        ],
    }
    (output_dir / "source_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> None:
    args = parse_args()
    config_path = args.config.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    config = read_json(config_path)
    base_model = load_module(
        ROOT / "scripts" / "design_eo_vapor_test_cell.py", "eo_error_control_base_model"
    )
    plates = plate_screen(config)
    minimums = minimum_plate_thicknesses(config)
    edge = edge_screen(config)
    apertures = aperture_regression_design(config)
    surface = surface_and_signal_screen(config, base_model)
    measurement = measurement_screen(config, surface)
    budget = error_budget_frame(config)
    audit = validate(config, plates, edge, surface, measurement, budget)
    summary = build_summary(
        config, plates, minimums, edge, surface, measurement, budget
    )

    paths = {
        "plates": output_dir / "wall_thickness_screen.csv",
        "edge": output_dir / "edge_band_screen.csv",
        "apertures": output_dir / "aperture_regression_design.csv",
        "budget": output_dir / "error_budget.csv",
        "summary": output_dir / "decision_summary.json",
        "audit": output_dir / "audit.json",
        "figure": output_dir / "wall_and_edge_error_controls.png",
        "report": output_dir / "REPORT.md",
    }
    plates.to_csv(paths["plates"], index=False)
    edge.to_csv(paths["edge"], index=False)
    apertures.to_csv(paths["apertures"], index=False)
    budget.to_csv(paths["budget"], index=False)
    paths["summary"].write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    paths["audit"].write_text(
        json.dumps({"checks": audit, "status": "PASS"}, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    build_figure(plates, edge, paths["figure"])
    paths["report"].write_text(
        build_report(config, summary, plates, edge), encoding="utf-8"
    )
    outputs = list(paths.values())
    write_manifest(config_path, output_dir, outputs)
    print(
        json.dumps(
            {
                "status": "PASS",
                "output_dir": str(output_dir),
                "selected_outer_wall_mm": summary["selected_construction"][
                    "outer_load_plate"
                ]["thickness_mm"],
                "selected_peek_plate_mm": summary["selected_construction"][
                    "insulating_cartridge_plate"
                ]["thickness_mm"],
                "planning_rss_error_percent": summary[
                    "planning_root_sum_square_error_percent"
                ],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
