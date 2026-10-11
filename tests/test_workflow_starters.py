"""Starter bundles validate, preserve exact bytes, and never replace owner files."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sys

import pytest

from relay.errors import PathSafetyError, PermissionFlowError, WorkflowValidationError
from relay.web.repositories import DjangoWorkflowStore
from relay.workflows import starters
from relay.workflows.loader import load_workflow
from relay.workflows.starters import (
    STARTER_ROOT,
    STARTERS,
    create_starter_workflow,
    starter_inventory,
)
from relay.workflows.validation import validate_loaded_workflow
from tests.support import (
    FakeAgents,
    InlineEngine,
    RelayProject,
    fake_executable,
    run_status,
    symlink_or_skip,
)


@pytest.mark.parametrize("starter", STARTERS, ids=lambda item: item.id)
def test_starter_copies_exact_sources_and_validates(
    project: RelayProject,
    starter: starters.Starter,
) -> None:
    key = f"{starter.id}.yaml"
    document = create_starter_workflow(
        DjangoWorkflowStore(), project.relay_root, project.project_id, key, starter.id
    )
    assert document.yaml.encode() == (STARTER_ROOT / key).read_bytes()
    for name in starter.prompts:
        assert (project.relay_root / "prompts" / name).read_bytes() == (
            STARTER_ROOT / name
        ).read_bytes()
    for target, source in starter.files:
        assert (project.relay_root / target).read_bytes() == (STARTER_ROOT / source).read_bytes()
    validate_loaded_workflow(
        load_workflow(project.relay_root / "workflows" / key), project.relay_root
    )
    second = create_starter_workflow(
        DjangoWorkflowStore(), project.relay_root, project.project_id, f"second-{key}", starter.id
    )
    assert second.yaml == document.yaml


def test_gallery_has_seven_templates_and_schema_defined_inputs() -> None:
    inventory = starter_inventory()
    assert len(inventory) == 7
    assert all(item["jobs"] and item["required_agents"] for item in inventory)
    assert [item["id"] for item in inventory if item["default"]] == ["ai-coding-workflow"]
    assert next(item for item in inventory if item["id"] == "ask-agent")["inputs"] == {
        "task": {
            "type": "string",
            "description": "What would you like to learn about this repository?",
            "default": "Explain what this repository does and where its main code lives.",
            "required": True,
            "constraints": {"min_length": None, "max_length": None, "pattern": None},
        },
    }


def test_starter_rejects_unknown_id_and_unsafe_key(project: RelayProject) -> None:
    store = DjangoWorkflowStore()
    with pytest.raises(WorkflowValidationError):
        create_starter_workflow(
            store, project.relay_root, project.project_id, "new.yaml", "unknown"
        )
    with pytest.raises(WorkflowValidationError):
        create_starter_workflow(
            store, project.relay_root, project.project_id, "../new.yaml", "ask-agent"
        )
    with pytest.raises(WorkflowValidationError):
        create_starter_workflow(
            store, project.relay_root, project.project_id, "CON.yaml", "ask-agent"
        )


def test_starter_preserves_existing_prompts_and_workflows(project: RelayProject) -> None:
    prompt = project.relay_root / "prompts" / "ask-agent.md"
    prompt.write_bytes(b"Owner instructions\n")
    with pytest.raises(PermissionFlowError):
        create_starter_workflow(
            DjangoWorkflowStore(), project.relay_root, project.project_id, "new.yaml", "ask-agent"
        )
    assert prompt.read_bytes() == b"Owner instructions\n"
    assert not (project.relay_root / "workflows" / "new.yaml").exists()
    with pytest.raises(PermissionFlowError):
        create_starter_workflow(
            DjangoWorkflowStore(),
            project.relay_root,
            project.project_id,
            "workflow.yaml",
            "write-docs",
        )
    assert not (project.relay_root / "prompts" / "write-docs.md").exists()


def test_starter_rolls_back_new_prompts_on_write_failure(
    project: RelayProject,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = starters._atomic_create

    def fail_workflow(path: Path, text: str) -> None:
        if path.suffix == ".yaml":
            message = "Could not publish."
            raise PermissionFlowError(message)
        original(path, text)

    monkeypatch.setattr(starters, "_atomic_create", fail_workflow)
    with pytest.raises(PermissionFlowError):
        create_starter_workflow(
            DjangoWorkflowStore(),
            project.relay_root,
            "project",
            "new.yaml",
            "plan-approve-implement",
        )
    assert not (project.relay_root / "workflows" / "new.yaml").exists()
    assert not (project.relay_root / "prompts" / "plan.md").exists()
    assert not (project.relay_root / "prompts" / "implement.md").exists()


def test_starter_rejects_symlink_escape(project: RelayProject, tmp_path: Path) -> None:
    outside = tmp_path / "outside.md"
    outside.write_bytes(b"Owner bytes")
    symlink_or_skip(project.relay_root / "prompts" / "ask-agent.md", outside)
    with pytest.raises(PathSafetyError):
        create_starter_workflow(
            DjangoWorkflowStore(), project.relay_root, project.project_id, "new.yaml", "ask-agent"
        )
    assert outside.read_bytes() == b"Owner bytes"


@pytest.mark.usefixtures("registry_network", "database_threads")
@pytest.mark.parametrize("passes_on,status,checks", [(2, "succeeded", 2), (99, "failed", 3)])
def test_fix_tests_starter_uses_real_verdicts_and_a_bounded_repair_budget(
    project: RelayProject,
    engine: InlineEngine,
    fake_agents: FakeAgents,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    passes_on: int,
    status: str,
    checks: int,
) -> None:
    counter = tmp_path / "test-counter"
    counter.write_text("0", encoding="utf-8")
    monkeypatch.setenv("STARTER_TEST_COUNTER", str(counter))
    monkeypatch.setenv("STARTER_TEST_PASSES_ON", str(passes_on))
    fake_agents.install("codex", mode="configuration")
    fake_agents.allow_commands(sys.executable)
    # Windows execv returns control before the replacement finishes. Keep this
    # shim alive so the owned job can retain pytest and report its real verdict.
    fake_executable(
        fake_agents.directory,
        "python",
        (
            "import subprocess, sys\n"
            "sys.exit(subprocess.call([sys.executable, *sys.argv[1:]], shell=False))\n"
        ),
    )
    project.write(".gitignore", "__pycache__/\n.pytest_cache/\n")
    project.write(
        "test_example.py",
        (
            "import os\nfrom pathlib import Path\n"
            "def test_result():\n"
            "    counter = Path(os.environ['STARTER_TEST_COUNTER'])\n"
            "    count = int(counter.read_text()) + 1\n"
            "    counter.write_text(str(count))\n"
            "    assert count >= int(os.environ['STARTER_TEST_PASSES_ON'])\n"
        ),
    )
    project.commit("Add deterministic sample tests")
    create_starter_workflow(
        DjangoWorkflowStore(), project.relay_root, project.project_id, "fix.yaml", "fix-tests"
    )
    run_id = engine.launch(project, "fix.yaml", model="m1")
    engine.drain(run_id)
    assert run_status(run_id) == status
    assert counter.read_text(encoding="utf-8") == str(checks)


def test_ai_starter_preserves_upstream_prompt_bytes() -> None:
    root = STARTER_ROOT / "ai-coding-workflow"
    provenance = json.loads((root / "provenance.json").read_text())
    assert len(provenance["prompts"]) == 10
    for name, digest in provenance["prompts"].items():
        assert sha256((root / name).read_bytes()).hexdigest() == digest
    # The copied workflow carries the upstream notice with the editable bundle.
    source = (STARTER_ROOT / "ai-coding-workflow.yaml").read_text()
    assert all(
        "# " + line in source for line in (root / "LICENSE").read_text().splitlines() if line
    )


@pytest.mark.parametrize(
    "target",
    [
        "workflows/ai-coding-workflow/plan-cycle.yaml",
        "actions/ai-coding-workflow/read-generated-prompt/action.yaml",
    ],
)
def test_ai_starter_preserves_owner_companion_sources(project: RelayProject, target: str) -> None:
    path = project.relay_root / target
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("Owner source\n")
    with pytest.raises(PermissionFlowError):
        create_starter_workflow(
            DjangoWorkflowStore(),
            project.relay_root,
            project.project_id,
            "full.yaml",
            "ai-coding-workflow",
        )
    assert path.read_text() == "Owner source\n"
    assert not (project.relay_root / "workflows/full.yaml").exists()
    assert not (project.relay_root / "prompts/ai-coding-workflow/interaction.md").exists()


def test_ai_starter_rolls_back_companions_if_main_workflow_cannot_publish(
    project: RelayProject,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = starters._atomic_create
    workflow = project.relay_root / "workflows/full.yaml"

    def fail_main(path: Path, text: str) -> None:
        if path == workflow:
            message = "Could not publish the main workflow."
            raise PermissionFlowError(message)
        original(path, text)

    monkeypatch.setattr(starters, "_atomic_create", fail_main)
    with pytest.raises(PermissionFlowError):
        create_starter_workflow(
            DjangoWorkflowStore(),
            project.relay_root,
            project.project_id,
            "full.yaml",
            "ai-coding-workflow",
        )
    for relative, _ in starters._sources(STARTERS[0], "full.yaml"):
        assert not (project.relay_root / relative).exists()


@pytest.mark.usefixtures("registry_network", "database_threads")
@pytest.mark.parametrize(
    "plan_ready,review_ready,audit_ready,audit_next,decision,status",
    [
        (2, 2, 2, "", "FOLLOWUP", "succeeded"),
        (1, 1, 1, "", "TESTS", "succeeded"),
        (99, 1, 1, "", "TESTS", "failed"),
        (1, 99, 1, "", "TESTS", "failed"),
        (1, 1, 99, "", "TESTS", "failed"),
        (1, 1, 1, "human", "TESTS", "failed"),
    ],
)
def test_full_starter_executes_handoffs_gates_and_bounded_loops(
    project: RelayProject,
    fake_agents: FakeAgents,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    plan_ready: int,
    review_ready: int,
    audit_ready: int,
    audit_next: str,
    decision: str,
    status: str,
) -> None:
    from relay.execution.nodes import node_executors
    from relay.execution.scheduler import dispatch_ready_nodes
    from relay.web.models import HumanInteraction, NodeAttempt, Run, RunEvent
    from tests.fake_agent import AI_HANDOFF

    counters = tmp_path / "phase-counters"
    counters.mkdir()
    monkeypatch.setenv("FAKE_AI_COUNTER_ROOT", str(counters))
    for name, value in (("PLAN", plan_ready), ("REVIEW", review_ready), ("AUDIT", audit_ready)):
        monkeypatch.setenv(f"FAKE_AI_{name}_READY_AFTER", str(value))
    if audit_next:
        monkeypatch.setenv("FAKE_AI_AUDIT_NEXT", audit_next)
    for agent in ("codex", "claude"):
        fake_agents.install(agent, mode="configuration-ai-starter")
    create_starter_workflow(
        DjangoWorkflowStore(),
        project.relay_root,
        project.project_id,
        "full.yaml",
        "ai-coding-workflow",
    )
    engine = InlineEngine(node_executors(), tmp_path / "artifacts")
    run_id = engine.launch(
        project,
        "full.yaml",
        inputs={
            "task": "Add dark mode",
            "agent": "codex",
            "model": "m1",
            "opus_model": "m2",
        },
    )
    engine.drain(run_id)
    answers = ["IMPLEMENT", decision, "ACCEPT"]
    answered = 0
    while run_status(run_id) != "failed" and answered < 3:
        pending = HumanInteraction.objects.get(run_id=run_id, kind="wait", status="pending")
        # No later phase runs before its owner gate has been answered.
        if answered == 0:
            assert not (counters / "review").exists()
        if answered == 1:
            assert not (counters / "tests").exists()
        engine.store.submit_control(
            str(pending.attempt_id),
            "wait_answer",
            f"answer-{answered}",
            {"value": answers[answered]},
            600.0,
        )
        engine.store.resolve_human_wait_controls()
        dispatch_ready_nodes(engine.store, run_id, engine.tokens.append)
        engine.drain(run_id)
        answered += 1
    failures = list(
        NodeAttempt.objects.filter(node_run__run_id=run_id, error_code__isnull=False).values_list(
            "node_run__scope_path", "error_code"
        )
    )
    diagnostics = {
        "failure_summary": Run.objects.get(pk=run_id).failure_summary,
        "errors": list(
            RunEvent.objects.filter(run_id=run_id, type="error").values("type", "payload")
        ),
        "failed_attempts": [
            event.payload
            for event in RunEvent.objects.filter(run_id=run_id, type="attempt.ended")
            if isinstance(event.payload, dict) and event.payload.get("error_code")
        ],
    }
    assert run_status(run_id) == status, diagnostics
    if status == "failed":
        if audit_next:
            expected_failure = (
                "root.tests.step_1.iteration_1.cycle.step_3",
                "workflow_validation_error",
            )
        else:
            phase = "refine_plan" if plan_ready > 3 else "review" if review_ready > 3 else "tests"
            expected_failure = (f"root.{phase}.step_1", "loop_exhausted")
        # An unrelated earlier failure must expose its cause before counter assertions.
        assert expected_failure in failures, diagnostics
    assert (counters / "plan").is_file(), diagnostics
    assert int((counters / "plan").read_text()) == min(plan_ready, 3)
    if plan_ready <= 3:
        assert (counters / "review").is_file(), diagnostics
        assert int((counters / "review").read_text()) == min(review_ready, 3)
    if plan_ready <= 3 and review_ready <= 3:
        assert (counters / "audit").is_file(), diagnostics
        assert int((counters / "audit").read_text()) == (1 if audit_next else min(audit_ready, 3))
    turns = [
        message["params"]["prompt"]
        for message in fake_agents.messages()
        if message.get("method") == "session/prompt"
    ]
    prompts = [turn[0]["text"] for turn in turns]
    assert "PLAN\r\n" + AI_HANDOFF in prompts
    if plan_ready <= 3:
        assert "IMPLEMENT\r\n" + AI_HANDOFF in prompts
        assert "FIX\r\n" + AI_HANDOFF in prompts
    # The task is supplied once, apart from the phase files and Relay metadata.
    assert sum(block.get("text") == "Add dark mode" for turn in turns for block in turn) == 1
    if status == "succeeded":
        assert answered == 3
        worktree = Path(Run.objects.get(pk=run_id).worktree_path)
        assert ("FOLLOWUP = True" in (worktree / "feature.py").read_text()) == (
            decision == "FOLLOWUP"
        )
