from __future__ import annotations

import copy
import importlib.util
import inspect
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "make_post_erv_eo_percentage_sweep_v1.py"
CONFIG = ROOT / "config" / "post_erv_eo_percentage_sweep_v1.json"
V2_ROOT = ROOT.parent / "HeiQ_V2"
RUNTIME_AVAILABLE = (
    V2_ROOT
    / "outputs"
    / "active_eo_erv_terminal1_v2_study"
    / "active_eo_erv_manifest.json"
).is_file()


def load_script():
    name = "_post_erv_eo_percentage_sweep_test"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_config_keeps_both_percentage_definitions_and_fail_closed_policy():
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    definitions = config["percentage_definition"]

    assert definitions["legacy_relative_reduction_pct"] == 10.0
    assert "w_ERV_out - w_after_EO" in definitions["historical_relative_reduction"]
    assert "w_ERV_out - w_supply" in definitions["remaining_duty_completion"]
    assert 100.0 in config["transport_remaining_duty_completion_pct"]
    assert 99.9 in config["transport_remaining_duty_completion_pct"]
    assert config["transport_overrides"]["receiver_to_process_dry_air_ratio"] == [
        1.0
    ]
    assert config["transport_overrides"]["receiver_capacity_sweep_target_ids"] == []
    assert config["claim_policy"]["full_system_claim_allowed"] is False


def test_special_target_transport_flags_match_the_declared_transport_grid(
    loaded_study,
):
    coordinates = loaded_study["coordinates"].set_index("target_id")
    configured_transport = np.asarray(
        loaded_study["percentage_config"][
            "transport_remaining_duty_completion_pct"
        ],
        dtype=float,
    )

    for special in loaded_study["percentage_config"]["special_targets"]:
        coordinate = coordinates.loc[str(special["target_id"])]
        listed_for_transport = bool(
            np.isclose(
                configured_transport,
                float(coordinate["remaining_duty_completion_pct"]),
                rtol=0.0,
                atol=1.0e-8,
            ).any()
        )
        assert bool(special["run_transport"]) is listed_for_transport
        assert bool(coordinate["run_transport"]) is bool(special["run_transport"])


def test_special_target_transport_flag_mismatch_is_rejected(loaded_study):
    module = loaded_study["module"]
    inconsistent = copy.deepcopy(loaded_study["percentage_config"])
    inconsistent["transport_remaining_duty_completion_pct"] = [
        value
        for value in inconsistent["transport_remaining_duty_completion_pct"]
        if not np.isclose(float(value), 100.0, rtol=0.0, atol=1.0e-8)
    ]
    config = module.effective_config(
        inconsistent,
        module.read_json(loaded_study["base_config_path"]),
    )

    with pytest.raises(module.StudyError, match="special.*run_transport|run_transport.*special"):
        module.make_percentage_targets(
            loaded_study["base"],
            loaded_study["runtime"],
            inconsistent,
            config,
            smoke=False,
        )


@pytest.fixture(scope="module")
def loaded_study():
    if not RUNTIME_AVAILABLE:
        pytest.skip("Audited HeiQ_V2 post-ERV runtime is not present")
    module = load_script()
    percentage_config = module.read_json(CONFIG)
    base_config_path = module.resolve_path(percentage_config["base_study_config"])
    base_config = module.read_json(base_config_path)
    base = module.load_module(module.BASE_SCRIPT, "_percentage_test_base")
    config = module.effective_config(percentage_config, base_config)
    analyzer, runtime, _, source_config_path, analyzer_path = base.load_runtime(
        config,
        v2_root=V2_ROOT,
        area_step_m2=float(config["transport_sweep"]["area_step_m2"]),
    )
    config, coordinates = module.make_percentage_targets(
        base, runtime, percentage_config, config, smoke=False
    )
    energy, break_even, endpoint = module.build_energy_tables(
        base, runtime, coordinates, config
    )
    return {
        "module": module,
        "base": base,
        "percentage_config": percentage_config,
        "base_config_path": base_config_path,
        "config": config,
        "analyzer": analyzer,
        "runtime": runtime,
        "source_config_path": source_config_path,
        "analyzer_path": analyzer_path,
        "coordinates": coordinates,
        "energy": energy,
        "break_even": break_even,
        "endpoint": endpoint,
    }


