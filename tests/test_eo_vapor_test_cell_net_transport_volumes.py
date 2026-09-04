"""Regression tests for the sealed-cell net-transport volume comparison."""

from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "analyze_eo_vapor_test_cell_net_transport_volumes.py"
CONFIG_PATH = ROOT / "config" / "eo_vapor_test_cell_net_transport_volume_study.json"
BASE_PATH = ROOT / "config" / "eo_vapor_test_cell_design.json"
BASE_MODEL_PATH = ROOT / "scripts" / "design_eo_vapor_test_cell.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = load_module(SCRIPT_PATH, "net_transport_volume_study")
BASE_MODEL = load_module(BASE_MODEL_PATH, "eo_test_cell_base_model_for_net_transport")
STUDY = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
BASE = json.loads(BASE_PATH.read_text(encoding="utf-8"))


def test_volume_cases_preserve_the_fixed_membrane_and_target_rate() -> None:
    MODULE.validate(STUDY, BASE)
    cases = MODULE.build_cases(STUDY, BASE, BASE_MODEL).set_index("case")

    assert set(cases["active_membrane_area_cm2"]) == {25.0}
    assert all(math.isclose(value, 13.0 / 90.0) for value in cases["integrated_water_rate_mg_s"])
    assert all(math.isclose(value, 13.0 / 18.0) for value in cases["water_transferred_per_segment_mg"])


def test_compact_and_large_cases_reproduce_the_declared_tradeoff() -> None:
    cases = MODULE.build_cases(STUDY, BASE, BASE_MODEL).set_index("case")
    compact = cases.loc["Kompakt transientcelle"]
    large = cases.loc["Lavdriftcelle"]

    assert math.isclose(compact["calibrated_net_volume_ml_per_side"], 200.0)
    assert math.isclose(compact["square_bulk_footprint_side_mm"], 110.56672193747991)
    assert math.isclose(compact["single_chamber_rh_change_pp"], 10.689010317885824)
    assert math.isclose(compact["rigid_chamber_differential_pressure_pa"], 1017.1321691328133)

    assert math.isclose(large["calibrated_net_volume_ml_per_side"], 500.0)
    assert math.isclose(large["square_bulk_footprint_side_mm"], 165.0)
    assert math.isclose(large["single_chamber_rh_change_pp"], 4.27560412715433)
    assert math.isclose(large["duration_to_planning_rh_signal_s"], 11.694253844141082)
    assert compact["single_chamber_rh_change_pp"] > large["single_chamber_rh_change_pp"]
    assert compact["square_bulk_footprint_side_mm"] < large["square_bulk_footprint_side_mm"]


def test_cli_writes_the_numeric_table_and_presentation_figure(tmp_path: Path, monkeypatch) -> None:
    output = tmp_path / "net_transport"
    monkeypatch.setattr(
        "sys.argv",
        [
            "analyze_eo_vapor_test_cell_net_transport_volumes.py",
            "--output-dir",
            str(output),
        ],
    )
    MODULE.main()

    assert (output / "net_transport_volume_tradeoff.png").is_file()
    assert (output / "volume_cases.csv").is_file()
    assert (output / "SUMMARY.md").is_file()
    assert (output / "source_manifest.json").is_file()
    summary = (output / "SUMMARY.md").read_text(encoding="utf-8")
    assert "110.6" in summary
    assert "165.0" in summary
