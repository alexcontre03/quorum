"""
Translate the synthetic Spanish dataset under app/data/transcripts/ to
English under app/data/transcripts_en/.

Why
---
The follow-up evaluation in section 7.5 of the CDIA chapter is bottlenecked
by Spanish-language inference on a model (qwen2.5:7b) whose training is
predominantly English. Under the retrieval phase the local model also
exhibits code-switching: it emits English titles even though prompt and
context are Spanish, which collapses the string-based match (and partially
the embedding-based one). Translating the whole dataset to English removes
the language axis from the comparison and lets section 7.5 report what the
task admits at the model's strongest language.

Invariants preserved
--------------------
1. expected_items[].title is the canonical title for the commitment. Every
   matched_history_title in expected_followups of later meetings refers to
   one of these titles. We translate the unique title set once and reuse the
   same translation everywhere, so the EN dataset preserves the byte-equal
   coupling between later FU references and earlier item titles.
2. Speaker names are NOT translated. Sprint ids, dates and structural
   metadata are preserved verbatim.
3. The translation uses OpenAI gpt-4o-mini with a low-temperature pass and
   strict instructions to avoid paraphrasing the same Spanish phrase
   differently across requests.

Outputs
-------
- app/data/transcripts_en/payments-*.json (mirroring the EN structure).
- A side-car app/data/transcripts_en/_title_translations.json with the
  Spanish to English mapping so the rescoring step can reuse it.
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

from app.config.runtime_settings import load_environment  # noqa: E402

load_environment()

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_TIMEOUT = 120

SRC_DIR = ROOT / "app" / "data" / "transcripts"
DST_DIR = ROOT / "app" / "data" / "transcripts_en"


def _openai_json(messages: list[dict[str, str]], schema: dict[str, Any]) -> dict:
    """Call OpenAI with a strict JSON schema and return the parsed message."""
    if not OPENAI_API_KEY:
        raise SystemExit("OPENAI_API_KEY missing in .env")
    payload = {
        "model": OPENAI_MODEL,
        "messages": messages,
        "temperature": 0.0,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "translation", "strict": True, "schema": schema},
        },
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
        with request.urlopen(req, timeout=OPENAI_TIMEOUT) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        raise SystemExit(f"OpenAI HTTP error {exc.code}: {exc.read().decode('utf-8', errors='ignore')}") from exc
    return json.loads(body["choices"][0]["message"]["content"])


def _translate_titles_and_summaries(transcripts: list[dict]) -> dict[str, str]:
    """Translate the union of expected_items titles+summaries and return a
    Spanish to English dict. Each Spanish phrase appears at most once in the
    input so its English translation is fixed and reusable across files."""
    strings: list[str] = []
    seen: set[str] = set()
    for t in transcripts:
        for ei in t.get("expected_items", []):
            for k in ("title", "summary"):
                v = ei.get(k, "").strip()
                if v and v not in seen:
                    strings.append(v)
                    seen.add(v)
        focus = t.get("metadata", {}).get("focus", "").strip()
        if focus and focus not in seen:
            strings.append(focus)
            seen.add(focus)
        tit = t.get("title", "").strip()
        if tit and tit not in seen:
            strings.append(tit)
            seen.add(tit)
    print(f"  {len(strings)} unique strings to translate (titles, summaries, focus, meeting titles)")
    schema = {
        "type": "object",
        "properties": {
            "translations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "es": {"type": "string"},
                        "en": {"type": "string"},
                    },
                    "required": ["es", "en"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["translations"],
        "additionalProperties": False,
    }
    system = (
        "You are a senior bilingual translator working on a synthetic software-engineering "
        "dataset for an academic evaluation. Translate each Spanish phrase to natural, "
        "concise English suitable for a Sprint planning or review meeting in a payments "
        "team. Keep technical terms (request_id, tenant, 5xx, runbook, idempotency, "
        "backoff, canary, rollout, dashboard, telemetry, SLA, p95) verbatim. Do NOT "
        "paraphrase: produce the most natural one-to-one translation. Preserve names. "
        "If the same Spanish noun phrase appears twice with slightly different wording, "
        "translate each to its own English equivalent. Return exactly one translation "
        "per input string in the same order."
    )
    user = "Translate to English (return strict JSON):\n\n" + "\n".join(
        f"{i+1}. {s}" for i, s in enumerate(strings)
    )
    result = _openai_json(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        schema,
    )
    pairs = result.get("translations", [])
    if len(pairs) != len(strings):
        raise SystemExit(f"translation count mismatch: got {len(pairs)}, expected {len(strings)}")
    # Trust positional alignment (the LLM may slightly rewrite the es side under
    # strict schema). Build the mapping from the original Spanish strings to
    # the i-th English translation, regardless of what the model echoed in `es`.
    mapping = {s: pairs[i]["en"] for i, s in enumerate(strings)}
    return mapping


def _translate_segments(meeting_id: str, segments: list[dict]) -> list[dict]:
    """Translate the list of segment texts in one call to keep the speakers'
    voice consistent within the meeting."""
    texts = [s.get("text", "") for s in segments]
    schema = {
        "type": "object",
        "properties": {
            "segments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"text_en": {"type": "string"}},
                    "required": ["text_en"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["segments"],
        "additionalProperties": False,
    }
    system = (
        "You are translating a Spanish sprint meeting transcript to English for an "
        "academic evaluation dataset. Translate each turn naturally and idiomatically, "
        "preserving the speaker's tone (informal, conversational, with hedges and "
        "fillers where present in Spanish). Keep technical terms verbatim (request_id, "
        "tenant, 5xx, runbook, idempotency, backoff, canary, rollout, dashboard, "
        "telemetry, SLA, p95, timeout). Keep speaker names and timestamps unchanged "
        "(they are not in this payload). Do not summarise or merge turns. Return one "
        "English translation per input turn in the same order."
    )
    user = f"Meeting id: {meeting_id}\n\nTurns to translate:\n\n" + "\n".join(
        f"[{i+1}] {t}" for i, t in enumerate(texts)
    )
    result = _openai_json(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        schema,
    )
    translated = result.get("segments", [])
    if len(translated) != len(segments):
        raise SystemExit(f"segment count mismatch on {meeting_id}: got {len(translated)}, expected {len(segments)}")
    out = []
    for orig, tr in zip(segments, translated):
        new = dict(orig)
        new["text"] = tr["text_en"]
        out.append(new)
    return out


def main() -> None:
    DST_DIR.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    paths = sorted(SRC_DIR.glob("*.json"))
    raw = [json.loads(p.read_text(encoding="utf-8")) for p in paths]
    print(f"[{int(time.time()-t0):4d}s] Loaded {len(raw)} transcripts")

    print(f"[{int(time.time()-t0):4d}s] Translating canonical titles, summaries and focuses...")
    title_map = _translate_titles_and_summaries(raw)
    (DST_DIR / "_title_translations.json").write_text(
        json.dumps(title_map, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[{int(time.time()-t0):4d}s] Saved title map ({len(title_map)} pairs)")

    for src_path, doc in zip(paths, raw):
        mid = doc["id"]
        print(f"[{int(time.time()-t0):4d}s] Translating segments of {mid} ({len(doc['segments'])} turns)...")
        new_segs = _translate_segments(mid, doc["segments"])

        new_doc = dict(doc)
        new_doc["title"] = title_map.get(doc.get("title", ""), doc.get("title", ""))
        meta = dict(doc.get("metadata", {}))
        focus = meta.get("focus", "")
        if focus in title_map:
            meta["focus"] = title_map[focus]
        new_doc["metadata"] = meta
        new_doc["segments"] = new_segs

        new_items = []
        for ei in doc.get("expected_items", []):
            new_items.append({
                **ei,
                "title": title_map.get(ei.get("title", ""), ei.get("title", "")),
                "summary": title_map.get(ei.get("summary", ""), ei.get("summary", "")),
            })
        new_doc["expected_items"] = new_items

        new_fus = []
        for fu in doc.get("expected_followups", []):
            es_title = fu.get("matched_history_title", "")
            en_title = title_map.get(es_title)
            if en_title is None:
                raise SystemExit(
                    f"FU title not in map for {mid}: {es_title!r}"
                )
            new_fus.append({**fu, "matched_history_title": en_title})
        new_doc["expected_followups"] = new_fus

        new_doc.pop("raw_text", None)

        out = DST_DIR / src_path.name
        out.write_text(json.dumps(new_doc, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[{int(time.time()-t0):4d}s]   -> {out.name}")

    print(f"[{int(time.time()-t0):4d}s] DONE in {(time.time()-t0)/60:.1f} min")


if __name__ == "__main__":
    main()
