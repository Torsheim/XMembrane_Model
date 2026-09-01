from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "open_questions_analysis_v1.json"
SCRIPT = ROOT / "scripts" / "analyze_open_questions_v1.py"
OUTPUT = ROOT / "outputs" / "open_questions_analysis_v1_candidate_20260826"


def load_module():
    spec = importlib.util.spec_from_file_location("_open_questions_v1_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_config() -> dict[str, object]:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def require_registered_evidence(module, config: dict[str, object]) -> None:
    """Skip integration assertions when ignored evidence outputs are absent."""
    try:
        module.bind_sources(config)
    except (FileNotFoundError, ValueError) as exc:
        pytest.skip(f"Registered evidence is not available in this checkout: {exc}")


def test_config_uses_rule_based_ordinals_and_disables_claims_and_probabilities():
    module = load_module()
    config = load_config()
    module.validate_config(config)

    assert config["claim_boundary"] == {
        "full_system_claim_allowed": False,
        "deterministic_scenarios_are_probabilities": False,
        "ordinal_categories_are_numeric_scores": False,
        "note": config["claim_boundary"]["note"],
    }
    impact = config["ordinal_categories"]["decision_impact_high_to_low"]
    effort = config["ordinal_categories"]["closure_effort_low_to_high"]
    assert [entry["id"] for entry in impact] == [
        "I_SIGN_OR_GO_NO_GO_CAN_CHANGE",
        "II_CURRENT_EVIDENCE_GATE_BLOCKED",
        "III_MATERIAL_REALITY_UNVALIDATED",
        "IV_DESIGN_SPACE_COVERAGE_INCOMPLETE",
        "V_FULL_SYSTEM_CLAIM_BLOCKED",
        "VI_DECISION_COMMUNICATION_OR_QUALIFICATION",
    ]
    assert [entry["id"] for entry in effort] == [
        "I_EXISTING_DATA_REPLAY",
        "II_BENCH_OR_SITE_MEASUREMENT_PLUS_REPLAY",
        "III_MODULE_HARDWARE_PROGRAM",
        "IV_LIFETIME_AND_MANUFACTURING_PROGRAM",
    ]
    assert all(entry["definition"] for entry in impact + effort)
    assert config["analysis_settings"]["report_correction"][
        "v4_must_remain_untouched"
    ] is True


def test_required_sources_are_hash_pinned_and_canonical_low_voltage_is_atomic():
    module = load_module()
    config = load_config()
    require_registered_evidence(module, config)
    paths, records, optional = module.bind_sources(config)

    assert len(paths) == len(config["sources"])
    assert all(record["available"] for record in records)
    assert all(record["hash_match"] for record in records)
    assert all(record["expected_sha256"] for record in records)
    low = optional["direct_eo_low_voltage_study_v1"]
    assert low["available"] is True
    assert set(low["paths"]) == {
        "source_generator_provenance.json",
        "study_audit.json",
        "analysis/analysis_audit.json",
        "analysis/low_voltage_cap_register.csv",
    }
    assert all(len(record["sha256"]) == 64 for record in low["records"])


def test_optional_group_fails_closed_if_canonical_directory_is_partial(tmp_path):
    module = load_module()
    config = load_config()
    require_registered_evidence(module, config)
    partial = tmp_path / "direct_eo_low_voltage_study_v1"
    (partial / "analysis").mkdir(parents=True)
    (partial / "analysis" / "analysis_audit.json").write_text(
        '{"status":"PASS"}\n', encoding="utf-8"
    )
    config["optional_source_groups"][0]["directory"] = str(partial)

    with pytest.raises(FileNotFoundError, match="exists but is incomplete"):
        module.bind_sources(config)


def test_evidence_calculation_reproduces_current_break_even_and_report_correction():
    module = load_module()
    config = load_config()
    require_registered_evidence(module, config)
    paths, _, optional = module.bind_sources(config)
    register, boundaries, context, checks = module.build_analysis(
        config, paths, optional
    )
    values = boundaries.set_index("boundary_id")["numeric_value"]

    assert len(register) == 10
    assert register["full_system_claim_allowed"].eq(False).all()
    assert register["probability_interpretation"].eq(
        "NO_PROBABILITY_ASSIGNED"
    ).all()
    assert values["B01"] == pytest.approx(0.127934, abs=5e-7)
    assert values["B03"] == pytest.approx(10.47362352, abs=1e-6)
    assert values["B04"] == pytest.approx(-8.27350773, abs=1e-6)
    assert values["B05"] == pytest.approx(0.1804886858, abs=1e-10)
    assert values["B06"] == pytest.approx(-91.5790190, abs=1e-6)
    assert values["B21"] == 92
    assert values["B25"] == 76
    assert values["B26"] == 0
    assert values["B29"] == pytest.approx(23.67927361, abs=1e-6)
    assert values["B30"] == pytest.approx(25.67263841, abs=1e-6)
    assert values["B42"] == 409
    assert values["B43"] == 81
    assert values["B44"] == 35
    assert values["B45"] == 23
    assert values["B46"] == pytest.approx(-0.7169833040, abs=1e-10)
    assert values["B47"] == pytest.approx(0.7160636307, abs=1e-10)
    assert values["B48"] == pytest.approx(-0.7140986837, abs=1e-10)
    assert values["B49"] == pytest.approx(-0.5782412144, abs=1e-10)
    assert values["B50"] == pytest.approx(-0.5713811129, abs=1e-10)
    assert values["B51"] == pytest.approx(-0.5620815792, abs=1e-10)
    q05 = register.loc[register["question_id"].eq("Q05")].iloc[0]
    assert "direct_eo_low_voltage_study_v1" in q05["source_ids"].split(";")
    assert context["uncertainty_scenario_count"] == 27
    assert context["uncertainty_positive_count"] == 16
    assert all(check["passed"] for check in checks)


def test_canonical_low_voltage_continuous_loss_boundaries_are_evidence_computed():
    module = load_module()
    config = load_config()
    require_registered_evidence(module, config)
    paths, _, optional = module.bind_sources(config)
    _, boundaries, context, _ = module.build_analysis(config, paths, optional)
    values = boundaries.set_index("boundary_id")["numeric_value"]

    assert context["optional_low_voltage_available"] is True
    assert values["B33"] == 2508
    assert values["B34"] == 178
    assert values["B35"] == 0
    assert values["B36"] == pytest.approx(0.3083661412, abs=1e-10)
    assert values["B37"] == pytest.approx(0.211218, abs=5e-7)
    assert values["B38"] == pytest.approx(0.183720, abs=5e-7)
    assert values["B39"] == pytest.approx(-0.009027, abs=5e-7)
    assert values["B40"] == pytest.approx(0.0033464, abs=5e-8)
    assert values["B41"] == pytest.approx(14.9707, abs=5e-4)

    b36 = boundaries.loc[boundaries["boundary_id"].eq("B36")].iloc[0]
    assert "tw=60" in b36["condition"]
    assert "j=25" in b36["condition"]
    assert "D-scale=0.001" in b36["condition"]
    assert "held fixed" in b36["interpretation"]


def test_candidate_output_is_complete_audited_and_contains_no_numeric_scores():
    if not OUTPUT.is_dir():
        pytest.skip("Materialized open-question analysis is not part of a clean checkout")
    required = [
        "open_question_register.csv",
        "quantified_decision_boundaries.csv",
        "audit.json",
        "SUMMARY.md",
        "figures/01_impact_vs_closure_effort.png",
        "figures/01_impact_vs_closure_effort.pdf",
        "figures/02_receiver_break_even.png",
        "figures/02_receiver_break_even.pdf",
        "figures/03_decision_chain.png",
        "figures/03_decision_chain.pdf",
    ]
    assert all((OUTPUT / name).is_file() for name in required)

    audit = json.loads((OUTPUT / "audit.json").read_text(encoding="utf-8"))
    register = pd.read_csv(OUTPUT / "open_question_register.csv")
    boundaries = pd.read_csv(OUTPUT / "quantified_decision_boundaries.csv")
    summary = (OUTPUT / "SUMMARY.md").read_text(encoding="utf-8")
    assert audit["status"] == "PASS"
    assert audit["row_counts"] == {
        "open_question_register": 10,
        "quantified_decision_boundaries": 51,
    }
    assert audit["report_correction"]["correction_pass"] is True
    assert audit["report_correction"]["observed_scenario_count"] == 27
    assert audit["report_correction"]["observed_positive_count"] == 16
    assert audit["optional_source_groups"]["direct_eo_low_voltage_study_v1"][
        "available"
    ] is True
    assert not any("score" in column.lower() for column in register.columns)
    assert not any("score" in column.lower() for column in boundaries.columns)
    assert boundaries["probability_interpretation"].eq(
        "DETERMINISTIC_NOT_PROBABILITY"
    ).all()
    assert "27 deterministiske scenarier, hvorav 16 er positive" in summary
    assert "V4-rapportfilene er ikke endret" in summary
