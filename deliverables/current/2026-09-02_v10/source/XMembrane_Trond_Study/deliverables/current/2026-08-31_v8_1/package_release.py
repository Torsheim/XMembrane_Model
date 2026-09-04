#!/usr/bin/env python3
"""Build the fail-closed XMembrane 2026-08-31 V8.1 English release package.

The script intentionally uses only the Python standard library. It copies an
explicit allowlist, verifies source and report manifests, checks report
freshness, runs the repository final-delivery checker in a temporary directory,
and creates deterministic source/results ZIP files plus release checksums.

Nothing is packaged unless every preflight check passes. Use ``--check-only``
before the final packaging run. This file is a scaffold and must not be run
until the report owners have declared the inputs final. V8.1 is an additive
English-reporting release and never mutates its hash-frozen V8 parent.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import shutil
import stat as stat_module
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence


RELEASE_ID = "XMEMBRANE-2026-08-31-V8.1"
SCHEMA_VERSION = 1
SCRIPT_VERSION = "xmembrane-v8.1-packager-1.0"
RELEASE_DIR = Path(__file__).resolve().parent
DEFAULT_REPO_ROOT = RELEASE_DIR.parents[2]

RELEASE_SCOPE = "translation_and_English_delivery_only"
PARENT_RELEASE_ID = "XMEMBRANE-2026-08-31-V8"
PARENT_RELEASE_MANIFEST = "deliverables/current/2026-08-31_v8/MANIFEST.json"
PARENT_RELEASE_MANIFEST_SHA256 = (
    "51f8ba4742af613a7b24d4d94062d4ad4b6a5440ed83149015c07afb9cf234fd"
)
PARENT_RELEASE_BINDING = (
    PARENT_RELEASE_MANIFEST,
    PARENT_RELEASE_MANIFEST_SHA256,
    PARENT_RELEASE_ID,
)
SOURCE_ARCHIVE_NAME = "HeiQ_XMembrane_2026-08-31_v8_1_source.zip"
RESULTS_ARCHIVE_NAME = "HeiQ_XMembrane_2026-08-31_v8_1_results.zip"

HASH_RE = re.compile(r"^[0-9a-f]{64}$")
MANIFEST_BINDING_CONTAINERS = {
    "canonical_source_records",
    "files",
    "file_sha256",
    "figures",
    "generated_outputs",
    "inputs",
    "source_files_sha256",
    "input_sha256",
    "generated_files",
    "outputs",
    "referenced_figures",
    "report_files",
    "sources",
    "source_files",
}
REPO_RELATIVE_PREFIXES = {
    "config",
    "deliverables",
    "outputs",
    "reports",
    "scripts",
    "src",
    "tests",
}
BUILD_SUFFIXES = {
    ".aux",
    ".bbl",
    ".blg",
    ".fdb_latexmk",
    ".fls",
    ".log",
    ".out",
    ".synctex.gz",
    ".toc",
    ".pyc",
    ".pyo",
}
FORBIDDEN_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
}
GENERATED_TARGETS = (
    "reports",
    "source",
    "results",
    "verification",
    "archives",
    "MANIFEST.json",
    "SHA256SUMS",
)
GENERATED_DIRECTORY_TARGETS = {
    "reports",
    "source",
    "results",
    "verification",
    "archives",
}
GENERATED_FILE_TARGETS = {"MANIFEST.json", "SHA256SUMS"}
SCAFFOLD_FILES = ("README.md", "RELEASE_NOTES.md", "package_release.py")
FINAL_CHECK_FILES = (
    "status.json",
    "gate_register.csv",
    "SUMMARY.md",
    "test_run.json",
    "source_manifest.json",
)


class PackagingError(RuntimeError):
    """Raised when a fail-closed release condition is not met."""


@dataclass(frozen=True)
class Artifact:
    source: str
    destination: str
    role: str
    category: str


@dataclass(frozen=True)
class ReportSpec:
    report_id: str
    tex: str
    pdf: str
    readme: str
    manifest: str


def artifact(source: str, destination: str, role: str, category: str) -> Artifact:
    return Artifact(source, destination, role, category)


REPORTS: tuple[ReportSpec, ...] = (
    ReportSpec(
        "current_result_v8",
        "reports/team_result_atlas_v8/HeiQ_XMembrane_Current_Result_and_Decision_Report_2026-08-31_v8.tex",
        "reports/team_result_atlas_v8/HeiQ_XMembrane_Current_Result_and_Decision_Report_2026-08-31_v8.pdf",
        "reports/team_result_atlas_v8/README.md",
        "reports/team_result_atlas_v8/source_manifest.json",
    ),
    ReportSpec(
        "eo_vapor_cell_v2_en",
        "reports/eo_vapor_boundary_analysis_v2_en/HeiQ_EO_Vapour_Cell_Boundary_Conditions_and_Sizing_2026-08-31_v2.tex",
        "reports/eo_vapor_boundary_analysis_v2_en/HeiQ_EO_Vapour_Cell_Boundary_Conditions_and_Sizing_2026-08-31_v2.pdf",
        "reports/eo_vapor_boundary_analysis_v2_en/README.md",
        "reports/eo_vapor_boundary_analysis_v2_en/source_manifest.json",
    ),
    ReportSpec(
        "model_closure",
        "reports/model_closure_2026-08-31/HeiQ_XMembrane_Model_Closure_and_Material_Handoff_2026-08-31.tex",
        "reports/model_closure_2026-08-31/HeiQ_XMembrane_Model_Closure_and_Material_Handoff_2026-08-31.pdf",
        "reports/model_closure_2026-08-31/README.md",
        "reports/model_closure_2026-08-31/source_manifest.json",
    ),
)

ENGLISH_TRANSLATION_MANIFEST = REPORTS[1].manifest
CANONICAL_NORWEGIAN_V2_SOURCE = (
    "reports/eo_vapor_boundary_analysis_v2_no/"
    "HeiQ_EO_Dampcelle_Randbetingelser_og_Dimensjonering_2026-08-31_v2.tex"
)
CANONICAL_NORWEGIAN_V2_SOURCE_SHA256 = (
    "3c31268bd8f1fd9637230b7b56b9fc0ddd89b3af0d38088bec1fd0f796c991a9"
)


REPORT_REQUIRED_BINDINGS: dict[str, tuple[str, ...]] = {
    "current_result_v8": (
        "outputs/direct_active_eo_erv_study_v1/study/study_audit.json",
        "outputs/direct_erv_gradient_closure_v1/source_manifest.json",
        "outputs/workshop_common_voltage_diffusivity_v1/audit.json",
        "outputs/workshop_common_voltage_diffusivity_v1/source_manifest.json",
        "outputs/fom_assessment_v1/audit.json",
        "outputs/fom_assessment_v1/source_manifest.json",
        "outputs/project_closure_check_v1/closure_status.json",
        "outputs/project_closure_check_v1/decision_gate_register.csv",
        "outputs/project_closure_check_v1/source_manifest.json",
        "outputs/eo_vapor_boundary_analysis_v1/audit.json",
        "outputs/eo_vapor_cell_sizing_v1/audit.json",
        "outputs/eo_vapor_cell_sizing_v1/source_manifest.json",
    ),
    "eo_vapor_cell_v2_en": (
        "outputs/eo_vapor_boundary_analysis_v1/audit.json",
        "outputs/eo_vapor_boundary_analysis_v1/scenario_summary.csv",
        "outputs/eo_vapor_boundary_analysis_v1/combined_sensitivity_rank.csv",
        "outputs/eo_vapor_boundary_analysis_v1/aperture_design_identifiability.csv",
        "outputs/eo_vapor_cell_sizing_v1/SUMMARY.md",
        "outputs/eo_vapor_cell_sizing_v1/audit.json",
        "outputs/eo_vapor_cell_sizing_v1/source_manifest.json",
    ),
    "model_closure": (
        "outputs/direct_active_eo_erv_study_v1/study/study_audit.json",
        "outputs/direct_erv_gradient_closure_v1/audit.json",
        "outputs/direct_erv_gradient_closure_v1/source_manifest.json",
        "outputs/fom_assessment_v1/device_fom.csv",
        "outputs/fom_assessment_v1/system_fom.csv",
        "outputs/project_closure_check_v1/closure_status.json",
        "outputs/project_closure_check_v1/decision_gate_register.csv",
        "outputs/project_closure_check_v1/source_manifest.json",
    ),
}


COPY_ALLOWLIST: tuple[Artifact, ...] = (
    # Canonical and supporting reports. Build artefacts are intentionally absent.
    artifact(REPORTS[0].pdf, f"reports/current_result/{Path(REPORTS[0].pdf).name}", "result", "canonical_report"),
    artifact(REPORTS[0].tex, f"reports/current_result/{Path(REPORTS[0].tex).name}", "source", "canonical_report"),
    artifact(REPORTS[0].readme, "reports/current_result/README.md", "source", "canonical_report"),
    artifact(REPORTS[0].manifest, "reports/current_result/source_manifest.json", "source", "canonical_report"),
    artifact(REPORTS[1].pdf, f"reports/eo_vapor_cell_en/{Path(REPORTS[1].pdf).name}", "result", "canonical_report"),
    artifact(REPORTS[1].tex, f"reports/eo_vapor_cell_en/{Path(REPORTS[1].tex).name}", "source", "canonical_report"),
    artifact(REPORTS[1].readme, "reports/eo_vapor_cell_en/README.md", "source", "canonical_report"),
    artifact(REPORTS[1].manifest, "reports/eo_vapor_cell_en/source_manifest.json", "source", "canonical_report"),
    artifact(REPORTS[2].pdf, f"reports/model_closure/{Path(REPORTS[2].pdf).name}", "result", "supporting_report"),
    artifact(REPORTS[2].tex, f"reports/model_closure/{Path(REPORTS[2].tex).name}", "source", "supporting_report"),
    artifact(REPORTS[2].readme, "reports/model_closure/README.md", "source", "supporting_report"),
    artifact(REPORTS[2].manifest, "reports/model_closure/source_manifest.json", "source", "supporting_report"),

    # Exact parent-release binding. This file is copied into the source archive
    # and its fixed hash/release identity are rechecked at every hard barrier.
    artifact(
        PARENT_RELEASE_MANIFEST,
        "source/parent_release/XMembrane_2026-08-31_V8_MANIFEST.json",
        "source",
        "parent_release_binding",
    ),

    # Frozen configuration and executable analysis chain.
    *tuple(
        artifact(f"config/{name}", f"source/config/{name}", "source", "config")
        for name in (
            "direct_active_eo_erv_study_v1.json",
            "direct_erv_gradient_closure_v1.json",
            "workshop_common_voltage_diffusivity_v1.json",
            "fom_assessment_v1.json",
            "eo_vapor_boundary_analysis_v1.json",
            "eo_vapor_cell_sizing_v1.json",
            "project_closure_check_v1.json",
            "final_delivery_check_v1.json",
        )
    ),
    *tuple(
        artifact(f"scripts/{name}", f"source/scripts/{name}", "source", "script")
        for name in (
            "run_direct_active_eo_erv_study_v1.py",
            "run_direct_erv_gradient_closure_v1.py",
            "run_workshop_common_voltage_diffusivity_v1.py",
            "calculate_fom_assessment_v1.py",
            "analyze_eo_vapor_boundaries_v1.py",
            "size_eo_vapor_cell_v1.py",
            "run_project_closure_check_v1.py",
            "run_final_delivery_check_v1.py",
        )
    ),
    *tuple(
        artifact(f"tests/{name}", f"source/tests/{name}", "source", "test")
        for name in (
            "test_direct_active_eo_erv_study_v1.py",
            "test_direct_erv_gradient_closure_v1.py",
            "test_workshop_common_voltage_diffusivity_v1.py",
            "test_fom_assessment_v1.py",
            "test_eo_vapor_boundary_analysis_v1.py",
            "test_eo_vapor_cell_sizing_v1.py",
            "test_project_closure_check_v1.py",
            "test_final_delivery_check_v1.py",
        )
    ),

    # Selected direct-active and gradient-closure evidence.
    *tuple(
        artifact(
            f"outputs/direct_active_eo_erv_study_v1/study/{name}",
            f"results/direct_active_erv/{name}",
            "result",
            "direct_active_erv",
        )
        for name in (
            "DECISION_SUMMARY.json",
            "SUMMARY.md",
            "selected_cases.csv",
            "target_summary.csv",
            "gate_counts.csv",
            "segment_convergence.csv",
            "study_audit.json",
        )
    ),
    *tuple(
        artifact(
            f"outputs/direct_erv_gradient_closure_v1/{name}",
            f"results/direct_erv_gradient/{name}",
            "result",
            "direct_erv_gradient",
        )
        for name in (
            "SUMMARY.md",
            "audit.json",
            "case_summary.csv",
            "film_area_sweep.csv",
            "signed_triplet.csv",
            "source_manifest.json",
        )
    ),

    # Project closure and common-voltage decision summaries.
    *tuple(
        artifact(
            f"outputs/project_closure_check_v1/{name}",
            f"results/project_closure/{name}",
            "result",
            "project_closure",
        )
        for name in (
            "SUMMARY.md",
            "closure_status.json",
            "decision_gate_register.csv",
            "active_erv_reclassification.csv",
            "common_voltage_window_summary.csv",
            "common_voltage_convergence.csv",
            "independent_voltage_root_replay.csv",
            "uniform_current_convergence.csv",
            "source_manifest.json",
        )
    ),
    *tuple(
        artifact(
            f"outputs/workshop_common_voltage_diffusivity_v1/{name}",
            f"results/common_voltage/{name}",
            "result",
            "common_voltage",
        )
        for name in (
            "README.md",
            "audit.json",
            "cases.csv",
            "diffusivity_envelope.csv",
            "local_bracket_probe.csv",
            "segment_convergence.csv",
            "source_manifest.json",
        )
    ),

    # FOM boundary and open-ledger summaries.
    *tuple(
        artifact(
            f"outputs/fom_assessment_v1/{name}",
            f"results/fom/{name}",
            "result",
            "fom",
        )
        for name in (
            "audit.json",
            "summary.json",
            "device_fom.csv",
            "system_fom.csv",
            "thirteen_fom_register.csv",
            "economic_sensitivity.csv",
            "operating_point.csv",
            "source_manifest.json",
        )
    ),

    # EO vapour-cell boundary and sizing summaries. Sizing audit/provenance are
    # mandatory release inputs, not optional metadata.
    *tuple(
        artifact(
            f"outputs/eo_vapor_boundary_analysis_v1/{name}",
            f"results/eo_vapor_boundary/{name}",
            "result",
            "eo_vapor_boundary",
        )
        for name in (
            "SUMMARY.md",
            "audit.json",
            "source_manifest.json",
            "config_used.json",
            "nominal_cases.csv",
            "scenario_summary.csv",
            "combined_sensitivity_rank.csv",
            "aperture_design_identifiability.csv",
        )
    ),
    *tuple(
        artifact(
            f"outputs/eo_vapor_cell_sizing_v1/{name}",
            f"results/eo_vapor_sizing/{name}",
            "result",
            "eo_vapor_sizing",
        )
        for name in (
            "SUMMARY.md",
            "audit.json",
            "source_manifest.json",
            "config_used.json",
            "fixture_dimension_basis.csv",
            "aperture_insert_dimensions.csv",
            "internal_volume_budget.csv",
            "detectability_flow_limits.csv",
            "plate_deflection_screen.csv",
            "closed_cell_dimension_screen.csv",
            "boundary_activity_mismatch_screen.csv",
            "membrane_diffusion_time_scale.csv",
            "gross_signal_envelope_25cm2.png",
            "cell_dimension_tradeoffs.png",
        )
    ),
)


PROVENANCE_MANIFESTS: tuple[str, ...] = (
    "outputs/direct_active_eo_erv_study_v1/study/study_audit.json",
    "outputs/direct_erv_gradient_closure_v1/source_manifest.json",
    "outputs/workshop_common_voltage_diffusivity_v1/source_manifest.json",
    "outputs/fom_assessment_v1/source_manifest.json",
    "outputs/project_closure_check_v1/source_manifest.json",
    "outputs/eo_vapor_boundary_analysis_v1/source_manifest.json",
    "outputs/eo_vapor_cell_sizing_v1/source_manifest.json",
)


AUDIT_CONTRACTS: tuple[tuple[str, tuple[str, ...], Any], ...] = (
    ("outputs/direct_active_eo_erv_study_v1/study/study_audit.json", ("status",), "PASS"),
    ("outputs/direct_erv_gradient_closure_v1/audit.json", ("status",), "PASS"),
    ("outputs/workshop_common_voltage_diffusivity_v1/audit.json", ("passed",), True),
    ("outputs/fom_assessment_v1/audit.json", ("all_pass",), True),
    ("outputs/eo_vapor_boundary_analysis_v1/audit.json", ("canonical_crosscheck_pass",), True),
    ("outputs/eo_vapor_cell_sizing_v1/audit.json", ("all_pass",), True),
    ("outputs/project_closure_check_v1/closure_status.json", ("broad_modelling_can_stop",), True),
    ("outputs/project_closure_check_v1/closure_status.json", ("material_data_collection_ready",), True),
    ("outputs/project_closure_check_v1/closure_status.json", ("material_candidate_ranking_ready",), False),
    ("outputs/project_closure_check_v1/closure_status.json", ("full_system_claim_allowed",), False),
    ("outputs/project_closure_check_v1/closure_status.json", ("technology_validated",), False),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=DEFAULT_REPO_ROOT,
        help="Repository root; defaults to the root containing this release directory.",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Run every preflight and live final check, but create no package files.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace only the known generated targets for this exact release.",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run isolated packager safety tests; do not inspect or package release inputs.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=3600,
        help="Timeout passed to the live final-delivery check.",
    )
    args = parser.parse_args()
    if args.self_test and (args.check_only or args.overwrite):
        parser.error("--self-test cannot be combined with --check-only or --overwrite")
    return args


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_regular_file(path: Path) -> None:
    if not path.is_file():
        raise PackagingError(f"Required input is missing or not a file: {path}")
    if path.stat().st_size <= 0:
        raise PackagingError(f"Required input is empty: {path}")


def verify_parent_release_binding(
    repo_root: Path,
    binding: tuple[str, str, str] = PARENT_RELEASE_BINDING,
) -> dict[str, Any]:
    """Verify the exact immutable parent manifest and its declared identity."""

    relative, expected_sha256, expected_release_id = binding
    if not HASH_RE.fullmatch(expected_sha256):
        raise PackagingError(
            f"Invalid configured parent-manifest SHA-256: {expected_sha256!r}"
        )
    path = (repo_root / relative).resolve()
    ensure_within(path, repo_root, "Parent release manifest")
    require_regular_file(path)
    actual_sha256 = sha256_file(path)
    if actual_sha256 != expected_sha256:
        raise PackagingError(
            "Parent release manifest hash mismatch: "
            f"{relative}; expected {expected_sha256}, got {actual_sha256}"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PackagingError(f"Invalid parent release manifest: {path}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise PackagingError(f"Parent release manifest must be a JSON object: {path}")
    if payload.get("release_id") != expected_release_id:
        raise PackagingError(
            "Parent release identity mismatch: "
            f"expected {expected_release_id!r}, got {payload.get('release_id')!r}"
        )
    return {
        "path": relative,
        "sha256": actual_sha256,
        "release_id": expected_release_id,
        "binding_type": "immutable_parent_release_manifest",
    }


def ensure_within(path: Path, root: Path, label: str) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise PackagingError(f"{label} escapes its allowed root: {path}") from exc


def validate_allowlist(
    repo_root: Path, items: Sequence[Artifact] = COPY_ALLOWLIST
) -> None:
    destinations: set[str] = set()
    for item in items:
        source_rel = PurePosixPath(item.source)
        destination_rel = PurePosixPath(item.destination)
        if source_rel.is_absolute() or destination_rel.is_absolute():
            raise PackagingError(f"Allowlist paths must be relative: {item}")
        if ".." in source_rel.parts or ".." in destination_rel.parts:
            raise PackagingError(f"Allowlist path traversal is forbidden: {item}")
        if any(part in FORBIDDEN_PARTS for part in source_rel.parts + destination_rel.parts):
            raise PackagingError(f"Cache/build directory is forbidden in allowlist: {item}")
        source_suffixes = Path(item.source).suffixes
        if source_suffixes and "".join(source_suffixes[-2:]) == ".synctex.gz":
            raise PackagingError(f"Build artefact is forbidden in allowlist: {item.source}")
        if Path(item.source).suffix in BUILD_SUFFIXES:
            raise PackagingError(f"Build artefact is forbidden in allowlist: {item.source}")
        if item.destination in destinations:
            raise PackagingError(f"Duplicate package destination: {item.destination}")
        destinations.add(item.destination)
        source = (repo_root / item.source).resolve()
        ensure_within(source, repo_root, "Allowlist source")
        require_regular_file(source)


def load_json(path: Path) -> Any:
    require_regular_file(path)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PackagingError(f"Invalid JSON in {path}: {exc}") from exc


def resolve_manifest_path(raw: str, manifest_path: Path, repo_root: Path) -> Path:
    candidate = Path(raw)
    if candidate.is_absolute():
        return candidate.resolve()
    pure = PurePosixPath(raw)
    if pure.parts and pure.parts[0] in REPO_RELATIVE_PREFIXES:
        return (repo_root / candidate).resolve()
    # Basenames, ../ paths and report-local subdirectories are deliberately
    # manifest-relative. Resolution never depends on which shadow path happens
    # to exist first.
    return (manifest_path.parent / candidate).resolve()


def extract_manifest_entries(
    payload: Any, manifest_path: Path, repo_root: Path
) -> dict[Path, str]:
    """Extract and strictly validate path/SHA-256 bindings.

    Supported bindings are ``{"path": ..., "sha256": ...}`` records and
    direct path-to-hash mappings under a known manifest container. Hashes must
    be lowercase 64-character hexadecimal strings; uppercase is deliberately
    not normalized so malformed or non-canonical declarations fail closed.
    """

    found: dict[Path, str] = {}

    def add(raw_path: Any, raw_hash: Any, location: str) -> None:
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise PackagingError(
                f"Manifest binding has a non-string or empty path at {location} "
                f"in {manifest_path}: {raw_path!r}"
            )
        if not isinstance(raw_hash, str):
            raise PackagingError(
                f"Manifest binding has a non-string SHA-256 at {location} "
                f"in {manifest_path}: {raw_hash!r}"
            )
        if not HASH_RE.fullmatch(raw_hash):
            raise PackagingError(
                f"Manifest binding has a malformed lowercase SHA-256 at {location} "
                f"in {manifest_path}: {raw_hash!r}"
            )
        path = resolve_manifest_path(raw_path, manifest_path, repo_root)
        previous = found.get(path)
        if previous is not None and previous != raw_hash:
            raise PackagingError(
                f"Conflicting hashes for {path} in {manifest_path}: "
                f"{previous} vs {raw_hash}"
            )
        found[path] = raw_hash

    def walk(
        value: Any, parent_key: str | None = None, location: str = "$"
    ) -> None:
        if isinstance(value, Mapping):
            declares_record = "path" in value or "sha256" in value
            if declares_record:
                if "path" not in value or "sha256" not in value:
                    raise PackagingError(
                        f"Incomplete path/SHA-256 manifest binding at {location} "
                        f"in {manifest_path}"
                    )
                add(value["path"], value["sha256"], location)

            if parent_key in MANIFEST_BINDING_CONTAINERS and not declares_record:
                nested_values = list(value.values())
                if not nested_values:
                    raise PackagingError(
                        f"Manifest binding container is empty at {location} "
                        f"in {manifest_path}"
                    )
                if all(isinstance(nested, str) for nested in nested_values):
                    for key, nested in value.items():
                        add(key, nested, f"{location}.{key}")
                elif all(
                    isinstance(nested, Mapping)
                    and ("path" in nested or "sha256" in nested)
                    for nested in nested_values
                ):
                    for key, nested in value.items():
                        walk(nested, None, f"{location}.{key}")
                else:
                    raise PackagingError(
                        f"Manifest binding container has a mixed or unsupported "
                        f"shape at {location} in {manifest_path}"
                    )
                return

            for key, nested in value.items():
                walk(nested, str(key), f"{location}.{key}")
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            if parent_key in MANIFEST_BINDING_CONTAINERS:
                if not value:
                    raise PackagingError(
                        f"Manifest binding container is empty at {location} "
                        f"in {manifest_path}"
                    )
                invalid_rows = [
                    index
                    for index, nested in enumerate(value)
                    if not isinstance(nested, Mapping)
                    or not ("path" in nested or "sha256" in nested)
                ]
                if invalid_rows:
                    raise PackagingError(
                        f"Manifest binding list has non-record rows {invalid_rows} "
                        f"at {location} in {manifest_path}"
                    )
            for index, nested in enumerate(value):
                # A list element is a record, not another path->hash mapping.
                # Clearing the container key prevents a record's literal
                # ``sha256`` field name from being interpreted as a file path.
                walk(nested, None, f"{location}[{index}]")

    walk(payload)
    return found


def verify_manifest(manifest_path: Path, repo_root: Path) -> dict[Path, str]:
    payload = load_json(manifest_path)
    entries = extract_manifest_entries(payload, manifest_path, repo_root)
    if not entries:
        raise PackagingError(f"Manifest has no explicit path/SHA-256 bindings: {manifest_path}")
    failures: list[str] = []
    for path, expected in sorted(entries.items(), key=lambda item: str(item[0])):
        if not path.is_file():
            failures.append(f"missing: {path}")
            continue
        actual = sha256_file(path)
        if actual != expected:
            failures.append(f"hash mismatch: {path}; expected {expected}, actual {actual}")
    if failures:
        raise PackagingError(
            f"Manifest verification failed for {manifest_path}:\n  "
            + "\n  ".join(failures)
        )
    return entries


def verify_english_translation_contract(
    repo_root: Path,
    manifest_relative: str = ENGLISH_TRANSLATION_MANIFEST,
    source_relative: str = CANONICAL_NORWEGIAN_V2_SOURCE,
    expected_source_sha256: str = CANONICAL_NORWEGIAN_V2_SOURCE_SHA256,
) -> dict[str, Any]:
    """Fail closed unless the English V2 is bound as a no-science translation."""

    manifest_path = (repo_root / manifest_relative).resolve()
    source_path = (repo_root / source_relative).resolve()
    ensure_within(manifest_path, repo_root, "English translation manifest")
    ensure_within(source_path, repo_root, "Norwegian translation source")
    require_regular_file(manifest_path)
    require_regular_file(source_path)
    if not HASH_RE.fullmatch(expected_source_sha256):
        raise PackagingError(
            "Configured Norwegian V2 source hash is malformed: "
            f"{expected_source_sha256!r}"
        )
    actual_source_sha256 = sha256_file(source_path)
    if actual_source_sha256 != expected_source_sha256:
        raise PackagingError(
            "Canonical Norwegian V2 translation source changed: "
            f"expected {expected_source_sha256}, got {actual_source_sha256}"
        )

    payload = load_json(manifest_path)
    if not isinstance(payload, Mapping):
        raise PackagingError(
            f"English translation manifest must be a JSON object: {manifest_path}"
        )
    if payload.get("language") != "English":
        raise PackagingError(
            "English translation manifest language contract failed: "
            f"{payload.get('language')!r}"
        )
    if payload.get("translation_only_no_scientific_delta") is not True:
        raise PackagingError(
            "English translation manifest must declare "
            "translation_only_no_scientific_delta=true"
        )

    source_binding = payload.get("translation_source_binding")
    if not isinstance(source_binding, Mapping):
        raise PackagingError(
            "English translation manifest lacks translation_source_binding"
        )
    bound_raw_path = source_binding.get("path")
    bound_sha256 = source_binding.get("sha256")
    if not isinstance(bound_raw_path, str):
        raise PackagingError("Translation source binding path must be a string")
    bound_path = resolve_manifest_path(bound_raw_path, manifest_path, repo_root)
    if bound_path != source_path or bound_sha256 != expected_source_sha256:
        raise PackagingError(
            "English translation source binding does not match canonical "
            f"Norwegian V2: path={bound_path}, sha256={bound_sha256!r}"
        )

    verification = payload.get("verification")
    if not isinstance(verification, Mapping):
        raise PackagingError("English translation manifest lacks verification")
    exact_verification = {
        "actionable_latex_warning_count": 0,
        "pdf_strictly_newer_than_tex": True,
    }
    for key, expected in exact_verification.items():
        if verification.get(key) != expected:
            raise PackagingError(
                f"English translation verification failed: {key} expected "
                f"{expected!r}, got {verification.get(key)!r}"
            )
    for key in (
        "language_audit",
        "scientific_numeric_equivalence",
        "visual_inspection",
    ):
        value = verification.get(key)
        if not isinstance(value, str) or not value.startswith("PASS"):
            raise PackagingError(
                f"English translation verification must record PASS for {key}: "
                f"{value!r}"
            )

    entries = extract_manifest_entries(payload, manifest_path, repo_root)
    if entries.get(source_path) != expected_source_sha256:
        raise PackagingError(
            "English translation files list does not bind the canonical "
            "Norwegian V2 source"
        )
    return {
        "manifest": manifest_relative,
        "language": "English",
        "translation_only_no_scientific_delta": True,
        "translation_source": source_relative,
        "translation_source_sha256": expected_source_sha256,
        "language_audit": verification["language_audit"],
        "scientific_numeric_equivalence": verification[
            "scientific_numeric_equivalence"
        ],
    }


def get_nested(payload: Any, keys: Sequence[str], path: Path) -> Any:
    current = payload
    for key in keys:
        if not isinstance(current, Mapping) or key not in current:
            raise PackagingError(f"Missing audit field {'.'.join(keys)} in {path}")
        current = current[key]
    return current


def verify_audit_contracts(
    repo_root: Path,
    contracts: Sequence[tuple[str, tuple[str, ...], Any]] = AUDIT_CONTRACTS,
) -> None:
    cache: dict[Path, Any] = {}
    for relative, keys, expected in contracts:
        path = (repo_root / relative).resolve()
        payload = cache.setdefault(path, load_json(path))
        actual = get_nested(payload, keys, path)
        if actual != expected:
            raise PackagingError(
                f"Audit contract failed: {relative}:{'.'.join(keys)} "
                f"expected {expected!r}, got {actual!r}"
            )


def parse_fls_inputs(fls_path: Path) -> list[Path]:
    lines = fls_path.read_text(encoding="utf-8", errors="replace").splitlines()
    working_directory = fls_path.parent
    for line in lines:
        if line.startswith("PWD "):
            working_directory = Path(line[4:]).resolve()
            break
    inputs: list[Path] = []
    for line in lines:
        if not line.startswith("INPUT "):
            continue
        candidate = Path(line[6:])
        if not candidate.is_absolute():
            candidate = working_directory / candidate
        try:
            candidate = candidate.resolve()
        except OSError:
            continue
        if candidate.is_file() and candidate not in inputs:
            inputs.append(candidate)
    return inputs


def verify_report(spec: ReportSpec, repo_root: Path) -> dict[str, Any]:
    tex = (repo_root / spec.tex).resolve()
    pdf = (repo_root / spec.pdf).resolve()
    readme = (repo_root / spec.readme).resolve()
    manifest = (repo_root / spec.manifest).resolve()
    for path in (tex, pdf, readme, manifest):
        require_regular_file(path)

    if b"\\documentclass" not in tex.read_bytes()[:32768]:
        raise PackagingError(f"Report TeX lacks a document class: {tex}")
    if not pdf.read_bytes()[:5].startswith(b"%PDF-"):
        raise PackagingError(f"Report output is not a PDF: {pdf}")
    if pdf.stat().st_mtime_ns <= tex.stat().st_mtime_ns:
        raise PackagingError(
            f"Report PDF must be strictly newer than its TeX source: {pdf}"
        )

    entries = verify_manifest(manifest, repo_root)
    for required in (tex, pdf):
        if required not in entries:
            raise PackagingError(
                f"Report manifest does not bind required file {required}: {manifest}"
            )
    missing_bindings = [
        relative
        for relative in REPORT_REQUIRED_BINDINGS.get(spec.report_id, ())
        if (repo_root / relative).resolve() not in entries
    ]
    if missing_bindings:
        raise PackagingError(
            f"Report manifest lacks required evidence bindings for {spec.report_id}:\n  "
            + "\n  ".join(missing_bindings)
        )

    log_path = tex.with_suffix(".log")
    fls_path = tex.with_suffix(".fls")
    require_regular_file(log_path)
    require_regular_file(fls_path)
    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    fatal_patterns = (
        "LaTeX Error",
        "undefined references",
        "There were undefined citations",
        "undefined on input line",
        "Rerun to get cross-references right",
        "Label(s) may have changed",
        "Emergency stop",
        "Fatal error occurred",
    )
    present = [pattern for pattern in fatal_patterns if pattern in log_text]
    if present:
        raise PackagingError(f"LaTeX log contains blocking warnings {present}: {log_path}")

    stale: list[str] = []
    for dependency in parse_fls_inputs(fls_path):
        try:
            dependency.relative_to(repo_root)
        except ValueError:
            continue
        if dependency == pdf or dependency.suffix in BUILD_SUFFIXES:
            continue
        if dependency.stat().st_mtime_ns <= pdf.stat().st_mtime_ns:
            continue
        stale.append(str(dependency.relative_to(repo_root)))
    if stale:
        raise PackagingError(
            f"Report {spec.report_id} has project dependencies newer than its PDF:\n  "
            + "\n  ".join(stale)
        )

    return {
        "report_id": spec.report_id,
        "tex": spec.tex,
        "pdf": spec.pdf,
        "manifest": spec.manifest,
        "manifest_entry_count": len(entries),
        "pdf_sha256": sha256_file(pdf),
        "tex_sha256": sha256_file(tex),
        "newer_project_dependencies": [],
    }


def report_dependency_paths(spec: ReportSpec, repo_root: Path) -> tuple[Path, ...]:
    """Return the exact project-local dependency set recorded by a report FLS."""

    tex = (repo_root / spec.tex).resolve()
    fls = tex.with_suffix(".fls")
    require_regular_file(fls)
    dependencies: set[Path] = set()
    for path in parse_fls_inputs(fls):
        try:
            path.relative_to(repo_root)
        except ValueError:
            continue
        dependencies.add(path)
    return tuple(sorted(dependencies, key=str))


def report_tracked_paths(spec: ReportSpec, repo_root: Path) -> tuple[Path, ...]:
    """Return report inputs plus the build log/FLS and their recorded project inputs."""

    tex = (repo_root / spec.tex).resolve()
    explicit = {
        tex,
        (repo_root / spec.pdf).resolve(),
        (repo_root / spec.readme).resolve(),
        (repo_root / spec.manifest).resolve(),
        tex.with_suffix(".log"),
        tex.with_suffix(".fls"),
    }
    explicit.update(report_dependency_paths(spec, repo_root))
    for path in explicit:
        require_regular_file(path)
    return tuple(sorted(explicit, key=str))


def verify_csv_readable(path: Path) -> None:
    require_regular_file(path)
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader)
    except (UnicodeDecodeError, StopIteration, csv.Error) as exc:
        raise PackagingError(f"Unreadable or empty CSV: {path}: {exc}") from exc
    if not header or any(not str(value).strip() for value in header):
        raise PackagingError(f"CSV has an invalid header: {path}")


def validate_hard_inputs(
    repo_root: Path,
    *,
    reports: Sequence[ReportSpec] = REPORTS,
    provenance_manifests: Sequence[str] = PROVENANCE_MANIFESTS,
    audit_contracts: Sequence[
        tuple[str, tuple[str, ...], Any]
    ] = AUDIT_CONTRACTS,
    allowlist: Sequence[Artifact] = COPY_ALLOWLIST,
    parent_release_binding: tuple[str, str, str] | None = PARENT_RELEASE_BINDING,
    enforce_english_translation_contract: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Re-evaluate every content-based release gate from current bytes."""

    validate_allowlist(repo_root, allowlist)
    verify_audit_contracts(repo_root, audit_contracts)
    manifest_results: list[dict[str, Any]] = []
    if parent_release_binding is not None:
        manifest_results.append(
            verify_parent_release_binding(repo_root, parent_release_binding)
        )
    if enforce_english_translation_contract:
        verify_english_translation_contract(repo_root)
    manifest_paths = [report.manifest for report in reports] + list(
        provenance_manifests
    )
    seen_manifests: set[str] = set()
    for relative in manifest_paths:
        if relative in seen_manifests:
            continue
        seen_manifests.add(relative)
        path = (repo_root / relative).resolve()
        entries = verify_manifest(path, repo_root)
        manifest_results.append(
            {
                "path": relative,
                "sha256": sha256_file(path),
                "verified_entry_count": len(entries),
            }
        )
    report_results = [verify_report(report, repo_root) for report in reports]
    for item in allowlist:
        if Path(item.source).suffix.lower() == ".csv":
            verify_csv_readable((repo_root / item.source).resolve())
    return manifest_results, report_results


