# HeiQ XMembrane final project closeout

**Version 10 — 2 September 2026**

**Decision status:** model phase complete; technology not validated

**Authority:** current project-closeout decision basis

## Document control

This report supersedes Version 9 for all current project decisions. Version 9
and earlier reports are preserved unchanged as historical model evidence and
provenance; they are not deleted, rewritten or retroactively relabelled.

Version 9 documented conditional steady-state energy windows. The subsequent
capacitive-electrode transient study changes the decision interpretation:
those windows cannot be applied to long-duration operation with purely
blocking electrodes. Where this report and Version 9 differ, this report
governs.

At the original stored O30 terminal limit of 0.025 V, the primary replay
retains only **16.2%** of counterfactual steady EO after one hour and **0.68%**
over 24 hours. The former 98.5%/4.6% result used a separate 1.8 V
current-commanded ceiling and is retained only as an optimistic upper bound.

## Final decision

> **The XMembrane model phase is complete. The technology is not validated.**

The modelling is sufficiently mature to stop broad hypothetical parameter
sweeps. It has produced internally audited transport models, explicit
architecture and comparison rules, useful sensitivity coordinates, and a
falsifiable coupon-test plan. It has not demonstrated a real membrane,
sustainable electrode mechanism, manufacturable module or net system saving.

No further modelling is required to close this project phase. Any continuation
is a separately gated experimental and engineering phase driven by measured
data.

## Governing architecture

The selected modelling architecture is **direct electro-osmotic (EO) transport
inside the ERV membrane/core**. Local through-plane current density and water
flux are evaluated along the supply and receiver channels; downstream
conditioning removes any remaining load.

The historical **post-ERV O30** configuration is not a selected product or
system architecture. It may be used only as a prescribed coupon-test boundary,
control or benchmark, and must be labelled that way, unless a future controlled
decision document explicitly selects another architecture. O30 is a humidity
target coordinate, not evidence that a downstream EO module is preferred.

## Evidence that closes the model phase

### 1. Purely blocking capacitive electrodes are transient

The new electrode study replaces the former implicit assumption that the
electrodes can sustain continuous DC current. For two purely blocking
capacitive electrodes, charge accumulates until the terminal-voltage limit is
reached; current and incremental EO transport then decay toward zero.

The transient solver is current-commanded with an absolute terminal-voltage
clamp, unlike the voltage-controlled steady axial model. The primary replay
therefore preserves each stored case's original terminal limit:

| Stored case | Terminal limit | EO after 1 h | EO over 24 h | Equivalent target time | Maximum pair-capacitor voltage |
|---|---:|---:|---:|---:|---:|
| O30 | **0.025 V** | **16.2%** | **0.68%** | **0.17 h** | **0.478 V** |
| Full humidity duty | **0.250 V** | **16.5%** | **0.69%** | **0.17 h** | **0.250 V** |

The separate 1.8 V current-commanded replay is an optimistic upper-bound
sensitivity, not a same-voltage replay:

| Stored case | Terminal ceiling | EO after 1 h | EO over 24 h | Equivalent target time | Maximum pair-capacitor voltage |
|---|---:|---:|---:|---:|---:|
| O30 upper bound | **1.800 V** | **98.5%** | **4.6%** | **1.10 h** | **2.253 V** |
| Full-duty upper bound | **1.800 V** | **92.3%** | **5.0%** | **1.20 h** | **1.800 V** |

These percentages are relative to the counterfactual continuous-current EO
displacement. The replay freezes the bulk stream states, gas films and
installed area while current collapses; it is a duration diagnostic, not a
dynamic, mass-balanced ERV prediction and not a revised HVAC-saving result.
The reference capacitance of 10,000 F/m² per electrode was an unmeasured
sensitivity assumption.

The terminal-voltage clamp is **not** an individual-electrode or
electrode-pair electrochemical-window constraint. The model does not resolve
individual electrode potentials and imposes no pair stability window. The
reported pair-capacitor state can therefore exceed the terminal clamp when the
membrane polarisation contribution is negative, as in the 2.253 V O30 upper
bound. These voltages are model states, not validated safe operating limits.

Symmetric, charge-balanced cycling gives **zero net EO water transport over a
complete cycle** in the present constant-drag model, to numerical precision.
Forward water displacement during one half-cycle is returned during the other.
A nonzero sustainable result therefore requires measured asymmetry or another
physical mechanism; it cannot be inferred from capacitance alone.

