# EO vapour coupon-cell design basis v1

## Decision

Build one modular fixture around a maximum 50 x 50 mm active aperture (25 cm2), then use precision membrane-mask inserts for 40 x 40 mm, 30 x 30 mm, 20 x 20 mm and 8 x 50 mm while retaining the same 50 x 50 mm gas-flow field. The 20 x 20 and 8 x 50 mm pair has equal area but different perimeter. Use two mirrored flow halves with interchangeable 1, 2 and 4 mm channel spacers. The first nominal test uses 2 mm on both sides; gap and flow are validation variables, not fixed nuisance parameters.

The fixture is intended for two distinct experiments:

1. **Steady material characterization:** controlled once-through gas on both sides, fixed measured inlet temperature, water activity, absolute pressure and flow. This is the primary way to estimate net EO transport.
2. **Reversible closed-loop demonstration:** two identical, well-mixed external reservoirs with recirculation, fitted as a transient water-inventory model. This demonstrates pumping and reversal but is not interpreted as fixed-boundary steady flux.

## Starting mechanical dimensions

| Item | Starting value | Acceptance basis |
|---|---:|---|
| Maximum active aperture | 50 x 50 mm | Signal floor and low perimeter/area ratio |
| Smaller apertures | 40 x 40; 30 x 30; 20 x 20; 8 x 50 mm | Area/perimeter separation with a same-area pair |
| Membrane coupon | about 80 x 80 mm | Leaves seal and guard land outside active area |
| Outer fixture | about 110 x 110 mm | Allows double seal, guard port and perimeter bolts |
| Flow frame | 8-10 mm | Ports plus electrical isolation |
| Proposed swept internal volume | 6.22 mL/side | 5.00 mL active + 1.22 mL proposed headers, ports and taps |
| Internal dead-volume limit | <=1.3 mL/side | Measure the assembled value; external tubing is separate |
| External metal load plate | 12 mm | Starting point only; verify under clamp load |
| All-polymer load plate | >=16 mm PEEK | 20 um plate-screen result at 1 MPa equivalent load |
| Gas gap per side | 1, 2, 4 mm | Gas-film and pressure-drop challenge |
| Nominal gap | 2 mm | Aligns with the existing declared channel basis |

Use hard compression stops so the gasket does not define the channel height. The acceptance quantity for plate thickness is measured gap/flatness under the real bolt and gasket load: target bow less than 2% of the smallest gap (20 micrometres for a 1 mm channel) or include the measured nonuniformity in the model. The simply-supported 50 mm square screen gives minimum thicknesses of 15.35 mm PEEK, 5.81 mm Al 6061-T6 and 4.16 mm 316L at a deliberately conservative 1 MPa equivalent uniform load. Gas pressure is not the dominant structural load; gasket and bolt load are, and the equivalent load is not a gasket-contact calculation.

The proposed internal-volume arithmetic uses two 7.5 mm triangular headers (0.750 mL), two 6 mm-ID by 8 mm port bores (0.452 mL), and 0.020 mL pressure-tap volume. Together with the 5.00 mL active channel, this gives 6.222 mL swept volume per side and about 62 ms ideal internal residence at 6 L/min. Measure the actual assembled volume and report fittings, sensor tubing, and instrument volumes separately.

Use double seals outside the active aperture with a vented/tracer guard groove between them. Avoid adhesive in the primary seal. The membrane needs symmetric, high-open-area support/electrode structures; their obstruction and water storage must be tested as part of the cell, not silently assigned to the membrane.

Minimize exposed water-sorbing polymer. Electropolished 316L or another compatible low-sorption wetted surface is preferred where the electrical architecture permits it. PEEK/PVDF can provide necessary insulation, but the complete assembled fixture must be preconditioned and blank-tested. PMMA and 3D-printed polymers are suitable for early fit checks, not the final low-flux metrology surface.

## Boundary-condition strategy

At equal-RH operation, split one conditioned inlet stream into the two cell halves. Do not rely on two independent generators both indicating the same nominal RH. Cross-switch or multiplex the humidity reference so sensor bias is observable. Record temperature close to both membrane surfaces, absolute pressure on both sides and low-range differential pressure across the membrane.

Hold differential pressure within +/-5 Pa for the main test and run separate +/-20 and +/-50 Pa challenges. Adjust the two outlet back-pressure valves rather than assuming equal mass-flow-controller settings imply equal pressure.

