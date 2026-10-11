"""Owner management protects current edits and retains historical records."""

from __future__ import annotations

from django.test import Client
from django.utils import timezone
import pytest

from relay.web.actions_automation import deliver, launch_delivery, local_refs, reconcile
from relay.web.models import Run, TriggerDelivery, WorkflowControl, WorkflowTrigger
from tests.support import Clock, InlineEngine, RelayProject, git
from tests.test_editor_recovery import SOURCE, owner, post

__all__ = ["owner"]


def test_management_requires_a_lease_and_unchanged_source(
    owner: Client, project: RelayProject
) -> None:
    path = "/api/workflows/check.yaml"
    document = owner.get(path).json()
    body = {
        "action": "rename",
        "holder": "tab",
        "base_hash": document["base_hash"],
        "new_key": "renamed.yaml",
        "name": "Renamed",
    }
    assert post(owner, path + "/manage", body).status_code == 409
    assert post(owner, path + "/lease", {"holder": "tab"}).status_code == 200
    project.write(".relay/workflows/check.yaml", SOURCE + "# owner changed this\n")
    assert post(owner, path + "/manage", body).status_code == 409
    assert not (project.repository / ".relay/workflows/renamed.yaml").exists()


def test_duplicate_rename_disable_and_delete_preserve_shared_files(
    owner: Client, project: RelayProject
) -> None:
    path = "/api/workflows/check.yaml"
    document = owner.get(path).json()
    post(owner, path + "/lease", {"holder": "tab"})
    project.write(".relay/prompts/shared.md", "Shared instructions\n")
    body = {
        "holder": "tab",
        "base_hash": document["base_hash"],
        "new_key": "copy.yaml",
        "name": "Copy",
    }
    assert post(owner, path + "/manage", {**body, "action": "duplicate"}).status_code == 200
    assert (project.repository / ".relay/workflows/check.yaml").read_text() == SOURCE
    assert "Copy" in (project.repository / ".relay/workflows/copy.yaml").read_text()
    result = post(owner, path + "/manage", {**body, "action": "rename", "new_key": "renamed.yaml"})
    assert result.status_code == 200
    path = "/api/workflows/renamed.yaml"
    body["base_hash"] = owner.get(path).json()["base_hash"]
    assert post(owner, path + "/manage", {**body, "action": "disable"}).status_code == 200
    disabled = next(
        row
        for row in owner.get("/api/workflows").json()["workflows"]
        if row["key"] == "renamed.yaml"
    )
    assert disabled["disabled"] is True
    assert (
        post(owner, "/api/runs", {"workflow_key": "renamed.yaml", "inputs": {}}).status_code == 409
    )
    assert post(owner, path + "/manage", {**body, "action": "enable"}).status_code == 200
    assert not WorkflowControl.objects.get(workflow_key="renamed.yaml").disabled
    assert post(owner, path + "/manage", {**body, "action": "delete"}).status_code == 400
    assert (
        post(owner, path + "/manage", {**body, "action": "delete", "confirmed": True}).status_code
        == 200
    )
    assert owner.get(path).status_code == 404
    assert (project.repository / ".relay/prompts/shared.md").read_text() == "Shared instructions\n"


@pytest.mark.parametrize("action", ["rename", "delete"])
def test_referenced_workflows_cannot_be_removed(
    owner: Client, project: RelayProject, action: str
) -> None:
    project.write(
        ".relay/workflows/parent.yaml", "jobs:\n  reuse:\n    uses: ./.relay/workflows/check.yaml\n"
    )
    path = "/api/workflows/check.yaml"
    post(owner, path + "/lease", {"holder": "tab"})
    result = post(
        owner,
        path + "/manage",
        {
            "action": action,
            "holder": "tab",
            "base_hash": owner.get(path).json()["base_hash"],
            "new_key": "new.yaml",
            "confirmed": True,
        },
    )
    assert result.status_code == 409
    assert "parent.yaml" in result.json()["message"]
    assert (project.repository / ".relay/workflows/check.yaml").exists()


