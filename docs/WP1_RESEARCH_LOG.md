# WP1 model portfolio and research log

This is the chronological record for the WP1 modelling programme. The V10
closeout report governs current interpretation; earlier decisions, gates, and
planned next steps below are retained to show how the work evolved. New work
after V10 belongs to a separately versioned successor-phase supplement.

## Purpose

The repository contains several different studies. They do
not all use an ERV and they do not all support full-system
energy claims.

Every reported result must identify:

- study ID and model boundary;
- inlet and delivered-air conditions;
- conserved dry-air flow;
- receiver architecture;
- HVAC reference, if applicable;
- membrane area, voltage and maximum local current density;
- all known power contributions;
- omitted physics and loads;
- whether the result is mechanistic, an upper bound,
  conditional or a closed full-system comparison.

## Study portfolio

| Study ID | Question | ERV |
|---|---|---:|
| `gross_no_erv_o80_to_o30` | Gross free-predrying opportunity | No |
| `eo_gas_receiver_no_erv` | Coupled gas-receiver EO core | No |
| `eo_saturation_drain_no_erv` | Gas saturation followed by liquid drain | No |
| `eo_direct_pure_liquid_no_erv` | Direct pure-liquid receiver | No |
| `eo_low_activity_liquid_no_erv` | Sorbent or low-activity liquid | No |
| `material_transport_mechanisms` | Material and transport sensitivities | No |
| `module_geometry` | Width, length, gap, films and fan work | No |
| `modern_ac_erv_reference` | Modern conventional AC+ERV reference | Yes |
| `eo_erv_hybrid` | Incremental EO benefit beyond ERV | Yes |
| `direct_eo_in_erv` | Active EO transport within the ERV core | Yes |
| `direct_erv_gradient_closure` | Film, gradient, and signed-polarity audit of frozen direct-ERV cases | Yes |
| `capacitive_electrode_transient` | Reduced-order duration and cycle response of blocking capacitive electrodes | Yes |
| `eo_vapour_coupon_cell` | Selected controlled-flow cell and measurement envelope | N/A |

## Findings recorded before V10

### Equal-service no-ERV comparison

Reported O80 and O30 normalized compressor powers are
1167.33 kW and 382.44 kW. The gross opportunity is therefore
784.89 kW.

At 4365.92 kg/h predryer water removal:

- conditional gross break-even: 179.78 Wh/L approximately;
- reported EO prearchitecture core: 115.02 kW;
- reported core SEC: 26.34 Wh/L approximately;
- remaining conditional no-ERV margin: 669.87 kW;
- remaining margin: 153.43 Wh/L approximately.

The 179.78 Wh/L value is not a universal or thermodynamic
break-even. It depends on the no-ERV comparator, design
conditions, downstream model and omitted auxiliary loads.

Source: `HeiQ_Terminal1_2_Results_and_Discussion_v2`,
principally pp. 28–29.

### Selected O30 prearchitecture point

The selected point reports:

- active area: 8922.21 m²;
- terminal voltage: 0.98 V;
- maximum local current density: 21.224 A/m²;
- receiver/process dry-air ratio: 2.5375;
- receiver airflow: 373339 cfm;
- EO grid power: 70.69 kW;
- process fan: 6.16 kW;
- receiver fan: 38.17 kW.

The 21.224 A/m² value is a reported operating diagnostic. The
temporary 21.0 A/m² workflow gate was subsequently withdrawn after
confirmation that no such design limit applies to this study. Current
density must remain visible for electrode, bus and durability design, but it
is not an acceptance ceiling in the present exploratory phase.

### Liquid receiver interpretation

Pure liquid water has activity approximately one. It is not
a dry thermodynamic sink. Direct transport from process air
with activity below one to pure liquid water is uphill in
water chemical potential.

A liquid receiver may still improve total performance by
eliminating receiver airflow, ducts and receiver-fan power.
The correct comparison is therefore higher cell work versus
lower system auxiliaries.

Saturation-triggered drainage and direct pure-liquid contact
are distinct architectures. A liquid with activity below one
is a sorbent or solution and requires a regeneration ledger.

Unresolved liquid-receiver physics includes:

- liquid-film mass transfer;
- nucleation and phase location;
- wetting, wicking and capillary pressure;
- flooding and drainage geometry;
- wet-electrode kinetics;
- electrolysis and corrosion;
- conjugate thermal behaviour;
- heat rejection.

At the reported O30 water rate, full vapour-to-liquid latent
heat is of order 3 MW thermal. Gravity drainage does not
eliminate this thermal duty.

Source: `HeiQ_Theory_and_Methods_Report`, Chapter 13.

### ERV boundary

ERV is a separate system-comparison layer. It is not part of
material, transport, receiver or module-geometry studies.

Modern AC+ERV and EO+ERV comparisons must enforce one
declared exhaust resource. Building exhaust cannot be fully
credited to both the ERV and the EO receiver.

Generic annual whole-building ERV saving percentages are not
direct validation of a design-point model. Validation should
use sensible and latent effectiveness, airflow, pressure
drop, leakage and fan/wheel electricity under equal inlet
conditions.

Source: `HeiQ_Theory_and_Methods_Report`, Chapter 14.

## Required power ledger

The canonical electrical ledger currently distinguishes:

- downstream HVAC;
- EO grid power;
- process fan;
- receiver fan;
- ERV fans;
- ERV wheel motor;
- liquid pump;
- heat rejection;
- receiver regeneration;
- other auxiliaries;
- upstream electrical losses.

Missing values must remain missing. They must not silently
become zero. A full-system total requires every component to
be either quantified or explicitly declared not applicable.

## Further 10 percent reduction

The phrase is ambiguous. Future inverse calculations must
report separately:

1. 10% relative reduction from ERV-only total grid power;
2. an additional 10 percentage points of saving relative to
   the original reference;
3. a 10-RH-percentage-point reduction when that physical
   target is requested.

Required outputs are additional water transport, outlet
humidity ratio, area, local and integrated current, voltage,
EO power, complete incremental power and marginal Wh/L.

## Closeout disposition

The numerical sequence was completed or superseded during the August and
September studies. The model phase closed in V10 on 2026-09-02. The successor
phase is experimental: measure the complete material-property vector on the
same sample, demonstrate a sustained electrode mechanism, run the selected
controlled-flow vapour coupon cell, and use those measurements to qualify the
module and full energy ledger.

## Run log

| Date | Commit | Study | Result | Claim level |
|---|---|---|---|---|
| 2026-08-19 | this commit | Boundary contracts | Initial portfolio and gates encoded | Contract only |
| 2026-08-19 | current commit | 21 A/m² workflow gate | 17/74 reduced-grid cases passed; cap propagated before candidate selection. Validation smoke only, not a feasibility conclusion. | Engineering-gate validation |
| 2026-08-26 | pending commit | System-closure gate audit | Superseded after confirmation that 21 A/m2 is not a design limit; closure outputs require regeneration without that gate. | Superseded contract audit |
| 2026-08-26 | pending commit | O30 nonlinear required area at 1.0 V | All eight fixed-basis receiver points reached target at 10499.7-12139.9 m2; R=3 step-halving result 10499.6770 m2. | Local model-conditioned area curve |
| 2026-08-31 | pending commit | Direct-ERV gradient and signed-triplet closure | O30 bulk driving is favourable but finite films reverse the selected surface gradient; 1.137x common film/area factor restores zero margin. Full duty is pinched at zero bulk margin. Matched +J/0/-J gives only 0.348 ppm incremental O30 rectification and zero at full duty. | Final steady-model closure; transient AC remains experimental |
| 2026-09-01 | V10 source revision | Capacitive-electrode transient screen | Blocking DC supplies finite startup displacement; the modelled symmetric cycle has zero net EO transport. Capacitance and leakage remain unmeasured sensitivity coordinates. | Reduced-order transient qualification |
| 2026-09-02 | `805ae087` | V10 final project closeout | Release `XMEMBRANE-2026-09-02-V10` passed its evidence, archive, report, scientific-audit, and reconstructed-test gates. | Governing model-phase closeout |
| 2026-09-03 | post-V10 working tree | Cell and presentation handoff material | Selected coupon-cell dimensioning and current V10-aligned presentation assigned to `2026-09-03_handoff_v1`. | Successor-phase handoff aid |

