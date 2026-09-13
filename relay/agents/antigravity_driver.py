"""Native Antigravity headless adapter with machine-checked soft denies."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import time

from relay.constants import (
    ATTEMPT_HEARTBEAT_INTERVAL_SECONDS,
    CONTROL_POLL_INTERVAL_SECONDS,
    DEFAULT_ANTIGRAVITY_PRINT_TIMEOUT_SECONDS,
)
from relay.errors import (
    AgentAuthError,
    AgentProtocolError,
    ModelSelectionRejectedError,
    ModelUnavailableError,
    PersistenceError,
)
from relay.execution.nodes.base import declared_output_artifacts
from relay.execution.state import ControlKind
from relay.vcs.commits import current_head

from .acp_driver import _spawn, _terminate_process
from .events import AgentEvent, normalize_antigravity_event
from .mapping import map_agent_exception
from .models import (
    AgentCommand,
    AgentExecutionContext,
    AgentProfile,
    AgentResult,
    ModelObservation,
    ProbeRequirement,
    ProbeResult,
)

_MODEL_LIST_TIMEOUT_SECONDS = 15.0
_SOFT_DENY = re.compile(
    r"(?i)(?:\bdenied\b|soft[- ]?deny|requires approval|permission[^\n]*not granted)"
)
_ACTION_TARGET = re.compile(r"(?:write_file|delete_file|move_file|command)\(([^)]+)\)")
_PATH_TOKEN = re.compile(r"(?:[A-Za-z]:[\\/]|\.{0,2}/)[^\s\"']+")


def _prompt(context: AgentExecutionContext) -> str:
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
    return prompt_bytes + suffix


def _timeout_value(context: AgentExecutionContext) -> str:
    return context.node.timeout or f"{DEFAULT_ANTIGRAVITY_PRINT_TIMEOUT_SECONDS // 60}m"


def _argv(context: AgentExecutionContext) -> tuple[str, ...]:
    values = [
        context.command.executable,
        *context.command.args,
        "-p",
        _prompt(context),
        "--output-format",
        "stream-json",
        "--model",
        context.model_value,
        "--print-timeout",
        _timeout_value(context),
    ]
    if context.permission_profile == "auto_approve":
        values.append("--dangerously-skip-permissions")
    return tuple(values)


def _nested_strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for key, item in value.items():
            if isinstance(key, str):
                yield key
            yield from _nested_strings(item)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            yield from _nested_strings(item)


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


def _denied_targets(value: object, worktree: Path) -> tuple[str, ...]:
    strings = tuple(_nested_strings(value))
    if not any(_SOFT_DENY.search(item) for item in strings):
        return ()
    candidates: list[str] = []
    for item in strings:
        candidates.extend(_ACTION_TARGET.findall(item))
        candidates.extend(_PATH_TOKEN.findall(item))
    targets = {
        target for item in candidates if (target := _inside_worktree(item, worktree)) is not None
    }
    return tuple(sorted(targets))


def _model_rows(output: str) -> tuple[tuple[str, str], ...]:
    rows: list[tuple[str, str]] = []
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
    if stream is None:
        await queue.put((f"{kind}_done", None))
        return
    pending = bytearray()
    while chunk := await stream.read(8_192):
        parts = chunk.split(b"\n")
        pending.extend(parts[0])
        if len(parts) > 1:
            await queue.put((kind, bytes(pending).decode("utf-8", "backslashreplace")))
            for line in parts[1:-1]:
                await queue.put((kind, line.decode("utf-8", "backslashreplace")))
            pending = bytearray(parts[-1])
    if pending:
        await queue.put((kind, bytes(pending).decode("utf-8", "backslashreplace")))
    await queue.put((f"{kind}_done", None))


class AntigravityDriver:
    """One installed agy command using the documented stream-json interface."""

    def __init__(self, profile: AgentProfile, command: AgentCommand) -> None:
        self.profile: AgentProfile = profile
        self.command: AgentCommand = command
        self.process: asyncio.subprocess.Process | None = None
        self.result: AgentResult | None = None

    async def probe_models(
        self,
        requirements: tuple[ProbeRequirement, ...],
        cwd: Path,
    ) -> ProbeResult:
        """Check exact membership against a fresh bounded `agy models` result."""
        try:
            process = await asyncio.create_subprocess_exec(
                self.command.executable,
                *self.command.args,
                "models",
                cwd=str(cwd),
                env=os.environ.copy(),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=_MODEL_LIST_TIMEOUT_SECONDS
                )
            except TimeoutError:
                await _terminate_process(process)
                message = "Antigravity did not return its model list within 15 seconds."
                raise AgentProtocolError(
                    message,
                    context={"agent": self.profile.agent_id},
                ) from None
            error_text = stderr.decode("utf-8", "backslashreplace")
            if process.returncode != 0:
                if "auth" in error_text.lower() or "login" in error_text.lower():
                    message = "Antigravity requires authentication before model discovery."
                    raise AgentAuthError(  # noqa: TRY301
                        message,
                        context={"agent": self.profile.agent_id},
                    )
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
            failures = {
                requirement.model_value: (
                    f"{ModelUnavailableError.error_code}: Exact model "
                    f"{requirement.model_value!r} is not advertised by Antigravity."
                )
                for requirement in requirements
                if requirement.model_value not in advertised
            }
            return ProbeResult(
                self.profile.agent_id,
                observations,
                frozenset(
                    requirement.model_value
                    for requirement in requirements
                    if requirement.model_value in advertised
                ),
                failures,
            )
        except Exception as error:
            mapped = map_agent_exception(error, agent_id=self.profile.agent_id)
            return ProbeResult(
                self.profile.agent_id,
                failures={
                    requirement.model_value: f"{mapped.error_code}: {mapped.message}"
                    for requirement in requirements
                },
                general_error=f"{mapped.error_code}: {mapped.message}",
            )

    async def start_attempt(
        self,
        context: AgentExecutionContext,
    ) -> AsyncIterator[AgentEvent]:
        """Run one native headless process and retain every stdout/stderr byte."""
        if context.permission_profile not in self.profile.permission_profiles:
            message = f"Unsupported Antigravity permission profile {context.permission_profile!r}."
            raise AgentProtocolError(message, context={"agent": self.profile.agent_id})
        queue: asyncio.Queue[tuple[str, object]] = asyncio.Queue()
        denied: set[str] = set()
        terminal_status: str | None = None
        terminal_error: str | None = None
        readers: tuple[asyncio.Task[None], ...] = ()
        try:
            arguments = _argv(context)
            command = AgentCommand(arguments[0], arguments[1:])
            process = await _spawn(command, context.cwd)
            self.process = process
            await asyncio.to_thread(
                context.attempt.runtime.record_agent_session,
                context.attempt.attempt.attempt_id,
                process_id=process.pid,
                session_id=None,
                agent_version="",
                config_ids={"model": "native:model"},
            )
            readers = (
                asyncio.create_task(_read_lines(process.stdout, "stdout", queue)),
                asyncio.create_task(_read_lines(process.stderr, "stderr", queue)),
            )
            completed_streams = 0
            heartbeat_due = time.monotonic() + ATTEMPT_HEARTBEAT_INTERVAL_SECONDS
            while completed_streams < len(readers):
                try:
                    kind, value = await asyncio.wait_for(
                        queue.get(), timeout=CONTROL_POLL_INTERVAL_SECONDS
                    )
                except TimeoutError:
                    kind, value = "", None
                if kind.endswith("_done"):
                    completed_streams += 1
                elif kind == "stderr" and isinstance(value, str):
                    denied.update(_denied_targets(value, context.cwd))
                    yield AgentEvent("agent.stderr", {"text": value + "\n"})
                elif kind == "stdout" and isinstance(value, str):
                    yield AgentEvent("agent.provider_event", {"text": value + "\n"})
                    try:
                        raw: object = json.loads(value)
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
                    denied.update(_denied_targets(raw, context.cwd))
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
                        error = result.get("error")
                        terminal_error = error if isinstance(error, str) else None
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
                        await _terminate_process(process)
                        self.result = AgentResult(False, "canceled", process.returncode, "canceled")
                        return
                now = time.monotonic()
                if now >= heartbeat_due:
                    alive = await asyncio.to_thread(
                        context.attempt.runtime.heartbeat_attempt,
                        context.attempt.attempt.attempt_id,
                        context.attempt.attempt.worker_id,
                    )
                    if not alive:
                        await _terminate_process(process)
                        message = "The Antigravity attempt lost its durable worker ownership."
                        raise PersistenceError(  # noqa: TRY301
                            message, context={"node": context.attempt.attempt.scope_path}
                        )
                    heartbeat_due = now + ATTEMPT_HEARTBEAT_INTERVAL_SECONDS
            await asyncio.gather(*readers)
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
            succeeded = process.returncode == 0 and terminal_status == "SUCCESS" and not soft_denied
            error_code = None
            stop_reason = "completed"
            if soft_denied:
                error_code = "antigravity_soft_denied"
                stop_reason = "soft_denied"
            elif terminal_status == "CANCELED":
                error_code = "canceled"
                stop_reason = "canceled"
            elif terminal_status == "INTERRUPTED":
                error_code = AgentProtocolError.error_code
                stop_reason = "interrupted"
            elif terminal_error is not None and "timeout" in terminal_error.lower():
                error_code = "node_timeout"
                stop_reason = "timeout"
            elif not succeeded:
                error_code = (
                    AgentAuthError.error_code
                    if terminal_error is not None
                    and ("auth" in terminal_error.lower() or "login" in terminal_error.lower())
                    else AgentProtocolError.error_code
                )
                stop_reason = "failed"
            self.result = AgentResult(
                succeeded,
                stop_reason,
                process.returncode,
                error_code,
                tuple(sorted(denied)),
            )
        except Exception as error:
            if self.process is not None:
                await _terminate_process(self.process)
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
            if self.process is not None and self.process.returncode is None:
                await _terminate_process(self.process)
            if readers:
                await asyncio.gather(*readers, return_exceptions=True)
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
            await _terminate_process(self.process)

    async def finalize(self) -> AgentResult:
        if self.result is None:
            message = "Antigravity ended without a terminal stream-json result."
            raise AgentProtocolError(message, context={"agent": self.profile.agent_id})
        return self.result


__all__ = ["AntigravityDriver"]
