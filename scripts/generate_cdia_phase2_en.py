"""Render the §7.5 figures and tables for the EN-translated evaluation.

Reads `app/data/followup_evaluation_runs/cdia_combined_summary_en__embed.json`
and writes:

- fig_7_5_3_confusion_matrix.png  — heatmap of the 7x7 confusion matrix
                                    under the "all sprints" retrieval mode
                                    (the headline configuration of the EN run).
- plot_7_5_3_recall_by_type.png   — grouped bar chart of per-type recall
                                    under the three retrieval modes (frontier).
- plot_7_5_3_local_vs_frontier.png — grouped bar chart of recall_micro by
                                     retrieval mode for local vs frontier.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.generate_cdia_phase2 import (  # noqa: E402
    render_confusion_matrix,
    render_recall_by_type,
    render_recall_comparison,
)

ROOT = Path(__file__).resolve().parent.parent
SUMMARY = ROOT / "app" / "data" / "followup_evaluation_runs" / "cdia_combined_summary_en__embed.json"
IMG_DIR = ROOT / "memoria" / "cdia" / "img"
IMG_DIR.mkdir(parents=True, exist_ok=True)


def main() -> None:
    if not SUMMARY.exists():
        raise SystemExit(f"Summary not found at {SUMMARY}.")
    data = json.loads(SUMMARY.read_text(encoding="utf-8"))
    local = data.get("followup_local", {})
    openai = data.get("followup_openai", {})

    # The headline of the EN run is `all sprints` mode, not `current`.
    cm = openai.get("all", {}).get("confusion_matrix", {})
    if cm:
        render_confusion_matrix(
            cm,
            IMG_DIR / "fig_7_5_3_confusion_matrix.png",
            mode_label="all sprints",
            system_label="frontier gpt-4o-mini",
        )
        print(f"  wrote {IMG_DIR / 'fig_7_5_3_confusion_matrix.png'}")
    else:
        print("  WARN: no confusion matrix for openai 'all' mode")

    render_recall_by_type(openai, IMG_DIR / "plot_7_5_3_recall_by_type.png")
    print(f"  wrote {IMG_DIR / 'plot_7_5_3_recall_by_type.png'}")

    render_recall_comparison(local, openai, IMG_DIR / "plot_7_5_3_local_vs_frontier.png")
    print(f"  wrote {IMG_DIR / 'plot_7_5_3_local_vs_frontier.png'}")


if __name__ == "__main__":
    main()
