"""One-command provisioning of the local transcription stack (defect D1).

The engine shells out to `ffmpeg`, `ffprobe` and a whisper binary and needs a
ggml model path. None of that can ship inside a signed installer, so the app
downloads it into a per-user directory on first setup:

    <target>/bin/ffmpeg[.exe]        static build
    <target>/bin/ffprobe[.exe]       same archive
    <target>/bin/whisper-cli[.cmd]   real binary, or a wrapper over faster-whisper
    <target>/models/ggml-<size>.bin  whisper.cpp model
    <target>/asr.env                 the two variables the engine reads

`bootstrap()` loads `asr.env` at startup so a provisioned directory keeps
working across restarts without the user touching PATH.
"""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

TARGET_ENV = "SHELLSLATEE_ASR_DIR"
MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{size}.bin"
FFMPEG_URLS = {
    "nt": "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
    "linux": "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz",
    "darwin": "https://evermeet.cx/ffmpeg/getrelease/zip",
}
FFPROBE_URLS = {"darwin": "https://evermeet.cx/ffmpeg/getrelease/ffprobe/zip"}
MODEL_SIZES = ("tiny.en", "base.en", "small.en", "medium.en", "tiny", "base", "small")
SHIM_ASSET = Path(__file__).with_name("data") / "whisper-cli-faster.py"
EXE = ".exe" if os.name == "nt" else ""
Log = Callable[[str], None]


def log_stderr(message: str) -> None:
    print(f"[asr] {message}", file=sys.stderr, flush=True)


def default_dir() -> Path:
    override = os.environ.get(TARGET_ENV)
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "Shellslatee" / "asr"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Shellslatee" / "asr"
    return Path.home() / ".local" / "share" / "shellslatee" / "asr"


def bin_dir(target: Path) -> Path:
    return target / "bin"


def model_path(target: Path, size: str) -> Path:
    return target / "models" / f"ggml-{size}.bin"


def whisper_wrapper(target: Path) -> Path:
    return bin_dir(target) / ("whisper-cli.cmd" if os.name == "nt" else "whisper-cli")


def inspect(target: Path | None = None) -> dict:
    root = Path(target or default_dir()).expanduser()
    tools = {name: bin_dir(root) / (name + EXE) for name in ("ffmpeg", "ffprobe")}
    wrapper = whisper_wrapper(root)
    models = sorted((root / "models").glob("ggml-*.bin")) if (root / "models").is_dir() else []
    present = {
        "ffmpeg": tools["ffmpeg"].is_file(),
        "ffprobe": tools["ffprobe"].is_file(),
        "whisper": wrapper.is_file() or bool(shutil.which("whisper-cli")),
        "models": [path.name for path in models],
    }
    missing = [name for name in ("ffmpeg", "ffprobe") if not present[name]]
    if not present["whisper"]:
        missing.append("whisper")
    if not models:
        missing.append("model")
    return {
        "target": str(root),
        "bin": str(bin_dir(root)),
        "present": present,
        "missing": missing,
        "has_env": (root / "asr.env").is_file(),
    }


def plan(size: str = "tiny.en", target: Path | None = None) -> list[dict[str, str]]:
    if size not in MODEL_SIZES:
        raise ValueError(f"unknown model {size!r}; pick one of {', '.join(MODEL_SIZES)}")
    platform_key = "nt" if os.name == "nt" else sys.platform
    ffmpeg = FFMPEG_URLS.get(platform_key)
    if not ffmpeg:
        raise ValueError(f"no ffmpeg build configured for {platform_key}")
    root = Path(target or default_dir()).expanduser()
    steps = [{"id": "ffmpeg", "url": ffmpeg, "dest": str(bin_dir(root))}]
    if platform_key == "darwin":
        steps.append({"id": "ffprobe", "url": FFPROBE_URLS["darwin"], "dest": str(bin_dir(root))})
    steps.append(
        {
            "id": "model",
            "url": MODEL_URL.format(size=size),
            "dest": str(model_path(root, size)),
        }
    )
    return steps


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, dest: Path, log: Log = log_stderr) -> Path:
    if dest.is_file() and dest.stat().st_size > 0:
        log(f"cached {dest.name} ({dest.stat().st_size // 1_048_576} MB)")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_name(dest.name + ".part")
    log(f"download {url}")
    try:
        with urllib.request.urlopen(url, timeout=120) as response, partial.open("wb") as out:
            shutil.copyfileobj(response, out, length=1 << 20)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    partial.replace(dest)
    log(f"saved {dest.name} ({dest.stat().st_size // 1_048_576} MB, sha256 {_sha256(dest)[:12]}…)")
    return dest


def _extract_binaries(archive: Path, wanted: set[str], dest: Path) -> dict[str, Path]:
    """Find named executables anywhere in a zip or tar and copy them flat."""
    dest.mkdir(parents=True, exist_ok=True)
    found: dict[str, Path] = {}

    def place(name: str, payload) -> None:
        stem = name[:-4] if name.endswith(".exe") else name
        if stem not in wanted:
            return
        target = dest / (stem + EXE)
        with target.open("wb") as out:
            shutil.copyfileobj(payload, out)
        if os.name != "nt":
            target.chmod(0o755)
        found[stem] = target

    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.namelist():
                base = Path(member).name
                if base.endswith((".exe",)) or base in wanted:
                    with bundle.open(member) as src:
                        place(base, src)
    else:
        with tarfile.open(archive) as bundle:
            for member in bundle.getmembers():
                if not member.isfile():
                    continue
                base = Path(member.name).name
                if base in wanted:
                    src = bundle.extractfile(member)
                    if src is not None:
                        with src:
                            place(base, src)
    return found


