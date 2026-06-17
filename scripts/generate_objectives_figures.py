from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "memoria" / "cdia" / "img"


TYPES = [
    "recurring_unresolved",
    "scope_change",
    "new_blocker",
    "blocker_resolved",
    "possible_duplicate",
    "contradicts_decision",
    "verbal_close",
]

COUNTS = {
    "S1": [2, 2, 2, 1, 1, 1, 2],
    "S2": [2, 2, 2, 1, 1, 1, 2],
    "S3": [2, 2, 2, 1, 1, 1, 3],
}


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 11,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
        }
    )

    sprint_labels = list(COUNTS.keys())
    matrix = [COUNTS[s] for s in sprint_labels]
    totals = [sum(values) for values in zip(*matrix)]
    sprint_totals = [sum(COUNTS[s]) for s in sprint_labels]

    fig = plt.figure(figsize=(8.4, 5.6))
    ax = fig.add_axes([0.12, 0.18, 0.76, 0.68])
    ax.set_xlim(0, 3)
    ax.set_ylim(0, len(TYPES))
    ax.invert_yaxis()
    ax.set_xticks([0.5, 1.5, 2.5], sprint_labels, fontsize=12, fontweight="bold")
    ax.set_yticks([i + 0.5 for i in range(len(TYPES))], [t.replace("_", " ") for t in TYPES], fontsize=10.5)
    ax.tick_params(length=0)

    cmap = {
        1: "#dde7ff",
        2: "#93b0ff",
        3: "#4169e1",
    }

    for row, _type in enumerate(TYPES):
        for col, sprint in enumerate(sprint_labels):
            value = COUNTS[sprint][row]
            ax.add_patch(
                Rectangle((col, row), 1, 1, facecolor=cmap[value], edgecolor="white", linewidth=1.8)
            )
            ax.text(
                col + 0.5,
                row + 0.5,
                str(value),
                ha="center",
                va="center",
                fontsize=14,
                fontweight="bold",
                color="#1f1f1f" if value < 3 else "white",
            )

    for spine in ax.spines.values():
        spine.set_visible(False)

    fig.text(0.12, 0.91, "Dataset coverage by follow-up type", fontsize=15, fontweight="bold", color="#202020")
    fig.text(0.12, 0.875, "34 expected follow-ups across 3 sprints and 6 evaluable transitions", fontsize=10.5, color="#404040")

    for idx, total in enumerate(sprint_totals):
        fig.text(0.23 + idx * 0.25, 0.09, f"{total}", ha="center", va="center", fontsize=12, fontweight="bold", color="#202020")
    fig.text(0.03, 0.09, "Per sprint total", ha="left", va="center", fontsize=10.5, color="#404040")

    fig.text(0.90, 0.78, "Type total", ha="center", va="center", fontsize=10.5, color="#404040", rotation=90)
    for idx, total in enumerate(totals):
        fig.text(0.91, 0.80 - idx * 0.097, str(total), ha="center", va="center", fontsize=11.5, fontweight="bold", color="#202020")

    fig.savefig(OUT_DIR / "plot_3_2_followup_coverage.png", dpi=220, bbox_inches="tight", pad_inches=0.06)
    plt.close(fig)


if __name__ == "__main__":
    main()
