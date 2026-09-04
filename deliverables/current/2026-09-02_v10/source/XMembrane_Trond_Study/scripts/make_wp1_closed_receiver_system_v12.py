#!/usr/bin/env python3
"""Coupled process/receiver and declared-system analysis for selected V11 materials.

V12 keeps the validated V2/V3 local membrane law, but removes V11's prescribed
receiver activity.  At every axial area step it solves the local membrane state
with the *current* process and receiver bulk water activities, then advances
both dry-air streams with the same transferred water flux.

The study is deliberately limited to selected hypothetical V11 property
combinations.  It is not a new global material search and it does not validate
that M08666, M08786 or M11675 is physically realisable.

The energy output is a declared incremental budget against the previously
calculated gross HVAC opportunity.  It is not a percentage reduction in total
building or HVAC energy.  Regeneration, external pressure loss, product-water
pumping and thermal management are explicit assumptions or sensitivities.

Run from the HeiQ_V2 repository root::

    python3 -B scripts/make_wp1_closed_receiver_system_v12.py \
      outputs/axial_independent_material_sweep_v8/coarse/voltage_refinement_v11 \
      --mode smoke --workers 2

    python3 -B scripts/make_wp1_closed_receiver_system_v12.py \
      outputs/axial_independent_material_sweep_v8/coarse/voltage_refinement_v11 \
      --mode study --workers 8

The V11 source files are read-only.  V12 writes a new child directory named
``closed_receiver_system_v12`` unless ``--output-dir`` is supplied.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import copy
from dataclasses import asdict, dataclass
import gzip
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
from types import ModuleType
from typing import Any, Iterable, Mapping, Sequence
import uuid

os.environ.setdefault("MPLCONFIGDIR", "/tmp/heiq-v12-closed-receiver-mpl")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


SCRIPT_VERSION = "v12.1-reviewed-coupled-receiver-2026-08-03"
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = Path(__file__).with_name("closed_receiver_system_v12_config.json")
DEFAULT_V11_DIR = (
    REPO_ROOT
    / "outputs"
    / "axial_independent_material_sweep_v8"
    / "coarse"
    / "voltage_refinement_v11"
)
DEFAULT_AXIAL_SCRIPT = Path(__file__).with_name("make_wp1_pre_receiver_axial_v3.py")
DEFAULT_V2_ROOT = REPO_ROOT / "heiq_pre_receiver_material_analyses"
DEFAULT_OUTPUT_NAME = "closed_receiver_system_v12"

MOLAR_MASS_WATER_KG_MOL = 0.01801528
R_DRY_AIR_J_KG_K = 287.055
REQUIRED_V11_SCRIPT_VERSION = "v11.1-target-order-fix-2026-08-03"
V11_FINAL_DATASET = "axial_free_sweep_all_cases.csv.gz"

MATERIAL_COLUMNS = [
    "water_drag",
    "water_diffusivity_m2_s",
    "conductivity_s_m",
    "dry_thickness_um",
    "water_capacity_mol_m3_activity",
    "diffusivity_activity_exponent",
    "conductivity_activity_exponent",
    "capacity_activity_exponent",
]

REQUIRED_V11_TRUE_FIELDS = [
    "analysis_complete",
    "source_coverage_pass",
    "source_balance_pass",
    "source_semantic_status_pass",
    "refined_coverage_pass",
    "refined_balance_pass",
    "refined_semantic_status_pass",
    "checkpoint_structure_pass",
    "anchor_reproduction_pass",
    "coarse_refinement_regression_pass",
]

REQUIRED_V11_COUNTS = {
    "source_row_count": 32_256,
    "refined_row_count": 2_808,
    "candidate_material_count": 12,
    "refined_voltage_count": 117,
    "anchor_row_count": 168,
    "expected_anchor_row_count": 168,
}

V11_CASE_COLUMNS = [
    "material_id",
    *MATERIAL_COLUMNS,
    "receiver_boundary",
    "target",
    "terminal_voltage_v",
    "status",
    "target_reached",
    "prerequisite_short_circuit",
    "worker_exception",
    "gross_hvac_electric_opportunity_kw",
]

V11_AUDIT_FILES = [
    "refinement_coverage_audit.csv",
    "refinement_balance_audit.csv",
    "refinement_semantic_status_audit.csv",
    "checkpoint_audit.csv",
    "v8_anchor_reproduction.csv",
    "coarse_vs_refined_scenario_comparison.csv",
]

CHECKPOINT_RESULT_COLUMNS = {
    "status",
    "target_reached",
    "water_balance_evaluated",
    "water_balance_pass",
    "local_solver_evaluated",
    "worker_exception",
}

_WORKER_CONTEXT: dict[str, Any] = {}


@dataclass(frozen=True)
class ReceiverBasis:
    """One receiver-loop dry-air basis for a target and humidity band."""

    band_id: str
    receiver_sizing_target: str
    flow_arrangement: str
    temperature_c: float
    pressure_pa: float
    inlet_activity: float
    maximum_outlet_activity: float
    inlet_humidity_ratio_kg_kg_da: float
    maximum_outlet_humidity_ratio_kg_kg_da: float
    target_outlet_humidity_ratio_kg_kg_da: float
    minimum_dry_air_mass_flow_kg_s: float
    selected_dry_air_mass_flow_kg_s: float
    selected_actual_volume_flow_m3_s: float
    selected_actual_airflow_cfm: float
    capacity_multiplier: float
    receiver_geometry_mode: str
    receiver_total_channel_width_m: float
    receiver_velocity_m_s: float
    receiver_to_process_dry_air_ratio: float
    target_capacity_sufficient: bool


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value


def unique_temporary_sibling(path: Path) -> Path:
    return path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = unique_temporary_sibling(path)
    try:
        temporary.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = unique_temporary_sibling(path)
    try:
        temporary.write_text(value, encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_csv(
    frame: pd.DataFrame,
    path: Path,
    *,
    compression: str | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = unique_temporary_sibling(path)
    try:
        frame.to_csv(temporary, index=False, compression=compression)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_fingerprint(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load Python module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def strict_bool_value(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)) and int(value) in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalised = value.strip().lower()
        if normalised in {"true", "1"}:
            return True
        if normalised in {"false", "0"}:
            return False
    raise ValueError(f"Invalid boolean value: {value!r}")


def strict_boolean_series(series: pd.Series) -> pd.Series:
    return series.map(strict_bool_value).astype(bool)


def finite_float(value: Any, label: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite, got {value!r}")
    return result


def validate_fraction(value: Any, label: str, *, allow_one: bool = True) -> float:
    result = finite_float(value, label)
    upper_ok = result <= 1.0 if allow_one else result < 1.0
    if result <= 0.0 or not upper_ok:
        bracket = "(0, 1]" if allow_one else "(0, 1)"
        raise ValueError(f"{label} must lie in {bracket}")
    return result


def validate_nonnegative(value: Any, label: str) -> float:
    result = finite_float(value, label)
    if result < 0.0:
        raise ValueError(f"{label} must be non-negative")
    return result


def validate_positive(value: Any, label: str) -> float:
    result = finite_float(value, label)
    if result <= 0.0:
        raise ValueError(f"{label} must be positive")
    return result


def validate_config(config: Mapping[str, Any]) -> None:
    required = {
        "schema_version",
        "candidate_material_ids",
        "receiver_bands",
        "voltage_grid",
        "operating",
        "channel",
        "integration",
        "stack",
        "energy_scenarios",
        "regression_anchors",
        "modes",
    }
    missing = required.difference(config)
    if missing:
        raise ValueError(f"V12 config is missing keys: {sorted(missing)}")
    if int(config["schema_version"]) != 1:
        raise ValueError("Only V12 config schema_version=1 is supported")
    candidates = [str(value) for value in config["candidate_material_ids"]]
    if len(candidates) != len(set(candidates)) or not candidates:
        raise ValueError("candidate_material_ids must be unique and non-empty")
    for band_id, band in config["receiver_bands"].items():
        inlet = validate_fraction(band["inlet_activity"], f"{band_id}.inlet_activity")
        outlet = validate_fraction(
            band["maximum_outlet_activity"],
            f"{band_id}.maximum_outlet_activity",
        )
        if outlet <= inlet:
            raise ValueError(f"Receiver band {band_id} must have outlet > inlet")
    operating = config["operating"]
    validate_fraction(
        operating["power_electronics_efficiency"],
        "operating.power_electronics_efficiency",
    )
    if finite_float(operating["current_density_cap_a_m2"], "current cap") <= 0:
        raise ValueError("current_density_cap_a_m2 must be positive")
    validate_positive(operating["film_scale_factor"], "operating.film_scale_factor")
    validate_nonnegative(
        operating["legacy_series_asr_ohm_m2"],
        "operating.legacy_series_asr_ohm_m2",
    )
    if str(operating["thermal_mode"]) != "isothermal":
        raise ValueError(
            "V12 currently supports only the explicit isothermal two-stream mode"
        )
    for name in ("process_fan_efficiency", "receiver_fan_efficiency"):
        validate_fraction(config["channel"][name], f"channel.{name}")
    validate_positive(
        config["channel"]["active_sides_per_process_channel"],
        "channel.active_sides_per_process_channel",
    )
    geometry_mode = str(config["channel"].get("receiver_geometry_mode", ""))
    if geometry_mode not in {
        "aligned_equal_total_width",
        "fixed_receiver_velocity_resize_width",
    }:
        raise ValueError("Unknown channel.receiver_geometry_mode")
    validate_positive(
        config["channel"].get("fixed_receiver_velocity_m_s"),
        "channel.fixed_receiver_velocity_m_s",
    )
    voltage = config["voltage_grid"]
    cap = finite_float(voltage["maximum_cell_terminal_voltage_v"], "voltage cap")
    if cap <= 0:
        raise ValueError("maximum cell voltage must be positive")
    exact = [float(value) for value in voltage["required_exact_voltages_v"]]
    if 1.0 not in exact:
        raise ValueError("required_exact_voltages_v must contain literal 1.0")
    if any(value > cap for value in exact):
        raise ValueError("A required exact voltage exceeds the cell voltage cap")
    integration = config["integration"]
    validate_positive(
        integration["mass_balance_relative_tolerance"],
        "integration.mass_balance_relative_tolerance",
    )
    validate_positive(
        integration["step_halving_relative_tolerance"],
        "integration.step_halving_relative_tolerance",
    )
    if int(integration["maximum_step_halving_cases"]) <= 0:
        raise ValueError("integration.maximum_step_halving_cases must be positive")
    stack = config["stack"]
    for name in (
        "maximum_cell_active_area_m2",
        "maximum_cell_current_a",
        "minimum_converter_input_voltage_v",
        "maximum_dc_bus_voltage_v",
        "maximum_converter_current_a",
        "maximum_converter_power_kw",
        "maximum_series_cells",
    ):
        validate_positive(stack[name], f"stack.{name}")
    if float(stack["minimum_converter_input_voltage_v"]) >= float(
        stack["maximum_dc_bus_voltage_v"]
    ):
        raise ValueError("Stack minimum converter voltage must be below its maximum")
    energy = config["energy_scenarios"]
    validate_nonnegative(
        energy["process_external_pressure_drop_pa"],
        "energy_scenarios.process_external_pressure_drop_pa",
    )
    validate_nonnegative(
        energy["controls_and_instrumentation_power_kw"],
        "energy_scenarios.controls_and_instrumentation_power_kw",
    )
    validate_fraction(
        energy["product_water_pump_efficiency"],
        "energy_scenarios.product_water_pump_efficiency",
    )
    heat_fraction = finite_float(
        energy["cell_power_to_managed_heat_fraction"],
        "energy_scenarios.cell_power_to_managed_heat_fraction",
    )
    if not 0.0 <= heat_fraction <= 1.0:
        raise ValueError("cell_power_to_managed_heat_fraction must lie in [0, 1]")
    for mode_name, mode in config["modes"].items():
        for arrangement in mode["flow_arrangements"]:
            if arrangement not in {"counter_current", "co_current"}:
                raise ValueError(
                    f"Mode {mode_name} has unknown flow arrangement {arrangement}"
                )
        for multiplier in mode["receiver_capacity_multipliers"]:
            if float(multiplier) < 1.0:
                raise ValueError(
                    f"Mode {mode_name} receiver capacity multipliers must be >= 1"
                )
        for name in (
            "electrode_pair_loss_voltages_v",
            "added_contact_asr_ohm_m2",
            "regeneration_electric_equivalent_sec_kwh_e_per_kg",
            "receiver_external_pressure_drop_pa",
            "product_water_pump_head_m",
        ):
            values = mode.get(name)
            if not isinstance(values, list) or not values:
                raise ValueError(f"Mode {mode_name}.{name} must be a non-empty list")
            for value in values:
                validate_nonnegative(value, f"modes.{mode_name}.{name}")
        thermal_values = mode.get("thermal_management_cop")
        if not isinstance(thermal_values, list) or not thermal_values:
            raise ValueError(
                f"Mode {mode_name}.thermal_management_cop must be non-empty"
            )
        for value in thermal_values:
            if value is not None:
                validate_positive(value, f"modes.{mode_name}.thermal_management_cop")
        for value in mode.get("explicit_voltages_v", []):
            validate_positive(value, f"modes.{mode_name}.explicit_voltages_v")
        if "linear_voltage_points" in mode and int(mode["linear_voltage_points"]) < 2:
            raise ValueError(f"Mode {mode_name} needs at least two linear voltages")
        for name, value in mode.get("integration_overrides", {}).items():
            validate_positive(value, f"modes.{mode_name}.integration_overrides.{name}")
        if int(mode["default_workers"]) <= 0 or int(mode["chunk_size"]) <= 0:
            raise ValueError(f"Mode {mode_name} worker and chunk counts must be positive")
        anchor_rows = int(mode["fixed_receiver_compatibility_anchor_rows"])
        if not 1 <= anchor_rows <= 168:
            raise ValueError(
                f"Mode {mode_name} compatibility anchor rows must lie in [1, 168]"
            )


def validate_v11_source(
    source_dir: Path,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply a strict, order-insensitive gate to the completed V11 result."""
    required_files = [
        "analysis_status.json",
        "run_plan.json",
        "source_manifest.json",
        "candidate_materials.csv",
        "material_grid_used.csv",
        "voltage_grid_used.csv",
        "axial_base_config_used.json",
        V11_FINAL_DATASET,
        *V11_AUDIT_FILES,
    ]
    missing_files = [name for name in required_files if not (source_dir / name).is_file()]
    if missing_files:
        raise FileNotFoundError(
            f"V11 source is missing required files: {missing_files}"
        )

    status = load_json(source_dir / "analysis_status.json")
    failures: list[str] = []
    for field in REQUIRED_V11_TRUE_FIELDS:
        try:
            passed = strict_bool_value(status.get(field))
        except ValueError:
            passed = False
        if not passed:
            failures.append(field)
    for field, expected in REQUIRED_V11_COUNTS.items():
        if int(status.get(field, -1)) != expected:
            failures.append(field)
    if str(status.get("script_version")) != REQUIRED_V11_SCRIPT_VERSION:
        failures.append("script_version")
    if not strict_bool_value(status.get("candidate_only_ranking")):
        failures.append("candidate_only_ranking")
    if strict_bool_value(status.get("global_material_optimum_claim")):
        failures.append("global_material_optimum_claim")

    plan = load_json(source_dir / "run_plan.json")
    expected_plan = {
        "mode": "fixed_material_voltage_refinement_v11",
        "source_mode": "coarse",
        "material_count": 12,
        "voltage_count": 117,
        "receiver_count": 1,
        "target_count": 2,
        "operating_point_count": 1_404,
        "axial_target_case_count": 2_808,
    }
    for field, expected in expected_plan.items():
        if plan.get(field) != expected:
            failures.append(f"run_plan.{field}")
    if strict_bool_value(plan.get("global_material_ranking")):
        failures.append("run_plan.global_material_ranking")

    candidates = pd.read_csv(source_dir / "candidate_materials.csv")
    material_grid = pd.read_csv(source_dir / "material_grid_used.csv")
    required_material_columns = {"material_id", *MATERIAL_COLUMNS}
    for label, frame in (("candidate_materials", candidates), ("material_grid", material_grid)):
        missing = required_material_columns.difference(frame.columns)
        if missing:
            failures.append(f"{label}.columns")
        if len(frame) != 12 or frame["material_id"].astype(str).nunique() != 12:
            failures.append(f"{label}.row_count")
    selected = [str(value) for value in config["candidate_material_ids"]]
    missing_selected = sorted(set(selected).difference(candidates["material_id"].astype(str)))
    if missing_selected:
        failures.append(f"selected_materials:{','.join(missing_selected)}")

    common = candidates[["material_id", *MATERIAL_COLUMNS]].merge(
        material_grid[["material_id", *MATERIAL_COLUMNS]],
        on="material_id",
        how="outer",
        suffixes=("_candidate", "_grid"),
        indicator=True,
    )
    if not common["_merge"].eq("both").all():
        failures.append("candidate_material_identity")
    for name in MATERIAL_COLUMNS:
        if not np.allclose(
            pd.to_numeric(common[f"{name}_candidate"], errors="coerce"),
            pd.to_numeric(common[f"{name}_grid"], errors="coerce"),
            rtol=1.0e-12,
            atol=1.0e-15,
            equal_nan=False,
        ):
            failures.append(f"candidate_property:{name}")

    voltage_frame = pd.read_csv(source_dir / "voltage_grid_used.csv")
    voltages = pd.to_numeric(voltage_frame["terminal_voltage_v"], errors="coerce")
    if len(voltage_frame) != 117 or voltages.nunique(dropna=False) != 117:
        failures.append("voltage_grid")
    if (voltages <= 0).any() or (~np.isfinite(voltages)).any():
        failures.append("voltage_grid_values")
    if (voltages == 1.0).any():
        failures.append("unexpected_v11_exact_1v")

    cases = pd.read_csv(
        source_dir / V11_FINAL_DATASET,
        compression="gzip",
    )
    missing_case_columns = set(V11_CASE_COLUMNS).difference(cases.columns)
    if missing_case_columns:
        failures.append("case_columns")
    if len(cases) != 2_808:
        failures.append("case_row_count")
    if cases["material_id"].astype(str).nunique() != 12:
        failures.append("case_material_count")
    if set(cases["target"].astype(str)) != {"O50", "O30"}:
        failures.append("case_targets")
    if set(cases["receiver_boundary"].astype(str)) != {"dry_receiver_80_50"}:
        failures.append("case_receiver")
    duplicate_keys = cases.duplicated(
        ["material_id", "receiver_boundary", "target", "terminal_voltage_v"],
        keep=False,
    )
    if duplicate_keys.any():
        failures.append("case_duplicate_keys")
    worker_text = cases["worker_exception"].fillna("").astype(str).str.strip()
    if worker_text.ne("").any():
        failures.append("case_worker_exceptions")

    expected_key_frame = pd.MultiIndex.from_product(
        [
            sorted(material_grid["material_id"].astype(str).tolist()),
            sorted(float(value) for value in voltages.tolist()),
            ["O30", "O50"],
        ],
        names=["material_id", "terminal_voltage_v", "target"],
    ).to_frame(index=False)
    observed_key_frame = cases[
        ["material_id", "terminal_voltage_v", "target"]
    ].copy()
    observed_key_frame["material_id"] = observed_key_frame["material_id"].astype(str)
    observed_key_frame["target"] = observed_key_frame["target"].astype(str)
    observed_key_frame["terminal_voltage_v"] = pd.to_numeric(
        observed_key_frame["terminal_voltage_v"], errors="coerce"
    )
    coverage = expected_key_frame.merge(
        observed_key_frame,
        on=["material_id", "terminal_voltage_v", "target"],
        how="outer",
        indicator=True,
    )
    if len(coverage) != 2_808 or not coverage["_merge"].eq("both").all():
        failures.append("case_cartesian_coverage")

    property_lookup = material_grid.copy()
    property_lookup["material_id"] = property_lookup["material_id"].astype(str)
    property_lookup = property_lookup.set_index("material_id")
    for name in MATERIAL_COLUMNS:
        expected_values = cases["material_id"].astype(str).map(
            pd.to_numeric(property_lookup[name], errors="coerce")
        )
        observed_values = pd.to_numeric(cases[name], errors="coerce")
        if not np.allclose(
            observed_values,
            expected_values,
            rtol=1.0e-12,
            atol=1.0e-15,
            equal_nan=False,
        ):
            failures.append(f"case_material_property:{name}")

    try:
        target_reached = strict_boolean_series(cases["target_reached"])
        prerequisite = strict_boolean_series(cases["prerequisite_short_circuit"])
    except ValueError:
        failures.append("case_boolean_semantics")
    else:
        status_text = cases["status"].fillna("").astype(str)
        if not target_reached.eq(status_text.eq("target_reached")).all():
            failures.append("case_status_semantics")
        if not prerequisite.eq(
            status_text.str.startswith("prerequisite_")
        ).all():
            failures.append("case_prerequisite_semantics")

    def require_boolean_audit(
        filename: str,
        column: str,
        expected_rows: int | None = None,
    ) -> None:
        frame = pd.read_csv(source_dir / filename)
        if expected_rows is not None and len(frame) != expected_rows:
            failures.append(f"{filename}.row_count")
        if column not in frame.columns:
            failures.append(f"{filename}.{column}")
            return
        try:
            passed = strict_boolean_series(frame[column]).all()
        except ValueError:
            passed = False
        if not passed:
            failures.append(f"{filename}.{column}")

    for filename in (
        "refinement_coverage_audit.csv",
        "refinement_balance_audit.csv",
        "refinement_semantic_status_audit.csv",
    ):
        audit = pd.read_csv(source_dir / filename)
        if "status" not in audit or not audit["status"].astype(str).eq("PASS").all():
            failures.append(f"{filename}.status")
        if "failure_count" in audit.columns and not pd.to_numeric(
            audit["failure_count"], errors="coerce"
        ).fillna(0).eq(0).all():
            failures.append(f"{filename}.failure_count")

    checkpoint_audit = pd.read_csv(source_dir / "checkpoint_audit.csv")
    checkpoint_errors = checkpoint_audit.get(
        "errors", pd.Series("", index=checkpoint_audit.index)
    )
    checkpoint_required = {
        "status",
        "row_count",
        "expected_row_count",
        "worker_exception_count",
    }
    checkpoint_valid = not checkpoint_required.difference(
        checkpoint_audit.columns
    )
    if checkpoint_valid:
        checkpoint_valid = bool(
            checkpoint_audit["status"].astype(str).eq("valid").all()
            and pd.to_numeric(checkpoint_audit["row_count"], errors="coerce")
            .eq(
                pd.to_numeric(
                    checkpoint_audit["expected_row_count"], errors="coerce"
                )
            )
            .all()
            and pd.to_numeric(
                checkpoint_audit["worker_exception_count"], errors="coerce"
            )
            .fillna(-1)
            .eq(0)
            .all()
            and checkpoint_errors.fillna("").astype(str).str.strip().eq("").all()
        )
    if not checkpoint_valid:
        failures.append("checkpoint_audit")
    require_boolean_audit(
        "v8_anchor_reproduction.csv", "anchor_reproduction_pass", 168
    )
    require_boolean_audit(
        "coarse_vs_refined_scenario_comparison.csv", "scenario_comparison_pass"
    )

    gross = (
        cases.groupby("target", sort=True)["gross_hvac_electric_opportunity_kw"]
        .agg(["min", "max"])
        .reset_index()
    )
    if not np.allclose(gross["min"], gross["max"], rtol=0.0, atol=1.0e-10):
        failures.append("gross_hvac_opportunity_uniqueness")
    expected_gross = config["regression_anchors"].get(
        "gross_hvac_electric_opportunity_kw", {}
    )
    for _, row in gross.iterrows():
        target = str(row["target"])
        if target not in expected_gross or not math.isclose(
            float(row["min"]),
            float(expected_gross[target]),
            rel_tol=1.0e-10,
            abs_tol=1.0e-8,
        ):
            failures.append(f"gross_hvac_opportunity:{target}")

    if failures:
        raise ValueError(
            "The source is not the required completed V11.1 analysis; "
            f"failed checks: {', '.join(sorted(set(failures)))}"
        )

    gross_budget = dict(zip(gross["target"], gross["min"].astype(float)))
    return {
        "status": status,
        "plan": plan,
        "candidates": candidates,
        "material_grid": material_grid,
        "voltage_frame": voltage_frame,
        "cases": cases,
        "gross_budget_kw": gross_budget,
    }


