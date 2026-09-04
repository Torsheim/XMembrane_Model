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
| Combined synthetic `t_w=50`, `D=1e-10 m2/s` replay | `scripts/run_direct_active_erv_tw50_d1e10.py` | derived from the direct-EO ERV configuration | covered by the direct-EO ERV tests and output audit |
| EO vapour test-cell design | `scripts/design_eo_vapor_test_cell.py` | `config/eo_vapor_test_cell_design.json` | `tests/test_eo_vapor_test_cell_design.py` |
| Post-V10 20 mm chamber-depth screen (fixed 25 cm² active membrane) | `scripts/analyze_eo_vapor_test_cell_20mm.py` | `config/eo_vapor_test_cell_20mm_channel_study.json` | `tests/test_eo_vapor_test_cell_20mm_study.py` |
| Capacitive-electrode transient screen | `scripts/run_capacitive_electrode_study_v1.py` and `src/heiq/wp1/electrodes/capacitive.py` | `config/capacitive_electrode_study_v1.json` | `tests/test_capacitive_electrode_study_v1.py` |
| V10 model-phase closeout release | `scripts/package_final_closeout_v10.py` | hash-bound report/evidence inputs | live full suite plus `verification/V10_STATUS.json` |
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
created. Do not rename or manually edit files inside
`deliverables/current/2026-09-02_v10` or the historical
`deliverables/current/2026-08-31_v8_1` release. The root source tree and this
mapping provide the current names.

Generated simulation outputs are ignored by Git unless a small regression
fixture is explicitly allow-listed under `data/golden/`. Tests that validate a
large materialized output skip clearly when that evidence is absent from a
clean checkout; unit and regression tests remain runnable.
