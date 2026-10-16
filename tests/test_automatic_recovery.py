"""Current Actions recovery preserves instructions, reports, and retry budgets."""

from dataclasses import dataclass, field
from hashlib import sha256
import json
import os
from pathlib import Path

from django.test import Client
import pytest

from relay.constants import (
    CONTROL_IDEMPOTENCY_KEY_MAX_CHARS,
    DEFAULT_RECOVERY_PROMPT,
    RETRY_HANDOFF_MAX_BYTES,
)
from relay.errors import PersistenceError
from relay.execution.automatic import recovery_instruction
from relay.execution.control import ControlResult
from relay.execution.nodes import node_executors
from relay.execution.recovery import prepare_recovery_workspace
from relay.execution.resume import RecoveryTarget, rerun_failed_node
from relay.execution.runner import AttemptContext, ExecutionOutcome, OutcomeKind
from relay.web.models import (
    Artifact,
    AutomaticRetry,
    NodeAttempt,
    NodeRun,
    Run,
    RunEvent,
    RunSnapshot,
)
from relay.workflows.schema import AgentNode
from tests.support import FakeAgents, InlineEngine, RelayProject
from tests.test_web_api import client as client
from tests.test_web_api import owner as owner
from tests.test_web_api import post


@dataclass
class ReportDriver:
    recover: bool = True
    error_code: str | None = None
    calls: list[AttemptContext] = field(default_factory=list)

    def execute(self, context: AttemptContext, node: AgentNode) -> ExecutionOutcome:
        del node
        self.calls.append(context)
        if self.error_code:
            return ExecutionOutcome(OutcomeKind.FAILED, error_code=self.error_code)
        recovering = any(
            DEFAULT_RECOVERY_PROMPT in text for text in context.attempt.prompt_contents
        )
        (context.worktree / "PLAN_CRITIQUE.md").write_text(
            "Created by: Offline provider\nReady: Yes\n"
            if recovering and self.recover
            else "Ready: No\n",
            encoding="utf-8",
        )
        return ExecutionOutcome(OutcomeKind.SUCCEEDED)


def launch_report_run(
    project: RelayProject,
    tmp_path: Path,
    fake_agents: FakeAgents,
    driver: ReportDriver,
    *,
    enabled: bool = False,
    opt_out: bool = False,
) -> tuple[InlineEngine, str]:
    fake_agents.install("codex")
    project.write(".relay/prompts/review.md", "Review the captured plan.\n")
    project.write_workflow(
        "recovery",
        json.dumps(
            {
                "recovery": {"enabled": enabled, "max_retries": 2},
                "jobs": {
                    "critique": {
                        "steps": [
                            {
                                "id": "review",
                                "uses": "relay/agent@v1",
                                "with": {
                                    "agent": "codex",
                                    "model": "m1",
                                    "prompt-files": "prompts/review.md",
                                    "report": "PLAN_CRITIQUE.md",
                                    "label": "Created by",
                                    **({"auto-retry": False} if opt_out else {}),
                                },
                            }
                        ]
                    }
                },
            }
        ),
    )
    from relay.paths import artifacts_dir

    engine = InlineEngine(node_executors(agent_driver=driver), artifacts_dir())
    run_id = engine.launch(project, "recovery")
    engine.drain(run_id)
    return engine, run_id


