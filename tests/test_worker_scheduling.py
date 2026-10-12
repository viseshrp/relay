"""Web commits intent; the single Huey consumer schedules and delivers it."""

from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.test import Client
import pytest

from relay.config import validate_config
from relay.execution import huey_app
from relay.execution.dispatch import set_dispatch_notifier
from relay.execution.launch import LaunchRequest, launch_workflow
from relay.execution.nodes import node_executors
from relay.web.actions_repository import approve_environment
from relay.web.models import DispatchClaim, HumanInteraction, NodeRun, RunEvent, WorkflowEnvironment
from relay.web.repositories import DjangoExecutionStore
from tests.sqlite_support import SqliteWriteProbe
from tests.support import InlineEngine, RelayProject


def test_launch_commits_no_scheduler_work_until_the_worker_advances(
    project: RelayProject, monkeypatch: pytest.MonkeyPatch
) -> None:
    project.write_workflow("queued", "name: Queued\njobs: {main: {steps: [{run: echo ready}]}}\n")
    queued: list[str] = []
    result = launch_workflow(
        DjangoExecutionStore(),
        project.relay_root,
        project.project_id,
        LaunchRequest("queued.yaml", {}, None, "retain", None, (), "owner"),
        queued.append,
    )
    assert not queued
    assert not DispatchClaim.objects.exists()
    assert not RunEvent.objects.filter(type__in=("node.ready", "node.dispatched")).exists()
    assert NodeRun.objects.get(run_id=result.run_id).status == "pending"
    monkeypatch.setattr(huey_app, "enqueue_claim", queued.append)
    huey_app._advance_changed_runs(DjangoExecutionStore())
    assert queued
    assert NodeRun.objects.get(run_id=result.run_id).status == "dispatched"


def test_environment_resume_is_delivered_from_committed_events(
    project: RelayProject, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    WorkflowEnvironment.objects.create(
        project_id=project.project_id, name="prod", approval_required=True
    )
    project.write_workflow(
        "gate",
        "name: Gate\njobs:\n  main:\n    environment: prod\n"
        "    steps: [{uses: relay/human-wait@v1, with: {prompt: Continue?}}]\n",
    )
    engine = InlineEngine(node_executors(), tmp_path / "artifacts")
    run_id = engine.launch(project, "gate")
    engine.drain(run_id)
    interaction = HumanInteraction.objects.get(run_id=run_id, status="pending")
    set_dispatch_notifier(None)
    assert approve_environment(str(interaction.attempt_id))
    queued: list[str] = []
    monkeypatch.setattr(huey_app, "enqueue_claim", queued.append)
    huey_app._advance_changed_runs(engine.store)
    assert queued
    claim = DispatchClaim.objects.get(claim_token=queued[0])
    assert str(claim.attempt_id) == str(interaction.attempt_id)


def test_idle_worker_scheduling_takes_no_write_lock() -> None:
    with SqliteWriteProbe() as probe:
        for _ in range(10):
            huey_app._advance_changed_runs(DjangoExecutionStore())
    assert probe.transactions == probe.autocommit_writes == 0


def test_legacy_worker_count_warns_and_uses_one(caplog: pytest.LogCaptureFixture) -> None:
    assert validate_config({"workers": 8}).workers == 1
    assert "one worker" in caplog.text


def test_settings_api_rejects_new_parallel_worker_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "RELAY_LOGIN_REQUIRED", False)
    client = Client()
    current = client.get("/api/settings").json()
    response = client.post(
        "/api/settings",
        data=json.dumps({"settings": {"workers": 2}, "revision": current["revision"]}),
        content_type="application/json",
    )
    assert response.status_code == 422
    assert response.json()["code"] == "config_error"
    assert client.get("/api/settings").json()["settings"]["workers"] == 1


def test_startup_enumerates_every_active_run_beyond_one_reconciliation_page(
    project: RelayProject,
) -> None:
    from relay.web.models import Run

    Run.objects.bulk_create(
        [
            Run(
                project_id=project.project_id,
                workflow_key="queued.yaml",
                status="running",
                source_commit="0" * 40,
                recorded_head="0" * 40,
                run_branch=f"relay/queued-{index}",
                worktree_path=str(project.repository / f"queued-{index}"),
                launcher="owner",
            )
            for index in range(205)
        ]
    )
    assert len(DjangoExecutionStore().active_run_ids()) == 205
