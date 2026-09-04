#!/usr/bin/env python3
"""Dimension the integrated sealed two-chamber EO vapour test-cell concept."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


WATER_VAPOUR_GAS_CONSTANT_J_KG_K = 461.495
UNIVERSAL_GAS_CONSTANT_J_MOL_K = 8.31446261815324
WATER_MOLAR_MASS_KG_MOL = 0.01801528


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Calculate and verify the integrated sealed EO vapour cell."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=root / "config" / "eo_vapor_test_cell_design.json",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=root
        / "reports"
        / "test_cell_handoff_supplement_2026-09-03"
        / "calculations",
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def saturation_pressure_water_pa(temperature_c: float) -> float:
    """Buck saturation pressure over liquid water in pascals."""

    return 611.21 * math.exp(
        (18.678 - temperature_c / 234.5)
        * (temperature_c / (257.14 + temperature_c))
    )


def saturated_water_vapour_density_kg_m3(temperature_c: float) -> float:
    return saturation_pressure_water_pa(temperature_c) / (
        WATER_VAPOUR_GAS_CONSTANT_J_KG_K * (temperature_c + 273.15)
    )


def validate_config(config: dict[str, Any]) -> None:
    cell = config["integrated_sealed_cell"]
    state = config["operating_state"]
    volumes = cell["chamber_net_free_gas_volumes_ml"]
    basis = cell["volume_sizing_basis"]
    region = cell["membrane_region"]
    protocol = cell["transient_protocol"]
    release = cell["fabrication_release"]
    register = cell["engineering_register"]
    selected = float(basis["selected_net_free_gas_volume_ml_per_side"])

    if not math.isclose(float(volumes["A"]), float(volumes["B"]), abs_tol=1e-12):
        raise ValueError("Chambers A and B require equal calibrated net volumes")
    if not math.isclose(float(volumes["A"]), selected, abs_tol=1e-12):
        raise ValueError("Chamber volumes must equal the selected sizing volume")
    if selected <= 0.0:
        raise ValueError("Net free-gas volume must be positive")
    if float(region["width_mm"]) <= 0.0 or float(region["height_mm"]) <= 0.0:
        raise ValueError("Membrane-region dimensions must be positive")
    if any(float(gap) <= 0.0 for gap in region["local_gap_options_mm"]):
        raise ValueError("Local gap options must be positive")
    initial_rh = float(state["initial_relative_humidity_percent"])
    if not 0.0 < initial_rh < 100.0:
        raise ValueError("Initial relative humidity must lie between 0 and 100 percent")
    frequency = float(basis["switching_frequency_hz"])
    half_cycle = float(basis["half_cycle_duration_s"])
    segment = float(protocol["segment_duration_s"])
    if not math.isclose(half_cycle, 0.5 / frequency, rel_tol=1e-12):
        raise ValueError("Half-cycle duration must equal 0.5 / switching frequency")
    if not math.isclose(segment, half_cycle, rel_tol=1e-12):
        raise ValueError("Transient segment duration must equal the sizing half-cycle")
    if protocol["polarity_sequence"] != [1, -1, -1, 1]:
        raise ValueError("The released transient protocol is the ABBA polarity sequence")

    register_by_item = {row["item"]: row for row in register}
    if len(register_by_item) != len(register):
        raise ValueError("Engineering-register item identifiers must be unique")
    allowed_statuses = {"open", "defined", "closed"}
    if any(row.get("status") not in allowed_statuses for row in register):
        raise ValueError("Engineering-register status must be open, defined or closed")
    if any(not str(row.get("closure_evidence", "")).strip() for row in register):
        raise ValueError("Every engineering-register item requires closure evidence")

    required_items = list(release["required_register_items"])
    if not isinstance(release.get("ready"), bool):
        raise ValueError("Fabrication-release readiness must be a Boolean")
    if len(set(required_items)) != len(required_items):
        raise ValueError("Fabrication-release register identifiers must be unique")
    missing_items = sorted(set(required_items) - set(register_by_item))
    if missing_items:
        raise ValueError(
            f"Fabrication-release register is missing required items: {missing_items}"
        )
    if bool(release["ready"]) and any(
        register_by_item[item]["status"] != "closed" for item in required_items
    ):
        raise ValueError(
            "Fabrication release cannot be ready while a required register item is not closed"
        )

    unresolved = release["unresolved_dimensions"]
    if bool(release["ready"]) and any(value is None for value in unresolved.values()):
        raise ValueError(
            "Fabrication release cannot be ready while physical dimensions remain unresolved"
        )


def membrane_area_m2(config: dict[str, Any]) -> float:
    region = config["integrated_sealed_cell"]["membrane_region"]
    return float(region["width_mm"]) * float(region["height_mm"]) * 1.0e-6


def integrated_target_water_rate_mg_s(config: dict[str, Any]) -> float:
    validate_config(config)
    flux = float(
        config["integrated_sealed_cell"]["volume_sizing_basis"][
            "target_net_water_flux_g_m2_h"
        ]
    )
    return flux * membrane_area_m2(config) * 1000.0 / 3600.0


def required_net_volume_ml_per_side(config: dict[str, Any]) -> float:
    validate_config(config)
    basis = config["integrated_sealed_cell"]["volume_sizing_basis"]
    transferred_kg = (
        integrated_target_water_rate_mg_s(config)
        * float(basis["half_cycle_duration_s"])
        / 1.0e6
    )
    allowed_fraction = (
        float(basis["maximum_single_chamber_rh_change_percentage_points"]) / 100.0
    )
    density = saturated_water_vapour_density_kg_m3(
        float(config["operating_state"]["temperature_c"])
    )
    return transferred_kg / (density * allowed_fraction) * 1.0e6


def build_integrated_volume_basis_frame(config: dict[str, Any]) -> pd.DataFrame:
    validate_config(config)
    cell = config["integrated_sealed_cell"]
    region = cell["membrane_region"]
    basis = cell["volume_sizing_basis"]
    gross = cell["gross_cavity_accounting"]
    selected_ml = float(basis["selected_net_free_gas_volume_ml_per_side"])
    required_ml = required_net_volume_ml_per_side(config)
    rate_mg_s = integrated_target_water_rate_mg_s(config)
    duration_s = float(basis["half_cycle_duration_s"])
    transferred_mg = rate_mg_s * duration_s
    density = saturated_water_vapour_density_kg_m3(
        float(config["operating_state"]["temperature_c"])
    )
    drift_pp = transferred_mg / 1.0e6 / (density * selected_ml / 1.0e6) * 100.0
    area_mm2 = float(region["width_mm"]) * float(region["height_mm"])

    rows = []
    for gap_mm in region["local_gap_options_mm"]:
        local_ml = area_mm2 * float(gap_mm) / 1000.0
        rows.append(
            {
                "chamber_pair": "A=B",
                "membrane_width_mm": float(region["width_mm"]),
                "membrane_height_mm": float(region["height_mm"]),
                "local_gap_mm": float(gap_mm),
                "local_membrane_region_volume_ml_per_side": local_ml,
                "bulk_free_gas_volume_ml_per_side": selected_ml - local_ml,
                "calibrated_net_free_gas_volume_ml_per_side": selected_ml,
                "gross_empty_cavity_volume_ml_per_side": gross[
                    "gross_empty_cavity_volume_ml_per_side"
                ],
                "installed_component_displacement_ml_per_side": gross[
                    "installed_component_displacement_ml_per_side"
                ],
                "gross_cavity_depth_mm_per_side": gross[
                    "gross_cavity_depth_mm_per_side"
                ],
                "target_net_water_flux_g_m2_h": float(
                    basis["target_net_water_flux_g_m2_h"]
                ),
                "target_net_water_rate_mg_s": rate_mg_s,
                "target_net_water_rate_mg_h": rate_mg_s * 3600.0,
                "water_transferred_per_half_cycle_mg": transferred_mg,
                "half_cycle_duration_s": duration_s,
                "allowed_single_chamber_rh_change_percentage_points": float(
                    basis["maximum_single_chamber_rh_change_percentage_points"]
                ),
                "required_net_free_gas_volume_ml_per_side": required_ml,
                "selected_to_required_volume_ratio": selected_ml / required_ml,
                "predicted_single_chamber_rh_change_percentage_points": drift_pp,
                "predicted_chamber_differential_rh_change_percentage_points": 2.0
                * drift_pp,
            }
        )
    return pd.DataFrame(rows)


def build_interconnect_volume_budget_frame(config: dict[str, Any]) -> pd.DataFrame:
    """Header/port/tap budget kept separate from total chamber inventory."""

    validate_config(config)
    cell = config["integrated_sealed_cell"]
    region = cell["membrane_region"]
    mechanical = cell["mechanical_starting_values"]
    budget = cell["interconnect_header_port_budget"]
    width_mm = float(region["width_mm"])
    nominal_gap_mm = float(region["nominal_gap_mm"])
    header_ml = (
        float(budget["triangular_header_count_per_side"])
        * 0.5
        * width_mm
        * float(budget["triangular_header_length_mm"])
        * nominal_gap_mm
        / 1000.0
    )
    port_radius_mm = 0.5 * float(mechanical["port_bore_inner_diameter_mm"])
    port_ml = (
        float(mechanical["port_bore_count_per_side"])
        * math.pi
        * port_radius_mm**2
        * float(mechanical["port_bore_length_mm"])
        / 1000.0
    )
    tap_ml = float(budget["pressure_tap_volume_ml_per_side"])
    total_ml = header_ml + port_ml + tap_ml
    return pd.DataFrame(
        [
            {
                "nominal_local_gap_mm": nominal_gap_mm,
                "triangular_header_volume_ml_per_side": header_ml,
                "port_bore_volume_ml_per_side": port_ml,
                "pressure_tap_volume_ml_per_side": tap_ml,
                "interconnect_header_port_volume_ml_per_side": total_ml,
                "maximum_interconnect_header_port_volume_ml_per_side": float(
                    budget["maximum_volume_ml_per_side"]
                ),
                "interconnect_volume_target_pass": total_ml
                <= float(budget["maximum_volume_ml_per_side"]),
                "calibrated_net_free_gas_volume_ml_per_side": float(
                    cell["volume_sizing_basis"][
                        "selected_net_free_gas_volume_ml_per_side"
                    ]
                ),
            }
        ]
    )


def _signed_exposure_seconds(
    time_s: float, polarity_sequence: list[int], segment_duration_s: float
) -> float:
    exposure_s = 0.0
    remaining_s = max(0.0, time_s)
    for polarity in polarity_sequence:
        interval_s = min(remaining_s, segment_duration_s)
        exposure_s += float(polarity) * interval_s
        remaining_s -= interval_s
        if remaining_s <= 0.0:
            break
    return exposure_s


def build_integrated_transient_frame(config: dict[str, Any]) -> pd.DataFrame:
    validate_config(config)
    cell = config["integrated_sealed_cell"]
    protocol = cell["transient_protocol"]
    state = config["operating_state"]
    sequence = [int(value) for value in protocol["polarity_sequence"]]
    segment_s = float(protocol["segment_duration_s"])
    sample_s = float(protocol["sample_interval_s"])
    end_s = len(sequence) * segment_s
    count = int(round(end_s / sample_s))
    volume_ml = float(
        cell["volume_sizing_basis"]["selected_net_free_gas_volume_ml_per_side"]
    )
    volume_m3 = volume_ml / 1.0e6
    temperature_c = float(state["temperature_c"])
    temperature_k = temperature_c + 273.15
    density = saturated_water_vapour_density_kg_m3(temperature_c)
    initial_mass_mg = (
        density
        * volume_m3
        * float(state["initial_relative_humidity_percent"])
        / 100.0
        * 1.0e6
    )
    rate_mg_s = integrated_target_water_rate_mg_s(config)

    rows = []
    for index in range(count + 1):
        time_s = index * sample_s
        exposure_s = _signed_exposure_seconds(time_s, sequence, segment_s)
        transferred_mg = rate_mg_s * exposure_s
        mass_a_mg = initial_mass_mg - transferred_mg
        mass_b_mg = initial_mass_mg + transferred_mg
        rh_a = mass_a_mg / 1.0e6 / (density * volume_m3) * 100.0
        rh_b = mass_b_mg / 1.0e6 / (density * volume_m3) * 100.0
        pressure_pa = (
            2.0
            * transferred_mg
            / 1.0e6
            / WATER_MOLAR_MASS_KG_MOL
            * UNIVERSAL_GAS_CONSTANT_J_MOL_K
            * temperature_k
            / volume_m3
        )
        segment_index = min(int(time_s // segment_s), len(sequence) - 1)
        rows.append(
            {
                "time_s": time_s,
                "segment_index": segment_index + 1,
                "polarity": sequence[segment_index],
                "signed_exposure_s": exposure_s,
                "signed_water_transferred_A_to_B_mg": transferred_mg,
                "water_inventory_A_mg": mass_a_mg,
                "water_inventory_B_mg": mass_b_mg,
                "total_water_inventory_mg": mass_a_mg + mass_b_mg,
                "relative_humidity_A_percent": rh_a,
                "relative_humidity_B_percent": rh_b,
                "differential_relative_humidity_B_minus_A_percentage_points": rh_b
                - rh_a,
                "gas_only_differential_pressure_B_minus_A_pa": pressure_pa,
            }
        )
    return pd.DataFrame(rows)


def build_integrated_engineering_register_frame(config: dict[str, Any]) -> pd.DataFrame:
    validate_config(config)
    return pd.DataFrame(config["integrated_sealed_cell"]["engineering_register"])


def write_summary(
    path: Path,
    config: dict[str, Any],
    volumes: pd.DataFrame,
    transient: pd.DataFrame,
    register: pd.DataFrame,
    interconnect: pd.DataFrame,
) -> None:
    basis = volumes.iloc[0]
    peak = transient.loc[transient["time_s"].eq(float(basis["half_cycle_duration_s"]))].iloc[0]
    open_items = register.loc[register["status"].eq("open"), "item"].tolist()
    release = config["integrated_sealed_cell"]["fabrication_release"]
    link = interconnect.iloc[0]
    path.write_text(
        f"""# Integrated sealed EO vapour test-cell calculation

