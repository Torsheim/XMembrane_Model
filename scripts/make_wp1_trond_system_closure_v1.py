#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


WATER_MOLAR_MASS_KG_MOL = 0.01801528
WATER_DENSITY_KG_L = 0.997
LATENT_HEAT_KJ_KG_32C = 2426.0
HUMIDITY_RATIO_CONSTANT = 0.621945
R_DRY_AIR_J_KG_K = 287.055
CFM_TO_M3_S = 0.00047194745
EPS = 1.0e-12

# Official ASHRAE Handbook Chapter 26 planning envelopes.
# These are exchanger-level ranges, not universal whole-building savings.
ERV_ENVELOPES = {
    "fixed_plate": {
        "sensible_effectiveness": (0.50, 0.75),
        "latent_effectiveness": (0.00, 0.00),
        "pressure_drop_pa_per_stream": (100.0, 1000.0),
    },
    "membrane_plate": {
        "sensible_effectiveness": (0.55, 0.75),
        "latent_effectiveness": (0.25, 0.60),
        "pressure_drop_pa_per_stream": (100.0, 500.0),
    },
    "energy_wheel": {
        "sensible_effectiveness": (0.65, 0.80),
        "latent_effectiveness": (0.50, 0.80),
        "pressure_drop_pa_per_stream": (100.0, 300.0),
    },
}

MATERIAL_DEFAULTS = {
    "model": "powerlaw",
    "water_drag": 100.060787,
    "water_diffusivity_m2_s": 1.597880e-14,
    "conductivity_s_m": 23.171887,
    "dry_thickness_um": 36.9137,
    "water_capacity_mol_m3_activity": 10000.0,
    "diffusivity_activity_exponent": 2.0,
    "conductivity_activity_exponent": 4.0,
    "capacity_activity_exponent": 0.0,
}


@dataclass(frozen=True)
class NativeAPI:
    activity_from_t_w: Any
    build_targets: Any
    channel_pressure_drop_and_fan: Any
    dry_air_mass_flow: Any
    humidity_ratio_from_t_rh: Any
    integrate_axial_case: Any
    load_v2_module: Any
    moist_air_enthalpy_kj_kg_da: Any
    process_channel_fan: Any
    relative_humidity_from_t_w: Any
    solve_local_state: Any
    vapour_pressure_from_humidity_ratio: Any


def native_api() -> NativeAPI:
    from heiq.wp1.airside.properties import (
        activity_from_t_w,
        dry_air_mass_flow,
        humidity_ratio_from_t_rh,
        moist_air_enthalpy_kj_kg_da,
        relative_humidity_from_t_w,
        vapour_pressure_from_humidity_ratio,
    )
    from heiq.wp1.airside.channels import process_channel_fan
    from heiq.wp1.axial import (
        build_targets,
        integrate_axial_case,
        load_v2_module,
        solve_local_state,
    )
    from heiq.wp1.engineering import channel_pressure_drop_and_fan

    return NativeAPI(
        activity_from_t_w=activity_from_t_w,
        build_targets=build_targets,
        channel_pressure_drop_and_fan=channel_pressure_drop_and_fan,
        dry_air_mass_flow=dry_air_mass_flow,
        humidity_ratio_from_t_rh=humidity_ratio_from_t_rh,
        integrate_axial_case=integrate_axial_case,
        load_v2_module=load_v2_module,
        moist_air_enthalpy_kj_kg_da=moist_air_enthalpy_kj_kg_da,
        process_channel_fan=process_channel_fan,
        relative_humidity_from_t_w=relative_humidity_from_t_w,
        solve_local_state=solve_local_state,
        vapour_pressure_from_humidity_ratio=vapour_pressure_from_humidity_ratio,
    )


def finite(value: Any, default: float = math.nan) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def truth(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "y", "pass", "passed"}


def first_existing(frame: pd.DataFrame, names: Iterable[str]) -> str | None:
    for name in names:
        if name in frame.columns:
            return name
    return None


def first_finite(row: Mapping[str, Any], names: Iterable[str], default: float = math.nan) -> float:
    for name in names:
        if name in row:
            value = finite(row[name])
            if math.isfinite(value):
                return value
    return default


def read_table(path: Path) -> pd.DataFrame:
    if path.suffix == ".gz" or path.name.endswith(".csv.gz"):
        return pd.read_csv(path, compression="gzip")
    return pd.read_csv(path)


def find_first(paths: Iterable[Path]) -> Path | None:
    for path in paths:
        if path.is_file() and path.stat().st_size > 0:
            return path
    return None


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def resolve_reference_paths(source_root: Path) -> dict[str, Path | None]:
    return {
        "base_config": find_first(
            [
                source_root / "data/reference/v11_compat/axial_base_config_used.json",
                source_root / "config/pre_receiver_axial_v3_config.json",
                source_root / "scripts/pre_receiver_axial_v3_config.json",
            ]
        ),
        "v2_config": find_first(
            [
                source_root / "config/membrane_v2_default.json",
                source_root / "heiq_pre_receiver_material_analyses/config/default.json",
                source_root / "reference/legacy/heiq_pre_receiver_material_analyses/config/default.json",
            ]
        ),
        "material": find_first(
            [
                source_root / "outputs/prearchitecture_continuation_v2/material_global/overall_best.csv",
                source_root / "data/golden/o30/overall_best.csv",
            ]
        ),
        "gas_o30": find_first(
            [
                source_root / "outputs/prearchitecture_continuation_v2/material_global/overall_best.csv",
                source_root / "outputs/prearchitecture_continuation_v2/o30_receiver/overall_best.csv",
                source_root / "data/golden/o30/overall_best.csv",
            ]
        ),
        "gas_o50": find_first(
            [
                source_root / "outputs/prearchitecture_continuation_v2/o50_edge/best_by_drag.csv",
                source_root / "data/golden/o50/best_by_drag.csv",
            ]
        ),
        "direct_liquid": find_first(
            [
                source_root / "outputs/direct_liquid_contact_receiver_low_activity_v1/all_direct_liquid_cases.csv.gz",
                source_root / "outputs/direct_liquid_contact_receiver_v1/all_direct_liquid_cases.csv.gz",
                source_root / "outputs/saturated_receiver_liquid_drain_v1/all_membrane_cases.csv.gz",
            ]
        ),
    }


def material_from_table(path: Path | None) -> dict[str, Any]:
    material = dict(MATERIAL_DEFAULTS)
    material["name"] = "Terminal1_optimum"

    if path is None:
        return material

    frame = read_table(path)
    if frame.empty:
        return material

    row = frame.iloc[0].to_dict()
    mapping = {
        "water_drag": ["water_drag", "transport_number", "tw"],
        "water_diffusivity_m2_s": ["water_diffusivity_m2_s", "D0"],
        "conductivity_s_m": ["conductivity_s_m", "sigma0"],
        "dry_thickness_um": ["dry_thickness_um", "thickness_um"],
        "water_capacity_mol_m3_activity": ["water_capacity_mol_m3_activity"],
        "diffusivity_activity_exponent": ["diffusivity_activity_exponent"],
        "conductivity_activity_exponent": ["conductivity_activity_exponent"],
        "capacity_activity_exponent": ["capacity_activity_exponent"],
    }
    for target, candidates in mapping.items():
        value = first_finite(row, candidates)
        if math.isfinite(value):
            material[target] = value

    material["name"] = str(row.get("material", row.get("material_id", "Terminal1_optimum")))
    return material


def selected_row(path: Path | None, target: str | None = None) -> dict[str, Any]:
    if path is None:
        return {}
    frame = read_table(path)
    if frame.empty:
        return {}

    if target is not None:
        target_col = first_existing(frame, ["target", "diagnostic_target"])
        if target_col:
            subset = frame[frame[target_col].astype(str).eq(target)]
            if not subset.empty:
                frame = subset

    pass_col = first_existing(frame, ["analysis_pass", "target_reached"])
    power_col = first_existing(
        frame,
        [
            "analysis_core_power_kw",
            "predryer_core_power_kw",
            "free_liquid_removal_power_kw",
            "eo_grid_power_kw",
        ],
    )
    if pass_col:
        passed = frame[frame[pass_col].map(truth)]
        if not passed.empty:
            frame = passed
    if power_col:
        frame = frame.assign(_objective=pd.to_numeric(frame[power_col], errors="coerce"))
        frame = frame.sort_values("_objective", kind="mergesort")
    return frame.iloc[0].to_dict()


def build_native_context(source_root: Path, args: argparse.Namespace) -> dict[str, Any]:
    api = native_api()
    paths = resolve_reference_paths(source_root)

    if paths["base_config"] is None:
        raise FileNotFoundError("Could not find axial base configuration.")
    if paths["v2_config"] is None:
        raise FileNotFoundError("Could not find V2 membrane configuration.")

    base = load_json(paths["base_config"])
    base = json.loads(json.dumps(base))
    base["integration"]["area_limit_m2"] = float(args.area_cap_m2)

    v2_root_candidates = [
        source_root / "heiq_pre_receiver_material_analyses",
        source_root
        / "reference"
        / "legacy"
        / "heiq_pre_receiver_material_analyses",
        source_root,
    ]
    v2_root = next(
        (
            candidate
            for candidate in v2_root_candidates
            if (
                candidate
                / "heiq_pre_receiver_model.py"
            ).is_file()
        ),
        source_root,
    )

    v2 = api.load_v2_module(v2_root)
    v2_config = v2.load_config(paths["v2_config"])

    basis = api.dry_air_mass_flow(base)
    targets = api.build_targets(base, basis, v2_config)
    target_lookup = {
        str(row["target"]): row
        for _, row in targets.iterrows()
    }

    material = material_from_table(paths["material"])

    return {
        "api": api,
        "paths": paths,
        "base": base,
        "v2": v2,
        "v2_config": v2_config,
        "basis": basis,
        "targets": target_lookup,
        "material": material,
    }


