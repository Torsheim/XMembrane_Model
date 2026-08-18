from __future__ import annotations

import copy
import math
from typing import Any

import pandas as pd

from heiq.wp1.airside.properties import (
    AirflowBasis,
    humidity_ratio_from_t_rh,
)

def validate_config(config: dict[str, Any]) -> None:
    for name in (
        "air",
        "targets",
        "receiver_boundaries",
        "channel",
        "electrical",
        "thermal",
        "integration",
        "materials",
    ):
        if name not in config:
            raise ValueError(f"Configuration is missing top-level key: {name}")
    if not config["materials"]:
        raise ValueError("At least one material design is required")
    if not 0.0 < float(config["air"]["inlet_relative_humidity"]) <= 1.0:
        raise ValueError("Inlet relative humidity must lie in (0, 1]")
    for target, values in config["targets"].items():
        rh = float(values["reference_relative_humidity"])
        if not 0.0 < rh < float(config["air"]["inlet_relative_humidity"]):
            raise ValueError(f"Target {target} has an invalid reference RH")
    for label, values in config["receiver_boundaries"].items():
        activity = float(values["water_activity"])
        if not 0.0 < activity < 1.0:
            raise ValueError(f"Receiver activity {label} must lie in (0, 1)")
    for efficiency in config["electrical"]["power_electronics_efficiencies"]:
        if not 0.0 < float(efficiency) <= 1.0:
            raise ValueError("Power-electronics efficiency must lie in (0, 1]")

def build_targets(
    config: dict[str, Any],
    basis: AirflowBasis,
    v2_config: dict[str, Any],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    inlet_w = basis.inlet_humidity_ratio_kg_kg_da
    for label, target in config["targets"].items():
        reference_temperature = float(target["reference_temperature_c"])
        reference_rh = float(target["reference_relative_humidity"])
        target_w = humidity_ratio_from_t_rh(
            reference_temperature,
            reference_rh,
            basis.absolute_pressure_pa,
        )
        water_load = (
            basis.dry_air_mass_flow_kg_s * (inlet_w - target_w) * 3600.0
        )
        legacy = v2_config.get("scenarios", {}).get(label, {})
        legacy_load = float(legacy.get("water_load_kg_h", math.nan))
        legacy_gross = float(
            legacy.get("gross_hvac_electric_opportunity_kw", math.nan)
        )
        if math.isfinite(legacy_load) and legacy_load > 0.0:
            gross_hvac = legacy_gross * water_load / legacy_load
        else:
            gross_hvac = math.nan
        rows.append(
            {
                "target": label,
                "target_definition": "fixed_humidity_ratio_at_reference_state",
                "reference_temperature_c": reference_temperature,
                "reference_relative_humidity": reference_rh,
                "target_humidity_ratio_kg_kg_da": target_w,
                "target_humidity_ratio_g_kg_da": 1000.0 * target_w,
                "computed_water_load_kg_h": water_load,
                "legacy_v2_water_load_kg_h": legacy_load,
                "water_load_difference_percent": (
                    100.0 * (water_load / legacy_load - 1.0)
                    if math.isfinite(legacy_load) and legacy_load > 0.0
                    else math.nan
                ),
                "scaled_gross_hvac_opportunity_kw": gross_hvac,
            }
        )
    return pd.DataFrame(rows)

def reduced_quick_config(config: dict[str, Any]) -> dict[str, Any]:
    quick = copy.deepcopy(config)
    quick["receiver_boundaries"] = {
        "dry_receiver_80_50": quick["receiver_boundaries"][
            "dry_receiver_80_50"
        ]
    }
    quick["electrical"]["terminal_voltages_v"] = [
        quick["electrical"]["terminal_voltages_v"][-1]
    ]
    quick["electrical"]["fixed_loss_voltages_v"] = [
        quick["electrical"]["fixed_loss_voltages_v"][0]
    ]
    quick["thermal"]["modes"] = ["isothermal"]
    quick["materials"] = [quick["materials"][0]]
    quick["integration"]["area_step_m2"] = max(
        50.0, float(quick["integration"]["area_step_m2"])
    )
    return quick

__all__ = [
    "validate_config",
    "build_targets",
    "reduced_quick_config",
]
