#!/usr/bin/env python3
"""Dev wrapper — provisioning now lives in the engine (defect D1).

The installer and the app both call `shellslatee provision`; this file stays so
older notes and muscle memory keep working.

    python scripts/dev/provision-asr.py --dir ~/.local/share/shellslatee/asr
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engine"))

from shellslatee_engine import asr_setup  # noqa: E402

if __name__ == "__main__":
    from shellslatee_engine.cli import main

    sys.exit(main(["provision", *sys.argv[1:]]))
