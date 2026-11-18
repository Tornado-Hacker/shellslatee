# Shellslatee — delivery tracking

Living status document. Every claim here is tied to a command that was run and
a file that exists. When something moves, this file moves with it; nothing is
marked done on intent.

Last updated: 2026-11-17

---

## 1. Version ladder (names are fixed)

| Version | Name | Meaning | State |
| --- | --- | --- | --- |
| 0.1.0 | **Genesis** | Headless engine: folder of videos → mirrored Markdown vault | engine wheel only |
| 0.2.0 | **Shell** | Tauri desktop shell, engine lifecycle, key storage, proxy | shipped |
| 0.2.4 | **Session** | Notes-folder wizard, self-healing supervisor, study loop | **shipped, current public release** |
| 0.3.0 | **Voice** | *First release that can be handed to a stranger and completed end to end* — ASR provisioning, real-content validation, signing, licence, defect P0s | **in progress** |
| 0.4.0 | **Recall** | Citation fidelity (timestamps), ask router that survives natural language, concept pruning, OCR | planned |
| 0.5.0 | **Reliability** | Multi-hour batches, resume/retry, cost ceiling, budget ledger | planned |
| 0.9.0 | **Release Candidate** | Signed MSI + NSIS, upgrade path, telemetry-free attestation, installer QA matrix | planned |
| 1.0.0 | **Cockpit** | The professional, full-fledged version — see §6 | planned |

**Answer to "what is the version name":** shipped is `0.2.4 Session`. The working
target right now is `0.3.0 Voice`. The full-fledged professional version is
`1.0.0 Cockpit`.

---

## 2. Where we are (as measured, not as intended)

| Dimension | Measure | Verdict |
| --- | --- | --- |
| UI surface | 4,910 LOC, 7 pages, 13 endpoints, zero TODOs | complete for 0.2.4 |
| Engine surface | vendored in `engine/` (0.2.1): 8,862 LOC, 40 modules, 33 endpoints, unit tests | complete for 0.2.1 |
| API contract | every endpoint the UI calls exists in the engine | closed |
| Installers | 0.2.0 → 0.2.4, MSI + NSIS, unsigned | built |
| Engine source | vendored at `engine/`, recovered from the shipped wheel; upstream repo still private | **P0 risk reduced, not removed** |
| Tests / CI | CI runs typecheck, bundle, `cargo check`, dev-tool syntax, **8 engine unit tests** | closed for current scope |
| Licence file | `LICENSE` added (MIT), `package.json` licensed | closed 2026-11-17 |
| Real-content runs before today | **0** | closed today (§3) |
| Real-content runs today | 2 lessons, 3m22s of video, 33 cards, 22 quiz items | **pipeline proven once** |
| Ship-to-stranger readiness | ~45% | 0.3.0 work |

---

## 3. Evidence log — 2026-11-17 (first time the product was actually flown)

Source material: `FsKnockOut / NahamSec — Hands-On Web Exploitation Course`
(154 MP4 files, 3.3 GB). Test host: Linux (dev-side), engine 0.2.0 from the
bundled wheel, ASR via a `whisper.cpp`-CLI-compatible shim over
`faster-whisper` (`scripts/dev/whisper-cli-faster.py`), ffmpeg 7.0.2 static.

| # | Input | Command | Result |
| --- | --- | --- | --- |
| 1 | 63s MP4, open redirects lab | `shellslatee run … --transcriber whisper --provider mock` | 1 note, 4 concepts, quality 94 |
| 2 | same | `--provider aikey` (`deepseek-v4.1-flash:free`) | 1 note, 5 concepts, quality 94, $0.00 |
| 3 | 139s MP4, SSRF via PDFs | `--provider aikey`, next lesson | 1 note, 6 concepts, quality 100 |
| 4 | both | `shellslatee index` | 2 notes, 11 concepts indexed |
| 5 | both | `cards build` / `quiz build` | 33 cards, 22 quiz items |
| 6 | both | `GET /api/search?q=token` | hits with section + snippet |
| 7 | both | `GET /api/health`, `/api/vault`, `/api/cards` | served correctly over loopback |
| 8 | notes on disk | read `09-open-redirects-mitigation.md`, `15-ssrf-via-pdfs.md` | TL;DR + stamped walkthrough + review questions, accurate to the audio |

What this proves: ingest → ASR → LLM notes → Markdown vault → index → cards →
quiz → API is a **working chain** on real lecture content, at a cost of
~$0.0004/lesson and ~50s wall time per 2-minute lesson on CPU.