def build_voltage_grid(
    source_voltage_frame: pd.DataFrame,
    config: Mapping[str, Any],
    mode_config: Mapping[str, Any],
) -> np.ndarray:
    voltage_config = config["voltage_grid"]
    cap = float(voltage_config["maximum_cell_terminal_voltage_v"])
    source = str(mode_config["voltage_source"])
    if source == "v11_below_cap_plus_exact":
        values = pd.to_numeric(
            source_voltage_frame["terminal_voltage_v"], errors="raise"
        ).to_numpy(float)
        values = values[values <= cap]
    elif source == "explicit":
        values = np.asarray(mode_config["explicit_voltages_v"], dtype=float)
    elif source == "linear":
        values = np.linspace(
            float(mode_config["linear_voltage_min_v"]),
            cap,
            int(mode_config["linear_voltage_points"]),
        )
    else:
        raise ValueError(f"Unknown voltage source: {source}")
    values = np.concatenate(
        [
            values,
            np.asarray(voltage_config["required_exact_voltages_v"], dtype=float),
        ]
    )
    if np.any(~np.isfinite(values)) or np.any(values <= 0.0):
        raise ValueError("Voltage grid contains non-finite or non-positive values")
    if np.any(values > cap):
        raise ValueError("Voltage grid contains a value above the hard per-cell cap")
    # Python float equality is intentional: exact 1.0 coverage is a V12 gate.
    unique = sorted(set(float(value) for value in values))
    if sum(value == 1.0 for value in unique) != 1:
        raise RuntimeError("V12 voltage grid must contain literal 1.0 exactly once")
    if any(value > 1.0 for value in unique) and cap == 1.0:
        raise RuntimeError("Hard 1.0-V mode contains a value above 1.0 V")
    return np.asarray(unique, dtype=float)


def resolve_v2_root(explicit: Path | None, source_dir: Path) -> Path:
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(explicit.resolve())
    manifest_path = source_dir / "source_manifest.json"
    if manifest_path.is_file():
        configured = load_json(manifest_path).get("v2_root")
        if configured:
            candidates.append(Path(str(configured)).resolve())
    candidates.append(DEFAULT_V2_ROOT.resolve())
    for candidate in candidates:
        if (
            (candidate / "heiq_pre_receiver_model.py").is_file()
            and (candidate / "config" / "default.json").is_file()
        ):
            return candidate
    attempted = "\n".join(f"- {path}" for path in candidates)
    raise FileNotFoundError(
        "Could not locate the V2 package with model and config. Tried:\n" + attempted
    )


def validate_unchanged_solver_sources(
    source_dir: Path,
    axial_script: Path,
    v2_root: Path,
) -> dict[str, str]:
    """Require the exact V2/V3 sources recorded by the completed V11 run."""
    manifest = load_json(source_dir / "source_manifest.json")
    declared = manifest.get("file_sha256")
    if not isinstance(declared, dict):
        raise ValueError("V11 source_manifest.json has no file_sha256 object")
    actual = {
        "v3_axial_script": sha256_file(axial_script),
        "v2_model": sha256_file(v2_root / "heiq_pre_receiver_model.py"),
        "v2_default_config": sha256_file(v2_root / "config" / "default.json"),
    }
    mismatches = [
        name for name, digest in actual.items() if declared.get(name) != digest
    ]
    if mismatches:
        raise ValueError(
            "V12 must use the unchanged V2/V3 solver sources recorded by V11; "
            f"hash mismatch: {', '.join(mismatches)}"
        )
    return actual


def target_map(targets: pd.DataFrame) -> dict[str, pd.Series]:
    return {
        str(row["target"]): row
        for _, row in targets.iterrows()
    }


def make_material(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "name": str(row["material_id"]),
        "model": "powerlaw",
        **{name: float(row[name]) for name in MATERIAL_COLUMNS},
        "interpretation": (
            "Selected hypothetical V11 property combination; not a measured material"
        ),
    }


def water_load_kg_h(target_row: Mapping[str, Any]) -> float:
    return finite_float(target_row["computed_water_load_kg_h"], "water load")


