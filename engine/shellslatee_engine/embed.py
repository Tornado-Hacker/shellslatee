"""Local embeddings: hybrid retrieval without a runtime dependency.

The vectors are deterministic feature-hash embeddings — word unigrams plus
character trigrams, signed and L2-normalized into a fixed number of buckets.
No model download, no numpy, no network: the same text always yields the same
vector, so the index is rebuildable and safe to delete.

``hybrid_search`` fuses the SQLite FTS5 ranking with cosine similarity using
reciprocal rank fusion, which finds paraphrases the keyword index misses while
keeping exact-term hits on top. ``related_lessons`` compares lesson-level
centroids for the roadmap's related-lesson links.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import re
from array import array
from pathlib import Path

from .indexdb import (
    IndexError_,
    _frontmatter,
    _split_sections,
    search as search_index,
)
from .util import atomic_write, utc_now

EMB_NAME = "embeddings.json"
DIM = 512
WORD_RE = re.compile(r"[a-z0-9]+")
RRF_K = 60


def _features(text: str) -> list[str]:
    features: list[str] = []
    for word in WORD_RE.findall(text.lower()):
        if len(word) < 2:
            continue
        features.append("w:" + word)
        if len(word) >= 4:
            for start in range(len(word) - 2):
                features.append("c:" + word[start : start + 3])
    return features


def _bucket(feature: str, dim: int) -> tuple[int, float]:
    digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
    value = int.from_bytes(digest, "big")
    sign = 1.0 if (value >> 63) & 1 else -1.0
    return value % dim, sign


def vector(text: str, dim: int = DIM) -> list[float]:
    """Deterministic signed feature-hash vector, L2-normalized."""
    counts: dict[int, float] = {}
    for feature in _features(text):
        index, sign = _bucket(feature, dim)
        counts[index] = counts.get(index, 0.0) + sign
    if not counts:
        return [0.0] * dim
    norm = math.sqrt(sum(value * value for value in counts.values()))
    result = [0.0] * dim
    if norm == 0.0:
        return result
    for index, value in counts.items():
        result[index] = value / norm
    return result


def _encode(vec: list[float]) -> str:
    return base64.b64encode(array("f", vec).tobytes()).decode("ascii")


def _decode(payload: str, dim: int) -> list[float]:
    raw = base64.b64decode(payload.encode("ascii"))
    values = array("f")
    values.frombytes(raw)
    if len(values) != dim:
        return [0.0] * dim
    return list(values)


def _path(out_root: Path) -> Path:
    return out_root / ".shellslatee" / EMB_NAME


def _iter_documents(out_root: Path):
    for path in sorted(out_root.rglob("*.md")):
        relative = path.relative_to(out_root)
        if any(part.startswith((".", "_")) for part in relative.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if not text.startswith("---"):
            continue  # only lesson notes carry frontmatter; skip README/index pages
        fields = _frontmatter(text)
        if not fields:
            continue
        title = fields.get("title", relative.stem).strip().strip('"')
        body = text[text.find("\n---", 3) + 4 :] if text.startswith("---") else text
        for heading, section_text, start in _split_sections(body):
            section_text = section_text.strip()
            if not section_text:
                continue
            yield {
                "lesson": relative.as_posix(),
                "title": title,
                "section": heading,
                "start": start,
                "snippet": " ".join(section_text.split())[:280],
                "text": section_text,
            }


def build(out_root: Path, dim: int = DIM) -> dict[str, int]:
    """Rebuild the embedding index from the Markdown vault."""
    docs: list[dict] = []
    for document in _iter_documents(out_root):
        text = document.pop("text")
        document["vec"] = _encode(vector(f"{document['section']}\n{text}", dim))
        docs.append(document)
    payload = {"dim": dim, "built_at": utc_now(), "docs": docs}
    target = _path(out_root)
    atomic_write(target, json.dumps(payload, separators=(",", ":")) + "\n")
    return {"documents": len(docs), "dim": dim}


def _load(out_root: Path) -> tuple[int, list[dict]]:
    path = _path(out_root)
    if not path.is_file():
        return 0, []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0, []
    dim = int(payload.get("dim", DIM))
    docs = payload.get("docs")
    return dim, docs if isinstance(docs, list) else []


def ensure(out_root: Path, dim: int = DIM) -> tuple[int, list[dict]]:
    """Load the index, building it on first use or after the vault changed."""
    found_dim, docs = _load(out_root)
    if docs:
        return found_dim, docs
    build(out_root, dim)
    return _load(out_root)


def _row(document: dict, score: float | None = None) -> dict[str, str]:
    row = {
        "path": str(document.get("lesson", "")),
        "title": str(document.get("title", "")),
        "section": str(document.get("section", "")),
        "snippet": str(document.get("snippet", "")),
    }
    if document.get("start") is not None:
        row["start"] = str(document["start"])
    if score is not None:
        row["score"] = f"{score:.4f}"
    return row


def semantic(out_root: Path, query: str, limit: int = 10) -> list[dict[str, str]]:
    """Cosine-ranked sections for a query. Empty when the index cannot load."""
    dim, docs = ensure(out_root)
    if not docs:
        return []
    query_vec = vector(query, dim)
    scored: list[tuple[float, dict]] = []
    for document in docs:
        doc_vec = _decode(str(document.get("vec", "")), dim)
        score = sum(left * right for left, right in zip(query_vec, doc_vec))
        if score > 0:
            scored.append((score, document))
    scored.sort(key=lambda item: (-item[0], str(item[1].get("lesson", ""))))
    return [_row(document, score) for score, document in scored[: max(1, limit)]]


def hybrid_search(
    out_root: Path, query: str, limit: int = 10, dedupe: bool = True
) -> list[dict[str, str]]:
    """FTS5 + local embeddings, fused with reciprocal rank fusion."""
    pool = max(limit * 3, limit)
    try:
        keyword = search_index(out_root, query, pool)
    except (IndexError_, ValueError):
        keyword = []
    semantic_rows = semantic(out_root, query, pool)

    scores: dict[tuple[str, str], float] = {}
    meta: dict[tuple[str, str], dict[str, str]] = {}
    for rank, row in enumerate(keyword):
        key = (str(row.get("path", "")), str(row.get("section", "")))
        scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + rank + 1)
        meta.setdefault(key, row)
    for rank, row in enumerate(semantic_rows):
        key = (str(row.get("path", "")), str(row.get("section", "")))
        scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + rank + 1)
        meta.setdefault(key, row)

    ordered = sorted(
        scores.items(),
        key=lambda item: (-item[1], item[0][0], item[0][1]),
    )
    results: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for key, score in ordered:
        if dedupe:
            if key in seen:
                continue
            seen.add(key)
        row = dict(meta[key])
        row["score"] = f"{score:.6f}"
        results.append(row)
        if len(results) >= max(1, limit):
            break
    return results


def _centroids(docs: list[dict], dim: int) -> dict[str, tuple[str, list[float], int]]:
    sums: dict[str, list[float]] = {}
    titles: dict[str, str] = {}
    counts: dict[str, int] = {}
    for document in docs:
        lesson = str(document.get("lesson", ""))
        if not lesson:
            continue
        vec = _decode(str(document.get("vec", "")), dim)
        acc = sums.setdefault(lesson, [0.0] * dim)
        for index, value in enumerate(vec):
            acc[index] += value
        counts[lesson] = counts.get(lesson, 0) + 1
        titles.setdefault(lesson, str(document.get("title", "")))
    centroids: dict[str, tuple[str, list[float], int]] = {}
    for lesson, acc in sums.items():
        norm = math.sqrt(sum(value * value for value in acc))
        unit = [value / norm for value in acc] if norm else acc
        centroids[lesson] = (titles.get(lesson, ""), unit, counts.get(lesson, 0))
    return centroids


def related_lessons(out_root: Path, rel: str, limit: int = 5) -> list[dict]:
    """Lessons whose note text is closest to ``rel`` (cosine of centroids)."""
    dim, docs = ensure(out_root)
    if not docs:
        return []
    centroids = _centroids(docs, dim)
    if rel not in centroids:
        return []
    _, target, _ = centroids[rel]
    scored: list[tuple[float, str, str]] = []
    for lesson, (title, vec, _count) in centroids.items():
        if lesson == rel:
            continue
        score = sum(left * right for left, right in zip(target, vec))
        if score > 0:
            scored.append((score, lesson, title))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [
        {"rel": lesson, "title": title, "score": round(score, 4)}
        for score, lesson, title in scored[: max(1, limit)]
    ]
