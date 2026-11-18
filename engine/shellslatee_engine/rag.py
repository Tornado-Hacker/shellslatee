"""Course-wide retrieval and grounded answering.

Searches the vault's full-text index (falling back to a keyword scan when no
index exists), stitches the top sections into a context block with lesson +
timestamp citations, and asks the model to answer using only that context. The
returned citations point back at a lesson note and, where the section heading
carries a timestamp, at the second in the video.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .indexdb import IndexError_, search as search_index
from .providers import Provider, ProviderError, chat

MAX_CONTEXT_CHARS = 9000
MAX_CITATIONS = 8
STAMP_RE = re.compile(r"^(?P<stamp>\d{1,2}:\d{2}(?::\d{2})?)")

COURSE_SYSTEM = (
    "You are the study assistant inside Shellslatee. You answer questions about a "
    "whole course using ONLY the provided note excerpts, each tagged with a "
    "citation number and a lesson. Synthesize across excerpts when useful. Cite "
    "the excerpts you used inline as [1], [2], and so on. If the excerpts do not "
    "cover the question, say so plainly instead of guessing. Never invent facts, "
    "numbers, or examples."
)


@dataclass
class Citation:
    n: int
    rel: str
    title: str
    section: str
    start: int | None
    snippet: str


@dataclass
class CourseAnswer:
    answer: str
    citations: list[Citation] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0


def _stamp_seconds(section: str) -> int | None:
    match = STAMP_RE.match(section.strip())
    if not match:
        return None
    parts = [int(part) for part in match.group("stamp").split(":")]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return parts[0] * 60 + parts[1]


def _keyword_fallback(out_root: Path, question: str, limit: int) -> list[dict[str, str]]:
    words = [word.lower() for word in re.findall(r"\w+", question) if len(word) > 2]
    if not words:
        return []
    hits: list[dict[str, str]] = []
    for path in sorted(out_root.rglob("*.md")):
        relative = path.relative_to(out_root)
        if any(part.startswith((".", "_")) for part in relative.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        body = text
        if text.startswith("---"):
            end = text.find("\n---", 3)
            if end != -1:
                body = text[end + 4 :]
        title = relative.stem
        section = ""
        start = None
        buffer: list[str] = []
        for line in body.splitlines() + [""]:
            stripped = line.strip()
            if stripped.startswith("#"):
                if buffer and any(word in " ".join(buffer).lower() for word in words):
                    hits.append(
                        {
                            "path": relative.as_posix(),
                            "title": title,
                            "section": section,
                            "snippet": " ".join(buffer)[:240],
                            "start": str(start) if start is not None else "",
                        }
                    )
                heading = stripped.lstrip("# ").strip()
                match = STAMP_RE.match(heading)
                start = _stamp_seconds(heading) if match else None
                section = heading.split("—", 1)[-1].strip()
                buffer = []
                continue
            if stripped:
                buffer.append(stripped)
        if len(hits) >= limit:
            break
    return hits[:limit]


def _order(rows: list[dict[str, str]], per_lesson: int = 3) -> list[dict[str, str]]:
    """Drop repeats and stop one lesson eating the whole citation list.

    Sections that carry a video timestamp go first, so the reader can always
    jump to the moment instead of re-reading prose. Vault scaffolding
    (`README.md`, `_index.md`, `_glossary.md`) is navigation, not source.
    """
    seen: set[tuple[str, str]] = set()
    per_path: dict[str, int] = {}
    stamped: list[dict[str, str]] = []
    plain: list[dict[str, str]] = []
    for row in rows:
        section = str(row.get("section", ""))
        path = str(row.get("path", ""))
        base = path.rsplit("/", 1)[-1]
        if base.startswith("_") or base.lower() == "readme.md":
            continue
        key = (path, section)
        if key in seen or per_path.get(path, 0) >= per_lesson:
            continue
        seen.add(key)
        per_path[path] = per_path.get(path, 0) + 1
        has_stamp = row.get("start") not in (None, "") or _stamp_seconds(section) is not None
        (stamped if has_stamp else plain).append(row)
    return stamped + plain


def retrieve(out_root: Path, question: str, limit: int = MAX_CITATIONS) -> list[Citation]:
    rows: list[dict[str, str]]
    try:
        rows = search_index(out_root, question, limit)
    except (IndexError_, ValueError):
        rows = _keyword_fallback(out_root, question, limit)

    citations: list[Citation] = []
    for index, row in enumerate(_order(rows)[:limit], start=1):
        section = str(row.get("section", ""))
        raw_start = row.get("start")
        start = int(raw_start) if raw_start not in (None, "") else _stamp_seconds(section)
        citations.append(
            Citation(
                n=index,
                rel=str(row.get("path", "")),
                title=str(row.get("title", "")),
                section=section,
                start=start,
                snippet=str(row.get("snippet", "")).strip(),
            )
        )
    return citations


def _context_block(citations: list[Citation]) -> str:
    blocks: list[str] = []
    used = 0
    for citation in citations:
        header = f"[{citation.n}] {citation.title}"
        if citation.section:
            header += f" — {citation.section}"
        if citation.start is not None:
            header += f" (at {_mmss(citation.start)})"
        entry = f"{header}\n{citation.snippet}"
        if used + len(entry) > MAX_CONTEXT_CHARS:
            break
        blocks.append(entry)
        used += len(entry)
    return "\n\n".join(blocks)


def _mmss(seconds: int) -> str:
    hours, rem = divmod(max(0, seconds), 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def answer(
    provider: Provider,
    model: str,
    api_key: str,
    *,
    out_root: Path,
    question: str,
) -> CourseAnswer:
    citations = retrieve(out_root, question)
    if provider.name == "mock":
        text = (
            f"Mock course answer for “{question.strip()}”. "
            f"I found {len(citations)} matching section(s) across the vault. "
            "Wire a real provider for a grounded, synthesized answer."
        )
        return CourseAnswer(answer=text, citations=citations)

    if not citations:
        return CourseAnswer(
            answer="I could not find anything in this course's notes that covers that yet.",
            citations=[],
        )

    user = (
        "Course note excerpts:\n\n"
        f"{_context_block(citations)}\n\n"
        f"Question: {question.strip()}"
    )
    raw, tokens = chat(
        provider,
        model,
        api_key,
        [{"role": "system", "content": COURSE_SYSTEM}, {"role": "user", "content": user}],
        json_mode=False,
        temperature=0.3,
    )
    return CourseAnswer(
        answer=raw.strip(),
        citations=citations,
        tokens_in=int((tokens or {}).get("in", 0)),
        tokens_out=int((tokens or {}).get("out", 0)),
    )
