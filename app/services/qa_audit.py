"""Audit log for the Q&A endpoint (G6 of the RAG guardrails, Decisión 022).

Every answered question is appended as a single JSON Lines record to a
daily file under ``app/data/qa_audit/YYYY-MM-DD.jsonl``. The record
captures the question, the active runtime profile, the confidence band,
the indices of the cited sources and the indices of any hallucinated
citations flagged by the citation-verification guardrail.

The file is intentionally append-only and human-readable: the operator
can ``tail -f`` it to see questions in flight, and a future report can
aggregate it without parsing extra metadata. No PII is added beyond what
the user typed; the answer body is truncated to 2000 characters so the
file does not balloon on long Q&A sessions.

Failures inside this module are swallowed by the caller, by design: an
audit log error must never prevent a user from getting their answer.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

_AUDIT_DIR = Path(__file__).resolve().parents[1] / "data" / "qa_audit"
_ANSWER_TRUNCATE = 2000


def _audit_file_for_today() -> Path:
    return _AUDIT_DIR / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.jsonl"


def write_audit_entry(
    *,
    question: str,
    sprint_id: str | None,
    confidence_band: str,
    top_similarity: float,
    source_count: int,
    source_indices: list[int],
    hallucinated_citations: list[int],
    answer: str,
) -> None:
    """Append one structured entry to the audit log."""
    from app.services.runtime_profile import get_chat_model, get_runtime_profile

    _AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "runtime_profile": get_runtime_profile(),
        "model": get_chat_model() or "agents.json default",
        "question": question,
        "sprint_scope": sprint_id,
        "confidence_band": confidence_band,
        "top_similarity": round(top_similarity, 4),
        "source_count": source_count,
        "source_indices": source_indices,
        "hallucinated_citations": hallucinated_citations,
        "answer": answer[:_ANSWER_TRUNCATE],
        "answer_truncated": len(answer) > _ANSWER_TRUNCATE,
    }
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    with _audit_file_for_today().open("a", encoding="utf-8") as f:
        f.write(line)


def write_guardrail_block(
    *,
    question: str,
    sprint_id: str | None,
    rule: str,
    detail: str,
    extra: dict | None = None,
) -> None:
    """Audit entry for a blocked question. Captures which guardrail rule
    fired and why so the operator can later distinguish abuse attempts
    from legitimate scope misses."""
    from app.services.runtime_profile import get_runtime_profile

    _AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "runtime_profile": get_runtime_profile(),
        "event": "guardrail_block",
        "rule": rule,
        "detail": detail,
        "question": question,
        "sprint_scope": sprint_id,
    }
    if extra:
        entry["extra"] = extra
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    with _audit_file_for_today().open("a", encoding="utf-8") as f:
        f.write(line)
