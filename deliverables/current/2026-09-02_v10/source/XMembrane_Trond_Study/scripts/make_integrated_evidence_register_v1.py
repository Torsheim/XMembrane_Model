#!/usr/bin/env python3
"""Build a fail-closed evidence register across the HeiQ WSL workspaces.

The script reads compact, audited result files.  It does not reinterpret chat
text as evidence and it never promotes smoke or diagnostic outputs to a full-
system claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_files(paths: Iterable[Path]) -> None:
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing required evidence files: " + ", ".join(missing))


def truth(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "pass", "passed"}


def finite(value: Any, default: float = math.nan) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def find_diffusivity_output(v2_root: Path) -> Path:
    candidates = [
        v2_root / "outputs/terminal1_post_erv_diffusivity_sensitivity_v1",
        *sorted(
            (v2_root / "outputs").glob(
                "archive_terminal1_post_erv_diffusivity_sensitivity_v1_*"
            ),
            reverse=True,
        ),
    ]
    for candidate in candidates:
        if (candidate / "audit.json").is_file() and (
            candidate / "best_case_by_diffusivity.csv"
        ).is_file():
            return candidate
    raise FileNotFoundError("No complete post-ERV diffusivity output was found")


def evidence_row(
    *,
    study_id: str,
    title: str,
    source: Path,
    mode: str,
    evidence_level: str,
    audit_pass: bool,
    current_density_limit_applied: bool,
    full_system_claim_allowed: bool,
    headline: str,
    decision_use: str,
) -> dict[str, Any]:
    return {
        "study_id": study_id,
        "title": title,
        "mode": mode,
        "evidence_level": evidence_level,
        "audit_pass": bool(audit_pass),
        "current_density_limit_applied": bool(current_density_limit_applied),
        "full_system_claim_allowed": bool(full_system_claim_allowed),
        "headline": headline,
        "decision_use": decision_use,
        "source_path": str(source.resolve()),
        "source_sha256": sha256_file(source),
    }


def metric_row(
    study_id: str,
    metric_id: str,
    value: Any,
    unit: str,
    interpretation: str,
) -> dict[str, Any]:
    return {
        "study_id": study_id,
        "metric_id": metric_id,
        "numeric_value": finite(value),
        "unit": unit,
        "interpretation": interpretation,
    }


def material_data_requirements() -> pd.DataFrame:
    """Return the minimum evidence fields for a model-rankable material."""

    rows = [
        (
            "MAT-01",
            "Sorption isotherm and hysteresis",
            "lambda(a,T), water uptake and dCw/dmu_w",
            "mol H2O/mol site or kg/kg",
            "23-32 C; activity approximately 0.05-0.9; adsorption and desorption",
            "Measured curve with method, ion form, conditioning and raw points",
            "Closes chemical-potential state, chemical capacitance and correlation domain",
        ),
        (
            "MAT-02",
            "Water diffusivity, mobility and chemical permeance",
            "D(a,T)",
            "m2/s plus D(dCw/dmu_w)/L or equivalent",
            "Same temperature/activity range and ion form as sorption data",
            "Measured activity-resolved values with Fick/Maxwell-Stefan definition and the coupled sorption derivative",
            "The identifiable passive transport bundle, not D alone, can assist or oppose EO",
        ),
        (
            "MAT-03",
            "Electro-osmotic water drag",
            "n_d(a,T,j)",
            "mol H2O/mol charge",
            "Relevant humidity gradient and current-density range",
            "Coupled transport measurement with sign convention",
            "Sets charge-coupled water transport",
        ),
        (
            "MAT-04",
            "Ionic conductivity",
            "sigma(a,T)",
            "S/m",
            "Wet operating range; declared ion form",
            "Measured activity-resolved curve and test frequency/method",
            "Sets membrane ohmic loss and local voltage",
        ),
        (
            "MAT-05",
            "Membrane and contact resistance",
            "ASR_membrane + ASR_contact",
            "ohm m2",
            "Candidate thickness, electrodes and wet compression state",
            "Through-plane stack measurement separated into membrane/contact terms",
            "Prevents optimistic power estimates from bulk conductivity alone",
        ),
        (
            "MAT-06",
            "Thickness, swelling and mechanics",
            "L_dry, L_wet, strain, creep",
            "um, %, MPa",
            "Dry/wet and cyclic 23-32 C exposure",
            "Batch-resolved measurements after declared conditioning",
            "Converts intrinsic properties to area, stack gap and durability",
        ),
        (
            "MAT-07",
            "Coupled net water flux",
            "J_net(a_source,a_receiver,T,j)",
            "mol/m2/s or kg/m2/h",
            "Model-relevant post-ERV and direct-ERV gradients; multiple flow/gap conditions",
            "Independent membrane-cell experiment with mass balance and separate source/receiver film sensitivity",
            "Joint validation of sorption, diffusion, drag, resistance and interfacial uptake/release",
        ),
        (
            "MAT-08",
            "Receiver and electrode compatibility",
            "wetting, corrosion, flooding, drainage",
            "qualitative plus test-specific metrics",
            "Selected receiver fluid/gas and electrode chemistry",
            "Observed interface behaviour and regeneration requirement",
            "Receiver/sink behaviour can reverse the system energy sign",
        ),
        (
            "MAT-09",
            "Provenance and availability",
            "sample, batch, supplier, source",
            "identifiers",
            "Every reported property",
            "Stable citation/raw-data link, sample ID and commercial availability",
            "Allows audit, domain checks and later procurement",
        ),
    ]
    columns = [
        "requirement_id",
        "property_group",
        "symbol_or_measurement",
        "preferred_unit",
        "required_conditions",
        "minimum_evidence",
        "decision_reason",
    ]
    frame = pd.DataFrame(rows, columns=columns)
    frame["candidate_sample_id"] = ""
    frame["candidate_value_or_source"] = ""
    frame["data_status"] = "missing"
    frame["notes"] = ""
    return frame


def build_register(
    *,
    trond_root: Path,
    v2_root: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    o30_curve_path = trond_root / "data/golden/o30/required_area_1v_curve_v1.csv"
    o30_convergence_path = (
        trond_root / "data/golden/o30/required_area_1v_convergence_v1.csv"
    )
    current_root = v2_root / "outputs/terminal1_current_controlled_receiver_v2_study"
    current_audit_path = current_root / "audit.json"
    current_requirements_path = current_root / "receiver_requirement_by_current.csv"
    post_root = v2_root / "outputs/terminal1_post_erv_10pct_incremental_v2_study"
    post_decision_path = post_root / "DECISION_SUMMARY.json"
    post_audit_path = post_root / "audit.json"
    diffusivity_root = find_diffusivity_output(v2_root)
    diffusivity_audit_path = diffusivity_root / "audit.json"
    diffusivity_table_path = diffusivity_root / "best_case_by_diffusivity.csv"
    physics_root = v2_root / "outputs/terminal1_post_erv_physics_closure_v1_smoke"
    physics_decision_path = physics_root / "DECISION_SUMMARY.json"
    physics_audit_path = physics_root / "audit.json"
    uncertainty_path = physics_root / "conditional_uncertainty_envelope.csv"
    material_root = v2_root / "outputs/terminal1_material_condensation_suite_v1_smoke"
    material_decision_path = material_root / "DECISION_SUMMARY.json"
    material_audit_path = material_root / "audit.json"
    material_cases_path = material_root / "material_duty_cases.csv"
    active_path = v2_root / "outputs/active_eo_erv_terminal1_v2_study/active_eo_erv_status.json"
    regeneration_path = (
        v2_root / "outputs/EO_receiver_regeneration_reality_gate_v39/selected_designs.csv"
    )
    closure_root = trond_root / "outputs/trond_system_closure_v2_no_current_gate"
    closure_reference_path = closure_root / "selected_reference_case.csv"
    closure_ledger_path = closure_root / "power_ledger.csv"

    required = [
        o30_curve_path,
        o30_convergence_path,
        current_audit_path,
        current_requirements_path,
        post_decision_path,
        post_audit_path,
        diffusivity_audit_path,
        diffusivity_table_path,
        physics_decision_path,
        physics_audit_path,
        uncertainty_path,
        material_decision_path,
        material_audit_path,
        material_cases_path,
        active_path,
        regeneration_path,
        closure_reference_path,
        closure_ledger_path,
    ]
    require_files(required)

    o30 = pd.read_csv(o30_curve_path)
    convergence = pd.read_csv(o30_convergence_path)
    current_audit = read_json(current_audit_path)
    current_requirements = pd.read_csv(current_requirements_path)
    post = read_json(post_decision_path)
    post_audit = read_json(post_audit_path)
    diffusivity_audit = read_json(diffusivity_audit_path)
    diffusivity = pd.read_csv(diffusivity_table_path).sort_values(
        "water_diffusivity_m2_s", kind="mergesort"
    )
    physics = read_json(physics_decision_path)
    physics_audit = read_json(physics_audit_path)
    uncertainty = pd.read_csv(uncertainty_path)
    material = read_json(material_decision_path)
    material_audit = read_json(material_audit_path)
    material_cases = pd.read_csv(material_cases_path)
    active = read_json(active_path)
    regeneration = pd.read_csv(regeneration_path)
    closure_reference = pd.read_csv(closure_reference_path)
    closure_ledger = pd.read_csv(closure_ledger_path)

    real_post = post["best_real_receiver_screen"]
    detailed = physics["best_detailed_isothermal_case"]
    best_uncertainty = uncertainty.loc[
        uncertainty["closure_case_id"].eq(detailed["closure_case_id"])
    ].iloc[0]
    counterflow = material["best_counterflow_coupled_case"]
    active_diag = active["best_engineering_screen_diagnostic"]
    primary_regeneration = regeneration.loc[
        regeneration["airflow_cfm"].eq(30000.0)
    ].sort_values("eo_path_total_electric_kw", kind="mergesort").iloc[0]
    closure_core = closure_ledger.loc[
        closure_ledger["scenario"].eq("gas_receiver_o30_core")
    ].iloc[0]
    closure_reference_row = closure_reference.iloc[0]

    requirement_resolved = current_requirements[
        current_requirements["receiver_requirement_resolved_on_grid"].map(truth)
    ]
    highest_current = requirement_resolved.groupby("target")[
        "imposed_current_density_a_m2"
    ].max()

    nafion = material_cases.loc[
        material_cases["material_id"].eq("nafion_vapor_reference")
    ]
    nafion_target = nafion["target_reached"].map(truth)
    nafion_valid = nafion["property_correlation_valid"].map(truth)

    o30_valid = o30["required_area_solution_valid"].map(truth).all()
    convergence_valid = len(convergence) > 0 and convergence.select_dtypes(
        include="number"
    ).notna().all().all()
    post_valid = (
        post_audit.get("case_count") == 34
        and post_audit.get("mechanism_energy_gate_pass_count") == 13
        and finite(post_audit.get("water_balance_max_abs")) < 1.0e-10
    )
    current_valid = (
        current_audit.get("case_count") == 336
        and current_audit.get("valid_case_count") == 195
        and current_audit.get("legacy_21_a_m2_limit_interpretation_withdrawn") is True
    )
    diffusivity_valid = (
        diffusivity_audit.get("case_count") == 12
        and diffusivity_audit.get("baseline_regression_pass") is True
    )

    evidence = [
        evidence_row(
            study_id="o30_exact_1v",
            title="Exact nonlinear O30 required-area curve at 1.0 V",
            source=o30_curve_path,
            mode="study",
            evidence_level="local_model_conditioned",
            audit_pass=bool(o30_valid and convergence_valid),
            current_density_limit_applied=False,
            full_system_claim_allowed=False,
            headline=(
                f"All 8 points reach O30 at {o30.required_active_area_m2.min():.1f}–"
                f"{o30.required_active_area_m2.max():.1f} m2."
            ),
            decision_use="Primary current gas-receiver area/airflow/core trade-off.",
        ),
        evidence_row(
            study_id="current_controlled_receiver",
            title="Terminal-1 current-controlled receiver",
            source=current_audit_path,
            mode="study",
            evidence_level="mechanism_study",
            audit_pass=current_valid,
            current_density_limit_applied=False,
            full_system_claim_allowed=False,
            headline="336 cases; 195 target-reaching mechanism-valid cases; 21 A/m2 withdrawn as a limit.",
            decision_use="Mechanism and receiver-activity interpretation only.",
        ),
        evidence_row(
            study_id="post_erv_10pct",
            title="Terminal-1 post-ERV additional 10% humidity-ratio reduction",
            source=post_decision_path,
            mode="study",
            evidence_level="conditional_energy_screen",
            audit_pass=post_valid,
            current_density_limit_applied=False,
            full_system_claim_allowed=bool(post.get("full_system_claim_allowed", False)),
            headline=(
                f"Best real-film screen: {real_post['incremental_saving_kw_vs_passive_erv']:.2f} kW "
                f"({real_post['incremental_saving_pct_vs_passive_erv']:.2f}%)."
            ),
            decision_use="Primary conditional energy opportunity after passive ERV.",
        ),
        evidence_row(
            study_id="post_erv_diffusivity",
            title="Post-ERV water-diffusivity sensitivity",
            source=diffusivity_table_path,
            mode="study",
            evidence_level="one_parameter_sensitivity",
            audit_pass=diffusivity_valid,
            current_density_limit_applied=False,
            full_system_claim_allowed=bool(
                diffusivity_audit.get("full_system_claim_allowed", False)
            ),
            headline="Positive screening margin persists through 1e-9 m2/s, with area and diffusion penalties.",
            decision_use="Material sensitivity; not proof of a candidate material.",
        ),
        evidence_row(
            study_id="post_erv_physics_closure",
            title="Detailed HVAC and thermal-feedback closure",
            source=physics_decision_path,
            mode=str(physics.get("mode", "smoke")),
            evidence_level="smoke_sensitivity",
            audit_pass=bool(physics_audit.get("pass", False)),
            current_density_limit_applied=False,
            full_system_claim_allowed=bool(physics.get("full_system_claim_allowed", False)),
            headline=(
                f"Best isothermal detailed-HVAC smoke: {detailed['detailed_incremental_saving_kw']:.2f} kW "
                f"({detailed['detailed_incremental_saving_pct']:.2f}%)."
            ),
            decision_use="Shows thermal/HVAC sensitivity; full study still required.",
        ),
        evidence_row(
            study_id="material_condensation",
            title="Material/activity and counter-current condensation suite",
            source=material_decision_path,
            mode=str(material_audit.get("mode", "smoke")),
            evidence_level="smoke_mechanism_screen",
            audit_pass=bool(material_audit.get("decision_summary_written", False)),
            current_density_limit_applied=False,
            full_system_claim_allowed=bool(material.get("full_system_claim_allowed", False)),
            headline=(
                f"Nafion: {int(nafion_target.sum())} numerical target rows, "
                f"{int((nafion_target & nafion_valid).sum())} within correlation domain."
            ),
            decision_use="Material-domain and condensation caution only.",
        ),
        evidence_row(
            study_id="active_eo_erv",
            title="Active EO-ERV v2.2.2",
            source=active_path,
            mode=str(active.get("mode", "study")),
            evidence_level="engineering_diagnostic",
            audit_pass=(
                active.get("completed_case_count") == active.get("planned_case_count")
                and active.get("failed_case_count") == 0
            ),
            current_density_limit_applied=False,
            full_system_claim_allowed=bool(active.get("full_system_claim_allowed", False)),
            headline=(
                f"Diagnostic margin {active_diag['net_saving_kw_vs_passive_modern_erv']:.2f} kW, "
                f"but {active.get('full_coupled_gate_case_count', 0)} full-coupled cases."
            ),
            decision_use="Code/system architecture diagnostic; not a performance claim.",
        ),
        evidence_row(
            study_id="receiver_regeneration_v39",
            title="Historical closed receiver-regeneration stress test",
            source=regeneration_path,
            mode="historical_study",
            evidence_level="boundary_stress_test",
            audit_pass=True,
            current_density_limit_applied=True,
            full_system_claim_allowed=False,
            headline=(
                f"Best 30000-cfm row gives {primary_regeneration['net_system_saving_kw']:.2f} kW net saving."
            ),
            decision_use="Demonstrates that receiver regeneration can consume the gross EO margin.",
        ),
        evidence_row(
            study_id="trond_closure_no_current_gate",
            title="Trond system-closure regeneration without current-density gate",
            source=closure_ledger_path,
            mode="integration",
            evidence_level="conditional_core_ledger",
            audit_pass=(
                truth(closure_reference_row["reference_gate_pass"])
                and not truth(closure_reference_row["reference_current_gate_applied"])
            ),
            current_density_limit_applied=False,
            full_system_claim_allowed=truth(closure_core["system_claim_available"]),
            headline=(
                f"Known core at site plane: {closure_core['site_total_kw']:.2f} kW; "
                "receiver regeneration and heat rejection remain missing."
            ),
            decision_use="Current integrated ledger; full-system FOMs remain unavailable.",
        ),
    ]

    metrics = [
        metric_row("o30_exact_1v", "minimum_required_area", o30["required_active_area_m2"].min(), "m2", "Minimum tested-area point."),
        metric_row("o30_exact_1v", "maximum_required_area", o30["required_active_area_m2"].max(), "m2", "Maximum tested-area point."),
        metric_row("o30_exact_1v", "minimum_core_power", o30["analysis_core_power_kw"].min(), "kW", "EO plus idealised straight-channel fans."),
        metric_row("o30_exact_1v", "maximum_core_power", o30["analysis_core_power_kw"].max(), "kW", "EO plus idealised straight-channel fans."),
        metric_row("current_controlled_receiver", "case_count", current_audit["case_count"], "count", "Sampled mechanism cases."),
        metric_row("current_controlled_receiver", "valid_case_count", current_audit["valid_case_count"], "count", "Target-reaching mechanism-valid cases."),
        metric_row("current_controlled_receiver", "highest_sampled_current_reaching_o30", highest_current["O30"], "A/m2", "Observed on sampled grid; not a limit."),
        metric_row("current_controlled_receiver", "highest_sampled_current_reaching_o50", highest_current["O50"], "A/m2", "Observed on sampled grid; not a limit."),
        metric_row("post_erv_10pct", "passive_erv_plus_ac_reference", post["passive_erv_plus_ac_reference_kw"], "kW", "Screening HVAC reference."),
        metric_row("post_erv_10pct", "incremental_water_removal", post["incremental_water_removal_kg_h"], "kg/h", "Further 10% relative humidity-ratio reduction."),
        metric_row("post_erv_10pct", "best_real_film_saving", real_post["incremental_saving_kw_vs_passive_erv"], "kW", "Conditional screen; negative surface margin."),
        metric_row("post_erv_10pct", "best_real_film_saving_percent", real_post["incremental_saving_pct_vs_passive_erv"], "%", "Conditional screen; no full-coupled gate."),
        metric_row("post_erv_10pct", "best_real_film_area", real_post["required_active_area_m2"], "m2", "Uniform 5 A/m2 case."),
        metric_row("post_erv_10pct", "best_real_film_addon_power", real_post["conservative_addon_power_kw"], "kW", "EO and bounded module-fan subtotal."),
        metric_row("post_erv_physics_closure", "best_detailed_saving", detailed["detailed_incremental_saving_kw"], "kW", "Isothermal smoke case."),
        metric_row("post_erv_physics_closure", "uncertainty_minimum", best_uncertainty["minimum_detailed_saving_kw"], "kW", "Deterministic scenario envelope; not probability."),
        metric_row("post_erv_physics_closure", "uncertainty_maximum", best_uncertainty["maximum_detailed_saving_kw"], "kW", "Deterministic scenario envelope; not probability."),
        metric_row("material_condensation", "nafion_numerical_target_rows", nafion_target.sum(), "count", "Numerical result only."),
        metric_row("material_condensation", "nafion_target_and_correlation_valid_rows", (nafion_target & nafion_valid).sum(), "count", "Within stated property-correlation domain."),
        metric_row("material_condensation", "counterflow_coupled_saving", counterflow["coupled_saving_kw"], "kW", "Only passing coupled smoke row; produced zero condensate."),
        metric_row("active_eo_erv", "diagnostic_saving", active_diag["net_saving_kw_vs_passive_modern_erv"], "kW", "Engineering diagnostic; module non-rankable."),
        metric_row("active_eo_erv", "diagnostic_area", active_diag["required_active_area_m2"], "m2", "Engineering diagnostic."),
        metric_row("receiver_regeneration_v39", "historical_net_saving", primary_regeneration["net_system_saving_kw"], "kW", "Older 30000-cfm stress test with hypothetical material envelope."),
        metric_row("receiver_regeneration_v39", "receiver_sec", primary_regeneration["receiver_electric_sec_kwh_kg"], "kWh/kg", "Closed chilled-air receiver loop."),
        metric_row("trond_closure_no_current_gate", "known_core_site_power", closure_core["site_total_kw"], "kW", "Known core subtotal; incomplete system ledger."),
    ]

    diffusivity_export = diffusivity.copy()
    diffusivity_export["evidence_level"] = "conditional_energy_sensitivity"
    diffusivity_export["full_system_claim_allowed"] = False

    decision_matrix = pd.DataFrame(
        [
            {
                "path": "Gas receiver, direct O80 to O30",
                "current_signal": "Numerically target-reaching at 1.0 V on fixed case-94 basis.",
                "main_penalty_or_gap": "10500–12140 m2 and 0.37–1.11 million cfm receiver flow; manifold/BOP unresolved.",
                "next_decision_evidence": "Receiver resource, manifold pressure-drop and packaging bracket.",
            },
            {
                "path": "Passive ERV plus EO polishing",
                "current_signal": "Best real-film screen gives 53.07 kW / 9.76% conditional margin.",
                "main_penalty_or_gap": "Negative surface margin; sink, thermal feedback and module rankability unresolved.",
                "next_decision_evidence": "Full detailed-HVAC/thermal run with explicit receiver-sink ledger.",
            },
            {
                "path": "Active EO-ERV",
                "current_signal": "58.60 kW diagnostic margin in v2.2.2 engineering row.",
                "main_penalty_or_gap": "18764 m2, 106.2 kW fan and zero full-coupled passing cases.",
                "next_decision_evidence": "Rankable geometry/topology and robust surface margin.",
            },
            {
                "path": "Liquid or condensing receiver",
                "current_signal": "Useful mechanism and boundary screens exist.",
                "main_penalty_or_gap": "Liquid activity, drainage, flooding, heat rejection and regeneration dominate.",
                "next_decision_evidence": "Finite film/two-phase model and measured sink/regeneration energy.",
            },
        ]
    )

    manifest_files = {
        str(path.resolve()): sha256_file(path)
        for path in required
    }
    manifest = {
        "script_version": "integrated-evidence-register-v1-2026-08-26",
        "source_roots": {
            "trond": str(trond_root.resolve()),
            "heiq_v2": str(v2_root.resolve()),
        },
        "source_files_sha256": manifest_files,
        "rules": {
            "chat_text_is_evidence": False,
            "smoke_promoted_to_study": False,
            "missing_power_treated_as_zero": False,
            "current_density_acceptance_limit_applied": False,
        },
    }

    return (
        pd.DataFrame(evidence),
        pd.DataFrame(metrics),
        diffusivity_export,
        decision_matrix,
        manifest,
    )


def summary_markdown(
    evidence: pd.DataFrame,
    metrics: pd.DataFrame,
    diffusivity: pd.DataFrame,
) -> str:
    values = metrics.set_index(["study_id", "metric_id"])["numeric_value"]
    return "\n".join(
        [
            "# Integrert evidensregister for HeiQ/XMembrane",
            "",
            "## Beslutningssetning",
            "",
            "Dagens modeller støtter en betinget energimulighet, ikke en lukket påstand om fullsystembesparelse.",
            "",
            "- Eksakt O30 ved 1,0 V: "
            f"{values['o30_exact_1v', 'minimum_required_area']:.1f}–"
            f"{values['o30_exact_1v', 'maximum_required_area']:.1f} m2 på den frosne lokale basen.",
            "- Ytterligere 10 % reduksjon etter ERV: "
            f"{values['post_erv_10pct', 'best_real_film_saving']:.2f} kW / "
            f"{values['post_erv_10pct', 'best_real_film_saving_percent']:.2f}% betinget margin.",
            "- Detaljert HVAC-smoke for beste isotermiske case: "
            f"{values['post_erv_physics_closure', 'uncertainty_minimum']:.2f} til "
            f"{values['post_erv_physics_closure', 'uncertainty_maximum']:.2f} kW.",
            "- Historisk lukket receiver-regenereringsstresstest: "
            f"{values['receiver_regeneration_v39', 'historical_net_saving']:.2f} kW.",
            "",
            "## Tolkning",
            "",
            "Det positive post-ERV-vinduet er det mest beslutningsrelevante energiresultatet, men det er avgrenset av negativ overflatemargin og manglende lukking av receiver/sink, termikk og modul. Den historiske receiver-regenereringsstraffen og det brede smoke-omslaget viser hvorfor screeningverdien ennå ikke kan oppgraderes.",
            "",
            "## Evidensdisiplin",
            "",
            f"- Registrerte studier: {len(evidence)}.",
            f"- Diffusivitetsfølsomhetspunkter: {len(diffusivity)}.",
            "- Ingen akseptgrense på 21 A/m2 brukes.",
            "- Smoke-output forblir merket smoke.",
            "- Manglende effektkomponenter forblir manglende og settes ikke til null.",
            "- `material_data_requirements.csv` er arbeidsmatrisen for leverandør- og litteratursøk.",
            "",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trond-root", type=Path, default=ROOT)
    parser.add_argument(
        "--heiq-v2-root",
        type=Path,
        default=ROOT.parent / "HeiQ_V2",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "outputs/integrated_evidence_v1",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    trond_root = args.trond_root.expanduser().resolve()
    v2_root = args.heiq_v2_root.expanduser().resolve()
    output = args.output_dir.expanduser().resolve()
    evidence, metrics, diffusivity, decision_matrix, manifest = build_register(
        trond_root=trond_root,
        v2_root=v2_root,
    )
    output.mkdir(parents=True, exist_ok=True)
    evidence.to_csv(output / "evidence_register.csv", index=False)
    metrics.to_csv(output / "headline_metrics.csv", index=False)
    diffusivity.to_csv(output / "diffusivity_summary.csv", index=False)
    decision_matrix.to_csv(output / "next_study_matrix.csv", index=False)
    material_data_requirements().to_csv(
        output / "material_data_requirements.csv", index=False
    )
    (output / "source_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary = summary_markdown(evidence, metrics, diffusivity)
    (output / "INTEGRATED_FINDINGS.md").write_text(summary, encoding="utf-8")
    print(summary)
    print(f"Outputs: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
