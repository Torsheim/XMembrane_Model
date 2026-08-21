# HeiQ Trond System Closure Study v1

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

## Install

Copy the package into the XMembrane repository and run:

```bash
python scripts/make_wp1_trond_system_closure_v1.py \
  --source-root "$HOME/HeiQ/XMembrane_Model" \
  --output-dir outputs/trond_system_closure_v1
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

The `--grid-to-device-efficiency` default is a screening assumption. It is not a universal transformer efficiency. Replace it with selected transformer, converter, cable and part-load data when the electrical architecture is known.
