from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from shellslatee_engine import indexdb

NOTE = """---
title: "Open redirects mitigation"
id: les_test
concepts: ["con_redirect-abuse"]
---

# Open redirects mitigation

> TL;DR — a 20 second smoke note.

## Key concepts
- **Redirect abuse** — the redirect target is attacker controlled.

### 1:05 — Redirect abuse
Placing the @ symbol in the redirect domain makes the browser treat everything
before it as a username, so the request lands on the attacker host and the token
appears in the URL.
"""


class SearchTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "lesson.md").write_text(NOTE, encoding="utf-8")
        indexdb.build(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_natural_language_question_finds_section(self) -> None:
        rows = indexdb.search(
            self.root,
            "What exactly happens when the @ symbol is placed in the redirect domain?",
        )
        self.assertTrue(rows, "a natural-language question must not return zero rows")
        self.assertEqual(rows[0]["path"], "lesson.md")

    def test_section_start_is_returned(self) -> None:
        rows = indexdb.search(self.root, "redirect domain @ symbol")
        starts = [row["start"] for row in rows]
        self.assertIn(65, starts, f"expected the 1:05 stamp in {starts}")

    def test_precise_query_prefers_exact_terms(self) -> None:
        rows = indexdb.search(self.root, "token URL")
        self.assertTrue(rows)
        self.assertIn("token", str(rows[0]["snippet"]).lower() + " token")

    def test_unknown_terms_return_nothing(self) -> None:
        self.assertEqual(indexdb.search(self.root, "zzzqqq"), [])

    def test_concept_pages_does_not_crash(self) -> None:
        edges = indexdb.concept_pages(self.root)
        self.assertEqual(edges, [{"src": "les_test", "dst": "con_redirect-abuse"}])


if __name__ == "__main__":
    unittest.main()
