# Test-cell minimum area and ERV scale check

## Decision

Keep the planned 50 x 50 mm maximum active window (25 cm2). The existing
40 x 40 mm insert (16 cm2) is the smallest practical insert that covers the
full 0.5-5 A/m2 low-current inverse-design-anchor screen at the nominal 6 L/min
per side. The existing 30 x 30 mm insert (9 cm2) is sufficient in the ideal
gross-signal calculation for the 1.24-3.37 A/m2 local-current range of the
selected direct-active-ERV case. These are measurement signal floors, not
guarantees of measurable net membrane transport.

The physical membrane coupon remains about 80 x 80 mm because the inactive land
is needed for the double seal, guard groove and clamping. Active aperture and
physical coupon area must not be confused.

## Minimum-area results

The calculation holds total gas flow fixed at 6 L/min per side and solves for a
two-stream differential RH signal equal to five times the combined expanded
uncertainty of two 0.1-RH-percentage-point channels.

| Case | Current density | Minimum ideal active area | Smallest existing insert |
|---|---:|---:|---:|
| Inverse-design anchor, lower planned point | 0.50 A/m2 | 13.09 cm2 | 16 cm2 |
| Inverse-design anchor | 1.00 A/m2 | 6.55 cm2 | 9 cm2 |
| Direct-active-ERV selected profile minimum | 1.242 A/m2 | 5.27 cm2 | 9 cm2 |
| Direct-active-ERV selected profile maximum | 3.366 A/m2 | 1.94 cm2 | 4 cm2 |
| Order-unity reference | 10 A/m2 | 65.5 cm2 | Does not fit at 6 L/min |
| Low-drag reference, transport number 0.3 | 10 A/m2 | 218 cm2 | Does not fit at 6 L/min |

The last two cases do not require a different fixture for every experiment.
With the 25 cm2 aperture, the existing calculation finds maximum ideal flows of
2.29 L/min for the order-unity reference and 0.69 L/min for the low-drag
reference. Signal acquisition and high-flow film characterization must therefore
be separate operating modes unless an integrating or more sensitive water-rate
measurement is added.

## Hydraulic similarity to the direct-active ERV calculation

| Quantity | Coupon fixture | Selected direct-active ERV | Assessment |
|---|---:|---:|---|
| Channel gap | 2 mm nominal; 1/2/4 mm sweep | 2 mm | Direct match |
| Channel velocity | 1 m/s nominal; 0.5-4 m/s sweep | 2 m/s | Full-scale point is covered |
| Reynolds number | about 236 at 1 m/s; 472 at 2 m/s | 488 process; 529 receiver | Close laminar similarity |
| Straight-channel pressure drop | 2.9 Pa at 1 m/s; about 5.8 Pa at 2 m/s | 218/226 Pa | Difference follows 50 mm versus 1.95/2.08 m flow length |
| Active flow length | 50 mm | 1.945/2.080 m | Coupon tests local transport, not a full axial core |

The coupon is therefore a reasonable local channel and membrane test. It cannot
validate the full axial humidity and temperature evolution by itself; that
requires either a longer multi-segment rig or a validated local model chained
over the full-scale length.

## Comparison with documented commercial installations

The selected direct-active case represents 150,000 CFM (70.79 m3/s), 34,425 m2
active membrane, 1.95-2.08 m flow length and 218-226 Pa calculated channel
pressure drop.

* RenewAire's largest published SA static membrane-core array is rated up to
  70,400 CFM and uses 64 modular enthalpy cores. The project flow corresponds to
  about 2.13 such maximum arrays by airflow. Source:
  [RenewAire SA Series specification](https://renewaire.com/wp-content/uploads/2025/05/Submittal-SASeries-Sept2021-1.pdf).
* The Naples Community Hospital installation is a concrete 11,000-CFM hospital
  laboratory retrofit using twelve 20-inch static enthalpy cores. Its specified
  maximum static pressure was one inch water gauge, about 249 Pa. The project's
  218-226 Pa calculated channel pressure drops are therefore within a documented
  commercial order of magnitude. Source:
  [RenewAire Naples Community Hospital case study](https://renewaire.com/casestudies/naples-community-hospital/).
* Kao Data London One is a concrete large-data-centre reference with thirteen
  plate-exchanger air handlers at 13.5 m3/s each, or 175.5 m3/s total. The
  project airflow is 5.24 Kao-sized units and 40% of that documented total.
  Those are sensible plate exchangers, not moisture-transfer membrane ERVs, so
  the example validates airflow and modular scale rather than membrane area.
  Source: [FlaktGroup Kao Data Centre case study](https://www.flaktgroup.com/en/references/kao-data-center/).

The 34,425 m2 result implies 486 m2 active membrane per m3/s of process air and
about 0.97 s nominal process-channel residence. The two 2-mm gas gaps alone
occupy approximately 138 m3 before headers, supports, electrodes, seals and
casing. A flow-equivalent set of the largest RenewAire arrays has about 97 m3 of
external bounding-box volume. This comparison is only a packaging diagnostic,
because RenewAire does not publish internal membrane surface area and the
architectures differ.

## Claim boundary

The airflow, velocity, Reynolds number and pressure drop are credible for a
large modular building installation. The active area is large but remains
within the same broad equipment-volume order as very large modular air systems.
It is not yet a commercially validated ERV design: electrode open area,
electrical segmentation, headers, support thickness, leakage, cleanability,
fire/hygiene compliance and manufactured-core pressure drop are not represented
in the ideal channel-volume comparison.

The generated minimum-area evidence is in
`outputs/eo_vapor_cell_sizing_v1/minimum_detectable_active_area.csv` and is
reproduced by `scripts/design_eo_vapor_test_cell.py`.
