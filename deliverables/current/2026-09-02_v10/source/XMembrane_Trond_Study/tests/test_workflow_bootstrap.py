from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from heiq.wp1.membrane import legacy_v2_module
from heiq.wp1.studies import build_repository_context


ROOT = Path(__file__).resolve().parents[1]

WORKFLOW_PATHS = [
    ROOT
    / "scripts"
    / "make_wp1_prearchitecture_continuation_v2.py",
    ROOT
    / "scripts"
    / "make_wp1_prearchitecture_bottleneck_diagnostics_v1.py",
    ROOT
    / "scripts"
    / "make_wp1_direct_liquid_contact_receiver_v1.py",
]


def test_migrated_workflows_have_no_dynamic_script_bootstrap():
    forbidden = [
        "spec_from_file_location",
        "CONTINUATION_SCRIPT",
        "continuation.setup",
        'context["v12"]',
        'context["axial"]',
    ]

    for path in WORKFLOW_PATHS:
        source = path.read_text(encoding="utf-8")

        for token in forbidden:
            assert token not in source, (
                f"{path.name} still contains {token!r}"
            )


def test_repository_bootstrap_builds_native_context():
    args = SimpleNamespace(
        receiver_band="bridge_40_to_60",
        receiver_temperature_c=None,
        area_max_m2=9000.0,
        voltage_max_v=2.0,
    )

    context = build_repository_context(
        args,
        root=ROOT,
    )

    assert context["v2"] is legacy_v2_module()
    assert "v12" not in context
    assert "axial" not in context
    assert context["args"] is args
    assert set(context["targets"]) >= {"O50", "O30"}
    assert str(
        context["m11675"]["material_id"]
    ) == "M11675"
