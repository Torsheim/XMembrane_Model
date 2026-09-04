# XMembrane English release scaffold — 2026-08-31 V8.1

> **State is determined by verification files, not this prose.** Before a
> successful package run, this directory is only a release scaffold. It is a
> controlled deliverable only when `MANIFEST.json` and `SHA256SUMS` exist and
> verify, all three packaged reports and their source manifests pass, the live
> final-delivery check passes, and `package_release.py` completes without an
> error. This wording remains valid before and after packaging.

## Canonical scope

The intended release has two current, team-facing documents:

1. `reports/team_result_atlas_v8/HeiQ_XMembrane_Current_Result_and_Decision_Report_2026-08-31_v8.pdf`
   is the canonical English result and decision report.
2. `reports/eo_vapor_boundary_analysis_v2_en/HeiQ_EO_Vapour_Cell_Boundary_Conditions_and_Sizing_2026-08-31_v2.pdf`
   is the canonical English EO vapour-cell boundary-condition and sizing
   report.

The model-closure report dated 31 August is included as supporting provenance.
It records the model-phase handoff and evidence contract, but the V8/V8.1 result and
decision report governs wherever wording or status differs. Reports dated 27
August or earlier, Result Atlas V7, the weekly notes, and workshop snapshots are
historical evidence only and are deliberately excluded from this current
package.

This is a **hash-frozen controlled V8.1 deliverable** with release scope
`translation_and_English_delivery_only`, not an immutable archival snapshot of
the whole repository. It is an additive derivative of the unchanged
`XMEMBRANE-2026-08-31-V8` parent. The parent binding is the exact SHA-256 of
`deliverables/current/2026-08-31_v8/MANIFEST.json`:
`51f8ba4742af613a7b24d4d94062d4ad4b6a5440ed83149015c07afb9cf234fd`.
The scientific result, decision hierarchy, and claim boundary are unchanged.

The repository contains substantial
pre-existing and user-owned working-tree changes. The packager records the Git
revision and dirty-state evidence as an advisory; it does not delete, reset,
commit, or otherwise alter unrelated work. It never writes into the V8 parent.

## Claim boundary

This is a modelling and experiment-design release, not material, module,
technology, or full-system validation. In particular:

- reported positive energy differences are conditional model windows, not
  measured or net system savings;
- receiver/sink work, EO heat rejection, pressure drop, leakage, electrodes,
  controls, durability, and other omitted loads must be closed before a net
  system claim;
- no material candidate is ranked without a complete same-sample property set;
- current density and membrane area are reported design coordinates, not
  exploratory acceptance limits;
- stress quantiles and sampled stress-point pass fractions are conditional on
  declared scenario ranges. They are not calibrated probabilities, confidence
  intervals, or predicted manufacturing yield;
- a gas-only closed cell is a transient inventory limit, not a fixed-boundary
  steady-state transport experiment;
- aperture comparisons identify area and edge contributions only when the
  declared multi-mask design, blanks, and replicates are used.

## Intended packaged layout

The packaging tool creates only explicitly allowlisted files:

```text
reports/
  current_result/
  eo_vapor_cell_en/
  model_closure/
source/
  parent_release/
  config/
  scripts/
  tests/
results/
  direct_active_erv/
  direct_erv_gradient/
  project_closure/
  common_voltage/
  fom/
  eo_vapor_boundary/
  eo_vapor_sizing/
verification/
  final_delivery_check/
archives/
  HeiQ_XMembrane_2026-08-31_v8_1_source.zip
  HeiQ_XMembrane_2026-08-31_v8_1_results.zip
MANIFEST.json
SHA256SUMS
```

LaTeX build debris, caches, temporary files, unselected dense registers, and
repository metadata are excluded. The source ZIP contains report sources,
READMEs, manifests, selected configs/scripts, and this release scaffold. The
results ZIP contains final PDFs, selected audited summaries, the live delivery
verification, and the release notes.

## Reproduction order

Run from `/home/torsheim/HeiQ/XMembrane_Trond_Study`. Do not run steps in
parallel when a later result consumes an earlier manifest.

```bash
python3 -B scripts/run_direct_active_eo_erv_study_v1.py --mode study --overwrite
python3 -B scripts/run_direct_active_eo_erv_study_v1.py --mode sensitivity --overwrite
python3 -B scripts/run_direct_erv_gradient_closure_v1.py --overwrite

python3 -B scripts/run_workshop_common_voltage_diffusivity_v1.py --overwrite
python3 scripts/calculate_fom_assessment_v1.py --overwrite

python3 scripts/analyze_eo_vapor_boundaries_v1.py
python3 scripts/size_eo_vapor_cell_v1.py

python3 -B scripts/run_project_closure_check_v1.py \
  --output-dir outputs/project_closure_check_v1 --overwrite
```

