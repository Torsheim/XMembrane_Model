# Integrated sealed EO vapour test cell

Status: authoritative engineering concept. Fabrication release is blocked by the open evidence gates below.

The current design is one integrated two-chamber cell. A membrane separates equal sealed gas chambers A and B. The governing target is **0.500 L net free-gas volume per assembled side**, with a **+/-5.0 mL calibration acceptance band**. The active membrane region is **50 x 50 mm (25 cm2)**, with interchangeable local gaps of **1, 2 and 4 mm** on both sides. The target is configuration-controlled; physical calibration remains open until it is measured on the assembled cell.

The sole current handoff note and Word report are:

- `reports/test_cell_handoff_supplement_2026-09-03/README.md`
- `reports/test_cell_handoff_supplement_2026-09-03/HeiQ_Integrated_EO_Vapour_Test_Cell_Handoff_2026-09-03_v1.docx`

## Volume sizing basis

The design point is 32 °C, 101325 Pa and 50% initial RH. The declared target water flux is 208 g m-2 h-1. Across 0.0025 m2 this gives `0.520 g/h = 0.144444 mg/s`.

The 0.1 Hz switching basis gives a 5.0 s polarity segment and 0.722222 mg transferred during one segment. For an allowable change of 5.0 RH percentage points in either chamber, the ideal-gas inventory requirement is:

`V_required = transferred mass / (saturated vapour density x allowed RH fraction)`.

At 32 °C the calculation gives **427.6 mL per side**. The selected **500.0 mL per side** gives a volume ratio of **1.169** and a predicted one-segment change of **4.276 RH percentage points per chamber**. The chamber-to-chamber RH difference is **8.551 percentage points** at the first switching point.

## Volume definitions

| Quantity per side | 1 mm gap | 2 mm gap | 4 mm gap | Release status |
|---|---:|---:|---:|---|
| Local 50 x 50 mm membrane-region volume | 2.5 mL | 5.0 mL | 10.0 mL | Defined |
| Bulk free-gas volume | 497.5 mL | 495.0 mL | 490.0 mL | Derived |
| Net free-gas volume target | 500.0 mL | 500.0 mL | 500.0 mL | Defined; calibration open |
| Gross empty-cavity volume | Open | Open | Open | Engineering register |

The local membrane-region volume is a subset of the net-volume target. Bulk plus local equals 500.0 mL. Gross empty-cavity volume is set by `gross empty-cavity volume = calibrated net free-gas volume + installed component displacement` after the component displacement is measured.

## Transient calculation

The calculation treats each chamber as rigid, isothermal and well mixed over the 20 s ABBA sequence `+1, -1, -1, +1`. Positive polarity transfers water from A to B. At each time:

- `m_A = m_initial - transferred mass`
- `m_B = m_initial + transferred mass`
- `RH = water mass / (saturated vapour density x net volume)`

The analytic sequence conserves `m_A + m_B`, produces equal and opposite chamber inventory changes, and returns both chambers to 50.000% RH at 20 s. The gas-only pressure diagnostic reaches **406.9 Pa differential** at a 5 s extremum; the pressure-management design and verification test are recorded in the engineering register.

## Engineering register

`fabrication_release.ready` is `false`. Fabrication release requires closure evidence for:

1. gross empty-cavity volume and depth;
2. installed displacement from fans, probes, baffles and ports;
3. end-wall and central-divider material, thickness and structural response;
4. fluidic-port and electrical-feedthrough interfaces, seals and leak test;
5. internal-fan selection, envelope, mounting, heat load and displacement;
6. baffle geometry and mounting;
7. differential-pressure management across the switching sequence;
8. external fixture mounting, fastener pattern and preload;
9. seal geometry and compression;
10. drawing datums and dimensional tolerances;
11. loaded flatness and 1, 2 and 4 mm gap uniformity;
12. internal mixing time; and
13. traceable 500.0 +/- 5.0 mL net-volume calibration on each assembled side.

All unresolved physical dimensions are `null` in the governing configuration. They must not be inferred from the concept rendering. The superseded 2026-09-02 report and older figure variants are retained only as design history under `reports/test_cell_dimensioning_basis_2026-09-02/`.

## Reproduction

```bash
python3 scripts/design_eo_vapor_test_cell.py --output-dir reports/test_cell_handoff_supplement_2026-09-03/calculations
pytest -q tests/test_eo_vapor_test_cell_design.py
python3 scripts/build_test_cell_dimensioning_word_report.py
```

The calculation outputs include the volume basis, a 5 s-per-segment ABBA
transient sampled every 0.1 s, engineering register, audit and hash-bound source
manifest.
