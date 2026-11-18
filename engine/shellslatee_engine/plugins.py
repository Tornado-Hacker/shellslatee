"""Plugin system: manifest discovery, an enable/disable registry, and hooks.

Two plugin kinds share one JSON protocol (``{"api", "hook", "plugin", "config"}``
in, ``{"markdown"|"value"}`` out):

- ``process`` — any executable the manifest names; the host pipes JSON on stdin
  and reads JSON from stdout. No shell, no third-party imports.
- ``wasm`` — a WASI command module run in-process through ``wasmtime`` when it
  is installed (``pip install shellslatee[plugins]``). The core stays dependency
  free: without the optional runtime the plugin reports a clear error instead of
  breaking the pipeline.

Plugins live at ``OUT/.shellslatee/plugins/<name>/plugin.json``; the registry at
``OUT/.shellslatee/plugins.json`` tracks enablement and per-plugin config. Hooks run
in stable name order so a vault output is deterministic across machines.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from .util import atomic_write, utc_now

PLUGIN_API = 1
MANIFEST_NAME = "plugin.json"
REGISTRY_NAME = "plugins.json"
PLUGINS_DIR = "plugins"

HOOK_NOTE_TRANSFORM = "note.transform"
KNOWN_HOOKS = frozenset({HOOK_NOTE_TRANSFORM})

KINDS = frozenset({"process", "wasm"})

MAX_IO_BYTES = 8 * 1024 * 1024
INVOKE_TIMEOUT = 30


class PluginError(RuntimeError):
    pass


# ---- paths ---------------------------------------------------------------


def plugins_root(out_root: Path) -> Path:
    return out_root / ".shellslatee" / PLUGINS_DIR


def registry_path(out_root: Path) -> Path:
    return out_root / ".shellslatee" / REGISTRY_NAME


# ---- manifest ------------------------------------------------------------


def _string(manifest: dict, key: str, *, required: bool = True) -> str:
    value = manifest.get(key)
    if value is None and not required:
        return ""
    if not isinstance(value, str) or not value.strip():
        raise PluginError(f"manifest field {key!r} must be a non-empty string")
    return value.strip()


def load_manifest(directory: Path) -> dict:
    """Read and validate one plugin manifest. Raises ``PluginError``."""
    path = directory / MANIFEST_NAME
    if not path.is_file():
        raise PluginError(f"missing {MANIFEST_NAME}")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PluginError(f"unreadable manifest: {exc}") from exc
    if not isinstance(manifest, dict):
        raise PluginError("manifest must be a JSON object")

    name = _string(manifest, "name")
    version = _string(manifest, "version")
    kind = _string(manifest, "kind").lower()
    if kind not in KINDS:
        raise PluginError(f"kind must be one of {sorted(KINDS)}")
    api = manifest.get("api", PLUGIN_API)
    if not isinstance(api, int) or api != PLUGIN_API:
        raise PluginError(f"unsupported api {api!r}; host speaks api {PLUGIN_API}")

    hooks = manifest.get("hooks")
    if not isinstance(hooks, list) or not hooks:
        raise PluginError("hooks must be a non-empty list")
    for hook in hooks:
        if hook not in KNOWN_HOOKS:
            raise PluginError(f"unknown hook {hook!r}")

    entry = _string(manifest, "entry")
    if kind == "wasm" and not entry.endswith(".wasm"):
        raise PluginError("wasm plugins need an .wasm entry")
    if not (directory / entry).is_file():
        raise PluginError(f"entry not found: {entry}")

    command = manifest.get("command")
    if command is not None and (
        not isinstance(command, list) or not all(isinstance(part, str) for part in command)
    ):
        raise PluginError("command must be a list of strings")

    config = manifest.get("config", {})
    if not isinstance(config, dict):
        raise PluginError("config must be an object")

    return {
        "name": name,
        "version": version,
        "kind": kind,
        "api": api,
        "entry": entry,
        "command": command,
        "hooks": hooks,
        "description": str(manifest.get("description", "")),
        "author": str(manifest.get("author", "")),
        "homepage": str(manifest.get("homepage", "")),
        "config": config,
    }


# ---- registry ------------------------------------------------------------


def _empty_registry() -> dict:
    return {"version": 1, "plugins": {}}


def load_registry(out_root: Path) -> dict:
    path = registry_path(out_root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _empty_registry()
    if not isinstance(payload, dict) or not isinstance(payload.get("plugins"), dict):
        return _empty_registry()
    return payload


def save_registry(out_root: Path, registry: dict) -> None:
    payload = {"version": 1, "plugins": registry.get("plugins", {})}
    atomic_write(registry_path(out_root), json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _entry(registry: dict, name: str) -> dict:
    plugins = registry.setdefault("plugins", {})
    entry = plugins.get(name)
    if not isinstance(entry, dict):
        entry = {}
        plugins[name] = entry
    entry.setdefault("enabled", False)
    entry.setdefault("config", {})
    return entry


# ---- discovery -----------------------------------------------------------


def discover(out_root: Path) -> list[dict]:
    """Every plugin directory, valid or not. ``valid``/``error`` explain state."""
    root = plugins_root(out_root)
    registry = load_registry(out_root)
    found: list[dict] = []
    if not root.is_dir():
        return found
    for directory in sorted(path for path in root.iterdir() if path.is_dir()):
        item = {
            "name": directory.name,
            "path": str(directory),
            "valid": False,
            "error": "",
            "enabled": False,
            "manifest": None,
        }
        try:
            manifest = load_manifest(directory)
            item["manifest"] = manifest
            item["name"] = manifest["name"]
            item["valid"] = True
        except PluginError as exc:
            item["error"] = str(exc)
        entry = (registry.get("plugins") or {}).get(item["name"])
        item["enabled"] = bool(entry and entry.get("enabled") and item["valid"])
        found.append(item)
    return found


def list_plugins(out_root: Path) -> list[dict]:
    rows: list[dict] = []
    for item in discover(out_root):
        manifest = item["manifest"] or {}
        rows.append(
            {
                "name": item["name"],
                "version": manifest.get("version", ""),
                "kind": manifest.get("kind", ""),
                "hooks": manifest.get("hooks", []),
                "description": manifest.get("description", ""),
                "enabled": item["enabled"],
                "valid": item["valid"],
                "error": item["error"],
                "path": item["path"],
            }
        )
    return rows


def find(out_root: Path, name: str) -> dict:
    for item in discover(out_root):
        if item["name"] == name:
            if not item["valid"]:
                raise PluginError(item["error"] or "invalid plugin")
            return item
    raise PluginError(f"plugin not found: {name}")


def set_enabled(out_root: Path, name: str, enabled: bool, config: dict | None = None) -> dict:
    plugin = find(out_root, name)  # validates it exists
    registry = load_registry(out_root)
    entry = _entry(registry, plugin["name"])
    entry["enabled"] = bool(enabled)
    if config is not None:
        if not isinstance(config, dict):
            raise PluginError("config must be an object")
        merged = dict(plugin["manifest"].get("config", {}))
        merged.update(config)
        entry["config"] = merged
    entry["updated"] = utc_now()
    save_registry(out_root, registry)
    return {"name": plugin["name"], "enabled": entry["enabled"], "config": entry.get("config", {})}


# ---- invocation ----------------------------------------------------------


def _plugin_config(manifest: dict, registry: dict) -> dict:
    entry = (registry.get("plugins") or {}).get(manifest["name"]) or {}
    config = dict(manifest.get("config", {}))
    config.update(entry.get("config") or {})
    return config


def _coerce_output(raw: bytes, plugin_name: str) -> dict:
    if len(raw) > MAX_IO_BYTES:
        raise PluginError(f"{plugin_name}: output exceeds {MAX_IO_BYTES} bytes")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise PluginError(f"{plugin_name}: invalid JSON output: {exc}") from exc
    if not isinstance(payload, dict):
        raise PluginError(f"{plugin_name}: output must be a JSON object")
    if payload.get("error"):
        raise PluginError(f"{plugin_name}: {payload['error']}")
    return payload


def _invoke_process(plugin: dict, payload: dict) -> dict:
    manifest = plugin["manifest"]
    directory = Path(plugin["path"])
    entry = directory / manifest["entry"]
    command = manifest.get("command")
    if command:
        argv = list(command)
    elif entry.suffix == ".py":
        argv = [sys.executable, str(entry)]
    elif entry.suffix in {".js", ".mjs", ".cjs"}:
        argv = ["node", str(entry)]
    elif entry.suffix == ".sh":
        argv = ["sh", str(entry)]
    else:
        argv = [str(entry)]
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    if len(raw) > MAX_IO_BYTES:
        raise PluginError(f"{manifest['name']}: input exceeds {MAX_IO_BYTES} bytes")
    try:
        completed = subprocess.run(
            argv,
            cwd=str(directory),
            input=raw,
            capture_output=True,
            timeout=INVOKE_TIMEOUT,
            check=False,
        )
    except FileNotFoundError as exc:
        raise PluginError(f"{manifest['name']}: command not found: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise PluginError(f"{manifest['name']}: timed out after {INVOKE_TIMEOUT}s") from exc
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", "replace").strip()[:500]
        raise PluginError(f"{manifest['name']}: exited {completed.returncode}: {detail}")
    return _coerce_output(completed.stdout, manifest["name"])


def _invoke_wasm(plugin: dict, payload: dict) -> dict:
    manifest = plugin["manifest"]
    try:
        import wasmtime  # type: ignore
    except ImportError as exc:  # pragma: no cover - exercised when runtime absent
        raise PluginError(
            f"{manifest['name']}: wasm runtime not installed (pip install 'shellslatee[plugins]')"
        ) from exc

    entry = Path(plugin["path"]) / manifest["entry"]
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    if len(raw) > MAX_IO_BYTES:
        raise PluginError(f"{manifest['name']}: input exceeds {MAX_IO_BYTES} bytes")

    with tempfile.TemporaryDirectory(prefix="shellslatee-wasm-") as workdir:
        stdin_path = Path(workdir) / "stdin.json"
        stdout_path = Path(workdir) / "stdout.json"
        stdin_path.write_bytes(raw)
        stdout_path.touch()
        try:
            engine = wasmtime.Engine()
            store = wasmtime.Store(engine)
            wasi = wasmtime.WasiConfig()
            wasi.stdin_file = str(stdin_path)
            wasi.stdout_file = str(stdout_path)
            wasi.stderr_file = str(Path(workdir) / "stderr.txt")
            store.set_wasi(wasi)
            linker = wasmtime.Linker(engine)
            linker.define_wasi()
            module = wasmtime.Module.from_file(engine, str(entry))
            instance = linker.instantiate(store, module)
            start = instance.exports(store).get("_start")
            if start is None:
                raise PluginError(f"{manifest['name']}: wasm module has no _start export")
            start(store)
        except PluginError:
            raise
        except Exception as exc:  # noqa: BLE001 - runtime errors vary by version
            raise PluginError(f"{manifest['name']}: wasm run failed: {exc}") from exc
        return _coerce_output(stdout_path.read_bytes(), manifest["name"])


def invoke(plugin: dict, hook: str, payload: dict, config: dict) -> dict:
    request = {
        "api": PLUGIN_API,
        "hook": hook,
        "plugin": plugin["manifest"]["name"],
        "config": config,
        "payload": payload,
    }
    if plugin["manifest"]["kind"] == "wasm":
        return _invoke_wasm(plugin, request)
    return _invoke_process(plugin, request)


# ---- hooks ---------------------------------------------------------------


def run_hook(out_root: Path, hook: str, payload: dict) -> list[tuple[str, dict]]:
    """Run every enabled plugin that declares ``hook`` in deterministic order."""
    if hook not in KNOWN_HOOKS:
        raise PluginError(f"unknown hook {hook!r}")
    registry = load_registry(out_root)
    results: list[tuple[str, dict]] = []
    for item in sorted(discover(out_root), key=lambda row: row["name"]):
        if not item["enabled"] or not item["valid"]:
            continue
        if hook not in item["manifest"]["hooks"]:
            continue
        config = _plugin_config(item["manifest"], registry)
        results.append((item["name"], invoke(item, hook, payload, config)))
    return results


def transform_note(
    out_root: Path, *, rel: str, title: str, module: str, markdown: str
) -> tuple[str, list[str]]:
    """Chain ``note.transform`` plugins over one note's Markdown."""
    applied: list[str] = []
    current = markdown
    payload = {"rel": rel, "title": title, "module": module, "markdown": current}
    for name, output in run_hook(out_root, HOOK_NOTE_TRANSFORM, payload):
        value = output.get("markdown")
        if value is None:
            continue
        if not isinstance(value, str):
            raise PluginError(f"{name}: markdown output must be a string")
        current = value
        applied.append(name)
        payload["markdown"] = current
    return current, applied


def apply_to_vault(out_root: Path) -> dict:
    """Run ``note.transform`` across the vault in place. Idempotency is the
    plugin's contract; transforms that depend on their own prior output should
    detect that in the note and no-op."""
    from .vault import collect

    records, _concepts = collect(out_root)
    changed = 0
    applied: set[str] = set()
    for record in records:
        path = out_root / record.lesson_rel
        if not path.is_file():
            continue
        original = path.read_text(encoding="utf-8", errors="replace")
        updated, names = transform_note(
            out_root,
            rel=record.lesson_rel,
            title=record.title,
            module=record.module,
            markdown=original,
        )
        if names:
            applied.update(names)
        if updated != original:
            atomic_write(path, updated)
            changed += 1
    return {"notes": len(records), "changed": changed, "plugins": sorted(applied)}


def validate(out_root: Path) -> list[dict]:
    rows: list[dict] = []
    for item in discover(out_root):
        rows.append(
            {
                "name": item["name"],
                "valid": item["valid"],
                "error": item["error"],
                "kind": (item["manifest"] or {}).get("kind", ""),
            }
        )
    return rows
