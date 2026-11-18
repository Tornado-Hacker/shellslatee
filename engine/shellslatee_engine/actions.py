"""Selection actions: explain / simplify / quiz / make cards / find related.

Operates on an arbitrary span of text the reader selected, grounded with the
note it came from. ``related`` skips the model entirely and returns vault
citations; the rest ask the configured provider and degrade to deterministic
mock output when the mock provider is in use.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import rag
from .providers import Provider, chat
from .util import atomic_write
from .vault import FRONTMATTER_RE, collect

ACTIONS = {"explain", "simplify", "quiz", "cards", "related", "link"}
MAX_SELECTION = 4000
MAX_NOTE_CONTEXT = 8000
LINK_HEADING = "## Linked passages"
MAX_LINK_SNIPPET = 200

SYSTEM = (
    "You are a study assistant inside Shellslatee. The user selects a span of an "
    "on-screen note and asks for one action. Be concise, concrete, and stay "
    "faithful to the selected text and its note. Never invent facts that the "
    "source does not support."
)

PROMPTS = {
    "explain": "Explain the selected passage in your own words. Name the key terms and why they matter.",
    "simplify": "Rewrite the selected passage in plain language a beginner can follow. Keep it short.",
    "quiz": "Write one exam-style question that tests the selected passage, then its answer.",
    "cards": "Turn the selected passage into 1-3 spaced-repetition flashcards.",
    "related": "List the concepts in the selected passage.",
}

CARDS_SCHEMA = (
    'Return strict JSON: {"cards": [{"front": "...", "back": "..."}]}. '
    "Front is a question, back is the answer. No prose outside the JSON."
)


class ActionError(ValueError):
    pass


def _note_file(out_root: Path, rel: str) -> Path:
    target = (out_root / rel).resolve()
    try:
        target.relative_to(out_root)
    except ValueError as exc:
        raise ActionError("path escapes the vault") from exc
    if not target.is_file() or target.suffix != ".md":
        raise ActionError(f"note not found: {rel}")
    return target


def _note_body(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    match = FRONTMATTER_RE.match(text)
    body = text[match.end() :] if match else text
    return body[:MAX_NOTE_CONTEXT]


def _parse_cards(raw: str) -> list[dict[str, str]]:
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    payload: Any = None
    if match:
        try:
            payload = json.loads(match.group(0))
        except ValueError:
            payload = None
    cards = payload.get("cards") if isinstance(payload, dict) else None
    if isinstance(cards, list):
        cleaned = [
            {"front": str(card.get("front", "")).strip(), "back": str(card.get("back", "")).strip()}
            for card in cards
            if isinstance(card, dict)
        ]
        cleaned = [card for card in cleaned if card["front"] and card["back"]]
        if cleaned:
            return cleaned[:5]
    return []


def _terms(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]{4,}", text.lower())}


def _pick_concept(out_root: Path, selection: str, wanted: str | None) -> tuple[str, dict]:
    """Resolve the concept a selection belongs to: named, else best token match."""
    _records, concepts = collect(out_root)
    if not concepts:
        raise ActionError("this vault has no concept pages yet — run `shellslatee index`")
    if wanted:
        target = wanted.strip().lower()
        for slug, payload in concepts.items():
            names = {payload["name"].lower(), slug.lower(), slug.removeprefix("con_").lower()}
            if target in names:
                return slug, payload
        raise ActionError(f"unknown concept: {wanted}")
    selection_terms = _terms(selection)
    lowered = selection.lower()
    best: tuple[str, dict] | None = None
    best_score = 0
    for slug, payload in concepts.items():
        haystack = f"{payload['name']} {payload.get('definition', '')}"
        score = len(selection_terms & _terms(haystack))
        if payload["name"].lower() and payload["name"].lower() in lowered:
            score += 5
        if score > best_score:
            best, best_score = (slug, payload), score
    if best is None or best_score <= 0:
        raise ActionError("no matching concept — select text that names one, or pass a concept")
    return best


def link_selection(out_root: Path, rel: str, selection: str, concept: str | None = None) -> dict:
    """Append a passage to an existing concept page, durably and idempotently."""
    slug, payload = _pick_concept(out_root, selection, concept)
    path = out_root / "_concepts" / f"{slug}.md"
    if not path.is_file():
        # A long run keeps concept pages stale until its final index pass; render
        # the one page on demand so linking works mid-run.
        from .render import render_concept_pages

        render_concept_pages([], out_root, {slug: payload})
    if not path.is_file():
        raise ActionError(f"concept page missing for {payload['name']} — run `shellslatee index`")
    snippet = " ".join(selection.split())[:MAX_LINK_SNIPPET]
    if len(snippet) < len(" ".join(selection.split())):
        snippet = snippet.rstrip() + "…"
    bullet = f'- "{snippet}" — `{rel}`'
    text = path.read_text(encoding="utf-8", errors="replace")
    added = bullet not in text
    if added:
        lines = text.splitlines()
        try:
            heading = next(i for i, line in enumerate(lines) if line.strip() == LINK_HEADING)
        except StopIteration:
            lines.extend(["", LINK_HEADING, "", bullet])
        else:
            insert_at = heading + 1
            while insert_at < len(lines) and not lines[insert_at].strip():
                insert_at += 1
            lines.insert(insert_at, bullet)
        atomic_write(path, "\n".join(lines).rstrip("\n") + "\n")
    return {
        "action": "link",
        "text": "",
        "concept": payload["name"],
        "slug": slug,
        "rel": path.relative_to(out_root).as_posix(),
        "added": added,
        "tokens": {"in": 0, "out": 0},
    }


def run(
    provider: Provider | None,
    model: str,
    api_key: str,
    *,
    out_root: Path,
    rel: str,
    selection: str,
    action: str,
    concept: str | None = None,
) -> dict:
    if action not in ACTIONS:
        raise ActionError(f"unknown action: {action}")
    selection = selection.strip()
    if not selection:
        raise ActionError("selection is empty")
    if len(selection) > MAX_SELECTION:
        raise ActionError("selection too large")
    note_path = _note_file(out_root, rel)

    if action == "link":
        return link_selection(out_root, rel, selection, concept)

    if action == "related":
        citations = rag.retrieve(out_root, selection, limit=6)
        return {"action": action, "text": "", "citations": [c.__dict__ for c in citations]}

    if provider is None or provider.name == "mock":
        return {"action": action, **_mock_result(action, selection)}

    user = (
        f"{PROMPTS[action]}\n\n"
        f"Selected passage:\n{selection}\n\n"
        f"Note context:\n{_note_body(note_path)}"
    )
    if action == "cards":
        user += f"\n\n{CARDS_SCHEMA}"
    raw, tokens = chat(
        provider,
        model,
        api_key,
        [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
        json_mode=action == "cards",
        temperature=0.3,
    )
    result: dict[str, Any] = {
        "action": action,
        "text": raw.strip(),
        "tokens": {"in": int((tokens or {}).get("in", 0)), "out": int((tokens or {}).get("out", 0))},
    }
    if action == "cards":
        cards = _parse_cards(raw)
        result["text"] = ""
        result["cards"] = cards
        if not cards:
            result["text"] = raw.strip()
    return result


def _mock_result(action: str, selection: str) -> dict:
    snippet = " ".join(selection.split())[:200]
    if action == "explain":
        return {
            "text": f"Mock explanation: “{snippet}” describes the passage the reader selected. "
            "Wire a real provider for a grounded explanation.",
            "tokens": {"in": 0, "out": 0},
        }
    if action == "simplify":
        return {
            "text": f"In plain terms: {snippet}",
            "tokens": {"in": 0, "out": 0},
        }
    if action == "quiz":
        return {
            "text": f"Question: What does the passage say about “{snippet[:80]}”?\n\n"
            f"Answer: {snippet}",
            "tokens": {"in": 0, "out": 0},
        }
    if action == "cards":
        return {
            "text": "",
            "cards": [
                {
                    "front": f"What does “{snippet[:60]}…” mean?",
                    "back": snippet,
                }
            ],
            "tokens": {"in": 0, "out": 0},
        }
    return {"text": "", "tokens": {"in": 0, "out": 0}}
