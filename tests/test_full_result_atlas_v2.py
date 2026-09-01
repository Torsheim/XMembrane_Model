from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
V2_ROOT = ROOT.parent / "HeiQ_V2"
SCRIPT = ROOT / "scripts" / "make_full_result_atlas_v2.py"


def module():
    spec = importlib.util.spec_from_file_location("_full_result_atlas_v2_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.skipif(
    not (V2_ROOT / "outputs/final_prearchitecture_closure_v1").is_dir(),
    reason="HeiQ_V2 audited sibling outputs are not present",
)
def test_atlas_retains_the_full_history_and_fails_system_claims_closed():
    mod = module()
    atlas = mod.build_result_atlas()

    assert len(atlas) >= 300
    assert atlas["result_id"].is_unique
    assert atlas["source_exists"].all()
    assert not atlas["full_system_claim_allowed"].any()
    assert atlas["study"].nunique() >= 50

    values = atlas.set_index("result_id")["numeric_value"]
    assert values["E106"] == 9.0  # all nine explicitly closed v39 cases negative
    assert values["E90"] == 0.0  # v44 robust receiver gate
    assert values["E93a"] == 0.0  # v55 receiver water handling deliberately unpriced
    assert values["F22"] == 7.0  # all selected final candidates negative
    assert math.isclose(values["F30"], -49.032028, abs_tol=1.0e-5)
    assert values["G41"] == 195.0
    assert values["G44"] == 0.0


@pytest.mark.skipif(
    not (V2_ROOT / "outputs/final_prearchitecture_closure_v1").is_dir(),
    reason="HeiQ_V2 audited sibling outputs are not present",
)
def test_inventory_and_latex_fragments_cover_all_sources(tmp_path):
    mod = module()
    atlas = mod.build_result_atlas()
    inventory = mod.build_output_inventory()
    downloads = mod.build_download_manifest()
    studies = mod.build_major_study_index(atlas)

    assert len(inventory) >= 320
    assert set(inventory["repository"]) == {
        "HeiQ V2",
        "Thermodynamical analysis",
        "Trond study",
        "XMembrane model",
    }
    assert len(studies) >= 50
    assert downloads["sha256"].str.len().eq(64).all()

    mod.write_latex_fragments(tmp_path, atlas, studies, inventory, downloads)
    atlas_tex = (tmp_path / "result_atlas_longtable.tex").read_text(encoding="utf-8")
    assert "V39 closed chilled receiver" in atlas_tex
    assert "V55 ideal wet receiver" in atlas_tex
    assert "Final pre-architecture closure" in atlas_tex
    assert "Current-controlled receiver v2" in atlas_tex
    assert atlas_tex.count("\\\\") >= len(atlas)
