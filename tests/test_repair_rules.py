"""Native repair policies preserve rejection evidence and gate downstream work."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path

from django.db import connections
import pytest
from ruamel.yaml import YAML

from relay.errors import WorkflowValidationError
from relay.execution.control import ControlResult
from relay.execution.nodes import node_executors
from relay.execution.runner import AttemptContext, ExecutionOutcome, OutcomeKind
from relay.execution.scheduler import dispatch_ready_nodes
from relay.web.models import Artifact, AutomaticRetry, NodeAttempt, NodeRun, RunSnapshot
from relay.web.repositories import DjangoReadStore
from relay.workflows.graph import compile_graph
from relay.workflows.loader import load_workflow_text
from relay.workflows.repairs import accepted_verdict
from relay.workflows.schema import AgentNode, Scalar
from tests.support import (
    PYTHON,
    FakeAgents,
    InlineEngine,
    RelayProject,
    git,
    run_status,
)


def repair_workflow(*, accepted: bool = False, rounds: int = 2, passes_at: int = 1) -> str:
    """Command boundaries produce real retained reports and committed repairs."""
    initial = "Yes" if accepted else "No"
    review = json.dumps(
        "from pathlib import Path; Path('REVIEW.md').write_text('Ready: " + initial + "\\n')"
    )
    fix = (
        "from pathlib import Path; import subprocess; p=Path('round.txt'); "
        "n=int(p.read_text())+1 if p.exists() else 1; p.write_text(str(n)); "
        "subprocess.run(['git','add','round.txt'],check=True); "
        "subprocess.run(['git','commit','-qm','Repair'],check=True)"
    )
    verify = (
        "from pathlib import Path; "
        f"ready='Yes' if int(Path('round.txt').read_text())>={passes_at} else 'No'; "
        "Path('REVIEW_FIX_VERIFICATION.md').write_text('Ready: '+ready+'\\n')"
    )
    return f"""version: 1
name: Native repairs
nodes:
  review:
    type: command
    writes: true
    allow_no_commit: true
    run: ["{PYTHON}", -c, {review}]
    outputs:
      ready: {{label: {{artifact: REVIEW.md, label: Ready}}}}
  deliver:
    type: command
    needs: [review]
    if: "${{{{ needs.review.outputs.ready == 'Yes' }}}}"
    run: [git, status]
repairs:
  review:
    max_rounds: {rounds}
    accepted_output: ready
    accepted_value: 'Yes'
    fix:
      type: command
      writes: true
      run: ["{PYTHON}", -c, {json.dumps(fix)}]
    verify:
      type: command
      writes: true
      allow_no_commit: true
      run: ["{PYTHON}", -c, {json.dumps(verify)}]
      outputs:
        ready: {{label: {{artifact: REVIEW_FIX_VERIFICATION.md, label: Ready}}}}
