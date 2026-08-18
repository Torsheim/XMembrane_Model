from __future__ import annotations

from .legacy_v3 import legacy_v3_module


def humidity_ratio_from_t_rh(*args, **kwargs):
    return legacy_v3_module().humidity_ratio_from_t_rh(*args, **kwargs)


def vapour_pressure_from_humidity_ratio(*args, **kwargs):
    return legacy_v3_module().vapour_pressure_from_humidity_ratio(*args, **kwargs)


def activity_from_t_w(*args, **kwargs):
    return legacy_v3_module().activity_from_t_w(*args, **kwargs)


def dry_air_mass_flow(*args, **kwargs):
    return legacy_v3_module().dry_air_mass_flow(*args, **kwargs)


def dynamic_viscosity_air_pa_s(*args, **kwargs):
    return legacy_v3_module().dynamic_viscosity_air_pa_s(*args, **kwargs)