def break_even_register(
    *,
    baseline_compressor_kw: float,
    o30_compressor_kw: float,
    water_load_kg_h: float,
    core_power_kw: float,
) -> pd.DataFrame:
    gross = baseline_compressor_kw - o30_compressor_kw
    gross_sec = gross / water_load_kg_h
    remaining = gross - core_power_kw
    remaining_sec = remaining / water_load_kg_h

    rows = [
        {
            "boundary": "legacy_no_erv_gross_compressor",
            "available_power_kw": gross,
            "water_load_kg_h": water_load_kg_h,
            "break_even_sec_kwh_kg": gross_sec,
            "break_even_wh_l_approx": 1000.0 * gross_sec / WATER_DENSITY_KG_L,
            "interpretation": (
                "Conditional gross compressor opportunity at one duty point; "
                "not a universal or ERV-adjusted system break-even."
            ),
        },
        {
            "boundary": "remaining_after_current_core",
            "available_power_kw": remaining,
            "water_load_kg_h": water_load_kg_h,
            "break_even_sec_kwh_kg": remaining_sec,
            "break_even_wh_l_approx": 1000.0 * remaining_sec / WATER_DENSITY_KG_L,
            "interpretation": (
                "Nominal allowance for receiver regeneration, heat rejection, "
                "pumps, controls and other omitted loads under the same legacy baseline."
            ),
        },
        {
            "boundary": "current_core",
            "available_power_kw": core_power_kw,
            "water_load_kg_h": water_load_kg_h,
            "break_even_sec_kwh_kg": core_power_kw / water_load_kg_h,
            "break_even_wh_l_approx": (
                1000.0 * core_power_kw / water_load_kg_h / WATER_DENSITY_KG_L
            ),
            "interpretation": "Current modeled pre-architecture core SEC.",
        },
    ]
    return pd.DataFrame(rows)


def erv_supply_state(
    *,
    api: NativeAPI,
    outdoor_temperature_c: float,
    outdoor_humidity_ratio: float,
    return_temperature_c: float,
    return_humidity_ratio: float,
    sensible_effectiveness: float,
    latent_effectiveness: float,
) -> tuple[float, float]:
    temperature = outdoor_temperature_c - sensible_effectiveness * (
        outdoor_temperature_c - return_temperature_c
    )
    humidity_ratio = outdoor_humidity_ratio - latent_effectiveness * (
        outdoor_humidity_ratio - return_humidity_ratio
    )
    return temperature, humidity_ratio


def build_erv_grid(
    *,
    api: NativeAPI,
    basis: Any,
    args: argparse.Namespace,
) -> pd.DataFrame:
    pressure = float(args.pressure_pa)
    outdoor_w = api.humidity_ratio_from_t_rh(
        args.outdoor_temperature_c,
        args.outdoor_rh,
        pressure,
    )
    return_w = api.humidity_ratio_from_t_rh(
        args.return_temperature_c,
        args.return_rh,
        pressure,
    )
    supply_w = api.humidity_ratio_from_t_rh(
        args.supply_temperature_c,
        args.supply_rh,
        pressure,
    )

    h_outdoor = api.moist_air_enthalpy_kj_kg_da(
        args.outdoor_temperature_c, outdoor_w
    )
    h_supply = api.moist_air_enthalpy_kj_kg_da(
        args.supply_temperature_c, supply_w
    )
    raw_base_coil_kw = basis.dry_air_mass_flow_kg_s * max(
        h_outdoor - h_supply, 0.0
    )
    raw_base_compressor_kw = raw_base_coil_kw / args.cooling_cop
    calibration = args.baseline_compressor_kw / max(raw_base_compressor_kw, EPS)

    rows: list[dict[str, Any]] = []
    for technology, envelope in ERV_ENVELOPES.items():
        for quantile, fraction in (("low", 0.0), ("mid", 0.5), ("high", 1.0)):
            sensible = envelope["sensible_effectiveness"][0] + fraction * (
                envelope["sensible_effectiveness"][1]
                - envelope["sensible_effectiveness"][0]
            )
            latent = envelope["latent_effectiveness"][0] + fraction * (
                envelope["latent_effectiveness"][1]
                - envelope["latent_effectiveness"][0]
            )
            pressure_drop = envelope["pressure_drop_pa_per_stream"][0] + fraction * (
                envelope["pressure_drop_pa_per_stream"][1]
                - envelope["pressure_drop_pa_per_stream"][0]
            )

            t_after, w_after = erv_supply_state(
                api=api,
                outdoor_temperature_c=args.outdoor_temperature_c,
                outdoor_humidity_ratio=outdoor_w,
                return_temperature_c=args.return_temperature_c,
                return_humidity_ratio=return_w,
                sensible_effectiveness=sensible,
                latent_effectiveness=latent,
            )
            h_after = api.moist_air_enthalpy_kj_kg_da(t_after, w_after)
            coil_kw = basis.dry_air_mass_flow_kg_s * max(h_after - h_supply, 0.0)
            compressor_kw = calibration * coil_kw / args.cooling_cop

            supply_volume = float(basis.volume_flow_m3_s)
            exhaust_volume = supply_volume
            fan_kw = (
                pressure_drop
                * (supply_volume + exhaust_volume)
                / args.erv_fan_efficiency
                / 1000.0
            )
            device_kw = compressor_kw + fan_kw
            site_kw = device_kw / args.grid_to_device_efficiency
            baseline_site_kw = args.baseline_compressor_kw / args.grid_to_device_efficiency
            saving_kw = baseline_site_kw - site_kw

            rows.append(
                {
                    "technology": technology,
                    "rating_point": quantile,
                    "sensible_effectiveness": sensible,
                    "latent_effectiveness": latent,
                    "pressure_drop_pa_per_stream": pressure_drop,
                    "erv_supply_temperature_c": t_after,
                    "erv_supply_humidity_ratio_kg_kg_da": w_after,
                    "erv_supply_relative_humidity": api.relative_humidity_from_t_w(
                        t_after, w_after, pressure
                    ),
                    "coil_load_kw": coil_kw,
                    "compressor_power_kw": compressor_kw,
                    "erv_fan_power_kw": fan_kw,
                    "device_bus_power_kw": device_kw,
                    "site_power_kw": site_kw,
                    "grid_conversion_loss_kw": site_kw - device_kw,
                    "baseline_site_power_kw": baseline_site_kw,
                    "saving_kw": saving_kw,
                    "saving_pct_of_baseline": 100.0 * saving_kw / baseline_site_kw,
                    "available_additional_water_kg_h": max(
                        basis.dry_air_mass_flow_kg_s * (w_after - supply_w) * 3600.0,
                        0.0,
                    ),
                    "source_basis": "ASHRAE Chapter 26 exchanger-level range",
                    "comparison_warning": (
                        "Design-point ventilation-air calculation; not directly "
                        "comparable to generic annual whole-building savings percentages."
                    ),
                }
            )
    return pd.DataFrame(rows)


def eo_sec_options(
    *,
    gas_row: Mapping[str, Any],
    liquid_table: pd.DataFrame | None,
    water_load_kg_h: float,
) -> pd.DataFrame:
    core_power = first_finite(
        gas_row,
        ["analysis_core_power_kw", "predryer_core_power_kw", "core_power_kw"],
        115.018,
    )
    eo_power = first_finite(gas_row, ["eo_grid_power_kw"], 70.69)
    process_fan = first_finite(
        gas_row, ["process_channel_fan_power_kw", "process_fan_power_kw"], 6.16
    )

    rows = [
        {
            "eo_boundary": "gas_receiver_core",
            "sec_kwh_kg": first_finite(
                gas_row, ["analysis_core_sec_kwh_kg", "core_sec_kwh_kg"],
                core_power / water_load_kg_h,
            ),
            "included": "EO + process fan + receiver fan",
        },
        {
            "eo_boundary": "eo_grid_only",
            "sec_kwh_kg": eo_power / water_load_kg_h,
            "included": "EO grid electricity only",
        },
        {
            "eo_boundary": "eo_plus_process_fan",
            "sec_kwh_kg": (eo_power + process_fan) / water_load_kg_h,
            "included": "EO + process fan; no receiver-air fan",
        },
    ]

    if liquid_table is not None and not liquid_table.empty:
        power_col = first_existing(
            liquid_table,
            [
                "free_liquid_removal_power_kw",
                "predryer_core_power_kw",
                "analysis_core_power_kw",
            ],
        )
        water_col = first_existing(
            liquid_table,
            [
                "integrated_water_transfer_kg_h",
                "integrated_water_removal_kg_h",
                "water_removed_kg_h",
            ],
        )
        pass_col = first_existing(liquid_table, ["analysis_pass", "target_reached"])
        subset = liquid_table.copy()
        if pass_col:
            passed = subset[subset[pass_col].map(truth)]
            if not passed.empty:
                subset = passed
        if power_col and water_col:
            subset = subset.assign(
                _sec=pd.to_numeric(subset[power_col], errors="coerce")
                / pd.to_numeric(subset[water_col], errors="coerce")
            )
            subset = subset.replace([np.inf, -np.inf], np.nan).dropna(subset=["_sec"])
            if not subset.empty:
                best = subset.sort_values("_sec").iloc[0]
                rows.append(
                    {
                        "eo_boundary": "best_available_direct_liquid_case",
                        "sec_kwh_kg": float(best["_sec"]),
                        "included": str(power_col),
                    }
                )
    return pd.DataFrame(rows)


