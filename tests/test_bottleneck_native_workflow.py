import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    ROOT
    / "scripts"
    / "make_wp1_prearchitecture_bottleneck_diagnostics_v1.py"
)


def load_script():
    name = "_native_bottleneck_test"

    spec = importlib.util.spec_from_file_location(
        name,
        SCRIPT,
    )

    module = importlib.util.module_from_spec(
        spec
    )

    sys.modules[name] = module
    spec.loader.exec_module(module)

    return module


def test_bottleneck_calculation_path_has_no_legacy_context_access():
    source = SCRIPT.read_text()

    assert 'context["v12"]' not in source
    assert 'context["axial"]' not in source

    assert (
        "patched_film_coefficients("
        not in source
    )

    assert (
        "v12.integrate_coupled_receiver_case"
        not in source
    )

    assert (
        "axial.solve_local_state"
        not in source
    )


def test_native_bottleneck_case_runs_with_independent_films():
    module = load_script()

    args = SimpleNamespace(
        receiver_band="bridge_40_to_60",
        receiver_temperature_c=None,
        area_max_m2=500.0,
        voltage_max_v=2.0,
    )

    context = module.setup_context(args)

    assert "v12" not in context
    assert "axial" not in context

    material = (
        module.material_from_baseline(
            context,
            {},
        )
    )

    band = module.default_band(
        context,
        args,
    )

    row, profile, receiver = (
        module.solve_full_case(
            context,
            target="O30",
            material=material,
            terminal_voltage_v=0.98,
            receiver_multiplier=1.05,
            receiver_band=band,
            receiver_band_id=(
                "native_test_040_060"
            ),
            process_film_factor=5.0,
            receiver_film_factor=1.0,
            area_limit_m2=250.0,
            record_profile=False,
        )
    )

    assert (
        row[
            "diagnostic_process_film_factor"
        ]
        == 5.0
    )

    assert (
        row[
            "diagnostic_receiver_film_factor"
        ]
        == 1.0
    )

    assert (
        row[
            "diagnostic_area_limit_m2"
        ]
        == 250.0
    )

    assert (
        receiver.flow_arrangement
        == "counter_current"
    )

    assert "status" in row
