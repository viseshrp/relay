"""Opt-in recovery drives real attempts without changing frozen instructions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from hashlib import sha256
import json
from pathlib import Path

from django.db import connections
from django.test import Client
import pytest

from relay.agents.usage_limits import ProviderUsageLimit
from relay.constants import DEFAULT_RECOVERY_PROMPT, RETRY_HANDOFF_MAX_BYTES
from relay.execution.automatic import recovery_instruction
from relay.execution.control import ControlResult
from relay.execution.nodes import node_executors
from relay.execution.reconcile import reconcile_once
from relay.execution.recovery import prepare_recovery_workspace
from relay.execution.resume import RecoveryTarget, rerun_failed_node
from relay.execution.runner import AttemptContext, ExecutionOutcome, OutcomeKind
from relay.execution.scheduler import dispatch_ready_nodes
from relay.web.models import Artifact, AutomaticRetry, NodeAttempt, NodeRun, Run, RunSnapshot
from relay.web.repositories import DjangoExecutionStore
from relay.workflows.schema import AgentNode
from tests.support import (
    Clock,
    FakeAgents,
    InlineEngine,
    RegistryNetwork,
    RelayProject,
    git,
    run_status,
)


@dataclass
class ReportDriver:
    """External provider boundary: retain an invalid report until reprompted."""

    recover: bool = True
    unfinished_code: bool = False
    failure_code: str | None = None
    usage_limit: ProviderUsageLimit | None = None
    calls: list[AttemptContext] = field(default_factory=list)

    def execute(self, context: AttemptContext, node: AgentNode) -> ExecutionOutcome:
        del node
        self.calls.append(context)
        if context.attempt.scope_path == "root.plan":
            (context.worktree / "FEATURE_SPEC_AND_PLAN.md").write_text(
                "Created by: Test provider\nReady: No\n", encoding="utf-8"
            )
            (context.worktree / "plan-marker.txt").write_text("Committed plan\n", encoding="utf-8")
            git(context.worktree, "add", "plan-marker.txt")
            git(context.worktree, "commit", "-q", "-m", "Prepare plan")
        elif self.failure_code:
            return ExecutionOutcome(
                OutcomeKind.FAILED, error_code=self.failure_code, usage_limit=self.usage_limit
            )
        else:
            report = context.worktree / "PLAN_CRITIQUE.md"
            recovering = any(
                DEFAULT_RECOVERY_PROMPT in text for text in context.attempt.prompt_contents
            )
            if recovering:
                assert (
                    (context.worktree / "FEATURE_SPEC_AND_PLAN.md")
                    .read_text(encoding="utf-8")
                    .endswith("Ready: No\n")
                )
                if report.exists():
                    assert report.read_text(encoding="utf-8").endswith("Ready: No\n")
            content = (
                "Created by: Test provider\nReady: No\n"
                if (recovering and self.recover) or self.unfinished_code
                else "Ready: No\n"
            )
            report.write_text(content, encoding="utf-8")
            if self.unfinished_code:
                (context.worktree / "feature.txt").write_text("Feature work\n", encoding="utf-8")
                if recovering:
                    git(context.worktree, "add", "feature.txt")
                    git(context.worktree, "commit", "-q", "-m", "Finish the feature")
        return ExecutionOutcome(OutcomeKind.SUCCEEDED)


@pytest.fixture
def report_driver() -> ReportDriver:
    return ReportDriver()


@pytest.fixture
def recovery_engine(
    report_driver: ReportDriver, fake_agents: FakeAgents, registry_network: RegistryNetwork
) -> InlineEngine:
    from relay.paths import artifacts_dir

    del registry_network
    fake_agents.install("codex", mode="configuration")
    return InlineEngine(node_executors(agent_driver=report_driver), artifacts_dir())


def launch_report_run(
    project: RelayProject, engine: InlineEngine, *, enabled: bool = True, opt_out: bool = False
) -> str:
    project.write(".relay/prompts/prompt.md", "Review only the current plan.\n")
    project.write_workflow(
        "recovery",
        f"""version: 1