def incremental_eo_requirement(
    *,
    erv: pd.DataFrame,
    sec_options: pd.DataFrame,
    basis: Any,
    args: argparse.Namespace,
) -> pd.DataFrame:
    api = native_api()
    pressure = args.pressure_pa
    supply_w = api.humidity_ratio_from_t_rh(
        args.supply_temperature_c, args.supply_rh, pressure
    )

    rows: list[dict[str, Any]] = []
    selected = erv[
        ((erv["technology"] == "membrane_plate") & (erv["rating_point"] == "mid"))
        | ((erv["technology"] == "energy_wheel") & (erv["rating_point"] == "mid"))
        | ((erv["technology"] == "energy_wheel") & (erv["rating_point"] == "high"))
    ].copy()

    for _, erv_row in selected.iterrows():
        t_after = float(erv_row["erv_supply_temperature_c"])
        w_after = float(erv_row["erv_supply_humidity_ratio_kg_kg_da"])
        available_water = max(
            basis.dry_air_mass_flow_kg_s * (w_after - supply_w) * 3600.0, 0.0
        )

        # Linearized latent-only compressor saving per kg/h of additional EO water removal.
        latent_kj_kg = 2501.0 + 1.86 * t_after
        raw_base_w = api.humidity_ratio_from_t_rh(
            args.outdoor_temperature_c, args.outdoor_rh, pressure
        )
        raw_supply_w = supply_w
        raw_base_h = api.moist_air_enthalpy_kj_kg_da(
            args.outdoor_temperature_c, raw_base_w
        )
        raw_supply_h = api.moist_air_enthalpy_kj_kg_da(
            args.supply_temperature_c, raw_supply_w
        )
        raw_base_compressor = (
            basis.dry_air_mass_flow_kg_s
            * max(raw_base_h - raw_supply_h, 0.0)
            / args.cooling_cop
        )
        calibration = args.baseline_compressor_kw / max(raw_base_compressor, EPS)
        compressor_device_saving_per_kg_h = (
            calibration * latent_kj_kg / 3600.0 / args.cooling_cop
        )
        compressor_site_saving_per_kg_h = (
            compressor_device_saving_per_kg_h / args.grid_to_device_efficiency
        )

        for _, sec_row in sec_options.iterrows():
            eo_site_sec = float(sec_row["sec_kwh_kg"]) / args.grid_to_device_efficiency
            net_site_saving_per_kg_h = (
                compressor_site_saving_per_kg_h - eo_site_sec
            )
            for basis_name, target_kw in (
                ("10pct_post_erv", 0.10 * float(erv_row["site_power_kw"])),
                ("10pct_original_baseline", 0.10 * float(erv_row["baseline_site_power_kw"])),
            ):
                if net_site_saving_per_kg_h <= 0.0:
                    required = math.inf
                else:
                    required = target_kw / net_site_saving_per_kg_h

                rows.append(
                    {
                        "technology": erv_row["technology"],
                        "erv_rating_point": erv_row["rating_point"],
                        "eo_boundary": sec_row["eo_boundary"],
                        "reduction_definition": basis_name,
                        "target_net_reduction_kw": target_kw,
                        "compressor_site_saving_per_kg_h": (
                            compressor_site_saving_per_kg_h
                        ),
                        "eo_site_sec_kwh_kg": eo_site_sec,
                        "net_site_saving_per_kg_h": net_site_saving_per_kg_h,
                        "required_additional_water_transport_kg_h": required,
                        "available_post_erv_water_kg_h": available_water,
                        "feasible_by_available_water": (
                            math.isfinite(required) and required <= available_water + 1e-9
                        ),
                        "additional_eo_site_power_kw": (
                            required * eo_site_sec if math.isfinite(required) else math.inf
                        ),
                        "gross_compressor_site_reduction_kw": (
                            required * compressor_site_saving_per_kg_h
                            if math.isfinite(required)
                            else math.inf
                        ),
                    }
                )
    return pd.DataFrame(rows)


def diffusivity_extension(
    *,
    context: dict[str, Any],
    args: argparse.Namespace,
) -> pd.DataFrame:
    api: NativeAPI = context["api"]
    material = dict(context["material"])
    base = context["base"]
    basis = context["basis"]
    v2 = context["v2"]
    v2_config = context["v2_config"]

    receiver_activity = args.diffusivity_receiver_activity
    voltage = args.diffusivity_voltage_v
    diffusivities = np.asarray(
        [1e-14, 1e-13, 1e-12, 1e-11, 1e-10, 1e-9], dtype=float
    )

    rows: list[dict[str, Any]] = []
    for diffusivity in diffusivities:
        tested = dict(material)
        tested["water_diffusivity_m2_s"] = float(diffusivity)
        local = api.solve_local_state(
            v2=v2,
            v2_config=v2_config,
            material=tested,
            source_temperature_c=float(basis.inlet_temperature_c),
            source_humidity_ratio=float(basis.inlet_humidity_ratio_kg_kg_da),
            receiver_activity=float(receiver_activity),
            terminal_voltage_v=float(voltage),
            fixed_loss_voltage_v=0.0,
            series_asr_ohm_m2=float(args.series_asr_ohm_m2),
            film_scale_factor=1.0,
            process_film_scale_factor=1.0,
            receiver_film_scale_factor=1.0,
            config=base,
        )
        row = {
            "water_diffusivity_m2_s": diffusivity,
            "solution_ok": bool(local.get("solution_ok", False)),
            "solution_status": str(local.get("solution_status", "")),
            "terminal_voltage_v": voltage,
            "receiver_activity": receiver_activity,
        }
        for name in (
            "current_density_a_m2",
            "eo_flux_mol_m2_s",
            "diffusion_flux_mol_m2_s",
            "net_flux_mol_m2_s",
            "ohmic_voltage_v",
            "water_polarisation_voltage_v",
            "series_loss_voltage_v",
            "source_surface_activity",
            "receiver_surface_activity",
            "source_bulk_activity",
        ):
            row[name] = finite(local.get(name))
        eo_flux = row["eo_flux_mol_m2_s"]
        diffusion = row["diffusion_flux_mol_m2_s"]
        row["absolute_diffusion_to_eo_ratio"] = (
            abs(diffusion) / abs(eo_flux)
            if math.isfinite(eo_flux) and abs(eo_flux) > 0.0
            else math.nan
        )
        rows.append(row)
    return pd.DataFrame(rows)


def liquid_local_upper_bound(
    *,
    context: dict[str, Any],
    args: argparse.Namespace,
) -> pd.DataFrame:
    api: NativeAPI = context["api"]
    material = context["material"]
    basis = context["basis"]
    v2 = context["v2"]
    v2_config = context["v2_config"]
    base = context["base"]
    target = context["targets"][args.target]

    water_load_kg_h = float(target["computed_water_load_kg_h"])
    molar_load_mol_s = water_load_kg_h / WATER_MOLAR_MASS_KG_MOL / 3600.0

    if args.smoke:
        activities = np.asarray([0.2, 0.7, 0.95, 0.999999])
        voltages = np.asarray([0.5, 1.0, 2.0, 5.0, 10.0, 20.0])
    else:
        activities = np.asarray(
            [0.05, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 0.95, 0.99, 0.999999]
        )
        voltages = np.unique(
            np.concatenate(
                [
                    np.geomspace(0.05, 2.0, 18),
                    np.linspace(2.5, args.voltage_cap_v, 18),
                ]
            )
        )

    pump_kw = (
        (water_load_kg_h / 3600.0)
        * args.liquid_pump_pressure_pa
        / args.liquid_density_kg_m3
        / args.liquid_pump_efficiency
        / 1000.0
    )
    condensation_heat_kw = (
        water_load_kg_h * LATENT_HEAT_KJ_KG_32C / 3600.0
    )

    rows: list[dict[str, Any]] = []
    for activity in activities:
        for voltage in voltages:
            local = api.solve_local_state(
                v2=v2,
                v2_config=v2_config,
                material=dict(material),
                source_temperature_c=float(basis.inlet_temperature_c),
                source_humidity_ratio=float(basis.inlet_humidity_ratio_kg_kg_da),
                receiver_activity=float(activity),
                terminal_voltage_v=float(voltage),
                fixed_loss_voltage_v=0.0,
                series_asr_ohm_m2=float(args.series_asr_ohm_m2),
                film_scale_factor=1.0,
                process_film_scale_factor=1.0,
                receiver_film_scale_factor=float(args.liquid_interface_factor),
                config=base,
            )

            flux = finite(local.get("net_flux_mol_m2_s"))
            current = finite(local.get("current_density_a_m2"))
            solution_ok = bool(local.get("solution_ok", False))
            if solution_ok and flux > 0.0 and current > 0.0:
                area = molar_load_mol_s / flux
                cell_kw = voltage * current * area / 1000.0
                eo_grid_kw = cell_kw / args.power_electronics_efficiency
                try:
                    process = api.process_channel_fan(
                        active_area_m2=area,
                        config=base,
                        basis=basis,
                    )
                    process_fan_kw = float(process["process_fan_power_kw"])
                except Exception:
                    process_fan_kw = math.nan
            else:
                area = math.nan
                eo_grid_kw = math.nan
                process_fan_kw = math.nan

            heat_rejection_kw = condensation_heat_kw / args.heat_rejection_cop
            gravity_upper_kw = eo_grid_kw + process_fan_kw
            gravity_heat_rejection_kw = gravity_upper_kw + heat_rejection_kw
            pumped_heat_rejection_kw = gravity_heat_rejection_kw + pump_kw

            if not solution_ok:
                bottleneck = "local_solver_or_activity_state"
            elif not math.isfinite(flux) or flux <= 0.0:
                bottleneck = "nonpositive_net_flux"
            elif current > args.current_cap_a_m2:
                bottleneck = "current_density_cap"
            elif area > args.area_cap_m2:
                bottleneck = "active_area_cap"
            elif voltage > args.voltage_cap_v:
                bottleneck = "terminal_voltage_cap"
            elif activity >= 0.95:
                bottleneck = "liquid_activity_chemical_potential"
            else:
                bottleneck = "no_declared_hard_gate"

            rows.append(
                {
                    "target": args.target,
                    "liquid_activity": activity,
                    "terminal_voltage_v": voltage,
                    "liquid_interface_factor": args.liquid_interface_factor,
                    "solution_ok": solution_ok,
                    "solution_status": str(local.get("solution_status", "")),
                    "net_flux_mol_m2_s": flux,
                    "current_density_a_m2": current,
                    "required_uniform_flux_area_m2": area,
                    "eo_grid_power_kw": eo_grid_kw,
                    "process_fan_power_kw": process_fan_kw,
                    "pump_power_kw": pump_kw,
                    "condensation_heat_kw": condensation_heat_kw,
                    "heat_rejection_power_kw": heat_rejection_kw,
                    "gravity_free_heat_sink_total_kw": gravity_upper_kw,
                    "gravity_with_heat_rejection_total_kw": gravity_heat_rejection_kw,
                    "pumped_with_heat_rejection_total_kw": pumped_heat_rejection_kw,
                    "source_surface_activity": finite(
                        local.get("source_surface_activity")
                    ),
                    "receiver_surface_activity": finite(
                        local.get("receiver_surface_activity")
                    ),
                    "water_polarisation_voltage_v": finite(
                        local.get("water_polarisation_voltage_v")
                    ),
                    "ohmic_voltage_v": finite(local.get("ohmic_voltage_v")),
                    "limiting_mechanism": bottleneck,
                    "screening_caveat": (
                        "Uniform-inlet-flux area upper-bound; not a full axial "
                        "liquid-film, drainage, flooding or thermal model."
                    ),
                }
            )
    return pd.DataFrame(rows)


