#!/usr/bin/env python3
"""Run an exact zero-current Nafion control for the shared ERV core.

The control keeps the active-study air-side architecture, endpoint target,
counter-current segmentation, film correlations, membrane thickness and
Nafion property correlations.  Its only mechanism change is the electrical
boundary condition: the membrane is open circuit and current density is
exactly zero.  Consequently electro-osmotic drag is exactly zero and all
water transfer is passive diffusion.

Positive water flux is defined from the humid process stream to the balanced
return/exhaust stream.  This is an open-circuit control, not a zero-terminal-
voltage control: a membrane diffusion potential can exist while current is
zero.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import numpy as np
import pandas as pd
from scipy.integrate import quad
from scipy.optimize import brentq

from heiq.wp1.airside.properties import (
    ACTIVITY_EPS,
    MOLAR_MASS_WATER_KG_MOL,
    R_UNIVERSAL_J_MOL_K,
    activity_from_t_w,
    calculate_film_state,
)
from heiq.wp1.membrane.local_transport import legacy_v2_module
from heiq.wp1.studies.direct_eo_erv import (
    DirectEOEndpoints,
    direct_eo_core_hydraulics,
    build_direct_eo_endpoints,
    build_passive_baseline,
    build_segments,
    segment_balance_audit,
    solve_coil,
    states_from_config,
)


SCRIPT_VERSION = "direct-passive-nafion-erv-control-v1.0-2026-08-27"
FARADAY_C_MOL = 96485.33212
CONTROL_SCRIPT = Path(__file__).resolve()
ACTIVE_ERV_MODULE = ROOT / "src" / "heiq" / "wp1" / "studies" / "direct_eo_erv.py"
CANONICAL_V2_MODEL = (
    ROOT / "heiq_pre_receiver_material_analyses" / "heiq_pre_receiver_model.py"
)
DEFAULT_CONFIG = ROOT / "config" / "direct_eo_erv_study_v1.json"
DEFAULT_V2_CONFIG = (
    ROOT / "heiq_pre_receiver_material_analyses" / "config" / "default.json"
)
DEFAULT_ACTIVE_CASE_REGISTER = (
    ROOT
    / "outputs"
    / "direct_active_eo_erv_study_v1"
    / "nafion_sensitivity"
    / "case_register.csv"
)
DEFAULT_ACTIVE_CASE_ID = (
    "case_00936__nafion_nr211_nominal_reference__w9p5__v0p0005"
    "__n8__eps0p85__film2__symmetric_split"
)
DEFAULT_OUTPUT = ROOT / "outputs" / "direct_passive_nafion_erv_control_v1"


@dataclass(frozen=True)
class ControlCoordinates:
    material_id: str
    process_outlet_w_g_kg_da: float
    segment_count: int
    sensible_effectiveness: float
    film_scale_factor: float
    electric_heat_scenario_id: str
    matched_active_case_id: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--v2-config", type=Path, default=DEFAULT_V2_CONFIG)
    parser.add_argument(
        "--active-case-register",
        type=Path,
        default=DEFAULT_ACTIVE_CASE_REGISTER,
    )
    parser.add_argument("--active-case-id", default=DEFAULT_ACTIVE_CASE_ID)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        value = float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _file_record(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    return {
        "path": str(resolved),
        "sha256": _sha256(resolved),
        "size_bytes": resolved.stat().st_size,
    }


def validate_control_config(config: Mapping[str, Any]) -> None:
    architecture = config["architecture"]
    if architecture.get("id") != "shared_core_same_stream":
        raise ValueError("The control requires shared_core_same_stream")
    if architecture.get("same_exhaust_stream_used_once") is not True:
        raise ValueError("The shared exhaust stream must be used exactly once")
    if architecture.get("separate_receiver_loop") is not False:
        raise ValueError("A separate receiver loop is outside this control")
    if architecture.get("receiver_regeneration_required") is not False:
        raise ValueError("Receiver regeneration contradicts this shared-core control")
    if float(architecture.get("external_receiver_mass_flow_kg_s", math.nan)) != 0.0:
        raise ValueError("The control cannot use an external receiver stream")
    if not math.isclose(
        float(config["boundary"]["available_exhaust_to_process_ratio"]),
        1.0,
        rel_tol=0.0,
        abs_tol=1.0e-12,
    ):
        raise ValueError("The control requires balanced dry-air flows")


def coordinates_from_active_row(row: Mapping[str, Any]) -> ControlCoordinates:
    material_id = str(row["material_id"])
    if material_id != "nafion_nr211_nominal_reference":
        raise ValueError("The matched zero-current control currently requires Nafion")
    return ControlCoordinates(
        material_id=material_id,
        process_outlet_w_g_kg_da=float(row["process_outlet_w_g_kg_da"]),
        segment_count=int(row["segment_count"]),
        sensible_effectiveness=float(row["sensible_effectiveness"]),
        film_scale_factor=float(row["film_scale_factor"]),
        electric_heat_scenario_id=str(row["electric_heat_scenario_id"]),
        matched_active_case_id=str(row["case_id"]),
    )


def load_active_case(path: Path, case_id: str) -> tuple[ControlCoordinates, dict[str, Any]]:
    cases = pd.read_csv(path)
    selected = cases.loc[cases["case_id"].eq(case_id)]
    if len(selected) != 1:
        raise ValueError(f"Expected one active case {case_id!r}; found {len(selected)}")
    row = selected.iloc[0].to_dict()
    return coordinates_from_active_row(row), row


def _nafion_properties(
    *,
    v2: Any,
    v2_config: Mapping[str, Any],
    activity: float | np.ndarray,
    temperature_k: float,
    drag_scale_factor: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return hydration, capacity, permeability and drag via canonical V2."""

    a = np.clip(np.asarray(activity, dtype=float), ACTIVITY_EPS, 1.0 - ACTIVITY_EPS)
    hydration = np.asarray(v2.nafion_lambda(a), dtype=float)
    capacity = (
        float(v2_config["nafion"]["dry_polymer_density_kg_m3"])
        / float(v2_config["nafion"]["equivalent_weight_kg_mol"])
        * np.asarray(v2.nafion_dlambda_da(a), dtype=float)
    )
    diffusivity = np.asarray(
        v2.nafion_diffusivity_m2_s(hydration, temperature_k),
        dtype=float,
    )
    permeability = diffusivity * capacity
    drag = drag_scale_factor * np.asarray(v2.nafion_drag_prior(hydration), dtype=float)
    return hydration, capacity, permeability, drag