name: Recovery
model: m2
agents: [codex]
recovery: {{enabled: {str(enabled).lower()}, max_retries: 2}}
nodes:
  plan:
    type: agent
    writes: true
    outputs:
      author: {{label: {{artifact: FEATURE_SPEC_AND_PLAN.md, label: Created by}}}}
  critique:
    type: agent
    writes: true
    needs: [plan]
    allow_no_commit: true
    auto_retry: {str(not opt_out).lower()}
    prompts: [{{local: prompts/prompt.md}}]
    agent_options: {{codex: {{effort: low, permission_mode: auto}}}}
    outputs:
      author: {{label: {{artifact: PLAN_CRITIQUE.md, label: Created by}}}}
""",
    )
    run_id = engine.launch(project, "recovery")
    engine.drain(run_id)
    assert run_status(run_id) == "failed"
    return run_id


def test_recovery_retains_reports_and_reuses_settings_without_changing_the_snapshot(
    project: RelayProject, recovery_engine: InlineEngine, report_driver: ReportDriver
) -> None:
    run_id = launch_report_run(project, recovery_engine)
    original = RunSnapshot.objects.get(run_id=run_id)
    snapshot = (original.hashes, original.resolved_prompts, original.route_table)
    head = Run.objects.get(pk=run_id).recorded_head
    rejected = Artifact.objects.filter(
        attempt__node_run__node_id="critique", declared_name="author"
    ).get()
    assert Path(str(rejected.retained_path)).read_text(encoding="utf-8") == "Ready: No\n"
    connections.close_all()
    store = DjangoExecutionStore()
    assert store.resume_automatic_retries() == 1
    assert store.resume_automatic_retries() == 0
    dispatch_ready_nodes(store, run_id, recovery_engine.tokens.append)
    recovery_engine.drain(run_id)
    assert run_status(run_id) == "succeeded"
    assert NodeAttempt.objects.filter(node_run__node_id="plan").count() == 1
    assert NodeAttempt.objects.filter(node_run__node_id="critique").count() == 2
    first, retry = [
        call.attempt for call in report_driver.calls if call.attempt.scope_path == "root.critique"
    ]
    assert retry.route == first.route
    assert retry.prompt_contents[:-1] == first.prompt_contents
    assert "output_validation_error" in retry.prompt_contents[-1]
    decision = AutomaticRetry.objects.get(attempt__node_run__node_id="critique")
    assert decision.instruction_sha256 == sha256(retry.prompt_contents[-1].encode()).hexdigest()
    final = RunSnapshot.objects.get(run_id=run_id)
    assert (final.hashes, final.resolved_prompts, final.route_table) == snapshot
    assert Run.objects.get(pk=run_id).recorded_head == head


def test_repeated_failures_stop_after_two_retries_across_restarts(
    project: RelayProject, recovery_engine: InlineEngine, report_driver: ReportDriver
) -> None:
    report_driver.recover = False
    run_id = launch_report_run(project, recovery_engine)
    for _ in range(2):
        connections.close_all()
        store = DjangoExecutionStore()
        assert store.resume_automatic_retries() == 1
        dispatch_ready_nodes(store, run_id, recovery_engine.tokens.append)
        recovery_engine.drain(run_id)
    assert recovery_engine.store.resume_automatic_retries() == 0
    assert run_status(run_id) == "failed"
    assert NodeAttempt.objects.filter(node_run__node_id="critique").count() == 3
    assert list(AutomaticRetry.objects.order_by("pk").values_list("state", flat=True)) == [
        "resumed",
        "resumed",
        "exhausted",
    ]


def test_uncommitted_code_and_its_valid_report_are_preserved_before_automatic_recovery(
    project: RelayProject, recovery_engine: InlineEngine, report_driver: ReportDriver
) -> None:
    report_driver.unfinished_code = True
    run_id = launch_report_run(project, recovery_engine)
    failed = NodeAttempt.objects.get(node_run__node_id="critique")
    assert failed.error_code == "commit_validation_error"
    report = Artifact.objects.get(attempt=failed, declared_name="author")
    original = Path(str(report.retained_path)).read_bytes()
    unfinished = Artifact.objects.get(attempt=failed, source_path__endswith="feature.txt")
    assert Path(str(unfinished.retained_path)).read_text(encoding="utf-8") == "Feature work\n"
    store = recovery_engine.store
    assert store.resume_automatic_retries() == 1
    dispatch_ready_nodes(store, run_id, recovery_engine.tokens.append)
    recovery_engine.drain(run_id)
    assert run_status(run_id) == "succeeded"
    assert Path(str(report.retained_path)).read_bytes() == original
    assert NodeAttempt.objects.filter(node_run__node_id="plan").count() == 1
    worktree = Path(str(Run.objects.get(pk=run_id).worktree_path))
    assert git(worktree, "status", "--porcelain", "--", "feature.txt") == ""


@pytest.mark.parametrize("opt_out", [False, True])
def test_disabled_policy_or_step_never_retries(
    project: RelayProject, recovery_engine: InlineEngine, opt_out: bool
) -> None:
    run_id = launch_report_run(project, recovery_engine, enabled=opt_out, opt_out=opt_out)
    assert recovery_engine.store.resume_automatic_retries() == 0
    assert (
        NodeAttempt.objects.filter(node_run__run_id=run_id, node_run__node_id="critique").count()
        == 1
    )


@pytest.mark.parametrize(
    "code",
    [
        "agent_auth_error",
        "permission_flow_error",
        "model_unavailable",
        "path_safety_error",
        "artifact_preservation_error",
    ],
)
def test_unsafe_or_owner_failures_are_visible_and_never_retried(
    project: RelayProject, recovery_engine: InlineEngine, report_driver: ReportDriver, code: str
) -> None:
    report_driver.failure_code = code
    launch_report_run(project, recovery_engine)
    assert recovery_engine.store.resume_automatic_retries() == 0
    assert AutomaticRetry.objects.get().state == "blocked"
    assert AutomaticRetry.objects.get().error_message


def test_owner_cancel_removes_pending_recovery(
    project: RelayProject, recovery_engine: InlineEngine
) -> None:
    run_id = launch_report_run(project, recovery_engine)
    assert (
        recovery_engine.store.request_run_cancellation(run_id, "cancel-auto")
        is ControlResult.ACCEPTED
    )
    assert recovery_engine.store.resume_automatic_retries() == 0
    assert AutomaticRetry.objects.get().state == "canceled"


def test_orderly_shutdown_defers_pending_recovery(
    project: RelayProject, recovery_engine: InlineEngine
) -> None:
    launch_report_run(project, recovery_engine)
    result = reconcile_once(
        recovery_engine.store, recovery_engine.tokens.append, orderly_shutdown=True
    )
    assert result.automatic_retries_resumed == 0
    assert AutomaticRetry.objects.get().state == "scheduled"


def test_run_policy_api_enables_an_existing_failure_without_editing_the_snapshot(
    project: RelayProject, recovery_engine: InlineEngine
) -> None:
    run_id = launch_report_run(project, recovery_engine, enabled=False)
    snapshot = RunSnapshot.objects.get(run_id=run_id).hashes
    client = Client()
    assert (
        client.post(
            "/api/auth/onboard",
            data=json.dumps({"username": "owner", "password": "Relay-Recovery-Test-2026!"}),
            content_type="application/json",
        ).status_code
        == 201
    )
    body = json.dumps({"enabled": True, "idempotency_key": "enable-auto"})
    assert (
        client.post(
            f"/api/runs/{run_id}/recovery", data=body, content_type="application/json"
        ).status_code
        == 202
    )
    assert (
        client.post(
            f"/api/runs/{run_id}/recovery", data=body, content_type="application/json"
        ).status_code
        == 202
    )
    detail = client.get(f"/api/runs/{run_id}").json()["run"]
    assert detail["recovery"]["current"]["state"] == "scheduled"
    assert detail["recovery"]["enabled"] is True
    assert RunSnapshot.objects.get(run_id=run_id).hashes == snapshot
    assert recovery_engine.store.resume_automatic_retries() == 1


def test_disabling_then_enabling_does_not_replenish_the_budget(
    project: RelayProject, recovery_engine: InlineEngine, report_driver: ReportDriver
) -> None:
    report_driver.recover = False
    run_id = launch_report_run(project, recovery_engine)
    store = recovery_engine.store
    assert store.configure_recovery(run_id, False, "disable") is ControlResult.ACCEPTED
    assert store.resume_automatic_retries() == 0
    assert store.configure_recovery(run_id, True, "enable") is ControlResult.ACCEPTED
    assert AutomaticRetry.objects.count() == 1
    assert store.resume_automatic_retries() == 1
    dispatch_ready_nodes(store, run_id, recovery_engine.tokens.append)
    recovery_engine.drain(run_id)
    assert store.configure_recovery(run_id, False, "disable-again") is ControlResult.ACCEPTED
    assert store.configure_recovery(run_id, True, "enable-again") is ControlResult.ACCEPTED
    assert store.resume_automatic_retries() == 1
    dispatch_ready_nodes(store, run_id, recovery_engine.tokens.append)
    recovery_engine.drain(run_id)
    store.configure_recovery(run_id, False, "disable-exhausted")
    store.configure_recovery(run_id, True, "enable-exhausted")
    assert store.resume_automatic_retries() == 0
    assert NodeAttempt.objects.filter(node_run__node_id="critique").count() == 3


def test_manual_retry_supersedes_pending_recovery_without_a_repair_instruction(
    project: RelayProject, recovery_engine: InlineEngine
) -> None:
    run_id = launch_report_run(project, recovery_engine)
    store = recovery_engine.store
    assert (
        rerun_failed_node(
            store,
            run_id,
            "root.critique",
            "owner-retry",
            lambda target: prepare_recovery_workspace(store, target),
        )
        is ControlResult.ACCEPTED
    )
    assert AutomaticRetry.objects.get().state == "canceled"
    assert store.resume_automatic_retries() == 0
    assert NodeRun.objects.get(run_id=run_id, node_id="critique").recovery_instruction == ""


def test_cancel_during_preparation_prevents_activation(
    project: RelayProject, recovery_engine: InlineEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from relay.execution import recovery

    run_id = launch_report_run(project, recovery_engine)
    original = recovery.prepare_recovery_workspace

    def prepare(store: DjangoExecutionStore, target: RecoveryTarget) -> None:
        store.request_run_cancellation(run_id, "cancel-during-preparation")
        original(store, target)

    monkeypatch.setattr(recovery, "prepare_recovery_workspace", prepare)
    assert recovery_engine.store.resume_automatic_retries() == 0
    assert run_status(run_id) == "failed"
    assert AutomaticRetry.objects.get().state == "canceled"
    assert NodeAttempt.objects.filter(node_run__node_id="critique").count() == 1


def test_corrupt_upstream_evidence_blocks_before_reset(
    project: RelayProject, recovery_engine: InlineEngine
) -> None:
    run_id = launch_report_run(project, recovery_engine)
    # A failed attempt can also retain an upstream report as an untracked file.
    # Damage every retained copy so there is no remaining verified handoff.
    for retained in Artifact.objects.filter(source_path__endswith="FEATURE_SPEC_AND_PLAN.md"):
        Path(str(retained.retained_path)).write_text("Corrupt evidence\n", encoding="utf-8")
    worktree = Path(str(Run.objects.get(pk=run_id).worktree_path))
    unfinished = worktree / "unfinished.txt"
    unfinished.write_text("Keep these bytes\n", encoding="utf-8")
    assert recovery_engine.store.resume_automatic_retries() == 0
    assert unfinished.read_text(encoding="utf-8") == "Keep these bytes\n"
    assert AutomaticRetry.objects.get().state == "blocked"
    assert NodeAttempt.objects.filter(node_run__node_id="critique").count() == 1


@pytest.mark.parametrize(
    "code", ["node_timeout", "agent_protocol_error", "commit_validation_error"]
)
def test_other_eligible_failures_receive_the_exact_error(
    project: RelayProject, recovery_engine: InlineEngine, report_driver: ReportDriver, code: str
) -> None:
    report_driver.failure_code = code
    run_id = launch_report_run(project, recovery_engine)
    report_driver.failure_code = None
    assert recovery_engine.store.resume_automatic_retries() == 1
    dispatch_ready_nodes(recovery_engine.store, run_id, recovery_engine.tokens.append)
    recovery_engine.drain(run_id)
    assert run_status(run_id) == "succeeded"
    assert f"Error code: {code}" in report_driver.calls[-1].attempt.prompt_contents[-1]


def test_a_confirmed_quota_retry_preserves_the_repair_note_without_spending_another_retry(
    project: RelayProject, recovery_engine: InlineEngine, report_driver: ReportDriver, clock: Clock
) -> None:
    run_id = launch_report_run(project, recovery_engine)
    store = recovery_engine.store
    assert store.resume_automatic_retries() == 1
    report_driver.failure_code = "agent_usage_limit"
    report_driver.usage_limit = ProviderUsageLimit(clock.instant + timedelta(hours=1), "five_hour")
    dispatch_ready_nodes(store, run_id, recovery_engine.tokens.append)
    recovery_engine.drain(run_id)
    assert store.resume_automatic_retries() == 0
    assert store.resume_usage_retries() == 0
    clock.advance(3601)
    assert store.resume_usage_retries() == 1
    report_driver.failure_code = None
    report_driver.usage_limit = None
    dispatch_ready_nodes(store, run_id, recovery_engine.tokens.append)
    recovery_engine.drain(run_id)
    assert run_status(run_id) == "succeeded"
    assert AutomaticRetry.objects.filter(state="resumed").count() == 1
    assert DEFAULT_RECOVERY_PROMPT in report_driver.calls[-1].attempt.prompt_contents[-1]


def test_a_preparation_crash_resumes_the_same_decision(
    project: RelayProject, recovery_engine: InlineEngine
) -> None:
    run_id = launch_report_run(project, recovery_engine)
    retry = AutomaticRetry.objects.get()
    retry.state = "preparing"
    retry.save(update_fields=("state",))
    connections.close_all()
    assert DjangoExecutionStore().resume_automatic_retries() == 1
    assert AutomaticRetry.objects.count() == 1
    assert AutomaticRetry.objects.get().retry_number == 1
    assert Run.objects.get(pk=run_id).status == "running"


def test_nested_recovery_reopens_the_loop_and_keeps_the_successful_plan(
    project: RelayProject, recovery_engine: InlineEngine
) -> None:
    project.write_workflow(
        "nested",
        """version: 1