def direct_liquid_output_summary(path: Path | None) -> pd.DataFrame:
    if path is None:
        return pd.DataFrame()
    frame = read_table(path)
    if frame.empty:
        return frame

    activity_col = first_existing(
        frame, ["liquid_activity", "receiver_liquid_activity", "liquid_water_activity"]
    )
    power_col = first_existing(
        frame,
        [
            "free_liquid_removal_power_kw",
            "predryer_core_power_kw",
            "analysis_core_power_kw",
        ],
    )
    target_col = first_existing(frame, ["target"])
    pass_col = first_existing(frame, ["analysis_pass", "target_reached"])
    if activity_col is None or power_col is None:
        return pd.DataFrame()

    working = frame.copy()
    working["_activity"] = pd.to_numeric(working[activity_col], errors="coerce")
    working["_power"] = pd.to_numeric(working[power_col], errors="coerce")
    if pass_col:
        working["_pass"] = working[pass_col].map(truth)
    else:
        working["_pass"] = True

    group_cols = ["_activity"]
    if target_col:
        group_cols.insert(0, target_col)

    rows = []
    for keys, group in working.groupby(group_cols, dropna=False):
        passing = group[group["_pass"]]
        source = passing if not passing.empty else group
        best = source.sort_values("_power", kind="mergesort").iloc[0]
        record = {
            "activity": float(best["_activity"]),
            "minimum_power_kw": float(best["_power"]),
            "any_passing_case": bool(group["_pass"].any()),
            "source_path": str(path),
        }
        if target_col:
            if isinstance(keys, tuple):
                record["target"] = str(keys[0])
            else:
                record["target"] = str(best[target_col])
        rows.append(record)
    return pd.DataFrame(rows)


def geometry_sweep(
    *,
    context: dict[str, Any],
    args: argparse.Namespace,
) -> pd.DataFrame:
    api = context["api"]
    basis = context["basis"]
    gas_row = selected_row(context["paths"]["gas_o30"], args.target)
    area = first_finite(
        gas_row,
        ["required_active_area_m2"],
        args.area_cap_m2,
    )
    humidity_ratio = float(basis.inlet_humidity_ratio_kg_kg_da)

    if args.smoke:
        widths = [0.5, 1.0]
        counts = [1000, 5000, 10000]
        gaps_mm = [1.0, 4.0, 8.0]
    else:
        widths = [0.5, 0.75, 1.0, 1.5, 2.0]
        counts = [100, 250, 500, 1000, 2000, 5000, 10000, 20000]
        gaps_mm = [1.0, 2.0, 4.0, 6.0, 8.0, 10.0]

    rows: list[dict[str, Any]] = []
    for width in widths:
        for count in counts:
            total_width = width * count
            for gap_mm in gaps_mm:
                gap = gap_mm / 1000.0
                velocity = basis.volume_flow_m3_s / max(total_width * gap, EPS)
                for active_sides in (1.0, 2.0):
                    try:
                        result = api.channel_pressure_drop_and_fan(
                            axial=None,
                            active_area_m2=area,
                            total_channel_width_m=total_width,
                            active_sides=active_sides,
                            gap_m=gap,
                            velocity_m_s=velocity,
                            volume_flow_m3_s=float(basis.volume_flow_m3_s),
                            temperature_c=float(basis.inlet_temperature_c),
                            pressure_pa=float(basis.absolute_pressure_pa),
                            humidity_ratio_kg_kg_da=humidity_ratio,
                            fan_efficiency=args.process_fan_efficiency,
                        )
                    except Exception:
                        continue

                    length = float(result["channel_length_m"])
                    open_volume = total_width * gap * length
                    feasible = (
                        args.minimum_channel_velocity_m_s
                        <= velocity
                        <= args.maximum_channel_velocity_m_s
                        and length <= args.maximum_channel_length_m
                        and float(result["channel_pressure_drop_pa"])
                        <= args.maximum_channel_pressure_drop_pa
                    )
                    rows.append(
                        {
                            "active_area_m2": area,
                            "channel_width_per_parallel_path_m": width,
                            "parallel_path_count": count,
                            "total_channel_width_m": total_width,
                            "channel_gap_mm": gap_mm,
                            "active_sides": active_sides,
                            "channel_velocity_m_s": velocity,
                            "channel_length_m": length,
                            "channel_pressure_drop_pa": float(
                                result["channel_pressure_drop_pa"]
                            ),
                            "channel_fan_power_kw": float(
                                result["channel_fan_power_kw"]
                            ),
                            "open_channel_volume_m3": open_volume,
                            "geometry_feasible": feasible,
                        }
                    )
    return pd.DataFrame(rows)


def power_ledger(
    *,
    gas_row: Mapping[str, Any],
    break_even: pd.DataFrame,
    liquid_upper: pd.DataFrame,
    args: argparse.Namespace,
) -> pd.DataFrame:
    water_load = args.o30_water_load_kg_h
    rows = [
        {
            "scenario": "gas_receiver_o30_core",
            "eo_grid_kw": first_finite(gas_row, ["eo_grid_power_kw"], 70.69),
            "process_fan_kw": first_finite(
                gas_row, ["process_channel_fan_power_kw"], 6.16
            ),
            "receiver_fan_kw": first_finite(
                gas_row, ["receiver_channel_fan_power_kw"], 38.17
            ),
            "pump_kw": 0.0,
            "heat_rejection_kw": 0.0,
            "controls_kw": args.controls_power_kw,
            "grid_to_device_efficiency": args.grid_to_device_efficiency,
            "water_load_kg_h": water_load,
        }
    ]

    if not liquid_upper.empty:
        valid = liquid_upper.replace([np.inf, -np.inf], np.nan).dropna(
            subset=["gravity_free_heat_sink_total_kw"]
        )
        if not valid.empty:
            best = valid.sort_values("gravity_free_heat_sink_total_kw").iloc[0]
            for scenario, column in (
                ("liquid_gravity_free_heat_sink", "gravity_free_heat_sink_total_kw"),
                (
                    "liquid_gravity_with_heat_rejection",
                    "gravity_with_heat_rejection_total_kw",
                ),
                (
                    "liquid_pumped_with_heat_rejection",
                    "pumped_with_heat_rejection_total_kw",
                ),
            ):
                total = float(best[column])
                rows.append(
                    {
                        "scenario": scenario,
                        "eo_grid_kw": float(best["eo_grid_power_kw"]),
                        "process_fan_kw": float(best["process_fan_power_kw"]),
                        "receiver_fan_kw": 0.0,
                        "pump_kw": (
                            float(best["pump_power_kw"])
                            if "pumped" in scenario
                            else 0.0
                        ),
                        "heat_rejection_kw": (
                            float(best["heat_rejection_power_kw"])
                            if "heat_rejection" in scenario
                            else 0.0
                        ),
                        "controls_kw": args.controls_power_kw,
                        "grid_to_device_efficiency": args.grid_to_device_efficiency,
                        "water_load_kg_h": water_load,
                        "liquid_activity": float(best["liquid_activity"]),
                        "terminal_voltage_v": float(best["terminal_voltage_v"]),
                    }
                )

    frame = pd.DataFrame(rows)
    component_cols = [
        "eo_grid_kw",
        "process_fan_kw",
        "receiver_fan_kw",
        "pump_kw",
        "heat_rejection_kw",
        "controls_kw",
    ]
    frame["device_total_kw"] = frame[component_cols].sum(axis=1)
    frame["site_total_kw"] = (
        frame["device_total_kw"] / frame["grid_to_device_efficiency"]
    )
    frame["grid_conversion_loss_kw"] = (
        frame["site_total_kw"] - frame["device_total_kw"]
    )
    frame["sec_kwh_kg"] = frame["site_total_kw"] / frame["water_load_kg_h"]
    return frame


