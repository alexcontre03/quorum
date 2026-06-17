"""
End-to-end OpenAI benchmark on the ENGLISH dataset
(``app/data/transcripts_en``) with the English system prompts under
``app/config/prompts_en``. Every chat agent is backed by gpt-4o-mini;
embeddings remain local.

Outputs land in:
    app/data/followup_evaluation_runs/cdia_followup_openai_en_{mode}.json
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib import error, request

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.agents import ollama_client as _ollama  # noqa: E402
from app.agents.exceptions import AgentExecutionError  # noqa: E402
from app.config.runtime_settings import load_environment  # noqa: E402


load_environment()

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_TIMEOUT = int(os.getenv("OPENAI_TIMEOUT", "240"))
OPENAI_MAX_RETRIES = 4

_original_embed = _ollama.OllamaChatClient.embed


def _openai_chat(
    self,
    *,
    base_url: str,
    model: str,
    messages: list[dict[str, str]],
    response_format: str | dict[str, Any] = "json",
    temperature: float = 0.1,
    options: dict[str, Any] | None = None,
    timeout: int = OPENAI_TIMEOUT,
) -> dict[str, Any]:
    if not OPENAI_API_KEY:
        raise AgentExecutionError("OPENAI_API_KEY is not set in the environment.")

    if isinstance(response_format, dict):
        api_response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "agent_response",
                "strict": True,
                "schema": response_format,
            },
        }
    else:
        api_response_format = {"type": "json_object"}

    payload = {
        "model": OPENAI_MODEL,
        "messages": messages,
        "temperature": temperature,
        "response_format": api_response_format,
    }
    req = request.Request(
        url=OPENAI_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPENAI_API_KEY}",
        },
        method="POST",
    )

    last_exc: Exception | None = None
    for attempt in range(1, OPENAI_MAX_RETRIES + 1):
        try:
            with request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            content = body["choices"][0]["message"]["content"]
            return {"message": {"content": content}, "_usage": body.get("usage", {})}
        except error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="ignore")
            if exc.code == 429 or 500 <= exc.code < 600:
                last_exc = AgentExecutionError(f"OpenAI HTTP {exc.code} (attempt {attempt}): {err_body[:200]}")
                time.sleep(2 ** attempt)
                continue
            raise AgentExecutionError(f"OpenAI HTTP error {exc.code}: {err_body}") from exc
        except (error.URLError, TimeoutError, OSError) as exc:
            last_exc = AgentExecutionError(f"OpenAI transport error (attempt {attempt}): {exc}")
            time.sleep(2 ** attempt)
            continue
    raise last_exc or AgentExecutionError("OpenAI: retries exhausted")


def main() -> None:
    if not OPENAI_API_KEY:
        raise SystemExit("OPENAI_API_KEY not set in .env.")

    _ollama.OllamaChatClient.chat = _openai_chat
    _ollama.OllamaChatClient.embed = _original_embed

    from app.services import transcript_repository as _repo
    _original_repo_init = _repo.TranscriptRepository.__init__

    def _patched_repo_init(self) -> None:
        _original_repo_init(self)
        self.base_dir = ROOT / "app" / "data" / "transcripts_en"

    _repo.TranscriptRepository.__init__ = _patched_repo_init

    from app.agents import catalog as _catalog
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

    from app.services.followup_evaluation import FollowupEvaluationService
    from app.services.transcript_repository import TranscriptRepository

    t0 = time.time()
    transcripts = TranscriptRepository().list_transcripts()
    print(f"[{int(time.time()-t0):4d}s] {len(transcripts)} transcripts loaded (EN dataset)", flush=True)
    print(f"[{int(time.time()-t0):4d}s] All chat agents backed by {OPENAI_MODEL}", flush=True)
    print(f"[{int(time.time()-t0):4d}s] System prompts redirected to prompts_en/", flush=True)
    if transcripts:
        print(f"[{int(time.time()-t0):4d}s] First transcript title: {transcripts[0].title!r}", flush=True)

    svc = FollowupEvaluationService()
    out_dir = ROOT / "app" / "data" / "followup_evaluation_runs"
    for mode in ("off", "current", "all"):
        out = out_dir / f"cdia_followup_openai_en_{mode}.json"
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
