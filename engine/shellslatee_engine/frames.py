"""Visual note harvesting: sample video frames and OCR the on-screen text.

The transcript only carries what is spoken. Slides, terminal panes, request
headers, browser devtools and code editors carry the rest. This module pulls
still frames on a fixed cadence, reads the text out of each one with a local OCR
engine, and drops near-duplicate frames so a static slide is captured once.

OCR is optional and stays on the machine: RapidOCR (in-process, no system
binaries) is preferred, then a `tesseract` binary if present. Neither is a
required dependency — without one the pipeline simply falls back to audio only.
"""

from __future__ import annotations

import difflib
import importlib.util
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

DEFAULT_INTERVAL = 5.0
DEFAULT_MAX_FRAMES = 120
MIN_TEXT_CHARS = 12
SIMILAR_RATIO = 0.90
RAPIDOCR_MIN_SCORE = 0.50


class FramesError(RuntimeError):
    pass


@dataclass
class VisualNote:
    start: float
    text: str


def ocr_backend() -> str | None:
    """Return the OCR engine name that is available, or None."""
    if importlib.util.find_spec("rapidocr_onnxruntime") is not None:
        return "rapidocr"
    if shutil.which("tesseract"):
        return "tesseract"
    return None


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _similar(left: str, right: str) -> bool:
    if not left or not right:
        return False
    return difflib.SequenceMatcher(None, left, right).ratio() >= SIMILAR_RATIO


def _frame_timestamp(index: int, interval: float) -> float:
    return round(index * interval, 2)


def extract_frames(
    video: Path,
    dest: Path,
    interval: float = DEFAULT_INTERVAL,
    max_frames: int = DEFAULT_MAX_FRAMES,
) -> list[tuple[Path, float]]:
    """Decode one still every ``interval`` seconds into ``dest``.

    Returns ``(path, seconds)`` pairs in order. Bounded by ``max_frames`` so a
    long recording cannot flood the disk or the OCR pass.
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise FramesError("ffmpeg not found on PATH — needed to sample frames")
    dest.mkdir(parents=True, exist_ok=True)
    interval = max(0.5, float(interval))
    max_frames = max(1, int(max_frames))
    pattern = dest / "frame_%05d.jpg"
    result = subprocess.run(
        [
            ffmpeg,
            "-nostdin",
            "-hide_banner",
            "-loglevel", "error",
            "-y",
            "-i", str(video),
            "-vf", f"fps=1/{interval}",
            "-frames:v", str(max_frames),
            "-q:v", "3",
            str(pattern),
        ],
        capture_output=True,
        text=True,
        timeout=1800,
    )
    if result.returncode != 0:
        raise FramesError(f"ffmpeg frame sampling failed: {result.stderr.strip()[:300]}")
    frames: list[tuple[Path, float]] = []
    for index, path in enumerate(sorted(dest.glob("frame_*.jpg"))):
        frames.append((path, _frame_timestamp(index, interval)))
    return frames


def _ocr_rapidocr(paths: list[Path]) -> list[str]:
    from rapidocr_onnxruntime import RapidOCR  # type: ignore

    engine = RapidOCR()
    texts: list[str] = []
    for path in paths:
        result, _ = engine(str(path))
        lines = [
            str(entry[1]).strip()
            for entry in (result or [])
            if len(entry) > 2 and float(entry[2]) >= RAPIDOCR_MIN_SCORE and str(entry[1]).strip()
        ]
        texts.append("\n".join(lines))
    return texts


def _ocr_tesseract(paths: list[Path]) -> list[str]:
    binary = shutil.which("tesseract")
    if not binary:
        raise FramesError("tesseract not found on PATH")
    texts: list[str] = []
    for path in paths:
        result = subprocess.run(
            [binary, str(path), "stdout", "--psm", "6"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        texts.append(result.stdout.strip() if result.returncode == 0 else "")
    return texts


def harvest_visual_notes(
    video: Path,
    workdir: Path,
    interval: float = DEFAULT_INTERVAL,
    max_frames: int = DEFAULT_MAX_FRAMES,
    keep_frames: bool = False,
) -> tuple[list[VisualNote], str]:
    """Sample ``video``, OCR each frame, and return deduped visual notes.

    The second return value is the OCR engine used. Raises ``FramesError`` when
    no engine or ffmpeg is available so the caller can decide to continue.
    """
    backend = ocr_backend()
    if not backend:
        raise FramesError(
            "no OCR engine found — install rapidocr-onnxruntime or tesseract to capture on-screen text"
        )
    frames = extract_frames(video, workdir, interval=interval, max_frames=max_frames)
    if not frames:
        return [], backend
    paths = [path for path, _ in frames]
    texts = _ocr_rapidocr(paths) if backend == "rapidocr" else _ocr_tesseract(paths)

    notes: list[VisualNote] = []
    previous = ""
    for (path, stamp), raw in zip(frames, texts):
        text = _tidy(raw)
        normalized = _normalize(text)
        if len(normalized) < MIN_TEXT_CHARS:
            continue
        if _similar(previous, normalized):
            continue
        notes.append(VisualNote(start=stamp, text=text))
        previous = normalized

    if not keep_frames:
        shutil.rmtree(workdir, ignore_errors=True)
    return notes, backend


def _tidy(raw: str) -> str:
    lines = [line.strip() for line in raw.replace("\r", "\n").split("\n")]
    kept = [line for line in lines if line]
    return "\n".join(kept)
