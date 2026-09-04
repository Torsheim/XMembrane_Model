# XMembrane model

Physics-based research software for electro-osmotic water transport in humid-air
systems. The selected model architecture places active EO transport within the
ERV core.

## Start here

Use [the handoff guide](docs/HANDOFF.md) to choose the correct reading or
reproduction path. It identifies which workflows run from a clean checkout,
which need the V10 result overlay, and which retain historical `HeiQ_V2`
dependencies.

The governing model-phase delivery is the hash-frozen English V10 package:

- [V10 package guide](deliverables/current/2026-09-02_v10/README.md)
- package directory: `deliverables/current/2026-09-02_v10/`
- governing report inside that package:
  `reports/HeiQ_XMembrane_Final_Project_Closeout_2026-09-02_v10.pdf`
- release status: `verification/V10_STATUS.json`

V10 governs whenever an earlier report, presentation, note, or generated output
uses different wording or reaches a different status. The model phase is closed;
the technology remains a research concept pending experimental qualification.
The final model interpretation includes the finite-duration response of blocking
capacitive electrodes and does not establish sustained EO operation or a net
full-system energy saving.

The selected vapour coupon-cell dimensioning and current presentation are in
the separately versioned post-V10 supplement at
`deliverables/current/2026-09-03_handoff_v1/`. They are handoff aids and do not
amend the V10 decision.

## Install and test

Python 3.10 or newer is required. From a complete repository checkout:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest -q
```

On Windows PowerShell, activate the environment with
`.venv\Scripts\Activate.ps1`. The supported numerical installation is editable
from the complete checkout; a wheel containing only `src/` is not standalone.

Generated study directories under `outputs/` are intentionally ignored by Git.
Tests that require a large historical result set skip when that evidence is not
present; unit and regression tests still run from a clean checkout.
`pyproject.toml` declares compatible minimums, while
`constraints/v10-python-3.10.txt` selects the model/test dependency versions
observed in the verified V10 Python 3.10 environment. It is a constraint set,
not a cross-platform lockfile. The full V10 packaging inventory is recorded under
`deliverables/current/2026-09-02_v10/environment/` when the complete release is
present.

## Workflow classes

| Class | Use | Representative entry points |
|---|---|---|
| Standalone checkout | Current package tests, direct EO-in-ERV calculation, and synthetic sensitivity | `python -m pytest -q`; `scripts/run_direct_eo_erv_study_v1.py`; `scripts/run_direct_active_erv_tw50_d1e10.py` |
| V10 result overlay | Audits that replay the frozen direct-ERV case and segment registers | `scripts/run_direct_erv_gradient_closure_v1.py`; `scripts/run_capacitive_electrode_study_v1.py` |
| External `HeiQ_V2` evidence | Integrated August studies and report builders that consume a sibling historical repository or its outputs | `scripts/run_membrane_operating_region_study_v1.py`; post-ERV study family; `scripts/make_integrated_evidence_register_v1.py` |
| Historical | Earlier model generations, decision packages, presentation builders, and the V9 delivery checker | retained for provenance; not current release gates |
| Post-V10 handoff | Integrated sealed 500 mL-per-side vapour-cell sizing, 20 mm bulk-depth sensitivity, and current presentation | `scripts/design_eo_vapor_test_cell.py`; `scripts/analyze_eo_vapor_test_cell_20mm.py`; `npm run build:presentations` |

Exact prerequisites, commands, expected outputs, and platform assumptions are in
[the handoff guide](docs/HANDOFF.md).

## Model and evidence boundaries

- [Model chain](docs/MODEL_CHAIN.md) — current numerical hierarchy and the
  capacitive transient extension.
- [Claim boundary](docs/CLAIM_BOUNDARY.md) — permitted interpretation of model
  results.
- [Package boundaries](docs/PACKAGE_BOUNDARIES.md) — native modules and retained
  compatibility sources.
- [Source provenance](docs/PROVENANCE.md) — source checksum registers and the V10
  integrity authority.
- [Workflow classification](docs/workflow_reproducibility.json) —
  machine-readable current, result-overlay, external, and historical boundaries.
- [Research log](docs/WP1_RESEARCH_LOG.md) — dated development record, including
  the September closeout.
- [Report map](reports/README.md) and [deliverable map](deliverables/README.md) —
  governing, supporting, supplemental, and historical documents.
- [Notice](NOTICE.md) — proprietary status and transfer-authorization boundary.

Current density and membrane area are reported design coordinates in the
exploratory screen. Material-property vectors are hypothetical unless supported
by same-sample measurements. Full-system claims require a complete, explicit
energy and engineering ledger.
