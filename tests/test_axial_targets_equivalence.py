import json
from pathlib import Path

import pandas as pd

from heiq.wp1.airside import legacy_v3_module
from heiq.wp1.airside.properties import dry_air_mass_flow
from heiq.wp1.axial import (
    build_targets,
    reduced_quick_config,
    validate_config,
)
from heiq.wp1.axial import targets as new_targets


ROOT = Path(__file__).resolve().parents[1]


def load_config():
    return json.loads(
        (
            ROOT
            / "config"
            / "pre_receiver_axial_v3_config.json"
        ).read_text()
    )


def load_v2():
    old = legacy_v3_module()

    root = ROOT / "heiq_pre_receiver_material_analyses"

    module = old.load_v2_module(root)
    config = module.load_config(
        root / "config" / "default.json"
    )

    return module, config


def test_c3a_functions_are_native_package_implementations():
    assert build_targets.__module__ == "heiq.wp1.axial.targets"
    assert validate_config.__module__ == "heiq.wp1.axial.targets"
    assert reduced_quick_config.__module__ == "heiq.wp1.axial.targets"


def test_validate_config_matches_legacy_reference():
    old = legacy_v3_module()
    config = load_config()

    assert validate_config(config) is None
    assert old.validate_config(config) is None


def test_build_targets_matches_legacy_exactly():
    old = legacy_v3_module()
    config = load_config()

    _, v2_config = load_v2()

    new_basis = dry_air_mass_flow(config)
    old_basis = old.dry_air_mass_flow(config)

    new_result = build_targets(
        config,
        new_basis,
        v2_config,
    )

    old_result = old.build_targets(
        config,
        old_basis,
        v2_config,
    )

    pd.testing.assert_frame_equal(
        new_result.reset_index(drop=True),
        old_result.reset_index(drop=True),
        check_exact=True,
    )


def test_reduced_quick_config_matches_legacy_exactly():
    old = legacy_v3_module()
    config = load_config()

    new_result = reduced_quick_config(config)
    old_result = old.reduced_quick_config(config)

    assert new_result == old_result

    # Both implementations must leave the supplied config untouched.
    assert config == load_config()


def test_targets_module_has_no_legacy_loader_dependency():
    source = Path(new_targets.__file__).read_text()

    assert "legacy_v3_module" not in source
    assert "make_wp1_pre_receiver_axial_v3" not in source
