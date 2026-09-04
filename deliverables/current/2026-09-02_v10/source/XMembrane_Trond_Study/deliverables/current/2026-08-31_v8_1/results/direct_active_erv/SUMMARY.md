# Direct active EO-assisted ERV study v1

- Mode: **study**.
- Cases: **320**.
- Passive modern ERV + AC reference: **543.741 kW**.
- Transport target closed (area is diagnostic only): **178**.
- Thermodynamically consistent active-transport cases: **179**.
- Physics screen: **178**.
- Positive / robust passive-gradient assistance diagnostics: **6 / 0**.
- Positive conditional energy margin: **108**.
- Engineering screen: **50**.
- Thermodynamic-physics + positive-energy overlap: **108**; of these **104** also pass the 4→8 decision-convergence gate.
- Stack-feasible cases: **63**.
- Cases touching the legacy numerical 50 kA/m² search ceiling: **50** (numerical status, not a current-density acceptance gate).
- 4→8-segment decision convergence: **136 / 320 case rows**.
- Full-coupled/full-system cases: **0** by model contract.

## Best available diagnostic

- Selection class: `engineering_screen_pass`.
- Case: `case_00150__terminal1_anchor__w7p2602806__v0p25__n8__eps0p75__film1__external_rejection`.
- Material: `terminal1_anchor`.
- Target: `7.260 g/kg`.
- Terminal voltage: `0.25 V`.
- Area: `34425.0 m²`.
- Minimum surface margin: `-0.08289`.
- Conditional arithmetic margin: `435.88 kW` / `80.16 %`.
- Heat treatment: `external_rejection`; effective fixed loss `0 V`; ASR `1e-05 ohm m²`.
- Gates: robust physics `True`, stack feasible `True`, engineering `True`.
- Numerics: 4→8 decision convergence `True`; maximum local current density `3.37 A/m²` (diagnostic only).
- Stack result: ``.

Audit PASS means integrity/reproducibility checks passed; it is not a design pass.
This prescribed-effectiveness segmented screen does not enable a full-system or commercial saving claim.
