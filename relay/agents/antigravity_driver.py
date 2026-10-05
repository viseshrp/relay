"""Native Antigravity headless adapter with machine-checked soft denies."""

from __future__ import annotations

import asyncio
import codecs
from collections.abc import AsyncIterator
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import time

from relay.constants import (
    AGENT_EVENT_QUEUE_MAX_ITEMS,
    AGENT_STREAM_LINE_MAX_BYTES,
    ANTIGRAVITY_PROMPT_MAX_BYTES,
    ATTEMPT_HEARTBEAT_INTERVAL_SECONDS,
    CONTROL_POLL_INTERVAL_SECONDS,
    DEFAULT_ANTIGRAVITY_PRINT_TIMEOUT_SECONDS,
    PROCESS_STREAM_CHUNK_BYTES,
    WINDOWS_BATCH_COMMAND_MAX_CHARS,
    WINDOWS_COMMAND_MAX_CHARS,
)
from relay.errors import (
    AgentProtocolError,
    ModelSelectionRejectedError,
    ModelUnavailableError,
    NodeExecutionError,
    PersistenceError,
)
from relay.execution.cancellation import (
    discard_process_stream,
    release_process_group,
    spawn_process,
    terminate_async_process_tree,
)
from relay.execution.control import cancel_stop_reason
from relay.execution.nodes.base import declared_output_artifacts
from relay.execution.state import ControlKind
from relay.execution.timing import attempt_deadline, duration_seconds
from relay.vcs.commits import current_head

from .configuration import native_configuration, validate_native_requirement
from .events import AgentEvent, normalize_antigravity_event
from .mapping import map_agent_exception
from .models import (
    AgentCommand,
    AgentExecutionContext,
    AgentProfile,
    AgentResult,
    ModelObservation,
    ProbeFailure,
    ProbeRequirement,
    ProbeResult,
)

_MODEL_LIST_TIMEOUT_SECONDS = 15.0
_SOFT_DENY = re.compile(
    r"(?i)(?:\bdenied\b|soft[- ]?deny|requires approval|permission[^\n]*not granted)"
)
_ACTION_TARGET = re.compile(r"(?:write_file|delete_file|move_file|command)\(([^)]+)\)")


def _prompt(context: AgentExecutionContext) -> str:
    """`Review.\n` is followed by `--- Relay inputs (JSON) ---\n{...}`."""
    prompt_bytes = "".join(context.attempt.attempt.prompt_contents)
    sections = (
        ("Relay inputs", context.attempt.attempt.inputs),
        ("Relay run metadata", context.attempt.attempt.run_metadata),
        ("Relay upstream outputs", context.attempt.attempt.upstream_outputs),
    )
    suffix = "".join(
        f"\n\n--- {heading} (JSON) ---\n{json.dumps(value, sort_keys=True, ensure_ascii=False)}"
        for heading, value in sections
    )
    workspace = f"\n\n{context.workspace_instructions()}"
    outputs = context.output_instructions()
    return prompt_bytes + suffix + workspace + (f"\n\n{outputs}" if outputs else "")


def _timeout_value(context: AgentExecutionContext) -> str:
    """A node's `15m` remains `15m`; an absent timeout becomes `5m`."""
    return context.node.timeout or f"{DEFAULT_ANTIGRAVITY_PRINT_TIMEOUT_SECONDS // 60}m"


