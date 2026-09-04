#!/usr/bin/env python3
"""Fail-closed final delivery check for the XMembrane model phase.

The checker deliberately separates three decisions:

* ``delivery_ready_today``: the bounded model study and its report can be
  delivered now;
* ``release_snapshot_ready``: the git worktree is clean enough to tag/archive;
* ``next_phase_empirical_ready``: measured candidate, receiver and practical
  data are complete enough for ranking and architecture selection.

Open empirical gates do not reopen the completed broad-modelling phase.  A
failed scientific audit, stale source hash, missing report or failed test does.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import importlib
from importlib import metadata
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "final_delivery_check_v1.json"
DEFAULT_OUTPUT = ROOT / "outputs" / "final_delivery_check_v1"
SCRIPT_VERSION = "final-delivery-check-v1.0-2026-08-31"


class FinalDeliveryCheckError(RuntimeError):
    """Raised for malformed checker inputs or an unsafe output operation."""


def load_json(path: Path | str) -> dict[str, Any]:
    resolved = Path(path).resolve()
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise FinalDeliveryCheckError(f"Expected a JSON object: {resolved}")
    return payload


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def resolve_path(value: str | Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    return {
        "path": str(resolved),
        "exists": resolved.is_file(),
        "size_bytes": resolved.stat().st_size if resolved.is_file() else None,
        "sha256": sha256_file(resolved) if resolved.is_file() else None,
    }


def verify_hash_manifest(manifest_path: Path | str) -> dict[str, Any]:
    """Verify the report-style relative-path SHA-256 manifest."""

    path = Path(manifest_path).resolve()
    result: dict[str, Any] = {
        "manifest_path": str(path),
        "passed": False,
        "checked_file_count": 0,
        "failed_file_count": 0,
        "files": [],
    }
    try:
        payload = load_json(path)
        if str(payload.get("hash_algorithm", "sha256")).lower() != "sha256":
            raise FinalDeliveryCheckError("Only SHA-256 manifests are supported")
        files = payload.get("files")
        if not isinstance(files, dict) or not files:
            raise FinalDeliveryCheckError("Manifest has no non-empty files object")
        checks: list[dict[str, Any]] = []
        for relative, expected in sorted(files.items()):
            target = (path.parent / str(relative)).resolve()
            exists = target.is_file()
            actual = sha256_file(target) if exists else None
            passed = bool(
                exists
                and isinstance(expected, str)
                and re.fullmatch(r"[0-9a-fA-F]{64}", expected)
                and actual == expected.lower()
            )
            checks.append(
                {
                    "path": str(target),
                    "declared_path": str(relative),
                    "exists": exists,
                    "expected_sha256": expected,
                    "actual_sha256": actual,
                    "passed": passed,
                }
            )
        result["files"] = checks
        result["checked_file_count"] = len(checks)
        result["failed_file_count"] = sum(not row["passed"] for row in checks)
        result["passed"] = result["failed_file_count"] == 0
    except Exception as exc:  # fail closed and retain a machine-readable reason
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["failed_file_count"] = max(1, int(result["failed_file_count"]))
    return result


def _collect_embedded_file_records(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        if isinstance(value.get("path"), str) and isinstance(
            value.get("sha256"), str
        ):
            yield value
        for child in value.values():
            yield from _collect_embedded_file_records(child)
    elif isinstance(value, list):
        for child in value:
            yield from _collect_embedded_file_records(child)


def verify_embedded_source_manifest(manifest_path: Path | str) -> dict[str, Any]:
    """Verify every embedded ``path``/``sha256`` record in a source manifest."""

    path = Path(manifest_path).resolve()
    result: dict[str, Any] = {
        "manifest_path": str(path),
        "passed": False,
        "checked_file_count": 0,
        "failed_file_count": 0,
        "files": [],
    }
    try:
        payload = load_json(path)
        records: list[Mapping[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for record in _collect_embedded_file_records(payload):
            key = (str(record["path"]), str(record["sha256"]).lower())
            if key not in seen:
                records.append(record)
                seen.add(key)
        if not records:
            raise FinalDeliveryCheckError(
                f"No embedded path/SHA-256 records found in {path}"
            )
        checks: list[dict[str, Any]] = []
        for record in records:
            target = Path(str(record["path"])).resolve()
            expected = str(record["sha256"]).lower()
            exists = target.is_file()
            actual = sha256_file(target) if exists else None
            expected_size = record.get("size_bytes")
            actual_size = target.stat().st_size if exists else None
            size_pass = bool(
                expected_size is None
                or (
                    isinstance(expected_size, (int, float))
                    and math.isfinite(float(expected_size))
                    and actual_size == int(expected_size)
                )
            )
            passed = bool(exists and actual == expected and size_pass)
            checks.append(
                {
                    "path": str(target),
                    "exists": exists,
                    "expected_sha256": expected,
                    "actual_sha256": actual,
                    "expected_size_bytes": expected_size,
                    "actual_size_bytes": actual_size,
                    "passed": passed,
                }
            )
        result["files"] = checks
        result["checked_file_count"] = len(checks)
        result["failed_file_count"] = sum(not row["passed"] for row in checks)
        result["passed"] = result["failed_file_count"] == 0
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["failed_file_count"] = max(1, int(result["failed_file_count"]))
    return result


def _audit_top_level_pass(audit: Mapping[str, Any]) -> bool:
    recognized = False
    passed = True
    if "status" in audit:
        recognized = True
        passed &= str(audit["status"]).upper() == "PASS"
    for key in ("all_pass", "passed", "canonical_crosscheck_pass"):
        if key in audit:
            recognized = True
            passed &= audit[key] is True
    return bool(recognized and passed)


def _audit_checks_pass(audit: Mapping[str, Any]) -> bool:
    checks = audit.get("checks")
    if checks is None:
        return True
    if isinstance(checks, Mapping):
        if not checks:
            return False
        return all(value is True for value in checks.values())
    if not isinstance(checks, list) or not checks:
        return False
    for item in checks:
        if not isinstance(item, Mapping):
            return False
        if "passed" in item and item["passed"] is not True:
            return False
        if "status" in item and str(item["status"]).upper() != "PASS":
            return False
        if "passed" not in item and "status" not in item:
            return False
    return True


def verify_scientific_audits(
    audits: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for index, audit in enumerate(audits):
        audit_id = str(
            audit.get("audit_id")
            or audit.get("study_id")
            or f"audit_{index + 1:02d}"
        )
        top_pass = _audit_top_level_pass(audit)
        checks_pass = _audit_checks_pass(audit)
        rows.append(
            {
                "audit_id": audit_id,
                "top_level_pass": top_pass,
                "nested_checks_pass": checks_pass,
                "passed": bool(top_pass and checks_pass),
            }
        )
    return {
        "passed": bool(rows and all(row["passed"] for row in rows)),
        "audit_count": len(rows),
        "failed_audit_count": sum(not row["passed"] for row in rows),
        "audits": rows,
    }


def _report_artifacts_pass(tex_path: Path, pdf_path: Path) -> bool:
    if not tex_path.is_file() or tex_path.stat().st_size == 0:
        return False
    if not pdf_path.is_file() or pdf_path.stat().st_size < 16:
        return False
    with pdf_path.open("rb") as handle:
        return handle.read(5) == b"%PDF-"


def evaluate_delivery(
    *,
    closure_status: Mapping[str, Any],
    scientific_audits: Sequence[Mapping[str, Any]],
    manifest_verification: Mapping[str, Any],
    report_tex_path: Path | str,
    report_pdf_path: Path | str,
    closure_gate_verification: Mapping[str, Any] | None = None,
    source_manifest_verification: Mapping[str, Any] | None = None,
    runtime_verification: Mapping[str, Any] | None = None,
    template_verification: Mapping[str, Any] | None = None,
    test_verification: Mapping[str, Any] | None = None,
    workshop_replay_verification: Mapping[str, Any] | None = None,
    common_voltage_claim_verification: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate model-phase delivery without treating future measurements as blockers."""

    model_phase_complete = bool(
        closure_status.get("broad_modelling_can_stop") is True
        and closure_status.get("material_data_collection_ready") is True
        and closure_status.get("technology_validated") is False
        and closure_status.get("full_system_claim_allowed") is False
        and str(closure_status.get("recommended_phase_label", ""))
        == "MODEL STUDY COMPLETE - MATERIAL AND SUBSYSTEM FEASIBILITY STARTS"
    )
    audit_result = verify_scientific_audits(scientific_audits)
    scientific_gates_pass = bool(audit_result["passed"])
    manifest_integrity_pass = manifest_verification.get("passed") is True
    report_artifacts_pass = _report_artifacts_pass(
        Path(report_tex_path).resolve(), Path(report_pdf_path).resolve()
    )

    optional_checks = {
        "closure_gate_register": closure_gate_verification,
        "nested_source_provenance": source_manifest_verification,
        "runtime_environment": runtime_verification,
        "handoff_templates": template_verification,
        "test_suite": test_verification,
        "workshop_replay": workshop_replay_verification,
        "common_voltage_claim_integrity": common_voltage_claim_verification,
    }
    optional_pass = {
        name: True if value is None else value.get("passed") is True
        for name, value in optional_checks.items()
    }

    blocking_items: list[str] = []
    if not model_phase_complete:
        blocking_items.append("closure_status_does_not_close_model_phase")
    if not scientific_gates_pass:
        blocking_items.append("one_or_more_scientific_audits_failed")
    if not manifest_integrity_pass:
        blocking_items.append("final_report_manifest_hash_mismatch")
    if not report_artifacts_pass:
        blocking_items.append("final_report_tex_or_pdf_missing_or_invalid")
    for name, passed in optional_pass.items():
        if not passed:
            blocking_items.append(f"{name}_failed")

    accepted_next_phase_open_items: list[str] = []
    for key in (
        "material_candidate_ranking_ready",
        "full_system_claim_allowed",
        "technology_validated",
        "full_duty_sampled_common_voltage_point_feasible",
    ):
        if closure_status.get(key) is False:
            accepted_next_phase_open_items.append(key)

    delivery_ready = len(blocking_items) == 0
    return {
        "delivery_ready_today": delivery_ready,
        "model_phase_complete": model_phase_complete,
        "scientific_gates_pass": scientific_gates_pass,
        "scientific_audit_verification": audit_result,
        "manifest_integrity_pass": manifest_integrity_pass,
        "report_artifacts_pass": report_artifacts_pass,
        "optional_checks_pass": optional_pass,
        "accepted_next_phase_open_items": accepted_next_phase_open_items,
        "blocking_items": blocking_items,
    }


