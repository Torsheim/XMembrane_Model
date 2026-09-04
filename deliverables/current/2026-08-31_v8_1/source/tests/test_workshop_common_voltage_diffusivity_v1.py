from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest


@pytest.fixture(scope="module")
def workshop_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "run_workshop_common_voltage_diffusivity_v1.py"
    spec = importlib.util.spec_from_file_location(
        "test_workshop_common_voltage_diffusivity_script", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_real_config_has_bounded_axes_and_no_engineering_gates(workshop_module):
    root = Path(__file__).resolve().parents[1]
    config = workshop_module.read_json(
        root / "config" / "workshop_common_voltage_diffusivity_v1.json"
    )
    workshop_module.validate_config(config)
    assert min(config["water_diffusivity_m2_s"]) == pytest.approx(1.0e-14)
    assert max(config["water_diffusivity_m2_s"]) == pytest.approx(1.0e-9)
    assert max(config["terminal_voltages_v"]) <= 2.0
    assert config["transport"]["engineering_current_density_limit_a_m2"] is None
    assert config["transport"]["area_is_acceptance_gate"] is False


def test_feasibility_does_not_use_area_current_or_surface_direction(workshop_module):
    result = {
        "transport_solution_complete": True,
        "transport_water_balance_pass": True,
        "terminal_voltage_solution_pass": True,
        "area_cap_pass": False,
        "positive_surface_direction": False,
        "maximum_local_current_density_a_m2": 1.0e9,
    }
    assert workshop_module.case_is_feasible(
        result, endpoint_valid=True, thermodynamic_pass=True
    )
    assert not workshop_module.case_is_feasible(
        result, endpoint_valid=True, thermodynamic_pass=False
    )


def test_convergence_requires_both_area_and_known_power(workshop_module):
    cases = pd.DataFrame(
        [
            {
                "target_id": "o30",
                "water_diffusivity_m2_s": 1.0e-12,
                "common_terminal_voltage_v": 1.0,
                "segment_count": 8,
                "case_id": "coarse",
                "common_voltage_feasible": True,
                "status": "COMMON_VOLTAGE_FEASIBLE",
                "required_active_area_m2": 100.0,
                "known_eo_grid_and_module_fan_power_kw": 10.0,
            },
            {
                "target_id": "o30",
                "water_diffusivity_m2_s": 1.0e-12,
                "common_terminal_voltage_v": 1.0,
                "segment_count": 16,
                "case_id": "refined",
                "common_voltage_feasible": True,
                "status": "COMMON_VOLTAGE_FEASIBLE",
                "required_active_area_m2": 101.0,
                "known_eo_grid_and_module_fan_power_kw": 10.3,
            },
        ]
    )
    config = {
        "segment_counts": [8, 16],
        "selected_segment_count": 16,
        "numerical_convergence": {
            "maximum_area_relative_change": 0.02,
            "maximum_known_power_relative_change": 0.02,
        },
    }
    row = workshop_module.build_segment_convergence(cases, config).iloc[0]
    assert row["area_relative_change"] < 0.02
    assert row["known_power_relative_change"] > 0.02
    assert not bool(row["numerically_confirmed_feasible"])


def test_envelope_preserves_physical_and_unresolved_failures(workshop_module):
    cases = pd.DataFrame(
        [
            {
                "target_id": "full_remaining_latent",
                "water_diffusivity_m2_s": 1.0e-12,
                "common_terminal_voltage_v": voltage,
                "segment_count": 16,
                "common_voltage_feasible": False,
                "resolution_class": resolution,
            }
            for voltage, resolution in (
                (0.5, "PHYSICAL_NO_COMMON_VOLTAGE_AT_THIS_COORDINATE"),
                (1.5, "NUMERICAL_OR_LOCAL_SOLUTION_FAILURE"),
            )
        ]
    )
    convergence = pd.DataFrame(
        {
            "target_id": ["full_remaining_latent", "full_remaining_latent"],
            "water_diffusivity_m2_s": [1.0e-12, 1.0e-12],
            "common_terminal_voltage_v": [0.5, 1.5],
            "sampled_feasibility_status_stable": [True, True],
            "numerically_confirmed_feasible": [False, False],
        }
    )
    envelope = workshop_module.build_diffusivity_envelope(
        cases, convergence, {"selected_segment_count": 16}
    ).iloc[0]
    assert envelope["selection_status"] == (
        "NO_FEASIBLE_SAMPLED_VOLTAGE_WITH_UNRESOLVED_POINTS"
    )
    assert envelope["refined_physical_no_solution_voltage_count"] == 1
    assert envelope["refined_numerical_or_local_unresolved_voltage_count"] == 1


def test_local_bracket_probe_covers_all_flagged_cases_and_promotes_only_recovery(
    workshop_module, monkeypatch
):
    source_cases = pd.DataFrame(
        [
            {
                "case_id": case_id,
                "target_id": "o30",
                "water_diffusivity_m2_s": 1.0e-9,
                "common_terminal_voltage_v": voltage,
                "segment_count": segment_count,
                "status": status,
                "resolution_class": resolution,
                "common_voltage_feasible": feasible,
                "legacy_numeric_current_search_ceiling_encountered": flagged,
                "current_density_gate_applied": False,
                "area_is_acceptance_gate": False,
                "surface_direction_is_acceptance_gate": False,
            }
            for case_id, voltage, segment_count, status, resolution, feasible, flagged in (
                (
                    "ceiling_n8",
                    1.5,
                    8,
                    "above_internal_current_search_ceiling",
                    "NUMERICAL_OR_LOCAL_SOLUTION_FAILURE",
                    False,
                    True,
                ),
                (
                    "ceiling_n16",
                    1.5,
                    16,
                    "above_internal_current_search_ceiling",
                    "NUMERICAL_OR_LOCAL_SOLUTION_FAILURE",
                    False,
                    True,
                ),
                (
                    "already_feasible",
                    1.0,
                    16,
                    "COMMON_VOLTAGE_FEASIBLE",
                    "CONVERGED_TARGET",
                    True,
                    False,
                ),
                (
                    "physical_failure",
                    0.5,
                    16,
                    "below_reversible_voltage",
                    "PHYSICAL_NO_COMMON_VOLTAGE_AT_THIS_COORDINATE",
                    False,
                    False,
                ),
            )
        ]
    )
    source_profiles = pd.DataFrame(
        {
            "case_id": source_cases["case_id"],
            "profile_source": "initial",
        }
    )
    config = {
        "selected_segment_count": 16,
        "targets": [{"target_id": "o30"}],
        "local_bracket_probe": {
            "numeric_ceiling_multiplier": 100.0,
            "coverage": "all_flagged_cases_at_or_below_2v",
        },
    }
    runtime = {
        "v2_config": {"model": {"current_solver_upper_bound_a_m2": 50_000.0}}
    }
    observed: list[tuple[int, float]] = []

    def fake_run_case(**kwargs):
        segment_count = int(kwargs["segment_count"])
        observed.append(
            (
                segment_count,
                kwargs["runtime"]["v2_config"]["model"][
                    "current_solver_upper_bound_a_m2"
                ],
            )
        )
        recovered = segment_count == 8
        case_id = f"ceiling_n{segment_count}"
        return (
            {
                "case_id": case_id,
                "target_id": "o30",
                "water_diffusivity_m2_s": 1.0e-9,
                "common_terminal_voltage_v": 1.5,
                "segment_count": segment_count,
                "status": (
                    "COMMON_VOLTAGE_FEASIBLE"
                    if recovered
                    else "above_internal_current_search_ceiling"
                ),
                "resolution_class": (
                    "CONVERGED_TARGET"
                    if recovered
                    else "PHYSICAL_NO_COMMON_VOLTAGE_AT_THIS_COORDINATE"
                ),
                "common_voltage_feasible": recovered,
                "legacy_numeric_current_search_ceiling_encountered": not recovered,
                "transport_solution_complete": recovered,
                "transport_water_balance_pass": recovered,
                "terminal_voltage_solution_pass": recovered,
                "thermodynamic_consistency_pass": recovered,
                "current_density_gate_applied": False,
                "area_is_acceptance_gate": False,
                "surface_direction_is_acceptance_gate": False,
                "required_active_area_m2": 123.0 if recovered else float("nan"),
                "minimum_local_current_density_a_m2": 25.0,
                "maximum_local_current_density_a_m2": 125.0,
            },
            pd.DataFrame(
                {"case_id": [case_id], "profile_source": ["retry"]}
            ),
        )

    monkeypatch.setattr(workshop_module, "run_case", fake_run_case)
    effective_cases, effective_profiles, probe = workshop_module.run_local_bracket_probe(
        cases=source_cases,
        profiles=source_profiles,
        config=config,
        closure=object(),
        closure_config={},
        runtime=runtime,
        source_config={},
        effective_config={},
        percentage_summary=pd.DataFrame(),
    )

    assert runtime["v2_config"]["model"]["current_solver_upper_bound_a_m2"] == 50_000.0
    assert observed == [(8, 5_000_000.0), (16, 5_000_000.0)]
    assert set(probe["source_case_id"]) == {"ceiling_n8", "ceiling_n16"}
    assert probe["source_case_id"].is_unique
    assert probe["source_high_bracket_encountered"].astype(bool).all()
    assert probe["common_terminal_voltage_v"].le(2.0).all()
    gate_columns = [column for column in probe if "acceptance_gate" in column]
    gate_columns += [column for column in probe if "current_density_gate" in column]
    assert not probe[gate_columns].astype(bool).any().any()

    effective = effective_cases.set_index("case_id")
    assert bool(effective.loc["ceiling_n8", "common_voltage_feasible"])
    assert bool(effective.loc["ceiling_n8", "numeric_ceiling_retry_recovered"])
    assert effective.loc["ceiling_n8", "status"] == "COMMON_VOLTAGE_FEASIBLE"
    assert not bool(effective.loc["ceiling_n16", "common_voltage_feasible"])
    assert not bool(effective.loc["ceiling_n16", "numeric_ceiling_retry_recovered"])
    assert effective.loc["ceiling_n16", "resolution_class"] == (
        "NUMERICAL_OR_LOCAL_SOLUTION_FAILURE"
    )
    assert not bool(effective.loc["already_feasible", "numeric_ceiling_retry_applied"])
    assert not bool(effective.loc["physical_failure", "numeric_ceiling_retry_applied"])

    profiles = effective_profiles.set_index("case_id")
    assert profiles.loc["ceiling_n8", "profile_source"] == "retry"
    assert profiles.loc["ceiling_n16", "profile_source"] == "initial"
