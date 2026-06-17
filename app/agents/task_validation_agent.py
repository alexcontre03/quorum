from pathlib import Path

from app.agents.chat_client import ChatClient
from app.agents.client_factory import get_chat_client
from app.agents.task_item_support import TaskItemSupport
from app.domain.models import AgentDefinition, AgentRun, DetectedItem, MeetingTranscript


class TaskValidationAgent:
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
        proposed_items: list[DetectedItem],
        definition: AgentDefinition,
    ) -> tuple[list[DetectedItem], AgentRun]:
        prompt = Path(definition.system_prompt_path).read_text(encoding="utf-8")
        raw_response = self.llm_client.chat(
            base_url=definition.base_url,
            model=definition.model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": self._build_user_prompt(transcript, proposed_items)},
            ],
            response_format=self.item_support.response_format_for(definition),
            temperature=definition.temperature,
            options=definition.options,
        )

        raw_content = raw_response.get("message", {}).get("content", "")
        payload = self.item_support.parse_payload(raw_content, agent_id=definition.id)
        items = self.item_support.build_detected_items(payload)
        run = AgentRun(
            agent_id=definition.id,
            agent_name=definition.name,
            provider=definition.provider,
            model=definition.model,
            status="completed",
            output_key=definition.output_key,
            raw_content=raw_content,
        )
        return items, run

    def _build_user_prompt(self, transcript: MeetingTranscript, proposed_items: list[DetectedItem]) -> str:
        return "\n".join(
            [
                f"Meeting title: {transcript.title}",
                f"Meeting date: {transcript.meeting_date or 'unknown'}",
                "Transcript:",
                transcript.raw_text or "",
                "",
                "Initial task candidates:",
                self.item_support.serialize_items_for_prompt(proposed_items),
            ]
        )
