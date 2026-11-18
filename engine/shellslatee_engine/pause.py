"""Operator-controlled pause for a running job.

A run can be paused between items and between provider retries, then resumed
without losing progress: finished items are already in the resumable state, and
an item interrupted mid-request simply retries on resume.

Control is cooperative. The CLI installs ``SIGUSR1`` (pause) and ``SIGUSR2``
(resume) handlers; the API job runner sends those signals to the child process.
On platforms without those signals the controller still exposes the same API,
so callers stay portable.
"""

from __future__ import annotations

import signal
import threading

PAUSE_SIGNAL_NAME = "SIGUSR1"
RESUME_SIGNAL_NAME = "SIGUSR2"


class PauseController:
    """A thread-safe pause gate shared by every worker in a process."""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._paused = False

    @property
    def paused(self) -> bool:
        with self._cond:
            return self._paused

    def pause(self) -> bool:
        """Request a pause. Returns True when the state changed."""
        with self._cond:
            if self._paused:
                return False
            self._paused = True
            self._cond.notify_all()
            return True

    def resume(self) -> bool:
        """Release a pause. Returns True when the state changed."""
        with self._cond:
            if not self._paused:
                return False
            self._paused = False
            self._cond.notify_all()
            return True

    def wait_if_paused(self, poll: float | None = None) -> None:
        """Block while paused; return immediately when running.

        ``poll`` bounds each wait so a caller in a signal-driven process still
        observes state changes even if a notify is missed.
        """
        with self._cond:
            while self._paused:
                self._cond.wait(poll)


PAUSE = PauseController()


def _pause_handler(signum, frame) -> None:  # noqa: ARG001 - signal signature
    PAUSE.pause()


def _resume_handler(signum, frame) -> None:  # noqa: ARG001 - signal signature
    PAUSE.resume()


def install_signal_handlers(controller: PauseController = PAUSE) -> bool:
    """Attach pause/resume signals to the current process. Main thread only.

    Returns False when the platform has no user signals (e.g. Windows) or the
    caller is not on the main thread; callers can then rely on in-process
    ``controller.pause()`` instead.
    """
    pause_signal = getattr(signal, PAUSE_SIGNAL_NAME, None)
    resume_signal = getattr(signal, RESUME_SIGNAL_NAME, None)
    if pause_signal is None or resume_signal is None:
        return False
    if threading.current_thread() is not threading.main_thread():
        return False
    signal.signal(pause_signal, lambda signum, frame: controller.pause())
    signal.signal(resume_signal, lambda signum, frame: controller.resume())
    return True
