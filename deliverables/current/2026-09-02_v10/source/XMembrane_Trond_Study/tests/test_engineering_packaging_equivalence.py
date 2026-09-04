import json
import math
from pathlib import Path

import numpy as np

from heiq.wp1.airside import legacy_v3_module
from heiq.wp1.airside.properties import dry_air_mass_flow
from heiq.wp1.engineering import add_geometry_and_stack
from heiq.wp1.engineering import packaging as new
from heiq.wp1.receiver import legacy_v12_module


ROOT = Path(__file__).resolve().parents[1]


def load_configs():
    base_config = json.loads(
        (
            ROOT
            / "config"
            / "pre_receiver_axial_v3_config.json"
        ).read_text()
    )

    v12_config = json.loads(
        (
            ROOT
            / "config"
            / "closed_receiver_system_v12_config.json"
        ).read_text()
    )

    return base_config, v12_config


def assert_mapping_equal(left, right):
    assert left.keys() == right.keys()

    for key in left:
        a = left[key]
        b = right[key]

        if isinstance(a, (str, bool)) or a is None:
            assert a == b, key
            continue

        try:
            af = float(a)
            bf = float(b)
        except (TypeError, ValueError):
            assert a == b, key
            continue

        if math.isnan(af) and math.isnan(bf):
            continue

        assert np.isclose(
            af,
            bf,
            rtol=1e-13,
            atol=1e-13,
            equal_nan=True,
        ), key


def positive_row():
    return {
        "target": "O30",
        "required_active_area_m2": 8922.21294,
        "receiver_total_channel_width_m": 18000.0,
        "receiver_velocity_m_s": 2.0,
        "selected_actual_volume_flow_m3_s": 176.0,
        "temperature_c": 32.0,
        "pressure_pa": 101325.0,
        "inlet_humidity_ratio_kg_kg_da": 0.015,
        "terminal_voltage_v": 0.98,
        "integrated_current_a": 64915.0,
        "maximum_local_current_density_a_m2": 21.224,
    }


def test_c5c_packaging_is_native():
    assert (
        add_geometry_and_stack.__module__
        == "heiq.wp1.engineering.packaging"
    )


def test_positive_geometry_and_stack_matches_legacy():
    old_v12 = legacy_v12_module()
    old_axial = legacy_v3_module()

    base_config, v12_config = load_configs()

    actual = add_geometry_and_stack(
        row=dict(positive_row()),
        axial=None,
        process_basis=dry_air_mass_flow(base_config),
        base_config=base_config,
        v12_config=v12_config,
    )

    expected = old_v12.add_geometry_and_stack(
        row=dict(positive_row()),
        axial=old_axial,
        process_basis=old_axial.dry_air_mass_flow(
            base_config
        ),
        base_config=base_config,
        v12_config=v12_config,
    )

    assert_mapping_equal(actual, expected)


def test_zero_area_branch_matches_legacy():
    old_v12 = legacy_v12_module()
    old_axial = legacy_v3_module()

    base_config, v12_config = load_configs()

    row = {
        **positive_row(),
        "required_active_area_m2": 0.0,
    }

    actual = add_geometry_and_stack(
        row=dict(row),
        axial=None,
        process_basis=dry_air_mass_flow(base_config),
        base_config=base_config,
        v12_config=v12_config,
    )

    expected = old_v12.add_geometry_and_stack(
        row=dict(row),
        axial=old_axial,
        process_basis=old_axial.dry_air_mass_flow(
            base_config
        ),
        base_config=base_config,
        v12_config=v12_config,
    )

    assert_mapping_equal(actual, expected)


def test_packaging_has_no_legacy_dependency():
    source = Path(new.__file__).read_text()

    assert "legacy_v12_module" not in source
    assert "legacy_v3_module" not in source
    assert "axial.process_channel_fan" not in source
    assert (
        "make_wp1_closed_receiver_system_v12"
        not in source
    )
