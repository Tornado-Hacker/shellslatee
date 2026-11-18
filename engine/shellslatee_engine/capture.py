"""Quick capture: append short notes to ``OUT/_inbox/YYYY-MM-DD.md``.

A frictionless entry point for ideas that arrive mid-study. Captures are plain
Markdown bullets so the inbox works in any editor and never blocks the pipeline.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .util import atomic_write


def capture(out_root: Path, text: str, tag: str | None = None) -> dict[str, str]:
    cleaned = " ".join(text.split())
    if not cleaned:
        raise ValueError("capture text is empty")
    now = datetime.now()
    day = now.strftime("%Y-%m-%d")
    clock = now.strftime("%H:%M")
    line = f"- {clock} — {cleaned}"
    if tag:
        line += f" #{tag.lstrip('#')}"
    directory = out_root / "_inbox"
    path = directory / f"{day}.md"
    if path.is_file():
        existing = path.read_text(encoding="utf-8", errors="replace")
        if not existing.endswith("\n"):
            existing += "\n"
    else:
        existing = f"# Inbox — {day}\n\n"
    atomic_write(path, existing + line + "\n")
    return {"path": path.relative_to(out_root).as_posix(), "line": line}