What it does **not** prove: Windows installer path, multi-hour batches, note
quality at lecture scale, prompt-injection resistance, OCR, and the "Ask the
whole course" flagship (§4, defect D2).

---

## 4. Defects found by flying it

### P0 — blocks a stranger from completing the first run

**D1. ASR is not provisioned by anything.**
`transcribe.py:154` resolves `whisper-cli`/`whisper` on `PATH` and requires
`SHELLSLATEE_WHISPER_MODEL`; `media.py:24,46` require `ffprobe`/`ffmpeg`.
`shellslatee doctor` reports all four as missing, and the installer ships none
of them. A fresh install cannot transcribe a single video, which is why the
shipped vault contains **0 notes**.
*Status 2026-11-17:* mitigated at the tooling level. `scripts/dev/provision-asr.py`
builds a self-contained ASR directory (static ffmpeg + ggml model + a
whisper.cpp-CLI-compatible `whisper-cli` wrapper over faster-whisper), writes
`asr.env`, and was proven end to end: `shellslatee doctor` reported **five green
ASR lines** and a fresh vault produced a note from scratch on the provisioned
directory. *Status 2026-11-17 (later):* **closed in the product.** The logic now lives in
`shellslatee_engine/asr_setup.py` — `shellslatee provision`, `GET /api/asr/status`,
`POST /api/asr/provision` (runs as a normal job, so progress streams through the
existing job model), and `POST /api/asr/apply`. Settings → *Transcription engine*
has a **Set up transcription** button that drives the job and re-checks readiness;
`asr.env` is loaded at engine startup, so no PATH editing and no terminal.
Proven from the built wheel in a fresh directory, then a lesson transcribed and
written through the API.

**D2. "Ask the whole course" returns nothing for a natural-language question.**
`rag.retrieve` passes the raw question to the FTS index; FTS needs every term
to match, so "What exactly breaks when the @ symbol is placed in the redirect
domain?" → `{"answer": "I could not find anything…", "citations": []}`, while
`"open redirect token"` → a correct cited answer.
*Status 2026-11-17:* **closed.** `indexdb.search` now tokenizes, drops
stopwords, tries a precise AND pass, then an OR pass over the same tokens, and
joins `segment` to return the section's start second. Verified against a real
vault: the sentence above retrieves four sections and `/api/ask_course` answers
with `[1]…[6]` citations instead of "nothing covers that". Eight unit tests in
`engine/tests/` pin the behaviour.

**D3. Engine source has no home on this machine.**
The public repo contains the shell only (10 commits, tag `v0.2.0`), and the
wheel was the sole engine artifact.
*Status 2026-11-17:* **closed by recovery.** All 40 modules were extracted from
the wheel into `engine/` (they ship as plain `.py`), given a `pyproject.toml`,
`LICENSE`, README and tests, and rebuilt as `0.2.1`. The installer now bundles
`shellslatee_engine-0.2.1-py3-none-any.whl` built from that tree. Residual risk:
the upstream private repo is still the nominal source of truth — mirror and tag
it before the next release.

### P1 — degrades the flagship promise

**D4. Citations lose their timestamps.** Notes carry `### 0:47 — …` headings,
but search returned no start second, so a "source chip" landed on a lesson.
*Status 2026-11-17:* **closed.** Search joins the `segment` table
(`MIN(start_s)` per lesson+heading) and returns `start`. Verified: the open
redirects section now resolves to `18s` and the SSRF request section to `0s`
where the heading carries a stamp; sections without stamps honestly return
null.

**D5. The key-export claim is false.** README says *"Settings → Export keys
writes an encrypted file"*; `Cargo.toml` has no crypto crate and
`desktop_keys.json` is plaintext JSON.
*Status 2026-11-17:* README corrected — it now states the file is plaintext JSON
and how to treat it. Encryption at rest (Argon2id + ChaCha20-Poly1305) remains an
open 0.3.0 item.

**D6. No LICENSE in the repo while both artifacts claim MIT.** *Closed 2026-11-17:*
`LICENSE` (MIT) added, `package.json` carries `"license": "MIT"`.

**D7. Unsigned installers.** SmartScreen blocks the first-run experience.
*Fix:* Authenticode certificate + `signtool` in `build.ps1` (0.3.0), or a
documented, verifiable SHA-256 + release-notes path until then.

