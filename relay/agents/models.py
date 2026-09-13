"""Provider-independent records shared by Relay's agent adapters."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

from relay.execution.runner import AttemptContext
from relay.workflows.schema import AgentNode

DriverName = Literal["acp", "antigravity"]


@dataclass(frozen=True, slots=True)
class AgentCommand:
    """An installed executable and its shell-free adapter arguments."""

    executable: str
    args: tuple[str, ...] = ()

    def argv(self) -> tuple[str, ...]:
        return (self.executable, *self.args)


@dataclass(frozen=True, slots=True)
class AgentProfile:
    """Certified compatibility facts for one of Relay's five agent families."""

    agent_id: str
    display_name: str
    driver: DriverName
    registry_id: str | None
    executable_names: tuple[str, ...]
    adapter_args: tuple[str, ...]
    model_config_id: str | None
    required_client_methods: frozenset[str]
    permission_profiles: frozenset[str]
    install_url: str
    login_guidance: str


@dataclass(frozen=True, slots=True)
class DiscoveredAgent:
    """Detection result that never installs or authenticates an agent."""

    profile: AgentProfile
    command: AgentCommand | None
    detected_version: str = ""
    reason: str | None = None

    @property
    def installed(self) -> bool:
        return self.command is not None


@dataclass(frozen=True, slots=True)
class ModelObservation:
    """One advisory model value observed in a disposable live session."""

    agent_id: str
    model_value: str
    model_name: str
    config_id: str
    agent_version: str
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class ProbeRequirement:
    """Exact value one candidate must advertise and select for launch."""

    model_value: str


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """Fresh capability evidence and bounded cleanup status for one agent."""

    agent_id: str
    models: tuple[ModelObservation, ...] = ()
    confirmed_values: frozenset[str] = field(default_factory=frozenset)
    failures: Mapping[str, str] = field(default_factory=dict)
    cleanup_warning: str | None = None
    general_error: str | None = None


@dataclass(frozen=True, slots=True)
class AgentExecutionContext:
    """Immutable node facts consumed by a selected provider adapter."""

    attempt: AttemptContext
    node: AgentNode
    agent_id: str
    model_value: str
    permission_profile: str
    command: AgentCommand

    @property
    def cwd(self) -> Path:
        return self.attempt.worktree


@dataclass(frozen=True, slots=True)
class AgentResult:
    """Provider-independent terminal result after one fresh session."""

    succeeded: bool
    stop_reason: str
    exit_code: int | None = None
    error_code: str | None = None
    denied_write_targets: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RegistryDistribution:
    """Validated install metadata retained without executing it."""

    manager: str
    package: str
    version: str
    args: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RegistryAgent:
    """Validated registry agent metadata used by discovery and the UI."""

    agent_id: str
    name: str
    version: str
    repository: str | None
    website: str | None
    auth_methods: tuple[str, ...]
    distributions: tuple[RegistryDistribution, ...]


@dataclass(frozen=True, slots=True)
class RegistrySnapshot:
    """Registry document plus fetch/cache provenance."""

    schema_version: str
    agents: Mapping[str, RegistryAgent]
    source_url: str
    fetched_at: datetime
    cache_age_seconds: float
    stale: bool
    warning: str | None = None


__all__ = [
    "AgentCommand",
    "AgentExecutionContext",
    "AgentProfile",
    "AgentResult",
    "DiscoveredAgent",
    "DriverName",
    "ModelObservation",
    "ProbeRequirement",
    "ProbeResult",
    "RegistryAgent",
    "RegistryDistribution",
    "RegistrySnapshot",
]