@pytest.mark.parametrize("recover,expected,calls", [(True, "succeeded", 2), (False, "failed", 3)])
def test_inline_recovery_retains_reports_and_frozen_prompts(
    project: RelayProject,
    tmp_path: Path,
    fake_agents: FakeAgents,
    recover: bool,
    expected: str,
    calls: int,
) -> None:
    driver = ReportDriver(recover=recover)
    engine, run_id = launch_report_run(project, tmp_path, fake_agents, driver, enabled=True)
    assert Run.objects.get(pk=run_id).status == expected
    assert len(driver.calls) == calls
    assert driver.calls[0].attempt.prompt_contents == ("Review the captured plan.\n",)
    assert all(
        call.attempt.prompt_contents[0] == "Review the captured plan.\n" for call in driver.calls
    )
    assert all(
        DEFAULT_RECOVERY_PROMPT in call.attempt.prompt_contents[-1] for call in driver.calls[1:]
    )
    assert AutomaticRetry.objects.filter(state="resumed").count() == calls - 1
    assert NodeAttempt.objects.filter(node_run__scope_path="root.critique.review").count() == calls
    snapshot = RunSnapshot.objects.get(run_id=run_id)
    assert snapshot.resolved_prompts[0]["content"] == "Review the captured plan.\n"
    assert snapshot.hashes["workflow"] == sha256(snapshot.workflow_yaml.encode()).hexdigest()
    reports = Artifact.objects.filter(attempt__node_run__run_id=run_id, declared_name="report")
    assert any(
        Path(row.retained_path).read_text(encoding="utf-8") == "Ready: No\n" for row in reports
    )
    assert engine.store.resume_automatic_retries() == 0


@pytest.mark.parametrize("enabled,opt_out", [(False, False), (True, True)])
def test_disabled_recovery_never_starts_another_turn(
    project: RelayProject, tmp_path: Path, fake_agents: FakeAgents, enabled: bool, opt_out: bool
) -> None:
    driver = ReportDriver()
    engine, run_id = launch_report_run(
        project, tmp_path, fake_agents, driver, enabled=enabled, opt_out=opt_out
    )
    assert Run.objects.get(pk=run_id).status == "failed"
    assert len(driver.calls) == 1
    assert engine.store.resume_automatic_retries() == 0


def test_owner_enables_recovery_without_rewriting_snapshot(
    project: RelayProject, tmp_path: Path, fake_agents: FakeAgents
) -> None:
    driver = ReportDriver()
    engine, run_id = launch_report_run(project, tmp_path, fake_agents, driver)
    snapshot = RunSnapshot.objects.get(run_id=run_id)
    before = (snapshot.hashes, snapshot.route_table, snapshot.resolved_prompts)
    engine.store.configure_recovery(run_id, True, "enable-current-step")
    assert engine.store.resume_automatic_retries() == 1
    engine.drain(run_id)
    assert Run.objects.get(pk=run_id).status == "succeeded"
    assert len(driver.calls) == 2
    snapshot.refresh_from_db()
    assert (snapshot.hashes, snapshot.route_table, snapshot.resolved_prompts) == before


@pytest.mark.parametrize("damage", ["bytes", "missing"])
def test_damaged_evidence_blocks_owner_enabled_recovery(
    project: RelayProject, tmp_path: Path, fake_agents: FakeAgents, damage: str
) -> None:
    driver = ReportDriver()
    engine, run_id = launch_report_run(project, tmp_path, fake_agents, driver)
    engine.store.configure_recovery(run_id, True, "enable-current-step")
    report = Artifact.objects.get(
        attempt__node_run__scope_path="root.critique.review", declared_name="report"
    )
    path = Path(report.retained_path)
    if damage == "bytes":
        path.write_text("Changed retained bytes\n", encoding="utf-8")
    else:
        path.unlink()
    assert engine.store.resume_automatic_retries() == 0
    assert len(driver.calls) == 1
    assert Run.objects.get(pk=run_id).status == "failed"
    assert AutomaticRetry.objects.get().state == "blocked"


def test_large_multibyte_diagnostics_keep_the_instruction_within_its_byte_limit() -> None:
    note, digest = recovery_instruction(
        "root." + "é" * 5_000, "output_validation_error", "🙂" * 5_000
    )
    assert note.startswith(DEFAULT_RECOVERY_PROMPT)
    assert len(note.encode("utf-8")) <= RETRY_HANDOFF_MAX_BYTES
    assert digest == sha256(note.encode("utf-8")).hexdigest()