def run_fixed_receiver_compatibility_audit(
    *,
    axial: ModuleType,
    v2: ModuleType,
    v2_config: Mapping[str, Any],
    base_config: Mapping[str, Any],
    process_basis: Any,
    targets: Mapping[str, Mapping[str, Any]],
    cases: pd.DataFrame,
    anchor_file: Path,
    maximum_rows: int,
) -> pd.DataFrame:
    """Re-run V11 fixed-receiver anchors with the unchanged V3 integrator."""
    anchors = pd.read_csv(
        anchor_file,
        usecols=["material_id", "target", "terminal_voltage_v"],
    ).drop_duplicates()
    keyed = anchors.merge(
        cases,
        on=["material_id", "target", "terminal_voltage_v"],
        how="left",
        validate="one_to_one",
    ).sort_values(["material_id", "target", "terminal_voltage_v"])
    if len(keyed) != 168 or keyed["status"].isna().any():
        raise RuntimeError("Could not resolve all 168 V11 compatibility anchors")
    if maximum_rows < len(keyed):
        first_by_stratum = keyed.groupby(
            ["material_id", "target"], sort=True
        ).head(1)
        if len(first_by_stratum) > maximum_rows:
            positions = np.linspace(
                0, len(first_by_stratum) - 1, maximum_rows, dtype=int
            )
            selected = first_by_stratum.iloc[positions]
        else:
            remaining = keyed.drop(index=first_by_stratum.index)
            needed = maximum_rows - len(first_by_stratum)
            positions = (
                np.linspace(0, len(remaining) - 1, needed, dtype=int)
                if needed > 0
                else np.asarray([], dtype=int)
            )
            selected = pd.concat(
                [first_by_stratum, remaining.iloc[positions]], ignore_index=True
            )
    else:
        selected = keyed
    numeric_fields = [
        "required_active_area_m2",
        "outlet_humidity_ratio_kg_kg_da",
        "integrated_water_removal_kg_h",
        "air_balance_water_removal_kg_h",
        "maximum_local_current_density_a_m2",
        "minimum_local_flux_mol_m2_s",
        "integrated_current_a",
        "cell_power_kw",
        "membrane_power_kw",
        "series_loss_power_kw",
        "fixed_loss_power_kw",
        "power_electronics_loss_kw",
        "eo_grid_power_kw",
    ]
    rows: list[dict[str, Any]] = []
    for _, expected in selected.iterrows():
        try:
            observed, _ = axial.integrate_axial_case(
                v2=v2,
                v2_config=dict(v2_config),
                config=copy.deepcopy(dict(base_config)),
                basis=process_basis,
                target_row=targets[str(expected["target"])],
                material=make_material(expected),
                receiver_label=str(expected["receiver_boundary"]),
                receiver_activity=float(expected["receiver_bulk_activity"]),
                terminal_voltage_v=float(expected["terminal_voltage_v"]),
                fixed_loss_voltage_v=float(expected["fixed_loss_voltage_v"]),
                series_asr_ohm_m2=float(expected["series_asr_ohm_m2"]),
                power_electronics_efficiency=float(
                    expected["power_electronics_efficiency"]
                ),
                current_cap_a_m2=float(expected["current_cap_a_m2"]),
                film_scale_factor=float(expected["film_scale_factor"]),
                thermal_mode=str(expected["thermal_mode"]),
                record_profile=False,
            )
            expected_status = str(expected["status"])
            if expected_status.startswith("prerequisite_") and ":" in expected_status:
                expected_status = expected_status.split(":", 1)[1]
            text_match = str(observed["status"]) == expected_status
            boolean_match = strict_bool_value(
                observed["target_reached"]
            ) == strict_bool_value(expected["target_reached"])
            absolute_errors: list[float] = []
            relative_errors: list[float] = []
            numeric_match = True
            mismatches: list[str] = []
            for name in numeric_fields:
                left = float(observed[name])
                right = float(expected[name])
                if math.isnan(left) and math.isnan(right):
                    continue
                if not (math.isfinite(left) and math.isfinite(right)):
                    numeric_match = False
                    mismatches.append(name)
                    continue
                absolute = abs(left - right)
                relative = absolute / max(abs(left), abs(right), 1.0e-12)
                absolute_errors.append(absolute)
                relative_errors.append(relative)
                if not math.isclose(
                    left, right, rel_tol=1.0e-9, abs_tol=1.0e-10
                ):
                    numeric_match = False
                    mismatches.append(name)
            error_text = ""
        except BaseException as error:
            text_match = False
            boolean_match = False
            numeric_match = False
            absolute_errors = []
            relative_errors = []
            mismatches = []
            error_text = f"{type(error).__name__}: {error}"
        rows.append(
            {
                "material_id": expected["material_id"],
                "target": expected["target"],
                "terminal_voltage_v": expected["terminal_voltage_v"],
                "text_match": text_match,
                "boolean_match": boolean_match,
                "numeric_match": numeric_match,
                "maximum_absolute_error": (
                    max(absolute_errors) if absolute_errors else math.nan
                ),
                "maximum_relative_error": (
                    max(relative_errors) if relative_errors else math.nan
                ),
                "numeric_mismatch_columns": ";".join(mismatches),
                "error": error_text,
                "compatibility_pass": bool(
                    text_match and boolean_match and numeric_match and not error_text
                ),
            }
        )
    return pd.DataFrame(rows)


def humidity_ratio_from_activity(
    axial: ModuleType,
    temperature_c: float,
    activity: float,
    pressure_pa: float,
) -> float:
    return float(
        axial.humidity_ratio_from_t_rh(temperature_c, activity, pressure_pa)
    )


def actual_volume_flow_from_dry_air(
    axial: ModuleType,
    dry_air_mass_flow_kg_s: float,
    temperature_c: float,
    humidity_ratio_kg_kg_da: float,
    pressure_pa: float,
) -> float:
    vapour_pressure = float(
        axial.vapour_pressure_from_humidity_ratio(
            humidity_ratio_kg_kg_da, pressure_pa
        )
    )
    dry_air_pressure = pressure_pa - vapour_pressure
    if dry_air_pressure <= 0.0:
        raise ValueError("Receiver dry-air partial pressure must be positive")
    return (
        dry_air_mass_flow_kg_s
        * R_DRY_AIR_J_KG_K
        * (temperature_c + 273.15)
        / dry_air_pressure
    )


def make_receiver_basis(
    *,
    axial: ModuleType,
    process_basis: Any,
    target_row: Mapping[str, Any],
    receiver_sizing_target_row: Mapping[str, Any],
    band_id: str,
    band: Mapping[str, Any],
    capacity_multiplier: float,
    flow_arrangement: str,
    base_config: Mapping[str, Any],
) -> ReceiverBasis:
    pressure = float(base_config["air"]["absolute_pressure_pa"])
    temperature = float(base_config["channel"]["receiver_temperature_c"])
    inlet_activity = float(band["inlet_activity"])
    maximum_activity = float(band["maximum_outlet_activity"])
    inlet_w = humidity_ratio_from_activity(
        axial, temperature, inlet_activity, pressure
    )
    maximum_w = humidity_ratio_from_activity(
        axial, temperature, maximum_activity, pressure
    )
    delta_w = maximum_w - inlet_w
    if delta_w <= 0.0:
        raise ValueError("Receiver humidity band has no water capacity")
    design_load_kg_s = water_load_kg_h(receiver_sizing_target_row) / 3600.0
    minimum_flow = design_load_kg_s / delta_w
    selected_flow = minimum_flow * float(capacity_multiplier)
    if selected_flow <= 0.0:
        raise ValueError("Receiver dry-air flow must be positive")
    actual_target_load_kg_s = water_load_kg_h(target_row) / 3600.0
    target_outlet_w = inlet_w + actual_target_load_kg_s / selected_flow
    capacity_sufficient = target_outlet_w <= maximum_w + 1.0e-12
    volume_flow = actual_volume_flow_from_dry_air(
        axial,
        selected_flow,
        temperature,
        inlet_w,
        pressure,
    )
    channel = base_config["channel"]
    process_open_area = (
        process_basis.volume_flow_m3_s
        / float(channel["process_velocity_m_s"])
    )
    total_process_width = process_open_area / float(channel["process_gap_m"])
    active_sides = float(channel["active_sides_per_process_channel"])
    receiver_gap = float(channel["receiver_gap_m"])
    geometry_mode = str(base_config["channel"]["receiver_geometry_mode"])
    if geometry_mode == "aligned_equal_total_width":
        receiver_total_width = total_process_width
        receiver_open_area = receiver_total_width * receiver_gap * active_sides
        receiver_velocity = volume_flow / receiver_open_area
    elif geometry_mode == "fixed_receiver_velocity_resize_width":
        receiver_velocity = float(
            base_config["channel"]["fixed_receiver_velocity_m_s"]
        )
        receiver_open_area = volume_flow / receiver_velocity
        receiver_total_width = receiver_open_area / (receiver_gap * active_sides)
    else:
        raise ValueError(f"Unknown receiver geometry mode {geometry_mode}")
    if receiver_open_area <= 0.0:
        raise ValueError("Receiver open flow area must be positive")
    return ReceiverBasis(
        band_id=band_id,
        receiver_sizing_target=str(receiver_sizing_target_row["target"]),
        flow_arrangement=flow_arrangement,
        temperature_c=temperature,
        pressure_pa=pressure,
        inlet_activity=inlet_activity,
        maximum_outlet_activity=maximum_activity,
        inlet_humidity_ratio_kg_kg_da=inlet_w,
        maximum_outlet_humidity_ratio_kg_kg_da=maximum_w,
        target_outlet_humidity_ratio_kg_kg_da=target_outlet_w,
        minimum_dry_air_mass_flow_kg_s=minimum_flow,
        selected_dry_air_mass_flow_kg_s=selected_flow,
        selected_actual_volume_flow_m3_s=volume_flow,
        selected_actual_airflow_cfm=volume_flow / float(axial.CFM_TO_M3_S),
        capacity_multiplier=float(capacity_multiplier),
        receiver_geometry_mode=geometry_mode,
        receiver_total_channel_width_m=receiver_total_width,
        receiver_velocity_m_s=receiver_velocity,
        receiver_to_process_dry_air_ratio=(
            selected_flow / process_basis.dry_air_mass_flow_kg_s
        ),
        target_capacity_sufficient=capacity_sufficient,
    )


def coupled_local_gate(local: Mapping[str, Any], current_cap_a_m2: float) -> str:
    if not bool(local.get("solution_ok", False)):
        return str(local.get("solution_status", "unknown_local_failure"))
    flux = float(local["net_flux_mol_m2_s"])
    current = float(local["current_density_a_m2"])
    if not math.isfinite(flux) or flux <= 0.0:
        return "nonpositive_net_water_flux"
    if not math.isfinite(current) or current <= 0.0:
        return "nonpositive_current_density"
    if current > current_cap_a_m2:
        return "operating_current_density_limit"
    return "local_gates_pass"


