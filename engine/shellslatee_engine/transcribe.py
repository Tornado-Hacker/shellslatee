from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .docs import DocumentError, extract_blocks
from .media import MediaError, extract_wav, probe_duration
from .scanner import SourceFile

TIMESTAMP_LINE = re.compile(
    r"(?P<sh>\d{1,2}):(?P<sm>\d{2}):(?P<ss>\d{2})[.,](?P<sms>\d{3})\s*-->\s*"
    r"(?P<eh>\d{1,2}):(?P<em>\d{2}):(?P<es>\d{2})[.,](?P<ems>\d{3})"
)
TAG_LINE = re.compile(r"<[^>]+>")
MAX_SEGMENTS = 20000


class TranscriberError(RuntimeError):
    pass


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Transcript:
    segments: list[Segment]
    engine: str
    model: str
    language: str = "en"
    source_hash: str = ""

    @property
    def duration(self) -> float:
        return self.segments[-1].end if self.segments else 0.0

    def plain_text(self) -> str:
        return " ".join(segment.text.strip() for segment in self.segments).strip()

    def stamped_text(self, max_chars: int = 0) -> str:
        lines = [f"[{_mmss(segment.start)}] {segment.text.strip()}" for segment in self.segments]
        text = "\n".join(lines)
        if max_chars and len(text) > max_chars:
            return text[:max_chars].rstrip() + "\n[... transcript truncated for this pass ...]"
        return text


OVERRIDE_SUFFIX = ".transcript.json"


def override_path(source_path: Path) -> Path:
    """Sidecar an operator can edit to override ASR before generation."""
    return source_path.with_name(source_path.name + OVERRIDE_SUFFIX)


def load_override(source_path: Path) -> Transcript | None:
    sidecar = override_path(source_path)
    if not sidecar.is_file():
        return None
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise TranscriberError(f"bad transcript override {sidecar.name}: {exc}") from exc
    raw_segments = data.get("segments") if isinstance(data, dict) else None
    if not isinstance(raw_segments, list) or not raw_segments:
        raise TranscriberError(f"transcript override {sidecar.name} has no segments")
    segments: list[Segment] = []
    for item in raw_segments:
        try:
            start = float(item["start"])
            end = float(item["end"])
            text = str(item["text"])
        except (KeyError, TypeError, ValueError) as exc:
            raise TranscriberError(f"bad segment in {sidecar.name}: {exc}") from exc
        segments.append(Segment(start=start, end=max(start, end), text=text))
    return Transcript(
        segments=segments,
        engine=str(data.get("engine", "override")),
        model=str(data.get("model", "edited")),
        language=str(data.get("language", "en")),
    )


@dataclass
class TranscribeSettings:
    mode: str = "auto"
    whisper_bin: str | None = None
    whisper_model: str | None = None
    language: str = "en"
    threads: int = 4
    fallback_duration: float = 600.0


def _mmss(seconds: float) -> str:
    total = max(0, int(seconds))
    minutes, secs = divmod(total, 60)
    return f"{minutes:02d}:{secs:02d}"


def parse_subtitle(text: str) -> list[Segment]:
    segments: list[Segment] = []
    blocks = re.split(r"\r?\n\s*\r?\n", text.strip())
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        stamp_index = next((i for i, line in enumerate(lines) if TIMESTAMP_LINE.search(line)), None)
        if stamp_index is None:
            continue
        match = TIMESTAMP_LINE.search(lines[stamp_index])
        assert match is not None
        start = (
            int(match["sh"]) * 3600
            + int(match["sm"]) * 60
            + int(match["ss"])
            + int(match["sms"]) / 1000
        )
        end = (
            int(match["eh"]) * 3600
            + int(match["em"]) * 60
            + int(match["es"])
            + int(match["ems"]) / 1000
        )
        body = " ".join(TAG_LINE.sub("", line) for line in lines[stamp_index + 1 :]).strip()
        if not body:
            continue
        segments.append(Segment(start=start, end=max(end, start), text=body))
        if len(segments) >= MAX_SEGMENTS:
            break
    return segments


def transcribe_subtitles(source: SourceFile) -> Transcript:
    assert source.subtitle is not None
    segments = parse_subtitle(source.subtitle.read_text(encoding="utf-8", errors="replace"))
    if not segments:
        raise TranscriberError(f"no cues parsed from {source.subtitle.name}")
    return Transcript(
        segments=segments,
        engine="subtitles",
        model=source.subtitle.suffix.lower().lstrip("."),
    )


def _resolve_whisper(settings: TranscribeSettings) -> tuple[str, Path]:
    binary = settings.whisper_bin or shutil.which("whisper-cli") or shutil.which("whisper")
    if not binary:
        raise TranscriberError(
            "whisper.cpp binary not found. Install whisper.cpp and set "
            "SHELLSLATEE_WHISPER_BIN, or run with --transcriber mock."
        )
    if settings.whisper_model:
        model = Path(settings.whisper_model).expanduser()
    else:
        raise TranscriberError(
            "no whisper model configured. Set SHELLSLATEE_WHISPER_MODEL to a ggml model file."
        )
    if not model.is_file():
        raise TranscriberError(f"whisper model not found: {model}")
    return binary, model


