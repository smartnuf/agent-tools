"""Explicit, bounded execution of immutable provider plans."""

from __future__ import annotations

import codecs
from decimal import Decimal, InvalidOperation
import math
import ntpath
import os
import posixpath
import re
import select
import signal
import shutil
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from pathlib import PurePosixPath, PureWindowsPath

from .capabilities import (
    Availability,
    CapabilitySpec,
    CapabilityState,
    MachineState,
    ProviderState,
    acceptable_provider_executables,
    current_machine,
    detect_capability,
    get_capability,
)
from .provider_plans import (
    EnvironmentRefresh,
    ExecutionPrivilege,
    PackageManagerState,
    ProviderAction,
    ProviderPlan,
    adapter_commands,
    adapter_environment_refresh,
    adapter_environment_path_entries,
    adapter_execution_privilege,
    PlanningError,
    validate_capability_state,
)
from .python_selection import NativeStatus, normalize_architecture


DEFAULT_COMMAND_TIMEOUT_SECONDS = 300
MAX_COMMAND_TIMEOUT_SECONDS = 999_999_999
MAX_COMMAND_TIMEOUT_FRACTION_DIGITS = 6
MIN_PROCESS_RETURNCODE = -(2**31)
MAX_PROCESS_RETURNCODE = (2**32) - 1
MAX_CAPTURED_OUTPUT_CHARS = 1024 * 1024
OUTPUT_TRUNCATION_MARKER = "[earlier output truncated]\n"
ELEVATED_TERM_TO_KILL_GRACE_SECONDS = 5
ELEVATED_SUPERVISOR_GUARD_SECONDS = 10
OUTPUT_PIPE_CLOSURE_GUARD_SECONDS = 1
POSIX_SIGKILL_RETURNCODE = -9
_ENVIRONMENT_LOCK = threading.RLock()
_EXECUTION_LOCK = threading.RLock()
_TIMEOUT_TOKEN = re.compile(
    rf"(?:0\.\d{{1,{MAX_COMMAND_TIMEOUT_FRACTION_DIGITS}}}|"
    rf"[1-9]\d{{0,8}}(?:\.\d{{1,{MAX_COMMAND_TIMEOUT_FRACTION_DIGITS}}})?)s"
)


class ExecutionContractError(RuntimeError):
    """Raised before mutation when a plan is stale or not catalogue-authoritative."""


class UncertainSupervisionError(ExecutionContractError):
    """Raised when observable post-exit evidence prevents a quiescence claim."""

    def __init__(
        self,
        result: subprocess.CompletedProcess[str],
        detail: str = (
            "the synchronous supervisor exited, but inherited output remained open; "
            "descendant or package-related activity may still be running, Agent Tools "
            "could not establish quiescence, and provider/package state is uncertain"
        ),
        *,
        timed_out: bool = False,
    ) -> None:
        super().__init__(detail)
        self.result = result
        self.detail = detail
        self.timed_out = timed_out


class CommandLifecycleError(ExecutionContractError):
    """Carry evidence for a failure after process creation succeeded."""

    def __init__(
        self,
        result: subprocess.CompletedProcess[str],
        detail: str,
        *,
        lifetime_uncertain: bool,
        timed_out: bool = False,
    ) -> None:
        super().__init__(detail)
        self.result = result
        self.detail = detail
        self.lifetime_uncertain = lifetime_uncertain
        self.timed_out = timed_out


class _ControlledCancellation(KeyboardInterrupt):
    """Base class for structured evidence carrying the first cancellation."""


class CommandInterruptedError(ExecutionContractError):
    """Carry post-start evidence from one cooperative cancellation checkpoint."""

    def __init__(
        self,
        result: subprocess.CompletedProcess[str],
        detail: str = "provider command interrupted after bounded cleanup",
        *,
        lifetime_uncertain: bool = False,
    ) -> None:
        super().__init__(detail)
        self.result = result
        self.detail = detail
        self.lifetime_uncertain = lifetime_uncertain


class _ForceAbort(KeyboardInterrupt):
    """Carry a later interrupt through an active cancellation unchanged."""

    def __init__(self, interruption: KeyboardInterrupt) -> None:
        super().__init__("force-abort during provider cancellation")
        self.interruption = interruption


class _CancellationPhase(str, Enum):
    RUNNING = "running"
    CANCEL_REQUESTED = "cancel-requested"
    CANCELLING = "cancelling"
    FORCE_ABORTED = "force-aborted"


@dataclass
class _CancellationContext:
    """Own cancellation phase for one provider operation."""

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
    """Translate supported first SIGINT into one cooperative request."""

    def __init__(self, cancellation: _CancellationContext) -> None:
        self._cancellation = cancellation
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
        del exc_type, exc, traceback
        if self.installed:
            signal.signal(signal.SIGINT, self._previous)
            self.installed = False


class ProviderPlanInterrupted(_ControlledCancellation):
    """Carry structured attempted-mutation evidence through interruption."""

    def __init__(self, report: PlanExecutionReport) -> None:
        super().__init__("provider plan interrupted after bounded cleanup")
        self.report = report
        self.managed_result: object | None = None


class _ProviderPartialReport(RuntimeError):
    """Internal control flow for returning evidence after a later preflight fails."""

    def __init__(self, report: PlanExecutionReport) -> None:
        super().__init__("provider execution produced a partial report")
        self.report = report


class PlanOutcome(str, Enum):
    NO_CHANGES = "no-changes"
    REFUSED = "refused"
    SUCCEEDED = "succeeded"
    PARTIAL_FAILURE = "partial-failure"
    PREFLIGHT_FAILED = "preflight-failed"


class ActionOutcome(str, Enum):
    REFUSED = "refused"
    NOT_ATTEMPTED = "not-attempted"
    ALREADY_SATISFIED = "already-satisfied"
    SUCCEEDED = "succeeded"
    MANAGER_UNAVAILABLE = "manager-unavailable"
    PRIVILEGE_UNAVAILABLE = "privilege-unavailable"
    PREFLIGHT_FAILED = "preflight-failed"
    COMMAND_FAILED = "command-failed"
    COMMAND_START_FAILED = "command-start-failed"
    TIMED_OUT = "timed-out"
    FORCED_KILL = "forced-kill"
    SUPERVISOR_FAILED = "supervisor-failed"
    INTERRUPTED = "interrupted"
    VERIFICATION_FAILED = "verification-failed"


@dataclass(frozen=True)
class CommandReport:
    argv: tuple[str, ...]
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool = False


@dataclass(frozen=True)
class ActionReport:
    capability_id: str
    provider_id: str
    manager: str
    installation_unit: str
    outcome: ActionOutcome
    commands: tuple[CommandReport, ...] = ()
    final_verified_paths: tuple[str, ...] = ()
    detail: str = ""
    target_architecture: str | None = None
    displaces_verified_paths: tuple[str, ...] = ()
    translated_manager_fallback_authorized: bool = False
    satisfied_by_provider_id: str | None = None


@dataclass(frozen=True)
class PlanExecutionReport:
    context: MachineState | None
    requested_capabilities: tuple[str, ...]
    outcome: PlanOutcome
    actions: tuple[ActionReport, ...]
    recovery_guidance: tuple[str, ...] = ()


TimeoutSeconds = int | float
Runner = Callable[[tuple[str, ...], TimeoutSeconds], subprocess.CompletedProcess[str]]
Detector = Callable[[CapabilitySpec, MachineState], CapabilityState]
ContextReader = Callable[[], MachineState]
ManagerVerifier = Callable[[PackageManagerState, MachineState], bool]
ManagerArchitectureReader = Callable[[PackageManagerState], str | None]
PrivilegeResolver = Callable[[ProviderAction], str | None]
SupervisorResolver = Callable[[ProviderAction], str | None]
PrivilegePreflight = Callable[[tuple[str, ...]], bool]
EnvironmentRefresher = Callable[[ProviderAction], Mapping[str, str]]


