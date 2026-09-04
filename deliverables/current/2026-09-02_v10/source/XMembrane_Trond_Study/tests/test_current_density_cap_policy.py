import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

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
    name = f"_current_cap_policy_{label}"
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
def test_active_workflow_has_no_default_current_acceptance_cap(
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

    assert args.current_cap_a_m2 is None


@pytest.mark.parametrize(
    ("label", "path"),
    SCRIPTS,
)
def test_active_workflow_retains_explicit_current_sensitivity(
    monkeypatch,
    label,
    path,
):
    module = load_script(f"{label}_explicit", path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(path),
            "--current-cap-a-m2",
            "21",
        ],
    )

    args = module.parse_args()

    assert args.current_cap_a_m2 == 21.0


@pytest.mark.parametrize(
    ("label", "path"),
    SCRIPTS,
)
def test_default_context_preserves_only_numerical_current_ceiling(
    monkeypatch,
    label,
    path,
):
    module = load_script(f"{label}_context", path)
    monkeypatch.setattr(sys, "argv", [str(path)])
    args = module.parse_args()

    if label == "continuation":
        context = module.setup(args)
    elif label == "bottleneck":
        context = module.setup_context(args)
    else:
        _, context = module.setup_context(args)

    assert args.current_cap_a_m2 is None
    assert (
        context["cfg12"]["operating"][
            "current_density_cap_a_m2"
        ]
        == 2000.0
    )
    assert context["args"].current_cap_a_m2 is None


def test_reference_config_retains_numerical_solver_ceiling():
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


def test_direct_liquid_current_comparison_requires_explicit_sensitivity():
    label, path = SCRIPTS[2]
    module = load_script(f"{label}_gate_semantics", path)
    local = {
        "solution_ok": True,
        "net_flux_mol_m2_s": 0.01,
        "current_density_a_m2": 21.1,
        "source_surface_activity": 0.5,
        "receiver_surface_activity": 0.4,
    }

    assert module.local_gate(local, None) == "local_gates_pass"
    assert (
        module.local_gate(local, 21.0)
        == "explicit_current_density_sensitivity_limit"
    )

    row = {
        "target_reached": True,
        "water_balance_pass": True,
        "required_active_area_m2": 1000.0,
        "maximum_local_current_density_a_m2": 21.1,
        "minimum_local_flux_mol_m2_s": 0.01,
        "maximum_receiver_surface_activity": 0.4,
        "predryer_core_power_kw": 10.0,
    }
    assert module.case_pass(
        row,
        SimpleNamespace(
            area_max_m2=9000.0,
            current_cap_a_m2=None,
        ),
    )
    assert not module.case_pass(
        row,
        SimpleNamespace(
            area_max_m2=9000.0,
            current_cap_a_m2=21.0,
        ),
    )
