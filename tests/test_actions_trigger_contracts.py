"""Local ref observation and uncertain trigger launches preserve durable intent."""

from datetime import timedelta
from pathlib import Path
from typing import Any

from django.utils import timezone
import pytest

from relay.errors import ConfigError
from relay.execution.nodes import node_executors
from relay.web.actions_automation import (
    activate,
    admit_queue,
    deliver,
    launch_delivery,
    reconcile,
    repository_dispatch,
)
from relay.web.models import (
    ActionsQueue,
    NodeRun,
    Run,
    RunSnapshot,
    TriggerDelivery,
    WorkflowTrigger,
)
from tests.support import InlineEngine, RelayProject, git

BASE = "jobs: {main: {steps: [{uses: relay/human-wait@v1, with: {prompt: Continue?}}]}}\n"


def test_push_observes_new_changed_and_deleted_refs_with_path_filters(
    project: RelayProject, monkeypatch: pytest.MonkeyPatch
) -> None:
    project.write_workflow("push", "on: {push: {branches: [main], paths: ['src/**']}}\n" + BASE)
    project.commit("Provide the automatic workflow")
    activate(project.project_id, project.relay_root, "push", "push", True, True)
    monkeypatch.setattr("relay.web.actions_automation.launch_delivery", lambda delivery: None)
    project.write("ignored.txt", "ignored\n")
    project.commit("Change an ignored path")
    reconcile()
    assert not TriggerDelivery.objects.exists()
    before = git(project.repository, "rev-parse", "HEAD")
    project.write("src/result.txt", "observed\n")
    project.commit("Change an included path")
    after = git(project.repository, "rev-parse", "HEAD")
    reconcile()
    delivery = TriggerDelivery.objects.get()
    assert delivery.payload["event"]["before"] == before and delivery.payload["sha"] == after
    assert delivery.payload["event"]["paths"] == ["src/result.txt"]
    reconcile()
    assert TriggerDelivery.objects.count() == 1
    git(project.repository, "branch", "new-ignored")
    reconcile()
    git(project.repository, "branch", "-D", "new-ignored")
    reconcile()
    assert TriggerDelivery.objects.count() == 1


@pytest.mark.parametrize(
    "event_type,payload,identity",
    [
        ("", {}, "id"),
        ("x" * 65536, {}, "id"),
        ("build", {"value": "x" * 65536}, "id"),
        ("build", {}, ""),
        ("build", {}, "x" * 201),
    ],
    ids=[
        "empty-event",
        "oversized-event",
        "oversized-payload",
        "empty-identity",
        "oversized-identity",
    ],
)
def test_dispatch_contract_bounds_reject_before_delivery(
    project: RelayProject, event_type: str, payload: dict[str, Any], identity: str
) -> None:
    with pytest.raises(ConfigError):
        repository_dispatch(project.project_id, event_type, payload, identity)
    assert not TriggerDelivery.objects.exists()


@pytest.mark.parametrize("filter_kind", ["paths", "paths-ignore"])
def test_local_tag_delivery_honors_path_filters(
    project: RelayProject, monkeypatch: pytest.MonkeyPatch, filter_kind: str
) -> None:
    pattern = "src/**" if filter_kind == "paths" else "docs/**"
    project.write_workflow(
        "tag", f"on: {{push: {{tags: [release], {filter_kind}: ['{pattern}']}}}}\n" + BASE
    )
    project.commit("Provide the local tag workflow")
    git(project.repository, "tag", "release")
    activate(project.project_id, project.relay_root, "tag", "push", True, True)
    monkeypatch.setattr("relay.web.actions_automation.launch_delivery", lambda _delivery: None)
    project.write("docs/guide.md", "Ignored change\n")
    project.commit("Change an ignored path")
    git(project.repository, "tag", "-f", "release")
    reconcile()
    assert not TriggerDelivery.objects.exists()
    before = git(project.repository, "rev-parse", "HEAD")
    project.write("src/code.py", "print('local')\n")
    project.commit("Change an included path")
    git(project.repository, "tag", "-f", "release")
    after = git(project.repository, "rev-parse", "HEAD")
    reconcile()
    delivery = TriggerDelivery.objects.get()
    assert delivery.payload["ref"] == "refs/tags/release"
    assert delivery.payload["ref_type"] == "tag"
    assert delivery.payload["event"]["before"] == before
    assert delivery.payload["sha"] == after
    assert delivery.payload["event"]["paths"] == ["src/code.py"]
    reconcile()
    assert TriggerDelivery.objects.count() == 1


