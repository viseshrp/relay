"""Structured workflow commands are recognized only in command/JavaScript logs."""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import TYPE_CHECKING, cast

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

    def __init__(self, runtime: RunnerStore, attempt_id: str, masks: Redactor) -> None:
        self.runtime = runtime
        self.attempt_id = attempt_id
        self.masks = masks
        self.buffers = {}
        self.stopped = None
        self.streams = {}

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

    def flush(self) -> None:
        for name in tuple(self.buffers):
            self.feed(name, "", final=True)
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

    def append_attempt_event(
        self,
        attempt_id: str,
        event_type: str,
        source: EventSource,
        payload: Mapping[str, object],
        *,
        sensitivity: EventSensitivity = EventSensitivity.NORMAL,
    ) -> None:
        if source is EventSource.COMMAND and isinstance(payload.get("chunk"), str):
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
