"""Environment readiness checks shared by `shellslatee doctor` and /api/doctor."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any

from . import keychain
from .frames import ocr_backend

# Every check the product needs for a video lesson to finish. The rest are
# optional capabilities; `ready` only looks at these.
REQUIRED = ("python 3.10+", "ffmpeg", "ffprobe", "whisper.cpp", "whisper model")


def checks() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str) -> None:
        rows.append({"name": name, "ok": bool(ok), "detail": detail})

    add("python 3.10+", sys.version_info >= (3, 10), sys.version.split()[0])
    for tool in ("ffmpeg", "ffprobe"):
        path = shutil.which(tool)
        add(tool, bool(path), path or "not found — install ffmpeg")

    whisper = (
        os.environ.get("SHELLSLATEE_WHISPER_BIN")
        or shutil.which("whisper-cli")
        or shutil.which("whisper")
    )
    add(
        "whisper.cpp",
        bool(whisper),
        whisper or "not found — subtitles or --transcriber mock still work",
    )

    model = os.environ.get("SHELLSLATEE_WHISPER_MODEL")
    add(
        "whisper model",
        bool(model and Path(model).is_file()),
        model or "set SHELLSLATEE_WHISPER_MODEL to a ggml model",
    )

    backend = ocr_backend()
    add(
        "ocr engine",
        bool(backend),
        backend + " — on-screen capture enabled"
        if backend
        else "none — install rapidocr-onnxruntime or tesseract for on-screen notes",
    )

    for env_name in ("AIKEY_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY"):
        value = os.environ.get(env_name)
        add(env_name, bool(value), "set" if value else "not set")

    key_file = Path("~/.config/shellslatee/aikey_key").expanduser()
    have_file_key = key_file.is_file() and bool(
        key_file.read_text(encoding="utf-8").strip()
    )
    add(
        "aikey key file",
        have_file_key,
        str(key_file)
        if have_file_key
        else f"missing {key_file} (or set AIKEY_API_KEY)",
    )

    add(
        "os keychain",
        True,
        keychain.backend_label()
        if keychain.available()
        else "none — key file or env is the default",
    )
    add("documents", True, "pdf (poppler or stdlib), pptx, docx")
    return rows


def ready(rows: list[dict[str, Any]] | None = None) -> bool:
    """True only when every required capability is present and green."""
    rows = checks() if rows is None else rows
    present = {str(row["name"]): bool(row["ok"]) for row in rows}
    return all(present.get(name) is True for name in REQUIRED)


def render(rows: list[dict[str, Any]] | None = None) -> list[str]:
    rows = checks() if rows is None else rows
    width = max(len(str(row["name"])) for row in rows)
    lines: list[str] = []
    for row in rows:
        status = "ok  " if row["ok"] else "miss"
        lines.append(f"{status} {str(row['name']):<{width}}  {row['detail']}")
    return lines