def test_percentage_coordinates_preserve_legacy_o30_and_full_meaning(loaded_study):
    coordinates = loaded_study["coordinates"].set_index("target_id")

    assert len(coordinates) == 106
    assert coordinates.loc["completion_0pct", "target_w_g_kg_da"] == pytest.approx(
        13.214990502676377
    )
    assert coordinates.loc[
        "post_erv_10pct", "remaining_duty_completion_pct"
    ] == pytest.approx(22.192500901195075)
    assert coordinates.loc[
        "post_erv_10pct", "historical_relative_reduction_pct"
    ] == pytest.approx(10.0)
    assert coordinates.loc["o30", "remaining_duty_completion_pct"] == pytest.approx(
        72.70030721103439
    )
    assert coordinates.loc[
        "full_remaining_latent", "remaining_duty_completion_pct"
    ] == pytest.approx(100.0)
    assert coordinates.loc[
        "full_remaining_latent", "historical_relative_reduction_pct"
    ] == pytest.approx(45.06026627878382)
    assert coordinates.loc[
        "full_remaining_latent", "eo_water_removal_kg_h"
    ] == pytest.approx(1689.5014518920134)


def test_water_duty_and_target_are_monotone_percentage_identities(loaded_study):
    coordinates = loaded_study["coordinates"].sort_values(
        "remaining_duty_completion_pct"
    )
    full_water = float(
        coordinates.loc[
            coordinates["target_id"].eq("full_remaining_latent"),
            "eo_water_removal_kg_h",
        ].iloc[0]
    )

    assert (
        coordinates["target_w_kg_kg_da"].diff().dropna() <= 1.0e-12
    ).all()
    assert (coordinates["eo_water_removal_kg_h"].diff().dropna() >= -1.0e-9).all()
    assert coordinates["eo_water_removal_kg_h"].to_numpy() == pytest.approx(
        coordinates["remaining_duty_completion_pct"].to_numpy()
        / 100.0
        * full_water,
        rel=1.0e-10,
        abs=1.0e-8,
    )


def test_energy_curve_separates_conservative_limit_from_exact_endpoint(loaded_study):
    energy = loaded_study["energy"]
    break_even = loaded_study["break_even"]
    subset = energy.loc[
        energy["target_id"].isin(["completion_99p9pct", "full_remaining_latent"])
        & energy["all_in_eo_sec_kwh_per_kg"].eq(0.1)
        & energy["process_heat_leak_fraction"].eq(0.0)
    ].set_index("target_id")

    assert subset.loc[
        "full_remaining_latent", "control_conservative_net_saving_kw_vs_erv_ac"
    ] == pytest.approx(95.7960958307, rel=1.0e-8)
    assert subset.loc[
        "full_remaining_latent", "net_saving_kw_vs_erv_ac"
    ] == pytest.approx(295.993383833, rel=1.0e-8)
    assert (
        subset.loc["full_remaining_latent", "net_saving_kw_vs_erv_ac"]
        - subset.loc[
            "full_remaining_latent", "control_conservative_net_saving_kw_vs_erv_ac"
        ]
    ) == pytest.approx(200.197288, rel=1.0e-7)
    full_break = break_even.loc[
        break_even["target_id"].eq("full_remaining_latent")
        & break_even["process_heat_leak_fraction"].eq(0.0)
    ].iloc[0]
    assert full_break["break_even_all_in_eo_sec_kwh_per_kg"] == pytest.approx(
        0.2751956966376383
    )
    assert full_break[
        "control_conservative_break_even_sec_kwh_per_kg"
    ] == pytest.approx(0.15670080744075676)


def test_energy_sec_scenarios_are_in_effective_grid_and_summary_is_finite(
    loaded_study,
):
    module = loaded_study["module"]
    scenarios = {
        float(value)
        for value in loaded_study["percentage_config"]["energy_percentage_grid"][
            "all_in_sec_scenarios_kwh_per_kg"
        ]
    }
    effective_grid = {
        float(value)
        for value in loaded_study["config"]["energy_window"][
            "all_in_eo_sec_kwh_per_kg"
        ]
    }
    assert scenarios <= effective_grid

    summary = module.build_percentage_summary(
        loaded_study["coordinates"],
        loaded_study["energy"],
        loaded_study["break_even"],
        pd.DataFrame(),
        pd.DataFrame(),
        pd.DataFrame(),
        loaded_study["percentage_config"],
    )
    for value in scenarios:
        token = module.percentage_token(1000.0 * value)
        for prefix in ("native", "control_conservative"):
            column = (
                f"{prefix}_saving_zero_process_heat_at_{token}_wh_per_kg_kw"
            )
            assert column in summary
            assert np.isfinite(pd.to_numeric(summary[column], errors="coerce")).all()


