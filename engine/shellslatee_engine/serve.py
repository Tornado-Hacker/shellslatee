"""Local HTTP API + static reader for the Shellslatee desktop shell.

Loopback-only by default. No third-party dependencies: the API is a thin,
read-mostly layer over the existing pipeline, and the browser UI is served
from ``web/dist`` when it has been built.
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from . import __version__, actions, assistant, cards, capture, embed, graph, plugins, publish, quiz, rag
from .pause import PAUSE_SIGNAL_NAME, RESUME_SIGNAL_NAME
from .indexdb import (
    IndexError_,
    _frontmatter,
    _split_sections,
    build as build_index,
    search as search_index,
)
from .media import MediaError, probe_duration
from .providers import PRESETS, ProviderError, resolve_provider
from .scanner import ScanError, scan
from .state import State
from .util import atomic_write, human_duration, pretty_name
from .vault import FRONTMATTER_RE, collect

DEFAULT_PORT = 8677
MEDIA_EXTS = {
    ".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v", ".mpg", ".mpeg", ".wmv", ".flv",
    ".mp3", ".m4a", ".wav", ".flac", ".ogg", ".opus", ".aac",
}
REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_DIST = REPO_ROOT / "web" / "dist"

PROGRESS_RE = re.compile(r"^\[(?P<index>\d+)/(?P<total>\d+)\]\s")
DONE_ITEM_RE = re.compile(r"^->\s+(?P<rel>.+?)\s+\((?P<dur>[^,]+),\s+gen\s+(?P<gen>\d+)\)")
FAILED_ITEM_RE = re.compile(r"^!!\s+(?P<rel>.+?)\s+—\s+(?P<err>.+)$")
SUMMARY_RE = re.compile(
    r"^done:\s+(?P<written>\d+)\s+written,\s+(?P<skipped>\d+)\s+skipped,\s+(?P<failed>\d+)\s+failed"
    r".*spent\s+\$(?P<usd>[\d.]+)"
)
PREFLIGHT_RE = re.compile(r"est\.\s+\$(?P<usd>[\d.]+)\s+on\s+(?P<target>.+)$")


def _json_bytes(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _resolve_dir(value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser()
    try:
        return path.resolve()
    except OSError:
        return None


def _safe_media(value: str | None) -> Path | None:
    path = _resolve_dir(value)
    if path is None or not path.is_file():
        return None
    if path.suffix.lower() not in MEDIA_EXTS:
        return None
    return path


def _media_url(path: Path | None) -> str | None:
    if path is None:
        return None
    return "/media?src=" + quote(path.as_posix(), safe="")


def _resolve_source(source_root: Path | None, source_rel: str) -> tuple[Path | None, str | None]:
    """Notes may store a relative path or an absolute ``file://`` URI."""
    if not source_rel:
        return None, None
    if source_rel.startswith("file://"):
        path = Path(unquote(urlparse(source_rel).path))
    else:
        candidate = Path(source_rel)
        path = candidate if candidate.is_absolute() else (source_root / candidate if source_root else None)
    if path is None:
        return None, source_rel
    display = source_rel
    if source_root is not None:
        try:
            display = path.resolve().relative_to(source_root.resolve()).as_posix()
        except (OSError, ValueError):
            display = path.name
    return path, display


def _lesson_payload(out_root: Path, rel: str, source_root: Path | None) -> dict | None:
    if not rel or ".." in Path(rel).parts:
        return None
    note_path = (out_root / rel).resolve()
    if not str(note_path).startswith(str(out_root.resolve())) or not note_path.is_file():
        return None
    text = note_path.read_text(encoding="utf-8", errors="replace")
    fields = _frontmatter(text)
    body = text[text.find("\n---", 3) + 4 :] if text.startswith("---") else text
    segments = [
        {"start": start, "heading": heading, "text": section_text}
        for heading, section_text, start in _split_sections(body)
        if start is not None
    ]
    source_rel = fields.get("source", "").strip().strip('"')
    video_path, video_rel = _resolve_source(source_root, source_rel)
    video = _media_url(video_path)
    return {
        "rel": rel,
        "title": fields.get("title", note_path.stem).strip('"'),
        "frontmatter": fields,
        "markdown": body,
        "segments": segments,
        "video": video,
        "video_rel": video_rel,
    }


def _note_file(out_root: Path, rel: str) -> Path | None:
    """Resolve a note path inside the vault, rejecting traversal or missing files."""
    if not rel or ".." in Path(rel).parts:
        return None
    root = out_root.resolve()
    candidate = (root / rel).resolve()
    if candidate == root or not str(candidate).startswith(str(root) + os.sep):
        return None
    return candidate if candidate.is_file() else None


