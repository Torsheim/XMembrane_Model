# Project closure check v1

**Phase result:** MODEL STUDY COMPLETE - MATERIAL AND SUBSYSTEM FEASIBILITY STARTS

This is a bounded modelling audit, not a material or technology validation.

## Key findings

- Stored active-ERV segments passing the thermodynamic audit: 16387/16387.
- Conditional active-ERV cases reclassified when passive surface direction is replaced by the dissipation gate: 0.
- A negative source-minus-receiver surface-activity margin is classified as uphill active transport when the applicable audit closes: full coupling and dissipation identities for the constant-drag power-law model, or the boundary energy balance for the variable-drag Nafion summary.
- Broad modelling can stop: True.
- Material data collection ready: True.
- Candidate ranking ready: False.

## Common-voltage selected replays

| Case | Completion | Voltage | Result | Area (m2) | Current range (A/m2) | Conditional receiver/sink room (kWh/kg) |
|---|---:|---:|---|---:|---:|---:|
| screen_50pct_1v | 50.000% | 1.000 | CONVERGED_TARGET | 2468.35 | 3.646--6.879 | 0.13620 |
| screen_60pct_1v | 60.000% | 1.000 | CONVERGED_TARGET | 3708.38 | 2.432--6.322 | 0.13520 |
| screen_67p5pct_1v | 67.500% | 1.000 | CONVERGED_TARGET | 5269.67 | 1.520--5.905 | 0.13389 |
| frontier_low_76p328125pct_1v | 76.328% | 1.000 | CONVERGED_TARGET | 9839.48 | 0.446--5.415 | 0.12979 |
| frontier_high_76p40625pct_1v | 76.406% | 1.000 | CONVERGED_TARGET | 9926.17 | 0.436--5.410 | 0.12971 |
| o30_1v | 72.700% | 1.000 | CONVERGED_TARGET | 7191.41 | 0.887--5.616 | 0.13221 |
| o30_balanced_anchor_voltage | 72.700% | 1.314 | CONVERGED_TARGET | 3461.40 | 3.044--8.427 | 0.13116 |
| full_duty_1v | 100.000% | 1.000 | PHYSICAL_NO_COMMON_VOLTAGE_AT_THIS_COORDINATE | nan | 0.064--10.964 | nan |
| full_duty_2v | 100.000% | 2.000 | NUMERICAL_OR_LOCAL_SOLUTION_FAILURE | nan | 2.358--10.006 | nan |

## Sampled common-voltage scan

| Completion | Feasible sampled point | Feasible sampled span (V) | Minimum area (m2) |
|---:|---|---:|---:|
| 50.000% | True | 0.55--1.75 | 1157.35 |
| 60.000% | True | 0.70--1.60 | 1714.62 |
| 67.500% | True | 0.80--1.45 | 2456.49 |
| 72.700% | True | 0.90--1.40 | 3062.26 |
| 100.000% | False | none | n/a |

## Decision gates

| Gate | Status | Blocks | Evidence |
|---|---|---|---|
| G01_THERMODYNAMIC_SIGN | PASS | model_closure | 16387/16387 stored valid segments pass; 8357 full constant-drag identities + 8030 variable-drag boundary-energy audits |
| G02_SURFACE_GATE_RECLASSIFICATION | PASS | claim_correction | 0 cases require reclassification because the stored source outputs already use the corrected thermodynamic/non-surface screen |
| G03_COMMON_VOLTAGE_PRIMARY | PASS | material_search_path | 3/3 primary 1-V cases pass |
| G03B_NO_CURRENT_DENSITY_GATE | PASS | model_closure | In this closure run, current density is solved/sampled and no A/m2 acceptance ceiling is configured or applied |
| G04_FULL_DUTY_SINGLE_BUS | OPEN | full_duty_single_bus_claim_only | No feasible point was found on the 0.05-V grid from 0.5 to 2.0 V at the frozen anchor |
| G05_SEGMENT_CONVERGENCE | PASS | model_closure | 7/7 closure-relevant replay outcomes stable from 32 to 64 segments |
| G06_INDEPENDENT_CURRENT_ROOTS | PASS | model_closure | 6/6 local roots reproduced with Brent |
| G07_UNIFORM_CURRENT_STEP_REPLAY | PASS | model_closure | 3 selected anchors replayed at 20/10/5 m2 |
| G08_FROZEN_ENERGY_CONTRACT | PASS | model_closure | baseline=543.740564 kW; break-even=0.156700807441 kWh/kg; full-duty sink budget=0.128323175854 kWh/kg |
| G09_MATERIAL_DATA_SCHEMA | PASS | supplier_data_collection | 9 requirement rows found |
| G09B_CANDIDATE_DATA_COMPLETENESS | OPEN | candidate_ranking | 0/9 requirement rows complete; one same-sample candidate ID is required |
| G10_RECEIVER_CONTRACT | OPEN | candidate_ranking_and_system_claim | OPEN_NEXT_PHASE |
| G11_PRACTICAL_LIMITS | OPEN | candidate_ranking | UNRESOLVED_TEAM_INPUT |
| G12_RUNTIME_ENVIRONMENT | PASS | release_freeze | Python 3.10.12, NumPy 1.26.4 |
| G13_RELEASE_SNAPSHOT | OPEN | release_freeze | revision=29ba6da9a33a50d8771adc6ee28438ab5131eed7; clean=False |

The correct milestone is **model study complete -- material and subsystem feasibility starts**, not technology validated.
