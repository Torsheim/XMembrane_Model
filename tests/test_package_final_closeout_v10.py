from __future__ import annotations

import hashlib
import importlib.util
import stat
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def packager_module():
    path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "package_final_closeout_v10.py"
    )
    spec = importlib.util.spec_from_file_location(
        "test_package_final_closeout_v10_script", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_normalize_release_modes_is_content_preserving(
    tmp_path: Path,
    packager_module,
):
    release = tmp_path / "release"
    source = release / "source" / packager_module.PROJECT_ARCHIVE_ROOT
    ordinary = release / "MANIFEST.json"
    tracked_text = source / "README.md"
    tracked_script = source / "scripts" / "run_model.py"
    result_script_copy = (
        release
        / "results"
        / packager_module.PROJECT_ARCHIVE_ROOT
        / "scripts"
        / "run_model.py"
    )
    link = source / "scripts" / "model-config.json"

    for path, payload in (
        (ordinary, b"manifest\n"),
        (tracked_text, b"readme\n"),
        (tracked_script, b"#!/usr/bin/env python3\n"),
        (result_script_copy, b"#!/usr/bin/env python3\n"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        path.chmod(0o777)
    link.symlink_to("../README.md")
    release.chmod(0o777)
    for directory in (source, tracked_script.parent, result_script_copy.parent):
        directory.chmod(0o777)

    digests_before = {
        path: _digest(path)
        for path in (ordinary, tracked_text, tracked_script, result_script_copy)
    }
    link_target_before = link.readlink()
    source_tree = [
        {"path": "README.md", "mode": "100644"},
        {"path": "scripts/run_model.py", "mode": "100755"},
        {"path": "scripts/model-config.json", "mode": "120000"},
    ]

    result = packager_module.normalize_release_modes(release, source_tree)

    assert _mode(release) == 0o755
    assert _mode(ordinary) == 0o644
    assert _mode(tracked_text) == 0o644
    assert _mode(tracked_script) == 0o755
    assert _mode(result_script_copy) == 0o644
    assert all(_mode(path) == 0o755 for path in (source, tracked_script.parent))
    assert link.is_symlink()
    assert link.readlink() == link_target_before
    assert {
        path: _digest(path)
        for path in digests_before
    } == digests_before
    assert result == {
        "directory_count": 7,
        "regular_file_count": 4,
        "executable_file_count": 1,
    }