### 2. The recent \(t_w=50\), \(D=10^{-10}\ \mathrm{m^2/s}\) case is synthetic

The recent combined run is retained as a sensitivity result, not a candidate
membrane:

| Item | Result |
|---|---:|
| Synthetic transport number | \(t_w=50\) |
| Synthetic water diffusivity | \(D=1.0\times10^{-10}\ \mathrm{m^2/s}\) |
| Transport-closed case rows | **4 of 8** |
| Best available eight-segment diagnostic area | **43,019.5 m²** |
| Voltage at that diagnostic | **0.10 V** |
| Full-coupled/full-system case rows | **0** |

The study audit passed integrity and reproducibility checks only. The joint
property vector was not measured on an identifiable membrane; `material_validated`
is false. The large calculated area is diagnostic, and the conditional energy
arithmetic omits unvalidated subsystems. This run therefore does not establish
a realistic material, a practical module, or a system-energy claim.

### 3. Earlier conditional windows remain historical evidence

Version 9's integrated-ERV O30 result and other positive energy differences
remain useful records of what the steady model predicted under its declared
assumptions. They are now historical conditional evidence. They must not be
reported as sustained performance because the continuous electrode mechanism,
same-sample membrane properties, receiver/thermal coupling and practical
hardware were not validated.

## Technical reference for the frozen axial model

The steady axial calculations are **voltage controlled**: terminal voltage is
held constant for a case, while current is not. Each axial segment solves its
local through-plane current density \(j(x)\), coupled to the two gas films and
net water flux, from the voltage balance

\[
V_{\mathrm{app}}=
j(x)\left(\mathrm{ASR}_{\mathrm{mem}}(x)+\mathrm{ASR}_{\mathrm{series}}\right)
+t_w\frac{RT}{F}\ln\!\left(\frac{a_{w,r}^{s}}{a_{w,s}^{s}}\right)
+V_{\mathrm{fixed}}.
\]

Local activities, resistance and flux vary along the channel, so \(j(x)\)
also varies with axial position. This is through-plane current sampled along
\(x\), not a solved in-plane current-collector current. The same physical
through-plane current has equal magnitude on the two membrane faces; it appears
with opposite sign only when each face is expressed using its own outward
surface normal.

The supply and receiver channel gaps are each **2.0 mm**, giving
\(D_h=4.0\) mm for the parallel-plate correlation. The model contains no
literal gas-film slab. At film scale factor 1, \(Sh=7.54\) implies the
**derived effective film thickness**

\[
\delta_{\mathrm{eff}}=\frac{D}{k}=\frac{D_h}{Sh}=0.5305\ \mathrm{mm}
\]

on each side. The unequal water-vapour diffusivities at the stated bulk
temperatures give \(k\approx0.0511\) m/s on the 32 °C supply side and
\(k\approx0.0475\) m/s on the 20 °C receiver side. The 0.5305-mm quantity is
therefore a correlation-equivalent boundary-layer thickness, not a physical
GDL or manufactured film.

The inverse-design anchor is also hypothetical: \(t_w=100.0608\),
\(D=1.5979\times10^{-14}\ \mathrm{m^2/s}\),
\(\sigma=23.1719\ \mathrm{S/m}\), and dry thickness
\(L=36.9137\ \mu\mathrm{m}\). It must not be called a realistic membrane.
Likewise, the combined \(t_w=50\), \(D=10^{-10}\ \mathrm{m^2/s}\) vector is
synthetic.

## Final claim boundary

The following statements are supported:

- the model phase is complete;
- direct EO inside the ERV is the selected modelling architecture;
- the models identify conditional sensitivities and experimental hypotheses;
- purely blocking capacitive electrodes provide finite startup displacement,
  not demonstrated continuous EO duty;
- the original-voltage O30 replay retains 16.2% of counterfactual steady EO
  after one hour and 0.68% over 24 hours; the 1.8 V replay is only an optimistic
  current-commanded upper bound;
- the \(t_w=50\), \(D=10^{-10}\ \mathrm{m^2/s}\) run is a synthetic,
  partially closed sensitivity screen.

The following statements are **not** supported and must not be made:

- that an existing or procurable membrane meets the model property bundle;
- that continuous EO transport has been demonstrated;
- that a Faradaic, pseudocapacitive or rectifying electrode architecture is
  validated;
