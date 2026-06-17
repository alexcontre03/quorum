"""
Embedding-based matching protocol for the follow-up evaluation.

The default matcher in :class:`FollowupEvaluationService` compares the
``matched_history_title`` of each predicted and expected follow-up using
character-level similarity (`difflib.SequenceMatcher`). That protocol breaks
in two scenarios that we observed empirically with ``qwen2.5:7b``:

1. The model translates the Spanish history title into English in
   ``matched_history_title`` (e.g. "Review secondary provider" instead of
   "Revisar proveedor secundario"), even though the system prompt explicitly
   instructs it to copy literally.
2. The model paraphrases ("Revisar al proveedor secundario de pagos" instead
   of "Revisar si conviene trabajar con un proveedor de pagos secundario").

Both cases lower the string-level similarity well below the 0.75 threshold
and produce no match, which inflates the unmatched_count and brings recall
to zero.

The embedding-based matcher in this module sidesteps both failure modes by
embedding the two titles with ``embeddinggemma:latest`` and matching them
by cosine similarity. The cross-lingual capability of the embedding model
captures the equivalence "Review secondary provider" ≈ "Revisar proveedor
secundario" with a cosine similarity above 0.7.
"""

from __future__ import annotations

import math
from typing import Sequence

from app.agents.ollama_client import OllamaChatClient
from app.config.runtime_settings import get_embedding_settings


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if not norm_a or not norm_b:
        return 0.0
    return dot / (norm_a * norm_b)


class EmbeddingTitleMatcher:
    """Match titles by cosine similarity over their embeddings.

    The matcher caches embeddings by raw text so repeated titles inside a
    single evaluation run cost a single embedding call.
    """

    def __init__(
        self,
        *,
        client: OllamaChatClient | None = None,
        base_url: str | None = None,
        model: str | None = None,
        threshold: float = 0.70,
    ) -> None:
        settings = get_embedding_settings()
        self._client = client or OllamaChatClient()
        self._base_url = base_url or settings.base_url
        self._model = model or settings.model
        self.threshold = threshold
        self._cache: dict[str, list[float]] = {}

    def similarity(self, a: str, b: str) -> float:
        if not a or not b:
            return 0.0
        va = self._embed(a)
        vb = self._embed(b)
        return _cosine(va, vb)

    def _embed(self, text: str) -> list[float]:
        text = text.strip()
        if text in self._cache:
            return self._cache[text]
        vector = self._client.embed(
            base_url=self._base_url, model=self._model, text=text
        )
        self._cache[text] = vector
        return vector
