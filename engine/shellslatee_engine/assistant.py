"""Grounded Q&A and note revision for the Shellslatee reader.

Both entry points take the note body the reader already holds, keep the model on a
short leash (answer only from the note / rewrite only the given body), and return
plain text. Token usage is handed straight back so the reader can show spend.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .providers import Provider, chat

MAX_CONTEXT_CHARS = 16000
MAX_HISTORY_TURNS = 8

ASK_SYSTEM = (
    "You are the study assistant built into Shellslatee, a local notes reader. "
    "Answer the learner's question using ONLY the note provided as context. "
    "Be direct and concrete; quote timestamps (mm:ss) when the note has them. "
    "If the note does not cover something, say so plainly and point at where in "
    "the note to look. Never invent facts, numbers, or examples."
)

EDIT_SYSTEM = (
    "You revise study notes for Shellslatee. You are given the current note body in "
    "Markdown and one instruction. Return ONLY the complete revised Markdown body — "
    "no preamble, no explanation, no code fences around the whole document. "
    "Preserve the existing structure (headings, timestamped walkthrough entries, "
    "review questions) unless the instruction explicitly changes it. Never invent "
    "facts that are not already present in the note."
)


@dataclass
class AssistantResult:
    text: str
    tokens_in: int = 0
    tokens_out: int = 0


def _clip(text: str, limit: int = MAX_CONTEXT_CHARS) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n\n[note truncated to fit the context window]"


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _tokens(tokens: dict[str, int] | None) -> tuple[int, int]:
    tokens = tokens or {}
    return int(tokens.get("in", 0)), int(tokens.get("out", 0))


def ask(
    provider: Provider,
    model: str,
    api_key: str,
    *,
    note_title: str,
    note_markdown: str,
    question: str,
    history: list[dict[str, str]] | None = None,
) -> AssistantResult:
    if provider.name == "mock":
        return AssistantResult(text=_mock_answer(note_title, question))

    context = f"Note title: {note_title}\n\nNote body (Markdown):\n{_clip(note_markdown)}"
    messages: list[dict[str, str]] = [
        {"role": "system", "content": ASK_SYSTEM},
        {"role": "user", "content": context},
    ]
    for turn in (history or [])[-MAX_HISTORY_TURNS:]:
        role = turn.get("role")
        content = str(turn.get("content", "")).strip()
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": question})

    raw, tokens = chat(provider, model, api_key, messages, json_mode=False, temperature=0.3)
    tokens_in, tokens_out = _tokens(tokens)
    return AssistantResult(text=raw.strip(), tokens_in=tokens_in, tokens_out=tokens_out)


def edit(
    provider: Provider,
    model: str,
    api_key: str,
    *,
    note_title: str,
    note_markdown: str,
    instruction: str,
) -> AssistantResult:
    if provider.name == "mock":
        return AssistantResult(text=_mock_edit(note_markdown, instruction))

    user = (
        f"Note title: {note_title}\n\n"
        "Current note body (Markdown):\n"
        f"{_clip(note_markdown)}\n\n"
        f"Instruction: {instruction}"
    )
    raw, tokens = chat(
        provider,
        model,
        api_key,
        [{"role": "system", "content": EDIT_SYSTEM}, {"role": "user", "content": user}],
        json_mode=False,
        temperature=0.2,
    )
    tokens_in, tokens_out = _tokens(tokens)
    return AssistantResult(text=_strip_fences(raw), tokens_in=tokens_in, tokens_out=tokens_out)


def _mock_answer(title: str, question: str) -> str:
    topic = question.strip().rstrip("?") or "that"
    return (
        f"Mock assistant: for “{title}” I would answer “{topic}” from the lesson body. "
        "Wire a real provider (aikey / openai / ollama) to get grounded answers."
    )


def _mock_edit(note_markdown: str, instruction: str) -> str:
    header = f"> _Mock edit applied: {instruction.strip()}_"
    return header + "\n\n" + note_markdown
