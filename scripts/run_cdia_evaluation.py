"""
Run the full CDIA evaluation: extraction + follow-up ablation over the three
retrieval modes, persist the results to disk and write a JSON summary that the
build_memoria pipeline can read to render real numbers and figures.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.dataset_evaluation import DatasetEvaluationService
from app.services.followup_evaluation import FollowupEvaluationService
from app.services.transcript_repository import TranscriptRepository


ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "app" / "data" / "followup_evaluation_runs"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def main() -> None:
    t_start = time.time()

    repo = TranscriptRepository()
    transcripts = repo.list_transcripts()
    print(f"[{int(time.time()-t_start):4d}s] Loaded {len(transcripts)} transcripts")

    # 1. Extraction evaluation (precondition for the followup chapter)
    print(f"[{int(time.time()-t_start):4d}s] Running extraction evaluation...")
    extraction = DatasetEvaluationService().evaluate_dataset(transcripts)
    ext_path = OUT_DIR / "cdia_extraction.json"
    ext_path.write_text(extraction.model_dump_json(indent=2), encoding="utf-8")
    print(f"[{int(time.time()-t_start):4d}s] Extraction OK -> {ext_path.name}")

    # 2. Follow-up ablation (off / current / all)
    print(f"[{int(time.time()-t_start):4d}s] Running follow-up ablation (3 modes)...")
    svc = FollowupEvaluationService()
    results = svc.evaluate_ablation(transcripts)
    for r in results:
        mode = r.retrieval_mode
        out = OUT_DIR / f"cdia_followup_{mode}.json"
        out.write_text(r.model_dump_json(indent=2), encoding="utf-8")
        s = r.summary
        print(
            f"[{int(time.time()-t_start):4d}s] mode={mode:>7} "
            f"pairs={s.completed_pairs}/{s.pair_count} "
            f"recall_micro={s.recall_micro:.3f} "
            f"f1_micro={s.f1_micro:.3f} "
            f"coverage={s.coverage:.3f}"
        )

    # 3. Combined summary JSON for the report pipeline
    combined = {
        "extraction": {
            "precision_micro": extraction.summary.precision_micro,
            "recall_micro": extraction.summary.recall_micro,
            "f1_micro": extraction.summary.f1_micro,
            "precision_macro": extraction.summary.precision_macro,
            "recall_macro": extraction.summary.recall_macro,
            "f1_macro": extraction.summary.f1_macro,
            "expected_count": extraction.summary.expected_count,
            "matched_count": extraction.summary.matched_count,
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
    summary_path = OUT_DIR / "cdia_combined_summary.json"
    summary_path.write_text(json.dumps(combined, indent=2), encoding="utf-8")
    print(f"[{int(time.time()-t_start):4d}s] Combined summary -> {summary_path.name}")
    print(f"[{int(time.time()-t_start):4d}s] DONE in {(time.time()-t_start)/60:.1f} min")


if __name__ == "__main__":
    main()
