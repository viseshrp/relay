"""Launch choices shared by application services and persistence adapters."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TypedDict

from relay.workflows.defaults import WorkflowDefaults


class FrozenSecretReference(TypedDict):
    source: str
    reference: str
    revision: str


class FrozenEnvironmentBindings(TypedDict):
    vars: dict[str, str]
    secrets: dict[str, FrozenSecretReference]


class FrozenLaunchBindings(TypedDict):
    vars: dict[str, str]
    secret_refs: dict[str, FrozenSecretReference]
    environment_bindings: dict[str, FrozenEnvironmentBindings]
    environments: dict[str, dict[str, object]]


@dataclass(frozen=True, slots=True)
class LaunchRequest:
    """Owner-selected values accepted by the browser launch surface."""

    workflow_key: str
    inputs: Mapping[str, object]
    model: str | None
    cleanup_policy: str
    entry_point: str | None
    owner_agents: Sequence[str]
    launcher: str
    source_branch: str | None = None
    defaults: WorkflowDefaults = field(default_factory=WorkflowDefaults, kw_only=True)
    event_context: Mapping[str, object] = field(default_factory=dict, kw_only=True)
    # Owner-selected workflow note IDs, frozen into the snapshot in this order.
    notes: Sequence[str] = field(default=(), kw_only=True)
