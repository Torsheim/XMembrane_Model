#!/usr/bin/env python3
"""
HeiQ WP1 direct liquid-contact receiver study v1
=================================================

Purpose
-------
Test the receiver concept that most directly matches the physical intuition:
water leaves the hydrated membrane into a liquid-contact/drainage layer from
the first axial position, rather than first entering a receiver gas stream and
waiting for that gas stream to become saturated.

The script reuses the reviewed V2/V3 local voltage-controlled membrane BVP and
the native process-air axial marching basis through the canonical ``heiq.wp1``
package. Only the receiver boundary is changed:

    process gas -> process gas film -> EO membrane -> liquid-contact sink

The receiver-side gas-film resistance is replaced numerically by a declared,
very large interface coefficient multiplier.  Every transferred kilogram of
water is counted as liquid product immediately.  There is no receiver gas flow
and no receiver-channel fan power in this boundary model.

This is an upper-bound boundary-condition study, not a final wet-electrode or
liquid-film model.  It does not resolve nucleation, capillary pressure, finite
liquid-film resistance, flooding, drainage geometry, wet-electrode kinetics,
liquid conductivity paths, electrolysis, corrosion, or conjugate heat transfer.

Main studies
------------
* O50 and O30 targets.
* Water drag t_w from 10 to 600.
* Liquid/sink activity from 0.70 to approximately 1.00.
  - a_l ~= 1 represents pure liquid water.
  - a_l < 1 represents an aqueous/desiccant sink sensitivity, not pure water.
* Terminal-voltage re-optimisation up to a declared diagnostic search cap.
* Separate 2, 5, 10 and 20 V design-cap summaries.
* M11675 property basis and, when available, the Terminal-1 material optimum.
* EO, signed diffusion, net flux, water-polarisation voltage, ohmic voltage,
  process gas-film polarisation, direct liquid production, process fan power,
  pump power, heat-rejection duty and system FOMs.
* Thermodynamic identity audit:

      j V_water ~= N_EO Delta mu_w
                ~= N_net Delta mu_w + (-N_diff) Delta mu_w.

Run from the HeiQ_V2 repository root.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, Iterable, Mapping, Sequence

os.environ.setdefault("MPLCONFIGDIR", "/tmp/heiq-direct-liquid-contact-v1-mpl")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from heiq.wp1.axial import (
    load_v2_module,
    solve_local_state,
)
from heiq.wp1.engineering import (
    channel_pressure_drop_and_fan,
    stack_topology,
)
from heiq.wp1.receiver import MATERIAL_COLUMNS
from heiq.wp1.studies.prearchitecture import (
    build_context as build_native_context,
)


ROOT = Path(__file__).resolve().parents[1]

FARADAY_C_MOL = 96485.33212
R_UNIVERSAL_J_MOL_K = 8.314462618
MOLAR_MASS_WATER_KG_MOL = 0.01801528
RHO_WATER_KG_M3 = 997.0
EPS = 1.0e-12

DEFAULT_DRAGS = [10.0, 20.0, 36.205058, 50.0, 75.0, 100.0, 150.0, 250.0, 400.0, 600.0]
DEFAULT_LIQUID_ACTIVITIES = [0.70, 0.80, 0.90, 0.95, 0.99, 0.999999]
DEFAULT_DESIGN_CAPS_V = [2.0, 5.0, 10.0, 20.0]
DEFAULT_HEAT_REJECTION_COPS = [3.0, 6.0]
DEFAULT_ANNUAL_HOURS = [2000.0, 4000.0, 6000.0, 8000.0, 8760.0]
PROFILE_POSITIONS = [0.0, 0.25, 0.50, 0.75, 1.0]

# Equal-service 150,000-cfm report anchors.  These are deliberately explicit so
# an unrelated scaled CSV cannot silently change the system basis.
AHU_ANCHORS = {
    "O80": {
        "process_electric_kw": 1166.4,
        "compressor_electric_kw": 1166.4,
        "cooling_removed_kw": 5260.0,
        "cop_cooling": 4.51,
    },
    "O50": {
        "process_electric_kw": 697.0807453,
        "compressor_electric_kw": 697.0807453,
        "cooling_removed_kw": 3366.4,
        "cop_cooling": 4.83,
    },
    "O30": {
        "process_electric_kw": 391.5503876,
        "compressor_electric_kw": 391.5503876,
        "cooling_removed_kw": 2019.8,
        "cop_cooling": 5.16,
    },
}

ABSOLUTE_VOLTAGES_V = [
    0.005, 0.010, 0.020, 0.030, 0.050, 0.075, 0.100, 0.150, 0.250,
    0.500, 0.750, 1.000, 1.500, 2.000, 3.000, 4.000, 5.000, 6.000,
    8.000, 10.000, 12.000, 16.000, 20.000, 24.000, 30.000,
]




def finite(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return math.nan
    return result if math.isfinite(result) else math.nan


def truth(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def first_finite(mapping: Mapping[str, Any], names: Sequence[str], default: float = math.nan) -> float:
    for name in names:
        if name in mapping:
            value = finite(mapping[name])
            if math.isfinite(value):
                return value
    return default


def unique_sorted(values: Iterable[float], lo: float = 0.0, hi: float = math.inf) -> list[float]:
    return sorted(
        {
            round(float(value), 10)
            for value in values
            if math.isfinite(float(value)) and lo <= float(value) <= hi
        }
    )


def safe_read_csv(path: Path) -> pd.DataFrame:
    if not path.is_file() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--mode", choices=["inspect", "smoke", "study", "postprocess"], default="study")
    parser.add_argument("--output-dir", default="outputs/direct_liquid_contact_receiver_v1")
    parser.add_argument("--targets", nargs="+", default=["O30", "O50"])
    parser.add_argument("--water-drags", nargs="+", type=float, default=DEFAULT_DRAGS)
    parser.add_argument(
        "--liquid-activities",
        nargs="+",
        type=float,
        default=DEFAULT_LIQUID_ACTIVITIES,
        help=(
            "Receiver liquid/sink activities. Values below one are solution/desiccant "
            "sensitivities; pure liquid water is represented by 0.999999."
        ),
    )
    parser.add_argument(
        "--material-basis",
        choices=["m11675", "terminal1_optimum", "both"],
        default="both",
    )
    parser.add_argument(
        "--terminal1-optimum-csv",
        type=Path,
        default=Path("outputs/prearchitecture_continuation_v2/material_global/overall_best.csv"),
    )
    parser.add_argument("--receiver-temperature-c", type=float, default=32.0)
    parser.add_argument("--area-max-m2", type=float, default=9000.0)
    parser.add_argument("--voltage-search-max-v", type=float, default=24.0)
    parser.add_argument("--design-voltage-caps-v", nargs="+", type=float, default=DEFAULT_DESIGN_CAPS_V)
    parser.add_argument("--current-cap-a-m2", type=float, default=2000.0)
    parser.add_argument("--liquid-interface-factor", type=float, default=1.0e6)
    parser.add_argument(
        "--process-film-factors",
        nargs="+",
        type=float,
        default=[1.0],
        help="Optional process gas-film sensitivity. Main physical case is 1.0.",
    )
    parser.add_argument("--pump-pressure-rise-pa", type=float, default=100000.0)
    parser.add_argument("--pump-efficiency", type=float, default=0.60)
    parser.add_argument("--heat-rejection-cops", nargs="+", type=float, default=DEFAULT_HEAT_REJECTION_COPS)
    parser.add_argument("--annual-hours", nargs="+", type=float, default=DEFAULT_ANNUAL_HOURS)
    parser.add_argument("--electricity-price-chf-kwh", type=float, default=0.25)
    parser.add_argument("--profile-top-n", type=int, default=3)
    parser.add_argument("--fixed-site-concentration-mol-m3", type=float, default=None)
    parser.add_argument(
        "--gas-only-results-csv",
        type=Path,
        default=Path("outputs/saturated_receiver_liquid_drain_v1/best_physics_by_target_drag_and_ledger.csv"),
    )
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if args.area_max_m2 <= 0.0:
        raise SystemExit("--area-max-m2 must be positive")
    if args.voltage_search_max_v <= 0.0:
        raise SystemExit("--voltage-search-max-v must be positive")
    if args.current_cap_a_m2 <= 0.0:
        raise SystemExit("--current-cap-a-m2 must be positive")
    if args.liquid_interface_factor <= 0.0:
        raise SystemExit("--liquid-interface-factor must be positive")
    if not 0.0 < args.pump_efficiency <= 1.0:
        raise SystemExit("--pump-efficiency must lie in (0,1]")
    if args.pump_pressure_rise_pa < 0.0:
        raise SystemExit("--pump-pressure-rise-pa cannot be negative")
    if not args.water_drags or any(value <= 0.0 for value in args.water_drags):
        raise SystemExit("All water-drag values must be positive")
    if not args.liquid_activities or any(not 0.0 < value < 1.0 for value in args.liquid_activities):
        raise SystemExit("All liquid activities must lie strictly in (0,1)")
    if not args.process_film_factors or any(value <= 0.0 for value in args.process_film_factors):
        raise SystemExit("All process-film factors must be positive")
    if not args.design_voltage_caps_v or any(value <= 0.0 for value in args.design_voltage_caps_v):
        raise SystemExit("All design voltage caps must be positive")


def setup_context(
    args: argparse.Namespace,
) -> tuple[None, dict[str, Any]]:
    cfg12 = json.loads(
        (
            ROOT
            / "config"
            / "closed_receiver_system_v12_config.json"
        ).read_text()
    )

    base = json.loads(
        (
            ROOT
            / "data"
            / "reference"
            / "v11_compat"
            / "axial_base_config_used.json"
        ).read_text()
    )

    candidates = pd.read_csv(
        ROOT
        / "data"
        / "reference"
        / "v11_compat"
        / "candidate_materials.csv"
    )

    v2_root = (
        ROOT
        / "heiq_pre_receiver_material_analyses"
    )

    v2 = load_v2_module(
        v2_root
    )

    v2_config = v2.load_config(
        v2_root
        / "config"
        / "default.json"
    )

    setup_args = SimpleNamespace(
        receiver_band="bridge_40_to_60",
        receiver_temperature_c=float(
            args.receiver_temperature_c
        ),
        area_max_m2=float(
            args.area_max_m2
        ),
        voltage_max_v=float(
            args.voltage_search_max_v
        ),
        lhs_samples=8,
        seed=20260812,
        smoke=False,
    )

    context = build_native_context(
        setup_args,
        cfg12=cfg12,
        base_config=base,
        candidates=candidates,
        v2=v2,
        v2_config=v2_config,
    )

    context["base"]["channel"][
        "receiver_temperature_c"
    ] = float(
        args.receiver_temperature_c
    )

    context["base"]["integration"][
        "area_limit_m2"
    ] = float(
        args.area_max_m2
    )

    return None, context



def row_to_material(
    context: Mapping[str, Any],
    row: Mapping[str, Any],
    basis_id: str,
    drag: float,
) -> dict[str, Any]:
    base = context["m11675"]
    props: dict[str, float] = {}

    for name in MATERIAL_COLUMNS:
        if name == "water_drag":
            props[name] = float(drag)
            continue

        value = finite(
            row.get(
                name,
                math.nan,
            )
        )

        props[name] = (
            value
            if math.isfinite(value)
            else float(base[name])
        )

    return {
        "name": (
            f"{basis_id}_"
            f"tw{props['water_drag']:.8g}_"
            f"D{props['water_diffusivity_m2_s']:.3e}_"
            f"sig{props['conductivity_s_m']:.8g}_"
            f"L{props['dry_thickness_um']:.8g}"
        ),
        "model": "powerlaw",
        **props,
        "interpretation": (
            f"{basis_id} property basis with swept "
            "water drag; hypothetical inverse-design "
            "coordinate, not measured material validation"
        ),
    }



def material_bases(context: Mapping[str, Any], args: argparse.Namespace) -> dict[str, Mapping[str, Any]]:
    bases: dict[str, Mapping[str, Any]] = {}
    if args.material_basis in {"m11675", "both"}:
        bases["M11675"] = context["m11675"].to_dict() if hasattr(context["m11675"], "to_dict") else dict(context["m11675"])

    if args.material_basis in {"terminal1_optimum", "both"}:
        path = args.terminal1_optimum_csv
        if not path.is_absolute():
            path = ROOT / path
        frame = safe_read_csv(path)
        if not frame.empty:
            bases["Terminal1_optimum"] = frame.iloc[0].to_dict()
        elif args.material_basis == "terminal1_optimum":
            raise FileNotFoundError(f"Terminal-1 optimum is missing or empty: {path}")
    return bases




def local_gate(local: Mapping[str, Any], current_cap_a_m2: float) -> str:
    if not bool(local.get("solution_ok", False)):
        return str(local.get("solution_status", "unknown_local_failure"))
    flux = finite(local.get("net_flux_mol_m2_s"))
    current = finite(local.get("current_density_a_m2"))
    if not math.isfinite(flux) or flux <= 0.0:
        return "nonpositive_net_water_flux"
    if not math.isfinite(current) or current <= 0.0:
        return "nonpositive_current_density"
    if current > current_cap_a_m2:
        return "operating_current_density_limit"
    source_surface = first_finite(local, ["source_surface_activity", "source_membrane_surface_activity"])
    receiver_surface = first_finite(local, ["receiver_surface_activity", "receiver_membrane_surface_activity"])
    if not (0.0 < source_surface <= 1.0 and 0.0 < receiver_surface <= 1.0):
        return "surface_activity_out_of_bounds"
    return "local_gates_pass"


def local_flux_components(local: Mapping[str, Any], water_drag: float) -> tuple[float, float, float]:
    net = finite(local.get("net_flux_mol_m2_s"))
    current = finite(local.get("current_density_a_m2"))
    eo = first_finite(local, ["eo_flux_mol_m2_s"], water_drag * current / FARADAY_C_MOL)
    diffusion = first_finite(local, ["diffusion_flux_mol_m2_s"], net - eo)
    return eo, diffusion, net


def mean_value(start: Mapping[str, Any], end: Mapping[str, Any], names: Sequence[str], default: float = math.nan) -> float:
    a = first_finite(start, names, default)
    b = first_finite(end, names, default)
    if math.isfinite(a) and math.isfinite(b):
        return 0.5 * (a + b)
    return math.nan


def latent_heat_vaporisation_kj_kg(temperature_c: float) -> float:
    return max(2200.0, 2500.9 - 2.36 * float(temperature_c))


def liquid_pump_power_kw(liquid_kg_h: float, pressure_rise_pa: float, efficiency: float) -> float:
    if liquid_kg_h <= 0.0:
        return 0.0
    return (
        liquid_kg_h / 3600.0
        * pressure_rise_pa
        / RHO_WATER_KG_M3
        / efficiency
        / 1000.0
    )


def process_geometry_and_fan(
    context: Mapping[str, Any],
    active_area_m2: float,
) -> dict[str, float]:
    base = context["base"]
    process = context["process_basis"]
    channel = base["channel"]

    velocity = float(
        channel["process_velocity_m_s"]
    )

    gap = float(
        channel["process_gap_m"]
    )

    active_sides = float(
        channel[
            "active_sides_per_process_channel"
        ]
    )

    open_area = (
        float(process.volume_flow_m3_s)
        / velocity
    )

    total_width = (
        open_area
        / (gap * active_sides)
    )

    hydro = channel_pressure_drop_and_fan(
        axial=None,
        active_area_m2=float(
            active_area_m2
        ),
        total_channel_width_m=total_width,
        active_sides=active_sides,
        gap_m=gap,
        velocity_m_s=velocity,
        volume_flow_m3_s=float(
            process.volume_flow_m3_s
        ),
        temperature_c=float(
            process.inlet_temperature_c
        ),
        pressure_pa=float(
            process.absolute_pressure_pa
        ),
        humidity_ratio_kg_kg_da=float(
            process
            .inlet_humidity_ratio_kg_kg_da
        ),
        fan_efficiency=float(
            channel[
                "process_fan_efficiency"
            ]
        ),
    )

    return {
        "process_gap_m":
            gap,

        "process_velocity_m_s":
            velocity,

        "process_active_sides":
            active_sides,

        "process_open_flow_area_m2":
            open_area,

        "process_total_channel_width_m":
            total_width,

        "process_channel_length_m":
            hydro["channel_length_m"],

        "process_channel_reynolds_number":
            hydro[
                "channel_reynolds_number"
            ],

        "process_pressure_drop_pa":
            hydro[
                "channel_pressure_drop_pa"
            ],

        "process_channel_fan_power_kw":
            hydro[
                "channel_fan_power_kw"
            ],
    }



def integrate_direct_liquid_case(
    context: Mapping[str, Any],
    *,
    target: str,
    material: Mapping[str, Any],
    material_basis_id: str,
    liquid_activity: float,
    terminal_voltage_v: float,
    process_film_factor: float,
    args: argparse.Namespace,
    record_profile: bool,
) -> tuple[dict[str, Any], pd.DataFrame]:
    v2 = context["v2"]
    v2_config = context["v2_config"]
    base = context["base"]
    cfg12 = context["cfg12"]
    process = context["process_basis"]
    target_row = context["targets"][target]

    integration = base["integration"]
    area_limit = float(args.area_max_m2)
    nominal_step = float(integration["area_step_m2"])
    minimum_step = float(integration["minimum_area_step_m2"])
    humidity_tolerance = float(integration["humidity_ratio_absolute_tolerance"])
    balance_tolerance = float(integration.get("mass_balance_relative_tolerance", 1.0e-8))

    process_temperature_c = float(process.inlet_temperature_c)
    process_mass_flow = float(process.dry_air_mass_flow_kg_s)
    process_inlet_w = float(process.inlet_humidity_ratio_kg_kg_da)
    target_w = float(target_row["target_humidity_ratio_kg_kg_da"])
    process_w = process_inlet_w

    local_config = copy.deepcopy(base)
    local_config["channel"] = copy.deepcopy(base["channel"])
    # The local solver still asks for a receiver-channel film state.  Its
    # resistance is made negligible by receiver_factor; its fan is never used.
    legacy_asr = float(cfg12["operating"]["legacy_series_asr_ohm_m2"])
    pe_efficiency = float(cfg12["operating"]["power_electronics_efficiency"])
    base_film_scale = float(cfg12["operating"]["film_scale_factor"])

    cumulative_area = 0.0
    integrated_transfer_mol_s = 0.0
    integrated_current_a = 0.0
    cell_power_w = 0.0
    membrane_power_w = 0.0
    series_power_w = 0.0
    water_polarisation_power_w = 0.0
    net_chemical_work_w = 0.0
    eo_chemical_work_w = 0.0
    diffusive_dissipation_w = 0.0
    maximum_current = -math.inf
    minimum_net_flux = math.inf
    maximum_terminal_error = 0.0
    minimum_process_surface_activity = math.inf
    maximum_receiver_surface_activity = -math.inf
    minimum_surface_margin = math.inf
    integrated_eo_flux_area_mol_s = 0.0
    integrated_diffusion_flux_area_mol_s = 0.0
    apparent_drag_area_integral = 0.0
    apparent_drag_area_weight = 0.0
    profile_rows: list[dict[str, Any]] = []
    status = "area_limit_before_target"
    last_local: Mapping[str, Any] | None = None
    shortened_endpoint_resolved = False

    def solve_at(water_ratio: float) -> dict[str, Any]:
        return solve_local_state(v2=v2, v2_config=v2_config, material=dict(material), source_temperature_c=process_temperature_c, source_humidity_ratio=float(water_ratio), receiver_activity=float(liquid_activity), terminal_voltage_v=float(terminal_voltage_v), fixed_loss_voltage_v=0.0, series_asr_ohm_m2=legacy_asr, film_scale_factor=base_film_scale, config=local_config, process_film_scale_factor=base_film_scale * float(process_film_factor), receiver_film_scale_factor=base_film_scale * float(args.liquid_interface_factor))

    def accumulate_segment(
        local_start: Mapping[str, Any],
        local_end: Mapping[str, Any],
        effective_step: float,
        next_process_w: float,
        transferred_kg_s: float,
        event: str,
    ) -> None:
        nonlocal cumulative_area
        nonlocal integrated_transfer_mol_s, integrated_current_a
        nonlocal cell_power_w, membrane_power_w, series_power_w
        nonlocal water_polarisation_power_w, net_chemical_work_w
        nonlocal eo_chemical_work_w, diffusive_dissipation_w
        nonlocal maximum_current, minimum_net_flux, maximum_terminal_error
        nonlocal minimum_process_surface_activity, maximum_receiver_surface_activity
        nonlocal minimum_surface_margin, integrated_eo_flux_area_mol_s
        nonlocal integrated_diffusion_flux_area_mol_s
        nonlocal apparent_drag_area_integral, apparent_drag_area_weight

        current = mean_value(local_start, local_end, ["current_density_a_m2"])
        net_flux = mean_value(local_start, local_end, ["net_flux_mol_m2_s"])
        eo_start, diff_start, _ = local_flux_components(local_start, float(material["water_drag"]))
        eo_end, diff_end, _ = local_flux_components(local_end, float(material["water_drag"]))
        eo_flux = 0.5 * (eo_start + eo_end)
        diffusion_flux = 0.5 * (diff_start + diff_end)
        membrane_power_density = mean_value(local_start, local_end, ["membrane_power_density_w_m2"])
        start_current = finite(local_start.get("current_density_a_m2"))
        end_current = finite(local_end.get("current_density_a_m2"))
        series_power_density = 0.5 * (start_current**2 + end_current**2) * legacy_asr
        water_voltage = mean_value(local_start, local_end, ["water_polarisation_voltage_v"])
        ohmic_voltage = mean_value(local_start, local_end, ["ohmic_voltage_v"])
        series_voltage = mean_value(local_start, local_end, ["series_loss_voltage_v"])
        process_surface = mean_value(
            local_start,
            local_end,
            ["source_surface_activity", "source_membrane_surface_activity"],
        )
        receiver_surface = mean_value(
            local_start,
            local_end,
            ["receiver_surface_activity", "receiver_membrane_surface_activity"],
        )
        delta_mu = R_UNIVERSAL_J_MOL_K * (process_temperature_c + 273.15) * math.log(
            max(receiver_surface, EPS) / max(process_surface, EPS)
        )

        integrated_transfer_mol_s += transferred_kg_s / MOLAR_MASS_WATER_KG_MOL
        integrated_current_a += current * effective_step
        cell_power_w += terminal_voltage_v * current * effective_step
        membrane_power_w += membrane_power_density * effective_step
        series_power_w += series_power_density * effective_step
        water_polarisation_power_w += current * water_voltage * effective_step
        net_chemical_work_w += net_flux * delta_mu * effective_step
        eo_chemical_work_w += eo_flux * delta_mu * effective_step
        diffusive_dissipation_w += (-diffusion_flux) * delta_mu * effective_step
        integrated_eo_flux_area_mol_s += eo_flux * effective_step
        integrated_diffusion_flux_area_mol_s += diffusion_flux * effective_step
        if current > 0.0:
            apparent_drag = FARADAY_C_MOL * net_flux / current
            apparent_drag_area_integral += apparent_drag * effective_step
            apparent_drag_area_weight += effective_step

        maximum_current = max(maximum_current, start_current, end_current)
        minimum_net_flux = min(
            minimum_net_flux,
            finite(local_start.get("net_flux_mol_m2_s")),
            finite(local_end.get("net_flux_mol_m2_s")),
        )
        maximum_terminal_error = max(
            maximum_terminal_error,
            abs(finite(local_start.get("terminal_voltage_error_v"))),
            abs(finite(local_end.get("terminal_voltage_error_v"))),
        )
        minimum_process_surface_activity = min(minimum_process_surface_activity, process_surface)
        maximum_receiver_surface_activity = max(maximum_receiver_surface_activity, receiver_surface)
        minimum_surface_margin = min(minimum_surface_margin, process_surface - receiver_surface)
        cumulative_area += effective_step

        if record_profile:
            profile_rows.append(
                {
                    "target": target,
                    "material_basis_id": material_basis_id,
                    "material_id": str(material["name"]),
                    "water_drag": float(material["water_drag"]),
                    "liquid_activity": float(liquid_activity),
                    "liquid_interface_factor": float(args.liquid_interface_factor),
                    "process_film_factor": float(process_film_factor),
                    "terminal_voltage_v": float(terminal_voltage_v),
                    "cumulative_area_m2": cumulative_area,
                    "step_area_m2": effective_step,
                    "process_humidity_ratio_kg_kg_da": next_process_w,
                    "process_activity": float(
                        axial.activity_from_t_w(
                            process_temperature_c,
                            next_process_w,
                            process.absolute_pressure_pa,
                        )
                    ),
                    "process_surface_activity": process_surface,
                    "receiver_surface_activity": receiver_surface,
                    "surface_activity_margin": process_surface - receiver_surface,
                    "current_density_a_m2": current,
                    "eo_flux_mol_m2_s": eo_flux,
                    "diffusion_flux_mol_m2_s": diffusion_flux,
                    "net_flux_mol_m2_s": net_flux,
                    "eo_flux_kg_m2_h": eo_flux * MOLAR_MASS_WATER_KG_MOL * 3600.0,
                    "diffusion_flux_kg_m2_h": diffusion_flux * MOLAR_MASS_WATER_KG_MOL * 3600.0,
                    "net_flux_kg_m2_h": net_flux * MOLAR_MASS_WATER_KG_MOL * 3600.0,
                    "ohmic_voltage_v": ohmic_voltage,
                    "water_polarisation_voltage_v": water_voltage,
                    "series_loss_voltage_v": series_voltage,
                    "delta_mu_water_j_mol": delta_mu,
                    "water_polarisation_power_density_w_m2": current * water_voltage,
                    "net_chemical_work_density_w_m2": net_flux * delta_mu,
                    "eo_chemical_work_density_w_m2": eo_flux * delta_mu,
                    "diffusive_dissipation_density_w_m2": (-diffusion_flux) * delta_mu,
                    "apparent_drag_t_w": FARADAY_C_MOL * net_flux / current if current > 0.0 else math.nan,
                    "cumulative_liquid_product_kg_h": integrated_transfer_mol_s * MOLAR_MASS_WATER_KG_MOL * 3600.0,
                    "event": event,
                }
            )

    while cumulative_area < area_limit - 1.0e-12:
        if process_w <= target_w + humidity_tolerance:
            status = "target_reached"
            break

        step = min(nominal_step, area_limit - cumulative_area)
        local_start = solve_at(process_w)
        start_gate = local_gate(local_start, float(args.current_cap_a_m2))
        if start_gate != "local_gates_pass":
            status = start_gate
            last_local = local_start
            break
        start_flux = float(local_start["net_flux_mol_m2_s"])

        while True:
            predicted_w = process_w - (
                start_flux * MOLAR_MASS_WATER_KG_MOL * step / process_mass_flow
            )
            if predicted_w <= 0.0:
                local_end = {"solution_ok": False, "solution_status": "predictor_negative_humidity_ratio"}
                end_gate = "predictor_negative_humidity_ratio"
            else:
                local_end = solve_at(predicted_w)
                end_gate = local_gate(local_end, float(args.current_cap_a_m2))
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
        if not math.isfinite(full_transfer_kg_s) or full_transfer_kg_s <= 0.0:
            status = "nonpositive_corrected_water_transfer"
            last_local = local_end
            break

        process_needed_kg_s = process_mass_flow * max(process_w - target_w, 0.0)
        if full_transfer_kg_s >= process_needed_kg_s - 1.0e-15:
            next_process_w = target_w
            event_end = solve_at(next_process_w)
            event_gate = local_gate(event_end, float(args.current_cap_a_m2))
            if event_gate != "local_gates_pass":
                status = f"shortened_endpoint_failure:{event_gate}"
                last_local = event_end
                break
            event_flux = float(event_end["net_flux_mol_m2_s"])
            event_mean_flux = 0.5 * (start_flux + event_flux)
            effective_step = process_needed_kg_s / (
                event_mean_flux * MOLAR_MASS_WATER_KG_MOL
            )
            if (
                not math.isfinite(effective_step)
                or effective_step <= 0.0
                or effective_step > step * (1.0 + 1.0e-6)
            ):
                status = "shortened_endpoint_area_inconsistent"
                last_local = event_end
                break
            accumulate_segment(
                local_start,
                event_end,
                effective_step,
                next_process_w,
                process_needed_kg_s,
                "target_reached",
            )
            process_w = next_process_w
            last_local = event_end
            shortened_endpoint_resolved = True
            status = "target_reached"
            break

        next_process_w = process_w - full_transfer_kg_s / process_mass_flow
        accumulate_segment(
            local_start,
            local_end,
            step,
            next_process_w,
            full_transfer_kg_s,
            "continue",
        )
        process_w = next_process_w
        last_local = local_end

    integrated_water_kg_h = integrated_transfer_mol_s * MOLAR_MASS_WATER_KG_MOL * 3600.0
    process_balance_kg_h = process_mass_flow * (process_inlet_w - process_w) * 3600.0
    mass_balance_error = (
        (integrated_water_kg_h - process_balance_kg_h)
        / max(abs(integrated_water_kg_h), abs(process_balance_kg_h), EPS)
    )
    water_balance_pass = abs(mass_balance_error) <= balance_tolerance
    if status == "target_reached" and not water_balance_pass:
        status = "water_balance_failure"

    geometry = process_geometry_and_fan(context, cumulative_area) if cumulative_area > 0.0 else {}
    grid_power_kw = cell_power_w / pe_efficiency / 1000.0
    pump_power_kw = liquid_pump_power_kw(
        integrated_water_kg_h,
        float(args.pump_pressure_rise_pa),
        float(args.pump_efficiency),
    )
    process_fan_kw = finite(geometry.get("process_channel_fan_power_kw"))
    if not math.isfinite(process_fan_kw):
        process_fan_kw = 0.0
    core_power_kw = grid_power_kw + process_fan_kw + pump_power_kw
    latent_heat_kw = (
        integrated_water_kg_h / 3600.0
        * latent_heat_vaporisation_kj_kg(float(args.receiver_temperature_c))
    )
    stack = (
        stack_topology(
            required_area_m2=cumulative_area,
            integrated_current_a=integrated_current_a,
            maximum_current_density_a_m2=(maximum_current if maximum_current > -math.inf else math.nan),
            cell_terminal_voltage_v=float(terminal_voltage_v),
            stack_config=context["cfg12"]["stack"],
        )
        if cumulative_area > 0.0 and integrated_current_a > 0.0
        else {"stack_feasible": False, "stack_infeasibility_reason": "case did not integrate positive area/current"}
    )

    summary = {
        "target": target,
        "material_basis_id": material_basis_id,
        "material_id": str(material["name"]),
        **{name: float(material[name]) for name in MATERIAL_COLUMNS},
        "receiver_boundary_model": "direct_liquid_contact_from_first_area_step",
        "receiver_gas_flow_present": False,
        "receiver_channel_fan_power_kw": 0.0,
        "liquid_activity": float(liquid_activity),
        "liquid_sink_kind": (
            "pure_liquid_water_proxy" if liquid_activity >= 0.999 else "subunity_activity_solution_or_desiccant_proxy"
        ),
        "liquid_interface_factor": float(args.liquid_interface_factor),
        "process_film_factor": float(process_film_factor),
        "terminal_voltage_v": float(terminal_voltage_v),
        "voltage_search_cap_v": float(args.voltage_search_max_v),
        "status": status,
        "target_reached": status == "target_reached",
        "required_active_area_m2": cumulative_area,
        "process_inlet_humidity_ratio_kg_kg_da": process_inlet_w,
        "process_outlet_humidity_ratio_kg_kg_da": process_w,
        "target_humidity_ratio_kg_kg_da": target_w,
        "integrated_water_transfer_kg_h": integrated_water_kg_h,
        "liquid_product_water_kg_h": integrated_water_kg_h,
        "liquid_product_l_day": integrated_water_kg_h * 24.0 / RHO_WATER_KG_M3 * 1000.0,
        "process_mass_balance_water_removal_kg_h": process_balance_kg_h,
        "water_mass_balance_relative_error": mass_balance_error,
        "water_balance_pass": water_balance_pass,
        "maximum_local_current_density_a_m2": maximum_current if maximum_current > -math.inf else math.nan,
        "minimum_local_flux_mol_m2_s": minimum_net_flux if minimum_net_flux < math.inf else math.nan,
        "integrated_current_a": integrated_current_a,
        "cell_power_kw": cell_power_w / 1000.0,
        "membrane_power_kw": membrane_power_w / 1000.0,
        "series_loss_power_kw": series_power_w / 1000.0,
        "power_electronics_loss_kw": grid_power_kw - cell_power_w / 1000.0,
        "eo_grid_power_kw": grid_power_kw,
        "process_channel_fan_power_kw": process_fan_kw,
        "condensate_pump_power_kw": pump_power_kw,
        "predryer_core_power_kw": core_power_kw,
        "predryer_core_sec_kwh_kg": core_power_kw / integrated_water_kg_h if integrated_water_kg_h > 0.0 else math.nan,
        "water_removed_per_core_kwh_kg_kwh": integrated_water_kg_h / core_power_kw if core_power_kw > 0.0 else math.nan,
        "condensation_or_phase_change_heat_proxy_kw": latent_heat_kw,
        "water_polarisation_electric_power_kw": water_polarisation_power_w / 1000.0,
        "net_chemical_work_kw": net_chemical_work_w / 1000.0,
        "eo_chemical_work_kw": eo_chemical_work_w / 1000.0,
        "diffusive_dissipation_kw": diffusive_dissipation_w / 1000.0,
        "thermodynamic_identity_residual_kw": (
            water_polarisation_power_w - net_chemical_work_w - diffusive_dissipation_w
        ) / 1000.0,
        "eo_identity_residual_kw": (water_polarisation_power_w - eo_chemical_work_w) / 1000.0,
        "thermodynamic_identity_relative_error": (
            (water_polarisation_power_w - net_chemical_work_w - diffusive_dissipation_w)
            / max(abs(water_polarisation_power_w), abs(net_chemical_work_w + diffusive_dissipation_w), EPS)
        ),
        "integrated_eo_flux_area_mol_s": integrated_eo_flux_area_mol_s,
        "integrated_diffusion_flux_area_mol_s": integrated_diffusion_flux_area_mol_s,
        "backdiffusion_fraction_of_eo": (
            max(-integrated_diffusion_flux_area_mol_s, 0.0) / max(integrated_eo_flux_area_mol_s, EPS)
        ),
        "mean_apparent_drag_t_w": (
            apparent_drag_area_integral / apparent_drag_area_weight
            if apparent_drag_area_weight > 0.0 else math.nan
        ),
        "minimum_process_surface_activity": (
            minimum_process_surface_activity if minimum_process_surface_activity < math.inf else math.nan
        ),
        "maximum_receiver_surface_activity": (
            maximum_receiver_surface_activity if maximum_receiver_surface_activity > -math.inf else math.nan
        ),
        "minimum_surface_activity_margin": (
            minimum_surface_margin if minimum_surface_margin < math.inf else math.nan
        ),
        "maximum_terminal_voltage_error_v": maximum_terminal_error,
        "shortened_endpoint_resolved": shortened_endpoint_resolved,
        "local_solver_evaluated": last_local is not None,
        **geometry,
        **stack,
    }
    profile = pd.DataFrame(profile_rows)
    return summary, profile


def case_pass(row: Mapping[str, Any], args: argparse.Namespace) -> bool:
    return bool(
        truth(row.get("target_reached"))
        and truth(row.get("water_balance_pass"))
        and finite(row.get("required_active_area_m2")) <= float(args.area_max_m2) + 1.0e-9
        and 0.0 < finite(row.get("maximum_local_current_density_a_m2")) <= float(args.current_cap_a_m2) + 1.0e-9
        and finite(row.get("minimum_local_flux_mol_m2_s")) > 0.0
        and finite(row.get("maximum_receiver_surface_activity")) <= 1.0 + 1.0e-9
        and math.isfinite(finite(row.get("predryer_core_power_kw")))
    )


def voltage_grid(
    *,
    target: str,
    water_drag: float,
    liquid_activity: float,
    temperature_c: float,
    search_max_v: float,
    smoke: bool,
) -> list[float]:
    target_activity = 0.30 if target == "O30" else 0.50
    thermal_voltage = R_UNIVERSAL_J_MOL_K * (temperature_c + 273.15) / FARADAY_C_MOL
    reversible = water_drag * thermal_voltage * max(
        math.log(liquid_activity / max(target_activity, 1.0e-4)),
        0.0,
    )
    center = max(0.005, 1.05 * reversible)
    if smoke:
        factors = [0.75, 1.0, 1.25]
        absolute = [0.1, 0.5, 1.0, 2.0, min(8.0, search_max_v), search_max_v]
    else:
        factors = [0.50, 0.65, 0.75, 0.85, 0.92, 0.97, 1.0, 1.03, 1.08, 1.15, 1.30, 1.50]
        absolute = ABSOLUTE_VOLTAGES_V
    values = [center * factor for factor in factors] + absolute + [center]
    return unique_sorted(values, lo=1.0e-5, hi=search_max_v)


def refine_voltage_grid(best_voltage_v: float, search_max_v: float) -> list[float]:
    low = max(1.0e-5, 0.82 * best_voltage_v)
    high = min(search_max_v, 1.18 * best_voltage_v)
    return unique_sorted(list(np.linspace(low, high, 19)) + [best_voltage_v], lo=1.0e-5, hi=search_max_v)


def run_grid(
    continuation: ModuleType,
    context: Mapping[str, Any],
    args: argparse.Namespace,
    out: Path,
) -> pd.DataFrame:
    checkpoint_dir = out / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    bases = material_bases(context, args)
    if not bases:
        raise RuntimeError("No material basis could be resolved")

    targets = list(args.targets)
    drags = list(args.water_drags)
    activities = list(args.liquid_activities)
    process_factors = list(args.process_film_factors)
    if args.mode == "smoke":
        targets = ["O30"]
        drags = [50.0, 150.0, 600.0]
        activities = [0.90, 0.999999]
        process_factors = [1.0]
        bases = {"M11675": bases["M11675"]} if "M11675" in bases else dict(list(bases.items())[:1])

    all_rows: list[dict[str, Any]] = []
    total_groups = len(targets) * len(bases) * len(drags) * len(activities) * len(process_factors)
    group_index = 0

    for target in targets:
        if target not in context["targets"]:
            raise KeyError(f"Unknown target {target}")
        for basis_id, basis_row in bases.items():
            for drag in drags:
                material = row_to_material(context, basis_row, basis_id, float(drag))
                for liquid_activity in activities:
                    for process_factor in process_factors:
                        group_index += 1
                        checkpoint_name = (
                            f"{target}__{basis_id}__tw{drag:.8g}__al{liquid_activity:.8g}__kp{process_factor:.8g}.csv.gz"
                            .replace("+", "")
                        )
                        checkpoint_path = checkpoint_dir / checkpoint_name
                        if checkpoint_path.is_file():
                            cached = safe_read_csv(checkpoint_path)
                            if not cached.empty:
                                all_rows.extend(cached.to_dict(orient="records"))
                                print(
                                    f"Direct-liquid group {group_index}/{total_groups}: reused {checkpoint_name}",
                                    flush=True,
                                )
                                continue

                        rows: list[dict[str, Any]] = []
                        coarse = voltage_grid(
                            target=target,
                            water_drag=float(drag),
                            liquid_activity=float(liquid_activity),
                            temperature_c=float(args.receiver_temperature_c),
                            search_max_v=float(args.voltage_search_max_v),
                            smoke=args.mode == "smoke",
                        )
                        for voltage in coarse:
                            summary, _ = integrate_direct_liquid_case(
                                context,
                                target=target,
                                material=material,
                                material_basis_id=basis_id,
                                liquid_activity=float(liquid_activity),
                                terminal_voltage_v=float(voltage),
                                process_film_factor=float(process_factor),
                                args=args,
                                record_profile=False,
                            )
                            summary["grid_stage"] = "coarse"
                            summary["analysis_pass"] = case_pass(summary, args)
                            rows.append(summary)

                        frame = pd.DataFrame(rows)
                        passing = frame[frame["analysis_pass"].map(truth)].copy()
                        if args.mode != "smoke" and not passing.empty:
                            best_coarse = passing.sort_values(
                                ["predryer_core_power_kw", "required_active_area_m2", "terminal_voltage_v"],
                                kind="mergesort",
                            ).iloc[0]
                            for voltage in refine_voltage_grid(
                                float(best_coarse["terminal_voltage_v"]),
                                float(args.voltage_search_max_v),
                            ):
                                if np.isclose(frame["terminal_voltage_v"], voltage).any():
                                    continue
                                summary, _ = integrate_direct_liquid_case(
                                    context,
                                    target=target,
                                    material=material,
                                    material_basis_id=basis_id,
                                    liquid_activity=float(liquid_activity),
                                    terminal_voltage_v=float(voltage),
                                    process_film_factor=float(process_factor),
                                    args=args,
                                    record_profile=False,
                                )
                                summary["grid_stage"] = "refined"
                                summary["analysis_pass"] = case_pass(summary, args)
                                rows.append(summary)

                        checkpoint = pd.DataFrame(rows)
                        checkpoint.to_csv(checkpoint_path, index=False, compression="gzip")
                        all_rows.extend(rows)
                        print(
                            f"Direct-liquid group {group_index}/{total_groups}: "
                            f"target={target}, basis={basis_id}, tw={drag:g}, a_l={liquid_activity:g}, Kp={process_factor:g}",
                            flush=True,
                        )

    result = pd.DataFrame(all_rows)
    if result.empty:
        return result
    result = (
        result.sort_values(
            [
                "target", "material_basis_id", "water_drag", "liquid_activity",
                "process_film_factor", "terminal_voltage_v", "grid_stage",
            ],
            kind="mergesort",
        )
        .drop_duplicates(
            [
                "target", "material_basis_id", "water_drag", "liquid_activity",
                "process_film_factor", "terminal_voltage_v",
            ],
            keep="last",
        )
        .reset_index(drop=True)
    )
    result.to_csv(out / "all_direct_liquid_cases.csv.gz", index=False, compression="gzip")
    return result


def select_best(cases: pd.DataFrame, args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame]:
    if cases.empty:
        return pd.DataFrame(), pd.DataFrame()
    passing = cases[cases["analysis_pass"].map(truth)].copy()
    if passing.empty:
        return pd.DataFrame(), pd.DataFrame()

    group_cols = [
        "target", "material_basis_id", "water_drag", "liquid_activity", "process_film_factor"
    ]
    best_physics = (
        passing.sort_values(
            [*group_cols, "predryer_core_power_kw", "required_active_area_m2", "terminal_voltage_v"],
            kind="mergesort",
        )
        .drop_duplicates(group_cols, keep="first")
        .reset_index(drop=True)
    )

    cap_rows: list[pd.DataFrame] = []
    for cap in sorted(set(float(value) for value in args.design_voltage_caps_v)):
        subset = passing[passing["terminal_voltage_v"] <= cap + 1.0e-12].copy()
        if subset.empty:
            continue
        selected = (
            subset.sort_values(
                [*group_cols, "predryer_core_power_kw", "required_active_area_m2", "terminal_voltage_v"],
                kind="mergesort",
            )
            .drop_duplicates(group_cols, keep="first")
            .copy()
        )
        selected.insert(0, "design_voltage_cap_v", cap)
        cap_rows.append(selected)
    best_caps = pd.concat(cap_rows, ignore_index=True) if cap_rows else pd.DataFrame()
    return best_physics, best_caps


def expand_energy_ledgers(best: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for _, case in best.iterrows():
        core = finite(case.get("predryer_core_power_kw"))
        heat = finite(case.get("condensation_or_phase_change_heat_proxy_kw"))
        water = finite(case.get("integrated_water_transfer_kg_h"))
        ledgers = [("free_heat_rejection_upper_bound", 0.0)]
        for cop in args.heat_rejection_cops:
            if cop > 0.0:
                ledgers.append((f"heat_rejection_cop_{cop:g}", heat / cop))
        for ledger_id, rejection_power in ledgers:
            total = core + rejection_power
            rows.append(
                {
                    **case.to_dict(),
                    "energy_ledger_id": ledger_id,
                    "heat_rejection_electricity_kw": rejection_power,
                    "predryer_total_electricity_kw": total,
                    "predryer_total_sec_kwh_kg": total / water if water > 0.0 else math.nan,
                }
            )
    return pd.DataFrame(rows)


def build_system_foms(energy: pd.DataFrame, context: Mapping[str, Any], args: argparse.Namespace) -> pd.DataFrame:
    if energy.empty:
        return pd.DataFrame()
    process = context["process_basis"]
    supply_w = float(axial.humidity_ratio_from_t_rh(20.0, 0.50, float(process.absolute_pressure_pa)))
    total_system_water_kg_h = (
        float(process.dry_air_mass_flow_kg_s)
        * (float(process.inlet_humidity_ratio_kg_kg_da) - supply_w)
        * 3600.0
    )
    baseline_power = AHU_ANCHORS["O80"]["process_electric_kw"]
    useful_service_kw = AHU_ANCHORS["O80"]["cooling_removed_kw"]
    baseline_cop = useful_service_kw / baseline_power

    rows: list[dict[str, Any]] = []
    for _, case in energy.iterrows():
        target = str(case["target"])
        remaining_ac = AHU_ANCHORS[target]["process_electric_kw"]
        predryer = finite(case.get("predryer_total_electricity_kw"))
        combined = remaining_ac + predryer
        saving_kw = baseline_power - combined
        combined_cop = useful_service_kw / combined
        water = finite(case.get("integrated_water_transfer_kg_h"))
        for hours in args.annual_hours:
            rows.append(
                {
                    **case.to_dict(),
                    "ahu_reference_source": "declared_150000_cfm_equal_service_report_anchors",
                    "baseline_hvac_electricity_kw": baseline_power,
                    "remaining_hvac_electricity_kw": remaining_ac,
                    "combined_system_electricity_kw": combined,
                    "net_system_saving_kw": saving_kw,
                    "net_system_saving_pct": 100.0 * saving_kw / baseline_power,
                    "baseline_useful_service_kw": useful_service_kw,
                    "baseline_constant_service_cop": baseline_cop,
                    "combined_constant_service_cop": combined_cop,
                    "combined_cop_improvement_pct": 100.0 * (combined_cop / baseline_cop - 1.0),
                    "target_ac_cop_without_predryer_power": AHU_ANCHORS[target]["cop_cooling"],
                    "ac_cop_improvement_pct": 100.0 * (
                        AHU_ANCHORS[target]["cop_cooling"] / AHU_ANCHORS["O80"]["cop_cooling"] - 1.0
                    ),
                    "predryer_water_removal_kg_h": water,
                    "total_system_water_removed_kg_h": total_system_water_kg_h,
                    "combined_system_sec_kwh_kg_total_water": (
                        combined / total_system_water_kg_h if total_system_water_kg_h > 0.0 else math.nan
                    ),
                    "annual_equivalent_full_load_hours": float(hours),
                    "annual_energy_saving_kwh": saving_kw * float(hours),
                    "annual_energy_value_chf": saving_kw * float(hours) * float(args.electricity_price_chf_kwh),
                }
            )
    return pd.DataFrame(rows)


def reconstruct_through_thickness(
    material: Mapping[str, Any],
    *,
    current_density_a_m2: float,
    net_flux_mol_m2_s: float,
    source_surface_activity: float,
    receiver_surface_activity: float,
    fixed_site_concentration_mol_m3: float | None,
    points: int = 161,
) -> pd.DataFrame:
    length_m = float(material["dry_thickness_um"]) * 1.0e-6
    drag = float(material["water_drag"])
    d0 = float(material["water_diffusivity_m2_s"])
    c0 = float(material["water_capacity_mol_m3_activity"])
    p_d = float(material["diffusivity_activity_exponent"])
    p_c = float(material["capacity_activity_exponent"])
    exponent = p_d + p_c
    eo_flux = drag * current_density_a_m2 / FARADAY_C_MOL
    gradient_numerator = eo_flux - net_flux_mol_m2_s
    y = np.linspace(0.0, length_m, points)
    if abs(exponent + 1.0) > 1.0e-12:
        power = exponent + 1.0
        base = (
            source_surface_activity**power
            + power * gradient_numerator * y / (d0 * c0)
        )
        activity_raw = np.where(base > 0.0, base ** (1.0 / power), np.nan)
    else:
        activity_raw = source_surface_activity * np.exp(gradient_numerator * y / (d0 * c0))

    if abs(p_c + 1.0) > 1.0e-12:
        concentration = c0 * activity_raw ** (p_c + 1.0) / (p_c + 1.0)
    else:
        concentration = c0 * np.log(activity_raw)

    endpoint_error = finite(activity_raw[-1]) - receiver_surface_activity
    physical = bool(
        np.isfinite(activity_raw).all()
        and np.nanmin(activity_raw) >= -1.0e-9
        and np.nanmax(activity_raw) <= 1.0 + 1.0e-8
        and abs(endpoint_error) <= 2.0e-3
    )
    frame = pd.DataFrame(
        {
            "y_m": y,
            "y_over_L": y / length_m,
            "water_activity_raw": activity_raw,
            "water_activity_for_plot": np.where(
                (activity_raw >= 0.0) & (activity_raw <= 1.0), activity_raw, np.nan
            ),
            "water_concentration_model_mol_m3": concentration,
            "profile_physical": physical,
            "receiver_endpoint_error": endpoint_error,
        }
    )
    if fixed_site_concentration_mol_m3 is not None and fixed_site_concentration_mol_m3 > 0.0:
        frame["hydration_lambda_proxy"] = concentration / fixed_site_concentration_mol_m3
    return frame


def rerun_selected_profiles(
    continuation: ModuleType,
    context: Mapping[str, Any],
    best: pd.DataFrame,
    args: argparse.Namespace,
    out: Path,
) -> pd.DataFrame:
    profiles_dir = out / "profiles"
    thickness_dir = out / "through_thickness"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    thickness_dir.mkdir(parents=True, exist_ok=True)
    bases = material_bases(context, args)
    diagnostics: list[dict[str, Any]] = []

    pure = best[np.isclose(best["liquid_activity"], max(args.liquid_activities), atol=1.0e-9)].copy()
    if pure.empty:
        pure = best.copy()

    for (target, basis_id), group in pure.groupby(["target", "material_basis_id"], sort=True):
        selected = group.sort_values("predryer_core_power_kw").head(int(args.profile_top_n))
        for rank, (_, row) in enumerate(selected.iterrows(), start=1):
            material = row_to_material(
                context,
                bases[basis_id],
                basis_id,
                float(row["water_drag"]),
            )
            summary, profile = integrate_direct_liquid_case(
                context,
                target=str(target),
                material=material,
                material_basis_id=str(basis_id),
                liquid_activity=float(row["liquid_activity"]),
                terminal_voltage_v=float(row["terminal_voltage_v"]),
                process_film_factor=float(row["process_film_factor"]),
                args=args,
                record_profile=True,
            )
            stem = (
                f"{target}__{basis_id}__rank{rank}__tw{float(row['water_drag']):g}__"
                f"V{float(row['terminal_voltage_v']):.6g}__al{float(row['liquid_activity']):.6g}"
            )
            pd.DataFrame([summary]).to_csv(profiles_dir / f"{stem}_summary.csv", index=False)
            profile.to_csv(profiles_dir / f"{stem}_axial_profile.csv.gz", index=False, compression="gzip")
            if profile.empty:
                continue
            total_area = max(float(profile["cumulative_area_m2"].max()), EPS)
            profile = profile.copy()
            profile["x_over_L"] = profile["cumulative_area_m2"] / total_area

            fig, ax = plt.subplots(figsize=(7.6, 4.8))
            ax.plot(profile["x_over_L"], profile["eo_flux_mol_m2_s"], label="EO")
            ax.plot(profile["x_over_L"], profile["diffusion_flux_mol_m2_s"], label="Signed diffusion")
            ax.plot(profile["x_over_L"], profile["net_flux_mol_m2_s"], label="Net")
            ax.axhline(0.0, linewidth=0.9)
            ax.set(xlabel="Axial position x/L", ylabel="Water flux [mol m$^{-2}$ s$^{-1}$]", title=f"{target}: direct-liquid EO/diffusion/net flux")
            ax.grid(alpha=0.25)
            ax.legend()
            fig.tight_layout()
            fig.savefig(profiles_dir / f"{stem}_fluxes.png", dpi=220)
            fig.savefig(profiles_dir / f"{stem}_fluxes.pdf")
            plt.close(fig)

            fig, ax = plt.subplots(figsize=(7.6, 4.8))
            ax.plot(profile["x_over_L"], profile["process_activity"], label="Process bulk")
            ax.plot(profile["x_over_L"], profile["process_surface_activity"], label="Process surface")
            ax.plot(profile["x_over_L"], profile["receiver_surface_activity"], label="Liquid-side surface")
            ax.axhline(float(row["liquid_activity"]), linestyle="--", label="Declared liquid activity")
            ax.set(xlabel="Axial position x/L", ylabel="Water activity [-]", title=f"{target}: direct-liquid activity boundary")
            ax.set_ylim(bottom=0.0, top=1.02)
            ax.grid(alpha=0.25)
            ax.legend()
            fig.tight_layout()
            fig.savefig(profiles_dir / f"{stem}_activities.png", dpi=220)
            fig.savefig(profiles_dir / f"{stem}_activities.pdf")
            plt.close(fig)

            local_config = copy.deepcopy(context["base"])
            local_config["channel"] = copy.deepcopy(context["base"]["channel"])
            curves: list[pd.DataFrame] = []
            profile_physical_all = True
            maximum_raw_activity = -math.inf
            maximum_endpoint_error = 0.0
            for position in PROFILE_POSITIONS:
                idx = (profile["x_over_L"] - position).abs().idxmin()
                point = profile.loc[idx]
                local = solve_local_state(v2=context['v2'], v2_config=context['v2_config'], material=material, source_temperature_c=float(context['process_basis'].inlet_temperature_c), source_humidity_ratio=float(point['process_humidity_ratio_kg_kg_da']), receiver_activity=float(row['liquid_activity']), terminal_voltage_v=float(row['terminal_voltage_v']), fixed_loss_voltage_v=0.0, series_asr_ohm_m2=float(context['cfg12']['operating']['legacy_series_asr_ohm_m2']), film_scale_factor=float(context['cfg12']['operating']['film_scale_factor']), config=local_config, process_film_scale_factor=float(context['cfg12']['operating']['film_scale_factor']) * float(row['process_film_factor']), receiver_film_scale_factor=float(context['cfg12']['operating']['film_scale_factor']) * float(args.liquid_interface_factor))
                if not bool(local.get("solution_ok", False)):
                    continue
                source_surface = first_finite(local, ["source_surface_activity", "source_membrane_surface_activity"])
                receiver_surface = first_finite(local, ["receiver_surface_activity", "receiver_membrane_surface_activity"])
                thickness = reconstruct_through_thickness(
                    material,
                    current_density_a_m2=float(local["current_density_a_m2"]),
                    net_flux_mol_m2_s=float(local["net_flux_mol_m2_s"]),
                    source_surface_activity=source_surface,
                    receiver_surface_activity=receiver_surface,
                    fixed_site_concentration_mol_m3=args.fixed_site_concentration_mol_m3,
                )
                thickness["requested_x_over_L"] = position
                thickness["actual_x_over_L"] = float(point["x_over_L"])
                path = thickness_dir / f"{stem}__x{position:.2f}.csv"
                thickness.to_csv(path, index=False)
                thickness["curve_label"] = f"x/L={position:.2f}"
                curves.append(thickness)
                profile_physical_all = profile_physical_all and bool(thickness["profile_physical"].iloc[0])
                maximum_raw_activity = max(maximum_raw_activity, float(np.nanmax(thickness["water_activity_raw"])))
                maximum_endpoint_error = max(maximum_endpoint_error, abs(float(thickness["receiver_endpoint_error"].iloc[0])))

            if curves:
                fig, ax = plt.subplots(figsize=(7.6, 4.8))
                for curve in curves:
                    ax.plot(
                        curve["y_over_L"],
                        curve["water_activity_for_plot"],
                        label=curve["curve_label"].iloc[0],
                    )
                ax.axhline(1.0, linestyle="--", linewidth=0.9, label="Physical activity limit")
                ax.set(xlabel="Through-thickness position y/L", ylabel="Water activity [-]", title=f"{target}: physically gated through-membrane profiles")
                ax.set_ylim(bottom=0.0, top=1.02)
                ax.grid(alpha=0.25)
                ax.legend()
                fig.tight_layout()
                fig.savefig(thickness_dir / f"{stem}_activity_profiles.png", dpi=220)
                fig.savefig(thickness_dir / f"{stem}_activity_profiles.pdf")
                plt.close(fig)

            diagnostics.append(
                {
                    "target": target,
                    "material_basis_id": basis_id,
                    "rank": rank,
                    "water_drag": float(row["water_drag"]),
                    "terminal_voltage_v": float(row["terminal_voltage_v"]),
                    "liquid_activity": float(row["liquid_activity"]),
                    "profile_physical_all_positions": profile_physical_all,
                    "maximum_reconstructed_raw_activity": maximum_raw_activity,
                    "maximum_receiver_endpoint_error": maximum_endpoint_error,
                    "thermodynamic_identity_relative_error": finite(summary.get("thermodynamic_identity_relative_error")),
                    "backdiffusion_fraction_of_eo": finite(summary.get("backdiffusion_fraction_of_eo")),
                    "minimum_process_surface_activity": finite(summary.get("minimum_process_surface_activity")),
                    "maximum_receiver_surface_activity": finite(summary.get("maximum_receiver_surface_activity")),
                }
            )
    diagnostics_frame = pd.DataFrame(diagnostics)
    diagnostics_frame.to_csv(out / "selected_profile_diagnostics.csv", index=False)
    return diagnostics_frame


def gas_only_comparison(best: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    path = args.gas_only_results_csv
    if not path.is_absolute():
        path = ROOT / path
    gas = safe_read_csv(path)
    if gas.empty or best.empty:
        return pd.DataFrame()
    if "energy_ledger_id" in gas.columns:
        gas = gas[gas["energy_ledger_id"].astype(str).eq("free_heat_rejection_upper_bound")].copy()
    direct = best[np.isclose(best["liquid_activity"], max(args.liquid_activities), atol=1.0e-9)].copy()
    if direct.empty:
        return pd.DataFrame()
    gas = gas.rename(columns={column: f"gas_{column}" for column in gas.columns if column not in {"target", "water_drag"}})
    direct = direct.rename(columns={column: f"direct_{column}" for column in direct.columns if column not in {"target", "water_drag"}})
    merged = direct.merge(gas, on=["target", "water_drag"], how="inner")
    if not merged.empty:
        if "direct_predryer_core_power_kw" in merged and "gas_predryer_core_power_kw" in merged:
            merged["direct_minus_gas_core_power_kw"] = (
                merged["direct_predryer_core_power_kw"] - merged["gas_predryer_core_power_kw"]
            )
        if "direct_required_active_area_m2" in merged and "gas_required_active_area_m2" in merged:
            merged["direct_minus_gas_area_m2"] = (
                merged["direct_required_active_area_m2"] - merged["gas_required_active_area_m2"]
            )
    return merged


def make_plots(best: pd.DataFrame, foms: pd.DataFrame, args: argparse.Namespace, out: Path) -> None:
    figures = out / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    if best.empty:
        return
    pure_activity = max(args.liquid_activities)
    pure = best[np.isclose(best["liquid_activity"], pure_activity, atol=1.0e-9)].copy()
    if pure.empty:
        pure = best.copy()

    for (target, basis_id), group in pure.groupby(["target", "material_basis_id"], sort=True):
        ordered = group.sort_values("water_drag")
        metrics = [
            ("core_power_vs_tw", "predryer_core_power_kw", "Pre-dryer core power [kW]", "Direct-liquid core power"),
            ("sec_vs_tw", "predryer_core_sec_kwh_kg", "SEC [kWh/kg water]", "Direct-liquid core SEC"),
            ("area_vs_tw", "required_active_area_m2", "Active area [m²]", "Required membrane area"),
            ("voltage_vs_tw", "terminal_voltage_v", "Terminal voltage [V]", "Optimised voltage"),
            ("backdiffusion_vs_tw", "backdiffusion_fraction_of_eo", "Back-diffusion / EO [-]", "Back-diffusion fraction"),
            ("heat_duty_vs_tw", "condensation_or_phase_change_heat_proxy_kw", "Thermal rejection duty [kW]", "Liquid-production heat duty"),
        ]
        for stem, column, ylabel, title in metrics:
            fig, ax = plt.subplots(figsize=(7.4, 4.7))
            ax.plot(ordered["water_drag"], ordered[column], marker="o")
            if column == "terminal_voltage_v":
                for cap in sorted(set(args.design_voltage_caps_v)):
                    ax.axhline(cap, linestyle="--", linewidth=0.8, label=f"{cap:g} V cap")
                ax.legend()
            ax.set(xlabel="Water drag $t_w$ [-]", ylabel=ylabel, title=f"{target}, {basis_id}: {title}")
            ax.grid(alpha=0.25)
            fig.tight_layout()
            fig.savefig(figures / f"{target}__{basis_id}__{stem}.png", dpi=220)
            fig.savefig(figures / f"{target}__{basis_id}__{stem}.pdf")
            plt.close(fig)

    for (target, basis_id), group in best.groupby(["target", "material_basis_id"], sort=True):
        pivot = group.pivot_table(
            index="liquid_activity",
            columns="water_drag",
            values="predryer_core_power_kw",
            aggfunc="min",
        )
        if pivot.empty:
            continue
        fig, ax = plt.subplots(figsize=(8.0, 4.8))
        image = ax.imshow(pivot.to_numpy(float), aspect="auto", origin="lower")
        ax.set_xticks(np.arange(len(pivot.columns)), labels=[f"{value:g}" for value in pivot.columns])
        ax.set_yticks(np.arange(len(pivot.index)), labels=[f"{value:.6g}" for value in pivot.index])
        ax.set_xlabel("Water drag $t_w$")
        ax.set_ylabel("Liquid/sink activity")
        ax.set_title(f"{target}, {basis_id}: direct-liquid core power [kW]")
        fig.colorbar(image, ax=ax, label="Core power [kW]")
        fig.tight_layout()
        fig.savefig(figures / f"{target}__{basis_id}__liquid_activity_power_map.png", dpi=220)
        fig.savefig(figures / f"{target}__{basis_id}__liquid_activity_power_map.pdf")
        plt.close(fig)

    if not foms.empty:
        reference_hours = min(
            foms["annual_equivalent_full_load_hours"].unique(),
            key=lambda value: abs(value - 6000.0),
        )
        selected = foms[
            np.isclose(foms["annual_equivalent_full_load_hours"], reference_hours)
            & foms["energy_ledger_id"].astype(str).eq("free_heat_rejection_upper_bound")
            & np.isclose(foms["liquid_activity"], pure_activity, atol=1.0e-9)
        ].copy()
        for (target, basis_id), group in selected.groupby(["target", "material_basis_id"], sort=True):
            ordered = group.sort_values("water_drag")
            fig, ax = plt.subplots(figsize=(7.4, 4.7))
            ax.plot(ordered["water_drag"], ordered["net_system_saving_pct"], marker="o")
            ax.axhline(0.0, linestyle="--", linewidth=0.9)
            ax.set(xlabel="Water drag $t_w$ [-]", ylabel="Net saving vs no-ERV AHU [%]", title=f"{target}, {basis_id}: conditional system saving")
            ax.grid(alpha=0.25)
            fig.tight_layout()
            fig.savefig(figures / f"{target}__{basis_id}__system_saving_vs_tw.png", dpi=220)
            fig.savefig(figures / f"{target}__{basis_id}__system_saving_vs_tw.pdf")
            plt.close(fig)


def write_summary(
    out: Path,
    args: argparse.Namespace,
    best: pd.DataFrame,
    caps: pd.DataFrame,
    foms: pd.DataFrame,
    diagnostics: pd.DataFrame,
) -> None:
    lines = [
        "# HeiQ direct liquid-contact receiver study v1",
        "",
        "## Boundary",
        "",
        "- Process air is marched axially with the reviewed V2/V3 local membrane BVP.",
        "- A liquid/sink activity is imposed from the first active-area step.",
        "- Receiver-side gas-flow capacity and receiver fan power are absent.",
        "- All transferred water is counted as liquid product immediately.",
        "- The full thermal rejection duty is reported explicitly.",
        "- Values below liquid activity one are solution/desiccant sensitivities, not pure water.",
        "",
        "## Scope limits",
        "",
        "No finite liquid film, capillary pressure, drainage geometry, flooding, wet-electrode kinetics, electrolysis, corrosion or conjugate heat-transfer model is included.",
        "",
    ]
    if best.empty:
        lines += ["## Result", "", "No case passed the physical and numerical gates."]
    else:
        pure_activity = max(args.liquid_activities)
        pure = best[np.isclose(best["liquid_activity"], pure_activity, atol=1.0e-9)].copy()
        lines += [
            "## Best pure-water-proxy rows",
            "",
        ]
        columns = [
            "target", "material_basis_id", "water_drag", "liquid_activity",
            "terminal_voltage_v", "required_active_area_m2",
            "predryer_core_power_kw", "predryer_core_sec_kwh_kg",
            "backdiffusion_fraction_of_eo", "condensation_or_phase_change_heat_proxy_kw",
        ]
        if pure.empty:
            lines.append("No pure-water-proxy case passed.")
        else:
            lines.append(pure[columns].to_markdown(index=False))
    if not diagnostics.empty:
        lines += [
            "",
            "## Profile audit",
            "",
            f"- Selected profile rows: {len(diagnostics)}.",
            f"- All reconstructed profiles physical: {bool(diagnostics['profile_physical_all_positions'].all())}.",
            f"- Maximum raw reconstructed activity: {diagnostics['maximum_reconstructed_raw_activity'].max():.6g}.",
            f"- Maximum through-thickness endpoint error: {diagnostics['maximum_receiver_endpoint_error'].max():.6g}.",
        ]
    if not foms.empty:
        lines += [
            "",
            "## Conditional no-ERV equal-service FOM range",
            "",
            f"- Maximum net saving: {foms['net_system_saving_pct'].max():.3f}%.",
            f"- Minimum net saving: {foms['net_system_saving_pct'].min():.3f}%.",
            "- These FOMs use the declared 150,000-cfm no-ERV AHU anchors and are not the modern AC+ERV project baseline.",
        ]
    (out / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def self_test() -> None:
    assert math.isclose(liquid_pump_power_kw(3600.0, 100000.0, 0.5), 0.20060180541624875, rel_tol=1e-12)
    assert latent_heat_vaporisation_kj_kg(32.0) > 2400.0
    grid = voltage_grid(
        target="O30",
        water_drag=50.0,
        liquid_activity=0.999999,
        temperature_c=32.0,
        search_max_v=24.0,
        smoke=False,
    )
    assert grid and max(grid) <= 24.0
    material = {
        "dry_thickness_um": 100.0,
        "water_drag": 50.0,
        "water_diffusivity_m2_s": 1.0e-12,
        "water_capacity_mol_m3_activity": 10000.0,
        "diffusivity_activity_exponent": 2.0,
        "capacity_activity_exponent": 0.0,
    }
    profile = reconstruct_through_thickness(
        material,
        current_density_a_m2=20.0,
        net_flux_mol_m2_s=0.005,
        source_surface_activity=0.3,
        receiver_surface_activity=0.8,
        fixed_site_concentration_mol_m3=None,
    )
    assert len(profile) == 161
    assert "water_activity_raw" in profile
    print("Self-test passed: voltage centring, pump ledger, latent-heat proxy and profile reconstruction are consistent.")


def main() -> int:
    args = parse_args()
    validate_args(args)
    if args.self_test:
        self_test()
        return 0

    continuation, context = setup_context(args)
    out = ROOT / args.output_dir
    out.mkdir(parents=True, exist_ok=True)

    metadata = {
        "script": "make_wp1_direct_liquid_contact_receiver_v1.py",
        "model_basis": "V2/V3 local membrane BVP plus process-only axial integration",
        "receiver_boundary": "direct liquid contact from first active-area step",
        "receiver_gas_flow_present": False,
        "receiver_fan_power_included": False,
        "water_drags": args.water_drags,
        "liquid_activities": args.liquid_activities,
        "material_basis": args.material_basis,
        "area_limit_m2": args.area_max_m2,
        "voltage_search_cap_v": args.voltage_search_max_v,
        "design_voltage_caps_v": args.design_voltage_caps_v,
        "liquid_interface_factor": args.liquid_interface_factor,
        "process_film_factors": args.process_film_factors,
        "limitations": [
            "no finite liquid-film mass-transfer law",
            "no capillary/drainage geometry",
            "no flooding model",
            "no wet-electrode kinetics",
            "no electrolysis/corrosion model",
            "no conjugate thermal solution",
            "sub-unity sink activity is not pure water",
        ],
    }
    (out / "run_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    if args.mode == "inspect":
        print(json.dumps(metadata, indent=2))
        return 0

    cases_path = out / "all_direct_liquid_cases.csv.gz"
    if args.mode == "postprocess":
        if not cases_path.is_file():
            raise FileNotFoundError(cases_path)
        cases = pd.read_csv(cases_path)
    else:
        cases = run_grid(continuation, context, args, out)

    best, caps = select_best(cases, args)
    best.to_csv(out / "best_physics_by_target_basis_drag_activity.csv", index=False)
    caps.to_csv(out / "best_by_design_voltage_cap.csv", index=False)

    pure_activity = max(args.liquid_activities)
    pure = best[np.isclose(best["liquid_activity"], pure_activity, atol=1.0e-9)].copy() if not best.empty else pd.DataFrame()
    pure.to_csv(out / "pure_water_proxy_best.csv", index=False)

    energy = expand_energy_ledgers(best, args)
    energy.to_csv(out / "energy_ledgers.csv.gz", index=False, compression="gzip")
    foms = build_system_foms(energy, context, args)
    foms.to_csv(out / "system_foms_no_erv_reference.csv", index=False)

    diagnostics = rerun_selected_profiles(continuation, context, best, args, out) if not best.empty else pd.DataFrame()
    comparison = gas_only_comparison(best, args)
    comparison.to_csv(out / "gas_only_vs_direct_liquid.csv", index=False)
    make_plots(best, foms, args, out)

    design_columns = [
        "target", "material_basis_id", "water_drag", "water_diffusivity_m2_s",
        "conductivity_s_m", "dry_thickness_um", "liquid_activity",
        "terminal_voltage_v", "required_active_area_m2", "process_gap_m",
        "process_velocity_m_s", "process_total_channel_width_m",
        "process_channel_length_m", "process_pressure_drop_pa",
        "maximum_local_current_density_a_m2", "integrated_current_a",
        "eo_grid_power_kw", "process_channel_fan_power_kw",
        "condensate_pump_power_kw", "condensation_or_phase_change_heat_proxy_kw",
        "predryer_core_power_kw", "predryer_core_sec_kwh_kg",
        "stack_feasible", "stack_total_cells", "stack_series_cells",
        "stack_parallel_strings", "minimum_process_surface_activity",
        "maximum_receiver_surface_activity", "backdiffusion_fraction_of_eo",
        "thermodynamic_identity_relative_error",
    ]
    if not pure.empty:
        pure[[column for column in design_columns if column in pure.columns]].to_csv(
            out / "declared_operating_points_and_designs.csv", index=False
        )

    write_summary(out, args, best, caps, foms, diagnostics)

    print("\n=== BEST PURE-WATER-PROXY CASES ===\n")
    if pure.empty:
        print("No pure-water-proxy case passed.")
    else:
        show = [
            "target", "material_basis_id", "water_drag", "terminal_voltage_v",
            "required_active_area_m2", "maximum_local_current_density_a_m2",
            "eo_grid_power_kw", "process_channel_fan_power_kw",
            "condensate_pump_power_kw", "predryer_core_power_kw",
            "predryer_core_sec_kwh_kg", "backdiffusion_fraction_of_eo",
            "condensation_or_phase_change_heat_proxy_kw",
            "thermodynamic_identity_relative_error",
        ]
        print(pure[[column for column in show if column in pure.columns]].to_string(index=False))
    print(f"\nOutputs: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