def test_activation_and_payload_validation_remain_opt_in(project: RelayProject) -> None:
    project.write_workflow("automatic", "on: repository_dispatch\n" + BASE)
    with pytest.raises(ConfigError, match="declared"):
        activate(project.project_id, project.relay_root, "automatic", "push", True, True)
    activate(
        project.project_id, project.relay_root, "automatic", "repository_dispatch", False, False
    )
    trigger = WorkflowTrigger.objects.get()
    with pytest.raises(ConfigError, match="65535"):
        deliver(trigger, "oversized", {"value": "x" * 65536})
    deliver(trigger, "disabled", {})
    launch_delivery(TriggerDelivery.objects.get())
    assert TriggerDelivery.objects.get().state == "pending" and not Run.objects.exists()


@pytest.mark.parametrize("recover", [True, False])
def test_uncertain_launch_reconciliation_never_replays_a_delivery(
    project: RelayProject, tmp_path: Path, recover: bool
) -> None:
    project.write_workflow("automatic", "on: repository_dispatch\n" + BASE)
    activate(project.project_id, project.relay_root, "automatic", "repository_dispatch", True, True)
    trigger = WorkflowTrigger.objects.get()
    delivery = TriggerDelivery.objects.create(
        trigger=trigger,
        occurrence="uncertain",
        state="launching",
        created_at=timezone.now() - timedelta(minutes=6),
    )
    run_id = None
    if recover:
        engine = InlineEngine(node_executors(), tmp_path / "artifacts")
        run_id = engine.launch(project, "automatic")
        snapshot = RunSnapshot.objects.get(run_id=run_id)
        defaults = dict(snapshot.launch_defaults)
        defaults["actions_context"]["relay"]["delivery_id"] = str(delivery.pk)
        snapshot.launch_defaults = defaults
        snapshot.save(update_fields=["launch_defaults"])
    reconcile()
    delivery.refresh_from_db()
    assert delivery.state == ("launched" if recover else "blocked")
    assert str(delivery.run_id) == str(run_id)
    assert Run.objects.count() == int(recover)
    reconcile()
    assert Run.objects.count() == int(recover)


def test_single_queue_supersedes_pending_work_and_keeps_the_active_owner(
    project: RelayProject, tmp_path: Path
) -> None:
    project.write_workflow("queue", "concurrency: shared\n" + BASE)
    engine = InlineEngine(node_executors(), tmp_path / "artifacts")
    ids = [engine.launch(project, "queue") for _ in range(3)]
    nodes = [NodeRun.objects.get(run_id=run_id, scope_path="root.main") for run_id in ids]
    assert admit_queue(nodes[0], {}, activate=True)
    assert not admit_queue(nodes[1], {})
    assert not admit_queue(nodes[2], {})
    assert ActionsQueue.objects.get(run_id=ids[0]).state == "active"
    assert ActionsQueue.objects.get(run_id=ids[1]).state == "superseded"
    assert Run.objects.get(pk=ids[1]).status == "canceled"
    assert ActionsQueue.objects.get(run_id=ids[2]).state == "pending"
    assert not admit_queue(nodes[1], {})
    ActionsQueue.objects.filter(run_id=ids[2]).update(group="changed")
    with pytest.raises(ConfigError, match="changed during resume"):
        admit_queue(nodes[2], {})


def test_max_queue_bound_rejects_extra_pending_reservations(
    project: RelayProject, tmp_path: Path
) -> None:
    project.write_workflow("queue", "concurrency: {group: shared, queue: max}\n" + BASE)
    engine = InlineEngine(node_executors(), tmp_path / "artifacts")
    first = engine.launch(project, "queue")
    second = engine.launch(project, "queue")
    ActionsQueue.objects.bulk_create(
        [
            ActionsQueue(
                run_id=first, scope=f"slot{i}", group="shared", mode="max", state="pending"
            )
            for i in range(100)
        ]
    )
    node = NodeRun.objects.get(run_id=second, scope_path="root.main")
    with pytest.raises(ConfigError, match="100 waiting"):
        admit_queue(node, {})
