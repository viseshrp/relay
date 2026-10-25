"""Owner-approved workflow notes are gated, scoped, and frozen at launch."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path

from django.test import Client
import pytest

from relay.constants import DEFAULT_RECOVERY_PROMPT
from relay.errors import ConfigError, PersistenceError
from relay.execution.nodes import node_executors
from relay.execution.runner import AttemptContext, ExecutionOutcome, OutcomeKind
from relay.web.models import Project, Run, RunSnapshot, WorkflowNote
from relay.workflows.notes import (
    NOTES_PER_LAUNCH_MAX,
    FrozenNote,
    frozen_notes,
    frozen_notes_text,
    launch_note_ids,
    validate_note,
)
from relay.workflows.schema import AgentNode
from tests.support import FakeAgents, InlineEngine, RelayProject
from tests.test_web_api import client as client
from tests.test_web_api import owner as owner
from tests.test_web_api import post
from tests.test_web_api import served as served

NOTE = {
    "cue": "The full test suite times out",
    "lesson": "Run the fast suite first and report which tests are slow",
    "evidence": "Run #4 timed out after 30 minutes in the full suite",
    "confidence": "medium",
}


@pytest.mark.parametrize("missing", ["cue", "lesson", "evidence"])
def test_a_note_needs_cue_lesson_and_evidence(missing: str) -> None:
    body = {**NOTE, missing: "   "}
    with pytest.raises(ConfigError, match=missing):
        validate_note(body)


@pytest.mark.parametrize(
    "body",
    [
        {**NOTE, "confidence": "certain"},
        {**NOTE, "cue": "x" * 501},
        {**NOTE, "evidence_run_id": 7},
    ],
)
def test_note_fields_are_bounded(body: dict[str, object]) -> None:
    with pytest.raises(ConfigError):
        validate_note(body)


def test_launch_note_ids_are_distinct_and_bounded() -> None:
    assert launch_note_ids(None) == ()
    assert launch_note_ids(["a", "b"]) == ("a", "b")
    for value in (["a", "a"], "a", [1], [f"n{i}" for i in range(NOTES_PER_LAUNCH_MAX + 1)]):
        with pytest.raises(ConfigError):
            launch_note_ids(value)


def test_frozen_block_keeps_order_and_detects_tampering() -> None:
    notes = (
        FrozenNote("1", "first cue", "first lesson", "first evidence", None),
        FrozenNote("2", "second cue", "second lesson", "second evidence", "high"),
    )
    record = frozen_notes(notes)
    assert record is not None
    text = frozen_notes_text({"workflow_notes": record})
    assert text is not None
    assert text.index("first lesson") < text.index("second lesson")
    assert "(confidence: high)" in text
    assert frozen_notes(()) is None
    assert frozen_notes_text({}) is None
    with pytest.raises(PersistenceError):
        frozen_notes_text({"workflow_notes": {**record, "text": text + "edited"}})


def test_notes_api_creates_lists_and_archives(owner: Client, served: RelayProject) -> None:
    served.write_workflow("review", "name: Review\njobs: {check: {steps: [{run: echo ok}]}}\n")
    created = post(owner, "/api/workflows/review/notes", NOTE)
    assert created.status_code == 201, created.content
    note = created.json()["note"]
    assert note["workflow_key"] == "review.yaml"
    assert {key: note[key] for key in NOTE} == NOTE
    listed = owner.get("/api/workflows/review.yaml/notes").json()["notes"]
    assert [item["id"] for item in listed] == [note["id"]]
    archived = post(owner, f"/api/workflows/review/notes/{note['id']}/archive", {})
    assert archived.status_code == 200
    assert archived.json()["note"]["archived"] is True
    assert owner.get("/api/workflows/review/notes").json()["notes"] == []
    assert len(owner.get("/api/workflows/review/notes?archived=true").json()["notes"]) == 1
    rejected = post(owner, "/api/workflows/review/notes", {**NOTE, "evidence": ""})
    assert (rejected.status_code, rejected.json()["code"]) == (400, "config_error")
    assert WorkflowNote.objects.count() == 1


def test_evidence_runs_must_belong_to_the_project(
    owner: Client, served: RelayProject, engine: InlineEngine, tmp_path: Path
) -> None:
    served.write_workflow("review", "name: Review\njobs: {check: {steps: [{run: echo ok}]}}\n")
    run_id = engine.launch(served, "review")
    engine.drain(run_id)
    linked = post(owner, "/api/workflows/review/notes", {**NOTE, "evidence_run_id": run_id})
    assert linked.status_code == 201
    assert linked.json()["note"]["evidence_run_id"] == run_id
    other = Project.objects.create(
        canonical_path=str(tmp_path / "other"), display_name="Other", git_root=str(tmp_path)
    )
    Run.objects.filter(pk=run_id).update(project=other)
    response = post(owner, "/api/workflows/review/notes", {**NOTE, "evidence_run_id": run_id})
    assert (response.status_code, response.json()["code"]) == (400, "config_error")


@dataclass
class PromptDriver:
    """Record each attempt's prompt blocks and fail the first report once."""

    calls: list[AttemptContext] = field(default_factory=list)

    def execute(self, context: AttemptContext, node: AgentNode) -> ExecutionOutcome:
        del node
        self.calls.append(context)
        recovering = any(
            DEFAULT_RECOVERY_PROMPT in text for text in context.attempt.prompt_contents
        )
        (context.worktree / "REVIEW.md").write_text(
            "Created by: Offline provider\n" if recovering else "Ready: No\n", encoding="utf-8"
        )
        return ExecutionOutcome(OutcomeKind.SUCCEEDED)


