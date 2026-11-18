#!/usr/bin/env python3
"""whisper.cpp-CLI-compatible shim backed by faster-whisper.

Why this exists: the engine shells out to `whisper-cli` (whisper.cpp) and reads
its `-oj` JSON. Building whisper.cpp on a dev box is slow and needs cmake; on
Linux/macOS contributors can install nothing but Python and still exercise the
real pipeline.

    python -m pip install faster-whisper numpy
    export SHELLSLATEE_WHISPER_BIN="$PWD/scripts/dev/whisper-cli-faster.py"
    export SHELLSLATEE_WHISPER_MODEL=/path/to/ggml-base.en.bin   # presence only
    shellslatee run ./course ./vault --transcriber whisper --provider aikey

The `-m` model path is validated by the engine but ignored here: faster-whisper
downloads and caches its own CTranslate2 weights ("tiny.en" by default, override
with WHISPER_SHIM_SIZE). This is a development aid, not part of the installer.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import wave
from pathlib import Path


def load_audio(path: str, sample_rate: int = 16000):
    """Decode PCM wav with the stdlib; fall back to PyAV for other containers.

    PyAV's API has moved (av>=14 dropped `metadata_errors`), which is what
    faster-whisper 1.2.x's decode path still passes. The engine always hands us
    16 kHz mono s16le wav, so the stdlib path is the normal one.
    """
    try:
        with wave.open(path, "rb") as handle:
            if (
                handle.getframerate() == sample_rate
                and handle.getnchannels() == 1
                and handle.getsampwidth() == 2
            ):
                import numpy as np

                pcm = np.frombuffer(
                    handle.readframes(handle.getnframes()), dtype=np.int16
                )
                return pcm.astype(np.float32) / 32768.0
    except (wave.Error, EOFError):
        pass

    from faster_whisper.audio import decode_audio

    return decode_audio(path, sampling_rate=sample_rate)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-m", dest="model")
    parser.add_argument("-f", dest="audio", required=True)
    parser.add_argument("-l", dest="language", default="en")
    parser.add_argument("-t", dest="threads", type=int, default=4)
    parser.add_argument("-oj", dest="json", action="store_true")
    parser.add_argument("-of", dest="prefix")
    parser.add_argument("-np", dest="quiet", action="store_true")
    return parser


def main() -> int:
    args, _unknown = build_parser().parse_known_args()

    from faster_whisper import WhisperModel

    size = os.environ.get("WHISPER_SHIM_SIZE") or (
        "tiny.en" if args.language.startswith("en") else "tiny"
    )
    model = WhisperModel(
        size,
        device="cpu",
        compute_type="int8",
        cpu_threads=max(1, args.threads),
    )
    segments, info = model.transcribe(
        load_audio(args.audio),
        language=args.language,
        vad_filter=True,
        beam_size=1,
    )

    payload = {
        "systeminfo": "faster-whisper shim",
        "model": {"type": size},
        "result": {"language": args.language},
        "transcription": [],
    }
    for segment in segments:
        text = segment.text.strip()
        if not text:
            continue
        payload["transcription"].append(
            {
                "timestamps": {"from": "00:00:00.000", "to": "00:00:00.000"},
                "offsets": {
                    "from": int(segment.start * 1000),
                    "to": int(segment.end * 1000),
                },
                "text": " " + text,
            }
        )

    if not payload["transcription"]:
        print("whisper-cli: no speech segments", file=sys.stderr)
        return 2

    encoded = json.dumps(payload, ensure_ascii=False, indent=1)
    if args.prefix:
        Path(args.prefix + ".json").write_text(encoded, encoding="utf-8")
    if not args.quiet:
        for item in payload["transcription"]:
            offsets = item["offsets"]
            print(f"[{offsets['from']:>8} --> {offsets['to']:>8}] {item['text']}")
    print(
        f"whisper-cli: {len(payload['transcription'])} segments, "
        f"{info.duration:.1f}s audio",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