def run_final_delivery_check(
    repo_root: Path, timeout_seconds: int
) -> tuple[dict[str, Any], dict[str, bytes], str]:
    script = repo_root / "scripts/run_final_delivery_check_v1.py"
    require_regular_file(script)
    with tempfile.TemporaryDirectory(prefix="heiq-v8-1-final-check-") as temporary:
        output_dir = Path(temporary) / "final_delivery_check"
        command = [
            sys.executable,
            "-B",
            str(script),
            "--run-tests",
            "--timeout-seconds",
            str(timeout_seconds),
            "--output-dir",
            str(output_dir),
            "--overwrite",
        ]
        completed = subprocess.run(
            command,
            cwd=repo_root,
            text=True,
            capture_output=True,
            timeout=timeout_seconds + 60,
            check=False,
        )
        if completed.returncode != 0:
            diagnostic = (completed.stdout + "\n" + completed.stderr).strip()
            raise PackagingError(
                "Live final-delivery check failed with return code "
                f"{completed.returncode}:\n{diagnostic[-12000:]}"
            )
        payloads: dict[str, bytes] = {}
        for name in FINAL_CHECK_FILES:
            path = output_dir / name
            require_regular_file(path)
            payloads[name] = path.read_bytes()
        status = json.loads(payloads["status.json"].decode("utf-8"))
        test_run = json.loads(payloads["test_run.json"].decode("utf-8"))

        try:
            gate_reader = csv.DictReader(
                io.StringIO(payloads["gate_register.csv"].decode("utf-8-sig"))
            )
            gate_rows = list(gate_reader)
        except (UnicodeDecodeError, csv.Error) as exc:
            raise PackagingError(f"Invalid live gate register: {exc}") from exc

    if not isinstance(status, Mapping):
        raise PackagingError("Live final-delivery status is not a JSON object")

    required_true = (
        "model_phase_delivery_ready",
        "scientific_gates_pass",
        "manifest_integrity_pass",
        "report_artifacts_pass",
    )
    failures = [key for key in required_true if status.get(key) is not True]
    if status.get("blocking_items") != []:
        failures.append(f"blocking_items={status.get('blocking_items')!r}")
    optional = status.get("optional_checks_pass", {})
    if (
        not isinstance(optional, Mapping)
        or not optional
        or not all(value is True for value in optional.values())
    ):
        failures.append(f"optional_checks_pass={optional!r}")

    if not isinstance(test_run, Mapping):
        failures.append("test_run is not a JSON object")
    else:
        if test_run.get("passed") is not True:
            failures.append(f"live test run did not pass: {test_run!r}")
        if test_run.get("mode") != "live_pytest":
            failures.append(f"test mode is not live_pytest: {test_run.get('mode')!r}")
        if test_run.get("return_code") != 0:
            failures.append(
                f"live test return code is not zero: {test_run.get('return_code')!r}"
            )
        passed_count = test_run.get("passed_count")
        if not isinstance(passed_count, int) or passed_count <= 0:
            failures.append(f"live test passed_count is invalid: {passed_count!r}")
        status_test_run = status.get("test_verification")
        if not isinstance(status_test_run, Mapping):
            failures.append("status.test_verification is not a JSON object")
        elif dict(status_test_run) != dict(test_run):
            failures.append("status.test_verification differs from test_run.json")

    required_gate_rows: list[Mapping[str, str]] = []
    invalid_required_values: list[str] = []
    for row in gate_rows:
        raw_required = str(row.get("required_today", "")).strip().lower()
        if raw_required in {"true", "1", "yes", "y"}:
            required_gate_rows.append(row)
        elif raw_required not in {"false", "0", "no", "n"}:
            invalid_required_values.append(
                f"{row.get('gate_id', '<missing>')}={raw_required!r}"
            )
    if invalid_required_values:
        failures.append(
            "invalid required_today values in live gate register: "
            + ", ".join(invalid_required_values)
        )
    if not required_gate_rows:
        failures.append("live gate register has no required-today gates")
    failed_required_gates = [
        str(row.get("gate_id", "<missing>"))
        for row in required_gate_rows
        if str(row.get("status", "")).strip().upper() != "PASS"
    ]
    if failed_required_gates:
        failures.append(
            "required-today gates are not PASS: " + ", ".join(failed_required_gates)
        )

    git_snapshot = status.get("git_snapshot")
    if not isinstance(git_snapshot, Mapping):
        failures.append("live final-delivery status lacks a Git-state advisory")
    elif not isinstance(git_snapshot.get("worktree_clean"), bool):
        failures.append("live Git-state advisory lacks worktree_clean boolean")
    if failures:
        raise PackagingError(
            "Final-delivery status does not satisfy release requirements: "
            + "; ".join(failures)
        )
    return status, payloads, " ".join(command)