def _install_ffmpeg(target: Path, size: str, force: bool, log: Log) -> None:
    tools = {"ffmpeg", "ffprobe"}
    have = {name for name in tools if (bin_dir(target) / (name + EXE)).is_file()}
    if have == tools and not force:
        log("ffmpeg already present")
        return
    cache = target / "cache"
    platform_key = "nt" if os.name == "nt" else sys.platform
    archive = FFMPEG_URLS[platform_key]
    suffix = ".zip" if archive.endswith(".zip") else ".tar.xz"
    saved = download(archive, cache / f"ffmpeg{suffix}", log)
    found = _extract_binaries(saved, tools, bin_dir(target))
    if platform_key == "darwin" and "ffprobe" not in found:
        probe = download(FFPROBE_URLS["darwin"], cache / "ffprobe.zip", log)
        found.update(_extract_binaries(probe, {"ffprobe"}, bin_dir(target)))
    missing = tools - set(found)
    if missing:
        raise RuntimeError(f"ffmpeg archive did not contain: {', '.join(sorted(missing))}")
    log("ffmpeg + ffprobe installed")


def _install_whisper(target: Path, log: Log, force: bool = False) -> tuple[str, Path]:
    if not force:
        existing = os.environ.get("SHELLSLATEE_WHISPER_BIN") or shutil.which("whisper-cli")
        if existing and Path(existing).is_file():
            log(f"native whisper binary kept: {existing}")
            return "native", Path(existing)

    wrapper = whisper_wrapper(target)
    shim_dir = target / "shim"
    shim_dir.mkdir(parents=True, exist_ok=True)
    shim = shim_dir / "whisper-cli-faster.py"
    if not SHIM_ASSET.is_file():
        raise RuntimeError(f"shim asset missing from the installed package: {SHIM_ASSET}")
    shim.write_text(SHIM_ASSET.read_text(encoding="utf-8"), encoding="utf-8")

    python = sys.executable
    try:
        subprocess.run(
            [python, "-c", "import faster_whisper"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, OSError):
        log("installing faster-whisper (one time, ~180 MB of wheels)")
        subprocess.run(
            [
                python,
                "-m",
                "pip",
                "install",
                "--quiet",
                "--disable-pip-version-check",
                "--no-warn-script-location",
                "faster-whisper",
                "numpy",
            ],
            check=True,
        )

    if os.name == "nt":
        wrapper.write_text(
            f'@echo off\r\n"{python}" "%~dp0..\\shim\\whisper-cli-faster.py" %*\r\n',
            encoding="utf-8",
        )
    else:
        wrapper.write_text(
            f'#!/bin/sh\nexec "{python}" "{shim}" "$@"\n',
            encoding="utf-8",
        )
        wrapper.chmod(0o755)
    log(f"whisper wrapper written: {wrapper}")
    return "shim", wrapper


def write_env(target: Path, whisper_bin: Path | None = None) -> Path:
    path = target / "asr.env"
    rows = {
        "SHELLSLATEE_WHISPER_BIN": str(whisper_bin or whisper_wrapper(target)),
        "SHELLSLATEE_WHISPER_MODEL": str(next(iter(sorted((target / "models").glob("ggml-*.bin"))), "")),
        "SHELLSLATEE_FFMPEG_DIR": str(bin_dir(target)),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{key}={value}\n" for key, value in rows.items()), encoding="utf-8")
    return path


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def apply_env(target: Path | None = None) -> dict[str, str]:
    """Load a provisioned directory into this process (env + PATH)."""
    root = Path(target or default_dir()).expanduser()
    values = read_env(root / "asr.env")
    for key, value in values.items():
        if value:
            os.environ[key] = value
    ffmpeg_dir = values.get("SHELLSLATEE_FFMPEG_DIR") or str(bin_dir(root))
    if Path(ffmpeg_dir).is_dir():
        parts = os.environ.get("PATH", "").split(os.pathsep)
        if ffmpeg_dir not in parts:
            os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
    return values


def bootstrap(log: Log | None = None) -> dict[str, str]:
    """Startup hook: pick up a previously provisioned directory, if any."""
    values = apply_env()
    if values and log:
        log(f"asr: using {values.get('SHELLSLATEE_WHISPER_MODEL', 'provisioned stack')}")
    return values


def install(
    target: Path | None = None,
    *,
    size: str = "tiny.en",
    force: bool = False,
    log: Log = log_stderr,
) -> dict:
    root = Path(target or default_dir()).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    log(f"target {root} on {platform.system()} {platform.machine()}")
    _install_ffmpeg(root, size, force, log)
    model = download(MODEL_URL.format(size=size), model_path(root, size), log)
    backend, whisper_bin = _install_whisper(root, log, force=force)
    env_file = write_env(root, whisper_bin)
    apply_env(root)
    log(f"wrote {env_file}")
    from . import doctor

    return {
        "target": str(root),
        "backend": backend,
        "model": str(model),
        "env": read_env(env_file),
        "checks": doctor.checks(),
        "ready": doctor.ready(),
    }

