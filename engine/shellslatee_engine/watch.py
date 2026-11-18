"""Polling watch mode.

No third-party watchers: a cheap fingerprint of the source tree (relative path,
mtime, size) is compared each tick. When it changes, the normal run path is
invoked, which already skips cached items, so a fresh drop only processes the
new or changed files.
"""

from __future__ import annotations

from pathlib import Path


def fingerprint(root: Path, out_root: Path | None = None) -> tuple[tuple[str, int, int], ...]:
    root = root.expanduser().resolve()
    excluded = out_root.expanduser().resolve() if out_root is not None else None
    items: list[tuple[str, int, int]] = []
    if not root.is_dir():
        return tuple()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part.startswith(".") for part in relative.parts):
            continue
        if excluded is not None:
            try:
                path.resolve().relative_to(excluded)
            except ValueError:
                pass
            else:
                continue
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        items.append((relative.as_posix(), int(stat.st_mtime_ns), stat.st_size))
    return tuple(items)
