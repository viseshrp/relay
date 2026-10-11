"""Local automation, scoped queues, owner templates, and native-store boundaries."""

from datetime import timedelta
from io import StringIO
import json
from pathlib import Path
from types import SimpleNamespace

from django.utils import timezone
import pytest

from relay.errors import ConfigError, WorkflowValidationError
from relay.execution.nodes import node_executors
from relay.web.actions_automation import activate, launch_delivery, reconcile, repository_dispatch
from relay.web.models import ActionsJobLease, ActionsQueue, Run, TriggerDelivery, WorkflowTrigger
from relay.web.repositories import DjangoWorkflowStore
from relay.workflows.library import export_template, import_template, instantiate
from tests.support import InlineEngine, RelayProject, answer_wait


def test_dispatch_is_opt_in_bounded_and_deduplicated(project: RelayProject, tmp_path: Path) -> None:
    project.write_workflow(
        "dispatch",
        """on: {repository_dispatch: {types: [build]}}
jobs: {main: {steps: [{run: echo ready}]}}
""",
    )
    repository_dispatch(project.project_id, "build", {}, "before-activation")
    assert not TriggerDelivery.objects.exists()
    with pytest.raises(ConfigError):
        activate(
            project.project_id, project.relay_root, "dispatch", "repository_dispatch", True, False
        )
    activate(project.project_id, project.relay_root, "dispatch", "repository_dispatch", True, True)
    repository_dispatch(project.project_id, "ignored", {}, "identity")
    repository_dispatch(project.project_id, "build", {"target": "local"}, "identity")
    repository_dispatch(project.project_id, "build", {"target": "different"}, "identity")
    assert TriggerDelivery.objects.count() == 1
    engine = InlineEngine(node_executors(), tmp_path / "artifacts")
    delivery = TriggerDelivery.objects.get()
    launch_delivery(delivery)
    delivery.refresh_from_db()
    assert delivery.state == "launched"
    engine.drain(str(delivery.run_id))
    assert Run.objects.get(pk=delivery.run_id).status == "succeeded"
    launch_delivery(delivery)
    assert Run.objects.count() == 1


def test_activation_freezes_transitive_sources_and_blocks_changed_calls(
    project: RelayProject,
) -> None:
    project.write_workflow(
        "callee",
        "on: workflow_call\njobs: {main: {steps: [{run: echo first}]}}\n",
    )
    project.write_workflow(
        "caller", "on: repository_dispatch\njobs: {call: {uses: ./.relay/workflows/callee.yaml}}\n"
    )
    activate(project.project_id, project.relay_root, "caller", "repository_dispatch", True, True)
    repository_dispatch(project.project_id, "event", {}, "identity")
    project.write_workflow(
        "callee",
        "on: workflow_call\njobs: {main: {steps: [{run: echo changed}]}}\n",
    )
    launch_delivery(TriggerDelivery.objects.get())
    assert TriggerDelivery.objects.get().state == "blocked"
    assert not Run.objects.exists()


