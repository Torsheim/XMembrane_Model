import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]

SCRIPTS = (
    (
        "continuation",
        ROOT
        / "scripts"
        / "make_wp1_prearchitecture_continuation_v2.py",
    ),
    (
        "bottleneck",
        ROOT
        / "scripts"
        / (
            "make_wp1_prearchitecture_"
            "bottleneck_diagnostics_v1.py"
        ),
    ),
    (
        "direct_liquid",
        ROOT
        / "scripts"
        / "make_wp1_direct_liquid_contact_receiver_v1.py",
    ),
)


def load_script(label: str, path: Path):
    name = f"_current_gate_{label}"
    spec = importlib.util.spec_from_file_location(
        name,
        path,
    )

    if spec is None or spec.loader is None:
        raise RuntimeError(
            f"Could not load {path}"
        )

    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("label", "path"),
    SCRIPTS,
)
def test_active_workflow_default_current_cap(
    monkeypatch,
    label,
    path,
):
    module = load_script(label, path)
    monkeypatch.setattr(
        sys,
        "argv",
        [str(path)],
    )

    args = module.parse_args()

    assert args.current_cap_a_m2 == 21.0


def test_reference_config_retains_historical_cap():
    path = (
        ROOT
        / "config"
        / "closed_receiver_system_v12_config.json"
    )
    data = json.loads(
        path.read_text(encoding="utf-8")
    )

    assert (
        data["operating"][
            "current_density_cap_a_m2"
        ]
        == 2000.0
    )
