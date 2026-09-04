# Deliverable map

## Controlled release

`current/2026-09-02_v10/` is the governing hash-frozen English model-phase
closeout release. Read its [package guide](current/2026-09-02_v10/README.md),
then verify the complete directory from inside it with:

```bash
sha256sum --check SHA256SUMS
```

The release gate is `verification/V10_STATUS.json`. The package is immutable;
any payload change requires a new release version and new checksums. The V10
source revision is `805ae087a7f3e133444c93f9fbb72856863754bf`.

The older `current/2026-08-31_v8_1/` release and V8/V9 report material are
historical provenance.

## Post-V10 handoff supplement

`current/2026-09-03_handoff_v1/` is the sole current entry point for the
post-V10 presentation and selected vapour coupon-cell handoff material. Its
current technical deck is available as
`presentations/HeiQ_XMembrane_Technical_Model_Peer_Review_V10_2026-09-03.pptx`
and `.pdf`; the standalone explanation is
`presentations/HeiQ_XMembrane_Model_Explainer_V10_2026-09-03.html`. Build and
render prerequisites are recorded in `PRESENTATION_BUILD.md`.
These files are not members of the V10 package. Transfer the supplement with:

- an explicit allowlisted inventory and SHA-256 checksums;
- a short build note with exact Python, Node, font, and PDF-conversion
  dependencies;
- confirmation that all decision wording has been reviewed against the V10
  report;
- a statement that V10 remains the governing model-phase authority.

The previous V9 presentation set is retained under
`archive/2026-09-02_v9_presentations/`. The tracked coupon-cell calculation
basis is documented in [the handoff guide](../docs/HANDOFF.md). Generated slide
images and renderer scratch directories are build artifacts unless the
supplement inventory names them explicitly.

Python presentation dependencies are pinned by
`../requirements-docs-presentations.txt`; Node dependencies are locked by
`../package-lock.json`. Build the current figures and deck from the repository
root with `npm ci` followed by `npm run build:presentations`.
