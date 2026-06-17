"""GithubEvidenceAgent (Decisión 023).

Detecta evidencia técnica en GitHub para un compromiso a partir de tres
búsquedas sobre la API de GitHub:

1. ``is:pr is:open <query>`` → PRs abiertos que mencionan la query.
2. ``is:pr is:merged <query>`` → PRs mergeados.
3. ``search/commits <query>`` → commits en la rama por defecto (sin filtrar
   por estado de PR).

La query se compone en este orden de preferencia:

- El **Jira issue key** del compromiso (``PAY-123``) cuando existe. Es lo
  más fiable porque los equipos suelen incluirlo en title/body del PR para
  que Jira detecte la relación.
- Si no hay Jira key, las **keywords del título** del compromiso filtradas
  por longitud y stopwords (similar a lo que hace ``JiraCloudClient`` para
  buscar issues similares).

El nivel de evidencia se calcula priorizando la señal más fuerte:

- ``merged`` (al menos un PR mergeado) → eleva el compromiso a
  ``evidenced``.
- ``in_code_review`` (al menos un PR abierto, sin mergeados) → eleva el
  compromiso a ``in_code_review``.
- ``none`` cuando no hay nada. La lista de commits puede no estar vacía
  incluso con nivel ``none`` (commits sueltos sin PR), por eso el agent
  los devuelve igualmente para que la UI pueda mostrarlos como
  evidencia complementaria.

Este agente *no* es parte del pipeline de análisis de reuniones. Vive
fuera, en el ``CommitmentRefreshService`` (D014), porque las señales de
GitHub son asíncronas respecto a las reuniones (un PR se abre o mergea
cuando el equipo termina, no cuando se reúne)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.domain.models import (
    Commitment,
    GitHubCommitRef,
    GitHubEvidence,
    GitHubEvidenceLevel,
    GitHubPullRequest,
)
from app.services.github_client import GitHubClient, GitHubClientError


_STOPWORDS = {
    "para", "sobre", "desde", "hasta", "este", "esta", "como", "porque",
    "cuando", "necesitamos", "corregir", "anadir", "añadir", "validacion",
    "validación", "issue", "task", "with", "that", "from", "what", "para",
    "sprint", "review", "planning", "midpoint", "the", "and", "for", "los",
    "las", "del", "que", "una", "unos",
}


@dataclass(frozen=True)
class _BuiltQuery:
    """Query construida + fuente (jira_key o keywords). La fuente se mete en
    la explanation para que el usuario sepa por qué match (o no match)."""
    text: str
    source: str  # "jira_key" | "keywords"


class GithubEvidenceAgent:
    """Construye un :class:`GitHubEvidence` para un compromiso usando la API
    de GitHub. No tiene LLM: las decisiones son deterministas a partir de
    los resultados de las tres búsquedas."""

    def __init__(self, github_client: GitHubClient | None = None) -> None:
        self.github_client = github_client or GitHubClient()

    def is_configured(self) -> bool:
        return self.github_client.is_configured()

    def evaluate(self, commitment: Commitment) -> GitHubEvidence | None:
        """Devuelve la evidencia GitHub más reciente para *commitment*, o
        ``None`` si GitHub no está configurado o el compromiso no es un
        item técnico (decisiones técnicas no se buscan en código)."""
        if not self.is_configured():
            return None
        if commitment.item_type not in ("task", "ambiguous_task"):
            return None

        query = self._build_query(commitment)
        if query is None:
            return GitHubEvidence(
                evidence_level="none",
                explanation="No hay Jira key ni palabras clave aprovechables para buscar.",
                repo=self.github_client.settings.repo,
            )

        # 1) PRs mergeados (la señal más fuerte primero, así si los hay no
        #    seguimos investigando si hay PRs abiertos con el mismo match).
        try:
            merged_raw = self.github_client.search_pull_requests(
                query.text, merged=True
            )
            merged_prs = self.github_client.to_pull_requests(merged_raw.items)
        except GitHubClientError as exc:
            return GitHubEvidence(
                evidence_level="none",
                explanation=f"GitHub no respondió a la búsqueda de PRs mergeados: {exc}",
                repo=self.github_client.settings.repo,
            )

        # 2) PRs abiertos
        try:
            open_raw = self.github_client.search_pull_requests(
                query.text, merged=False
            )
            open_prs = self.github_client.to_pull_requests(open_raw.items)
        except GitHubClientError:
            open_prs = []

        # 3) Commits (siempre, aunque haya PRs, para completar la traza).
        commits: list[GitHubCommitRef] = []
        try:
            commits = self.github_client.search_commits(query.text)
        except GitHubClientError:
            commits = []

        level, explanation = self._summarise(query, merged_prs, open_prs, commits)
        return GitHubEvidence(
            evidence_level=level,
            explanation=explanation,
            repo=self.github_client.settings.repo,
            pull_requests_open=open_prs,
            pull_requests_merged=merged_prs,
            supporting_commits=commits,
        )

    # ---------- helpers ----------

    def _build_query(self, commitment: Commitment) -> _BuiltQuery | None:
        if (
            commitment.jira_created_issue is not None
            and commitment.jira_created_issue.issue_key
        ):
            return _BuiltQuery(
                text=commitment.jira_created_issue.issue_key,
                source="jira_key",
            )
        keywords = self._extract_keywords(commitment.title)
        if not keywords:
            return None
        return _BuiltQuery(text=" ".join(keywords[:3]), source="keywords")

    @staticmethod
    def _extract_keywords(text: str) -> list[str]:
        tokens = re.findall(r"[a-zA-ZáéíóúñÁÉÍÓÚÑ0-9]{4,}", (text or "").lower())
        seen: list[str] = []
        for token in tokens:
            if token in _STOPWORDS or token in seen:
                continue
            seen.append(token)
        return seen

    @staticmethod
    def _summarise(
        query: _BuiltQuery,
        merged_prs: list[GitHubPullRequest],
        open_prs: list[GitHubPullRequest],
        commits: list[GitHubCommitRef],
    ) -> tuple[GitHubEvidenceLevel, str]:
        source_label = (
            f"Jira issue {query.text!r}"
            if query.source == "jira_key"
            else f"keywords {query.text!r}"
        )
        if merged_prs:
            pr = merged_prs[0]
            return "merged", (
                f"PR mergeado encontrado en GitHub (#{pr.number} «{pr.title}») "
                f"que referencia {source_label}."
            )
        if open_prs:
            pr = open_prs[0]
            return "in_code_review", (
                f"PR abierto en GitHub (#{pr.number} «{pr.title}») que "
                f"referencia {source_label}."
            )
        if commits:
            return "none", (
                f"Sin PRs asociados; se encontraron {len(commits)} commit(s) "
                f"mencionando {source_label}."
            )
        return "none", f"Sin actividad en GitHub para {source_label}."
