import json
import re

from pydantic import ValidationError

from app.agents.exceptions import AgentExecutionError
from app.domain.models import (
    AgentDefinition,
    DetectedItem,
    TaskCandidatePayload,
    TaskProposalPayload,
)


class TaskItemSupport:
    decision_cues = ("decidimos", "nos quedamos con", "la decision es", "descartamos", "mantenemos")
    ambiguous_cues = ("podriamos", "habria que", "no se si", "quizas", "igual hay que")
    task_cues = (
        "hay que",
        "tenemos que",
        "necesitamos",
        "crear ",
        "anadir ",
        "preparar ",
        "revisar ",
        "corregir ",
        "documentar ",
        "migrar ",
        "desplegar ",
        "implementar ",
        "validar ",
    )

    def response_format_for(self, definition: AgentDefinition) -> str | dict:
        if definition.response_schema in {"task_candidates_v1", "validated_task_candidates_v1"}:
            return {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "item_type": {
                                    "type": "string",
                                    "enum": ["task", "ambiguous_task", "technical_decision"],
                                },
                                "title": {"type": "string"},
                                "summary": {"type": "string"},
                                "confidence": {
                                    "type": "string",
                                    "enum": ["high", "medium", "low"],
                                },
                                "speaker": {"type": "string"},
                                "timestamp": {"type": ["string", "null"]},
                                "evidence": {"type": "string"},
                            },
                            "required": [
                                "item_type",
                                "title",
                                "summary",
                                "confidence",
                                "speaker",
                                "timestamp",
                                "evidence",
                            ],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["items"],
                "additionalProperties": False,
            }
        return definition.format

    def parse_payload(
        self, raw_content: str, agent_id: str | None = None
    ) -> TaskProposalPayload:
        try:
            return TaskProposalPayload.model_validate(self._parse_json_payload(raw_content))
        except (json.JSONDecodeError, ValidationError) as exc:
            label = agent_id or "agent"
            raise AgentExecutionError(
                f"Invalid JSON returned by {label}: {exc}"
            ) from exc

    def build_detected_items(self, payload: TaskProposalPayload) -> list[DetectedItem]:
        items: list[DetectedItem] = []
        seen_keys: set[tuple[str, str]] = set()

        for candidate in payload.items:
            normalized_type, normalized_confidence = self._normalize_classification(
                candidate.item_type, candidate.evidence
            )
            dedupe_key = (normalized_type, self._normalize(candidate.title))
            if dedupe_key in seen_keys:
                continue

            item = DetectedItem(
                item_type=normalized_type,
                title=candidate.title.strip(),
                summary=candidate.summary.strip(),
                confidence=normalized_confidence,
                speaker=candidate.speaker.strip() or "Unknown",
                timestamp=candidate.timestamp,
                evidence=candidate.evidence.strip(),
            )
            items.append(item)
            seen_keys.add(dedupe_key)

        return items

    def serialize_items_for_prompt(self, items: list[DetectedItem]) -> str:
        return json.dumps(
            [
                {
                    "item_type": item.item_type,
                    "title": item.title,
                    "summary": item.summary,
                    "confidence": item.confidence,
                    "speaker": item.speaker,
                    "timestamp": item.timestamp,
                    "evidence": item.evidence,
                }
                for item in items
            ],
            ensure_ascii=False,
            indent=2,
        )

    def task_payload_from_items(self, items: list[DetectedItem]) -> TaskProposalPayload:
        return TaskProposalPayload(
            items=[
                TaskCandidatePayload(
                    item_type=item.item_type,
                    title=item.title,
                    summary=item.summary,
                    confidence=item.confidence,
                    speaker=item.speaker,
                    timestamp=item.timestamp,
                    evidence=item.evidence,
                )
                for item in items
            ]
        )

    def _parse_json_payload(self, raw_content: str) -> dict:
        cleaned = raw_content.strip()
        if cleaned.startswith("```"):
            match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned, flags=re.DOTALL)
            if match:
                cleaned = match.group(1).strip()
        return json.loads(cleaned)

    def _normalize(self, value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()

    def _normalize_classification(self, item_type: str, evidence: str) -> tuple[str, str]:
        lowered = evidence.lower()

        if any(cue in lowered for cue in self.decision_cues):
            return "technical_decision", "high"

        if any(cue in lowered for cue in self.ambiguous_cues):
            return "ambiguous_task", "medium"

        if any(cue in lowered for cue in self.task_cues):
            return "task", "high"

        if item_type == "ambiguous_task":
            return item_type, "medium"

        return item_type, "high" if item_type == "task" else "medium"
