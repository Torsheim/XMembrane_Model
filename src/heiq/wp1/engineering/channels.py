from __future__ import annotations

from heiq.wp1.receiver.legacy_v12 import legacy_v12_module


def channel_pressure_drop_and_fan(*args, **kwargs):
    return legacy_v12_module().channel_pressure_drop_and_fan(*args, **kwargs)


def add_geometry_and_stack(*args, **kwargs):
    return legacy_v12_module().add_geometry_and_stack(*args, **kwargs)


__all__ = [
    "channel_pressure_drop_and_fan",
    "add_geometry_and_stack",
]
