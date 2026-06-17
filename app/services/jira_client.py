import base64
import json
import re
from dataclasses import dataclass
from typing import Any
from urllib import error, request

from app.config.runtime_settings import JiraRuntimeSettings, get_jira_settings
from app.domain.models import JiraCreatedIssue, JiraIssueMatch


class JiraClientError(Exception):
    pass


@dataclass(frozen=True)
class JiraSearchResult:
    jql: str
    matches: list[JiraIssueMatch]


@dataclass(frozen=True)
class JiraIssueStatus:
    """Estado actual de un issue en Jira tal y como lo expone la API (Decisión 014).

    `status_category_key` es estable (`new` / `indeterminate` / `done`) y es lo que
    `CommitmentRefreshService` usa para decidir si transicionar el compromiso a `closed`.
    `status_name` es el nombre humano de la columna ("Done", "En curso", etc.).
    """
    issue_key: str
    status_name: str
    status_category_key: str


@dataclass(frozen=True)
class JiraTransition:
    """Transición disponible en el workflow del issue (Decisión 015).

    `to_status_category_key` se usa para elegir la transición correcta cuando se quiere mover el
    issue a una categoría concreta (done, indeterminate, new). `name` se usa para preferir
    transiciones que mencionan "review" o "revisión" cuando hay varias `indeterminate`.
    """
    id: str
    name: str
    to_status_name: str
    to_status_category_key: str


