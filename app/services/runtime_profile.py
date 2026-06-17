"""Runtime profile and model selection.

Three profiles are supported:

- ``local``: every chat call goes to Ollama (`OllamaChatClient`). When
  ``model_overrides["local"]`` is ``None`` (the default), every agent uses
  the model that ``agents.json`` declares for it (Decision 016 preserved).
  When it is set to a model string, that string overrides the per-agent
  assignment for every chat call. Embeddings always use the local
  ``embeddinggemma:latest`` model.

- ``openai``: every chat call goes to OpenAI. The active model is read from
  ``model_overrides["openai"]`` (default ``gpt-4o-mini``). Embeddings use
  OpenAI's ``text-embedding-3-small``.

- ``anthropic``: every chat call goes to Anthropic. The active model is
  read from ``model_overrides["anthropic"]`` (default
  ``claude-3-5-sonnet-20241022``). Anthropic has no first-party embedding
  endpoint, so embeddings fall back to Ollama ``embeddinggemma:latest``;
  the asymmetry is documented and visible to the user.

The settings are persisted to ``app/data/settings/runtime_settings.json``.
A small in-memory cache avoids re-reading the file on every chat call; the
cache is invalidated whenever the file is written.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Literal, Optional

RuntimeProfile = Literal["local", "openai", "anthropic"]
ALLOWED_PROFILES: tuple[RuntimeProfile, ...] = ("local", "openai", "anthropic")
DEFAULT_PROFILE: RuntimeProfile = "local"

# Catalogue of known models for the UI dropdown. The factory does not enforce
# this list (the user can put any string), but the UI uses it to render the
# common options.
KNOWN_MODELS: dict[RuntimeProfile, list[str]] = {
    "local": [
        "qwen2.5:7b",
        "gemma3:4b",
        "qwen2.5:3b",
        "qwen2.5:14b",
        "llama3.1:8b",
    ],
    # Only models that support Structured Outputs (response_format with
    # type=json_schema and strict=true) belong here. The pipeline relies on
    # strict schema enforcement, so listing a model that does not accept it
    # would surface as a 400 on the next "Analizar reunión". gpt-4-turbo, for
    # instance, only supports json_object and was removed for that reason.
    "openai": [
        "gpt-4o-mini",
        "gpt-4o",
        "gpt-4.1-mini",
        "gpt-4.1",
    ],
    "anthropic": [
        "claude-3-5-sonnet-20241022",
        "claude-3-5-haiku-20241022",
        "claude-3-opus-20240229",
    ],
}

# Default model when ``model_overrides[profile]`` is None and the profile
# requires a single model (openai, anthropic). For ``local`` the default is
# None because every agent has its own model assignment in ``agents.json``.
DEFAULT_MODELS: dict[RuntimeProfile, Optional[str]] = {
    "local": None,
    "openai": "gpt-4o-mini",
    "anthropic": "claude-3-5-sonnet-20241022",
}

_SETTINGS_DIR = Path(__file__).resolve().parents[1] / "data" / "settings"
_SETTINGS_FILE = _SETTINGS_DIR / "runtime_settings.json"
_LEGACY_FILE = _SETTINGS_DIR / "runtime_profile.json"

_lock = threading.Lock()
_cache: dict[str, object] = {}


def _empty_overrides() -> dict[str, Optional[str]]:
    return {p: None for p in ALLOWED_PROFILES}


def _read_disk() -> dict[str, object]:
    """Read the settings file, migrating the legacy ``runtime_profile.json``
    format that only contained ``{"profile": ...}`` to the new shape."""
    if _SETTINGS_FILE.exists():
        try:
            data = json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    elif _LEGACY_FILE.exists():
        try:
            legacy = json.loads(_LEGACY_FILE.read_text(encoding="utf-8"))
            data = {"profile": legacy.get("profile")}
        except (json.JSONDecodeError, OSError):
            data = {}
    else:
        data = {}

    profile = data.get("profile")
    if profile not in ALLOWED_PROFILES:
        # Older files used "api" for what is now "openai"; preserve user intent.
        if profile == "api":
            profile = "openai"
        else:
            profile = DEFAULT_PROFILE
    raw_overrides = data.get("model_overrides") or {}
    overrides = _empty_overrides()
    for p in ALLOWED_PROFILES:
        value = raw_overrides.get(p)
        if isinstance(value, str) and value.strip():
            overrides[p] = value.strip()
    return {"profile": profile, "model_overrides": overrides}


def _write_disk(state: dict[str, object]) -> None:
    _SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    _SETTINGS_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _load() -> dict[str, object]:
    cached = _cache.get("state")
    if cached is not None:
        return cached  # type: ignore[return-value]
    state = _read_disk()
    _cache["state"] = state
    return state


def get_runtime_profile() -> RuntimeProfile:
    """Return the active runtime profile."""
    return _load()["profile"]  # type: ignore[return-value]


def get_chat_model(profile: Optional[RuntimeProfile] = None) -> Optional[str]:
    """Return the currently selected chat model for *profile* (or the active
    one when *profile* is None). ``None`` means "use the per-agent assignment
    of agents.json", which is only meaningful for the ``local`` profile."""
    state = _load()
    target: RuntimeProfile = profile or state["profile"]  # type: ignore[assignment]
    overrides: dict[str, Optional[str]] = state["model_overrides"]  # type: ignore[assignment]
    value = overrides.get(target)
    if value is not None:
        return value
    return DEFAULT_MODELS.get(target)


