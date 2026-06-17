"""
Smoke test: run ONE follow-up transition (s1-planning -> s1-midpoint) with
all chat agents on OpenAI and the new prompt. Print the predicted
followup_updates so we can verify that ``matched_history_title`` now matches
the ``title`` field of the history items instead of ``meeting_title``.

Cost: ~5 OpenAI calls (~$0.02-$0.05).
"""

from __future__ import annotations

import json
import os
import sys
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


def _openai_chat(self, *, base_url, model, messages, response_format="json",
                 temperature=0.1, options=None, timeout=120):
    if not OPENAI_API_KEY:
        raise AgentExecutionError("OPENAI_API_KEY missing")

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
    try:
        with request.urlopen(req, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="ignore")
        raise AgentExecutionError(f"OpenAI HTTP error {exc.code}: {err_body}") from exc

    return {"message": {"content": body["choices"][0]["message"]["content"]}}


def main() -> None:
    _ollama.OllamaChatClient.chat = _openai_chat

    from app.services.followup_evaluation import FollowupEvaluationService
    from app.services.transcript_repository import TranscriptRepository

    transcripts = TranscriptRepository().list_transcripts()
    # Take only s1-planning and s1-midpoint for the smoke test
    selected = [t for t in transcripts if t.id in {"payments-s1-planning", "payments-s1-midpoint"}]
    assert len(selected) == 2, f"expected 2 transcripts, got {len(selected)}: {[t.id for t in selected]}"
    print(f"Smoke test with {[t.id for t in selected]}\n")

    svc = FollowupEvaluationService()
    result = svc.evaluate_dataset(selected, retrieval_mode="off")
    pair = result.pair_results[0]

    print(f"== Pair {pair.meeting_2_id} ==")
    print(f"expected={pair.expected_count} predicted={pair.predicted_count} matched={pair.matched_count}\n")

    print("EXPECTED (showing matched_history_title required):")
    for e in pair.missing_expected:
        print(f"  type={e.followup_type:>22}  title={e.matched_history_title!r}")
    for m in pair.matches:
        print(f"  type={m.expected_type:>22}  title={m.expected_title!r}  (MATCHED)")

    print("\nPREDICTED (showing what model emitted as matched_history_title):")
    for p in pair.unexpected_predicted:
        print(f"  type={p.followup_type:>22}  title={p.matched_history_title!r}")
    for m in pair.matches:
        print(f"  type={m.predicted_type:>22}  (predicted; matched expected_title above)")

    print(f"\nResult: matched_count={pair.matched_count}/{pair.expected_count}")
    if pair.matched_count == 0 and pair.predicted_count > 0:
        print("FAIL: model emitted predictions but none matched. Check whether matched_history_title still equals meeting_title.")
    elif pair.matched_count > 0:
        print(f"OK: {pair.matched_count} matches found. Safe to run the full ablation.")


if __name__ == "__main__":
    main()