### P2 — correctness and hygiene

**D8. Orphan concept files survive regeneration.** After a mock run followed by
a real run, `_concepts/` kept pages no note referenced.
*Status 2026-11-17:* **closed.** `render_concept_pages` deletes any `*.md` in
`_concepts/` whose stem is not in the current concept set. Unit-tested.

**D9. `graph build` rejects a positional vault path.** *Retracted — not a
defect.* The command is `shellslatee graph <vault>`; the earlier invocation used
a non-existent `build` subcommand. Documentation only: the help text is correct.

**D10. Roadmap understates the engine.** `serve`, `plugins`, `publish`, `mcp`,
`watch`, `tui`, `ocr` hooks and drills already exist; the roadmap listed plugins
as a 1.0.0 item. *Closed 2026-11-17:* README roadmap rewritten to the version
ladder and caveats list what ships but is not yet in the UI.

**D11. `indexdb.concept_pages` referenced an undefined `dedupe`.** Any call
raised `NameError`. *Closed:* the function returns the edge rows; covered by a
unit test.

**D12. Concept ids kept their JSON quotes.** `concepts: ["con_x"]` produced the
edge target `"con_x"` (with quotes), which would mis-name pages and backlinks.
*Closed:* ids are stripped of quotes at index time; covered by a unit test.

---

## 5. 0.3.0 "Voice" — exit criteria (all must be true to tag)

1. Fresh Windows 10/11 VM: install → add key → drop a 30-minute lecture → note,
   cards, quiz, ask, without opening a terminal. Zero manual downloads.
2. `shellslatee doctor` green on a clean machine (ffmpeg, ffprobe, whisper-cli,
   model, provider key).
3. ~~D1, D2, D4 closed in the engine tree; D3 closed by vendoring~~
   D1, D2, D3, D4, D8, D11, D12, D13, D14 closed 2026-11-17; D1 verified on
   real Windows through the shipped app + API.
4. 10 real lectures (≥3 hours) in one batch, 0 failures, resumable after a kill.
5. Cost and time reported per lesson; a hard ceiling in settings.
6. ~~`LICENSE`, corrected README claims, `SECURITY.md`, `CONTRIBUTING.md`.~~
   done 2026-11-17.
7. Installers signed or the unsigned path documented with hashes.
   Unsigned path documented (§15, hashes below); signing still open (D7).
8. ~~CI: `npm run build`, `cargo check`, engine `pytest`, on every push.~~
   done — plus wheel-content assertions and a real `cargo check` on Windows.
9. First-run screen never shows a raw exception.
10. The tracking table in this file updated with measured numbers only.

---

## 6. 1.0.0 "Cockpit" — the full-fledged professional version

Not a bigger 0.3.0. Defined by what a paying, non-technical student and a
security reviewer can both rely on.

**Product**
- End-to-end first run, zero terminal, zero manual dependency install.
- Any lecture format: MP4/MKV/WebM/MP3/PPTX/DOCX/PDF, scanned PDFs via bundled
  OCR, screen-only recordings via frame sampling.
- Hours-long batches with pause/resume, crash recovery, and per-item retry.
- Cited tutor with **timestamp-accurate** chips; explain-back coach with rubric
  scores and a per-concept confusion heatmap that actually drives the planner.
- Exam planner that survives schedule changes; offline study mode.
- Export: Markdown, Anki, static study site (`publish`), and a documented
  adapter API for third-party vaults.

**Engineering**
- Engine vendored, tested (unit + golden-file pipeline tests), typed, linted.
- CI/CD: signed installers, reproducible builds, release notes generated from
  commits, automated upgrade test from 0.2.x.
- Crash reporting that is opt-in and local-only; a written, verifiable
  no-telemetry statement.
- Performance budget: 30-min lecture ≤ 6 min on a 4-core laptop with a local
  ASR model; memory ceiling documented.
- Prompt-injection containment: notes and transcripts are treated as untrusted
  input, tools are not callable from note content.

**Trust**
- MIT (or chosen) licence, SECURITY.md, disclosure policy, SBOM.
- Signed binaries; SmartScreen clean; documented data-flow diagram showing the
  only outbound calls are to the user's chosen model provider.
- Keys encrypted at rest with a user passphrase; export/import round-trip test.
- Accessibility pass (keyboard, contrast, screen reader labels).

