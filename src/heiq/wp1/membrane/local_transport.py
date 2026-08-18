from __future__ import annotations

import importlib.util
from functools import lru_cache
from pathlib import Path


def repository_root() -> Path:
    return Path(__file__).resolve().parents[4]


def legacy_module_path() -> Path:
    return (
        repository_root()
        / "heiq_pre_receiver_material_analyses"
        / "heiq_pre_receiver_model.py"
    )


@lru_cache(maxsize=1)
def _legacy_v2_module():
    path = legacy_module_path()

    if not path.is_file():
        raise FileNotFoundError(
            f"Canonical V2 implementation not found: {path}"
        )

    spec = importlib.util.spec_from_file_location(
        "_xmembrane_legacy_v2",
        path,
    )

    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load V2 module from {path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_config(*args, **kwargs):
    return _legacy_v2_module().load_config(*args, **kwargs)


def solve_powerlaw_voltage_control(*args, **kwargs):
    return _legacy_v2_module().solve_powerlaw_voltage_control(
        *args,
        **kwargs,
    )


def solve_nafion_voltage_state(*args, **kwargs):
    return _legacy_v2_module().solve_nafion_voltage_state(
        *args,
        **kwargs,
    )


__all__ = [
    "load_config",
    "solve_powerlaw_voltage_control",
    "solve_nafion_voltage_state",
    "legacy_module_path",
]
