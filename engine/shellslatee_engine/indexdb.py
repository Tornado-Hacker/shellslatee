from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from .util import atomic_write, utc_now

DB_NAME = "vault.db"
SCHEMA = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE entity(id TEXT PRIMARY KEY, kind TEXT, path TEXT, title TEXT);
CREATE TABLE edge(src TEXT, dst TEXT, rel TEXT, PRIMARY KEY(src, dst, rel));
CREATE TABLE segment(
    id INTEGER PRIMARY KEY,
    lesson TEXT,
    start_s REAL,
    heading TEXT,
    text TEXT
);
CREATE VIRTUAL TABLE note_fts USING fts5(lesson UNINDEXED, section, text);
"""

HEADING_RE = re.compile(r"^###\s+(?P<stamp>\d{1,2}:\d{2}(?::\d{2})?)\s+—\s+(?P<title>.+)$")


class IndexError_(RuntimeError):
    pass


def _stamp_seconds(value: str) -> float:
    parts = [int(part) for part in value.split(":")]
    if len(parts) == 3:
        return float(parts[0] * 3600 + parts[1] * 60 + parts[2])
    return float(parts[0] * 60 + parts[1])


def _frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    fields: dict[str, str] = {}
    for line in text[3:end].splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip().strip('"')
    return fields


def _split_sections(body: str) -> list[tuple[str, str, float | None]]:
    sections: list[tuple[str, str, float | None]] = []
    heading = ""
    start: float | None = None
    buffer: list[str] = []

    def flush() -> None:
        if heading or buffer:
            text = "\n".join(buffer).strip()
            if text:
                sections.append((heading or "preamble", text, start))

    for line in body.splitlines():
        if line.startswith("<!-- shellslatee:"):
            continue
        match = HEADING_RE.match(line.strip())
        if match:
            flush()
            heading = match.group("title").strip()
            start = _stamp_seconds(match.group("stamp"))
            buffer = []
            continue
        if line.startswith("## ") or line.startswith("# "):
            flush()
            heading = line.lstrip("# ").strip()
            start = None
            buffer = []
            continue
        stripped = line.strip()
        if stripped:
            buffer.append(stripped)
    flush()
    return sections


def build(out_root: Path) -> Path:
    shellslatee_dir = out_root / ".shellslatee"
    shellslatee_dir.mkdir(parents=True, exist_ok=True)
    target = shellslatee_dir / DB_NAME
    staging = shellslatee_dir / (DB_NAME + ".tmp")
    staging.unlink(missing_ok=True)

    connection = sqlite3.connect(staging)
    try:
        connection.executescript(SCHEMA)
        lessons = 0
        concepts = 0
        for path in sorted(out_root.rglob("*.md")):
            relative = path.relative_to(out_root)
            if any(part.startswith((".", "_")) for part in relative.parts):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            fields = _frontmatter(text)
            note_id = fields.get("id", "les_" + relative.stem)
            title = fields.get("title", relative.stem)
            connection.execute(
                "INSERT INTO entity(id, kind, path, title) VALUES (?, ?, ?, ?)",
                (note_id, "lesson", relative.as_posix(), title),
            )
            lessons += 1

            concept_ids = [
                item.strip().strip('"').strip("'")
                for item in fields.get("concepts", "").strip("[]").split(",")
                if item.strip().strip('"').strip("'")
            ]
            for concept_id in concept_ids:
                connection.execute(
                    "INSERT OR IGNORE INTO edge(src, dst, rel) VALUES (?, ?, ?)",
                    (note_id, concept_id, "covers"),
                )

            body = text[text.find("\n---", 3) + 4 :] if text.startswith("---") else text
            for section, section_text, start in _split_sections(body):
                connection.execute(
                    "INSERT INTO note_fts(lesson, section, text) VALUES (?, ?, ?)",
                    (note_id, section, section_text),
                )
                if start is not None:
                    connection.execute(
                        "INSERT INTO segment(lesson, start_s, heading, text) VALUES (?, ?, ?, ?)",
                        (note_id, start, section, section_text),
                    )
        connection.execute(
            "INSERT INTO meta(key, value) VALUES ('built_at', ?)", (utc_now(),)
        )
        connection.execute(
            "INSERT INTO meta(key, value) VALUES ('lessons', ?)", (str(lessons),)
        )
        connection.commit()
    finally:
        connection.close()

    staging.replace(target)
    return target


def open_db(out_root: Path) -> sqlite3.Connection:
    path = out_root / ".shellslatee" / DB_NAME
    if not path.is_file():
        raise IndexError_(f"no index at {path} — run: shellslatee index {out_root}")
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


STOPWORDS = frozenset(
    """
    a about after all also am an and any are as at be because been before being
    between both but by can could did do does doing done down during each few for
    from further had has have having he her here hers how i if in into is it its
    just me more most my no nor not now of off on once only or other our out over
    own same she should so some such than that the their them then there these they
    this those through to too under until up very was we were what when where which
    while who whom why will with would you your
    """.split()
)


def _tokens(text: str) -> list[str]:
    seen: list[str] = []
    for token in re.findall(r"[\w@.+/-]+", text.lower()):
        token = token.strip(".-/@+")
        if len(token) < 2 or token in STOPWORDS or token in seen:
            continue
        seen.append(token)
    return seen


def _fts_query(text: str, mode: str = "and") -> str:
    tokens = _tokens(text)
    if not tokens:
        raise IndexError_("empty query")
    if mode == "or":
        return " OR ".join(f'"{token}"' for token in tokens)
    return " ".join(f'"{token}"' for token in tokens)


def search(
    out_root: Path, query: str, limit: int = 10, dedupe: bool = True
) -> list[dict[str, object]]:
    """Search notes, precise first, then broad.

    A natural-language question almost never satisfies FTS5's implicit AND, so
    an empty AND pass falls back to OR over the content words, then (for a query
    with no usable tokens) to nothing. Results carry the section's timestamp in
    seconds when the heading had one, so citations can jump to the second.
    """
    connection = open_db(out_root)
    sql = (
        "SELECT e.path AS path, e.title AS title, "
        "       snippet(note_fts, 2, '[', ']', '…', 12) AS snippet, "
        "       note_fts.section AS section, "
        "       (SELECT MIN(seg.start_s) FROM segment seg "
        "         WHERE seg.lesson = note_fts.lesson "
        "           AND seg.heading = note_fts.section) AS start "
        "FROM note_fts JOIN entity e ON e.id = note_fts.lesson "
        "WHERE note_fts MATCH ? ORDER BY rank LIMIT ?"
    )
    try:
        rows: list[sqlite3.Row] = []
        for mode in ("and", "or"):
            try:
                rows = connection.execute(sql, (_fts_query(query, mode), limit)).fetchall()
            except sqlite3.OperationalError as exc:
                raise IndexError_(f"bad query: {exc}") from exc
            if rows:
                break
        results: list[dict[str, object]] = []
        seen: set[tuple[str, str]] = set()
        for row in rows:
            item: dict[str, object] = dict(row)
            if item.get("start") is not None:
                item["start"] = int(float(item["start"]))  # type: ignore[arg-type]
            key = (str(item.get("path", "")), str(item.get("section", "")))
            if dedupe and key in seen:
                continue
            seen.add(key)
            results.append(item)
        return results
    finally:
        connection.close()


def concept_pages(out_root: Path) -> list[dict[str, str]]:
    connection = open_db(out_root)
    try:
        rows = connection.execute(
            "SELECT src, dst FROM edge WHERE rel = 'covers' ORDER BY dst, src"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()