def _vault_payload(out_root: Path, source_root: Path | None) -> dict:
    records, concepts = collect(out_root)
    lessons = []
    for record in records:
        note_path = out_root / record.lesson_rel
        fields = _frontmatter(note_path.read_text(encoding="utf-8", errors="replace"))
        source_rel = fields.get("source", "").strip().strip('"')
        video_path, video_rel = _resolve_source(source_root, source_rel)
        video = _media_url(video_path)
        lessons.append(
            {
                "rel": record.lesson_rel,
                "title": record.title,
                "module": record.module,
                "summary": record.summary,
                "duration": record.duration,
                "tags": record.tags,
                "concepts": record.concepts,
                "video": video,
                "video_rel": video_rel,
            }
        )
    readme = out_root / "README.md"
    title = out_root.name
    if readme.is_file():
        first = readme.read_text(encoding="utf-8", errors="replace").splitlines()[:1]
        if first and first[0].startswith("# "):
            title = first[0][2:].strip()
    return {
        "out": str(out_root),
        "source": str(source_root) if source_root else None,
        "title": title,
        "lessons": lessons,
        "concepts": [
            {
                "slug": slug,
                "name": payload["name"],
                "definition": payload["definition"],
                "definitions": payload.get("definitions", 0),
                "lessons": [record.lesson_rel for record in payload["lessons"]],
            }
            for slug, payload in sorted(concepts.items())
        ],
        "total_duration": sum(item["duration"] for item in lessons),
        "has_index": (out_root / ".shellslatee" / "vault.db").is_file(),
    }


def _key_status() -> dict:
    from .providers import ProviderError

    presets = []
    for name, provider in sorted(PRESETS.items()):
        ready = provider.name == "mock" or not provider.api_key_env
        detail = "no key needed" if ready else f"set {provider.api_key_env}"
        if not ready and provider.api_key_file:
            key_file = Path(provider.api_key_file).expanduser()
            if key_file.is_file() and key_file.read_text(encoding="utf-8").strip():
                ready, detail = True, f"key file {key_file}"
        if not ready and os.environ.get(provider.api_key_env or "", "").strip():
            ready, detail = True, f"{provider.api_key_env} (env)"
        presets.append(
            {
                "name": name,
                "base_url": provider.base_url,
                "default_model": provider.default_model,
                "ready": ready,
                "detail": detail,
            }
        )
    try:
        from .providers import resolve_provider

        resolve_provider("aikey")
        default_ready = True
    except ProviderError:
        default_ready = False
    return {"default": "aikey", "default_ready": default_ready, "presets": presets}


@dataclass
class Job:
    id: str
    command: list[str]
    source: str
    out: str
    status: str = "queued"
    paused: bool = False
    created: float = field(default_factory=time.time)
    returncode: int | None = None
    total: int = 0
    index: int = 0
    written: int = 0
    skipped: int = 0
    failed: int = 0
    usd: float = 0.0
    projection_usd: float | None = None
    target: str = ""
    log: list[str] = field(default_factory=list)
    items: list[dict] = field(default_factory=list)
    process: subprocess.Popen | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "id": self.id,
                "status": self.status,
                "paused": self.paused,
                "created": self.created,
                "returncode": self.returncode,
                "total": self.total,
                "index": self.index,
                "written": self.written,
                "skipped": self.skipped,
                "failed": self.failed,
                "usd": round(self.usd, 6),
                "projection_usd": self.projection_usd,
                "target": self.target,
                "source": self.source,
                "out": self.out,
                "items": list(self.items),
                "log": self.log[-400:],
            }

    def _absorb(self, line: str) -> None:
        with self._lock:
            self.log.append(line)
            if line.startswith("paused:"):
                self.paused = True
                if self.status == "running":
                    self.status = "paused"
                return
            if line.startswith("resumed"):
                self.paused = False
                if self.status == "paused":
                    self.status = "running"
                return
            match = PROGRESS_RE.match(line)
            if match:
                self.index = int(match.group("index"))
                self.total = int(match.group("total"))
                return
            match = DONE_ITEM_RE.match(line)
            if match:
                self.written += 1
                self.items.append(
                    {"rel": match.group("rel"), "status": "done", "detail": f"gen {match.group('gen')}"}
                )
                return
            match = FAILED_ITEM_RE.match(line)
            if match:
                self.failed += 1
                self.items.append(
                    {"rel": match.group("rel"), "status": "failed", "detail": match.group("err")[:300]}
                )
                return
            match = PREFLIGHT_RE.search(line)
            if match:
                self.projection_usd = float(match.group("usd"))
                self.target = match.group("target").strip()
                return
            match = SUMMARY_RE.search(line)
            if match:
                self.written = int(match.group("written"))
                self.skipped = int(match.group("skipped"))
                self.failed = int(match.group("failed"))
                self.usd = float(match.group("usd"))

    def stop(self) -> None:
        with self._lock:
            process = self.process
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()

    def _signal(self, name: str) -> bool:
        signum = getattr(signal, name, None)
        with self._lock:
            process = self.process
        if signum is None or process is None or process.poll() is not None:
            return False
        try:
            process.send_signal(signum)
        except OSError:
            return False
        return True

    def pause(self) -> bool:
        """Ask the child run to pause between items and provider retries."""
        with self._lock:
            if self.paused or self.status not in {"queued", "running"}:
                return False
        if not self._signal(PAUSE_SIGNAL_NAME):
            return False
        with self._lock:
            self.paused = True
            if self.status == "running":
                self.status = "paused"
            self.log.append("paused: operator pause requested")
        return True

    def resume(self) -> bool:
        with self._lock:
            if not self.paused:
                return False
        if not self._signal(RESUME_SIGNAL_NAME):
            return False
        with self._lock:
            self.paused = False
            if self.status == "paused":
                self.status = "running"
            self.log.append("resumed: operator resumed the run")
        return True


