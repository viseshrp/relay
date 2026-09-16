"""Bounded retrieval and validated caching of the official ACP registry."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import NoReturn
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from relay.constants import REGISTRY_CACHE_TTL_SECONDS, REGISTRY_FETCH_TIMEOUT_SECONDS
from relay.errors import AgentDiscoveryError
from relay.paths import registry_cache_dir

from .models import RegistryAgent, RegistryDistribution, RegistrySnapshot

REGISTRY_URL = "https://cdn.agentclientprotocol.com/registry/v1/latest/registry.json"
_CACHE_FILE = "registry.json"
_USER_AGENT = "relay-app/1 ACP-registry-client"


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        message = f"The ACP registry field {field!r} must be non-empty text."
        raise AgentDiscoveryError(message)
    return value


def _optional_url(value: object, field: str) -> str | None:
    if value is None:
        return None
    text = _required_text(value, field)
    if not text.startswith("https://"):
        message = f"The ACP registry field {field!r} must use HTTPS."
        raise AgentDiscoveryError(message)
    return text


def _args(value: object, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        message = f"The ACP registry field {field!r} must be a list of strings."
        raise AgentDiscoveryError(message)
    return tuple(value)


def _package_version(package: str, fallback: str) -> str:
    marker = package.rfind("@")
    return package[marker + 1 :] if marker > 0 else fallback


def _parse_distributions(raw: object, agent_version: str) -> tuple[RegistryDistribution, ...]:
    if not isinstance(raw, dict) or not raw:
        message = "An ACP registry agent has no usable distribution metadata."
        raise AgentDiscoveryError(message)
    result: list[RegistryDistribution] = []
    for manager, value in raw.items():
        if manager in {"npx", "uvx"}:
            if not isinstance(value, dict):
                message = f"The ACP registry distribution {manager!r} is malformed."
                raise AgentDiscoveryError(message)
            package = _required_text(value.get("package"), f"distribution.{manager}.package")
            result.append(
                RegistryDistribution(
                    manager=manager,
                    package=package,
                    version=_package_version(package, agent_version),
                    args=_args(value.get("args"), f"distribution.{manager}.args"),
                )
            )
        elif manager == "binary":
            if not isinstance(value, dict) or not value:
                message = "The ACP registry binary distribution is malformed."
                raise AgentDiscoveryError(message)
            for platform, record in value.items():
                if not isinstance(platform, str) or not isinstance(record, dict):
                    message = "An ACP registry binary platform record is malformed."
                    raise AgentDiscoveryError(message)
                archive = _optional_url(record.get("archive"), f"binary.{platform}.archive")
                command = _required_text(record.get("cmd"), f"binary.{platform}.cmd")
                if archive is None:
                    message = f"The ACP registry binary {platform!r} has no archive."
                    raise AgentDiscoveryError(message)
                result.append(
                    RegistryDistribution(
                        manager=f"binary:{platform}",
                        package=f"{archive}#{command}",
                        version=agent_version,
                        args=_args(record.get("args"), f"binary.{platform}.args"),
                    )
                )
        else:
            message = f"The ACP registry distribution manager {manager!r} is unsupported."
            raise AgentDiscoveryError(message)
    return tuple(result)


def _auth_methods(raw: object) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        message = "The ACP registry auth methods must be a list."
        raise AgentDiscoveryError(message)
    result: list[str] = []
    for item in raw:
        if isinstance(item, str) and item:
            result.append(item)
        elif isinstance(item, dict):
            result.append(_required_text(item.get("id"), "auth_methods.id"))
        else:
            message = "An ACP registry auth method is malformed."
            raise AgentDiscoveryError(message)
    return tuple(result)


def validate_registry_document(raw: object) -> tuple[str, dict[str, RegistryAgent]]:
    """Validate the documented registry structure and reject duplicate identities."""
    if not isinstance(raw, dict):
        message = "The ACP registry response is not a JSON object."
        raise AgentDiscoveryError(message)
    version = _required_text(raw.get("version"), "version")
    rows = raw.get("agents")
    if not isinstance(rows, list):
        message = "The ACP registry agents field is not a list."
        raise AgentDiscoveryError(message)
    agents: dict[str, RegistryAgent] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            message = f"ACP registry agent {index} is not an object."
            raise AgentDiscoveryError(message)
        agent_id = _required_text(row.get("id"), f"agents[{index}].id")
        if agent_id in agents:
            message = f"The ACP registry repeats agent id {agent_id!r}."
            raise AgentDiscoveryError(message)
        agent_version = _required_text(row.get("version"), f"agents[{index}].version")
        agents[agent_id] = RegistryAgent(
            agent_id=agent_id,
            name=_required_text(row.get("name"), f"agents[{index}].name"),
            version=agent_version,
            repository=_optional_url(row.get("repository"), f"agents[{index}].repository"),
            website=_optional_url(row.get("website"), f"agents[{index}].website"),
            auth_methods=_auth_methods(row.get("auth_methods", row.get("authMethods"))),
            distributions=_parse_distributions(row.get("distribution"), agent_version),
        )
    return version, agents


def _read_cache(path: Path, now: datetime) -> tuple[object, datetime] | None:
    try:
        payload: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    fetched = payload.get("fetched_at")
    if not isinstance(fetched, str):
        return None
    try:
        fetched_at = datetime.fromisoformat(fetched)
    except ValueError:
        return None
    if fetched_at.tzinfo is None or fetched_at > now:
        return None
    return payload.get("document"), fetched_at


def _write_cache(path: Path, document: object, fetched_at: datetime) -> None:
    encoded = json.dumps(
        {"fetched_at": fetched_at.isoformat(), "document": document},
        separators=(",", ":"),
        ensure_ascii=False,
    )
    temporary = path.with_suffix(".tmp")
    temporary.write_text(encoded, encoding="utf-8")
    temporary.replace(path)


def _unexpected_status(status: int) -> NoReturn:
    message = f"The ACP registry returned HTTP {status}."
    raise AgentDiscoveryError(message)


def _fetch() -> object:
    request = Request(REGISTRY_URL, headers={"User-Agent": _USER_AGENT})
    try:
        with urlopen(request, timeout=REGISTRY_FETCH_TIMEOUT_SECONDS) as response:  # noqa: S310
            if response.status != 200:
                _unexpected_status(response.status)
            return json.load(response)
    except AgentDiscoveryError:
        raise
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError):
        message = "Relay could not fetch the official ACP registry."
        raise AgentDiscoveryError(
            message,
            next_action="Check network access or retry with a validated cached registry.",
        ) from None


def load_registry(
    *,
    cache_root: Path | None = None,
    now: datetime | None = None,
) -> RegistrySnapshot:
    """Use fresh cache, refresh stale cache, or surface an explicit stale fallback."""
    checked_at = now or datetime.now(timezone.utc)
    root = cache_root or registry_cache_dir(create=True)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    cache_path = root / _CACHE_FILE
    cached = _read_cache(cache_path, checked_at)
    if cached is not None:
        document, fetched_at = cached
        age = max(0.0, (checked_at - fetched_at).total_seconds())
        if age < REGISTRY_CACHE_TTL_SECONDS:
            try:
                version, agents = validate_registry_document(document)
            except AgentDiscoveryError:
                cached = None
            else:
                return RegistrySnapshot(version, agents, REGISTRY_URL, fetched_at, age, False)
    try:
        document = _fetch()
        version, agents = validate_registry_document(document)
        _write_cache(cache_path, document, checked_at)
        return RegistrySnapshot(version, agents, REGISTRY_URL, checked_at, 0.0, False)
    except AgentDiscoveryError as error:
        if cached is None:
            raise
        document, fetched_at = cached
        version, agents = validate_registry_document(document)
        age = max(0.0, (checked_at - fetched_at).total_seconds())
        return RegistrySnapshot(
            version,
            agents,
            REGISTRY_URL,
            fetched_at,
            age,
            True,
            warning=f"{error.message} Using a stale validated cache ({round(age)} seconds old).",
        )


def registry_agent(snapshot: RegistrySnapshot, agent_id: str) -> RegistryAgent:
    """Resolve one entry or fail without guessing another agent family."""
    try:
        return snapshot.agents[agent_id]
    except KeyError:
        message = f"The official ACP registry has no agent {agent_id!r}."
        raise AgentDiscoveryError(message, context={"agent": agent_id}) from None


__all__ = [
    "REGISTRY_URL",
    "load_registry",
    "registry_agent",
    "validate_registry_document",
]
