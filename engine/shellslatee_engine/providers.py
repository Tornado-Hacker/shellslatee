from __future__ import annotations

import http.client
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import keychain
from .pause import PAUSE

RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}
MAX_RETRIES = 3

# Set by the CLI to surface rate-limit pressure (provider, status, detail) in the
# event stream; the retry itself never depends on a hook being installed.
RATE_LIMIT_HOOK: Callable[[str, int, str], None] | None = None


class ProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    api_key_env: str | None
    default_model: str
    api_key_file: str | None = None
    prices_per_mtok: dict[str, tuple[float, float]] = field(default_factory=dict)


PRESETS: dict[str, Provider] = {
    "aikey": Provider(
        name="aikey",
        base_url=os.environ.get("AIKEY_BASE_URL", "https://tokenharbor.ai/v1"),
        api_key_env="AIKEY_API_KEY",
        api_key_file="~/.config/shellslatee/aikey_key",
        default_model="deepseek-v4.1-flash:free",
    ),
    "openrouter": Provider(
        name="openrouter",
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
        default_model="meta-llama/llama-3.3-70b-instruct:free",
        prices_per_mtok={
            "meta-llama/llama-3.3-70b-instruct:free": (0.0, 0.0),
            "google/gemini-2.0-flash-001": (0.10, 0.40),
            "anthropic/claude-3.5-haiku": (0.80, 4.00),
        },
    ),
    "openai": Provider(
        name="openai",
        base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        default_model="gpt-4o-mini",
        prices_per_mtok={"gpt-4o-mini": (0.15, 0.60), "gpt-4.1-mini": (0.40, 1.60)},
    ),
    "ollama": Provider(
        name="ollama",
        base_url="http://127.0.0.1:11434/v1",
        api_key_env=None,
        default_model="qwen2.5:7b-instruct",
    ),
    "mock": Provider(
        name="mock",
        base_url="",
        api_key_env=None,
        default_model="mock",
    ),
}


def resolve_provider(name: str, model: str | None = None) -> tuple[Provider, str, str]:
    provider = PRESETS.get(name)
    if provider is None:
        raise ProviderError(f"unknown provider: {name} (try: {', '.join(PRESETS)})")
    chosen = model or os.environ.get("SHELLSLATEE_MODEL") or provider.default_model
    api_key = ""
    if provider.api_key_env:
        # The app-managed key file wins so a stale shell export can't shadow it.
        if provider.api_key_file:
            try:
                api_key = Path(provider.api_key_file).expanduser().read_text(encoding="utf-8").strip()
            except OSError:
                api_key = ""
        if not api_key:
            api_key = keychain.get(provider.name) or ""
        if not api_key:
            api_key = os.environ.get(provider.api_key_env, "").strip()
        if not api_key:
            hint = f" or put it in {provider.api_key_file}" if provider.api_key_file else ""
            hint += " (or run `shellslatee keys set <provider>`)"
            raise ProviderError(
                f"{provider.api_key_env} is not set. Export it{hint}, or use --provider mock."
            )
    return provider, chosen, api_key


def estimate_cost(provider: Provider, model: str, tokens_in: int, tokens_out: int) -> float:
    prices = provider.prices_per_mtok.get(model)
    if not prices:
        return 0.0
    return (tokens_in / 1_000_000) * prices[0] + (tokens_out / 1_000_000) * prices[1]


