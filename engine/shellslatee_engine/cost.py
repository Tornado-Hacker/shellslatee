from __future__ import annotations

from .providers import Provider, estimate_cost

TOKENS_PER_MINUTE_IN = 200
TOKENS_PER_HOUR_OUT = 2000
NOTE_OVERHEAD_TOKENS = 400


def estimate(provider: Provider, model: str, durations: list[float]) -> dict[str, float]:
    minutes = sum(durations) / 60.0
    tokens_in = int(minutes * TOKENS_PER_MINUTE_IN) + int(len(durations) * NOTE_OVERHEAD_TOKENS)
    tokens_out = int((sum(durations) / 3600.0) * TOKENS_PER_HOUR_OUT) + len(durations) * 600
    usd = estimate_cost(provider, model, tokens_in, tokens_out)
    return {
        "lessons": float(len(durations)),
        "minutes": round(minutes, 1),
        "tokens_in": float(tokens_in),
        "tokens_out": float(tokens_out),
        "usd": round(usd, 4),
    }
