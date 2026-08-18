import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from heiq.wp1.membrane import load_config
from heiq.wp1.studies import prearchitecture as workflow


ROOT = Path(__file__).resolve().parents[1]


def make_context():
    cfg12 = json.loads(
        (
            ROOT
            / "config"
            / "closed_receiver_system_v12_config.json"
        ).read_text()
    )

    base = json.loads(
        (
            ROOT
            / "data"
            / "reference"
            / "v11_compat"
            / "axial_base_config_used.json"
        ).read_text()
    )

    candidates = pd.read_csv(
        ROOT
        / "data"
        / "reference"
        / "v11_compat"
        / "candidate_materials.csv"
    )

    v2_config = load_config(
        ROOT
        / "heiq_pre_receiver_material_analyses"
        / "config"
        / "default.json"
    )

    args = SimpleNamespace(
        receiver_band="bridge_40_to_60",
        receiver_temperature_c=None,
        area_max_m2=9000.0,
    )

    return workflow.build_context(
        args,
        cfg12=cfg12,
        base_config=base,
        candidates=candidates,
        v2=None,
        v2_config=v2_config,
    )


def test_workflow_package_has_no_legacy_script_dependency():
    source = Path(
        workflow.__file__
    ).read_text()

    for forbidden in (
        "legacy_v3_module",
        "legacy_v12_module",
        "spec_from_file_location",
        "make_wp1_pre_receiver_axial_v3",
        "make_wp1_closed_receiver_system_v12",
    ):
        assert forbidden not in source


def test_workflow_context_preserves_reference_targets():
    ctx = make_context()

    assert np.isclose(
        float(
            ctx["targets"]["O50"][
                "computed_water_load_kg_h"
            ]
        ),
        2644.741745,
        rtol=2e-6,
    )

    assert np.isclose(
        float(
            ctx["targets"]["O30"][
                "computed_water_load_kg_h"
            ]
        ),
        4365.918299,
        rtol=2e-6,
    )

    assert (
        str(
            ctx["m11675"]["material_id"]
        )
        == "M11675"
    )


def test_workflow_material_builder_preserves_canonical_columns():
    ctx = make_context()

    material = workflow.make_material(
        ctx,
        drag=123.0,
    )

    assert material["model"] == "powerlaw"
    assert material["water_drag"] == 123.0

    for name in workflow.MATERIAL_COLUMNS:
        assert name in material