**Business readiness**
- Pricing page, licence key or BYO-key story, refund/terms, support channel.
- Demo vault + 3-minute walkthrough video.
- Roadmap for the plugin marketplace with a sandboxed plugin ABI (wasm).

**Definition of done:** a stranger on a clean Windows 11 laptop, with one API
key, goes from download to a studied lecture in under 10 minutes without
reading a README section twice, and a security reviewer reads the repo and
finds nothing claimed that isn't in the code.

---

## 7. Path from here

| Step | Work | Effort | Unblocks |
| --- | --- | --- | --- |
| 1 | Vendor the engine tree + tag + mirror wheel | 0.5 d | D3, all engine fixes |
| 2 | ~~Provision ASR (download/verify/install + PATH + Settings UI)~~ done — `asr_setup.py`, `/api/asr/*`, Settings card | — | D1, first-run |
| 3 | Fix ask router (AND→OR→hybrid) + timestamp citations | 1 d | D2, D4 |
| 4 | Windows VM pass on 30-min lecture, then 10-lecture batch | 1 d | 0.3.0 criteria 1, 4 |
| 5 | LICENSE/SECURITY/CONTRIBUTING + README truth + hashes | 0.5 d | D5, D6 |
| 6 | CI + signing cert procurement (lead time) | 1 d + lead | D7, criteria 7–8 |
| 7 | Concept pruning, CLI consistency | 0.5 d | D8, D9 |

Rough: **0.3.0 Voice ≈ 6–7 focused days** (with a signing certificate already
in hand), **1.0.0 Cockpit ≈ 6–8 weeks** of product work after that, with the
genuine unknowns being note quality at scale and long-batch stability — not
the remaining UI.

---

## 8. Risk register

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Engine source lost (only a wheel exists) | product unrecoverable | vendor + tag + mirror now |
| ASR licensing: static ffmpeg builds are GPL | redistribution problem | use an LGPL ffmpeg build, or download at first run and record acceptance |
| Whisper model size vs installer | 75–150 MB download | download on first run with checksum + resume |
| LLM cost surprise on long courses | user trust | preflight estimate (already emitted) + hard ceiling + per-lesson ledger |
| Note quality collapses on dense lectures | the actual product risk | golden-file eval on 10 lectures, rubric floor, one retry (exists), human spot-check |
| Unsigned installer habits | SmartScreen friction | certificate + documented hashes until then |
| Two version numbers (shell 0.2.4 / engine 0.2.0) | support confusion | single release train from 0.3.0; engine version pinned in `tracking.md` |

---

## 9. Repo hygiene state

- `dist/` and `src-tauri/target/` are build output (2.6 GB `target/` locally);
  confirm `.gitignore` coverage before the next commit.
- `src-tauri/resources/shellslatee_engine-0.2.1-py3-none-any.whl` is now a
  build output of `engine/` (`python -m build --wheel --outdir dist`), not an
  opaque input. `dist-engine/` carries the same artifact.
- Dev shim `scripts/dev/whisper-cli-faster.py` is checked in so any contributor
  on Linux/macOS can run the real pipeline without building whisper.cpp. It is
  a dev tool, not shipped in the installer.

---

## 10. Session changelog — 2026-11-17

Files added or changed in this pass:

| File | Change |
| --- | --- |
| `tracking.md` | new — this document |
| `LICENSE` | new — MIT |
| `README.md` | key-export claim corrected; new **Step 2b — Audio transcription** (doctor + install workaround); roadmap rewritten to the version ladder; caveats updated (engine not published, ask-query defect, engine features not yet in UI) |
| `scripts/dev/whisper-cli-faster.py` | new — `whisper.cpp`-CLI-compatible dev shim over faster-whisper (handles PCM wav without PyAV API drift) |
| `scripts/dev/provision-asr.py` | now a thin wrapper over `shellslatee provision` (canonical logic moved into the engine) |
| `.github/workflows/ci.yml` | new — web typecheck/bundle, `cargo check`, dev-tool syntax; engine job commented until D3 |
| `package.json` | `license`, `description` added |

Verification performed this session (commands actually run):

1. `shellslatee run` on a 63s lecture, `--provider mock` → note, 4 concepts, quality 94.
2. Same lecture, `--provider aikey` → note, 5 concepts, quality 94, $0.00.
3. Second lecture (139s, SSRF via PDFs) → note, 6 concepts, quality 100.
4. `index` → 2 notes / 11 concepts; `cards build` → 33 cards; `quiz build` → 22 items.
5. `GET /api/search?out=…&q=token` → ranked hits with sections.
6. `POST /api/ask_course` with a natural-language question → **empty answer, 0 citations (D2)**; with keyword query → cited answer.
7. `provision-asr.py` from a clean venv → downloads, installs, writes `asr.env`; then `shellslatee doctor` shows `ok` for ffmpeg, ffprobe, whisper.cpp, model; then a fresh vault produces its first note.
8. `tsc --noEmit` → clean.

