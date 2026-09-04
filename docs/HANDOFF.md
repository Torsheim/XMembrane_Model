# Handoff guide

This page is the starting point for a new owner of the XMembrane study. It
separates the controlled conclusion from editable source, generated evidence,
historical workflows, and post-closeout handoff material.

## Choose a path

| Reader | Start with | Purpose |
|---|---|---|
| Decision reader | `deliverables/current/2026-09-02_v10/reports/HeiQ_XMembrane_Final_Project_Closeout_2026-09-02_v10.pdf` | Read the governing model-phase conclusion and claim boundary. |
| Technical reviewer | [V10 package guide](../deliverables/current/2026-09-02_v10/README.md), then [model chain](MODEL_CHAIN.md) and [claim boundary](CLAIM_BOUNDARY.md) | Check package integrity and understand the numerical hierarchy. |
| Code maintainer | [Root README](../README.md), [package boundaries](PACKAGE_BOUNDARIES.md), and [source provenance](PROVENANCE.md) | Install the editable project, run tests, and locate retained compatibility code. |
| Reproducer | The two V10 archives plus `verification/V10_STATUS.json` | Reconstruct the exact source-and-result tree used by the V10 release gate. |
| Experimental successor | V10 report plus `deliverables/current/2026-09-03_handoff_v1/` | Continue with the selected vapour coupon cell, measured material properties, and electrode qualification. |

V10, release ID `XMEMBRANE-2026-09-02-V10`, is the governing model-phase
delivery. Its source revision is
`805ae087a7f3e133444c93f9fbb72856863754bf`. Earlier reports and generated
outputs remain provenance. Post-V10 material is supplemental and does not
change the V10 decision.

## What the handoff must contain

The complete controlled delivery is the whole directory
`deliverables/current/2026-09-02_v10/`, including both archives,
`MANIFEST.json`, `SHA256SUMS`, the report, evidence, environment records, and
verification records. A Git checkout containing only the two small V10 guide
files is not the controlled delivery.

Before transfer, the sender should also provide:

- the repository revision or bundle intended for continued development;
- the `2026-09-03_handoff_v1` supplement inventory, if included;
- named transfer authorization, the project owner, technical contact, and
  confidentiality classification consistent with [the repository notice](../NOTICE.md);
- any historical `HeiQ_V2` snapshot required for the workflows explicitly
  classified that way below.

The V10 package is immutable. A change to its contents requires a new release
version and a new integrity manifest.

Its byte content remains unchanged. For portable Git transfer, directories are
normalized to mode `0755`, ordinary files to `0644`, and only source-snapshot
files recorded by Git as mode `100755` retain an executable bit. Symlink modes
are platform metadata and are not treated as ordinary-file modes.

### Do not copy this checkout as a repository

This directory is a linked Git worktree. Its `.git` file points to an absolute
path in another local checkout, so copying or zipping the working directory is
not a valid Git handoff. Transfer source history by one of these routes after
all intended commits exist:

- clone the canonical GitHub repository and check out the recorded branch or
  tag;
- create and verify a Git bundle with `git bundle create <file>.bundle --all`
  and `git bundle verify <file>.bundle`;
- export the controlled V10 release when only the frozen result is required.

Uncommitted and ignored files are not included by a clone or Git bundle. Include
an ignored artifact only through an explicit, checksum-bound deliverable.

## Ownership, contact, and use status

| Field | Handoff status |
|---|---|
| Repository maintenance / code review | GitHub `@Torsheim`, enforced as the default reviewer in `.github/CODEOWNERS` |
| Technical project contact | Route initially through `@Torsheim`; no email address is asserted by this repository |
| Legal rights holder / transfer approver | **TBD before external transfer**; repository metadata does not establish the legal rights holder |
| Transfer authorization reference | **TBD before external transfer** |
| Confidentiality classification | **TBD before external transfer** |
| Software-use terms | Proprietary; no open-source licence is granted. See [NOTICE.md](../NOTICE.md) |

Code ownership is a maintenance route, not proof of legal ownership or transfer
authority. The sender must fill the three TBD fields from the applicable
contract or authorized project record before an external handoff.

## Workflow matrix

