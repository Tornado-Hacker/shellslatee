# Contributing

Shellslatee is a Tauri 2 + React 19 desktop app with a Python engine that ships
as a wheel inside the installer.

## Layout

```
src/                 React UI (pages, components, lib)
src-tauri/           Rust shell; spawns the engine, owns the window
src-tauri/resources/ the built engine wheel (do not edit by hand)
engine/              Python engine source (the shipped code)
scripts/dev/         developer helpers (thin wrappers over engine commands)
tracking.md          status, defect ledger, version plan
```

## Prerequisites

| Platform | Needs |
| --- | --- |
| Windows | Node 20+, Rust 1.77+ with the MSVC toolchain, Python 3.10+, WebView2 (ships with Windows 11) |
| Linux | Node 20+, Rust, `webkit2gtk-4.1`, `libgtk-3-dev`, Python 3.10+ |
| macOS | Node 20+, Rust, Xcode command line tools, Python 3.10+ |

Optionally `shellslatee provision` (or Settings → Transcription engine) for
local video transcription; slides and PDFs work without it.

## Run

```bash
npm install
npm run dev            # UI only, against a local engine you start yourself
npm run tauri dev      # full desktop app
```

Engine on its own:

```bash
cd engine
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
python -m unittest discover -s tests -t .
python -m shellslatee_engine serve --port 8677
```

## Before opening a PR

```bash
npx tsc --noEmit
npm run build
cd engine && python -m unittest discover -s tests -t .
cargo check --manifest-path src-tauri/Cargo.toml --all-targets
```

All four run in CI. Keep engine tests offline: no network in unit tests.

## Conventions

- Engine changes: `engine/` is the source of truth. Rebuild the wheel with
  `python -m build --wheel --outdir dist` inside `engine/`, then copy it to
  `src-tauri/resources/` and `dist-engine/`. Never edit the wheel in place.
- Tests: pure functions first; mock the provider and the network.
- Comments explain *why* (constraints, failure modes), not *what*.
- Docs that state a limitation must match the code; `tracking.md` records what
  is known-broken and what closed.
- Version: `package.json`, `engine/pyproject.toml`, `src-tauri/Cargo.toml` and
  `src-tauri/tauri.conf.json` move together.

## Reporting defects

Use the tracking table format: symptom, evidence (command + output), likely
cause, and whether it blocks 0.3.0. Unsigned installer behaviour and plaintext
keys are known and tracked — see `SECURITY.md`.
