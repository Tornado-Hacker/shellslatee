"""Document ingestion: turn PDF / PPTX / DOCX sources into ordered text blocks.

Each extractor returns ``[(label, text), ...]`` where the label names the unit
("Slide 12", "Page 3", "Para 7").  PPTX and DOCX are parsed with the standard
library (both are ZIP + XML).  PDF prefers the ``pdftotext`` binary from
poppler when present and otherwise falls back to a small, best-effort parser
for the text-showing operators -- enough for slides, papers, and lecture
handouts, not for scanned or heavily subset-fonted PDFs.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
import zipfile
import zlib
from pathlib import Path

DOC_EXTS = {".pdf", ".pptx", ".docx"}
MAX_BLOCKS = 5000
MAX_BLOCK_CHARS = 2_000_000

_A_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

_SLIDE_RE = re.compile(r"^ppt/slides/slide(\d+)\.xml$")
_PDF_STREAM_RE = re.compile(rb"(?<!end)stream\r?\n")
_PDF_TEXT_STRING = re.compile(r"\((?:\\.|[^\\()])*\)", re.S)
_PDF_TEXT_OP = re.compile(r"\((?:\\.|[^\\()])*\)|\bT[dD*]\b|'|\"", re.S)
_PDF_TEXT_OBJECT = re.compile(r"BT(.*?)ET", re.S)


class DocumentError(RuntimeError):
    pass


def is_document(path: Path) -> bool:
    return path.suffix.lower() in DOC_EXTS


def _clip(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:MAX_BLOCK_CHARS]


def _pptx_blocks(path: Path) -> list[tuple[str, str]]:
    try:
        with zipfile.ZipFile(path) as archive:
            slides: list[tuple[int, str]] = []
            for name in archive.namelist():
                match = _SLIDE_RE.match(name)
                if not match:
                    continue
                try:
                    root = ET.fromstring(archive.read(name))
                except ET.ParseError as exc:
                    raise DocumentError(f"bad slide XML in {path.name}: {exc}") from exc
                parts = [node.text or "" for node in root.iter(f"{_A_NS}t")]
                text = _clip("\n".join(part for part in parts if part.strip()))
                if text:
                    slides.append((int(match.group(1)), text))
    except zipfile.BadZipFile as exc:
        raise DocumentError(f"not a valid PPTX (zip) file: {path.name}") from exc
    slides.sort(key=lambda item: item[0])
    return [(f"Slide {index}", text) for index, text in slides[:MAX_BLOCKS]]


def _docx_blocks(path: Path) -> list[tuple[str, str]]:
    try:
        with zipfile.ZipFile(path) as archive:
            raw = archive.read("word/document.xml")
    except KeyError as exc:
        raise DocumentError(f"{path.name} has no word/document.xml") from exc
    except zipfile.BadZipFile as exc:
        raise DocumentError(f"not a valid DOCX (zip) file: {path.name}") from exc
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise DocumentError(f"bad document XML in {path.name}: {exc}") from exc
    blocks: list[tuple[str, str]] = []
    for paragraph in root.iter(f"{_W_NS}p"):
        parts = [node.text or "" for node in paragraph.iter(f"{_W_NS}t")]
        text = _clip("".join(parts))
        if text:
            blocks.append((f"Para {len(blocks) + 1}", text))
        if len(blocks) >= MAX_BLOCKS:
            break
    return blocks


def _pdf_unescape(raw: str) -> str:
    out: list[str] = []
    i = 0
    escapes = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f"}
    while i < len(raw):
        char = raw[i]
        if char == "\\" and i + 1 < len(raw):
            nxt = raw[i + 1]
            if nxt in escapes:
                out.append(escapes[nxt])
                i += 2
            elif nxt in "()\\":
                out.append(nxt)
                i += 2
            elif nxt in "01234567":
                digits = ""
                j = i + 1
                while j < len(raw) and len(digits) < 3 and raw[j] in "01234567":
                    digits += raw[j]
                    j += 1
                out.append(chr(int(digits, 8)))
                i = j
            elif nxt in "\r\n":
                i += 2
            else:
                out.append(nxt)
                i += 2
        else:
            out.append(char)
            i += 1
    return "".join(out)


def _pdf_content_text(content: str) -> str:
    pieces: list[str] = []
    for block in _PDF_TEXT_OBJECT.finditer(content):
        for token in _PDF_TEXT_OP.finditer(block.group(1)):
            value = token.group(0)
            if value.startswith("("):
                pieces.append(_pdf_unescape(value[1:-1]))
            else:
                pieces.append("\n")
    return _clip("".join(pieces))


def _pdf_streams(data: bytes) -> list[bytes]:
    out: list[bytes] = []
    for match in _PDF_STREAM_RE.finditer(data):
        start = match.end()
        end = data.find(b"endstream", start)
        if end == -1:
            break
        raw = data[start:end]
        if raw.endswith(b"\r\n"):
            raw = raw[:-2]
        elif raw.endswith(b"\n") or raw.endswith(b"\r"):
            raw = raw[:-1]
        try:
            out.append(zlib.decompress(raw))
        except zlib.error:
            out.append(raw)
    return out


def _pdf_blocks_stdlib(path: Path) -> list[tuple[str, str]]:
    data = path.read_bytes()
    if b"%PDF" not in data[:1024]:
        raise DocumentError(f"not a PDF file: {path.name}")
    blocks: list[tuple[str, str]] = []
    for raw in _pdf_streams(data):
        try:
            text = _pdf_content_text(raw.decode("latin-1", errors="replace"))
        except Exception:  # noqa: BLE001 - corrupt streams are skipped, not fatal
            continue
        if text:
            blocks.append((f"Page {len(blocks) + 1}", text))
        if len(blocks) >= MAX_BLOCKS:
            break
    return blocks


def _pdf_blocks_pdftotext(path: Path) -> list[tuple[str, str]]:
    tool = shutil.which("pdftotext")
    assert tool is not None
    result = subprocess.run(
        [tool, "-layout", "-q", str(path), "-"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise DocumentError(f"pdftotext failed for {path.name}: {result.stderr.strip()[:300]}")
    blocks: list[tuple[str, str]] = []
    for page in result.stdout.split("\f"):
        text = _clip(page)
        if text:
            blocks.append((f"Page {len(blocks) + 1}", text))
        if len(blocks) >= MAX_BLOCKS:
            break
    return blocks


def _pdf_blocks(path: Path, use_tool: bool = True) -> list[tuple[str, str]]:
    if use_tool and shutil.which("pdftotext"):
        return _pdf_blocks_pdftotext(path)
    return _pdf_blocks_stdlib(path)


def extract_blocks(path: Path) -> list[tuple[str, str]]:
    """Ordered (label, text) blocks for a document source."""
    suffix = path.suffix.lower()
    if not path.is_file():
        raise DocumentError(f"document not found: {path}")
    if suffix == ".pptx":
        blocks = _pptx_blocks(path)
    elif suffix == ".docx":
        blocks = _docx_blocks(path)
    elif suffix == ".pdf":
        blocks = _pdf_blocks(path)
    else:
        raise DocumentError(f"unsupported document type {suffix}: {path.name}")
    if not blocks:
        raise DocumentError(
            f"no extractable text in {path.name} (scanned PDFs need OCR; "
            "install poppler-utils for better PDF extraction)"
        )
    return blocks
