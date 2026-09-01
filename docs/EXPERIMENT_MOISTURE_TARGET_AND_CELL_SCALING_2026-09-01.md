# EO vapour experiment: moisture target, cell scaling and reversible cycling

## Decision

Use the 50 x 50 mm maximum active aperture (25 cm2) as the primary EO vapour
coupon.  The building calculation defines a useful net EO target of about
200--250 g/m2/h at no more than 1 V, but this target must be demonstrated in a
controlled gas--membrane--gas experiment.  A once-through experiment measures
sustained transport.  A sealed or closed-loop experiment measures transient
water displacement and reversal; it does not demonstrate continuous removal
because a symmetric complete cycle has zero net EO transport.

The recommended fixture remains the modular design already specified in
`EO_VAPOR_TEST_CELL_DESIGN.md`: 4, 9, 16 and 25 cm2 square apertures, an
additional 4 cm2 rectangular aperture, interchangeable 1/2/4 mm channel gaps,
and a physical membrane coupon of approximately 80 x 80 mm.  The active
aperture, not the physical coupon area, is used in all flux calculations.

## Why the experiment needs a moisture-transport target

The active ERV model contains a large building-scale water balance.  It does
not by itself prove that a membrane has the required vapour-state transport
properties.  The model result must therefore be converted into an
area-normalised experimental target that can be tested on a coupon.

For dry-air mass flow \(\dot m_{da}\) and humidity ratios \(w\), the required
water-transfer rate is

\[
\dot m_w=\dot m_{da}(w_{\mathrm{in}}-w_{\mathrm{target}})3600.
\]

The O30 integrated-ERV case gives the following balance:

| Quantity | O30 value | Interpretation |
|---|---:|---|
| Total transport through the active ERV membrane | 4,365.9 kg/h | Passive plus electrically enhanced transport from the process inlet to O30 |
| Transport supplied by the matched passive ERV | approximately 3,137.6 kg/h | Transport available with EO switched off |
| Additional duty assigned to EO | 1,228.3 kg/h | Incremental duty relative to the same passive ERV |
| Selected active membrane area | 5,899 m2 | Coupled system-sweep result, not a measured material area requirement |
| Average total membrane flux | approximately 740 g/m2/h | 4,365.9 kg/h divided by 5,899 m2 |
| Area-normalised EO increment | approximately 208 g/m2/h | 1,228.3 kg/h divided by 5,899 m2 |

The arithmetic is

\[
J_{\mathrm{total}}=
\frac{4{,}365.9}{5{,}899}
=0.740\ \mathrm{kg\,m^{-2}\,h^{-1}},
\]

\[
J_{\mathrm{EO,equivalent}}=
\frac{1{,}228.3}{5{,}899}
=0.208\ \mathrm{kg\,m^{-2}\,h^{-1}}.
\]

The 208 g/m2/h value is a system-equivalent average.  It is not expected to be
the local flux at every axial position in an ERV.  Local water activity,
temperature, conductivity, current density, gas-film resistance and passive
back-diffusion all vary along the core.  For this reason, use 200--250 g/m2/h
as a coupon-level net EO target rather than claiming that 208 g/m2/h is an
intrinsic membrane constant.

## Relation to transport number and current density

The ideal gross EO water flux used in the material model is

\[
J_{\mathrm{EO,gross}}=t_w\frac{j}{F}M_w,
\]

or, in convenient units,

\[
J_{\mathrm{EO,gross}}
\approx0.672\,t_wj
\quad\mathrm{g\,m^{-2}\,h^{-1}},
\]

where \(t_w\) is mol water per mol elementary charge and \(j\) is in A/m2.
The relationship is a gross Faradaic mapping.  It does not subtract passive
diffusion, gas-film losses, leakage, electrode water storage or reaction water.

| Assumed \(t_w\) | Gross flux at 10 A/m2 |
|---:|---:|
| 10 | 67 g/m2/h |
| 20 | 134 g/m2/h |
| 30 | 202 g/m2/h |
| 50 | 336 g/m2/h |
| 75 | 504 g/m2/h |
| 100 | 672 g/m2/h |

The ideal 208 g/m2/h system-equivalent target corresponds to

\[
t_wj\approx310\ \mathrm{A/m^2}.
\]

Examples are \(t_w=50\) at 6.2 A/m2, \(t_w=30\) at 10.3 A/m2 and
\(t_w=20\) at 15.5 A/m2.  A real experiment may require a higher product
because the net measured flux is the gross EO contribution minus opposing
transport and artefacts.  Values such as \(t_w=50\) are inverse-design
coordinates until measured under the relevant vapour conditions.

## Coupon water rate for a given active area

For a uniform net flux \(J\) and active area \(A\), the measurable water rate is

