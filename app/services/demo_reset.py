"""Reset del estado derivado de la demo desde la UI (D023+).

El usuario pulsa "Reiniciar demo" en la cabecera y el backend borra los
directorios derivados que `scripts/reset_demo.py` ya limpiaba por CLI:

- ``analysis_runs/``           runs históricos de análisis
- ``commitments/``             compromisos persistidos
- ``evaluation_runs/``         evaluaciones de extracción
- ``followup_evaluation_runs/`` evaluaciones de seguimiento
- ``retrieval_index/``         índices RAG (.npz + .json)
- ``qa_audit/``                logs del Q&A guardrails (D022) — opcional

Lo que **no** toca el reset:

- ``transcripts/``    el dataset es la fuente de verdad.
- ``settings/``       el runtime_profile sigue activo.
- ``.env``            credenciales nunca se tocan desde la app.
- Jira / GitHub:      el reset es solo local. Para limpiar Jira hay un
                      endpoint aparte (``cleanup_jira_created_issues``).
"""

from __future__ import annotations

import logging
from pathlib import Path

_logger = logging.getLogger(__name__)

# Cinco directorios de datos derivados que la demo regenera al volver a
# analizar. Las claves son las que la respuesta JSON devuelve al frontend.
_RESET_DIRS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("analysis_runs", "analysis_runs", (".json",)),
    ("commitments", "commitments", (".json",)),
    ("evaluation_runs", "evaluation_runs", (".json",)),
    ("followup_evaluation_runs", "followup_evaluation_runs", (".json",)),
    ("retrieval_index", "retrieval_index", (".json", ".npz")),
)
_OPT_AUDIT_DIR = ("qa_audit", "qa_audit", (".jsonl",))


def _data_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "data"


def perform_reset(*, wipe_audit: bool = False) -> dict[str, int]:
    """Borra los ficheros derivados y devuelve cuántos se eliminaron por
    directorio. Errores individuales (un fichero bloqueado, por ejemplo)
    se loguean pero no impiden el resto del reset."""
    data = _data_dir()
    summary: dict[str, int] = {}
    targets = list(_RESET_DIRS)
    if wipe_audit:
        targets.append(_OPT_AUDIT_DIR)
    for key, subdir, extensions in targets:
        d = data / subdir
        if not d.exists():
            summary[key] = 0
            continue
        count = 0
        for path in d.iterdir():
            if path.suffix in extensions and path.is_file():
                try:
                    path.unlink()
                    count += 1
                except OSError as exc:
                    _logger.warning("Could not delete %s: %s", path, exc)
        summary[key] = count
    return summary


def cleanup_jira_created_issues(
    *, dry_run: bool = False
) -> dict[str, object]:
    """Cierra (o lista en modo dry-run) los issues de Jira que el sistema
    creó durante la demo. Solo toca los que están registrados como
    ``jira_created_issue`` en alguno de los compromisos persistidos: no
    busca por proyecto, así que es seguro contra issues que no son del
    sistema.

    En modo ``dry_run=True`` solo devuelve la lista de keys que cerraría,
    sin contactar Jira. En modo normal intenta moverlos a la categoría
    ``done`` usando el mismo ``JiraSyncService`` que el resto del sistema.
    """
    # Late imports para no penalizar el arranque del backend.
    from app.services.commitment_repository import CommitmentRepository
    from app.services.jira_client import JiraCloudClient
    from app.services.jira_sync import JiraSyncService

    jira = JiraCloudClient()
    repository = CommitmentRepository()
    sync = JiraSyncService(jira_client=jira)

    issue_keys: list[str] = []
    for c in repository.list_all():
        if c.jira_created_issue and c.jira_created_issue.issue_key:
            issue_keys.append(c.jira_created_issue.issue_key)

    if dry_run or not jira.is_configured():
        return {
            "configured": jira.is_configured(),
            "dry_run": True,
            "issue_keys": issue_keys,
            "closed": 0,
            "failed": [],
        }

    closed: list[str] = []
    failed: list[dict[str, str]] = []
    for key in issue_keys:
        try:
            # Reutilizamos el helper interno del sync: la transición se elige
            # buscando una con statusCategory.key == "done". El nombre
            # ("Done", "Cerrado", "Finalizada"...) depende del workflow del
            # proyecto Jira, por eso vamos por la categoría estable.
            transitions = jira.list_transitions(key)
            target = next(
                (t for t in transitions if t.to_status_category_key == "done"),
                None,
            )
            if target is None:
                failed.append({"key": key, "reason": "no done transition available"})
                continue
            jira.transition_issue(key, target.id)
            closed.append(key)
        except Exception as exc:  # pragma: no cover - depende de Jira en vivo
            failed.append({"key": key, "reason": str(exc)})
    return {
        "configured": True,
        "dry_run": False,
        "issue_keys": issue_keys,
        "closed": len(closed),
        "closed_keys": closed,
        "failed": failed,
    }
