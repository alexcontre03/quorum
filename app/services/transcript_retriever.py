"""Sprint-aware retriever over the transcript index (Decisión 012).

Chunking strategy: sliding window of 3 segments with stride 2 (overlap of 1). Each chunk preserves
the conversational turn around a focal segment, which matters for the kind of reasoning the
`task_followup_agent` does (`scope_change`, `contradicts_decision`, `recurring_unresolved`).

Embedding model is `mxbai-embed-large` by default, configured via `EMBEDDING_MODEL` env var. The
service degrades gracefully: if embedding fails (Ollama down, model not pulled), it returns no
chunks and logs the failure — the followup agent then runs with the structured history alone,
which is the pre-Decisión 012 behavior.
"""

from __future__ import annotations

import logging
from typing import Literal

import numpy as np

from app.agents.exceptions import AgentExecutionError
from app.agents.chat_client import ChatClient
from app.agents.client_factory import get_chat_client, get_embed_client
from app.config.runtime_settings import EmbeddingRuntimeSettings, get_embedding_settings
from app.domain.models import MeetingTranscript, RetrievedChunk
from app.services.retrieval_index import RetrievalIndex
from app.services.transcript_repository import TranscriptRepository


_logger = logging.getLogger(__name__)

RetrievalScope = Literal["current", "all"]

CHUNK_WINDOW = 3
CHUNK_STRIDE = 2
DEFAULT_TOP_K = 5
CHUNK_TEXT_TRUNCATE = 1000  # safety cap for prompt size


class TranscriptRetriever:
    """Construye índices por transcripción y resuelve queries con scoping por sprint."""

    def __init__(
        self,
        index: RetrievalIndex | None = None,
        ollama_client: ChatClient | None = None,
        settings: EmbeddingRuntimeSettings | None = None,
        transcript_repository: TranscriptRepository | None = None,
    ) -> None:
        self.index = index or RetrievalIndex()
        # Pinned client (test/DI override). When None, the embed_client
        # property resolves the active one on every call so a runtime
        # profile switch in the UI takes effect on the next request.
        self._pinned_client = ollama_client
        self.settings = settings or get_embedding_settings()
        self.transcripts = transcript_repository or TranscriptRepository()

    @property
    def ollama(self) -> ChatClient:
        if self._pinned_client is not None:
            return self._pinned_client
        return get_embed_client()

    # ---------- Indexing ----------

    def ensure_indexed(self, transcript: MeetingTranscript) -> bool:
        """Construye el índice del transcript si no existe. Devuelve True si quedó indexado, False si fallo."""
        if not self.settings.enabled:
            return False
        if self.index.has(transcript.id):
            return True
        return self._build_index(transcript)

    def reindex(self, transcript: MeetingTranscript) -> bool:
        """Fuerza la reconstrucción del índice del transcript."""
        self.index.delete(transcript.id)
        return self._build_index(transcript)

    def _build_index(self, transcript: MeetingTranscript) -> bool:
        chunks_meta = self._chunk_segments(transcript)
        if not chunks_meta:
            return False
        vectors: list[list[float]] = []
        for chunk in chunks_meta:
            try:
                vec = self.ollama.embed(
                    base_url=self.settings.base_url,
                    model=self.settings.model,
                    text=chunk["text"],
                )
            except AgentExecutionError as exc:
                _logger.warning(
                    "Embedding failed for transcript %s chunk %s: %s",
                    transcript.id,
                    chunk["chunk_index"],
                    exc,
                )
                return False
            vectors.append(vec)
        matrix = _l2_normalize(np.array(vectors, dtype=np.float32))
        self.index.save(transcript.id, matrix, chunks_meta)
        return True

    def _chunk_segments(self, transcript: MeetingTranscript) -> list[dict]:
        segments = transcript.segments
        if not segments:
            return []
        chunks: list[dict] = []
        chunk_index = 0
        for start in range(0, max(1, len(segments) - 1), CHUNK_STRIDE):
            end = min(start + CHUNK_WINDOW, len(segments))
            window = segments[start:end]
            if not window:
                break
            text = "\n".join(
                f"{s.speaker}: {s.text.strip()}" for s in window
            ).strip()
            if not text:
                continue
            chunks.append(
                {
                    "chunk_index": chunk_index,
                    "segment_indices": list(range(start, end)),
                    "speakers": [s.speaker for s in window],
                    "timestamps": [s.timestamp for s in window if s.timestamp],
                    "text": text,
                    "sprint_id": transcript.sprint_id,
                    "meeting_title": transcript.title,
                    "meeting_date": transcript.meeting_date,
                }
            )
            chunk_index += 1
            if end == len(segments):
                break
        return chunks

    # ---------- Querying ----------

    def retrieve(
        self,
        query: str,
        *,
        current_sprint_id: str | None,
        scope: RetrievalScope = "current",
        exclude_transcript_id: str | None = None,
        top_k: int = DEFAULT_TOP_K,
    ) -> list[RetrievedChunk]:
        """Recupera top-K chunks del historial relevantes al query, filtrados por sprint."""
        if not self.settings.enabled or not query.strip():
            return []
        candidates = self._gather_candidates(
            current_sprint_id=current_sprint_id,
            scope=scope,
            exclude_transcript_id=exclude_transcript_id,
        )
        if not candidates:
            return []
        try:
            query_vec = self.ollama.embed(
                base_url=self.settings.base_url,
                model=self.settings.model,
                text=query,
            )
        except AgentExecutionError as exc:
            _logger.warning("Embedding failed for query: %s", exc)
            return []
        q = _l2_normalize(np.array([query_vec], dtype=np.float32))[0]

        scored: list[tuple[float, dict]] = []
        for vectors, meta_list in candidates:
            sims = vectors @ q
            for sim, meta in zip(sims, meta_list, strict=True):
                scored.append((float(sim), meta))
        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[: max(1, top_k)]
        out: list[RetrievedChunk] = []
        for sim, meta in top:
            text = meta.get("text", "")
            if len(text) > CHUNK_TEXT_TRUNCATE:
                text = text[:CHUNK_TEXT_TRUNCATE].rstrip() + "…"
            out.append(
                RetrievedChunk(
                    transcript_id=self._infer_transcript_id(meta),
                    sprint_id=meta.get("sprint_id"),
                    chunk_index=int(meta.get("chunk_index", 0)),
                    segment_indices=list(meta.get("segment_indices", [])),
                    speakers=list(meta.get("speakers", [])),
                    text=text,
                    similarity=sim,
                )
            )
        return out

    def _gather_candidates(
        self,
        *,
        current_sprint_id: str | None,
        scope: RetrievalScope,
        exclude_transcript_id: str | None,
    ) -> list[tuple[np.ndarray, list[dict]]]:
        out: list[tuple[np.ndarray, list[dict]]] = []
        for transcript_id in self.index.list_indexed_transcripts():
            if exclude_transcript_id and transcript_id == exclude_transcript_id:
                continue
            payload = self.index.load(transcript_id)
            if payload is None:
                continue
            vectors, meta_list = payload
            if scope == "current":
                if current_sprint_id is None:
                    continue
                meta_list_sprint = meta_list[0].get("sprint_id") if meta_list else None
                if meta_list_sprint != current_sprint_id:
                    continue
            # inject transcript_id into each meta entry (it's not stored per-chunk)
            for meta in meta_list:
                meta.setdefault("transcript_id", transcript_id)
            out.append((vectors, meta_list))
        return out

    @staticmethod
    def _infer_transcript_id(meta: dict) -> str:
        return str(meta.get("transcript_id", ""))


def _l2_normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms
