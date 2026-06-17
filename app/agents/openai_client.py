"""OpenAI-backed implementation of `ChatClient`.

Used when the runtime profile is set to ``api`` (see
``app/services/runtime_profile.py``). Talks to two OpenAI endpoints:

- POST https://api.openai.com/v1/chat/completions for chat and chat_stream.
- POST https://api.openai.com/v1/embeddings           for embed.

The chat agent's response schema is forwarded through the
``response_format`` parameter with ``strict: True`` so OpenAI enforces the
JSON shape before returning. The chat() method returns the same
``{"message": {"content": "..."}}`` envelope that `OllamaChatClient.chat`
returns, so existing agents do not need to know which backend produced the
response.

Configuration is read from the environment:

- ``OPENAI_API_KEY``: required.
- ``OPENAI_CHAT_MODEL`` (default ``gpt-4o-mini``): model used for chat and
  chat_stream. The ``model`` parameter passed by the caller is ignored when
  the runtime profile is ``api``, because the agents.json mapping (Decision
  016) describes local models that do not exist on the OpenAI side.
- ``OPENAI_EMBED_MODEL`` (default ``text-embedding-3-small``): model used
  for embeddings.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Iterator
from urllib import error, request

from app.agents.chat_client import ChatClient
from app.agents.exceptions import AgentExecutionError


OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_EMBED_URL = "https://api.openai.com/v1/embeddings"
DEFAULT_CHAT_MODEL = "gpt-4o-mini"
DEFAULT_EMBED_MODEL = "text-embedding-3-small"
MAX_RETRIES = 4


class OpenAIChatClient(ChatClient):
    """Concrete `ChatClient` backed by OpenAI's HTTP API."""

    def __init__(self) -> None:
        self.api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.chat_model = os.getenv("OPENAI_CHAT_MODEL", DEFAULT_CHAT_MODEL)
        self.embed_model = os.getenv("OPENAI_EMBED_MODEL", DEFAULT_EMBED_MODEL)
        if not self.api_key:
            # We do not raise on construction so the client can be instantiated
            # eagerly in factories; the error fires only when a real call is
            # made.
            self._missing_key_reason = (
                "OPENAI_API_KEY is not set in the environment. "
                "Switch the runtime profile back to 'local' or configure the key."
            )
        else:
            self._missing_key_reason = ""

    def _headers(self) -> dict[str, str]:
        if self._missing_key_reason:
            raise AgentExecutionError(self._missing_key_reason)
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    def _post_json(self, url: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
        """POST with retries on 429/5xx/transport errors."""
        data = json.dumps(payload).encode("utf-8")
        last_exc: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            req = request.Request(
                url=url, data=data, headers=self._headers(), method="POST",
            )
            try:
                with request.urlopen(req, timeout=timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except error.HTTPError as exc:
                err_body = exc.read().decode("utf-8", errors="ignore")
                if exc.code == 429 or 500 <= exc.code < 600:
                    last_exc = AgentExecutionError(
                        f"OpenAI HTTP {exc.code} (attempt {attempt}): {err_body[:200]}"
                    )
                    time.sleep(2 ** attempt)
                    continue
                raise AgentExecutionError(
                    f"OpenAI HTTP {exc.code}: {err_body[:500]}"
                ) from exc
            except (error.URLError, TimeoutError, OSError) as exc:
                last_exc = AgentExecutionError(
                    f"OpenAI transport error (attempt {attempt}): {exc}"
                )
                time.sleep(2 ** attempt)
                continue
        raise last_exc or AgentExecutionError("OpenAI: retries exhausted")

    def chat(
        self,
        *,
        base_url: str,  # noqa: ARG002 (kept for interface parity with Ollama)
        model: str,     # noqa: ARG002 (overridden by OPENAI_CHAT_MODEL)
        messages: list[dict[str, str]],
        response_format: str | dict[str, Any] = "json",
        temperature: float = 0.1,
        options: dict[str, Any] | None = None,  # noqa: ARG002
        timeout: int = 240,
    ) -> dict[str, Any]:
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
            "model": self.chat_model,
            "messages": messages,
            "temperature": temperature,
            "response_format": api_response_format,
        }
        try:
            body = self._post_json(OPENAI_CHAT_URL, payload, timeout)
        except AgentExecutionError as exc:
            # Not every chat model accepts strict json_schema (gpt-4-turbo,
            # older 3.5 variants, fine-tunes...). When the API rejects the
            # response_format with a 400, retry once with the broader
            # json_object mode so the agent still gets a JSON envelope back.
            message = str(exc)
            looks_like_unsupported = (
                "HTTP 400" in message
                and (
                    "response_format" in message
                    or "json_schema" in message
                    or "structured outputs" in message.lower()
                )
            )
            if not looks_like_unsupported or not isinstance(api_response_format, dict):
                raise
            payload["response_format"] = {"type": "json_object"}
            body = self._post_json(OPENAI_CHAT_URL, payload, timeout)
        choices = body.get("choices") or []
        if not choices:
            raise AgentExecutionError(f"OpenAI response without choices: {body}")
        content = choices[0].get("message", {}).get("content", "")
        return {
            "message": {"content": content},
            "_usage": body.get("usage", {}),
        }

    def chat_stream(
        self,
        *,
        base_url: str,  # noqa: ARG002
        model: str,     # noqa: ARG002
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        options: dict[str, Any] | None = None,  # noqa: ARG002
        timeout: int = 180,
    ) -> Iterator[str]:
        payload = {
            "model": self.chat_model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
            "max_tokens": 2500,
        }
        data = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url=OPENAI_CHAT_URL, data=data, headers=self._headers(), method="POST",
        )
        try:
            response = request.urlopen(req, timeout=timeout)
        except error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="ignore")
            raise AgentExecutionError(
                f"OpenAI HTTP {exc.code}: {err_body[:500]}"
            ) from exc
        except error.URLError as exc:
            raise AgentExecutionError(f"Could not reach OpenAI: {exc.reason}") from exc

        try:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line or not line.startswith("data:"):
                    continue
                chunk = line[len("data:"):].strip()
                if chunk == "[DONE]":
                    break
                try:
                    event = json.loads(chunk)
                except json.JSONDecodeError:
                    continue
                delta = (event.get("choices") or [{}])[0].get("delta", {}).get("content", "")
                if delta:
                    yield delta
        finally:
            response.close()

    def embed(
        self,
        *,
        base_url: str,  # noqa: ARG002
        model: str,     # noqa: ARG002 (overridden by OPENAI_EMBED_MODEL)
        text: str,
        timeout: int = 60,
    ) -> list[float]:
        payload = {"model": self.embed_model, "input": text}
        body = self._post_json(OPENAI_EMBED_URL, payload, timeout)
        data = body.get("data") or []
        if not data:
            raise AgentExecutionError(f"OpenAI embed response without data: {body}")
        vector = data[0].get("embedding")
        if not isinstance(vector, list) or not vector:
            raise AgentExecutionError(f"OpenAI embed response missing 'embedding': {body}")
        return [float(v) for v in vector]
