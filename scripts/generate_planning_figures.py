from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "memoria" / "cdia" / "img"


PHASES = [
    ("Phase 1", "Definition and viability", 0.0, 1.0, 30),
    ("Phase 2", "Initial base implementation", 1.0, 2.4, 200),
    ("Phase 3", "Refocus and evaluation", 2.4, 5.0, 240),
    ("Phase 4", "Memoir drafting", 4.9, 6.0, 150),
]

MILESTONES = [
    ("H1", 3.02, 2.05),
    ("H2", 3.22, 2.40),
    ("H3", 3.45, 2.82),
    ("H4", 3.68, 3.10),
    ("H5", 3.95, 2.05),
    ("H6", 4.15, 2.40),
    ("H7", 4.37, 2.85),
    ("H8", 4.62, 2.42),
    ("H9", 4.85, 3.10),
    ("H10", 5.08, 2.83),
    ("H11", 5.33, 2.42),
    ("H12", 5.58, 3.10),
    ("H13", 5.82, 2.40),
    ("H14", 4.60, 2.00),
    ("H15", 5.05, 3.10),
    ("H16", 5.18, 2.05),
    ("H17", 5.32, 2.85),
    ("H18", 5.68, 2.05),
    ("H19", 5.82, 2.85),
]

EVALUATION_HITOS = {"H6", "H7", "H13", "H14"}


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10.5,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
        }
    )

    fig, ax = plt.subplots(figsize=(11.8, 4.7))
    ax.set_xlim(0, 6)
    ax.set_ylim(0, 4)
    ax.set_xticks([i + 0.5 for i in range(6)], [f"Month {i + 1}" for i in range(6)], fontsize=10.5, fontweight="bold")
    ax.set_yticks([])
    ax.tick_params(axis="x", length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)

    for month in range(7):
        ax.axvline(month, color="#d6dbea", linewidth=0.8, zorder=0)

    row_y = {
        "Phase 1": 3.6,
        "Phase 2": 3.32,
        "Phase 3": 1.88,
        "Phase 4": 0.22,
    }

    ax.add_patch(Rectangle((0, 3.48), 6.0, 0.34, facecolor="#dce0ff", edgecolor="none", zorder=0))
    ax.add_patch(Rectangle((0, 3.14), 6.0, 0.34, facecolor="#f3f4fb", edgecolor="none", zorder=0))
    ax.add_patch(Rectangle((0, 0.40), 6.0, 2.55, facecolor="#fff1a8", edgecolor="none", zorder=0))
    ax.add_patch(Rectangle((0, 0.00), 6.0, 0.24, facecolor="#f2f2f2", edgecolor="none", zorder=0))

    ax.text(3.0, 3.96, "Project phases and milestones", ha="center", va="top", fontsize=14, fontweight="bold", color="#202020")

    bar_fill = "#8b93e6"
    bar_edge = "#5d63cf"
    for phase_code, label, start, end, hours in PHASES:
        y = row_y[phase_code]
        height = 0.20 if phase_code != "Phase 3" else 0.18
        ax.add_patch(
            Rectangle((start, y - height / 2), end - start, height, facecolor=bar_fill, edgecolor=bar_edge, linewidth=1.2, zorder=2)
        )
        ax.text(-0.22, y, phase_code, ha="left", va="center", fontsize=9.8, fontweight="bold", color="#1f2430", clip_on=False)
        if phase_code == "Phase 1":
            ax.text((start + end) / 2, y, "Def. + viability", ha="center", va="center", fontsize=7.8, color="white")
        elif phase_code == "Phase 2":
            ax.text((start + end) / 2, y, "Pipeline v1 and UI prototype", ha="center", va="center", fontsize=8.2, color="white")
        elif phase_code == "Phase 3":
            ax.text((start + end) / 2, y, "Refactor and evaluation", ha="center", va="center", fontsize=8.3, color="white")
        else:
            ax.text((start + end) / 2, y, "Drafting", ha="center", va="center", fontsize=8.3, color="white")

    milestone_fill = "#93a3ff"
    milestone_edge = "#5667cf"
    eval_fill = "#f8a343"
    eval_edge = "#d47a1e"

    for label, x, y in MILESTONES:
        is_eval = label in EVALUATION_HITOS
        face = eval_fill if is_eval else milestone_fill
        edge = eval_edge if is_eval else milestone_edge
        ax.scatter([x], [y], marker="D", s=90, c=face, edgecolors=edge, linewidths=1.2, zorder=3)
        ax.text(x + 0.05, y, label, ha="left", va="center", fontsize=8.1, fontweight="bold", color="#111111")

    legend = [
        Line2D([0], [0], marker="D", color="none", markerfacecolor=milestone_fill, markeredgecolor=milestone_edge, markersize=7, label="Milestone"),
        Line2D([0], [0], marker="D", color="none", markerfacecolor=eval_fill, markeredgecolor=eval_edge, markersize=7, label="Evaluation milestone"),
    ]
    ax.legend(handles=legend, loc="lower right", bbox_to_anchor=(0.93, 0.02), frameon=False, fontsize=7.7, handletextpad=0.6, borderaxespad=0.0)

    fig.savefig(OUT_DIR / "fig_4_2_gantt.png", dpi=220, bbox_inches="tight", pad_inches=0.06)
    plt.close(fig)


if __name__ == "__main__":
    main()
