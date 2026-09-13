"""ACP client adapter with exact-model proof and durable owner interactions."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import signal
import subprocess
import time
from typing import TypeAlias

import acp
from acp import RequestError, schema

from relay._version import __version__
from relay.constants import (
    ATTEMPT_HEARTBEAT_INTERVAL_SECONDS,
    CANCELLATION_GRACE_SECONDS,
    CONTROL_POLL_INTERVAL_SECONDS,
)
from relay.errors import (
    AgentAuthError,
    AgentProtocolError,
    ModelSelectionRejectedError,
    ModelSelectorError,
    ModelUnavailableError,
    PermissionFlowError,
    PersistenceError,
    RelayError,
)
from relay.execution.control import ClaimedControl
from relay.execution.nodes.base import duration_seconds
from relay.execution.state import ControlKind, InteractionKind

from .events import AgentEvent, normalize_acp_update
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

LOGGER = logging.getLogger(__name__)
_AUTH_REQUIRED_CODE = RequestError.auth_required().code
_PROCESS_EXIT_GRACE_SECONDS = 2.0

SessionUpdate: TypeAlias = (
    schema.UserMessageChunk
    | schema.AgentMessageChunk
    | schema.AgentThoughtChunk
    | schema.ToolCallStart
    | schema.ToolCallProgress
    | schema.AgentPlanUpdate
    | schema.AgentPlanContentUpdate
    | schema.AgentPlanRemovedUpdate
    | schema.AvailableCommandsUpdate
    | schema.CurrentModeUpdate
    | schema.ConfigOptionUpdate
    | schema.SessionInfoUpdate
    | schema.UsageUpdate
)
SessionConfigOption: TypeAlias = (
    schema.SessionConfigOptionSelect | schema.SessionConfigOptionBoolean
)


def _model_options(option: schema.SessionConfigOptionSelect) -> tuple[tuple[str, str], ...]:
    result: list[tuple[str, str]] = []
    for item in option.options:
        if isinstance(item, schema.SessionConfigSelectGroup):
            result.extend((child.value, child.name) for child in item.options)
        elif isinstance(item, schema.SessionConfigSelectOption):
            result.append((item.value, item.name))
    return tuple(result)


def _model_selector(
    options: Sequence[SessionConfigOption],
    profile: AgentProfile,
) -> schema.SessionConfigOptionSelect:
    selects = [item for item in options if isinstance(item, schema.SessionConfigOptionSelect)]
    if profile.model_config_id is not None:
        matches = [item for item in selects if item.id == profile.model_config_id]
    else:
        matches = [item for item in selects if item.category == "model"]
    if len(matches) != 1:
        message = f"Agent {profile.agent_id!r} did not expose one identifiable model selector."
        raise ModelSelectorError(message, context={"agent": profile.agent_id})
    return matches[0]


def _selected_value(
    options: Sequence[SessionConfigOption],
    config_id: str,
) -> str | None:
    match = next(
        (
            item
            for item in options
            if isinstance(item, schema.SessionConfigOptionSelect) and item.id == config_id
        ),
        None,
    )
    return match.current_value if match is not None else None


def _capabilities(profile: AgentProfile) -> schema.ClientCapabilities:
    methods = profile.required_client_methods
    return schema.ClientCapabilities(
        fs=schema.FileSystemCapabilities(
            readTextFile="fs/read_text_file" in methods,
            writeTextFile="fs/write_text_file" in methods,
        ),
        terminal="terminal" in methods,
        auth=schema.AuthCapabilities(terminal=False),
        elicitation=schema.ElicitationCapabilities(
            form=schema.ElicitationFormCapabilities(),
            url=schema.ElicitationUrlCapabilities(),
        ),
    )


def _prompt_blocks(context: AgentExecutionContext) -> list[schema.TextContentBlock]:
    blocks = [
        schema.TextContentBlock(type="text", text=value)
        for value in context.attempt.attempt.prompt_contents
    ]
    values = (
        ("Relay inputs", context.attempt.attempt.inputs),
        ("Relay run metadata", context.attempt.attempt.run_metadata),
        ("Relay upstream outputs", context.attempt.attempt.upstream_outputs),
    )
    blocks.extend(
        schema.TextContentBlock(
            type="text",
            text=f"{heading} (JSON):\n{json.dumps(value, sort_keys=True, ensure_ascii=False)}",
        )
        for heading, value in values
    )
    return blocks


async def _terminate_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    if os.name != "nt":
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
    else:
        with suppress(ProcessLookupError):
            process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=CANCELLATION_GRACE_SECONDS)
    except TimeoutError:
        if os.name != "nt":
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
        else:
            with suppress(ProcessLookupError):
                process.kill()
        await process.wait()


async def _spawn(command: AgentCommand, cwd: Path) -> asyncio.subprocess.Process:
    if os.name == "nt":
        return await asyncio.create_subprocess_exec(
            *command.argv(),
            cwd=str(cwd),
            env=os.environ.copy(),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
    return await asyncio.create_subprocess_exec(
        *command.argv(),
        cwd=str(cwd),
        env=os.environ.copy(),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )


class RelayAcpClient:
    """ACP callbacks backed by the exact attempt's durable control mailbox."""

    agent: acp.Agent | None

    def __init__(
        self,
        context: AgentExecutionContext | None,
        profile: AgentProfile,
        event_queue: asyncio.Queue[AgentEvent] | None = None,
    ) -> None:
        self.context: AgentExecutionContext | None = context
        self.profile: AgentProfile = profile
        self.event_queue: asyncio.Queue[AgentEvent] | None = event_queue
        self.agent = None
        self.session_id: str | None = None
        self.expected_model: str | None = None
        self.model_config_id: str | None = None
        self.drift_error: RelayError | None = None

    def on_connect(self, conn: acp.Agent) -> None:
        self.agent = conn

    async def request_permission(
        self,
        session_id: str,
        tool_call: schema.ToolCallUpdate,
        options: list[schema.PermissionOption],
        **kwargs: object,
    ) -> schema.RequestPermissionResponse:
        del kwargs
        if self.context is None or session_id != self.session_id:
            raise RequestError.invalid_request()
        safe_options = tuple(
            {"id": option.option_id, "name": option.name, "kind": option.kind} for option in options
        )
        await asyncio.to_thread(
            self.context.attempt.runtime.request_agent_interaction,
            self.context.attempt.attempt.attempt_id,
            InteractionKind.PERMISSION.value,
            tool_call.title or "The agent requests permission to use a tool.",
            safe_options,
        )
        control = await self._wait_for_control(
            (ControlKind.PERMISSION_ANSWER.value, ControlKind.CANCEL.value)
        )
        if control.kind == ControlKind.CANCEL.value:
            await self._cancel_session()
            return schema.RequestPermissionResponse(
                outcome=schema.DeniedOutcome(outcome="cancelled")
            )
        decision = control.payload.get("decision")
        option_ids = {option.option_id for option in options}
        if not isinstance(decision, str) or decision not in option_ids:
            message = "The permission answer does not name an offered ACP option."
            raise PermissionFlowError(message)
        return schema.RequestPermissionResponse(
            outcome=schema.AllowedOutcome(outcome="selected", optionId=decision)
        )

    async def session_update(
        self,
        session_id: str,
        update: SessionUpdate,
        **kwargs: object,
    ) -> None:
        del kwargs
        if self.session_id is not None and session_id != self.session_id:
            raise RequestError.invalid_request()
        if (
            isinstance(update, schema.ConfigOptionUpdate)
            and self.model_config_id is not None
            and self.expected_model is not None
        ):
            current = _selected_value(update.config_options, self.model_config_id)
            if current != self.expected_model:
                self.drift_error = ModelSelectionRejectedError(
                    "The agent changed away from the snapshotted exact model.",
                    context={"agent": self.profile.agent_id},
                )
                await self._cancel_session()
        if self.event_queue is not None:
            for event in normalize_acp_update(update):
                await self.event_queue.put(event)

    async def _wait_for_control(self, kinds: tuple[str, ...]) -> ClaimedControl:
        if self.context is None:
            raise RequestError.invalid_request()
        attempt = self.context.attempt.attempt
        heartbeat_due = time.monotonic() + ATTEMPT_HEARTBEAT_INTERVAL_SECONDS
        while True:
            control = await asyncio.to_thread(
                self.context.attempt.runtime.claim_next_control,
                attempt.attempt_id,
                attempt.worker_id,
                kinds,
            )
            if control is not None:
                applied = await asyncio.to_thread(
                    self.context.attempt.runtime.apply_control,
                    control.request_id,
                    attempt.worker_id,
                )
                if applied:
                    return control
            now = time.monotonic()
            if now >= heartbeat_due:
                alive = await asyncio.to_thread(
                    self.context.attempt.runtime.heartbeat_attempt,
                    attempt.attempt_id,
                    attempt.worker_id,
                )
                if not alive:
                    message = "The ACP attempt lost its durable worker ownership."
                    raise PersistenceError(message, context={"node": attempt.scope_path})
                heartbeat_due = now + ATTEMPT_HEARTBEAT_INTERVAL_SECONDS
            await asyncio.sleep(CONTROL_POLL_INTERVAL_SECONDS)

    async def _cancel_session(self) -> None:
        if self.agent is not None and self.session_id is not None:
            with suppress(Exception):
                await self.agent.cancel(self.session_id)

    async def create_elicitation(
        self,
        message: str,
        mode: schema.ElicitationMode,
        **kwargs: object,
    ) -> schema.CreateElicitationResponse:
        del kwargs
        if self.context is None:
            raise RequestError.invalid_request()
        mode_payload = mode.model_dump(mode="json", by_alias=True)
        await asyncio.to_thread(
            self.context.attempt.runtime.request_agent_interaction,
            self.context.attempt.attempt.attempt_id,
            InteractionKind.ELICITATION.value,
            message,
            ({"mode": mode_payload},),
        )
        control = await self._wait_for_control(
            (ControlKind.ELICITATION_ANSWER.value, ControlKind.CANCEL.value)
        )
        if control.kind == ControlKind.CANCEL.value:
            await self._cancel_session()
            return schema.CancelElicitationResponse(action="cancel")
        value = control.payload.get("value")
        if value is None:
            return schema.DeclineElicitationResponse(action="decline")
        if not isinstance(value, dict):
            message = "An ACP form elicitation answer must be a JSON object."
            raise PermissionFlowError(message)
        return schema.AcceptElicitationResponse(action="accept", content=value)

    async def complete_elicitation(self, elicitation_id: str, **kwargs: object) -> None:
        del elicitation_id, kwargs

    async def write_text_file(
        self,
        session_id: str,
        path: str,
        content: str,
        **kwargs: object,
    ) -> schema.WriteTextFileResponse:
        del session_id, path, content, kwargs
        raise RequestError.method_not_found("fs/write_text_file")

    async def read_text_file(
        self,
        session_id: str,
        path: str,
        line: int | None = None,
        limit: int | None = None,
        **kwargs: object,
    ) -> schema.ReadTextFileResponse:
        del session_id, path, line, limit, kwargs
        raise RequestError.method_not_found("fs/read_text_file")

    async def create_terminal(
        self,
        session_id: str,
        command: str,
        args: list[str] | None = None,
        env: list[schema.EnvVariable] | None = None,
        cwd: str | None = None,
        output_byte_limit: int | None = None,
        **kwargs: object,
    ) -> schema.CreateTerminalResponse:
        del session_id, command, args, env, cwd, output_byte_limit, kwargs
        raise RequestError.method_not_found("terminal/create")

    async def terminal_output(
        self, session_id: str, terminal_id: str, **kwargs: object
    ) -> schema.TerminalOutputResponse:
        del session_id, terminal_id, kwargs
        raise RequestError.method_not_found("terminal/output")

    async def release_terminal(
        self, session_id: str, terminal_id: str, **kwargs: object
    ) -> schema.ReleaseTerminalResponse:
        del session_id, terminal_id, kwargs
        raise RequestError.method_not_found("terminal/release")

    async def wait_for_terminal_exit(
        self, session_id: str, terminal_id: str, **kwargs: object
    ) -> schema.WaitForTerminalExitResponse:
        del session_id, terminal_id, kwargs
        raise RequestError.method_not_found("terminal/wait_for_exit")

    async def kill_terminal(
        self, session_id: str, terminal_id: str, **kwargs: object
    ) -> schema.KillTerminalResponse:
        del session_id, terminal_id, kwargs
        raise RequestError.method_not_found("terminal/kill")

    async def ext_method(self, method: str, params: dict[str, object]) -> dict[str, object]:
        del params
        raise RequestError.method_not_found(method)

    async def ext_notification(self, method: str, params: dict[str, object]) -> None:
        del method, params


