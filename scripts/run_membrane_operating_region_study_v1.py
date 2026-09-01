#!/usr/bin/env python3
"""Run and audit the combined EO + ERV / direct-EO membrane region study.

This is the reproducible top-level entry point.  It runs only missing study
components and never deletes or silently overwrites an existing result set.
The two architectures retain their own reference systems and water duties;
their conditional saving percentages must therefore not be compared as if
they were observations of one common plant boundary.

Current density is a sampled operating coordinate.  No 21 A/m2 acceptance
limit is present.  Receiver/regeneration energy is unresolved, so every final
system-closure status written here is ``UNKNOWN``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, Iterable
import zipfile

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "membrane_operating_region_study_v1.json"
DEFAULT_OUTPUT = ROOT / "outputs" / "membrane_operating_region_study_v1"
DEFAULT_V2_ROOT = ROOT.parent / "HeiQ_V2"
DEFAULT_DETAILED_ZIP = Path(
    "/mnt/c/Users/mariu/Downloads/HeiQ_terminal1_post_erv_physics_closure_v1.zip"
)
EXPECTED_POST_ERV_SCRIPT_VERSION = "post-erv-inverse-design-v1.2-2026-08-26"
DETAILED_PROVENANCE_FILENAME = "source_package_provenance.json"
DIRECT_DENSE_PROVENANCE_FILENAME = "source_generator_provenance.json"
DIRECT_RECEIVER_SEC_VALUES_KWH_KG = [0.0, 0.05, 0.10, 0.15, 0.20]
DIRECT_REQUIRED_OUTPUTS = {
    "per_cap_robust_register.csv",
    "physical_sensitivity_register.csv",
    "parameter_level_pass_share.csv",
    "tw_diffusivity_cell_register.csv",
    "tw_diffusivity_3x3_neighborhood.csv",
    "receiver_sec_scenarios.csv",
    "receiver_sec_cap_summary.csv",
    "gate_failure_summary.csv",
    "analysis_assumptions.json",
    "summary_direct_eo_operating_region_v1.md",
    "01_dense_tw_diffusivity_region_by_cap.png",
    "01_dense_tw_diffusivity_region_by_cap.pdf",
    "02_dense_tw_diffusivity_region_by_current.png",
    "02_dense_tw_diffusivity_region_by_current.pdf",
    "03_global_tw_diffusivity_region_by_current.png",
    "03_global_tw_diffusivity_region_by_current.pdf",
    "04_parameter_level_robust_pass_share.png",
    "04_parameter_level_robust_pass_share.pdf",
    "05_dense_receiver_sec_break_even_budget.png",
    "05_dense_receiver_sec_break_even_budget.pdf",
}


class StudyError(RuntimeError):
    """Raised when a component is incomplete or an audit invariant fails."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--v2-root", type=Path, default=DEFAULT_V2_ROOT)
    parser.add_argument("--post-erv-jobs", type=int, default=min(8, os.cpu_count() or 1))
    parser.add_argument("--detailed-package-zip", type=Path, default=DEFAULT_DETAILED_ZIP)
    parser.add_argument(
        "--audit-only",
        action="store_true",
        help="Do not execute missing components; audit what is already present.",
    )
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def as_bool(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series.fillna(False)
    if pd.api.types.is_numeric_dtype(series):
        return series.fillna(0).astype(float).ne(0.0)
    return series.astype(str).str.strip().str.lower().isin({"true", "1", "yes", "y"})


def values(arguments: Iterable[float]) -> list[str]:
    return [f"{float(value):.12g}" for value in arguments]


def run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> None:
    print("Running:", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, env=env, check=True)


def directory_is_empty(path: Path) -> bool:
    return not path.exists() or not any(path.iterdir())


def detailed_provenance_payload(out: Path, package_zip: Path) -> dict[str, Any]:
    artifacts = {
        "audit.json": out / "audit.json",
        "inspect.json": out / "inspect.json",
        "detailed_hvac_base_cases_with_pareto_flag.csv": (
            out / "detailed_hvac_base_cases_with_pareto_flag.csv"
        ),
        "detailed_hvac_thermal_revaluation.csv": (
            out / "detailed_hvac_thermal_revaluation.csv"
        ),
    }
    missing = [str(path) for path in artifacts.values() if not path.is_file()]
    if not package_zip.is_file():
        missing.append(str(package_zip))
    if missing:
        raise StudyError(f"Cannot record detailed-HVAC provenance; missing: {missing}")
    return {
        "schema_version": 1,
        "source_package_path": str(package_zip),
        "source_package_sha256": sha256(package_zip),
        "artifact_sha256": {
            name: sha256(path) for name, path in sorted(artifacts.items())
        },
    }


def detailed_provenance_matches(out: Path, package_zip: Path) -> bool:
    path = out / DETAILED_PROVENANCE_FILENAME
    if not path.is_file():
        return False
    try:
        return read_json(path) == detailed_provenance_payload(out, package_zip)
    except (OSError, StudyError, ValueError, json.JSONDecodeError):
        return False


def direct_analysis_audit_matches(
    audit_path: Path,
    *,
    config: dict[str, Any],
    config_path: Path,
    output_root: Path,
    v2_root: Path,
) -> bool:
    if not audit_path.is_file():
        return False
    try:
        audit = read_json(audit_path)
        if audit.get("status") != "PASS":
            return False
        direct = config["direct_eo"]
        expected_paths = {
            "script": ROOT / "scripts" / "analyze_direct_eo_operating_region_v1.py",
            "manifest": config_path,
            "v53_generator": v2_root
            / "scripts"
            / "make_wp1_symmetric_wet_receiver_sink_v53.py",
            "global_register": Path(direct["global_v53_gate_register"]),
            "dense_register": output_root
            / "direct_eo_dense"
            / "joint_material_operating_gate_register.csv",
            "global_assumptions_v53": Path(direct["global_v53_gate_register"]).parent
            / "assumptions_v53.csv",
            "dense_assumptions_v53": output_root
            / "direct_eo_dense"
            / "assumptions_v53.csv",
        }
        provenance = audit.get("provenance", {})
        for name, path in expected_paths.items():
            resolved = path.expanduser().resolve()
            record = provenance.get(name, {})
            if (
                not resolved.is_file()
                or record.get("path") != str(resolved)
                or record.get("sha256") != sha256(resolved)
            ):
                return False
        expected_parameters = {
            "process_activity_min": float(direct["robust_process_surface_activity_min"]),
            "conditional_saving_min_kw": float(
                direct["robust_minimum_conditional_saving_kw"]
            ),
            "selected_cap_voltage_headroom_v": float(
                direct["robust_voltage_headroom_v"]
            ),
            "primary_cap_v": float(
                max(direct["dense_axes"]["cell_voltage_cap_tested_v"])
            ),
            "primary_current_density_a_m2": float(
                direct["v55_reference"]["current_density_a_m2"]
            ),
            "receiver_sec_values_kwh_kg": DIRECT_RECEIVER_SEC_VALUES_KWH_KG,
        }
        if audit.get("effective_parameters") != expected_parameters:
            return False
        policies = audit.get("policies", {})
        if (
            policies.get("engineering_current_density_limit_a_m2") is not None
            or policies.get("system_energy_status") != "UNKNOWN"
            or policies.get("full_system_claim_allowed") is not False
        ):
            return False
        stored_outputs = {
            str(item.get("relative_path")): item
            for item in audit.get("required_outputs", [])
        }
        if set(stored_outputs) != DIRECT_REQUIRED_OUTPUTS:
            return False
        out = audit_path.resolve().parent
        for relative in DIRECT_REQUIRED_OUTPUTS:
            live = out / relative
            if (
                not live.is_file()
                or stored_outputs[relative].get("sha256") != sha256(live)
            ):
                return False
        return True
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return False


def direct_dense_provenance_payload(
    config: dict[str, Any], out: Path, generator: Path
) -> dict[str, Any]:
    direct = config["direct_eo"]
    study_inputs = {
        "dense_axes": direct["dense_axes"],
        "receiver_control_activity": direct["receiver_control_activity"],
        "screening_process_surface_activity_min": direct[
            "screening_process_surface_activity_min"
        ],
        "preferred_area_diagnostic_m2": direct["preferred_area_diagnostic_m2"],
        "hard_area_screen_m2": direct["hard_area_screen_m2"],
        "screening_voltage_cap_v": 12.0,
        "saving_targets_kw": [0.0, 200.0, 400.0],
    }
    register = out / "joint_material_operating_gate_register.csv"
    assumptions = out / "assumptions_v53.csv"
    missing = [
        str(path)
        for path in (generator, register, assumptions)
        if not path.is_file()
    ]
    if missing:
        raise StudyError(f"Cannot record direct-EO dense provenance; missing: {missing}")
    return {
        "schema_version": 1,
        "study_input_sha256": sha256_json(study_inputs),
        "study_inputs": study_inputs,
        "generator_path": str(generator.resolve()),
        "generator_sha256": sha256(generator),
        "register_sha256": sha256(register),
        "assumptions_sha256": sha256(assumptions),
    }


def direct_dense_provenance_matches(
    config: dict[str, Any], out: Path, generator: Path
) -> bool:
    path = out / DIRECT_DENSE_PROVENANCE_FILENAME
    if not path.is_file():
        return False
    try:
        return read_json(path) == direct_dense_provenance_payload(config, out, generator)
    except (OSError, StudyError, ValueError, json.JSONDecodeError):
        return False


def run_direct_dense(config: dict[str, Any], output_root: Path, v2_root: Path) -> None:
    direct = config["direct_eo"]
    axes = direct["dense_axes"]
    out = output_root / "direct_eo_dense"
    register = out / "joint_material_operating_gate_register.csv"
    script = v2_root / "scripts" / "make_wp1_symmetric_wet_receiver_sink_v53.py"
    if register.is_file() and direct_dense_provenance_matches(config, out, script):
        print(f"Reusing direct-EO dense register: {register}")
        return
    if not directory_is_empty(out):
        raise StudyError(
            f"Direct-EO dense output exists but lacks matching generator/config "
            f"provenance: {out}"
        )
    command = [
        sys.executable,
        "-B",
        str(script),
        "--out-dir",
        str(out),
        "--screening-voltage-cap-v",
        "12",
        "--cell-voltage-caps-v",
        *values(axes["cell_voltage_cap_tested_v"]),
        "--operating-current-densities-a-m2",
        *values(axes["current_density_a_m2"]),
        "--reference-transport-numbers",
        *values(axes["transport_number_reference_t_w"]),
        "--diffusivity-scales",
        *values(axes["water_diffusivity_scale_vs_pfsa"]),
        "--area-resistances-ohm-m2",
        *values(axes["ionic_area_resistance_ohm_m2_at_lambda_ref"]),
        "--dry-thicknesses-um",
        *values(axes["dry_thickness_um"]),
        "--retention-factors",
        *values(axes["retention_factor_vs_pfsa_sorption"]),
        "--receiver-control-activities",
        f"{float(direct['receiver_control_activity']):.12g}",
        "--process-surface-activity-min",
        f"{float(direct['screening_process_surface_activity_min']):.12g}",
        "--saving-targets-kw",
        "0",
        "200",
        "400",
        "--preferred-area-m2",
        f"{float(direct['preferred_area_diagnostic_m2']):.12g}",
        "--hard-area-cap-m2",
        f"{float(direct['hard_area_screen_m2']):.12g}",
    ]
    run(command, cwd=v2_root)
    write_json(
        out / DIRECT_DENSE_PROVENANCE_FILENAME,
        direct_dense_provenance_payload(config, out, script),
    )


def run_direct_analysis(
    config: dict[str, Any], config_path: Path, output_root: Path, v2_root: Path
) -> None:
    out = output_root / "direct_eo_analysis"
    audit = out / "audit.json"
    if direct_analysis_audit_matches(
        audit,
        config=config,
        config_path=config_path,
        output_root=output_root,
        v2_root=v2_root,
    ):
        print(f"Reusing direct-EO analysis: {out}")
        return
    if not directory_is_empty(out):
        raise StudyError(
            f"Direct-EO analysis exists but lacks a matching provenance/hash audit: {out}"
        )
    direct = config["direct_eo"]
    global_register = Path(direct["global_v53_gate_register"])
    dense_dir = output_root / "direct_eo_dense"
    run(
        [
            sys.executable,
            "-B",
            str(ROOT / "scripts" / "analyze_direct_eo_operating_region_v1.py"),
            "--manifest",
            str(config_path),
            "--global-register",
            str(global_register),
            "--dense-register",
            str(dense_dir / "joint_material_operating_gate_register.csv"),
            "--v53-generator",
            str(v2_root / "scripts" / "make_wp1_symmetric_wet_receiver_sink_v53.py"),
            "--global-assumptions-v53",
            str(global_register.parent / "assumptions_v53.csv"),
            "--dense-assumptions-v53",
            str(dense_dir / "assumptions_v53.csv"),
            "--out-dir",
            str(out),
            "--require-empty-out-dir",
            "--process-activity-min",
            str(float(direct["robust_process_surface_activity_min"])),
            "--conditional-saving-min-kw",
            str(float(direct["robust_minimum_conditional_saving_kw"])),
            "--voltage-headroom-v",
            str(float(direct["robust_voltage_headroom_v"])),
            "--primary-cap-v",
            str(float(max(direct["dense_axes"]["cell_voltage_cap_tested_v"]))),
            "--primary-current-density-a-m2",
            str(float(direct["v55_reference"]["current_density_a_m2"])),
            "--receiver-sec-values-kwh-kg",
            *values(DIRECT_RECEIVER_SEC_VALUES_KWH_KG),
        ],
        cwd=ROOT,
    )


def run_post_erv(
    config_path: Path,
    output_root: Path,
    v2_root: Path,
    jobs: int,
    detailed_cases: Path,
) -> None:
    out = output_root / "post_erv"
    audit = out / "audit.json"
    prior_audit = read_json(audit) if audit.is_file() else {}
    live_script = ROOT / "scripts" / "analyze_post_erv_inverse_design_v1.py"
    expected_detailed_hash = sha256(detailed_cases) if detailed_cases.is_file() else None
    validation = prior_audit.get("detailed_hvac_validation", {})
    reusable = bool(
        prior_audit.get("pass")
        and prior_audit.get("script_version") == EXPECTED_POST_ERV_SCRIPT_VERSION
        and prior_audit.get("script_sha256") == sha256(live_script)
        and prior_audit.get("central_manifest_sha256") == sha256(config_path)
        and isinstance(validation, dict)
        and validation.get("source_sha256") == expected_detailed_hash
        and prior_audit.get("area_observation_semantics_pass") is True
        and prior_audit.get("capped_area_prcc_excludes_unobserved_rows") is True
        and prior_audit.get("observed_area_prcc_target_reached_only") is True
        and prior_audit.get("saving_prcc_target_reached_only") is True
        and prior_audit.get("censor_prcc_uses_reached_or_censored") is True
        and prior_audit.get("feasibility_prcc_uses_all_cases") is True
        and prior_audit.get("surface_margin_endpoint_definition_pass") is True
        and prior_audit.get("target_reached_saving_mask_pass") is True
        and prior_audit.get("dense_censored_strictly_above_target") is True
        and prior_audit.get("global_censored_strictly_above_target") is True
        and prior_audit.get("finite_balance_counts_match_target_counts") is True
        and prior_audit.get("deterministic_case_ids_and_axes_pass") is True
        and prior_audit.get("sampled_coordinate_parameterization_explicit") is True
        and prior_audit.get("global_parameter_bounds_count") == 4
    )
    if reusable:
        print(f"Reusing audited post-ERV inverse-design study: {out}")
        return
    if not directory_is_empty(out):
        reusable_solver_rows = all(
            (out / name).is_file()
            for name in (
                "post_erv_archive_regression_cases.csv",
                "post_erv_dense_dj_cases.csv",
                "post_erv_global_inverse_design_cases.csv",
            )
        )
        if not reusable_solver_rows:
            raise StudyError(
                f"Post-ERV output exists but is incomplete and cannot be "
                f"postprocessed safely: {out}"
            )
        mode = ["--postprocess-existing"]
        print(
            "Postprocessing existing post-ERV solver rows because the prior "
            "audit does not satisfy the current semantics."
        )
    else:
        mode = []
    run(
        [
            sys.executable,
            "-B",
            str(ROOT / "scripts" / "analyze_post_erv_inverse_design_v1.py"),
            "--v2-root",
            str(v2_root),
            "--config",
            str(config_path),
            "--detailed-cases",
            str(detailed_cases),
            "--output-dir",
            str(out),
            "--jobs",
            str(jobs),
            *mode,
        ],
        cwd=ROOT,
    )


def run_detailed_hvac(output_root: Path, v2_root: Path, package_zip: Path) -> None:
    out = output_root / "post_erv_detailed_hvac"
    audit = out / "audit.json"
    if (
        audit.is_file()
        and bool(read_json(audit).get("pass"))
        and detailed_provenance_matches(out, package_zip)
    ):
        print(f"Reusing audited detailed-HVAC study: {out}")
        return
    if not directory_is_empty(out):
        raise StudyError(
            f"Detailed-HVAC output exists but lacks matching source-package/artifact "
            f"provenance: {out}"
        )
    if not package_zip.is_file():
        raise StudyError(f"Detailed-HVAC source package is missing: {package_zip}")
    with tempfile.TemporaryDirectory(prefix="heiq-post-erv-physics-") as temporary:
        temporary_path = Path(temporary)
        with zipfile.ZipFile(package_zip) as archive:
            archive.extractall(temporary_path)
        candidates = list(temporary_path.glob("*/run_pipeline.sh"))
        if len(candidates) != 1:
            raise StudyError("Detailed-HVAC ZIP does not contain one top-level run_pipeline.sh")
        environment = os.environ.copy()
        environment["PATH"] = f"{v2_root / '.venv' / 'bin'}:{environment.get('PATH', '')}"
        run(
            ["bash", str(candidates[0]), "study", str(v2_root), str(out)],
            cwd=v2_root,
            env=environment,
        )
    write_json(
        out / DETAILED_PROVENANCE_FILENAME,
        detailed_provenance_payload(out, package_zip),
    )


def physical_key(frame: pd.DataFrame) -> list[str]:
    candidates = [
        "current_density_a_m2",
        "dry_thickness_um",
        "receiver_control_activity",
        "transport_number_reference_t_w",
        "water_diffusivity_scale_vs_pfsa",
        "ionic_area_resistance_ohm_m2_at_lambda_ref",
        "retention_factor_vs_pfsa_sorption",
    ]
    return [column for column in candidates if column in frame]


def audit_and_summarise(
    config: dict[str, Any],
    config_path: Path,
    output_root: Path,
    detailed_zip: Path,
    v2_root: Path,
) -> dict[str, Any]:
    dense_path = output_root / "direct_eo_dense" / "joint_material_operating_gate_register.csv"
    dense_provenance_path = (
        output_root / "direct_eo_dense" / DIRECT_DENSE_PROVENANCE_FILENAME
    )
    global_path = Path(config["direct_eo"]["global_v53_gate_register"])
    direct_analysis = output_root / "direct_eo_analysis"
    direct_register_path = direct_analysis / "per_cap_robust_register.csv"
    direct_audit_path = direct_analysis / "audit.json"
    receiver_sec_summary_path = direct_analysis / "receiver_sec_cap_summary.csv"
    direct_neighbourhood_path = direct_analysis / "tw_diffusivity_3x3_neighborhood.csv"
    post_audit_path = output_root / "post_erv" / "audit.json"
    post_dense_path = output_root / "post_erv" / "post_erv_dense_dj_cases.csv"
    post_prcc_path = output_root / "post_erv" / "post_erv_global_prcc.csv"
    detailed_audit_path = output_root / "post_erv_detailed_hvac" / "audit.json"
    detailed_provenance_path = (
        output_root / "post_erv_detailed_hvac" / DETAILED_PROVENANCE_FILENAME
    )
    detailed_cases_path = (
        output_root
        / "post_erv_detailed_hvac"
        / "detailed_hvac_thermal_revaluation.csv"
    )
    detailed_base_cases_path = (
        output_root
        / "post_erv_detailed_hvac"
        / "detailed_hvac_base_cases_with_pareto_flag.csv"
    )
    required = [
        dense_path,
        dense_provenance_path,
        global_path,
        direct_register_path,
        direct_audit_path,
        receiver_sec_summary_path,
        direct_neighbourhood_path,
        post_audit_path,
        post_dense_path,
        post_prcc_path,
        detailed_audit_path,
        detailed_provenance_path,
        detailed_cases_path,
        detailed_base_cases_path,
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise StudyError(f"Missing final study files: {missing}")

    dense = pd.read_csv(dense_path, low_memory=False)
    global_frame = pd.read_csv(global_path, low_memory=False)
    robust = pd.read_csv(direct_register_path, low_memory=False)
    robust["per_cap_robust_pass"] = as_bool(robust["per_cap_robust_pass"])
    post_audit = read_json(post_audit_path)
    detailed_audit = read_json(detailed_audit_path)
    post_validation = post_audit.get("detailed_hvac_validation", {})
    live_post_script = ROOT / "scripts" / "analyze_post_erv_inverse_design_v1.py"

    axes = config["direct_eo"]["dense_axes"]
    expected_dense_physical = int(
        np.prod(
            [
                len(axes["current_density_a_m2"]),
                len(axes["transport_number_reference_t_w"]),
                len(axes["water_diffusivity_scale_vs_pfsa"]),
                len(axes["dry_thickness_um"]),
                len(axes["ionic_area_resistance_ohm_m2_at_lambda_ref"]),
                len(axes["retention_factor_vs_pfsa_sorption"]),
            ]
        )
    )
    dense_unique = len(dense.drop_duplicates(physical_key(dense)))
    global_unique = len(global_frame.drop_duplicates(physical_key(global_frame)))
    expected_dense_rows = expected_dense_physical * len(axes["cell_voltage_cap_tested_v"])

    direct_counts: list[dict[str, Any]] = []
    for (source, cap), group in robust.groupby(
        ["source_study", "cell_voltage_cap_tested_v"], sort=True
    ):
        direct_counts.append(
            {
                "source": str(source),
                "cap_v": float(cap),
                "evaluated": int(len(group)),
                "robust": int(group["per_cap_robust_pass"].sum()),
            }
        )

    detailed_cases = pd.read_csv(detailed_cases_path, low_memory=False)
    isothermal = detailed_cases[
        detailed_cases["scenario_id"].eq("isothermal_counterfactual")
        & as_bool(detailed_cases["transport_target_reached"])
        & as_bool(detailed_cases["transport_mechanism_energy_gate_pass"])
        & pd.to_numeric(
            detailed_cases["detailed_incremental_saving_kw"], errors="coerce"
        ).notna()
    ].copy()
    if isothermal.empty:
        raise StudyError("No valid target-reaching detailed-HVAC isothermal row")
    best_detailed = isothermal.loc[isothermal["detailed_incremental_saving_kw"].idxmax()]

    post_dense = pd.read_csv(post_dense_path, low_memory=False)
    post_positive = post_dense[as_bool(post_dense["conditional_energy_pass"])]
    best_post = post_positive.loc[
        post_positive["incremental_saving_kw_vs_passive_erv"].idxmax()
    ]
    prcc = pd.read_csv(post_prcc_path)
    saving_prcc = prcc[
        prcc["output"].eq("incremental_saving_kw_vs_passive_erv")
    ].copy()
    saving_prcc["absolute_prcc"] = saving_prcc["prcc"].abs()
    saving_prcc = saving_prcc.sort_values("absolute_prcc", ascending=False)
    observed_area_prcc = prcc[
        prcc["output"].eq("required_active_area_m2")
    ].copy()
    observed_area_prcc["absolute_prcc"] = observed_area_prcc["prcc"].abs()
    observed_area_prcc = observed_area_prcc.sort_values(
        "absolute_prcc", ascending=False
    )
    backdiffusion_prcc = prcc[
        prcc["output"].eq("absolute_diffusion_fraction_of_eo")
    ].copy()
    backdiffusion_prcc["absolute_prcc"] = backdiffusion_prcc["prcc"].abs()
    backdiffusion_prcc = backdiffusion_prcc.sort_values(
        "absolute_prcc", ascending=False
    )

    receiver_sec_summary = pd.read_csv(receiver_sec_summary_path, low_memory=False)
    dense_receiver_sec = receiver_sec_summary[
        receiver_sec_summary["source_study"].eq("dense_local")
        & np.isclose(receiver_sec_summary["cell_voltage_cap_tested_v"], 5.0)
    ].copy()
    dense_receiver_sec_010_rows = dense_receiver_sec[
        np.isclose(dense_receiver_sec["receiver_sec_assumed_kwh_kg"], 0.10)
    ]
    dense_receiver_sec_015_rows = dense_receiver_sec[
        np.isclose(dense_receiver_sec["receiver_sec_assumed_kwh_kg"], 0.15)
    ]
    if len(dense_receiver_sec_010_rows) != 1 or len(dense_receiver_sec_015_rows) != 1:
        raise StudyError("Direct-EO receiver SEC summary lacks unique 0.10/0.15 rows")
    dense_receiver_sec_010 = dense_receiver_sec_010_rows.iloc[0]
    dense_receiver_sec_015 = dense_receiver_sec_015_rows.iloc[0]

    dense_primary = robust[
        robust["source_study"].eq("dense_local")
        & np.isclose(robust["cell_voltage_cap_tested_v"], 5.0)
    ].copy()
    dense_primary_current = dense_primary[
        np.isclose(dense_primary["current_density_a_m2"], 50.0)
        & dense_primary["per_cap_robust_pass"]
    ].copy()
    if dense_primary_current.empty:
        raise StudyError("Direct-EO primary 5 V / 50 A/m2 robust slice is empty")
    direct_neighbourhood = pd.read_csv(direct_neighbourhood_path, low_memory=False)
    stable_primary = direct_neighbourhood[
        direct_neighbourhood["source_study"].eq("dense_local")
        & np.isclose(direct_neighbourhood["cell_voltage_cap_tested_v"], 5.0)
        & np.isclose(direct_neighbourhood["current_density_a_m2"], 50.0)
        & as_bool(direct_neighbourhood["all_3x3_cells_have_robust_pass"])
    ].copy()
    if stable_primary.empty:
        raise StudyError("Direct-EO primary slice has no complete robust 3x3 centre")

    direct_span = {
        "transport_number_min": float(
            dense_primary_current["transport_number_reference_t_w"].min()
        ),
        "transport_number_max": float(
            dense_primary_current["transport_number_reference_t_w"].max()
        ),
        "diffusivity_scale_min": float(
            dense_primary_current["water_diffusivity_scale_vs_pfsa"].min()
        ),
        "diffusivity_scale_max": float(
            dense_primary_current["water_diffusivity_scale_vs_pfsa"].max()
        ),
        "stable_transport_number_min": float(
            stable_primary["transport_number_reference_t_w"].min()
        ),
        "stable_transport_number_max": float(
            stable_primary["transport_number_reference_t_w"].max()
        ),
    }

    sensitivity_labels = {
        "uniform_current_density_a_m2": "current density",
        "water_drag": "water drag",
        "diffusive_permeability_d_c_over_l_mol_m2_s_activity": "D·C/L",
        "total_reference_area_resistance_ohm_m2": "L/σ + series ASR",
    }
    saving_sensitivity_text = ", ".join(
        f"{sensitivity_labels.get(str(row['parameter']), str(row['parameter']))} "
        f"(PRCC {float(row['prcc']):.3f})"
        for _, row in saving_prcc.head(3).iterrows()
    )
    area_sensitivity_text = ", ".join(
        f"{sensitivity_labels.get(str(row['parameter']), str(row['parameter']))} "
        f"(PRCC {float(row['prcc']):+.3f})"
        for _, row in observed_area_prcc.head(3).iterrows()
    )

    post_target = as_bool(post_dense["target_reached"])
    post_censored = as_bool(post_dense["area_is_right_censored"])
    post_surface_positive = as_bool(
        post_dense["positive_surface_direction_everywhere"]
    )

    audit_pass = bool(
        len(dense) == expected_dense_rows
        and dense_unique == expected_dense_physical
        and len(global_frame) == 46080
        and global_unique == 11520
        and direct_dense_provenance_matches(
            config,
            output_root / "direct_eo_dense",
            v2_root / "scripts" / "make_wp1_symmetric_wet_receiver_sink_v53.py",
        )
        and direct_analysis_audit_matches(
            direct_audit_path,
            config=config,
            config_path=config_path,
            output_root=output_root,
            v2_root=v2_root,
        )
        and bool(post_audit.get("pass"))
        and post_audit.get("script_version") == EXPECTED_POST_ERV_SCRIPT_VERSION
        and post_audit.get("script_sha256") == sha256(live_post_script)
        and post_audit.get("central_manifest_sha256") == sha256(config_path)
        and isinstance(post_validation, dict)
        and post_validation.get("source_sha256")
        == sha256(detailed_base_cases_path)
        and post_audit.get("area_observation_semantics_pass") is True
        and post_audit.get("capped_area_prcc_excludes_unobserved_rows") is True
        and post_audit.get("observed_area_prcc_target_reached_only") is True
        and post_audit.get("saving_prcc_target_reached_only") is True
        and post_audit.get("censor_prcc_uses_reached_or_censored") is True
        and post_audit.get("feasibility_prcc_uses_all_cases") is True
        and post_audit.get("surface_margin_endpoint_definition_pass") is True
        and post_audit.get("target_reached_saving_mask_pass") is True
        and post_audit.get("dense_censored_strictly_above_target") is True
        and post_audit.get("global_censored_strictly_above_target") is True
        and post_audit.get("finite_balance_counts_match_target_counts") is True
        and post_audit.get("deterministic_case_ids_and_axes_pass") is True
        and post_audit.get("sampled_coordinate_parameterization_explicit") is True
        and post_audit.get("global_parameter_bounds_count") == 4
        and bool(detailed_audit.get("pass"))
        and detailed_provenance_matches(
            output_root / "post_erv_detailed_hvac", detailed_zip
        )
        and post_audit.get("engineering_current_density_limit_a_m2") is None
        and bool(post_audit.get("full_system_status_unknown_everywhere"))
        and config["current_density_policy"]["engineering_current_density_limit_a_m2"]
        is None
        and config["system_closure_policy"]["missing_receiver_energy_status"]
        == "UNKNOWN"
    )
    payload = {
        "study_id": config["study_id"],
        "pass": audit_pass,
        "current_density_acceptance_limit_a_m2": None,
        "current_density_is_sampling_or_control_axis": True,
        "no_21_a_m2_gate_applied": True,
        "full_system_status": "UNKNOWN",
        "full_system_claim_allowed": False,
        "direct_dense_cap_rows": len(dense),
        "direct_dense_physical_states": dense_unique,
        "direct_global_cap_rows": len(global_frame),
        "direct_global_physical_states": global_unique,
        "direct_cap_specific_robust_counts": direct_counts,
        "direct_primary_5v_50a_tested_span": direct_span,
        "post_erv_dense_cases": int(post_audit["dense_case_count"]),
        "post_erv_global_lhs_cases": int(post_audit["global_lhs_case_count"]),
        "post_erv_archive_regression_pass": bool(post_audit["archive_regression_pass"]),
        "post_erv_script_version": str(post_audit["script_version"]),
        "post_erv_area_observation_semantics_pass": bool(
            post_audit["area_observation_semantics_pass"]
        ),
        "post_erv_surface_margin_endpoint_definition_pass": bool(
            post_audit["surface_margin_endpoint_definition_pass"]
        ),
        "post_erv_saving_prcc_target_reached_only": bool(
            post_audit["saving_prcc_target_reached_only"]
        ),
        "post_erv_dense_conditional_positive": int(
            as_bool(post_dense["conditional_energy_pass"]).sum()
        ),
        "post_erv_dense_target_reached": int(post_target.sum()),
        "post_erv_dense_area_right_censored": int(post_censored.sum()),
        "post_erv_dense_unobserved_area": int((~(post_target | post_censored)).sum()),
        "post_erv_dense_positive_surface_direction": int(post_surface_positive.sum()),
        "post_erv_best_screening": {
            "water_diffusivity_m2_s": float(best_post["water_diffusivity_m2_s"]),
            "current_density_a_m2": float(best_post["uniform_current_density_a_m2"]),
            "conditional_saving_kw": float(
                best_post["incremental_saving_kw_vs_passive_erv"]
            ),
            "required_area_m2": float(best_post["required_active_area_censored_m2"]),
        },
        "post_erv_top_prcc_for_screening_saving": [
            {
                "parameter": str(row["parameter"]),
                "prcc": float(row["prcc"]),
                "ci025": float(row["prcc_ci025"]),
                "ci975": float(row["prcc_ci975"]),
            }
            for _, row in saving_prcc.iterrows()
        ],
        "post_erv_top_prcc_for_observed_area": [
            {
                "parameter": str(row["parameter"]),
                "prcc": float(row["prcc"]),
                "ci025": float(row["prcc_ci025"]),
                "ci975": float(row["prcc_ci975"]),
            }
            for _, row in observed_area_prcc.iterrows()
        ],
        "post_erv_detailed_hvac": {
            "transport_cases": int(detailed_audit["transport_case_count"]),
            "scenario_rows": int(detailed_audit["detailed_hvac_scenario_count"]),
            "uncertainty_rows": int(detailed_audit["conditional_uncertainty_scenario_count"]),
            "best_isothermal_saving_kw": float(
                best_detailed["detailed_incremental_saving_kw"]
            ),
            "best_isothermal_saving_pct": float(
                best_detailed["detailed_incremental_saving_pct"]
            ),
            "best_isothermal_diffusivity_m2_s": float(
                best_detailed["water_diffusivity_m2_s"]
            ),
            "best_isothermal_current_density_a_m2": float(
                best_detailed["uniform_current_density_a_m2"]
            ),
        },
        "sha256": {
            "config": sha256(config_path),
            "direct_dense_register": sha256(dense_path),
            "direct_dense_provenance": sha256(dense_provenance_path),
            "direct_global_register": sha256(global_path),
            "direct_analysis_audit": sha256(direct_audit_path),
            "post_erv_audit": sha256(post_audit_path),
            "detailed_hvac_audit": sha256(detailed_audit_path),
            "detailed_hvac_provenance": sha256(detailed_provenance_path),
            "detailed_source_zip": sha256(detailed_zip) if detailed_zip.is_file() else None,
        },
    }
    write_json(output_root / "study_audit.json", payload)

    lines = [
        "# Membrane operating-region study v1",
        "",
        f"Final computational audit: **{'PASS' if audit_pass else 'FAIL'}**.",
        "",
        "## Scope",
        "",
        "EO after ERV and direct EO are evaluated as separate architectures with separate references and duties. Current density is a sampled operating coordinate; no 21 A/m² acceptance limit is used. Receiver/regeneration energy is unresolved, so full-system status remains **UNKNOWN** everywhere.",
        "",
        "## Counts",
        "",
        f"- Direct EO: {len(global_frame):,} global cap rows / {global_unique:,} physical states, plus {len(dense):,} dense cap rows / {dense_unique:,} physical states.",
        f"- EO after ERV: {len(post_dense):,} dense D–j cases and {int(post_audit['global_lhs_case_count']):,} global inverse-design cases.",
        f"- Detailed EO-after-ERV replay: {int(detailed_audit['transport_case_count'])} transport cases, {int(detailed_audit['detailed_hvac_scenario_count'])} HVAC/thermal rows and {int(detailed_audit['conditional_uncertainty_scenario_count'])} deterministic uncertainty rows.",
        "",
        "## Main numerical results",
        "",
        "### Direct EO",
        "",
        f"- Dense robust region: {int(robust[(robust['source_study'].eq('dense_local')) & np.isclose(robust['cell_voltage_cap_tested_v'], 3.0)]['per_cap_robust_pass'].sum())}/{int(((robust['source_study'].eq('dense_local')) & np.isclose(robust['cell_voltage_cap_tested_v'], 3.0)).sum())} at 3 V and {int(robust[(robust['source_study'].eq('dense_local')) & np.isclose(robust['cell_voltage_cap_tested_v'], 5.0)]['per_cap_robust_pass'].sum())}/{int(((robust['source_study'].eq('dense_local')) & np.isclose(robust['cell_voltage_cap_tested_v'], 5.0)).sum())} at 5 V.",
        f"- At 5 V and 50 A/m², the tested robust span is t_w={direct_span['transport_number_min']:.0f}–{direct_span['transport_number_max']:.0f} and diffusivity scale {direct_span['diffusivity_scale_min']:.3g}–{direct_span['diffusivity_scale_max']:.3g} × PFSA; complete 3×3 neighbourhood centres occur at t_w={direct_span['stable_transport_number_min']:.0f}–{direct_span['stable_transport_number_max']:.0f}.",
        f"- A receiver duty of 0.10 kWh/kg leaves {int(dense_receiver_sec_010['positive_coordinates_after_receiver_energy'])}/{int(dense_receiver_sec_010['robust_coordinates_before_receiver_energy'])} dense 5 V robust points conditionally positive; at 0.15 kWh/kg this falls to {int(dense_receiver_sec_015['positive_coordinates_after_receiver_energy'])}.",
        "",
        "### EO after ERV",
        "",
        f"- Dense map: {int(as_bool(post_dense['conditional_energy_pass']).sum())}/{len(post_dense)} conditionally positive, {int(post_censored.sum())} area-right-censored, and {int((~(post_target | post_censored)).sum())} failed/unobserved rows omitted from area statistics.",
        f"- Best dense post-ERV screening point: {float(best_post['incremental_saving_kw_vs_passive_erv']):.3f} kW at D={float(best_post['water_diffusivity_m2_s']):.3e} m²/s and j={float(best_post['uniform_current_density_a_m2']):.2f} A/m².",
        f"- Best evaluated detailed-HVAC post-ERV point: {float(best_detailed['detailed_incremental_saving_kw']):.3f} kW ({float(best_detailed['detailed_incremental_saving_pct']):.3f} %).",
        f"- Strongest target-reached saving sensitivities are {saving_sensitivity_text}; these are inverse-design rank sensitivities, not material probabilities.",
        f"- Observed-area sensitivity among target-reaching rows is led by {area_sensitivity_text}. D·C/L also controls the opposing-diffusion fraction almost one-for-one in rank (PRCC {float(backdiffusion_prcc.iloc[0]['prcc']):+.3f}).",
        f"- Positive surface-direction rows: {int(post_surface_positive.sum())}/{len(post_dense)}. This boundary incompatibility must be resolved before calling the post-ERV region a material pass.",
        "",
        "## Decision boundary",
        "",
        "The calculations support concrete membrane target regions and receiver-energy budgets. They do not close receiver regeneration, conjugate thermal feedback, packaging, electrodes, lifetime or manufacturability. Material screening can start against the composite transport/electrical targets, but procurement should not be presented as evidence of a closed full system.",
        "",
        "Detailed registers and plots are in `direct_eo_analysis/`, `post_erv/` and `post_erv_detailed_hvac/`.",
        "",
        "These are conditional model results, not evidence that a full receiver/module/material system has been closed or manufactured.",
        "",
    ]
    (output_root / "STUDY_SUMMARY.md").write_text("\n".join(lines), encoding="utf-8")
    if not audit_pass:
        raise StudyError("Combined study audit failed; inspect study_audit.json")
    return payload


def main() -> int:
    args = parse_args()
    config_path = args.config.expanduser().resolve()
    output_root = args.output_root.expanduser().resolve()
    v2_root = args.v2_root.expanduser().resolve()
    detailed_zip = args.detailed_package_zip.expanduser().resolve()
    config = read_json(config_path)
    output_root.mkdir(parents=True, exist_ok=True)

    if not args.audit_only:
        run_direct_dense(config, output_root, v2_root)
        run_direct_analysis(config, config_path, output_root, v2_root)
        run_detailed_hvac(output_root, v2_root, detailed_zip)
        run_post_erv(
            config_path,
            output_root,
            v2_root,
            args.post_erv_jobs,
            output_root
            / "post_erv_detailed_hvac"
            / "detailed_hvac_base_cases_with_pareto_flag.csv",
        )

    result = audit_and_summarise(
        config, config_path, output_root, detailed_zip, v2_root
    )
    print("Combined study audit: PASS")
    print(f"Outputs: {output_root}")
    print("Full-system status: UNKNOWN (receiver/regeneration energy unresolved)")
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
