from __future__ import annotations

from .legacy_v12 import legacy_v12_module


ReceiverBasis = legacy_v12_module().ReceiverBasis
MATERIAL_COLUMNS = list(legacy_v12_module().MATERIAL_COLUMNS)


def make_receiver_basis(*args, **kwargs):
    return legacy_v12_module().make_receiver_basis(*args, **kwargs)


def integrate_coupled_receiver_case(*args, **kwargs):
    return legacy_v12_module().integrate_coupled_receiver_case(*args, **kwargs)


def coupled_local_gate(*args, **kwargs):
    return legacy_v12_module().coupled_local_gate(*args, **kwargs)


def validate_unchanged_solver_sources(*args, **kwargs):
    return legacy_v12_module().validate_unchanged_solver_sources(*args, **kwargs)


def load_json(*args, **kwargs):
    return legacy_v12_module().load_json(*args, **kwargs)


__all__ = [
    "ReceiverBasis",
    "MATERIAL_COLUMNS",
    "make_receiver_basis",
    "integrate_coupled_receiver_case",
    "coupled_local_gate",
    "validate_unchanged_solver_sources",
    "load_json",
]