def integrate_coupled_receiver_case(
    *,
    axial: ModuleType,
    v2: ModuleType,
    v2_config: Mapping[str, Any],
    config: Mapping[str, Any],
    process_basis: Any,
    target_row: Mapping[str, Any],
    material: Mapping[str, Any],
    receiver: ReceiverBasis,
    terminal_voltage_v: float,
    electrode_pair_loss_voltage_v: float,
    legacy_series_asr_ohm_m2: float,
    added_contact_asr_ohm_m2: float,
    power_electronics_efficiency: float,
    current_cap_a_m2: float,
    film_scale_factor: float,
    record_profile: bool,
) -> tuple[dict[str, Any], pd.DataFrame]:
    """Integrate a co- or counter-current two-stream membrane case.

    The same mean flux updates both streams, so each numerical segment closes
    water mass by construction.  Counter-current starts at the process inlet
    paired with the receiver outlet, whose humidity is fixed by the requested
    target and the global receiver balance.
    """
    integration = config["integration"]
    area_limit = float(integration["area_limit_m2"])
    nominal_step = float(integration["area_step_m2"])
    minimum_step = float(integration["minimum_area_step_m2"])
    humidity_tolerance = float(integration["humidity_ratio_absolute_tolerance"])
    balance_tolerance = float(integration["mass_balance_relative_tolerance"])
    target_w = float(target_row["target_humidity_ratio_kg_kg_da"])
    process_inlet_w = float(process_basis.inlet_humidity_ratio_kg_kg_da)
    process_w = process_inlet_w
    process_temperature_c = float(process_basis.inlet_temperature_c)
    receiver_inlet_w = receiver.inlet_humidity_ratio_kg_kg_da
    if receiver.flow_arrangement == "co_current":
        receiver_w = receiver_inlet_w
        receiver_derivative_sign = 1.0
    elif receiver.flow_arrangement == "counter_current":
        receiver_w = receiver.target_outlet_humidity_ratio_kg_kg_da
        receiver_derivative_sign = -1.0
    else:
        raise ValueError(f"Unknown flow arrangement {receiver.flow_arrangement}")

    identity = {
        "target": str(target_row["target"]),
        "material_id": str(material["name"]),
        **{name: float(material[name]) for name in MATERIAL_COLUMNS},
        "terminal_voltage_v": float(terminal_voltage_v),
        "is_exact_1v_solver_point": float(terminal_voltage_v) == 1.0,
        "electrode_pair_loss_voltage_v": float(electrode_pair_loss_voltage_v),
        "legacy_series_asr_ohm_m2": float(legacy_series_asr_ohm_m2),
        "added_contact_asr_ohm_m2": float(added_contact_asr_ohm_m2),
        **asdict(receiver),
    }
    if not receiver.target_capacity_sufficient:
        return (
            {
                **identity,
                "status": "receiver_capacity_insufficient_for_target_band",
                "target_reached": False,
                "required_active_area_m2": 0.0,
                "process_outlet_humidity_ratio_kg_kg_da": process_inlet_w,
                "receiver_outlet_humidity_ratio_kg_kg_da": math.nan,
                "receiver_outlet_activity": math.nan,
                "integrated_water_transfer_kg_h": 0.0,
                "process_air_balance_water_removal_kg_h": 0.0,
                "receiver_air_balance_water_gain_kg_h": 0.0,
                "process_mass_balance_relative_error": 0.0,
                "receiver_mass_balance_relative_error": 0.0,
                "maximum_local_current_density_a_m2": math.nan,
                "minimum_local_flux_mol_m2_s": math.nan,
                "integrated_current_a": 0.0,
                "cell_power_kw": 0.0,
                "membrane_power_kw": 0.0,
                "legacy_series_loss_power_kw": 0.0,
                "added_contact_loss_power_kw": 0.0,
                "electrode_loss_power_kw": 0.0,
                "power_electronics_loss_kw": 0.0,
                "eo_grid_power_kw": 0.0,
                "maximum_terminal_voltage_error_v": math.nan,
                "receiver_boundary_pass": False,
                "water_balance_evaluated": False,
                "water_balance_pass": False,
                "local_solver_evaluated": False,
                "worker_exception": "",
            },
            pd.DataFrame(),
        )

    local_config = copy.deepcopy(dict(config))
    local_config["channel"] = copy.deepcopy(dict(config["channel"]))
    local_config["channel"]["receiver_velocity_m_s"] = receiver.receiver_velocity_m_s
    total_series_asr = legacy_series_asr_ohm_m2 + added_contact_asr_ohm_m2
    process_mass_flow = float(process_basis.dry_air_mass_flow_kg_s)
    receiver_mass_flow = receiver.selected_dry_air_mass_flow_kg_s
    maximum_receiver_w = receiver.maximum_outlet_humidity_ratio_kg_kg_da

    cumulative_area = 0.0
    cell_power_w = 0.0
    membrane_power_w = 0.0
    legacy_series_power_w = 0.0
    contact_power_w = 0.0
    electrode_power_w = 0.0
    integrated_current_a = 0.0
    integrated_transfer_mol_s = 0.0
    maximum_current = -math.inf
    minimum_flux = math.inf
    maximum_voltage_error = 0.0
    profile_rows: list[dict[str, Any]] = []
    status = "area_limit_before_target"
    last_local: Mapping[str, Any] | None = None
    shortened_endpoint_resolved = False

    def receiver_activity(water_ratio: float) -> float:
        return float(
            axial.activity_from_t_w(
                receiver.temperature_c,
                water_ratio,
                receiver.pressure_pa,
            )
        )

    def solve_at(process_ratio: float, receiver_ratio: float) -> dict[str, Any]:
        activity = receiver_activity(receiver_ratio)
        if not axial.ACTIVITY_EPS < activity < 1.0 - axial.ACTIVITY_EPS:
            return {
                "solution_ok": False,
                "solution_status": "receiver_bulk_activity_out_of_bounds",
                "raw_solution_status": "receiver_bulk_activity_out_of_bounds",
                "receiver_bulk_activity": activity,
            }
        return axial.solve_local_state(
            v2=v2,
            v2_config=v2_config,
            material=dict(material),
            source_temperature_c=process_temperature_c,
            source_humidity_ratio=process_ratio,
            receiver_activity=activity,
            terminal_voltage_v=terminal_voltage_v,
            fixed_loss_voltage_v=electrode_pair_loss_voltage_v,
            series_asr_ohm_m2=total_series_asr,
            film_scale_factor=film_scale_factor,
            config=local_config,
        )

    while cumulative_area < area_limit - 1.0e-12:
        if process_w <= target_w + humidity_tolerance:
            status = "target_reached"
            break
        step = min(nominal_step, area_limit - cumulative_area)
        local_start = solve_at(process_w, receiver_w)
        start_gate = coupled_local_gate(local_start, current_cap_a_m2)
        if start_gate != "local_gates_pass":
            status = start_gate
            last_local = local_start
            break
        start_flux = float(local_start["net_flux_mol_m2_s"])

        while True:
            transfer_start_kg_s = start_flux * MOLAR_MASS_WATER_KG_MOL * step
            predicted_process_w = process_w - transfer_start_kg_s / process_mass_flow
            predicted_receiver_w = (
                receiver_w
                + receiver_derivative_sign * transfer_start_kg_s / receiver_mass_flow
            )
            if predicted_process_w <= 0.0:
                end_gate = "predictor_negative_process_humidity_ratio"
                local_end = {"solution_ok": False}
            elif predicted_receiver_w <= 0.0:
                end_gate = "predictor_negative_receiver_humidity_ratio"
                local_end = {"solution_ok": False}
            elif (
                receiver.flow_arrangement == "co_current"
                and predicted_receiver_w > maximum_receiver_w + humidity_tolerance
            ):
                end_gate = "predictor_receiver_activity_limit"
                local_end = {"solution_ok": False}
            else:
                local_end = solve_at(predicted_process_w, predicted_receiver_w)
                end_gate = coupled_local_gate(local_end, current_cap_a_m2)
            if end_gate == "local_gates_pass":
                break
            if step <= minimum_step + 1.0e-12:
                status = f"corrector_failure:{end_gate}"
                last_local = local_end
                break
            step = max(0.5 * step, minimum_step)
        if status.startswith("corrector_failure:"):
            break

        end_flux = float(local_end["net_flux_mol_m2_s"])
        mean_flux = 0.5 * (start_flux + end_flux)
        full_transfer_kg_s = mean_flux * MOLAR_MASS_WATER_KG_MOL * step
        if full_transfer_kg_s <= 0.0 or not math.isfinite(full_transfer_kg_s):
            status = "nonpositive_corrected_water_transfer"
            last_local = local_end
            break

        process_needed_kg_s = process_mass_flow * max(process_w - target_w, 0.0)
        fractions = [(1.0, "continue")]
        fractions.append((process_needed_kg_s / full_transfer_kg_s, "target_reached"))
        if receiver.flow_arrangement == "co_current":
            receiver_capacity_kg_s = receiver_mass_flow * max(
                maximum_receiver_w - receiver_w, 0.0
            )
            fractions.append(
                (
                    receiver_capacity_kg_s / full_transfer_kg_s,
                    "receiver_activity_limit_before_target",
                )
            )
        nonnegative = [(max(0.0, value), label) for value, label in fractions]
        step_fraction, limiting_status = min(nonnegative, key=lambda item: item[0])
        step_fraction = min(step_fraction, 1.0)
        if step_fraction < 1.0:
            # The old implementation scaled a full-step trapezoid even though
            # its end state lay beyond the target/band boundary.  Resolve the
            # physical event state, re-run the local solver there, and derive
            # the shortened area from the event's exact transferred water.
            if limiting_status == "target_reached":
                transferred_kg_s = process_needed_kg_s
                next_process_w = target_w
                next_receiver_w = receiver_w + (
                    receiver_derivative_sign
                    * transferred_kg_s
                    / receiver_mass_flow
                )
            elif limiting_status == "receiver_activity_limit_before_target":
                transferred_kg_s = receiver_capacity_kg_s
                next_receiver_w = maximum_receiver_w
                next_process_w = process_w - transferred_kg_s / process_mass_flow
            else:
                raise RuntimeError(f"Unexpected shortened-step status {limiting_status}")
            event_end = solve_at(next_process_w, next_receiver_w)
            event_gate = coupled_local_gate(event_end, current_cap_a_m2)
            if event_gate != "local_gates_pass":
                status = f"shortened_endpoint_failure:{event_gate}"
                last_local = event_end
                break
            local_end = event_end
            end_flux = float(local_end["net_flux_mol_m2_s"])
            mean_flux = 0.5 * (start_flux + end_flux)
            effective_step = transferred_kg_s / (
                mean_flux * MOLAR_MASS_WATER_KG_MOL
            )
            if (
                not math.isfinite(effective_step)
                or effective_step < 0.0
                or effective_step > step * (1.0 + 1.0e-8)
            ):
                status = "shortened_endpoint_area_inconsistent"
                last_local = local_end
                break
            step_fraction = effective_step / step
            shortened_endpoint_resolved = True
        else:
            effective_step = step
            transferred_kg_s = full_transfer_kg_s
            next_process_w = process_w - transferred_kg_s / process_mass_flow
            next_receiver_w = receiver_w + (
                receiver_derivative_sign
                * transferred_kg_s
                / receiver_mass_flow
            )

        def mean(name: str) -> float:
            return 0.5 * (float(local_start[name]) + float(local_end[name]))

        mean_current = mean("current_density_a_m2")
        mean_membrane_power = mean("membrane_power_density_w_m2")
        start_current = float(local_start["current_density_a_m2"])
        end_current = float(local_end["current_density_a_m2"])
        mean_current_squared = 0.5 * (start_current**2 + end_current**2)
        mean_legacy_series_power = (
            mean_current_squared * legacy_series_asr_ohm_m2
        )
        mean_contact_power = mean_current_squared * added_contact_asr_ohm_m2
        mean_electrode_power = mean_current * electrode_pair_loss_voltage_v
        mean_cell_power = terminal_voltage_v * mean_current
        component_sum = (
            mean_membrane_power
            + mean_legacy_series_power
            + mean_contact_power
            + mean_electrode_power
        )
        component_tolerance = 1.0e-6 + 1.0e-7 * max(abs(mean_cell_power), 1.0)
        if abs(component_sum - mean_cell_power) > component_tolerance:
            status = "electrical_component_identity_failure"
            last_local = local_end
            break

        cell_power_w += mean_cell_power * effective_step
        membrane_power_w += mean_membrane_power * effective_step
        legacy_series_power_w += mean_legacy_series_power * effective_step
        contact_power_w += mean_contact_power * effective_step
        electrode_power_w += mean_electrode_power * effective_step
        integrated_current_a += mean_current * effective_step
        integrated_transfer_mol_s += mean_flux * effective_step
        maximum_current = max(
            maximum_current,
            float(local_start["current_density_a_m2"]),
            float(local_end["current_density_a_m2"]),
        )
        minimum_flux = min(minimum_flux, start_flux, end_flux)
        maximum_voltage_error = max(
            maximum_voltage_error,
            abs(float(local_start["terminal_voltage_error_v"])),
            abs(float(local_end["terminal_voltage_error_v"])),
        )

        cumulative_area += effective_step
        process_w = next_process_w
        receiver_w = next_receiver_w
        last_local = local_end
        if record_profile:
            profile_rows.append(
                {
                    **identity,
                    "cumulative_area_m2": cumulative_area,
                    "step_area_m2": effective_step,
                    "process_humidity_ratio_kg_kg_da": process_w,
                    "process_activity": float(
                        axial.activity_from_t_w(
                            process_temperature_c,
                            process_w,
                            process_basis.absolute_pressure_pa,
                        )
                    ),
                    "receiver_humidity_ratio_kg_kg_da": receiver_w,
                    "receiver_activity": receiver_activity(receiver_w),
                    "net_flux_mol_m2_s": mean_flux,
                    "current_density_a_m2": mean_current,
                    "cell_power_density_w_m2": mean_cell_power,
                    "cumulative_cell_power_kw": cell_power_w / 1000.0,
                }
            )
        if step_fraction < 1.0:
            status = limiting_status
            break

    countercurrent_boundary_solution_valid = bool(
        receiver.flow_arrangement == "counter_current" and status == "target_reached"
    )
    if receiver.flow_arrangement == "co_current":
        receiver_outlet_w = receiver_w
        receiver_boundary_residual_w = math.nan
        receiver_calculated_far_end_w = receiver_outlet_w
    elif countercurrent_boundary_solution_valid:
        receiver_outlet_w = receiver.target_outlet_humidity_ratio_kg_kg_da
        receiver_boundary_residual_w = receiver_w - receiver_inlet_w
        receiver_calculated_far_end_w = receiver_w
    else:
        # The counter-current IVP was conditioned on the requested outlet.  If
        # it did not reach the target, that assumed outlet is not a solved
        # physical boundary and must not be published as one.
        receiver_outlet_w = math.nan
        receiver_boundary_residual_w = math.nan
        receiver_calculated_far_end_w = math.nan

    integrated_water_kg_h = (
        integrated_transfer_mol_s * MOLAR_MASS_WATER_KG_MOL * 3600.0
    )
    process_balance_kg_h = (
        process_mass_flow * (process_inlet_w - process_w) * 3600.0
    )
    receiver_balance_kg_h = (
        receiver_mass_flow * (receiver_outlet_w - receiver_inlet_w) * 3600.0
        if receiver.flow_arrangement == "co_current"
        else receiver_mass_flow
        * (receiver_outlet_w - receiver_calculated_far_end_w)
        * 3600.0
    )

    def relative_error(left: float, right: float) -> float:
        scale = max(abs(left), abs(right), 1.0e-12)
        return (left - right) / scale

    process_error = relative_error(integrated_water_kg_h, process_balance_kg_h)
    receiver_error = (
        relative_error(integrated_water_kg_h, receiver_balance_kg_h)
        if math.isfinite(receiver_balance_kg_h)
        else math.nan
    )
    receiver_boundary_pass = (
        True
        if receiver.flow_arrangement == "co_current"
        else countercurrent_boundary_solution_valid
        and abs(receiver_boundary_residual_w) <= max(humidity_tolerance, 1.0e-10)
    )
    balance_pass = (
        abs(process_error) <= balance_tolerance
        and math.isfinite(receiver_error)
        and abs(receiver_error) <= balance_tolerance
        and receiver_boundary_pass
    )
    if status == "target_reached" and not balance_pass:
        status = "coupled_water_balance_failure"

    grid_power_kw = cell_power_w / power_electronics_efficiency / 1000.0
    power_electronics_loss_kw = grid_power_kw - cell_power_w / 1000.0
    return (
        {
            **identity,
            "status": status,
            "target_reached": status == "target_reached",
            "required_active_area_m2": cumulative_area,
            "process_inlet_humidity_ratio_kg_kg_da": process_inlet_w,
            "process_outlet_humidity_ratio_kg_kg_da": process_w,
            "target_humidity_ratio_kg_kg_da": target_w,
            "receiver_inlet_humidity_ratio_kg_kg_da": receiver_inlet_w,
            "receiver_outlet_humidity_ratio_kg_kg_da": receiver_outlet_w,
            "receiver_calculated_far_end_humidity_ratio_kg_kg_da": (
                receiver_calculated_far_end_w
            ),
            "receiver_outlet_activity": (
                receiver_activity(receiver_outlet_w)
                if math.isfinite(receiver_outlet_w)
                else math.nan
            ),
            "receiver_boundary_residual_humidity_ratio": receiver_boundary_residual_w,
            "countercurrent_boundary_solution_valid": (
                countercurrent_boundary_solution_valid
            ),
            "integrated_water_transfer_kg_h": integrated_water_kg_h,
            "process_air_balance_water_removal_kg_h": process_balance_kg_h,
            "receiver_air_balance_water_gain_kg_h": receiver_balance_kg_h,
            "process_mass_balance_relative_error": process_error,
            "receiver_mass_balance_relative_error": receiver_error,
            "receiver_boundary_pass": receiver_boundary_pass,
            "water_balance_evaluated": True,
            "water_balance_pass": balance_pass,
            "local_solver_evaluated": True,
            "shortened_endpoint_resolved": shortened_endpoint_resolved,
            "maximum_local_current_density_a_m2": (
                maximum_current if maximum_current > -math.inf else math.nan
            ),
            "minimum_local_flux_mol_m2_s": (
                minimum_flux if minimum_flux < math.inf else math.nan
            ),
            "integrated_current_a": integrated_current_a,
            "cell_power_kw": cell_power_w / 1000.0,
            "membrane_power_kw": membrane_power_w / 1000.0,
            "legacy_series_loss_power_kw": legacy_series_power_w / 1000.0,
            "added_contact_loss_power_kw": contact_power_w / 1000.0,
            "electrode_loss_power_kw": electrode_power_w / 1000.0,
            "power_electronics_loss_kw": power_electronics_loss_kw,
            "eo_grid_power_kw": grid_power_kw,
            "maximum_terminal_voltage_error_v": maximum_voltage_error,
            "worker_exception": "",
            "material_evidence": (
                "hypothetical independent V11 property combination; not material validation"
            ),
        },
        pd.DataFrame(profile_rows),
    )


def channel_pressure_drop_and_fan(
    *,
    axial: ModuleType,
    active_area_m2: float,
    total_channel_width_m: float,
    active_sides: float,
    gap_m: float,
    velocity_m_s: float,
    volume_flow_m3_s: float,
    temperature_c: float,
    pressure_pa: float,
    humidity_ratio_kg_kg_da: float,
    fan_efficiency: float,
) -> dict[str, float]:
    if any(
        value <= 0.0
        for value in (
            total_channel_width_m,
            active_sides,
            gap_m,
            velocity_m_s,
            volume_flow_m3_s,
            fan_efficiency,
        )
    ):
        raise ValueError("Channel geometry, flow and fan efficiency must be positive")
    length = active_area_m2 / (active_sides * total_channel_width_m)
    temperature_k = temperature_c + 273.15
    if humidity_ratio_kg_kg_da < 0.0:
        raise ValueError("Humidity ratio cannot be negative")
    dry_air_partial_pressure = pressure_pa / (
        1.0 + humidity_ratio_kg_kg_da / 0.621945
    )
    density = (
        dry_air_partial_pressure
        / (R_DRY_AIR_J_KG_K * temperature_k)
        * (1.0 + humidity_ratio_kg_kg_da)
    )
    viscosity = float(axial.dynamic_viscosity_air_pa_s(temperature_c))
    hydraulic_diameter = 2.0 * gap_m
    reynolds = density * velocity_m_s * hydraulic_diameter / viscosity
    if reynolds <= 2300.0:
        pressure_drop = 12.0 * viscosity * length * velocity_m_s / gap_m**2
    else:
        friction_factor = 0.3164 * reynolds ** -0.25
        pressure_drop = (
            friction_factor
            * length
            / hydraulic_diameter
            * density
            * velocity_m_s**2
            / 2.0
        )
    fan_power_kw = pressure_drop * volume_flow_m3_s / fan_efficiency / 1000.0
    return {
        "channel_length_m": length,
        "channel_reynolds_number": reynolds,
        "channel_pressure_drop_pa": pressure_drop,
        "channel_fan_power_kw": fan_power_kw,
    }


