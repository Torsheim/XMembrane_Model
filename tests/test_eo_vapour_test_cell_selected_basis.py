"""Regression tests for the selected EO vapour test-cell design note."""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "build_eo_vapour_test_cell_selected_basis.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = load_module(SCRIPT_PATH, "eo_vapour_test_cell_selected_basis")


def test_selected_basis_reproduces_the_design_numbers() -> None:
    values = MODULE.calculate_basis()

    assert math.isclose(values["active_area_cm2"], 25.0)
    assert math.isclose(values["net_volume_ml"], 500.0)
    assert math.isclose(values["segment_s"], 12.0)
    assert values["polarity_sequence"] == [1, -1, -1, 1]
    assert math.isclose(values["rate_mg_s"], 13.0 / 90.0)
    assert math.isclose(values["transferred_mg"], 26.0 / 15.0)
    assert math.isclose(values["rh_change_pp"], 10.261449905170393)
    assert math.isclose(values["rigid_dp_pa"], 976.446882367501)


def test_selected_geometry_closes_at_the_calibrated_volume() -> None:
    values = MODULE.calculate_basis()

    assert math.isclose(values["bulk_footprint_width_mm"], 165.0)
    assert math.isclose(values["bulk_footprint_height_mm"], 165.0)
    assert math.isclose(values["bulk_depth_mm"], 20.0)
    assert math.isclose(values["gross_volume_ml"], 544.5)
    assert math.isclose(values["pretrim_net_volume_ml"], 521.9)
    assert math.isclose(values["nominal_trim_ml"], 21.9)
    assert math.isclose(
        values["gross_volume_ml"]
        - values["component_bound_ml"]
        - values["nominal_trim_ml"],
        values["net_volume_ml"],
    )


def test_selected_instrument_and_pressure_diagnostics() -> None:
    values = MODULE.calculate_basis()

    assert math.isclose(values["sensor_step_fraction"], 0.950212931632136)
    assert math.isclose(values["sensor_ramp_fraction"], 0.6832623561226214)
    assert math.isclose(values["diaphragm_travel_ml"], 2.396917965820757)
    assert math.isclose(values["diaphragm_full_stroke_ml"], 4.793717655854346)


def test_cli_writes_editable_source_and_word_document(
    tmp_path: Path, monkeypatch
) -> None:
    output = tmp_path / "selected_basis"
    optional_args = [] if MODULE.DOCX_AVAILABLE else ["--skip-docx"]
    monkeypatch.setattr(
        "sys.argv",
        [
            "build_eo_vapour_test_cell_selected_basis.py",
            "--output-dir",
            str(output),
            "--skip-pdf",
            *optional_args,
        ],
    )
    MODULE.main()

    markdown = output / f"{MODULE.DOCUMENT_STEM}.md"
    assert markdown.is_file()
    blueprint_png = output / "figures" / f"{MODULE.BLUEPRINT_STEM}.png"
    blueprint_svg = output / "figures" / f"{MODULE.BLUEPRINT_STEM}.svg"
    assert blueprint_png.is_file()
    assert blueprint_svg.is_file()
    blueprint_text = blueprint_svg.read_text(encoding="utf-8")
    assert "FUNCTIONAL SECTION" in blueprint_text
    assert "REMOVABLE MEMBRANE CARTRIDGE" in blueprint_text
    assert "DIFFERENTIAL PRESSURE" in blueprint_text
    if MODULE.DOCX_AVAILABLE:
        assert (output / f"{MODULE.DOCUMENT_STEM}.docx").is_file()
    assert (output / "calculation_basis.json").is_file()
    assert (output / "source_manifest.json").is_file()
    text = markdown.read_text(encoding="utf-8")
    assert "50 x 50 mm = 25 cm²" in text
    assert "500 ± 5 mL per side" in text
    assert "12 s segments" in text
