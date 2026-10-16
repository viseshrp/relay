"""Real provider adapters communicating with offline executable boundaries."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import replace
import json
from pathlib import Path
import threading
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
from relay.constants import ANTIGRAVITY_PROMPT_MAX_BYTES, EVENT_MAX_PAYLOAD_BYTES
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
from relay.execution.runner import OutcomeKind
from relay.web.actions_bindings import put_binding
from relay.web.models import NodeAttempt, Run, RunEvent
from relay.web.repositories import DjangoExecutionStore
from relay.workflows.routing import RouteRequirement
from relay.workflows.schema import AgentNode
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


@pytest.mark.parametrize("agent_context", ["codex", "claude", "copilot", "cursor"], indirect=True)
@pytest.mark.parametrize("mode", ["terminal-metadata", "raw-output-exit"])
def test_acp_terminal_output_and_exit_survive_real_protocol_notifications(
    agent_context: AgentExecutionContext, fake_agents: FakeAgents, mode: str
) -> None:
    fake_agents.install(agent_context.agent_id, mode=mode)
    events, result = execute(
        AcpDriver(PROFILES[agent_context.agent_id], agent_context.command), agent_context
    )
    assert result.succeeded
    tools = [
        json.loads(event.payload["summary"])
        for event in events
        if event.event_type in {"agent.tool_call", "agent.tool_result"}
    ]
    if mode == "terminal-metadata":
        assert "".join(tool.get("output_delta", "") for tool in tools) == "Access denied\ndenied\n"
        assert tools[-1] == {"status": "failed", "exit_code": 3}
    else:
        assert tools[-1]["raw_output"] == {"exit_code": 3}
        assert tools[-1]["content"] == [{"text": "Access denied\n"}]
    initialization = next(
        message["params"]
        for message in fake_agents.messages()
        if message.get("method") == "initialize"
    )
    capabilities = initialization["clientCapabilities"]
    assert capabilities["_meta"] == {"terminal_output_delta": True}
    assert capabilities.get("terminal", False) is False
    filesystem = capabilities.get("fs", {})
    assert filesystem.get("readTextFile", False) is False
    assert filesystem.get("writeTextFile", False) is False
    assert "hidden" not in json.dumps(tools)


@pytest.mark.parametrize("agent_context", ["claude"], indirect=True)
@pytest.mark.parametrize("mode", ["quota", "quota-unknown"])
def test_claude_limits_use_typed_errors_and_only_confirmed_resets(
    agent_context: AgentExecutionContext, fake_agents: FakeAgents, mode: str
) -> None:
    fake_agents.install("claude", mode=mode)
    events, result = execute(AcpDriver(PROFILES["claude"], agent_context.command), agent_context)
    assert not result.succeeded and result.error_code == "agent_usage_limit"
    assert result.usage_limit is not None
    assert (result.usage_limit.reset_at is not None) == (mode == "quota")
    assert any(event.event_type == "agent.usage_limit" for event in events)


@pytest.mark.parametrize("agent_context", ["codex", "antigravity"], indirect=True)
def test_agents_receive_their_declared_output_selectors(
    agent_context: AgentExecutionContext,
    fake_agents: FakeAgents,
) -> None:
    selectors = {
        "report": {"label": {"artifact": "REPORT.md", "label": "Created by"}},
        "ready": {"json_path": {"artifact": "result.json", "path": "ready"}},
        "optional": {"exists": "optional.txt"},
    }
    definition = agent_context.node.model_dump(mode="json", by_alias=True)
    node = AgentNode.model_validate({**definition, "outputs": selectors})
    context = replace(agent_context, node=node)
    driver = (
        AntigravityDriver(PROFILES["antigravity"], context.command)
        if context.agent_id == "antigravity"
        else AcpDriver(PROFILES["codex"], context.command)
    )
    _, result = execute(driver, context)
    assert result.succeeded
    messages = fake_agents.messages()
    if context.agent_id == "antigravity":
        prompt = next(
            message["input"]["message"]["content"] for message in messages if "input" in message
        )
    else:
        blocks = next(
            message["params"]["prompt"]
            for message in messages
            if message.get("method") == "session/prompt"
        )
        prompt = "\n".join(block["text"] for block in blocks)
    assert json.dumps(selectors, sort_keys=True, ensure_ascii=False) in prompt
    assert "Relay worktree rules" in prompt
    assert "temporary_directory" in prompt
    selection = {
        "agent_id": context.agent_id,
        "model_value": "m1",
        "effort_override": None,
        "permission_mode_override": None,
        "permission_profile": context.permission_profile,
    }
    assert json.dumps(selection, sort_keys=True, ensure_ascii=False) in prompt


@pytest.mark.parametrize("decision", ["allow", "deny"])
def test_paused_acp_feedback_continues_the_same_exact_model_session(
    agent_context: AgentExecutionContext,
    fake_agents: FakeAgents,
    monkeypatch: pytest.MonkeyPatch,
    decision: str,
) -> None:
    from tests.test_agent_controls import answer_when_requested

    fake_agents.install("codex", mode="feedback")
    answer_when_requested(
        agent_context,
        monkeypatch,
        "permission_answer",
        {
            "decision": decision,
            "feedback": "Review the error paths before finishing.",
        },
    )
    driver = AcpDriver(PROFILES["codex"], agent_context.command)
    events, result = execute(driver, agent_context)
    assert result.succeeded
    answer = next(
        message["result"]
        for message in fake_agents.messages()
        if message.get("id") == "owner-permission"
    )
    assert answer["outcome"] == {"outcome": "selected", "optionId": decision}
    prompts = [
        message["params"]
        for message in fake_agents.messages()
        if message.get("method") == "session/prompt"
    ]
    assert len(prompts) == 2
    assert prompts[0]["sessionId"] == prompts[1]["sessionId"]
    assert prompts[1]["prompt"] == [
        {"type": "text", "text": "Review the error paths before finishing."}
    ]
    assert [
        event.payload["turn"] for event in events if event.event_type == "agent.turn_started"
    ] == [1, 2]


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


def test_provider_finishing_during_a_control_poll_keeps_its_completed_result(
    agent_context: AgentExecutionContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    ready = threading.Event()
    completed = threading.Event()
    monkeypatch.setattr("relay.agents.driver.CONTROL_POLL_INTERVAL_SECONDS", 0.01)

    async def supervise() -> None:
        loop = asyncio.get_running_loop()
        finish = asyncio.Event()

        class FinishingDriver(AcpDriver):
            starts: int = 0
            cancellations: int = 0

            async def start_attempt(
                self, context: AgentExecutionContext
            ) -> AsyncIterator[AgentEvent]:
                del context
                self.starts += 1
                yield AgentEvent("agent.message", {"text": "waiting for a control poll"})
                ready.set()
                await finish.wait()

            async def cancel(self) -> None:
                self.cancellations += 1

            async def finalize(self) -> AgentResult:
                # Run this callback after the execution task returns its result.
                loop.call_soon(completed.set)
                return AgentResult(True, "end_turn", 0)

        def poll(attempt_id: str, worker_id: str, kinds: tuple[str, ...] | None = None) -> None:
            del attempt_id, worker_id, kinds
            if ready.is_set():
                loop.call_soon_threadsafe(finish.set)
                assert completed.wait(5), "provider did not finish during the control poll"

        driver = FinishingDriver(PROFILES["codex"], agent_context.command)
        monkeypatch.setattr(agent_context.attempt.runtime, "claim_next_control", poll)
        try:
            result = await asyncio.wait_for(
                RoutedAgentNodeDriver()._supervise(driver, agent_context), timeout=5
            )
        finally:
            await asyncio.to_thread(connections.close_all)
        assert (result.kind, result.stop_reason, result.exit_code) == (
            OutcomeKind.SUCCEEDED,
            "completed",
            0,
        )
        assert driver.starts == 1
        assert driver.cancellations == 0
        assert completed.is_set()

    asyncio.run(supervise())


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
    assert arguments[arguments.index("--input-format") + 1] == "stream-json"
    assert arguments[arguments.index("--print-timeout") + 1] == "5m"
    assert "--dangerously-skip-permissions" in arguments
    assert "-p" not in arguments
    inputs = [message["input"] for message in fake_agents.messages() if "input" in message]
    assert len(inputs) == 1
    assert "Relay inputs" in inputs[0]["message"]["content"]
    assert {"input_closed": True} in fake_agents.messages()


@pytest.mark.parametrize("agent_context", ["antigravity"], indirect=True)
@pytest.mark.parametrize(
    "prompt",
    ['First line\n"Second" line', "é😀 %&|<>()^!", "\t" * 16_000, "é" * 24_000, "\t" * 40_000],
    ids=["newlines", "unicode", "escaped-input", "large-unicode", "large-escaped-input"],
)
def test_antigravity_stdin_preserves_prompt_text_while_draining_startup_output(
    agent_context: AgentExecutionContext,
    fake_agents: FakeAgents,
    monkeypatch: pytest.MonkeyPatch,
    prompt: str,
) -> None:
    monkeypatch.setenv("FAKE_AGY_MODE", "stdin-backpressure")
    claim = replace(agent_context.attempt.attempt, prompt_contents=(prompt,))
    context = replace(agent_context, attempt=replace(agent_context.attempt, attempt=claim))
    events, result = execute(AntigravityDriver(PROFILES["antigravity"], context.command), context)
    assert result.succeeded
    inputs = [message["input"] for message in fake_agents.messages() if "input" in message]
    assert len(inputs) == 1
    assert inputs[0]["message"]["content"].startswith(prompt + "\n\n--- Relay inputs")
    assert any(event.event_type == "agent.stderr" for event in events)
    assert {"input_closed": True} in fake_agents.messages()


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
@pytest.mark.parametrize(
    ("mode", "denied"),
    [
        ("headless-help-only", False),
        ("headless-denied-write", True),
        ("headless-denied-outside", False),
        ("headless-denied-stdout-only", False),
        ("headless-command-denied", False),
        ("headless-write-error", False),
        ("headless-denied-before-tool", True),
    ],
)
def test_antigravity_native_denial_notice_requires_matching_write_target(
    agent_context: AgentExecutionContext, monkeypatch: pytest.MonkeyPatch, mode: str, denied: bool
) -> None:
    monkeypatch.setenv("FAKE_AGY_MODE", mode)
    _events, result = execute(
        AntigravityDriver(PROFILES["antigravity"], agent_context.command), agent_context
    )
    assert result.succeeded is not denied
    assert result.denied_write_targets == (("report.txt",) if denied else ())
    assert result.error_code == ("antigravity_soft_denied" if denied else None)
    assert result.stop_reason == ("soft_denied" if denied else "completed")


@pytest.mark.parametrize("agent_context", ["antigravity"], indirect=True)
def test_oversized_antigravity_prompts_fail_before_starting_a_process(
    agent_context: AgentExecutionContext,
) -> None:
    claim = replace(
        agent_context.attempt.attempt, prompt_contents=("é" * ANTIGRAVITY_PROMPT_MAX_BYTES,)
    )
    context = replace(agent_context, attempt=replace(agent_context.attempt, attempt=claim))
    driver = AntigravityDriver(PROFILES["antigravity"], context.command)
    with pytest.raises(NodeExecutionError) as error:
        execute(driver, context)
    assert driver.process is None
    assert error.value.context["max_bytes"] == str(ANTIGRAVITY_PROMPT_MAX_BYTES)
    prompt_bytes = error.value.context["prompt_bytes"]
    assert prompt_bytes is not None
    assert int(prompt_bytes) > ANTIGRAVITY_PROMPT_MAX_BYTES


@pytest.mark.parametrize("agent_context", ["antigravity"], indirect=True)
def test_windows_batch_argument_limits_are_enforced_before_spawning(
    agent_context: AgentExecutionContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = replace(agent_context, command=AgentCommand("fake.cmd", ("😀" * 5_000,)))
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
        (
            "name: Routed\n"
            "jobs:\n"
            "  work:\n"
            "    steps:\n"
            "    - id: work\n"
            "      uses: relay/agent@v1\n"
            "      with:\n"
            "        agent: codex\n"
            "        model: m1\n"
        ),
    )
    engine.executors = node_executors(agent_driver=RoutedAgentNodeDriver())
    run_id = engine.launch(project, "routed")
    engine.drain(run_id)
    messages = RunEvent.objects.filter(run_id=run_id, type="agent.message")
    assert [message.payload["text"] for message in messages] == ["ready"]
    assert (
        NodeAttempt.objects.get(
            node_run__run_id=run_id, node_run__node_type="actions_step"
        ).agent_id
        == "codex"
    )


@pytest.mark.usefixtures("registry_network", "database_threads")
def test_routed_execution_preserves_oversized_visible_events(
    agent_context: AgentExecutionContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = "log\n" * (EVENT_MAX_PAYLOAD_BYTES // 4)

    class LargeMessageDriver(AcpDriver):
        async def start_attempt(self, context: AgentExecutionContext) -> AsyncIterator[AgentEvent]:
            yield AgentEvent("agent.message", {"text": text, "message_id": "message-1", "turn": 1})

        async def finalize(self) -> AgentResult:
            return AgentResult(True, "end_turn", 0)

    monkeypatch.setattr("relay.agents.driver._driver", LargeMessageDriver)
    outcome = RoutedAgentNodeDriver().execute(agent_context.attempt, agent_context.node)

    assert outcome.kind is OutcomeKind.SUCCEEDED
    payloads = list(
        RunEvent.objects.filter(
            attempt_id=agent_context.attempt.attempt.attempt_id, type="agent.message"
        )
        .order_by("id")
        .values_list("payload", flat=True)
    )
    assert len(payloads) > 1
    assert "".join(payload["text"] for payload in payloads) == text
    assert [payload["part"] for payload in payloads] == list(range(1, len(payloads) + 1))
    assert all(
        payload["parts"] == len(payloads)
        and payload["message_id"] == "message-1"
        and payload["turn"] == 1
        for payload in payloads
    )
    assert all(len(json.dumps(payload).encode()) <= EVENT_MAX_PAYLOAD_BYTES for payload in payloads)


@pytest.mark.usefixtures("registry_network", "database_threads")
@pytest.mark.parametrize("representation", ["deltas", "snapshots"])
def test_actions_driver_masks_tool_deltas_before_splitting_persisted_events(
    project: RelayProject,
    tmp_path: Path,
    fake_agents: FakeAgents,
    monkeypatch: pytest.MonkeyPatch,
    representation: str,
) -> None:
    masked_value = 'TOKEN-"\\\tEND'
    prefix = "log\n" * (EVENT_MAX_PAYLOAD_BYTES // 4)

    class TerminalDeltaDriver(AcpDriver):
        async def start_attempt(self, context: AgentExecutionContext) -> AsyncIterator[AgentEvent]:
            if representation == "snapshots":
                for kind, text in (
                    ("agent.tool_call", prefix + masked_value[:8]),
                    ("agent.tool_result", prefix + masked_value + "\n"),
                ):
                    yield AgentEvent(
                        kind,
                        {
                            "tool_call_id": "terminal",
                            "turn": 1,
                            "summary": json.dumps({"content": [{"text": text}]}),
                        },
                    )
                return
            for delta in (prefix + masked_value[:8], masked_value[8:] + "\n"):
                yield AgentEvent(
                    "agent.tool_call",
                    {
                        "tool_call_id": "terminal",
                        "turn": 1,
                        "summary": json.dumps({"output_delta": delta}),
                    },
                )
            yield AgentEvent(
                "agent.tool_result",
                {"tool_call_id": "terminal", "turn": 1, "summary": '{"exit_code":0}'},
            )

        async def finalize(self) -> AgentResult:
            return AgentResult(True, "end_turn", 0)

    fake_agents.install("codex")
    monkeypatch.setattr("relay.agents.driver._driver", TerminalDeltaDriver)
    monkeypatch.setenv("RELAY_TEST_SECRET", masked_value)
    put_binding(
        f"project:{project.project_id}",
        "KEY",
        "secret",
        source="environment",
        reference="RELAY_TEST_SECRET",
    )
    project.write_workflow(
        "tool_output",
        (
            "on: workflow_dispatch\n"
            "jobs:\n"
            "  check:\n"
            "    env: {KEY: '${{ secrets.KEY }}'}\n"
            "    steps:\n"
            "      - uses: relay/agent@v1\n"
            "        with: {agent: codex, model: m1}\n"
        ),
    )
    engine = InlineEngine(node_executors(), tmp_path / "artifacts")
    run_id = engine.launch(project, "tool_output")
    engine.drain(run_id)

    assert Run.objects.get(pk=run_id).status == "succeeded"
    payloads = list(
        RunEvent.objects.filter(run_id=run_id, type="agent.tool_call")
        .order_by("id")
        .values_list("payload", flat=True)
    )
    fragments = [payload for payload in payloads if "part" in payload]
    assert len(fragments) > 1
    assert [payload["part"] for payload in fragments] == list(range(1, len(fragments) + 1))
    assert all(payload["parts"] == len(fragments) for payload in fragments)
    summary = json.loads("".join(payload["summary"] for payload in fragments))
    if representation == "snapshots":
        assert summary["content"] == [{"text": prefix}]
        results = list(
            RunEvent.objects.filter(run_id=run_id, type="agent.tool_result")
            .order_by("id")
            .values_list("payload", flat=True)
        )
        assert len(results) > 1
        result = json.loads("".join(payload["summary"] for payload in results))
        assert result["content"] == [{"text": prefix + "***\n"}]
        assert all(
            len(json.dumps(payload).encode()) <= EVENT_MAX_PAYLOAD_BYTES for payload in results
        )
        return
    assert summary["output_delta"] == prefix
    assert (
        "".join(
            json.loads(payload["summary"])["output_delta"]
            for payload in payloads
            if "part" not in payload
        )
        == "***\n"
    )
    assert all(
        payload["tool_call_id"] == "terminal" and payload["turn"] == 1 for payload in payloads
    )
    assert all(len(json.dumps(payload).encode()) <= EVENT_MAX_PAYLOAD_BYTES for payload in payloads)


@pytest.mark.usefixtures("registry_network")
def test_the_agent_node_port_validates_its_writers_output_handoff(
    project: RelayProject, engine: InlineEngine, fake_agents: FakeAgents
) -> None:
    from relay.web.models import NodeRun, Run

    fake_agents.install("codex")
    project.write_workflow(
        "handoff",
        (
            "name: Handoff\n"
            "jobs:\n"
            "  work:\n"
            "    outputs:\n"
            "      ready: ${{ steps.work.outputs.value }}\n"
            "    steps:\n"
            "    - id: work\n"
            "      uses: relay/agent@v1\n"
            "      with:\n"
            "        agent: codex\n"
            "        model: m1\n"
            "        report: agent-output.md\n"
            "        label: Ready\n"
        ),
    )
    from tests.support import FakeAgentDriver

    engine.executors = node_executors(agent_driver=FakeAgentDriver(edit_file=True))
    run_id = engine.launch(project, "handoff")
    starting_head = Run.objects.get(pk=run_id).recorded_head

    engine.drain(run_id)

    assert NodeRun.objects.get(run_id=run_id, scope_path="root.work").outputs == {"ready": "Yes"}
    assert Run.objects.get(pk=run_id).recorded_head != starting_head