## Questions handed to the successor phase

- Which sustained electrode mechanism operates over the required duty and
  lifetime?
- What coupled sorption, diffusivity, conductivity, drag, thickness, swelling,
  and conditioning vector is measured on each candidate sample?
- What net water-transfer signal, blank, leakage, film response, and electrode
  inventory are measured in the selected vapour coupon cell?
- What core pressure drop, sensible/latent coupling, heat rejection,
  auxiliaries, durability, safety, manufacturability, and cost are measured at
  module scale?
- Which certified ERV operating point defines the equal-service reference?

## 2026-08-21 — Canonical replay of legacy geometry finalists

The two post-filtered legacy geometry candidates were replayed
through the native canonical transport, receiver, engineering and
stack calculation path.

### Numerical equivalence

Both candidate-geometry rows reproduce their corresponding legacy
rows within a relative tolerance of 1e-6. The observed maximum
relative errors were approximately 1.5e-16 for O30 case 94 and
1.7e-16 for O50 case 310. The legacy-to-canonical migration is
therefore not the source of the reported performance differences.

### Gate decisions

- O30 case 94 passes the native analysis, stack, 9000 m2 area and
  21 A/m2 current-density gates. It requires 1.26356 V and therefore
  fails the declared 1.0 V per-cell limit. It is not an accepted
  all-gates design.
- The zero and NaN fields from the O30 default-geometry replay
  represent a failed solve, not a physical zero-power solution.
- O50 case 310 passes all currently declared model gates at
  0.343 V, 7757.25 m2 and 6.768 A/m2.

### Controlled O50 geometry comparison

At identical material, voltage and receiver operating state, moving
from the canonical default geometry to legacy case 310 changes:

- active area by +99.98 percent;
- maximum current density by -50.00 percent;
- combined process and receiver fan power from
  8.768 to 0.715 kW
  (-91.84 percent);
- analysis core power from
  23.755 to
  15.702 kW
  (-33.90 percent);
- EO grid power remains approximately 14.99 kW.

This demonstrates a geometry trade-off: additional active area and
parallel flow capacity reduce current loading and auxiliary fan
power, while the EO transport work remains nearly unchanged at the
fixed operating point.

### Decision

O50 case 310 is retained as a valid geometry hypothesis, not as a
hardware-validated optimum. O30 case 94 must not be used as an
accepted design or system-savings case unless the 1.0 V contract is
explicitly changed. The next calculation task is a new constrained
canonical O30 search with voltage <= 1.0 V, current density
<= 21 A/m2 and active area <= 9000 m2.

## 2026-08-21 — O30 one-volt receiver-capacity boundary

A local canonical gas-receiver scan tested the legacy O30 case-94
material and geometry at 0.8, 0.9 and 1.0 V and eight receiver
capacity multipliers from 1.01 to 3.0. The hard limits were 1.0 V,
21 A/m2 and 9000 m2.

### Result

No point passed all declared gates. All 24 points ended with
`area_limit_before_target`: the integration reached 9000 m2 before
the O30 process-air target was reached. The stored `area_gate_pass`
value only confirms that the recorded area does not exceed the cap;
it does not imply that the target was achieved.

The corrected nearest point was 1.0 V and receiver multiplier 3.0.
It achieved 97.0337 percent of the required
water removal, transferring
4236.411 kg/h and
leaving 129.507 kg/h unresolved. Maximum current
density was
18.758 A/m2,
so the 21 A/m2 gate was not the active limitation.

The nearest point required a receiver/process dry-air ratio of
7.537
and approximately
1108927 cfm receiver
air. Analysis core power was
73.420 kW.

At 1.0 V, increasing the receiver multiplier from 1.01 to 3.0
improved achieved removal from
92.7313 to
97.0337 percent, while increasing the
receiver/process dry-air ratio from
2.537
to
7.537
and core power from
67.964 to
73.420 kW.

A proportional area diagnostic gives approximately
9275.1 m2 for the nearest point. This is not an exact
required area and must not be reported as a solved design because
the coupled transport problem is nonlinear.

### Interpretation and decision

