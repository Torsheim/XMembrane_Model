from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
CLASSIFICATION = ROOT / "docs" / "workflow_reproducibility.json"
PROVENANCE = ROOT / "docs" / "PROVENANCE.md"

PERSONAL_ABSOLUTE_PATHS = (
    re.compile(r"/(?:home|Users)/[^/]+/"),
    re.compile(r"/mnt/[a-zA-Z]/Users/[^/]+/"),
    re.compile(r"[a-zA-Z]:[\\/]Users[\\/][^\\/]+[\\/]"),
)


def _walk_strings(value: object):
    if isinstance(value, dict):
        for nested in value.values():
            yield from _walk_strings(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_strings(nested)
    elif isinstance(value, str):
        yield value


def test_workflow_classification_covers_every_top_level_config() -> None:
    register = json.loads(CLASSIFICATION.read_text(encoding="utf-8"))
    classes = register["classes"]
    rows = register["configurations"]
    by_path = {row["path"]: row["class"] for row in rows}
    registered = [row["path"] for row in rows]
    observed = [
        path.relative_to(ROOT).as_posix()
        for path in sorted((ROOT / "config").glob("*.json"))
    ]

    assert len(registered) == len(set(registered))
    assert sorted(registered) == observed
    assert all(row["class"] in classes for row in rows)
    assert all((ROOT / row["path"]).is_file() for row in rows)
    assert by_path["config/direct_eo_erv_study_v1.json"] == "current_standalone"
    assert by_path["config/capacitive_electrode_study_v1.json"] == (
        "current_v10_result_overlay"
    )
    assert by_path["config/direct_erv_gradient_closure_v1.json"] == (
        "current_v10_result_overlay"
    )
    assert by_path["config/eo_vapor_test_cell_design.json"] == "post_v10_handoff"
    for name, policy in classes.items():
        if policy["personal_absolute_paths_allowed"]:
            assert policy["authority"] == "historical"
            assert policy.get("exception")


def test_current_configs_contain_no_personal_absolute_paths() -> None:
    register = json.loads(CLASSIFICATION.read_text(encoding="utf-8"))
    classes = register["classes"]
    offenders: list[tuple[str, str]] = []

    for row in register["configurations"]:
        policy = classes[row["class"]]
        if policy["personal_absolute_paths_allowed"]:
            continue
        payload = json.loads((ROOT / row["path"]).read_text(encoding="utf-8"))
        for value in _walk_strings(payload):
            if any(pattern.search(value) for pattern in PERSONAL_ABSOLUTE_PATHS):
                offenders.append((row["path"], value))

    assert offenders == []


def test_live_provenance_checksum_lines_match_local_files() -> None:
    checksum_line = re.compile(r"^([0-9a-f]{64})  (\S.+)$")
    checked = 0
    for line in PROVENANCE.read_text(encoding="utf-8").splitlines():
        match = checksum_line.fullmatch(line)
        if match is None:
            continue
        expected, relative = match.groups()
        path = ROOT / relative
        assert path.is_file(), f"Registered live provenance file is missing: {relative}"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
        checked += 1

    assert checked >= 20
