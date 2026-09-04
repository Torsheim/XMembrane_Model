# EO vapour cell V2 — English boundary-condition and sizing report

This is a new, standalone English deliverable dated 31 August 2026. It is the
complete English counterpart to the canonical Norwegian V2 report and uses the
current canonical results from:

- `outputs/eo_vapor_boundary_analysis_v1/`
- `outputs/eo_vapor_cell_sizing_v1/`

No V1 report, Norwegian report, or shared output file is modified by this
deliverable.

## Primary files

- `HeiQ_EO_Vapour_Cell_Boundary_Conditions_and_Sizing_2026-08-31_v2.tex`
- `HeiQ_EO_Vapour_Cell_Boundary_Conditions_and_Sizing_2026-08-31_v2.pdf`
- `source_manifest.json` — SHA-256 freeze of the report, code,
  configurations, tables, and figures on which the report depends

## Canonical starting geometry

The report follows `outputs/eo_vapor_cell_sizing_v1/audit.json`, which has
`all_pass: true`:

- one maximum active aperture of 50 × 50 mm, 25 cm²;
- an 80 × 80 mm membrane coupon and 110 × 110 mm outer plate;
- a nominal symmetric 2 mm gap, with interchangeable 1/2/4 mm spacers;
- 6 actual L/min per side in nominal film-characterisation mode;
- an 8–10 mm insulating flow body and 12 mm metal load plate;
- at least 16 mm if the PEEK plate alone carries the load;
- measured internal dead volume below 1.3 mL per side.

These are engineering starting values, not released manufacturing dimensions.
Gross Faradaic transport is not net measured transport, and the plate loads
are sensitivity coordinates rather than predicted gasket pressures.

## Build

From the repository root:

```bash
latexmk -cd -pdf -interaction=nonstopmode -halt-on-error \
  reports/eo_vapor_boundary_analysis_v2_en/HeiQ_EO_Vapour_Cell_Boundary_Conditions_and_Sizing_2026-08-31_v2.tex
```

## Focused tests

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -s -p no:cacheprovider \
  tests/test_eo_vapor_boundary_analysis_v1.py \
  tests/test_eo_vapor_cell_sizing_v1.py
```

## Claim boundary

Stress quantiles and sampled pass fractions are conditional on the declared
intervals. They are not probabilities, confidence intervals, or expected
hardware yield. Final acceptance requires physical blank, mass-balance,
flatness, pressure, leakage, and film tests.
