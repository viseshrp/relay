"""Owner settings for an unstarted agent step in a paused run."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from relay.constants import DEFAULT_UNSTARTED_HANDOFF_PROMPT
from relay.errors import ConfigError, PersistenceError
from relay.execution.control import ControlResult, valid_idempotency_key
from relay.execution.resume import RetryAgent, RetryEffort, RetryPermissionMode


@dataclass(frozen=True, slots=True)
class UnstartedAgentTarget:
    """Current choices and project used for validation outside a transaction."""

    run_id: str
    node_run_id: str
    scope_path: str
    project_path: str
    route: Mapping[str, object]
    options: Mapping[str, object]


class StepSettingsStore(Protocol):
    def unstarted_agent_target(
        self, run_id: str, scope_path: str, idempotency_key: str
    ) -> UnstartedAgentTarget | None: ...

    def save_unstarted_agent_settings(
        self,
        target: UnstartedAgentTarget,
        options: Mapping[str, object],
        idempotency_key: str,
    ) -> ControlResult: ...


def change_unstarted_agent_settings(
    store: StepSettingsStore,
    run_id: str,
    scope_path: str,
    idempotency_key: str,
    validate: Callable[[UnstartedAgentTarget, Mapping[str, object]], None],
    *,
    agent: RetryAgent | None = None,
    effort: RetryEffort | None = None,
    permission_mode: RetryPermissionMode | None = None,
) -> ControlResult:
    """Validate the chosen provider, then atomically recheck that no attempt began."""
    if agent is None and effort is None and permission_mode is None:
        message = "Choose an agent, effort, or permission-mode setting to save."
        raise ConfigError(message)
    if not valid_idempotency_key(idempotency_key):
        return ControlResult.INVALID
    target = store.unstarted_agent_target(run_id, scope_path, idempotency_key)
    if target is None:
        return ControlResult.ALREADY_APPLIED
    agent_id, model_value = target.route.get("selected_agent"), target.route.get("model_value")
    if not isinstance(agent_id, str) or not isinstance(model_value, str):
        message = "The stored agent selection is invalid."
        raise PersistenceError(message)
    if agent is not None:
        agent = agent.for_selection(
            agent_id,
            model_value,
            default_handoff=DEFAULT_UNSTARTED_HANDOFF_PROMPT,
        )
        options = agent.to_route()
    else:
        options = dict(target.options)
        if effort is not None:
            options["effort"] = effort.value
        if permission_mode is not None:
            options["permission_mode"] = permission_mode.value
    validate(target, {**target.route, **options})
    return store.save_unstarted_agent_settings(target, options, idempotency_key)
