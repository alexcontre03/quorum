import json
import re
from pathlib import Path

from app.agents.exceptions import AgentExecutionError
from app.agents.chat_client import ChatClient
from app.agents.client_factory import get_chat_client
from app.domain.models import AgentDefinition, AgentRun, DetectedItem, IssueDraft, MeetingTranscript

_DRAFTABLE_TYPES = {"task", "ambiguous_task"}

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "drafts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "labels": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["index", "title", "description", "labels"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["drafts"],
    "additionalProperties": False,
}


class IssueDraftAgent:
    def __init__(self, llm_client: ChatClient | None = None) -> None:
        self._pinned_client = llm_client

    @property
    def llm_client(self) -> ChatClient:
        if self._pinned_client is not None:
            return self._pinned_client
        return get_chat_client()

    def run(
        self,
        transcript: MeetingTranscript,
        validated_items: list[DetectedItem],
        definition: AgentDefinition,
    ) -> tuple[list[DetectedItem], AgentRun]:
        draftable = [(i, item) for i, item in enumerate(validated_items) if item.item_type in _DRAFTABLE_TYPES]

        if not draftable:
            return self._passthrough(validated_items, definition)

        prompt = Path(definition.system_prompt_path).read_text(encoding="utf-8")
        raw_response = self.llm_client.chat(
            base_url=definition.base_url,
            model=definition.model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": self._build_user_prompt(transcript, draftable)},
            ],
            response_format=_RESPONSE_SCHEMA,
            temperature=definition.temperature,
            options=definition.options,
        )

        raw_content = raw_response.get("message", {}).get("content", "")
        draft_map = self._parse_drafts(raw_content)

        result = []
        for i, item in enumerate(validated_items):
            enriched = item.model_copy(deep=True)
            if i in draft_map:
                d = draft_map[i]
                enriched.issue_draft = IssueDraft(
                    title=d.get("title", item.title).strip(),
                    description=d.get("description", "").strip(),
                    labels=d.get("labels", []),
                )
            result.append(enriched)

        run = AgentRun(
            agent_id=definition.id,
            agent_name=definition.name,
            provider=definition.provider,
            model=definition.model,
            status="completed",
            output_key=definition.output_key,
            raw_content=raw_content,
        )
        return result, run

    def _passthrough(
        self, items: list[DetectedItem], definition: AgentDefinition
    ) -> tuple[list[DetectedItem], AgentRun]:
        run = AgentRun(
            agent_id=definition.id,
            agent_name=definition.name,
            provider=definition.provider,
            model=definition.model,
            status="completed",
            output_key=definition.output_key,
            raw_content=json.dumps({"drafts": []}, ensure_ascii=False),
        )
        return items, run

    def _build_user_prompt(
        self, transcript: MeetingTranscript, draftable: list[tuple[int, DetectedItem]]
    ) -> str:
        items_json = json.dumps(
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
                for i, item in draftable
            ],
            ensure_ascii=False,
            indent=2,
        )
        return "\n".join(
            [
                f"Meeting title: {transcript.title}",
                f"Meeting date: {transcript.meeting_date or 'unknown'}",
                "Transcript:",
                transcript.raw_text or "",
                "",
                "Items to draft (JSON):",
                items_json,
            ]
        )

    def _parse_drafts(self, raw_content: str) -> dict[int, dict]:
        try:
            cleaned = raw_content.strip()
            if cleaned.startswith("```"):
                match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned, flags=re.DOTALL)
                if match:
                    cleaned = match.group(1).strip()
            data = json.loads(cleaned)
            return {
                d["index"]: d
                for d in data.get("drafts", [])
                if isinstance(d.get("index"), int)
            }
        except (json.JSONDecodeError, KeyError) as exc:
            raise AgentExecutionError(f"Invalid JSON returned by issue_draft_agent: {exc}") from exc
