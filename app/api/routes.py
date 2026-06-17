import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.agents.exceptions import AgentExecutionError
from app.agents.orchestrator import MeetingAnalysisOrchestrator
from app.config.runtime_settings import get_github_settings, get_jira_settings
from app.domain.models import (
    CommitmentEvent,
    JiraCreatedIssue,
    QARequest,
    RawTranscriptPayload,
    RetrievalMode,
    ValidationStatus,
)
from app.services.analysis_run_repository import AnalysisRunRepository
from app.services.commitment_refresh import CommitmentRefreshService
from app.services.commitment_repository import CommitmentRepository
from app.services.commitment_sync import CommitmentSyncService
from app.services.dataset_evaluation import DatasetEvaluationService
from app.services.evaluation_run_repository import EvaluationRunRepository
from app.services.followup_evaluation import FollowupEvaluationService
from app.services.followup_evaluation_run_repository import FollowupEvaluationRunRepository
from app.services.jira_client import JiraClientError, JiraCloudClient
from app.services.jira_sync import JiraSyncService
from app.services.manual_parser import ManualTranscriptParser
from app.services.qa_service import QAService
from app.services.runtime_profile import (
    ALLOWED_PROFILES,
    DEFAULT_PROFILE,
    get_runtime_profile,
    get_settings_snapshot,
    set_chat_model,
    set_runtime_profile,
)
from app.services.transcript_repository import TranscriptRepository


class ValidationPatch(BaseModel):
    validation_status: ValidationStatus


class RuntimeProfileBody(BaseModel):
    profile: str


class ChatModelBody(BaseModel):
    profile: str
    model: str | None

router = APIRouter(prefix="/api", tags=["meeting-lab"])

repository = TranscriptRepository()
runs_repository = AnalysisRunRepository()
evaluation_runs_repository = EvaluationRunRepository()
commitment_repository = CommitmentRepository()
commitment_sync = CommitmentSyncService(repository=commitment_repository)
parser = ManualTranscriptParser()
orchestrator = MeetingAnalysisOrchestrator()
evaluation_service = DatasetEvaluationService(orchestrator=orchestrator)
followup_evaluation_service = FollowupEvaluationService(orchestrator=orchestrator)
followup_evaluation_runs_repository = FollowupEvaluationRunRepository()
qa_service = QAService(
    transcript_repository=repository,
    transcript_retriever=orchestrator.retriever,
)
jira_sync_service = JiraSyncService()
commitment_refresh_service = CommitmentRefreshService(
    repository=commitment_repository, jira_sync=jira_sync_service
)


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/settings/runtime-profile")
def read_runtime_profile() -> dict[str, object]:
    """Return the full runtime settings snapshot the UI needs to render the
    toggle and the model dropdown: active profile, per-profile model
    override, allowed values, defaults and the catalogue of known models."""
    return get_settings_snapshot()


@router.put("/settings/runtime-profile")
def update_runtime_profile(body: RuntimeProfileBody) -> dict[str, object]:
    """Persist the new runtime profile. Takes effect on the next analysis
    because the client factory reads the setting at request time."""
    try:
        set_runtime_profile(body.profile)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return get_settings_snapshot()


