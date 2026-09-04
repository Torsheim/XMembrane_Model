from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "src" / "heiq" / "wp1"

ALLOWED_PACKAGE_LOADERS = {
    Path("src/heiq/wp1/airside/legacy_v3.py"),
    Path("src/heiq/wp1/membrane/local_transport.py"),
    Path("src/heiq/wp1/receiver/legacy_v12.py"),
}

MIGRATED_WORKFLOWS = (
    Path(
        "scripts/"
        "make_wp1_prearchitecture_continuation_v2.py"
    ),
    Path(
        "scripts/"
        "make_wp1_prearchitecture_"
        "bottleneck_diagnostics_v1.py"
    ),
    Path(
        "scripts/"
        "make_wp1_direct_liquid_contact_receiver_v1.py"
    ),
)


def test_package_dynamic_loaders_are_allowlisted():
    loader_tokens = (
        "spec_from_file_location(",
        "exec_module(",
    )

    actual = {
        path.relative_to(ROOT)
        for path in PACKAGE_ROOT.rglob("*.py")
        if any(
            token in path.read_text(encoding="utf-8")
            for token in loader_tokens
        )
    }

    assert actual == ALLOWED_PACKAGE_LOADERS


def test_migrated_workflows_do_not_cross_legacy_boundary():
    forbidden = (
        "spec_from_file_location(",
        "exec_module(",
        "CONTINUATION_SCRIPT",
        "continuation.setup",
        'context["v12"]',
        'context["axial"]',
        "legacy_v2_module",
        "legacy_v3_module",
        "legacy_v12_module",
        "heiq_pre_receiver_model.py",
        "make_wp1_pre_receiver_axial_v3.py",
        "make_wp1_closed_receiver_system_v12.py",
        "V11_DIR",
        "V12_SCRIPT",
        "AXIAL_SCRIPT",
        "V12_CONFIG",
        "V2_ROOT",
    )

    violations = {}

    for relative_path in MIGRATED_WORKFLOWS:
        source = (
            ROOT
            / relative_path
        ).read_text(encoding="utf-8")

        found = [
            token
            for token in forbidden
            if token in source
        ]

        if found:
            violations[str(relative_path)] = found

    assert violations == {}
