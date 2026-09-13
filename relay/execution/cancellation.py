"""Fail-fast run cancellation and bounded cross-platform process-tree stop."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
import signal
import subprocess
from typing import Protocol

from relay.constants import CANCELLATION_GRACE_SECONDS
from relay.errors import CancellationError

LOGGER = logging.getLogger(__name__)


class AgentSession(Protocol):
    def cancel(self) -> None: ...


class CancellationStore(Protocol):
    def request_run_cancellation(self, run_id: str, idempotency_key: str) -> tuple[str, ...]: ...


@dataclass(frozen=True, slots=True)
class ProcessCancellation:
    """Whether cooperative stop was enough or force was required."""

    exited: bool
    forced: bool
    returncode: int | None


def _wait(process: subprocess.Popen[bytes] | subprocess.Popen[str], timeout: float) -> bool:
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        return False
    return True


def _windows_tree(process: subprocess.Popen[bytes] | subprocess.Popen[str]) -> bool:
    command = ["taskkill", "/PID", str(process.pid), "/T"]
    result = subprocess.run(  # noqa: S603
        command,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def _windows_force(process: subprocess.Popen[bytes] | subprocess.Popen[str]) -> None:
    subprocess.run(  # noqa: S603
        ["taskkill", "/PID", str(process.pid), "/T", "/F"],  # noqa: S607
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def terminate_process_tree(
    process: subprocess.Popen[bytes] | subprocess.Popen[str],
    *,
    grace_seconds: float = CANCELLATION_GRACE_SECONDS,
) -> ProcessCancellation:
    """Terminate a process group, wait once, then force-kill after the grace."""
    if process.poll() is not None:
        return ProcessCancellation(True, False, process.returncode)
    try:
        if os.name == "nt":
            _windows_tree(process)
        else:
            os.killpg(process.pid, signal.SIGTERM)
        if _wait(process, grace_seconds):
            return ProcessCancellation(True, False, process.returncode)
        if os.name == "nt":
            _windows_force(process)
        else:
            os.killpg(process.pid, signal.SIGKILL)
        if not _wait(process, grace_seconds):
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


def cancel_agent_attempt(
    session: AgentSession,
    process: subprocess.Popen[bytes] | subprocess.Popen[str],
    *,
    grace_seconds: float = CANCELLATION_GRACE_SECONDS,
) -> ProcessCancellation:
    """Request protocol cancellation before enforcing the process-tree bound."""
    try:
        session.cancel()
    except Exception:
        # Process-tree termination remains mandatory when protocol cancellation fails.
        LOGGER.exception("Protocol cancellation failed; stopping the process tree")
    return terminate_process_tree(process, grace_seconds=grace_seconds)


__all__ = [
    "AgentSession",
    "CancellationStore",
    "ProcessCancellation",
    "cancel_agent_attempt",
    "terminate_process_tree",
]
