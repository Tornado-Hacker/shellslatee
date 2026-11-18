"""Deterministic quizzes built from the vault's own notes.

Quiz items come from the same structure the card engine reads — concept
definitions and timestamped walkthrough sections — so a quiz needs no provider
and no network. Multiple-choice items use other concepts in the vault as
distractors; everything else is a short-answer recall item. Storage is a
rebuildable SQLite file at ``OUT/.shellslatee/quizzes.db``.

Weak-concept focus: pass concept names (from ``cards.drills``) to build a quiz
that only drills those ideas.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from pathlib import Path

from .cards import _iter_notes, cards_from_note, concept_name
from .util import slugify

DB_NAME = "quizzes.db"
CHOICE_COUNT = 4

SCHEMA = """
CREATE TABLE IF NOT EXISTS quiz(
    id TEXT PRIMARY KEY,
    lesson TEXT NOT NULL,
    concept TEXT,
    kind TEXT NOT NULL,
    question TEXT NOT NULL,
    options TEXT NOT NULL DEFAULT '[]',
    answer TEXT NOT NULL DEFAULT '',
    answer_index INTEGER NOT NULL DEFAULT -1,
    explanation TEXT NOT NULL DEFAULT '',
    created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS attempt(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quiz_id TEXT NOT NULL,
    response TEXT NOT NULL,
    correct INTEGER NOT NULL,
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS quiz_kind ON quiz(kind);
"""


def _db(out_root: Path) -> sqlite3.Connection:
    shellslatee_dir = out_root / ".shellslatee"
    shellslatee_dir.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(shellslatee_dir / DB_NAME)
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    return connection


def _quiz_id(lesson: str, question: str) -> str:
    return "quiz_" + hashlib.sha1(f"{lesson}\n{question}".encode("utf-8")).hexdigest()[:16]


def _normalize(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def _ordered(values: list[str], seed: str) -> list[str]:
    """Stable, seed-dependent order without depending on ``random`` internals."""
    return sorted(values, key=lambda value: hashlib.sha1(f"{seed}\n{value}".encode("utf-8")).hexdigest())


def _distractors(name: str, definition: str, pool: dict[str, str], seed: str) -> list[str]:
    candidates = [
        value
        for other, value in pool.items()
        if other != name and value and _normalize(value) != _normalize(definition)
    ]
    unique: list[str] = []
    seen: set[str] = set()
    for value in _ordered(candidates, seed):
        key = _normalize(value)
        if key in seen:
            continue
        seen.add(key)
        unique.append(value)
        if len(unique) >= CHOICE_COUNT - 1:
            break
    return unique


def _concept_items(lesson: str, name: str, definition: str, pool: dict[str, str]) -> dict | None:
    definition = definition.strip()
    if not definition:
        return None
    seed = f"{lesson}\n{name}"
    question = f"Which best defines {name}?"
    wrong = _distractors(name, definition, pool, seed)
    if not wrong:
        return {
            "lesson": lesson,
            "concept": name,
            "kind": "short",
            "question": f"Define: {name}",
            "options": [],
            "answer": definition,
            "answer_index": -1,
            "explanation": definition,
        }
    options = _ordered([definition, *wrong], seed)
    return {
        "lesson": lesson,
        "concept": name,
        "kind": "mcq",
        "question": question,
        "options": options,
        "answer": definition,
        "answer_index": options.index(definition),
        "explanation": definition,
    }


def _collect_pool(out_root: Path) -> dict[str, str]:
    pool: dict[str, str] = {}
    for lesson_rel, path in _iter_notes(out_root):
        text = path.read_text(encoding="utf-8", errors="replace")
        for card in cards_from_note(lesson_rel, text):
            name = concept_name(card)
            if name and card.get("back", "").strip():
                pool.setdefault(name, card["back"].strip())
    return pool


def build(out_root: Path, focus: list[str] | None = None, limit: int = 0) -> dict[str, int]:
    """Rebuild quiz items from every note, optionally focused on weak concepts."""
    pool = _collect_pool(out_root)
    focus_keys = {_normalize(name) for name in (focus or []) if name.strip()}

    items: list[dict] = []
    for lesson_rel, path in _iter_notes(out_root):
        text = path.read_text(encoding="utf-8", errors="replace")
        for card in cards_from_note(lesson_rel, text):
            name = concept_name(card)
            if name:
                if focus_keys and _normalize(name) not in focus_keys:
                    continue
                item = _concept_items(lesson_rel, name, card.get("back", ""), pool)
                if item:
                    items.append(item)
                continue
            if focus_keys:
                continue
            if card.get("kind") == "recall" and card.get("back", "").strip():
                items.append(
                    {
                        "lesson": lesson_rel,
                        "concept": None,
                        "kind": "short",
                        "question": card["front"],
                        "options": [],
                        "answer": card["back"].strip(),
                        "answer_index": -1,
                        "explanation": card["back"].strip(),
                    }
                )

    items.sort(key=lambda item: (item["lesson"], item["kind"], item["question"]))
    if limit > 0:
        items = items[:limit]

    now = time.time()
    connection = _db(out_root)
    try:
        existing = {
            row["id"]
            for row in connection.execute("SELECT id FROM quiz").fetchall()
        }
        created = 0
        updated = 0
        keep: set[str] = set()
        for item in items:
            quiz_id = _quiz_id(item["lesson"], item["question"])
            keep.add(quiz_id)
            values = (
                item["lesson"],
                item["concept"],
                item["kind"],
                item["question"],
                json.dumps(item["options"], ensure_ascii=False),
                item["answer"],
                int(item["answer_index"]),
                item["explanation"],
                now,
            )
            if quiz_id in existing:
                connection.execute(
                    "UPDATE quiz SET lesson=?, concept=?, kind=?, question=?, options=?,"
                    " answer=?, answer_index=?, explanation=?, created=? WHERE id=?",
                    (*values, quiz_id),
                )
                updated += 1
            else:
                connection.execute(
                    "INSERT INTO quiz(id, lesson, concept, kind, question, options, answer,"
                    " answer_index, explanation, created) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (quiz_id, *values),
                )
                created += 1
        stale = existing - keep
        for quiz_id in stale:
            connection.execute("DELETE FROM quiz WHERE id = ?", (quiz_id,))
        connection.commit()
        total = connection.execute("SELECT COUNT(*) FROM quiz").fetchone()[0]
    finally:
        connection.close()
    return {"created": created, "updated": updated, "total": int(total), "pruned": len(stale)}


def _row_to_item(row: sqlite3.Row) -> dict:
    try:
        options = json.loads(row["options"] or "[]")
    except ValueError:
        options = []
    return {
        "id": row["id"],
        "lesson": row["lesson"],
        "concept": row["concept"],
        "kind": row["kind"],
        "question": row["question"],
        "options": options if isinstance(options, list) else [],
        "answer": row["answer"],
        "answer_index": row["answer_index"],
        "explanation": row["explanation"],
    }


def items(out_root: Path, limit: int = 20, kind: str | None = None) -> list[dict]:
    connection = _db(out_root)
    try:
        if kind in {"mcq", "short"}:
            rows = connection.execute(
                "SELECT * FROM quiz WHERE kind = ? ORDER BY lesson, question LIMIT ?",
                (kind, max(1, limit)),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT * FROM quiz ORDER BY lesson, question LIMIT ?", (max(1, limit),)
            ).fetchall()
        return [_row_to_item(row) for row in rows]
    finally:
        connection.close()


def stats(out_root: Path) -> dict[str, int]:
    connection = _db(out_root)
    try:
        total = connection.execute("SELECT COUNT(*) FROM quiz").fetchone()[0]
        mcq = connection.execute("SELECT COUNT(*) FROM quiz WHERE kind = 'mcq'").fetchone()[0]
        attempts = connection.execute("SELECT COUNT(*) FROM attempt").fetchone()[0]
        right = connection.execute("SELECT COUNT(*) FROM attempt WHERE correct = 1").fetchone()[0]
        return {
            "total": int(total),
            "mcq": int(mcq),
            "short": int(total) - int(mcq),
            "attempts": int(attempts),
            "correct": int(right),
        }
    finally:
        connection.close()


def _short_correct(expected: str, response: str) -> bool:
    want = _normalize(expected)
    got = _normalize(response)
    if not want or not got:
        return False
    if got in want or want in got:
        return True
    want_tokens = set(want.split())
    got_tokens = set(got.split())
    if not want_tokens:
        return False
    overlap = len(want_tokens & got_tokens) / len(want_tokens)
    return overlap >= 0.6


def check(out_root: Path, quiz_id: str, response: str | int) -> dict | None:
    """Grade one response, record the attempt, and reveal the expected answer."""
    connection = _db(out_root)
    try:
        row = connection.execute("SELECT * FROM quiz WHERE id = ?", (quiz_id,)).fetchone()
        if row is None:
            return None
        item = _row_to_item(row)
        if item["kind"] == "mcq":
            correct = False
            try:
                index = int(response)
            except (TypeError, ValueError):
                index = -1
            correct = index == item["answer_index"]
        else:
            correct = _short_correct(item["answer"], str(response))
        connection.execute(
            "INSERT INTO attempt(quiz_id, response, correct, ts) VALUES (?, ?, ?, ?)",
            (quiz_id, str(response), 1 if correct else 0, time.time()),
        )
        connection.commit()
        return {
            "id": quiz_id,
            "correct": correct,
            "kind": item["kind"],
            "answer": item["answer"],
            "answer_index": item["answer_index"],
            "explanation": item["explanation"],
            "lesson": item["lesson"],
            "concept": item["concept"],
        }
    finally:
        connection.close()
