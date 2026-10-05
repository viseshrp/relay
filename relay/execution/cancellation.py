"""Fail-fast run cancellation and bounded cross-platform process-tree stop."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import os
from pathlib import Path
import signal
import subprocess
import sys
from typing import Protocol

from relay.constants import (
    CANCELLATION_GRACE_SECONDS,
    PROCESS_EXIT_GRACE_SECONDS,
    PROCESS_STREAM_CHUNK_BYTES,
)
from relay.errors import CancellationError
from relay.execution.control import ControlResult, valid_idempotency_key


class CancellationStore(Protocol):
    def request_run_cancellation(self, run_id: str, idempotency_key: str) -> ControlResult: ...


@dataclass(frozen=True, slots=True)
class ProcessCancellation:
    """Whether cooperative stop was enough or force was required."""

    exited: bool
    forced: bool
    returncode: int | None


def request_cancellation(
    store: CancellationStore,
    run_id: str,
    idempotency_key: str,
) -> ControlResult:
    """Validate the public key before any durable run state changes."""
    if not valid_idempotency_key(idempotency_key):
        return ControlResult.INVALID
    return store.request_run_cancellation(run_id, idempotency_key)


def _wait(process: subprocess.Popen[bytes] | subprocess.Popen[str], timeout: float) -> bool:
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        return False
    return True


def signal_process_tree(
    process_id: int, *, force: bool = False, graceful_signal: signal.Signals = signal.SIGTERM
) -> None:
    """Signal a process group, or force-stop its Windows tree within a bound."""
    try:
        if os.name == "nt" and force:
            subprocess.run(  # noqa: S603
                ["taskkill", "/PID", str(process_id), "/T", "/F"],  # noqa: S607
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=PROCESS_EXIT_GRACE_SECONDS,
            )
        elif os.name == "nt":
            # CREATE_NEW_PROCESS_GROUP permits a cooperative console break.
            os.kill(process_id, signal.CTRL_BREAK_EVENT)
        else:
            os.killpg(process_id, signal.SIGKILL if force else graceful_signal)
    except ProcessLookupError:
        return


async def spawn_process(
    argv: Sequence[str],
    cwd: Path,
    *,
    input_pipe: bool = True,
    environment: Mapping[str, str] | None = None,
) -> asyncio.subprocess.Process:
    """Start every agent command and probe in its own process group."""
    stdin = asyncio.subprocess.PIPE if input_pipe else asyncio.subprocess.DEVNULL
    if os.name == "nt":
        return await asyncio.create_subprocess_exec(
            *owned_process_argv(argv),
            cwd=str(cwd),
            env=dict(environment) if environment is not None else os.environ.copy(),
            stdin=stdin,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    return await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(cwd),
        env=dict(environment) if environment is not None else os.environ.copy(),
        stdin=stdin,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )


def owned_process_argv(argv: Sequence[str]) -> tuple[str, ...]:
    """Windows starts the command inside a private job; POSIX uses its new session."""
    if os.name == "nt":
        return (sys.executable, str(Path(__file__).with_name("windows_process.py")), *argv)
    return tuple(argv)


def release_process_group(process_id: int) -> None:
    """Stop remaining descendants of a POSIX group Relay created, even after its leader exits."""
    if os.name != "nt":
        signal_process_tree(process_id, force=True)


async def discard_process_stream(stream: asyncio.StreamReader | None) -> None:
    """Drain an unused pipe without buffering provider output in memory."""
    if stream is not None:
        while await stream.read(PROCESS_STREAM_CHUNK_BYTES):
            pass


async def terminate_async_process_tree(process: asyncio.subprocess.Process) -> None:
    """Share tree signaling with command nodes and bound both process waits."""
    if process.returncode is not None:
        return
    try:
        try:
            await asyncio.to_thread(signal_process_tree, process.pid)
        except OSError:
            if os.name != "nt":
                raise
        try:
            await asyncio.wait_for(process.wait(), timeout=CANCELLATION_GRACE_SECONDS)
        except asyncio.TimeoutError:
            await asyncio.to_thread(signal_process_tree, process.pid, force=True)
        else:
            return
        await asyncio.wait_for(process.wait(), timeout=PROCESS_EXIT_GRACE_SECONDS)
    except (OSError, subprocess.SubprocessError, asyncio.TimeoutError):
        message = "Relay could not stop the attempt process tree within its deadline."
        raise CancellationError(
            message, next_action="Inspect the retained worktree and local process before cleanup."
        ) from None


def terminate_process_tree(
    process: subprocess.Popen[bytes] | subprocess.Popen[str],
    *,
    grace_seconds: float = CANCELLATION_GRACE_SECONDS,
) -> ProcessCancellation:
    """Terminate a process group, wait once, then force-kill after the grace."""
    if process.poll() is not None:
        return ProcessCancellation(True, False, process.returncode)
    try:
        try:
            signal_process_tree(process.pid)
        except OSError:
            if os.name != "nt":
                raise
        if _wait(process, grace_seconds):
            return ProcessCancellation(True, False, process.returncode)
        signal_process_tree(process.pid, force=True)
        if not _wait(process, PROCESS_EXIT_GRACE_SECONDS):
            message = "Relay force-stopped the process tree, but it did not exit in time."
            raise CancellationError(
                message,
                next_action="Inspect the retained worktree and local process before cleanup.",
            )
    except (OSError, subprocess.SubprocessError):
        message = "Relay could not stop the attempt process tree."
        raise CancellationError(
            message,
            next_action="Inspect the local process and retained worktree before cleanup.",
        ) from None
    return ProcessCancellation(True, True, process.returncode)


__all__ = [
    "CancellationStore",
    "ProcessCancellation",
    "request_cancellation",
    "terminate_process_tree",
]
