"""Sincronización automática del estado del compromiso al issue Jira (Decisión 015).

Cuando el estado de un compromiso cambia localmente (verbal_close, evidencia Git suficiente,
rechazo manual), este servicio propaga la transición correspondiente al issue Jira vinculado.
Es la mitad app → Jira de la sincronización bidireccional; la mitad Jira → app vive en
`CommitmentRefreshService` (Decisión 014).

Mapeo:
  - `closed`    → transición a destino con `statusCategory == "done"`.
  - `evidenced` → transición a `indeterminate` preferentemente cuyo nombre menciona "review"
                  o "revisión"; fallback al primer `indeterminate` disponible.
  - `rejected`  → no mueve columna; añade label `rechazado-en-fuente` para marcar visualmente.
  - Otros estados (detected, validated, registered) no propagan porque el issue Jira nace en
    `statusCategory == "new"` al crearse desde la app, lo que ya corresponde conceptualmente.

Degradación elegante: si Jira no está configurado o falla la llamada, devuelve un
`JiraSyncResult` con `outcome="not_configured"` o `"failed"` sin propagar la excepción.
"""

from __future__ import annotations

import logging

from app.domain.models import Commitment, CommitmentState, JiraSyncResult
from app.services.jira_client import JiraClientError, JiraCloudClient, JiraTransition


_logger = logging.getLogger(__name__)

REJECTED_LABEL = "rechazado-en-fuente"
_REVIEW_HINTS = ("review", "revision", "revisi")


class JiraSyncService:
    def __init__(self, jira_client: JiraCloudClient | None = None) -> None:
        self.jira_client = jira_client or JiraCloudClient()

    def push_state_change(self, commitment: Commitment) -> JiraSyncResult:
        """Propaga el estado actual del compromiso al issue Jira si procede."""
        if not self.jira_client.is_configured():
            return JiraSyncResult(
                commitment_id=commitment.commitment_id,
                outcome="not_configured",
                detail="Jira no está configurado",
            )
        if commitment.jira_created_issue is None:
            return JiraSyncResult(
                commitment_id=commitment.commitment_id,
                outcome="no_issue",
                detail="El compromiso no tiene issue Jira vinculado",
            )

        issue_key = commitment.jira_created_issue.issue_key

        if commitment.state == "rejected":
            return self._apply_rejected_label(commitment.commitment_id, issue_key)

        target_category = self._target_category(commitment.state)
        if target_category is None:
            return JiraSyncResult(
                commitment_id=commitment.commitment_id,
                outcome="skipped",
                issue_key=issue_key,
                detail=f"Estado {commitment.state} no propaga a Jira",
            )

        try:
            transitions = self.jira_client.list_transitions(issue_key)
        except JiraClientError as exc:
            _logger.warning("Jira list_transitions failed for %s: %s", issue_key, exc)
            return JiraSyncResult(
                commitment_id=commitment.commitment_id,
                outcome="failed",
                issue_key=issue_key,
                detail=f"list_transitions: {exc}",
            )

        chosen = self._pick_transition(transitions, target_category, commitment.state)
        if chosen is None:
            return JiraSyncResult(
                commitment_id=commitment.commitment_id,
                outcome="skipped",
                issue_key=issue_key,
                detail=f"Sin transición disponible para categoría {target_category}",
            )

        try:
            self.jira_client.transition_issue(issue_key, chosen.id)
        except JiraClientError as exc:
            _logger.warning("Jira transition_issue failed for %s -> %s: %s", issue_key, chosen.name, exc)
            return JiraSyncResult(
                commitment_id=commitment.commitment_id,
                outcome="failed",
                issue_key=issue_key,
                target_status_name=chosen.to_status_name,
                detail=f"transition_issue: {exc}",
            )

        return JiraSyncResult(
            commitment_id=commitment.commitment_id,
            outcome="transitioned",
            issue_key=issue_key,
            target_status_name=chosen.to_status_name,
            detail=f"Movido a '{chosen.to_status_name}' (transición '{chosen.name}')",
        )

    def _apply_rejected_label(self, commitment_id: str, issue_key: str) -> JiraSyncResult:
        try:
            self.jira_client.add_label(issue_key, REJECTED_LABEL)
        except JiraClientError as exc:
            _logger.warning("Jira add_label failed for %s: %s", issue_key, exc)
            return JiraSyncResult(
                commitment_id=commitment_id,
                outcome="failed",
                issue_key=issue_key,
                detail=f"add_label: {exc}",
            )
        return JiraSyncResult(
            commitment_id=commitment_id,
            outcome="labelled",
            issue_key=issue_key,
            label_applied=REJECTED_LABEL,
            detail=f"Etiqueta '{REJECTED_LABEL}' añadida al issue",
        )

    @staticmethod
    def _target_category(state: CommitmentState) -> str | None:
        if state == "closed":
            return "done"
        if state == "evidenced":
            return "indeterminate"
        return None

    @staticmethod
    def _pick_transition(
        transitions: list[JiraTransition],
        target_category: str,
        commitment_state: CommitmentState,
    ) -> JiraTransition | None:
        candidates = [t for t in transitions if t.to_status_category_key == target_category]
        if not candidates:
            return None
        if commitment_state == "evidenced":
            for t in candidates:
                lowered = (t.name + " " + t.to_status_name).lower()
                if any(hint in lowered for hint in _REVIEW_HINTS):
                    return t
        return candidates[0]
