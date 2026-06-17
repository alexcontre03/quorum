import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.domain.models import Commitment, HistoryItemSummary


class CommitmentRepository:
    """Persistencia JSON de compromisos: un fichero por compromiso."""

    def __init__(self) -> None:
        self.base_dir = Path(__file__).resolve().parents[1] / "data" / "commitments"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def create(self, commitment: Commitment) -> Commitment:
        self._write(commitment)
        return commitment

    def update(self, commitment: Commitment) -> Commitment:
        commitment.updated_at = self._now_iso()
        self._write(commitment)
        return commitment

    def get(self, commitment_id: str) -> Commitment | None:
        path = self.base_dir / f"{commitment_id}.json"
        if not path.exists():
            return None
        try:
            return Commitment.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, ValueError):
            return None

    def list_all(self) -> list[Commitment]:
        commitments: list[Commitment] = []
        for path in self.base_dir.glob("*.json"):
            try:
                commitments.append(
                    Commitment.model_validate(json.loads(path.read_text(encoding="utf-8")))
                )
            except (json.JSONDecodeError, ValueError):
                continue
        return commitments

    def list_summaries(self, limit: int = 50, sprint_id: str | None = None) -> list[dict]:
        commitments = sorted(self.list_all(), key=lambda c: c.updated_at, reverse=True)
        if sprint_id is not None:
            commitments = [c for c in commitments if c.origin.sprint_id == sprint_id]
        return [self._summary(c) for c in commitments[:limit]]

    def list_by_sprint(self, sprint_id: str) -> list[Commitment]:
        return [c for c in self.list_all() if c.origin.sprint_id == sprint_id]

    def build_history(self, limit: int = 50) -> list[HistoryItemSummary]:
        """Construye el historial que alimenta al follow-up agent desde los compromisos."""
        commitments = sorted(self.list_all(), key=lambda c: c.updated_at, reverse=True)
        history: list[HistoryItemSummary] = []
        for commitment in commitments[:limit]:
            history.append(
                HistoryItemSummary(
                    run_id=commitment.origin.source_run_id,
                    meeting_title=commitment.origin.meeting_title,
                    meeting_date=commitment.origin.meeting_date,
                    item_type=commitment.item_type,
                    title=commitment.title,
                    validation_status=self._derived_validation_status(commitment),
                    jira_issue_key=(
                        commitment.jira_created_issue.issue_key
                        if commitment.jira_created_issue
                        else None
                    ),
                    commitment_id=commitment.commitment_id,
                )
            )
        return history

    def new_commitment_id(self) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        return f"cmt-{timestamp}-{uuid4().hex[:8]}"

    @staticmethod
    def now_iso() -> str:
        return CommitmentRepository._now_iso()

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    def _write(self, commitment: Commitment) -> None:
        path = self.base_dir / f"{commitment.commitment_id}.json"
        path.write_text(
            json.dumps(commitment.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _summary(self, commitment: Commitment) -> dict:
        return {
            "commitment_id": commitment.commitment_id,
            "title": commitment.title,
            "item_type": commitment.item_type,
            "state": commitment.state,
            "meeting_title": commitment.origin.meeting_title,
            "meeting_date": commitment.origin.meeting_date,
            "sprint_id": commitment.origin.sprint_id,
            "jira_issue_key": (
                commitment.jira_created_issue.issue_key if commitment.jira_created_issue else None
            ),
            "git_evidence_level": (
                commitment.git_evidence.evidence_level if commitment.git_evidence else None
            ),
            "timeline_length": len(commitment.timeline),
            "created_at": commitment.created_at,
            "updated_at": commitment.updated_at,
        }

    def _derived_validation_status(self, commitment: Commitment):
        if commitment.state == "rejected":
            return "rejected"
        if commitment.state in ("validated", "registered", "evidenced", "closed"):
            return "approved"
        return "pending_review"
