from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .generate import Note
from .util import fmt_ts, pretty_name, rel_link, slugify

BEGIN_PREFIX = "<!-- shellslatee:begin"
END_MARK = "<!-- shellslatee:end -->"
MANAGED_RE = re.compile(
    r"<!-- shellslatee:begin[^>]*-->(?s:.*?)<!-- shellslatee:end -->",
    re.DOTALL,
)


@dataclass
class NoteRecord:
    module: str
    lesson_rel: str
    title: str
    summary: str
    duration: float
    concepts: list[str]
    tags: list[str]


def _yaml_value(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _yaml_list(values: list[str]) -> str:
    return "[" + ", ".join(_yaml_value(item) for item in values) + "]"


def render_note(note: Note, meta) -> str:
    concepts = note.concept_names()
    concept_slugs = [f"con_{slugify(name)}" for name in concepts]
    video_link = meta.source_rel
    lines: list[str] = []
    lines.append("---")
    lines.append(f"title: {_yaml_value(note.title)}")
    lines.append(f"id: {meta.note_id}")
    lines.append(f"course: {_yaml_value(meta.course_title)}")
    lines.append(f"module: {_yaml_value(meta.module)}")
    lines.append(f"order: {meta.order}")
    lines.append(f"source: {_yaml_value(video_link)}")
    lines.append(f"source_hash: {_yaml_value(meta.source_hash)}")
    lines.append(f"duration: {int(meta.duration)}")
    lines.append(f"transcribed_with: {_yaml_value(meta.engine + ' · ' + meta.asr_model)}")
    lines.append(f"notes_model: {_yaml_value(meta.provider + ' · ' + meta.model)}")
    lines.append(f"generated: {_yaml_value(meta.generated)}")
    lines.append(f"generation: {meta.generation}")
    lines.append(f"template: {_yaml_value(note.template)}")
    lines.append(f"quality: {note.quality}")
    lines.append(f"concepts: {_yaml_list(concept_slugs)}")
    lines.append(f"tags: {_yaml_list(note.tags)}")
    lines.append("---")
    lines.append("")
    lines.append(f"<!-- shellslatee:begin id={meta.note_id} gen={meta.generation} -->")
    lines.append(f"# {note.title}")
    lines.append("")
    lines.append(f"> **TL;DR** — {note.summary}")
    lines.append("")
    lines.append("## Key concepts")
    for concept in note.key_concepts:
        if concept["definition"]:
            lines.append(f"- **{concept['name']}** — {concept['definition']}")
        else:
            lines.append(f"- **{concept['name']}**")
    lines.append("")
    lines.append("## Walkthrough")
    for topic in note.topics:
        stamp = fmt_ts(topic["start"])
        lines.append(f"### {stamp} — {topic['title']}")
        lines.append(f"[▶ jump to {stamp}]({video_link}#t={int(topic['start'])})")
        lines.append("")
        for detail in topic["details"]:
            lines.append(f"- {detail}")
        lines.append("")
    visual = getattr(meta, "extra", {}).get("visual") if getattr(meta, "extra", None) else None
    if visual:
        lines.append("## On-screen notes")
        lines.append("")
        lines.append("_OCR text captured from the video frames; minor character errors are possible._")
        lines.append("")
        for block in visual:
            stamp = fmt_ts(float(block.get("start", 0) or 0))
            lines.append(f"**{stamp}**")
            lines.append("")
            lines.append("```text")
            lines.append(str(block.get("text", "")).strip())
            lines.append("```")
            lines.append("")
    lines.append("## Review questions")
    for index, question in enumerate(note.review_questions, start=1):
        lines.append(f"{index}. {question}")
    lines.append("")
    lines.append("## Source")
    lines.append(f"[Open video]({video_link}) · duration {fmt_ts(meta.duration)}")
    lines.append("<!-- shellslatee:end -->")
    lines.append("")
    lines.append("## My notes")
    lines.append("")
    lines.append("<!-- write anything here; regeneration never touches this section -->")
    lines.append("")
    return "\n".join(lines)


def merge_managed(existing: str, generated: str) -> str:
    match = MANAGED_RE.search(generated)
    if not match:
        return generated
    new_block = match.group(0)
    old = MANAGED_RE.search(existing)
    if old:
        return existing[: old.start()] + new_block + existing[old.end() :]
    if existing.strip():
        return new_block + "\n\n" + existing
    return generated


def write_note(path: Path, note: Note, meta) -> None:
    from .util import atomic_write

    generated = render_note(note, meta)
    if path.exists():
        existing = path.read_text(encoding="utf-8", errors="replace")
        atomic_write(path, merge_managed(existing, generated))
    else:
        atomic_write(path, generated)


def _anchor(text: str, limit: int = 120) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def render_module_index(
    module: str,
    records: list[NoteRecord],
    out_root: Path,
    index_path: Path,
    concepts: dict[str, dict] | None = None,
) -> str:
    title = pretty_name(module) if module else "Course root"
    total_seconds = sum(record.duration for record in records)
    lines = [f"# {title}", ""]
    lines.append(f"{len(records)} lesson(s) · {fmt_ts(total_seconds)} of video.")
    lines.append("")
    lines.append("## Overview")
    lines.append("")
    seen: dict[str, int] = {}
    for record in records:
        for slug in record.concepts:
            seen[slug] = seen.get(slug, 0) + 1
    ordered = sorted(
        seen.items(),
        key=lambda item: (-item[1], (concepts or {}).get(item[0], {}).get("name", item[0])),
    )
    concept_names = [
        (concepts or {}).get(slug, {}).get("name", slug.replace("con_", "").replace("-", " "))
        for slug, _count in ordered
    ]
    summary = (
        f"This module walks through {len(records)} lesson(s) over {fmt_ts(total_seconds)} of "
        f"video."
    )
    if concept_names:
        summary += f" It centers on {', '.join(concept_names[:8])}"
        summary += "." if len(concept_names) <= 8 else ", and related ideas."
    lines.append(summary)
    lines.append("")
    lines.append("## Lessons")
    for record in sorted(records, key=lambda item: item.lesson_rel):
        lesson_path = out_root / record.lesson_rel
        link = rel_link(lesson_path, index_path.parent)
        lines.append(f"- [{record.title}]({link}) — {_anchor(record.summary, 100)}")
    lines.append("")
    return "\n".join(lines)


def render_readme(course_title: str, records: list[NoteRecord], out_root: Path) -> str:
    total_seconds = sum(record.duration for record in records)
    modules: dict[str, list[NoteRecord]] = {}
    for record in records:
        modules.setdefault(record.module, []).append(record)

    lines = [f"# {course_title}", ""]
    lines.append(f"{len(records)} lesson(s) · {fmt_ts(total_seconds)} of video · generated by Shellslatee.")
    lines.append("")
    lines.append("## Modules")
    for module in sorted(modules):
        lessons = sorted(modules[module], key=lambda item: item.lesson_rel)
        if module:
            index_rel = f"{module}/_index.md"
            lines.append(f"### [{pretty_name(module)}]({index_rel})")
        else:
            lines.append("### Root")
        for record in lessons:
            lines.append(f"- [{record.title}]({record.lesson_rel})")
        lines.append("")
    lines.append("## How this vault works")
    lines.append("- Each lesson note mirrors its source video path.")
    lines.append("- Timestamps link straight to the moment in the video.")
    lines.append("- Concept pages live in `_concepts/` and link every lesson that covers them.")
    lines.append("- `_glossary.md` is generated; edit notes, not the glossary.")
    lines.append("")
    return "\n".join(lines)


LINKED_HEADING = "## Linked passages"


def _linked_passages(path: Path) -> list[str]:
    """Bullets a reader linked to this concept, preserved across re-indexing."""
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == LINKED_HEADING)
    except StopIteration:
        return []
    collected: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        collected.append(line.rstrip())
    while collected and not collected[0].strip():
        collected.pop(0)
    while collected and not collected[-1].strip():
        collected.pop()
    return collected


