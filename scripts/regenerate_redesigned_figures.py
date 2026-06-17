"""Regenerate the three figures of the CDIA memoir that needed a redesign.

Design rules (driven by the tutor's note that figures are unreadable when
reduced to A4 page width):

- large fonts (>= 14pt), high contrast, minimal text inside the figure.
- one main idea per figure.
- light backgrounds, no fancy colour ramps, no decorative elements.

The three figures regenerated here:

- ``fig_4_2_gantt.png`` — phases x time with milestone strip.
- ``fig_6_1_hitos.png`` — sequence of the nineteen milestones with the
  evaluative inflection points highlighted.
- ``fig_7_1_1_commitment_lifecycle.png`` — state diagram of the commitment
  lifecycle, including the ``in_code_review`` state inserted by Decision 023.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

ROOT = Path(__file__).resolve().parent.parent
IMG = ROOT / "memoria" / "cdia" / "img"
IMG_INF = ROOT / "memoria" / "ingenieria" / "img"
IMG.mkdir(parents=True, exist_ok=True)
IMG_INF.mkdir(parents=True, exist_ok=True)


def _save_shared(fig, name: str) -> None:
    """Save a figure to both the CDIA and INF image directories."""
    for target in (IMG, IMG_INF):
        out = target / name
        fig.savefig(out, dpi=150, bbox_inches="tight")
        print(f"  wrote {out.relative_to(ROOT)}")

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 14,
    "axes.titlesize": 16,
    "axes.labelsize": 14,
    "xtick.labelsize": 13,
    "ytick.labelsize": 13,
    "legend.fontsize": 12,
    "figure.dpi": 150,
})


# --- Colour palette (calm, prints well in B/W too) -------------------------
INK = "#1a1a1a"
MUTED = "#7a7a7a"
PHASE_COLOURS = {
    "Phase 1": "#cfd8dc",
    "Phase 2": "#90a4ae",
    "Phase 3": "#455a64",
    "Phase 4": "#cfd8dc",
}
HITO_GROUPS = {
    # H1-H8: foundation and dataset
    "Foundation (H1-H8)": ("#3a6ea5", range(1, 9)),
    # H9-H13: evaluation, retrieval, lifecycle integration
    "Evaluation and lifecycle (H9-H13)": ("#d9822b", range(9, 14)),
    # H14-H19: provider abstraction, guardrails, GitHub
    "Provider, guardrails, GitHub (H14-H19)": ("#6a994e", range(14, 20)),
}
EVAL_INFLECTIONS = {6, 7, 13, 14}


# ---------------------------------------------------------------------------
# fig_4_2_gantt.png
# ---------------------------------------------------------------------------
def gantt() -> None:
    fig, ax = plt.subplots(figsize=(11, 3.6))

    # Phase bars (one row each). Time axis is relative months 1..6.
    phases = [
        ("Phase 1: Definition", 0.5, 1.0, "30 h"),
        ("Phase 2: Base implementation", 1.0, 2.0, "200 h"),
        ("Phase 3: Refocus and evaluation", 3.0, 1.5, "240 h"),
        ("Phase 4: Memoir drafting", 4.5, 1.5, "150 h"),
    ]
    y_phases = list(range(len(phases), 0, -1))  # 4..1 (top to bottom)

    for (label, x, w, hours), y in zip(phases, y_phases):
        ax.barh(y, w, left=x, height=0.55,
                color=PHASE_COLOURS[label.split(":")[0]],
                edgecolor=INK, linewidth=0.8, zorder=2)
        # Phase code on the left of the bar.
        ax.text(x - 0.1, y, label.split(":")[0],
                va="center", ha="right", fontsize=13, color=INK,
                fontweight="bold", zorder=3)
        # Phase title centred inside the bar.
        ax.text(x + w / 2, y, label.split(": ")[1],
                va="center", ha="center", fontsize=12.5, color=INK, zorder=3)
        # Hours to the right of the bar.
        ax.text(x + w + 0.1, y, hours,
                va="center", ha="left", fontsize=12.5, color=MUTED, zorder=3)

    ax.set_xlim(-0.05, 6.6)
    ax.set_ylim(0.3, len(phases) + 0.8)
    ax.set_xticks([1, 2, 3, 4, 5, 6])
    ax.set_xticklabels([f"Month {i}" for i in [1, 2, 3, 4, 5, 6]])
    ax.set_yticks([])
    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color(MUTED)
    ax.grid(axis="x", color="#e0e0e0", zorder=0)

    fig.tight_layout()
    _save_shared(fig, "fig_4_2_gantt.png")
    plt.close(fig)


# ---------------------------------------------------------------------------
# fig_6_1_hitos.png
# ---------------------------------------------------------------------------
HITO_LABELS = {
    1: "Commitment as first-class entity",
    2: "Git as input to follow-up reasoning",
    3: "Commitment board as home",
    4: "Commitment detail with quote-first timeline",
    5: "Analyze meeting as ingestion plus triage",
    6: "Chained-transition evaluation",
    7: "RAG retrieval with sprint scoping",
    8: "Meetings as stateful sources",
    9: "Sprint as first-class concept",
    10: "Q&A surface over the history",
    11: "Refresh commitment against Jira/Git/GitHub",
    12: "Two-way Jira sync (state, scope, blockers)",
    13: "Per-agent model assignment",
    14: "Provider abstraction (Ollama/OpenAI/Anthropic)",
    15: "Model selector with per-provider override",
    16: "Intent-aware retrieval",
    17: "Visual redesign and design tokens",
    18: "Q&A guardrails (input, scope, grounding, audit)",
    19: "GitHub as code-review signal",
}


def hitos_sequence() -> None:
    fig, ax = plt.subplots(figsize=(9, 11))

    n = 19
    # y positions: H1 at top, H19 at bottom.
    ys = list(range(n, 0, -1))
    for h, y in zip(range(1, n + 1), ys):
        # Choose colour by group.
        colour = None
        for _label, (c, rng) in HITO_GROUPS.items():
            if h in rng:
                colour = c
                break
        is_inflection = h in EVAL_INFLECTIONS

        # Numbered box on the left.
        box_x = 0.05
        box = FancyBboxPatch(
            (box_x, y - 0.35), 0.10, 0.70,
            boxstyle="round,pad=0.02",
            linewidth=1.5 if is_inflection else 0.8,
            edgecolor=INK if is_inflection else colour,
            facecolor=colour,
        )
        ax.add_patch(box)
        ax.text(box_x + 0.05, y, f"H{h}",
                ha="center", va="center",
                fontsize=15, color="white", fontweight="bold")

        # Label to the right.
        label_text = HITO_LABELS[h]
        weight = "bold" if is_inflection else "normal"
        marker = "  ★" if is_inflection else ""
        ax.text(box_x + 0.18, y, label_text + marker,
                ha="left", va="center",
                fontsize=13.5, color=INK, fontweight=weight)

    # Header.
    ax.text(box_x, n + 1.1,
            "Sequence of the nineteen *hitos* of the project",
            ha="left", va="center", fontsize=15, color=INK, fontweight="bold", style="italic")
    ax.text(box_x, n + 0.5,
            "Star marks the CDIA evaluation inflection points (H6, H7, H13, H14).",
            ha="left", va="center", fontsize=12, color=MUTED)

    ax.set_xlim(0, 1.1)
    ax.set_ylim(0, n + 1.6)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)

    fig.tight_layout()
    _save_shared(fig, "fig_6_1_hitos.png")
    plt.close(fig)


# ---------------------------------------------------------------------------
# fig_7_1_1_commitment_lifecycle.png
# ---------------------------------------------------------------------------
def commitment_lifecycle() -> None:
    fig, ax = plt.subplots(figsize=(7.5, 10))

    # Vertical chain of main states, top to bottom.
    states = [
        ("Detected", "#e8eef5", "#3a6ea5"),
        ("Validated", "#e8eef5", "#3a6ea5"),
        ("Registered", "#e8eef5", "#3a6ea5"),
        ("In code review", "#e8eef5", "#3a6ea5"),
        ("Evidenced", "#e8eef5", "#3a6ea5"),
        ("Closed", "#d4e7d4", "#5a8a5a"),
    ]
    n = len(states)
    cx_main = 0.0
    box_w = 3.0
    box_h = 0.8
    step_y = 1.55
    y_top = (n - 1) * step_y / 2.0  # centre the chain vertically around 0

    centres: dict[str, tuple[float, float]] = {}
    for i, (label, fc, ec) in enumerate(states):
        y = y_top - i * step_y
        centres[label] = (cx_main, y)
        rect = FancyBboxPatch(
            (cx_main - box_w / 2, y - box_h / 2), box_w, box_h,
            boxstyle="round,pad=0.05",
            facecolor=fc, edgecolor=ec, linewidth=2.0,
        )
        ax.add_patch(rect)
        weight = "bold" if label in ("Detected", "Closed") else "normal"
        ax.text(cx_main, y, label,
                ha="center", va="center",
                fontsize=15, color=INK, fontweight=weight)

    # Vertical arrows between consecutive states.
    for a, b in zip([s[0] for s in states[:-1]], [s[0] for s in states[1:]]):
        ax.add_patch(FancyArrowPatch(
            (centres[a][0], centres[a][1] - box_h / 2),
            (centres[b][0], centres[b][1] + box_h / 2),
            arrowstyle="->", mutation_scale=22, linewidth=1.8, color=INK,
        ))

    # Rejected state — branch to the right of Validated.
    cx_rej = cx_main + box_w + 1.6
    cy_rej = centres["Validated"][1]
    rect_rej = FancyBboxPatch(
        (cx_rej - box_w / 2, cy_rej - box_h / 2), box_w, box_h,
        boxstyle="round,pad=0.05",
        facecolor="#fce4ec", edgecolor="#a44a3f", linewidth=2.0,
    )
    ax.add_patch(rect_rej)
    ax.text(cx_rej, cy_rej, "Rejected",
            ha="center", va="center",
            fontsize=15, color=INK, fontweight="bold")
    ax.add_patch(FancyArrowPatch(
        (cx_main + box_w / 2, cy_rej),
        (cx_rej - box_w / 2, cy_rej),
        arrowstyle="->", mutation_scale=20, linewidth=1.6, color="#a44a3f",
    ))
    ax.text((cx_main + box_w / 2 + cx_rej - box_w / 2) / 2, cy_rej + 0.30,
            "manual reject",
            ha="center", va="bottom", fontsize=11.5, color="#a44a3f", style="italic")

    ax.set_xlim(cx_main - box_w / 2 - 0.5, cx_rej + box_w / 2 + 0.4)
    ax.set_ylim(centres["Closed"][1] - 0.8, y_top + 0.8)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)

    fig.tight_layout()
    _save_shared(fig, "fig_7_1_1_commitment_lifecycle.png")
    plt.close(fig)


def three_sprints() -> None:
    """Clean 3 rows of 3 meetings each, generous whitespace, single accent
    colour per sprint applied subtly (only on the row label), boxes with
    light grey borders, faint hand-off arrows on the right side. No
    cross-sprint references in the figure: they are mentioned in the
    caption to keep the diagram free of overlapping arcs."""
    fig, ax = plt.subplots(figsize=(11, 6.5))

    meetings = ["Planning", "Midpoint", "Review"]
    sprints = ["Sprint 1", "Sprint 2", "Sprint 3"]
    sprint_colours = ["#3a6ea5", "#d9822b", "#6a994e"]

    box_w = 2.6
    box_h = 1.0
    gap_x = 0.5
    gap_y = 1.7
    x_start = 1.8  # leave room for the sprint label on the left

    box_fc = "#fafafa"
    box_ec = "#cbd0d6"

    centres: dict[tuple[int, int], tuple[float, float]] = {}

    for r, sprint in enumerate(sprints):
        y = (len(sprints) - 1 - r) * gap_y + 0.8

        # Sprint label to the left, in the sprint's accent colour.
        ax.text(x_start - 0.4, y, sprint,
                ha="right", va="center",
                fontsize=16, color=sprint_colours[r], fontweight="bold")

        # Three meeting boxes per row.
        for c, meeting in enumerate(meetings):
            cx = x_start + c * (box_w + gap_x) + box_w / 2
            centres[(r, c)] = (cx, y)
            rect = FancyBboxPatch(
                (cx - box_w / 2, y - box_h / 2), box_w, box_h,
                boxstyle="round,pad=0.08",
                facecolor=box_fc, edgecolor=box_ec, linewidth=1.5,
            )
            ax.add_patch(rect)
            ax.text(cx, y + 0.13, meeting,
                    ha="center", va="center",
                    fontsize=15, color=INK, fontweight="bold")
            ax.text(cx, y - 0.22, f"payments-s{r+1}-{meeting.lower()}",
                    ha="center", va="center",
                    fontsize=10.5, color=MUTED, style="italic",
                    family="DejaVu Sans Mono")

        # Within-sprint arrows (P -> M -> R).
        for c in range(len(meetings) - 1):
            ax.add_patch(FancyArrowPatch(
                (centres[(r, c)][0] + box_w / 2, y),
                (centres[(r, c + 1)][0] - box_w / 2, y),
                arrowstyle="->", mutation_scale=18, linewidth=1.4, color=INK,
            ))

    total_w = x_start + 3 * box_w + 2 * gap_x
    ax.set_xlim(0.2, total_w + 0.4)
    ax.set_ylim(-0.2, (len(sprints) - 1) * gap_y + 2.0)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)

    fig.tight_layout()
    out = IMG / "fig_7_3_1_three_sprints.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {out.name}")


def pipeline_v8_legacy_unused() -> None:
    """Unused; kept only for reference. Replaced by the vertical version below.
    The 2x3 snake layout proved hard to make fully overlap-free at A4 width."""
    fig, ax = plt.subplots(figsize=(12.0, 10.5))
    ax.set_aspect("equal")

    agents = [
        ("task_proposal_agent",     "gemma3:4b",     False),
        ("task_validation_agent",   "qwen2.5:7b",    False),
        ("issue_draft_agent",       "gemma3:4b",     False),
        ("git_evidence_agent",      "gemma3:4b",     False),
        ("task_followup_agent",     "qwen2.5:7b",    True),
        ("jira_issue_lookup_agent", "REST (no LLM)", False),
    ]
    edge_labels = [
        "task_candidates",
        "validated_task_candidates",
        "issue_drafts",
        "git_evidence",
        "followups",
    ]

    # Coordinates: 3 columns × 2 rows, with generous gaps so labels breathe.
    box_w, box_h = 3.0, 1.2
    col_gap = 2.6
    row_gap = 4.0
    cols_x = [-(box_w + col_gap), 0.0, (box_w + col_gap)]
    rows_y = [row_gap / 2, -row_gap / 2]

    aux_fc, aux_ec, aux_text = "#eef2f5", "#b5c0c8", "#5a6770"
    main_fc, main_ec = "#e8eef5", "#1f4e79"

    centres: dict[str, tuple[float, float]] = {}
    for idx, (name, model, is_main) in enumerate(agents):
        row, col = divmod(idx, 3)
        cx, cy = cols_x[col], rows_y[row]
        ax.add_patch(FancyBboxPatch(
            (cx - box_w / 2, cy - box_h / 2), box_w, box_h,
            boxstyle="round,pad=0.05",
            facecolor=main_fc if is_main else aux_fc,
            edgecolor=main_ec if is_main else aux_ec,
            linewidth=2.6 if is_main else 1.3,
        ))
        ax.text(cx, cy + 0.22, name,
                ha="center", va="center", fontsize=12.5,
                color=INK if is_main else aux_text,
                fontweight="bold" if is_main else "normal")
        ax.text(cx, cy - 0.22, model,
                ha="center", va="center", fontsize=11.5,
                color=INK if is_main else aux_text, style="italic")
        centres[name] = (cx, cy)

    # --- Horizontal arrows on row 1 (left → right). -------------------------
    def arrow_h(a: str, b: str, label: str, *, label_above: bool = True) -> None:
        cx_a, cy_a = centres[a]
        cx_b = centres[b][0]
        x1 = cx_a + box_w / 2
        x2 = cx_b - box_w / 2
        ax.add_patch(FancyArrowPatch(
            (x1, cy_a), (x2, cy_a),
            arrowstyle="->", mutation_scale=22, linewidth=1.6, color=INK,
        ))
        # Lift labels ABOVE the box top so they don't share a baseline with
        # the agent names (which would look like one continuous text line).
        ay = cy_a + box_h / 2 + 0.28 if label_above else cy_a - box_h / 2 - 0.28
        ax.text((x1 + x2) / 2, ay, label,
                ha="center", va="bottom" if label_above else "top",
                fontsize=11, color=MUTED, style="italic")

    arrow_h(agents[0][0], agents[1][0], edge_labels[0])
    arrow_h(agents[1][0], agents[2][0], edge_labels[1])
    arrow_h(agents[3][0], agents[4][0], edge_labels[3])
    arrow_h(agents[4][0], agents[5][0], edge_labels[4])

    # Coordinates of the input box need to be known before the snake routes,
    # since the snake's left pivot column sits to the LEFT of the input box.
    cx_in = cols_x[0] - box_w / 2 - 2.2
    cy_in = rows_y[0]

    # --- Snake polyline: top of issue_draft → up → left (outside the grid)
    #     → down → into git_evidence FROM THE LEFT. Routed entirely outside
    #     so it never crosses any agent box. -----------------------------
    sx = centres["issue_draft_agent"][0]
    sy = centres["issue_draft_agent"][1] + box_h / 2
    ex_box = centres["git_evidence_agent"][0] - box_w / 2  # left side of git_evidence
    ey = centres["git_evidence_agent"][1]
    # Cruise altitude above the row-1 labels.
    py = rows_y[0] + box_h / 2 + 0.95
    # Pivot column: just LEFT of the entire grid (left of the input box).
    px_pivot = cx_in - 0.95 - 0.6
    # Up from issue_draft top.
    ax.plot([sx, sx], [sy, py], color=INK, linewidth=1.6, solid_capstyle="round")
    # Left across the top to the pivot column.
    ax.plot([sx, px_pivot], [py, py], color=INK, linewidth=1.6, solid_capstyle="round")
    # Down to git_evidence row level.
    ax.plot([px_pivot, px_pivot], [py, ey], color=INK, linewidth=1.6, solid_capstyle="round")
    # Right into git_evidence's left side.
    ax.add_patch(FancyArrowPatch(
        (px_pivot, ey), (ex_box, ey),
        arrowstyle="->", mutation_scale=22, linewidth=1.6, color=INK,
    ))
    # Label centred on the horizontal cruise.
    ax.text((sx + px_pivot) / 2, py + 0.20, edge_labels[2],
            ha="center", va="bottom",
            fontsize=11, color=MUTED, style="italic")

    # --- Input arrow: Meeting transcript → task_proposal --------------------
    ax.add_patch(FancyBboxPatch(
        (cx_in - 0.95, cy_in - 0.55), 1.9, 1.1,
        boxstyle="round,pad=0.05",
        facecolor="#ffffff", edgecolor=INK, linewidth=1.4,
    ))
    ax.text(cx_in, cy_in, "Meeting\ntranscript",
            ha="center", va="center", fontsize=11.5, color=INK)
    ax.add_patch(FancyArrowPatch(
        (cx_in + 0.95, cy_in),
        (cols_x[0] - box_w / 2, cy_in),
        arrowstyle="->", mutation_scale=22, linewidth=1.6, color=INK,
    ))

    # --- Output arrow: jira_issue_lookup → AnalysisRun ----------------------
    cx_out = cols_x[2] + box_w / 2 + 2.4
    cy_out = rows_y[1]
    ax.add_patch(FancyArrowPatch(
        (cols_x[2] + box_w / 2, cy_out),
        (cx_out - 0.95, cy_out),
        arrowstyle="->", mutation_scale=22, linewidth=1.6, color=INK,
    ))
    ax.text((cols_x[2] + box_w / 2 + cx_out - 0.95) / 2,
            cy_out + box_h / 2 + 0.28, "jira_matches",
            ha="center", va="bottom", fontsize=11,
            color=MUTED, style="italic")
    ax.add_patch(FancyBboxPatch(
        (cx_out - 0.95, cy_out - 0.55), 1.9, 1.1,
        boxstyle="round,pad=0.05",
        facecolor="#f3eee4", edgecolor=INK, linewidth=1.4,
    ))
    ax.text(cx_out, cy_out, "AnalysisRun",
            ha="center", va="center", fontsize=11.5,
            color=INK, fontweight="bold")

    # --- Retrieval phase below task_followup --------------------------------
    cf_x, cf_y = centres["task_followup_agent"]
    rb_w, rb_h = 4.6, 1.2
    rb_y = cf_y - 2.4
    ax.add_patch(FancyBboxPatch(
        (cf_x - rb_w / 2, rb_y - rb_h / 2), rb_w, rb_h,
        boxstyle="round,pad=0.05",
        facecolor="#fff4e0", edgecolor="#d99641",
        linewidth=2.0, linestyle="--",
    ))
    ax.text(cf_x, rb_y + 0.24, "retrieval phase",
            ha="center", va="center", fontsize=12.5,
            color=INK, fontweight="bold")
    ax.text(cf_x, rb_y - 0.24,
            "orchestrator side-car · off / current sprint / all sprints",
            ha="center", va="center", fontsize=10.5,
            color=MUTED, style="italic")
    ax.add_patch(FancyArrowPatch(
        (cf_x, rb_y + rb_h / 2),
        (cf_x, cf_y - box_h / 2),
        arrowstyle="->", mutation_scale=22, linewidth=2.0, color="#d99641",
    ))
    ax.text(cf_x + 0.18, (rb_y + rb_h / 2 + cf_y - box_h / 2) / 2,
            "retrieved_fragments",
            ha="left", va="center", fontsize=11,
            color="#d99641", style="italic")

    # No star marker on the INF figure: the "agent under evaluation" framing
    # belongs in the CDIA chapter, not in the INF architecture diagram. The
    # bold blue border on task_followup_agent already encodes the asymmetry
    # introduced by Decision 016 (annotated below).

    # --- Decision annotations (discreet, under the model labels). -----------
    for name in ("task_validation_agent", "task_followup_agent"):
        cx, cy = centres[name]
        ax.text(cx, cy - box_h / 2 - 0.20, "D016",
                ha="center", va="top", fontsize=9.5,
                color=main_ec, fontweight="bold")
    # D012 sits inside the retrieval phase block, below the second line.
    ax.text(cf_x, rb_y - 0.55, "D012",
            ha="center", va="top", fontsize=9.5,
            color="#a86a16", fontweight="bold")
    # D023 acknowledged as out-of-pipeline (GitHub does not enter here; the
    # CommitmentRefreshService is the entry point). Small footnote.
    ax.text(cf_x, rb_y - rb_h / 2 - 0.55,
            "GitHub evidence (Decision 023) enters through the refresh "
            "service, not through this pipeline.",
            ha="center", va="top", fontsize=10,
            color=MUTED, style="italic")

    # --- Dashed input from validated_task_candidates into retrieval phase. ---
    # The retrieval phase consumes the validated items and produces fragments;
    # this is the missing input the previous version of the figure did not
    # show. Routed in the column gap LEFT of jira_issue_lookup_agent, outside
    # task_followup_agent. Dashed to keep it distinct from the main pipeline.
    tap_x = cols_x[1] + box_w / 2 + 0.45             # tap from the cable
    pivot_x = cf_x + rb_w / 2 + 0.7                  # vertical column
    enter_x = cf_x + rb_w / 2 - 0.7                  # arrow head x
    enter_y = rb_y + rb_h / 2                         # top edge of retrieval

    # 1. Small vertical drop from the cable.
    ax.plot([tap_x, tap_x], [rows_y[0], rows_y[0] - 0.5],
            color=MUTED, linewidth=1.2, linestyle="--",
            solid_capstyle="round")
    # 2. Horizontal across to the pivot column.
    ax.plot([tap_x, pivot_x], [rows_y[0] - 0.5, rows_y[0] - 0.5],
            color=MUTED, linewidth=1.2, linestyle="--",
            solid_capstyle="round")
    # 3. Vertical drop past task_followup to retrieval-phase entry height.
    ax.plot([pivot_x, pivot_x], [rows_y[0] - 0.5, enter_y + 0.3],
            color=MUTED, linewidth=1.2, linestyle="--",
            solid_capstyle="round")
    # 4. Final dashed arrow into the retrieval phase from the right-top.
    ax.add_patch(FancyArrowPatch(
        (pivot_x, enter_y + 0.3), (enter_x, enter_y),
        arrowstyle="->", mutation_scale=18, linewidth=1.2, color=MUTED,
        linestyle="--",
    ))
    # Short label right next to the arrow head (clear of every other label).
    ax.text(enter_x - 0.05, enter_y + 0.18,
            "validated items",
            ha="right", va="bottom", fontsize=10,
            color=MUTED, style="italic")

    # Title block (top-left, in figure margin).
    title_x = cx_in - 0.95
    title_y = rows_y[0] + box_h / 2 + 2.5
    ax.text(title_x, title_y, "meeting_analysis_pipeline_v8",
            ha="left", va="center", fontsize=14,
            color=INK, fontweight="bold")
    ax.text(title_x, title_y - 0.45,
            "six agents declared in agents.json plus the retrieval phase",
            ha="left", va="center", fontsize=11,
            color=MUTED, style="italic")

    ax.set_xlim(px_pivot - 0.6, cx_out + 2.0)
    ax.set_ylim(rb_y - rb_h / 2 - 1.4, title_y + 0.6)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)

    fig.tight_layout()
    _save_shared(fig, "fig_7_2_2_pipeline_v8.png")
    plt.close(fig)


def rag_architecture() -> None:
    """Vertical pipeline of the project's RAG architecture, top to bottom.

    Vertical orientation avoids the arrow crossings and text overlap that
    the previous horizontal version suffered when the two indices fed up
    into the retrieval box from below."""
    fig, ax = plt.subplots(figsize=(8.5, 11.5))

    INK_BOX = "#1f4e79"
    EMBED_FC = "#d0e4d4"
    EMBED_EC = "#5a8a5a"
    INDEX_FC = "#fff4e0"
    INDEX_EC = "#d99641"
    GUARD_FC = "#fce4ec"
    GUARD_EC = "#a44a3f"
    LLM_FC = "#e9d6f0"
    LLM_EC = "#7b3e8c"
    NEUTRAL_FC = "#f5f5f5"

    box_w = 5.6
    box_h = 1.10
    step_y = 1.55
    cx = 0.0
    y_top = 6.0  # y of top box

    nodes = [
        # (label, sublabel, facecolor, edgecolor)
        ("Question",      "from the user",                                  NEUTRAL_FC, INK_BOX),
        ("Embed",         "embeddinggemma:latest",                          EMBED_FC,   EMBED_EC),
        ("Top-K retrieval", "transcript index + commitment index, intent-aware boosts", INDEX_FC, INDEX_EC),
        ("Guardrails",    "input (G2, G4), scope (G3), grounding (G1, G5)", GUARD_FC,   GUARD_EC),
        ("Prompt builder","context fragments + inline citations [N]",       NEUTRAL_FC, INK_BOX),
        ("LLM",           "qwen2.5:7b (local) or gpt-4o-mini (frontier)",   LLM_FC,     LLM_EC),
        ("Answer",        "streamed back with cited fragments",             NEUTRAL_FC, INK_BOX),
    ]

    centres = []
    for i, (label, sublabel, fc, ec) in enumerate(nodes):
        y = y_top - i * step_y
        centres.append((cx, y))
        rect = FancyBboxPatch(
            (cx - box_w / 2, y - box_h / 2), box_w, box_h,
            boxstyle="round,pad=0.06",
            facecolor=fc, edgecolor=ec, linewidth=2.2,
        )
        ax.add_patch(rect)
        ax.text(cx, y + 0.20, label,
                ha="center", va="center",
                fontsize=15, color=INK, fontweight="bold")
        ax.text(cx, y - 0.22, sublabel,
                ha="center", va="center",
                fontsize=11.5, color=MUTED, style="italic")

    # Vertical arrows between consecutive nodes.
    for (cxa, ya), (cxb, yb) in zip(centres[:-1], centres[1:]):
        ax.add_patch(FancyArrowPatch(
            (cxa, ya - box_h / 2),
            (cxb, yb + box_h / 2),
            arrowstyle="->", mutation_scale=22, linewidth=1.8, color=INK,
        ))

    # Citation-verification feedback arc on the left side, from Answer back to
    # Guardrails, drawn so it sits clearly to the left of the boxes.
    cx_answer, cy_answer = centres[6]
    cx_guard, cy_guard = centres[3]
    x_arc = cx - box_w / 2 - 0.45
    ax.add_patch(FancyArrowPatch(
        (cx_answer - box_w / 2, cy_answer),
        (x_arc, cy_answer),
        arrowstyle="-", linewidth=1.5, color="#a44a3f", linestyle="dashed",
    ))
    ax.add_patch(FancyArrowPatch(
        (x_arc, cy_answer),
        (x_arc, cy_guard),
        arrowstyle="-", linewidth=1.5, color="#a44a3f", linestyle="dashed",
    ))
    ax.add_patch(FancyArrowPatch(
        (x_arc, cy_guard),
        (cx_guard - box_w / 2, cy_guard),
        arrowstyle="->", mutation_scale=20, linewidth=1.5,
        color="#a44a3f", linestyle="dashed",
    ))
    ax.text(x_arc - 0.15, (cy_answer + cy_guard) / 2,
            "citation\nverification",
            ha="right", va="center",
            fontsize=11.5, color="#a44a3f", style="italic")

    ax.set_xlim(x_arc - 2.5, cx + box_w / 2 + 0.5)
    ax.set_ylim(centres[-1][1] - 0.9, y_top + 0.9)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)

    fig.tight_layout()
    out = IMG / "fig_7_3_rag_architecture.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {out.name}")


# ---------------------------------------------------------------------------
# INF-only figures (live under memoria/ingenieria/img only).
# ---------------------------------------------------------------------------
def _save_inf(fig, name: str) -> None:
    out = IMG_INF / name
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print(f"  wrote {out.relative_to(ROOT)}")


def layers_v2() -> None:
    """fig_7_2_layers.png — layered system view with ChatClient + 3 integrations."""
    fig, ax = plt.subplots(figsize=(11.5, 7.4))

    def box(x, y, w, h, label, fc="#ffffff", ec=INK, dashed=False, lw=1.8):
        rect = FancyBboxPatch(
            (x - w / 2, y - h / 2), w, h,
            boxstyle="round,pad=0.04",
            facecolor=fc, edgecolor=ec, linewidth=lw,
            linestyle="--" if dashed else "-",
        )
        ax.add_patch(rect)
        ax.text(x, y, label, ha="center", va="center", fontsize=13, color=INK)
        return (x, y, w, h)

    def arrow(ax_, x1, y1, x2, y2, dashed=False, color=INK, label=""):
        ax_.add_patch(FancyArrowPatch(
            (x1, y1), (x2, y2),
            arrowstyle="->", mutation_scale=18, linewidth=1.4, color=color,
            linestyle="--" if dashed else "-",
        ))
        if label:
            ax_.text((x1 + x2) / 2, (y1 + y2) / 2 + 0.12, label,
                     ha="center", va="bottom",
                     fontsize=10.5, color=MUTED, style="italic")

    # Top: browser → frontend SPA.
    box(0.0, 6.0, 4.2, 0.9, "Web browser")
    box(0.0, 4.5, 5.5, 0.9, "React + TypeScript SPA\nbuilt with Vite, served as /app/static/")
    arrow(ax, 0.0, 5.55, 0.0, 4.95, label="HTTP and NDJSON")

    # Middle: HTTP API.
    box(0.0, 3.0, 5.5, 0.9, "FastAPI HTTP API\nPython 3 backend")
    arrow(ax, 0.0, 4.05, 0.0, 3.45)

    # Bottom row: orchestrator, ChatClient, domain services, persistence.
    box(-4.2, 1.3, 3.0, 1.0, "MeetingAnalysis\nOrchestrator")
    box(0.0, 1.3, 3.6, 1.0, "Domain services\ncommitment_sync, refresh,\njira_sync, qa, indexer")
    box(4.2, 1.3, 3.0, 1.0, "JSON persistence\napp/data/", fc="#f3eee4")

    arrow(ax, -1.5, 2.55, -4.2, 1.80)
    arrow(ax, 0.0, 2.55, 0.0, 1.80)
    arrow(ax, 1.5, 2.55, 4.2, 1.80)

    # ChatClient column on the left of bottom row.
    box(-4.2, -0.6, 3.4, 1.4, "ChatClient (Decision 018)\nOllama (default)\nOpenAI · Anthropic")
    arrow(ax, -4.2, 0.80, -4.2, 0.10)

    # Three optional integrations on the right.
    box(2.4, -0.6, 2.6, 1.0, "Jira Cloud REST",
        fc="#fafafa", dashed=True, lw=1.4)
    box(5.4, -0.6, 2.6, 1.0, "Local Git repo\nread-only",
        fc="#fafafa", dashed=True, lw=1.4)
    box(2.4, -2.2, 2.6, 1.0, "GitHub REST API\nread-only (Decision 023)",
        fc="#fafafa", dashed=True, lw=1.4)

    ax.text(3.9, 0.05, "optional", fontsize=10.5,
            color=MUTED, style="italic", ha="center")
    arrow(ax, 1.0, 0.80, 2.4, -0.10, dashed=True, color=MUTED)
    arrow(ax, 1.5, 0.80, 5.4, -0.10, dashed=True, color=MUTED)
    arrow(ax, 1.0, 0.80, 2.4, -1.70, dashed=True, color=MUTED)

    ax.set_xlim(-7.0, 7.5)
    ax.set_ylim(-3.0, 6.7)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)

    fig.tight_layout()
    _save_inf(fig, "fig_7_2_layers.png")
    plt.close(fig)


def domain_model_v2() -> None:
    """fig_7_2_1_domain_model.png — Commitment with five composition arms,
    one of which is the new GitHubEvidence block (Decision 023)."""
    fig, ax = plt.subplots(figsize=(13.5, 7.2))

    def entity(x, y, w, h, title, fields, accent="#3a6ea5", fc="#e8eef5"):
        rect = FancyBboxPatch(
            (x - w / 2, y - h / 2), w, h,
            boxstyle="round,pad=0.04",
            facecolor=fc, edgecolor=accent, linewidth=2.0,
        )
        ax.add_patch(rect)
        ax.text(x, y + h / 2 - 0.32, title,
                ha="center", va="center",
                fontsize=14, fontweight="bold", color=INK)
        for i, f in enumerate(fields):
            ax.text(x, y + h / 2 - 0.75 - i * 0.32, f,
                    ha="center", va="center",
                    fontsize=11.5, color=INK)

    # Commitment at the top centre.
    entity(0, 3.3, 4.6, 2.3, "Commitment",
           ["id", "state", "jira_created_issue", "last_seen_run_id"])

    # Five composition arms below.
    children = [
        (-6.4, 0.0, 3.0, 2.4, "CommitmentOrigin",
         ["meeting_id", "segment_index", "sprint_id", "verbatim"], "origin", "1"),
        (-3.2, 0.0, 3.0, 2.4, "CommitmentEvent",
         ["event_type", "run_id", "timestamp", "note"], "timeline", "*"),
        ( 0.0, 0.0, 3.0, 2.4, "GitEvidence",
         ["commit_hash", "message", "date", "level"], "evidence", "*"),
        ( 3.2, 0.0, 3.4, 2.4, "GitHubEvidence",
         ["evidence_level", "pull_requests_open",
          "pull_requests_merged", "supporting_commits", "repo"],
         "github_evidence", "1"),
        ( 6.6, 0.0, 2.8, 2.4, "Followup",
         ["followup_type", "meeting_id", "note"], "followups", "*"),
    ]
    for x, y, w, h, title, fields, rel, mult in children:
        is_github = title == "GitHubEvidence"
        entity(x, y, w, h, title, fields,
               accent="#6a994e" if is_github else "#3a6ea5",
               fc="#eef5e8" if is_github else "#e8eef5")
        # Composition diamond at the top + edge label.
        ax.add_patch(FancyArrowPatch(
            (0, 2.15), (x, 1.2),
            arrowstyle="-", mutation_scale=14, linewidth=1.4, color=INK,
        ))
        mx, my = (0 + x) / 2.0, (2.15 + 1.2) / 2.0
        ax.text(mx + 0.05, my + 0.18, rel,
                ha="center", va="bottom",
                fontsize=11, color=MUTED, style="italic")
        ax.text(x, 1.35, mult, ha="center", va="bottom",
                fontsize=10.5, color=INK)

    ax.text(3.2, -1.5, "Introduced by Decision 023",
            ha="center", va="top",
            fontsize=10, color="#6a994e", style="italic")

    ax.set_xlim(-9.0, 9.0)
    ax.set_ylim(-2.2, 4.8)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)

    fig.tight_layout()
    _save_inf(fig, "fig_7_2_1_domain_model.png")
    plt.close(fig)


def refresh_v2() -> None:
    """fig_7_5_1_refresh.png — sequence of the on-demand refresh, with
    THREE parallel reads (Jira + Git + GitHub) per Decision 023."""
    fig, ax = plt.subplots(figsize=(13.5, 8.6))

    # Six lifelines.
    actors = [
        ("User", -6.4),
        ("Board / Detail view", -4.0),
        ("CommitmentRefreshService", -1.0),
        ("JiraCloudClient", 1.8),
        ("GitClient\n(git_evidence_agent)", 4.4),
        ("GitHubClient\n(GithubEvidenceAgent)", 7.0),
    ]
    top_y = 7.2
    bot_y = -1.4

    # Lifelines: header box + vertical dashed line.
    for label, x in actors:
        ax.add_patch(FancyBboxPatch(
            (x - 1.05, top_y - 0.45), 2.10, 0.9,
            boxstyle="round,pad=0.03",
            facecolor="#e8eef5", edgecolor="#3a6ea5", linewidth=1.6,
        ))
        ax.text(x, top_y, label, ha="center", va="center",
                fontsize=11, color=INK)
        ax.plot([x, x], [top_y - 0.45, bot_y], linestyle=":", color=MUTED, linewidth=1.0)

    def msg(y, x1, x2, label, dashed=False, color=INK):
        ax.add_patch(FancyArrowPatch(
            (x1, y), (x2, y),
            arrowstyle="->", mutation_scale=14, linewidth=1.3, color=color,
            linestyle="--" if dashed else "-",
        ))
        mid = (x1 + x2) / 2.0
        ax.text(mid, y + 0.14, label,
                ha="center", va="bottom",
                fontsize=10.5, color=color, style="italic" if dashed else "normal")

    # Sequence steps (top → bottom).
    msg(6.2, -6.4, -4.0, 'click "Refresh"')
    msg(5.5, -4.0, -1.0, "POST /api/commitments/{id}/refresh")

    # par block for the three reads.
    ax.add_patch(FancyBboxPatch(
        (-1.6, 1.4), 9.8, 3.5,
        boxstyle="round,pad=0.02",
        facecolor="none", edgecolor="#6a994e", linewidth=1.4, linestyle="--",
    ))
    ax.text(-1.4, 4.75, "par   [parallel reads]",
            ha="left", va="center",
            fontsize=11, color="#6a994e", fontweight="bold")

    msg(4.3, -1.0, 1.8, "get_issue_status()")
    msg(3.8, 1.8, -1.0, "statusCategory.key", dashed=True, color=MUTED)

    msg(3.1, -1.0, 4.4, "query commits for commitment")
    msg(2.6, 4.4, -1.0, "evidence level", dashed=True, color=MUTED)

    msg(1.9, -1.0, 7.0, "search PRs and commits")
    msg(1.4, 7.0, -1.0, "PRs open / merged / commits", dashed=True, color=MUTED)

    # After the par block.
    msg(0.5, -1.0, -4.0, "CommitmentRefreshResult", dashed=True, color=MUTED)
    msg(-0.5, -4.0, -6.4, "render toast (one line per change)")

    ax.set_xlim(-7.6, 8.2)
    ax.set_ylim(-1.9, 8.0)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)

    fig.tight_layout()
    _save_inf(fig, "fig_7_5_1_refresh.png")
    plt.close(fig)


def pipeline_v8() -> None:
    """fig_7_2_2_pipeline_v8.png — vertical chain layout.

    Avoids the snake-routing fragility of the previous 2x3 layout. Six agents
    flow top-to-bottom in a single column; the retrieval phase sits as a
    side-car on the right, coupled to ``task_followup_agent`` with two arrows
    (validated items in, retrieved fragments out). Per-agent Decision 016
    markers sit beside the agents that use ``qwen2.5:7b``; the retrieval
    phase carries the Decision 012 marker. A footnote acknowledges that
    GitHub evidence (Decision 023) does not enter through this pipeline."""

    fig, ax = plt.subplots(figsize=(9.5, 11.5))

    agents = [
        ("task_proposal_agent",     "gemma3:4b",     False),
        ("task_validation_agent",   "qwen2.5:7b",    True),
        ("issue_draft_agent",       "gemma3:4b",     False),
        ("git_evidence_agent",      "gemma3:4b",     False),
        ("task_followup_agent",     "qwen2.5:7b",    True),
        ("jira_issue_lookup_agent", "REST (no LLM)", False),
    ]
    edge_labels = [
        "task_candidates",
        "validated_task_candidates",
        "issue_drafts",
        "git_evidence",
        "followups",
    ]

    box_w, box_h = 4.4, 1.0
    row_gap = 1.7
    col_x = 0.0
    # y coords for the 6 agents (top of chain is highest).
    n = len(agents)
    y_top = (n - 1) * row_gap / 2
    rows_y = [y_top - i * row_gap for i in range(n)]

    aux_fc, aux_ec, aux_text = "#eef2f5", "#b5c0c8", "#5a6770"
    main_fc, main_ec = "#e8eef5", "#1f4e79"

    centres: dict[str, tuple[float, float]] = {}
    for idx, (name, model, is_main) in enumerate(agents):
        cy = rows_y[idx]
        ax.add_patch(FancyBboxPatch(
            (col_x - box_w / 2, cy - box_h / 2), box_w, box_h,
            boxstyle="round,pad=0.05",
            facecolor=main_fc if is_main else aux_fc,
            edgecolor=main_ec if is_main else aux_ec,
            linewidth=2.6 if is_main else 1.3,
        ))
        ax.text(col_x, cy + 0.20, name,
                ha="center", va="center", fontsize=14,
                color=INK if is_main else aux_text,
                fontweight="bold" if is_main else "normal")
        ax.text(col_x, cy - 0.22, model,
                ha="center", va="center", fontsize=12.5,
                color=INK if is_main else aux_text, style="italic")
        centres[name] = (col_x, cy)
        # D016 marker BELOW the box so it doesn't compete with the retrieval
        # side-car on the right of task_followup_agent.
        if is_main:
            ax.text(col_x + box_w / 2 - 0.15, cy - box_h / 2 - 0.18, "D016",
                    ha="right", va="top", fontsize=10.5,
                    color=main_ec, fontweight="bold")

    # Vertical arrows between consecutive agents, labels on the RIGHT side.
    for i in range(n - 1):
        cy_a = rows_y[i]
        cy_b = rows_y[i + 1]
        ax.add_patch(FancyArrowPatch(
            (col_x, cy_a - box_h / 2),
            (col_x, cy_b + box_h / 2),
            arrowstyle="->", mutation_scale=24, linewidth=1.7, color=INK,
        ))
        label_y = (cy_a - box_h / 2 + cy_b + box_h / 2) / 2
        ax.text(col_x - box_w / 2 - 0.25, label_y, edge_labels[i],
                ha="right", va="center", fontsize=11,
                color=MUTED, style="italic")

    # Input: Meeting transcript at the very top.
    in_y = rows_y[0] + row_gap
    ax.add_patch(FancyBboxPatch(
        (col_x - 1.5, in_y - box_h / 2), 3.0, box_h,
        boxstyle="round,pad=0.05",
        facecolor="#ffffff", edgecolor=INK, linewidth=1.4,
    ))
    ax.text(col_x, in_y, "Meeting transcript",
            ha="center", va="center", fontsize=13, color=INK)
    ax.add_patch(FancyArrowPatch(
        (col_x, in_y - box_h / 2),
        (col_x, rows_y[0] + box_h / 2),
        arrowstyle="->", mutation_scale=24, linewidth=1.7, color=INK,
    ))

    # Output: AnalysisRun at the very bottom.
    out_y = rows_y[-1] - row_gap
    ax.add_patch(FancyBboxPatch(
        (col_x - 1.5, out_y - box_h / 2), 3.0, box_h,
        boxstyle="round,pad=0.05",
        facecolor="#f3eee4", edgecolor=INK, linewidth=1.4,
    ))
    ax.text(col_x, out_y, "AnalysisRun",
            ha="center", va="center", fontsize=13, color=INK, fontweight="bold")
    ax.add_patch(FancyArrowPatch(
        (col_x, rows_y[-1] - box_h / 2),
        (col_x, out_y + box_h / 2),
        arrowstyle="->", mutation_scale=24, linewidth=1.7, color=INK,
    ))
    ax.text(col_x - box_w / 2 - 0.25,
            (rows_y[-1] - box_h / 2 + out_y + box_h / 2) / 2,
            "jira_matches", ha="right", va="center",
            fontsize=11, color=MUTED, style="italic")

    # Retrieval phase — side-car on the right of task_followup_agent.
    cf_x, cf_y = centres["task_followup_agent"]
    rb_w, rb_h = 3.6, 1.6
    rb_x = cf_x + box_w / 2 + 1.6 + rb_w / 2
    rb_y = cf_y
    ax.add_patch(FancyBboxPatch(
        (rb_x - rb_w / 2, rb_y - rb_h / 2), rb_w, rb_h,
        boxstyle="round,pad=0.05",
        facecolor="#fff4e0", edgecolor="#d99641",
        linewidth=2.0, linestyle="--",
    ))
    ax.text(rb_x, rb_y + 0.36, "retrieval phase",
            ha="center", va="center", fontsize=13.5,
            color=INK, fontweight="bold")
    ax.text(rb_x, rb_y + 0.04,
            "orchestrator side-car",
            ha="center", va="center", fontsize=11,
            color=MUTED, style="italic")
    ax.text(rb_x, rb_y - 0.30,
            "off · current sprint · all sprints",
            ha="center", va="center", fontsize=10.5,
            color=MUTED, style="italic")
    ax.text(rb_x + rb_w / 2 + 0.20, rb_y - rb_h / 2 + 0.18, "D012",
            ha="left", va="bottom", fontsize=10.5,
            color="#a86a16", fontweight="bold")

    # Arrow IN: validated items from task_validation_agent → retrieval phase.
    src_x = centres["task_validation_agent"][0] + box_w / 2
    src_y = centres["task_validation_agent"][1]
    ax.add_patch(FancyArrowPatch(
        (src_x, src_y), (rb_x - rb_w / 2, rb_y + 0.45),
        arrowstyle="->", mutation_scale=18, linewidth=1.3, color=MUTED,
        linestyle="--",
        connectionstyle="arc3,rad=-0.25",
    ))
    ax.text((src_x + rb_x - rb_w / 2) / 2 + 0.1,
            (src_y + rb_y + 0.45) / 2 + 0.45,
            "validated items",
            ha="center", va="bottom", fontsize=10.5,
            color=MUTED, style="italic")

    # Arrow OUT: retrieval phase → top-right corner of task_followup_agent.
    # The arrow itself (and the orange colour of the retrieval block) carries
    # the meaning; the label was removed to guarantee zero overlap.
    out_src_y = rb_y + 0.10
    out_dst_x = cf_x + box_w / 2 - 0.15
    out_dst_y = cf_y + box_h / 2
    ax.add_patch(FancyArrowPatch(
        (rb_x - rb_w / 2, out_src_y),
        (out_dst_x, out_dst_y),
        arrowstyle="->", mutation_scale=22, linewidth=1.7, color="#d99641",
    ))

    # Title block (top, above the input box).
    title_y = in_y + box_h / 2 + 1.0
    ax.text(col_x - box_w / 2, title_y,
            "meeting_analysis_pipeline_v8",
            ha="left", va="center", fontsize=14.5,
            color=INK, fontweight="bold")
    ax.text(col_x - box_w / 2, title_y - 0.45,
            "six agents declared in agents.json plus the retrieval phase",
            ha="left", va="center", fontsize=11.5,
            color=MUTED, style="italic")

    # Footnote acknowledging the GitHub integration is OUT of this pipeline.
    foot_y = out_y - box_h / 2 - 0.8
    ax.text(col_x, foot_y,
            "GitHub evidence (Decision 023) enters through the refresh "
            "service, not through this pipeline.",
            ha="center", va="top", fontsize=11,
            color=MUTED, style="italic")

    ax.set_xlim(col_x - box_w / 2 - 2.2, rb_x + rb_w / 2 + 1.2)
    ax.set_ylim(foot_y - 0.6, title_y + 0.6)
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)

    fig.tight_layout()
    _save_shared(fig, "fig_7_2_2_pipeline_v8.png")
    plt.close(fig)


def main() -> None:
    print("Regenerating redesigned figures:")
    gantt()
    hitos_sequence()
    commitment_lifecycle()
    pipeline_v8()
    three_sprints()
    rag_architecture()
    layers_v2()
    domain_model_v2()
    refresh_v2()
    print("Done.")


if __name__ == "__main__":
    main()
