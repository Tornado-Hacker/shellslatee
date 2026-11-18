from __future__ import annotations

import re
from pathlib import Path

from .render import NoteRecord
from .util import slugify

FRONTMATTER_RE = re.compile(r"\A---\n(?P<body>.*?)\n---\n", re.DOTALL)
CONCEPT_DEF_RE = re.compile(r"^- \*\*(?P<name>[^*]+)\*\*(?: — (?P<definition>.+))?$")
TLDR_RE = re.compile(r"^> \*\*TL;DR\*\* — (?P<summary>.+)$")
LEADING_ARTICLES = ("the ", "a ", "an ")
PLURAL_KEEP = ("ss", "us", "is")


def normalized_name(name: str) -> str:
    """Case, punctuation, article, and simple plural folding for dedupe."""
    text = name.strip().lower()
    for article in LEADING_ARTICLES:
        if text.startswith(article):
            text = text[len(article) :]
            break
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    words = text.split()
    if not words:
        return ""
    last = words[-1]
    if len(last) > 3 and last.endswith("ies"):
        words[-1] = last[:-3] + "y"
    elif len(last) > 3 and last.endswith("s") and not last.endswith(PLURAL_KEEP):
        words[-1] = last[:-1]
    return " ".join(words)


def _parse_scalar(raw: str) -> str:
    value = raw.strip()
    if value.startswith('"') and value.endswith('"') and len(value) >= 2:
        value = value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return value


def _parse_list(raw: str) -> list[str]:
    value = raw.strip()
    if not (value.startswith("[") and value.endswith("]")):
        return []
    inner = value[1:-1].strip()
    if not inner:
        return []
    items: list[str] = []
    current = ""
    in_quotes = False
    for char in inner:
        if char == '"':
            in_quotes = not in_quotes
            current += char
        elif char == "," and not in_quotes:
            items.append(_parse_scalar(current))
            current = ""
        else:
            current += char
    if current.strip():
        items.append(_parse_scalar(current))
    return [item for item in items if item]


def parse_note(path: Path, out_root: Path) -> tuple[NoteRecord | None, list[dict[str, str]]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    match = FRONTMATTER_RE.match(text)
    if not match:
        return None, []

    fields: dict[str, str] = {}
    for line in match.group("body").splitlines():
        if ":" not in line:
            continue
        key, _, raw = line.partition(":")
        fields[key.strip()] = raw.strip()

    body = text[match.end() :]
    summary = ""
    for line in body.splitlines():
        tldr = TLDR_RE.match(line.strip())
        if tldr:
            summary = tldr.group("summary").strip()
            break

    concepts: list[dict[str, str]] = []
    in_concepts = False
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            in_concepts = stripped == "## Key concepts"
            continue
        if in_concepts:
            concept = CONCEPT_DEF_RE.match(stripped)
            if concept:
                concepts.append(
                    {
                        "name": concept.group("name").strip(),
                        "definition": (concept.group("definition") or "").strip(),
                    }
                )

    try:
        duration = float(fields.get("duration", "0") or 0)
    except ValueError:
        duration = 0.0

    record = NoteRecord(
        module=_parse_scalar(fields.get("module", "")),
        lesson_rel=path.relative_to(out_root).as_posix(),
        title=_parse_scalar(fields.get("title", "")) or path.stem,
        summary=summary,
        duration=duration,
        concepts=_parse_list(fields.get("concepts", "[]")),
        tags=_parse_list(fields.get("tags", "[]")),
    )
    return record, concepts


def merge_definition(current: str, candidate: str) -> str:
    """Pick a stable definition when several lessons define the same concept.

    Longest non-empty wins because it usually carries the most context; ties go
    to the lexicographically smaller string so re-indexing is deterministic
    regardless of the order files were read. Never lets a shorter definition
    replace a longer one.
    """
    left = (current or "").strip()
    right = (candidate or "").strip()
    if not right:
        return left
    if not left:
        return right
    if len(right) > len(left):
        return right
    if len(right) == len(left) and right < left:
        return right
    return left


def collect(out_root: Path) -> tuple[list[NoteRecord], dict[str, dict]]:
    records: list[NoteRecord] = []
    concepts: dict[str, dict] = {}
    seen_definitions: dict[str, set[str]] = {}
    if not out_root.is_dir():
        return records, concepts

    for path in sorted(out_root.rglob("*.md")):
        if any(part.startswith((".", "_")) for part in path.relative_to(out_root).parts):
            continue
        record, note_concepts = parse_note(path, out_root)
        if record is None:
            continue
        records.append(record)
        for concept in note_concepts:
            slug = "con_" + slugify(concept["name"])
            entry = concepts.setdefault(
                slug,
                {"name": concept["name"], "definition": "", "lessons": [], "definitions": 0},
            )
            definition = concept["definition"].strip()
            if definition:
                entry["definition"] = merge_definition(entry["definition"], definition)
                seen = seen_definitions.setdefault(slug, set())
                seen.add(definition)
                entry["definitions"] = len(seen)
            if all(item.lesson_rel != record.lesson_rel for item in entry["lessons"]):
                entry["lessons"].append(record)

    records.sort(key=lambda item: item.lesson_rel)
    for entry in concepts.values():
        entry["lessons"].sort(key=lambda item: item.lesson_rel)
    return records, concepts


def glossary_groups(concepts: dict[str, dict]) -> list[dict]:
    """Fold near-duplicate concept names into one glossary entry each.

    The canonical name and definition follow the same rule as concept merging:
    the longest definition wins, ties break lexicographically, so a rebuild is
    deterministic. Concept pages stay per-slug; only the glossary is folded.
    """
    groups: dict[str, dict] = {}
    for slug, payload in concepts.items():
        key = normalized_name(payload["name"]) or slug
        group = groups.setdefault(
            key,
            {
                "key": key,
                "name": payload["name"],
                "definition": "",
                "slug": slug,
                "aliases": [],
                "lessons": [],
            },
        )
        definition = (payload.get("definition") or "").strip()
        if definition:
            if (
                len(definition) > len(group["definition"])
                or (
                    len(definition) == len(group["definition"])
                    and payload["name"] < group["name"]
                )
            ):
                group["name"] = payload["name"]
                group["definition"] = definition
                group["slug"] = slug
        if payload["name"] != group["name"] and payload["name"] not in group["aliases"]:
            group["aliases"].append(payload["name"])
        for record in payload.get("lessons", []):
            if all(existing.lesson_rel != record.lesson_rel for existing in group["lessons"]):
                group["lessons"].append(record)

    for group in groups.values():
        group["aliases"] = sorted(set(group["aliases"]))
        group["lessons"].sort(key=lambda item: item.lesson_rel)
    return sorted(groups.values(), key=lambda item: item["name"].lower())