@asynccontextmanager
async def _connection(
    command: AgentCommand,
    cwd: Path,
    client: RelayAcpClient,
) -> AsyncIterator[tuple[acp.ClientSideConnection, asyncio.subprocess.Process]]:
    process = await _spawn(command, cwd)
    if process.stdin is None or process.stdout is None:
        await _terminate_process(process)
        message = "The ACP process did not expose both protocol streams."
        raise AgentProtocolError(message, context={"agent": client.profile.agent_id})
    # Session cleanup capabilities in SDK 0.12.1 remain behind its negotiated
    # unstable router even though the wire protocol version stays at 1.
    connection = acp.connect_to_agent(
        client, process.stdin, process.stdout, use_unstable_protocol=True
    )
    try:
        yield connection, process
    finally:
        with suppress(Exception):
            await connection.close()
        if process.stdin is not None:
            process.stdin.close()
            with suppress(Exception):
                await process.stdin.wait_closed()
        await _terminate_process(process)


async def _initialize(
    connection: acp.ClientSideConnection,
    profile: AgentProfile,
) -> schema.InitializeResponse:
    return await connection.initialize(
        protocol_version=acp.PROTOCOL_VERSION,
        client_capabilities=_capabilities(profile),
        client_info=schema.Implementation(name="relay", title="Relay", version=__version__),
    )


