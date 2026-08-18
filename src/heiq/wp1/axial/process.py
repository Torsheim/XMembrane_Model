from __future__ import annotations

from heiq.wp1.airside.legacy_v3 import legacy_v3_module

from .targets import (
    build_targets,
    reduced_quick_config,
    validate_config,
)


def solve_local_state(*args, **kwargs):
    return legacy_v3_module().solve_local_state(*args, **kwargs)


def integrate_axial_case(*args, **kwargs):
    return legacy_v3_module().integrate_axial_case(*args, **kwargs)


def load_v2_module(*args, **kwargs):
    return legacy_v3_module().load_v2_module(*args, **kwargs)


def load_json(*args, **kwargs):
    return legacy_v3_module().load_json(*args, **kwargs)


__all__ = [
    "validate_config",
    "build_targets",
    "solve_local_state",
    "integrate_axial_case",
    "load_v2_module",
    "load_json",
    "reduced_quick_config",
]
