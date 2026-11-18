from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from shellslatee_engine import render


class ConceptPruneTest(unittest.TestCase):
    def test_orphan_concept_pages_are_removed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            concepts = root / "_concepts"
            concepts.mkdir()
            orphan = concepts / "con_core-idea.md"
            orphan.write_text("# Core idea\n", encoding="utf-8")
            keep = concepts / "con_redirect-abuse.md"
            keep.write_text("# Redirect abuse\n", encoding="utf-8")

            payload = {
                "con_redirect-abuse": {
                    "name": "Redirect abuse",
                    "definition": "the redirect target is attacker controlled",
                    "lessons": [],
                    "definitions": 1,
                }
            }
            render.render_concept_pages([], root, payload)

            self.assertFalse(orphan.exists(), "stale concept page must be pruned")
            self.assertTrue(keep.exists())
            self.assertTrue((root / "_glossary.md").exists())


if __name__ == "__main__":
    unittest.main()
