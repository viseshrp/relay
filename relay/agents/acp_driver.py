"""ACP client adapter with exact-model proof and durable owner interactions."""

from __future__ import annotations

import asyncio
import codecs
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import time
from typing import TypeAlias

import acp
from acp import RequestError, schema

from relay._version import __version__
from relay.constants import (
    AGENT_EVENT_QUEUE_MAX_ITEMS,
    ATTEMPT_HEARTBEAT_INTERVAL_SECONDS,
    CANCELLATION_GRACE_SECONDS,
    CONTROL_POLL_INTERVAL_SECONDS,
    PROCESS_EXIT_GRACE_SECONDS,
    PROCESS_STREAM_CHUNK_BYTES,
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
from relay.execution.cancellation import (
    discard_process_stream,
    spawn_process,
    terminate_async_process_tree,
)
from relay.execution.control import ClaimedControl, cancel_stop_reason
from relay.execution.state import ControlKind, InteractionKind

from .events import AgentEvent, normalize_acp_update
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

LOGGER = logging.getLogger(__name__)
_AUTH_REQUIRED_CODE = RequestError.auth_required().code

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
    result = []
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
    """Keep `Review.\n` intact; `{'target': 'api'}` gets its own JSON block."""
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


async def _read_stderr(
    process: asyncio.subprocess.Process, queue: asyncio.Queue[AgentEvent] | None
) -> None:
    """Drain from spawn onward; attempts retain bytes and probes discard them."""
    if process.stderr is None:
        return
    decoder = codecs.getincrementaldecoder("utf-8")(errors="backslashreplace")
    while chunk := await process.stderr.read(PROCESS_STREAM_CHUNK_BYTES):
        text = decoder.decode(chunk)
        if queue is not None and text:
            await queue.put(AgentEvent("agent.stderr", {"text": text}))
    tail = decoder.decode(b"", final=True)
    if queue is not None and tail:
        await queue.put(AgentEvent("agent.stderr", {"text": tail}))


class RelayAcpClient:
    """ACP callbacks backed by the exact attempt's durable control mailbox."""

    context: AgentExecutionContext | None
    profile: AgentProfile
    event_queue: asyncio.Queue[AgentEvent] | None
    session_id: str | None
    expected_model: str | None
    model_config_id: str | None
    drift_error: RelayError | None
    control_stop: str | None
    interaction_lock: asyncio.Lock

    agent: acp.Agent | None

    def __init__(
        self,
        context: AgentExecutionContext | None,
        profile: AgentProfile,
        event_queue: asyncio.Queue[AgentEvent] | None = None,
    ) -> None:
        self.context = context
        self.profile = profile
        self.event_queue = event_queue
        self.agent = None
        self.session_id = None
        self.expected_model = None
        self.model_config_id = None
        self.drift_error = None
        self.control_stop = None
        self.interaction_lock = asyncio.Lock()

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
        # ACP dispatches requests concurrently; the mailbox owns one unanswered
        # interaction at a time. Hold the lock through the matching answer.
        async with self.interaction_lock:
            if self.control_stop is not None:
                return schema.RequestPermissionResponse(
                    outcome=schema.DeniedOutcome(outcome="cancelled")
                )
            safe_options = tuple(
                {"id": option.option_id, "name": option.name, "kind": option.kind}
                for option in options
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
                    if control.kind == ControlKind.CANCEL.value:
                        self.control_stop = cancel_stop_reason(control).value
                    return control
            now = time.monotonic()
            if now >= heartbeat_due:
                alive = await asyncio.to_thread(
                    self.context.attempt.heartbeat,
                )
                if not alive:
                    message = "The ACP attempt lost its durable worker ownership."
                    raise PersistenceError(message, context={"node": attempt.scope_path})
                heartbeat_due = now + ATTEMPT_HEARTBEAT_INTERVAL_SECONDS
            await asyncio.sleep(CONTROL_POLL_INTERVAL_SECONDS)

    async def _cancel_session(self) -> None:
        if self.agent is not None and self.session_id is not None:
            with suppress(Exception):
                await asyncio.wait_for(
                    self.agent.cancel(self.session_id),
                    timeout=CANCELLATION_GRACE_SECONDS,
                )

    async def create_elicitation(
        self,
        message: str,
        mode: schema.ElicitationMode,
        **kwargs: object,
    ) -> schema.CreateElicitationResponse:
        del kwargs
        if self.context is None:
            raise RequestError.invalid_request()
        # Form and URL requests share the permission mailbox and its ordering.
        async with self.interaction_lock:
            if self.control_stop is not None:
                return schema.CancelElicitationResponse(action="cancel")
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
    process = await spawn_process(command.argv(), cwd)
    stderr_task = asyncio.create_task(_read_stderr(process, client.event_queue))
    if process.stdin is None or process.stdout is None:
        await terminate_async_process_tree(process)
        await stderr_task
        message = "The ACP process did not expose both protocol streams."
        raise AgentProtocolError(message, context={"agent": client.profile.agent_id})
    # SDK 0.12.1 gates incoming elicitation/create on this flag. Outgoing
    # close_session does not depend on it; the wire protocol version stays 1.
    connection = acp.connect_to_agent(
        client, process.stdin, process.stdout, use_unstable_protocol=True
    )
    canceled = False
    try:
        yield connection, process
    except asyncio.CancelledError:
        canceled = True
        raise
    finally:
        if canceled:
            # A closed event consumer cannot service queue backpressure. Drain
            # directly while stopping the process so cleanup still reaches EOF.
            stderr_task.cancel()
            await asyncio.gather(stderr_task, return_exceptions=True)
            stderr_task = asyncio.create_task(_read_stderr(process, None))
        with suppress(Exception):
            await connection.close()
        if process.stdin is not None:
            process.stdin.close()
            with suppress(Exception):
                await process.stdin.wait_closed()
        stdout_task = asyncio.create_task(discard_process_stream(process.stdout))
        try:
            await terminate_async_process_tree(process)
        finally:
            for reader in (stderr_task, stdout_task):
                if process.returncode is None:
                    reader.cancel()
            await asyncio.gather(stderr_task, stdout_task, return_exceptions=True)


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
    stdout_task = asyncio.create_task(discard_process_stream(process.stdout))
    try:
        try:
            await asyncio.wait_for(process.wait(), timeout=PROCESS_EXIT_GRACE_SECONDS)
        except asyncio.TimeoutError:
            await terminate_async_process_tree(process)
    finally:
        if process.returncode is None:
            stdout_task.cancel()
        await asyncio.gather(stdout_task, return_exceptions=True)


class AcpDriver:
    """One installed ACP agent command, used for probes and fresh attempts."""

    profile: AgentProfile
    command: AgentCommand
    result: AgentResult | None
    connection: acp.ClientSideConnection | None
    process: asyncio.subprocess.Process | None
    session_id: str | None

    agent_version: str

    def __init__(self, profile: AgentProfile, command: AgentCommand) -> None:
        self.profile = profile
        self.command = command
        self.result = None
        self.connection = None
        self.process = None
        self.session_id = None
        self.agent_version = ""

    async def probe_models(
        self,
        requirements: tuple[ProbeRequirement, ...],
        cwd: Path,
    ) -> ProbeResult:
        """Open one disposable session and prove every requested exact value."""
        client = RelayAcpClient(None, self.profile)
        cleanup_warning = None
        session_id = None
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
                confirmed = set()
                failures = {}
                for requirement in requirements:
                    if requirement.model_value not in advertised:
                        error = ModelUnavailableError(
                            f"Exact model {requirement.model_value!r} is not advertised by "
                            f"{self.profile.agent_id!r}.",
                            context={"agent": self.profile.agent_id},
                        )
                        failures[requirement.model_value] = ProbeFailure.from_error(error)
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
                        failures[requirement.model_value] = ProbeFailure.from_error(error)
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
                        failures[requirement.model_value] = ProbeFailure.from_error(error)
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
                requirement.model_value: ProbeFailure.from_error(mapped)
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
                general_error=ProbeFailure.from_error(mapped),
            )

    async def _perform_attempt(
        self, context: AgentExecutionContext, client: RelayAcpClient
    ) -> AgentResult:
        # Run the entire stdio lifecycle concurrently with the event consumer,
        # including initialization and cleanup, so stderr backpressure is serviced.
        async with _connection(self.command, context.cwd, client) as (connection, process):
            self.connection = connection
            self.process = process
            initialized = await _initialize(connection, self.profile)
            new_session = await _new_session(
                connection, initialized, context.cwd, allow_authentication=True
            )
            self.session_id = new_session.session_id
            client.session_id = self.session_id
            selector = _model_selector(new_session.config_options or [], self.profile)
            client.model_config_id = selector.id
            client.expected_model = context.model_value
            if context.model_value not in {value for value, _name in _model_options(selector)}:
                message = f"Exact model {context.model_value!r} is no longer advertised."
                raise ModelUnavailableError(message, context={"agent": self.profile.agent_id})
            try:
                selected = await connection.set_config_option(
                    selector.id, self.session_id, context.model_value
                )
            except RequestError as error:
                if error.code == _AUTH_REQUIRED_CODE:
                    raise
                message = f"Agent {self.profile.agent_id!r} rejected the snapshotted model."
                raise ModelSelectionRejectedError(
                    message, context={"agent": self.profile.agent_id}
                ) from None
            if (
                selected is None
                or _selected_value(selected.config_options, selector.id) != context.model_value
            ):
                message = f"Agent {self.profile.agent_id!r} rejected the snapshotted model."
                raise ModelSelectionRejectedError(message, context={"agent": self.profile.agent_id})
            self.agent_version = (
                initialized.agent_info.version if initialized.agent_info is not None else ""
            )
            await asyncio.to_thread(
                context.attempt.runtime.record_agent_session,
                context.attempt.attempt.attempt_id,
                process_id=process.pid,
                session_id=self.session_id,
                agent_version=self.agent_version,
                config_ids={"model": selector.id},
            )
            response = await connection.prompt(self.session_id, _prompt_blocks(context))
            if client.drift_error is not None:
                raise client.drift_error
            capabilities = (
                initialized.agent_capabilities.session_capabilities
                if initialized.agent_capabilities is not None
                else None
            )
            if capabilities is not None and capabilities.close is not None:
                try:
                    await connection.close_session(self.session_id)
                except Exception:
                    LOGGER.exception(
                        "ACP attempt session close failed",
                        extra={"agent_id": self.profile.agent_id},
                    )
                    if client.event_queue is not None:
                        await client.event_queue.put(
                            AgentEvent(
                                "agent.cleanup_warning",
                                {"message": "The ACP session may remain in the agent's history."},
                            )
                        )
            await _finish_stdio(connection, process)
            succeeded = response.stop_reason == "end_turn" and client.control_stop is None
            return AgentResult(
                succeeded,
                client.control_stop or response.stop_reason,
                process.returncode,
                None if succeeded else AgentProtocolError.error_code,
            )

    async def start_attempt(self, context: AgentExecutionContext) -> AsyncIterator[AgentEvent]:
        """Consume a bounded queue throughout initialization, prompt, and shutdown."""
        queue = asyncio.Queue[AgentEvent](maxsize=AGENT_EVENT_QUEUE_MAX_ITEMS)
        client = RelayAcpClient(context, self.profile, queue)
        lifecycle = asyncio.create_task(self._perform_attempt(context, client))
        stopper = None
        requested_stop = None
        stop_deadline = None
        heartbeat_due = time.monotonic() + ATTEMPT_HEARTBEAT_INTERVAL_SECONDS
        try:
            while not lifecycle.done() or not queue.empty():
                with suppress(asyncio.TimeoutError):
                    yield await asyncio.wait_for(queue.get(), timeout=CONTROL_POLL_INTERVAL_SECONDS)
                now = time.monotonic()
                if requested_stop is None:
                    if context.attempt.timed_out():
                        requested_stop = "timeout"
                    else:
                        control = await asyncio.to_thread(
                            context.attempt.runtime.claim_next_control,
                            context.attempt.attempt.attempt_id,
                            context.attempt.attempt.worker_id,
                            (ControlKind.CANCEL.value,),
                        )
                        if control is not None and await asyncio.to_thread(
                            context.attempt.runtime.apply_control,
                            control.request_id,
                            context.attempt.attempt.worker_id,
                        ):
                            requested_stop = cancel_stop_reason(control).value
                    if requested_stop is not None:
                        client.control_stop = requested_stop
                        stop_deadline = now + CANCELLATION_GRACE_SECONDS
                        if self.connection is not None and self.session_id is not None:
                            with suppress(Exception):
                                await asyncio.wait_for(
                                    self.connection.cancel(self.session_id),
                                    timeout=CANCELLATION_GRACE_SECONDS,
                                )
                if (
                    stop_deadline is not None
                    and now >= stop_deadline
                    and self.process is not None
                    and stopper is None
                ):
                    stopper = asyncio.create_task(terminate_async_process_tree(self.process))
                if now >= heartbeat_due:
                    if not await asyncio.to_thread(context.attempt.heartbeat):
                        message = "The ACP attempt lost its durable worker ownership."
                        raise PersistenceError(  # noqa: TRY301
                            message, context={"node": context.attempt.attempt.scope_path}
                        )
                    heartbeat_due = now + ATTEMPT_HEARTBEAT_INTERVAL_SECONDS
            try:
                self.result = await lifecycle
            except Exception:
                if requested_stop is None:
                    raise
            if requested_stop is not None:
                error_code = "node_timeout" if requested_stop == "timeout" else requested_stop
                self.result = AgentResult(
                    False,
                    requested_stop,
                    self.process.returncode if self.process is not None else None,
                    error_code,
                )
        except Exception as error:
            mapped = map_agent_exception(error, agent_id=self.profile.agent_id)
            self.result = AgentResult(
                False,
                "failed",
                self.process.returncode if self.process is not None else None,
                mapped.error_code,
            )
            raise mapped from None
        finally:
            if not lifecycle.done():
                lifecycle.cancel()
            await asyncio.gather(lifecycle, return_exceptions=True)
            if stopper is not None:
                await stopper
            await asyncio.to_thread(
                context.attempt.runtime.record_agent_session,
                context.attempt.attempt.attempt_id,
                process_id=None,
                session_id=self.session_id,
                agent_version=self.agent_version,
                config_ids={"model": client.model_config_id or ""},
            )

    async def cancel(self) -> None:
        if self.connection is not None and self.session_id is not None:
            with suppress(Exception):
                await asyncio.wait_for(
                    self.connection.cancel(self.session_id),
                    timeout=CANCELLATION_GRACE_SECONDS,
                )
        if self.process is not None:
            await terminate_async_process_tree(self.process)

    async def finalize(self) -> AgentResult:
        if self.result is None:
            message = "The ACP attempt ended without a terminal provider result."
            raise AgentProtocolError(message, context={"agent": self.profile.agent_id})
        return self.result


__all__ = ["AcpDriver", "RelayAcpClient"]
