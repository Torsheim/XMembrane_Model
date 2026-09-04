from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
V2_ROOT = ROOT.parent / "HeiQ_V2"
SCRIPT = ROOT / "scripts" / "make_integrated_evidence_register_v1.py"


def module():
    spec = importlib.util.spec_from_file_location("_integrated_evidence_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.skipif(
    not (V2_ROOT / "outputs/terminal1_post_erv_10pct_incremental_v2_study").is_dir(),
    reason="HeiQ_V2 audited sibling output is not present",
)
def test_register_keeps_evidence_levels_and_system_claims_fail_closed():
    mod = module()
    evidence, metrics, diffusivity, matrix, manifest = mod.build_register(
        trond_root=ROOT,
        v2_root=V2_ROOT,
    )

    assert len(evidence) == 9
    assert evidence["audit_pass"].all()
    assert not evidence["full_system_claim_allowed"].any()
    assert set(evidence.loc[evidence["mode"].eq("smoke"), "study_id"]) == {
        "post_erv_physics_closure",
        "material_condensation",
    }
    current_conclusion = evidence.loc[
        ~evidence["study_id"].eq("receiver_regeneration_v39")
    ]
    assert not current_conclusion["current_density_limit_applied"].any()

    values = metrics.set_index(["study_id", "metric_id"])["numeric_value"]
    assert math.isclose(
        values["post_erv_10pct", "best_real_film_saving"],
        53.06655218750296,
        rel_tol=1.0e-12,
    )
    assert values[
        "material_condensation", "nafion_target_and_correlation_valid_rows"
    ] == 0.0
    assert values[
        "current_controlled_receiver", "highest_sampled_current_reaching_o30"
    ] == 21.0
    assert values[
        "current_controlled_receiver", "highest_sampled_current_reaching_o50"
    ] == 45.0

    assert len(diffusivity) == 4
    assert len(matrix) == 4
    material_requirements = mod.material_data_requirements()
    assert len(material_requirements) == 9
    assert set(material_requirements["data_status"]) == {"missing"}
    assert "D(a,T)" in set(material_requirements["symbol_or_measurement"])
    assert "J_net(a_source,a_receiver,T,j)" in set(
        material_requirements["symbol_or_measurement"]
    )
    assert manifest["rules"] == {
        "chat_text_is_evidence": False,
        "smoke_promoted_to_study": False,
        "missing_power_treated_as_zero": False,
        "current_density_acceptance_limit_applied": False,
    }
    assert len(manifest["source_files_sha256"]) >= 18
