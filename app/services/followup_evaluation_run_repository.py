import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.domain.models import FollowupEvaluationResult


class FollowupEvaluationRunRepository:
    """Persistencia JSON de evaluaciones del razonamiento de seguimiento: un fichero por evaluación."""

    def __init__(self) -> None:
        self.base_dir = Path(__file__).resolve().parents[1] / "data" / "followup_evaluation_runs"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save(self, evaluation: FollowupEvaluationResult) -> FollowupEvaluationResult:
        evaluation_id = self._new_evaluation_id()
        created_at = self._now_iso()
        saved = evaluation.model_copy(deep=True)
        saved.evaluation_id = evaluation_id
        saved.created_at = created_at

        path = self.base_dir / f"{evaluation_id}.json"
        path.write_text(
            json.dumps(saved.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return saved

    def list_summaries(self, limit: int = 20) -> list[dict]:
        evaluations = sorted(self._load_all(), key=lambda e: e.created_at or "", reverse=True)
        return [self._summary(e) for e in evaluations[:limit]]

    def get_evaluation(self, evaluation_id: str) -> FollowupEvaluationResult | None:
        path = self.base_dir / f"{evaluation_id}.json"
        if not path.exists():
            return None
        try:
            return FollowupEvaluationResult.model_validate(
                json.loads(path.read_text(encoding="utf-8"))
            )
        except (json.JSONDecodeError, ValueError):
            return None

    def _load_all(self) -> list[FollowupEvaluationResult]:
        evaluations = []
        for path in self.base_dir.glob("*.json"):
            try:
                evaluations.append(
                    FollowupEvaluationResult.model_validate(
                        json.loads(path.read_text(encoding="utf-8"))
                    )
                )
            except (json.JSONDecodeError, ValueError):
                continue
        return evaluations

    def _summary(self, evaluation: FollowupEvaluationResult) -> dict:
        return {
            "evaluation_id": evaluation.evaluation_id,
            "created_at": evaluation.created_at,
            "pipeline_id": evaluation.pipeline_id,
            "summary": evaluation.summary.model_dump(mode="json"),
        }

    def _new_evaluation_id(self) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        return f"followup-eval-{timestamp}-{uuid4().hex[:8]}"

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