Rebuild and refresh the source manifest for each final report only after its
inputs are stable:

```bash
latexmk -cd -pdf -interaction=nonstopmode -halt-on-error \
  reports/model_closure_2026-08-31/HeiQ_XMembrane_Model_Closure_and_Material_Handoff_2026-08-31.tex

latexmk -cd -pdf -interaction=nonstopmode -halt-on-error \
  reports/team_result_atlas_v8/HeiQ_XMembrane_Current_Result_and_Decision_Report_2026-08-31_v8.tex

latexmk -cd -pdf -interaction=nonstopmode -halt-on-error \
  reports/eo_vapor_boundary_analysis_v2_en/HeiQ_EO_Vapour_Cell_Boundary_Conditions_and_Sizing_2026-08-31_v2.tex
```

Each of those report directories must contain a `source_manifest.json` that
binds at least the final `.tex` and `.pdf`. The EO boundary audit must pass and
its selected evidence must be bound by the final English report manifest. The
manifest must also identify the Norwegian V2 source as its translation basis
and state that no scientific result changed.
The boundary-analysis and sizing output directories each require their own
passing `source_manifest.json`; the sizing output also requires its passing
`audit.json`. These audit/provenance records are explicitly packaged, hashed,
and verified.

## Required final checks

Before packaging:

1. Stop all generators and report builds. Inputs must not change during the
   check or copy.
2. Review `git status` and record the existing repository state. Do not clean,
   reset, delete, or commit unrelated/user-owned changes for this package. Git
   dirtiness is an explicit advisory, while allowlisted inputs are frozen by
   descriptor-backed identity and hash before hard validation. Audits,
   manifests, CSV structure and report freshness are then recomputed after the
   live checker and again at the final publication barrier.
3. Confirm the parent V8 manifest still has release ID
   `XMEMBRANE-2026-08-31-V8` and exact SHA-256
   `51f8ba4742af613a7b24d4d94062d4ad4b6a5440ed83149015c07afb9cf234fd`.
   Confirm that every report PDF is strictly newer than its TeX source, every
   declared hash matches, and no recorded project-local LaTeX dependency is
   newer than the PDF—even if its current bytes match a manifest hash.
4. Confirm the English EO report has the same scientific values, tables,
   figures, and claim boundary as Norwegian V2, and that no residual Norwegian
   headings or prose remain. Confirm `model_phase_delivery_ready=true`, an
   empty blocking-item list, all
   required-today gates at `PASS`, the common-voltage strict fail-closed checks,
   nested provenance, scientific audits, runtime, a complete live test run, and
   report hashes all pass. `release_snapshot_ready=false` is permitted and is
   retained as an advisory when it reflects the reviewed dirty working tree.
5. Run the packaging preflight. It writes only temporary verification data:

```bash
python3 deliverables/current/2026-08-31_v8_1/package_release.py --check-only
```

6. Run the isolated safety harness for malformed manifests, the immutable
   parent binding, scaffold and
   post-validation hard-gate mutation, strict freshness, unknown overwrite
   files, and transaction rollback:

```bash
python3 deliverables/current/2026-08-31_v8_1/package_release.py --self-test
```

7. After reviewing both checks, create the package exactly once:

```bash
python3 deliverables/current/2026-08-31_v8_1/package_release.py
```

`--overwrite` is available only for an intentional rebuild of this exact
release directory. It first verifies the complete existing generated set
against its old `MANIFEST.json` and `SHA256SUMS`, refuses unknown files or
directories, and promotes the replacement through backup and rollback. It
never replaces the authored `README.md`, `RELEASE_NOTES.md`, or packaging
script.

The tool runs the repository's final-delivery checker with live tests in a
temporary directory. It does not overwrite `outputs/final_delivery_check_v1/`.
A nonzero checker result, missing allowlist item, failed required gate, failed
test, failed audit, stale report, broken source hash, changed parent binding, or
changed input during copying aborts packaging. A dirty Git worktree is recorded
in `MANIFEST.json` but is not itself a packaging failure. The Norwegian V8
report and all V8 package files remain available only through the unchanged
parent; they are not copied into this English-only report set.