def git_revision(repo_root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise PackagingError(f"Cannot resolve Git revision: {completed.stderr.strip()}")
    revision = completed.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40,64}", revision):
        raise PackagingError(f"Unexpected Git revision value: {revision!r}")
    return revision


def snapshot_file(path: Path) -> dict[str, Any]:
    """Hash one regular file through a no-follow descriptor with race checks."""

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise PackagingError(f"Cannot open snapshot input {path}: {exc}") from exc
    with os.fdopen(descriptor, "rb") as handle:
        before = os.fstat(handle.fileno())
        if not stat_module.S_ISREG(before.st_mode) or before.st_size <= 0:
            raise PackagingError(f"Snapshot input is not a non-empty regular file: {path}")
        digest = hashlib.sha256()
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
        after = os.fstat(handle.fileno())
    identity_before = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    identity_after = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    if identity_before != identity_after:
        raise PackagingError(f"Input changed while it was being snapshotted: {path}")
    return {
        "sha256": digest.hexdigest(),
        "size_bytes": before.st_size,
        "mtime_ns": before.st_mtime_ns,
        "ctime_ns": before.st_ctime_ns,
        "device": before.st_dev,
        "inode": before.st_ino,
        "mode": stat_module.S_IMODE(before.st_mode),
        "mtime_utc": datetime.fromtimestamp(before.st_mtime, timezone.utc).isoformat(),
    }


