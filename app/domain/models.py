from typing import Any, Literal

from pydantic import BaseModel, Field


ItemType = Literal["task", "ambiguous_task", "technical_decision"]
ConfidenceLevel = Literal["high", "medium", "low"]
ValidationStatus = Literal["pending_review", "approved", "rejected"]
FollowupType = Literal[
    "recurring_unresolved",
    "scope_change",
    "new_blocker",
    "blocker_resolved",
    "possible_duplicate",
    "contradicts_decision",
    "verbal_close",
]


class Participant(BaseModel):
    name: str
    role: str | None = None


class TranscriptSegment(BaseModel):
    timestamp: str | None = None
    speaker: str
    text: str


class ExpectedItem(BaseModel):
    item_type: ItemType
    title: str
    summary: str | None = None


class ExpectedFollowup(BaseModel):
    """Etiqueta esperada para evaluar el razonamiento de seguimiento entre reuniones.

    Vive en la reunion 2 de cada par; `matched_history_title` debe referenciar un
    `expected_items[].title` de la reunion 1 del mismo par.
    """
    followup_type: FollowupType
    matched_history_title: str


class IssueDraft(BaseModel):
    title: str
    description: str
    labels: list[str] = Field(default_factory=list)


class JiraIssueMatch(BaseModel):
    issue_key: str
    summary: str
    status: str
    issue_type: str
    url: str


class JiraCreatedIssue(BaseModel):
    issue_key: str
    url: str


class GitCommitRef(BaseModel):
    hash: str
    message: str
    author: str
    date: str


EvidenceLevel = Literal["sufficient", "partial", "none"]


class GitEvidence(BaseModel):
    evidence_level: EvidenceLevel
    explanation: str
    supporting_commits: list[GitCommitRef] = Field(default_factory=list)


# ===== GitHub evidence (Decisión 023) =====
# Tres estados que el GithubEvidenceAgent puede reportar para un compromiso:
#   - none     : no se encontró nada en GitHub que mencione el issue/keywords
#   - in_code_review: hay uno o más PRs abiertos referenciando el compromiso
#   - merged   : al menos un PR está mergeado en la rama por defecto del repo
# Mantenemos también una lista de commits encontrados (vía search/commits)
# para preservar la trazabilidad histórica que el git_evidence_agent local
# ya aportaba.

GitHubEvidenceLevel = Literal["none", "in_code_review", "merged"]


class GitHubPullRequest(BaseModel):
    """PR detectado en GitHub que referencia un compromiso. ``state`` es el
    estado nativo de la API (``open`` / ``closed``); ``merged`` es ``True``
    cuando el PR está cerrado por merge, lo que la API expone como un campo
    distinto del ``state`` general."""
    number: int
    title: str
    html_url: str
    state: Literal["open", "closed"]
    merged: bool = False
    merged_at: str | None = None
    author: str | None = None
    head_ref: str | None = None  # rama origen del PR
    base_ref: str | None = None  # rama destino del PR


class GitHubCommitRef(BaseModel):
    """Commit detectado en GitHub. Misma forma que ``GitCommitRef`` pero
    incluye el ``html_url`` del commit para enlazar al diff desde la UI."""
    sha: str
    message: str
    date: str
    author: str | None = None
    html_url: str | None = None


class GitHubEvidence(BaseModel):
    """Evidencia técnica detectada en GitHub para un compromiso.

    El ``GithubEvidenceAgent`` (Decisión 023) la produce a partir de tres
    búsquedas: PRs abiertos, PRs mergeados y commits que referencien el
    Jira issue key del compromiso (o sus keywords si Jira no se creó).
    ``evidence_level`` resume la situación más fuerte detectada para que el
    ``CommitmentSyncService`` pueda mover el lifecycle a ``in_code_review``
    o ``evidenced`` según corresponda."""
    evidence_level: GitHubEvidenceLevel
    explanation: str
    repo: str = ""
    pull_requests_open: list[GitHubPullRequest] = Field(default_factory=list)
    pull_requests_merged: list[GitHubPullRequest] = Field(default_factory=list)
    supporting_commits: list[GitHubCommitRef] = Field(default_factory=list)


class DetectedItem(BaseModel):
    item_type: ItemType
    title: str
    summary: str
    confidence: ConfidenceLevel
    speaker: str
    timestamp: str | None = None
    evidence: str
    issue_draft: IssueDraft | None = None
    jira_matches: list[JiraIssueMatch] = Field(default_factory=list)
    validation_status: ValidationStatus = "pending_review"
    jira_created_issue: JiraCreatedIssue | None = None
    git_evidence: GitEvidence | None = None
    commitment_id: str | None = None


