from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from .providers import Provider, ProviderError, chat
from .quality import score_note
from .templates import Template, get_template
from .transcribe import Transcript
from .util import fmt_ts

MAX_TRANSCRIPT_CHARS = 24000
REDUCE_HEAD_CHARS = 4000

SYSTEM_PROMPT = """You write study notes from a lesson transcript.
Return ONE JSON object, no prose, no markdown fences, with exactly these keys:
{
  "title": string,
  "summary": string,
  "key_concepts": [{"name": string, "definition": string}],
  "topics": [{"start": number, "title": string, "details": [string]}],
  "review_questions": [string],
  "tags": [string]
}
Rules:
- "start" is seconds from the video start, copied from the transcript timestamps.
- Only claim what the transcript or the on-screen text supports. Never invent examples or numbers.
- When on-screen text is provided, copy exact commands, code, headers, URLs and status codes from it; prefer it over the transcript when the speech is vague.
- Summary: 3-6 sentences, plain language, no bullet points.
- key_concepts: 3-8 items, each a real term the lesson uses.
- topics: 3-12 items covering the lesson in order.
- review_questions: 3-6 questions answerable from the notes.
- tags: 2-6 lowercase topic tags.
"""

MAP_PROMPT = """You outline a chunk of a lesson transcript.
Return ONE JSON object: {"topics": [{"start": number, "title": string, "details": [string]}]}
Use only content present in this chunk. Keep each title under 10 words."""


class GenerateError(RuntimeError):
    pass


@dataclass
class Note:
    title: str
    summary: str
    key_concepts: list[dict[str, str]]
    topics: list[dict[str, Any]]
    review_questions: list[str]
    tags: list[str]
    tokens_in: int = 0
    tokens_out: int = 0
    template: str = "lecture"
    quality: int = 0
    quality_issues: list[str] = field(default_factory=list)
    attempts: int = 1

    def concept_names(self) -> list[str]:
        return [item["name"] for item in self.key_concepts]


@dataclass
class NoteMeta:
    note_id: str
    course_title: str
    module: str
    order: int
    source_rel: str
    source_hash: str
    duration: float
    engine: str
    asr_model: str
    provider: str
    model: str
    generated: str
    generation: int = 1
    extra: dict[str, Any] = field(default_factory=dict)


