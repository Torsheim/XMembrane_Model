from __future__ import annotations

import importlib.util
import sys
from functools import lru_cache
from pathlib import Path


def repository_root() -> Path:
    return Path(__file__).resolve().parents[4]


def legacy_v12_path() -> Path:
    return (
        repository_root()
        / "scripts"
        / "make_wp1_closed_receiver_system_v12.py"
    )


@lru_cache(maxsize=1)
def legacy_v12_module():
    path = legacy_v12_path()

    if not path.is_file():
        raise FileNotFoundError(
            f"Canonical V12 implementation not found: {path}"
        )

    name = "_xmembrane_legacy_v12"
    spec = importlib.util.spec_from_file_location(name, path)

    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load V12 module from {path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


__all__ = [
    "legacy_v12_module",
    "legacy_v12_path",
]
