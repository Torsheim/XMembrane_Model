from pathlib import Path

import numpy as np
import pandas as pd

from heiq.wp1.airside import dry_air_mass_flow, legacy_v3_module
from heiq.wp1.axial import (
    build_targets,
    integrate_axial_case,
    load_json,
    load_v2_module,
    reduced_quick_config,
    solve_local_state,
    validate_config,
)


ROOT = Path(__file__).resolve().parents[1]


def _config():
    return load_json(ROOT / "config" / "pre_receiver_axial_v3_config.json")


def _v2():
    root = ROOT / "heiq_pre_receiver_material_analyses"
    module = load_v2_module(root)
    config = module.load_config(root / "config" / "default.json")
    return module, config


def test_axial_public_api_is_available():
    assert callable(validate_config)
    assert callable(build_targets)
    assert callable(solve_local_state)
    assert callable(integrate_axial_case)
    assert callable(load_v2_module)
    assert callable(reduced_quick_config)


def test_axial_config_validation_passes_reference_config():
    config = _config()
    assert validate_config(config) is None


def test_axial_target_builder_matches_legacy_v3_exactly():
    config = _config()
    v2, v2_config = _v2()
    basis = dry_air_mass_flow(config)

    wrapped = build_targets(config, basis, v2_config)
    legacy = legacy_v3_module().build_targets(config, basis, v2_config)

    pd.testing.assert_frame_equal(
        wrapped.reset_index(drop=True),
        legacy.reset_index(drop=True),
        check_exact=True,
    )


def test_reference_target_water_loads_are_preserved():
    config = _config()
    v2, v2_config = _v2()
    basis = dry_air_mass_flow(config)
    targets = build_targets(config, basis, v2_config)

    by_target = targets.set_index("target")

    assert np.isclose(
        float(by_target.loc["O50", "computed_water_load_kg_h"]),
        2644.741745,
        rtol=2e-6,
    )

    assert np.isclose(
        float(by_target.loc["O30", "computed_water_load_kg_h"]),
        4365.918299,
        rtol=2e-6,
    )