def _normalized_context(machine: MachineState) -> MachineState:
    return MachineState(
        machine.platform,
        normalize_architecture(machine.architecture),
        machine.execution_environment,
    )


def _path_key(path: str, machine: MachineState) -> str:
    if machine.platform == "Windows":
        return ntpath.normcase(ntpath.normpath(path))
    return posixpath.normpath(path)


def _path_is_absolute(path: str, machine: MachineState) -> bool:
    return (
        PureWindowsPath(path).is_absolute()
        if machine.platform == "Windows"
        else PurePosixPath(path).is_absolute()
    )


def _raise_post_start_error(
    argv: tuple[str, ...],
    process: subprocess.Popen[str],
    stdout_tail: _BoundedOutputTail,
    stderr_tail: _BoundedOutputTail,
    error: Callable[[subprocess.CompletedProcess[str]], BaseException],
) -> None:
    """Materialize post-start evidence after cooperative signal capture."""

    raise error(_started_process_result(argv, process, stdout_tail, stderr_tail))


def _started_process_result(
    argv: tuple[str, ...],
    process: subprocess.Popen[str],
    stdout_tail: _BoundedOutputTail,
    stderr_tail: _BoundedOutputTail,
) -> subprocess.CompletedProcess[str]:
    """Snapshot bounded evidence for a process whose launch is established."""

    return subprocess.CompletedProcess(
        argv,
        process.returncode,
        stdout_tail.value(),
        stderr_tail.value(),
    )


def _run(
    argv: tuple[str, ...],
    timeout: TimeoutSeconds,
    *,
    privileged_supervision: bool = False,
    _cancellation: _CancellationContext | None = None,
) -> subprocess.CompletedProcess[str]:
    cancellation = _cancellation or _CancellationContext()
    process_options: dict[str, object]
    if os.name == "nt":
        process_options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    else:
        process_options = {"start_new_session": True}
    stdout_tail = _BoundedOutputTail(MAX_CAPTURED_OUTPUT_CHARS)
    stderr_tail = _BoundedOutputTail(MAX_CAPTURED_OUTPUT_CHARS)
    stop_readers = threading.Event()
    reader_errors: list[OSError] = []
    started_readers: list[threading.Thread] = []
    # Keep creation outside the post-start boundary: only this operation can prove
    # that no provider process was launched.
    process = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **process_options,
    )
    try:
        return _supervise_started_process(
            process,
            argv,
            timeout,
            privileged_supervision,
            stdout_tail,
            stderr_tail,
            stop_readers,
            reader_errors,
            started_readers,
            cancellation,
        )
    except _ForceAbort:
        raise
    except CommandLifecycleError as error:
        cleanup_established = _best_effort_started_process_cleanup(
            process,
            privileged_supervision,
            tuple(started_readers),
            stop_readers,
            reader_errors,
            cancellation,
        )
        lifetime_uncertain = not cleanup_established
        _raise_post_start_error(
            argv,
            process,
            stdout_tail,
            stderr_tail,
            lambda result: CommandLifecycleError(
                result,
                error.detail,
                lifetime_uncertain=lifetime_uncertain,
                timed_out=error.timed_out,
            ),
        )
    except CommandInterruptedError as error:
        raise
    except OSError as error:
        cleanup_established = _best_effort_started_process_cleanup(
            process,
            privileged_supervision,
            tuple(started_readers),
            stop_readers,
            reader_errors,
            cancellation,
        )
        lifetime_uncertain = not cleanup_established
        _raise_post_start_error(
            argv,
            process,
            stdout_tail,
            stderr_tail,
            lambda result: CommandLifecycleError(
                result,
                (
                    "provider command launched, but post-start lifecycle handling "
                    f"failed: {error}"
                ),
                lifetime_uncertain=lifetime_uncertain,
            ),
        )


def _best_effort_started_process_cleanup(
    process: subprocess.Popen[str],
    privileged_supervision: bool,
    readers: tuple[threading.Thread, ...],
    stop_readers: threading.Event,
    reader_errors: list[OSError],
    cancellation: _CancellationContext,
) -> bool:
    """Return whether process and pipe quiescence were established after failure."""

    process_quiesced = process.returncode is not None
    if not process_quiesced:
        try:
            if privileged_supervision:
                _terminate_privileged_supervisor(process)
            else:
                _terminate_process_tree(process)
        except Exception:
            process_quiesced = False
        else:
            process_quiesced = process.returncode is not None
    stop_readers.set()
    try:
        readers_clean = _join_output_readers(
            readers, stop_readers, reader_errors, cancellation
        )
    except Exception:
        readers_clean = False
    handles_clean = True
    for stream in (process.stdout, process.stderr):
        if stream is None:
            continue
        try:
            stream.close()
        except ValueError:
            pass
        except OSError:
            handles_clean = False
    return process_quiesced and readers_clean and handles_clean