Brute-force receiver-air scaling gives diminishing returns and
worsens the previously identified receiver-air bottleneck. It does
not recover a valid O30 design inside the current limits. The next
gas-receiver calculation should therefore investigate geometry or
material improvements at no more than 1.0 V before considering a
larger area contract.

The first postprocessor version ranked failed points by core power
after the formal gate checks and therefore selected 0.8 V / 1.01.
Version 1.1 corrects failed-point ranking by normalized target
shortfall. Raw solver rows were unchanged.

This result applies only to the fixed hypothetical case-94 material
and geometry. It is not a global O30 infeasibility result, a material
validation, a hardware validation or a liquid-receiver result.

## 2026-08-26 — Fail-closed system-closure audit

The Trond system-closure workflow was audited against the active O30
engineering contract. Historical `analysis_pass` is no longer accepted
as sufficient evidence for a current system claim. Reference selection
now separately requires the requested target, target attainment, water
balance, stack feasibility, terminal voltage <= 1.0 V, maximum local
current density <= 21.0 A/m2 and active area <= 9000 m2.

### Gas-reference decision

The retained O30 regression row passes every listed gate except current
density:

- terminal voltage: 0.98 V;
- active area: 8922.21 m2;
- maximum local current density: 21.2238 A/m2;
- current-density excess: 0.2238 A/m2.

It remains available as a diagnostic and numerical regression fixture,
but it is not an accepted system reference. No alternative all-gates O30
gas row is present in the current repository inputs.

Consequently, the workflow now reports the following as not available:

- gas-receiver EO/core SEC;
- incremental ERV+EO water and power requirements;
- combined EO-system power and savings;
- gas-derived annual energy and cost FOMs;
- enclosure capacity claims based on that module.

The conditional gross no-ERV arithmetic remains 180.32 Wh/L because it
depends only on the declared compressor anchors and water duty. The
remaining allowance after an EO core is not reported until a valid core
exists. Missing component values remain missing and are not replaced by
the historical 70.69, 6.16 or 38.17 kW values.

### Liquid local screen

Applying the same 1.0 V, 21.0 A/m2 and 9000 m2 local engineering screen
changes the best full-grid gravity/free-heat-sink point from the earlier
over-current result to:

- liquid activity: 0.60;
- terminal voltage: 0.05 V;
- maximum local current density: 19.521 A/m2;
- uniform-flux area estimate: 3325.21 m2;
- EO plus process-fan power: 5.713 kW.

This is still only a uniform-inlet local screen. Activity 0.60 requires a
regeneration ledger, and the 5.713 kW subtotal assumes a free heat sink.
At the configured heat-rejection COP of 6, the separate modeled heat-
rejection electricity is approximately 490.36 kW. Neither liquid result
is a closed system total or a validated saving.

### Decision

The next gas calculation remains a constrained canonical O30 search over
material and geometry at no more than 1.0 V, 21.0 A/m2 and 9000 m2.
System-level EO and ERV+EO claims stay unavailable until that search finds
an all-gates row. The liquid path requires finite film, phase-change,
drainage, heat-rejection and regeneration closure before promotion beyond
screening level.

## 2026-08-26 — Contract correction and nonlinear O30 required area

The 21 A/m2 value is not a design constraint for this study. The immediately
preceding fail-closed decision is therefore superseded: its rejection of the
historical O30 reference on current density alone must not be used in the final
system conclusion. Current density remains visible as a diagnostic, while any
large finite value passed into the legacy integration API is only a numerical
solver guard.

The earlier 9000 m2 receiver scan was then continued to the actual O30 target
at exactly 1.0 V for the same hypothetical case-94 material and fixed legacy
geometry. The numerical integration ceiling was 15000 m2; it was not a design
cap. The 9000 m2 value was retained only as a comparison line.

### Result

All eight receiver-capacity points from 1.01 through 3.0 reached target and
passed an independent required-area validity contract covering the local
solve, target endpoint, counter-current boundary, water balances, transport
direction, voltage reconstruction, finite power terms and worker status.

Required area decreased monotonically across the tested points from
12139.863 m2 at receiver multiplier 1.01 to 10499.717 m2 at multiplier 3.0.
The latter is 1499.717 m2, or 16.66%, above the 9000 m2 comparison line.
Maximum local current density ranged from 15.264 to 18.758 A/m2 and was not
used for acceptance or ranking.