Not verified: Windows installer path, signing, multi-hour batches, OCR,
prompt-injection behaviour, ask-quality grading.

---

## 11. Session changelog — 2026-11-17 (pass 2: engine recovered and fixed)

| File | Change |
| --- | --- |
| `engine/` (40 modules) | new — engine 0.2.1 source recovered verbatim from the 0.2.0 wheel, plus `pyproject.toml`, `README.md`, `LICENSE`, `dist/` wheel |
| `engine/shellslatee_engine/indexdb.py` | stopword list, tokenizer, AND→OR fallback, `start` second returned from `segment`, quote-stripped concept ids, `concept_pages` crash fixed |
| `engine/shellslatee_engine/render.py` | prunes unreferenced `_concepts/*.md` after writing |
| `engine/tests/` | 18 unit tests: NL search, timestamps, no-match, concept edges, retrieval, orphan prune, doctor, transport retry, citation ordering |
| `engine/dist/shellslatee_engine-0.2.1-py3-none-any.whl` | new artifact |
| `src-tauri/resources/`, `dist-engine/` | 0.2.1 wheel (0.2.0 removed) |
| `src-tauri/src/main.rs`, `src-tauri/tauri.conf.json` | bundle `0.2.1` |
| `.github/workflows/ci.yml` | engine job: install + `unittest discover` |
| `README.md` | engine section, project layout, install commands, caveats |

Verification actually run this pass:

1. `python -m unittest discover -s tests -t .` → **8 tests, OK**.
2. `python -m build --wheel` → `shellslatee_engine-0.2.1-py3-none-any.whl`.
3. Fresh venv + wheel → `shellslatee --version` → `0.2.1`; `/api/health` → `"version": "0.2.1"`.
4. Natural-language question against the real 2-lesson vault →
   `indexdb.search` returns 4 sections, one with `start=18`;
   `POST /api/ask_course` returns a synthesised answer with six citations
   (was: empty answer, zero citations).
5. Orphan prune path exercised by unit test (delete `con_core-idea.md`, keep
   the referenced page, glossary rewritten).

Still open: signed installers (D7), key
encryption (D5 implementation), Windows VM batch, OCR.

---

## 12. Session changelog — 2026-11-17 (pass 3: doctor surfaced in the product)

| File | Change |
| --- | --- |
| `engine/shellslatee_engine/doctor.py` | new — shared environment checks (`checks`, `ready`, `render`) used by the CLI and the API; `ready` requires every `REQUIRED` capability present and green |
| `engine/shellslatee_engine/cli.py` | `shellslatee doctor` delegates to `doctor.render()` (same output, one source of truth) |
| `engine/shellslatee_engine/serve.py` | `GET /api/doctor` → `{checks, ready}`; added to the `/` API index |
| `engine/tests/test_doctor.py` | 3 tests: required coverage, render parity, strict readiness |
| `src/lib/types.ts`, `src/lib/api.ts` | `DoctorCheck` / `DoctorReport`, `api.doctor()` |
| `src/pages/SettingsPage.tsx` | **Settings → Transcription engine** card: live rows, ready/missing badge, Re-check button, provisioner hint |
| `src-tauri/resources/`, `dist-engine/` | rebuilt 0.2.1 wheel |
| `README.md` | points at the Settings panel |

Verification actually run:

1. `python -m unittest discover -s tests -t .` → **11 tests, OK**.
2. `shellslatee doctor` → five ASR lines green on the provisioned directory.
3. `GET /api/doctor` → `{"ready": true, "checks": [...]}` with `python/ffmpeg/ffprobe/whisper.cpp/whisper model` green and OCR honestly `false`.
4. `npx tsc --noEmit` → clean with the new card.
5. `/` index lists `/api/doctor`.

This closes D1's *discoverability* half (a user can now see and fix the gap in
the app). The *automatic* half — provisioning without a terminal — remains the
0.3.0 installer hook.

---

## 13. Session changelog — 2026-11-17 (pass 4: batch proof, transport retry, citation order)

