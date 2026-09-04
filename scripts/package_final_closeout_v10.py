#!/usr/bin/env python3
"""Build and verify the controlled XMembrane V10 closeout package.

The packager is fail-closed and intentionally independent of the historical
``run_final_delivery_check_v1.py`` checker.  V10 validates the September
evidence directly, archives the complete Git source revision, overlays the
verified source/result archives into a fresh tree, runs the full test suite
there, and checks every ZIP member and package checksum before atomic
publication.

Publishing usage (run after committing the curated source/report revision)::

    python3 scripts/package_final_closeout_v10.py \
        --expected-source-revision "$(git rev-parse HEAD)"

Non-publishing preflight usage::

    python3 scripts/package_final_closeout_v10.py --check-only --skip-tests

V8 and V8.1 are never read as package parents and are never modified.
"""

from __future__ import annotations

import argparse
import hashlib
from importlib import metadata
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence


RELEASE_ID = "XMEMBRANE-2026-09-02-V10"
SCHEMA_VERSION = 1
SCRIPT_VERSION = "xmembrane-final-closeout-v10-packager-1.0"
PROJECT_ARCHIVE_ROOT = "XMembrane_Trond_Study"

SCRIPT_PATH = Path(__file__).resolve()
DEFAULT_REPO_ROOT = SCRIPT_PATH.parents[1]
DEFAULT_RELEASE_RELATIVE = Path("deliverables/current/2026-09-02_v10")

REPORT_DIRECTORY = Path("reports/final_project_closeout_2026-09-02")
REPORT_STEM = "HeiQ_XMembrane_Final_Project_Closeout_2026-09-02_v10"
REPORT_FILES = tuple(
    REPORT_DIRECTORY / f"{REPORT_STEM}{suffix}"
    for suffix in (".pdf", ".md", ".tex")
) + (REPORT_DIRECTORY / "source_manifest.json",)
REPORT_MANIFEST = REPORT_DIRECTORY / "source_manifest.json"
V9_REPORT_FILES = tuple(
    Path("reports/final_team_decision_report_2026-08-31")
    / f"HeiQ_XMembrane_Final_Result_and_Decision_Report_2026-08-31_v9{suffix}"
    for suffix in (".tex", ".pdf")
)

TEMPLATE_FILES = (
    DEFAULT_RELEASE_RELATIVE / "README.md",
    DEFAULT_RELEASE_RELATIVE / "RELEASE_NOTES.md",
)

CAPACITIVE_DIRECTORY = Path("outputs/capacitive_electrode_study_v1")
TW50_DIRECTORY = Path("outputs/direct_active_erv_tw50_d1e10_v1")
FROZEN_ACTIVE_ERV_DIRECTORY = Path("outputs/direct_active_eo_erv_study_v1/study")

FROZEN_ACTIVE_ERV_FILES = tuple(
    FROZEN_ACTIVE_ERV_DIRECTORY / name
    for name in (
        "case_register.csv",
        "segment_register.csv.gz",
    )
)

PROFILE_DIRECTORY = Path(
    "outputs/direct_active_erv_transport_sensitivity_2v/study/figures"
)
PROFILE_FILES = tuple(
    PROFILE_DIRECTORY / name
    for name in (
        "selected_membrane_current_profile.csv",
        "selected_membrane_current_profile_over_under.png",
        "selected_membrane_current_profile_over_under.svg",
        "selected_membrane_humidity_profile.csv",
        "selected_membrane_humidity_profile.png",
        "selected_membrane_humidity_profile.svg",
    )
)
PROFILE_INPUT_FILES = tuple(
    PROFILE_DIRECTORY.parent / name
    for name in (
        "selected_cases.csv",
        "segment_register.csv.gz",
    )
)

EVIDENCE_FILES = (
    Path("docs/CAPACITIVE_ELECTRODE_TRANSIENT_STUDY_2026-09-01.md"),
    CAPACITIVE_DIRECTORY / "SUMMARY.md",
    CAPACITIVE_DIRECTORY / "audit.json",
    CAPACITIVE_DIRECTORY / "source_manifest.json",
    TW50_DIRECTORY / "study/SUMMARY.md",
    TW50_DIRECTORY / "study/DECISION_SUMMARY.json",
    TW50_DIRECTORY / "study/study_audit.json",
    TW50_DIRECTORY / "study/case_register.csv",
)

REPORT_REQUIRED_BINDINGS = (
    Path("docs/CAPACITIVE_ELECTRODE_TRANSIENT_STUDY_2026-09-01.md"),
    CAPACITIVE_DIRECTORY / "audit.json",
    CAPACITIVE_DIRECTORY / "source_manifest.json",
    TW50_DIRECTORY / "study/study_audit.json",
    TW50_DIRECTORY / "study/case_register.csv",
)

REQUIRED_TRACKED_SOURCE_PATHS = (
    Path("pyproject.toml"),
    Path("heiq_pre_receiver_material_analyses/heiq_pre_receiver_model.py"),
    Path("heiq_pre_receiver_material_analyses/config/default.json"),
    Path("src/heiq/wp1/electrodes/__init__.py"),
    Path("src/heiq/wp1/electrodes/capacitive.py"),
    Path("src/heiq/wp1/receiver/coupled_integration.py"),
    Path("src/heiq/wp1/studies/direct_eo_erv.py"),
    Path("config/capacitive_electrode_study_v1.json"),
    Path("scripts/run_capacitive_electrode_study_v1.py"),
    Path("scripts/run_direct_active_erv_tw50_d1e10.py"),
    Path("scripts/plot_selected_membrane_current_profile.py"),
    Path("scripts/plot_selected_membrane_humidity_profile.py"),
    Path("scripts/package_final_closeout_v10.py"),
    Path("tests/test_capacitive_electrode_study_v1.py"),
    *REPORT_FILES,
    *V9_REPORT_FILES,
    *TEMPLATE_FILES,
)

REQUIRED_RESULT_FILES = (
    REPORT_MANIFEST,
    CAPACITIVE_DIRECTORY / "SUMMARY.md",
    CAPACITIVE_DIRECTORY / "audit.json",
    CAPACITIVE_DIRECTORY / "source_manifest.json",
    CAPACITIVE_DIRECTORY / "config_used.json",
    TW50_DIRECTORY / "config_tw50_d1e10.json",
    TW50_DIRECTORY / "study/SUMMARY.md",
    TW50_DIRECTORY / "study/DECISION_SUMMARY.json",
    TW50_DIRECTORY / "study/case_register.csv",
    TW50_DIRECTORY / "study/config_used.json",
    TW50_DIRECTORY / "study/segment_register.csv.gz",
    TW50_DIRECTORY / "study/study_audit.json",
    *FROZEN_ACTIVE_ERV_FILES,
    *PROFILE_INPUT_FILES,
    *PROFILE_FILES,
)

SOURCE_ARCHIVE_NAME = "HeiQ_XMembrane_2026-09-02_v10_source.zip"
RESULT_ARCHIVE_NAME = "HeiQ_XMembrane_2026-09-02_v10_results.zip"

HASH_RE = re.compile(r"^[0-9a-f]{64}$")
FORBIDDEN_RESULT_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".venv",
    "__pycache__",
}
FORBIDDEN_RESULT_SUFFIXES = {".pyc", ".pyo"}
ALLOWED_RELEASE_TOP_LEVEL = {
    "README.md",
    "RELEASE_NOTES.md",
    "MANIFEST.json",
    "SHA256SUMS",
    "archives",
    "environment",
    "evidence",
    "reports",
    "results",
    "source",
    "verification",
}


