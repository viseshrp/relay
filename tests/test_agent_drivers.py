"""Real provider adapters communicating with offline executable boundaries."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from django.db import connections
import pytest

from relay.agents import antigravity_driver
from relay.agents.acp_driver import AcpDriver
from relay.agents.antigravity_driver import AntigravityDriver
from relay.agents.discovery import discover_agents, discovered_by_id
from relay.agents.driver import AgentDriver, RoutedAgentNodeDriver, preflight_routes
from relay.agents.events import AgentEvent
from relay.agents.models import AgentCommand, AgentExecutionContext, AgentResult, ProbeRequirement
from relay.agents.profiles import PROFILES
from relay.constants import ANTIGRAVITY_PROMPT_MAX_BYTES
from relay.errors import (
    AgentAuthError,
    AgentLaunchError,
    AgentProtocolError,
    ModelSelectionRejectedError,
    ModelSelectorError,
    ModelUnavailableError,
    NodeExecutionError,
    RelayError,
)
from relay.execution.control import ControlResult
from relay.execution.nodes import node_executors
from relay.web.models import NodeAttempt, RunEvent
from relay.web.repositories import DjangoExecutionStore
from relay.workflows.routing import RouteRequirement
from tests.support import FakeAgents, InlineEngine, RelayProject


def execute(
    driver: AgentDriver, context: AgentExecutionContext
) -> tuple[list[AgentEvent], AgentResult]:
    async def collect() -> tuple[list[AgentEvent], AgentResult]:
        try:
            events = [event async for event in driver.start_attempt(context)]
            return events, await driver.finalize()
        finally:
            await asyncio.to_thread(connections.close_all)

    return asyncio.run(collect())


def test_acp_probes_confirm_exact_models_through_the_wire(
    fake_agents: FakeAgents, tmp_path: Path
) -> None:
    executable = fake_agents.install("codex")
    driver = AcpDriver(PROFILES["codex"], AgentCommand(str(executable)))
    result = asyncio.run(driver.probe_models((ProbeRequirement("m2"),), tmp_path))
    assert result.general_error is None
    assert result.confirmed_values == frozenset({"m2"})
    assert {model.model_value for model in result.models} == {"m1", "m2"}


def test_acp_attempts_retain_the_owner_visible_reply(agent_context: AgentExecutionContext) -> None:
    driver = AcpDriver(PROFILES["codex"], agent_context.command)
    events, result = execute(driver, agent_context)
    assert result.succeeded
    assert any(
        event.event_type == "agent.message" and event.payload["text"] == "ready" for event in events
    )


def test_single_profile_discovery_does_not_probe_unrequested_agents(
    fake_agents: FakeAgents,
) -> None:
    fake_agents.install("codex")
    fake_agents.install("claude")
    discovered = discovered_by_id("codex")
    assert discovered is not None and discovered.installed
    assert discovered.detected_version == "fake-agent 1.2.3"
    assert fake_agents.messages() == [{"version_probe": True}]


def test_discovery_ignores_unknown_profile_ids(fake_agents: FakeAgents) -> None:
    assert discovered_by_id("unsupported") is None
    assert fake_agents.messages() == []


def test_inventory_reports_missing_profiles_without_installing_them(
    fake_agents: FakeAgents,
) -> None:
    fake_agents.install("codex")
    installed = {row.profile.agent_id for row in discover_agents() if row.installed}
    assert installed == {"codex"}


@pytest.mark.parametrize("mode", ["grouped", "stderr"])
def test_acp_probes_support_grouped_models_and_drain_heavy_stderr(
    fake_agents: FakeAgents, tmp_path: Path, mode: str
) -> None:
    driver = AcpDriver(
        PROFILES["codex"], AgentCommand(str(fake_agents.install("codex", mode=mode)))
    )
    result = asyncio.run(driver.probe_models((ProbeRequirement("m2"),), tmp_path))
    assert result.confirmed_values == frozenset({"m2"})
    assert result.general_error is None


@pytest.mark.parametrize(
    ("mode", "code"), [("auth", "agent_auth_error"), ("no-selector", "model_selector_error")]
)
def test_acp_probe_failures_keep_the_structured_error_code(
    fake_agents: FakeAgents, tmp_path: Path, mode: str, code: str
) -> None:
    driver = AcpDriver(
        PROFILES["codex"], AgentCommand(str(fake_agents.install("codex", mode=mode)))
    )
    result = asyncio.run(driver.probe_models((ProbeRequirement("m1"),), tmp_path))
    assert result.general_error is not None and result.general_error.code == code
    assert result.failures["m1"].code == code
    assert all(message.get("method") != "authenticate" for message in fake_agents.messages())


@pytest.mark.parametrize(
    ("mode", "model", "code"),
    [
        ("success", "missing", "model_unavailable_error"),
        ("reject", "m1", "model_selection_rejected_error"),
        ("wrong-selection", "m1", "model_selection_rejected_error"),
    ],
)
def test_acp_exact_model_proof_rejects_missing_or_unconfirmed_values(
    fake_agents: FakeAgents, tmp_path: Path, mode: str, model: str, code: str
) -> None:
    driver = AcpDriver(
        PROFILES["codex"], AgentCommand(str(fake_agents.install("codex", mode=mode)))
    )
    result = asyncio.run(driver.probe_models((ProbeRequirement(model),), tmp_path))
    assert model not in result.confirmed_values
    assert result.failures[model].code == code


@pytest.mark.parametrize("mode", ["close-error", "delete-advertised"])
def test_acp_probe_cleanup_warnings_do_not_discard_model_proof(
    fake_agents: FakeAgents, tmp_path: Path, mode: str
) -> None:
    driver = AcpDriver(
        PROFILES["codex"], AgentCommand(str(fake_agents.install("codex", mode=mode)))
    )
    result = asyncio.run(driver.probe_models((ProbeRequirement("m1"),), tmp_path))
    assert result.confirmed_values == frozenset({"m1"})
    assert result.cleanup_warning is not None


def test_acp_attempts_preserve_all_startup_stderr(
    agent_context: AgentExecutionContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_ACP_MODE", "stderr")
    events, result = execute(AcpDriver(PROFILES["codex"], agent_context.command), agent_context)
    assert result.succeeded
    assert (
        "".join(event.payload["text"] for event in events if event.event_type == "agent.stderr")
        == "e" * 1_000_000
    )


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("drift", ModelSelectionRejectedError),
        ("reject", ModelSelectionRejectedError),
        ("wrong-selection", ModelSelectionRejectedError),
        ("no-selector", ModelSelectorError),
    ],
)
def test_acp_attempts_reject_model_drift_or_lost_model_proof(
    agent_context: AgentExecutionContext,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    expected: type[RelayError],
) -> None:
    monkeypatch.setenv("FAKE_ACP_MODE", mode)
    driver = AcpDriver(PROFILES["codex"], agent_context.command)
    with pytest.raises(expected):
        execute(driver, agent_context)
    assert asyncio.run(driver.finalize()).error_code == expected.error_code


def test_acp_attempts_can_use_the_advertised_agent_authentication_method(
    agent_context: AgentExecutionContext, fake_agents: FakeAgents, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_ACP_MODE", "auth")
    _events, result = execute(AcpDriver(PROFILES["codex"], agent_context.command), agent_context)
    assert result.succeeded
    assert any(message.get("method") == "authenticate" for message in fake_agents.messages())


def test_acp_refusal_is_a_failed_provider_result(
    agent_context: AgentExecutionContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_ACP_MODE", "refusal")
    _events, result = execute(AcpDriver(PROFILES["codex"], agent_context.command), agent_context)
    assert not result.succeeded
    assert (result.stop_reason, result.error_code) == ("refusal", "agent_protocol_error")


def test_acp_owner_cancel_stops_the_live_provider_process(
    agent_context: AgentExecutionContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_ACP_MODE", "hold")
    driver = AcpDriver(PROFILES["codex"], agent_context.command)

    async def cancel_on_ready() -> AgentResult:
        try:
            async for event in driver.start_attempt(agent_context):
                if event.event_type == "agent.message":
                    accepted = await asyncio.to_thread(
                        DjangoExecutionStore().request_run_cancellation,
                        agent_context.attempt.attempt.run_id,
                        "cancel-provider",
                    )
                    assert accepted is ControlResult.ACCEPTED
            return await driver.finalize()
        finally:
            await asyncio.to_thread(connections.close_all)

    result = asyncio.run(cancel_on_ready())
    assert (result.succeeded, result.stop_reason, result.error_code) == (
        False,
        "canceled",
        "canceled",
    )
    assert driver.process is not None and driver.process.returncode is not None
    assert NodeAttempt.objects.get(pk=agent_context.attempt.attempt.attempt_id).process_pid is None


@pytest.mark.parametrize("agent_id", ["codex", "antigravity"])
def test_finalizing_without_a_terminal_result_is_a_protocol_error(agent_id: str) -> None:
    profile = PROFILES[agent_id]
    command = AgentCommand("unused")
    driver = (
        AcpDriver(profile, command) if agent_id == "codex" else AntigravityDriver(profile, command)
    )
    with pytest.raises(AgentProtocolError):
        asyncio.run(driver.finalize())


def test_antigravity_model_inventory_proves_exact_membership(
    fake_agents: FakeAgents, tmp_path: Path
) -> None:
    driver = AntigravityDriver(
        PROFILES["antigravity"], AgentCommand(str(fake_agents.install("antigravity")))
    )
    result = asyncio.run(
        driver.probe_models((ProbeRequirement("m1"), ProbeRequirement("missing")), tmp_path)
    )
    assert result.confirmed_values == frozenset({"m1"})
    assert result.failures["missing"].code == "model_unavailable_error"


@pytest.mark.parametrize(
    ("mode", "code"),
    [("models-empty", "model_unavailable_error"), ("models-failed", "agent_protocol_error")],
)
def test_antigravity_model_discovery_failures_never_prove_an_exact_model(
    fake_agents: FakeAgents, tmp_path: Path, mode: str, code: str
) -> None:
    driver = AntigravityDriver(
        PROFILES["antigravity"], AgentCommand(str(fake_agents.install("antigravity", mode=mode)))
    )
    result = asyncio.run(driver.probe_models((ProbeRequirement("m1"),), tmp_path))
    assert not result.confirmed_values
    assert result.failures["m1"].code == code


@pytest.mark.parametrize("agent_context", ["antigravity"], indirect=True)
def test_antigravity_attempts_use_the_documented_headless_arguments(
    agent_context: AgentExecutionContext, fake_agents: FakeAgents
) -> None:
    context = replace(agent_context, permission_profile="auto_approve")
    events, result = execute(AntigravityDriver(PROFILES["antigravity"], context.command), context)
    assert result.succeeded, [
        event.payload for event in events if event.event_type == "agent.stderr"
    ]
    assert any(
        event.event_type == "agent.message" and event.payload["text"] == "Ready: Yes"
        for event in events
    )
    arguments = next(message["argv"] for message in fake_agents.messages() if "argv" in message)
    assert arguments[arguments.index("--model") + 1] == "m1"
    assert arguments[arguments.index("--output-format") + 1] == "stream-json"
    assert arguments[arguments.index("--print-timeout") + 1] == "5m"
    assert "--dangerously-skip-permissions" in arguments
    assert "Relay inputs" in arguments[arguments.index("-p") + 1]


@pytest.mark.parametrize("agent_context", ["antigravity"], indirect=True)
@pytest.mark.parametrize(
    ("mode", "reason", "code"),
    [
        ("timeout", "timeout", "node_timeout"),
        ("error-text", "failed", "agent_protocol_error"),
        ("boolean-duration", "failed", "agent_protocol_error"),
        ("canceled", "canceled", "canceled"),
        ("interrupted", "interrupted", "agent_protocol_error"),
        ("missing-result", "failed", "agent_protocol_error"),
    ],
)
def test_antigravity_terminal_failures_use_structured_status_and_duration(
    agent_context: AgentExecutionContext,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    reason: str,
    code: str,
) -> None:
    monkeypatch.setenv("FAKE_AGY_MODE", mode)
    _events, result = execute(
        AntigravityDriver(PROFILES["antigravity"], agent_context.command), agent_context
    )
    assert not result.succeeded
    assert (result.stop_reason, result.error_code) == (reason, code)


@pytest.mark.parametrize("agent_context", ["antigravity"], indirect=True)
@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("drift", ModelSelectionRejectedError),
        ("malformed", AgentProtocolError),
        ("non-object", AgentProtocolError),
        ("oversized", AgentProtocolError),
    ],
)
def test_antigravity_invalid_streams_raise_relay_errors(
    agent_context: AgentExecutionContext,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    expected: type[RelayError],
) -> None:
    monkeypatch.setenv("FAKE_AGY_MODE", mode)
    driver = AntigravityDriver(PROFILES["antigravity"], agent_context.command)
    with pytest.raises(expected):
        execute(driver, agent_context)
    assert asyncio.run(driver.finalize()).error_code == expected.error_code


@pytest.mark.parametrize("agent_context", ["antigravity"], indirect=True)
@pytest.mark.parametrize(
    ("mode", "denied"),
    [
        ("stderr-denied", True),
        ("stdout-denied", False),
        ("stderr-outside", False),
        ("stderr-fragments", False),
    ],
)
def test_antigravity_soft_denies_require_a_complete_in_worktree_stderr_notice(
    agent_context: AgentExecutionContext, monkeypatch: pytest.MonkeyPatch, mode: str, denied: bool
) -> None:
    monkeypatch.setenv("FAKE_AGY_MODE", mode)
    _events, result = execute(
        AntigravityDriver(PROFILES["antigravity"], agent_context.command), agent_context
    )
    assert result.succeeded is not denied
    assert result.denied_write_targets == (("report.txt",) if denied else ())
    assert result.error_code == ("antigravity_soft_denied" if denied else None)


@pytest.mark.parametrize("agent_context", ["antigravity"], indirect=True)
def test_oversized_antigravity_prompts_fail_before_starting_a_process(
    agent_context: AgentExecutionContext,
) -> None:
    claim = replace(
        agent_context.attempt.attempt, prompt_contents=("é" * ANTIGRAVITY_PROMPT_MAX_BYTES,)
    )
    context = replace(agent_context, attempt=replace(agent_context.attempt, attempt=claim))
    driver = AntigravityDriver(PROFILES["antigravity"], context.command)
    with pytest.raises(NodeExecutionError):
        execute(driver, context)
    assert driver.process is None


@pytest.mark.parametrize("agent_context", ["antigravity"], indirect=True)
def test_windows_batch_argument_limits_are_enforced_before_spawning(
    agent_context: AgentExecutionContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    claim = replace(agent_context.attempt.attempt, prompt_contents=("😀" * 5_000,))
    context = replace(
        agent_context,
        attempt=replace(agent_context.attempt, attempt=claim),
        command=AgentCommand("fake.cmd"),
    )
    monkeypatch.setattr(antigravity_driver, "os", SimpleNamespace(name="nt"))
    driver = AntigravityDriver(PROFILES["antigravity"], context.command)
    with pytest.raises(NodeExecutionError):
        execute(driver, context)
    assert driver.process is None


def test_preflight_chooses_the_first_installed_exact_match(
    fake_agents: FakeAgents, tmp_path: Path
) -> None:
    fake_agents.install("claude")
    entries, probes = preflight_routes(
        (RouteRequirement("root.work", "m1", ("codex", "claude")),), tmp_path
    )
    assert entries[0].selected_agent == "claude"
    assert {result.agent_id for result in probes} == {"codex", "claude"}


def test_an_unsupported_permission_profile_is_rejected_before_probing(
    fake_agents: FakeAgents, tmp_path: Path
) -> None:
    fake_agents.install("codex")
    requirement = RouteRequirement("root.work", "m1", ("codex",), permission_profile="auto_approve")
    with pytest.raises(AgentLaunchError):
        preflight_routes((requirement,), tmp_path)
    assert fake_agents.messages() == []


@pytest.mark.parametrize(
    ("mode", "model", "expected"),
    [
        ("auth", "m1", AgentAuthError),
        ("no-selector", "m1", ModelSelectorError),
        ("reject", "m1", ModelSelectionRejectedError),
        ("success", "absent", ModelUnavailableError),
    ],
)
def test_preflight_aggregates_machine_readable_failures(
    fake_agents: FakeAgents, tmp_path: Path, mode: str, model: str, expected: type[RelayError]
) -> None:
    fake_agents.install("codex", mode=mode)
    with pytest.raises(expected):
        preflight_routes((RouteRequirement("root.work", model, ("codex",)),), tmp_path)


@pytest.mark.usefixtures("registry_network", "database_threads")
def test_routed_execution_persists_visible_provider_events(
    project: RelayProject, engine: InlineEngine, fake_agents: FakeAgents
) -> None:
    fake_agents.install("codex")
    project.write_workflow(
        "routed",
        "version: 1\nname: Routed\nmodel: m1\nagents: [codex]\nnodes:\n"
        "  work: {type: agent, writes: true, allow_no_commit: true}\n",
    )
    engine.executors = node_executors(agent_driver=RoutedAgentNodeDriver())
    run_id = engine.launch(project, "routed")
    engine.drain(run_id)
    messages = RunEvent.objects.filter(run_id=run_id, type="agent.message")
    assert [message.payload["text"] for message in messages] == ["ready"]
    assert NodeAttempt.objects.get(node_run__run_id=run_id).agent_id == "codex"


@pytest.mark.usefixtures("registry_network")
def test_the_agent_node_port_validates_its_writers_output_handoff(
    project: RelayProject, engine: InlineEngine, fake_agents: FakeAgents
) -> None:
    from relay.web.models import NodeRun, Run

    fake_agents.install("codex")
    project.write_workflow(
        "handoff",
        "version: 1\nname: Handoff\nmodel: m1\nagents: [codex]\nnodes:\n"
        "  work:\n    type: agent\n    writes: true\n    outputs:\n"
        "      ready: {label: {artifact: agent-output.md, label: Ready}}\n",
    )
    run_id = engine.launch(project, "handoff")
    starting_head = Run.objects.get(pk=run_id).recorded_head

    engine.drain(run_id)

    assert NodeRun.objects.get(run_id=run_id).outputs == {"ready": "Yes"}
    assert Run.objects.get(pk=run_id).recorded_head != starting_head
