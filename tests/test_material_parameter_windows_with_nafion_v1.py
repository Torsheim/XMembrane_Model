from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "make_material_parameter_windows_with_nafion_v1.py"
CONFIG = ROOT / "config" / "material_parameter_windows_with_nafion_v1.json"


def materialized_sources_available() -> bool:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    for raw_path in config["sources"].values():
        path = Path(raw_path)
        if not path.is_absolute():
            path = ROOT / path
        if not path.is_file():
            return False
    return True


def load_module():
    spec = importlib.util.spec_from_file_location("_material_windows_with_nafion_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_config_forbids_joint_recipe_and_full_system_claim():
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    assert config["direct_eo"]["primary_voltage_cap_v"] == 2.0
    assert config["direct_eo"]["preferred_voltage_cap_v"] == 1.8
    assert config["claim_boundary"]["full_system_claim_allowed"] is False
    assert config["claim_boundary"]["parameter_marginal_extrema_may_be_combined"] is False
    assert config["claim_boundary"]["nafion_is_validated_for_heiq_device"] is False


@pytest.mark.skipif(
    not materialized_sources_available(),
    reason="Materialized parameter-window evidence and sibling references are absent",
)
def test_material_windows_are_reproducible_and_nafion_is_off_axis(tmp_path: Path):
    module = load_module()
    output = tmp_path / "material-windows"
    audit = module.run(CONFIG, output)
    assert audit["status"] == "PASS"
    assert all(row["passed"] for row in audit["checks"])

    metrics = audit["metrics"]
    assert metrics["direct_coordinates"] == 2508
    assert metrics["direct_2v_passes"] == 178
    assert metrics["direct_1p8v_passes"] == 108
    assert metrics["direct_2v_core_rows"] == 72
    assert metrics["direct_1p8v_core_rows"] == 48
    assert metrics["direct_broad_rows"] == 11520
    assert metrics["direct_broad_2v_passes"] == 1296
    assert metrics["direct_broad_1p8v_passes"] == 1116
    assert metrics["direct_broad_core_rows"] == 384
    assert metrics["direct_broad_retention_1p0_passes"] == 0
    assert metrics["post_conditional_passes"] == 646
    assert metrics["post_surface_direction_passes"] == 0
    assert 3.39 < metrics["nafion_direct_d_scale_at_lambda_8"] < 3.40
    assert metrics["nafion_direct_d_scale_min"] > metrics["direct_2v_d_max"]
    assert metrics["nafion_drag_max"] < metrics["direct_2v_tw_min"]
    assert metrics["nafion_adapter_reference_activity"] == pytest.approx(0.8)
    assert metrics["nafion_adapter_d_ref"] == pytest.approx(1.2803084564002419e-10)
    assert metrics["nafion_adapter_d_exponent"] == pytest.approx(-1.53238701042103)
    assert metrics["nafion_adapter_conductivity_ref"] == pytest.approx(2.5695340057747007)
    assert metrics["nafion_adapter_conductivity_exponent"] == pytest.approx(0.997284990686209)
    assert metrics["nafion_adapter_d_max_relative_error"] == pytest.approx(0.32300433150259)
    assert metrics["nafion_adapter_conductivity_max_relative_error"] == pytest.approx(0.12772341581092883)
    assert metrics["full_system_claim_allowed"] is False
    assert len(audit["sources"]) == 12
    assert len(audit["outputs"]) == 22

    cases = pd.read_csv(output / "nafion_reference_case_register.csv")
    curve = pd.read_csv(output / "nafion_property_curve_register.csv")
    fit_audit = pd.read_csv(output / "nafion_v14_powerlaw_fit_audit.csv")
    assert len(cases) == 12
    assert len(curve) == 501
    assert len(fit_audit) == 3
    assert set(fit_audit["property_name"]) == {
        "conductivity_s_m",
        "water_diffusivity_m2_s",
        "water_capacity_mol_m3_activity",
    }
    assert not cases["validated_for_heiq_device"].astype(bool).any()

    stems = [
        "01_direct_eo_joint_window_with_nafion",
        "02_direct_eo_energy_window_fixed_loss",
        "03_post_erv_dj_window_with_nafion",
        "04_simultaneous_property_gap_vs_nafion",
        "05_nafion_reference_vs_v5_internal_laws",
        "06_broad_6axis_direct_eo_window_with_nafion",
    ]
    for stem in stems:
        assert (output / f"{stem}.png").stat().st_size > 10_000
        assert (output / f"{stem}.pdf").stat().st_size > 5_000


def test_boolean_parser_rejects_unknown_and_missing_tokens():
    module = load_module()
    assert module._as_bool(pd.Series([1, 0, 1], name="numeric")).tolist() == [True, False, True]
    assert module._as_bool(pd.Series(["yes", "false", "1"], name="text")).tolist() == [True, False, True]
    with pytest.raises(ValueError, match="invalid tokens"):
        module._as_bool(pd.Series(["true", "maybe"], name="unknown"))
    with pytest.raises(ValueError, match="invalid tokens"):
        module._as_bool(pd.Series(["true", None], name="missing"))
