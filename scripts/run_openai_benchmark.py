"""
Benchmark the cross-meeting reasoning task against a hosted frontier model
(`gpt-4o-mini` from OpenAI) and persist the result alongside the local-model
results. This script monkey-patches ONLY the ``task_followup_agent``'s LLM
client. The other five pipeline agents continue to run locally through
Ollama. That keeps the comparison clean: only the agent under direct
evaluation is swapped.

Setup
-----
1. Export your OpenAI key: ``set OPENAI_API_KEY=sk-...`` (Windows cmd)
   or ``$env:OPENAI_API_KEY="sk-..."`` (PowerShell).
2. Optional: set ``OPENAI_MODEL`` (default ``gpt-4o-mini``).
3. Run::

       python scripts/run_openai_benchmark.py

The script writes ``cdia_followup_openai_<mode>.json`` per retrieval mode
under ``app/data/followup_evaluation_runs/``. The same embedding rescoring
of ``rescore_with_embeddings.py`` can be applied afterwards.

Cost estimate
-------------
With ``gpt-4o-mini`` (USD 0.15 / 1M input tokens + USD 0.60 / 1M output
tokens) and ~15K input + ~2K output per analysis, three retrieval modes
across nine transcripts cost ~$0.10-$0.30 in total.
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

# Load .env (gitignored) so OPENAI_API_KEY does not have to be exported.
load_environment()

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_TIMEOUT = int(os.getenv("OPENAI_TIMEOUT", "180"))


class OpenAIChatClient:
    """Drop-in replacement for :class:`OllamaChatClient.chat` that targets
    the OpenAI Chat Completions endpoint. Returns the same envelope shape
    that the rest of the pipeline expects::

        {"message": {"content": "<json string>"}}
    """

    def chat(
        self,
        *,
        base_url: str,  # noqa: ARG002  (kept for API compatibility)
        model: str,     # noqa: ARG002  (overridden by OPENAI_MODEL)
        messages: list[dict[str, str]],
        response_format: str | dict[str, Any] = "json",
        temperature: float = 0.1,
        options: dict[str, Any] | None = None,  # noqa: ARG002
        timeout: int = OPENAI_TIMEOUT,
    ) -> dict[str, Any]:
        if not OPENAI_API_KEY:
            raise AgentExecutionError("OPENAI_API_KEY is not set in the environment.")

        if isinstance(response_format, dict):
            # The pipeline passes a JSON Schema. OpenAI accepts json_schema
            # as a structured-output format with a name.
            api_response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": "followup_response",
                    "strict": False,
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
        usage = body.get("usage", {})
        return {
            "message": {"content": content},
            "_usage": usage,  # not consumed by the agents; useful for logging
        }


def _patch_followup_agent_only() -> None:
    """Make only the task_followup_agent use the OpenAI client. The other
    agents keep using Ollama. We achieve this by patching the agent class
    constructor so its ``llm_client`` is the OpenAI one, and leaving the
    Ollama client class untouched.
    """
    from app.agents import task_followup_agent as tfa
    original_init = tfa.TaskFollowupAgent.__init__

    def patched_init(self, llm_client=None):
        original_init(self, llm_client=OpenAIChatClient())

    tfa.TaskFollowupAgent.__init__ = patched_init


def main() -> None:
    t0 = time.time()
    if not OPENAI_API_KEY:
        raise SystemExit("OPENAI_API_KEY not set. Export it and rerun.")

    _patch_followup_agent_only()

    # Bump local timeout for the rest of the agents (we already learned that
    # qwen2.5:7b can exceed 120s on CPU for validation steps).
    _orig_chat = _ollama.OllamaChatClient.chat

    def _patched_chat(self, **kwargs):
        kwargs.setdefault("timeout", 600)
        return _orig_chat(self, **kwargs)

    _ollama.OllamaChatClient.chat = _patched_chat

    # Import AFTER patching so the followup agent uses the OpenAI client.
    from app.services.followup_evaluation import FollowupEvaluationService  # noqa: WPS433
    from app.services.transcript_repository import TranscriptRepository  # noqa: WPS433

    transcripts = TranscriptRepository().list_transcripts()
    print(f"[{int(time.time()-t0):4d}s] {len(transcripts)} transcripts loaded", flush=True)
    print(f"[{int(time.time()-t0):4d}s] Followup agent now backed by {OPENAI_MODEL}", flush=True)

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

    print(f"[{int(time.time()-t0):4d}s] DONE in {(time.time()-t0)/60:.1f} min")


if __name__ == "__main__":
    main()
