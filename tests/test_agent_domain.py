"""Provider event privacy, bounded payloads, registry caching, and error identities."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from urllib.error import URLError

from acp import RequestError, schema
import pytest

from relay.agents.events import (
    AgentEvent,
    bounded_agent_events,
    normalize_acp_update,
    normalize_antigravity_event,
)
from relay.agents.mapping import map_agent_exception
from relay.agents.models import ProbeFailure
from relay.agents.registry import REGISTRY_URL, load_registry, validate_registry_document
from relay.constants import EVENT_MAX_PAYLOAD_BYTES, REGISTRY_CACHE_TTL_SECONDS
from relay.errors import (
    AgentAuthError,
    AgentDiscoveryError,
    AgentLaunchError,
    AgentProtocolError,
    RelayError,
)
from relay.execution.state import EventSensitivity
from tests.support import RegistryNetwork, registry_document

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_probe_failure_keeps_error_identity_separate_from_prose() -> None:
    error = AgentAuthError("A custom provider diagnostic with punctuation: login.")
    failure = ProbeFailure.from_error(error)
    assert failure.code == error.error_code
    assert failure.message == error.message


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (RequestError.auth_required(), AgentAuthError),
        (RequestError.invalid_params(), AgentProtocolError),
        (RequestError(-1, "Authentication required"), AgentProtocolError),
        (FileNotFoundError("binary"), AgentLaunchError),
        (ConnectionResetError("closed"), AgentProtocolError),
        (BrokenPipeError("closed"), AgentProtocolError),
        (RuntimeError("details"), AgentProtocolError),
    ],
)
def test_agent_exception_mapping_uses_types_and_codes_not_text(
    error: BaseException, expected: type[RelayError]
) -> None:
    mapped = map_agent_exception(error, agent_id="codex")
    assert isinstance(mapped, expected)
    assert mapped.context == {"agent": "codex"}


def test_an_existing_relay_error_is_preserved() -> None:
    error = AgentAuthError("Login")
    assert map_agent_exception(error, agent_id="codex") is error


@pytest.mark.parametrize("text", ["", "ordinary", '"\\\n\r\t', "\x00\x1f", "é😀"])
def test_bounded_visible_events_preserve_every_character(text: str) -> None:
    original = text * EVENT_MAX_PAYLOAD_BYTES
    event = AgentEvent("agent.message", {"text": original}, EventSensitivity.REDACTED)

    parts = bounded_agent_events(event)

    assert "".join(part.payload["text"] for part in parts) == original
    assert all(
        part.event_type == event.event_type and part.sensitivity == event.sensitivity
        for part in parts
    )
    assert all(
        len(json.dumps(part.payload, separators=(",", ":"), ensure_ascii=False).encode())
        <= EVENT_MAX_PAYLOAD_BYTES
        for part in parts
    )


@pytest.mark.parametrize("visible_key", [None, "text"])
def test_oversized_metadata_is_retained_as_serialized_parts(visible_key: str | None) -> None:
    payload = {"metadata": {"large": "x" * EVENT_MAX_PAYLOAD_BYTES}}
    if visible_key is not None:
        payload[visible_key] = "small"
    parts = bounded_agent_events(AgentEvent("agent.provider_event", payload))
    assert json.loads("".join(part.payload["chunk"] for part in parts)) == payload
    assert [part.payload["part"] for part in parts] == list(range(1, len(parts) + 1))


@pytest.mark.parametrize(
    ("kind", "expected"),
    [("agent_message_chunk", "agent.message"), ("agent_thought_chunk", "agent.thought")],
)
def test_acp_text_updates_keep_the_visible_text(kind: str, expected: str) -> None:
    update = schema.SessionNotification.model_validate(
        {
            "sessionId": "s",
            "update": {"sessionUpdate": kind, "content": {"type": "text", "text": "visible"}},
        }
    ).update
    events = normalize_acp_update(update)
    assert [(event.event_type, event.payload) for event in events] == [
        (expected, {"text": "visible"})
    ]


@pytest.mark.parametrize(
    "privacy", [{"annotations": {"audience": ["assistant"]}}, {"_meta": {"private": True}}]
)
def test_acp_private_content_never_becomes_a_visible_event(privacy: dict[str, object]) -> None:
    update = schema.SessionNotification.model_validate(
        {
            "sessionId": "s",
            "update": {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": "private", **privacy},
            },
        }
    ).update
    assert normalize_acp_update(update) == ()


def test_acp_non_text_content_is_preserved_without_private_metadata() -> None:
    update = schema.SessionNotification.model_validate(
        {
            "sessionId": "s",
            "update": {
                "sessionUpdate": "agent_message_chunk",
                "content": {
                    "type": "image",
                    "data": "aGVsbG8=",
                    "mimeType": "image/png",
                    "_meta": {"provider": "internal"},
                },
            },
        }
    ).update
    events = normalize_acp_update(update)
    assert len(events) == 1
    event = events[0]
    assert event.event_type == "agent.provider_event"
    content = event.payload["content"]
    assert (content["type"], content["data"], content["mimeType"]) == (
        "image",
        "aGVsbG8=",
        "image/png",
    )
    assert "_meta" not in content and "annotations" not in content


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("in_progress", "agent.tool_call"),
        ("completed", "agent.tool_result"),
        ("failed", "agent.tool_result"),
    ],
)
def test_acp_tool_progress_retains_the_result_state(status: str, expected: str) -> None:
    update = schema.SessionNotification.model_validate(
        {
            "sessionId": "s",
            "update": {
                "sessionUpdate": "tool_call_update",
                "toolCallId": "tool-1",
                "status": status,
                "rawOutput": {"ok": True},
            },
        }
    ).update
    events = normalize_acp_update(update)
    assert len(events) == 1
    event = events[0]
    assert event.event_type == expected
    assert event.payload["tool"] == "tool-1"
    assert json.loads(event.payload["summary"])["raw_output"] == {"ok": True}


def test_acp_plan_updates_retain_owner_visible_entries() -> None:
    update = schema.SessionNotification.model_validate(
        {
            "sessionId": "s",
            "update": {
                "sessionUpdate": "plan",
                "entries": [{"content": "Review", "priority": "medium", "status": "pending"}],
            },
        }
    ).update
    events = normalize_acp_update(update)
    assert len(events) == 1
    event = events[0]
    assert (event.event_type, event.payload) == (
        "agent.plan",
        {"plan": [{"content": "Review", "priority": "medium", "status": "pending"}]},
    )


def test_acp_configuration_updates_keep_the_public_configuration() -> None:
    update = schema.SessionNotification.model_validate(
        {"sessionId": "s", "update": {"sessionUpdate": "config_option_update", "configOptions": []}}
    ).update
    events = normalize_acp_update(update)
    assert len(events) == 1
    event = events[0]
    assert event.event_type == "agent.provider_event"
    assert event.payload["update"]["configOptions"] == []


def test_unrecognized_acp_updates_do_not_emit_an_event() -> None:
    assert normalize_acp_update(object()) == ()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            {
                "event": "step_update",
                "step_update": {"step_type": "agent_response", "text_delta": "hello"},
            },
            "agent.message",
        ),
        (
            {"event": "step_update", "step_update": {"step_type": "tool", "state": "ACTIVE"}},
            "agent.tool_call",
        ),
        (
            {"event": "step_update", "step_update": {"step_type": "tool", "state": "DONE"}},
            "agent.tool_result",
        ),
        ({"event": "step_update", "step_update": []}, "agent.provider_event"),
    ],
)
def test_antigravity_updates_map_to_the_owner_event_vocabulary(
    raw: dict[str, object], expected: str
) -> None:
    events = normalize_antigravity_event(raw)
    assert len(events) == 1
    event = events[0]
    assert event.event_type == expected


def test_antigravity_result_events_exclude_response_and_structured_output() -> None:
    events = normalize_antigravity_event(
        {
            "event": "result",
            "result": {
                "status": "SUCCESS",
                "response": "private",
                "structured_output": {"secret": "value"},
                "duration_seconds": 1.0,
            },
        }
    )
    assert len(events) == 1
    event = events[0]
    assert event.payload == {"status": "SUCCESS", "duration_seconds": 1.0}


def test_unrecognized_antigravity_lines_do_not_create_normalized_events() -> None:
    assert normalize_antigravity_event({"event": "unknown"}) == ()


def test_a_fresh_registry_cache_prevents_another_network_fetch(
    registry_network: RegistryNetwork, tmp_path: Path
) -> None:
    fetched = load_registry(cache_root=tmp_path, now=NOW)
    cached = load_registry(cache_root=tmp_path, now=NOW + timedelta(seconds=1))
    assert fetched.agents == cached.agents
    assert registry_network.requests == [REGISTRY_URL]
    assert not cached.stale


def test_a_stale_registry_is_refreshed(registry_network: RegistryNetwork, tmp_path: Path) -> None:
    load_registry(cache_root=tmp_path, now=NOW)
    later = NOW + timedelta(seconds=REGISTRY_CACHE_TTL_SECONDS + 1)
    refreshed = load_registry(cache_root=tmp_path, now=later)
    assert refreshed.fetched_at == later and not refreshed.stale
    assert registry_network.requests == [REGISTRY_URL, REGISTRY_URL]


def test_offline_refresh_returns_only_a_validated_stale_cache(
    registry_network: RegistryNetwork, tmp_path: Path
) -> None:
    load_registry(cache_root=tmp_path, now=NOW)
    registry_network.error = URLError("offline")
    cached = load_registry(
        cache_root=tmp_path, now=NOW + timedelta(seconds=REGISTRY_CACHE_TTL_SECONDS + 1)
    )
    assert cached.stale and cached.warning is not None
    assert cached.fetched_at == NOW


def test_offline_discovery_without_a_cache_is_a_relay_error(
    registry_network: RegistryNetwork, tmp_path: Path
) -> None:
    registry_network.error = URLError("offline")
    with pytest.raises(AgentDiscoveryError):
        load_registry(cache_root=tmp_path, now=NOW)


@pytest.mark.parametrize("status", [404, 500])
def test_registry_http_failures_are_relay_errors(
    registry_network: RegistryNetwork, tmp_path: Path, status: int
) -> None:
    registry_network.status = status
    with pytest.raises(AgentDiscoveryError):
        load_registry(cache_root=tmp_path, now=NOW)


@pytest.mark.parametrize("corruption", ["json", "future", "naive", "invalid-document"])
def test_unusable_registry_caches_are_replaced_by_fresh_validation(
    registry_network: RegistryNetwork, tmp_path: Path, corruption: str
) -> None:
    cache = tmp_path / "registry.json"
    if corruption == "json":
        cache.write_text("{", encoding="utf-8")
    else:
        fetched_at = (
            (NOW + timedelta(days=1)).isoformat()
            if corruption == "future"
            else (
                NOW.replace(tzinfo=None).isoformat() if corruption == "naive" else NOW.isoformat()
            )
        )
        document = {} if corruption == "invalid-document" else registry_document()
        cache.write_text(
            json.dumps({"fetched_at": fetched_at, "document": document}), encoding="utf-8"
        )
    result = load_registry(cache_root=tmp_path, now=NOW)
    assert result.schema_version == registry_network.document["version"]
    assert registry_network.requests == [REGISTRY_URL]


@pytest.mark.parametrize(
    "raw", [[], {}, {"version": "v1", "agents": {}}, {"version": "v1", "agents": [None]}]
)
def test_invalid_registry_top_level_shapes_are_rejected(raw: object) -> None:
    with pytest.raises(AgentDiscoveryError):
        validate_registry_document(raw)


@pytest.mark.parametrize(
    "field", ["duplicate", "repository", "distribution", "args", "authMethods"]
)
def test_invalid_registry_metadata_is_rejected(field: str) -> None:
    document = registry_document()
    first = document["agents"][0]
    if field == "duplicate":
        document["agents"].append(first)
    elif field == "repository":
        first[field] = "http://example.invalid/repo"
    elif field == "distribution":
        first[field] = {"unknown": {"package": "test"}}
    elif field == "args":
        first["distribution"]["npx"][field] = [1]
    else:
        first[field] = [None]
    with pytest.raises(AgentDiscoveryError):
        validate_registry_document(document)


def test_binary_registry_distributions_keep_the_platform_and_command() -> None:
    document = {
        "version": "v1",
        "agents": [
            {
                "id": "fake",
                "name": "Fake",
                "version": "1",
                "auth_methods": ["login"],
                "distribution": {
                    "binary": {
                        "linux-x86_64": {
                            "archive": "https://example.invalid/fake.zip",
                            "cmd": "fake",
                            "args": ["--acp"],
                        }
                    }
                },
            }
        ],
    }
    _version, agents = validate_registry_document(document)
    (binary,) = agents["fake"].distributions
    assert (binary.manager, binary.package, binary.args) == (
        "binary:linux-x86_64",
        "https://example.invalid/fake.zip#fake",
        ("--acp",),
    )
