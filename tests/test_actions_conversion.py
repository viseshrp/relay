"""Conversion preserves provable values and exposes policies needing review."""

import json

import pytest

from relay.workflows.actions.conversion import preview
from relay.workflows.actions.language import load


def test_actions_preview_preserves_exact_comments_and_bytes() -> None:
    text = (
        "# Owner comment\nname: Existing\njobs: {a: {runs-on: self-hosted, steps: [{run: echo}]}}\n"
    )
    assert preview(text) == {"yaml": text, "issues": [], "complete": True}


@pytest.mark.parametrize(
    "timeout,minutes", [("250ms", 1 / 240), ("4s", 1 / 15), ("3m", 3), ("2h", 120)]
)
def test_legacy_command_durations_convert_to_minutes(timeout: str, minutes: float) -> None:
    result = preview(
        "version: 1\nname: Timed\nnodes:\n"
        f"  check: {{type: command, run: [git, status], timeout: {timeout}}}\n"
    )
    document = load(result["yaml"]).value
    job = document["jobs"]["check"]
    assert job["timeout-minutes"] == pytest.approx(minutes)
    assert json.loads(job["steps"][0]["with"]["argv"]) == ["git", "status"]
    assert result["complete"] and result["source_unchanged"]


def test_conversion_preserves_inputs_env_routes_prompts_and_dependencies() -> None:
    result = preview("""version: 1
name: Legacy
agents: [codex]
model: exact-model
env: {VALUE: ready}
inputs:
  mode: {type: enum, default: quick, constraints: {values: [quick, thorough]}}
  enabled: {type: boolean, required: true, description: Enable it}
nodes:
  prepare: {type: command, run: {command: owner_check}}
  review:
    type: agent
    needs: [prepare]
    prompts: [{local: prompts/review.md}, {global: common.md}]
  approve: {type: human_wait, needs: [review], prompt: Continue?, deadline: 15m}
""")
    document = load(result["yaml"]).value
    assert document["env"] == {"VALUE": "ready"}
    inputs = document["on"]["workflow_dispatch"]["inputs"]
    assert inputs["mode"] == {
        "description": "",
        "type": "choice",
        "default": "quick",
        "required": False,
        "options": ["quick", "thorough"],
    }
    assert inputs["enabled"]["type"] == "boolean" and inputs["enabled"]["required"]
    jobs = document["jobs"]
    assert jobs["prepare"]["steps"][0]["with"] == {"command": "owner_check"}
    assert jobs["review"]["needs"] == ["prepare"]
    assert jobs["review"]["steps"][0]["with"] == {
        "agents": '["codex"]',
        "model": "exact-model",
        "prompt-files": "prompts/review.md\nglobal:common.md",
    }
    assert jobs["approve"]["steps"][0]["with"] == {"prompt": "Continue?", "timeout-minutes": "15"}
    assert result["complete"]


def test_conversion_marks_untranslated_control_flow_and_policies_for_review() -> None:
    result = preview("""version: 1
name: Review
inputs:
  count: {type: integer, default: 2}
  slug: {type: string, constraints: {min_length: 2}}
nodes:
  check:
    type: command
    run: [git, status]
    env: {VALUE: local}
    writes: true
    allow_no_commit: true
  review:
    type: agent
    agents: [codex]
    agent_options: {codex: {effort: high}}
  approve: {type: human_wait, prompt: Continue?, on_timeout: check}
  choose: {type: condition, expr: '${{ True }}', branches: {yes: check}}
  child: {type: subworkflow, workflow: child}
""")
    assert not result["complete"] and result["source_unchanged"]
    issues = "\n".join(result["issues"])
    for term in (
        "expressions",
        "Git write",
        "provider effort",
        "timeout branching",
        "condition",
        "subworkflow",
        "inputs.count",
        "inputs.slug",
    ):
        assert term in issues
    assert "choose:" not in result["yaml"] and "child:" not in result["yaml"]
