"""Optional OS keychain storage for provider API keys.

The app-managed key file stays the default because it works everywhere with no
desktop session.  When a real keychain is available this module stores the key
in the platform store instead of on disk in plaintext:

* Linux  -> ``secret-tool`` (libsecret / GNOME Keyring, KWallet bridge)
* macOS  -> ``security`` (login keychain)

Windows Credential Manager cannot be read non-interactively from the command
line, so Windows keeps the key-file/env path and reports no backend.  Every
function degrades to ``None``/``False`` rather than raising, so the provider
resolver can treat the keychain as a best-effort layer.
"""

from __future__ import annotations

import shutil
import subprocess

SERVICE = "shellslatee"
TIMEOUT = 15


def detect_backend() -> str | None:
    if shutil.which("secret-tool"):
        return "secret-tool"
    if shutil.which("security"):
        return "security"
    return None


def available() -> bool:
    return detect_backend() is not None


def _run(cmd: list[str], stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        input=stdin,
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )


def get(account: str) -> str | None:
    backend = detect_backend()
    if backend == "secret-tool":
        result = _run(["secret-tool", "lookup", "service", SERVICE, "account", account])
    elif backend == "security":
        result = _run(["security", "find-generic-password", "-s", SERVICE, "-a", account, "-w"])
    else:
        return None
    if result.returncode != 0:
        return None
    secret = result.stdout.strip()
    return secret or None


def set(account: str, secret: str) -> bool:
    backend = detect_backend()
    if backend == "secret-tool":
        result = _run(
            ["secret-tool", "store", "--label", f"{SERVICE} {account}",
             "service", SERVICE, "account", account],
            stdin=secret,
        )
        return result.returncode == 0
    if backend == "security":
        # `security` takes the secret on argv; it briefly shows in the process
        # table on the local machine. Accepted for the login-keychain workflow.
        result = _run(
            ["security", "add-generic-password", "-U",
             "-a", account, "-s", SERVICE, "-w", secret]
        )
        return result.returncode == 0
    return False


def delete(account: str) -> bool:
    backend = detect_backend()
    if backend == "secret-tool":
        result = _run(["secret-tool", "clear", "service", SERVICE, "account", account])
    elif backend == "security":
        result = _run(["security", "delete-generic-password", "-a", account, "-s", SERVICE])
    else:
        return False
    return result.returncode == 0


def backend_label() -> str:
    backend = detect_backend()
    if backend == "secret-tool":
        return "libsecret (secret-tool)"
    if backend == "security":
        return "macOS login keychain (security)"
    return "none (key file or environment)"
