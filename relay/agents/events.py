"""Normalization of provider updates into Relay's durable event vocabulary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json

from acp import schema

from relay.execution.state import EventSensitivity

_SAFE_CHUNK_BYTES = 32_768


@dataclass(frozen=True, slots=True)
class AgentEvent:
    """A provider-neutral event safe for persistence and browser rendering."""

    event_type: str
    payload: Mapping[str, object]
    sensitivity: EventSensitivity = EventSensitivity.NORMAL


def _utf8_chunks(value: str) -> tuple[str, ...]:
    encoded = value.encode("utf-8")
    chunks: list[str] = []
    start = 0
    while start < len(encoded):
        end = min(len(encoded), start + _SAFE_CHUNK_BYTES)
        while end < len(encoded) and (encoded[end] & 0xC0) == 0x80:
            end -= 1
        chunks.append(encoded[start:end].decode("utf-8"))
        start = end
    return tuple(chunks) or ("",)


def bounded_agent_events(event: AgentEvent) -> tuple[AgentEvent, ...]:
    """Split large visible strings so no persisted event drops provider bytes."""
    encoded = json.dumps(event.payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(encoded) <= _SAFE_CHUNK_BYTES:
        return (event,)
    for key in ("text", "summary", "chunk"):
        value = event.payload.get(key)
        if isinstance(value, str):
            chunks = _utf8_chunks(value)
            return tuple(
                AgentEvent(
                    event.event_type,
                    {**event.payload, key: chunk, "part": index, "parts": len(chunks)},
                    event.sensitivity,
                )
                for index, chunk in enumerate(chunks, start=1)
            )
    serialized = json.dumps(event.payload, separators=(",", ":"), ensure_ascii=False)
    chunks = _utf8_chunks(serialized)
    return tuple(
        AgentEvent(
            event.event_type,
            {"chunk": chunk, "part": index, "parts": len(chunks)},
            event.sensitivity,
        )
        for index, chunk in enumerate(chunks, start=1)
    )


def _is_private(content: object) -> bool:
    annotations = getattr(content, "annotations", None)
    audience = getattr(annotations, "audience", None)
    if isinstance(audience, list) and audience and "user" not in audience:
        return True
    metadata = getattr(content, "field_meta", None)
    return isinstance(metadata, dict) and metadata.get("private") is True


def _visible_text(content: object) -> str | None:
    if _is_private(content):
        return None
    text = getattr(content, "text", None)
    return text if isinstance(text, str) else None


def _visible_content(content: object) -> Mapping[str, object] | None:
    if _is_private(content):
        return None
    dump = getattr(content, "model_dump", None)
    if not callable(dump):
        return None
    value = dump(mode="json", by_alias=True, exclude={"field_meta", "annotations"})
    return value if isinstance(value, dict) else None


def _tool_summary(update: schema.ToolCallStart | schema.ToolCallProgress) -> str:
    summary: dict[str, object] = {}
    if update.kind is not None:
        summary["kind"] = update.kind
    if update.status is not None:
        summary["status"] = update.status
    if update.locations:
        summary["locations"] = [
            {"path": item.path, **({"line": item.line} if item.line is not None else {})}
            for item in update.locations
        ]
    if update.raw_input is not None:
        summary["raw_input"] = update.raw_input
    if update.raw_output is not None:
        summary["raw_output"] = update.raw_output
    visible: list[object] = []
    for item in update.content or []:
        if isinstance(item, schema.ContentToolCallContent):
            text = _visible_text(item.content)
            if text is not None:
                visible.append({"text": text})
        elif isinstance(item, schema.FileEditToolCallContent):
            visible.append(
                {"path": item.path, "old_text": item.old_text, "new_text": item.new_text}
            )
        elif isinstance(item, schema.TerminalToolCallContent):
            visible.append({"terminal_id": item.terminal_id})
    if visible:
        summary["content"] = visible
    return json.dumps(summary, separators=(",", ":"), ensure_ascii=False)


def _plan_payload(update: schema.AgentPlanUpdate | schema.AgentPlanContentUpdate) -> object:
    if isinstance(update, schema.AgentPlanUpdate):
        return [
            {"content": item.content, "priority": item.priority, "status": item.status}
            for item in update.entries
        ]
    return update.plan.model_dump(mode="json", by_alias=True, exclude={"field_meta"})


def normalize_acp_update(update: object) -> tuple[AgentEvent, ...]:
    """Map all owner-visible ACP updates and discard provider-private content."""
    if isinstance(update, schema.AgentMessageChunk):
        text = _visible_text(update.content)
        if text is not None:
            return (AgentEvent("agent.message", {"text": text}),)
        content = _visible_content(update.content)
        return (
            () if content is None else (AgentEvent("agent.provider_event", {"content": content}),)
        )
    if isinstance(update, schema.AgentThoughtChunk):
        text = _visible_text(update.content)
        if text is not None:
            return (AgentEvent("agent.thought", {"text": text}),)
        content = _visible_content(update.content)
        return (
            () if content is None else (AgentEvent("agent.provider_event", {"content": content}),)
        )
    if isinstance(update, schema.ToolCallStart):
        return (
            AgentEvent(
                "agent.tool_call",
                {"tool": update.title, "summary": _tool_summary(update)},
            ),
        )
    if isinstance(update, schema.ToolCallProgress):
        terminal = update.status in {"completed", "failed"}
        return (
            AgentEvent(
                "agent.tool_result" if terminal else "agent.tool_call",
                {"tool": update.title or update.tool_call_id, "summary": _tool_summary(update)},
            ),
        )
    if isinstance(update, (schema.AgentPlanUpdate, schema.AgentPlanContentUpdate)):
        return (AgentEvent("agent.plan", {"plan": _plan_payload(update)}),)
    if isinstance(update, schema.AgentPlanRemovedUpdate):
        return (AgentEvent("agent.plan", {"plan": None, "plan_id": update.plan_id}),)
    if isinstance(
        update,
        (
            schema.AvailableCommandsUpdate,
            schema.CurrentModeUpdate,
            schema.ConfigOptionUpdate,
            schema.SessionInfoUpdate,
            schema.UsageUpdate,
        ),
    ):
        return (
            AgentEvent(
                "agent.provider_event",
                {"update": update.model_dump(mode="json", by_alias=True, exclude={"field_meta"})},
            ),
        )
    return ()


def _string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def normalize_antigravity_event(raw: Mapping[str, object]) -> tuple[AgentEvent, ...]:
    """Map documented stream-json lines while preserving unknown lines as diagnostics."""
    kind = _string(raw.get("event"))
    if kind == "step_update":
        update = raw.get("step_update")
        if not isinstance(update, dict):
            return (AgentEvent("agent.provider_event", {"event": dict(raw)}),)
        step_type = _string(update.get("step_type")) or "step"
        delta = _string(update.get("text_delta"))
        if step_type == "agent_response" and delta is not None:
            return (AgentEvent("agent.message", {"text": delta}),)
        if "tool" in step_type:
            terminal = update.get("state") in {"DONE", "ERROR"}
            return (
                AgentEvent(
                    "agent.tool_result" if terminal else "agent.tool_call",
                    {
                        "tool": step_type,
                        "summary": json.dumps(update, separators=(",", ":"), ensure_ascii=False),
                    },
                ),
            )
    if kind == "result":
        result = raw.get("result")
        if isinstance(result, dict):
            return (
                AgentEvent(
                    "agent.result",
                    {
                        key: value
                        for key, value in result.items()
                        if key not in {"response", "structured_output"}
                    },
                ),
            )
    return ()


__all__ = [
    "AgentEvent",
    "bounded_agent_events",
    "normalize_acp_update",
    "normalize_antigravity_event",
]
