import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from heiq.wp1.airside import legacy_v3_module
from heiq.wp1.airside.properties import (
    dry_air_mass_flow,
)
from heiq.wp1.axial import (
    build_targets,
    integrate_axial_case,
)
from heiq.wp1.axial import integration as new


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

    root = (
        ROOT
        / "heiq_pre_receiver_material_analyses"
    )

    v2 = old.load_v2_module(root)

    v2_config = v2.load_config(
        root / "config" / "default.json"
    )

    return v2, v2_config


def material():
    return {
        "name": "terminal1_optimum_test",
        "model": "powerlaw",
        "water_drag": 100.060787,
        "water_diffusivity_m2_s": 1.597880e-14,
        "conductivity_s_m": 23.171887,
        "dry_thickness_um": 36.9137,
        "water_capacity_mol_m3_activity": 10000.0,
        "diffusivity_activity_exponent": 2.0,
        "conductivity_activity_exponent": 4.0,
        "capacity_activity_exponent": 0.0,
    }


def assert_value_equal(a, b, key=""):
    if isinstance(a, (str, bool)) or a is None:
        assert a == b, key
        return

    try:
        af = float(a)
        bf = float(b)
    except (TypeError, ValueError):
        assert a == b, key
        return

    if math.isnan(af) and math.isnan(bf):
        return

    assert np.isclose(
        af,
        bf,
        rtol=1e-12,
        atol=1e-12,
        equal_nan=True,
    ), key


def assert_summary_equal(new_result, old_result):
    assert new_result.keys() == old_result.keys()

    for key in new_result:
        assert_value_equal(
            new_result[key],
            old_result[key],
            key,
        )


def prepare_case():
    old = legacy_v3_module()

    config = load_config()
    v2, v2_config = load_v2()

    new_basis = dry_air_mass_flow(config)
    old_basis = old.dry_air_mass_flow(config)

    new_targets = build_targets(
        config,
        new_basis,
        v2_config,
    )

    old_targets = old.build_targets(
        config,
        old_basis,
        v2_config,
    )

    new_target = (
        new_targets
        .set_index("target", drop=False)
        .loc["O30"]
    )

    old_target = (
        old_targets
        .set_index("target", drop=False)
        .loc["O30"]
    )

    return (
        old,
        config,
        v2,
        v2_config,
        new_basis,
        old_basis,
        new_target,
        old_target,
    )


def test_c3c_integrator_is_native_package_implementation():
    assert (
        integrate_axial_case.__module__
        == "heiq.wp1.axial.integration"
    )


def test_axial_integration_summary_matches_legacy():
    (
        old,
        config,
        v2,
        v2_config,
        new_basis,
        old_basis,
        new_target,
        old_target,
    ) = prepare_case()

    common = dict(
        v2=v2,
        v2_config=v2_config,
        config=config,
        material=material(),
        receiver_label="receiver_040",
        receiver_activity=0.4,
        terminal_voltage_v=0.98,
        fixed_loss_voltage_v=0.0,
        series_asr_ohm_m2=1.0e-5,
        power_electronics_efficiency=0.95,
        current_cap_a_m2=1000.0,
        film_scale_factor=1.0,
        thermal_mode="isothermal",
        record_profile=False,
    )

    new_summary, new_profile = (
        integrate_axial_case(
            basis=new_basis,
            target_row=new_target,
            **common,
        )
    )

    old_summary, old_profile = (
        old.integrate_axial_case(
            basis=old_basis,
            target_row=old_target,
            **common,
        )
    )

    assert_summary_equal(
        new_summary,
        old_summary,
    )

    assert new_profile.empty
    assert old_profile.empty


def test_axial_profile_matches_legacy():
    (
        old,
        config,
        v2,
        v2_config,
        new_basis,
        old_basis,
        new_target,
        old_target,
    ) = prepare_case()

    common = dict(
        v2=v2,
        v2_config=v2_config,
        config=config,
        material=material(),
        receiver_label="receiver_040",
        receiver_activity=0.4,
        terminal_voltage_v=0.98,
        fixed_loss_voltage_v=0.0,
        series_asr_ohm_m2=1.0e-5,
        power_electronics_efficiency=0.95,
        current_cap_a_m2=1000.0,
        film_scale_factor=1.0,
        thermal_mode="isothermal",
        record_profile=True,
    )

    new_summary, new_profile = (
        integrate_axial_case(
            basis=new_basis,
            target_row=new_target,
            **common,
        )
    )

    old_summary, old_profile = (
        old.integrate_axial_case(
            basis=old_basis,
            target_row=old_target,
            **common,
        )
    )

    assert_summary_equal(
        new_summary,
        old_summary,
    )

    pd.testing.assert_frame_equal(
        new_profile.reset_index(drop=True),
        old_profile.reset_index(drop=True),
        check_exact=False,
        rtol=1e-12,
        atol=1e-12,
    )


def test_integration_module_has_no_legacy_dependency():
    source = Path(new.__file__).read_text()

    assert "legacy_v3_module" not in source
    assert (
        "make_wp1_pre_receiver_axial_v3"
        not in source
    )