def stack_topology(
    *,
    required_area_m2: float,
    integrated_current_a: float,
    maximum_current_density_a_m2: float,
    cell_terminal_voltage_v: float,
    stack_config: Mapping[str, Any],
) -> dict[str, Any]:
    """Search an integer Ns x Np topology under declared illustrative limits."""
    if required_area_m2 <= 0.0 or integrated_current_a <= 0.0:
        return {
            "stack_feasible": False,
            "stack_infeasibility_reason": "nonpositive area or integrated current",
        }
    max_cell_area = float(stack_config["maximum_cell_active_area_m2"])
    max_cell_current = float(stack_config["maximum_cell_current_a"])
    minimum_converter_voltage = float(
        stack_config["minimum_converter_input_voltage_v"]
    )
    max_bus_voltage = float(stack_config["maximum_dc_bus_voltage_v"])
    max_bus_current = float(stack_config["maximum_converter_current_a"])
    max_converter_power_kw = float(stack_config["maximum_converter_power_kw"])
    max_series = int(stack_config["maximum_series_cells"])
    if any(
        value <= 0
        for value in (
            max_cell_area,
            max_cell_current,
            minimum_converter_voltage,
            max_bus_voltage,
            max_bus_current,
            max_converter_power_kw,
            max_series,
        )
    ):
        raise ValueError("Stack constraints must be positive")
    minimum_cells_area = math.ceil(required_area_m2 / max_cell_area)
    # Terminal current is the area integral of j divided among repeat cells.
    # The local maximum j is retained as a separate collector/material screen;
    # multiplying j_max by every cell's full area would overstate cell current.
    minimum_cells_terminal_current = math.ceil(
        integrated_current_a / max_cell_current
    )
    minimum_cells = max(1, minimum_cells_area, minimum_cells_terminal_current)
    reference_power_kw = cell_terminal_voltage_v * integrated_current_a / 1000.0
    if reference_power_kw > max_converter_power_kw + 1.0e-12:
        return {
            "stack_feasible": False,
            "stack_infeasibility_reason": "converter power limit exceeded",
            "stack_reference_cell_power_kw": reference_power_kw,
            "stack_maximum_local_current_density_a_m2": maximum_current_density_a_m2,
        }
    maximum_ns_voltage = math.floor(max_bus_voltage / cell_terminal_voltage_v)
    maximum_ns = min(max_series, maximum_ns_voltage)
    minimum_ns_current = max(1, math.ceil(integrated_current_a / max_bus_current))
    minimum_ns_voltage = max(
        1, math.ceil(minimum_converter_voltage / cell_terminal_voltage_v)
    )
    minimum_ns = max(minimum_ns_current, minimum_ns_voltage)
    if maximum_ns < minimum_ns:
        return {
            "stack_feasible": False,
            "stack_infeasibility_reason": (
                "no series count meets converter voltage/current limits"
            ),
            "minimum_series_cells_from_current": minimum_ns_current,
            "minimum_series_cells_from_voltage": minimum_ns_voltage,
            "maximum_series_cells_from_voltage": maximum_ns,
        }
    candidates: list[tuple[int, int, int]] = []
    for series_cells in range(minimum_ns, maximum_ns + 1):
        parallel_strings = math.ceil(minimum_cells / series_cells)
        total_cells = series_cells * parallel_strings
        candidates.append((total_cells, -series_cells, parallel_strings))
    total_cells, negative_series, parallel_strings = min(candidates)
    series_cells = -negative_series
    cell_area = required_area_m2 / total_cells
    cell_terminal_current = integrated_current_a / total_cells
    string_voltage = series_cells * cell_terminal_voltage_v
    dc_bus_current = integrated_current_a / series_cells
    topology_power_kw = string_voltage * dc_bus_current / 1000.0
    identity_error = topology_power_kw - reference_power_kw
    feasible = (
        cell_area <= max_cell_area + 1.0e-12
        and cell_terminal_current <= max_cell_current + 1.0e-9
        and string_voltage >= minimum_converter_voltage - 1.0e-12
        and string_voltage <= max_bus_voltage + 1.0e-12
        and dc_bus_current <= max_bus_current + 1.0e-9
        and topology_power_kw <= max_converter_power_kw + 1.0e-12
        and total_cells == series_cells * parallel_strings
        and abs(identity_error) <= 1.0e-9 * max(reference_power_kw, 1.0)
    )
    return {
        "stack_feasible": bool(feasible),
        "stack_infeasibility_reason": "" if feasible else "integer topology identity failure",
        "stack_series_cells": series_cells,
        "stack_parallel_strings": parallel_strings,
        "stack_total_cells": total_cells,
        "stack_cell_active_area_m2": cell_area,
        "stack_cell_terminal_current_a": cell_terminal_current,
        "stack_maximum_local_current_density_a_m2": maximum_current_density_a_m2,
        "stack_local_current_density_limit_interpretation": (
            "reported separately; no finite current-collector segment model"
        ),
        "stack_string_voltage_v": string_voltage,
        "stack_dc_bus_current_a": dc_bus_current,
        "stack_topology_power_kw": topology_power_kw,
        "stack_reference_cell_power_kw": reference_power_kw,
        "stack_power_identity_error_kw": identity_error,
        "stack_state_matching_assumption": (
            "series groups contain hydraulically parallel, state-matched repeat cells; "
            "axially dissimilar cells are not silently placed in one series string"
        ),
    }


def add_geometry_and_stack(
    *,
    row: dict[str, Any],
    axial: ModuleType,
    process_basis: Any,
    base_config: Mapping[str, Any],
    v12_config: Mapping[str, Any],
) -> dict[str, Any]:
    area = float(row.get("required_active_area_m2", 0.0))
    if area <= 0.0:
        return {
            **row,
            "process_channel_fan_power_kw": 0.0,
            "receiver_channel_fan_power_kw": 0.0,
            "stack_feasible": False,
            "stack_infeasibility_reason": "no positive active area",
        }
    process_geometry = axial.process_channel_fan(
        active_area_m2=area,
        config=dict(base_config),
        basis=process_basis,
    )
    channel = base_config["channel"]
    receiver_geometry = channel_pressure_drop_and_fan(
        axial=axial,
        active_area_m2=area,
        total_channel_width_m=float(row["receiver_total_channel_width_m"]),
        active_sides=float(channel["active_sides_per_process_channel"]),
        gap_m=float(channel["receiver_gap_m"]),
        velocity_m_s=float(row["receiver_velocity_m_s"]),
        volume_flow_m3_s=float(row["selected_actual_volume_flow_m3_s"]),
        temperature_c=float(row["temperature_c"]),
        pressure_pa=float(row["pressure_pa"]),
        humidity_ratio_kg_kg_da=float(
            row["inlet_humidity_ratio_kg_kg_da"]
        ),
        fan_efficiency=float(v12_config["channel"]["receiver_fan_efficiency"]),
    )
    topology = stack_topology(
        required_area_m2=area,
        integrated_current_a=float(row.get("integrated_current_a", 0.0)),
        maximum_current_density_a_m2=float(
            row.get("maximum_local_current_density_a_m2", 0.0)
        ),
        cell_terminal_voltage_v=float(row["terminal_voltage_v"]),
        stack_config=v12_config["stack"],
    )
    return {
        **row,
        **process_geometry,
        "process_channel_fan_power_kw": float(
            process_geometry["process_fan_power_kw"]
        ),
        "receiver_channel_length_m": receiver_geometry["channel_length_m"],
        "receiver_channel_reynolds_number": receiver_geometry[
            "channel_reynolds_number"
        ],
        "receiver_channel_pressure_drop_pa": receiver_geometry[
            "channel_pressure_drop_pa"
        ],
        "receiver_channel_fan_power_kw": receiver_geometry[
            "channel_fan_power_kw"
        ],
        **topology,
    }


def product_water_pump_power_kw(
    water_kg_h: float,
    head_m: float,
    pump_efficiency: float,
) -> float:
    if water_kg_h < 0.0 or head_m < 0.0:
        raise ValueError("Water flow and pump head cannot be negative")
    validate_fraction(pump_efficiency, "product-water pump efficiency")
    return water_kg_h * 9.80665 * head_m / (3.6e6 * pump_efficiency)


def external_fan_power_kw(
    volume_flow_m3_s: float,
    pressure_drop_pa: float,
    efficiency: float,
) -> float:
    if volume_flow_m3_s < 0.0 or pressure_drop_pa < 0.0:
        raise ValueError("Flow and pressure drop cannot be negative")
    validate_fraction(efficiency, "fan efficiency")
    return volume_flow_m3_s * pressure_drop_pa / efficiency / 1000.0


def expand_energy_scenarios(
    physical: pd.DataFrame,
    gross_budget_kw: Mapping[str, float],
    config: Mapping[str, Any],
    mode_config: Mapping[str, Any],
    process_volume_flow_m3_s: float,
) -> pd.DataFrame:
    energy = config["energy_scenarios"]
    rows: list[dict[str, Any]] = []
    regeneration_values = [float(v) for v in mode_config["regeneration_electric_equivalent_sec_kwh_e_per_kg"]]
    receiver_external_dp_values = [
        float(v) for v in mode_config["receiver_external_pressure_drop_pa"]
    ]
    product_heads = [float(v) for v in mode_config["product_water_pump_head_m"]]
    thermal_cops = mode_config["thermal_management_cop"]
    controls_kw = float(energy["controls_and_instrumentation_power_kw"])
    process_external_dp = float(energy["process_external_pressure_drop_pa"])
    process_fan_efficiency = float(config["channel"]["process_fan_efficiency"])
    receiver_fan_efficiency = float(config["channel"]["receiver_fan_efficiency"])
    pump_efficiency = float(energy["product_water_pump_efficiency"])
    heat_fraction = float(energy["cell_power_to_managed_heat_fraction"])
    for _, source in physical.iterrows():
        base = source.to_dict()
        raw_worker_exception = base.get("worker_exception", "")
        worker_exception = (
            ""
            if pd.isna(raw_worker_exception)
            else str(raw_worker_exception).strip()
        )
        if worker_exception:
            rows.append(
                {
                    **base,
                    "energy_scenario_evaluated": False,
                    "stack_feasible": False,
                    "thermal_management_declared": False,
                    "thermal_management_cop": math.nan,
                    "regeneration_electric_equivalent_sec_kwh_e_per_kg": math.nan,
                    "known_non_regeneration_power_kw": math.nan,
                    "gross_hvac_electric_opportunity_kw": float(
                        gross_budget_kw[str(base["target"])]
                    ),
                    "break_even_regeneration_electric_equivalent_sec_kwh_e_per_kg": math.nan,
                    "declared_incremental_predryer_power_kw": math.nan,
                    "declared_incremental_energy_margin_kw": math.nan,
                    "fraction_of_gross_opportunity_remaining": math.nan,
                    "declared_incremental_budget_positive": False,
                    "total_hvac_or_building_saving_percent": math.nan,
                    "full_system_saving_claim_allowed": False,
                    "claim_guard_reason": "worker exception; no energy ledger evaluated",
                }
            )
            continue
        target_reached = strict_bool_value(base["target_reached"])
        water_kg_h = float(base["integrated_water_transfer_kg_h"])
        process_external_fan = external_fan_power_kw(
            process_volume_flow_m3_s,
            process_external_dp,
            process_fan_efficiency,
        )
        for regeneration_sec in regeneration_values:
            for receiver_external_dp in receiver_external_dp_values:
                receiver_external_fan = external_fan_power_kw(
                    float(base["selected_actual_volume_flow_m3_s"]),
                    receiver_external_dp,
                    receiver_fan_efficiency,
                )
                for pump_head in product_heads:
                    product_pump = product_water_pump_power_kw(
                        water_kg_h, pump_head, pump_efficiency
                    )
                    for thermal_cop_raw in thermal_cops:
                        thermal_declared = thermal_cop_raw is not None
                        thermal_cop = (
                            float(thermal_cop_raw) if thermal_declared else math.nan
                        )
                        if thermal_declared and thermal_cop <= 0.0:
                            raise ValueError("Thermal-management COP must be positive")
                        thermal_power = (
                            heat_fraction * float(base["cell_power_kw"]) / thermal_cop
                            if thermal_declared
                            else math.nan
                        )
                        regeneration_power = regeneration_sec * water_kg_h
                        known_non_regen = (
                            float(base["eo_grid_power_kw"])
                            + float(base["process_channel_fan_power_kw"])
                            + process_external_fan
                            + float(base["receiver_channel_fan_power_kw"])
                            + receiver_external_fan
                            + product_pump
                            + controls_kw
                            + (thermal_power if thermal_declared else 0.0)
                        )
                        gross = float(gross_budget_kw[str(base["target"])])
                        break_even_regen = (
                            (gross - known_non_regen) / water_kg_h
                            if target_reached and water_kg_h > 0.0 and thermal_declared
                            else math.nan
                        )
                        total_declared = (
                            known_non_regen + regeneration_power
                            if thermal_declared
                            else math.nan
                        )
                        margin = (
                            gross - total_declared
                            if target_reached
                            and thermal_declared
                            and strict_bool_value(base["water_balance_pass"])
                            else math.nan
                        )
                        rows.append(
                            {
                                **base,
                                "energy_scenario_evaluated": True,
                                "regeneration_electric_equivalent_sec_kwh_e_per_kg": regeneration_sec,
                                "regeneration_power_kw": regeneration_power,
                                "receiver_external_pressure_drop_pa": receiver_external_dp,
                                "receiver_external_fan_power_kw": receiver_external_fan,
                                "process_external_pressure_drop_pa": process_external_dp,
                                "process_external_fan_power_kw": process_external_fan,
                                "product_water_pump_head_m": pump_head,
                                "product_water_pump_power_kw": product_pump,
                                "controls_and_instrumentation_power_kw": controls_kw,
                                "thermal_management_declared": thermal_declared,
                                "thermal_management_cop": thermal_cop,
                                "thermal_management_power_kw": thermal_power,
                                "known_non_regeneration_power_kw": known_non_regen,
                                "declared_incremental_predryer_power_kw": total_declared,
                                "gross_hvac_electric_opportunity_kw": gross,
                                "break_even_regeneration_electric_equivalent_sec_kwh_e_per_kg": break_even_regen,
                                "declared_incremental_energy_margin_kw": margin,
                                "fraction_of_gross_opportunity_remaining": (
                                    margin / gross
                                    if math.isfinite(margin) and gross > 0.0
                                    else math.nan
                                ),
                                "declared_incremental_budget_positive": bool(
                                    math.isfinite(margin) and margin >= 0.0
                                ),
                                "total_hvac_or_building_saving_percent": math.nan,
                                "full_system_saving_claim_allowed": False,
                                "claim_guard_reason": (
                                    "hypothetical material; no complete first-law, electrode-chemistry, "
                                    "lifetime, leakage or validated regeneration model"
                                ),
                            }
                        )
    return pd.DataFrame(rows)


def pareto_mask(frame: pd.DataFrame, columns: Sequence[str], minimise: Sequence[bool]) -> np.ndarray:
    values = frame[list(columns)].to_numpy(float)
    transformed = values.copy()
    for index, flag in enumerate(minimise):
        if not flag:
            transformed[:, index] *= -1.0
    keep = np.ones(len(frame), dtype=bool)
    for i in range(len(frame)):
        if not keep[i]:
            continue
        dominates_i = np.all(transformed <= transformed[i], axis=1) & np.any(
            transformed < transformed[i], axis=1
        )
        if dominates_i.any():
            keep[i] = False
    return keep


