"""Reduced-order direct active EO-assisted ERV study model.

The thermodynamic endpoint and counter-current segmentation algorithms are
adapted from the reviewed HeiQ_V2 package
``HeiQ_active_eo_erv_terminal1_v2`` (v2.2.2, 2026-08-23).  Psychrometric
properties and membrane transport are deliberately routed through the native
XMembrane APIs so the new study has one canonical property/transport chain.

This is a segmented screening model, not a conjugate heat-and-mass-transfer
PDE.  Sensible effectiveness is prescribed, bulk states are interpolated
between balanced endpoints, and each segment is sized at its mean local state.
Those limitations must remain visible in every downstream claim boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from types import ModuleType
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from heiq.wp1.airside.properties import (
    MOLAR_MASS_WATER_KG_MOL,
    R_DRY_AIR_J_KG_K,
    activity_from_t_w,
    humidity_ratio_from_t_rh,
    moist_air_enthalpy_kj_kg_da,
    relative_humidity_from_t_w,
)
from heiq.wp1.axial.local_state import solve_local_state
from heiq.wp1.engineering.channels import channel_pressure_drop_and_fan


@dataclass(frozen=True)
class AirState:
    t_c: float
    rh: float
    w: float
    h: float
    dewpoint_c: float
    v: float
    pressure_pa: float
    label: str = ""


@dataclass(frozen=True)
class ERVResult:
    oa_out: AirState
    exhaust_out: AirState
    fan_power_kw: float
    motor_power_kw: float
    total_power_kw: float
    effective_sensible_oa: float
    effective_latent_oa: float
    water_balance_residual_kg_s: float
    enthalpy_balance_residual_kw: float
    valid: bool
    condensation_required: bool


@dataclass(frozen=True)
class CoilResult:
    inlet: AirState
    off_coil: AirState
    supply: AirState
    adp: AirState | None
    cooling_load_kw: float
    water_removed_kg_h: float
    reheat_load_kw_th: float
    reheat_electric_kw: float
    evap_temperature_c: float
    cop: float
    compressor_power_kw: float
    total_ac_power_kw: float
    physical: bool


@dataclass(frozen=True)
class BaselineSystem:
    passive_erv: ERVResult
    remaining_ac: CoilResult
    rated_cop: float
    total_power_kw: float


@dataclass(frozen=True)
class DirectEOEndpoints:
    process_in: AirState
    exhaust_in: AirState
    process_out: AirState
    exhaust_out: AirState
    process_dry_air_kg_s: float
    exhaust_dry_air_kg_s: float
    sensible_effectiveness: float
    active_latent_effectiveness: float
    water_transfer_kg_h: float
    water_balance_residual_kg_s: float
    base_enthalpy_balance_residual_kw: float
    process_heat_kw: float
    exhaust_heat_kw: float
    externally_rejected_heat_kw: float
    condensation_required: bool
    valid: bool


@dataclass(frozen=True)
class Segment:
    index: int
    count: int
    x0: float
    x1: float
    process_in_t_c: float
    process_out_t_c: float
    process_in_w: float
    process_out_w: float
    receiver_in_t_c: float
    receiver_out_t_c: float
    receiver_in_w: float
    receiver_out_w: float
    membrane_temperature_c: float
    water_transfer_kg_h: float


def temperature_from_h_w(
    enthalpy_kj_kg_da: float,
    humidity_ratio_kg_kg_da: float,
) -> float:
    return (
        enthalpy_kj_kg_da - 2501.0 * humidity_ratio_kg_kg_da
    ) / (1.006 + 1.86 * humidity_ratio_kg_kg_da)


def moist_air_specific_volume_m3_kg_da(
    temperature_c: float,
    humidity_ratio_kg_kg_da: float,
    pressure_pa: float,
) -> float:
    return (
        R_DRY_AIR_J_KG_K
        * (temperature_c + 273.15)
        * (1.0 + 1.6078 * humidity_ratio_kg_kg_da)
        / pressure_pa
    )


def saturation_temperature_from_w(
    humidity_ratio_kg_kg_da: float,
    pressure_pa: float,
) -> float:
    lo, hi = -60.0, 80.0
    for _ in range(140):
        mid = 0.5 * (lo + hi)
        saturated_w = humidity_ratio_from_t_rh(mid, 1.0, pressure_pa)
        if saturated_w < humidity_ratio_kg_kg_da:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def state_from_t_w(
    temperature_c: float,
    humidity_ratio_kg_kg_da: float,
    pressure_pa: float,
    label: str = "",
) -> AirState:
    if humidity_ratio_kg_kg_da < 0.0:
        raise ValueError("Humidity ratio cannot be negative")
    return AirState(
        t_c=float(temperature_c),
        rh=relative_humidity_from_t_w(
            temperature_c,
            humidity_ratio_kg_kg_da,
            pressure_pa,
        ),
        w=float(humidity_ratio_kg_kg_da),
        h=moist_air_enthalpy_kj_kg_da(
            temperature_c, humidity_ratio_kg_kg_da
        ),
        dewpoint_c=saturation_temperature_from_w(
            humidity_ratio_kg_kg_da, pressure_pa
        ),
        v=moist_air_specific_volume_m3_kg_da(
            temperature_c, humidity_ratio_kg_kg_da, pressure_pa
        ),
        pressure_pa=float(pressure_pa),
        label=label,
    )


def state_from_t_rh(
    temperature_c: float,
    relative_humidity: float,
    pressure_pa: float,
    label: str = "",
) -> AirState:
    return state_from_t_w(
        temperature_c,
        humidity_ratio_from_t_rh(
            temperature_c, relative_humidity, pressure_pa
        ),
        pressure_pa,
        label,
    )


def state_from_h_w(
    enthalpy_kj_kg_da: float,
    humidity_ratio_kg_kg_da: float,
    pressure_pa: float,
    label: str = "",
) -> AirState:
    return state_from_t_w(
        temperature_from_h_w(
            enthalpy_kj_kg_da, humidity_ratio_kg_kg_da
        ),
        humidity_ratio_kg_kg_da,
        pressure_pa,
        label,
    )


def run_erv(
    *,
    oa_in: AirState,
    exhaust_in: AirState,
    m_oa: float,
    m_exhaust: float,
    sensible_effectiveness: float,
    latent_effectiveness: float,
    pressure_drop_each_side_pa: float,
    fan_efficiency: float,
    motor_power_kw: float,
) -> ERVResult:
    if m_oa <= 0.0 or m_exhaust <= 0.0:
        raise ValueError("ERV dry-air flows must be positive")
    if not 0.0 <= sensible_effectiveness <= 1.0:
        raise ValueError("Sensible effectiveness must be in [0, 1]")
    if not 0.0 <= latent_effectiveness <= 1.0:
        raise ValueError("Latent effectiveness must be in [0, 1]")
    if not 0.0 < fan_efficiency <= 1.0:
        raise ValueError("Fan efficiency must lie in (0, 1]")

    flow_factor = min(1.0, m_exhaust / m_oa)
    eps_s = sensible_effectiveness * flow_factor
    eps_l = latent_effectiveness * flow_factor
    oa_out = state_from_t_w(
        oa_in.t_c - eps_s * (oa_in.t_c - exhaust_in.t_c),
        oa_in.w - eps_l * (oa_in.w - exhaust_in.w),
        oa_in.pressure_pa,
        "outdoor air after passive ERV",
    )
    exhaust_out_w = exhaust_in.w + (
        m_oa / m_exhaust
    ) * (oa_in.w - oa_out.w)
    exhaust_out_h = (
        m_oa * oa_in.h
        + m_exhaust * exhaust_in.h
        - m_oa * oa_out.h
    ) / m_exhaust
    exhaust_out = state_from_h_w(
        exhaust_out_h,
        exhaust_out_w,
        exhaust_in.pressure_pa,
        "exhaust after passive ERV",
    )
    water_residual = (
        m_oa * (oa_in.w - oa_out.w)
        - m_exhaust * (exhaust_out.w - exhaust_in.w)
    )
    enthalpy_residual = (
        m_oa * oa_in.h
        + m_exhaust * exhaust_in.h
        - m_oa * oa_out.h
        - m_exhaust * exhaust_out.h
    )
    fan_kw = (
        m_oa * oa_in.v * pressure_drop_each_side_pa
        + m_exhaust * exhaust_in.v * pressure_drop_each_side_pa
    ) / fan_efficiency / 1000.0
    total_kw = fan_kw + motor_power_kw
    condensation = (
        oa_out.rh > 1.0 + 1.0e-9
        or exhaust_out.rh > 1.0 + 1.0e-9
    )
    valid = bool(
        not condensation
        and all(
            math.isfinite(value)
            for value in (
                fan_kw,
                total_kw,
                water_residual,
                enthalpy_residual,
            )
        )
    )
    return ERVResult(
        oa_out=oa_out,
        exhaust_out=exhaust_out,
        fan_power_kw=fan_kw,
        motor_power_kw=motor_power_kw,
        total_power_kw=total_kw,
        effective_sensible_oa=eps_s,
        effective_latent_oa=eps_l,
        water_balance_residual_kg_s=water_residual,
        enthalpy_balance_residual_kw=enthalpy_residual,
        valid=valid,
        condensation_required=condensation,
    )


def _carnot_cop(evaporating_c: float, condensing_c: float) -> float:
    evaporating_k = evaporating_c + 273.15
    condensing_k = condensing_c + 273.15
    if condensing_k <= evaporating_k:
        return math.nan
    return evaporating_k / (condensing_k - evaporating_k)


def _scaled_cop(
    rated_cop: float,
    evaporating_c: float,
    rated_evaporating_c: float,
    condensing_c: float,
    conservative_eta: float,
) -> float:
    current = _carnot_cop(evaporating_c, condensing_c)
    reference = _carnot_cop(rated_evaporating_c, condensing_c)
    if not math.isfinite(current) or not math.isfinite(reference):
        return math.nan
    return rated_cop * (
        1.0 + conservative_eta * (current / reference - 1.0)
    )


def _reheat_electric(
    thermal_load_kw: float, config: Mapping[str, Any]
) -> float:
    mode = str(config["reheat_mode"]).strip().lower()
    if mode == "electric":
        return thermal_load_kw
    if mode == "heat_pump":
        return thermal_load_kw / float(config["reheat_heat_pump_cop"])
    if mode in {"hot_gas_recovery", "hot_gas", "recovered"}:
        return thermal_load_kw * float(
            config["hot_gas_reheat_electric_fraction"]
        )
    if mode == "none":
        return 0.0
    raise ValueError(f"Unknown reheat mode {mode!r}")


def solve_coil(
    *,
    inlet: AirState,
    supply_target: AirState,
    m_da: float,
    rated_cop: float,
    ac_config: Mapping[str, Any],
) -> CoilResult:
    bypass = float(ac_config["coil_bypass_factor"])
    if not 0.0 <= bypass < 1.0:
        raise ValueError("coil_bypass_factor must lie in [0, 1)")
    target_w = supply_target.w
    if inlet.w > target_w + 1.0e-12:
        adp_w = (target_w - bypass * inlet.w) / (1.0 - bypass)
        if adp_w <= 0.0:
            invalid = state_from_t_w(
                supply_target.t_c,
                target_w,
                inlet.pressure_pa,
                "invalid coil state",
            )
            return CoilResult(
                inlet,
                invalid,
                invalid,
                None,
                *(math.nan,) * 8,
                False,
            )
        adp_t = saturation_temperature_from_w(
            adp_w, inlet.pressure_pa
        )
        adp = state_from_t_w(
            adp_t, adp_w, inlet.pressure_pa, "apparatus dew point"
        )
        off_coil_h = bypass * inlet.h + (1.0 - bypass) * adp.h
        off_coil = state_from_h_w(
            off_coil_h,
            target_w,
            inlet.pressure_pa,
            "off-coil",
        )
    else:
        adp = None
        adp_t = supply_target.t_c
        off_coil = state_from_t_w(
            supply_target.t_c,
            inlet.w,
            inlet.pressure_pa,
            "sensible off-coil",
        )
    supply = state_from_t_w(
        supply_target.t_c,
        off_coil.w,
        inlet.pressure_pa,
        "supply",
    )
    cooling_kw = max(inlet.h - off_coil.h, 0.0) * m_da
    water_kg_h = max(inlet.w - off_coil.w, 0.0) * m_da * 3600.0
    reheat_kw = max(supply.h - off_coil.h, 0.0) * m_da
    reheat_electric_kw = _reheat_electric(reheat_kw, ac_config)
    evaporating_c = adp_t - float(ac_config["evaporator_approach_k"])
    cop = _scaled_cop(
        rated_cop,
        evaporating_c,
        float(ac_config["rated_evaporating_temperature_c"]),
        float(ac_config["condensing_temperature_c"]),
        float(ac_config["conservative_cop_eta"]),
    )
    compressor_kw = (
        cooling_kw / cop
        if cop > 0.0 and math.isfinite(cop)
        else math.nan
    )
    total_kw = compressor_kw + reheat_electric_kw
    physical = bool(
        off_coil.rh <= 1.0 + 1.0e-8
        and supply.rh <= 1.0 + 1.0e-8
        and math.isfinite(total_kw)
    )
    if (
        str(ac_config["reheat_mode"]).strip().lower() == "none"
        and reheat_kw > 1.0e-9
    ):
        physical = False
    return CoilResult(
        inlet=inlet,
        off_coil=off_coil,
        supply=supply,
        adp=adp,
        cooling_load_kw=cooling_kw,
        water_removed_kg_h=water_kg_h,
        reheat_load_kw_th=reheat_kw,
        reheat_electric_kw=reheat_electric_kw,
        evap_temperature_c=evaporating_c,
        cop=cop,
        compressor_power_kw=compressor_kw,
        total_ac_power_kw=total_kw,
        physical=physical,
    )


def calibrate_rated_cop(
    inlet: AirState,
    supply_target: AirState,
    m_da: float,
    ac_config: Mapping[str, Any],
) -> float:
    unit = solve_coil(
        inlet=inlet,
        supply_target=supply_target,
        m_da=m_da,
        rated_cop=1.0,
        ac_config=ac_config,
    )
    remaining = (
        float(ac_config["legacy_no_erv_ac_power_anchor_kw"])
        - unit.reheat_electric_kw
    )
    if remaining <= 0.0:
        raise ValueError("Reheat power exceeds the legacy AC anchor")
    return unit.compressor_power_kw / remaining


def states_from_config(config: Mapping[str, Any]) -> dict[str, AirState]:
    boundary = config["boundary"]
    pressure = float(boundary["pressure_pa"])
    return {
        "outdoor": state_from_t_rh(
            float(boundary["outdoor_temperature_c"]),
            float(boundary["outdoor_rh"]),
            pressure,
            "outdoor/process inlet",
        ),
        "exhaust": state_from_t_rh(
            float(boundary["return_temperature_c"]),
            float(boundary["return_rh"]),
            pressure,
            "return/exhaust inlet",
        ),
        "supply": state_from_t_rh(
            float(boundary["supply_temperature_c"]),
            float(boundary["supply_rh"]),
            pressure,
            "supply target",
        ),
    }


def build_passive_baseline(
    config: Mapping[str, Any],
    states: Mapping[str, AirState],
    sensible_effectiveness: float,
) -> BaselineSystem:
    boundary = config["boundary"]
    m_process = float(boundary["process_outdoor_dry_air_kg_s"])
    m_exhaust = m_process * float(
        boundary["available_exhaust_to_process_ratio"]
    )
    if abs(m_process - m_exhaust) > 1.0e-9:
        raise ValueError("Direct active ERV requires balanced dry-air flows")
    rated_cop = calibrate_rated_cop(
        states["outdoor"], states["supply"], m_process, config["ac_model"]
    )
    erv_config = config["passive_baseline_erv"]
    erv = run_erv(
        oa_in=states["outdoor"],
        exhaust_in=states["exhaust"],
        m_oa=m_process,
        m_exhaust=m_exhaust,
        sensible_effectiveness=sensible_effectiveness,
        latent_effectiveness=float(erv_config["latent_effectiveness"]),
        pressure_drop_each_side_pa=float(
            erv_config["pressure_drop_each_side_pa"]
        ),
        fan_efficiency=float(erv_config["fan_efficiency"]),
        motor_power_kw=float(erv_config["motor_power_kw"]),
    )
    coil = solve_coil(
        inlet=erv.oa_out,
        supply_target=states["supply"],
        m_da=m_process,
        rated_cop=rated_cop,
        ac_config=config["ac_model"],
    )
    common_kw = float(
        config["common_components"]["common_electric_power_kw_each_system"]
    )
    return BaselineSystem(
        passive_erv=erv,
        remaining_ac=coil,
        rated_cop=rated_cop,
        total_power_kw=erv.total_power_kw + coil.total_ac_power_kw + common_kw,
    )


def build_direct_eo_endpoints(
    *,
    process_in: AirState,
    exhaust_in: AirState,
    process_dry_air_kg_s: float,
    exhaust_dry_air_kg_s: float,
    process_out_w: float,
    sensible_effectiveness: float,
    active_core_electric_power_kw: float = 0.0,
    process_heat_fraction: float = 0.0,
    exhaust_heat_fraction: float = 0.0,
) -> DirectEOEndpoints:
    m_process = float(process_dry_air_kg_s)
    m_exhaust = float(exhaust_dry_air_kg_s)
    if m_process <= 0.0 or m_exhaust <= 0.0:
        raise ValueError("Dry-air flows must be positive")
    if abs(m_process - m_exhaust) > 1.0e-9:
        raise ValueError("Balanced process and exhaust flows are required")
    if not 0.0 <= sensible_effectiveness <= 1.0:
        raise ValueError("sensible_effectiveness must lie in [0, 1]")
    if not 0.0 <= process_out_w < process_in.w:
        raise ValueError("process_out_w must be below the process inlet")
    if active_core_electric_power_kw < 0.0:
        raise ValueError("Active-core electric power cannot be negative")
    if process_heat_fraction < 0.0 or exhaust_heat_fraction < 0.0:
        raise ValueError("Electrical heat fractions cannot be negative")
    if process_heat_fraction + exhaust_heat_fraction > 1.0 + 1.0e-12:
        raise ValueError("Electrical heat fractions cannot sum above one")

    water_kg_s = m_process * (process_in.w - process_out_w)
    exhaust_out_w = exhaust_in.w + water_kg_s / m_exhaust
    process_out_base_t = process_in.t_c - sensible_effectiveness * (
        process_in.t_c - exhaust_in.t_c
    )
    process_out_base = state_from_t_w(
        process_out_base_t,
        process_out_w,
        process_in.pressure_pa,
        "active process outlet before electrical heat",
    )
    total_in_h_kw = m_process * process_in.h + m_exhaust * exhaust_in.h
    exhaust_out_base_h = (
        total_in_h_kw - m_process * process_out_base.h
    ) / m_exhaust
    exhaust_out_base = state_from_h_w(
        exhaust_out_base_h,
        exhaust_out_w,
        exhaust_in.pressure_pa,
        "active exhaust outlet before electrical heat",
    )
    base_h_residual = (
        total_in_h_kw
        - m_process * process_out_base.h
        - m_exhaust * exhaust_out_base.h
    )
    process_heat_kw = active_core_electric_power_kw * process_heat_fraction
    exhaust_heat_kw = active_core_electric_power_kw * exhaust_heat_fraction
    rejected_heat_kw = (
        active_core_electric_power_kw - process_heat_kw - exhaust_heat_kw
    )
    process_out = state_from_h_w(
        process_out_base.h + process_heat_kw / m_process,
        process_out_w,
        process_in.pressure_pa,
        "active process outlet",
    )
    exhaust_out = state_from_h_w(
        exhaust_out_base.h + exhaust_heat_kw / m_exhaust,
        exhaust_out_w,
        exhaust_in.pressure_pa,
        "active exhaust outlet",
    )
    water_residual = (
        m_process * (process_in.w - process_out.w)
        - m_exhaust * (exhaust_out.w - exhaust_in.w)
    )
    denominator = process_in.w - exhaust_in.w
    latent_effectiveness = (
        (process_in.w - process_out.w) / denominator
        if denominator > 0.0
        else math.nan
    )
    condensation = (
        process_out.rh > 1.0 + 1.0e-9
        or exhaust_out.rh > 1.0 + 1.0e-9
    )
    valid = bool(
        not condensation
        and abs(water_residual) <= 1.0e-10
        and abs(base_h_residual) <= 1.0e-8
        and all(
            math.isfinite(value)
            for value in (
                process_out.t_c,
                process_out.rh,
                exhaust_out.t_c,
                exhaust_out.rh,
            )
        )
    )
    return DirectEOEndpoints(
        process_in=process_in,
        exhaust_in=exhaust_in,
        process_out=process_out,
        exhaust_out=exhaust_out,
        process_dry_air_kg_s=m_process,
        exhaust_dry_air_kg_s=m_exhaust,
        sensible_effectiveness=sensible_effectiveness,
        active_latent_effectiveness=latent_effectiveness,
        water_transfer_kg_h=water_kg_s * 3600.0,
        water_balance_residual_kg_s=water_residual,
        base_enthalpy_balance_residual_kw=base_h_residual,
        process_heat_kw=process_heat_kw,
        exhaust_heat_kw=exhaust_heat_kw,
        externally_rejected_heat_kw=rejected_heat_kw,
        condensation_required=condensation,
        valid=valid,
    )


def _lerp(start: float, end: float, fraction: float) -> float:
    return start + fraction * (end - start)


def build_segments(
    endpoints: DirectEOEndpoints,
    count: int,
    membrane_temperature_mode: str = "local_stream_mean",
) -> list[Segment]:
    if count < 1:
        raise ValueError("segment count must be at least one")
    rows: list[Segment] = []
    for index in range(count):
        x0 = index / count
        x1 = (index + 1) / count
        process_t0 = _lerp(
            endpoints.process_in.t_c, endpoints.process_out.t_c, x0
        )
        process_t1 = _lerp(
            endpoints.process_in.t_c, endpoints.process_out.t_c, x1
        )
        process_w0 = _lerp(
            endpoints.process_in.w, endpoints.process_out.w, x0
        )
        process_w1 = _lerp(
            endpoints.process_in.w, endpoints.process_out.w, x1
        )
        # x is measured in the process direction; exhaust enters at x=1.
        receiver_t_in = _lerp(
            endpoints.exhaust_out.t_c, endpoints.exhaust_in.t_c, x1
        )
        receiver_t_out = _lerp(
            endpoints.exhaust_out.t_c, endpoints.exhaust_in.t_c, x0
        )
        receiver_w_in = _lerp(
            endpoints.exhaust_out.w, endpoints.exhaust_in.w, x1
        )
        receiver_w_out = _lerp(
            endpoints.exhaust_out.w, endpoints.exhaust_in.w, x0
        )
        process_mean_t = 0.5 * (process_t0 + process_t1)
        receiver_mean_t = 0.5 * (receiver_t_in + receiver_t_out)
        mode = membrane_temperature_mode.strip().lower()
        if mode == "local_stream_mean":
            membrane_t = 0.5 * (process_mean_t + receiver_mean_t)
        elif mode == "process_mean":
            membrane_t = process_mean_t
        elif mode == "receiver_mean":
            membrane_t = receiver_mean_t
        else:
            raise ValueError(
                f"Unknown membrane temperature mode {membrane_temperature_mode!r}"
            )
        rows.append(
            Segment(
                index=index,
                count=count,
                x0=x0,
                x1=x1,
                process_in_t_c=process_t0,
                process_out_t_c=process_t1,
                process_in_w=process_w0,
                process_out_w=process_w1,
                receiver_in_t_c=receiver_t_in,
                receiver_out_t_c=receiver_t_out,
                receiver_in_w=receiver_w_in,
                receiver_out_w=receiver_w_out,
                membrane_temperature_c=membrane_t,
                water_transfer_kg_h=(
                    endpoints.process_dry_air_kg_s
                    * (process_w0 - process_w1)
                    * 3600.0
                ),
            )
        )
    return rows


def segment_balance_audit(
    endpoints: DirectEOEndpoints, segments: Sequence[Segment]
) -> dict[str, Any]:
    total_water = sum(segment.water_transfer_kg_h for segment in segments)
    process_continuity = max(
        (
            abs(segments[index].process_out_w - segments[index + 1].process_in_w)
            for index in range(len(segments) - 1)
        ),
        default=0.0,
    )
    receiver_continuity = max(
        (
            abs(segments[index].receiver_in_w - segments[index + 1].receiver_out_w)
            for index in range(len(segments) - 1)
        ),
        default=0.0,
    )
    receiver_error = max(
        (
            abs(
                endpoints.exhaust_dry_air_kg_s
                * (segment.receiver_out_w - segment.receiver_in_w)
                * 3600.0
                - segment.water_transfer_kg_h
            )
            for segment in segments
        ),
        default=0.0,
    )
    relative_error = abs(total_water - endpoints.water_transfer_kg_h) / max(
        endpoints.water_transfer_kg_h, 1.0e-12
    )
    return {
        "total_water_transfer_kg_h": total_water,
        "relative_error": relative_error,
        "process_continuity_error_w": process_continuity,
        "receiver_continuity_error_w": receiver_continuity,
        "receiver_segment_balance_error_kg_h": receiver_error,
        "pass": bool(
            relative_error <= 1.0e-10
            and process_continuity <= 1.0e-12
            and receiver_continuity <= 1.0e-12
            and receiver_error <= 1.0e-8
        ),
    }


def _strict_sum(values: Sequence[float]) -> float:
    array = np.asarray(values, dtype=float)
    if len(array) == 0 or not np.isfinite(array).all():
        return math.nan
    return float(array.sum())


def _strict_min(values: Sequence[float]) -> float:
    array = np.asarray(values, dtype=float)
    if len(array) == 0 or not np.isfinite(array).all():
        return math.nan
    return float(array.min())


def _strict_max(values: Sequence[float]) -> float:
    array = np.asarray(values, dtype=float)
    if len(array) == 0 or not np.isfinite(array).all():
        return math.nan
    return float(array.max())


def solve_segmented_transport(
    *,
    v2: ModuleType,
    v2_config: dict[str, Any],
    study_config: Mapping[str, Any],
    endpoints: DirectEOEndpoints,
    material: Mapping[str, Any],
    terminal_voltage_v: float,
    fixed_loss_voltage_v: float,
    series_asr_ohm_m2: float,
    film_scale_factor: float,
    segment_count: int,
    process_film_scale_factor: float | None = None,
    receiver_film_scale_factor: float | None = None,
) -> tuple[dict[str, Any], pd.DataFrame]:
    """Size each counter-current segment at its mean local state.

    No engineering current-density cap is accepted by this API.  The canonical
    local solver can still fail at its declared numerical search ceiling; that
    is a numerical status, not a material acceptance rule.
    """

    solver = study_config["solver"]
    gates = study_config["gates"]
    electrical = study_config["electrical"]
    maximum_voltage = float(electrical["maximum_terminal_voltage_v"])
    if terminal_voltage_v <= 0.0 or terminal_voltage_v > maximum_voltage + 1.0e-12:
        raise ValueError(
            f"terminal voltage must lie in (0, {maximum_voltage:g}] V"
        )
    if electrical.get("engineering_current_density_limit_a_m2") is not None:
        raise ValueError("An engineering current-density acceptance gate is forbidden")

    segments = build_segments(
        endpoints,
        segment_count,
        str(solver["membrane_temperature_mode"]),
    )
    balance = segment_balance_audit(endpoints, segments)
    if not balance["pass"]:
        raise RuntimeError(f"Counter-current segment balance failed: {balance}")

    pressure = endpoints.process_in.pressure_pa
    activity_basis = str(solver["activity_temperature_basis"]).strip().lower()
    membrane_temperature_mode = str(
        solver["membrane_temperature_mode"]
    ).strip().lower()
    transport_config = {
        "air": {"absolute_pressure_pa": pressure},
        "channel": {
            "process_velocity_m_s": float(
                study_config["channel"]["process_velocity_m_s"]
            ),
            "receiver_velocity_m_s": float(
                study_config["channel"]["receiver_velocity_m_s"]
            ),
            "process_gap_m": float(study_config["channel"]["process_gap_m"]),
            "receiver_gap_m": float(study_config["channel"]["receiver_gap_m"]),
            "receiver_temperature_c": endpoints.exhaust_in.t_c,
        },
    }
    def membrane_temperature(process_t: float, receiver_t: float) -> float:
        if membrane_temperature_mode == "local_stream_mean":
            return 0.5 * (process_t + receiver_t)
        if membrane_temperature_mode == "process_mean":
            return process_t
        if membrane_temperature_mode == "receiver_mean":
            return receiver_t
        raise ValueError(
            f"Unknown membrane temperature mode {membrane_temperature_mode!r}"
        )

    def solve_at_state(
        *,
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
            raise ValueError(
                f"Unknown activity temperature basis {activity_basis!r}"
            )
        receiver_activity = activity_from_t_w(
            receiver_activity_t, receiver_w, pressure
        )
        return solve_local_state(
            v2=v2,
            v2_config=v2_config,
            material=dict(material),
            source_temperature_c=process_activity_t,
            source_humidity_ratio=process_w,
            receiver_activity=receiver_activity,
            terminal_voltage_v=float(terminal_voltage_v),
            fixed_loss_voltage_v=float(fixed_loss_voltage_v),
            series_asr_ohm_m2=float(series_asr_ohm_m2),
            film_scale_factor=float(film_scale_factor),
            process_film_scale_factor=(
                None
                if process_film_scale_factor is None
                else float(process_film_scale_factor)
            ),
            receiver_film_scale_factor=(
                None
                if receiver_film_scale_factor is None
                else float(receiver_film_scale_factor)
            ),
            config=transport_config,
            receiver_temperature_c=receiver_film_t,
            membrane_temperature_c=membrane_t,
        )

    # Surface-direction gates must include physical segment boundaries.  A
    # midpoint-only gate can miss a limiting end state and can falsely promote
    # a case close to the robustness threshold.  Shared boundaries are solved
    # once, so n segments require n+1 boundary evaluations.
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
            process_t=process_t,
            process_w=process_w,
            receiver_t=receiver_t,
            receiver_w=receiver_w,
            membrane_t=membrane_temperature(process_t, receiver_t),
        )
        for process_t, process_w, receiver_t, receiver_w in boundary_states
    ]

    def activity_margin(
        local: Mapping[str, Any], source_key: str, receiver_key: str
    ) -> float:
        source = float(local.get(source_key, math.nan))
        receiver = float(local.get(receiver_key, math.nan))
        return source - receiver

    rows: list[dict[str, Any]] = []
    for segment in segments:
        process_mean_t = 0.5 * (
            segment.process_in_t_c + segment.process_out_t_c
        )
        receiver_mean_t = 0.5 * (
            segment.receiver_in_t_c + segment.receiver_out_t_c
        )
        process_mean_w = 0.5 * (
            segment.process_in_w + segment.process_out_w
        )
        receiver_mean_w = 0.5 * (
            segment.receiver_in_w + segment.receiver_out_w
        )
        local = solve_at_state(
            process_t=process_mean_t,
            process_w=process_mean_w,
            receiver_t=receiver_mean_t,
            receiver_w=receiver_mean_w,
            membrane_t=segment.membrane_temperature_c,
        )
        start_local = boundary_locals[segment.index]
        end_local = boundary_locals[segment.index + 1]
        solution_ok = bool(local.get("solution_ok", False))
        net_flux = float(local.get("net_flux_mol_m2_s", math.nan))
        current_density = float(
            local.get("current_density_a_m2", math.nan)
        )
        positive_flux = bool(
            solution_ok and math.isfinite(net_flux) and net_flux > 0.0
        )
        duty_mol_s = (
            segment.water_transfer_kg_h
            / 3600.0
            / MOLAR_MASS_WATER_KG_MOL
        )
        area = duty_mol_s / net_flux if positive_flux else math.nan
        integrated_current = (
            current_density * area
            if positive_flux and math.isfinite(current_density)
            else math.nan
        )
        eo_flux = float(local.get("eo_flux_mol_m2_s", math.nan))
        diffusion_flux = float(
            local.get("diffusion_flux_mol_m2_s", math.nan)
        )
        source_bulk = float(local.get("source_bulk_activity", math.nan))
        receiver_bulk = float(
            local.get("receiver_bulk_activity", math.nan)
        )
        source_surface = float(
            local.get("source_surface_activity", math.nan)
        )
        receiver_surface = float(
            local.get("receiver_surface_activity", math.nan)
        )
        start_bulk_margin = activity_margin(
            start_local, "source_bulk_activity", "receiver_bulk_activity"
        )
        end_bulk_margin = activity_margin(
            end_local, "source_bulk_activity", "receiver_bulk_activity"
        )
        start_surface_margin = activity_margin(
            start_local, "source_surface_activity", "receiver_surface_activity"
        )
        end_surface_margin = activity_margin(
            end_local, "source_surface_activity", "receiver_surface_activity"
        )
        boundary_solution_ok = bool(
            start_local.get("solution_ok", False)
            and end_local.get("solution_ok", False)
            and all(
                math.isfinite(value)
                for value in (
                    start_bulk_margin,
                    end_bulk_margin,
                    start_surface_margin,
                    end_surface_margin,
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
                "process_in_temperature_c": segment.process_in_t_c,
                "process_out_temperature_c": segment.process_out_t_c,
                "process_mean_temperature_c": process_mean_t,
                "process_in_humidity_ratio_kg_kg_da": segment.process_in_w,
                "process_out_humidity_ratio_kg_kg_da": segment.process_out_w,
                "process_mean_humidity_ratio_kg_kg_da": process_mean_w,
                "receiver_in_temperature_c": segment.receiver_in_t_c,
                "receiver_out_temperature_c": segment.receiver_out_t_c,
                "receiver_mean_temperature_c": receiver_mean_t,
                "receiver_in_humidity_ratio_kg_kg_da": segment.receiver_in_w,
                "receiver_out_humidity_ratio_kg_kg_da": segment.receiver_out_w,
                "receiver_mean_humidity_ratio_kg_kg_da": receiver_mean_w,
                "membrane_temperature_c": segment.membrane_temperature_c,
                "activity_temperature_basis": activity_basis,
                "water_duty_kg_h": segment.water_transfer_kg_h,
                "terminal_voltage_v": terminal_voltage_v,
                "solution_ok": solution_ok,
                "solution_status": str(
                    local.get("solution_status", "unknown_local_failure")
                ),
                "net_flux_positive": positive_flux,
                "net_flux_mol_m2_s": net_flux,
                "eo_flux_mol_m2_s": eo_flux,
                "diffusion_flux_mol_m2_s": diffusion_flux,
                "current_density_a_m2": current_density,
                "required_active_area_m2": area,
                "integrated_current_a": integrated_current,
                "source_bulk_activity": source_bulk,
                "receiver_bulk_activity": receiver_bulk,
                "bulk_activity_margin": source_bulk - receiver_bulk,
                "source_surface_activity": source_surface,
                "receiver_surface_activity": receiver_surface,
                "surface_activity_margin": source_surface - receiver_surface,
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
                "calculated_terminal_voltage_v": float(
                    local.get("calculated_terminal_voltage_v", math.nan)
                ),
                "terminal_voltage_error_v": float(
                    local.get("terminal_voltage_error_v", math.nan)
                ),
                "ohmic_voltage_v": float(
                    local.get("ohmic_voltage_v", math.nan)
                ),
                "water_polarisation_voltage_v": float(
                    local.get("water_polarisation_voltage_v", math.nan)
                ),
                "membrane_voltage_v": float(
                    local.get("membrane_voltage_v", math.nan)
                ),
                "series_loss_voltage_v": float(
                    local.get("series_loss_voltage_v", math.nan)
                ),
                "fixed_loss_voltage_v": float(
                    local.get("fixed_loss_voltage_v", math.nan)
                ),
                "series_asr_ohm_m2": float(series_asr_ohm_m2),
                "start_calculated_terminal_voltage_v": float(
                    start_local.get("calculated_terminal_voltage_v", math.nan)
                ),
                "end_calculated_terminal_voltage_v": float(
                    end_local.get("calculated_terminal_voltage_v", math.nan)
                ),
                "start_terminal_voltage_error_v": float(
                    start_local.get("terminal_voltage_error_v", math.nan)
                ),
                "end_terminal_voltage_error_v": float(
                    end_local.get("terminal_voltage_error_v", math.nan)
                ),
                "source_film_coefficient_mol_m2_s_activity": float(
                    local.get(
                        "source_film_coefficient_mol_m2_s_activity", math.nan
                    )
                ),
                "receiver_film_coefficient_mol_m2_s_activity": float(
                    local.get(
                        "receiver_film_coefficient_mol_m2_s_activity", math.nan
                    )
                ),
            }
        )

    frame = pd.DataFrame(rows)
    complete = bool(
        len(frame) == segment_count
        and frame["solution_ok"].all()
        and frame["net_flux_positive"].all()
    )
    area = _strict_sum(frame["required_active_area_m2"].tolist())
    integrated_current = _strict_sum(frame["integrated_current_a"].tolist())
    net_water = (
        _strict_sum(
            (
                frame["net_flux_mol_m2_s"]
                * frame["required_active_area_m2"]
                * MOLAR_MASS_WATER_KG_MOL
                * 3600.0
            ).tolist()
        )
        if complete
        else math.nan
    )
    eo_water = (
        _strict_sum(
            (
                frame["eo_flux_mol_m2_s"]
                * frame["required_active_area_m2"]
                * MOLAR_MASS_WATER_KG_MOL
                * 3600.0
            ).tolist()
        )
        if complete
        else math.nan
    )
    diffusion_water = (
        _strict_sum(
            (
                frame["diffusion_flux_mol_m2_s"]
                * frame["required_active_area_m2"]
                * MOLAR_MASS_WATER_KG_MOL
                * 3600.0
            ).tolist()
        )
        if complete
        else math.nan
    )
    water_relative_error = (
        (net_water - endpoints.water_transfer_kg_h)
        / max(abs(endpoints.water_transfer_kg_h), 1.0e-12)
        if complete
        else math.nan
    )
    cell_power_kw = (
        terminal_voltage_v * integrated_current / 1000.0
        if complete
        else math.nan
    )
    grid_power_kw = (
        cell_power_kw / float(electrical["power_electronics_efficiency"])
        if complete
        else math.nan
    )
    minimum_midpoint_bulk_margin = _strict_min(
        frame["bulk_activity_margin"].tolist()
    )
    minimum_midpoint_surface_margin = _strict_min(
        frame["surface_activity_margin"].tolist()
    )
    surface_diagnostic_complete = bool(
        complete and frame["boundary_solution_ok"].all()
    )
    minimum_bulk_margin = _strict_min(
        frame["minimum_boundary_bulk_activity_margin"].tolist()
    )
    minimum_surface_margin = _strict_min(
        frame["minimum_boundary_surface_activity_margin"].tolist()
    )
    boundary_solution_complete = bool(frame["boundary_solution_ok"].all())
    calculated_voltages = frame["calculated_terminal_voltage_v"].tolist()
    calculated_voltages += frame[
        "start_calculated_terminal_voltage_v"
    ].tolist()
    calculated_voltages += frame[
        "end_calculated_terminal_voltage_v"
    ].tolist()
    voltage_errors = frame["terminal_voltage_error_v"].tolist()
    voltage_errors += frame["start_terminal_voltage_error_v"].tolist()
    voltage_errors += frame["end_terminal_voltage_error_v"].tolist()
    finite_voltage_errors = [
        abs(float(value)) for value in voltage_errors if math.isfinite(value)
    ]
    maximum_absolute_voltage_error = (
        max(finite_voltage_errors) if finite_voltage_errors else math.nan
    )
    maximum_calculated_voltage = _strict_max(calculated_voltages)
    voltage_tolerance = float(
        solver.get("terminal_voltage_absolute_tolerance_v", 2.0e-6)
    )
    terminal_voltage_solution_pass = bool(
        complete
        and boundary_solution_complete
        and math.isfinite(maximum_absolute_voltage_error)
        and maximum_absolute_voltage_error <= voltage_tolerance
        and math.isfinite(maximum_calculated_voltage)
        and maximum_calculated_voltage <= maximum_voltage + voltage_tolerance
    )
    statuses = [str(value) for value in frame["solution_status"].tolist()]
    statuses += [
        str(local.get("solution_status", "unknown_local_failure"))
        for local in boundary_locals
    ]
    search_ceiling_count = sum(
        "current_search_ceiling" in status for status in statuses
    )
    failed_midpoints = frame.loc[
        ~frame["solution_ok"].astype(bool), "solution_status"
    ].astype(str)
    if not failed_midpoints.empty:
        transport_failure_reason = failed_midpoints.iloc[0]
    elif not complete:
        transport_failure_reason = "nonpositive_net_water_flux"
    elif not boundary_solution_complete:
        transport_failure_reason = "boundary_surface_diagnostic_incomplete"
    elif not terminal_voltage_solution_pass:
        transport_failure_reason = "terminal_voltage_closure_failed"
    else:
        transport_failure_reason = ""
    positive_surface_threshold = float(
        gates["minimum_positive_surface_activity_margin"]
    )
    result = {
        "transport_solution_complete": complete,
        "segment_count": segment_count,
        "required_active_area_m2": area,
        "integrated_current_a": integrated_current,
        "minimum_local_current_density_a_m2": _strict_min(
            frame["current_density_a_m2"].tolist()
        ),
        "maximum_local_current_density_a_m2": _strict_max(
            frame["current_density_a_m2"].tolist()
        ),
        "minimum_net_flux_mol_m2_s": _strict_min(
            frame["net_flux_mol_m2_s"].tolist()
        ),
        "minimum_diffusion_flux_mol_m2_s": _strict_min(
            frame["diffusion_flux_mol_m2_s"].tolist()
        ),
        "minimum_bulk_activity_margin": minimum_bulk_margin,
        "minimum_surface_activity_margin": minimum_surface_margin,
        "minimum_midpoint_bulk_activity_margin": minimum_midpoint_bulk_margin,
        "minimum_midpoint_surface_activity_margin": (
            minimum_midpoint_surface_margin
        ),
        "surface_diagnostic_complete": surface_diagnostic_complete,
        "positive_surface_direction": bool(
            surface_diagnostic_complete
            and minimum_surface_margin > positive_surface_threshold
        ),
        "robust_surface_direction": bool(
            surface_diagnostic_complete
            and minimum_surface_margin
            >= float(gates["robust_surface_activity_margin"])
        ),
        "water_transfer_target_kg_h": endpoints.water_transfer_kg_h,
        "integrated_net_water_transfer_kg_h": net_water,
        "integrated_eo_water_transfer_kg_h": eo_water,
        "integrated_diffusion_water_transfer_kg_h": diffusion_water,
        "diffusion_fraction_of_net_water": (
            diffusion_water / net_water
            if complete and abs(net_water) > 1.0e-12
            else math.nan
        ),
        "transport_water_balance_relative_error": water_relative_error,
        "transport_water_balance_pass": bool(
            complete
            and abs(water_relative_error)
            <= float(gates["water_balance_relative_tolerance"])
        ),
        "area_observation_cap_m2": float(solver["area_observation_cap_m2"]),
        "area_cap_pass": bool(
            complete
            and area <= float(solver["area_observation_cap_m2"])
        ),
        "cell_power_kw": cell_power_kw,
        "eo_grid_power_kw": grid_power_kw,
        "effective_fixed_loss_voltage_v": float(fixed_loss_voltage_v),
        "effective_series_asr_ohm_m2": float(series_asr_ohm_m2),
        "maximum_calculated_terminal_voltage_v": maximum_calculated_voltage,
        "maximum_absolute_terminal_voltage_error_v": (
            maximum_absolute_voltage_error
        ),
        "terminal_voltage_absolute_tolerance_v": voltage_tolerance,
        "terminal_voltage_solution_pass": terminal_voltage_solution_pass,
        "transport_failure_reason": transport_failure_reason,
        "legacy_numeric_current_search_ceiling_encountered": bool(
            search_ceiling_count
        ),
        "legacy_numeric_current_search_ceiling_status_count": int(
            search_ceiling_count
        ),
        "current_density_gate_applied": False,
        "engineering_current_density_limit_a_m2": None,
        "terminal_voltage_gate_pass": terminal_voltage_solution_pass,
    }
    return result, frame


def direct_eo_core_hydraulics(
    *,
    endpoints: DirectEOEndpoints,
    active_area_m2: float,
    config: Mapping[str, Any],
) -> dict[str, float | str]:
    """Ideal parallel-channel hydraulic screen plus declared ERV floor."""

    if not math.isfinite(active_area_m2) or active_area_m2 <= 0.0:
        return {
            "hydraulic_status": "unavailable_without_positive_area",
            "selected_active_core_fan_power_kw": math.nan,
        }
    channel = config["channel"]
    process_volume = (
        endpoints.process_dry_air_kg_s * endpoints.process_in.v
    )
    receiver_volume = (
        endpoints.exhaust_dry_air_kg_s * endpoints.exhaust_in.v
    )
    process_velocity = float(channel["process_velocity_m_s"])
    receiver_velocity = float(channel["receiver_velocity_m_s"])
    process_gap = float(channel["process_gap_m"])
    receiver_gap = float(channel["receiver_gap_m"])
    active_sides = float(channel["active_sides_per_channel"])
    fan_efficiency = float(channel["fan_efficiency"])
    process_width = process_volume / process_velocity / process_gap
    receiver_width = receiver_volume / receiver_velocity / receiver_gap
    process = channel_pressure_drop_and_fan(
        axial=None,
        active_area_m2=active_area_m2,
        total_channel_width_m=process_width,
        active_sides=active_sides,
        gap_m=process_gap,
        velocity_m_s=process_velocity,
        volume_flow_m3_s=process_volume,
        temperature_c=endpoints.process_in.t_c,
        pressure_pa=endpoints.process_in.pressure_pa,
        humidity_ratio_kg_kg_da=endpoints.process_in.w,
        fan_efficiency=fan_efficiency,
    )
    receiver = channel_pressure_drop_and_fan(
        axial=None,
        active_area_m2=active_area_m2,
        total_channel_width_m=receiver_width,
        active_sides=active_sides,
        gap_m=receiver_gap,
        velocity_m_s=receiver_velocity,
        volume_flow_m3_s=receiver_volume,
        temperature_c=endpoints.exhaust_in.t_c,
        pressure_pa=endpoints.exhaust_in.pressure_pa,
        humidity_ratio_kg_kg_da=endpoints.exhaust_in.w,
        fan_efficiency=fan_efficiency,
    )
    native_fan = float(process["channel_fan_power_kw"]) + float(
        receiver["channel_fan_power_kw"]
    )
    declared_dp = float(channel["declared_pressure_drop_each_side_pa"])
    declared_fan = (
        (process_volume + receiver_volume)
        * declared_dp
        / fan_efficiency
        / 1000.0
    )
    selected = max(native_fan, declared_fan)
    return {
        "hydraulic_status": "ideal_parallel_channel_screen",
        "process_actual_volume_flow_m3_s": process_volume,
        "receiver_actual_volume_flow_m3_s": receiver_volume,
        "process_total_channel_width_m": process_width,
        "receiver_total_channel_width_m": receiver_width,
        "process_channel_length_m": float(process["channel_length_m"]),
        "receiver_channel_length_m": float(receiver["channel_length_m"]),
        "process_channel_reynolds_number": float(
            process["channel_reynolds_number"]
        ),
        "receiver_channel_reynolds_number": float(
            receiver["channel_reynolds_number"]
        ),
        "process_channel_pressure_drop_pa": float(
            process["channel_pressure_drop_pa"]
        ),
        "receiver_channel_pressure_drop_pa": float(
            receiver["channel_pressure_drop_pa"]
        ),
        "native_parallel_channel_fan_power_kw": native_fan,
        "declared_pressure_drop_fan_floor_kw": declared_fan,
        "selected_active_core_fan_power_kw": selected,
        "selected_fan_basis": (
            "native_parallel_channel"
            if native_fan >= declared_fan
            else "declared_pressure_drop_floor"
        ),
    }


__all__ = [
    "DirectEOEndpoints",
    "AirState",
    "BaselineSystem",
    "CoilResult",
    "ERVResult",
    "Segment",
    "direct_eo_core_hydraulics",
    "build_direct_eo_endpoints",
    "build_passive_baseline",
    "build_segments",
    "calibrate_rated_cop",
    "run_erv",
    "segment_balance_audit",
    "solve_coil",
    "solve_segmented_transport",
    "state_from_h_w",
    "state_from_t_rh",
    "state_from_t_w",
    "states_from_config",
]