def test_only_exact_full_target_uses_the_sensible_only_energy_endpoint(loaded_study):
    energy = loaded_study["energy"]
    sensible_only = energy.loc[
        np.isclose(energy["all_in_eo_sec_kwh_per_kg"], 0.0)
        & np.isclose(energy["process_heat_leak_fraction"], 0.0)
        & (energy["remaining_duty_completion_pct"] > 0.0)
        & energy["remaining_ac_is_sensible_only"].astype(bool)
    ]

    assert sensible_only["target_id"].tolist() == ["full_remaining_latent"]
    assert sensible_only.iloc[0]["remaining_duty_completion_pct"] == pytest.approx(
        100.0
    )


def test_transport_design_cardinality_and_balanced_receiver_only(loaded_study):
    base = loaded_study["base"]
    config = loaded_study["config"]
    coordinates = loaded_study["coordinates"]
    design = base.build_transport_case_design(coordinates, config, smoke=False)

    assert coordinates["run_transport"].sum() == 12
    assert len(design) == 720
    assert design["case_id"].nunique() == 720
    assert set(design["receiver_to_process_dry_air_ratio"]) == {1.0}

    smoke_config, smoke_coordinates = loaded_study["module"].make_percentage_targets(
        base,
        loaded_study["runtime"],
        loaded_study["percentage_config"],
        loaded_study["module"].effective_config(
            loaded_study["percentage_config"],
            loaded_study["module"].read_json(loaded_study["base_config_path"]),
        ),
        smoke=True,
    )
    smoke = base.build_transport_case_design(smoke_coordinates, smoke_config, smoke=True)
    assert smoke_coordinates["run_transport"].sum() == 7
    assert len(smoke) == 28


def test_percentage_selection_never_falls_back_to_failed_rows(loaded_study):
    module = loaded_study["module"]
    base = loaded_study["base"]
    frame = pd.DataFrame(
        [
            {
                "target_id": "a",
                "case_id": "failed",
                "target_reached": True,
                "declared_transport_screen_pass": False,
                "receiver_resource_feasible_without_external_source": True,
                "receiver_to_process_dry_air_ratio": 1.0,
                "incremental_saving_kw_vs_passive_erv": 100.0,
                "required_active_area_m2": 1.0,
            },
            {
                "target_id": "a",
                "case_id": "passing",
                "target_reached": True,
                "declared_transport_screen_pass": True,
                "receiver_resource_feasible_without_external_source": True,
                "receiver_to_process_dry_air_ratio": 1.0,
                "incremental_saving_kw_vs_passive_erv": 10.0,
                "required_active_area_m2": 2.0,
            },
            {
                "target_id": "b",
                "case_id": "only-failed",
                "target_reached": True,
                "declared_transport_screen_pass": False,
                "receiver_resource_feasible_without_external_source": True,
                "receiver_to_process_dry_air_ratio": 1.0,
                "incremental_saving_kw_vs_passive_erv": 200.0,
                "required_active_area_m2": 1.0,
            },
        ]
    )
    selected = module.select_percentage_cases(base, frame)

    assert set(selected["case_id"]) == {"passing"}
    assert set(selected["target_id"]) == {"a"}
    assert selected["percentage_selection_has_no_failed_case_fallback"].all()


def test_selection_status_records_selected_and_unavailable_reasons(loaded_study):
    module = loaded_study["module"]
    target_ids = ["completion_10pct", "post_erv_10pct", "completion_40pct"]
    transport = pd.DataFrame(
        [
            {
                "target_id": target_ids[0],
                "target_reached": True,
                "receiver_to_process_dry_air_ratio": 1.0,
                "declared_transport_screen_pass": True,
                "positive_surface_direction_screen_pass": True,
            },
            {
                "target_id": target_ids[1],
                "target_reached": False,
                "receiver_to_process_dry_air_ratio": 1.0,
                "declared_transport_screen_pass": False,
                "positive_surface_direction_screen_pass": False,
            },
            {
                "target_id": target_ids[2],
                "target_reached": True,
                "receiver_to_process_dry_air_ratio": 1.0,
                "declared_transport_screen_pass": False,
                "positive_surface_direction_screen_pass": True,
            },
        ]
    )
    selections = pd.DataFrame(
        [
            {
                "target_id": target_ids[0],
                "selection": "best_conditional_saving",
            }
        ]
    )
    status = module.build_selection_status(
        loaded_study["base"],
        transport,
        selections,
        loaded_study["coordinates"],
    ).set_index("target_id")

    assert status.loc[target_ids[0], "selection_status"] == (
        "selected_balanced_declared_gate_case"
    )
    assert bool(status.loc[target_ids[0], "balanced_selection_available"])
    assert status.loc[target_ids[1], "selection_status"] == "no_target_reaching_case"
    assert status.loc[target_ids[2], "selection_status"] == (
        "no_balanced_declared_gate_case"
    )


