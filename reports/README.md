# Report map

## Governing model-phase report

The controlled English delivery is described by the
[V10 package guide](../deliverables/current/2026-09-02_v10/README.md). The
governing report is
`deliverables/current/2026-09-02_v10/reports/HeiQ_XMembrane_Final_Project_Closeout_2026-09-02_v10.pdf`,
and its release gate is
`deliverables/current/2026-09-02_v10/verification/V10_STATUS.json`.

V10 records the selected direct EO-in-ERV architecture, the
blocking-electrode transient limitation, the synthetic combined-sensitivity
case, and the final claim boundary. Use it whenever another report differs in
wording, result status, or recommended next phase.

## Supporting reports

- `model_closure_and_material_handoff_2026-08-31_rev2/` documents the
  model-property handoff that preceded V10.
- `material_search_handoff_2026-08-31/` consolidates the completed material
  search, evidence gaps, and qualification matrix.
- `test_cell_erv_scale_note_2026-09-01/` records the initial detectable-area
  and ERV-scale calculation.

These reports provide context and provenance; they do not amend V10.

## Post-V10 handoff supplement

`test_cell_handoff_supplement_2026-09-03/` is the sole current source for the
selected integrated sealed two-chamber vapour cell. It contains the governing
configuration-linked report, dimensioned source and generated numerical
evidence. `test_cell_dimensioning_basis_2026-09-02/` is superseded design
history only. The current handoff copies belong with the technical presentation under
`deliverables/current/2026-09-03_handoff_v1/`. That supplement has its own
inventory, checksums, source/build notes, and explicit V10 reference.

`test_cell_20mm_channel_study_2026-09-04/` is a later, post-V10 geometry
sensitivity. It interprets 20 mm as bulk cavity depth per side while retaining
the 50 x 50 mm active membrane window (25 cm²), the 80 x 80 mm coupon and the
2 mm nominal local membrane gap. It rejects a 100 x 100 x 20 mm bulk plenum for
the original 5 s / 500 mL basis, evaluates a 165 x 165 x 20 mm bulk-plenum
footprint behind a transition to the unchanged membrane window, and gives
calculated starting values plus strengths, weaknesses and residual physical
tests for all 13 fabrication gates. It does not modify the published
handoff-v1 package.

`test_cell_selected_design_basis_2026-09-04/` is the short English working
note for the selected net-transient configuration. It combines the integrated
setup visualization with the 25 cm² membrane, 500 mL-per-side calibrated
volume, 20 mm bulk depth and 12 s polarity-segment calculations. The note is
available as Markdown, DOCX and PDF and explicitly separates the illustrative
architecture from fabrication evidence.

## Historical reports

The V8/V8.1 and V9 reports, the August atlases, weekly reports, workshop packs,
and other dated report directories are research snapshots. Their controlled
records are retained in Git where explicitly selected and in the frozen V10
source archive; additional generated copies may remain locally ignored. Identify
all of them as historical when sharing them. They are not current decision
documents.

See [the handoff guide](../docs/HANDOFF.md) for reader paths, reproduction
classes, and transfer checks.
