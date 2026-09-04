# Moisture target and integrated cell scaling

Status: calculation basis for the integrated sealed two-chamber engineering concept.

## Declared moisture target

The design target is **208 g m-2 h-1** across the **50 x 50 mm** active region:

| Quantity | Value |
|---|---:|
| Active area | 25 cm2 = 0.0025 m2 |
| Target flux | 208 g m-2 h-1 |
| Target water rate | 0.520 g/h = 520 mg/h |
| Target water rate | 0.144444 mg/s |

This target is the explicit sizing input for chamber inventory and switching response.

## Switching and allowable drift

The polarity frequency is 0.1 Hz. A polarity segment therefore lasts 5.0 s. Water transferred in one segment is `0.144444 mg/s x 5.0 s = 0.722222 mg`.

The chamber-volume criterion limits either chamber to 5.0 RH percentage points of change during that segment. At 32 °C, ideal saturated water-vapour density is calculated with `rho_v,sat = p_sat / (R_v T)`.

The minimum net free-gas volume per side is `V_min = 0.722222 mg / (rho_v,sat x 0.05)`, which is **427.6 mL**. The selected design target is **500.0 mL per chamber**, giving **16.9% inventory margin** and **4.276 RH percentage points** of predicted single-chamber drift at 5 s. Traceable calibration of the assembled chambers to 500.0 +/- 5.0 mL remains a fabrication-release gate.

## Local gap scaling

| Gap per side | Local volume | Remaining bulk free-gas volume | Net free-gas volume |
|---:|---:|---:|---:|
| 1 mm | 2.5 mL | 497.5 mL | 500.0 mL |
| 2 mm | 5.0 mL | 495.0 mL | 500.0 mL |
| 4 mm | 10.0 mL | 490.0 mL | 500.0 mL |

Net free-gas volume shall be calibrated on the assembled chamber. Gross cavity volume remains an engineering-release quantity because installed components occupy part of that cavity.

## Predicted ABBA behavior

The configured sequence is `+1, -1, -1, +1`, with 5 s per segment. Starting from 50% RH on both sides, the ideal well-mixed model predicts approximately:

| Time | RH A | RH B | Signed transfer A to B |
|---:|---:|---:|---:|
| 0 s | 50.00% | 50.00% | 0.000000 mg |
| 5 s | 45.724% | 54.276% | +0.722222 mg |
| 10 s | 50.00% | 50.00% | 0.000000 mg |
| 15 s | 54.276% | 45.724% | -0.722222 mg |
| 20 s | 50.00% | 50.00% | 0.000000 mg |

The two chamber inventories remain symmetric and their total is conserved at every calculated time point.

## Handoff authority

The sole current engineering note, figure set and Word report are in `reports/test_cell_handoff_supplement_2026-09-03/`. Mechanical dimensions and interfaces awaiting closure are listed there, in the governing configuration and in the generated engineering-register CSV. The 2026-09-02 dimensioning directory is retained only as design history.
