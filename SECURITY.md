# Security

Shellslatee turns lecture videos into local study notes. It runs an engine on
loopback, calls your chosen model provider, and stores your API keys locally.

## Reporting a vulnerability

Open a private report through the repository's Security tab, or email the
maintainer listed on the GitHub profile. Please include a minimal reproduction,
affected version (`shellslatee --version` or the About screen) and platform.

We aim to acknowledge within 72 hours and to ship a fix for anything that can
leak a key, execute untrusted input, or escape the loopback boundary.

## What the app does with your data

| Item | Where it lives | Notes |
| --- | --- | --- |
| API keys | `~/.config/shellslatee/desktop_keys.json` (Windows: `C:\Users\<you>\.config\shellslatee\`) | **Plaintext JSON, mode 0600.** The OS keychain is used when `SHELLSLATEE_KEYCHAIN=1` and an entry exists; otherwise the file is the fallback. Encrypted export is on the roadmap (tracking D5). |
| Course videos | your source folder | read only |
| Transcripts and notes | your vault folder | plain Markdown you own |
| Model requests | your provider | only the transcript + prompt for the notes step |
| Engine API | `127.0.0.1`, random port | no authentication; anything local can call it. Do not expose it |

Nothing is uploaded to the Shellslatee authors. There is no telemetry.

## Local API notes

The engine binds loopback only (`--host 127.0.0.1`, or `--port 0` chosen by the
app). Endpoints can read vault paths, write notes, and run jobs. Treat the
machine's local users as trusted; do not forward the port.

## Supported versions

Fixes land on the current 0.3.x line. Older 0.2.x installers are unsigned and
will not receive security patches once 0.3.0 ships.

## Known gaps (tracked, not hidden)

- Installers are unsigned until the code-signing certificate lands (D7).
- Keys are plaintext at rest (D5) — the README no longer claims otherwise.
- The first-run ASR download fetches from gyan.dev, Hugging Face and PyPI over
  HTTPS; no pinning or signature check yet.
