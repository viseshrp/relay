"""Provider-neutral agent port, route preflight, and node-driver bridge."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable, Mapping
from pathlib import Path
from typing import Protocol

from relay.constants import AGENT_PROBE_TIMEOUT_SECONDS
from relay.errors import (
    AgentAuthError,
    AgentLaunchError,
    AgentProtocolError,
    ModelSelectionRejectedError,
    ModelSelectorError,
    ModelUnavailableError,
    RelayError,
)
from relay.execution.runner import AttemptContext, ExecutionOutcome, OutcomeKind
from relay.execution.state import AttemptStopReason, EventSource
from relay.workflows.routing import RouteEntry, RouteRequirement
from relay.workflows.schema import AgentNode

from .acp_driver import AcpDriver
from .antigravity_driver import AntigravityDriver
from .discovery import discover_agents, discovered_by_id
from .events import AgentEvent, bounded_agent_events
from .models import (
    AgentCommand,
    AgentExecutionContext,
    AgentProfile,
    AgentResult,
    DiscoveredAgent,
    ModelObservation,
    ProbeRequirement,
    ProbeResult,
    RegistrySnapshot,
)


class AgentDriver(Protocol):
    """The complete provider boundary used by probes and node execution."""

    async def probe_models(
        self,
        requirements: tuple[ProbeRequirement, ...],
        cwd: Path,
    ) -> ProbeResult: ...

    def start_attempt(
        self,
        context: AgentExecutionContext,
    ) -> AsyncIterator[AgentEvent]: ...

    async def cancel(self) -> None: ...

    async def finalize(self) -> AgentResult: ...


class AgentObservationStore(Protocol):
    """Advisory cache port; fresh probes remain authoritative for launches."""

    def replace_model_observations(
        self,
        agent_id: str,
        observations: tuple[ModelObservation, ...],
    ) -> None: ...


def _driver(profile: AgentProfile, command: AgentCommand) -> AgentDriver:
    if profile.driver == "antigravity":
        return AntigravityDriver(profile, command)
    return AcpDriver(profile, command)


async def _bounded_probe(
    driver: AgentDriver,
    requirements: tuple[ProbeRequirement, ...],
    cwd: Path,
    agent_id: str,
) -> ProbeResult:
    try:
        return await asyncio.wait_for(
            driver.probe_models(requirements, cwd), timeout=AGENT_PROBE_TIMEOUT_SECONDS
        )
    except TimeoutError:
        message = (
            f"agent_launch_error: Agent {agent_id!r} did not complete its probe in "
            f"{AGENT_PROBE_TIMEOUT_SECONDS:g} seconds."
        )
        return ProbeResult(
            agent_id,
            failures={item.model_value: message for item in requirements},
            general_error=message,
        )


def _installed_agent(agent_id: str, registry: RegistrySnapshot | None) -> DiscoveredAgent:
    discovered = discovered_by_id(agent_id, registry)
    if discovered is None:
        message = f"Agent {agent_id!r} is outside Relay's Phase 1 compatibility scope."
        raise AgentLaunchError(message, context={"agent": agent_id})
    if discovered.command is None:
        message = discovered.reason or f"Agent {agent_id!r} is not installed."
        raise AgentLaunchError(
            message,
            context={"agent": agent_id},
            next_action=f"Follow the {discovered.profile.display_name} install guidance.",
        )
    return discovered


def _aggregate_error(reasons: Mapping[str, str]) -> RelayError:
    text = "; ".join(f"{candidate}: {reason}" for candidate, reason in reasons.items())
    message = f"No candidate confirmed the requested exact model. {text}"
    prefixes = {reason.partition(":")[0] for reason in reasons.values()}
    error_type: type[RelayError]
    if prefixes == {AgentLaunchError.error_code}:
        error_type = AgentLaunchError
    elif prefixes == {AgentAuthError.error_code}:
        error_type = AgentAuthError
    elif prefixes == {ModelSelectorError.error_code}:
        error_type = ModelSelectorError
    elif prefixes == {ModelSelectionRejectedError.error_code}:
        error_type = ModelSelectionRejectedError
    elif prefixes == {AgentProtocolError.error_code}:
        error_type = AgentProtocolError
    else:
        error_type = ModelUnavailableError
    return error_type(
        message,
        next_action="Install and authenticate a listed agent that advertises the exact value.",
    )


async def _probe_all(
    requirements: tuple[RouteRequirement, ...],
    cwd: Path,
    registry: RegistrySnapshot | None,
) -> dict[str, ProbeResult]:
    models_by_agent: dict[str, list[str]] = {}
    for requirement in requirements:
        for agent_id in requirement.effective_agent_order:
            values = models_by_agent.setdefault(agent_id, [])
            if requirement.model_value not in values:
                values.append(requirement.model_value)
    results: dict[str, ProbeResult] = {}
    for agent_id, values in models_by_agent.items():
        try:
            installed = _installed_agent(agent_id, registry)
        except RelayError as error:
            results[agent_id] = ProbeResult(
                agent_id,
                failures=dict.fromkeys(values, f"{error.error_code}: {error.message}"),
            )
            continue
        if installed.command is None:
            continue
        driver = _driver(installed.profile, installed.command)
        probes = tuple(ProbeRequirement(value) for value in values)
        results[agent_id] = await _bounded_probe(driver, probes, cwd, agent_id)
    return results


def preflight_routes(
    requirements: Iterable[RouteRequirement],
    cwd: Path,
    *,
    registry: RegistrySnapshot | None = None,
    observation_store: AgentObservationStore | None = None,
) -> tuple[tuple[RouteEntry, ...], tuple[ProbeResult, ...]]:
    """Probe each candidate once, then freeze the first exact-match route per node."""
    requested = tuple(requirements)
    results = asyncio.run(_probe_all(requested, cwd.resolve(), registry))
    if observation_store is not None:
        for result in results.values():
            if result.general_error is None:
                observation_store.replace_model_observations(result.agent_id, result.models)
    entries: list[RouteEntry] = []
    for requirement in requested:
        failures: dict[str, str] = {}
        selected: str | None = None
        for agent_id in requirement.effective_agent_order:
            result = results.get(agent_id)
            if result is not None and requirement.model_value in result.confirmed_values:
                selected = agent_id
                break
            failures[agent_id] = (
                result.failures.get(
                    requirement.model_value, "agent_launch_error: probe unavailable"
                )
                if result is not None
                else "agent_launch_error: probe unavailable"
            )
        if selected is None:
            raise _aggregate_error(failures)
        entries.append(
            RouteEntry(
                requirement.scope_path,
                requirement.model_value,
                requirement.effective_agent_order,
                selected,
            )
        )
    return tuple(entries), tuple(results.values())


def probe_installed_agents(
    cwd: Path,
    *,
    registry: RegistrySnapshot | None = None,
    observation_store: AgentObservationStore | None = None,
) -> tuple[tuple[DiscoveredAgent, ProbeResult | None], ...]:
    """Actively inventory models without installing agents or authorizing a launch."""

    async def probe() -> tuple[tuple[DiscoveredAgent, ProbeResult | None], ...]:
        rows: list[tuple[DiscoveredAgent, ProbeResult | None]] = []
        for discovered in discover_agents(registry):
            result = None
            if discovered.command is not None:
                driver = _driver(discovered.profile, discovered.command)
                result = await _bounded_probe(
                    driver, (), cwd.resolve(), discovered.profile.agent_id
                )
            rows.append((discovered, result))
        return tuple(rows)

    rows = asyncio.run(probe())
    if observation_store is not None:
        for _discovered, result in rows:
            if result is not None and result.general_error is None:
                observation_store.replace_model_observations(result.agent_id, result.models)
    return rows


def _stop_reason(result: AgentResult) -> AttemptStopReason:
    return {
        "completed": AttemptStopReason.COMPLETED,
        "end_turn": AttemptStopReason.COMPLETED,
        "canceled": AttemptStopReason.CANCELED,
        "timeout": AttemptStopReason.TIMEOUT,
        "interrupted": AttemptStopReason.INTERRUPTED,
        "soft_denied": AttemptStopReason.SOFT_DENIED,
        "max_tokens": AttemptStopReason.FAILED,
        "max_turn_requests": AttemptStopReason.FAILED,
        "refusal": AttemptStopReason.FAILED,
    }.get(result.stop_reason, AttemptStopReason.FAILED)


class RoutedAgentNodeDriver:
    """Consume only the immutable selected route captured before run creation."""

    def __init__(self, registry: RegistrySnapshot | None = None) -> None:
        self.registry: RegistrySnapshot | None = registry

    def execute(self, context: AttemptContext, node: AgentNode) -> ExecutionOutcome:
        route = context.attempt.route
        agent_id = route.get("selected_agent")
        model_value = route.get("model_value")
        if not isinstance(agent_id, str) or not isinstance(model_value, str):
            message = "The immutable node route has no preflight-proven agent and model."
            raise AgentLaunchError(message, context={"node": context.attempt.scope_path})
        installed = _installed_agent(agent_id, self.registry)
        if installed.command is None:
            message = f"The selected agent {agent_id!r} has no executable command."
            raise AgentLaunchError(message, context={"node": context.attempt.scope_path})
        permission_profile = node.permission_profile or (
            "respect_settings" if installed.profile.driver == "antigravity" else "interactive"
        )
        if permission_profile not in installed.profile.permission_profiles:
            message = (
                f"Permission profile {permission_profile!r} is not supported by agent {agent_id!r}."
            )
            raise AgentLaunchError(message, context={"node": context.attempt.scope_path})
        execution = AgentExecutionContext(
            context,
            node,
            agent_id,
            model_value,
            permission_profile,
            installed.command,
        )
        return asyncio.run(self._execute(_driver(installed.profile, installed.command), execution))

    async def _execute(
        self,
        driver: AgentDriver,
        context: AgentExecutionContext,
    ) -> ExecutionOutcome:
        async for event in driver.start_attempt(context):
            for chunk in bounded_agent_events(event):
                await asyncio.to_thread(
                    context.attempt.runtime.append_attempt_event,
                    context.attempt.attempt.attempt_id,
                    chunk.event_type,
                    EventSource.AGENT,
                    chunk.payload,
                    sensitivity=chunk.sensitivity,
                )
        result = await driver.finalize()
        return ExecutionOutcome(
            OutcomeKind.SUCCEEDED if result.succeeded else OutcomeKind.FAILED,
            stop_reason=_stop_reason(result),
            exit_code=result.exit_code,
            error_code=result.error_code,
        )


__all__ = [
    "AgentDriver",
    "AgentObservationStore",
    "RoutedAgentNodeDriver",
    "preflight_routes",
    "probe_installed_agents",
]