def select_results(energy: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    nonworker = energy[
        energy["worker_exception"].fillna("").astype(str).str.strip().eq("")
    ].copy()
    if nonworker.empty:
        return pd.DataFrame(), pd.DataFrame()
    eligible = nonworker[
        strict_boolean_series(nonworker["target_reached"])
        & strict_boolean_series(nonworker["water_balance_pass"])
        & strict_boolean_series(nonworker["thermal_management_declared"])
        & strict_boolean_series(nonworker["stack_feasible"])
        & np.isfinite(nonworker["declared_incremental_energy_margin_kw"])
    ].copy()
    if eligible.empty:
        return pd.DataFrame(), pd.DataFrame()
    group_columns = [
        "target",
        "receiver_sizing_target",
        "band_id",
        "flow_arrangement",
        "capacity_multiplier",
        "electrode_pair_loss_voltage_v",
        "added_contact_asr_ohm_m2",
        "regeneration_electric_equivalent_sec_kwh_e_per_kg",
        "receiver_external_pressure_drop_pa",
        "product_water_pump_head_m",
        "thermal_management_cop",
    ]
    ordered = eligible.sort_values(
        [
            *group_columns,
            "declared_incremental_energy_margin_kw",
            "required_active_area_m2",
            "maximum_local_current_density_a_m2",
            "terminal_voltage_v",
        ],
        ascending=[True] * len(group_columns) + [False, True, True, True],
    )
    optima = ordered.groupby(group_columns, sort=True, dropna=False).head(1).copy()
    # Use the already reduced per-scenario optima.  Computing an O(n²) front
    # over every algebraic energy expansion would duplicate identical physical
    # points and can become needlessly expensive.
    pareto_parts: list[pd.DataFrame] = []
    for (target, receiver_sizing_target), group in optima.groupby(
        ["target", "receiver_sizing_target"], sort=True
    ):
        group = group.copy()
        mask = pareto_mask(
            group,
            [
                "required_active_area_m2",
                "declared_incremental_predryer_power_kw",
                "maximum_local_current_density_a_m2",
            ],
            [True, True, True],
        )
        selected = group.loc[mask].copy()
        selected.insert(0, "pareto_target", target)
        selected.insert(1, "pareto_receiver_sizing_target", receiver_sizing_target)
        pareto_parts.append(selected)
    pareto = pd.concat(pareto_parts, ignore_index=True) if pareto_parts else pd.DataFrame()
    return optima.reset_index(drop=True), pareto.reset_index(drop=True)


def configure_plots() -> None:
    plt.rcParams.update(
        {
            "font.size": 9.5,
            "axes.titlesize": 11,
            "axes.labelsize": 10,
            "legend.fontsize": 8.5,
            "figure.dpi": 130,
            "savefig.dpi": 220,
        }
    )


def save_figure(fig: plt.Figure, output_dir: Path, stem: str) -> None:
    fig.savefig(output_dir / f"{stem}.png", bbox_inches="tight")
    fig.savefig(output_dir / f"{stem}.pdf", bbox_inches="tight")
    plt.close(fig)


def make_plots(
    physical: pd.DataFrame,
    energy: pd.DataFrame,
    optima: pd.DataFrame,
    output_dir: Path,
) -> None:
    configure_plots()
    reached = physical[
        strict_boolean_series(physical["target_reached"])
        & strict_boolean_series(physical["water_balance_pass"])
    ].copy()
    colors = {"M08666": "#167D9A", "M08786": "#E08B2C", "M11675": "#8B5FBF"}
    if not reached.empty:
        fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.4), sharex=True)
        for material_id, group in reached.groupby("material_id", sort=True):
            color = colors.get(str(material_id), None)
            for target, target_group in group.groupby("target", sort=True):
                reduced = (
                    target_group.groupby("terminal_voltage_v", as_index=False)
                    .agg(
                        required_active_area_m2=("required_active_area_m2", "min"),
                        eo_grid_power_kw=("eo_grid_power_kw", "min"),
                    )
                    .sort_values("terminal_voltage_v")
                )
                label = f"{material_id} · {target}"
                linestyle = "-" if target == "O50" else "--"
                axes[0].plot(
                    reduced["terminal_voltage_v"],
                    reduced["required_active_area_m2"],
                    color=color,
                    linestyle=linestyle,
                    label=label,
                )
                axes[1].plot(
                    reduced["terminal_voltage_v"],
                    reduced["eo_grid_power_kw"],
                    color=color,
                    linestyle=linestyle,
                    label=label,
                )
        for axis in axes:
            axis.axvline(1.0, color="black", linestyle=":", linewidth=1.2, label="Eksakt 1,000 V")
            axis.grid(alpha=0.25)
            axis.set_xlabel("Cellens terminalspenning [V]")
        axes[0].set_ylabel("Nødvendig aktivt membranareal [m²]")
        axes[1].set_ylabel("EO-nett-effekt [kW]")
        axes[0].set_title("Koblet mottaker: areal mot spenning")
        axes[1].set_title("Koblet mottaker: EO-effekt mot spenning")
        handles, labels = axes[0].get_legend_handles_labels()
        unique = dict(zip(labels, handles))
        fig.legend(unique.values(), unique.keys(), loc="upper center", ncol=4, frameon=False)
        fig.tight_layout(rect=(0, 0, 1, 0.86))
        save_figure(fig, output_dir, "01_coupled_voltage_response")

        fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.4))
        for target, axis in zip(("O50", "O30"), axes):
            subset = reached[reached["target"].astype(str).eq(target)]
            for material_id, group in subset.groupby("material_id", sort=True):
                axis.scatter(
                    group["required_active_area_m2"],
                    group["eo_grid_power_kw"]
                    + group["process_channel_fan_power_kw"]
                    + group["receiver_channel_fan_power_kw"],
                    s=18,
                    alpha=0.45,
                    label=material_id,
                    color=colors.get(str(material_id), None),
                )
            axis.set_title(f"{target}: areal–effekt-avveining")
            axis.set_xlabel("Aktivt membranareal [m²]")
            axis.set_ylabel("EO + begge kanalvifter [kW]")
            axis.grid(alpha=0.25)
        axes[0].legend(frameon=False)
        fig.tight_layout()
        save_figure(fig, output_dir, "02_area_power_tradeoff")

    eligible_energy = energy[
        strict_boolean_series(energy["target_reached"])
        & strict_boolean_series(energy["thermal_management_declared"])
        & np.isfinite(energy["break_even_regeneration_electric_equivalent_sec_kwh_e_per_kg"])
    ].copy()
    if not eligible_energy.empty:
        fig, axis = plt.subplots(figsize=(8.8, 5.0))
        summary = (
            eligible_energy.groupby(["target", "material_id"], as_index=False)[
                "break_even_regeneration_electric_equivalent_sec_kwh_e_per_kg"
            ]
            .max()
        )
        x = np.arange(len(summary))
        axis.bar(
            x,
            summary["break_even_regeneration_electric_equivalent_sec_kwh_e_per_kg"],
            color=[colors.get(str(value), "#777777") for value in summary["material_id"]],
        )
        axis.set_xticks(
            x,
            [f"{target}\n{material}" for target, material in zip(summary["target"], summary["material_id"])],
        )
        axis.set_ylabel("Maksimal regenereringsenergi før nullmargin [kWhₑ/kg]")
        axis.set_title("Break-even etter EO, begge vifter og øvrige deklarerte ledd")
        axis.grid(axis="y", alpha=0.25)
        fig.tight_layout()
        save_figure(fig, output_dir, "03_break_even_regeneration")

    if not optima.empty:
        stack = optima[strict_boolean_series(optima["stack_feasible"])].copy()
        if not stack.empty:
            fig, axis = plt.subplots(figsize=(8.5, 5.2))
            for material_id, group in stack.groupby("material_id", sort=True):
                axis.scatter(
                    group["stack_string_voltage_v"],
                    group["stack_dc_bus_current_a"],
                    label=material_id,
                    color=colors.get(str(material_id), None),
                    alpha=0.7,
                )
            axis.set_xlabel("Estimert DC-strengspenning [V]")
            axis.set_ylabel("Estimert samlet DC-busstrøm [A]")
            axis.set_title("Illustrativ serie-/parallellarkitektur")
            axis.grid(alpha=0.25)
            axis.legend(frameon=False)
            fig.tight_layout()
            save_figure(fig, output_dir, "04_stack_voltage_current")


def build_tasks(
    *,
    candidates: pd.DataFrame,
    targets: pd.DataFrame,
    voltages: np.ndarray,
    config: Mapping[str, Any],
    mode_config: Mapping[str, Any],
) -> list[dict[str, Any]]:
    selected_ids = [str(value) for value in mode_config["candidate_material_ids"]]
    material_rows = candidates[candidates["material_id"].astype(str).isin(selected_ids)]
    if set(selected_ids) != set(material_rows["material_id"].astype(str)):
        raise ValueError("Mode requests a material absent from validated V11 candidates")
    target_rows = target_map(targets)
    requested_targets = [str(value) for value in mode_config["targets"]]
    if not set(requested_targets).issubset(target_rows):
        raise ValueError("Mode requests an unknown target")
    tasks: list[dict[str, Any]] = []
    for _, material in material_rows.sort_values("material_id").iterrows():
        for target in requested_targets:
            receiver_sizing_targets = [target]
            if target == "O30" and strict_bool_value(mode_config["o30_include_o50_sized_receiver_flow"]):
                receiver_sizing_targets = ["O50", "O30"]
            for receiver_sizing_target in receiver_sizing_targets:
                for band_id in mode_config["receiver_band_ids"]:
                    for arrangement in mode_config["flow_arrangements"]:
                        for multiplier in mode_config["receiver_capacity_multipliers"]:
                            for electrode_loss in mode_config["electrode_pair_loss_voltages_v"]:
                                for contact_asr in mode_config["added_contact_asr_ohm_m2"]:
                                    for voltage in voltages:
                                        tasks.append(
                                            {
                                                "task_index": len(tasks),
                                                "material": {
                                                    "material_id": str(material["material_id"]),
                                                    **{
                                                        name: float(material[name])
                                                        for name in MATERIAL_COLUMNS
                                                    },
                                                },
                                                "target": target,
                                                "receiver_sizing_target": receiver_sizing_target,
                                                "band_id": str(band_id),
                                                "flow_arrangement": str(arrangement),
                                                "capacity_multiplier": float(multiplier),
                                                "electrode_pair_loss_voltage_v": float(electrode_loss),
                                                "added_contact_asr_ohm_m2": float(contact_asr),
                                                "terminal_voltage_v": float(voltage),
                                            }
                                        )
    return tasks


def task_identity(task: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "task_index": int(task["task_index"]),
        "material_id": str(task["material"]["material_id"]),
        "target": str(task["target"]),
        "receiver_sizing_target": str(task["receiver_sizing_target"]),
        "band_id": str(task["band_id"]),
        "flow_arrangement": str(task["flow_arrangement"]),
        "capacity_multiplier": float(task["capacity_multiplier"]),
        "electrode_pair_loss_voltage_v": float(task["electrode_pair_loss_voltage_v"]),
        "added_contact_asr_ohm_m2": float(task["added_contact_asr_ohm_m2"]),
        "terminal_voltage_v": float(task["terminal_voltage_v"]),
    }


def initialise_worker(
    axial_script: str,
    v2_root: str,
    base_config_path: str,
    v12_config_path: str,
    mode: str,
) -> None:
    axial = load_module(
        Path(axial_script), f"heiq_axial_v3_worker_v12_{os.getpid()}"
    )
    v2_path = Path(v2_root)
    v2 = axial.load_v2_module(v2_path)
    v2_config = v2.load_config(v2_path / "config" / "default.json")
    base_config = load_json(Path(base_config_path))
    v12_config = load_json(Path(v12_config_path))
    mode_config = v12_config["modes"][mode]
    base_config = copy.deepcopy(base_config)
    base_config["channel"]["active_sides_per_process_channel"] = float(
        v12_config["channel"]["active_sides_per_process_channel"]
    )
    base_config["channel"]["process_fan_efficiency"] = float(
        v12_config["channel"]["process_fan_efficiency"]
    )
    base_config["channel"]["receiver_geometry_mode"] = str(
        v12_config["channel"]["receiver_geometry_mode"]
    )
    base_config["channel"]["fixed_receiver_velocity_m_s"] = float(
        v12_config["channel"]["fixed_receiver_velocity_m_s"]
    )
    base_config["integration"].update(
        {
            key: value
            for key, value in mode_config.get("integration_overrides", {}).items()
        }
    )
    base_config["integration"]["mass_balance_relative_tolerance"] = float(
        v12_config["integration"]["mass_balance_relative_tolerance"]
    )
    axial.validate_config(base_config)
    process_basis = axial.dry_air_mass_flow(base_config)
    targets = axial.build_targets(base_config, process_basis, v2_config)
    _WORKER_CONTEXT.clear()
    _WORKER_CONTEXT.update(
        {
            "axial": axial,
            "v2": v2,
            "v2_config": v2_config,
            "base_config": base_config,
            "v12_config": v12_config,
            "mode_config": mode_config,
            "process_basis": process_basis,
            "targets": target_map(targets),
        }
    )


def solve_task(task: Mapping[str, Any]) -> dict[str, Any]:
    context = _WORKER_CONTEXT
    identity = task_identity(task)
    try:
        axial = context["axial"]
        base_config = context["base_config"]
        v12_config = context["v12_config"]
        targets = context["targets"]
        target_row = targets[str(task["target"])]
        receiver_sizing_target_row = targets[str(task["receiver_sizing_target"])]
        band_id = str(task["band_id"])
        receiver = make_receiver_basis(
            axial=axial,
            process_basis=context["process_basis"],
            target_row=target_row,
            receiver_sizing_target_row=receiver_sizing_target_row,
            band_id=band_id,
            band=v12_config["receiver_bands"][band_id],
            capacity_multiplier=float(task["capacity_multiplier"]),
            flow_arrangement=str(task["flow_arrangement"]),
            base_config=base_config,
        )
        summary, _ = integrate_coupled_receiver_case(
            axial=axial,
            v2=context["v2"],
            v2_config=context["v2_config"],
            config=base_config,
            process_basis=context["process_basis"],
            target_row=target_row,
            material=make_material(task["material"]),
            receiver=receiver,
            terminal_voltage_v=float(task["terminal_voltage_v"]),
            electrode_pair_loss_voltage_v=float(
                task["electrode_pair_loss_voltage_v"]
            ),
            legacy_series_asr_ohm_m2=float(
                v12_config["operating"]["legacy_series_asr_ohm_m2"]
            ),
            added_contact_asr_ohm_m2=float(task["added_contact_asr_ohm_m2"]),
            power_electronics_efficiency=float(
                v12_config["operating"]["power_electronics_efficiency"]
            ),
            current_cap_a_m2=float(
                v12_config["operating"]["current_density_cap_a_m2"]
            ),
            film_scale_factor=float(
                v12_config["operating"]["film_scale_factor"]
            ),
            record_profile=False,
        )
        summary = add_geometry_and_stack(
            row=summary,
            axial=axial,
            process_basis=context["process_basis"],
            base_config=base_config,
            v12_config=v12_config,
        )
        return {**identity, **summary}
    except BaseException as error:
        return {
            **identity,
            "status": "worker_exception",
            "target_reached": False,
            "target_capacity_sufficient": False,
            "water_balance_evaluated": False,
            "water_balance_pass": False,
            "local_solver_evaluated": False,
            "integrated_water_transfer_kg_h": math.nan,
            "selected_actual_volume_flow_m3_s": math.nan,
            "stack_feasible": False,
            "worker_exception": f"{type(error).__name__}: {error}",
        }


def chunked(values: Sequence[Any], size: int) -> list[list[Any]]:
    return [list(values[index : index + size]) for index in range(0, len(values), size)]


