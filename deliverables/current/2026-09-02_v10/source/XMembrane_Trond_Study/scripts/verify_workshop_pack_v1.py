#!/usr/bin/env python3
"""Fail-fast consistency check for the 2026-08-30 workshop package."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "workshop_diffusivity_energy_v1"
PACK = ROOT / "reports" / "workshop_pack_2026-08-30"


class VerificationError(RuntimeError):
    """Raised when a frozen workshop claim no longer matches its source."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=PACK / "verification.json",
        help="JSON record written after all checks pass",
    )
    parser.add_argument(
        "--skip-presentation-files",
        action="store_true",
        help="Check numerical sources before the deck and handout are compiled",
    )
    return parser.parse_args()


def close(actual: float, expected: float, tolerance: float, label: str) -> None:
    if not math.isfinite(actual) or abs(actual - expected) > tolerance:
        raise VerificationError(
            f"{label}: expected {expected:.12g} +/- {tolerance:g}, got {actual!r}"
        )


def one(frame: pd.DataFrame, label: str, **matches: object) -> pd.Series:
    selected = frame
    for column, value in matches.items():
        if isinstance(value, float):
            selected = selected.loc[
                pd.to_numeric(selected[column], errors="coerce").map(
                    lambda item: math.isclose(
                        float(item), value, rel_tol=1.0e-9, abs_tol=0.0
                    )
                    if math.isfinite(float(item))
                    else False
                )
            ]
        else:
            selected = selected.loc[selected[column].eq(value)]
    if len(selected) != 1:
        raise VerificationError(f"{label}: expected one row, found {len(selected)}")
    return selected.iloc[0]


def require_file(path: Path) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise VerificationError(f"Required file is missing or empty: {path}")