@pytest.mark.parametrize("body", [{"enabled": 1}, {"enabled": "true"}, {}])
def test_recovery_route_requires_a_boolean_enabled_value(
    owner: Client,
    project: RelayProject,
    tmp_path: Path,
    fake_agents: FakeAgents,
    body: dict[str, object],
) -> None:
    _engine, run_id = launch_report_run(project, tmp_path, fake_agents, ReportDriver())
    response = post(owner, f"/api/runs/{run_id}/recovery", {**body, "idempotency_key": "policy"})
    assert response.status_code == 400
    assert response.json()["code"] == "config_error"
    assert response.json()["message"] == "enabled must be a boolean."


def test_recovery_route_maps_accepted_duplicate_and_invalid_keys(
    owner: Client, project: RelayProject, tmp_path: Path, fake_agents: FakeAgents
) -> None:
    _engine, run_id = launch_report_run(project, tmp_path, fake_agents, ReportDriver())
    url = f"/api/runs/{run_id}/recovery"
    body = {"enabled": True, "idempotency_key": "enable-recovery"}
    accepted = post(owner, url, body)
    duplicate = post(owner, url, body)
    invalid = post(
        owner,
        url,
        {
            "enabled": True,
            "idempotency_key": "x" * (CONTROL_IDEMPOTENCY_KEY_MAX_CHARS + 1),
        },
    )
    assert (accepted.status_code, accepted.json()) == (202, {"result": "accepted"})
    assert (duplicate.status_code, duplicate.json()) == (202, {"result": "already_applied"})
    assert (invalid.status_code, invalid.json()) == (422, {"result": "invalid"})


@pytest.mark.parametrize("status", ["succeeded", "canceled"])
def test_recovery_route_refuses_a_finished_run(
    owner: Client, project: RelayProject, engine: InlineEngine, status: str
) -> None:
    project.write_workflow("finished", "jobs: {main: {steps: [{run: print(1), shell: python}]}}\n")
    run_id = engine.launch(project, "finished")
    if status == "canceled":
        engine.store.request_run_cancellation(run_id, "cancel")
    engine.drain(run_id)
    assert Run.objects.get(pk=run_id).status == status
    response = post(
        owner,
        f"/api/runs/{run_id}/recovery",
        {
            "enabled": True,
            "idempotency_key": "finished-policy",
        },
    )
    assert (response.status_code, response.json()) == (409, {"result": "stale"})


@pytest.fixture
def scheduled_recovery(
    project: RelayProject, tmp_path: Path, fake_agents: FakeAgents
) -> tuple[InlineEngine, str]:
    engine, run_id = launch_report_run(project, tmp_path, fake_agents, ReportDriver())
    assert (
        engine.store.configure_recovery(run_id, True, "schedule-recovery") is ControlResult.ACCEPTED
    )
    assert AutomaticRetry.objects.get().state == "scheduled"
    return engine, run_id


def test_disabling_recovery_cancels_a_scheduled_retry(
    scheduled_recovery: tuple[InlineEngine, str],
) -> None:
    engine, run_id = scheduled_recovery
    assert engine.store.configure_recovery(run_id, False, "disable") is ControlResult.ACCEPTED
    assert AutomaticRetry.objects.get().state == "canceled"
    assert RunEvent.objects.filter(run_id=run_id, type="run.recovery_canceled").exists()
    assert Run.objects.get(pk=run_id).status == "failed"


@pytest.mark.parametrize("refusal", ["paused", "disabled", "not_failed", "no_pending_retry"])
def test_automatic_rerun_target_requires_an_eligible_pending_failure(
    scheduled_recovery: tuple[InlineEngine, str], refusal: str
) -> None:
    engine, run_id = scheduled_recovery
    store = engine.store
    if refusal == "paused":
        store.configure_dispatch_pause(run_id, True, "pause")
    elif refusal == "disabled":
        store.configure_recovery(run_id, False, "disable")
    elif refusal == "not_failed":
        assert (
            rerun_failed_node(
                store,
                run_id,
                "root.critique.review",
                "owner-retry",
                lambda target: prepare_recovery_workspace(target, store),
            )
            is ControlResult.ACCEPTED
        )
        assert Run.objects.get(pk=run_id).status == "running"
    else:
        store.request_run_cancellation(run_id, "cancel-pending-retry")
        assert Run.objects.get(pk=run_id).status == "failed"
        assert AutomaticRetry.objects.get().state == "canceled"
    assert store.automatic_rerun_target(run_id, "root.critique.review", "automatic") is None


