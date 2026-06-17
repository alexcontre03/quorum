import json
import re
from pathlib import Path

from app.agents.exceptions import AgentExecutionError
from app.agents.chat_client import ChatClient
from app.agents.client_factory import get_chat_client
from app.agents.task_item_support import TaskItemSupport
from app.domain.models import (
    AgentDefinition,
    AgentRun,
    DetectedItem,
    FollowupAnalysisResult,
    FollowupUpdate,
    GitEvidenceUpdate,
    HistoryItemSummary,
    MeetingTranscript,
    RetrievedChunk,
    TaskCandidatePayload,
    TaskProposalPayload,
)

_FOLLOWUP_TYPES = {
    "recurring_unresolved",
    "scope_change",
    "new_blocker",
    "blocker_resolved",
    "possible_duplicate",
    "contradicts_decision",
    "verbal_close",
}

def _build_response_schema(history: list[HistoryItemSummary]) -> dict:
    """Build the JSON Schema for the response, with ``matched_history_title``
    constrained to the actual titles of the items in *history*. This
    eliminates the failure mode where the model invents a title that does
    not exist in the history (observed empirically with both ``qwen2.5:7b``
    and ``gpt-4o-mini`` once the history grows past ~10 items).
    """
    available_titles = sorted({h.title for h in history if h.title})
    matched_history_title_schema: dict = {"type": "string"}
    if available_titles:
        matched_history_title_schema["enum"] = available_titles
    return {
        "type": "object",
        "properties": {
            "new_items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "item_type": {"type": "string", "enum": ["task", "ambiguous_task", "technical_decision"]},
                        "title": {"type": "string"},
                        "summary": {"type": "string"},
                        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                        "speaker": {"type": "string"},
                        "timestamp": {"type": ["string", "null"]},
                        "evidence": {"type": "string"},
                    },
                    "required": ["item_type", "title", "summary", "confidence", "speaker", "timestamp", "evidence"],
                    "additionalProperties": False,
                },
            },
            "followup_updates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "followup_type": {
                            "type": "string",
                            "enum": [
                                "recurring_unresolved",
                                "scope_change",
                                "new_blocker",
                                "blocker_resolved",
                                "possible_duplicate",
                                "contradicts_decision",
                                "verbal_close",
                            ],
                        },
                        "matched_history_title": matched_history_title_schema,
                        "explanation": {"type": "string"},
                        "trigger_quote": {"type": "string"},
                        "new_title": {"type": ["string", "null"]},
                        "new_summary": {"type": ["string", "null"]},
                        "matched_new_item_index": {"type": ["integer", "null"]},
                    },
                    "required": [
                        "followup_type",
                        "matched_history_title",
                        "explanation",
                        "trigger_quote",
                        "new_title",
                        "new_summary",
                        "matched_new_item_index",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["new_items", "followup_updates"],
        "additionalProperties": False,
    }