class JobRunner:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def start(self, source: Path, out_root: Path, flags: dict) -> Job:
        command = [sys.executable, "-m", "shellslatee_engine", "run", str(source), str(out_root)]
        mapping = {
            "provider": "--provider",
            "model": "--model",
            "transcriber": "--transcriber",
            "language": "--language",
            "course": "--course",
            "jobs": "--jobs",
            "template": "--template",
        }
        for key, flag in mapping.items():
            value = flags.get(key)
            if value not in (None, ""):
                command.extend([flag, str(value)])
        if flags.get("limit"):
            command.extend(["--limit", str(int(flags["limit"]))])
        if flags.get("force"):
            command.append("--force")
        if flags.get("estimate_only"):
            command.append("--estimate-only")

        job = Job(id=uuid.uuid4().hex[:12], command=command, source=str(source), out=str(out_root))
        with self._lock:
            self.jobs[job.id] = job
        threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return job

    def start_command(self, command: list[str], source: str = "", out: str = "") -> Job:
        job = Job(id=uuid.uuid4().hex[:12], command=command, source=source, out=out)
        with self._lock:
            self.jobs[job.id] = job
        threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return job

    def _run(self, job: Job) -> None:
        env = dict(os.environ)
        env.setdefault("PYTHONUNBUFFERED", "1")
        with job._lock:
            job.status = "running"
        try:
            process = subprocess.Popen(
                job.command,
                cwd=str(REPO_ROOT) if (REPO_ROOT / "shellslatee_engine").is_dir() else None,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                env=env,
            )
        except OSError as exc:
            with job._lock:
                job.status = "failed"
                job.log.append(f"spawn failed: {exc}")
            return
        with job._lock:
            job.process = process
        assert process.stderr is not None
        try:
            for raw in process.stderr:
                job._absorb(raw.rstrip("\n"))
        finally:
            process.stderr.close()
        code = process.wait()
        with job._lock:
            job.returncode = code
            if job.status != "stopped":
                job.status = "done" if code in (0, 1) else "failed"
            if job.failed and code == 1:
                job.status = "done"
        with job._lock:
            job.process = None

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def list(self) -> list[dict]:
        with self._lock:
            jobs = sorted(self.jobs.values(), key=lambda item: item.created, reverse=True)
        return [job.snapshot() for job in jobs]


RUNNER = JobRunner()


