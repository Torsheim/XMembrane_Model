#!/usr/bin/env python3
"""Promote a completed low-voltage candidate without rewriting its history.

The expensive V50/V53 physics was executed in the dated candidate directory.
This script verifies that the canonical physics tree is byte-identical to that
executed candidate, records the promotion lineage explicitly, and regenerates
only the inexpensive canonical analysis/audits.  It never claims that the
physics generator command was executed in the canonical directory.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CANDIDATE = (
    ROOT / "outputs" / "direct_eo_low_voltage_study_v1_candidate_20260826"
)
DEFAULT_CANONICAL = ROOT / "outputs" / "direct_eo_low_voltage_study_v1"
DEFAULT_CONFIG = ROOT / "config" / "direct_eo_low_voltage_study_v1.json"
RUNNER = Path(__file__).with_name("run_direct_eo_low_voltage_study_v1.py")
ANALYZER = Path(__file__).with_name("analyze_direct_eo_low_voltage_study_v1.py")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-root", type=Path, default=DEFAULT_CANDIDATE)
    parser.add_argument("--canonical-root", type=Path, default=DEFAULT_CANONICAL)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    return {
        "path": str(resolved),
        "sha256": sha256_file(resolved),
        "size_bytes": resolved.stat().st_size,
    }


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def tree_manifest(root: Path) -> dict[str, dict[str, Any]]:
    if not root.is_dir():
        raise FileNotFoundError(root)
    manifest: dict[str, dict[str, Any]] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        manifest[relative] = {
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
    return manifest


def validate_original_execution(
    candidate: Path, config: Path
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    source_path = candidate / "source_generator_provenance.json"
    study_path = candidate / "study_audit.json"
    command_path = candidate / "generator_command.json"
    source = load_json(source_path)
    study = load_json(study_path)
    command = load_json(command_path)
    if source.get("status") != "PASS" or source.get("smoke") is not False:
        raise ValueError("Candidate source provenance is not a full PASS")
    if study.get("status") != "PASS":
        raise ValueError("Candidate study audit is not PASS")
    if source.get("command") != command.get("command"):
        raise ValueError("Candidate command file differs from executed source command")
    if source["config"]["sha256"] != sha256_file(config):
        raise ValueError("Candidate provenance config hash differs from live config")
    if source["runner"]["sha256"] != sha256_file(RUNNER):
        raise ValueError("Candidate provenance runner hash differs from live runner")
    if source["analyzer"]["sha256"] != sha256_file(ANALYZER):
        raise ValueError("Candidate provenance analyzer hash differs from live analyzer")
    for item in source.get("source_scripts", {}).values():
        path = Path(str(item["path"]))
        if sha256_file(path) != item["sha256"]:
            raise ValueError(f"Source model changed after execution: {path}")
    if study["source_generator_provenance"]["sha256"] != sha256_file(source_path):
        raise ValueError("Candidate study audit does not bind its source provenance")
    return source, study, command


def verify_key_physics_records(
    source: dict[str, Any], candidate_physics: Path
) -> None:
    expected = source["physics_outputs"]
    mapping = {
        "register": candidate_physics / "joint_material_operating_gate_register.csv",
        "assumptions_v53": candidate_physics / "assumptions_v53.csv",
        "v50_assumptions": candidate_physics / "_v50_full_grid" / "assumptions.csv",
    }
    for name, path in mapping.items():
        if sha256_file(path) != expected[name]["sha256"]:
            raise ValueError(f"Candidate physics key hash mismatch: {name}")


def main() -> int:
    args = parse_args()
    candidate = args.candidate_root.resolve()
    canonical = args.canonical_root.resolve()
    config = args.config.resolve()
    if candidate == canonical:
        raise ValueError("Candidate and canonical roots must differ")
    source, candidate_study, original_command_file = validate_original_execution(
        candidate, config
    )
    candidate_physics = candidate / "physics"
    canonical_physics = canonical / "physics"
    verify_key_physics_records(source, candidate_physics)
    candidate_manifest = tree_manifest(candidate_physics)
    canonical_manifest = tree_manifest(canonical_physics)
    if candidate_manifest != canonical_manifest:
        missing = sorted(set(candidate_manifest) - set(canonical_manifest))
        extra = sorted(set(canonical_manifest) - set(candidate_manifest))
        changed = sorted(
            key
            for key in set(candidate_manifest) & set(canonical_manifest)
            if candidate_manifest[key] != canonical_manifest[key]
        )
        raise ValueError(
            "Canonical physics is not byte-identical to candidate: "
            f"missing={missing[:5]}, extra={extra[:5]}, changed={changed[:5]}"
        )

    canonical.mkdir(parents=True, exist_ok=True)
    promotion = {
        "schema_version": 1,
        "study_id": source["study_id"],
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS",
        "execution_mode": "HASH_IDENTICAL_PHYSICS_PROMOTION",
        "physics_generator_executed_in_canonical_root": False,
        "original_execution_root": str(candidate),
        "canonical_root": str(canonical),
        "original_generator_command": record(candidate / "generator_command.json"),
        "original_source_generator_provenance": record(
            candidate / "source_generator_provenance.json"
        ),
        "original_study_audit": record(candidate / "study_audit.json"),
        "live_config": record(config),
        "live_runner": record(RUNNER),
        "live_analyzer": record(ANALYZER),
        "physics_tree_identity": {
            "passed": True,
            "file_count": len(candidate_manifest),
            "candidate_physics_root": str(candidate_physics),
            "canonical_physics_root": str(canonical_physics),
            "files": candidate_manifest,
        },
        "semantics": {
            "physics_values_recomputed_during_promotion": False,
            "canonical_analysis_regenerated": True,
            "internal_assumptions_paths_refer_to_original_execution_root": True,
            "full_system_claim_allowed": False,
        },
    }
    promotion_path = canonical / "promotion_provenance.json"
    write_json(promotion_path, promotion)

    generator_record = {
        "schema_version": 2,
        "execution_mode": "HASH_IDENTICAL_PHYSICS_PROMOTION",
        "physics_generator_executed_in_this_root": False,
        "original_execution_root": str(candidate),
        "original_executed_command": original_command_file["command"],
        "original_generator_command": record(candidate / "generator_command.json"),
        "promotion_provenance": record(promotion_path),
    }
    write_json(canonical / "generator_command.json", generator_record)

    canonical_physics_records = {
        "register": record(
            canonical_physics / "joint_material_operating_gate_register.csv"
        ),
        "assumptions_v53": record(canonical_physics / "assumptions_v53.csv"),
        "v50_assumptions": record(
            canonical_physics / "_v50_full_grid" / "assumptions.csv"
        ),
        "observed_cap_rows": source["physics_outputs"]["observed_cap_rows"],
        "observed_physical_coordinates": source["physics_outputs"][
            "observed_physical_coordinates"
        ],
        "expected_cap_rows": source["physics_outputs"]["expected_cap_rows"],
        "expected_physical_coordinates": source["physics_outputs"][
            "expected_physical_coordinates"
        ],
        "all_acceptance_caps_at_or_below_2v": True,
        "receiver_sink_energy_zero_in_source": True,
    }
    canonical_source = {
        "schema_version": 2,
        "study_id": source["study_id"],
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS",
        "smoke": False,
        "execution_mode": "HASH_IDENTICAL_PHYSICS_PROMOTION",
        "physics_generator_executed_in_canonical_root": False,
        "original_execution_root": str(candidate),
        "command": source["command"],
        "command_execution_root": str(candidate),
        "config": record(config),
        "runner": record(RUNNER),
        "analyzer": record(ANALYZER),
        "source_scripts": source["source_scripts"],
        "physics_outputs": canonical_physics_records,
        "original_source_generator_provenance": record(
            candidate / "source_generator_provenance.json"
        ),
        "promotion_provenance": record(promotion_path),
        "semantics": {
            **source["semantics"],
            "physics_values_recomputed_during_promotion": False,
            "canonical_analysis_regenerated": True,
            "internal_assumptions_paths_refer_to_original_execution_root": True,
        },
    }
    source_path = canonical / "source_generator_provenance.json"
    write_json(source_path, canonical_source)

    analysis_dir = canonical / "analysis"
    analyze_command = [
        sys.executable,
        "-B",
        str(ANALYZER),
        "--config",
        str(config),
        "--source-register",
        str(canonical_physics / "joint_material_operating_gate_register.csv"),
        "--source-assumptions",
        str(canonical_physics / "assumptions_v53.csv"),
        "--source-provenance",
        str(source_path),
        "--out-dir",
        str(analysis_dir),
    ]
    subprocess.run(analyze_command, check=True, cwd=ROOT)
    analysis_audit_path = analysis_dir / "analysis_audit.json"
    analysis_audit = load_json(analysis_audit_path)
    if analysis_audit.get("status") != "PASS":
        raise RuntimeError("Regenerated canonical analysis audit is not PASS")

    study_audit = {
        "schema_version": 2,
        "study_id": source["study_id"],
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS",
        "execution_mode": "HASH_IDENTICAL_PHYSICS_PROMOTION",
        "physics_generator_executed_in_canonical_root": False,
        "config": record(config),
        "runner": record(RUNNER),
        "promoter": record(Path(__file__)),
        "analyzer": record(ANALYZER),
        "promotion_provenance": record(promotion_path),
        "original_source_generator_provenance": record(
            candidate / "source_generator_provenance.json"
        ),
        "source_generator_provenance": record(source_path),
        "analysis_audit": record(analysis_audit_path),
        "physics_register": record(
            canonical_physics / "joint_material_operating_gate_register.csv"
        ),
        "physics_tree_identity_passed": True,
        "physics_tree_file_count": len(candidate_manifest),
        "claim_boundary": candidate_study["claim_boundary"],
    }
    write_json(canonical / "study_audit.json", study_audit)
    print(
        "Canonical low-voltage promotion PASS: "
        f"{len(candidate_manifest)} physics files are byte-identical; "
        "canonical analysis regenerated."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        FileNotFoundError,
        RuntimeError,
        ValueError,
        subprocess.CalledProcessError,
    ) as error:
        raise SystemExit(f"ERROR: {error}") from error
