"""Provider-neutral agent port, route preflight, and node-driver bridge."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable, Mapping
from contextlib import suppress
from pathlib import Path
import time
from typing import Protocol

from relay.constants import (
    AGENT_PROBE_TIMEOUT_SECONDS,
    AGENT_STOP_TIMEOUT_SECONDS,
    ATTEMPT_HEARTBEAT_INTERVAL_SECONDS,
    CANCELLATION_GRACE_SECONDS,
    CONTROL_POLL_INTERVAL_SECONDS,
)
from relay.errors import (
    AgentAuthError,
    AgentConfigurationError,
    AgentLaunchError,
    AgentProtocolError,
    ModelSelectionRejectedError,
    ModelSelectorError,
    ModelUnavailableError,
    PersistenceError,
    RelayError,
)
from relay.execution.control import cancel_stop_reason
from relay.execution.runner import AttemptContext, ExecutionOutcome, OutcomeKind
from relay.execution.state import AttemptStopReason, ControlKind, EventSource
from relay.workflows.routing import RouteEntry, RouteRequirement
from relay.workflows.schema import AgentNode

from .acp_driver import AcpDriver
from .antigravity_driver import AntigravityDriver
from .discovery import discover_agents, discovered_by_id
from .events import AgentEvent, bounded_agent_events
from .models import (
    AgentCommand,
    AgentConfiguration,
    AgentExecutionContext,
    AgentProfile,
    AgentResult,
    DiscoveredAgent,
    ModelObservation,
    ProbeFailure,
    ProbeRequirement,
    ProbeResult,
    RegistrySnapshot,
)
from .profiles import PROFILES


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
    except asyncio.TimeoutError:
        message = (
            f"Agent {agent_id!r} did not complete its probe in "
            f"{AGENT_PROBE_TIMEOUT_SECONDS:g} seconds."
        )
        return ProbeResult(
            agent_id,
            failures={
                item.model_value: ProbeFailure(AgentProtocolError.error_code, message)
                for item in requirements
            },
            general_error=ProbeFailure(AgentProtocolError.error_code, message),
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


def _aggregate_error(reasons: Mapping[str, ProbeFailure]) -> RelayError:
    """Report per-candidate proof failures with their shared Relay error code."""
    text = "; ".join(f"{candidate}: {reason}" for candidate, reason in reasons.items())
    message = f"No candidate confirmed the requested exact model and configuration. {text}"
    prefixes = {reason.code for reason in reasons.values()}
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
    elif prefixes == {AgentConfigurationError.error_code}:
        error_type = AgentConfigurationError
    else:
        error_type = ModelUnavailableError
    return error_type(
        message,
        next_action=(
            "Choose an installed, authenticated agent that supports "
            "the requested model and overrides."
        ),
    )


async def _probe_all(
    requirements: tuple[RouteRequirement, ...],
    cwd: Path,
    registry: RegistrySnapshot | None,
) -> dict[str, ProbeResult]:
    requirements_by_agent = {}
    seen_by_agent = {}
    for requirement in requirements:
        for agent_id in requirement.effective_agent_order:
            profile = PROFILES.get(agent_id)
            if (
                profile is not None
                and requirement.permission_profile is not None
                and requirement.permission_profile not in profile.permission_profiles
            ):
                continue
            values = requirements_by_agent.setdefault(agent_id, [])
            seen = seen_by_agent.setdefault(agent_id, set())
            probe = _candidate_requirement(requirement, agent_id)
            if probe not in seen:
                values.append(probe)
                seen.add(probe)
    results = {}
    for agent_id, values in requirements_by_agent.items():
        try:
            installed = _installed_agent(agent_id, registry)
        except RelayError as error:
            results[agent_id] = ProbeResult(
                agent_id,
                failures=dict.fromkeys(
                    (item.model_value for item in values), ProbeFailure.from_error(error)
                ),
                requirement_failures=dict.fromkeys(values, ProbeFailure.from_error(error)),
            )
            continue
        if installed.command is None:
            continue
        driver = _driver(installed.profile, installed.command)
        results[agent_id] = await _bounded_probe(driver, tuple(values), cwd, agent_id)
    return results


def _candidate_requirement(requirement: RouteRequirement, agent_id: str) -> ProbeRequirement:
    options = requirement.agent_options.get(agent_id)
    return ProbeRequirement(
        requirement.model_value,
        options.effort if options is not None else None,
        options.permission_mode if options is not None else None,
    )


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
    entries = []
    all_failures = {}
    for requirement in requested:
        failures = {}
        selected = None
        for agent_id in requirement.effective_agent_order:
            profile = PROFILES.get(agent_id)
            if (
                profile is not None
                and requirement.permission_profile is not None
                and requirement.permission_profile not in profile.permission_profiles
            ):
                failures[agent_id] = ProbeFailure(
                    AgentLaunchError.error_code,
                    f"Permission profile {requirement.permission_profile!r} is not "
                    f"supported by agent {agent_id!r}.",
                )
                continue
            result = results.get(agent_id)
            probe = _candidate_requirement(requirement, agent_id)
            if result is not None and probe in result.confirmed_requirements:
                selected = agent_id
                break
            failures[agent_id] = (
                result.requirement_failures.get(
                    probe,
                    result.failures.get(
                        requirement.model_value,
                        result.general_error
                        or ProbeFailure(AgentLaunchError.error_code, "probe unavailable"),
                    ),
                )
                if result is not None
                else ProbeFailure(AgentLaunchError.error_code, "probe unavailable")
            )
        if selected is None:
            all_failures.update(
                {
                    f"{requirement.scope_path}/{agent_id}": reason
                    for agent_id, reason in failures.items()
                }
            )
            continue
        entries.append(
            RouteEntry(
                requirement.scope_path,
                requirement.model_value,
                requirement.effective_agent_order,
                selected,
                effort=_candidate_requirement(requirement, selected).effort,
                permission_mode=_candidate_requirement(requirement, selected).permission_mode,
            )
        )
    if all_failures:
        raise _aggregate_error(all_failures)
    return tuple(entries), tuple(results.values())


def probe_agent_models(
    agent_id: str,
    cwd: Path,
    *,
    observation_store: AgentObservationStore | None = None,
) -> tuple[ModelObservation, ...]:
    """Read one installed tool's model menu without starting an attempt."""
    installed = _installed_agent(agent_id, None)
    if installed.command is None:
        message = f"Agent {agent_id!r} is not installed."
        raise AgentLaunchError(message)
    result = asyncio.run(
        _bounded_probe(_driver(installed.profile, installed.command), (), cwd.resolve(), agent_id)
    )
    if result.general_error is not None:
        raise _aggregate_error({agent_id: result.general_error})
    if observation_store is not None:
        observation_store.replace_model_observations(agent_id, result.models)
    return result.models