name: Nested recovery
model: m2
agents: [codex]
recovery: {enabled: true}
nodes:
  plan:
    type: agent
    writes: true
    outputs:
      author: {label: {artifact: FEATURE_SPEC_AND_PLAN.md, label: Created by}}
  repeat:
    type: loop
    needs: [plan]
    max_iterations: 2
    exhausted: finished
    until: "${{ needs.critique.outputs.author == 'Test provider' }}"
    body:
      critique:
        type: agent
        writes: true
        allow_no_commit: true
        outputs:
          author: {label: {artifact: PLAN_CRITIQUE.md, label: Created by}}
  finished: {type: command, run: [git, status]}
""",
    )
    run_id = recovery_engine.launch(project, "nested")
    recovery_engine.drain(run_id)
    assert run_status(run_id) == "failed"
    assert AutomaticRetry.objects.get().attempt.node_run.scope_path == "root.repeat#1.critique"
    assert recovery_engine.store.resume_automatic_retries() == 1
    dispatch_ready_nodes(recovery_engine.store, run_id, recovery_engine.tokens.append)
    recovery_engine.drain(run_id)
    assert run_status(run_id) == "succeeded"
    assert NodeAttempt.objects.filter(node_run__node_id="plan").count() == 1
    assert NodeAttempt.objects.filter(node_run__node_id="critique").count() == 2


def test_large_multibyte_diagnostics_keep_the_instruction_within_its_byte_limit() -> None:
    note, digest = recovery_instruction(
        "root." + "é" * 5_000, "output_validation_error", "🙂" * 5_000
    )
    assert note.startswith(DEFAULT_RECOVERY_PROMPT)
    assert len(note.encode("utf-8")) <= RETRY_HANDOFF_MAX_BYTES
    assert digest == sha256(note.encode("utf-8")).hexdigest()
