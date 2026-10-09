"""Shared jobs, frozen calls, approvals, timeouts, and bounded recovery."""

from datetime import timedelta
import json
from pathlib import Path
import time

from django.utils import timezone
import pytest

from relay.execution.nodes import node_executors
from relay.execution.nodes.actions import ActionsJobExecutor, ActionsStepExecutor
from relay.execution.runner import AttemptContext, ExecutionOutcome, OutcomeKind
from relay.web.actions_bindings import put_binding
from relay.web.actions_repository import approve_environment
from relay.web.models import (
    Artifact,
    AutomaticRetry,
    HumanInteraction,
    NodeAttempt,
    NodeRun,
    Run,
    RunEvent,
    WorkflowEnvironment,
)
from relay.workflows.schema import AgentNode
from tests.support import FakeAgents, InlineEngine, RelayProject, answer_wait


def test_human_answer_is_a_step_output_and_restart_does_not_repeat_edits(
    project: RelayProject, tmp_path: Path
) -> None:
    project.write_workflow(
        "wait",
        "defaults: {run: {shell: bash}}\n"
        + """on: workflow_dispatch
jobs:
  main:
    steps:
      - id: first
        run: echo 'value=once' >> "$RELAY_OUTPUT"
      - id: approval
        uses: relay/human-wait@v1
        with:
          prompt: "Continue after ${{ steps.first.outputs.value }}?"
          options: '["go", "stop"]'
      - run: test '${{ steps.approval.outputs.answer }}' = go
""",
    )
    engine = InlineEngine(node_executors(), tmp_path / "artifacts")
    run_id = engine.launch(project, "wait")
    engine.drain(run_id)
    interaction = HumanInteraction.objects.get(run_id=run_id, status="pending")
    assert interaction.request_payload["prompt"] == "Continue after once?"
    assert interaction.request_payload["options"] == ["go", "stop"]
    assert interaction.request_payload["deadline_source"] == "default job timeout"
    NodeAttempt.objects.filter(node_run__run_id=run_id).update(
        heartbeat_at=timezone.now() - timedelta(days=1)
    )
    assert engine.store.reap_stale_attempts(orderly_shutdown=False).worker_lost == 0
    assert answer_wait(engine, run_id) == "accepted"
    assert Run.objects.get(pk=run_id).status == "succeeded"
    assert (
        NodeAttempt.objects.filter(
            node_run__scope_path="root.main.first", node_run__run_id=run_id
        ).count()
        == 1
    )


