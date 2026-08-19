from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from heiq.wp1.airside import legacy_v3_path
from heiq.wp1.membrane import (
    legacy_module_path,
    legacy_v2_module,
)
from heiq.wp1.receiver import (
    load_json,
    validate_unchanged_solver_sources,
)

from .prearchitecture import build_context


def repository_root() -> Path:
    return Path(__file__).resolve().parents[4]


def build_repository_context(
    args: Any,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    """Load reviewed repository inputs and build a native study context.

    Legacy numerical source access is confined to the canonical package
    adapters. Workflow entrypoints receive only the native context and no
    V3/V12 script-module compatibility objects.
    """

    root = (
        repository_root()
        if root is None
        else Path(root).resolve()
    )

    v11_dir = (
        root
        / "outputs"
        / "axial_independent_material_sweep_v8"
        / "coarse"
        / "voltage_refinement_v11"
    )
    v12_config_path = (
        root
        / "scripts"
        / "closed_receiver_system_v12_config.json"
    )
    v2_root = (
        root
        / "heiq_pre_receiver_material_analyses"
    )
    v2_path = legacy_module_path().resolve()
    axial_path = legacy_v3_path().resolve()

    expected_v2_path = (
        v2_root
        / "heiq_pre_receiver_model.py"
    ).resolve()
    expected_axial_path = (
        root
        / "scripts"
        / "make_wp1_pre_receiver_axial_v3.py"
    ).resolve()

    if v2_path != expected_v2_path:
        raise RuntimeError(
            "V2 adapter path does not match repository root: "
            f"{v2_path} != {expected_v2_path}"
        )

    if axial_path != expected_axial_path:
        raise RuntimeError(
            "V3 adapter path does not match repository root: "
            f"{axial_path} != {expected_axial_path}"
        )

    validate_unchanged_solver_sources(
        v11_dir,
        axial_path,
        v2_root,
    )

    v2 = legacy_v2_module()
    v2_config = v2.load_config(
        v2_root
        / "config"
        / "default.json"
    )

    cfg12 = load_json(
        v12_config_path
    )
    base = load_json(
        v11_dir
        / "axial_base_config_used.json"
    )
    candidates = pd.read_csv(
        v11_dir
        / "candidate_materials.csv"
    )

    return build_context(
        args,
        cfg12=cfg12,
        base_config=base,
        candidates=candidates,
        v2=v2,
        v2_config=v2_config,
    )


__all__ = [
    "build_repository_context",
    "repository_root",
]
