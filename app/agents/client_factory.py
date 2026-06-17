"""Factories that resolve `ChatClient` instances based on the runtime
settings.

There are two factories:

- ``get_chat_client()``: returns the client to use for chat calls. Honors
  the active profile and the per-profile model override.
- ``get_embed_client()``: returns the client to use for embeddings. Honors
  the active profile too, but falls back to the local Ollama client when
  the profile does not have a first-party embedding endpoint
  (currently: ``anthropic``).

Each factory delegates the read of the active profile to
``runtime_profile.get_runtime_profile()`` at call time, so a profile change
takes effect on the next chat or embed call without restarting the
backend.
"""

from __future__ import annotations

from app.agents.chat_client import ChatClient


def _make_client(profile: str) -> ChatClient:
    if profile == "openai":
        from app.agents.openai_client import OpenAIChatClient
        client = OpenAIChatClient()
        from app.services.runtime_profile import get_chat_model
        model = get_chat_model("openai")
        if model:
            client.chat_model = model
        return client
    if profile == "anthropic":
        from app.agents.anthropic_client import AnthropicChatClient
        client = AnthropicChatClient()
        from app.services.runtime_profile import get_chat_model
        model = get_chat_model("anthropic")
        if model:
            client.default_model = model
        return client
    from app.agents.ollama_client import OllamaChatClient
    return OllamaChatClient()


def get_chat_client() -> ChatClient:
    """Return the chat client for the active profile."""
    from app.services.runtime_profile import get_runtime_profile
    return _make_client(get_runtime_profile())


def get_embed_client() -> ChatClient:
    """Return the embed client for the active profile, falling back to the
    local Ollama client when the active profile does not expose embeddings."""
    from app.services.runtime_profile import get_runtime_profile
    profile = get_runtime_profile()
    if profile == "anthropic":
        # Anthropic has no first-party embedding endpoint; use the local one.
        from app.agents.ollama_client import OllamaChatClient
        return OllamaChatClient()
    return _make_client(profile)


def get_local_model_override() -> str | None:
    """When the user has chosen to override the per-agent model assignment of
    ``agents.json`` while in the local profile, return that override; else
    None. Used by the orchestrator to substitute the model field before
    handing the catalogue entry to the agent."""
    from app.services.runtime_profile import get_chat_model, get_runtime_profile
    if get_runtime_profile() != "local":
        return None
    return get_chat_model("local")
