#!/usr/bin/env python3
"""Compare sealed-cell volumes for a net transient water-transport experiment."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "config" / "eo_vapor_test_cell_net_transport_volume_study.json",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "reports" / "test_cell_net_transport_volume_study_2026-09-04",
    )
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_base_model(path: Path):
    spec = importlib.util.spec_from_file_location("eo_test_cell_base_model", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load base model: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def validate(study: dict[str, Any], base: dict[str, Any]) -> None:
    if int(study["schema_version"]) != 1:
        raise ValueError("Only schema version 1 is supported")
    fixed = study["fixed_membrane"]
    region = base["integrated_sealed_cell"]["membrane_region"]
    mechanical = base["integrated_sealed_cell"]["mechanical_starting_values"]
    if fixed["active_window_mm"] != [region["width_mm"], region["height_mm"]]:
        raise ValueError("The study must preserve the base active membrane window")
    if not math.isclose(float(fixed["active_area_cm2"]), 25.0):
        raise ValueError("The study must preserve the 25 cm2 active area")
    if fixed["coupon_mm"] != mechanical["membrane_coupon_mm"]:
        raise ValueError("The study must preserve the 80 x 80 mm coupon")
    if not math.isclose(float(fixed["local_membrane_gap_mm"]), 2.0):
        raise ValueError("The study must preserve the 2 mm local membrane gap")
    if not math.isclose(float(study["bulk_geometry"]["bulk_depth_mm"]), 20.0):
        raise ValueError("This comparison is bound to a 20 mm bulk depth")
    volumes = [float(value) for value in study["net_volume_cases_ml_per_side"]]
    if volumes != sorted(volumes) or min(volumes) <= 0.0:
        raise ValueError("Net-volume cases must be positive and ordered")


def build_cases(study: dict[str, Any], base: dict[str, Any], model: Any) -> pd.DataFrame:
    cell = base["integrated_sealed_cell"]
    state = base["operating_state"]
    bulk = study["bulk_geometry"]
    transient = study["transient"]
    depth_mm = float(bulk["bulk_depth_mm"])
    displacement_ml = float(bulk["component_displacement_upper_bound_ml_per_side"])
    trim_reserve_ml = float(bulk["calibration_trim_reserve_ml_per_side"])
    duration_s = float(transient["segment_duration_s"])
    planning_signal_pp = float(transient["planning_rh_signal_pp"])
    sensor_tau_s = float(transient["sensor_tau63_s"])
    rate_mg_s = float(model.integrated_target_water_rate_mg_s(base))
    transferred_mg = rate_mg_s * duration_s
    saturation_density = float(model.saturated_water_vapour_density_kg_m3(state["temperature_c"]))
    temperature_k = float(state["temperature_c"]) + 273.15
    water_molar_mass_kg_mol = 0.01801528
    gas_constant = 8.31446261815324

    rows: list[dict[str, float | str]] = []
    case_names = ["Kompakt transientcelle", "Mellomvolum", "Lavdriftcelle"]
    for name, net_volume_ml in zip(case_names, study["net_volume_cases_ml_per_side"]):
        net_volume_ml = float(net_volume_ml)
        gross_volume_ml = net_volume_ml + displacement_ml + trim_reserve_ml
        footprint_side_mm = math.sqrt(gross_volume_ml * 1000.0 / depth_mm)
        rh_change_pp = (
            transferred_mg
            / 1.0e6
            / (saturation_density * net_volume_ml / 1.0e6)
            * 100.0
        )
        pressure_difference_pa = (
            2.0
            * (transferred_mg / 1.0e6 / water_molar_mass_kg_mol)
            * gas_constant
            * temperature_k
            / (net_volume_ml / 1.0e6)
        )
        duration_to_signal_s = duration_s * planning_signal_pp / rh_change_pp
        sensor_step_fraction = 1.0 - math.exp(-duration_to_signal_s / sensor_tau_s)
        rows.append(
            {
                "case": name,
                "calibrated_net_volume_ml_per_side": net_volume_ml,
                "bulk_depth_mm": depth_mm,
                "gross_cavity_volume_ml_per_side": gross_volume_ml,
                "square_bulk_footprint_side_mm": footprint_side_mm,
                "component_displacement_upper_bound_ml_per_side": displacement_ml,
                "pretrim_net_volume_at_displacement_bound_ml_per_side": net_volume_ml
                + trim_reserve_ml,
                "trim_required_at_displacement_bound_ml_per_side": trim_reserve_ml,
                "trim_capacity_if_component_displacement_is_zero_ml_per_side": displacement_ml
                + trim_reserve_ml,
                "active_membrane_area_cm2": 25.0,
                "target_flux_g_m2_h": float(
                    cell["volume_sizing_basis"]["target_net_water_flux_g_m2_h"]
                ),
                "integrated_water_rate_mg_s": rate_mg_s,
                "water_transferred_per_segment_mg": transferred_mg,
                "segment_duration_s": duration_s,
                "single_chamber_rh_change_pp": rh_change_pp,
                "rigid_chamber_differential_pressure_pa": pressure_difference_pa,
                "duration_to_planning_rh_signal_s": duration_to_signal_s,
                "sensor_step_fraction_at_planning_signal": sensor_step_fraction,
            }
        )
    return pd.DataFrame(rows)


def make_qualitative_plot(path: Path, cases: pd.DataFrame) -> None:
    """Create a presentation plot deliberately free of printed numeric values."""
    labels = list(cases["case"])
    colours = ["#B91C1C", "#D97706", "#176B87"]
    positions = list(range(len(labels)))

    fig, (ax_signal, ax_geometry) = plt.subplots(1, 2, figsize=(11.2, 4.8))
    ax_signal.bar(
        positions,
        cases["single_chamber_rh_change_pp"],
        color=colours,
        width=0.62,
    )
    ax_signal.set_xticks(positions, labels)
    ax_signal.tick_params(axis="x", labelsize=9)
    ax_signal.set_yticks([])
    ax_signal.set_ylabel("Størrelse på RH-respons")
    ax_signal.set_title("Netto transient-signal")
    ax_signal.grid(True, axis="y", alpha=0.22)
    ax_signal.text(
        0.5,
        0.93,
        "Større respons gir bedre observasjon\nmen mer endrede randbetingelser",
        transform=ax_signal.transAxes,
        ha="center",
        va="top",
        fontsize=9,
    )

    ax_geometry.bar(
        positions,
        cases["square_bulk_footprint_side_mm"],
        color=colours,
        width=0.62,
    )
    ax_geometry.set_xticks(positions, labels)
    ax_geometry.tick_params(axis="x", labelsize=9)
    ax_geometry.set_yticks([])
    ax_geometry.set_ylabel("Nødvendig bulkfotavtrykk")
    ax_geometry.set_title("Mekanisk plassbehov")
    ax_geometry.grid(True, axis="y", alpha=0.22)
    ax_geometry.text(
        0.5,
        0.93,
        "Større kammer gir roligere\nforløp og mer sensortid",
        transform=ax_geometry.transAxes,
        ha="center",
        va="top",
        fontsize=9,
    )

    fig.suptitle(
        "EO-dampcelle: avveiing for netto transienttransport\n"
        "Fast membranareal og likt testtrinn",
        fontsize=14,
    )
    fig.tight_layout()
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def write_summary(path: Path, study: dict[str, Any], cases: pd.DataFrame) -> None:
    rows = []
    for row in cases.itertuples(index=False):
        rows.append(
            "| {case} | {volume:.0f} | {side:.1f} | {rh:.2f} | {pressure:.0f} | {duration:.2f} | {sensor:.1%} |".format(
                case=row.case,
                volume=row.calibrated_net_volume_ml_per_side,
                side=row.square_bulk_footprint_side_mm,
                rh=row.single_chamber_rh_change_pp,
                pressure=row.rigid_chamber_differential_pressure_pa,
                duration=row.duration_to_planning_rh_signal_s,
                sensor=row.sensor_step_fraction_at_planning_signal,
            )
        )
    first = cases.iloc[0]
    last = cases.iloc[-1]
    summary = f"""# Volumscreen for netto transienttransport

