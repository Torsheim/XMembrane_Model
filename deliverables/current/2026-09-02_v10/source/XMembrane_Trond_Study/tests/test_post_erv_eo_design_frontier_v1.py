from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
from types import SimpleNamespace
import sys

import numpy as np
import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "make_post_erv_eo_design_frontier_v1.py"
CONFIG = ROOT / "config" / "post_erv_eo_design_frontier_v1.json"
DEFAULT_SMOKE_OUTPUT = ROOT / "outputs" / "post_erv_eo_design_frontier_v1_smoke"


def load_script():
    name = "_post_erv_eo_design_frontier_test"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def module():
    return load_script()


@pytest.fixture(scope="module")
def frontier():
    return json.loads(CONFIG.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def fake_runtime(frontier):
    special = frontier["special_completion_coordinates"][0]
    completion = float(special["remaining_duty_completion_pct"]) / 100.0
    inlet_w = 0.013214990502676377
    target_w = float(special["humidity_ratio_kg_kg_da"])
    supply_w = (target_w - (1.0 - completion) * inlet_w) / completion
    return {
        "process_in": SimpleNamespace(w=inlet_w),
        "baseline": SimpleNamespace(
            remaining_ac=SimpleNamespace(supply=SimpleNamespace(w=supply_w))
        ),
        "dry_air_mass_flow_kg_s": 100.0,
        "receiver_in": SimpleNamespace(rh=0.7169671942),
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def test_config_declares_extended_voltage_energy_and_receiver_questions(frontier):
    primary = frontier["primary_transport"]
    receiver = frontier["receiver_intervention"]

    assert min(primary["uniform_current_density_a_m2"]) <= 0.5
    assert max(primary["uniform_current_density_a_m2"]) >= 5.0
    assert len(primary["water_diffusivity_m2_s"]) >= 5
    assert primary["receiver_to_process_dry_air_ratio"] == 1.0
    assert primary["area_observation_cap_m2"] >= 60_000.0
    assert primary["terminal_voltage_limit_v"] == 1.0
    assert max(frontier["coarse_remaining_duty_completion_pct"]) >= 95.0
    assert 72.70030721103439 in frontier["coarse_remaining_duty_completion_pct"]

    assert min(receiver["receiver_inlet_rh"]) <= 0.2
    assert max(receiver["receiver_to_process_dry_air_ratio"]) >= 3.0
    assert min(receiver["receiver_film_multiplier"]) < 1.0
    assert max(receiver["receiver_film_multiplier"]) > 1.0
    assert frontier["claim_policy"]["receiver_interventions_energy_rankable"] is False
    assert frontier["claim_policy"]["full_system_claim_allowed"] is False


def test_effective_config_forces_balanced_primary_and_disables_full_system_claims(
    module, frontier
):
    base = module.read_json(module.resolve_path(frontier["base_study_config"]))
    effective = module.effective_config(frontier, base)
    sweep = effective["transport_sweep"]

    assert sweep["water_diffusivity_m2_s"] == frontier["primary_transport"][
        "water_diffusivity_m2_s"
    ]
    assert sweep["uniform_current_density_a_m2"] == frontier["primary_transport"][
        "uniform_current_density_a_m2"
    ]
    assert sweep["receiver_to_process_dry_air_ratio"] == [1.0]
    assert sweep["receiver_capacity_sweep_target_ids"] == []
    assert effective["claim_policy"]["full_system_claim_allowed"] is False
    assert effective["targets"] == []


def test_completion_coordinates_preserve_o30_and_water_duty_identity(
    module, frontier, fake_runtime
):
    o30_completion = float(
        frontier["special_completion_coordinates"][0][
            "remaining_duty_completion_pct"
        ]
    )
    at_50 = module.target_from_completion(
        50.0, fake_runtime, frontier, population="test"
    )
    o30 = module.target_from_completion(
        o30_completion, fake_runtime, frontier, population="test"
    )

    assert o30["target_id"] == "o30"
    assert o30["target_w_kg_kg_da"] == pytest.approx(0.0088858981051461)
    assert o30["remaining_duty_completion_pct"] == pytest.approx(o30_completion)
    assert o30["eo_water_removal_kg_h"] / at_50[
        "eo_water_removal_kg_h"
    ] == pytest.approx(o30_completion / 50.0)
    expected_historical = (
        100.0
        * (fake_runtime["process_in"].w - o30["target_w_kg_kg_da"])
        / fake_runtime["process_in"].w
    )
    assert o30["historical_relative_reduction_pct"] == pytest.approx(
        expected_historical
    )
    assert o30["full_system_claim_allowed"] is False


def test_coordinate_helpers_are_deterministic_and_fail_on_nonfinite(module):
    assert module.unique_sorted([60.0, 50.0, 60.0 + 1.0e-10]) == [50.0, 60.0]
    assert module.token(72.70030721103439) == "72p700307211"
    assert module.token(-0.5) == "m0p5"
    with pytest.raises(module.StudyError, match="finite"):
        module.unique_sorted([50.0, math.nan])


def test_unresolved_voltage_is_fail_closed_in_electrical_regime(
    module, frontier
):
    frame = pd.DataFrame(
        {
            "incremental_water_removal_target_kg_h": [100.0] * 4,
            "incremental_eo_and_fan_power_kw": [1.0] * 4,
            "incremental_saving_kw_vs_passive_erv": [2.0] * 4,
            "maximum_receiver_surface_activity": [0.8] * 4,
            "transport_gate_pass": [True] * 4,
            "positive_surface_direction_everywhere": [False] * 4,
            "receiver_to_process_dry_air_ratio": [1.0] * 4,
            "minimum_required_terminal_voltage_signed_v": [
                math.nan,
                0.1,
                0.1,
                0.9,
            ],
            "maximum_required_terminal_voltage_signed_v": [
                math.nan,
                0.9,
                math.inf,
                0.1,
            ],
        }
    )
    target = {
        "target_id": "test",
        "target_label": "test",
        "target_definition": "test",
        "target_w_kg_kg_da": 0.01,
        "target_w_g_kg_da": 10.0,
        "remaining_duty_completion_pct": 50.0,
        "historical_relative_reduction_pct": 10.0,
        "is_o30_bridge": False,
    }

    enriched = module.enrich_transport(
        frame, target, frontier, intervention=False
    )

    assert enriched.loc[0, "electrical_regime"] == "unresolved_voltage"
    assert not bool(
        enriched.loc[0, "ordinary_nonnegative_import_voltage_everywhere"]
    )
    assert enriched.loc[1, "electrical_regime"] == (
        "nonnegative_voltage_everywhere"
    )
    assert bool(
        enriched.loc[1, "ordinary_nonnegative_import_voltage_everywhere"]
    )
    for index in (2, 3):
        assert enriched.loc[index, "electrical_regime"] == "unresolved_voltage"
        assert not bool(
            enriched.loc[
                index, "ordinary_nonnegative_import_voltage_everywhere"
            ]
        )


def test_smoke_design_cardinality_and_balanced_primary_only(
    module, frontier, fake_runtime
):
    targets = module.make_targets(fake_runtime, frontier, smoke=True)
    design = module.build_primary_design(targets, frontier, smoke=True)
    smoke = frontier["smoke"]
    expected = (
        len(smoke["coarse_remaining_duty_completion_pct"])
        * len(smoke["water_diffusivity_m2_s"])
        * len(smoke["uniform_current_density_a_m2"])
    )

    assert len(design) == expected
    assert design["case_id"].nunique() == expected
    assert set(design["receiver_to_process_dry_air_ratio"]) == {1.0}
    assert set(design["uniform_current_density_a_m2"]) == set(
        smoke["uniform_current_density_a_m2"]
    )
    assert set(design["design_population"]) == {"balanced_primary_coarse"}


def test_receiver_factorial_includes_baseline_but_is_explicitly_unrankable(
    module, frontier, fake_runtime
):
    design = module.build_receiver_design(fake_runtime, frontier, smoke=True)
    completions, ratios, humidity, films = module.receiver_axes(
        fake_runtime, frontier, smoke=True
    )

    assert len(design) == len(completions) * len(ratios) * len(humidity) * len(films)
    assert design["case_id"].is_unique
    assert design["receiver_inlet_is_erv_baseline"].any()
    assert np.isclose(humidity, fake_runtime["receiver_in"].rh).any()
    assert set(design["design_population"]) == {
        "receiver_intervention_unrankable"
    }
    baseline = design.loc[
        design["receiver_inlet_is_erv_baseline"]
        & np.isclose(design["receiver_to_process_dry_air_ratio"], 1.0)
        & np.isclose(design["receiver_film_multiplier"], 1.0)
    ]
    assert len(baseline) == len(completions)


def _selection_row(
    *,
    target_id: str,
    completion: float,
    case_id: str,
    saving: float,
    voltage: float,
    gate: bool = True,
    reached: bool = True,
    area: float = 100.0,
    ratio: float = 1.0,
) -> dict[str, object]:
    return {
        "target_id": target_id,
        "remaining_duty_completion_pct": completion,
        "case_id": case_id,
        "target_reached": reached,
        "declared_transport_screen_pass": gate,
        "positive_surface_direction_screen_pass": False,
        "receiver_resource_feasible_without_external_source": ratio <= 1.0,
        "receiver_to_process_dry_air_ratio": ratio,
        "area_is_right_censored": False,
        "required_active_area_m2": area,
        "incremental_saving_kw_vs_passive_erv": saving,
        "maximum_required_terminal_voltage_signed_v": voltage,
    }


def test_primary_selection_is_fail_closed_and_applies_voltage_cap(module):
    transport = pd.DataFrame(
        [
            _selection_row(
                target_id="a",
                completion=50.0,
                case_id="failed-high-saving",
                saving=1_000.0,
                voltage=0.5,
                gate=False,
            ),
            _selection_row(
                target_id="a",
                completion=50.0,
                case_id="energy-best-over-cap",
                saving=20.0,
                voltage=1.2,
            ),
            _selection_row(
                target_id="a",
                completion=50.0,
                case_id="best-under-cap",
                saving=12.0,
                voltage=0.9,
                area=200.0,
            ),
            _selection_row(
                target_id="b",
                completion=60.0,
                case_id="only-failed",
                saving=2_000.0,
                voltage=0.4,
                gate=False,
            ),
        ]
    )

    selected, status = module.select_primary_cases(transport, 1.0)
    selected_a = selected.set_index("selection")

    assert set(selected["target_id"]) == {"a"}
    assert selected_a.loc[
        "best_conditional_saving", "case_id"
    ] == "energy-best-over-cap"
    assert selected_a.loc["best_under_1v", "case_id"] == "best-under-cap"
    assert selected_a.loc["minimum_voltage", "case_id"] == "best-under-cap"
    assert selected["selection_has_no_failed_case_fallback"].all()
    status = status.set_index("target_id")
    assert bool(status.loc["a", "one_volt_feasible"])
    assert not bool(status.loc["b", "one_volt_feasible"])
    assert status.loc["b", "declared_balanced_candidate_count"] == 0


def test_one_volt_bracket_reports_crossing_and_open_bounds(module):
    bracketed = pd.DataFrame(
        {
            "remaining_duty_completion_pct": [50.0, 60.0, 70.0],
            "one_volt_feasible": [True, True, False],
        }
    )
    assert module.find_one_volt_bracket(bracketed) == (
        "bracketed_crossing",
        60.0,
        70.0,
    )

    all_pass = bracketed.assign(one_volt_feasible=True)
    status, lower, upper = module.find_one_volt_bracket(all_pass)
    assert status == "not_reached_by_upper_bound"
    assert lower == 70.0
    assert math.isnan(upper)

    all_fail = bracketed.assign(one_volt_feasible=False)
    status, lower, upper = module.find_one_volt_bracket(all_fail)
    assert status == "already_failed_at_lower_bound"
    assert math.isnan(lower)
    assert upper == 50.0


def test_receiver_surface_threshold_interpolation_is_explicitly_diagnostic(module):
    crossing = module.classify_threshold([0.2, 0.4], [0.1, -0.3])
    assert crossing["status"] == "bracketed_crossing"
    assert crossing["threshold_x"] == pytest.approx(0.25)
    assert crossing["lower_x"] == 0.2
    assert crossing["upper_x"] == 0.4

    exact = module.classify_threshold([0.2, 0.4], [0.0, -0.2])
    assert exact["status"] == "exact_grid_crossing"
    assert exact["threshold_x"] == 0.2

    insufficient = module.classify_threshold([0.2], [0.1])
    assert insufficient["status"] == "invalid_or_missing_data"
    assert math.isnan(insufficient["threshold_x"])


def test_receiver_strategy_families_remain_unrankable(module, fake_runtime):
    baseline_rh = fake_runtime["receiver_in"].rh
    receiver = pd.DataFrame(
        [
            ("baseline", 1.0, baseline_rh, 1.0, -0.2),
            ("air", 2.0, baseline_rh, 1.0, -0.1),
            ("dry", 1.0, 0.4, 1.0, 0.1),
            ("film", 1.0, baseline_rh, 2.0, -0.05),
            ("combined", 2.0, 0.4, 2.0, 0.2),
        ],
        columns=[
            "case_id",
            "receiver_to_process_dry_air_ratio",
            "receiver_inlet_rh",
            "receiver_film_multiplier",
            "minimum_surface_activity_margin",
        ],
    )
    receiver["target_id"] = "completion_50pct"
    receiver["remaining_duty_completion_pct"] = 50.0
    receiver["target_reached"] = True
    receiver["declared_transport_screen_pass"] = True
    receiver["positive_surface_direction_screen_pass"] = receiver[
        "minimum_surface_activity_margin"
    ].gt(0.0)

    strategy, thresholds = module.receiver_strategy_tables(receiver, fake_runtime)

    assert set(strategy["receiver_strategy_family"]) == {
        "baseline",
        "airflow_only",
        "drying_only",
        "film_only",
        "combined_factorial",
    }
    assert (~strategy["energy_rankable"]).all()
    assert (~strategy["full_system_claim_allowed"]).all()
    assert thresholds["threshold_is_diagnostic_not_energy_rankable"].all()
    assert (~thresholds["full_system_claim_allowed"]).all()


def test_receiver_sec_identity_and_screened_optimum_can_shift(module, frontier):
    local_frontier = copy.deepcopy(frontier)
    local_frontier["receiver_and_sink_sec_scenarios_kwh_per_kg"] = [0.0, 1.2]
    selected = pd.DataFrame(
        [
            {
                "case_id": "p50",
                "target_id": "completion_50pct",
                "selection": "best_under_1v",
                "remaining_duty_completion_pct": 50.0,
                "incremental_water_removal_target_kg_h": 10.0,
                "control_regime_conservative_saving_kw_before_receiver_sink": 20.0,
            },
            {
                "case_id": "p60",
                "target_id": "completion_60pct",
                "selection": "best_under_1v",
                "remaining_duty_completion_pct": 60.0,
                "incremental_water_removal_target_kg_h": 20.0,
                "control_regime_conservative_saving_kw_before_receiver_sink": 30.0,
            },
        ]
    )

    scenarios, optimum = module.build_energy_scenarios(selected, local_frontier)
    # ``receiver_and_sink_power_kw`` already contains water * SEC; use the
    # published identity directly so the test remains schema-explicit.
    assert scenarios["scenario_saving_kw_vs_erv_ac"].to_numpy() == pytest.approx(
        (
            scenarios["saving_before_receiver_and_sink_kw"]
            - scenarios["receiver_and_sink_power_kw"]
        ).to_numpy()
    )
    by_sec = optimum.set_index("receiver_and_sink_sec_kwh_per_kg")
    assert by_sec.loc[0.0, "case_id"] == "p60"
    assert by_sec.loc[1.2, "case_id"] == "p50"
    assert optimum["screened_window_optimum_only"].all()
    assert (~optimum["validated_full_system_optimum"]).all()
    assert (~scenarios["full_system_claim_allowed"]).all()


def test_existing_smoke_output_has_passed_audit_and_untampered_transport():
    configured = os.environ.get("HEIQ_FRONTIER_SMOKE_OUTPUT")
    output = Path(configured).expanduser().resolve() if configured else DEFAULT_SMOKE_OUTPUT
    audit_path = output / "audit.json"
    if not audit_path.is_file():
        pytest.skip(
            "No design-frontier smoke output yet; run the generator's --smoke command first"
        )

    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    contract = json.loads((output / "transport_contract.json").read_text(encoding="utf-8"))
    primary = pd.read_csv(output / "primary_transport_cases.csv", low_memory=False)
    receiver = pd.read_csv(output / "receiver_intervention_cases.csv", low_memory=False)
    selected = pd.read_csv(output / "selected_primary_cases.csv", low_memory=False)

    assert audit["mode"] == "smoke"
    assert audit["pass"] is True, [
        name for name, passed in audit["checks"].items() if not passed
    ]
    assert all(audit["checks"].values())
    assert audit["physical_status"]["validated_full_system_optimum"] is False
    assert audit["physical_status"]["full_system_claim_allowed"] is False
    assert set(primary["receiver_to_process_dry_air_ratio"]) == {1.0}
    assert (~receiver["receiver_intervention_energy_rankable"].astype(bool)).all()
    assert (~receiver["full_system_claim_allowed"].astype(bool)).all()
    under = selected.loc[selected["selection"].eq("best_under_1v")]
    assert (
        under["maximum_required_terminal_voltage_signed_v"] <= 1.0 + 1.0e-12
    ).all()
    for filename, expected_hash in contract["transport_files"].items():
        assert sha256_file(output / filename) == expected_hash
