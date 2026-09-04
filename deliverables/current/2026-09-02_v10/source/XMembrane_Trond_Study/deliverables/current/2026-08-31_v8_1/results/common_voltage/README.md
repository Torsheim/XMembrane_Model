# Workshop common-voltage diffusivity cross-check v1

This is a bounded post-ERV screening calculation for the hypothetical Terminal-1 inverse-design membrane. Only water diffusivity is varied.

## Frozen boundary

- Passive ERV + AC reference: **543.740564 kW**.
- Targets: O30 and the full remaining latent duty to the 20 C / 50% RH supply humidity ratio.
- Electrical topology: one common terminal voltage with local parallel current sharing.
- Tested common voltages: 0.5--2 V; no point exceeds 2 V.
- No current-density acceptance gate and no active-area acceptance gate are used.
- Feasibility requires endpoint validity, transport/water closure, terminal-voltage closure and the local thermodynamic audit.

## Refined diffusivity envelope

| Target | D [m²/s] | Feasible sampled V | Confirmed count | Physical no-solution count | Numerical/local unresolved count | Selected V | Area [m²] | Known EO+fan [kW] | SEC [kWh/kg] | Conservative conditional saving [kW] |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| full_remaining_latent | 1.000000e-14 | none | 0 | 3 | 4 | -- | -- | -- | -- | -- |
| full_remaining_latent | 1.597880e-14 | none | 0 | 3 | 4 | -- | -- | -- | -- | -- |
| full_remaining_latent | 1.000000e-13 | none | 0 | 3 | 4 | -- | -- | -- | -- | -- |
| full_remaining_latent | 1.000000e-12 | none | 0 | 3 | 4 | -- | -- | -- | -- | -- |
| full_remaining_latent | 1.000000e-11 | none | 0 | 3 | 4 | -- | -- | -- | -- | -- |
| full_remaining_latent | 1.000000e-10 | none | 0 | 3 | 4 | -- | -- | -- | -- | -- |
| full_remaining_latent | 1.000000e-09 | none | 0 | 3 | 4 | -- | -- | -- | -- | -- |
| o30 | 1.000000e-14 | 1.00--1.25 | 2 | 2 | 3 | 1.00 | 7173.5 | 30.055 | 0.02447 | 162.416 |
| o30 | 1.597880e-14 | 1.00--1.25 | 2 | 2 | 3 | 1.00 | 7173.5 | 30.057 | 0.02447 | 162.414 |
| o30 | 1.000000e-13 | 1.00--1.25 | 2 | 2 | 3 | 1.00 | 7173.5 | 30.091 | 0.02450 | 162.380 |
| o30 | 1.000000e-12 | 1.00--1.25 | 2 | 2 | 3 | 1.00 | 7173.6 | 30.453 | 0.02479 | 162.018 |
| o30 | 1.000000e-11 | 1.00--1.25 | 2 | 2 | 3 | 1.25 | 3837.3 | 34.015 | 0.02769 | 158.456 |
| o30 | 1.000000e-10 | 1.00--1.25 | 2 | 2 | 3 | 1.25 | 3837.8 | 64.891 | 0.05283 | 127.580 |
| o30 | 1.000000e-09 | 1.00--1.25 | 2 | 2 | 3 | 1.25 | 3842.6 | 373.885 | 0.30440 | -181.413 |

## Workshop figure

See `figures/workshop_common_voltage_diffusivity.png` (and the PDF equivalent). In the left panel, crosses are physical no-solution results at the sampled voltage and open triangles are unresolved numerical/local high-bracket results. The saving and area panels explicitly state when a target has no feasible sampled value.

## Result status

- Evaluated cases: 196.
- Refined feasible cases: 14.
- Target/diffusivity coordinates with at least one numerically confirmed sampled voltage: 7/14.
- Stable sampled feasibility classifications between the two segment counts: 98/98.
- Refined sampled points unresolved by the numerical/local bracket: 49.
- Full remaining duty: 0/49 refined sampled voltages are feasible; 21 are physical no-solution results and 28 remain numerical/local-bracket unresolved. This is no demonstrated <=2 V solution, not a global physical no-go proof.

## Local-bracket sensitivity probe

Every flagged <=2 V case at both segment counts was retried after raising only the configured numerical current bound by 100x (50,000 to 5,000,000 A/m²). 0/98 retries recovered full closure and replaced their source rows and profiles; 98/98 remain numerical/local unresolved. The V2 high bracket also contains a physical-current limit, so an unrecovered retry is not promoted to a physical no-go. See `local_bracket_probe.csv`.

## Energy interpretation

The primary power column uses the frozen control-conservative avoided-AC boundary and subtracts EO grid power plus the frozen area-based process/receiver module-fan term. The CSV also retains the exact-endpoint coil result as a separate diagnostic. Receiver/sink energy and EO heat rejection are not modelled; therefore the reported saving and receiver SEC room are conditional budgets, not complete-system savings.

## Limitations

- The Terminal-1 vector is an inverse-design coordinate, not measured material data.
- Only D changes; correlated changes in sorption, conductivity, drag and thickness are excluded.
- The receiver is the balanced post-ERV exhaust gas stream, not a liquid-out boundary.
- The reduced-order model prescribes stream endpoints and linearly segmented bulk states; it is not a conjugate heat-and-mass-transfer solution.
- The 0.25-V grid can miss a narrow feasible voltage interval. `none` means no feasible sampled point, not a mathematical no-go proof.
- `above_internal_current_search_ceiling` is a legacy ambiguous status: the V2 high bracket is the lower of a physical-current limit and a configured numeric bound. Every flagged <=2 V case is retried at 100x the numeric bound; any unrecovered row remains unresolved/local-bracket-limited and is neither an engineering current-density rejection nor, by status alone, a physical no-go proof.
- Numerical refinement is only 8 to 16 segments. Unconfirmed rows require a targeted 32/64-segment replay before design use.
- Area is reported even above the observation cap, but is never used to determine feasibility.

## Reproduction

```bash
python3 -B scripts/run_workshop_common_voltage_diffusivity_v1.py --overwrite
```
