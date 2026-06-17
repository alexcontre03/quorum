"""Servicio que sincroniza un AnalysisResult con la capa de compromisos.

Convierte items detectados (task / ambiguous_task) en compromisos persistidos y los
enlaza con compromisos existentes entre reuniones, usando dos señales:

1. La salida del task_followup_agent (followup_updates), que dice qué títulos del
   historial están siendo retomados/cambiados en la reunión nueva.
2. Como red de seguridad, similitud de título entre el item detectado y los items
   de la historia que enviamos al agente.

El servicio muta el AnalysisResult para fijar `commitment_id` en cada item, y
crea/actualiza los ficheros del repositorio de compromisos.
"""

from difflib import SequenceMatcher
import re
import unicodedata

from app.domain.models import (
    AnalysisResult,
    Commitment,
    CommitmentEvent,
    CommitmentOrigin,
    CommitmentState,
    DetectedItem,
    FollowupUpdate,
    GitEvidenceUpdate,
    HistoryItemSummary,
    MeetingTranscript,
)
from app.services.commitment_repository import CommitmentRepository
from app.services.jira_client import JiraClientError, JiraCloudClient
from app.services.jira_sync import JiraSyncService


_COMMITTABLE_TYPES = {"task", "ambiguous_task"}
_FALLBACK_SIMILARITY_THRESHOLD = 0.75
_BLOCKER_LABEL = "bloqueado-trazabilidad"


