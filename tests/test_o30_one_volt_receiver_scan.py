from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    ROOT
    / "scripts"
    / "scan_wp1_o30_one_volt_receiver_boundary_v1.py"
)


def load_script():
    name = "_o30_one_volt_receiver_scan_test"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load scan script")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_grid_enforces_voltage_and_multiplier_domains():
    module = load_script()

    points = module.build_points(
        [1.0, 0.8, 1.0],
        [1.2, 1.01, 1.2],
        voltage_cap_v=1.0,
    )

    assert len(points) == 4
    assert points[-1].search_point_id == "O30_V1_R1.2"
    assert [
        (
            point.terminal_voltage_v,
            point.receiver_capacity_multiplier,
        )
        for point in points
    ] == [
        (0.8, 1.01),
        (1.0, 1.01),
        (0.8, 1.2),
        (1.0, 1.2),
    ]

    with pytest.raises(ValueError):
        module.build_points(
            [1.001],
            [1.01],
            voltage_cap_v=1.0,
        )

    with pytest.raises(ValueError):
        module.build_points(
            [1.0],
            [1.0],
            voltage_cap_v=1.0,
        )


def test_context_copy_preserves_modules_and_isolates_config():
    module = load_script()
    marker = math
    context = {
        "base": {"channel": {}},
        "cfg12": {"channel": {}},
        "args": SimpleNamespace(area_max_m2=9000.0),
        "v2": marker,
    }

    copied = module.selective_context_copy(context)
    module.apply_fixed_geometry(copied)

    assert copied["v2"] is marker
    assert context["base"]["channel"] == {}
    assert copied["base"]["channel"]["process_gap_m"] == 0.002
    assert (
        copied["cfg12"]["channel"][
            "active_sides_per_process_channel"
        ]
        == 2.0
    )


def test_gate_evaluation_rejects_each_hard_limit():
    module = load_script()
    point = module.SearchPoint(1.0, 1.05)
    base = {
        "analysis_pass": True,
        "stack_feasible": True,
        "required_active_area_m2": 8999.0,
        "maximum_local_current_density_a_m2": 20.0,
        "process_inlet_humidity_ratio_kg_kg_da": 0.024,
        "process_outlet_humidity_ratio_kg_kg_da": 0.009,
        "target_humidity_ratio_kg_kg_da": 0.009,
    }

    passing = module.evaluate_gates(
        base,
        point=point,
        current_cap_a_m2=21.0,
        area_cap_m2=9000.0,
        declared_cell_voltage_cap_v=1.0,
    )
    assert passing["all_declared_gates_pass"]
    assert passing["normalized_target_shortfall"] == 0.0
    assert passing["target_removal_fraction"] == 1.0

    over_area = module.evaluate_gates(
        {**base, "required_active_area_m2": 9000.1},
        point=point,
        current_cap_a_m2=21.0,
        area_cap_m2=9000.0,
        declared_cell_voltage_cap_v=1.0,
    )
    assert not over_area["area_gate_pass"]
    assert not over_area["all_declared_gates_pass"]

    over_current = module.evaluate_gates(
        {
            **base,
            "maximum_local_current_density_a_m2": 21.1,
        },
        point=point,
        current_cap_a_m2=21.0,
        area_cap_m2=9000.0,
        declared_cell_voltage_cap_v=1.0,
    )
    assert not over_current["current_gate_pass"]

    over_voltage = module.evaluate_gates(
        base,
        point=module.SearchPoint(1.01, 1.05),
        current_cap_a_m2=21.0,
        area_cap_m2=9000.0,
        declared_cell_voltage_cap_v=1.0,
    )
    assert not over_voltage["declared_cell_voltage_gate_pass"]


def test_selection_prefers_feasible_then_minimum_core_power():
    module = load_script()

    rows = [
        {
            "search_point_id": "near",
            "all_declared_gates_pass": False,
            "native_analysis_pass": True,
            "stack_gate_pass": True,
            "normalized_constraint_excess": 0.001,
            "analysis_core_power_kw": 1.0,
        },
        {
            "search_point_id": "feasible_high_power",
            "all_declared_gates_pass": True,
            "native_analysis_pass": True,
            "stack_gate_pass": True,
            "normalized_constraint_excess": 0.0,
            "analysis_core_power_kw": 20.0,
            "analysis_receiver_to_process_dry_air_ratio": 1.0,
        },
        {
            "search_point_id": "feasible_low_power",
            "all_declared_gates_pass": True,
            "native_analysis_pass": True,
            "stack_gate_pass": True,
            "normalized_constraint_excess": 0.0,
            "analysis_core_power_kw": 10.0,
            "analysis_receiver_to_process_dry_air_ratio": 2.0,
        },
    ]

    selected = module.select_best_row(rows)
    assert selected["search_point_id"] == "feasible_low_power"


def test_selection_ranks_failed_native_points_by_excess():
    module = load_script()
    rows = [
        {
            "search_point_id": "far",
            "all_declared_gates_pass": False,
            "native_analysis_pass": True,
            "stack_gate_pass": True,
            "normalized_constraint_excess": 0.2,
            "analysis_core_power_kw": 5.0,
        },
        {
            "search_point_id": "near",
            "all_declared_gates_pass": False,
            "native_analysis_pass": True,
            "stack_gate_pass": True,
            "normalized_constraint_excess": 0.1,
            "analysis_core_power_kw": 10.0,
        },
    ]

    selected = module.select_best_row(rows)
    assert selected["search_point_id"] == "near"


def test_failed_selection_prefers_target_approach_before_power():
    module = load_script()
    rows = [
        {
            "search_point_id": "low_power_far_from_target",
            "all_declared_gates_pass": False,
            "native_analysis_pass": False,
            "stack_gate_pass": True,
            "normalized_target_shortfall": 0.14,
            "normalized_constraint_excess": 0.0,
            "analysis_core_power_kw": 50.0,
        },
        {
            "search_point_id": "high_power_near_target",
            "all_declared_gates_pass": False,
            "native_analysis_pass": False,
            "stack_gate_pass": True,
            "normalized_target_shortfall": 0.03,
            "normalized_constraint_excess": 0.0,
            "analysis_core_power_kw": 73.0,
        },
    ]

    selected = module.select_best_row(rows)
    assert selected["search_point_id"] == "high_power_near_target"
