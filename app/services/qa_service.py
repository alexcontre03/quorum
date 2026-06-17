"""Servicio Q&A asistido por RAG sobre transcripciones y compromisos (Decisión 013).

Combina dos fuentes de recuperación:
  1) `TranscriptRetriever` (Decisión 012) sobre los chunks de transcripciones del dataset.
  2) `CommitmentIndexer` (esta decisión) sobre los compromisos del repositorio.

Une los top-K de cada fuente, reordena por similitud de coseno y construye un prompt para
`gemma3:4b` que exige citación con la notación `[N]`. La respuesta se streamea token a token al
endpoint, que la envuelve en NDJSON para el cliente.

El servicio asegura que ambos índices están al día antes de cada consulta: indexa
perezosamente las transcripciones que no estén indexadas todavía y refresca el índice de
compromisos si el repositorio ha cambiado desde la última vez. El coste de "garantizar índices"
en un dataset pequeño es despreciable; en un dataset mayor habría que mover esta verificación
a un job en segundo plano.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Iterable

import numpy as np

from app.agents.exceptions import AgentExecutionError
from app.agents.chat_client import ChatClient
from app.agents.client_factory import get_chat_client, get_embed_client
from app.config.runtime_settings import EmbeddingRuntimeSettings, get_embedding_settings
from app.domain.models import QAScope, QASource
from app.services.analysis_run_repository import AnalysisRunRepository
from app.services.commitment_indexer import CommitmentIndexer
from app.services.transcript_repository import TranscriptRepository
from app.services.transcript_retriever import TranscriptRetriever, _l2_normalize


_logger = logging.getLogger(__name__)

DEFAULT_TOTAL_K = 7
PER_SOURCE_K = 4
MIN_SIMILARITY = 0.40
CHUNK_TEXT_TRUNCATE = 1000
DEFAULT_QA_MODEL = "gemma3:4b"
DEFAULT_QA_BASE_URL = "http://127.0.0.1:11434/api"
QA_TEMPERATURE = 0.2

# ===== Guardrails (Decisión 022) =====
#
# Six lightweight checks layered around the RAG pipeline. None of them
# requires an extra LLM round-trip; they all run as cheap string / numeric
# operations on the question, on the retrieved sources or on the streamed
# answer. The aim is to make the system honest about what it knows
# (abstention), defensive against trivial misuse (length, injection), and
# auditable (audit log + cited-sources verification).

# G4 — Length limit on the user question. Anything beyond is rejected with
# a clear message instead of being silently truncated. 600 characters is
# enough for any realistic agile-team query and well below typical token
# budgets of the local model.
MAX_QUESTION_CHARS = 600

# G3 — Scope abstention threshold. If the boosted similarity of the best
# retrieved chunk is below this value, the RAG refuses to answer and the
# user is told the dataset does not contain that information. This is a
# stricter cousin of MIN_SIMILARITY: MIN_SIMILARITY filters individual
# chunks; SCOPE_MIN_TOP_SIMILARITY abstains globally.
#
# The threshold is profile-aware because the absolute cosine-similarity
# scale differs by embedding family. Ollama `embeddinggemma` returns
# ~0.55-0.75 for clearly relevant chunks; OpenAI `text-embedding-3-small`
# returns ~0.30-0.45 for the same kind of match. Using a single threshold
# would either spam abstentions on OpenAI or let weak matches through on
# Ollama. The values below are calibrated against the project dataset.
SCOPE_THRESHOLD_BY_EMBED_FAMILY = {
    "openai-text-embedding-3-small": 0.30,
    "ollama-embeddinggemma": 0.50,
}
SCOPE_MIN_TOP_SIMILARITY_DEFAULT = 0.50


def _scope_threshold_for_active_profile() -> float:
    """Resolve the SCOPE_MIN_TOP_SIMILARITY for the active runtime profile.

    Reading the family marker via ``runtime_profile`` avoids hard-coding
    knowledge of the embed family in this module. If the profile is unknown
    (custom embed override, tests), fall back to the default."""
    try:
        from app.services.runtime_profile import (
            _embed_dim_for_profile,
            get_runtime_profile,
        )
        family = _embed_dim_for_profile(get_runtime_profile())
        return SCOPE_THRESHOLD_BY_EMBED_FAMILY.get(family, SCOPE_MIN_TOP_SIMILARITY_DEFAULT)
    except Exception:
        return SCOPE_MIN_TOP_SIMILARITY_DEFAULT


# G5 — Confidence band thresholds. Both the top similarity and the number
# of retrieved sources contribute. The band is shown as a small badge under
# the answer in the UI.
CONFIDENCE_HIGH_SIM = 0.70
CONFIDENCE_MED_SIM = 0.55

# G2 — Prompt-injection patterns. Catches the obvious attempts a user might
# paste into the input. False positives are accepted: when in doubt the
# system asks the user to rephrase rather than silently following the
# injected instruction. The list is in Spanish and English because the
# dataset and the UI are bilingual.
_INJECTION_PATTERNS = (
    re.compile(r"\bignor(a|e|es|en)\s+(las|the|tus|your)?\s*(instrucciones|instructions)\b", re.IGNORECASE),
    re.compile(r"\bolvida(s|d)?\s+(las|el|tu)?\s*(instrucción|instrucciones|system)\b", re.IGNORECASE),
    re.compile(r"\bdisregard\s+(the|your|all)\s+(above|previous|prior)\b", re.IGNORECASE),
    re.compile(r"\bact(úa|ua|ún|uar)\s+como\b", re.IGNORECASE),
    re.compile(r"\bact\s+as\s+(a|an|the)\b", re.IGNORECASE),
    re.compile(r"\bsystem\s*:\s*", re.IGNORECASE),
    re.compile(r"\bnew\s+(system|instructions|prompt)\b", re.IGNORECASE),
    re.compile(r"\boverride\s+(the|your|all|safety)\b", re.IGNORECASE),
    re.compile(r"\brepeat\s+(the|your|all)\s+(prompt|instructions|system)\b", re.IGNORECASE),
    re.compile(r"\bjailbreak\b", re.IGNORECASE),
)

# Intent boosts applied during retrieval re-ranking.
#
# We only re-score (not filter) so an explicit keyword in the query lifts the
# matching chunks above the rest without dropping context entirely. Multiplied
# on top of the cosine similarity.
MEETING_KIND_BOOST = 1.45
SPRINT_BOOST = 1.30
RECENCY_BOOST_PER_RANK = 0.06  # per position when "última/reciente/etc" is detected
SIGNAL_BOOST = 1.55  # commitments matching an explicit lifecycle signal in the question

_MEETING_KIND_KEYWORDS = {
    "planning": ("planning", "planificación", "planificacion"),
    "midpoint": ("midpoint", "mitad", "intermedia", "intermedio"),
    "review": ("review", "retrospectiva", "retro"),
}
_RECENCY_KEYWORDS = (
    "última", "ultima", "último", "ultimo",
    "más reciente", "mas reciente", "reciente",
    "anteayer", "ayer", "esta semana", "ultimamente", "últimamente",
)

# Lifecycle signals: when the user explicitly asks about a kind of state
# (blocked / scope changes / etc.), commitments whose indexed text contains
# the matching marker get a multiplicative boost. The marker strings here
# must align with what `CommitmentIndexer._active_signals` emits.
_SIGNAL_KEYWORDS = {
    "blocker": (
        "bloqueo", "bloqueos", "bloqueado", "bloqueada", "bloqueados",
        "esperando", "atascado", "stuck", "blocker", "parado por",
        "depende de",
    ),
    "scope": (
        "alcance", "cambio de alcance", "scope change", "redefinid",
        "amplia", "ampliada", "reducid",
    ),
    "duplicate": (
        "duplicad", "duplicate", "ya existe",
    ),
    "recurring": (
        "se repite", "vuelve a salir", "sigue sin cerrarse",
        "recurring", "recurrente",
    ),
    "closed": (
        "cerrad", "hecho", "completad", "terminad", "ya está",
    ),
}
_SIGNAL_TO_INDEXED_MARKER = {
    "blocker": "bloqueado",
    "scope": "cambio de alcance",
    "duplicate": "posible duplicado",
    "recurring": "reaparece",
    "closed": "ya hecho",
}
_SPRINT_RE_PATTERNS = (
    re.compile(r"\bsprint\s*[-_]?\s*(\d+)\b", re.IGNORECASE),
    re.compile(r"\bs(\d+)\b"),
    re.compile(r"\bpayments-s(\d+)\b", re.IGNORECASE),
)

_SYSTEM_PROMPT = (
    "Eres un asistente que responde preguntas sobre las reuniones de un equipo de desarrollo "
    "de software y sobre los compromisos que han surgido en ellas.\n"
    "\n"
    "Reglas:\n"
    "1. Usa ÚNICAMENTE la información del contexto que se te proporciona a continuación. "
    "No inventes datos ni completes con conocimiento general.\n"
    "2. Si la respuesta no está en el contexto, responde exactamente: "
    "\"No tengo esa información en las reuniones indexadas.\"\n"
    "3. Cita las fuentes que utilices con la notación [N], donde N es el número del fragmento "
    "en la lista de contexto. Cita siempre que afirmes un hecho concreto.\n"
    "4. Responde en castellano, con tono claro y completo. No expliques tu razonamiento ni "
    "menciones que estás usando contexto recuperado. Cubre todos los matices que el contexto "
    "soporte, con párrafos completos cuando la pregunta lo requiera.\n"
)


@dataclass(frozen=True)
class _ScoredDoc:
    similarity: float
    payload: dict
    source_type: str  # "transcript" | "commitment"


@dataclass(frozen=True)
class _QueryIntent:
    """Lightweight structured representation of the user's question. Built
    from keyword matching, not from an LLM call. Used to bias the cosine
    similarity ranking without filtering anything out (a wrong intent guess
    therefore degrades gracefully)."""
    meeting_kinds: tuple[str, ...]
    sprints: tuple[str, ...]
    wants_recent: bool
    signals: tuple[str, ...]  # subset of _SIGNAL_KEYWORDS keys


def _parse_intent(question: str) -> _QueryIntent:
    lower = question.lower()
    kinds: list[str] = []
    for kind, words in _MEETING_KIND_KEYWORDS.items():
        if any(w in lower for w in words):
            kinds.append(kind)
    sprints: list[str] = []
    seen: set[str] = set()
    for pattern in _SPRINT_RE_PATTERNS:
        for match in pattern.finditer(lower):
            num = match.group(1)
            if num and num not in seen:
                seen.add(num)
                sprints.append(f"payments-s{num}")
    wants_recent = any(k in lower for k in _RECENCY_KEYWORDS)
    signals: list[str] = []
    for signal, words in _SIGNAL_KEYWORDS.items():
        if any(w in lower for w in words):
            signals.append(signal)
    return _QueryIntent(
        meeting_kinds=tuple(kinds),
        sprints=tuple(sprints),
        wants_recent=wants_recent,
        signals=tuple(signals),
    )


def _meeting_kind_of_transcript(transcript_id: str) -> str | None:
    """Derive the meeting kind from the transcript id used by the dataset
    (e.g. ``payments-s1-review`` → ``review``)."""
    for kind in _MEETING_KIND_KEYWORDS:
        if transcript_id.endswith(f"-{kind}"):
            return kind
    return None


# ---------- Guardrails (D022) ----------


def _detect_prompt_injection(question: str) -> tuple[bool, str | None]:
    """Return ``(matched, pattern)``. ``matched=True`` means the question hits
    one of the known injection patterns and should be rejected before any
    LLM call. The pattern is returned for the audit log."""
    for pattern in _INJECTION_PATTERNS:
        match = pattern.search(question)
        if match:
            return True, pattern.pattern
    return False, None


def _grade_confidence(top_similarity: float, source_count: int) -> str:
    """Map (top similarity, source count) to a coarse confidence band that
    the UI renders as a badge. Sources count is a tiebreaker: a single
    source even with high similarity is downgraded one step, because a
    single-source answer is harder to triangulate."""
    if top_similarity >= CONFIDENCE_HIGH_SIM and source_count >= 2:
        return "high"
    if top_similarity >= CONFIDENCE_MED_SIM:
        return "medium"
    return "low"


_CITATION_RE = re.compile(r"\[(\d+)\]")


def _extract_cited_indices(answer: str) -> set[int]:
    """Return the set of ``[N]`` numbers that appear in *answer*. Used to
    verify post-stream that every citation refers to a real source."""
    return {int(m.group(1)) for m in _CITATION_RE.finditer(answer)}


class QAService:
    def __init__(
        self,
        transcript_repository: TranscriptRepository | None = None,
        transcript_retriever: TranscriptRetriever | None = None,
        commitment_indexer: CommitmentIndexer | None = None,
        analysis_runs: AnalysisRunRepository | None = None,
        ollama_client: ChatClient | None = None,
        settings: EmbeddingRuntimeSettings | None = None,
        qa_model: str = DEFAULT_QA_MODEL,
        qa_base_url: str = DEFAULT_QA_BASE_URL,
    ) -> None:
        self.transcripts = transcript_repository or TranscriptRepository()
        self.transcript_retriever = transcript_retriever or TranscriptRetriever(
            transcript_repository=self.transcripts,
        )
        self.commitment_indexer = commitment_indexer or CommitmentIndexer()
        self.analysis_runs = analysis_runs or AnalysisRunRepository()
        self._pinned_client = ollama_client
        self.settings = settings or get_embedding_settings()
        self.qa_model = qa_model
        self.qa_base_url = qa_base_url

    @property
    def ollama(self) -> ChatClient:
        """For embed calls we always want the embed-capable client of the
        current profile; for chat_stream we use the chat client. Both fall
        back to the active profile, so a UI switch takes effect on the next
        question."""
        if self._pinned_client is not None:
            return self._pinned_client
        return get_chat_client()

    def _embed_client(self) -> ChatClient:
        if self._pinned_client is not None:
            return self._pinned_client
        return get_embed_client()

    @staticmethod
    def _safe_audit_block(
        question: str,
        sprint_id: str | None,
        rule: str,
        detail: str,
        *,
        extra: dict | None = None,
    ) -> None:
        """Write a guardrail-block entry to the audit log without ever
        letting a logging failure bubble up to the caller."""
        try:
            from app.services.qa_audit import write_guardrail_block

            write_guardrail_block(
                question=question,
                sprint_id=sprint_id,
                rule=rule,
                detail=detail,
                extra=extra,
            )
        except Exception as exc:  # pragma: no cover
            _logger.warning("Audit log (guardrail) failed: %s", exc)

    def ensure_indices_ready(self) -> None:
        """Indexa lo que falte. Coste despreciable a la escala del dataset."""
        if not self.settings.enabled:
            return
        for transcript in self.transcripts.list_transcripts():
            try:
                self.transcript_retriever.ensure_indexed(transcript)
            except Exception as exc:  # pragma: no cover - defensive
                _logger.warning("Transcript indexing failed for %s: %s", transcript.id, exc)
        try:
            self.commitment_indexer.refresh_if_stale()
        except Exception as exc:  # pragma: no cover - defensive
            _logger.warning("Commitment indexing failed: %s", exc)

    def answer(
        self,
        question: str,
        sprint_id: str | None = None,
        scope: QAScope = "analyzed_only",
    ) -> Iterator[dict]:
        """Yield NDJSON-friendly events: first `sources`, then `token`s, then `done`.

        Cada elemento del iterador es un dict serializable a JSON. El endpoint los serializa con
        `json.dumps(..., ensure_ascii=False)` y los emite uno por línea, terminando con un evento
        `done`. Si algo falla durante el retrieval, emite un evento `error` y termina.
        """
        question = (question or "").strip()
        if not question:
            yield {"type": "error", "detail": "Empty question"}
            yield {"type": "done"}
            return

        # ----- G4: length limit -----
        if len(question) > MAX_QUESTION_CHARS:
            detail = (
                f"La pregunta excede el límite de {MAX_QUESTION_CHARS} caracteres. "
                "Acórtala o divídela en varias preguntas."
            )
            self._safe_audit_block(question, sprint_id, "length", detail,
                                   extra={"length": len(question)})
            yield {"type": "guardrail_block", "rule": "length", "detail": detail}
            yield {"type": "done"}
            return

        # ----- G2: prompt injection detection -----
        injected, pattern = _detect_prompt_injection(question)
        if injected:
            detail = (
                "La pregunta contiene instrucciones que parecen intentar modificar "
                "el comportamiento del asistente. Reformúlala como una pregunta "
                "sobre las reuniones del equipo."
            )
            self._safe_audit_block(question, sprint_id, "prompt_injection", detail,
                                   extra={"pattern": pattern})
            yield {
                "type": "guardrail_block",
                "rule": "prompt_injection",
                "detail": detail,
                "pattern_matched": pattern,
            }
            yield {"type": "done"}
            return

        if not self.settings.enabled:
            yield {"type": "error", "detail": "Embeddings disabled — set EMBEDDING_ENABLED=1 to enable Q&A"}
            yield {"type": "done"}
            return

        allowed_transcript_ids = self._allowed_transcript_ids(scope)
        if scope == "analyzed_only" and not allowed_transcript_ids:
            detail = (
                "Todavía no hay reuniones analizadas en esta instancia. "
                "Analiza al menos una reunión o cambia a 'Dataset completo'."
            )
            self._safe_audit_block(question, sprint_id, "empty_context", detail)
            yield {"type": "sources", "sources": []}
            yield {"type": "guardrail_block", "rule": "empty_context", "detail": detail}
            yield {"type": "token", "text": detail}
            yield {"type": "done"}
            return

        self.ensure_indices_ready()

        try:
            question_vec = self._embed_client().embed(
                base_url=self.settings.base_url,
                model=self.settings.model,
                text=question,
            )
        except AgentExecutionError as exc:
            yield {"type": "error", "detail": f"Embedding error: {exc}"}
            yield {"type": "done"}
            return

        q_unit = _l2_normalize(np.array([question_vec], dtype=np.float32))[0]

        # Parse the question for hints (meeting kind, sprint, recency) so the
        # retriever can re-rank in favour of the matching chunks. Keyword
        # detection only, no LLM round-trip.
        intent = _parse_intent(question)

        try:
            scored = self._gather_transcript_candidates(
                q_unit, sprint_id, intent, allowed_transcript_ids
            )
            scored.extend(
                self._gather_commitment_candidates(
                    q_unit, sprint_id, intent, allowed_transcript_ids
                )
            )
        except ValueError as exc:
            # Triggered when the persisted retrieval index has a different
            # embedding dimension from the active embed client (e.g. you
            # switched the runtime profile after indexing). The set-profile
            # endpoint normally wipes the indices, so reaching this branch
            # means we have an inconsistent state on disk.
            yield {
                "type": "error",
                "detail": (
                    "Los índices guardados no son compatibles con el modelo de "
                    "embeddings actual. Borra app/data/retrieval_index/ y vuelve "
                    f"a indexar (detalle: {exc})."
                ),
            }
            yield {"type": "done"}
            return
        scored.sort(key=lambda d: d.similarity, reverse=True)
        # Hard cut weak matches so the answer is not polluted by chunks the
        # model would have to ignore anyway. The threshold is on the boosted
        # similarity, so a meaningful intent match (e.g. "review" keyword
        # lifting a sprint review chunk) still passes.
        top = [d for d in scored if d.similarity >= MIN_SIMILARITY][:DEFAULT_TOTAL_K]

        if not top:
            detail = "No tengo esa información en las reuniones indexadas."
            self._safe_audit_block(question, sprint_id, "empty_context", detail)
            yield {"type": "sources", "sources": []}
            yield {"type": "guardrail_block", "rule": "empty_context", "detail": detail}
            yield {"type": "token", "text": detail}
            yield {"type": "done"}
            return

        # ----- G3: scope abstention -----
        # If even the best chunk is below the scope threshold, the dataset
        # likely does not contain the answer. Abstain without calling the
        # LLM to avoid hallucinating a confident-sounding wrong answer.
        top_similarity = top[0].similarity
        scope_threshold = _scope_threshold_for_active_profile()
        if top_similarity < scope_threshold:
            detail = (
                "No encuentro información suficientemente relevante en las "
                "reuniones indexadas para responder a esta pregunta. Si crees "
                "que debería estarlo, prueba a reformularla mencionando el "
                "sprint o el tipo de reunión (planning, midpoint, review)."
            )
            self._safe_audit_block(
                question, sprint_id, "out_of_scope", detail,
                extra={"top_similarity": float(top_similarity)},
            )
            yield {"type": "sources", "sources": []}
            yield {
                "type": "guardrail_block",
                "rule": "out_of_scope",
                "detail": detail,
                "top_similarity": float(top_similarity),
            }
            yield {
                "type": "token",
                "text": (
                    "No encuentro información suficientemente relevante en las "
                    "reuniones indexadas para responder a esta pregunta."
                ),
            }
            yield {"type": "done"}
            return

        sources = self._to_sources(top)
        yield {"type": "sources", "sources": [s.model_dump(mode="json") for s in sources]}

        # ----- G5: confidence band -----
        confidence = _grade_confidence(top_similarity, len(sources))
        yield {
            "type": "confidence",
            "band": confidence,
            "top_similarity": float(top_similarity),
            "source_count": len(sources),
        }

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": self._build_user_prompt(question, sources)},
        ]

        answer_buffer: list[str] = []
        try:
            for delta in self.ollama.chat_stream(
                base_url=self.qa_base_url,
                model=self.qa_model,
                messages=messages,
                temperature=QA_TEMPERATURE,
                options={"num_predict": 2500, "num_ctx": 8192},
            ):
                if delta:
                    answer_buffer.append(delta)
                    yield {"type": "token", "text": delta}
        except AgentExecutionError as exc:
            yield {"type": "error", "detail": f"Generation error: {exc}"}

        # ----- G1: citation verification -----
        # Verify every [N] in the answer points to a real source. Inflated
        # citations are flagged so the UI can mark them in red. We do not
        # rewrite the answer: the user sees what the model said, plus a
        # transparency note about which citations are unsupported.
        full_answer = "".join(answer_buffer)
        cited = _extract_cited_indices(full_answer)
        valid_indices = {s.index for s in sources}
        hallucinated = sorted(cited - valid_indices)
        unused = sorted(valid_indices - cited)
        yield {
            "type": "citation_audit",
            "cited": sorted(cited),
            "valid_indices": sorted(valid_indices),
            "hallucinated": hallucinated,
            "unused": unused,
        }

        # ----- G6: structured audit log -----
        try:
            from app.services.qa_audit import write_audit_entry

            write_audit_entry(
                question=question,
                sprint_id=sprint_id,
                confidence_band=confidence,
                top_similarity=float(top_similarity),
                source_count=len(sources),
                source_indices=sorted(valid_indices),
                hallucinated_citations=hallucinated,
                answer=full_answer,
            )
        except Exception as exc:  # pragma: no cover - audit must not break QA
            _logger.warning("Audit log failed: %s", exc)

        yield {"type": "done"}

    def _gather_transcript_candidates(
        self,
        question_unit_vec: np.ndarray,
        sprint_id: str | None,
        intent: _QueryIntent,
        allowed_transcript_ids: set[str] | None,
    ) -> list[_ScoredDoc]:
        out: list[_ScoredDoc] = []
        index = self.transcript_retriever.index
        # Build a date index across transcripts so the recency bias works
        # without re-reading the transcript files (which would be expensive
        # in this hot path). The recency boost uses ranking position, not
        # absolute dates, so a simple sort by date is sufficient.
        all_dates: list[tuple[str, str]] = []
        for transcript_id in index.list_indexed_transcripts():
            if transcript_id.startswith("_"):
                continue
            if not self._transcript_is_allowed(transcript_id, allowed_transcript_ids):
                continue
            payload = index.load(transcript_id)
            if payload is None:
                continue
            _, metas = payload
            meeting_date = metas[0].get("meeting_date") if metas else None
            all_dates.append((transcript_id, str(meeting_date or "")))
        all_dates.sort(key=lambda p: p[1], reverse=True)  # most recent first
        recency_rank = {tid: i for i, (tid, _) in enumerate(all_dates)}

        for transcript_id in index.list_indexed_transcripts():
            if transcript_id.startswith("_"):
                continue  # skip namespaced indices (e.g., _commitments)
            if not self._transcript_is_allowed(transcript_id, allowed_transcript_ids):
                continue
            payload = index.load(transcript_id)
            if payload is None:
                continue
            vectors, metas = payload
            meta_sprint = metas[0].get("sprint_id") if metas else None
            if sprint_id is not None and meta_sprint != sprint_id:
                continue
            # Intent-driven sprint filter (only when the chip is "all")
            if (
                sprint_id is None
                and intent.sprints
                and meta_sprint not in intent.sprints
            ):
                # We still let other-sprint chunks compete, but with a hard
                # penalty so they almost never enter the top-K.
                sprint_penalty = 0.6
            else:
                sprint_penalty = 1.0

            # Intent-driven meeting-kind boost: lifts chunks whose transcript
            # type matches what the user is asking about.
            kind = _meeting_kind_of_transcript(transcript_id)
            kind_boost = (
                MEETING_KIND_BOOST
                if intent.meeting_kinds and kind in intent.meeting_kinds
                else 1.0
            )
            # Intent-driven sprint boost: matching explicit sprint mentions.
            sprint_boost = (
                SPRINT_BOOST
                if intent.sprints and meta_sprint in intent.sprints
                else 1.0
            )
            # Recency boost: when the user asks for "última/reciente", lift
            # the most recent transcripts by a small amount per rank. The
            # most recent transcript gets `(N-1) * step` extra similarity,
            # the oldest one gets none.
            recency_boost = 1.0
            if intent.wants_recent and all_dates:
                rank = recency_rank.get(transcript_id, len(all_dates) - 1)
                recency_boost = 1.0 + max(0, len(all_dates) - 1 - rank) * RECENCY_BOOST_PER_RANK

            multiplier = kind_boost * sprint_boost * recency_boost * sprint_penalty
            sims = vectors @ question_unit_vec
            for sim, meta in zip(sims, metas, strict=True):
                meta.setdefault("transcript_id", transcript_id)
                boosted = float(sim) * multiplier
                out.append(_ScoredDoc(boosted, meta, "transcript"))
        out.sort(key=lambda d: d.similarity, reverse=True)
        return out[:PER_SOURCE_K]

    def _gather_commitment_candidates(
        self,
        question_unit_vec: np.ndarray,
        sprint_id: str | None,
        intent: _QueryIntent,
        allowed_transcript_ids: set[str] | None,
    ) -> list[_ScoredDoc]:
        payload = self.commitment_indexer.load()
        if payload is None:
            return []
        vectors, documents = payload
        if allowed_transcript_ids is not None:
            mask = np.array(
                [
                    self._transcript_is_allowed(d.get("transcript_id"), allowed_transcript_ids)
                    for d in documents
                ],
                dtype=bool,
            )
            if not mask.any():
                return []
            vectors = vectors[mask]
            documents = [d for d, keep in zip(documents, mask, strict=True) if keep]
        if sprint_id is not None:
            mask = np.array(
                [d.get("sprint_id") == sprint_id for d in documents], dtype=bool
            )
            if not mask.any():
                return []
            vectors = vectors[mask]
            documents = [d for d, keep in zip(documents, mask, strict=True) if keep]
        sims = vectors @ question_unit_vec
        scored: list[_ScoredDoc] = []
        for sim, doc in zip(sims, documents, strict=True):
            doc_sprint = doc.get("sprint_id")
            # Penalise commitments outside an explicit sprint mention, lift
            # those inside it.
            if sprint_id is None and intent.sprints:
                if doc_sprint in intent.sprints:
                    multiplier = SPRINT_BOOST
                else:
                    multiplier = 0.6
            else:
                multiplier = 1.0
            # Signal boost: if the user asks about a lifecycle signal (e.g.
            # "qué bloqueos siguen abiertos") and the commitment's indexed
            # text mentions that signal, lift it. Lowercase the indexed text
            # once per doc; the marker check is a simple substring test.
            if intent.signals:
                indexed_text = (doc.get("indexed_text") or "").lower()
                for s in intent.signals:
                    marker = _SIGNAL_TO_INDEXED_MARKER.get(s)
                    if marker and marker in indexed_text:
                        multiplier *= SIGNAL_BOOST
                        break
            scored.append(_ScoredDoc(float(sim) * multiplier, doc, "commitment"))
        scored.sort(key=lambda d: d.similarity, reverse=True)
        return scored[:PER_SOURCE_K]

    def _allowed_transcript_ids(self, scope: QAScope) -> set[str] | None:
        if scope == "all":
            return None
        return self.analysis_runs.list_analyzed_transcript_ids()

    @staticmethod
    def _transcript_is_allowed(
        transcript_id: str | None,
        allowed_transcript_ids: set[str] | None,
    ) -> bool:
        if allowed_transcript_ids is None:
            return True
        if transcript_id is None:
            return False
        return transcript_id in allowed_transcript_ids

    def _to_sources(self, scored: Iterable[_ScoredDoc]) -> list[QASource]:
        out: list[QASource] = []
        for i, doc in enumerate(scored, start=1):
            if doc.source_type == "transcript":
                meta = doc.payload
                text = meta.get("text", "")
                if len(text) > CHUNK_TEXT_TRUNCATE:
                    text = text[:CHUNK_TEXT_TRUNCATE].rstrip() + "…"
                speakers = meta.get("speakers", [])
                subtitle_bits: list[str] = []
                if meta.get("meeting_title"):
                    subtitle_bits.append(str(meta["meeting_title"]))
                if speakers:
                    subtitle_bits.append(", ".join(speakers))
                out.append(
                    QASource(
                        index=i,
                        source_type="transcript",
                        sprint_id=meta.get("sprint_id"),
                        title=meta.get("meeting_title") or meta.get("transcript_id") or "Transcripción",
                        subtitle=" · ".join(subtitle_bits),
                        text=text,
                        similarity=doc.similarity,
                        transcript_id=meta.get("transcript_id"),
                        segment_indices=list(meta.get("segment_indices", [])),
                    )
                )
            else:
                meta = doc.payload
                text_bits: list[str] = []
                if meta.get("summary"):
                    text_bits.append(meta["summary"])
                last_event = meta.get("last_event")
                if last_event:
                    text_bits.append(f"Último evento: {last_event}")
                subtitle_bits = []
                if meta.get("state"):
                    subtitle_bits.append(f"estado: {meta['state']}")
                if meta.get("meeting_title"):
                    subtitle_bits.append(f"origen: {meta['meeting_title']}")
                out.append(
                    QASource(
                        index=i,
                        source_type="commitment",
                        sprint_id=meta.get("sprint_id"),
                        title=meta.get("title") or "Compromiso",
                        subtitle=" · ".join(subtitle_bits),
                        text=" — ".join(text_bits) if text_bits else "",
                        similarity=doc.similarity,
                        commitment_id=meta.get("commitment_id"),
                        commitment_state=meta.get("state"),
                    )
                )
        return out

    @staticmethod
    def _build_user_prompt(question: str, sources: list[QASource]) -> str:
        lines = [f"Pregunta: {question}", "", "Contexto disponible:"]
        for s in sources:
            header = f"[{s.index}]"
            tags: list[str] = []
            if s.source_type == "transcript":
                tags.append("Transcripción")
                if s.sprint_id:
                    tags.append(s.sprint_id)
                if s.title:
                    tags.append(s.title)
                if s.subtitle and s.subtitle != s.title:
                    tags.append(s.subtitle)
            else:
                tags.append("Compromiso")
                if s.title:
                    tags.append(f'"{s.title}"')
                if s.commitment_state:
                    tags.append(f"estado: {s.commitment_state}")
                if s.sprint_id:
                    tags.append(s.sprint_id)
            header += " (" + " · ".join(tags) + ")"
            lines.append(header)
            if s.text:
                lines.append(s.text)
            lines.append("")
        lines.append("Responde la pregunta del usuario usando solo este contexto.")
        lines.append("Cita las fuentes que uses con [N].")
        return "\n".join(lines)
