import copy
from dataclasses import replace
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from heiq.wp1.airside import legacy_v3_module
from heiq.wp1.airside.properties import (
    dry_air_mass_flow,
)
from heiq.wp1.axial import build_targets
from heiq.wp1.receiver import (
    integrate_coupled_receiver_case,
    legacy_v12_module,
    make_receiver_basis,
)
from heiq.wp1.receiver import (
    coupled_integration as new,
)


ROOT = Path(__file__).resolve().parents[1]


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
        rtol=1e-10,
        atol=1e-10,
        equal_nan=True,
    ), key


def assert_mapping_equal(left, right):
    assert left.keys() == right.keys()

    for key in left:
        assert_value_equal(
            left[key],
            right[key],
            key,
        )


def prepare_case():
    old_v12 = legacy_v12_module()
    old_axial = legacy_v3_module()

    config = json.loads(
        (
            ROOT
            / "config"
            / "pre_receiver_axial_v3_config.json"
        ).read_text()
    )

    config = copy.deepcopy(config)

    v12_config = json.loads(
        (
            ROOT
            / "config"
            / "closed_receiver_system_v12_config.json"
        ).read_text()
    )

    config["integration"][
        "mass_balance_relative_tolerance"
    ] = float(
        v12_config["integration"][
            "mass_balance_relative_tolerance"
        ]
    )

    # Keep the equivalence test computationally small while
    # still executing the coupled integration loop.
    config["integration"]["area_limit_m2"] = 500.0
    config["integration"]["area_step_m2"] = 250.0
    config["integration"][
        "minimum_area_step_m2"
    ] = 25.0

    config["channel"][
        "receiver_geometry_mode"
    ] = "fixed_receiver_velocity_resize_width"

    config["channel"][
        "fixed_receiver_velocity_m_s"
    ] = float(
        config["channel"].get(
            "receiver_velocity_m_s",
            2.0,
        )
    )

    v2_root = (
        ROOT
        / "heiq_pre_receiver_material_analyses"
    )

    v2 = old_axial.load_v2_module(
        v2_root
    )

    v2_config = v2.load_config(
        v2_root / "config" / "default.json"
    )

    basis = dry_air_mass_flow(
        config
    )

    targets = build_targets(
        config,
        basis,
        v2_config,
    )

    target = (
        targets
        .set_index("target", drop=False)
        .loc["O30"]
    )

    receiver = make_receiver_basis(
        axial=None,
        process_basis=basis,
        target_row=target,
        receiver_sizing_target_row=target,
        band_id="test_040_060",
        band={
            "inlet_activity": 0.4,
            "maximum_outlet_activity": 0.6,
        },
        capacity_multiplier=1.05,
        flow_arrangement="counter_current",
        base_config=config,
    )

    return (
        old_v12,
        old_axial,
        config,
        v2,
        v2_config,
        basis,
        target,
        receiver,
    )


def test_c4b_public_functions_are_native():
    assert (
        integrate_coupled_receiver_case.__module__
        == "heiq.wp1.receiver.coupled_integration"
    )

    assert (
        new.coupled_local_gate.__module__
        == "heiq.wp1.receiver.coupled_integration"
    )


def test_coupled_local_gate_matches_legacy():
    old = legacy_v12_module()

    cases = [
        {
            "solution_ok": False,
            "solution_status": "test_failure",
        },
        {
            "solution_ok": True,
            "net_flux_mol_m2_s": -1.0,
            "current_density_a_m2": 1.0,
        },
        {
            "solution_ok": True,
            "net_flux_mol_m2_s": 1.0,
            "current_density_a_m2": -1.0,
        },
        {
            "solution_ok": True,
            "net_flux_mol_m2_s": 1.0,
            "current_density_a_m2": 101.0,
        },
        {
            "solution_ok": True,
            "net_flux_mol_m2_s": 1.0,
            "current_density_a_m2": 50.0,
        },
    ]

    for local in cases:
        assert (
            new.coupled_local_gate(
                local,
                100.0,
            )
            ==
            old.coupled_local_gate(
                local,
                100.0,
            )
        )


def test_capacity_insufficient_branch_matches_legacy():
    (
        old_v12,
        old_axial,
        config,
        v2,
        v2_config,
        basis,
        target,
        receiver,
    ) = prepare_case()

    receiver = replace(
        receiver,
        target_capacity_sufficient=False,
    )

    common = dict(
        v2=v2,
        v2_config=v2_config,
        config=config,
        process_basis=basis,
        target_row=target,
        material=material(),
        receiver=receiver,
        terminal_voltage_v=0.98,
        electrode_pair_loss_voltage_v=0.0,
        legacy_series_asr_ohm_m2=1.0e-5,
        added_contact_asr_ohm_m2=0.0,
        power_electronics_efficiency=0.95,
        current_cap_a_m2=1000.0,
        film_scale_factor=1.0,
        record_profile=False,
    )

    new_summary, new_profile = (
        integrate_coupled_receiver_case(
            axial=None,
            **common,
        )
    )

    old_summary, old_profile = (
        old_v12.integrate_coupled_receiver_case(
            axial=old_axial,
            **common,
        )
    )

    assert_mapping_equal(
        new_summary,
        old_summary,
    )

    assert new_profile.empty
    assert old_profile.empty


def test_coupled_integration_matches_legacy():
    (
        old_v12,
        old_axial,
        config,
        v2,
        v2_config,
        basis,
        target,
        receiver,
    ) = prepare_case()

    common = dict(
        v2=v2,
        v2_config=v2_config,
        config=config,
        process_basis=basis,
        target_row=target,
        material=material(),
        receiver=receiver,
        terminal_voltage_v=0.98,
        electrode_pair_loss_voltage_v=0.0,
        legacy_series_asr_ohm_m2=1.0e-5,
        added_contact_asr_ohm_m2=0.0,
        power_electronics_efficiency=0.95,
        current_cap_a_m2=1000.0,
        film_scale_factor=1.0,
        record_profile=True,
    )

    new_summary, new_profile = (
        integrate_coupled_receiver_case(
            axial=None,
            **common,
        )
    )

    old_summary, old_profile = (
        old_v12.integrate_coupled_receiver_case(
            axial=old_axial,
            **common,
        )
    )

    assert_mapping_equal(
        new_summary,
        old_summary,
    )

    pd.testing.assert_frame_equal(
        new_profile.reset_index(drop=True),
        old_profile.reset_index(drop=True),
        check_exact=False,
        rtol=1e-10,
        atol=1e-10,
    )


def test_coupled_integration_has_no_legacy_dependency():
    source = Path(new.__file__).read_text()

    assert "legacy_v12_module" not in source
    assert "legacy_v3_module" not in source

    # Native receiver integration may legitimately import from
    # heiq.wp1.axial.*, but it must not access the old runtime
    # axial ModuleType object.
    assert "axial.ACTIVITY_EPS" not in source
    assert "axial.activity_from_t_w" not in source
    assert "axial.solve_local_state" not in source

    assert (
        "make_wp1_closed_receiver_system_v12"
        not in source
    )
