from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "make_wp1_o30_required_area_1v_v1.py"


def load_script():
    name = "_o30_required_area_1v_test"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load required-area script")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def valid_row(**overrides):
    row = {
        "status": "target_reached",
        "target_reached": True,
        "target_capacity_sufficient": True,
        "required_active_area_m2": 10500.0,
        "process_outlet_humidity_ratio_kg_kg_da": 0.009,
        "target_humidity_ratio_kg_kg_da": 0.009,
        "local_solver_evaluated": True,
        "minimum_local_flux_mol_m2_s": 0.001,
        "maximum_local_current_density_a_m2": 999.0,
        "countercurrent_boundary_solution_valid": True,
        "receiver_boundary_pass": True,
        "water_balance_evaluated": True,
        "water_balance_pass": True,
        "process_mass_balance_relative_error": 1.0e-12,
        "receiver_mass_balance_relative_error": -1.0e-12,
        "shortened_endpoint_resolved": True,
        "maximum_terminal_voltage_error_v": 1.0e-11,
        "eo_grid_power_kw": 70.0,
        "process_channel_fan_power_kw": 1.0,
        "receiver_channel_fan_power_kw": 2.0,
        "analysis_core_power_kw": 73.0,
        "worker_exception": "",
    }
    row.update(overrides)
    return row


def test_multiplier_grid_is_sorted_unique_and_above_unity():
    module = load_script()
    assert module.normalize_receiver_multipliers([3.0, 1.01, 3.0]) == (
        1.01,
        3.0,
    )
    with pytest.raises(ValueError):
        module.normalize_receiver_multipliers([1.0])
    with pytest.raises(ValueError):
        module.normalize_receiver_multipliers([math.inf])


def test_required_area_validity_has_no_current_or_design_area_gate():
    module = load_script()
    row = valid_row(
        maximum_local_current_density_a_m2=50000.0,
        required_active_area_m2=12000.0,
    )
    validity = module.required_area_validity(
        row,
        integration_ceiling_m2=15000.0,
    )
    assert validity["required_area_solution_valid"]

    decorated = module.decorate_result(
        row,
        receiver_multiplier=3.0,
        integration_area_step_m2=20.0,
        integration_ceiling_m2=15000.0,
        solver_current_safety_guard_a_m2=1.0e6,
        area_reference_m2=9000.0,
        contract_sha256="test",
    )
    assert not decorated["current_density_acceptance_gate_applied"]
    assert not decorated["design_area_cap_applied"]
    assert decorated["area_delta_vs_reference_m2"] == 3000.0
    assert decorated["required_area_solution_valid"]


@pytest.mark.parametrize(
    ("field", "value", "failed_check"),
    [
        ("target_reached", False, "target_reached_validity_pass"),
        ("water_balance_pass", False, "water_balance_validity_pass"),
        (
            "receiver_boundary_pass",
            False,
            "countercurrent_boundary_validity_pass",
        ),
        ("minimum_local_flux_mol_m2_s", 0.0, "positive_transport_direction_validity_pass"),
        ("worker_exception", "boom", "worker_exception_absent_validity_pass"),
    ],
)
def test_required_area_validity_rejects_numerically_invalid_rows(
    field,
    value,
    failed_check,
):
    module = load_script()
    validity = module.required_area_validity(
        valid_row(**{field: value}),
        integration_ceiling_m2=15000.0,
    )
    assert not validity["required_area_solution_valid"]
    assert failed_check in validity["required_area_invalid_reasons"]


def test_tradeoff_selection_does_not_collapse_area_and_power_objectives():
    module = load_script()
    rows = [
        {
            "receiver_capacity_multiplier": 1.01,
            "required_active_area_m2": 12140.0,
            "analysis_core_power_kw": 73.58,
            "required_area_solution_valid": True,
        },
        {
            "receiver_capacity_multiplier": 3.0,
            "required_active_area_m2": 10500.0,
            "analysis_core_power_kw": 76.13,
            "required_area_solution_valid": True,
        },
    ]
    minimum_area, minimum_power = module.choose_tradeoff_rows(rows)
    assert minimum_area["receiver_capacity_multiplier"] == 3.0
    assert minimum_power["receiver_capacity_multiplier"] == 1.01


def test_step_halving_convergence_uses_relative_area_difference():
    module = load_script()
    nominal = {
        "receiver_capacity_multiplier": 3.0,
        "integration_area_step_m2": 20.0,
        "required_active_area_m2": 10499.7174159,
        "required_area_solution_valid": True,
    }
    refined = {
        "receiver_capacity_multiplier": 3.0,
        "integration_area_step_m2": 10.0,
        "required_active_area_m2": 10499.6769649,
        "required_area_solution_valid": True,
    }
    metrics = module.convergence_metrics(
        nominal,
        refined,
        relative_tolerance=1.0e-4,
    )
    assert metrics["absolute_area_difference_m2"] == pytest.approx(
        0.040451,
        abs=1.0e-9,
    )
    assert metrics["relative_area_difference"] == pytest.approx(
        3.8526e-6,
        rel=1.0e-4,
    )
    assert metrics["step_halving_convergence_pass"]


def test_frozen_required_area_curve_preserves_no_gate_contract_and_result():
    curve = pd.read_csv(
        ROOT / "data" / "golden" / "o30" / "required_area_1v_curve_v1.csv"
    )
    convergence = pd.read_csv(
        ROOT
        / "data"
        / "golden"
        / "o30"
        / "required_area_1v_convergence_v1.csv"
    )

    assert len(curve) == 8
    assert curve["required_area_solution_valid"].all()
    assert not curve["current_density_acceptance_gate_applied"].any()
    assert not curve["design_area_cap_applied"].any()
    assert curve["required_active_area_m2"].min() == pytest.approx(
        10499.7174158979
    )
    assert curve.loc[
        curve["required_active_area_m2"].idxmin(),
        "receiver_capacity_multiplier",
    ] == pytest.approx(3.0)
    assert curve["analysis_core_power_kw"].idxmin() == curve.index[0]

    assert convergence.loc[0, "refined_required_active_area_m2"] == pytest.approx(
        10499.6769649072
    )
    assert convergence.loc[0, "step_halving_convergence_pass"]
