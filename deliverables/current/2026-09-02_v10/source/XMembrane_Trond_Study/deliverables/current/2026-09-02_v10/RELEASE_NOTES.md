# Version 10 release notes

- Declares the broad model phase complete and fixes the final claim boundary:
  no existing membrane, sustained electrode mechanism, full module, or net
  system saving has been validated experimentally.
- Incorporates the 2026-09-01 capacitive-electrode transient study. Blocking
  electrodes cannot sustain the assumed DC transport indefinitely, and a
  symmetric blocking-electrode cycle has zero net electro-osmotic transport.
- Includes the combined synthetic sensitivity case `t_w=50` and
  `D=10^-10 m2/s`. Its conditional low-voltage result is retained as a model
  sensitivity, not a realistic-material or product-performance claim.
- Includes the recent local membrane humidity and through-thickness current
  profile plots as supplemental explanatory artifacts. Their source scenario
  remains identified separately from the V10 synthetic combined case.
- Replaces broad exploratory packaging with a fail-closed, allowlisted V10
  release process. Required evidence manifests and audit gates are verified
  before anything is published.
- Adds a complete tracked source snapshot at a declared Git revision, a
  diagnostic environment inventory, deterministic source/result ZIP payloads,
  ZIP member/hash verification, a package manifest, and `SHA256SUMS`. The
  overall package remains intentionally time-, host-, and test-run-specific.
- Derives the result overlay from exact V10 and nested-manifest bindings plus a
  narrow explicit allowlist; unrelated untracked and output-directory extras
  are not packaged.
- Reconstructs one fresh repository tree from the source and result ZIPs,
  re-verifies every governing report/nested-manifest binding there, and runs
  the complete governing pytest suite from that reconstructed tree. Command,
  counts, skip reasons, duration, output, and exit status are retained.
- Leaves the existing V8 and V8.1 releases unchanged.

The correct continuation, if HeiQ elects to pursue the technology, is an
experimental phase: demonstrate a sustained Faradaic, pseudocapacitive, or
rectifying mechanism; measure the complete same-sample material-property
vector; and close receiver, thermal, pressure-drop, auxiliary-energy,
manufacturability, lifetime, and cost ledgers.
