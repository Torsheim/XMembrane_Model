import json
from contextlib import contextmanager
from pathlib import Path

import numpy as np

from heiq.wp1.airside import legacy_v3_module
from heiq.wp1.airside.properties import (
    humidity_ratio_from_t_rh,
)
from heiq.wp1.axial import solve_local_state
from heiq.wp1.receiver import (
    integrate_coupled_receiver_case,
)


ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def patched_legacy_films(
    axial,
    *,
    process_factor,
    receiver_factor,
):
    original = axial.calculate_film_state

    def patched(**kwargs):
        side = str(
            kwargs.get("side", "")
        ).strip().lower()

        factor = (
            process_factor
            if side in {
                "source",
                "process",
                "process_side",
            }
            else receiver_factor
        )

        copied = dict(kwargs)

        copied["scale_factor"] = (
            float(copied["scale_factor"])
            * float(factor)
        )

        return original(**copied)

    axial.calculate_film_state = patched

    try:
        yield
    finally:
        axial.calculate_film_state = original


def load_case():
    axial = legacy_v3_module()

    config = json.loads(
        (
            ROOT
            / "config"
            / "pre_receiver_axial_v3_config.json"
        ).read_text()
    )

    v2_root = (
        ROOT
        / "heiq_pre_receiver_material_analyses"
    )

    v2 = axial.load_v2_module(
        v2_root
    )

    v2_config = v2.load_config(
        v2_root
        / "config"
        / "default.json"
    )

    pressure = float(
        config["air"]["absolute_pressure_pa"]
    )

    humidity_ratio = humidity_ratio_from_t_rh(
        32.0,
        0.80,
        pressure,
    )

    material = {
        "model": "powerlaw",
        "water_drag": 100.060787,
        "water_diffusivity_m2_s":
            1.597880e-14,
        "conductivity_s_m":
            23.171887,
        "dry_thickness_um":
            36.9137,
        "water_capacity_mol_m3_activity":
            10000.0,
        "diffusivity_activity_exponent":
            2.0,
        "conductivity_activity_exponent":
            4.0,
        "capacity_activity_exponent":
            0.0,
    }

    return (
        axial,
        config,
        v2,
        v2_config,
        humidity_ratio,
        material,
    )


def assert_local_equal(left, right):
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

        assert np.isclose(
            af,
            bf,
            rtol=1e-12,
            atol=1e-12,
            equal_nan=True,
        ), key


def test_independent_film_factors_match_legacy_monkeypatch():
    (
        axial,
        config,
        v2,
        v2_config,
        humidity_ratio,
        material,
    ) = load_case()

    cases = [
        (5.0, 1.0),
        (1.0, 5.0),
        (5.0, 5.0),
    ]

    for (
        process_factor,
        receiver_factor,
    ) in cases:
        native = solve_local_state(
            v2=v2,
            v2_config=v2_config,
            material=material,
            source_temperature_c=32.0,
            source_humidity_ratio=humidity_ratio,
            receiver_activity=0.4,
            terminal_voltage_v=0.98,
            fixed_loss_voltage_v=0.0,
            series_asr_ohm_m2=1.0e-5,
            film_scale_factor=1.0,
            config=config,
            process_film_scale_factor=(
                process_factor
            ),
            receiver_film_scale_factor=(
                receiver_factor
            ),
        )

        with patched_legacy_films(
            axial,
            process_factor=process_factor,
            receiver_factor=receiver_factor,
        ):
            legacy = (
                axial.solve_local_state(
                    v2=v2,
                    v2_config=v2_config,
                    material=material,
                    source_temperature_c=32.0,
                    source_humidity_ratio=humidity_ratio,
                    receiver_activity=0.4,
                    terminal_voltage_v=0.98,
                    fixed_loss_voltage_v=0.0,
                    series_asr_ohm_m2=1.0e-5,
                    film_scale_factor=1.0,
                    config=config,
                )
            )

        assert_local_equal(
            native,
            legacy,
        )


def test_default_film_api_remains_backward_compatible():
    (
        _,
        config,
        v2,
        v2_config,
        humidity_ratio,
        material,
    ) = load_case()

    original = solve_local_state(
        v2=v2,
        v2_config=v2_config,
        material=material,
        source_temperature_c=32.0,
        source_humidity_ratio=humidity_ratio,
        receiver_activity=0.4,
        terminal_voltage_v=0.98,
        fixed_loss_voltage_v=0.0,
        series_asr_ohm_m2=1.0e-5,
        film_scale_factor=5.0,
        config=config,
    )

    explicit = solve_local_state(
        v2=v2,
        v2_config=v2_config,
        material=material,
        source_temperature_c=32.0,
        source_humidity_ratio=humidity_ratio,
        receiver_activity=0.4,
        terminal_voltage_v=0.98,
        fixed_loss_voltage_v=0.0,
        series_asr_ohm_m2=1.0e-5,
        film_scale_factor=5.0,
        config=config,
        process_film_scale_factor=None,
        receiver_film_scale_factor=None,
    )

    assert_local_equal(
        original,
        explicit,
    )


def test_coupled_integrator_exposes_independent_film_controls():
    import inspect

    signature = inspect.signature(
        integrate_coupled_receiver_case
    )

    assert (
        "process_film_scale_factor"
        in signature.parameters
    )

    assert (
        "receiver_film_scale_factor"
        in signature.parameters
    )
