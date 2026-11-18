"""Flashcards and spaced-repetition review for a Shellslatee vault.

Cards are generated deterministically from each note's structure — key concepts,
timestamped walkthrough topics, and review questions — so they work with no
provider and no network. Review state uses the FSRS-style scheduler in
``fsrs.py``. Storage is a rebuildable SQLite file at ``OUT/.shellslatee/cards.db``;
the Markdown vault stays canonical.
"""

from __future__ import annotations

import csv
import hashlib
import re
import sqlite3
import time
from pathlib import Path

from .fsrs import SchedulerState, schedule

DB_NAME = "cards.db"
CONCEPT_RE = re.compile(r"^- \*\*(?P<name>[^*]+)\*\*(?: — (?P<definition>.+))?$")
TOPIC_RE = re.compile(r"^###\s+(?P<stamp>\d{1,2}:\d{2}(?::\d{2})?)\s+—\s+(?P<title>.+)$")
QUESTION_RE = re.compile(r"^\d+\.\s+(?P<text>.+)$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS card(
    id TEXT PRIMARY KEY,
    lesson TEXT NOT NULL,
    kind TEXT NOT NULL,
    front TEXT NOT NULL,
    back TEXT NOT NULL,
    stability REAL NOT NULL DEFAULT 0,
    difficulty REAL NOT NULL DEFAULT 0,
    reps INTEGER NOT NULL DEFAULT 0,
    lapses INTEGER NOT NULL DEFAULT 0,
    due_ts REAL NOT NULL DEFAULT 0,
    last_review REAL NOT NULL DEFAULT 0,
    created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS review(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id TEXT NOT NULL,
    grade INTEGER NOT NULL,
    ts REAL NOT NULL,
    interval_s REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS card_due ON card(due_ts);
"""


def _card_id(lesson: str, front: str) -> str:
    return "card_" + hashlib.sha1(f"{lesson}\n{front}".encode("utf-8")).hexdigest()[:16]


def _db(out_root: Path) -> sqlite3.Connection:
    shellslatee_dir = out_root / ".shellslatee"
    shellslatee_dir.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(shellslatee_dir / DB_NAME)
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    return connection


def _strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4 :]
    return text


def cards_from_note(lesson_rel: str, text: str) -> list[dict[str, str]]:
    """Extract deterministic cards from one note's Markdown body."""
    body = _strip_frontmatter(text)
    cards: list[dict[str, str]] = []
    section = ""
    topic_title = ""
    topic_stamp = ""
    topic_details: list[str] = []
    question_mode = False

    def flush_topic() -> None:
        nonlocal topic_title, topic_stamp, topic_details
        if topic_title and topic_details:
            cards.append(
                {
                    "kind": "recall",
                    "front": f"What did the lesson cover at {topic_stamp}: {topic_title}?",
                    "back": "\n".join(f"- {item}" for item in topic_details),
                }
            )
        topic_title, topic_stamp, topic_details = "", "", []

    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            flush_topic()
            section = stripped[3:].strip().lower()
            question_mode = section.startswith("review questions")
            continue
        topic = TOPIC_RE.match(stripped)
        if topic:
            flush_topic()
            topic_stamp = topic.group("stamp")
            topic_title = topic.group("title").strip()
            continue
        if stripped.startswith("### "):
            flush_topic()
            continue
        if section.startswith("key concepts"):
            concept = CONCEPT_RE.match(stripped)
            if concept and concept.group("definition"):
                cards.append(
                    {
                        "kind": "concept",
                        "front": f"What is {concept.group('name').strip()}?",
                        "back": concept.group("definition").strip(),
                    }
                )
            continue
        if section.startswith("walkthrough"):
            if stripped.startswith("- ") and topic_title:
                topic_details.append(stripped[2:].strip())
            continue
        if question_mode:
            question = QUESTION_RE.match(stripped)
            if question:
                cards.append(
                    {
                        "kind": "question",
                        "front": question.group("text").strip(),
                        "back": "",
                    }
                )
    flush_topic()
    return cards


def _iter_notes(out_root: Path):
    for path in sorted(out_root.rglob("*.md")):
        relative = path.relative_to(out_root)
        if any(part.startswith((".", "_")) for part in relative.parts):
            continue
        yield relative.as_posix(), path


def build(out_root: Path) -> dict[str, int]:
    """Generate/refresh cards from every note, preserving existing review state."""
    created = 0
    updated = 0
    now = time.time()
    connection = _db(out_root)
    try:
        for lesson_rel, path in _iter_notes(out_root):
            text = path.read_text(encoding="utf-8", errors="replace")
            for item in cards_from_note(lesson_rel, text):
                card_id = _card_id(lesson_rel, item["front"])
                existing = connection.execute(
                    "SELECT id FROM card WHERE id = ?", (card_id,)
                ).fetchone()
                if existing:
                    connection.execute(
                        "UPDATE card SET back = ?, kind = ? WHERE id = ?",
                        (item["back"], item["kind"], card_id),
                    )
                    updated += 1
                else:
                    connection.execute(
                        "INSERT INTO card(id, lesson, kind, front, back, due_ts, created)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (card_id, lesson_rel, item["kind"], item["front"], item["back"], now, now),
                    )
                    created += 1
        connection.commit()
        total = connection.execute("SELECT COUNT(*) FROM card").fetchone()[0]
    finally:
        connection.close()
    return {"created": created, "updated": updated, "total": int(total)}


def _row_to_card(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "lesson": row["lesson"],
        "kind": row["kind"],
        "front": row["front"],
        "back": row["back"],
        "reps": row["reps"],
        "lapses": row["lapses"],
        "due_ts": row["due_ts"],
        "last_review": row["last_review"],
        "stability": row["stability"],
        "difficulty": row["difficulty"],
    }


def queue(out_root: Path, limit: int = 20, now: float | None = None) -> list[dict]:
    now = time.time() if now is None else now
    connection = _db(out_root)
    try:
        rows = connection.execute(
            "SELECT * FROM card WHERE due_ts <= ? ORDER BY due_ts ASC LIMIT ?",
            (now, max(1, limit)),
        ).fetchall()
        return [_row_to_card(row) for row in rows]
    finally:
        connection.close()


def stats(out_root: Path, now: float | None = None) -> dict[str, int]:
    now = time.time() if now is None else now
    connection = _db(out_root)
    try:
        total = connection.execute("SELECT COUNT(*) FROM card").fetchone()[0]
        fresh = connection.execute("SELECT COUNT(*) FROM card WHERE reps = 0").fetchone()[0]
        due = connection.execute(
            "SELECT COUNT(*) FROM card WHERE due_ts <= ?", (now,)
        ).fetchone()[0]
        return {"total": int(total), "new": int(fresh), "due": int(due)}
    finally:
        connection.close()


def review(out_root: Path, card_id: str, grade: int, now: float | None = None) -> dict | None:
    now = time.time() if now is None else now
    connection = _db(out_root)
    try:
        row = connection.execute("SELECT * FROM card WHERE id = ?", (card_id,)).fetchone()
        if row is None:
            return None
        state = SchedulerState(
            stability=row["stability"],
            difficulty=row["difficulty"],
            reps=row["reps"],
            lapses=row["lapses"],
            last_review=row["last_review"],
            due_ts=row["due_ts"],
        )
        next_state, interval_seconds = schedule(state, grade, now)
        connection.execute(
            "UPDATE card SET stability = ?, difficulty = ?, reps = ?, lapses = ?,"
            " due_ts = ?, last_review = ? WHERE id = ?",
            (
                next_state.stability,
                next_state.difficulty,
                next_state.reps,
                next_state.lapses,
                next_state.due_ts,
                next_state.last_review,
                card_id,
            ),
        )
        connection.execute(
            "INSERT INTO review(card_id, grade, ts, interval_s) VALUES (?, ?, ?, ?)",
            (card_id, grade, now, interval_seconds),
        )
        connection.commit()
        updated = connection.execute("SELECT * FROM card WHERE id = ?", (card_id,)).fetchone()
        payload = _row_to_card(updated)
        payload["interval_s"] = interval_seconds
        return payload
    finally:
        connection.close()


def due_cards(out_root: Path, limit: int = 20) -> dict:
    return {"stats": stats(out_root), "cards": queue(out_root, limit)}


CONCEPT_FRONT_RE = re.compile(r"^What is (?P<name>.+)\?$")


def concept_name(card: dict) -> str | None:
    """The concept a card drills, when the card is a concept card."""
    if card.get("kind") != "concept":
        return None
    match = CONCEPT_FRONT_RE.match(card.get("front", ""))
    return match.group("name").strip() if match else None


def _weakness(card: dict, now: float) -> float:
    """Higher means the learner is doing worse on it.

    Lapses dominate; a short stability and an overdue card add pressure; a card
    that has never been reviewed is nudged just above a proven one so a drill
    session shows new material before mastered material.
    """
    lapses = float(card.get("lapses", 0) or 0)
    stability = max(0.0, float(card.get("stability", 0) or 0))
    reps = int(card.get("reps", 0) or 0)
    score = lapses * 3.0 + (1.0 / (1.0 + stability))
    if reps == 0:
        score += 0.5
    if float(card.get("due_ts", 0) or 0) <= now:
        score += 1.5
    return score


def drills(out_root: Path, limit: int = 20, now: float | None = None) -> dict:
    """Weak-concept drill queue: cards with a review history or due now, ranked.

    Concept cards are grouped under their concept name; other cards fall back to
    their lesson so a drill session always has a heading to work from.
    """
    now = time.time() if now is None else now
    connection = _db(out_root)
    try:
        rows = connection.execute("SELECT * FROM card").fetchall()
    finally:
        connection.close()

    scored: list[dict] = []
    for row in rows:
        card = _row_to_card(row)
        if card["reps"] == 0 and card["lapses"] == 0:
            continue  # unstuck cards belong to the normal queue
        card["weakness"] = round(_weakness(card, now), 3)
        card["concept"] = concept_name(card)
        scored.append(card)

    scored.sort(key=lambda item: (-item["weakness"], item["lesson"], item["front"]))
    selected = scored[: max(1, limit)]

    groups: dict[str, dict] = {}
    for card in selected:
        label = card["concept"] or card["lesson"]
        group = groups.setdefault(
            label, {"concept": card["concept"], "lesson": card["lesson"], "weakness": 0.0, "cards": []}
        )
        group["weakness"] = max(group["weakness"], card["weakness"])
        group["cards"].append(card)

    ordered = sorted(groups.values(), key=lambda item: (-item["weakness"], item["lesson"]))
    return {"stats": stats(out_root, now), "groups": ordered, "cards": selected}


def export_csv(out_root: Path, target: Path) -> int:
    """Write an Anki-importable CSV (front, back, lesson)."""
    connection = _db(out_root)
    try:
        rows = connection.execute(
            "SELECT front, back, lesson FROM card ORDER BY lesson, front"
        ).fetchall()
    finally:
        connection.close()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["front", "back", "lesson"])
        for row in rows:
            writer.writerow([row["front"], row["back"], row["lesson"]])
    return len(rows)
