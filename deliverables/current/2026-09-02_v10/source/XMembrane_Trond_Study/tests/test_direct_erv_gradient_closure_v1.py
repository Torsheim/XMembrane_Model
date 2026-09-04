from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_direct_erv_gradient_closure_v1.py"
CONFIG = ROOT / "config" / "direct_erv_gradient_closure_v1.json"
CASE_REGISTER = (
    ROOT
    / "outputs"
    / "direct_active_eo_erv_study_v1"
    / "study"
    / "case_register.csv"
)
SEGMENT_REGISTER = (
    ROOT
    / "outputs"
    / "direct_active_eo_erv_study_v1"
    / "study"
    / "segment_register.csv.gz"
)


def require_materialized_direct_eo_erv() -> None:
    missing = [path for path in (CASE_REGISTER, SEGMENT_REGISTER) if not path.is_file()]
    if missing:
        pytest.skip(
            "Materialized direct-EO ERV evidence is not part of a clean source checkout: "
            + ", ".join(str(path.relative_to(ROOT)) for path in missing)
        )


def load_runner():
    spec = importlib.util.spec_from_file_location(
        "_direct_erv_gradient_closure_test", RUNNER
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_config_is_quasistatic_and_has_no_area_gate():
    runner = load_runner()
    config = runner.load_config(CONFIG)
    assert config["claim_boundary"]["quasistatic_only"] is True
    assert config["claim_boundary"]["zero_mean_current_not_zero_mean_voltage"] is True
    assert config["claim_boundary"]["area_is_acceptance_gate"] is False
    assert config["claim_boundary"]["transient_ac_predicted"] is False


def test_surface_margin_is_bulk_margin_minus_both_film_losses():
    require_materialized_direct_eo_erv()
    runner = load_runner()
    cases = pd.read_csv(CASE_REGISTER)
    segments = pd.read_csv(SEGMENT_REGISTER)
    case_id = json.loads(CONFIG.read_text(encoding="utf-8"))["cases"][0][
        "case_id"
    ]
    case = cases.loc[cases["case_id"].eq(case_id)].iloc[0]
    profile = segments.loc[segments["case_id"].eq(case_id)]
    result = runner.build_gradient_rows(
        case_label="o30",
        case_row=case,
        profile=profile,
        robust_margin=0.02,
    )
    assert result["surface_identity_error"].abs().max() < 1.0e-12
    critical = result[
        "critical_film_or_area_multiplier_for_zero_surface_margin"
    ].max()
    assert critical == pytest.approx(1.137, rel=2.0e-3)


def test_signed_flux_obeys_source_receiver_and_current_reversal_symmetry():
    runner = load_runner()
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    flux_module = runner.load_module(
        runner.resolve_path(config["signed_flux_source"]),
        "_signed_flux_symmetry_test",
    )
    material = {
        "water_drag": 10.0,
        "water_diffusivity_m2_s": 1.0e-12,
        "water_capacity_mol_m3_activity": 1000.0,
        "dry_thickness_um": 50.0,
        "diffusivity_activity_exponent": 0.0,
        "capacity_activity_exponent": 0.0,
    }

    def flux(source, receiver, current):
        state = flux_module.local_powerlaw_flux(
            source_bulk_activity=np.array([source]),
            receiver_bulk_activity=np.array([receiver]),
            signed_current_density_a_m2=np.array([current]),
            source_film_coefficient=np.array([0.05]),
            receiver_film_coefficient=np.array([0.05]),
            material=material,
            reference_activity=0.5,
        )
        assert bool(state["solver_success"][0])
        return float(state["net_flux_mol_m2_s"][0])

    forward = flux(0.8, 0.4, 2.0)
    reversed_state = flux(0.4, 0.8, -2.0)
    assert reversed_state == pytest.approx(-forward, rel=1.0e-10, abs=1.0e-14)


def test_materialized_closure_passes_and_ac_increment_is_negligible(tmp_path: Path):
    require_materialized_direct_eo_erv()
    runner = load_runner()
    output = tmp_path / "closure"
    audit = runner.run(CONFIG, output, overwrite=False)
    assert audit["status"] == "PASS"
    assert audit["maximum_absolute_rectification_fraction"] < 1.0e-5
    summary = pd.read_csv(output / "case_summary.csv")
    o30 = summary.loc[summary["case_label"].eq("direct_erv_o30")].iloc[0]
    full = summary.loc[
        summary["case_label"].eq("direct_erv_full_duty")
    ].iloc[0]
    assert 1.0 < o30[
        "minimum_common_film_or_area_multiplier_for_zero_surface_margin"
    ] < 2.0
    assert np.isinf(
        full[
            "minimum_common_film_or_area_multiplier_for_zero_surface_margin"
        ]
    )
    signed = pd.read_csv(output / "signed_triplet.csv")
    assert signed[
        [
            "plus_thermodynamic_pass",
            "zero_thermodynamic_pass",
            "minus_thermodynamic_pass",
        ]
    ].astype(bool).to_numpy().all()
    assert (output / "figures" / "01_film_area_gradient_envelope.pdf").is_file()
    assert (output / "figures" / "02_signed_triplet_ac_null.pdf").is_file()
