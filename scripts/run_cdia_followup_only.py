"""
Run only the follow-up ablation (reusing the extraction.json already on disk).
Patches the Ollama client timeout to 600s so qwen2.5:7b can finish long
follow-up prompts on CPU without raising socket.timeout.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Patch Ollama client timeout BEFORE importing anything that uses it.
from app.agents import ollama_client as _ollama  # noqa: E402
_original_chat = _ollama.OllamaChatClient.chat


def _patched_chat(self, **kwargs):
    kwargs.setdefault("timeout", 600)
    return _original_chat(self, **kwargs)


_ollama.OllamaChatClient.chat = _patched_chat

from app.services.followup_evaluation import FollowupEvaluationService  # noqa: E402
from app.services.transcript_repository import TranscriptRepository  # noqa: E402


ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "app" / "data" / "followup_evaluation_runs"


def main() -> None:
    t0 = time.time()
    transcripts = TranscriptRepository().list_transcripts()
    print(f"[{int(time.time()-t0):4d}s] {len(transcripts)} transcripts loaded", flush=True)
    print(f"[{int(time.time()-t0):4d}s] Ollama chat timeout patched to 600s", flush=True)

    svc = FollowupEvaluationService()
    results = svc.evaluate_ablation(transcripts)
    for r in results:
        out = OUT_DIR / f"cdia_followup_{r.retrieval_mode}.json"
        out.write_text(r.model_dump_json(indent=2), encoding="utf-8")
        s = r.summary
        print(
            f"[{int(time.time()-t0):4d}s] mode={r.retrieval_mode:>7} "
            f"pairs={s.completed_pairs}/{s.pair_count} "
            f"recall_micro={s.recall_micro:.3f} "
            f"f1_micro={s.f1_micro:.3f} "
            f"coverage={s.coverage:.3f}",
            flush=True,
        )

    # Re-emit the combined summary now that followup_* JSONs exist.
    extraction = json.loads((OUT_DIR / "cdia_extraction.json").read_text(encoding="utf-8"))
    es = extraction["summary"]
    combined = {
        "extraction": {
            "precision_micro": es["precision_micro"],
            "recall_micro": es["recall_micro"],
            "f1_micro": es["f1_micro"],
            "precision_macro": es["precision_macro"],
            "recall_macro": es["recall_macro"],
            "f1_macro": es["f1_macro"],
            "expected_count": es["expected_count"],
            "matched_count": es["matched_count"],
        },
        "followup": {
            r.retrieval_mode: {
                "pair_count": r.summary.pair_count,
                "completed_pairs": r.summary.completed_pairs,
                "expected_count": r.summary.expected_count,
                "predicted_count": r.summary.predicted_count,
                "matched_count": r.summary.matched_count,
                "coverage": r.summary.coverage,
                "precision_micro": r.summary.precision_micro,
                "recall_micro": r.summary.recall_micro,
                "f1_micro": r.summary.f1_micro,
                "precision_macro": r.summary.precision_macro,
                "recall_macro": r.summary.recall_macro,
                "f1_macro": r.summary.f1_macro,
                "precision_by_type": r.summary.precision_by_type,
                "recall_by_type": r.summary.recall_by_type,
                "f1_by_type": r.summary.f1_by_type,
                "confusion_matrix": r.summary.confusion_matrix,
            }
            for r in results
        },
    }
    (OUT_DIR / "cdia_combined_summary.json").write_text(
        json.dumps(combined, indent=2), encoding="utf-8"
    )
    print(f"[{int(time.time()-t0):4d}s] DONE in {(time.time()-t0)/60:.1f} min", flush=True)


if __name__ == "__main__":
    main()