class AnalysisSummary(BaseModel):
    total_items: int
    clear_tasks: int
    ambiguous_tasks: int
    technical_decisions: int


class AnalysisResult(BaseModel):
    transcript_id: str
    transcript_title: str
    items: list[DetectedItem]
    summary: AnalysisSummary
    pipeline_id: str
    agent_runs: list["AgentRun"] = Field(default_factory=list)
    followup_updates: list["FollowupUpdate"] = Field(default_factory=list)
    git_evidence_updates: list["GitEvidenceUpdate"] = Field(default_factory=list)
    retrieved_chunks_by_item: dict[int, list["RetrievedChunk"]] = Field(default_factory=dict)
    retrieval_mode: "RetrievalMode" = "off"
    run_id: str | None = None
    created_at: str | None = None


class MeetingTranscript(BaseModel):
    id: str
    title: str
    provider: str = "synthetic"
    meeting_date: str | None = None
    organizer: str | None = None
    sprint_id: str | None = None
    participants: list[Participant] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    segments: list[TranscriptSegment] = Field(default_factory=list)
    raw_text: str | None = None
    expected_items: list[ExpectedItem] = Field(default_factory=list)
    expected_followups: list[ExpectedFollowup] = Field(default_factory=list)


class RawTranscriptPayload(BaseModel):
    title: str = "Transcripcion manual"
    provider: str = "manual"
    transcript_text: str


class AgentDefinition(BaseModel):
    id: str
    name: str
    description: str
    agent_kind: str
    provider: str
    enabled: bool = True
    model: str
    base_url: str = "http://127.0.0.1:11434/api"
    input_key: str
    output_key: str
    system_prompt_path: str
    format: str = "json"
    response_schema: str | None = None
    temperature: float = 0.1
    options: dict[str, Any] = Field(default_factory=dict)


class AgentCatalog(BaseModel):
    pipeline_id: str = "meeting_analysis_pipeline"
    pipeline: list[str]
    agents: list[AgentDefinition]


class TaskCandidatePayload(BaseModel):
    item_type: ItemType
    title: str
    summary: str
    confidence: ConfidenceLevel = "medium"
    speaker: str = "Unknown"
    timestamp: str | None = None
    evidence: str


class TaskProposalPayload(BaseModel):
    items: list[TaskCandidatePayload] = Field(default_factory=list)


class AgentRun(BaseModel):
    agent_id: str
    agent_name: str
    provider: str
    model: str
    status: Literal["completed", "failed"]
    output_key: str
    raw_content: str | None = None
    error: str | None = None


class PersistedAnalysisRun(BaseModel):
    run_id: str
    created_at: str
    transcript_id: str
    transcript_title: str
    transcript_provider: str
    pipeline_id: str
    analysis: AnalysisResult


class EvaluationItemLink(BaseModel):
    expected_item_type: ItemType
    expected_title: str
    detected_item_type: ItemType
    detected_title: str
    similarity: float


class TranscriptEvaluationResult(BaseModel):
    transcript_id: str
    transcript_title: str
    status: Literal["completed", "failed"]
    error: str | None = None
    expected_count: int = 0
    detected_count: int = 0
    matched_count: int = 0
    false_negative_count: int = 0
    false_positive_count: int = 0
    misclassified_count: int = 0
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    expected_by_type: dict[str, int] = Field(default_factory=dict)
    detected_by_type: dict[str, int] = Field(default_factory=dict)
    matched_by_type: dict[str, int] = Field(default_factory=dict)
    matches: list[EvaluationItemLink] = Field(default_factory=list)
    misclassified_matches: list[EvaluationItemLink] = Field(default_factory=list)
    missing_expected_items: list[ExpectedItem] = Field(default_factory=list)
    unexpected_detected_items: list[DetectedItem] = Field(default_factory=list)
    detected_items: list[DetectedItem] = Field(default_factory=list)
    agent_runs: list["AgentRun"] = Field(default_factory=list)


class DatasetEvaluationSummary(BaseModel):
    transcript_count: int
    completed_transcripts: int
    failed_transcripts: int
    expected_count: int
    detected_count: int
    matched_count: int
    false_negative_count: int
    false_positive_count: int
    misclassified_count: int
    precision: float
    recall: float
    f1: float


