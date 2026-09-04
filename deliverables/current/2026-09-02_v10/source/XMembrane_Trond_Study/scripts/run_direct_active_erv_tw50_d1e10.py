#!/usr/bin/env python3
"""Run the combined t_w=50, D=1e-10 m2/s active-ERV case."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE_CONFIG = ROOT / "config/direct_eo_erv_study_v1.json"
RUNNER_PATH = ROOT / "scripts/run_direct_eo_erv_study_v1.py"
OUTPUT = ROOT / "outputs/direct_active_erv_tw50_d1e10_v1"


def load_runner():
    spec = importlib.util.spec_from_file_location("direct_eo_erv_runner", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import runner from {RUNNER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    config = json.loads(BASE_CONFIG.read_text(encoding="utf-8"))
    material = copy.deepcopy(config["materials"]["terminal1_anchor"])
    material["name"] = "combined_tw50_d1e10"
    material["water_drag"] = 50.0
    material["water_diffusivity_m2_s"] = 1.0e-10
    material["interpretation"] = (
        "Combined sensitivity point: water drag 50 and diffusivity 1e-10 m2/s; "
        "all other membrane fields at the Terminal-1 anchor."
    )
    config["study_id"] = "direct-active-erv-tw50-d1e10-v1-2026-09-02"
    config["title"] = "Direct active EO-in-ERV combined t_w=50, D=1e-10 case"
    config["materials"] = {material["name"]: material}
    config["electrical"]["maximum_terminal_voltage_v"] = 1.0
    config["electrical"]["preferred_terminal_voltage_v"] = 1.0
    config["electrical"]["default_series_asr_ohm_m2"] = 1.0e-5
    scenario = {
        "material_ids": [material["name"]],
        "process_outlet_w_g_kg_da": [7.26028059345441],
        "terminal_voltages_v": [0.1, 0.25, 0.5, 1.0],
        "segment_counts": [4, 8],
        "sensible_effectiveness_values": [0.75],
        "film_scale_factors": [1.0],
        "electric_heat_scenario_ids": ["external_rejection"],
    }
    for mode in config["modes"]:
        config["modes"][mode] = copy.deepcopy(scenario)

    OUTPUT.mkdir(parents=True, exist_ok=True)
    config_path = OUTPUT / "config_tw50_d1e10.json"
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    load_runner().run(config_path, OUTPUT, "study", True)


if __name__ == "__main__":
    main()
