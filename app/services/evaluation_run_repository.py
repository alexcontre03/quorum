import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.domain.models import DatasetEvaluationResult


class EvaluationRunRepository:
    def __init__(self) -> None:
        self.base_dir = Path(__file__).resolve().parents[1] / "data" / "evaluation_runs"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save(self, evaluation: DatasetEvaluationResult) -> DatasetEvaluationResult:
        evaluation_id = self._new_evaluation_id()
        created_at = self._now_iso()
        record = evaluation.model_copy(deep=True)
        record.evaluation_id = evaluation_id
        record.created_at = created_at

        path = self.base_dir / f"{evaluation_id}.json"
        path.write_text(json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
        return record

    def list_summaries(self, limit: int = 20) -> list[dict]:
        records = sorted(self._load_records(), key=lambda item: item.created_at or "", reverse=True)
        return [self._summary(record) for record in records[:limit]]

    def get_evaluation(self, evaluation_id: str) -> DatasetEvaluationResult | None:
        path = self.base_dir / f"{evaluation_id}.json"
        if not path.exists():
            return None
        return DatasetEvaluationResult.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def _load_records(self) -> list[DatasetEvaluationResult]:
        return [
            DatasetEvaluationResult.model_validate(json.loads(path.read_text(encoding="utf-8")))
            for path in self.base_dir.glob("*.json")
        ]

    def _summary(self, record: DatasetEvaluationResult) -> dict:
        return {
            "evaluation_id": record.evaluation_id,
            "created_at": record.created_at,
            "pipeline_id": record.pipeline_id,
            "matching_threshold": record.matching_threshold,
            "summary": record.summary.model_dump(mode="json"),
        }

    def _new_evaluation_id(self) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        return f"evaluation-{timestamp}-{uuid4().hex[:8]}"

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
