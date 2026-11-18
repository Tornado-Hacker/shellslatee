"""Concept/lesson graph and Obsidian ``.canvas`` export.

Nodes are lessons and concepts; edges are "covers" (lesson → concept) and
"related" (lessons sharing concepts, weighted by shared count). The graph is
derived from note frontmatter and concept definitions, so it reflects the vault
on disk and is safe to regenerate.
"""

from __future__ import annotations

import json
from pathlib import Path

from .vault import collect


def build(out_root: Path, semantic: bool = False) -> dict:
    records, concepts = collect(out_root)

    nodes: list[dict] = []
    edges: list[dict] = []

    for record in records:
        nodes.append(
            {
                "id": f"lesson:{record.lesson_rel}",
                "kind": "lesson",
                "label": record.title,
                "rel": record.lesson_rel,
                "module": record.module,
            }
        )
    for slug, payload in sorted(concepts.items()):
        nodes.append(
            {
                "id": f"concept:{slug}",
                "kind": "concept",
                "label": payload["name"],
                "slug": slug,
                "definitions": payload.get("definitions", 0),
            }
        )

    lesson_concepts: dict[str, set[str]] = {}
    for record in records:
        covered = {slug for slug in record.concepts if slug in concepts}
        lesson_concepts[record.lesson_rel] = covered
        for slug in sorted(covered):
            edges.append(
                {
                    "src": f"lesson:{record.lesson_rel}",
                    "dst": f"concept:{slug}",
                    "rel": "covers",
                }
            )

    rels = sorted(lesson_concepts)
    for i, left in enumerate(rels):
        for right in rels[i + 1 :]:
            shared = lesson_concepts[left] & lesson_concepts[right]
            if shared:
                edges.append(
                    {
                        "src": f"lesson:{left}",
                        "dst": f"lesson:{right}",
                        "rel": "related",
                        "weight": len(shared),
                    }
                )

    if semantic:
        from . import embed

        known = {
            frozenset((edge["src"], edge["dst"]))
            for edge in edges
            if edge["rel"] == "related"
        }
        for record in records:
            for related in embed.related_lessons(out_root, record.lesson_rel, limit=4):
                pair = frozenset((f"lesson:{record.lesson_rel}", f"lesson:{related['rel']}"))
                if pair in known:
                    continue
                known.add(pair)
                edges.append(
                    {
                        "src": f"lesson:{record.lesson_rel}",
                        "dst": f"lesson:{related['rel']}",
                        "rel": "related",
                        "weight": max(1, round(float(related.get("score", 0.0)) * 10)),
                        "semantic": True,
                    }
                )

    return {
        "nodes": nodes,
        "edges": edges,
        "counts": {
            "lessons": len(records),
            "concepts": len(concepts),
            "edges": len(edges),
        },
    }


def export_canvas(out_root: Path, target: Path, semantic: bool = False) -> int:
    """Write an Obsidian JSON Canvas file with a simple grid layout."""
    graph = build(out_root, semantic=semantic)
    width, height, gap = 240, 90, 60
    columns = 4
    canvas_nodes: list[dict] = []
    concept_offset = 0
    for index, node in enumerate(graph["nodes"]):
        if node["kind"] == "lesson":
            row, col = divmod(index, columns)
        else:
            row, col = divmod(concept_offset, columns)
            concept_offset += 1
        canvas_nodes.append(
            {
                "id": node["id"],
                "type": "text",
                "text": f"**{node['label']}**\n\n_{node['kind']}_",
                "x": col * (width + gap),
                "y": row * (height + gap) + (0 if node["kind"] == "lesson" else 10_000),
                "width": width,
                "height": height,
            }
        )
    canvas_edges = [
        {
            "id": f"e{index}",
            "fromNode": edge["src"],
            "toNode": edge["dst"],
            "label": edge["rel"],
        }
        for index, edge in enumerate(graph["edges"])
    ]
    payload = {"nodes": canvas_nodes, "edges": canvas_edges}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return len(canvas_nodes)