class TaskFollowupAgent:
    def __init__(self, llm_client: ChatClient | None = None) -> None:
        self._pinned_client = llm_client
        self.item_support = TaskItemSupport()

    @property
    def llm_client(self) -> ChatClient:
        if self._pinned_client is not None:
            return self._pinned_client
        return get_chat_client()

    def run(
        self,
        transcript: MeetingTranscript,
        current_items: list[DetectedItem],
        history: list[HistoryItemSummary],
        definition: AgentDefinition,
        history_git_evidence: list[GitEvidenceUpdate] | None = None,
        retrieved_chunks_by_item: dict[int, list[RetrievedChunk]] | None = None,
    ) -> FollowupAnalysisResult:
        if not history:
            return FollowupAnalysisResult(
                new_items=current_items,
                followup_updates=[],
                agent_run=AgentRun(
                    agent_id=definition.id,
                    agent_name=definition.name,
                    provider=definition.provider,
                    model=definition.model,
                    status="completed",
                    output_key=definition.output_key,
                    raw_content=json.dumps({"new_items": [], "followup_updates": [], "skipped": "no history"}, ensure_ascii=False),
                ),
            )

        prompt = Path(definition.system_prompt_path).read_text(encoding="utf-8")
        raw_response = self.llm_client.chat(
            base_url=definition.base_url,
            model=definition.model,
            messages=[
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": self._build_user_prompt(
                        transcript,
                        current_items,
                        history,
                        history_git_evidence or [],
                        retrieved_chunks_by_item or {},
                    ),
                },
            ],
            response_format=_build_response_schema(history),
            temperature=definition.temperature,
            options=definition.options,
        )

        raw_content = raw_response.get("message", {}).get("content", "")
        new_items, followup_updates = self._parse_response(raw_content)

        run = AgentRun(
            agent_id=definition.id,
            agent_name=definition.name,
            provider=definition.provider,
            model=definition.model,
            status="completed",
            output_key=definition.output_key,
            raw_content=raw_content,
        )
        return FollowupAnalysisResult(new_items=new_items, followup_updates=followup_updates, agent_run=run)

    def _build_user_prompt(
        self,
        transcript: MeetingTranscript,
        current_items: list[DetectedItem],
        history: list[HistoryItemSummary],
        history_git_evidence: list[GitEvidenceUpdate],
        retrieved_chunks_by_item: dict[int, list[RetrievedChunk]],
    ) -> str:
        evidence_by_commitment = {u.commitment_id: u.evidence for u in history_git_evidence}
        history_json = json.dumps(
            [
                {
                    "meeting_title": h.meeting_title,
                    "meeting_date": h.meeting_date,
                    "item_type": h.item_type,
                    "title": h.title,
                    "validation_status": h.validation_status,
                    "jira_issue_key": h.jira_issue_key,
                    "git_evidence": (
                        {
                            "evidence_level": evidence_by_commitment[h.commitment_id].evidence_level,
                            "explanation": evidence_by_commitment[h.commitment_id].explanation,
                        }
                        if h.commitment_id and h.commitment_id in evidence_by_commitment
                        else None
                    ),
                }
                for h in history
            ],
            ensure_ascii=False,
            indent=2,
        )
        current_json = json.dumps(
            [
                {
                    "index": i,
                    "item_type": item.item_type,
                    "title": item.title,
                    "summary": item.summary,
                    "speaker": item.speaker,
                    "timestamp": item.timestamp,
                    "evidence": item.evidence,
                }
                for i, item in enumerate(current_items)
            ],
            ensure_ascii=False,
            indent=2,
        )
        sections = [
            f"Titulo de la nueva reunion: {transcript.title}",
            f"Fecha de la nueva reunion: {transcript.meeting_date or 'desconocida'}",
            "",
            "Transcripcion de la nueva reunion:",
            transcript.raw_text or "",
            "",
            "Items detectados en la nueva reunion (ya extraidos por agentes previos):",
            current_json,
            "",
            "Historial de compromisos de reuniones anteriores (compara los items nuevos contra esto):",
            history_json,
        ]

        if retrieved_chunks_by_item:
            chunk_lines: list[str] = []
            for index, chunks in retrieved_chunks_by_item.items():
                if not chunks:
                    continue
                chunk_lines.append(f"- Para el item con index {index}:")
                for c in chunks:
                    meeting_tag = c.sprint_id or "historial"
                    chunk_lines.append(
                        f"  - ({meeting_tag}, similitud={c.similarity:.2f}) {c.text}"
                    )
            if chunk_lines:
                sections.extend(
                    [
                        "",
                        "Fragmentos relevantes recuperados de transcripciones anteriores (contexto de apoyo):",
                        *chunk_lines,
                    ]
                )

        return "\n".join(sections)

    def _parse_response(self, raw_content: str) -> tuple[list[DetectedItem], list[FollowupUpdate]]:
        try:
            cleaned = raw_content.strip()
            if cleaned.startswith("```"):
                match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned, flags=re.DOTALL)
                if match:
                    cleaned = match.group(1).strip()
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise AgentExecutionError(f"Invalid JSON returned by task_followup_agent: {exc}") from exc

        raw_items = data.get("new_items", [])
        payload = TaskProposalPayload(
            items=[
                TaskCandidatePayload(
                    item_type=i.get("item_type", "task"),
                    title=i.get("title", ""),
                    summary=i.get("summary", ""),
                    confidence=i.get("confidence", "medium"),
                    speaker=i.get("speaker", "Unknown"),
                    timestamp=i.get("timestamp"),
                    evidence=i.get("evidence", ""),
                )
                for i in raw_items
                if i.get("title")
            ]
        )
        new_items = self.item_support.build_detected_items(payload)

        followup_updates = [
            FollowupUpdate(
                followup_type=u.get("followup_type", "recurring_unresolved"),
                matched_history_title=u.get("matched_history_title", ""),
                explanation=u.get("explanation", ""),
                trigger_quote=(u.get("trigger_quote") or "").strip(),
                new_title=u.get("new_title"),
                new_summary=u.get("new_summary"),
                matched_new_item_index=u.get("matched_new_item_index"),
            )
            for u in data.get("followup_updates", [])
            if u.get("matched_history_title") and u.get("followup_type") in _FOLLOWUP_TYPES
        ]

        return new_items, followup_updates