| Class | Workflow | Prerequisites | Command | Expected output |
|---|---|---|---|---|
| Standalone checkout | Unit and regression suite | Python 3.10+, editable install | `python -m pytest -q` | Pytest summary; evidence-dependent tests may skip with an explicit reason. |
| Standalone checkout | Direct EO-in-ERV smoke study | Tracked source and configuration | `python3 -B scripts/run_direct_eo_erv_study_v1.py --mode smoke --overwrite` | `outputs/direct_active_eo_erv_study_v1/smoke/` with case registers, audit, summary, and figures. |
| Standalone checkout | Combined synthetic sensitivity | Tracked source and configuration | `python3 -B scripts/run_direct_active_erv_tw50_d1e10.py` | `outputs/direct_active_erv_tw50_d1e10_v1/study/` with decision summary, registers, audit, and figures. |
| Post-V10 handoff | Integrated sealed EO vapour-cell sizing | Tracked source, configuration, and Python dependencies | `python3 -B scripts/design_eo_vapor_test_cell.py --output-dir reports/test_cell_handoff_supplement_2026-09-03/calculations` | Volume basis, 5 s-per-segment ABBA transient sampled every 0.1 s, explicit engineering register, audit, source manifest, and plot. |
| V10 result overlay | Direct-ERV gradient closure | V10 source and result archives extracted into one tree | `python3 -B scripts/run_direct_erv_gradient_closure_v1.py --overwrite` | `outputs/direct_erv_gradient_closure_v1/`. |
| V10 result overlay | Capacitive-electrode transient screen | V10 source and result archives extracted into one tree | `PYTHONPATH=src python3 scripts/run_capacitive_electrode_study_v1.py --overwrite` | `outputs/capacitive_electrode_study_v1/` with DC, cycle, leakage, and frozen-case summaries plus audit. |
| External `HeiQ_V2` | Operating-region, post-ERV, integrated-evidence, FOM, atlas, and August closure workflows | Matching sibling `HeiQ_V2` source/outputs and, for some workflows, archived downloaded inputs | Use the individual script help and supply explicit roots where supported. | Workflow-specific ignored `outputs/` and generated reports. |
| Historical | V2/V3/V12 prearchitecture family, archived August study families, V8/V9 report builders, `run_final_delivery_check_v1.py`, and `package_final_release_v9.py` | Dated historical input tree | Run only to reproduce the named historical snapshot. | Historical evidence; never a V10 release gate. |
| Post-V10 supplement | Current review figures and technical deck | `requirements-docs-presentations.txt`; `npm ci` from `package-lock.json` | `npm run build:presentations` | `deliverables/current/2026-09-03_handoff_v1/figures/model_review/` and the current PPTX under `presentations/`. |
| Release engineering | V10 packager | Exact clean source revision and all hash-bound V10 inputs | `python3 scripts/package_final_closeout_v10.py --expected-source-revision <revision>` | A complete atomic release directory after every gate passes. |

Paths embedded in historical configurations and manifests may name the original
Linux/WSL host. Treat them as provenance. Resolve inputs explicitly on a new
machine; do not assume those absolute paths exist.

The complete configuration classification is machine-readable in
[`workflow_reproducibility.json`](workflow_reproducibility.json). A regression
test requires every top-level configuration to be classified and forbids
personal absolute paths in current, current-supporting, and post-V10 handoff
configurations. `historical_external` is the only class allowed to retain an
original host path.

For historical commands that accept `--v2-root`, use a caller-owned value, for
example:

```bash
export HEIQ_V2_ROOT=/path/to/HeiQ_V2
python3 scripts/run_membrane_operating_region_study_v1.py \
  --v2-root "$HEIQ_V2_ROOT"
```

For a config-only historical workflow, copy its configuration to a local work
area and replace the dated source paths there. Do not rewrite a frozen result
manifest. Current provenance fields that refer to `HeiQ_V2` store a path
relative to `HEIQ_V2_ROOT`, not a personal host path.

## Development and document setup

The supported development baseline is Python 3.10 or newer. V10 was packaged
with Python 3.10.12 on Linux/WSL2. For a normal compatible installation:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest -q
```

`pyproject.toml` is the compatibility declaration and intentionally uses
minimum versions. `constraints/v10-python-3.10.txt` is a curated constraint set
for the Python 3.10 package versions active during V10 verification; it is not
a cross-platform lockfile, has no artifact hashes, and does not replace the V10
environment record. Use it when a close handoff replay matters:

```bash
python -m pip install -c constraints/v10-python-3.10.txt setuptools wheel
python -m pip install --no-build-isolation \
  -c constraints/v10-python-3.10.txt -e ".[dev]"
