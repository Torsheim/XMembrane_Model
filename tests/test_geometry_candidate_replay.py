from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    ROOT
    / "scripts"
    / "replay_wp1_legacy_geometry_candidates_v1.py"
)


def load_script():
    name = "_geometry_candidate_replay_test"
    spec = importlib.util.spec_from_file_location(
        name,
        SCRIPT,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def fake_context():
    return {
        "base": {
            "channel": {
                "process_gap_m": 0.001,
                "receiver_gap_m": 0.001,
                "process_velocity_m_s": 2.0,
                "active_sides_per_process_channel": 1.0,
                "receiver_geometry_mode": (
                    "aligned_equal_total_width"
                ),
            }
        },
        "cfg12": {
            "channel": {
                "active_sides_per_process_channel": 1.0,
                "receiver_geometry_mode": (
                    "aligned_equal_total_width"
                ),
            },
            "operating": {
                "current_density_cap_a_m2": 21.0,
            },
            "voltage_grid": {
                "maximum_cell_terminal_voltage_v": 1.0,
            },
        },
        "args": SimpleNamespace(area_max_m2=9000.0),
        "v2": math,
    }


def test_candidate_constants_are_locked():
    module = load_script()

    assert [
        candidate.candidate_id
        for candidate in module.CANDIDATES
    ] == [
        "legacy_O30_case_94",
        "legacy_O50_case_310",
    ]

    assert (
        module.CANDIDATES[0].terminal_voltage_v
        > 1.0
    )
    assert (
        module.CANDIDATES[1].terminal_voltage_v
        < 1.0
    )


def test_selective_copy_preserves_module_and_config():
    module = load_script()
    original = fake_context()

    copied = module.selective_context_copy(
        original
    )
    module.apply_candidate_geometry(
        copied,
        module.CANDIDATES[0],
    )

    assert copied["v2"] is math
    assert (
        original["base"]["channel"][
            "process_gap_m"
        ]
        == 0.001
    )
    assert (
        copied["base"]["channel"][
            "process_gap_m"
        ]
        == 0.002
    )


def test_cell_voltage_gate_is_independent():
    module = load_script()
    context = fake_context()
    row = {
        "analysis_pass": True,
        "stack_feasible": True,
        "maximum_local_current_density_a_m2": 17.0,
        "required_active_area_m2": 8000.0,
    }

    o30 = module.evaluate_declared_gates(
        row,
        candidate=module.CANDIDATES[0],
        context=context,
        workflow_voltage_max_v=24.0,
    )
    o50 = module.evaluate_declared_gates(
        row,
        candidate=module.CANDIDATES[1],
        context=context,
        workflow_voltage_max_v=24.0,
    )

    assert not o30[
        "declared_cell_voltage_gate_pass"
    ]
    assert not o30["all_declared_gates_pass"]

    assert o50[
        "declared_cell_voltage_gate_pass"
    ]
    assert o50["all_declared_gates_pass"]