def foms(
    *,
    ledger: pd.DataFrame,
    args: argparse.Namespace,
) -> pd.DataFrame:
    rows = []
    baseline_site = args.baseline_compressor_kw / args.grid_to_device_efficiency
    gross = args.baseline_compressor_kw - args.o30_compressor_kw

    for _, row in ledger.iterrows():
        total = float(row["site_total_kw"])
        water = float(row["water_load_kg_h"])
        combined = args.o30_compressor_kw / args.grid_to_device_efficiency + total
        net_saving = baseline_site - combined
        rows.append(
            {
                "scenario": row["scenario"],
                "pre_dryer_sec_kwh_kg": total / water,
                "pre_dryer_kg_per_kwh": water / total if total > 0 else math.inf,
                "combined_site_power_kw": combined,
                "net_saving_kw": net_saving,
                "net_saving_pct": 100.0 * net_saving / baseline_site,
                "same_service_cop_ratio_vs_baseline": (
                    baseline_site / combined if combined > 0 else math.inf
                ),
                "annual_energy_saving_kwh": net_saving * args.annual_hours,
                "annual_cost_saving_chf": (
                    net_saving * args.annual_hours * args.electricity_price_chf_kwh
                ),
                "gross_no_erv_opportunity_kw": gross,
            }
        )
    return pd.DataFrame(rows)



def industry_benchmarks(
    *,
    break_even: pd.DataFrame,
    ledger: pd.DataFrame,
) -> pd.DataFrame:
    """Return external and internal benchmarks with explicit boundary caveats."""

    current_core = ledger[
        ledger["scenario"].eq("gas_receiver_o30_core")
    ].iloc[0]

    gross = break_even[
        break_even["boundary"].eq("legacy_no_erv_gross_compressor")
    ].iloc[0]

    rows = [
        {
            "benchmark": "ASHRAE fixed-plate exchanger",
            "metric": "typical sensible effectiveness",
            "lower_value": 0.50,
            "upper_value": 0.75,
            "unit": "fraction",
            "source": "ASHRAE Handbook 2024, Chapter 26",
            "comparison_status": "official exchanger-level range",
            "caveat": "Not a generic whole-building annual saving percentage.",
        },
        {
            "benchmark": "ASHRAE membrane-plate exchanger",
            "metric": "typical latent effectiveness",
            "lower_value": 0.25,
            "upper_value": 0.60,
            "unit": "fraction",
            "source": "ASHRAE Handbook 2024, Chapter 26",
            "comparison_status": "official exchanger-level range",
            "caveat": "Actual rating must come from manufacturer/AHRI data at the duty point.",
        },
        {
            "benchmark": "ASHRAE energy wheel",
            "metric": "typical latent effectiveness",
            "lower_value": 0.50,
            "upper_value": 0.80,
            "unit": "fraction",
            "source": "ASHRAE Handbook 2024, Chapter 26",
            "comparison_status": "official exchanger-level range",
            "caveat": "EATR, OACF, pressure drop and wheel motor must also be specified.",
        },
        {
            "benchmark": "AirJoule company-reported water separation",
            "metric": "reported water-production energetics",
            "lower_value": math.nan,
            "upper_value": 160.0,
            "unit": "Wh/L",
            "source": "AirJoule FY2024 results release, 25 March 2025",
            "comparison_status": "company-reported; not independent validation",
            "caveat": (
                "Atmospheric-water-harvesting claim, not a generic HVAC saving and "
                "not the same boundary as XMembrane pre-drying."
            ),
        },
        {
            "benchmark": "XMembrane gas-receiver O30 core",
            "metric": "modeled pre-dryer SEC",
            "lower_value": 1000.0 * float(current_core["sec_kwh_kg"]),
            "upper_value": 1000.0 * float(current_core["sec_kwh_kg"]),
            "unit": "Wh/kg water",
            "source": "current internal native-model output",
            "comparison_status": "conditional model result",
            "caveat": "Receiver regeneration and unmodeled balance of plant remain open.",
        },
        {
            "benchmark": "Legacy no-ERV O30 break-even",
            "metric": "gross all-in pre-dryer allowance",
            "lower_value": float(gross["break_even_wh_l_approx"]),
            "upper_value": float(gross["break_even_wh_l_approx"]),
            "unit": "Wh/L approx",
            "source": "1167.33-382.44 kW divided by modeled O30 water duty",
            "comparison_status": "conditional arithmetic boundary",
            "caveat": "Not an ERV-adjusted, thermodynamic or universal break-even.",
        },
    ]
    return pd.DataFrame(rows)


