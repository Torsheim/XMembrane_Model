# EO vapour-cell boundary analysis v1

## Scope

This is an experiment-design screen for the 25 cm2, 2 mm, 32 degC cell. It combines an imposed-current power-law membrane model, finite gas films, a short-channel mean-state water balance and declared measurement nuisances. The combined ranges are stress scenarios, not calibrated probability distributions.

The local flux surrogate reproduces the canonical repository finite-film solver to a maximum relative difference of 0.000e+00 in the registered cross-check cases.

## Nominal physical response

| Scenario | Gross Faradaic (mg/h) | Polarity-odd net (mg/h) | Net/gross | Conditional 95th percentile absolute odd error |
|---|---:|---:|---:|---:|
| order-unity slow diffusion | 16.804 | 16.803 | 99.99% | 7.47% |
| order-unity fast diffusion | 16.804 | 12.369 | 73.61% | 16.98% |
| inverse-design anchor | 168.146 | 168.136 | 99.99% | 1.01% |

## Main boundary findings

- In the fast-diffusion stress case, a static +0.1 RH-percentage-point inlet mismatch changes a naive single-direction result by +10.2%, but the polarity-odd result by only -0.00% in this model.
- A +0.1 K side-to-side temperature mismatch changes the same single-direction result by -28.9% and the odd result by -0.00%. Static mismatch is therefore highly damaging to one-way flux inference but largely rejected by a stable polarity reversal.
- Gas-film/geometry effects do not cancel. Changing the gap from the nominal 2 mm to 1 mm shifts the fast-diffusion odd signal by -2.0%; 4 mm shifts it by -10.1%.
- The project Sherwood correlation uses Sh=7.54 throughout this laminar envelope, so its local film coefficient is velocity-independent. Flow still changes axial bulk depletion. Experimental flow dependence must therefore be measured and an explicit film multiplier retained.
- Static leakage, edge flux and sensor offset mainly enter the polarity-even/single-direction channel. Residual polarity-correlated humidity or wall-inventory drift can mimic EO and survives the odd estimator. Ideal ABBA ordering rejects static and linear time drift; the sampled drift term must therefore be interpreted as the non-cancelling residual from curvature, hysteresis or polarity-linked settling.

## Closed-loop boundary screen

- In the 5 mL active chamber, the low-drag 5.04 mg/h case reaches 5 Pa differential pressure in only 0.0634 s in the gas-only rigid-chamber limit.
- With 5 L per side, the same gas-only time is 63.4 s. Unknown wall and membrane capacity lengthen the transient in direct proportion and must be identified by RH-step blanks.
- Symmetric one-side changes of 1 RH percentage point create about 95.2 Pa water-vapour pressure difference. A 0.1 K rigid-chamber temperature mismatch alone contributes about 33.2 Pa, already above the +/-5 Pa steady-cell target.
- The high-diffusivity scenario can reach passive equilibrium before a one-side 1 RH-point change; the closed test must fit EO and passive back-diffusion together.

## Rank associations in the declared combined stress space

- `low_drag_slow_diffusion`: humidity_drift_between_polarities_rh_percentage_points (|rho|=0.98), wall_and_sensor_rate_drift_between_polarities_mg_h (|rho|=0.20), active_area_error_fraction (|rho|=0.03)
- `order_unity_slow_diffusion`: humidity_drift_between_polarities_rh_percentage_points (|rho|=0.98), wall_and_sensor_rate_drift_between_polarities_mg_h (|rho|=0.20), active_area_error_fraction (|rho|=0.08)
- `order_unity_fast_diffusion`: film_multiplier (|rho|=0.73), humidity_drift_between_polarities_rh_percentage_points (|rho|=0.64), wall_and_sensor_rate_drift_between_polarities_mg_h (|rho|=0.13)
- `inverse_design_anchor`: humidity_drift_between_polarities_rh_percentage_points (|rho|=0.81), active_area_error_fraction (|rho|=0.53), current_error_fraction (|rho|=0.19)

The reported 5th/95th percentiles and pass fractions are conditional on `config/eo_vapor_boundary_analysis_v1.json`; they are not confidence limits. Replace each nuisance range with measured calibration, blank and repeatability results before producing a formal uncertainty budget.

## Experimental implications

1. Use a split common inlet and ABBA polarity reversal as the primary EO estimator.
2. Treat gap, support and unresolved film multiplier as physical calibration variables, not measurement noise.
3. Cross-switch the humidity reference; measure the residual over a complete ABBA block, not only absolute RH accuracy. Randomize or mirror block order to expose nonlinear drift and hysteresis.
4. Measure the foil blank and pressure-driven bypass before and after each block.
5. Report single-direction, polarity-even and polarity-odd rates separately.
6. Do not fit blank, area and perimeter from only the 4/9/25 cm2 square masks: that design has 0 residual degrees of freedom and area/perimeter correlation 0.995. Add a 16 cm2 square and an equal-area/different-perimeter insert (20x20 mm versus 8x50 mm, both 4 cm2), and run the rectangular insert in both flow orientations. The recommended five-insert design has 2 residual degrees of freedom and area/perimeter correlation 0.960.
