from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .util import atomic_write, utc_now

STATE_VERSION = 1


@dataclass
class ItemState:
    hash: str
    status: str
    note: str = ""
    engine: str = ""
    model: str = ""
    generation: int = 1
    updated: str = ""
    error: str = ""


@dataclass
class State:
    path: Path
    items: dict[str, ItemState] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "State":
        if not path.exists():
            return cls(path=path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return cls(path=path)
        items: dict[str, ItemState] = {}
        for key, value in (payload.get("items") or {}).items():
            if not isinstance(value, dict):
                continue
            items[key] = ItemState(
                hash=str(value.get("hash", "")),
                status=str(value.get("status", "pending")),
                note=str(value.get("note", "")),
                engine=str(value.get("engine", "")),
                model=str(value.get("model", "")),
                generation=int(value.get("generation", 1)),
                updated=str(value.get("updated", "")),
                error=str(value.get("error", "")),
            )
        return cls(path=path, items=items)

    def save(self) -> None:
        payload = {
            "version": STATE_VERSION,
            "items": {
                key: {
                    "hash": item.hash,
                    "status": item.status,
                    "note": item.note,
                    "engine": item.engine,
                    "model": item.model,
                    "generation": item.generation,
                    "updated": item.updated,
                    "error": item.error,
                }
                for key, item in sorted(self.items.items())
            },
        }
        atomic_write(self.path, json.dumps(payload, indent=2) + "\n")

    def get(self, key: str) -> ItemState | None:
        return self.items.get(key)

    def is_done(self, key: str, file_hash: str) -> bool:
        item = self.items.get(key)
        return bool(item and item.status == "done" and item.hash == file_hash)

    def record_done(
        self, key: str, file_hash: str, note_rel: str, engine: str, model: str, generation: int
    ) -> None:
        self.items[key] = ItemState(
            hash=file_hash,
            status="done",
            note=note_rel,
            engine=engine,
            model=model,
            generation=generation,
            updated=utc_now(),
        )

    def record_failure(self, key: str, file_hash: str, error: str) -> None:
        previous = self.items.get(key)
        self.items[key] = ItemState(
            hash=file_hash,
            status="failed",
            note=previous.note if previous else "",
            engine=previous.engine if previous else "",
            model=previous.model if previous else "",
            generation=previous.generation if previous else 1,
            updated=utc_now(),
            error=error[:1000],
        )
