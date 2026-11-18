"""Terminal UI over the ``shellslatee run --json`` NDJSON stream.

The stream is the contract: ``start``, ``preflight``, ``job``, ``paused``,
``resumed``, ``rate_limit``, and ``summary`` events. This module reduces those
events into a small state object and draws a progress view — no curses, no
third-party dependency, and the human log still lands on stderr so it can be
scrolled after the run.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

BAR_WIDTH = 28
LOG_TAIL = 6


@dataclass
class Progress:
    total: int = 0
    seconds: float = 0.0
    provider: str = ""
    model: str = ""
    target: str = ""
    projection_usd: float | None = None
    spent_usd: float = 0.0
    index: int = 0
    running: set[str] = field(default_factory=set)
    done: int = 0
    skipped: int = 0
    failed: int = 0
    paused: bool = False
    rate_limited: bool = False
    last: str = ""
    summary: dict | None = None

    @property
    def processed(self) -> int:
        return self.done + self.skipped + self.failed


def parse_event(line: str) -> dict | None:
    line = line.strip()
    if not line or not line.startswith("{"):
        return None
    try:
        payload = json.loads(line)
    except ValueError:
        return None
    return payload if isinstance(payload, dict) and "event" in payload else None


def apply(state: Progress, event: dict) -> Progress:
    kind = str(event.get("event", ""))
    if kind == "start":
        state.total = int(event.get("total", state.total) or 0)
        state.seconds = float(event.get("seconds", state.seconds) or 0.0)
        state.provider = str(event.get("provider", state.provider) or "")
        state.model = str(event.get("model", state.model) or "")
    elif kind == "preflight":
        state.target = str(event.get("target", state.target) or "")
        if "usd" in event:
            try:
                state.projection_usd = float(event["usd"])
            except (TypeError, ValueError):
                pass
    elif kind == "job":
        rel = str(event.get("rel", ""))
        status = str(event.get("status", ""))
        state.last = rel
        if status == "running":
            state.running.add(rel)
        else:
            state.running.discard(rel)
        if status == "done":
            state.done += 1
        elif status == "skip":
            state.skipped += 1
        elif status == "failed":
            state.failed += 1
        try:
            state.spent_usd += float(event.get("usd", 0) or 0)
        except (TypeError, ValueError):
            pass
        if "index" in event:
            try:
                state.index = max(state.index, int(event["index"]))
            except (TypeError, ValueError):
                pass
    elif kind == "paused":
        state.paused = True
    elif kind == "resumed":
        state.paused = False
    elif kind == "rate_limit":
        state.rate_limited = True
    elif kind == "summary":
        state.summary = dict(event)
        state.done = int(event.get("written", state.done) or state.done)
        state.skipped = int(event.get("skipped", state.skipped) or state.skipped)
        state.failed = int(event.get("failed", state.failed) or state.failed)
    return state


def _bar(processed: int, total: int) -> str:
    if total <= 0:
        return "-" * BAR_WIDTH
    filled = round(BAR_WIDTH * min(processed, total) / total)
    return "#" * filled + "-" * (BAR_WIDTH - filled)


def _duration(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def render(state: Progress, color: bool = False, width: int = 72) -> str:
    bar = _bar(state.processed, state.total)
    count = f"{state.processed}/{state.total}" if state.total else "?"
    line = f"[{bar}] {count}"
    lines = [line]
    stats = f"{state.done} done · {state.skipped} skipped · {state.failed} failed"
    if state.seconds:
        stats += f" · {_duration(state.seconds)} of video"
    lines.append(stats)
    money = f"spent ${state.spent_usd:.4f}"
    if state.projection_usd is not None:
        money += f" of ~${state.projection_usd:.2f} projected"
    lines.append(money)
    if state.target:
        lines.append(f"model: {state.target}")
    flags: list[str] = []
    if state.paused:
        flags.append("PAUSED (SIGUSR2 resumes)")
    if state.rate_limited:
        flags.append("rate limited — backing off")
    if flags:
        lines.append(" · ".join(flags))
    if state.running:
        lines.append("running: " + ", ".join(sorted(state.running)))
    elif state.last:
        lines.append("last: " + state.last)
    if state.summary is not None:
        summary = state.summary
        lines.append(
            f"done: {summary.get('written', 0)} written · "
            f"{summary.get('notes', 0)} note(s) · {summary.get('concepts', 0)} concept(s)"
        )
    if color:
        lines = [f"\x1b[1m{lines[0]}\x1b[0m", *lines[1:]]
    return "\n".join(line[:width] for line in lines)


def run(source: Path, out: Path, extra: list[str] | None = None, stream_in=None, stream_out=None) -> int:
    """Spawn ``shellslatee run --json``, reduce its events, draw the view."""
    sink = stream_out or sys.stdout
    color = bool(getattr(sink, "isatty", lambda: False)()) and os.environ.get("NO_COLOR") is None
    command = [
        sys.executable,
        "-m",
        "shellslatee",
        "run",
        str(source),
        str(out),
        "--json",
        *(extra or []),
    ]
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    state = Progress()
    log: list[str] = []

    def drain_stderr() -> None:
        assert process.stderr is not None
        for line in process.stderr:
            text = line.rstrip()
            if not text:
                continue
            log.append(text)
            del log[:-LOG_TAIL]

    reader = threading.Thread(target=drain_stderr, daemon=True)
    reader.start()

    def draw() -> None:
        if color:
            sink.write("\x1b[2J\x1b[H")
        sink.write(render(state, color) + "\n")
        if color and log:
            sink.write("\x1b[2m" + "\n".join(log) + "\x1b[0m\n")
        sink.flush()

    try:
        assert process.stdout is not None
        for line in process.stdout:
            event = parse_event(line)
            if event is None:
                continue
            apply(state, event)
            draw()
        returncode = process.wait()
    except KeyboardInterrupt:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        return 130
    finally:
        reader.join(timeout=2)
    if state.summary is None:
        draw()
    return returncode