@pytest.mark.parametrize("event", ["schedule", "push", "repository_dispatch"])
@pytest.mark.parametrize("enabled", [True, False], ids=["active", "already-disabled"])
def test_rename_disables_triggers_and_preserves_delivery_history_until_new_activation(
    owner: Client,
    project: RelayProject,
    engine: InlineEngine,
    clock: Clock,
    event: str,
    enabled: bool,
) -> None:
    project.write_workflow(
        "check",
        "on: {schedule: [{cron: '* * * * *'}], push: {branches: [main]}, "
        "repository_dispatch: {types: [build]}}\n"
        "jobs: {check: {steps: [{run: echo Ready}]}}\n",
    )
    activation = {"key": "check.yaml", "event": event, "enabled": True, "allow_writers": True}
    assert post(owner, "/api/workflow-triggers", activation).status_code == 200
    trigger = WorkflowTrigger.objects.get(workflow_key="check.yaml", event=event)
    head = git(project.repository, "rev-parse", "HEAD")
    payload = {"event_name": event, "ref": "refs/heads/main", "sha": head}
    deliver(trigger, "completed-before-rename", payload)
    historical = TriggerDelivery.objects.get(occurrence="completed-before-rename")
    launch_delivery(historical)
    historical.refresh_from_db()
    assert historical.state == "launched", historical.reason
    engine.drain(str(historical.run_id))
    assert Run.objects.get(pk=historical.run_id).status == "succeeded"
    deliver(trigger, "pending-before-rename", payload)
    pending = TriggerDelivery.objects.get(occurrence="pending-before-rename")
    if not enabled:
        assert (
            post(owner, "/api/workflow-triggers", {**activation, "enabled": False}).status_code
            == 200
        )
    trigger.refresh_from_db()
    trigger.cursor = {"at": timezone.now().isoformat(), "refs": local_refs(project.repository)}
    trigger.save(update_fields=["cursor"])
    evidence = (
        trigger.source_hash,
        trigger.config,
        trigger.cursor,
        trigger.activated_at,
        trigger.allow_writers,
    )
    path = "/api/workflows/check.yaml"
    assert post(owner, path + "/lease", {"holder": "tab"}).status_code == 200
    response = post(
        owner,
        path + "/manage",
        {
            "action": "rename",
            "holder": "tab",
            "base_hash": owner.get(path).json()["base_hash"],
            "new_key": "renamed.yaml",
        },
    )
    assert response.status_code == 200, response.content
    trigger.refresh_from_db()
    assert trigger.enabled is False
    assert trigger.workflow_key == "check.yaml"
    assert (
        trigger.source_hash,
        trigger.config,
        trigger.cursor,
        trigger.activated_at,
        trigger.allow_writers,
    ) == evidence
    assert not WorkflowTrigger.objects.filter(workflow_key="renamed.yaml").exists()
    project.commit("Record the owner rename")
    clock.advance(120)
    assert (
        post(
            owner,
            "/api/repository-dispatch",
            {
                "event_type": "build",
                "idempotency_key": "while-disabled",
                "client_payload": {},
            },
        ).status_code
        == 200
    )
    reconcile()
    pending.refresh_from_db()
    historical.refresh_from_db()
    trigger.refresh_from_db()
    assert pending.state == "pending" and pending.run_id is None
    assert historical.state == "launched"
    assert historical.trigger_id == pending.trigger_id == trigger.pk
    assert Run.objects.get(pk=historical.run_id).workflow_key == "check.yaml"
    assert TriggerDelivery.objects.count() == 2 and Run.objects.count() == 1
    assert trigger.cursor == evidence[2]

    assert (
        post(
            owner,
            "/api/workflow-triggers",
            {
                **activation,
                "key": "renamed.yaml",
            },
        ).status_code
        == 200
    )
    renamed = WorkflowTrigger.objects.get(workflow_key="renamed.yaml", event=event)
    assert renamed.pk != trigger.pk and renamed.enabled
    assert renamed.activated_at > trigger.activated_at
    if event == "schedule":
        clock.advance(60)
    elif event == "push":
        project.write("after-activation.txt", "Observed after activation\n")
        project.commit("Change the local branch after new activation")
    else:
        assert (
            post(
                owner,
                "/api/repository-dispatch",
                {
                    "event_type": "build",
                    "idempotency_key": "after-activation",
                    "client_payload": {},
                },
            ).status_code
            == 200
        )
    reconcile()
    launched = TriggerDelivery.objects.get(trigger=renamed)
    assert launched.state == "launched", launched.reason
    engine.drain(str(launched.run_id))
    run = Run.objects.get(pk=launched.run_id)
    assert run.workflow_key == "renamed.yaml" and run.status == "succeeded"
    pending.refresh_from_db()
    assert pending.state == "pending" and pending.run_id is None


def test_rename_keeps_retained_target_trigger_records_separate(
    owner: Client,
    project: RelayProject,
) -> None:
    source = "on: repository_dispatch\n" + SOURCE
    project.write_workflow("check", source)
    project.write_workflow("renamed", source)
    activation = {
        "key": "renamed.yaml",
        "event": "repository_dispatch",
        "enabled": False,
        "allow_writers": False,
    }
    assert post(owner, "/api/workflow-triggers", activation).status_code == 200
    retained = WorkflowTrigger.objects.get(workflow_key="renamed.yaml")
    deliver(retained, "retained-target", {"event_name": "repository_dispatch"})
    target_evidence = (retained.source_hash, retained.cursor, retained.activated_at)
    target = "/api/workflows/renamed.yaml"
    assert post(owner, target + "/lease", {"holder": "tab"}).status_code == 200
    assert (
        post(
            owner,
            target + "/manage",
            {
                "action": "delete",
                "holder": "tab",
                "confirmed": True,
                "base_hash": owner.get(target).json()["base_hash"],
            },
        ).status_code
        == 200
    )
    assert post(owner, target + "/lease/release", {"holder": "tab"}).status_code == 200
    assert (
        post(
            owner,
            "/api/workflow-triggers",
            {
                **activation,
                "key": "check.yaml",
                "enabled": True,
                "allow_writers": True,
            },
        ).status_code
        == 200
    )
    old = WorkflowTrigger.objects.get(workflow_key="check.yaml")
    path = "/api/workflows/check.yaml"
    assert post(owner, path + "/lease", {"holder": "tab"}).status_code == 200
    assert (
        post(
            owner,
            path + "/manage",
            {
                "action": "rename",
                "holder": "tab",
                "new_key": "renamed.yaml",
                "base_hash": owner.get(path).json()["base_hash"],
            },
        ).status_code
        == 200
    )
    old.refresh_from_db()
    retained.refresh_from_db()
    assert not old.enabled and not retained.enabled
    assert old.workflow_key == "check.yaml" and retained.workflow_key == "renamed.yaml"
    assert (retained.source_hash, retained.cursor, retained.activated_at) == target_evidence
    assert TriggerDelivery.objects.get(occurrence="retained-target").trigger_id == retained.pk
    assert WorkflowTrigger.objects.count() == 2
