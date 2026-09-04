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

    x = case["x_mid"].astype(float)
    j = case["current_density_a_m2"].astype(float)
    profile = pd.DataFrame(
        {
            "x_over_L": x,
            "through_membrane_current_density_a_m2": j,
            "supply_face_signed_current_density_a_m2": j,
            "receiver_face_signed_current_density_a_m2": -j,
            "terminal_voltage_v": case["terminal_voltage_v"].astype(float),
        }
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    profile.to_csv(OUTPUT_DIR / "selected_membrane_current_profile.csv", index=False)

    plt.style.use("seaborn-v0_8-whitegrid")
    fig, ax = plt.subplots(figsize=(9.2, 5.8))
    ax.axhline(0.0, color="#30343b", linewidth=2.0, label="Membranplan / nullinje")
    ax.step(x, j, where="mid", color="#1479c9", linewidth=2.4)
    ax.plot(
        x,
        j,
        color="#1479c9",
        marker="o",
        linestyle="none",
        markersize=6,
        label="Supply-flate (over): +j(x)",
    )
    ax.step(x, -j, where="mid", color="#e06b2d", linewidth=2.4)
    ax.plot(
        x,
        -j,
        color="#e06b2d",
        marker="s",
        linestyle="none",
        markersize=6,
        label="Receiver-flate (under): −j(x)",
    )
    ax.fill_between(x, 0.0, j, step="mid", color="#1479c9", alpha=0.10)
    ax.fill_between(x, 0.0, -j, step="mid", color="#e06b2d", alpha=0.10)
    ax.annotate(
        "Samme strøm gjennom begge flater\n– motsatt fortegn pga. valgt normalretning",
        xy=(0.56, -float(j.iloc[4])),
        xytext=(0.58, -1.2),
        arrowprops={"arrowstyle": "->", "color": "#555b66"},
        fontsize=9,
        color="#4b5563",
    )
    ax.set(
        xlabel="Normalisert posisjon langs membranen, x/L [–]",
        ylabel="Signert lokal strømtetthet [A/m²]",
        title="Lokal strøm gjennom membranen – over- og underside",
        xlim=(0.0, 1.0),
    )
    limit = 1.18 * float(j.abs().max())
    ax.set_ylim(-limit, limit)
    ax.legend(frameon=True, loc="upper right")
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
    fig.savefig(OUTPUT_DIR / "selected_membrane_current_profile_over_under.png", dpi=220)
    fig.savefig(OUTPUT_DIR / "selected_membrane_current_profile_over_under.svg")
    plt.close(fig)


if __name__ == "__main__":
    main()
