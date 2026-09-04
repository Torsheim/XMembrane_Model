#!/usr/bin/env python3
"""Build the controlled HeiQ XMembrane Version 9 delivery package.

The release is deliberately allow-listed. Historical reports and post-ERV EO
artifacts are not copied into the current package.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path


WORKSPACE = Path(__file__).resolve().parents[1]
DELIVERABLES = WORKSPACE / "deliverables"
RELEASE = DELIVERABLES / "current" / "2026-08-31_v9"

MAIN_STEM = "HeiQ_XMembrane_Final_Result_and_Decision_Report_2026-08-31_v9"
WEEKLY_STEM = "HeiQ_XMembrane_Weekly_Findings_2026-08-24_to_2026-08-30_Rev4"
CLOSURE_STEM = "HeiQ_XMembrane_Model_Closure_and_Material_Handoff_2026-08-31_Rev2"
CELL_STEM = "HeiQ_EO_Vapour_Cell_Boundary_Conditions_and_Sizing_2026-08-31_v2"

REPORTS = {
    f"{MAIN_STEM}.pdf": WORKSPACE / "reports/final_team_decision_report_2026-08-31" / f"{MAIN_STEM}.pdf",
    f"{WEEKLY_STEM}.pdf": WORKSPACE / "reports/weekly_findings_2026-08-24_to_2026-08-30" / f"{WEEKLY_STEM}.pdf",
    f"{CLOSURE_STEM}.pdf": WORKSPACE / "reports/model_closure_and_material_handoff_2026-08-31_rev2" / f"{CLOSURE_STEM}.pdf",
    f"{CELL_STEM}.pdf": WORKSPACE / "reports/eo_vapor_boundary_analysis_v2_en" / f"{CELL_STEM}.pdf",
}

SOURCE_FILES = [
    WORKSPACE / "reports/final_team_decision_report_2026-08-31" / f"{MAIN_STEM}.tex",
    WORKSPACE / "reports/weekly_findings_2026-08-24_to_2026-08-30" / "HeiQ_XMembrane_Weekly_Findings_2026-08-24_to_2026-08-30_Rev1.tex",
    WORKSPACE / "reports/model_closure_and_material_handoff_2026-08-31_rev2" / f"{CLOSURE_STEM}.tex",
    WORKSPACE / "reports/eo_vapor_boundary_analysis_v2_en" / f"{CELL_STEM}.tex",
    WORKSPACE / "scripts/plot_direct_eo_erv_energy_area_tradeoffs_v2.py",
    WORKSPACE / "scripts/analyze_direct_eo_erv_cases_below_9000_m2_v1.py",
    WORKSPACE / "scripts/run_direct_eo_erv_study_v1.py",
    WORKSPACE / "scripts/design_eo_vapor_test_cell.py",
    WORKSPACE / "scripts/analyze_eo_vapor_boundaries_v1.py",
    WORKSPACE / "scripts/make_integrated_direct_eo_erv_weather_v1.py",
    WORKSPACE / "scripts/make_integrated_evidence_register_v1.py",
    WORKSPACE / "scripts/package_final_release_v9.py",
]

SOURCE_DIRS = [
    WORKSPACE / "reports/weekly_findings_2026-08-24_to_2026-08-30/figures",
]

RESULT_DIRS = [
    WORKSPACE / "outputs/integrated_erv_eo_opportunity_plots_v2",
    WORKSPACE / "outputs/integrated_erv_eo_under_9000_v1",
    WORKSPACE / "outputs/direct_active_eo_erv_study_v1/study",
    WORKSPACE / "outputs/eo_vapor_cell_sizing_v1",
    WORKSPACE / "outputs/eo_vapor_boundary_analysis_v1",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_file(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def copy_tree(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise FileNotFoundError(source)
    shutil.copytree(source, destination, dirs_exist_ok=True)


def workspace_relative(path: Path) -> Path:
    return path.relative_to(WORKSPACE)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def make_zip(source_dir: Path, archive: Path) -> None:
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for path in sorted(source_dir.rglob("*")):
            if path.is_file():
                bundle.write(path, path.relative_to(source_dir.parent))


def pdf_text(path: Path) -> str:
    completed = subprocess.run(
        ["pdftotext", "-layout", str(path), "-"],
        check=True,
        text=True,
        capture_output=True,
    )
    return completed.stdout


def pdf_pages(path: Path) -> int:
    completed = subprocess.run(
        ["pdfinfo", str(path)],
        check=True,
        text=True,
        capture_output=True,
    )
    for line in completed.stdout.splitlines():
        if line.startswith("Pages:"):
            return int(line.split(":", 1)[1].strip())
    raise RuntimeError(f"No page count for {path}")


def build_release(staging: Path) -> None:
    reports_dir = staging / "reports"
    source_root = staging / "source" / "XMembrane_Trond_Study"
    results_root = staging / "results" / "XMembrane_Trond_Study"
    verification_dir = staging / "verification"
    archives_dir = staging / "archives"

    for name, source in REPORTS.items():
        copy_file(source, reports_dir / name)

    for source in SOURCE_FILES:
        relative = workspace_relative(source)
        destination = source_root / relative
        if source.name == "HeiQ_XMembrane_Weekly_Findings_2026-08-24_to_2026-08-30_Rev1.tex":
            destination = destination.with_name(f"{WEEKLY_STEM}.tex")
        copy_file(source, destination)

    for source in SOURCE_DIRS:
        copy_tree(source, source_root / workspace_relative(source))

    for source in RESULT_DIRS:
        relative = workspace_relative(source)
        copy_tree(source, results_root / relative)
        # Plot inputs are included under source as well, preserving the report
        # source's ../../outputs relative path for reproducible LaTeX builds.
        copy_tree(source, source_root / relative)

    index_source = DELIVERABLES / "CURRENT_ENGLISH_REPORTS_2026-08-31.md"
    copy_file(index_source, staging / index_source.name)

    readme = f"""