\[
\dot m=JA.
\]

The following rates show both the 208 g/m2/h system-equivalent EO target and
the ideal 336 g/m2/h gross flux for \(t_w=50\), \(j=10\) A/m2.

| Active aperture | Area | Rate at 208 g/m2/h | Rate at 336 g/m2/h |
|---|---:|---:|---:|
| 20 x 20 mm | 4 cm2 | 0.083 g/h = 0.023 mg/s | 0.134 g/h = 0.037 mg/s |
| 30 x 30 mm | 9 cm2 | 0.187 g/h = 0.052 mg/s | 0.302 g/h = 0.084 mg/s |
| 40 x 40 mm | 16 cm2 | 0.333 g/h = 0.092 mg/s | 0.538 g/h = 0.149 mg/s |
| 50 x 50 mm | 25 cm2 | 0.520 g/h = 0.144 mg/s | 0.840 g/h = 0.233 mg/s |

The 25 cm2 aperture gives the largest absolute signal and the smallest
perimeter-to-area ratio.  The smaller masks test whether the measured rate
scales with area.  The equal-area square and rectangular masks separate an
area-controlled membrane signal from seal, edge and flow-distribution effects.
Fit the aperture sweep to

\[
\dot m_{\mathrm{measured}}=J_AA+k_PP+\dot m_{\mathrm{blank}},
\]

where \(P\) is aperture perimeter.  A credible membrane result should be
dominated by the \(J_AA\) term rather than the perimeter or blank terms.

## Why the maximum active aperture is 25 cm2

The cell-size calculation does not assume that a larger coupon automatically
produces better membrane physics.  It asks what active area is needed to create
a resolvable change in two gas streams at fixed flow.

The declared sizing state is 32 degC, 101,325 Pa, inlet water activity 0.50 and
6 L/min per side.  Each humidity channel has an expanded uncertainty of 0.1 RH
percentage point.  The two-channel combined uncertainty is

\[
u_{\Delta RH}=\sqrt{0.1^2+0.1^2}=0.141\ \text{RH percentage point}.
\]

The five-to-one signal criterion therefore requires approximately

\[
\Delta RH_{\mathrm{required}}=5u_{\Delta RH}=0.707
\ \text{RH percentage point}.
\]

At fixed total gas flow, the ideal humidity signal scales approximately with
\(t_wjA/\dot V\).  The calculation converts EO water rate into the outlet
humidity-ratio and RH difference at the declared temperature and pressure,
then solves for the area that produces the 0.707-point differential signal.

| Gross-signal case at 6 L/min per side | Minimum ideal area | Smallest practical insert |
|---|---:|---:|
| Inverse-design anchor, 0.5 A/m2 | 13.09 cm2 | 16 cm2 |
| Inverse-design anchor, 1.0 A/m2 | 6.55 cm2 | 9 cm2 |
| Selected direct-active ERV profile minimum, 1.242 A/m2 | 5.27 cm2 | 9 cm2 |
| Selected direct-active ERV profile maximum, 3.366 A/m2 | 1.94 cm2 | 4 cm2 |
| Order-unity \(t_w=1\), 10 A/m2 | 65.5 cm2 | Does not fit at 6 L/min |
| Low-drag \(t_w=0.3\), 10 A/m2 | 218 cm2 | Does not fit at 6 L/min |

These are ideal detectability floors, not predictions of net membrane
performance.  For an order-unity material, retain the 25 cm2 fixture but lower
the gas flow or use an integrating water measurement.  At 25 cm2 the existing
screen gives maximum ideal flows of approximately 2.29 L/min for \(t_w=1\)
and 0.69 L/min for \(t_w=0.3\) at 10 A/m2.  Low-flow signal acquisition and
high-flow gas-film characterisation should therefore be separate test modes.

## Channel, coupon and fixture dimensions

| Item | Starting value | Calculation or purpose |
|---|---:|---|
| Maximum active aperture | 50 x 50 mm = 25 cm2 | Detectability margin and low perimeter/area ratio |
| Physical membrane coupon | approximately 80 x 80 mm | Space for double seals, guard groove and clamping |
| Outer fixture | approximately 110 x 110 mm | Ports, bolts, seals and electrical isolation |
| Nominal channel gap | 2 mm per side | Matches the declared ERV local-channel basis |
| Gap sensitivity | 1, 2 and 4 mm | Tests gas-film and pressure-drop effects |
| Active gas volume at 25 cm2 and 2 mm | 5.00 mL per side | \(25\ \mathrm{cm^2}\times0.2\ \mathrm{cm}\) |
| Headers, ports and pressure taps | 1.222 mL per side | Proposed geometric allowance |
| Total swept internal volume | 6.222 mL per side | Active channel plus internal dead volume |
| Ideal residence at 6 L/min | 62 ms | 6.222 mL divided by 100 mL/s |
| Main differential pressure | within +/-5 Pa | Suppresses hydraulic water transport |

