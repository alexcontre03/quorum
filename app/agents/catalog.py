import json
from pathlib import Path

from app.domain.models import AgentCatalog, AgentDefinition


class AgentCatalogLoader:
    def __init__(self) -> None:
        self.base_dir = Path(__file__).resolve().parents[1]
        self.catalog_path = self.base_dir / "config" / "agents.json"

    def load(self) -> AgentCatalog:
        data = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        catalog = AgentCatalog.model_validate(data)
        self._resolve_prompt_paths(catalog)
        return catalog

    def get_agent(self, agent_id: str) -> AgentDefinition:
        catalog = self.load()
        for agent in catalog.agents:
            if agent.id == agent_id:
                return agent
        raise KeyError(f"Agent '{agent_id}' not found")

    def _resolve_prompt_paths(self, catalog: AgentCatalog) -> None:
        for agent in catalog.agents:
            agent.system_prompt_path = str((self.base_dir / agent.system_prompt_path).resolve())