def _argv(context: AgentExecutionContext, prompt: str) -> tuple[str, ...]:
    """Bound the stdin prompt separately from the platform command line."""
    prompt_bytes = len(prompt.encode("utf-8"))
    if prompt_bytes > ANTIGRAVITY_PROMPT_MAX_BYTES:
        message = "The composed Antigravity prompt exceeds Relay's UTF-8 byte limit."
        # Error context carries decimal strings: 1200000 bytes becomes "1200000".
        raise NodeExecutionError(
            message,
            context={
                "prompt_bytes": str(prompt_bytes),
                "max_bytes": str(ANTIGRAVITY_PROMPT_MAX_BYTES),
            },
            next_action="Reduce prompt files, inputs, or upstream output.",
        )
    values = [
        context.command.executable,
        *context.command.args,
        "--input-format",
        "stream-json",
        "--output-format",
        "stream-json",
        "--model",
        context.model_value,
        "--print-timeout",
        _timeout_value(context),
    ]
    validate_native_requirement(
        native_configuration(context.agent_id, context.model_value),
        ProbeRequirement(context.model_value, context.effort, context.permission_mode),
    )
    if context.effort is not None:
        values.extend(("--effort", context.effort))
    if context.permission_mode in {"accept-edits", "plan"}:
        values.extend(("--mode", context.permission_mode))
    if (context.permission_mode or context.permission_profile) == "auto_approve":
        values.append("--dangerously-skip-permissions")
    if os.name == "nt":
        # CreateProcess counts UTF-16 units, including the terminating NUL.
        # For example, one emoji consumes two units, while ASCII consumes one.
        command = subprocess.list2cmdline(values)
        size = len(command.encode("utf-16-le")) // 2 + 1
        limit = WINDOWS_COMMAND_MAX_CHARS
        if Path(values[0]).suffix.lower() in {".cmd", ".bat"}:
            # Reserve cmd.exe's wrapper and quoting within its smaller limit.
            size += len('cmd.exe /c """"')
            limit = WINDOWS_BATCH_COMMAND_MAX_CHARS
        if size > limit:
            message = "The Antigravity command exceeds the Windows command-line limit."
            raise NodeExecutionError(
                message, next_action="Shorten the agent command arguments or exact model value."
            )
    return tuple(values)


async def _send_prompt(process: asyncio.subprocess.Process, prompt: str) -> None:
    """Send `Review.\nNext.` as one JSON content string with an escaped newline."""
    stream = process.stdin
    if stream is None:
        message = "Antigravity's prompt input pipe is unavailable."
        raise AgentProtocolError(message)
    frame = {"event": "user", "message": {"content": prompt}}
    payload = (json.dumps(frame, ensure_ascii=False) + "\n").encode("utf-8")
    try:
        stream.write(payload)
        await stream.drain()
    finally:
        # EOF ends the documented streaming session after this single turn.
        stream.close()
    await stream.wait_closed()


def _inside_worktree(target: str, worktree: Path) -> str | None:
    cleaned = target.strip().strip("`'\"")
    if not cleaned:
        return None
    candidate = Path(cleaned)
    resolved = (candidate if candidate.is_absolute() else worktree / candidate).resolve()
    try:
        relative = resolved.relative_to(worktree.resolve())
    except ValueError:
        return None
    return relative.as_posix()


def _denied_targets(notice: str, worktree: Path) -> tuple[str, ...]:
    """A stderr notice `denied write_file(src/a.py)` yields (`src/a.py`,)."""
    if not _SOFT_DENY.search(notice):
        return ()
    # Only a complete stderr tool notice is eligible. Natural-language stdout
    # and partial raw chunks must never become permission decisions.
    candidates = _ACTION_TARGET.findall(notice)
    targets = {
        target for item in candidates if (target := _inside_worktree(item, worktree)) is not None
    }
    return tuple(sorted(targets))


def _model_rows(output: str) -> tuple[tuple[str, str], ...]:
    """`gemini-pro Gemini Pro\n` becomes ((`gemini-pro`, `Gemini Pro`),)."""
    rows = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("Available", "MODEL", "─", "-")):
            continue
        fields = line.split(maxsplit=1)
        value = fields[0]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value):
            continue
        rows.append((value, fields[1].strip() if len(fields) == 2 else value))
    return tuple(rows)


