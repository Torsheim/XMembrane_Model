# XMembrane model closure and material handoff — 31 August 2026

This directory contains the current authoritative interpretation of the broad
XMembrane model study. Use it for the phase decision and claim boundaries;
retain the older weekly reports and result atlas as the chronological record.

## Files

- `HeiQ_XMembrane_Model_Closure_and_Material_Handoff_2026-08-31.tex` — English
  LaTeX source.
- `HeiQ_XMembrane_Model_Closure_and_Material_Handoff_2026-08-31.pdf` — compiled
  team report.
- `source_manifest.json` — SHA-256 freeze of the report and its canonical
  numerical/material evidence, with final verification results.
- `receiver_thermal_ledger_template.csv` — fail-closed ledger for receiver,
  heat rejection, pressure drop, leakage and auxiliary energy in the next phase.
- `architecture_decision_register_template.csv` — evidence table for choosing
  post-ERV EO versus direct EO inside the ERV after measurements exist.

## Decision frozen in the report

- The broad steady-state model phase is complete.
- Start same-sample material data collection and the 25-cm² controlled-flow
  coupon campaign.
- A positive passive membrane-surface gradient is a regime diagnostic, not a
  thermodynamic feasibility gate for active EO.
- O30 direct-ERV has a finite 1.137-fold film/area crossover; the full-duty
  counter-current pinch has no positive surface-gradient crossover at finite
  flux.
- Charge-balanced symmetric current provides no useful mean EO transport in
  the current quasi-static constant-drag model.
- All 98 common-voltage cases carrying the legacy high-bracket flag were
  retried with a 100-fold higher numerical current bound. None recovered; the
  rows remain explicitly numerical/local unresolved, not physical no-go proof.
- Candidate ranking, architecture selection and net system claims remain open.

## Build

From this directory:

```bash
latexmk -pdf -interaction=nonstopmode -halt-on-error \
  HeiQ_XMembrane_Model_Closure_and_Material_Handoff_2026-08-31.tex
```

The source references the two canonical figures directly from
`../../outputs/direct_erv_gradient_closure_v1/figures/`; keep that output
directory beside the report tree when rebuilding.

## Primary evidence

- `../../outputs/fom_assessment_v1/`
- `../../outputs/workshop_common_voltage_diffusivity_v1/`
- `../../outputs/direct_active_eo_erv_study_v1/study/`
- `../../outputs/direct_erv_gradient_closure_v1/`
- `../../outputs/project_closure_check_v1/`
- `../../outputs/eo_vapor_cell_sizing_v1/`
- `../../outputs/eo_vapor_boundary_analysis_v1/`
- `../workshop_pack_2026-08-30/MATERIAL_SEARCH_BRIEF.md`

All positive energy differences are conditional model windows. They are not
measured or net system savings.

## Final delivery check

From the repository root, run:

```bash
python3 -B scripts/run_final_delivery_check_v1.py --run-tests --overwrite
```

This validates the report, nested source hashes, scientific audits, runtime,
workshop package and complete test suite. It separately reports the still-open
git release snapshot and next-phase empirical inputs.