def test_environment_approval_precedes_secret_lookup_and_rejects_generic_answers(
    project: RelayProject, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    WorkflowEnvironment.objects.create(
        project_id=project.project_id, name="prod", approval_required=True
    )
    put_binding(
        f"environment:{project.project_id}:prod",
        "KEY",
        "secret",
        source="environment",
        reference="RELAY_GATED_TEST_KEY",
    )
    monkeypatch.delenv("RELAY_GATED_TEST_KEY", raising=False)
    project.write_workflow(
        "gate",
        "defaults: {run: {shell: bash}}\n"
        + """on: workflow_dispatch
jobs:
  main:
    environment: prod
    env: {KEY: '${{ secrets.KEY }}'}
    steps:
      - run: test "$KEY" = gated
""",
    )
    engine = InlineEngine(node_executors(), tmp_path / "artifacts")
    run_id = engine.launch(project, "gate")
    engine.drain(run_id)
    interaction = HumanInteraction.objects.get(run_id=run_id, status="pending")
    result = engine.store.submit_control(
        str(interaction.attempt_id), "wait_answer", "cannot-bypass", {"value": "yes"}, 600
    )
    assert result.value == "invalid"
    monkeypatch.setenv("RELAY_GATED_TEST_KEY", "gated")
    assert approve_environment(str(interaction.attempt_id))
    engine.drain(run_id)
    assert Run.objects.get(pk=run_id).status == "succeeded"
    assert not approve_environment(str(interaction.attempt_id))


def test_reusable_secret_contract_and_environment_precedence(
    project: RelayProject, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    WorkflowEnvironment.objects.create(project_id=project.project_id, name="prod")
    for scope, variable, value in [
        ("installation", "RELAY_TEST_BASE", "base"),
        (f"project:{project.project_id}", "RELAY_TEST_PROJECT", "project"),
        (f"environment:{project.project_id}:prod", "RELAY_TEST_ENV", "environment"),
    ]:
        monkeypatch.setenv(variable, value)
        put_binding(scope, "KEY", "secret", source="environment", reference=variable)
    project.write_workflow(
        "callee",
        "defaults: {run: {shell: bash}}\n"
        + """on:
  workflow_call:
    secrets: {RENAMED: {required: true}}
jobs:
  main:
    environment: prod
    env:
      RENAMED: ${{ secrets.RENAMED }}
      KEY: ${{ secrets.KEY }}
    steps:
      - run: test "$RENAMED" = project && test "$KEY" = environment
""",
    )
    project.write_workflow(
        "caller",
        "defaults: {run: {shell: bash}}\n"
        + """on: workflow_dispatch
jobs:
  call:
    uses: ./.relay/workflows/callee.yaml
    secrets: {RENAMED: '${{ secrets.KEY }}'}
""",
    )
    engine = InlineEngine(node_executors(), tmp_path / "artifacts")
    run_id = engine.launch(project, "caller")
    engine.drain(run_id)
    assert Run.objects.get(pk=run_id).status == "succeeded"
    assert "environment" not in json.dumps(
        list(
            RunEvent.objects.filter(run_id=run_id, source="command").values_list(
                "payload", flat=True
            )
        )
    )


def test_reusable_call_does_not_implicitly_inherit_secrets(
    project: RelayProject, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RELAY_UNPASSED", "private")
    put_binding(
        f"project:{project.project_id}",
        "HIDDEN",
        "secret",
        source="environment",
        reference="RELAY_UNPASSED",
    )
    project.write_workflow(
        "callee",
        "defaults: {run: {shell: bash}}\n"
        + """on: workflow_call
jobs:
  main:
    steps: [{run: "test '${{ secrets.HIDDEN }}' = ''"}]
""",
    )
    project.write_workflow(
        "caller",
        "defaults: {run: {shell: bash}}\n"
        + """on: workflow_dispatch
jobs: {call: {uses: ./.relay/workflows/callee.yaml}}
""",
    )
    engine = InlineEngine(node_executors(), tmp_path / "artifacts")
    run_id = engine.launch(project, "caller")
    engine.drain(run_id)
    assert Run.objects.get(pk=run_id).status == "succeeded"


def test_failed_job_retains_bytes_and_next_job_uses_last_accepted_commit(
    project: RelayProject, tmp_path: Path
) -> None:
    project.write_workflow(
        "continuation",
        "defaults: {run: {shell: bash}}\n"
        + """on: workflow_dispatch
jobs:
  accepted:
    steps:
      - run: echo accepted > accepted.txt; git add accepted.txt; git commit -m accepted
  rejected:
    steps:
      - run: echo rejected > rejected.txt; exit 1
  followup:
    steps:
      - run: test -f accepted.txt && test ! -f rejected.txt
""",
    )
    engine = InlineEngine(node_executors(), tmp_path / "artifacts")
    run_id = engine.launch(project, "continuation")
    engine.drain(run_id)
    run = Run.objects.get(pk=run_id)
    assert run.status == "failed"
    assert NodeRun.objects.get(run_id=run_id, scope_path="root.followup").status == "succeeded"
    retained = Path(run.actions_state["continuations"][0])
    assert (retained / "rejected.txt").read_text().strip() == "rejected"
    assert not (Path(run.worktree_path) / "rejected.txt").exists()


@pytest.mark.parametrize("expired_before_execution", [False, True])
@pytest.mark.parametrize("continued", [False, True])
def test_step_timeout_persists_and_failure_followup_runs(
    project: RelayProject,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    expired_before_execution: bool,
    continued: bool,
) -> None:
    from relay.execution import runner

    if expired_before_execution:
        original = runner.attempt_deadline

        def expired_deadline(timeout: str | None, inherited: float | None) -> float | None:
            return time.monotonic() - 1 if timeout == "60ms" else original(timeout, inherited)

        monkeypatch.setattr(runner, "attempt_deadline", expired_deadline)
    project.write_workflow(
        "timeout",
        "defaults: {run: {shell: bash}}\n"
        + f"""on: workflow_dispatch
jobs:
  main:
    steps:
      - id: slow
        timeout-minutes: 0.001
        continue-on-error: {str(continued).lower()}
        shell: python
        run: import time; time.sleep(2)
      - if: steps.slow.outcome == 'failure' && (failure() || steps.slow.conclusion == 'success')
        run: echo cleanup
""",
    )
    engine = InlineEngine(node_executors(), tmp_path / "artifacts")
    run_id = engine.launch(project, "timeout")
    engine.drain(run_id)
    attempt = NodeAttempt.objects.get(
        node_run__run_id=run_id, node_run__scope_path="root.main.slow"
    )
    assert attempt.stop_reason == "timeout" and attempt.deadline_at is not None
    assert attempt.node_run.outcome == "failure"
    assert attempt.node_run.conclusion == ("success" if continued else "failure")
    assert NodeRun.objects.get(run_id=run_id, scope_path="root.main.step_2").status == "succeeded"
    assert Run.objects.get(pk=run_id).status == ("succeeded" if continued else "failed")


@pytest.mark.parametrize("integrity_failure", [False, True])
def test_cache_filesystem_warnings_preserve_integrity_failures(
    integrity_failure: bool,
    project: RelayProject,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from relay.errors import NodeExecutionError

    def fail_restore(*_args: object) -> None:
        if integrity_failure:
            message = "Retained cache changed."
            raise NodeExecutionError(message)
        message = "Temporary cache filesystem error."
        raise OSError(message)

    monkeypatch.setattr("relay.web.actions_products.restore", fail_restore)
    project.write_workflow(
        "cache-fault",
        "defaults: {run: {shell: bash}}\n" + "jobs:\n  seed:\n    steps:\n"
        "      - run: echo memo > memo.txt\n"
        "      - uses: relay/save-cache@v1\n        with: {key: local, path: memo.txt}\n"
        "  restored:\n    cache-mode: read\n    steps:\n"
        "      - id: cache\n        uses: relay/restore-cache@v1\n"
        "        with: {key: local, path: memo.txt}\n"
        "      - run: test '${{ steps.cache.outputs.cache-hit }}' = false\n",
    )
    engine = InlineEngine(node_executors(), tmp_path / "artifacts")
    run_id = engine.launch(project, "cache-fault")
    engine.drain(run_id)
    assert Run.objects.get(pk=run_id).status == ("failed" if integrity_failure else "succeeded")
    assert RunEvent.objects.filter(run_id=run_id, type="actions.warning").exists() is (
        not integrity_failure
    )


def test_workspace_continuation_resumes_after_a_crash_between_move_and_recreation(
    project: RelayProject, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from relay.errors import GitError
    from relay.web import actions_repository
    from tests.support import git

    project.write_workflow(
        "journal",
        "defaults: {run: {shell: bash}}\n" + "jobs:\n  accepted:\n"
        "    steps: [{run: echo accepted > accepted.txt}]\n"
        "  rejected:\n"
        "    steps: [{run: 'echo rejected > rejected.txt; exit 1'}]\n",
    )
    engine = InlineEngine(node_executors(), tmp_path / "artifacts")
    run_id = engine.launch(project, "journal")
    engine.drain(run_id)
    run = Run.objects.get(pk=run_id)
    assert run.status == "failed"
    original = actions_repository.run_git
    interrupted = False

    def crash_on_recreation(root: Path, argv: list[str], **kwargs: object) -> object:
        nonlocal interrupted
        if argv[:2] == ["worktree", "add"] and not interrupted:
            interrupted = True
            message = "Injected loss before workspace recreation."
            raise GitError(message)
        return original(root, argv, **kwargs)

    monkeypatch.setattr(actions_repository, "run_git", crash_on_recreation)
    with pytest.raises(GitError):
        actions_repository.prepare_job_workspace(run_id)
    run.refresh_from_db()
    retained = Path(run.actions_state["continuation_journal"]["retained"])
    assert (retained / "rejected.txt").read_text().strip() == "rejected"
    assert not Path(run.worktree_path).exists()
    actions_repository.prepare_job_workspace(run_id)
    actions_repository.prepare_job_workspace(run_id)
    run.refresh_from_db()
    assert run.actions_state["continuations"] == [str(retained)]
    assert "continuation_journal" not in run.actions_state
    assert git(Path(run.worktree_path), "rev-parse", "HEAD") == run.recorded_head
    assert (Path(run.worktree_path) / "accepted.txt").read_text().strip() == "accepted"
    assert not (Path(run.worktree_path) / "rejected.txt").exists()


def test_local_composite_source_is_frozen_before_owner_edits(
    project: RelayProject, tmp_path: Path
) -> None:
    action = project.relay_root / "actions" / "echo"
    action.mkdir(parents=True)
    source = """name: Frozen
description: Output the frozen value
inputs:
  value: {description: Frozen input, default: frozen}
outputs:
  value: {description: Frozen output, value: '${{ steps.output.outputs.value }}'}
runs:
  using: composite
  steps:
    - id: output
      shell: python
      env: {VALUE: '${{ inputs.value }}'}
      run: |
        import os
        with open(os.environ['RELAY_OUTPUT'], 'a') as stream:
            stream.write('value=' + os.environ['VALUE'] + '\\n')
"""
    (action / "action.yml").write_text(source, encoding="utf-8")
    project.write_workflow(
        "composite",
        "defaults: {run: {shell: bash}}\n"
        + """on: workflow_dispatch
jobs:
  main:
    outputs: {value: '${{ steps.local.outputs.value }}'}
    steps: [{id: local, uses: ./.relay/actions/echo}]
""",
    )
    engine = InlineEngine(node_executors(), tmp_path / "artifacts")
    run_id = engine.launch(project, "composite")
    (action / "action.yml").write_text(
        source.replace("default: frozen", "default: changed"), encoding="utf-8"
    )
    engine.drain(run_id)
    assert NodeRun.objects.get(run_id=run_id, scope_path="root.main").outputs == {"value": "frozen"}


class RepairDriver:
    prompts: list[tuple[str, ...]]

    def __init__(self) -> None:
        self.prompts = []

    def execute(self, context: AttemptContext, _node: AgentNode) -> ExecutionOutcome:
        self.prompts.append(context.attempt.prompt_contents)
        (context.worktree / "REVIEW.md").write_text(
            "invalid report\n" if len(self.prompts) == 1 else "Ready: yes\n", encoding="utf-8"
        )
        return ExecutionOutcome(OutcomeKind.SUCCEEDED)


def test_bounded_agent_retry_preserves_rejected_report_and_frozen_prompt(
    project: RelayProject, tmp_path: Path, fake_agents: FakeAgents
) -> None:
    fake_agents.install("codex")
    project.write_workflow(
        "repair",
        "defaults: {run: {shell: bash}}\n"
        + """on: workflow_dispatch
jobs:
  main:
    steps:
      - id: review
        uses: relay/agent@v1
        with:
          agents: '["codex"]'
          model: m1
          prompt: Review this repository
          report: REVIEW.md
          label: Ready
          auto-retry: true
""",
    )
    driver = RepairDriver()
    engine = InlineEngine(
        {"actions_job": ActionsJobExecutor(driver), "actions_step": ActionsStepExecutor(driver)},
        tmp_path / "artifacts",
    )
    run_id = engine.launch(project, "repair")
    engine.drain(run_id)
    assert Run.objects.get(pk=run_id).status == "succeeded"
    assert len(driver.prompts) == 2
    assert driver.prompts[0][-1] == "Review this repository"
    assert "Failed step:" in driver.prompts[1][0]
    assert AutomaticRetry.objects.get(attempt__node_run__run_id=run_id).state == "resumed"
    reports = list(
        Artifact.objects.filter(
            attempt__node_run__run_id=run_id, declared_name="report"
        ).values_list("retained_path", flat=True)
    )
    assert any(Path(path).read_text() == "invalid report\n" for path in reports)


def test_job_cancellation_settles_run_and_allows_unrelated_jobs(
    project: RelayProject, tmp_path: Path
) -> None:
    from relay.web.actions_automation import cancel_queue_owner

    project.write_workflow(
        "cancel-job",
        "defaults: {run: {shell: bash}}\n"
        + """on: workflow_dispatch
jobs:
  accepted:
    steps: [{run: echo accepted > accepted.txt}]
  canceled:
    steps:
      - run: echo rejected > rejected.txt
      - uses: relay/human-wait@v1
        with: {prompt: Continue?}
      - run: echo should-not-run
  unrelated:
    steps: [{run: test -f accepted.txt && test ! -f rejected.txt}]
""",
    )
    engine = InlineEngine(node_executors(), tmp_path / "artifacts")
    run_id = engine.launch(project, "cancel-job")
    engine.drain(run_id)
    cancel_queue_owner(run_id, "root.canceled", "job-cancellation-test")
    engine.store.resolve_human_wait_controls()
    engine.drain(run_id)
    assert Run.objects.get(pk=run_id).status == "canceled"
    assert NodeRun.objects.get(run_id=run_id, scope_path="root.unrelated").status == "succeeded"
    assert (
        not NodeRun.objects.filter(run_id=run_id)
        .exclude(status__in=("succeeded", "failed", "canceled", "skipped"))
        .exists()
    )
    assert (
        NodeRun.objects.get(run_id=run_id, scope_path="root.canceled.step_2").outcome == "cancelled"
    )
    run = Run.objects.get(pk=run_id)
    retained = Path(run.actions_state["continuations"][0])
    assert (retained / "rejected.txt").read_text().strip() == "rejected"


def test_expired_human_step_exposes_failure_to_followup(
    project: RelayProject, tmp_path: Path
) -> None:
    project.write_workflow(
        "expire-step",
        "defaults: {run: {shell: bash}}\n"
        + """on: workflow_dispatch
jobs:
  main:
    steps:
      - id: approval
        uses: relay/human-wait@v1
        with: {prompt: Continue?, timeout-minutes: 1}
      - id: followup
        if: failure()
        run: echo '${{ steps.approval.outcome }}' | grep failure
""",
    )
    engine = InlineEngine(node_executors(), tmp_path / "artifacts")
    run_id = engine.launch(project, "expire-step")
    engine.drain(run_id)
    HumanInteraction.objects.filter(run_id=run_id, status="pending").update(
        deadline=timezone.now() - timedelta(seconds=1)
    )
    assert engine.store.expire_human_waits() == 1
    engine.drain(run_id)
    assert NodeRun.objects.get(run_id=run_id, scope_path="root.main.followup").status == "succeeded"
    assert Run.objects.get(pk=run_id).status == "failed"


def test_successful_job_commits_once_after_edits_and_keeps_reports_unstaged(
    project: RelayProject, tmp_path: Path
) -> None:
    from tests.support import git

    project.write_workflow(
        "automatic-checkpoint",
        "defaults: {run: {shell: bash}}\n"
        + """jobs:
  main:
    steps:
      - run: echo first > code.txt
      - run: |
          echo second >> code.txt && echo 'Ready: Yes' > REVIEW.md
      - run: |
          test "$(git log -1 --format=%s)" != 'Relay: complete job main'
""",
    )
    engine = InlineEngine(node_executors(), tmp_path / "artifacts")
    run_id = engine.launch(project, "automatic-checkpoint")
    engine.drain(run_id)
    run = Run.objects.get(pk=run_id)
    assert run.status == "succeeded"
    from relay.paths import safe_resolve, worktrees_dir

    workspace = safe_resolve(worktrees_dir(), run.worktree_path)
    assert git(workspace, "log", "-1", "--format=%s") == "Relay: complete job main"
    assert git(workspace, "show", "HEAD:code.txt") == "first\nsecond"
    assert git(workspace, "status", "--porcelain=v1") == "?? REVIEW.md"
    assert git(workspace, "rev-list", "--count", f"{run.source_commit}..HEAD") == "1"


def test_environment_url_resolves_after_steps_and_omits_secrets(
    project: RelayProject, tmp_path: Path
) -> None:
    from relay.execution.masking import redactor
    from relay.web.actions_repository import publish_environment

    WorkflowEnvironment.objects.create(project_id=project.project_id, name="preview")
    project.write_workflow(
        "environment-link",
        "defaults: {run: {shell: bash}}\n"
        + """jobs:
  deploy:
    environment:
      name: preview
      url: ${{ steps.deployment.outputs.url }}
    steps:
      - id: deployment
        run: echo 'url=https://preview.example.test/build' >> "$RELAY_OUTPUT"
""",
    )
    engine = InlineEngine(node_executors(), tmp_path / "artifacts")
    run_id = engine.launch(project, "environment-link")
    engine.drain(run_id)
    run = Run.objects.get(pk=run_id)
    assert run.status == "succeeded", list(
        RunEvent.objects.filter(run_id=run_id, type="attempt.ended").values_list(
            "payload", flat=True
        )
    )
    assert run.actions_state["environment_links"] == {
        "root.deploy": {"name": "preview", "url": "https://preview.example.test/build"}
    }
    attempt = NodeAttempt.objects.get(node_run__run_id=run_id, node_run__scope_path="root.deploy")
    redactor(run_id).register("private-token")
    publish_environment(str(attempt.pk), "preview", "https://example.test/private-token")
    publish_environment(str(attempt.pk), "preview", "javascript:alert(1)")
    run.refresh_from_db()
    assert run.actions_state["environment_links"]["root.deploy"]["url"] == (
        "https://preview.example.test/build"
    )