def _embed_dim_for_profile(profile: str) -> str:
    """Marker stored alongside retrieval indices so a profile change can be
    detected and the indices invalidated. Uses the embed family name rather
    than the exact dim so a future model swap inside the same family does
    not invalidate the index unnecessarily."""
    if profile == "openai":
        return "openai-text-embedding-3-small"
    if profile == "anthropic":
        # Anthropic has no native embeddings; falls back to Ollama.
        return "ollama-embeddinggemma"
    return "ollama-embeddinggemma"


def _invalidate_retrieval_index_if_dim_changed(new_profile: str, old_profile: str) -> None:
    """When the embedding family changes (Ollama ↔ OpenAI), the persisted
    vectors are no longer compatible with the active embed client. Wipe the
    ``.npz`` and ``.json`` shards under ``app/data/retrieval_index`` so the
    next analysis or QA rebuilds them with the new client. Only ~9 files on
    the dataset, so the rebuild takes seconds.

    Safe to call repeatedly: if the family did not change, no files are
    removed.
    """
    if _embed_dim_for_profile(new_profile) == _embed_dim_for_profile(old_profile):
        return
    index_dir = Path(__file__).resolve().parents[1] / "data" / "retrieval_index"
    if not index_dir.exists():
        return
    for path in index_dir.iterdir():
        if path.suffix in {".npz", ".json"}:
            try:
                path.unlink()
            except OSError:
                pass


def set_runtime_profile(profile: str) -> RuntimeProfile:
    if profile not in ALLOWED_PROFILES:
        raise ValueError(
            f"Invalid runtime profile: {profile!r}. "
            f"Allowed: {', '.join(ALLOWED_PROFILES)}"
        )
    with _lock:
        state = dict(_load())
        old_profile = str(state.get("profile", DEFAULT_PROFILE))
        state["profile"] = profile
        _write_disk(state)
        _cache["state"] = state
        # Drop incompatible retrieval indices outside the lock-protected
        # critical section to avoid holding the lock across disk I/O.
    _invalidate_retrieval_index_if_dim_changed(profile, old_profile)
    return profile  # type: ignore[return-value]


def set_chat_model(profile: str, model: Optional[str]) -> Optional[str]:
    """Set the chat model override for *profile*. Pass ``None`` to clear the
    override and fall back to the default (which, for ``local``, means
    "respect agents.json per-agent assignment")."""
    if profile not in ALLOWED_PROFILES:
        raise ValueError(
            f"Invalid runtime profile: {profile!r}. "
            f"Allowed: {', '.join(ALLOWED_PROFILES)}"
        )
    cleaned: Optional[str]
    if model is None:
        cleaned = None
    else:
        if not isinstance(model, str):
            raise ValueError("model must be a string or null")
        stripped = model.strip()
        cleaned = stripped or None
    with _lock:
        state = dict(_load())
        overrides = dict(state.get("model_overrides") or _empty_overrides())
        overrides[profile] = cleaned
        state["model_overrides"] = overrides
        _write_disk(state)
        _cache["state"] = state
    return cleaned


def get_settings_snapshot() -> dict[str, object]:
    """Snapshot for the UI: active profile, current overrides, defaults and
    the catalogue of known models."""
    state = _load()
    return {
        "profile": state["profile"],
        "model_overrides": state["model_overrides"],
        "allowed_profiles": list(ALLOWED_PROFILES),
        "default_profile": DEFAULT_PROFILE,
        "default_models": dict(DEFAULT_MODELS),
        "known_models": {p: list(v) for p, v in KNOWN_MODELS.items()},
    }


def reset_cache() -> None:
    """Force the next call to re-read from disk. Test-only helper."""
    _cache.clear()