- that membrane, module, receiver, current collector or full-system performance
  has been experimentally validated;
- that a net HVAC energy saving, commercial advantage, lifetime, cost or
  manufacturability target has been achieved.

The controlled closeout statement is:

> **The model phase is complete. No existing membrane, continuous electrode
> mechanism, module-scale performance or net system saving has been validated.
> All positive energy results remain conditional model sensitivities and must
> not be presented as product or commercial claims.**

## Accepted next phase, if the technology is continued

Only the following work is accepted as a successor phase:

1. **Demonstrate a sustainable electrode mechanism.** Measure a Faradaic,
   pseudocapacitive, rectifying, flow-switched or other charge/water-asymmetric
   mechanism. Quantify separate electrode potentials, reaction products,
   kinetics, overpotential, energy recovery, self-discharge and lifetime.
2. **Complete MAT-01–MAT-09 on the same identifiable sample or batch.** Measure
   sorption/hysteresis, water mobility/permeance, EO drag, wet through-plane
   conductivity, membrane/contact ASR, thickness/swelling/mechanics, coupled
   net water flux, receiver/electrode compatibility, and provenance/availability.
3. **Run a controlled-flow coupon test.** Use matched EO-off/EO-on operation,
   ABBA polarity reversal, two-sided water balance, pressure control, film/gap
   repeats and complete charge/discharge cycles. A post-ERV O30 state may be
   used here only as the declared boundary/control.
4. **Close the dynamic and full-system ledgers.** Couple transient membrane
   inventory and gas-stream response, receiver operation, sensible/latent heat,
   pressure drop, fans, power electronics, heat rejection, leakage and
   cross-contamination.
5. **Apply product constraints.** Establish accepted limits for active area,
   volume, pressure drop, current collection, cost, manufacturability, safety,
   fouling, lifetime and end-of-life handling.
6. **Replay once with measured inputs and hold a new gate review.** Do not
   restart broad hypothetical sweeps. A new model or product claim requires a
   controlled successor report.

## Closeout status

| Workstream | Closeout status |
|---|---|
| Mathematical/model development | **Complete for this phase** |
| Sensitivity and architecture screening | **Complete for this phase** |
| Real material qualification | **Not validated; successor phase** |
| Sustainable electrode operation | **Not validated; successor phase** |
| Coupled module/full-system closure | **Not validated; successor phase** |
| Product/commercial decision | **No claim permitted** |

### Release verification

The regenerated capacitive study audit passes **16 of 16** checks and its
targeted test module passes **9 of 9** tests. The corrected targeted release
suite passes **63 tests**, and the full suite passes **313 tests with 1
skipped**. The sole skip is the optional design-frontier smoke test because its
output is absent. These are code and integrity results, not technology
validation; the governing package result remains the V10 status file.

`scripts/run_final_delivery_check_v1.py` is a superseded historical checker. It
predates the September evidence and fails on stale August report and nested-
manifest assumptions, so its result is not a V10 acceptance signal. The sole
governing release status is the new fail-closed package verification at
`deliverables/current/2026-09-02_v10/verification/V10_STATUS.json`, produced by:

```bash
python3 scripts/package_final_closeout_v10.py \
  --expected-source-revision "$(git rev-parse HEAD)"
```

This report does not claim that package verification passes before that status
file has been generated successfully.

## Controlled evidence basis

- `reports/final_team_decision_report_2026-08-31/HeiQ_XMembrane_Final_Result_and_Decision_Report_2026-08-31_v9.tex` — preserved historical V9 decision report.
- `docs/CAPACITIVE_ELECTRODE_TRANSIENT_STUDY_2026-09-01.md` and `outputs/capacitive_electrode_study_v1/` — transient electrode model, replay registers and audit.
- `outputs/direct_active_erv_tw50_d1e10_v1/study/` — combined synthetic sensitivity run and audit.
- `outputs/integrated_evidence_v1/material_data_requirements.csv` — current MAT-01–MAT-09 qualification schema.
- `src/heiq/wp1/axial/local_state.py`, `src/heiq/wp1/airside/properties.py` and `heiq_pre_receiver_material_analyses/heiq_pre_receiver_model.py` — local voltage/current and gas-film model basis.
- `source_manifest.json` in this directory — SHA-256 bindings for this release and its decision-critical sources.

---

**End of controlled Version 10 closeout.** V9 and earlier files remain
available as historical provenance. V10 governs current project decisions.