Run each material state in both polarities using an ABBA sequence (`+I, -I, -I, +I`) with zero-current periods. The polarity-odd component

`J_odd = [J(+I) - J(-I)] / 2`

is the EO candidate. The polarity-even component exposes drift, heating, passive transport and electrode chemistry. Source loss and receiver gain must be reported separately before they are averaged.

## Required controls

1. Impermeable aluminium-foil blank with the same aperture, gasket, clamp load, temperature, RH, pressure and flow, before and after a test block.
2. Zero-current membrane run at equal boundary activity.
3. Zero-current passive-gradient run in both gradient directions.
4. Independent donor- and receiver-flow sweeps around 0.5x, 1x and 2x nominal flow.
5. Gap sweep at 1, 2 and 4 mm.
6. Aperture sweep and fit of `total rate = area term*A + edge term*perimeter + blank`. The 4/9/25 cm2 square masks alone give zero residual degrees of freedom and strongly confound area with perimeter. Add the 16 cm2 square and the 8 x 50 mm equal-area insert; test the rectangular insert in both flow orientations.
7. Differential-pressure challenges.
8. Electrode/gas analysis sufficient to distinguish transported water from reaction water and Faradaic gas.
9. Reference-film or standard-method comparison at matched temperature and RH.

The foil blank is directly supported by [ASTM E398-24](https://store.astm.org/standards/e398). The proposed blank limit (<10% of the minimum intended signal), flow plateau and mass-balance gates are internal acceptance criteria, not ASTM requirements. Passive WVTR can be cross-checked using the principles of [ASTM E96/E96M-24a](https://store.astm.org/e0096_e0096m-24a.html) or [ISO 9932:2021](https://www.iso.org/standard/80315.html), but these methods do not validate active EO transport.

Gas-film resistance must be demonstrated experimentally. Published work shows that the external boundary resistance can equal or exceed the selective-layer resistance, and that spacers/flow alter the result ([Koester et al.](https://doi.org/10.1016/j.memsci.2015.12.070)). Use a calibrated chilled-mirror/dew-point instrument as the humidity reference, with fast sensors for transients; NIST describes traceable humidity calibration in [SP 250-83r1](https://doi.org/10.6028/NIST.SP.250-83r1).

## Existing project test grid

The current project plan already declares 32 degC, activities 0.30/0.50/0.70/0.80/0.90, current densities 10/25/50/100/200 A/m2 and both polarities for material transport testing. Start below that current grid (0.5-5 A/m2) to locate the signal safely, because the hypothetical inverse-design transport number is about 100 whereas order-unity reference materials can be roughly two orders of magnitude lower.

The calculation now also solves the minimum ideal active area at fixed total flow. At the nominal 6 L/min per side and the declared five-to-one signal/uncertainty gate, the hypothetical inverse-design anchor at 1 A/m2 needs about 6.6 cm2. Covering the lower 0.5 A/m2 anchor point needs about 13.1 cm2, so the existing 40 x 40 mm insert (16 cm2) is the smallest practical insert that covers the full low-current anchor screen. Retain the 50 x 50 mm maximum aperture (25 cm2) because passive cancellation and other nonidealities can only reduce the measured net signal. Order-unity and low-drag references require lower flow or a more sensitive/integrating measurement; minimum areas from the ideal signal model are not validation guarantees.

Do not use a fixed elapsed time as the steady-state definition. The configured 36.9 micrometre membrane gives a characteristic `L2/D` from seconds to roughly one day across the current diffusivity screen. Precondition until inlet/outlet water balances, voltage and membrane rate meet a predeclared drift criterion.

## Run the sizing calculation

```bash
cd /home/torsheim/HeiQ/XMembrane_Trond_Study
python3 scripts/design_eo_vapor_test_cell.py
python3 -m pytest -q -s tests/test_eo_vapor_test_cell_design.py
```

Edit `config/eo_vapor_test_cell_design.json` when the actual sensor uncertainty, flow range, material thickness and expected transport number are known. The calculation writes the fixture and aperture dimensions, internal-volume budget, plate-deflection screen, detectability-versus-flow calculation, channel envelope, gross signal range, closed-loop volume/drift times, edge sensitivity, boundary mismatch sensitivity, membrane time scales, and sizing figure to the compatibility output directory `outputs/eo_vapor_cell_sizing_v1/`.
