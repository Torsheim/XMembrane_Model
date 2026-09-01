#!/usr/bin/env python3
"""Build the complete cross-study result atlas used by the Trond report.

The atlas is deliberately broader than the current-evidence register.  It
retains historically important negative controls and boundary studies, but
labels their evidence class and comparison boundary so that old screening
numbers cannot silently become current system claims.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd


TROND_ROOT = Path(__file__).resolve().parents[1]
HEIQ_ROOT = TROND_ROOT.parent
MODEL_ROOT = HEIQ_ROOT / "XMembrane_Model"
V2_ROOT = HEIQ_ROOT / "HeiQ_V2"
THERMO_ROOT = HEIQ_ROOT / "HeiQ-Thermodynamical-Analysis"
DOWNLOADS = Path("/mnt/c/Users/mariu/Downloads")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def add_metric(
    rows: list[dict[str, Any]],
    *,
    result_id: str,
    date: str,
    era: str,
    theme: str,
    study: str,
    target: str,
    metric: str,
    value: float,
    unit: str,
    boundary: str,
    evidence_class: str,
    decision_status: str,
    source: Path,
    interpretation: str,
    full_system_claim_allowed: bool = False,
) -> None:
    rows.append(
        {
            "result_id": result_id,
            "date": date,
            "era": era,
            "theme": theme,
            "study": study,
            "target": target,
            "metric": metric,
            "numeric_value": float(value),
            "unit": unit,
            "comparison_boundary": boundary,
            "evidence_class": evidence_class,
            "decision_status": decision_status,
            "full_system_claim_allowed": bool(full_system_claim_allowed),
            "source_path": str(source.resolve()),
            "source_exists": source.is_file(),
            "source_sha256": sha256_file(source) if source.is_file() else "",
            "interpretation": interpretation,
        }
    )


def build_result_atlas() -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    thermo_summary = THERMO_ROOT / "outputs/decision_summary/decision_summary.md"
    early = dict(
        date="2026-07-02",
        era="A · Thermodynamic framing",
        theme="thermodynamics",
        study="Model 1–2 energy and area envelope",
        target="generic",
        boundary="30 C/80% RH to 22 C/50% RH; 1 kg/s dry air",
        evidence_class="historical_thermodynamic_screen",
        decision_status="retained_requirement",
        source=thermo_summary,
    )
    for rid, metric, value, unit, note in [
        ("A01", "conservative_SEC_low_for_5pct_saving", 125.0, "Wh/kg", "Lower edge of the suggested conservative 5% product envelope."),
        ("A02", "conservative_SEC_high_for_5pct_saving", 175.0, "Wh/kg", "Upper edge; depends on heat return and scenario."),
        ("A03", "conservative_SEC_low_for_10pct_saving", 100.0, "Wh/kg", "Lower edge of the suggested conservative 10% envelope."),
        ("A04", "conservative_SEC_high_for_10pct_saving", 150.0, "Wh/kg", "Upper edge; not a measured product SEC."),
        ("A05", "full_latent_water_load", 48.048584, "kg/h per kg/s dry air", "Psychrometric scaling anchor."),
        ("A06", "area_at_100_g_m2_h_flux", 480.48584, "m2 per kg/s dry air", "Inverse flux–area scaling; no coupled membrane physics."),
        ("A07", "area_at_1000_g_m2_h_flux", 48.048584, "m2 per kg/s dry air", "Inverse flux–area scaling; no coupled membrane physics."),
    ]:
        add_metric(rows, result_id=rid, metric=metric, value=value, unit=unit, interpretation=note, **early)

    hvac_path = V2_ROOT / "outputs/wp1_free_predrying_explicit_cop/free_predrying_energy_cop_summary.csv"
    hvac = pd.read_csv(hvac_path).set_index("case")
    for target, rid in [("O50", "A08"), ("O30", "A09")]:
        row = hvac.loc[target]
        add_metric(
            rows,
            result_id=rid,
            date="2026-07-09",
            era="A · Thermodynamic framing",
            theme="HVAC",
            study="Explicit-COP free pre-drying comparison",
            target=target,
            metric="compressor_electric_saved",
            value=row["compressor_electric_saved_kw"],
            unit="kW at 50,000 cfm",
            boundary="No ERV; equal downstream supply service; reheat electricity excluded",
            evidence_class="historical_HVAC_duty_point",
            decision_status="gross_opportunity_only",
            source=hvac_path,
            interpretation="Gross compressor opportunity before complete EO subsystem loads.",
        )
        add_metric(
            rows,
            result_id=rid + "b",
            date="2026-07-09",
            era="A · Thermodynamic framing",
            theme="HVAC",
            study="Explicit-COP free pre-drying comparison",
            target=target,
            metric="aircon_COP",
            value=row["cop_cooling"],
            unit="-",
            boundary="Compressor-only cycle model",
            evidence_class="historical_HVAC_duty_point",
            decision_status="aircon_only",
            source=hvac_path,
            interpretation="Not a combined EO+HVAC COP.",
        )

    for rid, target, metric, value, unit, note in [
        ("A10", "generic", "simple_break_even_SEC_at_COP3", 237.085, "Wh/kg", "Latent-only first-pass value; excludes receiver, fans and heat rejection."),
        ("A11", "generic", "simple_break_even_SEC_at_COP5", 142.251, "Wh/kg", "Latent-only first-pass value; excludes receiver, fans and heat rejection."),
        ("A12", "O50", "water_removal", 33.557362, "kg/h per kg/s dry air", "Psychrometric duty anchor used in the realistic-coil work."),
        ("A13", "O30", "water_removal", 55.396222, "kg/h per kg/s dry air", "Psychrometric duty anchor used in the realistic-coil work."),
        ("A14", "O50", "gross_compressor_saving_at_COP3", 7.956977, "kW per kg/s dry air", "Gross AC opportunity, not EO system saving."),
        ("A15", "O30", "gross_compressor_saving_at_COP3", 13.134, "kW per kg/s dry air", "Gross AC opportunity, not EO system saving."),
    ]:
        add_metric(
            rows,
            result_id=rid,
            date="2026-07-07",
            era="A · Thermodynamic framing",
            theme="HVAC",
            study="Simple-COP psychrometric opportunity",
            target=target,
            metric=metric,
            value=value,
            unit=unit,
            boundary="Latent-only COP screen; 1 kg/s dry-air basis",
            evidence_class="historical_first_pass_energy_screen",
            decision_status="gross_opportunity_only",
            source=THERMO_ROOT / "outputs/decision_summary/decision_summary.md",
            interpretation=note,
        )

    for rid, target, compressor, cop in [
        ("A16", "O80", 389.111261, 4.506175),
        ("A17", "O50", 232.117448, 4.834815),
        ("A18", "O30", 130.522550, 5.159224),
    ]:
        add_metric(
            rows,
            result_id=rid,
            date="2026-07-09",
            era="A · Thermodynamic framing",
            theme="HVAC",
            study="Explicit-COP 50,000-cfm compressor cases",
            target=target,
            metric="compressor_electric_power",
            value=compressor,
            unit="kW",
            boundary="50,000 cfm; active reheat electricity excluded",
            evidence_class="historical_HVAC_duty_point",
            decision_status="aircon_only",
            source=hvac_path,
            interpretation=f"Explicit refrigerant-cycle result; cooling COP={cop:.3f}.",
        )

    results_so_far = DOWNLOADS / "HeiQ_Results_So_Far_Explainer_Rev2_PlotRich.pdf"
    nafion = dict(
        date="2026-07-28",
        era="B · Local material screens",
        theme="materials",
        study="Correlated H-Nafion 1 V negative control",
        target="O50/O30",
        boundary="Explicit 1 V full-cell accounting",
        evidence_class="historical_correlated_reference",
        decision_status="negative_control",
        source=results_so_far,
    )
    for rid, metric, value, unit, note in [
        ("B01", "central_drag_SEC_low", 1.83, "kWh/kg", "Central n_d=0.82 sensitivity; far above energy budget."),
        ("B02", "central_drag_SEC_high", 1.95, "kWh/kg", "Central n_d=0.82 sensitivity; far above energy budget."),
        ("B03", "optimistic_drag_SEC_low", 0.58, "kWh/kg", "Optimistic n_d=2.6 still above the old ~0.172 kWh/kg budget."),
        ("B04", "optimistic_drag_SEC_high", 0.62, "kWh/kg", "Optimistic n_d=2.6 still above the old ~0.172 kWh/kg budget."),
        ("B05", "O50_area_low", 2453.0, "m2", "Area can pass while electricity fails."),
        ("B06", "O50_area_high", 2621.0, "m2", "Area can pass while electricity fails."),
        ("B07", "O30_area_low", 4089.0, "m2", "Fails the declared historical 3000 m2 screen."),
        ("B08", "O30_area_high", 4368.0, "m2", "Fails the declared historical 3000 m2 screen."),
    ]:
        add_metric(rows, result_id=rid, metric=metric, value=value, unit=unit, interpretation=note, **nafion)

    oracle = dict(
        date="2026-07-30",
        era="B · Local material screens",
        theme="materials",
        study="Independent-property oracle V2–V7",
        target="O50/O30",
        boundary="Local/symmetric dry-receiver screens; properties independently selectable",
        evidence_class="historical_inverse_property_oracle",
        decision_status="hypothetical_requirement",
        source=results_so_far,
    )
    for rid, metric, value, unit, note in [
        ("B09", "best_O50_power_Amax3000", 0.25, "kW", "Gate-specific material substitution allowed."),
        ("B10", "best_O30_power_Amax3000", 0.70, "kW", "Gate-specific material substitution allowed."),
        ("B11", "best_O50_power_Amax1500", 0.49, "kW", "Not the same material as other area gates."),
        ("B12", "best_O30_power_Amax1500", 1.38, "kW", "Not the same material as other area gates."),
        ("B13", "best_O50_power_Amax300", 3.32, "kW", "Fantasy-grid oracle; historical current gate applied."),
        ("B14", "best_O30_power_Amax300", 17.51, "kW", "Fantasy-grid oracle; historical current gate applied."),
        ("B15", "M14424_drag_boundary", 120.0, "mol H2O/mol charge", "Maximum searched drag, not a measured material."),
        ("B16", "M14424_diffusivity_boundary", 1e-12, "m2/s", "Minimum searched diffusivity."),
        ("B17", "axial_V3_target_reaching", 28.0, "rows", "All successes were O50 with imposed dry receiver."),
        ("B18", "axial_V3_O30_target_reaching", 0.0, "rows", "O30 was not demonstrated in the V3 snapshot."),
    ]:
        add_metric(rows, result_id=rid, metric=metric, value=value, unit=unit, interpretation=note, **oracle)

    v8_report = DOWNLOADS / "HeiQ_V8_fullfort_materialsok_resultatrapport_2026-08-03.pdf"
    v8 = dict(
        date="2026-08-03",
        era="C · Axial V8–V11",
        theme="materials_transport",
        study="Completed axial independent-material sweep V8",
        target="O50/O30",
        boundary="150,000 cfm; fixed receiver assumptions; historical area/current gates",
        evidence_class="full_historical_parameter_sweep",
        decision_status="inverse_design_evidence",
        source=v8_report,
    )
    for rid, metric, value, unit, note in [
        ("C01", "evaluated_target_rows", 32256, "rows", "Complete 2304-material × 7-voltage × 2-target grid."),
        ("C02", "O50_target_reaching", 3560, "rows", "22.1% of O50 rows."),
        ("C03", "O30_target_reaching", 864, "rows", "5.4% of O30 rows."),
        ("C04", "O50_energy_positive", 2932, "rows", "Old incomplete auxiliary boundary."),
        ("C05", "O30_energy_positive", 608, "rows", "Old incomplete auxiliary boundary."),
        ("C06", "O50_low_aux_area", 5871.6, "m2", "M08786 at 0.02376 V."),
        ("C07", "O50_low_aux_power", 13.57, "kW", "EO grid plus idealised process fan only."),
        ("C08", "O30_low_aux_area", 5530.1, "m2", "M08794 at 0.18817 V."),
        ("C09", "O30_low_aux_power", 128.26, "kW", "EO grid plus idealised process fan only."),
        ("C10", "O50_min_energy_positive_area", 1056.5, "m2", "Power rises to 289.19 kW."),
        ("C11", "O30_min_energy_positive_area", 2169.5, "m2", "Power rises to 476.03 kW."),
        ("C12", "pareto_rows", 153, "rows", "115 O50 and 38 O30 rows."),
        ("C13", "pareto_rows_touching_property_boundary", 153, "rows", "No stable interior optimum."),
        ("C14", "pareto_rows_at_minimum_diffusivity", 149, "rows", "Strong direction toward low effective passive transport."),
        ("C15", "absolute_min_O50_area", 904.4, "m2", "Target-reaching but ~1979.5 kW and energy-negative."),
        ("C16", "absolute_min_O30_area", 1637.0, "m2", "Target-reaching but ~3267.8 kW and energy-negative."),
    ]:
        add_metric(rows, result_id=rid, metric=metric, value=value, unit=unit, interpretation=note, **v8)

    v11_report = DOWNLOADS / "HeiQ_V11_spenningsraffinering_resultatrapport_2026-08-03.pdf"
    v11 = dict(
        date="2026-08-03",
        era="C · Axial V8–V11",
        theme="materials_transport",
        study="V11 voltage refinement",
        target="O50/O30",
        boundary="Refinement of selected V8 candidates; historical nested gates",
        evidence_class="full_historical_refinement",
        decision_status="voltage_resolution_and_tradeoff",
        source=v11_report,
    )
    for rid, metric, value, unit, note in [
        ("C17", "O50_low_aux_power", 13.57, "kW", "No energy improvement from V8."),
        ("C18", "O50_low_aux_area", 5872, "m2", "M08786."),
        ("C19", "O30_low_aux_power", 123.51, "kW", "M11675; 4.75 kW below V8 low-power point."),
        ("C20", "O30_low_aux_area", 5922, "m2", "M11675."),
        ("C21", "O50_min_area", 1039, "m2", "Requires 296.12 kW."),
        ("C22", "O30_min_area", 2131, "m2", "Requires 487.26 kW."),
        ("C23", "O50_lowest_integrated_current", 109, "kA", "~70% below prior low-power candidate."),
        ("C24", "O30_lowest_integrated_current", 180, "kA", "~70% below prior low-power candidate."),
        ("C25", "candidates_reaching_300m2", 0, "count", "Historical zero result; not a current acceptance criterion."),
        ("C26", "O30_candidates_reaching_1500m2", 0, "count", "Historical zero result; not a current acceptance criterion."),
    ]:
        add_metric(rows, result_id=rid, metric=metric, value=value, unit=unit, interpretation=note, **v11)

    terminal12_report = DOWNLOADS / "HeiQ_Terminal1_2_Results_and_Discussion_v2.pdf"
    t12 = dict(
        date="2026-08-14",
        era="D · Coupled V12.1 / Terminal 1–2",
        theme="coupled_transport_receiver",
        study="Terminal 1 and 2 pre-architecture closure",
        target="O30",
        boundary="150,000 cfm; O80→O30; controlled gas receiver; no modern ERV comparator",
        evidence_class="full_coupled_prearchitecture_study",
        decision_status="historical_regression_and_mechanism",
        source=terminal12_report,
    )
    for rid, metric, value, unit, note in [
        ("D01", "selected_voltage", 0.98, "V", "Selected independent-property vector."),
        ("D02", "selected_area", 8922.21294, "m2", "Not a practical module design."),
        ("D03", "selected_core_power", 115.01772, "kW", "EO plus generic process and receiver channel fans."),
        ("D04", "selected_core_SEC", 0.02634445, "kWh/kg", "Incomplete pre-architecture core."),
        ("D05", "receiver_process_flow_ratio", 2.53749, "-", "~373,339 cfm receiver air."),
        ("D06", "receiver_airflow", 373338.7, "cfm", "Unclosed air resource."),
        ("D07", "water_activity_voltage_fraction", 99.983, "%", "Axial-mean reversible voltage contribution."),
        ("D08", "backdiffusion_fraction_upper", 0.008, "% of EO", "Specific to the selected very-low-D point."),
        ("D09", "target_reaching_material_plateau", 21, "vectors", "Broad energy plateau, not a unique material optimum."),
        ("D10", "best_vs_M11675_power_improvement", 0.058, "%", "Below model uncertainty; do not rank as a unique recipe."),
        ("D11", "core_power_receiver_band_0p4_0p6", 115.02, "kW", "Baseline receiver band."),
        ("D12", "core_power_receiver_band_0p1_0p3", 23.61, "kW", "Artificially drier receiver; sink energy not closed."),
        ("D13", "core_power_double_both_film_coefficients", 90.69, "kW", "21.1% below baseline."),
        ("D14", "core_power_reduction_tenfold_both_films", 43.4, "%", "Mass transfer is important but not free hydraulically."),
        ("D15", "core_power_at_4500m2", 148.01, "kW", "Area–energy Pareto."),
        ("D16", "core_power_at_6000m2", 124.94, "kW", "Area–energy Pareto."),
        ("D17", "conditional_no_ERV_saving", 669.87, "kW", "57.38%; not a modern AC+ERV comparison."),
        ("D18", "conditional_no_ERV_saving_percent", 57.38, "%", "Receiver resource and regeneration remain open."),
    ]:
        add_metric(rows, result_id=rid, metric=metric, value=value, unit=unit, interpretation=note, **t12)

    stage_gate = DOWNLOADS / "HeiQ_WP1_Stage_Gate_1_Current_Model_Status_2026-08-05.pdf"
    v14_common = dict(
        date="2026-08-05",
        era="E · V14 architecture hypotheses",
        theme="architecture_system_ledger",
        study="V14 stage-gate design comparison",
        boundary="No-ERV gross opportunity; stored architecture screen",
        evidence_class="historical_architecture_screen",
        decision_status="physical_gate_failed",
        source=stage_gate,
    )
    for target, values in {
        "O50": [("E01", "installed_area", 5200, "m2"), ("E02", "EO_grid_power", 8.15, "kW"), ("E03", "receiver_thermal_package", 219.58, "kW"), ("E04", "full_predryer_SEC", 0.0894, "kWh/kg"), ("E05", "conditional_peak_margin", 225.9, "kW")],
        "O30": [("E06", "installed_area", 4930, "m2"), ("E07", "EO_grid_power", 110.83, "kW"), ("E08", "receiver_thermal_package", 326.83, "kW"), ("E09", "full_predryer_SEC", 0.1075, "kWh/kg"), ("E10", "conditional_peak_margin", 286.8, "kW")],
    }.items():
        for rid, metric, value, unit in values:
            add_metric(rows, result_id=rid, target=target, metric=metric, value=value, unit=unit, interpretation="Both selected rows failed the physical architecture gate.", **v14_common)

    v13_summary = V2_ROOT / "outputs/axial_independent_material_sweep_v8/coarse/voltage_refinement_v11/closed_receiver_system_v12/system_regeneration_module_v13/study/summary.md"
    for rid, target, metric, value, unit, note in [
        ("E30", "O30", "receiver_regeneration_budget_low", 0.1125, "kWh/kg", "Remaining historical budget at area <=6000 m2."),
        ("E31", "O30", "receiver_regeneration_budget_high", 0.1372, "kWh/kg", "Remaining historical budget at area <=6000 m2."),
        ("E32", "O50", "receiver_regeneration_budget_low", 0.1442, "kWh/kg", "Remaining historical budget at area <=6000 m2."),
        ("E33", "O50", "receiver_regeneration_budget_high", 0.1661, "kWh/kg", "Remaining historical budget at area <=6000 m2."),
        ("E34", "O30", "lowest_wall_admissible_regeneration_package", 0.2277, "kWh/kg", "Already above the O30 budget."),
        ("E35", "O30", "Carnot_regeneration_lower_bound", 0.1523, "kWh/kg", "Even the lower bound exceeded part of the remaining budget."),
        ("E36", "O30", "illustrative_module_count", 95, "modules", "11,400 cells and at least 32.7 m2 rack footprint."),
    ]:
        add_metric(rows, result_id=rid, date="2026-08-04", era="E · V14 architecture hypotheses", theme="receiver_regeneration", study="V13 regeneration and module closure", target=target, metric=metric, value=value, unit=unit, boundary="Historical V12/V13 closed-receiver budget", evidence_class="full_historical_regeneration_study", decision_status="regeneration_exceeds_budget", source=v13_summary, interpretation=note)

    v14_nested = V2_ROOT / "outputs/axial_independent_material_sweep_v8/coarse/voltage_refinement_v11/closed_receiver_system_v12/architecture_hypothesis_tests_v14/study_v14_1_1_exact_mesh/summary.md"
    for rid, metric, value, unit, note in [
        ("E40", "axial_profiles", 200, "count", "Architecture source profiles."),
        ("E41", "geometry_topology_rows", 50688, "rows", "Broad architecture grid."),
        ("E42", "positive_rankable_arithmetic_rows", 80, "rows", "Positive arithmetic did not imply physics pass."),
        ("E43", "physical_architecture_gate_pass", 0, "rows", "Central V14 result."),
        ("E44", "best_conditional_margin", 286.82, "kW", "Not a physical or product result."),
        ("E45", "positive_unrankable_boundary_rows", 513, "rows", "Raw-positive but not rankable."),
    ]:
        add_metric(rows, result_id=rid, date="2026-08-04", era="E · V14 architecture hypotheses", theme="architecture_system_ledger", study="V14 architecture hypothesis grid", target="O50/O30", metric=metric, value=value, unit=unit, boundary="Stored V14.1.1 exact-mesh screen", evidence_class="full_historical_architecture_grid", decision_status="zero_physical_gate_pass", source=v14_nested, interpretation=note)

    closure_o50 = V2_ROOT / "outputs/receiver_closure_v2_study/receiver_closure_status.json"
    closure_o30 = V2_ROOT / "outputs/receiver_closure_o30_actual_v1_study/receiver_closure_status.json"
    two_stage = V2_ROOT / "outputs/two_stage_receiver_coupling_v1_2_study/two_stage_status.json"
    for rid, target, metric, value, unit, src, note in [
        ("E11", "O50", "working_baselines", 25, "count", closure_o50, "None passed the 0.02 robust surface gate or full module gate."),
        ("E12", "O50", "selected_area", 3200.0977, "m2", closure_o50, "Selected positive-margin single stage."),
        ("E13", "O50", "selected_known_power", 197.0207, "kW", closure_o50, "Conditional known ledger only."),
        ("E14", "O50", "selected_surface_margin", 0.014354, "activity", closure_o50, "Positive, below historical robustness flag."),
        ("E15", "O30", "working_baselines", 0, "count", closure_o30, "Five completed single-stage cases; none working."),
        ("E16", "O30", "selected_failure_diagnostic_area", 4197.7789, "m2", closure_o30, "Selected only for failure diagnosis."),
        ("E17", "O30", "selected_failure_diagnostic_power", 350.1761, "kW", closure_o30, "Physical direction failed."),
        ("E18", "O30", "selected_surface_margin", -0.290004, "activity", closure_o30, "Strongly negative."),
        ("E19", "O50", "two_stage_grid_cases", 72, "count", two_stage, "48 completed, zero full-coupled passes."),
        ("E20", "O50", "two_stage_full_coupled_pass", 0, "count", two_stage, "Complexity did not close the gate."),
        ("E21", "O50", "two_stage_selected_known_power", 157.6133, "kW", two_stage, "Selected row still failed."),
        ("E22", "O50", "two_stage_selected_area", 7429.8751, "m2", two_stage, "Selected row still failed."),
    ]:
        add_metric(
            rows, result_id=rid, date="2026-08-06", era="E · V14 architecture hypotheses",
            theme="receiver_architecture", study="Single- and two-stage receiver closure", target=target,
            metric=metric, value=value, unit=unit, boundary="V14 architecture mutation studies",
            evidence_class="full_historical_architecture_study", decision_status="no_full_coupled_pass",
            source=src, interpretation=note,
        )

    liquid_cross = V2_ROOT / "outputs/direct_liquid_activity_crossover_v1/crossover_summary.csv"
    saturated_summary = V2_ROOT / "outputs/saturated_receiver_liquid_drain_v1/SUMMARY.md"
    for rid, target, metric, value, unit, note in [
        ("E23", "O30", "minimum_liquid_penalty_vs_gas", 53.2432, "kW", "No crossover in activity 0.7–1.0."),
        ("E24", "O50", "minimum_liquid_penalty_vs_gas", 27.4192, "kW", "No crossover in activity 0.7–1.0."),
    ]:
        add_metric(rows, result_id=rid, date="2026-08-14", era="E · V14 architecture hypotheses", theme="liquid_receiver", study="Direct-liquid activity crossover", target=target, metric=metric, value=value, unit=unit, boundary="Free heat rejection upper bound; gas-reference core comparison", evidence_class="historical_mechanism_screen", decision_status="liquid_not_better_in_tested_range", source=liquid_cross, interpretation=note)
    for rid, target, value in [("E25", "O30", 0.0), ("E26", "O50", 0.0)]:
        add_metric(rows, result_id=rid, date="2026-08-12", era="E · V14 architecture hypotheses", theme="liquid_receiver", study="Saturated receiver / ideal liquid drain", target=target, metric="liquid_product_in_reported_best_rows", value=value, unit="kg/h", boundary="Co-current saturation-cap screen", evidence_class="historical_phase_boundary_screen", decision_status="drain_not_demonstrated", source=saturated_summary, interpretation="The reported best rows did not actually produce liquid product.")

    v33_1 = V2_ROOT / "outputs/EO_30k_axial_receiver1x_v33/summary.md"
    v33_2 = V2_ROOT / "outputs/EO_30k_axial_receiver2x_v33/summary.md"
    v33_3 = V2_ROOT / "outputs/EO_30k_axial_receiver3x_v33/summary.md"
    for rid, metric, value, unit, src, note in [
        ("E50", "receiver_1x_fully_feasible_rows", 0, "count", v33_1, "Receiver outlet approached saturation."),
        ("E51", "receiver_2x_area", 5818.2, "m2", v33_2, "Conditional, 30,000-cfm process basis."),
        ("E52", "receiver_2x_power", 36.57, "kW", v33_2, "15.7% conditional margin in its old boundary."),
        ("E53", "receiver_3x_area", 4600.0, "m2", v33_3, "Requires ~90,000 cfm receiver air."),
        ("E54", "receiver_3x_power", 60.89, "kW", v33_3, "26.1% conditional margin in its old boundary."),
    ]:
        add_metric(rows, result_id=rid, date="2026-08-05", era="E · V14 architecture hypotheses", theme="receiver_capacity", study="V33 receiver-capacity leverage", target="O30", metric=metric, value=value, unit=unit, boundary="30,000-cfm axial screen", evidence_class="historical_receiver_capacity_study", decision_status="large_receiver_resource", source=src, interpretation=note)

    v35 = V2_ROOT / "outputs/EO_30k_nafion_validity_window_v35/summary.md"
    for rid, metric, value, unit, note in [
        ("E60", "numerical_roots", 7, "of 9", "Numerical convergence only."),
        ("E61", "engineering_and_lambda_domain_pass", 0, "of 9", "No valid Nafion result."),
        ("E62", "O30_area", 3377.9, "m2", "Numerical row."),
        ("E63", "O30_power", 84.75, "kW", "Numerical row."),
        ("E64", "O30_minimum_lambda", 2.704, "-", "Below the declared lambda>=4 domain."),
        ("E65", "O30_backdiffusion_loss", 61.3, "% of gross EO", "Explains why numerical transport is not a valid material claim."),
    ]:
        add_metric(rows, result_id=rid, date="2026-08-06", era="E · V14 architecture hypotheses", theme="Nafion_validity", study="V35/V36 Nafion validity window", target="O30", metric=metric, value=value, unit=unit, boundary="30,000-cfm correlated Nafion screen", evidence_class="full_historical_validity_audit", decision_status="zero_domain_valid_pass", source=v35, interpretation=note)

    v37 = V2_ROOT / "outputs/EO_integrated_system_analysis_v37/summary.md"
    for rid, metric, value, unit, note in [
        ("E70", "local_tw10_conditional_saving", -845.773, "kW", "Local model; not comparable to axial rows."),
        ("E71", "local_tw100_conditional_saving", 563.785, "kW", "Local model; receiver/system incomplete."),
        ("E72", "local_compact_tw50_conditional_saving", 549.889, "kW", "Local hypothetical material."),
        ("E73", "axial_v35_conditional_saving", 70.021, "kW", "Axial row invalid at lambda_min=2.704."),
    ]:
        add_metric(rows, result_id=rid, date="2026-08-06", era="E · V14 architecture hypotheses", theme="system_material_bridge", study="V37 integrated-system comparison", target="O30", metric=metric, value=value, unit=unit, boundary="Mixed local and axial diagnostics kept explicitly separate", evidence_class="historical_cross_model_diagnostic", decision_status="not_rankable_across_models", source=v37, interpretation=note)

    v38 = V2_ROOT / "outputs/EO_material_reality_gate_v38/summary.md"
    v40 = V2_ROOT / "outputs/EO_open_receiver_conditional_v40/summary.md"
    v41 = V2_ROOT / "outputs/EO_countercurrent_geometry_gate_v41/summary.md"
    v42 = V2_ROOT / "outputs/EO_inverse_material_requirements_v42_full/summary.md"
    v43 = V2_ROOT / "outputs/EO_material_property_space_v43/summary.md"
    v44 = V2_ROOT / "outputs/EO_robust_material_requirements_v44_symmetric/summary.md"
    for rid, study, metric, value, unit, src, status, note in [
        ("E80", "V38 hydration-coupled material gate", "area_solutions", 8, "of 18", v38, "zero_full_gate_pass", "Only numerical area solutions."),
        ("E81", "V38 hydration-coupled material gate", "full_domain_and_engineering_pass", 0, "of 18", v38, "zero_full_gate_pass", "H-Nafion lambda=2.771."),
        ("E82", "V38 hydration-coupled material gate", "minimum_positive_requirement_area", 1277.959, "m2", v38, "hypothetical_requirement", "50x drag; only 0.0781 kWh/kg left for receiver/BOP."),
        ("E83", "V40 open receiver", "positive_rows", 6, "of 24", v40, "free_receiver_boundary", "Receiver disposition set to 0 kW."),
        ("E84", "V40 open receiver", "best_receiver_airflow", 455300, "cfm", v40, "free_receiver_boundary", "Large unclosed receiver resource."),
        ("E85", "V41 counter-current geometry", "positive_rows", 6, "of 108", v41, "material_domain_invalid", "Best row lambda_min=3.1346."),
        ("E86", "V41 counter-current geometry", "best_fan_power", 30.967, "kW", v41, "material_domain_invalid", "Geometry did not fix material validity."),
        ("E87", "V42 inverse requirements", "architecture_and_film_pass", 540, "of 864", v42, "zero_lambda_pass", "No strict hydration-domain pass."),
        ("E88", "V42 inverse requirements", "strict_lambda_pass", 0, "of 864", v42, "zero_lambda_pass", "Strong negative result."),
        ("E89", "V43 independent property space", "conditional_pass", 297, "of 720", v43, "independent_properties", "Minimum area 895.5 m2; not a material."),
        ("E90", "V44 robust requirements", "robust_pass", 0, "of 432", v44, "zero_robust_pass", "Robust gas-film/retention constraints collapse the space."),
    ]:
        add_metric(rows, result_id=rid, date="2026-08-07", era="E · V14 architecture hypotheses", theme="material_receiver_reality", study=study, target="O30", metric=metric, value=value, unit=unit, boundary="Hydration/property/geometry reality-gate chain", evidence_class="full_historical_reality_gate", decision_status=status, source=src, interpretation=note)

    # The v37–v55 chain is retained in unusual detail because it contains the
    # largest apparent improvements in the programme and the later tests that
    # removed them.  All positive values in this block are conditional known-
    # electricity margins unless the receiver water sink is explicitly closed.
    v39 = V2_ROOT / "outputs/EO_receiver_regeneration_reality_gate_v39/summary.md"
    for rid, study, metric, value, unit, src, status, note in [
        ("E100", "V37 integrated-system comparison", "strict_local_candidates", 83, "count", v37, "conditional_local_screen", "66 positive and 17 negative; local and axial results are not interchangeable."),
        ("E101", "V37 integrated-system comparison", "strict_local_positive", 66, "count", v37, "conditional_local_screen", "Known-electricity margin only."),
        ("E102", "V37 integrated-system comparison", "best_local_conditional_saving", 732.937, "kW", v37, "conditional_local_screen", "378.227 m2 at j=88.892 A/m2; receiver/BOP not closed."),
        ("E103", "V37 integrated-system comparison", "best_local_area", 378.227, "m2", v37, "conditional_local_screen", "Local-model upper bound, not an axial design."),
        ("E104", "V38 hydration-coupled material gate", "best_target_conditional_saving", 349.539, "kW", v38, "hypothetical_requirement", "50x drag/0.03x diffusivity and lambda_min=2.740, outside the PFSA domain."),
        ("E105", "V39 closed chilled receiver", "closed_receiver_cases", 9, "count", v39, "closed_receiver_negative", "Every explicit closed-receiver case was negative."),
        ("E106", "V39 closed chilled receiver", "negative_closed_receiver_cases", 9, "count", v39, "closed_receiver_negative", "Strongest available receiver falsification."),
        ("E107", "V39 closed chilled receiver", "least_negative_saving_at_20k_cfm", -61.053, "kW", v39, "closed_receiver_negative", "Best of the nine closed chilled-air cases."),
        ("E108", "V39 closed chilled receiver", "primary_30k_cfm_saving", -91.579, "kW", v39, "closed_receiver_negative", "50x drag/0.03x diffusivity case."),
        ("E109", "V39 closed chilled receiver", "primary_receiver_coil_thermal", 834.62, "kW thermal", v39, "closed_receiver_negative", "Drives 139.103 kW coil-compressor demand."),
        ("E110", "V39 closed chilled receiver", "primary_coil_compressor", 139.103, "kW", v39, "closed_receiver_negative", "Explicit receiver regeneration load."),
        ("E111", "V39 closed chilled receiver", "primary_total_path_power", 324.861, "kW", v39, "closed_receiver_negative", "Compared with 233.282 kW in the stored baseline."),
        ("E112", "V40 open receiver", "best_conditional_saving", 402.091, "kW", v40, "free_receiver_boundary", "Requires 455,328 cfm receiver exhaust and zero disposal energy."),
        ("E113", "V41 counter-current geometry", "best_countercurrent_saving", 400.593, "kW", v41, "free_receiver_boundary", "Only about 2.52 kW above the co-current result; receiver remains free."),
        ("E114", "V41 counter-current geometry", "best_countercurrent_area", 1480.833, "m2", v41, "free_receiver_boundary", "Geometry does not cure the sink boundary."),
        ("E115", "V43 independent property space", "best_conditional_saving", 488.157, "kW", v43, "independent_properties", "First sub-1000-m2-looking result; receiver is free and properties are independent."),
        ("E116", "V43 independent property space", "minimum_conditional_area", 895.477, "m2", v43, "independent_properties", "Falls away completely in v44."),
        ("E117", "V44 robust symmetric receiver", "raw_conditional_saving_low", 54.421, "kW", v44, "zero_robust_pass", "Raw arithmetic remained positive before surface-direction gates."),
        ("E118", "V44 robust symmetric receiver", "raw_conditional_saving_high", 608.880, "kW", v44, "zero_robust_pass", "Zero of 432 survives robust surface constraints."),
    ]:
        add_metric(
            rows,
            result_id=rid,
            date="2026-08-07",
            era="E · V14 architecture hypotheses",
            theme="material_receiver_reality",
            study=study,
            target="O30",
            metric=metric,
            value=value,
            unit=unit,
            boundary="v37–v44 material/receiver reality-gate chain",
            evidence_class="full_historical_reality_gate",
            decision_status=status,
            source=src,
            interpretation=note,
        )

    v45 = V2_ROOT / "outputs/EO_symmetric_wet_receiver_sink_v45/summary.md"
    v46 = V2_ROOT / "outputs/EO_symmetric_wet_receiver_sink_v46/summary.md"
    v47 = V2_ROOT / "outputs/EO_symmetric_wet_receiver_sink_v47/summary.md"
    v48 = V2_ROOT / "outputs/EO_symmetric_wet_receiver_sink_v48/summary.md"
    v49 = V2_ROOT / "outputs/EO_symmetric_wet_receiver_sink_v49/summary_v49.md"
    v50 = V2_ROOT / "outputs/EO_symmetric_wet_receiver_sink_v50/summary_v50.md"
    v50j = V2_ROOT / "outputs/EO_symmetric_wet_receiver_sink_v50_j_sweep/summary_v50.md"
    v52 = V2_ROOT / "outputs/EO_symmetric_wet_receiver_sink_v52/summary_v52.md"
    v53 = V2_ROOT / "outputs/EO_symmetric_wet_receiver_sink_v53/summary_v53.md"
    v54 = V2_ROOT / "outputs/EO_symmetric_wet_receiver_sink_v54/strict_margin_summary.csv"
    for rid, study, metric, value, unit, src, status, note in [
        ("E120", "V45 imposed wet receiver sink", "evaluated_cases", 216, "count", v45, "ideal_wet_sink", "Receiver wetness is imposed; sink maintenance is uncosted."),
        ("E121", "V45 imposed wet receiver sink", "gate_passing_cases", 135, "count", v45, "ideal_wet_sink", "45 passes at each receiver activity 0.7, 0.8 and 0.9."),
        ("E122", "V45 imposed wet receiver sink", "maximum_feasible_conditional_saving", 529.806, "kW", v45, "ideal_wet_sink", "Do not mix with the report's broader any-case extrema."),
        ("E123", "V45 imposed wet receiver sink", "unpriced_receiver_water_removal", 4473.6, "kg/h", v45, "ideal_wet_sink", "Water sink is a requirement, not a demonstrated subsystem."),
        ("E124", "V46 receiver-interface sensitivity", "evaluated_cases", 360, "count", v46, "ideal_wet_sink", "Interface activity sweep with zero sink-maintenance power."),
        ("E125", "V46 receiver-interface sensitivity", "robust_positive_cases", 225, "count", v46, "ideal_wet_sink", "Positive only inside the imposed wet-sink boundary."),
        ("E126", "V46 receiver-interface sensitivity", "robust_best_at_receiver_activity_0p8", 510.910, "kW", v46, "ideal_wet_sink", "Conditional known-electricity margin."),
        ("E127", "V46 receiver-interface sensitivity", "selected_400kW_target_area", 1369.461, "m2", v46, "ideal_wet_sink", "Selected target row saved 442.169 kW conditionally."),
        ("E128", "V47 process-surface margin", "physical_cases", 360, "count", v47, "ideal_wet_sink", "Expanded to 720 gate rows."),
        ("E129", "V47 process-surface margin", "robust_positive_gate_rows", 363, "count", v47, "ideal_wet_sink", "Across all receiver activities and surface gates."),
        ("E130", "V47 process-surface margin", "best_at_ap_gate_0p05", 510.910, "kW", v47, "ideal_wet_sink", "45 cases at the primary receiver activity 0.8."),
        ("E131", "V47 process-surface margin", "best_at_ap_gate_0p10", 444.824, "kW", v47, "ideal_wet_sink", "Wetness margin costs about 66.1 kW and removes 15 candidates."),
        ("E132", "V48 joint material requirements", "physical_cases", 7680, "count", v48, "ideal_wet_sink", "15,360 margin rows; 13,116 pass rows."),
        ("E133", "V48 joint material requirements", "pareto_rows", 384, "count", v48, "ideal_wet_sink", "Marginal extrema must not be combined as one design."),
        ("E134", "V48 joint material requirements", "primary_strict_best_saving", 446.562, "kW", v48, "ideal_wet_sink", "Still assumes a maintained wet receiver sink for free."),
        ("E135", "V48 joint material requirements", "primary_strict_minimum_area", 1361.298, "m2", v48, "ideal_wet_sink", "Conditional property bundle."),
        ("E136", "V49 feasibility register", "primary_register_cases", 38, "count", v49, "preferred_area_failed", "10/10/18 across 0/200/400-kW target branches."),
        ("E137", "V49 feasibility register", "full_preferred_area_pass", 0, "count", v49, "preferred_area_failed", "All candidates exceed the historical 1000-m2 preference."),
        ("E138", "V49 feasibility register", "minimum_400kW_branch_area", 1395, "m2", v49, "preferred_area_failed", "400-kW rows span 1395–1558 m2 and 400–429 kW."),
        ("E139", "V50 reversible voltage at j250", "passing_rows", 6024, "count", v50, "water_activity_voltage_correction", "Water-activity voltage removes the 400-kW primary branch."),
        ("E140", "V50 reversible voltage at j250", "pareto_rows", 243, "count", v50, "water_activity_voltage_correction", "Primary Pareto best is only 209.840 kW."),
        ("E141", "V50 reversible voltage at j250", "primary_pareto_best_saving", 209.840, "kW", v50, "water_activity_voltage_correction", "Large correction relative to v48."),
        ("E142", "V50 current-density sweep", "physical_cases", 23040, "count", v50j, "low_current_conditional_reopening", "46,080 margin rows; 32,696 passes."),
        ("E143", "V50 current-density sweep", "pareto_rows", 550, "count", v50j, "low_current_conditional_reopening", "Low-current operation reopens the conditional 400-kW branch."),
        ("E144", "V50 current-density sweep", "best_pareto_saving", 411.636, "kW", v50j, "low_current_conditional_reopening", "400-kW branch uses 100 A/m2, not a 21 A/m2 constraint."),
        ("E145", "V50 current-density sweep", "minimum_400kW_branch_area", 2180.573, "m2", v50j, "low_current_conditional_reopening", "At 100 A/m2 and Vmax 1.970 V."),
        ("E146", "V52 loose joint operating map", "passing_rows", 53952, "count", v52, "superseded_loose_gate", "Pre-hard-gate search; corrected by v53."),
        ("E147", "V52 loose joint operating map", "pareto_rows", 622, "count", v52, "superseded_loose_gate", "Apparent ~958-m2 points were not retained after strict gates."),
        ("E148", "V52 loose joint operating map", "apparent_minimum_area", 958, "m2", v52, "superseded_loose_gate", "Must not be presented as a feasible material target."),
        ("E149", "V53 strict joint operating map", "gate_register_rows", 46080, "count", v53, "strict_conditional_gate", "Every voltage-cap/current branch uses 2880 coordinates."),
        ("E150", "V53 strict joint operating map", "strict_pass_rows", 32996, "count", v53, "strict_conditional_gate", "Still retains the ideal wet-sink boundary."),
        ("E151", "V53 strict joint operating map", "strict_pareto_rows", 482, "count", v53, "strict_conditional_gate", "Sub-1000-m2 result disappears."),
        ("E152", "V53 strict joint operating map", "five_volt_j50_best_saving", 523, "kW", v53, "strict_conditional_gate", "At 5 V; minimum strict area ~1496 m2."),
        ("E153", "V53 strict joint operating map", "five_volt_j250_best_saving", 244, "kW", v53, "strict_conditional_gate", "Shows strong current-density sensitivity."),
        ("E154", "V54 diagnostic margins", "strict_candidates", 13154, "count", v54, "diagnostic_margin_gate", "8,132 pass the additional diagnostic robustness tests."),
        ("E155", "V54 diagnostic margins", "diagnostic_robust_candidates", 8132, "count", v54, "diagnostic_margin_gate", "No diagnostically robust design is below 1000 m2."),
        ("E156", "V54 diagnostic margins", "lowest_area_diagnostic_robust", 2200.012, "m2", v54, "diagnostic_margin_gate", "Exact v55 coordinate; +506.719 kW conditional and Vreq 3.177 V."),
    ]:
        add_metric(
            rows,
            result_id=rid,
            date="2026-08-08",
            era="E · V14 architecture hypotheses",
            theme="wet_receiver_inverse_design",
            study=study,
            target="O30",
            metric=metric,
            value=value,
            unit=unit,
            boundary="Symmetric imposed wet receiver; sink regeneration and water disposition set to zero power",
            evidence_class="historical_conditional_inverse_design",
            decision_status=status,
            source=src,
            interpretation=note,
        )

    v55 = V2_ROOT / "outputs/EO_symmetric_wet_receiver_sink_v55/summary_v55.md"
    v62 = V2_ROOT / "outputs/EO_v62_bottleneck_parametric/README.md"
    for rid, study, metric, value, unit, src, status, note in [
        ("E91", "V55 ideal wet receiver", "known_total_power", 659.3, "kW", v55, "ideal_upper_bound", "Receiver water handling was set to zero power."),
        ("E92", "V55 ideal wet receiver", "conditional_saving", 506.719, "kW", v55, "ideal_upper_bound", "43.5%; not a system claim."),
        ("E93", "V55 ideal wet receiver", "selected_area", 2200, "m2", v55, "ideal_upper_bound", "Undemonstrated 20 um / 3.18 V property combination."),
        ("E93a", "V55 ideal wet receiver", "receiver_water_handling_power", 0, "kW", v55, "ideal_upper_bound", "Receiver sink maintenance/regeneration is deliberately unpriced."),
        ("E94", "V62 bottleneck parametric", "energy_break_even_drag", 4.485, "mol H2O/mol charge", v62, "inverse_target", "Energy-only threshold."),
        ("E95", "V62 bottleneck parametric", "practical_break_even_drag", 44.816, "mol H2O/mol charge", v62, "inverse_target", "Practical threshold in its imposed-receiver boundary."),
        ("E96", "V62 bottleneck parametric", "remaining_receiver_SEC_budget", 0.16119, "kWh/kg", v62, "inverse_target", "Sink at receiver activity 0.8 was not modeled."),
    ]:
        add_metric(rows, result_id=rid, date="2026-08-08", era="E · V14 architecture hypotheses", theme="inverse_material_receiver", study=study, target="O30", metric=metric, value=value, unit=unit, boundary="Ideal/imposed receiver requirement screens", evidence_class="historical_inverse_upper_bound", decision_status=status, source=src, interpretation=note)

    modern = V2_ROOT / "outputs/modern_ac_erv_comparison_v1_study/SYSTEM_COMPARISON_SUMMARY.md"
    energy_window = V2_ROOT / "outputs/eo_energy_window_v1_study/EO_ENERGY_WINDOW_SUMMARY.md"
    for rid, target, metric, value, unit, note in [
        ("F01", "O30", "saving_vs_modern_AC_ERV", -218.55, "kW", "-40.19%; direct HeiQ path loses on the symmetric comparator."),
        ("F02", "O50", "saving_vs_modern_AC_ERV", -362.51, "kW", "-66.67%; direct HeiQ path loses on the symmetric comparator."),
    ]:
        add_metric(rows, result_id=rid, date="2026-08-07", era="F · Modern comparator and ERV", theme="energy_system", study="Symmetric modern AC+ERV comparison", target=target, metric=metric, value=value, unit=unit, boundary="Outdoor 32 C/80%; return 20 C/50%; exclusive exhaust allocation", evidence_class="historical_system_comparison", decision_status="negative_vs_modern_ERV", source=modern, interpretation=note)
    add_metric(rows, result_id="F03", date="2026-08-07", era="F · Modern comparator and ERV", theme="energy_system", study="Architecture-agnostic EO energy window after ERV", target="post-ERV partial target", metric="break_even_total_EO_SEC", value=0.157, unit="kWh/kg", boundary="Targets that leave latent work to the coil; zero process heat leak", evidence_class="energy_budget_screen", decision_status="retained_budget", source=energy_window, interpretation="Necessary but not sufficient; total EO subsystem must fit below this value.")

    final_root = V2_ROOT / "outputs/final_prearchitecture_closure_v1"
    final_status = final_root / "closure_status.json"
    final_reference_path = final_root / "modern_ac_erv_comparison/reference_modern_erv_cases.csv"
    final_sensitivity_path = final_root / "modern_ac_erv_comparison/system_comparison_summary.csv"
    final_reference = pd.read_csv(final_reference_path)
    final_sensitivity = pd.read_csv(final_sensitivity_path)
    for rid, metric, value, unit, note in [
        ("F20", "modern_AC_ERV_reference_power", 543.740591, "kW", "Symmetric selected reference used for all seven candidates."),
        ("F21", "normalised_candidate_count", 7, "count", "Gas, liquid and controlled-receiver candidate boundaries."),
        ("F22", "negative_candidates_at_reference", 7, "count", "Every selected-reference comparison is negative."),
        ("F23", "engineering_comparison_pass_at_reference", 0, "count", "No candidate closes the engineering system comparison."),
        ("F24", "validated_full_system_claims", 0, "count", "The closure status explicitly sets full_system_claim_allowed=false."),
    ]:
        add_metric(
            rows,
            result_id=rid,
            date="2026-08-18",
            era="F · Modern comparator and ERV",
            theme="final_prearchitecture_closure",
            study="Final pre-architecture closure against modern AC+ERV",
            target="all candidates",
            metric=metric,
            value=value,
            unit=unit,
            boundary="Selected modern AC+ERV reference; common site-plane comparison",
            evidence_class="full_cross_architecture_closure",
            decision_status="rework_no_go",
            source=final_status,
            interpretation=note,
        )

    for index, row in final_reference.iterrows():
        base = 30 + index * 3
        for offset, metric, value, unit, note in [
            (0, "selected_reference_saving", row["conditional_saving_kw_vs_modern_ac_erv"], "kW", "Negative means the HeiQ candidate consumes more total site power."),
            (1, "selected_reference_saving_percent", row["conditional_saving_pct_vs_modern_ac_erv"], "%", "Selected-reference outcome, not a sensitivity corner."),
            (2, "selected_reference_total_system_power", row["heiq_total_system_power_kw"], "kW", "Compared with 543.741 kW modern AC+ERV."),
        ]:
            add_metric(
                rows,
                result_id=f"F{base + offset:02d}",
                date="2026-08-18",
                era="F · Modern comparator and ERV",
                theme="final_prearchitecture_closure",
                study="Final pre-architecture closure against modern AC+ERV",
                target=row["candidate_id"],
                metric=metric,
                value=value,
                unit=unit,
                boundary="Selected modern AC+ERV reference; common site-plane comparison",
                evidence_class="full_cross_architecture_closure",
                decision_status="negative_at_selected_reference",
                source=final_reference_path,
                interpretation=note,
            )

    for index, row in final_sensitivity.iterrows():
        base = 60 + index * 3
        for offset, metric, value, unit, note in [
            (0, "sensitivity_minimum_saving", row["minimum_saving_pct"], "%", "Deterministic sensitivity envelope, not a probability interval."),
            (1, "sensitivity_maximum_saving", row["maximum_saving_pct"], "%", "Favourable corners exist but do not replace the selected-reference result."),
            (2, "engineering_comparison_pass_scenarios", row["comparison_pass_count"], "of 375", "Most candidate boundaries have zero scenario passes."),
        ]:
            add_metric(
                rows,
                result_id=f"F{base + offset:02d}",
                date="2026-08-18",
                era="F · Modern comparator and ERV",
                theme="final_prearchitecture_closure",
                study="Final pre-architecture robustness envelope",
                target=row["candidate_id"],
                metric=metric,
                value=value,
                unit=unit,
                boundary="375 deterministic scenario combinations per candidate",
                evidence_class="full_cross_architecture_sensitivity",
                decision_status="not_robust_at_selected_reference",
                source=final_sensitivity_path,
                interpretation=note,
            )

    active_status_path = V2_ROOT / "outputs/active_eo_erv_terminal1_v2_study/active_eo_erv_status.json"
    active_best_path = V2_ROOT / "outputs/active_eo_erv_terminal1_v2_study/best_case_by_target.csv"
    active = pd.read_csv(active_best_path)
    active_status = read_json(active_status_path)
    for rid, metric, key in [
        ("F04", "active_cases", "completed_case_count"),
        ("F05", "transport_complete", "transport_solution_complete_case_count"),
        ("F06", "engineering_working", "engineering_working_case_count"),
        ("F07", "robust_physics", "robust_physics_case_count"),
        ("F08", "full_coupled", "full_coupled_gate_case_count"),
    ]:
        add_metric(rows, result_id=rid, date="2026-08-23", era="F · Modern comparator and ERV", theme="active_ERV", study="Active EO-ERV Terminal-1 v2.2.2", target="all", metric=metric, value=active_status[key], unit="count", boundary="Balanced exhaust active ERV+EO", evidence_class="full_engineering_diagnostic", decision_status="zero_full_coupled", source=active_status_path, interpretation="Gate funnel; engineering rows are not system claims.")
    for index, target in enumerate([13.214990502676377, 12.0, 10.0], start=9):
        row = active.iloc[(active["process_outlet_target_w_g_kg_da"] - target).abs().argmin()]
        add_metric(rows, result_id=f"F{index:02d}", date="2026-08-23", era="F · Modern comparator and ERV", theme="active_ERV", study="Active EO-ERV Terminal-1 v2.2.2", target=f"{target:.3f} g/kg", metric="conditional_saving", value=row["net_saving_kw_vs_passive_modern_erv"], unit="kW", boundary="Balanced exhaust engineering screen", evidence_class="engineering_diagnostic", decision_status="not_full_coupled", source=active_best_path, interpretation="Core remains ~107–108 kW while downstream opportunity changes with target.")
        add_metric(rows, result_id=f"F{index:02d}a", date="2026-08-23", era="F · Modern comparator and ERV", theme="active_ERV", study="Active EO-ERV Terminal-1 v2.2.2", target=f"{target:.3f} g/kg", metric="required_area", value=row["required_active_area_m2"], unit="m2", boundary="Balanced exhaust engineering screen", evidence_class="engineering_diagnostic", decision_status="not_full_coupled", source=active_best_path, interpretation="Area grows sharply with deeper target.")

    mechanism_path = V2_ROOT / "outputs/terminal1_receiver_mechanism_map_v1_smoke/best_by_boundary_target.csv"
    mechanism = pd.read_csv(mechanism_path)
    for target, start in [("O50", 20), ("O30", 30)]:
        subset = mechanism.loc[mechanism["target"].eq(target)].set_index("boundary_id")
        for offset, boundary_id in enumerate(["controlled_a0p50_real_film", "controlled_a0p50_ideal_film", "dry_sink_a0p05"]):
            row = subset.loc[boundary_id]
            add_metric(rows, result_id=f"G{start+offset:02d}", date="2026-08-24", era="G · Receiver mechanism and control", theme="receiver_mechanism", study="Fixed-voltage receiver/mechanism map", target=target, metric=f"area_{boundary_id}", value=row["required_active_area_m2"], unit="m2", boundary="1.96 V isothermal mechanism screen; zero sink-maintenance energy", evidence_class="smoke_mechanism_map", decision_status="boundary_diagnostic", source=mechanism_path, interpretation="Fixed-voltage area comparison; no system energy claim.")
    process_ceiling_path = V2_ROOT / "outputs/terminal1_receiver_mechanism_map_v1_smoke/process_film_ceiling.csv"
    process_ceiling = pd.read_csv(process_ceiling_path)
    for target, rid in [("O50", "G23"), ("O30", "G33")]:
        row = process_ceiling.loc[process_ceiling["target"].eq(target)].iloc[0]
        add_metric(rows, result_id=rid, date="2026-08-24", era="G · Receiver mechanism and control", theme="receiver_mechanism", study="Process-film-only ceiling", target=target, metric="area_without_membrane_or_receiver_opposition", value=row["required_active_area_m2"], unit="m2", boundary="Artificial analytical ceiling", evidence_class="mechanism_upper_bound", decision_status="not_physical_architecture", source=process_ceiling_path, interpretation="Useful lower-bound comparison only.")

    current_path = V2_ROOT / "outputs/terminal1_current_controlled_receiver_v2_study/current_control_cases.csv"
    current = pd.read_csv(current_path)
    valid = current.loc[current["target_reached"] & current["mechanism_case_valid"]].copy()
    no_negative = valid["negative_required_voltage_area_fraction"].eq(0)
    positive_surface = valid["passive_surface_direction_positive_everywhere"]
    current_metrics = [
        ("G40", "sampled_cases", len(current)),
        ("G41", "valid_target_reaching", len(valid)),
        ("G42", "valid_without_negative_voltage_region", int(no_negative.sum())),
        ("G43", "valid_with_positive_surface_direction", int(positive_surface.sum())),
        ("G44", "valid_with_both_diagnostics", int((no_negative & positive_surface).sum())),
    ]
    for rid, metric, value in current_metrics:
        add_metric(rows, result_id=rid, date="2026-08-24", era="G · Receiver mechanism and control", theme="receiver_control", study="Current-controlled receiver v2", target="O50/O30", metric=metric, value=value, unit="count", boundary="5–75 A/m2 sampling grid; no engineering current limit", evidence_class="full_mechanism_study", decision_status="receiver_tradeoff_unresolved", source=current_path, interpretation="The two diagnostics are not formal hardware gates, but their zero overlap is decision-relevant.")
    for target, rid in [("O50", "G45"), ("O30", "G46")]:
        add_metric(rows, result_id=rid, date="2026-08-24", era="G · Receiver mechanism and control", theme="receiver_control", study="Current-controlled receiver v2", target=target, metric="highest_sampled_current_with_valid_target", value=valid.loc[valid["target"].eq(target), "imposed_current_density_a_m2"].max(), unit="A/m2", boundary="Sampling result, not a limit", evidence_class="full_mechanism_study", decision_status="solver_transport_result", source=current_path, interpretation="The legacy 21 A/m2 acceptance interpretation is withdrawn.")

    post_path = V2_ROOT / "outputs/terminal1_post_erv_10pct_incremental_v2_study/DECISION_SUMMARY.json"
    post_cases_path = V2_ROOT / "outputs/terminal1_post_erv_10pct_incremental_v2_study/post_erv_10pct_cases.csv"
    post = read_json(post_path)
    post_best = post["best_real_receiver_screen"]
    for rid, metric, value, unit, note in [
        ("H01", "incremental_water_removal", 374.94262494, "kg/h", "Only 8.59% of the direct O30 duty."),
        ("H02", "best_real_film_area", post_best["required_active_area_m2"], "m2", "Uniform 5 A/m2 row."),
        ("H03", "best_real_film_addon_power", post_best["conservative_addon_power_kw"], "kW", "EO plus bounded process/receiver fans."),
        ("H04", "best_real_film_saving", post_best["incremental_saving_kw_vs_passive_erv"], "kW", "Conditional screening margin."),
        ("H05", "best_real_film_saving_percent", post_best["incremental_saving_pct_vs_passive_erv"], "%", "Against 543.74 kW passive ERV+AC reference."),
        ("H06", "best_real_film_surface_margin", post_best["minimum_surface_activity_margin"], "activity", "Negative; no robust/full-coupled closure."),
    ]:
        add_metric(rows, result_id=rid, date="2026-08-25", era="H · Post-ERV and current closure", theme="post_ERV", study="Further 10% humidity-ratio reduction after passive ERV", target="13.215→11.893 g/kg", metric=metric, value=value, unit=unit, boundary="Passive ERV+AC comparator; real receiver film; sink/thermal closure absent", evidence_class="full_conditional_energy_screen", decision_status="positive_but_not_full_system", source=post_path if rid != "H01" else post_cases_path, interpretation=note)

    diff_path = V2_ROOT / "outputs/archive_terminal1_post_erv_diffusivity_sensitivity_v1_20260825T084804Z/best_case_by_diffusivity.csv"
    diff = pd.read_csv(diff_path)
    for index, row in diff.iterrows():
        base = 10 + 4 * index
        for offset, metric, value, unit in [
            (0, "required_area", row["best_required_active_area_m2"], "m2"),
            (1, "conditional_saving", row["best_incremental_saving_kw_vs_passive_erv"], "kW"),
            (2, "diffusion_fraction_of_EO", row["best_absolute_diffusion_fraction_of_eo"] * 100, "%"),
            (3, "best_current_density", row["best_uniform_current_density_a_m2"], "A/m2"),
        ]:
            add_metric(rows, result_id=f"H{base+offset:02d}", date="2026-08-25", era="H · Post-ERV and current closure", theme="materials_sensitivity", study="Post-ERV diffusivity sensitivity", target=f"D={row['water_diffusivity_m2_s']:.3g} m2/s", metric=metric, value=value, unit=unit, boundary="One-parameter sensitivity on Terminal-1 vector", evidence_class="full_one_parameter_sensitivity", decision_status="positive_conditional_margin_only", source=diff_path, interpretation="Not evidence that a real material has the complete property vector.")

    physics_path = V2_ROOT / "outputs/terminal1_post_erv_physics_closure_v1_smoke/DECISION_SUMMARY.json"
    material_path = V2_ROOT / "outputs/terminal1_material_condensation_suite_v1_smoke/DECISION_SUMMARY.json"
    regen_path = V2_ROOT / "outputs/EO_receiver_regeneration_reality_gate_v39/selected_designs.csv"
    for rid, metric, value, unit, src, note in [
        ("H30", "best_detailed_HVAC_saving", 47.967886, "kW", physics_path, "Isothermal detailed-HVAC smoke."),
        ("H31", "thermal_scenario_min", -131.95701, "kW", physics_path, "Deterministic scenario corner, not probability."),
        ("H32", "thermal_scenario_max", 146.38715, "kW", physics_path, "Deterministic scenario corner, not probability."),
        ("H33", "coupled_counterflow_saving", -32.778852, "kW", material_path, "Only passing coupled smoke row; zero condensate."),
        ("H34", "Nafion_numerical_target_rows", 8, "count", material_path, "Transport solve only."),
        ("H35", "Nafion_target_and_domain_valid_rows", 0, "count", material_path, "No current Nafion performance claim."),
        ("H36", "historical_regeneration_net_saving", -91.579019, "kW", regen_path, "30,000-cfm hypothetical-material stress test."),
        ("H37", "historical_receiver_SEC", 0.1804887, "kWh/kg", regen_path, "Closed chilled-air receiver loop."),
    ]:
        add_metric(rows, result_id=rid, date="2026-08-25", era="H · Post-ERV and current closure", theme="thermal_receiver_closure", study="Thermal, material-domain and regeneration closure", target="mixed", metric=metric, value=value, unit=unit, boundary="Smoke and historical stress boundaries are kept distinct", evidence_class="smoke_or_historical_stress", decision_status="sign_can_reverse", source=src, interpretation=note)

    o30_path = TROND_ROOT / "data/golden/o30/required_area_1v_curve_v1.csv"
    o30 = pd.read_csv(o30_path)
    for rid, metric, value, unit, note in [
        ("I01", "minimum_tested_area", o30["required_active_area_m2"].min(), "m2", "At receiver multiplier 3.0; not a system optimum."),
        ("I02", "maximum_tested_area", o30["required_active_area_m2"].max(), "m2", "At receiver multiplier 1.01."),
        ("I03", "minimum_core_power", o30["analysis_core_power_kw"].min(), "kW", "EO plus idealised straight-channel fans."),
        ("I04", "maximum_core_power", o30["analysis_core_power_kw"].max(), "kW", "EO plus idealised straight-channel fans."),
        ("I05", "minimum_receiver_airflow", o30["analysis_receiver_airflow_cfm"].min(), "cfm", "Already 2.49× process flow."),
        ("I06", "maximum_receiver_airflow", o30["analysis_receiver_airflow_cfm"].max(), "cfm", "7.39× process flow."),
        ("I07", "area_reduction_R1p01_to_R3", 13.51, "%", "Bought with 197% more receiver airflow."),
        ("I08", "core_power_increase_R1p01_to_R3", 3.46, "%", "Receiver fan dominates the increase."),
    ]:
        add_metric(rows, result_id=rid, date="2026-08-26", era="I · Exact O30 and integrated ledger", theme="exact_O30", study="Exact nonlinear O30 required area at 1.0 V", target="O30", metric=metric, value=value, unit=unit, boundary="Case-94 geometry; no current-density acceptance gate; no design area cap", evidence_class="full_local_conditioned_study", decision_status="numerically_closed_locally", source=o30_path, interpretation=note)

    ledger_path = TROND_ROOT / "outputs/trond_system_closure_v2_no_current_gate/power_ledger.csv"
    add_metric(rows, result_id="I09", date="2026-08-26", era="I · Exact O30 and integrated ledger", theme="system_ledger", study="Trond system closure without current gate", target="O30", metric="known_core_site_power", value=118.3854287, unit="kW", boundary="Canonical site-plane subtotal; regeneration and heat rejection missing", evidence_class="conditional_incomplete_ledger", decision_status="fail_closed_incomplete", source=ledger_path, interpretation="System total, FOM, net saving and annual energy remain unavailable.")

    frame = pd.DataFrame(rows).sort_values(["date", "result_id"]).reset_index(drop=True)
    missing = frame.loc[~frame["source_exists"], "source_path"].drop_duplicates().tolist()
    if missing:
        raise FileNotFoundError("Missing atlas sources: " + ", ".join(missing))
    return frame


MAJOR_OUTPUTS: dict[str, str] = {
    "decision_summary": "Early conservative energy/area envelope",
    "wp1_free_predrying_explicit_cop": "Explicit-COP gross HVAC opportunity",
    "wp1_eo_membrane_stage_gate_v2": "Early EO stage-gate bridge",
    "pre_receiver_axial_v3": "First axial target-reaching screen",
    "axial_independent_material_sweep_v8": "Completed V8 material sweep",
    "prearchitecture_continuation_v2": "Terminal-1 selected point and material plateau",
    "prearchitecture_bottleneck_diagnostics_v1_material_optimum": "Terminal-2 bottleneck diagnostics",
    "receiver_closure_v2_study": "O50 receiver closure",
    "receiver_closure_o30_actual_v1_study": "O30 receiver closure",
    "two_stage_receiver_coupling_v1_2_study": "Two-stage receiver closure",
    "receiver_reality_checks_v1_study": "Geometry, film and diffusivity reality checks",
    "EO_30k_axial_receiver1x_v33": "V33 one-times receiver capacity",
    "EO_30k_axial_receiver2x_v33": "V33 two-times receiver capacity",
    "EO_30k_axial_receiver3x_v33": "V33 three-times receiver capacity",
    "EO_30k_nafion_validity_window_v35": "Nafion hydration-domain validity",
    "EO_30k_nafion_validity_sensitivity_v36": "Nafion validity sensitivity",
    "EO_integrated_system_analysis_v37": "Integrated local/axial diagnostic",
    "EO_material_reality_gate_v38": "Hydration-coupled material gate",
    "EO_open_receiver_conditional_v40": "Free open-receiver upper bound",
    "EO_countercurrent_geometry_gate_v41": "Counter-current geometry gate",
    "EO_inverse_material_requirements_v42_full": "Inverse material requirements",
    "EO_material_property_space_v43": "Independent property space",
    "EO_robust_material_requirements_v44_symmetric": "Robust material/gas-film gate",
    "EO_symmetric_wet_receiver_sink_v45": "Imposed wet-receiver sink sensitivity",
    "EO_symmetric_wet_receiver_sink_v46": "Receiver-interface activity sensitivity",
    "EO_symmetric_wet_receiver_sink_v47": "Process-surface margin sensitivity",
    "EO_symmetric_wet_receiver_sink_v48": "Joint material-requirement Pareto search",
    "EO_symmetric_wet_receiver_sink_v49": "Candidate physical-feasibility register",
    "EO_symmetric_wet_receiver_sink_v50": "Reversible water-activity voltage correction",
    "EO_symmetric_wet_receiver_sink_v50_j_sweep": "Current-density operating sweep",
    "EO_symmetric_wet_receiver_sink_v52": "Loose joint material/operating map",
    "EO_symmetric_wet_receiver_sink_v53": "Strict joint material/operating map",
    "EO_symmetric_wet_receiver_sink_v54": "Diagnostic robustness margins",
    "EO_symmetric_wet_receiver_sink_v55": "Ideal wet receiver upper bound",
    "EO_v62_bottleneck_parametric": "Bottleneck and inverse drag targets",
    "saturated_receiver_liquid_drain_v1": "Saturated / ideal liquid-drain track",
    "direct_liquid_activity_crossover_v1": "Liquid-activity crossover",
    "EO_receiver_regeneration_reality_gate_v39": "Receiver regeneration stress test",
    "modern_ac_erv_comparison_v1_study": "Symmetric modern AC+ERV comparator",
    "final_prearchitecture_closure_v1": "Final seven-candidate modern-ERV closure",
    "eo_energy_window_v1_study": "Architecture-agnostic post-ERV energy budget",
    "active_eo_erv_terminal1_v2_study": "Active EO-ERV gate funnel",
    "terminal1_receiver_mechanism_map_v1_smoke": "Fixed-voltage receiver mechanism map",
    "terminal1_current_controlled_receiver_v2_study": "Current-controlled receiver map",
    "terminal1_post_erv_10pct_incremental_v2_study": "Post-ERV 10% polishing",
    "terminal1_post_erv_diffusivity_sensitivity_v1": "Post-ERV diffusivity sensitivity",
    "archive_terminal1_post_erv_diffusivity_sensitivity_v1_20260825T084804Z": "Complete archived diffusivity run",
    "terminal1_post_erv_physics_closure_v1_smoke": "Detailed HVAC / thermal closure smoke",
    "terminal1_material_condensation_suite_v1_smoke": "Material-domain and condensation smoke",
    "o30_required_area_1v_v1": "Exact O30 1 V area curve",
    "wp1_geometry_candidate_replay_v1": "Canonical legacy geometry replay",
    "trond_system_closure_v2_no_current_gate": "Current fail-closed system ledger",
}


def family_for(name: str) -> str:
    low = name.lower()
    if any(word in low for word in ["erv", "system", "energy_window", "four_system", "comparison"]):
        return "system / ERV / energy"
    if any(word in low for word in ["receiver", "liquid", "saturated", "two_stage", "geometry", "film"]):
        return "receiver / geometry / phase"
    if any(word in low for word in ["material", "nafion", "transport", "parameter", "axial", "membrane", "mechanism"]):
        return "material / transport"
    if any(word in low for word in ["hvac", "psychro", "enthalpy", "predry", "gree", "aircon", "cop", "reheat", "doas"]):
        return "thermodynamics / HVAC"
    return "support / integration / other"


def build_output_inventory() -> pd.DataFrame:
    roots = {
        "Trond study": TROND_ROOT,
        "XMembrane model": MODEL_ROOT,
        "HeiQ V2": V2_ROOT,
        "Thermodynamical analysis": THERMO_ROOT,
    }
    rows: list[dict[str, Any]] = []
    for repo, root in roots.items():
        outputs = root / "outputs"
        if not outputs.is_dir():
            continue
        for path in sorted(item for item in outputs.iterdir() if item.is_dir()):
            name = path.name
            low = name.lower()
            included = name in MAJOR_OUTPUTS
            diagnostic = any(token in low for token in ["smoke", "inspect", "inspection", "archive", "_quick", "run_logs", "briefing", "beamer"])
            if included:
                disposition = "included_quantitatively"
                reason = MAJOR_OUTPUTS[name]
            elif diagnostic:
                disposition = "supporting_or_superseded"
                reason = "Diagnostic/archive/presentation output; retained in inventory but not promoted over its parent full study."
            else:
                disposition = "reviewed_by_family"
                reason = "Covered through the family synthesis; no additional independent headline promoted."
            file_count = sum(1 for item in path.rglob("*") if item.is_file())
            rows.append(
                {
                    "repository": repo,
                    "output_name": name,
                    "family": family_for(name),
                    "disposition": disposition,
                    "reason": reason,
                    "file_count": file_count,
                    "path": str(path.resolve()),
                }
            )
    return pd.DataFrame(rows)


def build_download_manifest() -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if not DOWNLOADS.is_dir():
        return pd.DataFrame()
    candidates = []
    for path in DOWNLOADS.iterdir():
        low = path.name.lower()
        if path.is_file() and path.suffix.lower() == ".pdf" and any(token in low for token in ["heiq", "xmembrane", "terminal", "wp1"]):
            candidates.append(path)
    first_by_hash: dict[str, str] = {}
    for path in sorted(candidates, key=lambda item: (item.stat().st_mtime, item.name)):
        digest = sha256_file(path)
        duplicate_of = first_by_hash.get(digest, "")
        if not duplicate_of:
            first_by_hash[digest] = path.name
        rows.append(
            {
                "filename": path.name,
                "modified_date": dt.datetime.fromtimestamp(path.stat().st_mtime).date().isoformat(),
                "size_bytes": path.stat().st_size,
                "sha256": digest,
                "duplicate_of": duplicate_of,
                "unique_document": not bool(duplicate_of),
                "path": str(path.resolve()),
            }
        )
    return pd.DataFrame(rows)


def latex_escape(value: Any) -> str:
    text = str(value)
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_\allowbreak{}",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(char, char) for char in text)


def format_metric_value(value: float) -> str:
    if value == 0:
        return "0"
    absolute = abs(value)
    if absolute < 1e-3 or absolute >= 1e6:
        return f"{value:.3e}"
    if absolute >= 1000:
        return f"{value:,.1f}".replace(",", r"\,")
    if absolute >= 100:
        return f"{value:.2f}"
    if absolute >= 10:
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return f"{value:.5g}"


def write_latex_fragments(
    output_dir: Path,
    atlas: pd.DataFrame,
    studies: pd.DataFrame,
    inventory: pd.DataFrame,
    downloads: pd.DataFrame,
) -> None:
    atlas_lines = [
        r"\begin{longtable}{@{}p{9mm}p{35mm}p{43mm}r p{18mm}p{37mm}@{}}",
        r"\toprule",
        r"\textbf{ID} & \textbf{Studie / mål} & \textbf{Måltall} & \textbf{Verdi} & \textbf{Enhet} & \textbf{Status / tolkning} \\",
        r"\midrule",
        r"\endfirsthead",
        r"\toprule",
        r"\textbf{ID} & \textbf{Studie / mål} & \textbf{Måltall} & \textbf{Verdi} & \textbf{Enhet} & \textbf{Status / tolkning} \\",
        r"\midrule",
        r"\endhead",
        r"\midrule\multicolumn{6}{r}{\scriptsize Fortsetter på neste side}\\",
        r"\endfoot",
        r"\bottomrule",
        r"\endlastfoot",
    ]
    last_era = None
    for row in atlas.itertuples(index=False):
        if row.era != last_era:
            atlas_lines.append(
                rf"\multicolumn{{6}}{{@{{}}l}}{{\sffamily\bfseries\color{{Navy}} {latex_escape(row.era)}}}\\[1mm]"
            )
            last_era = row.era
        status = f"{row.decision_status}. {row.interpretation}"
        atlas_lines.append(
            " & ".join(
                [
                    latex_escape(row.result_id),
                    latex_escape(f"{row.study} / {row.target}"),
                    latex_escape(row.metric),
                    format_metric_value(float(row.numeric_value)),
                    latex_escape(row.unit),
                    latex_escape(status),
                ]
            )
            + r" \\"
        )
    atlas_lines.append(r"\end{longtable}")
    (output_dir / "result_atlas_longtable.tex").write_text("\n".join(atlas_lines) + "\n", encoding="utf-8")

    study_lines = [
        r"\begin{longtable}{@{}p{18mm}p{35mm}p{58mm}p{36mm}@{}}",
        r"\toprule",
        r"\textbf{Dato} & \textbf{Epoke} & \textbf{Studie} & \textbf{Beslutningsstatus} \\",
        r"\midrule\endfirsthead",
        r"\toprule",
        r"\textbf{Dato} & \textbf{Epoke} & \textbf{Studie} & \textbf{Beslutningsstatus} \\",
        r"\midrule\endhead",
        r"\bottomrule\endlastfoot",
    ]
    for row in studies.itertuples(index=False):
        study_lines.append(
            " & ".join(
                [
                    latex_escape(row.date),
                    latex_escape(row.era),
                    latex_escape(f"{row.study} ({row.metric_count} registrerte måltall)"),
                    latex_escape(row.decision_statuses),
                ]
            )
            + r" \\"
        )
    study_lines.append(r"\end{longtable}")
    (output_dir / "major_study_longtable.tex").write_text("\n".join(study_lines) + "\n", encoding="utf-8")

    unique_downloads = downloads.loc[downloads["unique_document"]].copy() if len(downloads) else downloads
    download_lines = [
        r"\begin{longtable}{@{}p{19mm}p{103mm}p{32mm}@{}}",
        r"\toprule",
        r"\textbf{Dato} & \textbf{Unikt PDF-dokument i Downloads} & \textbf{SHA-256 (start)} \\",
        r"\midrule\endfirsthead",
        r"\toprule",
        r"\textbf{Dato} & \textbf{Unikt PDF-dokument i Downloads} & \textbf{SHA-256 (start)} \\",
        r"\midrule\endhead",
        r"\bottomrule\endlastfoot",
    ]
    for row in unique_downloads.itertuples(index=False):
        download_lines.append(
            " & ".join(
                [
                    latex_escape(row.modified_date),
                    latex_escape(row.filename),
                    latex_escape(row.sha256[:16]),
                ]
            )
            + r" \\"
        )
    download_lines.append(r"\end{longtable}")
    (output_dir / "downloads_unique_longtable.tex").write_text("\n".join(download_lines) + "\n", encoding="utf-8")

    inventory_summary = (
        inventory.groupby(["repository", "family", "disposition"], dropna=False)
        .size()
        .reset_index(name="directory_count")
    )
    inv_lines = [
        r"\begin{longtable}{@{}p{37mm}p{42mm}p{49mm}r@{}}",
        r"\toprule",
        r"\textbf{Repository} & \textbf{Familie} & \textbf{Behandling} & \textbf{Mapper} \\",
        r"\midrule\endfirsthead",
        r"\toprule",
        r"\textbf{Repository} & \textbf{Familie} & \textbf{Behandling} & \textbf{Mapper} \\",
        r"\midrule\endhead",
        r"\bottomrule\endlastfoot",
    ]
    for row in inventory_summary.itertuples(index=False):
        inv_lines.append(
            " & ".join(
                [latex_escape(row.repository), latex_escape(row.family), latex_escape(row.disposition), str(row.directory_count)]
            )
            + r" \\"
        )
    inv_lines.append(r"\end{longtable}")
    (output_dir / "output_inventory_summary_longtable.tex").write_text("\n".join(inv_lines) + "\n", encoding="utf-8")


def build_major_study_index(atlas: pd.DataFrame) -> pd.DataFrame:
    grouped = []
    for (date, era, study), frame in atlas.groupby(["date", "era", "study"], sort=True):
        grouped.append(
            {
                "date": date,
                "era": era,
                "study": study,
                "themes": "; ".join(sorted(frame["theme"].unique())),
                "metric_count": len(frame),
                "evidence_classes": "; ".join(sorted(frame["evidence_class"].unique())),
                "decision_statuses": "; ".join(sorted(frame["decision_status"].unique())),
                "full_system_claim_allowed": bool(frame["full_system_claim_allowed"].all()),
                "primary_source": frame["source_path"].iloc[0],
            }
        )
    return pd.DataFrame(grouped)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=TROND_ROOT / "outputs/full_result_atlas_v2",
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    atlas = build_result_atlas()
    inventory = build_output_inventory()
    downloads = build_download_manifest()
    studies = build_major_study_index(atlas)

    atlas.to_csv(args.output_dir / "result_atlas.csv", index=False)
    inventory.to_csv(args.output_dir / "all_output_inventory.csv", index=False)
    downloads.to_csv(args.output_dir / "downloads_pdf_manifest.csv", index=False)
    studies.to_csv(args.output_dir / "major_study_index.csv", index=False)
    write_latex_fragments(args.output_dir, atlas, studies, inventory, downloads)

    summary = {
        "atlas_metric_count": int(len(atlas)),
        "major_study_count": int(len(studies)),
        "output_directory_count": int(len(inventory)),
        "output_repository_counts": inventory.groupby("repository").size().to_dict(),
        "output_disposition_counts": inventory.groupby("disposition").size().to_dict(),
        "download_pdf_count": int(len(downloads)),
        "download_unique_pdf_count": int(downloads["unique_document"].sum()) if len(downloads) else 0,
        "full_system_claim_allowed_count": int(atlas["full_system_claim_allowed"].sum()),
        "claim_boundary": "No row in this atlas is a validated full-system saving claim.",
        "current_density_rule": "No 21 A/m2 acceptance limit; current density is diagnostic/sampled unless a historical boundary is explicitly named.",
    }
    (args.output_dir / "atlas_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    readme = f"""# Full result atlas v2

- Metrics retained: **{len(atlas)}**
- Major named studies: **{len(studies)}**
- Top-level output directories inventoried: **{len(inventory)}**
- Relevant downloaded PDFs: **{len(downloads)}** ({summary['download_unique_pdf_count']} unique by SHA-256)

The atlas combines current results, historical negative controls and superseded
boundary studies.  `comparison_boundary`, `evidence_class` and
`decision_status` are mandatory interpretation fields.  No row enables a
validated full-system saving claim, and no 21 A/m2 acceptance limit is used.
"""
    (args.output_dir / "README.md").write_text(readme, encoding="utf-8")

    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
