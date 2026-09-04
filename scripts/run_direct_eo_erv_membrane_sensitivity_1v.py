#!/usr/bin/env python3
"""One-at-a-time membrane-property sensitivity for EO operating in the ERV.

The sweep retains the canonical shared-core boundary, full humidity duty,
external EO-heat rejection, and a 1 V terminal-voltage cap.  Material
properties are varied one at a time around the inverse-design anchor.  ASR is
run as separate canonical-runner invocations because it is an electrical
boundary in the v1 runner rather than a material field.
"""

from __future__ import annotations

import argparse
import copy
import csv
import importlib.util
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE_CONFIG = ROOT / "config" / "direct_eo_erv_study_v1.json"
DEFAULT_OUTPUT = ROOT / "outputs" / "direct_active_erv_material_sensitivity_1v"
RUNNER_PATH = ROOT / "scripts" / "run_direct_eo_erv_study_v1.py"

FULL_DUTY_W = 7.26028059345441
VOLTAGES = [0.1, 0.25, 0.5, 1.0]
SEGMENTS = [4, 8]


def load_runner():
    spec = importlib.util.spec_from_file_location("direct_eo_erv_runner", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import runner from {RUNNER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def material_variants(base: dict) -> tuple[dict[str, dict], dict[str, tuple[str, float]]]:
    anchor = copy.deepcopy(base["materials"]["terminal1_anchor"])
    axes = {
        "water_transport_number": ("water_drag", [25.0, 50.0, 75.0, anchor["water_drag"], 125.0, 150.0]),
        "water_diffusivity_m2_s": ("water_diffusivity_m2_s", [1e-15, anchor["water_diffusivity_m2_s"], 1e-13, 1e-12, 1e-11, 1e-10]),
        "wet_conductivity_s_m": ("conductivity_s_m", [5.0, 10.0, anchor["conductivity_s_m"], 40.0, 60.0]),
        "dry_thickness_um": ("dry_thickness_um", [20.0, 30.0, anchor["dry_thickness_um"], 50.0, 75.0]),
        "water_capacity_mol_m3_activity": ("water_capacity_mol_m3_activity", [2500.0, 5000.0, anchor["water_capacity_mol_m3_activity"], 20000.0]),
    }
    materials: dict[str, dict] = {}
    metadata: dict[str, tuple[str, float]] = {}
    seen: set[tuple[str, float]] = set()
    for axis, (field, values) in axes.items():
        for value in values:
            key = (axis, float(value))
            if key in seen:
                continue
            seen.add(key)
            material_id = f"oat_{axis}_{float(value):.8g}".replace("+", "p").replace("-", "m").replace(".", "p")
            material = copy.deepcopy(anchor)
            material["name"] = material_id
            material[field] = float(value)
            material["interpretation"] = f"OAT sensitivity: {axis}={value}; all other membrane fields at anchor."
            materials[material_id] = material
            metadata[material_id] = (axis, float(value))
    return materials, metadata


def configure(base: dict, materials: dict, asr: float) -> dict:
    config = copy.deepcopy(base)
    config["study_id"] = "direct-active-erv-material-sensitivity-1v-2026-09-01"
    config["title"] = "Direct active EO-in-ERV membrane sensitivity with 1 V cap"
    config["materials"] = materials
    config["electrical"]["maximum_terminal_voltage_v"] = 1.0
    config["electrical"]["preferred_terminal_voltage_v"] = 1.0
    config["electrical"]["default_series_asr_ohm_m2"] = float(asr)
    scenario = {
        "material_ids": list(materials),
        "process_outlet_w_g_kg_da": [FULL_DUTY_W],
        "terminal_voltages_v": VOLTAGES,
        "segment_counts": SEGMENTS,
        "sensible_effectiveness_values": [0.75],
        "film_scale_factors": [1.0],
        "electric_heat_scenario_ids": ["external_rejection"],
    }
    for mode in config["modes"]:
        config["modes"][mode] = copy.deepcopy(scenario)
    return config


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def finite(row: dict[str, str], field: str) -> bool:
    try:
        return math.isfinite(float(row[field]))
    except (KeyError, TypeError, ValueError):
        return False


def best_refined(rows: list[dict[str, str]]) -> dict[str, str] | None:
    candidates = [
        row for row in rows
        if row["segment_count"] == "8"
        and row["transport_solution_complete"] == "True"
        and row["robust_physics_pass"] == "True"
        and row["conditional_energy_pass"] == "True"
        and finite(row, "conditional_active_total_power_kw")
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda row: float(row["conditional_active_total_power_kw"]))


def write_summary(output: Path, records: list[dict[str, object]]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    fields = [
        "axis", "value", "best_voltage_v", "status", "area_m2",
        "j_min_a_m2", "j_max_a_m2", "eo_grid_power_kw", "fan_power_kw",
        "remaining_ac_power_kw", "total_power_kw", "saving_kw",
        "saving_pct", "stack_feasible", "engineering_screen_pass",
    ]
    with (output / "oat_sensitivity_summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)

    lines = [
        "# Direct active EO-in-ERV: 1 V membrane sensitivity",
        "",
        "One-at-a-time sweep at full humidity duty, 0.75 prescribed sensible effectiveness,",
        "external EO-heat rejection, 8 refined segments, and sampled voltages 0.1/0.25/0.5/1.0 V.",
        "Area is diagnostic, not an acceptance gate. Values are conditional model results.",
        "",
        "| Axis | Value | Best V | Total kW | Saving kW | Area m2 | j range A/m2 | Status |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in records:
        def fmt(name: str, digits: int = 3) -> str:
            value = row[name]
            return "—" if value is None else f"{float(value):.{digits}g}"
        j_range = "—" if row["j_min_a_m2"] is None else f"{fmt('j_min_a_m2')}–{fmt('j_max_a_m2')}"
        lines.append(
            f"| {row['axis']} | {float(row['value']):.6g} | {fmt('best_voltage_v')} | "
            f"{fmt('total_power_kw', 6)} | {fmt('saving_kw', 6)} | {fmt('area_m2', 6)} | "
            f"{j_range} | {row['status']} |"
        )
    (output / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    base = json.loads(BASE_CONFIG.read_text(encoding="utf-8"))
    runner = load_runner()
    materials, metadata = material_variants(base)
    output = args.output.resolve()
    generated = output / "generated_configs"
    generated.mkdir(parents=True, exist_ok=True)

    config = configure(base, materials, 1e-5)
    material_config = generated / "material_oat.json"
    material_config.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    material_root = output / "material_oat"
    runner.run(material_config, material_root, "study", args.overwrite)
    rows = read_rows(material_root / "study" / "case_register.csv")

    records: list[dict[str, object]] = []
    for material_id, (axis, value) in metadata.items():
        selected = best_refined([row for row in rows if row["material_id"] == material_id])
        records.append(record(axis, value, selected))

    anchor = copy.deepcopy(base["materials"]["terminal1_anchor"])
    for asr in [1e-6, 5e-6, 1e-5, 2e-5, 5e-5]:
        asr_config = configure(base, {"terminal1_anchor": anchor}, asr)
        config_path = generated / f"asr_{asr:.0e}.json"
        config_path.write_text(json.dumps(asr_config, indent=2) + "\n", encoding="utf-8")
        asr_root = output / f"asr_{asr:.0e}"
        runner.run(config_path, asr_root, "study", args.overwrite)
        selected = best_refined(read_rows(asr_root / "study" / "case_register.csv"))
        records.append(record("series_asr_ohm_m2", asr, selected))

    axis_order = {
        "water_transport_number": 0,
        "water_diffusivity_m2_s": 1,
        "wet_conductivity_s_m": 2,
        "dry_thickness_um": 3,
        "water_capacity_mol_m3_activity": 4,
        "series_asr_ohm_m2": 5,
    }
    records.sort(key=lambda row: (axis_order[str(row["axis"])], float(row["value"])))
    write_summary(output, records)
    print(output / "SUMMARY.md")
    return 0


def record(axis: str, value: float, row: dict[str, str] | None) -> dict[str, object]:
    if row is None:
        return {
            "axis": axis, "value": value, "best_voltage_v": None,
            "status": "no robust energy-positive full-duty solution",
            "area_m2": None, "j_min_a_m2": None, "j_max_a_m2": None,
            "eo_grid_power_kw": None, "fan_power_kw": None,
            "remaining_ac_power_kw": None, "total_power_kw": None,
            "saving_kw": None, "saving_pct": None,
            "stack_feasible": False, "engineering_screen_pass": False,
        }
    return {
        "axis": axis,
        "value": value,
        "best_voltage_v": float(row["terminal_voltage_v"]),
        "status": "robust energy-positive",
        "area_m2": float(row["required_active_area_m2"]),
        "j_min_a_m2": float(row["minimum_local_current_density_a_m2"]),
        "j_max_a_m2": float(row["maximum_local_current_density_a_m2"]),
        "eo_grid_power_kw": float(row["eo_grid_power_kw"]),
        "fan_power_kw": float(row["selected_active_core_fan_power_kw"]),
        "remaining_ac_power_kw": float(row["remaining_ac_power_kw"]),
        "total_power_kw": float(row["conditional_active_total_power_kw"]),
        "saving_kw": float(row["conditional_saving_kw_vs_passive_erv"]),
        "saving_pct": float(row["conditional_saving_pct_vs_passive_erv"]),
        "stack_feasible": row["stack_feasible"] == "True",
        "engineering_screen_pass": row["engineering_screen_pass"] == "True",
    }


if __name__ == "__main__":
    raise SystemExit(main())