def solve_zero_current_nafion_state(
    *,
    v2: Any,
    v2_config: Mapping[str, Any],
    source_bulk_activity: float,
    receiver_bulk_activity: float,
    membrane_temperature_c: float,
    dry_thickness_um: float,
    drag_scale_factor: float,
    source_film_coefficient_mol_m2_s_activity: float,
    receiver_film_coefficient_mol_m2_s_activity: float,
) -> dict[str, Any]:
    """Solve the exact passive-film/Nafion flux at open circuit.

    For current density ``j=0``, the canonical constitutive law reduces to

      ``N = -D(a) S(a) da/dx``.

    With positive ``N`` from source to receiver, the two film conditions are
    ``a_s = a_s,bulk - N/k_s`` and ``a_r = a_r,bulk + N/k_r``.  The one unknown
    ``N`` is therefore the monotone scalar root

      ``N - integral[a_r(N), a_s(N)] D(a)S(a) da / L = 0``.
    """

    source_bulk = float(source_bulk_activity)
    receiver_bulk = float(receiver_bulk_activity)
    temperature_k = float(membrane_temperature_c) + 273.15
    thickness_m = float(dry_thickness_um) * 1.0e-6
    k_source = float(source_film_coefficient_mol_m2_s_activity)
    k_receiver = float(receiver_film_coefficient_mol_m2_s_activity)
    if not ACTIVITY_EPS < source_bulk < 1.0 - ACTIVITY_EPS:
        raise ValueError("source bulk activity is outside the open interval (0, 1)")
    if not ACTIVITY_EPS < receiver_bulk < 1.0 - ACTIVITY_EPS:
        raise ValueError("receiver bulk activity is outside the open interval (0, 1)")
    if thickness_m <= 0.0 or k_source <= 0.0 or k_receiver <= 0.0:
        raise ValueError("thickness and film coefficients must be positive")
    bulk_margin = source_bulk - receiver_bulk
    if bulk_margin <= 0.0:
        return {
            "solution_ok": False,
            "solution_status": "nonpositive_bulk_activity_gradient",
            "electrical_boundary_condition": "open_circuit_zero_current",
            "terminal_voltage_imposed": False,
            "current_density_a_m2": 0.0,
            "eo_flux_mol_m2_s": 0.0,
            "source_bulk_activity": source_bulk,
            "receiver_bulk_activity": receiver_bulk,
            "bulk_activity_margin": bulk_margin,
            "net_flux_mol_m2_s": math.nan,
            "diffusion_flux_mol_m2_s": math.nan,
        }

    def permeability(activity: float) -> float:
        return float(
            _nafion_properties(
                v2=v2,
                v2_config=v2_config,
                activity=activity,
                temperature_k=temperature_k,
                drag_scale_factor=drag_scale_factor,
            )[2]
        )

    equal_surface_flux = bulk_margin / (1.0 / k_source + 1.0 / k_receiver)

    def membrane_flux(net_flux: float) -> float:
        source_surface = source_bulk - net_flux / k_source
        receiver_surface = receiver_bulk + net_flux / k_receiver
        integral, _ = quad(
            permeability,
            receiver_surface,
            source_surface,
            epsabs=1.0e-14,
            epsrel=1.0e-11,
            limit=100,
        )
        return integral / thickness_m

    def residual(net_flux: float) -> float:
        return net_flux - membrane_flux(net_flux)

    net_flux = float(
        brentq(
            residual,
            0.0,
            equal_surface_flux,
            xtol=1.0e-14,
            rtol=1.0e-13,
            maxiter=100,
        )
    )
    source_surface = source_bulk - net_flux / k_source
    receiver_surface = receiver_bulk + net_flux / k_receiver
    membrane_flux_value = membrane_flux(net_flux)

    def open_circuit_integrand(activity: float) -> float:
        drag = float(
            _nafion_properties(
                v2=v2,
                v2_config=v2_config,
                activity=activity,
                temperature_k=temperature_k,
                drag_scale_factor=drag_scale_factor,
            )[3]
        )
        return drag * R_UNIVERSAL_J_MOL_K * temperature_k / FARADAY_C_MOL / activity

    open_circuit_voltage, _ = quad(
        open_circuit_integrand,
        source_surface,
        receiver_surface,
        epsabs=1.0e-14,
        epsrel=1.0e-11,
        limit=100,
    )
    profile_activity = np.linspace(source_surface, receiver_surface, 101)
    hydration, capacity, permeability_values, drag = _nafion_properties(
        v2=v2,
        v2_config=v2_config,
        activity=profile_activity,
        temperature_k=temperature_k,
        drag_scale_factor=drag_scale_factor,
    )
    minimum_lambda = float(np.min(hydration))
    correlation_valid = bool(
        minimum_lambda
        >= float(v2_config["nafion"]["minimum_correlation_lambda"])
    )
    constitutive_residual = net_flux - membrane_flux_value
    source_film_residual = net_flux - k_source * (source_bulk - source_surface)
    receiver_film_residual = net_flux - k_receiver * (
        receiver_surface - receiver_bulk
    )
    maximum_absolute_residual = max(
        abs(constitutive_residual),
        abs(source_film_residual),
        abs(receiver_film_residual),
    )
    solution_ok = bool(
        net_flux > 0.0
        and source_surface > receiver_surface
        and source_surface < source_bulk
        and receiver_surface > receiver_bulk
        and maximum_absolute_residual <= 1.0e-11
        and np.isfinite(permeability_values).all()
        and np.all(permeability_values > 0.0)
        and np.all(capacity > 0.0)
    )
    return {
        "solution_ok": solution_ok,
        "solution_status": (
            "passive_open_circuit_steady_state"
            if solution_ok
            else "passive_open_circuit_residual_failure"
        ),
        "electrical_boundary_condition": "open_circuit_zero_current",
        "terminal_voltage_imposed": False,
        "current_density_a_m2": 0.0,
        "integrated_current_a": 0.0,
        "eo_flux_mol_m2_s": 0.0,
        "net_flux_mol_m2_s": net_flux,
        "diffusion_flux_mol_m2_s": net_flux,
        "net_flux_kg_m2_h": net_flux * MOLAR_MASS_WATER_KG_MOL * 3600.0,
        "source_bulk_activity": source_bulk,
        "receiver_bulk_activity": receiver_bulk,
        "bulk_activity_margin": bulk_margin,
        "source_surface_activity": source_surface,
        "receiver_surface_activity": receiver_surface,
        "surface_activity_margin": source_surface - receiver_surface,
        "source_film_coefficient_mol_m2_s_activity": k_source,
        "receiver_film_coefficient_mol_m2_s_activity": k_receiver,
        "open_circuit_membrane_voltage_v": float(open_circuit_voltage),
        "ohmic_voltage_v": 0.0,
        "series_loss_voltage_v": 0.0,
        "cell_power_density_w_m2": 0.0,
        "constitutive_flux_residual_mol_m2_s": constitutive_residual,
        "source_film_flux_residual_mol_m2_s": source_film_residual,
        "receiver_film_flux_residual_mol_m2_s": receiver_film_residual,
        "maximum_absolute_flux_residual_mol_m2_s": maximum_absolute_residual,
        "hydration_lambda_min": minimum_lambda,
        "hydration_lambda_max": float(np.max(hydration)),
        "minimum_diffusive_permeability_mol_m_s_activity": float(
            np.min(permeability_values)
        ),
        "maximum_diffusive_permeability_mol_m_s_activity": float(
            np.max(permeability_values)
        ),
        "minimum_water_drag": float(np.min(drag)),
        "maximum_water_drag": float(np.max(drag)),
        "nafion_correlation_validity_gate": correlation_valid,
    }