def transcribe_whisper(source: SourceFile, settings: TranscribeSettings) -> Transcript:
    binary, model = _resolve_whisper(settings)
    with tempfile.TemporaryDirectory(prefix="shellslatee-asr-") as tmp:
        wav = Path(tmp) / "audio.wav"
        extract_wav(source.path, wav)
        prefix = Path(tmp) / "out"
        result = subprocess.run(
            [
                binary,
                "-m", str(model),
                "-f", str(wav),
                "-l", settings.language,
                "-t", str(settings.threads),
                "-oj",
                "-of", str(prefix),
                "-np",
            ],
            capture_output=True,
            text=True,
            timeout=6 * 3600,
        )
        if result.returncode != 0:
            raise TranscriberError(
                f"whisper.cpp failed for {source.path.name}: {result.stderr.strip()[:300]}"
            )
        json_path = prefix.with_suffix(".json")
        if not json_path.is_file():
            raise TranscriberError("whisper.cpp produced no JSON output")
        payload = json.loads(json_path.read_text(encoding="utf-8"))

    raw_segments = payload.get("transcription") or []
    segments = [
        Segment(
            start=float(item.get("offsets", {}).get("from", 0)) / 1000.0,
            end=float(item.get("offsets", {}).get("to", 0)) / 1000.0,
            text=str(item.get("text", "")).strip(),
        )
        for item in raw_segments
        if str(item.get("text", "")).strip()
    ]
    if not segments:
        raise TranscriberError(f"whisper.cpp returned no segments for {source.path.name}")
    return Transcript(
        segments=segments,
        engine="whisper.cpp",
        model=Path(model).name,
        language=settings.language,
    )


_MOCK_SENTENCES = (
    "Welcome back to the lesson.",
    "Today we start with the core idea and why it matters in practice.",
    "Let's walk through an example so the shape of it becomes concrete.",
    "Notice how each step builds on the one before it.",
    "Here is the part people usually get wrong on the first pass.",
    "Write that down, because everything later depends on it.",
    "Now we generalize the idea to a slightly harder case.",
    "Compare this with the earlier approach and see what changed.",
    "The trade-offs here are the whole point of the discussion.",
    "Let's summarize where we are before moving on.",
    "One more example, this time with the edge case included.",
    "That is the idea in full: simple rule, careful application.",
)


def transcribe_mock(source: SourceFile) -> Transcript:
    try:
        duration = probe_duration(source.path)
    except MediaError:
        duration = TranscribeSettings().fallback_duration
    duration = max(duration, 60.0)
    step = 25.0
    segments: list[Segment] = []
    index = 0
    cursor = 0.0
    while cursor < duration and len(segments) < MAX_SEGMENTS:
        sentence = _MOCK_SENTENCES[index % len(_MOCK_SENTENCES)]
        segments.append(Segment(start=cursor, end=min(cursor + step, duration), text=sentence))
        cursor += step
        index += 1
    return Transcript(segments=segments, engine="mock", model="mock")


def transcribe_document(source: SourceFile) -> Transcript:
    if source.kind != "document":
        raise TranscriberError(f"{source.path.name} is not a document source")
    try:
        blocks = extract_blocks(source.path)
    except DocumentError as exc:
        raise TranscriberError(str(exc)) from exc
    segments = [
        Segment(start=float(index), end=float(index) + 1.0, text=f"[{label}] {text}")
        for index, (label, text) in enumerate(blocks)
    ]
    if not segments:
        raise TranscriberError(f"no extractable text in {source.path.name}")
    return Transcript(
        segments=segments,
        engine="document",
        model=source.path.suffix.lower().lstrip("."),
        language="",
    )


def transcribe_source(source: SourceFile, settings: TranscribeSettings) -> Transcript:
    override = load_override(source.path)
    if override is not None:
        return override
    if source.kind == "document":
        return transcribe_document(source)
    mode = settings.mode
    if mode == "mock":
        return transcribe_mock(source)
    if mode in {"auto", "subs"} and source.subtitle is not None:
        return transcribe_subtitles(source)
    if mode == "subs":
        raise TranscriberError(f"no subtitle file beside {source.path.name}")
    if mode == "whisper":
        return transcribe_whisper(source, settings)
    if mode == "auto":
        try:
            return transcribe_whisper(source, settings)
        except TranscriberError as exc:
            raise TranscriberError(
                f"{exc} (no subtitle file beside {source.path.name})"
            ) from exc
    raise TranscriberError(f"unknown transcriber mode: {mode}")
