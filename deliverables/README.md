# Controlled deliverables

`current/2026-09-02_v10/` is the governing hash-frozen English model-phase
closeout release. Verify it from that directory with:

```bash
sha256sum -c SHA256SUMS
```

The V10 release gate is `verification/V10_STATUS.json`. Rebuild it from the
curated source/report revision with `scripts/package_final_closeout_v10.py`;
the older August delivery checker is historical and is not the V10 authority.

The package is an immutable snapshot and therefore retains the source
filenames used when it was built. Current canonical source names are mapped in
`../docs/REPOSITORY_LAYOUT.md`; the frozen package itself must not be renamed or
edited. The earlier `2026-08-31_v8_1` release remains available as historical
provenance and is superseded for current decisions by V10.
