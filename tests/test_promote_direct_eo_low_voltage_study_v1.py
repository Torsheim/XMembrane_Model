from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "promote_direct_eo_low_voltage_study_v1.py"
CANDIDATE = ROOT / "outputs" / "direct_eo_low_voltage_study_v1_candidate_20260826"
CANONICAL = ROOT / "outputs" / "direct_eo_low_voltage_study_v1"


def load_module():
    spec = importlib.util.spec_from_file_location("_low_voltage_promoter", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_tree_manifest_detects_byte_identity_and_change(tmp_path):
    module = load_module()
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()
    (left / "a.txt").write_text("same\n", encoding="utf-8")
    (right / "a.txt").write_text("same\n", encoding="utf-8")
    assert module.tree_manifest(left) == module.tree_manifest(right)
    (right / "a.txt").write_text("changed\n", encoding="utf-8")
    assert module.tree_manifest(left) != module.tree_manifest(right)


@pytest.mark.skipif(
    not (CANONICAL / "promotion_provenance.json").is_file(),
    reason="Canonical promotion has not been generated",
)
def test_canonical_promotion_is_truthful_and_hash_bound():
    module = load_module()
    promotion = json.loads(
        (CANONICAL / "promotion_provenance.json").read_text(encoding="utf-8")
    )
    source = json.loads(
        (CANONICAL / "source_generator_provenance.json").read_text(encoding="utf-8")
    )
    command = json.loads(
        (CANONICAL / "generator_command.json").read_text(encoding="utf-8")
    )
    study = json.loads((CANONICAL / "study_audit.json").read_text(encoding="utf-8"))
    analysis = json.loads(
        (CANONICAL / "analysis" / "analysis_audit.json").read_text(encoding="utf-8")
    )

    assert promotion["status"] == "PASS"
    assert promotion["execution_mode"] == "HASH_IDENTICAL_PHYSICS_PROMOTION"
    assert promotion["physics_generator_executed_in_canonical_root"] is False
    assert promotion["physics_tree_identity"]["passed"] is True
    assert promotion["physics_tree_identity"]["file_count"] > 100
    assert source["status"] == "PASS"
    assert source["physics_generator_executed_in_canonical_root"] is False
    assert source["command_execution_root"] == str(CANDIDATE.resolve())
    assert command["physics_generator_executed_in_this_root"] is False
    assert study["status"] == "PASS"
    assert study["physics_generator_executed_in_canonical_root"] is False
    assert analysis["status"] == "PASS"
    assert analysis["inputs"]["source_generator_provenance"]["sha256"] == (
        module.sha256_file(CANONICAL / "source_generator_provenance.json")
    )
    assert module.tree_manifest(CANDIDATE / "physics") == module.tree_manifest(
        CANONICAL / "physics"
    )
