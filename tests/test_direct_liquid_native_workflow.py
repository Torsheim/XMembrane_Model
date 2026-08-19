import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]

SCRIPT = (
    ROOT
    / "scripts"
    / "make_wp1_direct_liquid_contact_receiver_v1.py"
)


def load_script():
    name = "_native_direct_liquid_test"

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


def test_direct_liquid_has_no_legacy_runtime_context():
    source = SCRIPT.read_text()

    for forbidden in (
        'context["v12"]',
        'context["axial"]',
        "patched_film_coefficients(",
        "spec_from_file_location",
        "CONTINUATION_SCRIPT",
    ):
        assert forbidden not in source


def test_native_direct_liquid_context_builds():
    module = load_script()

    args = SimpleNamespace(
        receiver_temperature_c=32.0,
        area_max_m2=9000.0,
        voltage_search_max_v=24.0,
        current_cap_a_m2=21.0,
    )

    continuation, context = (
        module.setup_context(args)
    )

    assert continuation is None
    assert "v12" not in context
    assert "axial" not in context
    assert "O30" in context["targets"]
    assert "O50" in context["targets"]
    assert context["v2"] is not None
    assert (
        context["cfg12"]["operating"][
            "current_density_cap_a_m2"
        ]
        == 21.0
    )
