"""Run the extraction evaluation (task_proposal + task_validation) over the
ENGLISH dataset using the local pipeline configuration (``qwen2.5:7b`` /
``gemma3:4b`` per Decision 016).

Outputs to ``app/data/followup_evaluation_runs/cdia_extraction_en_local.json``.

This script measures the extraction step in isolation as a precondition of
the follow-up evaluation reported in section 7.5.2 of the CDIA memoir. It
runs only the local model line; the follow-up evaluation covers the model
comparison.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Patch Ollama timeout BEFORE importing anything that uses it.
from app.agents import ollama_client as _ollama  # noqa: E402
_original_chat = _ollama.OllamaChatClient.chat


def _patched_chat(self, **kwargs):
    kwargs.setdefault("timeout", 600)
    return _original_chat(self, **kwargs)


_ollama.OllamaChatClient.chat = _patched_chat

# Repoint transcript repository to the EN dataset.
from app.services import transcript_repository as _repo  # noqa: E402
_original_repo_init = _repo.TranscriptRepository.__init__


def _patched_repo_init(self) -> None:
    _original_repo_init(self)
    self.base_dir = ROOT / "app" / "data" / "transcripts_en"


_repo.TranscriptRepository.__init__ = _patched_repo_init

# Repoint agent prompts to the EN versions.
from app.agents import catalog as _catalog  # noqa: E402
_original_catalog_load = _catalog.AgentCatalogLoader.load


def _patched_catalog_load(self):
    cat = _original_catalog_load(self)
    for a in cat.agents:
        a.system_prompt_path = a.system_prompt_path.replace(
            "\\config\\prompts\\", "\\config\\prompts_en\\"
        ).replace(
            "/config/prompts/", "/config/prompts_en/"
        )
    return cat


_catalog.AgentCatalogLoader.load = _patched_catalog_load

from app.services.dataset_evaluation import DatasetEvaluationService  # noqa: E402
from app.services.transcript_repository import TranscriptRepository  # noqa: E402


OUT_DIR = ROOT / "app" / "data" / "followup_evaluation_runs"


def main() -> None:
    t0 = time.time()
    transcripts = TranscriptRepository().list_transcripts()
    print(f"[{int(time.time()-t0):4d}s] {len(transcripts)} transcripts loaded (EN dataset)", flush=True)

    svc = DatasetEvaluationService()
    print(f"[{int(time.time()-t0):4d}s] starting extraction evaluation...", flush=True)
    result = svc.evaluate_dataset(transcripts)
    s = result.summary
    print(
        f"[{int(time.time()-t0):4d}s] done — expected={s.expected_count} "
        f"detected={s.detected_count} matched={s.matched_count} "
        f"precision={s.precision:.3f} recall={s.recall:.3f} f1={s.f1:.3f}",
        flush=True,
    )

    out = OUT_DIR / "cdia_extraction_en_local.json"
    out.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    print(f"[{int(time.time()-t0):4d}s] wrote {out.name}", flush=True)
    print(f"[{int(time.time()-t0):4d}s] DONE in {(time.time()-t0)/60:.1f} min", flush=True)


if __name__ == "__main__":
    main()
