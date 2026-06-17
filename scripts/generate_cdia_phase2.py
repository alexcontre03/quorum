"""
Post-process the evaluation outputs of run_cdia_evaluation.py and produce:

- fig_7_5_3_confusion_matrix.png  — heatmap of the 7x7 confusion matrix
                                    under the "current sprint" retrieval mode.
- plot_7_5_3_recall_by_type.png   — grouped bar chart of per-type recall
                                    across the three retrieval modes.
- markdown snippets for §7.5.1 (extraction table) and §7.5.2 (followup
  results table) that the operator can paste into the corresponding .md.

Reads `app/data/followup_evaluation_runs/cdia_combined_summary.json`.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# Bump every default font size so the rendered figures are legible at the
# 14 cm width they are inserted with in the memoir. The previous defaults
# produced labels that, after scaling, sat well below the body font size.
plt.rcParams.update({
    "font.size": 16,
    "axes.titlesize": 18,
    "axes.labelsize": 16,
    "xtick.labelsize": 14,
    "ytick.labelsize": 14,
    "legend.fontsize": 14,
    "legend.title_fontsize": 14,
    "figure.titlesize": 18,
})


ROOT = Path(__file__).resolve().parent.parent
SUMMARY = ROOT / "app" / "data" / "followup_evaluation_runs" / "cdia_combined_summary__embed.json"
IMG_DIR = ROOT / "memoria" / "cdia" / "img"
IMG_DIR.mkdir(parents=True, exist_ok=True)
SNIP_DIR = ROOT / "memoria" / "cdia"

FOLLOWUP_TYPES = [
    "recurring_unresolved",
    "scope_change",
    "new_blocker",
    "blocker_resolved",
    "possible_duplicate",
    "contradicts_decision",
    "verbal_close",
]
SHORT = {
    "recurring_unresolved": "recurring",
    "scope_change": "scope",
    "new_blocker": "blocker_new",
    "blocker_resolved": "blocker_res",
    "possible_duplicate": "duplicate",
    "contradicts_decision": "contradicts",
    "verbal_close": "verbal_close",
}


def render_confusion_matrix(
    cm: dict[str, dict[str, int]], out_path: Path,
    *, mode_label: str = "current sprint",
    system_label: str = "frontier gpt-4o-mini",
) -> None:
    """Render the 7x7 confusion matrix as a heatmap (grayscale, print-friendly).
    The title shows the retrieval mode and the system whose matrix is plotted
    so that the figure is unambiguous when it appears in the memoir."""
    n = len(FOLLOWUP_TYPES)
    mat = np.zeros((n, n), dtype=int)
    for i, row_t in enumerate(FOLLOWUP_TYPES):
        row = cm.get(row_t, {})
        for j, col_t in enumerate(FOLLOWUP_TYPES):
            mat[i, j] = row.get(col_t, 0)

    fig, ax = plt.subplots(figsize=(9, 7))
    im = ax.imshow(mat, cmap="Greys", aspect="auto")
    ax.set_xticks(range(n))
    ax.set_yticks(range(n))
    ax.set_xticklabels([SHORT[t] for t in FOLLOWUP_TYPES], rotation=40, ha="right")
    ax.set_yticklabels([SHORT[t] for t in FOLLOWUP_TYPES])
    ax.set_xlabel("Predicted")
    ax.set_ylabel("Labelled")
    ax.set_title(f"Confusion matrix, {system_label}, '{mode_label}' retrieval mode")
    for i in range(n):
        for j in range(n):
            color = "white" if mat[i, j] > mat.max() / 2 else "black"
            ax.text(j, i, str(mat[i, j]), ha="center", va="center", color=color, fontsize=14)
    plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04, label="Count")
    plt.tight_layout()
    plt.savefig(out_path, dpi=200)
    plt.close(fig)
    print(f"  wrote {out_path}")


def render_recall_by_type(followup: dict, out_path: Path) -> None:
    """Grouped bar chart of per-type recall across the three retrieval modes."""
    modes = ["off", "current", "all"]
    n_types = len(FOLLOWUP_TYPES)
    n_modes = len(modes)
    width = 0.27
    x = np.arange(n_types)

    fig, ax = plt.subplots(figsize=(11, 5))
    hatches = ["", "//", "xx"]
    for k, mode in enumerate(modes):
        rec = followup.get(mode, {}).get("recall_by_type", {}) or {}
        ys = [rec.get(t, 0.0) for t in FOLLOWUP_TYPES]
        ax.bar(x + (k - 1) * width, ys, width, label=mode, color="white",
               edgecolor="black", hatch=hatches[k])
    ax.set_xticks(x)
    ax.set_xticklabels([SHORT[t] for t in FOLLOWUP_TYPES], rotation=30, ha="right")
    ax.set_ylabel("Recall")
    ax.set_title("Per-type recall by retrieval mode")
    ax.set_ylim(0, 1)
    ax.legend(title="Retrieval mode")
    ax.grid(True, axis="y", linestyle=":", linewidth=0.5)
    plt.tight_layout()
    plt.savefig(out_path, dpi=200)
    plt.close(fig)
    print(f"  wrote {out_path}")


def md_table_extraction(extraction: dict) -> str:
    e = extraction
    return (
        "| Aggregate | Precision | Recall | F1 |\n"
        "|-----------|----------:|-------:|---:|\n"
        f"| Micro | {e['precision_micro']:.3f} | {e['recall_micro']:.3f} | {e['f1_micro']:.3f} |\n"
        f"| Macro | {e['precision_macro']:.3f} | {e['recall_macro']:.3f} | {e['f1_macro']:.3f} |\n"
        f"\nExpected items: {e['expected_count']}. Matched items: {e['matched_count']}.\n"
    )


def md_table_followup(followup: dict) -> str:
    header = (
        "| Retrieval mode | Pairs | Coverage | Precision micro | Recall micro | F1 micro | Precision macro | Recall macro | F1 macro |\n"
        "|----------------|------:|---------:|----------------:|-------------:|---------:|----------------:|-------------:|---------:|\n"
    )
    rows = ""
    for mode in ["off", "current", "all"]:
        s = followup.get(mode)
        if not s:
            continue
        rows += (
            f"| `{mode}` | {s['completed_pairs']}/{s['pair_count']} | "
            f"{s['coverage']:.3f} | "
            f"{s['precision_micro']:.3f} | {s['recall_micro']:.3f} | {s['f1_micro']:.3f} | "
            f"{s['precision_macro']:.3f} | {s['recall_macro']:.3f} | {s['f1_macro']:.3f} |\n"
        )
    return header + rows


def md_table_per_type(followup: dict) -> str:
    """Per-type recall under the current-sprint mode (the operational baseline)."""
    cur = followup.get("current", {})
    rec = cur.get("recall_by_type", {}) or {}
    prec = cur.get("precision_by_type", {}) or {}
    f1 = cur.get("f1_by_type", {}) or {}
    out = "| Follow-up type | Precision | Recall | F1 |\n|----------------|----------:|-------:|---:|\n"
    for t in FOLLOWUP_TYPES:
        out += f"| `{t}` | {prec.get(t, 0.0):.3f} | {rec.get(t, 0.0):.3f} | {f1.get(t, 0.0):.3f} |\n"
    return out


def render_recall_comparison(followup_local: dict, followup_openai: dict, out_path: Path) -> None:
    """Grouped bar chart comparing local vs frontier recall across the three
    retrieval modes."""
    modes = ["off", "current", "all"]
    n_modes = len(modes)
    width = 0.35
    x = np.arange(n_modes)

    fig, ax = plt.subplots(figsize=(8, 5))
    local_vals = [followup_local.get(m, {}).get("recall_micro", 0.0) for m in modes]
    openai_vals = [followup_openai.get(m, {}).get("recall_micro", 0.0) for m in modes]
    ax.bar(x - width / 2, local_vals, width, label="local qwen2.5:7b", color="white",
           edgecolor="black", hatch="//")
    ax.bar(x + width / 2, openai_vals, width, label="frontier gpt-4o-mini", color="white",
           edgecolor="black", hatch="..")
    ax.set_xticks(x)
    ax.set_xticklabels(modes)
    ax.set_ylabel("Micro recall on the 7-class problem")
    ax.set_title("Local vs frontier comparison across retrieval modes")
    ax.set_ylim(0, 0.40)
    ax.legend()
    ax.grid(True, axis="y", linestyle=":", linewidth=0.5)
    for i, v in enumerate(local_vals):
        ax.text(i - width / 2, v + 0.01, f"{v:.3f}", ha="center", fontsize=9)
    for i, v in enumerate(openai_vals):
        ax.text(i + width / 2, v + 0.01, f"{v:.3f}", ha="center", fontsize=9)
    plt.tight_layout()
    plt.savefig(out_path, dpi=200)
    plt.close(fig)
    print(f"  wrote {out_path}")


def md_table_followup_compare(local: dict, openai: dict) -> str:
    """Two-section table: local vs frontier under the same protocol."""
    out = (
        "| System | Retrieval | Pairs | Coverage | Precision | Recall | F1 |\n"
        "|--------|-----------|------:|---------:|----------:|-------:|---:|\n"
    )
    for mode in ["off", "current", "all"]:
        s = local.get(mode)
        if s:
            out += (
                f"| Local `qwen2.5:7b` | `{mode}` | "
                f"{s['completed_pairs']}/{s['pair_count']} | "
                f"{s['coverage']:.3f} | "
                f"{s['precision_micro']:.3f} | {s['recall_micro']:.3f} | {s['f1_micro']:.3f} |\n"
            )
    for mode in ["off", "current", "all"]:
        s = openai.get(mode)
        if s:
            out += (
                f"| Frontier `gpt-4o-mini` | `{mode}` | "
                f"{s['completed_pairs']}/{s['pair_count']} | "
                f"{s['coverage']:.3f} | "
                f"{s['precision_micro']:.3f} | {s['recall_micro']:.3f} | {s['f1_micro']:.3f} |\n"
            )
    return out


def main() -> None:
    if not SUMMARY.exists():
        raise SystemExit(f"Summary not found at {SUMMARY}.")

    data = json.loads(SUMMARY.read_text(encoding="utf-8"))
    extraction = data["extraction"]
    local = data.get("followup_local", {})
    openai = data.get("followup_openai", {})

    # Confusion matrix of the frontier under current sprint mode (headline)
    cur_cm = openai.get("current", {}).get("confusion_matrix", {})
    if cur_cm:
        render_confusion_matrix(cur_cm, IMG_DIR / "fig_7_5_3_confusion_matrix.png")
    else:
        print("  WARN: no confusion matrix for openai 'current' mode")

    # Per-type recall under the three modes (frontier, the headline system)
    render_recall_by_type(openai, IMG_DIR / "plot_7_5_3_recall_by_type.png")

    # Local vs frontier comparison
    render_recall_comparison(local, openai, IMG_DIR / "plot_7_5_3_local_vs_frontier.png")

    snippets = SNIP_DIR / "_phase2_snippets.md"
    snippets.write_text(
        "## §7.5.1 — Extraction results table\n\n" + md_table_extraction(extraction) +
        "\n## §7.5.2 — Follow-up reasoning results: local vs frontier across retrieval modes\n\n" +
        md_table_followup_compare(local, openai) +
        "\n## §7.5.3 — Per-type metrics (frontier, current sprint mode)\n\n" + md_table_per_type(openai),
        encoding="utf-8",
    )
    print(f"  wrote {snippets}")


if __name__ == "__main__":
    main()
