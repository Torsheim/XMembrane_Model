import copy
import json
from pathlib import Path

import numpy as np

from heiq.wp1.airside import (
    legacy_v3_module,
)
from heiq.wp1.airside.channels import (
    process_channel_fan as new_process_channel_fan,
)
from heiq.wp1.airside.properties import (
    dry_air_mass_flow,
)


ROOT = Path(__file__).resolve().parents[1]


def config():
    return json.loads(
        (
            ROOT
            / "config"
            / "pre_receiver_axial_v3_config.json"
        ).read_text()
    )


def assert_geometry_equal(new, old):
    assert new.keys() == old.keys()

    for key in new:
        assert np.isclose(
            float(new[key]),
            float(old[key]),
            rtol=1e-14,
            atol=1e-14,
        ), key


def test_process_channel_geometry_matches_legacy():
    old = legacy_v3_module()
    cfg = config()

    new_basis = dry_air_mass_flow(cfg)
    old_basis = old.dry_air_mass_flow(cfg)

    for area in (
        0.0,
        1000.0,
        4500.0,
        6000.0,
        8922.21294,
    ):
        new_result = new_process_channel_fan(
            active_area_m2=area,
            config=cfg,
            basis=new_basis,
        )

        old_result = old.process_channel_fan(
            active_area_m2=area,
            config=cfg,
            basis=old_basis,
        )

        assert_geometry_equal(
            new_result,
            old_result,
        )


def test_process_channel_turbulent_branch_matches_legacy():
    old = legacy_v3_module()

    cfg = config()

    cfg["channel"] = copy.deepcopy(
        cfg["channel"]
    )

    cfg["channel"][
        "process_velocity_m_s"
    ] = 20.0

    new_basis = dry_air_mass_flow(cfg)
    old_basis = old.dry_air_mass_flow(cfg)

    new_result = new_process_channel_fan(
        active_area_m2=6000.0,
        config=cfg,
        basis=new_basis,
    )

    old_result = old.process_channel_fan(
        active_area_m2=6000.0,
        config=cfg,
        basis=old_basis,
    )

    assert (
        new_result[
            "process_channel_reynolds_number"
        ]
        > 2300.0
    )

    assert_geometry_equal(
        new_result,
        old_result,
    )


def test_zero_area_has_zero_length_drop_and_power():
    cfg = config()
    basis = dry_air_mass_flow(cfg)

    result = new_process_channel_fan(
        active_area_m2=0.0,
        config=cfg,
        basis=basis,
    )

    assert (
        result[
            "process_channel_length_m"
        ]
        == 0.0
    )

    assert (
        result[
            "process_pressure_drop_pa"
        ]
        == 0.0
    )

    assert (
        result[
            "process_fan_power_kw"
        ]
        == 0.0
    )