class PackagingError(RuntimeError):
    """Raised when a V10 package condition fails closed."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value.rstrip() + "\n", encoding="utf-8")


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    write_text(
        path,
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True),
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_record(path: Path, relative: Path | str) -> dict[str, Any]:
    return {
        "path": Path(relative).as_posix(),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def run_command(
    command: Sequence[str],
    *,
    cwd: Path,
    check: bool = True,
    timeout: int | None = None,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            list(command),
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
            env=dict(env) if env is not None else None,
        )
    except FileNotFoundError as exc:
        raise PackagingError(f"Required command is unavailable: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise PackagingError(
            f"Command timed out after {timeout} s: {' '.join(command)}"
        ) from exc
    if check and completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise PackagingError(
            f"Command failed ({completed.returncode}): {' '.join(command)}\n{detail}"
        )
    return completed


def git_output(repo_root: Path, *arguments: str) -> str:
    return run_command(
        ("git", *arguments),
        cwd=repo_root,
    ).stdout.strip()


def ensure_repo_root(repo_root: Path) -> None:
    top = Path(git_output(repo_root, "rev-parse", "--show-toplevel")).resolve()
    if top != repo_root.resolve():
        raise PackagingError(
            f"--repo-root must be the Git top level: expected {top}, got {repo_root}"
        )


def ensure_required_files(repo_root: Path, paths: Iterable[Path]) -> None:
    missing = [path.as_posix() for path in paths if not (repo_root / path).is_file()]
    if missing:
        raise PackagingError(
            "Required V10 inputs are missing:\n- " + "\n- ".join(sorted(missing))
        )


def parse_git_tree(repo_root: Path, revision: str) -> list[dict[str, str]]:
    completed = subprocess.run(
        ["git", "ls-tree", "-r", "-z", "--full-tree", revision],
        cwd=repo_root,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise PackagingError(
            f"Cannot enumerate Git revision {revision}: "
            + completed.stderr.decode("utf-8", errors="replace").strip()
        )
    records: list[dict[str, str]] = []
    for raw in completed.stdout.split(b"\0"):
        if not raw:
            continue
        try:
            header, raw_path = raw.split(b"\t", 1)
            mode, object_type, object_id = header.decode("ascii").split(" ", 2)
            path = raw_path.decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise PackagingError("Unable to parse git ls-tree output") from exc
        if object_type != "blob" or mode not in {"100644", "100755", "120000"}:
            raise PackagingError(
                f"Unsupported non-regular tracked entry at {revision}: "
                f"{mode} {object_type} {path}"
            )
        pure = PurePosixPath(path)
        if pure.is_absolute() or ".." in pure.parts or "\n" in path or "\r" in path:
            raise PackagingError(f"Unsafe tracked path: {path!r}")
        records.append(
            {
                "path": path,
                "mode": mode,
                "object_id": object_id,
                "entry_type": "symlink" if mode == "120000" else "regular_file",
            }
        )
    if not records:
        raise PackagingError(f"Git revision contains no regular files: {revision}")
    return sorted(records, key=lambda row: row["path"])


def validate_source_revision(
    repo_root: Path,
    *,
    expected_revision: str | None,
    allow_dirty_tracked: bool,
    publishing: bool,
) -> dict[str, Any]:
    head = git_output(repo_root, "rev-parse", "HEAD")
    source_revision = (
        git_output(repo_root, "rev-parse", f"{expected_revision}^{{commit}}")
        if expected_revision
        else head
    )
    if publishing and not expected_revision:
        raise PackagingError(
            "Publishing requires --expected-source-revision to bind the package "
            "to the curated source/report commit"
        )
    if publishing and source_revision != head:
        raise PackagingError(
            "The expected source revision is not current HEAD: "
            f"expected={source_revision}, HEAD={head}"
        )
    diff = run_command(
        ("git", "diff", "--name-status", source_revision, "--"),
        cwd=repo_root,
        check=False,
    )
    if diff.returncode != 0:
        raise PackagingError("Unable to compare tracked working tree with source revision")
    changed_tracked = [line for line in diff.stdout.splitlines() if line.strip()]
    if changed_tracked and not allow_dirty_tracked:
        preview = "\n- ".join(changed_tracked[:30])
        suffix = "\n- ..." if len(changed_tracked) > 30 else ""
        raise PackagingError(
            "Tracked files differ from the declared source revision. Arbitrary "
            "untracked files are ignored, but tracked drift is not allowed:\n- "
            + preview
            + suffix
        )
    if publishing and allow_dirty_tracked:
        raise PackagingError("--allow-dirty-tracked is permitted only with --check-only")

    tree = parse_git_tree(repo_root, source_revision)
    tracked = {row["path"] for row in tree}
    missing_tracked = sorted(
        path.as_posix()
        for path in REQUIRED_TRACKED_SOURCE_PATHS
        if path.as_posix() not in tracked
    )
    if missing_tracked:
        raise PackagingError(
            "Required V10 source/report files are not tracked at the declared "
            "source revision:\n- " + "\n- ".join(missing_tracked)
        )

    v10_prefix = DEFAULT_RELEASE_RELATIVE.as_posix() + "/"
    allowed_v10 = {path.as_posix() for path in TEMPLATE_FILES}
    recursive_release_files = sorted(
        path for path in tracked if path.startswith(v10_prefix) and path not in allowed_v10
    )
    if recursive_release_files:
        raise PackagingError(
            "The source revision already tracks generated V10 package artifacts. "
            "Package from the curated source/report commit before committing the "
            "release artifacts:\n- " + "\n- ".join(recursive_release_files)
        )

    untracked_process = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
        cwd=repo_root,
        capture_output=True,
        check=False,
    )
    if untracked_process.returncode != 0:
        raise PackagingError(
            "Unable to inventory excluded untracked paths: "
            + untracked_process.stderr.decode("utf-8", errors="replace").strip()
        )
    untracked_paths = sorted(
        path for path in untracked_process.stdout.split(b"\0") if path
    )
    untracked_digest = hashlib.sha256(b"\0".join(untracked_paths)).hexdigest()
    branch = git_output(repo_root, "branch", "--show-current")
    return {
        "source_revision": source_revision,
        "package_time_revision": head,
        "source_and_package_time_revision_match": source_revision == head,
        "branch": branch or None,
        "tracked_source_file_count": len(tree),
        "tracked_files_match_source_revision": not changed_tracked,
        "changed_tracked_files": changed_tracked,
        "untracked_files_are_excluded_from_source_archive": True,
        "excluded_untracked_file_count": len(untracked_paths),
        "excluded_untracked_path_digest_sha256": untracked_digest,
        "release_artifact_revision": None,
        "release_artifact_revision_note": (
            "The commit/tag containing generated release artifacts is created after "
            "packaging and cannot be self-recorded; bind it in the annotated tag."
        ),
        "tree": tree,
    }


def normalize_manifest_path(repo_root: Path, value: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        try:
            return candidate.resolve().relative_to(repo_root.resolve())
        except ValueError:
            # Historical September manifests recorded the original absolute
            # checkout.  For a reconstructed archive, accept only an
            # unambiguous suffix below the exact project-root component.
            pure_absolute = PurePosixPath(value.replace("\\", "/"))
            marker_positions = [
                index
                for index, part in enumerate(pure_absolute.parts)
                if part == PROJECT_ARCHIVE_ROOT
            ]
            if len(marker_positions) != 1:
                raise PackagingError(
                    "Absolute manifest path has no unambiguous "
                    f"{PROJECT_ARCHIVE_ROOT}/ suffix: {value}"
                )
            suffix = pure_absolute.parts[marker_positions[0] + 1 :]
            if not suffix or ".." in suffix:
                raise PackagingError(f"Unsafe absolute manifest suffix: {value}")
            return Path(*suffix)
    pure = PurePosixPath(value.replace("\\", "/"))
    if pure.is_absolute() or not pure.parts or ".." in pure.parts:
        raise PackagingError(f"Unsafe relative manifest path: {value!r}")
    parts = list(pure.parts)
    if parts[0] == PROJECT_ARCHIVE_ROOT:
        parts = parts[1:]
    if not parts:
        raise PackagingError(f"Manifest path does not name a file: {value!r}")
    return Path(*parts)


def embedded_file_records(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        if isinstance(value.get("path"), str) and isinstance(
            value.get("sha256"), str
        ):
            yield value
        for child in value.values():
            yield from embedded_file_records(child)
    elif isinstance(value, list):
        for child in value:
            yield from embedded_file_records(child)


def verify_embedded_manifest(
    repo_root: Path,
    manifest_relative: Path,
    *,
    required_paths: Sequence[Path] = (),
) -> dict[str, Any]:
    manifest_path = repo_root / manifest_relative
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PackagingError(f"Invalid JSON manifest {manifest_relative}: {exc}") from exc
    records = list(embedded_file_records(payload))
    if not records:
        raise PackagingError(
            f"No embedded path/SHA-256 records found in {manifest_relative}"
        )
    checks: list[dict[str, Any]] = []
    seen: dict[str, str] = {}
    for record in records:
        relative = normalize_manifest_path(repo_root, str(record["path"]))
        relative_text = relative.as_posix()
        expected = str(record["sha256"]).lower()
        if HASH_RE.fullmatch(expected) is None:
            raise PackagingError(
                f"Malformed SHA-256 for {relative_text} in {manifest_relative}"
            )
        previous = seen.get(relative_text)
        if previous is not None and previous != expected:
            raise PackagingError(
                f"Conflicting hashes for {relative_text} in {manifest_relative}"
            )
        seen[relative_text] = expected
        target = repo_root / relative
        if not target.is_file():
            raise PackagingError(
                f"Manifest-bound file is missing: {relative_text} "
                f"(declared by {manifest_relative})"
            )
        actual = sha256_file(target)
        if actual != expected:
            raise PackagingError(
                f"Stale manifest hash for {relative_text}: expected {expected}, got {actual}"
            )
        expected_size = record.get("size_bytes")
        if expected_size is not None:
            if not isinstance(expected_size, int) or expected_size < 0:
                raise PackagingError(
                    f"Invalid size_bytes for {relative_text} in {manifest_relative}"
                )
            if target.stat().st_size != expected_size:
                raise PackagingError(
                    f"Stale manifest size for {relative_text}: expected "
                    f"{expected_size}, got {target.stat().st_size}"
                )
        checks.append(
            {
                "path": relative_text,
                "sha256": actual,
                "size_bytes": target.stat().st_size,
                "passed": True,
            }
        )
    missing_bindings = sorted(
        path.as_posix() for path in required_paths if path.as_posix() not in seen
    )
    if missing_bindings:
        raise PackagingError(
            f"{manifest_relative} lacks required V10 evidence bindings:\n- "
            + "\n- ".join(missing_bindings)
        )
    return {
        "manifest": manifest_relative.as_posix(),
        "passed": True,
        "checked_record_count": len(checks),
        "unique_path_count": len(seen),
        "required_bindings": [path.as_posix() for path in required_paths],
        "records": checks,
    }


def load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PackagingError(f"Invalid JSON file {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PackagingError(f"Expected JSON object: {path}")
    return value


def verify_scientific_audits(repo_root: Path) -> dict[str, Any]:
    capacitive_path = repo_root / CAPACITIVE_DIRECTORY / "audit.json"
    capacitive = load_json_object(capacitive_path)
    cap_checks = capacitive.get("checks")
    cap_claim = capacitive.get("claim_boundary")
    cap_pass = bool(
        capacitive.get("status") == "PASS"
        and capacitive.get("all_pass") is True
        and isinstance(cap_checks, dict)
        and cap_checks
        and all(value is True for value in cap_checks.values())
        and isinstance(cap_claim, dict)
        and cap_claim.get("full_system_claim_allowed") is False
        and cap_claim.get("validated_electrode_prediction") is False
    )
    if not cap_pass:
        raise PackagingError("Capacitive-electrode audit is not a fail-closed PASS")

    tw_path = repo_root / TW50_DIRECTORY / "study/study_audit.json"
    tw = load_json_object(tw_path)
    tw_checks = tw.get("checks")
    tw_claim = tw.get("claim_boundary")
    tw_pass = bool(
        tw.get("status") == "PASS"
        and isinstance(tw_checks, list)
        and tw_checks
        and all(
            isinstance(row, dict) and row.get("passed") is True for row in tw_checks
        )
        and isinstance(tw_claim, dict)
        and tw_claim.get("full_system_claim_allowed") is False
        and tw_claim.get("commercial_claim_allowed") is False
    )
    if not tw_pass:
        raise PackagingError("t_w=50, D=10^-10 study audit is not a fail-closed PASS")

    decision_path = repo_root / TW50_DIRECTORY / "study/DECISION_SUMMARY.json"
    decision = load_json_object(decision_path)
    if decision.get("full_coupled_gate_count") != 0:
        raise PackagingError(
            "The V10 synthetic case unexpectedly has a full-coupled gate pass"
        )
    decision_claim = decision.get("claim_boundary")
    if not isinstance(decision_claim, dict) or decision_claim.get(
        "full_system_claim_allowed"
    ) is not False:
        raise PackagingError("Synthetic-case decision claim boundary is not closed")

    return {
        "passed": True,
        "capacitive_electrode": {
            "path": capacitive_path.relative_to(repo_root).as_posix(),
            "status": capacitive.get("status"),
            "check_count": len(cap_checks),
            "full_system_claim_allowed": cap_claim.get("full_system_claim_allowed"),
            "validated_electrode_prediction": cap_claim.get(
                "validated_electrode_prediction"
            ),
        },
        "synthetic_tw50_d1e10": {
            "path": tw_path.relative_to(repo_root).as_posix(),
            "status": tw.get("status"),
            "check_count": len(tw_checks),
            "full_coupled_gate_count": decision.get("full_coupled_gate_count"),
            "full_system_claim_allowed": tw_claim.get("full_system_claim_allowed"),
            "commercial_claim_allowed": tw_claim.get("commercial_claim_allowed"),
        },
    }


def verify_report(repo_root: Path) -> dict[str, Any]:
    pdf = repo_root / REPORT_FILES[0]
    markdown = repo_root / REPORT_FILES[1]
    content = pdf.read_bytes()
    if len(content) < 1024 or not content.startswith(b"%PDF-"):
        raise PackagingError(f"V10 report is not a non-empty PDF: {REPORT_FILES[0]}")
    if b"%%EOF" not in content[-4096:]:
        raise PackagingError(f"V10 report lacks a terminal PDF EOF marker: {REPORT_FILES[0]}")

    markdown_text = markdown.read_text(encoding="utf-8")
    required_terms = (
        "capacitive",
        "transient",
        "t_w=50",
        "10^{-10}",
        "synthetic",
        "not validated",
    )
    folded = markdown_text.casefold()
    missing_terms = [term for term in required_terms if term.casefold() not in folded]
    if missing_terms:
        raise PackagingError(
            f"V10 closeout Markdown lacks required claim terms: {missing_terms}"
        )

    pdfinfo: dict[str, Any] = {"available": shutil.which("pdfinfo") is not None}
    if pdfinfo["available"]:
        completed = run_command(("pdfinfo", str(pdf)), cwd=repo_root)
        pages: int | None = None
        for line in completed.stdout.splitlines():
            if line.startswith("Pages:"):
                pages = int(line.split(":", 1)[1].strip())
                break
        if pages is None or pages <= 0:
            raise PackagingError("pdfinfo did not report a positive V10 page count")
        pdfinfo["pages"] = pages
    return {
        "passed": True,
        "pdf": file_record(pdf, REPORT_FILES[0]),
        "markdown": file_record(markdown, REPORT_FILES[1]),
        "required_terms": {term: True for term in required_terms},
        "pdfinfo": pdfinfo,
    }


def excluded_result_path(relative_within_root: Path) -> bool:
    return bool(
        set(relative_within_root.parts) & FORBIDDEN_RESULT_PARTS
        or relative_within_root.suffix.lower() in FORBIDDEN_RESULT_SUFFIXES
    )


def manifest_check_paths(check: Mapping[str, Any]) -> set[Path]:
    records = check.get("records")
    if not isinstance(records, list):
        raise PackagingError("Internal manifest check lacks a records list")
    return {
        Path(str(record["path"]))
        for record in records
        if isinstance(record, Mapping) and isinstance(record.get("path"), str)
    }


def files_below(repo_root: Path, relative_root: Path) -> set[Path]:
    root = repo_root / relative_root
    if not root.is_dir():
        raise PackagingError(f"Required result directory is missing: {relative_root}")
    records: set[Path] = set()
    for path in sorted(root.rglob("*")):
        within = path.relative_to(root)
        if excluded_result_path(within):
            continue
        if path.is_symlink():
            raise PackagingError(f"Symlinks are not allowed in results: {path}")
        if path.is_file():
            records.add(path.relative_to(repo_root))
    return records


def path_set_digest(paths: Iterable[Path]) -> str:
    encoded = b"\0".join(
        path.as_posix().encode("utf-8")
        for path in sorted(set(paths), key=lambda item: item.as_posix())
    )
    return hashlib.sha256(encoded).hexdigest()


def collect_result_paths(
    repo_root: Path,
    *,
    report_manifest_check: Mapping[str, Any],
    capacitive_manifest_check: Mapping[str, Any],
    tw50_manifest_check: Mapping[str, Any],
) -> tuple[list[Path], dict[str, Any]]:
    report_bound = manifest_check_paths(report_manifest_check)
    capacitive_bound = manifest_check_paths(capacitive_manifest_check)
    tw50_bound = manifest_check_paths(tw50_manifest_check)
    explicit = set(REQUIRED_RESULT_FILES)
    records = explicit | report_bound | capacitive_bound | tw50_bound
    ensure_required_files(repo_root, records)
    symlinks = sorted(
        path.as_posix() for path in records if (repo_root / path).is_symlink()
    )
    if symlinks:
        raise PackagingError(
            "Manifest-derived result overlay contains symlinks; add them to the "
            "tracked source revision instead:\n- " + "\n- ".join(symlinks)
        )

    # These three scientific directories are strict: every file must be
    # explicitly named by a governing manifest or the curated V10 list.
    strict_scopes: dict[str, dict[str, Any]] = {}
    for scope in (CAPACITIVE_DIRECTORY, TW50_DIRECTORY):
        actual = files_below(repo_root, scope)
        included = {path for path in records if path.is_relative_to(scope)}
        unexpected = actual - included
        if unexpected:
            raise PackagingError(
                f"Unallowlisted files found in strict result scope {scope}; "
                f"count={len(unexpected)}, path_digest={path_set_digest(unexpected)}"
            )
        strict_scopes[scope.as_posix()] = {
            "actual_file_count": len(actual),
            "allowlisted_file_count": len(included),
            "unexpected_file_count": 0,
        }

    # The transport-sensitivity study contains other exploratory artifacts.
    # They are deliberately excluded without disclosing unrelated names.
    frozen_actual = files_below(repo_root, FROZEN_ACTIVE_ERV_DIRECTORY)
    frozen_included = {
        path for path in records if path.is_relative_to(FROZEN_ACTIVE_ERV_DIRECTORY)
    }
    frozen_excluded = frozen_actual - frozen_included

    profile_scope = PROFILE_DIRECTORY.parent
    profile_actual = files_below(repo_root, profile_scope)
    profile_included = {path for path in records if path.is_relative_to(profile_scope)}
    profile_excluded = profile_actual - profile_included
    selection = {
        "selection_policy": (
            "exact union of report-manifest records, nested scientific-manifest "
            "records, and the explicit V10 profile/frozen-study allowlist"
        ),
        "report_manifest_bound_count": len(report_bound),
        "capacitive_manifest_bound_count": len(capacitive_bound),
        "tw50_manifest_bound_count": len(tw50_bound),
        "explicit_allowlist_count": len(explicit),
        "selected_unique_file_count": len(records),
        "strict_scopes": strict_scopes,
        "frozen_active_erv_scope": {
            "path": FROZEN_ACTIVE_ERV_DIRECTORY.as_posix(),
            "selected_file_count": len(frozen_included),
            "excluded_unallowlisted_file_count": len(frozen_excluded),
            "excluded_unallowlisted_path_digest_sha256": path_set_digest(
                frozen_excluded
            ),
        },
        "profile_scope": {
            "path": profile_scope.as_posix(),
            "selected_file_count": len(profile_included),
            "excluded_unallowlisted_file_count": len(profile_excluded),
            "excluded_unallowlisted_path_digest_sha256": path_set_digest(
                profile_excluded
            ),
        },
    }
    return sorted(records, key=lambda path: path.as_posix()), selection


def copy_file(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise PackagingError(f"Cannot copy missing file: {source}")
    if source.is_symlink():
        raise PackagingError(f"Symlink inputs are forbidden: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def normalize_release_modes(
    release_root: Path,
    source_tree: Sequence[Mapping[str, str]],
) -> dict[str, int]:
    """Apply portable modes without changing release file contents.

    The package may be staged on a filesystem that reports every copied file
    as executable. Published directories and ordinary files are normalized to
    0755 and 0644 respectively. Only files in the extracted Git source
    snapshot whose declared Git mode is 100755 retain an executable bit.
    Symlink modes are deliberately left alone because chmod would operate on
    their targets on many platforms.
    """

    if not release_root.is_dir() or release_root.is_symlink():
        raise PackagingError(
            f"Release mode root is not a normal directory: {release_root}"
        )

    source_modes: dict[PurePosixPath, str] = {}
    for record in source_tree:
        try:
            source_path = PurePosixPath(str(record["path"]))
            source_mode = str(record["mode"])
        except KeyError as exc:
            raise PackagingError("Source tree mode record is incomplete") from exc
        if (
            source_path.is_absolute()
            or not source_path.parts
            or ".." in source_path.parts
            or source_mode not in {"100644", "100755", "120000"}
        ):
            raise PackagingError(
                f"Invalid source tree mode record: {source_mode} {source_path}"
            )
        source_modes[source_path] = source_mode

    source_prefix = ("source", PROJECT_ARCHIVE_ROOT)
    directory_count = 1
    regular_file_count = 0
    executable_file_count = 0

    release_root.chmod(0o755)
    if stat.S_IMODE(release_root.stat().st_mode) != 0o755:
        raise PackagingError(
            f"Filesystem did not apply directory mode 0755: {release_root}"
        )

    for path in sorted(release_root.rglob("*")):
        if path.is_symlink():
            continue
        if path.is_dir():
            expected_mode = 0o755
            directory_count += 1
        elif path.is_file():
            relative = PurePosixPath(path.relative_to(release_root).as_posix())
            executable = False
            if relative.parts[:2] == source_prefix:
                source_relative = PurePosixPath(*relative.parts[2:])
                executable = source_modes.get(source_relative) == "100755"
            expected_mode = 0o755 if executable else 0o644
            regular_file_count += 1
            executable_file_count += int(executable)
        else:
            raise PackagingError(f"Unsupported release entry: {path}")

        path.chmod(expected_mode)
        actual_mode = stat.S_IMODE(path.stat().st_mode)
        if actual_mode != expected_mode:
            raise PackagingError(
                "Filesystem did not apply deterministic release mode "
                f"{expected_mode:04o}: {path} (actual {actual_mode:04o})"
            )

    return {
        "directory_count": directory_count,
        "regular_file_count": regular_file_count,
        "executable_file_count": executable_file_count,
    }


def safe_zip_member(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise PackagingError(f"Unsafe ZIP member path: {name!r}")
    return path


def make_deterministic_result_zip(
    repo_root: Path,
    result_paths: Sequence[Path],
    archive: Path,
) -> None:
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        archive,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as bundle:
        for relative in result_paths:
            source = repo_root / relative
            member = f"{PROJECT_ARCHIVE_ROOT}/{relative.as_posix()}"
            info = zipfile.ZipInfo(member, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            info.create_system = 3
            info.flag_bits |= 0x800
            bundle.writestr(info, source.read_bytes(), compresslevel=9)


def make_git_source_archive(
    repo_root: Path,
    source_revision: str,
    archive: Path,
) -> None:
    archive.parent.mkdir(parents=True, exist_ok=True)
    run_command(
        (
            "git",
            "archive",
            "--format=zip",
            f"--prefix={PROJECT_ARCHIVE_ROOT}/",
            "--output",
            str(archive),
            source_revision,
        ),
        cwd=repo_root,
    )


def expected_records(
    repo_root: Path,
    relative_paths: Sequence[Path],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for relative in relative_paths:
        source = repo_root / relative
        member = f"{PROJECT_ARCHIVE_ROOT}/{relative.as_posix()}"
        result[member] = file_record(source, relative)
    return result


def expected_git_source_records(
    repo_root: Path,
    tree: Sequence[Mapping[str, str]],
) -> dict[str, dict[str, Any]]:
    process = subprocess.Popen(
        ["git", "cat-file", "--batch"],
        cwd=repo_root,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    request = b"".join(row["object_id"].encode("ascii") + b"\n" for row in tree)
    stdout, stderr = process.communicate(request)
    if process.returncode != 0:
        raise PackagingError(
            "Cannot read tracked Git blobs: "
            + stderr.decode("utf-8", errors="replace").strip()
        )

    result: dict[str, dict[str, Any]] = {}
    offset = 0
    for row in tree:
        relative = Path(row["path"])
        header_end = stdout.find(b"\n", offset)
        if header_end < 0:
            raise PackagingError(
                f"Truncated git cat-file header for {relative}"
            )
        header = stdout[offset:header_end].decode("ascii", errors="strict")
        fields = header.split(" ")
        if len(fields) != 3 or fields[1] != "blob":
            raise PackagingError(f"Unexpected git cat-file header for {relative}: {header}")
        try:
            size = int(fields[2])
        except ValueError as exc:
            raise PackagingError(
                f"Invalid git cat-file size for {relative}: {header}"
            ) from exc
        data_start = header_end + 1
        data_end = data_start + size
        if data_end >= len(stdout) or stdout[data_end : data_end + 1] != b"\n":
            raise PackagingError(f"Truncated git cat-file payload for {relative}")
        data = stdout[data_start:data_end]
        offset = data_end + 1
        if row["entry_type"] == "symlink":
            try:
                link_target = data.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise PackagingError(
                    f"Tracked symlink target is not UTF-8: {relative}"
                ) from exc
            record = {
                "path": relative.as_posix(),
                "size_bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "entry_type": "symlink",
                "link_target": link_target,
            }
        else:
            record = {
                "path": relative.as_posix(),
                "size_bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "entry_type": "regular_file",
            }
        member = f"{PROJECT_ARCHIVE_ROOT}/{relative.as_posix()}"
        result[member] = record
    if offset != len(stdout):
        raise PackagingError("Unexpected trailing data from git cat-file --batch")
    return result


def verify_zip_archive(
    archive: Path,
    expected: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    try:
        bundle = zipfile.ZipFile(archive, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise PackagingError(f"Invalid ZIP archive {archive}: {exc}") from exc
    with bundle:
        infos = bundle.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise PackagingError(f"Duplicate members in ZIP archive: {archive}")
        actual_files: dict[str, zipfile.ZipInfo] = {}
        for info in infos:
            safe_zip_member(info.filename)
            mode = (info.external_attr >> 16) & 0o170000
            if not info.is_dir():
                actual_files[info.filename] = info
        missing = sorted(set(expected) - set(actual_files))
        unexpected = sorted(set(actual_files) - set(expected))
        if missing or unexpected:
            raise PackagingError(
                f"ZIP member mismatch for {archive}; missing={missing[:20]}, "
                f"unexpected={unexpected[:20]}"
            )
        for name, record in expected.items():
            info = actual_files[name]
            mode = (info.external_attr >> 16) & 0o170000
            actual_type = "symlink" if mode == 0o120000 else "regular_file"
            expected_type = str(record.get("entry_type", "regular_file"))
            if actual_type != expected_type:
                raise PackagingError(
                    f"ZIP member type mismatch: {archive.name}:{name}; "
                    f"expected={expected_type}, actual={actual_type}"
                )
            data = bundle.read(info)
            digest = hashlib.sha256(data).hexdigest()
            if digest != record["sha256"]:
                raise PackagingError(
                    f"ZIP member hash mismatch: {archive.name}:{name}"
                )
            if len(data) != record["size_bytes"]:
                raise PackagingError(
                    f"ZIP member size mismatch: {archive.name}:{name}"
                )
    return {
        "archive": archive.name,
        "passed": True,
        "file_member_count": len(expected),
        "sha256": sha256_file(archive),
        "size_bytes": archive.stat().st_size,
        "missing_members": [],
        "unexpected_members": [],
        "member_hash_failures": [],
    }


def verify_overlay_compatibility(
    source_expected: Mapping[str, Mapping[str, Any]],
    result_expected: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    shared = sorted(set(source_expected) & set(result_expected))
    mismatches: list[str] = []
    for member in shared:
        source = source_expected[member]
        result = result_expected[member]
        if (
            source.get("sha256") != result.get("sha256")
            or source.get("size_bytes") != result.get("size_bytes")
            or source.get("entry_type", "regular_file")
            != result.get("entry_type", "regular_file")
        ):
            mismatches.append(member)
    if mismatches:
        raise PackagingError(
            "Source/result archive overlays disagree for shared paths:\n- "
            + "\n- ".join(mismatches)
        )
    return {
        "passed": True,
        "shared_member_count": len(shared),
        "mismatched_member_count": 0,
    }


def extract_verified_zip(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "r") as bundle:
        for info in bundle.infolist():
            member = safe_zip_member(info.filename)
            if info.is_dir():
                continue
            target = destination.joinpath(*member.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() or target.is_symlink():
                target.unlink()
            mode = (info.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                try:
                    link_target = bundle.read(info).decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise PackagingError(
                        f"Non-UTF-8 symlink target in {archive.name}:{info.filename}"
                    ) from exc
                if Path(link_target).is_absolute():
                    raise PackagingError(
                        f"Absolute symlink target in {archive.name}:{info.filename}"
                    )
                resolved_target = (target.parent / link_target).resolve()
                try:
                    resolved_target.relative_to(destination.resolve())
                except ValueError as exc:
                    raise PackagingError(
                        f"Symlink escapes extracted tree: {info.filename} -> {link_target}"
                    ) from exc
                target.symlink_to(link_target)
            else:
                with bundle.open(info, "r") as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
                permissions = (info.external_attr >> 16) & 0o777
                if permissions:
                    target.chmod(permissions)


def package_inventory(root: Path, *, exclude: set[str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative in exclude:
            continue
        records.append(file_record(path, relative))
    return records


def python_package_inventory() -> list[str]:
    packages: set[tuple[str, str]] = set()
    for distribution in metadata.distributions():
        name = distribution.metadata.get("Name") or "UNKNOWN"
        packages.add((str(name), str(distribution.version)))
    return [
        f"{name}=={version}"
        for name, version in sorted(packages, key=lambda row: row[0].casefold())
    ]


def run_reconstructed_full_tests(
    reconstructed_root: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    command = (
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-rs",
        "-p",
        "no:cacheprovider",
    )
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["TMPDIR"] = "/tmp"
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    environment["PYTHONHASHSEED"] = "0"
    environment["MPLBACKEND"] = "Agg"
    environment["PYTHONPATH"] = os.pathsep.join(
        (str(reconstructed_root / "src"), str(reconstructed_root))
    )
    started = time.monotonic()
    try:
        completed = run_command(
            command,
            cwd=reconstructed_root,
            check=False,
            timeout=timeout_seconds,
            env=environment,
        )
    except PackagingError as exc:
        return {
            "mode": "reconstructed_archive_full_pytest",
            "command": list(command),
            "working_directory": PROJECT_ARCHIVE_ROOT,
            "pythonpath": [
                f"{PROJECT_ARCHIVE_ROOT}/src",
                PROJECT_ARCHIVE_ROOT,
            ],
            "environment_controls": {
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                "PYTHONHASHSEED": "0",
                "MPLBACKEND": "Agg",
                "TMPDIR": "/tmp",
            },
            "passed": False,
            "duration_seconds": time.monotonic() - started,
            "error": str(exc),
            "stdout": "",
            "stderr": "",
        }
    passed_match = re.search(r"\b(\d+) passed\b", completed.stdout)
    skipped_match = re.search(r"\b(\d+) skipped\b", completed.stdout)
    skip_reasons = [
        line.strip()
        for line in completed.stdout.splitlines()
        if line.lstrip().startswith("SKIPPED [")
    ]
    return {
        "mode": "reconstructed_archive_full_pytest",
        "command": list(command),
        "working_directory": PROJECT_ARCHIVE_ROOT,
        "pythonpath": [
            f"{PROJECT_ARCHIVE_ROOT}/src",
            PROJECT_ARCHIVE_ROOT,
        ],
        "environment_controls": {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "PYTHONHASHSEED": "0",
            "MPLBACKEND": "Agg",
            "TMPDIR": "/tmp",
        },
        "passed": completed.returncode == 0,
        "returncode": completed.returncode,
        "duration_seconds": time.monotonic() - started,
        "passed_test_count": int(passed_match.group(1)) if passed_match else None,
        "skipped_test_count": int(skipped_match.group(1)) if skipped_match else 0,
        "skip_reasons": skip_reasons,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def verify_package_manifest(staging: Path) -> dict[str, Any]:
    manifest_path = staging / "MANIFEST.json"
    payload = load_json_object(manifest_path)
    files = payload.get("files")
    if not isinstance(files, list) or not files:
        raise PackagingError("MANIFEST.json has no non-empty files array")
    declared: dict[str, Mapping[str, Any]] = {}
    for record in files:
        if not isinstance(record, Mapping):
            raise PackagingError("Malformed MANIFEST.json file record")
        relative = str(record.get("path", ""))
        safe_zip_member(relative)
        if relative in declared:
            raise PackagingError(f"Duplicate MANIFEST.json path: {relative}")
        declared[relative] = record
    actual = {
        record["path"]: record
        for record in package_inventory(
            staging,
            exclude={"MANIFEST.json", "SHA256SUMS"},
        )
    }
    if set(declared) != set(actual):
        raise PackagingError("MANIFEST.json file set does not match staged package")
    for relative, record in actual.items():
        declared_record = declared[relative]
        if declared_record.get("sha256") != record["sha256"] or declared_record.get(
            "size_bytes"
        ) != record["size_bytes"]:
            raise PackagingError(f"MANIFEST.json mismatch for {relative}")
    return {"passed": True, "checked_file_count": len(actual)}


def write_and_verify_sha256sums(staging: Path) -> dict[str, Any]:
    records = package_inventory(staging, exclude={"SHA256SUMS"})
    lines = [f"{record['sha256']}  {record['path']}" for record in records]
    write_text(staging / "SHA256SUMS", "\n".join(lines))

    return verify_sha256sums(staging)


def verify_sha256sums(staging: Path) -> dict[str, Any]:
    checksum_path = staging / "SHA256SUMS"
    if not checksum_path.is_file():
        raise PackagingError(f"Missing SHA256SUMS: {checksum_path}")

    seen: dict[str, str] = {}
    for line in checksum_path.read_text(encoding="utf-8").splitlines():
        if len(line) < 67 or line[64:66] != "  ":
            raise PackagingError(f"Malformed SHA256SUMS line: {line!r}")
        expected, relative = line[:64], line[66:]
        if HASH_RE.fullmatch(expected) is None:
            raise PackagingError(f"Malformed SHA-256 in SHA256SUMS: {line!r}")
        safe_zip_member(relative)
        if relative in seen:
            raise PackagingError(f"Duplicate SHA256SUMS entry: {relative}")
        seen[relative] = expected
        target = staging / relative
        if not target.is_file() or sha256_file(target) != expected:
            raise PackagingError(f"SHA256SUMS verification failed: {relative}")
    expected_paths = {
        record["path"]
        for record in package_inventory(staging, exclude={"SHA256SUMS"})
    }
    if set(seen) != expected_paths:
        raise PackagingError("SHA256SUMS file set does not match staged package")
    return {"passed": True, "checked_file_count": len(seen)}


def ensure_safe_existing_release(release_dir: Path) -> None:
    if not release_dir.exists():
        return
    if not release_dir.is_dir() or release_dir.is_symlink():
        raise PackagingError(f"Release target is not a normal directory: {release_dir}")
    unexpected = sorted(
        child.name
        for child in release_dir.iterdir()
        if child.name not in ALLOWED_RELEASE_TOP_LEVEL
    )
    if unexpected:
        raise PackagingError(
            "Refusing to replace release directory with unexpected top-level "
            f"content: {unexpected}"
        )


def publish_atomically(
    staging: Path,
    release_dir: Path,
    *,
    source_tree: Sequence[Mapping[str, str]],
) -> dict[str, int]:
    ensure_safe_existing_release(release_dir)
    backup = release_dir.with_name(release_dir.name + ".previous")
    if backup.exists():
        raise PackagingError(f"Stale release backup blocks publication: {backup}")
    had_existing = release_dir.exists()
    try:
        if had_existing:
            os.replace(release_dir, backup)
        os.replace(staging, release_dir)
        release_mode_check = normalize_release_modes(release_dir, source_tree)
        verify_package_manifest(release_dir)
        verify_sha256sums(release_dir)
    except Exception:
        failed = release_dir.with_name(release_dir.name + ".failed")
        if failed.exists():
            shutil.rmtree(failed)
        if release_dir.exists():
            os.replace(release_dir, failed)
        if had_existing and backup.exists() and not release_dir.exists():
            os.replace(backup, release_dir)
        if failed.exists():
            shutil.rmtree(failed)
        raise
    if backup.exists():
        shutil.rmtree(backup)
    return release_mode_check


def build_staging(
    repo_root: Path,
    staging: Path,
    *,
    git_state: Mapping[str, Any],
    run_tests: bool,
    pytest_timeout_seconds: int,
) -> dict[str, Any]:
    staging.mkdir(parents=True, exist_ok=False)
    ensure_required_files(
        repo_root,
        (*REPORT_FILES, *TEMPLATE_FILES, *REQUIRED_RESULT_FILES, *EVIDENCE_FILES),
    )

    report_manifest_check = verify_embedded_manifest(
        repo_root,
        REPORT_MANIFEST,
        required_paths=REPORT_REQUIRED_BINDINGS,
    )
    capacitive_manifest_check = verify_embedded_manifest(
        repo_root,
        CAPACITIVE_DIRECTORY / "source_manifest.json",
    )
    tw50_audit_manifest_check = verify_embedded_manifest(
        repo_root,
        TW50_DIRECTORY / "study/study_audit.json",
    )
    scientific_audits = verify_scientific_audits(repo_root)
    report_check = verify_report(repo_root)

    for template in TEMPLATE_FILES:
        copy_file(repo_root / template, staging / template.name)
    for report in REPORT_FILES:
        copy_file(repo_root / report, staging / "reports" / report.name)
    for evidence in EVIDENCE_FILES:
        copy_file(
            repo_root / evidence,
            staging / "evidence" / PROJECT_ARCHIVE_ROOT / evidence,
        )

    source_tree = list(git_state["tree"])
    source_paths = [Path(record["path"]) for record in source_tree]
    source_expected = expected_git_source_records(repo_root, source_tree)
    source_archive = staging / "archives" / SOURCE_ARCHIVE_NAME
    make_git_source_archive(
        repo_root,
        str(git_state["source_revision"]),
        source_archive,
    )
    source_archive_check = verify_zip_archive(source_archive, source_expected)
    extract_verified_zip(source_archive, staging / "source")

    result_paths, result_selection = collect_result_paths(
        repo_root,
        report_manifest_check=report_manifest_check,
        capacitive_manifest_check=capacitive_manifest_check,
        tw50_manifest_check=tw50_audit_manifest_check,
    )
    result_expected = expected_records(repo_root, result_paths)
    overlay_check = verify_overlay_compatibility(source_expected, result_expected)
    result_archive = staging / "archives" / RESULT_ARCHIVE_NAME
    make_deterministic_result_zip(repo_root, result_paths, result_archive)
    result_archive_check = verify_zip_archive(result_archive, result_expected)
    extract_verified_zip(result_archive, staging / "results")

    # Governing verification occurs only after reconstructing one repository
    # tree from the two already verified archive payloads.  This proves that
    # the release is self-contained and prevents the dirty live checkout from
    # acting as the sole test authority.
    with tempfile.TemporaryDirectory(
        prefix="xmembrane-v10-reconstructed-"
    ) as reconstructed_parent_text:
        reconstructed_parent = Path(reconstructed_parent_text)
        extract_verified_zip(source_archive, reconstructed_parent)
        extract_verified_zip(result_archive, reconstructed_parent)
        reconstructed_root = reconstructed_parent / PROJECT_ARCHIVE_ROOT
        if not reconstructed_root.is_dir():
            raise PackagingError("Archive reconstruction did not create project root")
        reconstructed_report_manifest_check = verify_embedded_manifest(
            reconstructed_root,
            REPORT_MANIFEST,
            required_paths=REPORT_REQUIRED_BINDINGS,
        )
        reconstructed_capacitive_manifest_check = verify_embedded_manifest(
            reconstructed_root,
            CAPACITIVE_DIRECTORY / "source_manifest.json",
        )
        reconstructed_tw50_manifest_check = verify_embedded_manifest(
            reconstructed_root,
            TW50_DIRECTORY / "study/study_audit.json",
        )
        reconstructed_scientific_audits = verify_scientific_audits(
            reconstructed_root
        )
        reconstructed_report_check = verify_report(reconstructed_root)
        if run_tests:
            test_check = run_reconstructed_full_tests(
                reconstructed_root,
                pytest_timeout_seconds,
            )
        else:
            test_check = {
                "mode": "skipped_reconstructed_archive_check_only_preflight",
                "passed": None,
                "reason": (
                    "--skip-tests is accepted only for non-publishing preflight; "
                    "archive reconstruction and manifest checks still ran"
                ),
                "stdout": "",
                "stderr": "",
            }
    if run_tests and test_check.get("passed") is not True:
        raise PackagingError(
            "The full pytest suite failed in the reconstructed archive tree; "
            "release not published"
        )

    profile_note = """
