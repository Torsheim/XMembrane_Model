# Current model chain

The governing V10 architecture applies active electro-osmotic transport within
the ERV core. The current numerical hierarchy is:

```text
declared membrane property vector
              |
              v
local EO, diffusion, conduction, and activity state
              |
              v
gas-film and local surface-state calculation
              |
              v
counter-current axial EO-in-ERV integration
              |
              v
core hydraulics, coil, and conditional energy ledger
              |
              +--> material and operating-coordinate sensitivities
              |
              +--> gradient, polarity, and numerical closure audits
              |
              +--> blocking-electrode transient qualification
              |
              v
hash-bound V10 closeout report and evidence package
```

## 1. Local membrane transport

The reviewed local implementation is
`heiq_pre_receiver_material_analyses/heiq_pre_receiver_model.py`, loaded through
`src/heiq/wp1/membrane/local_transport.py`. It evaluates electro-osmotic and
diffusive water transport, ionic conduction, activity-dependent properties,
and voltage-controlled states. Thermodynamic identities and signed transport
checks live in `src/heiq/wp1/membrane/thermodynamics.py`.

The input property vector is a model coordinate. It becomes a material claim
only after the coupled sorption, diffusivity, conductivity, drag, thickness,
and conditioning state are measured on the same sample.

## 2. Air-side and surface states

`src/heiq/wp1/airside/properties.py` and
`src/heiq/wp1/axial/local_state.py` calculate psychrometric states, channel
transfer coefficients, gas-film losses, and membrane-surface activities. The
surface-gradient result is an engineering diagnostic within the actively
driven transport calculation.

## 3. Direct EO-in-ERV axial integration

The current shared-core calculation is
`src/heiq/wp1/studies/direct_eo_erv.py`, orchestrated by
`scripts/run_direct_eo_erv_study_v1.py` with
`config/direct_eo_erv_study_v1.json`. It couples the balanced process and
return/exhaust streams segment by segment, conserves transferred water, sizes
the active area, checks stack coordinates, and evaluates the declared coil and
conditional energy ledger.

Current density and active area remain visible design coordinates. They are not
acceptance limits in the exploratory V10 screen.

## 4. Sensitivity and closure studies

The current study family uses the same direct-ERV implementation:

| Purpose | Entry point | Data class |
|---|---|---|
| Direct study and smoke replay | `scripts/run_direct_eo_erv_study_v1.py` | standalone checkout |
| One-at-a-time membrane sensitivity | `scripts/run_direct_eo_erv_membrane_sensitivity_1v.py` | standalone checkout |
| Combined synthetic `t_w=50`, `D=1e-10 m²/s` case | `scripts/run_direct_active_erv_tw50_d1e10.py` | standalone checkout |
| Gradient and signed-polarity closure | `scripts/run_direct_erv_gradient_closure_v1.py` | V10 result overlay |

The combined sensitivity case is conditional and synthetic. It is not evidence
for an existing material.

## 5. Capacitive-electrode transient extension

`src/heiq/wp1/electrodes/capacitive.py` and
`scripts/run_capacitive_electrode_study_v1.py` replace the steady electrode
assumption with a signed reduced-order RC state for two blocking capacitive
electrodes. The study evaluates DC charge duration, symmetric cycles, interface
ESR, diagnostic leakage, and frozen replays of selected axial states.

The capacitance and leakage coordinates are unmeasured sensitivities. The
transient calculation keeps membrane inventory and gas-stream states frozen;
it is not a dynamic full-core or full-system simulation. V10 concludes that
blocking capacitive operation supplies finite startup displacement and that the
modelled symmetric cycle has zero net EO transport.

The original stored terminal voltage is the primary replay boundary. At the
unmeasured 5,000 F/m² pair-capacitance coordinate, the stored O30 case at
0.025 V retained 16.2% of its initial EO contribution after one hour and
averaged 0.68% over 24 hours (0.17 h equivalent full contribution). The
separate 1.8 V current-commanded replay retained 98.5% after one hour and 4.6%
over 24 hours, but is only an optimistic capacity upper bound. Terminal voltage
is not an individual-electrode or electrode-pair electrochemical-window limit;
the transient model does not resolve individual electrode potentials.

## 6. System interpretation and release authority

The conditional energy ledger is evaluated only with the explicitly declared
power and heat terms. Missing experimental or system terms remain unresolved.
`scripts/package_final_closeout_v10.py` binds the report to its evidence,
archives, source revision, checksums, scientific audits, and reconstructed-tree
test result. The package under `deliverables/current/2026-09-02_v10/` is the
authority for model-phase conclusions.

## Historical numerical branches

The V2/V3/V12 legacy implementations, prearchitecture optimisation,
bottleneck studies, August system comparisons, and earlier report builders are
retained to reproduce dated development results. They do not define the current
architecture or release gate. Their external-data requirements are classified
in [the handoff guide](HANDOFF.md).

This repository contains research models, not a validated product design.