async def _new_session(
    connection: acp.ClientSideConnection,
    initialized: schema.InitializeResponse,
    cwd: Path,
    *,
    allow_authentication: bool,
) -> schema.NewSessionResponse:
    try:
        return await connection.new_session(cwd=str(cwd.resolve()), mcp_servers=[])
    except RequestError as error:
        if error.code != _AUTH_REQUIRED_CODE:
            raise
        methods = initialized.auth_methods or []
        method = next(
            (item for item in methods if not isinstance(item, schema.TerminalAuthMethod)),
            None,
        )
        if not allow_authentication or method is None:
            message = "The agent requires authentication owned by its own CLI."
            raise AgentAuthError(
                message,
                next_action="Authenticate with the agent directly, then retry.",
            ) from None
        await connection.authenticate(method.id)
        return await connection.new_session(cwd=str(cwd.resolve()), mcp_servers=[])


async def _finish_stdio(
    connection: acp.ClientSideConnection,
    process: asyncio.subprocess.Process,
) -> None:
    with suppress(Exception):
        await connection.close()
    if process.stdin is not None:
        process.stdin.close()
        with suppress(Exception):
            await process.stdin.wait_closed()
    try:
        await asyncio.wait_for(process.wait(), timeout=_PROCESS_EXIT_GRACE_SECONDS)
    except TimeoutError:
        await _terminate_process(process)