def probe_agent_configuration(
    agent_id: str,
    model_value: str,
    cwd: Path,
    *,
    observation_store: AgentObservationStore | None = None,
) -> AgentConfiguration:
    """Read one installed tool's current choices after proving the selected model."""
    installed = _installed_agent(agent_id, None)
    if installed.command is None:
        message = f"Agent {agent_id!r} is not installed."
        raise AgentLaunchError(message)
    requirement = ProbeRequirement(model_value)
    result = asyncio.run(
        _bounded_probe(
            _driver(installed.profile, installed.command),
            (requirement,),
            cwd.resolve(),
            agent_id,
        )
    )
    configuration = result.configurations.get(model_value)
    if requirement not in result.confirmed_requirements or configuration is None:
        failure = (
            result.failures.get(model_value)
            or result.general_error
            or ProbeFailure(
                AgentConfigurationError.error_code, "The tool did not expose its configuration."
            )
        )
        raise _aggregate_error({agent_id: failure})
    if observation_store is not None:
        observation_store.replace_model_observations(agent_id, result.models)
    return configuration


def probe_installed_agents(
    cwd: Path,
    *,
    registry: RegistrySnapshot | None = None,
    observation_store: AgentObservationStore | None = None,
) -> tuple[tuple[DiscoveredAgent, ProbeResult | None], ...]:
    """Actively inventory models without installing agents or authorizing a launch."""

    async def probe() -> tuple[tuple[DiscoveredAgent, ProbeResult | None], ...]:
        rows = []
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

    registry: RegistrySnapshot | None

    def __init__(self, registry: RegistrySnapshot | None = None) -> None:
        self.registry = registry

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
        effort = route.get("effort")
        permission_mode = route.get("permission_mode")
        if any(
            value is not None and not isinstance(value, str) for value in (effort, permission_mode)
        ):
            message = "The immutable node route has malformed agent overrides."
            raise AgentLaunchError(message, context={"node": context.attempt.scope_path})
        execution = AgentExecutionContext(
            context,
            node,
            agent_id,
            model_value,
            permission_profile,
            installed.command,
            effort=effort if isinstance(effort, str) else None,
            permission_mode=permission_mode if isinstance(permission_mode, str) else None,
        )
        return asyncio.run(
            self._supervise(_driver(installed.profile, installed.command), execution)
        )

    @staticmethod
    async def _stop_task(
        driver: AgentDriver,
        task: asyncio.Task[ExecutionOutcome],
    ) -> None:
        """Bound provider cancellation before closing its event consumer."""
        with suppress(Exception):
            await asyncio.wait_for(
                driver.cancel(),
                timeout=AGENT_STOP_TIMEOUT_SECONDS,
            )
        task.cancel()
        done, _pending = await asyncio.wait((task,), timeout=CANCELLATION_GRACE_SECONDS)
        if task in done:
            with suppress(asyncio.CancelledError, Exception):
                task.result()

    async def _supervise(
        self,
        driver: AgentDriver,
        context: AgentExecutionContext,
    ) -> ExecutionOutcome:
        """Own timeout, heartbeat, and cancellation across the full session."""
        task = asyncio.create_task(self._execute(driver, context))
        heartbeat_due = time.monotonic() + ATTEMPT_HEARTBEAT_INTERVAL_SECONDS
        stopped = False
        try:
            while not task.done():
                remaining = context.attempt.remaining_seconds()
                if remaining is not None and remaining <= 0:
                    await self._stop_task(driver, task)
                    stopped = True
                    return ExecutionOutcome(
                        OutcomeKind.FAILED,
                        stop_reason=AttemptStopReason.TIMEOUT,
                        error_code="node_timeout",
                    )
                wait_for = CONTROL_POLL_INTERVAL_SECONDS
                if remaining is not None:
                    wait_for = min(wait_for, remaining)
                await asyncio.wait((task,), timeout=wait_for)
                if task.done():
                    break
                control = await asyncio.to_thread(
                    context.attempt.runtime.claim_next_control,
                    context.attempt.attempt.attempt_id,
                    context.attempt.attempt.worker_id,
                    (ControlKind.CANCEL.value,),
                )
                if control is not None:
                    applied = await asyncio.to_thread(
                        context.attempt.runtime.apply_control,
                        control.request_id,
                        context.attempt.attempt.worker_id,
                    )
                    if applied:
                        reason = cancel_stop_reason(control)
                        await self._stop_task(driver, task)
                        stopped = True
                        return ExecutionOutcome(
                            OutcomeKind.FAILED,
                            stop_reason=reason,
                            error_code=reason.value,
                        )
                now = time.monotonic()
                if now >= heartbeat_due:
                    alive = await asyncio.to_thread(context.attempt.heartbeat)
                    if not alive:
                        await self._stop_task(driver, task)
                        stopped = True
                        message = "The agent attempt lost its durable worker ownership."
                        raise PersistenceError(
                            message,
                            context={"node": context.attempt.attempt.scope_path},
                        )
                    heartbeat_due = now + ATTEMPT_HEARTBEAT_INTERVAL_SECONDS
            return await task
        finally:
            if not stopped and not task.done():
                await self._stop_task(driver, task)

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
            error_message=(
                "The provider's usage limit stopped this step."
                if result.usage_limit is not None
                else None
            ),
            usage_limit=result.usage_limit,
        )


__all__ = [
    "AgentDriver",
    "AgentObservationStore",
    "RoutedAgentNodeDriver",
    "preflight_routes",
    "probe_agent_configuration",
    "probe_agent_models",
    "probe_installed_agents",
]