def _strict_sum(values: Sequence[float]) -> float:
    array = np.asarray(values, dtype=float)
    return float(array.sum()) if array.size and np.isfinite(array).all() else math.nan


def _strict_min(values: Sequence[float]) -> float:
    array = np.asarray(values, dtype=float)
    return float(array.min()) if array.size and np.isfinite(array).all() else math.nan


def _strict_max(values: Sequence[float]) -> float:
    array = np.asarray(values, dtype=float)
    return float(array.max()) if array.size and np.isfinite(array).all() else math.nan


def solve_segmented_zero_current_nafion(
    *,
    v2: Any,
    v2_config: Mapping[str, Any],
    study_config: Mapping[str, Any],
    endpoints: DirectEOEndpoints,
    material: Mapping[str, Any],
    film_scale_factor: float,
    segment_count: int,
    process_film_scale_factor: float | None = None,
    receiver_film_scale_factor: float | None = None,
) -> tuple[dict[str, Any], pd.DataFrame]:
    """Size the segmented shared-core control with exactly zero current."""

    if str(material.get("model")) != "nafion":
        raise ValueError("The zero-current same-material control requires Nafion")
    solver = study_config["solver"]
    gates = study_config["gates"]
    channel = study_config["channel"]
    pressure = endpoints.process_in.pressure_pa
    process_scale = (
        float(film_scale_factor)
        if process_film_scale_factor is None
        else float(process_film_scale_factor)
    )
    receiver_scale = (
        float(film_scale_factor)
        if receiver_film_scale_factor is None
        else float(receiver_film_scale_factor)
    )
    segments = build_segments(
        endpoints,
        int(segment_count),
        str(solver["membrane_temperature_mode"]),
    )
    balance = segment_balance_audit(endpoints, segments)
    if not balance["pass"]:
        raise RuntimeError(f"Counter-current segment balance failed: {balance}")
    activity_basis = str(solver["activity_temperature_basis"]).strip().lower()
    membrane_temperature_mode = str(solver["membrane_temperature_mode"]).strip().lower()

    def membrane_temperature(process_t: float, receiver_t: float) -> float:
        if membrane_temperature_mode == "local_stream_mean":
            return 0.5 * (process_t + receiver_t)
        if membrane_temperature_mode == "process_mean":
            return process_t
        if membrane_temperature_mode == "receiver_mean":
            return receiver_t
        raise ValueError(f"Unknown membrane temperature mode {membrane_temperature_mode!r}")

    def solve_at_state(
        process_t: float,
        process_w: float,
        receiver_t: float,
        receiver_w: float,
        membrane_t: float,
    ) -> dict[str, Any]:
        if activity_basis == "membrane_isothermal":
            process_activity_t = membrane_t
            receiver_activity_t = membrane_t
            process_film_t = membrane_t
            receiver_film_t = membrane_t
        elif activity_basis == "stream_bulk_rh":
            process_activity_t = process_t
            receiver_activity_t = receiver_t
            process_film_t = process_t
            receiver_film_t = receiver_t
        else:
            raise ValueError(f"Unknown activity temperature basis {activity_basis!r}")
        source_activity = activity_from_t_w(process_activity_t, process_w, pressure)
        receiver_activity = activity_from_t_w(receiver_activity_t, receiver_w, pressure)
        source_film = calculate_film_state(
            side="process",
            temperature_c=process_film_t,
            velocity_m_s=float(channel["process_velocity_m_s"]),
            gap_m=float(channel["process_gap_m"]),
            pressure_pa=pressure,
            scale_factor=process_scale,
        )
        receiver_film = calculate_film_state(
            side="receiver",
            temperature_c=receiver_film_t,
            velocity_m_s=float(channel["receiver_velocity_m_s"]),
            gap_m=float(channel["receiver_gap_m"]),
            pressure_pa=pressure,
            scale_factor=receiver_scale,
        )
        return solve_zero_current_nafion_state(
            v2=v2,
            v2_config=v2_config,
            source_bulk_activity=source_activity,
            receiver_bulk_activity=receiver_activity,
            membrane_temperature_c=membrane_t,
            dry_thickness_um=float(material["dry_thickness_um"]),
            drag_scale_factor=float(material.get("drag_scale_factor", 1.0)),
            source_film_coefficient_mol_m2_s_activity=(
                source_film.activity_film_coefficient_mol_m2_s_activity
            ),
            receiver_film_coefficient_mol_m2_s_activity=(
                receiver_film.activity_film_coefficient_mol_m2_s_activity
            ),
        )

    boundary_states: list[tuple[float, float, float, float]] = [
        (
            segments[0].process_in_t_c,
            segments[0].process_in_w,
            segments[0].receiver_out_t_c,
            segments[0].receiver_out_w,
        )
    ]
    boundary_states.extend(
        (
            segment.process_out_t_c,
            segment.process_out_w,
            segment.receiver_in_t_c,
            segment.receiver_in_w,
        )
        for segment in segments
    )
    boundary_locals = [
        solve_at_state(
            process_t,
            process_w,
            receiver_t,
            receiver_w,
            membrane_temperature(process_t, receiver_t),
        )
        for process_t, process_w, receiver_t, receiver_w in boundary_states
    ]

    rows: list[dict[str, Any]] = []
    for segment in segments:
        process_mean_t = 0.5 * (segment.process_in_t_c + segment.process_out_t_c)
        receiver_mean_t = 0.5 * (segment.receiver_in_t_c + segment.receiver_out_t_c)
        process_mean_w = 0.5 * (segment.process_in_w + segment.process_out_w)
        receiver_mean_w = 0.5 * (segment.receiver_in_w + segment.receiver_out_w)
        local = solve_at_state(
            process_mean_t,
            process_mean_w,
            receiver_mean_t,
            receiver_mean_w,
            segment.membrane_temperature_c,
        )
        start = boundary_locals[segment.index]
        end = boundary_locals[segment.index + 1]
        flux = float(local.get("net_flux_mol_m2_s", math.nan))
        solution_ok = bool(local.get("solution_ok", False))
        positive_flux = bool(solution_ok and math.isfinite(flux) and flux > 0.0)
        duty_mol_s = (
            segment.water_transfer_kg_h / 3600.0 / MOLAR_MASS_WATER_KG_MOL
        )
        area = duty_mol_s / flux if positive_flux else math.nan
        start_surface_margin = float(start.get("surface_activity_margin", math.nan))
        end_surface_margin = float(end.get("surface_activity_margin", math.nan))
        start_bulk_margin = float(start.get("bulk_activity_margin", math.nan))
        end_bulk_margin = float(end.get("bulk_activity_margin", math.nan))
        boundary_solution_ok = bool(
            start.get("solution_ok", False)
            and end.get("solution_ok", False)
            and all(
                math.isfinite(value)
                for value in (
                    start_surface_margin,
                    end_surface_margin,
                    start_bulk_margin,
                    end_bulk_margin,
                )
            )
        )
        rows.append(
            {
                "segment_index": segment.index,
                "segment_count": segment.count,
                "x0": segment.x0,
                "x1": segment.x1,
                "x_mid": 0.5 * (segment.x0 + segment.x1),
                "process_mean_temperature_c": process_mean_t,
                "process_mean_humidity_ratio_kg_kg_da": process_mean_w,
                "receiver_mean_temperature_c": receiver_mean_t,
                "receiver_mean_humidity_ratio_kg_kg_da": receiver_mean_w,
                "membrane_temperature_c": segment.membrane_temperature_c,
                "activity_temperature_basis": activity_basis,
                "water_duty_kg_h": segment.water_transfer_kg_h,
                "solution_ok": solution_ok,
                "solution_status": local.get("solution_status", "unknown"),
                "electrical_boundary_condition": "open_circuit_zero_current",
                "terminal_voltage_imposed": False,
                "current_density_a_m2": 0.0,
                "integrated_current_a": 0.0,
                "eo_flux_mol_m2_s": 0.0,
                "net_flux_mol_m2_s": flux,
                "diffusion_flux_mol_m2_s": float(
                    local.get("diffusion_flux_mol_m2_s", math.nan)
                ),
                "net_flux_kg_m2_h": float(local.get("net_flux_kg_m2_h", math.nan)),
                "required_passive_membrane_area_m2": area,
                "source_bulk_activity": local.get("source_bulk_activity", math.nan),
                "receiver_bulk_activity": local.get("receiver_bulk_activity", math.nan),
                "bulk_activity_margin": local.get("bulk_activity_margin", math.nan),
                "source_surface_activity": local.get("source_surface_activity", math.nan),
                "receiver_surface_activity": local.get("receiver_surface_activity", math.nan),
                "surface_activity_margin": local.get("surface_activity_margin", math.nan),
                "boundary_solution_ok": boundary_solution_ok,
                "start_bulk_activity_margin": start_bulk_margin,
                "end_bulk_activity_margin": end_bulk_margin,
                "minimum_boundary_bulk_activity_margin": min(
                    start_bulk_margin, end_bulk_margin
                ),
                "start_surface_activity_margin": start_surface_margin,
                "end_surface_activity_margin": end_surface_margin,
                "minimum_boundary_surface_activity_margin": min(
                    start_surface_margin, end_surface_margin
                ),
                "open_circuit_membrane_voltage_v": local.get(
                    "open_circuit_membrane_voltage_v", math.nan
                ),
                "source_film_coefficient_mol_m2_s_activity": local.get(
                    "source_film_coefficient_mol_m2_s_activity", math.nan
                ),
                "receiver_film_coefficient_mol_m2_s_activity": local.get(
                    "receiver_film_coefficient_mol_m2_s_activity", math.nan
                ),
                "maximum_absolute_flux_residual_mol_m2_s": local.get(
                    "maximum_absolute_flux_residual_mol_m2_s", math.nan
                ),
                "nafion_correlation_validity_gate": local.get(
                    "nafion_correlation_validity_gate", False
                ),
            }
        )

    frame = pd.DataFrame(rows)
    complete = bool(
        len(frame) == segment_count
        and frame["solution_ok"].all()
        and frame["net_flux_mol_m2_s"].gt(0.0).all()
    )
    surface_complete = bool(
        complete
        and frame["boundary_solution_ok"].all()
    )
    correlation_validity_complete = bool(
        complete
        and frame["nafion_correlation_validity_gate"].all()
        and all(
            local.get("nafion_correlation_validity_gate", False)
            for local in boundary_locals
        )
    )
    area = _strict_sum(frame["required_passive_membrane_area_m2"].tolist())
    net_water = (
        _strict_sum(
            (
                frame["net_flux_mol_m2_s"]
                * frame["required_passive_membrane_area_m2"]
                * MOLAR_MASS_WATER_KG_MOL
                * 3600.0
            ).tolist()
        )
        if complete
        else math.nan
    )
    water_error = (
        (net_water - endpoints.water_transfer_kg_h)
        / max(abs(endpoints.water_transfer_kg_h), 1.0e-12)
        if complete
        else math.nan
    )
    minimum_surface_margin = _strict_min(
        frame["minimum_boundary_surface_activity_margin"].tolist()
    )
    minimum_bulk_margin = _strict_min(
        frame["minimum_boundary_bulk_activity_margin"].tolist()
    )
    result = {
        "transport_solution_complete": complete,
        "surface_diagnostic_complete": surface_complete,
        "nafion_correlation_validity_complete": correlation_validity_complete,
        "segment_count": segment_count,
        "electrical_boundary_condition": "open_circuit_zero_current",
        "terminal_voltage_imposed": False,
        "current_density_a_m2": 0.0,
        "integrated_current_a": 0.0,
        "integrated_eo_water_transfer_kg_h": 0.0,
        "cell_power_kw": 0.0,
        "eo_grid_power_kw": 0.0,
        "required_passive_membrane_area_m2": area,
        "minimum_net_flux_mol_m2_s": _strict_min(
            frame["net_flux_mol_m2_s"].tolist()
        ),
        "maximum_net_flux_mol_m2_s": _strict_max(
            frame["net_flux_mol_m2_s"].tolist()
        ),
        "effective_net_flux_mol_m2_s": (
            endpoints.water_transfer_kg_h
            / 3600.0
            / MOLAR_MASS_WATER_KG_MOL
            / area
            if complete and area > 0.0
            else math.nan
        ),
        "minimum_bulk_activity_margin": minimum_bulk_margin,
        "minimum_surface_activity_margin": minimum_surface_margin,
        "minimum_midpoint_surface_activity_margin": _strict_min(
            frame["surface_activity_margin"].tolist()
        ),
        "minimum_open_circuit_membrane_voltage_v": _strict_min(
            frame["open_circuit_membrane_voltage_v"].tolist()
        ),
        "maximum_open_circuit_membrane_voltage_v": _strict_max(
            frame["open_circuit_membrane_voltage_v"].tolist()
        ),
        "positive_surface_direction": bool(
            surface_complete
            and minimum_surface_margin
            > float(gates["minimum_positive_surface_activity_margin"])
        ),
        "robust_surface_direction": bool(
            surface_complete
            and minimum_surface_margin
            >= float(gates["robust_surface_activity_margin"])
        ),
        "water_transfer_target_kg_h": endpoints.water_transfer_kg_h,
        "integrated_net_water_transfer_kg_h": net_water,
        "integrated_diffusion_water_transfer_kg_h": net_water,
        "diffusion_fraction_of_net_water": 1.0 if complete else math.nan,
        "transport_water_balance_relative_error": water_error,
        "transport_water_balance_pass": bool(
            complete
            and abs(water_error) <= float(gates["water_balance_relative_tolerance"])
        ),
        "area_observation_cap_m2": float(solver["area_observation_cap_m2"]),
        "area_cap_pass": bool(
            complete and area <= float(solver["area_observation_cap_m2"])
        ),
        "maximum_absolute_flux_residual_mol_m2_s": _strict_max(
            frame["maximum_absolute_flux_residual_mol_m2_s"].tolist()
        ),
        "current_density_gate_applied": False,
        "stack_required": False,
        "power_electronics_required": False,
    }
    return result, frame


