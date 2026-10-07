"""Shell-free command execution with durable output and bounded stopping."""

from __future__ import annotations

import codecs
import contextlib
import os
from pathlib import Path
import subprocess
import tempfile
import time
from typing import IO

from relay.constants import (
    ATTEMPT_HEARTBEAT_INTERVAL_SECONDS,
    CONTROL_POLL_INTERVAL_SECONDS,
)
from relay.errors import NodeExecutionError, PersistenceError
from relay.execution.cancellation import (
    owned_process_argv,
    release_process_group,
    terminate_process_tree,
)
from relay.execution.control import cancel_stop_reason
from relay.execution.runner import AttemptContext, ExecutionOutcome, OutcomeKind
from relay.execution.state import AttemptStopReason, ControlKind, EventSource
from relay.workflows.schema import CommandNode

from .base import parse_node, validated_outputs


def _creation_flags() -> int:
    if os.name != "nt":
        return 0
    value = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return value if isinstance(value, int) else 0


def _launch(
    context: AttemptContext,
    node: CommandNode,
    stdout: IO[bytes],
    stderr: IO[bytes],
) -> subprocess.Popen[bytes]:
    arguments = node.run
    if not isinstance(arguments, list):
        message = "The shared command was not resolved in the captured workflow."
        raise NodeExecutionError(message, context={"node": context.attempt.scope_path})
    environment = os.environ.copy()
    if context.resources is not None:
        environment.update(context.resources.environment())
    environment.update(node.env)
    try:
        return subprocess.Popen(  # noqa: S603
            owned_process_argv(arguments),
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
        message = f"Relay could not start command {arguments[0]!r}."
        raise NodeExecutionError(
            message,
            context={"node": context.attempt.scope_path},
        ) from None


class _CommandOutput:
    stream: IO[bytes]
    event_type: str
    decoder: codecs.IncrementalDecoder

    def __init__(self, stream: IO[bytes], event_type: str) -> None:
        self.stream = stream
        self.event_type = event_type
        self.decoder = codecs.getincrementaldecoder("utf-8")(errors="backslashreplace")

    def emit(self, context: AttemptContext, *, final: bool = False) -> None:
        # A busy producer must not starve cancellation or ownership heartbeats.
        remaining = 8
        while final or remaining > 0:
            chunk = self.stream.read(8192)
            if not chunk:
                break
            remaining -= 1
            self._append(context, self.decoder.decode(chunk))
        if final:
            self._append(context, self.decoder.decode(b"", final=True))

    def _append(self, context: AttemptContext, text: str) -> None:
        if text:
            context.runtime.append_attempt_event(
                context.attempt.attempt_id, self.event_type, EventSource.COMMAND, {"chunk": text}
            )


def _wait(
    context: AttemptContext,
    process: subprocess.Popen[bytes],
    timeout_seconds: float | None,
    outputs: tuple[_CommandOutput, _CommandOutput],
) -> AttemptStopReason | None:
    started = time.monotonic()
    heartbeat_due = started + ATTEMPT_HEARTBEAT_INTERVAL_SECONDS
    while process.poll() is None:
        for output in outputs:
            output.emit(context)
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
            if not context.heartbeat():
                terminate_process_tree(process)
                message = "The command attempt lost its durable worker ownership."
                raise PersistenceError(message, context={"node": context.attempt.scope_path})
            heartbeat_due = now + ATTEMPT_HEARTBEAT_INTERVAL_SECONDS
        control = context.runtime.claim_next_control(
            context.attempt.attempt_id,
            context.attempt.worker_id,
            (ControlKind.CANCEL.value,),
        )
        if control is not None:
            applied = context.runtime.apply_control(
                control.request_id,
                context.attempt.worker_id,
            )
            if applied and control.kind == ControlKind.CANCEL.value:
                terminate_process_tree(process)
                return cancel_stop_reason(control)
    return None


class CommandExecutor:
    """Execute one argv command and retain stdout, stderr, exit, timing, and outputs."""

    def execute(self, context: AttemptContext) -> ExecutionOutcome:
        node = parse_node(context, CommandNode)
        timeout = context.remaining_seconds()
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="relay-command-") as directory:
            stdout_path = Path(directory) / "stdout"
            stderr_path = Path(directory) / "stderr"
            with (
                stdout_path.open("wb") as stdout,
                stderr_path.open("wb") as stderr,
                stdout_path.open("rb") as stdout_reader,
                stderr_path.open("rb") as stderr_reader,
            ):
                # Independent readers cannot change the subprocesses' write offsets.
                outputs = (
                    _CommandOutput(stdout_reader, "command.stdout"),
                    _CommandOutput(stderr_reader, "command.stderr"),
                )
                process = _launch(context, node, stdout, stderr)
                try:
                    context.runtime.record_attempt_process(context.attempt.attempt_id, process.pid)
                    stop_reason = _wait(context, process, timeout, outputs)
                finally:
                    if process.poll() is None:
                        terminate_process_tree(process)
                    release_process_group(process.pid)
                    context.runtime.record_attempt_process(context.attempt.attempt_id, None)
                for output in outputs:
                    output.emit(context, final=True)

        duration_ms = round((time.monotonic() - started) * 1_000)
        context.runtime.append_attempt_event(
            context.attempt.attempt_id,
            "command.exit",
            EventSource.COMMAND,
            {"exit_code": process.returncode, "duration_ms": duration_ms},
        )
        if stop_reason is not None:
            if stop_reason is AttemptStopReason.CANCELED:
                error_code = "canceled"
            elif stop_reason is AttemptStopReason.INTERRUPTED:
                error_code = "interrupted"
            else:
                error_code = "node_timeout"
            return ExecutionOutcome(
                OutcomeKind.FAILED,
                stop_reason=stop_reason,
                exit_code=process.returncode,
                error_code=error_code,
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
