import json
from pathlib import Path

from app.domain.models import MeetingTranscript


class TranscriptRepository:
    def __init__(self) -> None:
        self.base_dir = Path(__file__).resolve().parents[1] / "data" / "transcripts"

    def list_summaries(self) -> list[dict]:
        transcripts = self.list_transcripts()
        return [self._summary(transcript) for transcript in transcripts]

    def list_transcripts(self) -> list[MeetingTranscript]:
        return sorted((self._load_file(path) for path in self.base_dir.glob("*.json")), key=lambda item: item.title)

    def get_transcript(self, transcript_id: str) -> MeetingTranscript | None:
        for path in self.base_dir.glob("*.json"):
            transcript = self._load_file(path)
            if transcript.id == transcript_id:
                return transcript
        return None

    def serialize(self, transcript: MeetingTranscript) -> dict:
        payload = transcript.model_dump(mode="json")
        payload["raw_text"] = transcript.raw_text or self._build_raw_text(transcript)
        payload["participant_names"] = [participant.name for participant in transcript.participants]
        payload["segment_count"] = len(transcript.segments)
        return payload

    def list_sprints(self) -> list[dict]:
        """Lista los sprints presentes en el dataset, derivados de las transcripciones.

        Cada entrada: {sprint_id, transcript_ids, transcript_count, meeting_dates}.
        Ordenados alfabéticamente por sprint_id (lo que en la práctica coincide con el orden cronológico
        si los sprint_ids siguen un esquema sortable, p. ej. "sprint-24" antes que "sprint-25").
        Las transcripciones sin sprint_id quedan agrupadas bajo `None`.
        """
        by_sprint: dict[str | None, list[MeetingTranscript]] = {}
        for transcript in self.list_transcripts():
            by_sprint.setdefault(transcript.sprint_id, []).append(transcript)
        sprints: list[dict] = []
        for sprint_id, transcripts in by_sprint.items():
            ordered = sorted(transcripts, key=lambda t: t.meeting_date or "")
            sprints.append({
                "sprint_id": sprint_id,
                "transcript_ids": [t.id for t in ordered],
                "transcript_count": len(ordered),
                "meeting_dates": [t.meeting_date for t in ordered if t.meeting_date],
            })
        sprints.sort(key=lambda s: (s["sprint_id"] is None, s["sprint_id"] or ""))
        return sprints

    def get_segment_context(
        self,
        transcript_id: str,
        segment_index: int,
        window: int = 2,
    ) -> dict | None:
        """Devuelve el segmento `segment_index` con `window` turnos previos y posteriores.

        Permite al detalle del compromiso expandir la cita literal a su contexto conversacional
        sin abrir el fichero completo. Retorna None si la transcripción no existe o el índice está
        fuera de rango.
        """
        transcript = self.get_transcript(transcript_id)
        if transcript is None:
            return None
        if segment_index < 0 or segment_index >= len(transcript.segments):
            return None
        start = max(0, segment_index - window)
        end = min(len(transcript.segments), segment_index + window + 1)
        context_segments = [
            {
                "index": i,
                "speaker": s.speaker,
                "timestamp": s.timestamp,
                "text": s.text,
                "is_focus": i == segment_index,
            }
            for i, s in enumerate(transcript.segments[start:end], start=start)
        ]
        return {
            "transcript_id": transcript.id,
            "transcript_title": transcript.title,
            "sprint_id": transcript.sprint_id,
            "focus_index": segment_index,
            "segments": context_segments,
        }

    def _summary(self, transcript: MeetingTranscript) -> dict:
        return {
            "id": transcript.id,
            "title": transcript.title,
            "provider": transcript.provider,
            "meeting_date": transcript.meeting_date,
            "sprint_id": transcript.sprint_id,
            "participant_names": [participant.name for participant in transcript.participants],
            "segment_count": len(transcript.segments),
            "expected_items_count": len(transcript.expected_items),
            "focus": transcript.metadata.get("focus", ""),
        }

    def _load_file(self, path: Path) -> MeetingTranscript:
        data = json.loads(path.read_text(encoding="utf-8"))
        transcript = MeetingTranscript.model_validate(data)
        if transcript.sprint_id is None:
            legacy_sprint = transcript.metadata.get("series_id")
            if isinstance(legacy_sprint, str) and legacy_sprint:
                transcript.sprint_id = legacy_sprint
        if not transcript.raw_text:
            transcript.raw_text = self._build_raw_text(transcript)
        return transcript

    def _build_raw_text(self, transcript: MeetingTranscript) -> str:
        lines = []
        for segment in transcript.segments:
            prefix = f"{segment.timestamp} " if segment.timestamp else ""
            lines.append(f"{prefix}{segment.speaker}: {segment.text}")
        return "\n".join(lines)
