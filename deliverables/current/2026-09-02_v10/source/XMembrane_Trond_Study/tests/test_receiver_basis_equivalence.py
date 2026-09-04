from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from heiq.wp1.airside import legacy_v3_module
from heiq.wp1.receiver import (
    ReceiverBasis,
    legacy_v12_module,
    make_receiver_basis,
)
from heiq.wp1.receiver import basis as new


def assert_value_equal(a, b, key=""):
    if isinstance(a, (str, bool)) or a is None:
        assert a == b, key
        return

    assert np.isclose(
        float(a),
        float(b),
        rtol=1e-14,
        atol=1e-14,
    ), key


def assert_dataclass_equal(a, b):
    left = asdict(a)
    right = asdict(b)

    assert left.keys() == right.keys()

    for key in left:
        assert_value_equal(
            left[key],
            right[key],
            key,
        )


def process_basis():
    return SimpleNamespace(
        volume_flow_m3_s=70.7921175,
        dry_air_mass_flow_kg_s=78.812564510,
    )


def base_config(mode):
    return {
        "air": {
            "absolute_pressure_pa": 101325.0,
        },
        "channel": {
            "receiver_temperature_c": 32.0,
            "process_velocity_m_s": 2.0,
            "process_gap_m": 0.002,
            "active_sides_per_process_channel": 2.0,
            "receiver_gap_m": 0.002,
            "receiver_geometry_mode": mode,
            "fixed_receiver_velocity_m_s": 2.0,
        },
    }


TARGET = {
    "target": "O50",
    "computed_water_load_kg_h": 2644.741745,
}

SIZING_TARGET = {
    "target": "O30",
    "computed_water_load_kg_h": 4365.918299,
}

BAND = {
    "inlet_activity": 0.4,
    "maximum_outlet_activity": 0.6,
}


def test_c4a_public_objects_are_native():
    assert (
        ReceiverBasis.__module__
        == "heiq.wp1.receiver.basis"
    )

    assert (
        make_receiver_basis.__module__
        == "heiq.wp1.receiver.basis"
    )


def test_finite_float_matches_legacy_validation():
    old = legacy_v12_module()

    for value in (
        0.0,
        1.0,
        -3.5,
        "42.25",
    ):
        assert (
            new.finite_float(value, "test")
            ==
            old.finite_float(value, "test")
        )

    for value in (
        float("nan"),
        float("inf"),
        float("-inf"),
    ):
        with pytest.raises(ValueError):
            new.finite_float(
                value,
                "test",
            )


def test_humidity_ratio_from_activity_matches_legacy():
    old = legacy_v12_module()
    axial = legacy_v3_module()

    for activity in (
        0.1,
        0.4,
        0.6,
        0.8,
    ):
        actual = (
            new.humidity_ratio_from_activity(
                32.0,
                activity,
                101325.0,
            )
        )

        expected = (
            old.humidity_ratio_from_activity(
                axial,
                32.0,
                activity,
                101325.0,
            )
        )

        assert np.isclose(
            actual,
            expected,
            rtol=0.0,
            atol=0.0,
        )


def test_actual_volume_flow_matches_legacy():
    old = legacy_v12_module()
    axial = legacy_v3_module()

    for mass_flow in (
        1.0,
        20.0,
        100.0,
    ):
        actual = (
            new.actual_volume_flow_from_dry_air(
                mass_flow,
                32.0,
                0.015,
                101325.0,
            )
        )

        expected = (
            old.actual_volume_flow_from_dry_air(
                axial,
                mass_flow,
                32.0,
                0.015,
                101325.0,
            )
        )

        assert np.isclose(
            actual,
            expected,
            rtol=0.0,
            atol=0.0,
        )


def test_water_load_matches_legacy():
    old = legacy_v12_module()

    row = {
        "computed_water_load_kg_h":
            4365.918299,
    }

    assert (
        new.water_load_kg_h(row)
        ==
        old.water_load_kg_h(row)
    )


def test_receiver_basis_matches_legacy_both_geometry_modes():
    old = legacy_v12_module()
    axial = legacy_v3_module()

    for mode in (
        "aligned_equal_total_width",
        "fixed_receiver_velocity_resize_width",
    ):
        config = base_config(mode)

        new_result = make_receiver_basis(
            axial=None,
            process_basis=process_basis(),
            target_row=TARGET,
            receiver_sizing_target_row=(
                SIZING_TARGET
            ),
            band_id="test_band",
            band=BAND,
            capacity_multiplier=1.05,
            flow_arrangement="counter_current",
            base_config=config,
        )

        old_result = old.make_receiver_basis(
            axial=axial,
            process_basis=process_basis(),
            target_row=TARGET,
            receiver_sizing_target_row=(
                SIZING_TARGET
            ),
            band_id="test_band",
            band=BAND,
            capacity_multiplier=1.05,
            flow_arrangement="counter_current",
            base_config=config,
        )

        assert_dataclass_equal(
            new_result,
            old_result,
        )


def test_receiver_basis_module_has_no_legacy_dependency():
    source = Path(new.__file__).read_text()

    assert "legacy_v12_module" not in source
    assert "legacy_v3_module" not in source
    assert (
        "make_wp1_closed_receiver_system_v12"
        not in source
    )
