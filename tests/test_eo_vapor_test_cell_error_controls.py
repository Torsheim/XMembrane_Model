"""Regression tests for the EO test-cell error-control design."""

from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "analyze_eo_vapor_test_cell_error_controls.py"
CONFIG_PATH = ROOT / "config" / "eo_vapor_test_cell_error_control_design.json"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = load_module(SCRIPT_PATH, "eo_vapor_test_cell_error_controls")
CONFIG = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
BASE_MODEL = load_module(
    ROOT / "scripts" / "design_eo_vapor_test_cell.py",
    "eo_error_control_test_base_model",
)


def build_results():
    plates = MODULE.plate_screen(CONFIG)
    edge = MODULE.edge_screen(CONFIG)
    surface = MODULE.surface_and_signal_screen(CONFIG, BASE_MODEL)
    measurement = MODULE.measurement_screen(CONFIG, surface)
    budget = MODULE.error_budget_frame(CONFIG)
    return plates, edge, surface, measurement, budget


def test_selected_wall_and_insulating_plate_meet_the_five_micron_screen() -> None:
    plates, _, _, _, _ = build_results()
    selected = plates[plates["selected"]].set_index("component")

    assert math.isclose(selected.loc["outer_load_plate", "thickness_mm"], 12.0)
    assert math.isclose(
        selected.loc["outer_load_plate", "pressure_only_deflection_um"],
        1.3301411410546882,
    )
    assert math.isclose(
        selected.loc["insulating_cartridge_plate", "thickness_mm"], 20.0
    )
    assert math.isclose(
        selected.loc[
            "insulating_cartridge_plate", "pressure_only_deflection_um"
        ],
        4.513911806248399,
    )
    assert selected["passes_pressure_only_deflection_limit"].all()


def test_edge_and_wall_storage_terms_are_explicitly_bounded() -> None:
    _, edge, surface, measurement, budget = build_results()
    one_mm = edge.loc[edge["edge_band_width_mm"] == 1.0].iloc[0]

    assert math.isclose(one_mm["edge_affected_fraction_percent"], 7.84)
    assert math.isclose(surface["conservative_internal_surface_area_m2_per_side"], 0.06765)
    assert math.isclose(surface["conditional_segment_signal_mg"], 26.0 / 15.0)
    assert math.isclose(surface["one_nm_equivalent_water_film_mg"], 0.06765)
    assert math.isclose(
        surface["allowed_equivalent_reversible_water_film_change_nm"],
        0.25622074402562206,
    )
    assert math.isclose(
        measurement["volume_measurement_scale_uncertainty_percent"], 0.2
    )
    assert math.isclose(
        math.sqrt(sum(value**2 for value in budget["allocation_percent"])),
        3.3634060117684275,
    )


def test_design_validation_passes() -> None:
    plates, edge, surface, measurement, budget = build_results()
    checks = MODULE.validate(CONFIG, plates, edge, surface, measurement, budget)

    assert all(checks.values())


def test_cli_writes_traceable_engineering_outputs(tmp_path: Path, monkeypatch) -> None:
    output = tmp_path / "error_controls"
    monkeypatch.setattr(
        "sys.argv",
        [
            "analyze_eo_vapor_test_cell_error_controls.py",
            "--output-dir",
            str(output),
        ],
    )
    MODULE.main()

    required = {
        "wall_thickness_screen.csv",
        "edge_band_screen.csv",
        "aperture_regression_design.csv",
        "error_budget.csv",
        "decision_summary.json",
        "audit.json",
        "wall_and_edge_error_controls.png",
        "REPORT.md",
        "source_manifest.json",
    }
    assert required <= {path.name for path in output.iterdir()}
    report = (output / "REPORT.md").read_text(encoding="utf-8")
    assert "12 mm EN AW-6082-T6 aluminium" in report
    assert "20 mm unfilled PEEK" in report
    assert "R = J_area A + J_edge P" in report
