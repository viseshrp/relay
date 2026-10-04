"""Provider configuration discovery and exact override validation."""

from __future__ import annotations

from collections.abc import Sequence

from acp import schema

from relay.errors import AgentConfigurationError

from .models import (
    AgentConfiguration,
    ConfigurationChoice,
    ConfigurationSelector,
    ProbeRequirement,
)

ConfigOption = schema.SessionConfigOptionSelect | schema.SessionConfigOptionBoolean


def select_choices(option: schema.SessionConfigOptionSelect) -> tuple[ConfigurationChoice, ...]:
    """Keep the provider's ordering, labels, descriptions, and grouped values."""
    values = []
    for item in option.options:
        children = item.options if isinstance(item, schema.SessionConfigSelectGroup) else [item]
        values.extend(
            ConfigurationChoice(child.value, child.name, child.description) for child in children
        )
    return tuple(values)


def _selector(
    options: Sequence[ConfigOption], category: str, identifiers: tuple[str, ...]
) -> ConfigurationSelector | None:
    selects = [item for item in options if isinstance(item, schema.SessionConfigOptionSelect)]
    # ACP categories are optional. Known IDs cover adapters that omit them.
    matches = [item for item in selects if item.category == category]
    if not matches:
        matches = [item for item in selects if item.id in identifiers]
    if not matches:
        return None
    option = matches[0]
    return ConfigurationSelector(
        option.id, option.name, option.current_value, select_choices(option)
    )


def acp_configuration(
    agent_id: str,
    model_value: str,
    options: Sequence[ConfigOption],
    modes: schema.SessionModeState | None,
) -> AgentConfiguration:
    """Read effort after model selection; prefer config options over legacy modes."""
    effort = _selector(options, "thought_level", ("reasoning_effort", "effort", "thought_level"))
    mode = _selector(options, "mode", ("mode", "permission_mode", "approval_mode"))
    if mode is None and modes is not None:
        mode = ConfigurationSelector(
            "session/mode",
            "Permission mode",
            modes.current_mode_id,
            tuple(
                ConfigurationChoice(item.id, item.name, item.description)
                for item in modes.available_modes
            ),
            "session_mode",
        )
    return AgentConfiguration(agent_id, model_value, effort, mode)


def native_configuration(agent_id: str, model_value: str) -> AgentConfiguration:
    """Antigravity's exact model slugs already identify their reasoning effort."""
    effort_value = model_value.rsplit("-", 1)[-1]
    effort = None
    if effort_value in {"low", "medium", "high", "xhigh", "max"}:
        effort = ConfigurationSelector(
            "native:effort",
            "Effort",
            effort_value,
            (
                ConfigurationChoice(
                    effort_value,
                    effort_value.capitalize(),
                    "Choose another exact model to change its effort.",
                ),
            ),
            "native",
        )
    mode = ConfigurationSelector(
        "native:permission_mode",
        "Permission mode",
        "respect_settings",
        (
            ConfigurationChoice("respect_settings", "Respect settings"),
            ConfigurationChoice(
                "accept-edits", "Accept edits", "Use the tool's accept-edits execution mode."
            ),
            ConfigurationChoice("plan", "Plan", "Use the tool's planning mode."),
            ConfigurationChoice("auto_approve", "Auto approve", "Approve all tool requests."),
        ),
        "native",
    )
    return AgentConfiguration(agent_id, model_value, effort, mode)


def require_choice(
    configuration: AgentConfiguration,
    field: str,
    value: str,
) -> ConfigurationSelector:
    """Reject missing selectors and values instead of guessing provider support."""
    selector = getattr(configuration, field)
    if selector is None or value not in {choice.value for choice in selector.choices}:
        message = (
            f"Agent {configuration.agent_id!r} does not advertise {field} {value!r} "
            f"for exact model {configuration.model_value!r}."
        )
        raise AgentConfigurationError(
            message, context={"agent": configuration.agent_id, "option": field}
        )
    return selector


def validate_native_requirement(
    configuration: AgentConfiguration, requirement: ProbeRequirement
) -> None:
    for field in ("effort", "permission_mode"):
        value = getattr(requirement, field)
        if value is not None:
            require_choice(configuration, field, value)