class AcpDriver:
    """One installed ACP agent command, used for probes and fresh attempts."""

    def __init__(self, profile: AgentProfile, command: AgentCommand) -> None:
        self.profile: AgentProfile = profile
        self.command: AgentCommand = command
        self.result: AgentResult | None = None
        self.connection: acp.ClientSideConnection | None = None
        self.process: asyncio.subprocess.Process | None = None
        self.session_id: str | None = None

    async def probe_models(
        self,
        requirements: tuple[ProbeRequirement, ...],
        cwd: Path,
    ) -> ProbeResult:
        """Open one disposable session and prove every requested exact value."""
        client = RelayAcpClient(None, self.profile)
        cleanup_warning: str | None = None
        session_id: str | None = None
        try:
            async with _connection(self.command, cwd, client) as (connection, _process):
                initialized = await _initialize(connection, self.profile)
                new_session = await _new_session(
                    connection, initialized, cwd, allow_authentication=False
                )
                session_id = new_session.session_id
                client.session_id = session_id
                options = new_session.config_options or []
                selector = _model_selector(options, self.profile)
                agent_version = (
                    initialized.agent_info.version if initialized.agent_info is not None else ""
                )
                observed_at = datetime.now(timezone.utc)
                observations = tuple(
                    ModelObservation(
                        self.profile.agent_id,
                        value,
                        name,
                        selector.id,
                        agent_version,
                        observed_at,
                    )
                    for value, name in _model_options(selector)
                )
                advertised = {item.model_value for item in observations}
                confirmed: set[str] = set()
                failures: dict[str, str] = {}
                for requirement in requirements:
                    if requirement.model_value not in advertised:
                        error = ModelUnavailableError(
                            f"Exact model {requirement.model_value!r} is not advertised by "
                            f"{self.profile.agent_id!r}.",
                            context={"agent": self.profile.agent_id},
                        )
                        failures[requirement.model_value] = f"{error.error_code}: {error.message}"
                        continue
                    try:
                        selected = await connection.set_config_option(
                            selector.id, session_id, requirement.model_value
                        )
                    except Exception:
                        error = ModelSelectionRejectedError(
                            f"Agent {self.profile.agent_id!r} rejected exact model "
                            f"{requirement.model_value!r}.",
                            context={"agent": self.profile.agent_id},
                        )
                        failures[requirement.model_value] = f"{error.error_code}: {error.message}"
                        continue
                    if (
                        selected is None
                        or _selected_value(selected.config_options, selector.id)
                        != requirement.model_value
                    ):
                        error = ModelSelectionRejectedError(
                            f"Agent {self.profile.agent_id!r} did not confirm exact model "
                            f"{requirement.model_value!r}.",
                            context={"agent": self.profile.agent_id},
                        )
                        failures[requirement.model_value] = f"{error.error_code}: {error.message}"
                    else:
                        confirmed.add(requirement.model_value)
                agent_capabilities = initialized.agent_capabilities
                capabilities = (
                    agent_capabilities.session_capabilities
                    if agent_capabilities is not None
                    else None
                )
                if capabilities is not None and capabilities.close is not None:
                    try:
                        await connection.close_session(session_id)
                    except Exception:
                        LOGGER.exception(
                            "ACP probe session close failed",
                            extra={"agent_id": self.profile.agent_id},
                        )
                        cleanup_warning = "The ACP probe session may not have closed cleanly."
                if capabilities is not None and capabilities.delete is not None:
                    suffix = " The pinned ACP SDK exposes no supported delete-session call."
                    cleanup_warning = (
                        cleanup_warning or "The ACP probe session may be retained."
                    ) + suffix
                return ProbeResult(
                    self.profile.agent_id,
                    observations,
                    frozenset(confirmed),
                    failures,
                    cleanup_warning,
                )
        except Exception as error:
            mapped = map_agent_exception(error, agent_id=self.profile.agent_id)
            failures = {
                requirement.model_value: f"{mapped.error_code}: {mapped.message}"
                for requirement in requirements
            }
            return ProbeResult(
                self.profile.agent_id,
                failures=failures,
                cleanup_warning=(
                    "The ACP probe session may be retained after failure."
                    if session_id is not None
                    else None
                ),
                general_error=f"{mapped.error_code}: {mapped.message}",
            )

    async def start_attempt(
        self,
        context: AgentExecutionContext,
    ) -> AsyncIterator[AgentEvent]:
        """Run one fresh session while yielding normalized updates as they arrive."""
        queue: asyncio.Queue[AgentEvent] = asyncio.Queue()
        client = RelayAcpClient(context, self.profile, queue)
        agent_version = ""
        stderr_task: asyncio.Task[None] | None = None
        try:
            async with _connection(self.command, context.cwd, client) as (connection, process):
                self.connection = connection
                self.process = process
                initialized = await _initialize(connection, self.profile)
                new_session = await _new_session(
                    connection,
                    initialized,
                    context.cwd,
                    allow_authentication=True,
                )
                self.session_id = new_session.session_id
                client.session_id = self.session_id
                selector = _model_selector(new_session.config_options or [], self.profile)
                client.model_config_id = selector.id
                client.expected_model = context.model_value
                if context.model_value not in {value for value, _name in _model_options(selector)}:
                    message = f"Exact model {context.model_value!r} is no longer advertised."
                    raise ModelUnavailableError(  # noqa: TRY301
                        message, context={"agent": self.profile.agent_id}
                    )
                selected = await connection.set_config_option(
                    selector.id, self.session_id, context.model_value
                )
                if (
                    selected is None
                    or _selected_value(selected.config_options, selector.id) != context.model_value
                ):
                    message = f"Agent {self.profile.agent_id!r} rejected the snapshotted model."
                    raise ModelSelectionRejectedError(  # noqa: TRY301
                        message, context={"agent": self.profile.agent_id}
                    )
                agent_version = (
                    initialized.agent_info.version if initialized.agent_info is not None else ""
                )
                await asyncio.to_thread(
                    context.attempt.runtime.record_agent_session,
                    context.attempt.attempt.attempt_id,
                    process_id=process.pid,
                    session_id=self.session_id,
                    agent_version=agent_version,
                    config_ids={"model": selector.id},
                )
                stderr_task = asyncio.create_task(self._read_stderr(process, queue))
                prompt_task = asyncio.create_task(
                    connection.prompt(self.session_id, _prompt_blocks(context))
                )
                started = time.monotonic()
                heartbeat_due = started + ATTEMPT_HEARTBEAT_INTERVAL_SECONDS
                timeout_seconds = duration_seconds(context.node.timeout)
                requested_stop: str | None = None
                stop_deadline: float | None = None
                while not prompt_task.done() or not queue.empty():
                    try:
                        event = await asyncio.wait_for(
                            queue.get(), timeout=CONTROL_POLL_INTERVAL_SECONDS
                        )
                    except TimeoutError:
                        event = None
                    if event is not None:
                        yield event
                    now = time.monotonic()
                    if (
                        requested_stop is None
                        and timeout_seconds is not None
                        and now - started >= timeout_seconds
                    ):
                        requested_stop = "timeout"
                        stop_deadline = now + CANCELLATION_GRACE_SECONDS
                        await connection.cancel(self.session_id)
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
                                requested_stop = "canceled"
                                stop_deadline = now + CANCELLATION_GRACE_SECONDS
                                await connection.cancel(self.session_id)
                    if (
                        stop_deadline is not None
                        and now >= stop_deadline
                        and not prompt_task.done()
                    ):
                        await _terminate_process(process)
                        prompt_task.cancel()
                        with suppress(asyncio.CancelledError, Exception):
                            await prompt_task
                        break
                    if now >= heartbeat_due:
                        alive = await asyncio.to_thread(
                            context.attempt.runtime.heartbeat_attempt,
                            context.attempt.attempt.attempt_id,
                            context.attempt.attempt.worker_id,
                        )
                        if not alive:
                            message = "The ACP attempt lost its durable worker ownership."
                            raise PersistenceError(  # noqa: TRY301
                                message,
                                context={"node": context.attempt.attempt.scope_path},
                            )
                        heartbeat_due = now + ATTEMPT_HEARTBEAT_INTERVAL_SECONDS
                response: schema.PromptResponse | None = None
                if prompt_task.done() and not prompt_task.cancelled():
                    try:
                        response = await prompt_task
                    except Exception:
                        if requested_stop is None:
                            raise
                if client.drift_error is not None:
                    raise client.drift_error  # noqa: TRY301
                response_stop = response.stop_reason if response is not None else "cancelled"
                succeeded = response_stop == "end_turn" and requested_stop is None
                agent_capabilities = initialized.agent_capabilities
                capabilities = (
                    agent_capabilities.session_capabilities
                    if agent_capabilities is not None
                    else None
                )
                if (
                    capabilities is not None
                    and capabilities.close is not None
                    and process.returncode is None
                ):
                    try:
                        await connection.close_session(self.session_id)
                    except Exception:
                        LOGGER.exception(
                            "ACP attempt session close failed",
                            extra={"agent_id": self.profile.agent_id},
                        )
                        yield AgentEvent(
                            "agent.cleanup_warning",
                            {"message": "The ACP session may remain in the agent's history."},
                        )
                await _finish_stdio(connection, process)
                await stderr_task
                while not queue.empty():
                    yield queue.get_nowait()
                self.result = AgentResult(
                    succeeded=succeeded,
                    stop_reason=requested_stop or response_stop,
                    exit_code=process.returncode,
                    error_code=(
                        None
                        if succeeded
                        else "node_timeout"
                        if requested_stop == "timeout"
                        else "canceled"
                        if requested_stop == "canceled"
                        else AgentProtocolError.error_code
                    ),
                )
        except Exception as error:
            mapped = map_agent_exception(error, agent_id=self.profile.agent_id)
            self.result = AgentResult(
                False,
                "failed",
                exit_code=self.process.returncode if self.process is not None else None,
                error_code=mapped.error_code,
            )
            raise mapped from None
        finally:
            if stderr_task is not None and not stderr_task.done():
                with suppress(asyncio.CancelledError, Exception):
                    await stderr_task
            await asyncio.to_thread(
                context.attempt.runtime.record_agent_session,
                context.attempt.attempt.attempt_id,
                process_id=None,
                session_id=self.session_id,
                agent_version=agent_version,
                config_ids={"model": client.model_config_id or ""},
            )

    async def _read_stderr(
        self,
        process: asyncio.subprocess.Process,
        queue: asyncio.Queue[AgentEvent],
    ) -> None:
        if process.stderr is None:
            return
        while chunk := await process.stderr.read(8_192):
            await queue.put(
                AgentEvent("agent.stderr", {"text": chunk.decode("utf-8", "backslashreplace")})
            )

    async def cancel(self) -> None:
        if self.connection is not None and self.session_id is not None:
            with suppress(Exception):
                await self.connection.cancel(self.session_id)
        if self.process is not None:
            await _terminate_process(self.process)

    async def finalize(self) -> AgentResult:
        if self.result is None:
            message = "The ACP attempt ended without a terminal provider result."
            raise AgentProtocolError(message, context={"agent": self.profile.agent_id})
        return self.result


__all__ = ["AcpDriver", "RelayAcpClient"]
