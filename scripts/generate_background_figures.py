from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle


ROOT = Path(__file__).resolve().parents[1]
OUT_DIRS = [
    ROOT / "memoria" / "cdia" / "img",
    ROOT / "memoria" / "ingenieria" / "img",
]


def _style():
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 11,
            "axes.facecolor": "white",
            "figure.facecolor": "white",
        }
    )


def generate_layers(out_dir: Path) -> None:
    fig, ax = plt.subplots(figsize=(14, 2.6))
    ax.set_xlim(0, 16)
    ax.set_ylim(0, 3)
    ax.axis("off")

    informal_bg = "#fbf6cf"
    formal_bg = "#fbf6cf"
    box_bg = "#f3f3f3"
    edge = "#555555"
    accent = "#666666"

    ax.add_patch(Rectangle((0, 0.15), 7.4, 2.55, facecolor=informal_bg, edgecolor=edge, linewidth=1.2))
    ax.add_patch(Rectangle((8.6, 0.15), 7.4, 2.55, facecolor=formal_bg, edgecolor=edge, linewidth=1.2))

    ax.text(3.7, 2.52, "Informal layer", ha="center", va="center", fontsize=14, weight="bold", color="#333333")
    ax.text(12.3, 2.52, "Formal layer", ha="center", va="center", fontsize=14, weight="bold", color="#333333")

    informal_boxes = [
        (0.55, 0.85, 1.7, 1.05, "Planning"),
        (2.55, 0.85, 1.7, 1.05, "Standup"),
        (4.55, 0.85, 1.9, 1.05, "Ad-hoc"),
        (6.65, 0.85, 0.7, 1.05, "Retro"),
    ]
    formal_boxes = [
        (9.0, 0.65, 1.8, 1.35, "Issues"),
        (11.0, 0.65, 1.4, 1.35, "Git"),
        (12.8, 0.85, 2.2, 1.05, "Docs"),
    ]

    for x, y, w, h, label in informal_boxes + formal_boxes:
        ax.add_patch(Rectangle((x, y), w, h, facecolor=box_bg, edgecolor=edge, linewidth=0.8))
        ax.text(x + w / 2, y + h / 2, label, ha="center", va="center", fontsize=12.5, color="#333333")

    ax.annotate(
        "",
        xy=(8.55, 1.32),
        xytext=(7.45, 1.32),
        arrowprops={"arrowstyle": "->", "linewidth": 1.4, "linestyle": "--", "color": accent},
    )
    ax.text(8.0, 1.75, "loss / lag", ha="center", va="center", fontsize=10.5, color="#333333", weight="bold")

    fig.savefig(out_dir / "fig_2_1_layers.png", dpi=220, bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)


def generate_quadrant(out_dir: Path) -> None:
    fig, ax = plt.subplots(figsize=(6.8, 6.8))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xticks([])
    ax.set_yticks([])

    top_fill = "#eef0ff"
    bottom_fill = "#f8f8fb"
    line = "#c8cbe6"
    text = "#202020"

    ax.add_patch(Rectangle((0, 0.5), 0.5, 0.5, facecolor=top_fill, edgecolor="none"))
    ax.add_patch(Rectangle((0.5, 0.5), 0.5, 0.5, facecolor=top_fill, edgecolor="none"))
    ax.add_patch(Rectangle((0, 0), 0.5, 0.5, facecolor=bottom_fill, edgecolor="none"))
    ax.add_patch(Rectangle((0.5, 0), 0.5, 0.5, facecolor=bottom_fill, edgecolor="none"))
    ax.axhline(0.5, color=line, linewidth=1.2)
    ax.axvline(0.5, color=line, linewidth=1.2)

    for spine in ax.spines.values():
        spine.set_color(line)
        spine.set_linewidth(1.2)

    ax.text(0.05, 0.96, "Cloud + cross", fontsize=10.5, color=text)
    ax.text(0.64, 0.96, "Local + cross", fontsize=10.5, color=text)
    ax.text(0.05, 0.47, "Cloud + single", fontsize=10.5, color=text)
    ax.text(0.62, 0.47, "Local + single", fontsize=10.5, color=text)

    points = [
        ("Otter", 0.18, 0.18, (-18, -10)),
        ("Fireflies", 0.22, 0.30, (-16, -10)),
        ("Granola", 0.30, 0.42, (-16, -10)),
        ("Local notes", 0.75, 0.12, (-10, -10)),
        ("This work", 0.88, 0.88, (-8, -10)),
    ]

    for label, x, y, offset in points:
        ax.scatter([x], [y], s=42, color="#3d3d3d", zorder=3)
        ax.annotate(
            label,
            (x, y),
            xytext=offset,
            textcoords="offset points",
            fontsize=10.5,
            color=text,
        )

    fig.text(0.23, 0.03, "Cloud-hosted", ha="center", va="center", fontsize=12, weight="bold", color=text)
    fig.text(0.73, 0.03, "Local-first", ha="center", va="center", fontsize=12, weight="bold", color=text)
    fig.text(0.03, 0.24, "Single meeting", ha="center", va="center", rotation=90, fontsize=12, weight="bold", color=text)
    fig.text(0.03, 0.74, "Cross-meeting", ha="center", va="center", rotation=90, fontsize=12, weight="bold", color=text)

    fig.savefig(out_dir / "fig_2_3_quadrant.png", dpi=220, bbox_inches="tight", pad_inches=0.08)
    plt.close(fig)


def main() -> None:
    _style()
    for out_dir in OUT_DIRS:
        out_dir.mkdir(parents=True, exist_ok=True)
        generate_layers(out_dir)
        generate_quadrant(out_dir)


if __name__ == "__main__":
    main()
