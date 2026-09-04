# HeiQ XMembrane team result atlas v8

Current English team result and decision report dated 2026-08-31.

The report references canonical figures and machine-readable outputs in
`../../outputs/`; it does not copy or modify those assets.

Canonical basename:
`HeiQ_XMembrane_Current_Result_and_Decision_Report_2026-08-31_v8`.
The adjacent `source_manifest.json` binds the TeX, PDF, README, cited output
manifests/audits and every referenced figure by SHA-256.

## Build

From this directory:

    latexmk -pdf -interaction=nonstopmode -halt-on-error \
      HeiQ_XMembrane_Current_Result_and_Decision_Report_2026-08-31_v8.tex

Clean generated LaTeX intermediates, while retaining the PDF:

    latexmk -c \
      HeiQ_XMembrane_Current_Result_and_Decision_Report_2026-08-31_v8.tex

## Claim boundary

This is an internal model and experiment-planning synthesis. Numerical EO
system differences are conditional ledgers, not validated savings. Before
external release, freeze the reviewed repository state, rerun the final
delivery check and tests, rebuild the report, and record source/output hashes.
