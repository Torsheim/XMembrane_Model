# Direct active EO-assisted ERV study v1

- Mode: **study**.
- Cases: **8**.
- Passive modern ERV + AC reference: **543.741 kW**.
- Transport target closed (area is diagnostic only): **4**.
- Thermodynamically consistent active-transport cases: **4**.
- Physics screen: **4**.
- Positive / robust passive-gradient assistance diagnostics: **0 / 0**.
- Positive conditional energy margin: **4**.
- Engineering screen: **4**.
- Thermodynamic-physics + positive-energy overlap: **4**; of these **4** also pass the 4→8 decision-convergence gate.
- Stack-feasible cases: **4**.
- Cases touching the legacy numerical 50 kA/m² search ceiling: **4** (numerical status, not a current-density acceptance gate).
- 4→8-segment decision convergence: **4 / 8 case rows**.
- Full-coupled/full-system cases: **0** by model contract.

## Best available diagnostic

- Selection class: `engineering_screen_pass`.
- Case: `case_00002__combined_tw50_d1e10__w7p2602806__v0p1__n8__eps0p75__film1__external_rejection`.
- Material: `combined_tw50_d1e10`.
- Target: `7.260 g/kg`.
- Terminal voltage: `0.1 V`.
- Area: `43019.5 m²`.
- Minimum surface margin: `-0.06631`.
- Conditional arithmetic margin: `418.68 kW` / `77.00 %`.
- Heat treatment: `external_rejection`; effective fixed loss `0 V`; ASR `1e-05 ohm m²`.
- Gates: robust physics `True`, stack feasible `True`, engineering `True`.
- Numerics: 4→8 decision convergence `True`; maximum local current density `9.36 A/m²` (diagnostic only).
- Stack result: ``.

Audit PASS means integrity/reproducibility checks passed; it is not a design pass.
This prescribed-effectiveness segmented screen does not enable a full-system or commercial saving claim.