def solve_chunk(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [solve_task(task) for task in tasks]


def checkpoint_path(directory: Path, index: int) -> Path:
    return directory / f"chunk_{index:06d}.csv.gz"


def validate_checkpoint(
    path: Path,
    tasks: Sequence[Mapping[str, Any]],
    plan_fingerprint: str,
) -> bool:
    try:
        frame = pd.read_csv(path, compression="gzip")
    except Exception:
        return False
    identity_columns = list(task_identity(tasks[0])) if tasks else []
    required = {
        *identity_columns,
        *CHECKPOINT_RESULT_COLUMNS,
        "run_plan_fingerprint",
    }
    if len(frame) != len(tasks) or required.difference(frame.columns):
        return False
    if not frame["run_plan_fingerprint"].astype(str).eq(plan_fingerprint).all():
        return False
    numeric_identity = {
        "task_index",
        "capacity_multiplier",
        "electrode_pair_loss_voltage_v",
        "added_contact_asr_ohm_m2",
        "terminal_voltage_v",
    }
    for row_index, task in enumerate(tasks):
        expected = task_identity(task)
        row = frame.iloc[row_index]
        for name, expected_value in expected.items():
            if name in numeric_identity:
                try:
                    observed = float(row[name])
                except (TypeError, ValueError):
                    return False
                if not math.isclose(
                    observed,
                    float(expected_value),
                    rel_tol=1.0e-13,
                    abs_tol=1.0e-15,
                ):
                    return False
            elif str(row[name]) != str(expected_value):
                return False
    try:
        for name in (
            "target_reached",
            "water_balance_evaluated",
            "water_balance_pass",
            "local_solver_evaluated",
        ):
            strict_boolean_series(frame[name])
    except ValueError:
        return False
    return True


def process_tasks(
    *,
    chunks: Sequence[list[dict[str, Any]]],
    checkpoint_dir: Path,
    workers: int,
    initializer_args: tuple[Any, ...],
    resume: bool,
    plan_fingerprint: str,
) -> None:
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    pending: list[tuple[int, list[dict[str, Any]]]] = []
    for index, tasks in enumerate(chunks):
        path = checkpoint_path(checkpoint_dir, index)
        if path.exists():
            if resume and validate_checkpoint(path, tasks, plan_fingerprint):
                continue
            raise RuntimeError(
                f"Existing V12 checkpoint is invalid or resume is disabled: {path}"
            )
        pending.append((index, tasks))
    if not pending:
        print("All requested V12 chunks already exist; continuing to summarisation.")
        return

    def save(index: int, rows: list[dict[str, Any]]) -> None:
        frame = pd.DataFrame(rows).sort_values("task_index")
        frame["run_plan_fingerprint"] = plan_fingerprint
        atomic_write_csv(frame, checkpoint_path(checkpoint_dir, index), compression="gzip")

    if workers == 1:
        initialise_worker(*initializer_args)
        for completed, (index, tasks) in enumerate(pending, start=1):
            save(index, solve_chunk(tasks))
            if completed == len(pending) or completed % 10 == 0:
                print(f"V12 checkpoints: {completed}/{len(pending)}", flush=True)
        return

    with ProcessPoolExecutor(
        max_workers=workers,
        initializer=initialise_worker,
        initargs=initializer_args,
    ) as executor:
        futures = {
            executor.submit(solve_chunk, tasks): (index, tasks)
            for index, tasks in pending
        }
        for completed, future in enumerate(as_completed(futures), start=1):
            index, _ = futures[future]
            save(index, future.result())
            if completed == len(pending) or completed % 10 == 0:
                print(f"V12 checkpoints: {completed}/{len(pending)}", flush=True)


def combine_checkpoints(
    chunks: Sequence[list[dict[str, Any]]],
    checkpoint_dir: Path,
    plan_fingerprint: str,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for index, tasks in enumerate(chunks):
        path = checkpoint_path(checkpoint_dir, index)
        if not path.is_file() or not validate_checkpoint(
            path, tasks, plan_fingerprint
        ):
            raise RuntimeError(f"Missing or invalid V12 checkpoint: {path}")
        frames.append(pd.read_csv(path, compression="gzip"))
    combined = pd.concat(frames, ignore_index=True).sort_values("task_index")
    expected = list(range(sum(len(chunk) for chunk in chunks)))
    observed = pd.to_numeric(combined["task_index"], errors="raise").astype(int).tolist()
    if observed != expected:
        raise RuntimeError("Combined V12 task coverage is incomplete or duplicated")
    return combined.reset_index(drop=True)


def run_step_halving_audit(
    *,
    tasks: Sequence[dict[str, Any]],
    physical: pd.DataFrame,
    initializer_args: tuple[Any, ...],
    relative_tolerance: float,
    maximum_cases: int,
    required_task_indices: Iterable[int] = (),
) -> pd.DataFrame:
    """Re-solve declared optima and numerical boundary cases at half step."""
    reached = physical[
        strict_boolean_series(physical["target_reached"])
        & strict_boolean_series(physical["water_balance_pass"])
    ].copy()
    columns = [
        "task_index",
        "material_id",
        "target",
        "receiver_sizing_target",
        "nominal_area_step_m2",
        "halved_area_step_m2",
        "nominal_status",
        "halved_status",
        "selection_reason",
        "required_area_relative_change",
        "eo_grid_power_relative_change",
        "integrated_water_relative_change",
        "integrated_current_relative_change",
        "cell_power_relative_change",
        "receiver_far_end_relative_change",
        "receiver_boundary_residual_absolute_change",
        "audit_pass",
    ]
    if reached.empty:
        return pd.DataFrame(columns=columns)
    strata = [
        "material_id",
        "target",
        "receiver_sizing_target",
        "band_id",
        "flow_arrangement",
        "capacity_multiplier",
        "electrode_pair_loss_voltage_v",
        "added_contact_asr_ohm_m2",
    ]
    reasons: dict[int, set[str]] = {}

    def add_rows(frame: pd.DataFrame, reason: str) -> None:
        for value in pd.to_numeric(frame["task_index"], errors="raise").astype(int):
            reasons.setdefault(int(value), set()).add(reason)

    grouped = reached.groupby(strata, sort=True, dropna=False)
    add_rows(
        reached.loc[grouped["terminal_voltage_v"].idxmin().to_numpy()],
        "minimum_voltage",
    )
    add_rows(
        reached.loc[grouped["terminal_voltage_v"].idxmax().to_numpy()],
        "maximum_voltage_exact_1v",
    )
    add_rows(
        reached.loc[grouped["eo_grid_power_kw"].idxmin().to_numpy()],
        "minimum_eo_power",
    )
    required_set = {int(value) for value in required_task_indices}
    if required_set:
        required_rows = reached[
            pd.to_numeric(reached["task_index"], errors="coerce")
            .astype(int)
            .isin(required_set)
        ]
        add_rows(required_rows, "declared_topology_feasible_optimum")
        present = set(pd.to_numeric(required_rows["task_index"]).astype(int))
        missing = required_set.difference(present)
        if missing:
            raise RuntimeError(
                "A declared optimum is absent from the successful physical rows: "
                f"{sorted(missing)}"
            )
    if len(reasons) > maximum_cases:
        raise RuntimeError(
            f"Step-halving audit needs {len(reasons)} cases but the declared cap is "
            f"{maximum_cases}; raise integration.maximum_step_halving_cases"
        )
    representatives = reached[
        pd.to_numeric(reached["task_index"], errors="coerce")
        .astype(int)
        .isin(reasons)
    ].sort_values("task_index")
    task_lookup = {int(task["task_index"]): task for task in tasks}
    initialise_worker(*initializer_args)
    integration = _WORKER_CONTEXT["base_config"]["integration"]
    nominal_step = float(integration["area_step_m2"])
    nominal_minimum = float(integration["minimum_area_step_m2"])
    integration["area_step_m2"] = 0.5 * nominal_step
    integration["minimum_area_step_m2"] = 0.5 * nominal_minimum

    def relative_change(new: float, old: float) -> float:
        scale = max(abs(new), abs(old), 1.0e-12)
        return abs(new - old) / scale

    rows: list[dict[str, Any]] = []
    try:
        for _, nominal in representatives.iterrows():
            task_index = int(nominal["task_index"])
            halved = solve_task(task_lookup[task_index])
            changes = {
                "required_area_relative_change": relative_change(
                    float(halved.get("required_active_area_m2", math.nan)),
                    float(nominal["required_active_area_m2"]),
                ),
                "eo_grid_power_relative_change": relative_change(
                    float(halved.get("eo_grid_power_kw", math.nan)),
                    float(nominal["eo_grid_power_kw"]),
                ),
                "integrated_water_relative_change": relative_change(
                    float(
                        halved.get("integrated_water_transfer_kg_h", math.nan)
                    ),
                    float(nominal["integrated_water_transfer_kg_h"]),
                ),
                "integrated_current_relative_change": relative_change(
                    float(halved.get("integrated_current_a", math.nan)),
                    float(nominal["integrated_current_a"]),
                ),
                "cell_power_relative_change": relative_change(
                    float(halved.get("cell_power_kw", math.nan)),
                    float(nominal["cell_power_kw"]),
                ),
                "receiver_far_end_relative_change": relative_change(
                    float(
                        halved.get(
                            "receiver_calculated_far_end_humidity_ratio_kg_kg_da",
                            math.nan,
                        )
                    ),
                    float(
                        nominal[
                            "receiver_calculated_far_end_humidity_ratio_kg_kg_da"
                        ]
                    ),
                ),
            }
            nominal_residual = float(
                nominal["receiver_boundary_residual_humidity_ratio"]
            )
            halved_residual = float(
                halved.get("receiver_boundary_residual_humidity_ratio", math.nan)
            )
            residual_change = (
                0.0
                if str(nominal["flow_arrangement"]) == "co_current"
                else abs(halved_residual - nominal_residual)
            )
            finite_changes = all(math.isfinite(value) for value in changes.values())
            audit_pass = bool(
                str(halved.get("status")) == "target_reached"
                and strict_bool_value(halved.get("water_balance_pass", False))
                and finite_changes
                and max(changes.values()) <= relative_tolerance
                and math.isfinite(residual_change)
                and residual_change <= max(1.0e-10, relative_tolerance * 1.0e-8)
            )
            rows.append(
                {
                    "task_index": task_index,
                    "material_id": nominal["material_id"],
                    "target": nominal["target"],
                    "receiver_sizing_target": nominal["receiver_sizing_target"],
                    "nominal_area_step_m2": nominal_step,
                    "halved_area_step_m2": 0.5 * nominal_step,
                    "nominal_status": nominal["status"],
                    "halved_status": halved.get("status"),
                    "selection_reason": ";".join(sorted(reasons[task_index])),
                    **changes,
                    "receiver_boundary_residual_absolute_change": residual_change,
                    "audit_pass": audit_pass,
                }
            )
    finally:
        integration["area_step_m2"] = nominal_step
        integration["minimum_area_step_m2"] = nominal_minimum
    return pd.DataFrame(rows, columns=columns)


def write_summary(
    path: Path,
    *,
    mode: str,
    physical: pd.DataFrame,
    energy: pd.DataFrame,
    status: Mapping[str, Any],
) -> None:
    reached = int(strict_boolean_series(physical["target_reached"]).sum())
    exact = physical[pd.to_numeric(physical["terminal_voltage_v"]) == 1.0]
    lines = [
        "# HeiQ V12 — coupled receiver/system analysis",
        "",
        f"- Script version: `{SCRIPT_VERSION}`",
        f"- Mode: `{mode}`",
        f"- Physical solver rows: {len(physical):,}",
        f"- Rows reaching their fixed humidity-ratio target: {reached:,}",
        f"- Newly solved exact 1.000-V rows: {len(exact):,}",
        f"- Expanded declared energy scenarios: {len(energy):,}",
        f"- Analysis complete: `{status['analysis_complete']}`",
        "",
        "## What changed from V11",
        "",
        "V11 prescribed receiver water activity at 0.50 everywhere. V12 instead "
        "updates both process and receiver humidity at each axial area step and "
        "re-solves the unchanged V2/V3 local membrane equations. Counter-current "
        "is the primary arrangement; co-current can be selected as a sensitivity.",
        "",
        "The 1.000-V rows are new solver evaluations. They are not interpolation "
        "between the V11 points at 0.814961 and 1.019759 V.",
        "",
        "## Interpretation guard",
        "",
        "The energy quantity is a declared incremental margin relative to the gross "
        "HVAC opportunity. It is not total HVAC or building energy saving. Every "
        "selected material remains a hypothetical property combination. Electric-"
        "equivalent regeneration SEC, external pressure drops, electrode loss, "
        "contact resistance, pump head, "
        "thermal-management COP and stack constraints are declared inputs rather than "
        "measured properties.",
        "",
        "A full-system saving claim is deliberately disabled in every result row.",
    ]
    atomic_write_text(path, "\n".join(lines) + "\n")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_dir", type=Path, nargs="?", default=DEFAULT_V11_DIR)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--mode", choices=("smoke", "study", "sensitivity"), default="study")
    parser.add_argument("--axial-script", type=Path, default=DEFAULT_AXIAL_SCRIPT)
    parser.add_argument("--v2-root", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--workers", type=int)
    parser.add_argument("--chunk-size", type=int)
    parser.add_argument(
        "--resume", action=argparse.BooleanOptionalAction, default=True
    )
    parser.add_argument("--analysis-only", action="store_true")
    parser.add_argument("--skip-plots", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    source_dir = args.source_dir.resolve()
    config_path = args.config.resolve()
    axial_script = args.axial_script.resolve()
    if not config_path.is_file():
        raise FileNotFoundError(f"Missing V12 config: {config_path}")
    if not axial_script.is_file():
        raise FileNotFoundError(f"Missing V3 axial script: {axial_script}")
    config = load_json(config_path)
    validate_config(config)
    mode_config = config["modes"][args.mode]
    source = validate_v11_source(source_dir, config)
    v2_root = resolve_v2_root(args.v2_root, source_dir)
    solver_hashes = validate_unchanged_solver_sources(
        source_dir, axial_script, v2_root
    )
    default_output_name = (
        DEFAULT_OUTPUT_NAME
        if args.mode == "study"
        else f"{DEFAULT_OUTPUT_NAME}_{args.mode}"
    )
    output_dir = (
        args.output_dir.resolve()
        if args.output_dir is not None
        else (source_dir / default_output_name).resolve()
    )
    v11_checkpoint_dir = (source_dir / "checkpoints").resolve()
    if (
        output_dir == source_dir
        or output_dir in source_dir.parents
        or output_dir == v11_checkpoint_dir
        or v11_checkpoint_dir in output_dir.parents
    ):
        raise ValueError(
            "V12 output must not be V11, a V11 parent, or inside V11 checkpoints"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_dir = output_dir / "checkpoints"

    axial = load_module(axial_script, "heiq_axial_v3_main_v12")
    v2 = axial.load_v2_module(v2_root)
    v2_config = v2.load_config(v2_root / "config" / "default.json")
    base_config = load_json(source_dir / "axial_base_config_used.json")
    compatibility_base_config = copy.deepcopy(base_config)
    base_config["channel"]["active_sides_per_process_channel"] = float(
        config["channel"]["active_sides_per_process_channel"]
    )
    base_config["channel"]["process_fan_efficiency"] = float(
        config["channel"]["process_fan_efficiency"]
    )
    base_config["channel"]["receiver_geometry_mode"] = str(
        config["channel"]["receiver_geometry_mode"]
    )
    base_config["channel"]["fixed_receiver_velocity_m_s"] = float(
        config["channel"]["fixed_receiver_velocity_m_s"]
    )
    base_config["integration"].update(mode_config.get("integration_overrides", {}))
    base_config["integration"]["mass_balance_relative_tolerance"] = float(
        config["integration"]["mass_balance_relative_tolerance"]
    )
    axial.validate_config(base_config)
    process_basis = axial.dry_air_mass_flow(base_config)
    targets = axial.build_targets(base_config, process_basis, v2_config)
    # Independent numerical anchors prevent accidental psychrometric drift.
    expected_basis = config["regression_anchors"]
    if not math.isclose(
        process_basis.volume_flow_m3_s,
        float(expected_basis["actual_volume_flow_m3_s"]),
        rel_tol=1.0e-10,
        abs_tol=1.0e-10,
    ):
        raise RuntimeError("150,000-actual-cfm volume-flow regression failed")
    if not math.isclose(
        process_basis.dry_air_mass_flow_kg_s,
        float(expected_basis["dry_air_mass_flow_kg_s"]),
        rel_tol=1.0e-9,
        abs_tol=1.0e-9,
    ):
        raise RuntimeError("Dry-air mass-flow regression failed")
    target_rows = target_map(targets)
    for target, expected_load in expected_basis["water_load_kg_h"].items():
        if not math.isclose(
            water_load_kg_h(target_rows[target]),
            float(expected_load),
            rel_tol=1.0e-8,
            abs_tol=1.0e-6,
        ):
            raise RuntimeError(f"{target} water-load regression failed")
    recomputed_gross_budget_kw = {
        target: float(row["scaled_gross_hvac_opportunity_kw"])
        for target, row in target_rows.items()
    }
    for target, recomputed in recomputed_gross_budget_kw.items():
        if not math.isclose(
            float(source["gross_budget_kw"][target]),
            recomputed,
            rel_tol=1.0e-10,
            abs_tol=1.0e-8,
        ):
            raise RuntimeError(
                f"V11 gross HVAC opportunity for {target} does not match "
                "the unchanged V2/V3 target calculation"
            )

    voltages = build_voltage_grid(source["voltage_frame"], config, mode_config)
    tasks = build_tasks(
        candidates=source["candidates"],
        targets=targets,
        voltages=voltages,
        config=config,
        mode_config=mode_config,
    )
    workers = int(args.workers if args.workers is not None else mode_config["default_workers"])
    chunk_size = int(
        args.chunk_size if args.chunk_size is not None else mode_config["chunk_size"]
    )
    if workers <= 0 or chunk_size <= 0:
        raise ValueError("workers and chunk size must be positive")
    chunks = chunked(tasks, chunk_size)
    plan = {
        "script_version": SCRIPT_VERSION,
        "mode": args.mode,
        "source_v11_script_version": source["status"]["script_version"],
        "source_v11_run_fingerprint": source["plan"].get("fingerprint"),
        "physical_task_count": len(tasks),
        "chunk_count": len(chunks),
        "chunk_size": chunk_size,
        "candidate_ids": sorted({task["material"]["material_id"] for task in tasks}),
        "targets": sorted({task["target"] for task in tasks}),
        "receiver_sizing_targets": sorted({task["receiver_sizing_target"] for task in tasks}),
        "flow_arrangements": sorted({task["flow_arrangement"] for task in tasks}),
        "receiver_bands": sorted({task["band_id"] for task in tasks}),
        "voltage_count": len(voltages),
        "exact_1v_in_grid": sum(float(v) == 1.0 for v in voltages) == 1,
        "maximum_cell_terminal_voltage_v": float(np.max(voltages)),
        "file_sha256": {
            "v12_script": sha256_file(Path(__file__).resolve()),
            "v12_config": sha256_file(config_path),
            "v3_axial_script": sha256_file(axial_script),
            "v2_model": sha256_file(v2_root / "heiq_pre_receiver_model.py"),
            "v2_default_config": sha256_file(v2_root / "config" / "default.json"),
            "v11_analysis_status": sha256_file(source_dir / "analysis_status.json"),
            "v11_run_plan": sha256_file(source_dir / "run_plan.json"),
            "v11_source_manifest": sha256_file(source_dir / "source_manifest.json"),
            "v11_candidate_materials": sha256_file(
                source_dir / "candidate_materials.csv"
            ),
            "v11_material_grid": sha256_file(source_dir / "material_grid_used.csv"),
            "v11_voltage_grid": sha256_file(source_dir / "voltage_grid_used.csv"),
            "v11_axial_base_config": sha256_file(
                source_dir / "axial_base_config_used.json"
            ),
            "v11_final_dataset": sha256_file(source_dir / V11_FINAL_DATASET),
            **{
                f"v11_{Path(name).stem}": sha256_file(source_dir / name)
                for name in V11_AUDIT_FILES
            },
        },
        "unchanged_solver_source_sha256": solver_hashes,
    }
    plan["fingerprint"] = json_fingerprint(plan)
    plan_path = output_dir / "run_plan.json"
    if plan_path.is_file():
        old_plan = load_json(plan_path)
        if old_plan.get("fingerprint") != plan["fingerprint"]:
            raise RuntimeError(
                "Existing V12 output has a different run plan. Use a new --output-dir."
            )
    else:
        atomic_write_json(plan_path, plan)
    atomic_write_json(output_dir / "v12_config_used.json", config)
    atomic_write_json(output_dir / "axial_base_config_used.json", base_config)
    atomic_write_csv(targets, output_dir / "targets_used.csv")
    atomic_write_csv(
        source["candidates"][
            source["candidates"]["material_id"].astype(str).isin(
                mode_config["candidate_material_ids"]
            )
        ],
        output_dir / "candidate_materials_used.csv",
    )
    atomic_write_csv(
        pd.DataFrame(
            {
                "voltage_index": np.arange(len(voltages), dtype=int),
                "terminal_voltage_v": voltages,
                "is_exact_1v": [float(value) == 1.0 for value in voltages],
                "new_solver_evaluation": [
                    not (
                        pd.to_numeric(
                            source["voltage_frame"]["terminal_voltage_v"], errors="coerce"
                        )
                        == float(value)
                    ).any()
                    for value in voltages
                ],
            }
        ),
        output_dir / "voltage_grid_used.csv",
    )
    compatibility_path = output_dir / "fixed_receiver_compatibility_audit.csv"
    expected_compatibility_rows = int(
        mode_config["fixed_receiver_compatibility_anchor_rows"]
    )
    if args.analysis_only:
        if not compatibility_path.is_file():
            raise RuntimeError(
                "--analysis-only requires an existing fixed_receiver_compatibility_audit.csv"
            )
        compatibility_audit = pd.read_csv(compatibility_path)
    else:
        compatibility_audit = run_fixed_receiver_compatibility_audit(
            axial=axial,
            v2=v2,
            v2_config=v2_config,
            base_config=compatibility_base_config,
            process_basis=process_basis,
            targets=target_rows,
            cases=source["cases"],
            anchor_file=source_dir / "v8_anchor_reproduction.csv",
            maximum_rows=expected_compatibility_rows,
        )
        atomic_write_csv(compatibility_audit, compatibility_path)
    compatibility_pass = bool(
        len(compatibility_audit) == expected_compatibility_rows
        and not compatibility_audit.empty
        and strict_boolean_series(
            compatibility_audit["compatibility_pass"]
        ).all()
    )

    print(
        f"V12 {args.mode}: {len(tasks):,} coupled physical cases, "
        f"{len(voltages):,} voltages including exact 1.000 V, "
        f"{len(chunks):,} chunks.",
        flush=True,
    )
    if not args.analysis_only:
        process_tasks(
            chunks=chunks,
            checkpoint_dir=checkpoint_dir,
            workers=workers,
            initializer_args=(
                str(axial_script),
                str(v2_root),
                str(source_dir / "axial_base_config_used.json"),
                str(config_path),
                args.mode,
            ),
            resume=bool(args.resume),
            plan_fingerprint=plan["fingerprint"],
        )
    physical = combine_checkpoints(
        chunks, checkpoint_dir, plan["fingerprint"]
    )
    worker_errors = physical["worker_exception"].fillna("").astype(str).str.strip().ne("")
    atomic_write_csv(
        physical,
        output_dir / "closed_receiver_physical_cases.csv.gz",
        compression="gzip",
    )
    initializer_args = (
        str(axial_script),
        str(v2_root),
        str(source_dir / "axial_base_config_used.json"),
        str(config_path),
        args.mode,
    )
    energy = expand_energy_scenarios(
        physical,
        recomputed_gross_budget_kw,
        config,
        mode_config,
        process_basis.volume_flow_m3_s,
    )
    atomic_write_csv(
        energy,
        output_dir / "closed_receiver_energy_scenarios.csv.gz",
        compression="gzip",
    )
    optima, pareto = select_results(energy)
    atomic_write_csv(optima, output_dir / "declared_scenario_optima.csv")
    atomic_write_csv(pareto, output_dir / "declared_system_pareto_front.csv")
    audit_path = output_dir / "step_halving_convergence_audit.csv"
    if args.analysis_only:
        if not audit_path.is_file():
            raise RuntimeError(
                "--analysis-only requires an existing step_halving_convergence_audit.csv"
            )
        convergence_audit = pd.read_csv(audit_path)
    else:
        required_audit_indices = (
            []
            if optima.empty
            else pd.to_numeric(optima["task_index"], errors="raise")
            .astype(int)
            .unique()
            .tolist()
        )
        convergence_audit = run_step_halving_audit(
            tasks=tasks,
            physical=physical,
            initializer_args=initializer_args,
            relative_tolerance=float(
                config["integration"]["step_halving_relative_tolerance"]
            ),
            maximum_cases=int(
                config["integration"]["maximum_step_halving_cases"]
            ),
            required_task_indices=required_audit_indices,
        )
        atomic_write_csv(convergence_audit, audit_path)

    exact_rows = physical[pd.to_numeric(physical["terminal_voltage_v"]) == 1.0]
    expected_exact = sum(
        1 for task in tasks if float(task["terminal_voltage_v"]) == 1.0
    )
    exact_nonworker = exact_rows[
        exact_rows["worker_exception"].fillna("").astype(str).str.strip().eq("")
    ].copy()
    exact_capacity_feasible = exact_nonworker[
        strict_boolean_series(exact_nonworker["target_capacity_sufficient"])
    ]
    exact_solver_coverage_pass = bool(
        not exact_capacity_feasible.empty
        and strict_boolean_series(
            exact_capacity_feasible["local_solver_evaluated"]
        ).all()
    )
    reached = physical[strict_boolean_series(physical["target_reached"])].copy()
    balance_pass = (
        True
        if reached.empty
        else strict_boolean_series(reached["water_balance_pass"]).all()
    )
    audited_indices = (
        set()
        if convergence_audit.empty
        else set(
            pd.to_numeric(convergence_audit["task_index"], errors="raise").astype(int)
        )
    )
    selected_indices = (
        set()
        if optima.empty
        else set(pd.to_numeric(optima["task_index"], errors="raise").astype(int))
    )
    convergence_coverage_pass = bool(
        reached.empty
        or (
            not convergence_audit.empty
            and selected_indices.issubset(audited_indices)
        )
    )
    convergence_pass = bool(
        convergence_coverage_pass
        and (
            reached.empty
            or strict_boolean_series(convergence_audit["audit_pass"]).all()
        )
    )
    evaluated_energy = energy[
        energy["energy_scenario_evaluated"].fillna(False).map(
            lambda value: strict_bool_value(value)
        )
    ].copy()
    thermal_energy = evaluated_energy[
        strict_boolean_series(evaluated_energy["thermal_management_declared"])
        & strict_boolean_series(evaluated_energy["target_reached"])
        & strict_boolean_series(evaluated_energy["water_balance_pass"])
    ].copy()
    ledger_columns = [
        "known_non_regeneration_power_kw",
        "declared_incremental_predryer_power_kw",
        "gross_hvac_electric_opportunity_kw",
        "break_even_regeneration_electric_equivalent_sec_kwh_e_per_kg",
    ]
    ledger_complete = bool(
        not thermal_energy.empty
        and np.isfinite(
            thermal_energy[ledger_columns].apply(pd.to_numeric, errors="coerce")
        ).all().all()
    )
    status = {
        "script_version": SCRIPT_VERSION,
        "analysis_complete": bool(
            len(physical) == len(tasks)
            and not worker_errors.any()
            and len(exact_rows) == expected_exact
            and exact_solver_coverage_pass
            and balance_pass
            and convergence_pass
            and ledger_complete
            and compatibility_pass
        ),
        "source_v11_validation_pass": True,
        "physical_row_count": len(physical),
        "expected_physical_row_count": len(tasks),
        "worker_exception_count": int(worker_errors.sum()),
        "target_reached_row_count": len(reached),
        "coupled_water_balance_pass": bool(balance_pass),
        "step_halving_convergence_pass": convergence_pass,
        "step_halving_coverage_pass": convergence_coverage_pass,
        "step_halving_audit_row_count": len(convergence_audit),
        "exact_1v_coverage_pass": bool(
            len(exact_rows) == expected_exact and exact_solver_coverage_pass
        ),
        "exact_1v_row_count": len(exact_rows),
        "expected_exact_1v_row_count": expected_exact,
        "exact_1v_is_new_physical_solver_evaluation": exact_solver_coverage_pass,
        "exact_1v_capacity_feasible_solver_row_count": len(
            exact_capacity_feasible
        ),
        "interpolation_used_for_1v": False,
        "energy_scenario_row_count": len(energy),
        "declared_energy_ledger_complete_for_rows_with_thermal_scenario": (
            ledger_complete
        ),
        "analysis_only_reused_existing_convergence_audit": bool(
            args.analysis_only
        ),
        "fixed_receiver_compatibility_pass": compatibility_pass,
        "fixed_receiver_compatibility_row_count": len(compatibility_audit),
        "expected_fixed_receiver_compatibility_row_count": (
            expected_compatibility_rows
        ),
        "v11_anchor_reproduction_audit_imported_pass": True,
        "unchanged_v2_v3_source_hashes_pass": True,
        "o30_o50_sized_case_scope": (
            "receiver dry-air flow only; membrane area, voltage and stack are not "
            "held fixed between targets"
        ),
        "full_first_law_validation_pass": False,
        "material_validation_pass": False,
        "global_material_optimum_claim": False,
        "total_system_saving_claim_allowed": False,
        "scope": (
            "Selected hypothetical V11 candidates in a coupled two-dry-air-stream "
            "model with declared receiver, loss, regeneration, fan, pump, thermal "
            "and integer-stack scenarios. No real-material or full-system validation."
        ),
    }
    atomic_write_json(output_dir / "analysis_status.json", status)
    write_summary(
        output_dir / "summary.md",
        mode=args.mode,
        physical=physical,
        energy=energy,
        status=status,
    )
    if not args.skip_plots and not worker_errors.any():
        make_plots(physical, energy, optima, output_dir)
    if not status["analysis_complete"]:
        raise RuntimeError(
            "V12 completed with failed coverage/balance/worker gates; inspect analysis_status.json"
        )
    print(json.dumps(status, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
