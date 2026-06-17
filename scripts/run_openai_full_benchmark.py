"""
End-to-end OpenAI benchmark: every language-model agent of the pipeline
(``task_proposal``, ``task_validation``, ``issue_draft``, ``git_evidence``,
``task_followup``) is backed by OpenAI ``gpt-4o-mini``. The embedding step
(retrieval phase) still uses the local ``embeddinggemma:latest`` so the
comparison stays focused on the chat agents.

Why this script exists
----------------------
``run_openai_benchmark.py`` only swapped the follow-up agent. Because the
local ``qwen2.5:7b`` validation step runs at ~60-120s per analysis on CPU,
that script was bottlenecked on Ollama even though the follow-up itself
fired against OpenAI in seconds. With every chat agent on OpenAI, the
ablation finishes in ~10-15 minutes total and the comparison is "100%
local vs 100% frontier", which is what the §7.5 narrative needs.

Cost estimate
-------------
Roughly ~$0.50-$1.50 total for the three retrieval modes.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib import error, request

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents import ollama_client as _ollama  # noqa: E402
from app.agents.exceptions import AgentExecutionError  # noqa: E402
from app.config.runtime_settings import load_environment  # noqa: E402


load_environment()

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_TIMEOUT = int(os.getenv("OPENAI_TIMEOUT", "120"))

# Save the original embed implementation so the retrieval phase keeps
# using the local embeddinggemma model.
_original_embed = _ollama.OllamaChatClient.embed


def _openai_chat(
    self,
    *,
    base_url: str,  # noqa: ARG001 (drop)
    model: str,     # noqa: ARG001 (drop; replaced by OPENAI_MODEL)
    messages: list[dict[str, str]],
    response_format: str | dict[str, Any] = "json",
    temperature: float = 0.1,
    options: dict[str, Any] | None = None,  # noqa: ARG001
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
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url=OPENAI_API_URL,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPENAI_API_KEY}",
        },
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="ignore")
        raise AgentExecutionError(f"OpenAI HTTP error {exc.code}: {err_body}") from exc
    except error.URLError as exc:
        raise AgentExecutionError(f"Could not reach OpenAI: {exc.reason}") from exc

    choices = body.get("choices") or []
    if not choices:
        raise AgentExecutionError(f"OpenAI response without choices: {body}")
    content = choices[0].get("message", {}).get("content", "")
    return {
        "message": {"content": content},
        "_usage": body.get("usage", {}),
    }


def main() -> None:
    if not OPENAI_API_KEY:
        raise SystemExit("OPENAI_API_KEY not set in .env. Add it and rerun.")

    # Patch chat to use OpenAI; keep embed local.
    _ollama.OllamaChatClient.chat = _openai_chat
    _ollama.OllamaChatClient.embed = _original_embed  # explicit no-op restore

    # Import AFTER patching.
    from app.services.followup_evaluation import FollowupEvaluationService  # noqa: WPS433
    from app.services.transcript_repository import TranscriptRepository  # noqa: WPS433

    t0 = time.time()
    transcripts = TranscriptRepository().list_transcripts()
    print(f"[{int(time.time()-t0):4d}s] {len(transcripts)} transcripts loaded", flush=True)
    print(f"[{int(time.time()-t0):4d}s] All chat agents now backed by {OPENAI_MODEL}", flush=True)
    print(f"[{int(time.time()-t0):4d}s] Embeddings still use local embeddinggemma", flush=True)

    svc = FollowupEvaluationService()
    results = svc.evaluate_ablation(transcripts)

    out_dir = Path(__file__).resolve().parent.parent / "app" / "data" / "followup_evaluation_runs"
    for r in results:
        out = out_dir / f"cdia_followup_openai_{r.retrieval_mode}.json"
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
