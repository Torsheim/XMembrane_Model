# EO vapour coupon-cell sizing v1

## Recommended starting fixture

- Maximum active aperture: **50 x 50 mm (25 cm2)**, with masks for 30 x 30 mm and 20 x 20 mm.
- Membrane coupon: approximately **80 x 80 mm**.
- Outer fixture: approximately **110 x 110 mm**.
- Interchangeable symmetric gaps: **1, 2 and 4 mm**; use **2 mm** as the first nominal case.
- Starting structural stack: **8-10 mm insulating flow frames** plus **12 mm metal backing/load plates**. If the load-bearing plate itself is PEEK, start at **16 mm**. Accept either only after measuring loaded gap and flatness under the real gasket/bolt load.
- Use continuous, controlled gas flow for steady transport measurements. Treat a closed loop as a separate transient experiment.

The 80 mm coupon leaves 15 mm per side outside the 50 mm aperture. A 3 mm inner seal, 2 mm guarded groove and 3 mm outer seal use 8 mm, leaving 7 mm of unallocated land before the coupon edge. The outer 110 mm plate leaves a further 15 mm per side for bolts and ports.

At 25 cm2, 2 mm gap and 1 m/s, each side needs 6.00 actual L/min, contains 5.00 mL in the active channel, has Re about 236, and the ideal straight-channel pressure drop is only 2.9 Pa. The exposed non-membrane surface in the ideal rectangular chamber is 29.0 cm2 per side (1.16 times the membrane area). The proposed two tapered headers, two port bores and pressure taps add 1.22 mL, giving 6.22 mL total swept internal volume and 62 ms residence at 6 L/min. The acceptance target is no more than 1.3 mL internal dead volume per side; measure the actual assembled volume.

The plate screen limits bow to 20 micrometres, or 2% of the 1 mm gap, across a 50 mm unsupported square. Gas pressure at 50 Pa alone requires less than 0.6 mm even for PEEK and is not the governing load. Under the deliberately conservative 1 MPa equivalent-uniform fixture-load surrogate, the calculated minimum thicknesses are 15.4 mm PEEK, 5.8 mm aluminium and 4.2 mm 316L. The surrogate is not a gasket-contact model; the assembled cell still needs a torque/flatness map.

## Signal envelope (gross EO only)

For order-unity transport-number scenarios, the 25 cm2 screen spans 5.04-840.2 mg/h over the declared current grid. The hypothetical inverse-design anchor spans 84.1-840.7 mg/h over its lower-current grid. These are not net-flux predictions.

With 0.1 RH-percentage-point expanded uncertainty for each humidity channel and a declared signal/uncertainty gate of five, the ideal gross-signal calculation limits flow to 0.69 L/min per side for the 5.04 mg/h low-drag floor and 2.29 L/min per side for the 16.80 mg/h order-unity reference. Both are below the 6 L/min film-characterisation baseline. Low-flow signal acquisition and high-flow film testing must therefore be separate modes unless a more sensitive or integrating water measurement is used.

To keep an unbuffered closed-loop boundary within 1 RH percentage point for one hour, the order-unity 25 cm2 cases would require approximately 14.9-2487 L of ideal gas inventory per side. This is why a shallow sealed chamber cannot represent fixed-RH steady state.

For the 5.04 mg/h gas-only reference, the 5 mL active chamber reaches 5 Pa in 0.063 s. A 5 L reservoir per side (equivalent cube side 17.1 cm) extends this only to 63.4 s and takes 20.1 min for a one-RH-percentage-point change per side. Closed operation therefore requires pressure-balancing compliance or active volume control and a transient inventory fit.

Gas residence time is not a membrane steady-state criterion. At the slowest hypothetical diffusivity in the configured screen, L2/D is 23.7 h and the declared preconditioning screen is 94.8 h. Use measured drift and mass-balance stability for acceptance.

Equal-RH work needs a common inlet, not merely two nominally equal sensor readings. In the configured high-diffusivity screen, a 0.1 RH-percentage-point mismatch produces 4.39 mg/h on 25 cm2, or 87% of the gross n=1, j=3 EO reference signal.

## Interpretation gates

1. An impermeable-foil blank must be below the allocated blank fraction before subtraction.
2. Source water loss and receiver water gain must close within the combined uncertainty.
3. Repeat at 0.5x, 1x and 2x flow and at multiple gaps; flow-dependent flux is a gas-film result, not yet an intrinsic membrane result.
4. Fit total measured rate versus aperture area and perimeter using at least three masks.
5. Hold membrane differential pressure within the declared limit and challenge it deliberately in a separate test.
6. Separate polarity-odd transport from polarity-even drift/electrode effects.

See the CSV files for the full, editable design envelope.
