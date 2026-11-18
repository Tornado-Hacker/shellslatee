from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from shellslatee_engine import indexdb, rag
from tests.test_search import NOTE


class RetrieveTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "lesson.md").write_text(NOTE, encoding="utf-8")
        indexdb.build(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_question_retrieves_citation_with_timestamp(self) -> None:
        citations = rag.retrieve(
            self.root,
            "What exactly happens when the @ symbol is placed in the redirect domain?",
        )
        self.assertTrue(citations, "retrieval must return the matching section")
        self.assertEqual(citations[0].rel, "lesson.md")
        self.assertEqual(citations[0].start, 65)

    def test_no_coverage_stays_empty(self) -> None:
        self.assertEqual(rag.retrieve(self.root, "quantum chromodynamics lattice"), [])


if __name__ == "__main__":
    unittest.main()
