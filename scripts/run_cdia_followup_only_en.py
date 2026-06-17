"""
Run the follow-up ablation against the ENGLISH-translated dataset
(``app/data/transcripts_en``) using the English system prompts under
``app/config/prompts_en``. Local ``qwen2.5:7b`` is kept as the backbone so
the comparison with ``run_cdia_followup_only.py`` (Spanish dataset) is
direct.

Outputs land in:
    app/data/followup_evaluation_runs/cdia_followup_en_{mode}.json
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Patch Ollama client timeout BEFORE importing anything that uses it.
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

# Repoint agent prompts to the EN versions by rewriting the resolved path
# inside AgentCatalog at load time.
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

from app.services.followup_evaluation import FollowupEvaluationService  # noqa: E402
from app.services.transcript_repository import TranscriptRepository  # noqa: E402


OUT_DIR = ROOT / "app" / "data" / "followup_evaluation_runs"


def main() -> None:
    t0 = time.time()
    transcripts = TranscriptRepository().list_transcripts()
    print(f"[{int(time.time()-t0):4d}s] {len(transcripts)} transcripts loaded (EN dataset)", flush=True)
    print(f"[{int(time.time()-t0):4d}s] Ollama chat timeout patched to 600s", flush=True)
    print(f"[{int(time.time()-t0):4d}s] System prompts redirected to prompts_en/", flush=True)
    # Sanity check: dump first transcript title to confirm EN.
    if transcripts:
        print(f"[{int(time.time()-t0):4d}s] First transcript title: {transcripts[0].title!r}", flush=True)

    svc = FollowupEvaluationService()
    for mode in ("off", "current", "all"):
        out = OUT_DIR / f"cdia_followup_en_{mode}.json"
        if out.exists():
            print(f"[{int(time.time()-t0):4d}s] mode={mode:>7} already exists, skipping", flush=True)
            continue
        print(f"[{int(time.time()-t0):4d}s] mode={mode:>7} starting...", flush=True)
        r = svc.evaluate_dataset(transcripts, retrieval_mode=mode)
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

    print(f"[{int(time.time()-t0):4d}s] DONE in {(time.time()-t0)/60:.1f} min", flush=True)


if __name__ == "__main__":
    main()
