from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path

from . import __version__
from . import cards, capture, embed, export, graph, keychain, mcp, pause, plugins, publish, quiz, rag, tui, watch
from . import providers as providers_mod
from .cost import estimate
from .frames import DEFAULT_INTERVAL, DEFAULT_MAX_FRAMES, FramesError, harvest_visual_notes, ocr_backend
from .generate import GenerateError, Note, NoteMeta, generate_note
from .indexdb import IndexError_, build as build_index, search as search_index
from .media import MediaError, probe_duration
from . import providers
from .providers import PRESETS, Provider, ProviderError, estimate_cost, resolve_provider
from .render import (
    NoteRecord,
    render_concept_pages,
    render_failed,
    render_module_index,
    render_readme,
    write_note,
)
from .docs import DOC_EXTS
from .scanner import ScanError, SourceFile, scan
from .state import State
from .templates import DEFAULT_TEMPLATE, template_names
from .transcribe import TranscribeSettings, TranscriberError, override_path, transcribe_source
from .tree import module_of, note_path, video_uri
from .util import (
    atomic_write,
    human_duration,
    pretty_name,
    sha256_file,
    sha256_text,
    utc_now,
)
from .vault import collect

FAILURE_TYPES = (TranscriberError, GenerateError, ProviderError, MediaError, OSError)


def _emit(message: str = "") -> None:
    print(message, file=sys.stderr, flush=True)


