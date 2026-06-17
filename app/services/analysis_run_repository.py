import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.domain.models import AnalysisResult, MeetingTranscript, PersistedAnalysisRun


class AnalysisRunRepository:
    def __init__(self) -> None:
        self.base_dir = Path(__file__).resolve().parents[1] / "data" / "analysis_runs"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save(self, transcript: MeetingTranscript, analysis: AnalysisResult) -> PersistedAnalysisRun:
        """Persiste el análisis de una transcripción de forma **idempotente** (Decisión 009).

        Si ya existe un run para `transcript.id`, reutiliza su `run_id` y sobrescribe el fichero;
        `created_at` se refresca como "última vez analizada". Si no existe, genera un `run_id` nuevo.
        Mantener el `run_id` estable entre re-análisis preserva los enlaces que viven en los
        compromisos persistidos (`commitment.origin.source_run_id`).
        """
        existing = self.get_run_by_transcript(transcript.id)
        run_id = existing.run_id if existing is not None else self._new_run_id()
        created_at = self._now_iso()

        saved_analysis = analysis.model_copy(deep=True)
        saved_analysis.run_id = run_id
        saved_analysis.created_at = created_at

        record = PersistedAnalysisRun(
            run_id=run_id,
            created_at=created_at,
            transcript_id=transcript.id,
            transcript_title=transcript.title,
            transcript_provider=transcript.provider,
            pipeline_id=analysis.pipeline_id,
            analysis=saved_analysis,
        )
        path = self.base_dir / f"{run_id}.json"
        path.write_text(json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
        return record

    def list_summaries(self, limit: int = 20) -> list[dict]:
        records = sorted(self._load_records(), key=lambda item: item.created_at, reverse=True)
        return [self._summary(record) for record in records[:limit]]

    def get_run(self, run_id: str) -> PersistedAnalysisRun | None:
        path = self.base_dir / f"{run_id}.json"
        if not path.exists():
            return None
        return PersistedAnalysisRun.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def get_run_by_transcript(self, transcript_id: str) -> PersistedAnalysisRun | None:
        """Devuelve el run vigente para una transcripción, o None si no se ha analizado.

        Escaneo del directorio en O(N); aceptable para el tamaño del dataset (Decisión 009).
        """
        for record in self._load_records():
            if record.transcript_id == transcript_id:
                return record
        return None

    def list_analyzed_transcript_ids(self) -> set[str]:
        """Devuelve los transcript_id que ya tienen run persistido en esta instancia."""
        return {record.transcript_id for record in self._load_records()}

    def update_run(self, record: PersistedAnalysisRun) -> None:
        path = self.base_dir / f"{record.run_id}.json"
        path.write_text(json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_records(self) -> list[PersistedAnalysisRun]:
        records = []
        for path in self.base_dir.glob("*.json"):
            try:
                records.append(PersistedAnalysisRun.model_validate(json.loads(path.read_text(encoding="utf-8"))))
            except (json.JSONDecodeError, ValueError):
                pass
        return records

    def _summary(self, record: PersistedAnalysisRun) -> dict:
        return {
            "run_id": record.run_id,
            "created_at": record.created_at,
            "transcript_id": record.transcript_id,
            "transcript_title": record.transcript_title,
            "transcript_provider": record.transcript_provider,
            "pipeline_id": record.pipeline_id,
            "summary": record.analysis.summary.model_dump(mode="json"),
            "agent_count": len(record.analysis.agent_runs),
        }

    def _new_run_id(self) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        return f"run-{timestamp}-{uuid4().hex[:8]}"

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
