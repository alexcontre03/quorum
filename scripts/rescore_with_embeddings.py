"""
Re-score the follow-up ablation outputs (already produced by
``run_cdia_followup_only.py``) under an embedding-based matching protocol.

The original protocol matches predicted follow-ups against expected ones by
character-level similarity of ``matched_history_title``. That is too strict
for predictions that translate or paraphrase. This script re-runs the
matching using cosine similarity over ``embeddinggemma:latest`` embeddings,
without invoking the chat agents again — the predicted lists are already
on disk.

Run AFTER ``run_cdia_followup_only.py`` and BEFORE
``generate_cdia_phase2.py``.

Output: overwrites the per-mode JSONs with the rescored summaries and emits
``cdia_followup_<mode>__embed.json`` so the original string-based score is
preserved alongside.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.embedding_matcher import EmbeddingTitleMatcher  # noqa: E402


ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = ROOT / "app" / "data" / "followup_evaluation_runs"

FOLLOWUP_TYPES = (
    "recurring_unresolved",
    "scope_change",
    "new_blocker",
    "blocker_resolved",
    "possible_duplicate",
    "contradicts_decision",
    "verbal_close",
)


def _split_pair(pair: dict) -> tuple[list[dict], list[dict]]:
    """Reconstruct (expected, predicted) lists from a serialized pair result.

    The original list of *expected* equals the matched ones (one entry per
    `matches`) plus the *missing_expected* the matcher could not pair. The
    list of *predicted* equals the matched ones plus the *unexpected_predicted*
    the matcher could not pair. We use the matched entries' titles+types
    from both sides to reconstruct both lists.
    """
    expected: list[dict] = []
    predicted: list[dict] = []

    for m in pair.get("matches", []):
        expected.append({
            "followup_type": m.get("expected_type") or m.get("expected_followup_type"),
            "matched_history_title": m.get("expected_title") or m.get("expected_matched_history_title", ""),
        })
        predicted.append({
            "followup_type": m.get("predicted_type") or m.get("predicted_followup_type"),
            "matched_history_title": m.get("expected_title") or "",
        })
    for e in pair.get("missing_expected", []):
        expected.append({
            "followup_type": e.get("followup_type"),
            "matched_history_title": e.get("matched_history_title", ""),
        })
    for p in pair.get("unexpected_predicted", []):
        predicted.append({
            "followup_type": p.get("followup_type"),
            "matched_history_title": p.get("matched_history_title", ""),
        })
    return expected, predicted


def _rematch_pair(
    expected: list[dict],
    predicted: list[dict],
    matcher: EmbeddingTitleMatcher,
    soft_threshold: float = 0.55,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Rebuild matches / missing / unexpected from the (expected, predicted)
    pair using a two-tier matching protocol:

    - Hard match: cosine similarity >= matcher.threshold (0.70) is enough.
    - Soft match: cosine similarity in [soft_threshold, matcher.threshold)
      counts only if the followup_type of expected and predicted agree. The
      type agreement is the cross-validation that keeps false positives in
      check when the title alone is too noisy.
    """
    candidates: list[tuple[float, int, int]] = []
    for ei, e in enumerate(expected):
        for pi, p in enumerate(predicted):
            sim = matcher.similarity(
                e.get("matched_history_title", ""),
                p.get("matched_history_title", ""),
            )
            if sim >= matcher.threshold:
                candidates.append((sim, ei, pi))
            elif sim >= soft_threshold and e.get("followup_type") == p.get("followup_type"):
                candidates.append((sim, ei, pi))

    candidates.sort(reverse=True)
    used_e: set[int] = set()
    used_p: set[int] = set()
    matches: list[dict] = []
    for sim, ei, pi in candidates:
        if ei in used_e or pi in used_p:
            continue
        e = expected[ei]
        p = predicted[pi]
        matches.append({
            "expected_title": e.get("matched_history_title", ""),
            "expected_type": e.get("followup_type"),
            "predicted_type": p.get("followup_type"),
            "similarity": float(sim),
            "correct_type": e.get("followup_type") == p.get("followup_type"),
        })
        used_e.add(ei)
        used_p.add(pi)

    missing = [expected[i] for i in range(len(expected)) if i not in used_e]
    unexpected = [predicted[i] for i in range(len(predicted)) if i not in used_p]
    return matches, missing, unexpected