class DatasetEvaluationResult(BaseModel):
    evaluation_id: str | None = None
    created_at: str | None = None
    pipeline_id: str
    matching_threshold: float
    transcript_results: list[TranscriptEvaluationResult] = Field(default_factory=list)
    summary: DatasetEvaluationSummary


class HistoryItemSummary(BaseModel):
    """Resumen compacto de un item de una ejecucion anterior, para alimentar al task_followup_agent."""
    run_id: str
    meeting_title: str
    meeting_date: str | None
    item_type: ItemType
    title: str
    validation_status: ValidationStatus
    jira_issue_key: str | None = None
    commitment_id: str | None = None


class FollowupUpdate(BaseModel):
    """Actualizacion detectada por task_followup_agent sobre un item ya conocido."""
    followup_type: FollowupType
    matched_history_title: str
    explanation: str
    # Cita textual de la reunion actual que justifica el update. La UI la
    # muestra como evidencia del cambio en la timeline del compromiso para
    # que el lector vea por que el agente cambio el estado, sin tener que
    # abrir la transcripcion entera.
    trigger_quote: str = ""
    new_title: str | None = None
    new_summary: str | None = None
    matched_new_item_index: int | None = None


class FollowupAnalysisResult(BaseModel):
    """Salida del task_followup_agent: nuevos items mas actualizaciones sobre items anteriores."""
    new_items: list[DetectedItem] = Field(default_factory=list)
    followup_updates: list[FollowupUpdate] = Field(default_factory=list)
    agent_run: AgentRun | None = None


RetrievalMode = Literal["off", "current", "all"]


class RetrievedChunk(BaseModel):
    """Fragmento textual recuperado del índice vectorial (Decisión 012).

    Cada chunk agrupa ~3 turnos consecutivos de una transcripción del historial; lo usa el
    `task_followup_agent` para razonar sobre el matiz textual y se guarda en `AnalysisResult`
    para transparencia (mostrar al usuario en el detalle del compromiso).
    """
    transcript_id: str
    sprint_id: str | None = None
    chunk_index: int
    segment_indices: list[int] = Field(default_factory=list)
    speakers: list[str] = Field(default_factory=list)
    text: str
    similarity: float


QASourceType = Literal["transcript", "commitment"]
QAScope = Literal["analyzed_only", "all"]


class QASource(BaseModel):
    """Fragmento usado como fuente en una respuesta de Q&A (Decisión 013)."""
    index: int
    source_type: QASourceType
    sprint_id: str | None = None
    title: str
    subtitle: str = ""
    text: str
    similarity: float
    transcript_id: str | None = None
    segment_indices: list[int] = Field(default_factory=list)
    commitment_id: str | None = None
    commitment_state: str | None = None


class QARequest(BaseModel):
    question: str
    sprint_id: str | None = None
    scope: QAScope = "analyzed_only"


class CommitmentRefreshChange(BaseModel):
    """Cambio individual aplicado por el refresh (Decisión 014).

    `event_type` y los estados se serializan como strings para evitar referencia adelantada a los
    `Literal` que viven más abajo en el módulo. Los valores siguen los mismos conjuntos cerrados:
    event_type en `CommitmentEventType` y los estados en `CommitmentState`.
    """
    source: Literal["jira", "git", "github"]
    event_type: str
    detail: str
    previous_state: str | None = None
    new_state: str | None = None


class CommitmentRefreshResult(BaseModel):
    commitment_id: str
    changed: bool
    jira_configured: bool
    git_configured: bool
    github_configured: bool = False  # D023
    changes: list[CommitmentRefreshChange] = Field(default_factory=list)
    reason: str | None = None


class CommitmentRefreshBatchResult(BaseModel):
    refreshed: int
    changed: int
    per_commitment: list[CommitmentRefreshResult] = Field(default_factory=list)


JiraSyncOutcome = Literal["transitioned", "labelled", "skipped", "no_issue", "not_configured", "failed"]


class JiraSyncResult(BaseModel):
    """Resultado de propagar un cambio de estado del compromiso al issue Jira (Decisión 015)."""
    commitment_id: str
    outcome: JiraSyncOutcome
    issue_key: str | None = None
    target_status_name: str | None = None
    label_applied: str | None = None
    detail: str = ""


class GitEvidenceUpdate(BaseModel):
    """Evidencia tecnica recogida para un compromiso del historial en este analisis."""
    commitment_id: str
    evidence: GitEvidence