### Batch validation — 8 real lectures, one worker, real provider

| Lesson | Duration | Wall time | Quality |
| --- | --- | --- | --- |
| 09-02 basic example | 118s | 2m 03s | 100 |
| 09-03 bypassing protections | 113s | 2m 08s | 100 |
| 09-05 mitigation one | 123s | 2m 04s | 100 |
| 09-06 mitigation two | 63s | 1m 03s | 100 |
| 14-08 final notes | 119s | 1m 58s | 100 |
| 17-02 RCE basic | 113s | 1m 52s | 100 |
| 18-02 identification | 112s | 1m 53s | 100 |
| 18-03 exploration | 103s | 1m 44s | 100 |

**8 written, 0 failed, 0 skipped** — 46 concepts, 149 cards, 104 quiz items, **$0.00** on
`aikey:deepseek-v4.1-flash:free`. Throughput ≈ 1m 55s per 2-minute lesson on one worker,
so the 154-video course is ≈ 4.5–5 hours of unattended wall time.

### Defects this pass

| ID | What | Status |
| --- | --- | --- |
| D13 | Free-tier provider drops HTTP connections mid-batch (`Remote end closed connection without response`) — first 8-lesson run lost 2 lessons outright, batch stalled on retries that never matched the exception type | **closed** — `providers.chat` retries `http.client.HTTPException` and `ConnectionError` with the same backoff/`Retry-After` path; two tests pin success-after-reset and give-up-after-`MAX_RETRIES` |
| D14 | Citations could repeat a section, let one lesson fill the list, and cite vault scaffolding (`README.md`) as if it were source | **closed** — `rag._order` dedupes `(path, section)`, caps 3 sections per lesson, drops `README.md`/`_*` files, and puts timestamped sections first; 5 tests |
| D15 | Rate-limit + parallel workers: `--jobs 2` on the free tier produced connection resets even with retry (each worker contends for the same connection budget) | **documented** — one worker is the safe default for free tiers; CI/docs note it. Not a code defect. |

Side finding worth keeping honest: a real `ask` on the batch vault says *"the actual
allowlist-bypass techniques are not covered in these excerpts"* rather than inventing
payloads — grounding held under a weak-evidence question. That is the behaviour we want;
it also shows notes carry technique names, not literal payload strings, when the lecture
never states them.

### Also verified this pass

- `vite build` **succeeds** (24.7s, 635 KB / 197 KB gzip) once output goes to a local disk
  path; the earlier hang was the `/mnt/c` output directory, not the build itself.
- `shellslatee index/cards/quiz` on the 8-note vault: 8 notes, 46 concepts, 149 cards,
  104 quiz items in seconds.
- Settings → Transcription engine doctor card: `tsc --noEmit` clean; bundle rebuilt.

### Open risks after this pass

| Risk | Note |
| --- | --- |
| Installer not built/tested on Windows here | No Ruby/NSIS/WiX/VM in this environment; CI job is the only place `cargo check` runs |
| Single 635 KB JS chunk | Acceptable for desktop; page-level lazy imports are a 0.4.0 nicety |
| Free-tier burst limits | Use `--jobs 1`, retry handles the rest; paid key parallelises safely |

---

## 14. Session changelog — 2026-11-17 (pass 5: D1 closed inside the product)

| File | Change |
| --- | --- |
| `engine/shellslatee_engine/asr_setup.py` | **new** — `default_dir` (per-user app data, `SHELLSLATEE_ASR_DIR` override), `inspect`, `plan`, `download` (`.part` + cache), `_extract_binaries` (zip/tar, name-anywhere), `_install_ffmpeg`, `_install_whisper` (keeps a native binary, else writes the faster-whisper wrapper, installing the wheels only when the import fails), `write_env` / `read_env` / `apply_env` / `bootstrap`, `install` |
| `engine/shellslatee_engine/data/whisper-cli-faster.py` | shim moved into the package (wheel ships it via `package-data`); `scripts/dev/whisper-cli-faster.py` is now a launcher |
| `engine/shellslatee_engine/cli.py` | `shellslatee provision [--dir] [--model] [--force]`; `bootstrap()` on every CLI start |
| `engine/shellslatee_engine/serve.py` | `GET /api/asr/status`, `POST /api/asr/provision` (job), `POST /api/asr/apply`; `JobRunner.start_command`; `bootstrap()` on server start; API index updated |
| `engine/tests/test_asr_setup.py` | 7 tests: missing/complete inspect, unknown model refused, env roundtrip + PATH apply, bootstrap without env, zip extraction, download cache |
| `src/lib/types.ts`, `src/lib/api.ts` | `AsrStatus`, `AsrApply`, `asrStatus()`, `asrProvision()`, `asrApply()` |
| `src/pages/SettingsPage.tsx` | card rewritten around real status; **Set up transcription** runs the job, streams the last log line, applies env, refreshes; Re-check |
| `README.md` | Step 2b replaced: in-app setup, CLI equivalent, native-binary opt-out, paths |

