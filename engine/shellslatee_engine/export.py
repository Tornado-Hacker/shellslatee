"""Exports: a static HTML site and a Joplin-ready Markdown tree.

No third-party renderer: a small Markdown subset covers what Shellslatee emits
(headings, lists, quotes, code fences, tables of links, emphasis, inline code).
The site is self-contained — one stylesheet inline, relative links — so it can
be opened from disk or dropped on any static host.
"""

from __future__ import annotations

import csv
import html
import re
import shutil
from pathlib import Path

from .util import fmt_ts
from .vault import collect

SKIP_PARTS = {".shellslatee", "_inbox", "node_modules"}

STYLE = """
:root{color-scheme:dark light}
*{box-sizing:border-box}
body{margin:0;font:16px/1.6 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
  background:#0e1116;color:#e6e9ef}
a{color:#6fd3c7;text-decoration:none}
a:hover{text-decoration:underline}
header{border-bottom:1px solid #232a36;padding:14px 22px;display:flex;gap:14px;align-items:center}
header .brand{font-weight:700;letter-spacing:.02em}
main{max-width:820px;margin:0 auto;padding:26px 22px 80px}
h1,h2,h3{line-height:1.25;margin:1.4em 0 .5em}
h1{font-size:26px}h2{font-size:20px}h3{font-size:17px}
p{margin:.7em 0}
blockquote{margin:1em 0;padding:.4em 14px;border-left:3px solid #2f6f68;color:#b7c0ce;background:#121722}
pre{background:#0b0f14;border:1px solid #232a36;border-radius:10px;padding:12px;overflow:auto}
code{background:#161c26;padding:1px 5px;border-radius:5px;font-size:.92em}
pre code{background:none;padding:0}
ul,ol{padding-left:24px}
li{margin:.25em 0}
img{max-width:100%}
.muted{color:#8b95a5;font-size:13px}
ul.tree{list-style:none;padding:0}
ul.tree li{margin:2px 0}
ul.tree .module{margin-top:16px;color:#8b95a5;font-size:12px;text-transform:uppercase;letter-spacing:.08em}
"""


def _iter_markdown(out_root: Path) -> list[Path]:
    found: list[Path] = []
    for path in sorted(out_root.rglob("*.md")):
        relative = path.relative_to(out_root)
        if any(part in SKIP_PARTS for part in relative.parts):
            continue
        if relative.as_posix() == "README.md":
            continue
        found.append(path)
    return found


def _strip_frontmatter(text: str) -> str:
    if not text.startswith("---"):
        return text
    end = text.find("\n---", 3)
    return text[end + 4 :] if end != -1 else text


def _inline(text: str) -> str:
    slots: list[str] = []

    def stash(value: str) -> str:
        slots.append(value)
        return f"\x00{len(slots) - 1}\x00"

    text = re.sub(r"`([^`]+)`", lambda m: stash(f"<code>{html.escape(m.group(1))}</code>"), text)
    text = html.escape(text)
    text = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        lambda m: f'<a href="{html.escape(m.group(2), quote=True)}">{m.group(1)}</a>',
        text,
    )
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", text)
    for index, slot in enumerate(slots):
        text = text.replace(f"\x00{index}\x00", slot)
    return text