def _summarize_pairs(pairs: list[dict]) -> dict:
    tp = {t: 0 for t in FOLLOWUP_TYPES}
    fp = {t: 0 for t in FOLLOWUP_TYPES}
    fn = {t: 0 for t in FOLLOWUP_TYPES}
    confusion = {a: {b: 0 for b in FOLLOWUP_TYPES} for a in FOLLOWUP_TYPES}

    expected_total = 0
    predicted_total = 0
    matched_total = 0

    for pair in pairs:
        expected_total += pair["expected_count"]
        predicted_total += pair["predicted_count"]
        matched_total += pair["matched_count"]
        for m in pair["matches"]:
            et = m["expected_type"]
            pt = m["predicted_type"]
            if et and pt:
                confusion[et][pt] += 1
                if et == pt:
                    tp[et] += 1
                else:
                    fn[et] += 1
                    fp[pt] += 1
        for e in pair.get("missing_expected", []):
            fn[e["followup_type"]] += 1
        for p in pair.get("unexpected_predicted", []):
            fp[p["followup_type"]] += 1

    precision_by = {t: tp[t] / (tp[t] + fp[t]) if (tp[t] + fp[t]) else 0.0 for t in FOLLOWUP_TYPES}
    recall_by = {t: tp[t] / (tp[t] + fn[t]) if (tp[t] + fn[t]) else 0.0 for t in FOLLOWUP_TYPES}
    f1_by = {
        t: (2 * precision_by[t] * recall_by[t] / (precision_by[t] + recall_by[t]))
        if (precision_by[t] + recall_by[t]) else 0.0
        for t in FOLLOWUP_TYPES
    }

    tp_t = sum(tp.values())
    fp_t = sum(fp.values())
    fn_t = sum(fn.values())
    precision_micro = tp_t / (tp_t + fp_t) if (tp_t + fp_t) else 0.0
    recall_micro = tp_t / (tp_t + fn_t) if (tp_t + fn_t) else 0.0
    f1_micro = (
        2 * precision_micro * recall_micro / (precision_micro + recall_micro)
        if (precision_micro + recall_micro) else 0.0
    )

    return {
        "pair_count": len(pairs),
        "completed_pairs": sum(1 for p in pairs if p["status"] == "completed"),
        "failed_pairs": sum(1 for p in pairs if p["status"] == "failed"),
        "expected_count": expected_total,
        "predicted_count": predicted_total,
        "matched_count": matched_total,
        "correct_type_count": sum(1 for pair in pairs for m in pair["matches"] if m["correct_type"]),
        "coverage": matched_total / expected_total if expected_total else 0.0,
        "precision_micro": precision_micro,
        "recall_micro": recall_micro,
        "f1_micro": f1_micro,
        "precision_macro": sum(precision_by.values()) / len(FOLLOWUP_TYPES),
        "recall_macro": sum(recall_by.values()) / len(FOLLOWUP_TYPES),
        "f1_macro": sum(f1_by.values()) / len(FOLLOWUP_TYPES),
        "precision_by_type": precision_by,
        "recall_by_type": recall_by,
        "f1_by_type": f1_by,
        "confusion_matrix": confusion,
    }


def _rescore_family(family: str, matcher: EmbeddingTitleMatcher, t0: float) -> dict:
    """Rescore a family of run JSONs (e.g. 'cdia_followup' or
    'cdia_followup_openai') against the embedding matcher."""
    rescored: dict[str, dict] = {}
    for mode in ("off", "current", "all"):
        src = RUNS_DIR / f"{family}_{mode}.json"
        if not src.exists():
            print(f"  [{family}] skip mode={mode}: source not found")
            continue
        original = json.loads(src.read_text(encoding="utf-8"))
        new_pairs: list[dict] = []

        for pair in original["pair_results"]:
            if pair["status"] != "completed":
                new_pairs.append(pair)
                continue
            expected, predicted = _split_pair(pair)
            matches, missing, unexpected = _rematch_pair(expected, predicted, matcher)
            correct = sum(1 for m in matches if m["correct_type"])
            new_pairs.append({
                "series_id": pair.get("series_id", ""),
                "meeting_1_id": pair.get("meeting_1_id", ""),
                "meeting_2_id": pair.get("meeting_2_id", ""),
                "expected_count": len(expected),
                "predicted_count": len(predicted),
                "matched_count": len(matches),
                "correct_type_count": correct,
                "matches": matches,
                "missing_expected": missing,
                "unexpected_predicted": unexpected,
                "status": "completed",
                "error": None,
            })

        summary = _summarize_pairs(new_pairs)
        new_doc = {
            "evaluation_id": original.get("evaluation_id"),
            "created_at": original.get("created_at"),
            "pipeline_id": original.get("pipeline_id"),
            "matching_threshold": matcher.threshold,
            "matching_protocol": "embedding-cosine",
            "retrieval_mode": mode,
            "pair_results": new_pairs,
            "summary": summary,
        }
        out = RUNS_DIR / f"{family}_{mode}__embed.json"
        out.write_text(json.dumps(new_doc, indent=2), encoding="utf-8")
        rescored[mode] = summary
        print(
            f"[{int(time.time()-t0):4d}s] [{family:24}] mode={mode:>7} "
            f"matched={summary['matched_count']}/{summary['expected_count']} "
            f"precision={summary['precision_micro']:.3f} "
            f"recall={summary['recall_micro']:.3f} "
            f"f1={summary['f1_micro']:.3f} "
            f"coverage={summary['coverage']:.3f}"
        )
    return rescored


def main() -> None:
    t0 = time.time()
    matcher = EmbeddingTitleMatcher(threshold=0.70)

    rescored_local = _rescore_family("cdia_followup", matcher, t0)
    rescored_openai = _rescore_family("cdia_followup_openai", matcher, t0)

    if rescored_local or rescored_openai:
        rescored = rescored_local  # backwards-compat name for combined summary
        extraction = json.loads((RUNS_DIR / "cdia_extraction.json").read_text(encoding="utf-8"))
        es = extraction.get("summary", extraction)
        combined = {
            "extraction": {
                "precision_micro": es.get("precision_micro", 0.0),
                "recall_micro": es.get("recall_micro", 0.0),
                "f1_micro": es.get("f1_micro", 0.0),
                "precision_macro": es.get("precision_macro", 0.0),
                "recall_macro": es.get("recall_macro", 0.0),
                "f1_macro": es.get("f1_macro", 0.0),
                "expected_count": es.get("expected_count", 0),
                "matched_count": es.get("matched_count", 0),
            },
            "matching_protocol": "embedding-cosine",
            "embedding_threshold": matcher.threshold,
            "followup_local": rescored_local,
            "followup_openai": rescored_openai,
        }
        (RUNS_DIR / "cdia_combined_summary__embed.json").write_text(
            json.dumps(combined, indent=2), encoding="utf-8"
        )
        print(f"[{int(time.time()-t0):4d}s] combined summary -> cdia_combined_summary__embed.json")

    print(f"[{int(time.time()-t0):4d}s] DONE in {(time.time()-t0)/60:.1f} min")


if __name__ == "__main__":
    main()