async def _read_lines(
    stream: asyncio.StreamReader | None,
    kind: str,
    queue: asyncio.Queue[tuple[str, object]],
) -> None:
    """Retain raw bytes in bounded chunks and parse only bounded NDJSON lines."""
    if stream is None:
        await queue.put((f"{kind}_done", None))
        return
    pending = bytearray()
    oversized = False
    decoder = codecs.getincrementaldecoder("utf-8")(errors="backslashreplace")

    async def finish_line() -> None:
        nonlocal pending, oversized
        if oversized:
            await queue.put((f"{kind}_oversized", None))
        else:
            await queue.put((f"{kind}_line", bytes(pending).decode("utf-8", "backslashreplace")))
        pending = bytearray()
        oversized = False

    while chunk := await stream.read(PROCESS_STREAM_CHUNK_BYTES):
        visible = decoder.decode(chunk)
        if visible:
            await queue.put((f"{kind}_raw", visible))
        parts = chunk.split(b"\n")
        for index, part in enumerate(parts):
            if not oversized:
                if len(pending) + len(part) <= AGENT_STREAM_LINE_MAX_BYTES:
                    pending.extend(part)
                else:
                    pending = bytearray()
                    oversized = True
            if index < len(parts) - 1:
                await finish_line()
    tail = decoder.decode(b"", final=True)
    if tail:
        await queue.put((f"{kind}_raw", tail))
    if pending or oversized:
        await finish_line()
    await queue.put((f"{kind}_done", None))


