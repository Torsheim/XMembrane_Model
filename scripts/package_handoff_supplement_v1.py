#!/usr/bin/env python3
"""Build and verify the post-V10 handoff supplement.

The payload inventory is deliberately allowlisted.  Manifest metadata contains
no build timestamp, so identical input bytes produce identical MANIFEST.json
and SHA256SUMS files.  Presentation generators themselves may embed
tool-specific metadata; the checksums bind the bytes that were actually
reviewed and transferred.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import unicodedata
import zipfile
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "deliverables/current/2026-09-03_handoff_v1"
V10_STATUS = ROOT / "deliverables/current/2026-09-02_v10/verification/V10_STATUS.json"
V10_REPORT = (
    ROOT
    / "deliverables/current/2026-09-02_v10/reports/"
    "HeiQ_XMembrane_Final_Project_Closeout_2026-09-02_v10.pdf"
)
V9_ARCHIVE = ROOT / "deliverables/archive/2026-09-02_v9_presentations"

DECK_STEM = "HeiQ_XMembrane_Technical_Model_Peer_Review_V10_2026-09-03"
HTML_NAME = "HeiQ_XMembrane_Model_Explainer_V10_2026-09-03.html"

PRESENTATION_PAYLOAD: dict[str, str] = {
    "README.md": "handoff_guide",
    "PRESENTATION_BUILD.md": "presentation_build_record",
    f"presentations/{DECK_STEM}.pptx": "current_v10_peer_review_deck",
    f"presentations/{DECK_STEM}.pdf": "current_v10_peer_review_pdf",
    f"presentations/{HTML_NAME}": "current_v10_interactive_explainer",
    "figures/model_review/00_simulated_system_setup.png": "presentation_figure",
    "figures/model_review/00_simulated_system_setup.svg": "presentation_figure_source",
    "figures/model_review/01_model_hierarchy.png": "presentation_figure",
    "figures/model_review/01_model_hierarchy.svg": "presentation_figure_source",
    "figures/model_review/02_local_membrane_control_volume.png": "presentation_figure",
    "figures/model_review/02_local_membrane_control_volume.svg": "presentation_figure_source",
    "figures/model_review/03_voltage_to_current_algorithm.png": "presentation_figure",
    "figures/model_review/03_voltage_to_current_algorithm.svg": "presentation_figure_source",
    "figures/model_review/04_two_integration_paths.png": "presentation_figure",
    "figures/model_review/04_two_integration_paths.svg": "presentation_figure_source",
    "figures/model_review/05_countercurrent_state_evolution.png": "presentation_figure",
    "figures/model_review/05_countercurrent_state_evolution.svg": "presentation_figure_source",
    "figures/model_review/06_evidence_ladder.png": "presentation_figure",
    "figures/model_review/06_evidence_ladder.svg": "presentation_figure_source",
    "figures/model_review/07_electrode_transient_boundary.png": "presentation_figure",
    "figures/model_review/07_electrode_transient_boundary.svg": "presentation_figure_source",
    "figures/model_review/contact_sheet.png": "presentation_figure_contact_sheet",
}

TEST_CELL_SOURCE = ROOT / "reports/test_cell_handoff_supplement_2026-09-03"
TEST_CELL_COPIES: dict[str, tuple[str, str]] = {
    "test_cell/README.md": ("README.md", "test_cell_authoritative_guide"),
    "test_cell/HeiQ_Integrated_EO_Vapour_Test_Cell_Handoff_2026-09-03_v1.docx": (
        "HeiQ_Integrated_EO_Vapour_Test_Cell_Handoff_2026-09-03_v1.docx",
        "test_cell_handoff_document",
    ),
    "test_cell/calculations/SUMMARY.md": ("calculations/SUMMARY.md", "test_cell_calculation_summary"),
    "test_cell/calculations/audit.json": ("calculations/audit.json", "test_cell_audit"),
    "test_cell/calculations/config_used.json": ("calculations/config_used.json", "test_cell_configuration"),
    "test_cell/calculations/integrated_sealed_cell_engineering_register.csv": (
        "calculations/integrated_sealed_cell_engineering_register.csv",
        "test_cell_engineering_release_gates",
    ),
    "test_cell/calculations/integrated_sealed_cell_transient.csv": (
        "calculations/integrated_sealed_cell_transient.csv",
        "test_cell_transient_register",
    ),
    "test_cell/calculations/integrated_sealed_cell_transient.png": (
        "calculations/integrated_sealed_cell_transient.png",
        "test_cell_transient_figure",
    ),
    "test_cell/calculations/integrated_sealed_cell_volume_basis.csv": (
        "calculations/integrated_sealed_cell_volume_basis.csv",
        "test_cell_volume_basis",
    ),
    "test_cell/calculations/interconnect_header_port_volume_budget.csv": (
        "calculations/interconnect_header_port_volume_budget.csv",
        "test_cell_interconnect_volume_budget",
    ),
    "test_cell/calculations/source_manifest.json": (
        "calculations/source_manifest.json",
        "test_cell_source_manifest",
    ),
    "test_cell/figures/eo_vapour_integrated_two_chamber_dimensioned_views.pdf": (
        "figures/eo_vapour_integrated_two_chamber_dimensioned_views.pdf",
        "test_cell_dimensioned_drawing",
    ),
    "test_cell/figures/eo_vapour_integrated_two_chamber_dimensioned_views.png": (
        "figures/eo_vapour_integrated_two_chamber_dimensioned_views.png",
        "test_cell_dimensioned_drawing_preview",
    ),
    "test_cell/figures/eo_vapour_integrated_two_chamber_dimensioned_views.tex": (
        "figures/eo_vapour_integrated_two_chamber_dimensioned_views.tex",
        "test_cell_dimensioned_drawing_source",
    ),
    "test_cell/figures/eo_vapour_integrated_two_chamber_exterior_render.png": (
        "figures/eo_vapour_integrated_two_chamber_exterior_render.png",
        "test_cell_exterior_concept_render",
    ),
}

BUILD_INPUTS = (
    "constraints/v10-python-3.10.txt",
    "deliverables/build_peer_review_figures.py",
    "deliverables/build_simulated_system_setup.py",
    "deliverables/build_xmembrane_peer_review_deck.js",
    "package-lock.json",
    "package.json",
    "requirements-docs-presentations.txt",
    "config/eo_vapor_test_cell_design.json",
    "docs/EO_VAPOR_TEST_CELL_DESIGN.md",
    "scripts/design_eo_vapor_test_cell.py",
    "scripts/package_handoff_supplement_v1.py",
    "tests/test_eo_vapor_test_cell_design.py",
)

LOCAL_SCRATCH_PREFIXES = ("presentations/rendered/",)
CONTROL_FILES = {"MANIFEST.json", "SHA256SUMS"}


class PackagingError(RuntimeError):
    """Fail-closed handoff packaging error."""


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    value = value.replace("−", "-").replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", value).strip()


def html_visible_text(path: Path) -> str:
    parser = _VisibleText()
    parser.feed(path.read_text(encoding="utf-8"))
    return canonical_text(" ".join(parser.parts))


def pptx_visible_text(path: Path) -> tuple[str, int]:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        slides = sorted(
            name
            for name in names
            if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
        )
        if "ppt/presentation.xml" not in names or len(slides) != 31:
            raise PackagingError(f"Unexpected PPTX structure or slide count: {path}")
        parts: list[str] = []
        for name in slides:
            root = ElementTree.fromstring(archive.read(name))
            parts.extend(node.text or "" for node in root.iter() if node.tag.endswith("}t"))
    return canonical_text(" ".join(parts)), len(slides)


def pdf_visible_text(path: Path) -> tuple[str, int]:
    pdftotext = shutil.which("pdftotext")
    pdfinfo = shutil.which("pdfinfo")
    if pdftotext is None or pdfinfo is None:
        raise PackagingError("Poppler pdftotext and pdfinfo are required for the claim gate")
    if not path.read_bytes()[:5] == b"%PDF-":
        raise PackagingError(f"Invalid PDF signature: {path}")
    info = subprocess.run(
        [pdfinfo, str(path)], check=True, text=True, capture_output=True
    ).stdout
    match = re.search(r"^Pages:\s+(\d+)\s*$", info, re.MULTILINE)
    if match is None:
        raise PackagingError(f"Could not read PDF page count: {path}")
    text = subprocess.run(
        [pdftotext, "-layout", str(path), "-"],
        check=True,
        text=True,
        capture_output=True,
    ).stdout
    return canonical_text(text), int(match.group(1))


REQUIRED_CLAIM_GROUPS: tuple[tuple[str, ...], ...] = (
    ("model phase complete",),
    ("technology not validated",),
    ("direct eo inside the erv", "eo function is embedded in the erv"),
    ("0.025 v",),
    ("16.2%",),
    ("0.68%",),
    ("1.8 v",),
    ("98.5%",),
    ("4.6%",),
    ("upper bound",),
    ("blocking",),
    ("tw = 50", "t w = 50"),
    ("4/8", "4 / 8"),
    ("0/8", "0 / 8"),
    ("sustained duty", "sustained-duty", "sustained performance"),
)


def require_claims(label: str, text: str) -> None:
    missing = [
        " | ".join(group)
        for group in REQUIRED_CLAIM_GROUPS
        if not any(canonical_text(term) in text for term in group)
    ]
    if missing:
        raise PackagingError(f"{label} is missing V10 claim terms: {missing}")
    if "selected v9 interpretation" in text:
        raise PackagingError(f"{label} retains the superseded selected-V9 wording")
    upper_indices = [match.start() for match in re.finditer("upper bound", text)]
    for metric in ("98.5%", "4.6%"):
        metric_indices = [match.start() for match in re.finditer(re.escape(metric), text)]
        locally_bound = any(
            abs(metric_index - upper_index) <= 500
            for metric_index in metric_indices
            for upper_index in upper_indices
        )
        if not locally_bound:
            raise PackagingError(f"{label} does not bind {metric} locally to upper-bound wording")


def validate_governing_v10() -> str:
    if not V10_STATUS.is_file() or not V10_REPORT.is_file():
        raise PackagingError("The governing V10 status or report is missing")
    status = json.loads(V10_STATUS.read_text(encoding="utf-8"))
    if status.get("status") != "PASS" or not status.get("publishing_eligible"):
        raise PackagingError("The governing V10 release is not PASS/publishing eligible")
    revision = status.get("source_revision")
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise PackagingError("The governing V10 source revision is malformed")
    return revision


def validate_presentation_claims(release: Path) -> dict[str, int]:
    source_text = canonical_text(
        (ROOT / "deliverables/build_xmembrane_peer_review_deck.js").read_text(encoding="utf-8")
    )
    figure_text = canonical_text(
        (ROOT / "deliverables/build_peer_review_figures.py").read_text(encoding="utf-8")
    )
    html_text = html_visible_text(release / "presentations" / HTML_NAME)
    pptx_text, slide_count = pptx_visible_text(
        release / "presentations" / f"{DECK_STEM}.pptx"
    )
    pdf_text, page_count = pdf_visible_text(
        release / "presentations" / f"{DECK_STEM}.pdf"
    )
    require_claims("deck source", source_text)
    require_claims("generated PPTX", pptx_text)
    require_claims("generated PDF", pdf_text)
    require_claims("HTML explainer", html_text)
    for label, text in (("figure source", figure_text),):
        for phrase in ("original 0.025 v limit", "16.2%", "0.68%", "1.8 v upper bound", "98.5%", "4.6%"):
            if phrase not in text:
                raise PackagingError(f"{label} is missing {phrase!r}")
    if page_count != slide_count:
        raise PackagingError(f"PPTX/PDF page mismatch: {slide_count} != {page_count}")
    return {"pptx_slides": slide_count, "pdf_pages": page_count}


def validate_v9_archive() -> None:
    required = (
        "README.md",
        "build_xmembrane_model_deck.js",
        "build_xmembrane_peer_review_deck_v9.js",
        "HeiQ_XMembrane_Coupled_Model_English_2026-09-02.pptx",
        "HeiQ_XMembrane_Coupled_Model_English_2026-09-02.pdf",
        "HeiQ_XMembrane_Technical_Model_Peer_Review_English_2026-09-02.pptx",
        "HeiQ_XMembrane_Technical_Model_Peer_Review_English_2026-09-02.pdf",
        "heiq-model-explainer.html",
        "heiq-model-explainer-preview.html",
    )
    missing = [name for name in required if not (V9_ARCHIVE / name).is_file()]
    if missing:
        raise PackagingError(f"Archived V9 presentation record is incomplete: {missing}")
    note = canonical_text((V9_ARCHIVE / "README.md").read_text(encoding="utf-8"))
    for phrase in ("histor", "version 9", "superseded", "do not use"):
        if phrase not in note:
            raise PackagingError(f"V9 archive README is missing {phrase!r}")


def expected_payload() -> dict[str, str]:
    payload = dict(PRESENTATION_PAYLOAD)
    payload.update({destination: role for destination, (_, role) in TEST_CELL_COPIES.items()})
    return payload


def copy_test_cell_payload(release: Path) -> None:
    for destination, (source_relative, _) in TEST_CELL_COPIES.items():
        source = TEST_CELL_SOURCE / source_relative
        if not source.is_file():
            raise PackagingError(f"Missing authoritative test-cell payload: {source}")
        target = release / destination
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def validate_test_cell_payload(release: Path) -> None:
    for destination, (source_relative, _) in TEST_CELL_COPIES.items():
        source = TEST_CELL_SOURCE / source_relative
        target = release / destination
        if not source.is_file() or not target.is_file() or sha256(source) != sha256(target):
            raise PackagingError(f"Test-cell handoff copy is absent or stale: {destination}")
    audit = json.loads((release / "test_cell/calculations/audit.json").read_text(encoding="utf-8"))
    checks = audit.get("checks")
    release_status = canonical_text(str(audit.get("release_status", "")))
    if (
        audit.get("all_pass") is not True
        or not isinstance(checks, dict)
        or len(checks) != 13
        or not all(value is True for value in checks.values())
    ):
        raise PackagingError("Test-cell audit does not pass all 13 declared checks")
    if "not released for fabrication" not in release_status:
        raise PackagingError("Test-cell audit does not preserve the blocked fabrication status")

    manifest_path = release / "test_cell/calculations/source_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    outputs = manifest.get("generated_outputs")
    sources = manifest.get("sources")
    verification = manifest.get("verification")
    if (
        not isinstance(outputs, list)
        or len(outputs) != 8
        or not isinstance(sources, list)
        or len(sources) != 2
        or not isinstance(verification, dict)
        or verification.get("audit_all_pass") is not True
        or verification.get("manifest_self_excluded_to_avoid_recursive_hash") is not True
    ):
        raise PackagingError("Test-cell nested manifest has an unexpected structure")
    calculation_root = manifest_path.parent
    for record in outputs:
        relative = record.get("path")
        if not isinstance(relative, str):
            raise PackagingError("Malformed test-cell output manifest record")
        pure = PurePosixPath(relative)
        if pure.is_absolute() or ".." in pure.parts or len(pure.parts) != 1:
            raise PackagingError(f"Unsafe test-cell output manifest path: {relative}")
        path = calculation_root / relative
        if (
            not path.is_file()
            or record.get("sha256") != sha256(path)
            or record.get("size_bytes") != path.stat().st_size
        ):
            raise PackagingError(f"Stale test-cell nested output manifest: {relative}")
    for record in sources:
        relative = record.get("path")
        if not isinstance(relative, str):
            raise PackagingError("Malformed test-cell source manifest record")
        pure = PurePosixPath(relative)
        if pure.is_absolute() or ".." in pure.parts:
            raise PackagingError(f"Unsafe test-cell source manifest path: {relative}")
        path = ROOT / relative
        if not path.is_file() or record.get("sha256") != sha256(path):
            raise PackagingError(f"Stale test-cell nested source manifest: {relative}")


def source_bindings() -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for relative in BUILD_INPUTS:
        path = ROOT / relative
        if not path.is_file():
            raise PackagingError(f"Missing build input: {relative}")
        records.append(
            {"path": relative, "bytes": path.stat().st_size, "sha256": sha256(path)}
        )
    return records


def file_record(release: Path, relative: str, role: str) -> dict[str, object]:
    path = release / relative
    if not path.is_file() or path.is_symlink():
        raise PackagingError(f"Missing or unsafe payload file: {relative}")
    return {
        "path": relative,
        "role": role,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "mode": "0644",
    }


def unexpected_files(release: Path) -> list[str]:
    expected = set(expected_payload()) | CONTROL_FILES
    unexpected: list[str] = []
    for path in sorted(release.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(release).as_posix()
        if relative in expected or any(relative.startswith(prefix) for prefix in LOCAL_SCRATCH_PREFIXES):
            continue
        unexpected.append(relative)
    return unexpected


def normalize_modes(release: Path) -> None:
    for relative in set(expected_payload()) | CONTROL_FILES:
        path = release / relative
        if path.exists():
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)


def manifest_document(release: Path, v10_revision: str, dimensions: dict[str, int]) -> dict[str, object]:
    files = [
        file_record(release, relative, role)
        for relative, role in sorted(expected_payload().items())
    ]
    return {
        "schema_version": 1,
        "release_id": "XMEMBRANE-2026-09-03-HANDOFF-V1",
        "authority": "post-V10 supplemental handoff; controlled V10 remains governing",
        "governing_v10_release": "XMEMBRANE-2026-09-02-V10",
        "governing_v10_source_revision": v10_revision,
        "determinism_scope": (
            "MANIFEST.json and SHA256SUMS are byte-deterministic for identical allowlisted "
            "payload and build-input bytes; the presentation/PDF generators may vary across tools"
        ),
        "excluded_local_scratch": list(LOCAL_SCRATCH_PREFIXES),
        "presentation_structure": dimensions,
        "source_bindings": source_bindings(),
        "files": files,
    }


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def write_control_files(release: Path, manifest: dict[str, object]) -> None:
    manifest_path = release / "MANIFEST.json"
    write_text(manifest_path, json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    checksum_paths = sorted(expected_payload()) + ["MANIFEST.json"]
    lines = [f"{sha256(release / relative)}  {relative}" for relative in checksum_paths]
    write_text(release / "SHA256SUMS", "\n".join(lines) + "\n")


def verify_control_files(release: Path, expected_manifest: dict[str, object]) -> None:
    manifest_path = release / "MANIFEST.json"
    checksum_path = release / "SHA256SUMS"
    if not manifest_path.is_file() or not checksum_path.is_file():
        raise PackagingError("MANIFEST.json or SHA256SUMS is missing")
    actual_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if actual_manifest != expected_manifest:
        raise PackagingError("MANIFEST.json is stale or does not match the allowlisted payload")
    entries: dict[str, str] = {}
    for line in checksum_path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([^\n]+)", line)
        if match is None:
            raise PackagingError(f"Malformed SHA256SUMS line: {line!r}")
        digest, relative = match.groups()
        pure = PurePosixPath(relative)
        if pure.is_absolute() or ".." in pure.parts or relative in entries:
            raise PackagingError(f"Unsafe or duplicate checksum path: {relative}")
        entries[relative] = digest
    expected_paths = set(expected_payload()) | {"MANIFEST.json"}
    if set(entries) != expected_paths:
        raise PackagingError("SHA256SUMS file set does not match the allowlist")
    for relative, digest in entries.items():
        if sha256(release / relative) != digest:
            raise PackagingError(f"SHA256SUMS mismatch: {relative}")
    for relative in set(expected_payload()) | CONTROL_FILES:
        mode = stat.S_IMODE((release / relative).stat().st_mode)
        if mode != 0o644:
            raise PackagingError(f"Non-portable file mode {mode:o}: {relative}")


def run(check_only: bool = False, release: Path = RELEASE) -> dict[str, object]:
    v10_revision = validate_governing_v10()
    validate_v9_archive()
    if check_only:
        validate_test_cell_payload(release)
    else:
        copy_test_cell_payload(release)
    extra = unexpected_files(release)
    if extra:
        raise PackagingError(f"Unexpected handoff payload files: {extra}")
    dimensions = validate_presentation_claims(release)
    validate_test_cell_payload(release)
    if not check_only:
        normalize_modes(release)
    manifest = manifest_document(release, v10_revision, dimensions)
    if check_only:
        verify_control_files(release, manifest)
    else:
        write_control_files(release, manifest)
        normalize_modes(release)
        verify_control_files(release, manifest)
    return {
        "status": "PASS",
        "release_id": manifest["release_id"],
        "payload_files": len(expected_payload()),
        "checksum_entries": len(expected_payload()) + 1,
        **dimensions,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true", help="verify without writing")
    args = parser.parse_args()
    try:
        result = run(check_only=args.check_only)
    except (OSError, ValueError, json.JSONDecodeError, zipfile.BadZipFile, PackagingError, subprocess.CalledProcessError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
