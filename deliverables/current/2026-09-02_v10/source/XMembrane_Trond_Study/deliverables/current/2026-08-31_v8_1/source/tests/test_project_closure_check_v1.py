from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest


@pytest.fixture(scope="module")
def closure_module():
    path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "run_project_closure_check_v1.py"
    )
    spec = importlib.util.spec_from_file_location(
        "test_project_closure_check_script", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_resolution_classification_keeps_numeric_ceiling_unresolved(
    closure_module,
):
    classify = closure_module.classify_replay_resolution
    assert classify(
        replay_pass=False,
        transport_complete=False,
        failure_reason="above_internal_current_search_ceiling",
    ) == "NUMERICAL_OR_LOCAL_SOLUTION_FAILURE"
    assert classify(
        replay_pass=False,
        transport_complete=False,
        failure_reason="boundary_surface_diagnostic_incomplete",
    ) == "NUMERICAL_OR_LOCAL_SOLUTION_FAILURE"
    assert classify(
        replay_pass=False,
        transport_complete=False,
        failure_reason="below_reversible_voltage",
    ) == "PHYSICAL_NO_COMMON_VOLTAGE_AT_THIS_COORDINATE"


def test_repeated_numeric_failure_is_not_convergence(closure_module):
    cases = pd.DataFrame(
        [
            {
                "case_id": "full_duty_2v",
                "case_role": "hard_voltage_stress_point",
                "segment_count": count,
                "transport_solution_complete": False,
                "required_active_area_m2": float("nan"),
                "resolution_status": "NUMERICAL_OR_LOCAL_SOLUTION_FAILURE",
            }
            for count in (32, 64)
        ]
    )
    config = {
        "common_voltage_replay": {
            "segment_counts": [32, 64],
            "selected_segment_count": 64,
        },
        "audit_tolerances": {"segment_area_relative_change": 0.005},
    }
    result = closure_module.build_segment_convergence(cases, config).iloc[0]
    assert bool(result["numerical_failure_present"])
    assert not bool(result["convergence_pass"])
    assert not bool(result["model_closure_relevant"])


def test_material_schema_rejects_duplicate_ids(closure_module):
    ids = [f"MAT-{index:02d}" for index in range(1, 10)]
    valid = pd.DataFrame({"requirement_id": ids})
    duplicate = valid.copy()
    duplicate.loc[8, "requirement_id"] = "MAT-08"
    assert closure_module.material_requirement_schema_valid(valid)
    assert not closure_module.material_requirement_schema_valid(duplicate)


def test_candidate_completion_requires_one_same_sample_id(closure_module):
    frame = pd.DataFrame(
        {
            "requirement_id": [f"MAT-{index:02d}" for index in range(1, 10)],
            "candidate_value_or_source": ["measured"] * 9,
            "data_status": ["verified"] * 9,
        }
    )
    assert not closure_module.material_candidate_data_complete(
        frame, same_sample_required=True
    )
    frame["candidate_sample_id"] = "batch-A"
    assert closure_module.material_candidate_data_complete(
        frame, same_sample_required=True
    )
    frame.loc[8, "candidate_sample_id"] = "batch-B"
    assert not closure_module.material_candidate_data_complete(
        frame, same_sample_required=True
    )


def test_receiver_and_practical_contracts_validate_ranges(closure_module):
    receiver = {
        "architecture_id": "balanced-exhaust",
        "inlet_temperature_c": 28.0,
        "inlet_relative_humidity": 0.5,
        "flow_ratio": 1.0,
        "regeneration_or_disposal_route": "exhaust",
        "measured_sec_kwh_per_kg": 0.05,
    }
    assert closure_module.receiver_contract_valid(receiver)
    assert not closure_module.receiver_contract_valid(
        {**receiver, "inlet_relative_humidity": 1.2}
    )
    practical = {
        "maximum_active_area_m2": 5000.0,
        "maximum_channel_pressure_drop_pa_each_side": 200.0,
        "maximum_module_footprint_m3": 10.0,
        "maximum_installed_cost": 1.0e6,
        "currency": "NOK",
    }
    assert closure_module.practical_limits_valid(practical)
    assert not closure_module.practical_limits_valid(
        {**practical, "maximum_active_area_m2": -1.0}
    )


def test_uniform_replay_cannot_pass_on_selected_step_alone(closure_module):
    config = {
        "uniform_current_convergence": {
            "area_steps_m2": [20.0, 10.0, 5.0],
            "selected_area_step_m2": 5.0,
            "anchors": [{}, {}, {}],
        }
    }
    selected_only = pd.DataFrame(
        {
            "area_step_m2": [5.0] * 3,
            "area_convergence_pass": [True] * 3,
        }
    )
    assert not closure_module.uniform_current_replay_converged(
        selected_only, config
    )
    comparison = pd.DataFrame(
        {
            "area_step_m2": [10.0] * 3,
            "area_convergence_pass": [True] * 3,
        }
    )
    assert closure_module.uniform_current_replay_converged(comparison, config)


def test_input_snapshot_detects_tampering(closure_module, tmp_path):
    path = tmp_path / "input.csv"
    path.write_text("a,b\n1,2\n", encoding="utf-8")
    records = closure_module.snapshot_inputs([path])
    closure_module.assert_inputs_unchanged(records)
    path.write_text("a,b\n1,3\n", encoding="utf-8")
    with pytest.raises(closure_module.ClosureCheckError):
        closure_module.assert_inputs_unchanged(records)