def grid_loss_sensitivity(
    *,
    ledger: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for efficiency in (0.95, 0.97, 0.98, 0.99, 1.00):
        for _, case in ledger.iterrows():
            device_kw = float(case["device_total_kw"])
            site_kw = device_kw / efficiency
            rows.append(
                {
                    "scenario": case["scenario"],
                    "grid_to_device_efficiency": efficiency,
                    "device_bus_power_kw": device_kw,
                    "site_input_power_kw": site_kw,
                    "conversion_and_distribution_loss_kw": site_kw - device_kw,
                    "loss_fraction_of_site_input": 1.0 - efficiency,
                    "interpretation": (
                        "Sensitivity only. Replace with transformer, converter, cable and "
                        "part-load data for the selected electrical architecture."
                    ),
                }
            )
    return pd.DataFrame(rows)


def enclosure_foms(
    *,
    api: NativeAPI,
    capacity_kg_h: float,
    args: argparse.Namespace,
) -> pd.DataFrame:
    pressure = float(args.pressure_pa)
    ambient_w = api.humidity_ratio_from_t_rh(
        args.enclosure_ambient_temperature_c,
        args.enclosure_ambient_rh,
        pressure,
    )
    target_w = api.humidity_ratio_from_t_rh(
        args.enclosure_target_temperature_c,
        args.enclosure_target_rh,
        pressure,
    )
    vapour_pressure = api.vapour_pressure_from_humidity_ratio(target_w, pressure)
    dry_air_density = (
        (pressure - vapour_pressure)
        / (R_DRY_AIR_J_KG_K * (args.enclosure_target_temperature_c + 273.15))
    )
    delta_w = max(ambient_w - target_w, 0.0)
    infiltration_load = (
        dry_air_density
        * args.enclosure_volume_m3
        * args.enclosure_air_changes_per_h
        * delta_w
    )
    total_load = infiltration_load + args.enclosure_internal_moisture_kg_h
    margin = capacity_kg_h - total_load
    denominator = (
        dry_air_density
        * args.enclosure_air_changes_per_h
        * delta_w
    )
    protected_volume = (
        (capacity_kg_h - args.enclosure_internal_moisture_kg_h) / denominator
        if denominator > 0.0
        and capacity_kg_h > args.enclosure_internal_moisture_kg_h
        else math.nan
    )
    return pd.DataFrame(
        [
            {
                "ambient_temperature_c": args.enclosure_ambient_temperature_c,
                "ambient_rh": args.enclosure_ambient_rh,
                "target_temperature_c": args.enclosure_target_temperature_c,
                "target_rh": args.enclosure_target_rh,
                "enclosure_volume_m3": args.enclosure_volume_m3,
                "air_changes_per_h": args.enclosure_air_changes_per_h,
                "internal_moisture_kg_h": args.enclosure_internal_moisture_kg_h,
                "module_capacity_kg_h": capacity_kg_h,
                "steady_moisture_load_kg_h": total_load,
                "capacity_margin_kg_h": margin,
                "humidity_control_pass": margin >= 0.0,
                "maximum_protected_volume_m3": protected_volume,
                "method": "steady-state well-mixed enclosure screen",
                "caveat": (
                    "No transient sorption, door openings, weather series, spatial gradients "
                    "or control cycling."
                ),
            }
        ]
    )


def complete_system_power_ledger(
    *,
    erv: pd.DataFrame,
    incremental: pd.DataFrame,
    predryer_ledger: pd.DataFrame,
    args: argparse.Namespace,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    baseline_site = args.baseline_compressor_kw / args.grid_to_device_efficiency

    rows.append(
        {
            "system": "conventional_AC_no_ERV",
            "technology": "baseline",
            "rating_point": "declared",
            "compressor_site_kw": baseline_site,
            "erv_fan_site_kw": 0.0,
            "eo_predryer_site_kw": 0.0,
            "other_site_kw": 0.0,
            "total_site_kw": baseline_site,
            "saving_vs_no_erv_kw": 0.0,
            "saving_vs_no_erv_pct": 0.0,
            "boundary": "compressor-only anchor plus declared conversion boundary",
        }
    )

    for _, row in erv.iterrows():
        total = float(row["site_power_kw"])
        rows.append(
            {
                "system": "AC_plus_ERV",
                "technology": row["technology"],
                "rating_point": row["rating_point"],
                "compressor_site_kw": (
                    float(row["compressor_power_kw"])
                    / args.grid_to_device_efficiency
                ),
                "erv_fan_site_kw": (
                    float(row["erv_fan_power_kw"])
                    / args.grid_to_device_efficiency
                ),
                "eo_predryer_site_kw": 0.0,
                "other_site_kw": float(row["grid_conversion_loss_kw"]),
                "total_site_kw": total,
                "saving_vs_no_erv_kw": baseline_site - total,
                "saving_vs_no_erv_pct": 100.0 * (baseline_site - total) / baseline_site,
                "boundary": "ERV-only design-point comparison",
            }
        )

    downstream_site = args.o30_compressor_kw / args.grid_to_device_efficiency
    for _, row in predryer_ledger.iterrows():
        predryer_site = float(row["site_total_kw"])
        total = downstream_site + predryer_site
        rows.append(
            {
                "system": "EO_enhanced_no_ERV",
                "technology": row["scenario"],
                "rating_point": "declared_O30",
                "compressor_site_kw": downstream_site,
                "erv_fan_site_kw": 0.0,
                "eo_predryer_site_kw": predryer_site,
                "other_site_kw": 0.0,
                "total_site_kw": total,
                "saving_vs_no_erv_kw": baseline_site - total,
                "saving_vs_no_erv_pct": 100.0 * (baseline_site - total) / baseline_site,
                "boundary": "EO system reported separately from ERV",
            }
        )

    selected = incremental[
        incremental["reduction_definition"].eq("10pct_post_erv")
    ].copy()
    for _, row in selected.iterrows():
        required = finite(row["required_additional_water_transport_kg_h"])
        if not math.isfinite(required):
            continue
        erv_match = erv[
            erv["technology"].eq(row["technology"])
            & erv["rating_point"].eq(row["erv_rating_point"])
        ]
        if erv_match.empty:
            continue
        erv_row = erv_match.iloc[0]
        compressor_reduction = float(row["gross_compressor_site_reduction_kw"])
        eo_site = float(row["additional_eo_site_power_kw"])
        total = float(erv_row["site_power_kw"]) - compressor_reduction + eo_site
        rows.append(
            {
                "system": "ERV_plus_incremental_EO",
                "technology": row["technology"],
                "rating_point": (
                    str(row["erv_rating_point"])
                    + "+"
                    + str(row["eo_boundary"])
                ),
                "compressor_site_kw": (
                    float(erv_row["compressor_power_kw"])
                    / args.grid_to_device_efficiency
                    - compressor_reduction
                ),
                "erv_fan_site_kw": (
                    float(erv_row["erv_fan_power_kw"])
                    / args.grid_to_device_efficiency
                ),
                "eo_predryer_site_kw": eo_site,
                "other_site_kw": 0.0,
                "total_site_kw": total,
                "saving_vs_no_erv_kw": baseline_site - total,
                "saving_vs_no_erv_pct": 100.0 * (baseline_site - total) / baseline_site,
                "additional_water_transport_kg_h": required,
                "boundary": "Linearized ERV+EO screen; exhaust resource must be allocated once.",
            }
        )

    return pd.DataFrame(rows)


def unified_fom_register(
    *,
    gas_row: Mapping[str, Any],
    ledger: pd.DataFrame,
    geometry: pd.DataFrame,
    enclosure: pd.DataFrame,
    context: Mapping[str, Any],
    args: argparse.Namespace,
) -> pd.DataFrame:
    case = ledger[ledger["scenario"].eq("gas_receiver_o30_core")].iloc[0]
    water = float(case["water_load_kg_h"])
    area = first_finite(gas_row, ["required_active_area_m2"], args.area_cap_m2)
    site_predryer = float(case["site_total_kw"])
    baseline_site = args.baseline_compressor_kw / args.grid_to_device_efficiency
    downstream_site = args.o30_compressor_kw / args.grid_to_device_efficiency
    combined_site = downstream_site + site_predryer
    net_saving = baseline_site - combined_site
    service_kw = args.baseline_compressor_kw * args.cooling_cop

    api: NativeAPI = context["api"]
    basis = context["basis"]
    supply_w = api.humidity_ratio_from_t_rh(
        args.supply_temperature_c,
        args.supply_rh,
        args.pressure_pa,
    )
    total_process_water = (
        basis.dry_air_mass_flow_kg_s
        * (basis.inlet_humidity_ratio_kg_kg_da - supply_w)
        * 3600.0
    )

    feasible_geometry = geometry[geometry["geometry_feasible"]]
    if feasible_geometry.empty:
        package_volume = math.nan
        mrd = math.nan
    else:
        selected_geometry = feasible_geometry.sort_values(
            ["channel_fan_power_kw", "open_channel_volume_m3"],
            kind="mergesort",
        ).iloc[0]
        package_volume = float(selected_geometry["open_channel_volume_m3"])
        mrd = 24.0 * water / (1000.0 * package_volume) if package_volume > 0 else math.nan

    enclosure_row = enclosure.iloc[0]
    values: dict[str, tuple[Any, str, str]] = {
        "FOM-01": (
            water / area if area > 0 else math.nan,
            "kg m-2 h-1",
            "calculated",
        ),
        "FOM-02": (site_predryer / water, "kWh/kg water", "calculated site boundary"),
        "FOM-03": (mrd, "kg day-1 L-1", "geometry proxy"),
        "FOM-04": (
            combined_site / total_process_water,
            "kWh/kg total process water",
            "conditional system model",
        ),
        "FOM-05": (
            100.0 * (baseline_site / combined_site - 1.0),
            "%",
            "constant-service ratio",
        ),
        "FOM-06": (100.0 * net_saving / baseline_site, "%", "design-point conditional"),
        "FOM-07": (
            bool(enclosure_row["humidity_control_pass"]),
            "boolean",
            "steady-state enclosure screen",
        ),
        "FOM-08": (
            float(enclosure_row["maximum_protected_volume_m3"]),
            "m3",
            "steady-state enclosure screen",
        ),
        "FOM-09": (math.nan, "K", "not available: evaporator state model required"),
        "FOM-10": (
            args.baseline_compressor_kw - args.o30_compressor_kw,
            "kW",
            "declared compressor anchors",
        ),
        "FOM-11": (
            service_kw / combined_site,
            "-",
            "conditional same-service COP proxy",
        ),
        "FOM-12": (
            100.0 * (baseline_site / combined_site - 1.0),
            "%",
            "conditional same-service COP ratio",
        ),
        "FOM-13": (
            combined_site / total_process_water,
            "kWh/kg total process water",
            "conditional system model",
        ),
        "FOM-14": (net_saving, "kW", "conditional site peak-power reduction"),
        "FOM-15": (
            net_saving * args.annual_hours,
            "kWh/year",
            "equivalent-full-load-hours estimate",
        ),
        "FOM-16": (
            net_saving * args.annual_hours * args.electricity_price_chf_kwh,
            "CHF/year",
            "equivalent-full-load-hours estimate",
        ),
        "FOM-17": (math.nan, "years", "not available: CAPEX and maintenance missing"),
        "FOM-18": (
            (args.baseline_compressor_kw - args.o30_compressor_kw) / water,
            "kWh/kg water",
            "legacy no-ERV conditional break-even",
        ),
    }

    names = {
        "FOM-01": "Water-removal flux",
        "FOM-02": "Pre-dryer SEC",
        "FOM-03": "Moisture-removal density",
        "FOM-04": "Combined HVAC-system SEC",
        "FOM-05": "HVAC COP improvement",
        "FOM-06": "Energy saving",
        "FOM-07": "Humidity-control capability",
        "FOM-08": "Protected volume",
        "FOM-09": "Evaporating-temperature increase",
        "FOM-10": "AC peak-power reduction",
        "FOM-11": "Combined-system COP",
        "FOM-12": "Combined COP improvement",
        "FOM-13": "Combined-system SEC",
        "FOM-14": "Net site peak-power reduction",
        "FOM-15": "Annual energy saving",
        "FOM-16": "Annual energy-cost saving",
        "FOM-17": "Payback period",
        "FOM-18": "Break-even all-in EO SEC",
    }

    rows: list[dict[str, Any]] = []
    for fom_id in [f"FOM-{index:02d}" for index in range(1, 19)]:
        value, unit, method = values[fom_id]
        available = not (
            isinstance(value, float) and math.isnan(value)
        )
        rows.append(
            {
                "fom_id": fom_id,
                "name": names[fom_id],
                "numeric_value": value if not isinstance(value, bool) else math.nan,
                "text_value": str(value) if isinstance(value, bool) else "",
                "unit": unit,
                "status": "reported" if available else "not_available",
                "method_classification": method,
                "operating_point": (
                    f"{args.process_airflow_cfm:g} cfm; "
                    f"{args.outdoor_temperature_c:g} C/{100*args.outdoor_rh:g}% RH; "
                    f"target {args.target}"
                ),
                "energy_boundary": "site input using declared grid-to-device efficiency",
                "active_area_m2": area,
                "maximum_current_density_a_m2": first_finite(
                    gas_row,
                    ["maximum_local_current_density_a_m2"],
                ),
                "integrated_current_a": first_finite(gas_row, ["integrated_current_a"]),
                "package_volume_proxy_m3": package_volume,
                "claim_caveat": (
                    "Calculated availability does not by itself validate a commercial claim."
                ),
            }
        )
    return pd.DataFrame(rows)

def conditions_table(
    *,
    context: dict[str, Any],
    args: argparse.Namespace,
) -> pd.DataFrame:
    material = context["material"]
    rows = [
        ("Process airflow", args.process_airflow_cfm, "cfm", "actual inlet basis"),
        ("Outdoor/process inlet", args.outdoor_temperature_c, "degC", f"RH={args.outdoor_rh:.2f}"),
        ("Return air", args.return_temperature_c, "degC", f"RH={args.return_rh:.2f}"),
        ("Supply target", args.supply_temperature_c, "degC", f"RH={args.supply_rh:.2f}"),
        ("Active membrane area cap", args.area_cap_m2, "m2", "hard screening gate"),
        ("Terminal voltage cap", args.voltage_cap_v, "V", "hard screening gate"),
        ("Current-density cap", args.current_cap_a_m2, "A/m2", "hard screening gate"),
        ("Grid-to-device efficiency", args.grid_to_device_efficiency, "-", "screening sensitivity"),
        ("Water drag", material["water_drag"], "-", "selected inverse-design coordinate"),
        ("Water diffusivity", material["water_diffusivity_m2_s"], "m2/s", "selected inverse-design coordinate"),
        ("Conductivity", material["conductivity_s_m"], "S/m", "selected inverse-design coordinate"),
        ("Dry thickness", material["dry_thickness_um"], "um", "selected inverse-design coordinate"),
    ]
    return pd.DataFrame(rows, columns=["condition", "value", "unit", "interpretation"])


def terminology_table() -> pd.DataFrame:
    rows = [
        ("EO", "electro-osmosis", "Charge-coupled water transport through the membrane."),
        ("ERV", "energy recovery ventilator", "Transfers sensible and usually latent energy between exhaust and outdoor air."),
        ("HRV", "heat recovery ventilator", "Sensible-only air-to-air recovery device."),
        ("water activity", "a_w", "Dimensionless chemical-potential state; not identical to water concentration."),
        ("humidity ratio", "w", "kg water vapour per kg dry air."),
        ("gas-film coefficient", "K", "Bulk-to-surface mass-transfer coefficient expressed on water-activity basis."),
        ("transport number / water drag", "t_w or n_d", "Model water-per-charge parameter."),
        ("SEC", "specific energy consumption", "Electric energy per unit water removed, kWh/kg."),
        ("core power", "P_core", "Declared EO/fan subsystem power; excludes unspecified balance of plant."),
        ("site power", "P_site", "Upstream electrical input including configured conversion loss."),
        ("gross HVAC opportunity", "Delta P_gross", "Compressor reduction before pre-dryer and auxiliary penalties."),
        ("break-even SEC", "SEC_BE", "Available gross power divided by water-removal duty under one fixed boundary."),
    ]
    return pd.DataFrame(rows, columns=["term", "symbol_or_expansion", "definition"])


def save_plot(path: Path, figure: plt.Figure) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.tight_layout()
    figure.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(figure)


def make_plots(
    *,
    out: Path,
    erv: pd.DataFrame,
    incremental: pd.DataFrame,
    diffusivity: pd.DataFrame,
    liquid_upper: pd.DataFrame,
    geometry: pd.DataFrame,
) -> None:
    fig, ax = plt.subplots(figsize=(8, 5))
    for technology, group in erv.groupby("technology"):
        ordered = group.sort_values("latent_effectiveness")
        ax.plot(
            ordered["latent_effectiveness"],
            ordered["saving_pct_of_baseline"],
            marker="o",
            label=technology,
        )
    ax.set_xlabel("Latent effectiveness [-]")
    ax.set_ylabel("Design-point site-power saving [%]")
    ax.set_title("ERV industry envelope applied to the declared duty point")
    ax.grid(True, alpha=0.3)
    ax.legend()
    save_plot(out / "figures/erv_industry_comparison.png", fig)

    if not incremental.empty:
        subset = incremental[
            incremental["reduction_definition"].eq("10pct_post_erv")
        ].replace([np.inf, -np.inf], np.nan).dropna(
            subset=["required_additional_water_transport_kg_h"]
        )
        if not subset.empty:
            fig, ax = plt.subplots(figsize=(9, 5))
            labels = (
                subset["technology"].astype(str)
                + "\n"
                + subset["erv_rating_point"].astype(str)
                + "\n"
                + subset["eo_boundary"].astype(str)
            )
            ax.bar(np.arange(len(subset)), subset["required_additional_water_transport_kg_h"])
            ax.set_xticks(np.arange(len(subset)), labels, rotation=60, ha="right")
            ax.set_ylabel("Additional EO water transport [kg/h]")
            ax.set_title("EO transport required for a further 10% post-ERV reduction")
            ax.grid(True, axis="y", alpha=0.3)
            save_plot(out / "figures/erv_plus_eo_10pct.png", fig)

    if not diffusivity.empty:
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.semilogx(
            diffusivity["water_diffusivity_m2_s"],
            diffusivity["absolute_diffusion_to_eo_ratio"],
            marker="o",
        )
        ax.set_xlabel("Water diffusivity D0 [m2/s]")
        ax.set_ylabel("|diffusion flux| / |EO flux| [-]")
        ax.set_title("Extended diffusivity sensitivity including 1e-10 and 1e-9 m2/s")
        ax.grid(True, which="both", alpha=0.3)
        save_plot(out / "figures/diffusivity_extension.png", fig)

    if not liquid_upper.empty:
        valid = liquid_upper.replace([np.inf, -np.inf], np.nan).dropna(
            subset=["gravity_free_heat_sink_total_kw"]
        )
        if not valid.empty:
            best = (
                valid.sort_values("gravity_free_heat_sink_total_kw")
                .groupby("liquid_activity", as_index=False)
                .first()
                .sort_values("liquid_activity")
            )
            fig, ax = plt.subplots(figsize=(8, 5))
            ax.plot(
                best["liquid_activity"],
                best["gravity_free_heat_sink_total_kw"],
                marker="o",
                label="Gravity, free heat sink (upper bound)",
            )
            ax.plot(
                best["liquid_activity"],
                best["gravity_with_heat_rejection_total_kw"],
                marker="o",
                label="Gravity + heat rejection",
            )
            ax.plot(
                best["liquid_activity"],
                best["pumped_with_heat_rejection_total_kw"],
                marker="o",
                label="Pump + heat rejection",
            )
            ax.set_xlabel("Liquid-side water activity [-]")
            ax.set_ylabel("Predryer power [kW]")
            ax.set_title("Liquid receiver: activity and balance-of-plant penalties")
            ax.grid(True, alpha=0.3)
            ax.legend()
            save_plot(out / "figures/liquid_receiver_bottlenecks.png", fig)

    if not geometry.empty:
        feasible = geometry[geometry["geometry_feasible"]].copy()
        if not feasible.empty:
            fig, ax = plt.subplots(figsize=(8, 5))
            scatter = ax.scatter(
                feasible["open_channel_volume_m3"],
                feasible["channel_fan_power_kw"],
                c=feasible["channel_gap_mm"],
            )
            ax.set_xscale("log")
            ax.set_yscale("log")
            ax.set_xlabel("Open channel volume [m3]")
            ax.set_ylabel("Process fan power [kW]")
            ax.set_title("Width-gap-length geometry trade-off")
            ax.grid(True, which="both", alpha=0.3)
            fig.colorbar(scatter, ax=ax, label="Gap [mm]")
            save_plot(out / "figures/geometry_pareto.png", fig)


def summary_markdown(
    *,
    out: Path,
    break_even: pd.DataFrame,
    erv: pd.DataFrame,
    incremental: pd.DataFrame,
    liquid_upper: pd.DataFrame,
    liquid_existing: pd.DataFrame,
    geometry: pd.DataFrame,
    diffusivity: pd.DataFrame,
    ledger: pd.DataFrame,
) -> str:
    gross = break_even.iloc[0]
    remaining = break_even.iloc[1]
    best_erv = erv.sort_values("site_power_kw").iloc[0]

    lines = [
        "# Trond system-closure study",
        "",
        "## Break-even",
        "",
        (
            f"The legacy no-ERV arithmetic gives "
            f"{gross['break_even_wh_l_approx']:.2f} Wh/L, while the remaining "
            f"allowance after the modeled core is "
            f"{remaining['break_even_wh_l_approx']:.2f} Wh/L."
        ),
        "",
        "This is conditional on one baseline and is not a universal or ERV-adjusted break-even.",
        "",
        "## ERV comparison",
        "",
        (
            f"The lowest design-point site power in the official ASHRAE exchanger envelope "
            f"is {best_erv['site_power_kw']:.2f} kW for "
            f"{best_erv['technology']} ({best_erv['rating_point']})."
        ),
        "",
        "The comparison is based on sensible/latent effectiveness and pressure drop, not generic annual savings percentages.",
        "",
        "## EO after ERV",
        "",
    ]

    feasible_incremental = incremental[
        incremental["feasible_by_available_water"]
    ].replace([np.inf, -np.inf], np.nan).dropna(
        subset=["required_additional_water_transport_kg_h"]
    )
    if feasible_incremental.empty:
        lines.append(
            "No tested linearized EO/ERV combination delivered the requested extra 10% within the available post-ERV moisture."
        )
    else:
        best = feasible_incremental.sort_values(
            "required_additional_water_transport_kg_h"
        ).iloc[0]
        lines.append(
            f"The least additional transport in the linearized screen is "
            f"{best['required_additional_water_transport_kg_h']:.1f} kg/h, "
            f"requiring {best['additional_eo_site_power_kw']:.1f} kW site input "
            f"under the {best['eo_boundary']} boundary."
        )

    lines += [
        "",
        "## Liquid receiver",
        "",
    ]
    valid_liquid = liquid_upper.replace([np.inf, -np.inf], np.nan).dropna(
        subset=["gravity_free_heat_sink_total_kw"]
    )
    if valid_liquid.empty:
        lines.append("No valid liquid-side local upper-bound point was found.")
    else:
        best = valid_liquid.sort_values("gravity_free_heat_sink_total_kw").iloc[0]
        lines.append(
            f"The best gravity/free-heat-sink upper bound is "
            f"{best['gravity_free_heat_sink_total_kw']:.2f} kW at "
            f"a_l={best['liquid_activity']:.3f} and "
            f"{best['terminal_voltage_v']:.3f} V."
        )
        lines.append(
            "Adding mandatory condensation-heat rejection can dominate this upper-bound result."
        )

    if not liquid_existing.empty:
        lines.append(
            f"Existing direct-liquid outputs were also found and summarized "
            f"({len(liquid_existing)} activity/target groups)."
        )

    lines += [
        "",
        "## Geometry",
        "",
    ]
    feasible_geometry = geometry[geometry["geometry_feasible"]]
    if feasible_geometry.empty:
        lines.append("No geometry point passed all declared velocity, length and pressure-drop screens.")
    else:
        compact = feasible_geometry.sort_values(
            ["channel_fan_power_kw", "open_channel_volume_m3"]
        ).iloc[0]
        lines.append(
            f"The lowest-fan feasible geometry uses "
            f"{compact['channel_gap_mm']:.1f} mm gap, "
            f"{compact['parallel_path_count']:.0f} parallel paths and "
            f"{compact['channel_length_m']:.3f} m channel length."
        )

    lines += [
        "",
        "## Diffusivity extension",
        "",
        "The diffusivity sweep explicitly includes D0 = 1e-10 and 1e-9 m2/s.",
        "",
        "## Files",
        "",
        "- `break_even_register.csv`",
        "- `erv_industry_grid.csv`",
        "- `erv_plus_eo_10pct.csv`",
        "- `liquid_local_upper_bound.csv`",
        "- `liquid_existing_output_summary.csv`",
        "- `diffusivity_extension.csv`",
        "- `geometry_sweep.csv`",
        "- `power_ledger.csv`",
        "- `complete_system_power_ledger.csv`",
        "- `systems_reported_separately.csv`",
        "- `figures_of_merit.csv`",
        "- `all_requested_foms.csv`",
        "- `industry_benchmarks.csv`",
        "- `grid_loss_sensitivity.csv`",
        "- `enclosure_foms.csv`",
        "- `selected_reference_case.csv`",
        "- `conditions.csv`",
        "- `terminology.csv`",
        "",
        "## Interpretation limits",
        "",
        "The liquid local model is a screening upper bound. It does not close finite liquid-film transport, capillary drainage, flooding, wet-electrode electrochemistry, corrosion, conjugate heat transfer or durability.",
    ]
    return "\n".join(lines) + "\n"


def write_outputs(
    *,
    out: Path,
    data: Mapping[str, pd.DataFrame],
    summary: str,
) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name, frame in data.items():
        frame.to_csv(out / f"{name}.csv", index=False)
    (out / "summary.md").write_text(summary)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "System-closure study for liquid receiver bottlenecks, ERV comparison, "
            "ERV+EO incremental duty, extended diffusivity and module geometry."
        )
    )
    parser.add_argument("--source-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/trond_system_closure_v1"))
    parser.add_argument("--target", choices=["O30", "O50"], default="O30")
    parser.add_argument("--smoke", action="store_true")

    parser.add_argument("--process-airflow-cfm", type=float, default=150000.0)
    parser.add_argument("--outdoor-temperature-c", type=float, default=32.0)
    parser.add_argument("--outdoor-rh", type=float, default=0.80)
    parser.add_argument("--return-temperature-c", type=float, default=20.0)
    parser.add_argument("--return-rh", type=float, default=0.50)
    parser.add_argument("--supply-temperature-c", type=float, default=20.0)
    parser.add_argument("--supply-rh", type=float, default=0.50)
    parser.add_argument("--pressure-pa", type=float, default=101325.0)
    parser.add_argument("--cooling-cop", type=float, default=4.51)

    parser.add_argument("--baseline-compressor-kw", type=float, default=1167.33)
    parser.add_argument("--o30-compressor-kw", type=float, default=382.44)
    parser.add_argument("--o30-water-load-kg-h", type=float, default=4365.92)
    parser.add_argument("--o30-core-power-kw", type=float, default=115.08)

    parser.add_argument("--grid-to-device-efficiency", type=float, default=0.98)
    parser.add_argument("--power-electronics-efficiency", type=float, default=0.95)
    parser.add_argument("--erv-fan-efficiency", type=float, default=0.65)
    parser.add_argument("--process-fan-efficiency", type=float, default=0.65)
    parser.add_argument("--controls-power-kw", type=float, default=1.0)
    parser.add_argument("--annual-hours", type=float, default=4000.0)
    parser.add_argument("--electricity-price-chf-kwh", type=float, default=0.25)

    parser.add_argument("--area-cap-m2", type=float, default=9000.0)
    parser.add_argument("--voltage-cap-v", type=float, default=24.0)
    parser.add_argument("--current-cap-a-m2", type=float, default=2000.0)
    parser.add_argument("--series-asr-ohm-m2", type=float, default=1.0e-5)
    parser.add_argument("--liquid-interface-factor", type=float, default=1.0e6)
    parser.add_argument("--liquid-pump-pressure-pa", type=float, default=100000.0)
    parser.add_argument("--liquid-pump-efficiency", type=float, default=0.60)
    parser.add_argument("--liquid-density-kg-m3", type=float, default=997.0)
    parser.add_argument("--heat-rejection-cop", type=float, default=6.0)

    parser.add_argument("--diffusivity-voltage-v", type=float, default=0.98)
    parser.add_argument("--diffusivity-receiver-activity", type=float, default=0.40)

    parser.add_argument("--minimum-channel-velocity-m-s", type=float, default=0.5)
    parser.add_argument("--maximum-channel-velocity-m-s", type=float, default=5.0)
    parser.add_argument("--maximum-channel-length-m", type=float, default=5.0)
    parser.add_argument("--maximum-channel-pressure-drop-pa", type=float, default=500.0)

    parser.add_argument("--enclosure-ambient-temperature-c", type=float, default=30.0)
    parser.add_argument("--enclosure-ambient-rh", type=float, default=0.90)
    parser.add_argument("--enclosure-target-temperature-c", type=float, default=30.0)
    parser.add_argument("--enclosure-target-rh", type=float, default=0.50)
    parser.add_argument("--enclosure-volume-m3", type=float, default=20.0)
    parser.add_argument("--enclosure-air-changes-per-h", type=float, default=0.5)
    parser.add_argument("--enclosure-internal-moisture-kg-h", type=float, default=0.0)

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_root = args.source_root.expanduser().resolve()
    out = args.output_dir.expanduser().resolve()

    context = build_native_context(source_root, args)
    gas_row = selected_row(context["paths"]["gas_o30"], args.target)
    liquid_table = (
        read_table(context["paths"]["direct_liquid"])
        if context["paths"]["direct_liquid"] is not None
        else None
    )

    water_load = float(
        context["targets"][args.target]["computed_water_load_kg_h"]
    )
    core_power = first_finite(
        gas_row,
        ["analysis_core_power_kw", "predryer_core_power_kw"],
        args.o30_core_power_kw,
    )

    break_even = break_even_register(
        baseline_compressor_kw=args.baseline_compressor_kw,
        o30_compressor_kw=args.o30_compressor_kw,
        water_load_kg_h=water_load,
        core_power_kw=core_power,
    )
    erv = build_erv_grid(
        api=context["api"],
        basis=context["basis"],
        args=args,
    )
    sec_options = eo_sec_options(
        gas_row=gas_row,
        liquid_table=liquid_table,
        water_load_kg_h=water_load,
    )
    incremental = incremental_eo_requirement(
        erv=erv,
        sec_options=sec_options,
        basis=context["basis"],
        args=args,
    )
    diffusivity = diffusivity_extension(
        context=context,
        args=args,
    )
    liquid_upper = liquid_local_upper_bound(
        context=context,
        args=args,
    )
    liquid_existing = direct_liquid_output_summary(
        context["paths"]["direct_liquid"]
    )
    geometry = geometry_sweep(
        context=context,
        args=args,
    )
    ledger = power_ledger(
        gas_row=gas_row,
        break_even=break_even,
        liquid_upper=liquid_upper,
        args=args,
    )
    figures = foms(
        ledger=ledger,
        args=args,
    )
    enclosure = enclosure_foms(
        api=context["api"],
        capacity_kg_h=water_load,
        args=args,
    )
    complete_ledger = complete_system_power_ledger(
        erv=erv,
        incremental=incremental,
        predryer_ledger=ledger,
        args=args,
    )
    expanded_foms = unified_fom_register(
        gas_row=gas_row,
        ledger=ledger,
        geometry=geometry,
        enclosure=enclosure,
        context=context,
        args=args,
    )
    benchmarks = industry_benchmarks(
        break_even=break_even,
        ledger=ledger,
    )
    grid_sensitivity = grid_loss_sensitivity(
        ledger=ledger,
    )
    conditions = conditions_table(
        context=context,
        args=args,
    )
    terminology = terminology_table()
    selected_reference = pd.DataFrame([gas_row])

    make_plots(
        out=out,
        erv=erv,
        incremental=incremental,
        diffusivity=diffusivity,
        liquid_upper=liquid_upper,
        geometry=geometry,
    )
    summary = summary_markdown(
        out=out,
        break_even=break_even,
        erv=erv,
        incremental=incremental,
        liquid_upper=liquid_upper,
        liquid_existing=liquid_existing,
        geometry=geometry,
        diffusivity=diffusivity,
        ledger=ledger,
    )
    write_outputs(
        out=out,
        data={
            "break_even_register": break_even,
            "erv_industry_grid": erv,
            "eo_sec_options": sec_options,
            "erv_plus_eo_10pct": incremental,
            "diffusivity_extension": diffusivity,
            "liquid_local_upper_bound": liquid_upper,
            "liquid_existing_output_summary": liquid_existing,
            "geometry_sweep": geometry,
            "power_ledger": ledger,
            "complete_system_power_ledger": complete_ledger,
            "systems_reported_separately": complete_ledger,
            "figures_of_merit": figures,
            "all_requested_foms": expanded_foms,
            "enclosure_foms": enclosure,
            "industry_benchmarks": benchmarks,
            "grid_loss_sensitivity": grid_sensitivity,
            "selected_reference_case": selected_reference,
            "conditions": conditions,
            "terminology": terminology,
        },
        summary=summary,
    )

    print(summary)
    print(f"Outputs: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
