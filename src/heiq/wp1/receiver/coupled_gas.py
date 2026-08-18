from __future__ import annotations

from .basis import (
    ReceiverBasis,
    make_receiver_basis,
)
from .coupled_integration import (
    MATERIAL_COLUMNS,
    coupled_local_gate,
    integrate_coupled_receiver_case,
)
from .legacy_v12 import legacy_v12_module


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
