import json
from typing import Any
from urllib import error, request

from app.agents.chat_client import ChatClient
from app.agents.exceptions import AgentExecutionError


class OllamaChatClient(ChatClient):
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
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "format": response_format,
            "options": {
                "temperature": temperature,
                **(options or {}),
            },
        }

        data = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url=f"{base_url.rstrip('/')}/chat",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise AgentExecutionError(f"Ollama HTTP error {exc.code}: {body}") from exc
        except error.URLError as exc:
            raise AgentExecutionError(f"Could not reach Ollama at {base_url}: {exc.reason}") from exc

    def chat_stream(
        self,
        *,
        base_url: str,
        model: str,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        options: dict[str, Any] | None = None,
        timeout: int = 180,
    ):
        """Iterador de tokens en streaming sobre `POST /chat` con `stream=true` (Decisión 013).

        Yields raw text deltas a medida que Ollama los emite. Maneja la respuesta línea a línea
        (cada línea es un JSON con `message.content` parcial). Levanta `AgentExecutionError` si
        Ollama no responde.
        """
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": temperature,
                **(options or {}),
            },
        }
        data = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url=f"{base_url.rstrip('/')}/chat",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            response = request.urlopen(req, timeout=timeout)
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise AgentExecutionError(f"Ollama HTTP error {exc.code}: {body}") from exc
        except error.URLError as exc:
            raise AgentExecutionError(f"Could not reach Ollama at {base_url}: {exc.reason}") from exc

        try:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                delta = event.get("message", {}).get("content", "")
                if delta:
                    yield delta
                if event.get("done"):
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
        """Embedding de un texto contra el endpoint `POST /embeddings` de Ollama (Decisión 012).

        Devuelve el vector como `list[float]`. Levanta `AgentExecutionError` si Ollama no responde
        o si la respuesta no contiene un campo `embedding`.
        """
        payload = {"model": model, "prompt": text}
        data = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url=f"{base_url.rstrip('/')}/embeddings",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="ignore")
            raise AgentExecutionError(f"Ollama embed HTTP error {exc.code}: {err_body}") from exc
        except error.URLError as exc:
            raise AgentExecutionError(f"Could not reach Ollama at {base_url}: {exc.reason}") from exc

        vector = body.get("embedding")
        if not isinstance(vector, list) or not vector:
            raise AgentExecutionError(f"Ollama embed response missing 'embedding': {body}")
        return [float(v) for v in vector]
