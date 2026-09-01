#!/usr/bin/env python3
"""Build a hash-bound register of the remaining HeiQ system questions.

The analysis reads existing audited outputs and calculates explicit decision
boundaries.  It does not assign probabilities, weighted scores, or a full-
system saving claim.  Impact and closure effort are reported only with the
ordinal, rule-based categories declared in the configuration file.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Iterable

os.environ.setdefault("MPLCONFIGDIR", "/tmp/heiq-open-questions-mpl")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
HEIQ_V2_ROOT = ROOT.parent / "HeiQ_V2"
DEFAULT_CONFIG = ROOT / "config" / "open_questions_analysis_v1.json"

INK = "#172A3A"
NAVY = "#17324D"
TEAL = "#008C8C"
TEAL_DARK = "#005F63"
ORANGE = "#E58B2A"
RED = "#B94A3D"
GOLD = "#D6A52A"
SLATE = "#607284"
PALE = "#EEF3F5"
WHITE = "#FFFFFF"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--require-empty-out-dir", action="store_true")
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def as_bool(values: pd.Series) -> pd.Series:
    if values.dtype == bool:
        return values.fillna(False).astype(bool)
    if pd.api.types.is_numeric_dtype(values):
        return values.fillna(0).astype(float).astype(bool)
    return values.astype(str).str.strip().str.lower().isin(
        {"1", "true", "yes", "pass", "passed"}
    )


def finite(value: Any) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"Expected finite value, got {value!r}")
    return result


def json_default(value: Any) -> Any:
    """Convert NumPy scalar values without weakening JSON validation."""

    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def validate_config(config: dict[str, Any]) -> None:
    if config.get("schema_version") != 1:
        raise ValueError("Unsupported open-questions config schema")
    claim = config.get("claim_boundary", {})
    if claim.get("full_system_claim_allowed") is not False:
        raise ValueError("Full-system claims must remain disabled")
    if claim.get("deterministic_scenarios_are_probabilities") is not False:
        raise ValueError("Deterministic scenarios must not be probabilities")
    if claim.get("ordinal_categories_are_numeric_scores") is not False:
        raise ValueError("Ordinal categories must not be numeric scores")

    categories = config.get("ordinal_categories", {})
    impact = categories.get("decision_impact_high_to_low", [])
    effort = categories.get("closure_effort_low_to_high", [])
    for name, entries in (("impact", impact), ("effort", effort)):
        if not isinstance(entries, list) or len(entries) < 2:
            raise ValueError(f"Missing ordinal {name} categories")
        ids = [entry.get("id") for entry in entries]
        if len(ids) != len(set(ids)) or any(not item for item in ids):
            raise ValueError(f"Invalid ordinal {name} identifiers")
        if any(not entry.get("definition") for entry in entries):
            raise ValueError(f"Every ordinal {name} needs a definition")

    settings = config.get("analysis_settings", {})
    if finite(settings.get("direct_voltage_cap_v")) > 2.0:
        raise ValueError("Direct open-question audit is limited to <=2 V")
    correction = settings.get("report_correction", {})
    if correction.get("v4_must_remain_untouched") is not True:
        raise ValueError("V4 preservation must be explicit")
    if not isinstance(config.get("sources"), list) or not config["sources"]:
        raise ValueError("No source bindings declared")
    source_ids = [item.get("source_id") for item in config["sources"]]
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("Duplicate source identifiers")


def root_for(name: str) -> Path:
    if name == "study":
        return ROOT
    if name == "heiq_v2":
        return HEIQ_V2_ROOT
    raise ValueError(f"Unknown source root: {name}")


def bind_sources(
    config: dict[str, Any],
) -> tuple[dict[str, Path], list[dict[str, Any]], dict[str, dict[str, Any]]]:
    paths: dict[str, Path] = {}
    records: list[dict[str, Any]] = []
    for spec in config["sources"]:
        source_id = str(spec["source_id"])
        path = (root_for(str(spec["root"])) / str(spec["path"])).resolve()
        required = bool(spec.get("required", True))
        if not path.is_file():
            if required:
                raise FileNotFoundError(f"Required source missing: {path}")
            records.append(
                {
                    "source_id": source_id,
                    "path": str(path),
                    "required": required,
                    "available": False,
                    "sha256": None,
                    "expected_sha256": spec.get("sha256"),
                    "hash_match": None,
                    "size_bytes": None,
                }
            )
            continue
        observed = sha256_file(path)
        expected = spec.get("sha256")
        if expected and observed != expected:
            raise ValueError(
                f"Hash mismatch for {source_id}: expected {expected}, got {observed}"
            )
        paths[source_id] = path
        records.append(
            {
                "source_id": source_id,
                "path": str(path),
                "required": required,
                "available": True,
                "sha256": observed,
                "expected_sha256": expected,
                "hash_match": expected is None or observed == expected,
                "size_bytes": path.stat().st_size,
            }
        )

    optional: dict[str, dict[str, Any]] = {}
    for group in config.get("optional_source_groups", []):
        group_id = str(group["group_id"])
        directory = (root_for(str(group["root"])) / str(group["directory"])).resolve()
        available = directory.is_dir()
        group_paths: dict[str, Path] = {}
        group_records: list[dict[str, Any]] = []
        if available:
            missing = [name for name in group["files"] if not (directory / name).is_file()]
            if missing:
                raise FileNotFoundError(
                    f"Optional group {group_id} exists but is incomplete: {missing}"
                )
            for name in group["files"]:
                path = (directory / name).resolve()
                group_paths[str(name)] = path
                group_records.append(
                    {
                        "relative_path": str(name),
                        "path": str(path),
                        "sha256": sha256_file(path),
                        "size_bytes": path.stat().st_size,
                    }
                )
        optional[group_id] = {
            "available": available,
            "directory": str(directory),
            "rule": group.get("rule"),
            "paths": group_paths,
            "records": group_records,
        }
    return paths, records, optional


def boundary_row(
    boundary_id: str,
    question_id: str,
    architecture: str,
    metric: str,
    value: float,
    unit: str,
    condition: str,
    interpretation: str,
    source_ids: Iterable[str],
) -> dict[str, Any]:
    return {
        "boundary_id": boundary_id,
        "question_id": question_id,
        "architecture": architecture,
        "metric": metric,
        "numeric_value": finite(value),
        "unit": unit,
        "condition": condition,
        "interpretation": interpretation,
        "source_ids": ";".join(source_ids),
        "probability_interpretation": "DETERMINISTIC_NOT_PROBABILITY",
    }


def question_row(
    *,
    question_id: str,
    system_gap: str,
    current_status: str,
    evidence_finding: str,
    decision_impact_category: str,
    decision_impact_basis: str,
    closure_effort_category: str,
    closure_effort_basis: str,
    next_experiment_or_replay: str,
    acceptance_or_replay_rule: str,
    source_ids: Iterable[str],
) -> dict[str, Any]:
    return {
        "question_id": question_id,
        "system_gap": system_gap,
        "current_status": current_status,
        "evidence_finding": evidence_finding,
        "decision_impact_category": decision_impact_category,
        "decision_impact_basis": decision_impact_basis,
        "closure_effort_category": closure_effort_category,
        "closure_effort_basis": closure_effort_basis,
        "next_experiment_or_replay": next_experiment_or_replay,
        "acceptance_or_replay_rule": acceptance_or_replay_rule,
        "source_ids": ";".join(source_ids),
        "full_system_claim_allowed": False,
        "probability_interpretation": "NO_PROBABILITY_ASSIGNED",
    }


def build_analysis(
    config: dict[str, Any],
    paths: dict[str, Path],
    optional: dict[str, dict[str, Any]],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any], list[dict[str, Any]]]:
    settings = config["analysis_settings"]
    direct = pd.read_csv(paths["direct_per_cap_register"], low_memory=False)
    direct_receiver = pd.read_csv(paths["direct_receiver_summary"])
    direct_assumptions = pd.read_csv(paths["direct_voltage_assumptions"]).iloc[0]
    post = read_json(paths["post_erv_decision"])
    post_config = read_json(paths["post_erv_config"])
    detailed = read_json(paths["detailed_decision"])
    uncertainty = pd.read_csv(paths["detailed_uncertainty_scenarios"])
    thermal = pd.read_csv(paths["detailed_thermal_break_even"])
    modern_cases = pd.read_csv(paths["modern_reference_cases"])
    modern_summary = pd.read_csv(paths["modern_comparator_summary"])
    v39 = pd.read_csv(paths["receiver_v39_selected"])
    packaging = pd.read_csv(paths["historical_packaging"])
    study_audit = read_json(paths["current_study_audit"])
    direct_audit = read_json(paths["direct_analysis_audit"])
    post_audit = read_json(paths["post_erv_audit"])
    detailed_audit = read_json(paths["detailed_audit"])
    detailed_base = pd.read_csv(paths["detailed_base_cases"])
    modern_baseline_audit = read_json(paths["modern_baseline_audit"])
    v39_all = pd.read_csv(paths["receiver_v39_all_cases"])
    dense_cases = pd.read_csv(paths["post_erv_dense_cases"], low_memory=False)
    global_cases = pd.read_csv(paths["post_erv_global_cases"], low_memory=False)
    global_prcc = pd.read_csv(paths["post_erv_global_prcc"])

    dense_status = dense_cases["status"].value_counts(dropna=False).to_dict()
    global_status = global_cases["status"].value_counts(dropna=False).to_dict()
    expected_dense_status = {
        "target_reached": 659,
        "local_solver:profile_solve_failed": 409,
        "area_limit_before_target": 35,
        "nonpositive_net_flux": 19,
    }
    expected_global_status = {
        "target_reached": 390,
        "local_solver:profile_solve_failed": 81,
        "area_limit_before_target": 23,
        "nonpositive_net_flux": 18,
    }

    def prcc_value(parameter: str, output: str) -> float:
        selected = global_prcc.loc[
            global_prcc["parameter"].eq(parameter)
            & global_prcc["output"].eq(output),
            "prcc",
        ]
        if len(selected) != 1:
            raise ValueError(f"Expected one PRCC row for {parameter} -> {output}")
        return finite(selected.iloc[0])

    drag_parameter = "water_drag"
    diffusion_parameter = "diffusive_permeability_d_c_over_l_mol_m2_s_activity"
    current_parameter = "uniform_current_density_a_m2"
    resistance_parameter = "total_reference_area_resistance_ohm_m2"
    area_output = "required_active_area_m2"
    saving_output = "incremental_saving_kw_vs_passive_erv"
    voltage_output = "maximum_required_terminal_voltage_signed_v"
    prcc_metrics = {
        "area_drag": prcc_value(drag_parameter, area_output),
        "area_d_c_over_l": prcc_value(diffusion_parameter, area_output),
        "area_current": prcc_value(current_parameter, area_output),
        "saving_current": prcc_value(current_parameter, saving_output),
        "saving_drag": prcc_value(drag_parameter, saving_output),
        "saving_d_c_over_l": prcc_value(diffusion_parameter, saving_output),
        "saving_total_asr": prcc_value(resistance_parameter, saving_output),
        "voltage_drag": prcc_value(drag_parameter, voltage_output),
        "voltage_d_c_over_l": prcc_value(diffusion_parameter, voltage_output),
        "voltage_current": prcc_value(current_parameter, voltage_output),
    }

    cap = finite(settings["direct_voltage_cap_v"])
    direct_2v = direct.loc[
        direct["source_study"].eq("global_v53")
        & np.isclose(direct["cell_voltage_cap_tested_v"].astype(float), cap)
        & as_bool(direct["per_cap_robust_pass"])
    ].copy()
    if direct_2v.empty:
        raise ValueError("No robust global_v53 coordinates at the configured <=2 V cap")
    receiver_be = direct_2v["receiver_sec_break_even_signed_kwh_kg"].astype(float)
    direct_current_ka = direct_2v["total_current_ka"].astype(float)
    literal_headroom = direct_2v["selected_cap_voltage_headroom_v"].astype(float)
    robust_headroom_requirement = finite(
        read_json(paths["post_erv_config"])["direct_eo"]["robust_voltage_headroom_v"]
    )
    excess_robust_headroom = literal_headroom - robust_headroom_requirement
    eta_product = finite(direct_assumptions["ionic_current_efficiency"]) * finite(
        direct_assumptions["electronics_efficiency"]
    )
    voltage_step = finite(settings["direct_incremental_fixed_loss_step_v"])
    added_loss_power_kw = direct_current_ka * voltage_step / eta_product

    direct_receiver_2v = direct_receiver.loc[
        direct_receiver["source_study"].eq("global_v53")
        & np.isclose(direct_receiver["cell_voltage_cap_tested_v"].astype(float), cap)
    ].copy()
    if direct_receiver_2v.empty:
        raise ValueError("Direct receiver summary has no configured <=2 V rows")
    direct_sec_010 = direct_receiver_2v.loc[
        np.isclose(direct_receiver_2v["receiver_sec_assumed_kwh_kg"], 0.1)
    ].iloc[0]
    direct_sec_015 = direct_receiver_2v.loc[
        np.isclose(direct_receiver_2v["receiver_sec_assumed_kwh_kg"], 0.15)
    ].iloc[0]

    best_screen = post["best_dense"]
    best_detail = detailed["best_detailed_isothermal_case"]
    duty = finite(best_detail.get("incremental_water_removal_target_kg_h")) if (
        "incremental_water_removal_target_kg_h" in best_detail
    ) else finite(best_screen["incremental_water_removal_target_kg_h"])
    detailed_margin = finite(best_detail["detailed_incremental_saving_kw"])
    screening_margin = finite(best_screen["incremental_saving_kw_vs_passive_erv"])
    receiver_be_detailed = detailed_margin / duty
    receiver_be_screening = screening_margin / duty
    receiver_residual_010 = detailed_margin - 0.1 * duty
    receiver_residual_015 = detailed_margin - 0.15 * duty

    closure_case = str(best_detail["closure_case_id"])
    current_uncertainty = uncertainty.loc[
        uncertainty["closure_case_id"].eq(closure_case)
    ].copy()
    if current_uncertainty.empty:
        raise ValueError(f"No uncertainty scenarios for {closure_case}")
    uncertainty_saving = current_uncertainty["detailed_incremental_saving_kw"].astype(float)
    uncertainty_count = int(len(current_uncertainty))
    uncertainty_positive = int((uncertainty_saving > 0.0).sum())

    thermal_best = thermal.loc[
        thermal["closure_case_id"].eq(closure_case)
        & np.isclose(
            thermal["joule_heat_to_process_fraction"].astype(float),
            finite(settings["thermal_joule_fraction_for_boundary"]),
        )
    ]
    if len(thermal_best) != 1:
        raise ValueError("Thermal boundary selection must identify exactly one row")
    thermal_best = thermal_best.iloc[0]

    primary_v39 = v39.loc[
        np.isclose(v39["airflow_cfm"].astype(float), finite(settings["v39_primary_airflow_cfm"]))
    ].sort_values("eo_path_total_electric_kw", kind="mergesort")
    if primary_v39.empty:
        raise ValueError("No v39 primary-airflow receiver result")
    primary_v39 = primary_v39.iloc[0]

    comparator_id = str(settings["modern_comparator_candidate_id"])
    modern_case = modern_cases.loc[modern_cases["candidate_id"].eq(comparator_id)]
    modern_range = modern_summary.loc[modern_summary["candidate_id"].eq(comparator_id)]
    if len(modern_case) != 1 or len(modern_range) != 1:
        raise ValueError("Modern comparator candidate must identify one detail and one summary row")
    modern_case = modern_case.iloc[0]
    modern_range = modern_range.iloc[0]

    package = packaging.loc[packaging["candidate_id"].eq(comparator_id)]
    if len(package) != 1:
        raise ValueError("Historical packaging candidate must identify one row")
    package = package.iloc[0]

    low_voltage_group = optional.get("direct_eo_low_voltage_study_v1", {})
    low_voltage_available = bool(low_voltage_group.get("available", False))
    low_voltage_note = "canonical optional output unavailable"
    low_voltage_metrics: dict[str, Any] = {}
    if low_voltage_available:
        source_provenance_path = low_voltage_group["paths"][
            "source_generator_provenance.json"
        ]
        study_audit_path = low_voltage_group["paths"]["study_audit.json"]
        audit_path = low_voltage_group["paths"]["analysis/analysis_audit.json"]
        register_path = low_voltage_group["paths"]["analysis/low_voltage_cap_register.csv"]
        low_source_provenance = read_json(source_provenance_path)
        low_study_audit = read_json(study_audit_path)
        low_audit = read_json(audit_path)
        low_register = pd.read_csv(register_path, low_memory=False)
        if (
            low_source_provenance.get("status") != "PASS"
            or low_study_audit.get("status") != "PASS"
            or low_audit.get("status") != "PASS"
        ):
            raise ValueError(
                "Canonical low-voltage output is present but provenance/study/analysis "
                "audit is not PASS"
            )
        primary = low_register.loc[
            np.isclose(low_register["cell_voltage_cap_tested_v"].astype(float), cap)
        ].copy()
        required_columns = {
            "membrane_operating_pass_at_cap",
            "modern_comparator_positive_before_receiver_pass",
            "strict_physical_and_architecture_pass",
            "hard_area_recomputed_pass",
            "robust_process_activity_pass",
            "cell_voltage_required_mean_v",
            "cell_voltage_required_max_v",
            "eo_grid_power_kw",
            "modern_comparator_margin_before_receiver_kw",
            "receiver_sink_net_kg_h",
            "voltage_electrode_overpotential_v",
            "voltage_interface_v",
        }
        missing = required_columns.difference(primary.columns)
        if missing:
            raise ValueError(f"Canonical low-voltage register lacks columns: {sorted(missing)}")
        low_voltage_metrics = {
            "cap_rows": int(len(primary)),
            "membrane_pass_rows": int(as_bool(primary["membrane_operating_pass_at_cap"]).sum()),
            "modern_positive_before_receiver_rows": int(
                as_bool(primary["modern_comparator_positive_before_receiver_pass"]).sum()
            ),
        }
        base_gate = (
            as_bool(primary["strict_physical_and_architecture_pass"])
            & as_bool(primary["hard_area_recomputed_pass"])
            & as_bool(primary["robust_process_activity_pass"])
        )
        baseline_fixed = (
            primary["voltage_electrode_overpotential_v"].astype(float)
            + primary["voltage_interface_v"].astype(float)
        )
        mean_voltage = primary["cell_voltage_required_mean_v"].astype(float)
        maximum_voltage = primary["cell_voltage_required_max_v"].astype(float)
        eo_grid_power = primary["eo_grid_power_kw"].astype(float)
        modern_margin = primary["modern_comparator_margin_before_receiver_kw"].astype(float)
        water_duty = primary["receiver_sink_net_kg_h"].astype(float)
        fixed_boundaries: dict[str, dict[str, Any]] = {}
        for receiver_sec in map(
            float, settings["low_voltage_continuous_receiver_sec_boundaries_kwh_kg"]
        ):
            margin_after_receiver = modern_margin - receiver_sec * water_duty
            energy_limited_fixed = (
                baseline_fixed + margin_after_receiver * mean_voltage / eo_grid_power
            )
            voltage_limited_fixed = baseline_fixed + (cap - maximum_voltage)
            allowable = pd.concat(
                [energy_limited_fixed, voltage_limited_fixed], axis=1
            ).min(axis=1)
            allowable = allowable.where(base_gate)
            if not allowable.notna().any():
                raise ValueError("No low-voltage base-gate row for continuous loss boundary")
            best_index = allowable.idxmax()
            best_row = primary.loc[best_index]
            key = f"{receiver_sec:.6g}"
            fixed_boundaries[key] = {
                "receiver_sec_kwh_kg": receiver_sec,
                "maximum_allowed_combined_fixed_loss_v": finite(allowable.loc[best_index]),
                "transport_number_reference_t_w": finite(best_row["transport_number_reference_t_w"]),
                "current_density_a_m2": finite(best_row["current_density_a_m2"]),
                "water_diffusivity_scale_vs_pfsa": finite(best_row["water_diffusivity_scale_vs_pfsa"]),
                "limiting_mechanism": (
                    "ENERGY"
                    if energy_limited_fixed.loc[best_index]
                    <= voltage_limited_fixed.loc[best_index]
                    else "VOLTAGE"
                ),
            }
        fixed_scenario = finite(
            settings["low_voltage_fixed_loss_receiver_break_even_scenario_v"]
        )
        scenario_mean_voltage = mean_voltage - baseline_fixed + fixed_scenario
        scenario_max_voltage = maximum_voltage - baseline_fixed + fixed_scenario
        scenario_eo_power = eo_grid_power * scenario_mean_voltage / mean_voltage
        scenario_margin = modern_margin - (scenario_eo_power - eo_grid_power)
        scenario_receiver_be = scenario_margin / water_duty
        scenario_pass = base_gate & (scenario_max_voltage <= cap + 1e-9)
        scenario_receiver_be = scenario_receiver_be.where(scenario_pass)
        if not scenario_receiver_be.notna().any():
            raise ValueError("No low-voltage base-gate row at configured fixed-loss scenario")
        best_be_index = scenario_receiver_be.idxmax()
        best_be_row = primary.loc[best_be_index]
        low_voltage_metrics["continuous_fixed_loss_boundaries"] = fixed_boundaries
        low_voltage_metrics["fixed_loss_receiver_break_even"] = {
            "combined_fixed_loss_v": fixed_scenario,
            "maximum_receiver_break_even_kwh_kg": finite(
                scenario_receiver_be.loc[best_be_index]
            ),
            "modern_margin_before_receiver_kw": finite(
                scenario_margin.loc[best_be_index]
            ),
            "water_duty_kg_h": finite(water_duty.loc[best_be_index]),
            "transport_number_reference_t_w": finite(
                best_be_row["transport_number_reference_t_w"]
            ),
            "current_density_a_m2": finite(best_be_row["current_density_a_m2"]),
            "water_diffusivity_scale_vs_pfsa": finite(
                best_be_row["water_diffusivity_scale_vs_pfsa"]
            ),
        }
        low_voltage_note = (
            f"canonical optional output included: {low_voltage_metrics['membrane_pass_rows']} "
            f"membrane-pass rows at {cap:g} V; continuous fixed-loss boundaries computed "
            "with transport/current held fixed"
        )

    if low_voltage_available:
        fixed = low_voltage_metrics["continuous_fixed_loss_boundaries"]
        fixed_be = low_voltage_metrics["fixed_loss_receiver_break_even"]
        q05_evidence = (
            f"Canonical <=2 V study has {low_voltage_metrics['membrane_pass_rows']}/"
            f"{low_voltage_metrics['cap_rows']} membrane-operating passes and "
            f"{low_voltage_metrics['modern_positive_before_receiver_rows']} modern-comparator "
            "positive rows at the inherited 0.85 V electrode+interface loss. Maximum allowed "
            f"combined loss is {fixed['0']['maximum_allowed_combined_fixed_loss_v']:.6f} V "
            "with zero receiver load and "
            f"{fixed['0.003']['maximum_allowed_combined_fixed_loss_v']:.6f} V at receiver "
            f"SEC 0.003 kWh/kg. At 0.2 V fixed loss, best receiver break-even is "
            f"{fixed_be['maximum_receiver_break_even_kwh_kg']:.7f} kWh/kg. The older v53 "
            f"control retains {len(direct_2v)} robust coordinates and only "
            f"{excess_robust_headroom.min():.4f}-{excess_robust_headroom.max():.4f} V "
            "beyond its registered 0.25 V reserve."
        )
        q05_rule = (
            "Replay with measured electrode/interface loss and common terminal voltage. "
            f"The fixed-transport envelope permits at most "
            f"{fixed['0']['maximum_allowed_combined_fixed_loss_v']:.6f} V combined loss "
            "before receiver energy and "
            f"{fixed['0.003']['maximum_allowed_combined_fixed_loss_v']:.6f} V at receiver "
            "SEC 0.003 kWh/kg; these are post-processing bounds, not device validation. "
            "Preserve the 2 V cap and introduce no current-density acceptance limit."
        )
    else:
        q05_evidence = (
            f"Main direct register has {len(direct_2v)} robust coordinates at 2 V, but only "
            f"{excess_robust_headroom.min():.4f}-{excess_robust_headroom.max():.4f} V "
            "beyond the registered 0.25 V reserve. An extra 0.1 V costs "
            f"{added_loss_power_kw.min():.2f}-{added_loss_power_kw.max():.2f} kW. "
            f"Optional low-voltage status: {low_voltage_note}."
        )
        q05_rule = (
            "Replay with measured electrode/interface loss and common terminal voltage. "
            "Preserve the 2 V cap and 0.25 V robustness reserve; no current-density "
            "acceptance limit may be introduced."
        )

    q05_source_ids = [
        "direct_per_cap_register",
        "direct_receiver_summary",
        "direct_voltage_assumptions",
    ]
    if low_voltage_available:
        q05_source_ids.append("direct_eo_low_voltage_study_v1")

    boundaries: list[dict[str, Any]] = []
    add = boundaries.append
    add(boundary_row("B01", "Q01", "EO_AFTER_ERV", "receiver_all_in_break_even", receiver_be_detailed, "kWh/kg_water", "Detailed isothermal margin divided by incremental water duty", "All omitted receiver and balance-of-plant electricity together must stay below this nominal boundary.", ["detailed_decision", "post_erv_decision"]))
    add(boundary_row("B02", "Q01", "EO_AFTER_ERV", "receiver_screening_break_even", receiver_be_screening, "kWh/kg_water", "Dense screening margin divided by incremental water duty", "Screening-only upper boundary; it must not replace the detailed boundary.", ["post_erv_decision"]))
    add(boundary_row("B03", "Q01", "EO_AFTER_ERV", "residual_saving_after_receiver_sec_0p10", receiver_residual_010, "kW", "Receiver SEC = 0.10 kWh/kg", "Remaining nominal detailed margin after the declared receiver load.", ["detailed_decision", "post_erv_decision"]))
    add(boundary_row("B04", "Q01", "EO_AFTER_ERV", "residual_saving_after_receiver_sec_0p15", receiver_residual_015, "kW", "Receiver SEC = 0.15 kWh/kg", "Negative means the receiver alone exceeds the nominal detailed margin.", ["detailed_decision", "post_erv_decision"]))
    add(boundary_row("B05", "Q01", "HISTORICAL_CLOSED_RECEIVER_V39", "receiver_electric_sec", primary_v39["receiver_electric_sec_kwh_kg"], "kWh/kg_water", "30,000 cfm; lowest EO-path electricity at this airflow", "Historical closed-loop stress result; different duty and material boundary, retained as sign-risk evidence.", ["receiver_v39_selected", "receiver_v39_summary"]))
    add(boundary_row("B06", "Q01", "HISTORICAL_CLOSED_RECEIVER_V39", "net_system_saving", primary_v39["net_system_saving_kw"], "kW", "Same selected v39 row", "Negative historical closed-receiver outcome.", ["receiver_v39_selected"]))

    add(boundary_row("B07", "Q02", "EO_AFTER_ERV", "detailed_passive_erv_ac_reference", best_detail["detailed_passive_erv_plus_ac_reference_kw"], "kW", "60-segment R1234ze(E) detailed reference", "Comparator power used for the detailed incremental result.", ["detailed_decision"]))
    add(boundary_row("B08", "Q02", "EO_AFTER_ERV", "detailed_heiq_total_at_break_even_comparator", best_detail["detailed_total_erv_eo_ac_power_kw"], "kW", "Current selected detailed EO row", "A comparator at or below this power removes the current EO advantage.", ["detailed_decision"]))
    add(boundary_row("B09", "Q02", "HISTORICAL_MODERN_COMPARATOR", "o30_nominal_saving_vs_modern_ac_erv", modern_case["conditional_saving_kw_vs_modern_ac_erv"], "kW", comparator_id, "Historical O30 result against a modern AC+ERV comparator.", ["modern_reference_cases"]))
    add(boundary_row("B10", "Q02", "HISTORICAL_MODERN_COMPARATOR", "o30_minimum_saving_sensitivity", modern_range["minimum_saving_pct"], "%", comparator_id, "Minimum registered comparator sensitivity result.", ["modern_comparator_summary"]))
    add(boundary_row("B11", "Q02", "HISTORICAL_MODERN_COMPARATOR", "o30_maximum_saving_sensitivity", modern_range["maximum_saving_pct"], "%", comparator_id, "Maximum registered comparator sensitivity result; range crosses zero but is not probabilistic.", ["modern_comparator_summary"]))

    add(boundary_row("B12", "Q03", "EO_AFTER_ERV", "thermal_break_even_effective_process_heat", thermal_best["break_even_effective_process_heat_kw"], "kW_thermal", "Selected detailed case; Joule-to-process fraction = 0", "Effective enthalpy boundary only; transport is not conjugately coupled.", ["detailed_thermal_break_even", "detailed_decision"]))
    add(boundary_row("B13", "Q03", "EO_AFTER_ERV", "thermal_break_even_specific_heat", thermal_best["break_even_effective_process_heat_kj_per_kg_water"], "kJ/kg_water", "Same selected thermal row", "Specific effective-process-heat boundary.", ["detailed_thermal_break_even"]))
    add(boundary_row("B14", "Q03", "EO_AFTER_ERV", "uncertainty_minimum_saving", uncertainty_saving.min(), "kW", f"{uncertainty_count} deterministic scenarios", "Minimum deterministic scenario, not a confidence bound.", ["detailed_uncertainty_scenarios"]))
    add(boundary_row("B15", "Q03", "EO_AFTER_ERV", "uncertainty_median_saving", uncertainty_saving.median(), "kW", f"{uncertainty_count} deterministic scenarios", "Median of a designed scenario set, not an expected value.", ["detailed_uncertainty_scenarios"]))
    add(boundary_row("B16", "Q03", "EO_AFTER_ERV", "uncertainty_maximum_saving", uncertainty_saving.max(), "kW", f"{uncertainty_count} deterministic scenarios", "Maximum deterministic scenario, not a confidence bound.", ["detailed_uncertainty_scenarios"]))
    add(boundary_row("B17", "Q08", "EO_AFTER_ERV", "registered_uncertainty_scenario_count", uncertainty_count, "count", closure_case, "Current evidence count; corrects stale V4 wording without editing V4.", ["detailed_uncertainty_scenarios"]))
    add(boundary_row("B18", "Q08", "EO_AFTER_ERV", "registered_positive_uncertainty_scenario_count", uncertainty_positive, "count", closure_case, "Positive deterministic scenario count; not a probability numerator.", ["detailed_uncertainty_scenarios"]))

    add(boundary_row("B19", "Q04", "EO_AFTER_ERV", "dense_positive_surface_direction_rows", post["dense_positive_surface_direction_count"], "count", f"of {post['dense_case_count']} dense rows", "Zero rows pass the named surface-direction diagnostic.", ["post_erv_decision"]))
    add(boundary_row("B20", "Q04", "EO_AFTER_ERV", "global_positive_surface_direction_rows", post["global_positive_surface_direction_count"], "count", f"of {post['global_case_count']} global rows", "Zero rows pass the named surface-direction diagnostic.", ["post_erv_decision"]))

    add(boundary_row("B21", "Q05", "DIRECT_EO", "robust_coordinates_at_2v", len(direct_2v), "count", "global_v53; per-cap robust gate", "Existing direct grid robust coordinates at the <=2 V cap.", ["direct_per_cap_register"]))
    add(boundary_row("B22", "Q05", "DIRECT_EO", "receiver_break_even_min_at_2v", receiver_be.min(), "kWh/kg_water", "robust global_v53 coordinates", "Lower edge of the direct-EO receiver budget.", ["direct_per_cap_register"]))
    add(boundary_row("B23", "Q05", "DIRECT_EO", "receiver_break_even_median_at_2v", receiver_be.median(), "kWh/kg_water", "robust global_v53 coordinates", "Median is descriptive across sampled coordinates, not probabilistic.", ["direct_per_cap_register"]))
    add(boundary_row("B24", "Q05", "DIRECT_EO", "receiver_break_even_max_at_2v", receiver_be.max(), "kWh/kg_water", "robust global_v53 coordinates", "Upper edge of the direct-EO receiver budget.", ["direct_per_cap_register"]))
    add(boundary_row("B25", "Q05", "DIRECT_EO", "positive_coordinates_after_receiver_sec_0p10", direct_sec_010["positive_coordinates_after_receiver_energy"], "count", f"of {int(direct_sec_010['robust_coordinates_before_receiver_energy'])}", "Conditional positives at receiver SEC 0.10 kWh/kg.", ["direct_receiver_summary"]))
    add(boundary_row("B26", "Q05", "DIRECT_EO", "positive_coordinates_after_receiver_sec_0p15", direct_sec_015["positive_coordinates_after_receiver_energy"], "count", f"of {int(direct_sec_015['robust_coordinates_before_receiver_energy'])}", "Conditional positives at receiver SEC 0.15 kWh/kg.", ["direct_receiver_summary"]))
    add(boundary_row("B27", "Q05", "DIRECT_EO", "literal_voltage_headroom_min", literal_headroom.min(), "V", "robust <=2 V coordinates", "Minimum additional local voltage before the literal 2 V cap.", ["direct_per_cap_register"]))
    add(boundary_row("B28", "Q05", "DIRECT_EO", "headroom_beyond_registered_0p25v_reserve_min", excess_robust_headroom.min(), "V", "robust <=2 V coordinates", "Minimum extra loss before the registered 0.25 V robustness reserve is violated.", ["direct_per_cap_register", "post_erv_config"]))
    add(boundary_row("B29", "Q05", "DIRECT_EO", "grid_power_cost_of_extra_0p1v_min", added_loss_power_kw.min(), "kW", "total current and registered ionic/electronics efficiencies", "Minimum grid-power cost over robust <=2 V coordinates.", ["direct_per_cap_register", "direct_voltage_assumptions"]))
    add(boundary_row("B30", "Q05", "DIRECT_EO", "grid_power_cost_of_extra_0p1v_max", added_loss_power_kw.max(), "kW", "total current and registered ionic/electronics efficiencies", "Maximum grid-power cost over robust <=2 V coordinates.", ["direct_per_cap_register", "direct_voltage_assumptions"]))

    add(boundary_row("B31", "Q06", "HISTORICAL_O30_PACKAGING", "module_count", package["module_count"], "count", comparator_id, "Historical screening proxy, not a validated post-ERV module design.", ["historical_packaging"]))
    add(boundary_row("B32", "Q06", "HISTORICAL_O30_PACKAGING", "total_module_volume", package["total_module_volume_m3"], "m3", comparator_id, "Historical screening proxy with unvalidated headers/manifolds.", ["historical_packaging"]))
    if low_voltage_available:
        add(boundary_row("B33", "Q05", "DIRECT_EO_LOW_VOLTAGE_CANONICAL", "cap_rows_at_2v", low_voltage_metrics["cap_rows"], "count", "Canonical optional study; audit PASS", "All cap-expanded rows at the configured 2 V cap.", ["direct_eo_low_voltage_study_v1"]))
        add(boundary_row("B34", "Q05", "DIRECT_EO_LOW_VOLTAGE_CANONICAL", "membrane_operating_pass_rows_at_2v", low_voltage_metrics["membrane_pass_rows"], "count", "Canonical optional study; audit PASS", "Membrane-operating passes before receiver closure.", ["direct_eo_low_voltage_study_v1"]))
        add(boundary_row("B35", "Q05", "DIRECT_EO_LOW_VOLTAGE_CANONICAL", "modern_comparator_positive_rows_before_receiver", low_voltage_metrics["modern_positive_before_receiver_rows"], "count", "Canonical optional study; audit PASS", "Like-for-like modern-comparator positives before receiver energy.", ["direct_eo_low_voltage_study_v1"]))
        for offset, receiver_sec in enumerate(
            settings["low_voltage_continuous_receiver_sec_boundaries_kwh_kg"], start=36
        ):
            result = low_voltage_metrics["continuous_fixed_loss_boundaries"][
                f"{float(receiver_sec):.6g}"
            ]
            condition = (
                f"receiver SEC={float(receiver_sec):.6g} kWh/kg; maximum across sampled "
                f"base-gate rows; selected tw={result['transport_number_reference_t_w']:g}, "
                f"j={result['current_density_a_m2']:g}, "
                f"D-scale={result['water_diffusivity_scale_vs_pfsa']:g}; "
                f"limiting mechanism={result['limiting_mechanism']}"
            )
            add(boundary_row(
                f"B{offset}", "Q05", "DIRECT_EO_LOW_VOLTAGE_CANONICAL",
                "maximum_allowed_combined_electrode_interface_loss",
                result["maximum_allowed_combined_fixed_loss_v"], "V", condition,
                "Continuous post-processing boundary with solved transport, activity and current held fixed; not a common-voltage device replay or material probability.",
                ["direct_eo_low_voltage_study_v1"],
            ))
        fixed_be = low_voltage_metrics["fixed_loss_receiver_break_even"]
        add(boundary_row(
            "B40", "Q05", "DIRECT_EO_LOW_VOLTAGE_CANONICAL",
            "best_receiver_break_even_at_combined_fixed_loss_0p2v",
            fixed_be["maximum_receiver_break_even_kwh_kg"], "kWh/kg_water",
            f"combined electrode+interface loss={fixed_be['combined_fixed_loss_v']:.3f} V; maximum across sampled base-gate rows",
            "Best modern-comparator receiver budget in the fixed-transport/current post-processing envelope; not full-system closure.",
            ["direct_eo_low_voltage_study_v1"],
        ))
        add(boundary_row(
            "B41", "Q05", "DIRECT_EO_LOW_VOLTAGE_CANONICAL",
            "best_modern_margin_at_combined_fixed_loss_0p2v",
            fixed_be["modern_margin_before_receiver_kw"], "kW",
            f"same row as B40; water duty={fixed_be['water_duty_kg_h']:.3f} kg/h",
            "Margin before receiver energy used in the B40 identity.",
            ["direct_eo_low_voltage_study_v1"],
        ))
    add(boundary_row("B42", "Q09", "EO_AFTER_ERV_DENSE", "local_solver_profile_failures", dense_status.get("local_solver:profile_solve_failed", 0), "count", f"of {len(dense_cases)} dense rows", "Numerically unresolved rows; not evidence of a physical no-go.", ["post_erv_dense_cases", "post_erv_audit"]))
    add(boundary_row("B43", "Q09", "EO_AFTER_ERV_GLOBAL", "local_solver_profile_failures", global_status.get("local_solver:profile_solve_failed", 0), "count", f"of {len(global_cases)} global rows", "Numerically unresolved rows; not evidence of a physical no-go.", ["post_erv_global_cases", "post_erv_audit"]))
    add(boundary_row("B44", "Q09", "EO_AFTER_ERV_DENSE", "right_censored_area_limit_rows", dense_status.get("area_limit_before_target", 0), "count", f"at the 24,000 m2 observation cap; {len(dense_cases)} total rows", "Right-censored lower bounds, not required-area estimates or physical failures.", ["post_erv_dense_cases", "post_erv_audit"]))
    add(boundary_row("B45", "Q09", "EO_AFTER_ERV_GLOBAL", "right_censored_area_limit_rows", global_status.get("area_limit_before_target", 0), "count", f"at the 24,000 m2 observation cap; {len(global_cases)} total rows", "Right-censored lower bounds, not required-area estimates or physical failures.", ["post_erv_global_cases", "post_erv_audit"]))

    add(boundary_row("B46", "Q10", "EO_AFTER_ERV_GLOBAL", "observed_area_prcc_water_drag", prcc_metrics["area_drag"], "PRCC", "TARGET_REACHED observed-area rows; n=390", "Deterministic inverse-design rank sensitivity, not a material probability or independent raw-property effect.", ["post_erv_global_prcc"]))
    add(boundary_row("B47", "Q10", "EO_AFTER_ERV_GLOBAL", "observed_area_prcc_d_c_over_l", prcc_metrics["area_d_c_over_l"], "PRCC", "TARGET_REACHED observed-area rows; n=390", "D*C/L is the identified composite coordinate; raw D, C and L are not separated by this result.", ["post_erv_global_prcc"]))
    add(boundary_row("B48", "Q10", "EO_AFTER_ERV_GLOBAL", "observed_area_prcc_current_density", prcc_metrics["area_current"], "PRCC", "TARGET_REACHED observed-area rows; n=390", "Current is a sampling/control coordinate, not an acceptance limit.", ["post_erv_global_prcc"]))
    add(boundary_row("B49", "Q10", "EO_AFTER_ERV_GLOBAL", "saving_prcc_current_density", prcc_metrics["saving_current"], "PRCC", "TARGET_REACHED rows; n=390", "Deterministic inverse-design rank sensitivity; not a probability distribution.", ["post_erv_global_prcc"]))
    add(boundary_row("B50", "Q10", "EO_AFTER_ERV_GLOBAL", "saving_prcc_water_drag", prcc_metrics["saving_drag"], "PRCC", "TARGET_REACHED rows; n=390", "Must be interpreted as part of a correlated material vector.", ["post_erv_global_prcc"]))
    add(boundary_row("B51", "Q10", "EO_AFTER_ERV_GLOBAL", "saving_prcc_d_c_over_l", prcc_metrics["saving_d_c_over_l"], "PRCC", "TARGET_REACHED rows; n=390", "Composite-coordinate sensitivity, not independent diffusivity evidence.", ["post_erv_global_prcc"]))

    questions = [
        question_row(
            question_id="Q01", system_gap="Receiver and regeneration",
            current_status="OPEN_SIGN_SENSITIVE",
            evidence_finding=f"Detailed post-ERV margin is {detailed_margin:.3f} kW at {duty:.3f} kg/h; nominal all-in receiver/BOP break-even is {receiver_be_detailed:.5f} kWh/kg. Historical v39 reached {finite(primary_v39['receiver_electric_sec_kwh_kg']):.5f} kWh/kg and {finite(primary_v39['net_system_saving_kw']):.3f} kW net.",
            decision_impact_category="I_SIGN_OR_GO_NO_GO_CAN_CHANGE",
            decision_impact_basis="The current omitted-load budget is finite and an explicit closed-receiver stress case exceeded it and was negative.",
            closure_effort_category="II_BENCH_OR_SITE_MEASUREMENT_PLUS_REPLAY",
            closure_effort_basis="Requires a physical receiver or side-stream energy and water balance, followed by a full state-path replay.",
            next_experiment_or_replay="Operate the candidate receiver at the registered inlet/outlet activities and water duty; meter condensate or purge water, fans, heat, compressor, pressure drop and surface states.",
            acceptance_or_replay_rule=f"Replay the full receiver-to-HVAC chain. Nominal all-in added electricity must be below {receiver_be_detailed:.5f} kWh/kg; use 0.10 kWh/kg as the preferred screening target, not as measured evidence.",
            source_ids=["post_erv_decision", "detailed_decision", "receiver_v39_selected"],
        ),
        question_row(
            question_id="Q02", system_gap="HVAC and modern ERV comparator",
            current_status="OPEN_REFERENCE_AND_SITE_DATA",
            evidence_finding=f"Detailed reference is {finite(best_detail['detailed_passive_erv_plus_ac_reference_kw']):.3f} kW versus {finite(best_detail['detailed_total_erv_eo_ac_power_kw']):.3f} kW for the selected EO chain. Historical O30 comparator sensitivity spans {finite(modern_range['minimum_saving_pct']):.2f}% to {finite(modern_range['maximum_saving_pct']):.2f}%.",
            decision_impact_category="I_SIGN_OR_GO_NO_GO_CAN_CHANGE",
            decision_impact_basis="The registered comparator sensitivity crosses zero and the detailed EO advantage is only 47.968 kW.",
            closure_effort_category="II_BENCH_OR_SITE_MEASUREMENT_PLUS_REPLAY",
            closure_effort_basis="Needs measured ERV effectiveness/pressure and chiller-cycle/site data, then the registered detailed replay.",
            next_experiment_or_replay="Measure sensible and latent ERV effectiveness, both-side pressure drop, fan/motor power, entering states, condensing temperature and COP over representative operation.",
            acceptance_or_replay_rule=f"Run a like-for-like 60-segment replay. At the selected EO state, a reference at or below {finite(best_detail['detailed_total_erv_eo_ac_power_kw']):.3f} kW removes the nominal advantage.",
            source_ids=["detailed_decision", "modern_reference_cases", "modern_comparator_summary"],
        ),
        question_row(
            question_id="Q03", system_gap="Conjugate thermal coupling and refrigeration cycle",
            current_status="OPEN_SIGN_SENSITIVE",
            evidence_finding=f"Effective-heat break-even is {finite(thermal_best['break_even_effective_process_heat_kw']):.3f} kW, but the current deterministic scenario set spans {uncertainty_saving.min():.3f} to {uncertainty_saving.max():.3f} kW and is not transport-coupled.",
            decision_impact_category="I_SIGN_OR_GO_NO_GO_CAN_CHANGE",
            decision_impact_basis="Declared thermal/cycle scenarios cross zero for the selected case.",
            closure_effort_category="II_BENCH_OR_SITE_MEASUREMENT_PLUS_REPLAY",
            closure_effort_basis="Requires calorimetry and interface temperatures, followed by a conjugate transport/HVAC replay.",
            next_experiment_or_replay="Measure heat partition, interface temperature, Joule heat and cycle COP versus condensing temperature under representative current and humidity gradients.",
            acceptance_or_replay_rule="Replace the effective-enthalpy parameter with measured heat paths and rerun transport and HVAC iteratively to convergence; retain min/median/max as deterministic scenarios only.",
            source_ids=["detailed_decision", "detailed_thermal_break_even", "detailed_uncertainty_scenarios"],
        ),
        question_row(
            question_id="Q04", system_gap="Surface-direction interpretation and missing ionic potential",
            current_status="OPEN_ZERO_PASS_DIAGNOSTIC_INTERPRETATION",
            evidence_finding=f"Positive surface-direction diagnostic passes in 0/{post['dense_case_count']} dense rows and 0/{post['global_case_count']} global rows. Alternative sorption laws and independent ionic concentration potential are outside the transport result.",
            decision_impact_category="II_CURRENT_EVIDENCE_GATE_BLOCKED",
            decision_impact_basis="No tested post-ERV row passes the named passive-direction diagnostic, while its role as a hard gate versus an uphill-pumping diagnostic remains unresolved.",
            closure_effort_category="II_BENCH_OR_SITE_MEASUREMENT_PLUS_REPLAY",
            closure_effort_basis="Needs a thermodynamic sign audit plus surface-state coupon measurements and reinsertion into transport.",
            next_experiment_or_replay="Measure both gas-film surface activities, local current/voltage and net water flux under the registered uphill activity gradients.",
            acceptance_or_replay_rule="Declare whether passive surface direction is a hard gate or an uphill-pumping diagnostic, then replay an explicit ionic concentration-potential bound.",
            source_ids=["post_erv_decision", "post_erv_summary", "sorption_scope"],
        ),
        question_row(
            question_id="Q10", system_gap="Correlated membrane-property vector and identifiability",
            current_status="OPEN_INVERSE_DESIGN_NOT_MATERIAL_VALIDATION",
            evidence_finding=(
                f"Observed-area PRCC is drag {prcc_metrics['area_drag']:+.5f}, D*C/L "
                f"{prcc_metrics['area_d_c_over_l']:+.5f} and current "
                f"{prcc_metrics['area_current']:+.5f}; saving PRCC is current "
                f"{prcc_metrics['saving_current']:+.5f}, drag "
                f"{prcc_metrics['saving_drag']:+.5f}, D*C/L "
                f"{prcc_metrics['saving_d_c_over_l']:+.5f} and total ASR "
                f"{prcc_metrics['saving_total_asr']:+.5f}. Maximum-voltage PRCC is drag "
                f"{prcc_metrics['voltage_drag']:+.5f}, D*C/L "
                f"{prcc_metrics['voltage_d_c_over_l']:+.5f} and current "
                f"{prcc_metrics['voltage_current']:+.5f}. These are inverse-design rank "
                "sensitivities, not a material population."
            ),
            decision_impact_category="III_MATERIAL_REALITY_UNVALIDATED",
            decision_impact_basis="The model identifies D*C/L and L/sigma plus series ASR; it does not identify raw D, capacity and thickness independently or prove their simultaneous availability.",
            closure_effort_category="II_BENCH_OR_SITE_MEASUREMENT_PLUS_REPLAY",
            closure_effort_basis="Needs simultaneous measurements on the same conditioned samples, then a correlated-vector replay.",
            next_experiment_or_replay="Measure c(a,T), D(a,T), electro-osmotic drag, conductivity, membrane/contact ASR, wet/dry thickness and swelling on the same sample and batch over the relevant activity/current range.",
            acceptance_or_replay_rule="Do not rank or procure a material from independently favourable marginal values. Replay only measured correlated vectors or an explicitly evidenced covariance/convex-hull envelope.",
            source_ids=["post_erv_global_prcc", "post_erv_summary", "sorption_scope"],
        ),
        question_row(
            question_id="Q05", system_gap="Electrodes, common-voltage topology and direct EO below 2 V",
            current_status="OPEN_TOPOLOGY_AND_LOSS_VALIDATION",
            evidence_finding=q05_evidence,
            decision_impact_category="I_SIGN_OR_GO_NO_GO_CAN_CHANGE",
            decision_impact_basis="Receiver SEC moves the direct set from conditional passes to zero, and small unmeasured fixed losses consume large power at 214-232 kA.",
            closure_effort_category="II_BENCH_OR_SITE_MEASUREMENT_PLUS_REPLAY",
            closure_effort_basis="Needs polarization/EIS/contact data and a bounded common-voltage/current-sharing replay before module hardware.",
            next_experiment_or_replay="Measure polarization and EIS from 0-2 V with candidate electrodes, contacts and wet compression; map current distribution and converter/string topology.",
            acceptance_or_replay_rule=q05_rule,
            source_ids=q05_source_ids,
        ),
        question_row(
            question_id="Q09", system_gap="Solver failure and right-censoring",
            current_status="OPEN_NUMERICAL_COVERAGE_INCOMPLETE",
            evidence_finding=f"Dense rows: 659 target reached, 409 local profile-solver failures, 35 right-censored at the area cap and 19 nonpositive-net-flux rows. Global rows: 390, 81, 23 and 18 respectively. Solver-failure and censored rows are unresolved, not physical no-go evidence.",
            decision_impact_category="IV_DESIGN_SPACE_COVERAGE_INCOMPLETE",
            decision_impact_basis="A substantial part of the sampled map has no converged or explicitly bracketed physical classification.",
            closure_effort_category="I_EXISTING_DATA_REPLAY",
            closure_effort_basis="Can be addressed with bounded continuation, bracketing, smaller integration steps and explicit solver-status semantics using existing inputs.",
            next_experiment_or_replay="Replay failures with continuation from neighbouring converged states, smaller area steps and bracketed root checks; separately extend selected right-censored rows beyond the observation cap.",
            acceptance_or_replay_rule="Every replayed row must end as CONVERGED/TARGET_REACHED, explicitly bracketed NO_ROOT or a retained RIGHT_CENSORED lower bound. Numerical failure must never be relabelled physical infeasibility.",
            source_ids=["post_erv_dense_cases", "post_erv_global_cases", "post_erv_audit"],
        ),
        question_row(
            question_id="Q06", system_gap="Packaging, channels, headers and manifolds",
            current_status="OPEN_UNVALIDATED_HARDWARE",
            evidence_finding=f"Current detailed post-ERV study excludes architecture/manifolds/topology. Historical O30 screening used {int(package['module_count'])} modules and {finite(package['total_module_volume_m3']):.2f} m3, explicitly not validated product specifications.",
            decision_impact_category="V_FULL_SYSTEM_CLAIM_BLOCKED",
            decision_impact_basis="Current fan/geometry efficiency is assumed and no post-ERV discrete module/manifold design is evaluated.",
            closure_effort_category="III_MODULE_HARDWARE_PROGRAM",
            closure_effort_basis="Requires channel/spacer and multi-channel header hardware, not only a source-data replay.",
            next_experiment_or_replay="Measure single-channel mass transfer and pressure drop, then header maldistribution in a multi-channel module with realistic current feeds and sealing.",
            acceptance_or_replay_rule="Replay discrete module count, fan curves, pressure drop, footprint, current feeds and flow maldistribution using measured correlations.",
            source_ids=["detailed_summary", "historical_packaging", "historical_stage_gate"],
        ),
        question_row(
            question_id="Q07", system_gap="Lifetime and manufacturability",
            current_status="OPEN_NO_QUANTITATIVE_ENVELOPE",
            evidence_finding="The current study explicitly leaves lifetime and manufacturability unresolved; no degradation or production-variation envelope is registered.",
            decision_impact_category="VI_DECISION_COMMUNICATION_OR_QUALIFICATION",
            decision_impact_basis="This blocks durable annual and commercial claims after immediate physics/energy gates, but no current lifetime data quantify a sign reversal.",
            closure_effort_category="IV_LIFETIME_AND_MANUFACTURING_PROGRAM",
            closure_effort_basis="Requires cyclic ageing, batch variation and end-of-life measurements.",
            next_experiment_or_replay="Cycle wet/dry state, current, temperature and contaminants; periodically measure drag, D*C/L, ASR, film/pressure behaviour, swelling and delamination by batch.",
            acceptance_or_replay_rule="Replay beginning-, middle- and end-of-life property vectors over measured annual duty; report batch envelopes without invented probabilities.",
            source_ids=["current_study_summary", "historical_stage_gate"],
        ),
        question_row(
            question_id="Q08", system_gap="Uncertainty semantics and report reconciliation",
            current_status="CORRECTED_IN_THIS_REGISTER",
            evidence_finding=f"The current selected-case register contains {uncertainty_count} deterministic scenarios and {uncertainty_positive} positive rows, correcting the stale V4 wording of eight/five. The V4 files are not edited.",
            decision_impact_category="VI_DECISION_COMMUNICATION_OR_QUALIFICATION",
            decision_impact_basis="The correction changes evidence communication, not the underlying scenario outcomes or claim boundary.",
            closure_effort_category="I_EXISTING_DATA_REPLAY",
            closure_effort_basis="The correction is resolved directly from the hash-bound scenario register.",
            next_experiment_or_replay="Use the generated correction in the next report revision and continue to label the scenario set deterministic, not probabilistic.",
            acceptance_or_replay_rule=f"Any derived report must state {uncertainty_count} scenarios / {uncertainty_positive} positive and cite the hash-bound scenario CSV.",
            source_ids=["detailed_uncertainty_scenarios"],
        ),
    ]

    checks = [
        {"check_id": "detailed_power_identity", "passed": math.isclose(finite(best_detail["detailed_passive_erv_plus_ac_reference_kw"]) - finite(best_detail["detailed_total_erv_eo_ac_power_kw"]), detailed_margin, rel_tol=0.0, abs_tol=1e-9), "detail": "reference - HeiQ total equals detailed margin"},
        {"check_id": "receiver_break_even_identity", "passed": math.isclose(receiver_be_detailed * duty, detailed_margin, rel_tol=0.0, abs_tol=1e-9), "detail": "receiver break-even times duty equals detailed margin"},
        {"check_id": "uncertainty_scenario_correction", "passed": uncertainty_count == int(settings["expected_current_uncertainty_scenario_count"]) and uncertainty_positive == int(settings["expected_current_uncertainty_positive_count"]), "detail": f"registered current result is {uncertainty_count} scenarios / {uncertainty_positive} positive"},
        {"check_id": "uncertainty_not_probability", "passed": detailed.get("conditional_uncertainty_is_probability_model") is False, "detail": "detailed decision disables probabilistic interpretation"},
        {"check_id": "surface_direction_zero_passes", "passed": int(post["dense_positive_surface_direction_count"]) == 0 and int(post["global_positive_surface_direction_count"]) == 0, "detail": "surface-direction diagnostic is zero in dense and global registers"},
        {"check_id": "direct_cap_not_above_2v", "passed": cap <= 2.0 and np.isclose(direct_2v["cell_voltage_cap_tested_v"].astype(float), cap).all(), "detail": "all selected direct coordinates use the configured <=2 V cap"},
        {"check_id": "no_current_density_limit_in_post", "passed": post.get("current_density_limit_a_m2") is None, "detail": "post-ERV current density remains a sampling/control axis"},
        {"check_id": "v39_closed_receiver_is_negative", "passed": finite(primary_v39["net_system_saving_kw"]) < 0.0, "detail": "selected 30,000-cfm v39 stress row is negative"},
        {"check_id": "full_system_claim_disabled", "passed": config["claim_boundary"]["full_system_claim_allowed"] is False and detailed.get("full_system_claim_allowed") is False and post.get("full_system_claim_allowed") is False, "detail": "config and current decision summaries all disable full-system claims"},
        {"check_id": "upstream_audits_pass", "passed": study_audit.get("pass") is True and direct_audit.get("status") == "PASS" and post_audit.get("pass") is True and detailed_audit.get("pass") is True, "detail": "study, direct, post-ERV and detailed upstream audits pass"},
        {"check_id": "detailed_base_identity", "passed": len(detailed_base) == int(detailed["detailed_base_positive_count"]) and np.allclose(detailed_base["detailed_passive_erv_plus_ac_reference_kw"].astype(float) - detailed_base["detailed_total_erv_eo_ac_power_kw"].astype(float), detailed_base["detailed_incremental_saving_kw"].astype(float), rtol=0.0, atol=1e-9), "detail": "17 local full-study detailed rows retain the reference-total identity"},
        {"check_id": "modern_baseline_reproduction", "passed": modern_baseline_audit.get("pass") is True and math.isclose(finite(modern_baseline_audit["actual_kw"]), finite(best_screen["passive_erv_plus_ac_reference_kw"]), rel_tol=0.0, abs_tol=1e-9), "detail": "canonical 543.740564-kW screening comparator reproduces and matches post-ERV"},
        {"check_id": "v39_all_rows_negative", "passed": len(v39_all) == 9 and (v39_all["net_system_saving_kw"].astype(float) < 0.0).all(), "detail": "all 9 registered v39 membrane/receiver cases are negative"},
        {"check_id": "post_erv_solver_status_counts", "passed": len(dense_cases) == 1122 and len(global_cases) == 512 and dense_status == expected_dense_status and global_status == expected_global_status, "detail": "dense/global status counts exactly preserve targets, solver failures, censoring and nonpositive-flux rows"},
        {"check_id": "prcc_population_semantics", "passed": len(global_prcc) == 28 and set(global_prcc.loc[global_prcc["output"].eq(area_output), "complete_case_count"].astype(int)) == {390} and global_prcc["interpretation"].astype(str).str.contains("deterministic|rank association", case=False, regex=True).all(), "detail": "PRCC table is complete and retains deterministic inverse-design interpretations"},
    ]
    for check in checks:
        check["passed"] = bool(check["passed"])

    context = {
        "receiver_break_even_detailed_kwh_kg": receiver_be_detailed,
        "receiver_break_even_screening_kwh_kg": receiver_be_screening,
        "direct_receiver_break_even_min_kwh_kg": float(receiver_be.min()),
        "direct_receiver_break_even_median_kwh_kg": float(receiver_be.median()),
        "direct_receiver_break_even_max_kwh_kg": float(receiver_be.max()),
        "v39_receiver_sec_kwh_kg": finite(primary_v39["receiver_electric_sec_kwh_kg"]),
        "uncertainty_scenario_count": uncertainty_count,
        "uncertainty_positive_count": uncertainty_positive,
        "optional_low_voltage_available": low_voltage_available,
        "optional_low_voltage_metrics": low_voltage_metrics,
        "post_topology_evaluated": bool(best_screen.get("electrical_topology_evaluated", False)),
        "post_fixed_loss_voltage_v": finite(best_screen.get("fixed_loss_voltage_v", 0.0)),
        "post_power_electronics_efficiency": finite(post_config["post_erv"]["power_electronics_efficiency"]),
        "solver_status_counts": {
            "dense": {str(key): int(value) for key, value in dense_status.items()},
            "global": {str(key): int(value) for key, value in global_status.items()},
        },
        "global_prcc_metrics": prcc_metrics,
    }
    return pd.DataFrame(questions), pd.DataFrame(boundaries), context, checks


def save_figure(fig: plt.Figure, base: Path) -> None:
    fig.savefig(base.with_suffix(".png"), dpi=220, bbox_inches="tight", metadata={"Software": "analyze_open_questions_v1.py"})
    fig.savefig(base.with_suffix(".pdf"), bbox_inches="tight", metadata={"Creator": "analyze_open_questions_v1.py", "CreationDate": None, "ModDate": None})
    plt.close(fig)


def plot_impact_effort(
    register: pd.DataFrame, config: dict[str, Any], out_dir: Path
) -> None:
    impact_entries = config["ordinal_categories"]["decision_impact_high_to_low"]
    effort_entries = config["ordinal_categories"]["closure_effort_low_to_high"]
    impact_ids = [entry["id"] for entry in impact_entries]
    effort_ids = [entry["id"] for entry in effort_entries]
    impact_labels = [
        "Sign/go-no-go\ncan change",
        "Evidence gate\nblocked",
        "Material reality\nunvalidated",
        "Design-space coverage\nincomplete",
        "Full-system\nclaim blocked",
        "Communication /\nqualification",
    ]
    effort_labels = [
        "Existing-data\nreplay",
        "Bench/site measure\n+ replay",
        "Module hardware\nprogramme",
        "Lifetime / mfg.\nprogramme",
    ]
    xmap = {name: i for i, name in enumerate(effort_ids)}
    ymap = {name: len(impact_ids) - 1 - i for i, name in enumerate(impact_ids)}

    fig, ax = plt.subplots(figsize=(11.2, 8.2))
    for x in range(len(effort_ids)):
        ax.axvspan(x - 0.48, x + 0.48, color=PALE if x % 2 == 0 else WHITE, zorder=0)
    colors = {
        "OPEN_SIGN_SENSITIVE": RED,
        "OPEN_ZERO_PASS_DIAGNOSTIC_INTERPRETATION": RED,
        "OPEN_REFERENCE_AND_SITE_DATA": ORANGE,
        "OPEN_TOPOLOGY_AND_LOSS_VALIDATION": ORANGE,
        "OPEN_INVERSE_DESIGN_NOT_MATERIAL_VALIDATION": ORANGE,
        "OPEN_NUMERICAL_COVERAGE_INCOMPLETE": GOLD,
        "OPEN_UNVALIDATED_HARDWARE": GOLD,
        "OPEN_NO_QUANTITATIVE_ENVELOPE": SLATE,
        "CORRECTED_IN_THIS_REGISTER": TEAL,
    }
    grouped: dict[tuple[int, int], list[Any]] = {}
    for row in register.itertuples(index=False):
        key = (
            xmap[row.closure_effort_category],
            ymap[row.decision_impact_category],
        )
        grouped.setdefault(key, []).append(row)
    for (x, y), rows in grouped.items():
        for index, row in enumerate(rows):
            dx = (index - 0.5 * (len(rows) - 1)) * 0.19
            ax.scatter(x + dx, y, s=680, color=colors.get(row.current_status, NAVY), edgecolor=WHITE, linewidth=1.5, zorder=3)
            ax.text(x + dx, y, row.question_id, color=WHITE, ha="center", va="center", weight="bold", fontsize=10, zorder=4)

    ax.set_xticks(range(len(effort_ids)), effort_labels)
    ax.set_yticks(range(len(impact_ids)), list(reversed(impact_labels)))
    ax.set_xlim(-0.55, len(effort_ids) - 0.45)
    ax.set_ylim(-0.55, len(impact_ids) - 0.45)
    ax.grid(axis="y", color="#C8D3D9", linewidth=0.8)
    fig.subplots_adjust(top=0.83, bottom=0.18, left=0.18, right=0.98)
    fig.suptitle("Open questions: decision impact versus closure effort", x=0.18, y=0.97, ha="left", color=INK, weight="bold", fontsize=15)
    fig.text(0.18, 0.915, "Rule-based ordinal categories — positions are not numeric scores or probabilities", color=SLATE, fontsize=9.5)
    ax.set_xlabel("Increasing closure effort →", color=INK, labelpad=12)
    ax.set_ylabel("Decision implication", color=INK, labelpad=12)
    for spine in ax.spines.values():
        spine.set_visible(False)
    save_figure(fig, out_dir / "figures" / "01_impact_vs_closure_effort")


def plot_break_even(boundaries: pd.DataFrame, out_dir: Path) -> None:
    values = boundaries.set_index("boundary_id")["numeric_value"]
    direct_min = values["B22"]
    direct_med = values["B23"]
    direct_max = values["B24"]
    post_detailed = values["B01"]
    post_screening = values["B02"]
    v39 = values["B05"]

    canonical_available = "B40" in values.index
    fig, ax = plt.subplots(figsize=(11.2, 6.2))
    if canonical_available:
        y_direct, y_post, y_v39, y_canonical = 2, 1, 0, 3
    else:
        y_direct, y_post, y_v39 = 2, 1, 0
    ax.errorbar(
        direct_med,
        y_direct,
        xerr=[[direct_med - direct_min], [direct_max - direct_med]],
        fmt="o",
        color=NAVY,
        ecolor=NAVY,
        elinewidth=5,
        capsize=7,
        markersize=8,
        label="Direct EO historical no-ERV / 425-kW range",
    )
    ax.scatter(post_detailed, y_post, s=95, color=TEAL_DARK, zorder=3, label="Post-ERV detailed")
    ax.scatter(post_screening, y_post, s=90, facecolor=WHITE, edgecolor=TEAL_DARK, linewidth=2, zorder=3, label="Post-ERV screening")
    ax.scatter(v39, y_v39, marker="X", s=125, color=RED, zorder=3, label="Historical v39 closed receiver")
    if canonical_available:
        canonical_be = values["B40"]
        ax.scatter(canonical_be, y_canonical, marker="D", s=90, color=ORANGE, zorder=3, label="Canonical direct EO: 0.2 V fixed-loss upper bound")
        ax.axvline(0.003, color=ORANGE, linestyle=":", linewidth=1.4)
        ax.text(canonical_be + 0.002, y_canonical, f"{canonical_be:.6f}", ha="left", va="center", color=ORANGE, fontsize=8.7)
    ax.axvline(0.10, color=ORANGE, linestyle="--", linewidth=1.7)
    ax.axvline(0.15, color=RED, linestyle="--", linewidth=1.7)
    ax.text(0.10, 2.42, "0.10 scenario", ha="center", color=ORANGE, fontsize=9)
    ax.text(0.15, 2.42, "0.15 scenario", ha="center", color=RED, fontsize=9)
    ax.text(direct_med, y_direct + 0.13, f"{direct_min:.4f}–{direct_max:.4f}", ha="center", color=NAVY, fontsize=8.7)
    ax.text(post_detailed - 0.001, 0.82, f"detailed {post_detailed:.4f}", ha="right", color=TEAL_DARK, fontsize=8.7)
    ax.text(post_screening + 0.001, 1.14, f"screening {post_screening:.4f}", ha="left", color=TEAL_DARK, fontsize=8.7)
    ax.text(v39, -0.18, f"{v39:.4f}", ha="center", color=RED, fontsize=8.7)
    if canonical_available:
        ax.set_yticks(
            [y_canonical, y_direct, y_post, y_v39],
            [
                "Canonical direct EO ≤2 V\nmodern comparator; fixed loss 0.2 V",
                "Direct EO ≤2 V\nhistorical no-ERV / 425-kW ledger",
                "EO after ERV",
                "v39 historical stress",
            ],
        )
    else:
        ax.set_yticks(
            [y_direct, y_post, y_v39],
            ["Direct EO ≤2 V — historical no-ERV / 425-kW ledger", "EO after ERV", "v39 historical stress"],
        )
    ax.set_xlabel("Receiver / omitted-load specific electricity [kWh/kg water]")
    ax.set_xlim(0.0 if canonical_available else 0.08, max(0.19, v39 + 0.01))
    ax.set_ylim(-0.55, 3.65 if canonical_available else 2.65)
    ax.grid(axis="x", color="#D1D9DE", linewidth=0.8)
    fig.subplots_adjust(top=0.82, bottom=0.18, left=0.19, right=0.98)
    fig.suptitle("Receiver-energy break-even boundaries", x=0.19, y=0.97, ha="left", color=INK, weight="bold", fontsize=15)
    fig.text(0.19, 0.91, "Architecture-specific deterministic ledgers; v39 is a historical stress result, not a probability sample", color=SLATE, fontsize=9.5)
    ax.legend(loc="lower left", frameon=False, ncol=2, fontsize=8.8)
    for spine in ax.spines.values():
        spine.set_visible(False)
    save_figure(fig, out_dir / "figures" / "02_receiver_break_even")


def plot_decision_chain(out_dir: Path) -> None:
    nodes = [
        ("Membrane +\nsurface physics", "interpretation unresolved\n0/1122 passive-direction", RED),
        ("Electrodes +\ntopology", "not evaluated", ORANGE),
        ("Receiver +\nregeneration", "energy open", RED),
        ("Thermal +\nHVAC replay", "sign crosses", RED),
        ("Measured ERV +\ncomparator", "site data open", ORANGE),
        ("Module +\nlifetime", "unvalidated", GOLD),
        ("Full-system\nclaim", "DISABLED", NAVY),
    ]
    fig, ax = plt.subplots(figsize=(14.4, 4.3))
    ax.set_xlim(0, len(nodes))
    ax.set_ylim(0, 1)
    ax.axis("off")
    for i, (title, status, color) in enumerate(nodes):
        x = i + 0.08
        box = FancyBboxPatch(
            (x, 0.34),
            0.84,
            0.38,
            boxstyle="round,pad=0.02,rounding_size=0.035",
            facecolor=color,
            edgecolor=WHITE,
            linewidth=1.5,
        )
        ax.add_patch(box)
        ax.text(x + 0.42, 0.56, title, color=WHITE, ha="center", va="center", weight="bold", fontsize=9.3)
        status_size = 6.5 if i == 0 else 8.1
        ax.text(x + 0.42, 0.40, status, color=WHITE, ha="center", va="center", fontsize=status_size)
        if i < len(nodes) - 1:
            arrow = FancyArrowPatch((x + 0.86, 0.53), (x + 1.04, 0.53), arrowstyle="-|>", mutation_scale=15, linewidth=1.3, color=SLATE)
            ax.add_patch(arrow)
    ax.text(0.08, 0.91, "Decision chain: every upstream gate must remain explicit", color=INK, weight="bold", fontsize=15)
    ax.text(0.08, 0.79, "A positive conditional membrane/HVAC row cannot bypass a failed or unmeasured downstream link.", color=SLATE, fontsize=10)
    ax.text(0.08, 0.15, "Current state: receiver/HVAC/surface can change go/no-go; packaging and lifetime qualify only a surviving physical architecture.", color=INK, fontsize=9.6)
    save_figure(fig, out_dir / "figures" / "03_decision_chain")


def write_summary(
    path: Path,
    register: pd.DataFrame,
    boundaries: pd.DataFrame,
    context: dict[str, Any],
    source_records: list[dict[str, Any]],
    optional: dict[str, dict[str, Any]],
) -> None:
    b = boundaries.set_index("boundary_id")["numeric_value"]
    lines = [
        "# Open questions analysis v1",
        "",
        "## Status",
        "",
        "Computational evidence audit: **PASS**. Full-system claim: **DISABLED**.",
        "",
        "Analysen bruker hashbundne eksisterende resultater. Ordinale kategorier beskriver dokumentert beslutningsimplikasjon og typen arbeid som gjenstår; de er ikke numeriske scorer. De deterministiske scenarioene er ikke sannsynligheter.",
        "",
        "## Viktigste beslutningsgrenser",
        "",
        f"- EO etter ERV: detaljert nominell all-in receiver/BOP-grense er **{b['B01']:.5f} kWh/kg vann**; screeninggrensen er {b['B02']:.5f} kWh/kg.",
        f"- Ved receiver-SEC 0,10 kWh/kg gjenstår **{b['B03']:.3f} kW**; ved 0,15 kWh/kg er resultatet **{b['B04']:.3f} kW**.",
        f"- Historisk no-ERV/425-kW robusthetsledger for direkte EO ved 2 V: {int(b['B21'])} robuste koordinater og receiver break-even {b['B22']:.5f}–{b['B24']:.5f} kWh/kg (median {b['B23']:.5f}); dette er ikke modern-komparator-resultatet.",
        f"- En ekstra 0,1 V fast tap i direkte EO koster {b['B29']:.2f}–{b['B30']:.2f} kW over de robuste 2-V-koordinatene.",
        f"- Termisk effektiv-heat break-even for valgt detaljcase er {b['B12']:.3f} kW termisk, men de deklarerte scenariene går fra {b['B14']:.3f} til {b['B16']:.3f} kW elektrisk margin.",
        f"- Post-ERV-dekning: {int(b['B42'])} dense og {int(b['B43'])} globale solverfeil er numerisk uavklarte; {int(b['B44'])} og {int(b['B45'])} rader er høyresensurert ved arealtaket.",
        f"- Membranvektor: observert areal styres i rang av drag ({b['B46']:+.3f}), D*C/L ({b['B47']:+.3f}) og strøm ({b['B48']:+.3f}); dette er inverse-design-PRCC, ikke en materialpopulasjon.",
        "",
    ]
    if context["optional_low_voltage_available"]:
        fixed = context["optional_low_voltage_metrics"]["continuous_fixed_loss_boundaries"]
        fixed_be = context["optional_low_voltage_metrics"]["fixed_loss_receiver_break_even"]
        lines.extend(
            [
                f"- Canonical lavspenning: {context['optional_low_voltage_metrics']['membrane_pass_rows']}/{context['optional_low_voltage_metrics']['cap_rows']} membranpass, men 0 modern-komparator-positive ved arvet 0,85 V fixed loss.",
                f"- Maksimal samlet elektrode+interface-loss er {fixed['0']['maximum_allowed_combined_fixed_loss_v']:.6f} V uten receiver og {fixed['0.003']['maximum_allowed_combined_fixed_loss_v']:.6f} V ved receiver-SEC 0,003 kWh/kg.",
                f"- Ved samlet fixed loss 0,2 V er beste modern-komparator receiver break-even bare {fixed_be['maximum_receiver_break_even_kwh_kg']:.7f} kWh/kg.",
            ]
        )
    lines.extend(["", "## Prioritert lukking", ""])
    for row in register.itertuples(index=False):
        lines.append(
            f"- **{row.question_id} — {row.system_gap}:** {row.current_status}. "
            f"Impact `{row.decision_impact_category}`; effort `{row.closure_effort_category}`. "
            f"{row.evidence_finding}"
        )
    lines.extend(
        [
            "",
            "## Rapportkorrigering",
            "",
            f"Gjeldende hashbundne output har **{context['uncertainty_scenario_count']} deterministiske scenarier, hvorav {context['uncertainty_positive_count']} er positive** for valgt D=1e-10, j=5-case. Dette erstatter ordlyden «åtte hjørner / fem positive» i en senere rapportrevisjon. V4-rapportfilene er ikke endret av denne analysen.",
            "",
            "## Valgfri lavspenningsstudie",
            "",
            (
                "Den kanoniske `outputs/direct_eo_low_voltage_study_v1` ble funnet og hashbundet."
                if context["optional_low_voltage_available"]
                else "Den kanoniske `outputs/direct_eo_low_voltage_study_v1` var ikke tilgjengelig. Analysen bruker derfor det eksisterende v53-baserte 2-V-registeret og erstatter ikke dette med en kandidatmappe."
            ),
            "",
            "## Evidensbinding",
            "",
            f"- Obligatoriske kildefiler: {sum(bool(r['available']) for r in source_records)}/{len(source_records)} tilgjengelige og hashverifiserte.",
            f"- Valgfrie kildegrupper tilgjengelig: {sum(bool(v['available']) for v in optional.values())}/{len(optional)}.",
            "- Full kildeproveniens, kontroller og output-hasher står i `audit.json`.",
            "",
            "## Claim boundary",
            "",
            "Resultatene rangerer ikke materialer eller tiltak med oppdiktede sannsynligheter. De lukker ikke receiver, konjugert termikk, elektrodetopologi, modulhardware, levetid eller produksjonsvariasjon. Positive tall er derfor fortsatt betingede modellresultater.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_analysis(
    config_path: Path = DEFAULT_CONFIG,
    out_dir: Path | None = None,
    require_empty_out_dir: bool = False,
) -> dict[str, Any]:
    config_path = config_path.resolve()
    config = read_json(config_path)
    validate_config(config)
    if out_dir is None:
        out_dir = (ROOT / str(config["output_directory"])).resolve()
    else:
        out_dir = out_dir.resolve()
    if require_empty_out_dir and out_dir.exists() and any(out_dir.iterdir()):
        raise FileExistsError(f"Output directory is not empty: {out_dir}")
    (out_dir / "figures").mkdir(parents=True, exist_ok=True)

    paths, source_records, optional = bind_sources(config)
    register, boundaries, context, checks = build_analysis(config, paths, optional)
    register.to_csv(out_dir / "open_question_register.csv", index=False, float_format="%.12g")
    boundaries.to_csv(out_dir / "quantified_decision_boundaries.csv", index=False, float_format="%.12g")
    plot_impact_effort(register, config, out_dir)
    plot_break_even(boundaries, out_dir)
    plot_decision_chain(out_dir)
    write_summary(out_dir / "SUMMARY.md", register, boundaries, context, source_records, optional)

    output_names = [
        "open_question_register.csv",
        "quantified_decision_boundaries.csv",
        "SUMMARY.md",
        "figures/01_impact_vs_closure_effort.png",
        "figures/01_impact_vs_closure_effort.pdf",
        "figures/02_receiver_break_even.png",
        "figures/02_receiver_break_even.pdf",
        "figures/03_decision_chain.png",
        "figures/03_decision_chain.pdf",
    ]
    output_records = []
    for name in output_names:
        path = out_dir / name
        output_records.append(
            {
                "relative_path": name,
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
        )

    audit = {
        "study_id": config["study_id"],
        "script": str(Path(__file__).resolve()),
        "script_sha256": sha256_file(Path(__file__).resolve()),
        "config": str(config_path),
        "config_sha256": sha256_file(config_path),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if all(bool(item["passed"]) for item in checks) else "FAIL",
        "checks": checks,
        "source_bindings": source_records,
        "optional_source_groups": {
            key: {
                "available": value["available"],
                "directory": value["directory"],
                "rule": value["rule"],
                "files": value["records"],
            }
            for key, value in optional.items()
        },
        "output_files": output_records,
        "row_counts": {
            "open_question_register": int(len(register)),
            "quantified_decision_boundaries": int(len(boundaries)),
        },
        "claim_boundary": config["claim_boundary"],
        "ordinal_category_definitions": config["ordinal_categories"],
        "report_correction": {
            **config["analysis_settings"]["report_correction"],
            "observed_scenario_count": context["uncertainty_scenario_count"],
            "observed_positive_count": context["uncertainty_positive_count"],
            "correction_pass": context["uncertainty_scenario_count"] == 27
            and context["uncertainty_positive_count"] == 16,
        },
        "analysis_context": context,
    }
    (out_dir / "audit.json").write_text(
        json.dumps(audit, indent=2, sort_keys=True, default=json_default) + "\n",
        encoding="utf-8",
    )
    if audit["status"] != "PASS":
        failed = [item["check_id"] for item in checks if not item["passed"]]
        raise RuntimeError(f"Open-questions audit failed: {failed}")
    return audit


def main() -> None:
    args = parse_args()
    audit = run_analysis(args.config, args.out_dir, args.require_empty_out_dir)
    print(json.dumps({"status": audit["status"], "row_counts": audit["row_counts"]}, indent=2))


if __name__ == "__main__":
    main()