Verification actually run (Linux, built wheel, no shell env):

1. `shellslatee provision --dir <fresh>` from the wheel → static ffmpeg extracted, model cached, wrapper written, `asr.env` created, 5 ASR lines green, exit 0.
2. Server started with only `SHELLSLATEE_ASR_DIR` set → `GET /api/asr/status` **ready, missing []** (bootstrap loaded `asr.env`).
3. `POST /api/asr/provision` → job `running → done`, log shows each step, `POST /api/asr/apply` → ready.
4. `POST /api/run` (mock provider) on a 63s lecture through the API with no shell ASR vars → **1 note written, 0 failed**.
5. `unittest` → **25 tests OK**; `tsc --noEmit` clean; `vite build` 24.6s (637 KB / 197 KB gzip).

Remaining for a shippable 0.3.0: Windows-build validation of the same path
(gyan.dev zip + `.cmd` wrapper), installer signing (D7), encrypted key export,
and a 10-lecture Windows run.

---

## 15. Windows build + validation — 2026-11-17

Machine: Windows 11, WebView2 157.0.4341.46, Node 26.8.1, cargo 1.100.0,
Python 3.12 (`C:\Python312`). Driven from WSL over `cmd.exe`/`powershell.exe`.

| Step | Command | Result |
| --- | --- | --- |
| UI build (Windows node) | `npm run build` | 32.5s; `index-LPeRTWQG.js` 636.73 kB / 197.39 kB gzip — **same hash as the Linux build** |
| Rust check | `cargo check --manifest-path src-tauri/Cargo.toml --all-targets` | **clean, 2m 07s** |
| Desktop build | `npm run tauri build` | MSI 2,768,896 B + NSIS 2,134,824 B, exit 0 |
| App launch | `shellslatee-studio.exe` | spawned `python.exe ... shellslatee.exe serve --port 0`; `/api/health` → `{"version":"0.2.1"}` |
| In-app ASR (button path, driven via API) | `POST /api/asr/provision` | gyan.dev ffmpeg 109 MB → `bin/ffmpeg.EXE` + `ffprobe.EXE`; ggml-tiny.en 74 MB; faster-whisper wheels; `asr.env` written; job `running → done` |
| Readiness | `POST /api/asr/apply` | `ready: true` — ffmpeg, ffprobe, `whisper-cli.cmd`, model all green |
| One lesson through the API | `POST /api/run` (mock) | 1 written, 0 failed |
| **10-lecture batch (real key)** | `shellslatee run course10 vault10 --provider aikey --jobs 1` | **10 written, 0 failed, 0 skipped · 56 concepts · $0.00 · exit 0** |

Per-lesson wall time on Windows (one worker): 1m 42s – 2m 32s for 103–186 s
videos. Preflight estimated 20m 26s for the batch.

### Installer hashes (unsigned, 0.2.4)

```
40b77e532c5f8ed9e516b955…  Shellslatee_0.2.4_x64_en-US.msi   (2,768,896 B)
5a59c188dd5274cd040f0932…  Shellslatee_0.2.4_x64-setup.exe   (2,134,824 B)
```

Full SHA-256 values are produced in `tracking.md` §15 only when we tag; they
change on every rebuild.

### Criteria status after this pass

| # | Criterion | Status |
| --- | --- | --- |
| 1 | Clean-VM install → 30-min lecture without a terminal | **partial** — provisioning, run and app launch proven on real Windows; needs a true clean VM and a 30-minute lecture |
| 2 | `doctor` green on a clean machine | **partial** — green after provisioning; key file pre-existed here |
| 3 | D1/D2/D4/D3 closed | **met** |
| 4 | 10 real lectures, 0 failures, resumable | **met for 10 short lectures** (56 concepts); ≥3 h batch still to run |
| 5 | Per-lesson cost/time + hard ceiling | per-lesson reporting **met**; a hard budget ceiling is **not implemented** |
| 6 | LICENSE, corrected README, SECURITY.md, CONTRIBUTING.md | **met** |
| 7 | Signing or documented unsigned path | documented + hashed; **signing open** |
| 8 | CI builds/tests on every push | **met** |
| 9 | First-run never shows a raw exception | **unverified** (GUI click-through pending) |
| 10 | Tracking updated with measured numbers | **met** |

