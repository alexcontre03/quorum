from app.agents.catalog import AgentCatalogLoader
from app.agents.exceptions import AgentExecutionError
from app.agents.git_evidence_agent import GitEvidenceAgent
from app.agents.issue_draft_agent import IssueDraftAgent
from app.agents.jira_issue_lookup_agent import JiraIssueLookupAgent
from app.agents.task_followup_agent import TaskFollowupAgent
from app.agents.task_proposal_agent import TaskProposalAgent
from app.agents.task_validation_agent import TaskValidationAgent
from app.domain.models import (
    AnalysisResult,
    AnalysisSummary,
    DetectedItem,
    FollowupUpdate,
    GitEvidenceUpdate,
    HistoryItemSummary,
    MeetingTranscript,
    RetrievalMode,
    RetrievedChunk,
)
from app.services.transcript_retriever import TranscriptRetriever


class MeetingAnalysisOrchestrator:
    def __init__(self, retriever: TranscriptRetriever | None = None) -> None:
        self.catalog_loader = AgentCatalogLoader()
        self.task_proposal_agent = TaskProposalAgent()
        self.task_validation_agent = TaskValidationAgent()
        self.issue_draft_agent = IssueDraftAgent()
        self.task_followup_agent = TaskFollowupAgent()
        self.jira_issue_lookup_agent = JiraIssueLookupAgent()
        self.git_evidence_agent = GitEvidenceAgent()
        self.retriever = retriever or TranscriptRetriever()

    def describe(self) -> dict:
        catalog = self.catalog_loader.load()
        return {
            "pipeline_id": catalog.pipeline_id,
            "pipeline": catalog.pipeline,
            "agents": [agent.model_dump(mode="json") for agent in catalog.agents if agent.enabled],
        }

    def analyze(
        self,
        transcript: MeetingTranscript,
        history: list[HistoryItemSummary] | None = None,
        retrieval_mode: RetrievalMode = "current",
    ) -> AnalysisResult:
        catalog = self.catalog_loader.load()
        context: dict = {"meeting_transcript": transcript}
        runs = []
        followup_updates: list[FollowupUpdate] = []
        git_evidence_updates: list[GitEvidenceUpdate] = []
        retrieved_chunks_by_item: dict[int, list[RetrievedChunk]] = {}
        final_output_key = None

        # When the user has chosen to override the per-agent model assignment
        # of agents.json while in the local profile, apply that override to
        # every chat agent before running the pipeline. The frontier profiles
        # apply their override on the client itself (see client_factory).
        from app.agents.client_factory import get_local_model_override
        local_override = get_local_model_override()

        for agent_id in catalog.pipeline:
            definition = next((a for a in catalog.agents if a.id == agent_id and a.enabled), None)
            if definition is None:
                continue
            if local_override and definition.agent_kind != "jira_issue_lookup":
                definition = definition.model_copy(update={"model": local_override})

            try:
                if definition.agent_kind == "task_proposal":
                    items, run = self.task_proposal_agent.run(transcript, definition)

                elif definition.agent_kind == "task_validation":
                    input_items = context.get(definition.input_key)
                    if not isinstance(input_items, list):
                        raise AgentExecutionError(
                            f"Agent {definition.id} expected a list in context key '{definition.input_key}'"
                        )
                    items, run = self.task_validation_agent.run(transcript, input_items, definition)

                elif definition.agent_kind == "issue_draft":
                    input_items = context.get(definition.input_key)
                    if not isinstance(input_items, list):
                        raise AgentExecutionError(
                            f"Agent {definition.id} expected a list in context key '{definition.input_key}'"
                        )
                    items, run = self.issue_draft_agent.run(transcript, input_items, definition)

                elif definition.agent_kind == "task_followup":
                    input_items = context.get(definition.input_key)
                    if not isinstance(input_items, list):
                        raise AgentExecutionError(
                            f"Agent {definition.id} expected a list in context key '{definition.input_key}'"
                        )
                    retrieved_chunks_by_item = self._retrieve_chunks(
                        transcript, input_items, retrieval_mode
                    )
                    followup_result = self.task_followup_agent.run(
                        transcript,
                        input_items,
                        history or [],
                        definition,
                        history_git_evidence=git_evidence_updates,
                        retrieved_chunks_by_item=retrieved_chunks_by_item,
                    )
                    items = input_items
                    followup_updates = followup_result.followup_updates
                    run = followup_result.agent_run

                elif definition.agent_kind == "git_evidence":
                    git_evidence_updates, run = self.git_evidence_agent.run(
                        transcript, history or [], definition
                    )
                    context[definition.output_key] = git_evidence_updates
                    if run is not None:
                        runs.append(run)
                    continue

                elif definition.agent_kind == "jira_issue_lookup":
                    input_items = context.get(definition.input_key)
                    if not isinstance(input_items, list):
                        raise AgentExecutionError(
                            f"Agent {definition.id} expected a list in context key '{definition.input_key}'"
                        )
                    items, run = self.jira_issue_lookup_agent.run(transcript, input_items, definition)

                else:
                    raise AgentExecutionError(f"Unsupported agent kind: {definition.agent_kind}")

            except AgentExecutionError as exc:
                runs.append(
                    {
                        "agent_id": definition.id,
                        "agent_name": definition.name,
                        "provider": definition.provider,
                        "model": definition.model,
                        "status": "failed",
                        "output_key": definition.output_key,
                        "error": str(exc),
                        "raw_content": None,
                    }
                )
                raise

            context[definition.output_key] = items
            final_output_key = definition.output_key
            if run is not None:
                runs.append(run)

        items = context.get(final_output_key or "task_candidates", [])
        summary = AnalysisSummary(
            total_items=len(items),
            clear_tasks=sum(1 for item in items if item.item_type == "task"),
            ambiguous_tasks=sum(1 for item in items if item.item_type == "ambiguous_task"),
            technical_decisions=sum(1 for item in items if item.item_type == "technical_decision"),
        )
        if retrieval_mode != "off":
            try:
                self.retriever.ensure_indexed(transcript)
            except Exception:
                pass

        return AnalysisResult(
            transcript_id=transcript.id,
            transcript_title=transcript.title,
            items=items,
            summary=summary,
            pipeline_id=catalog.pipeline_id,
            agent_runs=runs,
            followup_updates=followup_updates,
            git_evidence_updates=git_evidence_updates,
            retrieved_chunks_by_item=retrieved_chunks_by_item,
            retrieval_mode=retrieval_mode,
        )

    def _retrieve_chunks(
        self,
        transcript: MeetingTranscript,
        items: list[DetectedItem],
        retrieval_mode: RetrievalMode,
    ) -> dict[int, list[RetrievedChunk]]:
        """Recupera top-K chunks por item según el modo (Decisión 012). 'off' devuelve {}."""
        if retrieval_mode == "off":
            return {}
        scope = "current" if retrieval_mode == "current" else "all"
        out: dict[int, list[RetrievedChunk]] = {}
        for i, item in enumerate(items):
            query = " ".join(filter(None, [item.title, item.summary, item.evidence])).strip()
            if not query:
                continue
            chunks = self.retriever.retrieve(
                query,
                current_sprint_id=transcript.sprint_id,
                scope=scope,
                exclude_transcript_id=transcript.id,
            )
            if chunks:
                out[i] = chunks
        return out
