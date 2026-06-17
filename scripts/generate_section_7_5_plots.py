"""Generate the four §7.5 plots for the CDIA memoir.

Reads the rescored ``__embed.json`` files under
``app/data/followup_evaluation_runs/`` and writes the figures under
``memoria/cdia/img/``.

The plots produced:

- ``fig_7_5_3_confusion_matrix.png`` — 7x7 confusion matrix of the
  headline configuration (local 7B strict, mode off).
- ``plot_7_5_3_recall_by_type.png`` — per-type recall, three bars per
  type (local strict, local soft, frontier soft).
- ``plot_7_5_3_local_vs_frontier.png`` — micro recall and F1 across the
  three retrieval modes, comparing local strict vs frontier soft.
- ``plot_7_5_3_strict_vs_soft.png`` — sensitivity of the
  ``trigger_quote`` contract on the local 7B across the three modes.

Run after ``rescore_with_embeddings.py``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "app" / "data" / "followup_evaluation_runs"
IMG = ROOT / "memoria" / "cdia" / "img"
IMG.mkdir(parents=True, exist_ok=True)

TYPES = (
    "recurring_unresolved",
    "scope_change",
    "new_blocker",
    "blocker_resolved",
    "possible_duplicate",
    "contradicts_decision",
    "verbal_close",
)

# Short labels for plot axes (avoid cluttered ticks).
SHORT = {
    "recurring_unresolved": "recurring",
    "scope_change": "scope_chg",
    "new_blocker": "new_blocker",
    "blocker_resolved": "blocker_res",
    "possible_duplicate": "duplicate",
    "contradicts_decision": "contradict",
    "verbal_close": "verbal_close",
}

# Centralised typography settings: the tutor noted that figure text was
# unreadably small in the previous build. Bump font sizes here.
plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 13,
    "axes.titlesize": 15,
    "axes.labelsize": 13,
    "xtick.labelsize": 12,
    "ytick.labelsize": 12,
    "legend.fontsize": 12,
    "figure.dpi": 150,
})


def _load(path: Path) -> dict:
    if not path.exists():
        print(f"  missing: {path.name}", file=sys.stderr)
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def confusion_matrix() -> None:
    """Confusion matrix for local strict off (headline configuration)."""
    d = _load(RUNS / "cdia_followup_en_strict_off__embed.json")
    cm = d.get("summary", {}).get("confusion_matrix", {})
    if not cm:
        print("  no confusion matrix available for local strict off")
        return
    n = len(TYPES)
    grid = np.zeros((n, n), dtype=int)
    for ei, e in enumerate(TYPES):
        row = cm.get(e, {})
        for pi, p in enumerate(TYPES):
            grid[ei][pi] = row.get(p, 0)
    # Include an extra column for the "no prediction" cell when present.
    fig, ax = plt.subplots(figsize=(8, 7))
    im = ax.imshow(grid, cmap="Blues", aspect="auto")
    ax.set_xticks(range(n))
    ax.set_yticks(range(n))
    ax.set_xticklabels([SHORT[t] for t in TYPES], rotation=35, ha="right")
    ax.set_yticklabels([SHORT[t] for t in TYPES])
    ax.set_xlabel("Predicted type")
    ax.set_ylabel("Expected type")
    ax.set_title("Confusion matrix — local qwen2.5:7b strict, mode off")
    for i in range(n):
        for j in range(n):
            v = grid[i, j]
            if v:
                ax.text(
                    j, i, str(v),
                    ha="center", va="center",
                    color="white" if v > grid.max() / 2 else "black",
                    fontsize=12,
                )
    fig.colorbar(im, ax=ax, shrink=0.7, label="count")
    fig.tight_layout()
    out = IMG / "fig_7_5_3_confusion_matrix.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {out.name}")


def recall_by_type() -> None:
    """Per-type recall of the headline local configuration across the three modes."""
    modes = [
        ("off", RUNS / "cdia_followup_en_strict_off__embed.json", "#1f4e79"),
        ("current sprint", RUNS / "cdia_followup_en_strict_current__embed.json", "#6fa0d6"),
        ("all sprints", RUNS / "cdia_followup_en_strict_all__embed.json", "#a8c8e0"),
    ]
    values = []
    labels = []
    for name, p, color in modes:
        d = _load(p)
        rbt = d.get("summary", {}).get("recall_by_type", {})
        if not rbt:
            continue
        values.append([rbt.get(t, 0.0) for t in TYPES])
        labels.append((name, color))
    if not values:
        return
    x = np.arange(len(TYPES))
    width = 0.27
    fig, ax = plt.subplots(figsize=(11, 6))
    for i, ((name, color), v) in enumerate(zip(labels, values)):
        ax.bar(x + (i - 1) * width, v, width, label=f"mode = {name}", color=color)
    ax.set_xticks(x)
    ax.set_xticklabels([SHORT[t] for t in TYPES], rotation=20, ha="right")
    ax.set_ylabel("Recall")
    ax.set_ylim(0.0, 1.05)
    ax.set_title("Per-type recall of the local qwen2.5:7b strict pipeline across retrieval modes")
    ax.legend(loc="upper right")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    out = IMG / "plot_7_5_3_recall_by_type.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {out.name}")


def recall_by_type_local_vs_frontier() -> None:
    """Comparison plot for section 7.6: local strict off vs frontier soft off per type."""
    configs = [
        ("Local 7B strict off", RUNS / "cdia_followup_en_strict_off__embed.json", "#1f4e79"),
        ("Frontier 4o-mini soft off", RUNS / "cdia_followup_openai_en_soft_off__embed.json", "#d99641"),
    ]
    values = []
    labels = []
    for name, p, color in configs:
        d = _load(p)
        rbt = d.get("summary", {}).get("recall_by_type", {})
        if not rbt:
            continue
        values.append([rbt.get(t, 0.0) for t in TYPES])
        labels.append((name, color))
    if not values:
        return
    x = np.arange(len(TYPES))
    width = 0.32
    fig, ax = plt.subplots(figsize=(11, 6))
    for i, ((name, color), v) in enumerate(zip(labels, values)):
        ax.bar(x + (i - 0.5) * width, v, width, label=name, color=color)
    ax.set_xticks(x)
    ax.set_xticklabels([SHORT[t] for t in TYPES], rotation=20, ha="right")
    ax.set_ylabel("Recall")
    ax.set_ylim(0.0, 1.05)
    ax.set_title("Per-type recall: local 7B strict vs frontier 4o-mini soft (mode off)")
    ax.legend(loc="upper right")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    out = IMG / "plot_7_6_recall_by_type_local_vs_frontier.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {out.name}")


def local_vs_frontier() -> None:
    """Headline: recall and F1 across the three retrieval modes, each model under its optimal prompt contract."""
    modes = ["off", "current", "all"]
    local_recall = []
    local_f1 = []
    frontier_recall = []
    frontier_f1 = []
    for m in modes:
        l = _load(RUNS / f"cdia_followup_en_strict_{m}__embed.json").get("summary", {})
        f = _load(RUNS / f"cdia_followup_openai_en_soft_{m}__embed.json").get("summary", {})
        local_recall.append(l.get("recall_micro", 0.0))
        local_f1.append(l.get("f1_micro", 0.0))
        frontier_recall.append(f.get("recall_micro", 0.0))
        frontier_f1.append(f.get("f1_micro", 0.0))
    x = np.arange(len(modes))
    width = 0.2
    fig, ax = plt.subplots(figsize=(9, 5.5))
    ax.bar(x - 1.5 * width, local_recall, width, label="Local 7B strict (recall)", color="#1f4e79")
    ax.bar(x - 0.5 * width, local_f1, width, label="Local 7B strict (F1)", color="#6fa0d6")
    ax.bar(x + 0.5 * width, frontier_recall, width, label="Frontier 4o-mini soft (recall)", color="#a44a3f")
    ax.bar(x + 1.5 * width, frontier_f1, width, label="Frontier 4o-mini soft (F1)", color="#d99641")
    ax.set_xticks(x)
    ax.set_xticklabels(modes)
    ax.set_xlabel("Retrieval mode")
    ax.set_ylabel("Score")
    ax.set_ylim(0.0, 0.6)
    ax.set_title("Micro recall and F1 across retrieval modes (local strict vs frontier soft)")
    ax.legend(loc="upper right", fontsize=10)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    out = IMG / "plot_7_5_3_local_vs_frontier.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {out.name}")


def strict_vs_soft() -> None:
    """Sensitivity: trigger_quote contract on both models across the three modes.

    Exposes the model-by-contract interaction: the contract helps the smaller
    model and hurts the larger one.
    """
    modes = ["off", "current", "all"]
    local_strict = []
    local_soft = []
    frontier_strict = []
    frontier_soft = []
    for m in modes:
        local_strict.append(_load(RUNS / f"cdia_followup_en_strict_{m}__embed.json").get("summary", {}).get("recall_micro", 0.0))
        local_soft.append(_load(RUNS / f"cdia_followup_en_soft_{m}__embed.json").get("summary", {}).get("recall_micro", 0.0))
        frontier_strict.append(_load(RUNS / f"cdia_followup_openai_en_strict_{m}__embed.json").get("summary", {}).get("recall_micro", 0.0))
        frontier_soft.append(_load(RUNS / f"cdia_followup_openai_en_soft_{m}__embed.json").get("summary", {}).get("recall_micro", 0.0))
    x = np.arange(len(modes))
    width = 0.2
    fig, ax = plt.subplots(figsize=(10, 5.5))
    ax.bar(x - 1.5 * width, local_strict, width, label="Local 7B, strict", color="#1f4e79")
    ax.bar(x - 0.5 * width, local_soft, width, label="Local 7B, soft", color="#6fa0d6")
    ax.bar(x + 0.5 * width, frontier_strict, width, label="Frontier 4o-mini, strict", color="#a44a3f")
    ax.bar(x + 1.5 * width, frontier_soft, width, label="Frontier 4o-mini, soft", color="#d99641")
    ax.set_xticks(x)
    ax.set_xticklabels(modes)
    ax.set_xlabel("Retrieval mode")
    ax.set_ylabel("Recall (micro)")
    ax.set_ylim(0.0, 0.45)
    ax.set_title("Interaction of model and trigger_quote contract")
    ax.legend(loc="upper right", fontsize=10)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    out = IMG / "plot_7_5_3_strict_vs_soft.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {out.name}")


def main() -> None:
    print("Generating §7.5 and §7.6 plots:")
    confusion_matrix()
    recall_by_type()
    recall_by_type_local_vs_frontier()
    local_vs_frontier()
    strict_vs_soft()
    print("Done.")


if __name__ == "__main__":
    main()
