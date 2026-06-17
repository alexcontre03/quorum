"""Anthropic Claude implementation of `ChatClient`.

Used when the runtime profile is ``anthropic``. Calls Anthropic's
``/v1/messages`` endpoint. Structured-output enforcement is implemented as
a single ``tool_use`` declaration: when the caller passes a JSON Schema as
``response_format``, the client declares a tool whose input matches the
schema and forces Claude to call it. The result is then unwrapped so the
return shape matches the other clients (``{"message": {"content": "..."}}``
where the content is the JSON string of the tool input).

Anthropic does not expose a first-party embedding endpoint, so ``embed`` is
not implemented here. The client factory routes embedding calls through the
local Ollama client when the active profile is ``anthropic``. The
asymmetry is intentional and documented.

Configuration via environment:

- ``ANTHROPIC_API_KEY``: required for the profile to work.
- ``ANTHROPIC_CHAT_MODEL`` (default ``claude-3-5-sonnet-20241022``):
  fallback model when the caller does not pass an explicit model. The
  ``runtime_profile`` setting normally provides the model already.
- ``ANTHROPIC_VERSION`` (default ``2023-06-01``).
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Iterator
from urllib import error, request

from app.agents.chat_client import ChatClient
from app.agents.exceptions import AgentExecutionError


ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_CHAT_MODEL = "claude-3-5-sonnet-20241022"
DEFAULT_API_VERSION = "2023-06-01"
MAX_RETRIES = 4
DEFAULT_MAX_TOKENS = 4096


class AnthropicChatClient(ChatClient):
    def __init__(self) -> None:
        self.api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        self.default_model = os.getenv("ANTHROPIC_CHAT_MODEL", DEFAULT_CHAT_MODEL)
        self.api_version = os.getenv("ANTHROPIC_VERSION", DEFAULT_API_VERSION)
        self._missing_key_reason = (
            ""
            if self.api_key
            else (
                "ANTHROPIC_API_KEY is not set in the environment. "
                "Switch the runtime profile back to 'local' or configure the key."
            )
        )

    def _headers(self) -> dict[str, str]:
        if self._missing_key_reason:
            raise AgentExecutionError(self._missing_key_reason)
        return {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": self.api_version,
        }

    @staticmethod
    def _split_messages(messages: list[dict[str, str]]) -> tuple[str, list[dict[str, str]]]:
        """Anthropic's messages API expects ``system`` as a top-level field,
        not as a message. Pull it out and pass the remaining user/assistant
        messages through unchanged."""
        system_parts: list[str] = []
        non_system: list[dict[str, str]] = []
        for m in messages:
            if m.get("role") == "system":
                content = m.get("content", "")
                if content:
                    system_parts.append(content)
            else:
                non_system.append(m)
        return "\n\n".join(system_parts), non_system

    def _post_json(self, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8")
        last_exc: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            req = request.Request(
                url=ANTHROPIC_API_URL, data=data, headers=self._headers(), method="POST",
            )
            try:
                with request.urlopen(req, timeout=timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except error.HTTPError as exc:
                err_body = exc.read().decode("utf-8", errors="ignore")
                if exc.code == 429 or 500 <= exc.code < 600:
                    last_exc = AgentExecutionError(
                        f"Anthropic HTTP {exc.code} (attempt {attempt}): {err_body[:200]}"
                    )
                    time.sleep(2 ** attempt)
                    continue
                raise AgentExecutionError(
                    f"Anthropic HTTP {exc.code}: {err_body[:500]}"
                ) from exc
            except (error.URLError, TimeoutError, OSError) as exc:
                last_exc = AgentExecutionError(
                    f"Anthropic transport error (attempt {attempt}): {exc}"
                )
                time.sleep(2 ** attempt)
                continue
        raise last_exc or AgentExecutionError("Anthropic: retries exhausted")

    def chat(
        self,
        *,
        base_url: str,  # noqa: ARG002 (kept for interface parity)
        model: str,
        messages: list[dict[str, str]],
        response_format: str | dict[str, Any] = "json",
        temperature: float = 0.1,
        options: dict[str, Any] | None = None,
        timeout: int = 240,
    ) -> dict[str, Any]:
        system, dialog = self._split_messages(messages)
        active_model = model or self.default_model
        max_tokens = int((options or {}).get("max_tokens", DEFAULT_MAX_TOKENS))

        if isinstance(response_format, dict):
            # Force the model to produce a tool call whose input matches the
            # provided JSON schema. The unwrap below converts the tool input
            # back into the JSON string expected by the rest of the system.
            payload: dict[str, Any] = {
                "model": active_model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system": system or "You are a helpful assistant.",
                "messages": dialog,
                "tools": [
                    {
                        "name": "respond_in_schema",
                        "description": "Return the requested JSON object.",
                        "input_schema": response_format,
                    }
                ],
                "tool_choice": {"type": "tool", "name": "respond_in_schema"},
            }
            body = self._post_json(payload, timeout)
            for block in body.get("content", []):
                if block.get("type") == "tool_use":
                    obj = block.get("input", {})
                    return {
                        "message": {"content": json.dumps(obj, ensure_ascii=False)},
                        "_usage": body.get("usage", {}),
                    }
            raise AgentExecutionError(
                f"Anthropic response did not contain a tool_use block: {body}"
            )

        payload = {
            "model": active_model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system or "You are a helpful assistant.",
            "messages": dialog,
        }
        body = self._post_json(payload, timeout)
        text_parts = [b.get("text", "") for b in body.get("content", []) if b.get("type") == "text"]
        return {
            "message": {"content": "".join(text_parts)},
            "_usage": body.get("usage", {}),
        }

    def chat_stream(
        self,
        *,
        base_url: str,  # noqa: ARG002
        model: str,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        options: dict[str, Any] | None = None,
        timeout: int = 180,
    ) -> Iterator[str]:
        system, dialog = self._split_messages(messages)
        active_model = model or self.default_model
        max_tokens = int((options or {}).get("max_tokens", DEFAULT_MAX_TOKENS))
        payload = {
            "model": active_model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
            "system": system or "You are a helpful assistant.",
            "messages": dialog,
        }
        data = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url=ANTHROPIC_API_URL, data=data, headers=self._headers(), method="POST",
        )
        try:
            response = request.urlopen(req, timeout=timeout)
        except error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="ignore")
            raise AgentExecutionError(
                f"Anthropic HTTP {exc.code}: {err_body[:500]}"
            ) from exc
        except error.URLError as exc:
            raise AgentExecutionError(f"Could not reach Anthropic: {exc.reason}") from exc

        try:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line or not line.startswith("data:"):
                    continue
                chunk = line[len("data:"):].strip()
                if not chunk:
                    continue
                try:
                    event = json.loads(chunk)
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "content_block_delta":
                    delta = event.get("delta", {})
                    if delta.get("type") == "text_delta":
                        text = delta.get("text", "")
                        if text:
                            yield text
                elif event.get("type") == "message_stop":
                    break
        finally:
            response.close()

    def embed(
        self,
        *,
        base_url: str,
        model: str,
        text: str,
        timeout: int = 60,
    ) -> list[float]:
        raise AgentExecutionError(
            "Anthropic does not expose a first-party embedding endpoint. "
            "Embeddings fall back to the local Ollama client; this method "
            "should not be reached when the client factory is in use."
        )