```

Document and presentation builders need additional software:

- `python-docx` (imported as `docx`), Pillow (imported as `PIL`), `lxml`,
  `python-pptx`, and `XlsxWriter` are pinned in
  `requirements-docs-presentations.txt`;
- Node.js 22.17.0 and npm 11.4.2 are the recorded presentation-build runtime;
  `.nvmrc`, `package.json`, and `package-lock.json` select the runtime and lock
  `pptxgenjs` 4.0.1 plus its transitive Node dependencies;
- `latexmk` and a TeX Live installation with the packages used by the report
  preambles are required for LaTeX/PDF reports;
- LibreOffice is required for the scripted PPTX-to-PDF conversion and visual
  review path;
- Lato is the presentation font; install it rather than relying on silent font
  substitution. Liberation Mono is also used by the technical deck.

The handoff workstation recorded TeX Live 2022/pdfTeX 1.40.22, latexmk 4.76,
LibreOffice 7.3.7.2, and the system Lato font. These system-package versions are
an environment record, not a claim that newer compatible versions fail.

Install the non-model Python and Node dependencies with:

```bash
python -m pip install -r requirements-docs-presentations.txt
npm ci
npm run build:presentations
```

The presentation sources can be generated without LibreOffice, but the
controlled PDF rendering/check path cannot. A build note and checksums must
record the actual tools used for every transferred supplement.

## Reconstruct and verify V10

First verify the delivered package from its directory:

```bash
sha256sum --check SHA256SUMS
```

For a clean reconstruction, extract both archives into the same empty parent
directory. They share the root directory `XMembrane_Trond_Study/`:

```bash
reconstruction_parent=$(mktemp -d)
unzip archives/HeiQ_XMembrane_2026-09-02_v10_source.zip -d "$reconstruction_parent"
unzip archives/HeiQ_XMembrane_2026-09-02_v10_results.zip -d "$reconstruction_parent"
cd "$reconstruction_parent/XMembrane_Trond_Study"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest -q
```

The recorded reconstruction result is `275 passed, 39 skipped, 0 failed`.
`verification/pytest_result.json` contains the exact skip reasons. The package
environment inventory is diagnostic. V10 itself predates the handoff constraint
file and carries no Python lockfile; its source archive and environment record
remain the exact reconstruction authority.

## Post-V10 handoff supplement

The sole current supplement entry point is
`deliverables/current/2026-09-03_handoff_v1/`. Its current technical deck is
`presentations/HeiQ_XMembrane_Technical_Model_Peer_Review_V10_2026-09-03.pptx`
with a corresponding PDF. The standalone model explanation is
`presentations/HeiQ_XMembrane_Model_Explainer_V10_2026-09-03.html`, and
`PRESENTATION_BUILD.md` records the build and render path.
The previous V9 presentation set is archived under
`deliverables/archive/2026-09-02_v9_presentations/`.

The selected experimental starting point has two equal, sealed 500.0 mL
net-free-gas chambers, a 50 mm by 50 mm active region, and local 1/2/4 mm gas
gaps with 2 mm nominal. Its tracked calculation basis is:

- [cell design note](EO_VAPOR_TEST_CELL_DESIGN.md);
- `config/eo_vapor_test_cell_design.json`;
- `scripts/design_eo_vapor_test_cell.py`;
- `tests/test_eo_vapor_test_cell_design.py`.

The sole current design source and generated numerical evidence are under
`reports/test_cell_handoff_supplement_2026-09-03/`. The earlier
`reports/test_cell_dimensioning_basis_2026-09-02/` directory is retained only
as superseded design history. The transferred test-cell copy and the current
presentation belong under `deliverables/current/2026-09-03_handoff_v1/`. The
supplement carries an explicit allowlisted inventory and checksums. Review every
presentation claim against the V10 report before release.

The later `reports/test_cell_20mm_channel_study_2026-09-04/` directory is a
post-release geometry sensitivity, not part of handoff-v1. It treats 20 mm as
bulk cavity depth, retains the 2 mm local membrane gap, compares the existing
100 mm clear face with a 165 mm alternative, and records an assessment of all
13 fabrication gates. Reproduce it with
`python3 scripts/analyze_eo_vapor_test_cell_20mm.py`.

The rendered-document toolchain is broader than `pyproject.toml`. Its Python
versions are declared in `requirements-docs-presentations.txt` with the V10
constraints file, and its Node dependency is locked by `package-lock.json`.
Use `python -m pip install -r requirements-docs-presentations.txt` and `npm ci`
before running the supplement build. Record the fonts and PDF-conversion method
in the supplement build note.

## Final preflight

1. Confirm that V10 `SHA256SUMS` passes and `verification/V10_STATUS.json`
   reports `PASS` and `publishing_eligible: true`.
2. Confirm that the complete V10 directory, not only its guide files, is in the
   transfer set.
3. Run `python -m pytest -q` in the intended development checkout and retain
   the result with the handoff notes.
4. Record the exact Git revision and identify any uncommitted or ignored files
   intentionally included in the transfer.
5. Keep arbitrary working `outputs/`, caches, LaTeX intermediates, rendered
   slide images, and local virtual environments outside the controlled source
   handoff unless they appear in an explicit package inventory.
6. Confirm that every post-V10 document or presentation is inventoried under
   `2026-09-03_handoff_v1/` with a checksum; keep its authority below V10.
7. Confirm that the checkout is transferred by clone, bundle, or controlled
   export—not by copying this linked worktree's `.git` pointer.
8. Fill the legal rights-holder, transfer-authorization, and confidentiality
   fields above; retain `@Torsheim` as the repository maintenance route unless
   an authorized successor is recorded.
