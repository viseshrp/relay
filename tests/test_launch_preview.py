"""Launch preview shows each step's launch-static instructions without side effects."""

from __future__ import annotations

from hashlib import sha256
import json

from django.contrib.auth.models import User
from django.test import Client

from relay.web.models import NodeAttempt, Run, RunSnapshot, WorkflowNote
from relay.workflows.notes import FrozenNote, frozen_notes
from tests.support import FakeAgents, RelayProject, git
from tests.test_web_api import client as client
from tests.test_web_api import owner as owner
from tests.test_web_api import post
from tests.test_web_api import served as served

PROMPT = "Review the captured plan.\n"
WORKFLOW = {
    "name": "Review",
    "run-name": "Review ${{ inputs.target }}",
    "on": {
        "workflow_dispatch": {
            "inputs": {"target": {"type": "string", "required": True}},
        }
    },
    "jobs": {
        "plan": {
            "steps": [{"id": "list", "run": "echo ${{ inputs.target }} ${{ relay.sha }}"}],
        },
        "review": {
            "needs": "plan",
            "steps": [
                {
                    "id": "agent",
                    "name": "Review ${{ inputs.target }}",
                    "uses": "relay/agent@v1",
                    "with": {
                        "agent": "codex",
                        "model": "m1",
                        "prompt-files": "prompts/review.md",
                        "prompt": (
                            "Focus on ${{ inputs.target }} and ${{ steps.list.outputs.file }}."
                        ),
                        "report": "REVIEW.md",
                        "label": "Created by",
                    },
                }
            ],
        },
    },
}


def _preview(owner: Client, key: str, inputs: dict[str, object]) -> dict[str, object]:
    response = post(owner, f"/api/workflows/{key}/preview", {"inputs": inputs})
    assert response.status_code == 200, response.content
    return response.json()


def test_preview_renders_static_values_and_keeps_runtime_placeholders(
    owner: Client, served: RelayProject
) -> None:
    served.write(".relay/prompts/review.md", PROMPT)
    served.write_workflow("review", json.dumps(WORKFLOW))
    preview = _preview(owner, "review", {"target": "api"})
    assert preview["run_name"] == {"text": "Review api", "runtime": []}
    assert [job["id"] for job in preview["jobs"]] == ["plan", "review"]
    plan, review = preview["jobs"]
    assert review["needs"] == ["plan"]
    assert plan["steps"][0]["kind"] == "command"
    head = git(served.repository, "rev-parse", "HEAD")
    assert plan["steps"][0]["command"] == {"text": f"echo api {head}", "runtime": []}
    step = review["steps"][0]
    assert step["name"] == "Review api"
    assert step["agents"] == {"text": "codex", "runtime": []}
    assert step["model"] == {"text": "m1", "runtime": []}
    assert step["prompt_files"] == [
        {
            "reference": "prompts/review.md",
            "sha256": sha256(PROMPT.encode()).hexdigest(),
            "bytes": len(PROMPT),
            "text": PROMPT,
            "truncated": False,
        }
    ]
    assert step["prompt"] == {
        "text": "Focus on api and ${{ steps.list.outputs.file }}.",
        "runtime": ["steps.list.outputs.file"],
    }
    assert json.loads(step["report"]["text"]) == {
        "value": {"label": {"artifact": "REVIEW.md", "label": "Created by"}}
    }


def test_preview_creates_no_run_snapshot_worktree_or_agent_session(
    owner: Client, served: RelayProject, fake_agents: FakeAgents
) -> None:
    fake_agents.install("codex")
    served.write(".relay/prompts/review.md", PROMPT)
    served.write_workflow("review", json.dumps(WORKFLOW))
    status = git(served.repository, "status", "--porcelain=v1")
    worktrees = git(served.repository, "worktree", "list")
    _preview(owner, "review", {"target": "api"})
    assert not Run.objects.exists()
    assert not RunSnapshot.objects.exists()
    assert not NodeAttempt.objects.exists()
    assert git(served.repository, "status", "--porcelain=v1") == status
    assert git(served.repository, "worktree", "list") == worktrees
    assert fake_agents.messages() == []


def test_preview_applies_launch_input_rules(owner: Client, served: RelayProject) -> None:
    served.write(".relay/prompts/review.md", PROMPT)
    served.write_workflow("review", json.dumps(WORKFLOW))
    response = post(owner, "/api/workflows/review/preview", {"inputs": {}})
    assert response.status_code == 422
    missing = post(owner, "/api/workflows/missing/preview", {"inputs": {}})
    assert missing.status_code == 422
    assert missing.json()["code"] == "workflow_validation_error"