"""


def test_initial_acceptance_skips_fixers(project: RelayProject, engine: InlineEngine) -> None:
    project.write_workflow("repair", repair_workflow(accepted=True))
    run_id = engine.launch(project, "repair")
    engine.drain(run_id)

    assert run_status(run_id) == "succeeded"
    assert not NodeAttempt.objects.filter(node_run__scope_path__endswith=".fix").exists()
    assert NodeRun.objects.get(run_id=run_id, scope_path="root.deliver").status == "succeeded"


def test_repairs_publish_accepted_outputs_without_rewriting_the_rejection(
    project: RelayProject, engine: InlineEngine
) -> None:
    source = repair_workflow(passes_at=2)
    project.write_workflow("repair", source)
    run_id = engine.launch(project, "repair")
    engine.drain(run_id)

    assert run_status(run_id) == "succeeded"
    review = NodeRun.objects.get(run_id=run_id, scope_path="root.review")
    assert review.outputs == {"ready": "No"}
    assert NodeRun.objects.get(run_id=run_id, scope_path="root.deliver").status == "succeeded"
    assert NodeRun.objects.get(run_id=run_id, scope_path="root.relay_repair_review").outputs == {
        "ready": "Yes"
    }
    verified = NodeRun.objects.filter(run_id=run_id, scope_path__endswith=".verify").order_by(
        "loop_index"
    )
    assert [node.outputs for node in verified] == [{"ready": "No"}, {"ready": "Yes"}]
    reports = Artifact.objects.filter(attempt__node_run__run_id=run_id, declared_name="ready")
    assert reports.count() == 3
    contents = [Path(str(a.retained_path)).read_text() for a in reports]
    assert contents.count("Ready: No\n") == 2
    assert contents.count("Ready: Yes\n") == 1
    assert RunSnapshot.objects.get(run_id=run_id).workflow_yaml == source


def test_exhaustion_stops_work_with_the_last_rejection(
    project: RelayProject, engine: InlineEngine
) -> None:
    project.write_workflow("repair", repair_workflow(rounds=2, passes_at=3))
    run_id = engine.launch(project, "repair")
    engine.drain(run_id)

    assert run_status(run_id) == "failed"
    coordinator = NodeRun.objects.get(run_id=run_id, scope_path="root.relay_repair_review")
    assert NodeAttempt.objects.get(node_run=coordinator).error_code == "repair_exhausted"
    assert NodeAttempt.objects.filter(node_run__scope_path__endswith=".fix").count() == 2
    assert not NodeAttempt.objects.filter(node_run__scope_path="root.deliver").exists()


def test_disabled_repairs_leave_the_original_stage_behavior(
    project: RelayProject, engine: InlineEngine
) -> None:
    source = repair_workflow().replace("    max_rounds: 2", "    enabled: false\n    max_rounds: 2")
    project.write_workflow("repair", source)
    run_id = engine.launch(project, "repair")
    engine.drain(run_id)

    assert run_status(run_id) == "succeeded"
    assert not NodeRun.objects.filter(run_id=run_id, node_id="relay_repair_review").exists()
    assert NodeRun.objects.get(run_id=run_id, scope_path="root.deliver").status == "skipped"


@pytest.mark.parametrize(
    ("outputs", "expected", "accepted"),
    [
        ({"ready": True}, 1, False),
        ({"ready": 1}, True, False),
        ({}, None, False),
        ({"ready": "Yes"}, "yes", False),
        ({"ready": True}, True, True),
        ({"ready": 1.0}, 1, True),
        ({"ready": 1}, 1.0, True),
        ({"ready": True}, 1.0, False),
    ],
)
def test_acceptance_preserves_the_verdict_type(
    outputs: dict[str, object], expected: Scalar, accepted: bool
) -> None:
    assert accepted_verdict(outputs, "ready", expected) is accepted


@pytest.mark.parametrize(
    "mutation",
    ["unknown_source", "unknown_output", "uncontrolled_role", "collision", "forged_marker"],
)
def test_invalid_repair_policies_fail_before_launch(mutation: str) -> None:
    document = YAML(typ="safe").load(repair_workflow())
    rule = document["repairs"]["review"]
    if mutation == "unknown_source":
        document["repairs"]["missing"] = document["repairs"].pop("review")
    elif mutation == "unknown_output":
        rule["accepted_output"] = "absent"
    elif mutation == "uncontrolled_role":
        rule["fix"]["needs"] = ["deliver"]
    elif mutation == "collision":
        document["nodes"]["relay_repair_review"] = {"type": "command", "run": ["git", "status"]}
    else:
        document["nodes"]["forged"] = {
            "type": "loop",
            "body": {"x": {"type": "command", "run": ["git", "status"]}},
            "max_iterations": 1,
            "exhausted": "deliver",
            "repair_rule": {
                "source": "review",
                "accepted_output": "ready",
                "accepted_value": "Yes",
                "fix_instruction": "fix",
                "verify_instruction": "verify",
            },
        }

    with pytest.raises(WorkflowValidationError):
        load_workflow_text(json.dumps(document))


def test_compilation_keeps_portable_source_and_gates_dependents() -> None:
    source = repair_workflow()
    loaded = load_workflow_text(source)
    graph = compile_graph(loaded.definition.nodes)

    assert loaded.text == source
    assert set(loaded.document["nodes"]) == {"review", "deliver"}
    assert graph.dependencies["deliver"] == ("review", "relay_repair_review")
    assert graph.control_downstream["relay_repair_review"] == ()


def test_repairs_inside_a_subworkflow_export_the_accepted_result(
    project: RelayProject, engine: InlineEngine
) -> None:
    project.write_workflow("child", repair_workflow())
    project.write_workflow(
        "parent",
        """version: 1
