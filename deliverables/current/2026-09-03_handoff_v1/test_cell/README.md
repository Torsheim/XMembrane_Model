# Test-cell handoff supplement

This is the sole current test-cell artifact directory. It contains the editable
dimensioned figure, generated calculation evidence and the versioned Word
handoff report for the selected integrated sealed EO vapour-cell concept. It is
supplemental to the V10 model closeout and does not alter the V10 conclusion.

In a full repository checkout, the governing numerical inputs are
`config/eo_vapor_test_cell_design.json`. The current report is
`HeiQ_Integrated_EO_Vapour_Test_Cell_Handoff_2026-09-03_v1.docx`, and the current
dimensioned source is
`figures/eo_vapour_integrated_two_chamber_dimensioned_views.tex`. The earlier
material is retained in the full repository under
`reports/test_cell_dimensioning_basis_2026-09-02/` as historical design record;
it is deliberately excluded from this current supplement.

The selected design target is two equal 500.0 +/- 5.0 mL net-free-gas chambers
separated by a 50 x 50 mm active membrane region. Local gap inserts are 1, 2 and
4 mm, with 2 mm nominal. This is an engineering concept. Fabrication release is
blocked until every required item in the generated engineering register is
closed with cited evidence.

## Current artifacts

- `HeiQ_Integrated_EO_Vapour_Test_Cell_Handoff_2026-09-03_v1.docx`
- `figures/eo_vapour_integrated_two_chamber_dimensioned_views.tex`
- `figures/eo_vapour_integrated_two_chamber_dimensioned_views.pdf`
- `figures/eo_vapour_integrated_two_chamber_dimensioned_views.png`
- `figures/eo_vapour_integrated_two_chamber_exterior_render.png` (illustrative)
- `calculations/` (tables, transient plot, audit and source manifest)

Regenerate the calculations from repository root with:

```bash
python3 -B scripts/design_eo_vapor_test_cell.py \
  --output-dir reports/test_cell_handoff_supplement_2026-09-03/calculations
python3 -m pytest -q tests/test_eo_vapor_test_cell_design.py
python3 -B scripts/build_test_cell_dimensioning_word_report.py
```
