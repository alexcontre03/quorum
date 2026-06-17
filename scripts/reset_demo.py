"""Reset del estado derivado de la app para empezar una demo en limpio.

Conserva:
  - `app/data/transcripts/*.json`        (el dataset es la fuente de verdad)
  - `app/config/*`                       (agents.json, prompts, runtime_settings)
  - `.env`                               (credenciales Jira)

Borra:
  - `app/data/analysis_runs/*.json`           (runs anteriores)
  - `app/data/commitments/*.json`             (compromisos persistidos)
  - `app/data/evaluation_runs/*.json`         (evaluaciones de extracción)
  - `app/data/followup_evaluation_runs/*.json` (evaluaciones de seguimiento)
  - `app/data/retrieval_index/*.npz` y `*.json` (índices RAG; se regeneran al analizar)

NO toca Jira. Si quieres resetear también los issues Jira, hazlo manualmente desde la UI.

Uso:
  python scripts/reset_demo.py
  python scripts/reset_demo.py --dry-run     # solo lista lo que borraria
"""

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DATA = REPO_ROOT / "app" / "data"

TARGET_DIRS = [
    "analysis_runs",
    "commitments",
    "evaluation_runs",
    "followup_evaluation_runs",
    "retrieval_index",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="No borra, solo lista")
    args = parser.parse_args()

    print(f"Repo root: {REPO_ROOT}")
    print(f"Data dir:  {DATA}\n")

    total = 0
    for subdir in TARGET_DIRS:
        d = DATA / subdir
        if not d.exists():
            print(f"  [skip] {subdir}/ no existe")
            continue
        files = sorted(list(d.glob("*.json")) + list(d.glob("*.npz")))
        if not files:
            print(f"  [ok]   {subdir}/ ya esta vacio")
            continue
        if args.dry_run:
            print(f"  [DRY]  {subdir}/: borraria {len(files)} ficheros")
        else:
            for f in files:
                f.unlink()
            print(f"  [done] {subdir}/: borrados {len(files)} ficheros")
        total += len(files)

    print(f"\nTranscripts intactos en {DATA / 'transcripts'}:")
    for f in sorted((DATA / "transcripts").glob("*.json")):
        print(f"  - {f.name}")

    if args.dry_run:
        print(f"\nDry-run: borraria {total} ficheros derivados en total. Sin --dry-run los borra.")
    else:
        print(f"\nReset completado: {total} ficheros borrados. Listo para una demo limpia.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
