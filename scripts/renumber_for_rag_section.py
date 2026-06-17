"""One-shot renumbering of CDIA memoir to insert a new section 7.3 (RAG).

Current → target:
- 7.3 Dataset      → 7.4
- 7.4 Experimental → 7.5
- 7.5 Results      → 7.6
- 7.6 Discussion   → 7.7

The script processes files in 07_development/ (renames + header rewrite) and
updates every cross-reference (``section 7.X``, ``section 7.X.Y``, ``§7.X``,
``sección 7.X``, ``7.X.Y of...``) across memoria/cdia/.

Run from project root: ``python scripts/renumber_for_rag_section.py``
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MEM = ROOT / "memoria" / "cdia"
DEV = MEM / "07_development"

# Files to skip (working notes, asset indices). Everything else under MEM gets
# the cross-reference rewrite.
SKIP_FILES = {
    "INDICE.md",            # we update it manually
    "_phase2_snippets.md",  # working note
    "_review_status.md",    # working note
    "img/INDICE_FIGURAS.md",
    "PREGUNTAS_NORMATIVA.md",
    "INDICE_FIGURAS.md",
}


def renumber_text(text: str) -> str:
    """Apply the section number rewrites in safe order (high→low)."""
    # Order: 7.6 -> 7.7, 7.5 -> 7.6, 7.4 -> 7.5, 7.3 -> 7.4.
    # Use a regex that captures the trailing dot-digit so subsections shift too.
    replacements = [
        (r"\b7\.6\b", "7.7"),
        (r"\b7\.5\b", "7.6"),
        (r"\b7\.4\b", "7.5"),
        (r"\b7\.3\b", "7.4"),
    ]
    for pat, repl in replacements:
        text = re.sub(pat, repl, text)
    return text


def renumber_dev_file(src: Path, dst: Path) -> None:
    text = src.read_text(encoding="utf-8")
    text = renumber_text(text)
    dst.write_text(text, encoding="utf-8")
    if src != dst:
        src.unlink()
    print(f"  {src.name} -> {dst.name}")


def renumber_other(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    new = renumber_text(text)
    if new != text:
        path.write_text(new, encoding="utf-8")
        print(f"  rewrote {path.relative_to(MEM)}")


def main() -> None:
    print("Step 1: rename files in 07_development/ with header rewrites")
    # Reverse order so we don't clobber.
    plan = [
        ("06_discussion.md", "07_discussion.md"),
        ("05_results.md", "06_results.md"),
        ("04_experimental.md", "05_experimental.md"),
        ("03_dataset.md", "04_dataset.md"),
    ]
    for src, dst in plan:
        renumber_dev_file(DEV / src, DEV / dst)

    print("\nStep 2: rewrite cross-references in the rest of memoria/cdia/")
    for path in sorted(MEM.rglob("*.md")):
        if path.is_dir():
            continue
        if path.name in SKIP_FILES:
            continue
        # Already handled in step 1.
        if path.parent == DEV and path.name in {p[1] for p in plan}:
            continue
        renumber_other(path)

    print("\nDone. Now insert the new 03_rag.md and update INDICE.md manually.")


if __name__ == "__main__":
    main()