def test_schedule_downtime_coalesces_latest_and_reconciliation_is_idempotent(
    project: RelayProject, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = timezone.now().replace(second=30, microsecond=0)
    monkeypatch.setattr("relay.web.actions_automation.timezone.now", lambda: now)
    project.write_workflow(
        "scheduled",
        "on: {schedule: [{cron: '* * * * *'}]}\njobs: {main: {steps: [{run: echo scheduled}]}}\n",
    )
    activate(project.project_id, project.relay_root, "scheduled", "schedule", True, True)
    trigger = WorkflowTrigger.objects.get()
    WorkflowTrigger.objects.filter(pk=trigger.pk).update(
        cursor={"at": (now - timedelta(days=400)).isoformat()}
    )
    monkeypatch.setattr("relay.web.actions_automation.launch_delivery", lambda _delivery: None)
    reconcile()
    reconcile()
    assert TriggerDelivery.objects.count() == 1
    delivery = TriggerDelivery.objects.get()
    assert delivery.payload["scheduled_at"] == now.replace(second=0).isoformat()


def test_completed_run_cursor_pages_equal_timestamps_without_losing_deliveries(
    project: RelayProject, monkeypatch: pytest.MonkeyPatch
) -> None:
    from relay.web.models import RunSnapshot

    project.write_workflow(
        "completed",
        "on: {workflow_run: {workflows: [Upstream]}}\njobs: {main: {steps: [{run: echo ready}]}}\n",
    )
    activate(project.project_id, project.relay_root, "completed", "workflow_run", True, True)
    ended = timezone.now()
    runs = [
        Run(
            project_id=project.project_id,
            number=index + 1,
            workflow_key="upstream.yaml",
            title="Upstream",
            source_branch="main",
            status="succeeded",
            source_commit="a" * 40,
            recorded_head="a" * 40,
            run_branch=f"relay/test/{index}",
            worktree_path=str(project.repository / f"unused-{index}"),
            launcher="test",
            ended_at=ended,
        )
        for index in range(101)
    ]
    Run.objects.bulk_create(runs)
    RunSnapshot.objects.bulk_create(
        [RunSnapshot(run=run, workflow_yaml="", relay_version="test") for run in runs]
    )
    monkeypatch.setattr("relay.web.actions_automation.launch_delivery", lambda _delivery: None)
    reconcile()
    assert TriggerDelivery.objects.count() == 100
    reconcile()
    assert TriggerDelivery.objects.count() == 101
    reconcile()
    assert TriggerDelivery.objects.count() == 101
    assert set(TriggerDelivery.objects.values_list("occurrence", flat=True)) == {
        str(run.pk) for run in runs
    }


def test_queue_reservation_does_not_hold_global_job_lease(
    project: RelayProject, tmp_path: Path
) -> None:
    project.write_workflow(
        "queued",
        """on: workflow_dispatch
concurrency: {group: local, queue: max}
jobs:
  main:
    steps: [{uses: relay/human-wait@v1, with: {prompt: Continue?}}]
""",
    )
    engine = InlineEngine(node_executors(), tmp_path / "artifacts")
    first = engine.launch(project, "queued")
    engine.drain(first)
    owner = ActionsJobLease.objects.get().node_id
    second = engine.launch(project, "queued")
    engine.drain(second)
    assert ActionsJobLease.objects.get().node_id == owner
    assert ActionsQueue.objects.get(run_id=second).state == "pending"
    assert answer_wait(engine, first) == "accepted"
    engine.drain(second)
    assert ActionsQueue.objects.get(run_id=second).state == "active"
    assert answer_wait(engine, second) == "accepted"
    assert Run.objects.get(pk=second).status == "succeeded"


def test_nested_self_blocking_concurrency_is_rejected_without_deadlock(
    project: RelayProject, tmp_path: Path
) -> None:
    project.write_workflow(
        "callee",
        "on: workflow_call\nconcurrency: shared\njobs: {main: {steps: [{run: echo called}]}}\n",
    )
    project.write_workflow(
        "caller",
        "on: workflow_dispatch\nconcurrency: shared\n"
        "jobs: {call: {uses: ./.relay/workflows/callee.yaml}}\n",
    )
    engine = InlineEngine(node_executors(), tmp_path / "artifacts")
    run_id = engine.launch(project, "caller")
    engine.drain(run_id)
    assert Run.objects.get(pk=run_id).status == "failed"
    assert ActionsJobLease.objects.get().node_id is None


def test_owner_library_preserves_comments_metadata_and_default_branch(
    project: RelayProject,
) -> None:
    bundle = {
        "metadata": {"name": "Owner template", "description": "Local", "categories": ["review"]},
        "yaml": "# owner comment\non: {push: {branches: ['$default-branch']}}\n"
        "jobs: {main: {steps: [{run: echo ready}]}}\n",
        "sources": {".relay/prompts/custom.md": "Owner prompt\n"},
    }
    identity = import_template(bundle)
    assert export_template(identity) == bundle
    document = instantiate(
        DjangoWorkflowStore(), project.relay_root, project.project_id, "from-library", identity
    )
    assert "# owner comment" in document.yaml and "$default-branch" not in document.yaml
    assert (project.relay_root / "prompts" / "custom.md").read_text() == "Owner prompt\n"
    (project.relay_root / "prompts" / "custom.md").write_text(
        "Owner changed this\n", encoding="utf-8"
    )
    with pytest.raises(WorkflowValidationError):
        instantiate(
            DjangoWorkflowStore(), project.relay_root, project.project_id, "another", identity
        )
    assert (project.relay_root / "prompts" / "custom.md").read_text() == "Owner changed this\n"


@pytest.mark.parametrize(
    "system,module,backend",
    [
        ("Darwin", "keyring.backends.macOS", "Keyring"),
        ("Windows", "keyring.backends.Windows", "WinVaultKeyring"),
        ("Linux", "keyring.backends.SecretService", "Keyring"),
    ],
)
def test_native_store_selects_only_the_explicit_os_backend(
    system: str, module: str, backend: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from relay.execution import native_credentials

    calls = []

    class Native:
        def get_password(self, service: str, reference: str) -> str:
            calls.append((service, reference))
            return "test-value"

    def import_backend(name: str) -> object:
        assert name == module
        return SimpleNamespace(**{backend: Native})

    output = StringIO()
    monkeypatch.setattr(native_credentials.platform, "system", lambda: system)
    monkeypatch.setattr(native_credentials.importlib, "import_module", import_backend)
    monkeypatch.setattr(
        native_credentials.sys,
        "stdin",
        StringIO(json.dumps({"operation": "get", "reference": "test-reference"})),
    )
    monkeypatch.setattr(native_credentials.sys, "stdout", output)
    native_credentials._main()
    assert json.loads(output.getvalue()) == {"ok": True, "value": "test-value"}
    assert calls == [("Relay workflow secrets", "test-reference")]
