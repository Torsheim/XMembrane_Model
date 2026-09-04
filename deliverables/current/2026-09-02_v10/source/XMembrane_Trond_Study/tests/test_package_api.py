from pathlib import Path

from heiq.wp1.membrane import (
    legacy_module_path,
    load_config,
    solve_nafion_voltage_state,
    solve_powerlaw_voltage_control,
)


ROOT = Path(__file__).resolve().parents[1]


def test_v2_package_api_is_available():
    assert callable(load_config)
    assert callable(solve_powerlaw_voltage_control)
    assert callable(solve_nafion_voltage_state)


def test_v2_package_api_uses_canonical_repository_source():
    expected = (
        ROOT
        / "heiq_pre_receiver_material_analyses"
        / "heiq_pre_receiver_model.py"
    ).resolve()

    assert legacy_module_path().resolve() == expected
    assert expected.is_file()


def test_v2_package_config_loading_preserves_reference_config():
    config = (
        ROOT
        / "heiq_pre_receiver_material_analyses"
        / "config"
        / "default.json"
    )

    loaded = load_config(config)

    assert isinstance(loaded, dict)
    assert loaded
