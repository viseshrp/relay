"""Current Actions declarations reach real provider transports before validation."""

import json
from pathlib import Path

import pytest

from relay.agents.driver import RoutedAgentNodeDriver
from relay.execution.nodes import node_executors
from relay.web.models import Artifact, NodeAttempt, NodeRun, Run, RunSnapshot
from tests.support import FakeAgents, InlineEngine, RelayProject

SOURCE = "Owner instructions: café\r\nKeep the declared task unchanged.\n"


@pytest.mark.parametrize("agent", ["codex", "antigravity"])
@pytest.mark.parametrize("format_name", ["label", "json", "yaml", "exists", "selector"])
def test_action_report_contract_reaches_the_provider_and_validates_its_result(
    project: RelayProject,
    engine: InlineEngine,
    fake_agents: FakeAgents,
    agent: str,
    format_name: str,
) -> None:
    engine.executors = node_executors(agent_driver=RoutedAgentNodeDriver())
    fake_agents.install(agent, mode="report-contract")
    project.write(".relay/prompts/task.md", SOURCE)
    requested = "evidence/report-café.txt"
    artifact = "evidence/chosen-café.txt" if format_name == "selector" else requested
    inputs = {
        "agent": agent,
        "model": "m1",
        "prompt-files": "prompts/task.md",
        "report": "${{ inputs.report }}",
        "format": format_name if format_name != "selector" else "label",
        "label": "Accepted",
        "field": "build.ready",
    }
    if format_name == "selector":
        inputs["selector"] = json.dumps({"label": {"artifact": artifact, "label": "Chosen"}})
    project.write_workflow(
        "handoff",
        json.dumps(
            {
                "on": {"workflow_dispatch": {"inputs": {"report": {"type": "string"}}}},
                "jobs": {
                    "work": {"steps": [{"id": "agent", "uses": "relay/agent@v1", "with": inputs}]}
                },
            }
        ),
    )
    run_id = engine.launch(project, "handoff", inputs={"report": requested})
    snapshot = RunSnapshot.objects.get(run_id=run_id)
    before = (snapshot.hashes, snapshot.resolved_definition, snapshot.resolved_prompts)
    engine.drain(run_id)
    assert Run.objects.get(pk=run_id).status == "succeeded"
    node = NodeRun.objects.get(run_id=run_id, scope_path="root.work.agent")
    assert node.outputs == {"value": "false" if format_name == "exists" else "Yes"}
    retained = Artifact.objects.filter(attempt__node_run=node, declared_name="report")
    if format_name == "exists":
        assert not retained.exists()
    else:
        report = retained.get()
        content = Path(report.retained_path).read_text(encoding="utf-8")
        assert "Yes" in content
        if format_name == "selector":
            assert "Chosen" in content
    messages = fake_agents.messages()
    if agent == "codex":
        blocks = next(
            row["params"]["prompt"] for row in messages if row.get("method") == "session/prompt"
        )
        assert blocks[0]["text"] == SOURCE
        prompt = "\n".join(block["text"] for block in blocks)
    else:
        prompt = next(row["input"]["message"]["content"] for row in messages if "input" in row)
        assert prompt.startswith(SOURCE)
    assert artifact in prompt
    assert "Relay declared outputs (JSON):" in prompt
    assert "report provenance" not in prompt
    assert "Keep phase boundaries" not in prompt
    snapshot.refresh_from_db()
    assert (snapshot.hashes, snapshot.resolved_definition, snapshot.resolved_prompts) == before


@pytest.mark.parametrize("selector", ["{", "{}"])
def test_invalid_report_contract_fails_before_the_agent_prompt(
    project: RelayProject, engine: InlineEngine, fake_agents: FakeAgents, selector: str
) -> None:
    engine.executors = node_executors(agent_driver=RoutedAgentNodeDriver())
    fake_agents.install("codex", mode="report-contract")
    project.write_workflow(
        "invalid-report",
        "jobs:\n"
        "  work:\n"
        "    steps:\n"
        "      - uses: relay/agent@v1\n"
        "        with:\n"
        "          agent: codex\n"
        "          model: m1\n"
        "          report: REPORT.md\n"
        f"          selector: {json.dumps(selector)}\n",
    )
    run_id = engine.launch(project, "invalid-report")
    engine.drain(run_id)
    assert Run.objects.get(pk=run_id).status == "failed"
    attempt = NodeAttempt.objects.get(node_run__run_id=run_id, node_run__node_type="actions_step")
    assert attempt.error_code == "node_execution_error"
    assert not any(row.get("method") == "session/prompt" for row in fake_agents.messages())
