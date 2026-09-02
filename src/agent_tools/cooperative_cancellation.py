"""Operation-scoped cooperative handling for first SIGINT delivery."""

from __future__ import annotations

import signal
import threading
from dataclasses import dataclass
from enum import Enum


class _ForceAbort(KeyboardInterrupt):
    """Carry a later interrupt through an active cancellation unchanged."""

    def __init__(self, interruption: KeyboardInterrupt) -> None:
        super().__init__("force-abort during cooperative cancellation")
        self.interruption = interruption


class _CancellationPhase(str, Enum):
    RUNNING = "running"
    CANCEL_REQUESTED = "cancel-requested"
    CANCELLING = "cancelling"
    FORCE_ABORTED = "force-aborted"


@dataclass
class _CancellationContext:
    """Own cancellation phase for one operation."""

    phase: _CancellationPhase = _CancellationPhase.RUNNING
    first_interruption: KeyboardInterrupt | None = None
    force_abort: _ForceAbort | None = None

    @property
    def requested(self) -> bool:
        return self.phase in {
            _CancellationPhase.CANCEL_REQUESTED,
            _CancellationPhase.CANCELLING,
        }

    def request(self, interruption: KeyboardInterrupt | None = None) -> None:
        """Record a signal request without raising into transaction code."""

        interruption = interruption or KeyboardInterrupt()
        if self.phase is _CancellationPhase.RUNNING:
            self.phase = _CancellationPhase.CANCEL_REQUESTED
            self.first_interruption = interruption
            return
        self._raise_force_abort(interruption)

    def checkpoint(self) -> bool:
        """Accept a pending request at a semantically safe boundary."""

        if self.phase is _CancellationPhase.CANCEL_REQUESTED:
            self.phase = _CancellationPhase.CANCELLING
        if self.phase is _CancellationPhase.FORCE_ABORTED:
            if self.force_abort is None:
                raise RuntimeError("force-aborted context has no carrier")
            raise self.force_abort
        return self.phase is _CancellationPhase.CANCELLING

    def _raise_force_abort(self, interruption: KeyboardInterrupt) -> None:
        if self.force_abort is None:
            self.force_abort = _ForceAbort(interruption)
        self.phase = _CancellationPhase.FORCE_ABORTED
        raise self.force_abort from interruption


class _SigintBroker:
    """Translate a supported first SIGINT into one cooperative request."""

    def __init__(
        self,
        cancellation: _CancellationContext,
        *,
        propagate_pending_on_exit: bool = False,
    ) -> None:
        self._cancellation = cancellation
        self._propagate_pending_on_exit = propagate_pending_on_exit
        self._previous: object | None = None
        self.installed = False

    @staticmethod
    def _supported_previous_handler(handler: object) -> bool:
        return handler is signal.SIG_DFL or handler is signal.default_int_handler

    def __enter__(self) -> _SigintBroker:
        if threading.current_thread() is not threading.main_thread():
            return self
        previous = signal.getsignal(signal.SIGINT)
        if isinstance(getattr(previous, "__self__", None), _SigintBroker):
            raise RuntimeError("managed SIGINT brokerage cannot be nested")
        if not self._supported_previous_handler(previous):
            return self
        self._previous = previous
        signal.signal(signal.SIGINT, self._handle)
        self.installed = True
        return self

    def _handle(self, signum: int, frame: object) -> None:
        del signum, frame
        self._cancellation.request(KeyboardInterrupt())

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        del exc, traceback
        consume_pending = (
            self.installed
            and exc_type is None
            and self._propagate_pending_on_exit
        )
        if self.installed:
            signal.signal(signal.SIGINT, self._previous)
            self.installed = False
        if consume_pending and self._cancellation.checkpoint():
            raise self._cancellation.first_interruption or KeyboardInterrupt()
