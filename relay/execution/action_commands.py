"""Structured workflow commands are recognized only in command/JavaScript logs."""

from __future__ import annotations

from collections.abc import Mapping
import json
import re
from typing import TYPE_CHECKING, cast

from relay.agents.events import TOOL_EVENT_TYPES, AgentEvent, bounded_agent_events
from relay.execution.masking import Redactor
from relay.execution.state import EventSensitivity, EventSource

if TYPE_CHECKING:
    from relay.execution.runner import RunnerStore


def _unescape(value: str) -> str:
    for source, target in (("%0D", "\r"), ("%0A", "\n"), ("%3A", ":"), ("%2C", ","), ("%25", "%")):
        value = re.sub(
            source, lambda _match, replacement=target: replacement, value, flags=re.IGNORECASE
        )
    return value


class CommandLog:
    runtime: RunnerStore
    attempt_id: str
    masks: Redactor
    buffers: dict[str, str]
    stopped: str | None
    streams: dict[str, tuple[str, EventSource, EventSensitivity, str, dict[str, object]]]
    tool_streams: dict[str, tuple[EventSensitivity, dict[str, object]]]

    def __init__(self, runtime: RunnerStore, attempt_id: str, masks: Redactor) -> None:
        self.runtime = runtime
        self.attempt_id = attempt_id
        self.masks = masks
        self.buffers = {}
        self.stopped = None
        self.streams = {}
        self.tool_streams = {}

    def feed(self, event_type: str, chunk: str, *, final: bool = False) -> None:
        value = self.buffers.pop(event_type, "") + chunk
        lines = value.splitlines(keepends=True)
        if lines and not lines[-1].endswith(("\n", "\r")) and not final:
            self.buffers[event_type] = lines.pop()
        for line in lines:
            self.line(event_type, line)
        if len(self.buffers.get(event_type, "")) > 1_048_576:
            from relay.errors import NodeExecutionError

            message = "A workflow command log line exceeds 1 MiB."
            raise NodeExecutionError(message)

    def line(self, event_type: str, line: str) -> None:
        match = re.fullmatch(r"::([A-Za-z0-9_-]+)(?: ([^\r\n]*))?::(.*)", line.rstrip("\r\n"))
        if self.stopped:
            if line.rstrip("\r\n") == f"::{self.stopped}::":
                self.stopped = None
                return
            match = None
        if not match:
            chunk = self.masks.stream(self.attempt_id + event_type, line)
            self.runtime.append_attempt_event(
                self.attempt_id, event_type, EventSource.COMMAND, {"chunk": chunk}
            )
            return
        name, properties, content = match.groups()
        content = _unescape(content)
        if name == "add-mask":
            self.masks.register(content)
            for word in content.split():
                self.masks.register(word)
            return
        if name == "stop-commands":
            if content and len(content) <= 256:
                self.stopped = content
            return
        if name not in {"warning", "error", "notice", "debug", "group", "endgroup"}:
            self.runtime.append_attempt_event(
                self.attempt_id, event_type, EventSource.COMMAND, {"chunk": self.masks.text(line)}
            )
            return
        metadata = {}
        for item in (properties or "").split(","):
            if "=" in item:
                key, value = item.split("=", 1)
                if key in {"file", "line", "endLine", "col", "endColumn", "title"}:
                    metadata[key] = _unescape(value)
        self.runtime.append_attempt_event(
            self.attempt_id,
            f"actions.{name}",
            EventSource.COMMAND,
            {"message": self.masks.text(content), "properties": self.masks.payload(metadata)},
        )

    def append_tool_event(
        self,
        event_type: str,
        payload: Mapping[str, object],
        sensitivity: EventSensitivity,
    ) -> None:
        for event in bounded_agent_events(AgentEvent(event_type, payload, sensitivity)):
            self.runtime.append_attempt_event(
                self.attempt_id,
                event.event_type,
                EventSource.AGENT,
                event.payload,
                sensitivity=event.sensitivity,
            )

    def flush_tool(self, key: str) -> None:
        # Emit held text as its own delta before the caller's terminal event,
        # or at step shutdown if the tool never sends a terminal event.
        stream = self.tool_streams.pop(key, None)
        if stream is None:
            return
        sensitivity, metadata = stream
        chunk = self.masks.stream(key, "", final=True)
        if chunk:
            self.append_tool_event(
                "agent.tool_call",
                {
                    **metadata,
                    "summary": json.dumps(
                        {"output_delta": chunk}, separators=(",", ":"), ensure_ascii=False
                    ),
                },
                sensitivity,
            )

    def flush(self) -> None:
        for name in tuple(self.buffers):
            self.feed(name, "", final=True)
        for key in tuple(self.tool_streams):
            self.flush_tool(key)
        for key, (event, source, sensitivity, field, payload) in self.streams.items():
            chunk = self.masks.stream(key, "", final=True)
            if chunk:
                self.runtime.append_attempt_event(
                    self.attempt_id,
                    event,
                    source,
                    {**payload, field: chunk},
                    sensitivity=sensitivity,
                )
        self.streams.clear()
        for key in tuple(self.masks.pending):
            if key.startswith(self.attempt_id):
                event = key[len(self.attempt_id) :]
                chunk = self.masks.stream(key, "", final=True)
                if chunk:
                    self.runtime.append_attempt_event(
                        self.attempt_id, event, EventSource.COMMAND, {"chunk": chunk}
                    )


