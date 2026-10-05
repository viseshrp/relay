"""Exercise configuration discovery, default preservation, preflight, and real workers."""

from __future__ import annotations

import asyncio
from dataclasses import replace
import json
from pathlib import Path

from django.test import Client
from pydantic import ValidationError
import pytest

from relay.agents.acp_driver import AcpDriver
from relay.agents.antigravity_driver import AntigravityDriver
from relay.agents.driver import RoutedAgentNodeDriver, preflight_routes, probe_agent_configuration
from relay.agents.models import AgentCommand, AgentExecutionContext, ProbeRequirement
from relay.agents.profiles import PROFILES
from relay.errors import AgentConfigurationError, ModelSelectionRejectedError
from relay.execution.nodes import node_executors
from relay.web.models import NodeAttempt, Run, RunSnapshot
from relay.workflows.routing import RouteRequirement, serialize_route_table
from relay.workflows.schema import AgentNode, AgentOptions
from tests.support import FakeAgents, InlineEngine, RelayProject, run_status
from tests.test_agent_drivers import execute


def configured_driver(fake_agents: FakeAgents, mode: str = "configuration") -> AcpDriver:
    executable = fake_agents.install("codex", mode=mode)
    return AcpDriver(PROFILES["codex"], AgentCommand(str(executable)))


def assignments(fake_agents: FakeAgents) -> list[tuple[str, str]]:
    return [
        (item["params"]["configId"], item["params"]["value"])
        for item in fake_agents.messages()
        if item.get("method") == "session/set_config_option"
    ]


def test_workflow_options_preserve_absent_defaults_and_exact_values() -> None:
    node = AgentNode.model_validate({"type": "agent"})
    assert node.agent_options == {}
    node = AgentNode.model_validate(
        {
            "type": "agent",
            "agent_options": {"codex": {"effort": "high", "permission_mode": "workspace-write"}},
        }
    )
    assert node.agent_options["codex"].effort == "high"
    assert node.agent_options["codex"].permission_mode == "workspace-write"


