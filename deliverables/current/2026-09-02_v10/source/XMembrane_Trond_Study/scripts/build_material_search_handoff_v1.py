#!/usr/bin/env python3
"""Build the consolidated HeiQ material-search handoff.

The handoff deliberately separates:

* named membranes and material families found in the local evidence;
* counter-ion and supported-membrane development routes;
* inverse-design and other synthetic model coordinates; and
* current versus superseded screening constraints.

No external data are fetched.  Every quantitative statement is traceable to a
canonical file under ``/home/torsheim/HeiQ`` and every registered source is
hashed when the handoff is generated.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


SCRIPT_VERSION = "material-search-handoff-v1-2026-08-31"
REPO_ROOT = Path(__file__).resolve().parents[1]
HEIQ_ROOT = REPO_ROOT.parent
DEFAULT_OUTPUT = REPO_ROOT / "reports" / "material_search_handoff_2026-08-31" / "data"

EXCLUDED_PARTS = {
    ".git",
    ".heiq_patch_backups",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
}

WORKSPACE_ROOTS = (
    "HeiQ-Thermodynamical-Analysis",
    "HeiQ_V2",
    "XMembrane_Model",
    "XMembrane_Trond_Study",
    "deliverables",
)


SOURCE_RECORDS: tuple[dict[str, str], ...] = (
    {
        "source_id": "ROOT-01",
        "path": "collect_for_chatgpt.sh",
        "role": "Top-level historical review-bundle collector",
        "evidence_class": "workspace_utility",
        "use": "coverage_context_only",
    },
    {
        "source_id": "CUR-00",
        "path": "XMembrane_Trond_Study/reports/team_result_atlas_v8/HeiQ_XMembrane_Current_Result_and_Decision_Report_2026-08-31_v8.pdf",
        "role": "Governing current English result and decision report",
        "evidence_class": "current_governing_decision_basis",
        "use": "current_governing",
    },
    {
        "source_id": "CUR-00M",
        "path": "XMembrane_Trond_Study/reports/team_result_atlas_v8/source_manifest.json",
        "role": "Source and figure manifest for the governing V8 report",
        "evidence_class": "current_report_manifest",
        "use": "current_governing_provenance",
    },
    {
        "source_id": "CUR-01",
        "path": "XMembrane_Trond_Study/reports/model_closure_2026-08-31/HeiQ_XMembrane_Model_Closure_and_Material_Handoff_2026-08-31.tex",
        "role": "Supporting model closure and empirical handoff",
        "evidence_class": "current_supporting_decision_basis",
        "use": "supporting_where_V8_does_not_differ",
    },
    {
        "source_id": "CUR-02",
        "path": "XMembrane_Trond_Study/outputs/material_parameter_windows_with_nafion_v1/SUMMARY.md",
        "role": "Current direct-EO and post-ERV material-window synthesis",
        "evidence_class": "current_model_output",
        "use": "current",
    },
    {
        "source_id": "CUR-03",
        "path": "XMembrane_Trond_Study/outputs/material_parameter_windows_with_nafion_v1/parameter_window_register.csv",
        "role": "Machine-readable current parameter windows",
        "evidence_class": "current_model_output",
        "use": "current",
    },
    {
        "source_id": "CUR-04",
        "path": "XMembrane_Trond_Study/outputs/material_parameter_windows_with_nafion_v1/nafion_reference_case_register.csv",
        "role": "Named Nafion grade reference cases",
        "evidence_class": "literature_and_product_reference",
        "use": "reference_only",
    },
    {
        "source_id": "CUR-05",
        "path": "XMembrane_Trond_Study/outputs/integrated_evidence_v1/material_data_requirements.csv",
        "role": "MAT-01 to MAT-09 same-sample qualification schema",
        "evidence_class": "current_test_requirement",
        "use": "current",
    },
    {
        "source_id": "CUR-06",
        "path": "XMembrane_Trond_Study/config/direct_eo_erv_study_v1.json",
        "role": "Current direct-active-ERV material coordinates",
        "evidence_class": "current_model_configuration",
        "use": "current",
    },
    {
        "source_id": "CUR-07",
        "path": "XMembrane_Trond_Study/outputs/direct_active_eo_erv_study_v1/study/SUMMARY.md",
        "role": "Current direct-active-ERV study summary",
        "evidence_class": "current_model_output",
        "use": "current",
    },
    {
        "source_id": "CUR-08",
        "path": "XMembrane_Trond_Study/reports/workshop_pack_2026-08-30/MATERIAL_SEARCH_BRIEF.md",
        "role": "Current supplier and coupon data request",
        "evidence_class": "current_test_requirement",
        "use": "current",
    },
    {
        "source_id": "CUR-09",
        "path": "XMembrane_Trond_Study/outputs/final_delivery_check_v1/status.json",
        "role": "Current release and candidate-readiness status",
        "evidence_class": "current_audit",
        "use": "current",
    },
    {
        "source_id": "CUR-10",
        "path": "XMembrane_Trond_Study/heiq_pre_receiver_material_analyses/heiq_pre_receiver_model.py",
        "role": "Older local H-Nafion property implementation",
        "evidence_class": "historical_model_implementation",
        "use": "retain_separately",
    },
    {
        "source_id": "CUR-11",
        "path": "XMembrane_Trond_Study/heiq_pre_receiver_material_analyses/config/default.json",
        "role": "Older local H-Nafion assumptions and sweep bounds",
        "evidence_class": "historical_model_configuration",
        "use": "retain_separately",
    },
    {
        "source_id": "CUR-12",
        "path": "XMembrane_Trond_Study/reports/eo_vapor_boundary_analysis_v2_en/HeiQ_EO_Vapour_Cell_Boundary_Conditions_and_Sizing_2026-08-31_v2.pdf",
        "role": "Canonical English EO vapour coupon boundary and sizing report",
        "evidence_class": "current_experiment_design_report",
        "use": "current_coupon_design",
    },
    {
        "source_id": "CUR-12M",
        "path": "XMembrane_Trond_Study/reports/eo_vapor_boundary_analysis_v2_en/source_manifest.json",
        "role": "Source manifest for the English EO vapour coupon report",
        "evidence_class": "current_report_manifest",
        "use": "current_coupon_provenance",
    },
    {
        "source_id": "CUR-13",
        "path": "XMembrane_Trond_Study/deliverables/current/2026-08-31_v8/MANIFEST.json",
        "role": "Controlled V8 release manifest",
        "evidence_class": "current_controlled_release",
        "use": "current_release_hierarchy",
    },
    {
        "source_id": "CUR-13R",
        "path": "XMembrane_Trond_Study/deliverables/current/2026-08-31_v8/README.md",
        "role": "Controlled V8 authority hierarchy and claim boundary",
        "evidence_class": "current_controlled_release",
        "use": "current_release_hierarchy",
    },
    {
        "source_id": "CUR-14",
        "path": "XMembrane_Trond_Study/deliverables/current/2026-08-31_v8/SHA256SUMS",
        "role": "Controlled V8 release checksums",
        "evidence_class": "current_controlled_release",
        "use": "current_release_integrity",
    },
    {
        "source_id": "CUR-15",
        "path": "XMembrane_Trond_Study/deliverables/current/2026-08-31_v8_1/README.md",
        "role": "V8.1 English-delivery authority hierarchy",
        "evidence_class": "current_controlled_release",
        "use": "current_release_status_context",
    },
    {
        "source_id": "CUR-16",
        "path": "XMembrane_Trond_Study/deliverables/current/2026-08-31_v8_1/MANIFEST.json",
        "role": "Latest controlled English-delivery manifest; no scientific delta from V8",
        "evidence_class": "current_controlled_release",
        "use": "latest_delivery_layer",
    },
    {
        "source_id": "CUR-17",
        "path": "XMembrane_Trond_Study/deliverables/current/2026-08-31_v8_1/SHA256SUMS",
        "role": "Latest controlled English-delivery checksums",
        "evidence_class": "current_controlled_release",
        "use": "latest_delivery_integrity",
    },
    {
        "source_id": "CUR-18",
        "path": "XMembrane_Trond_Study/outputs/direct_erv_gradient_closure_v1/SUMMARY.md",
        "role": "Direct-ERV gradient and symmetric-current closure",
        "evidence_class": "current_model_output",
        "use": "secondary_architecture_status_and_claim_boundary",
    },
    {
        "source_id": "CUR-19",
        "path": "XMembrane_Trond_Study/outputs/direct_erv_gradient_closure_v1/case_summary.csv",
        "role": "Direct-ERV O30 and full-duty gradient/film diagnostic ledger",
        "evidence_class": "current_model_output",
        "use": "keep_distinct_from_post_erv_O30",
    },
    {
        "source_id": "CUR-20",
        "path": "XMembrane_Trond_Study/outputs/direct_erv_gradient_closure_v1/signed_triplet.csv",
        "role": "Segment-resolved +J/0/-J direct-ERV replay",
        "evidence_class": "current_model_output",
        "use": "symmetric_AC_null_and_unmodelled_rectification_boundary",
    },
    {
        "source_id": "CUR-21",
        "path": "XMembrane_Trond_Study/outputs/direct_erv_gradient_closure_v1/source_manifest.json",
        "role": "Direct-ERV gradient-closure source manifest",
        "evidence_class": "current_output_manifest",
        "use": "current_provenance",
    },
    {
        "source_id": "CUR-22",
        "path": "XMembrane_Trond_Study/outputs/eo_vapor_cell_sizing_v1/SUMMARY.md",
        "role": "Canonical controlled-flow coupon-cell sizing summary",
        "evidence_class": "current_experiment_design_output",
        "use": "coupon_size_and_operating_modes",
    },
    {
        "source_id": "CUR-23",
        "path": "XMembrane_Trond_Study/outputs/eo_vapor_cell_sizing_v1/source_manifest.json",
        "role": "Coupon-cell sizing source manifest",
        "evidence_class": "current_output_manifest",
        "use": "current_coupon_provenance",
    },
    {
        "source_id": "CUR-24",
        "path": "XMembrane_Trond_Study/outputs/eo_vapor_cell_sizing_v1/audit.json",
        "role": "Coupon-cell sizing validation audit",
        "evidence_class": "current_output_audit",
        "use": "current_coupon_validation",
    },
    {
        "source_id": "CUR-25",
        "path": "XMembrane_Trond_Study/outputs/eo_vapor_boundary_analysis_v1/SUMMARY.md",
        "role": "Canonical EO vapour-cell boundary and nuisance-analysis summary",
        "evidence_class": "current_experiment_design_output",
        "use": "coupon_protocol_and_claim_boundary",
    },
    {
        "source_id": "CUR-26",
        "path": "XMembrane_Trond_Study/outputs/eo_vapor_boundary_analysis_v1/source_manifest.json",
        "role": "EO vapour-cell boundary-analysis source manifest",
        "evidence_class": "current_output_manifest",
        "use": "current_coupon_provenance",
    },
    {
        "source_id": "CUR-27",
        "path": "XMembrane_Trond_Study/outputs/eo_vapor_boundary_analysis_v1/audit.json",
        "role": "EO vapour-cell boundary-analysis validation audit",
        "evidence_class": "current_output_audit",
        "use": "current_coupon_validation",
    },
    {
        "source_id": "CUR-28",
        "path": "XMembrane_Trond_Study/deliverables/current/2026-08-31_v8_1/results/common_voltage/README.md",
        "role": "Controlled post-ERV common-voltage diffusivity result",
        "evidence_class": "current_controlled_model_output",
        "use": "first_system_target_and_D_sensitivity",
    },
    {
        "source_id": "CUR-29",
        "path": "XMembrane_Trond_Study/deliverables/current/2026-08-31_v8_1/results/direct_active_erv/DECISION_SUMMARY.json",
        "role": "Controlled direct-active-ERV decision summary",
        "evidence_class": "current_controlled_model_output",
        "use": "secondary_architecture_gate_status",
    },
    {
        "source_id": "CUR-30",
        "path": "XMembrane_Trond_Study/deliverables/current/2026-08-31_v8_1/results/direct_active_erv/gate_counts.csv",
        "role": "Controlled direct-active-ERV gate-count ledger",
        "evidence_class": "current_controlled_model_output",
        "use": "secondary_architecture_gate_status",
    },
    {
        "source_id": "CUR-31",
        "path": "XMembrane_Trond_Study/outputs/direct_passive_nafion_erv_control_v1/SUMMARY.md",
        "role": "Matched active/passive Nafion NR211 mechanism control",
        "evidence_class": "current_model_output",
        "use": "negative_control_and_diffusion_attribution",
    },
    {
        "source_id": "CUR-32",
        "path": "XMembrane_Trond_Study/scripts/make_integrated_direct_eo_erv_weather_v1.py",
        "role": "Post-release direct-active-ERV weather-axis extension",
        "evidence_class": "post_release_uncontrolled_model_extension",
        "use": "coverage_context_and_conditional_weather_replay",
    },
    {
        "source_id": "CUR-33",
        "path": "XMembrane_Trond_Study/outputs/integrated_active_erv_weather_v1/active_erv_weather_energy.csv",
        "role": "Post-release direct-active-ERV fixed-area weather replay",
        "evidence_class": "post_release_uncontrolled_model_output",
        "use": "conditional_weather_replay_not_material_evidence",
    },
    {
        "source_id": "CUR-34",
        "path": "XMembrane_Trond_Study/outputs/integrated_active_erv_weather_v1/run_manifest.json",
        "role": "Claim boundary for the post-release direct-active-ERV weather replay",
        "evidence_class": "post_release_uncontrolled_output_manifest",
        "use": "conditional_weather_replay_provenance",
    },
    {
        "source_id": "CUR-35",
        "path": "XMembrane_Trond_Study/reports/weekly_findings_2026-08-24_to_2026-08-30/HeiQ_XMembrane_Weekly_Findings_2026-08-24_to_2026-08-30_Rev1.pdf",
        "role": "Latest dated weekly presentation including the direct-ERV weather-axis figure",
        "evidence_class": "post_release_non_governing_report",
        "use": "presentation_context_only",
    },
    {
        "source_id": "CUR-36",
        "path": "XMembrane_Trond_Study/reports/weekly_findings_2026-08-24_to_2026-08-30/HeiQ_XMembrane_Weekly_Findings_2026-08-24_to_2026-08-30_Rev1.tex",
        "role": "Source for the latest dated weekly presentation",
        "evidence_class": "post_release_non_governing_report_source",
        "use": "presentation_provenance",
    },
    {
        "source_id": "CUR-37",
        "path": "XMembrane_Trond_Study/reports/weekly_findings_2026-08-24_to_2026-08-30/README.md",
        "role": "Weekly-report authority and supersession note",
        "evidence_class": "post_release_non_governing_report_source",
        "use": "authority_hierarchy_context",
    },
    {
        "source_id": "HIST-01",
        "path": "HeiQ_V2/outputs/wp1_literature_ion_uncertainty_v12/literature_uncertainty_summary.md",
        "role": "Literature-bounded H/Li/Na/K route comparison",
        "evidence_class": "historical_conditional_model",
        "use": "retain_as_route_evidence",
    },
    {
        "source_id": "HIST-02",
        "path": "HeiQ_V2/outputs/wp1_literature_ion_uncertainty_v12/literature_sources.csv",
        "role": "Named membrane and literature-source register",
        "evidence_class": "literature_register",
        "use": "retain",
    },
    {
        "source_id": "HIST-03",
        "path": "HeiQ_V2/outputs/wp1_literature_ion_uncertainty_v12/literature_ion_priors.csv",
        "role": "H/Li/Na/K property priors and evidence labels",
        "evidence_class": "literature_bounded_prior",
        "use": "retain_with_conditions",
    },
    {
        "source_id": "HIST-04",
        "path": "HeiQ_V2/outputs/wp1_inverse_design_value_of_information_v13/inverse_design_summary_liplus.md",
        "role": "Li route sensitivity and inverse-design result",
        "evidence_class": "historical_conditional_model",
        "use": "retain_as_route_evidence",
    },
    {
        "source_id": "HIST-05",
        "path": "HeiQ_V2/outputs/wp1_inverse_design_value_of_information_v13/inverse_design_optima_all_ions.csv",
        "role": "Cross-ion inverse-design comparison",
        "evidence_class": "historical_conditional_model",
        "use": "retain_as_route_evidence",
    },
    {
        "source_id": "HIST-06",
        "path": "HeiQ_V2/outputs/wp1_supported_membrane_requirements_v14/supported_membrane_summary_liplus.md",
        "role": "Supported Li-membrane engineering checkpoint",
        "evidence_class": "historical_conditional_model",
        "use": "retain_as_route_evidence",
    },
    {
        "source_id": "HIST-07",
        "path": "HeiQ_V2/outputs/wp1_supported_membrane_requirements_v14/supported_membrane_scenarios_liplus.csv",
        "role": "Li supported-membrane thickness/ASR scenarios",
        "evidence_class": "historical_conditional_model",
        "use": "retain_as_route_evidence",
    },
    {
        "source_id": "HIST-08",
        "path": "HeiQ_V2/outputs/wp1_interface_limited_vapor_transport_v15/interface_limited_summary_liplus.md",
        "role": "Vapour-interface reality check for Li route",
        "evidence_class": "historical_conditional_model",
        "use": "retain_as_bottleneck_evidence",
    },
    {
        "source_id": "HIST-09",
        "path": "HeiQ_V2/outputs/wp1_interface_limited_vapor_transport_v15/interface_gate_scenarios_liplus.csv",
        "role": "Li vapour-interface scenario ledger",
        "evidence_class": "historical_conditional_model",
        "use": "retain_as_bottleneck_evidence",
    },
    {
        "source_id": "HIST-09B",
        "path": "HeiQ_V2/outputs/wp1_interface_limited_vapor_transport_v15_RH80_to_RH60/interface_limited_summary_liplus.md",
        "role": "Favourable-gradient vapour-interface comparison for the Li route",
        "evidence_class": "historical_conditional_model",
        "use": "retain_as_gradient_comparison",
    },
    {
        "source_id": "HIST-10",
        "path": "HeiQ_V2/outputs/wp1_feedback_plan_abc_v15/feedback_plan_assessment.md",
        "role": "Legacy nonlinear-profile and inverse requirement check",
        "evidence_class": "historical_model_assessment",
        "use": "retain_with_supersession_notes",
    },
    {
        "source_id": "HIST-11",
        "path": "HeiQ_V2/outputs/wp1_single_carrier_ion_screening_v11/single_carrier_ion_summary.md",
        "role": "Illustrative H/Li/Na/K precursor screen",
        "evidence_class": "illustrative_hypothesis",
        "use": "superseded_by_v12_to_v15",
    },
    {
        "source_id": "HIST-12",
        "path": "XMembrane_Model/data/reference/v11_compat/candidate_materials.csv",
        "role": "Legacy M-ID synthetic material vectors",
        "evidence_class": "synthetic_model_coordinates",
        "use": "benchmark_only",
    },
    {
        "source_id": "HIST-13",
        "path": "HeiQ-Thermodynamical-Analysis/docs/wp1_material_decision_memo.md",
        "role": "Early thermodynamic material target memo",
        "evidence_class": "historical_screening_basis",
        "use": "order_of_magnitude_only",
    },
    {
        "source_id": "HIST-14",
        "path": "HeiQ-Thermodynamical-Analysis/scenarios/nafion_literature_priors.yaml",
        "role": "Early PFSA/Nafion literature priors",
        "evidence_class": "literature_prior",
        "use": "reference_only",
    },
    {
        "source_id": "HIST-15",
        "path": "HeiQ_V2/tools/HeiQ_membrane_sensitivity_nafion_v1/nafion_reference.py",
        "role": "Newer hash-bound Nafion reference library",
        "evidence_class": "literature_function_reference_implementation",
        "use": "current_reference_only",
    },
    {
        "source_id": "HIST-16",
        "path": "HeiQ_V2/tools/HeiQ_membrane_sensitivity_nafion_v1/NAFION_REFERENCE.md",
        "role": "Declared assumptions for the newer Nafion reference library",
        "evidence_class": "literature_function_documentation",
        "use": "current_reference_only",
    },
    {
        "source_id": "HIST-17",
        "path": "HeiQ_V2/outputs/wp1_eo_material_scale_v4/eo_v4_high_transport_number_sweep.csv",
        "role": "Historical hypothetical high-transport-number sweep",
        "evidence_class": "synthetic_model_sweep",
        "use": "explain_transport_numbers_above_100_only",
    },
    {
        "source_id": "HIST-18",
        "path": "HeiQ_V2/outputs/axial_independent_material_sweep_v8/coarse/material_grid_used.csv",
        "role": "Full legacy material-sweep V8 synthetic property grid",
        "evidence_class": "synthetic_model_sweep",
        "use": "historical_parameter_space_only",
    },
    {
        "source_id": "HIST-19",
        "path": "HeiQ_V2/outputs/wp1_inverse_membrane_design_v9/inverse_membrane_design_v9_report.md",
        "role": "Historical V9 inverse membrane design",
        "evidence_class": "historical_inverse_design",
        "use": "historical_parameter_space_only",
    },
    {
        "source_id": "HIST-20",
        "path": "HeiQ_V2/outputs/wp1_transport_parameter_sensitivity_v10/transport_parameter_summary.md",
        "role": "Historical V10 transport-parameter decomposition",
        "evidence_class": "historical_sensitivity",
        "use": "retain_conceptual_decomposition",
    },
    {
        "source_id": "HIST-21",
        "path": "HeiQ_V2/outputs/EO_inverse_material_requirements_v42_full/least_demanding_inverse_envelopes.csv",
        "role": "Historical V42 full inverse material envelopes",
        "evidence_class": "historical_inverse_design",
        "use": "retain_with_receiver_and_hydration_caveats",
    },
    {
        "source_id": "HIST-22",
        "path": "HeiQ_V2/outputs/EO_symmetric_wet_receiver_sink_v53/summary_v53.md",
        "role": "Latest strict wet-receiver study within the V43-V55 branch",
        "evidence_class": "historical_conditional_model",
        "use": "retain_as_under_2V_descendant",
    },
    {
        "source_id": "HIST-23",
        "path": "HeiQ_V2/outputs/EO_symmetric_wet_receiver_sink_v55/selected_reference_design.csv",
        "role": "Historical V55 selected ideal-wet reference",
        "evidence_class": "historical_conditional_model",
        "use": "superseded_by_present_voltage_preference",
    },
    {
        "source_id": "HIST-24",
        "path": "HeiQ_V2/outputs/EO_ERV_inverse_v61_area3000/inverse_requirement_frontiers.csv",
        "role": "Historical direct-EO-in-ERV inverse frontiers",
        "evidence_class": "historical_inverse_design",
        "use": "retain_for_active_erv_material_requirements",
    },
    {
        "source_id": "HIST-25",
        "path": "HeiQ_V2/outputs/EO_v62_bottleneck_parametric/threshold_summary.csv",
        "role": "Historical V62 material-neutral bottleneck thresholds",
        "evidence_class": "historical_conditional_model",
        "use": "retain_as_target_envelope",
    },
    {
        "source_id": "HIST-26",
        "path": "HeiQ_V2/outputs/membrane_sensitivity_nafion_o50_global_fast_v1/global_material_best_cases.csv",
        "role": "Historical broad global sensitivity vectors",
        "evidence_class": "synthetic_global_sensitivity",
        "use": "retain_for_sensitivity_not_material_identity",
    },
    {
        "source_id": "HIST-27",
        "path": "HeiQ_V2/docs/wp1_waiting_period_project_control_v1/claim_ladder.csv",
        "role": "Historical evidence/claim maturity ladder",
        "evidence_class": "qualification_governance",
        "use": "retain_and_align_with_MAT_schema",
    },
    {
        "source_id": "HIST-28",
        "path": "HeiQ_V2/docs/wp1_waiting_period_project_control_v1/experimental_validation_plan.csv",
        "role": "Historical experimental validation plan",
        "evidence_class": "qualification_governance",
        "use": "retain_and_align_with_coupon_plan",
    },
    {
        "source_id": "ARCH-01",
        "path": "deliverables/HeiQ_Complete_Result_Atlas_and_Decision_Basis_2026-08-27_v6.pdf",
        "role": "Most complete frozen historical result atlas",
        "evidence_class": "historical_archive",
        "use": "chronology_and_provenance",
    },
    {
        "source_id": "ARCH-02",
        "path": "deliverables/HeiQ_Material_Parameter_Windows_with_Nafion_v1_2026-08-27_Code_and_Results.zip",
        "role": "Frozen audited material-window package",
        "evidence_class": "historical_archive",
        "use": "reproducible_historical_snapshot",
    },
    {
        "source_id": "ARCH-03",
        "path": "XMembrane_Trond_Study/reports/heiq_eo_complete_result_atlas_v7/data/all_output_inventory.csv",
        "role": "Cross-repository output inventory",
        "evidence_class": "inventory",
        "use": "coverage_control",
    },
    {
        "source_id": "ARCH-04",
        "path": "XMembrane_Trond_Study/reports/heiq_eo_complete_result_atlas_v7/data/downloads_pdf_manifest.csv",
        "role": "Hashed manifest of the previously reviewed Windows Downloads PDFs",
        "evidence_class": "external_document_inventory",
        "use": "coverage_and_duplicate_control",
    },
)


MAT_REQUIREMENTS: tuple[tuple[str, str], ...] = (
    ("MAT-01", "Sorption, desorption and hysteresis"),
    ("MAT-02", "Water diffusivity/mobility and chemical permeance"),
    ("MAT-03", "Electro-osmotic water drag"),
    ("MAT-04", "Wet through-plane ionic conductivity"),
    ("MAT-05", "Membrane and compressed-stack ASR"),
    ("MAT-06", "Dry/wet thickness, swelling and mechanics"),
    ("MAT-07", "Coupled two-sided net water flux and charge"),
    ("MAT-08", "Receiver/electrode/interface compatibility"),
    ("MAT-09", "Provenance, grade and availability"),
)


def _statuses(**updates: str) -> dict[str, str]:
    result = {req_id: "missing" for req_id, _ in MAT_REQUIREMENTS}
    result.update(updates)
    return result


NAMED_MATERIALS: tuple[dict[str, Any], ...] = (
    {
        "candidate_id": "SELEMION_CMVN",
        "name": "Selemion CMVN",
        "identity_type": "named commercial membrane in literature",
        "family": "cation-exchange membrane",
        "form": "H+, Li+, Na+ and K+ chloride forms",
        "role": "primary real-material mechanism evidence anchor",
        "priority": "P0_EVIDENCE_ANCHOR_TEST",
        "decision": "Confirm supply/ion-exchange route and obtain coupons first",
        "quantitative_local_evidence": "Same named membrane platform in liquid at 295+/-1 K: drag H 1.1+/-0.8, Li 9.2+/-0.8, Na 4.9+/-0.2, K 3.7+/-0.4 mol H2O/mol ion; identical physical coupon is not established",
        "direct_eo_reading": "Li form is the closest named local lead, but its measured drag remains below the preferred 1.8-V discrete core (t_w=20 or 25-30 depending replay)",
        "active_erv_reading": "Useful falsification/benchmark; about 11x below the terminal-1 t_w=100.06 coordinate at the Li central value",
        "next_action": "Availability, construction and thickness check; condition/exchange to Li form; run same-sample MAT-01 to MAT-08 coupon sequence",
        "sources": "HIST-02;HIST-03",
        "statuses": _statuses(
            **{
                "MAT-03": "same_named_platform_liquid_literature_not_identical_coupon",
                "MAT-09": "named_grade_and_doi_known_availability_unverified",
            }
        ),
    },
    {
        "candidate_id": "CR61_AZL386",
        "name": "CR61 AZL 386",
        "identity_type": "named membrane in literature",
        "family": "cation-exchange membrane",
        "form": "H+/K+ forms",
        "role": "secondary high-drag counterion reference",
        "priority": "P2",
        "decision": "Retain as a K+/H+ comparison; verify whether an obtainable modern equivalent is needed",
        "quantitative_local_evidence": "Aqueous HCl/KCl literature envelope: H drag near 2 and K drag near 11",
        "direct_eo_reading": "K result approaches the lower edge of broad direct-EO support but is not vapour/same-condition evidence",
        "active_erv_reading": "Far below t_w=100.06 and lacks vapour conductivity/permeance bundle",
        "next_action": "Check identity and availability; use only if coupon construction and Li/Na/K exchange are practical",
        "sources": "HIST-02;HIST-03",
        "statuses": _statuses(
            **{
                "MAT-03": "partial_liquid_literature_H_and_K",
                "MAT-09": "named_membrane_and_doi_known_availability_unverified",
            }
        ),
    },
    {
        "candidate_id": "MF4SC",
        "name": "MF-4SC",
        "identity_type": "named PFSA membrane in literature review",
        "family": "PFSA",
        "form": "H+, Li+ and Na+ forms",
        "role": "alkali-PFSA conductivity lead",
        "priority": "P1",
        "decision": "Seek grade/construction details and a Li-form coupon or an equivalent PFSA route",
        "quantitative_local_evidence": "Fully hydrated conductivity cited as H/Li/Na = 2.8/0.61/0.62 S/m",
        "direct_eo_reading": "Conductivity anchor only; no matched vapour drag/D/sorption bundle",
        "active_erv_reading": "Li conductivity is roughly 38x below the 23.17-S/m terminal-1 coefficient, with non-matched conditions",
        "next_action": "Obtain or identify equivalent membrane; measure vapour sorption, Li drag, D and through-plane conductivity on the same sample",
        "sources": "HIST-02;HIST-03",
        "statuses": _statuses(
            **{
                "MAT-04": "partial_fully_hydrated_literature",
                "MAT-09": "named_material_and_doi_known_grade_availability_unverified",
            }
        ),
    },
    {
        "candidate_id": "NAFION_N117",
        "name": "Nafion N117",
        "identity_type": "named commercial membrane/reference",
        "family": "PFSA",
        "form": "H+, Li+ and Na+ literature forms",
        "role": "thick reference and counterion-change control",
        "priority": "CONTROL",
        "decision": "Use as a benchmark/control, not as the target membrane",
        "quantitative_local_evidence": "Nominal dry thickness 178-183 um; Li/Na conductivity at 98% RH 1.3/1.1 S/m; H-form model drag envelope 0.3-2.5",
        "direct_eo_reading": "H-form drag and D schema do not overlap the current direct-EO target bundle",
        "active_erv_reading": "Reference only: t_w 0.3-2.5 versus 100.06 and sigma_ref 2.57 versus 23.17 S/m",
        "next_action": "Keep one benchmark coupon; do not rank it as a product winner",
        "sources": "CUR-04;HIST-02;HIST-14",
        "statuses": _statuses(
            **{
                "MAT-01": "family_literature_function_not_same_batch",
                "MAT-02": "family_literature_function_not_same_batch",
                "MAT-03": "partial_literature_scenarios_not_device_specific",
                "MAT-04": "partial_literature_near_saturation",
                "MAT-05": "model_derived_not_compressed_coupon",
                "MAT-06": "nominal_product_thickness_only",
                "MAT-09": "named_grade_and_sources_known",
            }
        ),
    },
    {
        "candidate_id": "NAFION_NR211",
        "name": "Nafion NR211",
        "identity_type": "named commercial membrane/reference",
        "family": "PFSA",
        "form": "H-form local adapter",
        "role": "thin reference coupon",
        "priority": "CONTROL",
        "decision": "Use as the primary thin PFSA control, not as the target membrane",
        "quantitative_local_evidence": "Nominal dry thickness 25 um; L/sigma(lambda=8) = 6.413e-6 ohm m2; H-form drag reference 0.3-2.5. In the matched active/passive ERV control, 91.63% of active-row transport is diffusive; EO uses 0.444 kW while passive needs 2.653% more area and 0.493 kW less electricity",
        "direct_eo_reading": "Correctly thin but fails the drag/property-bundle match",
        "active_erv_reading": "Useful negative/mechanism control: the matched result is primarily passive diffusion, and the correlation leaves its declared hydration domain locally",
        "next_action": "Acquire/control coupon if not already available; run identical fixture protocol alongside candidates",
        "sources": "CUR-04;CUR-06;CUR-07;CUR-31",
        "statuses": _statuses(
            **{
                "MAT-01": "family_literature_function_not_same_batch",
                "MAT-02": "family_literature_function_not_same_batch",
                "MAT-03": "declared_reference_scenarios_not_measurement",
                "MAT-04": "family_literature_function_not_same_batch",
                "MAT-05": "L_over_sigma_derived_not_stack_EIS",
                "MAT-06": "nominal_product_thickness_only",
                "MAT-09": "named_grade_and_sources_known",
            }
        ),
    },
    {
        "candidate_id": "NAFION_NR212",
        "name": "Nafion NR212",
        "identity_type": "named commercial membrane/reference",
        "family": "PFSA",
        "form": "H form",
        "role": "thickness control",
        "priority": "CONTROL",
        "decision": "Retain only if a 50-um PFSA thickness control is useful",
        "quantitative_local_evidence": "Nominal dry thickness 50 um; L/sigma(lambda=8) = 1.283e-5 ohm m2",
        "direct_eo_reading": "Reference property bundle remains outside the target",
        "active_erv_reading": "Reference only",
        "next_action": "Optional control; lower priority than NR211 and N117",
        "sources": "CUR-04",
        "statuses": _statuses(
            **{
                "MAT-01": "family_literature_function_not_same_batch",
                "MAT-02": "family_literature_function_not_same_batch",
                "MAT-03": "declared_reference_scenarios_not_measurement",
                "MAT-04": "family_literature_function_not_same_batch",
                "MAT-05": "L_over_sigma_derived_not_stack_EIS",
                "MAT-06": "nominal_product_thickness_only",
                "MAT-09": "named_grade_and_sources_known",
            }
        ),
    },
    {
        "candidate_id": "NAFION_N115",
        "name": "Nafion N115",
        "identity_type": "named commercial membrane/reference",
        "family": "PFSA",
        "form": "H form plus Na/K liquid-D context",
        "role": "legacy reference",
        "priority": "CONTROL_LOW",
        "decision": "Keep in the evidence base; procure only for a deliberate thickness/counterion comparison",
        "quantitative_local_evidence": "Nominal dry thickness 127 um; Motupally liquid-to-dry-N2 limiting flux is an optimistic non-device reference",
        "direct_eo_reading": "Does not match current joint target",
        "active_erv_reading": "Does not match current joint target",
        "next_action": "No first-wave procurement unless already on hand",
        "sources": "CUR-04;HIST-14",
        "statuses": _statuses(
            **{
                "MAT-01": "family_literature_function_not_same_batch",
                "MAT-02": "partial_non_device_literature",
                "MAT-03": "declared_reference_scenarios_not_measurement",
                "MAT-04": "family_literature_function_not_same_batch",
                "MAT-05": "L_over_sigma_derived_not_stack_EIS",
                "MAT-06": "nominal_product_thickness_only",
                "MAT-09": "named_grade_and_sources_known",
            }
        ),
    },
    {
        "candidate_id": "NAFION_N112",
        "name": "Nafion N112",
        "identity_type": "named commercial membrane/reference",
        "family": "PFSA",
        "form": "H form",
        "role": "legacy model/data-chain reference",
        "priority": "CONTROL_LOW",
        "decision": "Retain as historical reference; do not treat the ECSIM MEA slopes as membrane properties",
        "quantitative_local_evidence": "Nominal dry thickness 50.8 um; local v5 reference vector t_w=0.445, D=1.729e-10 m2/s, sigma=1.672 S/m",
        "direct_eo_reading": "Reference values are far outside the direct-EO target",
        "active_erv_reading": "Reference values are far outside the terminal-1 bundle",
        "next_action": "No first-wave procurement unless needed to reproduce the legacy model chain",
        "sources": "HIST-14",
        "statuses": _statuses(
            **{
                "MAT-01": "family_literature_function_not_same_batch",
                "MAT-02": "model_adapter_from_literature",
                "MAT-03": "model_adapter_from_literature",
                "MAT-04": "model_adapter_from_literature",
                "MAT-05": "MEA_apparent_resistance_not_membrane_ASR",
                "MAT-06": "nominal_product_thickness_only",
                "MAT-09": "named_grade_and_sources_known",
            }
        ),
    },
    {
        "candidate_id": "NAFION_120",
        "name": "Nafion 120",
        "identity_type": "named membrane in literature",
        "family": "PFSA",
        "form": "Na+ and K+ liquid-equilibrated forms",
        "role": "alkali-water-diffusivity reference",
        "priority": "P2_REFERENCE",
        "decision": "Retain as a property reference; verify modern equivalent/availability before any procurement",
        "quantitative_local_evidence": "Liquid-equilibrated 25 C D_w: Na 2.65e-10 and K 2.15e-10 m2/s",
        "direct_eo_reading": "D-only evidence is insufficient and conditions do not match the coupon",
        "active_erv_reading": "D lies within a sampled current axis but the rest of the material vector is missing",
        "next_action": "Use to bound literature, not to rank without matched drag/conductivity/sorption",
        "sources": "HIST-02;HIST-03",
        "statuses": _statuses(
            **{
                "MAT-02": "partial_liquid_literature_Na_and_K",
                "MAT-09": "named_membrane_and_doi_known_availability_unverified",
            }
        ),
    },
    {
        "candidate_id": "BPSH",
        "name": "BPSH",
        "identity_type": "named polymer family in literature",
        "family": "sulfonated aromatic proton conductor",
        "form": "H form",
        "role": "non-PFSA vapour reference/family lead",
        "priority": "P2",
        "decision": "Retain as the only named non-PFSA family in the local vapour-drag evidence",
        "quantitative_local_evidence": "Vapour-equilibrated proton-drag source shared with Nafion; local register reports the source but not a complete BPSH property vector",
        "direct_eo_reading": "Potentially broadens chemistry beyond PFSA; quantitative joint gap is unknown",
        "active_erv_reading": "No local evidence of the high-drag/high-conductivity terminal-1 bundle",
        "next_action": "Identify exact BPSH chemistry and availability; request matched vapour sorption/D/drag/conductivity before procurement",
        "sources": "HIST-02;HIST-03",
        "statuses": _statuses(
            **{
                "MAT-03": "partial_vapour_H_form_literature",
                "MAT-09": "family_and_doi_known_exact_grade_availability_missing",
            }
        ),
    },
)


LITERATURE_LEADS: tuple[dict[str, str], ...] = (
    {
        "lead_id": "LIT_MICROPOROUS_POLYAMINE",
        "name": "Intrinsically/molecularly rigid microporous polyamine membranes",
        "lead_type": "mechanism and chemistry lead",
        "local_evidence": "Madrid et al. 2021, DOI 10.1016/j.elecom.2021.107110, and Madrid et al. 2023, DOI 10.1021/acsami.3c10220; local reports note very high apparent water-per-charge ratios",
        "limitation": "Liquid-filled anionic systems with nonlinear finite-bias behaviour; apparent ratios cannot be inserted as an intrinsic vapour-HVAC drag coefficient",
        "material_search_use": "Search the chemistry/architecture family, while requiring reciprocal flux/charge definitions and vapour-state measurements",
        "priority": "P1_EXPLORATORY",
        "sources": "ARCH-04",
    },
    {
        "lead_id": "LIT_GERLACH_2008",
        "name": "Nafion and plaster-silica-gel EO dehumidification membranes",
        "lead_type": "direct EO-dehumidification precedent",
        "local_evidence": "Gerlach 2008 is the clearest direct dehumidification material precedent found in the downloaded/local report chain",
        "limitation": "No complete, traceable property vector or supplier row was extracted locally",
        "material_search_use": "Recover construction and operating conditions; treat plaster-silica as an architecture lead, not a ranked product",
        "priority": "P1_LITERATURE_RECOVERY",
        "sources": "ARCH-04",
    },
    {
        "lead_id": "LIT_YAROSHCHUK_2017",
        "name": "Porous media and perforated ion-exchange membrane architecture",
        "lead_type": "asymmetric/AC architecture lead",
        "local_evidence": "Yaroshchuk et al. 2017, DOI 10.1039/C6FD00248J; retained separately from the dense-ionomer V13-V15 branch",
        "limitation": "Architecture result without a candidate property bundle for the HeiQ vapour duty",
        "material_search_use": "Keep as a separate porous/perforated route and as context for rectified symmetric AC",
        "priority": "P2_ARCHITECTURE",
        "sources": "HIST-04;HIST-08;HIST-09B;ARCH-04",
    },
    {
        "lead_id": "LIT_GRADED_BUFFER_LAYER",
        "name": "Graded ion-exchange, porous adsorbing or MOF-buffered composite",
        "lead_type": "unqualified composite hypothesis",
        "local_evidence": "The downloaded Updated EO Membrane Model proposes alternative carriers, tailored/graded ion-exchange structures and porous/adsorbing or MOF-containing inner layers",
        "limitation": "No locally extracted composition, grade, measurement or supplier evidence",
        "material_search_use": "Use only as a search taxonomy and coupon-architecture hypothesis after the base ionomer route is characterized",
        "priority": "P2_EXPLORATORY",
        "sources": "ARCH-04",
    },
)


AVAILABILITY_SHEET: tuple[dict[str, str], ...] = (
    {
        "search_id": "SEARCH_SELEMION_CMVN",
        "candidate_or_route": "Selemion CMVN",
        "record_type": "named_membrane_evidence_anchor",
        "priority": "P0",
        "target_form_or_construction": "One traceable lot; Li+, Na+, K+ and H+ forms if exchange is chemically defensible",
        "proposed_role": "Primary counter-ion mechanism coupon",
        "local_evidence_tier": "E2_named_grade_unmatched_bundle",
        "supplier": "",
        "procurement_identifier": "",
        "construction_and_support": "",
        "nominal_thickness_um": "",
        "availability_status": "UNVERIFIED_LOCAL",
        "lot_or_sample_id": "",
        "first_question": "Can the exact CMVN construction be supplied with thickness, reinforcement, ion-form and lot documentation?",
        "decision_after_local_audit": "First availability check; not a validated lead solution",
        "sources": "HIST-02;HIST-03",
    },
    {
        "search_id": "SEARCH_NAFION_NR211_NR212",
        "candidate_or_route": "Nafion NR211 and NR212",
        "record_type": "commercial_reference_controls",
        "priority": "P0_CONTROL",
        "target_form_or_construction": "H-form, 25 and 50 um nominal dry thickness; optional Li-exchanged subset",
        "proposed_role": "Method and thickness controls",
        "local_evidence_tier": "E2_commercial_grade_reference",
        "supplier": "",
        "procurement_identifier": "",
        "construction_and_support": "solution-cast PFSA reference",
        "nominal_thickness_um": "25;50",
        "availability_status": "UNVERIFIED_LOCAL",
        "lot_or_sample_id": "",
        "first_question": "Are current lots available with certificate, nominal thickness and conditioning guidance?",
        "decision_after_local_audit": "Acquire only as controls, never as the desired optimum",
        "sources": "CUR-04;HIST-15;HIST-16",
    },
    {
        "search_id": "SEARCH_MF4SC_OR_EQUIVALENT",
        "candidate_or_route": "MF-4SC or traceable alkali-PFSA equivalent",
        "record_type": "named_literature_family_lead",
        "priority": "P1",
        "target_form_or_construction": "Li+ form, thin or supported coupon",
        "proposed_role": "Alkali-ionomer conductivity route",
        "local_evidence_tier": "E2_property_fragment",
        "supplier": "",
        "procurement_identifier": "",
        "construction_and_support": "",
        "nominal_thickness_um": "",
        "availability_status": "UNVERIFIED_LOCAL",
        "lot_or_sample_id": "",
        "first_question": "What exact grade/construction reproduces the cited Li/Na conductivity and is it available as membrane film?",
        "decision_after_local_audit": "Route lead; requires identity and matched vapour properties",
        "sources": "HIST-02;HIST-03",
    },
    {
        "search_id": "SEARCH_CR61_AZL386",
        "candidate_or_route": "CR61 AZL 386 or traceable modern equivalent",
        "record_type": "named_literature_membrane",
        "priority": "P1_SECONDARY",
        "target_form_or_construction": "H+/K+ reference; Li/Na/K exchange only if construction permits",
        "proposed_role": "High-drag counter-ion comparison",
        "local_evidence_tier": "E2_property_fragment",
        "supplier": "",
        "procurement_identifier": "",
        "construction_and_support": "",
        "nominal_thickness_um": "",
        "availability_status": "UNVERIFIED_LOCAL",
        "lot_or_sample_id": "",
        "first_question": "Is the historical membrane or a compositionally equivalent current grade obtainable?",
        "decision_after_local_audit": "Use only if identity, construction and exchange route are practical",
        "sources": "HIST-02;HIST-03",
    },
    {
        "search_id": "SEARCH_BPSH_NON_PFSA",
        "candidate_or_route": "BPSH / non-PFSA sulfonated aromatic ionomer",
        "record_type": "polymer_family_lead",
        "priority": "P1_EXPLORATORY",
        "target_form_or_construction": "Thin H+ and Li+ membrane where stable",
        "proposed_role": "Non-PFSA vapour-ionomer comparison",
        "local_evidence_tier": "E1_family_mechanism",
        "supplier": "",
        "procurement_identifier": "",
        "construction_and_support": "",
        "nominal_thickness_um": "",
        "availability_status": "NO_EXACT_LOCAL_GRADE",
        "lot_or_sample_id": "",
        "first_question": "Which exact BPSH chemistry/IEC and membrane construction correspond to the vapour-drag literature?",
        "decision_after_local_audit": "Identify chemistry before requesting coupons",
        "sources": "HIST-02;HIST-03",
    },
    {
        "search_id": "SEARCH_MICROPOROUS_POLYAMINE",
        "candidate_or_route": "Intrinsically microporous polyamine membrane",
        "record_type": "chemistry_and_mechanism_lead",
        "priority": "P1_EXPLORATORY",
        "target_form_or_construction": "Vapour-compatible free-standing or supported anionic film",
        "proposed_role": "High apparent water-per-charge mechanism test",
        "local_evidence_tier": "E1_literature_mechanism",
        "supplier": "",
        "procurement_identifier": "",
        "construction_and_support": "",
        "nominal_thickness_um": "",
        "availability_status": "NO_PRODUCT_IDENTIFIED_LOCAL",
        "lot_or_sample_id": "",
        "first_question": "Can the reported chemistry be obtained as a stable vapour-state coupon with reciprocal flux/charge data?",
        "decision_after_local_audit": "Retain; do not transfer liquid apparent drag directly into the HVAC model",
        "sources": "ARCH-04",
    },
    {
        "search_id": "SEARCH_PLASTER_SILICA",
        "candidate_or_route": "Plaster-silica-gel EO dehumidification membrane",
        "record_type": "direct_dehumidification_architecture_lead",
        "priority": "P1_LITERATURE_RECOVERY",
        "target_form_or_construction": "Construction matching Gerlach 2008",
        "proposed_role": "Direct EO-dehumidification precedent coupon",
        "local_evidence_tier": "E1_literature_precedent",
        "supplier": "",
        "procurement_identifier": "",
        "construction_and_support": "",
        "nominal_thickness_um": "",
        "availability_status": "CONSTRUCTION_NOT_EXTRACTED_LOCAL",
        "lot_or_sample_id": "",
        "first_question": "What exact composition, thickness, electrodes and humidity boundary produced the reported effect?",
        "decision_after_local_audit": "Recover full paper/construction before any procurement action",
        "sources": "ARCH-04",
    },
    {
        "search_id": "SEARCH_POROUS_PERFORATED_IEM",
        "candidate_or_route": "Porous/perforated ion-exchange architecture",
        "record_type": "architecture_lead",
        "priority": "P2",
        "target_form_or_construction": "Asymmetric porous medium or perforated IEM with controlled interfaces",
        "proposed_role": "Rectification/asymmetric EO route",
        "local_evidence_tier": "E1_literature_architecture",
        "supplier": "",
        "procurement_identifier": "",
        "construction_and_support": "",
        "nominal_thickness_um": "",
        "availability_status": "NO_PRODUCT_IDENTIFIED_LOCAL",
        "lot_or_sample_id": "",
        "first_question": "Which geometry and material asymmetry can be reproduced at vapour boundaries and below 2 V?",
        "decision_after_local_audit": "Separate from dense-ionomer ranking; test only as a declared architecture",
        "sources": "HIST-04;HIST-08;ARCH-04",
    },
    {
        "search_id": "SEARCH_GRADED_BUFFER_COMPOSITE",
        "candidate_or_route": "Graded/adsorbing/MOF-buffered composite",
        "record_type": "concept_architecture_lead",
        "priority": "P2",
        "target_form_or_construction": "Ion-conducting selective skins plus a controlled water-buffer layer",
        "proposed_role": "Reduce hydration sensitivity or introduce useful asymmetry",
        "local_evidence_tier": "E0_concept",
        "supplier": "",
        "procurement_identifier": "",
        "construction_and_support": "",
        "nominal_thickness_um": "",
        "availability_status": "NO_COMPOSITION_IDENTIFIED_LOCAL",
        "lot_or_sample_id": "",
        "first_question": "What composition gives reversible water capacity without short-circuit diffusion or excessive ASR?",
        "decision_after_local_audit": "Search taxonomy only until a base ionomer coupon is characterized",
        "sources": "ARCH-04",
    },
)

# One run in the controlled-flow fixture uses an approximately 80 x 80 mm
# physical coupon. Availability is not procurement-ready until sheet size and
# usable coupon yield are recorded explicitly. The replicate count is frozen
# after the pilot and conditioning-yield check, not invented in this desk audit.
AVAILABILITY_SHEET = tuple(
    {
        **row,
        "required_physical_coupon_mm": "80 x 80",
        "available_sheet_dimensions_mm": "",
        "usable_80x80_coupon_count": "",
        "minimum_order_quantity": "",
        "replicate_count_status": "TO_BE_FROZEN_AFTER_PILOT_AND_CONDITIONING_YIELD",
    }
    for row in AVAILABILITY_SHEET
)


DEVELOPMENT_ROUTES: tuple[dict[str, str], ...] = (
    {
        "route_id": "ROUTE_LI_CEM",
        "route": "Li+-form cation-exchange membrane",
        "basis": "V12 ranks Li+ above Na+, K+ and H+ under the declared vapour-stress prior",
        "quantitative_anchor": "At 100 um and 0.6 V: median flux 0.442 kg/m2/h, median SEC 0.125 kWh/kg; conditional SEC<=0.17 share 81.5%",
        "current_interpretation": "Still the best prior real-chemistry lead, but the old 20-m2 area probability is not a current gate",
        "first_material": "Selemion CMVN Li+ form",
        "priority": "P1",
        "sources": "HIST-01;HIST-02;HIST-03",
    },
    {
        "route_id": "ROUTE_LI_SUPPORTED",
        "route": "Thin supported Li+-form active layer",
        "basis": "V13 optimum hit the minimum-thickness boundary; V14 added support/interface ASR",
        "quantitative_anchor": "25 um + 0.05 mOhm m2, 0.675 V: median flux 2.35 kg/m2/h and median SEC 0.136 kWh/kg",
        "current_interpretation": "Development checkpoint, not a material or mechanical recommendation; re-evaluate without area acceptance cap",
        "first_material": "Supported Selemion/PFSA-equivalent Li+ coupon after availability review",
        "priority": "P1",
        "sources": "HIST-04;HIST-05;HIST-06;HIST-07",
    },
    {
        "route_id": "ROUTE_LI_VAPOUR_INTERFACE",
        "route": "Li+-form membrane with measured two-sided vapour exchange",
        "basis": "V15 shows interface/hydration losses can erase the apparent bulk-material advantage",
        "quantitative_anchor": "At 25 um, k_int=0.1 and 0.05 mOhm m2: 65->80% RH gives median flux 0.434 kg/m2/h and SEC 0.217 kWh/kg at 0.55 V; 80->60% RH gives 1.164 kg/m2/h and 0.142 kWh/kg at 0.60 V",
        "current_interpretation": "Primary coupon falsification route; direction and both films matter, while area remains diagnostic only",
        "first_material": "Same Li+ coupon as ROUTE_LI_CEM, tested with independent source/receiver films",
        "priority": "P0_EXPERIMENT",
        "sources": "HIST-08;HIST-09;HIST-09B",
    },
    {
        "route_id": "ROUTE_NA_K_CONTROLS",
        "route": "Na+ and K+ counterion controls",
        "basis": "Same-platform Selemion data motivate a clean counterion falsification experiment on one future lot",
        "quantitative_anchor": "Selemion drag Na 4.9+/-0.2 and K 3.7+/-0.4 versus Li 9.2+/-0.8",
        "current_interpretation": "Use on the same base membrane to test whether the Li ranking survives vapour conditioning",
        "first_material": "Selemion CMVN exchanged to Li/Na/K from the same lot",
        "priority": "P1_CONTROL",
        "sources": "HIST-02;HIST-03",
    },
    {
        "route_id": "ROUTE_DIRECT_EO_1P8V",
        "route": "Direct EO below 2 V",
        "basis": "Current six-axis and joint material-window replays",
        "quantitative_anchor": "Preferred discrete cores: t_w=25/30 at j=75/100 A/m2 in the fixed screen; broader 384/384 core at t_w=20 and j=100/150 A/m2",
        "current_interpretation": "Material-operating region only; with 0.85-V fixed losses there are zero modern-comparator-positive rows before receiver",
        "first_material": "Li-route coupons plus non-PFSA family leads; do not assume any named membrane passes",
        "priority": "P1_SCREEN",
        "sources": "CUR-02;CUR-03",
    },
    {
        "route_id": "ROUTE_POST_ERV_O30",
        "route": "Post-ERV EO to the O30 moisture endpoint",
        "basis": "The governing V8 decision report selects this as the first system-relevant controlled-flow coupon target",
        "quantitative_anchor": "Post-ERV O30 removes 1228.27 kg/h; the Terminal-1 D-only screen has sampled solutions for all seven D values from 1e-14 to 1e-9 m2/s at 1.00-1.25 V, while the conditional power window changes from +162.416 to -181.413 kW",
        "current_interpretation": "Primary system experiment, not a material result: replay measured same-coupon properties and preserve the conditional receiver/BOP energy boundary",
        "first_material": "Li-route evidence-anchor coupon and PFSA controls in the 25-cm2 controlled-flow fixture",
        "priority": "P0_FIRST_SYSTEM_EXPERIMENT",
        "sources": "CUR-00;CUR-22;CUR-25;CUR-28",
    },
    {
        "route_id": "ROUTE_DIRECT_ACTIVE_ERV",
        "route": "EO integrated directly into the ERV core",
        "basis": "Current terminal-1 active-ERV model coordinate",
        "quantitative_anchor": "t_w=100.0608, D_ref=1.598e-14 m2/s, sigma_ref=23.1719 S/m, L=36.9137 um; 178/320 rows close target transport, 50/320 pass the engineering screen and 0/320 pass the full coupled gate",
        "current_interpretation": "Open secondary architecture: the 0.25-V, 34425-m2 row is only a conditional diagnostic; a post-release fixed-area weather replay has O80/O50 engineering passes but O30 fails the stack screen, all full-system claims remain false, and no named material matches the joint vector",
        "first_material": "Replay each measured post-ERV coupon only after its passive transfer and both film responses are measured; do not search D alone",
        "priority": "P1_SECONDARY_TARGET",
        "sources": "CUR-00;CUR-06;CUR-07;CUR-18;CUR-19;CUR-20;CUR-29;CUR-30;CUR-32;CUR-33;CUR-34",
    },
)


SYNTHETIC_TARGETS: tuple[dict[str, str], ...] = (
    {
        "target_id": "TERMINAL1_ANCHOR",
        "kind": "current inverse-design coordinate",
        "properties": "t_w=100.0608; D_ref=1.59788e-14 m2/s; sigma_ref=23.1719 S/m; L=36.9137 um; alpha_D=2; alpha_sigma=4",
        "allowed_use": "Active-ERV/post-ERV replay target and gap metric",
        "forbidden_interpretation": "Not a material, product, supplier candidate or validated membrane",
        "sources": "CUR-06;CUR-07",
    },
    {
        "target_id": "DIRECT_EO_1P8V_CORE",
        "kind": "current discrete model region",
        "properties": "Fixed-screen t_w=25/30, j=75/100 A/m2; broad core t_w=20, j=100/150 A/m2 with sampled D/ASR/L and retention 1.25/1.5",
        "allowed_use": "Coupon screening and measured-candidate replay",
        "forbidden_interpretation": "Not a continuous tolerance box and not one existing membrane",
        "sources": "CUR-02;CUR-03",
    },
    {
        "target_id": "M08786",
        "kind": "legacy material-sweep V8 coordinate",
        "properties": "t_w=10.9234; D=1e-12 m2/s; sigma=50 S/m; L=50 um",
        "allowed_use": "Historical benchmark",
        "forbidden_interpretation": "Not an identified material",
        "sources": "HIST-12;ARCH-01",
    },
    {
        "target_id": "M08794",
        "kind": "legacy material-sweep V8 coordinate",
        "properties": "t_w=10.9234; D=1e-12 m2/s; sigma=50 S/m; L=100 um",
        "allowed_use": "Historical benchmark",
        "forbidden_interpretation": "Not an identified material",
        "sources": "HIST-12;ARCH-01",
    },
    {
        "target_id": "M11675",
        "kind": "legacy synthetic V11 coordinate",
        "properties": "t_w=36.2051; D=1e-12 m2/s; sigma=50 S/m; L=100 um; activity exponents 2/4/0",
        "allowed_use": "Historical robust-ranking benchmark",
        "forbidden_interpretation": "Not an identified material",
        "sources": "HIST-12;ARCH-01",
    },
    {
        "target_id": "V43_SELECTED_POINT",
        "kind": "legacy inverse property point",
        "properties": "70x PFSA drag; 0.1x PFSA D; ASR 5e-6 ohm m2; retention 1.5; L=20 um",
        "allowed_use": "Show why surface closure changed the conclusion",
        "forbidden_interpretation": "Disappears under V44 robust surface gates; not a material",
        "sources": "ARCH-01",
    },
    {
        "target_id": "M00653",
        "kind": "legacy V43 conditional target label",
        "properties": "70x PFSA drag; 0.1x PFSA D; L=20 um; ASR=5e-6 ohm m2; retention=1.5",
        "allowed_use": "Historical illustration of a point that passed an intermediate conditional screen",
        "forbidden_interpretation": "Invalidated by the V44 robust-surface result; not an identified material",
        "sources": "ARCH-01",
    },
    {
        "target_id": "GLOBAL_0041",
        "kind": "legacy broad global-sensitivity vector",
        "properties": "t_w=59.585; D=1.803e-11 m2/s; sigma=0.1458 S/m; L=127.5 um",
        "allowed_use": "Historical global-sensitivity comparison",
        "forbidden_interpretation": "No material identity and no same-sample evidence",
        "sources": "HIST-26",
    },
    {
        "target_id": "V4_HIGH_TRANSPORT_NUMBER_AXIS",
        "kind": "legacy hypothetical sweep axis",
        "properties": "Independent water transport-number sweep extending to t_w=150",
        "allowed_use": "Explain why older simulations contained transport numbers above 100",
        "forbidden_interpretation": "No named membrane demonstrated t_w above 100; the companion material template is empty",
        "sources": "HIST-17",
    },
    {
        "target_id": "LI_V14_CHECKPOINT",
        "kind": "historical supported-membrane route coordinate",
        "properties": "Li+; L=25 um; added ASR=5e-5 ohm m2; selected voltage=0.675 V",
        "allowed_use": "Design a Li-route coupon and compare support penalties",
        "forbidden_interpretation": "Not a mechanical recommendation or measured membrane",
        "sources": "HIST-06;HIST-07",
    },
)


SUPERSEDED_CONSTRAINTS: tuple[dict[str, str], ...] = (
    {
        "constraint_id": "AREA_20_M2",
        "legacy_statement": "Area <=20 m2 used in V12-V15 probability summaries",
        "current_treatment": "Diagnostic only; no exploratory membrane-area acceptance cap",
        "reason": "User removed the area limit and current closure treats area as a scale-up output",
        "sources": "CUR-00;CUR-01;HIST-01;HIST-04;HIST-08",
    },
    {
        "constraint_id": "AREA_100_M2",
        "legacy_statement": "Area <=100 m2 in the legacy Nafion-derived v7 stage gate",
        "current_treatment": "Superseded",
        "reason": "Older system basis and explicitly removed area acceptance cap",
        "sources": "ARCH-01",
    },
    {
        "constraint_id": "CURRENT_21_A_M2",
        "legacy_statement": "21 A/m2 discussed as a possible limitation",
        "current_treatment": "No such gate; report solved current density",
        "reason": "Current-density values are operating/diagnostic coordinates, not a material acceptance ceiling",
        "sources": "CUR-00;CUR-01;CUR-03",
    },
    {
        "constraint_id": "CURRENT_2000_A_M2",
        "legacy_statement": "2000 A/m2 cap in V12-V15 dense-ionomer screens",
        "current_treatment": "Historical numerical/screening bound, not a current acceptance rule",
        "reason": "Keep only when interpreting those legacy probabilities",
        "sources": "HIST-01;HIST-04;HIST-06",
    },
    {
        "constraint_id": "VOLTAGE_5_V",
        "legacy_statement": "Earlier sweeps extended to 5 V or above",
        "current_treatment": "Preferred material work is below 2 V",
        "reason": "Current direct-EO window is reported at 1.8 and 2.0 V; active-ERV target is lower",
        "sources": "CUR-00;CUR-01;CUR-02;CUR-03",
    },
    {
        "constraint_id": "NAFION_TARGET",
        "legacy_statement": "Nafion-derived multipliers used as a design language",
        "current_treatment": "Nafion/PFSA is a reference/control, not the target material",
        "reason": "Its drag and joint material vector do not match the current inverse targets",
        "sources": "CUR-00;CUR-01;CUR-02;CUR-04",
    },
    {
        "constraint_id": "POSITIVE_SURFACE_GRADIENT",
        "legacy_statement": "Positive passive surface direction used as a feasibility gate",
        "current_treatment": "Regime diagnostic only",
        "reason": "Active EO can transport uphill when thermodynamic coupling and dissipation close",
        "sources": "CUR-00;CUR-01;CUR-07",
    },
    {
        "constraint_id": "LOW_D_ALONE",
        "legacy_statement": "Low scalar D treated as an independently sufficient material direction",
        "current_treatment": "Rank the coupled chemical-permeance bundle D(dCw/da)/L plus drag, conductivity, ASR and films",
        "reason": "The focused D study froze the other properties",
        "sources": "CUR-01;CUR-03;CUR-08",
    },
    {
        "constraint_id": "HISTORICAL_SEC",
        "legacy_statement": "50-100 Wh/kg water (sometimes 150 Wh/kg) black-box target",
        "current_treatment": "Order-of-magnitude context only",
        "reason": "The modern comparator and receiver/BOP ledger are different and incomplete",
        "sources": "HIST-13;CUR-00;CUR-01",
    },
)


HISTORICAL_SCREEN_MILESTONES: tuple[dict[str, str], ...] = (
    {
        "milestone": "V4 high-transport-number sweep",
        "retained_result": "Synthetic transport-number axis extends to 150",
        "current_use": "Explains the earlier >100 results",
        "claim_boundary": "Independent hypothetical properties; no named material or populated candidate template",
        "sources": "HIST-17",
    },
    {
        "milestone": "Legacy material-sweep V8/V11 synthetic search",
        "retained_result": "Legacy material-sweep V8 used 2304 hypothetical property combinations; 12 compatibility M-ID vectors were retained for later replays",
        "current_use": "Parameter-space history and regression benchmarks",
        "claim_boundary": "M-IDs are model coordinates, not products",
        "sources": "HIST-12;HIST-18;ARCH-01",
    },
    {
        "milestone": "V9/V10 inverse and sensitivity work",
        "retained_result": "Built Nafion-relative envelopes and decomposed effective transport into carrier and drag terms",
        "current_use": "Search vocabulary and mechanism decomposition",
        "claim_boundary": "Properties were intentionally independent and the 2000-A/m2 screen is historical",
        "sources": "HIST-19;HIST-20",
    },
    {
        "milestone": "V12 literature-bounded ion screen",
        "retained_result": "At 0.6 V the median flux/SEC were H 0.385/1.22, Li 0.442/0.125, Na 0.272/0.197 and K 0.281/0.232 kg/m2/h and kWh/kg",
        "current_use": "Prioritize Li+-form CEM/PFSA-like coupons",
        "claim_boundary": "Conditional cross-study priors, not candidate success probabilities",
        "sources": "HIST-01;HIST-02;HIST-03",
    },
    {
        "milestone": "V13 Li inverse design",
        "retained_result": "15 um and 0.6375 V; median flux 3.57 kg/m2/h and SEC 0.131 kWh/kg; conductivity dominated value of information",
        "current_use": "Measure vapour conductivity first, then drag and D/sorption",
        "claim_boundary": "Optimum sat on the minimum-thickness boundary",
        "sources": "HIST-04;HIST-05",
    },
    {
        "milestone": "V14 supported Li checkpoint",
        "retained_result": "25 um plus 0.05 mOhm m2 at 0.675 V; median flux 2.35 kg/m2/h and SEC 0.136 kWh/kg",
        "current_use": "Thin supported-coupon architecture checkpoint",
        "claim_boundary": "Historical conditional result, not a mechanical recommendation",
        "sources": "HIST-06;HIST-07",
    },
    {
        "milestone": "V15 two-interface Li checkpoint",
        "retained_result": "65->80% RH: 0.434 kg/m2/h and 0.217 kWh/kg; 80->60% RH: 1.164 kg/m2/h and 0.142 kWh/kg",
        "current_use": "Test both gradient directions and both films",
        "claim_boundary": "Interface/hydration closure materially reduces bulk-only performance",
        "sources": "HIST-08;HIST-09;HIST-09B",
    },
    {
        "milestone": "V42 full inverse envelopes",
        "retained_result": "Stored inverse requirement envelopes across earlier receiver assumptions",
        "current_use": "Historical lower-demand coordinates",
        "claim_boundary": "Low-hydration and receiver-energy limitations remain",
        "sources": "HIST-21",
    },
    {
        "milestone": "V43/V44 surface-robustness transition",
        "retained_result": "The M00653/70x-drag intermediate target disappeared under the subsequent robust surface test",
        "current_use": "Demonstrate why conditional target points must be replayed through the full closure",
        "claim_boundary": "The selected point is not a candidate",
        "sources": "ARCH-01",
    },
    {
        "milestone": "V53 strict wet-receiver study",
        "retained_result": "Most relevant <=2-V descendant of the V43-V55 branch",
        "current_use": "Historical joint property/operating envelope",
        "claim_boundary": "Conditional ideal-wet receiver branch; sampled rows are not materials",
        "sources": "HIST-22",
    },
    {
        "milestone": "V55 selected ideal-wet point",
        "retained_result": "75x PFSA drag, 0.6x D, 20 um, 5e-6 ohm m2 and retention 1.25 required 3.177 V",
        "current_use": "Historical comparison only",
        "claim_boundary": "Conflicts with the present preference below 2 V",
        "sources": "HIST-23",
    },
    {
        "milestone": "V61 direct EO in ERV",
        "retained_result": "Inverse frontiers for the integrated active-ERV architecture",
        "current_use": "Retain as the pre-current active-ERV material-requirement branch",
        "claim_boundary": "Historical area-conditioned inverse results; no named material",
        "sources": "HIST-24",
    },
    {
        "milestone": "V62 bottleneck envelope",
        "retained_result": "Practical break-even t_w about 18.43/27.39/35.85/44.82 for O60/O50/O40/O30",
        "current_use": "Material-neutral target envelope for direct EO",
        "claim_boundary": "Receiver SEC excluded and no demonstrated material",
        "sources": "HIST-25",
    },
    {
        "milestone": "Current direct-EO window",
        "retained_result": "108/2508 sampled rows pass at 1.8 V; broad six-axis replay has 1116/11520 passing rows",
        "current_use": "Measured-candidate replay region",
        "claim_boundary": "Sampled joint support, not a continuous tolerance box; modern 0.85-V fixed loss gives no pre-receiver comparator-positive row",
        "sources": "CUR-02;CUR-03",
    },
    {
        "milestone": "Current post-ERV O30 common-voltage target",
        "retained_result": "The controlled D-only screen retains sampled O30 solutions for D=1e-14 to 1e-9 m2/s at 1.00-1.25 V; the conditional window falls from +162.416 to -181.413 kW",
        "current_use": "First system-relevant 25-cm2 controlled-flow coupon target",
        "claim_boundary": "Post-ERV water target is 1228.27 kg/h; it is distinct from direct-ERV O30, and the power difference is a conditional budget rather than net saving",
        "sources": "CUR-00;CUR-22;CUR-25;CUR-28",
    },
    {
        "milestone": "Current direct active-ERV anchor",
        "retained_result": "Terminal-1 gives a conditional active-ERV coordinate; direct O30 needs 1.137x common film/diagnostic-area capacity to restore zero surface margin, while symmetric +/-J adds only 0.001518 kg/h above passive",
        "current_use": "Open secondary architecture and measured-candidate diagnostic replay",
        "claim_boundary": "Direct O30 is not post-ERV O30; no named membrane matches, full duty has a zero-bulk-gradient pinch, and frequency/asymmetry rectification is unmodelled",
        "sources": "CUR-00;CUR-06;CUR-07;CUR-18;CUR-19;CUR-20;CUR-29;CUR-30",
    },
    {
        "milestone": "Post-release direct-active-ERV weather-axis extension",
        "retained_result": "At fixed 34425.05-m2 O80 inverse area, conditional O80/O50/O30 voltages are 0.2500/0.1491/0.04155 V and active totals are 107.856/93.293/88.235 kW",
        "current_use": "Exploratory weather-axis visualization only; O30 fails the declared stack and engineering screens",
        "claim_boundary": "Not in V8.1, not a manufactured fixed-stack off-design replay, all full-system claims false, and the three outdoor states are different duties",
        "sources": "CUR-32;CUR-33;CUR-34",
    },
)


MODEL_CONFLICTS: tuple[dict[str, str], ...] = (
    {
        "conflict_id": "NAFION_IMPLEMENTATIONS",
        "subject": "Two different Nafion property implementations",
        "source_a": "CUR-10;CUR-11: rho_dry=1980 kg/m3, polynomial D and n_d=clip(2.5 lambda/22,0,2.5)",
        "source_b": "HIST-15;HIST-16: rho_dry=1970 kg/m3, Motupally piecewise D and declared drag scenarios 0.3/1/2.5",
        "status": "intentional_model_divergence",
        "required_treatment": "Keep separate, name the implementation and conditioning in every comparison",
        "notes": "Do not merge the functions into a fabricated same-sample Nafion vector",
    },
    {
        "conflict_id": "N117_THICKNESS",
        "subject": "Nafion N117 nominal dry thickness",
        "source_a": "Historical v5 convention: 178 um",
        "source_b": "Current grade library: 183 um",
        "status": "condition_or_product_convention_unresolved",
        "required_treatment": "Report 178-183 um with source/condition; current grade register uses 183 um",
        "notes": "Do not silently harmonize",
    },
    {
        "conflict_id": "TERMINAL1_ALIASES",
        "subject": "Terminal-1 inverse vector labels",
        "source_a": "terminal1_anchor; terminal1_post_erv_anchor; legacy_O30_case_94_material",
        "source_b": "Terminal1_optimum and encoded golden ID tw100.061_D1.598e-14_sig23.1719_L36.9137",
        "status": "resolved_same_synthetic_vector",
        "required_treatment": "Map to one TERMINAL1_ANCHOR scenario record",
        "notes": "The word optimum/validated remains numerical, not experimental",
    },
    {
        "conflict_id": "O30_FINAL_ALIAS",
        "subject": "O30_final_material label",
        "source_a": "Historical comparator label",
        "source_b": "No matched local property-source row",
        "status": "unresolved",
        "required_treatment": "Do not auto-alias to TERMINAL1_ANCHOR",
        "notes": "Resolve only if the original row is recovered",
    },
    {
        "conflict_id": "M14424_M14425",
        "subject": "Legacy material-sweep V8 extreme material ID",
        "source_a": "Legacy material-sweep V8 report labels the lowest-current extreme M14425",
        "source_b": "Result atlas labels a t_w=120, D=1e-12 boundary M14424",
        "status": "unresolved_off_by_one_or_label",
        "required_treatment": "Preserve both labels until the raw material-grid row is matched",
        "notes": "Never merge by ID alone",
    },
    {
        "conflict_id": "OFAT_GLOBAL_CONDUCTIVITY",
        "subject": "Apparent conductivity sensitivity",
        "source_a": "Local OFAT near a high-conductivity point appears weak/saturated",
        "source_b": "Broad V13/global screens rank conductivity as important",
        "status": "resolved_scale_dependence",
        "required_treatment": "State the sampled range and reference point",
        "notes": "Local saturation and broad global importance are compatible",
    },
    {
        "conflict_id": "D_VS_CHEMICAL_PERMEANCE",
        "subject": "Diffusivity as a stand-alone ranking variable",
        "source_a": "Older studies quote scalar D or PFSA-relative D",
        "source_b": "Current closure requires D*(dCw/da_w)/L plus drag, conductivity/ASR and films",
        "status": "superseded_interpretation",
        "required_treatment": "Preserve D studies as one-factor sensitivity only; never rank products from D alone",
        "notes": "Conditioning and sorption definition are mandatory",
    },
    {
        "conflict_id": "MAT_ID_SCHEMA_COLLISION",
        "subject": "MAT-01 to MAT-05 identifiers have incompatible historical and current meanings",
        "source_a": "HIST-28 old plan: MAT-01 transport number, MAT-03 conductivity, MAT-04 sorption",
        "source_b": "CUR-05 current schema: MAT-01 sorption, MAT-03 EO drag, MAT-04 conductivity",
        "status": "versioned_schema_collision",
        "required_treatment": "Never join on MAT ID alone; map by property semantics and schema/source version",
        "notes": "The current handoff uses CUR-05 MAT-01 to MAT-09; the historical plan remains operational context only",
    },
    {
        "conflict_id": "RELOCATED_REPORT_MANIFEST_PATHS",
        "subject": "Report-level relative paths after copies are relocated into controlled releases",
        "source_a": "Original EN/NO report manifests resolve and hash their complete source chains",
        "source_b": "Relocated V8/V8.1 report-manifest copies retain original relative paths, so many local targets do not resolve in-place",
        "status": "open_portable_release_traceability_defect",
        "required_treatment": "Use the top release MANIFEST for copy integrity and the original canonical report manifests for scientific provenance",
        "notes": "This is not a scientific discrepancy; unresolved relocated paths are not missing model evidence",
    },
    {
        "conflict_id": "CANONICAL_COPIES",
        "subject": "Frozen report code/data versus canonical implementations",
        "source_a": "reports/*/code and reports/*/data are frozen deliverable copies",
        "source_b": "Top-level scripts/src/config/outputs are the maintained chain",
        "status": "resolved_provenance_rule",
        "required_treatment": "Use frozen copies only for reproduction of that report; integrate from canonical code",
        "notes": "Archive, smoke and backup copies do not create new candidate evidence",
    },
)


ALIAS_REGISTER: tuple[dict[str, str], ...] = (
    {"canonical_id": "TERMINAL1_ANCHOR", "alias": "terminal1_anchor", "record_type": "inverse_design_scenario", "status": "resolved", "treatment": "same exact vector", "sources": "CUR-06"},
    {"canonical_id": "TERMINAL1_ANCHOR", "alias": "terminal1_post_erv_anchor", "record_type": "inverse_design_scenario", "status": "resolved", "treatment": "same exact vector", "sources": "ARCH-01"},
    {"canonical_id": "TERMINAL1_ANCHOR", "alias": "legacy_O30_case_94_material", "record_type": "inverse_design_scenario", "status": "resolved", "treatment": "same exact vector", "sources": "CUR-06"},
    {"canonical_id": "TERMINAL1_ANCHOR", "alias": "Terminal1_optimum", "record_type": "inverse_design_scenario", "status": "resolved", "treatment": "same exact vector", "sources": "ARCH-01"},
    {"canonical_id": "TERMINAL1_ANCHOR", "alias": "tw100.061_D1.598e-14_sig23.1719_L36.9137", "record_type": "inverse_design_scenario", "status": "resolved", "treatment": "rounded encoded ID", "sources": "ARCH-01"},
    {"canonical_id": "UNRESOLVED_O30_FINAL", "alias": "O30_final_material", "record_type": "historical_comparator", "status": "unresolved", "treatment": "do not map to Terminal-1 without source row", "sources": "ARCH-01"},
    {"canonical_id": "UNRESOLVED_V8_EXTREME", "alias": "M14424", "record_type": "synthetic_scenario", "status": "unresolved_pair", "treatment": "preserve alongside M14425", "sources": "ARCH-01"},
    {"canonical_id": "UNRESOLVED_V8_EXTREME", "alias": "M14425", "record_type": "synthetic_scenario", "status": "unresolved_pair", "treatment": "preserve alongside M14424", "sources": "ARCH-01"},
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_sha256sums(release_dir: Path) -> dict[str, Any]:
    """Verify every path declared by a standard two-column SHA256SUMS file."""

    checksum_path = release_dir / "SHA256SUMS"
    failures: list[str] = []
    checked = 0
    if not checksum_path.is_file():
        return {
            "pass": False,
            "checked_file_count": 0,
            "failure_count": 1,
            "failures": [f"missing checksum file: {checksum_path}"],
        }
    for line_number, raw in enumerate(checksum_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        parts = raw.split(maxsplit=1)
        if len(parts) != 2 or len(parts[0]) != 64:
            failures.append(f"malformed SHA256SUMS line {line_number}: {raw}")
            continue
        expected, relative_name = parts
        relative_name = relative_name.lstrip("*")
        path = release_dir / relative_name
        if not path.is_file():
            failures.append(f"missing checksummed path: {path}")
            continue
        checked += 1
        observed = sha256(path)
        if observed != expected:
            failures.append(f"checksum mismatch: {path}: {observed} != {expected}")
    return {
        "pass": not failures,
        "checked_file_count": checked,
        "failure_count": len(failures),
        "failures": failures,
    }


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def workspace_inventory() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    handoff_root = DEFAULT_OUTPUT.parent.resolve()
    for root_name in WORKSPACE_ROOTS:
        root = HEIQ_ROOT / root_name
        extension_counts: Counter[str] = Counter()
        total_bytes = 0
        files = 0
        for path in root.rglob("*"):
            if not path.is_file() or any(part in EXCLUDED_PARTS for part in path.parts):
                continue
            if path.resolve().is_relative_to(handoff_root):
                continue
            files += 1
            total_bytes += path.stat().st_size
            extension_counts[path.suffix.lower() or "[none]"] += 1
        rows.append(
            {
                "workspace_root": str(root),
                "file_count": files,
                "total_bytes": total_bytes,
                "python_files": extension_counts[".py"],
                "csv_files": extension_counts[".csv"],
                "json_files": extension_counts[".json"],
                "markdown_files": extension_counts[".md"],
                "latex_files": extension_counts[".tex"],
                "pdf_files": extension_counts[".pdf"],
                "zip_files": extension_counts[".zip"],
            }
        )
    root_files = [path for path in HEIQ_ROOT.iterdir() if path.is_file()]
    root_extension_counts = Counter(path.suffix.lower() or "[none]" for path in root_files)
    rows.append(
        {
            "workspace_root": f"{HEIQ_ROOT} [top-level files]",
            "file_count": len(root_files),
            "total_bytes": sum(path.stat().st_size for path in root_files),
            "python_files": root_extension_counts[".py"],
            "csv_files": root_extension_counts[".csv"],
            "json_files": root_extension_counts[".json"],
            "markdown_files": root_extension_counts[".md"],
            "latex_files": root_extension_counts[".tex"],
            "pdf_files": root_extension_counts[".pdf"],
            "zip_files": root_extension_counts[".zip"],
        }
    )
    return rows


def validate_local_evidence() -> dict[str, Any]:
    failures: list[str] = []
    source_ids = [record["source_id"] for record in SOURCE_RECORDS]
    if len(source_ids) != len(set(source_ids)):
        failures.append("duplicate source IDs in SOURCE_RECORDS")
    for record in SOURCE_RECORDS:
        path = HEIQ_ROOT / record["path"]
        if not path.is_file():
            failures.append(f"missing source: {path}")

    try:
        release = current_release_status()
        expected_manifest_hashes = {
            "v8_manifest_sha256": "51f8ba4742af613a7b24d4d94062d4ad4b6a5440ed83149015c07afb9cf234fd",
            "v8_1_manifest_sha256": "6b83c446fc44f109790a043063d39012df54eb7c3d64c50e53de9c4552ca76a1",
        }
        for key, expected in expected_manifest_hashes.items():
            if release.get(key) != expected:
                failures.append(f"controlled release {key} changed: {release.get(key)} != {expected}")
        if release.get("v8_release_id") != "XMEMBRANE-2026-08-31-V8":
            failures.append(f"unexpected V8 release ID: {release.get('v8_release_id')}")
        if release.get("v8_release_class") != "hash_frozen_controlled_deliverable":
            failures.append(f"unexpected V8 release class: {release.get('v8_release_class')}")
        if release.get("v8_1_state") != "controlled_release":
            failures.append(f"V8.1 is not a verified controlled release: {release.get('v8_1_state')}")
        if not release["v8_checksum_verification"]["pass"]:
            failures.extend(release["v8_checksum_verification"]["failures"])
        if not release["v8_1_checksum_verification"]["pass"]:
            failures.extend(release["v8_1_checksum_verification"]["failures"])
    except (FileNotFoundError, KeyError, json.JSONDecodeError) as exc:
        failures.append(f"controlled release validation failed: {exc}")

    coupon_manifest_path = HEIQ_ROOT / "XMembrane_Trond_Study/reports/eo_vapor_boundary_analysis_v2_en/source_manifest.json"
    if coupon_manifest_path.is_file():
        coupon_manifest = json.loads(coupon_manifest_path.read_text(encoding="utf-8"))
        if coupon_manifest.get("translation_only_no_scientific_delta") is not True:
            failures.append("canonical English coupon report is not bound as a translation-only scientific equivalent")
        claim_boundary = coupon_manifest.get("claim_boundary", {})
        if claim_boundary.get("fixture_dimensions_are_starting_values") is not True:
            failures.append("coupon fixture dimensions lost their starting-value claim boundary")

    sizing_audit_path = HEIQ_ROOT / "XMembrane_Trond_Study/outputs/eo_vapor_cell_sizing_v1/audit.json"
    if sizing_audit_path.is_file():
        sizing_audit = json.loads(sizing_audit_path.read_text(encoding="utf-8"))
        failed_sizing_checks = [
            key for key, value in sizing_audit.get("checks", {}).items() if value is not True
        ]
        if sizing_audit.get("all_pass") is not True:
            failed_sizing_checks.append("all_pass")
        if failed_sizing_checks:
            failures.append(f"coupon sizing audit has failed checks: {failed_sizing_checks}")

    direct_gradient_path = HEIQ_ROOT / "XMembrane_Trond_Study/outputs/direct_erv_gradient_closure_v1/case_summary.csv"
    if direct_gradient_path.is_file():
        with direct_gradient_path.open(encoding="utf-8-sig", newline="") as handle:
            direct_cases = {row["case_label"]: row for row in csv.DictReader(handle)}
        direct_o30 = direct_cases.get("direct_erv_o30", {})
        direct_expected = {
            "water_target_kg_h": 4365.918299374118,
            "minimum_surface_activity_margin": -0.0079654586788779,
            "minimum_common_film_or_area_multiplier_for_zero_surface_margin": 1.1369893775398874,
            "minimum_common_film_or_area_multiplier_for_robust_margin": 1.73310598450244,
            "incremental_rectification_water_rate_kg_h": 0.0015178268745167896,
        }
        for key, expected in direct_expected.items():
            observed = float(direct_o30.get(key, "nan"))
            if abs(observed - expected) > max(1e-12, abs(expected) * 1e-10):
                failures.append(f"direct-ERV O30 {key} changed: {observed} != {expected}")

    active_decision_path = HEIQ_ROOT / "XMembrane_Trond_Study/deliverables/current/2026-08-31_v8_1/results/direct_active_erv/DECISION_SUMMARY.json"
    if active_decision_path.is_file():
        active_decision = json.loads(active_decision_path.read_text(encoding="utf-8"))
        expected_counts = {
            "case_count": 320,
            "transport_closed_count": 178,
            "engineering_screen_count": 50,
            "full_coupled_gate_count": 0,
        }
        for key, expected in expected_counts.items():
            if active_decision.get(key) != expected:
                failures.append(f"direct-active-ERV {key} changed: {active_decision.get(key)} != {expected}")

    common_voltage_path = HEIQ_ROOT / "XMembrane_Trond_Study/deliverables/current/2026-08-31_v8_1/results/common_voltage/README.md"
    if common_voltage_path.is_file():
        common_voltage_text = common_voltage_path.read_text(encoding="utf-8")
        for token in ("162.416", "-181.413", "0/49", "21 are physical no-solution", "28 remain numerical/local-bracket unresolved"):
            if token not in common_voltage_text:
                failures.append(f"post-ERV O30/common-voltage token missing: {token}")

    weather_path = HEIQ_ROOT / "XMembrane_Trond_Study/outputs/integrated_active_erv_weather_v1/active_erv_weather_energy.csv"
    if weather_path.is_file():
        with weather_path.open(encoding="utf-8-sig", newline="") as handle:
            weather_rows = {row["weather_state"]: row for row in csv.DictReader(handle)}
        weather_expected = {
            "O80": (0.25, 107.85631599323443, "True", "True"),
            "O50": (0.14905745506286622, 93.2925274081273, "True", "True"),
            "O30": (0.041546621322631844, 88.23534634720366, "False", "False"),
        }
        if set(weather_rows) != set(weather_expected):
            failures.append(f"unexpected direct-ERV weather axis: {sorted(weather_rows)}")
        for state, (voltage, total_kw, stack_feasible, engineering_pass) in weather_expected.items():
            row = weather_rows.get(state, {})
            if abs(float(row.get("terminal_voltage_v", "nan")) - voltage) > 1e-10:
                failures.append(f"direct-ERV weather {state} voltage changed")
            if abs(float(row.get("active_erv_plus_ac_total_power_kw", "nan")) - total_kw) > 1e-8:
                failures.append(f"direct-ERV weather {state} total power changed")
            if row.get("stack_feasible") != stack_feasible or row.get("engineering_screen_pass") != engineering_pass:
                failures.append(f"direct-ERV weather {state} engineering status changed")
            if row.get("full_system_claim_allowed") != "False":
                failures.append(f"direct-ERV weather {state} unexpectedly permits a full-system claim")

    id_collections = {
        "named material": [row["candidate_id"] for row in NAMED_MATERIALS],
        "literature lead": [row["lead_id"] for row in LITERATURE_LEADS],
        "availability search": [row["search_id"] for row in AVAILABILITY_SHEET],
        "development route": [row["route_id"] for row in DEVELOPMENT_ROUTES],
        "synthetic target": [row["target_id"] for row in SYNTHETIC_TARGETS],
        "constraint": [row["constraint_id"] for row in SUPERSEDED_CONSTRAINTS],
        "conflict": [row["conflict_id"] for row in MODEL_CONFLICTS],
    }
    for label, values in id_collections.items():
        if len(values) != len(set(values)):
            failures.append(f"duplicate {label} IDs")

    valid_source_ids = set(source_ids)
    evidence_groups: tuple[Iterable[dict[str, Any]], ...] = (
        NAMED_MATERIALS,
        LITERATURE_LEADS,
        AVAILABILITY_SHEET,
        DEVELOPMENT_ROUTES,
        SYNTHETIC_TARGETS,
        SUPERSEDED_CONSTRAINTS,
        HISTORICAL_SCREEN_MILESTONES,
        ALIAS_REGISTER,
    )
    for group in evidence_groups:
        for row in group:
            unknown = set(str(row.get("sources", "")).split(";")) - valid_source_ids
            unknown.discard("")
            if unknown:
                failures.append(f"unknown source IDs {sorted(unknown)} in {row}")

    mat_path = HEIQ_ROOT / "XMembrane_Trond_Study/outputs/integrated_evidence_v1/material_data_requirements.csv"
    if mat_path.is_file():
        with mat_path.open(encoding="utf-8-sig", newline="") as handle:
            observed = {row["requirement_id"] for row in csv.DictReader(handle)}
        expected = {req_id for req_id, _ in MAT_REQUIREMENTS}
        if observed != expected:
            failures.append(f"MAT requirement IDs differ: observed={sorted(observed)} expected={sorted(expected)}")

    v12_sources = HEIQ_ROOT / "HeiQ_V2/outputs/wp1_literature_ion_uncertainty_v12/literature_sources.csv"
    if v12_sources.is_file():
        with v12_sources.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        source_ids = {row["source_id"] for row in rows}
        if source_ids != {"S1", "S2", "S3", "S4", "S5", "S6"}:
            failures.append(f"Unexpected V12 literature source IDs: {sorted(source_ids)}")
        joined = " ".join(row.get("membrane", "") for row in rows)
        for name in ("Selemion CMVN", "CR61 AZL 386", "MF-4SC", "Nafion 117", "BPSH"):
            if name not in joined:
                failures.append(f"Named material missing from V12 source register: {name}")

    nafion_register = HEIQ_ROOT / "XMembrane_Trond_Study/outputs/material_parameter_windows_with_nafion_v1/nafion_reference_case_register.csv"
    if nafion_register.is_file():
        with nafion_register.open(encoding="utf-8-sig", newline="") as handle:
            grades = {row["grade_id"] for row in csv.DictReader(handle)}
        if grades != {"NR211", "NR212", "N115", "N117"}:
            failures.append(f"Unexpected current Nafion grade set: {sorted(grades)}")

    active_cfg = HEIQ_ROOT / "XMembrane_Trond_Study/config/direct_eo_erv_study_v1.json"
    if active_cfg.is_file():
        config = json.loads(active_cfg.read_text(encoding="utf-8"))
        terminal = config["materials"]["terminal1_anchor"]
        checks = {
            "water_drag": 100.06078708377692,
            "water_diffusivity_m2_s": 1.597880133581376e-14,
            "conductivity_s_m": 23.171886845550485,
            "dry_thickness_um": 36.91369958200169,
        }
        for key, expected in checks.items():
            if abs(float(terminal[key]) - expected) > max(1e-15, abs(expected) * 1e-12):
                failures.append(f"terminal1_anchor {key} changed: {terminal[key]} != {expected}")

    high_tw = HEIQ_ROOT / "HeiQ_V2/outputs/wp1_eo_material_scale_v4/eo_v4_high_transport_number_sweep.csv"
    if high_tw.is_file():
        with high_tw.open(encoding="utf-8-sig", newline="") as handle:
            transport_numbers = [float(row["transport_number"]) for row in csv.DictReader(handle)]
        if max(transport_numbers) != 150.0:
            failures.append(f"historical high-transport-number maximum changed: {max(transport_numbers)}")

    v8_grid = HEIQ_ROOT / "HeiQ_V2/outputs/axial_independent_material_sweep_v8/coarse/material_grid_used.csv"
    if v8_grid.is_file():
        with v8_grid.open(encoding="utf-8-sig", newline="") as handle:
            v8_count = sum(1 for _ in csv.DictReader(handle))
        if v8_count != 2304:
            failures.append(f"historical V8 grid row count changed: {v8_count}")

    download_manifest = HEIQ_ROOT / "XMembrane_Trond_Study/reports/heiq_eo_complete_result_atlas_v7/data/downloads_pdf_manifest.csv"
    if download_manifest.is_file():
        download_stats = downloaded_document_summary()
        if download_stats != {"manifest_rows": 45, "unique_documents": 31, "duplicate_rows": 14}:
            failures.append(f"downloaded-document inventory changed: {download_stats}")

    v62 = HEIQ_ROOT / "HeiQ_V2/outputs/EO_v62_bottleneck_parametric/threshold_summary.csv"
    if v62.is_file():
        with v62.open(encoding="utf-8-sig", newline="") as handle:
            observed = {row["case"]: float(row["t_w_practical_break_even"]) for row in csv.DictReader(handle)}
        expected = {"O60": 18.426778242677827, "O50": 27.389121338912133, "O40": 35.853556485355654, "O30": 44.81589958158996}
        for case, expected_value in expected.items():
            if abs(observed.get(case, float("nan")) - expected_value) > 1e-10:
                failures.append(f"V62 {case} practical t_w changed: {observed.get(case)}")

    old_nafion = HEIQ_ROOT / "XMembrane_Trond_Study/heiq_pre_receiver_material_analyses/config/default.json"
    if old_nafion.is_file():
        old_config = json.loads(old_nafion.read_text(encoding="utf-8"))
        density = float(old_config["nafion"]["dry_polymer_density_kg_m3"])
        if density != 1980.0:
            failures.append(f"older Nafion density changed: {density}")
    new_nafion = HEIQ_ROOT / "HeiQ_V2/tools/HeiQ_membrane_sensitivity_nafion_v1/nafion_reference.py"
    if new_nafion.is_file():
        source_text = new_nafion.read_text(encoding="utf-8")
        for token in ("dry_density_kg_m3: float = 1970.0", "DEFAULT_DRAG_SCENARIOS", "Motupally-Becker-Weidner"):
            if token not in source_text:
                failures.append(f"newer Nafion reference token missing: {token}")

    return {"pass": not failures, "failure_count": len(failures), "failures": failures}


def source_inventory_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in SOURCE_RECORDS:
        path = HEIQ_ROOT / record["path"]
        rows.append(
            {
                **record,
                "absolute_path": str(path),
                "exists": path.is_file(),
                "bytes": path.stat().st_size if path.is_file() else "",
                "sha256": sha256(path) if path.is_file() else "",
            }
        )
    return rows


def named_material_rows() -> list[dict[str, Any]]:
    fields = (
        "candidate_id",
        "name",
        "identity_type",
        "family",
        "form",
        "role",
        "priority",
        "decision",
        "quantitative_local_evidence",
        "direct_eo_reading",
        "active_erv_reading",
        "same_sample_complete",
        "next_action",
        "sources",
    )
    rows: list[dict[str, Any]] = []
    for item in NAMED_MATERIALS:
        row = {key: item[key] for key in fields if key in item}
        row["same_sample_complete"] = all(
            status.startswith("same_sample_measured") for status in item["statuses"].values()
        )
        rows.append(row)
    return rows


def downloaded_document_summary() -> dict[str, int]:
    path = HEIQ_ROOT / "XMembrane_Trond_Study/reports/heiq_eo_complete_result_atlas_v7/data/downloads_pdf_manifest.csv"
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    unique = sum(str(row.get("unique_document", "")).strip().lower() == "true" for row in rows)
    return {"manifest_rows": len(rows), "unique_documents": unique, "duplicate_rows": len(rows) - unique}


def current_release_status() -> dict[str, Any]:
    v8_dir = HEIQ_ROOT / "XMembrane_Trond_Study/deliverables/current/2026-08-31_v8"
    v81_dir = HEIQ_ROOT / "XMembrane_Trond_Study/deliverables/current/2026-08-31_v8_1"
    v8_manifest_path = v8_dir / "MANIFEST.json"
    v81_manifest_path = v81_dir / "MANIFEST.json"
    v8_manifest = json.loads(v8_manifest_path.read_text(encoding="utf-8"))
    v81_manifest = json.loads(v81_manifest_path.read_text(encoding="utf-8"))
    v8_checksums = verify_sha256sums(v8_dir)
    v81_checksums = verify_sha256sums(v81_dir)
    v8_manifest_sha = sha256(v8_manifest_path)
    v81_manifest_sha = sha256(v81_manifest_path)
    parent = v81_manifest.get("parent_release", {})
    translation = v81_manifest.get("english_translation_verification", {})
    live_delivery = v81_manifest.get("live_final_delivery", {})
    v81_controlled = all(
        (
            v81_manifest.get("release_id") == "XMEMBRANE-2026-08-31-V8.1",
            v81_manifest.get("release_class") == "hash_frozen_controlled_deliverable",
            v81_manifest.get("release_scope") == "translation_and_English_delivery_only",
            v81_manifest.get("scientific_delta_from_parent") is False,
            parent.get("release_id") == "XMEMBRANE-2026-08-31-V8",
            parent.get("manifest_sha256") == v8_manifest_sha,
            translation.get("translation_only_no_scientific_delta") is True,
            live_delivery.get("full_live_tests_pass") is True,
            live_delivery.get("live_test_passed_count") == 300,
            v81_checksums["pass"],
        )
    )
    return {
        "latest_controlled_delivery": "deliverables/current/2026-08-31_v8_1",
        "governing_scientific_report": "reports/team_result_atlas_v8/HeiQ_XMembrane_Current_Result_and_Decision_Report_2026-08-31_v8.pdf",
        "supporting_model_closure": "reports/model_closure_2026-08-31/HeiQ_XMembrane_Model_Closure_and_Material_Handoff_2026-08-31.pdf",
        "canonical_coupon_report": "reports/eo_vapor_boundary_analysis_v2_en/HeiQ_EO_Vapour_Cell_Boundary_Conditions_and_Sizing_2026-08-31_v2.pdf",
        "v8_release_id": v8_manifest.get("release_id"),
        "v8_release_class": v8_manifest.get("release_class"),
        "v8_manifest_sha256": v8_manifest_sha,
        "v8_checksum_verification": v8_checksums,
        "v8_1_release_id": v81_manifest.get("release_id"),
        "v8_1_release_class": v81_manifest.get("release_class"),
        "v8_1_release_scope": v81_manifest.get("release_scope"),
        "v8_1_manifest_sha256": v81_manifest_sha,
        "v8_1_checksum_verification": v81_checksums,
        "v8_1_state": "controlled_release" if v81_controlled else "invalid_or_incomplete",
        "v8_1_scientific_delta_from_parent": v81_manifest.get("scientific_delta_from_parent"),
        "v8_1_parent_manifest_sha256": parent.get("manifest_sha256"),
        "v8_1_translation_only_no_scientific_delta": translation.get("translation_only_no_scientific_delta"),
        "v8_1_live_tests_pass": live_delivery.get("full_live_tests_pass"),
        "v8_1_live_test_passed_count": live_delivery.get("live_test_passed_count"),
        "v8_1_immutable_repository_archival_release": v81_manifest.get("immutable_repository_archival_release"),
        "v8_1_release_snapshot_ready": live_delivery.get("release_snapshot_ready"),
        "material_handoff_release_status": "internal_post_release_addendum_not_in_v8_1_allowlist",
        "first_system_relevant_coupon_target": "post-ERV O30 in the 25-cm2 controlled-flow fixture",
        "direct_active_erv_status": "open secondary architecture pending measured passive transfer and film behaviour",
    }


def qualification_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    descriptions = dict(MAT_REQUIREMENTS)
    for material in NAMED_MATERIALS:
        for requirement_id, status in material["statuses"].items():
            rows.append(
                {
                    "candidate_id": material["candidate_id"],
                    "candidate_name": material["name"],
                    "requirement_id": requirement_id,
                    "requirement": descriptions[requirement_id],
                    "evidence_status": status,
                    "complete_for_ranking": status.startswith("same_sample_measured"),
                    "sources": material["sources"],
                }
            )
    return rows


def gap_rows() -> list[dict[str, str]]:
    return [
        {
            "comparison_id": "SELEMION_LI_VS_DIRECT_1P8V",
            "candidate_or_route": "Selemion CMVN Li+ central drag",
            "candidate_value": "9.2+/-0.8 mol H2O/mol ion (liquid, 295 K)",
            "current_target": "direct-EO preferred discrete cores t_w=20 or 25-30",
            "numeric_gap": "2.17x to t_w=20 using central value; upper reported value only reaches 10.0",
            "interpretation": "Closest named local lead, but not a pass and not measured in the required vapour state",
            "sources": "HIST-02;CUR-02;CUR-03",
        },
        {
            "comparison_id": "SELEMION_LI_VS_ACTIVE_ERV",
            "candidate_or_route": "Selemion CMVN Li+ central drag",
            "candidate_value": "9.2 mol H2O/mol ion",
            "current_target": "terminal-1 t_w=100.0608",
            "numeric_gap": "10.88x",
            "interpretation": "Large drag gap even before conductivity, D, sorption and interface coupling are considered",
            "sources": "HIST-02;CUR-06",
        },
        {
            "comparison_id": "LI_PRIOR_HIGH_VS_ACTIVE_ERV",
            "candidate_or_route": "Li+ literature-prior high drag",
            "candidate_value": "15",
            "current_target": "terminal-1 t_w=100.0608",
            "numeric_gap": "6.67x",
            "interpretation": "Even the historical upper Li prior is far below the active-ERV inverse coordinate",
            "sources": "HIST-03;CUR-06",
        },
        {
            "comparison_id": "MF4SC_LI_SIGMA_VS_ACTIVE_ERV",
            "candidate_or_route": "MF-4SC Li+ fully hydrated conductivity",
            "candidate_value": "0.61 S/m",
            "current_target": "terminal-1 sigma_ref=23.1719 S/m at a_ref=0.8",
            "numeric_gap": "37.99x",
            "interpretation": "Conditions and definitions differ, so this is a warning-scale comparison, not a rejection ratio",
            "sources": "HIST-02;CUR-06",
        },
        {
            "comparison_id": "NAFION_DRAG_VS_ACTIVE_ERV",
            "candidate_or_route": "Nafion H-form declared drag envelope",
            "candidate_value": "0.3-2.5",
            "current_target": "terminal-1 t_w=100.0608",
            "numeric_gap": "40.0x even against the 2.5 upper reference",
            "interpretation": "Confirms Nafion is a reference/control rather than the target",
            "sources": "CUR-04;CUR-06",
        },
        {
            "comparison_id": "NAFION_D_VS_DIRECT",
            "candidate_or_route": "Nafion equal-lambda D/internal-V5 ratio",
            "candidate_value": "2.98-14.18",
            "current_target": "direct-EO marginal D/V5 support 0.001-0.6",
            "numeric_gap": "lowest Nafion ratio is 4.97x above the upper direct-EO support",
            "interpretation": "Cross-schema diagnostic only; reinforces that D cannot be assessed alone",
            "sources": "CUR-02;CUR-03;CUR-04",
        },
        {
            "comparison_id": "LI_V14_TO_V15_INTERFACE",
            "candidate_or_route": "Historical supported Li+ route",
            "candidate_value": "V14 median flux/SEC 2.35 kg/m2/h and 0.136 kWh/kg",
            "current_target": "same route with V15 two-interface vapour checkpoint",
            "numeric_gap": "V15 median flux 0.434 kg/m2/h and SEC 0.217 kWh/kg",
            "interpretation": "The interface/hydration model cuts median flux about 5.4x and raises SEC; prioritize film and same-sample vapour tests",
            "sources": "HIST-06;HIST-08",
        },
        {
            "comparison_id": "LI_V15_GRADIENT_DIRECTION",
            "candidate_or_route": "Historical Li+ two-interface route",
            "candidate_value": "65->80% RH: 0.434 kg/m2/h and 0.217 kWh/kg at 0.55 V",
            "current_target": "80->60% RH matched architecture comparison",
            "numeric_gap": "80->60% RH: 1.164 kg/m2/h and 0.142 kWh/kg at 0.60 V; about 2.68x flux",
            "interpretation": "Favourable passive direction materially helps, but does not remove the need to measure both interfaces and the same-sample bundle",
            "sources": "HIST-08;HIST-09B",
        },
        {
            "comparison_id": "POST_ERV_O30_D_SENSITIVITY",
            "candidate_or_route": "Terminal-1 post-ERV O30 one-factor D replay",
            "candidate_value": "D=1e-14 to 1e-9 m2/s at otherwise frozen synthetic properties",
            "current_target": "1228.27 kg/h post-ERV O30 duty on one common bus",
            "numeric_gap": "Known power rises 30.055 to 373.885 kW and the conditional window falls +162.416 to -181.413 kW",
            "interpretation": "All seven D coordinates have sampled 1.00-1.25-V solutions, but high D is strongly adverse; this is not a candidate curve or net-saving claim",
            "sources": "CUR-00;CUR-28",
        },
        {
            "comparison_id": "DIRECT_ERV_O30_FILM_SURFACE",
            "candidate_or_route": "Terminal-1 direct-ERV O30 diagnostic",
            "candidate_value": "4365.918 kg/h direct-ERV boundary; minimum surface margin -0.00797",
            "current_target": "non-negative surface direction and former +0.02 robustness margin",
            "numeric_gap": "1.137x common film capacity/diagnostic area restores zero; 1.733x restores +0.02",
            "interpretation": "Surface direction and area are diagnostics, not acceptance gates; keep this boundary separate from post-ERV O30",
            "sources": "CUR-18;CUR-19",
        },
        {
            "comparison_id": "DIRECT_ERV_SYMMETRIC_AC_NULL",
            "candidate_or_route": "Quasi-static constant-drag +J/0/-J direct-ERV replay",
            "candidate_value": "O30 incremental even transport 0.001518 kg/h; full duty 0 kg/h",
            "current_target": "useful charge-balanced mean EO transport",
            "numeric_gap": "O30 increment is 0.348 ppm of the +J rate",
            "interpretation": "The present model gives no useful symmetric-AC rectification; frequency, hysteresis and asymmetric-interface effects remain unmodelled hypotheses",
            "sources": "CUR-18;CUR-20",
        },
        {
            "comparison_id": "NAFION_NR211_ACTIVE_VS_PASSIVE",
            "candidate_or_route": "Matched Nafion NR211 active/passive mechanism control",
            "candidate_value": "Active transfer is 91.63% diffusive and EO uses 0.444 kW",
            "current_target": "demonstrable EO benefit over the exact passive control",
            "numeric_gap": "Passive needs 2.653% more area but 0.493 kW less electricity",
            "interpretation": "Nafion is a useful negative/mechanism control, not an EO performance candidate; its correlation also leaves the declared hydration domain locally",
            "sources": "CUR-31",
        },
        {
            "comparison_id": "DIRECT_ERV_FIXED_AREA_WEATHER_EXTENSION",
            "candidate_or_route": "Post-release Terminal-1 direct-active-ERV weather-axis replay",
            "candidate_value": "Fixed 34425.05 m2 inverse area; O80/O50/O30 terminal voltage 0.2500/0.1491/0.04155 V",
            "current_target": "20 C/50% RH supply at three different 32 C outdoor humidity states",
            "numeric_gap": "Conditional active totals 107.856/93.293/88.235 kW versus passive 543.741/398.470/303.929 kW",
            "interpretation": "O80/O50 pass the declared engineering screen, O30 fails stack/engineering and every full-system claim is false; this is not a fixed manufactured off-design stack or a same-duty saving comparison",
            "sources": "CUR-32;CUR-33;CUR-34",
        },
    ]


def write_outputs(output_dir: Path) -> dict[str, Any]:
    validation = validate_local_evidence()
    if not validation["pass"]:
        raise RuntimeError("Local evidence validation failed:\n" + "\n".join(validation["failures"]))

    output_dir.mkdir(parents=True, exist_ok=True)
    inventory = workspace_inventory()
    sources = source_inventory_rows()
    materials = named_material_rows()
    qualifications = qualification_rows()
    gaps = gap_rows()
    download_stats = downloaded_document_summary()
    release_status = current_release_status()

    write_csv(
        output_dir / "workspace_inventory_summary.csv",
        inventory,
        [
            "workspace_root",
            "file_count",
            "total_bytes",
            "python_files",
            "csv_files",
            "json_files",
            "markdown_files",
            "latex_files",
            "pdf_files",
            "zip_files",
        ],
    )
    write_csv(
        output_dir / "source_inventory.csv",
        sources,
        [
            "source_id",
            "path",
            "absolute_path",
            "role",
            "evidence_class",
            "use",
            "exists",
            "bytes",
            "sha256",
        ],
    )
    write_csv(
        output_dir / "named_material_register.csv",
        materials,
        [
            "candidate_id",
            "name",
            "identity_type",
            "family",
            "form",
            "role",
            "priority",
            "decision",
            "quantitative_local_evidence",
            "direct_eo_reading",
            "active_erv_reading",
            "same_sample_complete",
            "next_action",
            "sources",
        ],
    )
    write_csv(
        output_dir / "literature_lead_register.csv",
        LITERATURE_LEADS,
        [
            "lead_id",
            "name",
            "lead_type",
            "local_evidence",
            "limitation",
            "material_search_use",
            "priority",
            "sources",
        ],
    )
    write_csv(
        output_dir / "candidate_availability_sheet.csv",
        AVAILABILITY_SHEET,
        [
            "search_id",
            "candidate_or_route",
            "record_type",
            "priority",
            "target_form_or_construction",
            "proposed_role",
            "local_evidence_tier",
            "supplier",
            "procurement_identifier",
            "construction_and_support",
            "nominal_thickness_um",
            "required_physical_coupon_mm",
            "available_sheet_dimensions_mm",
            "usable_80x80_coupon_count",
            "minimum_order_quantity",
            "replicate_count_status",
            "availability_status",
            "lot_or_sample_id",
            "first_question",
            "decision_after_local_audit",
            "sources",
        ],
    )
    write_csv(
        output_dir / "qualification_matrix.csv",
        qualifications,
        [
            "candidate_id",
            "candidate_name",
            "requirement_id",
            "requirement",
            "evidence_status",
            "complete_for_ranking",
            "sources",
        ],
    )
    write_csv(
        output_dir / "development_route_register.csv",
        DEVELOPMENT_ROUTES,
        [
            "route_id",
            "route",
            "basis",
            "quantitative_anchor",
            "current_interpretation",
            "first_material",
            "priority",
            "sources",
        ],
    )
    write_csv(
        output_dir / "synthetic_target_register.csv",
        SYNTHETIC_TARGETS,
        [
            "target_id",
            "kind",
            "properties",
            "allowed_use",
            "forbidden_interpretation",
            "sources",
        ],
    )
    write_csv(
        output_dir / "gap_to_current_targets.csv",
        gaps,
        [
            "comparison_id",
            "candidate_or_route",
            "candidate_value",
            "current_target",
            "numeric_gap",
            "interpretation",
            "sources",
        ],
    )
    write_csv(
        output_dir / "superseded_constraint_register.csv",
        SUPERSEDED_CONSTRAINTS,
        [
            "constraint_id",
            "legacy_statement",
            "current_treatment",
            "reason",
            "sources",
        ],
    )
    write_csv(
        output_dir / "historical_screen_milestones.csv",
        HISTORICAL_SCREEN_MILESTONES,
        ["milestone", "retained_result", "current_use", "claim_boundary", "sources"],
    )
    write_csv(
        output_dir / "model_conflict_register.csv",
        MODEL_CONFLICTS,
        [
            "conflict_id",
            "subject",
            "source_a",
            "source_b",
            "status",
            "required_treatment",
            "notes",
        ],
    )
    write_csv(
        output_dir / "alias_register.csv",
        ALIAS_REGISTER,
        ["canonical_id", "alias", "record_type", "status", "treatment", "sources"],
    )

    summary = {
        "script_version": SCRIPT_VERSION,
        "heiq_root": str(HEIQ_ROOT),
        "output_dir": str(output_dir),
        "validation": validation,
        "workspace_root_count": len(WORKSPACE_ROOTS),
        "workspace_inventory_group_count": len(inventory),
        "workspace_top_level_file_count": sum(
            int(row["file_count"]) for row in inventory if "[top-level files]" in row["workspace_root"]
        ),
        "workspace_file_count": sum(int(row["file_count"]) for row in inventory),
        "workspace_pdf_count": sum(int(row["pdf_files"]) for row in inventory),
        "downloaded_pdf_manifest": download_stats,
        "current_release_status": release_status,
        "source_record_count": len(sources),
        "named_material_count": len(materials),
        "literature_lead_count": len(LITERATURE_LEADS),
        "availability_search_row_count": len(AVAILABILITY_SHEET),
        "named_materials_same_sample_complete": sum(
            str(row["same_sample_complete"]).lower() == "true" for row in materials
        ),
        "development_route_count": len(DEVELOPMENT_ROUTES),
        "synthetic_target_count": len(SYNTHETIC_TARGETS),
        "historical_milestone_count": len(HISTORICAL_SCREEN_MILESTONES),
        "model_conflict_count": len(MODEL_CONFLICTS),
        "qualification_row_count": len(qualifications),
        "decision": {
            "start_from_zero": False,
            "primary_real_material_evidence_anchor": "Selemion CMVN in Li+ form; test priority only, not performance ranking",
            "primary_development_route": "thin supported Li+-form cation-exchange membrane with measured two-sided vapour interfaces",
            "first_system_relevant_coupon_target": "post-ERV O30 in the 25-cm2 controlled-flow fixture",
            "direct_active_erv_status": "open secondary architecture pending measured passive transfer and film behaviour",
            "post_release_direct_active_weather_extension": "reviewed; O80/O50 engineering passes, O30 stack/engineering failure, all full-system claims false; not in V8.1 and not material evidence",
            "reference_controls": ["Nafion NR211", "Nafion NR212"],
            "exploratory_chemistry_leads": [
                "intrinsically microporous polyamine membranes",
                "BPSH/non-PFSA sulfonated aromatic ionomers",
                "graded/adsorbing composite architectures",
            ],
            "consolidated_material_search_input_ready": True,
            "availability_and_procurement_inquiry_ready": True,
            "procurement_shortlist_ready": False,
            "candidate_ranking_ready": False,
            "reason": "No named material has a complete MAT-01 to MAT-09 same-sample data bundle under the intended vapour conditions.",
        },
    }
    (output_dir / "handoff_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    manifest_rows = []
    for path in sorted(output_dir.iterdir()):
        if path.is_file() and path.name != "output_manifest.csv":
            manifest_rows.append(
                {
                    "file": path.name,
                    "bytes": path.stat().st_size,
                    "sha256": sha256(path),
                }
            )
    write_csv(output_dir / "output_manifest.csv", manifest_rows, ["file", "bytes", "sha256"])
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output directory (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Validate canonical local sources without writing outputs",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.check_only:
        result = validate_local_evidence()
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["pass"] else 1
    summary = write_outputs(args.output_dir.resolve())
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