class CommitmentSyncService:
    def __init__(
        self,
        repository: CommitmentRepository | None = None,
        jira_sync: JiraSyncService | None = None,
    ) -> None:
        self.repository = repository or CommitmentRepository()
        self.jira_sync = jira_sync or JiraSyncService()

    def _push_to_jira(self, commitment: Commitment, run_id: str) -> None:
        """Propaga el estado actual al issue Jira (Decisión 015). Silencioso si Jira degrada."""
        result = self.jira_sync.push_state_change(commitment)
        if result.outcome == "failed":
            now = self.repository.now_iso()
            commitment.timeline.append(
                CommitmentEvent(
                    event_type="jira_sync_failed",
                    run_id=run_id,
                    meeting_title=None,
                    meeting_date=None,
                    detail=result.detail,
                    recorded_at=now,
                )
            )

    def sync_from_analysis(
        self,
        transcript: MeetingTranscript,
        analysis: AnalysisResult,
        run_id: str,
        history: list[HistoryItemSummary],
    ) -> None:
        """Sincroniza el análisis con la capa de compromisos. Idempotente por `run_id` (Decisión 009).

        Si este `run_id` ya tiene compromisos asociados (re-análisis de la misma reunión), los usa
        como **priors** y los prefiere al matchear ítems del nuevo análisis antes de caer al
        historial general. Nunca borra compromisos existentes — el estado del usuario (validación,
        creación en Jira, timeline) se preserva. Los priors que ningún ítem nuevo enlace quedan
        vivos sin reflejo en el run actual.
        """
        history_by_norm_title = {
            self._normalize(h.title): h for h in history if h.commitment_id
        }
        priors_by_norm_title = {
            self._normalize(c.title): c
            for c in self.repository.list_all()
            if c.origin.source_run_id == run_id
        }

        self._apply_git_evidence_updates(
            analysis.git_evidence_updates, transcript, run_id
        )

        matched_index_to_commitment_id = self._apply_followup_updates(
            analysis.followup_updates,
            history_by_norm_title,
            transcript,
            run_id,
        )

        for index, item in enumerate(analysis.items):
            if item.item_type not in _COMMITTABLE_TYPES:
                continue
            if item.commitment_id:
                continue

            # Orden de preferencia: 1) match explícito vía follow-up; 2) prior de este run;
            # 3) historial general; 4) creación nueva.
            commitment_id = matched_index_to_commitment_id.get(index)
            if commitment_id is None:
                commitment_id = self._best_effort_match_priors(item, priors_by_norm_title)
            if commitment_id is None:
                commitment_id = self._best_effort_match(item, history_by_norm_title)

            if commitment_id is not None:
                item.commitment_id = commitment_id
                continue

            commitment = self._create_commitment_from_item(transcript, run_id, item)
            self.repository.create(commitment)
            item.commitment_id = commitment.commitment_id

    def _best_effort_match_priors(
        self,
        item: DetectedItem,
        priors_by_norm_title: dict[str, Commitment],
    ) -> str | None:
        """Match por similitud contra los compromisos del propio run (re-análisis idempotente)."""
        if not priors_by_norm_title:
            return None
        item_norm = self._normalize(item.title)
        if not item_norm:
            return None
        best_ratio = 0.0
        best_id: str | None = None
        for norm_title, commitment in priors_by_norm_title.items():
            ratio = SequenceMatcher(None, item_norm, norm_title).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_id = commitment.commitment_id
        if best_ratio >= _FALLBACK_SIMILARITY_THRESHOLD:
            return best_id
        return None

    def _apply_git_evidence_updates(
        self,
        updates: list[GitEvidenceUpdate],
        transcript: MeetingTranscript,
        run_id: str,
    ) -> None:
        now = self.repository.now_iso()
        for update in updates:
            commitment = self.repository.get(update.commitment_id)
            if commitment is None:
                continue
            commitment.git_evidence = update.evidence
            commitment.timeline.append(
                CommitmentEvent(
                    event_type="git_evidence_updated",
                    run_id=run_id,
                    meeting_title=transcript.title,
                    meeting_date=transcript.meeting_date,
                    detail=update.evidence.explanation,
                    recorded_at=now,
                )
            )
            promoted_to_evidenced = False
            if (
                update.evidence.evidence_level == "sufficient"
                and commitment.state in ("detected", "validated", "registered")
            ):
                commitment.state = "evidenced"
                promoted_to_evidenced = True
            if promoted_to_evidenced:
                self._push_to_jira(commitment, run_id)
            self.repository.update(commitment)

    def _apply_followup_updates(
        self,
        followups: list[FollowupUpdate],
        history_by_norm_title: dict[str, HistoryItemSummary],
        transcript: MeetingTranscript,
        run_id: str,
    ) -> dict[int, str]:
        matched: dict[int, str] = {}
        now = self.repository.now_iso()

        for f in followups:
            # Fuzzy match para tolerar parafraseos / traducciones del LLM en `matched_history_title`.
            # El exact match es ideal pero modelos como gemma3:4b a veces re-formulan en lugar de copiar literal.
            history_entry = self._resolve_history_entry(f.matched_history_title, history_by_norm_title)
            if history_entry is None or history_entry.commitment_id is None:
                continue
            commitment = self.repository.get(history_entry.commitment_id)
            if commitment is None:
                continue

            if (
                f.matched_new_item_index is not None
                and f.matched_new_item_index >= 0
            ):
                matched[f.matched_new_item_index] = commitment.commitment_id

            # Para `scope_change` con renombrado real y `verbal_close` con
            # cierre real emitimos UN evento especifico (mas informativo) en
            # vez del generico `followup`. Asi la timeline no tiene dos cards
            # consecutivas con la misma cita. Para los demas tipos (bloqueos,
            # duplicados, recurring, contradiccion) el `followup` SI se emite
            # porque no tienen un evento mas concreto que los represente.
            emitted_specific = False

            if f.followup_type == "scope_change" and (f.new_title or f.new_summary):
                previous_title = commitment.title
                if f.new_title:
                    commitment.title = f.new_title
                if f.new_summary:
                    commitment.summary = f.new_summary
                commitment.timeline.append(
                    CommitmentEvent(
                        event_type="scope_changed",
                        run_id=run_id,
                        meeting_title=transcript.title,
                        meeting_date=transcript.meeting_date,
                        detail=f.explanation,
                        recorded_at=now,
                        previous_title=previous_title,
                        new_title=commitment.title,
                        trigger_quote=f.trigger_quote,
                        followup_type=f.followup_type,
                    )
                )
                emitted_specific = True
                self._sync_scope_to_jira(commitment, run_id, transcript)
            elif f.followup_type == "verbal_close" and commitment.state != "closed":
                commitment.state = "closed"
                commitment.timeline.append(
                    CommitmentEvent(
                        event_type="closed",
                        run_id=run_id,
                        meeting_title=transcript.title,
                        meeting_date=transcript.meeting_date,
                        detail=f.explanation or "Cierre verbal en esta reunion",
                        recorded_at=now,
                        trigger_quote=f.trigger_quote,
                        followup_type=f.followup_type,
                    )
                )
                emitted_specific = True
                self._push_to_jira(commitment, run_id)

            if not emitted_specific:
                commitment.timeline.append(
                    CommitmentEvent(
                        event_type="followup",
                        run_id=run_id,
                        meeting_title=transcript.title,
                        meeting_date=transcript.meeting_date,
                        detail=f.explanation,
                        recorded_at=now,
                        followup_type=f.followup_type,
                        trigger_quote=f.trigger_quote,
                    )
                )
                if f.followup_type == "new_blocker":
                    self._sync_blocker_label(commitment, run_id, transcript, present=True)
                elif f.followup_type == "blocker_resolved":
                    self._sync_blocker_label(commitment, run_id, transcript, present=False)

            self.repository.update(commitment)

        return matched

    def _sync_scope_to_jira(
        self,
        commitment: Commitment,
        run_id: str,
        transcript: MeetingTranscript,
    ) -> None:
        """Tras un `scope_change` con renombrado real, propaga título y resumen
        al issue Jira (si existe). Silencioso si Jira no está configurado o el
        compromiso no tiene issue creado. Registra el resultado en la timeline
        para que el usuario sepa que el tablero ya está alineado."""
        if commitment.jira_created_issue is None:
            return
        jira = self.jira_sync.jira_client
        if not jira.is_configured():
            return
        issue_key = commitment.jira_created_issue.issue_key
        now = self.repository.now_iso()
        try:
            jira.update_summary_and_description(
                issue_key, commitment.title, commitment.summary
            )
        except JiraClientError as exc:
            commitment.timeline.append(
                CommitmentEvent(
                    event_type="jira_sync_failed",
                    run_id=run_id,
                    meeting_title=transcript.title,
                    meeting_date=transcript.meeting_date,
                    detail=f"No se pudo actualizar {issue_key}: {exc}",
                    recorded_at=now,
                )
            )
            return
        commitment.timeline.append(
            CommitmentEvent(
                event_type="jira_scope_synced",
                run_id=run_id,
                meeting_title=transcript.title,
                meeting_date=transcript.meeting_date,
                detail=f"{issue_key} actualizado con el nuevo título",
                recorded_at=now,
            )
        )

    def _sync_blocker_label(
        self,
        commitment: Commitment,
        run_id: str,
        transcript: MeetingTranscript,
        *,
        present: bool,
    ) -> None:
        """Añade o quita la etiqueta `bloqueado-trazabilidad` en el issue Jira
        del compromiso. Idempotente: Jira ignora un add sobre una label
        existente y un remove sobre una inexistente. Si Jira no está
        configurado o no hay issue, la operación se omite silenciosamente."""
        if commitment.jira_created_issue is None:
            return
        jira = self.jira_sync.jira_client
        if not jira.is_configured():
            return
        issue_key = commitment.jira_created_issue.issue_key
        now = self.repository.now_iso()
        try:
            if present:
                jira.add_label(issue_key, _BLOCKER_LABEL)
            else:
                jira.remove_label(issue_key, _BLOCKER_LABEL)
        except JiraClientError as exc:
            commitment.timeline.append(
                CommitmentEvent(
                    event_type="jira_sync_failed",
                    run_id=run_id,
                    meeting_title=transcript.title,
                    meeting_date=transcript.meeting_date,
                    detail=f"No se pudo {'añadir' if present else 'quitar'} label en {issue_key}: {exc}",
                    recorded_at=now,
                )
            )
            return
        commitment.timeline.append(
            CommitmentEvent(
                event_type="jira_blocker_labeled" if present else "jira_blocker_cleared",
                run_id=run_id,
                meeting_title=transcript.title,
                meeting_date=transcript.meeting_date,
                detail=(
                    f"Etiqueta `{_BLOCKER_LABEL}` añadida a {issue_key}"
                    if present
                    else f"Etiqueta `{_BLOCKER_LABEL}` retirada de {issue_key}"
                ),
                recorded_at=now,
            )
        )

    def _resolve_history_entry(
        self,
        proposed_match: str,
        history_by_norm_title: dict[str, HistoryItemSummary],
    ) -> HistoryItemSummary | None:
        """Resuelve un `matched_history_title` propuesto por el LLM al item del historial real.

        Intenta exact match primero, luego fuzzy match con `SequenceMatcher`. Umbral más bajo que
        el del fallback porque el LLM ya ha hecho la asociación semántica, solo le pedimos confirmar
        el match a través del fuzzy.
        """
        if not proposed_match:
            return None
        norm = self._normalize(proposed_match)
        if not norm:
            return None
        exact = history_by_norm_title.get(norm)
        if exact is not None:
            return exact
        best_ratio = 0.0
        best_entry: HistoryItemSummary | None = None
        for hist_norm, entry in history_by_norm_title.items():
            ratio = SequenceMatcher(None, norm, hist_norm).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_entry = entry
        if best_ratio >= 0.45:
            return best_entry
        return None

    def _best_effort_match(
        self,
        item: DetectedItem,
        history_by_norm_title: dict[str, HistoryItemSummary],
    ) -> str | None:
        if not history_by_norm_title:
            return None
        item_norm = self._normalize(item.title)
        if not item_norm:
            return None

        best_ratio = 0.0
        best_id: str | None = None
        for norm_title, entry in history_by_norm_title.items():
            ratio = SequenceMatcher(None, item_norm, norm_title).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_id = entry.commitment_id
        if best_ratio >= _FALLBACK_SIMILARITY_THRESHOLD:
            return best_id
        return None

    def _create_commitment_from_item(
        self,
        transcript: MeetingTranscript,
        run_id: str,
        item: DetectedItem,
    ) -> Commitment:
        now = self.repository.now_iso()
        commitment_id = self.repository.new_commitment_id()
        state: CommitmentState = "detected"
        segment_index = self._locate_segment_index(transcript, item)
        return Commitment(
            commitment_id=commitment_id,
            title=item.title,
            summary=item.summary,
            item_type=item.item_type,
            state=state,
            origin=CommitmentOrigin(
                source_run_id=run_id,
                transcript_id=transcript.id,
                meeting_title=transcript.title,
                meeting_date=transcript.meeting_date,
                sprint_id=transcript.sprint_id,
                segment_index=segment_index,
                speaker=item.speaker,
                timestamp=item.timestamp,
                evidence=item.evidence,
            ),
            timeline=[
                CommitmentEvent(
                    event_type="detected",
                    run_id=run_id,
                    meeting_title=transcript.title,
                    meeting_date=transcript.meeting_date,
                    detail=item.evidence or "Detectado en esta reunion",
                    recorded_at=now,
                )
            ],
            created_at=now,
            updated_at=now,
        )

    @staticmethod
    def _locate_segment_index(transcript: MeetingTranscript, item: DetectedItem) -> int | None:
        """Localiza el segmento de la transcripción que corresponde a la cita del item.

        Estrategia: (1) match exacto por `timestamp + speaker`; (2) match por `timestamp`;
        (3) similitud de texto entre `item.evidence` y `segment.text`. Devuelve None si nada supera
        un umbral mínimo (caso raro: items que el LLM ha sintetizado sin segmento concreto).
        """
        segments = transcript.segments
        if not segments:
            return None

        if item.timestamp:
            for i, seg in enumerate(segments):
                if seg.timestamp == item.timestamp and seg.speaker == item.speaker:
                    return i
            for i, seg in enumerate(segments):
                if seg.timestamp == item.timestamp:
                    return i

        if item.evidence:
            evidence_norm = CommitmentSyncService._normalize(item.evidence)
            best_ratio = 0.0
            best_idx: int | None = None
            for i, seg in enumerate(segments):
                ratio = SequenceMatcher(
                    None, evidence_norm, CommitmentSyncService._normalize(seg.text)
                ).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_idx = i
            if best_ratio >= 0.4:
                return best_idx

        return None

    @staticmethod
    def _normalize(text: str) -> str:
        if not text:
            return ""
        normalized = unicodedata.normalize("NFKD", text)
        ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
        ascii_text = ascii_text.lower()
        ascii_text = re.sub(r"[^a-z0-9\s]", " ", ascii_text)
        ascii_text = re.sub(r"\s+", " ", ascii_text).strip()
        return ascii_text
