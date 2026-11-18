"""Model Context Protocol server over stdio.

Exposes the vault as a handful of tools so an external assistant (Claude
Desktop, an IDE agent, a local MCP client) can search notes, ask the course,
read a lesson, draft cards, review them, capture ideas, and inspect the concept
graph. Transport is newline-delimited JSON-RPC 2.0 on stdin/stdout; nothing
leaves the machine except the transcript text a configured provider receives.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable

from . import __version__, cards, capture, embed, graph, plugins, publish, quiz, rag, vault
from .indexdb import IndexError_, search as search_index
from .providers import ProviderError, chat, resolve_provider

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "shellslatee", "version": __version__}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "vault_overview",
        "description": "Summarize a Shellslatee vault: lesson count, modules, concepts, total duration.",
        "inputSchema": {
            "type": "object",
            "properties": {"out": {"type": "string", "description": "Vault (output) folder."}},
            "required": ["out"],
        },
    },
    {
        "name": "search_notes",
        "description": "Full-text search across every note in the vault.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "out": {"type": "string"},
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                "mode": {"type": "string", "enum": ["fts", "hybrid", "semantic"]},
            },
            "required": ["out", "query"],
        },
    },
    {
        "name": "read_note",
        "description": "Read a single note's Markdown by its vault-relative path.",
        "inputSchema": {
            "type": "object",
            "properties": {"out": {"type": "string"}, "rel": {"type": "string"}},
            "required": ["out", "rel"],
        },
    },
    {
        "name": "ask_course",
        "description": "Answer a question across the whole course with timestamped citations.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "out": {"type": "string"},
                "question": {"type": "string"},
                "provider": {"type": "string"},
                "model": {"type": "string"},
            },
            "required": ["out", "question"],
        },
    },
    {
        "name": "build_cards",
        "description": "Generate spaced-repetition cards from the vault's notes.",
        "inputSchema": {
            "type": "object",
            "properties": {"out": {"type": "string"}},
            "required": ["out"],
        },
    },
    {
        "name": "list_cards",
        "description": "List cards due for review now.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "out": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "required": ["out"],
        },
    },
    {
        "name": "drill_cards",
        "description": "Weak-concept drill queue: cards ranked by lapses, short stability, and overdue-ness, grouped by concept.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "out": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "required": ["out"],
        },
    },
    {
        "name": "review_card",
        "description": "Record a review grade for a card: 1 again, 2 hard, 3 good, 4 easy.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "out": {"type": "string"},
                "id": {"type": "string"},
                "grade": {"type": "integer", "minimum": 1, "maximum": 4},
            },
            "required": ["out", "id", "grade"],
        },
    },
    {
        "name": "capture",
        "description": "Append a quick note to the vault's inbox.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "out": {"type": "string"},
                "text": {"type": "string"},
                "tag": {"type": "string"},
            },
            "required": ["out", "text"],
        },
    },
    {
        "name": "build_quiz",
        "description": "Generate quiz items from the vault; optionally focus on weak concept names.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "out": {"type": "string"},
                "focus": {"type": "array", "items": {"type": "string"}},
                "limit": {"type": "integer", "minimum": 0},
            },
            "required": ["out"],
        },
    },
    {
        "name": "list_quiz",
        "description": "List quiz items (multiple choice and short answer).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "out": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                "kind": {"type": "string", "enum": ["mcq", "short"]},
            },
            "required": ["out"],
        },
    },
    {
        "name": "check_quiz",
        "description": "Grade a quiz response; returns correctness, the expected answer, and the reason.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "out": {"type": "string"},
                "id": {"type": "string"},
                "response": {"type": "string"},
            },
            "required": ["out", "id", "response"],
        },
    },
    {
        "name": "concept_graph",
        "description": "Return the lesson/concept graph (nodes, covers and related edges, counts).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "out": {"type": "string"},
                "semantic": {"type": "boolean"},
            },
            "required": ["out"],
        },
    },
    {
        "name": "list_plugins",
        "description": "List installed note-transform plugins with kind, hooks, and enabled state.",
        "inputSchema": {
            "type": "object",
            "properties": {"out": {"type": "string"}},
            "required": ["out"],
        },
    },
    {
        "name": "publish_site",
        "description": "Build a deployable static study bundle from the vault; optionally zip it.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "out": {"type": "string"},
                "target": {"type": "string"},
                "base_url": {"type": "string"},
                "zip": {"type": "boolean"},
            },
            "required": ["out"],
        },
    },
]


class ToolError(RuntimeError):
    pass


def _require_dir(args: dict) -> Path:
    raw = args.get("out")
    if not raw or not isinstance(raw, str):
        raise ToolError("'out' (vault folder) is required")
    path = Path(raw).expanduser().resolve()
    if not path.is_dir():
        raise ToolError(f"vault folder not found: {raw}")
    return path


def _note_file(out_root: Path, rel: str) -> Path:
    target = (out_root / rel).resolve()
    try:
        target.relative_to(out_root)
    except ValueError as exc:
        raise ToolError("path escapes the vault") from exc
    if not target.is_file() or target.suffix != ".md":
        raise ToolError(f"note not found: {rel}")
    return target


def _tool_vault_overview(args: dict) -> Any:
    out_root = _require_dir(args)
    records, concepts = vault.collect(out_root)
    modules = sorted({record.module or "(root)" for record in records})
    return {
        "lessons": len(records),
        "concepts": len(concepts),
        "modules": modules,
        "total_seconds": round(sum(record.duration for record in records), 1),
        "items": [
            {"rel": record.lesson_rel, "title": record.title, "module": record.module}
            for record in records
        ],
    }


def _tool_search_notes(args: dict) -> Any:
    out_root = _require_dir(args)
    query = str(args.get("query", "")).strip()
    if not query:
        raise ToolError("'query' is required")
    limit = int(args.get("limit", 10))
    mode = str(args.get("mode") or "fts").lower()
    try:
        if mode == "hybrid":
            rows = embed.hybrid_search(out_root, query, limit)
        elif mode == "semantic":
            rows = embed.semantic(out_root, query, limit)
        else:
            rows = search_index(out_root, query, limit)
    except IndexError_ as exc:
        raise ToolError(str(exc)) from exc
    return {"query": query, "mode": mode, "rows": rows}


def _tool_read_note(args: dict) -> Any:
    out_root = _require_dir(args)
    rel = str(args.get("rel", ""))
    if not rel:
        raise ToolError("'rel' is required")
    path = _note_file(out_root, rel)
    return {"rel": rel, "markdown": path.read_text(encoding="utf-8", errors="replace")}


def _tool_ask_course(args: dict) -> Any:
    out_root = _require_dir(args)
    question = str(args.get("question", "")).strip()
    if not question:
        raise ToolError("'question' is required")
    provider, model, api_key = resolve_provider(
        str(args.get("provider") or "aikey"),
        str(args.get("model") or "") or None,
    )
    result = rag.answer(provider, model, api_key, out_root=out_root, question=question)
    return {
        "answer": result.answer,
        "citations": [citation.__dict__ for citation in result.citations],
        "tokens": {"in": result.tokens_in, "out": result.tokens_out},
    }


def _tool_build_cards(args: dict) -> Any:
    return cards.build(_require_dir(args))


def _tool_list_cards(args: dict) -> Any:
    return cards.due_cards(_require_dir(args), int(args.get("limit", 20)))


def _tool_drill_cards(args: dict) -> Any:
    return cards.drills(_require_dir(args), int(args.get("limit", 20)))


def _tool_review_card(args: dict) -> Any:
    out_root = _require_dir(args)
    card_id = str(args.get("id", ""))
    if not card_id:
        raise ToolError("'id' is required")
    try:
        grade = int(args.get("grade"))
    except (TypeError, ValueError) as exc:
        raise ToolError("'grade' must be 1-4") from exc
    result = cards.review(out_root, card_id, grade)
    if result is None:
        raise ToolError(f"card not found: {card_id}")
    return result


def _tool_capture(args: dict) -> Any:
    out_root = _require_dir(args)
    text = str(args.get("text", "")).strip()
    if not text:
        raise ToolError("'text' is required")
    return capture.capture(out_root, text, args.get("tag") or None)


def _tool_build_quiz(args: dict) -> Any:
    out_root = _require_dir(args)
    focus = args.get("focus")
    if isinstance(focus, str):
        focus = [focus]
    if not isinstance(focus, list):
        focus = None
    result = quiz.build(out_root, [str(item) for item in (focus or [])] or None, int(args.get("limit", 0) or 0))
    result["stats"] = quiz.stats(out_root)
    return result


def _tool_list_quiz(args: dict) -> Any:
    out_root = _require_dir(args)
    kind = args.get("kind")
    return {
        "stats": quiz.stats(out_root),
        "items": quiz.items(out_root, int(args.get("limit", 20)), kind if kind in {"mcq", "short"} else None),
    }


def _tool_check_quiz(args: dict) -> Any:
    out_root = _require_dir(args)
    quiz_id = str(args.get("id", ""))
    if not quiz_id:
        raise ToolError("'id' is required")
    result = quiz.check(out_root, quiz_id, args.get("response", ""))
    if result is None:
        raise ToolError(f"quiz item not found: {quiz_id}")
    return result


def _tool_concept_graph(args: dict) -> Any:
    return graph.build(_require_dir(args), semantic=bool(args.get("semantic", False)))


def _tool_list_plugins(args: dict) -> Any:
    return {"plugins": plugins.list_plugins(_require_dir(args))}


def _tool_publish_site(args: dict) -> Any:
    raw_target = args.get("target")
    target = Path(raw_target).expanduser().resolve() if isinstance(raw_target, str) and raw_target else None
    base_url = args.get("base_url") if isinstance(args.get("base_url"), str) else None
    return publish.build(
        _require_dir(args), target=target, base_url=base_url, zip_bundle=bool(args.get("zip"))
    )


HANDLERS: dict[str, Callable[[dict], Any]] = {
    "vault_overview": _tool_vault_overview,
    "search_notes": _tool_search_notes,
    "read_note": _tool_read_note,
    "ask_course": _tool_ask_course,
    "build_cards": _tool_build_cards,
    "list_cards": _tool_list_cards,
    "drill_cards": _tool_drill_cards,
    "review_card": _tool_review_card,
    "capture": _tool_capture,
    "build_quiz": _tool_build_quiz,
    "list_quiz": _tool_list_quiz,
    "check_quiz": _tool_check_quiz,
    "concept_graph": _tool_concept_graph,
    "list_plugins": _tool_list_plugins,
    "publish_site": _tool_publish_site,
}


def _result(request_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def handle(request: dict) -> dict | None:
    """Handle one JSON-RPC request. Returns ``None`` for notifications."""
    request_id = request.get("id")
    method = request.get("method")
    params = request.get("params") or {}

    if method == "initialize":
        return _result(
            request_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
            },
        )
    if method == "ping":
        return _result(request_id, {})
    if method == "tools/list":
        return _result(request_id, {"tools": TOOLS})
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        handler = HANDLERS.get(name or "")
        if handler is None:
            return _error(request_id, -32602, f"unknown tool: {name}")
        try:
            payload = handler(arguments)
        except (ToolError, ProviderError, ValueError, OSError) as exc:
            return _result(
                request_id,
                {"content": [{"type": "text", "text": f"error: {exc}"}], "isError": True},
            )
        return _result(
            request_id,
            {"content": [{"type": "text", "text": json.dumps(payload, indent=2)}]},
        )
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None
    if method is None:
        return _error(request_id, -32600, "invalid request")
    return _error(request_id, -32601, f"method not found: {method}")


def serve(stream_in=None, stream_out=None) -> int:
    source = stream_in or sys.stdin
    sink = stream_out or sys.stdout
    for line in source:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except ValueError:
            sink.write(json.dumps(_error(None, -32700, "parse error")) + "\n")
            sink.flush()
            continue
        response = handle(request)
        if response is not None:
            sink.write(json.dumps(response) + "\n")
            sink.flush()
    return 0
