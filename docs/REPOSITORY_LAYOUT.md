# Repository layout and naming policy

The active source tree uses functional names that describe what a file does.
Personal names are not used for current code, configuration, tests or team
reports.

## Canonical source families

| Purpose | Runner or module | Configuration | Test |
|---|---|---|---|
| System energy closure | `scripts/run_system_energy_closure_study.py` | `config/system_energy_closure_references.json` | `tests/test_system_energy_closure_study.py` |
| Direct EO in the ERV | `scripts/run_direct_eo_erv_study_v1.py` and `src/heiq/wp1/studies/direct_eo_erv.py` | `config/direct_eo_erv_study_v1.json` | `tests/test_direct_eo_erv.py` and `tests/test_direct_eo_erv_study_v1.py` |
| Direct-EO ERV membrane sensitivity | `scripts/run_direct_eo_erv_membrane_sensitivity_1v.py` | uses the direct-EO ERV configuration | covered by the direct-EO ERV tests |
| EO vapour test-cell design | `scripts/design_eo_vapor_test_cell.py` | `config/eo_vapor_test_cell_design.json` | `tests/test_eo_vapor_test_cell_design.py` |
| Current-density policy | the three active receiver workflows | their native configurations | `tests/test_current_density_cap_policy.py` |

Use `run_` for executable studies, `analyze_` for result reduction, `plot_` or
`make_` for generated presentation assets, and `test_` for regression tests.
A `_vN` suffix identifies a method or schema version; dates identify report
snapshots.

## Stable legacy output identifiers

Several ignored directories under `outputs/` retain older identifiers such as
`direct_active_eo_erv_study_v1`, `eo_vapor_cell_sizing_v1` and
`trond_system_closure_v2_no_current_gate`. They are kept intentionally because
dated reports and hash-bound manifests refer to those exact paths. New source
filenames are canonical; these output identifiers are compatibility and
provenance keys, not the preferred names for new code.

## Historical and controlled snapshots

Directories inside a hash-frozen release are immutable snapshots. They can
therefore contain the source names that were valid when the package was
created. Do not rename files inside `deliverables/current/2026-08-31_v8_1` or
manually edit its manifests. The root source tree and this mapping provide the
current names.

Generated simulation outputs are ignored by Git unless a small regression
fixture is explicitly allow-listed under `data/golden/`. Tests that validate a
large materialized output skip clearly when that evidence is absent from a
clean checkout; unit and regression tests remain runnable.
