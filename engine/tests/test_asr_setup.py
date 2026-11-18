from __future__ import annotations

import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from shellslatee_engine import asr_setup


class InspectTest(unittest.TestCase):
    def test_empty_target_lists_everything_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = asr_setup.inspect(Path(tmp))
            self.assertEqual(report["missing"], ["ffmpeg", "ffprobe", "whisper", "model"])
            self.assertFalse(report["has_env"])

    def test_complete_target_reports_nothing_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bin").mkdir()
            for name in ("ffmpeg", "ffprobe"):
                (root / "bin" / (name + asr_setup.EXE)).write_text("x")
            asr_setup.whisper_wrapper(root).write_text("x")
            (root / "models").mkdir()
            (root / "models" / "ggml-tiny.en.bin").write_bytes(b"m")
            report = asr_setup.inspect(root)
            self.assertEqual(report["missing"], [])
            self.assertEqual(report["present"]["models"], ["ggml-tiny.en.bin"])

    def test_unknown_model_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            asr_setup.plan("gigantic")


class EnvTest(unittest.TestCase):
    def test_env_roundtrip_and_apply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bin").mkdir()
            (root / "models").mkdir()
            (root / "models" / "ggml-tiny.en.bin").write_bytes(b"m")
            path = asr_setup.write_env(root)
            values = asr_setup.read_env(path)
            self.assertEqual(values["SHELLSLATEE_WHISPER_MODEL"], str(root / "models" / "ggml-tiny.en.bin"))
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("SHELLSLATEE_WHISPER_BIN", None)
                os.environ.pop("SHELLSLATEE_WHISPER_MODEL", None)
                asr_setup.apply_env(root)
                self.assertIn(str(root / "bin"), os.environ["PATH"].split(os.pathsep))
                self.assertTrue(os.environ["SHELLSLATEE_WHISPER_BIN"].startswith(str(root / "bin")))

    def test_bootstrap_survives_missing_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ, {asr_setup.TARGET_ENV: tmp}, clear=False
        ):
            self.assertEqual(asr_setup.bootstrap(), {})


class ExtractTest(unittest.TestCase):
    def test_zip_extraction_matches_names_anywhere(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "ffmpeg.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("ffmpeg-7.0-essentials_build/bin/ffmpeg", b"bin-ffmpeg")
                bundle.writestr("ffmpeg-7.0-essentials_build/bin/ffprobe", b"bin-ffprobe")
                bundle.writestr("readme.txt", b"noise")
            dest = Path(tmp) / "out"
            found = asr_setup._extract_binaries(archive, {"ffmpeg", "ffprobe"}, dest)
            self.assertEqual(set(found), {"ffmpeg", "ffprobe"})
            self.assertEqual((dest / ("ffmpeg" + asr_setup.EXE)).read_bytes(), b"bin-ffmpeg")
            if os.name != "nt":
                self.assertTrue(os.access(dest / "ffmpeg", os.X_OK))

    def test_download_uses_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "cached.bin"
            dest.write_bytes(b"already-here")
            with mock.patch.object(asr_setup.urllib.request, "urlopen") as opener:
                asr_setup.download("https://example.invalid/x", dest, log=lambda _m: None)
            opener.assert_not_called()


if __name__ == "__main__":
    unittest.main()