@pytest.mark.parametrize(
    "invalid", [{"effort": ""}, {"permission_mode": ""}, {"effort": 1}, {"mode": "auto"}]
)
def test_workflow_options_reject_empty_nonstring_and_unknown_fields(
    invalid: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        AgentOptions.model_validate(invalid)


@pytest.mark.parametrize(
    "mode", ["configuration", "configuration-grouped", "configuration-no-categories"]
)
def test_configuration_choices_come_from_the_selected_models_response(
    fake_agents: FakeAgents,
    tmp_path: Path,
    mode: str,
) -> None:
    result = asyncio.run(
        configured_driver(fake_agents, mode).probe_models((ProbeRequirement("m2"),), tmp_path)
    )
    configuration = result.configurations["m2"]
    assert configuration.effort is not None
    assert [(item.value, item.name) for item in configuration.effort.choices] == [
        ("low", "Low"),
        ("medium", "Medium"),
    ]
    assert configuration.effort.choices[0].description == "Use low effort."
    assert configuration.permission_mode is not None
    assert [item.value for item in configuration.permission_mode.choices] == ["ask", "auto"]
    # Reading the provider default never sets it as an override.
    assert assignments(fake_agents) == [("model", "m2")]


def test_unadvertised_selectors_allow_defaults_and_reject_overrides(
    fake_agents: FakeAgents,
    tmp_path: Path,
) -> None:
    driver = configured_driver(fake_agents, "success")
    default = ProbeRequirement("m1")
    explicit = ProbeRequirement("m1", effort="high")
    result = asyncio.run(driver.probe_models((default, explicit), tmp_path))
    assert result.configurations["m1"].effort is None
    assert result.configurations["m1"].permission_mode is None
    assert default in result.confirmed_requirements
    assert explicit not in result.confirmed_requirements
    assert result.requirement_failures[explicit].code == "agent_configuration_error"


@pytest.mark.parametrize(
    "requirement",
    [ProbeRequirement("m2", effort="high"), ProbeRequirement("m1", permission_mode="unknown")],
)
def test_unsupported_choices_fail_without_sending_them(
    fake_agents: FakeAgents,
    tmp_path: Path,
    requirement: ProbeRequirement,
) -> None:
    result = asyncio.run(configured_driver(fake_agents).probe_models((requirement,), tmp_path))
    assert requirement not in result.confirmed_requirements
    assert result.requirement_failures[requirement].code == "agent_configuration_error"
    assert assignments(fake_agents) == [("model", requirement.model_value)]


@pytest.mark.parametrize(
    "mode",
    [
        "configuration-reject",
        "configuration-wrong",
        "configuration-model-drift",
        "configuration-drop-mode",
    ],
)
def test_overrides_require_complete_confirmed_configuration(
    fake_agents: FakeAgents,
    tmp_path: Path,
    mode: str,
) -> None:
    requirement = ProbeRequirement("m1", effort="low", permission_mode="auto")
    result = asyncio.run(
        configured_driver(fake_agents, mode).probe_models((requirement,), tmp_path)
    )
    assert requirement not in result.confirmed_requirements
    assert result.requirement_failures[requirement].code == "agent_configuration_error"


def test_distinct_configurations_for_the_same_model_use_fresh_defaults(
    fake_agents: FakeAgents,
    tmp_path: Path,
) -> None:
    requirements = (
        ProbeRequirement("m1", effort="low", permission_mode="auto"),
        ProbeRequirement("m1"),
        ProbeRequirement("m1", effort="high"),
    )
    result = asyncio.run(configured_driver(fake_agents).probe_models(requirements, tmp_path))
    assert result.confirmed_requirements == frozenset(requirements)
    assert (
        len([item for item in fake_agents.messages() if item.get("method") == "session/new"]) == 3
    )
    assert assignments(fake_agents) == [
        ("model", "m1"),
        ("mode", "auto"),
        ("reasoning_effort", "low"),
        ("model", "m1"),
        ("model", "m1"),
        ("reasoning_effort", "high"),
    ]


def test_legacy_modes_use_the_supported_session_mode_method(
    fake_agents: FakeAgents,
    tmp_path: Path,
) -> None:
    requirement = ProbeRequirement("m1", effort="low", permission_mode="auto")
    result = asyncio.run(
        configured_driver(fake_agents, "configuration-legacy").probe_models(
            (requirement,), tmp_path
        )
    )
    assert result.confirmed_requirements == frozenset({requirement})
    selector = result.configurations["m1"].permission_mode
    assert selector is not None and selector.transport == "session_mode"
    modes = [
        item["params"]["modeId"]
        for item in fake_agents.messages()
        if item.get("method") == "session/set_mode"
    ]
    assert modes == ["auto"]


@pytest.mark.parametrize("explicit", [False, True])
def test_attempts_apply_only_explicit_overrides_before_prompting(
    agent_context: AgentExecutionContext,
    fake_agents: FakeAgents,
    monkeypatch: pytest.MonkeyPatch,
    explicit: bool,
) -> None:
    monkeypatch.setenv("FAKE_ACP_MODE", "configuration")
    context = replace(
        agent_context,
        effort="low" if explicit else None,
        permission_mode="auto" if explicit else None,
    )
    _events, result = execute(AcpDriver(PROFILES["codex"], context.command), context)
    assert result.succeeded
    selected = assignments(fake_agents)
    assert (
        selected[-3:] == [("model", "m1"), ("mode", "auto"), ("reasoning_effort", "low")]
        if explicit
        else selected[-1:] == [("model", "m1")]
    )
    prompt_index = next(
        index
        for index, item in enumerate(fake_agents.messages())
        if item.get("method") == "session/prompt"
    )
    assert all(
        index < prompt_index
        for index, item in enumerate(fake_agents.messages())
        if item.get("method") == "session/set_config_option"
    )
    config_ids = NodeAttempt.objects.get(pk=context.attempt.attempt.attempt_id).config_ids
    assert config_ids == (
        {"model": "model", "permission_mode": "mode", "effort": "reasoning_effort"}
        if explicit
        else {"model": "model"}
    )


@pytest.mark.parametrize(
    "mode", ["configuration-late-effort-drift", "configuration-late-mode-drift"]
)
def test_attempts_cancel_if_a_provider_changes_an_explicit_override(
    agent_context: AgentExecutionContext,
    monkeypatch: pytest.MonkeyPatch,
    fake_agents: FakeAgents,
    mode: str,
) -> None:
    monkeypatch.setenv("FAKE_ACP_MODE", mode)
    context = replace(agent_context, effort="low", permission_mode="auto")
    with pytest.raises(AgentConfigurationError):
        execute(AcpDriver(PROFILES["codex"], context.command), context)
    assert any(item.get("method") == "session/cancel" for item in fake_agents.messages())


def test_preflight_routes_same_model_with_different_overrides_independently(
    fake_agents: FakeAgents,
    tmp_path: Path,
) -> None:
    fake_agents.install("codex", mode="configuration")
    requirements = (
        RouteRequirement(
            "root.first", "m1", ("codex",), agent_options={"codex": AgentOptions(effort="low")}
        ),
        RouteRequirement(
            "root.second",
            "m1",
            ("codex",),
            agent_options={"codex": AgentOptions(effort="high", permission_mode="auto")},
        ),
    )
    routes, _probes = preflight_routes(requirements, tmp_path)
    serialized = serialize_route_table(routes)
    assert serialized["root.first"]["effort"] == "low"
    assert "permission_mode" not in serialized["root.first"]
    assert serialized["root.second"]["effort"] == "high"
    assert serialized["root.second"]["permission_mode"] == "auto"


def test_preflight_chooses_a_candidate_that_supports_its_own_overrides(
    fake_agents: FakeAgents,
    tmp_path: Path,
) -> None:
    fake_agents.install("codex", mode="configuration")
    fake_agents.install("claude", mode="configuration")
    requirement = RouteRequirement(
        "root.work",
        "m2",
        ("codex", "claude"),
        agent_options={
            "codex": AgentOptions(effort="high"),
            "claude": AgentOptions(effort="medium"),
        },
    )
    routes, _probes = preflight_routes((requirement,), tmp_path)
    assert routes[0].selected_agent == "claude"
    assert routes[0].effort == "medium"


def test_a_confirmed_override_cannot_authorize_a_rejected_default_route(
    fake_agents: FakeAgents,
    tmp_path: Path,
) -> None:
    fake_agents.install("codex", mode="configuration-default-reject")
    requirements = (
        RouteRequirement("root.default", "m1", ("codex",)),
        RouteRequirement(
            "root.explicit", "m1", ("codex",), agent_options={"codex": AgentOptions(effort="low")}
        ),
    )
    with pytest.raises(ModelSelectionRejectedError):
        preflight_routes(requirements, tmp_path)
    # The explicit combination did succeed; the rejected default still blocks launch.
    assert assignments(fake_agents)[-1] == ("reasoning_effort", "low")


@pytest.mark.usefixtures("registry_network", "database_threads")
def test_launch_snapshots_and_executes_saved_overrides_end_to_end(
    project: RelayProject,
    engine: InlineEngine,
    fake_agents: FakeAgents,
) -> None:
    fake_agents.install("codex", mode="configuration")
    project.write_workflow(
        "configured",
        "version: 1\nname: Configured\nmodel: m1\nagents: [codex]\nnodes:\n"
        "  work:\n    type: agent\n    agent_options:\n"
        "      codex: {effort: low, permission_mode: auto}\n",
    )
    engine.executors = node_executors(agent_driver=RoutedAgentNodeDriver())
    run_id = engine.launch(project, "configured")
    route = RunSnapshot.objects.get(run_id=run_id).route_table["root.work"]
    assert (route["effort"], route["permission_mode"]) == ("low", "auto")
    engine.drain(run_id)
    assert run_status(run_id) == "succeeded"
    assert (
        assignments(fake_agents)
        == [("model", "m1"), ("mode", "auto"), ("reasoning_effort", "low")] * 2
    )


@pytest.mark.usefixtures("registry_network")
def test_an_invalid_override_prevents_run_creation(
    project: RelayProject,
    engine: InlineEngine,
    fake_agents: FakeAgents,
) -> None:
    fake_agents.install("codex", mode="configuration")
    project.write_workflow(
        "invalid",
        "version: 1\nname: Invalid\nmodel: m2\nagents: [codex]\nnodes:\n"
        "  work:\n    type: agent\n    agent_options:\n      codex: {effort: high}\n",
    )
    with pytest.raises(AgentConfigurationError):
        engine.launch(project, "invalid")
    assert not Run.objects.exists()
    assert not engine.tokens


@pytest.mark.parametrize("explicit", [False, True])
@pytest.mark.parametrize("agent_context", ["antigravity"], indirect=True)
def test_native_defaults_and_explicit_flags(
    agent_context: AgentExecutionContext,
    fake_agents: FakeAgents,
    explicit: bool,
) -> None:
    context = replace(
        agent_context,
        model_value="gemini-test-low",
        effort="low" if explicit else None,
        permission_mode="auto_approve" if explicit else None,
    )
    _events, result = execute(AntigravityDriver(PROFILES["antigravity"], context.command), context)
    assert result.succeeded
    arguments = next(item["argv"] for item in fake_agents.messages() if "argv" in item)
    assert ("--effort" in arguments) is explicit
    assert ("--dangerously-skip-permissions" in arguments) is explicit
    if explicit:
        assert arguments[arguments.index("--effort") + 1] == "low"


def test_native_effort_cannot_silently_change_the_exact_model(
    fake_agents: FakeAgents,
    tmp_path: Path,
) -> None:
    executable = fake_agents.install("antigravity", mode="configuration")
    driver = AntigravityDriver(PROFILES["antigravity"], AgentCommand(str(executable)))
    valid = ProbeRequirement("gemini-test-low", effort="low", permission_mode="auto_approve")
    invalid = ProbeRequirement("gemini-test-low", effort="high")
    result = asyncio.run(
        driver.probe_models((valid, invalid, ProbeRequirement("gemini-test-low")), tmp_path)
    )
    assert valid in result.confirmed_requirements
    assert ProbeRequirement("gemini-test-low") in result.confirmed_requirements
    assert result.requirement_failures[invalid].code == "agent_configuration_error"


@pytest.mark.parametrize("mode", ["accept-edits", "plan"])
@pytest.mark.parametrize("agent_context", ["antigravity"], indirect=True)
def test_native_permission_modes_use_the_cli_mode_flag(
    agent_context: AgentExecutionContext,
    fake_agents: FakeAgents,
    mode: str,
) -> None:
    context = replace(agent_context, permission_mode=mode)
    _events, result = execute(AntigravityDriver(PROFILES["antigravity"], context.command), context)
    assert result.succeeded
    arguments = next(item["argv"] for item in fake_agents.messages() if "argv" in item)
    assert arguments[arguments.index("--mode") + 1] == mode
    assert "--dangerously-skip-permissions" not in arguments


def test_configuration_api_is_authenticated_and_does_not_create_a_run(
    project: RelayProject,
    fake_agents: FakeAgents,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_agents.install("codex", mode="configuration")
    monkeypatch.setenv("RELAY_PROJECT_ROOT", str(project.repository))
    client = Client()
    url = "/api/agents/codex/configuration"
    payload = json.dumps({"model": "m2"})
    assert client.post(url, data=payload, content_type="application/json").status_code == 401
    assert (
        client.post(
            "/api/auth/onboard",
            data=json.dumps({"username": "owner", "password": "Relay-Test-Passphrase-2026!"}),
            content_type="application/json",
        ).status_code
        == 201
    )
    response = client.post(url, data=payload, content_type="application/json")
    assert response.status_code == 200
    assert response.json()["effort"]["choices"][1]["value"] == "medium"
    assert client.get(url).status_code == 405
    assert not Run.objects.exists()
    assert assignments(fake_agents) == [("model", "m2")]
    invalid = client.post(
        url, data=json.dumps({"model": "unknown"}), content_type="application/json"
    )
    assert (invalid.status_code, invalid.json()["code"]) == (422, "model_unavailable_error")


def test_single_tool_configuration_probe_does_not_start_other_agents(
    fake_agents: FakeAgents,
    tmp_path: Path,
) -> None:
    fake_agents.install("codex", mode="configuration")
    fake_agents.install("claude", mode="configuration")
    configuration = probe_agent_configuration("codex", "m1", tmp_path)
    assert configuration.agent_id == "codex"
    assert len([item for item in fake_agents.messages() if item.get("method") == "initialize"]) == 1
