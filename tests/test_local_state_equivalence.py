import json
import math
from pathlib import Path

import numpy as np

from heiq.wp1.airside import legacy_v3_module
from heiq.wp1.airside.properties import (
    calculate_film_state,
    humidity_ratio_from_t_rh,
)
from heiq.wp1.axial import solve_local_state
from heiq.wp1.axial import local_state as new


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

    v2 = old.load_v2_module(root)

    v2_config = v2.load_config(
        root / "config" / "default.json"
    )

    return v2, v2_config


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

    assert np.isclose(
        af,
        bf,
        rtol=1e-13,
        atol=1e-13,
        equal_nan=True,
    ), key


def assert_mapping_equal(new_result, old_result):
    assert new_result.keys() == old_result.keys()

    for key in new_result:
        assert_value_equal(
            new_result[key],
            old_result[key],
            key,
        )


def common_state():
    config = load_config()

    pressure = float(
        config["air"]["absolute_pressure_pa"]
    )

    humidity_ratio = humidity_ratio_from_t_rh(
        32.0,
        0.80,
        pressure,
    )

    return config, humidity_ratio


def test_c3b_solver_is_native_package_implementation():
    assert (
        solve_local_state.__module__
        == "heiq.wp1.axial.local_state"
    )


def test_status_category_matches_legacy():
    old = legacy_v3_module()

    cases = [
        ("converged", True),
        ("below_reversible_voltage", False),
        ("above_current_solver_ceiling", False),
        ("profile_bracket_failed", False),
        ("voltage_root_not_converged", False),
        ("no_positive_current_at_applied_voltage", False),
        ("activity_profile_out_of_bounds", False),
        ("bvp_failed_example", False),
        ("something_new", False),
    ]

    for raw_status, solution_ok in cases:
        assert (
            new.status_category(
                raw_status,
                solution_ok,
            )
            ==
            old.status_category(
                raw_status,
                solution_ok,
            )
        )


def test_make_local_config_matches_legacy_exactly():
    old = legacy_v3_module()

    _, v2_config = load_v2()
    config, _ = common_state()

    pressure = float(
        config["air"]["absolute_pressure_pa"]
    )

    new_source_film = calculate_film_state(
        side="process",
        temperature_c=32.0,
        velocity_m_s=float(
            config["channel"]["process_velocity_m_s"]
        ),
        gap_m=float(
            config["channel"]["process_gap_m"]
        ),
        pressure_pa=pressure,
        scale_factor=1.0,
    )

    new_receiver_film = calculate_film_state(
        side="receiver",
        temperature_c=float(
            config["channel"]["receiver_temperature_c"]
        ),
        velocity_m_s=float(
            config["channel"]["receiver_velocity_m_s"]
        ),
        gap_m=float(
            config["channel"]["receiver_gap_m"]
        ),
        pressure_pa=pressure,
        scale_factor=1.0,
    )

    old_source_film = old.calculate_film_state(
        side="process",
        temperature_c=32.0,
        velocity_m_s=float(
            config["channel"]["process_velocity_m_s"]
        ),
        gap_m=float(
            config["channel"]["process_gap_m"]
        ),
        pressure_pa=pressure,
        scale_factor=1.0,
    )

    old_receiver_film = old.calculate_film_state(
        side="receiver",
        temperature_c=float(
            config["channel"]["receiver_temperature_c"]
        ),
        velocity_m_s=float(
            config["channel"]["receiver_velocity_m_s"]
        ),
        gap_m=float(
            config["channel"]["receiver_gap_m"]
        ),
        pressure_pa=pressure,
        scale_factor=1.0,
    )

    new_result = new.make_local_config(
        v2_config,
        temperature_c=32.0,
        source_activity=0.8,
        receiver_activity=0.4,
        source_film=new_source_film,
        receiver_film=new_receiver_film,
        fixed_loss_voltage_v=0.0,
        series_asr_ohm_m2=1.0e-5,
    )

    old_result = old.make_local_config(
        v2_config,
        temperature_c=32.0,
        source_activity=0.8,
        receiver_activity=0.4,
        source_film=old_source_film,
        receiver_film=old_receiver_film,
        fixed_loss_voltage_v=0.0,
        series_asr_ohm_m2=1.0e-5,
    )

    assert new_result == old_result


def test_local_derivatives_match_legacy():
    old = legacy_v3_module()

    local = {
        "net_flux_mol_m2_s": 0.0123,
        "cell_power_density_w_m2": 12.5,
    }

    thermal_config = {
        "cell_power_to_process_air_fraction": 0.35,
    }

    for mode in (
        "isothermal",
        "adiabatic_upper_bound",
    ):
        new_result = new.local_derivatives(
            local,
            dry_air_mass_flow_kg_s=78.81256451,
            humidity_ratio=0.02,
            temperature_c=32.0,
            thermal_mode=mode,
            thermal_config=thermal_config,
        )

        old_result = old.local_derivatives(
            local,
            dry_air_mass_flow_kg_s=78.81256451,
            humidity_ratio=0.02,
            temperature_c=32.0,
            thermal_mode=mode,
            thermal_config=thermal_config,
        )

        assert np.allclose(
            new_result,
            old_result,
            rtol=0.0,
            atol=0.0,
        )


def test_local_gate_status_matches_legacy():
    old = legacy_v3_module()

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
            new.local_gate_status(
                local,
                current_cap_a_m2=100.0,
            )
            ==
            old.local_gate_status(
                local,
                current_cap_a_m2=100.0,
            )
        )


def test_powerlaw_local_state_matches_legacy():
    old = legacy_v3_module()
    v2, v2_config = load_v2()
    config, humidity_ratio = common_state()

    material = {
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

    kwargs = dict(
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

    new_result = new.solve_local_state(**kwargs)
    old_result = old.solve_local_state(**kwargs)

    assert_mapping_equal(
        new_result,
        old_result,
    )


def test_nafion_local_state_matches_legacy():
    old = legacy_v3_module()
    v2, v2_config = load_v2()
    config, humidity_ratio = common_state()

    material = {
        "model": "nafion",
        "dry_thickness_um": 100.0,
        "drag_scale_factor": 1.0,
    }

    kwargs = dict(
        v2=v2,
        v2_config=v2_config,
        material=material,
        source_temperature_c=32.0,
        source_humidity_ratio=humidity_ratio,
        receiver_activity=0.4,
        terminal_voltage_v=1.5,
        fixed_loss_voltage_v=0.0,
        series_asr_ohm_m2=1.0e-5,
        film_scale_factor=1.0,
        config=config,
    )

    new_result = new.solve_local_state(**kwargs)
    old_result = old.solve_local_state(**kwargs)

    assert_mapping_equal(
        new_result,
        old_result,
    )


def test_local_state_module_has_no_legacy_dependency():
    source = Path(new.__file__).read_text()

    assert "legacy_v3_module" not in source
    assert "make_wp1_pre_receiver_axial_v3" not in source
