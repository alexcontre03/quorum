"""Refresco del estado del compromiso contra Jira y Git (Decisión 014).

Cierra el bucle entre lo dicho en una reunión, lo planificado en Jira y lo construido en Git.
Sin esto, el estado de un compromiso solo cambia si se vuelve a mencionar en otra reunión
analizada — lo que deja ciego al sistema cuando el equipo simplemente trabaja la tarea.

El servicio es quirúrgico: NO pasa por el pipeline de análisis, NO procesa transcripciones, NO
ejecuta los seis agentes. Para cada compromiso consulta directamente Jira y Git y aplica solo
cambios monótonos (el ciclo de vida no retrocede; la evidencia no degrada). Si Jira o Git no
están configurados, salta esa fuente sin romper el flujo.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.agents.catalog import AgentCatalogLoader
from app.agents.exceptions import AgentExecutionError
from app.agents.git_evidence_agent import GitEvidenceAgent
from app.agents.github_evidence_agent import GithubEvidenceAgent
from app.domain.models import (
    Commitment,
    CommitmentEvent,
    CommitmentRefreshChange,
    CommitmentRefreshResult,
    CommitmentState,
    EvidenceLevel,
    GitHubEvidence,
    GitHubEvidenceLevel,
    HistoryItemSummary,
    MeetingTranscript,
)
from app.services.commitment_repository import CommitmentRepository
from app.services.jira_client import JiraClientError, JiraCloudClient
from app.services.jira_sync import JiraSyncService


_STATES_OPEN_FOR_CLOSE: set[CommitmentState] = {
    "detected", "validated", "registered", "in_code_review", "evidenced"
}
_STATES_OPEN_FOR_EVIDENCE: set[CommitmentState] = {
    "detected", "validated", "registered", "in_code_review"
}
_STATES_OPEN_FOR_CODE_REVIEW: set[CommitmentState] = {
    "detected", "validated", "registered"
}
_EVIDENCE_RANK: dict[EvidenceLevel, int] = {"none": 0, "partial": 1, "sufficient": 2}
# Ranking de las señales GitHub: más alto = señal más fuerte, solo subimos.
_GITHUB_RANK: dict[GitHubEvidenceLevel, int] = {
    "none": 0,
    "in_code_review": 1,
    "merged": 2,
}


class CommitmentRefreshService:
    """Refresca un compromiso o un lote sin pasar por el pipeline de análisis."""

    def __init__(
        self,
        repository: CommitmentRepository | None = None,
        jira_client: JiraCloudClient | None = None,
        git_evidence_agent: GitEvidenceAgent | None = None,
        catalog_loader: AgentCatalogLoader | None = None,
        jira_sync: JiraSyncService | None = None,
        github_evidence_agent: GithubEvidenceAgent | None = None,
    ) -> None:
        self.repository = repository or CommitmentRepository()
        self.jira_client = jira_client or JiraCloudClient()
        self.git_evidence_agent = git_evidence_agent or GitEvidenceAgent()
        self.catalog_loader = catalog_loader or AgentCatalogLoader()
        self.jira_sync = jira_sync or JiraSyncService(jira_client=self.jira_client)
        self.github_evidence_agent = github_evidence_agent or GithubEvidenceAgent()

    def refresh(self, commitment_id: str) -> CommitmentRefreshResult:
        jira_configured = self.jira_client.is_configured()
        git_configured = self.git_evidence_agent.git_client.is_configured()
        github_configured = self.github_evidence_agent.is_configured()

        commitment = self.repository.get(commitment_id)
        if commitment is None:
            return CommitmentRefreshResult(
                commitment_id=commitment_id,
                changed=False,
                jira_configured=jira_configured,
                git_configured=git_configured,
                github_configured=github_configured,
                reason="commitment not found",
            )

        if commitment.state == "rejected":
            return CommitmentRefreshResult(
                commitment_id=commitment_id,
                changed=False,
                jira_configured=jira_configured,
                git_configured=git_configured,
                github_configured=github_configured,
                reason="rejected commitments are not refreshed",
            )

        run_id = self._build_run_id()
        changes: list[CommitmentRefreshChange] = []

        if jira_configured:
            jira_change = self._refresh_from_jira(commitment, run_id)
            if jira_change is not None:
                changes.append(jira_change)

        if git_configured:
            git_change = self._refresh_from_git(commitment, run_id)
            if git_change is not None:
                changes.append(git_change)

        if github_configured:
            github_change = self._refresh_from_github(commitment, run_id)
            if github_change is not None:
                changes.append(github_change)

        if changes:
            self.repository.update(commitment)

        return CommitmentRefreshResult(
            commitment_id=commitment_id,
            changed=bool(changes),
            jira_configured=jira_configured,
            git_configured=git_configured,
            github_configured=github_configured,
            changes=changes,
        )

    def refresh_active(self) -> list[CommitmentRefreshResult]:
        """Refresca todos los compromisos no `closed` y no `rejected`."""
        active = [
            c
            for c in self.repository.list_all()
            if c.state not in ("closed", "rejected")
        ]
        return [self.refresh(c.commitment_id) for c in active]

    def _refresh_from_jira(
        self,
        commitment: Commitment,
        run_id: str,
    ) -> CommitmentRefreshChange | None:
        if commitment.jira_created_issue is None:
            return None
        try:
            status = self.jira_client.get_issue_status(commitment.jira_created_issue.issue_key)
        except JiraClientError:
            return None
        if status is None:
            return None

        category = status.status_category_key
        now = self.repository.now_iso()

        if category == "done":
            if commitment.state not in _STATES_OPEN_FOR_CLOSE:
                return None
            previous_state = commitment.state
            commitment.state = "closed"
            commitment.timeline.append(
                CommitmentEvent(
                    event_type="closed",
                    run_id=run_id,
                    meeting_title=None,
                    meeting_date=None,
                    detail=f"Cerrado en Jira (columna: {status.status_name})",
                    recorded_at=now,
                )
            )
            return CommitmentRefreshChange(
                source="jira",
                event_type="closed",
                detail=f"Cerrado en Jira (columna: {status.status_name})",
                previous_state=previous_state,
                new_state="closed",
            )

        if category == "indeterminate":
            # Sin cambio de estado, pero el equipo está trabajando: registramos un evento informativo
            # solo si el último estado conocido no era ya un refresh con el mismo nombre de columna.
            last_event = commitment.timeline[-1] if commitment.timeline else None
            same_signal = (
                last_event is not None
                and last_event.event_type == "jira_status_refreshed"
                and (last_event.detail or "").endswith(status.status_name)
            )
            if same_signal:
                return None
            detail = f"Jira indica trabajo en curso (columna: {status.status_name})"
            commitment.timeline.append(
                CommitmentEvent(
                    event_type="jira_status_refreshed",
                    run_id=run_id,
                    meeting_title=None,
                    meeting_date=None,
                    detail=detail,
                    recorded_at=now,
                )
            )
            return CommitmentRefreshChange(
                source="jira",
                event_type="jira_status_refreshed",
                detail=detail,
                previous_state=commitment.state,
                new_state=commitment.state,
            )

        # category == "new" or unknown: no hace nada (silencio).
        return None

    def _refresh_from_git(
        self,
        commitment: Commitment,
        run_id: str,
    ) -> CommitmentRefreshChange | None:
        if commitment.item_type not in ("task", "ambiguous_task"):
            return None
        catalog = self.catalog_loader.load()
        definition = next(
            (a for a in catalog.agents if a.agent_kind == "git_evidence" and a.enabled),
            None,
        )
        if definition is None:
            return None

        synthetic_history = [
            HistoryItemSummary(
                run_id=commitment.origin.source_run_id,
                meeting_title=commitment.origin.meeting_title,
                meeting_date=commitment.origin.meeting_date,
                item_type=commitment.item_type,
                title=commitment.title,
                validation_status=self._derived_validation(commitment),
                jira_issue_key=(
                    commitment.jira_created_issue.issue_key
                    if commitment.jira_created_issue
                    else None
                ),
                commitment_id=commitment.commitment_id,
            )
        ]
        synthetic_transcript = MeetingTranscript(
            id=f"refresh-placeholder-{commitment.commitment_id}",
            title="Refresh ad-hoc",
            provider="refresh",
        )

        try:
            updates, _run = self.git_evidence_agent.run(
                synthetic_transcript, synthetic_history, definition
            )
        except AgentExecutionError:
            return None

        if not updates:
            return None
        update = updates[0]
        new_evidence = update.evidence
        previous_evidence = commitment.git_evidence

        previous_rank = _EVIDENCE_RANK.get(
            previous_evidence.evidence_level if previous_evidence else "none", 0
        )
        new_rank = _EVIDENCE_RANK.get(new_evidence.evidence_level, 0)
        if new_rank <= previous_rank:
            return None  # No degradar ni reescribir sin mejora.

        now = self.repository.now_iso()
        commitment.git_evidence = new_evidence
        commitment.timeline.append(
            CommitmentEvent(
                event_type="git_evidence_updated",
                run_id=run_id,
                meeting_title=None,
                meeting_date=None,
                detail=new_evidence.explanation,
                recorded_at=now,
            )
        )

        previous_state = commitment.state
        new_state: CommitmentState | None = None
        if (
            new_evidence.evidence_level == "sufficient"
            and commitment.state in _STATES_OPEN_FOR_EVIDENCE
        ):
            commitment.state = "evidenced"
            new_state = "evidenced"
            sync_result = self.jira_sync.push_state_change(commitment)
            if sync_result.outcome == "failed":
                commitment.timeline.append(
                    CommitmentEvent(
                        event_type="jira_sync_failed",
                        run_id=run_id,
                        meeting_title=None,
                        meeting_date=None,
                        detail=sync_result.detail,
                        recorded_at=now,
                    )
                )

        return CommitmentRefreshChange(
            source="git",
            event_type="git_evidence_updated",
            detail=new_evidence.explanation,
            previous_state=previous_state,
            new_state=new_state,
        )

    def _refresh_from_github(
        self,
        commitment: Commitment,
        run_id: str,
    ) -> CommitmentRefreshChange | None:
        """Consulta GitHub para PRs abiertos / mergeados / commits que
        referencien el compromiso (D023). Aplica transiciones monótonas:
        - ``merged`` → mueve a ``evidenced`` si todavía no lo está; dispara
          el sync con Jira para alinear estado (paralelo a lo que hace Git).
        - ``in_code_review`` → mueve a ``in_code_review`` si el lifecycle
          aún no ha pasado de ``registered``.
        - ``none`` → no toca el lifecycle aunque actualice la lista de
          commits, porque la ausencia de PRs no es una señal positiva.
        Nunca degrada un nivel ya alcanzado (`_GITHUB_RANK`)."""
        if commitment.item_type not in ("task", "ambiguous_task"):
            return None

        try:
            new_evidence = self.github_evidence_agent.evaluate(commitment)
        except Exception:  # pragma: no cover - defensive
            return None
        if new_evidence is None:
            return None

        previous_evidence: GitHubEvidence | None = commitment.github_evidence
        previous_rank = _GITHUB_RANK.get(
            previous_evidence.evidence_level if previous_evidence else "none", 0
        )
        new_rank = _GITHUB_RANK.get(new_evidence.evidence_level, 0)
        # Solo aceptamos subidas. Una bajada (un PR que se cerró sin merge)
        # se ignora para no perder la traza histórica.
        if new_rank < previous_rank:
            return None
        # Si el nivel es el mismo y la lista de PRs/commits no cambia,
        # no merece la pena escribir nada.
        if new_rank == previous_rank and self._github_payload_equal(
            previous_evidence, new_evidence
        ):
            return None

        now = self.repository.now_iso()
        commitment.github_evidence = new_evidence
        commitment.timeline.append(
            CommitmentEvent(
                event_type="github_evidence_updated",
                run_id=run_id,
                meeting_title=None,
                meeting_date=None,
                detail=new_evidence.explanation,
                recorded_at=now,
            )
        )

        previous_state = commitment.state
        new_state: CommitmentState | None = None

        if (
            new_evidence.evidence_level == "merged"
            and commitment.state in _STATES_OPEN_FOR_EVIDENCE
        ):
            commitment.state = "evidenced"
            new_state = "evidenced"
            sync_result = self.jira_sync.push_state_change(commitment)
            if sync_result.outcome == "failed":
                commitment.timeline.append(
                    CommitmentEvent(
                        event_type="jira_sync_failed",
                        run_id=run_id,
                        meeting_title=None,
                        meeting_date=None,
                        detail=sync_result.detail,
                        recorded_at=now,
                    )
                )
        elif (
            new_evidence.evidence_level == "in_code_review"
            and commitment.state in _STATES_OPEN_FOR_CODE_REVIEW
        ):
            commitment.state = "in_code_review"
            new_state = "in_code_review"

        return CommitmentRefreshChange(
            source="github",
            event_type="github_evidence_updated",
            detail=new_evidence.explanation,
            previous_state=previous_state,
            new_state=new_state,
        )

    @staticmethod
    def _github_payload_equal(
        a: GitHubEvidence | None, b: GitHubEvidence | None
    ) -> bool:
        if a is None or b is None:
            return False
        return (
            [p.number for p in a.pull_requests_open]
            == [p.number for p in b.pull_requests_open]
            and [p.number for p in a.pull_requests_merged]
            == [p.number for p in b.pull_requests_merged]
            and [c.sha for c in a.supporting_commits]
            == [c.sha for c in b.supporting_commits]
        )

    @staticmethod
    def _build_run_id() -> str:
        return f"refresh-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"

    @staticmethod
    def _derived_validation(commitment: Commitment):
        if commitment.state == "rejected":
            return "rejected"
        if commitment.state in ("validated", "registered", "evidenced", "closed"):
            return "approved"
        return "pending_review"