def check_pdf(path: Path) -> int:
    require_file(path)
    result = subprocess.run(
        ["pdfinfo", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    pages = None
    for line in result.stdout.splitlines():
        if line.startswith("Pages:"):
            pages = int(line.split(":", 1)[1].strip())
            break
    if not pages or pages < 1:
        raise VerificationError(f"Could not verify PDF pages: {path}")
    return pages


def sha256(path: Path) -> str:
    require_file(path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    args = parse_args()
    checks: list[dict[str, object]] = []

    system = pd.read_csv(REPORT / "data" / "system_bar_data.csv")
    ac = one(system, "AC-only O80", diagram_id="ac_only_weather", state_id="O80")
    passive = one(
        system, "passive ERV O80", diagram_id="ac_erv_weather", state_id="O80"
    )
    o30_system = one(
        system,
        "post-ERV O30",
        diagram_id="ac_erv_eo_posterv",
        state_id="O30 target",
    )
    close(float(ac.total_power_kw), 1166.4, 1.0e-6, "AC-only reference")
    close(float(passive.total_power_kw), 543.7405641877893, 1.0e-6, "ERV+AC")
    close(float(o30_system.total_power_kw), 379.515777961, 1.0e-6, "O30 subtotal")
    close(
        float(o30_system.saving_vs_first_bar_kw),
        164.224786227,
        1.0e-6,
        "O30 conditional reduction",
    )
    checks.append({"check": "system_energy_coordinates", "status": "PASS"})

    diffusivity = pd.read_csv(REPORT / "data" / "diffusivity_workshop_table.csv")
    low = one(
        diffusivity,
        "O30 D=1e-14",
        target_id="o30",
        water_diffusivity_m2_s=1.0e-14,
    )
    high = one(
        diffusivity,
        "O30 D=1e-9",
        target_id="o30",
        water_diffusivity_m2_s=1.0e-9,
    )
    close(float(low.reported_saving_kw), 164.224786227, 1.0e-6, "low-D saving")
    close(float(high.reported_saving_kw), -176.643710, 1.0e-5, "high-D saving")
    close(
        float(high.absolute_diffusion_fraction_of_eo),
        0.943242,
        1.0e-6,
        "high-D back-diffusion fraction",
    )
    if float(diffusivity.maximum_required_terminal_voltage_signed_v.max()) > 2.0 + 1e-9:
        raise VerificationError("A selected diffusivity row exceeds the 2-V boundary")
    checks.append({"check": "uniform_current_diffusivity_sensitivity", "status": "PASS"})

    break_even = pd.read_csv(REPORT / "data" / "break_even_180whkg.csv")
    o30_be = one(break_even, "O30 break-even", case_id="o30")
    full_be = one(
        break_even,
        "full conservative break-even",
        case_id="full_remaining_latent",
    )
    close(
        float(o30_be.break_even_all_in_sec_kwh_kg),
        0.156700807441,
        1.0e-10,
        "O30 break-even",
    )
    close(float(o30_be.saving_at_180_wh_kg_kw), -28.617763, 1.0e-5, "O30 at 180")
    close(float(full_be.saving_at_180_wh_kg_kw), -39.364020, 1.0e-5, "full at 180")
    checks.append({"check": "break_even_boundary", "status": "PASS"})

    pri2 = pd.read_csv(REPORT / "data" / "pri2_eo_first_parallel_summary.csv")
    post = one(pri2, "post-ERV PRI2", architecture="post_passive_erv")
    close(float(post.total_water_removal_kg_h), 1689.501452, 1.0e-6, "PRI2 water")
    close(float(post.rh85_entry_temperature_c), 20.954211, 1.0e-6, "PRI2 entry")
    close(
        float(post.endpoint_process_air_enthalpy_decrease_kw),
        1434.860315,
        1.0e-6,
        "PRI2 endpoint enthalpy",
    )
    checks.append({"check": "pri2_psychrometric_envelope", "status": "PASS"})

    geometry = pd.read_csv(REPORT / "data" / "test_cell_nominal_geometry.csv").iloc[0]
    close(float(geometry.active_area_cm2), 25.0, 1.0e-12, "coupon area")
    close(float(geometry.actual_flow_l_min), 6.0, 1.0e-12, "coupon flow")
    close(float(geometry.channel_gap_mm), 2.0, 1.0e-12, "coupon gap")
    checks.append({"check": "coupon_geometry", "status": "PASS"})

    template = pd.read_csv(PACK / "material_candidate_register_template.csv")
    required_columns = {
        "candidate_id",
        "batch_or_sample_id",
        "property_id",
        "temperature_c",
        "source_activity",
        "receiver_activity",
        "current_density_a_m2",
        "same_sample_confirmed",
        "data_status",
    }
    missing = sorted(required_columns - set(template.columns))
    if missing:
        raise VerificationError(f"Candidate-register columns missing: {missing}")
    checks.append({"check": "material_search_template", "status": "PASS"})

    claims = pd.read_csv(PACK / "WORKSHOP_CLAIM_REGISTER.csv")
    if set(claims["claim_id"]) != {f"C{index:02d}" for index in range(1, 13)}:
        raise VerificationError("Workshop claim register is incomplete")
    if claims["principal_source"].isna().any():
        raise VerificationError("Workshop claim register contains an empty source")
    checks.append({"check": "workshop_claim_register", "status": "PASS"})

    common_dir = ROOT / "outputs" / "workshop_common_voltage_diffusivity_v1"
    common_path = common_dir / "diffusivity_envelope.csv"
    require_file(common_path)
    common = pd.read_csv(common_path)
    if len(common) != 14:
        raise VerificationError(
            f"Common-voltage envelope: expected 14 rows, found {len(common)}"
        )
    selected_voltage = pd.to_numeric(
        common["selected_common_terminal_voltage_v"], errors="coerce"
    )
    if selected_voltage.dropna().gt(2.0 + 1.0e-9).any():
        raise VerificationError("A common-voltage selected row exceeds 2 V")
    o30_common = common.loc[common["target_id"].eq("o30")]
    full_common = common.loc[common["target_id"].eq("full_remaining_latent")]
    if len(o30_common) != 7 or len(full_common) != 7:
        raise VerificationError("Common-voltage target/diffusivity coordinates are incomplete")
    if not o30_common["selection_status"].eq(
        "NUMERICALLY_CONFIRMED_FEASIBLE_VOLTAGE"
    ).all():
        raise VerificationError("Not every O30 diffusivity coordinate is confirmed")
    if full_common["selected_case_id"].notna().any():
        raise VerificationError("A full-duty selected case appeared unexpectedly")
    if not full_common["selection_status"].eq(
        "NO_FEASIBLE_SAMPLED_VOLTAGE_WITH_UNRESOLVED_POINTS"
    ).all():
        raise VerificationError("Full-duty fail-closed classification changed")
    common_low = one(
        common,
        "common-voltage O30 D=1e-14",
        target_id="o30",
        water_diffusivity_m2_s=1.0e-14,
    )
    common_high = one(
        common,
        "common-voltage O30 D=1e-9",
        target_id="o30",
        water_diffusivity_m2_s=1.0e-9,
    )
    close(
        float(common_low.selected_conditional_conservative_saving_kw_vs_erv_ac),
        162.416247,
        1.0e-4,
        "common-voltage low-D saving",
    )
    close(
        float(common_high.selected_conditional_conservative_saving_kw_vs_erv_ac),
        -181.413475,
        1.0e-4,
        "common-voltage high-D saving",
    )
    common_audit = json.loads((common_dir / "audit.json").read_text(encoding="utf-8"))
    if common_audit.get("passed") is not True:
        raise VerificationError("Common-voltage study audit did not pass")
    if int(common_audit.get("case_count", -1)) != 196:
        raise VerificationError("Common-voltage case count changed")
    checks.append(
        {"check": "common_voltage_diffusivity_cross_check", "status": "PASS"}
    )

    active = pd.read_csv(
        ROOT / "outputs" / "direct_active_eo_erv_study_v1" / "study" / "selected_cases.csv"
    )
    direct = one(active, "direct EO-in-ERV case", case_index=150)
    close(float(direct.terminal_voltage_v), 0.25, 1.0e-12, "direct ERV voltage")
    close(float(direct.required_active_area_m2), 34425.049213, 1.0e-5, "direct ERV area")
    close(
        float(direct.conditional_active_total_power_kw),
        107.856316,
        1.0e-5,
        "direct ERV subtotal",
    )
    close(
        float(direct.conditional_saving_kw_vs_passive_erv),
        435.884248,
        1.0e-5,
        "direct ERV conditional window",
    )
    checks.append({"check": "direct_eo_inside_erv_coordinate", "status": "PASS"})

    pdfs: dict[str, int] = {}
    if not args.skip_presentation_files:
        presentation_files = [
            PACK / "HeiQ_XMembrane_Workshop_Deck_2026-08-30.pdf",
            PACK / "HeiQ_XMembrane_Workshop_Handout_2026-08-30.pdf",
            REPORT
            / "HeiQ_XMembrane_Workshop_Decision_Report_2026-08-30_v2.pdf",
        ]
        for path in presentation_files:
            pdfs[str(path.relative_to(ROOT))] = check_pdf(path)
        checks.append({"check": "presentation_pdfs", "status": "PASS"})

    manifest_paths = [
        PACK / "README.md",
        PACK / "WORKSHOP_DECISION_SHEET.md",
        PACK / "WORKSHOP_CLAIM_REGISTER.csv",
        PACK / "MATERIAL_SEARCH_BRIEF.md",
        PACK / "material_candidate_register_template.csv",
        PACK / "practical_gate_register_template.csv",
        common_dir / "diffusivity_envelope.csv",
        common_dir / "audit.json",
        common_dir / "source_manifest.json",
    ]
    if not args.skip_presentation_files:
        manifest_paths.extend(
            [
                PACK / "HeiQ_XMembrane_Workshop_Deck_2026-08-30.tex",
                PACK / "HeiQ_XMembrane_Workshop_Deck_2026-08-30.pdf",
                PACK / "HeiQ_XMembrane_Workshop_Handout_2026-08-30.tex",
                PACK / "HeiQ_XMembrane_Workshop_Handout_2026-08-30.pdf",
                REPORT / "HeiQ_XMembrane_Workshop_Decision_Report_2026-08-30_v2.tex",
                REPORT / "HeiQ_XMembrane_Workshop_Decision_Report_2026-08-30_v2.pdf",
            ]
        )
    hashes = {
        str(path.relative_to(ROOT)): sha256(path)
        for path in manifest_paths
    }
    checks.append({"check": "workshop_asset_hashes", "status": "PASS"})

    record = {
        "schema_version": 1,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS",
        "claim_boundary": "conditional modelling evidence; not product validation",
        "checks": checks,
        "pdf_pages": pdfs,
        "sha256": hashes,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