Dette er en separat sensitivitetsstudie. Den endrer ikke det eksisterende
500 mL-konseptet eller påstår at en lukket celle måler intrinsisk EO-fluks.
Den sammenligner i stedet kalibrerte nettovolumer når RH-endringen er selve
nettotransportsignalet.

## Fast grunnlag

- Aktiv membran: 50 x 50 mm = 25 cm² i en 80 x 80 mm kupong.
- Lokalt membrangap: 2 mm; bulkdybde: 20 mm.
- Betinget målfluks: 208 g/m²/h, som over 25 cm² er {first.integrated_water_rate_mg_s:.6f} mg/s.
- Over ett {first.segment_duration_s:.0f} s trinn flyttes {first.water_transferred_per_segment_mg:.6f} mg vann.
- Geometrien reserverer 22,6 mL for komponenter og 21,9 mL kalibreringstrim ved denne konservative komponentgrensen.

## Beregninger

For hvert kalibrert nettovolum brukes

```text
V_gross = V_net + V_komponentgrense + V_trimreserve
side = sqrt(1000 V_gross / bulkdybde)
ΔRH = m_overført / (rho_sat V_net)
Δp_rigid = 2 (m_overført / M_vann) R T / V_net
```

`Δp_rigid` er en diagnose for helt stive, lukkede kamre. Den er ikke en
akseptabel driftsgrense; den viser hvorfor differansetrykk må måles og
utjevnes.