def test_runtime_prompt_files_are_listed_without_resolution(
    owner: Client, served: RelayProject
) -> None:
    workflow = json.loads(json.dumps(WORKFLOW))
    workflow["jobs"]["review"]["strategy"] = {"matrix": {"file": ["review.md"]}}
    workflow["jobs"]["review"]["steps"][0]["with"]["prompt-files"] = "prompts/${{ matrix.file }}"
    served.write(".relay/prompts/review.md", PROMPT)
    served.write_workflow("review", json.dumps(workflow))
    job = _preview(owner, "review", {"target": "api"})["jobs"][1]
    assert job["matrix"] is True
    step = job["steps"][0]
    assert step["prompt_files"] == []
    assert step["prompt_files_runtime"] == {
        "text": "prompts/${{ matrix.file }}",
        "runtime": ["matrix.file"],
    }


def test_preview_requires_login_and_post(
    client: Client, owner: Client, served: RelayProject
) -> None:
    served.write_workflow("review", json.dumps(WORKFLOW))
    assert owner.get("/api/workflows/review/preview").status_code == 405
    client.logout()
    assert post(client, "/api/workflows/review/preview", {"inputs": {}}).status_code == 401
    client.force_login(User.objects.get(username="owner"))


CHILD = """name: Child
on:
  workflow_call:
    inputs:
      target:
        type: string
        required: true
jobs:
  inner:
    steps:
      - id: say
        run: echo child ${{ inputs.target }}
"""
ACTION = """name: Check
description: Run a check on one target.
inputs:
  target:
    description: What to check.
    default: everything
runs:
  using: composite
  steps:
    - id: check
      shell: bash
      run: echo check ${{ inputs.target }}
"""


def test_preview_expands_reusable_workflows_loops_and_composite_actions(
    owner: Client, served: RelayProject
) -> None:
    served.write(".relay/workflows/child.yaml", CHILD)
    served.write(".relay/actions/check/action.yaml", ACTION)
    served.write_workflow(
        "nested",
        json.dumps(
            {
                "on": {"workflow_dispatch": {"inputs": {"target": {"type": "string"}}}},
                "jobs": {
                    "call": {
                        "uses": "./.relay/workflows/child.yaml",
                        "with": {"target": "${{ inputs.target }}"},
                    },
                    "local": {
                        "steps": [
                            {
                                "id": "composite",
                                "uses": "./.relay/actions/check",
                                "with": {"target": "${{ inputs.target }}"},
                            },
                            {
                                "id": "repeat",
                                "uses": "relay/loop@v1",
                                "with": {
                                    "workflow": "./.relay/workflows/child.yaml",
                                    "inputs": '{"target": "again"}',
                                    "max-iterations": 3,
                                },
                            },
                        ]
                    },
                },
            }
        ),
    )
    preview = _preview(owner, "nested", {"target": "api"})
    call, local = preview["jobs"]
    assert call["uses"] == "./.relay/workflows/child.yaml"
    assert call["jobs"][0]["steps"][0]["command"]["text"] == "echo child api"
    composite, repeat = local["steps"]
    assert composite["steps"][0]["command"]["text"] == "echo check api"
    assert repeat["repeat"]["text"] == "3"
    assert repeat["jobs"][0]["steps"][0]["command"]["text"] == "echo child again"
    assert preview["notes"] is None


def test_preview_shows_the_notes_block_launch_would_freeze(
    owner: Client, served: RelayProject
) -> None:
    served.write(".relay/prompts/review.md", PROMPT)
    served.write_workflow("review", json.dumps(WORKFLOW))
    note = WorkflowNote.objects.create(
        project_id=served.project_id,
        workflow_key="review.yaml",
        cue="Tests are slow",
        lesson="Run the fast suite first",
        evidence="Run #4 timed out",
    )
    response = post(
        owner,
        "/api/workflows/review/preview",
        {"inputs": {"target": "api"}, "notes": [str(note.pk)]},
    )
    assert response.status_code == 200, response.content
    expected = frozen_notes(
        (
            FrozenNote(
                str(note.pk), "Tests are slow", "Run the fast suite first", "Run #4 timed out", None
            ),
        )
    )
    assert expected is not None
    assert response.json()["notes"] == expected["text"]
    WorkflowNote.objects.filter(pk=note.pk).update(archived=True)
    rejected = post(
        owner,
        "/api/workflows/review/preview",
        {"inputs": {"target": "api"}, "notes": [str(note.pk)]},
    )
    assert (rejected.status_code, rejected.json()["code"]) == (400, "config_error")
