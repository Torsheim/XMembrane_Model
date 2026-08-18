from __future__ import annotations

from heiq.wp1.receiver.legacy_v12 import legacy_v12_module


def stack_topology(*args, **kwargs):
    return legacy_v12_module().stack_topology(*args, **kwargs)


__all__ = ["stack_topology"]
