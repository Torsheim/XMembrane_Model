from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
STUDY_DIR = ROOT / "outputs/direct_active_erv_transport_sensitivity_2v/study"
OUTPUT_DIR = STUDY_DIR / "figures"


def main() -> None:
    selected = pd.read_csv(STUDY_DIR / "selected_cases.csv").iloc[0]
    segments = pd.read_csv(STUDY_DIR / "segment_register.csv.gz")
    case = segments.loc[segments["case_id"] == selected["case_id"]].copy()
    case = case.sort_values("segment_index")
    if case.empty:
        raise RuntimeError(f"No segment data for selected case {selected['case_id']}")

    # Process flow follows increasing x. Receiver flow is counter-current, so
    # receiver_out belongs at x0 and receiver_in belongs at x1 for each segment.
    process_x = [float(case.iloc[0]["x0"]), *case["x1"].astype(float).tolist()]
    process_w = [
        1000.0 * float(case.iloc[0]["process_in_humidity_ratio_kg_kg_da"]),
        *(1000.0 * case["process_out_humidity_ratio_kg_kg_da"].astype(float)).tolist(),
    ]
    receiver_x = [float(case.iloc[0]["x0"]), *case["x1"].astype(float).tolist()]
    receiver_w = [
        1000.0 * float(case.iloc[0]["receiver_out_humidity_ratio_kg_kg_da"]),
        *(1000.0 * case["receiver_in_humidity_ratio_kg_kg_da"].astype(float)).tolist(),
    ]

    profile = pd.DataFrame(
        {
            "x_over_L": process_x,
            "supply_humidity_ratio_g_kg_dry_air": process_w,
            "receiver_humidity_ratio_g_kg_dry_air": receiver_w,
        }
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    profile.to_csv(OUTPUT_DIR / "selected_membrane_humidity_profile.csv", index=False)

    plt.style.use("seaborn-v0_8-whitegrid")
    fig, ax = plt.subplots(figsize=(9.2, 5.6))
    ax.plot(
        process_x,
        process_w,
        color="#1479c9",
        marker="o",
        linewidth=2.5,
        markersize=5,
        label="Supply / process  →",
    )
    ax.plot(
        receiver_x,
        receiver_w,
        color="#e06b2d",
        marker="s",
        linewidth=2.5,
        markersize=5,
        label="←  Receiver (motstrøm)",
    )
    ax.fill_between(
        process_x,
        process_w,
        receiver_w,
        color="#7d8fa3",
        alpha=0.12,
        label="Lokal forskjell i fuktinnhold",
    )
    ax.set(
        xlabel="Normalisert posisjon langs membranen, x/L [–]",
        ylabel="Fuktforhold, w [g vann/kg tørrluft]",
        title="Fuktprofil langs membranen – valgt aktivt ERV-case",
        xlim=(0.0, 1.0),
    )
    ax.legend(frameon=True, loc="best")
    ax.text(
        0.01,
        0.02,
        f"{selected['material_id']}, {selected['terminal_voltage_v']:.1f} V, "
        f"{int(selected['segment_count'])} segmenter",
        transform=ax.transAxes,
        fontsize=9,
        color="#4b5563",
    )
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "selected_membrane_humidity_profile.png", dpi=220)
    fig.savefig(OUTPUT_DIR / "selected_membrane_humidity_profile.svg")
    plt.close(fig)


if __name__ == "__main__":
    main()