Status: engineering concept; fabrication release is blocked by open evidence gates.

The selected cell has equal sealed chambers A and B separated by a 50 x 50 mm membrane region. Each assembled side has a governing **500.0 +/- 5.0 mL net free-gas target**. Local gap inserts provide 1, 2 and 4 mm spacing. Traceable physical calibration remains open.

## Derived volume basis

- Target flux: {basis['target_net_water_flux_g_m2_h']:.1f} g m-2 h-1 over 25 cm2.
- Target rate: {basis['target_net_water_rate_mg_h']:.1f} mg/h.
- Water transferred in {basis['half_cycle_duration_s']:.1f} s: {basis['water_transferred_per_half_cycle_mg']:.6f} mg.
- Allowable change: {basis['allowed_single_chamber_rh_change_percentage_points']:.1f} RH percentage points per chamber.
- Calculated minimum net volume: {basis['required_net_free_gas_volume_ml_per_side']:.1f} mL per chamber.
- Selected/required volume ratio: {basis['selected_to_required_volume_ratio']:.3f}.
- Predicted first-segment change: {basis['predicted_single_chamber_rh_change_percentage_points']:.3f} percentage points per chamber.

The 1, 2 and 4 mm local membrane regions contain 2.5, 5.0 and 10.0 mL per side. Their corresponding bulk free-gas volumes are 497.5, 495.0 and 490.0 mL. Local plus bulk equals the 500.0 mL net-volume target. Gross empty-cavity volume closes from `gross = net + installed displacement`.