class Handler(BaseHTTPRequestHandler):
    server_version = f"shellslatee/{__version__}"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:  # keep the console clean
        if os.environ.get("SHELLSLATEE_SERVE_LOG"):
            super().log_message(fmt, *args)

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, payload: object) -> None:
        self._send(status, _json_bytes(payload), "application/json; charset=utf-8")

    def _error(self, status: int, message: str) -> None:
        self._json(status, {"error": message})

    def _query(self) -> dict[str, str]:
        parsed = urlparse(self.path)
        return {key: values[-1] for key, values in parse_qs(parsed.query, keep_blank_values=True).items()}

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path.startswith("/api/"):
                return self._api_get(path)
            if path == "/media":
                return self._media()
            if path == "/" or not path.startswith("/api"):
                return self._static(path)
            self._error(HTTPStatus.NOT_FOUND, "not found")
        except BrokenPipeError:
            return
        except Exception as exc:  # noqa: BLE001 — surface as JSON, never crash the server
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"{type(exc).__name__}: {exc}")

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/run":
                return self._api_run()
            if parsed.path == "/api/ask":
                return self._api_ask()
            if parsed.path == "/api/ask_course":
                return self._api_ask_course()
            if parsed.path == "/api/cards/build":
                return self._api_cards_build()
            if parsed.path == "/api/cards/review":
                return self._api_cards_review()
            if parsed.path == "/api/quiz/build":
                return self._api_quiz_build()
            if parsed.path == "/api/quiz/check":
                return self._api_quiz_check()
            if parsed.path == "/api/asr/provision":
                return self._api_asr_provision()
            if parsed.path == "/api/asr/apply":
                return self._api_asr_apply()
            if parsed.path == "/api/capture":
                return self._api_capture()
            if parsed.path == "/api/plugins":
                return self._api_plugins_toggle()
            if parsed.path == "/api/publish":
                return self._api_publish()
            if parsed.path == "/api/action":
                return self._api_action()
            if parsed.path == "/api/note/write":
                return self._api_note_write()
            if parsed.path.startswith("/api/jobs/") and parsed.path.endswith("/stop"):
                return self._api_stop(parsed.path)
            if parsed.path.startswith("/api/jobs/") and parsed.path.endswith("/pause"):
                return self._api_job_control(parsed.path, pause=True)
            if parsed.path.startswith("/api/jobs/") and parsed.path.endswith("/resume"):
                return self._api_job_control(parsed.path, pause=False)
            self._error(HTTPStatus.NOT_FOUND, "not found")
        except BrokenPipeError:
            return
        except Exception as exc:  # noqa: BLE001
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"{type(exc).__name__}: {exc}")

    # ---- API -----------------------------------------------------------

    def _api_get(self, path: str) -> None:
        query = self._query()
        if path == "/api/health":
            return self._json(
                HTTPStatus.OK,
                {"ok": True, "version": __version__, "jobs": len(RUNNER.list()), "web_built": (WEB_DIST / "index.html").is_file()},
            )
        if path == "/api/providers":
            return self._json(HTTPStatus.OK, _key_status())
        if path == "/api/doctor":
            from . import doctor

            rows = doctor.checks()
            return self._json(
                HTTPStatus.OK, {"checks": rows, "ready": doctor.ready(rows)}
            )
        if path == "/api/settings":
            out_root = _resolve_dir(query.get("out"))
            stored: dict = {}
            if out_root and (out_root / ".shellslatee" / "settings.json").is_file():
                try:
                    stored = json.loads((out_root / ".shellslatee" / "settings.json").read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    stored = {}
            return self._json(HTTPStatus.OK, {"stored": stored, **_key_status()})
        if path == "/api/scan":
            source = _resolve_dir(query.get("source"))
            if source is None:
                return self._error(HTTPStatus.BAD_REQUEST, "source is required")
            try:
                found = scan(source)
            except ScanError as exc:
                return self._error(HTTPStatus.BAD_REQUEST, str(exc))
            items = []
            durations: dict[str, float] = {}
            if query.get("durations") == "1":
                for item in found:
                    try:
                        durations[str(item.rel)] = round(probe_duration(item.path), 2)
                    except MediaError:
                        durations[str(item.rel)] = 0.0
            for item in found:
                items.append(
                    {
                        "rel": item.rel.as_posix(),
                        "kind": item.kind,
                        "bytes": item.size,
                        "subtitle": item.subtitle.as_posix() if item.subtitle else None,
                        "duration": durations.get(str(item.rel)),
                        "video": _media_url(item.path),
                    }
                )
            return self._json(HTTPStatus.OK, {"source": str(source), "count": len(items), "items": items})
        if path == "/api/vault":
            out_root = _resolve_dir(query.get("out"))
            if out_root is None or not out_root.is_dir():
                return self._error(HTTPStatus.BAD_REQUEST, "out folder is required")
            return self._json(HTTPStatus.OK, _vault_payload(out_root, _resolve_dir(query.get("source"))))
        if path == "/api/note":
            out_root = _resolve_dir(query.get("out"))
            if out_root is None:
                return self._error(HTTPStatus.BAD_REQUEST, "out folder is required")
            payload = _lesson_payload(out_root, query.get("rel", ""), _resolve_dir(query.get("source")))
            if payload is None:
                return self._error(HTTPStatus.NOT_FOUND, "note not found")
            return self._json(HTTPStatus.OK, payload)
        if path == "/api/search":
            out_root = _resolve_dir(query.get("out"))
            if out_root is None:
                return self._error(HTTPStatus.BAD_REQUEST, "out folder is required")
            try:
                limit = int(query.get("limit", "12"))
                mode = (query.get("mode", "fts") or "fts").lower()
                if mode == "hybrid":
                    rows = embed.hybrid_search(out_root, query.get("q", ""), limit)
                elif mode == "semantic":
                    rows = embed.semantic(out_root, query.get("q", ""), limit)
                else:
                    rows = search_index(out_root, query.get("q", ""), limit)
            except (IndexError_, ValueError) as exc:
                return self._error(HTTPStatus.BAD_REQUEST, str(exc))
            return self._json(HTTPStatus.OK, {"rows": rows, "mode": mode})
        if path == "/api/cards":
            out_root = _resolve_dir(query.get("out"))
            if out_root is None:
                return self._error(HTTPStatus.BAD_REQUEST, "out folder is required")
            try:
                limit = int(query.get("limit", "20"))
            except ValueError:
                limit = 20
            return self._json(HTTPStatus.OK, cards.due_cards(out_root, limit))
        if path == "/api/cards/drills":
            out_root = _resolve_dir(query.get("out"))
            if out_root is None:
                return self._error(HTTPStatus.BAD_REQUEST, "out folder is required")
            try:
                limit = int(query.get("limit", "20"))
            except ValueError:
                limit = 20
            return self._json(HTTPStatus.OK, cards.drills(out_root, limit))
        if path == "/api/quiz":
            out_root = _resolve_dir(query.get("out"))
            if out_root is None:
                return self._error(HTTPStatus.BAD_REQUEST, "out folder is required")
            try:
                limit = int(query.get("limit", "20"))
            except ValueError:
                limit = 20
            kind = query.get("kind") or None
            return self._json(
                HTTPStatus.OK,
                {"stats": quiz.stats(out_root), "items": quiz.items(out_root, limit, kind)},
            )
        if path == "/api/graph":
            out_root = _resolve_dir(query.get("out"))
            if out_root is None or not out_root.is_dir():
                return self._error(HTTPStatus.BAD_REQUEST, "out folder is required")
            semantic = (query.get("semantic", "0") or "0") not in {"0", "", "false", "no"}
            return self._json(HTTPStatus.OK, graph.build(out_root, semantic=semantic))
        if path == "/api/plugins":
            out_root = _resolve_dir(query.get("out"))
            if out_root is None:
                return self._error(HTTPStatus.BAD_REQUEST, "out folder is required")
            return self._json(HTTPStatus.OK, {"plugins": plugins.list_plugins(out_root)})
        if path == "/api/asr/status":
            from . import asr_setup

            report = asr_setup.inspect()
            from . import doctor

            return self._json(
                HTTPStatus.OK,
                {
                    **report,
                    "checks": [row for row in doctor.checks() if row["name"] in doctor.REQUIRED],
                    "ready": doctor.ready(),
                    "models_available": list(asr_setup.MODEL_SIZES),
                },
            )
        if path == "/api/jobs":
            return self._json(HTTPStatus.OK, {"jobs": RUNNER.list()})
        if path.startswith("/api/jobs/"):
            job = RUNNER.get(path.rsplit("/", 1)[-1])
            if job is None:
                return self._error(HTTPStatus.NOT_FOUND, "job not found")
            return self._json(HTTPStatus.OK, job.snapshot())
        self._error(HTTPStatus.NOT_FOUND, "not found")

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except ValueError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _api_asr_provision(self) -> None:
        from . import asr_setup

        payload = self._read_body()
        size = str(payload.get("model") or "tiny.en")
        if size not in asr_setup.MODEL_SIZES:
            return self._error(HTTPStatus.BAD_REQUEST, f"unknown model {size!r}")
        target = payload.get("dir")
        command = [sys.executable, "-m", "shellslatee_engine", "provision", "--model", size]
        if target:
            command.extend(["--dir", str(target)])
        if payload.get("force"):
            command.append("--force")
        job = RUNNER.start_command(command, source="asr", out=str(asr_setup.default_dir()))
        self._json(HTTPStatus.ACCEPTED, job.snapshot())

    def _api_asr_apply(self) -> None:
        from . import asr_setup, doctor

        values = asr_setup.apply_env()
        self._json(
            HTTPStatus.OK,
            {
                "env": values,
                "checks": [row for row in doctor.checks() if row["name"] in doctor.REQUIRED],
                "ready": doctor.ready(),
            },
        )

    def _api_run(self) -> None:
        payload = self._read_body()
        source = _resolve_dir(payload.get("source"))
        out_root = _resolve_dir(payload.get("out"))
        if source is None or not source.is_dir():
            return self._error(HTTPStatus.BAD_REQUEST, "source folder not found")
        if out_root is None:
            return self._error(HTTPStatus.BAD_REQUEST, "out folder is required")
        if out_root == source:
            return self._error(HTTPStatus.BAD_REQUEST, "output folder must differ from the source folder")
        job = RUNNER.start(source, out_root, payload)
        self._json(HTTPStatus.ACCEPTED, job.snapshot())

    def _api_stop(self, path: str) -> None:
        job_id = path.split("/")[3] if len(path.split("/")) > 3 else ""
        job = RUNNER.get(job_id)
        if job is None:
            return self._error(HTTPStatus.NOT_FOUND, "job not found")
        with job._lock:
            job.status = "stopped"
        job.stop()
        self._json(HTTPStatus.OK, job.snapshot())

    def _api_job_control(self, path: str, *, pause: bool) -> None:
        job_id = path.split("/")[3] if len(path.split("/")) > 3 else ""
        job = RUNNER.get(job_id)
        if job is None:
            return self._error(HTTPStatus.NOT_FOUND, "job not found")
        changed = job.pause() if pause else job.resume()
        if not changed:
            state = "paused" if job.paused else job.status
            return self._error(
                HTTPStatus.CONFLICT,
                f"cannot {'pause' if pause else 'resume'} a job that is {state}",
            )
        self._json(HTTPStatus.OK, job.snapshot())

    # ---- assistant -----------------------------------------------------

    def _api_ask(self) -> None:
        payload = self._read_body()
        out_root = _resolve_dir(payload.get("out"))
        rel = str(payload.get("rel", ""))
        mode = str(payload.get("mode", "ask")).lower()
        question = str(payload.get("question", "")).strip()
        if out_root is None:
            return self._error(HTTPStatus.BAD_REQUEST, "out folder is required")
        note = _lesson_payload(out_root, rel, _resolve_dir(payload.get("source")))
        if note is None:
            return self._error(HTTPStatus.NOT_FOUND, "note not found")
        if not question:
            return self._error(HTTPStatus.BAD_REQUEST, "question is required")
        try:
            provider, model, api_key = resolve_provider(
                str(payload.get("provider") or "aikey"),
                str(payload.get("model") or "") or None,
            )
        except ProviderError as exc:
            return self._error(HTTPStatus.BAD_REQUEST, str(exc))

        try:
            if mode == "edit":
                result = assistant.edit(
                    provider,
                    model,
                    api_key,
                    note_title=note["title"],
                    note_markdown=note["markdown"],
                    instruction=question,
                )
            else:
                history = payload.get("history")
                if not isinstance(history, list):
                    history = []
                result = assistant.ask(
                    provider,
                    model,
                    api_key,
                    note_title=note["title"],
                    note_markdown=note["markdown"],
                    question=question,
                    history=history,
                )
        except ProviderError as exc:
            return self._error(HTTPStatus.BAD_GATEWAY, str(exc))

        self._json(
            HTTPStatus.OK,
            {
                "mode": "edit" if mode == "edit" else "ask",
                "answer": result.text,
                "tokens": {"in": result.tokens_in, "out": result.tokens_out},
                "provider": provider.name,
                "model": model,
            },
        )

    def _api_ask_course(self) -> None:
        payload = self._read_body()
        out_root = _resolve_dir(payload.get("out"))
        question = str(payload.get("question", "")).strip()
        if out_root is None or not out_root.is_dir():
            return self._error(HTTPStatus.BAD_REQUEST, "out folder is required")
        if not question:
            return self._error(HTTPStatus.BAD_REQUEST, "question is required")
        try:
            provider, model, api_key = resolve_provider(
                str(payload.get("provider") or "aikey"),
                str(payload.get("model") or "") or None,
            )
        except ProviderError as exc:
            return self._error(HTTPStatus.BAD_REQUEST, str(exc))
        try:
            result = rag.answer(provider, model, api_key, out_root=out_root, question=question)
        except ProviderError as exc:
            return self._error(HTTPStatus.BAD_GATEWAY, str(exc))
        self._json(
            HTTPStatus.OK,
            {
                "answer": result.answer,
                "citations": [citation.__dict__ for citation in result.citations],
                "tokens": {"in": result.tokens_in, "out": result.tokens_out},
                "provider": provider.name,
                "model": model,
            },
        )

    def _api_cards_build(self) -> None:
        payload = self._read_body()
        out_root = _resolve_dir(payload.get("out"))
        if out_root is None or not out_root.is_dir():
            return self._error(HTTPStatus.BAD_REQUEST, "out folder is required")
        self._json(HTTPStatus.OK, cards.build(out_root))

    def _api_cards_review(self) -> None:
        payload = self._read_body()
        out_root = _resolve_dir(payload.get("out"))
        card_id = str(payload.get("id", ""))
        if out_root is None or not out_root.is_dir():
            return self._error(HTTPStatus.BAD_REQUEST, "out folder is required")
        try:
            grade = int(payload.get("grade"))
        except (TypeError, ValueError):
            return self._error(HTTPStatus.BAD_REQUEST, "grade must be 1-4")
        result = cards.review(out_root, card_id, grade)
        if result is None:
            return self._error(HTTPStatus.NOT_FOUND, "card not found")
        self._json(HTTPStatus.OK, result)

    def _api_quiz_build(self) -> None:
        payload = self._read_body()
        out_root = _resolve_dir(payload.get("out"))
        if out_root is None or not out_root.is_dir():
            return self._error(HTTPStatus.BAD_REQUEST, "out folder is required")
        focus = payload.get("focus")
        if isinstance(focus, str):
            focus = [focus]
        if not isinstance(focus, list):
            focus = None
        try:
            limit = int(payload.get("limit", 0) or 0)
        except (TypeError, ValueError):
            limit = 0
        result = quiz.build(out_root, [str(item) for item in (focus or [])] or None, limit)
        result["stats"] = quiz.stats(out_root)
        self._json(HTTPStatus.OK, result)

    def _api_quiz_check(self) -> None:
        payload = self._read_body()
        out_root = _resolve_dir(payload.get("out"))
        quiz_id = str(payload.get("id", ""))
        if out_root is None or not out_root.is_dir():
            return self._error(HTTPStatus.BAD_REQUEST, "out folder is required")
        if not quiz_id:
            return self._error(HTTPStatus.BAD_REQUEST, "id is required")
        result = quiz.check(out_root, quiz_id, payload.get("response", ""))
        if result is None:
            return self._error(HTTPStatus.NOT_FOUND, "quiz item not found")
        self._json(HTTPStatus.OK, result)

    def _api_action(self) -> None:
        payload = self._read_body()
        out_root = _resolve_dir(payload.get("out"))
        rel = str(payload.get("rel", ""))
        text = str(payload.get("text", ""))
        action = str(payload.get("action", ""))
        if out_root is None or not out_root.is_dir():
            return self._error(HTTPStatus.BAD_REQUEST, "out folder is required")
        if action == "link":
            try:
                result = actions.run(
                    None,
                    "",
                    "",
                    out_root=out_root,
                    rel=rel,
                    selection=text,
                    action=action,
                    concept=str(payload.get("concept") or "") or None,
                )
            except actions.ActionError as exc:
                return self._error(HTTPStatus.BAD_REQUEST, str(exc))
            result["provider"] = "none"
            result["model"] = ""
            return self._json(HTTPStatus.OK, result)
        try:
            provider, model, api_key = resolve_provider(
                str(payload.get("provider") or "aikey"),
                str(payload.get("model") or "") or None,
            )
        except ProviderError as exc:
            return self._error(HTTPStatus.BAD_REQUEST, str(exc))
        try:
            result = actions.run(
                provider,
                model,
                api_key,
                out_root=out_root,
                rel=rel,
                selection=text,
                action=action,
            )
        except actions.ActionError as exc:
            return self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except ProviderError as exc:
            return self._error(HTTPStatus.BAD_GATEWAY, str(exc))
        result["provider"] = provider.name
        result["model"] = model
        self._json(HTTPStatus.OK, result)

    def _api_capture(self) -> None:
        payload = self._read_body()
        out_root = _resolve_dir(payload.get("out"))
        text = str(payload.get("text", "")).strip()
        if out_root is None or not out_root.is_dir():
            return self._error(HTTPStatus.BAD_REQUEST, "out folder is required")
        if not text:
            return self._error(HTTPStatus.BAD_REQUEST, "text is required")
        try:
            result = capture.capture(out_root, text, payload.get("tag") or None)
        except ValueError as exc:
            return self._error(HTTPStatus.BAD_REQUEST, str(exc))
        self._json(HTTPStatus.OK, result)

    def _api_plugins_toggle(self) -> None:
        payload = self._read_body()
        out_root = _resolve_dir(payload.get("out"))
        name = payload.get("name")
        if out_root is None or not out_root.is_dir():
            return self._error(HTTPStatus.BAD_REQUEST, "out folder is required")
        if not isinstance(name, str) or not name.strip():
            return self._error(HTTPStatus.BAD_REQUEST, "name is required")
        enabled = bool(payload.get("enabled", True))
        config = payload.get("config") if isinstance(payload.get("config"), dict) else None
        try:
            result = plugins.set_enabled(out_root, name, enabled, config)
        except plugins.PluginError as exc:
            return self._error(HTTPStatus.BAD_REQUEST, str(exc))
        self._json(HTTPStatus.OK, result)

    def _api_publish(self) -> None:
        payload = self._read_body()
        out_root = _resolve_dir(payload.get("out"))
        if out_root is None or not out_root.is_dir():
            return self._error(HTTPStatus.BAD_REQUEST, "out folder is required")
        target = _resolve_dir(payload.get("target")) if payload.get("target") else None
        base_url = payload.get("base_url") if isinstance(payload.get("base_url"), str) else None
        try:
            result = publish.build(
                out_root,
                target=target,
                base_url=base_url,
                zip_bundle=bool(payload.get("zip")),
            )
        except (OSError, plugins.PluginError) as exc:
            return self._error(HTTPStatus.BAD_REQUEST, str(exc))
        self._json(HTTPStatus.OK, result)

    def _api_note_write(self) -> None:
        payload = self._read_body()
        out_root = _resolve_dir(payload.get("out"))
        rel = str(payload.get("rel", ""))
        markdown = payload.get("markdown")
        if out_root is None or not out_root.is_dir():
            return self._error(HTTPStatus.BAD_REQUEST, "out folder is required")
        if not isinstance(markdown, str):
            return self._error(HTTPStatus.BAD_REQUEST, "markdown is required")
        if len(markdown) > 2_000_000:
            return self._error(HTTPStatus.BAD_REQUEST, "note too large")
        note_path = _note_file(out_root, rel)
        if note_path is None:
            return self._error(HTTPStatus.NOT_FOUND, "note not found")

        existing = note_path.read_text(encoding="utf-8", errors="replace")
        match = FRONTMATTER_RE.match(existing)
        front = existing[: match.end()] if match else ""
        body = markdown if markdown.endswith("\n") else markdown + "\n"
        atomic_write(note_path, front + body)

        warnings: list[str] = []
        try:
            if (out_root / ".shellslatee" / "vault.db").is_file():
                build_index(out_root)
        except Exception as exc:  # noqa: BLE001 — index refresh is best-effort
            warnings.append(f"index not refreshed: {exc}")

        self._json(
            HTTPStatus.OK,
            {"ok": True, "rel": rel, "bytes": len((front + body).encode("utf-8")), "warnings": warnings},
        )

    # ---- media ---------------------------------------------------------

    def _media(self) -> None:
        path = _safe_media(self._query().get("src"))
        if path is None:
            return self._error(HTTPStatus.NOT_FOUND, "media not found")
        size = path.stat().st_size
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        range_header = self.headers.get("Range", "")
        start, end = 0, size - 1
        status = HTTPStatus.OK
        if range_header.startswith("bytes="):
            spec = range_header[6:].split(",")[0].strip()
            first, _, last = spec.partition("-")
            try:
                if first:
                    start = int(first)
                    end = int(last) if last else size - 1
                elif last:
                    start = max(0, size - int(last))
            except ValueError:
                return self._error(HTTPStatus.BAD_REQUEST, "bad range")
            start = min(max(0, start), size - 1)
            end = min(max(start, end), size - 1)
            status = HTTPStatus.PARTIAL_CONTENT
        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if status == HTTPStatus.PARTIAL_CONTENT:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if self.command == "HEAD":
            return
        with path.open("rb") as handle:
            handle.seek(start)
            remaining = length
            while remaining > 0:
                chunk = handle.read(min(512 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    # ---- static --------------------------------------------------------

    def _static(self, path: str) -> None:
        if not WEB_DIST.is_dir():
            return self._json(
                HTTPStatus.OK,
                {
                    "service": "shellslatee",
                    "version": __version__,
                    "web": "not built",
                    "hint": "cd web && npm install && npm run build",
                    "api": ["/api/health", "/api/doctor", "/api/asr/status", "/api/providers", "/api/scan", "/api/vault", "/api/note", "/api/search", "/api/jobs"],
                },
            )
        rel = unquote(path).lstrip("/") or "index.html"
        candidate = (WEB_DIST / rel).resolve()
        if not str(candidate).startswith(str(WEB_DIST.resolve())):
            return self._error(HTTPStatus.NOT_FOUND, "not found")
        if candidate.is_dir():
            candidate = candidate / "index.html"
        if not candidate.is_file():
            candidate = WEB_DIST / "index.html"
        body = candidate.read_bytes()
        ctype = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in {"application/javascript", "application/json"}:
            ctype += "; charset=utf-8"
        self._send(HTTPStatus.OK, body, ctype)


def serve(host: str, port: int, web: Path | None = None) -> int:
    global WEB_DIST
    from . import asr_setup

    asr_setup.bootstrap()
    if web is not None:
        WEB_DIST = web.expanduser().resolve()
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    bound_port = httpd.server_address[1]
    if not (WEB_DIST / "index.html").is_file():
        print(f"shellslatee serve: web UI not built at {WEB_DIST} — API only", file=sys.stderr)
    print(f"shellslatee serve: http://{host}:{bound_port}", file=sys.stderr, flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("shellslatee serve: stopped", file=sys.stderr)
    finally:
        httpd.server_close()
    return 0