At multiplier 3.0, step halving from 20 to 10 m2 changed the required area
from 10499.7174 to 10499.6770 m2: 0.0405 m2, or 0.000385%. The practical
fixed-basis result is therefore approximately 10500 m2.

The old proportional indicator of approximately 9275.1 m2 was 13.2% below
the nonlinear target-reaching result. It was optimistic because the final
coupled-transport tail is nonlinear.

### Decision

The curve is an area-airflow-power trade-off, not a single optimum. Moving
from receiver multiplier 1.01 to 3.0 reduces area by 13.51%, but increases
receiver airflow by 197% to approximately 1.109 million cfm and increases
core power by about 3.46% to 76.13 kW. Multiplier 3.0 is the minimum-area
tested point; multiplier 1.01 is the minimum-core-power tested point.

This closes the exact-area question for the fixed local basis. It does not
validate the hypothetical material, close receiver manifolding or identify a
global material/geometry optimum. The next finalization task is to remove the
superseded 21 A/m2 acceptance gate from system-closure selection and regenerate
dependent gas/liquid/system outputs before freezing the final conclusion.

## 2026-08-26 — Cross-workspace evidence integration and full report

The WSL source trees, downloaded HeiQ code archives, audited output packages and six
shared work-chat histories were reviewed together. Chat text was used only to recover
requirements and corrections; numerical claims were tied to named local output files.

### Integrated findings

- The post-ERV additional-10% full study is the primary conditional energy result:
  53.0666 kW / 9.7595% for the best real-film row at 5 A/m2, with 1115.07 m2
  required area and 5.6873 kW bounded add-on power. Full-system claims remain disabled
  and the minimum surface-activity margin is negative.
- The 12-case diffusivity study remains positive in 11 cases. The best margin falls
  from 9.76% at the Terminal-1 diffusivity to 6.11% at 1e-9 m2/s while best-case area
  rises to 4901.68 m2. This is a one-parameter sensitivity, not a candidate-material
  validation.
- Detailed-HVAC/thermal smoke gives 47.9679 kW in the isothermal base row, but the
  deterministic scenario envelope spans -131.957 to +146.387 kW. Five of eight
  scenario corners are positive; this is not a probability model.
- The coupled condensation smoke has one passing counter-current row and no crossflow.
  It produces zero condensate, 441.525 kW sensible condenser duty and -32.779 kW
  coupled saving even with condenser electricity assumed zero.
- The Nafion vapor reference has 8 numerical target rows but 0 rows that both reach
  target and remain within the declared property-correlation domain.
- Historical receiver-regeneration v39 gives -91.579 kW in its 30000-cfm stress row.
  It uses an older hypothetical material/boundary and is retained only as evidence
  that receiver regeneration can erase a gross EO margin.

### Code and system-closure decision

The default `PrearchitectureGates` current-density limit is now `None`. An explicit
current cap remains available only as a named sensitivity. The regenerated
`outputs/trond_system_closure_v2_no_current_gate` package reports a known gas-core
site subtotal of 118.385 kW but holds system saving and FOMs unavailable because heat
rejection and receiver regeneration remain missing.

The canonical `PowerLedger` is now used in the Trond closure workflow. A new
`outputs/integrated_evidence_v1` register records nine studies, modes, audits,
source hashes, headline metrics, the next-study matrix and a nine-row
`material_data_requirements.csv` working template. Smoke outputs remain smoke,
historical current-gated results remain historical, and missing power is never treated
as zero.

### Historical finalization decision at 2026-08-26

At this snapshot, the next numerical work was a detailed-HVAC/thermal run with
an explicit energy ledger and a rankable module/pressure-drop bracket.
Structured material scouting was to proceed in parallel as a data-gap matrix
covering sorption, D(a,T), conductivity/ASR, drag, thickness/swelling,
durability, ion form, and operating compatibility. No candidate was to be
ranked from a single datasheet property.

This dated recommendation was superseded by the V10 selection of direct EO
transport within the ERV core.

## 2026-08-27 — Historical post-ERV full-duty study