def render_concept_pages(records: list[NoteRecord], out_root: Path, concepts: dict[str, dict]) -> None:
    from .util import atomic_write

    concept_dir = out_root / "_concepts"
    for slug, payload in concepts.items():
        path = concept_dir / f"{slug}.md"
        linked = _linked_passages(path)
        lines = [f"# {payload['name']}", ""]
        if payload["definition"]:
            lines.append(payload["definition"])
            lines.append("")
        merged = payload.get("definitions", 0)
        if merged > 1:
            lines.append(f"_Merged from {merged} definitions; the most detailed one is shown._")
            lines.append("")
        lines.append("## Covered in")
        for record in payload["lessons"]:
            lesson_path = out_root / record.lesson_rel
            link = rel_link(lesson_path, path.parent)
            lines.append(f"- [{record.title}]({link})")
        lines.append("")
        if linked:
            lines.append(LINKED_HEADING)
            lines.extend(linked)
            lines.append("")
        atomic_write(path, "\n".join(lines))

    for stale in concept_dir.glob("*.md"):
        if stale.stem not in concepts:
            stale.unlink(missing_ok=True)

    from .vault import glossary_groups

    glossary = ["# Glossary", ""]
    for group in glossary_groups(concepts):
        definition = f" — {group['definition']}" if group["definition"] else ""
        alias = ""
        if group["aliases"]:
            alias = f" (also: {', '.join(group['aliases'])})"
        glossary.append(
            f"- **{group['name']}**{alias}{definition} · [page](_concepts/{group['slug']}.md)"
        )
    glossary.append("")
    atomic_write(out_root / "_glossary.md", "\n".join(glossary))


def render_failed(failures: list[tuple[str, str]], out_root: Path) -> None:
    from .util import atomic_write

    if not failures:
        return
    lines = ["# Failed items", "", "Re-run with `shellslatee run … --force` to retry.", ""]
    for rel, reason in failures:
        lines.append(f"- `{rel}` — {reason}")
    lines.append("")
    atomic_write(out_root / "_failed.md", "\n".join(lines))