def _supervise_started_process(
    process: subprocess.Popen[str],
    argv: tuple[str, ...],
    timeout: TimeoutSeconds,
    privileged_supervision: bool,
    stdout_tail: _BoundedOutputTail,
    stderr_tail: _BoundedOutputTail,
    stop_readers: threading.Event,
    reader_errors: list[OSError],
    started_readers: list[threading.Thread],
    cancellation: _CancellationContext,
) -> subprocess.CompletedProcess[str]:
    """Supervise a process whose launch is already established as fact."""

    readers: tuple[threading.Thread, ...]
    try:
        readers = _start_output_readers(
            process, stdout_tail, stderr_tail, stop_readers, reader_errors
        )
        started_readers.extend(readers)
    except Exception as error:
        if isinstance(error, _OutputReaderInitializationError):
            started_readers.extend(error.started_readers)
        _cleanup_reader_initialization_failure(
            process,
            argv,
            privileged_supervision,
            stdout_tail,
            stderr_tail,
            stop_readers,
            reader_errors,
            error,
            cancellation,
        )
        raise AssertionError("reader initialization cleanup must raise")
    try:
        deadline = time.monotonic() + timeout
        while True:
            if cancellation.checkpoint():
                try:
                    if privileged_supervision:
                        _terminate_privileged_supervisor(process)
                    else:
                        _terminate_process_tree(process)
                except (ExecutionContractError, OSError) as error:
                    stop_readers.set()
                    _join_output_readers(
                        readers, stop_readers, reader_errors, cancellation
                    )
                    raise CommandInterruptedError(
                        _started_process_result(
                            argv, process, stdout_tail, stderr_tail
                        ),
                        (
                            "provider command cancellation was accepted after launch, "
                            f"but termination or reaping failed: {error}"
                        ),
                        lifetime_uncertain=True,
                    ) from error
                readers_clean = _join_output_readers(
                    readers, stop_readers, reader_errors, cancellation
                )
                raise CommandInterruptedError(
                    _started_process_result(
                        argv, process, stdout_tail, stderr_tail
                    ),
                    lifetime_uncertain=not readers_clean,
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(argv, timeout)
            try:
                process.wait(timeout=min(0.1, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
    except CommandInterruptedError:
        raise
    except subprocess.TimeoutExpired:
        try:
            if privileged_supervision:
                _terminate_privileged_supervisor(process)
            else:
                _terminate_process_tree(process)
        except OSError as error:
            lifetime_uncertain = process.returncode is None
            _raise_post_start_error(
                argv,
                process,
                stdout_tail,
                stderr_tail,
                lambda result: CommandLifecycleError(
                    result,
                    (
                        "provider command launched and exceeded its timeout, but "
                        f"termination or reaping failed: {error}"
                    ),
                    lifetime_uncertain=lifetime_uncertain,
                    timed_out=True,
                ),
            )
        except ExecutionContractError:
            _join_output_readers(
                readers, stop_readers, reader_errors, cancellation
            )
            detail = (
                "privileged supervisor termination could not be established; "
                "privileged package-related activity may still be running, Agent "
                "Tools could not establish quiescence, and provider/package state "
                "is uncertain"
            )
            _raise_post_start_error(
                argv,
                process,
                stdout_tail,
                stderr_tail,
                lambda result: UncertainSupervisionError(
                    result, detail, timed_out=True
                ),
            )
        if not _join_output_readers(
            readers, stop_readers, reader_errors, cancellation
        ):
            _raise_post_start_error(
                argv,
                process,
                stdout_tail,
                stderr_tail,
                lambda result: UncertainSupervisionError(
                    result, timed_out=True
                ),
            )
        _raise_post_start_error(
            argv,
            process,
            stdout_tail,
            stderr_tail,
            lambda result: subprocess.TimeoutExpired(
                argv,
                timeout,
                output=result.stdout,
                stderr=result.stderr,
            ),
        )
    if not _join_output_readers(
        readers, stop_readers, reader_errors, cancellation
    ):
        _raise_post_start_error(
            argv,
            process,
            stdout_tail,
            stderr_tail,
            lambda result: UncertainSupervisionError(result),
        )
    return _started_process_result(argv, process, stdout_tail, stderr_tail)


def _start_output_readers(
    process: subprocess.Popen[str],
    stdout_tail: _BoundedOutputTail,
    stderr_tail: _BoundedOutputTail,
    stop: threading.Event,
    errors: list[OSError],
) -> tuple[threading.Thread, ...]:
    readers: list[threading.Thread] = []
    for stream, tail, name in (
        (process.stdout, stdout_tail, "provider-output-stdout"),
        (process.stderr, stderr_tail, "provider-output-stderr"),
    ):
        reader = None
        try:
            reader = threading.Thread(
                target=_drain_output,
                args=(stream, tail, stop, errors),
                daemon=True,
                name=name,
            )
            reader.start()
        except Exception as error:
            started_readers = tuple(readers)
            if reader is not None and reader.ident is not None:
                started_readers += (reader,)
            raise _OutputReaderInitializationError(
                started_readers, error
            ) from error
        readers.append(reader)
    return tuple(readers)


class _OutputReaderInitializationError(RuntimeError):
    def __init__(
        self,
        started_readers: tuple[threading.Thread, ...],
        error: BaseException,
    ) -> None:
        super().__init__(str(error))
        self.started_readers = started_readers
        self.error = error


def _cleanup_reader_initialization_failure(
    process: subprocess.Popen[str],
    argv: tuple[str, ...],
    privileged_supervision: bool,
    stdout_tail: _BoundedOutputTail,
    stderr_tail: _BoundedOutputTail,
    stop: threading.Event,
    errors: list[OSError],
    error: BaseException,
    cancellation: _CancellationContext,
) -> None:
    initialization_error = (
        error.error if isinstance(error, _OutputReaderInitializationError) else error
    )
    _finish_reader_initialization_cleanup(
        process,
        argv,
        privileged_supervision,
        stdout_tail,
        stderr_tail,
        stop,
        errors,
        error,
        initialization_error,
        cancellation,
    )


def _finish_reader_initialization_cleanup(
    process: subprocess.Popen[str],
    argv: tuple[str, ...],
    privileged_supervision: bool,
    stdout_tail: _BoundedOutputTail,
    stderr_tail: _BoundedOutputTail,
    stop: threading.Event,
    errors: list[OSError],
    error: BaseException,
    initialization_error: BaseException,
    cancellation: _CancellationContext,
) -> None:
    started_readers = (
        error.started_readers
        if isinstance(error, _OutputReaderInitializationError)
        else ()
    )
    termination_failed = False
    try:
        if privileged_supervision:
            _terminate_privileged_supervisor(process)
        else:
            _terminate_process_tree(process)
    except (ExecutionContractError, OSError):
        termination_failed = True
    stop.set()
    readers_clean = _join_output_readers(
        started_readers, stop, errors, cancellation
    )
    for stream in (process.stdout, process.stderr):
        with suppress(OSError, ValueError):
            if stream is not None:
                stream.close()
    detail = (
        "output reader initialization failed after the command may have started"
    )
    if termination_failed or not readers_clean:
        _raise_post_start_error(
            argv,
            process,
            stdout_tail,
            stderr_tail,
            lambda result: UncertainSupervisionError(
                result,
                (
                    f"{detail}; termination or local reader cleanup could not "
                    "establish quiescence, and provider/package state is uncertain"
                ),
            ),
        )
    _raise_post_start_error(
        argv,
        process,
        stdout_tail,
        stderr_tail,
        lambda result: CommandLifecycleError(
            result,
            (
                f"{detail}; the process was terminated and reaped, but it may have "
                "mutated state before cleanup"
            ),
            lifetime_uncertain=False,
        ),
    )


def _uncertain_output_error(
    argv: tuple[str, ...],
    returncode: int | None,
    stdout_tail: _BoundedOutputTail,
    stderr_tail: _BoundedOutputTail,
    detail: str | None = None,
    *,
    timed_out: bool = False,
) -> UncertainSupervisionError:
    result = subprocess.CompletedProcess(
        argv,
        returncode,
        stdout_tail.value(),
        stderr_tail.value(),
    )
    return (
        UncertainSupervisionError(result, detail, timed_out=timed_out)
        if detail is not None
        else UncertainSupervisionError(result, timed_out=timed_out)
    )


class _BoundedOutputTail:
    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._chunks: deque[str] = deque()
        self._size = 0
        self._truncated = False

    def append(self, chunk: str) -> None:
        self._chunks.append(chunk)
        self._size += len(chunk)
        while self._size > self._limit and self._chunks:
            overflow = self._size - self._limit
            first = self._chunks[0]
            if len(first) <= overflow:
                self._chunks.popleft()
                self._size -= len(first)
            else:
                self._chunks[0] = first[overflow:]
                self._size -= overflow
            self._truncated = True

    def value(self) -> str:
        value = "".join(self._chunks)
        if self._truncated:
            return OUTPUT_TRUNCATION_MARKER + value
        return value


def _drain_output(
    stream,
    tail: _BoundedOutputTail,
    stop: threading.Event,
    errors: list[OSError],
) -> None:
    if stream is None:
        return
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    try:
        while not stop.is_set():
            if not _pipe_ready(stream):
                stop.wait(0.01)
                continue
            chunk = stream.read1(8192)
            if not chunk:
                break
            tail.append(decoder.decode(chunk))
    except OSError as error:
        errors.append(error)
    finally:
        tail.append(decoder.decode(b"", final=True))
        with suppress(OSError, ValueError):
            stream.close()


def _pipe_ready(stream) -> bool:
    if os.name != "nt":
        ready, _, _ = select.select((stream,), (), (), 0.05)
        return bool(ready)
    import ctypes
    import msvcrt

    available = ctypes.c_ulong()
    handle = msvcrt.get_osfhandle(stream.fileno())
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    succeeded = kernel32.PeekNamedPipe(
        ctypes.c_void_p(handle),
        None,
        0,
        None,
        ctypes.byref(available),
        None,
    )
    if succeeded:
        return bool(available.value)
    error = ctypes.get_last_error()
    if error == 109:  # ERROR_BROKEN_PIPE: one final read observes EOF.
        return True
    raise OSError(error, "PeekNamedPipe failed")


def _join_output_readers(
    readers: tuple[threading.Thread, ...],
    stop: threading.Event,
    errors: list[OSError],
    cancellation: _CancellationContext | None = None,
) -> bool:
    """Return whether output closed cleanly within the synchronous guard."""

    cancellation = cancellation or _CancellationContext()
    deadline = time.monotonic() + OUTPUT_PIPE_CLOSURE_GUARD_SECONDS
    try:
        for reader in readers:
            while True:
                if cancellation.phase is _CancellationPhase.CANCEL_REQUESTED:
                    cancellation.checkpoint()
                    stop.set()
                    return False
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                reader.join(timeout=min(0.1, remaining))
                if not reader.is_alive():
                    break
    except Exception:
        stop.set()
        for reader in readers:
            reader.join(timeout=1)
        return False
    if cancellation.phase is _CancellationPhase.CANCEL_REQUESTED:
        cancellation.checkpoint()
        stop.set()
        return False
    if not any(reader.is_alive() for reader in readers):
        return not errors
    stop.set()
    for reader in readers:
        reader.join(timeout=1)
    return False


def _terminate_privileged_supervisor(process: subprocess.Popen[str]) -> None:
    """Ask sudo/timeout to terminate from the privileged side and confirm exit."""

    try:
        process.terminate()
    except ProcessLookupError:
        pass
    try:
        process.wait(
            timeout=(
                ELEVATED_TERM_TO_KILL_GRACE_SECONDS
                + ELEVATED_SUPERVISOR_GUARD_SECONDS
            )
        )
    except subprocess.TimeoutExpired as error:
        raise ExecutionContractError(
            "privileged supervisor termination could not be established"
        ) from error


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    """Terminate and reap the isolated command process tree."""

    if os.name == "nt":
        system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
        taskkill = system_root / "System32" / "taskkill.exe"
        try:
            resolved_taskkill = taskkill.resolve(strict=True)
            result = subprocess.run(
                (
                    str(resolved_taskkill),
                    "/PID",
                    str(process.pid),
                    "/T",
                    "/F",
                ),
                check=False,
                capture_output=True,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            process.kill()
            process.wait()
            raise ExecutionContractError(
                f"could not terminate timed-out Windows process tree: {error}"
            ) from error
        if result.returncode != 0 and process.poll() is None:
            process.kill()
            process.wait()
            raise ExecutionContractError(
                "could not terminate timed-out Windows process tree: "
                + result.stderr.decode(errors="replace")
            )
        process.wait()
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def _detect(capability: CapabilitySpec, machine: MachineState) -> CapabilityState:
    return detect_capability(capability, machine)


def _verify_manager(state: PackageManagerState, machine: MachineState) -> bool:
    path = Path(state.executable_path)
    try:
        if not path.is_file():
            return False
        resolved = str(path.resolve(strict=True))
    except OSError:
        return False
    expected = state.resolved_executable_path or state.executable_path
    if _path_key(resolved, machine) != _path_key(expected, machine):
        return False
    return state.installation_root is None or Path(state.installation_root).is_dir()


def _read_manager_architecture(state: PackageManagerState) -> str | None:
    if state.manager != "brew":
        return state.architecture
    executable = state.executable_path
    environment = {**os.environ, "HOMEBREW_NO_AUTO_UPDATE": "1"}
    try:
        result = subprocess.run(
            (executable, "ruby", "-e", "puts Hardware::CPU.arch"),
            check=False,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=10,
            env=environment,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return lines[-1] if result.returncode == 0 and lines else None


def _resolve_privilege(action: ProviderAction) -> str | None:
    if action.execution_privilege is ExecutionPrivilege.CURRENT_USER:
        return ""
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        return ""
    sudo = shutil.which("sudo")
    return sudo if sudo and Path(sudo).is_absolute() else None


def _resolve_supervisor(action: ProviderAction) -> str | None:
    if (
        action.execution_privilege is not ExecutionPrivilege.SYSTEM
        or os.name == "nt"
    ):
        return ""
    candidate = shutil.which("timeout")
    if not candidate or not Path(candidate).is_absolute():
        return None
    try:
        resolved = Path(candidate).resolve(strict=True)
        result = subprocess.run(
            (str(resolved), "--version"),
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0 or "GNU coreutils" not in result.stdout:
        return None
    return str(resolved)


def _preflight_privilege(argv: tuple[str, ...]) -> bool:
    if len(argv) < 4 or argv[1:3] != ("-n", "--"):
        return True
    try:
        result = subprocess.run(
            (argv[0], "-n", "-l", "--", *argv[3:]),
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _elevated_argv(
    reviewed_argv: tuple[str, ...],
    *,
    elevation: str,
    supervisor: str,
    timeout_seconds: TimeoutSeconds,
) -> tuple[str, ...]:
    supervised = (
        supervisor,
        "--signal=TERM",
        f"--kill-after={ELEVATED_TERM_TO_KILL_GRACE_SECONDS}s",
        _format_timeout_seconds(timeout_seconds),
        *reviewed_argv,
    )
    return (elevation, "-n", "--", *supervised) if elevation else supervised


def _validate_timeout_seconds(value: object) -> TimeoutSeconds:
    """Return a supported timeout without accepting bool or non-finite values."""

    if type(value) not in {int, float}:
        raise ValueError("timeout_seconds must be an exact integer or float")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("timeout_seconds must be finite")
    decimal = Decimal(str(value))
    if decimal <= 0 or decimal > MAX_COMMAND_TIMEOUT_SECONDS:
        raise ValueError(
            f"timeout_seconds must be positive and at most {MAX_COMMAND_TIMEOUT_SECONDS}"
        )
    if decimal.as_tuple().exponent < -MAX_COMMAND_TIMEOUT_FRACTION_DIGITS:
        raise ValueError(
            "timeout_seconds supports at most "
            f"{MAX_COMMAND_TIMEOUT_FRACTION_DIGITS} fractional digits"
        )
    return value


def _format_timeout_seconds(value: TimeoutSeconds) -> str:
    """Serialize one validated timeout in the canonical GNU duration grammar."""

    value = _validate_timeout_seconds(value)
    decimal = Decimal(str(value))
    rendered = format(decimal, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return f"{rendered}s"


def _is_canonical_timeout_token(value: object) -> bool:
    """Recognize exactly the bounded duration language emitted by the writer."""

    if not isinstance(value, str) or _TIMEOUT_TOKEN.fullmatch(value) is None:
        return False
    numeric = value[:-1]
    try:
        decimal = Decimal(numeric)
    except InvalidOperation:
        return False
    if decimal <= 0 or decimal > MAX_COMMAND_TIMEOUT_SECONDS:
        return False
    rendered = format(decimal, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return value == f"{rendered}s"


def _windows_persisted_path() -> str:
    if os.name != "nt":
        return os.environ.get("PATH", "")
    import winreg

    values: list[str] = []
    keys = (
        (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
        (winreg.HKEY_CURRENT_USER, r"Environment"),
    )
    for hive, key_name in keys:
        try:
            with winreg.OpenKey(hive, key_name) as key:
                value, _ = winreg.QueryValueEx(key, "Path")
        except OSError:
            continue
        if isinstance(value, str) and value:
            values.append(os.path.expandvars(value))
    current = os.environ.get("PATH", "")
    if current:
        values.append(current)
    return os.pathsep.join(values)


def _refresh_environment(action: ProviderAction) -> Mapping[str, str]:
    if action.environment_refresh is EnvironmentRefresh.NONE:
        return {}
    if action.environment_refresh is EnvironmentRefresh.PATH:
        return {"PATH": _windows_persisted_path()}
    if action.environment_refresh is EnvironmentRefresh.MANAGER_BIN:
        if not action.environment_path_entries:
            raise ExecutionContractError(
                "manager-bin refresh has no reviewed executable-search path"
            )
        current = os.environ.get("PATH", "")
        prefix = os.pathsep.join(action.environment_path_entries)
        return {"PATH": prefix + (os.pathsep + current if current else "")}
    raise ExecutionContractError(
        f"unsupported environment refresh: {action.environment_refresh}"
    )


def _restore_environment(previous: Mapping[str, str | None]) -> None:
    for name, value in previous.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


def _apply_environment(updates: Mapping[str, str]) -> None:
    """Apply a known set of environment updates one entry at a time."""

    for name, value in updates.items():
        os.environ[name] = value


@contextmanager
def _temporary_environment(
    updates: Mapping[str, str], cancellation: _CancellationContext
):
    del cancellation
    with _ENVIRONMENT_LOCK:
        previous = {name: os.environ.get(name) for name in updates}
        try:
            _apply_environment(updates)
            yield
        except _ForceAbort:
            raise
        except BaseException:
            _restore_environment(previous)
            raise
        else:
            _restore_environment(previous)


@contextmanager
def _refreshed_environment(
    action: ProviderAction,
    refresher: EnvironmentRefresher,
    cancellation: _CancellationContext,
):
    """Compute and apply a temporary refresh under one process-wide lock."""

    with _ENVIRONMENT_LOCK:
        with _temporary_environment(refresher(action), cancellation):
            yield


def _validate_action(action: ProviderAction, context: MachineState) -> None:
    try:
        capability = get_capability(action.capability_id)
    except KeyError as error:
        raise ExecutionContractError(
            f"unknown action capability: {action.capability_id}"
        ) from error
    provider = next(
        (item for item in capability.providers if item.provider_id == action.provider_id),
        None,
    )
    if provider is None or not provider.supports(context) or not provider.satisfies_capability:
        raise ExecutionContractError(
            f"action provider is not catalogue-supported: {action.provider_id}"
        )
    package = next(
        (
            item
            for item in provider.packages
            if item.manager == action.manager
            and item.installation_unit == action.installation_unit
            and context.platform in item.platforms
            and (
                not item.architectures
                or normalize_architecture(context.architecture) in item.architectures
            )
        ),
        None,
    )
    if package is None:
        raise ExecutionContractError(
            f"action package is not catalogue-owned: {action.installation_unit}"
        )
    if action.manager_state.execution_environment != context.execution_environment:
        raise ExecutionContractError("action package manager is from another environment")
    if not _path_is_absolute(action.manager_state.executable_path, context) or (
        action.manager_state.resolved_executable_path is not None
        and not _path_is_absolute(action.manager_state.resolved_executable_path, context)
    ):
        raise ExecutionContractError("action package-manager identity is not absolute")
    expected_commands = adapter_commands(
        action.manager,
        action.installation_unit,
        executable_path=action.manager_state.executable_path,
        target_architecture=action.target_architecture,
    )
    if action.commands != expected_commands:
        raise ExecutionContractError("action commands do not match the reviewed adapter")
    if action.execution_privilege is not adapter_execution_privilege(action.manager):
        raise ExecutionContractError("action privilege does not match the reviewed adapter")
    if action.environment_refresh is not adapter_environment_refresh(action.manager):
        raise ExecutionContractError("action refresh does not match the reviewed adapter")
    expected_path_entries = adapter_environment_path_entries(
        action.manager_state, context
    )
    if (
        expected_path_entries is None
        or action.environment_path_entries != expected_path_entries
        or any(
            not _path_is_absolute(path, context)
            for path in action.environment_path_entries
        )
    ):
        raise ExecutionContractError(
            "action executable-search paths do not match reviewed manager evidence"
        )
    if (
        action.verification.probes != provider.probes
        or action.verification.policy is not provider.probe_policy
        or action.shared_package is not provider.shared_package
    ):
        raise ExecutionContractError("action verification does not match the catalogue")
    if action.target_architecture is not None:
        target_architecture = normalize_architecture(action.target_architecture)
        if target_architecture == "unknown":
            raise ExecutionContractError(
                "native replacement target architecture is unknown"
            )
        if target_architecture != normalize_architecture(context.architecture):
            raise ExecutionContractError(
                "action target architecture is not native to the plan"
            )
    if bool(action.displaces_verified_paths) != (action.target_architecture is not None):
        raise ExecutionContractError("native replacement evidence is incomplete")
    if any(
        not _path_is_absolute(path, context)
        for path in action.displaces_verified_paths
    ):
        raise ExecutionContractError("displaced provider identity is not absolute")
    manager_native_status = action.manager_state.native_status(context)
    if action.manager == "brew":
        if manager_native_status is NativeStatus.UNKNOWN:
            raise ExecutionContractError("Homebrew manager architecture is unknown")
        if (
            manager_native_status is NativeStatus.TRANSLATED
            and not action.translated_manager_fallback_authorized
        ):
            raise ExecutionContractError(
                "translated Homebrew manager lacks explicit fallback authorization"
            )
        if (
            manager_native_status is NativeStatus.NATIVE
            and action.translated_manager_fallback_authorized
        ):
            raise ExecutionContractError(
                "native Homebrew cannot carry translated-fallback authorization"
            )
    elif action.translated_manager_fallback_authorized:
        raise ExecutionContractError(
            "translated package-manager authorization is limited to Homebrew"
        )


def _validate_plan(plan: ProviderPlan, current: MachineState) -> MachineState:
    if plan.context is None:
        if plan.actions:
            raise ExecutionContractError("mutating plan has no execution context")
        return current
    context = _normalized_context(plan.context)
    if context != _normalized_context(current):
        raise ExecutionContractError("provider plan is for a different execution context")
    if len(plan.requested_capabilities) != len(set(plan.requested_capabilities)):
        raise ExecutionContractError("provider plan has duplicate requested capabilities")
    seen: set[str] = set()
    for action in plan.actions:
        if action.capability_id not in plan.requested_capabilities:
            raise ExecutionContractError("action capability was not requested")
        if action.capability_id in seen:
            raise ExecutionContractError("provider plan has duplicate capability actions")
        seen.add(action.capability_id)
        _validate_action(action, context)
    return context


def _verified_provider_paths(
    action: ProviderAction,
    state: CapabilityState,
) -> tuple[str, ...]:
    provider = next(
        (item for item in state.providers if item.provider.provider_id == action.provider_id),
        None,
    )
    if provider is None:
        return ()
    if (
        provider.provider.probes != action.verification.probes
        or provider.provider.probe_policy is not action.verification.policy
    ):
        return ()
    return _acceptable_provider_paths(
        provider, state.machine, action.target_architecture
    )


def _acceptable_provider_paths(
    provider: ProviderState,
    machine: MachineState,
    target_architecture: str | None,
) -> tuple[str, ...]:
    target = (
        normalize_architecture(target_architecture)
        if target_architecture is not None
        else None
    )
    qualifying = acceptable_provider_executables(
        provider,
        lambda item: (
            item.path is not None
            and _path_is_absolute(item.path, machine)
            and (
                target is None
                or normalize_architecture(item.architecture) == target
            )
        ),
    )
    return tuple(item.path for item in qualifying if item.path is not None)


def _acceptable_current_provider(
    state: CapabilityState,
    target_architecture: str | None,
) -> tuple[str, tuple[str, ...]] | None:
    """Select fresh satisfying evidence using catalogue provider priority."""

    for provider in state.providers:
        paths = _acceptable_provider_paths(
            provider, state.machine, target_architecture
        )
        if paths:
            return provider.provider.provider_id, paths
    return None


def _observed_verified_provider_paths(
    action: ProviderAction,
    state: CapabilityState,
) -> tuple[str, ...]:
    provider = next(
        (item for item in state.providers if item.provider.provider_id == action.provider_id),
        None,
    )
    if provider is None:
        return ()
    return tuple(
        item.path
        for item in provider.executables
        if (
            item.verified
            and item.path is not None
            and _path_is_absolute(item.path, state.machine)
        )
    )


def _command_report(
    argv: tuple[str, ...],
    result: subprocess.CompletedProcess[str],
    *,
    timed_out: bool = False,
) -> CommandReport:
    return CommandReport(
        argv,
        result.returncode,
        _bounded_command_output(result.stdout or ""),
        _bounded_command_output(result.stderr or ""),
        timed_out,
    )


def _runner_contract_failure(
    argv: tuple[str, ...], result: object
) -> tuple[CommandReport, str] | None:
    """Convert malformed injected runner output into uncertain structured evidence."""

    if not isinstance(result, subprocess.CompletedProcess):
        return (
            CommandReport(argv, None, "", ""),
            "runner returned an object that is not subprocess.CompletedProcess",
        )
    invalid_fields: list[str] = []
    if not _is_valid_returncode(result.returncode):
        invalid_fields.append("returncode")
    if result.stdout is not None and not isinstance(result.stdout, str):
        invalid_fields.append("stdout")
    if result.stderr is not None and not isinstance(result.stderr, str):
        invalid_fields.append("stderr")
    if not invalid_fields:
        return None
    stdout = result.stdout if isinstance(result.stdout, str) else ""
    stderr = result.stderr if isinstance(result.stderr, str) else ""
    return (
        CommandReport(
            argv,
            None,
            _bounded_command_output(stdout),
            _bounded_command_output(stderr),
        ),
        "runner returned malformed completed-process evidence: "
        + ", ".join(invalid_fields),
    )


def _is_valid_returncode(value: object) -> bool:
    """Recognize the bounded cross-platform subprocess return-code domain."""

    return (
        type(value) is int
        and MIN_PROCESS_RETURNCODE <= value <= MAX_PROCESS_RETURNCODE
    )


def _bounded_command_output(value: str) -> str:
    if len(value) <= MAX_CAPTURED_OUTPUT_CHARS:
        return value
    return OUTPUT_TRUNCATION_MARKER + value[-MAX_CAPTURED_OUTPUT_CHARS:]


def _completed_command_failure(
    result: subprocess.CompletedProcess[str], *, elevated_linux: bool
) -> tuple[ActionOutcome, str] | None:
    """Classify completed command evidence before the next provider command."""

    if elevated_linux and result.returncode in {
        124,
        137,
        POSIX_SIGKILL_RETURNCODE,
        125,
        126,
        127,
    }:
        supervised_outcomes = {
            124: ActionOutcome.COMMAND_FAILED,
            137: ActionOutcome.FORCED_KILL,
            POSIX_SIGKILL_RETURNCODE: ActionOutcome.FORCED_KILL,
            125: ActionOutcome.SUPERVISOR_FAILED,
            126: ActionOutcome.COMMAND_START_FAILED,
            127: ActionOutcome.COMMAND_START_FAILED,
        }
        details = {
            124: (
                "GNU timeout returned status 124, which cannot distinguish "
                "deadline expiry from the reviewed command's own status 124"
            ),
            137: "command or supervisor exited after SIGKILL; timeout expiry is not independently established",
            POSIX_SIGKILL_RETURNCODE: (
                "command or supervisor exited after SIGKILL; timeout "
                "expiry is not independently established"
            ),
            125: (
                "GNU timeout returned status 125, which cannot distinguish "
                "supervisor failure from the reviewed command's own status 125"
            ),
            126: (
                "GNU timeout returned status 126, which cannot distinguish "
                "command-start failure from the reviewed command's own status 126"
            ),
            127: (
                "GNU timeout returned status 127, which cannot distinguish "
                "command resolution failure from the reviewed command's own status 127"
            ),
        }
        return supervised_outcomes[result.returncode], details[result.returncode]
    if result.returncode != 0:
        return (
            ActionOutcome.COMMAND_FAILED,
            f"command exited with status {result.returncode}",
        )
    return None


def _action_report(
    action: ProviderAction,
    outcome: ActionOutcome,
    commands: tuple[CommandReport, ...] = (),
    final_verified_paths: tuple[str, ...] = (),
    detail: str = "",
    satisfied_by_provider_id: str | None = None,
) -> ActionReport:
    return ActionReport(
        action.capability_id,
        action.provider_id,
        action.manager,
        action.installation_unit,
        outcome,
        commands,
        final_verified_paths,
        detail,
        action.target_architecture,
        action.displaces_verified_paths,
        action.translated_manager_fallback_authorized,
        satisfied_by_provider_id,
    )


def _materialize_post_start_failure_report(
    *,
    plan: ProviderPlan,
    context: MachineState,
    reports: list[ActionReport],
    action: ProviderAction,
    commands: list[CommandReport],
    command: Callable[[], CommandReport],
    outcome: ActionOutcome,
    detail: str,
    uncertain_external_state: bool,
) -> PlanExecutionReport:
    """Build a post-start failure report without losing prior action evidence."""

    action_report = _action_report(
        action,
        outcome,
        (*commands, command()),
        detail=detail,
    )
    return _failed_report(
        plan,
        context,
        [*reports, action_report],
        mutation_may_have_started=True,
        uncertain_external_state=uncertain_external_state,
    )


def _omitted_request_failure(
    plan: ProviderPlan,
    context: MachineState,
    detector: Detector,
) -> str | None:
    action_capabilities = {action.capability_id for action in plan.actions}
    for capability_id in plan.requested_capabilities:
        if capability_id in action_capabilities:
            continue
        try:
            capability = get_capability(capability_id)
        except KeyError:
            return f"unknown requested capability: {capability_id}"
        state = detector(capability, context)
        if state.capability != capability:
            return (
                "omitted capability detector returned evidence for a different "
                f"capability: {capability_id}"
            )
        try:
            validate_capability_state(state, expected_context=context)
        except PlanningError as error:
            return f"omitted capability evidence is stale: {error}"
        if _acceptable_current_provider(state, None) is None:
            return f"requested capability no longer verifies: {capability_id}"
    return None


@contextmanager
def _provider_execution_transaction():
    """Serialize the complete supported managed mutation transaction."""

    with _EXECUTION_LOCK:
        yield


def _execute_provider_plan_unmanaged(
    plan: ProviderPlan,
    *,
    allow_provider_mutation: bool = False,
    timeout_seconds: TimeoutSeconds = DEFAULT_COMMAND_TIMEOUT_SECONDS,
    runner: Runner = _run,
    detector: Detector = _detect,
    current_context: ContextReader = current_machine,
    manager_verifier: ManagerVerifier = _verify_manager,
    manager_architecture_reader: ManagerArchitectureReader = _read_manager_architecture,
    privilege_resolver: PrivilegeResolver = _resolve_privilege,
    supervisor_resolver: SupervisorResolver = _resolve_supervisor,
    privilege_preflight: PrivilegePreflight = _preflight_privilege,
    environment_refresher: EnvironmentRefresher = _refresh_environment,
    _cancellation: _CancellationContext | None = None,
) -> PlanExecutionReport:
    """Internal executor primitive; callers must use the managed-state boundary."""

    cancellation = _cancellation or _CancellationContext()
    timeout_seconds = _validate_timeout_seconds(timeout_seconds)
    with _provider_execution_transaction():
        try:
            return _execute_provider_plan(
                plan,
                allow_provider_mutation=allow_provider_mutation,
                timeout_seconds=timeout_seconds,
                runner=runner,
                detector=detector,
                current_context=current_context,
                manager_verifier=manager_verifier,
                manager_architecture_reader=manager_architecture_reader,
                privilege_resolver=privilege_resolver,
                supervisor_resolver=supervisor_resolver,
                privilege_preflight=privilege_preflight,
                environment_refresher=environment_refresher,
                cancellation=cancellation,
            )
        except _ProviderPartialReport as error:
            return error.report


def _execute_provider_plan(
    plan: ProviderPlan,
    *,
    allow_provider_mutation: bool,
    timeout_seconds: TimeoutSeconds,
    runner: Runner,
    detector: Detector,
    current_context: ContextReader,
    manager_verifier: ManagerVerifier,
    manager_architecture_reader: ManagerArchitectureReader,
    privilege_resolver: PrivilegeResolver,
    supervisor_resolver: SupervisorResolver,
    privilege_preflight: PrivilegePreflight,
    environment_refresher: EnvironmentRefresher,
    cancellation: _CancellationContext,
) -> PlanExecutionReport:
    context = _validate_plan(plan, current_context())
    if not plan.actions:
        failure = _omitted_request_failure(plan, context, detector)
        if failure:
            return PlanExecutionReport(
                context,
                plan.requested_capabilities,
                PlanOutcome.PREFLIGHT_FAILED,
                (),
                (failure,),
            )
        return PlanExecutionReport(
            context,
            plan.requested_capabilities,
            PlanOutcome.NO_CHANGES,
            (),
        )
    if not allow_provider_mutation:
        return PlanExecutionReport(
            context,
            plan.requested_capabilities,
            PlanOutcome.REFUSED,
            tuple(
                _action_report(
                    action,
                    ActionOutcome.REFUSED,
                    detail="provider mutation was not explicitly authorized",
                )
                for action in plan.actions
            ),
            ("rerun with explicit provider-mutation authorization",),
        )

    failure = _omitted_request_failure(plan, context, detector)
    if failure:
        return PlanExecutionReport(
            context,
            plan.requested_capabilities,
            PlanOutcome.PREFLIGHT_FAILED,
            tuple(
                _action_report(
                    action,
                    ActionOutcome.NOT_ATTEMPTED,
                    detail="not attempted because requested capability preflight failed",
                )
                for action in plan.actions
            ),
            (
                "no provider command started; this attempt did not mutate provider state",
                failure,
            ),
        )

    reports: list[ActionReport] = []
    for action in plan.actions:
        if cancellation.checkpoint():
            reports.append(
                _action_report(
                    action,
                    ActionOutcome.NOT_ATTEMPTED,
                    detail="cancellation accepted before this provider action started",
                )
            )
            return _failed_report(
                plan,
                context,
                reports,
                mutation_may_have_started=any(report.commands for report in reports),
            )
        try:
            capability = get_capability(action.capability_id)
            with _refreshed_environment(
                action, environment_refresher, cancellation
            ):
                before = detector(capability, context)
            if before.capability != capability:
                raise PlanningError(
                    "detector returned evidence for a different capability"
                )
            validate_capability_state(before, expected_context=context)
        except PlanningError as error:
            if not reports:
                raise ExecutionContractError(
                    f"pre-action detection is not authoritative: {error}"
                ) from error
            reports.append(
                _action_report(
                    action,
                    ActionOutcome.PREFLIGHT_FAILED,
                    detail=f"pre-action detection is not authoritative: {error}",
                )
            )
            return _failed_report(
                plan,
                context,
                reports,
                mutation_may_have_started=any(report.commands for report in reports),
            )
        except Exception as error:
            if not any(report.commands for report in reports):
                raise ExecutionContractError(
                    "pre-action detection failed before any provider command: "
                    f"{type(error).__name__}: {error}"
                ) from error
            reports.append(
                _action_report(
                    action,
                    ActionOutcome.PREFLIGHT_FAILED,
                    detail=(
                        "pre-action detection failed after an earlier action may have "
                        f"mutated state: {type(error).__name__}: {error}"
                    ),
                )
            )
            return _failed_report(
                plan, context, reports, mutation_may_have_started=True
            )

        if cancellation.checkpoint():
            reports.append(
                _action_report(
                    action,
                    ActionOutcome.NOT_ATTEMPTED,
                    detail=(
                        "cancellation accepted after pre-action detection; no "
                        "command started for this action"
                    ),
                )
            )
            return _failed_report(
                plan,
                context,
                reports,
                mutation_may_have_started=any(report.commands for report in reports),
            )

        def precommand(operation):
            try:
                return operation()
            except Exception as error:
                if not any(report.commands for report in reports):
                    raise ExecutionContractError(
                        "execution preflight failed before any provider command: "
                        f"{type(error).__name__}: {error}"
                    ) from error
                reports.append(
                    _action_report(
                        action,
                        ActionOutcome.PREFLIGHT_FAILED,
                        detail=(
                            "execution preflight failed after an earlier action may "
                            f"have mutated state: {type(error).__name__}: {error}"
                        ),
                    )
                )
                raise _ProviderPartialReport(
                    _failed_report(
                        plan,
                        context,
                        reports,
                        mutation_may_have_started=True,
                    )
                ) from error

        existing_provider = precommand(
            lambda: _acceptable_current_provider(
                before, action.target_architecture
            )
        )
        if existing_provider:
            existing_provider_id, existing_paths = existing_provider
            reports.append(
                _action_report(
                    action,
                    ActionOutcome.ALREADY_SATISFIED,
                    final_verified_paths=existing_paths,
                    detail="a current satisfying provider already verifies; no command executed",
                    satisfied_by_provider_id=existing_provider_id,
                )
            )
            continue
        if not precommand(lambda: manager_verifier(action.manager_state, context)):
            reports.append(
                _action_report(
                    action,
                    ActionOutcome.MANAGER_UNAVAILABLE,
                    detail="verified package-manager identity is no longer available",
                )
            )
            return _failed_report(
                plan, context, reports, mutation_may_have_started=False
            )
        if action.manager == "brew" and normalize_architecture(
            precommand(lambda: manager_architecture_reader(action.manager_state))
        ) != normalize_architecture(action.manager_state.architecture):
            reports.append(
                _action_report(
                    action,
                    ActionOutcome.MANAGER_UNAVAILABLE,
                    detail="Homebrew architecture no longer matches reviewed evidence",
                )
            )
            return _failed_report(
                plan, context, reports, mutation_may_have_started=False
            )
        elevation = precommand(lambda: privilege_resolver(action))
        if elevation is None:
            reports.append(
                _action_report(
                    action,
                    ActionOutcome.PRIVILEGE_UNAVAILABLE,
                    detail="system privilege is required but no safe elevation path is available",
                )
            )
            return _failed_report(
                plan, context, reports, mutation_may_have_started=False
            )
        supervisor = precommand(lambda: supervisor_resolver(action))
        if supervisor is None:
            reports.append(
                _action_report(
                    action,
                    ActionOutcome.SUPERVISOR_FAILED,
                    detail="verified GNU timeout supervision is unavailable",
                )
            )
            return _failed_report(
                plan, context, reports, mutation_may_have_started=False
            )
        elevated_linux = (
            action.execution_privilege is ExecutionPrivilege.SYSTEM
            and context.platform == "Linux"
        )
        elevated_commands = (
            tuple(
                _elevated_argv(
                    reviewed_argv,
                    elevation=elevation,
                    supervisor=supervisor,
                    timeout_seconds=timeout_seconds,
                )
                for reviewed_argv in action.commands
            )
            if elevated_linux
            else ()
        )
        if elevated_linux and precommand(
            lambda: any(
                not privilege_preflight(argv) for argv in elevated_commands
            )
        ):
            reports.append(
                _action_report(
                    action,
                    ActionOutcome.PRIVILEGE_UNAVAILABLE,
                    detail="noninteractive sudo refused the verified supervisor",
                )
            )
            return _failed_report(
                plan, context, reports, mutation_may_have_started=False
            )

        commands: list[CommandReport] = []
        for command_index, reviewed_argv in enumerate(action.commands):
            if cancellation.checkpoint():
                reports.append(
                    _action_report(
                        action,
                        (
                            ActionOutcome.INTERRUPTED
                            if commands
                            else ActionOutcome.NOT_ATTEMPTED
                        ),
                        tuple(commands),
                        detail=(
                            "cancellation accepted before the next provider command "
                            "started"
                        ),
                    )
                )
                return _failed_report(
                    plan,
                    context,
                    reports,
                    mutation_may_have_started=bool(commands)
                    or any(report.commands for report in reports),
                )
            argv = (
                elevated_commands[command_index]
                if elevated_linux
                else ((elevation, *reviewed_argv) if elevation else reviewed_argv)
            )
            runner_timeout = (
                timeout_seconds
                + ELEVATED_TERM_TO_KILL_GRACE_SECONDS
                + ELEVATED_SUPERVISOR_GUARD_SECONDS
                if elevated_linux
                else timeout_seconds
            )
            try:
                if runner is _run:
                    result = _run(
                        argv,
                        runner_timeout,
                        privileged_supervision=elevated_linux,
                        _cancellation=cancellation,
                    )
                else:
                    result = runner(argv, runner_timeout)
            except _ForceAbort:
                raise
            except UncertainSupervisionError as error:
                retained_timeout = (
                    error.timed_out and error.result.returncode is None
                )
                return _materialize_post_start_failure_report(
                    plan=plan,
                    context=context,
                    reports=reports,
                    action=action,
                    commands=commands,
                    command=lambda: _command_report(
                        argv, error.result, timed_out=retained_timeout
                    ),
                    outcome=(
                        ActionOutcome.TIMED_OUT
                        if retained_timeout and not elevated_linux
                        else ActionOutcome.SUPERVISOR_FAILED
                    ),
                    detail=error.detail,
                    uncertain_external_state=True,
                )
            except CommandLifecycleError as error:
                retained_timeout = (
                    error.timed_out and error.result.returncode is None
                )
                return _materialize_post_start_failure_report(
                    plan=plan,
                    context=context,
                    reports=reports,
                    action=action,
                    commands=commands,
                    command=lambda: _command_report(
                        argv, error.result, timed_out=retained_timeout
                    ),
                    outcome=(
                        ActionOutcome.TIMED_OUT
                        if retained_timeout and not elevated_linux
                        else ActionOutcome.SUPERVISOR_FAILED
                    ),
                    detail=error.detail,
                    uncertain_external_state=error.lifetime_uncertain,
                )
            except CommandInterruptedError as error:
                commands.append(_command_report(argv, error.result))
                reports.append(
                    _action_report(
                        action,
                        (
                            ActionOutcome.SUPERVISOR_FAILED
                            if error.lifetime_uncertain
                            else ActionOutcome.INTERRUPTED
                        ),
                        tuple(commands),
                        detail=error.detail,
                    )
                )
                return _failed_report(
                    plan,
                    context,
                    reports,
                    mutation_may_have_started=True,
                    uncertain_external_state=error.lifetime_uncertain,
                )
            except subprocess.TimeoutExpired as error:
                commands.append(
                    CommandReport(
                        argv,
                        None,
                        _bounded_command_output(_timeout_text(error.stdout)),
                        _bounded_command_output(_timeout_text(error.stderr)),
                        timed_out=True,
                    )
                )
                reports.append(
                    _action_report(
                        action,
                        (
                            ActionOutcome.SUPERVISOR_FAILED
                            if elevated_linux
                            else ActionOutcome.TIMED_OUT
                        ),
                        tuple(commands),
                        detail=(
                            "privileged supervisor did not establish bounded termination"
                            if elevated_linux
                            else f"command exceeded {timeout_seconds} seconds"
                        ),
                    )
                )
                return _failed_report(
                    plan,
                    context,
                    reports,
                    mutation_may_have_started=True,
                    uncertain_external_state=elevated_linux,
                )
            except OSError as error:
                earlier_command_completed = bool(commands)
                commands.append(
                    CommandReport(
                        argv, None, "", _bounded_command_output(str(error))
                    )
                )
                reports.append(
                    _action_report(
                        action,
                        ActionOutcome.COMMAND_START_FAILED,
                        tuple(commands),
                        detail=f"command could not start: {error}",
                    )
                )
                return _failed_report(
                    plan,
                    context,
                    reports,
                    mutation_may_have_started=earlier_command_completed,
                )
            runner_failure = _runner_contract_failure(argv, result)
            if runner_failure is not None:
                command_report, detail = runner_failure
                commands.append(command_report)
                reports.append(
                    _action_report(
                        action,
                        ActionOutcome.SUPERVISOR_FAILED,
                        tuple(commands),
                        detail=detail,
                    )
                )
                return _failed_report(
                    plan,
                    context,
                    reports,
                    mutation_may_have_started=True,
                    uncertain_external_state=True,
                )
            command_report = _command_report(argv, result)
            commands.append(command_report)
            failure = _completed_command_failure(
                result, elevated_linux=elevated_linux
            )
            if failure is not None:
                outcome, detail = failure
                return _failed_report(
                    plan,
                    context,
                    [
                        *reports,
                        _action_report(
                            action,
                            outcome,
                            tuple(commands),
                            detail=detail,
                        ),
                    ],
                    mutation_may_have_started=True,
                )

            if cancellation.checkpoint():
                reports.append(
                    _action_report(
                        action,
                        ActionOutcome.INTERRUPTED,
                        tuple(commands),
                        detail=(
                            "cancellation accepted after completed provider command "
                            "evidence was published"
                        ),
                    )
                )
                return _failed_report(
                    plan, context, reports, mutation_may_have_started=True
                )

        observed_paths: tuple[str, ...] = ()
        try:
            with _refreshed_environment(
                action, environment_refresher, cancellation
            ):
                after = detector(capability, context)
            if after.capability != capability:
                raise PlanningError(
                    "detector returned evidence for a different capability"
                )
            validate_capability_state(after, expected_context=context)
            observed_paths = _observed_verified_provider_paths(action, after)
            final_paths = _verified_provider_paths(action, after)
            verification_detail = (
                "package-manager success did not produce the planned verified provider"
            )
        except PlanningError as error:
            final_paths = ()
            verification_detail = f"post-action detection is not authoritative: {error}"
        except Exception as error:
            reports.append(
                _action_report(
                    action,
                    ActionOutcome.VERIFICATION_FAILED,
                    tuple(commands),
                    detail=(
                        "post-action verification failed after the package-manager "
                        f"command completed: {type(error).__name__}: {error}"
                    ),
                )
            )
            return _failed_report(
                plan, context, reports, mutation_may_have_started=True
            )
        if not final_paths:
            reports.append(
                _action_report(
                    action,
                    ActionOutcome.VERIFICATION_FAILED,
                    tuple(commands),
                    observed_paths,
                    detail=verification_detail,
                )
            )
            return _failed_report(
                plan, context, reports, mutation_may_have_started=True
            )
        reports.append(
            _action_report(
                action,
                ActionOutcome.SUCCEEDED,
                tuple(commands),
                final_paths,
                "planned provider rediscovered and verified",
            )
        )

        if cancellation.checkpoint():
            return _failed_report(
                plan, context, reports, mutation_may_have_started=True
            )

    return PlanExecutionReport(
        context,
        plan.requested_capabilities,
        PlanOutcome.SUCCEEDED,
        tuple(reports),
    )


def _preflight_interrupted_report(
    plan: ProviderPlan, context: MachineState | None
) -> PlanExecutionReport:
    return PlanExecutionReport(
        context,
        plan.requested_capabilities,
        PlanOutcome.PREFLIGHT_FAILED,
        tuple(
            _action_report(
                action,
                ActionOutcome.NOT_ATTEMPTED,
                detail="interrupted before any provider command started",
            )
            for action in plan.actions
        ),
        (
            "no provider command started; this interruption did not mutate provider state",
            "generate fresh current state before a later mutation attempt",
        ),
    )


def _timeout_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode(errors="replace") if isinstance(value, bytes) else value


def _failed_report(
    plan: ProviderPlan,
    context: MachineState,
    reports: list[ActionReport],
    *,
    mutation_may_have_started: bool,
    uncertain_external_state: bool = False,
) -> PlanExecutionReport:
    reports.extend(
        _action_report(
            action,
            ActionOutcome.NOT_ATTEMPTED,
            detail="not attempted because an earlier provider action failed",
        )
        for action in plan.actions[len(reports) :]
    )
    earlier_action_changed_state = any(
        report.outcome is ActionOutcome.SUCCEEDED for report in reports
    )
    if uncertain_external_state:
        recovery_guidance = (
            "synchronous supervision ended but relevant descendant or package activity may still be running",
            "Agent Tools could not establish quiescence; provider/package state is uncertain",
            "do not retry automatically or immediately, and do not attempt rollback or removal",
            "retry only after an operator independently establishes relevant activity has quiesced and generates a fresh plan from current state",
        )
    elif mutation_may_have_started or earlier_action_changed_state:
        recovery_guidance = (
            "the package manager may have left partial host state",
            "do not retry automatically or immediately; inspect the reported command output "
            "and current package-manager/provider state first",
            "restore provider availability if needed, then generate a fresh plan before retry; "
            "repeated package-manager operations are expected to be idempotent",
        )
    else:
        recovery_guidance = (
            "no provider command started; this attempt did not mutate provider state",
            "correct the reported pre-execution failure, then regenerate a plan and retry",
        )
    return PlanExecutionReport(
        context,
        plan.requested_capabilities,
        PlanOutcome.PARTIAL_FAILURE,
        tuple(reports),
        recovery_guidance,
    )
