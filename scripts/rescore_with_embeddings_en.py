"""Rescore the EN-dataset follow-up runs (``cdia_followup_en_*`` and
``cdia_followup_openai_en_*``) under the embedding-based protocol. Writes
``cdia_followup_en_<mode>__embed.json`` and ``cdia_followup_openai_en_<mode>__embed.json``,
plus ``cdia_combined_summary_en__embed.json`` aggregating both lines.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.services.embedding_matcher import EmbeddingTitleMatcher  # noqa: E402

# Reuse the helpers from the original rescore script.
from scripts.rescore_with_embeddings import _rescore_family  # noqa: E402


RUNS_DIR = ROOT / "app" / "data" / "followup_evaluation_runs"


def main() -> None:
    t0 = time.time()
    matcher = EmbeddingTitleMatcher(threshold=0.70)

    rescored_local = _rescore_family("cdia_followup_en", matcher, t0)
    rescored_openai = _rescore_family("cdia_followup_openai_en", matcher, t0)

    combined = {
        "matching_protocol": "embedding-cosine",
        "embedding_threshold": matcher.threshold,
        "dataset": "transcripts_en",
        "language": "en",
        "followup_local": rescored_local,
        "followup_openai": rescored_openai,
    }
    out = RUNS_DIR / "cdia_combined_summary_en__embed.json"
    out.write_text(json.dumps(combined, indent=2), encoding="utf-8")
    print(f"[{int(time.time()-t0):4d}s] combined summary -> {out.name}")

    print(f"[{int(time.time()-t0):4d}s] DONE in {(time.time()-t0)/60:.1f} min")


if __name__ == "__main__":
    main()
