"""Owner defaults applied only to omitted workflow choices at launch."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from pydantic import Field, ValidationError, field_validator

from relay.agents.profiles import PROFILES
from relay.errors import ConfigError

from .routing import effective_agent_order
from .schema import (
    DURATION_PATTERN,
    NODE_ID_PATTERN,
    ActionsJobNode,
    AgentNode,
    AgentOptions,
    RecoveryPolicy,
    StrictModel,
    WorkflowDefinition,
    validate_environment,
)
from .validation import ValidatedWorkflow


class ProviderDefaults(AgentOptions):
    """Options belong to one exact model, never to a guessed model family."""

    model: str | None = Field(default=None, min_length=1, max_length=500)


class WorkflowDefaults(StrictModel):
    """Cross-project fallbacks with the same bounds as workflow settings."""

    model: str | None = Field(default=None, min_length=1, max_length=500)
    providers: dict[str, ProviderDefaults] = Field(default_factory=dict)
    timeout: str | None = None
    auto_retry: bool = True
    recovery: RecoveryPolicy = Field(default_factory=RecoveryPolicy)
    commands: dict[str, list[str]] = Field(default_factory=dict)
    env: dict[str, str] = Field(default_factory=dict)

    @field_validator("commands")
    @classmethod
    def valid_commands(cls, value: dict[str, list[str]]) -> dict[str, list[str]]:
        del cls
        for name, arguments in value.items():
            if NODE_ID_PATTERN.fullmatch(name) is None:
                message = "Use a lowercase command name with letters, numbers, and underscores"
                raise ValueError(message)
            if not arguments or not arguments[0] or any("\x00" in item for item in arguments):
                message = "Shared commands need a program and arguments without NUL characters"
                raise ValueError(message)
        return value

    validate_env = field_validator("env")(validate_environment)

    @field_validator("providers")
    @classmethod
    def known_providers(cls, value: dict[str, ProviderDefaults]) -> dict[str, ProviderDefaults]:
        del cls
        if value.keys() - PROFILES.keys():
            message = "Choose a supported Relay agent"
            raise ValueError(message)
        return value

    @field_validator("timeout")
    @classmethod
    def valid_timeout(cls, value: str | None) -> str | None:
        del cls
        if value is not None and DURATION_PATTERN.fullmatch(value) is None:
            message = "Use a duration such as 30s, 15m, or 2h"
            raise ValueError(message)
        return value


def validate_defaults(raw: object) -> WorkflowDefaults:
    """Keep configuration failures inside Relay's public error contract."""
    try:
        defaults = WorkflowDefaults.model_validate(raw)
    except ValidationError as error:
        issues = [
            f"{'.'.join(str(p) for p in row['loc'])}: {row['msg'].removeprefix('Value error, ')}"
            for row in error.errors(include_url=False, include_context=False)
        ]
        message = "Invalid workflow defaults:\n" + "\n".join(issues)
        raise ConfigError(message) from None
    for provider in defaults.providers.values():
        if provider.model is None and (
            provider.effort is not None or provider.permission_mode is not None
        ):
            message = "Thinking effort and permissions require an exact model."
            raise ConfigError(message)
    return defaults


def _agent_with_defaults(
    node: AgentNode,
    defaults: WorkflowDefaults,
    owner_agents: tuple[str, ...],
    launch_model: str | None,
) -> AgentNode:
    order = effective_agent_order(node.agents, owner_agents)
    model = node.model or launch_model or defaults.model
    if model is None and order:
        provider = defaults.providers.get(order[0])
        model = provider.model if provider is not None else None
    updates: dict[str, object] = {"model": model}
    if "timeout" not in node.model_fields_set:
        updates["timeout"] = defaults.timeout
    options = dict(node.agent_options)
    for agent, provider in defaults.providers.items():
        # An absent choice inherits; explicit null keeps the provider default.
        inherited = provider.model_dump(exclude={"model"}) if provider.model == model else {}
        if node.permission_profile is not None:
            inherited.pop("permission_mode", None)
        explicit = options.get(agent)
        if explicit is not None:
            inherited.update(explicit.model_dump(exclude_unset=True))
        options[agent] = AgentOptions.model_validate(inherited)
    updates["agent_options"] = options
    if "auto_retry" not in node.model_fields_set:
        updates["auto_retry"] = defaults.auto_retry
    return node.model_copy(update=updates)


def _nodes_with_defaults(
    nodes: Mapping[str, ActionsJobNode],
    defaults: WorkflowDefaults,
    owner_agents: tuple[str, ...],
    launch_model: str | None,
) -> dict[str, ActionsJobNode]:
    resolved = {}
    for key, node in nodes.items():
        updates: dict[str, object] = {
            "bound_agents": {
                step: _agent_with_defaults(agent, defaults, owner_agents, launch_model)
                for step, agent in node.bound_agents.items()
            }
        }
        if "timeout-minutes" not in node.job and defaults.timeout:
            updates["timeout"] = defaults.timeout
        resolved[key] = node.model_copy(update=updates)
    return resolved


def apply_workflow_defaults(
    workflow: ValidatedWorkflow,
    defaults: WorkflowDefaults,
    owner_agents: tuple[str, ...],
    launch_model: str | None,
) -> ValidatedWorkflow:
    """Resolve fallbacks without touching source bytes, prompts, or dependencies."""

    def resolve(definition: WorkflowDefinition) -> WorkflowDefinition:
        updates: dict[str, object] = {
            "nodes": _nodes_with_defaults(
                definition.nodes,
                defaults,
                owner_agents,
                launch_model,
            )
        }
        explicit = definition.recovery.model_dump(exclude_unset=True)
        inherited = defaults.recovery.model_dump()
        inherited.update(explicit)
        updates["recovery"] = RecoveryPolicy.model_validate(inherited)
        return definition.model_copy(update=updates)

    return replace(
        workflow,
        root=replace(workflow.root, definition=resolve(workflow.root.definition)),
    )