# HeiQ XMembrane — controlled final delivery, Version 9

This is the only package intended for current delivery. The governing report
is `reports/{MAIN_STEM}.pdf`. EO is modelled only inside the ERV
membrane/core; no downstream or post-ERV EO module belongs to the selected
architecture.

## Final report set

1. **Final result and decision report.** This report fixes the matched service
   and comparator discipline, establishes the passive ERV baseline, selects
   the under-9,000-m² integrated O30 point and calculates its 51.955-Wh/kg
   architecture-specific break-even. It concludes that the 125.340-kW
   incremental window justifies testing but is not a validated net saving.
2. **Weekly findings, Revision 4.** This is the final evidence chronology. It
   contains the corrected AC, AC+ERV and integrated AC+ERV+EO comparisons,
   pairwise reductions, under-area frontier, full-duty screen and explanation
   of O50 and O30 as intermediate humidity coordinates.
3. **Model closure and material handoff, Revision 2.** This explains what the
   model has actually resolved: architecture, signs, comparators, area and
   break-even. It shows why material choice requires a coupled same-sample
   property vector and states that a Yaroshchuk-type asymmetric constitutive
   model has not yet been validated or implemented.
4. **EO vapour-cell boundary conditions and sizing, Version 2.** This defines a
   50×50-mm active aperture, 25-cm² membrane area, nominal 2-mm gaps, 6-L/min
   actual flow per side and the controls needed to separate EO transport from
   humidity, pressure, leakage, edge and structural errors.

## Final project summary

The strongest established model result is passive recovery: AC power falls
from 1,166.400 kW to 543.741 kW with the matched passive ERV. Passive ERV
already passes O50. For EO integrated in the ERV, O30 is the best current
under-area coordinate at 5,899 m² and 418.400 kW known subtotal, leaving a
conditional 125.340-kW (23.05%) window versus the same ERV with EO off. Full
EO humidity removal does not fit the 9,000-m² gate. The project is therefore
ready for controlled coupon evidence generation and full subsystem-loss
closure, but not for a measured net-energy or commercial-material claim.

## Package layout

- `reports/`: the four controlled English PDFs.
- `source/`: LaTeX, analysis code and report inputs in workspace-relative form.
- `results/`: selected raw result registers, plots, configurations and audits.
- `archives/`: portable source and result ZIP archives.
- `verification/`: extracted-text assertions and page counts.
- `MANIFEST.json` and `SHA256SUMS`: immutable file inventory and checksums.

Historical Version 8/8.1 and Weekly Revisions 1–3 are intentionally excluded.
"""
    write_text(staging / "README.md", readme)

    release_notes = """
# Version 9 release notes

- Replaced the earlier leading post-ERV EO interpretation with EO integrated
  only in the ERV membrane/core.
- Rebuilt the governing report around matched equal-service comparators.
- Corrected O50: passive ERV already reaches below O50, so matched EO duty is
  zero at that coordinate.