def read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def _csv_bool(value: Any) -> bool | None:
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    return None


def _csv_float(value: Any) -> float | None:
    try:
        converted = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return converted if math.isfinite(converted) else None


def _csv_value_is_missing(value: Any) -> bool:
    return str(value).strip().lower() in {"", "nan", "none", "null"}


def verify_common_voltage_claim_integrity(
    cases_path: Path,
    envelope_path: Path,
    local_probe_path: Path,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Protect claims from unresolved common-voltage solution coordinates.

    A numerically unresolved high-voltage row may remain in the bounded grid,
    but it may not supply area, power, saving or selected-case evidence.  The
    selected O30 coordinates are delivery-critical and therefore must map to
    converged refined cases.  Full-duty unresolved rows stay explicitly OPEN
    and do not block delivery when the claim boundary remains fail-closed.
    """

    result: dict[str, Any] = {
        "passed": False,
        "delivery_blocking": True,
        "hard_checks": {},
        "blocking_items": [],
        "warnings": [],
        "selected_target": {},
        "high_bracket_fail_closed": {},
        "full_duty_claim_guard": {},
        "local_bracket_probe": {},
        "full_duty_maturity_gate": {
            "status": "OPEN",
            "required_today": False,
            "delivery_blocking": False,
        },
    }
    try:
        case_columns, cases = read_csv_rows(cases_path)
        envelope_columns, envelope = read_csv_rows(envelope_path)
        decision_columns = list(
            contract["unresolved_case_decision_value_columns"]
        )
        selected_mapping = dict(contract["selected_numeric_field_mapping"])
        required_case_columns = {
            "case_id",
            "target_id",
            "water_diffusivity_m2_s",
            "common_terminal_voltage_v",
            "segment_count",
            "status",
            "resolution_class",
            "common_voltage_feasible",
            "transport_solution_complete",
            "terminal_voltage_solution_pass",
            "thermodynamic_consistency_pass",
            "numeric_ceiling_retry_applied",
            "numeric_ceiling_retry_recovered",
            "initial_status_before_numeric_ceiling_retry",
            "initial_resolution_class_before_numeric_ceiling_retry",
            *decision_columns,
            *selected_mapping.values(),
        }
        required_envelope_columns = {
            "target_id",
            "water_diffusivity_m2_s",
            "sampled_voltage_count",
            "refined_feasible_voltage_count",
            "numerically_confirmed_voltage_count",
            "refined_physical_no_solution_voltage_count",
            "refined_numerical_or_local_unresolved_voltage_count",
            "selection_status",
            "full_system_claim_allowed",
            "selected_case_id",
            *selected_mapping.keys(),
        }
        missing_case_columns = sorted(required_case_columns - set(case_columns))
        missing_envelope_columns = sorted(
            required_envelope_columns - set(envelope_columns)
        )
        schema_pass = not missing_case_columns and not missing_envelope_columns
        result["hard_checks"]["input_schema"] = schema_pass
        result["missing_case_columns"] = missing_case_columns
        result["missing_envelope_columns"] = missing_envelope_columns
        if not schema_pass:
            raise FinalDeliveryCheckError(
                "Common-voltage input schema is incomplete"
            )

        selected_target_id = str(contract["selected_target_id"])
        full_target_id = str(contract["full_duty_target_id"])
        selected_segment_count = int(contract["selected_segment_count"])
        confirmed_status = str(contract["confirmed_selection_status"])
        full_open_status = str(contract["full_duty_open_selection_status"])
        converged_resolution = str(contract["converged_resolution_class"])
        unresolved_resolution = str(contract["unresolved_resolution_class"])
        physical_resolution = str(
            contract["physical_no_solution_resolution_class"]
        )
        high_status = str(contract["legacy_high_bracket_status"])
        feasible_status = str(contract["feasible_case_status"])
        relative_tolerance = float(contract["numeric_match_relative_tolerance"])
        absolute_tolerance = float(contract["numeric_match_absolute_tolerance"])

        case_ids: dict[str, list[dict[str, str]]] = {}
        for row in cases:
            case_ids.setdefault(str(row["case_id"]), []).append(row)

        selected_envelope = [
            row for row in envelope if row["target_id"] == selected_target_id
        ]
        selected_failures: list[dict[str, Any]] = []
        selected_ids: list[str] = []
        for row in selected_envelope:
            case_id = str(row["selected_case_id"]).strip()
            selected_ids.append(case_id)
            mapped = case_ids.get(case_id, [])
            reasons: list[str] = []
            if row["selection_status"] != confirmed_status:
                reasons.append("selection_not_numerically_confirmed")
            if _csv_bool(row["full_system_claim_allowed"]) is not False:
                reasons.append("full_system_claim_not_disabled")
            if not case_id or len(mapped) != 1:
                reasons.append("selected_case_id_does_not_map_one_to_one")
            if len(mapped) == 1:
                case = mapped[0]
                if case["target_id"] != selected_target_id:
                    reasons.append("selected_case_target_mismatch")
                if _csv_float(case["segment_count"]) != float(
                    selected_segment_count
                ):
                    reasons.append("selected_case_not_refined_segment_count")
                if case["resolution_class"] != converged_resolution:
                    reasons.append("selected_case_not_converged")
                if case["status"] != feasible_status:
                    reasons.append("selected_case_status_not_feasible")
                for column in (
                    "common_voltage_feasible",
                    "transport_solution_complete",
                    "terminal_voltage_solution_pass",
                    "thermodynamic_consistency_pass",
                ):
                    if _csv_bool(case[column]) is not True:
                        reasons.append(f"selected_case_{column}_not_true")
                envelope_d = _csv_float(row["water_diffusivity_m2_s"])
                case_d = _csv_float(case["water_diffusivity_m2_s"])
                if (
                    envelope_d is None
                    or case_d is None
                    or not math.isclose(
                        envelope_d,
                        case_d,
                        rel_tol=relative_tolerance,
                        abs_tol=0.0,
                    )
                ):
                    reasons.append("selected_case_diffusivity_mismatch")
                for envelope_field, case_field in selected_mapping.items():
                    envelope_value = _csv_float(row[envelope_field])
                    case_value = _csv_float(case[case_field])
                    if (
                        envelope_value is None
                        or case_value is None
                        or not math.isclose(
                            envelope_value,
                            case_value,
                            rel_tol=relative_tolerance,
                            abs_tol=absolute_tolerance,
                        )
                    ):
                        reasons.append(
                            f"selected_numeric_mismatch:{envelope_field}"
                        )
            if reasons:
                selected_failures.append(
                    {
                        "water_diffusivity_m2_s": row["water_diffusivity_m2_s"],
                        "selected_case_id": case_id,
                        "reasons": reasons,
                    }
                )
        expected_selected_count = int(
            contract["expected_selected_target_envelope_rows"]
        )
        selected_pass = bool(
            len(selected_envelope) == expected_selected_count
            and len(set(selected_ids)) == expected_selected_count
            and not selected_failures
        )
        result["hard_checks"]["selected_o30_rows_resolved_and_mapped"] = (
            selected_pass
        )
        result["selected_target"] = {
            "target_id": selected_target_id,
            "expected_envelope_row_count": expected_selected_count,
            "observed_envelope_row_count": len(selected_envelope),
            "unique_selected_case_count": len(set(selected_ids) - {""}),
            "failure_count": len(selected_failures),
            "failures": selected_failures,
        }

        retry_source_rows = [
            row
            for row in cases
            if _csv_bool(row["numeric_ceiling_retry_applied"]) is True
        ]
        high_rows = [
            row
            for row in retry_source_rows
            if _csv_bool(row["numeric_ceiling_retry_recovered"]) is not True
        ]
        high_failures: list[dict[str, Any]] = []
        decision_value_violations: list[dict[str, Any]] = []
        for row in high_rows:
            reasons: list[str] = []
            if row["resolution_class"] != unresolved_resolution:
                reasons.append("high_bracket_not_classified_unresolved")
            if _csv_bool(row["common_voltage_feasible"]) is not False:
                reasons.append("high_bracket_marked_feasible")
            populated = [
                column
                for column in decision_columns
                if not _csv_value_is_missing(row[column])
            ]
            if populated:
                reasons.append("unresolved_decision_values_populated")
                decision_value_violations.append(
                    {
                        "case_id": row["case_id"],
                        "populated_columns": populated,
                    }
                )
            if reasons:
                high_failures.append(
                    {"case_id": row["case_id"], "reasons": reasons}
                )
        high_pass = bool(high_rows and not high_failures)
        result["hard_checks"]["legacy_high_bracket_rows_fail_closed"] = high_pass
        result["high_bracket_fail_closed"] = {
            "legacy_status": high_status,
            "retry_source_row_count": len(retry_source_rows),
            "recovered_retry_row_count": len(retry_source_rows) - len(high_rows),
            "unrecovered_retry_row_count": len(high_rows),
            "row_count": len(high_rows),
            "failure_count": len(high_failures),
            "decision_value_violation_count": len(decision_value_violations),
            "failures": high_failures,
            "decision_value_violations": decision_value_violations,
            "diagnostic_transport_values_allowed": True,
        }

        full_envelope = [
            row for row in envelope if row["target_id"] == full_target_id
        ]
        full_failures: list[dict[str, Any]] = []
        full_physical = 0
        full_unresolved = 0
        for row in full_envelope:
            reasons: list[str] = []
            physical_count = int(
                _csv_float(
                    row["refined_physical_no_solution_voltage_count"]
                )
                or 0
            )
            unresolved_count = int(
                _csv_float(
                    row[
                        "refined_numerical_or_local_unresolved_voltage_count"
                    ]
                )
                or 0
            )
            full_physical += physical_count
            full_unresolved += unresolved_count
            sampled_count = int(_csv_float(row["sampled_voltage_count"]) or 0)
            confirmed_count = int(
                _csv_float(row["numerically_confirmed_voltage_count"]) or 0
            )
            feasible_count = int(
                _csv_float(row["refined_feasible_voltage_count"]) or 0
            )
            if row["selection_status"] != full_open_status:
                reasons.append("full_duty_selection_status_not_open_unresolved")
            if confirmed_count != 0 or feasible_count != 0:
                reasons.append("full_duty_has_feasible_or_confirmed_count")
            if physical_count + unresolved_count != sampled_count:
                reasons.append("full_duty_resolution_counts_do_not_close")
            if unresolved_count <= 0:
                reasons.append("full_duty_open_status_has_no_unresolved_points")
            if not _csv_value_is_missing(row["selected_case_id"]):
                reasons.append("full_duty_has_selected_case_id")
            selected_values = [
                column
                for column in envelope_columns
                if column.startswith("selected_")
                and column != "selected_case_id"
                and not _csv_value_is_missing(row[column])
            ]
            if selected_values:
                reasons.append("full_duty_has_selected_decision_values")
            if _csv_bool(row["full_system_claim_allowed"]) is not False:
                reasons.append("full_duty_full_system_claim_not_disabled")
            if reasons:
                full_failures.append(
                    {
                        "water_diffusivity_m2_s": row["water_diffusivity_m2_s"],
                        "reasons": reasons,
                        "populated_selected_fields": selected_values,
                    }
                )
        expected_full_count = int(contract["expected_full_duty_envelope_rows"])
        full_guard_pass = bool(
            len(full_envelope) == expected_full_count and not full_failures
        )
        result["hard_checks"]["full_duty_claim_remains_fail_closed"] = (
            full_guard_pass
        )
        result["full_duty_claim_guard"] = {
            "target_id": full_target_id,
            "expected_envelope_row_count": expected_full_count,
            "observed_envelope_row_count": len(full_envelope),
            "confirmed_selected_case_count": sum(
                not _csv_value_is_missing(row["selected_case_id"])
                for row in full_envelope
            ),
            "refined_physical_no_solution_count": full_physical,
            "refined_numerical_or_local_unresolved_count": full_unresolved,
            "failure_count": len(full_failures),
            "failures": full_failures,
            "allowed_claim": (
                "No confirmed feasible sampled common-voltage point was found; "
                "some sampled coordinates remain numerical/local unresolved."
            ),
            "prohibited_claims": [
                "full duty is impossible",
                "no common-voltage solution exists below 2 V",
                "all sampled failures are physical no-solutions",
            ],
        }
        result["full_duty_maturity_gate"] = {
            "status": "OPEN" if full_unresolved > 0 else "CLOSED",
            "required_today": False,
            "delivery_blocking": False,
            "reason": (
                f"{full_unresolved} refined points remain numerical/local "
                "unresolved; this limits the full-duty single-bus claim only."
            ),
        }

        probe_pass = False
        probe_detail: dict[str, Any] = {}
        try:
            probe_columns, probes = read_csv_rows(local_probe_path)
            gate_columns = (
                "source_current_density_gate_applied",
                "elevated_current_density_gate_applied",
                "source_area_is_acceptance_gate",
                "elevated_area_is_acceptance_gate",
                "source_surface_direction_is_acceptance_gate",
                "elevated_surface_direction_is_acceptance_gate",
            )
            closure_columns = (
                "elevated_common_voltage_feasible",
                "elevated_transport_solution_complete",
                "elevated_transport_water_balance_pass",
                "elevated_terminal_voltage_solution_pass",
                "elevated_thermodynamic_consistency_pass",
            )
            required_probe_columns = {
                "source_case_id",
                "target_id",
                "water_diffusivity_m2_s",
                "common_terminal_voltage_v",
                "segment_count",
                "source_numeric_current_ceiling_a_m2",
                "elevated_numeric_current_ceiling_a_m2",
                "numeric_ceiling_multiplier",
                "source_status",
                "elevated_status",
                "source_resolution_class",
                "elevated_resolution_class",
                "source_common_voltage_feasible",
                "retry_recovered",
                *gate_columns,
                *closure_columns,
            }
            missing_probe_columns = sorted(
                required_probe_columns - set(probe_columns)
            )
            minimum_multiplier = float(
                contract["minimum_local_probe_ceiling_multiplier"]
            )
            maximum_probe_voltage = float(
                contract["maximum_local_probe_voltage_v"]
            )
            expected_retry_ids = {row["case_id"] for row in retry_source_rows}
            observed_retry_ids = [str(row.get("source_case_id", "")) for row in probes]
            duplicate_probe_ids = sorted(
                {
                    case_id
                    for case_id in observed_retry_ids
                    if case_id and observed_retry_ids.count(case_id) > 1
                }
            )
            missing_probe_ids = sorted(expected_retry_ids - set(observed_retry_ids))
            unexpected_probe_ids = sorted(
                set(observed_retry_ids) - expected_retry_ids
            )
            probe_failures: list[dict[str, Any]] = []
            recovered_count = 0
            unrecovered_count = 0
            for index, row in enumerate(probes):
                source_case_id = str(row.get("source_case_id", ""))
                reasons: list[str] = []
                mapped = case_ids.get(source_case_id, [])
                if len(mapped) != 1:
                    reasons.append("probe_source_case_does_not_map_one_to_one")
                    source_case: Mapping[str, Any] = {}
                else:
                    source_case = mapped[0]
                multiplier = _csv_float(row.get("numeric_ceiling_multiplier"))
                source_ceiling = _csv_float(
                    row.get("source_numeric_current_ceiling_a_m2")
                )
                elevated_ceiling = _csv_float(
                    row.get("elevated_numeric_current_ceiling_a_m2")
                )
                if multiplier is None or multiplier < minimum_multiplier:
                    reasons.append("numeric_ceiling_multiplier_too_small")
                if (
                    source_ceiling is None
                    or elevated_ceiling is None
                    or multiplier is None
                    or not math.isclose(
                        elevated_ceiling,
                        source_ceiling * multiplier,
                        rel_tol=relative_tolerance,
                        abs_tol=absolute_tolerance,
                    )
                ):
                    reasons.append("numeric_ceiling_elevation_identity_failed")
                voltage = _csv_float(row.get("common_terminal_voltage_v"))
                if (
                    voltage is None
                    or voltage <= 0.0
                    or voltage > maximum_probe_voltage + absolute_tolerance
                ):
                    reasons.append("probe_voltage_outside_declared_boundary")
                if _csv_bool(row.get("source_common_voltage_feasible")) is not False:
                    reasons.append("source_probe_marked_feasible")
                if any(_csv_bool(row.get(column)) is not False for column in gate_columns):
                    reasons.append("acceptance_gate_changed_or_applied")
                if source_case:
                    for column in (
                        "target_id",
                        "water_diffusivity_m2_s",
                        "common_terminal_voltage_v",
                        "segment_count",
                    ):
                        left = row.get(column)
                        right = source_case.get(column)
                        if column == "target_id":
                            matches = str(left) == str(right)
                        else:
                            left_number = _csv_float(left)
                            right_number = _csv_float(right)
                            matches = bool(
                                left_number is not None
                                and right_number is not None
                                and math.isclose(
                                    left_number,
                                    right_number,
                                    rel_tol=relative_tolerance,
                                    abs_tol=absolute_tolerance,
                                )
                            )
                        if not matches:
                            reasons.append(f"probe_source_coordinate_mismatch:{column}")
                    if _csv_bool(
                        source_case.get("numeric_ceiling_retry_applied")
                    ) is not True:
                        reasons.append("mapped_case_retry_applied_not_true")
                    initial_status = str(
                        source_case.get(
                            "initial_status_before_numeric_ceiling_retry", ""
                        )
                    )
                    initial_resolution = str(
                        source_case.get(
                            "initial_resolution_class_before_numeric_ceiling_retry",
                            "",
                        )
                    )
                    if str(row.get("source_status", "")) != initial_status:
                        reasons.append("probe_source_status_mismatch")
                    if (
                        str(row.get("source_resolution_class", ""))
                        != initial_resolution
                    ):
                        reasons.append("probe_source_resolution_mismatch")

                recovered = _csv_bool(row.get("retry_recovered")) is True
                if recovered:
                    recovered_count += 1
                    if str(row.get("elevated_resolution_class", "")) != converged_resolution:
                        reasons.append("recovered_probe_not_converged")
                    if any(
                        _csv_bool(row.get(column)) is not True
                        for column in closure_columns
                    ):
                        reasons.append("recovered_probe_missing_full_closure")
                    if source_case and (
                        _csv_bool(
                            source_case.get("numeric_ceiling_retry_recovered")
                        )
                        is not True
                        or _csv_bool(source_case.get("common_voltage_feasible"))
                        is not True
                        or str(source_case.get("resolution_class", ""))
                        != converged_resolution
                    ):
                        reasons.append("recovered_probe_not_promoted_to_effective_case")
                else:
                    unrecovered_count += 1
                    if (
                        str(row.get("elevated_resolution_class", ""))
                        != unresolved_resolution
                    ):
                        reasons.append("unrecovered_probe_not_fail_closed")
                    if _csv_bool(row.get("elevated_common_voltage_feasible")) is not False:
                        reasons.append("unrecovered_probe_marked_feasible")
                    if source_case and (
                        _csv_bool(
                            source_case.get("numeric_ceiling_retry_recovered")
                        )
                        is not False
                        or _csv_bool(source_case.get("common_voltage_feasible"))
                        is not False
                        or str(source_case.get("resolution_class", ""))
                        != unresolved_resolution
                    ):
                        reasons.append("unrecovered_probe_effective_case_not_fail_closed")
                if reasons:
                    probe_failures.append(
                        {
                            "row_index": index,
                            "source_case_id": source_case_id,
                            "reasons": reasons,
                        }
                    )
            exact_coverage = bool(
                not duplicate_probe_ids
                and not missing_probe_ids
                and not unexpected_probe_ids
                and len(probes) == len(expected_retry_ids)
            )
            probe_pass = bool(
                not missing_probe_columns
                and expected_retry_ids
                and exact_coverage
                and not probe_failures
            )
            probe_detail = {
                "passed": probe_pass,
                "delivery_blocking": not probe_pass,
                "coverage_contract": contract["local_probe_coverage"],
                "expected_source_case_count": len(expected_retry_ids),
                "observed_probe_row_count": len(probes),
                "recovered_case_count": recovered_count,
                "unrecovered_case_count": unrecovered_count,
                "minimum_ceiling_multiplier": minimum_multiplier,
                "maximum_probe_voltage_v": maximum_probe_voltage,
                "exact_source_coverage": exact_coverage,
                "duplicate_source_case_ids": duplicate_probe_ids,
                "missing_source_case_ids": missing_probe_ids,
                "unexpected_source_case_ids": unexpected_probe_ids,
                "missing_columns": missing_probe_columns,
                "failures": probe_failures,
                "interpretation": (
                    "Every flagged <=2 V source case is retried at the elevated "
                    "numeric bound. Only full transport, water, voltage and "
                    "thermodynamic closure permits recovery; all other rows remain "
                    "numerical/local unresolved."
                ),
            }
            if unrecovered_count:
                result["warnings"].append(
                    f"numeric_ceiling_retries_unrecovered:{unrecovered_count}"
                )
        except Exception as exc:
            probe_detail = {
                "passed": False,
                "delivery_blocking": True,
                "error": f"{type(exc).__name__}: {exc}",
            }
        result["local_bracket_probe"] = probe_detail
        result["hard_checks"][
            "numeric_ceiling_retry_exact_coverage_and_closure"
        ] = probe_pass

        failed_hard_checks = [
            key for key, passed in result["hard_checks"].items() if not passed
        ]
        result["blocking_items"] = failed_hard_checks
        result["passed"] = not failed_hard_checks
        result["delivery_blocking"] = bool(failed_hard_checks)
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["blocking_items"] = ["common_voltage_claim_integrity_unreadable"]
    return result


def verify_closure_gate_register(
    path: Path,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        columns, rows = read_csv_rows(path)
        if not {"gate_id", "status", "blocks", "evidence"}.issubset(columns):
            raise FinalDeliveryCheckError("Closure gate register schema is incomplete")
        ids = [row["gate_id"] for row in rows]
        duplicate_ids = sorted({value for value in ids if ids.count(value) > 1})
        expected = {
            **dict(config["required_model_gate_status"]),
            **dict(config["accepted_next_phase_gate_status"]),
            str(config["release_gate"]["gate_id"]): str(
                config["release_gate"]["accepted_status_for_model_delivery"]
            ),
        }
        actual = {row["gate_id"]: row["status"].upper() for row in rows}
        missing = sorted(set(expected) - set(actual))
        unexpected = sorted(set(actual) - set(expected))
        mismatches = [
            {
                "gate_id": gate_id,
                "expected": status,
                "actual": actual.get(gate_id),
            }
            for gate_id, status in expected.items()
            if actual.get(gate_id) != status
        ]
        passed = not duplicate_ids and not missing and not unexpected and not mismatches
        return {
            "passed": passed,
            "gate_count": len(rows),
            "duplicate_gate_ids": duplicate_ids,
            "missing_gate_ids": missing,
            "unexpected_gate_ids": unexpected,
            "status_mismatches": mismatches,
            "gates": rows,
        }
    except Exception as exc:
        return {"passed": False, "error": f"{type(exc).__name__}: {exc}"}


def _version_tuple(value: str) -> tuple[int, ...]:
    parts = [int(item) for item in re.findall(r"\d+", str(value))[:4]]
    return tuple(parts + [0] * (4 - len(parts)))


def verify_runtime(requirements: Mapping[str, str]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for package, requirement in requirements.items():
        match = re.fullmatch(r">=\s*([0-9][0-9.]*)", str(requirement))
        if match is None:
            rows.append(
                {
                    "package": package,
                    "requirement": requirement,
                    "installed_version": None,
                    "passed": False,
                    "detail": "unsupported requirement syntax",
                }
            )
            continue
        minimum = match.group(1)
        installed: str | None = None
        detail = ""
        try:
            if package.lower() == "python":
                installed = ".".join(str(item) for item in sys.version_info[:3])
            else:
                try:
                    installed = metadata.version(package)
                except metadata.PackageNotFoundError:
                    module = importlib.import_module(package)
                    installed = str(getattr(module, "__version__", "0"))
            passed = _version_tuple(installed) >= _version_tuple(minimum)
        except Exception as exc:
            passed = False
            detail = f"{type(exc).__name__}: {exc}"
        rows.append(
            {
                "package": package,
                "requirement": requirement,
                "installed_version": installed,
                "passed": passed,
                "detail": detail,
            }
        )
    return {
        "passed": bool(rows and all(row["passed"] for row in rows)),
        "requirements": rows,
        "failed_requirement_count": sum(not row["passed"] for row in rows),
    }


def _verify_id_table(
    path: Path,
    *,
    id_column: str,
    required_ids: Sequence[str],
    required_columns: Sequence[str],
) -> dict[str, Any]:
    try:
        columns, rows = read_csv_rows(path)
        ids = [row.get(id_column, "") for row in rows]
        duplicate_ids = sorted({value for value in ids if value and ids.count(value) > 1})
        missing_columns = sorted(set(required_columns) - set(columns))
        missing_ids = sorted(set(required_ids) - set(ids))
        unexpected_ids = sorted(set(ids) - set(required_ids))
        passed = not duplicate_ids and not missing_columns and not missing_ids and not unexpected_ids
        return {
            "path": str(path),
            "passed": passed,
            "row_count": len(rows),
            "duplicate_ids": duplicate_ids,
            "missing_columns": missing_columns,
            "missing_ids": missing_ids,
            "unexpected_ids": unexpected_ids,
        }
    except Exception as exc:
        return {
            "path": str(path),
            "passed": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


def verify_handoff_templates(
    config: Mapping[str, Any], paths: Mapping[str, Path]
) -> dict[str, Any]:
    checks = [
        _verify_id_table(
            paths["material_requirements"],
            id_column="requirement_id",
            required_ids=list(config["required_material_ids"]),
            required_columns=[
                "requirement_id",
                "candidate_sample_id",
                "candidate_value_or_source",
                "data_status",
            ],
        ),
        _verify_id_table(
            paths["practical_gate_template"],
            id_column="gate_id",
            required_ids=list(config["required_practical_gate_ids"]),
            required_columns=[
                "gate_id",
                "proposed_limit",
                "evidence_source",
                "status",
            ],
        ),
        _verify_id_table(
            paths["receiver_thermal_ledger_template"],
            id_column="ledger_id",
            required_ids=list(config["required_receiver_ledger_ids"]),
            required_columns=[
                "ledger_id",
                "value",
                "evidence_source",
                "uncertainty",
                "status",
            ],
        ),
        _verify_id_table(
            paths["architecture_decision_template"],
            id_column="criterion_id",
            required_ids=list(config["required_architecture_criterion_ids"]),
            required_columns=[
                "criterion_id",
                "post_erv_value_or_source",
                "direct_erv_value_or_source",
                "comparison_status",
            ],
        ),
    ]
    candidate_path = paths["material_candidate_template"]
    try:
        columns, _ = read_csv_rows(candidate_path)
        required_candidate_columns = {
            "candidate_id",
            "batch_or_sample_id",
            "property_id",
            "measured_value",
            "same_sample_confirmed",
            "data_status",
        }
        checks.append(
            {
                "path": str(candidate_path),
                "passed": required_candidate_columns.issubset(columns),
                "missing_columns": sorted(required_candidate_columns - set(columns)),
            }
        )
    except Exception as exc:
        checks.append(
            {
                "path": str(candidate_path),
                "passed": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
    return {
        "passed": all(check["passed"] for check in checks),
        "checks": checks,
        "template_count": len(checks),
    }


def run_pytest(timeout_seconds: int) -> dict[str, Any]:
    start = time.monotonic()
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-s",
        "-p",
        "no:cacheprovider",
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        combined = "\n".join(
            part.strip() for part in (completed.stdout, completed.stderr) if part.strip()
        )
        summary_matches = re.findall(
            r"(?:(\d+) failed, )?(\d+) passed(?:, (\d+) skipped)?",
            combined,
        )
        failed_count = passed_count = skipped_count = None
        if summary_matches:
            failed_text, passed_text, skipped_text = summary_matches[-1]
            failed_count = int(failed_text or 0)
            passed_count = int(passed_text)
            skipped_count = int(skipped_text or 0)
        return {
            "passed": completed.returncode == 0,
            "mode": "live_pytest",
            "command": command,
            "return_code": completed.returncode,
            "duration_seconds": time.monotonic() - start,
            "failed_count": failed_count,
            "passed_count": passed_count,
            "skipped_count": skipped_count,
            "output_tail": combined[-6000:],
        }
    except Exception as exc:
        return {
            "passed": False,
            "mode": "live_pytest",
            "command": command,
            "duration_seconds": time.monotonic() - start,
            "error": f"{type(exc).__name__}: {exc}",
        }


def frozen_test_evidence(report_manifest: Mapping[str, Any]) -> dict[str, Any]:
    value = str(report_manifest.get("verification", {}).get("full_pytest_suite", ""))
    return {
        "passed": bool(re.search(r"\d+ passed", value) and "failed" not in value.lower()),
        "mode": "frozen_report_manifest",
        "evidence": value,
    }


def run_workshop_verifier(timeout_seconds: int) -> dict[str, Any]:
    script = ROOT / "scripts" / "verify_workshop_pack_v1.py"
    try:
        with tempfile.TemporaryDirectory(prefix="heiq-workshop-verify-") as temporary:
            output = Path(temporary) / "verification.json"
            command = [
                sys.executable,
                str(script),
                "--output",
                str(output),
            ]
            completed = subprocess.run(
                command,
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
            payload = load_json(output) if output.is_file() else {}
            passed = bool(
                completed.returncode == 0
                and payload.get("status") == "PASS"
                and _audit_checks_pass(payload)
            )
            return {
                "passed": passed,
                "mode": "temporary_output_replay",
                "return_code": completed.returncode,
                "status": payload.get("status"),
                "check_count": len(payload.get("checks", [])),
                "output_tail": (completed.stdout + completed.stderr)[-3000:],
            }
    except Exception as exc:
        return {
            "passed": False,
            "mode": "temporary_output_replay",
            "error": f"{type(exc).__name__}: {exc}",
        }


def live_git_snapshot() -> dict[str, Any]:
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        lines = status.splitlines()
        return {
            "passed": len(lines) == 0,
            "git_available": True,
            "revision": revision,
            "worktree_clean": len(lines) == 0,
            "porcelain_line_count": len(lines),
        }
    except Exception as exc:
        return {
            "passed": False,
            "git_available": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


def make_gate_rows(
    delivery: Mapping[str, Any],
    gate_verification: Mapping[str, Any],
    runtime: Mapping[str, Any],
    templates: Mapping[str, Any],
    test_result: Mapping[str, Any],
    workshop: Mapping[str, Any],
    common_voltage: Mapping[str, Any],
    git: Mapping[str, Any],
) -> list[dict[str, Any]]:
    rows = [
        {
            "gate_id": "FINAL-01_MODEL_CLOSURE",
            "category": "TODAY_BLOCKER",
            "required_today": True,
            "status": "PASS" if delivery["model_phase_complete"] else "FAIL",
            "evidence": "project closure status",
        },
        {
            "gate_id": "FINAL-02_SCIENTIFIC_AUDITS",
            "category": "TODAY_BLOCKER",
            "required_today": True,
            "status": "PASS" if delivery["scientific_gates_pass"] else "FAIL",
            "evidence": "all top-level and nested audit checks",
        },
        {
            "gate_id": "FINAL-03_CLOSURE_GATE_SCHEMA",
            "category": "TODAY_BLOCKER",
            "required_today": True,
            "status": "PASS" if gate_verification["passed"] else "FAIL",
            "evidence": "exact 15-gate status contract",
        },
        {
            "gate_id": "FINAL-04_REPORT_AND_HASHES",
            "category": "TODAY_BLOCKER",
            "required_today": True,
            "status": (
                "PASS"
                if delivery["report_artifacts_pass"]
                and delivery["manifest_integrity_pass"]
                else "FAIL"
            ),
            "evidence": "final TeX/PDF and report manifest",
        },
        {
            "gate_id": "FINAL-05_RUNTIME",
            "category": "TODAY_BLOCKER",
            "required_today": True,
            "status": "PASS" if runtime["passed"] else "FAIL",
            "evidence": "declared Python dependency versions",
        },
        {
            "gate_id": "FINAL-06_HANDOFF_TEMPLATES",
            "category": "TODAY_BLOCKER",
            "required_today": True,
            "status": "PASS" if templates["passed"] else "FAIL",
            "evidence": "material, practical, receiver and architecture schemas",
        },
        {
            "gate_id": "FINAL-07_TEST_SUITE",
            "category": "TODAY_BLOCKER",
            "required_today": True,
            "status": "PASS" if test_result["passed"] else "FAIL",
            "evidence": test_result.get("mode", "unknown"),
        },
        {
            "gate_id": "FINAL-08_WORKSHOP_REPLAY",
            "category": "TODAY_BLOCKER",
            "required_today": True,
            "status": "PASS" if workshop["passed"] else "FAIL",
            "evidence": "temporary-output workshop verifier replay",
        },
        {
            "gate_id": "FINAL-09_COMMON_VOLTAGE_CLAIM_INTEGRITY",
            "category": "TODAY_BLOCKER",
            "required_today": True,
            "status": "PASS" if common_voltage["passed"] else "FAIL",
            "evidence": (
                "selected O30 rows resolved; unresolved rows fail closed; "
                "full-duty claim remains OPEN"
            ),
        },
        {
            "gate_id": "FINAL-10_COMMON_VOLTAGE_NUMERIC_CEILING_RETRY",
            "category": "TODAY_BLOCKER",
            "required_today": True,
            "status": (
                "PASS"
                if common_voltage.get("local_bracket_probe", {}).get("passed")
                is True
                else "FAIL"
            ),
            "evidence": (
                "exact all-flagged <=2 V coverage; only full closure may "
                "recover a retry"
            ),
        },
        {
            "gate_id": "FINAL-11_RELEASE_SNAPSHOT",
            "category": "RELEASE_FREEZE",
            "required_today": False,
            "status": "PASS" if git["passed"] else "OPEN",
            "evidence": (
                f"revision={git.get('revision', 'n/a')}; "
                f"dirty_lines={git.get('porcelain_line_count', 'n/a')}"
            ),
        },
    ]
    for gate_id in (
        "G04_FULL_DUTY_SINGLE_BUS",
        "G09B_CANDIDATE_DATA_COMPLETENESS",
        "G10_RECEIVER_CONTRACT",
        "G11_PRACTICAL_LIMITS",
    ):
        rows.append(
            {
                "gate_id": gate_id,
                "category": "NEXT_PHASE_EMPIRICAL",
                "required_today": False,
                "status": "OPEN",
                "evidence": "accepted next-phase input; does not reopen broad modelling",
            }
        )
    return rows


def write_gate_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fieldnames = ["gate_id", "category", "required_today", "status", "evidence"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_summary(path: Path, result: Mapping[str, Any]) -> None:
    lines = [
        "# Final delivery check v1",
        "",
        f"**Model-phase delivery ready today:** {result['delivery_ready_today']}",
        f"**Release snapshot ready:** {result['release_snapshot_ready']}",
        f"**Ready to archive today:** {result['ready_to_archive_today']}",
        f"**Material search can start:** {result['material_search_can_start']}",
        "",
        "## Interpretation",
        "",
        (
            "The broad model phase is deliverable. Open candidate, receiver, practical "
            "and architecture gates are measurements and decisions for the next phase, "
            "not reasons to resume unfocused parameter sweeps."
            if result["delivery_ready_today"]
            else "One or more delivery-critical checks failed; see gate_register.csv."
        ),
        "",
        "## Remaining actions",
        "",
    ]
    for action in result["remaining_actions"]:
        lines.append(f"- {action}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(
    config_path: Path,
    output_dir: Path,
    *,
    overwrite: bool,
    run_tests: bool,
    require_clean_git: bool,
    timeout_seconds: int,
) -> dict[str, Any]:
    config_path = config_path.resolve()
    output_dir = output_dir.resolve()
    known = (
        "status.json",
        "gate_register.csv",
        "SUMMARY.md",
        "test_run.json",
        "source_manifest.json",
    )
    if output_dir.exists() and not overwrite:
        existing = [output_dir / name for name in known if (output_dir / name).exists()]
        if existing:
            raise FinalDeliveryCheckError(
                "Final-delivery outputs exist; use --overwrite to replace them"
            )
    output_dir.mkdir(parents=True, exist_ok=True)

    config = load_json(config_path)
    paths = {
        key: resolve_path(value) for key, value in config["paths"].items()
    }
    closure_status = load_json(paths["closure_status"])
    closure_gates = verify_closure_gate_register(
        paths["closure_gates"], config
    )
    report_manifest = load_json(paths["report_manifest"])
    report_hashes = verify_hash_manifest(paths["report_manifest"])

    scientific_audits: list[dict[str, Any]] = []
    embedded_manifests: list[dict[str, Any]] = []
    input_paths: list[Path] = [
        config_path,
        Path(__file__).resolve(),
        paths["closure_status"],
        paths["closure_gates"],
        paths["closure_source_manifest"],
        paths["report_manifest"],
        paths["report_tex"],
        paths["report_pdf"],
    ]
    for spec in config["scientific_audits"]:
        audit_path = resolve_path(spec["path"])
        audit = load_json(audit_path)
        audit["audit_id"] = str(spec["audit_id"])
        scientific_audits.append(audit)
        input_paths.append(audit_path)
        manifest_value = spec.get("source_manifest_path")
        if manifest_value:
            manifest_path = resolve_path(manifest_value)
            embedded_manifests.append(
                verify_embedded_source_manifest(manifest_path)
            )
            input_paths.append(manifest_path)
    for value in config.get("additional_source_manifests", []):
        manifest_path = resolve_path(value)
        embedded_manifests.append(
            verify_embedded_source_manifest(manifest_path)
        )
        input_paths.append(manifest_path)
    embedded_manifests.append(
        verify_embedded_source_manifest(paths["closure_source_manifest"])
    )
    source_manifest_verification = {
        "passed": bool(
            embedded_manifests
            and all(item["passed"] for item in embedded_manifests)
        ),
        "manifest_count": len(embedded_manifests),
        "failed_manifest_count": sum(
            not item["passed"] for item in embedded_manifests
        ),
        "manifests": embedded_manifests,
    }

    runtime = verify_runtime(config["runtime_requirements"])
    templates = verify_handoff_templates(config, paths)
    input_paths.extend(
        paths[key]
        for key in (
            "material_requirements",
            "material_candidate_template",
            "practical_gate_template",
            "receiver_thermal_ledger_template",
            "architecture_decision_template",
        )
    )
    tests = (
        run_pytest(timeout_seconds)
        if run_tests
        else frozen_test_evidence(report_manifest)
    )
    workshop = run_workshop_verifier(timeout_seconds)
    common_voltage = verify_common_voltage_claim_integrity(
        paths["common_voltage_cases"],
        paths["common_voltage_envelope"],
        paths["common_voltage_local_probe"],
        config["common_voltage_claim_integrity"],
    )
    input_paths.extend(
        paths[key]
        for key in (
            "common_voltage_cases",
            "common_voltage_envelope",
            "common_voltage_local_probe",
        )
    )

    delivery = evaluate_delivery(
        closure_status=closure_status,
        scientific_audits=scientific_audits,
        manifest_verification=report_hashes,
        report_tex_path=paths["report_tex"],
        report_pdf_path=paths["report_pdf"],
        closure_gate_verification=closure_gates,
        source_manifest_verification=source_manifest_verification,
        runtime_verification=runtime,
        template_verification=templates,
        test_verification=tests,
        workshop_replay_verification=workshop,
        common_voltage_claim_verification=common_voltage,
    )
    git = live_git_snapshot()
    release_snapshot_ready = git.get("passed") is True
    ready_to_archive_today = bool(
        delivery["delivery_ready_today"] and release_snapshot_ready
    )
    remaining_actions = [
        "Freeze the reviewed repository in a commit/tag or other immutable release snapshot."
        if not release_snapshot_ready
        else "No release-snapshot action remains.",
        "Populate one same-sample MAT-01 through MAT-09 candidate dataset before ranking materials.",
        "Close REC-01 through REC-10 before claiming receiver, liquid-product or net-system performance.",
        "Set PRACT-01 through PRACT-10 and complete ARCH-01 through ARCH-08 before selecting the architecture.",
    ]
    result = {
        "schema_version": 1,
        "study_id": config["study_id"],
        "script_version": SCRIPT_VERSION,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        **delivery,
        "model_phase_delivery_ready": delivery["delivery_ready_today"],
        "release_snapshot_ready": release_snapshot_ready,
        "ready_to_archive_today": ready_to_archive_today,
        "material_search_can_start": bool(
            delivery["delivery_ready_today"]
            and closure_status.get("material_data_collection_ready") is True
        ),
        "next_phase_empirical_ready": bool(
            closure_status.get("material_candidate_ranking_ready") is True
        ),
        "candidate_ranking_ready": bool(
            closure_status.get("material_candidate_ranking_ready") is True
        ),
        "full_system_claim_allowed": bool(
            closure_status.get("full_system_claim_allowed") is True
        ),
        "technology_validated": bool(
            closure_status.get("technology_validated") is True
        ),
        "require_clean_git": require_clean_git,
        "closure_gate_verification": closure_gates,
        "report_manifest_verification": report_hashes,
        "source_manifest_verification": source_manifest_verification,
        "runtime_verification": runtime,
        "template_verification": templates,
        "test_verification": tests,
        "workshop_replay_verification": workshop,
        "common_voltage_claim_verification": common_voltage,
        "git_snapshot": git,
        "remaining_actions": remaining_actions,
    }
    rows = make_gate_rows(
        result,
        closure_gates,
        runtime,
        templates,
        tests,
        workshop,
        common_voltage,
        git,
    )
    result["gate_register"] = rows

    write_json(output_dir / "status.json", result)
    write_gate_csv(output_dir / "gate_register.csv", rows)
    write_summary(output_dir / "SUMMARY.md", result)
    write_json(output_dir / "test_run.json", tests)
    source_manifest = {
        "schema_version": 1,
        "study_id": config["study_id"],
        "script_version": SCRIPT_VERSION,
        "generated_utc": result["generated_utc"],
        "inputs": [file_record(path) for path in sorted(set(input_paths))],
    }
    write_json(output_dir / "source_manifest.json", source_manifest)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--run-tests",
        action="store_true",
        help="Run the complete pytest suite instead of using frozen test evidence.",
    )
    parser.add_argument(
        "--require-clean-git",
        action="store_true",
        help="Return nonzero unless both model delivery and release snapshot pass.",
    )
    parser.add_argument("--timeout-seconds", type=int, default=900)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run(
        args.config,
        args.output_dir,
        overwrite=args.overwrite,
        run_tests=args.run_tests,
        require_clean_git=args.require_clean_git,
        timeout_seconds=args.timeout_seconds,
    )
    headline = {
        key: result[key]
        for key in (
            "model_phase_delivery_ready",
            "release_snapshot_ready",
            "ready_to_archive_today",
            "material_search_can_start",
            "candidate_ranking_ready",
            "full_system_claim_allowed",
            "technology_validated",
            "blocking_items",
        )
    }
    print(json.dumps(headline, indent=2, ensure_ascii=False))
    print(f"Wrote final delivery check to {args.output_dir.resolve()}")
    if not result["model_phase_delivery_ready"]:
        return 2
    if args.require_clean_git and not result["release_snapshot_ready"]:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