CommitmentState = Literal[
    "detected",
    "validated",
    "registered",
    "in_code_review",  # PR abierto en GitHub que referencia el compromiso (D023)
    "evidenced",
    "closed",
    "rejected",
]


CommitmentEventType = Literal[
    "detected",
    "validated",
    "rejected",
    "jira_created",
    "jira_status_refreshed",
    "jira_sync_failed",
    "jira_scope_synced",      # Tras scope_change propagamos el nuevo título/resumen a Jira
    "jira_blocker_labeled",   # Tras new_blocker añadimos label "bloqueado-trazabilidad"
    "jira_blocker_cleared",   # Tras blocker_resolved quitamos el label
    "git_evidence_updated",
    "github_evidence_updated",  # GitHub PR/merge detectado (D023)
    "followup",
    "scope_changed",
    "duplicate_dismissed",    # El usuario marca: no es duplicado en realidad
    "closed",
]


class CommitmentOrigin(BaseModel):
    """Dónde se dijo por primera vez el compromiso."""
    source_run_id: str
    transcript_id: str
    meeting_title: str
    meeting_date: str | None = None
    sprint_id: str | None = None
    segment_index: int | None = None
    speaker: str
    timestamp: str | None = None
    evidence: str


class CommitmentEvent(BaseModel):
    """Entrada del timeline de un compromiso: qué le pasó, cuándo y en qué reunión."""
    event_type: CommitmentEventType
    run_id: str | None = None
    meeting_title: str | None = None
    meeting_date: str | None = None
    detail: str = ""
    recorded_at: str
    followup_type: FollowupType | None = None
    previous_title: str | None = None
    new_title: str | None = None
    # Cita textual de la reunion que provoco el evento (ej. la frase que
    # justifico el `scope_change` o el `new_blocker`). Vacio en eventos
    # automaticos como `jira_created` o `git_evidence_updated`.
    trigger_quote: str = ""


class Commitment(BaseModel):
    """Entidad de primera clase: un compromiso con identidad estable y línea de vida."""
    commitment_id: str
    title: str
    summary: str
    item_type: ItemType
    state: CommitmentState
    origin: CommitmentOrigin
    jira_created_issue: JiraCreatedIssue | None = None
    git_evidence: GitEvidence | None = None
    github_evidence: GitHubEvidence | None = None  # D023: PRs / merges detectados en GitHub
    timeline: list[CommitmentEvent] = Field(default_factory=list)
    created_at: str
    updated_at: str


class FollowupEvaluationPairMatch(BaseModel):
    """Detalle de un emparejamiento esperado↔predicho dentro de un par de seguimiento."""
    expected_title: str
    expected_type: FollowupType | None = None
    predicted_type: FollowupType | None = None
    similarity: float = 0.0
    correct_type: bool = False


class FollowupPairEvaluation(BaseModel):
    """Resultado de evaluar un par de reuniones (reunion 1 → reunion 2 con historial)."""
    series_id: str
    meeting_1_id: str
    meeting_2_id: str
    expected_count: int
    predicted_count: int
    matched_count: int
    correct_type_count: int
    matches: list[FollowupEvaluationPairMatch] = Field(default_factory=list)
    missing_expected: list[ExpectedFollowup] = Field(default_factory=list)
    unexpected_predicted: list[FollowupUpdate] = Field(default_factory=list)
    status: Literal["completed", "failed"] = "completed"
    error: str | None = None


class FollowupEvaluationSummary(BaseModel):
    pair_count: int
    completed_pairs: int
    failed_pairs: int
    expected_count: int
    predicted_count: int
    matched_count: int
    correct_type_count: int
    coverage: float
    precision_micro: float
    recall_micro: float
    f1_micro: float
    precision_macro: float
    recall_macro: float
    f1_macro: float
    precision_by_type: dict[str, float] = Field(default_factory=dict)
    recall_by_type: dict[str, float] = Field(default_factory=dict)
    f1_by_type: dict[str, float] = Field(default_factory=dict)
    confusion_matrix: dict[str, dict[str, int]] = Field(default_factory=dict)


class FollowupEvaluationResult(BaseModel):
    evaluation_id: str | None = None
    created_at: str | None = None
    pipeline_id: str
    matching_threshold: float
    retrieval_mode: RetrievalMode = "off"
    pair_results: list[FollowupPairEvaluation] = Field(default_factory=list)
    summary: FollowupEvaluationSummary


AnalysisResult.model_rebuild()
TranscriptEvaluationResult.model_rebuild()
