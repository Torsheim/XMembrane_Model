from .channels import channel_pressure_drop_and_fan
from .stack import stack_topology


def add_geometry_and_stack(*args, **kwargs):
    """Temporary compatibility wrapper until C5c."""
    from heiq.wp1.receiver.legacy_v12 import (
        legacy_v12_module,
    )

    return (
        legacy_v12_module()
        .add_geometry_and_stack(
            *args,
            **kwargs,
        )
    )


__all__ = [
    "add_geometry_and_stack",
    "channel_pressure_drop_and_fan",
    "stack_topology",
]
