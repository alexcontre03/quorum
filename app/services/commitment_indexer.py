"""Índice vectorial de compromisos para Q&A (Decisión 013).

Mantiene un único fichero `_commitments.npz` + `_commitments.json` en `app/data/retrieval_index/`
con un documento por compromiso. El documento se construye a partir del `title`, `summary`,
estado del ciclo de vida, reunión de origen y resumen del último evento del timeline. La idea es
que el embedding capture tanto el tema del compromiso como su estado actual, para que preguntas
del tipo "¿está cerrado X?" o "¿en qué reunión nació Y?" encuentren la fuente correcta.

El índice se reconstruye perezosamente: en cada llamada al `QAService`, si algún fichero de
compromiso es más reciente que el índice, se rebuilds completo. Para el tamaño del dataset
(decenas de compromisos) el coste es trivial.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from app.agents.exceptions import AgentExecutionError
from app.agents.chat_client import ChatClient
from app.agents.client_factory import get_chat_client, get_embed_client
from app.config.runtime_settings import EmbeddingRuntimeSettings, get_embedding_settings
from app.domain.models import Commitment
from app.services.commitment_repository import CommitmentRepository


_INDEX_NAME = "_commitments"
# Bump cuando el formato del texto indexado cambie. Un mismatch invalida
# el indice completo aunque los compromisos no se hayan tocado.
_INDEXER_VERSION = 3


class CommitmentIndexer:
    def __init__(
        self,
        repository: CommitmentRepository | None = None,
        ollama_client: ChatClient | None = None,
        settings: EmbeddingRuntimeSettings | None = None,
        index_dir: Path | None = None,
    ) -> None:
        self.repository = repository or CommitmentRepository()
        self._pinned_client = ollama_client
        self.settings = settings or get_embedding_settings()
        self.index_dir = index_dir or (
            Path(__file__).resolve().parents[1] / "data" / "retrieval_index"
        )
        self.index_dir.mkdir(parents=True, exist_ok=True)

    @property
    def ollama(self) -> ChatClient:
        if self._pinned_client is not None:
            return self._pinned_client
        return get_embed_client()

    def refresh_if_stale(self) -> bool:
        """Reconstruye el índice si algún compromiso es más reciente que el índice persistido."""
        if not self.settings.enabled:
            return False
        if self._is_stale():
            return self._rebuild()
        return True

    def load(self) -> tuple[np.ndarray, list[dict]] | None:
        vp = self._vectors_path()
        mp = self._metadata_path()
        if not vp.exists() or not mp.exists():
            return None
        with np.load(vp) as data:
            vectors = data["embeddings"]
        meta = json.loads(mp.read_text(encoding="utf-8"))
        documents = meta.get("documents", []) if isinstance(meta, dict) else []
        if vectors.shape[0] != len(documents):
            return None
        return vectors, documents

    def _is_stale(self) -> bool:
        commitments_dir = self.repository.base_dir
        if not commitments_dir.exists():
            return False
        commitments = list(commitments_dir.glob("*.json"))
        if not commitments:
            return self._vectors_path().exists() or self._metadata_path().exists()
        if not self._vectors_path().exists() or not self._metadata_path().exists():
            return True
        index_mtime = max(self._vectors_path().stat().st_mtime, self._metadata_path().stat().st_mtime)
        latest_commitment_mtime = max(p.stat().st_mtime for p in commitments)
        if latest_commitment_mtime > index_mtime:
            return True
        meta = json.loads(self._metadata_path().read_text(encoding="utf-8"))
        # Mismatch en version del indexer: cambio el formato del texto y hay
        # que reembed. La comparacion por presencia tolera indices viejos sin
        # campo de version (los tratamos como version 1).
        if meta.get("indexer_version", 1) != _INDEXER_VERSION:
            return True
        return len(meta.get("documents", [])) != len(commitments)

    def _rebuild(self) -> bool:
        commitments = self.repository.list_all()
        if not commitments:
            self._delete()
            return True
        documents: list[dict] = []
        vectors: list[list[float]] = []
        for commitment in commitments:
            text = self._format_document(commitment)
            try:
                vec = self.ollama.embed(
                    base_url=self.settings.base_url,
                    model=self.settings.model,
                    text=text,
                )
            except AgentExecutionError:
                return False
            documents.append(
                {
                    "commitment_id": commitment.commitment_id,
                    "transcript_id": commitment.origin.transcript_id,
                    "sprint_id": commitment.origin.sprint_id,
                    "title": commitment.title,
                    "summary": commitment.summary,
                    "state": commitment.state,
                    "meeting_title": commitment.origin.meeting_title,
                    "meeting_date": commitment.origin.meeting_date,
                    "speaker": commitment.origin.speaker,
                    "last_event": self._last_event_text(commitment),
                    "indexed_text": text,
                }
            )
            vectors.append(vec)
        matrix = _l2_normalize(np.array(vectors, dtype=np.float32))
        np.savez_compressed(self._vectors_path(), embeddings=matrix)
        self._metadata_path().write_text(
            json.dumps(
                {"documents": documents, "indexer_version": _INDEXER_VERSION},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return True

    def _delete(self) -> None:
        for path in (self._vectors_path(), self._metadata_path()):
            if path.exists():
                path.unlink()

    @staticmethod
    def _format_document(commitment: Commitment) -> str:
        parts = [
            f"Compromiso: {commitment.title}.",
            f"Resumen: {commitment.summary}.",
            f"Estado actual: {commitment.state}.",
            f"Detectado en: {commitment.origin.meeting_title}",
        ]
        if commitment.origin.meeting_date:
            parts.append(f"({commitment.origin.meeting_date})")
        parts.append(f"por {commitment.origin.speaker}.")
        signals = CommitmentIndexer._active_signals(commitment)
        if signals:
            parts.append(f"Señales actuales: {'; '.join(signals)}.")
        last = CommitmentIndexer._last_event_text(commitment)
        if last:
            parts.append(f"Último evento: {last}")
        return " ".join(parts)

    @staticmethod
    def _active_signals(commitment: Commitment) -> list[str]:
        """Resume las señales activas del compromiso en lenguaje natural para
        que el embedding las capture. Sin esto, una pregunta como "qué
        bloqueos siguen abiertos" no encuentra el compromiso porque ni la
        palabra "bloqueo" ni "duplicado" aparecen en el título o resumen,
        solo viven implícitas en el `followup_type` de la timeline.
        """
        if not commitment.timeline:
            return []
        signals: list[str] = []
        blocker_open = False
        duplicate_dismissed = False
        seen_scope_change = False
        seen_recurring = False
        seen_contradiction = False
        seen_duplicate = False
        last_blocker_quote = ""
        # Recorremos en orden inverso para detectar el estado MAS reciente
        # de cada eje (blocker resuelto > blocker abierto, dismissed > flag).
        for ev in reversed(commitment.timeline):
            if ev.event_type == "duplicate_dismissed":
                duplicate_dismissed = True
                continue
            ftype = ev.followup_type
            if ftype == "new_blocker" and not blocker_open:
                blocker_open = True
                last_blocker_quote = ev.trigger_quote or ev.detail
            elif ftype == "blocker_resolved":
                # Si el evento mas reciente sobre bloqueos fue resolver,
                # el bloqueo ya no esta vivo. Marcamos para no degradar.
                blocker_open = False
                break_blocker = True  # noqa
            elif ftype == "scope_change":
                seen_scope_change = True
            elif ftype == "recurring_unresolved":
                seen_recurring = True
            elif ftype == "contradicts_decision":
                seen_contradiction = True
            elif ftype == "possible_duplicate":
                seen_duplicate = True
        if blocker_open:
            txt = "Bloqueado, esperando desbloqueo"
            if last_blocker_quote:
                txt += f' ("{last_blocker_quote[:140]}")'
            signals.append(txt)
        if seen_scope_change:
            signals.append("Ha sufrido cambio de alcance")
        if seen_recurring:
            signals.append("Reaparece sin cerrarse (recurring unresolved)")
        if seen_contradiction:
            signals.append("Contradice una decisión anterior")
        if seen_duplicate and not duplicate_dismissed:
            signals.append("Marcado como posible duplicado")
        if commitment.state == "closed":
            signals.append("Cerrado, ya hecho")
        if commitment.state == "evidenced":
            signals.append("Hay código que lo respalda")
        if commitment.state == "in_code_review":
            signals.append("Pull request abierto en revisión")
        return signals

    @staticmethod
    def _last_event_text(commitment: Commitment) -> str:
        if not commitment.timeline:
            return ""
        last = commitment.timeline[-1]
        bits = [last.event_type]
        if last.followup_type:
            bits.append(f"(tipo: {last.followup_type})")
        if last.meeting_title:
            bits.append(f"en {last.meeting_title}")
        if last.detail:
            bits.append(f"— {last.detail}")
        return " ".join(bits)

    def _vectors_path(self) -> Path:
        return self.index_dir / f"{_INDEX_NAME}.npz"

    def _metadata_path(self) -> Path:
        return self.index_dir / f"{_INDEX_NAME}.json"


def _l2_normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms
