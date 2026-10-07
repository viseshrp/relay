"""Owner defaults applied only to omitted workflow choices at launch."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from pydantic import Field, ValidationError, field_validator

from relay.agents.profiles import PROFILES
from relay.constants import (
    DEFAULT_FIX_INSTRUCTION,
    DEFAULT_REPAIR_ROUNDS,
    DEFAULT_VERIFY_INSTRUCTION,
    MAX_LOOP_ITERATIONS,
)
from relay.errors import ConfigError, WorkflowValidationError

from .routing import effective_agent_order
from .schema import (
    DURATION_PATTERN,
    NODE_ID_PATTERN,
    AgentNode,
    AgentOptions,
    CommandNode,
    LoopNode,
    NodeDefinition,
    RecoveryPolicy,
    SharedCommandReference,
    StrictModel,
    WorkflowDefinition,
    validate_environment,
)
from .validation import ValidatedWorkflow


class ProviderDefaults(AgentOptions):
    """Options belong to one exact model, never to a guessed model family."""

    model: str | None = Field(default=None, min_length=1, max_length=500)


class RepairDefaults(StrictModel):
    """Initial values for new repair rules; saved rules retain their own values."""

    max_rounds: int = Field(default=DEFAULT_REPAIR_ROUNDS, ge=1, le=MAX_LOOP_ITERATIONS)
    fix_instruction: str = Field(default=DEFAULT_FIX_INSTRUCTION, min_length=1, max_length=16000)
    verify_instruction: str = Field(
        default=DEFAULT_VERIFY_INSTRUCTION, min_length=1, max_length=16000
    )


class WorkflowDefaults(StrictModel):
    """Cross-project fallbacks with the same bounds as workflow settings."""

    model: str | None = Field(default=None, min_length=1, max_length=500)
    providers: dict[str, ProviderDefaults] = Field(default_factory=dict)
    timeout: str | None = None
    auto_retry: bool = True
    recovery: RecoveryPolicy = Field(default_factory=RecoveryPolicy)
    repairs: RepairDefaults = Field(default_factory=RepairDefaults)
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
            f"{'.'.join(str(p) for p in row['loc'])}: {row['msg']}"
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


def _nodes_with_defaults(
    nodes: Mapping[str, NodeDefinition],
    definition: WorkflowDefinition,
    defaults: WorkflowDefaults,
    owner_agents: tuple[str, ...],
    launch_model: str | None,
) -> dict[str, NodeDefinition]:
    resolved: dict[str, NodeDefinition] = {}
    for key, node in nodes.items():
        updates: dict[str, object] = {}
        # Human waits and structural deadlines remain workflow decisions.
        if isinstance(node, (AgentNode, CommandNode)) and "timeout" not in node.model_fields_set:
            updates["timeout"] = defaults.timeout
        if isinstance(node, AgentNode):
            order = effective_agent_order(node.agents, definition.agents, owner_agents)
            model = node.model or launch_model or definition.model or defaults.model
            if model is None and order:
                provider = defaults.providers.get(order[0])
                model = provider.model if provider is not None else None
            updates["model"] = model
            options = dict(node.agent_options)
            for agent, provider in defaults.providers.items():
                # An option's absence inherits; an explicit null preserves agent defaults.
                inherited = (
                    provider.model_dump(exclude={"model"}) if provider.model == model else {}
                )
                if node.permission_profile is not None:
                    inherited.pop("permission_mode", None)
                explicit = options.get(agent)
                if explicit is not None:
                    inherited.update(explicit.model_dump(exclude_unset=True))
                options[agent] = AgentOptions.model_validate(inherited)
            updates["agent_options"] = options
            if "auto_retry" not in node.model_fields_set:
                updates["auto_retry"] = defaults.auto_retry
        elif isinstance(node, CommandNode):
            if isinstance(node.run, SharedCommandReference):
                arguments = defaults.commands.get(node.run.command)
                if arguments is None:
                    message = (
                        f"Shared command {node.run.command!r} is not configured for this project."
                    )
                    raise WorkflowValidationError(message)
                updates["run"] = list(arguments)
            inherited_env = defaults.env if definition.inherit_env else {}
            updates["env"] = (
                {**inherited_env, **definition.env, **node.env}
                if node.inherit_env
                else dict(node.env)
            )
        elif isinstance(node, LoopNode):
            updates["body"] = _nodes_with_defaults(
                node.body, definition, defaults, owner_agents, launch_model
            )
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
                definition,
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
        subworkflows={
            key: replace(child, definition=resolve(child.definition))
            for key, child in workflow.subworkflows.items()
        },
    )
