"""A compact FSRS-style spaced-repetition scheduler.

Deterministic, dependency-free, and easy to test. It uses the power forgetting
curve ``R(t, S) = (1 + FACTOR * t / S) ** DECAY`` with the standard ``19/81``
factor so that ``R(S, S) = 0.9``, and the FSRS-4.5 difficulty/stability update
equations with the published default weights. Grades:

    1 = again, 2 = hard, 3 = good, 4 = easy

This intentionally avoids claiming exact FSRS-5 parity; the shape is FSRS, the
weights are the 4.5 defaults, and every step is clamped so state can never go
negative or explode.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

DECAY = -0.5
FACTOR = 19.0 / 81.0
MIN_STABILITY = 0.1
MAX_INTERVAL_DAYS = 36_500
RELEARN_SECONDS = 600  # an "again" card returns this session

# FSRS-4.5 default parameters (w0..w16).
W = (
    0.4872, 1.4003, 3.7145, 13.8206, 5.1618, 1.2298, 0.8975, 0.031,
    1.6474, 0.1367, 1.0461, 2.1072, 0.0793, 0.3246, 1.587, 0.2272, 2.8755,
)

GRADES = {1: "again", 2: "hard", 3: "good", 4: "easy"}


@dataclass
class SchedulerState:
    stability: float = 0.0
    difficulty: float = 0.0
    reps: int = 0
    lapses: int = 0
    last_review: float = 0.0
    due_ts: float = 0.0


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def retrievability(elapsed_days: float, stability: float) -> float:
    if stability <= 0:
        return 0.0
    return (1.0 + FACTOR * max(0.0, elapsed_days) / stability) ** DECAY


def initial_stability(grade: int) -> float:
    return max(MIN_STABILITY, W[grade - 1])


def initial_difficulty(grade: int) -> float:
    return _clamp(W[4] - (grade - 3) * W[5], 1.0, 10.0)


def next_difficulty(difficulty: float, grade: int) -> float:
    target = initial_difficulty(4)
    update = difficulty - W[6] * (grade - 3)
    return _clamp(W[7] * target + (1.0 - W[7]) * update, 1.0, 10.0)


def next_stability_success(difficulty: float, stability: float, r: float, grade: int) -> float:
    hard_penalty = W[15] if grade == 2 else 1.0
    easy_bonus = W[16] if grade == 4 else 1.0
    growth = (
        math.exp(W[8])
        * max(0.01, 11.0 - difficulty)
        * (stability ** -W[9])
        * (math.exp((1.0 - r) * W[10]) - 1.0)
        * hard_penalty
        * easy_bonus
    )
    return max(MIN_STABILITY, stability * (1.0 + growth))


def next_stability_failure(difficulty: float, stability: float, r: float) -> float:
    value = (
        W[11]
        * (max(0.01, difficulty) ** -W[12])
        * (((stability + 1.0) ** W[13]) - 1.0)
        * math.exp((1.0 - r) * W[14])
    )
    return max(MIN_STABILITY, value)


def interval_days(stability: float, desired_retention: float = 0.9) -> int:
    retention = _clamp(desired_retention, 0.05, 0.99)
    days = stability / FACTOR * (retention ** (1.0 / DECAY) - 1.0)
    return int(_clamp(round(days), 1, MAX_INTERVAL_DAYS))


def schedule(state: SchedulerState, grade: int, now: float | None = None) -> tuple[SchedulerState, int]:
    """Return the next state and the interval in seconds for a review."""
    if grade not in GRADES:
        raise ValueError(f"grade must be one of {sorted(GRADES)}")
    now = time.time() if now is None else now

    if state.reps <= 0 or state.stability <= 0:
        stability = initial_stability(grade)
        difficulty = initial_difficulty(grade)
        reps = 1
        lapses = 1 if grade == 1 else 0
        interval_seconds = RELEARN_SECONDS if grade == 1 else interval_days(stability) * 86_400
        due_ts = now + interval_seconds
        return (
            SchedulerState(stability, difficulty, reps, lapses, now, due_ts),
            int(interval_seconds),
        )

    elapsed_days = max(0.0, (now - state.last_review) / 86_400)
    r = retrievability(elapsed_days, state.stability)
    difficulty = next_difficulty(state.difficulty, grade)

    if grade == 1:
        stability = next_stability_failure(state.difficulty, state.stability, r)
        lapses = state.lapses + 1
        interval_seconds = RELEARN_SECONDS
    else:
        stability = next_stability_success(state.difficulty, state.stability, r, grade)
        lapses = state.lapses
        interval_seconds = interval_days(stability) * 86_400

    due_ts = now + interval_seconds
    return (
        SchedulerState(stability, difficulty, state.reps + 1, lapses, now, due_ts),
        int(interval_seconds),
    )