def run_control_case(
    *,
    coordinates: ControlCoordinates,
    config: Mapping[str, Any],
    v2: Any,
    v2_config: Mapping[str, Any],
) -> tuple[dict[str, Any], pd.DataFrame]:
    """Run the matched passive control including the existing thermal loop."""

    validate_control_config(config)
    material = dict(config["materials"][coordinates.material_id])
    if material.get("model") != "nafion":
        raise ValueError("Control material must use the Nafion model")
    heat = config["electric_heat_scenarios"][coordinates.electric_heat_scenario_id]
    states = states_from_config(config)
    baseline = build_passive_baseline(
        config,
        states,
        float(config["passive_baseline_erv"]["sensible_effectiveness"]),
    )
    boundary = config["boundary"]
    m_process = float(boundary["process_outdoor_dry_air_kg_s"])
    m_exhaust = m_process * float(boundary["available_exhaust_to_process_ratio"])
    target_w = coordinates.process_outlet_w_g_kg_da / 1000.0
    if target_w < states["supply"].w - 1.0e-12 or target_w >= states["outdoor"].w:
        raise ValueError("Control target lies outside the active-study target interval")

    solver_config = config["solver"]
    core_power_for_heat_kw = 0.0
    previous_temperatures: tuple[float, float] | None = None
    previous_power_kw: float | None = None
    thermal_converged = False
    temperature_residual_k = math.nan
    power_residual_fraction = math.nan
    endpoints: DirectEOEndpoints | None = None
    transport: dict[str, Any] = {}
    segments = pd.DataFrame()
    hydraulics: dict[str, Any] = {}
    core_power_kw = math.nan
    iteration = 0
    for iteration in range(
        1, int(solver_config["maximum_thermal_iterations"]) + 1
    ):
        endpoints = build_direct_eo_endpoints(
            process_in=states["outdoor"],
            exhaust_in=states["exhaust"],
            process_dry_air_kg_s=m_process,
            exhaust_dry_air_kg_s=m_exhaust,
            process_out_w=target_w,
            sensible_effectiveness=coordinates.sensible_effectiveness,
            active_core_electric_power_kw=core_power_for_heat_kw,
            process_heat_fraction=float(heat["process_fraction"]),
            exhaust_heat_fraction=float(heat["exhaust_fraction"]),
        )
        if not endpoints.valid:
            raise RuntimeError("Passive-control endpoints are invalid or supersaturated")
        transport, segments = solve_segmented_zero_current_nafion(
            v2=v2,
            v2_config=v2_config,
            study_config=config,
            endpoints=endpoints,
            material=material,
            film_scale_factor=coordinates.film_scale_factor,
            segment_count=coordinates.segment_count,
        )
        if not transport["transport_solution_complete"]:
            break
        hydraulics = direct_eo_core_hydraulics(
            endpoints=endpoints,
            active_area_m2=float(transport["required_passive_membrane_area_m2"]),
            config=config,
        )
        core_power_kw = (
            float(hydraulics["selected_active_core_fan_power_kw"])
            + float(config["active_core"]["motor_power_kw"])
            + float(config["active_core"]["controls_power_kw"])
        )
        temperatures = (endpoints.process_out.t_c, endpoints.exhaust_out.t_c)
        if previous_temperatures is not None and previous_power_kw is not None:
            temperature_residual_k = max(
                abs(temperatures[0] - previous_temperatures[0]),
                abs(temperatures[1] - previous_temperatures[1]),
            )
            power_residual_fraction = abs(core_power_kw - previous_power_kw) / max(
                abs(core_power_kw), 1.0e-9
            )
            if (
                temperature_residual_k
                <= float(solver_config["thermal_temperature_tolerance_k"])
                and power_residual_fraction
                <= float(solver_config["thermal_power_relative_tolerance"])
            ):
                thermal_converged = True
                break
        previous_temperatures = temperatures
        previous_power_kw = core_power_kw
        core_power_for_heat_kw = core_power_kw

    if endpoints is None:
        raise RuntimeError("No passive-control endpoint calculation was attempted")
    remaining_ac = solve_coil(
        inlet=endpoints.process_out,
        supply_target=states["supply"],
        m_da=m_process,
        rated_cop=baseline.rated_cop,
        ac_config=config["ac_model"],
    )
    exhaust_rh_pass = bool(
        endpoints.exhaust_out.rh <= float(config["gates"]["maximum_exhaust_outlet_rh"])
    )
    hydraulic_pass = bool(
        transport.get("transport_solution_complete", False)
        and float(hydraulics.get("process_channel_pressure_drop_pa", math.inf))
        <= float(config["gates"]["maximum_channel_pressure_drop_each_side_pa"])
        and float(hydraulics.get("receiver_channel_pressure_drop_pa", math.inf))
        <= float(config["gates"]["maximum_channel_pressure_drop_each_side_pa"])
    )
    decision_ready = bool(
        transport.get("transport_solution_complete", False)
        and transport.get("transport_water_balance_pass", False)
        and transport.get("area_cap_pass", False)
        and thermal_converged
        and endpoints.valid
        and exhaust_rh_pass
        and remaining_ac.physical
        and math.isfinite(core_power_kw)
    )
    common_kw = float(config["common_components"]["common_electric_power_kw_each_system"])
    total_power_kw = (
        core_power_kw + remaining_ac.total_ac_power_kw + common_kw
        if decision_ready
        else math.nan
    )
    saving_kw = baseline.total_power_kw - total_power_kw if decision_ready else math.nan
    summary = {
        "script_version": SCRIPT_VERSION,
        "control_id": (
            f"passive_open_circuit__{coordinates.matched_active_case_id}"
            if coordinates.matched_active_case_id
            else "passive_open_circuit_unmatched"
        ),
        "matched_active_case_id": coordinates.matched_active_case_id,
        "material_id": coordinates.material_id,
        "material_model": material["model"],
        "material_validated": bool(material.get("validated_material", False)),
        "architecture_id": config["architecture"]["id"],
        "same_exhaust_stream_used_once": True,
        "external_receiver_mass_flow_kg_s": 0.0,
        "electrical_boundary_condition": "open_circuit_zero_current",
        "zero_terminal_voltage_imposed": False,
        "current_density_a_m2": 0.0,
        "integrated_current_a": 0.0,
        "eo_flux_mol_m2_s": 0.0,
        "membrane_electric_power_kw": 0.0,
        "process_outlet_target_w_g_kg_da": coordinates.process_outlet_w_g_kg_da,
        "sensible_effectiveness": coordinates.sensible_effectiveness,
        "film_scale_factor": coordinates.film_scale_factor,
        "segment_count": coordinates.segment_count,
        "electric_heat_scenario_id": coordinates.electric_heat_scenario_id,
        "thermal_iteration_count": iteration,
        "thermal_fixed_point_converged": thermal_converged,
        "thermal_temperature_residual_k": temperature_residual_k,
        "thermal_power_residual_fraction": power_residual_fraction,
        "process_outlet_temperature_c": endpoints.process_out.t_c,
        "process_outlet_rh": endpoints.process_out.rh,
        "exhaust_outlet_temperature_c": endpoints.exhaust_out.t_c,
        "exhaust_outlet_rh": endpoints.exhaust_out.rh,
        "endpoint_water_balance_residual_kg_s": endpoints.water_balance_residual_kg_s,
        **transport,
        **hydraulics,
        "exhaust_rh_gate_pass": exhaust_rh_pass,
        "hydraulic_pressure_gate_pass": hydraulic_pass,
        "remaining_ac_power_kw": remaining_ac.total_ac_power_kw if decision_ready else math.nan,
        "passive_control_core_power_kw": core_power_kw if decision_ready else math.nan,
        "conditional_passive_control_total_power_kw": total_power_kw,
        "passive_erv_plus_ac_reference_kw": baseline.total_power_kw,
        "conditional_saving_kw_vs_passive_erv": saving_kw,
        "conditional_saving_pct_vs_passive_erv": (
            100.0 * saving_kw / baseline.total_power_kw if decision_ready else math.nan
        ),
        "conditional_decision_ready": decision_ready,
        "full_coupled_gate_pass": False,
        "full_system_claim_allowed": False,
        "claim_level": config["claim_boundary"]["claim_level"],
    }
    if not segments.empty:
        segments.insert(0, "control_id", summary["control_id"])
        segments.insert(1, "matched_active_case_id", coordinates.matched_active_case_id)
    return summary, segments