# Supplemental membrane profile plots

The six `selected_membrane_*` files in the preserved workspace-relative
directory answer the recent requests for local humidity and through-thickness
current profiles along the membrane. They come from the selected scenario in
`direct_active_erv_transport_sensitivity_2v`, not from the combined
`t_w=50`, `D=10^-10 m2/s` V10 sensitivity case. They are explanatory profile
artifacts and are not evidence of a realistic, measured, or validated
membrane. Their generator scripts are included in the source revision.
The exact `selected_cases.csv` and `segment_register.csv.gz` inputs consumed by
those generators are included in the result archive.
"""
    write_text(staging / "results" / "PROFILE_PLOTS_NOTE.md", profile_note)

    source_inventory = [
        {
            **source_expected[f"{PROJECT_ARCHIVE_ROOT}/{relative.as_posix()}"],
            "archive_member": f"{PROJECT_ARCHIVE_ROOT}/{relative.as_posix()}",
        }
        for relative in source_paths
    ]
    result_inventory = [
        {
            **result_expected[f"{PROJECT_ARCHIVE_ROOT}/{relative.as_posix()}"],
            "archive_member": f"{PROJECT_ARCHIVE_ROOT}/{relative.as_posix()}",
        }
        for relative in result_paths
    ]
    write_json(
        staging / "environment" / "source_snapshot.json",
        {
            "schema_version": SCHEMA_VERSION,
            "snapshot_type": "complete_git_revision",
            "source_revision": git_state["source_revision"],
            "file_count": len(source_inventory),
            "files": source_inventory,
        },
    )
    write_json(
        staging / "environment" / "result_snapshot.json",
        {
            "schema_version": SCHEMA_VERSION,
            "snapshot_type": "allowlisted_working_tree_results",
            "file_count": len(result_inventory),
            "selection": result_selection,
            "files": result_inventory,
        },
    )
    runtime = {
        "created_utc": utc_now(),
        "release_id": RELEASE_ID,
        "script_version": SCRIPT_VERSION,
        "python_executable": sys.executable,
        "python_version": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "operating_system": os.name,
        "determinism_scope": (
            "Only the source and result ZIP payloads are deterministic for fixed "
            "inputs. The complete package intentionally records time-, host-, and "
            "test-run-specific evidence."
        ),
        "git": {
            key: value
            for key, value in git_state.items()
            if key != "tree"
        },
    }
    write_json(staging / "environment" / "runtime.json", runtime)
    write_text(
        staging / "environment" / "python_packages.txt",
        "# Diagnostic environment inventory; this is not a lockfile.\n"
        + "\n".join(python_package_inventory()),
    )

    write_text(
        staging / "verification" / "pytest_output.txt",
        str(test_check.get("stdout", ""))
        + ("\n--- STDERR ---\n" + str(test_check.get("stderr", "")) if test_check.get("stderr") else ""),
    )
    write_json(
        staging / "verification" / "pytest_result.json",
        {key: value for key, value in test_check.items() if key not in {"stdout", "stderr"}},
    )
    archive_checks = {
        "passed": True,
        "source": source_archive_check,
        "results": result_archive_check,
        "source_result_overlay": overlay_check,
        "result_selection": result_selection,
    }
    write_json(staging / "verification" / "archive_checks.json", archive_checks)
    write_json(
        staging / "verification" / "evidence_manifest_checks.json",
        {
            "passed": True,
            "report_source_manifest": report_manifest_check,
            "capacitive_source_manifest": capacitive_manifest_check,
            "tw50_study_audit_manifest": tw50_audit_manifest_check,
            "reconstructed_report_source_manifest": (
                reconstructed_report_manifest_check
            ),
            "reconstructed_capacitive_source_manifest": (
                reconstructed_capacitive_manifest_check
            ),
            "reconstructed_tw50_study_audit_manifest": (
                reconstructed_tw50_manifest_check
            ),
        },
    )
    write_json(
        staging / "verification" / "scientific_audit_checks.json",
        {
            "passed": True,
            "live_input_preflight": scientific_audits,
            "reconstructed_archive": reconstructed_scientific_audits,
        },
    )
    write_json(
        staging / "verification" / "report_checks.json",
        {
            "passed": True,
            "live_input_preflight": report_check,
            "reconstructed_archive": reconstructed_report_check,
        },
    )
    write_json(
        staging / "verification" / "reconstruction_checks.json",
        {
            "passed": True,
            "reconstruction_inputs": [
                f"archives/{SOURCE_ARCHIVE_NAME}",
                f"archives/{RESULT_ARCHIVE_NAME}",
            ],
            "logical_root": PROJECT_ARCHIVE_ROOT,
            "source_result_overlay": overlay_check,
            "report_manifest_reverified": True,
            "nested_scientific_manifests_reverified": True,
            "scientific_audits_reverified": True,
            "report_reverified": True,
            "governing_pytest_mode": test_check.get("mode"),
            "governing_pytest_passed": test_check.get("passed"),
        },
    )

    status = {
        "schema_version": SCHEMA_VERSION,
        "release_id": RELEASE_ID,
        "status": "PASS" if run_tests else "PREFLIGHT_ONLY",
        "publishing_eligible": bool(run_tests and test_check.get("passed") is True),
        "created_utc": utc_now(),
        "source_revision": git_state["source_revision"],
        "package_time_revision": git_state["package_time_revision"],
        "reconstructed_archive_pytest": {
            "mode": test_check.get("mode"),
            "passed": test_check.get("passed"),
            "passed_test_count": test_check.get("passed_test_count"),
            "skipped_test_count": test_check.get("skipped_test_count"),
            "failed_test_count": 0 if test_check.get("passed") is True else None,
            "skip_reasons": test_check.get("skip_reasons", []),
            "interpretation": (
                "Counts may differ from the live-workspace baseline because "
                "historical generated outputs and external sibling-repository "
                "evidence are deliberately excluded. PASS requires zero failures "
                "and complete governing V10 evidence."
            ),
        },
        "checks": {
            "required_inputs_present": True,
            "tracked_source_matches_declared_revision": git_state[
                "tracked_files_match_source_revision"
            ],
            "v10_report_pdf_and_claim_terms": True,
            "v10_report_evidence_bindings": True,
            "archive_reconstruction_report_manifest": True,
            "archive_reconstruction_nested_manifests": True,
            "capacitive_manifest_fresh": True,
            "tw50_d1e10_manifest_fresh": True,
            "scientific_audits_pass_with_claim_boundaries_closed": True,
            "source_archive_members_and_hashes": True,
            "result_archive_members_and_hashes": True,
            "package_manifest_inventory": True,
            "package_sha256sums": True,
            "reconstructed_archive_full_pytest": test_check.get("passed"),
        },
        "publication_control_note": (
            "The packager writes and independently re-verifies MANIFEST.json and "
            "SHA256SUMS after this status record is written; any failure prevents "
            "atomic publication."
        ),
        "legacy_final_delivery_checker_v1": {
            "used_as_v10_authority": False,
            "reason": (
                "Historical checker v1 is tied to stale 2026-08-31 report and "
                "nested manifests and does not cover the September evidence."
            ),
        },
    }
    write_json(staging / "verification" / "V10_STATUS.json", status)

    manifest_files = package_inventory(
        staging,
        exclude={"MANIFEST.json", "SHA256SUMS"},
    )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "release_id": RELEASE_ID,
        "script_version": SCRIPT_VERSION,
        "created_utc": utc_now(),
        "hash_algorithm": "sha256",
        "source_snapshot": {
            "type": "complete_git_revision",
            "source_revision": git_state["source_revision"],
            "tracked_file_count": len(source_paths),
            "archive": f"archives/{SOURCE_ARCHIVE_NAME}",
            "untracked_files_included": False,
        },
        "package_execution": {
            "package_time_revision": git_state["package_time_revision"],
            "source_and_package_time_revision_match": git_state[
                "source_and_package_time_revision_match"
            ],
            "release_artifact_revision": None,
            "note": git_state["release_artifact_revision_note"],
        },
        "result_snapshot": {
            "type": "manifest_derived_plus_explicit_allowlist",
            "file_count": len(result_paths),
            "archive": f"archives/{RESULT_ARCHIVE_NAME}",
            "selection": result_selection,
        },
        "reconstructed_verification": {
            "source_and_result_archives_overlaid": True,
            "report_manifest_reverified": True,
            "nested_scientific_manifests_reverified": True,
            "governing_full_pytest_passed": test_check.get("passed"),
        },
        "determinism_scope": (
            "Source and result ZIP payloads are deterministic for fixed inputs; "
            "the complete package is intentionally time-, host-, and test-run-specific."
        ),
        "claim_boundary": (
            "Model phase closeout only; no existing membrane, sustained electrode "
            "mechanism, complete module, commercial performance, or measured net "
            "system-energy saving is validated."
        ),
        "verification_authority": "verification/V10_STATUS.json",
        "files": manifest_files,
    }
    write_json(staging / "MANIFEST.json", manifest)
    manifest_check = verify_package_manifest(staging)
    checksum_check = write_and_verify_sha256sums(staging)
    return {
        "status": status["status"],
        "publishing_eligible": status["publishing_eligible"],
        "source_revision": git_state["source_revision"],
        "package_time_revision": git_state["package_time_revision"],
        "source_file_count": len(source_paths),
        "result_file_count": len(result_paths),
        "package_manifest_file_count": manifest_check["checked_file_count"],
        "sha256sum_file_count": checksum_check["checked_file_count"],
        "source_archive_sha256": source_archive_check["sha256"],
        "result_archive_sha256": result_archive_check["sha256"],
        "reconstructed_pytest_passed_count": test_check.get("passed_test_count"),
        "reconstructed_pytest_skipped_count": test_check.get("skipped_test_count"),
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=DEFAULT_REPO_ROOT,
        help="Git repository root (default: inferred from this script).",
    )
    parser.add_argument(
        "--release-dir",
        type=Path,
        default=None,
        help="Output directory (default: deliverables/current/2026-09-02_v10).",
    )
    parser.add_argument(
        "--expected-source-revision",
        help=(
            "Expected curated source/report commit. Mandatory for publication; "
            "must resolve to current HEAD."
        ),
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Build and verify in temporary storage without publishing.",
    )
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Skip pytest only for a non-publishing --check-only preflight.",
    )
    parser.add_argument(
        "--allow-dirty-tracked",
        action="store_true",
        help="Allow tracked drift only for development --check-only runs.",
    )
    parser.add_argument(
        "--pytest-timeout-seconds",
        type=int,
        default=1800,
        help="Timeout for pytest in the reconstructed archive tree (default: 1800).",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = args.repo_root.resolve()
    release_dir = (
        args.release_dir.resolve()
        if args.release_dir is not None
        else repo_root / DEFAULT_RELEASE_RELATIVE
    )
    if args.skip_tests and not args.check_only:
        raise PackagingError("--skip-tests requires --check-only")
    if args.allow_dirty_tracked and not args.check_only:
        raise PackagingError("--allow-dirty-tracked requires --check-only")
    if args.pytest_timeout_seconds <= 0:
        raise PackagingError("--pytest-timeout-seconds must be positive")
    ensure_repo_root(repo_root)

    git_state = validate_source_revision(
        repo_root,
        expected_revision=args.expected_source_revision,
        allow_dirty_tracked=args.allow_dirty_tracked,
        publishing=not args.check_only,
    )
    release_parent = release_dir.parent
    release_parent.mkdir(parents=True, exist_ok=True)
    staging_parent = Path(tempfile.mkdtemp(prefix="xmembrane-v10-stage-"))
    staging = staging_parent / release_dir.name
    published = False
    try:
        summary = build_staging(
            repo_root,
            staging,
            git_state=git_state,
            run_tests=not args.skip_tests,
            pytest_timeout_seconds=args.pytest_timeout_seconds,
        )
        if args.check_only:
            print(json.dumps({"mode": "check_only", **summary}, indent=2))
        else:
            if not summary["publishing_eligible"]:
                raise PackagingError("Staged package is not publishing-eligible")
            # Move staging onto the repository filesystem before atomic replace.
            local_stage = Path(
                tempfile.mkdtemp(
                    prefix=f".{release_dir.name}.stage-",
                    dir=release_parent,
                )
            )
            local_stage.rmdir()
            shutil.copytree(staging, local_stage, symlinks=True)
            normalize_release_modes(
                local_stage,
                git_state["tree"],
            )
            verify_package_manifest(local_stage)
            verify_sha256sums(local_stage)
            release_mode_check = publish_atomically(
                local_stage,
                release_dir,
                source_tree=git_state["tree"],
            )
            published = True
            final_checksum_check = verify_sha256sums(release_dir)
            final_manifest_check = verify_package_manifest(release_dir)
            print(
                json.dumps(
                    {
                        "mode": "published",
                        "release_dir": str(release_dir),
                        **summary,
                        "post_publish_release_modes": release_mode_check,
                        "post_publish_manifest_check": final_manifest_check,
                        "post_publish_checksum_check": final_checksum_check,
                    },
                    indent=2,
                )
            )
    finally:
        if staging_parent.exists():
            shutil.rmtree(staging_parent)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PackagingError as exc:
        print(f"V10 packaging failed: {exc}", file=sys.stderr)
        raise SystemExit(2)