def test_automatic_rerun_target_refuses_an_unrelated_failed_step(
    scheduled_recovery: tuple[InlineEngine, str],
) -> None:
    engine, run_id = scheduled_recovery
    failed = NodeRun.objects.get(run_id=run_id, scope_path="root.critique.review")
    NodeRun.objects.create(
        run_id=run_id,
        node_id="other",
        scope_path="root.critique.other",
        node_type=failed.node_type,
        frozen_def=failed.frozen_def,
        status="failed",
    )
    with pytest.raises(
        PersistenceError,
        match=r"Another failed step must be resolved before automatic recovery\.",
    ):
        engine.store.automatic_rerun_target(run_id, "root.critique.review", "automatic")
    assert AutomaticRetry.objects.get().state == "scheduled"


def test_automatic_retries_remain_pending_during_orderly_shutdown(
    scheduled_recovery: tuple[InlineEngine, str],
) -> None:
    engine, run_id = scheduled_recovery
    instance = engine.store.acquire_instance(os.getpid(), "test-host")
    engine.store.request_orderly_shutdown(instance)
    assert engine.store.resume_automatic_retries() == 0
    assert AutomaticRetry.objects.get().state == "scheduled"
    assert Run.objects.get(pk=run_id).status == "failed"


@pytest.mark.parametrize("change", ["disabled", "paused", "shutdown", "newer_attempt"])
def test_automatic_activation_rechecks_changes_during_workspace_preparation(
    scheduled_recovery: tuple[InlineEngine, str], change: str
) -> None:
    engine, run_id = scheduled_recovery
    store = engine.store
    activations = []

    def prepare(target: RecoveryTarget) -> None:
        prepare_recovery_workspace(target, store)
        if change == "disabled":
            store.configure_recovery(run_id, False, "disable-during-preparation")
        elif change == "paused":
            store.configure_dispatch_pause(run_id, True, "pause-during-preparation")
        elif change == "shutdown":
            instance = store.acquire_instance(os.getpid(), "test-host")
            store.request_orderly_shutdown(instance)
        else:
            failed = NodeAttempt.objects.get(pk=target.attempt_id)
            NodeAttempt.objects.create(
                node_run_id=target.node_run_id,
                attempt_number=failed.attempt_number + 1,
                worker_id=engine.worker_id,
                starting_head=failed.starting_head,
                status="failed",
            )
        activations.append(store.activate_automatic_recovery(target, "activation-probe"))

    result = rerun_failed_node(
        store,
        run_id,
        "root.critique.review",
        "automatic",
        prepare,
        automatic_retry=True,
    )
    assert activations == [False]
    assert result is ControlResult.ALREADY_APPLIED
    assert Run.objects.get(pk=run_id).status == "failed"
    assert AutomaticRetry.objects.get().state == (
        "canceled" if change == "disabled" else "preparing"
    )


def test_owner_retry_cancels_a_scheduled_automatic_retry(
    scheduled_recovery: tuple[InlineEngine, str],
) -> None:
    engine, run_id = scheduled_recovery
    store = engine.store
    result = rerun_failed_node(
        store,
        run_id,
        "root.critique.review",
        "owner-retry",
        lambda target: prepare_recovery_workspace(target, store),
    )
    assert result is ControlResult.ACCEPTED
    assert AutomaticRetry.objects.get().state == "canceled"
    assert RunEvent.objects.filter(run_id=run_id, type="run.recovery_canceled").exists()
    assert Run.objects.get(pk=run_id).status == "running"
