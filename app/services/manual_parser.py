import re
import unicodedata

from app.domain.models import MeetingTranscript, TranscriptSegment


class ManualTranscriptParser:
    line_pattern = re.compile(
        r"^(?:(?P<timestamp>\d{1,2}:\d{2}(?::\d{2})?)\s+)?(?P<speaker>[^:]+):\s*(?P<text>.+)$"
    )

    def parse(self, raw_text: str, title: str, provider: str = "manual") -> MeetingTranscript:
        lines = [line.rstrip() for line in raw_text.splitlines()]
        segments: list[TranscriptSegment] = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            match = self.line_pattern.match(stripped)
            if match:
                segments.append(
                    TranscriptSegment(
                        timestamp=match.group("timestamp"),
                        speaker=match.group("speaker").strip(),
                        text=match.group("text").strip(),
                    )
                )
                continue

            if segments:
                segments[-1].text = f"{segments[-1].text} {stripped}".strip()
            else:
                segments.append(TranscriptSegment(speaker="Unknown", text=stripped))

        return MeetingTranscript(
            id=self._slugify(title),
            title=title,
            provider=provider,
            segments=segments,
            raw_text=raw_text.strip(),
            metadata={"source": "manual-input"},
        )

    def _slugify(self, value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
        collapsed = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
        return collapsed or "manual-transcript"
