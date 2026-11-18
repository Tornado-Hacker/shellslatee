from __future__ import annotations

from pathlib import Path

from .scanner import SourceFile
from .util import slugify


def note_path(out_root: Path, source: SourceFile, used: set[Path]) -> Path:
    parent = out_root / source.rel.parent
    stem = slugify(source.stem)
    candidate = parent / f"{stem}.md"
    counter = 2
    while candidate in used:
        candidate = parent / f"{stem}-{counter}.md"
        counter += 1
    used.add(candidate)
    return candidate


def module_of(rel: Path) -> str:
    parent = rel.parent.as_posix()
    return "" if parent == "." else parent


def video_uri(source: SourceFile) -> str:
    from urllib.parse import quote

    absolute = source.path.resolve().as_posix()
    return "file://" + quote(absolute, safe="/:")
