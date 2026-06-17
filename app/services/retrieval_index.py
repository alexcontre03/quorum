"""Per-transcript vector store for the RAG layer (Decisión 012).

Each transcript gets its own index:
- `app/data/retrieval_index/<transcript_id>.npz` — matrix of embeddings shape (n_chunks, dim)
- `app/data/retrieval_index/<transcript_id>.json` — list of chunk metadata aligned 1-to-1 with rows

Indexing is idempotent by transcript_id: re-indexing overwrites both files. The dataset is small
(~50 chunks per transcript, ~150 in total) so cosine similarity over the full matrix is fast enough
in pure numpy without a vector database.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np


class RetrievalIndex:
    """Persistencia simple de un índice vectorial por transcripción."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or Path(__file__).resolve().parents[1] / "data" / "retrieval_index"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save(
        self,
        transcript_id: str,
        vectors: np.ndarray,
        metadata: list[dict],
    ) -> None:
        """Persiste el índice del transcript. Sobrescribe si ya existe (idempotente)."""
        if vectors.shape[0] != len(metadata):
            raise ValueError(
                f"vectors rows ({vectors.shape[0]}) does not match metadata length ({len(metadata)})"
            )
        np.savez_compressed(self._vectors_path(transcript_id), embeddings=vectors)
        self._metadata_path(transcript_id).write_text(
            json.dumps({"transcript_id": transcript_id, "chunks": metadata}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load(self, transcript_id: str) -> tuple[np.ndarray, list[dict]] | None:
        """Carga el índice. Devuelve None si no existe."""
        vp = self._vectors_path(transcript_id)
        mp = self._metadata_path(transcript_id)
        if not vp.exists() or not mp.exists():
            return None
        with np.load(vp) as data:
            vectors = data["embeddings"]
        meta = json.loads(mp.read_text(encoding="utf-8"))
        chunks = meta.get("chunks", []) if isinstance(meta, dict) else []
        if vectors.shape[0] != len(chunks):
            return None
        return vectors, chunks

    def has(self, transcript_id: str) -> bool:
        return self._vectors_path(transcript_id).exists() and self._metadata_path(transcript_id).exists()

    def delete(self, transcript_id: str) -> None:
        for path in (self._vectors_path(transcript_id), self._metadata_path(transcript_id)):
            if path.exists():
                path.unlink()

    def list_indexed_transcripts(self) -> list[str]:
        return sorted(p.stem for p in self.base_dir.glob("*.json"))

    def _vectors_path(self, transcript_id: str) -> Path:
        return self.base_dir / f"{transcript_id}.npz"

    def _metadata_path(self, transcript_id: str) -> Path:
        return self.base_dir / f"{transcript_id}.json"
