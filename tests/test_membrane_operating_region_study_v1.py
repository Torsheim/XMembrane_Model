from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "membrane_operating_region_study_v1.json"
OUTPUT = ROOT / "outputs" / "membrane_operating_region_study_v1"
DIRECT = OUTPUT / "direct_eo_analysis" / "per_cap_robust_register.csv"
POST_AUDIT = OUTPUT / "post_erv" / "audit.json"
POST_DENSE = OUTPUT / "post_erv" / "post_erv_dense_dj_cases.csv"
POST_GLOBAL = OUTPUT / "post_erv" / "post_erv_global_inverse_design_cases.csv"
POST_PRCC = OUTPUT / "post_erv" / "post_erv_global_prcc.csv"
POST_ANALYZER = ROOT / "scripts" / "analyze_post_erv_inverse_design_v1.py"
COMBINED_AUDIT = OUTPUT / "study_audit.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_manifest_has_no_current_density_acceptance_limit():
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    policy = config["current_density_policy"]
    assert policy["engineering_current_density_limit_a_m2"] is None
    assert policy["current_density_is_sampling_or_control_axis"] is True
    assert config["system_closure_policy"]["missing_receiver_energy_status"] == "UNKNOWN"
    assert config["system_closure_policy"]["full_system_claim_allowed"] is False


@pytest.mark.skipif(not DIRECT.is_file(), reason="direct-EO analysis has not been run")
def test_direct_dense_grid_and_v55_cap_consequence_are_explicit():
    frame = pd.read_csv(DIRECT, low_memory=False)
    dense = frame[frame["source_study"].eq("dense_local")].copy()
    assert len(dense) == 1320
    assert set(dense["cell_voltage_cap_tested_v"].unique()) == {3.0, 5.0}

    v55 = dense[
        np.isclose(dense["current_density_a_m2"], 50.0)
        & np.isclose(dense["transport_number_reference_t_w"], 75.0)
        & np.isclose(dense["water_diffusivity_scale_vs_pfsa"], 0.6)
    ].sort_values("cell_voltage_cap_tested_v")
    assert len(v55) == 2
    robust = v55["per_cap_robust_pass"].astype(bool).tolist()
    assert robust == [False, True]
    assert np.allclose(v55["cell_voltage_required_max_v"], 3.177365, atol=2e-6)


@pytest.mark.skipif(not POST_AUDIT.is_file(), reason="post-ERV study has not finished")
def test_post_erv_audit_keeps_censoring_and_system_unknown():
    audit = json.loads(POST_AUDIT.read_text(encoding="utf-8"))
    assert audit["pass"] is True
    assert audit["archive_regression_pass"] is True
    assert audit["dense_case_count"] == 33 * 34
    assert audit["global_lhs_case_count"] == 512
    assert audit["engineering_current_density_limit_a_m2"] is None
    assert audit["no_21_a_m2_gate_applied"] is True
    assert audit["full_system_status"] == "UNKNOWN"
    assert audit["full_system_status_unknown_everywhere"] is True
    assert audit["dense_area_right_censored_count"] > 0
    assert audit["surface_margin_endpoint_definition_pass"] is True
    assert audit["target_reached_saving_mask_pass"] is True
    assert audit["dense_censored_strictly_above_target"] is True
    assert audit["global_censored_strictly_above_target"] is True
    assert audit["observed_area_prcc_target_reached_only"] is True
    assert audit["capped_area_prcc_excludes_unobserved_rows"] is True
    assert audit["censor_prcc_uses_reached_or_censored"] is True
    assert audit["finite_balance_counts_match_target_counts"] is True
    assert audit["deterministic_case_ids_and_axes_pass"] is True
    assert audit["sampled_coordinate_parameterization_explicit"] is True


@pytest.mark.skipif(
    not all(path.is_file() for path in (POST_AUDIT, POST_DENSE, POST_GLOBAL, POST_PRCC)),
    reason="post-ERV study has not finished",
)
def test_post_erv_area_and_sensitivity_populations_exclude_solver_placeholders():
    audit = json.loads(POST_AUDIT.read_text(encoding="utf-8"))
    for path in (POST_DENSE, POST_GLOBAL):
        frame = pd.read_csv(path, low_memory=False)
        target = frame["target_reached"].astype(bool)
        censored = frame["area_is_right_censored"].astype(bool)
        observed_or_censored = target | censored
        assert not (target & censored).any()
        assert frame["required_active_area_censored_m2"].notna().equals(
            observed_or_censored
        )
        assert frame.loc[~observed_or_censored, "area_observation_status"].eq(
            "NOT_OBSERVED"
        ).all()

    global_frame = pd.read_csv(POST_GLOBAL, low_memory=False)
    prcc = pd.read_csv(POST_PRCC)
    expected_counts = {
        "incremental_saving_kw_vs_passive_erv": int(
            global_frame["target_reached"].astype(bool).sum()
        ),
        "required_active_area_m2": int(
            global_frame["target_reached"].astype(bool).sum()
        ),
        "required_active_area_censored_m2": int(
            (
                global_frame["target_reached"].astype(bool)
                | global_frame["area_is_right_censored"].astype(bool)
            ).sum()
        ),
        "area_censoring_numeric": int(
            (
                global_frame["target_reached"].astype(bool)
                | global_frame["area_is_right_censored"].astype(bool)
            ).sum()
        ),
        "transport_gate_numeric": len(global_frame),
    }
    for output, expected in expected_counts.items():
        counts = prcc.loc[prcc["output"].eq(output), "complete_case_count"].unique()
        assert counts.tolist() == [expected]

    assert audit["script_sha256"] == sha256(POST_ANALYZER)
    assert audit["central_manifest_sha256"] == sha256(CONFIG)


@pytest.mark.skipif(not COMBINED_AUDIT.is_file(), reason="combined audit has not been run")
def test_combined_audit_counts_physical_states_without_cap_duplication():
    audit = json.loads(COMBINED_AUDIT.read_text(encoding="utf-8"))
    assert audit["pass"] is True
    assert audit["direct_dense_cap_rows"] == 1320
    assert audit["direct_dense_physical_states"] == 660
    assert audit["direct_global_cap_rows"] == 46080
    assert audit["direct_global_physical_states"] == 11520
    assert audit["current_density_acceptance_limit_a_m2"] is None
    assert audit["full_system_status"] == "UNKNOWN"


def test_top_level_runner_is_non_destructive_and_reuses_complete_components():
    module = load_module(
        ROOT / "scripts" / "run_membrane_operating_region_study_v1.py",
        "_membrane_region_runner_test",
    )
    assert module.directory_is_empty(ROOT / "path-that-does-not-exist")
    assert module.DEFAULT_OUTPUT == OUTPUT
