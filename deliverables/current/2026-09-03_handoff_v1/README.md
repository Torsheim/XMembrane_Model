# XMembrane post-V10 handoff supplement v1

This directory is the sole current entry point for the post-V10 presentation
and selected integrated EO vapour coupon-cell handoff. It is supplemental to
the immutable controlled release `XMEMBRANE-2026-09-02-V10` and does not amend
its scientific conclusion:

> **The model phase is complete. The technology is not validated.**

The governing document remains
[`../2026-09-02_v10/reports/HeiQ_XMembrane_Final_Project_Closeout_2026-09-02_v10.pdf`](../2026-09-02_v10/reports/HeiQ_XMembrane_Final_Project_Closeout_2026-09-02_v10.pdf).

## Recommended reading order

1. Read the controlled V10 closeout report above.
2. Open
   `presentations/HeiQ_XMembrane_Model_Explainer_V10_2026-09-03.html` for a
   concise interactive explanation of the decision and model boundary.
3. Use
   `presentations/HeiQ_XMembrane_Technical_Model_Peer_Review_V10_2026-09-03.pdf`
   for technical review; the matching PPTX is editable.
4. Read `test_cell/README.md`, then the versioned Word handoff document and
   dimensioned drawing before using the coupon-cell concept.
5. Check `test_cell/calculations/audit.json` and
   `integrated_sealed_cell_engineering_register.csv` before any detailed
   design work.

## Scientific boundary carried into the supplement

- Direct EO inside the ERV is the selected modelling architecture. Post-ERV
  O30 work is retained as a coupon-test boundary and historical comparator.
- The steady axial model prescribes terminal voltage and solves the local
  current density as humidity and membrane properties vary along the core.
- The primary blocking-electrode O30 replay preserves the original 0.025 V
  terminal limit. It retains 16.2% of the former counterfactual steady EO
  displacement after one hour and 0.68% over 24 hours.
- The former 98.5% and 4.6% figures belong only to a separate optimistic 1.8 V
  current-commanded upper bound; they are not a same-voltage replay.
- Purely blocking electrodes provide finite startup displacement. An ideal
  symmetric charge-balanced cycle gives zero net EO water transport.
- `t_w = 50` with `D_ref = 1e-10 m2/s` is a synthetic sensitivity, not a
  material identification. Four of eight cases close the prescribed transport
  screen; zero of eight close the full coupled system by model contract.
- No sustained-duty, full-system-saving, commercial-material, safety,
  lifetime, or product-performance claim is enabled by this supplement.

## Contents

- `presentations/`: current V10-aligned HTML, PPTX, and PDF.
- `figures/model_review/`: eight technical review figures in total (one system
  setup plus seven model-review figures), matching SVG sources, and a contact
  sheet.
- `PRESENTATION_BUILD.md`: locked dependencies, exact build commands, font and
  PDF-conversion requirements, and validation record.
- `test_cell/`: current test-cell guide, Word handoff document, dimensioned
  source/render, illustrative exterior render, calculation registers, audit,
  and nested source manifest.
- `MANIFEST.json`: exact allowlisted payload inventory, roles, sizes, hashes,
  governing V10 revision, and build-source bindings.
- `SHA256SUMS`: independent checksums for every transferred payload file and
  `MANIFEST.json`.

Individual PNGs under `presentations/rendered/` are local visual-review
scratch. They are intentionally excluded from the payload and must not be
substituted for the PDF or PPTX.

## Test-cell status

The selected concept uses two equal `500.0 +/- 5.0 mL` net-free-gas chambers,
a `50 x 50 mm` active membrane region, and 1, 2, and 4 mm local gap inserts
with 2 mm nominal. The generated calculation audit passes 13 of 13 numerical
and contract checks.

This is still an engineering concept, not a fabrication release. Thirteen
mechanical, interface, mixing, calibration, tolerance, sealing, pressure, and
mounting evidence gates remain open. Unresolved physical dimensions are null
in the governing configuration and must not be inferred from the illustrative
exterior render.

## Build and integrity verification

Regenerate the presentation files using `PRESENTATION_BUILD.md`. Regenerate
the test-cell calculations and report using `test_cell/README.md`. Then write
or refresh the exact handoff controls from repository root:

```bash
python3 scripts/package_handoff_supplement_v1.py
```

Verify without changing files:

```bash
python3 scripts/package_handoff_supplement_v1.py --check-only
cd deliverables/current/2026-09-03_handoff_v1
sha256sum --check SHA256SUMS
```

The packager fails closed if the V10 release is not `PASS`, a payload file is
missing or unexpected, the test-cell copy is stale, file modes are not 0644,
PPTX/PDF page counts differ, or any required V10 interpretation term is absent
from the deck source, PPTX, PDF, or HTML.

`MANIFEST.json` and `SHA256SUMS` contain no build timestamp and are
byte-deterministic for identical allowlisted payload and build-input bytes.
The generated PPTX/PDF themselves may vary across office-suite or font
versions; the recorded hashes bind the reviewed bytes actually transferred.

## Historical presentations

The earlier coupled-model and peer-review decks and the old HTML explainer are
retained under `deliverables/archive/2026-09-02_v9_presentations/`. They are
explicitly Version 9 history and are superseded for current interpretation by
this supplement.
