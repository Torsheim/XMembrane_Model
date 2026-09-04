# HeiQ XMembrane — controlled project closeout, Version 10

This is the controlled closeout package for the completed model phase. The
governing document is
`reports/HeiQ_XMembrane_Final_Project_Closeout_2026-09-02_v10.pdf`.

The package closes the modelling work; it does not validate an existing
membrane, electrode mechanism, module, or net system-energy claim. In
particular, the `t_w=50`, `D=10^-10 m2/s` study is a synthetic conditional
sensitivity case. The capacitive-electrode study shows that blocking
electrodes provide transient rather than sustained DC transport, while a
symmetric blocking-electrode cycle gives zero net electro-osmotic transport.

## Contents

- `reports/`: the authoritative V10 closeout report and its readable Markdown
  source/manifest.
- `evidence/`: the key capacitive-electrode note and concise summaries/audits
  for the final synthetic membrane study.
- `results/`: an expanded exact allowlist formed from every V10-report and
  nested scientific-manifest binding, plus the two frozen active-ERV inputs
  and the recent membrane humidity/current plots and generator inputs.
- `source/`: an expanded Git-revision snapshot of the complete tracked
  repository, including `src/`, `pyproject.toml`, the reviewed legacy model,
  configurations, scripts, tests, data, and report source.
- `archives/`: deterministic source and result ZIP payloads. The package as a
  whole is intentionally time-, host-, environment-, and test-run-specific.
- `environment/`: Python, operating-system, Git, package, and source/result
  inventory captured at packaging time.
- `verification/`: V10-specific audit, manifest, archive, PDF, and full-test
  checks.
- `MANIFEST.json` and `SHA256SUMS`: the package inventory and final checksums.

## Integrity check

From this directory, verify every packaged file with:

```bash
sha256sum --check SHA256SUMS
```

The source and result ZIPs are opened, member-checked, and SHA-256 checked by
the packager. It then overlays both ZIPs into a fresh temporary
`XMembrane_Trond_Study/` tree, re-verifies the V10 report manifest and both
nested scientific manifests there, and runs the governing full pytest suite
from that reconstructed tree. `MANIFEST.json` records the source revision and
the Git revision at package execution. The later commit/tag containing the
generated release cannot be self-recorded inside the immutable package;
record that revision in the annotated release tag.

Exact reconstructed-tree test counts and every skip reason are recorded in
`verification/pytest_result.json` and `verification/pytest_output.txt`, and
are repeated in `verification/V10_STATUS.json`. They need not equal the live
workspace baseline because deliberately excluded historical generated outputs
and external sibling-repository evidence cause their own tests to skip. A
reconstructed-tree PASS means no test failed and all governing V10 evidence
was present; it does not claim that excluded historical evidence was rerun.

## Reproduction

Extract both archives into the same empty parent directory. They share the
root `XMembrane_Trond_Study/`. Create a Python 3.10+ environment, install the
project and development dependencies, then run the tests:

```bash
python3 -m pip install -e '.[dev]'
python3 -m pytest -q
```

`environment/python_packages.txt` is a diagnostic inventory of distributions
visible on the closeout host, not a lockfile or guarantee of a clean solver
environment. `pyproject.toml` remains the declared dependency specification.
Some historical workflows retain explicit sibling-repository assumptions;
the governing V10 studies and their reviewed legacy implementation are
included locally in this snapshot.

Historical V8 and V8.1 directories are immutable predecessors and are not
modified by the V10 packager.
