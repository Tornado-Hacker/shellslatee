from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .docs import DOC_EXTS

VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v", ".mpg", ".mpeg", ".wmv", ".flv"}
AUDIO_EXTS = {".mp3", ".m4a", ".wav", ".flac", ".ogg", ".opus", ".aac"}
SUBTITLE_EXTS = {".srt", ".vtt", ".ass", ".ssa"}
MAX_DEPTH = 16


@dataclass(frozen=True)
class SourceFile:
    path: Path
    rel: Path
    kind: str
    size: int
    subtitle: Path | None

    @property
    def stem(self) -> str:
        return self.path.stem


class ScanError(RuntimeError):
    pass


def scan(root: Path, exclude: tuple[Path, ...] = ()) -> list[SourceFile]:
    root = root.resolve()
    if not root.is_dir():
        raise ScanError(f"source folder not found: {root}")

    excluded = {p.resolve() for p in exclude}
    found: list[SourceFile] = []

    for current, dirnames, filenames in os.walk(root, topdown=True):
        current_path = Path(current)
        depth = len(current_path.relative_to(root).parts)

        dirnames[:] = sorted(
            name
            for name in dirnames
            if not name.startswith(".")
            and (current_path / name).resolve() not in excluded
        )
        if depth >= MAX_DEPTH:
            dirnames[:] = []

        subtitle_stems = {
            Path(name).stem.lower(): current_path / name
            for name in filenames
            if Path(name).suffix.lower() in SUBTITLE_EXTS
        }

        for name in sorted(filenames):
            if name.startswith("."):
                continue
            path = current_path / name
            suffix = path.suffix.lower()
            if suffix in VIDEO_EXTS:
                kind = "video"
            elif suffix in AUDIO_EXTS:
                kind = "audio"
            elif suffix in DOC_EXTS:
                kind = "document"
            else:
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            found.append(
                SourceFile(
                    path=path,
                    rel=path.relative_to(root),
                    kind=kind,
                    size=size,
                    subtitle=subtitle_stems.get(path.stem.lower()),
                )
            )

    found.sort(key=lambda item: str(item.rel).lower())
    return found
