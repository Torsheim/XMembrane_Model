from __future__ import annotations

from .basis import (
    ReceiverBasis,
    make_receiver_basis,
)
from .legacy_v12 import legacy_v12_module


MATERIAL_COLUMNS = list(
    legacy_v12_module().MATERIAL_COLUMNS
)


def integrate_coupled_receiver_case(
    *args,
    **kwargs,
):
    return (
        legacy_v12_module()
        .integrate_coupled_receiver_case(
            *args,
            **kwargs,
        )
    )


def coupled_local_gate(*args, **kwargs):
    return (
        legacy_v12_module()
        .coupled_local_gate(
            *args,
            **kwargs,
        )
    )


def validate_unchanged_solver_sources(
    *args,
    **kwargs,
):
    return (
        legacy_v12_module()
        .validate_unchanged_solver_sources(
            *args,
            **kwargs,
        )
    )


def load_json(*args, **kwargs):
    return legacy_v12_module().load_json(
        *args,
        **kwargs,
    )


__all__ = [
    "ReceiverBasis",
    "MATERIAL_COLUMNS",
    "make_receiver_basis",
    "integrate_coupled_receiver_case",
    "coupled_local_gate",
    "validate_unchanged_solver_sources",
    "load_json",
]