class JiraCloudClient:
    def __init__(self, settings: JiraRuntimeSettings | None = None) -> None:
        self.settings = settings or get_jira_settings()

    def is_configured(self) -> bool:
        return self.settings.configured

    def create_issue(self, summary: str, description: str, labels: list[str]) -> JiraCreatedIssue:
        if not self.is_configured():
            raise JiraClientError("Jira is not configured")

        safe_labels = [re.sub(r"\s+", "-", label.strip().lower()) for label in labels if label.strip()]
        payload: dict[str, Any] = {
            "fields": {
                "project": {"key": self.settings.project_key},
                "summary": summary[:255],
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": description}],
                        }
                    ],
                },
                "issuetype": {"name": self.settings.issue_type},
                "labels": safe_labels,
            }
        }
        result = self._post("/rest/api/3/issue", payload)
        issue_key = result.get("key", "")
        url = f"{self.settings.base_url.rstrip('/')}/browse/{issue_key}"
        return JiraCreatedIssue(issue_key=issue_key, url=url)

    def get_issue_status(self, issue_key: str) -> JiraIssueStatus | None:
        """Lee el estado actual del issue por clave (Decisión 014).

        Devuelve `None` si el issue ya no existe en Jira (404) o si Jira no está configurado.
        El campo estable para mapear estados es `statusCategory.key`, que Atlassian categoriza
        automáticamente en `new` / `indeterminate` / `done`. El `name` es la columna humana.
        """
        if not self.is_configured() or not issue_key:
            return None
        url = f"{self.settings.base_url.rstrip('/')}/rest/api/3/issue/{issue_key}?fields=status"
        req = request.Request(
            url,
            method="GET",
            headers={
                "Authorization": f"Basic {self._basic_auth_token()}",
                "Accept": "application/json",
            },
        )
        try:
            with request.urlopen(req, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            if exc.code == 404:
                return None
            detail = exc.read().decode("utf-8", errors="replace")
            raise JiraClientError(f"Jira get_issue_status failed with HTTP {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise JiraClientError(f"Jira request failed: {exc.reason}") from exc

        status = (payload.get("fields") or {}).get("status") or {}
        name = status.get("name") or "Unknown"
        category_key = ((status.get("statusCategory") or {}).get("key") or "indeterminate").lower()
        return JiraIssueStatus(
            issue_key=issue_key,
            status_name=name,
            status_category_key=category_key,
        )

    def list_transitions(self, issue_key: str) -> list[JiraTransition]:
        """Devuelve las transiciones disponibles para el issue (Decisión 015)."""
        if not self.is_configured() or not issue_key:
            return []
        url = f"{self.settings.base_url.rstrip('/')}/rest/api/3/issue/{issue_key}/transitions"
        req = request.Request(
            url,
            method="GET",
            headers={
                "Authorization": f"Basic {self._basic_auth_token()}",
                "Accept": "application/json",
            },
        )
        try:
            with request.urlopen(req, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            if exc.code == 404:
                return []
            detail = exc.read().decode("utf-8", errors="replace")
            raise JiraClientError(f"Jira list_transitions failed with HTTP {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise JiraClientError(f"Jira request failed: {exc.reason}") from exc

        out: list[JiraTransition] = []
        for tr in payload.get("transitions", []):
            to = tr.get("to") or {}
            category = ((to.get("statusCategory") or {}).get("key") or "indeterminate").lower()
            out.append(
                JiraTransition(
                    id=str(tr.get("id", "")),
                    name=tr.get("name", ""),
                    to_status_name=to.get("name", ""),
                    to_status_category_key=category,
                )
            )
        return out

    def transition_issue(self, issue_key: str, transition_id: str) -> None:
        """Aplica una transición concreta al issue (Decisión 015).

        Atlassian devuelve 204 No Content en éxito, así que esta llamada no parsea body.
        """
        if not self.is_configured() or not issue_key or not transition_id:
            return
        url = f"{self.settings.base_url.rstrip('/')}/rest/api/3/issue/{issue_key}/transitions"
        body = json.dumps({"transition": {"id": str(transition_id)}}).encode("utf-8")
        req = request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Basic {self._basic_auth_token()}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        try:
            with request.urlopen(req, timeout=15) as response:
                response.read()  # drena el cuerpo aunque esté vacío
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise JiraClientError(f"Jira transition_issue failed with HTTP {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise JiraClientError(f"Jira request failed: {exc.reason}") from exc

    def add_label(self, issue_key: str, label: str) -> None:
        """Añade una etiqueta al issue sin alterar su estado (Decisión 015)."""
        self._mutate_labels(issue_key, label, action="add")

    def remove_label(self, issue_key: str, label: str) -> None:
        """Quita una etiqueta del issue sin alterar su estado (D023+)."""
        self._mutate_labels(issue_key, label, action="remove")

    def _mutate_labels(self, issue_key: str, label: str, *, action: str) -> None:
        if not self.is_configured() or not issue_key or not label:
            return
        safe_label = re.sub(r"\s+", "-", label.strip().lower())
        if not safe_label:
            return
        url = f"{self.settings.base_url.rstrip('/')}/rest/api/3/issue/{issue_key}"
        body = json.dumps({"update": {"labels": [{action: safe_label}]}}).encode("utf-8")
        req = request.Request(
            url,
            data=body,
            method="PUT",
            headers={
                "Authorization": f"Basic {self._basic_auth_token()}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        try:
            with request.urlopen(req, timeout=15) as response:
                response.read()
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise JiraClientError(
                f"Jira label {action} failed with HTTP {exc.code}: {detail}"
            ) from exc
        except error.URLError as exc:
            raise JiraClientError(f"Jira request failed: {exc.reason}") from exc

    def update_summary_and_description(
        self,
        issue_key: str,
        summary: str | None,
        description: str | None,
    ) -> None:
        """Actualiza el título y/o descripción del issue sin tocar transiciones.

        Util para `scope_change`: cuando la reunión redefine la tarea, el issue
        existente queda obsoleto si no propagamos el nuevo título. Idempotente:
        si el campo nuevo es vacío, ese campo no se envía y no se sobreescribe.
        """
        if not self.is_configured() or not issue_key:
            return
        fields: dict[str, Any] = {}
        if summary is not None and summary.strip():
            fields["summary"] = summary.strip()[:255]
        if description is not None and description.strip():
            fields["description"] = {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": description.strip()}],
                    }
                ],
            }
        if not fields:
            return
        url = f"{self.settings.base_url.rstrip('/')}/rest/api/3/issue/{issue_key}"
        body = json.dumps({"fields": fields}).encode("utf-8")
        req = request.Request(
            url,
            data=body,
            method="PUT",
            headers={
                "Authorization": f"Basic {self._basic_auth_token()}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        try:
            with request.urlopen(req, timeout=15) as response:
                response.read()
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise JiraClientError(
                f"Jira update_summary_and_description failed with HTTP {exc.code}: {detail}"
            ) from exc
        except error.URLError as exc:
            raise JiraClientError(f"Jira request failed: {exc.reason}") from exc

    def search_similar_issues(self, text: str, limit: int = 5) -> JiraSearchResult:
        cleaned_text = self._normalize_search_text(text)
        if not cleaned_text:
            return JiraSearchResult(jql="", matches=[])

        if not self.is_configured():
            return JiraSearchResult(jql="", matches=[])

        queries = self._candidate_jql_queries(cleaned_text)
        seen_keys: set[str] = set()
        matches: list[JiraIssueMatch] = []
        executed_jql = ""

        for jql in queries:
            executed_jql = jql
            payload = self._post(
                "/rest/api/3/search/jql",
                {
                    "jql": jql,
                    "maxResults": limit,
                    "fields": ["summary", "status", "issuetype"],
                },
            )
            for issue in payload.get("issues", []):
                key = issue.get("key", "").strip()
                if not key or key in seen_keys:
                    continue
                fields = issue.get("fields", {})
                matches.append(
                    JiraIssueMatch(
                        issue_key=key,
                        summary=fields.get("summary", "").strip() or "(sin summary)",
                        status=(fields.get("status") or {}).get("name", "Unknown"),
                        issue_type=(fields.get("issuetype") or {}).get("name", "Unknown"),
                        url=f"{self.settings.base_url}/browse/{key}",
                    )
                )
                seen_keys.add(key)
            if matches:
                break

        return JiraSearchResult(jql=executed_jql, matches=matches[:limit])

    def _candidate_jql_queries(self, text: str) -> list[str]:
        escaped_text = self._escape_jql(text)
        keywords = self._extract_keywords(text)
        project = self.settings.project_key
        queries = [
            f'project = {project} AND text ~ "\\"{escaped_text}\\"" ORDER BY updated DESC',
        ]
        if keywords:
            keyword_terms = " OR ".join(f'text ~ "\\"{self._escape_jql(keyword)}\\""' for keyword in keywords[:3])
            queries.append(f"project = {project} AND ({keyword_terms}) ORDER BY updated DESC")
        return queries

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.is_configured():
            raise JiraClientError("Jira is not configured")

        url = f"{self.settings.base_url.rstrip('/')}{path}"
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Basic {self._basic_auth_token()}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        try:
            with request.urlopen(req, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise JiraClientError(f"Jira request failed with HTTP {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise JiraClientError(f"Jira request failed: {exc.reason}") from exc

    def _basic_auth_token(self) -> str:
        raw = f"{self.settings.email}:{self.settings.api_token}".encode("utf-8")
        return base64.b64encode(raw).decode("ascii")

    def _normalize_search_text(self, text: str) -> str:
        normalized = re.sub(r"\s+", " ", text).strip()
        return normalized[:200]

    def _extract_keywords(self, text: str) -> list[str]:
        tokens = re.findall(r"[a-zA-Z0-9]{4,}", text.lower())
        stopwords = {
            "para",
            "sobre",
            "desde",
            "hasta",
            "issue",
            "task",
            "with",
            "that",
            "este",
            "esta",
            "como",
            "porque",
            "cuando",
            "necesitamos",
            "corregir",
            "anadir",
            "validacion",
        }
        unique: list[str] = []
        for token in tokens:
            if token in stopwords or token in unique:
                continue
            unique.append(token)
        return unique

    def _escape_jql(self, value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')
