# Integrated sealed EO vapour test-cell calculation

Status: engineering concept; fabrication release is blocked by open evidence gates.

The selected cell has equal sealed chambers A and B separated by a 50 x 50 mm membrane region. Each assembled side has a governing **500.0 +/- 5.0 mL net free-gas target**. Local gap inserts provide 1, 2 and 4 mm spacing. Traceable physical calibration remains open.

## Derived volume basis

- Target flux: 208.0 g m-2 h-1 over 25 cm2.
- Target rate: 520.0 mg/h.
- Water transferred in 5.0 s: 0.722222 mg.
- Allowable change: 5.0 RH percentage points per chamber.
- Calculated minimum net volume: 427.6 mL per chamber.
- Selected/required volume ratio: 1.169.
- Predicted first-segment change: 4.276 percentage points per chamber.

The 1, 2 and 4 mm local membrane regions contain 2.5, 5.0 and 10.0 mL per side. Their corresponding bulk free-gas volumes are 497.5, 495.0 and 490.0 mL. Local plus bulk equals the 500.0 mL net-volume target. Gross empty-cavity volume closes from `gross = net + installed displacement`.

The nominal header/port/pressure-tap budget is 1.222389 mL per side against its 1.3 mL allocation. This budget is an identified portion of chamber geometry and a separate quantity from the total net free-gas volume.

## Transient inventory

At 5.0 s, chamber A is 45.724% RH and chamber B is 54.276% RH. The chamber difference is 8.551 percentage points. The analytic ABBA sequence conserves total water and returns both chambers to 50.000% RH at 20 s. The gas-only pressure diagnostic at the first extremum is 406.9 Pa.

## Engineering register

Fabrication release is **not ready**. The 13 open items are: gross_empty_cavity_volume_and_depth, installed_component_displacement, end_wall_and_central_divider_structural_sizing, fluidic_and_electrical_port_interfaces, internal_fan_selection_and_mounting, baffle_geometry_and_mounting, differential_pressure_management, fixture_mounting_fastener_pattern_and_preload, seal_geometry_and_compression, drawing_datums_and_dimensional_tolerances, loaded_flatness_and_gap_uniformity, internal_mixing_time, net_volume_calibration. Every required item must be closed with cited evidence before `fabrication_release.ready` may be set to true. Closure evidence is recorded in `integrated_sealed_cell_engineering_register.csv`; unresolved physical dimensions remain null in the governing configuration.
