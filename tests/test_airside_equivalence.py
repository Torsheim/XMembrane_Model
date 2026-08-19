from dataclasses import asdict
import json
from pathlib import Path

import numpy as np

from heiq.wp1.airside import legacy_v3_module
from heiq.wp1.airside import properties as new


ROOT = Path(__file__).resolve().parents[1]


def assert_values_equal(new_value, old_value):
    if isinstance(new_value, str):
        assert new_value == old_value
    elif new_value is None:
        assert old_value is None
    else:
        assert np.isclose(
            float(new_value),
            float(old_value),
            rtol=1e-14,
            atol=1e-14,
        )


def test_scalar_airside_properties_match_legacy_v3():
    old = legacy_v3_module()

    pressure = 101325.0

    for temperature in (-10.0, 0.0, 20.0, 32.0, 45.0):
        assert_values_equal(
            new.saturation_vapour_pressure_pa(temperature),
            old.saturation_vapour_pressure_pa(temperature),
        )

        assert_values_equal(
            new.dynamic_viscosity_air_pa_s(temperature),
            old.dynamic_viscosity_air_pa_s(temperature),
        )

        assert_values_equal(
            new.water_vapour_diffusivity_air_m2_s(
                temperature,
                pressure,
            ),
            old.water_vapour_diffusivity_air_m2_s(
                temperature,
                pressure,
            ),
        )

        for rh in (0.2, 0.5, 0.8):
            w_new = new.humidity_ratio_from_t_rh(
                temperature,
                rh,
                pressure,
            )

            w_old = old.humidity_ratio_from_t_rh(
                temperature,
                rh,
                pressure,
            )

            assert_values_equal(w_new, w_old)

            assert_values_equal(
                new.vapour_pressure_from_humidity_ratio(
                    w_new,
                    pressure,
                ),
                old.vapour_pressure_from_humidity_ratio(
                    w_old,
                    pressure,
                ),
            )

            assert_values_equal(
                new.activity_from_t_w(
                    temperature,
                    w_new,
                    pressure,
                ),
                old.activity_from_t_w(
                    temperature,
                    w_old,
                    pressure,
                ),
            )

            assert_values_equal(
                new.relative_humidity_from_t_w(
                    temperature,
                    w_new,
                    pressure,
                ),
                old.relative_humidity_from_t_w(
                    temperature,
                    w_old,
                    pressure,
                ),
            )

            assert_values_equal(
                new.moist_air_enthalpy_kj_kg_da(
                    temperature,
                    w_new,
                ),
                old.moist_air_enthalpy_kj_kg_da(
                    temperature,
                    w_old,
                ),
            )


def test_dry_air_mass_flow_matches_legacy_v3():
    old = legacy_v3_module()

    config = json.loads(
        (
            ROOT
            / "config"
            / "pre_receiver_axial_v3_config.json"
        ).read_text()
    )

    new_basis = new.dry_air_mass_flow(config)
    old_basis = old.dry_air_mass_flow(config)

    new_values = asdict(new_basis)
    old_values = asdict(old_basis)

    assert new_values.keys() == old_values.keys()

    for key in new_values:
        assert_values_equal(
            new_values[key],
            old_values[key],
        )


def test_sherwood_correlations_match_legacy_v3():
    old = legacy_v3_module()

    for reynolds in (
        100.0,
        495.0,
        2300.0,
        3000.0,
        4000.0,
        10000.0,
    ):
        for schmidt in (0.5, 0.8, 1.0):
            assert (
                new.sherwood_parallel_plate(
                    reynolds,
                    schmidt,
                )
                ==
                old.sherwood_parallel_plate(
                    reynolds,
                    schmidt,
                )
            )


def test_film_state_matches_legacy_v3():
    old = legacy_v3_module()

    for velocity in (0.5, 2.0, 20.0):
        kwargs = dict(
            side="process",
            temperature_c=32.0,
            velocity_m_s=velocity,
            gap_m=0.002,
            pressure_pa=101325.0,
            scale_factor=1.0,
        )

        new_state = asdict(
            new.calculate_film_state(**kwargs)
        )

        old_state = asdict(
            old.calculate_film_state(**kwargs)
        )

        assert new_state.keys() == old_state.keys()

        for key in new_state:
            assert_values_equal(
                new_state[key],
                old_state[key],
            )
