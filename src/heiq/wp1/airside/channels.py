from __future__ import annotations

from .legacy_v3 import legacy_v3_module


def process_channel_fan(*args, **kwargs):
    return legacy_v3_module().process_channel_fan(*args, **kwargs)