def chat(
    provider: Provider,
    model: str,
    api_key: str,
    messages: list[dict[str, str]],
    *,
    json_mode: bool = True,
    temperature: float = 0.2,
    timeout: int = 180,
) -> tuple[str, dict[str, int]]:
    if provider.name == "mock":
        return mock_chat(messages)

    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    request = urllib.request.Request(
        f"{provider.base_url.rstrip('/')}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    last_error = ""
    for attempt in range(MAX_RETRIES + 1):
        # An operator pause holds here between attempts, including retries.
        PAUSE.wait_if_paused()
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            choices = payload.get("choices") or []
            if not choices:
                raise ProviderError("provider returned no choices")
            content = choices[0].get("message", {}).get("content") or ""
            usage = payload.get("usage") or {}
            tokens = {
                "in": int(usage.get("prompt_tokens", 0)),
                "out": int(usage.get("completion_tokens", 0)),
            }
            return content, tokens
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            last_error = f"HTTP {exc.code}: {detail}"
            if exc.code == 429 and RATE_LIMIT_HOOK is not None:
                try:
                    RATE_LIMIT_HOOK(provider.name, exc.code, detail)
                except Exception:  # noqa: BLE001 - a hook must never break a request
                    pass
            if exc.code not in RETRY_STATUS or attempt == MAX_RETRIES:
                raise ProviderError(f"{provider.name} request failed — {last_error}") from exc
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            delay = float(retry_after) if retry_after and retry_after.isdigit() else 2.0 ** attempt
            time.sleep(min(delay, 30.0))
            PAUSE.wait_if_paused()
        except (
            urllib.error.URLError,
            TimeoutError,
            json.JSONDecodeError,
            http.client.HTTPException,
            ConnectionError,
        ) as exc:
            last_error = str(exc)
            if attempt == MAX_RETRIES:
                raise ProviderError(f"{provider.name} request failed — {last_error}") from exc
            time.sleep(min(2.0 ** attempt, 30.0))
            PAUSE.wait_if_paused()

    raise ProviderError(f"{provider.name} request failed — {last_error}")


def mock_chat(messages: list[dict[str, str]]) -> tuple[str, dict[str, int]]:
    user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    title = "Untitled lesson"
    for line in user.splitlines():
        if line.lower().startswith("lesson title:"):
            title = line.split(":", 1)[1].strip() or title
            break

    stamps: list[tuple[str, str]] = []
    for line in user.splitlines():
        line = line.strip()
        if len(line) > 8 and line[0] == "[" and "] " in line:
            stamp = line[1 : line.index("]")]
            body = line[line.index("]") + 2 :].strip()
            if body:
                stamps.append((stamp, body))
        if len(stamps) >= 12:
            break
    if not stamps:
        stamps = [("00:00", "The lesson opens with the core idea.")]

    def pick(index: int) -> tuple[str, str]:
        return stamps[min(index, len(stamps) - 1)]

    topics = []
    for offset in range(0, min(len(stamps), 9), 3):
        stamp, body = pick(offset)
        topics.append(
            {
                "start": _stamp_to_seconds(stamp),
                "title": _clip(body, 60) or f"Topic at {stamp}",
                "details": [
                    _clip(body, 180),
                    "Worked through with a concrete example.",
                    "Trade-offs are named explicitly before moving on.",
                ],
            }
        )

    payload = {
        "title": title,
        "summary": (
            f"This lesson covers {title.lower()} and walks through the ideas in order. "
            "It builds from a simple statement of the problem toward a practical rule, "
            "naming the trade-offs along the way. The recording stays concrete: each "
            "claim is paired with an example so the summary can be checked against the source."
        ),
        "key_concepts": [
            {"name": "Core idea", "definition": "The single claim the lesson is built around."},
            {"name": "Worked example", "definition": "A concrete case that makes the idea checkable."},
            {"name": "Trade-offs", "definition": "What you gain and lose by applying the rule."},
            {"name": "Edge case", "definition": "The case where the naive application fails."},
        ],
        "topics": topics,
        "review_questions": [
            "State the core idea of this lesson in one sentence.",
            "Walk through the worked example without looking at the notes.",
            "Name one trade-off and when it would change your decision.",
            "Where does the naive approach break, and what fixes it?",
        ],
        "tags": ["lesson", "study"],
    }
    return json.dumps(payload), {"in": 0, "out": 0}


def _stamp_to_seconds(stamp: str) -> float:
    parts = stamp.split(":")
    try:
        numbers = [int(part) for part in parts]
    except ValueError:
        return 0.0
    if len(numbers) == 3:
        return float(numbers[0] * 3600 + numbers[1] * 60 + numbers[2])
    if len(numbers) == 2:
        return float(numbers[0] * 60 + numbers[1])
    return float(numbers[0]) if numbers else 0.0


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
