"""Smoke test for the EN runner wiring: list 9 transcripts, check first one
is English, and confirm each agent's system_prompt_path now points under
prompts_en/."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.services import transcript_repository as _repo
_orig = _repo.TranscriptRepository.__init__


def _p(self):
    _orig(self)
    self.base_dir = ROOT / "app" / "data" / "transcripts_en"


_repo.TranscriptRepository.__init__ = _p

from app.agents import catalog as _catalog
_orig_load = _catalog.AgentCatalogLoader.load


def _pl(self):
    cat = _orig_load(self)
    for a in cat.agents:
        a.system_prompt_path = a.system_prompt_path.replace(
            "\\config\\prompts\\", "\\config\\prompts_en\\"
        ).replace(
            "/config/prompts/", "/config/prompts_en/"
        )
    return cat


_catalog.AgentCatalogLoader.load = _pl

from app.services.transcript_repository import TranscriptRepository
from app.agents.catalog import AgentCatalogLoader

ts = TranscriptRepository().list_transcripts()
print(f"Loaded {len(ts)} transcripts")
print(f"First title: {ts[0].title!r}")
print(f"First segment: {ts[0].segments[0].text!r}")

cat = AgentCatalogLoader().load()
for a in cat.agents:
    in_en = "prompts_en" in a.system_prompt_path
    print(f"{a.id:30}  prompts_en={in_en}  {Path(a.system_prompt_path).name}")