| Case | Nettovolum per side mL | Kvadratisk bulkfotavtrykk mm | RH-endring per trinn pp | Stiv Δp Pa | Tid til 10 pp s | SHT45-respons ved 10 pp |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
{chr(10).join(rows)}

## Tolkning

Den kompakte løsningen gir tydeligst RH-signal, men også raskest utvikling av
damptrykks- og fuktgradienter. Den store løsningen gir roligere utvikling og
passer bedre til en langsom RH-sensor, men krever det brede plenumet. Alle tre
tilfellene forutsetter at blanding, lekkasje, temperaturbias og
differansetrykk verifiseres. Den tallfrie figuren er laget for presentasjon;
`volume_cases.csv` er den autoritative talltabellen.

For netto transienttransport er {first.calibrated_net_volume_ml_per_side:.0f}–{cases.iloc[1].calibrated_net_volume_ml_per_side:.0f} mL et relevant kompakt område hvis en raskere RH-/duggpunktsreferanse brukes. Med SHT45 som hovedsensor er {last.calibrated_net_volume_ml_per_side:.0f} mL og omtrent {last.duration_to_planning_rh_signal_s:.0f} s mer konsistent med sensorens respons.
"""
    path.write_text(summary, encoding="utf-8")


def main() -> None:
    args = parse_args()
    config_path = args.config.resolve()
    study = read_json(config_path)
    base_path = ROOT / study["base_config"]
    base = read_json(base_path)
    base_model_path = ROOT / "scripts" / "design_eo_vapor_test_cell.py"
    model = load_base_model(base_model_path)
    validate(study, base)
    cases = build_cases(study, base, model)

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "volume_cases.csv"
    plot_path = output_dir / "net_transport_volume_tradeoff.png"
    summary_path = output_dir / "SUMMARY.md"
    decision_path = output_dir / "decision_summary.json"
    cases.to_csv(csv_path, index=False)
    make_qualitative_plot(plot_path, cases)
    write_summary(summary_path, study, cases)
    decision = {
        "study_id": study["study_id"],
        "status": "SCREENING ONLY",
        "recommended_use": {
            "fast_reference_sensor": "200–300 mL per side for a compact net-transient cell",
            "sht45_as_primary_sensor": "500 mL per side with approximately 10–12 s segments",
        },
        "claim_boundary": study["interpretation"]["claim_boundary"],
        "fixed_membrane": study["fixed_membrane"],
        "cases": cases.to_dict(orient="records"),
    }
    write_json(decision_path, decision)
    generated = [csv_path, plot_path, summary_path, decision_path]
    manifest = {
        "schema_version": 1,
        "study_id": study["study_id"],
        "sources": [
            {"path": config_path.relative_to(ROOT).as_posix(), "sha256": sha256(config_path)},
            {"path": base_path.relative_to(ROOT).as_posix(), "sha256": sha256(base_path)},
            {"path": base_model_path.relative_to(ROOT).as_posix(), "sha256": sha256(base_model_path)},
            {
                "path": Path(__file__).resolve().relative_to(ROOT).as_posix(),
                "sha256": sha256(Path(__file__).resolve()),
            },
        ],
        "generated_outputs": [
            {
                "path": item.name,
                "sha256": sha256(item),
                "size_bytes": item.stat().st_size,
            }
            for item in generated
        ],
    }
    write_json(output_dir / "source_manifest.json", manifest)
    print(
        json.dumps(
            {
                "status": "PASS",
                "output_dir": str(output_dir),
                "recommended_compact_volume_range_ml": [200.0, 300.0],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
