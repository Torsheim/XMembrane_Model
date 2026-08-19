# WP1 model portfolio and research log

This is the living record for the WP1 modelling programme.
It must be updated when a new model, comparison or verified
result is added.

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

## Confirmed findings

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

A new hard limit of 21.0 A/m² makes this selected point
infeasible by 0.224 A/m². It must be reoptimized rather than
rounded into compliance. The older material screen used a
much looser 2000 A/m² screening gate.

The active continuation, bottleneck and direct-liquid
workflows now default to 21.0 A/m² and propagate that value
into the local axial solver before integration and candidate
selection. The retained 2000 A/m² configuration is historical
reference data, not the active engineering design gate.

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

## Planned sequence

1. Enforce the 21 A/m² gate and rerun feasible O30 designs.
2. Preserve a true passive or zero-current O50 reference.
3. Compare coupled gas, saturation-drain and direct-liquid
   receiver boundaries.
4. Add liquid heat-rejection and drainage sensitivities.
5. Run diffusivity cases including 1e-10 and 1e-9 m²/s and
   a sourced Nafion case.
6. Optimize membrane length, width and channel depth jointly.
7. Validate a separate modern AC+ERV reference.
8. Solve EO+ERV topology and incremental 10% cases.
9. Close the full FOM and energy ledger.

## Run log

| Date | Commit | Study | Result | Claim level |
|---|---|---|---|---|
| 2026-08-19 | this commit | Boundary contracts | Initial portfolio and gates encoded | Contract only |
| 2026-08-19 | current commit | 21 A/m² workflow gate | 17/74 reduced-grid cases passed; cap propagated before candidate selection. Validation smoke only, not a feasibility conclusion. | Engineering-gate validation |

## Open questions

- Is 21.0 A/m² a hard local limit for every architecture or
  only the selected prearchitecture design?
- Which measured Nafion diffusivity dataset and hydration
  condition should define the reference case?
- Where does phase change occur in a direct-liquid design?
- What heat sink and rejection COP are physically available?
- Which exhaust fraction is allocated to ERV versus an EO
  gas receiver?
- Which ERV product class and certified operating point
  should define the industry comparison?
