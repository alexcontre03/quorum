"""Cliente de la API REST de GitHub para detectar evidencia técnica de un
compromiso (Decisión 023).

Tres búsquedas son la columna vertebral del cliente, todas sobre el endpoint
``/search/issues`` con los selectores adecuados:

1. PRs abiertos que mencionen una query (issue Jira key o keywords del
   compromiso) → señal "in_code_review".
2. PRs mergeados que mencionen la misma query → señal "merged" (la más
   fuerte; gatilla la transición del compromiso a ``evidenced``).
3. Commits en la rama por defecto que mencionen la query →
   evidencia complementaria (la lista clásica del ``git_evidence_agent``
   pero contra el repo remoto, sin necesidad de clonar nada en local).

El cliente nunca escribe nada en GitHub. No crea issues, ni branches, ni
deja comentarios. Solo lee. Por eso el scope mínimo del token es ``repo``
de solo lectura (``public_repo`` si el repositorio es público).

Falla con :class:`GitHubClientError` cuando GitHub devuelve un código
inesperado o cuando el token es inválido; el caller (el
``GithubEvidenceAgent``) trata las excepciones como evidencia ``none`` y
no rompe el resto del pipeline.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib import error, parse, request

from app.config.runtime_settings import GitHubRuntimeSettings, get_github_settings
from app.domain.models import GitHubCommitRef, GitHubPullRequest


class GitHubClientError(Exception):
    """Excepción única de la integración GitHub. El llamador la trata como
    'no hay evidencia GitHub' y continúa con el resto de señales."""


@dataclass(frozen=True)
class GitHubSearchResult:
    """Resultado bruto de una búsqueda en ``/search/issues`` antes de mapear
    a ``GitHubPullRequest``. Útil para tests y para introspección desde
    la UI cuando se quiere mostrar el ``q`` que generó la respuesta."""
    query: str
    total_count: int
    items: list[dict]


class GitHubClient:
    """Cliente fino sobre la API REST v3 de GitHub.

    Solo expone los métodos que el ``GithubEvidenceAgent`` necesita:
    búsqueda de PRs abiertos/mergeados, búsqueda de commits y comprobación
    de configuración. Cualquier otra operación queda fuera de alcance
    (ningún ``create_issue``, ``open_pr`` etc.) porque la integración es
    de lectura por contrato (D023)."""

    def __init__(self, settings: GitHubRuntimeSettings | None = None) -> None:
        self.settings = settings or get_github_settings()

    # ---------- estado ----------

    def is_configured(self) -> bool:
        return self.settings.configured

    # ---------- búsquedas ----------

    def search_pull_requests(
        self,
        query: str,
        *,
        merged: bool | None = None,
        per_page: int = 5,
    ) -> GitHubSearchResult:
        """Devuelve PRs que matchean *query* en title/body/comments.

        - ``merged=None``  → cualquier estado (abierto o cerrado, incluyendo merged).
        - ``merged=True``  → solo PRs mergeados (estos también están ``state:closed``
          en GitHub pero la API admite el qualifier ``is:merged``).
        - ``merged=False`` → solo PRs abiertos (``state:open``).

        La query se compone con los qualifiers de GitHub Search:
        ``repo:owner/repo is:pr <merged-qualifier> <texto>``. La librería no
        intenta escapar los qualifiers porque el texto del compromiso ya
        viene normalizado por el caller; la única transformación es eliminar
        comillas que romperían la cadena de búsqueda.
        """
        text = self._normalize_query(query)
        if not text:
            return GitHubSearchResult(query="", total_count=0, items=[])
        if not self.is_configured():
            raise GitHubClientError("GitHub is not configured")

        qualifiers = [f"repo:{self.settings.repo}", "is:pr"]
        if merged is True:
            qualifiers.append("is:merged")
        elif merged is False:
            qualifiers.append("is:open")
        q = " ".join([*qualifiers, text])
        payload = self._get("/search/issues", {"q": q, "per_page": str(per_page)})
        return GitHubSearchResult(
            query=q,
            total_count=int(payload.get("total_count", 0)),
            items=list(payload.get("items", [])),
        )

    def search_commits(self, query: str, *, per_page: int = 5) -> list[GitHubCommitRef]:
        """Busca commits que mencionen *query* en su mensaje. Usa el endpoint
        ``/search/commits`` que requiere el ``Accept`` header
        ``application/vnd.github.cloak-preview`` (Atlassian lo llama "cloak").
        Devuelve hasta *per_page* resultados, ordenados por relevancia."""
        text = self._normalize_query(query)
        if not text or not self.is_configured():
            return []

        q = f"repo:{self.settings.repo} {text}"
        try:
            payload = self._get(
                "/search/commits",
                {"q": q, "per_page": str(per_page)},
                accept="application/vnd.github.cloak-preview+json",
            )
        except GitHubClientError:
            return []

        commits: list[GitHubCommitRef] = []
        for item in payload.get("items", []):
            commit_info = item.get("commit", {})
            author_info = commit_info.get("author") or {}
            commits.append(
                GitHubCommitRef(
                    sha=str(item.get("sha", "")),
                    message=str(commit_info.get("message", "")).split("\n", 1)[0],
                    date=str(author_info.get("date", "")),
                    author=str(author_info.get("name", "")) or None,
                    html_url=str(item.get("html_url", "")) or None,
                )
            )
        return commits

    # ---------- mappers ----------

    @staticmethod
    def to_pull_requests(items: list[dict]) -> list[GitHubPullRequest]:
        """Convierte los ``items`` brutos de ``/search/issues`` (donde cada PR
        es un issue con ``pull_request != null``) en ``GitHubPullRequest``s."""
        out: list[GitHubPullRequest] = []
        for item in items:
            pull = item.get("pull_request") or {}
            state = item.get("state", "open")
            merged = bool(pull.get("merged_at"))
            out.append(
                GitHubPullRequest(
                    number=int(item.get("number", 0)),
                    title=str(item.get("title", "")),
                    html_url=str(item.get("html_url", "")),
                    state="closed" if state == "closed" else "open",
                    merged=merged,
                    merged_at=str(pull.get("merged_at") or "") or None,
                    author=str((item.get("user") or {}).get("login", "")) or None,
                    head_ref=str((item.get("head") or {}).get("ref", "")) or None,
                    base_ref=str((item.get("base") or {}).get("ref", "")) or None,
                )
            )
        return out

    # ---------- helpers internos ----------

    @staticmethod
    def _normalize_query(text: str) -> str:
        cleaned = re.sub(r'["\\]', " ", text or "")
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned[:200]

    def _get(self, path: str, params: dict[str, str] | None = None, *, accept: str | None = None) -> dict[str, Any]:
        url = f"{self.settings.base_url.rstrip('/')}{path}"
        if params:
            url = f"{url}?{parse.urlencode(params)}"
        req = request.Request(
            url,
            method="GET",
            headers={
                "Authorization": f"Bearer {self.settings.token}",
                "Accept": accept or "application/vnd.github+json",
                "User-Agent": self.settings.user_agent,
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with request.urlopen(req, timeout=15) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise GitHubClientError(
                f"GitHub request failed with HTTP {exc.code}: {detail[:300]}"
            ) from exc
        except error.URLError as exc:
            raise GitHubClientError(f"GitHub request failed: {exc.reason}") from exc
