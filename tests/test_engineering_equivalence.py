import json
from pathlib import Path

import numpy as np

from heiq.wp1.airside import legacy_v3_module
from heiq.wp1.engineering import (
    channel_pressure_drop_and_fan,
    stack_topology,
)
from heiq.wp1.engineering import channels as new_channels
from heiq.wp1.engineering import stack as new_stack
from heiq.wp1.receiver import legacy_v12_module


ROOT = Path(__file__).resolve().parents[1]


def assert_mapping_equal(left, right):
    assert left.keys() == right.keys()

    for key in left:
        a = left[key]
        b = right[key]

        if isinstance(a, (str, bool)) or a is None:
            assert a == b, key
        else:
            assert np.isclose(
                float(a),
                float(b),
                rtol=1e-14,
                atol=1e-14,
            ), key


def stack_config():
    return json.loads(
        (
            ROOT
            / "config"
            / "closed_receiver_system_v12_config.json"
        ).read_text()
    )["stack"]


def test_c5_low_level_engineering_is_native():
    assert (
        channel_pressure_drop_and_fan.__module__
        == "heiq.wp1.engineering.channels"
    )

    assert (
        stack_topology.__module__
        == "heiq.wp1.engineering.stack"
    )


def test_channel_pressure_drop_matches_legacy():
    old_v12 = legacy_v12_module()
    old_axial = legacy_v3_module()

    for velocity in (
        2.0,
        20.0,
    ):
        common = dict(
            active_area_m2=8922.21294,
            total_channel_width_m=18000.0,
            active_sides=2.0,
            gap_m=0.002,
            velocity_m_s=velocity,
            volume_flow_m3_s=176.0,
            temperature_c=32.0,
            pressure_pa=101325.0,
            humidity_ratio_kg_kg_da=0.015,
            fan_efficiency=0.65,
        )

        actual = (
            channel_pressure_drop_and_fan(
                axial=None,
                **common,
            )
        )

        expected = (
            old_v12.channel_pressure_drop_and_fan(
                axial=old_axial,
                **common,
            )
        )

        assert_mapping_equal(
            actual,
            expected,
        )


def test_stack_topology_matches_legacy_reference_cases():
    old = legacy_v12_module()
    config = stack_config()

    cases = [
        dict(
            required_area_m2=0.0,
            integrated_current_a=0.0,
            maximum_current_density_a_m2=0.0,
            cell_terminal_voltage_v=0.98,
        ),
        dict(
            required_area_m2=8922.21294,
            integrated_current_a=64915.0,
            maximum_current_density_a_m2=21.224,
            cell_terminal_voltage_v=0.98,
        ),
        dict(
            required_area_m2=4500.0,
            integrated_current_a=40000.0,
            maximum_current_density_a_m2=35.0,
            cell_terminal_voltage_v=1.75,
        ),
        dict(
            required_area_m2=10000.0,
            integrated_current_a=1.0e9,
            maximum_current_density_a_m2=1.0e6,
            cell_terminal_voltage_v=2.0,
        ),
    ]

    for case in cases:
        actual = stack_topology(
            **case,
            stack_config=config,
        )

        expected = old.stack_topology(
            **case,
            stack_config=config,
        )

        assert_mapping_equal(
            actual,
            expected,
        )


def test_channel_validation_matches_legacy():
    old_v12 = legacy_v12_module()
    old_axial = legacy_v3_module()

    common = dict(
        active_area_m2=100.0,
        total_channel_width_m=10.0,
        active_sides=2.0,
        gap_m=0.002,
        velocity_m_s=0.0,
        volume_flow_m3_s=1.0,
        temperature_c=32.0,
        pressure_pa=101325.0,
        humidity_ratio_kg_kg_da=0.015,
        fan_efficiency=0.65,
    )

    for fn, axial in (
        (
            channel_pressure_drop_and_fan,
            None,
        ),
        (
            old_v12.channel_pressure_drop_and_fan,
            old_axial,
        ),
    ):
        try:
            fn(
                axial=axial,
                **common,
            )
        except ValueError as exc:
            assert (
                "must be positive"
                in str(exc)
            )
        else:
            raise AssertionError(
                "Expected ValueError"
            )


def test_low_level_engineering_has_no_legacy_dependency():
    channel_source = Path(
        new_channels.__file__
    ).read_text()

    stack_source = Path(
        new_stack.__file__
    ).read_text()

    for source in (
        channel_source,
        stack_source,
    ):
        assert (
            "legacy_v12_module"
            not in source
        )

        assert (
            "legacy_v3_module"
            not in source
        )

        assert (
            "make_wp1_closed_receiver_system_v12"
            not in source
        )