async def _drain_raw_events(
    queue: asyncio.Queue[tuple[str, object]],
    readers: tuple[asyncio.Task[None], ...],
) -> AsyncIterator[AgentEvent]:
    """Drain bytes already read after a protocol failure without parsing them."""
    while any(not task.done() for task in readers) or not queue.empty():
        try:
            kind, value = await asyncio.wait_for(queue.get(), timeout=CONTROL_POLL_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            continue
        if kind == "stderr_raw" and isinstance(value, str):
            yield AgentEvent("agent.stderr", {"text": value})
        elif kind == "stdout_raw" and isinstance(value, str):
            yield AgentEvent("agent.provider_event", {"text": value})
    await asyncio.gather(*readers, return_exceptions=True)


class AntigravityDriver:
    """One installed agy command using the documented stream-json interface."""

    profile: AgentProfile
    command: AgentCommand
    process: asyncio.subprocess.Process | None
    result: AgentResult | None

    def __init__(self, profile: AgentProfile, command: AgentCommand) -> None:
        self.profile = profile
        self.command = command
        self.process = None
        self.result = None

    async def probe_models(
        self,
        requirements: tuple[ProbeRequirement, ...],
        cwd: Path,
    ) -> ProbeResult:
        """Check exact membership against a fresh bounded `agy models` result."""
        try:
            process = await spawn_process((*self.command.argv(), "models"), cwd, input_pipe=False)
            communication = asyncio.create_task(process.communicate())
            try:
                stdout, _stderr = await asyncio.wait_for(
                    asyncio.shield(communication), timeout=_MODEL_LIST_TIMEOUT_SECONDS
                )
            except asyncio.TimeoutError:
                await terminate_async_process_tree(process)
                await communication
                message = "Antigravity did not return its model list within 15 seconds."
                raise AgentProtocolError(
                    message,
                    context={"agent": self.profile.agent_id},
                ) from None
            except asyncio.CancelledError:
                await terminate_async_process_tree(process)
                await communication
                raise
            if process.returncode != 0:
                message = "Antigravity model discovery failed."
                raise AgentProtocolError(  # noqa: TRY301
                    message,
                    context={"agent": self.profile.agent_id},
                )
            rows = _model_rows(stdout.decode("utf-8", "backslashreplace"))
            observed_at = datetime.now(timezone.utc)
            observations = tuple(
                ModelObservation(
                    self.profile.agent_id,
                    value,
                    name,
                    "native:model",
                    "",
                    observed_at,
                )
                for value, name in rows
            )
            advertised = {value for value, _name in rows}
            configurations = {
                value: native_configuration(self.profile.agent_id, value) for value in advertised
            }
            failures = {
                requirement.model_value: (
                    ProbeFailure(
                        ModelUnavailableError.error_code,
                        f"Exact model {requirement.model_value!r} is not advertised "
                        "by Antigravity.",
                    )
                )
                for requirement in requirements
                if requirement.model_value not in advertised
            }
            confirmed_requirements = set()
            requirement_failures = {}
            for requirement in requirements:
                if requirement.model_value not in advertised:
                    requirement_failures[requirement] = failures[requirement.model_value]
                    continue
                try:
                    validate_native_requirement(
                        configurations[requirement.model_value], requirement
                    )
                except Exception as error:
                    mapped = map_agent_exception(error, agent_id=self.profile.agent_id)
                    requirement_failures[requirement] = ProbeFailure.from_error(mapped)
                    failures[requirement.model_value] = ProbeFailure.from_error(mapped)
                else:
                    confirmed_requirements.add(requirement)
            return ProbeResult(
                self.profile.agent_id,
                observations,
                frozenset(
                    requirement.model_value
                    for requirement in requirements
                    if requirement in confirmed_requirements
                ),
                failures,
                configurations=configurations,
                confirmed_requirements=frozenset(confirmed_requirements),
                requirement_failures=requirement_failures,
            )
        except Exception as error:
            mapped = map_agent_exception(error, agent_id=self.profile.agent_id)
            return ProbeResult(
                self.profile.agent_id,
                failures={
                    requirement.model_value: ProbeFailure.from_error(mapped)
                    for requirement in requirements
                },
                general_error=ProbeFailure.from_error(mapped),
            )

    async def start_attempt(
        self,
        context: AgentExecutionContext,
    ) -> AsyncIterator[AgentEvent]:
        """Run one native headless process and retain every stdout/stderr byte."""
        if context.permission_profile not in self.profile.permission_profiles:
            message = f"Unsupported Antigravity permission profile {context.permission_profile!r}."
            raise AgentProtocolError(message, context={"agent": self.profile.agent_id})
        queue = asyncio.Queue(maxsize=AGENT_EVENT_QUEUE_MAX_ITEMS)
        denied = set()
        terminal_status = None
        terminal_timed_out = False
        requested_stop = None
        readers = ()
        stopper = None
        sender = None
        try:
            prompt = _prompt(context)
            arguments = _argv(context, prompt)
            # agy reports failures as ERROR plus free text, without a documented
            # timeout code. Enforce its advertised print ceiling locally as well.
            print_deadline = attempt_deadline(_timeout_value(context), context.attempt.deadline_at)
            print_limit = duration_seconds(_timeout_value(context))
            command = AgentCommand(arguments[0], arguments[1:])
            resources = context.attempt.resources
            process = await spawn_process(
                command.argv(),
                context.cwd,
                environment=resources.environment() if resources is not None else None,
            )
            self.process = process
            readers = (
                asyncio.create_task(_read_lines(process.stdout, "stdout", queue)),
                asyncio.create_task(_read_lines(process.stderr, "stderr", queue)),
            )
            # Feed stdin alongside both drains: a provider may write startup
            # diagnostics before reading a prompt larger than the pipe buffer.
            sender = asyncio.create_task(_send_prompt(process, prompt))
            await asyncio.to_thread(
                context.attempt.runtime.record_agent_session,
                context.attempt.attempt.attempt_id,
                process_id=process.pid,
                session_id=None,
                agent_version="",
                config_ids={"model": "native:model"},
            )
            completed_streams = 0
            heartbeat_due = time.monotonic() + ATTEMPT_HEARTBEAT_INTERVAL_SECONDS
            while completed_streams < len(readers):
                try:
                    kind, value = await asyncio.wait_for(
                        queue.get(), timeout=CONTROL_POLL_INTERVAL_SECONDS
                    )
                except asyncio.TimeoutError:
                    kind, value = "", None
                if kind.endswith("_done"):
                    completed_streams += 1
                elif kind == "stderr_raw" and isinstance(value, str):
                    yield AgentEvent("agent.stderr", {"text": value})
                elif kind == "stderr_line" and isinstance(value, str):
                    denied.update(_denied_targets(value, context.cwd))
                elif kind == "stderr_oversized":
                    message = "Antigravity emitted a stderr line above Relay's byte limit."
                    raise AgentProtocolError(  # noqa: TRY301
                        message, context={"agent": self.profile.agent_id}
                    )
                elif kind == "stdout_raw" and isinstance(value, str):
                    yield AgentEvent("agent.provider_event", {"text": value})
                elif kind == "stdout_oversized":
                    message = "Antigravity emitted a stream-json line above Relay's byte limit."
                    raise AgentProtocolError(  # noqa: TRY301
                        message, context={"agent": self.profile.agent_id}
                    )
                elif kind == "stdout_line" and isinstance(value, str):
                    try:
                        raw = json.loads(value)
                    except json.JSONDecodeError:
                        message = "Antigravity emitted a malformed stream-json line."
                        raise AgentProtocolError(
                            message, context={"agent": self.profile.agent_id}
                        ) from None
                    if not isinstance(raw, dict):
                        message = "Antigravity emitted a non-object stream-json line."
                        raise AgentProtocolError(  # noqa: TRY301
                            message, context={"agent": self.profile.agent_id}
                        )
                    init = raw.get("init") if raw.get("event") == "init" else None
                    if isinstance(init, dict):
                        observed_model = init.get("model")
                        if (
                            isinstance(observed_model, str)
                            and observed_model != context.model_value
                        ):
                            message = "Antigravity reported a model different from the route."
                            raise ModelSelectionRejectedError(  # noqa: TRY301
                                message, context={"agent": self.profile.agent_id}
                            )
                    for event in normalize_antigravity_event(raw):
                        yield event
                    result = raw.get("result") if raw.get("event") == "result" else None
                    if isinstance(result, dict):
                        status = result.get("status")
                        terminal_status = status if isinstance(status, str) else None
                        elapsed = result.get("duration_seconds")
                        # The documented numeric duration proves expiry without
                        # interpreting prose such as "timeout configuration failed".
                        terminal_timed_out = (
                            terminal_status == "ERROR"
                            and print_limit is not None
                            and isinstance(elapsed, (int, float))
                            and not isinstance(elapsed, bool)
                            and elapsed >= print_limit
                        )
                if requested_stop is None:
                    control = await asyncio.to_thread(
                        context.attempt.runtime.claim_next_control,
                        context.attempt.attempt.attempt_id,
                        context.attempt.attempt.worker_id,
                        (ControlKind.CANCEL.value,),
                    )
                    if control is not None:
                        applied = await asyncio.to_thread(
                            context.attempt.runtime.apply_control,
                            control.request_id,
                            context.attempt.attempt.worker_id,
                        )
                        if applied:
                            reason = cancel_stop_reason(control)
                            requested_stop = reason.value
                            stopper = asyncio.create_task(terminate_async_process_tree(process))
                now = time.monotonic()
                if requested_stop is None and (
                    context.attempt.timed_out()
                    or (
                        print_deadline is not None
                        and now >= print_deadline
                        and terminal_status != "SUCCESS"
                        and process.returncode is None
                    )
                ):
                    requested_stop = "timeout"
                    stopper = asyncio.create_task(terminate_async_process_tree(process))
                if now >= heartbeat_due:
                    alive = await asyncio.to_thread(
                        context.attempt.heartbeat,
                    )
                    if not alive:
                        message = "The Antigravity attempt lost its durable worker ownership."
                        raise PersistenceError(  # noqa: TRY301
                            message, context={"node": context.attempt.attempt.scope_path}
                        )
                    heartbeat_due = now + ATTEMPT_HEARTBEAT_INTERVAL_SECONDS
                if requested_stop is None and sender.done():
                    await sender
            await asyncio.gather(*readers)
            if stopper is not None:
                await stopper
            if requested_stop is None:
                await sender
            await process.wait()
            required = set(declared_output_artifacts(context.node.outputs).values())
            denied_required = any(
                requested == target
                or requested.startswith(target.rstrip("/") + "/")
                or target.startswith(requested.rstrip("/") + "/")
                for requested in required
                for target in denied
            )
            denied_without_commit = (
                context.node.writes
                and bool(denied)
                and current_head(context.cwd) == context.attempt.attempt.starting_head
            )
            soft_denied = context.node.writes and (denied_required or denied_without_commit)
            succeeded = (
                requested_stop is None
                and process.returncode == 0
                and terminal_status == "SUCCESS"
                and not soft_denied
            )
            error_code = None
            stop_reason = "completed"
            if requested_stop is not None:
                error_code = "node_timeout" if requested_stop == "timeout" else requested_stop
                stop_reason = requested_stop
            elif terminal_timed_out:
                error_code = "node_timeout"
                stop_reason = "timeout"
            elif soft_denied:
                error_code = "antigravity_soft_denied"
                stop_reason = "soft_denied"
            elif terminal_status == "CANCELED":
                error_code = "canceled"
                stop_reason = "canceled"
            elif terminal_status == "INTERRUPTED":
                error_code = AgentProtocolError.error_code
                stop_reason = "interrupted"
            elif not succeeded:
                error_code = AgentProtocolError.error_code
                stop_reason = "failed"
            self.result = AgentResult(
                succeeded,
                stop_reason,
                process.returncode,
                error_code,
                tuple(sorted(denied)),
            )
        except Exception as error:
            if self.process is not None and stopper is None:
                stopper = asyncio.create_task(terminate_async_process_tree(self.process))
            if readers:
                async for pending_event in _drain_raw_events(queue, readers):
                    yield pending_event
                readers = ()
            if stopper is not None:
                await stopper
            mapped = map_agent_exception(error, agent_id=self.profile.agent_id)
            self.result = AgentResult(
                False,
                "failed",
                self.process.returncode if self.process is not None else None,
                mapped.error_code,
                tuple(sorted(denied)),
            )
            raise mapped from None
        finally:
            if self.process is not None and self.process.returncode is not None:
                release_process_group(self.process.pid)
            if sender is not None:
                if not sender.done():
                    sender.cancel()
                await asyncio.gather(sender, return_exceptions=True)
            if readers:
                for reader in readers:
                    if not reader.done():
                        # A closed consumer cannot drain the bounded queue.
                        reader.cancel()
                await asyncio.gather(*readers, return_exceptions=True)
            if self.process is not None and self.process.returncode is None:
                # A closed generator has no queue consumer. Direct drains keep
                # pipe backpressure from blocking the bounded process wait.
                drains = (
                    asyncio.create_task(discard_process_stream(self.process.stdout)),
                    asyncio.create_task(discard_process_stream(self.process.stderr)),
                )
                try:
                    await terminate_async_process_tree(self.process)
                finally:
                    release_process_group(self.process.pid)
                    for drain in drains:
                        if self.process.returncode is None:
                            drain.cancel()
                    await asyncio.gather(*drains, return_exceptions=True)
            await asyncio.to_thread(
                context.attempt.runtime.record_agent_session,
                context.attempt.attempt.attempt_id,
                process_id=None,
                session_id=None,
                agent_version="",
                config_ids={"model": "native:model"},
            )

    async def cancel(self) -> None:
        if self.process is not None:
            await terminate_async_process_tree(self.process)

    async def finalize(self) -> AgentResult:
        if self.result is None:
            message = "Antigravity ended without a terminal stream-json result."
            raise AgentProtocolError(message, context={"agent": self.profile.agent_id})
        return self.result


__all__ = ["AntigravityDriver"]
