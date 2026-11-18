"""Publishing: turn a vault into a deployable, self-contained study bundle.

Reuses the static site renderer, then adds a machine-readable manifest, a
``robots.txt``, and an optional zip so the bundle can be dropped on any static
host (GitHub Pages, Netlify, an S3 bucket, a USB stick). No server, no accounts,
no third-party service: the publish step produces files and nothing else.
"""

from __future__ import annotations

import html
import json
import shutil
from pathlib import Path

from .export import export_site
from .util import atomic_write, utc_now
from .vault import collect

MANIFEST_NAME = "shellslatee.json"
DEFAULT_TARGET = "publish"


def _course_title(out_root: Path) -> str:
    readme = out_root / "README.md"
    if readme.is_file():
        first = readme.read_text(encoding="utf-8", errors="replace").splitlines()[:1]
        if first and first[0].startswith("# "):
            return first[0][2:].strip()
    return out_root.name.replace("-", " ").replace("_", " ").strip().title() or "Shellslatee course"


def _landing(title: str, lessons: int, has_index: bool) -> str:
    body = (
        "<h1>" + html.escape(title) + "</h1>"
        f'<p class="muted">{lessons} lesson(s) · published with Shellslatee</p>'
    )
    if has_index:
        body += '<p><a href="site/index.html">Open the study site →</a></p>'
    return body


def build(
    out_root: Path,
    *,
    target: Path | None = None,
    base_url: str | None = None,
    zip_bundle: bool = False,
) -> dict:
    """Render the site into ``TARGET/site`` and write bundle metadata.

    Returns a summary: ``site``, ``manifest``, ``lessons``, ``base_url`` and,
    when requested, ``archive``.
    """
    out_root = out_root.resolve()
    if not out_root.is_dir():
        raise FileNotFoundError(f"vault folder not found: {out_root}")

    records, concepts = collect(out_root)
    target = (target or (out_root / DEFAULT_TARGET)).resolve()
    site = target / "site"
    site.mkdir(parents=True, exist_ok=True)

    lessons = export_site(out_root, site)
    title = _course_title(out_root)
    base = (base_url or "").rstrip("/")

    if base:
        for path in site.rglob("*.html"):
            text = path.read_text(encoding="utf-8", errors="replace")
            if '<base href=' in text:
                continue
            relative = path.relative_to(site).as_posix()
            href = f"{base}/{'' if relative == 'index.html' else relative}"
            if path.name == "index.html":
                href = f"{base}/"
            injected = text.replace(
                "<head>",
                f'<head><link rel="canonical" href="{html.escape(href, quote=True)}">',
                1,
            )
            path.write_text(injected, encoding="utf-8")

    manifest = {
        "generator": "shellslatee",
        "version": 1,
        "title": title,
        "generated": utc_now(),
        "lessons": lessons,
        "concepts": len(concepts),
        "base_url": base or None,
        "site": "site/index.html",
        "format": "static-html",
    }
    manifest_path = target / MANIFEST_NAME
    atomic_write(manifest_path, json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    atomic_write(
        target / "robots.txt",
        "User-agent: *\nAllow: /\n",
    )

    result = {
        "site": str(site),
        "manifest": str(manifest_path),
        "lessons": lessons,
        "base_url": base or None,
    }

    if zip_bundle:
        archive_base = target / "shellslatee-site"
        archive = shutil.make_archive(str(archive_base), "zip", root_dir=str(site))
        result["archive"] = archive

    return result
