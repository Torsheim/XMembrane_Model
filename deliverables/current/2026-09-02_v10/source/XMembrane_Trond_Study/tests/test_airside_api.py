from pathlib import Path

from heiq.wp1.airside import (
    activity_from_t_w,
    dry_air_mass_flow,
    dynamic_viscosity_air_pa_s,
    humidity_ratio_from_t_rh,
    legacy_v3_module,
    legacy_v3_path,
    process_channel_fan,
    vapour_pressure_from_humidity_ratio,
)


ROOT = Path(__file__).resolve().parents[1]


def test_v3_airside_api_uses_canonical_source():
    expected = (ROOT / "scripts" / "make_wp1_pre_receiver_axial_v3.py").resolve()
    assert legacy_v3_path().resolve() == expected
    assert expected.is_file()


def test_v3_airside_public_symbols_exist_in_legacy_module():
    module = legacy_v3_module()
    names = [
        "humidity_ratio_from_t_rh",
        "vapour_pressure_from_humidity_ratio",
        "activity_from_t_w",
        "dry_air_mass_flow",
        "dynamic_viscosity_air_pa_s",
        "process_channel_fan",
    ]
    for name in names:
        assert hasattr(module, name), name
        assert callable(getattr(module, name)), name


def test_v3_airside_wrappers_are_callable():
    assert callable(humidity_ratio_from_t_rh)
    assert callable(vapour_pressure_from_humidity_ratio)
    assert callable(activity_from_t_w)
    assert callable(dry_air_mass_flow)
    assert callable(dynamic_viscosity_air_pa_s)
    assert callable(process_channel_fan)