def _parse_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end <= start:
            raise GenerateError("model did not return JSON")
        try:
            payload = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise GenerateError(f"model returned invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise GenerateError("model returned JSON that is not an object")
    return payload


def _require_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise GenerateError(f"missing or empty field: {key}")
    return value.strip()


def _coerce_concepts(value: Any) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    if isinstance(value, list):
        for entry in value:
            if isinstance(entry, str) and entry.strip():
                items.append({"name": entry.strip(), "definition": ""})
            elif isinstance(entry, dict) and str(entry.get("name", "")).strip():
                items.append(
                    {
                        "name": str(entry["name"]).strip(),
                        "definition": str(entry.get("definition", "")).strip(),
                    }
                )
    if not items:
        raise GenerateError("key_concepts must be a non-empty list")
    return items[:12]


def _to_seconds(value: Any) -> float:
    if isinstance(value, (int, float)):
        return max(0.0, float(value))
    if isinstance(value, str):
        match = re.match(r"^(?:(\d+):)?(\d{1,2}):(\d{2})$", value.strip())
        if match:
            hours = int(match.group(1) or 0)
            return float(hours * 3600 + int(match.group(2)) * 60 + int(match.group(3)))
    return 0.0


def _coerce_topics(value: Any) -> list[dict[str, Any]]:
    topics: list[dict[str, Any]] = []
    if isinstance(value, list):
        for entry in value:
            if not isinstance(entry, dict):
                continue
            title = str(entry.get("title", "")).strip()
            if not title:
                continue
            details = entry.get("details")
            if isinstance(details, str):
                details = [details]
            clean_details = [str(item).strip() for item in details or [] if str(item).strip()]
            topics.append(
                {
                    "start": _to_seconds(entry.get("start")),
                    "title": title,
                    "details": clean_details[:8],
                }
            )
    if not topics:
        raise GenerateError("topics must be a non-empty list")
    topics.sort(key=lambda item: item["start"])
    return topics[:16]


def _coerce_str_list(value: Any, key: str) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        raise GenerateError(f"{key} must be a list of strings")
    items = [str(item).strip() for item in value if str(item).strip()]
    if not items:
        raise GenerateError(f"{key} must not be empty")
    return items[:10]


def _build_note(payload: dict[str, Any], tokens: tuple[int, int]) -> Note:
    return Note(
        title=_require_str(payload, "title"),
        summary=_require_str(payload, "summary"),
        key_concepts=_coerce_concepts(payload.get("key_concepts")),
        topics=_coerce_topics(payload.get("topics")),
        review_questions=_coerce_str_list(payload.get("review_questions"), "review_questions"),
        tags=[tag.lower() for tag in _coerce_str_list(payload.get("tags"), "tags")],
        tokens_in=tokens[0],
        tokens_out=tokens[1],
    )


def _visual_block(visual: list[dict[str, Any]] | None, limit: int = 8000) -> str:
    if not visual:
        return ""
    lines: list[str] = []
    used = 0
    for block in visual:
        text = str(block.get("text", "")).strip()
        if not text:
            continue
        stamp = fmt_ts(float(block.get("start", 0) or 0))
        entry = f"[{stamp}]\n{text}"
        if used + len(entry) > limit:
            break
        lines.append(entry)
        used += len(entry)
    if not lines:
        return ""
    return (
        "On-screen text captured from the video (OCR, may contain minor character "
        "errors; timestamps mm:ss):\n" + "\n\n".join(lines)
    )


def _system_prompt(template: Template) -> str:
    return SYSTEM_PROMPT + f"\nTemplate focus — {template.label}:\n{template.guidance}\n"


def _single_pass(
    provider: Provider,
    model: str,
    api_key: str,
    meta: NoteMeta,
    title_hint: str,
    body: str,
    template: Template,
    feedback: list[str] | None = None,
    visual: list[dict[str, Any]] | None = None,
) -> Note:
    user = (
        f"Course: {meta.course_title}\n"
        f"Module: {meta.module}\n"
        f"Lesson title: {title_hint}\n"
        f"Duration: {fmt_ts(meta.duration)}\n\n"
        "Transcript with timestamps (mm:ss):\n"
        f"{body}"
    )
    visual_block = _visual_block(visual)
    if visual_block:
        user += "\n\n" + visual_block
    if feedback:
        user += "\n\nA previous attempt failed the quality rubric. Fix: " + "; ".join(feedback)
    system = _system_prompt(template)
    raw, tokens = chat(
        provider,
        model,
        api_key,
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    try:
        return _build_note(_parse_json(raw), (tokens["in"], tokens["out"]))
    except GenerateError as exc:
        repair = user + f"\n\nYour previous reply was unusable: {exc}. Return valid JSON only."
        raw, more = chat(
            provider,
            model,
            api_key,
            [{"role": "system", "content": system}, {"role": "user", "content": repair}],
        )
        note = _build_note(_parse_json(raw), (tokens["in"] + more["in"], tokens["out"] + more["out"]))
        return note


def _map_chunks(
    provider: Provider, model: str, api_key: str, chunks: list[str]
) -> tuple[list[dict[str, Any]], tuple[int, int]]:
    merged: list[dict[str, Any]] = []
    tokens_in = 0
    tokens_out = 0
    for chunk in chunks[:24]:
        try:
            raw, tokens = chat(
                provider,
                model,
                api_key,
                [{"role": "system", "content": MAP_PROMPT}, {"role": "user", "content": chunk}],
            )
            tokens_in += tokens["in"]
            tokens_out += tokens["out"]
            payload = _parse_json(raw)
            for topic in payload.get("topics", []) if isinstance(payload.get("topics"), list) else []:
                if isinstance(topic, dict) and str(topic.get("title", "")).strip():
                    merged.append(topic)
        except (GenerateError, ProviderError):
            continue
    return merged, (tokens_in, tokens_out)


def _build_once(
    provider: Provider,
    model: str,
    api_key: str,
    meta: NoteMeta,
    title_hint: str,
    body: str,
    template: Template,
    feedback: list[str] | None = None,
    visual: list[dict[str, Any]] | None = None,
) -> Note:
    if len(body) <= MAX_TRANSCRIPT_CHARS:
        return _single_pass(provider, model, api_key, meta, title_hint, body, template, feedback, visual)

    chunks = _split_transcript(body)
    outline, (map_in, map_out) = _map_chunks(provider, model, api_key, chunks)
    outline_text = "\n".join(
        f"- [{fmt_ts(_to_seconds(item.get('start')))}] {item.get('title', '').strip()}"
        for item in outline[:40]
    )
    condensed = (
        f"{body[:REDUCE_HEAD_CHARS]}\n\n"
        "[... later transcript summarized as an outline ...]\n"
        f"{outline_text or '[no outline produced]'}"
    )
    note = _single_pass(provider, model, api_key, meta, title_hint, condensed, template, feedback, visual)
    note.tokens_in += map_in
    note.tokens_out += map_out
    return note


def generate_note(
    provider: Provider,
    model: str,
    api_key: str,
    meta: NoteMeta,
    title_hint: str,
    transcript: Transcript,
    template: str | None = None,
    quality_min: int | None = None,
    visual: list[dict[str, Any]] | None = None,
) -> Note:
    """Generate a note, score it against the quality rubric, and retry once if it falls short.

    ``quality_min=None`` uses the template's own floor; ``0`` disables the retry.
    At most two generation attempts are made — the better-scored note wins.
    """
    tmpl = get_template(template)
    floor = tmpl.quality_floor if quality_min is None else max(0, quality_min)
    body = transcript.stamped_text()

    note = _build_once(provider, model, api_key, meta, title_hint, body, tmpl, visual=visual)
    rubric = score_note(note, body, meta.duration, tmpl)
    total_in = note.tokens_in
    total_out = note.tokens_out
    attempts = 1

    if floor and rubric.score < floor:
        retry = _build_once(
            provider, model, api_key, meta, title_hint, body, tmpl,
            feedback=rubric.issues, visual=visual,
        )
        total_in += retry.tokens_in
        total_out += retry.tokens_out
        retry_rubric = score_note(retry, body, meta.duration, tmpl)
        attempts = 2
        if retry_rubric.score >= rubric.score:
            note, rubric = retry, retry_rubric

    note.tokens_in = total_in
    note.tokens_out = total_out
    note.template = tmpl.name
    note.quality = rubric.score
    note.quality_issues = list(rubric.issues)
    note.attempts = attempts
    return note


def _split_transcript(body: str) -> list[str]:
    lines = body.splitlines()
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for line in lines:
        current.append(line)
        size += len(line) + 1
        if size >= MAX_TRANSCRIPT_CHARS:
            chunks.append("\n".join(current))
            current = []
            size = 0
    if current:
        chunks.append("\n".join(current))
    return chunks
