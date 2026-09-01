# HeiQ system energy-closure study

This package adds one study script that addresses the next questions:

- What limits a receiver when water leaves as liquid?
- What changes when receiver gas-film resistance is removed?
- How does the model compare with official ERV effectiveness and pressure-drop ranges?
- How can ERV and EO be combined without double-counting savings?
- How much extra water transport and EO input are required for a further 10% reduction?
- Is the ~180 Wh/L break-even arithmetic correct, and what boundary does it describe?
- What happens at D0 = 1e-10 and 1e-9 m2/s?
- How do total channel width, gap/chamber depth, path count and length trade against fan power?
- Are all main power terms, FOMs, conditions and terminology reported in one place?

## Important interpretation

The script treats 180 Wh/L as a conditional gross no-ERV compressor limit, not as a
universal whole-system or thermodynamic break-even.

The liquid study includes a local uniform-flux upper-bound screen. It does not replace a
full finite liquid-film, drainage, flooding, wet-electrode or conjugate thermal model.

ERV comparison uses official exchanger-level effectiveness and pressure-drop envelopes,
not generic annual whole-building savings claims.

The earlier 21 A/m2 acceptance gate has been superseded: current density is a
reported diagnostic, not a design limit. Any system-closure output generated with
that gate is superseded. The active `v2_no_current_gate` package has now been
regenerated. Gas-derived
claims should remain fail-closed against target attainment, solver and water-balance
validity, the declared voltage/area contract and complete power components, but not
against 21 A/m2.

The retained O30 regression row reaches the target at 0.98 V and 8922.21 m2. Its
21.2238 A/m2 maximum local current density does not disqualify it. The current
required-area study separately shows that the fixed legacy case-94 basis requires
10499.7-12139.9 m2 at exactly 1.0 V, depending on receiver airflow. These are
different fixed geometry/operating bases and must not be interchanged.

## Install

From a complete editable repository checkout, run:

```bash
PYTHONPATH=src python3 scripts/run_system_energy_closure_study.py \
  --source-root . \
  --output-dir outputs/system_energy_closure_study
```

Use `--smoke` for a faster first run.


## Main outputs

The workflow writes:

- `break_even_register.csv` — verifies the conditional ~180 Wh/L arithmetic and the remaining auxiliary allowance;
- `erv_industry_grid.csv` — ASHRAE exchanger-level effectiveness/pressure-drop screen;
- `erv_plus_eo_10pct.csv` — extra EO water transport and input power for a further 10% reduction;
- `systems_reported_separately.csv` — no-ERV AC, ERV-only, EO-only and ERV+EO as separate system rows;
- `liquid_local_upper_bound.csv` — liquid activity, voltage, area, current and balance-of-plant bottlenecks;
- `diffusivity_extension.csv` — includes D0 = 1e-10 and 1e-9 m2/s;
- `geometry_sweep.csv` — total width, chamber gap/depth, parallel paths, length, pressure drop and fan power;
- `complete_system_power_ledger.csv` — compressor, ERV fan, EO, receiver/process fans, pumps, heat rejection, controls and conversion boundary;
- `all_requested_foms.csv` — FOM-01 through FOM-18 with reported/not-available status;
- `industry_benchmarks.csv` — official ERV ranges plus the AirJoule company-reported <160 Wh/L water-harvesting benchmark, with boundary caveats;
- `grid_loss_sensitivity.csv` — 95–100% grid-to-device efficiency sensitivity;
- `conditions.csv` and `terminology.csv` — one-place design basis and controlled nomenclature.

`selected_reference_case.csv` records every individual reference gate and the failure
reason. `power_ledger.csv`, `complete_system_power_ledger.csv`,
`figures_of_merit.csv`, `all_requested_foms.csv` and `enclosure_foms.csv` retain their
audit rows but leave claim-dependent values missing when the reference fails.

The legacy `trond_system_closure_v1` output was produced under the
superseded current gate and must not be reused. The current package performs no
current-density acceptance test unless `--current-cap-a-m2` is supplied explicitly
as a named sensitivity. Regardless of selection, the liquid calculation remains
only a local screen: it excludes a closed regeneration and heat-sink ledger and must
not be reported as a full-system total or saving.

## Active no-current-gate status (2026-08-26)

The regenerated gas reference passes the active target, balance, stack, voltage and
area gates. The known gas-core subtotal is 118.39 kW at the site plane. This is not a
complete system total: `heat_rejection` and `receiver_regeneration` remain unresolved,
so system saving and system FOMs are deliberately unavailable. Missing components are
not interpreted as zero.

The primary post-ERV energy evidence is the separate audited
`terminal1_post_erv_10pct_incremental_v2_study` output, not the linearized 2.9 kW
screen in this integration package. It reports a 53.07 kW / 9.76% conditional margin
for the best real-film row, while still disabling full-system claims.

The `--grid-to-device-efficiency` default is a screening assumption. It is not a universal transformer efficiency. Replace it with selected transformer, converter, cable and part-load data when the electrical architecture is known.