class ActionRuntime:
    """Proxy only log persistence; process, ownership, and control callbacks stay real."""

    runtime: RunnerStore
    log: CommandLog
    masks: Redactor

    def __init__(self, runtime: RunnerStore, log: CommandLog, masks: Redactor) -> None:
        self.runtime = runtime
        self.log = log
        self.masks = masks

    def __getattr__(self, name: str) -> object:
        return getattr(self.runtime, name)

    def _append_tool_event(
        self,
        attempt_id: str,
        event_type: str,
        payload: Mapping[str, object],
        sensitivity: EventSensitivity,
    ) -> None:
        value = payload.get("summary")
        try:
            summary = json.loads(value) if isinstance(value, str) else None
        except json.JSONDecodeError:
            summary = None
        metadata = self.masks.mapping(
            {name: item for name, item in payload.items() if name != "summary"}
        )
        tool_id = payload.get("tool_call_id")
        # Attempt a1, normal sensitivity, turn 1, call-7 -> a1:tool:normal:1:call-7.
        key = f"{attempt_id}:tool:{sensitivity.value}:{payload.get('turn')}:{tool_id}"
        # Codex can report terminal_exit in a progress update, before a tool result.
        terminal = event_type == "agent.tool_result" or (
            isinstance(summary, dict) and "exit_code" in summary
        )
        if isinstance(summary, dict):
            delta = summary.get("output_delta")
            if isinstance(tool_id, str) and isinstance(delta, str):
                # Decode first: deltas 'TOKEN-12345' + '67890\n' become '***\n'
                # even when the registered value contains JSON-escaped bytes.
                summary["output_delta"] = self.masks.stream(key, delta, final=terminal)
                if key in self.masks.pending:
                    self.log.tool_streams[key] = (sensitivity, metadata)
                else:
                    self.log.tool_streams.pop(key, None)
            elif terminal:
                self.log.flush_tool(key)
            masked = {
                **metadata,
                "summary": json.dumps(
                    self.masks.payload(summary), separators=(",", ":"), ensure_ascii=False
                ),
            }
        else:
            if terminal:
                self.log.flush_tool(key)
            masked = self.masks.mapping(payload)
        self.log.append_tool_event(event_type, masked, sensitivity)

    def append_attempt_event(
        self,
        attempt_id: str,
        event_type: str,
        source: EventSource,
        payload: Mapping[str, object],
        *,
        sensitivity: EventSensitivity = EventSensitivity.NORMAL,
    ) -> None:
        if source is EventSource.AGENT and event_type in TOOL_EVENT_TYPES:
            self._append_tool_event(attempt_id, event_type, payload, sensitivity)
        elif source is EventSource.COMMAND and isinstance(payload.get("chunk"), str):
            self.log.feed(event_type, cast(str, payload["chunk"]))
        elif isinstance(payload.get("chunk"), str) or isinstance(payload.get("text"), str):
            field = "chunk" if isinstance(payload.get("chunk"), str) else "text"
            key = f"{attempt_id}:{event_type}:{source.value}:{sensitivity.value}:{field}"
            metadata = cast(
                dict[str, object],
                self.masks.payload(
                    {name: value for name, value in payload.items() if name != field}
                ),
            )
            self.log.streams[key] = (event_type, source, sensitivity, field, metadata)
            chunk = self.masks.stream(key, cast(str, payload[field]))
            if chunk:
                self.runtime.append_attempt_event(
                    attempt_id,
                    event_type,
                    source,
                    {**metadata, field: chunk},
                    sensitivity=sensitivity,
                )
        else:
            self.runtime.append_attempt_event(
                attempt_id,
                event_type,
                source,
                cast(Mapping[str, object], self.masks.payload(payload)),
                sensitivity=sensitivity,
            )