The dated full-duty sweep used an ERV outlet of 23.00 °C and 13.215 g/kg, a
7.260 g/kg target, and a water duty of 1689.50 kg/h. It evaluated 480 membrane
cases: 195 reached the target, 185 passed the declared transport and surface
checks, and 7/7 selected cases passed step halving. The reported primary case
required 8376.25 m², 0.881–1.895 V, and 47.94 kW of known EO-grid and fan
power. Its energy result remained conditional because the full engineering and
energy ledger was incomplete.

## 2026-08-27 — Historical EO-percentage sweep

This sweep varied completion of the remaining latent duty. The earlier
“additional 10%” coordinate equals 22.1925% completion on that axis, O30 equals
72.7003%, and the final supply-humidity coordinate equals 100%. At a fixed
Terminal-1 material/current/resistance coordinate, the corresponding active
areas were 1858.5, 6089.1, and 8376.2 m²; maximum terminal voltages were 0.503,
1.314, and 1.895 V. The 720-case run had 306 target-reaching and 289 declared
transport-gate rows, with 12/12 selected cases passing step halving. The energy
results were conditional and did not establish a full-system optimum.

## 2026-08-27 — Historical 1 V design frontier

The sampled 1 V frontier was 76.328125–76.406250% completion. The best sampled
O30 coordinate at or below 1 V used `D=1.597880e-14 m²/s`, `j=0.75 A/m²`,
24,369.97 m², and 0.985815 V, with a negative local surface margin. The audit
reported 1250 primary cases, 1005 target-reaching cases, 1002 declared-gate
cases, and 5/5 step-halving checks. This is retained as historical evidence;
V10 governs the architecture and claim boundary.

## 2026-09-01 — Capacitive-electrode transient closure

The reduced-order transient study applied signed membrane transport to two
blocking capacitive electrodes at fixed bulk activities and finite gas films.
It evaluated blocking DC, symmetric current cycling, interface ESR, diagnostic
leakage, and frozen direct-ERV axial states. Blocking DC produced finite startup
displacement, and the modelled symmetric cycle produced zero net EO transport.
At the unmeasured 5,000 F/m² pair-capacitance coordinate, the original stored
O30 terminal-voltage case (0.025 V) retained 16.2% after one hour, averaged
0.68% over 24 hours, and delivered 0.17 h equivalent full contribution. The
full-duty 0.250 V case gave 16.5%, 0.69%, and 0.17 h respectively. A separate
1.8 V current-commanded replay gave 98.5%/4.6% for O30 and 92.3%/5.0% for full
duty; these are optimistic capacity upper bounds, not same-voltage replays or
electrochemical-window checks. The capacitance and leakage values were
sensitivity coordinates rather than measurements. The result therefore
qualified the steady model interpretation without establishing sustained
operation.

## 2026-09-02 — V10 model-phase closeout

Release `XMEMBRANE-2026-09-02-V10` froze the final English report, governing
evidence, source and result archives, environment inventory, package manifest,
checksums, and verification records. Its declared source revision is
`805ae087a7f3e133444c93f9fbb72856863754bf`. The reconstructed archive passed
275 tests, skipped 39 evidence-dependent tests with recorded reasons, and had
zero failures. `verification/V10_STATUS.json` reports `PASS` and
`publishing_eligible: true`.

V10 closes the model phase and selects direct EO transport within the ERV core
as the architecture for interpretation. The combined `t_w=50`, `D=1e-10 m²/s`
case remains a synthetic conditional sensitivity. Experimental qualification
of the same-sample material vector, sustained electrode mechanism, controlled
vapour-cell signal, module engineering, and full energy ledger is the handoff
to the successor phase.

## 2026-09-03 — Post-V10 handoff supplement

The selected experimental starting point was consolidated as an integrated
sealed vapour cell with two equal 500.0 mL net-free-gas chambers, a 50 mm by
50 mm active region, local 1/2/4 mm gaps (2 mm nominal), and a 5 s-per-segment
ABBA transient sampled every 0.1 s. The authoritative dimensioning document, numerical
handoff evidence, and V10-aligned technical presentation were assigned to the
post-V10 handoff supplement as successor-phase aids. The supplement carries
its own inventory, checksums, and build notes. It does not amend the V10
model-phase release.
