"""Shell-free command execution with durable output and bounded stopping."""

from __future__ import annotations

import contextlib
import os
import subprocess
import tempfile
import time
from typing import BinaryIO

from relay.constants import (
    ATTEMPT_HEARTBEAT_INTERVAL_SECONDS,
    CONTROL_POLL_INTERVAL_SECONDS,
)
from relay.errors import NodeExecutionError, PersistenceError
from relay.execution.cancellation import terminate_process_tree
from relay.execution.control import cancel_stop_reason
from relay.execution.runner import AttemptContext, ExecutionOutcome, OutcomeKind
from relay.execution.state import AttemptStopReason, ControlKind, EventSource
from relay.workflows.schema import CommandNode

from .base import duration_seconds, emit_output_stream, parse_node, validated_outputs


def _creation_flags() -> int:
    if os.name != "nt":
        return 0
    value = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return value if isinstance(value, int) else 0


def _launch(
    context: AttemptContext,
    node: CommandNode,
    stdout: BinaryIO,
    stderr: BinaryIO,
) -> subprocess.Popen[bytes]:
    environment = os.environ.copy()
    environment.update(node.env)
    try:
        return subprocess.Popen(  # noqa: S603
            list(node.run),
            cwd=context.worktree,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            shell=False,
            text=False,
            start_new_session=os.name != "nt",
            creationflags=_creation_flags(),
        )
    except OSError:
        message = f"Relay could not start command {node.run[0]!r}."
        raise NodeExecutionError(
            message,
            context={"node": context.attempt.scope_path},
        ) from None


def _wait(
    context: AttemptContext,
    process: subprocess.Popen[bytes],
    timeout_seconds: float | None,
) -> AttemptStopReason | None:
    started = time.monotonic()
    heartbeat_due = started + ATTEMPT_HEARTBEAT_INTERVAL_SECONDS
    while process.poll() is None:
        elapsed = time.monotonic() - started
        if timeout_seconds is not None and elapsed >= timeout_seconds:
            terminate_process_tree(process)
            return AttemptStopReason.TIMEOUT
        wait_for = CONTROL_POLL_INTERVAL_SECONDS
        if timeout_seconds is not None:
            wait_for = min(wait_for, max(0.001, timeout_seconds - elapsed))
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=wait_for)
        now = time.monotonic()
        if now >= heartbeat_due:
            if not context.runtime.heartbeat_attempt(
                context.attempt.attempt_id, context.attempt.worker_id
            ):
                terminate_process_tree(process)
                message = "The command attempt lost its durable worker ownership."
                raise PersistenceError(message, context={"node": context.attempt.scope_path})
            heartbeat_due = now + ATTEMPT_HEARTBEAT_INTERVAL_SECONDS
        control = context.runtime.claim_next_control(
            context.attempt.attempt_id,
            context.attempt.worker_id,
        )
        if control is not None:
            context.runtime.apply_control(
                control.request_id,
                context.attempt.worker_id,
            )
            if control.kind == ControlKind.CANCEL.value:
                terminate_process_tree(process)
                return cancel_stop_reason(control)
    return None


class CommandExecutor:
    """Execute one argv command and retain stdout, stderr, exit, timing, and outputs."""

    def execute(self, context: AttemptContext) -> ExecutionOutcome:
        node = parse_node(context, CommandNode)
        timeout = duration_seconds(node.timeout)
        started = time.monotonic()
        with (
            tempfile.TemporaryFile(mode="w+b") as stdout,
            tempfile.TemporaryFile(mode="w+b") as stderr,
        ):
            process = _launch(context, node, stdout, stderr)
            context.runtime.record_attempt_process(context.attempt.attempt_id, process.pid)
            try:
                stop_reason = _wait(context, process, timeout)
            finally:
                context.runtime.record_attempt_process(context.attempt.attempt_id, None)
            emit_output_stream(context, stdout, "command.stdout")
            emit_output_stream(context, stderr, "command.stderr")

        duration_ms = round((time.monotonic() - started) * 1_000)
        context.runtime.append_attempt_event(
            context.attempt.attempt_id,
            "command.exit",
            EventSource.COMMAND,
            {"exit_code": process.returncode, "duration_ms": duration_ms},
        )
        if stop_reason is not None:
            return ExecutionOutcome(
                OutcomeKind.FAILED,
                stop_reason=stop_reason,
                exit_code=process.returncode,
                error_code=(
                    "canceled"
                    if stop_reason is AttemptStopReason.CANCELED
                    else "interrupted"
                    if stop_reason is AttemptStopReason.INTERRUPTED
                    else "node_timeout"
                ),
            )
        if process.returncode != 0:
            return ExecutionOutcome(
                OutcomeKind.FAILED,
                stop_reason=AttemptStopReason.FAILED,
                exit_code=process.returncode,
                error_code=NodeExecutionError.error_code,
            )
        outputs, artifacts = validated_outputs(context.worktree, node.outputs)
        return ExecutionOutcome(
            OutcomeKind.SUCCEEDED,
            outputs=outputs,
            declared_artifacts=artifacts,
            exit_code=process.returncode,
        )


__all__ = ["CommandExecutor"]
