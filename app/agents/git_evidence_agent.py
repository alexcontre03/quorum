import json
import re
from pathlib import Path

from app.agents.exceptions import AgentExecutionError
from app.agents.chat_client import ChatClient
from app.agents.client_factory import get_chat_client
from app.domain.models import (
    AgentDefinition,
    AgentRun,
    GitCommitRef,
    GitEvidence,
    GitEvidenceUpdate,
    HistoryItemSummary,
    MeetingTranscript,
)
from app.services.git_client import GitCommit, GitRepositoryClient

_ASSESSABLE_TYPES = {"task", "ambiguous_task"}
_MAX_COMMITMENTS_PER_RUN = 15

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "assessments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item_index": {"type": "integer"},
                    "evidence_level": {"type": "string", "enum": ["sufficient", "partial", "none"]},
                    "explanation": {"type": "string"},
                    "supporting_commits": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["item_index", "evidence_level", "explanation", "supporting_commits"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["assessments"],
    "additionalProperties": False,
}


class GitEvidenceAgent:
    """Reune evidencia tecnica en Git para los compromisos del historial.

    Bajo H2 el agente ya no opera sobre los items recien detectados en el run, sino sobre
    los compromisos activos del historial: solo tiene sentido buscar evidencia para algo
    que ya se dijo en una reunion anterior. La salida es una lista de `GitEvidenceUpdate`
    que el follow-up agent recibe como contexto y que el sync aplica al compromiso.
    """

    def __init__(
        self,
        llm_client: ChatClient | None = None,
        git_client: GitRepositoryClient | None = None,
    ) -> None:
        self._pinned_client = llm_client
        self.git_client = git_client or GitRepositoryClient()

    @property
    def llm_client(self) -> ChatClient:
        if self._pinned_client is not None:
            return self._pinned_client
        return get_chat_client()

    def run(
        self,
        transcript: MeetingTranscript,
        history: list[HistoryItemSummary],
        definition: AgentDefinition,
    ) -> tuple[list[GitEvidenceUpdate], AgentRun]:
        if not self.git_client.is_configured():
            return [], self._build_run(definition, reason="git not configured")
        if not history:
            return [], self._build_run(definition, reason="no history")

        candidates = [
            h for h in history
            if h.item_type in _ASSESSABLE_TYPES
            and h.validation_status != "rejected"
            and h.commitment_id
        ][:_MAX_COMMITMENTS_PER_RUN]

        if not candidates:
            return [], self._build_run(definition, reason="no assessable commitments in history")

        commit_map: dict[int, list[GitCommit]] = {}
        for i, candidate in enumerate(candidates):
            keywords = self._extract_keywords(candidate.title)
            commit_map[i] = self.git_client.search_commits(keywords)

        if not any(commit_map.values()):
            return [], self._build_run(definition, reason="no commits found")

        prompt = Path(definition.system_prompt_path).read_text(encoding="utf-8")
        raw_response = self.llm_client.chat(
            base_url=definition.base_url,
            model=definition.model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": self._build_user_prompt(candidates, commit_map)},
            ],
            response_format=_RESPONSE_SCHEMA,
            temperature=definition.temperature,
            options=definition.options,
        )

        raw_content = raw_response.get("message", {}).get("content", "")
        assessments_by_index = self._parse_assessments(raw_content)

        updates: list[GitEvidenceUpdate] = []
        for i, candidate in enumerate(candidates):
            assessment = assessments_by_index.get(i)
            if assessment is None:
                continue
            all_commits = commit_map.get(i, [])
            llm_supporting = {h[:12] for h in assessment.get("supporting_commits", [])}
            supporting = [
                GitCommitRef(hash=c.hash, message=c.message, author=c.author, date=c.date)
                for c in all_commits
                if c.hash in llm_supporting
            ]
            evidence = GitEvidence(
                evidence_level=assessment.get("evidence_level", "none"),
                explanation=assessment.get("explanation", ""),
                supporting_commits=supporting,
            )
            updates.append(
                GitEvidenceUpdate(commitment_id=candidate.commitment_id, evidence=evidence)
            )

        return (
            updates,
            AgentRun(
                agent_id=definition.id,
                agent_name=definition.name,
                provider=definition.provider,
                model=definition.model,
                status="completed",
                output_key=definition.output_key,
                raw_content=raw_content,
            ),
        )

    def _build_run(self, definition: AgentDefinition, reason: str) -> AgentRun:
        return AgentRun(
            agent_id=definition.id,
            agent_name=definition.name,
            provider=definition.provider,
            model=definition.model,
            status="completed",
            output_key=definition.output_key,
            raw_content=json.dumps({"skipped": reason}, ensure_ascii=False),
        )

    def _extract_keywords(self, title: str) -> list[str]:
        stopwords = {
            "el", "la", "los", "las", "un", "una", "de", "del", "en", "al",
            "con", "para", "por", "que", "the", "a", "an", "of", "in", "to", "for",
        }
        tokens = re.findall(r"[a-zA-ZÀ-ɏ]{4,}", title.lower())
        return [t for t in tokens if t not in stopwords][:4]

    def _build_user_prompt(
        self,
        candidates: list[HistoryItemSummary],
        commit_map: dict[int, list[GitCommit]],
    ) -> str:
        items_with_commits = []
        for i, candidate in enumerate(candidates):
            commits = commit_map.get(i, [])
            items_with_commits.append({
                "index": i,
                "commitment_title": candidate.title,
                "meeting_origin": candidate.meeting_title,
                "meeting_date": candidate.meeting_date,
                "commits_found": [
                    {"hash": c.hash, "message": c.message, "author": c.author, "date": c.date}
                    for c in commits
                ],
            })
        return json.dumps(items_with_commits, ensure_ascii=False, indent=2)

    def _parse_assessments(self, raw_content: str) -> dict[int, dict]:
        try:
            cleaned = raw_content.strip()
            if cleaned.startswith("```"):
                match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned, flags=re.DOTALL)
                if match:
                    cleaned = match.group(1).strip()
            data = json.loads(cleaned)
            return {
                a["item_index"]: a
                for a in data.get("assessments", [])
                if isinstance(a.get("item_index"), int)
            }
        except (json.JSONDecodeError, KeyError) as exc:
            raise AgentExecutionError(f"Invalid JSON returned by git_evidence_agent: {exc}") from exc