- Selected the best screened O30 point below 9,000 m²: 5,899 m², 1.00 V and
  418.400 kW known subtotal.
- Replaced the assumed 180-Wh/kg shorthand with a calculated O30 break-even of
  51.955 Wh/kg.
- Added the under-9,000-m² frontier and separated EO-specific saving from the
  total difference to AC only.
- Added the full-duty area rejection and a corrected model-closure report.
- Preserved the centimetre-scale vapour-cell design and boundary-condition
  controls as the experimental continuation route.
"""
    write_text(staging / "RELEASE_NOTES.md", release_notes)

    required = {
        f"reports/{MAIN_STEM}.pdf": [
            "EO integrated only in the ERV membrane/core",
            "125.340",
            "51.955",
            "17,253",
        ],
        f"reports/{WEEKLY_STEM}.pdf": [
            "EO is integrated directly inside that ERV membrane/core",
            "125.340",
            "52.0 Wh/kg",
        ],
        f"reports/{CLOSURE_STEM}.pdf": [
            "Closure in one sentence",
            "125.340",
            "51.955",
            "Yaroshchuk-type asymmetry",
        ],
        f"reports/{CELL_STEM}.pdf": [
            "Maximum membrane aperture",
            "6 actual L/min per side",
        ],
    }
    checks: dict[str, object] = {
        "release": "2026-08-31_v9",
        "passed": True,
        "reports": {},
    }
    for relative, phrases in required.items():
        path = staging / relative
        text = pdf_text(path)
        phrase_results = {phrase: phrase in text for phrase in phrases}
        passed = all(phrase_results.values())
        checks["reports"][relative] = {
            "pages": pdf_pages(path),
            "required_phrases": phrase_results,
            "passed": passed,
        }
        checks["passed"] = bool(checks["passed"] and passed)
    write_text(
        verification_dir / "report_text_and_page_checks.json",
        json.dumps(checks, indent=2, ensure_ascii=False),
    )
    if not checks["passed"]:
        raise RuntimeError("One or more report text assertions failed")

    archives_dir.mkdir(parents=True, exist_ok=True)
    make_zip(staging / "source", archives_dir / "HeiQ_XMembrane_2026-08-31_v9_source.zip")
    make_zip(staging / "results", archives_dir / "HeiQ_XMembrane_2026-08-31_v9_results.zip")

    entries = []
    for path in sorted(staging.rglob("*")):
        if path.is_file() and path.name not in {"MANIFEST.json", "SHA256SUMS"}:
            relative = path.relative_to(staging).as_posix()
            entries.append(
                {
                    "path": relative,
                    "bytes": path.stat().st_size,
                    "sha256": sha256(path),
                }
            )
    manifest = {
        "release_id": "2026-08-31_v9",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "governing_report": f"reports/{MAIN_STEM}.pdf",
        "architecture_rule": "EO is integrated only in the ERV membrane/core.",
        "primary_comparator": "Passive ERV+AC with EO off.",
        "claim_boundary": "Conditional model evidence; no measured net-system saving or product validation.",
        "files": entries,
    }
    write_text(staging / "MANIFEST.json", json.dumps(manifest, indent=2, ensure_ascii=False))

    checksum_paths = [path for path in sorted(staging.rglob("*")) if path.is_file() and path.name != "SHA256SUMS"]
    checksum_lines = [f"{sha256(path)}  {path.relative_to(staging).as_posix()}" for path in checksum_paths]
    write_text(staging / "SHA256SUMS", "\n".join(checksum_lines))


def main() -> None:
    if RELEASE.exists():
        raise FileExistsError(f"Refusing to overwrite existing controlled release: {RELEASE}")
    DELIVERABLES.mkdir(parents=True, exist_ok=True)
    RELEASE.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="heiq-v9-release-") as temp:
        staging = Path(temp) / RELEASE.name
        build_release(staging)
        shutil.move(str(staging), RELEASE)

    for name, source in REPORTS.items():
        copy_file(source, DELIVERABLES / name)

    print(json.dumps({
        "release": str(RELEASE),
        "governing_report": str(RELEASE / "reports" / f"{MAIN_STEM}.pdf"),
        "files": sum(1 for path in RELEASE.rglob("*") if path.is_file()),
        "bytes": sum(path.stat().st_size for path in RELEASE.rglob("*") if path.is_file()),
    }, indent=2))


if __name__ == "__main__":
    main()