def test_percentage_contract_rejects_transport_csv_tampering(tmp_path, loaded_study):
    module = loaded_study["module"]
    base = loaded_study["base"]
    design = base.build_transport_case_design(
        loaded_study["coordinates"], loaded_study["config"], smoke=False
    )
    transport_path = tmp_path / "transport_cases.csv"
    contract_path = tmp_path / "transport_contract.json"
    transport_path.write_text("case_id\nplaceholder\n", encoding="utf-8")
    contract_kwargs = {
        "percentage_config_path": CONFIG,
        "base_config_path": loaded_study["base_config_path"],
        "source_config_path": loaded_study["source_config_path"],
        "analyzer_path": loaded_study["analyzer_path"],
        "mode": "study",
    }
    source_snapshot = None
    if "source_snapshot" in inspect.signature(
        module.build_transport_contract
    ).parameters:
        source_snapshot = module.build_source_snapshot(
            loaded_study["runtime"],
            percentage_config_path=CONFIG,
            base_config_path=loaded_study["base_config_path"],
            source_config_path=loaded_study["source_config_path"],
            analyzer_path=loaded_study["analyzer_path"],
        )
        contract_kwargs["source_snapshot"] = source_snapshot
    contract = module.build_transport_contract(
        base,
        loaded_study["runtime"],
        loaded_study["percentage_config"],
        loaded_study["config"],
        design,
        transport_path,
        **contract_kwargs,
    )
    if source_snapshot is not None:
        assert contract["source_snapshot"] == source_snapshot
    base.write_json(contract_path, contract)
    module.validate_transport_contract(
        base,
        contract_path,
        loaded_study["runtime"],
        loaded_study["percentage_config"],
        loaded_study["config"],
        design,
        transport_path,
        percentage_config_path=CONFIG,
        base_config_path=loaded_study["base_config_path"],
        source_config_path=loaded_study["source_config_path"],
        analyzer_path=loaded_study["analyzer_path"],
        mode="study",
    )

    transport_path.write_text("case_id\ntampered\n", encoding="utf-8")
    with pytest.raises(module.StudyError, match="transport_csv.sha256"):
        module.validate_transport_contract(
            base,
            contract_path,
            loaded_study["runtime"],
            loaded_study["percentage_config"],
            loaded_study["config"],
            design,
            transport_path,
            percentage_config_path=CONFIG,
            base_config_path=loaded_study["base_config_path"],
            source_config_path=loaded_study["source_config_path"],
            analyzer_path=loaded_study["analyzer_path"],
            mode="study",
        )


def test_energy_only_audit_passes_with_full_system_claims_disabled(loaded_study):
    module = loaded_study["module"]
    summary = module.build_percentage_summary(
        loaded_study["coordinates"],
        loaded_study["energy"],
        loaded_study["break_even"],
        pd.DataFrame(),
        pd.DataFrame(),
        pd.DataFrame(),
        loaded_study["percentage_config"],
    )
    audit = module.build_audit(
        loaded_study["base"],
        loaded_study["runtime"],
        loaded_study["percentage_config"],
        loaded_study["config"],
        loaded_study["coordinates"],
        loaded_study["energy"],
        loaded_study["break_even"],
        pd.DataFrame(),
        pd.DataFrame(),
        loaded_study["endpoint"],
        pd.DataFrame(),
        summary,
        pd.DataFrame(),
        pd.DataFrame(),
        False,
        True,
        percentage_config_path=CONFIG,
        base_config_path=loaded_study["base_config_path"],
        source_config_path=loaded_study["source_config_path"],
        analyzer_path=loaded_study["analyzer_path"],
        mode="energy_only",
    )

    assert audit["pass"] is True, {
        "base_pass": audit.get("base_pass", audit.get("pass")),
        "failed_percentage_checks": [
            name for name, passed in audit["percentage_checks"].items() if not passed
        ],
    }
    assert all(audit["percentage_checks"].values())
    assert audit["full_system_claim_allowed"] is False
    assert audit["transport_contract_required"] is False