def _event(enabled: bool, kind: str, **fields) -> None:
    """Machine-readable NDJSON on stdout. Human logs keep going to stderr."""
    if enabled:
        print(json.dumps({"event": kind, **fields}, separators=(",", ":")), flush=True)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shellslatee",
        description="Turn a folder of videos into a mirrored vault of study notes.",
    )
    parser.add_argument("--version", action="version", version=f"shellslatee {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    scan_parser = sub.add_parser("scan", help="list videos found in a folder")
    scan_parser.add_argument("source", type=Path)
    scan_parser.add_argument("--json", action="store_true", dest="as_json")

    run_parser = sub.add_parser("run", help="transcribe and write notes")
    run_parser.add_argument("source", type=Path)
    run_parser.add_argument("output", type=Path)
    run_parser.add_argument(
        "--provider", default=None, choices=sorted(PRESETS),
        help="provider (default: aikey, or the stored value from .shellslatee/settings.json)",
    )
    run_parser.add_argument("--model", default=None)
    run_parser.add_argument(
        "--transcriber", default=None, choices=["auto", "whisper", "subs", "mock"],
        help="transcription mode (default: auto, or the stored value from .shellslatee/settings.json)",
    )
    run_parser.add_argument(
        "--language", default=None,
        help="ASR language (default: en, or the stored value from .shellslatee/settings.json)",
    )
    run_parser.add_argument("--course", default=None, help="course title for the vault")
    run_parser.add_argument("--whisper-bin", default=os.environ.get("SHELLSLATEE_WHISPER_BIN"))
    run_parser.add_argument("--whisper-model", default=os.environ.get("SHELLSLATEE_WHISPER_MODEL"))
    run_parser.add_argument("--jobs", type=int, default=2, help="parallel workers for transcribe+generate")
    run_parser.add_argument(
        "--template", default=None, choices=template_names(),
        help="note shape (default: lecture, or the stored value from .shellslatee/settings.json)",
    )
    run_parser.add_argument(
        "--quality-min", type=int, default=None,
        help="rubric floor 0-100 before one retry (default: the template's floor, 0 disables)",
    )
    run_parser.add_argument(
        "--visual", default=None, choices=["auto", "on", "off"],
        help="capture on-screen text from frames via OCR (default: auto — on when an OCR engine is present)",
    )
    run_parser.add_argument(
        "--frame-interval", type=float, default=None,
        help=f"seconds between sampled frames for OCR (default: {DEFAULT_INTERVAL:g})",
    )
    run_parser.add_argument(
        "--max-frames", type=int, default=None,
        help=f"cap on frames sampled per video (default: {DEFAULT_MAX_FRAMES})",
    )
    run_parser.add_argument("--keep-frames", action="store_true", help="keep sampled frames under .shellslatee/frames/")
    run_parser.add_argument("--limit", type=int, default=0)
    run_parser.add_argument("--force", action="store_true")
    run_parser.add_argument("--estimate-only", action="store_true")
    run_parser.add_argument(
        "--max-cost", type=float, default=None,
        help="hard USD ceiling for this run; stops before the next lesson would exceed it (0 disables)",
    )
    run_parser.add_argument(
        "--allow-over-budget", action="store_true",
        help="run even when the preflight estimate exceeds the ceiling",
    )
    run_parser.add_argument(
        "--json", action="store_true", dest="json_stream",
        help="emit NDJSON progress events on stdout (human logs stay on stderr)",
    )
    run_parser.add_argument(
        "--plugins", default="on", choices=["on", "off"],
        help="apply enabled note-transform plugins after writing (default: on)",
    )

    watch_parser = sub.add_parser("watch", help="re-run when the source folder changes")
    watch_parser.add_argument("source", type=Path)
    watch_parser.add_argument("output", type=Path)
    watch_parser.add_argument("--interval", type=float, default=5.0, help="seconds between checks")
    watch_parser.add_argument("--once", action="store_true", help="run one pass and exit")
    watch_parser.add_argument("--provider", default=None, choices=sorted(PRESETS))
    watch_parser.add_argument("--model", default=None)
    watch_parser.add_argument(
        "--transcriber", default=None, choices=["auto", "whisper", "subs", "mock"]
    )
    watch_parser.add_argument("--language", default=None)
    watch_parser.add_argument("--course", default=None)
    watch_parser.add_argument("--jobs", type=int, default=2)
    watch_parser.add_argument("--template", default=None, choices=template_names())
    watch_parser.add_argument("--limit", type=int, default=0)
    watch_parser.add_argument("--force", action="store_true")
    watch_parser.add_argument("--json", action="store_true", dest="json_stream")

    transcript_parser = sub.add_parser("transcript", help="dump or write an editable transcript sidecar")
    transcript_parser.add_argument("source", type=Path)
    transcript_parser.add_argument("--transcriber", default="auto", choices=["auto", "whisper", "subs", "mock"])
    transcript_parser.add_argument("--language", default="en")
    transcript_parser.add_argument("--whisper-bin", default=os.environ.get("SHELLSLATEE_WHISPER_BIN"))
    transcript_parser.add_argument("--whisper-model", default=os.environ.get("SHELLSLATEE_WHISPER_MODEL"))
    transcript_parser.add_argument("--write", action="store_true", help="write SOURCE.transcript.json beside the media")

    index_parser = sub.add_parser("index", help="rebuild indexes from notes on disk")
    index_parser.add_argument("output", type=Path)

    search_parser = sub.add_parser("search", help="full-text search over the vault index")
    search_parser.add_argument("output", type=Path)
    search_parser.add_argument("query")
    search_parser.add_argument("--limit", type=int, default=10)
    search_parser.add_argument(
        "--hybrid", action="store_true", help="fuse FTS5 with local embeddings (RRF)"
    )
    search_parser.add_argument(
        "--semantic", action="store_true", help="rank by local embedding similarity only"
    )

    cards_parser = sub.add_parser("cards", help="build and review spaced-repetition cards")
    cards_sub = cards_parser.add_subparsers(dest="cards_command", required=True)
    cards_build = cards_sub.add_parser("build", help="generate cards from notes")
    cards_build.add_argument("output", type=Path)
    cards_queue = cards_sub.add_parser("queue", help="show cards due now")
    cards_queue.add_argument("output", type=Path)
    cards_queue.add_argument("--limit", type=int, default=20)
    cards_review = cards_sub.add_parser("review", help="record a review grade (1-4)")
    cards_review.add_argument("output", type=Path)
    cards_review.add_argument("card_id")
    cards_review.add_argument("grade", type=int)
    cards_export = cards_sub.add_parser("export", help="export cards to Anki-importable CSV")
    cards_export.add_argument("output", type=Path)
    cards_export.add_argument("--path", type=Path, default=None)
    cards_stats = cards_sub.add_parser("stats", help="show card counts")
    cards_stats.add_argument("output", type=Path)
    cards_drills = cards_sub.add_parser("drills", help="weak-concept drill queue")
    cards_drills.add_argument("output", type=Path)
    cards_drills.add_argument("--limit", type=int, default=20)
    cards_drills.add_argument("--json", action="store_true", dest="as_json")

    export_parser = sub.add_parser("export", help="export the vault")
    export_sub = export_parser.add_subparsers(dest="export_command", required=True)
    export_site = export_sub.add_parser("site", help="render a static HTML site")
    export_site.add_argument("output", type=Path)
    export_site.add_argument("--target", type=Path, default=None)
    export_joplin = export_sub.add_parser("joplin", help="copy a Joplin-importable Markdown tree")
    export_joplin.add_argument("output", type=Path)
    export_joplin.add_argument("--target", type=Path, default=None)
    export_notion = export_sub.add_parser("notion", help="write a Notion-importable CSV")
    export_notion.add_argument("output", type=Path)
    export_notion.add_argument("--target", type=Path, default=None)
    export_anki = export_sub.add_parser("anki", help="write an Anki .apkg deck")
    export_anki.add_argument("output", type=Path)
    export_anki.add_argument("--target", type=Path, default=None)
    export_anki.add_argument("--deck", default=None, help="deck name (default: Shellslatee)")

    quiz_parser = sub.add_parser("quiz", help="build and take quizzes from the notes")
    quiz_sub = quiz_parser.add_subparsers(dest="quiz_command", required=True)
    quiz_build = quiz_sub.add_parser("build", help="generate quiz items from notes")
    quiz_build.add_argument("output", type=Path)
    quiz_build.add_argument("--focus", action="append", default=None, help="concept name to focus on (repeatable)")
    quiz_build.add_argument("--limit", type=int, default=0)
    quiz_list = quiz_sub.add_parser("list", help="list quiz items")
    quiz_list.add_argument("output", type=Path)
    quiz_list.add_argument("--limit", type=int, default=20)
    quiz_list.add_argument("--kind", default=None, choices=["mcq", "short"])
    quiz_list.add_argument("--json", action="store_true", dest="as_json")
    quiz_check = quiz_sub.add_parser("check", help="grade one answer")
    quiz_check.add_argument("output", type=Path)
    quiz_check.add_argument("quiz_id")
    quiz_check.add_argument("response")
    quiz_stats = quiz_sub.add_parser("stats", help="show quiz counts")
    quiz_stats.add_argument("output", type=Path)

    tui_parser = sub.add_parser("tui", help="run with a live terminal progress view")
    tui_parser.add_argument("source", type=Path)
    tui_parser.add_argument("output", type=Path)
    tui_parser.add_argument("rest", nargs=argparse.REMAINDER, help="extra run flags after --")

    ask_parser = sub.add_parser("ask", help="ask a question across the whole course")
    ask_parser.add_argument("output", type=Path)
    ask_parser.add_argument("question")
    ask_parser.add_argument("--provider", default="aikey", choices=sorted(PRESETS))
    ask_parser.add_argument("--model", default=None)
    ask_parser.add_argument("--json", action="store_true", dest="as_json")

    capture_parser = sub.add_parser("capture", help="append a quick note to the inbox")
    capture_parser.add_argument("output", type=Path)
    capture_parser.add_argument("text")
    capture_parser.add_argument("--tag", default=None)

    graph_parser = sub.add_parser("graph", help="build the concept/lesson graph")
    graph_parser.add_argument("output", type=Path)
    graph_parser.add_argument("--canvas", type=Path, default=None, help="write an Obsidian .canvas")
    graph_parser.add_argument("--semantic", action="store_true", help="add embedding-based related links")
    graph_parser.add_argument("--json", action="store_true", dest="as_json")

    plugins_parser = sub.add_parser("plugins", help="manage note-transform plugins")
    plugins_sub = plugins_parser.add_subparsers(dest="plugins_command", required=True)
    plugins_list = plugins_sub.add_parser("list", help="list discovered plugins")
    plugins_list.add_argument("output", type=Path)
    plugins_list.add_argument("--json", action="store_true", dest="as_json")
    plugins_info = plugins_sub.add_parser("info", help="show one plugin's manifest")
    plugins_info.add_argument("output", type=Path)
    plugins_info.add_argument("name")
    plugins_info.add_argument("--json", action="store_true", dest="as_json")
    plugins_enable = plugins_sub.add_parser("enable", help="enable a plugin")
    plugins_enable.add_argument("output", type=Path)
    plugins_enable.add_argument("name")
    plugins_disable = plugins_sub.add_parser("disable", help="disable a plugin")
    plugins_disable.add_argument("output", type=Path)
    plugins_disable.add_argument("name")
    plugins_validate = plugins_sub.add_parser("validate", help="validate all plugin manifests")
    plugins_validate.add_argument("output", type=Path)
    plugins_validate.add_argument("--json", action="store_true", dest="as_json")
    plugins_run = plugins_sub.add_parser("run", help="apply enabled transforms across the vault")
    plugins_run.add_argument("output", type=Path)

    publish_parser = sub.add_parser("publish", help="build a deployable static study bundle")
    publish_parser.add_argument("output", type=Path)
    publish_parser.add_argument("--target", type=Path, default=None)
    publish_parser.add_argument("--base-url", default=None, help="canonical host prefix for page links")
    publish_parser.add_argument("--zip", action="store_true", dest="zip_bundle", help="also write a zip archive")

    keys_parser = sub.add_parser("keys", help="manage provider keys in the OS keychain")
    keys_sub = keys_parser.add_subparsers(dest="keys_command", required=True)
    keys_sub.add_parser("status", help="show keychain backend and stored providers")
    keys_set = keys_sub.add_parser("set", help="store a provider key (reads stdin unless --secret)")
    keys_set.add_argument("account", help="provider name, e.g. aikey")
    keys_set.add_argument("--secret", default=None)
    keys_get = keys_sub.add_parser("get", help="print whether a provider key is stored")
    keys_get.add_argument("account")
    keys_del = keys_sub.add_parser("delete", help="remove a provider key")
    keys_del.add_argument("account")

    sub.add_parser("doctor", help="check the local environment")
    provision_parser = sub.add_parser(
        "provision",
        help="download ffmpeg + a whisper model and wire the transcription stack",
    )
    provision_parser.add_argument("--dir", type=Path, default=None, help="target directory (default: per-user app data)")
    provision_parser.add_argument("--model", default="tiny.en", help="ggml model size (default: tiny.en)")
    provision_parser.add_argument("--force", action="store_true", help="redownload and rewrite everything")
    sub.add_parser("mcp", help="start the MCP server on stdio (for MCP clients)")

    serve_parser = sub.add_parser("serve", help="run the local reader API and web UI")
    serve_parser.add_argument("--host", default="127.0.0.1", help="bind address (default: loopback only)")
    serve_parser.add_argument("--port", type=int, default=8677)
    serve_parser.add_argument("--web", type=Path, default=None, help="serve a prebuilt UI folder instead of web/dist")
    return parser


def _scan_exit(source: Path) -> list[SourceFile]:
    try:
        return scan(source)
    except ScanError as exc:
        _emit(f"error: {exc}")
        raise SystemExit(2)


def cmd_scan(args: argparse.Namespace) -> int:
    found = _scan_exit(args.source)
    if args.as_json:
        print(
            json.dumps(
                [
                    {
                        "path": str(item.rel),
                        "kind": item.kind,
                        "bytes": item.size,
                        "subtitle": str(item.subtitle.name) if item.subtitle else None,
                    }
                    for item in found
                ],
                indent=2,
            )
        )
        return 0
    for item in found:
        sub = f"  + {item.subtitle.name}" if item.subtitle else ""
        print(f"{item.kind:6} {item.rel}{sub}")
    print(f"\n{len(found)} file(s)", file=sys.stderr)
    return 0


def rebuild_indexes(
    out_root: Path, course_title: str | None = None
) -> tuple[list[NoteRecord], dict[str, dict]]:
    records, concepts = collect(out_root)
    if not records:
        return records, concepts

    modules: dict[str, list[NoteRecord]] = {}
    for record in records:
        modules.setdefault(record.module, []).append(record)

    for module, module_records in modules.items():
        index_path = out_root / module / "_index.md" if module else out_root / "_index.md"
        title_module = module if module else "Course root"
        atomic_write(
            index_path,
            render_module_index(title_module, module_records, out_root, index_path, concepts),
        )

    fallback_title = (
        course_title
        or out_root.name.replace("-", " ").replace("_", " ").strip().title()
        or "Course"
    )
    readme_path = out_root / "README.md"
    existing_title = ""
    if readme_path.exists():
        first = readme_path.read_text(encoding="utf-8", errors="replace").splitlines()[:1]
        if first and first[0].startswith("# "):
            existing_title = first[0][2:].strip()
    atomic_write(readme_path, render_readme(existing_title or fallback_title, records, out_root))
    if concepts:
        render_concept_pages(records, out_root, concepts)
    build_index(out_root)
    return records, concepts


WATCH_DEFAULTS = {
    "whisper_bin": os.environ.get("SHELLSLATEE_WHISPER_BIN"),
    "whisper_model": os.environ.get("SHELLSLATEE_WHISPER_MODEL"),
    "quality_min": None,
    "visual": None,
    "frame_interval": None,
    "max_frames": None,
    "keep_frames": False,
    "estimate_only": False,
    "max_cost": None,
    "allow_over_budget": False,
}


def cmd_watch(args: argparse.Namespace) -> int:
    for name, value in WATCH_DEFAULTS.items():
        if not hasattr(args, name):
            setattr(args, name, value)
    source = args.source.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if source == output:
        _emit("error: output folder must differ from the source folder")
        return 2
    _emit(f"watch: {source} -> {output} every {args.interval:g}s (ctrl-c to stop)")
    seen: tuple | None = None
    rc = 0
    while True:
        current = watch.fingerprint(source, output)
        if current != seen:
            seen = current
            _emit("watch: change detected — running")
            rc = cmd_run(args)
            _emit("watch: pass finished — waiting for changes")
        if args.once:
            return rc
        try:
            time.sleep(max(0.5, args.interval))
        except KeyboardInterrupt:
            _emit("watch: stopped")
            return 0


def cmd_transcript(args: argparse.Namespace) -> int:
    path: Path = args.source.expanduser().resolve()
    if path.is_dir():
        try:
            items = scan(path)
        except ScanError as exc:
            _emit(f"error: {exc}")
            return 2
    elif path.is_file():
        kind = "document" if path.suffix.lower() in DOC_EXTS else "video"
        items = [SourceFile(path=path, rel=Path(path.name), kind=kind, size=path.stat().st_size, subtitle=None)]
    else:
        _emit(f"error: not a file or folder: {path}")
        return 2
    settings = _settings(args)
    written = 0
    for item in items:
        try:
            transcript = transcribe_source(item, settings)
        except TranscriberError as exc:
            _emit(f"!! {item.rel} — {exc}")
            continue
        payload = {
            "engine": transcript.engine,
            "model": transcript.model,
            "language": transcript.language,
            "segments": [
                {"start": round(segment.start, 3), "end": round(segment.end, 3), "text": segment.text}
                for segment in transcript.segments
            ],
        }
        text = json.dumps(payload, indent=2)
        if args.write:
            target = override_path(item.path)
            atomic_write(target, text + "\n")
            _emit(f"wrote {target}")
        else:
            print(text)
        written += 1
    return 0 if written else 1


def cmd_index(args: argparse.Namespace) -> int:
    records, concepts = rebuild_indexes(args.output)
    _emit(f"indexed {len(records)} note(s), {len(concepts)} concept(s)")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    semantic = bool(getattr(args, "semantic", False))
    hybrid = bool(getattr(args, "hybrid", False))
    try:
        if semantic:
            rows = embed.semantic(args.output, args.query, args.limit)
        elif hybrid:
            rows = embed.hybrid_search(args.output, args.query, args.limit)
        else:
            rows = search_index(args.output, args.query, args.limit)
    except IndexError_ as exc:
        _emit(f"error: {exc}")
        return 2
    for row in rows:
        score = f"  ({row['score']})" if row.get("score") else ""
        print(f"{row['title']}  [{row['section']}]  {row['path']}{score}")
        print(f"  {row['snippet']}")
    if not rows:
        _emit("no matches")
    return 0


def cmd_cards(args: argparse.Namespace) -> int:
    out_root: Path = args.output
    if args.cards_command == "build":
        result = cards.build(out_root)
        _emit(f"cards: {result['created']} created, {result['updated']} updated, {result['total']} total")
        return 0
    if args.cards_command == "queue":
        payload = cards.due_cards(out_root, args.limit)
        _emit(
            f"{payload['stats']['due']} due · {payload['stats']['new']} new · "
            f"{payload['stats']['total']} total"
        )
        for card in payload["cards"]:
            print(f"[{card['id']}] {card['front']}")
            if card["back"]:
                print(f"    {card['back']}")
        return 0
    if args.cards_command == "review":
        result = cards.review(out_root, args.card_id, args.grade)
        if result is None:
            _emit("error: card not found")
            return 2
        _emit(f"reviewed {args.card_id}: next in {result['interval_s'] / 3600:.1f}h")
        return 0
    if args.cards_command == "export":
        target = args.path or (out_root / "cards.csv")
        count = cards.export_csv(out_root, target)
        _emit(f"exported {count} card(s) -> {target}")
        return 0
    if args.cards_command == "stats":
        payload = cards.stats(out_root)
        _emit(f"{payload['total']} total · {payload['new']} new · {payload['due']} due now")
        return 0
    if args.cards_command == "drills":
        payload = cards.drills(out_root, args.limit)
        if args.as_json:
            print(json.dumps(payload, indent=2))
            return 0
        if not payload["cards"]:
            _emit("no weak cards yet — review some cards first")
            return 0
        _emit(
            f"{len(payload['cards'])} weak card(s) across {len(payload['groups'])} group(s)"
        )
        for group in payload["groups"]:
            label = group["concept"] or group["lesson"]
            print(f"\n{label}  (weakness {group['weakness']:.2f})")
            for card in group["cards"]:
                print(f"  [{card['id']}] {card['front']}")
        return 0
    return 2


def cmd_export(args: argparse.Namespace) -> int:
    out_root: Path = args.output
    if not out_root.is_dir():
        _emit(f"error: vault folder not found: {out_root}")
        return 2
    if args.export_command == "site":
        target = args.target or (out_root / "_site")
        count = export.export_site(out_root, target)
        _emit(f"site: {count} page(s) -> {target}")
        return 0
    if args.export_command == "joplin":
        target = args.target or (out_root / "_joplin")
        count = export.export_joplin(out_root, target)
        _emit(f"joplin: {count} note(s) -> {target}")
        return 0
    if args.export_command == "notion":
        target = args.target or (out_root / "_notion.csv")
        count = export.export_notion(out_root, target)
        _emit(f"notion: {count} row(s) -> {target}")
        return 0
    if args.export_command == "anki":
        from . import anki

        target = args.target or (out_root / "_exports" / "shellslatee.apkg")
        deck = args.deck or "Shellslatee"
        count = anki.build(out_root, target, deck)
        _emit(f"anki: {count} card(s) -> {target}")
        return 0
    return 2


def cmd_ask(args: argparse.Namespace) -> int:
    try:
        provider, model, api_key = resolve_provider(args.provider, args.model)
    except ProviderError as exc:
        _emit(f"error: {exc}")
        return 2
    try:
        result = rag.answer(provider, model, api_key, out_root=args.output, question=args.question)
    except ProviderError as exc:
        _emit(f"error: {exc}")
        return 2
    if args.as_json:
        print(
            json.dumps(
                {
                    "answer": result.answer,
                    "citations": [citation.__dict__ for citation in result.citations],
                },
                indent=2,
            )
        )
        return 0
    print(result.answer)
    if result.citations:
        print()
        for citation in result.citations:
            stamp = f" @{citation.start}s" if citation.start is not None else ""
            print(f"  [{citation.n}] {citation.title} — {citation.section}{stamp} ({citation.rel})")
    return 0


def cmd_capture(args: argparse.Namespace) -> int:
    try:
        result = capture.capture(args.output, args.text, args.tag)
    except ValueError as exc:
        _emit(f"error: {exc}")
        return 2
    _emit(f"captured -> {result['path']}")
    return 0


def cmd_graph(args: argparse.Namespace) -> int:
    semantic = bool(getattr(args, "semantic", False))
    payload = graph.build(args.output, semantic=semantic)
    if args.canvas is not None:
        count = graph.export_canvas(args.output, args.canvas, semantic=semantic)
        _emit(f"wrote {count} node(s) -> {args.canvas}")
    if args.as_json:
        print(json.dumps(payload, indent=2))
    else:
        counts = payload["counts"]
        _emit(f"graph: {counts['lessons']} lesson(s), {counts['concepts']} concept(s), {counts['edges']} edge(s)")
    return 0


def cmd_plugins(args: argparse.Namespace) -> int:
    out_root: Path = args.output
    if args.plugins_command == "list":
        rows = plugins.list_plugins(out_root)
        if args.as_json:
            print(json.dumps(rows, indent=2))
            return 0
        if not rows:
            _emit("no plugins found (drop one in .shellslatee/plugins/<name>/)")
            return 0
        for row in rows:
            state = "on " if row["enabled"] else ("bad" if not row["valid"] else "off")
            _emit(
                f"[{state}] {row['name']} {row['version']} ({row['kind']})  {', '.join(row['hooks'])}"
            )
            if row["error"]:
                print(f"    ! {row['error']}")
        return 0
    if args.plugins_command == "info":
        try:
            item = plugins.find(out_root, args.name)
        except plugins.PluginError as exc:
            _emit(f"error: {exc}")
            return 2
        payload = {"path": item["path"], "enabled": item["enabled"], **item["manifest"]}
        print(json.dumps(payload, indent=2))
        return 0
    if args.plugins_command in {"enable", "disable"}:
        try:
            result = plugins.set_enabled(out_root, args.name, args.plugins_command == "enable")
        except plugins.PluginError as exc:
            _emit(f"error: {exc}")
            return 2
        _emit(f"{result['name']}: {'enabled' if result['enabled'] else 'disabled'}")
        return 0
    if args.plugins_command == "validate":
        rows = plugins.validate(out_root)
        bad = [row for row in rows if not row["valid"]]
        if args.as_json:
            print(json.dumps(rows, indent=2))
            return 1 if bad else 0
        _emit(f"{len(rows) - len(bad)} valid, {len(bad)} invalid")
        for row in bad:
            print(f"  ! {row['name']}: {row['error']}")
        return 1 if bad else 0
    if args.plugins_command == "run":
        try:
            result = plugins.apply_to_vault(out_root)
        except plugins.PluginError as exc:
            _emit(f"error: {exc}")
            return 2
        names = ", ".join(result["plugins"]) or "none"
        _emit(f"plugins: {result['changed']} note(s) changed by {names}")
        return 0
    return 2


def cmd_keys(args: argparse.Namespace) -> int:
    if args.keys_command == "status":
        _emit(f"keychain: {keychain.backend_label()}")
        for name, preset in sorted(providers.PRESETS.items()):
            if not preset.api_key_env:
                continue
            stored = keychain.get(name)
            where = "keychain" if stored else ""
            keyfile = preset.api_key_file
            if not where and keyfile and Path(keyfile).expanduser().is_file():
                where = "key file"
            if not where and os.environ.get(preset.api_key_env):
                where = "env"
            _emit(f"{name:12} {where or 'not set'}")
        return 0
    if args.keys_command == "set":
        secret = args.secret
        if secret is None:
            secret = sys.stdin.readline().strip()
        if not secret:
            _emit("error: no secret supplied")
            return 2
        if not keychain.set(args.account, secret):
            _emit(f"error: keychain unavailable or store failed (backend: {keychain.backend_label()})")
            return 1
        _emit(f"{args.account}: stored in keychain")
        return 0
    if args.keys_command == "get":
        found = keychain.get(args.account) is not None
        _emit(f"{args.account}: {'stored' if found else 'not in keychain'}")
        return 0 if found else 1
    if args.keys_command == "delete":
        ok = keychain.delete(args.account)
        _emit(f"{args.account}: {'deleted' if ok else 'nothing to delete'}")
        return 0 if ok else 1
    return 2


def cmd_publish(args: argparse.Namespace) -> int:
    try:
        result = publish.build(
            args.output,
            target=args.target,
            base_url=args.base_url,
            zip_bundle=bool(args.zip_bundle),
        )
    except (OSError, plugins.PluginError) as exc:
        _emit(f"error: {exc}")
        return 2
    _emit(f"published {result['lessons']} lesson(s) -> {result['site']}")
    if result.get("base_url"):
        _emit(f"base url: {result['base_url']}")
    if result.get("archive"):
        _emit(f"archive: {result['archive']}")
    return 0


def cmd_quiz(args: argparse.Namespace) -> int:
    out_root: Path = args.output
    if args.quiz_command == "build":
        result = quiz.build(out_root, args.focus, args.limit)
        _emit(
            f"quiz: {result['created']} created, {result['updated']} updated, "
            f"{result['pruned']} pruned, {result['total']} total"
        )
        return 0
    if args.quiz_command == "list":
        items = quiz.items(out_root, args.limit, args.kind)
        if args.as_json:
            print(json.dumps(items, indent=2))
            return 0
        if not items:
            _emit("no quiz items yet — run: shellslatee quiz build OUT")
            return 0
        for item in items:
            print(f"[{item['id']}] {item['question']}")
            if item["kind"] == "mcq":
                for index, option in enumerate(item["options"], start=1):
                    marker = "*" if index - 1 == item["answer_index"] else " "
                    print(f"  {marker}{index}. {option}")
            else:
                print(f"   -> {item['answer']}")
            print(f"   lesson: {item['lesson']}")
        return 0
    if args.quiz_command == "check":
        result = quiz.check(out_root, args.quiz_id, args.response)
        if result is None:
            _emit("error: quiz item not found")
            return 2
        verdict = "correct" if result["correct"] else "wrong"
        _emit(f"{verdict}: {args.quiz_id}")
        print(f"expected: {result['answer']}")
        if result["explanation"] and result["explanation"] != result["answer"]:
            print(f"why: {result['explanation']}")
        return 0
    if args.quiz_command == "stats":
        payload = quiz.stats(out_root)
        _emit(
            f"{payload['total']} item(s) · {payload['mcq']} mcq · {payload['short']} short · "
            f"{payload['correct']}/{payload['attempts']} correct"
        )
        return 0
    return 2


def cmd_tui(args: argparse.Namespace) -> int:
    rest = [item for item in (args.rest or []) if item != "--"]
    return tui.run(args.source, args.output, rest)


def _settings(args: argparse.Namespace) -> TranscribeSettings:
    return TranscribeSettings(
        mode=args.transcriber,
        language=args.language,
        whisper_bin=args.whisper_bin,
        whisper_model=args.whisper_model,
    )


def _load_out_settings(out_root: Path) -> dict:
    """Read previously written OUT/.shellslatee/settings.json as run defaults."""
    path = out_root / ".shellslatee" / "settings.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _apply_stored_defaults(args: argparse.Namespace, stored: dict) -> None:
    """Fill unset CLI flags from the stored settings. CLI always wins."""
    stored = stored or {}
    if args.provider is None:
        provider = stored.get("provider")
        args.provider = provider if provider in PRESETS else "aikey"
    if args.transcriber is None:
        transcriber = stored.get("transcriber")
        args.transcriber = transcriber if transcriber in {"auto", "whisper", "subs", "mock"} else "auto"
    if args.language is None:
        language = stored.get("language")
        args.language = language if isinstance(language, str) and language else "en"
    if args.course is None:
        course = stored.get("course")
        args.course = course if isinstance(course, str) and course else None
    if args.template is None:
        template = stored.get("template")
        args.template = template if template in template_names() else DEFAULT_TEMPLATE
    if args.model is None and isinstance(stored.get("model"), str):
        if stored.get("provider") == args.provider:
            args.model = stored["model"]
    if getattr(args, "max_cost", None) is None:
        ceiling = stored.get("max_cost_usd")
        if isinstance(ceiling, (int, float)) and ceiling > 0:
            args.max_cost = float(ceiling)


@dataclass
class Job:
    source: SourceFile
    note_rel: Path
    note_id: str
    module: str
    order: int
    generation: int
    rel_key: str
    file_hash: str


def _process_job(
    job: Job,
    provider: Provider,
    model: str,
    api_key: str,
    settings: TranscribeSettings,
    course_title: str,
    template: str,
    quality_min: int | None,
    out_root: Path | None = None,
    visual_mode: str = "auto",
    frame_interval: float = DEFAULT_INTERVAL,
    max_frames: int = DEFAULT_MAX_FRAMES,
    keep_frames: bool = False,
) -> tuple[Note, NoteMeta]:
    # A paused run must not start new work; in-flight provider retries gate in
    # providers.chat(), and the run loop holds result recording until resumed.
    pause.PAUSE.wait_if_paused()
    transcript = transcribe_source(job.source, settings)
    visual, visual_engine = _harvest_visual(
        job, out_root, visual_mode, frame_interval, max_frames, keep_frames
    )
    meta = NoteMeta(
        note_id=job.note_id,
        course_title=course_title,
        module=job.module,
        order=job.order,
        source_rel=video_uri(job.source),
        source_hash=job.file_hash[:19],
        duration=transcript.duration,
        engine=transcript.engine,
        asr_model=transcript.model,
        provider=provider.name,
        model=model,
        generated=utc_now(),
        generation=job.generation,
    )
    if visual:
        meta.extra["visual"] = visual
        meta.extra["visual_engine"] = visual_engine
    note = generate_note(
        provider,
        model,
        api_key,
        meta,
        pretty_name(job.source.stem),
        transcript,
        template=template,
        quality_min=quality_min,
        visual=visual,
    )
    write_note(job.note_rel, note, meta)
    return note, meta


def _harvest_visual(
    job: Job,
    out_root: Path | None,
    mode: str,
    interval: float,
    max_frames: int,
    keep_frames: bool,
) -> tuple[list[dict], str]:
    if mode == "off" or job.source.kind == "document":
        return [], ""
    backend = ocr_backend()
    if not backend:
        if mode == "on":
            _emit("warning: --visual on but no OCR engine found; install rapidocr-onnxruntime or tesseract")
        return [], ""
    if out_root is None:
        return [], backend
    workdir = out_root / ".shellslatee" / "frames" / job.note_id
    try:
        notes, backend = harvest_visual_notes(
            job.source.path,
            workdir,
            interval=interval,
            max_frames=max_frames,
            keep_frames=keep_frames,
        )
    except FramesError as exc:
        _emit(f"warning: visual capture skipped for {job.rel_key} — {exc}")
        return [], backend
    visual = [{"start": note.start, "text": note.text} for note in notes]
    if visual:
        sidecar = out_root / ".shellslatee" / "visual" / f"{job.note_id}.json"
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        import json as _json

        sidecar.write_text(
            _json.dumps({"engine": backend, "blocks": visual}, indent=2),
            encoding="utf-8",
        )
    return visual, backend


def cmd_run(args: argparse.Namespace) -> int:
    source_root: Path = args.source.expanduser().resolve()
    out_root: Path = args.output.expanduser().resolve()
    if out_root == source_root:
        _emit("error: output folder must differ from the source folder")
        return 2

    _apply_stored_defaults(args, _load_out_settings(out_root))
    stream = bool(getattr(args, "json_stream", False))

    found = _scan_exit(source_root)
    if args.limit > 0:
        found = found[: args.limit]
    if not found:
        _emit("no sources found — nothing to do")
        return 0

    try:
        provider, model, api_key = resolve_provider(args.provider, args.model)
    except ProviderError as exc:
        _emit(f"error: {exc}")
        return 2

    durations: list[float] = []
    for item in found:
        if item.kind == "document":
            durations.append(0.0)
            continue
        try:
            durations.append(probe_duration(item.path))
        except MediaError:
            durations.append(0.0)
    projection = estimate(provider, model, durations)
    _event(
        stream,
        "start",
        total=len(found),
        seconds=round(sum(durations), 1),
        source=str(source_root),
        out=str(out_root),
        provider=provider.name,
        model=model,
    )
    _event(
        stream,
        "preflight",
        tokens_in=int(projection["tokens_in"]),
        tokens_out=int(projection["tokens_out"]),
        usd=projection["usd"],
        target=f"{provider.name}:{model}",
        template=args.template,
    )
    _emit(
        f"preflight: {len(found)} file(s) · {human_duration(sum(durations))} · "
        f"~{int(projection['tokens_in']):,} in / ~{int(projection['tokens_out']):,} out tokens · "
        f"est. ${projection['usd']:.2f} on {provider.name}:{model}"
    )

    settings = _settings(args)
    if args.estimate_only:
        for item in found:
            print(f"{item.kind:6} {item.rel}")
        return 0

    ceiling = float(getattr(args, "max_cost", None) or 0.0)
    allow_over = bool(getattr(args, "allow_over_budget", False))
    if ceiling > 0 and projection["usd"] > ceiling:
        if allow_over:
            _emit(
                f"budget: estimated ${projection['usd']:.2f} is over the ${ceiling:.2f} ceiling — "
                f"continuing anyway (--allow-over-budget)"
            )
        else:
            _emit(
                f"budget: estimated ${projection['usd']:.2f} is over the ${ceiling:.2f} ceiling — "
                f"will stop once the ceiling is reached"
            )

    course_title = args.course or pretty_name(source_root.name)
    state_dir = out_root / ".shellslatee"
    state = State.load(state_dir / "state.json")
    used_notes: set[Path] = set()
    jobs: list[Job] = []
    skipped = 0

    for position, source in enumerate(found, start=1):
        rel_key = source.rel.as_posix()
        file_hash = sha256_file(source.path)
        if not args.force and state.is_done(rel_key, file_hash):
            skipped += 1
            _emit(f"[{position}/{len(found)}] skip (cached) {rel_key}")
            _event(stream, "job", index=position, total=len(found), rel=rel_key, status="skip")
            continue

        previous = state.get(rel_key)
        generation = previous.generation + 1 if previous and previous.status == "done" else 1
        if previous and previous.note and (out_root / previous.note).exists():
            note_rel = out_root / previous.note
            used_notes.add(note_rel)
        else:
            note_rel = note_path(out_root, source, used_notes)

        jobs.append(
            Job(
                source=source,
                note_rel=note_rel,
                note_id="les_" + sha256_text(rel_key + file_hash)[:8],
                module=module_of(source.rel),
                order=position,
                generation=generation,
                rel_key=rel_key,
                file_hash=file_hash,
            )
        )

    visual_mode = args.visual or "auto"
    frame_interval = args.frame_interval or DEFAULT_INTERVAL
    max_frames = args.max_frames or DEFAULT_MAX_FRAMES
    if visual_mode != "off" and not ocr_backend() and visual_mode == "on":
        _emit("warning: --visual on but no OCR engine found; continuing audio-only")

    failures: list[tuple[str, str]] = []
    spent_usd = 0.0
    written = 0
    workers = max(1, args.jobs)
    budget_stopped = False

    def _on_rate_limit(name: str, status: int, _detail: str) -> None:
        _emit(f"rate limited: {name} HTTP {status} — retrying with backoff")
        _event(stream, "rate_limit", provider=name, status=status)

    providers_mod.RATE_LIMIT_HOOK = _on_rate_limit
    pause_ready = pause.install_signal_handlers()
    if pause_ready:
        _emit("pause: SIGUSR1 pauses between items, SIGUSR2 resumes")
    paused_announced = False
    _emit(f"running {len(jobs)} job(s) with {workers} worker(s)")

    def _over_budget() -> bool:
        return ceiling > 0 and not allow_over and spent_usd >= ceiling

    with ThreadPoolExecutor(max_workers=workers) as pool:
        queue = list(jobs)
        in_flight: dict = {}
        while queue or in_flight:
            # Submit only while the budget allows, so a ceiling stops the run
            # instead of merely warning after the lesson was already paid for.
            while queue and len(in_flight) < workers:
                if _over_budget():
                    budget_stopped = True
                    break
                job = queue.pop(0)
                _event(
                    stream, "job", index=job.order, total=len(found),
                    rel=job.rel_key, status="running",
                )
                future = pool.submit(
                    _process_job,
                    job,
                    provider,
                    model,
                    api_key,
                    settings,
                    course_title,
                    args.template,
                    args.quality_min,
                    out_root,
                    visual_mode,
                    frame_interval,
                    max_frames,
                    args.keep_frames,
                )
                in_flight[future] = job
            if not in_flight:
                break
            if pause.PAUSE.paused:
                if not paused_announced:
                    paused_announced = True
                    _emit("paused: holding until resumed (SIGUSR2)")
                    _event(stream, "paused")
                pause.PAUSE.wait_if_paused(poll=0.2)
                continue
            if paused_announced:
                paused_announced = False
                _emit("resumed")
                _event(stream, "resumed")
            completed, _ = wait(list(in_flight), timeout=0.25, return_when=FIRST_COMPLETED)
            for future in completed:
                job = in_flight.pop(future)
                try:
                    note, meta = future.result()
                except FAILURE_TYPES as exc:
                    message = str(exc)
                    state.record_failure(job.rel_key, job.file_hash, message)
                    state.save()
                    failures.append((job.rel_key, message))
                    _emit(f"!! {job.rel_key} — {message}")
                    _event(
                        stream, "job", index=job.order, total=len(found),
                        rel=job.rel_key, status="failed", error=message[:300],
                    )
                    continue

                state.record_done(
                    job.rel_key,
                    job.file_hash,
                    job.note_rel.relative_to(out_root).as_posix(),
                    meta.engine,
                    model,
                    job.generation,
                )
                state.save()
                item_usd = estimate_cost(provider, model, note.tokens_in, note.tokens_out)
                spent_usd += item_usd
                written += 1
                _event(
                    stream,
                    "job",
                    index=job.order,
                    total=len(found),
                    rel=job.rel_key,
                    status="done",
                    note=job.note_rel.relative_to(out_root).as_posix(),
                    generation=job.generation,
                    duration=round(meta.duration, 1),
                    quality=note.quality,
                    template=note.template,
                    attempts=note.attempts,
                    usd=round(item_usd, 6),
                )
                _emit(
                    f"-> {job.note_rel.relative_to(out_root)}  "
                    f"({human_duration(meta.duration)}, gen {job.generation})"
                )

        if queue:
            for job in queue:
                skipped += 1
                _emit(f"skip (budget ceiling reached) {job.rel_key}")
                _event(
                    stream, "job", index=job.order, total=len(found),
                    rel=job.rel_key, status="skip", reason="budget",
                )

    if budget_stopped:
        _emit(
            f"budget ceiling reached: spent ${spent_usd:.4f} of ${ceiling:.2f}; "
            f"remaining lessons are left for the next run"
        )
        _event(stream, "budget_stopped", spent=round(spent_usd, 6), ceiling=ceiling)

    settings_payload = {
        "provider": provider.name,
        "model": model,
        "transcriber": args.transcriber,
        "language": args.language,
        "course": course_title,
        "template": args.template,
        "max_cost_usd": ceiling,
        "updated": utc_now(),
    }
    atomic_write(state_dir / "settings.json", json.dumps(settings_payload, indent=2) + "\n")

    if getattr(args, "plugins", "on") == "on":
        try:
            applied = plugins.apply_to_vault(out_root)
            if applied["changed"]:
                names = ", ".join(applied["plugins"]) or "none"
                _emit(f"plugins: {applied['changed']} note(s) transformed by {names}")
                _event(stream, "plugins", changed=applied["changed"], plugins=applied["plugins"])
        except plugins.PluginError as exc:
            _emit(f"warning: plugin transform skipped — {exc}")

    records, concepts = rebuild_indexes(out_root, course_title)
    if failures:
        render_failed(failures, out_root)
    else:
        (out_root / "_failed.md").unlink(missing_ok=True)

    _emit(
        f"done: {written} written, {skipped} skipped, {len(failures)} failed · "
        f"{len(records)} note(s), {len(concepts)} concept(s) · spent ${spent_usd:.4f}"
    )
    _event(
        stream,
        "summary",
        written=written,
        skipped=skipped,
        failed=len(failures),
        notes=len(records),
        concepts=len(concepts),
        usd=round(spent_usd, 6),
    )
    if failures:
        _emit("see _failed.md")
        return 1
    if budget_stopped:
        return 3
    return 0


def cmd_mcp(_: argparse.Namespace) -> int:
    return mcp.serve()


def cmd_provision(args: argparse.Namespace) -> int:
    from . import asr_setup

    report = asr_setup.install(args.dir, size=args.model, force=args.force)
    print(f"target   {report['target']}")
    print(f"backend  {report['backend']}")
    print(f"model    {report['model']}")
    for row in report["checks"]:
        print(f"{'ok  ' if row['ok'] else 'miss'} {row['name']:<18} {row['detail']}")
    return 0 if report["ready"] else 1


def cmd_doctor(_: argparse.Namespace) -> int:
    from . import doctor

    for line in doctor.render():
        print(line)
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from .serve import serve

    return serve(args.host, args.port, args.web)


def main(argv: list[str] | None = None) -> int:
    from . import asr_setup

    asr_setup.bootstrap()
    parser = _build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "scan": cmd_scan,
        "run": cmd_run,
        "watch": cmd_watch,
        "transcript": cmd_transcript,
        "index": cmd_index,
        "search": cmd_search,
        "cards": cmd_cards,
        "quiz": cmd_quiz,
        "tui": cmd_tui,
        "ask": cmd_ask,
        "export": cmd_export,
        "publish": cmd_publish,
        "plugins": cmd_plugins,
        "keys": cmd_keys,
        "capture": cmd_capture,
        "graph": cmd_graph,
        "mcp": cmd_mcp,
        "doctor": cmd_doctor,
        "provision": cmd_provision,
        "serve": cmd_serve,
    }
    return handlers[args.command](args)