The gas gap must be fixed by hard mechanical stops rather than gasket
compression.  For the 1 mm gap, the target plate bow is less than 20 um, or the
measured nonuniformity must be included in the analysis.  The existing
small-deflection screen gives minimum thicknesses of 15.35 mm PEEK, 5.81 mm
Al 6061-T6 and 4.16 mm 316L at a deliberately conservative 1 MPa equivalent
uniform load.  These values screen plate stiffness; the equivalent load is not
a calculated gasket contact pressure.  Final acceptance requires measured
flatness under the actual bolt, gasket, hard-stop and electrode stack.

## Reversible fluctuation without through-flow

For a sealed or recirculating cell, reversing the current reverses the EO water
direction.  At constant flux, the water shifted during one half-cycle is

\[
\Delta m_{\mathrm{half}}=JA\Delta t
=\frac{JA}{2f},
\]

where \(f\) is the full-cycle frequency.  For the 25 cm2 aperture and the
208 g/m2/h target, \(JA=0.520\) g/h = 0.144 mg/s.

| Full-cycle frequency | Half-cycle duration | Ideal water shifted in one direction |
|---:|---:|---:|
| 0.1 Hz | 5 s | 0.72 mg |
| 0.01 Hz | 50 s | 7.2 mg |
| 0.001 Hz | 500 s | 72 mg |
| 0.0001 Hz | 5,000 s | 722 mg |

At the 336 g/m2/h gross reference, multiply these values by 1.615.  For
example, the 25 cm2 coupon ideally shifts 0.233 mg/s, 14.0 mg/min or 140 mg in
a ten-minute half-cycle.

These linear values apply only while the imposed current and boundary states
remain available.  They do not account for chamber humidity drift, membrane
inventory, back-diffusion or electrode charging.  They must therefore be
treated as initial-rate or command-rate calculations rather than guaranteed
cycle amplitudes.

## Closed-cell water inventory and humidity drift

The swept internal gas volume is small.  At 25--32 degC, 6.222 mL of gas holds
only approximately 0.1--0.2 mg of water vapour over the full 0--100% RH span.
At the target coupon rate of 0.144 mg/s, the internal chamber humidity can
therefore change materially in about one second if no external reservoir,
sorbent or condensation capacity is present.

This is not an instrumentation detail.  The growing activity difference
creates passive back-diffusion that opposes EO.  A closed experiment must
include the measured volumes and water capacities of tubing, sensors,
reservoirs, electrodes, supports and chamber surfaces in a transient inventory
model.  Water-sorbing polymers can dominate the apparent response and must be
blank-tested and preconditioned.

For a symmetric polarity cycle in the current constant-drag model,

\[
\boxed{\text{net EO water transport over one complete cycle}=0.}
\]

The absolute water shuttled is nonzero, but the second half-cycle returns the
EO displacement.  Such a test demonstrates directionality, reversibility and
transient storage.  It does not demonstrate continuous building
dehumidification unless the cycle contains a measured rectification,
flow-switching, condensation, asymmetric regeneration or other mechanism that
prevents the transported water from simply returning.

## Capacitive-electrode limit

Two purely blocking capacitive electrodes support only a finite charge before
the terminal-voltage limit is reached.  For effective pair capacitance per area
\(C_{\mathrm{pair},A}\), active area \(A\), voltage swing \(\Delta V\) and
transport number \(t_w\), the ideal finite EO displacement is

\[
m_{\max}=t_w\frac{M_w}{F}C_{\mathrm{pair},A}A\Delta V.
\]

The reference sensitivity assumes 10,000 F/m2 for each identical electrode,
equivalent to 5,000 F/m2 for the series pair.  For the 25 cm2 coupon,
\(t_w\approx100\) and a 1.8 V terminal limit, the transient model gives about
420 mg of EO displacement before current collapses.  At \(t_w=50\), the same
ideal scaling gives approximately 210 mg.  Lower capacitance, transport number,
area or voltage reduces this inventory linearly.

This capacitance is an unmeasured sensitivity coordinate.  A real electrode
requires measured differential capacitance, ESR/CPE behaviour, self-discharge,
Faradaic leakage, products and separate electrode potentials.  A leakage path
that sustains current is Faradaic by definition and cannot be labelled purely
capacitive.

## Sensitivity interpretation

