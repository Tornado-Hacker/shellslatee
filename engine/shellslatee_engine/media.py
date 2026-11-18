from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class MediaError(RuntimeError):
    pass


def find_tool(name: str) -> str | None:
    return shutil.which(name)


def require_tool(name: str, hint: str) -> str:
    found = find_tool(name)
    if not found:
        raise MediaError(f"{name} not found on PATH. {hint}")
    return found


def probe_duration(path: Path) -> float:
    ffprobe = require_tool("ffprobe", "Install ffmpeg (which ships ffprobe) and try again.")
    result = subprocess.run(
        [
            ffprobe,
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise MediaError(f"ffprobe failed for {path.name}: {result.stderr.strip()[:300]}")
    try:
        return float(result.stdout.strip())
    except ValueError as exc:
        raise MediaError(f"ffprobe returned no duration for {path.name}") from exc


def extract_wav(path: Path, dest: Path) -> None:
    ffmpeg = require_tool("ffmpeg", "Install ffmpeg and try again.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            ffmpeg,
            "-nostdin",
            "-hide_banner",
            "-loglevel", "error",
            "-y",
            "-i", str(path),
            "-vn",
            "-ac", "1",
            "-ar", "16000",
            "-c:a", "pcm_s16le",
            str(dest),
        ],
        capture_output=True,
        text=True,
        timeout=3600,
    )
    if result.returncode != 0:
        raise MediaError(f"ffmpeg decode failed for {path.name}: {result.stderr.strip()[:300]}")