The nominal header/port/pressure-tap budget is {link['interconnect_header_port_volume_ml_per_side']:.6f} mL per side against its {link['maximum_interconnect_header_port_volume_ml_per_side']:.1f} mL allocation. This budget is an identified portion of chamber geometry and a separate quantity from the total net free-gas volume.

## Transient inventory

At {peak['time_s']:.1f} s, chamber A is {peak['relative_humidity_A_percent']:.3f}% RH and chamber B is {peak['relative_humidity_B_percent']:.3f}% RH. The chamber difference is {peak['differential_relative_humidity_B_minus_A_percentage_points']:.3f} percentage points. The analytic ABBA sequence conserves total water and returns both chambers to 50.000% RH at 20 s. The gas-only pressure diagnostic at the first extremum is {peak['gas_only_differential_pressure_B_minus_A_pa']:.1f} Pa.

## Engineering register

Fabrication release is **not ready**. The {len(open_items)} open items are: {', '.join(open_items)}. Every required item must be closed with cited evidence before `fabrication_release.ready` may be set to true. Closure evidence is recorded in `integrated_sealed_cell_engineering_register.csv`; unresolved physical dimensions remain null in the governing configuration.
""",
        encoding="utf-8",
    )


def make_transient_plot(path: Path, transient: pd.DataFrame) -> None:
    fig, (ax_rh, ax_mass) = plt.subplots(2, 1, figsize=(7.4, 6.2), sharex=True)
    ax_rh.plot(
        transient["time_s"],
        transient["relative_humidity_A_percent"],
        label="Chamber A",
        color="#176B87",
    )
    ax_rh.plot(
        transient["time_s"],
        transient["relative_humidity_B_percent"],
        label="Chamber B",
        color="#D97706",
    )
    ax_rh.set_ylabel("Relative humidity (%)")
    ax_rh.legend()
    ax_rh.grid(True, alpha=0.25)
    ax_mass.plot(
        transient["time_s"],
        transient["water_inventory_A_mg"],
        label="Inventory A",
        color="#176B87",
    )
    ax_mass.plot(
        transient["time_s"],
        transient["water_inventory_B_mg"],
        label="Inventory B",
        color="#D97706",
    )
    ax_mass.set_xlabel("Time (s)")
    ax_mass.set_ylabel("Water-vapour inventory (mg)")
    ax_mass.legend()
    ax_mass.grid(True, alpha=0.25)
    fig.suptitle("Integrated sealed two-chamber transient")
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def write_audit_and_manifest(
    output_dir: Path,
    config_path: Path,
    config: dict[str, Any],
    volumes: pd.DataFrame,
    transient: pd.DataFrame,
    register: pd.DataFrame,
    interconnect: pd.DataFrame,
    generated_paths: list[Path],
) -> None:
    repo_root = Path(__file__).resolve().parents[1]

    def source_path(path: Path) -> str:
        resolved = path.resolve()
        try:
            return resolved.relative_to(repo_root).as_posix()
        except ValueError:
            return resolved.name

    initial = transient.iloc[0]
    final = transient.iloc[-1]
    initial_total = float(initial["total_water_inventory_mg"])
    delta_a = transient["water_inventory_A_mg"] - float(initial["water_inventory_A_mg"])
    delta_b = transient["water_inventory_B_mg"] - float(initial["water_inventory_B_mg"])
    chambers = config["integrated_sealed_cell"]["chamber_net_free_gas_volumes_ml"]
    release = config["integrated_sealed_cell"]["fabrication_release"]
    required_items = set(release["required_register_items"])
    register_by_item = register.set_index("item")
    checks = {
        "declared_outputs_exist_and_are_nonempty": all(
            item.is_file() and item.stat().st_size > 0 for item in generated_paths
        ),
        "chamber_design_targets_are_symmetric_500_ml_net": math.isclose(
            float(chambers["A"]), 500.0, abs_tol=1e-12
        )
        and math.isclose(float(chambers["B"]), 500.0, abs_tol=1e-12),
        "local_gap_volumes_are_2p5_5_10_ml": volumes[
            "local_membrane_region_volume_ml_per_side"
        ].tolist()
        == [2.5, 5.0, 10.0],
        "local_plus_bulk_equals_net": bool(
            (
                volumes["local_membrane_region_volume_ml_per_side"]
                + volumes["bulk_free_gas_volume_ml_per_side"]
                - volumes["calibrated_net_free_gas_volume_ml_per_side"]
            ).abs().max()
            < 1e-12
        ),
        "selected_volume_meets_switching_drift_basis": bool(
            (
                volumes["predicted_single_chamber_rh_change_percentage_points"]
                <= volumes[
                    "allowed_single_chamber_rh_change_percentage_points"
                ]
            ).all()
        ),
        "transient_total_water_is_conserved": bool(
            (transient["total_water_inventory_mg"] - initial_total).abs().max()
            < 1e-12
        ),
        "transient_chamber_changes_are_equal_and_opposite": bool(
            (delta_a + delta_b).abs().max() < 1e-12
        ),
        "abba_sequence_returns_to_initial_state": math.isclose(
            float(final["signed_water_transferred_A_to_B_mg"]), 0.0, abs_tol=1e-12
        )
        and math.isclose(
            float(final["relative_humidity_A_percent"]), 50.0, abs_tol=1e-12
        )
        and math.isclose(
            float(final["relative_humidity_B_percent"]), 50.0, abs_tol=1e-12
        ),
        "gross_cavity_dimensions_are_registered_open": volumes[
            "gross_empty_cavity_volume_ml_per_side"
        ].isna().all()
        and bool(
            (
                register["item"].eq("gross_empty_cavity_volume_and_depth")
                & register["status"].eq("open")
            ).any()
        ),
        "fabrication_release_is_explicitly_gated": not bool(release["ready"])
        and required_items.issubset(set(register_by_item.index))
        and bool(
            (register_by_item.loc[sorted(required_items), "status"] == "open").all()
        ),
        "unresolved_physical_dimensions_are_null": all(
            value is None for value in release["unresolved_dimensions"].values()
        ),
        "net_volume_is_a_defined_target_with_open_calibration": bool(
            (
                register["item"].eq("net_free_gas_volume_target")
                & register["status"].eq("defined")
            ).any()
        )
        and bool(
            (
                register["item"].eq("net_volume_calibration")
                & register["status"].eq("open")
            ).any()
        ),
        "interconnect_header_port_budget_passes": bool(
            interconnect.iloc[0]["interconnect_volume_target_pass"]
        ),
    }
    audit = {
        "schema_version": 2,
        "study_id": config["study_id"],
        "all_pass": all(checks.values()),
        "checks": checks,
        "numerical_result": {
            "required_net_volume_ml_per_side": required_net_volume_ml_per_side(config),
            "selected_net_volume_target_ml_per_side": 500.0,
            "predicted_single_chamber_drift_percentage_points": float(
                volumes.iloc[0][
                    "predicted_single_chamber_rh_change_percentage_points"
                ]
            ),
            "peak_gas_only_differential_pressure_pa": float(
                transient["gas_only_differential_pressure_B_minus_A_pa"].abs().max()
            ),
        },
        "release_status": config["integrated_sealed_cell"]["status"],
    }
    write_json(output_dir / "audit.json", audit)
    if not audit["all_pass"]:
        failed = [name for name, passed in checks.items() if not passed]
        raise RuntimeError(f"Integrated cell audit failed: {failed}")

    bound = [*generated_paths, output_dir / "audit.json"]
    manifest = {
        "schema_version": 2,
        "study_id": config["study_id"],
        "sources": [
            {"path": source_path(config_path), "sha256": sha256(config_path)},
            {
                "path": source_path(Path(__file__)),
                "sha256": sha256(Path(__file__)),
            },
        ],
        "generated_outputs": [
            {
                "path": item.resolve().relative_to(output_dir.resolve()).as_posix(),
                "sha256": sha256(item),
                "size_bytes": item.stat().st_size,
            }
            for item in bound
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
    validate_config(config)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    volumes = build_integrated_volume_basis_frame(config)
    transient = build_integrated_transient_frame(config)
    register = build_integrated_engineering_register_frame(config)
    interconnect = build_interconnect_volume_budget_frame(config)

    volumes.to_csv(args.output_dir / "integrated_sealed_cell_volume_basis.csv", index=False)
    transient.to_csv(args.output_dir / "integrated_sealed_cell_transient.csv", index=False)
    register.to_csv(
        args.output_dir / "integrated_sealed_cell_engineering_register.csv", index=False
    )
    interconnect.to_csv(
        args.output_dir / "interconnect_header_port_volume_budget.csv", index=False
    )
    write_json(args.output_dir / "config_used.json", config)
    write_summary(
        args.output_dir / "SUMMARY.md",
        config,
        volumes,
        transient,
        register,
        interconnect,
    )
    make_transient_plot(
        args.output_dir / "integrated_sealed_cell_transient.png", transient
    )

    generated_paths = [
        args.output_dir / name
        for name in (
            "integrated_sealed_cell_volume_basis.csv",
            "integrated_sealed_cell_transient.csv",
            "integrated_sealed_cell_engineering_register.csv",
            "interconnect_header_port_volume_budget.csv",
            "config_used.json",
            "SUMMARY.md",
            "integrated_sealed_cell_transient.png",
        )
    ]
    write_audit_and_manifest(
        args.output_dir,
        args.config,
        config,
        volumes,
        transient,
        register,
        interconnect,
        generated_paths,
    )
    print(f"Wrote integrated sealed-cell study to {args.output_dir}")


if __name__ == "__main__":
    main()
