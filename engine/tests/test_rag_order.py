from __future__ import annotations

import unittest

from shellslatee_engine.rag import _order


def row(path: str, section: str, start: str = "") -> dict[str, str]:
    return {"path": path, "title": path, "section": section, "snippet": "x", "start": start}


class OrderTest(unittest.TestCase):
    def test_duplicate_sections_collapse(self) -> None:
        rows = [row("a.md", "Intro"), row("a.md", "Intro"), row("a.md", "Body")]
        self.assertEqual(len(_order(rows)), 2)

    def test_one_lesson_cannot_dominate(self) -> None:
        rows = [row("a.md", f"S{i}") for i in range(10)] + [row("b.md", "Only")]
        ordered = _order(rows, per_lesson=3)
        self.assertEqual([r["path"] for r in ordered].count("a.md"), 3)
        self.assertIn("b.md", [r["path"] for r in ordered])

    def test_timestamped_sections_lead(self) -> None:
        rows = [row("a.md", "Key concepts"), row("a.md", "0:18 — Walk through", "18"), row("a.md", "Notes")]
        self.assertEqual(_order(rows)[0]["section"], "0:18 — Walk through")

    def test_vault_scaffolding_is_not_a_citation(self) -> None:
        rows = [row("README.md", "Modules"), row("_glossary.md", "Terms"), row("a.md", "Body")]
        self.assertEqual([r["path"] for r in _order(rows)], ["a.md"])

    def test_inline_stamp_counts_without_start_field(self) -> None:
        rows = [row("a.md", "Summary"), row("a.md", "1:02:03 — Demo")]
        self.assertTrue(_order(rows)[0]["section"].endswith("Demo"))


if __name__ == "__main__":
    unittest.main()
