# O30 nonlinear required-area study at 1.0 V — v1

## Decision addressed

This study replaces the proportional area extrapolation from the earlier
9000 m2-truncated receiver scan with a target-reaching nonlinear solve.

There is no 21 A/m2 acceptance limit in this study. Maximum local current
density is retained only as a model diagnostic. Likewise, 9000 m2 is a
comparison line, not an area acceptance cap.

## Fixed basis

- target: O30;
- cell terminal voltage: exactly 1.0 V;
- material: hypothetical legacy O30 case-94 material vector;
- geometry: fixed legacy case-94 channel geometry;
- receiver: coupled counter-current gas receiver;
- receiver-capacity multipliers: 1.01, 1.02, 1.05, 1.10, 1.20, 1.50,
  2.00 and 3.00;
- numerical integration ceiling: 15000 m2;
- nominal/refined area steps: 20/10 m2;
- finite local-current value supplied to the solver API: a non-binding
  numerical safety guard, not an engineering limit.

The required-area validity contract independently requires target attainment,
sufficient receiver capacity, a finite positive target-reaching area, a valid
counter-current receiver boundary, evaluated and closed process/receiver water
balances, positive transport direction, a resolved shortened endpoint, finite
power terms, voltage reconstruction within tolerance and no worker exception.
It does not reuse the legacy `analysis_pass` flag because that flag embeds
solver-guard values.

## Result

All eight tested points reach the O30 target and pass the required-area
validity contract.

| Receiver multiplier | Receiver/process dry-air ratio | Receiver airflow (cfm) | Required area (m2) | Delta vs 9000 m2 | Maximum local current (A/m2, diagnostic) | Core power (kW) |
|---:|---:|---:|---:|---:|---:|---:|
| 1.01 | 2.537 | 373339 | 12139.9 | +34.89% | 15.264 | 73.583 |
| 1.02 | 2.563 | 377035 | 12111.3 | +34.57% | 15.315 | 73.588 |
| 1.05 | 2.638 | 388124 | 12029.9 | +33.67% | 15.463 | 73.603 |
| 1.10 | 2.764 | 406607 | 11906.5 | +32.29% | 15.692 | 73.629 |
| 1.20 | 3.015 | 443571 | 11697.2 | +29.97% | 16.094 | 73.691 |
| 1.50 | 3.769 | 554463 | 11264.9 | +25.17% | 16.979 | 73.932 |
| 2.00 | 5.025 | 739285 | 10867.1 | +20.75% | 17.867 | 74.491 |
| 3.00 | 7.537 | 1108927 | 10499.7 | +16.66% | 18.758 | 76.131 |

Every point transfers approximately 4365.9183 kg/h. Process and receiver
relative water-balance errors are at numerical-noise scale, and the
counter-current boundary residual is likewise negligible.

## Convergence audit

The minimum-area tested point, receiver multiplier 3.0, gives:

- 20 m2 nominal step: 10499.7174 m2;
- 10 m2 refined step: 10499.6770 m2;
- absolute difference: 0.0405 m2;
- relative difference: 0.000385%.

The practical reported area is therefore approximately 10500 m2 for this
tested point.

## Interpretation

The previous proportional diagnostic of approximately 9275.1 m2 was 13.2%
below the nonlinear target-reaching result. The nonlinear tail cannot be
represented reliably by proportional extrapolation from the 9000 m2 stop.

Increasing receiver multiplier from 1.01 to 3.0 reduces required area by
13.51%, but increases receiver airflow by 197% to approximately 1.109 million
cfm and raises core power by about 3.46%. There is no unique system optimum:
R=3.0 minimizes area among tested points, while R=1.01 minimizes modeled core
power.

The result is a local area-airflow-power curve, not a global material or
geometry optimum. It does not validate the hypothetical material or a hardware
implementation. In particular, the very large receiver-air requirement still
needs manifold, distribution, pressure-drop and physical packaging closure.

## Reproduction

Run:

```bash
python3 scripts/make_wp1_o30_required_area_1v_v1.py
```

The workflow writes the full curve, per-point checkpoints, the refined selected
case and profile, a step-halving audit, a hashed run contract, a machine-readable
summary and a generated interpretation to `outputs/o30_required_area_1v_v1/`.