def markdown_to_html(markdown: str) -> str:
    lines = _strip_frontmatter(markdown).splitlines()
    blocks: list[str] = []
    paragraph: list[str] = []
    list_kind: str | None = None
    in_code = False
    code: list[str] = []

    def close_paragraph() -> None:
        if paragraph:
            blocks.append(f"<p>{_inline(' '.join(paragraph))}</p>")
            paragraph.clear()

    def close_list() -> None:
        nonlocal list_kind
        if list_kind:
            blocks.append(f"</{list_kind}>")
            list_kind = None

    def open_list(kind: str) -> None:
        nonlocal list_kind
        if list_kind != kind:
            close_list()
            blocks.append(f"<{kind}>")
            list_kind = kind

    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()
        if stripped.startswith("```"):
            if in_code:
                blocks.append(f"<pre><code>{html.escape(chr(10).join(code))}</code></pre>")
                code.clear()
                in_code = False
            else:
                close_paragraph()
                close_list()
                in_code = True
            continue
        if in_code:
            code.append(raw)
            continue
        if stripped.startswith("<!-- shellslatee:"):
            continue
        if not stripped:
            close_paragraph()
            close_list()
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            close_paragraph()
            close_list()
            level = len(heading.group(1))
            blocks.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            continue
        if stripped.startswith(">"):
            close_paragraph()
            close_list()
            blocks.append(f"<blockquote>{_inline(stripped.lstrip('> ').strip())}</blockquote>")
            continue
        bullet = re.match(r"^[-*]\s+(.*)$", stripped)
        if bullet:
            close_paragraph()
            open_list("ul")
            blocks.append(f"<li>{_inline(bullet.group(1))}</li>")
            continue
        numbered = re.match(r"^\d+\.\s+(.*)$", stripped)
        if numbered:
            close_paragraph()
            open_list("ol")
            blocks.append(f"<li>{_inline(numbered.group(1))}</li>")
            continue
        if list_kind:
            close_paragraph()
            blocks.append(f"<li>{_inline(stripped)}</li>")
            continue
        if re.match(r"^(-{3,}|\*{3,})$", stripped):
            close_paragraph()
            blocks.append("<hr />")
            continue
        paragraph.append(stripped)

    if in_code and code:
        blocks.append(f"<pre><code>{html.escape(chr(10).join(code))}</code></pre>")
    close_paragraph()
    close_list()
    return "\n".join(blocks)


def _page(title: str, body: str, home: str) -> str:
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{html.escape(title)}</title><style>{STYLE}</style></head><body>"
        f'<header><a class="brand" href="{home}">Shellslatee</a>'
        '<span class="muted">static study site</span></header>'
        f"<main>{body}</main></body></html>"
    )


def _relative_home(relative: Path) -> str:
    depth = len(relative.parts) - 1
    return "../" * depth + "index.html"


def export_joplin(out_root: Path, target: Path) -> int:
    """Copy the Markdown vault into a Joplin-importable folder tree."""
    target.mkdir(parents=True, exist_ok=True)
    count = 0
    for path in sorted(out_root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(out_root)
        if any(part in SKIP_PARTS for part in relative.parts):
            continue
        if path.suffix not in {".md", ".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            continue
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        if path.suffix == ".md":
            count += 1
    return count


def export_notion(out_root: Path, target: Path) -> int:
    """Write a Notion-importable CSV: one row per lesson, concepts summarized."""
    records, concepts = collect(out_root)
    names = {slug: payload["name"] for slug, payload in concepts.items()}
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Name", "Module", "Summary", "Concepts", "Duration", "Source"])
        for record in records:
            writer.writerow(
                [
                    record.title,
                    record.module or "Root",
                    record.summary,
                    ", ".join(names.get(slug, slug) for slug in record.concepts),
                    fmt_ts(record.duration),
                    record.lesson_rel,
                ]
            )
    return len(records)


def export_site(out_root: Path, target: Path) -> int:
    """Render every note to HTML plus a grouped index page."""
    records, _ = collect(out_root)
    titles = {record.lesson_rel: record.title for record in records}
    target.mkdir(parents=True, exist_ok=True)
    written = 0

    for path in _iter_markdown(out_root):
        relative = path.relative_to(out_root)
        text = path.read_text(encoding="utf-8", errors="replace")
        body = markdown_to_html(text)
        title = titles.get(relative.as_posix(), relative.stem.replace("-", " ").title())
        destination = (target / relative).with_suffix(".html")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(_page(title, body, _relative_home(relative)), encoding="utf-8")
        written += 1

    groups: dict[str, list[tuple[str, str]]] = {}
    for record in records:
        key = record.module or "(root)"
        href = record.lesson_rel[:-3] + ".html" if record.lesson_rel.endswith(".md") else record.lesson_rel
        groups.setdefault(key, []).append((record.title, href))

    items: list[str] = []
    for module in sorted(groups):
        items.append(f'<li class="module">{html.escape(module)}</li>')
        for title, href in groups[module]:
            items.append(f'<li><a href="{html.escape(href, quote=True)}">{html.escape(title)}</a></li>')
    index_body = (
        "<h1>Course notes</h1>"
        f'<p class="muted">{len(records)} lesson(s)</p>'
        f'<ul class="tree">{"".join(items) or "<li>No notes yet.</li>"}</ul>'
    )
    (target / "index.html").write_text(_page("Shellslatee — course notes", index_body, "index.html"), encoding="utf-8")
    return written