def compare_to_active_case(
    control: Mapping[str, Any], active: Mapping[str, Any]
) -> dict[str, Any]:
    passive_area = float(control["required_passive_membrane_area_m2"])
    active_area = float(active["required_active_area_m2"])
    return {
        "matched_active_case_id": str(active["case_id"]),
        "active_terminal_voltage_v": float(active["terminal_voltage_v"]),
        "active_required_area_m2": active_area,
        "passive_required_area_m2": passive_area,
        "passive_area_increase_m2": passive_area - active_area,
        "passive_area_increase_pct_vs_active": 100.0 * (passive_area / active_area - 1.0),
        "active_diffusion_fraction_of_net_water": float(
            active["diffusion_fraction_of_net_water"]
        ),
        "active_eo_grid_power_kw": float(active["eo_grid_power_kw"]),
        "passive_membrane_electric_power_kw": 0.0,
        "active_conditional_total_power_kw": float(active["conditional_active_total_power_kw"]),
        "passive_conditional_total_power_kw": float(
            control["conditional_passive_control_total_power_kw"]
        ),
        "passive_minus_active_total_power_kw": float(
            control["conditional_passive_control_total_power_kw"]
        )
        - float(active["conditional_active_total_power_kw"]),
        "interpretation": (
            "Matched mechanism control only; both rows retain the prescribed-effectiveness "
            "and ideal parallel-channel screening assumptions."
        ),
    }