def _agent_workflow(project: RelayProject) -> None:
    project.write(".relay/prompts/review.md", "Review the change.\n")
    project.write_workflow(
        "review",
        json.dumps(
            {
                "recovery": {"enabled": True, "max_retries": 2},
                "jobs": {
                    "check": {
                        "steps": [
                            {
                                "id": "list",
                                "uses": "relay/command@v1",
                                "with": {"argv": '["git", "status"]'},
                            },
                            {
                                "id": "review",
                                "uses": "relay/agent@v1",
                                "with": {
                                    "agent": "codex",
                                    "model": "m1",
                                    "prompt-files": "prompts/review.md",
                                    "report": "REVIEW.md",
                                    "label": "Created by",
                                },
                            },
                        ]
                    }
                },
            }
        ),
    )


def _note(project: RelayProject, **values: object) -> str:
    note = WorkflowNote.objects.create(
        **{"project_id": project.project_id, "workflow_key": "review.yaml", **NOTE, **values}
    )
    return str(note.pk)


def test_launch_freezes_selected_notes_as_a_separate_block_reused_by_retries(
    project: RelayProject, fake_agents: FakeAgents
) -> None:
    from relay.paths import artifacts_dir

    fake_agents.install("codex")
    _agent_workflow(project)
    second = _note(project, lesson="Second lesson")
    first = _note(project, lesson="First lesson")
    driver = PromptDriver()
    engine = InlineEngine(node_executors(agent_driver=driver), artifacts_dir())
    run_id = engine.launch(project, "review", notes=[first, second])
    WorkflowNote.objects.filter(pk=first).update(lesson="Edited later", archived=True)
    engine.drain(run_id)
    assert Run.objects.get(pk=run_id).status == "succeeded"
    assert len(driver.calls) == 2
    snapshot = RunSnapshot.objects.get(run_id=run_id)
    frozen = snapshot.launch_defaults["workflow_notes"]
    assert [note["id"] for note in frozen["notes"]] == [first, second]
    for call in driver.calls:
        prompts = call.attempt.prompt_contents
        assert prompts[0] == "Review the change.\n"
        assert prompts[1] == frozen["text"]
        assert prompts[1].index("First lesson") < prompts[1].index("Second lesson")
        assert "Edited later" not in prompts[1]


def test_launch_without_notes_keeps_prompts_unchanged(
    project: RelayProject, fake_agents: FakeAgents
) -> None:
    from relay.paths import artifacts_dir

    fake_agents.install("codex")
    _agent_workflow(project)
    _note(project)
    driver = PromptDriver()
    engine = InlineEngine(node_executors(agent_driver=driver), artifacts_dir())
    run_id = engine.launch(project, "review")
    engine.drain(run_id)
    assert "workflow_notes" not in RunSnapshot.objects.get(run_id=run_id).launch_defaults
    assert driver.calls[0].attempt.prompt_contents == ("Review the change.\n",)


def test_archived_or_foreign_notes_reject_the_launch(
    project: RelayProject, fake_agents: FakeAgents, engine: InlineEngine
) -> None:
    fake_agents.install("codex")
    _agent_workflow(project)
    archived = _note(project, archived=True)
    other = _note(project, workflow_key="other.yaml")
    for note in (archived, other):
        with pytest.raises(ConfigError):
            engine.launch(project, "review", notes=[note])
    assert not Run.objects.exists()


def test_launch_endpoint_accepts_and_validates_notes(owner: Client, served: RelayProject) -> None:
    served.write_workflow("review", "name: Review\njobs: {check: {steps: [{run: echo ok}]}}\n")
    response = post(
        owner, "/api/runs", {"workflow_key": "review", "inputs": {}, "notes": ["a", "a"]}
    )
    assert (response.status_code, response.json()["code"]) == (400, "config_error")
    assert not Run.objects.exists()
