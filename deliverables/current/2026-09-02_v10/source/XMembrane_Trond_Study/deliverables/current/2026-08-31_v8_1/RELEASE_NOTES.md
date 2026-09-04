# Release notes — XMembrane 2026-08-31 V8.1 English reporting release

**Release ID:** `XMEMBRANE-2026-08-31-V8.1`  
**Release scope:** `translation_and_English_delivery_only`  
**Parent release:** `XMEMBRANE-2026-08-31-V8`  
**Parent MANIFEST SHA-256:**
`51f8ba4742af613a7b24d4d94062d4ad4b6a5440ed83149015c07afb9cf234fd`  
**Status rule:** scaffold unless `MANIFEST.json` and `SHA256SUMS` exist and
verify; hash-frozen controlled deliverable after a successful package run  
**Decision date:** 31 August 2026  
**Release class:** hash-frozen controlled deliverable; not an immutable
repository archival release

## Release documents

- `HeiQ_XMembrane_Current_Result_and_Decision_Report_2026-08-31_v8.pdf`
  — canonical English result and decision report.
- `HeiQ_EO_Vapour_Cell_Boundary_Conditions_and_Sizing_2026-08-31_v2.pdf`
  — canonical English EO vapour-cell boundary and sizing report.
- `HeiQ_XMembrane_Model_Closure_and_Material_Handoff_2026-08-31.pdf`
  — supporting model-phase closure and material-handoff record.

All packaged reports are in English. The packaging tool requires these exact
basenames and fails rather than substitute an older filename.

## Changes from V8

- Replace the packaged Norwegian EO vapour-cell report with its faithful
  English counterpart.
- Keep the V8 result-and-decision report as the governing canonical report and
  the model-closure report as supporting provenance.
- Preserve every scientific value, table, figure, audit, decision, limitation,
  and claim boundary from V8; there is no scientific delta.
- Bind V8.1 to the exact immutable V8 `MANIFEST.json` hash recorded above.
- Use new V8.1 archive names and a separate package directory. No V8 file is
  edited, removed, overwritten, or silently relabelled.
- Keep weekly and workshop reports as non-canonical chronology outside this
  controlled report set.

## Decision carried by this release

The V8 decision is inherited unchanged. The broad hypothetical model phase may
close only if the final checker passes.
The next phase is same-sample material measurement, controlled-flow coupon
testing, and explicit receiver/thermal/hardware ledger closure. Candidate
ranking, architecture selection, technology validation, and full-system energy
claims remain open until their empirical gates close.

## Claim language

Permitted wording is that the models identify conditional energy windows,
transport regimes, and measurable experiment-design regions under declared
boundaries. Do not state that a reported conditional difference has been saved,
that a membrane candidate has been validated, that full duty is impossible,
or that stress-scenario pass fractions are calibrated probabilities.

## Historical material

The complete V8 release, its Norwegian EO report, Result Atlas V7, weekly
reports, workshop packs, and earlier PDFs remain unchanged for chronology.
They are not copied into this English report set and must not override V8/V8.1
conclusions. The weekly report is already English but remains non-canonical.

## Repository-state advisory

The repository has substantial pre-existing and user-owned working-tree state.
This package does not claim that the repository is clean and does not perform
destructive cleanup or broad commits to make it appear clean. The packaging
manifest records the revision, `release_snapshot_ready=false`, and the final
checker's dirty-Git evidence as an explicit non-blocking advisory. Integrity of
the controlled deliverable is established by explicit allowlists, verified
source/report manifests, repeated source hashing during the copy, and final
`SHA256SUMS`. This package may therefore pass while the repository-wide
archival-snapshot gate remains open; it does not relabel that open gate as
closed.

## Release verification record

When packaging succeeds, `MANIFEST.json` records the immutable parent binding,
release scope, Git revision, live final-delivery result, source-to-destination
allowlist, file sizes, mtimes, and
SHA-256 hashes. `SHA256SUMS` covers the authored scaffold, every packaged file,
both uniquely named V8.1 ZIP archives, and the manifest. Until those files
exist and verify, this directory is not a release.
