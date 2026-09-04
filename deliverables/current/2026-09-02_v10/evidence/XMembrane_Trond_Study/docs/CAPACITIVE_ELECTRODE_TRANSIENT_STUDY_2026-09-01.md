# Capacitive electrode transient study

**Controlled revision 1.1 — 2 September 2026**

## Decision result

Replacing the former steady electrode assumption with two purely blocking
capacitive electrodes changes the interpretation materially: the electrodes
support only a finite startup water displacement while they charge.  At the
imposed terminal-voltage limit, current then decays toward zero.  Symmetric,
charge-balanced cycling moves water in both directions but gives zero net EO
transport over a complete cycle in the present constant-drag model.

This does not show that capacitive electrodes are unusable.  It shows that a
sustainable device needs a measured mechanism that breaks the charge/water
reversal: a Faradaic or pseudocapacitive pathway, state-dependent
rectification, flow switching, an asymmetric regeneration path, or another
validated cycle architecture.

## Implemented model

The signed local membrane model retains finite source and receiver gas films,
activity-dependent diffusivity and conductivity, passive diffusion, water
polarisation and series ASR.  The capacitive pair adds the state

\[
V_{\mathrm{term}}
=V_{\mathrm{mem}}(j,a_w)+jR_{\mathrm{interface},A}+\eta,
\]

\[
C_{\mathrm{pair},A}\frac{d\eta}{dt}=j-j_F,
\qquad
j_F=\frac{\eta}{R_{\mathrm{leak},A}}.
\]

For two electrodes,

\[
C_{\mathrm{pair},A}
=\left(C_{s,A}^{-1}+C_{r,A}^{-1}\right)^{-1}.
\]

The reference sensitivity assumes 10,000 F/m² for each identical electrode,
or 5,000 F/m² for the effective pair.  This is an unmeasured sensitivity
coordinate, not a selected electrode specification.

The transient solver is current-commanded with an absolute terminal-voltage
clamp.  This must not be confused with the earlier steady axial calculation,
which is voltage controlled.  The frozen ERV replay therefore uses two
explicit electrical boundaries: the original stored terminal voltage is the
primary same-boundary result, while a separate 1.8 V current-commanded ceiling
is retained only as an optimistic upper-bound sensitivity.

## 25 cm² coupon-cell result

At equal inlet activity and with the inverse-design membrane anchor:

| Current command | EO retained after 1 h | EO retained over 24 h |
|---:|---:|---:|
| 0.5 A/m² | 100.0% | 20.8% |
| 1.0 A/m² | 100.0% | 10.4% |
| 5.0 A/m² | 49.7% | 2.1% |

The comparison is against a counterfactual electrode that supports the same
current continuously.  At 1.0 A/m², the blocking cell moves about 420 mg by EO
before saturating at 1.8 V; the calculated current is effectively zero after
24 h.  Lower assumed capacitance shortens this useful startup interval in
direct proportion.

For symmetric square-current cycling from 0.1 mHz to 0.1 Hz, the maximum
full-cycle charge closure error was 1.63e-8 C/m² and the maximum full-cycle EO
water closure error was 3.21e-10 mg.  Net EO is therefore zero to numerical
precision, even though the absolute water shuttled in both directions is
nonzero.

## Dual frozen replay of the stored direct-ERV results

The saved eight-segment O30 and full-duty states were replayed with their
original areas, activities, gas films, temperatures and current-density
commands. Bulk stream states were frozen while current collapsed, so this is a
duration diagnostic rather than a coupled transient ERV solution.

The primary replay retains each case's original terminal-voltage limit:

| Stored direct-ERV case | Applied terminal limit | EO retained after 1 h | EO retained over 24 h | Finite water inventory / original target rate | Maximum pair-capacitor voltage |
|---|---:|---:|---:|---:|---:|
| O30 | 0.025 V | 16.2% | 0.68% | 0.17 h | 0.478 V |
| Full humidity duty | 0.250 V | 16.5% | 0.69% | 0.17 h | 0.250 V |

The separate common-ceiling sensitivity permits terminal voltage to rise far
above the original 0.025 V and 0.250 V cases:

| Stored direct-ERV case | Applied terminal ceiling | EO retained after 1 h | EO retained over 24 h | Finite water inventory / original target rate | Maximum pair-capacitor voltage |
|---|---:|---:|---:|---:|---:|
| O30 optimistic upper bound | 1.800 V | 98.5% | 4.6% | 1.10 h | 2.253 V |
| Full-duty optimistic upper bound | 1.800 V | 92.3% | 5.0% | 1.20 h | 1.800 V |

The former 98.5%/4.6% O30 headline is therefore not a same-voltage replay. It
is the explicitly optimistic 1.8 V ceiling sensitivity. At the original O30
voltage boundary, only 16.2% is retained over the first hour and 0.68% over
24 h. Neither electrical boundary sustains the previously calculated EO duty,
and the earlier HVAC savings must not be applied to long-duration operation
with purely blocking electrodes.

The 1.8 V value constrains terminal voltage only. The model neither resolves
nor constrains individual electrode potentials and imposes no electrode-pair
electrochemical stability window. The pair-capacitor state can consequently
exceed 1.8 V when an assisting water-activity gradient contributes a negative
membrane polarisation voltage; the O30 upper-bound replay reaches 2.253 V. This
is another reason the common-ceiling result is not a design prediction.

## Leakage sensitivity

A finite linear leakage branch sustains current in the model, but that current
is Faradaic by construction.  Such cases require measured reaction kinetics,
products, electrode lifetime and overpotential.  They cannot be labelled
purely capacitive or used as validated energy results.

## Important validity limit

For the anchor thickness and diffusivity,

\[
L^2/D \approx 23.69\ \mathrm{h}.
\]

The electrical electrode state is transient, but the present membrane profile
is quasi-steady.  The AC periods are therefore faster than the characteristic
internal water redistribution time.  Quantitative frequency selection needs a
transient membrane-inventory model, for example

\[
S(a_w)\frac{\partial a_w}{\partial t}
=-\frac{\partial N_w}{\partial x},
\]

coupled to the electrode charge and gas-side balances.

## Required measurements before design use

1. Measure differential capacitance per electrode versus activity, temperature
   and polarisation.
2. Measure EIS and fit ESR plus a CPE or distributed-pore model if a single
   ideal capacitance is inadequate.
3. Measure self-discharge and separate ionic Faradaic current through the
   membrane from external electronic leakage.
4. Measure water transported during both charge and discharge on complete
   cycles, not only the first half-cycle.
5. Record reaction products and electrode voltage separately on both sides,
   and establish the allowed individual and pair electrochemical windows.
6. Only after these data exist, couple the transient membrane inventory and
   dynamic ERV air streams and recalculate system energy.

## Reproduction

```bash
PYTHONPATH=src python3 scripts/run_capacitive_electrode_study_v1.py --overwrite
pytest -q -s tests/test_capacitive_electrode_study_v1.py
```

The generated registers, audit and figures are written to
`outputs/capacitive_electrode_study_v1/`.