name: Parent
nodes:
  child:
    type: subworkflow
    workflow: child
    outputs: {ready: review.ready}
  deliver:
    type: command
    needs: [child]
    if: "${{ needs.child.outputs.ready == 'Yes' }}"
    run: [git, status]
""",
    )
    run_id = engine.launch(project, "parent")
    engine.drain(run_id)

    assert run_status(run_id) == "succeeded"
    assert NodeRun.objects.get(run_id=run_id, scope_path="root.child.review").outputs == {
        "ready": "No"
    }
    assert NodeRun.objects.get(run_id=run_id, scope_path="root.child").outputs == {"ready": "Yes"}
    assert NodeRun.objects.get(run_id=run_id, scope_path="root.deliver").status == "succeeded"


@dataclass
class RepairProvider:
    """External provider stand-in, with a real committed fix and retained reports."""

    pause_after_fix: bool = False
    fail_verifier_once: bool = False
    calls: list[AttemptContext] = field(default_factory=list)

    def execute(self, context: AttemptContext, node: AgentNode) -> ExecutionOutcome:
        del node
        self.calls.append(context)
        scope = context.attempt.scope_path
        if scope == "root.review":
            (context.worktree / "REVIEW.md").write_text("Ready: No\n", encoding="utf-8")
        elif scope.endswith(".fix"):
            (context.worktree / "fixed.txt").write_text("Repair complete\n", encoding="utf-8")
            git(context.worktree, "add", "fixed.txt")
            git(context.worktree, "commit", "-qm", "Repair finding")
            if self.pause_after_fix:
                context.runtime.configure_dispatch_pause(context.attempt.run_id, True, "pause-fix")
        else:
            if self.fail_verifier_once:
                self.fail_verifier_once = False
                return ExecutionOutcome(OutcomeKind.FAILED, error_code="agent_protocol_error")
            (context.worktree / "REVIEW_FIX_VERIFICATION.md").write_text(
                "Ready: Yes\n", encoding="utf-8"
            )
        return ExecutionOutcome(OutcomeKind.SUCCEEDED)


def agent_repair_workflow(project: RelayProject) -> str:
    document = YAML(typ="safe").load(repair_workflow())
    document.update(model="m2", agents=["codex"], recovery={"enabled": True})
    for role, target in (
        ("review", document["nodes"]),
        ("fix", document["repairs"]["review"]),
        ("verify", document["repairs"]["review"]),
    ):
        outputs = target[role].get("outputs", {})
        target[role] = {
            "type": "agent",
            "writes": True,
            "allow_no_commit": True,
            "outputs": outputs,
            "prompts": [{"local": "prompts/original.txt"}],
            "agent_options": {"codex": {"effort": "low", "permission_mode": "auto"}},
        }
    project.write(".relay/prompts/original.txt", "Original scope and checks.\n")
    return json.dumps(document)


@pytest.mark.usefixtures("registry_network")
def test_pause_mid_repair_keeps_prompts_routes_reports_and_attempts(
    project: RelayProject, engine: InlineEngine, fake_agents: FakeAgents
) -> None:
    fake_agents.install("codex", mode="configuration")
    provider = RepairProvider(pause_after_fix=True)
    engine.executors = node_executors(agent_driver=provider)
    project.write_workflow("repair", agent_repair_workflow(project))
    run_id = engine.launch(project, "repair")
    captured = RunSnapshot.objects.get(run_id=run_id)
    frozen = (captured.hashes, captured.resolved_prompts, captured.route_table)
    engine.drain(run_id)
    coordinator = NodeRun.objects.get(run_id=run_id, scope_path="root.relay_repair_review")
    assert coordinator.status == "waiting"
    assert not NodeAttempt.objects.filter(node_run__scope_path__endswith=".verify").exists()
    connections.close_all()
    assert engine.store.configure_dispatch_pause(run_id, False, "resume") is ControlResult.ACCEPTED
    engine.tokens.extend(engine.store.pending_dispatch_tokens(run_id))
    dispatch_ready_nodes(engine.store, run_id, engine.tokens.append)
    engine.drain(run_id)

    assert run_status(run_id) == "succeeded"
    assert NodeAttempt.objects.filter(node_run=coordinator).count() == 1
    assert NodeAttempt.objects.filter(node_run__scope_path__endswith=".fix").count() == 1
    review, fix, verify = [call.attempt for call in provider.calls]
    assert fix.prompt_contents[0] == review.prompt_contents[0] == "Original scope and checks.\n"
    assert fix.run_metadata["repair"]["rejected_outputs"] == {"ready": "No"}
    assert fix.prompt_contents[-1].startswith(
        coordinator.frozen_def["repair_rule"]["fix_instruction"]
    )
    assert verify.prompt_contents[-1].startswith(
        coordinator.frozen_def["repair_rule"]["verify_instruction"]
    )
    assert all(
        a.route["effort"] == "low" and a.route["permission_mode"] == "auto"
        for a in (review, fix, verify)
    )
    saved = RunSnapshot.objects.get(run_id=run_id)
    assert (saved.hashes, saved.resolved_prompts, saved.route_table) == frozen


@pytest.mark.usefixtures("registry_network")
def test_provider_recovery_resumes_the_same_repair_round(
    project: RelayProject, engine: InlineEngine, fake_agents: FakeAgents
) -> None:
    fake_agents.install("codex", mode="configuration")
    provider = RepairProvider(fail_verifier_once=True)
    engine.executors = node_executors(agent_driver=provider)
    project.write_workflow("repair", agent_repair_workflow(project))
    run_id = engine.launch(project, "repair")
    engine.drain(run_id)
    assert run_status(run_id) == "failed"
    connections.close_all()
    assert engine.store.resume_automatic_retries() == 1
    dispatch_ready_nodes(engine.store, run_id, engine.tokens.append)
    engine.drain(run_id)

    assert run_status(run_id) == "succeeded"
    assert NodeAttempt.objects.filter(node_run__scope_path__endswith=".fix").count() == 1
    assert NodeAttempt.objects.filter(node_run__scope_path__endswith=".verify").count() == 2
    assert NodeRun.objects.filter(run_id=run_id, scope_path__contains="#2").count() == 0
    assert AutomaticRetry.objects.get().state == "resumed"


def test_repair_budget_exhaustion_never_schedules_an_automatic_retry(
    project: RelayProject, engine: InlineEngine
) -> None:
    source = repair_workflow(rounds=1, passes_at=2).replace(
        "nodes:\n", "recovery: {enabled: true}\nnodes:\n", 1
    )
    project.write_workflow("repair", source)
    run_id = engine.launch(project, "repair")
    engine.drain(run_id)
    assert run_status(run_id) == "failed"
    assert not AutomaticRetry.objects.filter(
        state__in=("scheduled", "preparing", "resumed")
    ).exists()
    assert engine.store.resume_automatic_retries() == 0


def test_native_repair_metadata_is_explicit_in_run_pages(
    project: RelayProject, engine: InlineEngine
) -> None:
    project.write_workflow("repair", repair_workflow())
    run_id = engine.launch(project, "repair")
    engine.drain(run_id)
    page, _ = DjangoReadStore().run_detail(run_id, collection="nodes", since=0, limit=200)
    rows = {n["scope_path"]: n for n in page["nodes"]}
    settings = rows["root.relay_repair_review"]["repair_settings"]
    assert rows["root.relay_repair_review"]["repair_for"] == "root.review"
    assert settings["legacy"] is False
    assert settings["max_rounds"] == 2
    assert settings["accepted_output"] == "ready"
    assert settings["accepted_value"] == "Yes"
    assert rows["root.review"]["repair_for"] is None


@pytest.mark.parametrize(
    "groups",
    [
        {"root.deliver": "root.review"},
        {"root.relay_repair_review": "root.review"},
        {"root.review": "root.review"},
        {"root.absent": "root.review"},
    ],
)
def test_repair_classification_cannot_hide_an_arbitrary_or_native_stage(
    project: RelayProject, engine: InlineEngine, groups: dict[str, str]
) -> None:
    project.write_workflow("repair", repair_workflow())
    run_id = engine.launch(project, "repair")
    engine.store.configure_dispatch_pause(run_id, True, "pause")
    assert (
        engine.store.configure_repair_groups(run_id, groups, "bad-group") is ControlResult.INVALID
    )
