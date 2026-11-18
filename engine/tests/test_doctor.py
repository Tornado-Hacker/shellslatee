from __future__ import annotations

import unittest

from shellslatee_engine import doctor


class DoctorTest(unittest.TestCase):
    def test_checks_cover_required_capabilities(self) -> None:
        rows = doctor.checks()
        names = {row["name"] for row in rows}
        self.assertTrue(set(doctor.REQUIRED) <= names, names)
        for row in rows:
            self.assertIsInstance(row["ok"], bool)
            self.assertIsInstance(row["detail"], str)
            self.assertTrue(row["detail"])

    def test_render_matches_check_count(self) -> None:
        rows = doctor.checks()
        lines = doctor.render(rows)
        self.assertEqual(len(lines), len(rows))
        self.assertTrue(all(line.startswith(("ok  ", "miss")) for line in lines))

    def test_ready_only_looks_at_required(self) -> None:
        green = {name: True for name in doctor.REQUIRED}
        optional_missing = [
            {"name": name, "ok": ok, "detail": "x"} for name, ok in green.items()
        ] + [{"name": "ocr engine", "ok": False, "detail": "none"}]
        self.assertTrue(doctor.ready(optional_missing))

        partial = [row for row in optional_missing if row["name"] != "whisper model"]
        self.assertFalse(doctor.ready(partial), "a missing required row is not ready")

        failing = [dict(row) for row in optional_missing]
        failing[0]["ok"] = False
        self.assertFalse(doctor.ready(failing))


if __name__ == "__main__":
    unittest.main()