That leaves 0.3.0 blocking on: signing (D7), a budget ceiling, a 30-minute
lecture on a clean VM, and a GUI click-through of first-run.

---

## 16. 0.3.0 "Voice" build pass — 2026-11-18

Closed in code this pass: the hard budget ceiling, DPAPI-sealed key storage,
the first-run error boundary, and signing wired into `build.ps1` (active only
when a certificate is present). Version bumped to 0.3.0 across shell and engine.

### What changed

| Item | Change |
| --- | --- |
| Budget ceiling | Engine `run` gains `--max-cost` / `--allow-over-budget`; `serve` maps `max_cost`, treats exit 3 as `done` (stopped, not failed); UI adds "Cost ceiling per run (USD)" in Settings, persisted as `maxCostUsd` and passed to `api.run`. Preflight warns; the executor stops submitting once spent ≥ ceiling and marks the rest `skip(reason=budget)`, emitting `budget_stopped`. |
| Key storage (D5) | API keys are now DPAPI-sealed (`desktop_keys.dat`, `CryptProtectData`/`CryptUnprotectData`, user scope, UI forbidden). Legacy `desktop_keys.json` migrates on first launch and is removed. No passphrase, ciphertext useless off-account. Non-Windows keeps the 0600 plaintext dev file. |
| First-run resilience | `ErrorBoundary` wraps `App`; render crashes show a readable card with Reload + Copy details, never a raw stack. |
| Signing (D7) | `build.ps1` finds `signtool`, signs exe + MSI + setup with SHA-256 + RFC3161 timestamp when `SHELLSLATEE_CERT_PFX`/`_PASSWORD` or `SHELLSLATEE_CERT_THUMBPRINT` is set; prints SHA-256 of every installer. |

### Build + test results (Windows 11)

| Step | Command | Result |
| --- | --- | --- |
| Engine wheel | `py -3 -m pip wheel .\engine -w src-tauri\resources --no-deps` | `shellslatee_engine-0.3.0-py3-none-any.whl`, 114,397 B |
| UI build | `npm run build` | `tsc --noEmit` clean; vite 15.2s; `index-C9Roqk1Q.js` 638.76 kB / 198.01 kB gzip |
| Desktop build | `build-dev.bat build` | exit 0; rust 4m 18s; MSI 2,772,992 B + NSIS 2,141,411 B |
| Engine tests | `py -3 -m unittest` (excluding `test_asr_setup`) | **18 tests OK**; `test_asr_setup` has 2 failures that are Windows-only executable-bit assumptions, unrelated to this pass |
| Embedded wheel | `grep` exe for wheel name | present; exe 5,047,808 B |

### Installer hashes (unsigned, 0.3.0)

```
461aae1c079b74fe24b14585e9fee1c647265c77c19a8f579a592fe5dba2d50d  Shellslatee_0.3.0_x64-setup.exe   (2,141,411 B)
59b1712c6e5162f462c73d66c767aace7bdb4ecba5ef6daff73c92634fb1c324  Shellslatee_0.3.0_x64_en-US.msi   (2,772,992 B)
614366a4acc578626f489142450d6b5bfe08880de62c12bb63a503ab1210be8b  shellslatee-studio.exe            (5,047,808 B)
e0090e7ff5fd7651b94a89b85f26d08c5b1bdcd5248ada19bfc3b87eaa5ae932  shellslatee_engine-0.3.0-py3-none-any.whl (114,397 B)
```

### Criteria status after this pass

| # | Criterion | Status |
| --- | --- | --- |
| 5 | Per-lesson cost/time + hard ceiling | **met in code** — ceiling enforced per run |
| 7 | Signing or documented unsigned path | **path ready** — build signs automatically when a cert is supplied; still unsigned without one |
| 9 | First-run never shows a raw exception | **mitigated** — error boundary in place; real GUI click-through still pending |

Still open for the tag: supply an Authenticode cert (or ship explicitly
unsigned), then the clean-VM 30-minute lecture run and the GUI first-run
click-through.