@router.put("/settings/chat-model")
def update_chat_model(body: ChatModelBody) -> dict[str, object]:
    """Persist the chat model override for *body.profile*. Pass ``model=None``
    to clear the override and fall back to the default (which, for ``local``,
    is the per-agent assignment of agents.json)."""
    try:
        set_chat_model(body.profile, body.model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return get_settings_snapshot()


@router.get("/transcripts")
def list_transcripts() -> list[dict]:
    return repository.list_summaries()


@router.get("/sprints")
def list_sprints() -> list[dict]:
    """Lista los sprints derivados de las transcripciones del dataset (Decisión 011).

    Cada entrada: `{sprint_id, transcript_ids, transcript_count, meeting_dates}`. Los sprints se
    derivan del campo `sprint_id` de cada transcripción; no hay una entidad `Sprint` separada.
    Transcripciones sin sprint quedan agrupadas bajo `null`.
    """
    return repository.list_sprints()


@router.get("/agents")
def list_agents() -> dict:
    return orchestrator.describe()


@router.get("/jira/config")
def get_jira_config() -> dict:
    settings = get_jira_settings()
    return settings.public_payload()


@router.get("/github/config")
def get_github_config() -> dict:
    """Devuelve el estado de la integración GitHub (D023). El cliente solo
    ve si está configurado y la coordenada ``owner/repo``; el token nunca
    sale del backend."""
    settings = get_github_settings()
    return settings.public_payload()


# ===== Demo reset =====

class DemoResetBody(BaseModel):
    """Body opcional de ``POST /api/demo/reset``. Permite incluir el audit
    log del Q&A (D022) en el barrido o dejarlo intacto si quieres conservar
    las preguntas de pruebas anteriores."""
    wipe_audit: bool = False


class DemoJiraCleanupBody(BaseModel):
    dry_run: bool = True


@router.post("/demo/reset")
def post_demo_reset(body: DemoResetBody | None = None) -> dict:
    """Borra los datos derivados de la app (runs, compromisos, índices,
    evaluaciones) para empezar la demo desde cero. Conserva el dataset de
    transcripciones y las credenciales. No toca Jira ni GitHub."""
    from app.services.demo_reset import perform_reset

    payload = body or DemoResetBody()
    summary = perform_reset(wipe_audit=payload.wipe_audit)
    return {
        "deleted": summary,
        "total": sum(summary.values()),
        "wiped_audit": payload.wipe_audit,
    }


@router.post("/demo/cleanup-jira")
def post_demo_cleanup_jira(body: DemoJiraCleanupBody | None = None) -> dict:
    """Cierra los issues de Jira que el sistema creó durante la demo. Por
    defecto ``dry_run=true``: solo lista qué cerraría sin contactar Jira.
    Para ejecutar realmente, pasa ``{"dry_run": false}``."""
    from app.services.demo_reset import cleanup_jira_created_issues

    payload = body or DemoJiraCleanupBody()
    return cleanup_jira_created_issues(dry_run=payload.dry_run)


@router.get("/runs")
def list_runs(limit: int = 20) -> list[dict]:
    normalized_limit = max(1, min(limit, 50))
    return runs_repository.list_summaries(limit=normalized_limit)


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict:
    record = runs_repository.get_run(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return record.model_dump(mode="json")


@router.get("/commitments")
def list_commitments(limit: int = 50, sprint_id: str | None = None) -> list[dict]:
    """Lista los compromisos completos, opcionalmente filtrados por sprint (Decisión 011)."""
    normalized_limit = max(1, min(limit, 100))
    commitments = sorted(
        commitment_repository.list_all(),
        key=lambda c: c.updated_at,
        reverse=True,
    )
    if sprint_id is not None:
        commitments = [c for c in commitments if c.origin.sprint_id == sprint_id]
    return [c.model_dump(mode="json") for c in commitments[:normalized_limit]]


@router.get("/commitments/{commitment_id}")
def get_commitment(commitment_id: str) -> dict:
    commitment = commitment_repository.get(commitment_id)
    if commitment is None:
        raise HTTPException(status_code=404, detail="Commitment not found")
    return commitment.model_dump(mode="json")


@router.post("/commitments/{commitment_id}/refresh")
def refresh_commitment(commitment_id: str) -> dict:
    """Refresca el estado del compromiso consultando Jira y Git (Decisión 014).

    Devuelve el resumen de cambios aplicados y el compromiso actualizado. Si Jira o Git no están
    configurados, el resumen lo declara explícitamente.
    """
    result = commitment_refresh_service.refresh(commitment_id)
    if result.reason == "commitment not found":
        raise HTTPException(status_code=404, detail="Commitment not found")
    commitment = commitment_repository.get(commitment_id)
    payload = {"refresh": result.model_dump(mode="json")}
    if commitment is not None:
        payload["commitment"] = commitment.model_dump(mode="json")
    return payload


@router.post("/commitments/{commitment_id}/dismiss-duplicate")
def dismiss_duplicate(commitment_id: str) -> dict:
    """Marca el flag de `possible_duplicate` como descartado por el usuario.

    El usuario afirma que el agente se equivocó y son compromisos distintos.
    Añadimos un evento `duplicate_dismissed` a la timeline; la UI lo lee para
    dejar de mostrar el badge "Posible duplicado" en la lista y en el detalle.
    No tocamos ni Jira ni GitHub: es una decisión interna del usuario.
    """
    from datetime import datetime, timezone

    from app.domain.models import CommitmentEvent

    commitment = commitment_repository.get(commitment_id)
    if commitment is None:
        raise HTTPException(status_code=404, detail="Commitment not found")
    has_active_duplicate = False
    for ev in reversed(commitment.timeline):
        if ev.event_type == "duplicate_dismissed":
            break
        if ev.event_type == "followup" and ev.followup_type == "possible_duplicate":
            has_active_duplicate = True
            break
    if not has_active_duplicate:
        return {"commitment": commitment.model_dump(mode="json"), "changed": False}
    commitment.timeline.append(
        CommitmentEvent(
            event_type="duplicate_dismissed",
            recorded_at=datetime.now(timezone.utc).isoformat(),
            detail="El usuario descarta el aviso de duplicado",
        )
    )
    commitment_repository.update(commitment)
    return {"commitment": commitment.model_dump(mode="json"), "changed": True}


@router.post("/commitments/refresh-all")
def refresh_all_commitments() -> dict:
    """Refresca todos los compromisos activos (no closed, no rejected) (Decisión 014)."""
    results = commitment_refresh_service.refresh_active()
    changed = sum(1 for r in results if r.changed)
    return {
        "refreshed": len(results),
        "changed": changed,
        "per_commitment": [r.model_dump(mode="json") for r in results],
    }


@router.get("/evaluations")
def list_evaluations(limit: int = 20) -> list[dict]:
    normalized_limit = max(1, min(limit, 50))
    return evaluation_runs_repository.list_summaries(limit=normalized_limit)


@router.get("/evaluations/{evaluation_id}")
def get_evaluation(evaluation_id: str) -> dict:
    record = evaluation_runs_repository.get_evaluation(evaluation_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    return record.model_dump(mode="json")


@router.post("/evaluations")
def run_dataset_evaluation() -> dict:
    transcripts = repository.list_transcripts()
    if not transcripts:
        raise HTTPException(status_code=400, detail="No transcripts available for evaluation")

    try:
        evaluation = evaluation_service.evaluate_dataset(transcripts)
    except AgentExecutionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    saved_evaluation = evaluation_runs_repository.save(evaluation)
    return {"evaluation": saved_evaluation.model_dump(mode="json")}


@router.get("/followup-evaluations")
def list_followup_evaluations(limit: int = 20) -> list[dict]:
    normalized_limit = max(1, min(limit, 50))
    return followup_evaluation_runs_repository.list_summaries(limit=normalized_limit)


@router.get("/followup-evaluations/{evaluation_id}")
def get_followup_evaluation(evaluation_id: str) -> dict:
    record = followup_evaluation_runs_repository.get_evaluation(evaluation_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Followup evaluation not found")
    return record.model_dump(mode="json")


@router.post("/followup-evaluations")
def run_followup_evaluation(
    retrieval_mode: RetrievalMode = "off",
    ablation: bool = False,
) -> dict:
    """Lanza una evaluación de seguimiento (Decisión 006), opcionalmente con RAG (Decisión 012).

    Parámetros:
    - `retrieval_mode`: `off` (default) | `current` | `all`. Ignorado si `ablation=true`.
    - `ablation=true`: corre las tres configuraciones (`off`, `current`, `all`) y devuelve la lista.
    """
    transcripts = repository.list_transcripts()
    if not transcripts:
        raise HTTPException(status_code=400, detail="No transcripts available for evaluation")

    chains = followup_evaluation_service._collect_chains(transcripts)
    if not chains:
        raise HTTPException(
            status_code=400,
            detail="No follow-up transitions labelled with expected_followups in the dataset",
        )

    try:
        if ablation:
            evaluations = followup_evaluation_service.evaluate_ablation(transcripts)
        else:
            evaluations = [
                followup_evaluation_service.evaluate_dataset(
                    transcripts, retrieval_mode=retrieval_mode
                )
            ]
    except AgentExecutionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    saved = [followup_evaluation_runs_repository.save(e) for e in evaluations]
    if ablation:
        return {"ablation": [e.model_dump(mode="json") for e in saved]}
    return {"evaluation": saved[0].model_dump(mode="json")}


@router.get("/transcripts/{transcript_id}")
def get_transcript(transcript_id: str) -> dict:
    transcript = repository.get_transcript(transcript_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail="Transcript not found")
    return repository.serialize(transcript)


@router.get("/transcripts/{transcript_id}/context")
def get_transcript_segment_context(
    transcript_id: str,
    segment_index: int,
    window: int = 2,
) -> dict:
    """Devuelve el segmento focal y los `window` turnos previos y posteriores (Decisión 011 A).

    Sirve a la cita literal del `CommitmentDetailPage`: permite expandir la cita a su contexto
    conversacional sin abrir el fichero de transcripción completo.
    """
    normalized_window = max(0, min(window, 10))
    context = repository.get_segment_context(transcript_id, segment_index, normalized_window)
    if context is None:
        raise HTTPException(status_code=404, detail="Transcript or segment not found")
    return context


@router.get("/meetings")
def list_meetings(sprint_id: str | None = None) -> list[dict]:
    """Lista las reuniones (transcripciones) del dataset con su estado de análisis (Decisión 009).

    Por cada transcripción: si tiene run vigente devuelve `analyzed=True`, `analyzed_at`,
    `commitments_count` (items committable con `commitment_id` asignado por el sync) y `run_id`.
    Si no, `analyzed=False` y los campos derivados como `None`/`0`. Cada entrada incluye además
    `sprint_id` para que el frontend pueda agrupar (Decisión 011). Filtrable por sprint.
    """
    out = []
    for transcript in repository.list_transcripts():
        if sprint_id is not None and transcript.sprint_id != sprint_id:
            continue
        run = runs_repository.get_run_by_transcript(transcript.id)
        if run is None:
            out.append(
                {
                    "id": transcript.id,
                    "title": transcript.title,
                    "provider": transcript.provider,
                    "meeting_date": transcript.meeting_date,
                    "sprint_id": transcript.sprint_id,
                    "analyzed": False,
                    "analyzed_at": None,
                    "commitments_count": 0,
                    "run_id": None,
                }
            )
        else:
            commitments_count = sum(
                1 for item in run.analysis.items if item.commitment_id is not None
            )
            out.append(
                {
                    "id": transcript.id,
                    "title": transcript.title,
                    "provider": transcript.provider,
                    "meeting_date": transcript.meeting_date,
                    "sprint_id": transcript.sprint_id,
                    "analyzed": True,
                    "analyzed_at": run.created_at,
                    "commitments_count": commitments_count,
                    "run_id": run.run_id,
                }
            )
    return out


@router.post("/transcripts/{transcript_id}/analyze")
def analyze_transcript(transcript_id: str) -> dict:
    """Analiza una transcripcion del dataset razonando siempre contra el historial.

    Si el repositorio de compromisos esta vacio (primera reunion del sistema), el
    historial sera `[]` y el pipeline se comporta como un analisis aislado: el
    `task_followup_agent` y el `git_evidence_agent` hacen passthrough naturalmente.
    Ver Decision 008.
    """
    transcript = repository.get_transcript(transcript_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail="Transcript not found")
    history = commitment_repository.build_history()
    try:
        analysis = orchestrator.analyze(transcript, history=history)
    except AgentExecutionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    saved_run = runs_repository.save(transcript, analysis)
    commitment_sync.sync_from_analysis(
        transcript, saved_run.analysis, saved_run.run_id, history=history
    )
    runs_repository.update_run(saved_run)
    return {
        "transcript": repository.serialize(transcript),
        "analysis": saved_run.analysis.model_dump(mode="json"),
    }


@router.patch("/runs/{run_id}/items/{item_index}")
def patch_item_validation(run_id: str, item_index: int, body: ValidationPatch) -> dict:
    record = runs_repository.get_run(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if item_index < 0 or item_index >= len(record.analysis.items):
        raise HTTPException(status_code=404, detail="Item index out of range")
    item = record.analysis.items[item_index]
    item.validation_status = body.validation_status
    runs_repository.update_run(record)

    if item.commitment_id:
        commitment = commitment_repository.get(item.commitment_id)
        if commitment is not None:
            now = commitment_repository.now_iso()
            if body.validation_status == "approved" and commitment.state == "detected":
                commitment.state = "validated"
                commitment.timeline.append(
                    CommitmentEvent(
                        event_type="validated",
                        run_id=record.run_id,
                        meeting_title=record.transcript_title,
                        meeting_date=commitment.origin.meeting_date,
                        detail="Aprobado en triaje",
                        recorded_at=now,
                    )
                )
                commitment_repository.update(commitment)
            elif body.validation_status == "rejected" and commitment.state != "rejected":
                commitment.state = "rejected"
                commitment.timeline.append(
                    CommitmentEvent(
                        event_type="rejected",
                        run_id=record.run_id,
                        meeting_title=record.transcript_title,
                        meeting_date=commitment.origin.meeting_date,
                        detail="Rechazado en triaje",
                        recorded_at=now,
                    )
                )
                sync_result = jira_sync_service.push_state_change(commitment)
                if sync_result.outcome == "failed":
                    commitment.timeline.append(
                        CommitmentEvent(
                            event_type="jira_sync_failed",
                            run_id=record.run_id,
                            meeting_title=record.transcript_title,
                            meeting_date=commitment.origin.meeting_date,
                            detail=sync_result.detail,
                            recorded_at=commitment_repository.now_iso(),
                        )
                    )
                commitment_repository.update(commitment)

    return {"run_id": run_id, "item_index": item_index, "validation_status": body.validation_status}


@router.post("/runs/{run_id}/items/{item_index}/create-jira-issue")
def create_jira_issue_from_item(run_id: str, item_index: int) -> dict:
    record = runs_repository.get_run(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if item_index < 0 or item_index >= len(record.analysis.items):
        raise HTTPException(status_code=404, detail="Item index out of range")

    item = record.analysis.items[item_index]
    if item.validation_status != "approved":
        raise HTTPException(status_code=400, detail="Item must be approved before creating a Jira issue")
    if item.issue_draft is None:
        raise HTTPException(status_code=400, detail="Item has no issue draft to create from")
    if item.jira_created_issue is not None:
        return {"run_id": run_id, "item_index": item_index, "jira_issue": item.jira_created_issue.model_dump()}

    client = JiraCloudClient()
    if not client.is_configured():
        raise HTTPException(status_code=503, detail="Jira is not configured")

    try:
        result = client.create_issue(
            summary=item.issue_draft.title,
            description=item.issue_draft.description,
            labels=item.issue_draft.labels,
        )
    except JiraClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    item.jira_created_issue = JiraCreatedIssue(issue_key=result.issue_key, url=result.url)
    runs_repository.update_run(record)

    if item.commitment_id:
        commitment = commitment_repository.get(item.commitment_id)
        if commitment is not None:
            commitment.jira_created_issue = item.jira_created_issue
            if commitment.state in ("detected", "validated"):
                commitment.state = "registered"
            commitment.timeline.append(
                CommitmentEvent(
                    event_type="jira_created",
                    run_id=record.run_id,
                    meeting_title=record.transcript_title,
                    meeting_date=commitment.origin.meeting_date,
                    detail=f"Issue creado en Jira: {result.issue_key}",
                    recorded_at=commitment_repository.now_iso(),
                )
            )
            # Si el compromiso ya estaba en evidenced/closed antes del Llevar al tablero, sincroniza
            # la columna del issue recién creado para que no quede atrás del estado real.
            if commitment.state in ("evidenced", "closed"):
                sync_result = jira_sync_service.push_state_change(commitment)
                if sync_result.outcome == "failed":
                    commitment.timeline.append(
                        CommitmentEvent(
                            event_type="jira_sync_failed",
                            run_id=record.run_id,
                            meeting_title=record.transcript_title,
                            meeting_date=commitment.origin.meeting_date,
                            detail=sync_result.detail,
                            recorded_at=commitment_repository.now_iso(),
                        )
                    )
            commitment_repository.update(commitment)

    return {"run_id": run_id, "item_index": item_index, "jira_issue": item.jira_created_issue.model_dump()}


@router.post("/qa/ask")
def ask_question(payload: QARequest) -> StreamingResponse:
    """Q&A asistido por RAG con respuesta en streaming NDJSON (Decisión 013).

    El cuerpo emite una línea de JSON por evento:
      `{"type":"sources","sources":[...]}` primero,
      luego `{"type":"token","text":"..."}` por cada token generado,
      y termina con `{"type":"done"}` (o `{"type":"error","detail":"..."}` si falló).
    El cliente lee línea a línea y va renderizando la respuesta incrementalmente.
    """

    def event_stream():
        for event in qa_service.answer(
            payload.question,
            payload.sprint_id,
            payload.scope,
        ):
            yield (json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8")

    return StreamingResponse(
        event_stream(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.post("/analyze/raw")
def analyze_raw_transcript(payload: RawTranscriptPayload) -> dict:
    """Analiza texto manual razonando siempre contra el historial (Decision 008)."""
    transcript = parser.parse(
        raw_text=payload.transcript_text,
        title=payload.title,
        provider=payload.provider,
    )
    history = commitment_repository.build_history()
    try:
        analysis = orchestrator.analyze(transcript, history=history)
    except AgentExecutionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    saved_run = runs_repository.save(transcript, analysis)
    commitment_sync.sync_from_analysis(
        transcript, saved_run.analysis, saved_run.run_id, history=history
    )
    runs_repository.update_run(saved_run)
    return {
        "transcript": repository.serialize(transcript),
        "analysis": saved_run.analysis.model_dump(mode="json"),
    }
