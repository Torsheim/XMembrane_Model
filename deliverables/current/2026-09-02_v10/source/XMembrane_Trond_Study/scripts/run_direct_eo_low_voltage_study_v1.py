#!/usr/bin/env python3
"""Run the separate hash-bound direct-EO <=2 V candidate study.

This runner never writes into membrane_operating_region_study_v1 or its V4
report outputs.  It drives the unchanged V50/V53 source model with a new grid,
writes source provenance, invokes the dedicated analyzer, and refuses to call
the study complete unless both source and analysis audits pass.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "direct_eo_low_voltage_study_v1.json"
DEFAULT_OUTPUT = ROOT / "outputs" / "direct_eo_low_voltage_study_v1_candidate_20260826"
ANALYZER = Path(__file__).with_name("analyze_direct_eo_low_voltage_study_v1.py")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--reuse-physics",
        action="store_true",
        help="Reuse an existing physics register only after its source provenance validates.",
    )
    parser.add_argument(
        "--require-empty-out-root",
        action="store_true",
        help="Refuse any pre-existing files. Intended for the first candidate run.",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Run a tiny command-contract smoke grid. Smoke output cannot pass the full analysis audit.",
    )
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def record(path: Path) -> dict[str, object]:
    resolved = path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    return {
        "path": str(resolved),
        "sha256": sha256_file(resolved),
        "size_bytes": resolved.stat().st_size,
    }


def load_config(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise FileNotFoundError(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("Unsupported low-voltage study config")
    caps = list(map(float, payload["grid"]["cell_voltage_caps_v"]))
    if max(caps) > 2.0:
        raise ValueError("Acceptance cap above 2 V is forbidden in this runner")
    if payload["gates"].get("engineering_current_density_limit_a_m2") is not None:
        raise ValueError("Current-density acceptance limit is forbidden")
    return payload


def expected_counts(config: dict[str, object]) -> tuple[int, int]:
    grid = config["grid"]
    physical = 1
    for name in (
        "current_density_a_m2",
        "transport_number_reference_t_w",
        "water_diffusivity_scale_vs_pfsa",
        "dry_thickness_um",
        "ionic_area_resistance_ohm_m2_at_lambda_ref",
        "retention_factor_vs_pfsa_sorption",
        "receiver_control_activity",
    ):
        physical *= len(grid[name])
    return physical, physical * len(grid["cell_voltage_caps_v"])


def list_values(command: list[str], flag: str, values: list[float]) -> None:
    command.append(flag)
    command.extend(f"{float(value):.12g}" for value in values)


def generator_command(
    config: dict[str, object], physics_dir: Path, smoke: bool
) -> list[str]:
    model = config["source_model"]
    grid = config["grid"]
    command = [
        sys.executable,
        "-B",
        str(Path(model["v53_generator"])),
        "--out-dir",
        str(physics_dir),
        "--screening-voltage-cap-v",
        f"{float(model['calculation_ceiling_v']):.12g}",
        "--process-surface-activity-min",
        f"{float(model['process_surface_activity_screen_min']):.12g}",
        "--preferred-area-m2",
        f"{float(model['preferred_area_diagnostic_m2']):.12g}",
        "--hard-area-cap-m2",
        f"{float(model['hard_area_screen_m2']):.12g}",
    ]
    if smoke:
        axes = {
            "current_density_a_m2": [10.0, 50.0],
            "transport_number_reference_t_w": [35.0, 120.0],
            "water_diffusivity_scale_vs_pfsa": [0.003, 0.6],
            "dry_thickness_um": [20.0],
            "ionic_area_resistance_ohm_m2_at_lambda_ref": [5e-6],
            "retention_factor_vs_pfsa_sorption": [1.25],
            "receiver_control_activity": [0.8],
            "cell_voltage_caps_v": [1.5, 2.0],
        }
    else:
        axes = grid
    list_values(command, "--cell-voltage-caps-v", axes["cell_voltage_caps_v"])
    list_values(
        command,
        "--operating-current-densities-a-m2",
        axes["current_density_a_m2"],
    )
    list_values(
        command,
        "--reference-transport-numbers",
        axes["transport_number_reference_t_w"],
    )
    list_values(command, "--diffusivity-scales", axes["water_diffusivity_scale_vs_pfsa"])
    list_values(
        command,
        "--area-resistances-ohm-m2",
        axes["ionic_area_resistance_ohm_m2_at_lambda_ref"],
    )
    list_values(command, "--dry-thicknesses-um", axes["dry_thickness_um"])
    list_values(
        command,
        "--retention-factors",
        axes["retention_factor_vs_pfsa_sorption"],
    )
    list_values(
        command,
        "--receiver-control-activities",
        axes["receiver_control_activity"],
    )
    list_values(command, "--saving-targets-kw", [0.0, 400.0, 425.0])
    return command


def source_chain(generator: Path) -> list[Path]:
    scripts = generator.parent
    names = [
        "make_wp1_symmetric_wet_receiver_sink_v53.py",
        "make_wp1_symmetric_wet_receiver_sink_v50.py",
        "make_wp1_symmetric_wet_receiver_sink_v49.py",
        "make_wp1_symmetric_wet_receiver_sink_v48.py",
        "make_wp1_symmetric_wet_receiver_sink_v47.py",
        "make_wp1_symmetric_wet_receiver_sink_v46.py",
        "make_wp1_countercurrent_geometry_gate_v41.py",
        "make_wp1_material_property_space_v43.py",
    ]
    return [scripts / name for name in names]


def verify_physics_outputs(
    config: dict[str, object], physics_dir: Path, smoke: bool
) -> dict[str, object]:
    register = physics_dir / "joint_material_operating_gate_register.csv"
    assumptions = physics_dir / "assumptions_v53.csv"
    full_grid_assumptions = physics_dir / "_v50_full_grid" / "assumptions.csv"
    for path in (register, assumptions, full_grid_assumptions):
        if not path.is_file():
            raise FileNotFoundError(path)
    usecols = [
        "current_density_a_m2",
        "transport_number_reference_t_w",
        "water_diffusivity_scale_vs_pfsa",
        "cell_voltage_cap_tested_v",
        "receiver_sink_energy_kw_assumed",
    ]
    frame = pd.read_csv(register, usecols=usecols)
    observed_physical = frame.drop(columns="cell_voltage_cap_tested_v").drop_duplicates().shape[0]
    expected_physical, expected_rows = expected_counts(config)
    if not smoke and (len(frame) != expected_rows or observed_physical != expected_physical):
        raise ValueError(
            f"Generated count mismatch: rows {len(frame)}/{expected_rows}, "
            f"physical {observed_physical}/{expected_physical}"
        )
    if frame["cell_voltage_cap_tested_v"].max() > 2.0:
        raise ValueError("Generated acceptance register contains cap above 2 V")
    if not (frame["receiver_sink_energy_kw_assumed"].abs() <= 1e-12).all():
        raise ValueError("Source unexpectedly includes non-zero receiver energy")
    return {
        "register": record(register),
        "assumptions_v53": record(assumptions),
        "v50_assumptions": record(full_grid_assumptions),
        "observed_cap_rows": len(frame),
        "observed_physical_coordinates": observed_physical,
        "expected_cap_rows": expected_rows if not smoke else None,
        "expected_physical_coordinates": expected_physical if not smoke else None,
        "all_acceptance_caps_at_or_below_2v": True,
        "receiver_sink_energy_zero_in_source": True,
    }


def write_source_provenance(
    path: Path,
    config_path: Path,
    config: dict[str, object],
    command: list[str],
    physics: dict[str, object],
    smoke: bool,
) -> dict[str, object]:
    generator = Path(config["source_model"]["v53_generator"])
    payload = {
        "schema_version": 1,
        "study_id": config["study_id"],
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "status": "SMOKE_PASS" if smoke else "PASS",
        "smoke": smoke,
        "command": command,
        "config": record(config_path),
        "runner": record(Path(__file__)),
        "analyzer": record(ANALYZER),
        "source_scripts": {item.name: record(item) for item in source_chain(generator)},
        "physics_outputs": physics,
        "semantics": {
            "calculation_ceiling_is_acceptance_cap": False,
            "all_acceptance_caps_at_or_below_2v": True,
            "current_density_acceptance_limit_a_m2": None,
            "receiver_energy_status": "UNKNOWN",
            "full_system_claim_allowed": False,
        },
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def validate_reuse_provenance(path: Path, config_path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError("Cannot reuse physics without source provenance")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("status") != "PASS" or payload.get("smoke"):
        raise ValueError("Only a full PASS source provenance may be reused")
    if payload["config"]["sha256"] != sha256_file(config_path):
        raise ValueError("Reuse provenance config hash differs from live config")
    if payload["runner"]["sha256"] != sha256_file(Path(__file__)):
        raise ValueError("Reuse provenance runner hash differs from live runner")
    if payload["analyzer"]["sha256"] != sha256_file(ANALYZER):
        raise ValueError("Reuse provenance analyzer hash differs from live analyzer")


def main() -> int:
    args = parse_args()
    # The V53 subprocess runs from the HeiQ_V2 repository so its legacy
    # imports resolve.  Resolve the candidate root first; otherwise a relative
    # --out-root would silently be interpreted below HeiQ_V2 instead of this
    # study repository.
    args.out_root = args.out_root.resolve()
    args.config = args.config.resolve()
    config = load_config(args.config)
    if args.require_empty_out_root and args.out_root.exists() and any(args.out_root.iterdir()):
        raise ValueError(f"Refusing non-empty candidate root: {args.out_root}")
    args.out_root.mkdir(parents=True, exist_ok=True)
    physics_dir = args.out_root / "physics"
    analysis_dir = args.out_root / "analysis"
    source_provenance_path = args.out_root / "source_generator_provenance.json"
    command = generator_command(config, physics_dir, args.smoke)
    (args.out_root / "generator_command.json").write_text(
        json.dumps({"command": command}, indent=2) + "\n", encoding="utf-8"
    )

    if args.reuse_physics:
        validate_reuse_provenance(source_provenance_path, args.config)
        print("Reusing hash-validated low-voltage physics grid.", flush=True)
    else:
        print("Running new V50/V53 low-voltage physics grid ...", flush=True)
        subprocess.run(command, check=True, cwd=ROOT.parent / "HeiQ_V2")
    physics = verify_physics_outputs(config, physics_dir, args.smoke)
    write_source_provenance(
        source_provenance_path, args.config, config, command, physics, args.smoke
    )
    if args.smoke:
        print(f"Smoke physics contract PASS: {args.out_root}")
        return 0

    analyze_command = [
        sys.executable,
        "-B",
        str(ANALYZER),
        "--config",
        str(args.config),
        "--source-register",
        str(physics_dir / "joint_material_operating_gate_register.csv"),
        "--source-assumptions",
        str(physics_dir / "assumptions_v53.csv"),
        "--source-provenance",
        str(source_provenance_path),
        "--out-dir",
        str(analysis_dir),
    ]
    if not args.reuse_physics:
        analyze_command.append("--require-empty-out-dir")
    print("Running dedicated <=2 V analysis and audit ...", flush=True)
    subprocess.run(analyze_command, check=True, cwd=ROOT)
    analysis_audit_path = analysis_dir / "analysis_audit.json"
    analysis_audit = json.loads(analysis_audit_path.read_text(encoding="utf-8"))
    if analysis_audit.get("status") != "PASS":
        raise RuntimeError("Analysis audit did not pass")
    study_audit = {
        "schema_version": 1,
        "study_id": config["study_id"],
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS",
        "config": record(args.config),
        "runner": record(Path(__file__)),
        "analyzer": record(ANALYZER),
        "source_generator_provenance": record(source_provenance_path),
        "analysis_audit": record(analysis_audit_path),
        "physics_register": record(
            physics_dir / "joint_material_operating_gate_register.csv"
        ),
        "claim_boundary": config["claim_boundary"],
    }
    (args.out_root / "study_audit.json").write_text(
        json.dumps(study_audit, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Direct EO <=2 V candidate study PASS: {args.out_root}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"ERROR: {error}") from error
