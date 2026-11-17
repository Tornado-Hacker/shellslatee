# Shellslatee

**Your lectures become memory — not another folder of PDFs you never open.**

Shellslatee is a local-first study cockpit for Windows (Linux and macOS build
from source). It turns your own lecture recordings, slides, and documents into
linked Markdown notes, flashcards, quizzes, a confusion heatmap, and a tutor
that cites the exact lesson and timestamp for every claim — then makes you
recall it before the exam does it for you.

Your notes stay as plain Markdown on your disk. Your API key stays in your
local config. No account, no sync server, no telemetry.

```
  ┌──────────────────────────────────────────────────────────────────┐
  │  Shellslatee                                    ⌘K  search…      │
  ├────────────┬─────────────────────────────────────────────────────┤
  │  Home      │  Today · 34 min planned                             │
  │  Library   │  ▸ 12 due cards        ▸ 3 weak concepts            │
  │  Study     │  ▸ explain-back: "Photosynthesis — light phase"     │
  │  Ask       │                                                     │
  │  Graph     │  Ask the whole course →  answers with source chips   │
  │  Settings  │                                                     │
  └────────────┴─────────────────────────────────────────────────────┘
```

---

## Contents

- [What it does](#what-it-does)
- [Install on Windows](#install-on-windows-end-users)
- [First run](#first-run--five-minutes)
- [Build from source](#build-from-source)
- [Command reference](#command-reference)
- [Where your data lives](#where-your-data-lives)
- [How the engine is found](#how-the-engine-is-found)
- [Troubleshooting](#troubleshooting)
- [Project layout](#project-layout)
- [Roadmap](#roadmap)

---

## What it does

| Feature | What it means for you |
| --- | --- |
| **Ingest anything** | MP4 / MKV / WebM, PPTX, DOCX, PDF, audio, and plain text all become timestamped lessons. |
| **Exam-date planner** | Tell it the exam date and your daily minutes. The home screen sizes today's plan around due cards, new material, and weak concepts. |
| **Explain-back coach** | Write the lesson in your own words. Get a verdict, the gaps you skipped, and one probing question — grounded in your notes, with citations. |
| **Confusion heatmap** | Cards you keep failing cluster by concept, ranked by weakness, one click into a drill session. |
| **Cited tutor** | Ask the whole course. Every claim carries a source chip that jumps to the lesson and timestamp. |
| **Bring your own key** | Any OpenAI-compatible provider. Keys are stored locally, never sent anywhere but the provider you chose. |
| **Local-first** | Notes are Markdown. Vault is a folder. Copy it, back it up, open it in Obsidian if you like. |

---

## Install on Windows (end users)

### What you need

| Piece | Why | Where |
| --- | --- | --- |
| Windows 10 21H2+ or 11, x64 | Runs the app | — |
| WebView2 Runtime | Renders the UI | Preinstalled on Windows 11; [evergreen installer](https://developer.microsoft.com/microsoft-edge/webview2/) on 10 |
| Python 3.10+ (optional) | Runs the local engine | The app can download and install it for you — only tick *Add python.exe to PATH* if installing manually |
| An API key | Powers notes, quizzes, tutor | Any OpenAI-compatible provider |

### Step 1 — Install the app

Download the installer from
[**Releases**](https://github.com/Tornado-Hacker/shellslatee/releases):

- `Shellslatee_0.2.4_x64-setup.exe` — recommended (per-user, no admin needed)
- `Shellslatee_0.2.4_x64_en-US.msi` — for managed / enterprise installs

Run it. SmartScreen will warn because the build is unsigned — choose
**More info → Run anyway**.

The setup wizard opens with a **Notes folder** page. Keep the suggested
`%USERPROFILE%\Shellslatee Notes`, type another path, or use **Browse** to pick
a parent — the folder name stays `Shellslatee Notes`. Setup creates it and
checks that it is writable; if Windows Defender *Controlled folder access*
blocks the location, it falls back to the profile so setup still completes.
Uninstalling never deletes your notes.

### Step 2 — Let the app install the engine

Start **Shellslatee**. On first launch it checks two things and shows a short
setup card:

| Piece | What happens |
| --- | --- |
| Python 3.10+ | Found automatically. If missing, the app offers to download the official Python installer (per-user, no admin). |
| Local engine | **Bundled inside the installer** — installing it takes seconds, no download. |

Tick **"Install the missing software for me"** and press the button. The app
downloads Python only if it has to, installs the bundled engine wheel, restarts
the engine, and walks you into setup. One click, no terminal.

<details>
<summary>Prefer the command line?</summary>

Download the engine wheel from [Releases](https://github.com/Tornado-Hacker/shellslatee/releases)
and install it yourself:

```powershell
python -m pip install --user --upgrade .\shellslatee_engine-0.2.0-py3-none-any.whl
```

The engine is not on PyPI yet — install the wheel from the release.

</details>

### Step 3 — Launch

Start **Shellslatee** from the Start menu. The window opens, the app spawns
`shellslatee serve` on a random loopback port, and the title bar shows the engine
status. First launch walks you through:

1. **Add a key** — pick a provider, paste the key, hit **Test**.
2. **Point at your course** — optionally pick the folder with your videos and
   slides. The notes folder is already set by the installer; change it later
   under **Settings → Vault**.
3. **Drop a lecture** — an MP4, PPTX, or PDF. That's the fastest way to see the
   whole pipeline work.

---

## First run — five minutes

| Step | Do this | You should see |
| --- | --- | --- |
| 1 | **Settings → Provider** → paste key → **Test** | `… accepted the key — test completion ran.` |
| 2 | **Settings → Vault** → keep the installer's folder or pick another | Vault path shown; engine restarts automatically |
| 3 | **Library → Capture** → drop `lecture.mp4` or `slides.pdf` | A job appears, then a lesson with a transcript/outline |
| 4 | Open the lesson → **Study** | Flashcards and quiz generated from the source |
| 5 | **Home** → set exam date and daily minutes | Today's plan with due cards and weak concepts |
| 6 | **Ask** → "explain the light reactions like I'm behind" | Answer with clickable source chips |
| 7 | **Study → Explain back** → write the lesson yourself | Verdict, gaps, one probing question |

**Back up your keys before you reinstall Windows.** Settings → *Export keys*
writes an encrypted file you can restore on the new machine. The config folder
itself is listed [below](#where-your-data-lives).

---

## Build from source

### Prerequisites

| Tool | Version | Notes |
| --- | --- | --- |
| Node.js | 20+ | `npm ci` fetches the Tauri CLI for your platform |
| Rust | stable, `x86_64-pc-windows-msvc` | [rustup.rs](https://rustup.rs) |
| Visual Studio Build Tools | 2022, **Desktop development with C++** | Includes MSVC + Windows SDK |
| Git | any | |

No-admin Rust install (works when you cannot run installers as admin):

```powershell
winget install --id Microsoft.VisualStudio.2022.BuildTools -e `
  --override "--quiet --wait --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
Invoke-WebRequest https://win.rustup.rs/x86_64 -OutFile rustup-init.exe
.\rustup-init.exe -y --default-toolchain stable-x86_64-pc-windows-msvc --profile minimal
```

### Clone and build

```powershell
git clone https://github.com/Tornado-Hacker/shellslatee.git
cd shellslatee
npm ci
```

If `cargo` is not on `PATH`, use the wrapper — it loads vcvars and prepends
`%USERPROFILE%\.cargo\bin` for you:

```powershell
.\build-dev.bat check     # fast type/compile check
.\build-dev.bat dev       # run the app with hot reload
.\build-dev.bat build     # produce installers
```

Or with cargo already on `PATH`:

```powershell
npm run dev               # UI only in a browser, no Tauri bridge
npx tauri dev             # full desktop app with hot reload
.\build.ps1               # release build + installers
.\build.ps1 -DebugBuild   # debug build, faster, no bundling
```

Installers land in:

```
src-tauri/target/release/bundle/msi/Shellslatee_<version>_x64_en-US.msi
src-tauri/target/release/bundle/nsis/Shellslatee_<version>_x64-setup.exe
```

### Build the engine wheel yourself

The engine lives in its own repository. To produce the wheel the installer
expects:

```powershell
git clone <engine-repo> shellslatee-engine
python -m pip wheel .\shellslatee-engine --no-deps -w dist-engine
python -m pip install --user --upgrade .\dist-engine\shellslatee_engine-0.2.0-py3-none-any.whl
```

---

## Command reference

| Command | What it does |
| --- | --- |
| `npm run dev` | Vite dev server on `:1420` — UI only, browser mode, no engine spawning |
| `npx tauri dev` | Full desktop app, hot reload, engine spawned by Rust |
| `npm run build` | Type-check (`tsc --noEmit`) then production web bundle into `dist/` |
| `npm run tauri build` | Release desktop build + MSI/NSIS installers |
| `npm run tauri info` | Toolchain versions and dependencies Tauri detects |
| `.\build.ps1` | Windows release build wrapper (installers) |
| `.\build.ps1 -DebugBuild` | Windows debug build wrapper |
| `.\build-dev.bat check` | `cargo check` with the VS environment loaded |
| `.\build-dev.bat build` | `tauri build` with the VS environment loaded |
| `.\build-dev.bat dev` | `tauri dev` with the VS environment loaded |

Engine commands (when running it directly):

| Command | What it does |
| --- | --- |
| `shellslatee serve --port 0` | Start the local API on a random free port (what the app does) |
| `shellslatee serve --port 8677` | Fixed port, useful when the browser UI needs a known origin |
| `shellslatee --help` | Engine subcommands (ingest, build, serve, …) |

Environment variables read by the desktop shell:

| Variable | Effect |
| --- | --- |
| `SHELLSLATEE_BIN` | Full path to a `shellslatee` executable — highest priority |
| `SHELLSLATEE_REPO` | Engine repo root; app runs `python -m shellslatee_engine` there |
| `SHELLSLATEE_URL` | Dev only: proxy target for the Vite dev server |

---

## Where your data lives

| What | Path |
| --- | --- |
| Notes / vault | `%USERPROFILE%\Shellslatee Notes\` — chosen in the setup wizard, changeable in **Settings → Vault** |
| Notes-folder marker | `%USERPROFILE%\.config\shellslatee\notes_dir.txt` |
| Installer log | `%USERPROFILE%\.config\shellslatee\install.log` |
| Provider keys | `%USERPROFILE%\.config\shellslatee\desktop_keys.json` |
| AI Key mirror | `%USERPROFILE%\.config\shellslatee\aikey_key` |
| App config | `%USERPROFILE%\.config\shellslatee\desktop.json` |

### Upgrading from an earlier build

Builds before the rename used a different bundle identifier, so the installer
does not upgrade in place. Uninstall the earlier app from *Apps & features*
once the new one opens correctly, then delete the leftover
`%USERPROFILE%\.config\` folder from that build if you do not want the old
key file on disk.

---

## How the engine is found

On launch, in order:

1. `SHELLSLATEE_BIN` — full path to a `shellslatee` executable.
2. `SHELLSLATEE_REPO` — repo root; the app runs `python -m shellslatee_engine` there.
3. User-script roots:
   - `%APPDATA%\Python\*\Scripts\shellslatee.exe`
   - `%LOCALAPPDATA%\Programs\Python\*\Scripts\shellslatee.exe`
   - `~/.local/bin/shellslatee`
4. `shellslatee` on `PATH`.

This is why `pip install --user` works without touching `PATH`: GUI processes
rarely inherit the user-script directory.

The app starts `shellslatee serve --port 0`, reads the loopback URL the engine
prints on stderr, proxies every API call through Rust (no CORS, no open port
to the LAN), and kills the child on exit. Saving a key restarts the engine with
the provider's environment variable set.

---

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `could not start the local engine` | Engine not installed or not discoverable | Install the wheel, or set `SHELLSLATEE_BIN` to `…\Scripts\shellslatee.exe` |
| `the engine did not report a loopback URL in time` | Engine crashed on start — usually a bad key or missing dependency | Run `shellslatee serve --port 8677` in a terminal and read the traceback |
| `engine is unreachable` after an update | Stale spawn after the port died | Settings → *Restart engine* |
| Window is blank / unstyled | WebView2 missing or outdated | Install the WebView2 evergreen runtime |
| `npm ci` fails on Windows | Postinstall scripts blocked by npm policy | `npm install --ignore-scripts` then `npx tauri --version` |
| `cargo` not recognized | Rust not on `PATH` for this shell | Use `build-dev.bat`, or add `%USERPROFILE%\.cargo\bin` |
| `link.exe not found` | MSVC environment not loaded | Run from *x64 Native Tools Command Prompt*, or use `build-dev.bat` |
| SmartScreen blocks the installer | Build is unsigned | **More info → Run anyway**, or configure a signing certificate |
| Notes folder was not created | Windows Defender *Controlled folder access* blocked `Documents` | The app falls back to `%USERPROFILE%\Shellslatee Notes`; check `install.log`, or allow Shellslatee under **Ransomware protection → Allow an app through Controlled folder access** |
| Setup never asked for a folder | You ran the MSI or a silent `/S` install | Use `Shellslatee_0.2.4_x64-setup.exe`; silent installs use the profile default by design |
| Port `1420` already in use | Another vite instance | Kill it, or set `VITE_PORT` and update `devUrl` in `tauri.conf.json` |
| Scanned PDF produces no text | PDF is images, no text layer | OCR is on the roadmap for 0.4.0; meanwhile convert with an OCR tool first |

Logs:

```powershell
# engine stderr is captured by the app; for a raw view run it directly
shellslatee serve --port 8677
# web bundle / build logs
npm run build
```

---

## Project layout

```
shellslatee/
├── index.html                 entry document
├── package.json               web side + Tauri CLI scripts
├── build.ps1                  Windows release wrapper
├── build-dev.bat              vcvars + cargo wrapper (no PATH setup needed)
├── src/
│   ├── App.tsx                splash → onboarding → connection → routed shell
│   ├── components/            sidebar, top bar, command palette, capture,
│   │                          onboarding, connection screen, markdown
│   ├── lib/                   Tauri bridge, API client, zustand store, types
│   └── pages/                 Home, Library, Note, Study, Ask, Graph, Settings
└── src-tauri/
    ├── Cargo.toml             crate `shellslatee-studio`
    ├── tauri.conf.json        window, bundle, identifier
    ├── capabilities/          Tauri v2 permission grants
    └── src/main.rs            engine lifecycle, key storage, API proxy
```

---

## Roadmap

| Version | Focus |
| --- | --- |
| 0.2.4 | Current — setup wizard picks the notes folder; engine lifecycle, key storage, study loop |
| 0.3.0 | Signed installers, multi-hour sessions with real models |
| 0.4.0 | Scanned-PDF OCR, richer slide-note extraction |
| 1.0.0 | Plugin marketplace, publishable adapter API |

---

## Notes and caveats

- The shell is **not standalone** — it spawns the Python engine on launch.
  For a single-file installer, freeze the engine with PyInstaller and point
  `SHELLSLATEE_BIN` at the result.
- Installers are unsigned until certificates are configured.
- The graph view computes a force layout in the renderer; very large vaults
  (500+ lessons) take a moment to settle.
- Licence: TBD — add a `LICENSE` file before distributing publicly.
