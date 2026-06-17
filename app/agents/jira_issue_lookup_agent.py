import json

from app.agents.exceptions import AgentExecutionError
from app.domain.models import AgentDefinition, AgentRun, DetectedItem, MeetingTranscript
from app.services.jira_client import JiraClientError, JiraCloudClient


class JiraIssueLookupAgent:
    def __init__(self, jira_client: JiraCloudClient | None = None) -> None:
        self.jira_client = jira_client or JiraCloudClient()

    def run(
        self,
        transcript: MeetingTranscript,
        issue_ready_items: list[DetectedItem],
        definition: AgentDefinition,
    ) -> tuple[list[DetectedItem], AgentRun]:
        looked_up_items: list[DetectedItem] = []
        match_counts: dict[str, int] = {}
        last_jql = ""

        for item in issue_ready_items:
            copied_item = item.model_copy(deep=True)
            if copied_item.issue_draft is None:
                looked_up_items.append(copied_item)
                continue

            search_text = copied_item.issue_draft.title or copied_item.title
            try:
                result = self.jira_client.search_similar_issues(search_text)
            except JiraClientError as exc:
                raise AgentExecutionError(str(exc)) from exc
            copied_item.jira_matches = result.matches
            match_counts[copied_item.title] = len(result.matches)
            if result.jql:
                last_jql = result.jql
            looked_up_items.append(copied_item)

        run = AgentRun(
            agent_id=definition.id,
            agent_name=definition.name,
            provider=definition.provider,
            model=definition.model,
            status="completed",
            output_key=definition.output_key,
            raw_content=json.dumps(
                {
                    "jira_configured": self.jira_client.is_configured(),
                    "match_counts": match_counts,
                    "last_jql": last_jql,
                },
                ensure_ascii=False,
            ),
        )
        return looked_up_items, run