def write_summary_markdown(
    path: Path,
    control: Mapping[str, Any],
    comparison: Mapping[str, Any],
) -> None:
    correlation_valid = bool(
        control["nafion_correlation_validity_complete"]
    )
    lines = [
        "# Matched zero-current Nafion control",
        "",
        (
            "This control uses the same shared-stream ERV architecture, target, "
            "segmentation, films, 25 µm Nafion reference and thermal accounting "
            "as the matched active row. Current and EO flux are exactly zero."
        ),
        "",
        "## Result",
        "",
        (
            "- Nafion correlation validity over every midpoint and physical "
            f"segment boundary: **{correlation_valid}**."
        ),
        (
            "- Passive membrane area: "
            f"**{float(comparison['passive_required_area_m2']):,.2f} m²**; "
            "matched active area: "
            f"**{float(comparison['active_required_area_m2']):,.2f} m²**."
        ),
        (
            "- Passive area penalty: "
            f"**{float(comparison['passive_area_increase_m2']):,.2f} m² "
            f"({float(comparison['passive_area_increase_pct_vs_active']):.3f}%)**."
        ),
        (
            "- Passive conditional total power: "
            f"**{float(comparison['passive_conditional_total_power_kw']):.3f} kW**; "
            "matched active total power: "
            f"**{float(comparison['active_conditional_total_power_kw']):.3f} kW**."
        ),
        (
            "- Passive minus active total power: "
            f"**{float(comparison['passive_minus_active_total_power_kw']):+.3f} kW** "
            "(negative means the passive control uses less electricity)."
        ),
        (
            "- The matched active row attributes "
            f"**{100.0 * float(comparison['active_diffusion_fraction_of_net_water']):.2f}%** "
            "of net water transfer to diffusion and consumes "
            f"**{float(comparison['active_eo_grid_power_kw']):.3f} kW** for EO."
        ),
        (
            "- Passive local flux range: "
            f"**{float(control['minimum_net_flux_mol_m2_s']):.6f}–"
            f"{float(control['maximum_net_flux_mol_m2_s']):.6f} mol m⁻² s⁻¹**; "
            "minimum physical-boundary surface margin: "
            f"**{float(control['minimum_surface_activity_margin']):.5f}**."
        ),
        (
            "- Open-circuit membrane potential range: "
            f"**{1.0e3 * float(control['minimum_open_circuit_membrane_voltage_v']):.3f} "
            f"to {1.0e3 * float(control['maximum_open_circuit_membrane_voltage_v']):.3f} mV**. "
            "No terminal voltage is imposed and this potential contributes no "
            "electric power at zero current."
        ),
        "",
        "## Interpretation",
        "",
        (
            "At this matched target, 0.5 mV EO buys only a small area reduction "
            "and does not buy an electrical-energy reduction relative to the exact "
            "zero-current control. The result is therefore primarily a passive-"
            "diffusion result, not evidence that EO drives the reported saving."
        ),
        "",
        (
            "`Nafion correlation validity = false` is material: at least one local "
            "state lies below the declared hydration range of the literature "
            "correlation. Nafion remains a numerical reference, not a validated "
            "material or device claim."
        ),
        "",
        (
            "This remains a prescribed-effectiveness segmented screen with idealized "
            "parallel-channel hydraulics. It does not enable a full-system or "
            "commercial claim."
        ),
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def run(
    *,
    config_path: Path,
    v2_config_path: Path,
    active_case_register: Path,
    active_case_id: str,
    output_dir: Path,
    overwrite: bool,
) -> dict[str, Any]:
    known = (
        "control_summary.json",
        "segment_register.csv",
        "matched_comparison.json",
        "SUMMARY.md",
        "audit.json",
    )
    existing = [output_dir / name for name in known if (output_dir / name).exists()]
    if existing and not overwrite:
        raise FileExistsError(f"Known control outputs already exist below {output_dir}")
    config = _load_json(config_path)
    validate_control_config(config)
    coordinates, active_row = load_active_case(active_case_register, active_case_id)
    v2 = legacy_v2_module()
    v2_config = v2.load_config(v2_config_path)
    summary, segments = run_control_case(
        coordinates=coordinates,
        config=config,
        v2=v2,
        v2_config=v2_config,
    )
    comparison = compare_to_active_case(summary, active_row)
    checks = [
        {
            "check_id": "exact_zero_current",
            "passed": bool(
                summary["current_density_a_m2"] == 0.0
                and summary["integrated_current_a"] == 0.0
            ),
        },
        {
            "check_id": "exact_zero_eo_flux",
            "passed": bool(
                summary["eo_flux_mol_m2_s"] == 0.0
                and summary["integrated_eo_water_transfer_kg_h"] == 0.0
            ),
        },
        {
            "check_id": "diffusion_equals_net",
            "passed": bool(
                np.allclose(
                    segments["diffusion_flux_mol_m2_s"],
                    segments["net_flux_mol_m2_s"],
                    rtol=0.0,
                    atol=1.0e-14,
                )
            ),
        },
        {
            "check_id": "water_balance",
            "passed": bool(summary["transport_water_balance_pass"]),
        },
        {
            "check_id": "shared_stream_identity",
            "passed": bool(summary["same_exhaust_stream_used_once"]),
        },
        {
            "check_id": "matched_coordinates",
            "passed": bool(summary["matched_active_case_id"] == active_case_id),
        },
        {
            "check_id": "nafion_correlation_validity_reported_fail_closed",
            "passed": bool(
                summary["nafion_correlation_validity_complete"] is False
            ),
        },
    ]
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "control_summary.json"
    segment_path = output_dir / "segment_register.csv"
    comparison_path = output_dir / "matched_comparison.json"
    markdown_path = output_dir / "SUMMARY.md"
    audit_path = output_dir / "audit.json"
    summary_path.write_text(
        json.dumps(_json_safe(summary), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    segments.to_csv(segment_path, index=False)
    comparison_path.write_text(
        json.dumps(_json_safe(comparison), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    write_summary_markdown(markdown_path, summary, comparison)
    materialized_outputs = (
        summary_path,
        segment_path,
        comparison_path,
        markdown_path,
    )
    audit = {
        "status": "PASS" if all(check["passed"] for check in checks) else "FAIL",
        "audit_scope": "mechanism-control-integrity-not-design-acceptance",
        "checks": checks,
        "sources": {
            "control_script": _file_record(CONTROL_SCRIPT),
            "active_erv_module": _file_record(ACTIVE_ERV_MODULE),
            "canonical_v2_model": _file_record(CANONICAL_V2_MODEL),
        },
        "inputs": {
            "config": _file_record(config_path),
            "v2_config": _file_record(v2_config_path),
            "active_case_register": _file_record(active_case_register),
        },
        "outputs_excluding_self_referential_audit": {
            path.name: _file_record(path) for path in materialized_outputs
        },
        "notes": [
            "audit.json is excluded from its own output-hash register to avoid a self-referential digest",
            "PASS covers mechanism-control integrity and reproducibility, not Nafion correlation validity or design acceptance",
        ],
    }
    audit_path.write_text(
        json.dumps(_json_safe(audit), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return audit


def main() -> int:
    args = parse_args()
    audit = run(
        config_path=args.config.resolve(),
        v2_config_path=args.v2_config.resolve(),
        active_case_register=args.active_case_register.resolve(),
        active_case_id=str(args.active_case_id),
        output_dir=args.output_dir.resolve(),
        overwrite=bool(args.overwrite),
    )
    print(f"{audit['status']}: exact zero-current Nafion control")
    return 0 if audit["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