| Variable increased | First-order result | Important limitation |
|---|---|---|
| Active area \(A\) | Water rate and capacitive inventory increase linearly | Edge leakage, pressure distribution and current uniformity may not scale linearly |
| Transport number \(t_w\) | Gross EO flux and charge-normalised displacement increase linearly | Must be measured in vapour; liquid values are not directly transferable |
| Current density \(j\) | Initial gross EO flux increases linearly | Voltage, heating, concentration polarisation and reactions may increase nonlinearly |
| Half-cycle duration | Ideal displacement per half-cycle increases linearly | Chamber and electrode saturation eventually stop the linear increase |
| Cycling frequency | Displacement per half-cycle decreases as \(1/f\) | Very fast cycling can probe electrode rather than membrane redistribution |
| Electrode capacitance | Available blocking-electrode displacement increases linearly | Does not create nonzero net transport over a symmetric full cycle |
| Gas flow | Outlet humidity signal decreases at fixed water rate | Higher flow can reduce film resistance and improve boundary control |
| Channel gap | Changes velocity, gas volume, films and pressure drop | Must be measured through the declared 1/2/4 mm sweep |
| Water diffusivity | Can accelerate internal equilibration and passive flux | Higher passive back-diffusion can reduce the observable EO increment |

The membrane redistribution scale is approximately \(L^2/D\).  For the
36.9-um reference membrane it ranges from seconds to roughly one day across
the current diffusivity screen.  Do not define steady state using one fixed
elapsed time.  Require stable voltage and closed donor/receiver water balances
under a predeclared drift criterion.

## Recommended experimental sequence

1. Perform impermeable-foil and zero-current blanks with every aperture.
2. Use once-through gas at equal inlet activity and low current to establish a
   measurable polarity-odd signal.
3. Run both polarities in an ABBA sequence and calculate
   \(J_{\mathrm{odd}}=[J(+I)-J(-I)]/2\).
4. Confirm donor loss and receiver gain independently before averaging them.
5. Repeat the 4/9/16/25 cm2 aperture sweep and fit area, perimeter and blank
   terms.
6. Sweep gas flow separately from the 1/2/4 mm gap sweep to expose film
   limitations.
7. Only after the steady polarity-dependent rate is established, operate the
   cell as two closed, well-mixed reservoirs and measure water displacement in
   both half-cycles.
8. Report initial rate, half-cycle displacement, peak-to-peak water inventory,
   full-cycle closure and voltage/charge closure.  Do not report absolute
   shuttled water as net dehumidification.

## Experimental acceptance quantities

The main material-screening result should contain all of the following:

- net polarity-odd EO flux in g/m2/h;
- effective \(t_w=FJ_{\mathrm{odd}}/(jM_w)\) versus activity, temperature and
  current density;
- conductivity or area-specific resistance under the same vapour state;
- passive water flux at zero current and under both gradient directions;
- donor/receiver water-balance closure;
- voltage, current, charge and energy per transported water mass;
- aperture, perimeter, gap, flow, pressure and blank sensitivities;
- closed-loop water inventory and complete-cycle closure where cycling is used.

A practical first success criterion is a repeatable polarity-odd net flux of at
least 200--250 g/m2/h below 1 V, with source loss matching receiver gain and
with the signal dominated by active area rather than perimeter or blank terms.
Failure to reach that target is still useful: the measured \(t_w\),
conductivity, passive back-diffusion and voltage identify which system-level
assumption must be revised.

## Claim boundary

The 200--250 g/m2/h value is a conditional target derived from the selected
O30 system model.  The 25 cm2 aperture is an experimentally motivated signal
and artefact-control choice.  Neither quantity validates a membrane material,
electrode, receiver or commercial ERV design.

Steady once-through measurements can test sustained EO transport under fixed
gas boundaries.  Closed-loop oscillation can test transient water shuttling
and reversibility.  Purely symmetric oscillation without through-flow,
rectification or water removal cannot provide sustained net dehumidification,
irrespective of how large the instantaneous flux appears.

## Reproduction and linked evidence

Run the existing sizing and transient calculations with:

```bash
python3 scripts/design_eo_vapor_test_cell.py
PYTHONPATH=src python3 scripts/run_capacitive_electrode_study_v1.py --overwrite
pytest -q -s tests/test_eo_vapor_test_cell_design.py
pytest -q -s tests/test_capacitive_electrode_study_v1.py
```

The detailed mechanical and metrology basis is in
`docs/EO_VAPOR_TEST_CELL_DESIGN.md`.  The minimum-area and ERV similarity check
is in `docs/TEST_CELL_AND_ERV_SCALE_CHECK_2026-09-01.md`.  The blocking-electrode
and cycle-closure analysis is in
`docs/CAPACITIVE_ELECTRODE_TRANSIENT_STUDY_2026-09-01.md`.  The nonlinear O30
water-transfer result is documented in `docs/O30_REQUIRED_AREA_1V_v1.md`.