def verify_file_unchanged(
    path: Path, expected: Mapping[str, Any], context: str
) -> None:
    current = snapshot_file(path)
    compared_fields = (
        "sha256",
        "size_bytes",
        "mtime_ns",
        "ctime_ns",
        "device",
        "inode",
        "mode",
    )
    if any(current.get(field) != expected.get(field) for field in compared_fields):
        raise PackagingError(f"Input changed {context}: {path}")


def copy_verified_snapshot(
    source: Path,
    destination: Path,
    expected: Mapping[str, Any],
) -> None:
    """Stream exactly the snapshotted source inode once into a new staged file."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        raise PackagingError(f"Staged copy destination already exists: {destination}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(source, flags)
    except OSError as exc:
        raise PackagingError(f"Cannot open source for staged copy {source}: {exc}") from exc
    digest = hashlib.sha256()
    try:
        with os.fdopen(descriptor, "rb") as input_handle:
            before = os.fstat(input_handle.fileno())
            identity = {
                "size_bytes": before.st_size,
                "mtime_ns": before.st_mtime_ns,
                "ctime_ns": before.st_ctime_ns,
                "device": before.st_dev,
                "inode": before.st_ino,
                "mode": stat_module.S_IMODE(before.st_mode),
            }
            if not stat_module.S_ISREG(before.st_mode) or any(
                identity[field] != expected.get(field) for field in identity
            ):
                raise PackagingError(f"Source changed before staged copy: {source}")
            with destination.open("xb") as output_handle:
                for chunk in iter(lambda: input_handle.read(1024 * 1024), b""):
                    digest.update(chunk)
                    output_handle.write(chunk)
                output_handle.flush()
                os.fsync(output_handle.fileno())
            after = os.fstat(input_handle.fileno())
            after_identity = {
                "size_bytes": after.st_size,
                "mtime_ns": after.st_mtime_ns,
                "ctime_ns": after.st_ctime_ns,
                "device": after.st_dev,
                "inode": after.st_ino,
                "mode": stat_module.S_IMODE(after.st_mode),
            }
            if after_identity != identity:
                raise PackagingError(f"Source changed during staged copy: {source}")
    except Exception:
        if destination.exists():
            destination.unlink()
        raise
    if digest.hexdigest() != expected.get("sha256"):
        destination.unlink()
        raise PackagingError(f"Source content changed during staged copy: {source}")
    os.chmod(destination, int(expected["mode"]))
    os.utime(
        destination,
        ns=(int(expected["mtime_ns"]), int(expected["mtime_ns"])),
    )
    staged = snapshot_file(destination)
    if (
        staged["sha256"] != expected.get("sha256")
        or staged["size_bytes"] != expected.get("size_bytes")
        or staged["mtime_ns"] != expected.get("mtime_ns")
        or staged["mode"] != expected.get("mode")
    ):
        raise PackagingError(f"Staged copy does not match snapshot: {destination}")


def snapshot_allowlist(
    repo_root: Path, items: Sequence[Artifact] = COPY_ALLOWLIST
) -> dict[str, dict[str, Any]]:
    snapshots: dict[str, dict[str, Any]] = {}
    for item in items:
        path = (repo_root / item.source).resolve()
        snapshots[item.source] = snapshot_file(path)
    return snapshots


def snapshot_scaffold(
    release_dir: Path = RELEASE_DIR,
) -> dict[str, dict[str, Any]]:
    return {name: snapshot_file(release_dir / name) for name in SCAFFOLD_FILES}


def snapshot_report_states(repo_root: Path) -> dict[str, dict[str, Any]]:
    states: dict[str, dict[str, Any]] = {}
    for spec in REPORTS:
        dependencies = report_dependency_paths(spec, repo_root)
        tracked = report_tracked_paths(spec, repo_root)
        states[spec.report_id] = {
            "dependency_paths": [str(path) for path in dependencies],
            "tracked_paths": {
                str(path): snapshot_file(path) for path in tracked
            },
        }
    return states


def verify_allowlist_unchanged(
    repo_root: Path,
    snapshots: Mapping[str, Mapping[str, Any]],
    context: str,
    items: Sequence[Artifact] = COPY_ALLOWLIST,
) -> None:
    for item in items:
        source = (repo_root / item.source).resolve()
        verify_file_unchanged(source, snapshots[item.source], context)


def verify_scaffold_unchanged(
    snapshots: Mapping[str, Mapping[str, Any]],
    context: str,
    release_dir: Path = RELEASE_DIR,
) -> None:
    for name in SCAFFOLD_FILES:
        verify_file_unchanged(release_dir / name, snapshots[name], context)


def verify_report_states_unchanged(
    repo_root: Path,
    states: Mapping[str, Mapping[str, Any]],
    context: str,
) -> list[dict[str, Any]]:
    """Re-run report validation and enforce the original FLS/log dependency set."""

    results: list[dict[str, Any]] = []
    for spec in REPORTS:
        expected = states.get(spec.report_id)
        if not isinstance(expected, Mapping):
            raise PackagingError(f"Missing report snapshot for {spec.report_id}")
        current_dependencies = [
            str(path) for path in report_dependency_paths(spec, repo_root)
        ]
        if current_dependencies != expected.get("dependency_paths"):
            raise PackagingError(
                f"Report FLS dependency set changed {context}: {spec.report_id}"
            )
        current_paths = {str(path) for path in report_tracked_paths(spec, repo_root)}
        tracked = expected.get("tracked_paths")
        if not isinstance(tracked, Mapping) or current_paths != set(tracked):
            raise PackagingError(
                f"Report tracked path set changed {context}: {spec.report_id}"
            )
        for raw_path, file_snapshot in tracked.items():
            if not isinstance(raw_path, str) or not isinstance(file_snapshot, Mapping):
                raise PackagingError(
                    f"Invalid report snapshot entry for {spec.report_id}: {raw_path!r}"
                )
            verify_file_unchanged(Path(raw_path), file_snapshot, context)
        results.append(verify_report(spec, repo_root))
    return results


def preflight(
    repo_root: Path, timeout_seconds: int
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any],
    dict[str, bytes],
    str,
    str,
]:
    repo_root = repo_root.resolve()
    if not (repo_root / "pyproject.toml").is_file():
        raise PackagingError(f"Not an XMembrane repository root: {repo_root}")
    ensure_within(RELEASE_DIR, repo_root, "Release directory")
    for name in SCAFFOLD_FILES:
        require_regular_file(RELEASE_DIR / name)

    # Establish the immutable baseline before any content-based audit,
    # manifest, CSV or report decision. Validation can therefore never bless a
    # mutation as a new post-validation baseline.
    validate_allowlist(repo_root)
    snapshots = snapshot_allowlist(repo_root)
    scaffold_snapshots = snapshot_scaffold()
    report_states = snapshot_report_states(repo_root)
    verify_allowlist_unchanged(repo_root, snapshots, "while baseline was captured")
    verify_scaffold_unchanged(
        scaffold_snapshots, "while baseline was captured"
    )
    verify_report_states_unchanged(
        repo_root, report_states, "while baseline was captured"
    )
    manifest_results, report_results = validate_hard_inputs(repo_root)
    verify_allowlist_unchanged(repo_root, snapshots, "during hard validation")
    verify_scaffold_unchanged(scaffold_snapshots, "during hard validation")
    verify_report_states_unchanged(
        repo_root, report_states, "during hard validation"
    )

    status, verification_payloads, checker_command = run_final_delivery_check(
        repo_root, timeout_seconds
    )
    # Recompute, rather than reuse, every hard result after the long live check.
    manifest_results, report_results = validate_hard_inputs(repo_root)
    verify_allowlist_unchanged(repo_root, snapshots, "during final preflight")
    verify_scaffold_unchanged(scaffold_snapshots, "during final preflight")
    report_results = verify_report_states_unchanged(
        repo_root, report_states, "during final preflight"
    )
    revision = git_revision(repo_root)
    checker_revision = status.get("git_snapshot", {}).get("revision")
    if checker_revision != revision:
        raise PackagingError(
            "Git revision changed during final preflight: "
            f"checker recorded {checker_revision!r}, current revision is {revision!r}"
        )
    return (
        snapshots,
        scaffold_snapshots,
        report_states,
        manifest_results,
        report_results,
        status,
        verification_payloads,
        checker_command,
        revision,
    )


def deterministic_zip(
    output_path: Path, members: Iterable[tuple[Path, str]]
) -> None:
    timestamp = (2026, 8, 31, 0, 0, 0)
    with zipfile.ZipFile(
        output_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for disk_path, archive_name in sorted(members, key=lambda item: item[1]):
            require_regular_file(disk_path)
            name = PurePosixPath(archive_name)
            if name.is_absolute() or ".." in name.parts:
                raise PackagingError(f"Invalid ZIP member path: {archive_name}")
            info = zipfile.ZipInfo(str(name), date_time=timestamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, disk_path.read_bytes())


def inventory_record(
    source_path: Path,
    source_label: str,
    destination: str,
    role: str,
    category: str,
) -> dict[str, Any]:
    stat = source_path.stat()
    return {
        "source": source_label,
        "destination": destination,
        "role": role,
        "category": category,
        "size_bytes": stat.st_size,
        "source_mtime_utc": datetime.fromtimestamp(
            stat.st_mtime, timezone.utc
        ).isoformat(),
        "sha256": sha256_file(source_path),
    }


def parse_sha256sums(path: Path) -> dict[str, str]:
    """Read a canonical SHA256SUMS file and reject malformed/duplicate paths."""

    require_regular_file(path)
    entries: dict[str, str] = {}
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if match is None:
            raise PackagingError(
                f"Malformed SHA256SUMS line {line_number} in {path}: {line!r}"
            )
        digest, relative = match.groups()
        pure = PurePosixPath(relative)
        if (
            pure.is_absolute()
            or ".." in pure.parts
            or not pure.parts
            or "\\" in relative
        ):
            raise PackagingError(
                f"Unsafe SHA256SUMS path on line {line_number} in {path}: "
                f"{relative!r}"
            )
        normalized = pure.as_posix()
        if normalized in entries:
            raise PackagingError(f"Duplicate SHA256SUMS path in {path}: {normalized}")
        entries[normalized] = digest
    if not entries:
        raise PackagingError(f"SHA256SUMS has no entries: {path}")
    return entries


def is_generated_package_path(relative: str) -> bool:
    parts = PurePosixPath(relative).parts
    return bool(parts and parts[0] in GENERATED_TARGETS)


def collect_generated_tree(base: Path) -> tuple[set[str], set[str]]:
    """Collect files/directories under only the known generated top-level targets."""

    files: set[str] = set()
    directories: set[str] = set()
    for name in GENERATED_TARGETS:
        target = base / name
        if not target.exists() and not target.is_symlink():
            continue
        if target.is_symlink():
            raise PackagingError(f"Generated release target may not be a symlink: {target}")
        if name in GENERATED_DIRECTORY_TARGETS:
            if not target.is_dir():
                raise PackagingError(f"Expected generated directory, found other type: {target}")
            directories.add(name)
            for child in target.rglob("*"):
                relative = child.relative_to(base).as_posix()
                if child.is_symlink():
                    raise PackagingError(
                        f"Generated release content may not be a symlink: {child}"
                    )
                if child.is_dir():
                    directories.add(relative)
                elif child.is_file():
                    files.add(relative)
                else:
                    raise PackagingError(f"Unsupported generated file type: {child}")
        elif name in GENERATED_FILE_TARGETS:
            if not target.is_file():
                raise PackagingError(f"Expected generated file, found other type: {target}")
            files.add(name)
        else:  # Defensive if GENERATED_TARGETS is extended without a type contract.
            raise PackagingError(f"No generated-target type contract for {name}")
    return files, directories


def expected_directories_for_files(files: Iterable[str]) -> set[str]:
    expected: set[str] = set()
    for relative in files:
        pure = PurePosixPath(relative)
        if not pure.parts or pure.parts[0] not in GENERATED_DIRECTORY_TARGETS:
            continue
        for index in range(1, len(pure.parts)):
            expected.add(PurePosixPath(*pure.parts[:index]).as_posix())
    return expected


def verify_existing_generated_release(
    base: Path, *, verify_scaffold: bool
) -> dict[str, Any]:
    """Verify an existing generated set before it may be replaced or accepted."""

    manifest_path = base / "MANIFEST.json"
    sums_path = base / "SHA256SUMS"
    require_regular_file(manifest_path)
    require_regular_file(sums_path)
    checksums = parse_sha256sums(sums_path)

    invalid_checksum_paths = sorted(
        relative
        for relative in checksums
        if not is_generated_package_path(relative) and relative not in SCAFFOLD_FILES
    )
    if invalid_checksum_paths:
        raise PackagingError(
            "SHA256SUMS declares paths outside the controlled release set:\n  "
            + "\n  ".join(invalid_checksum_paths)
        )
    if "SHA256SUMS" in checksums:
        raise PackagingError("SHA256SUMS must not contain a self-hash")
    for required in ("MANIFEST.json", *SCAFFOLD_FILES):
        if required not in checksums:
            raise PackagingError(f"SHA256SUMS lacks required entry: {required}")

    actual_files, actual_directories = collect_generated_tree(base)
    expected_generated_files = {
        relative for relative in checksums if is_generated_package_path(relative)
    } | {"SHA256SUMS"}
    if actual_files != expected_generated_files:
        unknown = sorted(actual_files - expected_generated_files)
        missing = sorted(expected_generated_files - actual_files)
        raise PackagingError(
            "Existing generated release set differs from SHA256SUMS; "
            f"unknown={unknown!r}; missing={missing!r}"
        )
    expected_directories = expected_directories_for_files(expected_generated_files)
    if actual_directories != expected_directories:
        unknown = sorted(actual_directories - expected_directories)
        missing = sorted(expected_directories - actual_directories)
        raise PackagingError(
            "Existing generated directory set differs from SHA256SUMS; "
            f"unknown={unknown!r}; missing={missing!r}"
        )

    paths_to_hash = {
        relative: digest
        for relative, digest in checksums.items()
        if is_generated_package_path(relative)
        or (verify_scaffold and relative in SCAFFOLD_FILES)
    }
    for relative, expected_hash in sorted(paths_to_hash.items()):
        path = base / relative
        require_regular_file(path)
        actual_hash = sha256_file(path)
        if actual_hash != expected_hash:
            raise PackagingError(
                f"Existing release checksum mismatch: {path}; "
                f"expected {expected_hash}, actual {actual_hash}"
            )

    manifest = load_json(manifest_path)
    if not isinstance(manifest, Mapping) or manifest.get("release_id") != RELEASE_ID:
        raise PackagingError(
            f"Existing MANIFEST.json does not identify {RELEASE_ID}: {manifest_path}"
        )
    inventory = manifest.get("inventory")
    if not isinstance(inventory, Sequence) or isinstance(inventory, (str, bytes)):
        raise PackagingError(f"Existing MANIFEST.json has no inventory list: {manifest_path}")
    inventory_destinations: set[str] = set()
    for index, row in enumerate(inventory):
        if not isinstance(row, Mapping) or not isinstance(row.get("destination"), str):
            raise PackagingError(
                f"Invalid inventory row {index} in existing MANIFEST.json"
            )
        relative = PurePosixPath(row["destination"])
        if relative.is_absolute() or ".." in relative.parts:
            raise PackagingError(
                f"Unsafe inventory destination in existing MANIFEST.json: {relative}"
            )
        normalized = relative.as_posix()
        if normalized in inventory_destinations:
            raise PackagingError(
                f"Duplicate inventory destination in existing MANIFEST.json: {normalized}"
            )
        inventory_destinations.add(normalized)
    inventory_generated = {
        relative for relative in inventory_destinations if is_generated_package_path(relative)
    }
    expected_inventory = actual_files - {"MANIFEST.json", "SHA256SUMS"}
    if inventory_generated != expected_inventory:
        raise PackagingError(
            "Existing MANIFEST inventory differs from generated file set; "
            f"unknown={sorted(inventory_generated - expected_inventory)!r}; "
            f"missing={sorted(expected_inventory - inventory_generated)!r}"
        )
    return {
        "file_count": len(actual_files),
        "directory_count": len(actual_directories),
        "manifest_sha256": sha256_file(manifest_path),
        "sha256sums_sha256": sha256_file(sums_path),
    }


def existing_generated_targets(base: Path) -> list[str]:
    return [
        name
        for name in GENERATED_TARGETS
        if (base / name).exists() or (base / name).is_symlink()
    ]


def promote_staged_release(
    stage: Path,
    release_dir: Path,
    *,
    overwrite: bool,
    fail_after_promotions: int | None = None,
) -> None:
    """Promote a verified stage with backup and rollback of known targets only."""

    stale_backups = sorted(release_dir.glob(".v8-1-package-backup-*"))
    if stale_backups:
        raise PackagingError(
            "A prior recovery backup exists; inspect/recover it before publishing:\n  "
            + "\n  ".join(str(path) for path in stale_backups)
        )
    verify_existing_generated_release(stage, verify_scaffold=True)
    existing = existing_generated_targets(release_dir)
    if existing and not overwrite:
        raise PackagingError(
            "Generated release targets already exist; review them and use --overwrite "
            "only for an intentional rebuild:\n  "
            + "\n  ".join(str(release_dir / name) for name in existing)
        )
    if existing:
        verify_existing_generated_release(release_dir, verify_scaffold=False)

    backup = Path(tempfile.mkdtemp(prefix=".v8-1-package-backup-", dir=release_dir))
    moved_old: list[str] = []
    promoted: list[str] = []
    try:
        backup_order = [
            name
            for name in ("SHA256SUMS", "MANIFEST.json", *GENERATED_TARGETS)
            if name in existing
        ]
        # Preserve order while removing MANIFEST/SHA duplicates from the tail.
        backup_order = list(dict.fromkeys(backup_order))
        for name in backup_order:
            os.replace(release_dir / name, backup / name)
            moved_old.append(name)
        if moved_old:
            verify_existing_generated_release(backup, verify_scaffold=False)

        for name in GENERATED_TARGETS:
            source = stage / name
            if not source.exists() and not source.is_symlink():
                raise PackagingError(f"Staged release lacks generated target: {source}")
            destination = release_dir / name
            if destination.exists() or destination.is_symlink():
                raise PackagingError(
                    f"Concurrent file appeared at release destination: {destination}"
                )
            os.replace(source, destination)
            promoted.append(name)
            if (
                fail_after_promotions is not None
                and len(promoted) >= fail_after_promotions
            ):
                raise PackagingError("Injected promotion failure for self-test")

        verify_existing_generated_release(release_dir, verify_scaffold=True)
    except Exception as exc:
        rollback_errors: list[str] = []
        rollback_new = stage / ".rollback-new"
        rollback_new.mkdir(exist_ok=True)
        for name in reversed(promoted):
            current = release_dir / name
            try:
                if current.exists() or current.is_symlink():
                    os.replace(current, rollback_new / name)
            except OSError as rollback_exc:
                rollback_errors.append(f"remove new {name}: {rollback_exc}")
        restore_order = [
            name
            for name in moved_old
            if name not in {"MANIFEST.json", "SHA256SUMS"}
        ]
        if "MANIFEST.json" in moved_old:
            restore_order.append("MANIFEST.json")
        if "SHA256SUMS" in moved_old:
            restore_order.append("SHA256SUMS")
        for name in restore_order:
            saved = backup / name
            destination = release_dir / name
            try:
                if destination.exists() or destination.is_symlink():
                    rollback_errors.append(
                        f"restore old {name}: destination unexpectedly exists"
                    )
                elif saved.exists() or saved.is_symlink():
                    os.replace(saved, destination)
            except OSError as rollback_exc:
                rollback_errors.append(f"restore old {name}: {rollback_exc}")
        if rollback_errors:
            raise PackagingError(
                f"Release promotion failed ({exc}); rollback is incomplete. "
                f"Recovery backup retained at {backup}: {rollback_errors}"
            ) from exc
        shutil.rmtree(backup)
        raise
    else:
        shutil.rmtree(backup)


def build_package(
    repo_root: Path,
    snapshots: dict[str, dict[str, Any]],
    scaffold_snapshots: dict[str, dict[str, Any]],
    report_states: dict[str, dict[str, Any]],
    manifest_results: list[dict[str, Any]],
    report_results: list[dict[str, Any]],
    final_status: dict[str, Any],
    verification_payloads: dict[str, bytes],
    checker_command: str,
    revision: str,
    overwrite: bool,
) -> None:
    existing = existing_generated_targets(RELEASE_DIR)
    if existing and not overwrite:
        raise PackagingError(
            "Generated release targets already exist; review them and use --overwrite "
            "only for an intentional rebuild:\n  "
            + "\n  ".join(str(RELEASE_DIR / name) for name in existing)
        )
    if existing:
        verify_existing_generated_release(RELEASE_DIR, verify_scaffold=False)

    with tempfile.TemporaryDirectory(prefix=".v8-1-package-stage-", dir=RELEASE_DIR) as temporary:
        stage = Path(temporary)
        inventory: list[dict[str, Any]] = []
        source_zip_members: list[tuple[Path, str]] = []
        result_zip_members: list[tuple[Path, str]] = []

        # Freeze one verified scaffold copy in the stage. Every downstream ZIP,
        # inventory row and checksum uses these staged bytes, never a second
        # read of a potentially changing authored original.
        for name in SCAFFOLD_FILES:
            source = RELEASE_DIR / name
            verify_file_unchanged(
                source, scaffold_snapshots[name], "after final preflight"
            )
            destination = stage / name
            copy_verified_snapshot(source, destination, scaffold_snapshots[name])
            inventory.append(
                inventory_record(
                    destination,
                    name,
                    name,
                    "source",
                    "release_scaffold",
                )
            )
            source_zip_members.append((destination, name))
            if name in {"README.md", "RELEASE_NOTES.md"}:
                result_zip_members.append((destination, name))

        for item in COPY_ALLOWLIST:
            source = (repo_root / item.source).resolve()
            before = snapshots[item.source]
            verify_file_unchanged(source, before, "after final preflight")
            destination = stage / item.destination
            ensure_within(destination, stage, "Package destination")
            copy_verified_snapshot(source, destination, before)
            inventory.append(
                inventory_record(
                    destination,
                    item.source,
                    item.destination,
                    item.role,
                    item.category,
                )
            )
            if item.role == "source":
                source_zip_members.append((destination, item.destination))
            if item.role == "result" or item.category in {
                "canonical_report",
                "supporting_report",
            }:
                result_zip_members.append((destination, item.destination))

        verification_dir = stage / "verification/final_delivery_check"
        verification_dir.mkdir(parents=True, exist_ok=True)
        for name, payload in sorted(verification_payloads.items()):
            destination = verification_dir / name
            destination.write_bytes(payload)
            relative = destination.relative_to(stage).as_posix()
            inventory.append(
                inventory_record(
                    destination,
                    "live final-delivery check",
                    relative,
                    "result",
                    "verification",
                )
            )
            result_zip_members.append((destination, relative))

        archives_dir = stage / "archives"
        archives_dir.mkdir(parents=True, exist_ok=True)
        source_zip = archives_dir / SOURCE_ARCHIVE_NAME
        results_zip = archives_dir / RESULTS_ARCHIVE_NAME
        deterministic_zip(source_zip, source_zip_members)
        deterministic_zip(results_zip, result_zip_members)

        for archive in (source_zip, results_zip):
            inventory.append(
                inventory_record(
                    archive,
                    "generated by package_release.py",
                    archive.relative_to(stage).as_posix(),
                    "archive",
                    "release_archive",
                )
            )

        # Refresh every content-based result from the snapshotted originals
        # immediately before writing those results into MANIFEST.json.
        manifest_results, report_results = validate_hard_inputs(repo_root)
        verify_allowlist_unchanged(
            repo_root, snapshots, "before package manifest generation"
        )
        verify_scaffold_unchanged(
            scaffold_snapshots, "before package manifest generation"
        )
        verify_report_states_unchanged(
            repo_root, report_states, "before package manifest generation"
        )

        translation_verification = verify_english_translation_contract(repo_root)
        package_manifest = {
            "schema_version": SCHEMA_VERSION,
            "release_id": RELEASE_ID,
            "release_scope": RELEASE_SCOPE,
            "release_class": "hash_frozen_controlled_deliverable",
            "immutable_repository_archival_release": False,
            "script_version": SCRIPT_VERSION,
            "generated_utc": utc_now(),
            "git_revision": revision,
            "parent_release": {
                "release_id": PARENT_RELEASE_ID,
                "manifest_path": PARENT_RELEASE_MANIFEST,
                "manifest_sha256": PARENT_RELEASE_MANIFEST_SHA256,
                "relationship": "additive_English_reporting_derivative",
                "parent_mutated": False,
            },
            "scientific_delta_from_parent": False,
            "canonical_reports": [REPORTS[0].pdf, REPORTS[1].pdf],
            "supporting_report": REPORTS[2].pdf,
            "report_language_policy": {
                "packaged_report_language": "English",
                "all_packaged_reports_are_English": True,
                "Norwegian_parent_report_retained_unchanged": True,
            },
            "english_translation_verification": translation_verification,
            "claim_boundary": {
                "model_and_experiment_design_release": True,
                "conditional_energy_windows_are_net_savings": False,
                "candidate_ranking_ready": False,
                "full_system_claim_allowed": False,
                "technology_validated": False,
                "stress_scenarios_are_calibrated_probabilities": False,
            },
            "live_final_delivery": {
                "command": checker_command,
                "generated_utc": final_status.get("generated_utc"),
                "model_phase_delivery_ready": final_status.get(
                    "model_phase_delivery_ready"
                ),
                "release_snapshot_ready": final_status.get(
                    "release_snapshot_ready"
                ),
                "ready_to_archive_today": final_status.get(
                    "ready_to_archive_today"
                ),
                "blocking_items": final_status.get("blocking_items"),
                "full_live_tests_pass": final_status.get(
                    "test_verification", {}
                ).get("passed"),
                "test_mode": final_status.get("test_verification", {}).get(
                    "mode"
                ),
                "live_test_passed_count": final_status.get(
                    "test_verification", {}
                ).get("passed_count"),
            },
            "repository_state_advisory": {
                "release_snapshot_ready": final_status.get(
                    "release_snapshot_ready"
                ),
                "ready_to_archive_today": final_status.get(
                    "ready_to_archive_today"
                ),
                "git_worktree_clean": final_status.get("git_snapshot", {}).get(
                    "worktree_clean"
                ),
                "dirty_git_state": final_status.get("git_snapshot", {}).get(
                    "worktree_clean"
                )
                is False,
                "git_porcelain_line_count": final_status.get(
                    "git_snapshot", {}
                ).get("porcelain_line_count"),
                "blocking_for_controlled_deliverable": False,
                "interpretation": (
                    "Git cleanliness is advisory. Integrity is provided by the "
                    "explicit allowlist, verified provenance, repeated input "
                    "hashing, deterministic archives and SHA256SUMS."
                ),
            },
            "verified_manifests": manifest_results,
            "verified_reports": report_results,
            "inventory": sorted(inventory, key=lambda row: row["destination"]),
            "excluded_by_design": [
                "historical reports through Result Atlas V7",
                "the Norwegian EO vapour-cell report retained in parent V8",
                "weekly and workshop reports retained as non-canonical chronology",
                "LaTeX build artefacts",
                "Python and test caches",
                "temporary files",
                "unselected dense simulation registers",
                "Git metadata",
            ],
        }
        manifest_path = stage / "MANIFEST.json"
        manifest_path.write_text(
            json.dumps(package_manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        checksum_inputs: list[tuple[Path, str]] = []
        for path in stage.rglob("*"):
            if path.is_file() and path.name != "SHA256SUMS":
                checksum_inputs.append((path, path.relative_to(stage).as_posix()))
        checksum_lines = [
            f"{sha256_file(path)}  {relative}"
            for path, relative in sorted(checksum_inputs, key=lambda item: item[1])
        ]
        (stage / "SHA256SUMS").write_text(
            "\n".join(checksum_lines) + "\n", encoding="utf-8"
        )

        # Final TOCTOU barrier: validate the same FLS/log/dependency set and all
        # original source/scaffold bytes immediately before transactional
        # promotion. No report freshness exception is granted for equal bytes.
        verify_allowlist_unchanged(repo_root, snapshots, "before release publish")
        verify_scaffold_unchanged(scaffold_snapshots, "before release publish")
        verify_report_states_unchanged(
            repo_root, report_states, "before release publish"
        )
        final_manifest_results, final_report_results = validate_hard_inputs(repo_root)
        if final_manifest_results != manifest_results:
            raise PackagingError(
                "Verified manifest results changed after MANIFEST.json was staged"
            )
        if final_report_results != report_results:
            raise PackagingError(
                "Verified report results changed after MANIFEST.json was staged"
            )
        verify_allowlist_unchanged(
            repo_root, snapshots, "after final hard-gate validation"
        )
        verify_scaffold_unchanged(
            scaffold_snapshots, "after final hard-gate validation"
        )
        verify_report_states_unchanged(
            repo_root, report_states, "after final hard-gate validation"
        )
        if git_revision(repo_root) != revision:
            raise PackagingError("Git revision changed while package was being built")

        promote_staged_release(stage, RELEASE_DIR, overwrite=overwrite)


def expect_packaging_error(action: Any, label: str) -> None:
    try:
        action()
    except PackagingError:
        return
    raise AssertionError(f"Expected PackagingError for self-test: {label}")


def write_release_fixture(base: Path, marker: str) -> None:
    """Create a minimal internally consistent generated release for self-tests."""

    base.mkdir(parents=True, exist_ok=True)
    inventory: list[dict[str, str]] = []
    for name in SCAFFOLD_FILES:
        (base / name).write_text(f"{marker}:{name}\n", encoding="utf-8")
        inventory.append({"destination": name})
    for directory in sorted(GENERATED_DIRECTORY_TARGETS):
        payload = base / directory / "payload.txt"
        payload.parent.mkdir(parents=True, exist_ok=True)
        payload.write_text(f"{marker}:{directory}\n", encoding="utf-8")
        inventory.append({"destination": payload.relative_to(base).as_posix()})
    manifest = {
        "release_id": RELEASE_ID,
        "inventory": inventory,
    }
    (base / "MANIFEST.json").write_text(
        json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8"
    )
    checksum_paths = [
        path
        for path in base.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS"
    ]
    lines = [
        f"{sha256_file(path)}  {path.relative_to(base).as_posix()}"
        for path in sorted(checksum_paths, key=lambda value: value.relative_to(base).as_posix())
    ]
    (base / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_self_tests() -> None:
    """Exercise fail-closed parser, TOCTOU, freshness and rollback contracts."""

    with tempfile.TemporaryDirectory(prefix="heiq-v8-1-packager-selftest-") as raw:
        temporary = Path(raw)

        # Strict manifest syntax: valid supported shapes pass; every declared
        # malformed path/hash record or path->hash entry must raise.
        manifest_dir = temporary / "manifest"
        manifest_dir.mkdir()
        target = manifest_dir / "target.bin"
        target.write_bytes(b"manifest-target")
        digest = sha256_file(target)
        manifest_path = manifest_dir / "manifest.json"
        good_payloads = (
            {"files": {"target.bin": digest}},
            {"files": [{"path": "target.bin", "sha256": digest}]},
            {"files": {"target": {"path": "target.bin", "sha256": digest}}},
        )
        for payload in good_payloads:
            entries = extract_manifest_entries(payload, manifest_path, manifest_dir)
            if entries != {target.resolve(): digest}:
                raise AssertionError(f"Valid manifest shape parsed incorrectly: {payload!r}")
        bad_payloads = (
            {"files": {"target.bin": "0" * 63}},
            {"files": {"target.bin": 123}},
            {"files": [{"path": "target.bin", "sha256": "A" * 64}]},
            {"files": [{"path": "target.bin", "sha256": None}]},
            {"files": [{"path": 1, "sha256": digest}]},
            {"files": [{"path": "target.bin"}]},
            {"files": [{"sha256": digest}]},
            {
                "files": [
                    {"foo": "silently ignored without container validation"},
                    {"path": "target.bin", "sha256": digest},
                ]
            },
            {"generated_outputs": []},
            {
                "files": {
                    "valid": {"path": "target.bin", "sha256": digest},
                    "mixed": digest,
                }
            },
        )
        for index, payload in enumerate(bad_payloads):
            expect_packaging_error(
                lambda payload=payload: extract_manifest_entries(
                    payload, manifest_path, manifest_dir
                ),
                f"malformed manifest {index}",
            )

        # Parent release binding is both content-addressed and identity-bound.
        # A changed parent manifest or a valid manifest with the wrong release
        # identity must fail before any derived package can be created.
        parent_root = temporary / "parent-binding"
        parent_manifest = parent_root / "parent" / "MANIFEST.json"
        parent_manifest.parent.mkdir(parents=True)
        parent_manifest.write_text(
            json.dumps({"release_id": PARENT_RELEASE_ID}) + "\n",
            encoding="utf-8",
        )
        parent_relative = "parent/MANIFEST.json"
        parent_digest = sha256_file(parent_manifest)
        verified_parent = verify_parent_release_binding(
            parent_root,
            (parent_relative, parent_digest, PARENT_RELEASE_ID),
        )
        if verified_parent.get("sha256") != parent_digest:
            raise AssertionError("Valid parent release binding parsed incorrectly")
        expect_packaging_error(
            lambda: verify_parent_release_binding(
                parent_root,
                (parent_relative, parent_digest, "WRONG-PARENT-ID"),
            ),
            "wrong parent release identity",
        )
        parent_manifest.write_text(
            json.dumps({"release_id": PARENT_RELEASE_ID, "changed": True}) + "\n",
            encoding="utf-8",
        )
        expect_packaging_error(
            lambda: verify_parent_release_binding(
                parent_root,
                (parent_relative, parent_digest, PARENT_RELEASE_ID),
            ),
            "changed parent release manifest",
        )

        # The English report cannot be relabelled without a no-science-delta
        # declaration, PASS language/numeric/visual audits, and an exact hash
        # binding to the canonical Norwegian V2 translation source.
        translation_root = temporary / "translation-contract"
        translation_source = translation_root / "parent" / "source.tex"
        translation_manifest = translation_root / "report" / "source_manifest.json"
        translation_source.parent.mkdir(parents=True)
        translation_manifest.parent.mkdir(parents=True)
        translation_source.write_text("canonical source\n", encoding="utf-8")
        translation_source_digest = sha256_file(translation_source)
        good_translation_payload = {
            "language": "English",
            "translation_only_no_scientific_delta": True,
            "translation_source_binding": {
                "path": "../parent/source.tex",
                "sha256": translation_source_digest,
            },
            "verification": {
                "actionable_latex_warning_count": 0,
                "pdf_strictly_newer_than_tex": True,
                "language_audit": "PASS; self-test",
                "scientific_numeric_equivalence": "PASS; self-test",
                "visual_inspection": "PASS; self-test",
            },
            "files": [
                {
                    "path": "../parent/source.tex",
                    "sha256": translation_source_digest,
                }
            ],
        }
        translation_manifest.write_text(
            json.dumps(good_translation_payload) + "\n", encoding="utf-8"
        )
        verify_english_translation_contract(
            translation_root,
            "report/source_manifest.json",
            "parent/source.tex",
            translation_source_digest,
        )
        bad_translation_payload = dict(good_translation_payload)
        bad_translation_payload["language"] = "Norwegian"
        translation_manifest.write_text(
            json.dumps(bad_translation_payload) + "\n", encoding="utf-8"
        )
        expect_packaging_error(
            lambda: verify_english_translation_contract(
                translation_root,
                "report/source_manifest.json",
                "parent/source.tex",
                translation_source_digest,
            ),
            "non-English translation manifest",
        )
        translation_manifest.write_text(
            json.dumps(good_translation_payload) + "\n", encoding="utf-8"
        )
        translation_source.write_text("changed source\n", encoding="utf-8")
        expect_packaging_error(
            lambda: verify_english_translation_contract(
                translation_root,
                "report/source_manifest.json",
                "parent/source.tex",
                translation_source_digest,
            ),
            "changed canonical translation source",
        )

        # Scaffold snapshot catches same-scope mutation before staged bytes can
        # be used in archives, inventory or checksums.
        scaffold_dir = temporary / "scaffold"
        scaffold_dir.mkdir()
        for name in SCAFFOLD_FILES:
            (scaffold_dir / name).write_text(f"original:{name}\n", encoding="utf-8")
        scaffold_state = snapshot_scaffold(scaffold_dir)
        (scaffold_dir / "README.md").write_text("mutated:README.md\n", encoding="utf-8")
        expect_packaging_error(
            lambda: verify_scaffold_unchanged(
                scaffold_state, "during scaffold self-test", scaffold_dir
            ),
            "scaffold mutation",
        )

        # Report freshness is strict: PDF == TeX fails, and any project FLS
        # dependency newer than the PDF fails even when content is unchanged.
        report_root = temporary / "report-root"
        report_dir = report_root / "report"
        report_dir.mkdir(parents=True)
        tex = report_dir / "selftest.tex"
        pdf = report_dir / "selftest.pdf"
        readme = report_dir / "README.md"
        log = report_dir / "selftest.log"
        fls = report_dir / "selftest.fls"
        dependency = report_dir / "dependency.csv"
        report_manifest = report_dir / "source_manifest.json"
        tex.write_text("\\documentclass{article}\n", encoding="utf-8")
        pdf.write_bytes(b"%PDF-1.4\nself-test\n")
        readme.write_text("self-test report\n", encoding="utf-8")
        log.write_text("This is pdfTeX; no blocking warnings.\n", encoding="utf-8")
        dependency.write_text("value\n1\n", encoding="utf-8")
        fls.write_text(
            f"PWD {report_dir.resolve()}\nINPUT {dependency.name}\n",
            encoding="utf-8",
        )
        report_manifest.write_text(
            json.dumps(
                {
                    "files": [
                        {"path": tex.name, "sha256": sha256_file(tex)},
                        {"path": pdf.name, "sha256": sha256_file(pdf)},
                    ]
                }
            )
            + "\n",
            encoding="utf-8",
        )
        report_spec = ReportSpec(
            "selftest",
            "report/selftest.tex",
            "report/selftest.pdf",
            "report/README.md",
            "report/source_manifest.json",
        )
        base_ns = 1_700_000_000_000_000_000
        step_ns = 2_000_000_000
        os.utime(tex, ns=(base_ns, base_ns))
        os.utime(pdf, ns=(base_ns, base_ns))
        os.utime(dependency, ns=(base_ns - step_ns, base_ns - step_ns))
        expect_packaging_error(
            lambda: verify_report(report_spec, report_root),
            "PDF mtime equal to TeX",
        )
        os.utime(pdf, ns=(base_ns + step_ns, base_ns + step_ns))
        os.utime(
            dependency,
            ns=(base_ns + 2 * step_ns, base_ns + 2 * step_ns),
        )
        expect_packaging_error(
            lambda: verify_report(report_spec, report_root),
            "project dependency newer than PDF",
        )
        os.utime(dependency, ns=(base_ns, base_ns))
        verify_report(report_spec, report_root)

        # Unknown files prevent overwrite; an injected mid-promotion failure
        # restores the fully verified old generated set byte-for-byte.
        unknown_release = temporary / "unknown-release"
        write_release_fixture(unknown_release, "old")
        (unknown_release / "reports" / "user-owned.txt").write_text(
            "do not remove\n", encoding="utf-8"
        )
        expect_packaging_error(
            lambda: verify_existing_generated_release(
                unknown_release, verify_scaffold=True
            ),
            "unknown overwrite file",
        )

        rollback_release = temporary / "rollback-release"
        rollback_stage = temporary / "rollback-stage"
        write_release_fixture(rollback_release, "old")
        write_release_fixture(rollback_stage, "new")
        old_hashes = {
            relative: sha256_file(rollback_release / relative)
            for relative in parse_sha256sums(rollback_release / "SHA256SUMS")
            if is_generated_package_path(relative)
        }
        expect_packaging_error(
            lambda: promote_staged_release(
                rollback_stage,
                rollback_release,
                overwrite=True,
                fail_after_promotions=1,
            ),
            "injected transaction rollback",
        )
        verify_existing_generated_release(rollback_release, verify_scaffold=True)
        restored_hashes = {
            relative: sha256_file(rollback_release / relative)
            for relative in old_hashes
        }
        if restored_hashes != old_hashes:
            raise AssertionError("Rollback did not restore the original generated bytes")
        if list(rollback_release.glob(".v8-1-package-backup-*")):
            raise AssertionError("Rollback left an unexpected backup after full recovery")

        # Hard-gate ordering: audit, manifest and CSV bytes are snapshotted
        # before validation. A mutation after a successful validation can never
        # become a new baseline or leave reusable stale manifest_results.
        guard_root = temporary / "hard-gate-guard"
        guard_root.mkdir()
        guard_target = guard_root / "target.txt"
        guard_target.write_text("stable target\n", encoding="utf-8")
        guard_items = (
            artifact("audit.json", "results/audit.json", "result", "selftest"),
            artifact(
                "source_manifest.json",
                "results/source_manifest.json",
                "result",
                "selftest",
            ),
            artifact("data.csv", "results/data.csv", "result", "selftest"),
            artifact("target.txt", "results/target.txt", "result", "selftest"),
        )
        guard_audits = (("audit.json", ("passed",), True),)

        def reset_guard_inputs() -> None:
            (guard_root / "audit.json").write_text(
                '{"passed": true}\n', encoding="utf-8"
            )
            (guard_root / "data.csv").write_text(
                "case_id,value\nA,1\n", encoding="utf-8"
            )
            (guard_root / "source_manifest.json").write_text(
                json.dumps(
                    {
                        "files": [
                            {
                                "path": "target.txt",
                                "sha256": sha256_file(guard_target),
                            }
                        ]
                    }
                )
                + "\n",
                encoding="utf-8",
            )

        mutations = {
            "audit": lambda: (guard_root / "audit.json").write_text(
                '{"passed": false}\n', encoding="utf-8"
            ),
            "manifest": lambda: (guard_root / "source_manifest.json").write_text(
                '{"files": []}\n', encoding="utf-8"
            ),
            "CSV": lambda: (guard_root / "data.csv").write_text(
                "case_id,value\nA,1\nB,2\n", encoding="utf-8"
            ),
        }
        for label, mutate in mutations.items():
            reset_guard_inputs()
            guarded_snapshots = snapshot_allowlist(guard_root, guard_items)
            validate_hard_inputs(
                guard_root,
                reports=(),
                provenance_manifests=("source_manifest.json",),
                audit_contracts=guard_audits,
                allowlist=guard_items,
                parent_release_binding=None,
                enforce_english_translation_contract=False,
            )
            mutate()
            expect_packaging_error(
                lambda: verify_allowlist_unchanged(
                    guard_root,
                    guarded_snapshots,
                    f"after {label} hard-gate validation",
                    guard_items,
                ),
                f"{label} mutation after hard validation",
            )


def main() -> int:
    args = parse_args()
    if args.self_test:
        try:
            run_self_tests()
        except (AssertionError, PackagingError, OSError) as exc:
            print(f"SELF-TEST ERROR: {exc}", file=sys.stderr)
            return 2
        print("PASS: isolated packager safety self-tests")
        return 0
    try:
        (
            snapshots,
            scaffold_snapshots,
            report_states,
            manifest_results,
            report_results,
            final_status,
            verification_payloads,
            checker_command,
            revision,
        ) = preflight(args.repo_root, args.timeout_seconds)
        if args.check_only:
            print(
                f"PASS: {RELEASE_ID} preflight; {len(COPY_ALLOWLIST)} allowlisted "
                f"files, {len(manifest_results)} manifests, {len(report_results)} reports."
            )
            print("No package files were created (--check-only).")
            return 0
        build_package(
            args.repo_root.resolve(),
            snapshots,
            scaffold_snapshots,
            report_states,
            manifest_results,
            report_results,
            final_status,
            verification_payloads,
            checker_command,
            revision,
            args.overwrite,
        )
    except (PackagingError, subprocess.TimeoutExpired, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(f"PASS: packaged {RELEASE_ID} in {RELEASE_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
