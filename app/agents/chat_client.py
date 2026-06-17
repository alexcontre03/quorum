"""Chat-client abstraction.

The project supports two runtime profiles: a local one backed by an Ollama
runtime, and an api one backed by OpenAI. The orchestrator and the agents
talk to a chat client through this abstract interface, and the concrete
client is resolved at request time by the factory in
``app/agents/client_factory.py`` based on the current runtime profile.

The interface mirrors the original `OllamaChatClient` so callers do not need
to know which backend they are talking to. New backends only need to
implement the three methods declared here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Iterator


class ChatClient(ABC):
    """Abstract chat client. Concrete subclasses provide the transport."""

    @abstractmethod
    def chat(
        self,
        *,
        base_url: str,
        model: str,
        messages: list[dict[str, str]],
        response_format: str | dict[str, Any] = "json",
        temperature: float = 0.1,
        options: dict[str, Any] | None = None,
        timeout: int = 120,
    ) -> dict[str, Any]:
        """Run a chat completion and return ``{"message": {"content": "..."}}``.

        The returned shape matches what `OllamaChatClient.chat` returns so
        existing agents do not need to be rewritten.
        """

    @abstractmethod
    def chat_stream(
        self,
        *,
        base_url: str,
        model: str,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        options: dict[str, Any] | None = None,
        timeout: int = 180,
    ) -> Iterator[str]:
        """Yield text deltas as they arrive. Powers the Q&A streaming view."""

    @abstractmethod
    def embed(
        self,
        *,
        base_url: str,
        model: str,
        text: str,
        timeout: int = 60,
    ) -> list[float]:
        """Return an embedding vector for *text*."""
